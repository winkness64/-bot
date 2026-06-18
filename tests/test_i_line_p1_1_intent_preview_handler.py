from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "plugins" / "yangyang" / "core" / "isaac_agent_bus_p0.py"
SPEC = importlib.util.spec_from_file_location("isaac_agent_bus_p0_p1_preview_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)
handle = mod.handle_isaac_agent_bus_p0_message


def _owner_private(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, raw_content=text, channel="private", is_owner=True)


def _non_owner_private(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, raw_content=text, channel="private", is_owner=False)


def _owner_group(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, raw_content=text, channel="group", is_owner=True, group_id="137918147")


def test_p1_preview_natural_language_low_risk_would_dispatch_only() -> None:
    result = handle(_owner_private("麻烦 I叔 看看你现在状态"))

    assert result.handled is True
    assert result.allowed is True
    assert result.reason == "pass"
    assert result.task_type == "health_report"
    assert result.task_request is not None
    assert result.task_result is not None
    assert result.worker_result is not None
    assert result.intent_preview is None
    assert "I叔 P1 preview" not in result.reply
    assert "I叔 P0 闭环已跑通" in result.reply
    assert "readonly_health_snapshot=" in result.reply
    snapshot = result.worker_result["readonly_health_snapshot"]
    assert snapshot["read_only"] is True
    assert snapshot["workspace_only"] is True
    assert snapshot["gate_state"]["provider_enabled"] is False
    assert snapshot["gate_state"]["executor_enabled"] is False


def test_p1_preview_workspace_natural_language_allowlisted_without_bus() -> None:
    result = handle(_owner_private("艾萨克 看一下工作区情况"))

    assert result.handled is True
    assert result.allowed is True
    assert result.reason == "would_dispatch_dry_run"
    assert result.task_type == "workspace_report"
    assert result.task_request is None
    assert "intent=workspace_report" in result.reply
    assert "不真实派发 TaskRequest" in result.reply


def test_p1_preview_ambiguous_requires_clarification_without_dispatch() -> None:
    result = handle(_owner_private("I叔 你看这个是不是有问题？"))

    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "clarification_required"
    assert result.task_type is None
    assert result.task_request is None
    assert result.task_result is None
    assert result.intent_preview is not None
    assert result.intent_preview["decision"] == "clarification_required"
    assert result.intent_preview["would_dispatch_task_type"] is None
    assert "I叔 P1 preview" in result.reply
    assert "clarification_required" in result.reply
    assert "task_request_dispatched=false" in result.reply


def test_p1_preview_high_risk_blocked_before_any_dispatch() -> None:
    result = handle(_owner_private("I叔 帮我部署并 systemctl restart 服务"))

    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "high_risk_blocked"
    assert result.task_request is None
    assert result.task_result is None
    assert result.worker_result is None
    assert "high_risk_blocked" in result.reply


def test_p1_preview_keeps_explicit_p0_commands_on_p0_path() -> None:
    cases = [
        ("I叔 help", "help_report"),
        ("I叔 health", "health_report"),
        ("I叔 workspace report", "workspace_report"),
        ("I叔 dry_run plan", "dry_run_plan"),
    ]
    for text, task_type in cases:
        result = handle(_owner_private(text))
        assert result.handled is True
        assert result.allowed is True
        assert result.reason == "pass"
        assert result.task_type == task_type
        assert result.task_request is not None
        assert result.task_result is not None
        assert result.worker_result is not None
        assert result.intent_preview is None
        assert "I叔 P0 闭环已跑通" in result.reply


def test_p1_preview_does_not_expose_group_or_non_owner_or_english_trigger() -> None:
    group = handle(_owner_group("I叔 看看你现在状态"))
    non_owner = handle(_non_owner_private("I叔 看看你现在状态"))
    english = handle(_owner_private("isaac 看看你现在状态"))
    slash = handle(_owner_private("/isaac 看看你现在状态"))

    assert group.handled is True and group.allowed is False and group.reason == "private_only"
    assert non_owner.handled is True and non_owner.allowed is False and non_owner.reason == "owner_only"
    assert english.handled is False and english.reason == "not_isaac_command"
    assert slash.handled is False and slash.reason == "not_isaac_command"
    assert group.intent_preview is None
    assert non_owner.intent_preview is None
    assert english.intent_preview is None
    assert slash.intent_preview is None


def test_p1_preview_payload_contains_no_raw_private_or_bus_material() -> None:
    raw = "麻烦 I叔 看看你现在状态"
    result = handle(_owner_private(raw))

    serialized = json.dumps([result.intent_preview, result.task_request, result.task_result], ensure_ascii=False, sort_keys=True)
    assert raw not in serialized
    assert "335059272" not in serialized
    assert "I叔 P0 闭环已跑通" in result.reply
    assert "readonly_health_snapshot=" in result.reply
    assert result.task_request is not None
    assert result.task_result is not None
    assert result.worker_result is not None
    assert result.worker_result["readonly_health_snapshot"]["read_only"] is True
