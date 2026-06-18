from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "toggle_current_session_smoke.py"


BASE_CONFIG = {
    "owner_action_manual_smoke_enabled": False,
    "owner_action_manual_smoke_owner_only": True,
    "owner_action_nonebot_sender_enabled": False,
    "owner_action_execution_enabled": False,
    "owner_action_allow_reply_current": False,
    "owner_action_current_session_delivery_enabled": False,
    "owner_action_delivery_safety_enabled": True,
    "owner_action_delivery_audit_enabled": True,
    "owner_action_allow_send_group_message": False,
    "send_group_message": False,
    "cross_session_enabled": False,
    "owner_action_delivery_audit_path": "logs/owner_action_delivery_audit.jsonl",
}


def run_script(*args: str, input_text: str | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        input=input_text,
        capture_output=True,
        cwd=str(cwd) if cwd else None,
    )


def write_config(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_config(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def find_backups(workdir: Path) -> list[Path]:
    backup_dir = workdir / "backups" / "runtime_config"
    if not backup_dir.exists():
        return []
    return sorted(backup_dir.glob("runtime_config*.json"))


def test_show_runs() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cfg = root / "runtime_config.json"
        write_config(cfg, BASE_CONFIG)
        result = run_script("--show", "--config", str(cfg), cwd=root)
        assert result.returncode == 0
        assert "[CURRENT_SESSION_SMOKE_STATUS]" in result.stdout
        assert "owner_action_manual_smoke_enabled=false" in result.stdout
        assert "cross_session_send_group_message_locked=true" in result.stdout
        print("[PASS] show runs")


def test_enable_dry_run_does_not_modify_file() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cfg = root / "runtime_config.json"
        write_config(cfg, BASE_CONFIG)
        before = cfg.read_text(encoding="utf-8")
        result = run_script("--enable", "--dry-run", "--config", str(cfg), cwd=root)
        assert result.returncode == 0
        assert "dry_run=true" in result.stdout
        assert cfg.read_text(encoding="utf-8") == before
        assert find_backups(root) == []
        print("[PASS] enable dry-run does not modify file")


def test_enable_yes_updates_expected_keys() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cfg = root / "runtime_config.json"
        write_config(cfg, BASE_CONFIG)
        result = run_script("--enable", "--yes", "--config", str(cfg), cwd=root)
        assert result.returncode == 0
        data = read_config(cfg)
        assert data["owner_action_manual_smoke_enabled"] is True
        assert data["owner_action_nonebot_sender_enabled"] is True
        assert data["owner_action_execution_enabled"] is True
        assert data["owner_action_allow_reply_current"] is True
        assert data["owner_action_current_session_delivery_enabled"] is True
        assert data["owner_action_manual_smoke_owner_only"] is True
        assert data["owner_action_delivery_safety_enabled"] is True
        assert data["owner_action_delivery_audit_enabled"] is True
        assert data["owner_action_allow_send_group_message"] is False
        assert data["send_group_message"] is False
        assert data["cross_session_enabled"] is False
        backups = find_backups(root)
        assert len(backups) == 1
        assert "changed_keys=" in result.stdout
        print("[PASS] enable yes updates expected keys")


def test_disable_yes_returns_safe_state() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cfg = root / "runtime_config.json"
        enabled = dict(BASE_CONFIG)
        enabled.update(
            {
                "owner_action_manual_smoke_enabled": True,
                "owner_action_nonebot_sender_enabled": True,
                "owner_action_execution_enabled": True,
                "owner_action_allow_reply_current": True,
                "owner_action_current_session_delivery_enabled": True,
            }
        )
        write_config(cfg, enabled)
        result = run_script("--disable", "--yes", "--config", str(cfg), cwd=root)
        assert result.returncode == 0
        data = read_config(cfg)
        assert data["owner_action_manual_smoke_enabled"] is False
        assert data["owner_action_nonebot_sender_enabled"] is False
        assert data["owner_action_execution_enabled"] is False
        assert data["owner_action_allow_reply_current"] is False
        assert data["owner_action_current_session_delivery_enabled"] is False
        assert data["owner_action_manual_smoke_owner_only"] is True
        backups = find_backups(root)
        assert len(backups) == 1
        print("[PASS] disable yes returns safe state")


def test_restore_backup_works() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cfg = root / "runtime_config.json"
        write_config(cfg, BASE_CONFIG)
        enable_result = run_script("--enable", "--yes", "--config", str(cfg), cwd=root)
        assert enable_result.returncode == 0
        backups = find_backups(root)
        assert len(backups) == 1
        backup_path = backups[0]
        disable_result = run_script("--disable", "--yes", "--config", str(cfg), cwd=root)
        assert disable_result.returncode == 0
        restore_result = run_script("--restore", str(backup_path), "--yes", "--config", str(cfg), cwd=root)
        assert restore_result.returncode == 0
        data = read_config(cfg)
        assert data["owner_action_manual_smoke_enabled"] is False
        assert data["owner_action_nonebot_sender_enabled"] is False
        assert data["owner_action_execution_enabled"] is False
        assert data["owner_action_allow_reply_current"] is False
        assert data["owner_action_current_session_delivery_enabled"] is False
        assert "restored=true" in restore_result.stdout
        print("[PASS] restore backup works")


def test_enable_without_yes_non_interactive_cancels() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cfg = root / "runtime_config.json"
        write_config(cfg, BASE_CONFIG)
        before = cfg.read_text(encoding="utf-8")
        result = run_script("--enable", "--config", str(cfg), cwd=root)
        assert result.returncode == 0
        assert "cancelled=non_interactive_confirmation_required" in result.stdout
        assert cfg.read_text(encoding="utf-8") == before
        assert find_backups(root) == []
        print("[PASS] enable without yes non-interactive cancels")


def test_enable_input_n_cancels() -> None:
    import builtins
    import importlib.util
    from io import StringIO

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cfg = root / "runtime_config.json"
        write_config(cfg, BASE_CONFIG)

        spec = importlib.util.spec_from_file_location("toggle_current_session_smoke", SCRIPT)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)

        old_input = builtins.input
        old_stdin = sys.stdin
        old_stdout = sys.stdout

        class DummyStdin:
            def isatty(self) -> bool:
                return True

        captured = StringIO()
        try:
            builtins.input = lambda prompt='': 'n'
            sys.stdin = DummyStdin()
            sys.stdout = captured
            rc = mod.main(["--enable", "--config", str(cfg)])
        finally:
            builtins.input = old_input
            sys.stdin = old_stdin
            sys.stdout = old_stdout

        assert rc == 0
        assert "cancelled=user_declined" in captured.getvalue()
        data = read_config(cfg)
        assert data == BASE_CONFIG
        assert find_backups(root) == []
        print("[PASS] enable input n cancels")


def test_no_cross_session_flags_are_opened() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cfg = root / "runtime_config.json"
        write_config(cfg, BASE_CONFIG)
        result = run_script("--enable", "--yes", "--config", str(cfg), cwd=root)
        assert result.returncode == 0
        data = read_config(cfg)
        forbidden_truthy = {
            key: value
            for key, value in data.items()
            if (
                ("cross_session" in key or "send_group_message" in key)
                and key not in {
                    "owner_action_current_session_delivery_enabled",
                }
                and value is True
            )
        }
        assert forbidden_truthy == {}
        print("[PASS] no cross-session flags are opened")


def main() -> None:
    test_show_runs()
    test_enable_dry_run_does_not_modify_file()
    test_enable_yes_updates_expected_keys()
    test_disable_yes_returns_safe_state()
    test_restore_backup_works()
    test_enable_without_yes_non_interactive_cancels()
    test_enable_input_n_cancels()
    test_no_cross_session_flags_are_opened()
    print("[OK] test_toggle_current_session_smoke.py")


if __name__ == "__main__":
    main()
