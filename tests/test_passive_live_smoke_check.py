from __future__ import annotations

import json
from pathlib import Path

from tools.memory_final_closure.passive_live_smoke_check import main, run_check


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def test_checker_passes_positive_oolong_and_pipeline_log(tmp_path: Path) -> None:
    baseline = tmp_path / "baseline.jsonl"
    current = tmp_path / "memories.jsonl"
    log = tmp_path / "bot.log"
    write_jsonl(baseline, [])
    write_jsonl(
        current,
        [
            {
                "id": "mem_1",
                "status": "active",
                "scope": "private_user",
                "kind": "preference",
                "slot": "favorite_food",
                "value": "喝无糖乌龙茶",
                "summary": "用户说：喝无糖乌龙茶",
            }
        ],
    )
    log.write_text(
        "MemoryPipeline: run_once done — sessions=1 msgs=2 raw_candidates=2 aggregated_candidates=1 promoted=1 errors=0\n",
        encoding="utf-8",
    )

    result = run_check(
        memories_path=current,
        log_path=log,
        baseline_memories_path=baseline,
        expect_oolong_written="yes",
        require_pipeline_log=True,
    )

    assert result.ok is True
    assert result.errors == []
    assert result.observations["oolong_match_count"] == 1


def test_checker_fails_for_forbidden_temporary_state(tmp_path: Path) -> None:
    current = tmp_path / "memories.jsonl"
    log = tmp_path / "bot.log"
    write_jsonl(
        current,
        [
            {
                "id": "mem_bad",
                "status": "active",
                "scope": "private_user",
                "value": "我去倒杯水",
                "summary": "用户说：我去倒杯水",
            }
        ],
    )
    log.write_text("", encoding="utf-8")

    result = run_check(memories_path=current, log_path=log)

    assert result.ok is False
    assert any("倒杯水" in item for item in result.errors)


def test_checker_uses_baseline_to_avoid_old_forbidden_false_positive(tmp_path: Path) -> None:
    old_row = {"id": "mem_old", "status": "active", "value": "每天吃键盘", "summary": "旧数据"}
    baseline = tmp_path / "baseline.jsonl"
    current = tmp_path / "memories.jsonl"
    log = tmp_path / "bot.log"
    write_jsonl(baseline, [old_row])
    write_jsonl(current, [old_row])
    log.write_text("", encoding="utf-8")

    result = run_check(memories_path=current, log_path=log, baseline_memories_path=baseline)

    assert result.ok is True
    assert result.observations["checked_delta_rows"] == 0


def test_cli_returns_nonzero_when_required_log_missing(tmp_path: Path) -> None:
    current = tmp_path / "memories.jsonl"
    log = tmp_path / "bot.log"
    write_jsonl(current, [])
    log.write_text("no pipeline here", encoding="utf-8")

    code = main(["--memories", str(current), "--log", str(log), "--require-pipeline-log"])

    assert code == 1
