from __future__ import annotations

import inspect
from typing import Any

from ..output.sender_adapter import NoneBotCurrentSessionSenderAdapter, NullSenderAdapter, SendResult

OwnerActionDeliveryResult = SendResult


async def deliver_owner_action_reply_draft(
    draft: Any,
    action: Any,
    gate: Any,
    plan: Any,
    message: Any,
    config: Any,
    sender: Any = None,
) -> SendResult:
    del gate

    destination_type = _normalize_text(getattr(plan, "destination_type", None)) or _normalize_text(
        getattr(draft, "destination_type", None)
    ) or "none"
    destination_id = _normalize_optional_str(getattr(plan, "destination_id", None))
    if destination_id is None:
        destination_id = _normalize_optional_str(getattr(draft, "destination_id", None))

    if draft is None:
        return _result(False, False, "blocked", destination_type, destination_id, 0, "no_draft", False)

    content = _extract_content(draft)
    content_length = len(content)

    draft_status = _normalize_text(getattr(draft, "status", None)) or "noop"
    if draft_status != "drafted":
        mode = "blocked" if draft_status == "blocked" else "disabled"
        return _result(False, False, mode, destination_type, destination_id, content_length, f"draft_status_{draft_status}", False)

    action_type = _normalize_text(getattr(action, "action_type", None)) or _normalize_text(
        getattr(draft, "action_type", None)
    ) or "unknown"

    if action_type == "send_group_message" or destination_type == "group":
        return _result(
            False,
            False,
            "blocked",
            destination_type or "group",
            destination_id,
            content_length,
            "cross_session_blocked:send_group_locked",
            False,
        )

    if destination_type == "internal_control" or action_type in {"cancel_reply", "silence_topic"}:
        return _result(
            False,
            False,
            "blocked",
            destination_type or "internal_control",
            destination_id,
            content_length,
            "internal_control_not_implemented",
            False,
        )

    if action_type != "reply_current":
        return _result(
            False,
            False,
            "blocked",
            destination_type,
            destination_id,
            content_length,
            f"unsupported_action:{action_type}",
            False,
        )

    if destination_type != "current_session":
        return _result(
            False,
            False,
            "blocked",
            destination_type,
            destination_id,
            content_length,
            "invalid_destination:reply_current_requires_current_session",
            False,
        )

    if not _config_get_bool(config, "owner_action_execution_enabled", False):
        return _result(False, False, "disabled", destination_type, destination_id, content_length, "execution_disabled", False)

    if not _config_get_bool(config, "owner_action_allow_reply_current", False):
        return _result(False, False, "blocked", destination_type, destination_id, content_length, "reply_current_not_allowed", False)

    if not _config_get_bool(config, "owner_action_current_session_delivery_enabled", False):
        return _result(False, False, "disabled", destination_type, destination_id, content_length, "current_session_delivery_disabled", False)

    if _config_get_bool(config, "dry_run", False):
        return _result(False, False, "dry_run", destination_type, destination_id, content_length, "dry_run_no_delivery", False)

    sender_adapter = _resolve_sender_adapter(sender)
    if sender_adapter is None:
        sender_adapter = NullSenderAdapter(mode="blocked", reason="no_sender", real_send=False)

    if not content:
        return _result(False, False, "blocked", destination_type, destination_id, content_length, "empty_draft_content", False)

    try:
        send_result = await _invoke_sender_adapter(sender_adapter, message, content)
    except Exception as exc:
        return _result(True, False, "blocked", destination_type, destination_id, content_length, f"sender_error:{exc.__class__.__name__}", False)

    return _coerce_send_result(send_result, destination_type, destination_id, content_length)


def format_owner_action_delivery_summary(result: Any) -> str:
    if result is None:
        return ""
    reason = _normalize_text(getattr(result, "reason", None)).replace("\n", " ") or "-"
    return (
        "[dry_run][owner_action_delivery] "
        f"mode={_normalize_text(getattr(result, 'mode', None)) or 'unknown'} "
        f"attempted={str(bool(getattr(result, 'attempted', False))).lower()} "
        f"delivered={str(bool(getattr(result, 'delivered', False))).lower()} "
        f"real_send={str(bool(getattr(result, 'real_send', False))).lower()} "
        f"reason={reason}"
    )


async def _invoke_sender_adapter(sender_adapter: Any, message: Any, content: str) -> Any:
    method = getattr(sender_adapter, "send_current_session", None)
    if callable(method):
        result = method(message, content)
        if inspect.isawaitable(result):
            return await result
        return result
    raise RuntimeError("unsupported_sender")


def _resolve_sender_adapter(sender: Any) -> Any:
    if sender is None:
        return None

    if isinstance(sender, NoneBotCurrentSessionSenderAdapter):
        return sender

    method = getattr(sender, "send_current_session", None)
    if callable(method):
        return sender

    if callable(sender):
        return _LegacyCallableSenderAdapter(sender)

    for method_name in ("deliver_owner_action_reply", "deliver", "send_current_session_reply"):
        method = getattr(sender, method_name, None)
        if callable(method):
            return _LegacyObjectSenderAdapter(sender, method_name)

    return None


class _LegacyCallableSenderAdapter:
    def __init__(self, sender_callable: Any):
        self.sender_callable = sender_callable
        self.is_fake_sender = bool(getattr(sender_callable, "is_fake_sender", False))
        self.is_test_sender = bool(getattr(sender_callable, "is_test_sender", False))

    async def send_current_session(self, message: Any, content: str) -> Any:
        destination_type = "current_session"
        destination_id = _resolve_current_session_id(message)
        result = self.sender_callable(content, destination_type, destination_id, None, None, None)
        if inspect.isawaitable(result):
            return await result
        return result


class _LegacyObjectSenderAdapter:
    def __init__(self, sender: Any, method_name: str):
        self.sender = sender
        self.method_name = method_name
        self.is_fake_sender = bool(getattr(sender, "is_fake_sender", False))
        self.is_test_sender = bool(getattr(sender, "is_test_sender", False))

    async def send_current_session(self, message: Any, content: str) -> Any:
        method = getattr(self.sender, self.method_name)
        destination_type = "current_session"
        destination_id = _resolve_current_session_id(message)
        result = method(
            content=content,
            destination_type=destination_type,
            destination_id=destination_id,
            action=None,
            draft=None,
            plan=None,
        )
        if inspect.isawaitable(result):
            return await result
        return result


def _coerce_send_result(
    send_result: Any,
    destination_type: str,
    destination_id: str | None,
    content_length: int,
) -> SendResult:
    if _looks_like_send_result(send_result):
        return SendResult(
            attempted=bool(getattr(send_result, "attempted", False)),
            delivered=bool(getattr(send_result, "delivered", False)),
            mode=_normalize_text(getattr(send_result, "mode", None)) or "unknown",
            destination_type=_normalize_text(getattr(send_result, "destination_type", None)) or destination_type or "current_session",
            destination_id=_normalize_optional_str(getattr(send_result, "destination_id", None)) or destination_id,
            content_length=int(getattr(send_result, "content_length", content_length) or 0),
            reason=_normalize_text(getattr(send_result, "reason", None)) or "sender_result",
            real_send=bool(getattr(send_result, "real_send", False)),
        )

    if isinstance(send_result, bool):
        delivered = bool(send_result)
        return _result(
            attempted=True,
            delivered=delivered,
            mode="fake_delivered" if delivered else "blocked",
            destination_type=destination_type,
            destination_id=destination_id,
            content_length=content_length,
            reason="fake_sender_delivered" if delivered else "sender_returned_false",
            real_send=delivered,
        )

    delivered = bool(send_result)
    return _result(
        attempted=True,
        delivered=delivered,
        mode="delivered" if delivered else "blocked",
        destination_type=destination_type,
        destination_id=destination_id,
        content_length=content_length,
        reason="sender_result_object" if delivered else "sender_result_empty",
        real_send=delivered,
    )


def _looks_like_send_result(value: Any) -> bool:
    return all(hasattr(value, key) for key in (
        "attempted",
        "delivered",
        "mode",
        "destination_type",
        "destination_id",
        "content_length",
        "reason",
        "real_send",
    ))


def _extract_content(draft: Any) -> str:
    preview = _normalize_text(getattr(draft, "content_preview", None))
    return preview


def _config_get(config: Any, path: str, default: Any = None) -> Any:
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            return getter(path, default)
        except TypeError:
            pass

    if isinstance(config, dict):
        current: Any = config
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    return default


def _config_get_bool(config: Any, path: str, default: bool = False) -> bool:
    getter = getattr(config, "get_bool", None)
    if callable(getter):
        try:
            return bool(getter(path, default))
        except TypeError:
            pass

    value = _config_get(config, path, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


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


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_optional_str(value: Any) -> str | None:
    normalized = _normalize_text(value)
    return normalized or None


def _result(
    attempted: bool,
    delivered: bool,
    mode: str,
    destination_type: str,
    destination_id: str | None,
    content_length: int,
    reason: str,
    real_send: bool,
) -> SendResult:
    return SendResult(
        attempted=attempted,
        delivered=delivered,
        mode=mode,
        destination_type=destination_type or "none",
        destination_id=destination_id,
        content_length=int(content_length or 0),
        reason=reason,
        real_send=real_send,
    )
