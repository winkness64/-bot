from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from mock_pipeline_runtime import DictConfig, FakeBot, FakeEvent, FakeSenderInfo, Seg, prepare_modules  # type: ignore


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
    old_cfg = plugin.cfg
    old_store = plugin.store
    old_cooldown = plugin.cooldown
    old_project_root = plugin.PROJECT_ROOT
    old_env = os.environ.get("YANGYANG_DRY_RUN")
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = DictConfig(
                {
                    "owner_uid": "335059272",
                    "owner_uids": ["335059272"],
                    "owner_toolbox_light_workspace_root": tmpdir,
                    "owner_toolbox_light_timeout_seconds": 5,
                    "owner_toolbox_light_max_output_chars": 4000,
                    "owner_engineering_toolbox_enabled": True,
                    "owner_engineering_toolbox_low_risk_enabled": True,
                    "owner_engineering_toolbox_write_enabled": True,
                    "owner_engineering_toolbox_shell_enabled": True,
                    "owner_engineering_toolbox_python_enabled": True,
                    "owner_engineering_toolbox_audit_enabled": False,
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
            plugin.cfg = cfg
            plugin.store = MemoryStore(str(Path(tmpdir) / "chat.db"), str(Path(tmpdir) / "cache"))
            plugin.cooldown = CooldownManager(cfg)
            plugin.PROJECT_ROOT = Path(tmpdir)
            os.environ.pop("YANGYANG_DRY_RUN", None)
            await fn(plugin, Path(tmpdir))
    finally:
        plugin.cfg = old_cfg
        plugin.store = old_store
        plugin.cooldown = old_cooldown
        plugin.PROJECT_ROOT = old_project_root
        if old_env is None:
            os.environ.pop("YANGYANG_DRY_RUN", None)
        else:
            os.environ["YANGYANG_DRY_RUN"] = old_env


def test_plugin_owner_private_slash_toolbox_status() -> None:
    mods = prepare_modules()

    async def scenario(plugin, _tmp_path: Path):
        bot = FakeBot(self_id="90001")
        PrivateFakeEvent, _GroupFakeEvent = _event_classes()
        event = PrivateFakeEvent(
            self_id=bot.self_id,
            user_id="335059272",
            message_id="owner-light-slash-1",
            message=[Seg("text", text="/toolbox status")],
            raw_message="/toolbox status",
            sender=FakeSenderInfo("漂♂总"),
        )
        await plugin.handle_message(bot, event)
        assert bot.group_sent == []
        assert len(bot.private_sent) == 1
        assert bot.private_sent[0][1] == "工具箱正常。"

    _run(_with_plugin_temp_state(mods, scenario))


def test_plugin_group_slash_toolbox_not_visible() -> None:
    mods = prepare_modules()

    async def scenario(plugin, _tmp_path: Path):
        bot = FakeBot(self_id="90001")
        _PrivateFakeEvent, GroupFakeEvent = _event_classes()
        event = GroupFakeEvent(
            self_id=bot.self_id,
            user_id="335059272",
            message_id="owner-light-group-1",
            message=[Seg("text", text="/toolbox status")],
            raw_message="/toolbox status",
            sender=FakeSenderInfo("漂♂总"),
            group_id="137918147",
        )
        await plugin.handle_message(bot, event)
        assert bot.group_sent == []
        assert bot.private_sent == []

    _run(_with_plugin_temp_state(mods, scenario))


def test_plugin_plain_restart_chat_does_not_hit_legacy_toolbox_router(monkeypatch) -> None:
    mods = prepare_modules()
    plugin = mods["plugin"]

    async def should_not_call(*_args, **_kwargs):
        raise AssertionError("legacy engineering toolbox should not run for plain chat")

    monkeypatch.setattr(plugin, "handle_owner_engineering_toolbox_message_nl_async", should_not_call)

    async def scenario(plugin, _tmp_path: Path):
        bot = FakeBot(self_id="90001")
        PrivateFakeEvent, _GroupFakeEvent = _event_classes()
        event = PrivateFakeEvent(
            self_id=bot.self_id,
            user_id="335059272",
            message_id="owner-light-chat-1",
            message=[Seg("text", text="我今天重启了电脑")],
            raw_message="我今天重启了电脑",
            sender=FakeSenderInfo("漂♂总"),
        )

        await plugin.handle_message(bot, event)

        assert bot.group_sent == []
        assert len(bot.private_sent) == 1
        assert "高风险" not in bot.private_sent[0][1]
        msg = SimpleNamespace(
            text="我今天重启了电脑",
            raw_content="我今天重启了电脑",
            uid="335059272",
            channel="private",
            is_owner=True,
            group_id="",
        )
        light = await plugin.handle_owner_toolbox_light_message(msg, plugin.cfg, project_root=plugin.PROJECT_ROOT)
        assert light.handled is False
        assert light.reason == "no_tool_intent"

    _run(_with_plugin_temp_state(mods, scenario))


def test_plugin_owner_private_natural_language_uses_main_router_tool_loop(monkeypatch) -> None:
    mods = prepare_modules()
    plugin = mods["plugin"]
    calls: list[str] = []

    async def fake_tool_loop(_tier, messages, **_kwargs):
        calls.append("tool_loop")
        assert messages[0]["role"] == "system"
        assert "Owner Toolbox" in messages[0]["content"]
        assert any("帮我看一下 tmp 目录有什么" in str(item.get("content", "")) for item in messages)
        return "LLM loop 先处理了。", "fake_tier", [{"tool_name": "list"}]

    async def legacy_light_should_not_run(*_args, **_kwargs):
        calls.append("legacy_light")
        raise AssertionError("legacy Light NL parser must not run for non-slash natural language")

    monkeypatch.setattr(plugin.router, "call_with_tool_loop", fake_tool_loop)
    monkeypatch.setattr(plugin, "handle_owner_toolbox_light_message", legacy_light_should_not_run)

    async def scenario(plugin, _tmp_path: Path):
        bot = FakeBot(self_id="90001")
        PrivateFakeEvent, _GroupFakeEvent = _event_classes()
        event = PrivateFakeEvent(
            self_id=bot.self_id,
            user_id="335059272",
            message_id="owner-light-llm-main-1",
            message=[Seg("text", text="帮我看一下 tmp 目录有什么")],
            raw_message="帮我看一下 tmp 目录有什么",
            sender=FakeSenderInfo("漂♂总"),
        )

        await plugin.handle_message(bot, event)

        assert calls == ["tool_loop"]
        assert bot.group_sent == []
        assert bot.private_sent == [(335059272, "LLM loop 先处理了。")]

    _run(_with_plugin_temp_state(mods, scenario))


def test_plugin_owner_private_no_tool_trace_does_not_fallback_to_light(monkeypatch) -> None:
    mods = prepare_modules()
    plugin = mods["plugin"]
    calls: list[str] = []

    async def fake_tool_loop(_tier, _messages, **_kwargs):
        calls.append("tool_loop")
        return "普通聊天回复。", "fake_tier", []

    async def legacy_light_should_not_run(*_args, **_kwargs):
        calls.append("legacy_light")
        raise AssertionError("legacy Light NL parser must not run after no-tool native loop")

    monkeypatch.setattr(plugin.router, "call_with_tool_loop", fake_tool_loop)
    monkeypatch.setattr(plugin, "handle_owner_toolbox_light_message", legacy_light_should_not_run)

    async def scenario(plugin, _tmp_path: Path):
        bot = FakeBot(self_id="90001")
        PrivateFakeEvent, _GroupFakeEvent = _event_classes()
        event = PrivateFakeEvent(
            self_id=bot.self_id,
            user_id="335059272",
            message_id="owner-light-no-tool-1",
            message=[Seg("text", text="我今天重启了电脑")],
            raw_message="我今天重启了电脑",
            sender=FakeSenderInfo("漂♂总"),
        )

        await plugin.handle_message(bot, event)

        assert calls == ["tool_loop"]
        assert bot.group_sent == []
        assert bot.private_sent == [(335059272, "普通聊天回复。")]

    _run(_with_plugin_temp_state(mods, scenario))

def test_plugin_owner_private_natural_query_tool_loop_max_steps_uses_native_tool_loop(monkeypatch) -> None:
    mods = prepare_modules()
    plugin = mods["plugin"]
    calls: list[tuple[str, object]] = []

    async def fake_tool_loop(_tier, _messages, **kwargs):
        calls.append(("tool_loop", [tool["name"] for tool in kwargs.get("tools", [])]))
        result = kwargs["tool_executor"]("get_tool_loop_max_steps", {})
        assert result.tool_name == "get_tool_loop_max_steps"
        assert result.data["max_steps"] == 9
        return "现在是 9 步。", "fake_tier", [{"tool_name": "get_tool_loop_max_steps"}]

    monkeypatch.setattr(plugin.router, "call_with_tool_loop", fake_tool_loop)

    async def scenario(plugin, _tmp_path: Path):
        plugin.cfg.data["owner_toolbox_light_native_loop_max_steps"] = 9
        bot = FakeBot(self_id="90001")
        PrivateFakeEvent, _GroupFakeEvent = _event_classes()
        event = PrivateFakeEvent(
            self_id=bot.self_id,
            user_id="335059272",
            message_id="owner-max-steps-query-1",
            message=[Seg("text", text="查一下我们工具次数")],
            raw_message="查一下我们工具次数",
            sender=FakeSenderInfo("漂♂总"),
        )
        await plugin.handle_message(bot, event)
        assert calls == [("tool_loop", [tool["name"] for tool in plugin.build_owner_toolbox_tools()])]
        assert "get_tool_loop_max_steps" in calls[0][1]
        assert "set_tool_loop_max_steps" in calls[0][1]
        assert bot.group_sent == []
        assert bot.private_sent == [(335059272, "现在是 9 步。")]

    _run(_with_plugin_temp_state(mods, scenario))


def test_plugin_owner_private_natural_set_tool_loop_max_steps_uses_native_tool_loop(monkeypatch) -> None:
    mods = prepare_modules()
    plugin = mods["plugin"]
    calls: list[str] = []

    async def fake_tool_loop(_tier, _messages, **kwargs):
        calls.append("tool_loop")
        result = kwargs["tool_executor"]("set_tool_loop_max_steps", {"value": "1000000"})
        assert result.tool_name == "set_tool_loop_max_steps"
        assert result.data["max_steps"] == 1000000
        return "已经按你说的改成 1000000 步。", "fake_tier", [{"tool_name": "set_tool_loop_max_steps"}]

    monkeypatch.setattr(plugin.router, "call_with_tool_loop", fake_tool_loop)

    async def scenario(plugin, _tmp_path: Path):
        bot = FakeBot(self_id="90001")
        PrivateFakeEvent, _GroupFakeEvent = _event_classes()
        event = PrivateFakeEvent(
            self_id=bot.self_id,
            user_id="335059272",
            message_id="owner-max-steps-set-1",
            message=[Seg("text", text="把工具调用上限改成 1000000")],
            raw_message="把工具调用上限改成 1000000",
            sender=FakeSenderInfo("漂♂总"),
        )
        await plugin.handle_message(bot, event)
        assert calls == ["tool_loop"]
        assert bot.group_sent == []
        assert bot.private_sent == [(335059272, "已经按你说的改成 1000000 步。")]
        assert plugin.cfg.get("owner_toolbox_light_native_loop_max_steps") == 1000000

    _run(_with_plugin_temp_state(mods, scenario))

def test_plugin_group_and_non_owner_max_steps_natural_not_handled(monkeypatch) -> None:
    mods = prepare_modules()
    plugin = mods["plugin"]
    calls: list[str] = []

    async def fake_tool_loop(_tier, _messages, **_kwargs):
        calls.append("tool_loop")
        return "不应进入 owner 工具 loop。", "fake_tier", []

    async def fake_normal_call(_tier, _messages, **_kwargs):
        calls.append("normal_call")
        return "普通回复。", "fake_tier"

    monkeypatch.setattr(plugin.router, "call_with_tool_loop", fake_tool_loop)
    monkeypatch.setattr(plugin.router, "call", fake_normal_call)

    async def scenario(plugin, _tmp_path: Path):
        bot = FakeBot(self_id="90001")
        PrivateFakeEvent, GroupFakeEvent = _event_classes()
        group_event = GroupFakeEvent(
            self_id=bot.self_id,
            user_id="335059272",
            message_id="group-max-steps-1",
            message=[Seg("text", text="当前工具调用上限是多少")],
            raw_message="当前工具调用上限是多少",
            sender=FakeSenderInfo("漂♂总"),
            group_id="137918147",
        )
        non_owner_event = PrivateFakeEvent(
            self_id=bot.self_id,
            user_id="10086",
            message_id="non-owner-max-steps-1",
            message=[Seg("text", text="把工具调用上限改成 15")],
            raw_message="把工具调用上限改成 15",
            sender=FakeSenderInfo("路人"),
        )

        await plugin.handle_message(bot, group_event)
        await plugin.handle_message(bot, non_owner_event)

        assert bot.group_sent == []
        assert bot.private_sent == [(10086, "普通回复。")]
        assert "15" not in bot.private_sent[0][1]
        assert "工具" not in bot.private_sent[0][1]
        assert plugin.cfg.get("owner_toolbox_light_native_loop_max_steps", None) in (None, 5)
        assert calls == ["normal_call"]

    _run(_with_plugin_temp_state(mods, scenario))



def test_plugin_owner_toolbox_assistant_prelude_strips_role_prefix(monkeypatch) -> None:
    mods = prepare_modules()
    plugin = mods["plugin"]

    async def fake_tool_loop(_tier, _messages, **kwargs):
        progress = kwargs.get("progress_callback")
        assert progress is not None
        await progress("assistant_prelude", {"step": 1, "text": "秧秧: 好嘞漂♂总，我先看看冷备目录现在有什么，再动手～", "tool_call_count": 1})
        return "看完了，冷备目录里现在有这些。", "fake_tier", [{"tool_name": "list"}]

    monkeypatch.setattr(plugin.router, "call_with_tool_loop", fake_tool_loop)

    async def scenario(plugin, _tmp_path: Path):
        bot = FakeBot(self_id="90001")
        PrivateFakeEvent, _GroupFakeEvent = _event_classes()
        event = PrivateFakeEvent(
            self_id=bot.self_id,
            user_id="335059272",
            message_id="owner-prelude-prefix-1",
            message=[Seg("text", text="看一下冷备目录")],
            raw_message="看一下冷备目录",
            sender=FakeSenderInfo("漂♂总"),
        )
        await plugin.handle_message(bot, event)
        assert bot.group_sent == []
        assert bot.private_sent == [
            (335059272, "好嘞漂♂总，我先看看冷备目录现在有什么，再动手～"),
            (335059272, "看完了，冷备目录里现在有这些。"),
        ]

    _run(_with_plugin_temp_state(mods, scenario))
