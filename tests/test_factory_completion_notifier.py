from __future__ import annotations

import json
import tempfile
from pathlib import Path

from conftest import run
from mock_pipeline_runtime import DictConfig, FakeBot, prepare_modules  # type: ignore


OWNER_UID = "335059272"


def _build_config() -> DictConfig:
    return DictConfig(
        {
            "owner_uid": OWNER_UID,
            "owner_action_auto_reply_current_production_enabled": True,
            "owner_action_nonebot_sender_enabled": True,
            "owner_action_execution_enabled": True,
            "owner_action_allow_reply_current": True,
            "owner_action_current_session_delivery_enabled": True,
            "owner_action_delivery_safety_enabled": True,
            "owner_action_delivery_dedup_ttl_seconds": 300,
            "owner_action_delivery_audit_enabled": False,
        }
    )


def test_factory_completion_bridge_real_send_once(mods: dict) -> None:
    notify = mods["notify_owner_current_session_on_factory_completion"]
    bot = FakeBot(self_id="90001")

    result = run(
        notify(
            summary_text="工厂收工：共 12 项，全部结束。",
            config=_build_config(),
            bot=bot,
            owner_uid=OWNER_UID,
            explicit_enable=True,
            dry_run=False,
        )
    )

    assert result.enabled is True
    assert result.attempted is True
    assert result.delivered is True
    assert result.real_send is True
    assert result.reason == "private_msg_sent"
    assert bot.private_sent == [(int(OWNER_UID), "工厂收工：共 12 项，全部结束。")]
    print("[PASS] factory completion bridge current-session real send")


def test_factory_completion_bridge_empty_summary_blocked(mods: dict) -> None:
    notify = mods["notify_owner_current_session_on_factory_completion"]
    bot = FakeBot(self_id="90001")

    result = run(
        notify(
            summary_text="   ",
            config=_build_config(),
            bot=bot,
            owner_uid=OWNER_UID,
            explicit_enable=True,
            dry_run=False,
        )
    )

    assert result.enabled is False
    assert result.attempted is False
    assert result.delivered is False
    assert result.reason == "empty_summary"
    assert bot.private_sent == []
    print("[PASS] factory completion bridge empty summary blocked")


def test_factory_completion_notifier_collected_state_and_dedup() -> None:
    mods = prepare_modules()
    notifier_mod = mods["factory_completion_notifier_module"]

    with tempfile.TemporaryDirectory() as tmpdir:
        state_path = Path(tmpdir) / "factory_notifier_state.json"
        bot = FakeBot(self_id="90001")
        config = _build_config()

        notifier_mod.DEFAULT_STATE_PATH = state_path
        notifier_mod._get_runtime_config = lambda: config
        notifier_mod.get_bot = lambda: bot
        notifier_mod.build_agentbus_factory_report = lambda: {
            "status": "PASS",
            "latest_run": {"name": "run-001"},
            "latest": {"name": "run-001", "activity_state": "COLLECTED"},
            "recent_runs": [{"name": "run-001", "activity_state": "COLLECTED"}],
        }
        notifier_mod.format_agentbus_factory_report = lambda report: "收工摘要 run-001"

        run(notifier_mod.run_factory_completion_notifier())
        assert bot.private_sent == [(int(OWNER_UID), "收工摘要 run-001")]
        saved = json.loads(state_path.read_text(encoding="utf-8"))
        assert saved["last_notified_run_id"] == "run-001"

        run(notifier_mod.run_factory_completion_notifier())
        assert bot.private_sent == [(int(OWNER_UID), "收工摘要 run-001")]
        print("[PASS] factory completion notifier collected state + dedup")


def test_factory_completion_notifier_scheduler_registration_removed() -> None:
    mods = prepare_modules()
    tasks_mod = mods["tasks_module"]

    tasks_mod.stop_scheduler()
    tasks_mod.start_scheduler(interval_minutes=7)
    scheduler = tasks_mod._scheduler
    assert scheduler is not None

    job_ids = [kwargs.get("id") for _args, kwargs in scheduler.jobs]
    assert "factory_completion_notifier" not in job_ids
    assert job_ids.count("memory_pipeline") == 1
    assert job_ids.count("token_usage_hourly_push") == 1

    tasks_mod.stop_scheduler()
    print("[PASS] factory completion scheduler registration removed")
