from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping

try:
    from .isaac_intent_p1 import (
        IntentProviderProtocol,
        parse_intent_with_provider_dry_run,
    )
except Exception:  # pragma: no cover - supports direct file loading in tests.
    import importlib.util
    import sys
    from pathlib import Path

    _INTENT_PATH = Path(__file__).resolve().with_name("isaac_intent_p1.py")
    _INTENT_SPEC = importlib.util.spec_from_file_location("isaac_intent_p1_for_i_line_p1_5", _INTENT_PATH)
    if _INTENT_SPEC is None or _INTENT_SPEC.loader is None:
        raise ImportError(f"cannot load Isaac P1 intent parser from {_INTENT_PATH}")
    _intent_mod = importlib.util.module_from_spec(_INTENT_SPEC)
    sys.modules[_INTENT_SPEC.name] = _intent_mod
    _INTENT_SPEC.loader.exec_module(_intent_mod)
    IntentProviderProtocol = _intent_mod.IntentProviderProtocol  # type: ignore[assignment]
    parse_intent_with_provider_dry_run = _intent_mod.parse_intent_with_provider_dry_run  # type: ignore[assignment]


P1_5_BRIDGE_SCHEMA_VERSION = "i_line.p1_5.default_off_intent_provider_bridge.20260607"
P1_5_ALLOWED_PROVIDER_MODES = {"disabled", "fixture"}
P1_5_DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "provider_mode": "disabled",
    "fixture_name": "natural_alias_fixture_v1",
    "expose_raw_provider_output": True,
}

_HIGH_RISK_TEXT_MARKERS = (
    "restart",
    "deploy",
    "shell",
    "ssh",
    "systemctl",
    "service",
    "supervisorctl",
    "docker",
    "kubectl",
    "subprocess",
    "os.system",
    "command",
    "write_config",
    "runtime_config",
    ".env",
    "long_term",
    "memories.jsonl",
    "/opt",
    "重启",
    "部署",
    "上线",
    "发布",
    "执行命令",
    "跑命令",
    "改配置",
    "写配置",
    "删除",
    "安装",
    "卸载",
    "读记忆",
    "导出记忆",
    "长期记忆",
    "密钥",
    "令牌",
    "密码",
)


@dataclass(frozen=True)
class IntentProviderBridgeConfig:
    """Default-off P1.5 bridge config.

    The bridge is intentionally inert unless ``enabled=True`` and
    ``provider_mode='fixture'`` are passed by tests or a future owner-private
    runtime gate.  It does not read runtime_config, environment variables, or
    provider credentials.
    """

    enabled: bool = False
    provider_mode: str = "disabled"
    fixture_name: str = "natural_alias_fixture_v1"
    expose_raw_provider_output: bool = True

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any] | None) -> "IntentProviderBridgeConfig":
        if data is None:
            return cls()
        return cls(
            enabled=bool(data.get("enabled", False)),
            provider_mode=str(data.get("provider_mode", "disabled") or "disabled"),
            fixture_name=str(data.get("fixture_name", "natural_alias_fixture_v1") or "natural_alias_fixture_v1"),
            expose_raw_provider_output=bool(data.get("expose_raw_provider_output", True)),
        )

    def normalized(self) -> "IntentProviderBridgeConfig":
        mode = self.provider_mode if self.provider_mode in P1_5_ALLOWED_PROVIDER_MODES else "disabled"
        if not self.enabled:
            mode = "disabled"
        return IntentProviderBridgeConfig(
            enabled=bool(self.enabled),
            provider_mode=mode,
            fixture_name=self.fixture_name,
            expose_raw_provider_output=bool(self.expose_raw_provider_output),
        )


@dataclass(frozen=True)
class IntentProviderBridgeResult:
    handled: bool
    allowed: bool
    reason: str
    intent_preview: dict[str, Any] | None
    provider_called: bool
    reply: str


def _contains_high_risk(text: str) -> str | None:
    lowered = str(text or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    for marker in _HIGH_RISK_TEXT_MARKERS:
        marker_low = marker.lower()
        if marker_low in lowered or marker_low.replace(" ", "") in compact:
            return marker
    return None


def _text_matches(text: str, *needles: str) -> bool:
    raw = str(text or "").lower()
    compact = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", raw)
    for needle in needles:
        n = str(needle or "").lower().strip()
        if not n:
            continue
        n_compact = re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", n)
        if n in raw or (n_compact and n_compact in compact):
            return True
    return False


def fixture_intent_provider(command_text: str) -> dict[str, Any]:
    """Local fixture/mock provider for P1.5 dry-run bridge.

    This is not an LLM/provider/network adapter.  It is a deterministic fixture
    that emits only the P1.2 provider contract shape for intent preview tests.
    Authorization remains entirely in code gates after this output.
    """

    text = str(command_text or "")
    high = _contains_high_risk(text)
    if high:
        return {
            "intent": "blocked_high_risk",
            "confidence": 0.99,
            "risk_level": "high",
            "needs_confirmation": True,
            "reason": f"p1_5_fixture_high_risk_marker:{high}",
            "source": "p1_5_fixture_provider",
        }
    if _text_matches(
        text,
        "workspace",
        "workspace report",
        "project status",
        "项目进度",
        "项目情况",
        "维护内容",
        "维护进度",
        "工作进展",
        "今天维护",
    ):
        intent = "workspace_report"
        confidence = 0.91
    elif _text_matches(
        text,
        "health",
        "status",
        "selfcheck",
        "系统情况",
        "系统状态",
        "运行状态",
        "运行情况",
        "巡检",
        "自检",
        "异常",
        "还好吗",
        "正常吗",
    ):
        intent = "health_report"
        confidence = 0.92
    elif _text_matches(
        text,
        "dry run",
        "dry_run",
        "plan",
        "rehearsal",
        "后续计划",
        "落地步骤",
        "行动方案",
        "执行方案",
        "预演",
        "演练",
        "先别执行",
        "步骤",
    ):
        intent = "dry_run_plan"
        confidence = 0.89
    elif _text_matches(
        text,
        "help",
        "usage",
        "commands",
        "能干嘛",
        "有什么功能",
        "使用说明",
        "可用指令",
        "帮助",
        "菜单",
    ):
        intent = "help_report"
        confidence = 0.94
    else:
        return {
            "intent": "unknown",
            "confidence": 0.40,
            "risk_level": "low",
            "needs_confirmation": True,
            "reason": "p1_5_fixture_ambiguous",
            "source": "p1_5_fixture_provider",
        }
    return {
        "intent": intent,
        "confidence": confidence,
        "risk_level": "low",
        "needs_confirmation": False,
        "reason": f"p1_5_fixture_matched:{intent}",
        "source": "p1_5_fixture_provider",
    }


def make_fixture_intent_provider(fixture_name: str = "natural_alias_fixture_v1") -> IntentProviderProtocol:
    if fixture_name != "natural_alias_fixture_v1":
        raise ValueError("unsupported_fixture_provider")
    return fixture_intent_provider


def build_intent_provider_from_bridge_config(
    config: IntentProviderBridgeConfig | Mapping[str, Any] | None,
) -> IntentProviderProtocol | None:
    bridge_config = config if isinstance(config, IntentProviderBridgeConfig) else IntentProviderBridgeConfig.from_mapping(config)
    normalized = bridge_config.normalized()
    if not normalized.enabled or normalized.provider_mode != "fixture":
        return None
    try:
        return make_fixture_intent_provider(normalized.fixture_name)
    except Exception:
        def _failing_fixture_provider(_command_text: str) -> dict[str, Any]:
            raise RuntimeError("p1_5_fixture_provider_unavailable")

        return _failing_fixture_provider


def _candidate_preview_dict(candidate: Any) -> dict[str, Any] | None:
    if candidate is None:
        return None
    return {
        "intent": str(getattr(candidate, "intent", "") or ""),
        "confidence": float(getattr(candidate, "confidence", 0.0) or 0.0),
        "risk_level": str(getattr(candidate, "risk_level", "") or ""),
        "needs_confirmation": bool(getattr(candidate, "needs_confirmation", False)),
        "reason": str(getattr(candidate, "reason", "") or ""),
        "source": str(getattr(candidate, "source", "") or ""),
    }


def decision_to_intent_preview(decision: Any, *, provider_bridge_enabled: bool, provider_mode: str, provider_called: bool) -> dict[str, Any]:
    return {
        "schema_version": P1_5_BRIDGE_SCHEMA_VERSION,
        "handled": bool(getattr(decision, "handled", False)),
        "allowed": bool(getattr(decision, "allowed", False)),
        "decision": str(getattr(decision, "decision", "") or ""),
        "reason": str(getattr(decision, "reason", "") or ""),
        "candidate": _candidate_preview_dict(getattr(decision, "candidate", None)),
        "would_dispatch_task_type": getattr(decision, "would_dispatch_task_type", None),
        "raw_model_output": dict(getattr(decision, "raw_model_output", None) or {}),
        "provider_bridge_enabled": bool(provider_bridge_enabled),
        "provider_mode": str(provider_mode or "disabled"),
        "provider_called": bool(provider_called),
        "provider_network_used": False,
        "provider_authorized": False,
        "authorization_source": "code_gate_only",
        "no_real_dispatch": True,
        "agent_bus_used": False,
        "task_request_dispatched": False,
        "executor_enabled": False,
    }


def _bridge_reply(reason: str, preview: Mapping[str, Any] | None = None) -> str:
    if preview is None:
        return f"I叔 P1.5 provider bridge dry-run：{reason}。"
    candidate = dict(preview.get("candidate") or {})
    intent = str(candidate.get("intent") or "unknown")
    would_dispatch = str(preview.get("would_dispatch_task_type") or "-")
    return (
        f"I叔 P1.5 provider bridge dry-run：{preview.get('decision')} reason={preview.get('reason')}\n"
        f"intent={intent} would_dispatch_task_type={would_dispatch}\n"
        "provider_network_used=false provider_authorized=false no_real_dispatch=true "
        "task_request_dispatched=false executor_enabled=false"
    )


def dry_run_intent_provider_bridge(
    msg: Any,
    config: IntentProviderBridgeConfig | Mapping[str, Any] | None = None,
) -> IntentProviderBridgeResult:
    """Run the default-off fixture provider bridge and return an intent preview.

    Safety order:
    1. trigger check;
    2. private gate;
    3. owner gate;
    4. high-risk text gate before provider;
    5. disabled-by-default bridge config;
    6. fixture provider -> P1.2/P1.4 parser contract -> preview only.
    """

    raw_text = str(getattr(msg, "text", "") or getattr(msg, "raw_content", "") or "")
    if not re.search(r"(?i)i叔|艾萨克", raw_text):
        return IntentProviderBridgeResult(False, False, "not_isaac_command", None, False, "")
    if str(getattr(msg, "channel", "") or "") != "private":
        return IntentProviderBridgeResult(True, False, "private_only", None, False, _bridge_reply("private_only"))
    if not bool(getattr(msg, "is_owner", False)):
        return IntentProviderBridgeResult(True, False, "owner_only", None, False, _bridge_reply("owner_only"))
    high = _contains_high_risk(raw_text)
    if high:
        return IntentProviderBridgeResult(True, False, "high_risk_blocked", None, False, _bridge_reply("high_risk_blocked"))

    bridge_config = (config if isinstance(config, IntentProviderBridgeConfig) else IntentProviderBridgeConfig.from_mapping(config)).normalized()
    provider = build_intent_provider_from_bridge_config(bridge_config)
    if provider is None:
        return IntentProviderBridgeResult(
            True,
            False,
            "provider_bridge_disabled",
            None,
            False,
            _bridge_reply("provider_bridge_disabled"),
        )

    decision = parse_intent_with_provider_dry_run(raw_text, provider=provider)
    preview = decision_to_intent_preview(
        decision,
        provider_bridge_enabled=bridge_config.enabled,
        provider_mode=bridge_config.provider_mode,
        provider_called=True,
    )
    if not bridge_config.expose_raw_provider_output:
        preview["raw_model_output"] = {"redacted": True}
    reason = str(preview.get("reason") or preview.get("decision") or "intent_preview")
    if preview.get("decision") == "would_dispatch_dry_run":
        reason = "would_dispatch_dry_run"
    elif preview.get("decision") == "clarification_required":
        reason = "clarification_required"
    elif preview.get("reason") == "high_risk_blocked":
        reason = "high_risk_blocked"
    return IntentProviderBridgeResult(
        True,
        bool(preview.get("allowed", False)),
        reason,
        preview,
        True,
        _bridge_reply(reason, preview),
    )


__all__ = [
    "IntentProviderBridgeConfig",
    "IntentProviderBridgeResult",
    "P1_5_BRIDGE_SCHEMA_VERSION",
    "P1_5_DEFAULT_CONFIG",
    "build_intent_provider_from_bridge_config",
    "decision_to_intent_preview",
    "dry_run_intent_provider_bridge",
    "fixture_intent_provider",
    "make_fixture_intent_provider",
]
