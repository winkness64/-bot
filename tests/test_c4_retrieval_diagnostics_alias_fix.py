from __future__ import annotations

import json
from pathlib import Path

from mock_pipeline_runtime import prepare_modules  # type: ignore


mods = prepare_modules()
PromptBuilder = mods["PromptBuilder"]

from plugins.yangyang.memory.retrieval import MemoryRetriever
from plugins.yangyang.memory.types import LongTermMemoryEntry


ROOT = Path(__file__).resolve().parents[1]
SEED_MEMORIES_PATH = ROOT / "src" / "plugins" / "yangyang" / "data" / "memory" / "long_term" / "memories.jsonl"
OWNER_UID = "335059272"

MODEL_DIVISION_QUERY = "秧秧，按你现在的迁移记忆说一下模型分工和搬家路线。"
MIGRATION_REASON_QUERY = "我们为什么要从 AstrBot 搬到 NoneBot？"
TEST_MACHINE_QUERY = "测试机同志为什么值得被记住？"


def _seed_entries() -> list[LongTermMemoryEntry]:
    entries: list[LongTermMemoryEntry] = []
    for line in SEED_MEMORIES_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        entries.append(LongTermMemoryEntry.from_dict(json.loads(line)))
    return entries


def _search_blob(entry: LongTermMemoryEntry) -> str:
    return " ".join([entry.value, entry.summary, entry.slot, entry.kind, " ".join(entry.tags)])


def test_seed_active_long_term_contains_test_machine_keyword_family() -> None:
    entries = [entry for entry in _seed_entries() if entry.status == "active"]
    assert len(entries) >= 34

    keyword_hits = {
        keyword: [entry.id for entry in entries if keyword.casefold() in _search_blob(entry).casefold()]
        for keyword in ("测试机", "先遣验证", "真机验证")
    }

    assert keyword_hits["测试机"]
    assert keyword_hits["先遣验证"]
    assert keyword_hits["真机验证"]
    assert "P4D_004_test_machine_contribution" in keyword_hits["测试机"]
    assert "P4D_004_test_machine_contribution" in keyword_hits["真机验证"]


def test_c4_retrieval_diagnostics_expose_safe_fields_for_short_window_debug() -> None:
    retriever = MemoryRetriever()
    entries = _seed_entries()

    retrieved, diagnostics = retriever.retrieve_with_diagnostics(
        entries,
        query=TEST_MACHINE_QUERY,
        user_id=OWNER_UID,
        group_id="",
        top_k=3,
    )

    assert len(retrieved) == 3
    assert len(diagnostics) == len(retrieved)
    first = diagnostics[0]
    assert first.id == retrieved[0].id
    assert first.slot == retrieved[0].slot
    assert first.kind == retrieved[0].kind
    assert first.score > 0
    assert "测试机" in first.matched_terms or "真机验证" in first.matched_terms
    assert len(first.summary_preview) <= 96
    assert "\n" not in first.summary_preview

    formatted = retriever.format_diagnostics(diagnostics)
    assert "id=" in formatted
    assert "slot=" in formatted
    assert "kind=" in formatted
    assert "score=" in formatted
    assert "matched_terms=" in formatted
    assert "preview=" in formatted

    sanitized = retriever.sanitize_preview("owner 335059272 path=/opt/yangyang_nonebot/a/b token=abcdefghi", limit=80)
    assert "335059272" not in sanitized
    assert "/opt/yangyang_nonebot" not in sanitized
    assert "abcdefghi" not in sanitized


def test_c4_model_division_query_still_hits_model_division_and_route() -> None:
    retriever = MemoryRetriever()
    result = retriever.retrieve(
        _seed_entries(),
        query=MODEL_DIVISION_QUERY,
        user_id=OWNER_UID,
        group_id="",
        top_k=3,
    )
    ids = [entry.id for entry in result]

    assert ids[0] == "P4D_001_model_division_current"
    assert "P4D_003_migration_current" in ids


def test_c4_migration_reason_query_hits_astrbot_nonebot_migration_fact() -> None:
    retriever = MemoryRetriever()
    result = retriever.retrieve(
        _seed_entries(),
        query=MIGRATION_REASON_QUERY,
        user_id=OWNER_UID,
        group_id="",
        top_k=3,
    )

    assert result[0].id == "P4D_003_migration_current"
    assert "AstrBot" in result[0].summary
    assert "NoneBot" in result[0].summary
    assert "迁移" in result[0].summary


def test_c4_test_machine_query_recalls_contribution_memory_not_model_division() -> None:
    retriever = MemoryRetriever()
    result, diagnostics = retriever.retrieve_with_diagnostics(
        _seed_entries(),
        query=TEST_MACHINE_QUERY,
        user_id=OWNER_UID,
        group_id="",
        top_k=3,
    )
    ids = [entry.id for entry in result]

    assert ids[0] == "P4D_004_test_machine_contribution"
    assert ids[0] != "P4D_001_model_division_current"
    assert "P4D_001_model_division_current" not in ids[:2]
    assert any(term in _search_blob(result[0]) for term in ("测试机", "先遣测试", "真机验证"))
    assert any(term in diagnostics[0].matched_terms for term in ("测试机", "真机验证", "贡献", "功臣"))


def test_prompt_builder_adds_light_long_term_fact_usage_guard_to_system(tmp_path: Path) -> None:
    class FakeStore:
        def build_memory_prompt(self, user_id: str, session_id: str, query: str = "") -> str:
            return "[来自长期记忆的事实]\n- 当前迁移事实：AstrBot 到 NoneBot 的迁移已经启动。"

    builder = PromptBuilder(store=FakeStore(), skill_loader=None, memory_enabled=True)
    builder.PUBLIC_MEMORY_PATH = tmp_path / "missing_public_memory.txt"
    builder.PRIVATE_MEMORY_PATH = tmp_path / "missing_private_memory.txt"
    system = builder.build_system(
        "private",
        target_uid=OWNER_UID,
        reply_style="warm",
        session_id=f"private:{OWNER_UID}",
        current_text=MIGRATION_REASON_QUERY,
        sender_uid=OWNER_UID,
    )

    assert "[来自长期记忆的事实]" in system
    assert "[长期记忆事实使用规则]" in system
    assert "具体事实、名称、阶段、分工与路径" in system
    assert "不要只给泛泛常识解释" in system
    assert system.index("[来自长期记忆的事实]") < system.index("[长期记忆事实使用规则]")


def test_prompt_builder_long_term_fact_guard_not_repeated() -> None:
    class FakeStore:
        def build_memory_prompt(self, user_id: str, session_id: str, query: str = "") -> str:
            return (
                "[来自长期记忆的事实]\n"
                "- 当前迁移事实：AstrBot 到 NoneBot 的迁移已经启动。\n"
                "[长期记忆事实使用规则]\n"
                "已有同类约束。"
            )

    builder = PromptBuilder(store=FakeStore(), skill_loader=None, memory_enabled=True)
    prompt = builder.build_optional_memory_prompt(
        target_uid=OWNER_UID,
        session_id=f"private:{OWNER_UID}",
        query_text=MIGRATION_REASON_QUERY,
    )

    assert prompt.count("[长期记忆事实使用规则]") == 1


def test_prompt_builder_does_not_add_long_term_fact_guard_without_c4_section() -> None:
    class FakeStore:
        def build_memory_prompt(self, user_id: str, session_id: str, query: str = "") -> str:
            return "[用户印象]\n- 当前用户喜欢低延迟观测。"

    builder = PromptBuilder(store=FakeStore(), skill_loader=None, memory_enabled=True)
    prompt = builder.build_optional_memory_prompt(
        target_uid=OWNER_UID,
        session_id=f"private:{OWNER_UID}",
        query_text=MIGRATION_REASON_QUERY,
    )

    assert "[来自长期记忆的事实]" not in prompt
    assert "[长期记忆事实使用规则]" not in prompt


def test_prompt_builder_long_term_fact_guard_forbids_internal_mechanism_leak() -> None:
    class FakeStore:
        def build_memory_prompt(self, user_id: str, session_id: str, query: str = "") -> str:
            return "[来自长期记忆的事实]\n- 当前迁移事实：AstrBot 到 NoneBot 的迁移已经启动。"

    builder = PromptBuilder(store=FakeStore(), skill_loader=None, memory_enabled=True)
    prompt = builder.build_optional_memory_prompt(
        target_uid=OWNER_UID,
        session_id=f"private:{OWNER_UID}",
        query_text=MIGRATION_REASON_QUERY,
    )

    assert "不要在回复中暴露" in prompt
    assert "prompt/注入/检索" in prompt
    assert "内部机制" in prompt
