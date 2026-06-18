from __future__ import annotations

from dataclasses import dataclass
from typing import Any


DEFAULT_PREVIEW_LIMIT = 120
INTERNAL_CONTROL_ACTIONS = {"cancel_reply", "silence_topic"}


@dataclass(frozen=True)
class OwnerActionReplyDraft:
    destination_type: str
    destination_id: str | None
    action_type: str
    style: str
    content_preview: str
    content_length: int
    status: str
    real_send: bool
    reason: str


def build_owner_action_reply_draft(
    action: Any,
    execution_plan: Any,
    model_reply: Any,
    message: Any,
    config: Any,
) -> OwnerActionReplyDraft:
    """构造 OwnerAction 待发送草稿。当前只做草稿层，real_send 必须恒为 False。"""
    del message, config

    if action is None:
        return OwnerActionReplyDraft(
            destination_type="none",
            destination_id=None,
            action_type="none",
            style="normal",
            content_preview="",
            content_length=0,
            status="noop",
            real_send=False,
            reason="no_action",
        )

    action_type = _normalize_text(getattr(action, "action_type", None)) or "unknown"
    style = _normalize_text(getattr(action, "style", None)) or "normal"

    if execution_plan is None:
        return OwnerActionReplyDraft(
            destination_type="none",
            destination_id=None,
            action_type=action_type,
            style=style,
            content_preview="",
            content_length=0,
            status="noop",
            real_send=False,
            reason="no_execution_plan",
        )

    destination_type = _normalize_text(getattr(execution_plan, "destination_type", None)) or "none"
    destination_id = _normalize_optional_str(getattr(execution_plan, "destination_id", None))
    plan_status = _normalize_text(getattr(execution_plan, "status", None)) or "noop"
    plan_reason = _normalize_text(getattr(execution_plan, "reason", None)) or "unknown"

    if plan_status != "planned":
        status = "blocked" if plan_status == "blocked" else "noop"
        return OwnerActionReplyDraft(
            destination_type=destination_type,
            destination_id=destination_id,
            action_type=action_type,
            style=style,
            content_preview="",
            content_length=0,
            status=status,
            real_send=False,
            reason=plan_reason,
        )

    if action_type in INTERNAL_CONTROL_ACTIONS:
        preview = _build_internal_control_preview(action_type, style, plan_reason)
        return OwnerActionReplyDraft(
            destination_type=destination_type,
            destination_id=destination_id,
            action_type=action_type,
            style=style,
            content_preview=_truncate_preview(preview),
            content_length=len(preview),
            status="drafted",
            real_send=False,
            reason=plan_reason,
        )

    reply_text = _normalize_model_reply(model_reply)
    if not reply_text:
        return OwnerActionReplyDraft(
            destination_type=destination_type,
            destination_id=destination_id,
            action_type=action_type,
            style=style,
            content_preview="",
            content_length=0,
            status="blocked",
            real_send=False,
            reason="empty_reply",
        )

    return OwnerActionReplyDraft(
        destination_type=destination_type,
        destination_id=destination_id,
        action_type=action_type,
        style=style,
        content_preview=_truncate_preview(reply_text),
        content_length=len(reply_text),
        status="drafted",
        real_send=False,
        reason=plan_reason,
    )


def format_owner_action_reply_draft_summary(draft: Any) -> str:
    if draft is None:
        return ""

    destination = _normalize_text(getattr(draft, "destination_type", None)) or "none"
    destination_id = _normalize_optional_str(getattr(draft, "destination_id", None))
    if destination_id:
        destination = f"{destination}:{destination_id}"

    status = _normalize_text(getattr(draft, "status", None)) or "noop"
    length = int(getattr(draft, "content_length", 0) or 0)
    preview = _sanitize_inline_text(getattr(draft, "content_preview", ""), DEFAULT_PREVIEW_LIMIT)
    preview = preview or "-"
    return (
        "[dry_run][owner_action_reply_draft] "
        f"destination={destination} "
        f"status={status} "
        f"length={length} "
        f"real_send={str(bool(getattr(draft, 'real_send', False))).lower()} "
        f"preview={preview}"
    )


def _build_internal_control_preview(action_type: str, style: str, reason: str) -> str:
    if action_type == "cancel_reply":
        return f"[control draft] cancel_reply style={style} reason={reason}"
    if action_type == "silence_topic":
        return f"[control draft] silence_topic style={style} reason={reason}"
    return f"[control draft] {action_type} style={style} reason={reason}"


def _normalize_model_reply(model_reply: Any) -> str:
    return _sanitize_inline_text(model_reply, limit=100000)


def _truncate_preview(text: str, limit: int = DEFAULT_PREVIEW_LIMIT) -> str:
    sanitized = _sanitize_inline_text(text, limit=100000)
    if len(sanitized) <= limit:
        return sanitized
    return sanitized[:limit] + "…"


def _sanitize_inline_text(text: Any, limit: int) -> str:
    value = str(text or "").replace("\r", " ").replace("\n", " ")
    value = " ".join(value.split()).strip()
    if not value:
        return ""
    if len(value) <= limit:
        return value
    return value[:limit]


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_optional_str(value: Any) -> str | None:
    normalized = _normalize_text(value)
    return normalized or None
