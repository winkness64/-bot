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
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls: list[tuple[object, str]] = []

    async def send(self, event, message: str):
        self.calls.append((event, message))
        if self.fail:
            raise RuntimeError("boom")
        return {"message_id": 1}


class MockEvent:
    pass


def build_full_enabled_config() -> DictConfig:
    return DictConfig(
        {
            "dry_run": False,
            "owner_action_nonebot_sender_enabled": True,
            "owner_action_execution_enabled": True,
            "owner_action_allow_reply_current": True,
            "owner_action_current_session_delivery_enabled": True,
        }
    )


async def _test_factory_default_config_returns_null(mods: dict) -> None:
    build_factory = mods["build_owner_action_sender_adapter"]
    NullSenderAdapter = mods["NullSenderAdapter"]
    adapter = build_factory(DictConfig({}), explicit_enable=False)
    assert isinstance(adapter, NullSenderAdapter)
    assert adapter.reason == "explicit_enable_required"
    print("[PASS] factory default config -> NullSenderAdapter")


async def _test_factory_execution_only_without_nonebot_sender_returns_null(mods: dict) -> None:
    build_factory = mods["build_owner_action_sender_adapter"]
    NullSenderAdapter = mods["NullSenderAdapter"]
    adapter = build_factory(
        DictConfig(
            {
                "owner_action_execution_enabled": True,
                "owner_action_allow_reply_current": True,
                "owner_action_current_session_delivery_enabled": True,
            }
        ),
        bot=MockBot(),
        event=MockEvent(),
        explicit_enable=True,
    )
    assert isinstance(adapter, NullSenderAdapter)
    assert adapter.reason == "nonebot_sender_disabled"
    print("[PASS] factory execution only but nonebot sender off -> NullSenderAdapter")


async def _test_factory_all_enabled_but_not_explicit_returns_null(mods: dict) -> None:
    build_factory = mods["build_owner_action_sender_adapter"]
    NullSenderAdapter = mods["NullSenderAdapter"]
    adapter = build_factory(build_full_enabled_config(), bot=MockBot(), event=MockEvent(), explicit_enable=False)
    assert isinstance(adapter, NullSenderAdapter)
    assert adapter.reason == "explicit_enable_required"
    print("[PASS] factory all enabled but explicit_enable false -> NullSenderAdapter")


async def _test_factory_all_enabled_but_missing_bot_or_event_returns_null(mods: dict) -> None:
    build_factory = mods["build_owner_action_sender_adapter"]
    NullSenderAdapter = mods["NullSenderAdapter"]

    adapter_missing_bot = build_factory(build_full_enabled_config(), bot=None, event=MockEvent(), explicit_enable=True)
    assert isinstance(adapter_missing_bot, NullSenderAdapter)
    assert adapter_missing_bot.reason == "missing_bot_or_event"

    adapter_missing_event = build_factory(build_full_enabled_config(), bot=MockBot(), event=None, explicit_enable=True)
    assert isinstance(adapter_missing_event, NullSenderAdapter)
    assert adapter_missing_event.reason == "missing_bot_or_event"
    print("[PASS] factory all enabled but missing bot/event -> NullSenderAdapter")


async def _test_factory_all_enabled_with_explicit_injection_returns_nonebot_adapter(mods: dict) -> None:
    build_factory = mods["build_owner_action_sender_adapter"]
    Adapter = mods["NoneBotCurrentSessionSenderAdapter"]
    bot = MockBot()
    event = MockEvent()
    adapter = build_factory(build_full_enabled_config(), bot=bot, event=event, explicit_enable=True)
    assert isinstance(adapter, Adapter)
    assert adapter.bot is bot
    assert adapter.event is event
    print("[PASS] factory full enable + explicit injection -> NoneBotCurrentSessionSenderAdapter")


async def _test_delivery_with_factory_nonebot_adapter_can_send_current_session(mods: dict) -> None:
    build_factory = mods["build_owner_action_sender_adapter"]
    deliver = mods["deliver_owner_action_reply_draft"]
    bot = MockBot()
    event = MockEvent()
    adapter = build_factory(build_full_enabled_config(), bot=bot, event=event, explicit_enable=True)

    result = await deliver(
        SimpleDraft("current_session", "group:31003", "reply_current", "收到，当前会话回复"),
        SimpleAction("reply_current"),
        gate=None,
        plan=SimplePlan("current_session", "group:31003"),
        message=SimpleMessage(channel="group", group_id="31003", uid="335059272"),
        config=build_full_enabled_config(),
        sender=adapter,
    )

    assert result.delivered is True
    assert result.real_send is True
    assert bot.calls == [(event, "收到，当前会话回复")]
    print("[PASS] delivery current_session with factory adapter calls mock bot")


async def _test_send_group_message_stays_blocked_even_with_real_adapter(mods: dict) -> None:
    build_factory = mods["build_owner_action_sender_adapter"]
    deliver = mods["deliver_owner_action_reply_draft"]
    bot = MockBot()
    event = MockEvent()
    adapter = build_factory(build_full_enabled_config(), bot=bot, event=event, explicit_enable=True)

    result = await deliver(
        SimpleDraft("group", "137918147", "send_group_message", "跨群内容"),
        SimpleAction("send_group_message"),
        gate=None,
        plan=SimplePlan("group", "137918147"),
        message=SimpleMessage(channel="private", uid="335059272"),
        config=build_full_enabled_config(),
        sender=adapter,
    )

    assert result.mode == "blocked"
    assert result.reason == "cross_session_blocked:send_group_locked"
    assert bot.calls == []
    print("[PASS] send_group_message / group destination still blocked")


async def _test_dry_run_with_real_factory_adapter_still_not_call_bot(mods: dict) -> None:
    build_factory = mods["build_owner_action_sender_adapter"]
    deliver = mods["deliver_owner_action_reply_draft"]
    bot = MockBot()
    event = MockEvent()
    adapter = build_factory(build_full_enabled_config(), bot=bot, event=event, explicit_enable=True)
    cfg = DictConfig(
        {
            "dry_run": True,
            "owner_action_nonebot_sender_enabled": True,
            "owner_action_execution_enabled": True,
            "owner_action_allow_reply_current": True,
            "owner_action_current_session_delivery_enabled": True,
        }
    )

    result = await deliver(
        SimpleDraft("current_session", "group:31003", "reply_current", "dry run text"),
        SimpleAction("reply_current"),
        gate=None,
        plan=SimplePlan("current_session", "group:31003"),
        message=SimpleMessage(channel="group", group_id="31003", uid="335059272"),
        config=cfg,
        sender=adapter,
    )

    assert result.delivered is False
    assert result.real_send is False
    assert result.mode == "dry_run"
    assert bot.calls == []
    print("[PASS] dry run with real factory adapter does not call mock bot")


async def _test_real_adapter_send_failure_becomes_failed_delivery(mods: dict) -> None:
    build_factory = mods["build_owner_action_sender_adapter"]
    deliver = mods["deliver_owner_action_reply_draft"]
    bot = MockBot(fail=True)
    event = MockEvent()
    adapter = build_factory(build_full_enabled_config(), bot=bot, event=event, explicit_enable=True)

    result = await deliver(
        SimpleDraft("current_session", "group:31003", "reply_current", "should fail"),
        SimpleAction("reply_current"),
        gate=None,
        plan=SimplePlan("current_session", "group:31003"),
        message=SimpleMessage(channel="group", group_id="31003", uid="335059272"),
        config=build_full_enabled_config(),
        sender=adapter,
    )

    assert result.delivered is False
    assert result.real_send is False
    assert result.mode == "send_failed"
    assert str(result.reason).startswith("send_failed:")
    assert bot.calls == [(event, "should fail")]
    print("[PASS] real adapter send failure -> failed delivery")


def test_factory_default_config_returns_null(mods: dict) -> None:
    run(_test_factory_default_config_returns_null(mods))


def test_factory_execution_only_without_nonebot_sender_returns_null(mods: dict) -> None:
    run(_test_factory_execution_only_without_nonebot_sender_returns_null(mods))


def test_factory_all_enabled_but_not_explicit_returns_null(mods: dict) -> None:
    run(_test_factory_all_enabled_but_not_explicit_returns_null(mods))


def test_factory_all_enabled_but_missing_bot_or_event_returns_null(mods: dict) -> None:
    run(_test_factory_all_enabled_but_missing_bot_or_event_returns_null(mods))


def test_factory_all_enabled_with_explicit_injection_returns_nonebot_adapter(mods: dict) -> None:
    run(_test_factory_all_enabled_with_explicit_injection_returns_nonebot_adapter(mods))


def test_delivery_with_factory_nonebot_adapter_can_send_current_session(mods: dict) -> None:
    run(_test_delivery_with_factory_nonebot_adapter_can_send_current_session(mods))


def test_send_group_message_stays_blocked_even_with_real_adapter(mods: dict) -> None:
    run(_test_send_group_message_stays_blocked_even_with_real_adapter(mods))


def test_dry_run_with_real_factory_adapter_still_not_call_bot(mods: dict) -> None:
    run(_test_dry_run_with_real_factory_adapter_still_not_call_bot(mods))


def test_real_adapter_send_failure_becomes_failed_delivery(mods: dict) -> None:
    run(_test_real_adapter_send_failure_becomes_failed_delivery(mods))


async def main() -> None:
    mods = prepare_modules()
    await _test_factory_default_config_returns_null(mods)
    await _test_factory_execution_only_without_nonebot_sender_returns_null(mods)
    await _test_factory_all_enabled_but_not_explicit_returns_null(mods)
    await _test_factory_all_enabled_but_missing_bot_or_event_returns_null(mods)
    await _test_factory_all_enabled_with_explicit_injection_returns_nonebot_adapter(mods)
    await _test_delivery_with_factory_nonebot_adapter_can_send_current_session(mods)
    await _test_send_group_message_stays_blocked_even_with_real_adapter(mods)
    await _test_dry_run_with_real_factory_adapter_still_not_call_bot(mods)
    await _test_real_adapter_send_failure_becomes_failed_delivery(mods)
    print("[OK] test_sender_adapter_factory.py")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
