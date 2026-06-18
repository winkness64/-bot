#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import asdict
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.plugins.yangyang.knowledge import KnowledgeBase, KnowledgeConfig


def main() -> int:
    ap = argparse.ArgumentParser(description="YangYang embo-01 knowledge base CLI")
    ap.add_argument("action", choices=["ingest", "rebuild", "search", "stats"])
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--root", default="src/plugins/yangyang/data/knowledge")
    ap.add_argument("--title", default="")
    ap.add_argument("--tags", default="")
    ap.add_argument("--query", default="")
    ap.add_argument("--top-k", type=int, default=3)
    ap.add_argument("--chunk-chars", type=int, default=700)
    ap.add_argument("--overlap-chars", type=int, default=120)
    args = ap.parse_args()

    kb = KnowledgeBase(KnowledgeConfig(enabled=True, root_dir=Path(args.root), top_k=args.top_k))
    tags = [x.strip() for x in args.tags.split(",") if x.strip()]
    if args.action == "ingest":
        results = [kb.ingest_path(path, title=args.title, tags=tags) for path in args.paths]
        print(json.dumps({"ok": True, "results": results}, ensure_ascii=False, indent=2))
        return 0
    if args.action == "rebuild":
        print(json.dumps(kb.rebuild_index(chunk_chars=args.chunk_chars, overlap_chars=args.overlap_chars), ensure_ascii=False, indent=2))
        return 0
    if args.action == "search":
        hits = kb.search(args.query, top_k=args.top_k)
        print(json.dumps({"ok": True, "query": args.query, "hits": [asdict(h) for h in hits]}, ensure_ascii=False, indent=2))
        return 0
    docs = kb.load_documents()
    index_lines = sum(1 for _ in kb.index_path.open(encoding="utf-8")) if kb.index_path.exists() else 0
    print(json.dumps({"ok": True, "docs": len(docs), "chunks": index_lines, "root": str(kb.root_dir)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
