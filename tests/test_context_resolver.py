from __future__ import annotations

from src.plugins.yangyang.memory.context_resolver import (
    resolve_recent_context_for_explicit_write,
)
from src.plugins.yangyang.memory.explicit_memory import (
    ExplicitMemoryIntent,
    detect_explicit_memory_intent,
)


def _record(msg_id: str, text: str, ts: float, *, is_bot: bool = False, channel: str = "private") -> dict:
    return {
        "msg_id": msg_id,
        "uid": "335059272" if not is_bot else "bot",
        "nick": "漂♂总" if not is_bot else "秧秧",
        "group_id": "",
        "channel": channel,
        "text": text,
        "raw_content": text,
        "is_bot": is_bot,
        "created_at": ts,
    }


def test_non_contextual_intent_returns_not_contextual() -> None:
    intent = detect_explicit_memory_intent("记一下：以后迁移包只发私聊")
    result = resolve_recent_context_for_explicit_write(
        intent,
        "记一下：以后迁移包只发私聊",
        [_record("m1", "前文", 1.0)],
    )
    assert result.status == "not_contextual"
    assert result.payload is None


def test_contextual_empty_recent_returns_insufficient_context() -> None:
    intent = detect_explicit_memory_intent("把刚才我们的讨论内容记一下")
    result = resolve_recent_context_for_explicit_write(intent, "把刚才我们的讨论内容记一下", [])
    assert result.status == "insufficient_context"
    assert result.payload is None


def test_discussion_context_resolves_recent_messages_and_evidence() -> None:
    intent = detect_explicit_memory_intent("把刚才我们的讨论内容记一下")
    records = [
        _record("m1", "M2.1 主路径真机通过", 1.0),
        _record("m2", "M2.1 边界真机补测也通过", 2.0),
        _record("m3", "下一步是 M2.2 recent context resolver", 3.0, is_bot=True),
    ]
    result = resolve_recent_context_for_explicit_write(intent, "把刚才我们的讨论内容记一下", records)
    assert result.status == "resolved"
    assert result.payload is not None
    assert "近期讨论要点" in result.payload
    assert "M2.1 主路径真机通过" in result.payload
    assert "M2.1 边界真机补测也通过" in result.payload
    assert "M2.2 recent context resolver" not in result.payload
    assert result.used_msg_ids == ("m1", "m2")
    assert result.context_range["message_count"] == 2
    assert result.context_range["start_ts"] == 1.0
    assert result.context_range["end_ts"] == 2.0
    assert result.context_range["channel"] == "private"
    assert result.context_range["resolver"] == "recent_context_resolver_v1_rules"


def test_conclusion_marker_prefers_conclusion_like_messages() -> None:
    intent = detect_explicit_memory_intent("这个结论记录一下")
    records = [
        _record("m1", "前面只是闲聊一两句", 1.0),
        _record("m2", "当前结论：M2.2-A2 先做规则版，不接 handler", 2.0),
        _record("m3", "下一步：A3 再接 explicit handler pending", 3.0),
        _record("m4", "普通补充：晚上再看", 4.0),
    ]
    result = resolve_recent_context_for_explicit_write(intent, "这个结论记录一下", records)
    assert result.status == "resolved"
    assert result.payload is not None
    assert "近期结论" in result.payload
    assert "当前结论：M2.2-A2" in result.payload
    assert "下一步：A3" in result.payload
    assert "前面只是闲聊" not in result.payload
    assert result.used_msg_ids == ("m2", "m3")


def test_resolver_excludes_current_command_text() -> None:
    command = "把刚才那个记一下"
    intent = detect_explicit_memory_intent(command)
    records = [
        _record("m0", "真正要记录的是 C3.1 stable 已通过", 1.0),
        _record("cmd", command, 2.0),
    ]
    result = resolve_recent_context_for_explicit_write(intent, command, records)
    assert result.status == "resolved"
    assert result.payload is not None
    assert command not in result.payload
    assert result.used_msg_ids == ("m0",)


def test_resolver_excludes_handler_confirmation_reply() -> None:
    intent = detect_explicit_memory_intent("把刚才那个记一下")
    records = [
        _record("m1", "C4 subject guard 真机通过", 1.0),
        _record("m2", "记好了，漂♂总。", 2.0, is_bot=True),
        _record("m3", "好，已经记录。", 3.0, is_bot=True),
    ]
    result = resolve_recent_context_for_explicit_write(intent, "把刚才那个记一下", records)
    assert result.status == "resolved"
    assert result.payload is not None
    assert "C4 subject guard" in result.payload
    assert "记好了" not in result.payload
    assert "已经记录" not in result.payload
    assert result.used_msg_ids == ("m1",)


def test_resolver_noise_filter_keeps_latest_owner_substantive_message() -> None:
    intent = detect_explicit_memory_intent("把刚才我们的讨论内容记一下")
    records = [
        _record("old1", "我晚上喜欢打什么游戏", 1.0),
        _record("bot1", "你晚上喜欢打《绝区零》呀，我记得的。", 2.0, is_bot=True),
        _record("ack", "确认", 3.0),
        _record("bot2", "嗯，记得的——漂♂总晚上喜欢打《绝区零》。", 4.0, is_bot=True),
        _record("new1", "今天 M2.2-A3 接入成功，下一步要做真机灰度", 5.0),
        _record("bot3", "漂♂总好厉害！M2.2-A3接入成功。", 6.0, is_bot=True),
    ]
    result = resolve_recent_context_for_explicit_write(intent, "把刚才我们的讨论内容记一下", records)
    assert result.status == "resolved"
    assert result.payload is not None
    assert result.payload == "今天 M2.2-A3 接入成功，下一步要做真机灰度"
    assert "我晚上喜欢打什么游戏" not in result.payload
    assert "绝区零" not in result.payload
    assert "确认" not in result.payload
    assert "漂♂总好厉害" not in result.payload
    assert result.used_msg_ids == ("new1",)


def test_max_payload_chars_is_enforced() -> None:
    intent = detect_explicit_memory_intent("把刚才我们的讨论内容记一下")
    records = [
        _record("m1", "A" * 100, 1.0),
        _record("m2", "B" * 100, 2.0),
    ]
    result = resolve_recent_context_for_explicit_write(
        intent,
        "把刚才我们的讨论内容记一下",
        records,
        max_payload_chars=40,
    )
    assert result.status == "resolved"
    assert result.payload is not None
    assert len(result.payload) <= 40
    assert result.payload.endswith("…")


def test_detector_integration_for_gangcai_nage() -> None:
    intent = detect_explicit_memory_intent("刚才那个也记一下")
    assert intent.needs_context_resolution is True
    records = [_record("m1", "M2.1 边界真机补测通过", 1.0)]
    result = resolve_recent_context_for_explicit_write(intent, "刚才那个也记一下", records)
    assert result.status == "resolved"
    assert result.payload == "M2.1 边界真机补测通过"
    assert result.used_msg_ids == ("m1",)


def test_deictic_only_context_is_insufficient() -> None:
    intent = detect_explicit_memory_intent("把刚才那个记一下")
    records = [
        _record("m1", "这个", 1.0),
        _record("m2", "那个", 2.0),
        _record("m3", "刚才", 3.0),
    ]
    result = resolve_recent_context_for_explicit_write(intent, "把刚才那个记一下", records)
    assert result.status == "insufficient_context"
    assert result.payload is None
