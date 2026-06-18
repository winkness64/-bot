from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any, Mapping

_LOG = logging.getLogger("yangyang.isaac_audit")

try:
    from .isaac_intent_p1 import parse_intent_dry_run, parse_intent_with_provider_dry_run
except Exception:  # pragma: no cover - supports direct file loading in tests.
    import importlib.util
    import sys
    from pathlib import Path

    _INTENT_PATH = Path(__file__).resolve().with_name("isaac_intent_p1.py")
    _INTENT_SPEC = importlib.util.spec_from_file_location("isaac_intent_p1_for_i_line_p1_1", _INTENT_PATH)
    if _INTENT_SPEC is None or _INTENT_SPEC.loader is None:
        raise ImportError(f"cannot load Isaac P1 intent parser from {_INTENT_PATH}")
    _intent_mod = importlib.util.module_from_spec(_INTENT_SPEC)
    sys.modules[_INTENT_SPEC.name] = _intent_mod
    _INTENT_SPEC.loader.exec_module(_intent_mod)
    parse_intent_dry_run = _intent_mod.parse_intent_dry_run  # type: ignore[assignment]
    parse_intent_with_provider_dry_run = _intent_mod.parse_intent_with_provider_dry_run  # type: ignore[assignment]

try:
    from .isaac_intent_provider_bridge_p15 import build_intent_provider_from_bridge_config
except Exception:  # pragma: no cover - supports direct file loading in tests.
    try:
        import importlib.util
        import sys
        from pathlib import Path

        _BRIDGE_PATH = Path(__file__).resolve().with_name("isaac_intent_provider_bridge_p15.py")
        _BRIDGE_SPEC = importlib.util.spec_from_file_location("isaac_intent_provider_bridge_p15_for_i_line_p0", _BRIDGE_PATH)
        if _BRIDGE_SPEC is None or _BRIDGE_SPEC.loader is None:
            raise ImportError(f"cannot load Isaac P1.5 provider bridge from {_BRIDGE_PATH}")
        _bridge_mod = importlib.util.module_from_spec(_BRIDGE_SPEC)
        sys.modules[_BRIDGE_SPEC.name] = _bridge_mod
        _BRIDGE_SPEC.loader.exec_module(_bridge_mod)
        build_intent_provider_from_bridge_config = _bridge_mod.build_intent_provider_from_bridge_config  # type: ignore[assignment]
    except Exception:
        build_intent_provider_from_bridge_config = None  # type: ignore[assignment]


try:
    from .isaac_readonly_health import build_readonly_health_snapshot
except Exception:  # pragma: no cover - supports direct file loading in tests.
    try:
        import importlib.util
        import sys
        from pathlib import Path

        _HEALTH_PATH = Path(__file__).resolve().with_name("isaac_readonly_health.py")
        _HEALTH_SPEC = importlib.util.spec_from_file_location("isaac_readonly_health_for_i_line_p0", _HEALTH_PATH)
        if _HEALTH_SPEC is None or _HEALTH_SPEC.loader is None:
            raise ImportError(f"cannot load Isaac read-only health builder from {_HEALTH_PATH}")
        _health_mod = importlib.util.module_from_spec(_HEALTH_SPEC)
        sys.modules[_HEALTH_SPEC.name] = _health_mod
        _HEALTH_SPEC.loader.exec_module(_health_mod)
        build_readonly_health_snapshot = _health_mod.build_readonly_health_snapshot  # type: ignore[assignment]
    except Exception:
        build_readonly_health_snapshot = None  # type: ignore[assignment]

try:
    from .isaac_dry_run_plan import build_dry_run_plan
except Exception:  # pragma: no cover - supports direct file loading in tests.
    import importlib.util
    import sys
    from pathlib import Path

    _DRY_PATH = Path(__file__).resolve().with_name("isaac_dry_run_plan.py")
    _DRY_SPEC = importlib.util.spec_from_file_location("isaac_dry_run_plan_for_i_line_p0", _DRY_PATH)
    if _DRY_SPEC is None or _DRY_SPEC.loader is None:
        raise ImportError(f"cannot load Isaac dry_run_plan builder from {_DRY_PATH}")
    _dry_mod = importlib.util.module_from_spec(_DRY_SPEC)
    sys.modules[_DRY_SPEC.name] = _dry_mod
    _DRY_SPEC.loader.exec_module(_dry_mod)
    build_dry_run_plan = _dry_mod.build_dry_run_plan  # type: ignore[assignment]

try:  # Reuse A-line schema validation as a passive contract checker only.
    from tools.agent_bus.agent_bus_a1_schema import sha256_payload, validate_message_envelope
except Exception:  # pragma: no cover - supports direct file loading in tests.
    try:
        import importlib.util
        import sys
        from pathlib import Path

        _PROJECT_ROOT = Path(__file__).resolve().parents[4]
        _SCHEMA_PATH = _PROJECT_ROOT / "tools" / "agent_bus" / "agent_bus_a1_schema.py"
        _SPEC = importlib.util.spec_from_file_location("agent_bus_a1_schema_for_i_line_p0", _SCHEMA_PATH)
        if _SPEC is None or _SPEC.loader is None:
            raise ImportError(f"cannot load Agent Bus schema from {_SCHEMA_PATH}")
        _schema_mod = importlib.util.module_from_spec(_SPEC)
        sys.modules[_SPEC.name] = _schema_mod
        _SPEC.loader.exec_module(_schema_mod)
        sha256_payload = _schema_mod.sha256_payload  # type: ignore[assignment]
        validate_message_envelope = _schema_mod.validate_message_envelope  # type: ignore[assignment]
    except Exception:
        sha256_payload = None  # type: ignore[assignment]
        validate_message_envelope = None  # type: ignore[assignment]


# Isaac Agent v0.1 (LLM-driven readonly tool chooser).  Optional import:
# agent_v0.py is the new I叔 decision layer.  It is fail-soft: if the module
# cannot be loaded (older layouts, missing path), we fall back to the existing
# P0 built-in worker dispatcher without losing any owner/private gate behavior.
_isaac_agent_module = None
_isaac_agent_import_error: str | None = None
try:  # pragma: no cover - import shim only
    from .isaac_agent.agent_v0 import (
        IsaacAgent as _IsaacAgentCls,
        READONLY_TOOLS as _ISAAC_READONLY_TOOLS,
    )
    _isaac_agent_module = _IsaacAgentCls
except Exception:
    try:
        import importlib.util as _il
        import sys as _sys
        from pathlib import Path as _P

        _AGENT_DIR = Path(__file__).resolve().parent / "isaac_agent"
        _AGENT_FILE = _AGENT_DIR / "agent_v0.py"
        if _AGENT_FILE.exists():
            _spec = _il.spec_from_file_location("isaac_agent_v0_for_bus_p0", _AGENT_FILE)
            if _spec is not None and _spec.loader is not None:
                _mod = _il.module_from_spec(_spec)
                _sys.modules[_spec.name] = _mod
                _spec.loader.exec_module(_mod)
                _isaac_agent_module = getattr(_mod, "IsaacAgent", None)
                _ISAAC_READONLY_TOOLS = getattr(_mod, "READONLY_TOOLS", None)
    except Exception as exc:  # pragma: no cover - defensive only
        _isaac_agent_module = None
        _isaac_agent_import_error = f"{type(exc).__name__}: {exc}"

# Mapping: IsaacAgent readonly tool name -> P0 built-in task_type.
# The agent only narrows/rejects; it never promotes to a non-allowed task_type.
_AGENT_TOOL_TO_P0_TASK = {
    "health": "health_report",
    "workspace": "workspace_report",
    "audit": "audit_report",
    "status": "status_report",
    "dry_run_plan": "dry_run_plan",
    "agentbus_factory": "agentbus_factory_report",
}


def _resolve_available_router() -> Any | None:
    """Locate an available model_router instance for IsaacAgent.

    Priority: explicit module attribute, then well-known globals on the parent
    plugin package.  Returns None when no router is reachable; callers must
    treat that as a fail-soft condition and stay on the existing P0 worker.
    """
    for owner in (globals(),):
        candidate = owner.get("_isaac_p0_model_router")
        if candidate is not None:
            return candidate
    try:
        import yangyang  # type: ignore
    except Exception:
        yangyang = None  # type: ignore
    if yangyang is not None:
        for attr in ("router", "model_router", "_router"):
            cand = getattr(yangyang, attr, None)
            if cand is not None and hasattr(cand, "call_via_tier"):
                return cand
    return None


def _build_isaac_agent_for_bus(router: Any | None) -> Any | None:
    """Construct an IsaacAgent bound to the supplied router.  None if unavailable."""
    if _isaac_agent_module is None or router is None:
        return None
    try:
        return _isaac_agent_module(model_router=router)
    except Exception:
        return None


def _isaac_agent_decide_for_p0(
    agent: Any,
    *,
    command_text: str,
    task_type: str,
    request_id: str,
) -> dict[str, Any]:
    """Run IsaacAgent.think() and map its decision to a P0 verdict.

    Returns a dict with keys: allow (bool), reason (str), agent_task_type (str|None),
    decision (object|None).  Never raises; all errors map to allow=True with
    reason="agent_unavailable" so the existing P0 built-in worker still runs.
    """
    if agent is None:
        return {"allow": True, "reason": "agent_unavailable", "agent_task_type": None, "decision": None}
    try:
        decision = agent.think(user_intent=command_text, request_id=request_id)
    except Exception as exc:  # noqa: BLE001 - fail-soft to keep P0 running.
        return {
            "allow": True,
            "reason": f"agent_think_error:{type(exc).__name__}",
            "agent_task_type": None,
            "decision": None,
        }
    chosen = str(getattr(decision, "chosen_tool", "") or "")
    blocked = str(getattr(decision, "blocked_reason", "") or "")
    if blocked:
        if blocked.startswith("llm_error:"):
            return {
                "allow": True,
                "reason": f"agent_unavailable:{blocked[:96]}",
                "agent_task_type": None,
                "decision": decision,
            }
        # LLM picked something forbidden or out of registry.  Fail closed.
        return {
            "allow": False,
            "reason": f"forbidden_or_unsupported_tool:{blocked}",
            "agent_task_type": None,
            "decision": decision,
        }
    if not chosen:
        # Fail-soft for explicit P0 slash commands: provider/local-safe fallback
        # may produce no tool choice, but slash commands are already rule-resolved
        # and should still reach the built-in read-only worker.  Natural-language
        # delegates are blocked later unless reason == agent_endorsed.
        return {
            "allow": True,
            "reason": "agent_no_choice_fallback",
            "agent_task_type": None,
            "decision": decision,
        }
    mapped = _AGENT_TOOL_TO_P0_TASK.get(chosen)
    if mapped is None:
        return {
            "allow": False,
            "reason": f"agent_tool_not_mapped:{chosen}",
            "agent_task_type": None,
            "decision": decision,
        }
    if mapped not in ALLOWED_TASK_TYPES:
        return {
            "allow": False,
            "reason": f"mapped_task_not_allowed:{mapped}",
            "agent_task_type": None,
            "decision": decision,
        }
    # Soft check: if the LLM-chosen tool disagrees with the P0 rule-resolved
    # task_type, prefer the agent's choice (it had prompt context) but only when
    # the LLM choice is a P0-allowed task.  Otherwise stay on the original.
    final_task_type = mapped if mapped in ALLOWED_TASK_TYPES else task_type
    return {
        "allow": True,
        "reason": "agent_endorsed",
        "agent_task_type": final_task_type,
        "decision": decision,
    }


def _agent_audit_from_verdict(verdict: dict[str, Any]) -> dict[str, Any]:
    """Small, redacted audit summary for IsaacAgent decision layer."""
    decision = verdict.get("decision") if isinstance(verdict, dict) else None
    blocked = str(getattr(decision, "blocked_reason", "") or "") if decision is not None else ""
    used_tier = (
        str(getattr(decision, "model_tier", "") or "")
        if decision is not None
        else ""
    )
    tool_output = getattr(decision, "tool_output", {}) if decision is not None else {}
    tool_status = ""
    if isinstance(tool_output, dict):
        tool_status = str(tool_output.get("status") or "")[:64]
    return {
        "agent_called": bool(decision is not None),
        "agent_reason": str(verdict.get("reason", "") or "") if isinstance(verdict, dict) else "",
        "agent_chosen_tool": str(getattr(decision, "chosen_tool", "") or "") if decision is not None else "",
        "agent_used_tier": used_tier,
        "agent_llm_error": blocked if "llm_error" in blocked else "",
        "agent_tool_executed": bool(getattr(decision, "tool_executed", False)) if decision is not None else False,
        "agent_tool_latency_ms": int(getattr(decision, "tool_latency_ms", 0) or 0) if decision is not None else 0,
        "agent_tool_status": tool_status,
        "agent_tool_blocked_reason": str(getattr(decision, "tool_blocked_reason", "") or "")[:96] if decision is not None else "",
    }


def _build_agent_executed_worker_result(task_type: str, verdict: dict[str, Any], task_request: Mapping[str, Any]) -> dict[str, Any] | None:
    """Use IsaacAgent's v0.2 readonly execution result for whitelisted tools."""
    if task_type != "agentbus_factory_report":
        return None
    decision = verdict.get("decision") if isinstance(verdict, dict) else None
    if decision is None:
        return None
    if str(getattr(decision, "chosen_tool", "") or "") != "agentbus_factory":
        return None
    if not bool(getattr(decision, "tool_executed", False)):
        return None
    tool_output = getattr(decision, "tool_output", {})
    if not isinstance(tool_output, dict):
        tool_output = {"status": "non_dict_tool_output"}
    request_envelope = dict(task_request.get("envelope") or {})
    task_id = _safe_slug(f"i_line_p0_task_{_hash16(request_envelope.get('message_id', task_type))}", prefix="task")
    return {
        "schema_version": RESULT_PAYLOAD_SCHEMA_VERSION,
        "task_id": task_id,
        "task_type": task_type,
        "status": "PASS" if not str(getattr(decision, "tool_blocked_reason", "") or "") else "WARN",
        "isaac_worker": "isaac_agent_v02_readonly_tool",
        "workspace_only": True,
        "read_only": True,
        "executor_enabled": False,
        "host_probe_enabled": False,
        "service_control_enabled": False,
        "host_action_executed": False,
        "provider_network_used": False,
        "production_memory_accessed": False,
        "diagnostics": {
            "agentbus_factory_check": "isaac_agent_v02_readonly_tool",
            "agentbus_factory_report": tool_output,
            "external_delivery_performed": False,
            "agent_tool_executed": True,
            "agent_tool_latency_ms": int(getattr(decision, "tool_latency_ms", 0) or 0),
            "agent_tool_blocked_reason": str(getattr(decision, "tool_blocked_reason", "") or "")[:96],
        },
    }


def _extract_agent_ping_intent(command_text: str) -> str | None:
    """Return the payload for `/i叔 agent_ping ...`, or None when not a ping."""
    text = str(command_text or "").strip()
    if not text:
        return None
    match = re.match(r"^(?:agent[_\s-]?ping|ping[_\s-]?agent)(?:\s*[:：/\-]\s*|\s+|$)(.*)$", text, flags=re.I | re.S)
    if not match:
        return None
    payload = str(match.group(1) or "").strip()
    return payload or "看看系统状态"


def _agent_ping_redact(value: Any, limit: int = 160) -> str:
    """Tiny reply redactor for QQ-visible agent_ping fields."""
    s = str(value or "")
    lowered = s.lower()
    sensitive_markers = (
        "api_key", "apikey", "token", "secret", "password", "passwd",
        "base_url", "authorization", "cookie", "session", ".env", "sk-",
        "/opt", "runtime_config", "long_term", "memories.jsonl",
    )
    if any(marker in lowered for marker in sensitive_markers):
        return "[redacted]"
    return s[:limit]


def _format_agent_ping_reply(
    *,
    llm_called: bool,
    request_id: str,
    chosen_tool: str = "",
    blocked_reason: str = "",
    model_tier: str = "",
    tool_executed: bool = False,
    tool_status: str = "",
    tool_latency_ms: int = 0,
    tool_blocked_reason: str = "",
) -> str:
    return (
        "I叔 agent_ping v0.2：\n"
        "route=isaac_agent_v0\n"
        f"llm_called={str(bool(llm_called)).lower()}\n"
        f"request_id={_agent_ping_redact(request_id, 64)}\n"
        f"chosen_tool={_agent_ping_redact(chosen_tool, 64)}\n"
        f"blocked_reason={_agent_ping_redact(blocked_reason, 160)}\n"
        f"model_tier={_agent_ping_redact(model_tier, 64)}\n"
        f"tool_executed={str(bool(tool_executed)).lower()}\n"
        f"tool_status={_agent_ping_redact(tool_status, 64)}\n"
        f"tool_latency_ms={int(tool_latency_ms or 0)}\n"
        f"tool_blocked_reason={_agent_ping_redact(tool_blocked_reason, 160)}"
    )


def _handle_agent_ping(
    *,
    msg: Any,
    raw_text: str,
    command_text: str,
    model_router: Any | None = None,
    isaac_agent: Any | None = None,
) -> "IsaacP0HandleResult":
    """Direct QQ smoke for IsaacAgent v0.1.

    `/i叔 agent_ping <intent>` intentionally does not run the P0 builtin worker.
    It only proves the owner-private QQ path can reach IsaacAgent.think().
    High-risk words in <intent> are allowed here because no tool is executed;
    the LLM decision layer should expose blocked_reason instead.
    """
    intent = _extract_agent_ping_intent(command_text)
    if intent is None:
        return IsaacP0HandleResult(handled=False, allowed=False, reason="not_agent_ping", reply="")

    request_id = f"agent_ping_{_hash16(raw_text)}"
    router = model_router if model_router is not None else _resolve_available_router()
    agent = isaac_agent if isaac_agent is not None else _build_isaac_agent_for_bus(router)
    if agent is None:
        agent_audit = {
            "route": "isaac_agent_v0",
            "agent_called": False,
            "agent_reason": "agent_unavailable",
            "agent_chosen_tool": "",
            "agent_used_tier": "",
            "agent_llm_error": "",
        }
        return _with_isaac_p0_audit(
            IsaacP0HandleResult(
                handled=True,
                allowed=False,
                reason="agent_ping_unavailable",
                reply=_format_agent_ping_reply(llm_called=False, request_id=request_id),
                task_type="agent_ping",
                agent_audit=agent_audit,
            ),
            msg=msg,
            command_text=raw_text,
        )

    try:
        decision = agent.think(user_intent=intent, request_id=request_id)
    except Exception as exc:  # noqa: BLE001 - QQ smoke must fail closed.
        blocked = f"agent_think_error:{type(exc).__name__}"
        agent_audit = {
            "route": "isaac_agent_v0",
            "agent_called": True,
            "agent_reason": "agent_ping_exception",
            "agent_chosen_tool": "",
            "agent_used_tier": "",
            "agent_llm_error": blocked,
        }
        return _with_isaac_p0_audit(
            IsaacP0HandleResult(
                handled=True,
                allowed=False,
                reason="agent_ping_error",
                reply=_format_agent_ping_reply(llm_called=True, request_id=request_id, blocked_reason=blocked),
                task_type="agent_ping",
                agent_audit=agent_audit,
            ),
            msg=msg,
            command_text=raw_text,
        )

    chosen = str(getattr(decision, "chosen_tool", "") or "")
    blocked = str(getattr(decision, "blocked_reason", "") or "")
    if not chosen and not blocked:
        # The agent may correctly answer chosen_tool=null for requests outside
        # the readonly registry (for example restart/deploy).  Make that
        # visible in QQ instead of returning two blank fields.
        blocked = "no_readonly_tool_chosen"
    model_tier = str(getattr(decision, "model_tier", "") or "")
    tool_output = getattr(decision, "tool_output", {})
    tool_status = str(tool_output.get("status") or "")[:64] if isinstance(tool_output, dict) else ""
    agent_audit = {
        "route": "isaac_agent_v0",
        "agent_called": True,
        "agent_reason": "agent_ping",
        "agent_chosen_tool": chosen,
        "agent_used_tier": model_tier,
        "agent_llm_error": blocked if "llm_error" in blocked else "",
        "agent_tool_executed": bool(getattr(decision, "tool_executed", False)),
        "agent_tool_latency_ms": int(getattr(decision, "tool_latency_ms", 0) or 0),
        "agent_tool_status": tool_status,
        "agent_tool_blocked_reason": str(getattr(decision, "tool_blocked_reason", "") or "")[:96],
    }
    return _with_isaac_p0_audit(
        IsaacP0HandleResult(
            handled=True,
            allowed=not bool(blocked),
            reason="agent_ping_blocked" if blocked else "agent_ping_pass",
            reply=_format_agent_ping_reply(
                llm_called=True,
                request_id=request_id,
                chosen_tool=chosen,
                blocked_reason=blocked,
                model_tier=model_tier,
                tool_executed=bool(getattr(decision, "tool_executed", False)),
                tool_status=tool_status,
                tool_latency_ms=int(getattr(decision, "tool_latency_ms", 0) or 0),
                tool_blocked_reason=str(getattr(decision, "tool_blocked_reason", "") or ""),
            ),
            task_type="agent_ping",
            agent_audit=agent_audit,
        ),
        msg=msg,
        command_text=raw_text,
    )


P0_SCHEMA_VERSION = "i_line.p0.isaac_agent_bus_mvp.20260607"
TASK_PAYLOAD_SCHEMA_VERSION = "i_line.p0.task_payload.v1"
RESULT_PAYLOAD_SCHEMA_VERSION = "i_line.p0.task_result.v1"

ISAAC_SLASH_TOKENS = frozenset({"i叔", "艾萨克"})
ISAAC_TRIGGER_PATTERN = re.compile(r"^/(?:i叔|艾萨克)(?=$|[\s/:：])", flags=re.I)
ALLOWED_TASK_TYPES = {"health_report", "workspace_report", "dry_run_plan", "help_report", "audit_report", "status_report", "agentbus_factory_report"}

# --- audit (P0 minimal, fails-soft) -----------------------------------------
_ISAAC_AUDIT_SCHEMA = "i_line.p0.audit.v1"
_ISAAC_AUDIT_FILENAME = "isaac_p0_audit.jsonl"
_ISAAC_AUDIT_ENV_DIR = "ISAAC_P0_AUDIT_DIR"
_ISAAC_AUDIT_MAX_BYTES = 2 * 1024 * 1024  # 2 MiB rotate threshold per file
_ISAAC_AUDIT_KEEP_ROTATIONS = 3
_FORBIDDEN_AUDIT_KEYS = frozenset({
    "api_key", "apikey", "token", "secret", "password", "passwd",
    "base_url", "endpoint", "env", "authorization", "cookie", "session",
    "raw_text", "raw_content", "full_prompt", "prompt", "messages",
})


def _resolve_isaac_audit_dir() -> Path:
    override = (os.environ.get(_ISAAC_AUDIT_ENV_DIR) or "").strip()
    if override:
        return Path(override).expanduser()
    # Production layout: src/plugins/yangyang/data/audit/
    try:
        pkg_root = Path(__file__).resolve().parent.parent  # .../yangyang/
        candidate = pkg_root / "data" / "audit"
        return candidate
    except Exception:
        return Path("/tmp/isaac_p0_audit")


def _audit_dir_safe(audit_dir: Path) -> Path:
    try:
        audit_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        return Path("/tmp/isaac_p0_audit").expanduser()
    return audit_dir


def _classify_isaac_trigger(command_text: str | None) -> tuple[str, str | None]:
    """Map raw input to (trigger_type, command_head).  Never returns raw text."""
    if command_text is None:
        return ("natural_llm", None)
    text = str(command_text).strip()
    if not text:
        return ("natural_llm", None)
    if text.startswith("/"):
        # Extract only the head token, drop the body.
        m = re.match(r"^/([^\s/:：]+)", text)
        if m:
            return ("slash_fallback", f"/{m.group(1)}")
        return ("slash_fallback", "/")
    return ("natural_llm", None)


def _redact_record(record: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in record.items():
        if k.lower() in _FORBIDDEN_AUDIT_KEYS:
            continue
        out[k] = v
    return out


def _rotate_isaac_audit_file(path: Path) -> None:
    try:
        if not path.exists() or path.stat().st_size < _ISAAC_AUDIT_MAX_BYTES:
            return
        # shift isaac_p0_audit.jsonl -> .1 -> .2 -> .3 (drop oldest)
        for idx in range(_ISAAC_AUDIT_KEEP_ROTATIONS, 0, -1):
            older = path.with_suffix(path.suffix + f".{idx}")
            newer = path.with_suffix(path.suffix + f".{idx - 1}")
            if older.exists():
                try:
                    older.unlink()
                except Exception:
                    pass
            if idx == 1:
                src = path
            else:
                src = path.with_suffix(path.suffix + f".{idx - 1}")
            if src.exists() and src != older:
                try:
                    src.rename(older)
                except Exception:
                    pass
    except Exception:
        pass


def _audit_decision_for_result(result: "IsaacP0HandleResult") -> str:
    if not bool(getattr(result, "handled", False)):
        return "ignored"
    if bool(getattr(result, "allowed", False)):
        return "handled"
    return "denied"


def _with_isaac_p0_audit(
    result: "IsaacP0HandleResult",
    *,
    msg: Any,
    command_text: str | None,
) -> "IsaacP0HandleResult":
    _record_isaac_p0_audit(
        msg=msg,
        command_text=command_text,
        decision=_audit_decision_for_result(result),
        reason=str(getattr(result, "reason", "") or ""),
        task_type=getattr(result, "task_type", None),
        agent_audit=getattr(result, "agent_audit", None),
    )
    return result


def _record_isaac_p0_audit(
    *,
    msg: Any,
    command_text: str | None,
    decision: str,
    reason: str,
    task_type: str | None,
    agent_audit: dict[str, Any] | None = None,
) -> None:
    """Fail-soft JSONL audit.  Never raises."""
    try:
        audit_dir = _audit_dir_safe(_resolve_isaac_audit_dir())
        audit_path = audit_dir / _ISAAC_AUDIT_FILENAME
        _rotate_isaac_audit_file(audit_path)
        trigger_type, command_head = _classify_isaac_trigger(command_text)
        uid_raw = str(getattr(msg, "user_id", "") or getattr(msg, "uid", "") or "")
        sender_qq = uid_raw.strip() or "unknown"
        # Hash the QQ to avoid storing a fully identifying value in the JSONL
        # while still allowing same-user correlation across lines.
        sender_qq_hash = hashlib.sha256(sender_qq.encode("utf-8", errors="ignore")).hexdigest()[:16] if sender_qq != "unknown" else "unknown"
        record = {
            "schema": _ISAAC_AUDIT_SCHEMA,
            "ts": _utc_now(),
            "run_id": uuid.uuid4().hex[:12],
            "channel": str(getattr(msg, "channel", "") or "unknown"),
            "sender_qq": sender_qq,
            "sender_qq_hash": sender_qq_hash,
            "user_id": sender_qq,  # legacy alias kept for spec, not a secret
            "is_owner": bool(getattr(msg, "is_owner", False)),
            "trigger_type": trigger_type,
            "command_head": command_head,
            "task_type": task_type,
            "decision": decision,
            "reason": str(reason or "")[:96],
            "audit_version": 1,
        }
        if agent_audit:
            safe_agent = {
                "route": str(agent_audit.get("route", "isaac_agent_v0") or "isaac_agent_v0")[:64],
                "agent_called": bool(agent_audit.get("agent_called", False)),
                "agent_reason": str(agent_audit.get("agent_reason", "") or "")[:96],
                "agent_chosen_tool": str(agent_audit.get("agent_chosen_tool", "") or "")[:64],
                "agent_used_tier": str(agent_audit.get("agent_used_tier", "") or "")[:64],
                "agent_llm_error": str(agent_audit.get("agent_llm_error", "") or "")[:96],
                "agent_tool_executed": bool(agent_audit.get("agent_tool_executed", False)),
                "agent_tool_latency_ms": int(agent_audit.get("agent_tool_latency_ms", 0) or 0),
                "agent_tool_status": str(agent_audit.get("agent_tool_status", "") or "")[:64],
                "agent_tool_blocked_reason": str(agent_audit.get("agent_tool_blocked_reason", "") or "")[:96],
            }
            record.update(safe_agent)
        else:
            record["route"] = "p0_handler"
        record = _redact_record(record)
        line = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        with audit_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except Exception as exc:  # pragma: no cover - defensive only
        try:
            _LOG.debug("isaac_p0_audit write failed: %s", type(exc).__name__)
        except Exception:
            pass


HIGH_RISK_MARKERS = (
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
    "command",
    "write_config",
    "runtime_config",
    "long_term",
    "memories.jsonl",
    ".env",
    "/opt",
    "重启",
    "部署",
    "上线",
    "发布",
    "执行命令",
    "跑命令",
    "终端",
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
    "端口",
    "服务器ip",
    "公网ip",
)

FORBIDDEN_BUS_SUBSTRINGS = (
    "/opt",
    ".env",
    "runtime_config",
    "long_term/memories.jsonl",
    "project_notes",
    "335059272",
)


@dataclass(frozen=True)
class IsaacP0HandleResult:
    handled: bool
    allowed: bool
    reason: str
    reply: str
    task_type: str | None = None
    task_request: dict[str, Any] | None = None
    task_result: dict[str, Any] | None = None
    worker_result: dict[str, Any] | None = None
    request_schema: dict[str, Any] | None = None
    result_schema: dict[str, Any] | None = None
    intent_preview: dict[str, Any] | None = None
    agent_audit: dict[str, Any] | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_payload(data: Any) -> str:
    if sha256_payload is not None:
        return sha256_payload(data)  # type: ignore[misc]
    return "sha256:" + hashlib.sha256(_stable_json(data).encode("utf-8")).hexdigest()


def _hash16(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()[:16]


def _safe_slug(text: str, *, prefix: str) -> str:
    slug = re.sub(r"[^a-z0-9_.:-]+", "_", str(text or "").lower()).strip("_:. -")
    if not slug:
        slug = "empty"
    if not slug[0].isalpha():
        slug = f"{prefix}_{slug}"
    return slug[:96]


def _extract_isaac_command(text: str) -> str | None:
    raw = str(text or "").strip()
    if not raw or not raw.startswith("/"):
        return None
    match = re.match(r"^/([^\s/:：]+)(.*)$", raw, flags=re.S)
    if not match:
        return None
    token = match.group(1).casefold()
    if token not in ISAAC_SLASH_TOKENS:
        return None
    tail = match.group(2) or ""
    if tail and not (tail[0].isspace() or tail[0] in "/:："):
        return None
    return tail.lstrip("/:：").strip()


def _contains_high_risk_marker(command_text: str) -> str | None:
    lowered = str(command_text or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    for marker in HIGH_RISK_MARKERS:
        marker_low = marker.lower()
        if marker_low in lowered or marker_low.replace(" ", "") in compact:
            return marker
    return None


def _resolve_task_type(command_text: str) -> tuple[str | None, str]:
    text = str(command_text or "").strip()
    lowered = text.lower()
    compact = re.sub(r"\s+", "", lowered)
    if not text:
        return "help_report", "default_empty_command"
    if any(token in compact for token in ("agentbus", "agent_bus", "factory", "workerfactory", "nekroworker", "nekro工位", "黑奴工厂", "工厂", "验尸报告", "验收报告", "collector", "validator", "writeartifacts", "write_artifacts")):
        return "agentbus_factory_report", "matched_agentbus_factory"
    if any(token in compact for token in ("help", "usage", "commands", "commandlist", "帮助", "说明", "命令", "用法", "菜单")):
        return "help_report", "matched_help"
    # status_report must be checked before health_report: "status" token overlaps.
    if any(token in compact for token in ("audit", "审计", "审计报告")):
        return "audit_report", "matched_audit"
    if any(token in compact for token in ("status", "状态", "情况", "总览", "面板")):
        # Bare "status" (from /i叔 status) -> status_report.  Natural phrases
        # with "status" still flow to health via the P1 preview/delegation
        # path because the explicit-rule check below requires exact token
        # match for status_report.
        return "status_report", "matched_status"
    if any(token in compact for token in ("health", "selfcheck", "check", "健康", "自检", "诊断", "巡检", "报错", "异常")):
        return "health_report", "matched_health"
    if any(token in compact for token in ("workspace", "workspacereport", "report")):
        return "workspace_report", "matched_workspace"
    if any(token in compact for token in ("dryrun", "dry_run", "plan")):
        return "dry_run_plan", "matched_dry_run_plan"
    return None, "unsupported_task"


def _compact_command(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").lower())


def _is_explicit_p0_rule_command(command_text: str, task_type: str | None) -> bool:
    text = str(command_text or "").strip()
    if not text:
        return task_type == "help_report"
    compact = _compact_command(text)
    exact_tokens = {
        "help_report": {"help", "usage", "commands", "commandlist", "帮助", "命令", "用法", "菜单"},
        "health_report": {"health", "selfcheck", "check", "健康", "自检", "诊断", "巡检"},
        "workspace_report": {"workspace", "workspacereport", "report", "工作区", "项目状态", "项目进度"},
        "audit_report": {"audit", "审计", "审计报告", "audit_report"},
        "status_report": {"status", "状态", "情况", "总览", "面板", "isaacstatus", "i叔status"},
        "dry_run_plan": {"dryrun", "dry_run", "plan", "演练", "计划", "预案"},
        "agentbus_factory_report": {"agentbus", "agent_bus", "factory", "workerfactory", "黑奴工厂", "工厂", "验尸报告", "验收报告", "collector", "validator", "writeartifacts", "write_artifacts"},
    }.get(str(task_type or ""), set())
    if compact in exact_tokens:
        return True
    # Keep broad substring matching for ASCII/operator commands, but avoid
    # treating every natural Chinese sentence containing “状态/异常/报错” as an
    # explicit P0 rule command.  Those go through P1 preview first and only
    # health delegates with real system/error wording are promoted below.
    explicit_ascii_tokens = {
        "help_report": ("help", "usage", "commands", "commandlist"),
        "health_report": ("health", "selfcheck", "check"),
        "workspace_report": ("workspace", "workspacereport", "report"),
        "audit_report": ("audit", "audit_report"),
        "status_report": ("status",),
        "dry_run_plan": ("dryrun", "dry_run", "plan"),
        "agentbus_factory_report": ("agentbus", "agent_bus", "factory", "workerfactory", "collector", "validator", "writeartifacts", "write_artifacts"),
    }.get(str(task_type or ""), ())
    if any(token in compact for token in explicit_ascii_tokens):
        return True
    # /i叔 plan <need> form (compact starts with "plan" and has more chars).
    if task_type == "dry_run_plan" and compact.startswith("plan") and len(compact) > len("plan"):
        return True
    return False


def _should_promote_natural_health_delegate(command_text: str) -> bool:
    raw = str(command_text or "").lower()
    compact = _compact_command(raw)
    if compact in {"health", "status", "selfcheck", "check", "健康", "状态", "自检", "诊断", "巡检"}:
        return True
    # Any local, owner-private health intent is safe to promote: the promoted
    # path is still read-only, workspace-only, no provider, and no executor.
    promote_markers = (
        "系统",
        "状态",
        "情况",
        "异常",
        "运行",
        "还好吗",
        "报错",
        "错误",
        "日志",
        "插件",
        "健康",
        "健康摘要",
        "健康快照",
        "真实状态",
        "实际状态",
        "readonlyhealth",
        "read-onlyhealth",
        "realhealth",
        "health",
        "status",
        "runtime",
        "error",
        "exception",
        "traceback",
        "plugin",
        "log",
    )
    return any(marker in raw or marker in compact for marker in promote_markers)


def _validate_bus_message(message: dict[str, Any]) -> dict[str, Any]:
    if validate_message_envelope is None:
        return {
            "valid": False,
            "verdict": "BLOCKED",
            "failure_class": "schema_unavailable",
            "reason": "Agent Bus A1.1 schema validator is unavailable",
            "safe_to_route_in_memory": False,
        }
    return validate_message_envelope(message)  # type: ignore[misc]


def _make_envelope(
    *,
    message_type: str,
    source_agent: str,
    target_agent: str,
    actor_context: dict[str, Any],
    session_scope: dict[str, Any],
    payload: dict[str, Any],
    capability: str,
    correlation_id: str,
    trace_id: str,
    parent_message_id: str | None = None,
    seen_by: list[str] | None = None,
) -> dict[str, Any]:
    payload_digest = _sha256_payload(payload)
    mid_seed = _stable_json([message_type, source_agent, target_agent, payload_digest, parent_message_id or ""])
    message_id = _safe_slug(f"msg_i_line_p0_{_hash16(mid_seed)}", prefix="msg")
    payload_ref = f"inline_redacted://i_line_p0/{message_type}/{_hash16(payload_digest)}"
    return {
        "type": message_type,
        "envelope": {
            "message_id": message_id,
            "message_type": message_type,
            "correlation_id": correlation_id,
            "parent_message_id": parent_message_id,
            "trace_id": trace_id,
            "source_agent": source_agent,
            "target_agent": target_agent,
            "actor_context": actor_context,
            "session_scope": session_scope,
            "risk_level": "low",
            "capability_requested": capability,
            "payload_ref": payload_ref,
            "payload_digest": payload_digest,
            "created_at": _utc_now(),
            "ttl_seconds": 300,
            "requires_owner_approval": False,
            "requires_second_factor": False,
            "loop_guard": {
                "max_hops": 6,
                "hop_count": 0,
                "seen_by": list(seen_by or [source_agent, "agent_bus_p0"]),
                "idempotency_key": _safe_slug(f"idem:i_line_p0:{_hash16(mid_seed)}", prefix="idem"),
                "cooldown_seconds": 0,
                "reply_policy": "result_once",
                "stop_on_signal": True,
            },
        },
        "payload_inline_redacted": payload,
        "status": None,
        "failure": None,
    }


def _build_task_request(task_type: str, *, text_hash: str, parse_reason: str, command_text: str = "") -> dict[str, Any]:
    payload = {
        "schema_version": TASK_PAYLOAD_SCHEMA_VERSION,
        "task_type": task_type,
        "task_title_redacted": f"isaac_p0_{task_type}",
        "request_text_sha256_16": text_hash,
        "raw_text_included": False,
        "command_text_redacted": "[redacted]" if command_text else "",
        "command_text": command_text,
        "workspace_only": True,
        "read_only": True,
        "executor_enabled": False,
        "host_action_executed": False,
        "parse_reason": parse_reason,
    }
    correlation_id = _safe_slug(f"corr_i_line_p0_{text_hash}", prefix="corr")
    trace_id = _safe_slug(f"trace_i_line_p0_{text_hash}", prefix="trace")
    actor_context = {
        "actor_type": "owner",
        "actor_id_redacted": "owner_redacted",
        "channel": "owner_private",
        "owner_verified": True,
        "group_id_redacted": None,
        "source_trust": "owner_verified",
    }
    session_scope = {
        "scope_type": "private_user",
        "scope_id_redacted": "private_user_redacted",
        "visibility": "owner_private",
    }
    return _make_envelope(
        message_type="task_request",
        source_agent="yangyang_owner_private",
        target_agent="isaac_worker_p0",
        actor_context=actor_context,
        session_scope=session_scope,
        payload=payload,
        capability="dry_run_review",
        correlation_id=correlation_id,
        trace_id=trace_id,
        seen_by=["yangyang_owner_private", "agent_bus_p0"],
    )


def _build_readonly_health_snapshot_safe() -> dict[str, Any]:
    if build_readonly_health_snapshot is None:
        return {
            "schema_version": "i_line.readonly_health.v1.unavailable",
            "generated_at": _utc_now(),
            "overall_status": "WARN",
            "read_only": True,
            "workspace_only": True,
            "builder_unavailable": True,
            "gate_state": {
                "owner_private_only": True,
                "group_exposure": False,
                "high_risk_blocked": True,
                "provider_enabled": False,
                "executor_enabled": False,
            },
            "recent_errors": {"status": "log_source_unavailable", "log_source_unavailable": True},
            "data_integrity": {"sensitive_body_read": False, "sensitive_body_output": False},
        }
    try:
        return build_readonly_health_snapshot(plugin_loaded_marker=True, handler_available=True)  # type: ignore[misc]
    except Exception as exc:  # pragma: no cover - defensive fail-soft snapshot only.
        return {
            "schema_version": "i_line.readonly_health.v1.error",
            "generated_at": _utc_now(),
            "overall_status": "WARN",
            "read_only": True,
            "workspace_only": True,
            "builder_error": True,
            "builder_error_type": type(exc).__name__,
            "gate_state": {
                "owner_private_only": True,
                "group_exposure": False,
                "high_risk_blocked": True,
                "provider_enabled": False,
                "executor_enabled": False,
            },
            "recent_errors": {"status": "log_source_unavailable", "log_source_unavailable": True},
            "data_integrity": {"sensitive_body_read": False, "sensitive_body_output": False},
        }


def _run_isaac_builtin_worker(task_type: str, task_request: Mapping[str, Any]) -> dict[str, Any]:
    request_envelope = dict(task_request.get("envelope") or {})
    task_id = _safe_slug(f"i_line_p0_task_{_hash16(request_envelope.get('message_id', task_type))}", prefix="task")
    base = {
        "schema_version": RESULT_PAYLOAD_SCHEMA_VERSION,
        "task_id": task_id,
        "task_type": task_type,
        "status": "PASS",
        "isaac_worker": "isaac_builtin_readonly_p0",
        "workspace_only": True,
        "read_only": True,
        "executor_enabled": False,
        "host_probe_enabled": False,
        "service_control_enabled": False,
        "host_action_executed": False,
        "provider_network_used": False,
        "production_memory_accessed": False,
    }
    if task_type == "health_report":
        snapshot = _build_readonly_health_snapshot_safe()
        base["readonly_health_snapshot"] = snapshot
        base["diagnostics"] = {
            "health": str(snapshot.get("overall_status") or "unknown").lower(),
            "agent_bus_request_seen": True,
            "no_executor_mode": True,
            "snapshot_schema_version": snapshot.get("schema_version"),
        }
    elif task_type == "help_report":
        base["diagnostics"] = {
            "help": "I叔 P0 仅支持 owner 私聊的 read-only 诊断命令",
            "allowed_commands": [
                "/i叔 help",
                "/i叔 health",
                "/i叔 workspace report",
                "/i叔 dry_run plan",
            ],
            "blocked_by_default": [
                "system_control_redacted",
                "config_or_memory_material_redacted",
                "group_trigger_redacted",
            ],
        }
    elif task_type == "workspace_report":
        workspace_report = _import_workspace_report_builder()()
        base["diagnostics"] = {
            "workspace_check": "filesystem_readonly",
            "filesystem_scan_performed": True,
            "allowed_scope": "workspace_metadata_only",
            "report_schema_version": workspace_report.get("schema_version"),
            "workspace_report": workspace_report,
        }
    elif task_type == "audit_report":
        report = _import_audit_report_builder()(audit_dir=_resolve_isaac_audit_dir())
        base["diagnostics"] = {
            "audit_check": "jsonl_readonly",
            "audit_report": report,
        }
    elif task_type == "status_report":
        report = _import_audit_status_builder()(audit_dir=_resolve_isaac_audit_dir())
        base["diagnostics"] = {
            "status_check": "audit_plus_capabilities",
            "status_report": report,
        }
    elif task_type == "dry_run_plan":
        # command_text lives in payload_inline_redacted (not envelope.payload).
        cmd_text = str(
            (task_request.get("payload_inline_redacted") or {}).get("command_text", "")
            or ""
        )
        need = ""
        m = re.search(r"(?:dry[_ ]?run\s+plan|plan)[ 	]*(.*)$", cmd_text, flags=re.I)
        if m:
            need = (m.group(1) or "").strip()
        plan = build_dry_run_plan(need)
        base["diagnostics"] = {
            "plan_check": "readonly_plan_v1",
            "dry_run_plan": plan,
            "external_delivery_performed": False,
        }
    elif task_type == "agentbus_factory_report":
        report = _import_agentbus_factory_report_builder()()
        base["diagnostics"] = {
            "agentbus_factory_check": "readonly_latest_run_v1",
            "agentbus_factory_report": report,
            "external_delivery_performed": False,
        }
    else:  # Defensive only; callers should allowlist before invoking.
        base["status"] = "BLOCKED"
        base["diagnostics"] = {"reason": "unsupported_task"}
    return base


def _build_task_result(task_request: dict[str, Any], worker_result: dict[str, Any]) -> dict[str, Any]:
    request_envelope = dict(task_request.get("envelope") or {})
    actor_context = {
        "actor_type": "agent",
        "actor_id_redacted": "agent_isaac_worker_p0",
        "channel": "internal_bus",
        "owner_verified": False,
        "group_id_redacted": None,
        "source_trust": "trusted_agent",
    }
    session_scope = {
        "scope_type": "internal",
        "scope_id_redacted": "internal_i_line_p0_redacted",
        "visibility": "internal_only",
    }
    return _make_envelope(
        message_type="task_result",
        source_agent="isaac_worker_p0",
        target_agent="yangyang_owner_private",
        actor_context=actor_context,
        session_scope=session_scope,
        payload=worker_result,
        capability="dry_run_review",
        correlation_id=str(request_envelope.get("correlation_id") or "corr_i_line_p0_fallback"),
        trace_id=str(request_envelope.get("trace_id") or "trace_i_line_p0_fallback"),
        parent_message_id=str(request_envelope.get("message_id") or "msg_i_line_p0_fallback"),
        seen_by=["isaac_worker_p0", "agent_bus_p0"],
    )


def _bus_payload_has_forbidden_material(*messages: Mapping[str, Any]) -> str | None:
    text = _stable_json(list(messages)).lower()
    for marker in FORBIDDEN_BUS_SUBSTRINGS:
        if marker.lower() in text:
            return marker
    return None


def _bool_text(value: Any) -> str:
    return str(bool(value)).lower()


def _format_readonly_health_snapshot(snapshot: Mapping[str, Any]) -> str:
    gate = dict(snapshot.get("gate_state") or {})
    runtime = dict(snapshot.get("runtime_visible") or {})
    recent = dict(snapshot.get("recent_errors") or {})
    baseline = dict(snapshot.get("baseline") or {})
    integrity = dict(snapshot.get("data_integrity") or {})
    effects = dict(snapshot.get("external_effects") or {})
    regression = str(baseline.get("regression_summary") or "-").replace("\n", " ")[:96]
    return (
        f"readonly_health_snapshot={snapshot.get('overall_status') or 'unknown'} schema={snapshot.get('schema_version') or '-'}\n"
        "gate "
        f"owner_private_only={_bool_text(gate.get('owner_private_only'))} "
        f"group_exposure={_bool_text(gate.get('group_exposure'))} "
        f"high_risk_blocked={_bool_text(gate.get('high_risk_blocked'))} "
        f"provider_enabled={_bool_text(gate.get('provider_enabled'))} "
        f"executor_enabled={_bool_text(gate.get('executor_enabled'))}\n"
        "runtime "
        f"plugin_loaded={_bool_text(runtime.get('plugin_loaded_marker'))} "
        f"i_line_module_importable={_bool_text(runtime.get('i_line_module_importable'))} "
        f"handler_available={_bool_text(runtime.get('handler_available'))}\n"
        "recent_errors "
        f"status={recent.get('status') or 'unknown'} "
        f"log_source_unavailable={_bool_text(recent.get('log_source_unavailable'))} "
        f"sampled_sources={recent.get('sampled_source_count', 0)} "
        f"error_markers={recent.get('error_marker_count', 0)} "
        f"tracebacks={recent.get('traceback_marker_count', 0)} "
        f"failed_tests={recent.get('failed_test_marker_count', 0)}\n"
        "baseline "
        f"conclusion={baseline.get('conclusion') or 'unknown'} "
        f"status={baseline.get('bundle_status') or '-'} "
        f"date={baseline.get('baseline_date') or '-'} "
        f"regression={regression}\n"
        "data_integrity "
        f"status={integrity.get('status') or 'unknown'} "
        f"sha_match={_bool_text(integrity.get('sha_match')) if integrity.get('sha_match') is not None else 'unknown'} "
        f"unchanged={_bool_text(integrity.get('unchanged')) if integrity.get('unchanged') is not None else 'unknown'} "
        f"sensitive_body_output={_bool_text(integrity.get('sensitive_body_output'))}\n"
        "effects "
        f"shell_used={_bool_text(effects.get('shell_used'))} "
        f"network_used={_bool_text(effects.get('network_used'))} "
        f"executor_used={_bool_text(effects.get('executor_used'))} "
        f"host_action_executed={_bool_text(effects.get('host_action_executed'))}"
    )


def _format_success_reply(task_type: str, request_schema: Mapping[str, Any], result_schema: Mapping[str, Any], worker_result: Mapping[str, Any], high_risk_markers: str | None = None) -> str:
    req_ok = str(bool(request_schema.get("valid"))).lower()
    res_ok = str(bool(result_schema.get("valid"))).lower()
    task_id = str(worker_result.get("task_id") or "-")
    base = (
        "I叔 P0 闭环已跑通：TaskRequest -> Isaac worker -> TaskResult。\n"
        f"task={task_type} task_id={task_id}\n"
        f"agent_bus_request_valid={req_ok} agent_bus_result_valid={res_ok}\n"
        "executor_enabled=false host_action_executed=false workspace_only=true read_only=true"
    )
    if task_type == "health_report":
        snapshot = dict(worker_result.get("readonly_health_snapshot") or {})
        return f"{base}\n{_format_readonly_health_snapshot(snapshot)}"
    if task_type == "workspace_report":
        diagnostics = dict(worker_result.get("diagnostics") or {})
        report = dict(diagnostics.get("workspace_report") or {})
        return f"{base}\n{_import_workspace_report_formatter()(report)}"
    if task_type == "help_report":
        return (
            f"{base}\n"
            "可用命令：/i叔 help / /i叔 health / /i叔 workspace / /i叔 audit / /i叔 status / /i叔 dry_run plan。\n"
            "边界：owner 私聊限定；高危操作、群聊触发、配置/记忆/宿主动作默认 blocked。"
        )
    if high_risk_markers:
        base += f"\
high_risk_detected=true markers={high_risk_markers}"
    if task_type == "audit_report":
        diagnostics = dict(worker_result.get("diagnostics") or {})
        report = dict(diagnostics.get("audit_report") or {})
        return f"{base}\naudit_check=jsonl_readonly\n{_import_audit_report_formatter()(report)}"
    if task_type == "status_report":
        diagnostics = dict(worker_result.get("diagnostics") or {})
        report = dict(diagnostics.get("status_report") or {})
        return f"{base}\nstatus_check=audit_plus_capabilities\n{_import_audit_status_formatter()(report)}"
    if task_type == "agentbus_factory_report":
        diagnostics = dict(worker_result.get("diagnostics") or {})
        report = dict(diagnostics.get("agentbus_factory_report") or {})
        return f"{base}\nagentbus_factory_check=readonly_latest_run_v1\n{_import_agentbus_factory_report_formatter()(report)}"
    return base


def _format_block_reply(reason: str, detail: str = "") -> str:
    suffix = f" detail={detail}" if detail else ""
    help_hint = " 可发送：/i叔 help 查看当前 P0 允许的只读命令。" if reason == "unsupported_task" else ""
    return (
        f"I叔 P0 已拦截：reason={reason}{suffix}\n"
        "当前只允许 owner 私聊触发、内部 Agent Bus、内置 read-only 诊断；高危操作默认 blocked。"
        f"{help_hint}"
    )


def _format_clarification_reply(command_text: str) -> str:
    preview = str(command_text or "").replace("\n", " ").strip()[:80]
    return (
        "I叔 P0 需要二次确认：我还不能确定要做哪一种只读诊断。\n"
        f"request_preview={preview or '-'}\n"
        "可以明确说：/i叔 help / /i叔 health / /i叔 workspace report / /i叔 dry_run plan。"
    )


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


def _intent_preview_payload(decision: Any) -> dict[str, Any]:
    return {
        "handled": bool(getattr(decision, "handled", False)),
        "allowed": bool(getattr(decision, "allowed", False)),
        "decision": str(getattr(decision, "decision", "") or ""),
        "reason": str(getattr(decision, "reason", "") or ""),
        "candidate": _candidate_preview_dict(getattr(decision, "candidate", None)),
        "would_dispatch_task_type": getattr(decision, "would_dispatch_task_type", None),
        "raw_model_output": dict(getattr(decision, "raw_model_output", None) or {}),
        "no_real_dispatch": True,
        "agent_bus_used": False,
        "task_request_dispatched": False,
        "executor_enabled": False,
        "provider_network_used": False,
    }


def _p1_preview_result_reason(decision: Any) -> str:
    reason = str(getattr(decision, "reason", "") or "")
    decision_name = str(getattr(decision, "decision", "") or "")
    if reason == "high_risk_blocked":
        return "high_risk_blocked"
    if decision_name == "would_dispatch_dry_run":
        return "would_dispatch_dry_run"
    if decision_name == "clarification_required":
        return "clarification_required"
    return reason or decision_name or "p1_preview_failed_closed"


def _format_p1_preview_reply(decision: Any) -> str:
    candidate = getattr(decision, "candidate", None)
    intent = str(getattr(candidate, "intent", "unknown") or "unknown") if candidate is not None else "unknown"
    try:
        confidence = f"{float(getattr(candidate, 'confidence', 0.0) or 0.0):.2f}" if candidate is not None else "-"
    except Exception:
        confidence = "-"
    risk = str(getattr(candidate, "risk_level", "unknown") or "unknown") if candidate is not None else "unknown"
    would_dispatch = getattr(decision, "would_dispatch_task_type", None) or "-"
    decision_name = str(getattr(decision, "decision", "") or "")
    result_reason = _p1_preview_result_reason(decision)
    common = (
        f"intent={intent} confidence={confidence} risk={risk} would_dispatch_task_type={would_dispatch}\n"
        "no_real_dispatch=true agent_bus_used=false task_request_dispatched=false "
        "executor_enabled=false provider_network_used=false"
    )
    if result_reason == "high_risk_blocked":
        return (
            "I叔 P1 preview：high_risk_blocked，识别到高风险意图，已拦截。\n"
            f"{common}\n"
            "不会接 runtime Agent Bus / Isaac executor / shell/systemctl/deploy。"
        )
    if decision_name == "would_dispatch_dry_run":
        return (
            "I叔 P1 preview：would_dispatch_dry_run（低风险自然语言意图预览）。\n"
            f"{common}\n"
            "本阶段只展示预览，不真实派发 TaskRequest。"
        )
    if decision_name == "clarification_required":
        return (
            "I叔 P1 preview：clarification_required，需要二次确认。\n"
            f"{common}\n"
            "可以明确说：/i叔 help / /i叔 health / /i叔 workspace report / /i叔 dry_run plan。"
        )
    return (
        f"I叔 P1 preview：blocked，reason={result_reason}。\n"
        f"{common}\n"
        "本阶段 fail-closed，不真实派发 TaskRequest。"
    )

def _handle_p1_intent_preview(raw_text: str, intent_provider: Any = None) -> IsaacP0HandleResult:
    decision = parse_intent_with_provider_dry_run(raw_text, provider=intent_provider)
    if not bool(getattr(decision, "handled", False)):
        return IsaacP0HandleResult(
            handled=True,
            allowed=False,
            reason="p1_preview_not_triggered",
            reply=_format_block_reply("p1_preview_not_triggered"),
            intent_preview=_intent_preview_payload(decision),
        )
    return IsaacP0HandleResult(
        handled=True,
        allowed=bool(getattr(decision, "allowed", False)),
        reason=_p1_preview_result_reason(decision),
        reply=_format_p1_preview_reply(decision),
        task_type=getattr(decision, "would_dispatch_task_type", None),
        intent_preview=_intent_preview_payload(decision),
    )


def handle_isaac_agent_bus_p0_message(
    msg: Any,
    intent_provider: Any = None,
    intent_provider_bridge_config: Any = None,
    model_router: Any | None = None,
    isaac_agent: Any | None = None,
) -> IsaacP0HandleResult:
    """Handle the I_LINE_P0 Isaac + Agent Bus MVP command.

    This function is intentionally self-contained and fail-closed.  It does not
    execute shell commands, connect providers/network, read production memory,
    write runtime config, or deliver external messages.  It only builds a
    sanitized in-memory Agent Bus TaskRequest, invokes the built-in no-executor
    Isaac P0 worker, validates the TaskResult, and returns a current-session
    reply string for the caller to send.
    """
    raw_text = str(getattr(msg, "text", "") or getattr(msg, "raw_content", "") or "")
    command_text = _extract_isaac_command(raw_text)
    natural_delegate = bool(
        getattr(msg, "isaac_p0_natural_delegate", False)
        or getattr(msg, "natural_llm_delegate", False)
    )
    if command_text is None and natural_delegate:
        # Trusted owner-toolbox/LLM delegation path: execute the read-only P0
        # command body while keeping audit classification as natural_llm.
        # Direct bare text without this explicit proxy flag remains ignored.
        command_text = raw_text.strip()
    if command_text is None:
        return _with_isaac_p0_audit(
            IsaacP0HandleResult(handled=False, allowed=False, reason="not_isaac_command", reply=""),
            msg=msg,
            command_text=raw_text,
        )
    slash_command = raw_text.strip().startswith("/")

    if str(getattr(msg, "channel", "") or "") != "private":
        return _with_isaac_p0_audit(
            IsaacP0HandleResult(handled=True, allowed=False, reason="private_only", reply=_format_block_reply("private_only")),
            msg=msg,
            command_text=raw_text,
        )
    if not bool(getattr(msg, "is_owner", False)):
        return _with_isaac_p0_audit(
            IsaacP0HandleResult(handled=True, allowed=False, reason="owner_only", reply=_format_block_reply("owner_only")),
            msg=msg,
            command_text=raw_text,
        )

    if _extract_agent_ping_intent(command_text) is not None:
        return _handle_agent_ping(
            msg=msg,
            raw_text=raw_text,
            command_text=command_text,
            model_router=model_router,
            isaac_agent=isaac_agent,
        )

    marker = _contains_high_risk_marker(command_text)
    high_risk_markers: str | None = None
    if marker:
        # dry_run_plan is the read-only planning surface; it must stay usable
        # for high-risk intents so owner can preview the plan.  Other task
        # types still hard-block.
        probe_type, _ = _resolve_task_type(command_text)
        if probe_type != "dry_run_plan":
            return _with_isaac_p0_audit(
                IsaacP0HandleResult(
                    handled=True,
                    allowed=False,
                    reason="high_risk_blocked",
                    reply=_format_block_reply("high_risk_blocked", str(marker)),
                ),
                msg=msg,
                command_text=raw_text,
            )
        # dry_run_plan: allow but collect all high-risk markers for reminder
        lowered = command_text.lower()
        high_risk_markers = ",".join(m for m in HIGH_RISK_MARKERS if m.lower() in lowered)

    task_type, parse_reason = _resolve_task_type(command_text)
    if task_type not in ALLOWED_TASK_TYPES or not _is_explicit_p0_rule_command(command_text, task_type):
        # Natural health delegation can now return a real read-only P0 snapshot.
        # Explicit test/future providers still stay on the P1 preview path: a
        # provider output must never silently authorize or dispatch P0 work.
        effective_intent_provider = intent_provider
        if effective_intent_provider is None and build_intent_provider_from_bridge_config is not None:
            effective_intent_provider = build_intent_provider_from_bridge_config(intent_provider_bridge_config)
        if effective_intent_provider is not None:
            return _with_isaac_p0_audit(
                _handle_p1_intent_preview(raw_text, intent_provider=effective_intent_provider),
                msg=msg,
                command_text=raw_text,
            )

        local_p1_result = _handle_p1_intent_preview(raw_text, intent_provider=None)
        if (
            local_p1_result.allowed
            and local_p1_result.reason == "would_dispatch_dry_run"
            and local_p1_result.task_type in ALLOWED_TASK_TYPES
            and natural_delegate
        ):
            # Trusted natural-language delegation from the owner/private LLM
            # path should continue into IsaacAgent, not stop at P1 preview.
            # P1 only classifies; IsaacAgent must endorse/narrow before the
            # builtin read-only worker runs.
            task_type = local_p1_result.task_type
            parse_reason = "matched_p1_natural_delegate"
        elif (
            local_p1_result.allowed
            and local_p1_result.task_type == "health_report"
            and local_p1_result.reason == "would_dispatch_dry_run"
            and _should_promote_natural_health_delegate(command_text)
        ):
            task_type = "health_report"
            parse_reason = "matched_p1_health_delegate"
        else:
            return _with_isaac_p0_audit(local_p1_result, msg=msg, command_text=raw_text)

    text_hash = _hash16(raw_text)

    # I叔 Agent v0.1 decision layer (optional).  When a model_router is reachable
    # and the IsaacAgent module loaded successfully, we ask the LLM to endorse
    # the readonly tool choice.  The agent can only narrow or reject; it can
    # never promote to a non-allowed task_type.  When unavailable, the existing
    # P0 built-in worker runs unchanged (fail-soft).
    _bus_router = model_router if model_router is not None else _resolve_available_router()
    _bus_agent = isaac_agent if isaac_agent is not None else _build_isaac_agent_for_bus(_bus_router)
    _agent_verdict = _isaac_agent_decide_for_p0(
        _bus_agent,
        command_text=command_text,
        task_type=task_type,
        request_id=text_hash,
    )
    _agent_audit = _agent_audit_from_verdict(_agent_verdict)
    tool_call_delegate = bool(getattr(msg, "isaac_p0_tool_call_delegate", False))
    if natural_delegate and not tool_call_delegate and str(_agent_verdict.get("reason") or "") != "agent_endorsed":
        return _with_isaac_p0_audit(
            IsaacP0HandleResult(
                handled=True,
                allowed=False,
                reason=str(_agent_verdict.get("reason") or "agent_not_endorsed"),
                reply=_format_block_reply(
                    str(_agent_verdict.get("reason") or "agent_not_endorsed"),
                    detail="natural_delegate_requires_agent_endorsement",
                ),
                task_type=task_type,
                agent_audit=_agent_audit,
            ),
            msg=msg,
            command_text=raw_text,
        )
    if not _agent_verdict.get("allow", True):
        return _with_isaac_p0_audit(
            IsaacP0HandleResult(
                handled=True,
                allowed=False,
                reason=str(_agent_verdict.get("reason") or "agent_blocked"),
                reply=_format_block_reply(
                    str(_agent_verdict.get("reason") or "agent_blocked"),
                    detail="agent_decision=blocked",
                ),
                task_type=task_type,
                agent_audit=_agent_audit,
            ),
            msg=msg,
            command_text=raw_text,
        )
    if (
        natural_delegate
        and _agent_verdict.get("agent_task_type")
        and _agent_verdict["agent_task_type"] in ALLOWED_TASK_TYPES
    ):
        task_type = _agent_verdict["agent_task_type"]
        parse_reason = f"agent_endorsed:{parse_reason}"
    elif _agent_verdict.get("agent_task_type") and slash_command:
        parse_reason = f"agent_endorsed_slash_preserved:{parse_reason}"

    task_request = _build_task_request(task_type, text_hash=text_hash, parse_reason=parse_reason, command_text=command_text)
    request_schema = _validate_bus_message(task_request)
    if not request_schema.get("valid"):
        return _with_isaac_p0_audit(
            IsaacP0HandleResult(
                handled=True,
                allowed=False,
                reason="task_request_schema_blocked",
                reply=_format_block_reply("task_request_schema_blocked", str(request_schema.get("failure_class") or request_schema.get("reason") or "schema")),
                task_type=task_type,
                task_request=task_request,
                request_schema=request_schema,
                agent_audit=_agent_audit,
            ),
            msg=msg,
            command_text=raw_text,
        )

    worker_result = _build_agent_executed_worker_result(task_type, _agent_verdict, task_request)
    if worker_result is None:
        worker_result = _run_isaac_builtin_worker(task_type, task_request)
    task_result = _build_task_result(task_request, worker_result)
    result_schema = _validate_bus_message(task_result)
    if not result_schema.get("valid"):
        return _with_isaac_p0_audit(
            IsaacP0HandleResult(
                handled=True,
                allowed=False,
                reason="task_result_schema_blocked",
                reply=_format_block_reply("task_result_schema_blocked", str(result_schema.get("failure_class") or result_schema.get("reason") or "schema")),
                task_type=task_type,
                task_request=task_request,
                task_result=task_result,
                worker_result=worker_result,
                request_schema=request_schema,
                result_schema=result_schema,
                agent_audit=_agent_audit,
            ),
            msg=msg,
            command_text=raw_text,
        )

    forbidden = _bus_payload_has_forbidden_material(task_request, task_result)
    if forbidden:
        return _with_isaac_p0_audit(
            IsaacP0HandleResult(
                handled=True,
                allowed=False,
                reason="redaction_guard_blocked",
                reply=_format_block_reply("redaction_guard_blocked", forbidden),
                task_type=task_type,
                task_request=task_request,
                task_result=task_result,
                worker_result=worker_result,
                request_schema=request_schema,
                result_schema=result_schema,
                agent_audit=_agent_audit,
            ),
            msg=msg,
            command_text=raw_text,
        )

    return _with_isaac_p0_audit(
        IsaacP0HandleResult(
            handled=True,
            allowed=True,
            reason="pass",
            reply=_format_success_reply(task_type, request_schema, result_schema, worker_result, high_risk_markers=high_risk_markers),
            task_type=task_type,
            task_request=task_request,
            task_result=task_result,
            worker_result=worker_result,
            request_schema=request_schema,
            result_schema=result_schema,
            agent_audit=_agent_audit,
        ),
        msg=msg,
        command_text=raw_text,
    )

__all__ = [
    "IsaacP0HandleResult",
    "P0_SCHEMA_VERSION",
    "ISAAC_SLASH_TOKENS",
    "handle_isaac_agent_bus_p0_message",
    "_handle_p1_intent_preview",
    "_resolve_available_router",
    "_build_isaac_agent_for_bus",
    "_isaac_agent_decide_for_p0",
    "_extract_agent_ping_intent",
    "_handle_agent_ping",
]


def _import_audit_report_builder():
    try:
        from .isaac_audit_report import build_audit_report  # type: ignore
        return build_audit_report
    except Exception:
        import importlib.util as _il, sys as _sys
        from pathlib import Path as _P
        _mod_path = _P(__file__).resolve().parent / "isaac_audit_report.py"
        _name = "isaac_audit_report_under_test"
        if _name in _sys.modules:
            return getattr(_sys.modules[_name], "build_audit_report")
        _spec = _il.spec_from_file_location(_name, _mod_path)
        _mod = _il.module_from_spec(_spec)
        _sys.modules[_name] = _mod
        _spec.loader.exec_module(_mod)
        return _mod.build_audit_report


def _import_audit_status_builder():
    try:
        from .isaac_audit_report import build_status_report  # type: ignore
        return build_status_report
    except Exception:
        import importlib.util as _il, sys as _sys
        from pathlib import Path as _P
        _mod_path = _P(__file__).resolve().parent / "isaac_audit_report.py"
        _name = "isaac_audit_report_under_test"
        if _name in _sys.modules:
            return getattr(_sys.modules[_name], "build_status_report")
        _spec = _il.spec_from_file_location(_name, _mod_path)
        _mod = _il.module_from_spec(_spec)
        _sys.modules[_name] = _mod
        _spec.loader.exec_module(_mod)
        return _mod.build_status_report


def _import_audit_report_formatter():
    try:
        from .isaac_audit_report import format_audit_report  # type: ignore
        return format_audit_report
    except Exception:
        import importlib.util as _il, sys as _sys
        from pathlib import Path as _P
        _mod_path = _P(__file__).resolve().parent / "isaac_audit_report.py"
        _name = "isaac_audit_report_under_test"
        if _name in _sys.modules:
            return getattr(_sys.modules[_name], "format_audit_report")
        _spec = _il.spec_from_file_location(_name, _mod_path)
        _mod = _il.module_from_spec(_spec)
        _sys.modules[_name] = _mod
        _spec.loader.exec_module(_mod)
        return _mod.format_audit_report


def _import_audit_status_formatter():
    try:
        from .isaac_audit_report import format_status_report  # type: ignore
        return format_status_report
    except Exception:
        import importlib.util as _il, sys as _sys
        from pathlib import Path as _P
        _mod_path = _P(__file__).resolve().parent / "isaac_audit_report.py"
        _name = "isaac_audit_report_under_test"
        if _name in _sys.modules:
            return getattr(_sys.modules[_name], "format_status_report")
        _spec = _il.spec_from_file_location(_name, _mod_path)
        _mod = _il.module_from_spec(_spec)
        _sys.modules[_name] = _mod
        _spec.loader.exec_module(_mod)
        return _mod.format_status_report


def _import_agentbus_factory_report_builder():
    try:
        from .isaac_agentbus_factory_report import build_agentbus_factory_report  # type: ignore
        return build_agentbus_factory_report
    except Exception:
        import importlib.util as _il, sys as _sys
        from pathlib import Path as _P
        _mod_path = _P(__file__).resolve().parent / "isaac_agentbus_factory_report.py"
        _name = "isaac_agentbus_factory_report_under_test"
        if _name in _sys.modules:
            return getattr(_sys.modules[_name], "build_agentbus_factory_report")
        _spec = _il.spec_from_file_location(_name, _mod_path)
        _mod = _il.module_from_spec(_spec)
        _sys.modules[_name] = _mod
        _spec.loader.exec_module(_mod)
        return _mod.build_agentbus_factory_report


def _import_agentbus_factory_report_formatter():
    try:
        from .isaac_agentbus_factory_report import format_agentbus_factory_report  # type: ignore
        return format_agentbus_factory_report
    except Exception:
        import importlib.util as _il, sys as _sys
        from pathlib import Path as _P
        _mod_path = _P(__file__).resolve().parent / "isaac_agentbus_factory_report.py"
        _name = "isaac_agentbus_factory_report_under_test"
        if _name in _sys.modules:
            return getattr(_sys.modules[_name], "format_agentbus_factory_report")
        _spec = _il.spec_from_file_location(_name, _mod_path)
        _mod = _il.module_from_spec(_spec)
        _sys.modules[_name] = _mod
        _spec.loader.exec_module(_mod)
        return _mod.format_agentbus_factory_report


def _import_workspace_report_builder():
    try:
        from .isaac_workspace_report import build_workspace_report  # type: ignore
        return build_workspace_report
    except Exception:
        import importlib.util as _il, sys as _sys
        from pathlib import Path as _P
        _mod_path = _P(__file__).resolve().parent / "isaac_workspace_report.py"
        _name = "isaac_workspace_report_under_test"
        if _name in _sys.modules:
            return getattr(_sys.modules[_name], "build_workspace_report")
        _spec = _il.spec_from_file_location(_name, _mod_path)
        _mod = _il.module_from_spec(_spec)
        _sys.modules[_name] = _mod
        _spec.loader.exec_module(_mod)
        return _mod.build_workspace_report


def _import_workspace_report_formatter():
    try:
        from .isaac_workspace_report import format_workspace_report  # type: ignore
        return format_workspace_report
    except Exception:
        import importlib.util as _il, sys as _sys
        from pathlib import Path as _P
        _mod_path = _P(__file__).resolve().parent / "isaac_workspace_report.py"
        _name = "isaac_workspace_report_under_test"
        if _name in _sys.modules:
            return getattr(_sys.modules[_name], "format_workspace_report")
        _spec = _il.spec_from_file_location(_name, _mod_path)
        _mod = _il.module_from_spec(_spec)
        _sys.modules[_name] = _mod
        _spec.loader.exec_module(_mod)
        return _mod.format_workspace_report
