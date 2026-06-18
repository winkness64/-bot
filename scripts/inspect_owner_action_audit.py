from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_AUDIT_PATH = "logs/owner_action_delivery_audit.jsonl"
DEFAULT_RUNTIME_CONFIG = "src/plugins/yangyang/data/runtime_config.json"


@dataclass(frozen=True)
class AuditInspectSummary:
    total: int
    delivered: int
    real_send: int
    duplicate: int
    blocked: int
    skipped_bad_lines: int


@dataclass(frozen=True)
class ParsedAuditLines:
    records: list[dict[str, Any]]
    bad_lines: int


@dataclass
class TailFollowState:
    position: int = 0
    remainder: str = ""
    seen_bad_lines: int = 0


def load_runtime_config(path: str | Path = DEFAULT_RUNTIME_CONFIG) -> dict[str, Any]:
    config_path = Path(path)
    if not config_path.exists():
        return {}
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


def resolve_default_audit_path() -> Path:
    cfg = load_runtime_config()
    raw = str(cfg.get("owner_action_delivery_audit_path") or DEFAULT_AUDIT_PATH)
    path = Path(raw)
    if path.is_absolute():
        return path
    return Path.cwd() / path


def parse_jsonl_text(text: str) -> ParsedAuditLines:
    records: list[dict[str, Any]] = []
    bad_lines = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            bad_lines += 1
            continue
        if isinstance(obj, dict):
            records.append(obj)
        else:
            bad_lines += 1
    return ParsedAuditLines(records=records, bad_lines=bad_lines)


def load_jsonl_records(path: Path) -> tuple[list[dict[str, Any]], int]:
    if not path.exists() or not path.is_file():
        return [], 0

    try:
        parsed = parse_jsonl_text(path.read_text(encoding="utf-8"))
    except Exception:
        return [], 0
    return parsed.records, parsed.bad_lines


def _is_true(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _contains_duplicate_reason(record: dict[str, Any]) -> bool:
    reason = _normalize_text(record.get("reason"))
    return "duplicate" in reason.lower()


def _record_matches(record: dict[str, Any], args: argparse.Namespace) -> bool:
    if args.real_send_only and not _is_true(record.get("real_send")):
        return False
    if args.duplicates_only and not (_is_true(record.get("duplicate")) or _contains_duplicate_reason(record)):
        return False
    if args.action_type and _normalize_text(record.get("action_type")) != args.action_type:
        return False
    if args.status and _normalize_text(record.get("status")) != args.status:
        return False
    if args.mode and _normalize_text(record.get("mode")) != args.mode:
        return False
    return True


def filter_records(records: list[dict[str, Any]], args: argparse.Namespace) -> list[dict[str, Any]]:
    filtered = [record for record in records if _record_matches(record, args)]
    limit = max(int(args.limit or 20), 0)
    if limit <= 0:
        return filtered
    return filtered[-limit:]


def build_summary(records: list[dict[str, Any]], bad_lines: int) -> AuditInspectSummary:
    delivered = sum(1 for record in records if _is_true(record.get("delivered")))
    real_send = sum(1 for record in records if _is_true(record.get("real_send")))
    duplicate = sum(1 for record in records if _is_true(record.get("duplicate")) or _contains_duplicate_reason(record))
    blocked = sum(
        1
        for record in records
        if _normalize_text(record.get("status")).lower() == "blocked"
        or _normalize_text(record.get("mode")).lower() == "blocked"
        or "blocked" in _normalize_text(record.get("reason")).lower()
    )
    return AuditInspectSummary(
        total=len(records),
        delivered=delivered,
        real_send=real_send,
        duplicate=duplicate,
        blocked=blocked,
        skipped_bad_lines=bad_lines,
    )


def _shorten(text: Any, limit: int = 40) -> str:
    value = _normalize_text(text).replace("\n", " ").replace("\r", " ")
    if len(value) <= limit:
        return value
    return value[:limit] + "…"


def _destination_text(record: dict[str, Any]) -> str:
    dst_type = _normalize_text(record.get("destination_type")) or "-"
    dst_id = _normalize_text(record.get("destination_id")) or "-"
    return f"{dst_type}:{dst_id}"


def format_record_line(record: dict[str, Any]) -> str:
    time_value = _shorten(record.get("time"), 24) or "-"
    action_type = _shorten(record.get("action_type"), 16) or "-"
    destination = _shorten(_destination_text(record), 28) or "-"
    mode_status = _shorten(record.get("mode") or record.get("status"), 18) or "-"
    real_send = str(_is_true(record.get("real_send"))).lower()
    reason = _shorten(record.get("reason"), 36) or "-"
    preview = _shorten(record.get("content_preview"), 48) or "-"
    return (
        f"time={time_value} | action_type={action_type} | destination={destination} | "
        f"mode/status={mode_status} | real_send={real_send} | reason={reason} | content_preview={preview}"
    )


def print_summary(records: list[dict[str, Any]], bad_lines: int) -> None:
    summary = build_summary(records, bad_lines)
    print(
        "summary="
        f"total={summary.total} "
        f"delivered={summary.delivered} "
        f"real_send={summary.real_send} "
        f"duplicate={summary.duplicate} "
        f"blocked={summary.blocked} "
        f"skipped_bad_lines={summary.skipped_bad_lines}"
    )


def print_records(records: list[dict[str, Any]], *, heading: str | None = None) -> None:
    if heading:
        print(heading)
    for record in records:
        print(format_record_line(record))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect owner_action audit JSONL without connecting QQ/OneBot.")
    parser.add_argument("--path", default=None, help="Audit JSONL path. Default comes from runtime config or logs/owner_action_delivery_audit.jsonl")
    parser.add_argument("--limit", type=int, default=20, help="Show recent N matched records. Default 20")
    parser.add_argument("--real-send-only", action="store_true", help="Only show records with real_send=true")
    parser.add_argument("--duplicates-only", action="store_true", help="Only show duplicate records")
    parser.add_argument("--action-type", default="", help="Filter by action_type, e.g. reply_current")
    parser.add_argument("--status", default="", help="Filter by status field")
    parser.add_argument("--mode", default="", help="Filter by mode field")
    parser.add_argument("--tail-follow", action="store_true", help="Tail-follow audit file in read-only mode")
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Polling interval seconds for --tail-follow. Default 1.0")
    parser.add_argument("--follow-timeout", type=float, default=0.0, help="Timeout seconds for --tail-follow. 0 means no timeout")
    parser.add_argument("--no-initial", action="store_true", help="Do not print initial recent records, only follow new appended lines")
    return parser


def _read_incremental_lines(path: Path, state: TailFollowState) -> ParsedAuditLines:
    if not path.exists() or not path.is_file():
        return ParsedAuditLines(records=[], bad_lines=0)

    try:
        current_size = path.stat().st_size
        if current_size < state.position:
            state.position = 0
            state.remainder = ""

        with path.open("r", encoding="utf-8") as fh:
            fh.seek(state.position)
            chunk = fh.read()
            state.position = fh.tell()
    except Exception:
        return ParsedAuditLines(records=[], bad_lines=0)

    if not chunk:
        return ParsedAuditLines(records=[], bad_lines=0)

    combined = state.remainder + chunk
    if combined.endswith("\n"):
        complete_text = combined
        state.remainder = ""
    else:
        parts = combined.splitlines(keepends=True)
        if parts and not parts[-1].endswith("\n"):
            state.remainder = parts[-1]
            complete_text = "".join(parts[:-1])
        else:
            complete_text = combined
            state.remainder = ""

    return parse_jsonl_text(complete_text)


def _print_tail_follow_bad_lines(count: int, state: TailFollowState) -> None:
    if count <= 0:
        return
    state.seen_bad_lines += count
    print(f"tail_follow_skipped_bad_lines+={count} total={state.seen_bad_lines}")


def run_tail_follow(args: argparse.Namespace, audit_path: Path) -> int:
    poll_interval = max(float(args.poll_interval or 1.0), 0.05)
    follow_timeout = max(float(args.follow_timeout or 0.0), 0.0)
    start_time = time.monotonic()
    state = TailFollowState()

    print("[OWNER_ACTION_AUDIT_INSPECT]")
    print(f"path={audit_path}")
    print("tail_follow=true")
    print(f"poll_interval={poll_interval}")
    print(f"timeout={follow_timeout}")

    if not args.no_initial:
        if not audit_path.exists():
            print("no audit file")
            print("tail_follow_waiting_for_file=true")
        else:
            records, bad_lines = load_jsonl_records(audit_path)
            filtered = filter_records(records, args)
            print_summary(filtered, bad_lines)
            if filtered:
                print_records(filtered, heading="recent_records:")
            else:
                print("no matched records")
            try:
                state.position = audit_path.stat().st_size
            except Exception:
                state.position = 0
    else:
        if not audit_path.exists():
            print("no audit file")
            print("tail_follow_waiting_for_file=true")
        else:
            try:
                state.position = audit_path.stat().st_size
            except Exception:
                state.position = 0

    file_seen = audit_path.exists()

    try:
        while True:
            if follow_timeout > 0 and time.monotonic() - start_time >= follow_timeout:
                print("tail_follow_timeout_reached=true")
                return 0

            exists_now = audit_path.exists() and audit_path.is_file()
            if exists_now and not file_seen:
                file_seen = True
                print("tail_follow_file_detected=true")
                if args.no_initial:
                    try:
                        state.position = audit_path.stat().st_size
                    except Exception:
                        state.position = 0
            elif not exists_now and not file_seen:
                time.sleep(poll_interval)
                continue
            elif not exists_now:
                file_seen = False
                state.position = 0
                state.remainder = ""
                print("tail_follow_file_missing=true")
                time.sleep(poll_interval)
                continue

            parsed = _read_incremental_lines(audit_path, state)
            _print_tail_follow_bad_lines(parsed.bad_lines, state)
            matched = [record for record in parsed.records if _record_matches(record, args)]
            if matched:
                print_records(matched)

            time.sleep(poll_interval)
    except KeyboardInterrupt:
        print("tail_follow_stopped=keyboard_interrupt")
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    audit_path = Path(args.path) if args.path else resolve_default_audit_path()
    if not audit_path.is_absolute():
        audit_path = Path.cwd() / audit_path

    if args.tail_follow:
        return run_tail_follow(args, audit_path)

    print("[OWNER_ACTION_AUDIT_INSPECT]")
    print(f"path={audit_path}")

    if not audit_path.exists():
        print("no audit file")
        return 0

    records, bad_lines = load_jsonl_records(audit_path)
    filtered = filter_records(records, args)
    print_summary(filtered, bad_lines)

    if not filtered:
        print("no matched records")
        return 0

    print_records(filtered, heading="recent_records:")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
