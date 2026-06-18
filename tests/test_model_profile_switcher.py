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
load_module("plugins.yangyang.core.model_profile_switcher", PLUGIN_ROOT / "core" / "model_profile_switcher.py")
router_mod = load_module("plugins.yangyang.core.model_router", PLUGIN_ROOT / "core" / "model_router.py")
light_mod = load_module("plugins.yangyang.core.owner_toolbox_light", PLUGIN_ROOT / "core" / "owner_toolbox_light.py")

MockProvider = provider_mock_mod.MockProvider
ModelRouter = router_mod.ModelRouter
execute_owner_toolbox_tool = light_mod.execute_owner_toolbox_tool
handle_owner_toolbox_light_llm_message = light_mod.handle_owner_toolbox_light_llm_message
build_owner_toolbox_tools = light_mod.build_owner_toolbox_tools
switcher = __import__("plugins.yangyang.core.model_profile_switcher", fromlist=["*"])


def _run(coro):
    return asyncio.run(coro)


def _cfg() -> DictConfig:
    return DictConfig(
        {
            "owner_uid": "335059272",
            "owner_uids": ["335059272"],
            "owner_toolbox_light_native_loop_enabled": True,
            "owner_toolbox_light_native_loop_max_steps": 5,
            "model_profile_switcher": {
                "active_profile_private": "v4_flash",
                "active_profile_group": "v4_flash",
            },
            "models": {
                "v4_flash": {"enabled": True, "model": "flash-model"},
                "v4_pro": {"enabled": True, "model": "pro-model"},
                "gpt_5_5": {"enabled": False, "model": "gpt-model"},
                "disabled_x": {"enabled": False, "model": "disabled-model"},
            },
            "providers": {
                "v4_flash": {"enabled": True, "provider": "mock", "model": "flash-model", "timeout": 5, "api_key": "SECRET_A", "base_url": "https://secret.example"},
                "v4_pro": {"enabled": True, "provider": "mock", "model": "pro-model", "timeout": 5, "token": "SECRET_B"},
                "gpt_5_5": {"enabled": False, "provider": "mock", "model": "gpt-model", "timeout": 5},
                "disabled_x": {"enabled": False, "provider": "mock", "model": "disabled-model", "timeout": 5},
            },
            "dry_run": False,
        }
    )


def _router(cfg, responses=None):
    router = ModelRouter(cfg)
    router.register_provider(MockProvider(responses=list(responses or ["ok"])))
    return router


def _msg(text: str, *, channel: str = "private"):
    return SimpleNamespace(
        text=text,
        raw_content=text,
        uid="335059272",
        user_id="335059272",
        channel=channel,
        group_id="137918147" if channel == "group" else "",
        is_owner=True,
    )


def _profiles_by_id(result: dict) -> dict[str, dict]:
    return {str(item.get("profile_id")): item for item in result.get("profiles", []) if isinstance(item, dict)}


def test_list_model_profiles_uses_runtime_providers_order_with_stable_index_and_no_secrets() -> None:
    cfg = _cfg()

    result = switcher.list_model_profiles(cfg, scope="current", include_disabled=True, context_channel="private")
    profiles = result["profiles"]
    by_id = _profiles_by_id(result)

    assert [item["profile_id"] for item in profiles[:4]] == ["v4_flash", "v4_pro", "gpt_5_5", "disabled_x"]
    assert [item["index"] for item in profiles] == list(range(len(profiles)))
    assert by_id["v4_flash"]["source"] == "providers"
    assert by_id["v4_pro"]["source"] == "providers"
    assert by_id["v4_flash"]["enabled"] is True
    assert by_id["v4_pro"]["enabled"] is True
    assert by_id["m2_7"]["enabled"] is False
    assert by_id["gpt_5_5"]["enabled"] is False
    blob = str(result)
    for forbidden in ("SECRET_A", "SECRET_B", "base_url", "token", "api_key", "api_key_env"):
        assert forbidden not in blob


def test_runtime_defaults_list_comes_from_providers_and_statuses_are_expected() -> None:
    runtime_mod = load_module("plugins.yangyang.admin.runtime_config", PLUGIN_ROOT / "admin" / "runtime_config.py")
    cfg = DictConfig(runtime_mod.DEFAULTS)

    result = switcher.list_model_profiles(cfg, scope="current", include_disabled=True, context_channel="private")
    profiles = result["profiles"]
    by_id = _profiles_by_id(result)
    provider_ids = list(runtime_mod.DEFAULTS["providers"].keys())

    assert [item["profile_id"] for item in profiles[: len(provider_ids)]] == provider_ids
    assert [item["index"] for item in profiles] == list(range(len(profiles)))
    assert by_id["v4_flash"]["enabled"] is True
    assert by_id["v4_pro"]["enabled"] is True
    assert by_id["m2_7"]["enabled"] is False
    assert by_id["gpt_5_5"]["enabled"] is False


def test_provider_enabled_wins_over_models_disabled_for_profile_switcher() -> None:
    cfg = _cfg()
    cfg.data["models"]["v4_pro"]["enabled"] = False

    descriptor = switcher.get_model_profile_descriptor(cfg, "v4_pro")
    switched = switcher.set_active_model_profile(cfg, profile_id="v4_pro", scope="private")

    assert descriptor["enabled"] is True
    assert switched["ok"] is True
    assert cfg.get("model_profile_switcher.active_profile_private") == "v4_pro"


def test_router_provider_enabled_wins_over_models_disabled() -> None:
    cfg = _cfg()
    cfg.data["models"]["v4_pro"]["enabled"] = False
    switcher.set_active_model_profile(cfg, profile_id="v4_pro", scope="private")
    router = _router(cfg, ["provider priority ok"])

    response, tier = _run(router.call("v4_flash", [{"role": "user", "content": "p"}], channel="private", session_id="private:335059272"))

    assert response == "provider priority ok"
    assert tier == "v4_pro"
    assert router.providers["mock"].calls[-1]["model"] == "pro-model"


def test_selection_index_switch_private_to_v4_pro_group_unchanged() -> None:
    cfg = _cfg()
    idx = _profiles_by_id(switcher.list_model_profiles(cfg, include_disabled=True))["v4_pro"]["index"]

    switched = switcher.set_active_model_profile(cfg, selection_index=idx, scope="private")

    assert switched["ok"] is True
    assert switched["profile_id"] == "v4_pro"
    assert cfg.get("model_profile_switcher.active_profile_private") == "v4_pro"
    assert cfg.get("model_profile_switcher.active_profile_group") == "v4_flash"


def test_selection_index_switch_group_to_v4_pro_private_unchanged() -> None:
    cfg = _cfg()
    idx = _profiles_by_id(switcher.list_model_profiles(cfg, include_disabled=True))["v4_pro"]["index"]

    switched = switcher.set_active_model_profile(cfg, selection_index=idx, scope="group")

    assert switched["ok"] is True
    assert switched["profile_id"] == "v4_pro"
    assert cfg.get("model_profile_switcher.active_profile_private") == "v4_flash"
    assert cfg.get("model_profile_switcher.active_profile_group") == "v4_pro"


def test_invalid_selection_index_does_not_write_any_scope() -> None:
    cfg = _cfg()
    before_private = cfg.get("model_profile_switcher.active_profile_private")
    before_group = cfg.get("model_profile_switcher.active_profile_group")

    switched = switcher.set_active_model_profile(cfg, selection_index=999, scope="private")

    assert switched["ok"] is False
    assert switched["reason"] == "invalid_selection_index"
    assert cfg.get("model_profile_switcher.active_profile_private") == before_private
    assert cfg.get("model_profile_switcher.active_profile_group") == before_group


def test_disabled_selection_index_does_not_write_any_scope() -> None:
    cfg = _cfg()
    idx = _profiles_by_id(switcher.list_model_profiles(cfg, include_disabled=True))["m2_7"]["index"]
    before_private = cfg.get("model_profile_switcher.active_profile_private")
    before_group = cfg.get("model_profile_switcher.active_profile_group")

    switched = switcher.set_active_model_profile(cfg, selection_index=idx, scope="group")

    assert switched["ok"] is False
    assert switched["reason"] == "profile_disabled"
    assert cfg.get("model_profile_switcher.active_profile_private") == before_private
    assert cfg.get("model_profile_switcher.active_profile_group") == before_group


def test_owner_toolbox_set_active_model_profile_accepts_selection_index() -> None:
    cfg = _cfg()
    idx = _profiles_by_id(switcher.list_model_profiles(cfg, include_disabled=True))["v4_pro"]["index"]

    result = execute_owner_toolbox_tool("set_active_model_profile", {"selection_index": idx, "scope": "private"}, cfg)

    assert result.allowed is True
    assert result.data["profile_id"] == "v4_pro"
    assert cfg.get("model_profile_switcher.active_profile_private") == "v4_pro"
    assert cfg.get("model_profile_switcher.active_profile_group") == "v4_flash"


def test_default_private_group_active_profiles_exist() -> None:
    cfg = _cfg()
    assert switcher.get_private_active_profile_id(cfg) == "v4_flash"
    assert switcher.get_group_active_profile_id(cfg) == "v4_flash"


def test_set_private_does_not_change_group_and_set_group_does_not_change_private() -> None:
    cfg = _cfg()
    private = switcher.set_active_model_profile(cfg, profile_id="v4_pro", scope="private", context_channel="private")
    assert private["ok"] is True
    assert cfg.get("model_profile_switcher.active_profile_private") == "v4_pro"
    assert cfg.get("model_profile_switcher.active_profile_group") == "v4_flash"

    group = switcher.set_active_model_profile(cfg, profile_id="v4_pro", scope="group", context_channel="private")
    assert group["ok"] is True
    assert cfg.get("model_profile_switcher.active_profile_private") == "v4_pro"
    assert cfg.get("model_profile_switcher.active_profile_group") == "v4_pro"


def test_router_private_uses_private_profile_group_uses_group_profile() -> None:
    cfg = _cfg()
    switcher.set_active_model_profile(cfg, profile_id="v4_pro", scope="private")
    switcher.set_active_model_profile(cfg, profile_id="v4_flash", scope="group")
    router = _router(cfg, ["private ok", "group ok"])

    private_resp, private_tier = _run(router.call("v4_flash", [{"role": "user", "content": "p"}], channel="private", session_id="private:335059272"))
    assert private_resp == "private ok"
    assert private_tier == "v4_pro"
    assert router.providers["mock"].calls[-1]["model"] == "pro-model"

    group_resp, group_tier = _run(router.call("v4_flash", [{"role": "user", "content": "g"}], channel="group", session_id="group:137918147"))
    assert group_resp == "group ok"
    assert group_tier == "v4_flash"
    assert router.providers["mock"].calls[-1]["model"] == "flash-model"


def test_router_message_context_overrides_session_id_for_scope() -> None:
    cfg = _cfg()
    switcher.set_active_model_profile(cfg, profile_id="v4_pro", scope="private")
    switcher.set_active_model_profile(cfg, profile_id="v4_flash", scope="group")
    router = _router(cfg, ["group context ok"])
    message = SimpleNamespace(channel="group")

    _resp, tier = _run(router.call("v4_flash", [{"role": "user", "content": "g"}], message=message, session_id="private:335059272"))
    assert tier == "v4_flash"
    assert router.last_call_channel_scope == "group"
    assert router.providers["mock"].calls[-1]["model"] == "flash-model"


def test_private_group_invalid_active_falls_back_default_not_other_scope() -> None:
    cfg = _cfg()
    cfg.data["model_profile_switcher"]["active_profile_private"] = "disabled_x"
    cfg.data["model_profile_switcher"]["active_profile_group"] = "v4_pro"
    router = _router(cfg, ["fallback ok", "group ok"])

    _resp, tier = _run(router.call("v4_pro", [{"role": "user", "content": "p"}], channel="private", session_id="private:335059272"))
    assert tier == "v4_flash"
    assert router.providers["mock"].calls[-1]["model"] == "flash-model"

    _resp2, tier2 = _run(router.call("v4_flash", [{"role": "user", "content": "g"}], channel="group", session_id="group:137918147"))
    assert tier2 == "v4_pro"
    assert router.providers["mock"].calls[-1]["model"] == "pro-model"


def test_router_unknown_channel_keeps_legacy_requested_tier() -> None:
    cfg = _cfg()
    switcher.set_active_model_profile(cfg, profile_id="v4_pro", scope="private")
    router = _router(cfg, ["legacy ok"])
    _resp, tier = _run(router.call("v4_flash", [{"role": "user", "content": "u"}], channel="", session_id="unknown"))
    assert tier == "v4_flash"
    assert router.last_call_channel_scope == ""
    assert router.providers["mock"].calls[-1]["model"] == "flash-model"


def test_owner_private_native_loop_set_private_only_and_group_only(tmp_path: Path) -> None:
    cfg = _cfg()
    router = _router(
        cfg,
        [
            {"content": "", "tool_calls": [{"id": "c1", "name": "set_active_model_profile", "arguments": {"profile_id": "v4_pro", "scope": "private"}}]},
            "私聊切好了。",
            {"content": "", "tool_calls": [{"id": "c2", "name": "set_active_model_profile", "arguments": {"profile_id": "v4_pro", "scope": "group"}}]},
            "群聊切好了。",
        ],
    )

    r1 = _run(handle_owner_toolbox_light_llm_message(_msg("切私聊模型到 v4_pro"), cfg, model_router=router, project_root=tmp_path, session_id="private:335059272"))
    assert r1.tool_name == "set_active_model_profile"
    assert cfg.get("model_profile_switcher.active_profile_private") == "v4_pro"
    assert cfg.get("model_profile_switcher.active_profile_group") == "v4_flash"

    r2 = _run(handle_owner_toolbox_light_llm_message(_msg("把群聊切到 v4_pro"), cfg, model_router=router, project_root=tmp_path, session_id="private:335059272"))
    assert r2.tool_name == "set_active_model_profile"
    assert cfg.get("model_profile_switcher.active_profile_private") == "v4_pro"
    assert cfg.get("model_profile_switcher.active_profile_group") == "v4_pro"


def test_get_list_show_both_active_and_no_secret() -> None:
    cfg = _cfg()
    switcher.set_active_model_profile(cfg, profile_id="v4_pro", scope="private")
    get_result = execute_owner_toolbox_tool("get_active_model_profile", {"scope": "private"}, cfg)
    list_result = execute_owner_toolbox_tool("list_model_profiles", {"scope": "current", "include_disabled": True}, cfg)
    blob = str(get_result.reply) + str(get_result.data) + str(list_result.reply) + str(list_result.data)
    assert "private_active" in blob and "group_active" in blob
    assert "v4_pro" in blob and "v4_flash" in blob
    assert "SECRET_A" not in blob and "SECRET_B" not in blob
    assert "base_url" not in blob and "token" not in blob and "api_key" not in blob


def test_test_private_group_direct_no_fallback() -> None:
    cfg = _cfg()
    switcher.set_active_model_profile(cfg, profile_id="v4_pro", scope="private")
    switcher.set_active_model_profile(cfg, profile_id="v4_flash", scope="group")
    router = _router(cfg, ["private pong", "group pong"])

    private = _run(router.test_model_profile(switcher.get_active_profile_id(cfg, "private"), timeout_seconds=5))
    group = _run(router.test_model_profile(switcher.get_active_profile_id(cfg, "group"), timeout_seconds=5))

    assert private["ok"] is True and private["profile_id"] == "v4_pro" and private["fallback_used"] is False
    assert group["ok"] is True and group["profile_id"] == "v4_flash" and group["fallback_used"] is False
    assert [call["tier"] for call in router.providers["mock"].calls] == ["v4_pro", "v4_flash"]





def test_v4_pro_profile_enabled_in_runtime_defaults() -> None:
    runtime_mod = load_module("plugins.yangyang.admin.runtime_config", PLUGIN_ROOT / "admin" / "runtime_config.py")
    cfg = DictConfig(runtime_mod.DEFAULTS)

    descriptor = switcher.get_model_profile_descriptor(cfg, "v4_pro")

    assert cfg.get("providers.v4_pro.enabled") is True
    assert cfg.get("models.v4_pro.enabled") is True
    assert descriptor["enabled"] is True


def test_gpt_5_5_placeholder_remains_disabled_and_not_switchable() -> None:
    cfg = _cfg()

    descriptor = switcher.get_model_profile_descriptor(cfg, "gpt_5_5")
    switched = switcher.set_active_model_profile(cfg, profile_id="gpt_5_5", scope="group")

    assert descriptor["enabled"] is False
    assert switched["ok"] is False
    assert switched["reason"] == "profile_disabled"
    assert cfg.get("model_profile_switcher.active_profile_group") == "v4_flash"

def test_disabled_or_illegal_profile_does_not_write_any_scope() -> None:
    cfg = _cfg()
    before_private = cfg.get("model_profile_switcher.active_profile_private")
    before_group = cfg.get("model_profile_switcher.active_profile_group")

    disabled = switcher.set_active_model_profile(cfg, profile_id="disabled_x", scope="private")
    illegal = switcher.set_active_model_profile(cfg, profile_id="missing", scope="group")

    assert disabled["ok"] is False and disabled["reason"] == "profile_disabled"
    assert illegal["ok"] is False and illegal["reason"] == "profile_not_found"
    assert cfg.get("model_profile_switcher.active_profile_private") == before_private
    assert cfg.get("model_profile_switcher.active_profile_group") == before_group


def test_tool_schema_and_regression_tools_still_present() -> None:
    tools = {tool["name"]: tool for tool in build_owner_toolbox_tools()}
    for name in (
        "list_model_profiles",
        "get_active_model_profile",
        "set_active_model_profile",
        "test_model_profile",
        "get_tool_loop_max_steps",
        "set_tool_loop_max_steps",
        "shell",
    ):
        assert name in tools
    set_schema = tools["set_active_model_profile"]["parameters"]
    assert "selection_index" in set_schema["properties"]
    assert set_schema.get("required", []) == []
    assert "scope" in tools["test_model_profile"]["parameters"]["properties"]


class _ListModelsProvider:
    provider_name = "openai_compat"
    is_available = True

    def __init__(self, model_ids):
        self.model_ids = list(model_ids)
        self.calls = []

    async def list_models(self, *, tier: str, timeout: float = 30):
        self.calls.append({"tier": tier, "timeout": timeout})
        return list(self.model_ids)


def test_refresh_model_profiles_from_models_writes_sanitized_disabled_profiles() -> None:
    cfg = _cfg()
    cfg.data["providers"]["gpt_5_4"] = {
        "enabled": False,
        "provider": "openai_compat",
        "model": "gpt-5.4",
        "api_key_env": "GPT_API_KEY_SHOULD_NOT_LEAK",
        "base_url_env": "GPT_BASE_URL_SHOULD_NOT_LEAK",
        "timeout": 7,
        "cooldown_on_fail": 11,
    }
    cfg.data["models"]["gpt_5_4"] = {"enabled": False, "model": "gpt-5.4"}
    router = ModelRouter(cfg)
    provider = _ListModelsProvider(["gpt-5.4", "gpt-5.5", "weird/model.name"])
    router.register_provider(provider)

    result = _run(router.refresh_model_profiles(provider_profile_id="gpt_5_4", timeout_seconds=6))
    listed = switcher.list_model_profiles(cfg, include_disabled=True)
    by_id = _profiles_by_id(listed)

    assert result["ok"] is True
    assert provider.calls == [{"tier": "gpt_5_4", "timeout": 6.0}]
    assert by_id["gpt_5_4"]["model"] == "gpt-5.4"
    assert by_id["gpt_5_5"]["model"] == "gpt-5.5"
    assert by_id["weird_model_name"]["model"] == "weird/model.name"
    assert by_id["weird_model_name"]["enabled"] is False
    blob = str(result) + str(listed)
    for forbidden in ("GPT_API_KEY_SHOULD_NOT_LEAK", "GPT_BASE_URL_SHOULD_NOT_LEAK", "api_key_env", "base_url_env", "base_url", "token", "SECRET"):
        assert forbidden not in blob


def test_refresh_model_profiles_can_enable_when_explicitly_requested() -> None:
    cfg = _cfg()
    cfg.data["providers"]["gpt_5_4"] = {
        "enabled": True,
        "provider": "openai_compat",
        "model": "gpt-5.4",
        "api_key_env": "GPT_API_KEY",
        "base_url_env": "GPT_BASE_URL",
        "timeout": 7,
        "cooldown_on_fail": 11,
    }
    router = ModelRouter(cfg)
    router.register_provider(_ListModelsProvider(["fresh-model-1"]))

    result = _run(router.refresh_model_profiles(provider_profile_id="gpt_5_4", enable_discovered=True))
    descriptor = switcher.get_model_profile_descriptor(cfg, "fresh_model_1")

    assert result["ok"] is True
    assert descriptor["exists"] is True
    assert descriptor["enabled"] is True
    assert descriptor["provider"] == "openai_compat"
    assert descriptor["model"] == "fresh-model-1"


def test_dynamic_runtime_profile_is_attempted_before_order_fallback() -> None:
    cfg = _cfg()
    cfg.data["providers"]["fresh_model_1"] = {
        "enabled": True,
        "provider": "mock",
        "model": "fresh-model-1",
        "timeout": 5,
        "cooldown_on_fail": 1,
    }
    cfg.data["models"]["fresh_model_1"] = {"enabled": True, "model": "fresh-model-1"}
    switcher.set_active_model_profile(cfg, profile_id="fresh_model_1", scope="private")
    router = _router(cfg, ["dynamic ok"])

    response, tier = _run(router.call("v4_flash", [{"role": "user", "content": "p"}], channel="private", session_id="private:335059272"))

    assert response == "dynamic ok"
    assert tier == "fresh_model_1"
    assert router.providers["mock"].calls[-1]["tier"] == "fresh_model_1"
    assert router.providers["mock"].calls[-1]["model"] == "fresh-model-1"


def test_refresh_model_profiles_tool_schema_present() -> None:
    tools = {tool["name"]: tool for tool in build_owner_toolbox_tools()}

    assert "refresh_model_profiles" in tools
    props = tools["refresh_model_profiles"]["parameters"]["properties"]
    assert "provider_profile_id" in props
    assert "enable_discovered" in props



def test_refresh_model_profiles_uses_profile_prefix_to_avoid_reseller_overlap() -> None:
    cfg = _cfg()
    cfg.data["providers"]["gpt_regular"] = {
        "enabled": False,
        "provider": "openai_compat",
        "model": "gpt-5.4",
        "api_key_env": "REGULAR_KEY",
        "base_url_env": "REGULAR_URL",
        "timeout": 7,
        "cooldown_on_fail": 11,
        "family": "regular",
    }
    cfg.data["models"]["gpt_regular"] = {"enabled": False, "model": "gpt-5.4", "family": "regular"}
    cfg.data["providers"]["promo_gpt"] = {
        "enabled": False,
        "provider": "openai_compat",
        "model": "gpt-5.4",
        "api_key_env": "PROMO_KEY",
        "base_url_env": "PROMO_URL",
        "timeout": 7,
        "cooldown_on_fail": 11,
        "family": "promo_gpt",
        "profile_prefix": "promo",
    }
    cfg.data["models"]["promo_gpt"] = {"enabled": False, "model": "gpt-5.4", "family": "promo_gpt", "profile_prefix": "promo"}
    router = ModelRouter(cfg)

    regular = switcher.refresh_model_profiles_from_models(cfg, provider_profile_id="gpt_regular", model_ids=["gpt-5.4"], enable_discovered=False)
    promo = switcher.refresh_model_profiles_from_models(cfg, provider_profile_id="promo_gpt", model_ids=["gpt-5.4"], enable_discovered=False)
    listed = switcher.list_model_profiles(cfg, include_disabled=True)
    by_id = _profiles_by_id(listed)

    assert regular["ok"] is True
    assert promo["ok"] is True
    assert "gpt_5_4" in by_id
    assert "promo_gpt_5_4" in by_id
    assert by_id["gpt_5_4"]["model"] == "gpt-5.4"
    assert by_id["promo_gpt_5_4"]["model"] == "gpt-5.4"
    assert by_id["promo_gpt_5_4"]["enabled"] is False
    blob = str(regular) + str(promo) + str(listed)
    for forbidden in ("REGULAR_KEY", "REGULAR_URL", "PROMO_KEY", "PROMO_URL", "api_key_env", "base_url_env"):
        assert forbidden not in blob



def test_set_model_profile_enabled_toggles_disabled_profile_without_switching_active() -> None:
    cfg = _cfg()

    result = switcher.set_model_profile_enabled(cfg, profile_id="gpt_5_5", enabled=True)
    descriptor = switcher.get_model_profile_descriptor(cfg, "gpt_5_5")

    assert result["ok"] is True
    assert result["previous_enabled"] is False
    assert result["enabled"] is True
    assert descriptor["enabled"] is True
    assert cfg.get("model_profile_switcher.active_profile_private") == "v4_flash"
    assert cfg.get("model_profile_switcher.active_profile_group") == "v4_flash"


def test_owner_toolbox_set_model_profile_enabled_accepts_selection_index() -> None:
    cfg = _cfg()
    idx = _profiles_by_id(switcher.list_model_profiles(cfg, include_disabled=True))["gpt_5_5"]["index"]

    result = execute_owner_toolbox_tool(
        "set_model_profile_enabled",
        {"selection_index": idx, "enabled": True},
        cfg,
    )

    assert result.allowed is True
    assert result.data["profile_id"] == "gpt_5_5"
    assert switcher.get_model_profile_descriptor(cfg, "gpt_5_5")["enabled"] is True
    assert cfg.get("model_profile_switcher.active_profile_private") == "v4_flash"
    assert cfg.get("model_profile_switcher.active_profile_group") == "v4_flash"


def test_owner_toolbox_set_model_profile_enabled_schema_present() -> None:
    tools = {tool["name"]: tool for tool in build_owner_toolbox_tools()}

    assert "set_model_profile_enabled" in tools
    props = tools["set_model_profile_enabled"]["parameters"]["properties"]
    assert "profile_id" in props
    assert "selection_index" in props
    assert "enabled" in props
