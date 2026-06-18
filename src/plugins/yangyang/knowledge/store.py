from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from loguru import logger

from ..memory.embedding import EmbeddingConfig, OpenAIEmbeddingClient, cosine_similarity
from ..memory.retrieval import MemoryRetriever


@dataclass(slots=True, frozen=True)
class KnowledgeConfig:
    enabled: bool = False
    root_dir: Path = Path("src/plugins/yangyang/data/knowledge")
    top_k: int = 3
    char_budget: int = 900
    min_score: float = 0.18
    owner_private_only: bool = True

    @classmethod
    def from_env(cls, cfg: dict[str, Any] | None = None) -> "KnowledgeConfig":
        data = cfg or {}
        root = data.get("knowledge_root_dir") or os.getenv("YANGYANG_KNOWLEDGE_ROOT_DIR") or "src/plugins/yangyang/data/knowledge"
        return cls(
            enabled=_bool(data.get("knowledge_enabled", os.getenv("YANGYANG_KNOWLEDGE_ENABLED", "0"))),
            root_dir=Path(str(root)),
            top_k=max(1, int(data.get("knowledge_top_k") or os.getenv("YANGYANG_KNOWLEDGE_TOP_K") or 3)),
            char_budget=max(200, int(data.get("knowledge_char_budget") or os.getenv("YANGYANG_KNOWLEDGE_CHAR_BUDGET") or 900)),
            min_score=float(data.get("knowledge_min_score") or os.getenv("YANGYANG_KNOWLEDGE_MIN_SCORE") or 0.18),
            owner_private_only=_bool(data.get("knowledge_owner_private_only", os.getenv("YANGYANG_KNOWLEDGE_OWNER_PRIVATE_ONLY", "1"))),
        )


@dataclass(slots=True, frozen=True)
class KnowledgeHit:
    doc_id: str
    chunk_id: str
    title: str
    source_path: str
    text: str
    score: float
    tags: tuple[str, ...] = ()


class KnowledgeBase:
    """Small embo-01 backed knowledge base, separate from long-term memory."""

    def __init__(self, config: KnowledgeConfig | None = None, client: OpenAIEmbeddingClient | None = None):
        self.config = config or KnowledgeConfig.from_env()
        self.root_dir = self.config.root_dir
        self.docs_dir = self.root_dir / "docs"
        self.sources_dir = self.root_dir / "sources"
        self.index_path = self.root_dir / "index_embo01.jsonl"
        self.manifest_path = self.root_dir / "manifest.json"
        self.client = client or OpenAIEmbeddingClient(EmbeddingConfig.from_env({"memory_embedding_enabled": True}))
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.sources_dir.mkdir(parents=True, exist_ok=True)

    def ingest_path(self, source_path: str | Path, *, title: str = "", tags: list[str] | None = None) -> dict[str, Any]:
        path = Path(source_path)
        if not path.exists() or not path.is_file():
            raise FileNotFoundError(str(path))
        text = _read_text_file(path)
        doc_id = _stable_id(str(path.resolve()) + "\n" + hashlib.sha256(text.encode("utf-8")).hexdigest())
        payload = {
            "schema_version": 1,
            "doc_id": doc_id,
            "title": title or path.stem,
            "source_path": str(path),
            "tags": [str(x) for x in (tags or []) if str(x).strip()],
            "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "updated_at": _now(),
            "text": text,
        }
        doc_path = self.docs_dir / f"{doc_id}.json"
        doc_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "doc_id": doc_id, "title": payload["title"], "chars": len(text), "path": str(doc_path)}

    def load_documents(self) -> list[dict[str, Any]]:
        docs: list[dict[str, Any]] = []
        for path in sorted(self.docs_dir.glob("*.json")):
            try:
                docs.append(json.loads(path.read_text(encoding="utf-8")))
            except Exception:
                logger.warning("KnowledgeBase: failed to load doc %s", path)
        return docs

    def rebuild_index(self, *, chunk_chars: int = 700, overlap_chars: int = 120, batch_size: int = 12) -> dict[str, Any]:
        docs = self.load_documents()
        chunks: list[dict[str, Any]] = []
        for doc in docs:
            for idx, chunk_text in enumerate(_chunk_text(str(doc.get("text") or ""), chunk_chars=chunk_chars, overlap_chars=overlap_chars)):
                chunks.append({
                    "schema_version": 1,
                    "doc_id": str(doc.get("doc_id") or ""),
                    "chunk_id": f"{doc.get('doc_id')}:{idx}",
                    "title": str(doc.get("title") or ""),
                    "source_path": str(doc.get("source_path") or ""),
                    "tags": list(doc.get("tags") or []),
                    "text": chunk_text,
                })
        rows: list[dict[str, Any]] = []
        for offset in range(0, len(chunks), max(1, batch_size)):
            batch = chunks[offset : offset + max(1, batch_size)]
            vectors = self.client.embed_texts([_embedding_text(chunk) for chunk in batch])
            for chunk, vector in zip(batch, vectors):
                row = dict(chunk)
                row.update({"model": self.client.config.model, "dim": len(vector), "indexed_at": _now(), "embedding": vector})
                rows.append(row)
        tmp = self.index_path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        tmp.replace(self.index_path)
        manifest = {"docs": len(docs), "chunks": len(rows), "model": self.client.config.model, "updated_at": _now(), "index_path": str(self.index_path)}
        self.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, **manifest}

    def search(self, query: str, *, top_k: int | None = None, min_score: float | None = None) -> list[KnowledgeHit]:
        q = str(query or "").strip()
        if not q or not self.index_path.exists():
            return []
        query_vec = self.client.embed_text(q)
        limit = max(1, int(top_k or self.config.top_k))
        threshold = self.config.min_score if min_score is None else float(min_score)
        scored: list[KnowledgeHit] = []
        for row in _iter_jsonl(self.index_path):
            score = cosine_similarity(query_vec, [float(x) for x in row.get("embedding", [])])
            if score < threshold:
                continue
            scored.append(KnowledgeHit(
                doc_id=str(row.get("doc_id") or ""),
                chunk_id=str(row.get("chunk_id") or ""),
                title=str(row.get("title") or ""),
                source_path=str(row.get("source_path") or ""),
                text=str(row.get("text") or ""),
                score=round(score, 6),
                tags=tuple(str(x) for x in list(row.get("tags") or [])),
            ))
        scored.sort(key=lambda item: -item.score)
        return scored[:limit]

    def render_prompt_section(self, hits: list[KnowledgeHit], *, char_budget: int | None = None) -> str:
        if not hits:
            return ""
        budget = max(200, int(char_budget or self.config.char_budget))
        header = "[来自知识库的参考资料]"
        guard = "说明：以下是外部资料片段，只在与当前问题相关时参考；不要暴露检索、向量库、索引等内部机制；不确定时说明资料不足。"
        lines = [header, guard]
        remaining = budget - len(header) - len(guard) - 2
        for hit in hits:
            title = hit.title or hit.doc_id
            text = MemoryRetriever.sanitize_preview(hit.text, limit=360)
            line = f"- {title}：{text}"
            if remaining - len(line) - 1 <= 0:
                break
            lines.append(line)
            remaining -= len(line) + 1
        return "\n".join(lines)


def _read_text_file(path: Path) -> str:
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return json.dumps(data, ensure_ascii=False, indent=2)
        return json.dumps(data, ensure_ascii=False)
    return path.read_text(encoding="utf-8", errors="ignore")


def _chunk_text(text: str, *, chunk_chars: int, overlap_chars: int) -> list[str]:
    normalized = re.sub(r"\n{3,}", "\n\n", str(text or "").strip())
    if not normalized:
        return []
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", normalized) if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 <= chunk_chars:
            current = f"{current}\n\n{para}".strip() if current else para
            continue
        if current:
            chunks.append(current)
        if len(para) <= chunk_chars:
            current = para
        else:
            start = 0
            while start < len(para):
                chunks.append(para[start : start + chunk_chars].strip())
                start += max(1, chunk_chars - overlap_chars)
            current = ""
    if current:
        chunks.append(current)
    if overlap_chars > 0 and len(chunks) > 1:
        with_overlap: list[str] = []
        prev_tail = ""
        for chunk in chunks:
            merged = f"{prev_tail}\n{chunk}".strip() if prev_tail else chunk
            with_overlap.append(merged[-chunk_chars:])
            prev_tail = chunk[-overlap_chars:]
        return with_overlap
    return chunks


def _embedding_text(chunk: dict[str, Any]) -> str:
    tags = " ".join(str(x) for x in list(chunk.get("tags") or []))
    return "\n".join(x for x in [str(chunk.get("title") or ""), tags, str(chunk.get("text") or "")] if x)


def _iter_jsonl(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except Exception:
            continue


def _stable_id(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime())


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
