from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

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
    old_env = os.environ.get("YANGYANG_DRY_RUN")
    cfg = DictConfig(
        {
            "owner_uid": "335059272",
            "owner_uids": ["335059272"],
            "dry_run": False,
            "owner_engineering_toolbox_enabled": True,
            "owner_engineering_toolbox_low_risk_enabled": True,
            "owner_engineering_toolbox_write_enabled": True,
            "owner_engineering_toolbox_shell_enabled": True,
            "owner_engineering_toolbox_python_enabled": True,
            "owner_engineering_toolbox_audit_enabled": True,
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
            os.environ.pop("YANGYANG_DRY_RUN", None)
            plugin.PROJECT_ROOT = Path(tmpdir)
            await fn(plugin)
    finally:
        plugin.cfg = old_cfg
        plugin.store = old_store
        plugin.cooldown = old_cooldown
        if old_env is None:
            os.environ.pop("YANGYANG_DRY_RUN", None)
        else:
            os.environ["YANGYANG_DRY_RUN"] = old_env


def test_plugin_owner_private_toolbox_status_replies_current_session() -> None:
    mods = prepare_modules()

    async def scenario(plugin):
        bot = FakeBot(self_id="90001")
        PrivateFakeEvent, _GroupFakeEvent = _event_classes()
        event = PrivateFakeEvent(
            self_id=bot.self_id,
            user_id="335059272",
            message_id="toolbox-owner-1",
            message=[Seg("text", text="工具箱 status")],
            raw_message="工具箱 status",
            sender=FakeSenderInfo("漂♂总"),
        )

        await plugin.handle_message(bot, event)

        assert bot.group_sent == []
        assert len(bot.private_sent) == 1
        reply = bot.private_sent[0][1]
        # M3 redo: 默认 status 走"人话一句"，不要再像 OA 风控小黑框
        assert reply == "工具箱正常。"
        assert "[owner_toolbox]" not in reply
        assert "仅 owner 私聊可用" not in reply
        assert "[owner_toolbox]" not in reply
        assert "owner_private_only=" not in reply

    _run(_with_plugin_temp_state(mods, scenario))


def test_plugin_non_owner_private_toolbox_is_rejected_without_tool_details() -> None:
    mods = prepare_modules()

    async def scenario(plugin):
        bot = FakeBot(self_id="90001")
        PrivateFakeEvent, _GroupFakeEvent = _event_classes()
        event = PrivateFakeEvent(
            self_id=bot.self_id,
            user_id="10086",
            message_id="toolbox-non-owner-1",
            message=[Seg("text", text="工具箱 status")],
            raw_message="工具箱 status",
            sender=FakeSenderInfo("路人"),
        )

        await plugin.handle_message(bot, event)

        assert bot.group_sent == []
        assert len(bot.private_sent) == 1
        reply = bot.private_sent[0][1]
        assert "owner 私聊" in reply
        assert "owner_private_only" not in reply
        assert "workspace_root=" not in reply
        assert "[owner_toolbox]" not in reply

    _run(_with_plugin_temp_state(mods, scenario))


def test_plugin_owner_group_toolbox_is_not_visible() -> None:
    mods = prepare_modules()

    async def scenario(plugin):
        bot = FakeBot(self_id="90001")
        _PrivateFakeEvent, GroupFakeEvent = _event_classes()
        event = GroupFakeEvent(
            self_id=bot.self_id,
            user_id="335059272",
            message_id="toolbox-group-1",
            message=[Seg("text", text="工具箱 status")],
            raw_message="工具箱 status",
            sender=FakeSenderInfo("漂♂总"),
            group_id="137918147",
        )

        await plugin.handle_message(bot, event)

        assert bot.group_sent == []
        assert bot.private_sent == []

    _run(_with_plugin_temp_state(mods, scenario))
