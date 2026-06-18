from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping, Sequence


ModelCall = Callable[[list[dict[str, str]]], str]
AsyncModelCall = Callable[[list[dict[str, str]]], Awaitable[str]]


@dataclass(frozen=True)
class TopicBoundaryResolution:
    """LLM/mock 模型话题边界解析结果。

    B1 只提供可注入 model_call 的纯函数，不接真实 LLM、不写入、不接 handler。
    """

    status: str  # resolved | ambiguous | insufficient_context | invalid_model_output | model_error
    payload: str | None = None
    confidence: float = 0.0
    start_msg_id: str | None = None
    end_msg_id: str | None = None
    used_msg_ids: tuple[str, ...] = ()
    context_range: dict[str, Any] = field(default_factory=dict)
    reason: str = ""
    raw_model_output: str = ""


_RESOLVER_NAME = "topic_boundary_resolver_v1_mockable"

_SYSTEM_PROMPT = """你是一个“话题边界解析器”，只负责根据给定的最近聊天窗口，判断用户命令里“刚才/那个/这段/我们的讨论内容/这个结论”指的是哪一段对话，并生成一条可存档的候选摘要。

硬性规则：
1. 只能使用输入 recent_records 中出现的信息。
2. 不得使用窗口外事实、长期记忆、常识补全或猜测。
3. 不做人物黑话/外号解析，不做 memory grounding。
4. 如果最近窗口中有多个话题，且无法确定用户指哪一段，返回 status="ambiguous"。
5. 如果上下文不足，返回 status="insufficient_context"。
6. 输出必须是 JSON 对象，不要输出 Markdown，不要解释。
7. payload 应是适合长期记忆的简洁事实/结论，不要复读“记一下”命令。
8. used_msg_ids 必须来自输入 recent_records。
""".strip()

_OUTPUT_SCHEMA = {
    "ok": "boolean",
    "status": "resolved|ambiguous|insufficient_context",
    "payload": "string|null",
    "confidence": "number 0..1",
    "start_msg_id": "string|null",
    "end_msg_id": "string|null",
    "used_msg_ids": "array[string]",
    "reason": "string",
}


def _clean_text(value: Any) -> str:
    text = str(value or "").strip()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _record_text(record: Mapping[str, Any]) -> str:
    return _clean_text(record.get("text") or record.get("raw_content") or record.get("content") or "")


def _record_msg_id(record: Mapping[str, Any], index: int) -> str:
    raw = record.get("msg_id") or record.get("message_id") or record.get("id")
    if raw is None or str(raw).strip() == "":
        return f"idx_{index}"
    return str(raw)


def _created_at(record: Mapping[str, Any]) -> float | None:
    raw = record.get("created_at") or record.get("timestamp")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _is_bot_record(record: Mapping[str, Any]) -> bool:
    raw = record.get("is_bot")
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "bot", "assistant"}


def _speaker(record: Mapping[str, Any]) -> str:
    return "assistant" if _is_bot_record(record) else "user"


def _prepare_window(
    recent_records: Sequence[Mapping[str, Any]],
    *,
    max_records: int,
) -> list[dict[str, Any]]:
    safe_limit = max(1, int(max_records or 1))
    tail = list(recent_records)[-safe_limit:]
    prepared: list[dict[str, Any]] = []
    for index, record in enumerate(tail):
        text = _record_text(record)
        if not text:
            continue
        prepared.append(
            {
                "msg_id": _record_msg_id(record, index),
                "speaker": _speaker(record),
                "created_at": _created_at(record),
                "text": text,
                "_record": record,
            }
        )
    return prepared


def _model_records(window: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "msg_id": str(item["msg_id"]),
            "speaker": str(item["speaker"]),
            "created_at": item.get("created_at"),
            "text": str(item["text"]),
        }
        for item in window
    ]


def build_topic_boundary_messages(command_text: str, window: Sequence[Mapping[str, Any]]) -> list[dict[str, str]]:
    """构造给 topic boundary model_call 的 messages。

    单独暴露该函数，方便测试确认 prompt 中包含硬约束、命令和消息窗口。
    """

    user_payload = {
        "command_text": str(command_text or ""),
        "recent_records": _model_records(window),
        "output_schema": _OUTPUT_SCHEMA,
    }
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False, sort_keys=True)},
    ]


def _strip_json_fence(raw: str) -> str:
    text = str(raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json|JSON)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_json_object(raw: str) -> dict[str, Any] | None:
    try:
        obj = json.loads(_strip_json_fence(raw))
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _coerce_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lower = value.strip().lower()
        if lower in {"true", "1", "yes"}:
            return True
        if lower in {"false", "0", "no"}:
            return False
    return None


def _coerce_float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number < 0.0 or number > 1.0:
        return None
    return number


def _coerce_optional_msg_id(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _coerce_used_msg_ids(value: Any) -> tuple[str, ...] | None:
    if not isinstance(value, list):
        return None
    result: list[str] = []
    for item in value:
        text = str(item).strip()
        if not text:
            return None
        result.append(text)
    return tuple(result)


def _limit_payload(text: str, max_chars: int) -> tuple[str, bool]:
    cleaned = _clean_text(text)
    safe_limit = max(1, int(max_chars or 1))
    if len(cleaned) <= safe_limit:
        return cleaned, False
    if safe_limit == 1:
        return "…", True
    return cleaned[: safe_limit - 1].rstrip() + "…", True


def _interval_ids(window_ids: Sequence[str], start_msg_id: str, end_msg_id: str) -> tuple[str, ...] | None:
    try:
        start_idx = list(window_ids).index(start_msg_id)
        end_idx = list(window_ids).index(end_msg_id)
    except ValueError:
        return None
    if start_idx > end_idx:
        return None
    return tuple(window_ids[start_idx : end_idx + 1])


def _context_range(
    window_by_id: Mapping[str, Mapping[str, Any]],
    used_msg_ids: Sequence[str],
    *,
    start_msg_id: str | None,
    end_msg_id: str | None,
    model_status: str,
    truncated: bool = False,
) -> dict[str, Any]:
    timestamps = [_created_at(window_by_id[msg_id]) for msg_id in used_msg_ids if msg_id in window_by_id]
    timestamps = [item for item in timestamps if item is not None]
    result: dict[str, Any] = {
        "resolver": _RESOLVER_NAME,
        "start_msg_id": start_msg_id,
        "end_msg_id": end_msg_id,
        "message_count": len(tuple(used_msg_ids)),
        "model_status": model_status,
    }
    if timestamps:
        result["start_ts"] = min(timestamps)
        result["end_ts"] = max(timestamps)
    if truncated:
        result["truncated"] = True
    return result


def _invalid(reason: str, raw: str = "") -> TopicBoundaryResolution:
    return TopicBoundaryResolution(status="invalid_model_output", reason=reason, raw_model_output=raw)


def _model_error(exc: Exception) -> TopicBoundaryResolution:
    return TopicBoundaryResolution(status="model_error", reason=str(exc) or exc.__class__.__name__)


def _resolve_topic_boundary_from_raw(
    raw: Any,
    window: Sequence[Mapping[str, Any]],
    *,
    max_payload_chars: int,
    min_confidence: float,
) -> TopicBoundaryResolution:
    """解析并校验模型原始输出，供同步/异步 resolver 共用。"""

    window_ids = tuple(str(item["msg_id"]) for item in window)
    window_by_id = {str(item["msg_id"]): item for item in window}

    raw_text = str(raw or "")
    obj = _parse_json_object(raw_text)
    if obj is None:
        return _invalid("bad_json_or_not_object", raw_text)

    status = str(obj.get("status") or "").strip()
    ok = _coerce_bool(obj.get("ok"))
    reason = str(obj.get("reason") or "").strip()

    if status == "ambiguous" or ok is False and status == "ambiguous":
        return TopicBoundaryResolution(status="ambiguous", reason=reason or "model_marked_ambiguous", raw_model_output=raw_text)
    if status == "insufficient_context" or ok is False and status == "insufficient_context":
        return TopicBoundaryResolution(status="insufficient_context", reason=reason or "model_marked_insufficient_context", raw_model_output=raw_text)

    if status != "resolved" or ok is not True:
        return _invalid("status_or_ok_not_resolved", raw_text)

    payload_raw = obj.get("payload")
    if not isinstance(payload_raw, str) or not payload_raw.strip():
        return _invalid("resolved_payload_empty_or_not_string", raw_text)

    confidence = _coerce_float(obj.get("confidence"))
    if confidence is None:
        return _invalid("confidence_invalid", raw_text)

    used_msg_ids = _coerce_used_msg_ids(obj.get("used_msg_ids"))
    if used_msg_ids is None:
        return _invalid("used_msg_ids_not_list", raw_text)

    start_msg_id = _coerce_optional_msg_id(obj.get("start_msg_id"))
    end_msg_id = _coerce_optional_msg_id(obj.get("end_msg_id"))

    if start_msg_id is not None and start_msg_id not in window_by_id:
        return _invalid("start_msg_id_out_of_window", raw_text)
    if end_msg_id is not None and end_msg_id not in window_by_id:
        return _invalid("end_msg_id_out_of_window", raw_text)

    if not used_msg_ids:
        if start_msg_id is None or end_msg_id is None:
            return _invalid("used_msg_ids_empty_without_valid_range", raw_text)
        interval = _interval_ids(window_ids, start_msg_id, end_msg_id)
        if not interval:
            return _invalid("invalid_start_end_range", raw_text)
        used_msg_ids = interval

    for msg_id in used_msg_ids:
        if msg_id not in window_by_id:
            return _invalid("used_msg_id_out_of_window", raw_text)

    if start_msg_id is None:
        start_msg_id = used_msg_ids[0]
    if end_msg_id is None:
        end_msg_id = used_msg_ids[-1]

    if confidence < float(min_confidence):
        return TopicBoundaryResolution(
            status="ambiguous",
            confidence=confidence,
            reason=f"low_confidence:{confidence:.3f}<min:{float(min_confidence):.3f}",
            raw_model_output=raw_text,
        )

    payload, truncated = _limit_payload(payload_raw, max_payload_chars)
    final_reason = reason or "resolved_by_model"
    if truncated:
        final_reason = f"{final_reason};payload_truncated"

    return TopicBoundaryResolution(
        status="resolved",
        payload=payload,
        confidence=confidence,
        start_msg_id=start_msg_id,
        end_msg_id=end_msg_id,
        used_msg_ids=tuple(used_msg_ids),
        context_range=_context_range(
            window_by_id,
            used_msg_ids,
            start_msg_id=start_msg_id,
            end_msg_id=end_msg_id,
            model_status=status,
            truncated=truncated,
        ),
        reason=final_reason,
        raw_model_output=raw_text,
    )


def resolve_topic_boundary_with_model(
    command_text: str,
    recent_records: Sequence[Mapping[str, Any]],
    model_call: ModelCall,
    *,
    max_records: int = 50,
    max_payload_chars: int = 800,
    min_confidence: float = 0.65,
) -> TopicBoundaryResolution:
    """使用注入的 model_call 解析“刚才/那段讨论”的语义边界。

    B1 仅为 mockable pure function：不接真实模型、不写记忆、不接 handler。
    """

    window = _prepare_window(recent_records, max_records=max_records)
    if not window:
        return TopicBoundaryResolution(status="insufficient_context", reason="no_recent_records")

    messages = build_topic_boundary_messages(command_text, window)

    try:
        raw = model_call(messages)
    except Exception as exc:  # pragma: no cover - exact exception type由调用方决定
        return _model_error(exc)

    return _resolve_topic_boundary_from_raw(
        raw,
        window,
        max_payload_chars=max_payload_chars,
        min_confidence=min_confidence,
    )


async def resolve_topic_boundary_with_model_async(
    command_text: str,
    recent_records: Sequence[Mapping[str, Any]],
    model_call: AsyncModelCall,
    *,
    max_records: int = 50,
    max_payload_chars: int = 800,
    min_confidence: float = 0.65,
) -> TopicBoundaryResolution:
    """异步模型调用版话题边界解析纯函数。

    仅将 model_call 改为 async callable 并 await；不接 provider/handler/真实 LLM。
    """

    window = _prepare_window(recent_records, max_records=max_records)
    if not window:
        return TopicBoundaryResolution(status="insufficient_context", reason="no_recent_records")

    messages = build_topic_boundary_messages(command_text, window)

    try:
        raw = await model_call(messages)
    except Exception as exc:  # pragma: no cover - exact exception type由调用方决定
        return _model_error(exc)

    return _resolve_topic_boundary_from_raw(
        raw,
        window,
        max_payload_chars=max_payload_chars,
        min_confidence=min_confidence,
    )
