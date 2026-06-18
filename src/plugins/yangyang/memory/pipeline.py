from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

from nonebot.log import logger

from .candidate_extractor import CandidateExtractor
from .promotion import PromotionEngine
from .store import MemoryStore
from .types import Evidence, MemoryCandidate


class MemoryPipeline:
    """短期记忆 → 候选提取 → 升格 → 长期记忆 自动闭环。

    由外部调度器（apscheduler / cron）周期性调用 run_once()。
    """

    def __init__(self, store: MemoryStore):
        self.store = store
        self.extractor = CandidateExtractor()
        self.engine = PromotionEngine()

        # 每次处理时，只扫最近 N 条短期记忆的会话
        self.max_sessions = 10
        self.max_messages_per_session = 50
        self.max_diagnostic_sessions = 3
        self.preview_limit = 30
        self._last_collection_meta: dict[str, dict[str, Any]] = {}
        self.processed_ids_path = self.store.memory_root / "processed_short_term_ids.json"
        self.processed_ids_limit = 5000

    def run_once(self) -> dict[str, Any]:
        """执行一轮完整管线，返回统计信息。"""
        stats: dict[str, Any] = {
            "sessions_scanned": 0,
            "messages_collected": 0,
            "new_candidates": 0,
            "candidates_after_dedup": 0,
            "promoted": 0,
            "errors": 0,
            "skipped_bot_self": 0,
            "skipped_processed": 0,
            "detail": [],
            "diagnostics": [],
            "long_term_path": str(self.store.long_term_entries_path),
            "memory_root": str(self.store.memory_root),
        }

        processed_ids = self._load_processed_ids()
        messages_by_session = self._collect_from_short_term(processed_ids)
        collection_meta = dict(self._last_collection_meta)
        stats["sessions_scanned"] = len(messages_by_session)
        stats["skipped_bot_self"] = sum(int(meta.get("skipped_bot_self", 0)) for meta in collection_meta.values())
        stats["skipped_processed"] = sum(int(meta.get("skipped_processed", 0)) for meta in collection_meta.values())

        logger.info(
            f"MemoryPipeline: run_once start — memory_root={self.store.memory_root} "
            f"long_term_path={self.store.long_term_entries_path} candidate_dir={self.store.memory_system.daily_dir} "
            f"cache_sessions={len(getattr(self.store.memory_system, 'short_term_cache', {}) or {})} "
            f"collected_sessions={stats['sessions_scanned']} skipped_bot_self={stats['skipped_bot_self']} "
            f"skipped_processed={stats['skipped_processed']}"
        )

        for session_id, messages in messages_by_session.items():
            meta = collection_meta.get(session_id, {})
            try:
                stats["messages_collected"] += len(messages)

                extracted = self.extractor.extract_from_messages(messages)
                raw_candidates = len(extracted)
                stats["new_candidates"] += raw_candidates

                if raw_candidates == 0:
                    diagnostic = {
                        "session_id": session_id,
                        "message_count": len(messages),
                        "skipped_bot_self": int(meta.get("skipped_bot_self", 0)),
                        "recent": [self._message_summary(message) for message in messages[-2:]],
                    }
                    stats["diagnostics"].append({"stage": "c1_zero_raw", **diagnostic})
                    logger.info(
                        f"MemoryPipeline: C1 raw_candidates=0 — session_id={session_id} msgs={len(messages)} "
                        f"skipped_bot_self={diagnostic['skipped_bot_self']} recent={diagnostic['recent']}"
                    )
                    stats["detail"].append({
                        "session": session_id,
                        "message_count": len(messages),
                        "raw_candidates": 0,
                        "aggregated_candidates": 0,
                        "promoted": 0,
                    })
                    self._mark_processed_messages(messages, processed_ids)
                    continue

                candidates = self._aggregate_candidates(extracted)
                aggregated_count = len(candidates)

                today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
                existing_candidates = self.store.load_candidates(today)
                existing_ids = {c.candidate_id for c in existing_candidates}
                fresh = [c for c in candidates if c.candidate_id not in existing_ids]
                fresh_count = len(fresh)
                stats["candidates_after_dedup"] += fresh_count

                if not fresh:
                    logger.info(
                        f"MemoryPipeline: C1/C2 dedup produced no fresh candidates — session_id={session_id} "
                        f"raw_candidates={raw_candidates} aggregated_candidates={aggregated_count} "
                        "reason=all_candidate_ids_already_seen"
                    )
                    stats["detail"].append({
                        "session": session_id,
                        "message_count": len(messages),
                        "raw_candidates": raw_candidates,
                        "aggregated_candidates": 0,
                        "promoted": 0,
                        "reason": "all_candidate_ids_already_seen",
                    })
                    self._mark_processed_messages(messages, processed_ids)
                    continue

                for c in fresh:
                    self.store.append_candidate(c)

                existing_entries = self.store.load_long_term_entries()
                updated, audit = self.engine.promote_candidates(fresh, existing_entries)

                for entry in updated:
                    self.store.upsert_long_term_entry(entry)
                for record in audit:
                    self.store.append_promotion_audit(record)

                promoted = sum(1 for a in audit if a.decision == "promoted")
                stats["promoted"] += promoted
                self._mark_processed_messages(messages, processed_ids)
                rejected_reasons = [str(a.reason or "") for a in audit if a.decision != "promoted"]

                if aggregated_count > 0 and promoted == 0:
                    logger.info(
                        f"MemoryPipeline: C2 promoted=0 — session_id={session_id} raw_candidates={raw_candidates} "
                        f"aggregated_candidates={aggregated_count} reasons={rejected_reasons[:3]}"
                    )

                stats["detail"].append({
                    "session": session_id,
                    "message_count": len(messages),
                    "raw_candidates": raw_candidates,
                    "aggregated_candidates": fresh_count,
                    "promoted": promoted,
                    "reasons": rejected_reasons[:3],
                })

            except Exception:
                logger.exception(f"MemoryPipeline: session {session_id} failed")
                stats["errors"] += 1

        logger.info(
            f"MemoryPipeline: run_once done — sessions={stats['sessions_scanned']} msgs={stats['messages_collected']} "
            f"raw_candidates={stats['new_candidates']} aggregated_candidates={stats['candidates_after_dedup']} "
            f"promoted={stats['promoted']} errors={stats['errors']} skipped_processed={stats['skipped_processed']} "
            f"long_term_path={stats['long_term_path']}"
        )
        return stats

    def _collect_from_short_term(self, processed_ids: set[str] | None = None) -> dict[str, list[dict[str, Any]]]:
        """从 MemorySystem 的短期缓存按 session 收集消息。"""
        cache = getattr(self.store.memory_system, "short_term_cache", None)
        self._last_collection_meta = {}
        if not cache:
            return {}

        processed_ids = processed_ids or set()
        result: dict[str, list[dict[str, Any]]] = {}
        ranked_sessions = sorted(
            cache.items(),
            key=lambda item: self._session_last_timestamp(item[1]),
            reverse=True,
        )[: self.max_sessions]

        for session_id, bucket in ranked_sessions:
            items = list(bucket or [])[-self.max_messages_per_session :]
            if not items:
                continue

            messages: list[dict[str, Any]] = []
            skipped_bot_self = 0
            skipped_processed = 0
            for item in items:
                msg = self._normalize_short_term_item(item)
                if msg is None:
                    if self._looks_like_bot_or_self(self._unwrap_short_term_item(item)):
                        skipped_bot_self += 1
                    continue
                if msg.get("processed_id") in processed_ids:
                    skipped_processed += 1
                    continue
                messages.append(msg)
            session_key = str(session_id)
            if messages:
                result[session_key] = messages
            if messages or skipped_bot_self or skipped_processed:
                self._last_collection_meta[session_key] = {
                    "bucket_size": len(items),
                    "message_count": len(messages),
                    "skipped_bot_self": skipped_bot_self,
                    "skipped_processed": skipped_processed,
                }

        return result

    def _normalize_short_term_item(self, item: dict[str, Any]) -> dict[str, Any] | None:
        """将短期缓存条目归一化为 extractor 可读的 dict。"""
        payload = self._unwrap_short_term_item(item)
        if self._looks_like_bot_or_self(payload):
            return None

        text = self._extract_text(payload)
        if not text.strip():
            return None

        channel = str(payload.get("channel") or payload.get("chat_type") or "")
        group_id = str(payload.get("group_id") or payload.get("group") or payload.get("guild_id") or "")
        uid = str(payload.get("uid") or payload.get("user_id") or payload.get("sender_id") or payload.get("from_user_id") or "")
        session_id = str(payload.get("session_id") or self._build_session_id(channel, group_id, uid))

        message_id = str(payload.get("message_id") or payload.get("msg_id") or payload.get("request_id") or "")
        timestamp = self._normalize_timestamp_value(payload.get("timestamp") or payload.get("created_at") or payload.get("time"))
        if not message_id:
            message_id = self._fallback_message_id(session_id, timestamp, text)
        processed_id = self._build_processed_id(session_id, message_id, timestamp, text)

        return {
            "text": text,
            "content": text,
            "uid": uid,
            "user_id": uid,
            "role": str(payload.get("role") or payload.get("sender_role") or "user"),
            "channel": channel,
            "group_id": group_id,
            "message_id": message_id,
            "timestamp": timestamp,
            "processed_id": processed_id,
            "nick": str(payload.get("nick") or payload.get("nickname") or payload.get("sender_name") or ""),
            "session_id": session_id,
            "source": str(payload.get("source") or payload.get("sender") or payload.get("type") or ""),
        }


    def _fallback_message_id(self, session_id: str, timestamp: str, text: str) -> str:
        digest = hashlib.sha256(f"{session_id}|{timestamp}|{text}".encode("utf-8", errors="ignore")).hexdigest()[:16]
        return f"fallback_{digest}"

    def _build_processed_id(self, session_id: str, message_id: str, timestamp: str, text: str) -> str:
        stable = message_id or self._fallback_message_id(session_id, timestamp, text)
        digest = hashlib.sha256(f"{session_id}|{stable}".encode("utf-8", errors="ignore")).hexdigest()[:24]
        return f"pst_{digest}"

    def _load_processed_ids(self) -> set[str]:
        path = Path(self.processed_ids_path)
        if not path.exists():
            return set()
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                items = payload.get("processed_ids", [])
            else:
                items = payload
            return {str(item) for item in items if str(item or "")}
        except Exception:
            logger.exception(f"MemoryPipeline: failed to load processed ids path={path}")
            return set()

    def _save_processed_ids(self, processed_ids: set[str]) -> None:
        path = Path(self.processed_ids_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        ordered = sorted(processed_ids)[-self.processed_ids_limit :]
        payload = {"version": 1, "processed_ids": ordered}
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(path)

    def _mark_processed_messages(self, messages: list[dict[str, Any]], processed_ids: set[str]) -> None:
        before = len(processed_ids)
        for message in messages:
            processed_id = str(message.get("processed_id") or "")
            if processed_id:
                processed_ids.add(processed_id)
        if len(processed_ids) != before:
            self._save_processed_ids(processed_ids)

    def _unwrap_short_term_item(self, item: Any) -> dict[str, Any]:
        payload = dict(item or {}) if isinstance(item, dict) else {}
        nested = payload.get("message")
        if isinstance(nested, dict):
            merged = dict(nested)
            for key, value in payload.items():
                merged.setdefault(key, value)
            payload = merged
        return payload

    def _extract_text(self, item: dict[str, Any]) -> str:
        candidates = (
            item.get("text"),
            item.get("content"),
            item.get("raw_content"),
            item.get("raw_message"),
            item.get("plain_text"),
        )
        for value in candidates:
            if isinstance(value, str) and value.strip():
                return str(value)
        nested = item.get("message")
        if isinstance(nested, dict):
            for key in ("text", "content", "raw_content", "plain_text"):
                value = nested.get(key)
                if isinstance(value, str) and value.strip():
                    return str(value)
        return ""

    def _looks_like_bot_or_self(self, item: dict[str, Any]) -> bool:
        role = str(item.get("role") or item.get("sender_role") or "").lower()
        source = str(item.get("source") or item.get("sender") or item.get("type") or "").lower()
        if role in {"assistant", "bot", "self"}:
            return True
        if source in {"assistant", "bot", "self", "outgoing", "reply"}:
            return True
        if bool(item.get("is_bot")) or bool(item.get("is_self")):
            return True
        return False

    def _message_summary(self, message: dict[str, Any]) -> dict[str, str]:
        return {
            "role": str(message.get("role") or "user"),
            "source": str(message.get("source") or ""),
            "content_preview": self._preview_text(str(message.get("text") or message.get("content") or "")),
        }

    def _preview_text(self, text: str) -> str:
        normalized = " ".join(str(text or "").split())
        if len(normalized) <= self.preview_limit:
            return normalized
        return normalized[: self.preview_limit - 1] + "…"

    def _aggregate_candidates(self, candidates: list[MemoryCandidate]) -> list[MemoryCandidate]:
        """合并同 scope/kind/slot/value 的重复候选，让重复表达形成 support_count。"""
        merged: dict[tuple[str, str, str, str, str], MemoryCandidate] = {}
        order: list[tuple[str, str, str, str, str]] = []

        for candidate in candidates:
            key = (candidate.scope, candidate.scope_id, candidate.kind, candidate.slot, candidate.value)
            existing = merged.get(key)
            if existing is None:
                merged[key] = candidate
                order.append(key)
                continue

            total_support = max(0, int(existing.support_count)) + max(0, int(candidate.support_count))
            weighted_confidence = 0.0
            if total_support > 0:
                weighted_confidence = (
                    existing.confidence * max(0, int(existing.support_count))
                    + candidate.confidence * max(0, int(candidate.support_count))
                ) / total_support
            existing.support_count = total_support
            existing.confidence = round(weighted_confidence, 4)
            existing.contradiction_count += candidate.contradiction_count
            existing.evidence = self._merge_evidence(existing.evidence, candidate.evidence)
            if candidate.created_at:
                existing.created_at = candidate.created_at
            if candidate.summary:
                existing.summary = candidate.summary

        return [merged[key] for key in order]

    def _merge_evidence(self, left: list[Evidence], right: list[Evidence]) -> list[Evidence]:
        result = list(left)
        seen = {(item.message_id, item.timestamp, item.text) for item in result}
        for item in right:
            marker = (item.message_id, item.timestamp, item.text)
            if marker in seen:
                continue
            result.append(item)
            seen.add(marker)
        return result

    def _session_last_timestamp(self, items: list[dict[str, Any]]) -> float:
        timestamps = [self._coerce_timestamp(item.get("timestamp") or item.get("created_at")) for item in list(items or [])]
        return max(timestamps, default=0.0)

    def _normalize_timestamp_value(self, value: Any) -> str:
        if value in (None, ""):
            return ""
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc).astimezone().isoformat(timespec="seconds")
        text = str(value).strip()
        if not text:
            return ""
        try:
            return datetime.fromtimestamp(float(text), tz=timezone.utc).astimezone().isoformat(timespec="seconds")
        except ValueError:
            return text

    def _coerce_timestamp(self, value: Any) -> float:
        if value in (None, ""):
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            pass
        try:
            return datetime.fromisoformat(text).timestamp()
        except ValueError:
            return 0.0

    def _build_session_id(self, channel: str, group_id: str, user_id: str) -> str:
        if channel == "private" or not group_id:
            return f"private:{user_id}" if user_id else "private:"
        return f"group:{group_id}"
