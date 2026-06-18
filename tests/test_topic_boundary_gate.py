from __future__ import annotations

from src.plugins.yangyang.memory.topic_boundary_gate import (
    TopicBoundaryGateDecision,
    build_provider_config_from_decision,
    decide_topic_boundary_enabled,
)
from src.plugins.yangyang.memory.topic_boundary_provider import TopicBoundaryProviderConfig


BASE_ENABLED_CONFIG = {
    "memory_topic_boundary_enabled": True,
    "memory_topic_boundary_private_enabled": True,
}


def _decide(config, *, is_owner: bool = True, is_private: bool = True, is_group: bool = False) -> TopicBoundaryGateDecision:
    return decide_topic_boundary_enabled(
        config,
        is_owner=is_owner,
        is_private=is_private,
        is_group=is_group,
    )


def test_config_none_default_disabled() -> None:
    decision = _decide(None)

    assert decision.enabled is False
    assert decision.reason == "disabled"
    assert decision.model_tier == "v4_flash"
    assert decision.timeout_seconds == 8.0
    assert decision.max_records == 40
    assert decision.max_payload_chars == 800
    assert decision.min_confidence == 0.65
    assert decision.fallback_on_invalid is True
    assert decision.fallback_on_error is True
    assert decision.fallback_on_ambiguous is False


def test_missing_global_enabled_key_default_disabled() -> None:
    decision = _decide({"memory_topic_boundary_private_enabled": True})

    assert decision.enabled is False
    assert decision.reason == "disabled"


def test_enabled_true_owner_private_enabled() -> None:
    decision = _decide(BASE_ENABLED_CONFIG)

    assert decision.enabled is True
    assert decision.reason == "enabled"


def test_enabled_true_but_non_owner_disabled() -> None:
    decision = _decide(BASE_ENABLED_CONFIG, is_owner=False)

    assert decision.enabled is False
    assert decision.reason == "not_owner"


def test_enabled_true_but_non_private_disabled() -> None:
    decision = _decide(BASE_ENABLED_CONFIG, is_private=False)

    assert decision.enabled is False
    assert decision.reason == "not_private"


def test_group_context_always_disabled_even_if_private_flag_true() -> None:
    decision = _decide(BASE_ENABLED_CONFIG, is_owner=True, is_private=True, is_group=True)

    assert decision.enabled is False
    assert decision.reason == "group_disabled"


def test_group_non_private_disabled_by_group_gate_first() -> None:
    decision = _decide(BASE_ENABLED_CONFIG, is_owner=True, is_private=False, is_group=True)

    assert decision.enabled is False
    assert decision.reason == "group_disabled"


def test_private_enabled_false_disabled() -> None:
    config = {
        "memory_topic_boundary_enabled": True,
        "memory_topic_boundary_private_enabled": False,
    }

    decision = _decide(config)

    assert decision.enabled is False
    assert decision.reason == "private_disabled"


def test_model_tier_default_and_custom() -> None:
    default_decision = _decide(BASE_ENABLED_CONFIG)
    custom_decision = _decide({**BASE_ENABLED_CONFIG, "memory_topic_boundary_model_tier": "v4_pro"})
    blank_decision = _decide({**BASE_ENABLED_CONFIG, "memory_topic_boundary_model_tier": "   "})

    assert default_decision.model_tier == "v4_flash"
    assert custom_decision.model_tier == "v4_pro"
    assert blank_decision.model_tier == "v4_flash"


def test_numeric_config_parse_and_boundary_clamp() -> None:
    low = _decide(
        {
            **BASE_ENABLED_CONFIG,
            "memory_topic_boundary_max_records": -10,
            "memory_topic_boundary_max_payload_chars": 20,
            "memory_topic_boundary_min_confidence": -0.5,
            "memory_topic_boundary_timeout_seconds": 0,
        }
    )
    high = _decide(
        {
            **BASE_ENABLED_CONFIG,
            "memory_topic_boundary_max_records": 999,
            "memory_topic_boundary_max_payload_chars": 9999,
            "memory_topic_boundary_min_confidence": 1.5,
            "memory_topic_boundary_timeout_seconds": 999,
        }
    )
    parsed = _decide(
        {
            **BASE_ENABLED_CONFIG,
            "memory_topic_boundary_max_records": "55",
            "memory_topic_boundary_max_payload_chars": "1200",
            "memory_topic_boundary_min_confidence": "0.42",
            "memory_topic_boundary_timeout_seconds": "12.5",
        }
    )

    assert low.max_records == 1
    assert low.max_payload_chars == 100
    assert low.min_confidence == 0.0
    assert low.timeout_seconds == 1.0

    assert high.max_records == 100
    assert high.max_payload_chars == 2000
    assert high.min_confidence == 1.0
    assert high.timeout_seconds == 60.0

    assert parsed.max_records == 55
    assert parsed.max_payload_chars == 1200
    assert parsed.min_confidence == 0.42
    assert parsed.timeout_seconds == 12.5


def test_fallback_flags_defaults_and_custom_values() -> None:
    default_decision = _decide(BASE_ENABLED_CONFIG)
    custom_decision = _decide(
        {
            **BASE_ENABLED_CONFIG,
            "memory_topic_boundary_fallback_on_invalid": False,
            "memory_topic_boundary_fallback_on_error": "off",
            "memory_topic_boundary_fallback_on_ambiguous": "yes",
        }
    )

    assert default_decision.fallback_on_invalid is True
    assert default_decision.fallback_on_error is True
    assert default_decision.fallback_on_ambiguous is False

    assert custom_decision.fallback_on_invalid is False
    assert custom_decision.fallback_on_error is False
    assert custom_decision.fallback_on_ambiguous is True


def test_invalid_numeric_values_do_not_raise_and_fall_back_to_defaults() -> None:
    decision = _decide(
        {
            **BASE_ENABLED_CONFIG,
            "memory_topic_boundary_max_records": "bad",
            "memory_topic_boundary_max_payload_chars": None,
            "memory_topic_boundary_min_confidence": "nan",
            "memory_topic_boundary_timeout_seconds": object(),
        }
    )

    assert decision.enabled is True
    assert decision.max_records == 40
    assert decision.max_payload_chars == 800
    assert decision.min_confidence == 0.65
    assert decision.timeout_seconds == 8.0


def test_bool_values_are_safely_parsed() -> None:
    enabled_by_string = _decide({"memory_topic_boundary_enabled": "true"})
    disabled_by_string = _decide({"memory_topic_boundary_enabled": "0"})
    enabled_by_number = _decide({"memory_topic_boundary_enabled": 1})
    unknown_string_uses_default_false_for_global_gate = _decide({"memory_topic_boundary_enabled": "maybe"})

    assert enabled_by_string.enabled is True
    assert disabled_by_string.enabled is False
    assert disabled_by_string.reason == "disabled"
    assert enabled_by_number.enabled is True
    assert unknown_string_uses_default_false_for_global_gate.enabled is False


def test_provider_config_can_be_built_from_decision() -> None:
    decision = _decide(
        {
            **BASE_ENABLED_CONFIG,
            "memory_topic_boundary_model_tier": "v4_pro",
            "memory_topic_boundary_timeout_seconds": 15,
            "memory_topic_boundary_max_records": 60,
        }
    )

    provider_config = build_provider_config_from_decision(decision)

    assert isinstance(provider_config, TopicBoundaryProviderConfig)
    assert provider_config.model_tier == "v4_pro"
    assert provider_config.timeout_seconds == 15.0
    assert provider_config == TopicBoundaryProviderConfig(model_tier="v4_pro", timeout_seconds=15.0)
