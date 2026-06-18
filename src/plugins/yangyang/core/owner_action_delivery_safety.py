from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..output.sender_adapter import SendResult

DEFAULT_PREVIEW_LIMIT = 120
DEFAULT_TTL_SECONDS = 300
_DEFAULT_AUDIT_PATH = "logs/owner_action_delivery_audit.jsonl"


@dataclass(frozen=True)
class OwnerActionDeliverySafetyResult:
    allowed: bool
    duplicate: bool
    key: str
    reason: str
    ttl_seconds: int
    real_send: bool = False


@dataclass(frozen=True)
class OwnerActionDeliveryAuditRecord:
    time: str
    action_type: str
    destination_type: str
    destination_id: str | None
    status: str
    mode: str
    allowed: bool
    duplicate: bool
    attempted: bool
    delivered: bool
    real_send: bool
    reason: str
    key: str
    content_preview: str


class _InMemoryDeliveryDedupStore:
    def __init__(self):
        self._lock = threading.RLock()
        self._entries: dict[str, float] = {}

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()

    reset = clear

    def check_and_register(self, key: str, ttl_seconds: int, register: bool) -> OwnerActionDeliverySafetyResult:
        now = _now_seconds()
        ttl = max(int(ttl_seconds or DEFAULT_TTL_SECONDS), 1)
        with self._lock:
            self._purge_expired_locked(now)
            expires_at = self._entries.get(key)
            if expires_at is not None and expires_at > now:
                return OwnerActionDeliverySafetyResult(
                    allowed=False,
                    duplicate=True,
                    key=key,
                    reason="duplicate_blocked",
                    ttl_seconds=ttl,
                    real_send=False,
                )

            if register:
                self._entries[key] = now + ttl

        return OwnerActionDeliverySafetyResult(
            allowed=True,
            duplicate=False,
            key=key,
            reason="allowed" if register else "dry_run_not_registered",
            ttl_seconds=ttl,
            real_send=False,
        )

    def _purge_expired_locked(self, now: float) -> None:
        expired = [key for key, expires_at in self._entries.items() if expires_at <= now]
        for key in expired:
            self._entries.pop(key, None)


_STORE = _InMemoryDeliveryDedupStore()


def check_owner_action_delivery_safety(
    draft: Any,
    action: Any,
    plan: Any,
    message: Any,
    config: Any,
    *,
    dry_run: bool = False,
) -> OwnerActionDeliverySafetyResult:
    if draft is None or action is None or plan is None:
        return OwnerActionDeliverySafetyResult(
            allowed=False,
            duplicate=False,
            key="",
            reason="missing_required_input",
            ttl_seconds=_get_ttl_seconds(config),
            real_send=False,
        )

    if not _config_get_bool(config, "owner_action_delivery_safety_enabled", True):
        return OwnerActionDeliverySafetyResult(
            allowed=True,
            duplicate=False,
            key="",
            reason="safety_disabled",
            ttl_seconds=_get_ttl_seconds(config),
            real_send=False,
        )

    key = build_owner_action_delivery_idempotency_key(draft, action, plan, message)
    if not key:
        return OwnerActionDeliverySafetyResult(
            allowed=False,
            duplicate=False,
            key="",
            reason="missing_idempotency_key",
            ttl_seconds=_get_ttl_seconds(config),
            real_send=False,
        )

    return _STORE.check_and_register(key, _get_ttl_seconds(config), register=not bool(dry_run))


def build_owner_action_delivery_idempotency_key(draft: Any, action: Any, plan: Any, message: Any) -> str:
    action_type = _normalize_text(getattr(action, "action_type", None)) or _normalize_text(getattr(draft, "action_type", None)) or "unknown"
    destination_type = _normalize_text(getattr(plan, "destination_type", None)) or _normalize_text(getattr(draft, "destination_type", None)) or "none"
    destination_id = _normalize_optional_str(getattr(plan, "destination_id", None))
    if destination_id is None:
        destination_id = _normalize_optional_str(getattr(draft, "destination_id", None))

    source_message_id = (
        _normalize_optional_str(getattr(message, "msg_id", None))
        or _normalize_optional_str(getattr(message, "message_id", None))
        or _normalize_optional_str(getattr(message, "reply_to_message_id", None))
    )
    session_id = _resolve_session_id(message)
    timestamp = _normalize_optional_str(getattr(message, "timestamp", None)) or _normalize_optional_str(getattr(message, "time", None)) or "-"
    content_hash = _build_content_hash(draft)
    if not content_hash:
        return ""

    raw = {
        "source_message_id": source_message_id or "-",
        "session_id": session_id or "-",
        "timestamp": timestamp,
        "action_type": action_type,
        "destination_type": destination_type,
        "destination_id": destination_id or "-",
        "content_hash": content_hash,
    }
    encoded = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
    return f"owner_action_delivery:{digest}"


def write_owner_action_delivery_audit(
    config: Any,
    *,
    draft: Any,
    action: Any,
    plan: Any,
    safety_result: OwnerActionDeliverySafetyResult | None,
    delivery_result: Any,
    message: Any,
) -> str:
    if not _config_get_bool(config, "owner_action_delivery_audit_enabled", True):
        return "audit_disabled"

    audit_path = _resolve_audit_path(config)
    try:
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        record = build_owner_action_delivery_audit_record(
            draft=draft,
            action=action,
            plan=plan,
            safety_result=safety_result,
            delivery_result=delivery_result,
            message=message,
        )
        with audit_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")
        return "audit_written"
    except Exception:
        return "audit_failed"


def build_owner_action_delivery_audit_record(
    *,
    draft: Any,
    action: Any,
    plan: Any,
    safety_result: OwnerActionDeliverySafetyResult | None,
    delivery_result: Any,
    message: Any,
) -> OwnerActionDeliveryAuditRecord:
    del message
    action_type = _normalize_text(getattr(action, "action_type", None)) or _normalize_text(getattr(draft, "action_type", None)) or "unknown"
    destination_type = _normalize_text(getattr(plan, "destination_type", None)) or _normalize_text(getattr(draft, "destination_type", None)) or "none"
    destination_id = _normalize_optional_str(getattr(plan, "destination_id", None))
    if destination_id is None:
        destination_id = _normalize_optional_str(getattr(draft, "destination_id", None))

    mode = _normalize_text(getattr(delivery_result, "mode", None)) or "not_attempted"
    status = mode
    reason = _normalize_text(getattr(delivery_result, "reason", None)) or _normalize_text(getattr(safety_result, "reason", None)) or "unknown"
    preview = _truncate_preview(getattr(draft, "content_preview", ""), DEFAULT_PREVIEW_LIMIT)
    return OwnerActionDeliveryAuditRecord(
        time=datetime.now(timezone.utc).isoformat(),
        action_type=action_type,
        destination_type=destination_type,
        destination_id=destination_id,
        status=status,
        mode=mode,
        allowed=bool(getattr(safety_result, "allowed", False)),
        duplicate=bool(getattr(safety_result, "duplicate", False)),
        attempted=bool(getattr(delivery_result, "attempted", False)),
        delivered=bool(getattr(delivery_result, "delivered", False)),
        real_send=bool(getattr(delivery_result, "real_send", False)),
        reason=reason,
        key=_normalize_text(getattr(safety_result, "key", None)),
        content_preview=preview,
    )


def build_duplicate_blocked_delivery_result(draft: Any, plan: Any) -> SendResult:
    destination_type = _normalize_text(getattr(plan, "destination_type", None)) or _normalize_text(getattr(draft, "destination_type", None)) or "none"
    destination_id = _normalize_optional_str(getattr(plan, "destination_id", None))
    if destination_id is None:
        destination_id = _normalize_optional_str(getattr(draft, "destination_id", None))
    content_length = int(getattr(draft, "content_length", 0) or len(str(getattr(draft, "content_preview", "") or "")))
    return SendResult(
        attempted=False,
        delivered=False,
        mode="blocked",
        destination_type=destination_type,
        destination_id=destination_id,
        content_length=content_length,
        reason="duplicate_blocked",
        real_send=False,
    )


def format_owner_action_delivery_safety_summary(result: Any) -> str:
    if result is None:
        return ""
    return (
        "[dry_run][owner_action_delivery_safety] "
        f"allowed={str(bool(getattr(result, 'allowed', False))).lower()} "
        f"duplicate={str(bool(getattr(result, 'duplicate', False))).lower()} "
        f"reason={_normalize_text(getattr(result, 'reason', None)) or '-'} "
        f"key={_normalize_text(getattr(result, 'key', None)) or '-'}"
    )


def reset_owner_action_delivery_safety_store() -> None:
    _STORE.reset()


def clear_owner_action_delivery_safety_store() -> None:
    _STORE.clear()


def _build_content_hash(draft: Any) -> str:
    preview = _normalize_text(getattr(draft, "content_preview", None))
    content_length = int(getattr(draft, "content_length", 0) or len(preview))
    if not preview and content_length <= 0:
        return ""
    raw = f"preview={preview}|length={content_length}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _resolve_session_id(message: Any) -> str | None:
    if message is None:
        return None
    channel = _normalize_text(getattr(message, "channel", None))
    if channel == "group":
        group_id = _normalize_optional_str(getattr(message, "group_id", None))
        if group_id:
            return f"group:{group_id}"
    uid = _normalize_optional_str(getattr(message, "uid", None))
    if channel == "private" and uid:
        return f"private:{uid}"
    return uid


def _resolve_audit_path(config: Any) -> Path:
    raw_path = _normalize_text(_config_get(config, "owner_action_delivery_audit_path", _DEFAULT_AUDIT_PATH)) or _DEFAULT_AUDIT_PATH
    path = Path(raw_path)
    if path.is_absolute():
        return path
    return Path.cwd() / path


def _get_ttl_seconds(config: Any) -> int:
    return max(int(_config_get(config, "owner_action_delivery_dedup_ttl_seconds", DEFAULT_TTL_SECONDS) or DEFAULT_TTL_SECONDS), 1)


def _config_get(config: Any, path: str, default: Any = None) -> Any:
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            return getter(path, default)
        except TypeError:
            return getter(path)

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


def _truncate_preview(text: Any, limit: int) -> str:
    preview = _normalize_text(str(text or "").replace("\n", " ").replace("\r", " "))
    if len(preview) <= limit:
        return preview
    return preview[:limit] + "…"


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_optional_str(value: Any) -> str | None:
    value = _normalize_text(value)
    return value or None


def _now_seconds() -> float:
    return time.monotonic()
