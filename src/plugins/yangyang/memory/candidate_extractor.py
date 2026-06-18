from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Iterable

from .types import Evidence, MemoryCandidate, Scope



_QUESTION_MARKERS: tuple[str, ...] = (
    "什么",
    "啥",
    "哪个",
    "哪款",
    "哪种",
    "谁",
    "多少",
    "吗",
    "么",
    "？",
    "?",
)

_PREFERENCE_PATTERNS: tuple[tuple[re.Pattern[str], str, str, float], ...] = (
    (re.compile(r"^我最喜欢(?P<value>[^，。！？!?,；;]{1,40})"), "preference", "favorite", 0.82),
    (re.compile(r"^我一般喜欢(?P<value>[^，。！？!?,；;]{1,40})"), "preference", "general_like", 0.72),
    (re.compile(r"^我喜欢(?P<value>[^，。！？!?,；;]{1,40})"), "preference", "like", 0.7),
    (re.compile(r"^我讨厌(?P<value>[^，。！？!?,；;]{1,40})"), "preference", "dislike", 0.76),
    (re.compile(r"^我常玩(?P<value>[^，。！？!?,；;]{1,40})"), "preference", "often_play", 0.74),
    (re.compile(r"^我最近在玩(?P<value>[^，。！？!?,；;]{1,40})"), "preference", "recent_play", 0.74),
)

_ACTIVITY_PREFERENCE_PATTERNS: tuple[tuple[re.Pattern[str], str, float], ...] = (
    (
        re.compile(
            r"^我(?P<time>晚上|夜里|夜晚|白天|早上|上午|中午|下午|最近|近来|平时|通常|一般|下班后|放学后|休息时|周末|有空时)?"
            r"(?P<intensity>一般|最|特别|很|挺|比较)?喜欢(?P<action>打|玩|看|听|刷|追)(?P<object>[^，。！？!?,；;]{1,30})"
        ),
        "activity_like",
        0.78,
    ),
)

_ACTIVITY_SLOT_BY_ACTION: dict[str, str] = {
    "打": "favorite_game",
    "玩": "favorite_game",
    "看": "leisure_activity",
    "听": "leisure_activity",
    "刷": "leisure_activity",
    "追": "leisure_activity",
}

_GAME_KEYWORDS: tuple[str, ...] = ("游戏", "原神", "崩铁", "星铁", "绝区零", "鸣潮", "Minecraft", "MC", "lol", "LOL", "王者", "吃鸡")

_HABIT_PATTERNS: tuple[tuple[re.Pattern[str], str, float], ...] = (
    (re.compile(r"^我经常(?P<value>[^。！？!?]{2,80})"), "habit", 0.74),
    (re.compile(r"^我一般(?P<value>[^。！？!?]{2,80})"), "habit", 0.68),
    (re.compile(r"^我通常(?P<value>[^。！？!?]{2,80})"), "habit", 0.72),
    (re.compile(r"^以后我说(?P<value>[^。！？!?]{2,120})"), "habit", 0.84),
    (re.compile(r"^(?P<value>起码[^。！？!?]{2,120}才问)"), "habit", 0.66),
)

# 保留 joke 标记用于简单的玩笑过滤，但不做严格风险拦截
_JOKE_MARKERS: tuple[str, ...] = (
    "开玩笑",
    "别当真",
    "逗你",
)


class CandidateExtractor:
    def extract_from_message(self, message: dict) -> list[MemoryCandidate]:
        text = self._normalize_text(message.get("text") or message.get("content") or "")
        if not text:
            return []

        # 写入链路防污染：疑问句只允许走读取/检索，不进入 C1 preference/habit 候选。
        # 必须先于所有“我喜欢...”规则，否则“我喜欢打什么游戏”会被误写成偏好。
        if self.is_question_for_write(text):
            return []

        scope, scope_id = self.infer_scope(message)
        candidates: list[MemoryCandidate] = []
        candidates.extend(self._extract_by_patterns(message, text, scope, scope_id, _PREFERENCE_PATTERNS))
        candidates.extend(self._extract_activity_preferences(message, text, scope, scope_id))
        candidates.extend(self._extract_by_patterns(message, text, scope, scope_id, _HABIT_PATTERNS))
        return candidates


    def is_question_for_write(self, text: str) -> bool:
        """C1 写入前的高优先级问句防线。

        命中这些疑问结构时，消息应被当作 ask_memory/read_query，不能生成写入候选。
        """
        normalized = self._normalize_text(text)
        if not normalized:
            return False
        return any(marker in normalized for marker in _QUESTION_MARKERS)

    def extract_from_messages(self, messages: list[dict]) -> list[MemoryCandidate]:
        results: list[MemoryCandidate] = []
        for message in messages:
            results.extend(self.extract_from_message(message))
        return results

    def infer_scope(self, message: dict) -> tuple[Scope, str]:
        channel = str(message.get("channel") or "").strip().lower()
        user_id = str(message.get("user_id") or message.get("uid") or "")
        group_id = str(message.get("group_id") or "")

        if channel == "private" or not group_id:
            return "private_user", user_id
        return "group_user", f"{group_id}:{user_id}"

    def _extract_by_patterns(
        self,
        message: dict,
        text: str,
        scope: Scope,
        scope_id: str,
        patterns: Iterable[tuple[re.Pattern[str], str, str | float, float | None]],
    ) -> list[MemoryCandidate]:
        candidates: list[MemoryCandidate] = []
        for item in patterns:
            pattern = item[0]
            kind = str(item[1])
            if len(item) == 4:
                slot_hint = str(item[2])
                confidence = float(item[3] or 0.0)
            else:
                slot_hint = kind
                confidence = float(item[2] or 0.0)
            match = pattern.search(text)
            if not match:
                continue
            value = self._clean_value(match.group("value"))
            if not value:
                continue
            candidate = self._build_candidate(
                message=message,
                scope=scope,
                scope_id=scope_id,
                kind=kind,
                slot=self._infer_slot(kind, slot_hint, value),
                value=value,
                confidence=confidence,
                promotion_reason="single_clear_self_statement" if kind == "preference" else "rule_match",
            )
            candidates.append(candidate)
        return candidates

    def _extract_activity_preferences(
        self,
        message: dict,
        text: str,
        scope: Scope,
        scope_id: str,
    ) -> list[MemoryCandidate]:
        """提取“时间状语 + 喜欢 + 活动动词 + 对象”的活动偏好。

        目标覆盖：我晚上一般喜欢打鸣潮 / 我最近喜欢看番 / 我平时喜欢听歌。
        聚合策略：同一动作和对象归一为同一 value，例如“晚上一般喜欢打鸣潮”与
        “晚上最喜欢打鸣潮”都产出 value=打鸣潮，确保 support_count 可累计。
        """
        candidates: list[MemoryCandidate] = []
        for pattern, slot_hint, confidence in _ACTIVITY_PREFERENCE_PATTERNS:
            match = pattern.search(text)
            if not match:
                continue
            action = self._clean_value(match.group("action") or "")
            obj = self._clean_value(match.group("object") or "")
            if not action or not obj:
                continue
            value = self._clean_value(f"{action}{obj}")
            if not value:
                continue
            slot = self._infer_activity_slot(action, obj, slot_hint)
            candidates.append(
                self._build_candidate(
                    message=message,
                    scope=scope,
                    scope_id=scope_id,
                    kind="preference",
                    slot=slot,
                    value=value,
                    confidence=confidence,
                    promotion_reason="activity_preference_statement",
                )
            )
        return candidates

    def _infer_activity_slot(self, action: str, obj: str, slot_hint: str) -> str:
        if action in {"打", "玩"}:
            return "favorite_game"
        if any(keyword in obj for keyword in _GAME_KEYWORDS):
            return "favorite_game"
        return _ACTIVITY_SLOT_BY_ACTION.get(action, slot_hint)

    def _build_candidate(
        self,
        *,
        message: dict,
        scope: Scope,
        scope_id: str,
        kind: str,
        slot: str,
        value: str,
        confidence: float,
        promotion_reason: str,
    ) -> MemoryCandidate:
        text = self._normalize_text(message.get("text") or message.get("content") or "")
        user_id = str(message.get("user_id") or message.get("uid") or "")
        group_id = str(message.get("group_id") or "")
        channel = str(message.get("channel") or "")
        timestamp = str(message.get("timestamp") or self._now_iso())
        evidence = [
            Evidence(
                message_id=str(message.get("message_id") or message.get("msg_id") or ""),
                timestamp=timestamp,
                speaker_id=user_id,
                text=text,
            )
        ]
        return MemoryCandidate(
            candidate_id=f"cand_{uuid.uuid4().hex[:12]}",
            date=timestamp[:10] if len(timestamp) >= 10 else self._now_iso()[:10],
            state="pending",
            scope=scope,
            scope_id=scope_id,
            session_id=self._build_session_id(channel, group_id, user_id),
            user_id=user_id,
            group_id=group_id,
            channel=channel,
            kind=kind,  # type: ignore[arg-type]
            slot=slot,
            value=value,
            summary=self._build_summary(kind, value, channel, user_id),
            evidence=evidence,
            confidence=confidence,
            support_count=1,
            contradiction_count=0,
            promotion_reason=promotion_reason,
            risk_flags=[],
            created_at=self._now_iso(),
        )

    def _infer_slot(self, kind: str, slot_hint: str, value: str) -> str:
        text = value.lower()
        if kind == "preference":
            if any(word in value for word in ("吃", "喝", "奶茶", "咖啡", "新地", "火锅", "面", "脉动", "可乐", "雪碧", "果汁")):
                return "favorite_food"
            if any(word in value for word in ("玩", "打", "游戏", "原神", "崩铁", "星铁", "绝区零", "鸣潮", "Minecraft", "MC")):
                return "favorite_game"
            return slot_hint
        if kind == "habit":
            if any(word in text for word in ("加班", "睡", "起床", "作息", "熬夜", "码")):
                return "schedule_rule"
            return "habit"
        return slot_hint

    def _build_summary(self, kind: str, value: str, channel: str, user_id: str) -> str:
        if channel == "private":
            return f"用户说：{value}"
        return f"群友说：{value}"

    def _build_session_id(self, channel: str, group_id: str, user_id: str) -> str:
        if channel == "private" or not group_id:
            return f"private:{user_id}"
        return f"group:{group_id}"

    def _normalize_text(self, text: str | None) -> str:
        return str(text or "").strip()

    def _clean_value(self, value: str) -> str:
        return value.strip().rstrip("，。！？!?；;、")

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
