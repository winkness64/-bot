from __future__ import annotations

import asyncio
from dataclasses import dataclass

from conftest import run
from mock_pipeline_runtime import DictConfig, prepare_modules  # type: ignore


@dataclass
class SimpleMessage:
    channel: str
    uid: str = "12345"
    group_id: str = "67890"


@dataclass
class SimpleDraft:
    destination_type: str
    destination_id: str | None
    action_type: str
    content_preview: str
    status: str = "drafted"


@dataclass
class SimpleAction:
    action_type: str


@dataclass
class SimplePlan:
    destination_type: str
    destination_id: str | None


class MockBot:
    def __init__(self, fail: bool = False, call_api_fail: bool = False):
        self.fail = fail
        self.call_api_fail = call_api_fail
        self.calls: list[tuple[object, str]] = []
        self.api_calls: list[tuple[str, dict]] = []
        self.self_id = '114514'

    async def send(self, event, message: str):
        self.calls.append((event, message))
        if self.fail:
            raise RuntimeError("boom")
        return {"message_id": 1}

    async def call_api(self, name: str, **kwargs):
        self.api_calls.append((name, kwargs))
        if self.call_api_fail:
            raise RuntimeError("forward boom")
        return {"message_id": 2}


class MockEvent:
    def __init__(self, *, group_id: int | None = None, user_id: int | None = None):
        self.group_id = group_id
        self.user_id = user_id

    def dict(self):
        data = {}
        if self.group_id is not None:
            data['group_id'] = self.group_id
        if self.user_id is not None:
            data['user_id'] = self.user_id
        return data


class TrackingAdapter:
    def __init__(self):
        self.calls: list[tuple[object, str]] = []

    async def send_current_session(self, message, content: str):
        self.calls.append((message, content))
        raise AssertionError("adapter should not be called")


async def _test_nonebot_adapter_success(mods: dict) -> None:
    Adapter = mods["NoneBotCurrentSessionSenderAdapter"]
    message = SimpleMessage(channel="group", group_id="31003", uid="335059272")
    bot = MockBot()
    event = MockEvent()
    adapter = Adapter(bot=bot, event=event)

    result = await adapter.send_current_session(message, "收到，当前会话回复")

    assert result.attempted is True
    assert result.delivered is True
    assert result.real_send is True
    assert result.destination_type == "current_session"
    assert result.destination_id == "group:31003"
    assert bot.calls == [(event, "收到，当前会话回复")]
    print("[PASS] nonebot current-session adapter success")


async def _test_nonebot_adapter_empty_content_blocked(mods: dict) -> None:
    Adapter = mods["NoneBotCurrentSessionSenderAdapter"]
    message = SimpleMessage(channel="private", uid="335059272")
    bot = MockBot()
    event = MockEvent()
    adapter = Adapter(bot=bot, event=event)

    result = await adapter.send_current_session(message, "   ")

    assert result.attempted is False
    assert result.delivered is False
    assert result.reason == "empty_content"
    assert result.real_send is False
    assert bot.calls == []
    print("[PASS] nonebot current-session adapter empty content blocked")


async def _test_nonebot_adapter_send_failed(mods: dict) -> None:
    Adapter = mods["NoneBotCurrentSessionSenderAdapter"]
    message = SimpleMessage(channel="group", group_id="31003", uid="335059272")
    bot = MockBot(fail=True)
    event = MockEvent()
    adapter = Adapter(bot=bot, event=event)

    result = await adapter.send_current_session(message, "测试失败")

    assert result.attempted is True
    assert result.delivered is False
    assert result.real_send is False
    assert result.mode == "send_failed"
    assert "send_failed:RuntimeError:boom" in result.reason
    assert bot.calls == [(event, "测试失败")]
    print("[PASS] nonebot current-session adapter send failure handled")




async def _test_nonebot_adapter_long_text_forward_fallback(mods: dict) -> None:
    Adapter = mods["NoneBotCurrentSessionSenderAdapter"]
    message = SimpleMessage(channel="private", uid="335059272")
    bot = MockBot(call_api_fail=True)
    event = MockEvent(user_id=335059272)
    adapter = Adapter(bot=bot, event=event)

    long_text = ("漂♂总在冒烟\n" * 400).strip()
    result = await adapter.send_current_session(message, long_text)

    assert result.attempted is True
    assert result.delivered is True
    assert result.real_send is True
    assert result.mode == "nonebot_chunked_text"
    assert result.reason == "chunked_fallback"
    assert bot.api_calls and bot.api_calls[0][0] == "send_private_forward_msg"
    assert len(bot.calls) >= 2
    print("[PASS] nonebot current-session adapter long text fallback to chunked")


async def _test_nonebot_adapter_long_text_forward_success(mods: dict) -> None:
    Adapter = mods["NoneBotCurrentSessionSenderAdapter"]
    message = SimpleMessage(channel="private", uid="335059272")
    bot = MockBot()
    event = MockEvent(user_id=335059272)
    adapter = Adapter(bot=bot, event=event)

    long_text = ("合并转发测试\n" * 400).strip()
    result = await adapter.send_current_session(message, long_text)

    assert result.attempted is True
    assert result.delivered is True
    assert result.real_send is True
    assert result.mode == "nonebot_forward_private"
    assert result.reason == "forward_sent"
    assert bot.api_calls and bot.api_calls[0][0] == "send_private_forward_msg"
    assert len(bot.calls) == 1
    assert bot.calls[0][0] is event
    assert "长消息发送中，请稍等" in bot.calls[0][1]
    print("[PASS] nonebot current-session adapter long text forward success")

async def _test_delivery_dry_run_not_call_adapter(mods: dict) -> None:
    deliver = mods["deliver_owner_action_reply_draft"]
    tracking = TrackingAdapter()
    result = await deliver(
        SimpleDraft("current_session", "group:31003", "reply_current", "dry run text"),
        SimpleAction("reply_current"),
        gate=None,
        plan=SimplePlan("current_session", "group:31003"),
        message=SimpleMessage(channel="group", group_id="31003", uid="335059272"),
        config=DictConfig(
            {
                "dry_run": True,
                "owner_action_execution_enabled": True,
                "owner_action_allow_reply_current": True,
                "owner_action_current_session_delivery_enabled": True,
            }
        ),
        sender=tracking,
    )

    assert result.mode == "dry_run"
    assert result.delivered is False
    assert tracking.calls == []
    print("[PASS] delivery dry_run does not call adapter")


async def _test_delivery_config_disabled_not_call_adapter(mods: dict) -> None:
    deliver = mods["deliver_owner_action_reply_draft"]
    tracking = TrackingAdapter()
    result = await deliver(
        SimpleDraft("current_session", "group:31003", "reply_current", "config off text"),
        SimpleAction("reply_current"),
        gate=None,
        plan=SimplePlan("current_session", "group:31003"),
        message=SimpleMessage(channel="group", group_id="31003", uid="335059272"),
        config=DictConfig(
            {
                "dry_run": False,
                "owner_action_execution_enabled": True,
                "owner_action_allow_reply_current": True,
                "owner_action_current_session_delivery_enabled": False,
            }
        ),
        sender=tracking,
    )

    assert result.mode == "disabled"
    assert result.reason == "current_session_delivery_disabled"
    assert tracking.calls == []
    print("[PASS] delivery config disabled does not call adapter")


async def _test_delivery_group_destination_blocked(mods: dict) -> None:
    deliver = mods["deliver_owner_action_reply_draft"]
    tracking = TrackingAdapter()
    result = await deliver(
        SimpleDraft("group", "137918147", "send_group_message", "跨群内容"),
        SimpleAction("send_group_message"),
        gate=None,
        plan=SimplePlan("group", "137918147"),
        message=SimpleMessage(channel="private", uid="335059272"),
        config=DictConfig(
            {
                "dry_run": False,
                "owner_action_execution_enabled": True,
                "owner_action_allow_reply_current": True,
                "owner_action_current_session_delivery_enabled": True,
            }
        ),
        sender=tracking,
    )

    assert result.mode == "blocked"
    assert "cross_session_blocked:send_group_locked" == result.reason
    assert tracking.calls == []
    print("[PASS] group destination stays blocked")


def test_nonebot_adapter_success(mods: dict) -> None:
    run(_test_nonebot_adapter_success(mods))


def test_nonebot_adapter_empty_content_blocked(mods: dict) -> None:
    run(_test_nonebot_adapter_empty_content_blocked(mods))


def test_nonebot_adapter_send_failed(mods: dict) -> None:
    run(_test_nonebot_adapter_send_failed(mods))


def test_nonebot_adapter_long_text_forward_fallback(mods: dict) -> None:
    run(_test_nonebot_adapter_long_text_forward_fallback(mods))


def test_nonebot_adapter_long_text_forward_success(mods: dict) -> None:
    run(_test_nonebot_adapter_long_text_forward_success(mods))


def test_delivery_dry_run_not_call_adapter(mods: dict) -> None:
    run(_test_delivery_dry_run_not_call_adapter(mods))


def test_delivery_config_disabled_not_call_adapter(mods: dict) -> None:
    run(_test_delivery_config_disabled_not_call_adapter(mods))


def test_delivery_group_destination_blocked(mods: dict) -> None:
    run(_test_delivery_group_destination_blocked(mods))


async def main() -> None:
    mods = prepare_modules()
    await _test_nonebot_adapter_success(mods)
    await _test_nonebot_adapter_empty_content_blocked(mods)
    await _test_nonebot_adapter_send_failed(mods)
    await _test_nonebot_adapter_long_text_forward_fallback(mods)
    await _test_nonebot_adapter_long_text_forward_success(mods)
    await _test_delivery_dry_run_not_call_adapter(mods)
    await _test_delivery_config_disabled_not_call_adapter(mods)
    await _test_delivery_group_destination_blocked(mods)
    print("[OK] test_sender_adapter_nonebot.py")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
