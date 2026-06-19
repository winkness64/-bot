from __future__ import annotations

from types import SimpleNamespace

from mock_pipeline_runtime import prepare_modules  # type: ignore


mods = prepare_modules()
PromptBuilder = mods["PromptBuilder"]
Decision = mods["Decision"]
plugin = mods["plugin"]


OWNER_UID = "335059272"
COLD_BACKUP_PATH = PromptBuilder.OWNER_COLD_BACKUP_PATH


def _builder_without_external_files(tmp_path):
    builder = PromptBuilder(store=None, skill_loader=None)
    builder.PUBLIC_MEMORY_PATH = tmp_path / "missing_public_memory.txt"
    builder.PRIVATE_MEMORY_PATH = tmp_path / "missing_private_memory.txt"
    return builder


def _decision(target_uid: str | None) -> object:
    return Decision(True, "warm", "v4_flash", 3, target_uid=target_uid, reason="test", is_forced=True)


def _msg(**overrides):
    base = {
        "msg_id": "m-owner-private-context",
        "uid": OWNER_UID,
        "nick": "漂♂总",
        "group_id": "",
        "channel": "private",
        "text": "测试 owner 私聊 prompt",
        "raw_content": "测试 owner 私聊 prompt",
        "is_owner": True,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _system_from_messages(messages: list[dict[str, str]]) -> str:
    return "\n\n".join(item["content"] for item in messages if item["role"] == "system")


def test_owner_private_messages_include_owner_context_without_active_path_by_default(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    msg = _msg()

    messages = builder.build_messages(msg, _decision(OWNER_UID), history=[])
    system = _system_from_messages(messages)

    assert "[OwnerPrivateContext]" in system
    assert "漂♂总" in system
    assert "娅娅" in system
    assert "I叔" in system
    assert "艾萨克" in system
    assert COLD_BACKUP_PATH not in system
    assert "受控备份位置" in system
    assert "代码层 user_id gate" in system
    assert "唯一 owner / 最高授权入口" in system
    assert "不承接陪伴人格设定" in system


def test_owner_private_explicit_path_query_may_include_controlled_path_context(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    msg = _msg(text="冷备路径是什么？", raw_content="冷备路径是什么？")

    messages = builder.build_messages(msg, _decision(OWNER_UID), history=[])
    system = _system_from_messages(messages)

    assert "[OwnerPrivateContext]" in system
    assert "[路径与系统信息输出规则]" in system
    assert COLD_BACKUP_PATH in system
    assert "本轮已出现 owner 私聊明确路径/文件位置/部署细节询问" in system



def test_owner_private_system_includes_opsec_path_guard(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    msg = _msg(text="秧秧，按你现在的迁移记忆说一下模型分工和搬家路线。", raw_content="秧秧，按你现在的迁移记忆说一下模型分工和搬家路线。")

    messages = builder.build_messages(msg, _decision(OWNER_UID), history=[])
    system = _system_from_messages(messages)

    assert system.count("[路径与系统信息输出规则]") == 1
    assert "不要主动输出本机绝对路径、服务器路径、配置路径、配置文件路径、日志路径" in system
    assert "用户明确询问路径、命令、文件位置、部署细节时，才允许进入受控回答" in system
    assert "冷备目录" in system
    assert "项目目录" in system
    assert "受控备份位置" in system
    assert "日志位置" in system
    assert "不要在群聊或非 owner 私聊输出这些信息" in system


def test_owner_private_opsec_path_guard_coexists_with_c4_fact_guard(tmp_path) -> None:
    class FakeStore:
        def build_memory_prompt(self, user_id: str, session_id: str, query: str = "") -> str:
            return "[来自长期记忆的事实]\n- 搬家路线：先整理冷备，再迁入项目目录。"

    builder = PromptBuilder(store=FakeStore(), skill_loader=None, memory_enabled=True)
    builder.PUBLIC_MEMORY_PATH = tmp_path / "missing_public_memory.txt"
    builder.PRIVATE_MEMORY_PATH = tmp_path / "missing_private_memory.txt"

    system = builder.build_system(
        "private",
        target_uid=OWNER_UID,
        reply_style="warm",
        session_id=f"private:{OWNER_UID}",
        current_text="秧秧，按你现在的迁移记忆说一下模型分工和搬家路线。",
        sender_uid=OWNER_UID,
    )

    assert system.count("[路径与系统信息输出规则]") == 1
    assert "[来自长期记忆的事实]" in system
    assert "[长期记忆事实使用规则]" in system
    assert "具体事实、名称、阶段、分工与路径" in system
    assert "路径与系统信息输出规则" in system
    assert system.index("[路径与系统信息输出规则]") < system.index("[来自长期记忆的事实]")
    assert system.index("[来自长期记忆的事实]") < system.index("[长期记忆事实使用规则]")


def test_non_owner_and_group_system_do_not_include_opsec_path_guard(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)

    non_owner = builder.build_system("private", target_uid="10001", reply_style="warm", sender_uid="10001")
    group = builder.build_system("group", target_uid=OWNER_UID, reply_style="warm", sender_uid=OWNER_UID)

    assert "[路径与系统信息输出规则]" not in non_owner
    assert "[路径与系统信息输出规则]" not in group


def test_non_owner_private_messages_do_not_include_owner_context(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    msg = _msg(uid="10001", nick="普通用户", is_owner=False, text="普通私聊", raw_content="普通私聊")

    messages = builder.build_messages(msg, _decision("10001"), history=[])
    system = _system_from_messages(messages)

    assert "[OwnerPrivateContext]" not in system
    assert "唯一 owner / 最高授权入口" not in system
    assert "代码层 user_id gate" not in system
    assert COLD_BACKUP_PATH not in system
    assert "不要套用 owner 专属称呼" in system


def test_group_messages_never_include_owner_context_even_when_target_is_owner(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    msg = _msg(channel="group", group_id="137918147", is_owner=True, text="@bot 测试", raw_content="@bot 测试")

    messages = builder.build_messages(msg, _decision(OWNER_UID), history=[])
    system = _system_from_messages(messages)

    assert "[OwnerPrivateContext]" not in system
    assert "唯一 owner / 最高授权入口" not in system
    assert "代码层 user_id gate" not in system
    assert COLD_BACKUP_PATH not in system
    assert "群聊中只有外层规则已放行时才简短回应" in system


def test_build_system_direct_call_default_does_not_inject_owner_context(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)

    system = builder.build_system("private", target_uid=OWNER_UID, reply_style="warm")

    assert "[OwnerPrivateContext]" not in system
    assert "唯一 owner / 最高授权入口" not in system
    assert "代码层 user_id gate" not in system
    assert COLD_BACKUP_PATH not in system


def test_build_system_direct_call_requires_private_and_sender_uid(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)

    private_system = builder.build_system(
        "private",
        target_uid=OWNER_UID,
        reply_style="warm",
        sender_uid=OWNER_UID,
        current_text="冷备路径是什么？",
    )
    group_system = builder.build_system("group", target_uid=OWNER_UID, reply_style="warm", sender_uid=OWNER_UID)
    non_owner_system = builder.build_system("private", target_uid="10001", reply_style="warm", sender_uid="10001")
    conflicting_target_system = builder.build_system(
        "private", target_uid="10001", reply_style="warm", sender_uid=OWNER_UID
    )

    assert "[OwnerPrivateContext]" in private_system
    assert COLD_BACKUP_PATH in private_system
    assert "[OwnerPrivateContext]" not in group_system
    assert "[OwnerPrivateContext]" not in non_owner_system
    assert "[OwnerPrivateContext]" not in conflicting_target_system


def test_owner_private_message_sender_label_keeps_owner_nick_for_private_thread(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    msg = _msg(text="普通私聊", raw_content="普通私聊")

    messages = builder.build_messages(msg, _decision(OWNER_UID), history=[])

    assert messages[-1]["content"].startswith("漂♂总:")


def test_non_owner_private_message_sender_label_avoids_owner_alias_collision(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)

    for uid, nick in [("10004", "漂♂总"), ("10005", "漂泊者"), ("10006", "漂♂总本人")]:
        msg = _msg(uid=uid, nick=nick, is_owner=False, text="普通私聊", raw_content="普通私聊")

        messages = builder.build_messages(msg, _decision(uid), history=[])

        assert messages[-1]["content"].startswith("用户:")
        assert not messages[-1]["content"].startswith(f"{nick}:")


plugin = mods["plugin"]


def test_owner_private_messages_include_session_anchor_when_state_present(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    msg = _msg(text="继续", raw_content="继续")
    session_id = builder.derive_session_id(msg)
    builder.session_state_store.update(
        session_id,
        current_task="先出diff再落",
        todo_items=["先出diff再落", "继续接写回"],
        recent_decisions=["漂♂总要求：先出diff再落"],
        last_tool_summary="direct_reply tier=v4_flash",
    )

    messages = builder.build_messages(msg, _decision(OWNER_UID), history=[])
    system = _system_from_messages(messages)

    assert "[SessionAnchor]" in system
    assert "current_task: 先出diff再落" in system
    assert "todo_items:" in system
    assert "- 继续接写回" in system
    assert "recent_decisions:" in system
    assert "last_tool_summary: direct_reply tier=v4_flash" in system


def test_non_owner_private_messages_do_not_include_session_anchor(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    msg = _msg(uid="10001", nick="普通用户", is_owner=False, text="继续", raw_content="继续")
    session_id = builder.derive_session_id(msg)
    builder.session_state_store.update(
        session_id,
        current_task="不该出现的任务",
        todo_items=["不该出现的任务"],
        recent_decisions=["不该出现的决策"],
        last_tool_summary="direct_reply tier=v4_flash",
    )

    messages = builder.build_messages(msg, _decision("10001"), history=[])
    system = _system_from_messages(messages)

    assert "[SessionAnchor]" not in system
    assert "不该出现的任务" not in system
    assert "不该出现的决策" not in system


def test_update_owner_private_session_state_inherits_current_task_for_continue(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"

    first_msg = _msg(text="先出diff再落", raw_content="先出diff再落")
    plugin._update_owner_private_session_state(
        builder,
        first_msg,
        session_id,
        response_text="先给你 unified diff 草案。",
        actual_tier="v4_flash",
        owner_tool_trace=None,
    )

    follow_msg = _msg(text="继续", raw_content="继续")
    plugin._update_owner_private_session_state(
        builder,
        follow_msg,
        session_id,
        response_text="继续往下切。",
        actual_tier="v4_flash",
        owner_tool_trace=None,
    )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.current_task == "先出diff再落"
    assert state.todo_items[0] == "先出diff再落"
    assert any("漂♂总要求：继续" == item for item in state.recent_decisions)
    assert state.last_tool_summary == "direct_reply tier=v4_flash"


def test_update_owner_private_session_state_records_tool_summary(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"
    msg = _msg(text="看看项目目录", raw_content="看看项目目录")
    owner_tool_trace = [
        {"tool_name": "list", "result": {"output": "abs_path=/srv/app\nfile\tREADME.md\t12"}},
        {"tool_name": "read", "result": {"output": "read path=README.md\n1: hello"}},
    ]

    plugin._update_owner_private_session_state(
        builder,
        msg,
        session_id,
        response_text="我看完了。",
        actual_tier="owner_toolbox",
        owner_tool_trace=owner_tool_trace,
    )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.current_task == "看看项目目录"
    assert state.last_tool_summary.startswith("tools=list,read calls=2")
    assert "last=" in state.last_tool_summary


def test_update_owner_private_session_state_ignores_non_owner_private(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = "private:10001"
    msg = _msg(uid="10001", nick="普通用户", is_owner=False, text="继续", raw_content="继续")

    plugin._update_owner_private_session_state(
        builder,
        msg,
        session_id,
        response_text="不会写回",
        actual_tier="v4_flash",
        owner_tool_trace=None,
    )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.current_task == ""
    assert state.todo_items == []
    assert state.recent_decisions == []
    assert state.last_tool_summary == ""



def test_confirmed_facts_session_store_deduplicates_and_trims_values(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    store = builder.session_state_store.__class__()
    session_id = f"private:{OWNER_UID}"
    long_text = "A" * 140

    state = store.update(
        session_id,
        confirmed_facts=["owner_id=335059272", "owner_id=335059272", "", long_text],
    )

    assert state.confirmed_facts[0] == "owner_id=335059272"
    assert len(state.confirmed_facts) == 2
    assert state.confirmed_facts[1].endswith("…")
    assert len(state.confirmed_facts[1]) == 120



def test_confirmed_facts_session_anchor_renders_existing_items_for_owner_private(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    msg = _msg(text="继续干", raw_content="继续干")
    session_id = builder.derive_session_id(msg)
    builder.session_state_store.update(
        session_id,
        current_task="继续 confirmed_facts smoke",
        confirmed_facts=["owner_id=335059272", "project_doc=老年痴呆治疗.md"],
    )

    messages = builder.build_messages(msg, _decision(OWNER_UID), history=[])
    system = _system_from_messages(messages)

    assert "[SessionAnchor]" in system
    assert "confirmed_facts:" in system
    assert "- owner_id=335059272" in system
    assert "- project_doc=老年痴呆治疗.md" in system



def test_confirmed_facts_session_anchor_is_hidden_from_group_even_if_state_exists(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    msg = _msg(channel="group", group_id="137918147", text="继续干", raw_content="继续干")
    session_id = builder.derive_session_id(msg)
    builder.session_state_store.update(
        session_id,
        confirmed_facts=["owner_id=335059272"],
    )

    messages = builder.build_messages(msg, _decision(OWNER_UID), history=[])
    system = _system_from_messages(messages)

    assert "[SessionAnchor]" not in system
    assert "confirmed_facts:" not in system
    assert "owner_id=335059272" not in system



def test_confirmed_facts_session_anchor_is_hidden_from_non_owner_private_even_if_state_exists(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    msg = _msg(uid="10001", nick="普通用户", is_owner=False, text="继续干", raw_content="继续干")
    session_id = builder.derive_session_id(msg)
    builder.session_state_store.update(
        session_id,
        confirmed_facts=["owner_id=335059272"],
    )

    messages = builder.build_messages(msg, _decision("10001"), history=[])
    system = _system_from_messages(messages)

    assert "[SessionAnchor]" not in system
    assert "confirmed_facts:" not in system
    assert "owner_id=335059272" not in system



def test_confirmed_facts_update_owner_private_session_state_preserves_existing_items(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"
    builder.session_state_store.update(
        session_id,
        confirmed_facts=["owner_id=335059272", "project_doc=老年痴呆治疗.md"],
    )
    msg = _msg(text="继续干", raw_content="继续干")

    plugin._update_owner_private_session_state(
        builder,
        msg,
        session_id,
        response_text="继续往下切。",
        actual_tier="v4_flash",
        owner_tool_trace=None,
    )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.confirmed_facts == ["owner_id=335059272", "project_doc=老年痴呆治疗.md"]



def test_confirmed_facts_update_owner_private_session_state_extracts_explicit_owner_id(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"
    msg = _msg(text="我的QQ是335059272，记一下", raw_content="我的QQ是335059272，记一下")

    plugin._update_owner_private_session_state(
        builder,
        msg,
        session_id,
        response_text="收到。",
        actual_tier="v4_flash",
        owner_tool_trace=None,
    )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.confirmed_facts == ["owner_id=335059272"]


def test_confirmed_facts_update_owner_private_session_state_overwrites_owner_id_on_explicit_update(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"
    builder.session_state_store.update(session_id, confirmed_facts=["owner_id=111111"])

    msg = _msg(text="我的QQ是335059272，改成这个", raw_content="我的QQ是335059272，改成这个")
    plugin._update_owner_private_session_state(
        builder,
        msg,
        session_id,
        response_text="收到，按新值走。",
        actual_tier="v4_flash",
        owner_tool_trace=None,
    )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.confirmed_facts == ["owner_id=335059272"]


def test_confirmed_facts_update_owner_private_session_state_skips_emotional_or_context_only_text(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"

    for text_value in ["md", "好", "继续", "这个也记一下", "笑死我了"]:
        msg = _msg(text=text_value, raw_content=text_value)
        plugin._update_owner_private_session_state(
            builder,
            msg,
            session_id,
            response_text="收到。",
            actual_tier="v4_flash",
            owner_tool_trace=None,
        )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.confirmed_facts == []


def test_confirmed_facts_update_owner_private_session_state_extracts_project_doc_from_explicit_statement(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"
    msg = _msg(text="文档是老年痴呆治疗.md，记一下", raw_content="文档是老年痴呆治疗.md，记一下")

    plugin._update_owner_private_session_state(
        builder,
        msg,
        session_id,
        response_text="收到。",
        actual_tier="v4_flash",
        owner_tool_trace=None,
    )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.confirmed_facts == ["project_doc=老年痴呆治疗.md"]


def test_confirmed_facts_update_owner_private_session_state_keeps_single_active_value_after_multiple_updates(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"

    for text_value in ["我的QQ是111111", "我的QQ是222222", "我的QQ是335059272"]:
        msg = _msg(text=text_value, raw_content=text_value)
        plugin._update_owner_private_session_state(
            builder,
            msg,
            session_id,
            response_text="收到。",
            actual_tier="v4_flash",
            owner_tool_trace=None,
        )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.confirmed_facts == ["owner_id=335059272"]



def test_confirmed_facts_update_owner_private_session_state_deprecates_only_owner_id_on_explicit_qq_retire(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"
    builder.session_state_store.update(
        session_id,
        confirmed_facts=["owner_id=335059272", "project_doc=老年痴呆治疗.md"],
    )

    msg = _msg(text="旧QQ不用了", raw_content="旧QQ不用了")
    plugin._update_owner_private_session_state(
        builder,
        msg,
        session_id,
        response_text="收到。",
        actual_tier="v4_flash",
        owner_tool_trace=None,
    )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.confirmed_facts == ["project_doc=老年痴呆治疗.md"]



def test_confirmed_facts_update_owner_private_session_state_deprecates_only_project_doc_on_explicit_doc_retire(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"
    builder.session_state_store.update(
        session_id,
        confirmed_facts=["owner_id=335059272", "project_doc=老年痴呆治疗.md"],
    )

    msg = _msg(text="旧文档废弃了", raw_content="旧文档废弃了")
    plugin._update_owner_private_session_state(
        builder,
        msg,
        session_id,
        response_text="收到。",
        actual_tier="v4_flash",
        owner_tool_trace=None,
    )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.confirmed_facts == ["owner_id=335059272"]



def test_confirmed_facts_update_owner_private_session_state_does_not_deprecate_unrelated_items_on_vague_retire_text(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"
    builder.session_state_store.update(
        session_id,
        confirmed_facts=["owner_id=335059272", "project_doc=老年痴呆治疗.md"],
    )

    msg = _msg(text="旧的不用了", raw_content="旧的不用了")
    plugin._update_owner_private_session_state(
        builder,
        msg,
        session_id,
        response_text="收到。",
        actual_tier="v4_flash",
        owner_tool_trace=None,
    )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.confirmed_facts == ["owner_id=335059272", "project_doc=老年痴呆治疗.md"]



def test_confirmed_facts_update_owner_private_session_state_rejects_weak_source_doc_hint_without_explicit_file_subject(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"
    msg = _msg(text="这个 md 记一下", raw_content="这个 md 记一下")

    plugin._update_owner_private_session_state(
        builder,
        msg,
        session_id,
        response_text="收到。",
        actual_tier="v4_flash",
        owner_tool_trace=None,
    )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.confirmed_facts == []



def test_confirmed_facts_update_owner_private_session_state_rejects_bare_filename_without_doc_subject(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"
    msg = _msg(text="老年痴呆治疗.md，记一下", raw_content="老年痴呆治疗.md，记一下")

    plugin._update_owner_private_session_state(
        builder,
        msg,
        session_id,
        response_text="收到。",
        actual_tier="v4_flash",
        owner_tool_trace=None,
    )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.confirmed_facts == []



def test_confirmed_facts_update_owner_private_session_state_accepts_explicit_file_subject_variants(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"

    for text_value in ["文件叫老年痴呆治疗.md", "文档名为老年痴呆治疗.txt", "文件是notes.cmm"]:
        msg = _msg(text=text_value, raw_content=text_value)
        plugin._update_owner_private_session_state(
            builder,
            msg,
            session_id,
            response_text="收到。",
            actual_tier="v4_flash",
            owner_tool_trace=None,
        )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.confirmed_facts == ["project_doc=notes.cmm"]



def test_confirmed_facts_update_owner_private_session_state_extracts_group_id_from_explicit_statement(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"
    msg = _msg(text="群号是137918147，记一下", raw_content="群号是137918147，记一下")

    plugin._update_owner_private_session_state(
        builder,
        msg,
        session_id,
        response_text="收到。",
        actual_tier="v4_flash",
        owner_tool_trace=None,
    )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.confirmed_facts == ["group_id=137918147"]



def test_confirmed_facts_update_owner_private_session_state_extracts_alias_from_explicit_statement(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"
    msg = _msg(text="你可以叫我漂♂总", raw_content="你可以叫我漂♂总")

    plugin._update_owner_private_session_state(
        builder,
        msg,
        session_id,
        response_text="收到。",
        actual_tier="v4_flash",
        owner_tool_trace=None,
    )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.confirmed_facts == ["alias=漂♂总"]



def test_confirmed_facts_update_owner_private_session_state_deprecates_only_group_id_on_explicit_group_retire(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"
    builder.session_state_store.update(
        session_id,
        confirmed_facts=["group_id=137918147", "project_doc=老年痴呆治疗.md"],
    )

    msg = _msg(text="旧群号不用了", raw_content="旧群号不用了")
    plugin._update_owner_private_session_state(
        builder,
        msg,
        session_id,
        response_text="收到。",
        actual_tier="v4_flash",
        owner_tool_trace=None,
    )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.confirmed_facts == ["project_doc=老年痴呆治疗.md"]



def test_confirmed_facts_update_owner_private_session_state_deprecates_only_alias_on_explicit_alias_retire(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"
    builder.session_state_store.update(
        session_id,
        confirmed_facts=["alias=漂♂总", "project_doc=老年痴呆治疗.md"],
    )

    msg = _msg(text="这个称呼不用了", raw_content="这个称呼不用了")
    plugin._update_owner_private_session_state(
        builder,
        msg,
        session_id,
        response_text="收到。",
        actual_tier="v4_flash",
        owner_tool_trace=None,
    )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.confirmed_facts == ["project_doc=老年痴呆治疗.md"]



def test_confirmed_facts_update_owner_private_session_state_rejects_vague_name_without_explicit_alias_prefix(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    session_id = f"private:{OWNER_UID}"
    msg = _msg(text="漂♂总，记一下", raw_content="漂♂总，记一下")

    plugin._update_owner_private_session_state(
        builder,
        msg,
        session_id,
        response_text="收到。",
        actual_tier="v4_flash",
        owner_tool_trace=None,
    )

    state = builder.session_state_store.get_or_create(session_id)
    assert state.confirmed_facts == []



def test_owner_private_rolling_summary_injected_when_enabled(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    builder.runtime_config = SimpleNamespace(
        get=lambda key, default=None: {
            "private_context_rolling_summary_enabled": True,
            "private_context_rolling_summary_char_budget": 500,
        }.get(key, default),
        get_bool=lambda key, default=False, env_key=None: {
            "private_context_rolling_summary_enabled": True,
        }.get(key, default),
    )
    state = builder.session_state_store.get_or_create(f"private:{OWNER_UID}")
    state.current_task = "继续 rolling summary 落地"
    state.rolling_summary = "当前任务=继续 rolling summary 落地；最近指令=继续；最近回复=已完成 fallback 验尸并转入 summary 主线"

    messages = builder.build_messages(_msg(text="继续", raw_content="继续"), _decision(OWNER_UID), history=[])
    system = _system_from_messages(messages)

    assert "[RollingSummary]" in system
    assert "当前任务=继续 rolling summary 落地" in system
    assert "rolling_summary_hint:" in system


def test_private_context_session_state_store_persists_to_runtime_configured_path(tmp_path) -> None:
    class FakeCfg:
        def get(self, key, default=None):
            data = {
                "private_context_rolling_summary_state_path": str(tmp_path / "private_context_session_state.json"),
            }
            return data.get(key, default)

        def get_bool(self, key, default=False, env_key=None):
            data = {
                "private_context_rolling_summary_persist_enabled": True,
            }
            return data.get(key, default)

    session_store = plugin.PrivateContextSessionStateStore(
        persist_enabled=FakeCfg().get_bool("private_context_rolling_summary_persist_enabled", False),
        state_path=FakeCfg().get("private_context_rolling_summary_state_path"),
    )
    builder = PromptBuilder(store=None, skill_loader=None, runtime_config=FakeCfg(), session_state_store=session_store)

    plugin._update_owner_private_session_state(
        builder,
        _msg(text="继续搞 rolling summary", raw_content="继续搞 rolling summary"),
        f"private:{OWNER_UID}",
        response_text="已写入落盘状态。",
        actual_tier="gpt_5_4",
        owner_tool_trace=[{"tool_name": "read", "result": {"content": "read ok"}}],
    )

    persisted_path = tmp_path / "private_context_session_state.json"
    assert persisted_path.exists()
    raw = persisted_path.read_text(encoding="utf-8")
    assert f'"private:{OWNER_UID}"' in raw
    assert '"current_task": "继续搞 rolling summary"' in raw
    assert '"last_tool_summary": "tools=read calls=1' in raw


def test_private_context_session_state_store_load_restores_persisted_state(tmp_path) -> None:
    state_path = tmp_path / "private_context_session_state.json"
    state_path.write_text(
        """{
  "private:335059272": {
    "session_id": "private:335059272",
    "current_task": "继续 rolling summary 落地",
    "rolling_summary": "当前任务=继续 rolling summary 落地；最近指令=继续",
    "confirmed_facts": ["owner_id=335059272"],
    "todo_items": ["继续 rolling summary 落地"],
    "recent_decisions": ["漂♂总要求：继续"],
    "last_tool_summary": "tools=read calls=1",
    "turn_count": 3,
    "updated_at": "2026-06-18T22:29:18+08:00"
  }
}
""",
        encoding="utf-8",
    )

    store = plugin.PrivateContextSessionStateStore(persist_enabled=True, state_path=state_path)
    state = store.get_or_create(f"private:{OWNER_UID}")

    assert state.current_task == "继续 rolling summary 落地"
    assert state.rolling_summary.startswith("当前任务=继续 rolling summary 落地")
    assert state.confirmed_facts == ["owner_id=335059272"]
    assert state.turn_count == 3


def test_update_owner_private_session_state_builds_rolling_summary_when_enabled() -> None:
    class FakeCfg:
        def get(self, key, default=None):
            data = {
                "private_context_rolling_summary_char_budget": 500,
                "private_context_rolling_summary_update_min_turns": 1,
            }
            return data.get(key, default)
        def get_bool(self, key, default=False, env_key=None):
            data = {
                "private_context_rolling_summary_enabled": True,
            }
            return data.get(key, default)

    builder = PromptBuilder(store=None, skill_loader=None, runtime_config=FakeCfg())
    msg = _msg(text="继续搞 rolling summary", raw_content="继续搞 rolling summary")

    plugin._update_owner_private_session_state(
        builder,
        msg,
        f"private:{OWNER_UID}",
        response_text="已补第一版 summary 注入和状态更新。",
        actual_tier="gpt_5_4",
        owner_tool_trace=[{"tool_name": "read", "result": {"content": "read ok"}}],
    )

    state = builder.session_state_store.get_or_create(f"private:{OWNER_UID}")
    assert state.turn_count == 1
    assert "最近指令=继续搞 rolling summary" in state.rolling_summary
    assert "最近回复=已补第一版 summary 注入和状态更新。" in state.rolling_summary
    assert "工具结论=" in state.rolling_summary


def test_owner_private_summary_reduces_recent_history_when_enabled(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    builder.runtime_config = SimpleNamespace(
        get=lambda key, default=None: {
            "private_context_rolling_summary_enabled": True,
            "private_context_rolling_summary_char_budget": 500,
            "private_context_summary_history_reduction_trigger": 8,
            "private_context_recent_history_limit": 12,
            "private_context_recent_history_limit_when_summary_present": 4,
        }.get(key, default),
        get_bool=lambda key, default=False, env_key=None: {
            "private_context_rolling_summary_enabled": True,
            "private_context_summary_history_reduction_enabled": True,
        }.get(key, default),
    )
    state = builder.session_state_store.get_or_create(f"private:{OWNER_UID}")
    state.current_task = "继续压缩接管截断"
    state.rolling_summary = "当前任务=继续压缩接管截断；最近指令=继续；最近回复=已切到 summary 优先"
    history = [
        {"nick": f"用户{i}", "uid": str(i), "text": f"历史{i}", "is_bot": False}
        for i in range(10)
    ]

    messages = builder.build_messages(_msg(text="继续", raw_content="继续"), _decision(OWNER_UID), history=history)
    contents = [item["content"] for item in messages]

    assert any(item.startswith("[RollingSummary]") for item in contents)
    assert any("历史9" in item for item in contents)
    assert any("历史6" in item for item in contents)
    assert not any("历史5" in item for item in contents)
    assert not any("历史0" in item for item in contents)


def test_owner_private_long_history_backfills_summary_and_then_reduces_window(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    builder.runtime_config = SimpleNamespace(
        get=lambda key, default=None: {
            "private_context_rolling_summary_enabled": True,
            "private_context_rolling_summary_char_budget": 500,
            "private_context_summary_history_reduction_trigger": 8,
            "private_context_recent_history_limit": 12,
            "private_context_recent_history_limit_when_summary_present": 4,
        }.get(key, default),
        get_bool=lambda key, default=False, env_key=None: {
            "private_context_rolling_summary_enabled": True,
            "private_context_summary_history_reduction_enabled": True,
        }.get(key, default),
    )
    session_id = f"private:{OWNER_UID}"
    state = builder.session_state_store.get_or_create(session_id)
    state.current_task = "继续压缩接管截断"
    state.recent_decisions = ["漂♂总要求：继续搞上下文压缩 V1"]
    history = [
        {"nick": f"用户{i}", "uid": str(i), "text": f"历史{i}", "is_bot": False}
        for i in range(10)
    ]

    messages = builder.build_messages(_msg(text="继续", raw_content="继续"), _decision(OWNER_UID), history=history)
    contents = [item["content"] for item in messages]
    state = builder.session_state_store.get_or_create(session_id)

    assert state.rolling_summary
    assert "当前任务=继续压缩接管截断" in state.rolling_summary
    assert "近期对话=" in state.rolling_summary
    assert any(item.startswith("[RollingSummary]") for item in contents)
    assert any("历史9" in item for item in contents)
    assert any("历史6" in item for item in contents)
    assert not any("历史5" in item for item in contents)


def test_owner_private_without_summary_keeps_default_recent_history_window(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    builder.runtime_config = SimpleNamespace(
        get=lambda key, default=None: {
            "private_context_rolling_summary_enabled": True,
            "private_context_rolling_summary_char_budget": 500,
            "private_context_summary_history_reduction_trigger": 8,
            "private_context_recent_history_limit": 12,
            "private_context_recent_history_limit_when_summary_present": 4,
        }.get(key, default),
        get_bool=lambda key, default=False, env_key=None: {
            "private_context_rolling_summary_enabled": True,
            "private_context_summary_history_reduction_enabled": True,
        }.get(key, default),
    )
    history = [
        {"nick": f"用户{i}", "uid": str(i), "text": f"历史{i}", "is_bot": False}
        for i in range(6)
    ]

    messages = builder.build_messages(_msg(text="继续", raw_content="继续"), _decision(OWNER_UID), history=history)
    contents = [item["content"] for item in messages]

    assert any("历史0" in item for item in contents)
    assert any("历史5" in item for item in contents)
    assert not any(item.startswith("[RollingSummary]") for item in contents)
