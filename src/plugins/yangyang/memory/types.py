from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


Scope = Literal["private_user", "group_user", "group_shared"]
MemoryKind = Literal[
    "preference",
    "habit",
    "identity",
    "relationship",
    "group_fact",
    "technical_note",
    "risk",
]
CandidateState = Literal["pending", "promoted", "rejected", "needs_review"]
MemoryStatus = Literal["active", "archived", "rejected"]
PromotionEvent = Literal["promote", "reject", "merge"]
PromotionDecision = Literal["promoted", "rejected", "merged", "reviewed"]

SCOPES: tuple[Scope, ...] = ("private_user", "group_user", "group_shared")
MEMORY_KINDS: tuple[MemoryKind, ...] = (
    "preference",
    "habit",
    "identity",
    "relationship",
    "group_fact",
    "technical_note",
    "risk",
)
CANDIDATE_STATES: tuple[CandidateState, ...] = ("pending", "promoted", "rejected", "needs_review")
MEMORY_STATUSES: tuple[MemoryStatus, ...] = ("active", "archived", "rejected")
PROMOTION_EVENTS: tuple[PromotionEvent, ...] = ("promote", "reject", "merge")
PROMOTION_DECISIONS: tuple[PromotionDecision, ...] = ("promoted", "rejected", "merged", "reviewed")


@dataclass(slots=True)
class Evidence:
    message_id: str
    timestamp: str
    speaker_id: str
    text: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evidence":
        payload = dict(data or {})
        return cls(
            message_id=str(payload.get("message_id") or ""),
            timestamp=str(payload.get("timestamp") or ""),
            speaker_id=str(payload.get("speaker_id") or ""),
            text=str(payload.get("text") or ""),
        )


@dataclass(slots=True)
class MemoryCandidate:
    candidate_id: str
    date: str
    scope: Scope
    scope_id: str
    session_id: str
    user_id: str
    group_id: str
    channel: str
    kind: MemoryKind
    slot: str
    value: str
    summary: str
    evidence: list[Evidence] = field(default_factory=list)
    confidence: float = 0.0
    support_count: int = 0
    contradiction_count: int = 0
    promotion_reason: str = ""
    risk_flags: list[str] = field(default_factory=list)
    created_at: str = ""
    state: CandidateState = "pending"
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = [item.to_dict() for item in self.evidence]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryCandidate":
        payload = dict(data or {})
        return cls(
            schema_version=int(payload.get("schema_version", 1) or 1),
            candidate_id=str(payload.get("candidate_id") or ""),
            date=str(payload.get("date") or ""),
            state=str(payload.get("state") or "pending"),
            scope=str(payload.get("scope") or "private_user"),
            scope_id=str(payload.get("scope_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            user_id=str(payload.get("user_id") or ""),
            group_id=str(payload.get("group_id") or ""),
            channel=str(payload.get("channel") or ""),
            kind=str(payload.get("kind") or "preference"),
            slot=str(payload.get("slot") or ""),
            value=str(payload.get("value") or ""),
            summary=str(payload.get("summary") or ""),
            evidence=[Evidence.from_dict(item) for item in list(payload.get("evidence") or [])],
            confidence=float(payload.get("confidence", 0.0) or 0.0),
            support_count=int(payload.get("support_count", 0) or 0),
            contradiction_count=int(payload.get("contradiction_count", 0) or 0),
            promotion_reason=str(payload.get("promotion_reason") or ""),
            risk_flags=[str(item) for item in list(payload.get("risk_flags") or [])],
            created_at=str(payload.get("created_at") or ""),
        )


@dataclass(slots=True)
class LongTermMemoryEntry:
    id: str
    status: MemoryStatus
    scope: Scope
    scope_id: str
    session_id: str
    user_id: str
    group_id: str
    channel: str
    kind: MemoryKind
    slot: str
    value: str
    summary: str
    evidence: list[Evidence] = field(default_factory=list)
    confidence: float = 0.0
    support_count: int = 0
    contradiction_count: int = 0
    source: str = "rule_promotion"
    tags: list[str] = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    last_seen_at: str = ""
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["evidence"] = [item.to_dict() for item in self.evidence]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LongTermMemoryEntry":
        payload = dict(data or {})
        return cls(
            schema_version=int(payload.get("schema_version", 1) or 1),
            id=str(payload.get("id") or ""),
            status=str(payload.get("status") or "active"),
            scope=str(payload.get("scope") or "private_user"),
            scope_id=str(payload.get("scope_id") or ""),
            session_id=str(payload.get("session_id") or ""),
            user_id=str(payload.get("user_id") or ""),
            group_id=str(payload.get("group_id") or ""),
            channel=str(payload.get("channel") or ""),
            kind=str(payload.get("kind") or "preference"),
            slot=str(payload.get("slot") or ""),
            value=str(payload.get("value") or ""),
            summary=str(payload.get("summary") or ""),
            evidence=[Evidence.from_dict(item) for item in list(payload.get("evidence") or [])],
            confidence=float(payload.get("confidence", 0.0) or 0.0),
            support_count=int(payload.get("support_count", 0) or 0),
            contradiction_count=int(payload.get("contradiction_count", 0) or 0),
            source=str(payload.get("source") or "rule_promotion"),
            tags=[str(item) for item in list(payload.get("tags") or [])],
            created_at=str(payload.get("created_at") or ""),
            updated_at=str(payload.get("updated_at") or ""),
            last_seen_at=str(payload.get("last_seen_at") or ""),
        )


@dataclass(slots=True)
class PromotionAuditRecord:
    event_id: str
    event: PromotionEvent
    candidate_id: str
    memory_id: str
    decision: PromotionDecision
    reason: str
    scope: Scope
    scope_id: str
    operator: str
    created_at: str
    schema_version: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PromotionAuditRecord":
        payload = dict(data or {})
        return cls(
            schema_version=int(payload.get("schema_version", 1) or 1),
            event_id=str(payload.get("event_id") or ""),
            event=str(payload.get("event") or "promote"),
            candidate_id=str(payload.get("candidate_id") or ""),
            memory_id=str(payload.get("memory_id") or ""),
            decision=str(payload.get("decision") or "promoted"),
            reason=str(payload.get("reason") or ""),
            scope=str(payload.get("scope") or "private_user"),
            scope_id=str(payload.get("scope_id") or ""),
            operator=str(payload.get("operator") or "rule_engine"),
            created_at=str(payload.get("created_at") or ""),
        )
