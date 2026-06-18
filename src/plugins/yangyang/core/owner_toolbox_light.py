from __future__ import annotations

from pathlib import Path

try:
    from .model_profile_switcher import (
        get_active_model_profile,
        list_model_profiles as switcher_list_model_profiles,
        resolve_profile_scope,
        set_active_model_profile as switcher_set_active_model_profile,
        validate_model_profile_enabled,
    )
except ImportError:  # direct-file test import compatibility
    import importlib.util
    import sys

    _switcher_path = Path(__file__).resolve().with_name("model_profile_switcher.py")
    _switcher_spec = importlib.util.spec_from_file_location("owner_toolbox_light_model_profile_switcher", _switcher_path)
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

try:
    from .owner_toolbox.types import SlashCommand, OwnerToolboxLightResult, ToolInvocation, ToolLoopMaxStepsCommand
    from .owner_toolbox.config import (
        TOOL_LOOP_MAX_STEPS_CONFIG_KEY, TOOL_LOOP_MAX_STEPS_ALIAS_KEYS, TOOL_LOOP_MAX_STEPS_DEFAULT, TOOL_LOOP_MAX_STEPS_MIN,
        _utc_now, _config_get, _config_get_bool, _config_get_int, _tool_loop_max_steps_raw,
        clamp_owner_tool_loop_max_steps, get_owner_tool_loop_max_steps, _config_set, set_owner_tool_loop_max_steps,
    )
    from .owner_toolbox.constants import (
        REGISTERED_SLASH_TOKENS, TOOL_ALIASES, AVAILABLE_TOOLS, DEFAULT_TIMEOUT_SECONDS,
        DEFAULT_MAX_OUTPUT_CHARS, DEFAULT_MAX_READ_BYTES, DEFAULT_MAX_LIST_ENTRIES, DEFAULT_MAX_PACK_FILES,
    )
    from .owner_toolbox.permissions import _owner_uid_set, is_owner_private
    from .owner_toolbox.paths import PROJECT_ROOT, _resolve_workspace_root, _is_relative_to, _resolve_user_path
    from .owner_toolbox.results import _truncate, _result
    from .owner_toolbox.schemas import build_owner_toolbox_tools
    from .owner_toolbox.parser import (
        _message_text, _split_argv, _split_first_word, _normalize_tool_name, parse_slash_command, _usage,
        is_legacy_toolbox_prefix, _invocation_from_toolbox_text, parse_natural_tool_invocation,
        parse_owner_tool_loop_max_steps_command, is_owner_tool_loop_max_steps_intent,
    )
    from .owner_toolbox.formatters import (
        _format_profile_list_reply, _format_active_profile_reply, _format_set_profile_reply, _format_test_profile_reply,
        format_owner_toolbox_reply, format_owner_toolbox_raw_details,
    )
    from .owner_toolbox.executor import (
        _args_to_mapping, _context_channel_from_args, _clean_tool_args, _validate_model_profile_enabled_for_light,
        execute_owner_toolbox_tool_async, _max_output_chars, _timeout, execute_owner_toolbox_tool, _python_runner_code,
    )
    from .owner_toolbox.native_loop import (
        handle_owner_tool_loop_max_steps_message, wants_owner_toolbox_raw_details, _strip_raw_mode_markers,
        _owner_tool_loop_system_prompt, _extract_systemd_service_name, _owner_tool_loop_systemd_hint,
        _owner_tool_loop_messages, prepare_owner_tool_loop_messages, coerce_owner_toolbox_human_reply,
        _looks_like_frontend_tool_payload, _fallback_human_reply_from_trace, _model_final_content,
        handle_owner_toolbox_light_llm_message, handle_slash_command, handle_owner_toolbox_light_message,
        handle_owner_toolbox_light_message_sync,
    )
except ImportError:  # direct-file test import compatibility
    import importlib.util as _ot_importlib_util
    import sys as _ot_sys
    import types as _ot_types

    _ot_dir = Path(__file__).resolve().with_name("owner_toolbox")
    _ot_pkg_name = "owner_toolbox_light_owner_toolbox"
    if _ot_pkg_name not in _ot_sys.modules:
        _ot_pkg = _ot_types.ModuleType(_ot_pkg_name)
        _ot_pkg.__path__ = [str(_ot_dir)]
        _ot_sys.modules[_ot_pkg_name] = _ot_pkg

    def _ot_load_module(name: str):
        full_name = f"{_ot_pkg_name}.{name}"
        if full_name in _ot_sys.modules:
            return _ot_sys.modules[full_name]
        spec = _ot_importlib_util.spec_from_file_location(full_name, _ot_dir / f"{name}.py")
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load owner_toolbox.{name}")
        mod = _ot_importlib_util.module_from_spec(spec)
        _ot_sys.modules[full_name] = mod
        spec.loader.exec_module(mod)
        return mod

    _ot_types_mod = _ot_load_module("types")
    _ot_config_mod = _ot_load_module("config")
    _ot_constants_mod = _ot_load_module("constants")
    _ot_permissions_mod = _ot_load_module("permissions")
    _ot_paths_mod = _ot_load_module("paths")
    _ot_results_mod = _ot_load_module("results")
    _ot_schemas_mod = _ot_load_module("schemas")
    _ot_parser_mod = _ot_load_module("parser")
    _ot_formatters_mod = _ot_load_module("formatters")
    _ot_executor_mod = _ot_load_module("executor")
    _ot_native_loop_mod = _ot_load_module("native_loop")

    SlashCommand = _ot_types_mod.SlashCommand
    OwnerToolboxLightResult = _ot_types_mod.OwnerToolboxLightResult
    ToolInvocation = _ot_types_mod.ToolInvocation
    ToolLoopMaxStepsCommand = _ot_types_mod.ToolLoopMaxStepsCommand
    TOOL_LOOP_MAX_STEPS_CONFIG_KEY = _ot_config_mod.TOOL_LOOP_MAX_STEPS_CONFIG_KEY
    TOOL_LOOP_MAX_STEPS_ALIAS_KEYS = _ot_config_mod.TOOL_LOOP_MAX_STEPS_ALIAS_KEYS
    TOOL_LOOP_MAX_STEPS_DEFAULT = _ot_config_mod.TOOL_LOOP_MAX_STEPS_DEFAULT
    TOOL_LOOP_MAX_STEPS_MIN = _ot_config_mod.TOOL_LOOP_MAX_STEPS_MIN
    _utc_now = _ot_config_mod._utc_now
    _config_get = _ot_config_mod._config_get
    _config_get_bool = _ot_config_mod._config_get_bool
    _config_get_int = _ot_config_mod._config_get_int
    _tool_loop_max_steps_raw = _ot_config_mod._tool_loop_max_steps_raw
    clamp_owner_tool_loop_max_steps = _ot_config_mod.clamp_owner_tool_loop_max_steps
    get_owner_tool_loop_max_steps = _ot_config_mod.get_owner_tool_loop_max_steps
    _config_set = _ot_config_mod._config_set
    set_owner_tool_loop_max_steps = _ot_config_mod.set_owner_tool_loop_max_steps
    REGISTERED_SLASH_TOKENS = _ot_constants_mod.REGISTERED_SLASH_TOKENS
    TOOL_ALIASES = _ot_constants_mod.TOOL_ALIASES
    AVAILABLE_TOOLS = _ot_constants_mod.AVAILABLE_TOOLS
    DEFAULT_TIMEOUT_SECONDS = _ot_constants_mod.DEFAULT_TIMEOUT_SECONDS
    DEFAULT_MAX_OUTPUT_CHARS = _ot_constants_mod.DEFAULT_MAX_OUTPUT_CHARS
    DEFAULT_MAX_READ_BYTES = _ot_constants_mod.DEFAULT_MAX_READ_BYTES
    DEFAULT_MAX_LIST_ENTRIES = _ot_constants_mod.DEFAULT_MAX_LIST_ENTRIES
    DEFAULT_MAX_PACK_FILES = _ot_constants_mod.DEFAULT_MAX_PACK_FILES
    _owner_uid_set = _ot_permissions_mod._owner_uid_set
    is_owner_private = _ot_permissions_mod.is_owner_private
    PROJECT_ROOT = _ot_paths_mod.PROJECT_ROOT
    _resolve_workspace_root = _ot_paths_mod._resolve_workspace_root
    _is_relative_to = _ot_paths_mod._is_relative_to
    _resolve_user_path = _ot_paths_mod._resolve_user_path
    _truncate = _ot_results_mod._truncate
    _result = _ot_results_mod._result
    build_owner_toolbox_tools = _ot_schemas_mod.build_owner_toolbox_tools
    _message_text = _ot_parser_mod._message_text
    _split_argv = _ot_parser_mod._split_argv
    _split_first_word = _ot_parser_mod._split_first_word
    _normalize_tool_name = _ot_parser_mod._normalize_tool_name
    parse_slash_command = _ot_parser_mod.parse_slash_command
    _usage = _ot_parser_mod._usage
    is_legacy_toolbox_prefix = _ot_parser_mod.is_legacy_toolbox_prefix
    _invocation_from_toolbox_text = _ot_parser_mod._invocation_from_toolbox_text
    parse_natural_tool_invocation = _ot_parser_mod.parse_natural_tool_invocation
    parse_owner_tool_loop_max_steps_command = _ot_parser_mod.parse_owner_tool_loop_max_steps_command
    is_owner_tool_loop_max_steps_intent = _ot_parser_mod.is_owner_tool_loop_max_steps_intent
    _format_profile_list_reply = _ot_formatters_mod._format_profile_list_reply
    _format_active_profile_reply = _ot_formatters_mod._format_active_profile_reply
    _format_set_profile_reply = _ot_formatters_mod._format_set_profile_reply
    _format_test_profile_reply = _ot_formatters_mod._format_test_profile_reply
    format_owner_toolbox_reply = _ot_formatters_mod.format_owner_toolbox_reply
    format_owner_toolbox_raw_details = _ot_formatters_mod.format_owner_toolbox_raw_details
    _args_to_mapping = _ot_executor_mod._args_to_mapping
    _context_channel_from_args = _ot_executor_mod._context_channel_from_args
    _clean_tool_args = _ot_executor_mod._clean_tool_args
    _validate_model_profile_enabled_for_light = _ot_executor_mod._validate_model_profile_enabled_for_light
    execute_owner_toolbox_tool_async = _ot_executor_mod.execute_owner_toolbox_tool_async
    _max_output_chars = _ot_executor_mod._max_output_chars
    _timeout = _ot_executor_mod._timeout
    execute_owner_toolbox_tool = _ot_executor_mod.execute_owner_toolbox_tool
    _python_runner_code = _ot_executor_mod._python_runner_code
    handle_owner_tool_loop_max_steps_message = _ot_native_loop_mod.handle_owner_tool_loop_max_steps_message
    wants_owner_toolbox_raw_details = _ot_native_loop_mod.wants_owner_toolbox_raw_details
    _strip_raw_mode_markers = _ot_native_loop_mod._strip_raw_mode_markers
    _owner_tool_loop_system_prompt = _ot_native_loop_mod._owner_tool_loop_system_prompt
    _extract_systemd_service_name = _ot_native_loop_mod._extract_systemd_service_name
    _owner_tool_loop_systemd_hint = _ot_native_loop_mod._owner_tool_loop_systemd_hint
    _owner_tool_loop_messages = _ot_native_loop_mod._owner_tool_loop_messages
    prepare_owner_tool_loop_messages = _ot_native_loop_mod.prepare_owner_tool_loop_messages
    coerce_owner_toolbox_human_reply = _ot_native_loop_mod.coerce_owner_toolbox_human_reply
    _looks_like_frontend_tool_payload = _ot_native_loop_mod._looks_like_frontend_tool_payload
    _fallback_human_reply_from_trace = _ot_native_loop_mod._fallback_human_reply_from_trace
    _model_final_content = _ot_native_loop_mod._model_final_content
    handle_owner_toolbox_light_llm_message = _ot_native_loop_mod.handle_owner_toolbox_light_llm_message
    handle_slash_command = _ot_native_loop_mod.handle_slash_command
    handle_owner_toolbox_light_message = _ot_native_loop_mod.handle_owner_toolbox_light_message
    handle_owner_toolbox_light_message_sync = _ot_native_loop_mod.handle_owner_toolbox_light_message_sync

# backward-compat alias for legacy tests/tools
execute_owner_toolbox_command = execute_owner_toolbox_tool
execute_owner_toolbox_command_async = execute_owner_toolbox_tool_async
