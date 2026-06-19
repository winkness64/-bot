from __future__ import annotations

import json
import tempfile
from pathlib import Path
from types import SimpleNamespace

from mock_pipeline_runtime import prepare_modules  # type: ignore


mods = prepare_modules()
MemoryStore = mods["MemoryStore"]
PromptBuilder = mods["PromptBuilder"]
RuntimeConfig = mods["RuntimeConfig"]
DEFAULTS = mods["DEFAULTS"]
plugin = mods["plugin"]
Decision = mods["Decision"]


def _build_store(tmpdir: str):
    return MemoryStore(str(Path(tmpdir) / "chat.db"), str(Path(tmpdir) / "cache"))


def _build_msg(**overrides):
    base = {
        "msg_id": "m1",
        "uid": "335059272",
        "nick": "漂♂总",
        "group_id": "",
        "channel": "private",
        "text": "测试消息",
        "raw_content": "测试消息",
        "is_at_bot": False,
        "is_at_owner": False,
        "is_quote_bot": False,
        "quote_target_msg_id": None,
        "at_user_ids": [],
        "bot_self_id": "90001",
        "reply_to_message_id": None,
        "reply_to_user_id": None,
        "is_reply_to_bot": False,
        "is_owner": True,
        "owner_command": False,
        "explicit_command": False,
        "images": [],
        "timestamp": 1710000000.0,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_memory_observation_detects_c4_long_term_fact_section() -> None:
    msg = _build_msg()
    decision = SimpleNamespace(should_reply=True)
    messages = [
        {
            "role": "system",
            "content": "[来自长期记忆的事实]\n- 当前用户/对话对象喜欢低延迟观测。",
        },
        {"role": "user", "content": "漂♂总: 测试"},
    ]

    observation = plugin._collect_memory_observation(
        msg,
        decision,
        captured=False,
        session_id="private:335059272",
        messages=messages,
    )

    assert observation["prompt_injected"] is True
    assert observation["memory_prompt_chars"] > 0
    assert observation["memory_items_used"] == 1


def test_memory_paths_initialized_and_seed_files_created() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        mem = store.memory_system

        assert mem.base_dir.exists()
        assert mem.short_term_dir.exists()
        assert mem.daily_dir.exists()
        assert mem.long_term_dir.exists()
        assert mem.backups_dir.exists()
        assert mem.impressions_path.exists()
        assert mem.relations_path.exists()
        assert json.loads(mem.impressions_path.read_text(encoding="utf-8")) == {}
        assert json.loads(mem.relations_path.read_text(encoding="utf-8")) == {}


def test_short_term_cache_truncates_to_capacity() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        mem = store.memory_system
        mem.short_term_limit = 3

        for index in range(5):
            store.add_to_short_term(
                "session-a",
                {"uid": "u1", "nick": "漂泊者", "text": f"msg-{index}", "timestamp": index},
            )

        context = store.get_short_term_context("session-a", limit=10)
        assert [item["text"] for item in context] == ["msg-2", "msg-3", "msg-4"]


def test_user_profile_read_write_roundtrip_and_backup_created() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        profile = {
            "nickname": "漂♂总",
            "traits": ["喜欢活人感", "讨厌模板化"],
            "relationship": "伴侣",
        }

        saved = store.save_user_profile("335059272", profile)
        loaded = store.get_user_profile("335059272")

        assert saved["user_id"] == "335059272"
        assert loaded is not None
        assert loaded["nickname"] == "漂♂总"
        assert loaded["traits"] == ["喜欢活人感", "讨厌模板化"]
        assert "last_updated" in loaded

        backups = list(store.memory_system.backups_dir.glob("*profile_335059272.json"))
        assert backups, "expected profile backup files"


def test_impression_update_persists_and_creates_backup() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)

        updated = store.update_impression("335059272", "bond_level", "极高")
        assert updated["bond_level"] == "极高"
        assert "last_updated" in updated

        persisted = store.memory_system.get_impressions("335059272")
        assert persisted["bond_level"] == "极高"

        backups = list(store.memory_system.backups_dir.glob("*impressions.json"))
        assert backups, "expected impressions backup files"


def test_memory_prompt_building_contains_short_term_profile_and_impression() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        store.add_to_short_term("session-b", {"uid": "335059272", "nick": "漂♂总", "text": "今天做记忆系统"})
        store.save_user_profile(
            "335059272",
            {"nickname": "漂♂总", "preferences": ["低成本方案", "搞事情"], "relationship": "伴侣"},
        )
        store.update_impression("335059272", "mood", "productive")
        store.memory_system.update_relation("335059272", "2690087239", "信任队友")

        prompt = store.build_memory_prompt("335059272", "session-b")

        assert "[短期上下文记忆]" in prompt
        assert "今天做记忆系统" in prompt
        assert "[长期用户画像]" in prompt
        assert "低成本方案" in prompt
        assert "[用户印象]" in prompt
        assert "productive" in prompt
        assert "[关系图谱]" in prompt
        assert "2690087239" in prompt


def test_prompt_builder_memory_prompt_is_optional_and_not_enabled_by_default() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        store.save_user_profile("335059272", {"nickname": "漂♂总", "traits": ["喜欢活人感"]})
        store.update_impression("335059272", "style", "真实聊天")
        store.add_to_short_term("335059272", {"uid": "335059272", "nick": "漂♂总", "text": "测试可选记忆"})

        default_builder = PromptBuilder(store=store, skill_loader=None)
        enabled_builder = PromptBuilder(store=store, skill_loader=None, memory_enabled=True)

        default_system = default_builder.build_system("private", target_uid="335059272", reply_style="warm")
        enabled_system = enabled_builder.build_system("private", target_uid="335059272", reply_style="warm")

        assert "[长期用户画像]" not in default_system
        assert "[用户印象]" not in default_system
        assert "[长期用户画像]" in enabled_system
        assert "真实聊天" in enabled_system
        assert "测试可选记忆" in enabled_system


def test_runtime_config_memory_defaults_off() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cfg = RuntimeConfig(DEFAULTS, path=Path(tmpdir) / "runtime_config.json")
        assert cfg.get_bool("memory_short_term_capture_enabled", True) is False
        assert cfg.get_bool("memory_prompt_injection_enabled", True) is False
        assert cfg.get_bool("memory_prompt_injection_private_enabled", False) is True
        assert cfg.get_bool("memory_prompt_injection_group_mention_enabled", False) is True
        assert cfg.get_bool("memory_prompt_injection_group_silent_enabled", True) is False
        assert cfg.get_bool("memory_capture_audit_enabled", False) is True
        assert int(cfg.get("memory_short_term_limit", 0) or 0) == 100


def test_capture_short_term_memory_when_enabled() -> None:
    original_cfg = plugin.cfg
    original_store = plugin.store
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = RuntimeConfig(DEFAULTS, path=Path(tmpdir) / "runtime_config.json")
            cfg.set("memory_short_term_capture_enabled", True)
            cfg.set("memory_capture_audit_enabled", True)
            cfg.set("memory_capture_audit_path", str(Path(tmpdir) / "memory_audit.jsonl"))
            store = _build_store(tmpdir)
            plugin.cfg = cfg
            plugin.store = store

            msg = _build_msg(
                uid="3916107556",
                nick="小维",
                text="群里潜水中",
                raw_content="群里潜水中",
                channel="group",
                group_id="137918147",
            )
            captured = plugin._capture_short_term_memory(msg)

            session_id = plugin._get_session_id(msg)
            context = store.get_short_term_context(session_id, limit=5)
            assert captured is True
            assert len(context) == 1
            assert context[0]["uid"] == "3916107556"
            assert context[0]["user_id"] == "3916107556"
            assert context[0]["text"] == "群里潜水中"
            assert context[0]["raw_content"] == "群里潜水中"
            assert context[0]["channel"] == "group"
            assert context[0]["session_id"] == "group:137918147"

            audit_path = Path(tmpdir) / "memory_audit.jsonl"
            rows = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines() if line.strip()]
            assert len(rows) == 1
            assert rows[0]["session_id"] == "group:137918147"
            assert rows[0]["user_id"] == "3916107556"
            assert rows[0]["channel"] == "group"
    finally:
        plugin.cfg = original_cfg
        plugin.store = original_store


def test_capture_short_term_memory_when_disabled_does_nothing() -> None:
    original_cfg = plugin.cfg
    original_store = plugin.store
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = RuntimeConfig(DEFAULTS, path=Path(tmpdir) / "runtime_config.json")
            cfg.set("memory_short_term_capture_enabled", False)
            cfg.set("memory_capture_audit_enabled", True)
            cfg.set("memory_capture_audit_path", str(Path(tmpdir) / "memory_audit.jsonl"))
            store = _build_store(tmpdir)
            plugin.cfg = cfg
            plugin.store = store

            msg = _build_msg(uid="3916107556", nick="小维", channel="group", group_id="137918147", text="静默路过")
            captured = plugin._capture_short_term_memory(msg)

            assert captured is False
            assert store.get_short_term_context("group:137918147", limit=5) == []
            assert not (Path(tmpdir) / "memory_audit.jsonl").exists()
    finally:
        plugin.cfg = original_cfg
        plugin.store = original_store


def test_prompt_injection_uses_real_session_id_only_when_enabled() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        store.add_to_short_term("group:real", {"uid": "3916107556", "nick": "小维", "text": "真实群记忆"})
        store.add_to_short_term("3916107556", {"uid": "3916107556", "nick": "小维", "text": "错误会话记忆"})

        msg = _build_msg(uid="3916107556", nick="小维", channel="group", group_id="real", text="你还记得吗")
        decision = Decision(True, "warm", "v4_flash", 2, target_uid="3916107556", reason="at_bot", is_forced=True)

        disabled_builder = PromptBuilder(store=store, skill_loader=None, memory_enabled=False)
        disabled_messages = disabled_builder.build_messages(msg, decision, history=[], session_id="group:real")
        assert "真实群记忆" not in disabled_messages[0]["content"]

        enabled_builder = PromptBuilder(store=store, skill_loader=None, memory_enabled=True)
        enabled_messages = enabled_builder.build_messages(msg, decision, history=[], session_id="group:real")
        assert "真实群记忆" in enabled_messages[0]["content"]
        assert "错误会话记忆" not in enabled_messages[0]["content"]


def test_non_at_group_message_capture_only_does_not_force_reply() -> None:
    original_cfg = plugin.cfg
    original_store = plugin.store
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = RuntimeConfig(DEFAULTS, path=Path(tmpdir) / "runtime_config.json")
            cfg.set("memory_short_term_capture_enabled", True)
            cfg.set("memory_capture_audit_enabled", False)
            store = _build_store(tmpdir)
            plugin.cfg = cfg
            plugin.store = store

            msg = _build_msg(
                uid="3916107556",
                nick="小维",
                channel="group",
                group_id="137918147",
                text="没@也记一下",
                raw_content="没@也记一下",
                is_at_bot=False,
                at_user_ids=[],
            )
            decision = SimpleNamespace(should_reply=False)
            captured = plugin._capture_short_term_memory(msg)
            observation = plugin._collect_memory_observation(msg, decision, captured=captured)

            context = store.get_short_term_context("group:137918147", limit=5)
            assert len(context) == 1
            assert context[0]["text"] == "没@也记一下"
            assert observation["captured"] is True
            assert observation["will_reply"] is False
            assert observation["prompt_injected"] is False
    finally:
        plugin.cfg = original_cfg
        plugin.store = original_store


runtime_compat = mods["runtime_compat"]


def test_escape_log_preview_converts_real_newlines_to_literal_sequences() -> None:
    value = runtime_compat.escape_log_preview("a\nb\rc")
    assert value == "a\\nb\\rc"


def test_resolve_plugin_init_config_priority_explicit_over_context() -> None:
    class Ctx:
        def get_config(self):
            return {"memory_root": "ctx-memory", "memory_prompt_injection_enabled": False}

    merged = runtime_compat.resolve_plugin_init_config(
        context=Ctx(),
        config={"memory_root": "explicit-memory", "memory_short_term_limit": 55},
        plugin_config={"memory_prompt_injection_enabled": True},
    )
    assert merged["memory_root"] == "explicit-memory"
    assert merged["memory_prompt_injection_enabled"] is True
    assert merged["memory_short_term_limit"] == 55


def test_memory_root_env_override_beats_plugin_config() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        resolved = runtime_compat.resolve_memory_root(
            plugin_config={"memory_root": "plugin-memory"},
            data_dir=Path(tmpdir) / "data",
            project_root=Path(tmpdir),
            cwd=Path(tmpdir),
            env={"YANGYANG_MEMORY_ROOT": str(Path(tmpdir) / "env-memory")},
        )
        assert resolved == (Path(tmpdir) / "env-memory").resolve()


def test_memory_root_relative_path_resolves_from_data_dir() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        resolved = runtime_compat.resolve_memory_root(
            plugin_config={"memory_root": "relative/memory"},
            data_dir=Path(tmpdir) / "plugin_data",
            project_root=Path(tmpdir) / "project",
            cwd=Path(tmpdir) / "cwd",
            env={},
        )
        assert resolved == (Path(tmpdir) / "plugin_data" / "relative/memory").resolve()


def test_initialize_plugin_applies_explicit_memory_root_and_prompt_default_off() -> None:
    original_cfg = plugin.cfg
    original_store = plugin.store
    original_builder = plugin.builder
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            runtime_path = plugin.DATA_DIR / "runtime_config.json"
            original_text = runtime_path.read_text(encoding="utf-8") if runtime_path.exists() else None
            runtime_path.parent.mkdir(parents=True, exist_ok=True)
            runtime_path.write_text(json.dumps({"memory_prompt_injection_enabled": True, "memory_root": "disk-old"}), encoding="utf-8")
            settings = plugin.initialize_plugin(plugin_config={"memory_root": "mem-root", "memory_prompt_injection_enabled": False})
            assert settings["memory_root"] == "mem-root"
            assert plugin.cfg.get_bool("memory_prompt_injection_enabled", True) is False
            assert plugin.builder.memory_enabled is False
            assert plugin.store.memory_root == (plugin.DATA_DIR / "mem-root").resolve()
            assert str(plugin.cfg.get("resolved_memory_root", "")).endswith("mem-root")
            persisted = json.loads(runtime_path.read_text(encoding="utf-8"))
            assert persisted["memory_root"] == "mem-root"
            assert persisted["memory_prompt_injection_enabled"] is False
    finally:
        if 'runtime_path' in locals():
            if original_text is None:
                try:
                    runtime_path.unlink()
                except FileNotFoundError:
                    pass
            else:
                runtime_path.write_text(original_text, encoding="utf-8")
        plugin.cfg = original_cfg
        plugin.store = original_store
        plugin.builder = original_builder



def test_sync_runtime_components_passes_grounding_gate_to_store() -> None:
    original_cfg = plugin.cfg
    original_store = plugin.store
    original_builder = plugin.builder
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = RuntimeConfig(DEFAULTS, path=Path(tmpdir) / "runtime_config.json")
            cfg.set("memory_prompt_injection_enabled", True)
            cfg.set("memory_long_term_retrieval_grounding_enabled", True)
            cfg.set("memory_long_term_retrieval_top_k", 2)
            cfg.set("memory_long_term_retrieval_char_budget", 333)
            store = _build_store(tmpdir)
            plugin.cfg = cfg
            plugin.store = store
            plugin.builder = PromptBuilder(store=store, skill_loader=None)

            plugin._sync_runtime_components()

            assert plugin.builder.memory_enabled is True
            assert plugin.store.retrieval_enabled is True
            assert plugin.store.retrieval_grounding_enabled is True
            assert plugin.store.retrieval_top_k == 2
            assert plugin.store.retrieval_char_budget == 333
    finally:
        plugin.cfg = original_cfg
        plugin.store = original_store
        plugin.builder = original_builder


def test_sync_runtime_components_grounding_gate_defaults_false() -> None:
    original_cfg = plugin.cfg
    original_store = plugin.store
    original_builder = plugin.builder
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = RuntimeConfig(DEFAULTS, path=Path(tmpdir) / "runtime_config.json")
            cfg.set("memory_prompt_injection_enabled", True)
            store = _build_store(tmpdir)
            plugin.cfg = cfg
            plugin.store = store
            plugin.builder = PromptBuilder(store=store, skill_loader=None)

            plugin._sync_runtime_components()

            assert plugin.store.retrieval_enabled is True
            assert plugin.store.retrieval_grounding_enabled is False
    finally:
        plugin.cfg = original_cfg
        plugin.store = original_store
        plugin.builder = original_builder

def test_build_memory_prompt_budget_controls_for_many_items() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        for index in range(1000):
            store.add_to_short_term("session-budget", {"uid": "u1", "nick": "漂♂总", "text": f"msg-{index}-" + ("x" * 40), "timestamp": index})
        prompt = store.build_memory_prompt("u1", "session-budget", short_term_limit=1000, char_budget=600)
        assert len(prompt) <= 600
        assert "msg-999" in prompt
        assert "msg-0" not in prompt
        assert "[记忆裁剪提示]" in prompt


def test_build_memory_prompt_budget_controls_for_hundred_items() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        for index in range(100):
            store.add_to_short_term("session-100", {"uid": "u1", "nick": "漂♂总", "text": f"line-{index}", "timestamp": index})
        prompt = store.build_memory_prompt("u1", "session-100", short_term_limit=100, char_budget=500)
        assert len(prompt) <= 500
        assert "line-99" in prompt
        assert "line-0" not in prompt


def test_prompt_injection_default_remains_disabled_after_initialize() -> None:
    original_builder = plugin.builder
    original_cfg = plugin.cfg
    original_store = plugin.store
    try:
        plugin.initialize_plugin(plugin_config={})
        assert plugin.cfg.get_bool("memory_prompt_injection_enabled", True) is False
        assert plugin.builder.memory_enabled is False
    finally:
        plugin.builder = original_builder
        plugin.cfg = original_cfg
        plugin.store = original_store


def test_stability_multi_session_isolation_and_limit_eviction() -> None:
    original_cfg = plugin.cfg
    original_store = plugin.store
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = RuntimeConfig(DEFAULTS, path=Path(tmpdir) / "runtime_config.json")
            cfg.set("memory_short_term_capture_enabled", True)
            cfg.set("memory_short_term_limit", 100)
            store = _build_store(tmpdir)
            plugin.cfg = cfg
            plugin.store = store

            for index in range(105):
                plugin._capture_short_term_memory(
                    _build_msg(uid="335059272", channel="private", text=f"private-{index}", raw_content=f"private-{index}")
                )
            plugin._capture_short_term_memory(
                _build_msg(uid="3916107556", nick="小维", channel="group", group_id="137918147", text="group-only", raw_content="group-only")
            )

            private_context = store.get_short_term_context("private:335059272", limit=200)
            group_context = store.get_short_term_context("group:137918147", limit=20)
            assert len(private_context) == 100
            assert private_context[0]["text"] == "private-5"
            assert private_context[-1]["text"] == "private-104"
            assert [item["text"] for item in group_context] == ["group-only"]
            prompt = store.build_memory_prompt("335059272", "private:335059272", short_term_limit=100, char_budget=1200)
            assert "private-104" in prompt
            assert "group-only" not in prompt
    finally:
        plugin.cfg = original_cfg
        plugin.store = original_store


def test_stability_injection_split_switches_and_kill_switch() -> None:
    original_cfg = plugin.cfg
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = RuntimeConfig(DEFAULTS, path=Path(tmpdir) / "runtime_config.json")
            cfg.set("memory_prompt_injection_enabled", True)
            cfg.set("memory_prompt_injection_private_enabled", True)
            cfg.set("memory_prompt_injection_group_mention_enabled", False)
            cfg.set("memory_prompt_injection_group_silent_enabled", True)
            plugin.cfg = cfg

            private_msg = _build_msg(channel="private", uid="335059272")
            group_at_msg = _build_msg(channel="group", group_id="137918147", is_at_bot=True, at_user_ids=["90001"])
            group_silent_msg = _build_msg(channel="group", group_id="137918147", is_at_bot=False, at_user_ids=[])

            assert plugin._memory_injection_enabled_for_message(private_msg) is True
            # Current safety policy: group prompt injection is hard-disabled.
            # Split switches remain config-compatible but cannot override the group hard gate.
            assert plugin._memory_injection_enabled_for_message(group_at_msg) is False
            assert plugin._memory_injection_enabled_for_message(group_silent_msg) is False

            cfg.set("memory_prompt_injection_enabled", False)
            assert plugin._memory_injection_enabled_for_message(private_msg) is False
            assert plugin._memory_injection_enabled_for_message(group_at_msg) is False
            assert plugin._memory_injection_enabled_for_message(group_silent_msg) is False
    finally:
        plugin.cfg = original_cfg


def test_stability_group_observation_semantics_for_silent_and_mention() -> None:
    original_cfg = plugin.cfg
    original_store = plugin.store
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = RuntimeConfig(DEFAULTS, path=Path(tmpdir) / "runtime_config.json")
            cfg.set("memory_short_term_capture_enabled", True)
            cfg.set("memory_prompt_injection_enabled", True)
            cfg.set("memory_prompt_injection_group_mention_enabled", True)
            cfg.set("memory_prompt_injection_group_silent_enabled", False)
            store = _build_store(tmpdir)
            store.add_to_short_term("group:137918147", {"uid": "3916107556", "nick": "小维", "text": "历史群记忆"})
            plugin.cfg = cfg
            plugin.store = store

            silent_msg = _build_msg(uid="3916107556", nick="小维", channel="group", group_id="137918147", text="没@", is_at_bot=False)
            silent_decision = SimpleNamespace(should_reply=False)
            silent_captured = plugin._capture_short_term_memory(silent_msg)
            silent_observation = plugin._collect_memory_observation(silent_msg, silent_decision, captured=silent_captured)
            assert silent_observation["captured"] is True
            assert silent_observation["will_reply"] is False
            assert silent_observation["prompt_injected"] is False
            assert silent_observation["is_mentioned"] is False

            mention_msg = _build_msg(uid="3916107556", nick="小维", channel="group", group_id="137918147", text="@bot 记得吗", is_at_bot=True, at_user_ids=["90001"])
            mention_decision = Decision(True, "warm", "v4_flash", 2, target_uid="3916107556", reason="at_bot", is_forced=True)
            builder = PromptBuilder(store=store, skill_loader=None, memory_enabled=plugin._memory_injection_enabled_for_message(mention_msg))
            messages = builder.build_messages(mention_msg, mention_decision, history=[], session_id="group:137918147")
            mention_observation = plugin._collect_memory_observation(mention_msg, mention_decision, captured=True, session_id="group:137918147", messages=messages)
            assert mention_observation["will_reply"] is True
            # Current safety policy: group messages may be captured/observed, but prompt injection
            # stays disabled even for mentions.
            assert mention_observation["prompt_injected"] is False
            assert mention_observation["is_mentioned"] is True
            assert mention_observation["memory_prompt_chars"] == 0
    finally:
        plugin.cfg = original_cfg
        plugin.store = original_store
