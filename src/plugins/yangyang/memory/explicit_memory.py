from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal


ExplicitIntent = Literal["write", "query", "audit", "none", "confirm", "cancel"]
ExplicitConfidence = Literal["high", "medium", "low"]
ExplicitScope = Literal["private_owner", "group"]


@dataclass(slots=True)
class ExplicitMemoryIntent:
    """显式记忆意图识别结果。

    v1 只负责把“写入/查询/审计/确认/取消/普通聊天”分开，
    避免见到“记”字就写入。真正消息 handler 接入和多轮 pending
    状态放到后续小阶段。
    """

    intent: ExplicitIntent
    confidence: ExplicitConfidence = "low"
    payload: str = ""
    reason: str = ""
    needs_confirmation: bool = False
    scope: ExplicitScope = "private_owner"
    needs_context_resolution: bool = False
    context_markers: tuple[str, ...] = ()
    context_hint: str | None = None

    @property
    def should_write(self) -> bool:
        return self.intent == "write" and not self.needs_confirmation and bool(self.payload.strip())


_CONFIRM_WORDS = {"是", "好", "确认", "对", "可以", "嗯", "记", "行", "没错", "对的"}
_CANCEL_WORDS = {"不是", "不用", "取消", "算了", "别记", "不要记", "不记", "先别", "先不用"}

_QUESTION_HINTS = (
    "吗", "么", "？", "?", "什么", "啥", "哪个", "哪款", "哪种", "谁", "多少",
    "记得", "记不记得", "还记得", "之前说过", "昨天说了什么", "上次聊到哪",
)

_AUDIT_PATTERNS = (
    re.compile(r"你(?:现在|刚才|到底)?(?:在)?(?:记录|记)(?:了)?(?:啥|什么|哪些东西|哪些内容)"),
    re.compile(r"你(?:都|到底)?(?:记|记录)(?:了)?(?:啥|什么|哪些|哪些东西|哪些内容)"),
    re.compile(r"你刚才(?:写|存|记录|记)(?:了)?什么记忆"),
    re.compile(r"(?:看看|查看|列一下|列出)(?:你)?(?:记|记录)(?:了)?(?:啥|什么|哪些东西|哪些内容)"),
)

_QUERY_PATTERNS = (
    re.compile(r"你(?:还)?记得.+(?:吗|么|？|\?)?$"),
    re.compile(r"你记不记得.+"),
    re.compile(r"我之前说过什么"),
    re.compile(r"我们上次聊到哪(?:了)?"),
    re.compile(r"(?:昨天|上次|刚才).*(?:说了什么|聊了什么)"),
)

# 高置信写入：仅斜杠命令走规则直写；普通自然语言交给 LLM 判定和润色。
_HIGH_WRITE_PATTERNS = (
    re.compile(r"^/记一下[：:，,\s]+(.{2,300})$"),
    re.compile(r"^/记住[：:，,\s]+(.{2,300})$"),
    re.compile(r"^/记录[：:，,\s]+(.{2,300})$"),
    re.compile(r"^/存档[：:，,\s]+(.{2,300})$"),
)

# 中置信：有写入动词，但 payload 边界依赖上下文或没有清楚分隔。
_MEDIUM_WRITE_HINTS: tuple[str, ...] = ()

# A1 只做上下文型写入识别，不解析 payload。长 marker 放前面，便于调用方看到更具体的命中项。
_CONTEXTUAL_WRITE_MARKERS = (
    "上面那段",
    "我们的讨论",
    "讨论内容",
    "这个结论",
    "前面说的",
    "刚才说的",
    "刚刚",
    "刚才",
    "那个",
    "这个",
    "上面",
    "那段",
    "这段",
)

_CONTEXTUAL_WRITE_ACTION_HINTS = (
    "/记一下",
    "/记住",
    "/记录",
    "/存档",
)

# 普通自然语言写入不再由规则提取，交给 LLM 判定和润色。
_GENERIC_WRITE_ACTION_HINTS: tuple[str, ...] = ()

_LOW_VALUE_PAYLOADS = {"", "一下", "这个", "那个", "这件事", "刚才那个", "以后别忘了这个事"}


def _normalize_text(text: str) -> str:
    return str(text or "").strip()


def _strip_payload(payload: str) -> str:
    value = str(payload or "").strip()
    value = value.strip(" ：:，,。.!！;；")
    return value


def _find_context_markers(text: str) -> tuple[str, ...]:
    cleaned = _normalize_text(text)
    compact = re.sub(r"\s+", "", cleaned)
    if not cleaned:
        return ()
    return tuple(
        marker
        for marker in _CONTEXTUAL_WRITE_MARKERS
        if marker in cleaned or marker in compact
    )


def _has_any_action_hint(text: str, hints: tuple[str, ...]) -> bool:
    cleaned = _normalize_text(text)
    compact = re.sub(r"\s+", "", cleaned)
    return any(hint in cleaned or hint in compact for hint in hints)


def _has_contextual_write_action(text: str) -> bool:
    return _has_any_action_hint(text, _CONTEXTUAL_WRITE_ACTION_HINTS)


def _has_generic_write_action(text: str) -> bool:
    return _has_any_action_hint(text, _GENERIC_WRITE_ACTION_HINTS)


def _is_context_only_payload(payload: str) -> bool:
    stripped = _strip_payload(payload)
    markers = _find_context_markers(stripped)
    if not stripped or stripped in _LOW_VALUE_PAYLOADS:
        return True
    if not markers:
        return False
    filler = stripped
    for marker in markers:
        filler = filler.replace(marker, "")
    filler = re.sub(r"[把也请帮我我们的这那一段个件事内容结论说的上下前面刚才刚刚\s]+", "", filler)
    filler = filler.strip(" ：:，,。.!！;；")
    return not filler


def _is_question_like(text: str) -> bool:
    cleaned = _normalize_text(text)
    if not cleaned:
        return False
    if cleaned.endswith(("?", "？", "吗", "么")):
        return True
    return any(hint in cleaned for hint in _QUESTION_HINTS[:11]) and any(kw in cleaned for kw in ("记", "说", "喜欢", "记录"))


def _looks_like_audit(text: str) -> bool:
    return any(pattern.search(text) for pattern in _AUDIT_PATTERNS)


def _looks_like_query(text: str) -> bool:
    return any(pattern.search(text) for pattern in _QUERY_PATTERNS)


def detect_explicit_memory_intent(text: str, *, scope: ExplicitScope = "private_owner") -> ExplicitMemoryIntent:
    """识别显式记忆相关意图。

    优先级：确认/取消 -> 审计 -> 查询 -> 高置信写入 -> 中置信确认 -> none。
    这样可以保证“你记得...吗”“你在记录啥”不会因为含有“记”而误写。
    """

    cleaned = _normalize_text(text)
    if not cleaned:
        return ExplicitMemoryIntent("none", reason="empty", scope=scope)

    compact = re.sub(r"\s+", "", cleaned)

    if compact in _CANCEL_WORDS:
        return ExplicitMemoryIntent("cancel", confidence="high", reason="cancel_word", scope=scope)
    if compact in _CONFIRM_WORDS:
        return ExplicitMemoryIntent("confirm", confidence="high", reason="confirm_word", scope=scope)

    if _looks_like_audit(cleaned):
        return ExplicitMemoryIntent("audit", confidence="high", reason="memory_audit_question", scope=scope)

    if _looks_like_query(cleaned):
        return ExplicitMemoryIntent("query", confidence="high", reason="memory_query_question", scope=scope)

    # 疑问句默认只读/查询，不进入写入。
    if _is_question_like(cleaned) and "记" in cleaned:
        return ExplicitMemoryIntent("query", confidence="medium", reason="question_like_memory_read", scope=scope)

    for pattern in _HIGH_WRITE_PATTERNS:
        m = pattern.search(cleaned)
        if not m:
            continue
        payload = _strip_payload(m.group(1))
        payload_markers = _find_context_markers(payload)
        if not payload or payload in _LOW_VALUE_PAYLOADS or _is_context_only_payload(payload):
            return ExplicitMemoryIntent(
                "write",
                confidence="medium",
                payload=payload,
                reason="contextual_write_payload_unclear" if payload_markers else "write_command_payload_unclear",
                needs_confirmation=True,
                scope=scope,
                needs_context_resolution=bool(payload_markers),
                context_markers=payload_markers,
                context_hint=payload or cleaned if payload_markers else None,
            )
        if _is_question_like(payload):
            return ExplicitMemoryIntent("query", confidence="medium", reason="payload_is_question_like", scope=scope)
        return ExplicitMemoryIntent(
            "write",
            confidence="high",
            payload=payload,
            reason="explicit_write_command_with_payload",
            needs_confirmation=False,
            scope=scope,
        )

    context_markers = _find_context_markers(cleaned)
    if context_markers and _has_contextual_write_action(cleaned):
        return ExplicitMemoryIntent(
            "write",
            confidence="medium",
            payload="",
            reason="contextual_write_needs_resolution",
            needs_confirmation=True,
            scope=scope,
            needs_context_resolution=True,
            context_markers=context_markers,
            context_hint=cleaned,
        )

    if cleaned in _MEDIUM_WRITE_HINTS:
        return ExplicitMemoryIntent(
            "write",
            confidence="medium",
            payload="",
            reason="write_hint_context_dependent",
            needs_confirmation=True,
            scope=scope,
        )

    # 泛化中置信：有“记/记录/存档”写入动词，但没有明确 payload 分隔。
    if _has_generic_write_action(cleaned):
        if _is_question_like(cleaned):
            return ExplicitMemoryIntent("query", confidence="medium", reason="question_like_memory_read", scope=scope)
        return ExplicitMemoryIntent(
            "write",
            confidence="medium",
            payload="",
            reason="write_command_without_clear_payload",
            needs_confirmation=True,
            scope=scope,
        )

    return ExplicitMemoryIntent("none", confidence="low", reason="no_explicit_memory_intent", scope=scope)
