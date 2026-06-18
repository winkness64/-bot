from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .types import (
    LongTermMemoryEntry,
    MemoryCandidate,
    PromotionAuditRecord,
    PromotionDecision,
    PromotionEvent,
)


class PromotionEngine:
    """候选记忆升格引擎。

    将 MemoryCandidate 按规则升格为 LongTermMemoryEntry。
    只做规则判断，不接 LLM，不改生产链路。
    """

    MIN_SUPPORT_FOR_PROMOTION = 2

    def promote_candidates(
        self,
        candidates: list[MemoryCandidate],
        existing: list[LongTermMemoryEntry],
    ) -> tuple[list[LongTermMemoryEntry], list[PromotionAuditRecord]]:
        """批量 promotion，返回（新增/更新条目，审计记录）。"""
        updated_entries: list[LongTermMemoryEntry] = []
        audit_events: list[PromotionAuditRecord] = []

        for candidate in candidates:
            should_promote, reason = self.should_promote(candidate, existing)

            if should_promote:
                entry = self.merge_or_create(candidate, existing)
                entry.source = "rule_promotion"
                updated_entries.append(entry)
                decision: PromotionDecision = "promoted"
                event: PromotionEvent = "promote"
                memory_id = entry.id
            else:
                decision = "rejected"
                event = "reject"
                memory_id = ""

            audit_events.append(
                PromotionAuditRecord(
                    event_id=f"audit_{uuid.uuid4().hex[:12]}",
                    event=event,
                    candidate_id=candidate.candidate_id,
                    memory_id=memory_id,
                    decision=decision,
                    reason=reason,
                    scope=candidate.scope,
                    scope_id=candidate.scope_id,
                    operator="rule_engine",
                    created_at=self._now_iso(),
                )
            )

        return updated_entries, audit_events

    def should_promote(
        self,
        candidate: MemoryCandidate,
        existing: list[LongTermMemoryEntry],
    ) -> tuple[bool, str]:
        """判断候选是否可升格。

        返回 (是否升格, 原因)。
        """
        # 已有同 kind+slot 的活跃条目 → 更新
        matched = self._find_matched(candidate, existing)
        if matched:
            return True, "matched_existing_entry"

        # 矛盾计数超过支持 → rejected
        if candidate.contradiction_count > candidate.support_count:
            return False, "contradiction_count > support_count"

        # support_count 足够 → promote
        if candidate.support_count >= self.MIN_SUPPORT_FOR_PROMOTION:
            return True, "support_count>=2"

        return False, "support_count insufficient"

    def merge_or_create(
        self,
        candidate: MemoryCandidate,
        existing: list[LongTermMemoryEntry],
    ) -> LongTermMemoryEntry:
        """同 slot/scope 下合并，否则创建新条目。"""
        matched = self._find_matched(candidate, existing)
        if matched:
            return self._merge(candidate, matched)

        now = self._now_iso()
        return LongTermMemoryEntry(
            id=f"mem_{uuid.uuid4().hex[:12]}",
            status="active",
            scope=candidate.scope,
            scope_id=candidate.scope_id,
            session_id=candidate.session_id,
            user_id=candidate.user_id,
            group_id=candidate.group_id,
            channel=candidate.channel,
            kind=candidate.kind,
            slot=candidate.slot,
            value=candidate.value,
            summary=candidate.summary,
            evidence=candidate.evidence,
            confidence=candidate.confidence,
            support_count=candidate.support_count,
            contradiction_count=candidate.contradiction_count,
            source="rule_promotion",
            tags=self._infer_tags(candidate),
            created_at=now,
            updated_at=now,
            last_seen_at=now,
        )

    def _find_matched(
        self,
        candidate: MemoryCandidate,
        existing: list[LongTermMemoryEntry],
    ) -> LongTermMemoryEntry | None:
        """在已有条目中找同 kind+slot+scope 的活跃条目。"""
        for entry in existing:
            if entry.status != "active":
                continue
            if entry.kind != candidate.kind:
                continue
            if entry.slot != candidate.slot:
                continue
            if entry.scope != candidate.scope:
                continue
            if entry.scope_id != candidate.scope_id:
                continue
            return entry
        return None

    def _merge(
        self,
        candidate: MemoryCandidate,
        existing_entry: LongTermMemoryEntry,
    ) -> LongTermMemoryEntry:
        """合并候选到已有条目。"""
        now = self._now_iso()
        total = existing_entry.support_count + candidate.support_count

        weighted_conf = (
            (existing_entry.confidence * existing_entry.support_count)
            + (candidate.confidence * candidate.support_count)
        ) / max(total, 1)

        all_evidence = list(existing_entry.evidence)
        for ev in candidate.evidence:
            if ev.message_id and not any(
                e.message_id == ev.message_id for e in all_evidence
            ):
                all_evidence.append(ev)

        existing_tags = set(existing_entry.tags)
        new_tags = set(self._infer_tags(candidate))
        merged_tags = sorted(existing_tags | new_tags)[:12]

        existing_entry.value = candidate.value if total >= 3 else existing_entry.value
        existing_entry.summary = candidate.summary
        existing_entry.confidence = round(weighted_conf, 4)
        existing_entry.support_count = total
        existing_entry.evidence = all_evidence
        existing_entry.tags = merged_tags
        existing_entry.updated_at = now
        existing_entry.last_seen_at = now

        return existing_entry

    def _infer_tags(self, candidate: MemoryCandidate) -> list[str]:
        tags: list[str] = []
        if candidate.kind == "preference":
            tags.append("preference")
            if any(food in candidate.value for food in ("吃", "喝", "奶茶", "咖啡", "新地", "火锅", "面", "饭")):
                tags.append("food")
            if any(game in candidate.value for game in ("玩", "游戏", "原神", "崩铁", "Minecraft", "MC")):
                tags.append("game")
        elif candidate.kind == "habit":
            tags.append("habit")
            if any(word in candidate.value for word in ("加班", "23点", "睡", "起床", "作息")):
                tags.append("schedule")
        if candidate.scope == "private_user":
            tags.append("private")
        elif candidate.scope == "group_user":
            tags.append("group_member")
        else:
            tags.append("group_shared")
        return tags[:8]

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
