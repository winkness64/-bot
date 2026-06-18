#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Literal

Expectation = Literal["yes", "no", "optional"]

OOLONG_TERM = "无糖乌龙茶"
PROJECT_STATUS_TERM = "被动记忆P0只做owner私聊最小灰度"
DEFAULT_FORBIDDEN_TERMS = (
    "我最近晚上常喝什么",
    "最近晚上常喝什么",
    "我去倒杯水",
    "倒杯水",
    "我宣布从今天开始每天吃键盘",
    "每天吃键盘",
    "吃键盘",
)
PIPELINE_LOG_MARKERS = (
    "MemoryPipeline: run_once",
    "Tasks: pipeline completed",
)
RETRIEVAL_LOG_MARKERS = (
    "MemoryStore[C4]: retrieved",
    "MemoryStore[C4]: rendered section",
)
CAPTURE_AUDIT_LOG_MARKERS = (
    "memory_capture_audit",
    "yangyang plugin: memory_capture_audit",
)


@dataclass(slots=True)
class CheckResult:
    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    observations: dict[str, Any] = field(default_factory=dict)

    def add_error(self, message: str) -> None:
        self.errors.append(message)
        self.ok = False

    def add_warning(self, message: str) -> None:
        self.warnings.append(message)


def load_jsonl_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                value = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{path}:{lineno}: invalid JSONL row: {exc}") from exc
            if isinstance(value, dict):
                rows.append(value)
            else:
                raise ValueError(f"{path}:{lineno}: JSONL row must be an object")
    return rows


def canonical_row_digest(row: dict[str, Any]) -> str:
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def diff_rows(current: list[dict[str, Any]], baseline: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if baseline is None:
        return list(current)
    baseline_hashes = {canonical_row_digest(row) for row in baseline}
    return [row for row in current if canonical_row_digest(row) not in baseline_hashes]


def row_text(row: dict[str, Any]) -> str:
    selected: list[str] = []
    for key in ("id", "status", "scope", "scope_id", "session_id", "user_id", "channel", "kind", "slot", "value", "summary", "source"):
        value = row.get(key)
        if value not in (None, "", [], {}):
            selected.append(str(value))
    evidence = row.get("evidence")
    if isinstance(evidence, list):
        for item in evidence:
            if isinstance(item, dict):
                for key in ("message_id", "timestamp", "text"):
                    value = item.get(key)
                    if value not in (None, "", [], {}):
                        selected.append(str(value))
    tags = row.get("tags")
    if isinstance(tags, list):
        selected.extend(str(item) for item in tags)
    selected.append(json.dumps(row, ensure_ascii=False, sort_keys=True))
    return "\n".join(selected)


def find_rows_containing(rows: Iterable[dict[str, Any]], term: str) -> list[dict[str, Any]]:
    needle = str(term or "")
    if not needle:
        return []
    return [row for row in rows if needle in row_text(row)]


def _read_log_file(path: Path, max_bytes: int) -> str:
    if not path.exists() or not path.is_file():
        return ""
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > max_bytes:
            fh.seek(max(0, size - max_bytes))
        data = fh.read(max_bytes)
    return data.decode("utf-8", errors="replace")


def read_log_text(path: Path, max_bytes_per_file: int = 2_000_000) -> str:
    if not path.exists():
        return ""
    if path.is_file():
        return _read_log_file(path, max_bytes_per_file)
    if not path.is_dir():
        return ""

    chunks: list[str] = []
    candidates = [p for p in path.iterdir() if p.is_file() and p.suffix.lower() in {".log", ".txt", ".jsonl", ""}]
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for item in candidates[:8]:
        text = _read_log_file(item, max_bytes_per_file // 2)
        if text:
            chunks.append(f"\n===== {item.name} =====\n{text}")
    return "\n".join(chunks)


def _expect_term(
    result: CheckResult,
    *,
    term: str,
    rows: list[dict[str, Any]],
    expectation: Expectation,
    label: str,
) -> None:
    matches = find_rows_containing(rows, term)
    result.observations[f"{label}_match_count"] = len(matches)
    if expectation == "yes" and not matches:
        result.add_error(f"required term not written in checked row set: {label}={term}")
    elif expectation == "no" and matches:
        ids = [str(row.get("id") or row.get("memory_id") or "<no-id>") for row in matches[:5]]
        result.add_error(f"forbidden term written in checked row set: {label}={term} ids={ids}")
    elif expectation == "optional" and not matches:
        result.add_warning(f"optional positive term not found: {label}={term}")


def run_check(
    *,
    memories_path: Path,
    log_path: Path,
    baseline_memories_path: Path | None = None,
    expect_oolong_written: Expectation = "optional",
    expect_project_written: Expectation = "optional",
    require_keywords: Iterable[str] = (),
    forbid_keywords: Iterable[str] = (),
    require_pipeline_log: bool = False,
    require_capture_audit_log: bool = False,
    require_retrieval_log: bool = False,
) -> CheckResult:
    result = CheckResult(ok=True)

    current_rows = load_jsonl_rows(memories_path)
    baseline_rows: list[dict[str, Any]] | None = None
    if baseline_memories_path is not None:
        baseline_rows = load_jsonl_rows(baseline_memories_path)
    else:
        result.add_warning("baseline memories.jsonl not provided; checks are against the full current file")

    checked_rows = diff_rows(current_rows, baseline_rows)
    result.observations.update(
        {
            "memories_path": str(memories_path),
            "baseline_memories_path": str(baseline_memories_path) if baseline_memories_path else "",
            "current_rows": len(current_rows),
            "baseline_rows": len(baseline_rows) if baseline_rows is not None else None,
            "checked_delta_rows": len(checked_rows),
        }
    )

    _expect_term(
        result,
        term=OOLONG_TERM,
        rows=checked_rows,
        expectation=expect_oolong_written,
        label="oolong",
    )
    _expect_term(
        result,
        term=PROJECT_STATUS_TERM,
        rows=checked_rows,
        expectation=expect_project_written,
        label="project_status",
    )

    for term in DEFAULT_FORBIDDEN_TERMS:
        matches = find_rows_containing(checked_rows, term)
        if matches:
            ids = [str(row.get("id") or row.get("memory_id") or "<no-id>") for row in matches[:5]]
            result.add_error(f"default forbidden test term was written: term={term} ids={ids}")

    for term in require_keywords:
        _expect_term(result, term=str(term), rows=checked_rows, expectation="yes", label=f"required:{term}")
    for term in forbid_keywords:
        _expect_term(result, term=str(term), rows=checked_rows, expectation="no", label=f"forbidden:{term}")

    log_text = read_log_text(log_path)
    result.observations["log_path"] = str(log_path)
    result.observations["log_bytes_read"] = len(log_text.encode("utf-8", errors="replace"))
    result.observations["log_has_raw_candidates"] = "raw_candidates" in log_text
    result.observations["log_has_promoted"] = "promoted=" in log_text or "\"promoted\"" in log_text
    result.observations["log_has_memory_pipeline"] = any(marker in log_text for marker in PIPELINE_LOG_MARKERS)
    result.observations["log_has_capture_audit"] = any(marker in log_text for marker in CAPTURE_AUDIT_LOG_MARKERS)
    result.observations["log_has_retrieval"] = "MemoryStore[C4]" in log_text

    if require_pipeline_log:
        if not result.observations["log_has_memory_pipeline"]:
            result.add_error("pipeline log marker not found")
        if not result.observations["log_has_raw_candidates"]:
            result.add_error("raw_candidates log marker not found")
        if not result.observations["log_has_promoted"]:
            result.add_error("promoted log marker not found")
    if require_capture_audit_log and not result.observations["log_has_capture_audit"]:
        result.add_error("memory_capture_audit log marker not found")
    if require_retrieval_log:
        if "MemoryStore[C4]" not in log_text:
            result.add_error("MemoryStore[C4] retrieval log marker not found")
        elif not any(marker in log_text for marker in RETRIEVAL_LOG_MARKERS):
            result.add_error("retrieval log lacks retrieved/rendered section marker")

    return result


def render_text_result(result: CheckResult) -> str:
    lines: list[str] = []
    lines.append("PASS passive_live_smoke_check" if result.ok else "FAIL passive_live_smoke_check")
    lines.append("observations:")
    for key in sorted(result.observations):
        lines.append(f"  - {key}: {result.observations[key]}")
    if result.warnings:
        lines.append("warnings:")
        lines.extend(f"  - {item}" for item in result.warnings)
    if result.errors:
        lines.append("errors:")
        lines.extend(f"  - {item}" for item in result.errors)
    return "\n".join(lines) + "\n"


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read-only checker for owner-private passive memory live smoke results."
    )
    parser.add_argument("--memories", required=True, help="Path to current long_term/memories.jsonl")
    parser.add_argument("--log", required=True, help="Path to live log file or a log directory")
    parser.add_argument("--baseline-memories", help="Optional pre-smoke memories.jsonl backup; checks only delta rows when provided")
    parser.add_argument(
        "--expect-oolong-written",
        choices=("yes", "no", "optional"),
        default="optional",
        help="Whether 无糖乌龙茶 must be written. Default optional supports no-write P0 smoke.",
    )
    parser.add_argument(
        "--expect-project-written",
        choices=("yes", "no", "optional"),
        default="optional",
        help="Whether the project-status sentence must be written. Default optional.",
    )
    parser.add_argument("--require-keyword", action="append", default=[], help="Additional keyword that must appear in delta memories")
    parser.add_argument("--forbid-keyword", action="append", default=[], help="Additional keyword that must not appear in delta memories")
    parser.add_argument("--require-pipeline-log", action="store_true", help="Require MemoryPipeline/Tasks raw_candidates/promoted log markers")
    parser.add_argument("--require-capture-audit-log", action="store_true", help="Require memory_capture_audit log marker")
    parser.add_argument("--require-retrieval-log", action="store_true", help="Require MemoryStore[C4] retrieved/rendered log marker")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON result")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv if argv is not None else sys.argv[1:]))
    try:
        result = run_check(
            memories_path=Path(args.memories),
            log_path=Path(args.log),
            baseline_memories_path=Path(args.baseline_memories) if args.baseline_memories else None,
            expect_oolong_written=args.expect_oolong_written,
            expect_project_written=args.expect_project_written,
            require_keywords=args.require_keyword,
            forbid_keywords=args.forbid_keyword,
            require_pipeline_log=bool(args.require_pipeline_log),
            require_capture_audit_log=bool(args.require_capture_audit_log),
            require_retrieval_log=bool(args.require_retrieval_log),
        )
    except Exception as exc:
        print(f"FAIL passive_live_smoke_check\nerrors:\n  - checker_exception: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(
            json.dumps(
                {
                    "ok": result.ok,
                    "errors": result.errors,
                    "warnings": result.warnings,
                    "observations": result.observations,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(render_text_result(result), end="")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
