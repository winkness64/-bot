from __future__ import annotations

import asyncio
import json
import tempfile
from pathlib import Path

from mock_pipeline_runtime import (  # type: ignore
    DictConfig,
    FakeEvent,
    FakeSenderInfo,
    Seg,
    prepare_modules,
)


OWNER_UID = "335059272"
BOT_UID = "90001"
GROUP_ID = "31003"
XIAOWEI_UID = "3916107556"


class MockBot:
    def __init__(self):
        self.calls: list[tuple[object, str]] = []

    async def send(self, event, message: str):
        self.calls.append((event, message))
        return {"message_id": len(self.calls)}


class MockEventRef:
    pass


DEFAULT_MEMBER_ALIASES = {
    "小维": XIAOWEI_UID,
    "红尘": "2434523727",
    "娅娅": "2690087239",
}


def build_config(*, audit_path: str, full_enable: bool = False, dry_run: bool = False) -> DictConfig:
    return DictConfig(
        {
            "owner_uid": OWNER_UID,
            "owner_uids": [OWNER_UID],
            "default_group_id": "137918147",
            "primary_group_id": "137918147",
            "member_aliases": dict(DEFAULT_MEMBER_ALIASES),
            "dry_run": dry_run,
            "owner_action_nonebot_sender_enabled": bool(full_enable),
            "owner_action_execution_enabled": bool(full_enable),
            "owner_action_allow_send_group_message": bool(full_enable),
            "owner_action_allow_reply_current": bool(full_enable),
            "owner_action_current_session_delivery_enabled": bool(full_enable),
            "owner_action_allow_internal_control": False,
            "owner_action_delivery_safety_enabled": True,
            "owner_action_delivery_dedup_ttl_seconds": 300,
            "owner_action_delivery_audit_enabled": True,
            "owner_action_delivery_audit_path": audit_path,
            "behavior": {
                "cooldown_global_s": 0,
                "cooldown_topic_rounds": 0,
                "cooldown_topic_s": 0,
                "daily_auto_reply_limit": 0,
                "bot_loop_enabled": False,
                "bot_loop_recent_limit": 8,
                "bot_loop_min_bot_messages": 3,
                "bot_loop_cooldown_seconds": 30,
            },
        }
    )


def make_group_event(*, user_id: str, message_id: str, text: str, group_id: str = GROUP_ID) -> FakeEvent:
    return FakeEvent(
        self_id=BOT_UID,
        user_id=user_id,
        message_id=message_id,
        message=[Seg("text", text=text)],
        raw_message=text,
        sender=FakeSenderInfo("漂♂总" if user_id == OWNER_UID else "普通群友"),
        group_id=group_id,
    )


def build_recent_messages(*, include_xiaowei: bool = True) -> list[dict]:
    rows = [
        {
            "message_id": "r-0",
            "user_id": "10001",
            "uid": "10001",
            "nick": "路人甲",
            "text": "今天天气一般",
            "content": "今天天气一般",
            "timestamp": 1,
        }
    ]
    if include_xiaowei:
        rows.append(
            {
                "message_id": "r-1",
                "user_id": XIAOWEI_UID,
                "uid": XIAOWEI_UID,
                "nick": "小维",
                "text": "我觉得这句不太对",
                "content": "我觉得这句不太对",
                "timestamp": 2,
            }
        )
    rows.append(
        {
            "message_id": "r-2",
            "user_id": "10002",
            "uid": "10002",
            "nick": "路人乙",
            "text": "继续看戏",
            "content": "继续看戏",
            "timestamp": 3,
        }
    )
    return rows


async def run_sandbox_case(
    mods: dict,
    *,
    text: str,
    user_id: str,
    message_id: str,
    config: DictConfig,
    explicit_enable: bool,
    dry_run: bool,
    model_reply: str = "收到，这句我来接。",
    recent_messages: list[dict] | None = None,
) -> dict:
    EventAdapter = mods["EventAdapter"]
    DecisionEngine = mods["DecisionEngine"]
    parse_owner_action = mods["parse_owner_action"]
    resolve_owner_action_context = mods["resolve_owner_action_context"]
    evaluate_owner_action_gate = mods["evaluate_owner_action_gate"]
    build_owner_action_execution_plan = mods["build_owner_action_execution_plan"]
    build_owner_action_reply_draft = mods["build_owner_action_reply_draft"]
    deliver_owner_action_current_session_if_enabled = mods["deliver_owner_action_current_session_if_enabled"]

    adapter = EventAdapter(owner_id=OWNER_UID, owner_uids=[OWNER_UID])
    engine = DecisionEngine(store=None, skill_loader=None)
    event = make_group_event(user_id=user_id, message_id=message_id, text=text)
    msg = adapter.adapt_group_msg(event)
    decision = engine.decide(msg)
    action = parse_owner_action(msg, config)

    bot = MockBot()
    sender_event = MockEventRef()
    context = None
    gate = None
    plan = None
    draft = None
    result = None

    if action is not None:
        msg.owner_action = action
        context = resolve_owner_action_context(
            action,
            msg,
            recent_messages=list(recent_messages or []),
            store=None,
            config=config,
        )
        msg.owner_action_context = context
        gate = evaluate_owner_action_gate(action, msg, config)
        msg.owner_action_gate = gate
        plan = build_owner_action_execution_plan(action, gate, msg, config)
        msg.owner_action_execution_plan = plan
        draft = build_owner_action_reply_draft(action, plan, model_reply, msg, config)
        msg.owner_action_reply_draft = draft
        result = await deliver_owner_action_current_session_if_enabled(
            draft,
            action,
            plan,
            msg,
            config,
            bot=bot,
            event=sender_event,
            explicit_enable=explicit_enable,
            dry_run=dry_run,
            gate=gate,
        )

    return {
        "msg": msg,
        "decision": decision,
        "action": action,
        "context": context,
        "gate": gate,
        "plan": plan,
        "draft": draft,
        "result": result,
        "bot": bot,
        "sender_event": sender_event,
    }


def read_audit_lines(audit_path: Path) -> list[dict]:
    if not audit_path.exists():
        return []
    lines = [line for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [json.loads(line) for line in lines]


def assert_audit_row_shape(row: dict) -> None:
    for field in ["action_type", "destination_type", "status", "mode", "real_send", "reason", "content_preview", "key"]:
        assert field in row


async def test_a_default_config_not_send(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(audit_path=str(audit_path), full_enable=False, dry_run=False)
        result = await run_sandbox_case(
            mods,
            text="秧秧 回应小维",
            user_id=OWNER_UID,
            message_id="owner-a-1",
            config=cfg,
            explicit_enable=False,
            dry_run=False,
            recent_messages=build_recent_messages(include_xiaowei=True),
        )
        assert result["action"] is not None
        assert result["action"].action_type == "reply_current"
        assert result["context"] is not None
        assert result["context"].source == "recent_by_user"
        assert result["draft"] is not None
        assert result["draft"].status == "drafted"
        assert result["result"] is not None
        assert result["result"].delivered is False
        assert result["result"].real_send is False
        assert result["result"].delivery_mode in {"disabled", "blocked", "null", "not_attempted"}
        assert result["bot"].calls == []
        rows = read_audit_lines(audit_path)
        assert len(rows) == 1
        assert_audit_row_shape(rows[0])
        assert rows[0]["real_send"] is False
        print("[PASS] sandbox A default config -> no send")


async def test_b_full_enable_explicit_true_send_success(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(audit_path=str(audit_path), full_enable=True, dry_run=False)
        result = await run_sandbox_case(
            mods,
            text="秧秧 回应小维",
            user_id=OWNER_UID,
            message_id="owner-b-1",
            config=cfg,
            explicit_enable=True,
            dry_run=False,
            model_reply="小维，这句我先帮你接一下。",
            recent_messages=build_recent_messages(include_xiaowei=True),
        )
        assert result["result"] is not None
        assert result["result"].delivered is True
        assert result["result"].real_send is True
        assert result["result"].delivery_mode == "nonebot_current_session"
        assert result["bot"].calls == [(result["sender_event"], "小维，这句我先帮你接一下。")]
        rows = read_audit_lines(audit_path)
        assert len(rows) == 1
        assert_audit_row_shape(rows[0])
        assert rows[0]["action_type"] == "reply_current"
        assert rows[0]["destination_type"] == "current_session"
        assert rows[0]["real_send"] is True
        print("[PASS] sandbox B explicit enable current-session send success")


async def test_c_duplicate_blocked(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(audit_path=str(audit_path), full_enable=True, dry_run=False)
        common = dict(
            text="秧秧 回应小维",
            user_id=OWNER_UID,
            message_id="owner-c-dup-1",
            config=cfg,
            explicit_enable=True,
            dry_run=False,
            model_reply="重复触发测试内容",
            recent_messages=build_recent_messages(include_xiaowei=True),
        )
        first = await run_sandbox_case(mods, **common)
        second = await run_sandbox_case(mods, **common)
        assert first["result"] is not None and first["result"].delivered is True
        assert second["result"] is not None
        assert second["result"].delivered is False
        assert second["result"].real_send is False
        assert second["result"].reason.startswith("duplicate_blocked")
        assert len(first["bot"].calls) == 1
        assert second["bot"].calls == []
        rows = read_audit_lines(audit_path)
        assert len(rows) == 2
        assert any("duplicate_blocked" in row.get("reason", "") or row.get("duplicate") is True for row in rows)
        print("[PASS] sandbox C duplicate blocked")


async def test_d_dry_run_not_register_dedup(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(audit_path=str(audit_path), full_enable=True, dry_run=False)
        common = dict(
            text="秧秧 回应小维",
            user_id=OWNER_UID,
            message_id="owner-d-1",
            config=cfg,
            explicit_enable=True,
            model_reply="dry run 先不发",
            recent_messages=build_recent_messages(include_xiaowei=True),
        )
        dry = await run_sandbox_case(mods, dry_run=True, **common)
        real = await run_sandbox_case(mods, dry_run=False, **common)
        assert dry["result"] is not None
        assert dry["result"].delivered is False
        assert dry["result"].real_send is False
        assert dry["result"].reason == "dry_run_no_delivery"
        assert dry["bot"].calls == []
        assert real["result"] is not None
        assert real["result"].delivered is True
        assert real["result"].real_send is True
        assert len(real["bot"].calls) == 1
        rows = read_audit_lines(audit_path)
        assert len(rows) == 2
        assert rows[0]["real_send"] is False
        assert rows[1]["real_send"] is True
        print("[PASS] sandbox D dry_run does not pollute dedup")


async def test_e_cross_group_stays_locked(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(audit_path=str(audit_path), full_enable=True, dry_run=False)
        result = await run_sandbox_case(
            mods,
            text="去群里劝和一下",
            user_id=OWNER_UID,
            message_id="owner-e-1",
            config=cfg,
            explicit_enable=True,
            dry_run=False,
            model_reply="都先别吵。",
            recent_messages=build_recent_messages(include_xiaowei=True),
        )
        assert result["action"] is not None
        assert result["action"].action_type == "send_group_message"
        assert result["plan"] is not None
        assert result["plan"].destination_type == "group"
        assert result["result"] is not None
        assert result["result"].delivered is False
        assert result["result"].real_send is False
        assert any(token in result["result"].reason for token in ["send_group_locked", "cross_session_blocked", "group"])
        assert result["bot"].calls == []
        rows = read_audit_lines(audit_path)
        assert len(rows) == 1
        assert rows[0]["destination_type"] == "group"
        assert rows[0]["real_send"] is False
        print("[PASS] sandbox E cross-group stays locked")


async def test_f_non_owner_same_words_no_trigger(mods: dict) -> None:
    mods["reset_owner_action_delivery_safety_store"]()
    with tempfile.TemporaryDirectory() as tmpdir:
        audit_path = Path(tmpdir) / "audit.jsonl"
        cfg = build_config(audit_path=str(audit_path), full_enable=True, dry_run=False)
        result = await run_sandbox_case(
            mods,
            text="秧秧 回应小维",
            user_id="10086",
            message_id="member-f-1",
            config=cfg,
            explicit_enable=True,
            dry_run=False,
            recent_messages=build_recent_messages(include_xiaowei=True),
        )
        assert result["decision"].should_reply is False
        assert result["action"] is None
        assert result["context"] is None
        assert result["plan"] is None
        assert result["draft"] is None
        assert result["result"] is None
        assert result["bot"].calls == []
        assert read_audit_lines(audit_path) == []
        print("[PASS] sandbox F non-owner same words -> no trigger")


async def main() -> None:
    mods = prepare_modules()
    await test_a_default_config_not_send(mods)
    await test_b_full_enable_explicit_true_send_success(mods)
    await test_c_duplicate_blocked(mods)
    await test_d_dry_run_not_register_dedup(mods)
    await test_e_cross_group_stays_locked(mods)
    await test_f_non_owner_same_words_no_trigger(mods)
    print("[OK] test_current_session_sandbox_e2e.py")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
