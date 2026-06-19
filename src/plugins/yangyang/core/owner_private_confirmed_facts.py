from __future__ import annotations

import re
from typing import Any

from .private_context_session_state import PrivateContextSessionState


DEFAULT_CONFIRMED_FACT_LIMIT = 6
DEFAULT_CONFIRMED_FACT_TEXT_LIMIT = 120
DEFAULT_NORMALIZED_TEXT_LIMIT = 240

_DEPRECATION_TOKENS = ("失效", "作废", "废弃", "不用了", "不再使用")
_DOC_SUBJECT_RE = re.compile(
    r'(?:文档|文件)(?:是|叫|名为)?[《"“]?([^\n，,。；;]{1,80}?\.(?:md|txt|cmm))[》"”]?',
    re.IGNORECASE,
)
_ALIAS_RE = re.compile(r"(?:你可以叫我|我叫做|我叫|叫我|我是)\s*([^\s，,。；;!！?？\"'“”‘’()（）\[\]【】]{1,24})")


def trim_confirmed_fact_text(value: Any, limit: int = DEFAULT_CONFIRMED_FACT_TEXT_LIMIT) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    text = re.sub(r"\s+", " ", text)
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def _deprecate_prefixed_items(items: list[str], prefixes: tuple[str, ...], fact_limit: int) -> None:
    kept: list[str] = []
    for item in items:
        raw = trim_confirmed_fact_text(item, DEFAULT_CONFIRMED_FACT_TEXT_LIMIT)
        if not raw:
            continue
        if any(raw.startswith(prefix) for prefix in prefixes):
            continue
        if raw not in kept:
            kept.append(raw)
    items[:] = kept[-fact_limit:]


def extract_confirmed_facts_from_owner_private_text(
    user_text: str,
    previous: PrivateContextSessionState | None = None,
    *,
    fact_limit: int = DEFAULT_CONFIRMED_FACT_LIMIT,
) -> list[str]:
    text = str(user_text or "").strip()
    if not text:
        return list(getattr(previous, "confirmed_facts", []) or [])[:fact_limit]

    normalized = trim_confirmed_fact_text(text, DEFAULT_NORMALIZED_TEXT_LIMIT)
    compact = normalized.replace(" ", "")
    items: list[str] = list(getattr(previous, "confirmed_facts", []) or [])

    def upsert(prefix: str, value: str) -> None:
        cleaned = trim_confirmed_fact_text(value, DEFAULT_CONFIRMED_FACT_TEXT_LIMIT)
        if not cleaned:
            return
        candidate = f"{prefix}{cleaned}"
        kept: list[str] = []
        for item in items:
            raw = trim_confirmed_fact_text(item, DEFAULT_CONFIRMED_FACT_TEXT_LIMIT)
            if not raw:
                continue
            if raw == candidate:
                continue
            if raw.startswith(prefix):
                continue
            if raw not in kept:
                kept.append(raw)
        kept.append(candidate)
        items[:] = kept[-fact_limit:]

    has_deprecation = any(token in normalized for token in _DEPRECATION_TOKENS)

    if has_deprecation and any(token in normalized for token in ("QQ", "qq")):
        _deprecate_prefixed_items(items, ("owner_id=",), fact_limit)
    if has_deprecation and any(token in normalized for token in ("文档", "文件")):
        _deprecate_prefixed_items(items, ("project_doc=",), fact_limit)
    if has_deprecation and any(token in normalized for token in ("群", "群号", "群聊")):
        _deprecate_prefixed_items(items, ("group_id=",), fact_limit)
    if has_deprecation and any(token in normalized for token in ("称呼", "别名", "名字", "叫我")):
        _deprecate_prefixed_items(items, ("alias=",), fact_limit)

    m = re.search(r"(?:我的|我)QQ(?:号)?是\s*(\d{5,12})", compact)
    if m:
        upsert("owner_id=", m.group(1))

    group_match = re.search(r"(?:群号|群聊|这个群|该群)(?:是|为)?\s*(\d{5,12})", compact)
    if group_match:
        upsert("group_id=", group_match.group(1))

    explicit_doc = _DOC_SUBJECT_RE.search(normalized)
    if explicit_doc:
        upsert("project_doc=", explicit_doc.group(1).strip())

    alias_match = _ALIAS_RE.search(normalized)
    if alias_match and not explicit_doc:
        alias = trim_confirmed_fact_text(alias_match.group(1).strip(" ，,。；;!！?？\"'“”‘’()（）[]【】"))
        if alias:
            upsert("alias=", alias)

    return items[:fact_limit]
