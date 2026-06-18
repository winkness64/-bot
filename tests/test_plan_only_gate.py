from __future__ import annotations

import asyncio
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
            "owner_toolbox_light_plan_only_gate_enabled": True,
            "models": {"v4_flash": {"enabled": True, "model": "mock-model"}},
            "providers": {"v4_flash": {"enabled": True, "provider": "mock", "model": "mock-model", "timeout": 5, "cooldown_on_fail": 1}},
            "dry_run": False,
        }
    )


def _msg(text, *, uid=OWNER_UID, channel="private", is_owner=None):
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
    router.register_provider(MockProvider(responses=list(responses)))
    return router


def _run(coro):
    return asyncio.run(coro)


# ==== plan_only mode tests ====

def test_plan_only_dont_touch_tool_is_blocked(tmp_path):
    cfg = _cfg(tmp_path)
    router = _router(cfg, ["这个方案的风险主要在三个方面..."])
    result = _run(handle_owner_toolbox_light_llm_message(
        _msg("先不动手，帮我分析一下这个方案的风险"), cfg, model_router=router, project_root=tmp_path
    ))
    assert result.handled is True
    assert result.reason == "plan_only"
    assert result.tool_name is None
    assert result.reply.strip()


def test_plan_only_say_idea_first(tmp_path):
    cfg = _cfg(tmp_path)
    router = _router(cfg, ["我建议分三步走..."])
    result = _run(handle_owner_toolbox_light_llm_message(
        _msg("先说想法，你打算怎么做"), cfg, model_router=router, project_root=tmp_path
    ))
    assert result.handled is True
    assert result.reason == "plan_only"
    assert result.tool_name is None


def test_plan_only_evaluate_first(tmp_path):
    cfg = _cfg(tmp_path)
    router = _router(cfg, ["主要风险有三个..."])
    result = _run(handle_owner_toolbox_light_llm_message(
        _msg("先评估一下这个方案的风险"), cfg, model_router=router, project_root=tmp_path
    ))
    assert result.handled is True
    assert result.reason == "plan_only"


def test_plan_only_what_if(tmp_path):
    cfg = _cfg(tmp_path)
    router = _router(cfg, ["如果我来做，我会这样设计..."])
    result = _run(handle_owner_toolbox_light_llm_message(
        _msg("假如让你做这个插件，你怎么设计"), cfg, model_router=router, project_root=tmp_path
    ))
    assert result.handled is True
    assert result.reason == "plan_only"


def test_plan_only_give_plan(tmp_path):
    cfg = _cfg(tmp_path)
    router = _router(cfg, ["方案如下："])
    result = _run(handle_owner_toolbox_light_llm_message(
        _msg("给个方案，怎么做这个功能"), cfg, model_router=router, project_root=tmp_path
    ))
    assert result.handled is True
    assert result.reason == "plan_only"


def test_plan_only_system_prompt_no_tool_calls(tmp_path):
    cfg = _cfg(tmp_path)
    router = _router(cfg, ["好的，我来分析。"])
    _run(handle_owner_toolbox_light_llm_message(
        _msg("先分析一下有什么坑"), cfg, model_router=router, project_root=tmp_path
    ))
    calls = router.providers["mock"].calls
    assert len(calls) >= 1
    plan_call = calls[0]
    assert plan_call.get("tools") is None or plan_call["tools"] == []


# ==== execute mode tests (gate passes through) ====

def test_execute_list_dir_normal(tmp_path):
    (tmp_path / "tmp").mkdir()
    cfg = _cfg(tmp_path)
    router = _router(
        cfg,
        [
            {"content": "", "tool_calls": [{"id": "c1", "name": "list", "arguments": {"path": "tmp"}}]},
            "tmp 目录是空的。",
        ],
    )
    result = _run(handle_owner_toolbox_light_llm_message(
        _msg("帮我看一下 tmp 目录有什么"), cfg, model_router=router, project_root=tmp_path
    ))
    assert result.handled is True
    assert result.reason in ("ok", "no_tool_call")
    assert "tmp" in result.reply


def test_execute_python_math(tmp_path):
    cfg = _cfg(tmp_path)
    # "用 python 算一下" is ambiguous -> triggers LLM classifier
    # Add "execute" as first response for the classifier
    router = _router(cfg, ["execute", "1+1=2。"])
    result = _run(handle_owner_toolbox_light_llm_message(
        _msg("用 python 算一下 1+1"), cfg, model_router=router, project_root=tmp_path
    ))
    assert result.handled is True
    assert result.reason in ("ok", "no_tool_call")


# ==== config disable test ====

def test_plan_only_gate_config_disabled_still_allows_execute(tmp_path):
    (tmp_path / "tmp").mkdir()
    cfg = _cfg(tmp_path)
    cfg.data["owner_toolbox_light_plan_only_gate_enabled"] = False
    router = _router(
        cfg,
        [
            {"content": "", "tool_calls": [{"id": "c1", "name": "list", "arguments": {"path": "tmp"}}]},
            "tmp 目录是空的。",
        ],
    )
    result = _run(handle_owner_toolbox_light_llm_message(
        _msg("先不动手，帮我看看 tmp 目录"), cfg, model_router=router, project_root=tmp_path
    ))
    assert result.handled is True
    assert result.reason in ("ok", "no_tool_call")


# ==== non-owner / group gate tests ====

def test_group_does_not_trigger_gate(tmp_path):
    cfg = _cfg(tmp_path)
    router = _router(cfg, ["群聊不处理。"])
    result = _run(handle_owner_toolbox_light_llm_message(
        _msg("先不动手，分析一下", channel="group"), cfg, model_router=router, project_root=tmp_path
    ))
    assert result.handled is False
    assert result.reason == "not_owner_private"


def test_non_owner_does_not_trigger_gate(tmp_path):
    cfg = _cfg(tmp_path)
    router = _router(cfg, ["非 owner 不处理。"])
    result = _run(handle_owner_toolbox_light_llm_message(
        _msg("先不动手", uid="10086", is_owner=False), cfg, model_router=router, project_root=tmp_path
    ))
    assert result.handled is False
    assert result.reason == "not_owner_private"
