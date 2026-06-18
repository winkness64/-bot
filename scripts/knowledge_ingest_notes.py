#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE_SOURCE_DIR = REPO_ROOT / "src/plugins/yangyang/data/knowledge/sources"
OUTPUT_PATH = KNOWLEDGE_SOURCE_DIR / "yangyang_notes_digest.md"
EXCLUDE_NAME_KEYWORDS = ("亲密日志", "intimate", "亲密")
SOURCE_CANDIDATES = [
    Path("/mnt/warehouse/astrbot_yangyang/data/永久记忆库.txt"),
    Path("/mnt/warehouse/astrbot_yangyang/data/永久记忆库_私密.txt"),
    Path("/mnt/warehouse/astrbot_yangyang/data/workspaces/project_notes/秧秧_工作日记.md"),
    Path("/mnt/warehouse/astrbot_yangyang/data/workspaces/project_notes/秧秧_侦察报告.md"),
    REPO_ROOT / "src/plugins/yangyang/data/memory/long_term/memories.jsonl",
]
PROJECT_NOTES_DIR = Path("/mnt/warehouse/astrbot_yangyang/data/workspaces/project_notes")


def main() -> int:
    ap = argparse.ArgumentParser(description="Summarize YangYang notes and ingest digest into knowledge base")
    ap.add_argument("--no-ingest", action="store_true")
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    sources = collect_sources()
    digest = build_digest(sources)
    KNOWLEDGE_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(digest, encoding="utf-8")
    result = {"ok": True, "digest": str(OUTPUT_PATH), "sources": [str(x) for x in sources], "chars": len(digest)}

    if not args.no_ingest:
        removed = remove_existing_digest_docs()
        if removed:
            result["removed_old_digest_docs"] = removed
        ingest_result = run_cli(["ingest", str(OUTPUT_PATH), "--title", "秧秧笔记归纳摘要", "--tags", "yangyang,notes,digest,runbook,memory-summary"])
        result["ingest"] = ingest_result
        if args.rebuild:
            result["rebuild"] = run_cli(["rebuild"])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


def collect_sources() -> list[Path]:
    paths: list[Path] = []
    for path in SOURCE_CANDIDATES:
        if path.exists() and path.is_file() and not excluded(path):
            paths.append(path)
    if PROJECT_NOTES_DIR.exists():
        for path in sorted(PROJECT_NOTES_DIR.iterdir()):
            if not path.is_file() or excluded(path):
                continue
            if path.suffix.lower() not in {".md", ".txt", ".json", ".jsonl"}:
                continue
            if path not in paths:
                paths.append(path)
    return paths


def excluded(path: Path) -> bool:
    name = path.name.casefold()
    return any(keyword.casefold() in name for keyword in EXCLUDE_NAME_KEYWORDS)


def build_digest(sources: list[Path]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts = [
        "# 秧秧笔记归纳摘要",
        "",
        f"生成时间：{now} CST",
        "",
        "用途：供知识库按需检索。本文是归纳摘要，不是长期记忆原文；默认不注入 prompt，只有显式查知识库时才参考。",
        "",
        "敏感日志排除规则：指定私密互动类日志不纳入。",
        "",
        "## 来源清单",
    ]
    for path in sources:
        parts.append(f"- `{path}`")
    parts.extend(["", "## 工作日记摘要"])
    for path in sources:
        if "工作日记" in path.name:
            parts.extend(summarize_markdown_log(path))
    parts.extend(["", "## 侦察报告摘要"])
    found_scout = False
    for path in sources:
        if "侦察" in path.name:
            found_scout = True
            parts.extend(summarize_plain_file(path, heading_prefix="侦察报告"))
    if not found_scout:
        parts.append("- 当前未发现侦察报告文件。")
    parts.extend(["", "## 永久记忆库摘要"])
    found_perm = False
    for path in sources:
        if path.name in {"永久记忆库.txt", "永久记忆库_私密.txt"}:
            found_perm = True
            parts.extend(summarize_plain_file(path, heading_prefix=path.stem))
    if not found_perm:
        parts.append("- 当前未发现 `/mnt/warehouse/astrbot_yangyang/data/永久记忆库.txt` 或 `/mnt/warehouse/astrbot_yangyang/data/永久记忆库_私密.txt`。")
    parts.extend(["", "## NoneBot 长期记忆目录摘要"])
    for path in sources:
        if path.name == "memories.jsonl":
            parts.extend(summarize_long_term_jsonl(path))
    return "\n".join(parts).strip() + "\n"


def summarize_markdown_log(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    text = re.sub(r"<!--\s*migrated_from_wrong_astrbot_path_20260614\s*-->", "", text)
    text = re.sub(r"^# 误写路径迁移记录\s*$", "", text, flags=re.M)
    text = re.sub(r"^以下内容.*?知识库整理时会去重保留有效条目。\s*$", "", text, flags=re.M)
    sections = re.split(r"(?=^##\s+)", text, flags=re.M)
    by_title: dict[str, list[str]] = {}
    order: list[str] = []
    for section in sections:
        section = section.strip()
        if not section:
            continue
        lines = section.splitlines()
        title = lines[0].strip("# ") if lines else path.name
        if not title or title.startswith("误写路径迁移记录"):
            continue
        bullets = dedupe_lines([line.strip() for line in lines[1:] if line.strip().startswith("-") and not text_has_excluded_sensitive_content(line)])[:14]
        if not bullets:
            continue
        if title not in by_title:
            order.append(title)
            by_title[title] = []
        by_title[title].extend(bullets)
        by_title[title] = dedupe_lines(by_title[title])[:18]
    items: list[str] = []
    for title in order[-28:]:
        items.append(f"### {title}")
        items.extend(by_title[title])
    return items or [f"- `{path}` 暂无可归纳条目。"]


def summarize_plain_file(path: Path, *, heading_prefix: str) -> list[str]:
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return [f"- {heading_prefix} 为空。"]
    lines = dedupe_lines([line.strip() for line in text.splitlines() if line.strip() and not text_has_excluded_sensitive_content(line)])
    picked = lines[-120:]
    result = [f"### {heading_prefix}"]
    for line in picked:
        safe = line[:420] + ("…" if len(line) > 420 else "")
        result.append(f"- {safe.lstrip('- ').strip()}")
    return result


def dedupe_lines(lines: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for line in lines:
        normalized = re.sub(r"\s+", " ", str(line or "").strip())
        normalized = normalize_known_corrections(normalized)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(normalized)
    return result


def summarize_long_term_jsonl(path: Path) -> list[str]:
    rows = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except Exception:
            continue
        if str(row.get("status") or "active") != "active":
            continue
        if row_has_excluded_sensitive_content(row):
            continue
        rows.append(row)
    by_kind = Counter(str(row.get("kind") or "unknown") for row in rows)
    by_scope = Counter(str(row.get("scope") or "unknown") for row in rows)
    tag_counter: Counter[str] = Counter()
    for row in rows:
        for tag in row.get("tags") or []:
            tag_counter[str(tag)] += 1
    result = [
        f"- active 长期记忆条目数：{len(rows)}。",
        "- kind 分布：" + ", ".join(f"{k}={v}" for k, v in by_kind.most_common(12)),
        "- scope 分布：" + ", ".join(f"{k}={v}" for k, v in by_scope.most_common(8)),
        "- 高频 tags：" + ", ".join(f"{k}={v}" for k, v in tag_counter.most_common(18)),
        "",
        "### 代表性长期记忆条目",
    ]
    for row in rows[-40:]:
        slot = str(row.get("slot") or row.get("id") or "未命名")
        summary = str(row.get("summary") or row.get("value") or "").replace("\n", " ")
        summary = summary[:220] + ("…" if len(summary) > 220 else "")
        tags = ",".join(str(x) for x in (row.get("tags") or [])[:5])
        result.append(f"- {slot}：{summary}（tags: {tags}）")
    return result


def normalize_known_corrections(text: str) -> str:
    value = str(text or "")
    if "embo-01" in value or "embeddings" in value:
        value = value.replace("向量维度为 1024", "向量维度为 1536")
        value = value.replace("向量维度 1024", "向量维度 1536")
        value = value.replace("embo-01 1024维", "embo-01 1536维")
        value = value.replace("MiniMax embo-01 1024维", "MiniMax embo-01 1536维")
    return value


def text_has_excluded_sensitive_content(text: str) -> bool:
    haystack = str(text or "").casefold()
    blocked = ("亲密日志", "亲密互动", "亲密摘要", "intimacy", "露骨", "浴室", "浴缸")
    return any(token.casefold() in haystack for token in blocked)


def remove_existing_digest_docs() -> list[str]:
    docs_dir = REPO_ROOT / "src/plugins/yangyang/data/knowledge/docs"
    removed: list[str] = []
    if not docs_dir.exists():
        return removed
    for path in sorted(docs_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if str(data.get("title") or "") == "秧秧笔记归纳摘要":
            path.unlink()
            removed.append(str(path))
    return removed


def row_has_excluded_sensitive_content(row: dict) -> bool:
    haystack = " ".join(
        [
            str(row.get("id") or ""),
            str(row.get("slot") or ""),
            str(row.get("summary") or ""),
            str(row.get("value") or ""),
            " ".join(str(x) for x in (row.get("tags") or [])),
        ]
    ).casefold()
    blocked = ("亲密日志", "亲密互动", "intimacy", "露骨", "浴室", "浴缸")
    return any(token.casefold() in haystack for token in blocked)


def run_cli(args: list[str]) -> dict:
    cmd = [str(REPO_ROOT / ".venv/bin/python"), str(REPO_ROOT / "scripts/knowledge_cli.py"), *args]
    proc = subprocess.run(cmd, cwd=REPO_ROOT, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        return {"ok": False, "returncode": proc.returncode, "stdout": proc.stdout, "stderr": proc.stderr}
    try:
        return json.loads(proc.stdout)
    except Exception:
        return {"ok": True, "stdout": proc.stdout}


if __name__ == "__main__":
    raise SystemExit(main())
