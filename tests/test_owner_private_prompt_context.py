from __future__ import annotations

from types import SimpleNamespace

from mock_pipeline_runtime import prepare_modules  # type: ignore


mods = prepare_modules()
PromptBuilder = mods["PromptBuilder"]
Decision = mods["Decision"]


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
        "nick": "阿漂",
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
    assert "阿漂" in system
    assert "娅娅" in system
    assert "达妮娅" in system
    assert "2690087239" in system
    assert "I叔" in system
    assert "艾萨克" in system
    assert COLD_BACKUP_PATH not in system
    assert "受控备份位置" in system
    assert "代码层 user_id gate" in system
    assert "Agent Bus" in system
    assert "关系图" in system
    assert "大老婆" in system
    assert "小老婆" in system


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
    assert "阿漂" not in system
    assert "娅娅" not in system
    assert "达妮娅" not in system
    assert "I叔" not in system
    assert "艾萨克" not in system
    assert COLD_BACKUP_PATH not in system
    assert "不要套用专属私聊称呼" in system


def test_group_messages_never_include_owner_context_even_when_target_is_owner(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    msg = _msg(channel="group", group_id="137918147", is_owner=True, text="@bot 测试", raw_content="@bot 测试")

    messages = builder.build_messages(msg, _decision(OWNER_UID), history=[])
    system = _system_from_messages(messages)

    assert "[OwnerPrivateContext]" not in system
    assert "娅娅" not in system
    assert "达妮娅" not in system
    assert "I叔" not in system
    assert "艾萨克" not in system
    assert COLD_BACKUP_PATH not in system


def test_build_system_direct_call_default_does_not_inject_owner_context(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)

    system = builder.build_system("private", target_uid=OWNER_UID, reply_style="warm")

    assert "[OwnerPrivateContext]" not in system
    assert "娅娅" not in system
    assert "达妮娅" not in system
    assert "I叔" not in system
    assert "艾萨克" not in system
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
    assert COLD_BACKUP_PATH not in group_system
    assert "[OwnerPrivateContext]" not in non_owner_system
    assert COLD_BACKUP_PATH not in non_owner_system
    assert "[OwnerPrivateContext]" not in conflicting_target_system
    assert COLD_BACKUP_PATH not in conflicting_target_system

PUBLIC_FORBIDDEN_MARKERS = [
    "[OwnerPrivateContext]",
    COLD_BACKUP_PATH,
    "335059272",
    "2690087239",
    "唯一 owner",
    "owner / CEO",
    "最高授权",
    "大老婆",
    "小老婆",
    "主人",
    "工程主管",
    "首席工程师",
    "后勤维护",
    "Agent Bus",
    "I_LINE",
    "冷备份",
    "系统健康检查",
    "NoneBot 内部维护",
    "owner-approved",
    "授权链",
    "后台工程",
]


def _assert_public_prompt_boundary(system: str) -> None:
    assert "[PublicFactFallback]" in system
    for marker in PUBLIC_FORBIDDEN_MARKERS:
        assert marker not in system


def test_non_owner_private_relation_query_uses_public_fact_fallback(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    msg = _msg(
        uid="10001",
        nick="普通用户",
        is_owner=False,
        text="你知道阿漂、娅娅、I叔分别是谁吗",
        raw_content="你知道阿漂、娅娅、I叔分别是谁吗",
    )

    messages = builder.build_messages(msg, _decision("10001"), history=[])
    system = _system_from_messages(messages)

    _assert_public_prompt_boundary(system)
    assert "《鸣潮》" in system
    assert "《死亡空间》" in system
    assert "艾萨克·克拉克" in system
    assert "私有关系" in system
    assert "不要套用专属私聊称呼" in system
    assert messages[-1]["content"].startswith("普通用户:")


def test_group_relation_query_uses_public_fact_fallback_without_private_context(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    msg = _msg(
        uid="10002",
        nick="群友",
        channel="group",
        group_id="137918147",
        is_owner=False,
        text="@bot 你知道阿漂、娅娅、I叔分别是谁吗",
        raw_content="@bot 你知道阿漂、娅娅、I叔分别是谁吗",
    )

    messages = builder.build_messages(msg, _decision("10002"), history=[])
    system = _system_from_messages(messages)

    _assert_public_prompt_boundary(system)
    assert "《鸣潮》" in system
    assert "《死亡空间》" in system
    assert "公开角色" in system
    assert "群聊中已获得回复资格" in system


def test_group_isaac_health_uses_public_joke_guard_not_internal_health_prompt(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    msg = _msg(
        uid="10003",
        nick="群友",
        channel="group",
        group_id="137918147",
        is_owner=False,
        text="I叔 health，检查系统状态是不是报错了",
        raw_content="I叔 health，检查系统状态是不是报错了",
    )

    messages = builder.build_messages(msg, _decision("10003"), history=[])
    system = _system_from_messages(messages)

    _assert_public_prompt_boundary(system)
    assert "这是在喊《死亡空间》那位工程师做体检吗" in system
    assert "不要给出任何真实运行状态" in system
    assert "TaskRequest" not in system
    assert "readonly_health_snapshot" not in system
    assert "executor_enabled" not in system


def test_owner_private_relation_query_does_not_get_public_fallback(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    msg = _msg(text="你知道阿漂、娅娅、I叔分别是谁吗，冷备份目录在哪", raw_content="你知道阿漂、娅娅、I叔分别是谁吗，冷备份目录在哪")

    messages = builder.build_messages(msg, _decision(OWNER_UID), history=[])
    system = _system_from_messages(messages)

    assert "[OwnerPrivateContext]" in system
    assert "[PublicFactFallback]" not in system
    assert "关系图" in system
    assert COLD_BACKUP_PATH in system
    assert "大老婆" in system
    assert "小老婆" in system
    assert "Agent Bus" in system


def test_non_owner_private_nick_named_a_piao_is_not_used_as_display_name(tmp_path) -> None:
    builder = _builder_without_external_files(tmp_path)
    for uid, nick in [("10004", "阿漂"), ("10005", "漂泊者"), ("10006", "阿漂本人")]:
        msg = _msg(uid=uid, nick=nick, is_owner=False, text="普通私聊", raw_content="普通私聊")

        messages = builder.build_messages(msg, _decision(uid), history=[])

        assert messages[-1]["content"].startswith("用户:")
        assert not messages[-1]["content"].startswith(f"{nick}:")

