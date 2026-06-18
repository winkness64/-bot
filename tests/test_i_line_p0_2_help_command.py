from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import SimpleNamespace


MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "plugins" / "yangyang" / "core" / "isaac_agent_bus_p0.py"
SPEC = importlib.util.spec_from_file_location("isaac_agent_bus_p0_help_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
isaac_agent_bus_p0 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = isaac_agent_bus_p0
SPEC.loader.exec_module(isaac_agent_bus_p0)
handle_isaac_agent_bus_p0_message = isaac_agent_bus_p0.handle_isaac_agent_bus_p0_message


def _owner_private(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, raw_content=text, channel="private", is_owner=True)


def test_help_command_is_read_only_success() -> None:
    result = handle_isaac_agent_bus_p0_message(_owner_private("/i叔 help"))
    assert result.handled is True
    assert result.allowed is True
    assert result.task_type == "help_report"
    assert "可用命令" in result.reply
    assert "owner 私聊限定" in result.reply
    assert result.worker_result is not None
    assert result.worker_result["executor_enabled"] is False
    assert result.worker_result["host_action_executed"] is False
    assert result.worker_result["read_only"] is True


def test_empty_isaac_command_defaults_to_help_not_health() -> None:
    result = handle_isaac_agent_bus_p0_message(_owner_private("/i叔"))
    assert result.handled is True
    assert result.allowed is True
    assert result.task_type == "help_report"
    assert "/i叔 help" in result.reply


def test_unsupported_task_reply_contains_help_hint() -> None:
    result = handle_isaac_agent_bus_p0_message(_owner_private("/i叔 整点别的"))
    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "clarification_required"
    assert "I叔 P1 preview" in result.reply or "I叔 P0 需要二次确认" in result.reply
    assert "clarification_required" in result.reply
    assert "/i叔 help" in result.reply
    assert result.task_request is None
