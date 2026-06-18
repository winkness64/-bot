from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from mock_pipeline_runtime import DictConfig, prepare_modules  # type: ignore


OWNER_UID = "335059272"
GROUP_ID = "31003"
XIAOWEI_UID = "3916107556"


class MockBot:
    def __init__(self):
        self.calls: list[tuple[object, str]] = []
        self.self_id = "90001"

    async def send(self, event, message: str):
        self.calls.append((event, message))
        return {"message_id": len(self.calls)}


class MockEvent:
    pass


class SmokeEvent(sys.modules.get("builtins").object):
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


def build_trigger_message(text: str, *, is_owner: bool = True, msg_id: str = "trigger-msg-1"):
    return SimpleNamespace(
        channel="group",
        uid=OWNER_UID if is_owner else "10086",
        group_id=GROUP_ID,
        msg_id=msg_id,
        timestamp=1710000000,
        is_owner=is_owner,
        text=text,
        raw_content=text,
        bot_self_id="90001",
        at_user_ids=None,
        reply_to_user_id=None,
        reply_to_message_id=None,
    )


def read_audit_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def test_runtime_config_reload_reads_disk_toggle(mods: dict) -> None:
    RuntimeConfig = mods["RuntimeConfig"]
    DEFAULTS = mods["DEFAULTS"]
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg_path = Path(tmpdir) / "runtime_config.json"
        cfg = RuntimeConfig(DEFAULTS, path=cfg_path)
        assert cfg.get_bool("owner_action_manual_smoke_enabled", False) is False

        data = json.loads(cfg_path.read_text(encoding="utf-8"))
        data["owner_action_manual_smoke_enabled"] = True
        cfg_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        cfg.reload()
        assert cfg.get_bool("owner_action_manual_smoke_enabled", False) is True
        print("[PASS] runtime_config reload reads disk toggle")


async def test_handle_message_smoke_bypasses_default_silent(mods: dict) -> None:
    plugin = mods["plugin"]
    v11_mod = sys.modules["nonebot.adapters.onebot.v11"]

    class SmokeGroupEvent(v11_mod.GroupMessageEvent):
        pass

    event = SmokeGroupEvent()
    bot = MockBot()
    msg = build_trigger_message("/yy-smoke-current 回应小维", is_owner=True, msg_id="bypass-1")
    recorded: list[tuple[str, bool]] = []
    smoke_calls: list[str] = []

    original_adapter = plugin.adapter
    original_engine = plugin.engine
    original_store = plugin.store
    original_smoke_handler = plugin.handle_current_session_smoke_trigger_if_matched

    plugin.adapter = SimpleNamespace(adapt_group_msg=lambda _event: msg, adapt_private_msg=lambda _event: msg)
    plugin.engine = SimpleNamespace(decide=lambda _msg: SimpleNamespace(should_reply=False, is_forced=False, model_tier=None))
    plugin.store = SimpleNamespace(
        get_recent_messages=lambda *args, **kwargs: [{"uid": XIAOWEI_UID, "text": "你看着回"}],
        record_message=lambda message, is_bot=False: recorded.append((message.msg_id, is_bot)),
    )

    async def fake_smoke_handler(*args, **kwargs):
        smoke_calls.append("called")
        return SimpleNamespace(matched=True, delivered=False, real_send=False, reason="smoke_disabled")

    plugin.handle_current_session_smoke_trigger_if_matched = fake_smoke_handler
    try:
        await plugin.handle_message(bot, event)
    finally:
        plugin.adapter = original_adapter
        plugin.engine = original_engine
        plugin.store = original_store
        plugin.handle_current_session_smoke_trigger_if_matched = original_smoke_handler

    assert smoke_calls == ["called"]
    assert recorded == [("bypass-1", False)]
    print("[PASS] handle_message smoke bypasses default silent return")


async def test_not_owner_still_blocked(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    handle_trigger = mods["handle_current_session_smoke_trigger_if_matched"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(smoke_enabled=True, full_enable=True, audit_path=str(audit))
        msg = build_trigger_message("/yy-smoke-current 回应小维", is_owner=False)
        bot = MockBot()
        event = MockEvent()
        result = await handle_trigger(msg, cfg, bot=bot, event=event, dry_run=False)
        assert result.reason == "not_owner"
        assert result.real_send is False
        assert bot.calls == []
        assert read_audit_rows(audit) == []
        print("[PASS] smoke trigger not_owner still blocked")


async def test_dry_run_still_no_delivery(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    handle_trigger = mods["handle_current_session_smoke_trigger_if_matched"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(smoke_enabled=True, full_enable=True, audit_path=str(audit))
        msg = build_trigger_message("/yy-smoke-current 回应小维", is_owner=True, msg_id="dry-run-patch-1")
        msg._current_session_smoke_model_reply = "dry run 测试"
        bot = MockBot()
        event = MockEvent()
        result = await handle_trigger(msg, cfg, bot=bot, event=event, dry_run=True)
        assert result.real_send is False
        assert result.delivered is False
        assert result.reason == "dry_run_no_delivery"
        assert bot.calls == []
        rows = read_audit_rows(audit)
        assert len(rows) == 1
        assert rows[0]["real_send"] is False
        print("[PASS] smoke trigger dry_run still no delivery")


async def test_cross_session_still_blocked(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    handle_trigger = mods["handle_current_session_smoke_trigger_if_matched"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(smoke_enabled=True, full_enable=True, audit_path=str(audit))
        msg = build_trigger_message("/yy-smoke-current 去群里劝和一下", is_owner=True, msg_id="cross-session-1")
        bot = MockBot()
        event = MockEvent()
        result = await handle_trigger(msg, cfg, bot=bot, event=event, dry_run=False)
        assert result.reason == "cross_session_blocked"
        assert result.real_send is False
        assert result.delivered is False
        assert bot.calls == []
        assert read_audit_rows(audit) == []
        print("[PASS] smoke trigger cross-session still blocked")


async def main() -> None:
    mods = prepare_modules()
    await test_runtime_config_reload_reads_disk_toggle(mods)
    await test_handle_message_smoke_bypasses_default_silent(mods)
    await test_not_owner_still_blocked(mods)
    await test_dry_run_still_no_delivery(mods)
    await test_cross_session_still_blocked(mods)
    print("PASS")


if __name__ == "__main__":
    asyncio.run(main())
