from __future__ import annotations

from typing import Any


def build_owner_toolbox_tools() -> list[dict[str, Any]]:
    """Tool metadata for the owner-private native tool loop.

    Owner-private sessions have full host filesystem visibility: paths may be
    absolute or relative to the default cwd, and `shell` / `python` may run
    any explicit command. There is no workspace sandbox and no keyword safety
    valve on tool descriptions — privilege is gated solely by the owner-private
    entrypoint in `handle_owner_toolbox_light_llm_message` /
    `handle_slash_command` via `is_owner_private`.
    """
    return [
        {
            "name": "status",
            "description": (
                "Show Owner Toolbox Light status, default cwd, and available tools. "
                "Owner-private executor has full host filesystem and shell/python access; "
                "no workspace sandbox."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "list",
            "description": (
                "List files at a host path. Accepts absolute paths (e.g. /opt/...) or "
                "paths relative to the default cwd. No workspace sandbox. Result data includes abs_path; "
                "use abs_path when telling the owner where files actually are."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "default": "."}},
                "additionalProperties": False,
            },
        },
        {
            "name": "read",
            "description": (
                "Read a UTF-8 text file from the host filesystem. Accepts absolute "
                "paths or paths relative to the default cwd. No workspace sandbox. Result data includes abs_path; "
                "use abs_path when reporting file location."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "start_line": {"type": "integer", "default": 1},
                    "lines": {"type": "integer", "default": 120},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "log_tail",
            "description": (
                "Tail an explicit log/text file path from the host filesystem. Use log_tail only when "
                "the owner gives a concrete file path (absolute or relative to the default cwd). "
                "For systemd service logs/status such as yangyang-nonebot, do NOT use log_tail; "
                "use shell with journalctl/systemctl instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}, "lines": {"type": "integer", "default": 80}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
        {
            "name": "python",
            "description": (
                "Run a Python 3 code snippet on the host with a timeout. The runner "
                "has full host filesystem visibility and inherits the default cwd. "
                "No command blacklist, no keyword safety valve, no workspace sandbox — owner-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {"code": {"type": "string"}, "timeout_seconds": {"type": "integer", "default": 30}},
                "required": ["code"],
                "additionalProperties": False,
            },
        },
        {
            "name": "shell",
            "description": (
                "Run a shell command on the host with a timeout (bash via $SHELL or /bin/bash). "
                "Cwd is the default cwd; the command may use absolute paths to operate anywhere "
                "the host user can reach. For systemd service logs/status, prefer real host commands "
                "such as `journalctl -u yangyang-nonebot -n 50 --no-pager` and "
                "`systemctl status yangyang-nonebot --no-pager -l`; if unavailable, return the real error. "
                "No command blacklist, no keyword safety valve, no workspace sandbox — owner-only."
            ),
            "parameters": {
                "type": "object",
                "properties": {"command": {"type": "string"}, "timeout_seconds": {"type": "integer", "default": 30}},
                "required": ["command"],
                "additionalProperties": False,
            },
        },
        {
            "name": "write",
            "description": (
                "Write or append UTF-8 text to a host file. Accepts absolute paths or "
                "paths relative to the default cwd. Parent directories are auto-created. "
                "No workspace sandbox — owner-only. Result data includes abs_path; use abs_path when reporting where it wrote. "
                "Before calling write, the target file path must be concrete. "
                "If the owner says ambiguous phrases like 那个txt/那个文件/冷备份那个/上次那个 without an explicit filename or path, "
                "first use list/read/shell to locate candidates and ask the owner to confirm; do not guess a file and write."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                    "append": {"type": "boolean", "default": False},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
        {
            "name": "pack",
            "description": (
                "Create a tar.gz archive from host filesystem paths (absolute or "
                "relative to the default cwd). No workspace sandbox — owner-only. Result data includes abs_output; "
                "use abs_output when reporting archive location."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}},
                    "output": {"type": "string"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "get_tool_loop_max_steps",
            "description": (
                "Read runtime_config owner_toolbox_light_native_loop_max_steps for the owner-private "
                "native tool loop. Use when the owner asks what the current tool-loop/max_steps/tool-call "
                "step limit is. Owner-private only."
            ),
            "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "set_tool_loop_max_steps",
            "description": (
                "Write runtime_config owner_toolbox_light_native_loop_max_steps for the owner-private "
                "native tool loop. Parameter value may be an integer or string; values below 1 are "
                "normalized to 1, and there is intentionally no upper clamp. Owner-private only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {
                        "description": "New max_steps value. Integer or string; minimum normalized to 1; no upper limit.",
                        "anyOf": [{"type": "integer"}, {"type": "string"}],
                    }
                },
                "required": ["value"],
                "additionalProperties": False,
            },
        },
        {
            "name": "query_token_usage",
            "description": (
                "Query recorded token usage from the local token usage ledger. Use when owner asks 查询token / 看token / 当前token用量 / token花了多少. "
                "Owner-private only. Return natural summary; never expose database/log absolute paths, API keys, tokens, or base_url."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "hours": {"type": "integer", "description": "Optional recent-hours window, e.g. 1 for last hour."},
                    "period": {"type": "string", "enum": ["all", "hour", "today", "month"], "description": "Stats period: all/current hour/today/current month."},
                    "group_by": {"type": "string", "enum": ["none", "model", "hour", "day", "month", "all"], "description": "Optional grouping dimension."}
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "isaac_p0",
            "description": (
                "Route an owner-private Isaac/I叔 read-only Agent Bus P0 request. When the owner asks I叔/艾萨克 "
                "to inspect AgentBus/黑奴工厂/Nekro worker factory/validator/collector status, call this tool with "
                "command_text='agentbus factory' and task_type='agentbus_factory_report'; do not answer from memory or invent factory status. "
                "Also use this tool for low-risk Isaac diagnostics such as health/status/workspace report/help/dry_run plan. "
                "This tool may call Isaac's configured model profile to choose a readonly tool, but must not do shell, service control, config/memory write; group/non-owner entrypoints must not call this tool."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "command_text": {"type": "string", "description": "Sanitized Isaac command text, e.g. health, workspace report, dry_run plan, agentbus factory."},
                    "task_type": {"type": "string", "enum": ["health_report", "workspace_report", "dry_run_plan", "help_report", "agentbus_factory_report"], "description": "Optional explicit P0 task type."}
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "list_model_profiles",
            "description": (
                "List model profiles for the model profile switcher. scope may be private, group, or current. "
                "Owner private chat default current resolves to private. Always reports private_active and group_active. "
                "Never returns secret, base_url, token, or API key values. Future group-entry owner commands must only use group scope. "
                "If owner asks 全量/全部/所有/完整/禁用/disabled models, set include_disabled=true; otherwise the tool returns only enabled profiles."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "enum": ["private", "group", "current"], "default": "current"},
                    "include_disabled": {"type": "boolean", "default": False},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "get_active_model_profile",
            "description": (
                "Get the active model profile for one scope. scope private/group/current; current in owner private chat means private only. "
                "Return also includes both private_active and group_active. No secret/base_url/token is exposed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "enum": ["private", "group", "current"], "default": "current"}
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "get_model_runtime_chain",
            "description": (
                "Get the current runtime model chain for one scope, including active profile and configured fallback_profiles chain. "
                "Use this when owner asks 当前模型、fallback、回退模型、回退链、后备模型. No secret/base_url/token is exposed."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "scope": {"type": "string", "enum": ["private", "group", "current"], "default": "current"}
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "set_active_model_profile",
            "description": (
                "Switch active model profile for exactly one scope. Provide either profile_id or selection_index from list_model_profiles; "
                "the chosen profile must exist and be enabled. Default scope=current; in owner private chat this changes private only and never changes group. "
                "If owner says group/群聊, set scope=group; if owner says private/私聊, set scope=private. "
                "Do not switch all scopes unless the owner explicitly asks for all/全部; this tool intentionally has no all scope."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "profile_id": {"type": "string"},
                    "selection_index": {"type": "integer"},
                    "scope": {"type": "string", "enum": ["private", "group", "current"], "default": "current"},
                },
                "additionalProperties": False,
            },
        },


        {
            "name": "set_model_profile_enabled",
            "description": (
                "Enable or disable exactly one model profile without switching private/group active profile. "
                "Use this when owner says 启用/禁用/打开/关闭 a model. Provide profile_id or selection_index from list_model_profiles. "
                "If owner asks to enable multiple models, call this tool once per model. This tool does not expose secrets."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "profile_id": {"type": "string"},
                    "selection_index": {"type": "integer"},
                    "enabled": {"type": "boolean", "default": True}
                },
                "additionalProperties": False,
            },
        },

        {
            "name": "refresh_model_profiles",
            "description": (
                "Refresh runtime model profiles by calling OpenAI-compatible /models for one provider profile or all configured "
                "openai_compat provider profiles. This writes only sanitized non-secret profile metadata into runtime_config. "
                "Newly discovered profiles default disabled unless enable_discovered=true is explicitly requested. Never expose api key, token, base_url, or env names."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "provider_profile_id": {"type": "string", "description": "Optional provider profile id to refresh, e.g. gpt_5_4 or m2_7. Omit to refresh all openai_compat families."},
                    "enable_discovered": {"type": "boolean", "default": False, "description": "Whether newly discovered profiles should be enabled immediately. Default false."},
                    "timeout_seconds": {"type": "integer", "default": 30},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "test_model_profile",
            "description": (
                "Directly test one model profile without fallback. profile_id optional; default tests the active profile of scope. "
                "scope private/group/current; current in owner private chat means private. Does not use ORDER fallback and returns sanitized errors only."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "profile_id": {"type": "string"},
                    "scope": {"type": "string", "enum": ["private", "group", "current"], "default": "current"},
                    "timeout_seconds": {"type": "integer", "default": 30},
                },
                "additionalProperties": False,
            },
        },
    ]
