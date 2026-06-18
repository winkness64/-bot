from __future__ import annotations

from typing import Any, Mapping

try:
    from ...model_profile_switcher import (
        get_active_model_profile,
        list_model_profiles as switcher_list_model_profiles,
        resolve_profile_scope,
        set_active_model_profile as switcher_set_active_model_profile,
        set_model_profile_enabled as switcher_set_model_profile_enabled,
        validate_model_profile_enabled,
    )
except ImportError:
    import importlib.util
    import sys
    from pathlib import Path

    _switcher_path = Path(__file__).resolve().parents[2] / "model_profile_switcher.py"
    _switcher_spec = importlib.util.spec_from_file_location("owner_toolbox_tools_model_profile_switcher", _switcher_path)
    if _switcher_spec is None or _switcher_spec.loader is None:
        raise
    _switcher_mod = importlib.util.module_from_spec(_switcher_spec)
    sys.modules.setdefault(_switcher_spec.name, _switcher_mod)
    _switcher_spec.loader.exec_module(_switcher_mod)
    get_active_model_profile = _switcher_mod.get_active_model_profile
    switcher_list_model_profiles = _switcher_mod.list_model_profiles
    resolve_profile_scope = _switcher_mod.resolve_profile_scope
    switcher_set_active_model_profile = _switcher_mod.set_active_model_profile
    switcher_set_model_profile_enabled = _switcher_mod.set_model_profile_enabled
    validate_model_profile_enabled = _switcher_mod.validate_model_profile_enabled

from ..formatters import _format_profile_list_reply, _format_active_profile_reply, _format_set_profile_reply, _format_test_profile_reply, _format_refresh_profiles_reply, _format_enable_profile_reply
from ..results import _result
from ..types import OwnerToolboxLightResult


def _clean_tool_args(argmap: Mapping[str, Any] | dict[str, Any]) -> dict[str, Any]:
    return {str(k): v for k, v in dict(argmap or {}).items() if not str(k).startswith("_context_")}


def _context_channel_from_args(argmap: Mapping[str, Any] | dict[str, Any]) -> str:
    return str((argmap or {}).get("_context_channel") or "private").strip().lower() or "private"


def _validate_model_profile_enabled_for_light(config: Any, profile_id: Any) -> tuple[bool, str, dict[str, Any]]:
    return validate_model_profile_enabled(config, profile_id)


def handle_list_model_profiles(config: Any, argmap: Mapping[str, Any] | dict[str, Any], *, tool: str = "list_model_profiles") -> OwnerToolboxLightResult:
    args_clean = _clean_tool_args(argmap)
    scope = args_clean.get("scope") or "current"
    raw_text = str(args_clean.get("_raw") or args_clean.get("query") or args_clean.get("text") or "")
    include_disabled = bool(args_clean.get("include_disabled", False))
    if not include_disabled and any(marker in raw_text.lower() for marker in ("全量", "全部", "所有", "完整", "禁用", "disabled", "include_disabled")):
        include_disabled = True
    context_channel = _context_channel_from_args(argmap)
    data = switcher_list_model_profiles(
        config,
        scope=scope,
        include_disabled=include_disabled,
        context_channel=context_channel,
    )
    output = _format_profile_list_reply(data)
    return _result(reason="ok" if data.get("ok") else data.get("reason", "error"), reply=output, tool_name=tool, output=output, data=data)


def handle_get_active_model_profile(config: Any, argmap: Mapping[str, Any] | dict[str, Any], *, tool: str = "get_active_model_profile") -> OwnerToolboxLightResult:
    args_clean = _clean_tool_args(argmap)
    context_channel = _context_channel_from_args(argmap)
    data = get_active_model_profile(config, scope=args_clean.get("scope") or "current", context_channel=context_channel)
    output = _format_active_profile_reply(data)
    return _result(reason="ok" if data.get("ok") else data.get("reason", "error"), reply=output, tool_name=tool, output=output, data=data)


def handle_set_active_model_profile(config: Any, argmap: Mapping[str, Any] | dict[str, Any], *, tool: str = "set_active_model_profile") -> OwnerToolboxLightResult:
    args_clean = _clean_tool_args(argmap)
    profile_id = args_clean.get("profile_id") or ((args_clean.get("_argv") or [None])[0] if args_clean.get("_argv") else None)
    if profile_id is None and args_clean.get("_raw") is not None:
        profile_id = str(args_clean.get("_raw") or "").strip()
    context_channel = _context_channel_from_args(argmap)
    data = switcher_set_active_model_profile(
        config,
        profile_id=profile_id,
        selection_index=args_clean.get("selection_index"),
        scope=args_clean.get("scope") or "current",
        context_channel=context_channel,
    )
    output = _format_set_profile_reply(data)
    return _result(
        allowed=bool(data.get("ok")),
        reason=str(data.get("reason") or "error"),
        reply=output,
        tool_name=tool,
        output=output,
        data=data,
    )


def handle_set_model_profile_enabled(config: Any, argmap: Mapping[str, Any] | dict[str, Any], *, tool: str = "set_model_profile_enabled") -> OwnerToolboxLightResult:
    args_clean = _clean_tool_args(argmap)
    profile_id = args_clean.get("profile_id") or ((args_clean.get("_argv") or [None])[0] if args_clean.get("_argv") else None)
    if profile_id is None and args_clean.get("_raw") is not None:
        profile_id = str(args_clean.get("_raw") or "").strip()
    enabled = args_clean.get("enabled", True)
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() not in {"0", "false", "no", "off", "disable", "disabled", "禁用", "关", "关闭"}
    data = switcher_set_model_profile_enabled(
        config,
        profile_id=profile_id,
        selection_index=args_clean.get("selection_index"),
        enabled=bool(enabled),
    )
    output = _format_enable_profile_reply(data)
    return _result(
        allowed=bool(data.get("ok")),
        reason=str(data.get("reason") or "error"),
        reply=output,
        tool_name=tool,
        output=output,
        data=data,
    )


def handle_test_model_profile(config: Any, argmap: Mapping[str, Any] | dict[str, Any], *, tool: str = "test_model_profile") -> OwnerToolboxLightResult:
    args_clean = _clean_tool_args(argmap)
    scope = args_clean.get("scope") or "current"
    context_channel = _context_channel_from_args(argmap)
    ok_scope, resolved_scope, scope_reason = resolve_profile_scope(scope, context_channel=context_channel)
    if not ok_scope:
        data = {"ok": False, "reason": scope_reason, "scope": scope, "fallback_used": False}
    else:
        active = get_active_model_profile(config, scope=resolved_scope, context_channel=context_channel)
        profile_id = str(args_clean.get("profile_id") or active.get("profile_id") or "").strip()
        ok, reason, profile = _validate_model_profile_enabled_for_light(config, profile_id)
        data = {"ok": ok, "reason": reason, "profile_id": profile_id, "profile": profile, "fallback_used": False}
        if isinstance(data, dict):
            data["scope"] = resolved_scope
            data.setdefault("private_active", active.get("private_active"))
            data.setdefault("group_active", active.get("group_active"))
    output = _format_test_profile_reply(data if isinstance(data, dict) else {"ok": False, "reason": "bad_result", "fallback_used": False})
    return _result(
        allowed=bool(isinstance(data, dict) and data.get("ok")),
        reason=str(data.get("reason") if isinstance(data, dict) else "bad_result"),
        reply=output,
        tool_name=tool,
        output=output,
        data=data if isinstance(data, dict) else {"ok": False, "reason": "bad_result", "fallback_used": False},
    )


async def handle_refresh_model_profiles(
    config: Any,
    argmap: Mapping[str, Any] | dict[str, Any],
    *,
    model_router: Any = None,
    tool: str = "refresh_model_profiles",
) -> OwnerToolboxLightResult:
    args_clean = _clean_tool_args(argmap)
    if model_router is None or not hasattr(model_router, "refresh_model_profiles"):
        data = {"ok": False, "reason": "model_router_unavailable", "refreshed": [], "failed": []}
    else:
        data = await model_router.refresh_model_profiles(
            provider_profile_id=args_clean.get("provider_profile_id") or None,
            enable_discovered=bool(args_clean.get("enable_discovered", False)),
            timeout_seconds=int(args_clean.get("timeout_seconds") or args_clean.get("timeout") or 30),
        )
    if not isinstance(data, dict):
        data = {"ok": False, "reason": "bad_result", "refreshed": [], "failed": []}
    output = _format_refresh_profiles_reply(data)
    return _result(
        allowed=bool(data.get("ok") or data.get("reason") == "partial"),
        reason=str(data.get("reason") or "error"),
        reply=output,
        tool_name=tool,
        output=output,
        data=data,
    )


def handle_get_model_runtime_chain(config: Any, argmap: Mapping[str, Any] | dict[str, Any], *, tool: str = "get_model_runtime_chain") -> OwnerToolboxLightResult:
    args_clean = _clean_tool_args(argmap)
    context_channel = _context_channel_from_args(argmap)
    scope = args_clean.get("scope") or "current"
    active = get_active_model_profile(config, scope=scope, context_channel=context_channel)
    resolved_scope = str(active.get("scope") or scope or "private")
    if resolved_scope == "group":
        fallback_chain = list(config.get('model_profile_switcher.fallback_profiles_group', []) or [])
    else:
        fallback_chain = list(config.get('model_profile_switcher.fallback_profiles_private', []) or [])
    data = {
        'ok': bool(active.get('ok', True)),
        'reason': str(active.get('reason') or 'ok'),
        'scope': resolved_scope,
        'profile_id': active.get('profile_id'),
        'profile': active.get('profile') if isinstance(active.get('profile'), Mapping) else {},
        'private_active': active.get('private_active'),
        'group_active': active.get('group_active'),
        'fallback_profiles': fallback_chain,
    }
    profile = data.get('profile') if isinstance(data.get('profile'), Mapping) else {}
    fallback_text = ' -> '.join(str(x) for x in fallback_chain) if fallback_chain else '(empty)'
    output = (
        f"scope={data.get('scope')} active={data.get('profile_id')} "
        f"provider={profile.get('provider')} model={profile.get('model')} "
        f"fallback={fallback_text} private_active={data.get('private_active')} group_active={data.get('group_active')}"
    ).strip()
    return _result(reason=str(data.get('reason') or 'ok'), reply=output, tool_name=tool, output=output, data=data)
