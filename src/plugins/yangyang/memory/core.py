from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from nonebot.log import logger

from ..core.runtime_compat import escape_log_preview


@dataclass
class ShortTermMemoryEntry:
    uid: str
    text: str
    timestamp: float
    type: str = "message"
    group_id: str = ""
    nick: str = ""
    channel: str = ""
    session_id: str = ""


class MemorySystem:
    """Phase A 基础记忆系统。

    - L1: 进程内短期会话缓存
    - L3: 用户画像 / impressions / relations 文件存储
    - backups: 每次写入生成审计快照
    """

    def __init__(self, base_dir: str | Path, short_term_limit: int = 100):
        self.base_dir = Path(base_dir)
        self.short_term_limit = max(1, int(short_term_limit))
        self.prompt_char_budget = 2400
        self.prompt_short_term_item_limit = 8
        self.prompt_profile_char_budget = 800
        self.prompt_impression_char_budget = 500
        self.prompt_relation_char_budget = 400
        self.short_term_cache: dict[str, list[dict[str, Any]]] = {}

        self.daily_dir = self.base_dir / "daily"
        self.long_term_dir = self.base_dir / "long_term"
        self.backups_dir = self.base_dir / "backups"
        self.short_term_dir = self.base_dir / "short_term"
        self.impressions_path = self.long_term_dir / "impressions.json"
        self.relations_path = self.long_term_dir / "relations.json"

        self.ensure_directories()

    def ensure_directories(self) -> None:
        for path in (self.base_dir, self.daily_dir, self.long_term_dir, self.backups_dir, self.short_term_dir):
            path.mkdir(parents=True, exist_ok=True)
        self._ensure_json_file(self.impressions_path, {})
        self._ensure_json_file(self.relations_path, {})

    def add_to_short_term(self, session_id: str, message: dict[str, Any] | ShortTermMemoryEntry | str) -> None:
        session_key = str(session_id or "default")
        normalized = self._normalize_short_term_message(session_key, message)
        bucket = self.short_term_cache.setdefault(session_key, [])
        bucket.append(normalized)
        if len(bucket) > self.short_term_limit:
            self.short_term_cache[session_key] = bucket[-self.short_term_limit :]

    def get_short_term_context(self, session_id: str, limit: int = 20) -> list[dict[str, Any]]:
        session_key = str(session_id or "default")
        bucket = self.short_term_cache.get(session_key, [])
        return [dict(item) for item in bucket[-max(1, int(limit)) :]]

    def save_user_profile(self, user_id: str, profile: dict[str, Any]) -> dict[str, Any]:
        payload = dict(profile or {})
        payload["user_id"] = str(user_id)
        payload.setdefault("last_updated", self._now_iso())
        if "last_updated" not in payload or not payload["last_updated"]:
            payload["last_updated"] = self._now_iso()
        path = self._profile_path(user_id)
        self._write_json_with_backup(path, payload)
        return payload

    def get_user_profile(self, user_id: str) -> dict[str, Any] | None:
        return self._read_json(self._profile_path(user_id), default=None)

    def update_impression(self, user_id: str, key: str, value: Any) -> dict[str, Any]:
        data = self.get_all_impressions()
        user_key = str(user_id)
        node = dict(data.get(user_key) or {})
        node[str(key)] = value
        node["last_updated"] = self._now_iso()
        data[user_key] = node
        self._write_json_with_backup(self.impressions_path, data)
        return node

    def get_impressions(self, user_id: str) -> dict[str, Any]:
        return dict(self.get_all_impressions().get(str(user_id)) or {})

    def get_all_impressions(self) -> dict[str, Any]:
        return dict(self._read_json(self.impressions_path, default={}) or {})

    def save_relations(self, relations: dict[str, Any]) -> dict[str, Any]:
        payload = dict(relations or {})
        self._write_json_with_backup(self.relations_path, payload)
        return payload

    def get_relations(self) -> dict[str, Any]:
        return dict(self._read_json(self.relations_path, default={}) or {})

    def update_relation(self, user_id: str, related_user_id: str, relation: Any) -> dict[str, Any]:
        data = self.get_relations()
        user_key = str(user_id)
        user_relations = dict(data.get(user_key) or {})
        user_relations[str(related_user_id)] = relation
        data[user_key] = user_relations
        self._write_json_with_backup(self.relations_path, data)
        return user_relations

    def build_memory_prompt(
        self,
        user_id: str,
        session_id: str,
        short_term_limit: int = 8,
        char_budget: int | None = None,
    ) -> str:
        total_budget = max(200, int(char_budget or self.prompt_char_budget))
        short_budget = max(120, total_budget // 2)
        profile_budget = max(80, min(self.prompt_profile_char_budget, total_budget // 3))
        impression_budget = max(60, min(self.prompt_impression_char_budget, total_budget // 5))
        relation_budget = max(60, min(self.prompt_relation_char_budget, total_budget // 6))
        item_limit = max(1, min(int(short_term_limit or self.prompt_short_term_item_limit), self.prompt_short_term_item_limit))

        parts: list[str] = []
        truncation_notes: list[str] = []

        short_term = self.get_short_term_context(session_id, limit=max(item_limit * 4, item_limit))
        rendered_short = self._render_short_term_section(short_term, item_limit=item_limit, char_budget=short_budget)
        if rendered_short:
            section, truncated = rendered_short
            parts.append(section)
            if truncated:
                truncation_notes.append(f"短期记忆已裁剪，仅保留最近 {item_limit} 条关键信息")

        profile = self.get_user_profile(user_id)
        if profile:
            rendered = self._render_budgeted_section(
                "[长期用户画像]",
                self._format_mapping(profile, exclude_keys={"user_id"}),
                profile_budget,
            )
            if rendered:
                section, truncated = rendered
                parts.append(section)
                if truncated:
                    truncation_notes.append("长期用户画像已裁剪")

        impressions = self.get_impressions(user_id)
        if impressions:
            rendered = self._render_budgeted_section("[用户印象]", self._format_mapping(impressions), impression_budget)
            if rendered:
                section, truncated = rendered
                parts.append(section)
                if truncated:
                    truncation_notes.append("用户印象已裁剪")

        relations = self.get_relations().get(str(user_id))
        if relations:
            rendered = self._render_budgeted_section("[关系图谱]", self._format_mapping(relations), relation_budget)
            if rendered:
                section, truncated = rendered
                parts.append(section)
                if truncated:
                    truncation_notes.append("关系图谱已裁剪")

        prompt = "\n\n".join(part for part in parts if part).strip()
        if len(prompt) > total_budget:
            prompt = prompt[: total_budget - 1] + "…"
            if "记忆上下文已按预算裁剪" not in truncation_notes:
                truncation_notes.append("记忆上下文已按预算裁剪")

        if truncation_notes:
            hint = "[记忆裁剪提示]\n- " + "\n- ".join(dict.fromkeys(truncation_notes))
            if prompt:
                if len(prompt) + 2 + len(hint) <= total_budget:
                    prompt = f"{prompt}\n\n{hint}"
                else:
                    room = max(0, total_budget - len(hint) - 2)
                    prompt = (prompt[:room].rstrip() + "\n\n" + hint).strip() if room > 0 else hint[:total_budget]
            else:
                prompt = hint[:total_budget]

        preview = escape_log_preview(prompt, limit=240)
        logger.info(
            f"MemorySystem: build_memory_prompt user_id={user_id} session_id={session_id} preview={preview}"
        )
        return prompt.strip()

    def _profile_path(self, user_id: str) -> Path:
        return self.long_term_dir / f"profile_{str(user_id)}.json"

    def _render_short_term_section(
        self,
        items: list[dict[str, Any]],
        *,
        item_limit: int,
        char_budget: int,
    ) -> tuple[str, bool] | None:
        lines: list[str] = []
        source_items = list(items or [])
        selected = source_items[-item_limit:]
        for item in selected:
            speaker = item.get("nick") or item.get("uid") or "用户"
            text = str(item.get("text") or "").strip()
            if not text:
                continue
            lines.append(f"- {speaker}: {self._truncate_text(text, 160)}")
        if not lines:
            return None
        body = "\n".join(lines)
        truncated = len(source_items) > len(selected)
        section = f"[短期上下文记忆]\n{body}"
        if len(section) > char_budget:
            truncated = True
            kept: list[str] = []
            current_len = len("[短期上下文记忆]\n")
            for line in reversed(lines):
                line_len = len(line) + (1 if kept else 0)
                if current_len + line_len > char_budget:
                    continue
                kept.append(line)
                current_len += line_len
            kept.reverse()
            if not kept:
                kept = [self._truncate_text(lines[-1], max(10, char_budget - len("[短期上下文记忆]\n")))]
            section = "[短期上下文记忆]\n" + "\n".join(kept)
        return section, truncated

    def _render_budgeted_section(self, title: str, body: str, char_budget: int) -> tuple[str, bool] | None:
        normalized = str(body or "").strip()
        if not normalized:
            return None
        section = f"{title}\n{normalized}"
        if len(section) <= char_budget:
            return section, False
        available = max(1, char_budget - len(title) - 1)
        return f"{title}\n{self._truncate_text(normalized, available)}", True

    def _truncate_text(self, text: str, limit: int) -> str:
        value = str(text or "").strip()
        if len(value) <= limit:
            return value
        if limit <= 1:
            return value[:limit]
        return value[: limit - 1] + "…"

    def _normalize_short_term_message(
        self,
        session_id: str,
        message: dict[str, Any] | ShortTermMemoryEntry | str,
    ) -> dict[str, Any]:
        if isinstance(message, ShortTermMemoryEntry):
            payload = asdict(message)
            payload["session_id"] = str(payload.get("session_id") or session_id or "default")
            return payload
        if isinstance(message, str):
            return asdict(
                ShortTermMemoryEntry(
                    uid="",
                    text=message,
                    timestamp=time.time(),
                    session_id=str(session_id or "default"),
                )
            )

        payload = dict(message or {})
        entry = ShortTermMemoryEntry(
            uid=str(payload.get("uid") or payload.get("user_id") or ""),
            text=str(payload.get("text") or payload.get("content") or payload.get("raw_content") or ""),
            timestamp=float(payload.get("timestamp") or payload.get("created_at") or time.time()),
            type=str(payload.get("type") or "message"),
            group_id=str(payload.get("group_id") or ""),
            nick=str(payload.get("nick") or ""),
            channel=str(payload.get("channel") or ""),
            session_id=str(payload.get("session_id") or session_id or "default"),
        )
        normalized = asdict(entry)
        for key, value in payload.items():
            if key not in normalized:
                normalized[key] = value
        return normalized

    def _ensure_json_file(self, path: Path, default: Any) -> None:
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_json(self, path: Path, default: Any) -> Any:
        try:
            if not path.exists():
                return default
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("MemorySystem: failed to read json: %s", path)
            return default

    def _write_json_with_backup(self, path: Path, data: Any) -> None:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists():
                existing = self._read_json(path, default=None)
                if existing is not None:
                    self._write_backup(path, existing, stage="before")
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            self._write_backup(path, data, stage="after")
        except Exception:
            logger.exception("MemorySystem: failed to write json with backup: %s", path)
            raise

    def _write_backup(self, source_path: Path, data: Any, stage: str) -> None:
        relative = source_path.relative_to(self.base_dir)
        backup_name = f"{self._backup_timestamp()}__{stage}__{str(relative).replace('/', '__')}"
        backup_path = self.backups_dir / backup_name
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")

    def _format_mapping(self, data: dict[str, Any], exclude_keys: set[str] | None = None) -> str:
        excluded = exclude_keys or set()
        lines: list[str] = []
        for key, value in data.items():
            if key in excluded:
                continue
            if value in (None, "", [], {}):
                continue
            if isinstance(value, list):
                rendered = "、".join(str(item) for item in value)
            elif isinstance(value, dict):
                rendered = "; ".join(f"{k}:{v}" for k, v in value.items())
            else:
                rendered = str(value)
            lines.append(f"- {key}: {rendered}")
        return "\n".join(lines)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    def _backup_timestamp(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
