from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from .owner_rules import (
    has_owner_command_prefix,
    is_owner_uid,
    normalize_command_text,
    starts_with_bot_name_and_command_verb,
)


@dataclass(frozen=True)
class OwnerAction:
    action_type: str
    style: str
    target_group_id: Optional[str]
    target_user_id: Optional[str]
    raw_text: str
    reason: str
    confidence: float


GROUP_SEND_KEYWORDS: tuple[str, ...] = (
    "去群里",
    "回群里",
    "在群里",
    "群里说",
)
REPLY_CURRENT_KEYWORDS: tuple[str, ...] = (
    "回应",
    "回复",
    "回一下",
    "接一下",
    "看一下",
    "cue",
)
NATURAL_CONTINUATION_KEYWORDS: tuple[str, ...] = (
    "继续",
    "继续搞",
    "继续吧",
    "继续做",
    "搞吧",
    "你搞",
    "你搞啊",
    "开搞",
    "干吧",
    "做吧",
)
CANCEL_KEYWORDS: tuple[str, ...] = (
    "别回",
    "别回了",
    "收手",
    "停一下",
)
SILENCE_KEYWORDS: tuple[str, ...] = (
    "静默",
)
MEDIATE_KEYWORDS: tuple[str, ...] = (
    "劝和",
)
ROAST_KEYWORDS: tuple[str, ...] = (
    "补刀",
    "锐评",
)
CORRECT_KEYWORDS: tuple[str, ...] = (
    "纠错",
    "更正",
)
COMMENT_KEYWORDS: tuple[str, ...] = (
    "评价",
    "评论",
)


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


def _normalize_text(text: str) -> str:
    return normalize_command_text(text)


def _contains_any(text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in text for keyword in keywords)


def _infer_style(text: str) -> tuple[str, str, float]:
    if _contains_any(text, MEDIATE_KEYWORDS):
        return "mediate", "style_mediate", 0.95
    if _contains_any(text, ROAST_KEYWORDS):
        return "roast", "style_roast", 0.95
    if _contains_any(text, CORRECT_KEYWORDS):
        return "correct", "style_correct", 0.95
    if _contains_any(text, COMMENT_KEYWORDS):
        return "comment", "style_comment", 0.8
    return "normal", "style_normal", 0.6


def _extract_explicit_numeric_id(text: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{5,})(?!\d)", text)
    if not match:
        return None
    return str(match.group(1))


def _resolve_member_aliases(config: Any) -> dict[str, str]:
    aliases = _config_get(config, "member_aliases", {})
    if not isinstance(aliases, dict):
        return {}

    resolved: dict[str, str] = {}
    for raw_alias, raw_uid in aliases.items():
        alias = str(raw_alias or "").strip()
        uid = str(raw_uid or "").strip()
        if alias and uid:
            resolved[_normalize_text(alias)] = uid
    return resolved


def _resolve_target_user_id(message: Any, config: Any, normalized_text: str) -> tuple[str | None, str]:
    explicit_user_id = _extract_explicit_numeric_id(normalized_text)
    if explicit_user_id:
        return explicit_user_id, "explicit_target_user"

    aliases = _resolve_member_aliases(config)
    for alias, uid in aliases.items():
        if alias and alias in normalized_text:
            return uid, f"member_alias:{alias}"

    bot_self_id = str(getattr(message, "bot_self_id", "") or getattr(message, "self_id", "") or "").strip()
    at_user_ids = getattr(message, "at_user_ids", None)
    if isinstance(at_user_ids, list):
        for item in at_user_ids:
            target_uid = str(item or "").strip()
            if not target_uid:
                continue
            if bot_self_id and target_uid == bot_self_id:
                continue
            return target_uid, "mentioned_target_user"

    reply_target_uid = str(getattr(message, "reply_to_user_id", "") or "").strip()
    if reply_target_uid:
        if not bot_self_id or reply_target_uid != bot_self_id:
            return reply_target_uid, "reply_target_user"

    return None, "no_target_user"


def _resolve_default_group_id(config: Any) -> str | None:
    for path in ("default_group_id", "primary_group_id"):
        value = _config_get(config, path)
        if value is None:
            continue
        normalized = str(value).strip()
        if normalized:
            return normalized
    return None


def _resolve_target_group_id(message: Any, config: Any, normalized_text: str) -> tuple[str | None, str]:
    explicit_group_id = _extract_explicit_numeric_id(normalized_text)
    if explicit_group_id:
        return explicit_group_id, "explicit_target_group"

    current_group_id = str(getattr(message, "group_id", "") or "").strip()
    if current_group_id:
        return current_group_id, "current_group"

    default_group_id = _resolve_default_group_id(config)
    if default_group_id:
        return default_group_id, "default_target_group"

    return None, "no_target_group"


def _has_explicit_owner_command_signal(message: Any, normalized_text: str) -> tuple[bool, str]:
    if bool(getattr(message, "is_at_bot", False)):
        return True, "at_bot"
    if has_owner_command_prefix(normalized_text):
        return True, "command_prefix"
    if starts_with_bot_name_and_command_verb(normalized_text):
        return True, "bot_name_verb"
    return False, "no_explicit_signal"


def _is_owner_private_followup_message(message: Any, normalized_text: str) -> bool:
    if not bool(getattr(message, "is_owner", False)):
        return False
    if str(getattr(message, "channel", "") or "").strip().lower() != "private":
        return False
    if len(normalized_text) > 24:
        return False
    return _contains_any(normalized_text, NATURAL_CONTINUATION_KEYWORDS)


def parse_owner_action(message: Any, config: Any) -> OwnerAction | None:
    """只解析 owner 指令，不做执行。"""
    if message is None:
        return None

    uid = str(getattr(message, "uid", "") or "")
    text = str(getattr(message, "text", "") or getattr(message, "raw_content", "") or "")
    raw_text = str(getattr(message, "raw_content", "") or text)
    normalized = _normalize_text(text)
    if not normalized:
        return None

    is_owner = bool(getattr(message, "is_owner", False))
    if not is_owner:
        owner_uids = _config_get(config, "owner_uids", [])
        owner_uid = _config_get(config, "owner_uid")
        is_owner = is_owner_uid(uid, owner_uids, owner_uid)
    if not is_owner:
        return None

    has_explicit_signal, explicit_reason = _has_explicit_owner_command_signal(message, normalized)
    natural_followup = _is_owner_private_followup_message(message, normalized)
    if not has_explicit_signal and not natural_followup:
        return None
    if natural_followup and not has_explicit_signal:
        explicit_reason = "owner_private_followup"

    style, style_reason, style_confidence = _infer_style(normalized)
    target_group_id = str(getattr(message, "group_id", "") or "") or None
    target_user_id, target_user_reason = _resolve_target_user_id(message, config, normalized)

    if _contains_any(normalized, SILENCE_KEYWORDS):
        return OwnerAction(
            action_type="silence_topic",
            style=style,
            target_group_id=target_group_id,
            target_user_id=target_user_id,
            raw_text=raw_text,
            reason=f"{explicit_reason}+matched_silence_keyword+{target_user_reason}",
            confidence=0.98,
        )

    if _contains_any(normalized, CANCEL_KEYWORDS):
        return OwnerAction(
            action_type="cancel_reply",
            style=style,
            target_group_id=target_group_id,
            target_user_id=target_user_id,
            raw_text=raw_text,
            reason=f"{explicit_reason}+matched_cancel_keyword+{target_user_reason}",
            confidence=0.98,
        )

    if _contains_any(normalized, GROUP_SEND_KEYWORDS):
        target_group_id, target_group_reason = _resolve_target_group_id(message, config, normalized)
        return OwnerAction(
            action_type="send_group_message",
            style=style,
            target_group_id=target_group_id,
            target_user_id=target_user_id,
            raw_text=raw_text,
            reason=f"{explicit_reason}+matched_group_send_keyword+{target_group_reason}+{target_user_reason}+{style_reason}",
            confidence=max(0.86, style_confidence),
        )

    if _contains_any(normalized, REPLY_CURRENT_KEYWORDS):
        if target_user_id is None and explicit_reason == "no_explicit_signal":
            return None
        return OwnerAction(
            action_type="reply_current",
            style=style,
            target_group_id=target_group_id,
            target_user_id=target_user_id,
            raw_text=raw_text,
            reason=f"{explicit_reason}+matched_reply_current_keyword+{target_user_reason}+{style_reason}",
            confidence=max(0.82, style_confidence),
        )

    if natural_followup:
        return OwnerAction(
            action_type="reply_current",
            style=style,
            target_group_id=target_group_id,
            target_user_id=target_user_id,
            raw_text=raw_text,
            reason=f"{explicit_reason}+matched_natural_followup+{target_user_reason}+{style_reason}",
            confidence=max(0.84, style_confidence),
        )

    if style != "normal":
        if target_user_id is None and explicit_reason == "no_explicit_signal":
            return None
        return OwnerAction(
            action_type="reply_current",
            style=style,
            target_group_id=target_group_id,
            target_user_id=target_user_id,
            raw_text=raw_text,
            reason=f"{explicit_reason}+matched_style_only_default_reply_current+{target_user_reason}+{style_reason}",
            confidence=max(0.78, style_confidence),
        )

    return None
