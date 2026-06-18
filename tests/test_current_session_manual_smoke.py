from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from mock_pipeline_runtime import DictConfig, prepare_modules  # type: ignore


OWNER_UID = "335059272"
GROUP_ID = "31003"


@dataclass
class SimpleMessage:
    channel: str = "group"
    uid: str = OWNER_UID
    group_id: str = GROUP_ID
    msg_id: str = "msg-1"
    timestamp: int = 1710000000
    is_owner: bool = True
    owner_action: object | None = None
    owner_action_gate: object | None = None
    owner_action_execution_plan: object | None = None
    owner_action_reply_draft: object | None = None


@dataclass
class SimpleAction:
    action_type: str = "reply_current"


@dataclass
class SimplePlan:
    destination_type: str = "current_session"
    destination_id: str | None = f"group:{GROUP_ID}"


@dataclass
class SimpleDraft:
    destination_type: str = "current_session"
    destination_id: str | None = f"group:{GROUP_ID}"
    action_type: str = "reply_current"
    content_preview: str = "手动 smoke 当前会话回复"
    content_length: int = 12
    status: str = "drafted"
    real_send: bool = False
    reason: str = "reply_current_pending"


class MockBot:
    def __init__(self):
        self.calls: list[tuple[object, str]] = []

    async def send(self, event, message: str):
        self.calls.append((event, message))
        return {"message_id": len(self.calls)}


class MockEvent:
    pass


def build_config(*, smoke: bool = False, full_enable: bool = False, audit_path: str, dry_run: bool = False) -> DictConfig:
    return DictConfig(
        {
            "dry_run": dry_run,
            "owner_action_manual_smoke_enabled": smoke,
            "owner_action_manual_smoke_owner_only": True,
            "owner_action_nonebot_sender_enabled": bool(full_enable),
            "owner_action_execution_enabled": bool(full_enable),
            "owner_action_allow_reply_current": bool(full_enable),
            "owner_action_current_session_delivery_enabled": bool(full_enable),
            "owner_action_delivery_safety_enabled": True,
            "owner_action_delivery_dedup_ttl_seconds": 300,
            "owner_action_delivery_audit_enabled": True,
            "owner_action_delivery_audit_path": audit_path,
        }
    )


def attach_reply_current_payload(msg: SimpleMessage, *, content: str = "手动 smoke 当前会话回复") -> SimpleMessage:
    msg.owner_action = SimpleAction("reply_current")
    msg.owner_action_execution_plan = SimplePlan("current_session", f"group:{msg.group_id}")
    msg.owner_action_reply_draft = SimpleDraft(
        destination_type="current_session",
        destination_id=f"group:{msg.group_id}",
        action_type="reply_current",
        content_preview=content,
        content_length=len(content),
        status="drafted",
        real_send=False,
        reason="reply_current_pending",
    )
    return msg


def attach_group_payload(msg: SimpleMessage) -> SimpleMessage:
    msg.owner_action = SimpleAction("send_group_message")
    msg.owner_action_execution_plan = SimplePlan("group", "137918147")
    msg.owner_action_reply_draft = SimpleDraft(
        destination_type="group",
        destination_id="137918147",
        action_type="send_group_message",
        content_preview="跨群不允许",
        content_length=5,
        status="drafted",
        real_send=False,
        reason="send_group_message_pending",
    )
    return msg


def read_audit_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


async def test_default_disabled(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    run_smoke = mods["run_current_session_manual_smoke_if_enabled"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"
        msg = attach_reply_current_payload(SimpleMessage())
        bot = MockBot()
        event = MockEvent()
        result = await run_smoke(msg, build_config(smoke=False, full_enable=True, audit_path=str(audit_path)), bot=bot, event=event, explicit_enable=True, dry_run=False)
        assert result.enabled is False
        assert result.reason == "disabled"
        assert result.delivered is False
        assert bot.calls == []
        assert read_audit_rows(audit_path) == []
        print("[PASS] manual smoke default disabled")


async def test_smoke_enabled_but_explicit_false(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    run_smoke = mods["run_current_session_manual_smoke_if_enabled"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"
        msg = attach_reply_current_payload(SimpleMessage())
        bot = MockBot()
        event = MockEvent()
        result = await run_smoke(msg, build_config(smoke=True, full_enable=True, audit_path=str(audit_path)), bot=bot, event=event, explicit_enable=False, dry_run=False)
        assert result.enabled is True
        assert result.reason == "explicit_enable_required"
        assert result.delivered is False
        assert bot.calls == []
        assert read_audit_rows(audit_path) == []
        print("[PASS] manual smoke explicit enable required")


async def test_smoke_enabled_but_not_fully_open(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    run_smoke = mods["run_current_session_manual_smoke_if_enabled"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"
        msg = attach_reply_current_payload(SimpleMessage())
        bot = MockBot()
        event = MockEvent()
        result = await run_smoke(msg, build_config(smoke=True, full_enable=False, audit_path=str(audit_path)), bot=bot, event=event, explicit_enable=True, dry_run=False)
        assert result.enabled is True
        assert result.eligible is True
        assert result.delivered is False
        assert result.real_send is False
        assert result.reason in {"nonebot_sender_disabled", "execution_disabled", "reply_current_not_allowed", "current_session_delivery_disabled"}
        assert bot.calls == []
        rows = read_audit_rows(audit_path)
        assert len(rows) == 1
        assert rows[0]["real_send"] is False
        print("[PASS] manual smoke not fully open -> still no send")


async def test_full_enable_real_send_once_and_audit(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    run_smoke = mods["run_current_session_manual_smoke_if_enabled"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"
        msg = attach_reply_current_payload(SimpleMessage(), content="现在只在当前会话试发一次")
        bot = MockBot()
        event = MockEvent()
        result = await run_smoke(msg, build_config(smoke=True, full_enable=True, audit_path=str(audit_path)), bot=bot, event=event, explicit_enable=True, dry_run=False)
        assert result.enabled is True
        assert result.eligible is True
        assert result.attempted is True
        assert result.delivered is True
        assert result.real_send is True
        assert result.integration_mode == "nonebot_current_session"
        assert bot.calls == [(event, "现在只在当前会话试发一次")]
        rows = read_audit_rows(audit_path)
        assert len(rows) == 1
        assert rows[0]["real_send"] is True
        assert rows[0]["action_type"] == "reply_current"
        print("[PASS] manual smoke full enable real send once")


async def test_non_owner_blocked(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    run_smoke = mods["run_current_session_manual_smoke_if_enabled"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"
        msg = attach_reply_current_payload(SimpleMessage(uid="10086", is_owner=False))
        bot = MockBot()
        event = MockEvent()
        result = await run_smoke(msg, build_config(smoke=True, full_enable=True, audit_path=str(audit_path)), bot=bot, event=event, explicit_enable=True, dry_run=False)
        assert result.reason == "not_owner"
        assert result.delivered is False
        assert bot.calls == []
        assert read_audit_rows(audit_path) == []
        print("[PASS] manual smoke non-owner blocked")


async def test_send_group_message_blocked(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    run_smoke = mods["run_current_session_manual_smoke_if_enabled"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"
        msg = attach_group_payload(SimpleMessage())
        bot = MockBot()
        event = MockEvent()
        result = await run_smoke(msg, build_config(smoke=True, full_enable=True, audit_path=str(audit_path)), bot=bot, event=event, explicit_enable=True, dry_run=False)
        assert result.reason == "cross_session_blocked"
        assert result.delivered is False
        assert bot.calls == []
        assert read_audit_rows(audit_path) == []
        print("[PASS] manual smoke cross-session blocked")


async def test_dry_run_does_not_register_dedup(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    run_smoke = mods["run_current_session_manual_smoke_if_enabled"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(smoke=True, full_enable=True, audit_path=str(audit_path), dry_run=False)
        msg = attach_reply_current_payload(SimpleMessage(msg_id="dry-run-msg"), content="dry run 先别发")
        bot1 = MockBot()
        event1 = MockEvent()
        dry = await run_smoke(msg, cfg, bot=bot1, event=event1, explicit_enable=True, dry_run=True)
        assert dry.delivered is False
        assert dry.real_send is False
        assert dry.reason == "dry_run_no_delivery"
        assert bot1.calls == []

        bot2 = MockBot()
        event2 = MockEvent()
        real = await run_smoke(msg, cfg, bot=bot2, event=event2, explicit_enable=True, dry_run=False)
        assert real.delivered is True
        assert real.real_send is True
        assert len(bot2.calls) == 1
        rows = read_audit_rows(audit_path)
        assert len(rows) == 2
        assert rows[0]["real_send"] is False
        assert rows[1]["real_send"] is True
        print("[PASS] manual smoke dry_run does not register dedup")


async def test_missing_bot_event_blocked(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    run_smoke = mods["run_current_session_manual_smoke_if_enabled"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"
        msg = attach_reply_current_payload(SimpleMessage())
        result = await run_smoke(msg, build_config(smoke=True, full_enable=True, audit_path=str(audit_path)), bot=None, event=None, explicit_enable=True, dry_run=False)
        assert result.reason == "missing_bot_event"
        assert result.delivered is False
        assert read_audit_rows(audit_path) == []
        print("[PASS] manual smoke missing bot/event blocked")


async def test_duplicate_blocked_second_time(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    run_smoke = mods["run_current_session_manual_smoke_if_enabled"]
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(smoke=True, full_enable=True, audit_path=str(audit_path))
        msg = attach_reply_current_payload(SimpleMessage(msg_id="dup-msg"), content="重复试发")

        bot1 = MockBot()
        event1 = MockEvent()
        first = await run_smoke(msg, cfg, bot=bot1, event=event1, explicit_enable=True, dry_run=False)
        bot2 = MockBot()
        event2 = MockEvent()
        second = await run_smoke(msg, cfg, bot=bot2, event=event2, explicit_enable=True, dry_run=False)
        assert first.delivered is True
        assert second.delivered is False
        assert second.reason.startswith("duplicate_blocked")
        assert len(bot1.calls) == 1
        assert bot2.calls == []
        print("[PASS] manual smoke duplicate blocked")


def test_check_script_runs_without_send() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        cfg_path = root / "runtime_config.json"
        cfg_path.write_text(
            json.dumps(
                {
                    "owner_action_manual_smoke_enabled": False,
                    "owner_action_manual_smoke_owner_only": True,
                    "owner_action_nonebot_sender_enabled": False,
                    "owner_action_execution_enabled": False,
                    "owner_action_allow_reply_current": False,
                    "owner_action_current_session_delivery_enabled": False,
                    "owner_action_delivery_dedup_ttl_seconds": 300,
                    "owner_action_delivery_audit_path": "logs/owner_action_delivery_audit.jsonl",
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        script = Path(__file__).resolve().parents[1] / "scripts" / "check_current_session_smoke_ready.py"
        result = subprocess.run([sys.executable, str(script), "--config", str(cfg_path)], text=True, capture_output=True)
        assert result.returncode == 0
        assert "manual_smoke_enabled=false" in result.stdout
        assert "cross_session_locked=true" in result.stdout
        print("[PASS] smoke ready check script runs")


async def main() -> None:
    mods = prepare_modules()
    await test_default_disabled(mods)
    await test_smoke_enabled_but_explicit_false(mods)
    await test_smoke_enabled_but_not_fully_open(mods)
    await test_full_enable_real_send_once_and_audit(mods)
    await test_non_owner_blocked(mods)
    await test_send_group_message_blocked(mods)
    await test_dry_run_does_not_register_dedup(mods)
    await test_missing_bot_event_blocked(mods)
    await test_duplicate_blocked_second_time(mods)
    test_check_script_runs_without_send()
    print("[OK] test_current_session_manual_smoke.py")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
