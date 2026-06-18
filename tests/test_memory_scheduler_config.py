from __future__ import annotations

from types import SimpleNamespace

from plugins.yangyang.tasks import resolve_pipeline_interval_minutes


def test_resolve_pipeline_interval_minutes_reads_runtime_config() -> None:
    cfg = SimpleNamespace(get=lambda key, default=None: 5 if key == "memory_pipeline_interval_minutes" else default)
    assert resolve_pipeline_interval_minutes(cfg) == 5


def test_resolve_pipeline_interval_minutes_clamps_invalid_values() -> None:
    cfg = SimpleNamespace(get=lambda key, default=None: 0 if key == "memory_pipeline_interval_minutes" else default)
    assert resolve_pipeline_interval_minutes(cfg) == 1


def test_resolve_pipeline_interval_minutes_falls_back_to_default() -> None:
    cfg = SimpleNamespace(get=lambda key, default=None: "bad" if key == "memory_pipeline_interval_minutes" else default)
    assert resolve_pipeline_interval_minutes(cfg, default=30) == 30
