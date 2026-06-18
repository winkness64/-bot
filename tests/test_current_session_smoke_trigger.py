from __future__ import annotations

import asyncio
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mock_pipeline_runtime import DictConfig, prepare_modules  # type: ignore


OWNER_UID = "335059272"
GROUP_ID = "31003"
XIAOWEI_UID = "3916107556"


@dataclass
class TriggerMessage:
    channel: str = "group"
    uid: str = OWNER_UID
    group_id: str = GROUP_ID
    msg_id: str = "trigger-msg-1"
    timestamp: int = 1710000000
    is_owner: bool = True
    text: str = ""
    raw_content: str = ""
    bot_self_id: str = "90001"
    at_user_ids: list[str] | None = None
    reply_to_user_id: str | None = None
    reply_to_message_id: str | None = None


class MockBot:
    def __init__(self):
        self.calls: list[tuple[object, str]] = []

    async def send(self, event, message: str):
        self.calls.append((event, message))
        return {"message_id": len(self.calls)}


class MockEvent:
    pass


def build_config(*, smoke_enabled: bool, full_enable: bool, audit_path: str, dry_run: bool = False) -> DictConfig:
    return DictConfig(
        {
            "owner_uid": OWNER_UID,
            "owner_uids": [OWNER_UID],
            "member_aliases": {"小维": XIAOWEI_UID},
            "dry_run": dry_run,
            "owner_action_manual_smoke_enabled": smoke_enabled,
            "owner_action_manual_smoke_owner_only": True,
            "owner_action_nonebot_sender_enabled": bool(full_enable),
            "owner_action_execution_enabled": bool(full_enable),
            "owner_action_allow_reply_current": bool(full_enable),
            "owner_action_current_session_delivery_enabled": bool(full_enable),
            "owner_action_allow_send_group_message": False,
            "owner_action_delivery_safety_enabled": True,
            "owner_action_delivery_dedup_ttl_seconds": 300,
            "owner_action_delivery_audit_enabled": True,
            "owner_action_delivery_audit_path": audit_path,
        }
    )


def build_msg(text: str, *, is_owner: bool = True, msg_id: str = "trigger-msg-1") -> TriggerMessage:
    return TriggerMessage(
        is_owner=is_owner,
        uid=OWNER_UID if is_owner else "10086",
        text=text,
        raw_content=text,
        msg_id=msg_id,
    )


def read_audit_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def test_no_prefix_not_matched(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    handle_trigger = mods["handle_current_session_smoke_trigger_if_matched"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(smoke_enabled=True, full_enable=True, audit_path=str(audit))
        msg = build_msg("回应小维")
        bot = MockBot()
        event = MockEvent()
        result = await handle_trigger(msg, cfg, bot=bot, event=event, dry_run=False)
        assert result.matched is False
        assert result.reason == "prefix_not_matched"
        assert bot.calls == []
        assert read_audit_rows(audit) == []
        print("[PASS] trigger no prefix not matched")


async def test_non_owner_with_prefix_blocked(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    handle_trigger = mods["handle_current_session_smoke_trigger_if_matched"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(smoke_enabled=True, full_enable=True, audit_path=str(audit))
        msg = build_msg("/yy-smoke-current 回应小维", is_owner=False)
        bot = MockBot()
        event = MockEvent()
        result = await handle_trigger(msg, cfg, bot=bot, event=event, dry_run=False)
        assert result.matched is True
        assert result.reason == "not_owner"
        assert bot.calls == []
        assert read_audit_rows(audit) == []
        print("[PASS] trigger non-owner blocked")


async def test_owner_prefix_but_smoke_disabled(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    handle_trigger = mods["handle_current_session_smoke_trigger_if_matched"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(smoke_enabled=False, full_enable=True, audit_path=str(audit))
        msg = build_msg("/yy-smoke-current 回应小维")
        bot = MockBot()
        event = MockEvent()
        result = await handle_trigger(msg, cfg, bot=bot, event=event, dry_run=False)
        assert result.reason == "smoke_disabled"
        assert bot.calls == []
        assert read_audit_rows(audit) == []
        print("[PASS] trigger smoke disabled blocked")


async def test_owner_prefix_but_empty_inner_text(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    handle_trigger = mods["handle_current_session_smoke_trigger_if_matched"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(smoke_enabled=True, full_enable=True, audit_path=str(audit))
        msg = build_msg("/yy-smoke-current　 ")
        bot = MockBot()
        event = MockEvent()
        result = await handle_trigger(msg, cfg, bot=bot, event=event, dry_run=False)
        assert result.matched is True
        assert result.reason == "empty_inner_text"
        assert bot.calls == []
        assert read_audit_rows(audit) == []
        print("[PASS] trigger empty inner text blocked")


async def test_full_enable_but_missing_bot_event(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    handle_trigger = mods["handle_current_session_smoke_trigger_if_matched"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(smoke_enabled=True, full_enable=True, audit_path=str(audit))
        msg = build_msg("/yy-smoke-current 回应小维")
        result = await handle_trigger(msg, cfg, bot=None, event=None, dry_run=False)
        assert result.reason == "missing_bot_event"
        assert read_audit_rows(audit) == []
        print("[PASS] trigger missing bot/event blocked")


async def test_full_enable_owner_send_once_and_audit(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    handle_trigger = mods["handle_current_session_smoke_trigger_if_matched"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(smoke_enabled=True, full_enable=True, audit_path=str(audit))
        msg = build_msg("/yy-smoke-current 回应小维", msg_id="send-once-1")
        msg._current_session_smoke_model_reply = "收到，这句我来接。"
        msg._current_session_smoke_recent_messages = [
            {
                "message_id": "r1",
                "user_id": XIAOWEI_UID,
                "uid": XIAOWEI_UID,
                "nick": "小维",
                "text": "你看着回",
                "content": "你看着回",
                "timestamp": 1,
            }
        ]
        bot = MockBot()
        event = MockEvent()
        result = await handle_trigger(msg, cfg, bot=bot, event=event, dry_run=False)
        assert result.matched is True
        assert result.delivered is True
        assert result.real_send is True
        assert result.reason == "nonebot_current_session_sent"
        assert bot.calls == [(event, "收到，这句我来接。")]
        rows = read_audit_rows(audit)
        assert len(rows) == 1
        assert rows[0]["real_send"] is True
        print("[PASS] trigger full enable send once and audit")


async def test_duplicate_same_source_message_blocked(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    handle_trigger = mods["handle_current_session_smoke_trigger_if_matched"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(smoke_enabled=True, full_enable=True, audit_path=str(audit))
        msg = build_msg("/yy-smoke-current 回应小维", msg_id="dup-1")
        msg._current_session_smoke_model_reply = "重复保护测试"
        bot = MockBot()
        event = MockEvent()
        first = await handle_trigger(msg, cfg, bot=bot, event=event, dry_run=False)
        second = await handle_trigger(msg, cfg, bot=bot, event=event, dry_run=False)
        assert first.delivered is True
        assert second.delivered is False
        assert second.reason == "duplicate_blocked"
        assert len(bot.calls) == 1
        rows = read_audit_rows(audit)
        assert len(rows) == 2
        assert rows[1]["reason"].startswith("duplicate_blocked")
        print("[PASS] trigger duplicate blocked")


async def test_dry_run_no_send_and_no_dedup_pollution(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    handle_trigger = mods["handle_current_session_smoke_trigger_if_matched"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(smoke_enabled=True, full_enable=True, audit_path=str(audit))
        msg = build_msg("/yy-smoke-current 回应小维", msg_id="dry-1")
        msg._current_session_smoke_model_reply = "dry run 测试"
        bot1 = MockBot()
        event1 = MockEvent()
        dry = await handle_trigger(msg, cfg, bot=bot1, event=event1, dry_run=True)
        assert dry.delivered is False
        assert dry.real_send is False
        assert bot1.calls == []

        bot2 = MockBot()
        event2 = MockEvent()
        real = await handle_trigger(msg, cfg, bot=bot2, event=event2, dry_run=False)
        assert real.delivered is True
        assert real.real_send is True
        assert len(bot2.calls) == 1
        rows = read_audit_rows(audit)
        assert len(rows) == 2
        assert rows[0]["real_send"] is False
        assert rows[1]["real_send"] is True
        print("[PASS] trigger dry-run no dedup pollution")


async def test_cross_session_group_blocked(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    handle_trigger = mods["handle_current_session_smoke_trigger_if_matched"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(smoke_enabled=True, full_enable=True, audit_path=str(audit))
        msg = build_msg("/yy-smoke-current 去群里劝和一下")
        msg._current_session_smoke_model_reply = "不该发送"
        bot = MockBot()
        event = MockEvent()
        result = await handle_trigger(msg, cfg, bot=bot, event=event, dry_run=False)
        assert result.reason == "cross_session_blocked"
        assert bot.calls == []
        assert read_audit_rows(audit) == []
        print("[PASS] trigger cross-session group blocked")


async def test_chinese_prefix_also_supported(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    handle_trigger = mods["handle_current_session_smoke_trigger_if_matched"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(smoke_enabled=True, full_enable=True, audit_path=str(audit))
        msg = build_msg("/秧秧smoke 回应小维", msg_id="cn-prefix-1")
        msg._current_session_smoke_model_reply = "中文前缀可用"
        bot = MockBot()
        event = MockEvent()
        result = await handle_trigger(msg, cfg, bot=bot, event=event, dry_run=False)
        assert result.delivered is True
        assert result.real_send is True
        assert bot.calls == [(event, "中文前缀可用")]
        print("[PASS] trigger chinese prefix supported")


async def test_plain_owner_action_does_not_trigger_real_send(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    handle_trigger = mods["handle_current_session_smoke_trigger_if_matched"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(smoke_enabled=True, full_enable=True, audit_path=str(audit))
        msg = build_msg("回应小维", msg_id="plain-1")
        msg._current_session_smoke_model_reply = "不该触发"
        bot = MockBot()
        event = MockEvent()
        result = await handle_trigger(msg, cfg, bot=bot, event=event, dry_run=False)
        assert result.matched is False
        assert result.real_send is False
        assert bot.calls == []
        assert read_audit_rows(audit) == []
        print("[PASS] plain owner action does not trigger smoke")


def main() -> None:
    mods = prepare_modules()
    mods["reset_owner_action_delivery_safety_store"]()
    asyncio.run(test_no_prefix_not_matched(mods))
    asyncio.run(test_non_owner_with_prefix_blocked(mods))
    asyncio.run(test_owner_prefix_but_smoke_disabled(mods))
    asyncio.run(test_owner_prefix_but_empty_inner_text(mods))
    asyncio.run(test_full_enable_but_missing_bot_event(mods))
    asyncio.run(test_full_enable_owner_send_once_and_audit(mods))
    asyncio.run(test_duplicate_same_source_message_blocked(mods))
    asyncio.run(test_dry_run_no_send_and_no_dedup_pollution(mods))
    asyncio.run(test_cross_session_group_blocked(mods))
    asyncio.run(test_chinese_prefix_also_supported(mods))
    asyncio.run(test_plain_owner_action_does_not_trigger_real_send(mods))
    print("[OK] test_current_session_smoke_trigger.py")


if __name__ == "__main__":
    main()
