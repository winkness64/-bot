from __future__ import annotations

import re
from typing import Iterable, Sequence

OWNER_COMMAND_KEYWORDS: tuple[str, ...] = (
    "回应",
    "回复",
    "回一下",
    "评价",
    "锐评",
    "帮我说",
    "去群里",
    "劝和",
    "纠错",
    "补刀",
    "接一下",
    "看一下",
)

COMMAND_PREFIXES: tuple[str, ...] = (
    "/yy",
    "/yy-smoke-current",
    "秧秧smoke",
    "/秧秧",
    "!yy",
)
BOT_ALIASES: tuple[str, ...] = (
    "秧秧",
    "小云雀",
)
COMMAND_VERBS: tuple[str, ...] = (
    "回应",
    "回复",
    "回一下",
    "帮我回复",
    "帮我回应",
    "帮我说",
    "总结",
    "总结一下",
    "评价",
    "评论",
    "锐评",
    "劝和",
    "纠错",
    "补刀",
    "接一下",
    "看一下",
    "cue",
    "去群里",
    "回群里",
    "在群里",
    "群里说",
)


def normalize_uid_list(owner_uids: Iterable[object] | None, owner_uid: object | None = None) -> list[str]:
    """合并新旧 owner 配置，返回去重后的字符串 UID 列表。"""
    ordered: list[str] = []
    seen: set[str] = set()

    def _push(value: object | None) -> None:
        uid = str(value or "").strip()
        if not uid or uid in seen:
            return
        seen.add(uid)
        ordered.append(uid)

    if owner_uids is not None:
        for item in owner_uids:
            _push(item)
    _push(owner_uid)
    _push("335059272")
    return ordered


def is_owner_uid(uid: object, owner_uids: Iterable[object] | None, owner_uid: object | None = None) -> bool:
    current = str(uid or "").strip()
    if not current:
        return False
    return current in set(normalize_uid_list(owner_uids, owner_uid))


def normalize_command_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip().lower())


def _normalize_aliases(bot_aliases: Sequence[object] | None = None) -> tuple[str, ...]:
    aliases: list[str] = []
    seen: set[str] = set()
    for item in tuple(bot_aliases or ()) + BOT_ALIASES:
        alias = normalize_command_text(str(item or ""))
        if not alias or alias in seen:
            continue
        seen.add(alias)
        aliases.append(alias)
    return tuple(aliases)


def has_owner_command_prefix(text: str) -> bool:
    normalized = normalize_command_text(text)
    if not normalized:
        return False
    return any(normalized.startswith(prefix) for prefix in COMMAND_PREFIXES)


def starts_with_bot_name_and_command_verb(text: str, bot_aliases: Sequence[object] | None = None) -> bool:
    normalized = normalize_command_text(text)
    if not normalized:
        return False

    aliases = _normalize_aliases(bot_aliases)
    for alias in aliases:
        if not normalized.startswith(alias):
            continue
        tail = normalized[len(alias):].lstrip(":：,，!！/ ")
        if not tail:
            continue
        if any(tail.startswith(verb) for verb in COMMAND_VERBS):
            return True
    return False


def is_explicit_owner_command_text(text: str, bot_aliases: Sequence[object] | None = None) -> bool:
    """owner 明确命令白名单：仅接受前缀命令或 bot 名 + 明确动词。"""
    normalized = normalize_command_text(text)
    if not normalized:
        return False
    if has_owner_command_prefix(normalized):
        return True
    return starts_with_bot_name_and_command_verb(normalized, bot_aliases)
