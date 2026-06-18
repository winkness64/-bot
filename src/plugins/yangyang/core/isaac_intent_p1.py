from __future__ import annotations

from dataclasses import dataclass
import json
import math
import re
from typing import Any, Mapping, Protocol


P1_SCHEMA_VERSION = "i_line.p1.llm_intent_parser_dry_run.20260607"
P1_2_PROVIDER_CONTRACT_VERSION = "i_line.p1_2.intent_provider_contract.20260607"
ALLOWED_INTENTS = {"help_report", "health_report", "workspace_report", "dry_run_plan"}
HIGH_RISK_INTENTS = {
    "blocked_high_risk",
    "restart",
    "restart_service",
    "deploy",
    "deploy_service",
    "shell",
    "execute_shell",
    "run_command",
    "ssh",
    "systemctl",
    "service_control",
    "write_config",
    "read_memory_body",
    "read_long_term_body",
    "write_memory",
    "executor",
    "isaac_executor",
    "task_dispatch",
    "agent_bus_dispatch",
}
RISK_LEVELS = {"low", "medium", "high", "critical"}
REQUIRED_PROVIDER_FIELDS = ("intent", "confidence", "risk_level", "needs_confirmation", "reason")
TRIGGER_RE = re.compile(r"(?i)i叔|艾萨克")
HIGH_RISK_TEXT_MARKERS = (
    "restart",
    "deploy",
    "shell",
    "ssh",
    "systemctl",
    "write_config",
    "runtime_config",
    ".env",
    "long_term",
    "memory body",
    "executor",
    "subprocess",
    "os.system",
    "重启",
    "部署",
    "执行命令",
    "改配置",
    "密钥",
    "长期记忆",
)

# P1.4: deterministic, local-only normalization.  These aliases are deliberately
# small and read-only oriented; they do not authorize or dispatch anything.
INTENT_ALIAS_TO_CANONICAL = {
    "help": "help_report",
    "usage": "help_report",
    "commands": "help_report",
    "command_list": "help_report",
    "menu": "help_report",
    "help_report": "help_report",
    "功能": "help_report",
    "帮助": "help_report",
    "用法": "help_report",
    "菜单": "help_report",
    "health": "health_report",
    "status": "health_report",
    "status_check": "health_report",
    "status_report": "health_report",
    "selfcheck": "health_report",
    "self_check": "health_report",
    "diagnostic": "health_report",
    "diagnostics": "health_report",
    "health_report": "health_report",
    "状态": "health_report",
    "健康": "health_report",
    "诊断": "health_report",
    "自检": "health_report",
    "workspace": "workspace_report",
    "workspace_report": "workspace_report",
    "workspace_status": "workspace_report",
    "project_status": "workspace_report",
    "project_report": "workspace_report",
    "maintenance_report": "workspace_report",
    "progress_report": "workspace_report",
    "workspace_progress": "workspace_report",
    "工作区": "workspace_report",
    "项目状态": "workspace_report",
    "维护进度": "workspace_report",
    "维护内容": "workspace_report",
    "dryrun": "dry_run_plan",
    "dry_run": "dry_run_plan",
    "dry_run_plan": "dry_run_plan",
    "plan": "dry_run_plan",
    "plan_only": "dry_run_plan",
    "rehearsal": "dry_run_plan",
    "rehearsal_plan": "dry_run_plan",
    "dryrun_plan": "dry_run_plan",
    "计划": "dry_run_plan",
    "预案": "dry_run_plan",
    "演练": "dry_run_plan",
    "方案": "dry_run_plan",
    "blocked_high_risk": "blocked_high_risk",
    "high_risk_blocked": "blocked_high_risk",
    "restart_service": "restart_service",
    "service_control": "service_control",
    "run_command": "run_command",
    "execute_shell": "execute_shell",
    "write_runtime_config": "write_config",
    "runtime_config": "write_config",
    "memories_jsonl": "read_memory_body",
}

NATURAL_TEXT_INTENT_ALIASES: tuple[tuple[str, float, tuple[str, ...]], ...] = (
    (
        "workspace_report",
        0.90,
        (
            "workspace",
            "workspace report",
            "workspace status",
            "project status",
            "project report",
            "工作区",
            "工作区情况",
            "项目状态",
            "项目情况",
            "项目进度",
            "项目报告",
            "工程状态",
            "工程进度",
            "维护内容",
            "维护进度",
            "维护情况",
            "今天维护",
            "今天进度",
            "今天做了什么",
            "整理进度",
            "汇报维护",
            "汇报下维护内容",
            "工作进展",
            "进度汇报",
            "变更摘要",
            "改动摘要",
            "文件概览",
            "仓库情况",
            "代码进度",
            "开发进度",
        ),
    ),
    (
        "health_report",
        0.91,
        (
            "health",
            "status",
            "selfcheck",
            "self check",
            "checkup",
            "diagnostic",
            "diagnostics",
            "看下系统情况",
            "看看系统情况",
            "系统情况",
            "系统状态",
            "当前状态",
            "现在状态",
            "运行状态",
            "运行情况",
            "健康",
            "健康度",
            "自检",
            "诊断",
            "巡检",
            "体检",
            "有没有异常",
            "有无异常",
            "是否异常",
            "异常情况",
            "报错情况",
            "还好吗",
            "活着没",
            "正常吗",
            "是否正常",
            "看状态",
            "看一下状态",
            "看看状态",
        ),
    ),
    (
        "dry_run_plan",
        0.88,
        (
            "dryrun",
            "dry run",
            "dry_run",
            "plan",
            "plan only",
            "rehearsal",
            "计划",
            "预案",
            "演练",
            "方案",
            "步骤",
            "拆步骤",
            "排步骤",
            "下一步怎么做",
            "下一步计划",
            "后续怎么做",
            "后续计划",
            "给个计划",
            "做个计划",
            "出个计划",
            "拟个计划",
            "计划一下",
            "先别执行",
            "不执行先计划",
            "只做计划",
            "只给计划",
            "先走预演",
            "预演一下",
            "演练一下",
            "怎么落地",
            "落地步骤",
            "行动方案",
            "执行方案",
            "实施方案",
            "路线图",
            "排期",
        ),
    ),
    (
        "help_report",
        0.94,
        (
            "help",
            "usage",
            "commands",
            "command list",
            "帮助",
            "说明",
            "命令",
            "用法",
            "菜单",
            "怎么用",
            "能干嘛",
            "能干啥",
            "会干嘛",
            "会干啥",
            "有什么功能",
            "能做什么",
            "可以做什么",
            "支持什么",
            "支持哪些",
            "能做哪些",
            "可用指令",
            "指令列表",
            "命令列表",
            "功能列表",
            "使用说明",
        ),
    ),
)


class IntentProviderProtocol(Protocol):
    """Dry-run provider contract for future LLM intent parsing.

    The callable receives trigger-stripped command text and returns either a JSON
    object string or a mapping.  This module never imports or calls network LLM
    SDKs; tests can replay fixtures by passing local callables.
    """

    def __call__(self, command_text: str) -> str | Mapping[str, Any]:
        ...


@dataclass(frozen=True)
class IntentCandidate:
    intent: str
    confidence: float
    risk_level: str
    needs_confirmation: bool
    reason: str
    source: str = "mock_llm_rules"


@dataclass(frozen=True)
class IntentDecision:
    handled: bool
    allowed: bool
    decision: str
    reason: str
    candidate: IntentCandidate | None = None
    would_dispatch_task_type: str | None = None
    reply: str = ""
    raw_model_output: dict[str, Any] | None = None


def extract_triggered_text(text: str) -> str | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    match = TRIGGER_RE.search(raw)
    if not match:
        return None
    before = raw[:match.start()].strip(" ：:，,\t\n")
    after = raw[match.end():].strip(" ：:，,\t\n")
    return f"{before} {after}".strip()


def _contains_high_risk(text: str) -> str | None:
    lowered = str(text or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    for marker in HIGH_RISK_TEXT_MARKERS:
        m = marker.lower()
        if m in lowered or m.replace(" ", "") in compact:
            return marker
    return None


def _alias_key(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "_", str(text or "").strip().lower()).strip("_")


def _alias_compact(text: str) -> str:
    return re.sub(r"[^0-9a-zA-Z\u4e00-\u9fff]+", "", str(text or "").strip().lower())


def normalize_intent_alias(intent: str) -> str:
    raw = str(intent or "").strip()
    key = _alias_key(raw)
    compact = _alias_compact(raw)
    return INTENT_ALIAS_TO_CANONICAL.get(key) or INTENT_ALIAS_TO_CANONICAL.get(compact) or key or raw


def _matches_text_alias(text: str, alias: str) -> bool:
    raw = str(text or "").lower()
    alias_raw = str(alias or "").lower().strip()
    if not alias_raw:
        return False
    if alias_raw in raw:
        return True
    alias_compact = _alias_compact(alias_raw)
    return bool(alias_compact and alias_compact in _alias_compact(raw))


def _natural_text_alias_parse(text: str) -> dict[str, Any] | None:
    for intent, confidence, aliases in NATURAL_TEXT_INTENT_ALIASES:
        for alias in aliases:
            if _matches_text_alias(text, alias):
                return {
                    "intent": intent,
                    "confidence": confidence,
                    "risk_level": "low",
                    "needs_confirmation": False,
                    "reason": f"p1_4_natural_alias_matched:{intent}",
                }
    return None


def mock_llm_intent_parse(command_text: str) -> dict[str, Any]:
    """Mock LLM-like parser for P1 dry-run.

    This deliberately does not call a provider/network. It simulates the shape of
    a future LLM response so schema/gate/clarification logic can be tested first.
    """
    text = str(command_text or "").strip()
    lowered = text.lower()
    compact = re.sub(r"\s+", "", lowered)
    high = _contains_high_risk(text)
    if high:
        return {
            "intent": "blocked_high_risk",
            "confidence": 0.99,
            "risk_level": "high",
            "needs_confirmation": True,
            "reason": f"high risk marker detected: {high}",
        }
    if not text:
        return {"intent": "help_report", "confidence": 0.94, "risk_level": "low", "needs_confirmation": False, "reason": "empty request defaults to help"}
    alias_result = _natural_text_alias_parse(text)
    if alias_result is not None:
        return alias_result
    return {"intent": "unknown", "confidence": 0.35, "risk_level": "low", "needs_confirmation": True, "reason": "ambiguous request"}


def _json_safe(value: Any) -> Any:
    try:
        json.dumps(value, ensure_ascii=False)
        return value
    except Exception:
        return repr(value)


def _safe_raw_model_output(raw: Mapping[str, Any] | None, *, error: str | None = None, detail: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if raw is not None:
        for key, value in raw.items():
            payload[str(key)] = _json_safe(value)
    if error:
        payload["error"] = error
    if detail:
        payload["detail"] = detail
    return payload


def _invalid_schema_decision(*, raw: Mapping[str, Any] | None = None, detail: str = "invalid_intent_schema") -> IntentDecision:
    return IntentDecision(
        handled=True,
        allowed=False,
        decision="blocked",
        reason="invalid_intent_schema",
        reply="I叔 P1 dry-run：intent schema 无效，已拦截。",
        raw_model_output=_safe_raw_model_output(raw, error="invalid_intent_schema", detail=detail),
    )


def _provider_exception_decision(exc: BaseException) -> IntentDecision:
    return IntentDecision(
        handled=True,
        allowed=False,
        decision="blocked",
        reason="provider_exception",
        reply="I叔 P1 dry-run：intent provider 异常，已 fail-closed 拦截。",
        raw_model_output={"error": "provider_exception", "exception_type": type(exc).__name__},
    )


def _high_risk_text_decision(marker: str) -> IntentDecision:
    candidate = IntentCandidate(
        intent="blocked_high_risk",
        confidence=0.99,
        risk_level="high",
        needs_confirmation=True,
        reason=f"high risk marker detected: {marker}",
        source="input_risk_guard",
    )
    return IntentDecision(
        handled=True,
        allowed=False,
        decision="blocked",
        reason="high_risk_blocked",
        candidate=candidate,
        reply="I叔 P1 dry-run：识别到高风险意图，已拦截，不会派发任务。",
        raw_model_output={
            "intent": candidate.intent,
            "confidence": candidate.confidence,
            "risk_level": candidate.risk_level,
            "needs_confirmation": candidate.needs_confirmation,
            "reason": candidate.reason,
            "source": candidate.source,
        },
    )


def _provider_output_to_mapping(provider_output: Any) -> tuple[dict[str, Any] | None, dict[str, Any] | None, str | None]:
    if isinstance(provider_output, Mapping):
        raw = dict(provider_output)
        return raw, _safe_raw_model_output(raw), None
    if isinstance(provider_output, str):
        try:
            decoded = json.loads(provider_output)
        except Exception:
            return None, {"provider_output_type": "str", "error": "invalid_json"}, "invalid_json"
        if not isinstance(decoded, Mapping):
            return None, {
                "provider_output_type": "str",
                "decoded_type": type(decoded).__name__,
                "error": "json_root_not_object",
            }, "json_root_not_object"
        raw = dict(decoded)
        return raw, _safe_raw_model_output(raw), None
    return None, {"provider_output_type": type(provider_output).__name__, "error": "provider_output_not_json_or_mapping"}, "provider_output_not_json_or_mapping"


def _provider_schema_error(raw: Mapping[str, Any]) -> str | None:
    for field in REQUIRED_PROVIDER_FIELDS:
        if field not in raw:
            return f"missing_{field}"

    intent = raw.get("intent")
    if not isinstance(intent, str) or not intent.strip():
        return "invalid_intent_type"

    confidence = raw.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        return "invalid_confidence_type"
    try:
        conf = float(confidence)
    except Exception:
        return "invalid_confidence_type"
    if not math.isfinite(conf) or not 0.0 <= conf <= 1.0:
        return "invalid_confidence_range"

    risk_level = raw.get("risk_level")
    if not isinstance(risk_level, str) or risk_level not in RISK_LEVELS:
        return "invalid_risk_level"

    needs_confirmation = raw.get("needs_confirmation")
    if not isinstance(needs_confirmation, bool):
        return "invalid_needs_confirmation_type"

    reason = raw.get("reason")
    if not isinstance(reason, str):
        return "invalid_reason_type"

    if "source" in raw and not isinstance(raw.get("source"), str):
        return "invalid_source_type"

    return None


def _coerce_candidate(raw: Mapping[str, Any], *, default_source: str = "mock_llm_rules") -> IntentCandidate | None:
    if _provider_schema_error(raw) is not None:
        return None
    source = raw.get("source") if "source" in raw else default_source
    if not source:
        source = default_source
    return IntentCandidate(
        intent=normalize_intent_alias(str(raw["intent"])),
        confidence=float(raw["confidence"]),
        risk_level=str(raw["risk_level"]),
        needs_confirmation=bool(raw["needs_confirmation"]),
        reason=str(raw["reason"])[:240],
        source=str(source),
    )


def evaluate_intent_candidate(candidate: IntentCandidate | None) -> IntentDecision:
    if candidate is None:
        return IntentDecision(
            handled=True,
            allowed=False,
            decision="blocked",
            reason="invalid_intent_schema",
            reply="I叔 P1 dry-run：intent schema 无效，已拦截。",
        )
    if candidate.intent in HIGH_RISK_INTENTS or candidate.risk_level in {"high", "critical"}:
        return IntentDecision(
            handled=True,
            allowed=False,
            decision="blocked",
            reason="high_risk_blocked",
            candidate=candidate,
            reply="I叔 P1 dry-run：识别到高风险意图，已拦截，不会派发任务。",
        )
    if candidate.intent not in ALLOWED_INTENTS:
        return IntentDecision(
            handled=True,
            allowed=False,
            decision="clarification_required",
            reason="intent_not_allowlisted_or_ambiguous",
            candidate=candidate,
            reply="I叔 P1 dry-run：我还不能确定要做哪种只读任务，请二次确认 help / health / workspace / dry_run plan。",
        )
    if candidate.needs_confirmation or candidate.confidence < 0.70:
        return IntentDecision(
            handled=True,
            allowed=False,
            decision="clarification_required",
            reason="low_confidence_or_confirmation_required",
            candidate=candidate,
            reply="I叔 P1 dry-run：这个意图需要二次确认，暂不派发任务。",
        )
    return IntentDecision(
        handled=True,
        allowed=True,
        decision="would_dispatch_dry_run",
        reason="intent_allowlisted_low_risk",
        candidate=candidate,
        would_dispatch_task_type=candidate.intent,
        reply=(
            "I叔 P1 dry-run：已理解为只读任务，但本阶段不真实派发。\n"
            f"intent={candidate.intent} confidence={candidate.confidence:.2f} risk={candidate.risk_level}\n"
            "next=code_gate_would_build_TaskRequest"
        ),
    )


def parse_intent_with_provider_dry_run(text: str, provider: IntentProviderProtocol | None = None) -> IntentDecision:
    """Parse an Isaac intent through the P1.2 provider contract in dry-run mode.

    Boundary guarantees:
    - provider=None preserves the P1 mock parser behavior;
    - provider output may be a JSON object string or a mapping;
    - malformed provider output, missing/wrong typed fields, provider exceptions,
      out-of-range confidence, and risky outputs fail closed without raising;
    - this function never dispatches TaskRequest, Agent Bus messages, executors,
      shell commands, or network LLM calls.
    """
    command_text = extract_triggered_text(text)
    if command_text is None:
        return IntentDecision(handled=False, allowed=False, decision="not_triggered", reason="missing_i_uncle_trigger")

    if provider is None:
        raw = mock_llm_intent_parse(command_text)
        candidate = _coerce_candidate(raw, default_source="mock_llm_rules")
        if candidate is None:
            return _invalid_schema_decision(raw=raw, detail=_provider_schema_error(raw) or "invalid_intent_schema")
        decision = evaluate_intent_candidate(candidate)
        return IntentDecision(
            handled=decision.handled,
            allowed=decision.allowed,
            decision=decision.decision,
            reason=decision.reason,
            candidate=decision.candidate,
            would_dispatch_task_type=decision.would_dispatch_task_type,
            reply=decision.reply,
            raw_model_output=_safe_raw_model_output(raw),
        )

    high = _contains_high_risk(command_text)
    if high:
        return _high_risk_text_decision(high)

    try:
        provider_output = provider(command_text)
    except Exception as exc:
        return _provider_exception_decision(exc)

    raw, safe_raw, parse_error = _provider_output_to_mapping(provider_output)
    if parse_error is not None or raw is None:
        return _invalid_schema_decision(raw=safe_raw, detail=parse_error or "invalid_provider_output")

    schema_error = _provider_schema_error(raw)
    if schema_error is not None:
        return _invalid_schema_decision(raw=safe_raw, detail=schema_error)

    candidate = _coerce_candidate(raw, default_source="provider_contract")
    decision = evaluate_intent_candidate(candidate)
    return IntentDecision(
        handled=decision.handled,
        allowed=decision.allowed,
        decision=decision.decision,
        reason=decision.reason,
        candidate=decision.candidate,
        would_dispatch_task_type=decision.would_dispatch_task_type,
        reply=decision.reply,
        raw_model_output=safe_raw,
    )


def parse_intent_dry_run(text: str) -> IntentDecision:
    return parse_intent_with_provider_dry_run(text, provider=None)


def decision_to_json(decision: IntentDecision) -> str:
    payload = {
        "schema_version": P1_SCHEMA_VERSION,
        "provider_contract_version": P1_2_PROVIDER_CONTRACT_VERSION,
        "handled": decision.handled,
        "allowed": decision.allowed,
        "decision": decision.decision,
        "reason": decision.reason,
        "candidate": decision.candidate.__dict__ if decision.candidate else None,
        "would_dispatch_task_type": decision.would_dispatch_task_type,
        "reply": decision.reply,
        "raw_model_output": decision.raw_model_output,
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2, default=str)


__all__ = [
    "ALLOWED_INTENTS",
    "HIGH_RISK_INTENTS",
    "IntentCandidate",
    "IntentDecision",
    "IntentProviderProtocol",
    "P1_SCHEMA_VERSION",
    "P1_2_PROVIDER_CONTRACT_VERSION",
    "decision_to_json",
    "evaluate_intent_candidate",
    "extract_triggered_text",
    "mock_llm_intent_parse",
    "normalize_intent_alias",
    "parse_intent_dry_run",
    "parse_intent_with_provider_dry_run",
]
