from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from mock_pipeline_runtime import DictConfig, install_nonebot_stubs, ensure_package, load_module, SRC_ROOT, PLUGIN_ROOT  # type: ignore

install_nonebot_stubs()
ensure_package("plugins", SRC_ROOT / "plugins")
ensure_package("plugins.yangyang", PLUGIN_ROOT)
ensure_package("plugins.yangyang.core", PLUGIN_ROOT / "core")
ensure_package("plugins.yangyang.core.model", PLUGIN_ROOT / "core" / "model")
ensure_package("plugins.yangyang.core.owner_toolbox", PLUGIN_ROOT / "core" / "owner_toolbox")

load_module("plugins.yangyang.core.token_usage", PLUGIN_ROOT / "core" / "token_usage.py")
load_module("plugins.yangyang.core.model.provider_base", PLUGIN_ROOT / "core" / "model" / "provider_base.py")
provider_mock_mod = load_module("plugins.yangyang.core.model.provider_mock", PLUGIN_ROOT / "core" / "model" / "provider_mock.py")
router_mod = load_module("plugins.yangyang.core.model_router", PLUGIN_ROOT / "core" / "model_router.py")
light_mod = load_module("plugins.yangyang.core.owner_toolbox_light", PLUGIN_ROOT / "core" / "owner_toolbox_light.py")

MockProvider = provider_mock_mod.MockProvider
ModelRouter = router_mod.ModelRouter
execute_owner_toolbox_tool = light_mod.execute_owner_toolbox_tool
handle_owner_toolbox_light_message = light_mod.handle_owner_toolbox_light_message
handle_owner_toolbox_light_llm_message = light_mod.handle_owner_toolbox_light_llm_message

OWNER_UID = "335059272"


def _cfg(tmp_path: Path) -> DictConfig:
    return DictConfig(
        {
            "owner_uid": OWNER_UID,
            "owner_uids": [OWNER_UID],
            "owner_toolbox_light_workspace_root": str(tmp_path),
            "owner_toolbox_light_timeout_seconds": 5,
            "owner_toolbox_light_max_output_chars": 4000,
            "owner_toolbox_light_native_loop_enabled": True,
            "owner_toolbox_light_plan_only_gate_enabled": False,
            "token_usage_log_path": str(tmp_path / "logs" / "token_usage.jsonl"),
            "models": {"v4_flash": {"enabled": True, "model": "mock-model"}},
            "providers": {"v4_flash": {"enabled": True, "provider": "mock", "model": "mock-model", "timeout": 5, "cooldown_on_fail": 1}},
            "dry_run": False,
        }
    )


def _msg(text: str, *, uid: str = OWNER_UID, channel: str = "private"):
    return SimpleNamespace(
        text=text,
        raw_content=text,
        uid=uid,
        user_id=uid,
        channel=channel,
        group_id="137918147" if channel == "group" else "",
        is_owner=uid == OWNER_UID,
    )


def _run(coro):
    return asyncio.run(coro)



def test_token_usage_default_root_follows_module_location_not_legacy_opt() -> None:
    token_mod = __import__("plugins.yangyang.core.token_usage", fromlist=["resolve_token_usage_log_path"])

    path = token_mod.resolve_token_usage_log_path({"token_usage_log_path": "logs/token_usage.jsonl"})
    expected = Path(token_mod.__file__).resolve().parents[4] / "logs" / "token_usage.jsonl"

    assert path == expected
    assert path.as_posix() != "/opt/yangyang_nonebot/logs/token_usage.jsonl"



def test_hourly_push_formatter_falls_back_to_today_when_recent_window_empty() -> None:
    token_mod = __import__("plugins.yangyang.core.token_usage", fromlist=["TokenUsageSummary", "format_token_usage_push_summary"])
    recent = token_mod.TokenUsageSummary(available=False, reason="no_matching_usage", period="last_1h", group_by="model")
    today = token_mod.TokenUsageSummary(
        available=True,
        total_calls=2,
        prompt_tokens=100,
        completion_tokens=20,
        total_tokens=120,
        last_model="deepseek-v4-flash",
        last_tier="v4_flash",
        group_by="model",
        by_model={"deepseek-v4-flash（v4_flash）": {"calls": 2, "prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120}},
    )

    text = token_mod.format_token_usage_push_summary(recent, hours=1, today=today, group_by="model")

    assert "最近 1 小时没有新增模型调用" in text
    assert "今日累计 Token 用量：共 120 tokens" in text
    assert "按模型：" in text
    assert "没有可用的 token 统计记录" not in text


def test_model_router_records_token_usage_jsonl(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    router = ModelRouter(cfg)
    router.register_provider(MockProvider(response_text="ok", token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}))

    text, tier = _run(router.call("v4_flash", [{"role": "user", "content": "hi"}], session_id="private:335059272", channel="private"))

    assert text == "ok"
    assert tier == "v4_flash"
    path = tmp_path / "logs" / "token_usage.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert rows[-1]["session_id"] == "private:335059272"
    assert rows[-1]["total_tokens"] == 15
    assert rows[-1]["model"] == "mock-model"


def test_query_token_usage_tool_summarizes_current_session(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    log = tmp_path / "logs" / "token_usage.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(
        "\n".join(
            [
                json.dumps({"ts": "2026-06-10T00:00:00+00:00", "session_id": "private:335059272", "prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7, "model": "m1", "tier": "v4_flash"}),
                json.dumps({"ts": "2026-06-10T00:01:00+00:00", "session_id": "group:1", "prompt_tokens": 100, "completion_tokens": 100, "total_tokens": 200, "model": "m2", "tier": "v4_flash"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = execute_owner_toolbox_tool("query_token_usage", {"_session_id": "private:335059272"}, cfg, project_root=tmp_path)

    assert result.allowed is True
    assert result.tool_name == "query_token_usage"
    assert result.data["total_tokens"] == 7
    assert "共 7 tokens" in result.reply
    assert str(tmp_path) not in result.reply


def test_token_slash_owner_private_queries_current_session(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    log = tmp_path / "logs" / "token_usage.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps({"ts": "2026-06-10T00:00:00+00:00", "session_id": "private:335059272", "prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10}) + "\n", encoding="utf-8")

    result = _run(handle_owner_toolbox_light_message(_msg("/token"), cfg, project_root=tmp_path))

    assert result.handled is True
    assert result.tool_name == "query_token_usage"
    assert "共 10 tokens" in result.reply


def test_token_slash_non_owner_rejected(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    result = _run(handle_owner_toolbox_light_message(_msg("/token", uid="123"), cfg, project_root=tmp_path))
    assert result.handled is False
    assert result.reason == "not_owner_private"


def test_llm_soft_token_query_calls_native_tool(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    log = tmp_path / "logs" / "token_usage.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(json.dumps({"ts": "2026-06-10T00:00:00+00:00", "session_id": "private:335059272", "prompt_tokens": 20, "completion_tokens": 6, "total_tokens": 26}) + "\n", encoding="utf-8")
    router = ModelRouter(cfg)
    router.register_provider(
        MockProvider(
            responses=[
                {"content": "", "tool_calls": [{"id": "tok", "name": "query_token_usage", "arguments": {}}]},
                "token 查完了。",
            ]
        )
    )

    result = _run(handle_owner_toolbox_light_llm_message(_msg("看下现在 token 花了多少"), cfg, model_router=router, project_root=tmp_path, session_id="private:335059272"))

    assert result.handled is True
    assert result.tool_name == "query_token_usage"
    assert result.raw_trace[0]["tool_name"] == "query_token_usage"
    assert "token 查完了" in result.reply



def test_query_token_usage_groups_by_model_day_month_and_period(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    log = tmp_path / "logs" / "token_usage.jsonl"
    log.parent.mkdir(parents=True)
    log.write_text(
        "\n".join(
            [
                json.dumps({"ts": "2026-06-10T00:00:00+00:00", "session_id": "private:335059272", "prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12, "model": "deepseek-v4-flash", "tier": "v4_flash"}),
                json.dumps({"ts": "2026-06-10T01:00:00+00:00", "session_id": "private:335059272", "prompt_tokens": 20, "completion_tokens": 3, "total_tokens": 23, "model": "gpt-5.5", "tier": "gpt_5_5"}),
                json.dumps({"ts": "2026-06-11T01:00:00+00:00", "session_id": "private:335059272", "prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2, "model": "gpt-5.5", "tier": "gpt_5_5"}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    result = execute_owner_toolbox_tool("query_token_usage", {"_session_id": "private:335059272", "group_by": "all"}, cfg, project_root=tmp_path)

    assert result.allowed is True
    assert result.data["total_tokens"] == 37
    assert result.data["by_model"]["gpt-5.5（gpt_5_5）"]["total_tokens"] == 25
    assert "按模型：" in result.reply
    assert "按小时：" in result.reply
    assert "按天：" in result.reply
    assert "按月：" in result.reply


def test_token_slash_today_model_adds_period_and_group(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    log = tmp_path / "logs" / "token_usage.jsonl"
    log.parent.mkdir(parents=True)
    # Use current UTC timestamp so today's CST cutoff always includes it.
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).isoformat()
    log.write_text(json.dumps({"ts": now, "session_id": "private:335059272", "prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10, "model": "deepseek-v4-flash", "tier": "v4_flash"}) + "\n", encoding="utf-8")

    result = _run(handle_owner_toolbox_light_message(_msg("/token today model"), cfg, project_root=tmp_path))

    assert result.handled is True
    assert result.tool_name == "query_token_usage"
    assert result.data["period"] == "today"
    assert result.data["group_by"] == "model"
    assert "今日 当前会话 Token 用量" in result.reply
    assert "按模型：" in result.reply



def test_model_router_tool_loop_emits_progress_events(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    router = ModelRouter(cfg)
    router.register_provider(
        MockProvider(
            responses=[
                {"content": "", "tool_calls": [{"id": "c1", "name": "query_token_usage", "arguments": {}}]},
                "done",
            ],
            token_usage={"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        )
    )
    events = []

    async def cb(event, payload):
        events.append((event, dict(payload)))

    def executor(name, args):
        return execute_owner_toolbox_tool(name, {"_session_id": "private:335059272"}, cfg, project_root=tmp_path)

    text, tier, trace = _run(
        router.call_with_tool_loop(
            "v4_flash",
            [{"role": "user", "content": "查 token"}],
            tools=[{"name": "query_token_usage", "parameters": {"type": "object", "properties": {}}}],
            tool_executor=executor,
            session_id="private:335059272",
            channel="private",
            progress_callback=cb,
            run_id="run-test",
        )
    )

    assert text == "done"
    assert trace and trace[0]["tool_name"] == "query_token_usage"
    event_names = [item[0] for item in events]
    assert "run_start" in event_names
    assert "llm_response" in event_names
    assert "tool_start" in event_names
    assert "tool_done" in event_names
    assert "run_done" in event_names
    assert all(item[1].get("run_id") == "run-test" for item in events)
