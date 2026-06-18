from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MOCK_PATH = ROOT / "tests" / "mock_pipeline_runtime.py"
SPEC = importlib.util.spec_from_file_location("mock_pipeline_runtime_for_i_line_p0", MOCK_PATH)
assert SPEC is not None and SPEC.loader is not None
mock_pipeline = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = mock_pipeline
SPEC.loader.exec_module(mock_pipeline)


DictConfig = mock_pipeline.DictConfig
FakeBot = mock_pipeline.FakeBot
FakeEvent = mock_pipeline.FakeEvent
FakeSenderInfo = mock_pipeline.FakeSenderInfo
Seg = mock_pipeline.Seg


def _run(coro):
    return asyncio.run(coro)


def _event_classes():
    v11 = sys.modules["nonebot.adapters.onebot.v11"]

    class PrivateFakeEvent(FakeEvent, v11.PrivateMessageEvent):
        pass

    class GroupFakeEvent(FakeEvent, v11.GroupMessageEvent):
        pass

    return PrivateFakeEvent, GroupFakeEvent


async def _with_plugin_temp_state(mods: dict, fn):
    plugin = mods["plugin"]
    MemoryStore = mods["MemoryStore"]
    CooldownManager = mods["CooldownManager"]
    ModelRouter = mods["ModelRouter"]
    old_cfg = plugin.cfg
    old_store = plugin.store
    old_cooldown = plugin.cooldown
    old_router = plugin.router
    old_env = os.environ.get("YANGYANG_DRY_RUN")
    cfg = DictConfig(
        {
            "owner_uid": "335059272",
            "owner_uids": ["335059272"],
            "dry_run": False,
            "memory_short_term_capture_enabled": False,
            "memory_prompt_injection_enabled": False,
            "behavior": {
                "cooldown_global_s": 0,
                "cooldown_topic_rounds": 0,
                "cooldown_topic_s": 0,
                "daily_auto_reply_limit": 0,
                "bot_loop_enabled": True,
                "bot_loop_recent_limit": 8,
                "bot_loop_min_bot_messages": 3,
                "bot_loop_cooldown_seconds": 30,
            },
        }
    )
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            plugin.cfg = cfg
            plugin.store = MemoryStore(str(Path(tmpdir) / "chat.db"), str(Path(tmpdir) / "cache"))
            plugin.cooldown = CooldownManager(cfg)
            plugin.router = ModelRouter(cfg)
            os.environ.pop("YANGYANG_DRY_RUN", None)
            await fn(plugin)
    finally:
        plugin.cfg = old_cfg
        plugin.store = old_store
        plugin.cooldown = old_cooldown
        plugin.router = old_router
        if old_env is None:
            os.environ.pop("YANGYANG_DRY_RUN", None)
        else:
            os.environ["YANGYANG_DRY_RUN"] = old_env


def test_i_line_p0_plugin_owner_private_slash_roundtrip_current_session() -> None:
    mods = mock_pipeline.prepare_modules()

    async def scenario(plugin):
        bot = FakeBot(self_id="90001")
        PrivateFakeEvent, _GroupFakeEvent = _event_classes()
        event = PrivateFakeEvent(
            self_id=bot.self_id,
            user_id="335059272",
            message_id="i-p0-owner-1",
            message=[Seg("text", text="/i叔 health")],
            raw_message="/i叔 health",
            sender=FakeSenderInfo("阿漂"),
        )

        await plugin.handle_message(bot, event)

        assert bot.group_sent == []
        assert len(bot.private_sent) == 1
        assert bot.private_sent[0][0] == 335059272
        reply = bot.private_sent[0][1]
        assert "I叔 P0 闭环已跑通" in reply
        assert "TaskRequest -> Isaac worker -> TaskResult" in reply
        assert "executor_enabled=false" in reply
        assert "host_action_executed=false" in reply
        rows = plugin.store.get_recent_messages("", limit=10, channel=None)
        assert any(row["is_bot"] == 1 and "I叔 P0 闭环已跑通" in row["text"] for row in rows)
        isaac_results = [getattr(obj, "isaac_p0_result", None) for obj in []]
        assert isaac_results == []

    _run(_with_plugin_temp_state(mods, scenario))


def test_i_line_p0_plugin_non_owner_private_does_not_expose_isaac() -> None:
    mods = mock_pipeline.prepare_modules()

    async def scenario(plugin):
        bot = FakeBot(self_id="90001")
        PrivateFakeEvent, _GroupFakeEvent = _event_classes()
        event = PrivateFakeEvent(
            self_id=bot.self_id,
            user_id="10086",
            message_id="i-p0-non-owner-1",
            message=[Seg("text", text="/i叔 health")],
            raw_message="/i叔 health",
            sender=FakeSenderInfo("路人"),
        )

        await plugin.handle_message(bot, event)

        assert bot.group_sent == []
        if bot.private_sent:
            assert all("I叔" not in sent[1] and "Isaac" not in sent[1] and "TaskRequest" not in sent[1] for sent in bot.private_sent)
        rows = plugin.store.get_recent_messages("", limit=20, channel=None)
        assert not any(row["is_bot"] == 1 and "I叔" in row["text"] for row in rows)
        assert not any(row["is_bot"] == 1 and "TaskRequest" in row["text"] for row in rows)

    _run(_with_plugin_temp_state(mods, scenario))


def test_i_line_p0_plugin_owner_group_does_not_expose_isaac() -> None:
    mods = mock_pipeline.prepare_modules()

    async def scenario(plugin):
        bot = FakeBot(self_id="90001")
        _PrivateFakeEvent, GroupFakeEvent = _event_classes()
        event = GroupFakeEvent(
            self_id=bot.self_id,
            user_id="335059272",
            message_id="i-p0-owner-group-1",
            message=[Seg("text", text="/i叔 health")],
            raw_message="/i叔 health",
            sender=FakeSenderInfo("阿漂"),
            group_id="137918147",
        )

        await plugin.handle_message(bot, event)

        assert bot.group_sent == []
        assert bot.private_sent == []
        rows = plugin.store.get_recent_messages("137918147", limit=20, channel="group")
        assert not any(row["is_bot"] == 1 and "I叔" in row["text"] for row in rows)

    _run(_with_plugin_temp_state(mods, scenario))


def test_i_line_p0_plugin_owner_private_bare_i_uncle_uses_native_tool_loop(monkeypatch) -> None:
    mods = mock_pipeline.prepare_modules()
    calls: list[str] = []

    async def scenario(plugin):
        async def fake_tool_loop(_tier, _messages, **_kwargs):
            calls.append("tool_loop")
            return "走正常主链路。", "fake_tier", [{}]

        monkeypatch.setattr(plugin.router, "call_with_tool_loop", fake_tool_loop)

        bot = FakeBot(self_id="90001")
        PrivateFakeEvent, _GroupFakeEvent = _event_classes()
        event = PrivateFakeEvent(
            self_id=bot.self_id,
            user_id="335059272",
            message_id="i-p0-owner-bare-1",
            message=[Seg("text", text="I叔 帮我看看状态")],
            raw_message="I叔 帮我看看状态",
            sender=FakeSenderInfo("阿漂"),
        )

        await plugin.handle_message(bot, event)

        assert calls == ["tool_loop"]
        assert bot.group_sent == []
        assert bot.private_sent == [(335059272, "走正常主链路。")]

    _run(_with_plugin_temp_state(mods, scenario))



def test_i_line_p0_plugin_internal_sse_route_handler_exists_and_keeps_response_model_none_guard() -> None:
    mods = mock_pipeline.prepare_modules()
    plugin = mods["plugin"]

    handler = getattr(plugin, "_yy_internal_chat_send_stream", None)

    assert handler is not None
    assert handler.__name__ == "_yy_internal_chat_send_stream"

    source = Path(plugin.__file__).read_text(encoding="utf-8")
    assert "@app.post('/yy/api/chat/send_stream', response_model=None)" in source



def test_i_line_p0_plugin_internal_sse_route_rejects_non_loopback() -> None:
    mods = mock_pipeline.prepare_modules()
    plugin = mods["plugin"]

    class FakeClient:
        host = "10.0.0.1"

    class FakeRequest:
        client = FakeClient()
        headers = {}

        async def json(self):
            return {"text": "hello"}

    async def scenario(_plugin):
        handler = getattr(plugin, "_yy_internal_chat_send_stream")
        response = await handler(FakeRequest())
        assert response.status_code == 403
        assert b"forbidden" in response.body

    _run(_with_plugin_temp_state(mods, scenario))


def test_i_line_p0_plugin_internal_sse_route_streams_events(monkeypatch) -> None:
    mods = mock_pipeline.prepare_modules()
    plugin = mods["plugin"]

    class FakeClient:
        host = "127.0.0.1"

    class FakeRequest:
        client = FakeClient()
        headers = {}

        async def json(self):
            return {"text": "test", "session_id": "sse_test_1", "scope": "private"}

    async def scenario(_plugin):
        async def fake_call(tier, messages, **kwargs):
            callback = kwargs.get("stream_callback")
            if callback is not None:
                await callback("阿漂", {"seq": 1})
                await callback(" 收到", {"seq": 2})
            _plugin.router.last_call_request_id = "req_stream_1"
            _plugin.router.last_call_resolved_profile = "v4_flash"
            _plugin.router.last_call_fallback_used = False
            _plugin.router.last_call_fallback_from = ""
            _plugin.router.last_call_fallback_to = ""
            _plugin.router.last_call_fallback_reason = ""
            return "阿漂 收到", "v4_flash"

        monkeypatch.setattr(_plugin.router, "call", fake_call)
        handler = getattr(_plugin, "_yy_internal_chat_send_stream")
        response = await handler(FakeRequest())
        assert response.media_type == "text/event-stream"
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk.decode("utf-8"))
        body = "".join(chunks)
        assert "event: proxy_open" in body
        assert "event: session_id" in body
        assert "event: plain" in body
        assert "event: agent_stats" in body
        assert "event: end" in body
        assert "event: proxy_closed" in body
        assert "sse_test_1" in body
        assert "req_stream_1" in body

    _run(_with_plugin_temp_state(mods, scenario))
