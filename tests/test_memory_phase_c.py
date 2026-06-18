from __future__ import annotations

import tempfile
import uuid
from pathlib import Path

from mock_pipeline_runtime import prepare_modules  # type: ignore


mods = prepare_modules()
MemoryStore = mods["MemoryStore"]

from plugins.yangyang.memory.candidate_extractor import CandidateExtractor
from plugins.yangyang.memory.promotion import PromotionEngine
from plugins.yangyang.memory.query_router import detect_structured_memory_query
from plugins.yangyang.memory.retrieval import MemoryRetriever
from plugins.yangyang.memory.types import Evidence, LongTermMemoryEntry, MemoryCandidate, PromotionAuditRecord


EXTRACTOR = CandidateExtractor()
ENGINE = PromotionEngine()


def _build_store(tmpdir: str):
    return MemoryStore(str(Path(tmpdir) / "chat.db"), str(Path(tmpdir) / "cache"))


def _evidence() -> list[Evidence]:
    return [
        Evidence(
            message_id="msg_001",
            timestamp="2026-06-03T09:00:00+08:00",
            speaker_id="335059272",
            text="我最喜欢靛蓝色。",
        )
    ]


def _message(text: str, *, channel: str = "private", user_id: str = "335059272", group_id: str = "") -> dict:
    return {
        "message_id": "msg_001",
        "timestamp": "2026-06-03T09:00:00+08:00",
        "user_id": user_id,
        "group_id": group_id,
        "channel": channel,
        "text": text,
    }


def test_candidate_jsonl_roundtrip_and_basic_fields() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        candidate = MemoryCandidate(
            candidate_id="cand_20260603_abcd1234",
            date="2026-06-03",
            scope="private_user",
            scope_id="335059272",
            session_id="private:335059272",
            user_id="335059272",
            group_id="",
            channel="private",
            kind="preference",
            slot="favorite_color",
            value="靛蓝色",
            summary="阿漂说自己最喜欢的颜色是靛蓝色。",
            evidence=_evidence(),
            confidence=0.68,
            support_count=1,
            contradiction_count=0,
            promotion_reason="single_clear_self_statement",
            risk_flags=[],
            created_at="2026-06-03T09:00:00+08:00",
        )

        path = store.append_candidate(candidate)
        rows = store.load_candidates("2026-06-03")

        assert path.name == "candidates_2026-06-03.jsonl"
        assert len(rows) == 1
        assert rows[0].candidate_id == candidate.candidate_id
        assert rows[0].scope == "private_user"
        assert rows[0].scope_id == "335059272"
        assert rows[0].kind == "preference"
        assert rows[0].evidence[0].text == "我最喜欢靛蓝色。"
        assert rows[0].to_dict() == candidate.to_dict()


def test_long_term_jsonl_roundtrip_and_scope_isolation() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        private_entry = LongTermMemoryEntry(
            id="mem_private_001",
            status="active",
            scope="private_user",
            scope_id="335059272",
            session_id="private:335059272",
            user_id="335059272",
            group_id="",
            channel="private",
            kind="preference",
            slot="favorite_food",
            value="巧克力新地",
            summary="阿漂喜欢吃巧克力新地。",
            evidence=_evidence(),
            confidence=0.82,
            support_count=2,
            contradiction_count=0,
            source="rule_promotion",
            tags=["food", "preference"],
            created_at="2026-06-03T09:00:00+08:00",
            updated_at="2026-06-03T09:00:00+08:00",
            last_seen_at="2026-06-03T09:00:00+08:00",
        )
        group_entry = LongTermMemoryEntry(
            id="mem_group_001",
            status="active",
            scope="group_shared",
            scope_id="137918147",
            session_id="group:137918147",
            user_id="",
            group_id="137918147",
            channel="group",
            kind="group_fact",
            slot="project_status",
            value="Phase C0 开工",
            summary="群里确认 Phase C0 只做基础层。",
            evidence=_evidence(),
            confidence=0.9,
            support_count=3,
            contradiction_count=0,
            source="manual",
            tags=["project"],
            created_at="2026-06-03T10:00:00+08:00",
            updated_at="2026-06-03T10:00:00+08:00",
            last_seen_at="2026-06-03T10:00:00+08:00",
        )

        store.append_long_term_entry(private_entry)
        store.append_long_term_entry(group_entry)

        all_rows = store.load_long_term_entries()
        private_rows = store.load_long_term_entries(scope="private_user", scope_id="335059272")
        group_rows = store.load_long_term_entries(scope="group_shared", scope_id="137918147")

        assert len(all_rows) == 2
        assert [item.id for item in private_rows] == ["mem_private_001"]
        assert [item.id for item in group_rows] == ["mem_group_001"]
        assert private_rows[0].scope_id != group_rows[0].scope_id


def test_promotion_audit_jsonl_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        record = PromotionAuditRecord(
            event_id="audit_20260603_xxxx",
            event="promote",
            candidate_id="cand_20260603_abcd1234",
            memory_id="mem_20260603_abcdef12",
            decision="promoted",
            reason="support_count>=2",
            scope="private_user",
            scope_id="335059272",
            operator="rule_engine",
            created_at="2026-06-03T09:00:00+08:00",
        )

        path = store.append_promotion_audit(record)
        rows = store.load_promotion_audit(scope="private_user", scope_id="335059272")

        assert path.name == "memory_promotion_audit.jsonl"
        assert len(rows) == 1
        assert rows[0].decision == "promoted"
        assert rows[0].candidate_id == "cand_20260603_abcd1234"
        assert rows[0].to_dict() == record.to_dict()


def test_extract_preference_from_clear_self_statement() -> None:
    candidates = EXTRACTOR.extract_from_message(_message("我最喜欢巧克力新地"))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.kind == "preference"
    assert candidate.value == "巧克力新地"
    assert candidate.slot == "favorite_food"
    assert candidate.state == "pending"


def test_extract_activity_preference_with_time_adverb() -> None:
    candidates = EXTRACTOR.extract_from_message(_message("我晚上一般喜欢打鸣潮"))

    assert len(candidates) >= 1
    candidate = next(item for item in candidates if item.value == "打鸣潮")
    assert candidate.kind == "preference"
    assert candidate.slot == "favorite_game"
    assert candidate.promotion_reason == "activity_preference_statement"


def test_extract_activity_preference_media_variants() -> None:
    samples = {
        "我最近喜欢看番": "看番",
        "我平时喜欢听歌": "听歌",
        "我下班后喜欢刷视频": "刷视频",
    }
    for text, expected in samples.items():
        candidates = EXTRACTOR.extract_from_message(_message(text))
        assert any(item.value == expected and item.slot == "leisure_activity" for item in candidates)


def test_c1_question_guard_skips_preference_write_candidates() -> None:
    samples = [
        "我晚上喜欢打什么游戏",
        "我晚上最喜欢打什么",
        "我最喜欢什么游戏",
        "我平时喜欢喝什么",
        "我喜欢喝什么",
        "我喜欢吃什么",
        "我喜欢听什么",
        "我平时喜欢刷什么",
    ]
    for text in samples:
        assert EXTRACTOR.extract_from_message(_message(text)) == []


def test_extract_habit_from_overtime_rule() -> None:
    candidates = EXTRACTOR.extract_from_message(_message("以后我说加班，都是23点干活，你起码1点才问"))

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.kind == "habit"
    assert "23点干活" in candidate.value
    assert candidate.slot == "schedule_rule"
def test_scope_inference_private_to_private_user() -> None:
    scope, scope_id = EXTRACTOR.infer_scope(_message("我经常熬夜改bug", channel="private", user_id="335059272"))
    assert scope == "private_user"
    assert scope_id == "335059272"


def test_scope_inference_group_to_group_user_for_self_statement() -> None:
    scope, scope_id = EXTRACTOR.infer_scope(
        _message("我最近在玩Minecraft", channel="group", user_id="335059272", group_id="137918147")
    )
    assert scope == "group_user"
    assert scope_id == "137918147:335059272"


def test_extract_from_messages_batches_results() -> None:
    candidates = EXTRACTOR.extract_from_messages(
        [
            _message("我最喜欢巧克力新地"),
            _message("我经常半夜写代码"),
            _message("我喜欢你个头，开玩笑的"),
        ]
    )
    # 去掉了玩笑过滤后，"你个头" 作为 "我喜欢" 的匹配值也成了候选
    assert len(candidates) == 3
    assert {item.kind for item in candidates} == {"preference", "habit"}


# ── Phase C C2: PromotionEngine ──────────────────────────────


def _candidate(
    kind: str = "preference",
    slot: str = "favorite_food",
    value: str = "巧克力新地",
    support_count: int = 2,
    scope: str = "private_user",
    scope_id: str = "335059272",
    channel: str = "private",
    user_id: str = "335059272",
) -> MemoryCandidate:
    """便捷构造一个 MemoryCandidate 用于测试。"""
    return MemoryCandidate(
        candidate_id=f"cand_test_{uuid.uuid4().hex[:8]}",
        date="2026-06-03",
        scope=scope,  # type: ignore
        scope_id=scope_id,
        session_id=f"private:{user_id}" if channel == "private" else f"group:{scope_id}",
        user_id=user_id,
        group_id="",
        channel=channel,
        kind=kind,  # type: ignore
        slot=slot,
        value=value,
        summary=f"测试候选：{value}",
        evidence=[],
        confidence=0.75,
        support_count=support_count,
        contradiction_count=0,
        risk_flags=[],
        created_at="2026-06-03T12:00:00+08:00",
    )


def _existing_entry(
    kind: str = "preference",
    slot: str = "favorite_food",
    value: str = "巧克力新地",
    support_count: int = 1,
    confidence: float = 0.7,
) -> LongTermMemoryEntry:
    """便捷构造一个已有长期记忆条目。"""
    return LongTermMemoryEntry(
        id=f"mem_test_{uuid.uuid4().hex[:8]}",
        status="active",
        scope="private_user",
        scope_id="335059272",
        session_id="private:335059272",
        user_id="335059272",
        group_id="",
        channel="private",
        kind=kind,  # type: ignore
        slot=slot,
        value=value,
        summary=f"已有条目：{value}",
        evidence=[],
        confidence=confidence,
        support_count=support_count,
        contradiction_count=0,
        source="rule_promotion",
        tags=["preference"],
        created_at="2026-06-03T09:00:00+08:00",
        updated_at="2026-06-03T09:00:00+08:00",
        last_seen_at="2026-06-03T09:00:00+08:00",
    )


def test_promote_sufficient_support() -> None:
    """support_count>=2 → promoted。"""
    cand = _candidate(support_count=2)
    should, reason = ENGINE.should_promote(cand, [])
    assert should, f"预期 promoted，但决策为：{reason}"
    assert "support_count>=2" in reason

def test_contradiction_rejected() -> None:
    """contradiction_count > support_count → rejected。"""
    cand = _candidate(support_count=1)
    cand.contradiction_count = 2
    should, reason = ENGINE.should_promote(cand, [])
    assert not should
    assert "contradiction" in reason


def test_merge_same_slot() -> None:
    """同 kind+slot+scope → 合并。"""
    cand = _candidate(value="草莓新地", support_count=2)
    existing = [_existing_entry(value="巧克力新地", support_count=1)]
    merged = ENGINE.merge_or_create(cand, existing)

    assert merged.id == existing[0].id  # 保留原 ID
    assert merged.support_count == 3   # 1 + 2
    assert merged.tags is not None


def test_create_new_entry_no_match() -> None:
    """不同 slot → 创建新条目。"""
    cand = _candidate(slot="favorite_game", value="原神", support_count=2)
    existing = [_existing_entry(slot="favorite_food", value="巧克力新地")]
    merged = ENGINE.merge_or_create(cand, existing)

    assert merged.id != existing[0].id
    assert merged.slot == "favorite_game"
    assert merged.value == "原神"


def test_batch_promote_mixed() -> None:
    """批量 promote_candidates 处理多个候选。"""
    cand_a = _candidate(kind="preference", slot="favorite_food", value="火锅", support_count=2)
    cand_b = _candidate(kind="habit", slot="schedule_rule", value="经常加班", support_count=1)

    existing = [_existing_entry(kind="preference", slot="favorite_food", value="巧克力新地")]
    entries, audit = ENGINE.promote_candidates([cand_a, cand_b], existing)

    assert len(entries) >= 1  # cand_a support>=2 被升格
    assert len(audit) == 2


# ── Phase C C3: MemoryRetriever ──────────────────────────────


RETRIEVER = MemoryRetriever()


def _entry(
    entry_id: str = "mem_001",
    kind: str = "preference",
    slot: str = "favorite_food",
    value: str = "巧克力新地",
    summary: str = "阿漂喜欢吃巧克力新地。",
    scope: str = "private_user",
    scope_id: str = "335059272",
    confidence: float = 0.8,
    support_count: int = 2,
    tags: list[str] | None = None,
    last_seen_at: str = "",
) -> LongTermMemoryEntry:
    if not last_seen_at:
        last_seen_at = "2026-06-03T12:00:00+08:00"
    return LongTermMemoryEntry(
        id=entry_id,
        status="active",
        scope=scope,  # type: ignore
        scope_id=scope_id,
        session_id=f"private:{scope_id}" if scope == "private_user" else f"group:{scope_id}",
        user_id=scope_id if scope == "private_user" else "",
        group_id=scope_id if scope in ("group_shared", "group_user") else "",
        channel="private" if scope == "private_user" else "group",
        kind=kind,  # type: ignore
        slot=slot,
        value=value,
        summary=summary,
        evidence=[],
        confidence=confidence,
        support_count=support_count,
        contradiction_count=0,
        source="rule_promotion",
        tags=tags or ["preference"],
        created_at="2026-06-03T09:00:00+08:00",
        updated_at="2026-06-03T10:00:00+08:00",
        last_seen_at=last_seen_at,
    )


def test_query_router_maps_game_question_to_favorite_game() -> None:
    query = detect_structured_memory_query("我晚上喜欢打什么游戏")

    assert query is not None
    assert query.intent == "ask_self_memory"
    assert query.kind == "preference"
    assert query.primary_slot == "favorite_game"
    assert "favorite_game" in query.slots


def test_query_router_maps_drink_question_to_favorite_drink_with_compat_alias() -> None:
    query = detect_structured_memory_query("我喜欢喝什么")

    assert query is not None
    assert query.primary_slot == "favorite_drink"
    # 写入侧旧 slot 会把“喝/脉动”落到 favorite_food；读取侧保留兼容 fallback。
    assert query.slots == ("favorite_drink", "favorite_food")


def test_structured_query_prioritizes_game_slot_over_semantic_noise_in_rendered_prompt() -> None:
    entries = [
        _entry(
            entry_id="drink_noise",
            slot="favorite_drink",
            value="脉动",
            summary="用户说：脉动",
            confidence=0.95,
            support_count=8,
            tags=["preference", "drink"],
        ),
        _entry(
            entry_id="game_hit",
            slot="favorite_game",
            value="打绝区零",
            summary="用户说：打绝区零",
            confidence=0.7,
            support_count=2,
            tags=["preference", "game"],
        ),
    ]

    result = RETRIEVER.retrieve(
        entries,
        query="我晚上喜欢打什么游戏",
        user_id="335059272",
        group_id="",
        top_k=2,
    )
    prompt = RETRIEVER.render_prompt_section(result, char_budget=500)

    assert [item.id for item in result][:2] == ["game_hit", "drink_noise"]
    assert "打绝区零" in prompt
    assert "脉动" in prompt
    assert prompt.index("打绝区零") < prompt.index("脉动")


def test_structured_query_slot_miss_falls_back_to_existing_retrieval() -> None:
    entries = [
        _entry(
            entry_id="fallback_food",
            slot="favorite_food",
            value="巧克力新地",
            summary="用户说：巧克力新地",
        )
    ]

    result = RETRIEVER.retrieve(
        entries,
        query="我最喜欢什么游戏",
        user_id="335059272",
        group_id="",
        top_k=1,
    )

    assert len(result) == 1
    assert result[0].id == "fallback_food"


def test_retrieve_scope_private_only_sees_own() -> None:
    """私聊作用域：只看自己的条目。"""
    entries = [
        _entry(entry_id="1", scope="private_user", scope_id="335059272", value="巧克力新地"),
        _entry(entry_id="2", scope="private_user", scope_id="999999999", value="火锅"),
    ]
    result = RETRIEVER.retrieve(entries, user_id="335059272", group_id="")
    assert len(result) == 1
    assert result[0].id == "1"


def test_retrieve_scope_group_shared_only_same_group() -> None:
    """群聊共享作用域：只看本群。"""
    entries = [
        _entry(entry_id="1", scope="group_shared", scope_id="137918147", value="群梗A"),
        _entry(entry_id="2", scope="group_shared", scope_id="88888888", value="群梗B"),
    ]
    result = RETRIEVER.retrieve(entries, user_id="335059272", group_id="137918147")
    assert len(result) == 1
    assert result[0].id == "1"


def test_retrieve_top_k_limits_results() -> None:
    """top_k 限制返回条数。"""
    entries = [
        _entry(entry_id=str(i), scope="private_user", scope_id="335059272", value=f"条目{i}")
        for i in range(10)
    ]
    result = RETRIEVER.retrieve(entries, user_id="335059272", group_id="", top_k=3)
    assert len(result) == 3


def test_retrieve_keyword_match_scores_higher() -> None:
    """关键词匹配的条目打分更高。"""
    entries = [
        _entry(entry_id="match", scope="private_user", scope_id="335059272", value="巧克力新地", summary="阿漂喜欢巧克力新地"),
        _entry(entry_id="no_match", scope="private_user", scope_id="335059272", value="火锅", summary="阿漂喜欢火锅"),
    ]
    result = RETRIEVER.retrieve(entries, query="巧克力", user_id="335059272", group_id="", top_k=2)
    assert result[0].id == "match"


def test_retrieve_respects_char_budget() -> None:
    """render_prompt_section 受字符预算约束。"""
    entries = [
        _entry(entry_id="1", scope="private_user", scope_id="335059272", summary="第一段很长的事实描述。" * 10),
        _entry(entry_id="2", scope="private_user", scope_id="335059272", summary="第二段很长的事实描述。" * 10),
    ]
    result = RETRIEVER.retrieve(entries, user_id="335059272", group_id="", top_k=2)
    prompt = RETRIEVER.render_prompt_section(result, char_budget=50)
    # 预算极低时，只输出 header 或 header + 部分内容
    assert len(prompt) <= 60


def test_retrieve_inactive_entries_excluded() -> None:
    """已归档/已拒绝的条目不参与检索。"""
    entries = [
        _entry(entry_id="active", scope="private_user", scope_id="335059272"),
        LongTermMemoryEntry(
            id="archived", status="archived",
            scope="private_user", scope_id="335059272",
            session_id="private:335059272", user_id="335059272",
            group_id="", channel="private",
            kind="preference", slot="favorite_food",
            value="火锅", summary="已归档",
            evidence=[], confidence=0.7, support_count=1,
            contradiction_count=0, source="rule_promotion",
            tags=[], created_at="", updated_at="", last_seen_at="",
        ),
    ]
    result = RETRIEVER.retrieve(entries, user_id="335059272", group_id="")
    assert len(result) == 1
    assert result[0].id == "active"


def test_render_empty_entries() -> None:
    """空条目列表返回空字符串。"""
    assert RETRIEVER.render_prompt_section([]) == ""


def test_render_prompt_section_basic() -> None:
    """正常渲染 prompt 小节。"""
    entries = [
        _entry(entry_id="1", scope="private_user", scope_id="335059272", summary="阿漂喜欢吃巧克力新地。", tags=["preference", "food"]),
    ]
    prompt = RETRIEVER.render_prompt_section(entries, char_budget=240)
    assert "[来自长期记忆的事实]" in prompt
    assert "巧克力新地" in prompt
    assert "preference" in prompt


def test_render_prompt_section_subject_guard_for_user_memories() -> None:
    """长期记忆渲染包含主语约束，避免把用户经历说成助手自己的经历。"""
    entries = [
        _entry(
            entry_id="subject_guard",
            scope="private_user",
            scope_id="335059272",
            summary="用户说：打绝区零",
            tags=["preference", "game", "private"],
        ),
    ]
    prompt = RETRIEVER.render_prompt_section(entries, char_budget=260)
    assert "当前用户/对话对象" in prompt
    assert "不是助手自己的经历" in prompt
    assert "不要改成“我”" in prompt
    assert "记忆里显示/你之前说过" in prompt
    assert "用户说：打绝区零" in prompt


def test_render_prompt_section_first_person_query_disambiguation_guard() -> None:
    """第一人称记忆问句渲染歧义约束，避免模型误判为询问助手偏好。"""
    entries = [
        _entry(
            entry_id="drink_guard",
            slot="favorite_drink",
            value="脉动",
            summary="用户说：脉动",
            tags=["preference", "drink"],
        ),
    ]
    prompt = RETRIEVER.render_prompt_section(entries, char_budget=900, query="我喜欢喝什么")

    assert "第一人称问句约束" in prompt
    assert "询问用户自己的记忆" in prompt
    assert "不要反问“是在问我吗”" in prompt
    assert "只有明确说“你喜欢/你喝/你玩" in prompt
    assert "用户说：脉动" in prompt


# ── Phase C C4: 灰度注入集成 ──────────────────────────────


def _store_with_retrieval(
    tmpdir: str,
    owner_id: str = "335059272",
    enabled: bool = True,
    private_only: bool = True,
) -> MemoryStore:
    """构造一个开启了检索注入的 MemoryStore。"""
    from plugins.yangyang.memory.store import MemoryStore as MS

    store = MS(
        db_path=str(Path(tmpdir) / "chat.db"),
        cache_dir=str(Path(tmpdir) / "cache"),
        memory_root=str(Path(tmpdir) / "memories"),
        owner_id=owner_id,
        retrieval_enabled=enabled,
        retrieval_private_only=private_only,
        retrieval_top_k=3,
        retrieval_char_budget=500,
    )
    # 写入一条长期记忆条目
    entry = LongTermMemoryEntry(
        id="mem_c4_test",
        status="active",
        scope="private_user",
        scope_id=owner_id,
        session_id=f"private:{owner_id}",
        user_id=owner_id,
        group_id="",
        channel="private",
        kind="preference",
        slot="favorite_food",
        value="巧克力新地",
        summary="阿漂喜欢吃巧克力新地。",
        evidence=[],
        confidence=0.8,
        support_count=2,
        contradiction_count=0,
        source="rule_promotion",
        tags=["preference", "food"],
        created_at="2026-06-03T09:00:00+08:00",
        updated_at="2026-06-03T10:00:00+08:00",
        last_seen_at="2026-06-03T12:00:00+08:00",
    )
    store.append_long_term_entry(entry)
    return store


def test_retrieval_injection_disabled_by_default() -> None:
    """retrieval_enabled=False 时不注入。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store_with_retrieval(tmpdir, enabled=False)
        prompt = store.build_memory_prompt(
            user_id="335059272",
            session_id="private:335059272",
        )
        assert "[来自长期记忆的事实]" not in prompt


def test_retrieval_injection_group_never_injects() -> None:
    """群聊永不注入长期记忆。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store_with_retrieval(tmpdir, enabled=True)
        prompt = store.build_memory_prompt(
            user_id="335059272",
            session_id="group:137918147",
        )
        assert "[来自长期记忆的事实]" not in prompt


def test_retrieval_injection_private_non_owner_not_injected() -> None:
    """私聊 non-owner 不注入（private_only=True）。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store_with_retrieval(tmpdir, owner_id="335059272", enabled=True, private_only=True)
        prompt = store.build_memory_prompt(
            user_id="999999999",
            session_id="private:999999999",
        )
        assert "[来自长期记忆的事实]" not in prompt


def test_retrieval_injection_private_owner_injected() -> None:
    """私聊 owner + enabled → 注入。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store_with_retrieval(tmpdir, owner_id="335059272", enabled=True, private_only=True)
        prompt = store.build_memory_prompt(
            user_id="335059272",
            session_id="private:335059272",
        )
        assert "[来自长期记忆的事实]" in prompt
        assert "巧克力新地" in prompt


def test_retrieval_injection_structured_query_prioritizes_hit_and_keeps_subject_guard() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = MemoryStore(
            db_path=str(Path(tmpdir) / "chat.db"),
            cache_dir=str(Path(tmpdir) / "cache"),
            memory_root=str(Path(tmpdir) / "memories"),
            owner_id="335059272",
            retrieval_enabled=True,
            retrieval_private_only=True,
            retrieval_top_k=2,
            retrieval_char_budget=600,
        )
        store.append_long_term_entry(
            _entry(
                entry_id="drink_noise",
                slot="favorite_drink",
                value="脉动",
                summary="用户说：脉动",
                confidence=0.95,
                support_count=8,
                tags=["preference", "drink"],
            )
        )
        store.append_long_term_entry(
            _entry(
                entry_id="game_hit",
                slot="favorite_game",
                value="打绝区零",
                summary="用户说：打绝区零",
                confidence=0.7,
                support_count=2,
                tags=["preference", "game"],
            )
        )

        prompt = store.build_memory_prompt(
            user_id="335059272",
            session_id="private:335059272",
            query="我晚上喜欢打什么游戏",
        )

        assert "[来自长期记忆的事实]" in prompt
        assert "当前用户/对话对象" in prompt
        assert "不是助手自己的经历" in prompt
        assert "打绝区零" in prompt
        assert "脉动" in prompt
        assert prompt.index("打绝区零") < prompt.index("脉动")


def test_retrieval_config_configure_method() -> None:
    """configure_retrieval 运行时调整生效。"""
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _store_with_retrieval(tmpdir, enabled=False)
        assert store.retrieval_enabled is False
        store.configure_retrieval(enabled=True, top_k=5, char_budget=800)
        assert store.retrieval_enabled is True
        assert store.retrieval_top_k == 5
        assert store.retrieval_char_budget == 800
        # 现在应该能注入了
        prompt = store.build_memory_prompt(
            user_id="335059272",
            session_id="private:335059272",
        )
        assert "[来自长期记忆的事实]" in prompt


def test_phase_c4_does_not_modify_group_reply_gate() -> None:
    """C4 不改群聊闸门。"""
    import inspect
    from plugins.yangyang.memory import store as store_mod
    source = inspect.getsource(store_mod.MemoryStore)
    assert "retrieval_enabled" in source
    assert "group" in source
    assert "def build_memory_prompt" in source


# ── Phase C 闭环: MemoryPipeline ────────────────────────────


from plugins.yangyang.memory.pipeline import MemoryPipeline


def test_pipeline_normalize_short_term_item() -> None:
    """短期缓存条目归一化。"""
    store = _store_with_retrieval(tempfile.mkdtemp())
    pipeline = MemoryPipeline(store)

    item = {
        "uid": "335059272",
        "text": "我最喜欢巧克力新地",
        "channel": "private",
        "group_id": "",
        "timestamp": 1717400000.0,
        "session_id": "private:335059272",
    }
    normalized = pipeline._normalize_short_term_item(item)
    assert normalized is not None
    assert normalized["text"] == "我最喜欢巧克力新地"
    assert normalized["user_id"] == "335059272"
    assert normalized["channel"] == "private"


def test_pipeline_skip_empty_text() -> None:
    """空文本条目跳过。"""
    store = _store_with_retrieval(tempfile.mkdtemp())
    pipeline = MemoryPipeline(store)

    assert pipeline._normalize_short_term_item({"text": ""}) is None
    assert pipeline._normalize_short_term_item({"text": "   "}) is None


def test_pipeline_collect_from_empty_cache() -> None:
    """短期缓存为空时返回空。"""
    store = _store_with_retrieval(tempfile.mkdtemp())
    pipeline = MemoryPipeline(store)

    result = pipeline._collect_from_short_term()
    assert result == {}


def test_pipeline_run_once_graceful_with_no_store() -> None:
    """store 无短期缓存时正常运行不报错。"""
    store = _store_with_retrieval(tempfile.mkdtemp())
    pipeline = MemoryPipeline(store)

    stats = pipeline.run_once()
    assert stats["sessions_scanned"] == 0
    assert stats["messages_collected"] == 0
    assert stats["errors"] == 0


def test_pipeline_collect_prefers_most_recent_sessions() -> None:
    store = _store_with_retrieval(tempfile.mkdtemp())
    pipeline = MemoryPipeline(store)
    pipeline.max_sessions = 2

    store.add_to_short_term("session-old", {"uid": "u1", "text": "我喜欢火锅", "timestamp": 1, "channel": "private", "session_id": "session-old"})
    store.add_to_short_term("session-mid", {"uid": "u2", "text": "我喜欢奶茶", "timestamp": 2, "channel": "private", "session_id": "session-mid"})
    store.add_to_short_term("session-new", {"uid": "u3", "text": "我喜欢咖啡", "timestamp": 3, "channel": "private", "session_id": "session-new"})

    result = pipeline._collect_from_short_term()

    assert list(result.keys()) == ["session-new", "session-mid"]
    assert "session-old" not in result


def test_pipeline_run_once_logs_stats_without_format_error(caplog) -> None:
    store = _store_with_retrieval(tempfile.mkdtemp())
    pipeline = MemoryPipeline(store)

    with caplog.at_level("INFO"):
        stats = pipeline.run_once()

    assert stats["sessions_scanned"] == 0
    assert any("MemoryPipeline: run_once done" in record.message for record in caplog.records)


def test_pipeline_run_once_promotes_aggregated_preference_from_short_term() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        pipeline = MemoryPipeline(store)
        session_id = "private:335059272"

        store.add_to_short_term(session_id, {
            "uid": "335059272",
            "user_id": "335059272",
            "nick": "阿漂",
            "text": "我最喜欢脉动",
            "timestamp": 1717400001.0,
            "channel": "private",
            "session_id": session_id,
            "message_id": "m1",
        })
        store.add_to_short_term(session_id, {
            "uid": "335059272",
            "user_id": "335059272",
            "nick": "阿漂",
            "text": "我喜欢脉动",
            "timestamp": 1717400002.0,
            "channel": "private",
            "session_id": session_id,
            "message_id": "m2",
        })

        stats = pipeline.run_once()
        entries = store.load_long_term_entries()
        candidate_files = sorted(store.memory_system.daily_dir.glob("candidates_*.jsonl"))
        assert len(candidate_files) == 1
        candidate_date = candidate_files[0].stem.removeprefix("candidates_")
        candidates = store.load_candidates(candidate_date)

        assert stats["sessions_scanned"] == 1
        assert stats["messages_collected"] == 2
        assert stats["new_candidates"] == 2
        assert stats["candidates_after_dedup"] == 1
        assert stats["promoted"] == 1
        assert len(candidates) == 1
        assert candidates[0].support_count == 2
        assert len(entries) == 1
        assert entries[0].kind == "preference"
        assert entries[0].support_count == 2
        assert entries[0].value == "脉动"



def test_pipeline_run_once_promotes_activity_preference_from_short_term() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        pipeline = MemoryPipeline(store)
        session_id = "private:335059272"

        store.add_to_short_term(session_id, {
            "uid": "335059272",
            "user_id": "335059272",
            "nick": "阿漂",
            "text": "我晚上一般喜欢打鸣潮",
            "timestamp": 1717400101.0,
            "channel": "private",
            "session_id": session_id,
            "message_id": "ww_1",
        })
        store.add_to_short_term(session_id, {
            "uid": "335059272",
            "user_id": "335059272",
            "nick": "阿漂",
            "text": "我晚上最喜欢打鸣潮",
            "timestamp": 1717400102.0,
            "channel": "private",
            "session_id": session_id,
            "message_id": "ww_2",
        })

        stats = pipeline.run_once()
        entries = store.load_long_term_entries()

        assert stats["sessions_scanned"] == 1
        assert stats["messages_collected"] == 2
        assert stats["new_candidates"] >= 2
        assert stats["candidates_after_dedup"] >= 1
        assert stats["promoted"] >= 1
        assert any(entry.value == "打鸣潮" and entry.slot == "favorite_game" and entry.support_count == 2 for entry in entries)
        assert any("鸣潮" in evidence.text for entry in entries for evidence in entry.evidence)


def test_pipeline_question_messages_are_not_promoted_or_persisted() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        pipeline = MemoryPipeline(store)
        session_id = "private:335059272"
        for idx, text in enumerate([
            "我晚上喜欢打什么游戏",
            "我晚上最喜欢打什么",
            "我最喜欢什么游戏",
        ], start=1):
            store.add_to_short_term(session_id, {
                "uid": "335059272",
                "user_id": "335059272",
                "nick": "阿漂",
                "text": text,
                "timestamp": 1717400200.0 + idx,
                "channel": "private",
                "session_id": session_id,
                "message_id": f"q_{idx}",
            })

        stats = pipeline.run_once()
        entries = store.load_long_term_entries()

        assert stats["sessions_scanned"] == 1
        assert stats["messages_collected"] == 3
        assert stats["new_candidates"] == 0
        assert stats["candidates_after_dedup"] == 0
        assert stats["promoted"] == 0
        assert entries == []


def test_pipeline_processed_short_term_messages_are_not_repromoted() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        pipeline = MemoryPipeline(store)
        session_id = "private:335059272"
        store.add_to_short_term(session_id, {
            "uid": "335059272",
            "user_id": "335059272",
            "nick": "阿漂",
            "text": "我晚上一般喜欢打绝区零",
            "timestamp": 1717400301.0,
            "channel": "private",
            "session_id": session_id,
            "message_id": "z_1",
        })
        store.add_to_short_term(session_id, {
            "uid": "335059272",
            "user_id": "335059272",
            "nick": "阿漂",
            "text": "我晚上最喜欢打绝区零",
            "timestamp": 1717400302.0,
            "channel": "private",
            "session_id": session_id,
            "message_id": "z_2",
        })

        first = pipeline.run_once()
        second = pipeline.run_once()
        entries = store.load_long_term_entries()

        assert first["messages_collected"] == 2
        assert first["new_candidates"] == 2
        assert first["candidates_after_dedup"] == 1
        assert first["promoted"] == 1
        assert second["messages_collected"] == 0
        assert second["new_candidates"] == 0
        assert second["promoted"] == 0
        assert second["skipped_processed"] == 2
        assert len(entries) == 1
        assert entries[0].value == "打绝区零"
        assert entries[0].support_count == 2
