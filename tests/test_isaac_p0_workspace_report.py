from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
import json
from pathlib import Path
import sys


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "plugins" / "yangyang" / "core" / "isaac_agent_bus_p0.py"
SPEC = importlib.util.spec_from_file_location("isaac_agent_bus_p0_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
isaac_agent_bus_p0 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = isaac_agent_bus_p0
SPEC.loader.exec_module(isaac_agent_bus_p0)
handle_isaac_agent_bus_p0_message = isaac_agent_bus_p0.handle_isaac_agent_bus_p0_message


SENSITIVE_MARKERS = (
    "api_key", "apikey", "token", "base_url", "secret", "password",
    "authorization", "cookie", "session_key",
)


@dataclass
class DummyMessage:
    text: str
    channel: str = "private"
    is_owner: bool = True
    raw_content: str = ""
    uid: str = "335059272"
    group_id: str = ""
    msg_id: str = "dummy-msg"
    nick: str = "漂♂总"
    is_at_bot: bool = False
    owner_command: bool = False
    explicit_command: bool = False
    at_user_ids: list[str] = field(default_factory=list)


def test_owner_private_workspace_report_returns_real_overview() -> None:
    msg = DummyMessage(text="/i叔 workspace report")
    result = handle_isaac_agent_bus_p0_message(msg)
    assert result.handled is True
    assert result.allowed is True
    assert result.reason == "pass"
    assert result.task_type == "workspace_report"
    reply = str(result.reply or "")
    assert "workspace" in reply.lower()
    assert "project_name" in reply
    assert "audit" in reply.lower()
    wr = dict((result.worker_result or {}).get("diagnostics", {}).get("workspace_report") or {})
    assert wr.get("project_name") == "yangyang_nonebot"
    assert isinstance(wr.get("directories"), dict)
    assert isinstance(wr.get("audit"), dict)
    assert isinstance(wr.get("recent_files"), list)
    # sensitive markers must not appear in reply
    lower_reply = reply.lower()
    for marker in SENSITIVE_MARKERS:
        assert marker not in lower_reply, f"leaked marker: {marker}"


def test_workspace_report_no_sensitive_markers() -> None:
    msg = DummyMessage(text="/i叔 workspace")
    result = handle_isaac_agent_bus_p0_message(msg)
    assert result.handled is True
    assert result.allowed is True
    reply = str(result.reply or "")
    lower = reply.lower()
    for marker in SENSITIVE_MARKERS:
        assert marker not in lower, f"sensitive marker leaked: {marker}"


def test_group_non_owner_workspace_denied() -> None:
    msg = DummyMessage(text="/i叔 workspace report", channel="group", is_owner=False, group_id="999999")
    result = handle_isaac_agent_bus_p0_message(msg)
    assert result.handled is True
    assert result.allowed is False
    reply = str(result.reply or "").lower()
    for marker in SENSITIVE_MARKERS:
        assert marker not in reply
    # workspace report specific data must not leak
    assert "project_root" not in reply
    assert "isaac_p0_audit.jsonl" not in reply
