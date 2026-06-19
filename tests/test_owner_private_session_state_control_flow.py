from __future__ import annotations

from types import SimpleNamespace

from mock_pipeline_runtime import prepare_modules  # type: ignore


mods = prepare_modules()
plugin = mods["plugin"]


def _state(**overrides):
    base = {
        "current_task": "更新一下文档老年痴呆治疗，然后继续",
        "todo_items": ["更新一下文档老年痴呆治疗，然后继续"],
        "open_loops": ["更新一下文档老年痴呆治疗，然后继续"],
        "recent_decisions": [],
        "focus_hint": "更新一下文档老年痴呆治疗，然后继续",
        "memory_decision_hint": "",
        "rolling_summary": "",
        "confirmed_facts": [],
        "last_tool_summary": "",
        "turn_count": 3,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_defer_turn_marks_suspended_open_loop() -> None:
    previous = _state()
    result = plugin._build_open_loops(previous, previous.current_task, "这个先放着，回头再说")
    assert result[0].startswith("suspended:")
    assert "更新一下文档老年痴呆治疗，然后继续" in result[0]


def test_completion_turn_clears_target_loop() -> None:
    previous = _state()
    result = plugin._build_open_loops(previous, previous.current_task, "这个已经做完了")
    assert "更新一下文档老年痴呆治疗，然后继续" not in result


def test_resume_turn_restores_suspended_loop_to_active() -> None:
    previous = _state(open_loops=["suspended:更新一下文档老年痴呆治疗，然后继续"])
    result = plugin._build_open_loops(previous, previous.current_task, "把刚才放着的捡回来")
    assert result[0] == "更新一下文档老年痴呆治疗，然后继续"
    assert all(not item.startswith("suspended:") for item in result)


def test_resume_turn_updates_current_task_from_suspended_target() -> None:
    previous = _state(
        current_task="别的任务",
        focus_hint="别的任务",
        open_loops=["suspended:更新一下文档老年痴呆治疗，然后继续"],
    )
    current_task = plugin._pick_session_current_task("文档那个继续", previous)
    assert current_task == "更新一下文档老年痴呆治疗，然后继续"


def test_diff_summary_includes_suspended_count() -> None:
    previous = _state(open_loops=["更新一下文档老年痴呆治疗，然后继续"])
    summary = plugin._build_session_state_diff_summary(
        previous,
        current_task=previous.current_task,
        todo_items=[],
        recent_decisions=[],
        focus_hint=previous.focus_hint,
        open_loops=["suspended:更新一下文档老年痴呆治疗，然后继续"],
        memory_decision_hint="signal:high | store:task_control | recall:task_anchor | reason:defer_turn | anchor:task",
        rolling_summary="",
        confirmed_facts=[],
        last_tool_summary="",
    )
    assert "reason=defer_turn" in summary
    assert "suspended=1" in summary


def test_diff_summary_includes_resumed_count() -> None:
    previous = _state(open_loops=["suspended:更新一下文档老年痴呆治疗，然后继续"])
    summary = plugin._build_session_state_diff_summary(
        previous,
        current_task="更新一下文档老年痴呆治疗，然后继续",
        todo_items=["更新一下文档老年痴呆治疗，然后继续"],
        recent_decisions=[],
        focus_hint="更新一下文档老年痴呆治疗，然后继续",
        open_loops=["更新一下文档老年痴呆治疗，然后继续"],
        memory_decision_hint="signal:high | store:task_control | recall:task_anchor | reason:resume_turn | anchor:task",
        rolling_summary="",
        confirmed_facts=[],
        last_tool_summary="",
    )
    assert "reason=resume_turn" in summary
    assert "resumed=1" in summary
