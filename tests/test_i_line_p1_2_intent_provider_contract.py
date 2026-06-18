from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
from typing import Any

MODULE_PATH = Path(__file__).resolve().parents[1] / "src" / "plugins" / "yangyang" / "core" / "isaac_intent_p1.py"
SPEC = importlib.util.spec_from_file_location("isaac_intent_p1_p1_2_under_test", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mod = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mod
SPEC.loader.exec_module(mod)

parse_intent_with_provider_dry_run = mod.parse_intent_with_provider_dry_run
parse_intent_dry_run = mod.parse_intent_dry_run
decision_to_json = mod.decision_to_json


def _health_fixture(**overrides: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "intent": "health_report",
        "confidence": 0.93,
        "risk_level": "low",
        "needs_confirmation": False,
        "reason": "fixture health replay",
        "source": "fixture_provider",
    }
    payload.update(overrides)
    return payload


def test_p1_2_fixture_provider_health_report_would_dispatch_dry_run() -> None:
    seen: list[str] = []

    def provider(command_text: str) -> dict[str, Any]:
        seen.append(command_text)
        return _health_fixture()

    d = parse_intent_with_provider_dry_run("麻烦 I叔 看看你现在状态", provider=provider)

    assert seen == ["麻烦 看看你现在状态"]
    assert d.handled is True
    assert d.allowed is True
    assert d.decision == "would_dispatch_dry_run"
    assert d.reason == "intent_allowlisted_low_risk"
    assert d.would_dispatch_task_type == "health_report"
    assert d.candidate is not None
    assert d.candidate.intent == "health_report"
    assert d.candidate.source == "fixture_provider"
    assert "不真实派发" in d.reply


def test_p1_2_provider_json_string_parses_correctly() -> None:
    def provider(command_text: str) -> str:
        assert command_text == "做个 dry_run plan"
        return json.dumps(
            {
                "intent": "dry_run_plan",
                "confidence": 0.86,
                "risk_level": "low",
                "needs_confirmation": False,
                "reason": "json string fixture",
            }
        )

    d = parse_intent_with_provider_dry_run("I叔 做个 dry_run plan", provider=provider)

    assert d.allowed is True
    assert d.decision == "would_dispatch_dry_run"
    assert d.would_dispatch_task_type == "dry_run_plan"
    assert d.candidate is not None
    assert d.candidate.source == "provider_contract"
    assert d.raw_model_output is not None
    assert d.raw_model_output["intent"] == "dry_run_plan"


def test_p1_2_invalid_json_blocks_invalid_schema_without_exception() -> None:
    d = parse_intent_with_provider_dry_run("I叔 看状态", provider=lambda _text: "not-json")

    assert d.handled is True
    assert d.allowed is False
    assert d.decision == "blocked"
    assert d.reason == "invalid_intent_schema"
    assert d.candidate is None
    assert d.would_dispatch_task_type is None
    assert d.raw_model_output is not None
    assert d.raw_model_output["error"] == "invalid_intent_schema"
    assert d.raw_model_output["detail"] == "invalid_json"


def test_p1_2_missing_confidence_or_risk_level_blocks_invalid_schema() -> None:
    missing_confidence = _health_fixture()
    missing_confidence.pop("confidence")
    missing_risk = _health_fixture()
    missing_risk.pop("risk_level")

    for payload, detail in [(missing_confidence, "missing_confidence"), (missing_risk, "missing_risk_level")]:
        d = parse_intent_with_provider_dry_run("I叔 看状态", provider=lambda _text, payload=payload: payload)
        assert d.allowed is False
        assert d.decision == "blocked"
        assert d.reason == "invalid_intent_schema"
        assert d.raw_model_output is not None
        assert d.raw_model_output["detail"] == detail


def test_p1_2_wrong_field_types_block_invalid_schema() -> None:
    cases = [
        _health_fixture(intent=123),
        _health_fixture(confidence="0.9"),
        _health_fixture(risk_level=1),
        _health_fixture(needs_confirmation="false"),
        _health_fixture(reason={"nested": "no"}),
    ]

    for payload in cases:
        d = parse_intent_with_provider_dry_run("I叔 看状态", provider=lambda _text, payload=payload: payload)
        assert d.allowed is False
        assert d.decision == "blocked"
        assert d.reason == "invalid_intent_schema"
        assert d.would_dispatch_task_type is None


def test_p1_2_confidence_over_one_blocks_invalid_schema() -> None:
    d = parse_intent_with_provider_dry_run("I叔 看状态", provider=lambda _text: _health_fixture(confidence=1.01))

    assert d.handled is True
    assert d.allowed is False
    assert d.decision == "blocked"
    assert d.reason == "invalid_intent_schema"
    assert d.raw_model_output is not None
    assert d.raw_model_output["detail"] == "invalid_confidence_range"


def test_p1_2_high_risk_intent_or_risk_blocks_high_risk() -> None:
    by_intent = parse_intent_with_provider_dry_run(
        "I叔 看状态",
        provider=lambda _text: _health_fixture(intent="systemctl", risk_level="low"),
    )
    by_risk = parse_intent_with_provider_dry_run(
        "I叔 看状态",
        provider=lambda _text: _health_fixture(intent="health_report", risk_level="high"),
    )

    for d in (by_intent, by_risk):
        assert d.handled is True
        assert d.allowed is False
        assert d.decision == "blocked"
        assert d.reason == "high_risk_blocked"
        assert d.would_dispatch_task_type is None


def test_p1_2_unknown_intent_requires_clarification() -> None:
    d = parse_intent_with_provider_dry_run("I叔 看状态", provider=lambda _text: _health_fixture(intent="tell_joke", confidence=0.88))

    assert d.handled is True
    assert d.allowed is False
    assert d.decision == "clarification_required"
    assert d.reason == "intent_not_allowlisted_or_ambiguous"
    assert d.would_dispatch_task_type is None


def test_p1_2_provider_exception_blocks_provider_exception() -> None:
    def provider(_command_text: str) -> dict[str, Any]:
        raise RuntimeError("fixture boom")

    d = parse_intent_with_provider_dry_run("I叔 看状态", provider=provider)

    assert d.handled is True
    assert d.allowed is False
    assert d.decision == "blocked"
    assert d.reason == "provider_exception"
    assert d.candidate is None
    assert d.raw_model_output is not None
    assert d.raw_model_output["error"] == "provider_exception"
    assert d.raw_model_output["exception_type"] == "RuntimeError"


def test_p1_2_provider_none_keeps_p1_mock_compatibility() -> None:
    old_path = parse_intent_dry_run("麻烦 I叔 看看你现在状态")
    new_path = parse_intent_with_provider_dry_run("麻烦 I叔 看看你现在状态", provider=None)

    assert old_path == new_path
    assert new_path.allowed is True
    assert new_path.decision == "would_dispatch_dry_run"
    assert new_path.would_dispatch_task_type == "health_report"


def test_p1_2_high_risk_input_marker_blocks_before_fixture_dispatch() -> None:
    called = False

    def provider(_command_text: str) -> dict[str, Any]:
        nonlocal called
        called = True
        return _health_fixture()

    d = parse_intent_with_provider_dry_run("I叔 帮我 systemctl restart 服务", provider=provider)

    assert called is False
    assert d.allowed is False
    assert d.decision == "blocked"
    assert d.reason == "high_risk_blocked"
    assert d.would_dispatch_task_type is None


def test_p1_2_decision_to_json_keeps_provider_contract_metadata() -> None:
    d = parse_intent_with_provider_dry_run("I叔 看状态", provider=lambda _text: _health_fixture())
    payload = json.loads(decision_to_json(d))

    assert payload["schema_version"] == mod.P1_SCHEMA_VERSION
    assert payload["provider_contract_version"] == mod.P1_2_PROVIDER_CONTRACT_VERSION
    assert payload["decision"] == "would_dispatch_dry_run"
    assert payload["candidate"]["intent"] == "health_report"
