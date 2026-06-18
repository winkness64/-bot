from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mock_pipeline_runtime import DictConfig, prepare_modules  # type: ignore


@dataclass
class SimpleMessage:
    channel: str
    uid: str = "335059272"
    group_id: str = "31003"
    msg_id: str = "msg-1"
    timestamp: int = 1710000000


@dataclass
class SimpleDraft:
    destination_type: str
    destination_id: str | None
    action_type: str
    content_preview: str
    content_length: int | None = None
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


def build_full_enabled_config(*, dry_run: bool = False, audit_path: str | None = None) -> DictConfig:
    data = {
        "dry_run": dry_run,
        "owner_action_nonebot_sender_enabled": True,
        "owner_action_execution_enabled": True,
        "owner_action_allow_reply_current": True,
        "owner_action_current_session_delivery_enabled": True,
        "owner_action_delivery_safety_enabled": True,
        "owner_action_delivery_dedup_ttl_seconds": 300,
        "owner_action_delivery_audit_enabled": True,
        "owner_action_delivery_audit_path": audit_path or "logs/owner_action_delivery_audit.jsonl",
    }
    return DictConfig(data)


async def test_first_key_allowed(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    check = mods["check_owner_action_delivery_safety"]
    result = check(
        SimpleDraft("current_session", "group:31003", "reply_current", "hello", 5),
        SimpleAction("reply_current"),
        SimplePlan("current_session", "group:31003"),
        SimpleMessage(channel="group", msg_id="msg-allow-1"),
        build_full_enabled_config(),
        dry_run=False,
    )
    assert result.allowed is True
    assert result.duplicate is False
    assert result.reason == "allowed"
    assert result.key
    print("[PASS] safety first key allowed")


async def test_ttl_duplicate_blocked(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    check = mods["check_owner_action_delivery_safety"]
    args = (
        SimpleDraft("current_session", "group:31003", "reply_current", "same", 4),
        SimpleAction("reply_current"),
        SimplePlan("current_session", "group:31003"),
        SimpleMessage(channel="group", msg_id="msg-dup-1"),
        build_full_enabled_config(),
    )
    first = check(*args, dry_run=False)
    second = check(*args, dry_run=False)
    assert first.allowed is True
    assert second.allowed is False
    assert second.duplicate is True
    assert second.reason == "duplicate_blocked"
    print("[PASS] safety ttl duplicate blocked")


async def test_clear_reset_allows_again(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    check = mods["check_owner_action_delivery_safety"]
    args = (
        SimpleDraft("current_session", "group:31003", "reply_current", "same", 4),
        SimpleAction("reply_current"),
        SimplePlan("current_session", "group:31003"),
        SimpleMessage(channel="group", msg_id="msg-reset-1"),
        build_full_enabled_config(),
    )
    check(*args, dry_run=False)
    mods["clear_owner_action_delivery_safety_store"]()
    again = check(*args, dry_run=False)
    assert again.allowed is True
    assert again.duplicate is False
    print("[PASS] safety clear/reset allows again")


async def test_different_inputs_do_not_conflict(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    check = mods["check_owner_action_delivery_safety"]
    config = build_full_enabled_config()
    base_message = SimpleMessage(channel="group", msg_id="msg-diff-1")
    r1 = check(SimpleDraft("current_session", "group:31003", "reply_current", "a", 1), SimpleAction("reply_current"), SimplePlan("current_session", "group:31003"), base_message, config, dry_run=False)
    r2 = check(SimpleDraft("current_session", "group:31003", "reply_current", "b", 1), SimpleAction("reply_current"), SimplePlan("current_session", "group:31003"), base_message, config, dry_run=False)
    r3 = check(SimpleDraft("current_session", "group:99999", "reply_current", "a", 1), SimpleAction("reply_current"), SimplePlan("current_session", "group:99999"), base_message, config, dry_run=False)
    r4 = check(SimpleDraft("current_session", "group:31003", "cancel_reply", "a", 1), SimpleAction("cancel_reply"), SimplePlan("current_session", "group:31003"), base_message, config, dry_run=False)
    assert len({r1.key, r2.key, r3.key, r4.key}) == 4
    print("[PASS] safety different content/destination/action do not conflict")


async def test_dry_run_not_registered(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    check = mods["check_owner_action_delivery_safety"]
    args = (
        SimpleDraft("current_session", "group:31003", "reply_current", "dry", 3),
        SimpleAction("reply_current"),
        SimplePlan("current_session", "group:31003"),
        SimpleMessage(channel="group", msg_id="msg-dry-1"),
        build_full_enabled_config(dry_run=True),
    )
    dry = check(*args, dry_run=True)
    real = check(*args, dry_run=False)
    assert dry.allowed is True
    assert dry.reason == "dry_run_not_registered"
    assert real.allowed is True
    print("[PASS] safety dry_run not registered")


async def test_non_dry_run_duplicate_blocks_second_send(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    deliver = mods["deliver_owner_action_current_session_if_enabled"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = str(Path(tmpdir) / "audit.jsonl")
        cfg = build_full_enabled_config(dry_run=False, audit_path=audit_path)
        bot = MockBot()
        event = MockEvent()
        message = SimpleMessage(channel="group", group_id="31003", msg_id="msg-live-1")
        draft = SimpleDraft("current_session", "group:31003", "reply_current", "真实发送", 4)
        action = SimpleAction("reply_current")
        plan = SimplePlan("current_session", "group:31003")

        first = await deliver(draft, action, plan, message, cfg, bot=bot, event=event, explicit_enable=True, dry_run=False)
        second = await deliver(draft, action, plan, message, cfg, bot=bot, event=event, explicit_enable=True, dry_run=False)
        assert first.delivered is True
        assert second.delivered is False
        assert second.reason.startswith("duplicate_blocked")
        assert len(bot.calls) == 1
    print("[PASS] integration duplicate blocks second real send")


async def test_audit_jsonl_written(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    deliver = mods["deliver_owner_action_current_session_if_enabled"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_file = Path(tmpdir) / "logs" / "owner_action_delivery_audit.jsonl"
        cfg = build_full_enabled_config(audit_path=str(audit_file))
        bot = MockBot()
        event = MockEvent()
        result = await deliver(
            SimpleDraft("current_session", "group:31003", "reply_current", "审计内容", 4),
            SimpleAction("reply_current"),
            SimplePlan("current_session", "group:31003"),
            SimpleMessage(channel="group", msg_id="msg-audit-1"),
            cfg,
            bot=bot,
            event=event,
            explicit_enable=True,
            dry_run=False,
        )
        assert result.delivered is True
        lines = audit_file.read_text(encoding="utf-8").strip().splitlines()
        assert lines
        row = json.loads(lines[-1])
        for field in ["action_type", "destination_type", "status", "real_send", "reason", "content_preview"]:
            assert field in row
        assert row["action_type"] == "reply_current"
        assert row["destination_type"] == "current_session"
    print("[PASS] audit jsonl written with expected fields")


async def test_audit_write_failure_not_crash(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    deliver = mods["deliver_owner_action_current_session_if_enabled"]
    cfg = build_full_enabled_config(audit_path="/proc/1/forbidden_audit.jsonl")
    bot = MockBot()
    event = MockEvent()
    result = await deliver(
        SimpleDraft("current_session", "group:31003", "reply_current", "审计失败", 4),
        SimpleAction("reply_current"),
        SimplePlan("current_session", "group:31003"),
        SimpleMessage(channel="group", msg_id="msg-audit-fail-1"),
        cfg,
        bot=bot,
        event=event,
        explicit_enable=True,
        dry_run=False,
    )
    assert result.delivered is True
    assert "audit_failed" in result.reason
    assert len(bot.calls) == 1
    print("[PASS] audit failure does not crash main flow")


async def test_send_group_message_still_blocked(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    deliver = mods["deliver_owner_action_current_session_if_enabled"]
    bot = MockBot()
    event = MockEvent()
    result = await deliver(
        SimpleDraft("group", "137918147", "send_group_message", "跨群", 2),
        SimpleAction("send_group_message"),
        SimplePlan("group", "137918147"),
        SimpleMessage(channel="private", uid="335059272", group_id="", msg_id="msg-group-block-1"),
        build_full_enabled_config(),
        bot=bot,
        event=event,
        explicit_enable=True,
        dry_run=False,
    )
    assert result.delivered is False
    assert "cross_session_blocked:send_group_locked" in result.reason
    assert bot.calls == []
    print("[PASS] send_group_message still blocked")


async def main() -> None:
    mods = prepare_modules()
    await test_first_key_allowed(mods)
    await test_ttl_duplicate_blocked(mods)
    await test_clear_reset_allows_again(mods)
    await test_different_inputs_do_not_conflict(mods)
    await test_dry_run_not_registered(mods)
    await test_non_dry_run_duplicate_blocks_second_send(mods)
    await test_audit_jsonl_written(mods)
    await test_audit_write_failure_not_crash(mods)
    await test_send_group_message_still_blocked(mods)
    print("[OK] test_owner_action_delivery_safety.py")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
