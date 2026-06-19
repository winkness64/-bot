from __future__ import annotations

import asyncio
import json

from src.plugins.yangyang.memory.topic_boundary_resolver import (
    build_topic_boundary_messages,
    resolve_topic_boundary_with_model,
    resolve_topic_boundary_with_model_async,
)


def _record(msg_id: str, text: str, ts: float, *, is_bot: bool = False) -> dict:
    return {
        "msg_id": msg_id,
        "uid": "yangyang_bot" if is_bot else "335059272",
        "nick": "秧秧" if is_bot else "漂♂总",
        "group_id": "",
        "channel": "private",
        "text": text,
        "raw_content": text,
        "is_bot": is_bot,
        "created_at": ts,
    }


def _json_response(**kwargs) -> str:
    return json.dumps(kwargs, ensure_ascii=False)


def test_three_turn_discussion_resolved() -> None:
    records = [
        _record("m1", "M2.2-A3.1 降噪修复完成", 1.0),
        _record("m2", "下一步验证 payload 是否干净", 2.0),
        _record("m3", "好，我会按这段整理。", 3.0, is_bot=True),
    ]

    def fake_model(messages):
        assert "话题边界解析器" in messages[0]["content"]
        assert "把刚才我们的讨论内容记一下" in messages[1]["content"]
        assert "m1" in messages[1]["content"] and "M2.2-A3.1" in messages[1]["content"]
        return _json_response(
            ok=True,
            status="resolved",
            payload="M2.2-A3.1 降噪修复完成，下一步验证 payload 是否干净",
            confidence=0.91,
            start_msg_id="m1",
            end_msg_id="m2",
            used_msg_ids=["m1", "m2"],
            reason="用户最近两条在讨论 A3.1 验收",
        )

    result = resolve_topic_boundary_with_model("把刚才我们的讨论内容记一下", records, fake_model)

    assert result.status == "resolved"
    assert result.payload == "M2.2-A3.1 降噪修复完成，下一步验证 payload 是否干净"
    assert result.confidence == 0.91
    assert result.start_msg_id == "m1"
    assert result.end_msg_id == "m2"
    assert result.used_msg_ids == ("m1", "m2")
    assert result.context_range["resolver"] == "topic_boundary_resolver_v1_mockable"
    assert result.context_range["message_count"] == 2
    assert result.context_range["start_ts"] == 1.0
    assert result.context_range["end_ts"] == 2.0


def test_six_turn_discussion_resolved_with_range_ids() -> None:
    records = [_record(f"m{i}", f"第{i}条：围绕 B1 mock resolver 设计", float(i)) for i in range(1, 7)]

    def fake_model(_messages):
        return _json_response(
            ok=True,
            status="resolved",
            payload="B1 mock resolver 需要校验 JSON schema、used_msg_ids 和错误容错",
            confidence=0.86,
            start_msg_id="m2",
            end_msg_id="m6",
            used_msg_ids=["m2", "m3", "m4", "m5", "m6"],
            reason="连续五条都在讨论 B1",
        )

    result = resolve_topic_boundary_with_model("上面那段存档", records, fake_model)

    assert result.status == "resolved"
    assert result.used_msg_ids == ("m2", "m3", "m4", "m5", "m6")
    assert result.start_msg_id == "m2"
    assert result.end_msg_id == "m6"
    assert result.context_range["message_count"] == 5


def test_fifteen_turn_discussion_resolved_when_window_allows() -> None:
    records = [_record(f"m{i}", f"第{i}轮讨论：长窗口边界测试", float(i)) for i in range(1, 16)]

    def fake_model(_messages):
        return _json_response(
            ok=True,
            status="resolved",
            payload="长窗口 15 轮讨论被模型判定为同一话题",
            confidence=0.8,
            start_msg_id="m1",
            end_msg_id="m15",
            used_msg_ids=[f"m{i}" for i in range(1, 16)],
            reason="窗口内连续讨论同一主题",
        )

    result = resolve_topic_boundary_with_model("把刚才讨论记一下", records, fake_model, max_records=50)

    assert result.status == "resolved"
    assert len(result.used_msg_ids) == 15
    assert result.context_range["start_ts"] == 1.0
    assert result.context_range["end_ts"] == 15.0


def test_ambiguous_model_response() -> None:
    records = [_record("m1", "先聊绝区零", 1), _record("m2", "又聊 M2.2-B1", 2)]

    def fake_model(_messages):
        return _json_response(ok=False, status="ambiguous", payload=None, confidence=0.3, used_msg_ids=[], reason="多个话题")

    result = resolve_topic_boundary_with_model("把刚才那个记一下", records, fake_model)

    assert result.status == "ambiguous"
    assert result.payload is None
    assert "多个话题" in result.reason


def test_empty_recent_records_returns_insufficient_without_calling_model() -> None:
    called = False

    def fake_model(_messages):  # pragma: no cover - should not be called
        nonlocal called
        called = True
        return "{}"

    result = resolve_topic_boundary_with_model("把刚才讨论记一下", [], fake_model)

    assert result.status == "insufficient_context"
    assert called is False


def test_bad_json_returns_invalid_model_output() -> None:
    result = resolve_topic_boundary_with_model(
        "把刚才讨论记一下",
        [_record("m1", "有效上下文", 1)],
        lambda _messages: "不是 json",
    )

    assert result.status == "invalid_model_output"
    assert result.reason == "bad_json_or_not_object"


def test_used_msg_id_out_of_window_returns_invalid() -> None:
    def fake_model(_messages):
        return _json_response(
            ok=True,
            status="resolved",
            payload="越界测试",
            confidence=0.9,
            start_msg_id="m1",
            end_msg_id="m1",
            used_msg_ids=["m1", "mx"],
            reason="bad id",
        )

    result = resolve_topic_boundary_with_model("把刚才讨论记一下", [_record("m1", "上下文", 1)], fake_model)

    assert result.status == "invalid_model_output"
    assert result.reason == "used_msg_id_out_of_window"


def test_start_or_end_out_of_window_returns_invalid() -> None:
    def fake_model(_messages):
        return _json_response(
            ok=True,
            status="resolved",
            payload="边界越界",
            confidence=0.9,
            start_msg_id="mx",
            end_msg_id="m1",
            used_msg_ids=["m1"],
            reason="bad start",
        )

    result = resolve_topic_boundary_with_model("把刚才讨论记一下", [_record("m1", "上下文", 1)], fake_model)

    assert result.status == "invalid_model_output"
    assert result.reason == "start_msg_id_out_of_window"


def test_low_confidence_resolved_becomes_ambiguous() -> None:
    def fake_model(_messages):
        return _json_response(
            ok=True,
            status="resolved",
            payload="低置信候选",
            confidence=0.41,
            start_msg_id="m1",
            end_msg_id="m1",
            used_msg_ids=["m1"],
            reason="不太确定",
        )

    result = resolve_topic_boundary_with_model("把刚才讨论记一下", [_record("m1", "上下文", 1)], fake_model)

    assert result.status == "ambiguous"
    assert result.confidence == 0.41
    assert "low_confidence" in result.reason


def test_payload_too_long_is_truncated() -> None:
    long_payload = "A" * 100

    def fake_model(_messages):
        return _json_response(
            ok=True,
            status="resolved",
            payload=long_payload,
            confidence=0.9,
            start_msg_id="m1",
            end_msg_id="m1",
            used_msg_ids=["m1"],
            reason="too long",
        )

    result = resolve_topic_boundary_with_model(
        "把刚才讨论记一下",
        [_record("m1", "上下文", 1)],
        fake_model,
        max_payload_chars=20,
    )

    assert result.status == "resolved"
    assert result.payload is not None
    assert len(result.payload) <= 20
    assert result.payload.endswith("…")
    assert result.context_range["truncated"] is True
    assert "payload_truncated" in result.reason


def test_model_call_exception_returns_model_error() -> None:
    def fake_model(_messages):
        raise RuntimeError("timeout")

    result = resolve_topic_boundary_with_model("把刚才讨论记一下", [_record("m1", "上下文", 1)], fake_model)

    assert result.status == "model_error"
    assert "timeout" in result.reason


def test_messages_builder_contains_constraints_command_and_records() -> None:
    records = [_record("m1", "M2.2-B1 设计", 1.0), _record("m2", "继续 mock 测试", 2.0, is_bot=True)]
    # 这里直接使用内部同格式窗口，确保 build 函数输出可检查。
    window = [
        {"msg_id": "m1", "speaker": "user", "created_at": 1.0, "text": "M2.2-B1 设计"},
        {"msg_id": "m2", "speaker": "assistant", "created_at": 2.0, "text": "继续 mock 测试"},
    ]

    messages = build_topic_boundary_messages("把刚才讨论记一下", window)

    assert messages[0]["role"] == "system"
    assert "只能使用输入 recent_records" in messages[0]["content"]
    assert "不做 memory grounding" in messages[0]["content"]
    assert messages[1]["role"] == "user"
    assert "把刚才讨论记一下" in messages[1]["content"]
    assert "m1" in messages[1]["content"]
    assert "M2.2-B1 设计" in messages[1]["content"]
    assert "assistant" in messages[1]["content"]


def test_json_code_fence_is_accepted() -> None:
    raw = """```json
{"ok": true, "status": "resolved", "payload": "围栏 JSON 可解析", "confidence": 0.9, "start_msg_id": "m1", "end_msg_id": "m1", "used_msg_ids": ["m1"], "reason": "ok"}
```"""

    result = resolve_topic_boundary_with_model("把刚才讨论记一下", [_record("m1", "上下文", 1)], lambda _messages: raw)

    assert result.status == "resolved"
    assert result.payload == "围栏 JSON 可解析"


def test_empty_used_msg_ids_can_be_filled_from_valid_range() -> None:
    records = [_record("m1", "第一句", 1), _record("m2", "第二句", 2), _record("m3", "第三句", 3)]

    def fake_model(_messages):
        return _json_response(
            ok=True,
            status="resolved",
            payload="用 start/end 补齐 used ids",
            confidence=0.9,
            start_msg_id="m1",
            end_msg_id="m3",
            used_msg_ids=[],
            reason="range only",
        )

    result = resolve_topic_boundary_with_model("把刚才讨论记一下", records, fake_model)

    assert result.status == "resolved"
    assert result.used_msg_ids == ("m1", "m2", "m3")



def test_async_resolved_matches_sync_behavior_and_messages() -> None:
    records = [
        _record("m1", "M2.2-B2-B1-A async resolver 开始补齐", 1.0),
        _record("m2", "只增加 async pure function，不接 provider", 2.0),
    ]
    raw = _json_response(
        ok=True,
        status="resolved",
        payload="M2.2-B2-B1-A 只补 async topic boundary resolver，不接 provider",
        confidence=0.93,
        start_msg_id="m1",
        end_msg_id="m2",
        used_msg_ids=["m1", "m2"],
        reason="两条连续讨论 async resolver 范围",
    )
    captured_messages = []

    async def fake_async_model(messages):
        captured_messages.append(messages)
        assert "话题边界解析器" in messages[0]["content"]
        assert "只能使用输入 recent_records" in messages[0]["content"]
        assert "不做 memory grounding" in messages[0]["content"]
        assert "把刚才 async resolver 讨论记一下" in messages[1]["content"]
        assert "m1" in messages[1]["content"]
        assert "M2.2-B2-B1-A async resolver" in messages[1]["content"]
        assert "m2" in messages[1]["content"]
        assert "不接 provider" in messages[1]["content"]
        return raw

    def fake_sync_model(_messages):
        return raw

    async_result = asyncio.run(
        resolve_topic_boundary_with_model_async("把刚才 async resolver 讨论记一下", records, fake_async_model)
    )
    sync_result = resolve_topic_boundary_with_model("把刚才 async resolver 讨论记一下", records, fake_sync_model)

    assert async_result == sync_result
    assert async_result.status == "resolved"
    assert async_result.used_msg_ids == ("m1", "m2")
    assert len(captured_messages) == 1


def test_async_ambiguous_model_response() -> None:
    records = [_record("m1", "先聊 provider design", 1), _record("m2", "又聊 async resolver", 2)]

    async def fake_async_model(_messages):
        return _json_response(ok=False, status="ambiguous", payload=None, confidence=0.2, used_msg_ids=[], reason="多个话题")

    result = asyncio.run(resolve_topic_boundary_with_model_async("把刚才那个记一下", records, fake_async_model))

    assert result.status == "ambiguous"
    assert result.payload is None
    assert "多个话题" in result.reason


def test_async_bad_json_returns_invalid_model_output() -> None:
    async def fake_async_model(_messages):
        return "不是 json"

    result = asyncio.run(
        resolve_topic_boundary_with_model_async("把刚才讨论记一下", [_record("m1", "有效上下文", 1)], fake_async_model)
    )

    assert result.status == "invalid_model_output"
    assert result.reason == "bad_json_or_not_object"


def test_async_model_call_exception_returns_model_error() -> None:
    async def fake_async_model(_messages):
        raise RuntimeError("async timeout")

    result = asyncio.run(
        resolve_topic_boundary_with_model_async("把刚才讨论记一下", [_record("m1", "上下文", 1)], fake_async_model)
    )

    assert result.status == "model_error"
    assert "async timeout" in result.reason


def test_async_empty_recent_records_returns_insufficient_without_calling_model() -> None:
    called = False

    async def fake_async_model(_messages):  # pragma: no cover - should not be called
        nonlocal called
        called = True
        return "{}"

    result = asyncio.run(resolve_topic_boundary_with_model_async("把刚才讨论记一下", [], fake_async_model))

    assert result.status == "insufficient_context"
    assert called is False
