from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from mock_pipeline_runtime import (  # type: ignore
    DictConfig,
    FakeBot,
    FakeEvent,
    FakeReply,
    FakeSenderInfo,
    Seg,
    prepare_modules,
)


DEFAULT_CFG = {
    "owner_uid": "335059272",
    "owner_uids": ["335059272"],
    "default_group_id": "137918147",
    "primary_group_id": "137918147",
    "member_aliases": {
        "小维": "3916107556",
        "红尘": "2434523727",
        "娅娅": "2690087239",
    },
    "dry_run": True,
    "owner_action_execution_enabled": False,
    "owner_action_allow_send_group_message": False,
    "owner_action_allow_reply_current": False,
    "owner_action_current_session_delivery_enabled": False,
    "owner_action_allow_internal_control": False,
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


async def run_owner_action_dryrun_case(
    mods: dict,
    *,
    text: str,
    user_id: str,
    group_id: str | None,
    cfg_data: dict | None = None,
    raw_message: str | None = None,
    recent_messages: list[dict] | None = None,
    reply_to_message_id: str | None = None,
    reply_to_user_id: str | None = None,
) -> dict:
    EventAdapter = mods["EventAdapter"]
    DecisionEngine = mods["DecisionEngine"]
    MemoryStore = mods["MemoryStore"]
    CooldownManager = mods["CooldownManager"]
    PromptBuilder = mods["PromptBuilder"]
    Sender = mods["Sender"]
    ModelRouter = mods["ModelRouter"]
    parse_owner_action = mods["parse_owner_action"]
    evaluate_owner_action_gate = mods["evaluate_owner_action_gate"]
    build_owner_action_execution_plan = mods["build_owner_action_execution_plan"]
    build_owner_action_reply_draft = mods["build_owner_action_reply_draft"]
    deliver_owner_action_reply_draft = mods["deliver_owner_action_reply_draft"]
    resolve_owner_action_context = mods["resolve_owner_action_context"]
    plugin = mods["plugin"]

    merged_cfg = dict(DEFAULT_CFG)
    if cfg_data:
        merged_cfg.update(cfg_data)
    cfg = DictConfig(merged_cfg)

    with tempfile.TemporaryDirectory() as tmpdir:
        store = MemoryStore(str(Path(tmpdir) / "chat.db"), str(Path(tmpdir) / "cache"))
        cooldown = CooldownManager(cfg)
        builder = PromptBuilder(store, skill_loader=None)
        engine = DecisionEngine(store=None, skill_loader=None)
        adapter = EventAdapter(owner_id="335059272", owner_uids=["335059272"])
        bot = FakeBot(self_id="90001")
        sender = Sender(bot, store, cooldown, bot_uid=bot.self_id, dry_run=True)

        reply = None
        if reply_to_message_id:
            reply = FakeReply(reply_to_message_id, reply_to_user_id or "")

        event = FakeEvent(
            self_id=bot.self_id,
            user_id=user_id,
            message_id=f"case-{user_id}-{group_id or 'private'}-{abs(hash((text, user_id, group_id))) % 100000}",
            message=[Seg("text", text=text)],
            raw_message=raw_message or text,
            sender=FakeSenderInfo("漂♂总" if user_id == "335059272" else "普通群友"),
            group_id=group_id,
            reply=reply,
        )
        recent_messages = list(recent_messages or [])

        if group_id:
            msg = adapter.adapt_group_msg(event)
        else:
            msg = adapter.adapt_private_msg(event)

        decision = engine.decide(msg)
        action = parse_owner_action(msg, cfg)
        gate = None
        plan = None
        draft = None
        if action is not None:
            msg.owner_action = action
            action_context = resolve_owner_action_context(
                action,
                msg,
                recent_messages=recent_messages,
                store=store,
                config=cfg,
            )
            msg.owner_action_context = action_context
            gate = evaluate_owner_action_gate(action, msg, cfg)
            plan = build_owner_action_execution_plan(action, gate, msg, cfg)
            msg.owner_action_gate = gate
            msg.owner_action_execution_plan = plan

        messages = builder.build_messages(msg, decision, history=[])
        system_context = "\n".join(item["content"] for item in messages if item["role"] == "system")

        sent_response = None
        rows = []
        delivery = None
        if decision.should_reply:
            response = ModelRouter.DRY_RUN_TEXT
            if plan is not None:
                draft = build_owner_action_reply_draft(action, plan, response, msg, cfg)
                msg.owner_action_reply_draft = draft
                delivery = await deliver_owner_action_reply_draft(draft, action, gate, plan, msg, cfg, sender=None)
                msg.owner_action_delivery_result = delivery
            if action is not None:
                response = f"{response}\n{plugin._format_owner_action_summary(action)}".strip()
                response = f"{response}\n{plugin.format_owner_action_context_summary(getattr(msg, 'owner_action_context', None))}".strip()
            if gate is not None:
                response = f"{response}\n{plugin._format_owner_action_gate_summary(gate)}".strip()
            if plan is not None:
                response = f"{response}\n{plugin._format_owner_action_execution_plan_summary(plan)}".strip()
            if draft is not None:
                response = f"{response}\n{plugin.format_owner_action_reply_draft_summary(draft)}".strip()
            if delivery is not None:
                response = f"{response}\n{plugin._format_owner_action_delivery_summary(delivery)}".strip()
            sent_response = response
            store.record_message(msg, is_bot=False)
            await sender.send(msg, decision, response, actual_tier="dry_run")
            rows = store.get_recent_messages(str(group_id or ""), limit=20, channel=None)

        return {
            "msg": msg,
            "decision": decision,
            "action": action,
            "context": getattr(msg, "owner_action_context", None),
            "gate": gate,
            "plan": plan,
            "draft": draft,
            "delivery": delivery,
            "messages": messages,
            "system_context": system_context,
            "bot": bot,
            "rows": rows,
            "response": sent_response,
        }


async def test_owner_private_mediate_default_group(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="去群里劝和一下",
        user_id="335059272",
        group_id=None,
    )
    msg = result["msg"]
    action = result["action"]
    gate = result["gate"]
    plan = result["plan"]
    assert msg.is_owner is True
    assert msg.owner_command is True
    assert action is not None
    assert action.action_type == "send_group_message"
    assert action.style == "mediate"
    assert action.target_group_id == "137918147"
    assert gate is not None and gate.reason == "send_group_message_pending:execution_disabled"
    assert gate.safe_to_execute is False
    assert gate.execution_enabled is False
    assert gate.blocked_by_config is True
    assert plan is not None and plan.destination_type == "group"
    assert plan.destination_id == "137918147"
    assert plan.real_send is False
    assert "action_type=send_group_message" in result["system_context"]
    assert "style=mediate" in result["system_context"]
    assert "target_group=137918147" in result["system_context"]
    assert "target_user=-" in result["system_context"]
    assert result["bot"].group_sent == []
    assert result["bot"].private_sent == []
    assert "[dry_run][owner_action] action=send_group_message style=mediate target_group=137918147" in result["response"]
    assert "[dry_run][owner_action_gate] mode=dry_run allowed=true reason=send_group_message_pending:execution_disabled safe=false execution_enabled=false blocked_by_config=true permission=send_group_message" in result["response"]
    assert "[dry_run][owner_action_executor] action=send_group_message destination=group:137918147 status=planned real_send=false" in result["response"]
    assert any(row["is_bot"] == 1 for row in result["rows"])
    print("[PASS] e2e dry_run: 私聊 去群里劝和一下")


async def test_owner_group_reply_xiaowei(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="回应小维",
        user_id="335059272",
        group_id="31003",
    )
    action = result["action"]
    gate = result["gate"]
    plan = result["plan"]
    assert action is not None
    assert action.action_type == "reply_current"
    assert action.style == "normal"
    assert action.target_group_id == "31003"
    assert action.target_user_id == "3916107556"
    assert gate is not None and gate.reason == "reply_current_pending:execution_disabled"
    assert gate.safe_to_execute is False
    assert gate.execution_enabled is False
    assert gate.blocked_by_config is True
    assert plan is not None and plan.destination_type == "current_session"
    assert plan.destination_id == "group:31003"
    assert plan.real_send is False
    assert "action_type=reply_current" in result["system_context"]
    assert "target_group=31003" in result["system_context"]
    assert "target_user=3916107556" in result["system_context"]
    print("[PASS] e2e dry_run: 群聊 回应小维")


async def test_owner_group_roast_yaya(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="补刀娅娅",
        user_id="335059272",
        group_id="31003",
    )
    action = result["action"]
    plan = result["plan"]
    assert action is not None
    assert action.action_type == "reply_current"
    assert action.style == "roast"
    assert action.target_group_id == "31003"
    assert action.target_user_id == "2690087239"
    assert result["gate"] is not None
    assert result["gate"].reason == "reply_current_pending:execution_disabled"
    assert plan is not None
    assert plan.status == "planned"
    assert plan.destination_type == "current_session"
    assert plan.destination_id == "group:31003"
    assert plan.real_send is False
    assert "style=roast" in result["system_context"]
    assert "target_user=2690087239" in result["system_context"]
    print("[PASS] e2e dry_run: 群聊 补刀娅娅")


async def test_owner_group_correct(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="纠错刚才那句",
        user_id="335059272",
        group_id="31003",
    )
    action = result["action"]
    plan = result["plan"]
    assert action is not None
    assert action.action_type == "reply_current"
    assert action.style == "correct"
    assert action.target_group_id == "31003"
    assert result["gate"] is not None
    assert result["gate"].reason == "reply_current_pending:execution_disabled"
    assert plan is not None
    assert plan.status == "planned"
    assert plan.destination_type == "current_session"
    assert plan.destination_id == "group:31003"
    assert plan.real_send is False
    assert "style=correct" in result["system_context"]
    print("[PASS] e2e dry_run: 群聊 纠错刚才那句")


async def test_owner_group_comment_default_reply_current(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="评价小维",
        user_id="335059272",
        group_id="31003",
    )
    action = result["action"]
    gate = result["gate"]
    plan = result["plan"]
    assert action is not None
    assert action.action_type == "reply_current"
    assert action.style == "comment"
    assert action.target_group_id == "31003"
    assert action.target_user_id == "3916107556"
    assert gate is not None and gate.reason == "reply_current_pending:execution_disabled"
    assert plan is not None and plan.destination_type == "current_session"
    assert plan.destination_id == "group:31003"
    assert plan.status == "planned"
    assert plan.real_send is False
    assert "style=comment" in result["system_context"]
    print("[PASS] e2e dry_run: 群聊 评价小维")


async def test_owner_group_cancel(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="别回了，收手",
        user_id="335059272",
        group_id="31003",
    )
    action = result["action"]
    gate = result["gate"]
    plan = result["plan"]
    assert action is not None
    assert action.action_type == "cancel_reply"
    assert gate is not None and gate.reason == "cancel_reply_pending:execution_disabled"
    assert plan is not None and plan.destination_type == "internal_control"
    assert plan.status == "planned"
    assert plan.real_send is False
    assert "action_type=cancel_reply" in result["system_context"]
    print("[PASS] e2e dry_run: 群聊 别回了，收手")


async def test_owner_group_silence(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="静默一下",
        user_id="335059272",
        group_id="31003",
    )
    action = result["action"]
    gate = result["gate"]
    plan = result["plan"]
    assert action is not None
    assert action.action_type == "silence_topic"
    assert gate is not None and gate.reason == "silence_topic_pending:execution_disabled"
    assert plan is not None and plan.destination_type == "internal_control"
    assert plan.status == "planned"
    assert plan.real_send is False
    assert "action_type=silence_topic" in result["system_context"]
    print("[PASS] e2e dry_run: 群聊 静默一下")


async def test_owner_quote_correct_context(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="纠错这个",
        user_id="335059272",
        group_id="31003",
        recent_messages=[
            {
                "message_id": "quoted-1",
                "user_id": "3916107556",
                "uid": "3916107556",
                "nick": "小维",
                "content": "昨天那句说反了",
                "text": "昨天那句说反了",
                "timestamp": 1,
            }
        ],
        reply_to_message_id="quoted-1",
        reply_to_user_id="3916107556",
    )
    context = result["context"]
    assert context is not None
    assert context.source == "quote"
    assert context.target_user_id == "3916107556"
    assert context.target_message_id == "quoted-1"
    assert len(context.target_messages) == 1
    assert "昨天那句说反了" in result["system_context"]
    assert "[dry_run][owner_action_context] source=quote target_user=3916107556 messages=1" in result["response"]
    print("[PASS] e2e dry_run: quote 上下文可见")


async def test_owner_reply_xiaowei_recent_by_user_context(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="回应小维",
        user_id="335059272",
        group_id="31003",
        recent_messages=[
            {"message_id": "m1", "user_id": "10001", "uid": "10001", "nick": "别人", "text": "路过", "timestamp": 1},
            {"message_id": "m2", "user_id": "3916107556", "uid": "3916107556", "nick": "小维", "text": "我觉得这句不对", "timestamp": 2},
            {"message_id": "m3", "user_id": "3916107556", "uid": "3916107556", "nick": "小维", "text": "你再看一下", "timestamp": 3},
        ],
    )
    context = result["context"]
    assert context is not None
    assert context.source == "recent_by_user"
    assert context.target_user_id == "3916107556"
    assert len(context.target_messages) >= 1
    assert "我觉得这句不对" in result["system_context"] or "你再看一下" in result["system_context"]
    print("[PASS] e2e dry_run: recent_by_user 上下文可见")


async def test_owner_mediate_recent_current_session_context(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="劝和一下",
        user_id="335059272",
        group_id="31003",
        recent_messages=[
            {"message_id": "m1", "user_id": "10001", "uid": "10001", "nick": "甲", "text": "你这说得太冲了", "timestamp": 1},
            {"message_id": "m2", "user_id": "10002", "uid": "10002", "nick": "乙", "text": "我只是不同意", "timestamp": 2},
            {"message_id": "m3", "user_id": "90001", "uid": "90001", "nick": "bot", "text": "[bot]", "timestamp": 3, "is_bot": True},
        ],
    )
    context = result["context"]
    assert context is not None
    assert context.source == "recent_current_session"
    assert len(context.target_messages) >= 1
    assert "你这说得太冲了" in result["system_context"]
    print("[PASS] e2e dry_run: recent_current_session 上下文可见")


async def test_owner_reply_xiaowei_context_not_found(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="回应小维",
        user_id="335059272",
        group_id="31003",
        recent_messages=[
            {"message_id": "m1", "user_id": "10001", "uid": "10001", "nick": "甲", "text": "只有别人说话", "timestamp": 1},
        ],
    )
    context = result["context"]
    assert context is not None
    assert context.source == "none"
    assert context.summary == "context_not_found"
    assert "上下文不足，谨慎回应" in result["system_context"]
    print("[PASS] e2e dry_run: context_not_found 可见")


async def test_non_owner_same_words_no_owner_action(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="去群里劝和一下",
        user_id="10086",
        group_id="31003",
    )
    msg = result["msg"]
    assert msg.is_owner is False
    assert msg.owner_command is False
    assert result["decision"].should_reply is False
    assert result["action"] is None
    assert result["gate"] is None
    assert result["plan"] is None
    assert "[OwnerAction]" not in result["system_context"]
    assert result["bot"].group_sent == []
    assert result["bot"].private_sent == []
    print("[PASS] e2e dry_run 反例: 普通群友无 owner action")


async def test_owner_plain_chat_no_owner_action(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="今天吃什么",
        user_id="335059272",
        group_id=None,
    )
    msg = result["msg"]
    assert msg.is_owner is True
    assert msg.owner_command is False
    assert result["decision"].should_reply is True
    assert result["action"] is None
    assert result["gate"] is None
    assert result["plan"] is None
    assert "[OwnerAction]" not in result["system_context"]
    assert result["response"] == mods["ModelRouter"].DRY_RUN_TEXT
    print("[PASS] e2e dry_run 反例: owner 普通闲聊无 owner action")


async def test_missing_target_group_blocked(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="去群里劝和一下",
        user_id="335059272",
        group_id=None,
        cfg_data={
            "default_group_id": "",
            "primary_group_id": "",
        },
    )
    action = result["action"]
    gate = result["gate"]
    plan = result["plan"]
    assert action is not None
    assert action.action_type == "send_group_message"
    assert action.target_group_id is None
    assert gate is not None and gate.mode == "blocked"
    assert gate.reason == "missing_target_group"
    assert plan is not None
    assert plan.status == "blocked"
    assert plan.destination_type == "none"
    assert plan.real_send is False
    assert "target_group=-" in result["system_context"]
    assert "[dry_run][owner_action_gate] mode=blocked allowed=false reason=missing_target_group safe=false execution_enabled=false blocked_by_config=false permission=send_group_message" in result["response"]
    assert "status=blocked real_send=false reason=missing_target_group" in result["response"]
    assert result["bot"].group_sent == []
    assert result["bot"].private_sent == []
    print("[PASS] e2e dry_run 反例: 缺 target_group 被 gate blocked")


async def test_execution_enabled_still_real_send_false(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="回应小维",
        user_id="335059272",
        group_id="31003",
        cfg_data={
            "owner_action_execution_enabled": True,
            "owner_action_allow_send_group_message": True,
            "owner_action_allow_reply_current": True,
            "owner_action_allow_internal_control": True,
        },
    )
    gate = result["gate"]
    plan = result["plan"]
    assert gate is not None
    assert gate.execution_enabled is True
    assert gate.blocked_by_config is False
    assert gate.safe_to_execute is False
    assert gate.reason == "reply_current_pending:dry_run_only"
    assert plan is not None
    assert plan.real_send is False
    assert plan.reason == "reply_current_pending:dry_run_only"
    assert "real_send=false" in result["response"]
    print("[PASS] e2e dry_run: execution_enabled 仍不真实发送")


async def test_reply_draft_drafted_current_session(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="回应小维",
        user_id="335059272",
        group_id="31003",
    )
    draft = result["draft"]
    assert draft is not None
    assert draft.status == "drafted"
    assert draft.destination_type == "current_session"
    assert draft.destination_id == "group:31003"
    assert draft.real_send is False
    assert draft.content_length == len(mods["ModelRouter"].DRY_RUN_TEXT)
    assert draft.content_preview.startswith("[dry_run] 模拟回复")
    assert "[dry_run][owner_action_reply_draft] destination=current_session:group:31003 status=drafted" in result["response"]
    print("[PASS] e2e dry_run: reply_current draft 可见")


async def test_reply_draft_drafted_group_destination(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="去群里劝和一下",
        user_id="335059272",
        group_id=None,
    )
    draft = result["draft"]
    assert draft is not None
    assert draft.status == "drafted"
    assert draft.destination_type == "group"
    assert draft.destination_id == "137918147"
    assert draft.real_send is False
    print("[PASS] e2e dry_run: send_group_message draft 可见")


async def test_reply_draft_blocked_when_plan_blocked(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="去群里劝和一下",
        user_id="335059272",
        group_id=None,
        cfg_data={"default_group_id": "", "primary_group_id": ""},
    )
    draft = result["draft"]
    assert draft is not None
    assert draft.status == "blocked"
    assert draft.real_send is False
    assert draft.reason == "missing_target_group"
    print("[PASS] e2e dry_run: blocked plan draft blocked")


async def test_reply_draft_empty_model_reply_blocked(mods: dict) -> None:
    build_owner_action_reply_draft = mods["build_owner_action_reply_draft"]
    action = mods["OwnerAction"](
        action_type="reply_current",
        style="normal",
        target_group_id="31003",
        target_user_id="3916107556",
        raw_text="回应小维",
        reason="test",
        confidence=1.0,
    )
    plan = mods["OwnerActionExecutionPlan"](
        action_type="reply_current",
        destination_type="current_session",
        destination_id="group:31003",
        style="normal",
        status="planned",
        real_send=False,
        reason="reply_current_pending:execution_disabled",
    )
    draft = build_owner_action_reply_draft(action, plan, "   ", None, DictConfig(DEFAULT_CFG))
    assert draft.status == "blocked"
    assert draft.reason == "empty_reply"
    assert draft.real_send is False
    print("[PASS] unit: empty model reply blocked")


async def test_reply_draft_preview_truncated(mods: dict) -> None:
    build_owner_action_reply_draft = mods["build_owner_action_reply_draft"]
    long_reply = "A" * 300
    action = mods["OwnerAction"](
        action_type="reply_current",
        style="normal",
        target_group_id="31003",
        target_user_id="3916107556",
        raw_text="回应小维",
        reason="test",
        confidence=1.0,
    )
    plan = mods["OwnerActionExecutionPlan"](
        action_type="reply_current",
        destination_type="current_session",
        destination_id="group:31003",
        style="normal",
        status="planned",
        real_send=False,
        reason="reply_current_pending:execution_disabled",
    )
    draft = build_owner_action_reply_draft(action, plan, long_reply, None, DictConfig(DEFAULT_CFG))
    assert draft.status == "drafted"
    assert draft.content_length == 300
    assert len(draft.content_preview) <= 121
    assert draft.content_preview.endswith("…")
    print("[PASS] unit: reply draft preview truncated")


async def test_internal_control_draft_preview(mods: dict) -> None:
    build_owner_action_reply_draft = mods["build_owner_action_reply_draft"]
    action = mods["OwnerAction"](
        action_type="cancel_reply",
        style="normal",
        target_group_id="31003",
        target_user_id=None,
        raw_text="别回了，收手",
        reason="test",
        confidence=1.0,
    )
    plan = mods["OwnerActionExecutionPlan"](
        action_type="cancel_reply",
        destination_type="internal_control",
        destination_id=None,
        style="normal",
        status="planned",
        real_send=False,
        reason="cancel_reply_pending:execution_disabled",
    )
    draft = build_owner_action_reply_draft(action, plan, "", None, DictConfig(DEFAULT_CFG))
    assert draft is not None
    assert draft.status == "drafted"
    assert draft.destination_type == "internal_control"
    assert draft.real_send is False
    assert "control draft" in draft.content_preview
    print("[PASS] unit: internal_control draft 可见")


class FakeCurrentSessionSender:
    is_fake_sender = True

    def __init__(self):
        self.calls: list[dict] = []

    async def deliver_owner_action_reply(
        self,
        *,
        content: str,
        destination_type: str,
        destination_id: str | None,
        action,
        draft,
        plan,
    ):
        self.calls.append(
            {
                "content": content,
                "destination_type": destination_type,
                "destination_id": destination_id,
                "action_type": getattr(action, "action_type", None),
                "draft_status": getattr(draft, "status", None),
                "plan_status": getattr(plan, "status", None),
            }
        )
        return True


async def test_sender_adapter_null_sender(mods: dict) -> None:
    NullSenderAdapter = mods["NullSenderAdapter"]
    SendResult = mods["SendResult"]
    adapter = NullSenderAdapter()
    message = type("Msg", (), {"channel": "group", "group_id": "31003", "uid": "335059272"})()
    result = await adapter.send_current_session(message, "测试")
    assert isinstance(result, SendResult)
    assert result.attempted is False
    assert result.delivered is False
    assert result.real_send is False
    assert result.mode == "null"
    assert result.destination_type == "current_session"
    assert result.destination_id == "group:31003"
    assert result.content_length == 2
    print("[PASS] sender adapter: NullSenderAdapter 安全不发送")


async def test_sender_adapter_fake_sender_records(mods: dict) -> None:
    FakeSenderAdapter = mods["FakeSenderAdapter"]
    adapter = FakeSenderAdapter()
    message = type("Msg", (), {"channel": "private", "uid": "12345", "group_id": None})()
    result = await adapter.send_current_session(message, "fake hello")
    assert result.attempted is True
    assert result.delivered is True
    assert result.real_send is True
    assert result.mode == "fake"
    assert result.reason == "fake_sender"
    assert len(adapter.sent_messages) == 1
    assert adapter.sent_messages[0]["content"] == "fake hello"
    assert adapter.sent_messages[0]["destination_id"] == "private:12345"
    print("[PASS] sender adapter: FakeSenderAdapter 记录调用")


async def test_delivery_default_sender_safe_blocked(mods: dict) -> None:
    build_owner_action_reply_draft = mods["build_owner_action_reply_draft"]
    deliver_owner_action_reply_draft = mods["deliver_owner_action_reply_draft"]
    result = await run_owner_action_dryrun_case(
        mods,
        text="回应小维",
        user_id="335059272",
        group_id="31003",
        cfg_data={
            "dry_run": False,
            "owner_action_execution_enabled": True,
            "owner_action_allow_reply_current": True,
            "owner_action_current_session_delivery_enabled": True,
        },
    )
    cfg = DictConfig({
        **DEFAULT_CFG,
        "dry_run": False,
        "owner_action_execution_enabled": True,
        "owner_action_allow_reply_current": True,
        "owner_action_current_session_delivery_enabled": True,
    })
    draft = build_owner_action_reply_draft(result["action"], result["plan"], "测试默认 sender", result["msg"], cfg)
    delivery = await deliver_owner_action_reply_draft(
        draft, result["action"], result["gate"], result["plan"], result["msg"], cfg
    )
    assert delivery.mode == "blocked"
    assert delivery.reason == "no_sender"
    assert delivery.real_send is False
    assert delivery.delivered is False
    print("[PASS] delivery: 默认 sender 安全阻断")


async def test_delivery_dry_run_does_not_call_fake_sender(mods: dict) -> None:
    build_owner_action_reply_draft = mods["build_owner_action_reply_draft"]
    deliver_owner_action_reply_draft = mods["deliver_owner_action_reply_draft"]
    FakeSenderAdapter = mods["FakeSenderAdapter"]
    result = await run_owner_action_dryrun_case(
        mods,
        text="回应小维",
        user_id="335059272",
        group_id="31003",
        cfg_data={
            "dry_run": True,
            "owner_action_execution_enabled": True,
            "owner_action_allow_reply_current": True,
            "owner_action_current_session_delivery_enabled": True,
        },
    )
    cfg = DictConfig({
        **DEFAULT_CFG,
        "dry_run": True,
        "owner_action_execution_enabled": True,
        "owner_action_allow_reply_current": True,
        "owner_action_current_session_delivery_enabled": True,
    })
    sender = FakeSenderAdapter()
    draft = build_owner_action_reply_draft(result["action"], result["plan"], "测试 dry run", result["msg"], cfg)
    delivery = await deliver_owner_action_reply_draft(
        draft, result["action"], result["gate"], result["plan"], result["msg"], cfg, sender=sender
    )
    assert delivery.mode == "dry_run"
    assert delivery.delivered is False
    assert delivery.real_send is False
    assert sender.sent_messages == []
    print("[PASS] delivery: dry_run 不调用 FakeSenderAdapter")


async def test_delivery_default_disabled_with_draft(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="回应小维",
        user_id="335059272",
        group_id="31003",
    )
    delivery = result["delivery"]
    assert delivery is not None
    assert delivery.mode == "disabled"
    assert delivery.delivered is False
    assert delivery.real_send is False
    assert delivery.reason in {"execution_disabled", "current_session_delivery_disabled"}
    assert "[dry_run][owner_action_delivery] mode=disabled" in result["response"]
    print("[PASS] delivery: 默认配置 reply_current 禁投递")


async def test_delivery_dry_run_even_if_all_open(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="回应小维",
        user_id="335059272",
        group_id="31003",
        cfg_data={
            "dry_run": True,
            "owner_action_execution_enabled": True,
            "owner_action_allow_reply_current": True,
            "owner_action_current_session_delivery_enabled": True,
        },
    )
    delivery = result["delivery"]
    assert delivery is not None
    assert delivery.mode == "dry_run"
    assert delivery.real_send is False
    assert delivery.delivered is False
    print("[PASS] delivery: dry_run 下永不真实投递")


async def test_delivery_fake_sender_current_session_enabled(mods: dict) -> None:
    build_owner_action_reply_draft = mods["build_owner_action_reply_draft"]
    deliver_owner_action_reply_draft = mods["deliver_owner_action_reply_draft"]
    FakeSenderAdapter = mods["FakeSenderAdapter"]
    result = await run_owner_action_dryrun_case(
        mods,
        text="回应小维",
        user_id="335059272",
        group_id="31003",
        cfg_data={
            "dry_run": False,
            "owner_action_execution_enabled": True,
            "owner_action_allow_reply_current": True,
            "owner_action_current_session_delivery_enabled": True,
        },
    )
    sender = FakeSenderAdapter()
    draft = build_owner_action_reply_draft(result["action"], result["plan"], "测试投递", result["msg"], DictConfig({
        **DEFAULT_CFG,
        "dry_run": False,
        "owner_action_execution_enabled": True,
        "owner_action_allow_reply_current": True,
        "owner_action_current_session_delivery_enabled": True,
    }))
    delivery = await deliver_owner_action_reply_draft(
        draft,
        result["action"],
        result["gate"],
        result["plan"],
        result["msg"],
        DictConfig({
            **DEFAULT_CFG,
            "dry_run": False,
            "owner_action_execution_enabled": True,
            "owner_action_allow_reply_current": True,
            "owner_action_current_session_delivery_enabled": True,
        }),
        sender=sender,
    )
    assert delivery.mode == "fake"
    assert delivery.delivered is True
    assert delivery.real_send is True
    assert sender.sent_messages
    assert sender.sent_messages[0]["destination_type"] == "current_session"
    print("[PASS] delivery: fake sender 可验证当前会话投递")


async def test_delivery_send_group_message_still_blocked(mods: dict) -> None:
    build_owner_action_reply_draft = mods["build_owner_action_reply_draft"]
    deliver_owner_action_reply_draft = mods["deliver_owner_action_reply_draft"]
    FakeSenderAdapter = mods["FakeSenderAdapter"]
    result = await run_owner_action_dryrun_case(
        mods,
        text="去群里劝和一下",
        user_id="335059272",
        group_id=None,
        cfg_data={
            "dry_run": False,
            "owner_action_execution_enabled": True,
            "owner_action_allow_send_group_message": True,
            "owner_action_current_session_delivery_enabled": True,
        },
    )
    sender = FakeSenderAdapter()
    draft = build_owner_action_reply_draft(result["action"], result["plan"], "测试跨群", result["msg"], DictConfig(DEFAULT_CFG))
    delivery = await deliver_owner_action_reply_draft(
        draft, result["action"], result["gate"], result["plan"], result["msg"], DictConfig({
            **DEFAULT_CFG,
            "dry_run": False,
            "owner_action_execution_enabled": True,
            "owner_action_allow_send_group_message": True,
            "owner_action_current_session_delivery_enabled": True,
        }), sender=sender
    )
    assert delivery.mode == "blocked"
    assert delivery.real_send is False
    assert "cross_session_blocked" in delivery.reason or "send_group_locked" in delivery.reason
    assert sender.sent_messages == []
    print("[PASS] delivery: send_group_message 继续锁死")


async def test_delivery_internal_control_blocked(mods: dict) -> None:
    build_owner_action_reply_draft = mods["build_owner_action_reply_draft"]
    deliver_owner_action_reply_draft = mods["deliver_owner_action_reply_draft"]
    result = await run_owner_action_dryrun_case(
        mods,
        text="别回了，收手",
        user_id="335059272",
        group_id="31003",
    )
    draft = build_owner_action_reply_draft(result["action"], result["plan"], "", result["msg"], DictConfig(DEFAULT_CFG))
    delivery = await deliver_owner_action_reply_draft(
        draft, result["action"], result["gate"], result["plan"], result["msg"], DictConfig(DEFAULT_CFG), sender=FakeCurrentSessionSender()
    )
    assert delivery.mode == "blocked"
    assert "internal_control_not_implemented" in delivery.reason
    print("[PASS] delivery: internal_control 未实现")


async def test_delivery_no_sender_blocked(mods: dict) -> None:
    build_owner_action_reply_draft = mods["build_owner_action_reply_draft"]
    deliver_owner_action_reply_draft = mods["deliver_owner_action_reply_draft"]
    result = await run_owner_action_dryrun_case(
        mods,
        text="回应小维",
        user_id="335059272",
        group_id="31003",
        cfg_data={
            "dry_run": False,
            "owner_action_execution_enabled": True,
            "owner_action_allow_reply_current": True,
            "owner_action_current_session_delivery_enabled": True,
        },
    )
    cfg = DictConfig({
        **DEFAULT_CFG,
        "dry_run": False,
        "owner_action_execution_enabled": True,
        "owner_action_allow_reply_current": True,
        "owner_action_current_session_delivery_enabled": True,
    })
    draft = build_owner_action_reply_draft(result["action"], result["plan"], "测试", result["msg"], cfg)
    delivery = await deliver_owner_action_reply_draft(
        draft, result["action"], result["gate"], result["plan"], result["msg"], cfg, sender=None
    )
    assert delivery.mode == "blocked"
    assert delivery.reason == "no_sender"
    assert delivery.real_send is False
    print("[PASS] delivery: 无 sender 时阻断")


async def test_non_owner_no_delivery_result(mods: dict) -> None:
    result = await run_owner_action_dryrun_case(
        mods,
        text="回应小维",
        user_id="10086",
        group_id="31003",
    )
    assert result["action"] is None
    assert result["delivery"] is None
    print("[PASS] delivery: 普通群友不产生 delivery_result")


async def main() -> int:
    mods = prepare_modules()
    await test_owner_private_mediate_default_group(mods)
    await test_owner_group_reply_xiaowei(mods)
    await test_owner_group_roast_yaya(mods)
    await test_owner_group_correct(mods)
    await test_owner_group_comment_default_reply_current(mods)
    await test_owner_group_cancel(mods)
    await test_owner_group_silence(mods)
    await test_owner_quote_correct_context(mods)
    await test_reply_draft_drafted_current_session(mods)
    await test_reply_draft_drafted_group_destination(mods)
    await test_reply_draft_blocked_when_plan_blocked(mods)
    await test_reply_draft_empty_model_reply_blocked(mods)
    await test_reply_draft_preview_truncated(mods)
    await test_internal_control_draft_preview(mods)
    await test_sender_adapter_null_sender(mods)
    await test_sender_adapter_fake_sender_records(mods)
    await test_owner_reply_xiaowei_recent_by_user_context(mods)
    await test_owner_mediate_recent_current_session_context(mods)
    await test_owner_reply_xiaowei_context_not_found(mods)
    await test_delivery_default_disabled_with_draft(mods)
    await test_delivery_default_sender_safe_blocked(mods)
    await test_delivery_dry_run_even_if_all_open(mods)
    await test_delivery_dry_run_does_not_call_fake_sender(mods)
    await test_delivery_fake_sender_current_session_enabled(mods)
    await test_delivery_send_group_message_still_blocked(mods)
    await test_delivery_internal_control_blocked(mods)
    await test_delivery_no_sender_blocked(mods)
    await test_non_owner_no_delivery_result(mods)
    await test_non_owner_same_words_no_owner_action(mods)
    await test_owner_plain_chat_no_owner_action(mods)
    await test_missing_target_group_blocked(mods)
    await test_execution_enabled_still_real_send_false(mods)
    print("[PASS] owner_action e2e dry_run tests finished")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
