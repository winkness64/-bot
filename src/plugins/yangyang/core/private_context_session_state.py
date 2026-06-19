from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


def _now_iso() -> str:
    try:
        return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")
    except Exception:
        return datetime.now().astimezone().isoformat(timespec="seconds")


def _trim(text: Any, limit: int) -> str:
    value = str(text or "").strip()
    if len(value) <= limit:
        return value
    return value[: max(limit - 1, 0)] + "…"


def _dedupe_trim_list(items: list[Any] | None, *, item_limit: int, char_limit: int) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in items or []:
        value = _trim(raw, char_limit)
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= item_limit:
            break
    return result


@dataclass
class PrivateContextSessionState:
    session_id: str
    current_task: str = ""
    rolling_summary: str = ""
    confirmed_facts: list[str] = field(default_factory=list)
    todo_items: list[str] = field(default_factory=list)
    recent_decisions: list[str] = field(default_factory=list)
    last_tool_summary: str = ""
    focus_hint: str = ""
    open_loops: list[str] = field(default_factory=list)
    memory_decision_hint: str = ""
    session_state_diff_summary: str = ""
    turn_count: int = 0
    updated_at: str = field(default_factory=_now_iso)


class PrivateContextSessionStateStore:
    def __init__(self, *, persist_enabled: bool = False, state_path: str | Path | None = None) -> None:
        self._states: dict[str, PrivateContextSessionState] = {}
        self.persist_enabled = bool(persist_enabled)
        self.state_path = Path(state_path) if state_path else None
        if self.persist_enabled and self.state_path is not None:
            self.load()

    def get_or_create(self, session_id: str) -> PrivateContextSessionState:
        key = str(session_id or "").strip() or "private:unknown"
        state = self._states.get(key)
        if state is None:
            state = PrivateContextSessionState(session_id=key)
            self._states[key] = state
        return state

    def update(
        self,
        session_id: str,
        *,
        current_task: str | None = None,
        rolling_summary: str | None = None,
        confirmed_facts: list[Any] | None = None,
        todo_items: list[Any] | None = None,
        recent_decisions: list[Any] | None = None,
        last_tool_summary: str | None = None,
        focus_hint: str | None = None,
        open_loops: list[Any] | None = None,
        memory_decision_hint: str | None = None,
        session_state_diff_summary: str | None = None,
        turn_count: int | None = None,
    ) -> PrivateContextSessionState:
        state = self.get_or_create(session_id)
        if current_task is not None:
            state.current_task = _trim(current_task, 160)
        if rolling_summary is not None:
            state.rolling_summary = _trim(rolling_summary, 500)
        if confirmed_facts is not None:
            state.confirmed_facts = _dedupe_trim_list(confirmed_facts, item_limit=6, char_limit=120)
        if todo_items is not None:
            state.todo_items = _dedupe_trim_list(todo_items, item_limit=6, char_limit=120)
        if recent_decisions is not None:
            state.recent_decisions = _dedupe_trim_list(recent_decisions, item_limit=6, char_limit=120)
        if last_tool_summary is not None:
            state.last_tool_summary = _trim(last_tool_summary, 240)
        if focus_hint is not None:
            state.focus_hint = _trim(focus_hint, 160)
        if open_loops is not None:
            state.open_loops = _dedupe_trim_list(open_loops, item_limit=6, char_limit=120)
        if memory_decision_hint is not None:
            state.memory_decision_hint = _trim(memory_decision_hint, 240)
        if session_state_diff_summary is not None:
            state.session_state_diff_summary = _trim(session_state_diff_summary, 240)
        if turn_count is not None:
            state.turn_count = max(0, int(turn_count))
        state.updated_at = _now_iso()
        if self.persist_enabled and self.state_path is not None:
            self.flush()
        return state

    def flush(self) -> None:
        if self.state_path is None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {k: asdict(v) for k, v in self._states.items()}
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def load(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            return
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return
        if not isinstance(raw, dict):
            return
        loaded: dict[str, PrivateContextSessionState] = {}
        for key, value in raw.items():
            if not isinstance(value, dict):
                continue
            try:
                loaded[str(key)] = PrivateContextSessionState(**value)
            except Exception:
                continue
        self._states = loaded
