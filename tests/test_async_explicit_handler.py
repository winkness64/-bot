from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from mock_pipeline_runtime import prepare_modules  # type: ignore


mods = prepare_modules()
MemoryStore = mods["MemoryStore"]

from plugins.yangyang.core.event_adapter import Message
from plugins.yangyang.memory.explicit_handler import (
    clear_explicit_memory_pending,
    handle_explicit_memory_message,
    handle_explicit_memory_message_async,
    has_explicit_memory_pending,
)


ENABLED_CONFIG = {
    "memory_topic_boundary_enabled": True,
    "memory_topic_boundary_private_enabled": True,
    "memory_topic_boundary_model_tier": "v4_flash",
    "memory_topic_boundary_timeout_seconds": 1.0,
    "memory_topic_boundary_max_records": 16,
    "memory_topic_boundary_max_payload_chars": 500,
    "memory_topic_boundary_min_confidence": 0.65,
}
DISABLED_CONFIG = {"memory_topic_boundary_enabled": False}


class FakeAsyncRouter:
    def __init__(self, result: Any = "", *, error: Exception | None = None):
        self.result = result
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def call(self, *, tier: str, messages: list[dict[str, str]]) -> Any:
        self.calls.append({"tier": tier, "messages": messages})
        if self.error is not None:
            raise self.error
        return self.result


def _build_store(tmpdir: str):
    return MemoryStore(str(Path(tmpdir) / "chat.db"), str(Path(tmpdir) / "cache"))


def _message(
    text: str,
    *,
    uid: str = "335059272",
    channel: str = "private",
    is_owner: bool = True,
    msg_id: str | None = None,
    timestamp: float = 1717400000.0,
) -> Message:
    return Message(
        msg_id=msg_id or f"msg_{abs(hash((text, uid, channel))) % 100000}",
        uid=uid,
        nick="阿漂" if uid == "335059272" else uid,
        group_id="137918147" if channel == "group" else "",
        channel=channel,
        text=text,
        raw_content=text,
        is_at_bot=False,
        is_at_owner=False,
        is_quote_bot=False,
        quote_target_msg_id=None,
        is_owner=is_owner,
        timestamp=timestamp,
    )


def _record_recent(
    store,
    msg_id: str,
    text: str,
    *,
    created_at: float,
    uid: str = "335059272",
    is_bot: bool = False,
) -> None:
    store.record_message(
        _message(
            text,
            uid="yangyang_bot" if is_bot else uid,
            is_owner=False if is_bot else uid == "335059272",
            msg_id=msg_id,
            timestamp=created_at,
        ),
        is_bot=is_bot,
    )
    with store._connect() as conn:
        conn.execute(
            "UPDATE messages SET created_at=? WHERE msg_id=?",
            (float(created_at), msg_id),
        )


def _topic_json_response(**kwargs: Any) -> str:
    return json.dumps(kwargs, ensure_ascii=False)


def test_async_wrapper_config_none_direct_write_matches_sync_without_router() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as async_tmp, tempfile.TemporaryDirectory() as sync_tmp:
        async_store = _build_store(async_tmp)
        sync_store = _build_store(sync_tmp)
        msg = _message("记一下：async wrapper 默认关闭走同步 direct write", msg_id="cmd_direct")

        async_result = asyncio.run(
            handle_explicit_memory_message_async(
                msg,
                async_store,
                session_id="private:335059272",
                config=None,
                router=None,
                now=1000,
            )
        )
        sync_result = handle_explicit_memory_message(
            msg,
            sync_store,
            session_id="private:335059272",
            now=1000,
        )
        async_rows = async_store.load_long_term_entries(scope="private_user", scope_id="335059272")
        sync_rows = sync_store.load_long_term_entries(scope="private_user", scope_id="335059272")

        assert async_result.handled == sync_result.handled is True
        assert async_result.action == sync_result.action == "direct_write"
        assert async_result.reply == sync_result.reply
        assert len(async_rows) == len(sync_rows) == 1
        assert async_rows[0].value == sync_rows[0].value == "async wrapper 默认关闭走同步 direct write"
        assert async_rows[0].source == sync_rows[0].source == "owner_command"


def test_async_wrapper_config_disabled_contextual_uses_rules_and_does_not_call_router() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record_recent(store, "r1", "disabled config 仍走 A3.1 规则版", created_at=100.0)
        _record_recent(store, "r2", "fake router 不能被调用", created_at=101.0)
        router = FakeAsyncRouter("should not be used")

        result = asyncio.run(
            handle_explicit_memory_message_async(
                _message("把刚才我们的讨论内容记一下", msg_id="cmd_disabled", timestamp=102.0),
                store,
                session_id="private:335059272",
                config=DISABLED_CONFIG,
                router=router,
                now=1000,
            )
        )

        assert result.handled is True
        assert result.action == "pending_context_confirmation"
        assert "近期讨论要点" in result.reply
        assert "disabled config 仍走 A3.1 规则版" in result.reply
        assert router.calls == []
        assert store.load_long_term_entries(scope="private_user", scope_id="335059272") == []
        assert has_explicit_memory_pending("private:335059272", "335059272") is True


def test_async_wrapper_enabled_fake_router_resolved_then_confirm_writes_topic_evidence() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record_recent(store, "r_old", "旧主题：不要选这个", created_at=100.0)
        _record_recent(store, "r_b1", "B2-B2-B 新增 async wrapper", created_at=101.0)
        _record_recent(store, "r_b2", "默认关闭，只有 config enabled 加 router 才走 async topic boundary", created_at=102.0)
        fake_payload = "B2-B2-B async wrapper 只在 config enabled + router 时使用 fake topic boundary"
        router = FakeAsyncRouter(
            _topic_json_response(
                ok=True,
                status="resolved",
                payload=fake_payload,
                confidence=0.96,
                start_msg_id="r_b1",
                end_msg_id="r_b2",
                used_msg_ids=["r_b1", "r_b2"],
                reason="fake async router selected wrapper topic",
            )
        )
        command = "把刚才我们的讨论内容记一下"

        first = asyncio.run(
            handle_explicit_memory_message_async(
                _message(command, msg_id="cmd_async_resolved", timestamp=103.0),
                store,
                session_id="private:335059272",
                config=ENABLED_CONFIG,
                router=router,
                now=1000,
            )
        )
        second = asyncio.run(
            handle_explicit_memory_message_async(
                _message("确认", msg_id="cmd_async_confirm", timestamp=104.0),
                store,
                session_id="private:335059272",
                config=ENABLED_CONFIG,
                router=router,
                now=1005,
            )
        )
        rows = store.load_long_term_entries(scope="private_user", scope_id="335059272")

        assert first.handled is True
        assert first.action == "pending_topic_boundary_confirmation"
        assert fake_payload in first.reply
        assert second.handled is True
        assert second.action == "confirmed_write"
        assert len(router.calls) == 1
        assert router.calls[0]["tier"] == "v4_flash"
        assert "话题边界解析器" in router.calls[0]["messages"][0]["content"]
        assert command in router.calls[0]["messages"][1]["content"]
        assert len(rows) == 1
        assert rows[0].source == "explicit_context_resolved"
        assert rows[0].value == fake_payload
        evidence = json.loads(rows[0].evidence[0].text)
        assert evidence["resolver"] == "topic_boundary_resolver_v1_mockable"
        assert evidence["used_msg_ids"] == ["r_b1", "r_b2"]
        assert evidence["context_range"]["resolver"] == "topic_boundary_resolver_v1_mockable"
        assert evidence["context_range"]["start_msg_id"] == "r_b1"
        assert evidence["context_range"]["end_msg_id"] == "r_b2"
        assert "fake async router" in evidence["resolution_reason"]
        assert has_explicit_memory_pending("private:335059272", "335059272") is False


def test_async_wrapper_enabled_fake_router_ambiguous_does_not_fallback_or_write() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record_recent(store, "r1", "话题一：A3.1 规则版其实能生成摘要", created_at=100.0)
        _record_recent(store, "r2", "话题二：B2-B2-B async router ambiguous", created_at=101.0)
        router = FakeAsyncRouter(
            _topic_json_response(
                ok=False,
                status="ambiguous",
                payload=None,
                confidence=0.33,
                start_msg_id=None,
                end_msg_id=None,
                used_msg_ids=[],
                reason="窗口内多个话题，无法确认",
            )
        )

        result = asyncio.run(
            handle_explicit_memory_message_async(
                _message("把刚才那个记一下", msg_id="cmd_async_ambiguous", timestamp=102.0),
                store,
                session_id="private:335059272",
                config=ENABLED_CONFIG,
                router=router,
                now=1000,
            )
        )

        assert result.handled is True
        assert result.action == "topic_boundary_ambiguous"
        assert "不止一段话题" in result.reply or "点明" in result.reply
        assert len(router.calls) == 1
        assert store.load_long_term_entries(scope="private_user", scope_id="335059272") == []
        assert has_explicit_memory_pending("private:335059272", "335059272") is False


def test_async_wrapper_enabled_fake_router_bad_json_falls_back_to_rules() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record_recent(store, "r1", "bad JSON fallback 应保留基础功能", created_at=100.0)
        _record_recent(store, "r2", "A3.1 规则版能 pending 规则 payload", created_at=101.0)
        router = FakeAsyncRouter("这不是 JSON")

        result = asyncio.run(
            handle_explicit_memory_message_async(
                _message("把刚才我们的讨论内容记一下", msg_id="cmd_async_bad_json", timestamp=102.0),
                store,
                session_id="private:335059272",
                config=ENABLED_CONFIG,
                router=router,
                now=1000,
            )
        )

        assert result.handled is True
        assert result.action == "pending_context_confirmation"
        assert "近期讨论要点" in result.reply
        assert "bad JSON fallback 应保留基础功能" in result.reply
        assert "这不是 JSON" not in result.reply
        assert len(router.calls) == 1
        assert store.load_long_term_entries(scope="private_user", scope_id="335059272") == []
        assert has_explicit_memory_pending("private:335059272", "335059272") is True


def test_async_wrapper_enabled_fake_router_raises_falls_back_to_rules() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record_recent(store, "r1", "router raises fallback 不能崩", created_at=100.0)
        _record_recent(store, "r2", "仍应 pending A3.1 规则 payload", created_at=101.0)
        router = FakeAsyncRouter(error=RuntimeError("fake async router boom"))

        result = asyncio.run(
            handle_explicit_memory_message_async(
                _message("把刚才我们的讨论内容记一下", msg_id="cmd_async_error", timestamp=102.0),
                store,
                session_id="private:335059272",
                config=ENABLED_CONFIG,
                router=router,
                now=1000,
            )
        )

        assert result.handled is True
        assert result.action == "pending_context_confirmation"
        assert "近期讨论要点" in result.reply
        assert "router raises fallback 不能崩" in result.reply
        assert len(router.calls) == 1
        assert store.load_long_term_entries(scope="private_user", scope_id="335059272") == []
        assert has_explicit_memory_pending("private:335059272", "335059272") is True


def test_async_wrapper_group_message_passes_and_does_not_call_router() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        router = FakeAsyncRouter("should not be used")

        result = asyncio.run(
            handle_explicit_memory_message_async(
                _message("把刚才我们的讨论内容记一下", channel="group", is_owner=True, msg_id="cmd_group"),
                store,
                session_id="group:137918147",
                config=ENABLED_CONFIG,
                router=router,
                now=1000,
            )
        )

        assert result.handled is False
        assert result.action == "pass_non_owner_or_non_private"
        assert router.calls == []
        assert store.load_long_term_entries() == []
        assert has_explicit_memory_pending("group:137918147", "335059272") is False


def test_async_wrapper_non_owner_private_passes_and_does_not_call_router() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        router = FakeAsyncRouter("should not be used")

        result = asyncio.run(
            handle_explicit_memory_message_async(
                _message(
                    "把刚才我们的讨论内容记一下",
                    uid="123456",
                    is_owner=False,
                    msg_id="cmd_non_owner_private",
                ),
                store,
                session_id="private:123456",
                config=ENABLED_CONFIG,
                router=router,
                now=1000,
            )
        )

        assert result.handled is False
        assert result.action == "pass_non_owner_or_non_private"
        assert router.calls == []
        assert store.load_long_term_entries() == []
        assert has_explicit_memory_pending("private:123456", "123456") is False
