from __future__ import annotations

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


def make_group_event(*, user_id: str, text: str, message=None, raw_message: str | None = None) -> FakeEvent:
    return FakeEvent(
        self_id=BOT_UID,
        user_id=user_id,
        message_id=f"msg-{abs(hash((user_id, text, raw_message))) % 100000}",
        message=message if message is not None else [Seg("text", text=text)],
        raw_message=raw_message if raw_message is not None else text,
        sender=FakeSenderInfo("阿漂" if user_id == OWNER_UID else "普通群友"),
        group_id=GROUP_ID,
    )


def build_config() -> DictConfig:
    return DictConfig(
        {
            "owner_uid": OWNER_UID,
            "owner_uids": [OWNER_UID],
            "bot_name": "秧秧",
            "member_aliases": {
                "小维": "3916107556",
                "红尘": "2434523727",
                "娅娅": "2690087239",
            },
        }
    )


def test_non_trigger_cases(mods: dict) -> None:
    EventAdapter = mods["EventAdapter"]
    DecisionEngine = mods["DecisionEngine"]
    parse_owner_action = mods["parse_owner_action"]

    adapter = EventAdapter(owner_id=OWNER_UID, owner_uids=[OWNER_UID])
    engine = DecisionEngine(store=None, skill_loader=None)
    config = build_config()

    cases = [
        "你怎么不回复捏啊233",
        "怎么没人回复我",
        "这句话不用回复",
        "回复这个词只是普通聊天",
        "回应一下也只是说说",
    ]

    for text in cases:
        msg = adapter.adapt_group_msg(make_group_event(user_id=OWNER_UID, text=text))
        decision = engine.decide(msg)
        action = parse_owner_action(msg, config)
        assert msg.is_owner is True
        assert msg.is_at_bot is False
        assert msg.owner_command is False, text
        assert msg.explicit_command is False, text
        assert action is None, text
        assert decision.should_reply is False, text
        assert decision.reason == "default_silent", text

    print("[PASS] phase6c non-trigger cases")


def test_trigger_cases(mods: dict) -> None:
    EventAdapter = mods["EventAdapter"]
    DecisionEngine = mods["DecisionEngine"]
    parse_owner_action = mods["parse_owner_action"]

    adapter = EventAdapter(owner_id=OWNER_UID, owner_uids=[OWNER_UID])
    engine = DecisionEngine(store=None, skill_loader=None)
    config = build_config()

    at_bot = adapter.adapt_group_msg(
        make_group_event(
            user_id=OWNER_UID,
            text="你好",
            message=[Seg("at", qq=BOT_UID), Seg("text", text=" 你好")],
            raw_message=f"[CQ:at,qq={BOT_UID}] 你好",
        )
    )
    at_bot_decision = engine.decide(at_bot)
    assert at_bot.is_at_bot is True
    assert at_bot.owner_command is True
    assert at_bot.explicit_command is True
    assert at_bot_decision.should_reply is True
    assert at_bot_decision.reason == "owner_explicit_command"

    command_texts = [
        "/yy-smoke-current 回应小维",
        "秧秧smoke 回应小维",
        "秧秧 回应小维",
        "秧秧 帮我回复小维",
        "/yy 回应小维",
        "小云雀 总结一下",
    ]

    for text in command_texts:
        msg = adapter.adapt_group_msg(make_group_event(user_id=OWNER_UID, text=text))
        action = parse_owner_action(msg, config)
        if action is not None:
            msg.owner_command = True
            msg.explicit_command = True
        decision = engine.decide(msg)
        assert (msg.owner_command or msg.explicit_command) is True, text
        assert decision.should_reply is True, text
        assert decision.reason == "owner_explicit_command", text
        if "回应小维" in text or "帮我回复小维" in text:
            assert action is not None, text
            assert action.action_type == "reply_current", text
            assert action.target_user_id == "3916107556", text

    print("[PASS] phase6c trigger cases")


def main() -> None:
    mods = prepare_modules()
    test_non_trigger_cases(mods)
    test_trigger_cases(mods)
    print("PASS")


if __name__ == "__main__":
    main()
