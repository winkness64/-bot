from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .topic_boundary_provider import TopicBoundaryProviderConfig


@dataclass(frozen=True)
class TopicBoundaryGateDecision:
    """Decision and safe settings for topic-boundary LLM resolution.

    This module is intentionally pure: it accepts a mapping supplied by the
    caller and never reads or mutates runtime_config by itself.
    """

    enabled: bool
    reason: str
    model_tier: str = "v4_flash"
    timeout_seconds: float = 8.0
    max_records: int = 40
    max_payload_chars: int = 800
    min_confidence: float = 0.65
    fallback_on_invalid: bool = True
    fallback_on_error: bool = True
    fallback_on_ambiguous: bool = False


_DEFAULT_MODEL_TIER = "v4_flash"
_DEFAULT_TIMEOUT_SECONDS = 8.0
_DEFAULT_MAX_RECORDS = 40
_DEFAULT_MAX_PAYLOAD_CHARS = 800
_DEFAULT_MIN_CONFIDENCE = 0.65

_TRUE_STRINGS = {"1", "true", "yes", "y", "on"}
_FALSE_STRINGS = {"0", "false", "no", "n", "off", ""}


def _safe_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in _TRUE_STRINGS:
            return True
        if lowered in _FALSE_STRINGS:
            return False
        return default
    if isinstance(value, (int, float)):
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(number):
            return default
        return bool(number)
    return default


def _finite_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _clamp_float(value: Any, *, default: float, minimum: float, maximum: float) -> float:
    number = _finite_float(value)
    if number is None:
        return default
    return min(maximum, max(minimum, number))


def _clamp_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    number = _finite_float(value)
    if number is None:
        return default
    integer = int(number)
    return min(maximum, max(minimum, integer))


def _model_tier(value: Any) -> str:
    text = str(value or "").strip()
    return text or _DEFAULT_MODEL_TIER


def _decision(
    *,
    enabled: bool,
    reason: str,
    config: Mapping[str, Any] | None,
) -> TopicBoundaryGateDecision:
    cfg = config or {}
    return TopicBoundaryGateDecision(
        enabled=enabled,
        reason=reason,
        model_tier=_model_tier(cfg.get("memory_topic_boundary_model_tier", _DEFAULT_MODEL_TIER)),
        timeout_seconds=_clamp_float(
            cfg.get("memory_topic_boundary_timeout_seconds", _DEFAULT_TIMEOUT_SECONDS),
            default=_DEFAULT_TIMEOUT_SECONDS,
            minimum=1.0,
            maximum=60.0,
        ),
        max_records=_clamp_int(
            cfg.get("memory_topic_boundary_max_records", _DEFAULT_MAX_RECORDS),
            default=_DEFAULT_MAX_RECORDS,
            minimum=1,
            maximum=100,
        ),
        max_payload_chars=_clamp_int(
            cfg.get("memory_topic_boundary_max_payload_chars", _DEFAULT_MAX_PAYLOAD_CHARS),
            default=_DEFAULT_MAX_PAYLOAD_CHARS,
            minimum=100,
            maximum=2000,
        ),
        min_confidence=_clamp_float(
            cfg.get("memory_topic_boundary_min_confidence", _DEFAULT_MIN_CONFIDENCE),
            default=_DEFAULT_MIN_CONFIDENCE,
            minimum=0.0,
            maximum=1.0,
        ),
        fallback_on_invalid=_safe_bool(
            cfg.get("memory_topic_boundary_fallback_on_invalid", True),
            default=True,
        ),
        fallback_on_error=_safe_bool(
            cfg.get("memory_topic_boundary_fallback_on_error", True),
            default=True,
        ),
        fallback_on_ambiguous=_safe_bool(
            cfg.get("memory_topic_boundary_fallback_on_ambiguous", False),
            default=False,
        ),
    )


def decide_topic_boundary_enabled(
    config: Mapping[str, Any] | None,
    *,
    is_owner: bool,
    is_private: bool,
    is_group: bool = False,
) -> TopicBoundaryGateDecision:
    """Return whether topic-boundary LLM resolution may run for this message.

    Gate policy for M2.2-B2-B2-A:
    - default closed when config is ``None`` or the global key is absent/false;
    - owner private chat only;
    - group context is always disabled in this phase;
    - no file IO and no runtime_config mutation.
    """

    if config is None or "memory_topic_boundary_enabled" not in config:
        return _decision(enabled=False, reason="disabled", config=config)

    if not _safe_bool(config.get("memory_topic_boundary_enabled"), default=False):
        return _decision(enabled=False, reason="disabled", config=config)

    if is_group:
        return _decision(enabled=False, reason="group_disabled", config=config)

    if not is_owner:
        return _decision(enabled=False, reason="not_owner", config=config)

    if not is_private:
        return _decision(enabled=False, reason="not_private", config=config)

    if not _safe_bool(config.get("memory_topic_boundary_private_enabled", True), default=True):
        return _decision(enabled=False, reason="private_disabled", config=config)

    return _decision(enabled=True, reason="enabled", config=config)


def build_provider_config_from_decision(
    decision: TopicBoundaryGateDecision,
) -> "TopicBoundaryProviderConfig":
    """Build provider adapter config from a gate decision.

    Kept as a tiny optional bridge so handler integration can avoid duplicating
    model tier and timeout extraction later.
    """

    from .topic_boundary_provider import TopicBoundaryProviderConfig

    return TopicBoundaryProviderConfig(
        model_tier=decision.model_tier,
        timeout_seconds=decision.timeout_seconds,
    )
