from __future__ import annotations

from mock_pipeline_runtime import prepare_modules  # type: ignore

prepare_modules()

from plugins.yangyang.memory.grounding import RuleBasedGroundingResolver
from plugins.yangyang.memory.types import LongTermMemoryEntry


def _entry(slot: str, value: str, *, scope: str = "private_user", scope_id: str = "335059272") -> LongTermMemoryEntry:
    return LongTermMemoryEntry(
        id=f"mem_{slot}_{value}",
        status="active",
        scope=scope,
        scope_id=scope_id,
        session_id=f"private:{scope_id}" if scope == "private_user" else f"group:{scope_id}",
        user_id=scope_id if scope == "private_user" else "335059272",
        group_id="" if scope == "private_user" else scope_id,
        channel="private" if scope == "private_user" else "group",
        kind="preference",
        slot=slot,
        value=value,
        summary=f"用户说：{value}",
        confidence=0.8,
        support_count=1,
        created_at="2026-06-05T15:50:00+08:00",
        updated_at="2026-06-05T15:50:00+08:00",
        last_seen_at="2026-06-05T15:50:00+08:00",
    )


def test_grounding_expands_favorite_game_and_matches_memory_value() -> None:
    resolver = RuleBasedGroundingResolver()
    result = resolver.ground("我晚上喜欢打什么游戏", entries=[_entry("favorite_game", "打绝区零")])

    assert result.status == "resolved"
    assert "favorite_game" in result.expanded_slots
    assert any(item.canonical == "绝区零" and item.kind == "game" for item in result.entity_candidates)
    assert "slot_expanded" in result.reasons


def test_grounding_drink_query_expands_drink_and_food_compat_slot() -> None:
    resolver = RuleBasedGroundingResolver()
    result = resolver.ground("我喜欢喝什么", entries=[_entry("favorite_drink", "脉动")])

    assert result.status == "resolved"
    assert "favorite_drink" in result.expanded_slots
    assert "favorite_food" in result.expanded_slots
    assert any(item.canonical == "脉动" and item.kind == "drink" for item in result.entity_candidates)


def test_grounding_alias_zzz_resolves_to_zenless_zone_zero() -> None:
    resolver = RuleBasedGroundingResolver()
    result = resolver.ground("zzz 是什么来着")

    assert result.status == "resolved"
    assert "zzz" in tuple(term.lower() for term in result.alias_terms)
    assert any(item.canonical == "绝区零" and item.kind == "game" for item in result.entity_candidates)


def test_short_alias_without_domain_hint_is_ambiguous() -> None:
    resolver = RuleBasedGroundingResolver()
    result = resolver.ground("绝是什么意思")

    assert result.status == "ambiguous"
    assert any(item.canonical == "绝区零" for item in result.entity_candidates)
    assert "ambiguous_short_alias" in result.reasons


def test_short_alias_with_game_domain_hint_can_resolve() -> None:
    resolver = RuleBasedGroundingResolver()
    result = resolver.ground("绝是什么游戏")

    assert result.status == "resolved"
    assert any(item.canonical == "绝区零" and item.kind == "game" for item in result.entity_candidates)


def test_multiple_game_memory_candidates_are_ambiguous() -> None:
    resolver = RuleBasedGroundingResolver()
    result = resolver.ground(
        "我最近喜欢玩什么",
        entries=[_entry("favorite_game", "打绝区零"), _entry("favorite_game", "鸣潮")],
    )

    assert result.status == "ambiguous"
    assert {item.canonical for item in result.entity_candidates} == {"绝区零", "鸣潮"}
    assert "multiple_entity_candidates" in result.reasons


def test_empty_or_unmatched_query_does_not_invent_memory() -> None:
    resolver = RuleBasedGroundingResolver()
    result = resolver.ground("我说的那个东西")

    assert result.status == "none"
    assert result.entity_candidates == ()
    assert result.expanded_slots == ()
    assert "no_grounding_match" in result.reasons


def test_resolver_does_not_mutate_entries() -> None:
    resolver = RuleBasedGroundingResolver()
    entry = _entry("favorite_game", "打绝区零")
    before = entry.to_dict()

    resolver.ground("我晚上喜欢打什么游戏", entries=[entry])

    assert entry.to_dict() == before

from plugins.yangyang.memory.retrieval import MemoryRetriever


def test_retriever_can_use_resolved_grounding_alias_hint_without_store_integration() -> None:
    resolver = RuleBasedGroundingResolver()
    retriever = MemoryRetriever()
    entries = [
        _entry("favorite_drink", "脉动"),
        _entry("favorite_game", "打绝区零"),
    ]
    grounding = resolver.ground("zzz 是什么来着")

    result = retriever.retrieve(
        entries,
        query="zzz 是什么来着",
        user_id="335059272",
        group_id="",
        top_k=1,
        grounding_result=grounding,
    )

    assert len(result) == 1
    assert result[0].slot == "favorite_game"
    assert result[0].value == "打绝区零"


def test_retriever_does_not_hard_select_ambiguous_grounding_hint() -> None:
    resolver = RuleBasedGroundingResolver()
    retriever = MemoryRetriever()
    entries = [
        _entry("favorite_drink", "脉动"),
        _entry("favorite_game", "打绝区零"),
    ]
    grounding = resolver.ground("绝是什么意思")

    assert grounding.status == "ambiguous"
    result = retriever.retrieve(
        entries,
        query="绝是什么意思",
        user_id="335059272",
        group_id="",
        top_k=1,
        grounding_result=grounding,
    )

    # Ambiguous grounding must not force the alias candidate to the top.
    assert result[0].slot == "favorite_drink"


def test_retriever_grounding_hint_still_respects_existing_scope_filter() -> None:
    resolver = RuleBasedGroundingResolver()
    retriever = MemoryRetriever()
    other_user_entry = _entry("favorite_game", "打绝区零", scope="private_user", scope_id="999999")
    grounding = resolver.ground("zzz 是什么来着")

    result = retriever.retrieve(
        [other_user_entry],
        query="zzz 是什么来着",
        user_id="335059272",
        group_id="",
        top_k=3,
        grounding_result=grounding,
    )

    assert result == []

import tempfile
from pathlib import Path
from unittest.mock import patch

from plugins.yangyang.memory.store import MemoryStore


def _store(tmpdir: str, *, grounding_enabled: bool = False, top_k: int = 3) -> MemoryStore:
    store = MemoryStore(
        str(Path(tmpdir) / "chat.db"),
        str(Path(tmpdir) / "cache"),
        owner_id="335059272",
        retrieval_enabled=True,
        retrieval_private_only=True,
        retrieval_top_k=top_k,
        retrieval_char_budget=500,
        retrieval_grounding_enabled=grounding_enabled,
    )
    return store


def test_memory_store_grounding_default_disabled_does_not_call_resolver() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store(tmpdir, grounding_enabled=False, top_k=1)
        store.append_long_term_entry(_entry("favorite_drink", "脉动"))
        store.append_long_term_entry(_entry("favorite_game", "打绝区零"))

        with patch("plugins.yangyang.memory.store.RuleBasedGroundingResolver") as mocked:
            prompt = store.build_memory_prompt(
                "335059272",
                "private:335059272",
                query="zzz 是什么来着",
            )

        mocked.assert_not_called()
        # Default-off means no alias resolver participates. Existing C4 fallback may still
        # inject some scoped memory by generic score; with equal scores and top_k=1, the
        # first inserted drink memory remains first instead of zzz promoting the game.
        assert "脉动" in prompt
        assert "绝区零" not in prompt


def test_memory_store_grounding_enabled_can_help_alias_retrieval() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store(tmpdir, grounding_enabled=True, top_k=1)
        store.append_long_term_entry(_entry("favorite_drink", "脉动"))
        store.append_long_term_entry(_entry("favorite_game", "打绝区零"))

        prompt = store.build_memory_prompt(
            "335059272",
            "private:335059272",
            query="zzz 是什么来着",
        )

        assert "绝区零" in prompt
        assert "脉动" not in prompt


def test_memory_store_grounding_not_called_for_group_because_group_never_injects() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store(tmpdir, grounding_enabled=True)
        store.append_long_term_entry(_entry("favorite_game", "打绝区零"))

        with patch("plugins.yangyang.memory.store.RuleBasedGroundingResolver") as mocked:
            prompt = store.build_memory_prompt(
                "335059272",
                "group:137918147",
                query="zzz 是什么来着",
            )

        mocked.assert_not_called()
        assert "绝区零" not in prompt
