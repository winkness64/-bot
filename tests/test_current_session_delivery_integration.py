from __future__ import annotations

import asyncio
from dataclasses import dataclass

from conftest import run
from mock_pipeline_runtime import DictConfig, prepare_modules  # type: ignore


@dataclass
class SimpleMessage:
    channel: str
    uid: str = "335059272"
    group_id: str = "31003"


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
    def __init__(self):
        self.calls: list[tuple[object, str]] = []

    async def send(self, event, message: str):
        self.calls.append((event, message))
        return {"message_id": 1}


class MockEvent:
    pass


def build_full_enabled_config(*, dry_run: bool = False) -> DictConfig:
    return DictConfig(
        {
            "dry_run": dry_run,
            "owner_action_nonebot_sender_enabled": True,
            "owner_action_execution_enabled": True,
            "owner_action_allow_reply_current": True,
            "owner_action_current_session_delivery_enabled": True,
            "owner_action_allow_internal_control": False,
            "owner_action_delivery_safety_enabled": True,
            "owner_action_delivery_dedup_ttl_seconds": 300,
            "owner_action_delivery_audit_enabled": True,
            "owner_action_delivery_audit_path": "logs/owner_action_delivery_audit.jsonl",
        }
    )


async def _test_default_config_explicit_false_no_bot_call(mods: dict) -> None:
    deliver = mods["deliver_owner_action_current_session_if_enabled"]
    bot = MockBot()
    event = MockEvent()

    result = await deliver(
        SimpleDraft("current_session", "group:31003", "reply_current", "默认关闭"),
        SimpleAction("reply_current"),
        SimplePlan("current_session", "group:31003"),
        SimpleMessage(channel="group"),
        DictConfig({}),
        bot=bot,
        event=event,
        explicit_enable=False,
        dry_run=False,
    )

    assert result.adapter_type == "NullSenderAdapter"
    assert result.sender_enabled is False
    assert result.delivered is False
    assert result.real_send is False
    assert result.reason == "execution_disabled"
    assert bot.calls == []
    print("[PASS] integration default config + explicit false -> no bot call")


async def _test_full_config_but_not_explicit_no_bot_call(mods: dict) -> None:
    deliver = mods["deliver_owner_action_current_session_if_enabled"]
    bot = MockBot()
    event = MockEvent()

    result = await deliver(
        SimpleDraft("current_session", "group:31003", "reply_current", "配置全开但未显式启用"),
        SimpleAction("reply_current"),
        SimplePlan("current_session", "group:31003"),
        SimpleMessage(channel="group"),
        build_full_enabled_config(),
        bot=bot,
        event=event,
        explicit_enable=False,
        dry_run=False,
    )

    assert result.adapter_type == "NullSenderAdapter"
    assert result.sender_enabled is False
    assert result.delivered is False
    assert result.reason == "explicit_enable_required"
    assert bot.calls == []
    print("[PASS] integration full config + explicit false -> no bot call")


async def _test_full_config_explicit_true_current_session_real_send(mods: dict) -> None:
    deliver = mods["deliver_owner_action_current_session_if_enabled"]
    bot = MockBot()
    event = MockEvent()

    result = await deliver(
        SimpleDraft("current_session", "group:31003", "reply_current", "真实发送当前会话"),
        SimpleAction("reply_current"),
        SimplePlan("current_session", "group:31003"),
        SimpleMessage(channel="group"),
        build_full_enabled_config(),
        bot=bot,
        event=event,
        explicit_enable=True,
        dry_run=False,
    )

    assert result.adapter_type == "NoneBotCurrentSessionSenderAdapter"
    assert result.sender_enabled is True
    assert result.delivery_mode == "nonebot_current_session"
    assert result.attempted is True
    assert result.delivered is True
    assert result.real_send is True
    assert result.reason == "nonebot_current_session_sent"
    assert result.safety_allowed is True
    assert result.safety_duplicate is False
    assert bool(result.safety_key) is True
    assert bot.calls == [(event, "真实发送当前会话")]
    print("[PASS] integration explicit true current_session -> bot.send once")


async def _test_dry_run_true_no_bot_call(mods: dict) -> None:
    deliver = mods["deliver_owner_action_current_session_if_enabled"]
    bot = MockBot()
    event = MockEvent()

    result = await deliver(
        SimpleDraft("current_session", "group:31003", "reply_current", "dry run"),
        SimpleAction("reply_current"),
        SimplePlan("current_session", "group:31003"),
        SimpleMessage(channel="group"),
        build_full_enabled_config(),
        bot=bot,
        event=event,
        explicit_enable=True,
        dry_run=True,
    )

    assert result.adapter_type == "NoneBotCurrentSessionSenderAdapter"
    assert result.delivery_mode == "dry_run"
    assert result.delivered is False
    assert result.real_send is False
    assert result.reason == "dry_run_no_delivery"
    assert result.safety_allowed is True
    assert result.safety_duplicate is False
    assert bot.calls == []
    print("[PASS] integration dry_run true -> no bot call")


async def _test_send_group_message_blocked(mods: dict) -> None:
    deliver = mods["deliver_owner_action_current_session_if_enabled"]
    bot = MockBot()
    event = MockEvent()

    result = await deliver(
        SimpleDraft("group", "137918147", "send_group_message", "跨群发送"),
        SimpleAction("send_group_message"),
        SimplePlan("group", "137918147"),
        SimpleMessage(channel="private", uid="335059272", group_id=""),
        build_full_enabled_config(),
        bot=bot,
        event=event,
        explicit_enable=True,
        dry_run=False,
    )

    assert result.delivery_mode == "blocked"
    assert result.delivered is False
    assert result.reason == "cross_session_blocked:send_group_locked"
    assert bot.calls == []
    print("[PASS] integration send_group_message stays blocked")


async def _test_internal_control_blocked(mods: dict) -> None:
    deliver = mods["deliver_owner_action_current_session_if_enabled"]
    bot = MockBot()
    event = MockEvent()

    result = await deliver(
        SimpleDraft("internal_control", None, "cancel_reply", "控制动作"),
        SimpleAction("cancel_reply"),
        SimplePlan("internal_control", None),
        SimpleMessage(channel="group"),
        build_full_enabled_config(),
        bot=bot,
        event=event,
        explicit_enable=True,
        dry_run=False,
    )

    assert result.delivery_mode == "blocked"
    assert result.reason == "internal_control_not_implemented"
    assert result.delivered is False
    assert bot.calls == []
    print("[PASS] integration internal_control blocked")


async def _test_missing_bot_or_event_returns_null_blocked(mods: dict) -> None:
    deliver = mods["deliver_owner_action_current_session_if_enabled"]

    result_missing_bot = await deliver(
        SimpleDraft("current_session", "group:31003", "reply_current", "缺 bot"),
        SimpleAction("reply_current"),
        SimplePlan("current_session", "group:31003"),
        SimpleMessage(channel="group"),
        build_full_enabled_config(),
        bot=None,
        event=MockEvent(),
        explicit_enable=True,
        dry_run=False,
    )
    assert result_missing_bot.adapter_type == "NullSenderAdapter"
    assert result_missing_bot.sender_enabled is False
    assert result_missing_bot.reason == "missing_bot_or_event"

    result_missing_event = await deliver(
        SimpleDraft("current_session", "group:31003", "reply_current", "缺 event"),
        SimpleAction("reply_current"),
        SimplePlan("current_session", "group:31003"),
        SimpleMessage(channel="group"),
        build_full_enabled_config(),
        bot=MockBot(),
        event=None,
        explicit_enable=True,
        dry_run=False,
    )
    assert result_missing_event.adapter_type == "NullSenderAdapter"
    assert result_missing_event.sender_enabled is False
    assert result_missing_event.reason == "missing_bot_or_event"
    print("[PASS] integration missing bot/event -> null blocked")


async def _test_missing_draft_plan_action_no_send(mods: dict) -> None:
    deliver = mods["deliver_owner_action_current_session_if_enabled"]
    bot = MockBot()
    event = MockEvent()

    result_no_draft = await deliver(
        None,
        SimpleAction("reply_current"),
        SimplePlan("current_session", "group:31003"),
        SimpleMessage(channel="group"),
        build_full_enabled_config(),
        bot=bot,
        event=event,
        explicit_enable=True,
        dry_run=False,
    )
    assert result_no_draft.reason == "no_draft"

    result_no_action = await deliver(
        SimpleDraft("current_session", "group:31003", "reply_current", "缺 action"),
        None,
        SimplePlan("current_session", "group:31003"),
        SimpleMessage(channel="group"),
        build_full_enabled_config(),
        bot=bot,
        event=event,
        explicit_enable=True,
        dry_run=False,
    )
    assert result_no_action.reason == "no_action"

    result_no_plan = await deliver(
        SimpleDraft("current_session", "group:31003", "reply_current", "缺 plan"),
        SimpleAction("reply_current"),
        None,
        SimpleMessage(channel="group"),
        build_full_enabled_config(),
        bot=bot,
        event=event,
        explicit_enable=True,
        dry_run=False,
    )
    assert result_no_plan.reason == "no_plan"
    assert bot.calls == []
    print("[PASS] integration missing draft/plan/action -> no send")


def test_default_config_explicit_false_no_bot_call(mods: dict) -> None:
    run(_test_default_config_explicit_false_no_bot_call(mods))


def test_full_config_but_not_explicit_no_bot_call(mods: dict) -> None:
    run(_test_full_config_but_not_explicit_no_bot_call(mods))


def test_full_config_explicit_true_current_session_real_send(mods: dict) -> None:
    run(_test_full_config_explicit_true_current_session_real_send(mods))


def test_dry_run_true_no_bot_call(mods: dict) -> None:
    run(_test_dry_run_true_no_bot_call(mods))


def test_send_group_message_blocked(mods: dict) -> None:
    run(_test_send_group_message_blocked(mods))


def test_internal_control_blocked(mods: dict) -> None:
    run(_test_internal_control_blocked(mods))


def test_missing_bot_or_event_returns_null_blocked(mods: dict) -> None:
    run(_test_missing_bot_or_event_returns_null_blocked(mods))


def test_missing_draft_plan_action_no_send(mods: dict) -> None:
    run(_test_missing_draft_plan_action_no_send(mods))


async def main() -> None:
    mods = prepare_modules()
    await _test_default_config_explicit_false_no_bot_call(mods)
    await _test_full_config_but_not_explicit_no_bot_call(mods)
    await _test_full_config_explicit_true_current_session_real_send(mods)
    await _test_dry_run_true_no_bot_call(mods)
    await _test_send_group_message_blocked(mods)
    await _test_internal_control_blocked(mods)
    await _test_missing_bot_or_event_returns_null_blocked(mods)
    await _test_missing_draft_plan_action_no_send(mods)
    print("[OK] test_current_session_delivery_integration.py")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
