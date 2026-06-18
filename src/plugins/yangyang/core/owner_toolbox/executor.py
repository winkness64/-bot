from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
import subprocess
import tarfile
from typing import Any, Mapping, Sequence

try:
    from ..isaac_agent_bus_p0 import handle_isaac_agent_bus_p0_message
except Exception:  # pragma: no cover - direct-file compatibility.
    try:
        import importlib.util
        import sys

        _ISAAC_P0_PATH = Path(__file__).resolve().parents[1] / "isaac_agent_bus_p0.py"
        _ISAAC_P0_SPEC = importlib.util.spec_from_file_location("owner_toolbox_isaac_agent_bus_p0", _ISAAC_P0_PATH)
        if _ISAAC_P0_SPEC is None or _ISAAC_P0_SPEC.loader is None:
            raise ImportError(f"cannot load Isaac P0 handler from {_ISAAC_P0_PATH}")
        _isaac_p0_mod = importlib.util.module_from_spec(_ISAAC_P0_SPEC)
        sys.modules[_ISAAC_P0_SPEC.name] = _isaac_p0_mod
        _ISAAC_P0_SPEC.loader.exec_module(_isaac_p0_mod)
        handle_isaac_agent_bus_p0_message = _isaac_p0_mod.handle_isaac_agent_bus_p0_message  # type: ignore[assignment]
    except Exception:
        handle_isaac_agent_bus_p0_message = None  # type: ignore[assignment]

try:
    from ..model_profile_switcher import (
        get_active_model_profile,
        list_model_profiles as switcher_list_model_profiles,
        resolve_profile_scope,
        set_active_model_profile as switcher_set_active_model_profile,
        validate_model_profile_enabled,
    )
except ImportError:
    import importlib.util
    import sys

    _switcher_path = Path(__file__).resolve().parents[1] / "model_profile_switcher.py"
    _switcher_spec = importlib.util.spec_from_file_location("owner_toolbox_executor_model_profile_switcher", _switcher_path)
    if _switcher_spec is None or _switcher_spec.loader is None:
        raise
    _switcher_mod = importlib.util.module_from_spec(_switcher_spec)
    sys.modules.setdefault(_switcher_spec.name, _switcher_mod)
    _switcher_spec.loader.exec_module(_switcher_mod)
    get_active_model_profile = _switcher_mod.get_active_model_profile
    switcher_list_model_profiles = _switcher_mod.list_model_profiles
    resolve_profile_scope = _switcher_mod.resolve_profile_scope
    switcher_set_active_model_profile = _switcher_mod.set_active_model_profile
    validate_model_profile_enabled = _switcher_mod.validate_model_profile_enabled

from .config import _config_get_int, _utc_now, get_owner_tool_loop_max_steps, set_owner_tool_loop_max_steps, TOOL_LOOP_MAX_STEPS_CONFIG_KEY
from .constants import (
    AVAILABLE_TOOLS,
    REGISTERED_SLASH_TOKENS,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_MAX_OUTPUT_CHARS,
    DEFAULT_MAX_READ_BYTES,
    DEFAULT_MAX_LIST_ENTRIES,
    DEFAULT_MAX_PACK_FILES,
)
from .formatters import _format_profile_list_reply, _format_active_profile_reply, _format_set_profile_reply, _format_test_profile_reply
from .parser import _normalize_tool_name, _split_first_word
from .paths import _resolve_workspace_root, _resolve_user_path
from .results import _result, _truncate
from .types import OwnerToolboxLightResult
from .tools.status import handle_status
from .tools.max_steps import handle_get_tool_loop_max_steps, handle_set_tool_loop_max_steps
from .tools.model_profile import (
    handle_list_model_profiles,
    handle_get_active_model_profile,
    handle_get_model_runtime_chain,
    handle_set_active_model_profile,
    handle_set_model_profile_enabled,
    handle_test_model_profile,
    handle_refresh_model_profiles,
)
from .tools.filesystem import handle_list, handle_read_or_log_tail, handle_write
from .tools.process import handle_shell_or_python, _python_runner_code
from .tools.archive import handle_pack
from .tools.token_usage import handle_query_token_usage


def _args_to_mapping(args: Any) -> dict[str, Any]:
    if args is None:
        return {}
    if isinstance(args, Mapping):
        return dict(args)
    if isinstance(args, str):
        return {"_raw": args}
    if isinstance(args, Sequence) and not isinstance(args, (bytes, bytearray)):
        return {"_argv": [str(item) for item in args]}
    return {"value": args}


def _context_channel_from_args(argmap: Mapping[str, Any] | dict[str, Any]) -> str:
    return str((argmap or {}).get("_context_channel") or "private").strip().lower() or "private"


def _clean_tool_args(argmap: Mapping[str, Any] | dict[str, Any]) -> dict[str, Any]:
    return {str(k): v for k, v in dict(argmap or {}).items() if not str(k).startswith("_context_")}


def _validate_model_profile_enabled_for_light(config: Any, profile_id: Any) -> tuple[bool, str, dict[str, Any]]:
    return validate_model_profile_enabled(config, profile_id)


def _format_isaac_p0_tool_reply(isaac_result: Any) -> str:
    reply = str(getattr(isaac_result, "reply", "") or "").strip()
    if reply:
        return reply
    reason = str(getattr(isaac_result, "reason", "") or "unknown")
    return f"Isaac P0 未返回内容：reason={reason}"


def _handle_isaac_p0_tool(
    argmap: Mapping[str, Any] | dict[str, Any],
    *,
    tool: str,
    model_router: Any = None,
) -> OwnerToolboxLightResult:
    if _context_channel_from_args(argmap) != "private":
        return _result(allowed=False, reason="not_owner_private", reply="Isaac P0 仅 owner 私聊可用。", tool_name=tool)
    if handle_isaac_agent_bus_p0_message is None:
        return _result(allowed=False, reason="isaac_p0_unavailable", reply="Isaac P0 当前不可用。", tool_name=tool)
    raw_command = str((argmap or {}).get("command_text") or (argmap or {}).get("text") or (argmap or {}).get("query") or "").strip()
    task_type = str((argmap or {}).get("task_type") or "").strip()
    if not raw_command and task_type:
        raw_command = {
            "health_report": "health",
            "workspace_report": "workspace report",
            "dry_run_plan": "dry_run plan",
            "help_report": "help",
            "agentbus_factory_report": "agentbus factory",
        }.get(task_type, task_type)
    if not raw_command:
        raw_command = "help"
    proxy_uid = str(
        (argmap or {}).get("_context_user_id")
        or (argmap or {}).get("_context_uid")
        or (argmap or {}).get("user_id")
        or (argmap or {}).get("uid")
        or ""
    ).strip()
    proxy_text = str(raw_command or "").strip()
    natural_delegate = not proxy_text.startswith("/")
    proxy = type("IsaacP0ToolMessage", (), {
        "text": proxy_text,
        "raw_content": proxy_text,
        "channel": "private",
        "is_owner": True,
        "uid": proxy_uid,
        "user_id": proxy_uid,
        "group_id": "",
        "isaac_p0_natural_delegate": natural_delegate,
        "isaac_p0_tool_call_delegate": True,
    })()
    isaac_result = handle_isaac_agent_bus_p0_message(proxy, model_router=model_router)
    reply = _format_isaac_p0_tool_reply(isaac_result)
    data = {
        "isaac_reason": str(getattr(isaac_result, "reason", "") or ""),
        "task_type": getattr(isaac_result, "task_type", None),
        "handled": bool(getattr(isaac_result, "handled", False)),
    }
    return _result(
        handled=bool(getattr(isaac_result, "handled", True)),
        allowed=bool(getattr(isaac_result, "allowed", False)),
        reason=str(getattr(isaac_result, "reason", "") or "ok"),
        reply=reply,
        tool_name=tool,
        output=reply,
        data=data,
    )


async def execute_owner_toolbox_tool_async(
    tool_name: str,
    args: Any = None,
    config: Any = None,
    *,
    project_root: str | Path | None = None,
    model_router: Any = None,
    context_channel: str = "private",
) -> OwnerToolboxLightResult:
    tool = _normalize_tool_name(tool_name)
    argmap = _args_to_mapping(args)
    argmap.setdefault("_context_channel", str(context_channel or "private"))
    if tool == "refresh_model_profiles":
        return await handle_refresh_model_profiles(
            config,
            argmap,
            model_router=model_router,
            tool=tool,
        )
    if tool == "isaac_p0":
        return _handle_isaac_p0_tool(argmap, tool=tool, model_router=model_router)
    if tool != "test_model_profile":
        return execute_owner_toolbox_tool(tool, argmap, config, project_root=project_root)

    args_clean = _clean_tool_args(argmap)
    scope = args_clean.get("scope") or "current"
    ok_scope, resolved_scope, scope_reason = resolve_profile_scope(scope, context_channel=str(context_channel or "private"))
    active = get_active_model_profile(config, scope=resolved_scope if ok_scope else "private", context_channel=str(context_channel or "private"))
    if not ok_scope:
        data = {"ok": False, "reason": scope_reason, "scope": scope, "fallback_used": False}
    else:
        profile_id = str(args_clean.get("profile_id") or active.get("profile_id") or "").strip()
        timeout_seconds = args_clean.get("timeout_seconds") or args_clean.get("timeout") or 30
        if model_router is not None and hasattr(model_router, "test_model_profile"):
            data = await model_router.test_model_profile(
                profile_id,
                timeout_seconds=int(timeout_seconds),
                session_id=f"owner_toolbox_model_test:{resolved_scope}",
            )
        else:
            ok, reason, profile = _validate_model_profile_enabled_for_light(config, profile_id)
            data = {"ok": ok, "reason": reason, "profile_id": profile_id, "profile": profile, "fallback_used": False}
        if isinstance(data, dict):
            data["scope"] = resolved_scope
            data.setdefault("private_active", active.get("private_active"))
            data.setdefault("group_active", active.get("group_active"))
    if not isinstance(data, dict):
        data = {"ok": False, "reason": "bad_result", "fallback_used": False}
    output = _format_test_profile_reply(data)
    return _result(
        allowed=bool(data.get("ok")),
        reason=str(data.get("reason") or "error"),
        reply=output,
        tool_name=tool,
        output=output,
        data=data,
    )


def _max_output_chars(config: Any) -> int:
    return _config_get_int(config, "owner_toolbox_light_max_output_chars", DEFAULT_MAX_OUTPUT_CHARS, minimum=500, maximum=50000)


def _timeout(config: Any, explicit: Any = None) -> int:
    if explicit is not None:
        try:
            return max(1, min(300, int(explicit)))
        except Exception:
            pass
    return _config_get_int(config, "owner_toolbox_light_timeout_seconds", DEFAULT_TIMEOUT_SECONDS, minimum=1, maximum=300)


def execute_owner_toolbox_tool(
    tool_name: str,
    args: Any = None,
    config: Any = None,
    *,
    project_root: str | Path | None = None,
) -> OwnerToolboxLightResult:
    tool = _normalize_tool_name(tool_name)
    if tool not in AVAILABLE_TOOLS:
        return _result(allowed=False, reason="unknown_tool", reply=f"未知工具：{tool_name}", tool_name=tool)

    root = _resolve_workspace_root(config, project_root=project_root)
    max_output = _max_output_chars(config)
    argmap = _args_to_mapping(args)

    try:
        if tool == "status":
            return handle_status(root=root, tool=tool)

        if tool == "get_tool_loop_max_steps":
            return handle_get_tool_loop_max_steps(config, tool=tool)

        if tool == "list_model_profiles":
            return handle_list_model_profiles(config, argmap, tool=tool)

        if tool == "get_active_model_profile":
            return handle_get_active_model_profile(config, argmap, tool=tool)

        if tool == "set_active_model_profile":
            return handle_set_active_model_profile(config, argmap, tool=tool)

        if tool == "set_model_profile_enabled":
            return handle_set_model_profile_enabled(config, argmap, tool=tool)

        if tool == "test_model_profile":
            return handle_test_model_profile(config, argmap, tool=tool)

        if tool == "refresh_model_profiles":
            return _result(allowed=False, reason="async_tool_requires_model_router", reply="refresh_model_profiles 需要通过 native tool loop 调用。", tool_name=tool)

        if tool == "query_token_usage":
            return handle_query_token_usage(config, argmap, project_root=project_root, tool=tool)

        if tool == "isaac_p0":
            return _handle_isaac_p0_tool(argmap, tool=tool)

        if tool == "set_tool_loop_max_steps":
            return handle_set_tool_loop_max_steps(config, argmap, tool=tool)

        if tool == "list":
            return handle_list(config, argmap, root=root, max_output=max_output, tool=tool)

        if tool in {"read", "log_tail"}:
            return handle_read_or_log_tail(config, argmap, root=root, max_output=max_output, tool=tool)

        if tool == "write":
            return handle_write(argmap, root=root, tool=tool)

        if tool in {"shell", "python"}:
            return handle_shell_or_python(config, argmap, root=root, max_output=max_output, timeout_func=_timeout, tool=tool)

        if tool == "pack":
            return handle_pack(config, argmap, root=root, tool=tool)

    except subprocess.TimeoutExpired:
        return _result(allowed=False, reason="timeout", reply="执行超时。", tool_name=tool)
    except Exception as exc:
        return _result(allowed=False, reason=f"tool_error:{exc.__class__.__name__}", reply=f"工具报错：{exc.__class__.__name__}", tool_name=tool)

    return _result(allowed=False, reason="unknown_tool", reply=f"未知工具：{tool}", tool_name=tool)
