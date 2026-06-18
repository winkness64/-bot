from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

BRIDGE_PATH = Path(__file__).resolve().parents[1] / "src" / "plugins" / "yangyang" / "core" / "isaac_intent_provider_bridge_p15.py"
BRIDGE_SPEC = importlib.util.spec_from_file_location("isaac_intent_provider_bridge_p15_under_test", BRIDGE_PATH)
assert BRIDGE_SPEC is not None and BRIDGE_SPEC.loader is not None
bridge_mod = importlib.util.module_from_spec(BRIDGE_SPEC)
sys.modules[BRIDGE_SPEC.name] = bridge_mod
BRIDGE_SPEC.loader.exec_module(bridge_mod)

P0_PATH = Path(__file__).resolve().parents[1] / "src" / "plugins" / "yangyang" / "core" / "isaac_agent_bus_p0.py"
P0_SPEC = importlib.util.spec_from_file_location("isaac_agent_bus_p0_p1_5_under_test", P0_PATH)
assert P0_SPEC is not None and P0_SPEC.loader is not None
p0_mod = importlib.util.module_from_spec(P0_SPEC)
sys.modules[P0_SPEC.name] = p0_mod
P0_SPEC.loader.exec_module(p0_mod)

IntentProviderBridgeConfig = bridge_mod.IntentProviderBridgeConfig
build_provider = bridge_mod.build_intent_provider_from_bridge_config
dry_run_bridge = bridge_mod.dry_run_intent_provider_bridge
fixture_provider = bridge_mod.fixture_intent_provider
handle = p0_mod.handle_isaac_agent_bus_p0_message


def _owner_private(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, raw_content=text, channel="private", is_owner=True)


def _owner_group(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, raw_content=text, channel="group", is_owner=True, group_id="137918147")


def _non_owner_private(text: str) -> SimpleNamespace:
    return SimpleNamespace(text=text, raw_content=text, channel="private", is_owner=False)


def test_p1_5_default_config_is_off_and_returns_no_provider() -> None:
    assert build_provider(None) is None
    assert build_provider({}) is None
    assert build_provider({"enabled": False, "provider_mode": "fixture"}) is None
    assert build_provider(IntentProviderBridgeConfig(enabled=False, provider_mode="fixture")) is None

    bridge = dry_run_bridge(_owner_private("你帮我让 I叔 看下系统情况"))
    assert bridge.handled is True
    assert bridge.allowed is False
    assert bridge.reason == "provider_bridge_disabled"
    assert bridge.provider_called is False
    assert bridge.intent_preview is None


def test_p1_5_fixture_provider_only_emits_provider_contract_preview_shape() -> None:
    payload = fixture_provider("你帮我让 看下系统情况")

    assert payload == {
        "intent": "health_report",
        "confidence": 0.92,
        "risk_level": "low",
        "needs_confirmation": False,
        "reason": "p1_5_fixture_matched:health_report",
        "source": "p1_5_fixture_provider",
    }


def test_p1_5_enabled_fixture_bridge_owner_private_health_preview_only() -> None:
    bridge = dry_run_bridge(
        _owner_private("你帮我让 I叔 看下系统情况"),
        {"enabled": True, "provider_mode": "fixture"},
    )

    assert bridge.handled is True
    assert bridge.allowed is True
    assert bridge.reason == "would_dispatch_dry_run"
    assert bridge.provider_called is True
    assert bridge.intent_preview is not None
    assert bridge.intent_preview["schema_version"] == bridge_mod.P1_5_BRIDGE_SCHEMA_VERSION
    assert bridge.intent_preview["decision"] == "would_dispatch_dry_run"
    assert bridge.intent_preview["candidate"]["intent"] == "health_report"
    assert bridge.intent_preview["candidate"]["source"] == "p1_5_fixture_provider"
    assert bridge.intent_preview["provider_bridge_enabled"] is True
    assert bridge.intent_preview["provider_mode"] == "fixture"
    assert bridge.intent_preview["provider_called"] is True
    assert bridge.intent_preview["provider_network_used"] is False
    assert bridge.intent_preview["provider_authorized"] is False
    assert bridge.intent_preview["authorization_source"] == "code_gate_only"
    assert bridge.intent_preview["no_real_dispatch"] is True
    assert bridge.intent_preview["agent_bus_used"] is False
    assert bridge.intent_preview["task_request_dispatched"] is False
    assert bridge.intent_preview["executor_enabled"] is False
    assert "provider_network_used=false" in bridge.reply
    assert "provider_authorized=false" in bridge.reply


def test_p1_5_p0_handler_bridge_config_is_default_off_but_can_use_fixture_when_enabled() -> None:
    default_off = handle(_owner_private("你帮我让 I叔 看下系统情况"), intent_provider_bridge_config={})
    enabled = handle(_owner_private("你帮我让 I叔 看下系统情况"), intent_provider_bridge_config={"enabled": True, "provider_mode": "fixture"})

    assert default_off.handled is True
    assert default_off.allowed is True
    assert default_off.reason == "pass"
    assert default_off.task_type == "health_report"
    assert default_off.task_request is not None
    assert default_off.worker_result is not None
    assert default_off.intent_preview is None
    assert default_off.worker_result["readonly_health_snapshot"]["external_effects"]["provider_network_used"] is False

    assert enabled.handled is True
    assert enabled.allowed is True
    assert enabled.reason == "would_dispatch_dry_run"
    assert enabled.task_type == "health_report"
    assert enabled.task_request is None
    assert enabled.task_result is None
    assert enabled.worker_result is None
    assert enabled.intent_preview is not None
    assert enabled.intent_preview["candidate"]["source"] == "p1_5_fixture_provider"
    assert enabled.intent_preview["raw_model_output"]["source"] == "p1_5_fixture_provider"
    assert enabled.intent_preview["provider_network_used"] is False
    assert enabled.intent_preview["task_request_dispatched"] is False
    assert enabled.intent_preview["agent_bus_used"] is False
    assert enabled.intent_preview["executor_enabled"] is False
    assert "不真实派发 TaskRequest" in enabled.reply


def test_p1_5_group_and_non_owner_do_not_trigger_or_expose_fixture_bridge() -> None:
    config = {"enabled": True, "provider_mode": "fixture"}

    group_bridge = dry_run_bridge(_owner_group("你帮我让 I叔 看下系统情况"), config)
    non_owner_bridge = dry_run_bridge(_non_owner_private("你帮我让 I叔 看下系统情况"), config)
    group_handle = handle(_owner_group("你帮我让 I叔 看下系统情况"), intent_provider_bridge_config=config)
    non_owner_handle = handle(_non_owner_private("你帮我让 I叔 看下系统情况"), intent_provider_bridge_config=config)

    assert group_bridge.handled is True and group_bridge.allowed is False and group_bridge.reason == "private_only"
    assert non_owner_bridge.handled is True and non_owner_bridge.allowed is False and non_owner_bridge.reason == "owner_only"
    assert group_bridge.provider_called is False
    assert non_owner_bridge.provider_called is False
    assert group_bridge.intent_preview is None
    assert non_owner_bridge.intent_preview is None

    assert group_handle.handled is True and group_handle.allowed is False and group_handle.reason == "private_only"
    assert non_owner_handle.handled is True and non_owner_handle.allowed is False and non_owner_handle.reason == "owner_only"
    assert group_handle.intent_preview is None
    assert non_owner_handle.intent_preview is None
    assert "I叔 P1 preview" not in group_handle.reply
    assert "I叔 P1 preview" not in non_owner_handle.reply


def test_p1_5_high_risk_blocks_before_fixture_provider_and_has_no_preview() -> None:
    config = {"enabled": True, "provider_mode": "fixture"}

    bridge = dry_run_bridge(_owner_private("让 I叔 systemctl restart 服务并看状态"), config)
    handled = handle(_owner_private("让 I叔 systemctl restart 服务并看状态"), intent_provider_bridge_config=config)

    assert bridge.handled is True
    assert bridge.allowed is False
    assert bridge.reason == "high_risk_blocked"
    assert bridge.provider_called is False
    assert bridge.intent_preview is None

    assert handled.handled is True
    assert handled.allowed is False
    assert handled.reason == "high_risk_blocked"
    assert handled.task_request is None
    assert handled.task_result is None
    assert handled.worker_result is None
    assert handled.intent_preview is None


def test_p1_5_fixture_bridge_clarification_preview_still_no_dispatch_or_authorization() -> None:
    bridge = dry_run_bridge(
        _owner_private("你让 I叔 看看这个"),
        {"enabled": True, "provider_mode": "fixture"},
    )

    assert bridge.handled is True
    assert bridge.allowed is False
    assert bridge.reason == "clarification_required"
    assert bridge.provider_called is True
    assert bridge.intent_preview is not None
    assert bridge.intent_preview["decision"] == "clarification_required"
    assert bridge.intent_preview["candidate"]["intent"] == "unknown"
    assert bridge.intent_preview["provider_authorized"] is False
    assert bridge.intent_preview["authorization_source"] == "code_gate_only"
    assert bridge.intent_preview["task_request_dispatched"] is False
    assert bridge.intent_preview["agent_bus_used"] is False
    assert bridge.intent_preview["executor_enabled"] is False


def test_p1_5_preview_payload_contains_no_raw_private_text_or_protected_material() -> None:
    raw = "让 I叔 给我整理一下今天维护进度"
    bridge = dry_run_bridge(_owner_private(raw), {"enabled": True, "provider_mode": "fixture"})

    serialized = json.dumps(bridge.intent_preview, ensure_ascii=False, sort_keys=True)
    assert raw not in serialized
    assert "335059272" not in serialized
    assert "runtime_config" not in serialized
    assert ".env" not in serialized
    assert "long_term/memories.jsonl" not in serialized
    assert bridge.intent_preview is not None
    assert bridge.intent_preview["no_real_dispatch"] is True



def _preview_fingerprint(result: SimpleNamespace) -> tuple[object, ...]:
    preview = result.intent_preview or {}
    candidate = preview.get("candidate") or {}
    return (
        result.handled,
        result.allowed,
        result.reason,
        result.task_type,
        result.task_request is None,
        result.task_result is None,
        result.worker_result is None,
        preview.get("decision"),
        preview.get("would_dispatch_task_type"),
        candidate.get("intent"),
        candidate.get("source"),
        preview.get("no_real_dispatch"),
        preview.get("agent_bus_used"),
        preview.get("task_request_dispatched"),
        preview.get("executor_enabled"),
        preview.get("provider_network_used"),
    )


def test_p1_5_1_no_bridge_config_preserves_p1_4_mock_preview_behavior() -> None:
    raw = "让 I叔 给我整理一下今天维护进度"

    without_arg = handle(_owner_private(raw))
    none_config = handle(_owner_private(raw), intent_provider_bridge_config=None)
    empty_config = handle(_owner_private(raw), intent_provider_bridge_config={})

    assert _preview_fingerprint(without_arg) == _preview_fingerprint(none_config)
    assert _preview_fingerprint(without_arg) == _preview_fingerprint(empty_config)
    assert without_arg.reason == "would_dispatch_dry_run"
    assert without_arg.task_type == "workspace_report"
    assert without_arg.intent_preview is not None
    assert without_arg.intent_preview["candidate"]["source"] == "mock_llm_rules"
    assert without_arg.intent_preview["provider_network_used"] is False
    assert "provider_bridge_enabled" not in without_arg.intent_preview


def test_p1_5_1_fixture_mode_requires_explicit_enabled_fixture_config() -> None:
    raw = "你帮我让 I叔 看下系统情况"
    disabled_variants = [
        None,
        {},
        {"provider_mode": "fixture"},
        {"enabled": False, "provider_mode": "fixture"},
        {"enabled": True, "provider_mode": "disabled"},
        {"enabled": True, "provider_mode": "real_provider"},
    ]

    for cfg in disabled_variants:
        result = handle(_owner_private(raw), intent_provider_bridge_config=cfg)
        assert result.handled is True
        assert result.allowed is True
        assert result.reason == "pass"
        assert result.task_type == "health_report"
        assert result.intent_preview is None
        assert result.task_request is not None
        assert result.worker_result is not None
        assert result.worker_result["readonly_health_snapshot"]["external_effects"]["provider_network_used"] is False

    enabled = handle(
        _owner_private(raw),
        intent_provider_bridge_config={"enabled": True, "provider_mode": "fixture", "fixture_name": "natural_alias_fixture_v1"},
    )
    assert enabled.intent_preview is not None
    assert enabled.intent_preview["candidate"]["source"] == "p1_5_fixture_provider"
    assert enabled.intent_preview["provider_network_used"] is False
    assert enabled.task_request is None


def test_p1_5_1_default_disabled_bridge_does_not_construct_or_call_fixture_provider() -> None:
    original = bridge_mod.make_fixture_intent_provider
    calls: list[str] = []

    def forbidden_fixture_factory(fixture_name: str = "natural_alias_fixture_v1") -> object:
        calls.append(fixture_name)
        raise AssertionError("fixture provider must not be constructed while bridge is disabled")

    bridge_mod.make_fixture_intent_provider = forbidden_fixture_factory
    try:
        for cfg in (None, {}, {"provider_mode": "fixture"}, {"enabled": False, "provider_mode": "fixture"}):
            provider = build_provider(cfg)
            bridge = dry_run_bridge(_owner_private("你帮我让 I叔 看下系统情况"), cfg)
            assert provider is None
            assert bridge.provider_called is False
            assert bridge.intent_preview is None
            assert bridge.reason == "provider_bridge_disabled"
    finally:
        bridge_mod.make_fixture_intent_provider = original

    assert calls == []


def test_p1_5_1_group_non_owner_and_high_risk_do_not_build_or_call_bridge_provider() -> None:
    original = p0_mod.build_intent_provider_from_bridge_config
    calls: list[object] = []

    def forbidden_builder(config: object) -> object:
        calls.append(config)
        raise AssertionError("provider bridge builder must not be reached before pre-gates")

    p0_mod.build_intent_provider_from_bridge_config = forbidden_builder
    cfg = {"enabled": True, "provider_mode": "fixture"}
    try:
        group = handle(_owner_group("你帮我让 I叔 看下系统情况"), intent_provider_bridge_config=cfg)
        non_owner = handle(_non_owner_private("你帮我让 I叔 看下系统情况"), intent_provider_bridge_config=cfg)
        high = handle(_owner_private("让 I叔 systemctl restart 服务并看状态"), intent_provider_bridge_config=cfg)
    finally:
        p0_mod.build_intent_provider_from_bridge_config = original

    assert calls == []
    assert group.reason == "private_only" and group.intent_preview is None and group.task_request is None
    assert non_owner.reason == "owner_only" and non_owner.intent_preview is None and non_owner.task_request is None
    assert high.reason == "high_risk_blocked" and high.intent_preview is None and high.task_request is None


def test_p1_5_1_provider_invalid_unknown_and_high_risk_alias_outputs_fail_closed() -> None:
    raw = "让 I叔 看下系统情况"
    provider_calls: list[str] = []

    def invalid_provider(command_text: str) -> dict[str, object]:
        provider_calls.append(command_text)
        return {
            "intent": "health_report",
            "risk_level": "low",
            "needs_confirmation": False,
            "reason": "missing confidence fixture",
            "source": "p1_5_1_negative_fixture",
        }

    invalid = handle(_owner_private(raw), intent_provider=invalid_provider)
    assert invalid.handled is True
    assert invalid.allowed is False
    assert invalid.reason == "invalid_intent_schema"
    assert invalid.task_request is None
    assert invalid.task_result is None
    assert invalid.worker_result is None
    assert invalid.intent_preview is not None
    assert invalid.intent_preview["decision"] == "blocked"
    assert invalid.intent_preview["task_request_dispatched"] is False

    unknown = handle(
        _owner_private(raw),
        intent_provider=lambda _text: {
            "intent": "tell_joke",
            "confidence": 0.88,
            "risk_level": "low",
            "needs_confirmation": False,
            "reason": "unknown low risk fixture",
            "source": "p1_5_1_negative_fixture",
        },
    )
    assert unknown.handled is True
    assert unknown.allowed is False
    assert unknown.reason == "clarification_required"
    assert unknown.task_request is None
    assert unknown.intent_preview is not None
    assert unknown.intent_preview["candidate"]["intent"] == "tell_joke"
    assert unknown.intent_preview["would_dispatch_task_type"] is None
    assert unknown.intent_preview["task_request_dispatched"] is False

    high_alias = handle(
        _owner_private(raw),
        intent_provider=lambda _text: {
            "intent": "restart_service",
            "confidence": 0.91,
            "risk_level": "low",
            "needs_confirmation": False,
            "reason": "high risk alias fixture",
            "source": "p1_5_1_negative_fixture",
        },
    )
    assert high_alias.handled is True
    assert high_alias.allowed is False
    assert high_alias.reason == "high_risk_blocked"
    assert high_alias.task_request is None
    assert high_alias.intent_preview is not None
    assert high_alias.intent_preview["candidate"]["intent"] == "restart_service"
    assert high_alias.intent_preview["task_request_dispatched"] is False
    assert high_alias.intent_preview["agent_bus_used"] is False
    assert high_alias.intent_preview["executor_enabled"] is False

    assert provider_calls == ["让 看下系统情况"]


def test_p1_5_1_english_isaac_still_does_not_trigger_even_with_bridge_enabled() -> None:
    cfg = {"enabled": True, "provider_mode": "fixture"}

    for raw in ("isaac 看看系统情况", "/isaac health", "ask isaac for status"):
        bridge = dry_run_bridge(_owner_private(raw), cfg)
        result = handle(_owner_private(raw), intent_provider_bridge_config=cfg)
        assert bridge.handled is False
        assert bridge.provider_called is False
        assert bridge.intent_preview is None
        assert result.handled is False
        assert result.reason == "not_isaac_command"
        assert result.intent_preview is None
        assert result.task_request is None


def test_p1_5_1_explicit_p0_commands_have_priority_over_enabled_bridge() -> None:
    original = p0_mod.build_intent_provider_from_bridge_config
    calls: list[object] = []

    def forbidden_builder(config: object) -> object:
        calls.append(config)
        raise AssertionError("P0 explicit commands must not consult provider bridge")

    p0_mod.build_intent_provider_from_bridge_config = forbidden_builder
    cfg = {"enabled": True, "provider_mode": "fixture"}
    try:
        cases = [
            ("I叔 help", "help_report"),
            ("I叔 health", "health_report"),
            ("I叔 workspace report", "workspace_report"),
            ("I叔 dry_run plan", "dry_run_plan"),
        ]
        for raw, task_type in cases:
            result = handle(_owner_private(raw), intent_provider_bridge_config=cfg)
            assert result.handled is True
            assert result.allowed is True
            assert result.reason == "pass"
            assert result.task_type == task_type
            assert result.intent_preview is None
            assert result.task_request is not None
            assert result.task_result is not None
            assert result.worker_result is not None
            assert result.worker_result["executor_enabled"] is False
    finally:
        p0_mod.build_intent_provider_from_bridge_config = original

    assert calls == []


def test_p1_5_1_unsupported_fixture_name_fails_closed_without_dispatch() -> None:
    bridge = dry_run_bridge(
        _owner_private("你帮我让 I叔 看下系统情况"),
        {"enabled": True, "provider_mode": "fixture", "fixture_name": "unsupported_fixture"},
    )

    assert bridge.handled is True
    assert bridge.allowed is False
    assert bridge.reason == "provider_exception"
    assert bridge.provider_called is True
    assert bridge.intent_preview is not None
    assert bridge.intent_preview["decision"] == "blocked"
    assert bridge.intent_preview["task_request_dispatched"] is False
    assert bridge.intent_preview["agent_bus_used"] is False
    assert bridge.intent_preview["executor_enabled"] is False
    assert bridge.intent_preview["provider_network_used"] is False
