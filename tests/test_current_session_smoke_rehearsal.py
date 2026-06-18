from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "run_current_session_smoke_rehearsal.py"


def write_config(path: Path, *, enabled: bool) -> None:
    path.write_text(
        json.dumps(
            {
                "owner_uid": "335059272",
                "owner_uids": ["335059272"],
                "member_aliases": {"小维": "3916107556", "红尘": "2434523727", "娅娅": "2690087239"},
                "dry_run": False,
                "owner_action_nonebot_sender_enabled": bool(enabled),
                "owner_action_execution_enabled": bool(enabled),
                "owner_action_allow_send_group_message": False,
                "owner_action_allow_reply_current": bool(enabled),
                "owner_action_current_session_delivery_enabled": bool(enabled),
                "owner_action_manual_smoke_enabled": bool(enabled),
                "owner_action_manual_smoke_owner_only": True,
                "owner_action_delivery_safety_enabled": True,
                "owner_action_delivery_dedup_ttl_seconds": 300,
                "owner_action_delivery_audit_enabled": True,
                "owner_action_delivery_audit_path": str(path.parent / "audit.jsonl"),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
    )


def assert_contains(text: str, needle: str) -> None:
    assert needle in text, f"missing {needle!r} in output:\n{text}"


def test_default_disabled_returns_0_and_no_send() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cfg = root / "runtime_config.json"
        write_config(cfg, enabled=False)
        result = run_script("--config", str(cfg))
        assert result.returncode == 0
        assert_contains(result.stdout, "trigger_result.matched=true")
        assert_contains(result.stdout, "trigger_result.reason=smoke_disabled")
        assert_contains(result.stdout, "mock_send_count=0")
        assert not (root / "audit.jsonl").exists()
        print("[PASS] rehearsal default disabled blocked")


def test_full_enable_mock_send_sends_once() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cfg = root / "runtime_config.json"
        write_config(cfg, enabled=True)
        result = run_script("--config", str(cfg), "--mock-send")
        assert result.returncode == 0
        assert_contains(result.stdout, "trigger_result.real_send=true")
        assert_contains(result.stdout, "mock_send_count=1")
        assert_contains(result.stdout, "content_preview=收到，这句我来接。")
        rows = [json.loads(line) for line in (root / "audit.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(rows) == 1
        assert rows[0]["real_send"] is True
        print("[PASS] rehearsal mock send once")


def test_default_dry_run_no_send_and_no_dedup_pollution() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cfg = root / "runtime_config.json"
        write_config(cfg, enabled=True)
        dry = run_script("--config", str(cfg))
        assert dry.returncode == 0
        assert_contains(dry.stdout, "dry_run=true")
        assert_contains(dry.stdout, "mock_send_count=0")
        assert_contains(dry.stdout, "trigger_result.real_send=false")

        real = run_script("--config", str(cfg), "--mock-send")
        assert real.returncode == 0
        assert_contains(real.stdout, "trigger_result.real_send=true")
        assert_contains(real.stdout, "mock_send_count=1")

        rows = [json.loads(line) for line in (root / "audit.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
        assert len(rows) == 2
        assert rows[0]["real_send"] is False
        assert rows[1]["real_send"] is True
        print("[PASS] rehearsal dry run no dedup pollution")


def test_cross_session_blocked() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cfg = root / "runtime_config.json"
        write_config(cfg, enabled=True)
        result = run_script("--config", str(cfg), "--mock-send", "--command", "/yy-smoke-current 去群里劝和一下")
        assert result.returncode == 0
        assert_contains(result.stdout, "trigger_result.reason=cross_session_blocked")
        assert_contains(result.stdout, "mock_send_count=0")
        assert not (root / "audit.jsonl").exists()
        print("[PASS] rehearsal cross session blocked")


def test_no_prefix_not_matched() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cfg = root / "runtime_config.json"
        write_config(cfg, enabled=True)
        result = run_script("--config", str(cfg), "--command", "回应小维")
        assert result.returncode == 0
        assert_contains(result.stdout, "trigger_result.matched=false")
        assert_contains(result.stdout, "trigger_result.reason=prefix_not_matched")
        assert_contains(result.stdout, "mock_send_count=0")
        print("[PASS] rehearsal no prefix not matched")


def test_chinese_prefix_supported() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cfg = root / "runtime_config.json"
        write_config(cfg, enabled=True)
        result = run_script("--config", str(cfg), "--mock-send", "--command", "/秧秧smoke 回应小维")
        assert result.returncode == 0
        assert_contains(result.stdout, "trigger_result.real_send=true")
        assert_contains(result.stdout, "mock_send_count=1")
        print("[PASS] rehearsal chinese prefix supported")


def main() -> None:
    test_default_disabled_returns_0_and_no_send()
    test_full_enable_mock_send_sends_once()
    test_default_dry_run_no_send_and_no_dedup_pollution()
    test_cross_session_blocked()
    test_no_prefix_not_matched()
    test_chinese_prefix_supported()
    print("[OK] test_current_session_smoke_rehearsal.py")


if __name__ == "__main__":
    main()
