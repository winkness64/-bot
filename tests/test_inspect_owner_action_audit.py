from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "inspect_owner_action_audit.py"


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([sys.executable, str(SCRIPT), *args], text=True, capture_output=True)


def write_jsonl(path: Path, rows: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for row in rows:
        if isinstance(row, str):
            lines.append(row)
        else:
            lines.append(json.dumps(row, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_jsonl(path: Path, row: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        if isinstance(row, str):
            fh.write(row)
        else:
            fh.write(json.dumps(row, ensure_ascii=False))
        fh.write("\n")


def sample_rows() -> list[dict]:
    return [
        {
            "time": "2026-01-01T00:00:01+00:00",
            "action_type": "reply_current",
            "destination_type": "current_session",
            "destination_id": "group:31003",
            "status": "nonebot_current_session",
            "mode": "nonebot_current_session",
            "allowed": True,
            "duplicate": False,
            "attempted": True,
            "delivered": True,
            "real_send": True,
            "reason": "sent",
            "key": "k1",
            "content_preview": "第一条真实发送",
        },
        {
            "time": "2026-01-01T00:00:02+00:00",
            "action_type": "reply_current",
            "destination_type": "current_session",
            "destination_id": "group:31003",
            "status": "blocked",
            "mode": "blocked",
            "allowed": False,
            "duplicate": True,
            "attempted": False,
            "delivered": False,
            "real_send": False,
            "reason": "duplicate_blocked",
            "key": "k2",
            "content_preview": "第二条重复",
        },
        {
            "time": "2026-01-01T00:00:03+00:00",
            "action_type": "send_group_message",
            "destination_type": "group",
            "destination_id": "137918147",
            "status": "blocked",
            "mode": "blocked",
            "allowed": True,
            "duplicate": False,
            "attempted": False,
            "delivered": False,
            "real_send": False,
            "reason": "cross_session_blocked",
            "key": "k3",
            "content_preview": "第三条跨群阻断",
        },
    ]


def test_no_audit_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        missing = Path(tmpdir) / "missing.jsonl"
        result = run_script("--path", str(missing))
        assert result.returncode == 0
        assert "no audit file" in result.stdout.lower()
        print("[PASS] no audit file")


def test_normal_jsonl_outputs_summary() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        write_jsonl(audit, sample_rows())
        result = run_script("--path", str(audit))
        assert result.returncode == 0
        stdout = result.stdout
        assert "summary=total=3 delivered=1 real_send=1 duplicate=1 blocked=2" in stdout
        assert "recent_records:" in stdout
        print("[PASS] normal jsonl summary")


def test_limit_works() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        write_jsonl(audit, sample_rows())
        result = run_script("--path", str(audit), "--limit", "2")
        assert result.returncode == 0
        stdout = result.stdout
        assert "summary=total=2" in stdout
        assert "第一条真实发送" not in stdout
        assert "第二条重复" in stdout
        assert "第三条跨群阻断" in stdout
        print("[PASS] limit works")


def test_real_send_only_works() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        write_jsonl(audit, sample_rows())
        result = run_script("--path", str(audit), "--real-send-only")
        assert result.returncode == 0
        stdout = result.stdout
        assert "summary=total=1 delivered=1 real_send=1 duplicate=0 blocked=0" in stdout
        assert "第一条真实发送" in stdout
        assert "第二条重复" not in stdout
        print("[PASS] real-send-only works")


def test_duplicates_only_works() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        write_jsonl(audit, sample_rows())
        result = run_script("--path", str(audit), "--duplicates-only")
        assert result.returncode == 0
        stdout = result.stdout
        assert "summary=total=1 delivered=0 real_send=0 duplicate=1 blocked=1" in stdout
        assert "第二条重复" in stdout
        assert "第一条真实发送" not in stdout
        print("[PASS] duplicates-only works")


def test_action_type_reply_current_works() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        write_jsonl(audit, sample_rows())
        result = run_script("--path", str(audit), "--action-type", "reply_current")
        assert result.returncode == 0
        stdout = result.stdout
        assert "summary=total=2" in stdout
        assert "send_group_message" not in stdout
        print("[PASS] action-type filter works")


def test_bad_json_line_skipped() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        rows = sample_rows()
        write_jsonl(audit, [rows[0], "{bad json", rows[1]])
        result = run_script("--path", str(audit))
        assert result.returncode == 0
        stdout = result.stdout
        assert "skipped_bad_lines=1" in stdout
        assert "summary=total=2" in stdout
        print("[PASS] bad json line skipped")


def test_tail_follow_missing_file_timeout() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        missing = Path(tmpdir) / "missing.jsonl"
        result = run_script("--tail-follow", "--follow-timeout", "0.2", "--path", str(missing))
        assert result.returncode == 0
        stdout = result.stdout
        assert "tail_follow=true" in stdout
        assert "no audit file" in stdout.lower()
        assert "tail_follow_waiting_for_file=true" in stdout
        assert "tail_follow_timeout_reached=true" in stdout
        print("[PASS] tail-follow missing file timeout")


def test_tail_follow_existing_file_outputs_initial_records() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        write_jsonl(audit, sample_rows())
        result = run_script("--tail-follow", "--follow-timeout", "0.2", "--path", str(audit))
        assert result.returncode == 0
        stdout = result.stdout
        assert "tail_follow=true" in stdout
        assert "summary=total=3 delivered=1 real_send=1 duplicate=1 blocked=2" in stdout
        assert "第一条真实发送" in stdout
        assert "第二条重复" in stdout
        print("[PASS] tail-follow existing file outputs initial records")


def test_tail_follow_real_send_only_filter_works() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        write_jsonl(audit, sample_rows())
        result = run_script(
            "--tail-follow",
            "--follow-timeout",
            "0.2",
            "--real-send-only",
            "--path",
            str(audit),
        )
        assert result.returncode == 0
        stdout = result.stdout
        assert "summary=total=1 delivered=1 real_send=1 duplicate=0 blocked=0" in stdout
        assert "第一条真实发送" in stdout
        assert "第二条重复" not in stdout
        assert "第三条跨群阻断" not in stdout
        print("[PASS] tail-follow real-send-only filter works")


def test_tail_follow_bad_json_line_does_not_crash() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        rows = sample_rows()
        write_jsonl(audit, [rows[0], "{bad json", rows[1]])
        result = run_script("--tail-follow", "--follow-timeout", "0.2", "--path", str(audit))
        assert result.returncode == 0
        stdout = result.stdout
        assert "skipped_bad_lines=1" in stdout
        assert "第一条真实发送" in stdout
        print("[PASS] tail-follow bad json line does not crash")


def test_tail_follow_captures_appended_record() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        rows = sample_rows()
        write_jsonl(audit, [rows[0]])

        appended = {
            "time": "2026-01-01T00:00:04+00:00",
            "action_type": "reply_current",
            "destination_type": "current_session",
            "destination_id": "group:31003",
            "status": "blocked",
            "mode": "blocked",
            "allowed": False,
            "duplicate": True,
            "attempted": False,
            "delivered": False,
            "real_send": False,
            "reason": "duplicate_blocked_runtime",
            "key": "k4",
            "content_preview": "运行时追加记录",
        }

        def delayed_append() -> None:
            time.sleep(0.1)
            append_jsonl(audit, appended)

        worker = threading.Thread(target=delayed_append, daemon=True)
        worker.start()
        result = run_script(
            "--tail-follow",
            "--follow-timeout",
            "0.35",
            "--poll-interval",
            "0.05",
            "--path",
            str(audit),
        )
        worker.join(timeout=1.0)
        assert result.returncode == 0
        stdout = result.stdout
        assert "第一条真实发送" in stdout
        assert "运行时追加记录" in stdout
        print("[PASS] tail-follow captures appended record")


def main() -> None:
    test_no_audit_file()
    test_normal_jsonl_outputs_summary()
    test_limit_works()
    test_real_send_only_works()
    test_duplicates_only_works()
    test_action_type_reply_current_works()
    test_bad_json_line_skipped()
    test_tail_follow_missing_file_timeout()
    test_tail_follow_existing_file_outputs_initial_records()
    test_tail_follow_real_send_only_filter_works()
    test_tail_follow_bad_json_line_does_not_crash()
    test_tail_follow_captures_appended_record()
    print("[OK] test_inspect_owner_action_audit.py")


if __name__ == "__main__":
    main()
