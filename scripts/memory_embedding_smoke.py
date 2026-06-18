#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.plugins.yangyang.memory.embedding import EmbeddingConfig, MemoryEmbeddingIndex, OpenAIEmbeddingClient
from src.plugins.yangyang.memory.types import LongTermMemoryEntry


def main() -> int:
    ap = argparse.ArgumentParser(description="YangYang long-term memory embo-01 embedding smoke tool")
    ap.add_argument("--memory-root", default="src/plugins/yangyang/data/memory")
    ap.add_argument("--index", default="src/plugins/yangyang/data/memory/long_term/embeddings_embo01.jsonl")
    ap.add_argument("--base-url", default="http://127.0.0.1:18001/v1/embeddings")
    ap.add_argument("--query", default="阿漂说加班时什么时候问结束")
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--top-k", type=int, default=5)
    args = ap.parse_args()

    memory_file = Path(args.memory_root) / "long_term" / "memories.jsonl"
    entries = []
    for line in memory_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            entries.append(LongTermMemoryEntry.from_dict(json.loads(line)))
    client = OpenAIEmbeddingClient(EmbeddingConfig(enabled=True, base_url=args.base_url, model="embo-01"))
    index = MemoryEmbeddingIndex(args.index, client)
    result = {"entries": len(entries), "index": args.index}
    if args.rebuild:
        result["rebuild"] = index.rebuild(entries)
    hits = index.search(entries, args.query, user_id="335059272", top_k=args.top_k)
    result["query"] = args.query
    result["hits"] = [{"id": entry.id, "score": score, "slot": entry.slot, "summary": entry.summary[:120]} for entry, score in hits]
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
