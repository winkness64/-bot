from __future__ import annotations

import json
import tempfile
from pathlib import Path

from mock_pipeline_runtime import prepare_modules  # type: ignore


mods = prepare_modules()
MemoryStore = mods["MemoryStore"]

from plugins.yangyang.memory.context_resolver import resolve_recent_context_for_explicit_write
from plugins.yangyang.memory.explicit_memory import detect_explicit_memory_intent
from plugins.yangyang.memory.explicit_handler import (
    clear_explicit_memory_pending,
    handle_explicit_memory_message,
    has_explicit_memory_pending,
)
from plugins.yangyang.core.event_adapter import Message


def _build_store(tmpdir: str):
    return MemoryStore(str(Path(tmpdir) / "chat.db"), str(Path(tmpdir) / "cache"))


def test_high_confidence_write_colon_payload() -> None:
    result = detect_explicit_memory_intent("记一下：以后迁移包只发私聊")
    assert result.intent == "write"
    assert result.confidence == "high"
    assert result.needs_confirmation is False
    assert result.needs_context_resolution is False
    assert result.context_markers == ()
    assert result.payload == "以后迁移包只发私聊"
    assert result.should_write is True


def test_high_confidence_record_and_archive_payload() -> None:
    for text in ("记录一下：C3.1 stable 已通过", "存档一下：C3.1 stable 已通过"):
        result = detect_explicit_memory_intent(text)
        assert result.intent == "write"
        assert result.confidence == "high"
        assert result.needs_confirmation is False
        assert result.needs_context_resolution is False
        assert result.context_markers == ()
        assert result.payload == "C3.1 stable 已通过"


def test_memory_query_is_not_write() -> None:
    result = detect_explicit_memory_intent("你记得我昨天说了什么吗")
    assert result.intent == "query"
    assert result.intent != "write"
    assert result.needs_confirmation is False
    assert result.needs_context_resolution is False


def test_memory_audit_is_not_write() -> None:
    result = detect_explicit_memory_intent("你在记录啥")
    assert result.intent == "audit"
    assert result.intent != "write"
    assert result.needs_context_resolution is False


def test_contextual_write_detector_marks_resolution_required() -> None:
    cases = (
        ("把刚才那个记一下", {"刚才", "那个"}),
        ("刚才那个也记一下", {"刚才", "那个"}),
        ("把刚才我们的讨论内容记一下", {"刚才", "我们的讨论", "讨论内容"}),
        ("上面那段存档", {"上面那段"}),
        ("这个结论记录一下", {"这个结论"}),
        ("把这个记录一下", {"这个"}),
    )
    for text, expected_markers in cases:
        result = detect_explicit_memory_intent(text)
        assert result.intent == "write"
        assert result.confidence == "medium"
        assert result.needs_confirmation is True
        assert result.needs_context_resolution is True
        assert expected_markers.issubset(set(result.context_markers))
        assert result.context_hint == text
        assert result.should_write is False


def test_medium_confidence_write_needs_confirmation() -> None:
    result = detect_explicit_memory_intent("刚才那个也记一下")
    assert result.intent == "write"
    assert result.confidence == "medium"
    assert result.needs_confirmation is True
    assert result.needs_context_resolution is True
    assert {"刚才", "那个"}.issubset(set(result.context_markers))
    assert result.should_write is False


def test_confirm_and_cancel_words() -> None:
    assert detect_explicit_memory_intent("确认").intent == "confirm"
    assert detect_explicit_memory_intent("好").intent == "confirm"
    assert detect_explicit_memory_intent("取消").intent == "cancel"
    assert detect_explicit_memory_intent("别记").intent == "cancel"


def test_store_add_explicit_memory_metadata_and_retrieval_safe() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        entry = store.add_explicit_memory(
            user_id="335059272",
            session_id="private:335059272",
            payload="群聊不承载系统控制面",
            message_id="msg_explicit_001",
            source_text="记一下：群聊不承载系统控制面",
        )
        rows = store.load_long_term_entries(scope="private_user", scope_id="335059272")

        assert len(rows) == 1
        loaded = rows[0]
        assert loaded.id == entry.id
        assert loaded.kind == "technical_note"
        assert loaded.slot == "explicit_note"
        assert loaded.value == "群聊不承载系统控制面"
        assert loaded.source == "owner_command"
        assert "explicit" in loaded.tags
        assert "owner_command" in loaded.tags
        assert loaded.scope == "private_user"
        assert loaded.scope_id == "335059272"
        assert loaded.evidence[0].message_id == "msg_explicit_001"
        assert loaded.evidence[0].text == "记一下：群聊不承载系统控制面"

        store.configure_retrieval(enabled=True, private_only=True, top_k=3, char_budget=500)
        store.owner_id = "335059272"
        prompt = store.build_memory_prompt(
            "335059272",
            "private:335059272",
            query="你还记得群聊控制面吗",
        )
        assert "群聊不承载系统控制面" in prompt
        assert "[来自长期记忆的事实]" in prompt


def _message(
    text: str,
    *,
    uid: str = "335059272",
    channel: str = "private",
    is_owner: bool = True,
    msg_id: str | None = None,
    timestamp: float = 1717400000.0,
) -> Message:
    return Message(
        msg_id=msg_id or f"msg_{abs(hash((text, uid, channel))) % 100000}",
        uid=uid,
        nick="阿漂" if uid == "335059272" else uid,
        group_id="137918147" if channel == "group" else "",
        channel=channel,
        text=text,
        raw_content=text,
        is_at_bot=False,
        is_at_owner=False,
        is_quote_bot=False,
        quote_target_msg_id=None,
        is_owner=is_owner,
        timestamp=timestamp,
    )


def _record_recent(
    store,
    msg_id: str,
    text: str,
    *,
    created_at: float,
    uid: str = "335059272",
    is_bot: bool = False,
) -> None:
    store.record_message(
        _message(
            text,
            uid="yangyang_bot" if is_bot else uid,
            is_owner=False if is_bot else uid == "335059272",
            msg_id=msg_id,
            timestamp=created_at,
        ),
        is_bot=is_bot,
    )
    with store._connect() as conn:
        conn.execute(
            "UPDATE messages SET created_at=? WHERE msg_id=?",
            (float(created_at), msg_id),
        )


def test_handler_owner_private_high_confidence_direct_write() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        result = handle_explicit_memory_message(
            _message("记一下：以后迁移包只发私聊"),
            store,
            session_id="private:335059272",
            now=1000,
        )
        rows = store.load_long_term_entries(scope="private_user", scope_id="335059272")

        assert result.handled is True
        assert result.action == "direct_write"
        assert "记好了" in result.reply
        assert len(rows) == 1
        assert rows[0].value == "以后迁移包只发私聊"
        assert rows[0].source == "owner_command"
        assert "explicit" in rows[0].tags
        assert rows[0].evidence[0].text == "记一下：以后迁移包只发私聊"


def test_handler_contextual_write_resolves_recent_records_into_pending_payload() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record_recent(store, "r1", "今天 M2.2-A3 接入成功", created_at=100.0)
        _record_recent(store, "r2", "下一步要做真机灰度", created_at=101.0)
        _record_recent(store, "r3", "好，已经记录。", created_at=102.0, is_bot=True)

        command = "把刚才我们的讨论内容记一下"
        result = handle_explicit_memory_message(
            _message(command, msg_id="cmd_ctx", timestamp=103.0),
            store,
            session_id="private:335059272",
            now=1000,
        )
        rows = store.load_long_term_entries(scope="private_user", scope_id="335059272")

        assert result.handled is True
        assert result.action == "pending_context_confirmation"
        assert result.intent is not None
        assert result.intent.needs_context_resolution is True
        assert "近期讨论要点" in result.reply
        assert "今天 M2.2-A3 接入成功" in result.reply
        assert command not in result.reply
        assert rows == []
        assert has_explicit_memory_pending("private:335059272", "335059272") is True


def test_handler_contextual_pending_confirm_writes_resolved_payload_with_context_source() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record_recent(store, "r1", "今天 M2.2-A3 接入成功", created_at=100.0)
        _record_recent(store, "r2", "下一步要做真机灰度", created_at=101.0)

        command = "把刚才我们的讨论内容记一下"
        first = handle_explicit_memory_message(
            _message(command, msg_id="cmd_ctx", timestamp=102.0),
            store,
            session_id="private:335059272",
            now=1000,
        )
        second = handle_explicit_memory_message(
            _message("确认", msg_id="cmd_confirm", timestamp=103.0),
            store,
            session_id="private:335059272",
            now=1005,
        )
        rows = store.load_long_term_entries(scope="private_user", scope_id="335059272")

        assert first.action == "pending_context_confirmation"
        assert second.handled is True
        assert second.action == "confirmed_write"
        assert len(rows) == 1
        assert rows[0].source == "explicit_context_resolved"
        assert rows[0].value != command
        assert "今天 M2.2-A3 接入成功" in rows[0].value
        evidence_text = rows[0].evidence[0].text
        assert command in evidence_text
        assert "recent_context_resolver_v1_rules" in evidence_text
        assert "r1" in evidence_text and "r2" in evidence_text
        assert "context_range" in evidence_text
        assert has_explicit_memory_pending("private:335059272", "335059272") is False



def _topic_json_response(**kwargs) -> str:
    return json.dumps(kwargs, ensure_ascii=False)


def test_handler_contextual_write_default_uses_rules_without_topic_hook() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record_recent(store, "r1", "默认路径仍使用 A3.1 规则版", created_at=100.0)
        _record_recent(store, "r2", "没有注入 fake model 时不能尝试 B resolver", created_at=101.0)

        result = handle_explicit_memory_message(
            _message("把刚才我们的讨论内容记一下", msg_id="cmd_default_rules", timestamp=102.0),
            store,
            session_id="private:335059272",
            now=1000,
        )

        assert result.handled is True
        assert result.action == "pending_context_confirmation"
        assert "近期讨论要点" in result.reply
        assert "默认路径仍使用 A3.1 规则版" in result.reply
        assert "topic_boundary_resolver_v1_mockable" not in result.reply
        assert store.load_long_term_entries(scope="private_user", scope_id="335059272") == []
        assert has_explicit_memory_pending("private:335059272", "335059272") is True


def test_handler_contextual_write_topic_boundary_fake_resolved_then_confirm_writes_evidence() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record_recent(store, "r_old", "旧主题：A3 noisy 测试记忆已经清理", created_at=100.0)
        _record_recent(store, "r_b1", "B2-A hook 只接 fake model，不接真实 LLM", created_at=101.0)
        _record_recent(store, "r_b2", "生产默认必须继续走 A3.1 规则版", created_at=102.0)

        command = "把刚才我们的讨论内容记一下"
        fake_payload = "B2-A handler hook 通过 fake topic boundary payload 记录"
        recent_records = store.get_recent_message_records(
            channel="private",
            uid="335059272",
            session_id="private:335059272",
            limit=16,
        )
        rule_resolution = resolve_recent_context_for_explicit_write(
            detect_explicit_memory_intent(command),
            command,
            recent_records,
            max_messages=8,
            max_payload_chars=500,
        )
        assert rule_resolution.status == "resolved"
        assert rule_resolution.payload != fake_payload

        def fake_model(messages: list[dict[str, str]]) -> str:
            assert "话题边界解析器" in messages[0]["content"]
            assert command in messages[1]["content"]
            assert "r_b1" in messages[1]["content"] and "r_b2" in messages[1]["content"]
            return _topic_json_response(
                ok=True,
                status="resolved",
                payload=fake_payload,
                confidence=0.93,
                start_msg_id="r_b1",
                end_msg_id="r_b2",
                used_msg_ids=["r_b1", "r_b2"],
                reason="fake model selected the B2-A topic only",
            )

        first = handle_explicit_memory_message(
            _message(command, msg_id="cmd_topic", timestamp=103.0),
            store,
            session_id="private:335059272",
            now=1000,
            topic_boundary_model_call=fake_model,
        )
        assert first.handled is True
        assert first.action == "pending_topic_boundary_confirmation"
        assert fake_payload in first.reply
        assert str(rule_resolution.payload) not in first.reply
        assert store.load_long_term_entries(scope="private_user", scope_id="335059272") == []
        assert has_explicit_memory_pending("private:335059272", "335059272") is True

        second = handle_explicit_memory_message(
            _message("确认", msg_id="cmd_topic_confirm", timestamp=104.0),
            store,
            session_id="private:335059272",
            now=1005,
        )
        rows = store.load_long_term_entries(scope="private_user", scope_id="335059272")

        assert second.handled is True
        assert second.action == "confirmed_write"
        assert len(rows) == 1
        assert rows[0].source == "explicit_context_resolved"
        assert rows[0].value == fake_payload
        assert rows[0].value != rule_resolution.payload
        evidence = json.loads(rows[0].evidence[0].text)
        assert evidence["resolver"] == "topic_boundary_resolver_v1_mockable"
        assert evidence["used_msg_ids"] == ["r_b1", "r_b2"]
        assert evidence["context_range"]["resolver"] == "topic_boundary_resolver_v1_mockable"
        assert evidence["context_range"]["start_msg_id"] == "r_b1"
        assert evidence["context_range"]["end_msg_id"] == "r_b2"
        assert "fake model selected" in evidence["resolution_reason"]
        assert has_explicit_memory_pending("private:335059272", "335059272") is False


def test_handler_contextual_write_topic_boundary_ambiguous_does_not_fallback_or_write() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record_recent(store, "r1", "话题一：先讨论 A3.1 降噪", created_at=100.0)
        _record_recent(store, "r2", "话题二：又讨论 B2-A fake hook", created_at=101.0)

        command = "把刚才那个记一下"
        recent_records = store.get_recent_message_records(
            channel="private",
            uid="335059272",
            session_id="private:335059272",
            limit=16,
        )
        rule_resolution = resolve_recent_context_for_explicit_write(
            detect_explicit_memory_intent(command),
            command,
            recent_records,
            max_messages=8,
            max_payload_chars=500,
        )
        assert rule_resolution.status == "resolved"

        def fake_model(_messages: list[dict[str, str]]) -> str:
            return _topic_json_response(
                ok=False,
                status="ambiguous",
                payload=None,
                confidence=0.31,
                start_msg_id=None,
                end_msg_id=None,
                used_msg_ids=[],
                reason="窗口内多个话题，无法确认指代",
            )

        result = handle_explicit_memory_message(
            _message(command, msg_id="cmd_ambiguous", timestamp=102.0),
            store,
            session_id="private:335059272",
            now=1000,
            topic_boundary_model_call=fake_model,
        )

        assert result.handled is True
        assert result.action == "topic_boundary_ambiguous"
        assert "不止一段话题" in result.reply or "点明" in result.reply
        assert store.load_long_term_entries(scope="private_user", scope_id="335059272") == []
        assert has_explicit_memory_pending("private:335059272", "335059272") is False


def test_handler_contextual_write_topic_boundary_invalid_output_falls_back_to_rules() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record_recent(store, "r1", "invalid fallback 应保留基础功能", created_at=100.0)
        _record_recent(store, "r2", "坏 JSON 时回退 A3.1 规则 resolver", created_at=101.0)

        result = handle_explicit_memory_message(
            _message("把刚才我们的讨论内容记一下", msg_id="cmd_invalid", timestamp=102.0),
            store,
            session_id="private:335059272",
            now=1000,
            topic_boundary_model_call=lambda _messages: "这不是 JSON",
        )

        assert result.handled is True
        assert result.action == "pending_context_confirmation"
        assert "近期讨论要点" in result.reply
        assert "invalid fallback 应保留基础功能" in result.reply
        assert "topic_boundary_resolver_v1_mockable" not in result.reply
        assert store.load_long_term_entries(scope="private_user", scope_id="335059272") == []
        assert has_explicit_memory_pending("private:335059272", "335059272") is True



def test_handler_contextual_write_topic_boundary_invalid_window_id_falls_back_to_rules() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record_recent(store, "r1", "窗口外 id invalid 输出时要回退规则版", created_at=100.0)
        _record_recent(store, "r2", "A3.1 fallback 仍能生成 pending payload", created_at=101.0)

        def fake_model(_messages: list[dict[str, str]]) -> str:
            return _topic_json_response(
                ok=True,
                status="resolved",
                payload="这个 payload 因 used_msg_ids 越界不该进入 pending",
                confidence=0.9,
                start_msg_id="r1",
                end_msg_id="r2",
                used_msg_ids=["r1", "missing_window_id"],
                reason="bad used id",
            )

        result = handle_explicit_memory_message(
            _message("把刚才我们的讨论内容记一下", msg_id="cmd_invalid_id", timestamp=102.0),
            store,
            session_id="private:335059272",
            now=1000,
            topic_boundary_model_call=fake_model,
        )

        assert result.handled is True
        assert result.action == "pending_context_confirmation"
        assert "近期讨论要点" in result.reply
        assert "窗口外 id invalid 输出时要回退规则版" in result.reply
        assert "这个 payload 因 used_msg_ids 越界不该进入 pending" not in result.reply
        assert store.load_long_term_entries(scope="private_user", scope_id="335059272") == []
        assert has_explicit_memory_pending("private:335059272", "335059272") is True


def test_handler_contextual_write_topic_boundary_model_error_falls_back_to_rules() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record_recent(store, "r1", "model_error fallback 不能让 handler 崩", created_at=100.0)
        _record_recent(store, "r2", "仍应 pending A3.1 规则 payload", created_at=101.0)

        def fake_model(_messages: list[dict[str, str]]) -> str:
            raise RuntimeError("fake timeout")

        result = handle_explicit_memory_message(
            _message("把刚才我们的讨论内容记一下", msg_id="cmd_error", timestamp=102.0),
            store,
            session_id="private:335059272",
            now=1000,
            topic_boundary_model_call=fake_model,
        )

        assert result.handled is True
        assert result.action == "pending_context_confirmation"
        assert "近期讨论要点" in result.reply
        assert "model_error fallback" in result.reply
        assert store.load_long_term_entries(scope="private_user", scope_id="335059272") == []
        assert has_explicit_memory_pending("private:335059272", "335059272") is True


def test_handler_topic_boundary_hook_not_used_for_direct_query_audit_or_confirm_without_pending() -> None:
    clear_explicit_memory_pending()

    def forbidden_model_call(_messages: list[dict[str, str]]) -> str:  # pragma: no cover - must not be called
        raise AssertionError("topic boundary hook should only run for contextual write")

    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        direct = handle_explicit_memory_message(
            _message("记一下：direct write 不受 topic hook 影响"),
            store,
            session_id="private:335059272",
            now=1000,
            topic_boundary_model_call=forbidden_model_call,
        )
        query = handle_explicit_memory_message(
            _message("你记得我昨天说了什么吗", msg_id="cmd_query_hook"),
            store,
            session_id="private:335059272",
            now=1001,
            topic_boundary_model_call=forbidden_model_call,
        )
        audit = handle_explicit_memory_message(
            _message("你在记录啥", msg_id="cmd_audit_hook"),
            store,
            session_id="private:335059272",
            now=1002,
            topic_boundary_model_call=forbidden_model_call,
        )
        confirm = handle_explicit_memory_message(
            _message("好", msg_id="cmd_confirm_no_pending_hook"),
            store,
            session_id="private:335059272",
            now=1003,
            topic_boundary_model_call=forbidden_model_call,
        )
        rows = store.load_long_term_entries(scope="private_user", scope_id="335059272")

        assert direct.handled is True
        assert direct.action == "direct_write"
        assert query.handled is False
        assert query.action == "pass_query"
        assert audit.handled is False
        assert audit.action == "pass_audit"
        assert confirm.handled is False
        assert confirm.action == "pass_confirm_or_cancel_without_pending"
        assert len(rows) == 1
        assert rows[0].value == "direct write 不受 topic hook 影响"


def test_handler_contextual_write_empty_recent_is_insufficient_without_pending_or_write() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        result = handle_explicit_memory_message(
            _message("刚才那个也记一下", msg_id="cmd_empty", timestamp=100.0),
            store,
            session_id="private:335059272",
            now=1000,
        )
        rows = store.load_long_term_entries(scope="private_user", scope_id="335059272")

        assert result.handled is True
        assert result.action == "context_insufficient"
        assert "没抓准" in result.reply or "说清楚" in result.reply
        assert rows == []
        assert has_explicit_memory_pending("private:335059272", "335059272") is False


def test_handler_medium_confidence_non_contextual_pending_regression() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        result = handle_explicit_memory_message(
            _message("以后迁移包流程要记一下"),
            store,
            session_id="private:335059272",
            now=1000,
        )
        rows = store.load_long_term_entries(scope="private_user", scope_id="335059272")

        assert result.handled is True
        assert result.action == "pending_confirmation"
        assert result.intent is not None
        assert result.intent.needs_context_resolution is False
        assert "是要记录为" in result.reply
        assert rows == []
        assert has_explicit_memory_pending("private:335059272", "335059272") is True


def test_handler_pending_confirm_writes_confirmed_and_clears_pending() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        first = handle_explicit_memory_message(
            _message("以后迁移包流程要记一下"),
            store,
            session_id="private:335059272",
            now=1000,
        )
        second = handle_explicit_memory_message(
            _message("确认"),
            store,
            session_id="private:335059272",
            now=1005,
        )
        rows = store.load_long_term_entries(scope="private_user", scope_id="335059272")

        assert first.action == "pending_confirmation"
        assert first.intent is not None
        assert first.intent.needs_context_resolution is False
        assert second.handled is True
        assert second.action == "confirmed_write"
        assert len(rows) == 1
        assert rows[0].source == "explicit_confirmed"
        assert rows[0].value == "以后迁移包流程要记一下"
        assert has_explicit_memory_pending("private:335059272", "335059272") is False


def test_handler_pending_cancel_does_not_write_and_clears_pending() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        handle_explicit_memory_message(
            _message("以后迁移包流程要记一下"),
            store,
            session_id="private:335059272",
            now=1000,
        )
        result = handle_explicit_memory_message(
            _message("取消"),
            store,
            session_id="private:335059272",
            now=1005,
        )
        rows = store.load_long_term_entries(scope="private_user", scope_id="335059272")

        assert result.handled is True
        assert result.action == "canceled"
        assert rows == []
        assert has_explicit_memory_pending("private:335059272", "335059272") is False


def test_handler_confirm_without_pending_passes_through() -> None:
    for word in ("确认", "好", "是"):
        clear_explicit_memory_pending()
        with tempfile.TemporaryDirectory() as tmpdir:
            store = _build_store(tmpdir)
            result = handle_explicit_memory_message(
                _message(word),
                store,
                session_id="private:335059272",
                now=1000,
            )
            assert result.handled is False
            assert result.action == "pass_confirm_or_cancel_without_pending"
            assert store.load_long_term_entries() == []
            assert has_explicit_memory_pending("private:335059272", "335059272") is False


def test_handler_query_and_audit_pass_through_without_write() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        query = handle_explicit_memory_message(
            _message("你记得我昨天说了什么吗"),
            store,
            session_id="private:335059272",
            now=1000,
        )
        audit = handle_explicit_memory_message(
            _message("你在记录啥"),
            store,
            session_id="private:335059272",
            now=1001,
        )
        rows = store.load_long_term_entries(scope="private_user", scope_id="335059272")

        assert query.handled is False
        assert query.action == "pass_query"
        assert audit.handled is False
        assert audit.action == "pass_audit"
        assert rows == []
        assert has_explicit_memory_pending("private:335059272", "335059272") is False


def test_handler_group_message_does_not_write_private_owner_memory() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        result = handle_explicit_memory_message(
            _message("记一下M2.1群聊边界测试", channel="group", is_owner=True),
            store,
            session_id="group:137918147",
            now=1000,
        )
        assert result.handled is False
        assert result.action == "pass_non_owner_or_non_private"
        assert store.load_long_term_entries(scope="private_user", scope_id="335059272") == []
        assert store.load_long_term_entries() == []
        assert has_explicit_memory_pending("group:137918147", "335059272") is False


def test_handler_non_owner_private_and_group_do_not_write() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        non_owner = handle_explicit_memory_message(
            _message("记一下：非 owner 不该写", uid="123456", is_owner=False),
            store,
            session_id="private:123456",
            now=1000,
        )
        group = handle_explicit_memory_message(
            _message("记一下：群聊不该写主脑", channel="group", is_owner=True),
            store,
            session_id="group:137918147",
            now=1000,
        )
        assert non_owner.handled is False
        assert group.handled is False
        assert store.load_long_term_entries() == []


def test_handler_pending_expired_confirm_is_handled_safely() -> None:
    clear_explicit_memory_pending()
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        handle_explicit_memory_message(
            _message("以后迁移包流程要记一下"),
            store,
            session_id="private:335059272",
            now=1000,
            ttl_seconds=10,
        )
        result = handle_explicit_memory_message(
            _message("确认"),
            store,
            session_id="private:335059272",
            now=1015,
            ttl_seconds=10,
        )
        assert result.handled is True
        assert result.action == "pending_expired"
        assert store.load_long_term_entries() == []
        assert has_explicit_memory_pending("private:335059272", "335059272") is False
