from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from .owner_rules import is_owner_uid


OwnerActionGateMode = Literal["dry_run", "pending", "blocked"]


@dataclass(frozen=True)
class OwnerActionGateResult:
    allowed: bool
    mode: OwnerActionGateMode
    reason: str
    requires_target_group: bool
    requires_target_user: bool
    safe_to_execute: bool
    execution_enabled: bool = False
    permission: str = "none"
    blocked_by_config: bool = False


TARGET_GROUP_REQUIRED_ACTIONS: set[str] = {
    "send_group_message",
}


TARGET_USER_OPTIONAL_ACTIONS: set[str] = {
    "send_group_message",
    "reply_current",
    "silence_topic",
}


ACTION_PERMISSION_MAP: dict[str, str] = {
    "send_group_message": "send_group_message",
    "reply_current": "reply_current",
    "cancel_reply": "internal_control",
    "silence_topic": "internal_control",
}


PERMISSION_CONFIG_MAP: dict[str, str] = {
    "send_group_message": "owner_action_allow_send_group_message",
    "reply_current": "owner_action_allow_reply_current",
    "internal_control": "owner_action_allow_internal_control",
}


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


def _is_owner_message(message: Any, config: Any) -> bool:
    if bool(getattr(message, "is_owner", False)):
        return True

    uid = str(getattr(message, "uid", "") or "")
    owner_uids = _config_get(config, "owner_uids", [])
    owner_uid = _config_get(config, "owner_uid")
    return is_owner_uid(uid, owner_uids, owner_uid)


def _make_result(
    *,
    allowed: bool,
    mode: OwnerActionGateMode,
    reason: str,
    requires_target_group: bool,
    requires_target_user: bool,
    safe_to_execute: bool,
    execution_enabled: bool = False,
    permission: str = "none",
    blocked_by_config: bool = False,
) -> OwnerActionGateResult:
    return OwnerActionGateResult(
        allowed=allowed,
        mode=mode,
        reason=reason,
        requires_target_group=requires_target_group,
        requires_target_user=requires_target_user,
        safe_to_execute=safe_to_execute,
        execution_enabled=execution_enabled,
        permission=permission,
        blocked_by_config=blocked_by_config,
    )


def _evaluate_execution_policy(permission: str, config: Any) -> tuple[bool, bool, bool]:
    execution_enabled = _config_get_bool(config, "owner_action_execution_enabled", False)
    permission_key = PERMISSION_CONFIG_MAP.get(permission)
    permission_enabled = _config_get_bool(config, permission_key, False) if permission_key else False
    safe_to_execute = execution_enabled and permission_enabled
    blocked_by_config = not safe_to_execute
    return execution_enabled, permission_enabled, blocked_by_config


def _config_blocked_result(
    *,
    base_reason: str,
    permission: str,
    requires_target_group: bool,
    requires_target_user: bool,
    config: Any,
) -> OwnerActionGateResult:
    execution_enabled, permission_enabled, blocked_by_config = _evaluate_execution_policy(permission, config)

    if not execution_enabled:
        reason = f"{base_reason}:execution_disabled"
    elif not permission_enabled:
        reason = f"{base_reason}:permission_denied:{permission}"
    else:
        reason = f"{base_reason}:dry_run_only"

    return _make_result(
        allowed=True,
        mode="dry_run",
        reason=reason,
        requires_target_group=requires_target_group,
        requires_target_user=requires_target_user,
        safe_to_execute=False,
        execution_enabled=execution_enabled,
        permission=permission,
        blocked_by_config=blocked_by_config,
    )


def evaluate_owner_action_gate(action: Any, message: Any, config: Any) -> OwnerActionGateResult:
    if action is None:
        return _make_result(
            allowed=False,
            mode="blocked",
            reason="no_action",
            requires_target_group=False,
            requires_target_user=False,
            safe_to_execute=False,
        )

    if message is None or not _is_owner_message(message, config):
        return _make_result(
            allowed=False,
            mode="blocked",
            reason="not_owner",
            requires_target_group=False,
            requires_target_user=False,
            safe_to_execute=False,
        )

    action_type = str(getattr(action, "action_type", "") or "").strip()
    requires_target_group = action_type in TARGET_GROUP_REQUIRED_ACTIONS
    requires_target_user = action_type in TARGET_USER_OPTIONAL_ACTIONS
    permission = ACTION_PERMISSION_MAP.get(action_type, "none")

    if action_type == "send_group_message":
        target_group_id = str(getattr(action, "target_group_id", "") or "").strip()
        if not target_group_id:
            return _make_result(
                allowed=False,
                mode="blocked",
                reason="missing_target_group",
                requires_target_group=True,
                requires_target_user=requires_target_user,
                safe_to_execute=False,
                permission=permission,
            )
        return _config_blocked_result(
            base_reason="send_group_message_pending",
            permission=permission,
            requires_target_group=True,
            requires_target_user=requires_target_user,
            config=config,
        )

    if action_type == "reply_current":
        return _config_blocked_result(
            base_reason="reply_current_pending",
            permission=permission,
            requires_target_group=requires_target_group,
            requires_target_user=requires_target_user,
            config=config,
        )

    if action_type == "cancel_reply":
        return _config_blocked_result(
            base_reason="cancel_reply_pending",
            permission=permission,
            requires_target_group=requires_target_group,
            requires_target_user=False,
            config=config,
        )

    if action_type == "silence_topic":
        return _config_blocked_result(
            base_reason="silence_topic_pending",
            permission=permission,
            requires_target_group=requires_target_group,
            requires_target_user=requires_target_user,
            config=config,
        )

    return _make_result(
        allowed=False,
        mode="blocked",
        reason="unknown_action",
        requires_target_group=requires_target_group,
        requires_target_user=requires_target_user,
        safe_to_execute=False,
        permission=permission,
    )
