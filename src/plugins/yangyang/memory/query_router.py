from __future__ import annotations

import re
from dataclasses import dataclass


QUESTION_MARKERS: tuple[str, ...] = (
    "什么",
    "啥",
    "哪个",
    "哪款",
    "哪种",
    "吗",
    "么",
    "？",
    "?",
)

SELF_REFERENCE_MARKERS: tuple[str, ...] = (
    "我",
    "我的",
    "自己",
    "之前说过",
    "以前说过",
    "你记得我",
    "记得我",
)

MEMORY_READ_INTENT_MARKERS: tuple[str, ...] = (
    "喜欢",
    "最喜欢",
    "爱好",
    "习惯",
    "平时",
    "通常",
    "一般",
    "常",
    "晚上",
    "之前说过",
    "以前说过",
    "你记得",
    "记得我",
)

QUESTION_OBJECT_MARKERS: tuple[str, ...] = (
    "什么",
    "啥",
    "哪个",
    "哪款",
    "哪种",
)

DRINK_WORDS: tuple[str, ...] = (
    "喝",
    "饮料",
    "奶茶",
    "咖啡",
    "可乐",
    "雪碧",
    "果汁",
    "茶",
)

FOOD_WORDS: tuple[str, ...] = (
    "吃",
    "食物",
    "菜",
    "饭",
    "餐",
    "小吃",
    "零食",
    "甜品",
)

LISTEN_WORDS: tuple[str, ...] = (
    "听",
    "音乐",
    "歌",
    "歌曲",
)

WATCH_WORDS: tuple[str, ...] = (
    "看",
    "追",
    "刷",
)

GAME_WORDS: tuple[str, ...] = (
    "游戏",
    "打",
    "玩",
)


@dataclass(frozen=True, slots=True)
class StructuredMemoryQuery:
    """显式长期记忆读取问句的结构化表示。"""

    intent: str = "ask_self_memory"
    kind: str = "preference"
    slots: tuple[str, ...] = ()
    confidence: float = 0.0
    reason: str = ""
    question_text: str = ""

    @property
    def primary_slot(self) -> str:
        return self.slots[0] if self.slots else ""


def detect_structured_memory_query(text: str | None) -> StructuredMemoryQuery | None:
    """识别“用户显式询问自己偏好/习惯/信息”的读取型问句。

    第一版只做轻量规则路由：必须同时具备疑问特征、自我指向和记忆读取意图；
    命中后返回要优先精准查询的长期记忆 slot。该函数只读不写，不产生 C1/C2 候选。
    """
    normalized = _normalize_text(text)
    if not normalized:
        return None
    if not _contains_any(normalized, QUESTION_MARKERS):
        return None
    if not _contains_any(normalized, SELF_REFERENCE_MARKERS):
        return None
    if not _contains_any(normalized, MEMORY_READ_INTENT_MARKERS):
        return None

    slots, reasons = _infer_slots(normalized)
    if not slots:
        return None

    confidence = 0.78
    if normalized.startswith("我") or "你记得我" in normalized or "之前说过" in normalized or "以前说过" in normalized:
        confidence += 0.05
    if "最喜欢" in normalized:
        confidence += 0.05
    elif "喜欢" in normalized:
        confidence += 0.03
    if any(marker in normalized for marker in QUESTION_OBJECT_MARKERS):
        confidence += 0.03

    return StructuredMemoryQuery(
        intent="ask_self_memory",
        kind="preference",
        slots=slots,
        confidence=min(round(confidence, 2), 0.95),
        reason=";".join(reasons),
        question_text=normalized,
    )


def _infer_slots(text: str) -> tuple[tuple[str, ...], list[str]]:
    slots: list[str] = []
    reasons: list[str] = []

    if _looks_like_game_query(text):
        slots.append("favorite_game")
        reasons.append("game_action_or_keyword")

    if _contains_any(text, DRINK_WORDS):
        # 写入侧历史版本曾把“喝/饮料”合并进 favorite_food；读取侧保留 favorite_drink
        # 作为主 slot，同时兼容 favorite_food，避免旧记忆查不到。
        slots.extend(["favorite_drink", "favorite_food"])
        reasons.append("drink_keyword_with_food_compat")

    if _contains_any(text, FOOD_WORDS):
        slots.append("favorite_food")
        reasons.append("food_keyword")

    if _contains_any(text, LISTEN_WORDS):
        # 当前 CandidateExtractor 对“听歌/听音乐”写入 leisure_activity；favorite_music
        # 作为未来兼容 alias 放在后面。
        slots.extend(["leisure_activity", "favorite_music"])
        reasons.append("listen_keyword_current_leisure_activity")

    if _contains_any(text, WATCH_WORDS):
        slots.append("leisure_activity")
        reasons.append("watch_follow_scroll_keyword")

    return _dedupe(slots), reasons


def _looks_like_game_query(text: str) -> bool:
    if "游戏" in text:
        return True
    if re.search(r"(喜欢|最喜欢|平时|通常|一般|常|晚上).{0,8}(打|玩)", text):
        return True
    if re.search(r"(打|玩).{0,8}(什么|啥|哪个|哪款|哪种)", text):
        return True
    return False


def _normalize_text(text: str | None) -> str:
    value = str(text or "").strip()
    value = re.sub(r"\s+", "", value)
    return value


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


def _dedupe(items: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        result.append(item)
        seen.add(item)
    return tuple(result)
