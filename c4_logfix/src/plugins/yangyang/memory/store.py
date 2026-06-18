from __future__ import annotations

import json
import hashlib
import sqlite3
import time
from pathlib import Path
from typing import Any, Callable, TypeVar

from nonebot.log import logger

from ..core.event_adapter import Message
from .core import MemorySystem
from .retrieval import MemoryRetriever
from .types import LongTermMemoryEntry, MemoryCandidate, PromotionAuditRecord, Scope




T = TypeVar("T")


class MemoryStore:
    """SQLite 消息存储。

    MVP 只做原始消息入库、用户档案与最近上下文读取。
    """

    def __init__(
        self,
        db_path: str,
        cache_dir: str,
        memory_root: str | Path | None = None,
        owner_id: str = "",
        retrieval_enabled: bool = False,
        retrieval_private_only: bool = True,
        retrieval_top_k: int = 3,
        retrieval_char_budget: int = 500,
    ):
        self.db_path = Path(db_path)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._cache: dict[str, Any] = {}
        self.memory_root = Path(memory_root).resolve() if memory_root else (self.cache_dir / "memories").resolve()
        self.memory_system = MemorySystem(self.memory_root)
        self._init_tables()

        # Phase C4: 长期记忆检索注入配置
        self.owner_id = str(owner_id or "")
        self.retrieval_enabled = bool(retrieval_enabled)
        self.retrieval_private_only = bool(retrieval_private_only)
        self.retrieval_top_k = max(1, int(retrieval_top_k))
        self.retrieval_char_budget = max(100, int(retrieval_char_budget))

    def configure_retrieval(
        self,
        enabled: bool | None = None,
        private_only: bool | None = None,
        top_k: int | None = None,
        char_budget: int | None = None,
    ) -> None:
        """运行时调整检索注入配置。"""
        if enabled is not None:
            self.retrieval_enabled = bool(enabled)
        if private_only is not None:
            self.retrieval_private_only = bool(private_only)
        if top_k is not None:
            self.retrieval_top_k = max(1, int(top_k))
        if char_budget is not None:
            self.retrieval_char_budget = max(100, int(char_budget))

    def configure_retrieval_from_env(
        self,
        cfg: dict[str, Any] | object,
        prefix: str = "memory_long_term_retrieval_",
    ) -> None:
        """从配置对象/字典批量读取检索注入配置。

        支持的 key（去掉 prefix 后的小写）：
          enabled, private_only, top_k, char_budget

        用法（NoneBot 侧）：
          store.configure_retrieval_from_env(cfg_obj)
          # 或
          store.configure_retrieval_from_env({"memory_long_term_retrieval_enabled": True})
        """
        if isinstance(cfg, dict):
            self.retrieval_enabled = bool(cfg.get(f"{prefix}enabled", self.retrieval_enabled))
            self.retrieval_private_only = bool(cfg.get(f"{prefix}private_only", self.retrieval_private_only))
            top_k = cfg.get(f"{prefix}top_k")
            if top_k is not None:
                self.retrieval_top_k = max(1, int(top_k))
            budget = cfg.get(f"{prefix}char_budget")
            if budget is not None:
                self.retrieval_char_budget = max(100, int(budget))
        elif hasattr(cfg, "__getattr__") or hasattr(cfg, "get_bool"):
            # NoneBot pydantic config 风格：cfg.get_bool("memory_long_term_retrieval_enabled")
            get_bool = getattr(cfg, "get_bool", None)
            get_int = getattr(cfg, "get_int", None)
            if get_bool:
                self.retrieval_enabled = get_bool(f"{prefix}enabled", self.retrieval_enabled)
                self.retrieval_private_only = get_bool(f"{prefix}private_only", self.retrieval_private_only)
            if get_int:
                top_k = get_int(f"{prefix}top_k", self.retrieval_top_k)
                self.retrieval_top_k = max(1, top_k)
                budget = get_int(f"{prefix}char_budget", self.retrieval_char_budget)
                self.retrieval_char_budget = max(100, budget)
        logger.info(
            "MemoryStore: configure_retrieval_from_env "
            "enabled=%s private_only=%s top_k=%s char_budget=%s",
            self.retrieval_enabled, self.retrieval_private_only,
            self.retrieval_top_k, self.retrieval_char_budget,
        )

    def configure_short_term_limit(self, limit: int) -> None:
        self.memory_system.short_term_limit = max(1, int(limit))

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _init_tables(self) -> None:
        try:
            with self._connect() as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS messages (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        msg_id TEXT,
                        uid TEXT NOT NULL,
                        nick TEXT,
                        group_id TEXT,
                        channel TEXT NOT NULL,
                        text TEXT,
                        raw_content TEXT,
                        is_bot INTEGER DEFAULT 0,
                        created_at REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS users (
                        uid TEXT PRIMARY KEY,
                        nick TEXT,
                        first_seen REAL NOT NULL,
                        last_seen REAL NOT NULL,
                        message_count INTEGER DEFAULT 0
                    )
                    """
                )
                conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_group_time ON messages(group_id, created_at)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_uid_time ON messages(uid, created_at)")
        except Exception:
            logger.exception("MemoryStore: failed to init tables: %s", self.db_path)

    def record_message(self, msg: Message, is_bot: bool = False, text_override: str | None = None) -> None:
        """记录一条消息并更新用户基础档案。敏感失败时丢弃原文，仅存事件摘要。"""
        try:
            now = time.time()
            text = msg.text if text_override is None else text_override
            raw_content = msg.raw_content
            if bool(getattr(msg, "sensitive_failure", False)) and not is_bot:
                raw = str(text or raw_content or "")
                raw_hash = hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()[:16]
                text = (
                    "[sensitive_failure_event "
                    f"raw_dropped=true request_id={getattr(msg, 'sensitive_failure_request_id', '')} "
                    f"error_type={getattr(msg, 'sensitive_failure_error_type', '')} "
                    f"hash={raw_hash} length={len(raw)}]"
                )
                raw_content = text
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO messages
                    (msg_id, uid, nick, group_id, channel, text, raw_content, is_bot, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        msg.msg_id,
                        msg.uid,
                        msg.nick,
                        msg.group_id,
                        msg.channel,
                        text,
                        raw_content,
                        1 if is_bot else 0,
                        now,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO users(uid, nick, first_seen, last_seen, message_count)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(uid) DO UPDATE SET
                        nick=excluded.nick,
                        last_seen=excluded.last_seen,
                        message_count=users.message_count + 1
                    """,
                    (msg.uid, msg.nick, now, now),
                )
        except Exception:
            logger.exception("MemoryStore: failed to record message")

    def record_bot_message(
        self,
        channel: str,
        group_id: str,
        bot_uid: str,
        bot_nick: str,
        text: str,
    ) -> None:
        """记录 bot 自己发出的消息。"""
        msg = Message(
            msg_id="",
            uid=str(bot_uid),
            nick=str(bot_nick),
            group_id=str(group_id or ""),
            channel=channel,
            text=text,
            raw_content=text,
            is_at_bot=False,
            is_at_owner=False,
            is_quote_bot=False,
            quote_target_msg_id=None,
            reply_to_message_id=None,
            reply_to_user_id=None,
            is_reply_to_bot=False,
            is_owner=False,
            owner_command=False,
            explicit_command=False,
            images=[],
            timestamp=time.time(),
        )
        self.record_message(msg, is_bot=True)

    def get_or_create_user(self, uid: str, nick: str) -> dict[str, Any]:
        """获取或创建用户基础档案。"""
        try:
            now = time.time()
            with self._connect() as conn:
                conn.execute(
                    """
                    INSERT INTO users(uid, nick, first_seen, last_seen, message_count)
                    VALUES (?, ?, ?, ?, 0)
                    ON CONFLICT(uid) DO NOTHING
                    """,
                    (str(uid), str(nick), now, now),
                )
                row = conn.execute("SELECT * FROM users WHERE uid=?", (str(uid),)).fetchone()
                return dict(row) if row else {"uid": str(uid), "nick": str(nick)}
        except Exception:
            logger.exception("MemoryStore: failed to get_or_create_user: %s", uid)
            return {"uid": str(uid), "nick": str(nick)}

    def get_recent_messages(self, group_id: str, limit: int = 12, channel: str | None = "group") -> list[dict[str, Any]]:
        """读取最近消息，按时间正序返回。默认读取群聊上下文。"""
        try:
            query = (
                """
                SELECT uid, nick, group_id, channel, text, is_bot, created_at
                FROM messages
                WHERE group_id=?
                ORDER BY created_at DESC
                LIMIT ?
                """
            )
            params: tuple[Any, ...] = (str(group_id or ""), int(limit))

            if channel is None:
                query = (
                    """
                    SELECT uid, nick, group_id, channel, text, is_bot, created_at
                    FROM messages
                    WHERE group_id=?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """
                )
            elif channel == "private":
                query = (
                    """
                    SELECT uid, nick, group_id, channel, text, is_bot, created_at
                    FROM messages
                    WHERE channel='private'
                    ORDER BY created_at DESC
                    LIMIT ?
                    """
                )
                params = (int(limit),)
            else:
                query = (
                    """
                    SELECT uid, nick, group_id, channel, text, is_bot, created_at
                    FROM messages
                    WHERE group_id=? AND channel=?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """
                )
                params = (str(group_id or ""), str(channel), int(limit))

            with self._connect() as conn:
                rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in reversed(rows)]
        except Exception:
            logger.exception("MemoryStore: failed to get recent messages")
            return []

    def get_last_bot_message(self, group_id: str) -> dict[str, Any] | None:
        """读取指定群最近一条 bot 消息。"""
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT uid, nick, group_id, channel, text, is_bot, created_at
                    FROM messages
                    WHERE group_id=? AND is_bot=1
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (str(group_id or ""),),
                ).fetchone()
            return dict(row) if row else None
        except Exception:
            logger.exception("MemoryStore: failed to get last bot message")
            return None

    def get_message_by_msg_id(self, msg_id: str) -> dict[str, Any] | None:
        """按消息 ID 读取单条消息，供 OwnerAction Context Resolver 等观察位使用。"""
        try:
            normalized_msg_id = str(msg_id or "").strip()
            if not normalized_msg_id:
                return None
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT msg_id, uid, nick, group_id, channel, text, raw_content, is_bot, created_at
                    FROM messages
                    WHERE msg_id=?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (normalized_msg_id,),
                ).fetchone()
            if not row:
                return None
            item = dict(row)
            item["message_id"] = item.get("msg_id")
            item["timestamp"] = item.get("created_at")
            item["user_id"] = item.get("uid")
            item["content"] = item.get("text") or item.get("raw_content") or ""
            return item
        except Exception:
            logger.exception("MemoryStore: failed to get message by msg_id: %s", msg_id)
            return None

    def _memory_logs_dir(self) -> Path:
        path = self.memory_system.base_dir / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _candidates_path(self, date: str) -> Path:
        self.memory_system.daily_dir.mkdir(parents=True, exist_ok=True)
        return self.memory_system.daily_dir / f"candidates_{str(date)}.jsonl"

    def _long_term_entries_path(self) -> Path:
        self.memory_system.long_term_dir.mkdir(parents=True, exist_ok=True)
        return self.memory_system.long_term_dir / "memories.jsonl"

    def _promotion_audit_path(self) -> Path:
        return self._memory_logs_dir() / "memory_promotion_audit.jsonl"

    def _append_jsonl_row(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _load_jsonl_rows(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                rows.append(dict(json.loads(line)))
        return rows

    def _filter_scope_rows(
        self,
        rows: list[T],
        *,
        scope: Scope | None = None,
        scope_id: str | None = None,
    ) -> list[T]:
        filtered = list(rows)
        if scope is not None:
            filtered = [row for row in filtered if getattr(row, "scope", None) == scope]
        if scope_id is not None:
            normalized_scope_id = str(scope_id)
            filtered = [row for row in filtered if str(getattr(row, "scope_id", "")) == normalized_scope_id]
        return filtered

    def _load_typed_jsonl(
        self,
        path: Path,
        factory: Callable[[dict[str, Any]], T],
        *,
        scope: Scope | None = None,
        scope_id: str | None = None,
    ) -> list[T]:
        rows = [factory(item) for item in self._load_jsonl_rows(path)]
        return self._filter_scope_rows(rows, scope=scope, scope_id=scope_id)

    def append_candidate(self, candidate: MemoryCandidate) -> Path:
        path = self._candidates_path(candidate.date)
        self._append_jsonl_row(path, candidate.to_dict())
        return path

    def load_candidates(
        self,
        date: str,
        *,
        scope: Scope | None = None,
        scope_id: str | None = None,
    ) -> list[MemoryCandidate]:
        return self._load_typed_jsonl(
            self._candidates_path(date),
            MemoryCandidate.from_dict,
            scope=scope,
            scope_id=scope_id,
        )

    def append_long_term_entry(self, entry: LongTermMemoryEntry) -> Path:
        path = self._long_term_entries_path()
        self._append_jsonl_row(path, entry.to_dict())
        return path

    def load_long_term_entries(
        self,
        *,
        scope: Scope | None = None,
        scope_id: str | None = None,
    ) -> list[LongTermMemoryEntry]:
        return self._load_typed_jsonl(
            self._long_term_entries_path(),
            LongTermMemoryEntry.from_dict,
            scope=scope,
            scope_id=scope_id,
        )

    def append_promotion_audit(self, record: PromotionAuditRecord) -> Path:
        path = self._promotion_audit_path()
        self._append_jsonl_row(path, record.to_dict())
        return path

    def load_promotion_audit(
        self,
        *,
        scope: Scope | None = None,
        scope_id: str | None = None,
    ) -> list[PromotionAuditRecord]:
        return self._load_typed_jsonl(
            self._promotion_audit_path(),
            PromotionAuditRecord.from_dict,
            scope=scope,
            scope_id=scope_id,
        )

    def add_entry(self, uid: str, entry: dict[str, Any]) -> None:
        """第二阶段记忆接口占位。"""
        logger.debug("MemoryStore.add_entry placeholder uid=%s entry=%s", uid, entry)

    def retrieve_context(self, uid: str, query: str, top_k: int = 5) -> list[str]:
        """第二阶段检索接口占位。"""
        return []

    def update_profile(self, uid: str, delta: dict[str, Any]) -> None:
        """第二阶段用户档案更新占位。"""
        logger.debug("MemoryStore.update_profile placeholder uid=%s delta=%s", uid, delta)

    def add_to_short_term(self, session_id: str, message: dict[str, Any] | str) -> None:
        self.memory_system.add_to_short_term(session_id, message)

    def get_short_term_context(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.memory_system.get_short_term_context(session_id, limit=limit)

    def save_user_profile(self, user_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        return self.memory_system.save_user_profile(user_id, profile)

    def get_user_profile(self, user_id: str) -> dict[str, Any] | None:
        return self.memory_system.get_user_profile(user_id)

    def update_impression(self, user_id: str, key: str, value: Any) -> dict[str, Any]:
        return self.memory_system.update_impression(user_id, key, value)

    def build_memory_prompt(self, user_id: str, session_id: str, short_term_limit: int = 8, char_budget: int | None = None) -> str:
        base_prompt = self.memory_system.build_memory_prompt(user_id, session_id, short_term_limit=short_term_limit, char_budget=char_budget)

        # Phase C4: 长期记忆检索注入
        if not self.retrieval_enabled:
            logger.info("MemoryStore[C4]: skipped — retrieval_enabled=False")
            return base_prompt

        channel = session_id.split(":")[0] if ":" in session_id else ""
        group_id = session_id.split(":")[1] if channel == "group" else ""
        logger.info("MemoryStore[C4]: user_id=%s session_id=%s channel=%s group_id=%s", user_id, session_id, channel, group_id)

        # 群聊永不注入长期记忆
        if channel == "group":
            logger.info("MemoryStore[C4]: skipped — group chat never injects")
            return base_prompt

        # 私聊：仅 owner 灰度
        if self.retrieval_private_only and user_id != self.owner_id:
            logger.info("MemoryStore[C4]: skipped — private_only=True user_id=%s != owner_id=%s", user_id, self.owner_id)
            return base_prompt

        try:
            entries = self.load_long_term_entries()
            logger.info("MemoryStore[C4]: loaded %d long-term entries", len(entries))
            if not entries:
                return base_prompt

            retriever = MemoryRetriever()
            top_k = self.retrieval_top_k
            budget = self.retrieval_char_budget

            retrieved = retriever.retrieve(
                entries,
                query="",
                user_id=user_id,
                group_id=group_id,
                top_k=top_k,
            )
            logger.info("MemoryStore[C4]: retrieved %d/%d entries after scoring", len(retrieved), len(entries))

            rendered = retriever.render_prompt_section(retrieved, char_budget=budget)
            logger.info("MemoryStore[C4]: rendered section (%d chars): %s", len(rendered), rendered[:120] if rendered else "(empty)")
            if rendered:
                return rendered + "\n\n" + base_prompt
        except Exception:
            logger.exception("MemoryStore: long-term memory retrieval failed, falling back to base prompt")

        return base_prompt
