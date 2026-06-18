from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from mock_pipeline_runtime import prepare_modules  # type: ignore


mods = prepare_modules()
MemoryStore = mods["MemoryStore"]

from plugins.yangyang.core.event_adapter import Message


REQUIRED_RECENT_RECORD_FIELDS = {
    "msg_id",
    "uid",
    "nick",
    "group_id",
    "channel",
    "text",
    "raw_content",
    "is_bot",
    "created_at",
}


def _build_store(tmpdir: str):
    return MemoryStore(str(Path(tmpdir) / "chat.db"), str(Path(tmpdir) / "cache"))


def _message(
    msg_id: str,
    text: str,
    *,
    uid: str = "335059272",
    nick: str | None = None,
    channel: str = "private",
    group_id: str = "",
    raw_content: str | None = None,
) -> Message:
    return Message(
        msg_id=msg_id,
        uid=uid,
        nick=nick or ("秧秧" if uid == "yangyang_bot" else "阿漂"),
        group_id=group_id if channel == "group" else "",
        channel=channel,
        text=text,
        raw_content=raw_content if raw_content is not None else text,
        is_at_bot=False,
        is_at_owner=False,
        is_quote_bot=False,
        quote_target_msg_id=None,
        reply_to_message_id=None,
        reply_to_user_id=None,
        is_reply_to_bot=False,
        is_owner=uid == "335059272",
        owner_command=False,
        explicit_command=False,
        images=[],
        timestamp=0.0,
    )


def _record(
    store: Any,
    msg_id: str,
    text: str,
    *,
    created_at: float,
    uid: str = "335059272",
    nick: str | None = None,
    channel: str = "private",
    group_id: str = "",
    raw_content: str | None = None,
    is_bot: bool = False,
) -> None:
    store.record_message(
        _message(
            msg_id,
            text,
            uid=uid,
            nick=nick,
            channel=channel,
            group_id=group_id,
            raw_content=raw_content,
        ),
        is_bot=is_bot,
    )
    with store._connect() as conn:
        conn.execute(
            "UPDATE messages SET created_at=? WHERE msg_id=? AND uid=?",
            (float(created_at), msg_id, uid),
        )


def test_private_owner_recent_records_are_chronological_and_complete() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record(store, "p_001", "第一句", created_at=100.0, raw_content="raw:第一句")
        _record(
            store,
            "bot_001",
            "收到",
            created_at=110.0,
            uid="yangyang_bot",
            nick="秧秧",
            raw_content="raw:收到",
            is_bot=True,
        )
        _record(store, "p_002", "第二句", created_at=120.0, raw_content="raw:第二句")

        rows = store.get_recent_message_records(channel="private", uid="335059272", limit=10)

        assert [row["msg_id"] for row in rows] == ["p_001", "bot_001", "p_002"]
        assert [row["created_at"] for row in rows] == sorted(row["created_at"] for row in rows)
        assert [row["is_bot"] for row in rows] == [0, 1, 0]
        assert rows[0]["raw_content"] == "raw:第一句"
        assert rows[1]["uid"] == "yangyang_bot"
        assert all(REQUIRED_RECENT_RECORD_FIELDS <= set(row.keys()) for row in rows)

        session_rows = store.get_recent_message_records(channel="private", session_id="private:335059272", limit=10)
        assert [row["msg_id"] for row in session_rows] == ["p_001", "bot_001", "p_002"]


def test_recent_record_limit_applies_before_chronological_return() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record(store, "p_001", "一", created_at=100.0)
        _record(store, "p_002", "二", created_at=110.0)
        _record(store, "p_003", "三", created_at=120.0)
        _record(store, "p_004", "四", created_at=130.0)

        rows = store.get_recent_message_records(channel="private", uid="335059272", limit=2)

        assert [row["msg_id"] for row in rows] == ["p_003", "p_004"]
        assert [row["created_at"] for row in rows] == [120.0, 130.0]


def test_recent_records_can_exclude_current_command_message() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record(store, "ctx_001", "上文一", created_at=100.0)
        _record(store, "ctx_002", "上文二", created_at=110.0)
        _record(store, "cmd_001", "记一下刚才那个", created_at=120.0)

        rows = store.get_recent_message_records(
            channel="private",
            uid="335059272",
            limit=3,
            exclude_msg_id="cmd_001",
        )
        before_rows = store.get_recent_message_records(
            channel="private",
            uid="335059272",
            limit=3,
            before_ts=120.0,
        )

        assert [row["msg_id"] for row in rows] == ["ctx_001", "ctx_002"]
        assert [row["msg_id"] for row in before_rows] == ["ctx_001", "ctx_002"]
        assert all(row["msg_id"] != "cmd_001" for row in rows)


def test_group_recent_records_are_scoped_to_group_id() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record(store, "g1_001", "群一第一句", created_at=100.0, channel="group", group_id="137918147")
        _record(store, "g2_001", "群二第一句", created_at=110.0, channel="group", group_id="999000")
        _record(store, "g1_002", "群一第二句", created_at=120.0, channel="group", group_id="137918147")

        rows = store.get_recent_message_records(channel="group", group_id="137918147", limit=10)
        session_rows = store.get_recent_message_records(channel="group", session_id="group:137918147", limit=10)

        assert [row["msg_id"] for row in rows] == ["g1_001", "g1_002"]
        assert [row["msg_id"] for row in session_rows] == ["g1_001", "g1_002"]
        assert {row["group_id"] for row in rows} == {"137918147"}
        assert all(row["channel"] == "group" for row in rows)


def test_private_recent_records_do_not_include_group_messages() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)
        _record(store, "p_001", "私聊", created_at=100.0, channel="private")
        _record(store, "g_001", "群聊", created_at=110.0, channel="group", group_id="137918147")

        rows = store.get_recent_message_records(channel="private", uid="335059272", limit=10)

        assert [row["msg_id"] for row in rows] == ["p_001"]
        assert all(row["channel"] == "private" for row in rows)
        assert all(row["group_id"] == "" for row in rows)


def test_recent_records_empty_store_returns_empty_list() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        store = _build_store(tmpdir)

        assert store.get_recent_message_records(channel="private", uid="335059272", limit=10) == []
        assert store.get_recent_message_records(channel="group", group_id="137918147", limit=10) == []
