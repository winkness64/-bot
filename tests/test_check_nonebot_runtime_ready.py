from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_nonebot_runtime_ready.py"


def run_script(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        text=True,
        capture_output=True,
    )


def assert_contains(text: str, needle: str) -> None:
    assert needle in text, f"missing {needle!r} in output:\n{text}"


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_minimal_project(root: Path, *, include_env: bool = False, smoke_enabled: bool = False) -> None:
    write_text(
        root / "bot.py",
        "from dotenv import load_dotenv\nimport nonebot\nfrom nonebot.adapters.onebot.v11 import Adapter as OneBotV11Adapter\n"
        "load_dotenv('.env')\nnonebot.load_plugins('src/plugins')\n",
    )
    write_text(
        root / "pyproject.toml",
        "[project]\nname='tmp'\n[project.optional-dependencies]\nnonebot=['nonebot2>=2.3.0','nonebot-adapter-onebot>=2.4.0']\n"
        "[tool.pytest.ini_options]\npythonpath=['src']\n",
    )
    write_text(
        root / ".env.example",
        "DRIVER=~fastapi+~httpx+~websockets\nHOST=127.0.0.1\nPORT=8080\nONEBOT_WS_URL=ws://127.0.0.1:8080/ws\n"
        "ONEBOT_ACCESS_TOKEN=\nONEBOT_SECRET=\nONEBOT_API_ROOT=http://127.0.0.1:3000\nONEBOT_WS_REVERSE_URL=\n",
    )
    if include_env:
        write_text(
            root / ".env",
            "DRIVER=~fastapi+~httpx+~websockets\nONEBOT_ACCESS_TOKEN=super-secret-token\nOPENAI_API_KEY=ultra-secret\n",
        )
    write_text(
        root / "src/plugins/yangyang/__init__.py",
        "from .output.current_session_smoke_trigger import handle_current_session_smoke_trigger_if_matched, parse_current_session_smoke_trigger_command\n"
        "async def handle_message(bot, event):\n    smoke_command = parse_current_session_smoke_trigger_command('x')\n    if smoke_command.matched:\n        await handle_current_session_smoke_trigger_if_matched(None, None, bot=bot, event=event)\n",
    )
    write_text(
        root / "src/plugins/yangyang/output/current_session_smoke_trigger.py",
        "async def handle_current_session_smoke_trigger_if_matched(*args, **kwargs):\n    return None\n"
        "def parse_current_session_smoke_trigger_command(text):\n    return type('X', (), {'matched': False})()\n"
        "def x():\n    action_type='send_group_message'\n    reason='cross_session_blocked'\n    explicit_enable=True\n",
    )
    write_text(
        root / "src/plugins/yangyang/output/current_session_manual_smoke.py",
        "def x():\n    action_type != \"reply_current\"\n    destination_type != \"current_session\"\n",
    )
    write_text(
        root / "src/plugins/yangyang/output/sender_adapter_factory.py",
        "owner_action_allow_reply_current = True\nowner_action_current_session_delivery_enabled = True\n",
    )
    write_text(
        root / "src/plugins/yangyang/output/sender_adapter.py",
        "class NoneBotCurrentSessionSenderAdapter:\n    pass\n",
    )
    write_text(
        root / "src/plugins/yangyang/data/runtime_config.json",
        json.dumps(
            {
                "owner_action_manual_smoke_enabled": smoke_enabled,
                "owner_action_nonebot_sender_enabled": False,
                "owner_action_allow_reply_current": False,
                "owner_action_current_session_delivery_enabled": False,
                "owner_action_allow_send_group_message": False,
                "owner_action_delivery_audit_enabled": True,
                "owner_action_delivery_audit_path": "logs/owner_action_delivery_audit.jsonl",
            },
            ensure_ascii=False,
            indent=2,
        ),
    )


def test_script_runs_on_current_project() -> None:
    result = run_script()
    assert "[NONEBOT_RUNTIME_READY_CHECK]" in result.stdout
    assert result.returncode in {0, 1}
    print("[PASS] runtime ready script runs on current project")


def test_env_values_are_not_printed() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        build_minimal_project(root, include_env=True, smoke_enabled=False)
        result = run_script("--root", str(root))
        assert result.returncode in {0, 1}
        assert_contains(result.stdout, "[NONEBOT_RUNTIME_READY_CHECK]")
        assert "super-secret-token" not in result.stdout
        assert "ultra-secret" not in result.stdout
        assert_contains(result.stdout, ".env exists; parsed keys only:")
        print("[PASS] env sensitive values not printed")


def test_missing_env_is_warn_not_fail_for_temp_root() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        build_minimal_project(root, include_env=False, smoke_enabled=False)
        result = run_script("--root", str(root))
        assert_contains(result.stdout, "[WARN] .env missing; create from .env.example before real OneBot run")
        print("[PASS] missing env is warn")


def test_missing_key_files_fail() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        build_minimal_project(root, include_env=False, smoke_enabled=False)
        (root / "bot.py").unlink()
        result = run_script("--root", str(root))
        assert result.returncode == 1
        assert_contains(result.stdout, "[FAIL] file bot.py missing")
        print("[PASS] missing key files fail")


def test_runtime_smoke_enabled_warns() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        build_minimal_project(root, include_env=False, smoke_enabled=True)
        result = run_script("--root", str(root))
        assert_contains(result.stdout, "runtime_config.json smoke currently enabled")
        print("[PASS] runtime smoke enabled warns")


def main() -> None:
    test_script_runs_on_current_project()
    test_env_values_are_not_printed()
    test_missing_env_is_warn_not_fail_for_temp_root()
    test_missing_key_files_fail()
    test_runtime_smoke_enabled_warns()
    print("[OK] test_check_nonebot_runtime_ready.py")


if __name__ == "__main__":
    main()
