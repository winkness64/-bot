from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Sequence

from .query_router import detect_structured_memory_query
from .types import LongTermMemoryEntry

GroundingStatus = Literal["none", "resolved", "ambiguous"]
EntitySource = Literal["rules", "memory_value", "manual_alias"]


@dataclass(frozen=True, slots=True)
class EntityCandidate:
    canonical: str
    kind: str
    aliases: tuple[str, ...] = ()
    confidence: float = 0.0
    source: EntitySource = "rules"


@dataclass(frozen=True, slots=True)
class GroundingResult:
    normalized_query: str
    expanded_slots: tuple[str, ...] = ()
    alias_terms: tuple[str, ...] = ()
    entity_candidates: tuple[EntityCandidate, ...] = ()
    confidence: float = 0.0
    status: GroundingStatus = "none"
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GroundingInput:
    user_id: str
    session_id: str
    channel: Literal["private", "group"]
    query: str
    scope: str
    scope_id: str


@dataclass(frozen=True, slots=True)
class AliasRule:
    canonical: str
    kind: str
    aliases: tuple[str, ...]
    confidence: float = 0.85


DEFAULT_ALIAS_RULES: tuple[AliasRule, ...] = (
    AliasRule(canonical="绝区零", kind="game", aliases=("绝区零", "zzz", "ZZZ", "绝"), confidence=0.88),
    AliasRule(canonical="鸣潮", kind="game", aliases=("鸣潮", "mc", "MC"), confidence=0.82),
    AliasRule(canonical="脉动", kind="drink", aliases=("脉动",), confidence=0.9),
)

_SHORT_AMBIGUOUS_ALIASES: frozenset[str] = frozenset({"绝", "mc", "MC"})


def normalize_query(text: str | None) -> str:
    """Return a compact query string for deterministic matching."""
    value = str(text or "").strip()
    value = re.sub(r"\s+", " ", value)
    return value


class RuleBasedGroundingResolver:
    """Read-only rules grounding / alias resolver.

    This class never writes memory, never mutates entries, and never performs
    permission checks by itself. Callers must pass only entries already filtered
    by actor/scope gates.
    """

    def __init__(self, alias_rules: Sequence[AliasRule] | None = None) -> None:
        self.alias_rules: tuple[AliasRule, ...] = tuple(alias_rules or DEFAULT_ALIAS_RULES)

    def ground(
        self,
        query: str | None,
        *,
        entries: Sequence[LongTermMemoryEntry] | None = None,
        user_id: str = "",
        session_id: str = "",
        channel: Literal["private", "group"] = "private",
        scope: str = "private_user",
        scope_id: str = "",
    ) -> GroundingResult:
        normalized = normalize_query(query)
        if not normalized:
            return GroundingResult(normalized_query="", reasons=("empty_query",))

        expanded_slots: list[str] = []
        reasons: list[str] = []

        structured = detect_structured_memory_query(normalized)
        if structured is not None:
            expanded_slots.extend(structured.slots)
            reasons.append(f"structured_query:{structured.reason}")

        alias_candidates, alias_terms, alias_ambiguous = self._match_alias_rules(normalized)
        memory_candidates = self._match_memory_values(normalized, entries or (), expanded_slots)
        candidates = self._dedupe_candidates((*alias_candidates, *memory_candidates))

        # Avoid hard-resolving short aliases unless the query has a clear domain hint.
        if alias_ambiguous:
            status: GroundingStatus = "ambiguous"
            confidence = min((c.confidence for c in candidates), default=0.45)
            reasons.append("ambiguous_short_alias")
        elif len(candidates) > 1 and self._has_conflicting_candidates(candidates):
            status = "ambiguous"
            confidence = max((c.confidence for c in candidates), default=0.5)
            reasons.append("multiple_entity_candidates")
        elif candidates or expanded_slots:
            status = "resolved"
            confidence = max([0.6, *(c.confidence for c in candidates)] if candidates else [0.6])
            if candidates:
                reasons.append("entity_candidate_resolved")
            if expanded_slots:
                reasons.append("slot_expanded")
        else:
            status = "none"
            confidence = 0.0
            reasons.append("no_grounding_match")

        return GroundingResult(
            normalized_query=normalized,
            expanded_slots=tuple(dict.fromkeys(expanded_slots)),
            alias_terms=tuple(dict.fromkeys(alias_terms)),
            entity_candidates=candidates,
            confidence=round(float(confidence), 3),
            status=status,
            reasons=tuple(dict.fromkeys(reasons)),
        )

    def _match_alias_rules(self, query: str) -> tuple[tuple[EntityCandidate, ...], tuple[str, ...], bool]:
        candidates: list[EntityCandidate] = []
        terms: list[str] = []
        ambiguous = False
        query_lower = query.lower()
        for rule in self.alias_rules:
            for alias in rule.aliases:
                alias_lower = alias.lower()
                if not alias_lower:
                    continue
                if alias_lower not in query_lower:
                    continue
                terms.append(alias)
                confidence = rule.confidence
                if alias in _SHORT_AMBIGUOUS_ALIASES and not _has_domain_hint(query, rule.kind):
                    confidence = min(confidence, 0.55)
                    ambiguous = True
                candidates.append(
                    EntityCandidate(
                        canonical=rule.canonical,
                        kind=rule.kind,
                        aliases=rule.aliases,
                        confidence=confidence,
                        source="rules",
                    )
                )
                break
        return tuple(candidates), tuple(terms), ambiguous

    def _match_memory_values(
        self,
        query: str,
        entries: Sequence[LongTermMemoryEntry],
        expanded_slots: Sequence[str],
    ) -> tuple[EntityCandidate, ...]:
        if not entries:
            return ()
        candidates: list[EntityCandidate] = []
        wanted_slots = set(expanded_slots)
        for entry in entries:
            if getattr(entry, "status", "active") != "active":
                continue
            value = _canonicalize_memory_value(str(getattr(entry, "value", "")))
            if not value:
                continue
            slot = str(getattr(entry, "slot", ""))
            kind = _kind_from_slot(slot, str(getattr(entry, "kind", "")))
            if value in query or query.lower() in value.lower():
                candidates.append(
                    EntityCandidate(canonical=value, kind=kind, aliases=(value,), confidence=0.82, source="memory_value")
                )
                continue
            if wanted_slots and slot in wanted_slots:
                candidates.append(
                    EntityCandidate(canonical=value, kind=kind, aliases=(value,), confidence=0.72, source="memory_value")
                )
        return tuple(candidates)

    @staticmethod
    def _dedupe_candidates(candidates: Sequence[EntityCandidate]) -> tuple[EntityCandidate, ...]:
        merged: dict[tuple[str, str], EntityCandidate] = {}
        for candidate in candidates:
            key = (candidate.kind, candidate.canonical)
            previous = merged.get(key)
            if previous is None or candidate.confidence > previous.confidence:
                merged[key] = candidate
        return tuple(merged.values())

    @staticmethod
    def _has_conflicting_candidates(candidates: Sequence[EntityCandidate]) -> bool:
        by_kind: dict[str, set[str]] = {}
        for candidate in candidates:
            by_kind.setdefault(candidate.kind, set()).add(candidate.canonical)
        return any(len(values) > 1 for values in by_kind.values())


def _has_domain_hint(query: str, kind: str) -> bool:
    if kind == "game":
        return any(token in query for token in ("游戏", "打", "玩"))
    if kind == "drink":
        return any(token in query for token in ("喝", "饮料"))
    return False


def _canonicalize_memory_value(value: str) -> str:
    result = value.strip()
    for prefix in ("打", "玩", "喝", "吃", "看", "听"):
        if result.startswith(prefix) and len(result) > len(prefix):
            result = result[len(prefix) :].strip()
            break
    return result


def _kind_from_slot(slot: str, fallback: str) -> str:
    if "game" in slot:
        return "game"
    if "drink" in slot:
        return "drink"
    if "food" in slot:
        return "food"
    if "music" in slot or "song" in slot:
        return "music"
    if "show" in slot or "anime" in slot:
        return "show"
    return fallback or "memory"
