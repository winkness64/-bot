from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
import json
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "plugins" / "yangyang" / "core" / "isaac_agent_bus_p0.py"
SPEC = importlib.util.spec_from_file_location("isaac_agent_bus_p0_audit_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)
handle = mod.handle_isaac_agent_bus_p0_message


@dataclass
class DummyMessage:
    text: str
    channel: str = "private"
    is_owner: bool = True
    raw_content: str = ""
    uid: str = "335059272"
    user_id: str = "335059272"
    group_id: str = ""
    msg_id: str = "dummy-msg"
    nick: str = "阿漂"
    is_at_bot: bool = False
    owner_command: bool = False
    explicit_command: bool = False
    at_user_ids: list[str] = field(default_factory=list)


def _read_audit_lines(audit_dir: Path) -> list[dict[str, object]]:
    path = audit_dir / "isaac_p0_audit.jsonl"
    assert path.exists()
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_isaac_p0_owner_private_slash_writes_handled_audit(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ISAAC_P0_AUDIT_DIR", str(tmp_path))

    result = handle(DummyMessage(text="/i叔 health"))

    assert result.handled is True
    assert result.allowed is True
    assert result.reason == "pass"
    rows = _read_audit_lines(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["decision"] == "handled"
    assert row["reason"] == "pass"
    assert row["channel"] == "private"
    assert row["is_owner"] is True
    assert row["trigger_type"] == "slash_fallback"
    assert row["command_head"] == "/i叔"
    assert row["task_type"] == "health_report"
    assert isinstance(row["run_id"], str) and len(row["run_id"]) == 12
    assert row["user_id"] == "335059272"


def test_isaac_p0_denied_branch_writes_denied_audit(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ISAAC_P0_AUDIT_DIR", str(tmp_path))

    result = handle(DummyMessage(text="/I叔 health", channel="group", group_id="137918147"))

    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "private_only"
    rows = _read_audit_lines(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["decision"] == "denied"
    assert row["reason"] == "private_only"
    assert row["channel"] == "group"
    assert row["command_head"] == "/I叔"
    assert row["trigger_type"] == "slash_fallback"


def test_isaac_p0_ignored_branch_writes_ignored_audit_without_raw_text(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ISAAC_P0_AUDIT_DIR", str(tmp_path))

    result = handle(DummyMessage(text="普通闲聊 api_key token base_url secret env should not leak"))

    assert result.handled is False
    assert result.allowed is False
    assert result.reason == "not_isaac_command"
    rows = _read_audit_lines(tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["decision"] == "ignored"
    assert row["trigger_type"] == "natural_llm"
    assert row["command_head"] is None
    serialized = json.dumps(row, ensure_ascii=False).lower()
    for marker in ("api_key", "token", "base_url", "env", "secret", "raw_text", "full_prompt", "messages"):
        assert marker not in serialized
    assert "普通闲聊" not in serialized


def test_isaac_p0_audit_write_failure_does_not_break_handler(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ISAAC_P0_AUDIT_DIR", str(tmp_path))

    def boom(_path):
        raise RuntimeError("audit fs down")

    monkeypatch.setattr(mod, "_rotate_isaac_audit_file", boom)

    result = handle(DummyMessage(text="/艾萨克 health"))

    assert result.handled is True
    assert result.allowed is True
    assert result.reason == "pass"
    assert not (tmp_path / "isaac_p0_audit.jsonl").exists()
