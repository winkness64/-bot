#!/usr/bin/env python3
"""C4 closure cleanup helper for 2026-06-04.

Safely cleans dirty favorite_game memories produced by question sentences such as
"我晚上喜欢打什么游戏" while preserving/rebuilding a clean "打绝区零" entry when
there is clean evidence.

Usage:
  python scripts/clean_c4_dirty_memories_20260604.py \
    --memory-root src/plugins/yangyang/data/memory

The script always creates backups under <project>/backups by default.
"""
from __future__ import annotations

import argparse
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

QUESTION_MARKERS = ("什么", "啥", "哪个", "哪款", "哪种", "谁", "多少", "吗", "么", "？", "?")
DIRTY_VALUES = {"打什么", "打什么游戏"}
DIRTY_IDS = {"mem_b7217c1c2a40"}
CLEAN_ZZZ_TEXTS = {"我晚上一般喜欢打绝区零", "我晚上最喜欢打绝区零"}


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    tmp.replace(path)


def _has_question_evidence(row: dict[str, Any]) -> bool:
    for ev in row.get("evidence") or []:
        text = str(ev.get("text") or "")
        if any(marker in text for marker in QUESTION_MARKERS):
            return True
    return False


def _collect_clean_zzz_evidence(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    evidence: list[dict[str, str]] = []
    seen_text: set[str] = set()
    for row in rows:
        for ev in row.get("evidence") or []:
            text = str(ev.get("text") or "").strip()
            if text not in CLEAN_ZZZ_TEXTS or text in seen_text:
                continue
            evidence.append({
                "message_id": str(ev.get("message_id") or ""),
                "timestamp": str(ev.get("timestamp") or ""),
                "speaker_id": str(ev.get("speaker_id") or "335059272"),
                "text": text,
            })
            seen_text.add(text)
    return evidence


def _dedupe_by_id_keep_last(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for idx, row in enumerate(rows):
        row_id = str(row.get("id") or f"__noid_{idx}")
        if row_id not in by_id:
            order.append(row_id)
        by_id[row_id] = row
    return [by_id[row_id] for row_id in order]


def clean(memory_root: Path, backups_dir: Path) -> dict[str, Any]:
    memories_path = memory_root / "long_term" / "memories.jsonl"
    if not memories_path.exists():
        raise FileNotFoundError(memories_path)

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    backups_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backups_dir / f"memories.jsonl.bak_c4_closure_20260604-{ts}"
    removed_path = backups_dir / f"removed_dirty_memories_c4_closure_20260604-{ts}.jsonl"
    shutil.copy2(memories_path, backup_path)

    rows = _load_jsonl(memories_path)
    clean_zzz_evidence = _collect_clean_zzz_evidence(rows)

    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for row in rows:
        value = str(row.get("value") or "").strip()
        row_id = str(row.get("id") or "")
        slot = str(row.get("slot") or "")
        dirty = (
            value in DIRTY_VALUES
            or row_id in DIRTY_IDS
            or (slot == "favorite_game" and _has_question_evidence(row))
        )
        if dirty:
            removed.append(row)
            continue
        kept.append(row)

    kept = _dedupe_by_id_keep_last(kept)
    has_clean_zzz = any(row.get("slot") == "favorite_game" and row.get("value") == "打绝区零" for row in kept)
    if not has_clean_zzz and len(clean_zzz_evidence) >= 2:
        now = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
        kept.append({
            "id": "mem_clean_favorite_game_zzz_20260604",
            "status": "active",
            "scope": "private_user",
            "scope_id": "335059272",
            "session_id": "private:335059272",
            "user_id": "335059272",
            "group_id": "",
            "channel": "private",
            "kind": "preference",
            "slot": "favorite_game",
            "value": "打绝区零",
            "summary": "用户说：打绝区零",
            "evidence": clean_zzz_evidence[:2],
            "confidence": 0.78,
            "support_count": 2,
            "contradiction_count": 0,
            "source": "rule_promotion_cleaned",
            "tags": ["preference", "game", "private"],
            "created_at": clean_zzz_evidence[0].get("timestamp") or now,
            "updated_at": now,
            "last_seen_at": now,
        })

    _write_jsonl(removed_path, removed)
    _write_jsonl(memories_path, kept)
    return {
        "memories_path": str(memories_path),
        "backup_path": str(backup_path),
        "removed_path": str(removed_path),
        "before_rows": len(rows),
        "removed_rows": len(removed),
        "after_rows": len(kept),
        "favorite_game_values_after": [row.get("value") for row in kept if row.get("slot") == "favorite_game"],
        "dirty_values_after": [row.get("value") for row in kept if str(row.get("value") or "").strip() in DIRTY_VALUES],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memory-root", default="src/plugins/yangyang/data/memory")
    parser.add_argument("--backups-dir", default="backups")
    args = parser.parse_args()
    result = clean(Path(args.memory_root).resolve(), Path(args.backups_dir).resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
