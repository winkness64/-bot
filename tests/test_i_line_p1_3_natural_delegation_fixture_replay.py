from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any, Callable

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "plugins" / "yangyang" / "core" / "isaac_agent_bus_p0.py"
SPEC = importlib.util.spec_from_file_location("isaac_agent_bus_p0_p1_3_fixture_replay_under_test", MODULE_PATH)
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


def _fixture_json(intent: str, *, reason: str = "fixture replay", confidence: float = 0.93) -> str:
    return json.dumps(
        {
            "intent": intent,
            "confidence": confidence,
            "risk_level": "low",
            "needs_confirmation": False,
            "reason": reason,
            "source": "p1_3_fixture_provider",
        },
        ensure_ascii=False,
    )


def _provider_for(intent: str, seen: list[str] | None = None) -> Callable[[str], str]:
    def provider(command_text: str) -> str:
        if seen is not None:
            seen.append(command_text)
        return _fixture_json(intent, reason=f"fixture says {intent}")

    return provider


def _assert_preview_would_dispatch(result: Any, task_type: str) -> None:
    assert result.handled is True
    assert result.allowed is True
    assert result.reason == "would_dispatch_dry_run"
    assert result.task_type == task_type
    assert result.task_request is None
    assert result.task_result is None
    assert result.worker_result is None
    assert result.intent_preview is not None
    assert result.intent_preview["decision"] == "would_dispatch_dry_run"
    assert result.intent_preview["would_dispatch_task_type"] == task_type
    assert result.intent_preview["no_real_dispatch"] is True
    assert result.intent_preview["agent_bus_used"] is False
    assert result.intent_preview["task_request_dispatched"] is False
    assert result.intent_preview["executor_enabled"] is False
    assert result.intent_preview["provider_network_used"] is False
    assert result.intent_preview["candidate"]["source"] == "p1_3_fixture_provider"
    assert result.intent_preview["raw_model_output"]["source"] == "p1_3_fixture_provider"
    assert "I叔 P1 preview" in result.reply
    assert "would_dispatch_dry_run" in result.reply
    assert f"intent={task_type}" in result.reply
    assert f"would_dispatch_task_type={task_type}" in result.reply
    assert "no_real_dispatch=true" in result.reply
    assert "agent_bus_used=false" in result.reply
    assert "task_request_dispatched=false" in result.reply
    assert "executor_enabled=false" in result.reply
    assert "provider_network_used=false" in result.reply
    assert "不真实派发 TaskRequest" in result.reply


def test_p1_3_owner_natural_delegation_system_status_replays_health_fixture() -> None:
    seen: list[str] = []

    result = handle(_owner_private("你帮我让 I叔 看下系统情况"), intent_provider=_provider_for("health_report", seen))

    assert seen == ["你帮我让 看下系统情况"]
    _assert_preview_would_dispatch(result, "health_report")


def test_p1_3_owner_natural_delegation_abnormal_check_replays_health_fixture() -> None:
    seen: list[str] = []

    result = handle(_owner_private("帮我叫艾萨克看看现在有没有异常"), intent_provider=_provider_for("health_report", seen))

    assert seen == ["帮我叫 看看现在有没有异常"]
    _assert_preview_would_dispatch(result, "health_report")


def test_p1_3_owner_natural_delegation_maintenance_content_replays_workspace_fixture() -> None:
    seen: list[str] = []

    result = handle(_owner_private("让 I叔 汇报下维护内容"), intent_provider=_provider_for("workspace_report", seen))

    assert seen == ["让 汇报下维护内容"]
    _assert_preview_would_dispatch(result, "workspace_report")


def test_p1_3_owner_natural_delegation_maintenance_progress_replays_workspace_fixture() -> None:
    seen: list[str] = []

    result = handle(_owner_private("让 I叔 给我整理一下今天维护进度"), intent_provider=_provider_for("workspace_report", seen))

    assert seen == ["让 给我整理一下今天维护进度"]
    _assert_preview_would_dispatch(result, "workspace_report")


def test_p1_3_high_risk_input_blocks_before_fixture_provider_even_if_fixture_allows() -> None:
    called = False

    def provider(_command_text: str) -> str:
        nonlocal called
        called = True
        return _fixture_json("health_report")

    result = handle(_owner_private("你让 I叔 重启服务"), intent_provider=provider)

    assert called is False
    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "high_risk_blocked"
    assert result.task_request is None
    assert result.task_result is None
    assert result.worker_result is None
    assert result.intent_preview is None
    assert "reason=high_risk_blocked" in result.reply


def test_p1_3_group_natural_delegation_does_not_expose_preview_or_call_provider() -> None:
    called = False

    def provider(_command_text: str) -> str:
        nonlocal called
        called = True
        return _fixture_json("health_report")

    result = handle(_owner_group("你帮我让 I叔 看下系统情况"), intent_provider=provider)

    assert called is False
    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "private_only"
    assert result.task_request is None
    assert result.task_result is None
    assert result.intent_preview is None
    assert "reason=private_only" in result.reply
    assert "I叔 P1 preview" not in result.reply


def test_p1_3_non_owner_natural_delegation_does_not_preview_or_call_provider() -> None:
    called = False

    def provider(_command_text: str) -> str:
        nonlocal called
        called = True
        return _fixture_json("health_report")

    result = handle(_non_owner_private("你帮我让 I叔 看下系统情况"), intent_provider=provider)

    assert called is False
    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "owner_only"
    assert result.task_request is None
    assert result.task_result is None
    assert result.intent_preview is None
    assert "reason=owner_only" in result.reply
    assert "I叔 P1 preview" not in result.reply


def test_p1_3_provider_exception_blocks_preview_without_raising() -> None:
    def provider(_command_text: str) -> str:
        raise RuntimeError("fixture provider boom")

    result = handle(_owner_private("让 I叔 汇报下维护内容"), intent_provider=provider)

    assert result.handled is True
    assert result.allowed is False
    assert result.reason == "provider_exception"
    assert result.task_type is None
    assert result.task_request is None
    assert result.task_result is None
    assert result.worker_result is None
    assert result.intent_preview is not None
    assert result.intent_preview["decision"] == "blocked"
    assert result.intent_preview["reason"] == "provider_exception"
    assert result.intent_preview["would_dispatch_task_type"] is None
    assert result.intent_preview["raw_model_output"]["error"] == "provider_exception"
    assert result.intent_preview["raw_model_output"]["exception_type"] == "RuntimeError"
    assert result.intent_preview["no_real_dispatch"] is True
    assert result.intent_preview["task_request_dispatched"] is False
    assert "I叔 P1 preview" in result.reply
    assert "reason=provider_exception" in result.reply
    assert "不真实派发 TaskRequest" in result.reply


def test_p1_3_explicit_p0_command_still_wins_over_fixture_provider() -> None:
    called = False

    def provider(_command_text: str) -> str:
        nonlocal called
        called = True
        raise AssertionError("fixture provider must not be called for explicit P0 command")

    result = handle(_owner_private("I叔 health"), intent_provider=provider)

    assert called is False
    assert result.handled is True
    assert result.allowed is True
    assert result.reason == "pass"
    assert result.task_type == "health_report"
    assert result.task_request is not None
    assert result.task_result is not None
    assert result.worker_result is not None
    assert result.intent_preview is None
    assert "I叔 P0 闭环已跑通" in result.reply
