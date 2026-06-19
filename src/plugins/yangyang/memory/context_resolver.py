from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from .explicit_memory import ExplicitMemoryIntent


@dataclass(frozen=True)
class ContextResolution:
    """规则版 recent context 解析结果。

    A2 只负责把“上下文型显式写入”解析成候选 payload，供后续 pending
    confirmation 使用；不写长期记忆、不接 handler、不调用 LLM。
    """

    status: str  # resolved | insufficient_context | not_contextual
    payload: str | None = None
    confidence: str = "low"  # medium/low for v1 rules
    used_msg_ids: tuple[str, ...] = ()
    context_range: dict[str, Any] = field(default_factory=dict)
    reason: str = ""


_RESOLVER_NAME = "recent_context_resolver_v1_rules"

_CONCLUSION_KEYWORDS = (
    "当前结论",
    "结论",
    "所以",
    "因此",
    "下一步",
    "建议",
    "通过",
    "失败",
    "完成",
    "待",
    "验收",
    "灰度",
    "基线",
)

_DEICTIC_WORDS = (
    "这个",
    "那个",
    "刚才",
    "刚刚",
    "上面",
    "前面",
    "那段",
    "这段",
    "我们的讨论",
    "讨论内容",
    "这个结论",
    "记一下",
    "记下来",
    "记录一下",
    "记录下来",
    "存档",
    "存档一下",
    "把",
    "也",
    "帮我",
    "请",
)

_CONFIRMATION_PREFIXES = (
    "记好了",
    "好，已经记录",
    "好,已经记录",
    "已经记录",
    "记录好了",
    "存好了",
    "好，记下来了",
    "好,记下来了",
    "漂♂总，是要记录为",
)

_CONFIRMATION_WORDS = {
    "确认",
    "好",
    "是",
    "嗯",
    "对",
    "可以",
    "取消",
    "不用",
    "算了",
    "行",
    "没错",
    "对的",
    "不要",
    "不记",
}

_MEMORY_COMMAND_HINTS = (
    "记一下",
    "记下来",
    "记录一下",
    "记录下来",
    "存档",
    "存档一下",
)


@dataclass(frozen=True)
class _CleanRecord:
    record: Mapping[str, Any]
    text: str
    index: int


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", str(value or "").strip())


def _created_at(record: Mapping[str, Any]) -> float | None:
    raw = record.get("created_at")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _is_handler_confirmation(text: str) -> bool:
    cleaned = _clean_text(text).strip(" 。.!！")
    return any(cleaned.startswith(prefix) for prefix in _CONFIRMATION_PREFIXES)


def _is_short_confirmation_or_control(text: str) -> bool:
    cleaned = _compact(text).strip("。.!！?？")
    if not cleaned:
        return True
    if cleaned in _CONFIRMATION_WORDS:
        return True
    # 过短、且没有实质名词/动词的确认类小尾巴，不应进入记忆 payload。
    return len(cleaned) <= 2 and cleaned in _CONFIRMATION_WORDS


def _is_bot_record(record: Mapping[str, Any]) -> bool:
    raw = record.get("is_bot")
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "bot"}


def _is_memory_command_only(text: str) -> bool:
    cleaned = _clean_text(text)
    if not any(hint in cleaned for hint in _MEMORY_COMMAND_HINTS):
        return False
    # 带冒号/明确 payload 的直写命令通常不会进入 recent resolver；这里主要排除
    # “把刚才那个记一下”这类命令本身或纯命令味文本。
    return _is_meaningless_deictic(cleaned) or len(_compact(cleaned)) <= 12


def _is_meaningless_deictic(text: str) -> bool:
    cleaned = _clean_text(text)
    if not cleaned:
        return True
    filler = cleaned
    for word in _DEICTIC_WORDS:
        filler = filler.replace(word, "")
    filler = re.sub(r"[：:，,。.!！?？；;、\s]+", "", filler)
    return len(filler) < 2


def _limit_chars(text: str, max_chars: int) -> str:
    cleaned = _clean_text(text)
    if max_chars <= 0:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned
    if max_chars == 1:
        return "…"
    return cleaned[: max_chars - 1].rstrip() + "…"


def _record_text(record: Mapping[str, Any]) -> str:
    return _clean_text(record.get("text") or record.get("raw_content") or record.get("content") or "")


def _filter_recent_records(
    recent_records: Sequence[Mapping[str, Any]],
    command_text: str,
) -> list[_CleanRecord]:
    command_compact = _compact(command_text)
    cleaned: list[_CleanRecord] = []
    for index, record in enumerate(recent_records):
        # A3.1：上下文型写入默认只信 owner 用户自己的实质消息。
        # bot 回复、确认词和 handler 确认不仅要排除，还应视为轻量话题边界；
        # 否则旧主题会穿过“确认/回复”混进新的候选 payload。
        if _is_bot_record(record):
            continue
        text = _record_text(record)
        if not text:
            continue
        if command_compact and _compact(text) == command_compact:
            continue
        if _is_handler_confirmation(text):
            cleaned.clear()
            continue
        if _is_short_confirmation_or_control(text):
            cleaned.clear()
            continue
        if _is_memory_command_only(text):
            cleaned.clear()
            continue
        cleaned.append(_CleanRecord(record=record, text=text, index=index))
    return cleaned

def _sort_time_asc(records: Sequence[_CleanRecord]) -> list[_CleanRecord]:
    # A0 当前已经正序返回；这里按 created_at 补一层稳定排序，缺时间时保留原顺序。
    return sorted(records, key=lambda item: (_created_at(item.record) is None, _created_at(item.record) or 0.0, item.index))


def _tail(records: Sequence[_CleanRecord], limit: int) -> list[_CleanRecord]:
    safe_limit = max(1, int(limit or 1))
    return list(records[-safe_limit:])


def _has_conclusion_marker(intent: ExplicitMemoryIntent, command_text: str) -> bool:
    markers = tuple(getattr(intent, "context_markers", ()) or ())
    joined = " ".join(markers) + " " + str(command_text or "")
    return "结论" in joined


def _select_conclusion_records(records: Sequence[_CleanRecord]) -> list[_CleanRecord]:
    matches = [item for item in records if any(keyword in item.text for keyword in _CONCLUSION_KEYWORDS)]
    if matches:
        return matches[-3:]
    return list(records[-3:])


def _build_payload(records: Sequence[_CleanRecord], *, conclusion_mode: bool, max_payload_chars: int) -> str:
    texts = [_limit_chars(item.text, 180) for item in records if _clean_text(item.text)]
    if not texts:
        return ""
    if len(texts) == 1:
        return _limit_chars(texts[0], max_payload_chars)
    prefix = "近期结论" if conclusion_mode else "近期讨论要点"
    joined = "；".join(texts)
    if not joined.endswith(("。", ".", "！", "!", "？", "?")):
        joined += "。"
    return _limit_chars(f"{prefix}：{joined}", max_payload_chars)


def _msg_ids(records: Sequence[_CleanRecord]) -> tuple[str, ...]:
    ids: list[str] = []
    for item in records:
        msg_id = item.record.get("msg_id") or item.record.get("message_id")
        if msg_id is None or str(msg_id).strip() == "":
            continue
        ids.append(str(msg_id))
    return tuple(ids)


def _context_range(records: Sequence[_CleanRecord]) -> dict[str, Any]:
    timestamps = [_created_at(item.record) for item in records]
    timestamps = [ts for ts in timestamps if ts is not None]
    channels = {_clean_text(item.record.get("channel")) for item in records if _clean_text(item.record.get("channel"))}
    result: dict[str, Any] = {
        "start_ts": min(timestamps) if timestamps else None,
        "end_ts": max(timestamps) if timestamps else None,
        "message_count": len(records),
        "resolver": _RESOLVER_NAME,
    }
    if len(channels) == 1:
        result["channel"] = next(iter(channels))
    return result


def resolve_recent_context_for_explicit_write(
    intent: ExplicitMemoryIntent,
    command_text: str,
    recent_records: Sequence[Mapping[str, Any]],
    max_messages: int = 8,
    max_payload_chars: int = 500,
) -> ContextResolution:
    """把上下文型显式写入命令解析成候选 payload。

    这是 M2.2-A2 规则版核心：只读入调用方提供的 recent records，生成可给
    pending confirmation 使用的候选记忆，不接 handler、不写入、不调用模型。
    """

    if not getattr(intent, "needs_context_resolution", False):
        return ContextResolution(status="not_contextual", reason="intent_does_not_require_context_resolution")

    filtered = _filter_recent_records(recent_records, command_text)
    filtered = [item for item in filtered if not _is_meaningless_deictic(item.text)]
    if not filtered:
        return ContextResolution(status="insufficient_context", reason="no_usable_recent_context")

    ordered = _sort_time_asc(filtered)
    # 输入窗口仍可较大，但实际写入候选只取最近 1-3 条，避免把旧主题、
    # 确认词和更早上下文一起拼成 noisy payload。
    input_window = _tail(ordered, max_messages)
    if not input_window:
        return ContextResolution(status="insufficient_context", reason="empty_context_window")

    conclusion_mode = _has_conclusion_marker(intent, command_text)
    if conclusion_mode:
        used = _select_conclusion_records(input_window)
    else:
        used = _tail(input_window, 3)
    used = [item for item in used if not _is_meaningless_deictic(item.text)]
    if not used:
        return ContextResolution(status="insufficient_context", reason="context_contains_only_deictic_text")

    payload = _build_payload(used, conclusion_mode=conclusion_mode, max_payload_chars=max_payload_chars)
    if not payload or _is_meaningless_deictic(payload):
        return ContextResolution(status="insufficient_context", reason="payload_empty_or_deictic")

    confidence = "medium"
    if len(used) <= 1 or len(payload) < 12:
        confidence = "low"

    return ContextResolution(
        status="resolved",
        payload=payload,
        confidence=confidence,
        used_msg_ids=_msg_ids(used),
        context_range=_context_range(used),
        reason="resolved_by_rules_conclusion" if conclusion_mode else "resolved_by_rules_recent_context",
    )
