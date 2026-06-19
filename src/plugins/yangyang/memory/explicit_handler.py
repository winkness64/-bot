from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping

from nonebot.log import logger

from ..core.event_adapter import Message
from .context_resolver import resolve_recent_context_for_explicit_write
from .topic_boundary_gate import build_provider_config_from_decision, decide_topic_boundary_enabled
from .topic_boundary_provider import build_topic_boundary_model_call
from .topic_boundary_resolver import resolve_topic_boundary_with_model, resolve_topic_boundary_with_model_async
from .explicit_memory import ExplicitMemoryIntent, detect_explicit_memory_intent
from .store import MemoryStore


@dataclass(slots=True)
class PendingExplicitMemory:
    user_id: str
    session_id: str
    payload: str
    original_text: str
    created_at: float
    source: str = "owner_command_pending"
    resolved: bool = False
    resolver: str = ""
    used_msg_ids: tuple[str, ...] = ()
    context_range: dict[str, Any] = field(default_factory=dict)
    resolution_reason: str = ""


@dataclass(slots=True)
class ExplicitMemoryHandleResult:
    handled: bool
    reply: str = ""
    action: str = "pass"
    intent: ExplicitMemoryIntent | None = None
    entry_id: str = ""


_PENDING_EXPLICIT_MEMORY: dict[tuple[str, str], PendingExplicitMemory] = {}
DEFAULT_PENDING_TTL_SECONDS = 300

_CONFIRM_REPLIES = {"是", "好", "确认", "对", "可以", "嗯", "记", "行", "没错", "对的"}
_CANCEL_REPLIES = {"不是", "不用", "取消", "算了", "别记", "不要记", "不记", "先别", "先不用"}


def clear_explicit_memory_pending() -> None:
    """测试/重载辅助：清空内存 pending。"""
    _PENDING_EXPLICIT_MEMORY.clear()


def has_explicit_memory_pending(session_id: str, user_id: str) -> bool:
    return (str(session_id), str(user_id)) in _PENDING_EXPLICIT_MEMORY


def _pending_key(session_id: str, user_id: str) -> tuple[str, str]:
    return (str(session_id or ""), str(user_id or ""))


def _compact(text: str) -> str:
    return "".join(str(text or "").split())


def _is_owner_private_message(msg: Message) -> bool:
    return str(getattr(msg, "channel", "") or "") == "private" and bool(getattr(msg, "is_owner", False))


def _message_text(msg: Message) -> str:
    return str(getattr(msg, "text", "") or getattr(msg, "raw_content", "") or "").strip()


def _message_msg_id(msg: Message) -> str:
    return str(getattr(msg, "msg_id", "") or "").strip()


def _message_timestamp(msg: Message) -> float | None:
    try:
        timestamp = float(getattr(msg, "timestamp", 0) or 0)
    except (TypeError, ValueError):
        return None
    return timestamp if timestamp > 0 else None


def _fallback_payload_from_recent(msg: Message) -> str:
    """中置信命令没有明确 payload 时的最小兜底。

    非上下文型中置信命令仍沿用 M2.1 行为：只把原命令作为待确认文本。
    上下文型写入会在 handler 的 contextual 分支读取 recent records 并解析候选 payload。
    """
    text = _message_text(msg)
    return text.strip(" ：:，,。.!！;；") or "这条内容"


def _write_explicit_memory(
    store: MemoryStore,
    msg: Message,
    *,
    session_id: str,
    payload: str,
    source_text: str,
    confirmed: bool,
    source: str | None = None,
) -> str:
    entry = store.add_explicit_memory(
        user_id=str(getattr(msg, "uid", "") or ""),
        session_id=session_id,
        payload=payload,
        message_id=_message_msg_id(msg),
        source_text=source_text,
        group_id=str(getattr(msg, "group_id", "") or ""),
        channel=str(getattr(msg, "channel", "") or "private"),
        confirmed=confirmed,
        source=source,
    )
    return str(getattr(entry, "id", "") or "")


def _extract_json_object(text: str) -> dict[str, Any] | None:
    value = str(text or "").strip()
    if not value:
        return None
    start = value.find("{")
    end = value.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(value[start : end + 1])
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _looks_like_natural_memory_request(text: str) -> bool:
    compact = _compact(text)
    if not compact or compact.startswith("/"):
        return False
    if any(q in compact for q in ("你记得", "记不记得", "还记得", "你在记录", "你都记", "记录了什么")):
        return False
    triggers = ("写入记忆", "写进记忆", "写进永久记忆", "记一下", "记下来", "记住", "记着", "记录一下", "记录下来", "存档一下", "别忘了")
    return any(trigger in compact for trigger in triggers)


def _format_recent_records_for_natural_memory(records: list[dict[str, Any]], *, max_records: int = 12) -> str:
    items: list[str] = []
    for row in list(records)[-max_records:]:
        speaker = "bot" if bool(row.get("is_bot")) else "owner"
        msg_id = str(row.get("msg_id") or row.get("message_id") or "")
        content = str(row.get("text") or row.get("content") or row.get("raw_content") or "").strip()
        if not content:
            continue
        content = content.replace("\n", " ")[:500]
        items.append(f"- [{speaker} {msg_id}] {content}")
    return "\n".join(items)


def _build_natural_memory_messages(text: str, recent_records: list[dict[str, Any]] | None = None) -> list[dict[str, str]]:
    recent_text = _format_recent_records_for_natural_memory(recent_records or [])
    return [
        {
            "role": "system",
            "content": (
                "你是私聊长期记忆写入判定器。只判断 owner 是否明确要求把某个事实写入长期记忆。"
                "如果是，提取并润色为一条简洁准确的中文长期记忆；不要编造，不要加入未出现的事实。"
                "如果用户说‘刚才/这个/上面’等上下文指代，可以参考 recent context；若上下文不足或多义，should_write=false。"
                "如果只是询问、闲聊、玩笑、或没有明确要记，should_write=false。"
                "只输出 JSON：{\"should_write\":bool,\"payload\":str,\"needs_confirmation\":bool,\"reason\":str}。"
                "除非用户使用 /记一下 这类硬命令，否则 needs_confirmation 通常为 true。"
            ),
        },
        {"role": "user", "content": f"recent context:\n{recent_text or '(empty)'}\n\ncurrent owner message:\n{text}"},
    ]


async def _handle_natural_memory_request_async(
    msg: Message,
    store: MemoryStore,
    *,
    session_id: str,
    uid: str,
    key: tuple[str, str],
    text: str,
    current_time: float,
    model_call: Callable[[list[dict[str, str]]], Awaitable[str]],
) -> ExplicitMemoryHandleResult:
    recent_records = _get_recent_records_for_context(store, msg, session_id=session_id, uid=uid, limit=16)
    try:
        raw = await model_call(_build_natural_memory_messages(text, recent_records))
    except Exception:
        logger.exception("ExplicitMemoryHandler: natural memory LLM decision failed")
        return ExplicitMemoryHandleResult(
            True,
            reply="漂♂总，这句像是自然语言记忆请求，但判定模型失败；我没有写入，也不会假装记好了。要强制规则写入请用 `/记一下 内容`。",
            action="natural_llm_error",
        )
    data = _extract_json_object(raw)
    if not data or not bool(data.get("should_write")):
        return ExplicitMemoryHandleResult(
            True,
            reply="漂♂总，我判断这句不该写入长期记忆；当前未写入。要强制规则写入请用 `/记一下 内容`。",
            action="natural_llm_no_write",
        )
    payload = str(data.get("payload") or "").strip()
    if not payload:
        return ExplicitMemoryHandleResult(
            True,
            reply="漂♂总，判定模型没有给出可写入内容；当前未写入，也不会假装记好了。",
            action="natural_llm_empty_payload",
        )
    needs_confirmation = bool(data.get("needs_confirmation", True))
    intent = ExplicitMemoryIntent(
        "write",
        confidence="medium",
        payload=payload,
        reason=str(data.get("reason") or "natural_llm_memory_decision"),
        needs_confirmation=needs_confirmation,
        scope="private_owner",
    )
    if needs_confirmation:
        _PENDING_EXPLICIT_MEMORY[key] = PendingExplicitMemory(
            user_id=uid,
            session_id=session_id,
            payload=payload,
            original_text=text,
            created_at=current_time,
            source="natural_llm_pending",
        )
        return ExplicitMemoryHandleResult(
            True,
            reply=f"漂♂总，我理解成这条记忆：“{payload}”。确认写入吗？",
            action="natural_llm_pending_confirmation",
            intent=intent,
        )
    entry_id = _write_explicit_memory(
        store,
        msg,
        session_id=session_id,
        payload=payload,
        source_text=text,
        confirmed=False,
        source="natural_llm_direct",
    )
    if not entry_id:
        return ExplicitMemoryHandleResult(False, action="natural_llm_write_failed", intent=intent)
    _PENDING_EXPLICIT_MEMORY.pop(key, None)
    return ExplicitMemoryHandleResult(
        True,
        reply=f"记好了，漂♂总。entry_id={entry_id}",
        action="natural_llm_direct_write",
        intent=intent,
        entry_id=entry_id,
    )


def _get_recent_records_for_context(
    store: MemoryStore,
    msg: Message,
    *,
    session_id: str,
    uid: str,
    limit: int = 16,
) -> list[dict[str, Any]]:
    """读取 owner 私聊 recent records，尽量排除当前显式写入命令。"""
    kwargs: dict[str, Any] = {
        "channel": "private",
        "uid": uid,
        "session_id": session_id,
        "limit": int(limit),
    }
    current_msg_id = _message_msg_id(msg)
    if current_msg_id:
        kwargs["exclude_msg_id"] = current_msg_id
    else:
        before_ts = _message_timestamp(msg)
        if before_ts is not None:
            kwargs["before_ts"] = before_ts

    try:
        return list(store.get_recent_message_records(**kwargs))
    except Exception:
        logger.exception("ExplicitMemoryHandler: failed to read recent records for contextual write")
        return []


def _contextual_source_text(pending: PendingExplicitMemory) -> str:
    evidence = {
        "type": "explicit_context_resolved",
        "original_text": pending.original_text,
        "resolver": pending.resolver or str((pending.context_range or {}).get("resolver") or ""),
        "used_msg_ids": list(pending.used_msg_ids),
        "context_range": pending.context_range or {},
        "resolution_reason": pending.resolution_reason,
    }
    return json.dumps(evidence, ensure_ascii=False, sort_keys=True)


def _is_contextual_pending(pending: PendingExplicitMemory) -> bool:
    return bool(pending.resolved) or pending.source == "context_resolved_pending"


def _set_contextual_pending(
    *,
    uid: str,
    session_id: str,
    key: tuple[str, str],
    payload: str,
    original_text: str,
    current_time: float,
    resolver: str,
    used_msg_ids: tuple[str, ...],
    context_range: dict[str, Any],
    resolution_reason: str,
) -> None:
    _PENDING_EXPLICIT_MEMORY[key] = PendingExplicitMemory(
        user_id=uid,
        session_id=session_id,
        payload=payload,
        original_text=original_text,
        created_at=current_time,
        source="context_resolved_pending",
        resolved=True,
        resolver=resolver,
        used_msg_ids=used_msg_ids,
        context_range=context_range,
        resolution_reason=resolution_reason,
    )


def _handle_contextual_write(
    msg: Message,
    store: MemoryStore,
    *,
    session_id: str,
    uid: str,
    key: tuple[str, str],
    text: str,
    current_time: float,
    intent: ExplicitMemoryIntent,
    topic_boundary_model_call: Callable[[list[dict[str, str]]], str] | None = None,
) -> ExplicitMemoryHandleResult:
    recent_records = _get_recent_records_for_context(store, msg, session_id=session_id, uid=uid, limit=16)

    if topic_boundary_model_call is not None:
        try:
            topic_resolution = resolve_topic_boundary_with_model(
                text,
                recent_records,
                topic_boundary_model_call,
                max_records=16,
                max_payload_chars=500,
            )
        except Exception as exc:  # pragma: no cover - resolver should catch model errors, keep handler safe.
            logger.exception("ExplicitMemoryHandler: topic boundary resolver crashed; fallback to rules")
            topic_resolution = None
            topic_status = "model_error"
            topic_reason = str(exc) or exc.__class__.__name__
        else:
            topic_status = str(topic_resolution.status or "")
            topic_reason = str(topic_resolution.reason or "")

        if topic_resolution is not None and topic_status == "resolved" and str(topic_resolution.payload or "").strip():
            payload = str(topic_resolution.payload or "").strip()
            context_range = dict(topic_resolution.context_range or {})
            resolver = str(context_range.get("resolver") or "topic_boundary_resolver_v1_mockable")
            context_range["resolver"] = resolver
            used_msg_ids = tuple(str(item) for item in topic_resolution.used_msg_ids)
            _set_contextual_pending(
                uid=uid,
                session_id=session_id,
                key=key,
                payload=payload,
                original_text=text,
                current_time=current_time,
                resolver=resolver,
                used_msg_ids=used_msg_ids,
                context_range=context_range,
                resolution_reason=str(topic_resolution.reason or ""),
            )
            logger.info(
                f"ExplicitMemoryHandler: pending_topic_boundary user_id={uid} session_id={session_id} "
                f"resolver={resolver} used_msg_ids={list(used_msg_ids)} payload_preview={payload[:40]}"
            )
            return ExplicitMemoryHandleResult(
                True,
                reply=f"漂♂总，是要记录为：“{payload}” 吗？",
                action="pending_topic_boundary_confirmation",
                intent=intent,
            )

        if topic_status in {"ambiguous", "insufficient_context"}:
            _PENDING_EXPLICIT_MEMORY.pop(key, None)
            logger.info(
                f"ExplicitMemoryHandler: topic_boundary_unresolved user_id={uid} session_id={session_id} "
                f"status={topic_status} reason={topic_reason} recent_count={len(recent_records)}"
            )
            if topic_status == "ambiguous":
                return ExplicitMemoryHandleResult(
                    True,
                    reply="漂♂总，我看到刚才可能有不止一段话题。你把要记的那段内容再点明一下？",
                    action="topic_boundary_ambiguous",
                    intent=intent,
                )
            return ExplicitMemoryHandleResult(
                True,
                reply="漂♂总，我没抓准你说的“刚才/那个”是哪段，要不你把要记的内容再说清楚一点？",
                action="context_insufficient",
                intent=intent,
            )

        logger.info(
            f"ExplicitMemoryHandler: topic_boundary_fallback_to_rules user_id={uid} session_id={session_id} "
            f"status={topic_status} reason={topic_reason} recent_count={len(recent_records)}"
        )

    resolution = resolve_recent_context_for_explicit_write(
        intent,
        text,
        recent_records,
        max_messages=8,
        max_payload_chars=500,
    )

    if resolution.status == "resolved" and str(resolution.payload or "").strip():
        payload = str(resolution.payload or "").strip()
        context_range = dict(resolution.context_range or {})
        resolver = str(context_range.get("resolver") or "recent_context_resolver_v1_rules")
        _set_contextual_pending(
            uid=uid,
            session_id=session_id,
            key=key,
            payload=payload,
            original_text=text,
            current_time=current_time,
            resolver=resolver,
            used_msg_ids=tuple(str(item) for item in resolution.used_msg_ids),
            context_range=context_range,
            resolution_reason=str(resolution.reason or ""),
        )
        logger.info(
            f"ExplicitMemoryHandler: pending_context user_id={uid} session_id={session_id} "
            f"resolver={resolver} used_msg_ids={list(resolution.used_msg_ids)} payload_preview={payload[:40]}"
        )
        return ExplicitMemoryHandleResult(
            True,
            reply=f"漂♂总，是要记录为：“{payload}” 吗？",
            action="pending_context_confirmation",
            intent=intent,
        )

    # 新的上下文型写入没有解析到候选时，不保留旧 pending，避免下一句“确认”误写旧内容。
    _PENDING_EXPLICIT_MEMORY.pop(key, None)
    logger.info(
        f"ExplicitMemoryHandler: context_insufficient user_id={uid} session_id={session_id} "
        f"status={resolution.status} reason={resolution.reason} recent_count={len(recent_records)}"
    )
    return ExplicitMemoryHandleResult(
        True,
        reply="漂♂总，我没抓准你说的“刚才/那个”是哪段，要不你把要记的内容再说清楚一点？",
        action="context_insufficient",
        intent=intent,
    )


async def _handle_contextual_write_async(
    msg: Message,
    store: MemoryStore,
    *,
    session_id: str,
    uid: str,
    key: tuple[str, str],
    text: str,
    current_time: float,
    intent: ExplicitMemoryIntent,
    topic_boundary_model_call: Callable[[list[dict[str, str]]], Awaitable[str]],
    max_records: int = 16,
    max_payload_chars: int = 500,
    min_confidence: float = 0.65,
) -> ExplicitMemoryHandleResult:
    recent_records = _get_recent_records_for_context(
        store,
        msg,
        session_id=session_id,
        uid=uid,
        limit=max(1, int(max_records or 1)),
    )

    try:
        topic_resolution = await resolve_topic_boundary_with_model_async(
            text,
            recent_records,
            topic_boundary_model_call,
            max_records=max(1, int(max_records or 1)),
            max_payload_chars=max(1, int(max_payload_chars or 1)),
            min_confidence=float(min_confidence),
        )
    except Exception as exc:  # pragma: no cover - resolver should catch model errors, keep handler safe.
        logger.exception("ExplicitMemoryHandler: async topic boundary resolver crashed; fallback to rules")
        topic_resolution = None
        topic_status = "model_error"
        topic_reason = str(exc) or exc.__class__.__name__
    else:
        topic_status = str(topic_resolution.status or "")
        topic_reason = str(topic_resolution.reason or "")

    if topic_resolution is not None and topic_status == "resolved" and str(topic_resolution.payload or "").strip():
        payload = str(topic_resolution.payload or "").strip()
        context_range = dict(topic_resolution.context_range or {})
        resolver = str(context_range.get("resolver") or "topic_boundary_resolver_v1_mockable")
        context_range["resolver"] = resolver
        used_msg_ids = tuple(str(item) for item in topic_resolution.used_msg_ids)
        _set_contextual_pending(
            uid=uid,
            session_id=session_id,
            key=key,
            payload=payload,
            original_text=text,
            current_time=current_time,
            resolver=resolver,
            used_msg_ids=used_msg_ids,
            context_range=context_range,
            resolution_reason=str(topic_resolution.reason or ""),
        )
        logger.info(
            f"ExplicitMemoryHandler: pending_topic_boundary_async user_id={uid} session_id={session_id} "
            f"resolver={resolver} used_msg_ids={list(used_msg_ids)} payload_preview={payload[:40]}"
        )
        return ExplicitMemoryHandleResult(
            True,
            reply=f"漂♂总，是要记录为：“{payload}” 吗？",
            action="pending_topic_boundary_confirmation",
            intent=intent,
        )

    if topic_status in {"ambiguous", "insufficient_context"}:
        _PENDING_EXPLICIT_MEMORY.pop(key, None)
        logger.info(
            f"ExplicitMemoryHandler: topic_boundary_async_unresolved user_id={uid} session_id={session_id} "
            f"status={topic_status} reason={topic_reason} recent_count={len(recent_records)}"
        )
        if topic_status == "ambiguous":
            return ExplicitMemoryHandleResult(
                True,
                reply="漂♂总，我看到刚才可能有不止一段话题。你把要记的那段内容再点明一下？",
                action="topic_boundary_ambiguous",
                intent=intent,
            )
        return ExplicitMemoryHandleResult(
            True,
            reply="漂♂总，我没抓准你说的“刚才/那个”是哪段，要不你把要记的内容再说清楚一点？",
            action="context_insufficient",
            intent=intent,
        )

    logger.info(
        f"ExplicitMemoryHandler: topic_boundary_async_fallback_to_rules user_id={uid} session_id={session_id} "
        f"status={topic_status} reason={topic_reason} recent_count={len(recent_records)}"
    )
    return _handle_contextual_write(
        msg,
        store,
        session_id=session_id,
        uid=uid,
        key=key,
        text=text,
        current_time=current_time,
        intent=intent,
    )


def handle_explicit_memory_message(
    msg: Message,
    store: MemoryStore,
    *,
    session_id: str,
    now: float | None = None,
    ttl_seconds: int = DEFAULT_PENDING_TTL_SECONDS,
    topic_boundary_model_call: Callable[[list[dict[str, str]]], str] | None = None,
) -> ExplicitMemoryHandleResult:
    """处理 owner 私聊显式记忆命令。

    返回 handled=True 时，调用方应直接发送 reply 并停止后续 LLM 流程。
    返回 handled=False 时，调用方继续原有消息链路。
    """
    if not _is_owner_private_message(msg):
        return ExplicitMemoryHandleResult(False, action="pass_non_owner_or_non_private")

    current_time = float(now if now is not None else time.time())
    sid = str(session_id or f"private:{getattr(msg, 'uid', '')}")
    uid = str(getattr(msg, "uid", "") or "")
    key = _pending_key(sid, uid)
    text = _message_text(msg)
    compact = _compact(text)

    pending = _PENDING_EXPLICIT_MEMORY.get(key)
    if pending is not None:
        age = current_time - float(pending.created_at)
        if age > max(1, int(ttl_seconds)):
            _PENDING_EXPLICIT_MEMORY.pop(key, None)
            if compact in _CONFIRM_REPLIES or compact in _CANCEL_REPLIES:
                return ExplicitMemoryHandleResult(
                    True,
                    reply="刚才那条确认已经过期啦，漂♂总要记的话再说一遍。",
                    action="pending_expired",
                )
            pending = None

    intent = detect_explicit_memory_intent(text, scope="private_owner")

    if pending is not None and intent.intent == "confirm":
        contextual = _is_contextual_pending(pending)
        source_text = _contextual_source_text(pending) if contextual else pending.original_text
        entry_id = _write_explicit_memory(
            store,
            msg,
            session_id=sid,
            payload=pending.payload,
            source_text=source_text,
            confirmed=True,
            source="explicit_context_resolved" if contextual else (pending.source or None),
        )
        if not entry_id:
            return ExplicitMemoryHandleResult(True, reply="漂♂总，这条没有真实写入成功，我不会假装已经记好。", action="confirmed_write_failed", intent=intent)
        _PENDING_EXPLICIT_MEMORY.pop(key, None)
        logger.info(
            f"ExplicitMemoryHandler: confirmed user_id={uid} session_id={sid} "
            f"entry_id={entry_id} contextual={contextual}"
        )
        return ExplicitMemoryHandleResult(
            True,
            reply=f"好，已经真实写入。entry_id={entry_id}",
            action="confirmed_write",
            intent=intent,
            entry_id=entry_id,
        )

    if pending is not None and intent.intent == "cancel":
        _PENDING_EXPLICIT_MEMORY.pop(key, None)
        logger.info(f"ExplicitMemoryHandler: canceled user_id={uid} session_id={sid}")
        return ExplicitMemoryHandleResult(True, reply="好，那我不记这条。", action="canceled", intent=intent)

    # 没有 pending 时，确认/取消词必须放过，避免“好/是”被误吞。
    if intent.intent in {"confirm", "cancel"}:
        return ExplicitMemoryHandleResult(False, action="pass_confirm_or_cancel_without_pending", intent=intent)

    # 查询/审计只读，不写入、不确认，交回 C3.1/C4/普通 LLM 链路。
    if intent.intent in {"query", "audit", "none"}:
        return ExplicitMemoryHandleResult(False, action=f"pass_{intent.intent}", intent=intent)

    if intent.intent == "write" and intent.needs_context_resolution:
        return _handle_contextual_write(
            msg,
            store,
            session_id=sid,
            uid=uid,
            key=key,
            text=text,
            current_time=current_time,
            intent=intent,
            topic_boundary_model_call=topic_boundary_model_call,
        )

    if intent.intent == "write" and not intent.needs_confirmation and intent.payload.strip():
        entry_id = _write_explicit_memory(
            store,
            msg,
            session_id=sid,
            payload=intent.payload.strip(),
            source_text=text,
            confirmed=False,
        )
        if not entry_id:
            return ExplicitMemoryHandleResult(True, reply="漂♂总，这条没有真实写入成功，我不会假装已经记好。", action="direct_write_failed", intent=intent)
        _PENDING_EXPLICIT_MEMORY.pop(key, None)
        logger.info(f"ExplicitMemoryHandler: direct_write user_id={uid} session_id={sid} entry_id={entry_id}")
        return ExplicitMemoryHandleResult(
            True,
            reply=f"记好了，漂♂总。entry_id={entry_id}",
            action="direct_write",
            intent=intent,
            entry_id=entry_id,
        )

    if intent.intent == "write" and intent.needs_confirmation:
        payload = (intent.payload or "").strip() or _fallback_payload_from_recent(msg)
        _PENDING_EXPLICIT_MEMORY[key] = PendingExplicitMemory(
            user_id=uid,
            session_id=sid,
            payload=payload,
            original_text=text,
            created_at=current_time,
        )
        logger.info(f"ExplicitMemoryHandler: pending user_id={uid} session_id={sid} payload_preview={payload[:40]}")
        return ExplicitMemoryHandleResult(
            True,
            reply=f"漂♂总，是要记录为：“{payload}” 吗？",
            action="pending_confirmation",
            intent=intent,
        )

    return ExplicitMemoryHandleResult(False, action="pass_unhandled", intent=intent)

async def handle_explicit_memory_message_async(
    msg: Message,
    store: MemoryStore,
    *,
    session_id: str,
    config: Mapping[str, Any] | None = None,
    router: Any | None = None,
    now: float | None = None,
    ttl_seconds: int = DEFAULT_PENDING_TTL_SECONDS,
) -> ExplicitMemoryHandleResult:
    """Async entry for explicit memory handling with a default-closed topic-boundary gate.

    When the gate is disabled or no async router is supplied, this wrapper fully
    falls back to the existing synchronous handler.  The async topic-boundary
    model path is only used for owner-private contextual writes.
    """

    channel = str(getattr(msg, "channel", "") or "")
    is_owner = bool(getattr(msg, "is_owner", False))
    is_private = channel == "private"
    is_group = channel == "group"
    decision = decide_topic_boundary_enabled(
        config,
        is_owner=is_owner,
        is_private=is_private,
        is_group=is_group,
    )

    if not decision.enabled or router is None:
        if _is_owner_private_message(msg) and _looks_like_natural_memory_request(_message_text(msg)):
            return ExplicitMemoryHandleResult(
                True,
                reply="漂♂总，这句像是自然语言记忆请求，但记忆判定模型当前不可用；我没有写入，也不会假装记好了。要强制规则写入请用 `/记一下 内容`。",
                action="natural_memory_router_unavailable",
            )
        return handle_explicit_memory_message(
            msg,
            store,
            session_id=session_id,
            now=now,
            ttl_seconds=ttl_seconds,
        )

    if not _is_owner_private_message(msg):
        return handle_explicit_memory_message(
            msg,
            store,
            session_id=session_id,
            now=now,
            ttl_seconds=ttl_seconds,
        )

    text = _message_text(msg)
    current_time = float(now if now is not None else time.time())
    sid = str(session_id or f"private:{getattr(msg, 'uid', '')}")
    uid = str(getattr(msg, "uid", "") or "")
    key = _pending_key(sid, uid)

    provider_config = build_provider_config_from_decision(decision)
    topic_boundary_model_call = build_topic_boundary_model_call(router, provider_config)

    if _looks_like_natural_memory_request(text):
        natural_result = await _handle_natural_memory_request_async(
            msg,
            store,
            session_id=sid,
            uid=uid,
            key=key,
            text=text,
            current_time=current_time,
            model_call=topic_boundary_model_call,
        )
        if natural_result.handled:
            return natural_result

    intent = detect_explicit_memory_intent(text, scope="private_owner")
    if intent.intent != "write" or not intent.needs_context_resolution:
        return handle_explicit_memory_message(
            msg,
            store,
            session_id=session_id,
            now=now,
            ttl_seconds=ttl_seconds,
        )
    return await _handle_contextual_write_async(
        msg,
        store,
        session_id=sid,
        uid=uid,
        key=key,
        text=text,
        current_time=current_time,
        intent=intent,
        topic_boundary_model_call=topic_boundary_model_call,
        max_records=decision.max_records,
        max_payload_chars=decision.max_payload_chars,
        min_confidence=decision.min_confidence,
    )

