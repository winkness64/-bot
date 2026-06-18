from __future__ import annotations

import json
import math
import os
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .types import LongTermMemoryEntry


@dataclass(slots=True, frozen=True)
class EmbeddingConfig:
    enabled: bool = False
    base_url: str = "http://127.0.0.1:18001/v1/embeddings"
    api_key_env: str = ""
    model: str = "embo-01"
    vector_dim: int = 1024
    timeout_seconds: int = 30

    @classmethod
    def from_env(cls, cfg: dict[str, Any] | None = None) -> "EmbeddingConfig":
        data = cfg or {}
        return cls(
            enabled=_bool(data.get("memory_embedding_enabled", os.getenv("YANGYANG_MEMORY_EMBEDDING_ENABLED", "0"))),
            base_url=str(data.get("memory_embedding_base_url") or os.getenv("YANGYANG_MEMORY_EMBEDDING_BASE_URL") or "http://127.0.0.1:18001/v1/embeddings"),
            api_key_env=str(data.get("memory_embedding_api_key_env") or os.getenv("YANGYANG_MEMORY_EMBEDDING_API_KEY_ENV") or ""),
            model=str(data.get("memory_embedding_model") or os.getenv("YANGYANG_MEMORY_EMBEDDING_MODEL") or "embo-01"),
            vector_dim=int(data.get("memory_embedding_vector_dim") or os.getenv("YANGYANG_MEMORY_EMBEDDING_VECTOR_DIM") or 1024),
            timeout_seconds=int(data.get("memory_embedding_timeout_seconds") or os.getenv("YANGYANG_MEMORY_EMBEDDING_TIMEOUT_SECONDS") or 30),
        )


class OpenAIEmbeddingClient:
    """OpenAI-compatible embedding client for the local embo-01 proxy."""

    def __init__(self, config: EmbeddingConfig | None = None):
        self.config = config or EmbeddingConfig.from_env()

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        clean = [str(text or "") for text in texts]
        if not clean:
            return []
        payload = {"model": self.config.model, "input": clean}
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.config.api_key_env:
            key = os.getenv(self.config.api_key_env, "")
            if key:
                headers["Authorization"] = f"Bearer {key}"
        req = urllib.request.Request(self.config.base_url, data=body, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.config.timeout_seconds) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        vectors = [item.get("embedding") for item in sorted(data.get("data", []), key=lambda x: int(x.get("index", 0)))]
        return [[float(x) for x in vec] for vec in vectors if isinstance(vec, list)]

    def embed_text(self, text: str) -> list[float]:
        vectors = self.embed_texts([text])
        return vectors[0] if vectors else []


def memory_embedding_text(entry: LongTermMemoryEntry) -> str:
    tags = " ".join(entry.tags or [])
    return "\n".join(
        part for part in [entry.kind, entry.slot, entry.summary or entry.value, entry.value, tags] if part
    )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    ln = math.sqrt(sum(a * a for a in left))
    rn = math.sqrt(sum(b * b for b in right))
    if ln <= 0 or rn <= 0:
        return 0.0
    return dot / (ln * rn)


class MemoryEmbeddingIndex:
    """Small JSONL vector sidecar for long-term memory semantic retrieval.

    This is intentionally independent from the production keyword retriever. It can be rebuilt
    and queried without changing prompt injection behavior.
    """

    def __init__(self, index_path: str | Path, client: OpenAIEmbeddingClient | None = None):
        self.index_path = Path(index_path)
        self.client = client or OpenAIEmbeddingClient()

    def load(self) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        if not self.index_path.exists():
            return out
        for line in self.index_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            mem_id = str(row.get("id") or "")
            if mem_id:
                out[mem_id] = row
        return out

    def rebuild(self, entries: list[LongTermMemoryEntry], *, batch_size: int = 16) -> dict[str, Any]:
        active = [entry for entry in entries if entry.status == "active"]
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        rows: list[dict[str, Any]] = []
        for offset in range(0, len(active), max(1, batch_size)):
            batch = active[offset : offset + max(1, batch_size)]
            vectors = self.client.embed_texts([memory_embedding_text(entry) for entry in batch])
            for entry, vector in zip(batch, vectors):
                rows.append({
                    "id": entry.id,
                    "scope": entry.scope,
                    "scope_id": entry.scope_id,
                    "kind": entry.kind,
                    "slot": entry.slot,
                    "model": self.client.config.model,
                    "dim": len(vector),
                    "updated_at": entry.updated_at or entry.created_at,
                    "indexed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime()),
                    "embedding": vector,
                })
        tmp = self.index_path.with_suffix(".jsonl.tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
        tmp.replace(self.index_path)
        return {"ok": True, "indexed": len(rows), "path": str(self.index_path), "model": self.client.config.model}

    def search(
        self,
        entries: list[LongTermMemoryEntry],
        query: str,
        *,
        user_id: str = "",
        group_id: str = "",
        top_k: int = 5,
    ) -> list[tuple[LongTermMemoryEntry, float]]:
        by_id = {entry.id: entry for entry in entries if entry.status == "active"}
        index = self.load()
        query_vec = self.client.embed_text(str(query or ""))
        scored: list[tuple[LongTermMemoryEntry, float]] = []
        for mem_id, row in index.items():
            entry = by_id.get(mem_id)
            if entry is None:
                continue
            if entry.scope == "private_user" and entry.scope_id != user_id:
                continue
            if entry.scope == "group_shared" and entry.scope_id != group_id:
                continue
            if entry.scope == "group_user" and group_id and user_id:
                if entry.scope_id != f"{group_id}:{user_id}":
                    continue
            score = cosine_similarity(query_vec, [float(x) for x in row.get("embedding", [])])
            scored.append((entry, round(score, 6)))
        scored.sort(key=lambda item: -item[1])
        return scored[: max(1, top_k)]


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
