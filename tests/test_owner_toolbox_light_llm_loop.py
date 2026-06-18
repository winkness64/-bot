from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

from mock_pipeline_runtime import DictConfig, install_nonebot_stubs, ensure_package, load_module  # type: ignore
from mock_pipeline_runtime import SRC_ROOT, PLUGIN_ROOT  # type: ignore

install_nonebot_stubs()
ensure_package("plugins", SRC_ROOT / "plugins")
ensure_package("plugins.yangyang", PLUGIN_ROOT)
ensure_package("plugins.yangyang.core", PLUGIN_ROOT / "core")
ensure_package("plugins.yangyang.core.model", PLUGIN_ROOT / "core" / "model")

load_module("plugins.yangyang.core.model.provider_base", PLUGIN_ROOT / "core" / "model" / "provider_base.py")
load_module("plugins.yangyang.core.model.provider_deepseek", PLUGIN_ROOT / "core" / "model" / "provider_deepseek.py")
load_module("plugins.yangyang.core.model.provider_minimax", PLUGIN_ROOT / "core" / "model" / "provider_minimax.py")
provider_mock_mod = load_module("plugins.yangyang.core.model.provider_mock", PLUGIN_ROOT / "core" / "model" / "provider_mock.py")
router_mod = load_module("plugins.yangyang.core.model_router", PLUGIN_ROOT / "core" / "model_router.py")
light_mod = load_module("plugins.yangyang.core.owner_toolbox_light", PLUGIN_ROOT / "core" / "owner_toolbox_light.py")

MockProvider = provider_mock_mod.MockProvider
ModelRouter = router_mod.ModelRouter
handle_owner_toolbox_light_llm_message = light_mod.handle_owner_toolbox_light_llm_message
handle_owner_toolbox_light_message = light_mod.handle_owner_toolbox_light_message
build_owner_toolbox_tools = light_mod.build_owner_toolbox_tools
execute_owner_toolbox_tool = light_mod.execute_owner_toolbox_tool
get_owner_tool_loop_max_steps = light_mod.get_owner_tool_loop_max_steps
prepare_owner_tool_loop_messages = light_mod.prepare_owner_tool_loop_messages

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
            "models": {"v4_flash": {"enabled": True, "model": "mock-model"}},
            "providers": {"v4_flash": {"enabled": True, "provider": "mock", "model": "mock-model", "timeout": 5, "cooldown_on_fail": 1}},
            "dry_run": False,
        }
    )


def _msg(text: str, *, uid: str = OWNER_UID, channel: str = "private", is_owner: bool | None = None):
    return SimpleNamespace(
        text=text,
        raw_content=text,
        uid=uid,
        user_id=uid,
        channel=channel,
        group_id="137918147" if channel == "group" else "",
        is_owner=(uid == OWNER_UID if is_owner is None else is_owner),
    )


def _router(cfg, responses):
    router = ModelRouter(cfg)
    router.register_provider(MockProvider(responses=responses))
    return router


def _run(coro):
    return asyncio.run(coro)


def test_owner_private_natural_list_tmp_tool_loop_human_reply(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()
    cfg = _cfg(tmp_path)
    router = _router(
        cfg,
        [
            {"content": "", "tool_calls": [{"id": "call_1", "name": "list", "arguments": {"path": "tmp"}}]},
            "tmp 目录是空的。",
        ],
    )
    result = _run(handle_owner_toolbox_light_llm_message(_msg("帮我看一下 tmp 目录有什么"), cfg, model_router=router, project_root=tmp_path))
    assert result.handled is True
    assert result.reason == "ok"
    assert "tmp" in result.reply and "空" in result.reply
    assert "tool_call" not in result.reply
    assert "tool_name" not in result.reply
    assert len(router.providers["mock"].calls) == 2
    assert router.providers["mock"].calls[0]["tools"]


def test_owner_private_python_math_can_be_direct_answer_without_tool(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    router = _router(cfg, ["1+1=2。"])
    result = _run(handle_owner_toolbox_light_llm_message(_msg("用 python 算一下 1+1"), cfg, model_router=router, project_root=tmp_path))
    assert result.handled is True
    assert result.reason == "no_tool_call"
    assert "2" in result.reply
    assert "stdout" not in result.reply.lower()
    assert len(router.providers["mock"].calls) == 1


def test_owner_private_plain_restart_no_tool_call_chat(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    router = _router(cfg, ["那今天先让电脑缓口气，别再折腾它了。"])
    result = _run(handle_owner_toolbox_light_llm_message(_msg("我今天重启了电脑"), cfg, model_router=router, project_root=tmp_path))
    assert result.handled is True
    assert result.reason == "no_tool_call"
    assert result.raw_trace in (None, [])
    assert len(router.providers["mock"].calls) == 1
    assert router.providers["mock"].calls[0]["tools"]


def test_fake_multi_step_model_outage_diagnosis_loop(tmp_path: Path) -> None:
    (tmp_path / "logs").mkdir()
    (tmp_path / "config").mkdir()
    (tmp_path / "logs" / "model.log").write_text(
        "2026-06-09 08:00:00 provider=v4_flash error=model_not_found model=disabled-model\n",
        encoding="utf-8",
    )
    (tmp_path / "config" / "model.json").write_text(
        '{"providers":{"v4_flash":{"model":"disabled-model"}}}',
        encoding="utf-8",
    )
    cfg = _cfg(tmp_path)
    cfg.data["owner_toolbox_light_native_loop_max_steps"] = 5
    router = _router(
        cfg,
        [
            {
                "content": "我先看状态和日志。",
                "tool_calls": [
                    {"id": "call_status", "name": "status", "arguments": {}},
                    {"id": "call_log", "name": "log_tail", "arguments": {"path": "logs/model.log", "lines": 20}},
                ],
            },
            {
                "content": "日志指向模型名问题，我再看配置。",
                "tool_calls": [
                    {"id": "call_config", "name": "read", "arguments": {"path": "config/model.json", "start_line": 1, "lines": 20}},
                ],
            },
            "我先看了状态和日志，又查了配置：日志里 disabled-model 报 model_not_found，配置也正指向 disabled-model，所以模型不可用是模型名或供应商配置不匹配。先把 v4_flash 改回可用模型再重试。",
        ],
    )

    result = _run(handle_owner_toolbox_light_llm_message(_msg("某个模型不能用了，你给我排查下"), cfg, model_router=router, project_root=tmp_path))

    assert result.handled is True
    assert result.allowed is True
    assert result.reason == "ok"
    assert len(result.raw_trace or []) == 3
    assert [item["tool_name"] for item in result.raw_trace or []] == ["status", "log_tail", "read"]
    assert len(router.providers["mock"].calls) == 3

    second_call_messages = router.providers["mock"].calls[1]["messages"]
    assert sum(1 for item in second_call_messages if item.get("role") == "tool") == 2
    assert any("model_not_found" in str(item.get("content")) for item in second_call_messages if item.get("role") == "tool")

    final_call_messages = router.providers["mock"].calls[2]["messages"]
    assert any("disabled-model" in str(item.get("content")) for item in final_call_messages if item.get("role") == "tool")
    assert "我先看了状态和日志" in result.reply
    assert "model_not_found" in result.reply
    assert "tool_call" not in result.reply
    assert "tool_name" not in result.reply
    assert "JSON" not in result.reply


def test_slash_shell_pwd_still_uses_light_executor(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    result = _run(handle_owner_toolbox_light_message(_msg("/toolbox shell pwd"), cfg, project_root=tmp_path))
    assert result.handled is True
    assert result.tool_name == "shell"
    assert str(tmp_path) in result.reply


def test_group_and_non_owner_do_not_inject_tools_or_execute(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    router = _router(cfg, ["不该调用"])
    group = _run(handle_owner_toolbox_light_llm_message(_msg("帮我看一下 tmp 目录有什么", channel="group"), cfg, model_router=router, project_root=tmp_path))
    non_owner = _run(handle_owner_toolbox_light_llm_message(_msg("帮我看一下 tmp 目录有什么", uid="10086", is_owner=False), cfg, model_router=router, project_root=tmp_path))
    assert group.handled is False and group.reason == "not_owner_private"
    assert non_owner.handled is False and non_owner.reason == "not_owner_private"
    assert router.providers["mock"].calls == []


def test_raw_debug_request_shows_tool_details_only_when_explicit(tmp_path: Path) -> None:
    (tmp_path / "tmp").mkdir()
    cfg = _cfg(tmp_path)
    router = _router(
        cfg,
        [
            {"content": "", "tool_calls": [{"id": "call_1", "name": "list", "arguments": {"path": "tmp"}}]},
            "整理完了。",
        ],
    )
    result = _run(handle_owner_toolbox_light_llm_message(_msg("debug raw 帮我看一下 tmp 目录有什么"), cfg, model_router=router, project_root=tmp_path))
    assert result.handled is True
    assert "raw_trace" in result.reply
    assert "tool_name" in result.reply
    assert "list" in result.reply

def test_systemd_service_log_request_prompt_prefers_shell_journalctl(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    messages = prepare_owner_tool_loop_messages([
        {"role": "system", "content": "base"},
        {"role": "user", "content": "看一下 yangyang-nonebot 最近 50 行日志，不用发我全部，总结一下就行"},
    ])
    prompt_blob = "\n".join(str(item.get("content", "")) for item in messages)
    assert "journalctl -u yangyang-nonebot -n 50 --no-pager" in prompt_blob
    assert "不要把服务名当文件路径交给 log_tail" in prompt_blob
    assert "不要原样贴满日志" in prompt_blob

    tools_blob = "\n".join(str(tool.get("description", "")) for tool in build_owner_toolbox_tools())
    assert "journalctl" in tools_blob and "systemctl status" in tools_blob
    assert "log_tail only" in tools_blob or "Use log_tail only" in tools_blob


def test_max_steps_default_read_from_runtime_config_default(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    assert get_owner_tool_loop_max_steps(cfg) == 5


def test_max_steps_runtime_config_override_drives_router_loop(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.data["owner_toolbox_light_native_loop_max_steps"] = 1000000
    router = _router(
        cfg,
        [
            {"content": "step1", "tool_calls": [{"id": "c1", "name": "list", "arguments": {"path": "."}}]},
            {"content": "step2", "tool_calls": [{"id": "c2", "name": "read", "arguments": {"path": "missing.txt"}}]},
            {"content": "step3", "tool_calls": [{"id": "c3", "name": "status", "arguments": {}}]},
            "三步排完了。",
        ],
    )
    result = _run(handle_owner_toolbox_light_llm_message(_msg("连续排查三步"), cfg, model_router=router, project_root=tmp_path))
    assert result.handled is True
    assert len(result.raw_trace or []) == 3
    assert len(router.providers["mock"].calls) == 4
    assert router.last_tool_loop_max_steps == 1000000


def test_model_router_uses_runtime_config_1000000_without_30_clamp(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.data["owner_toolbox_light_native_loop_max_steps"] = 1000000
    responses = [
        {"content": f"step{i}", "tool_calls": [{"id": f"c{i}", "name": "status", "arguments": {"i": i}}]}
        for i in range(35)
    ] + ["超过 30 步后结束。"]
    router = _router(cfg, responses)
    response, _tier, trace = _run(
        router.call_with_tool_loop(
            "v4_flash",
            [{"role": "user", "content": "跑超过三十步"}],
            tools=build_owner_toolbox_tools(),
            tool_executor=lambda name, args: {"handled": True, "allowed": True, "reason": "ok", "tool_name": name, "data": args},
            max_steps=None,
        )
    )
    assert response == "超过 30 步后结束。"
    assert len(trace) == 35
    assert len(router.providers["mock"].calls) == 36
    assert router.last_tool_loop_max_steps == 1000000


def test_max_steps_tools_schema_contains_get_set() -> None:
    tools = {item["name"]: item for item in build_owner_toolbox_tools()}
    assert "get_tool_loop_max_steps" in tools
    assert "set_tool_loop_max_steps" in tools
    assert tools["get_tool_loop_max_steps"]["parameters"]["properties"] == {}
    set_params = tools["set_tool_loop_max_steps"]["parameters"]
    assert set_params["required"] == ["value"]
    assert "value" in set_params["properties"]




def test_slash_max_steps_1000000_fallback(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    result = _run(handle_owner_toolbox_light_message(_msg("/toolbox max_steps 1000000"), cfg, project_root=tmp_path))
    assert result.handled is True and result.allowed is True
    assert result.tool_name == "set_tool_loop_max_steps"
    assert result.data["max_steps"] == 1000000
    assert cfg.get("owner_toolbox_light_native_loop_max_steps") == 1000000

    negative = _run(handle_owner_toolbox_light_message(_msg("/toolbox max_steps -7"), cfg, project_root=tmp_path))
    assert negative.handled is True and negative.allowed is True
    assert negative.tool_name == "set_tool_loop_max_steps"
    assert negative.data["max_steps"] == 1
    assert cfg.get("owner_toolbox_light_native_loop_max_steps") == 1
def test_max_steps_execute_get_set_roundtrip_1000000(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    set_result = execute_owner_toolbox_tool("set_tool_loop_max_steps", {"value": "1000000"}, cfg, project_root=tmp_path)
    assert set_result.handled is True and set_result.allowed is True
    assert set_result.tool_name == "set_tool_loop_max_steps"
    assert set_result.data["max_steps"] == 1000000
    assert cfg.get("owner_toolbox_light_native_loop_max_steps") == 1000000

    get_result = execute_owner_toolbox_tool("get_tool_loop_max_steps", {}, cfg, project_root=tmp_path)
    assert get_result.handled is True and get_result.allowed is True
    assert get_result.tool_name == "get_tool_loop_max_steps"
    assert get_result.data["max_steps"] == 1000000
    assert get_result.reply == "1000000"


def test_max_steps_owner_private_natural_query_uses_llm_tool_call(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.data["owner_toolbox_light_native_loop_max_steps"] = 12
    router = _router(
        cfg,
        [
            {"content": "", "tool_calls": [{"id": "get_max_steps", "name": "get_tool_loop_max_steps", "arguments": {}}]},
            "现在是 12 步。",
        ],
    )
    result = _run(handle_owner_toolbox_light_llm_message(_msg("当前工具调用上限是多少"), cfg, model_router=router, project_root=tmp_path))
    assert result.handled is True and result.tool_name == "get_tool_loop_max_steps"
    assert "12" in result.reply
    assert len(result.raw_trace or []) == 1
    assert len(router.providers["mock"].calls) == 2
    assert any(tool["name"] == "get_tool_loop_max_steps" for tool in build_owner_toolbox_tools())


def test_max_steps_owner_private_natural_set_uses_llm_tool_call(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    router = _router(
        cfg,
        [
            {"content": "", "tool_calls": [{"id": "set_max_steps", "name": "set_tool_loop_max_steps", "arguments": {"value": "1000000"}}]},
            "已经按你说的改成 1000000 步。",
            {"content": "", "tool_calls": [{"id": "get_max_steps", "name": "get_tool_loop_max_steps", "arguments": {}}]},
            "当前就是 1000000 步。",
            {"content": "", "tool_calls": [{"id": "set_max_steps_2", "name": "set_tool_loop_max_steps", "arguments": {"value": 999999}}]},
            "改成 999999 步了。",
        ],
    )
    result = _run(handle_owner_toolbox_light_llm_message(_msg("把我们工具次数设为 1000000"), cfg, model_router=router, project_root=tmp_path))
    assert result.handled is True and result.tool_name == "set_tool_loop_max_steps"
    assert "1000000" in result.reply
    assert cfg.get("owner_toolbox_light_native_loop_max_steps") == 1000000
    assert get_owner_tool_loop_max_steps(cfg) == 1000000

    query = _run(handle_owner_toolbox_light_llm_message(_msg("当前工具调用上限是多少"), cfg, model_router=router, project_root=tmp_path))
    assert query.handled is True and query.tool_name == "get_tool_loop_max_steps"
    assert "1000000" in query.reply

    result2 = _run(handle_owner_toolbox_light_llm_message(_msg("工具调用上限改成 999999"), cfg, model_router=router, project_root=tmp_path))
    assert result2.handled is True and result2.tool_name == "set_tool_loop_max_steps"
    assert "999999" in result2.reply
    assert cfg.get("owner_toolbox_light_native_loop_max_steps") == 999999
    assert len(router.providers["mock"].calls) == 6


def test_max_steps_natural_language_is_not_slash_parser(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    router = _router(cfg, ["模型认为不用调工具，直接聊天。"])
    result = _run(handle_owner_toolbox_light_llm_message(_msg("把我们工具次数设为 1000000"), cfg, model_router=router, project_root=tmp_path))
    assert result.handled is True
    assert result.reason == "no_tool_call"
    assert cfg.get("owner_toolbox_light_native_loop_max_steps", 5) == 5
    assert len(router.providers["mock"].calls) == 1

def test_max_steps_group_and_non_owner_natural_config_not_handled(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    router = _router(cfg, ["不该调用"])
    group = _run(handle_owner_toolbox_light_llm_message(_msg("当前工具调用上限是多少", channel="group"), cfg, model_router=router, project_root=tmp_path))
    non_owner = _run(handle_owner_toolbox_light_llm_message(_msg("把工具调用上限改成 15", uid="10086", is_owner=False), cfg, model_router=router, project_root=tmp_path))
    assert group.handled is False and group.reason == "not_owner_private"
    assert non_owner.handled is False and non_owner.reason == "not_owner_private"
    assert cfg.get("owner_toolbox_light_native_loop_max_steps", 5) == 5
    assert router.providers["mock"].calls == []


def test_write_like_request_without_successful_write_tool_cannot_claim_done(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    router = _router(cfg, ["搞定啦～已经在冷备份那个 `永久记忆库.txt` 的事件类里加上了。"])
    result = _run(handle_owner_toolbox_light_llm_message(_msg("在冷备份那个txt里面加一行 娅娅给我们优化了工具箱"), cfg, model_router=router, project_root=tmp_path))
    assert result.handled is True
    assert result.reason == "no_tool_call"
    assert "没看到写入工具成功" in result.reply
    assert "搞定" not in result.reply
    assert "加上" not in result.reply


def test_write_like_request_with_successful_write_tool_can_claim_done(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    router = _router(
        cfg,
        [
            {"content": "", "tool_calls": [{"id": "call_write", "name": "write", "arguments": {"path": "tmp/write_guard.txt", "content": "ok"}}]},
            "写好了。",
        ],
    )
    result = _run(handle_owner_toolbox_light_llm_message(_msg("在 tmp/write_guard.txt 里面写一行 ok"), cfg, model_router=router, project_root=tmp_path))
    assert result.handled is True
    assert result.reason == "ok"
    assert "写好了" in result.reply
    assert (tmp_path / "tmp" / "write_guard.txt").read_text(encoding="utf-8") == "ok"



def test_model_profile_list_trace_reply_uses_real_profiles_not_model_memory(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.data["providers"].update(
        {
            "v4_pro": {"enabled": True, "provider": "mock", "model": "deepseek-v4-pro", "timeout": 5, "cooldown_on_fail": 1},
            "gpt_5_4": {"enabled": False, "provider": "mock", "model": "gpt-5.4", "timeout": 5, "cooldown_on_fail": 1},
            "promo_gpt_5_4": {"enabled": False, "provider": "mock", "model": "gpt-5.4", "timeout": 5, "cooldown_on_fail": 1, "profile_prefix": "promo"},
            "gemini_3_1_pro_high": {"enabled": False, "provider": "mock", "model": "gemini-3.1-pro-high", "timeout": 5, "cooldown_on_fail": 1},
        }
    )
    router = _router(
        cfg,
        [
            {"content": "", "tool_calls": [{"id": "call_models", "name": "list_model_profiles", "arguments": {"scope": "current", "include_disabled": True}}]},
            "好嘞~ 全量列表来啦，但是我只想贴旧六个。",
        ],
    )
    result = _run(handle_owner_toolbox_light_llm_message(_msg("全量模型列表"), cfg, model_router=router, project_root=tmp_path))
    assert result.handled is True
    assert result.reason == "ok"
    assert "真实模型列表" in result.reply
    assert "promo_gpt_5_4" in result.reply
    assert "gemini_3_1_pro_high" in result.reply
    assert "minimax_m3" in result.reply
    assert "只想贴旧六个" not in result.reply


def test_minimax_m3_builtin_catalog_disabled_default_does_not_change_active(tmp_path: Path) -> None:
    """The new m3 builtin entry must appear in the catalog but stay disabled,
    and must NOT silently change the active private/group profile."""
    from plugins.yangyang.core import model_profile_switcher as switcher
    from plugins.yangyang.admin.runtime_config import DEFAULTS

    cfg = _cfg(tmp_path)
    cfg.data.update(json.loads(json.dumps(DEFAULTS)))
    # m3 should be discoverable
    descriptor = switcher.get_model_profile_descriptor(cfg, "minimax_m3")
    assert descriptor["exists"] is True
    assert descriptor["provider"] == "anthropic_compat"
    assert descriptor["model"] == "MiniMax-M3"
    assert descriptor["enabled"] is False
    # active must still be v4_flash after touching the catalog
    assert cfg.get("model_profile_switcher.active_profile_private") == "v4_flash"
    assert cfg.get("model_profile_switcher.active_profile_group") == "v4_flash"
    # enabling m3 must NOT auto-switch active
    enable = switcher.set_model_profile_enabled(cfg, profile_id="minimax_m3", enabled=True)
    assert enable["ok"] is True
    assert cfg.get("model_profile_switcher.active_profile_private") == "v4_flash"
    assert cfg.get("model_profile_switcher.active_profile_group") == "v4_flash"
    # explicit switch via scope=private should land on m3 only when owner says so
    switched = switcher.set_active_model_profile(cfg, profile_id="minimax_m3", scope="private")
    assert switched["ok"] is True
    assert cfg.get("model_profile_switcher.active_profile_private") == "minimax_m3"
    assert cfg.get("model_profile_switcher.active_profile_group") == "v4_flash"
    # refresh must NOT try to overwrite the anthropic_compat profile via /models
    # The provider exposes no /models endpoint so refresh returns "unsupported".
    # The important property: no new fake profile was created from /models.
    router = ModelRouter(cfg)
    refresh = _run(router.refresh_model_profiles(provider_profile_id="minimax_m3", timeout_seconds=1))
    assert refresh.get("ok") in (True, False)
    failed_ids = {item.get("provider_profile_id") for item in refresh.get("failed", [])}
    # If unsupported, m3 must be in the failed list (not silently skipped).
    # If it succeeded, the catalog must be unchanged because anthropic_compat
    # has no /models endpoint to read.
    if refresh.get("ok") is False:
        assert "minimax_m3" in failed_ids
    # No new entries should have been auto-created for anthropic_compat.
    descriptor_after = switcher.get_model_profile_descriptor(cfg, "minimax_m3")
    assert descriptor_after["model"] == "MiniMax-M3"



def test_model_profile_list_request_directly_uses_tool_even_if_model_would_hallucinate(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.data["providers"]["promo_gpt_5_4"] = {
        "enabled": False,
        "provider": "mock",
        "model": "gpt-5.4",
        "timeout": 5,
        "cooldown_on_fail": 1,
        "profile_prefix": "promo",
    }
    router = _router(cfg, ["好嘞，我凭记忆列旧六个。"])
    result = _run(handle_owner_toolbox_light_llm_message(_msg("全量模型列表"), cfg, model_router=router, project_root=tmp_path))
    assert result.handled is True
    assert result.tool_name == "list_model_profiles"
    assert "promo_gpt_5_4" in result.reply
    assert "凭记忆" not in result.reply
    assert len(router.providers["mock"].calls) == 0



def test_available_model_profile_list_shows_enabled_only_even_if_model_would_request_disabled(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.data["providers"].update(
        {
            "v4_pro": {"enabled": True, "provider": "mock", "model": "deepseek-v4-pro", "timeout": 5, "cooldown_on_fail": 1},
            "gpt_5_5": {"enabled": True, "provider": "mock", "model": "gpt-5.5", "timeout": 5, "cooldown_on_fail": 1},
            "gemini_3_1_pro_high": {"enabled": True, "provider": "mock", "model": "gemini-3.1-pro-high", "timeout": 5, "cooldown_on_fail": 1},
            "promo_gpt_5_4": {"enabled": False, "provider": "mock", "model": "gpt-5.4", "timeout": 5, "cooldown_on_fail": 1, "profile_prefix": "promo"},
        }
    )
    router = _router(
        cfg,
        [
            {"content": "", "tool_calls": [{"id": "call_models", "name": "list_model_profiles", "arguments": {"scope": "current", "include_disabled": True}}]},
            "我想把禁用也贴出来。",
        ],
    )
    result = _run(handle_owner_toolbox_light_llm_message(_msg("查看可用模型"), cfg, model_router=router, project_root=tmp_path))

    assert result.handled is True
    assert result.tool_name == "list_model_profiles"
    assert "gpt_5_5" in result.reply
    assert "gemini_3_1_pro_high" in result.reply
    assert "promo_gpt_5_4" not in result.reply
    assert "我想把禁用也贴出来" not in result.reply
    trace = result.raw_trace[0]
    assert trace["args"]["include_disabled"] is False



def test_available_model_profile_render_filters_disabled_profiles_from_full_tool_data(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    cfg.data["providers"].update(
        {
            "v4_pro": {"enabled": True, "provider": "mock", "model": "deepseek-v4-pro", "timeout": 5, "cooldown_on_fail": 1},
            "gpt_5_4": {"enabled": True, "provider": "mock", "model": "gpt-5.4", "timeout": 5, "cooldown_on_fail": 1},
            "disabled_x": {"enabled": False, "provider": "mock", "model": "disabled-model", "timeout": 5, "cooldown_on_fail": 1},
        }
    )
    router = _router(
        cfg,
        [
            {"content": "", "tool_calls": [{"id": "call_models", "name": "list_model_profiles", "arguments": {"scope": "current", "include_disabled": True}}]},
            "我又想糊全量。",
        ],
    )
    result = _run(handle_owner_toolbox_light_llm_message(_msg("查看可用模型"), cfg, model_router=router, project_root=tmp_path))

    assert result.handled is True
    assert "真实可用模型" in result.reply
    assert "gpt_5_4" in result.reply
    assert "v4_pro" in result.reply
    assert "disabled_x" not in result.reply
    assert "disabled-model" not in result.reply
    assert "禁用 0 个" in result.reply


def test_model_router_emits_assistant_prelude_for_content_with_tool_calls(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    router = _router(
        cfg,
        [
            {"content": "我先看一下真实目录。", "tool_calls": [{"id": "call_1", "name": "list", "arguments": {"path": "."}}]},
            "看完了。",
        ],
    )
    events: list[tuple[str, dict]] = []

    async def progress(event_name, payload):
        events.append((event_name, dict(payload or {})))

    response, _tier, trace = _run(
        router.call_with_tool_loop(
            "v4_flash",
            [{"role": "user", "content": "看一下目录"}],
            tools=build_owner_toolbox_tools(),
            tool_executor=lambda name, args: {"handled": True, "allowed": True, "reason": "ok", "tool_name": name, "data": args},
            progress_callback=progress,
            max_steps=5,
        )
    )

    assert response == "看完了。"
    assert len(trace) == 1
    prelude_events = [payload for name, payload in events if name == "assistant_prelude"]
    assert len(prelude_events) == 1
    assert prelude_events[0]["text"] == "我先看一下真实目录。"
    llm_events = [payload for name, payload in events if name == "llm_response"]
    assert llm_events[0]["assistant_content_chars"] == len("我先看一下真实目录。")


def test_owner_private_natural_isaac_can_call_p0_tool_by_model_choice(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    router = _router(
        cfg,
        [
            {"content": "", "tool_calls": [{"id": "call_isaac", "name": "isaac_p0", "arguments": {"command_text": "health"}}]},
            "I叔只读健康检查已完成。",
        ],
    )

    result = _run(handle_owner_toolbox_light_llm_message(_msg("帮我找 I叔 看下状态"), cfg, model_router=router, project_root=tmp_path))

    assert result.handled is True
    assert result.allowed is True
    assert result.reason == "ok"
    assert [item["tool_name"] for item in (result.raw_trace or [])] == ["isaac_p0"]
    assert "I叔只读健康检查已完成" in result.reply


def test_group_natural_isaac_tool_loop_does_not_execute(tmp_path: Path) -> None:
    cfg = _cfg(tmp_path)
    router = _router(
        cfg,
        [{"content": "", "tool_calls": [{"id": "call_isaac", "name": "isaac_p0", "arguments": {"command_text": "health"}}]}],
    )

    result = _run(handle_owner_toolbox_light_llm_message(_msg("帮我找 I叔 看下状态", channel="group"), cfg, model_router=router, project_root=tmp_path))

    assert result.handled is False
    assert result.reason == "not_owner_private"
    assert router.providers["mock"].calls == []
