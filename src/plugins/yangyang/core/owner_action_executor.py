from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OwnerActionExecutionPlan:
    action_type: str
    destination_type: str
    destination_id: str | None
    style: str
    status: str
    real_send: bool
    reason: str


def build_owner_action_execution_plan(action: Any, gate_result: Any, message: Any, config: Any) -> OwnerActionExecutionPlan:
    """只生成执行计划，不做真实执行。real_send 当前必须恒为 False。"""
    action_type = str(getattr(action, "action_type", "") or "").strip()
    style = str(getattr(action, "style", "normal") or "normal").strip() or "normal"

    if action is None:
        return OwnerActionExecutionPlan(
            action_type="none",
            destination_type="none",
            destination_id=None,
            style="normal",
            status="noop",
            real_send=False,
            reason="no_action",
        )

    gate_allowed = bool(getattr(gate_result, "allowed", False)) if gate_result is not None else False
    gate_reason = str(getattr(gate_result, "reason", "") or "").strip()
    gate_safe = bool(getattr(gate_result, "safe_to_execute", False)) if gate_result is not None else False

    if gate_result is not None and not gate_allowed:
        return OwnerActionExecutionPlan(
            action_type=action_type or "unknown",
            destination_type="none",
            destination_id=None,
            style=style,
            status="blocked",
            real_send=False,
            reason=gate_reason or "gate_blocked",
        )

    plan_reason = gate_reason or "dry_run_only"

    if action_type == "reply_current":
        destination_id = _resolve_current_session_id(message)
        return OwnerActionExecutionPlan(
            action_type=action_type,
            destination_type="current_session",
            destination_id=destination_id,
            style=style,
            status="planned" if not gate_safe else "planned",
            real_send=False,
            reason=plan_reason,
        )

    if action_type == "send_group_message":
        destination_id = _normalize_optional_str(getattr(action, "target_group_id", None))
        if not destination_id:
            return OwnerActionExecutionPlan(
                action_type=action_type,
                destination_type="none",
                destination_id=None,
                style=style,
                status="blocked",
                real_send=False,
                reason=gate_reason or "missing_target_group",
            )
        return OwnerActionExecutionPlan(
            action_type=action_type,
            destination_type="group",
            destination_id=destination_id,
            style=style,
            status="planned" if not gate_safe else "planned",
            real_send=False,
            reason=plan_reason,
        )

    if action_type in {"cancel_reply", "silence_topic"}:
        return OwnerActionExecutionPlan(
            action_type=action_type,
            destination_type="internal_control",
            destination_id=None,
            style=style,
            status="planned" if not gate_safe else "planned",
            real_send=False,
            reason=plan_reason,
        )

    return OwnerActionExecutionPlan(
        action_type=action_type or "unknown",
        destination_type="none",
        destination_id=None,
        style=style,
        status="noop",
        real_send=False,
        reason=gate_reason or "unknown_action",
    )


def _normalize_optional_str(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _resolve_current_session_id(message: Any) -> str | None:
    if message is None:
        return None
    channel = str(getattr(message, "channel", "") or "").strip()
    if channel == "group":
        group_id = _normalize_optional_str(getattr(message, "group_id", None))
        if group_id:
            return f"group:{group_id}"
    uid = _normalize_optional_str(getattr(message, "uid", None))
    if uid:
        if channel == "private":
            return f"private:{uid}"
        return uid
    return None
