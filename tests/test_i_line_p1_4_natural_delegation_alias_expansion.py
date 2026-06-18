from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from typing import Any

INTENT_PATH = Path(__file__).resolve().parents[1] / "src" / "plugins" / "yangyang" / "core" / "isaac_intent_p1.py"
INTENT_SPEC = importlib.util.spec_from_file_location("isaac_intent_p1_p1_4_under_test", INTENT_PATH)
assert INTENT_SPEC is not None and INTENT_SPEC.loader is not None
intent_mod = importlib.util.module_from_spec(INTENT_SPEC)
sys.modules[INTENT_SPEC.name] = intent_mod
INTENT_SPEC.loader.exec_module(intent_mod)

P0_PATH = Path(__file__).resolve().parents[1] / "src" / "plugins" / "yangyang" / "core" / "isaac_agent_bus_p0.py"
P0_SPEC = importlib.util.spec_from_file_location("isaac_agent_bus_p0_p1_4_under_test", P0_PATH)
assert P0_SPEC is not None and P0_SPEC.loader is not None
p0_mod = importlib.util.module_from_spec(P0_SPEC)
sys.modules[P0_SPEC.name] = p0_mod
P0_SPEC.loader.exec_module(p0_mod)

parse_intent_dry_run = intent_mod.parse_intent_dry_run
parse_intent_with_provider_dry_run = intent_mod.parse_intent_with_provider_dry_run
normalize_intent_alias = intent_mod.normalize_intent_alias
handle = p0_mod.handle_isaac_agent_bus_p0_message


def _owner_private(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, raw_content=text, channel="private", is_owner=True)


def _owner_group(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, raw_content=text, channel="group", is_owner=True, group_id="137918147")


def _non_owner_private(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, raw_content=text, channel="private", is_owner=False)


def _assert_parse(text: str, task_type: str) -> None:
    d = parse_intent_dry_run(text)
    assert d.handled is True
    assert d.allowed is True
    assert d.decision == "would_dispatch_dry_run"
    assert d.reason == "intent_allowlisted_low_risk"
    assert d.would_dispatch_task_type == task_type
    assert d.candidate is not None
    assert d.candidate.intent == task_type
    assert d.candidate.source == "mock_llm_rules"
    assert d.raw_model_output is not None
    assert d.raw_model_output["intent"] == task_type
    assert str(d.raw_model_output["reason"]).startswith("p1_4_natural_alias_matched")


def _assert_handler_preview(text: str, task_type: str) -> None:
    result = handle(_owner_private(text))
    assert result.handled is True
    assert result.allowed is True
    assert result.task_type == task_type
    if task_type == "health_report":
        assert result.reason == "pass"
        assert result.task_request is not None
        assert result.task_result is not None
        assert result.worker_result is not None
        assert result.intent_preview is None
        assert "I叔 P1 preview" not in result.reply
        assert "readonly_health_snapshot=" in result.reply
        assert result.worker_result["readonly_health_snapshot"]["read_only"] is True
        return
    assert result.reason == "would_dispatch_dry_run"
    assert result.task_request is None
    assert result.task_result is None
    assert result.worker_result is None
    assert result.intent_preview is not None
    assert result.intent_preview["decision"] == "would_dispatch_dry_run"
    assert result.intent_preview["would_dispatch_task_type"] == task_type
    assert result.intent_preview["candidate"]["intent"] == task_type
    assert result.intent_preview["candidate"]["source"] == "mock_llm_rules"
    assert result.intent_preview["no_real_dispatch"] is True
    assert result.intent_preview["agent_bus_used"] is False
    assert result.intent_preview["task_request_dispatched"] is False
    assert result.intent_preview["executor_enabled"] is False
    assert result.intent_preview["provider_network_used"] is False
    assert "I叔 P1 preview" in result.reply
    assert f"intent={task_type}" in result.reply
    assert f"would_dispatch_task_type={task_type}" in result.reply
    assert "不真实派发 TaskRequest" in result.reply


def test_p1_4_health_natural_aliases_normalize_without_provider() -> None:
    cases = [
        "你帮我让 I叔 看下系统情况",
        "帮我叫艾萨克看看现在有没有异常",
        "麻烦 I叔 巡检一下运行情况",
        "问问 I叔 现在还好吗",
    ]
    for text in cases:
        _assert_parse(text, "health_report")
        _assert_handler_preview(text, "health_report")


def test_p1_4_workspace_natural_aliases_normalize_without_provider() -> None:
    cases = [
        "让 I叔 汇报下维护内容",
        "让 I叔 给我整理一下今天维护进度",
        "叫艾萨克说下项目进度",
        "让 I叔 整理工作进展",
    ]
    for text in cases:
        _assert_parse(text, "workspace_report")
        _assert_handler_preview(text, "workspace_report")


def test_p1_4_dry_run_plan_natural_aliases_normalize_without_provider() -> None:
    cases = [
        "让 I叔 先别执行，给个落地步骤",
        "叫艾萨克 出个后续计划",
        "让 I叔 预演一下怎么落地",
        "请 I叔 做个行动方案",
    ]
    for text in cases:
        _assert_parse(text, "dry_run_plan")
        _assert_handler_preview(text, "dry_run_plan")


def test_p1_4_help_natural_aliases_normalize_without_provider() -> None:
    cases = [
        "问问 I叔 能干嘛",
        "让艾萨克说下有什么功能",
        "让 I叔 给个使用说明",
        "叫 I叔 列一下可用指令",
    ]
    for text in cases:
        _assert_parse(text, "help_report")
        _assert_handler_preview(text, "help_report")


def test_p1_4_provider_intent_aliases_expand_to_canonical_allowlist() -> None:
    provider_payloads: list[dict[str, Any]] = [
        {"intent": "status", "confidence": 0.90, "risk_level": "low", "needs_confirmation": False, "reason": "alias"},
        {"intent": "project_status", "confidence": 0.90, "risk_level": "low", "needs_confirmation": False, "reason": "alias"},
        {"intent": "rehearsal_plan", "confidence": 0.90, "risk_level": "low", "needs_confirmation": False, "reason": "alias"},
        {"intent": "commands", "confidence": 0.90, "risk_level": "low", "needs_confirmation": False, "reason": "alias"},
    ]
    expected = ["health_report", "workspace_report", "dry_run_plan", "help_report"]

    for payload, task_type in zip(provider_payloads, expected, strict=True):
        d = parse_intent_with_provider_dry_run("让 I叔 做个别名归一测试", provider=lambda _text, payload=payload: payload)
        assert d.allowed is True
        assert d.decision == "would_dispatch_dry_run"
        assert d.would_dispatch_task_type == task_type
        assert d.candidate is not None
        assert d.candidate.intent == task_type
        assert d.raw_model_output is not None
        assert d.raw_model_output["intent"] == payload["intent"]


def test_p1_4_normalize_intent_alias_public_helper() -> None:
    assert normalize_intent_alias("status") == "health_report"
    assert normalize_intent_alias("workspace-status") == "workspace_report"
    assert normalize_intent_alias("dry run") == "dry_run_plan"
    assert normalize_intent_alias("command list") == "help_report"
    assert normalize_intent_alias("high_risk_blocked") == "blocked_high_risk"


def test_p1_4_ambiguous_and_high_risk_still_fail_closed() -> None:
    ambiguous = handle(_owner_private("你让 I叔 看看这个"))
    assert ambiguous.handled is True
    assert ambiguous.allowed is False
    assert ambiguous.reason == "clarification_required"
    assert ambiguous.intent_preview is not None
    assert ambiguous.intent_preview["decision"] == "clarification_required"
    assert ambiguous.task_request is None

    high = handle(_owner_private("让 I叔 systemctl restart 服务并看状态"))
    assert high.handled is True
    assert high.allowed is False
    assert high.reason == "high_risk_blocked"
    assert high.intent_preview is None
    assert high.task_request is None


def test_p1_4_group_and_non_owner_do_not_expose_preview_or_call_provider() -> None:
    called = False

    def provider(_command_text: str) -> str:
        nonlocal called
        called = True
        return json.dumps({
            "intent": "health_report",
            "confidence": 0.9,
            "risk_level": "low",
            "needs_confirmation": False,
            "reason": "must not call",
        })

    group = handle(_owner_group("你帮我让 I叔 看下系统情况"), intent_provider=provider)
    non_owner = handle(_non_owner_private("你帮我让 I叔 看下系统情况"), intent_provider=provider)

    assert called is False
    assert group.handled is True and group.allowed is False and group.reason == "private_only"
    assert non_owner.handled is True and non_owner.allowed is False and non_owner.reason == "owner_only"
    assert group.intent_preview is None
    assert non_owner.intent_preview is None


def test_p1_4_preview_payload_contains_no_task_dispatch_or_raw_private_text() -> None:
    raw = "让 I叔 给我整理一下今天维护进度"
    result = handle(_owner_private(raw))
    serialized = json.dumps([result.intent_preview, result.task_request, result.task_result], ensure_ascii=False, sort_keys=True)

    assert raw not in serialized
    assert result.task_request is None
    assert result.task_result is None
    assert result.worker_result is None
    assert result.intent_preview is not None
    assert result.intent_preview["task_request_dispatched"] is False
    assert result.intent_preview["agent_bus_used"] is False
    assert result.intent_preview["executor_enabled"] is False
