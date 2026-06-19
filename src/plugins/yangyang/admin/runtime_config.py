from __future__ import annotations

import copy
import json
import os
import shutil
import threading
from pathlib import Path
from typing import Any

from nonebot.log import logger

from ..core.owner_rules import normalize_uid_list


# ── 默认配置 ──

DEFAULTS: dict[str, Any] = {
    "version": 1,
    "bot_name": "秧秧",
    "owner_uid": "335059272",
    "owner_uids": ["335059272"],
    "owner_nick_private": "漂♂总",
    "owner_nick_group": "漂泊者",
    "member_aliases": {
        "小维": "3916107556",
        "红尘": "2434523727",
        "娅娅": "2690087239",
    },
    "default_group_id": "",
    "primary_group_id": "",
    "dry_run": False,
    "owner_action_nonebot_sender_enabled": False,
    "owner_action_execution_enabled": False,
    "owner_action_allow_send_group_message": False,
    "owner_action_allow_reply_current": False,
    "owner_action_current_session_delivery_enabled": False,
    "owner_action_auto_reply_current_production_enabled": False,
    "owner_action_manual_smoke_enabled": False,
    "owner_action_manual_smoke_owner_only": True,
    "owner_action_delivery_safety_enabled": True,
    "owner_action_delivery_dedup_ttl_seconds": 300,
    "owner_action_delivery_audit_enabled": True,
    "owner_action_delivery_audit_path": "logs/owner_action_delivery_audit.jsonl",
    "owner_engineering_toolbox_enabled": True,
    "owner_engineering_toolbox_low_risk_enabled": True,
    "owner_engineering_toolbox_workspace_root": "",
    "owner_engineering_toolbox_max_read_bytes": 65536,
    "owner_engineering_toolbox_max_read_lines": 120,
    "owner_engineering_toolbox_max_list_entries": 80,
    "owner_engineering_toolbox_max_grep_results": 30,
    "owner_engineering_toolbox_max_grep_files": 200,
    "owner_engineering_toolbox_max_tail_lines": 80,
    "owner_engineering_toolbox_max_pack_files": 100,
    "owner_engineering_toolbox_timeout_seconds": 30,
    "owner_engineering_toolbox_max_output_chars": 6000,
    "owner_engineering_toolbox_audit_enabled": True,
    "owner_engineering_toolbox_audit_path": "logs/owner_engineering_toolbox_audit.jsonl",
    "owner_engineering_toolbox_raw_report_enabled": False,
    "owner_engineering_toolbox_debug_raw_enabled": False,
    "owner_engineering_toolbox_formatter_persona": "default",
    "owner_toolbox_light_native_loop_enabled": True,
    "owner_toolbox_light_native_loop_max_steps": 5,
    "owner_toolbox_light_workspace_root": "",
    "owner_toolbox_light_timeout_seconds": 30,
    "owner_toolbox_light_max_output_chars": 8000,
    "owner_toolbox_light_max_read_bytes": 262144,
    "owner_toolbox_light_max_list_entries": 200,
    "owner_toolbox_light_max_pack_files": 2000,
    "owner_toolbox_result_llm_formatter_enabled": False,
    "owner_toolbox_result_llm_formatter_tier": "v4_flash",
    "owner_toolbox_result_llm_formatter_timeout_seconds": 12,
    "owner_toolbox_result_llm_formatter_max_input_chars": 2000,
    "owner_toolbox_result_llm_formatter_max_output_chars": 220,
    "token_usage_log_path": "logs/token_usage.jsonl",
    "token_usage_hourly_push_enabled": True,
    "token_usage_hourly_push_owner_only": True,
    "token_usage_hourly_push_hours": 1,
    "owner_toolbox_native_audit_enabled": True,
    "owner_toolbox_native_audit_path": "logs/owner_toolbox_native_audit.jsonl",
    "owner_toolbox_progress_push_enabled": True,
    "owner_toolbox_progress_push_min_tools": 1,
    "owner_toolbox_progress_push_compact": True,
    "owner_toolbox_progress_push_events": ["llm_response", "tool_error", "max_steps_hit", "run_done"],
    "owner_toolbox_progress_llm_enabled": True,
    "owner_toolbox_progress_llm_tier": "v4_flash",
    "owner_toolbox_progress_llm_timeout_seconds": 8,
    "owner_engineering_toolbox_nl_enabled": True,
    "owner_engineering_toolbox_llm_parser_enabled": True,
    "owner_engineering_toolbox_llm_parser_primary_enabled": True,
    "owner_engineering_toolbox_llm_parser_tier": "v4_flash",
    "owner_engineering_toolbox_llm_parser_timeout_seconds": 12,
    "owner_engineering_toolbox_write_enabled": True,
    "owner_engineering_toolbox_shell_enabled": True,
    "owner_engineering_toolbox_python_enabled": True,
    "llm_timeout_bucket_enabled": False,
    "llm_timeout_bucket_default": "provider_default",
    "llm_timeout_bucket_override_provider_timeout": False,
    "llm_timeout_buckets": {
        "normal": 45,
        "tool_followup": 90,
        "longform": 150,
        "progress": 12,
    },
    "llm_streaming_enabled": False,
    "llm_streaming_progress_notice_enabled": True,
    "memory_short_term_capture_enabled": False,
    "memory_prompt_injection_enabled": False,
    "memory_prompt_injection_private_enabled": True,
    "memory_prompt_injection_group_mention_enabled": True,
    "memory_prompt_injection_group_silent_enabled": False,
    "memory_daily_summary_enabled": False,
    "memory_capture_audit_enabled": True,
    "memory_root": "",
    "memory_capture_audit_path": "logs/memory_capture_audit.jsonl",
    "memory_short_term_limit": 100,
    "memory_prompt_char_budget": 4800,
    "memory_prompt_short_term_item_limit": 50,
    "memory_long_term_retrieval_top_k": 5,
    "memory_long_term_retrieval_char_budget": 900,
    "memory_pipeline_interval_minutes": 30,
    "private_context_task_anchor_enabled": True,
    "private_context_task_anchor_char_budget": 600,
    "private_context_task_anchor_turn_ttl": 12,
    "private_context_rolling_summary_enabled": False,
    "private_context_rolling_summary_char_budget": 500,
    "private_context_rolling_summary_update_min_turns": 2,
    "private_context_rolling_summary_persist_enabled": False,
    "private_context_rolling_summary_state_path": "data/private_context_session_state.json",
    "private_context_tool_result_summary_enabled": False,
    "private_context_tool_result_error_only_default": True,
    "prompt_overlay": {
        "owner_private_enabled": False,
        "owner_private_text": "",
        "owner_private_updated_at": "",
        "owner_private_updated_by": "",
    },
    "owner_action_allow_internal_control": False,
    "pippit_mcp_enabled": False,
    "pippit_mcp_working_directory": "",
    "pippit_mcp_state_path": "data/pippit_mcp_state.json",
    "pippit_mcp_cli_command": "pippit-tool-cli",
    "pippit_mcp_cli_mode": "scripts",
    "pippit_mcp_python_executable": "python3",
    "pippit_mcp_submit_script": "submit_run.py",
    "pippit_mcp_get_thread_script": "get_thread.py",
    "pippit_mcp_upload_script": "upload_file.py",
    "pippit_mcp_download_script": "download_results.py",
    "pippit_mcp_daily_limit_per_key": 60,
    "pippit_mcp_poll_interval_seconds": 3.0,
    "pippit_mcp_poll_timeout_seconds": 300,
    "pippit_mcp_credentials": [],
    "known_bot_uids": [],
    "models": {
        "v4_flash": {
            "model": "deepseek-v4-flash",
            "enabled": True,
        },
        "v4_pro": {
            "model": "deepseek-v4-pro",
            "enabled": True,
        },
        "gpt_5_4": {
            "model": "gpt-5.4",
            "enabled": False,
        },
        "gpt_5_5": {
            "model": "gpt-5.5",
            "enabled": False,
        },
        "m2_7": {
            "model": "MiniMax-M2.7",
            "enabled": False,
        },
        "gemini_3_1_pro_high": {
            "model": "gemini-3.1-pro-high",
            "enabled": False,
        },
    },
    "model_profile_switcher": {
        "active_profile_private": "v4_flash",
        "active_profile_group": "v4_flash",
    },
    "isaac": {
        "model_profile": "v4_pro",
    },
    "providers": {
        "v4_pro": {
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "api_key_env": "DEEPSEEK_API_KEY",
            "timeout": 60,
            "cooldown_on_fail": 120,
            "enabled": True,
        },
        "v4_flash": {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "api_key_env": "DEEPSEEK_API_KEY",
            "timeout": 30,
            "cooldown_on_fail": 60,
            "enabled": True,
        },
        "gpt_5_4": {
            "provider": "openai_compat",
            "model": "gpt-5.4",
            "api_key_env": "GPT_API_KEY",
            "base_url_env": "GPT_BASE_URL",
            "timeout": 120,
            "cooldown_on_fail": 300,
            "enabled": False,
        },
        "gpt_5_5": {
            "provider": "openai_compat",
            "model": "gpt-5.5",
            "api_key_env": "GPT_API_KEY",
            "base_url_env": "GPT_BASE_URL",
            "timeout": 120,
            "cooldown_on_fail": 300,
            "enabled": False,
        },
        "m2_7": {
            "provider": "openai_compat",
            "model": "MiniMax-M2.7",
            "api_key_env": "MINIMAX_API_KEY",
            "base_url_env": "MINIMAX_BASE_URL",
            "timeout": 60,
            "cooldown_on_fail": 120,
            "enabled": False,
        },
        "gemini_3_1_pro_high": {
            "provider": "openai_compat",
            "model": "gemini-3.1-pro-high",
            "api_key_env": "GEMINI_API_KEY",
            "base_url_env": "GEMINI_BASE_URL",
            "timeout": 120,
            "cooldown_on_fail": 300,
            "enabled": False,
        },
        "minimax_m3": {
            "provider": "anthropic_compat",
            "model": "MiniMax-M3",
            "api_key_env": "MINIMAX_API_KEY",
            "base_url_env": "MINIMAX_BASE_URL",
            "timeout": 120,
            "cooldown_on_fail": 300,
            "enabled": False,
        },
    },
    "behavior": {
        "cooldown_global_s": 60,
        "cooldown_topic_rounds": 3,
        "cooldown_topic_s": 300,
        "daily_auto_reply_limit": 15,
        "bot_loop_enabled": True,
        "bot_loop_recent_limit": 8,
        "bot_loop_min_bot_messages": 3,
        "bot_loop_cooldown_seconds": 300,
    },
    "features": {
        "smart_chat_enabled": False,
        "tts_enabled": False,
        "emoji_enabled": True,
    },
}


# ── 运行时配置 ──

class RuntimeConfig:
    """运行时配置管理器，支持点号路径读写与原子保存。"""

    PATH = "data/runtime_config.json"
    # 使用 RLock 避免 _load/set 持锁调用 save 时产生重入死锁。
    # 未来接 Web API 热更新时，可改为 asyncio.Lock，或采用「后台写原子文件 → 主循环 reload」模式。
    _lock = threading.RLock()

    def __init__(self, defaults: dict[str, Any] | None = None, path: str | Path | None = None, explicit_overrides: dict[str, Any] | None = None):
        self.defaults = copy.deepcopy(defaults or DEFAULTS)
        self.path = Path(path or self.PATH)
        self.explicit_overrides = copy.deepcopy(explicit_overrides or {})
        self.overrides = self._load()

    def _apply_explicit_overrides(self, data: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        if not isinstance(data, dict):
            return copy.deepcopy(self.explicit_overrides), bool(self.explicit_overrides)
        if not self.explicit_overrides:
            return copy.deepcopy(data), False

        result = copy.deepcopy(data)
        changed = False

        def _merge(dst: dict[str, Any], src: dict[str, Any]) -> None:
            nonlocal changed
            for key, value in src.items():
                if isinstance(value, dict) and isinstance(dst.get(key), dict):
                    _merge(dst[key], value)
                    continue
                if dst.get(key) != value:
                    dst[key] = copy.deepcopy(value)
                    changed = True

        _merge(result, self.explicit_overrides)
        return result, changed

    def _load(self) -> dict[str, Any]:
        """加载配置并按默认值 normalize 回填缺失字段。"""
        with self._lock:
            if not self.path.exists():
                data = copy.deepcopy(self.defaults)
                data, _ = self._apply_explicit_overrides(data)
                self.save(data)
                return data

            try:
                with self.path.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
            except Exception:
                logger.exception("RuntimeConfig: failed to load config, fallback to defaults: %s", self.path)
                data = copy.deepcopy(self.defaults)
                data, _ = self._apply_explicit_overrides(data)
                self.save(data)
                return data

            normalized, changed = self._normalize_with_defaults(self.defaults, raw)
            normalized, override_changed = self._apply_explicit_overrides(normalized)
            if changed or override_changed:
                self.save(normalized)
            return normalized

    def save(self, data: dict[str, Any]) -> bool:
        """原子保存配置: tmp → bak → replace。"""
        with self._lock:
            tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            bak_path = self.path.with_suffix(self.path.suffix + ".bak")
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)

                with tmp_path.open("w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
                    f.flush()
                    os.fsync(f.fileno())

                if self.path.exists():
                    try:
                        shutil.copy2(self.path, bak_path)
                    except Exception:
                        logger.exception("RuntimeConfig: failed to backup config: %s", bak_path)

                os.replace(tmp_path, self.path)
                return True
            except Exception:
                logger.exception("RuntimeConfig: failed to save config: %s", self.path)
                try:
                    if tmp_path.exists():
                        tmp_path.unlink()
                except Exception:
                    logger.exception("RuntimeConfig: failed to cleanup tmp config: %s", tmp_path)
                return False

    def get(self, path: str, default: Any = None) -> Any:
        """按点号路径读取配置，如 get('models.v4_flash.model')。"""
        if not path:
            return self.overrides

        current: Any = self.overrides
        for part in path.split("."):
            if not isinstance(current, dict) or part not in current:
                return default
            current = current[part]
        return current

    def get_bool(self, path: str, default: bool = False, env_key: str | None = None) -> bool:
        """读取布尔配置，支持环境变量覆盖。"""
        if env_key:
            env_value = os.getenv(env_key)
            if env_value is not None:
                return str(env_value).strip().lower() in {"1", "true", "yes", "on"}

        value = self.get(path, default)
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "on"}

    def set(self, path: str, value: Any) -> bool:
        """按点号路径写入配置并落盘。"""
        if not path:
            logger.error("RuntimeConfig: set path is empty")
            return False

        with self._lock:
            try:
                new_data = copy.deepcopy(self.overrides)
                current: Any = new_data
                parts = path.split(".")

                for part in parts[:-1]:
                    if not isinstance(current, dict):
                        logger.error("RuntimeConfig: invalid path: %s", path)
                        return False
                    if part not in current or not isinstance(current[part], dict):
                        current[part] = {}
                    current = current[part]

                current[parts[-1]] = value
                normalized, _ = self._normalize_with_defaults(self.defaults, new_data)
                if not self.save(normalized):
                    return False

                self.overrides = normalized
                return True
            except Exception:
                logger.exception("RuntimeConfig: failed to set path: %s", path)
                return False

    def reload(self) -> dict[str, Any]:
        """重新从磁盘加载配置。"""
        self.overrides = self._load()
        return self.overrides

    def _normalize_with_defaults(self, defaults: dict[str, Any], data: Any) -> tuple[dict[str, Any], bool]:
        """递归补齐默认字段，不删除用户自定义字段。"""
        if not isinstance(data, dict):
            normalized = copy.deepcopy(defaults)
            normalized["owner_uids"] = normalize_uid_list(
                normalized.get("owner_uids", []),
                normalized.get("owner_uid"),
            )
            return normalized, True

        changed = False
        result = copy.deepcopy(data)

        for key, default_value in defaults.items():
            if key not in result:
                result[key] = copy.deepcopy(default_value)
                changed = True
                continue

            if isinstance(default_value, dict):
                merged, sub_changed = self._normalize_with_defaults(default_value, result[key])
                result[key] = merged
                changed = changed or sub_changed

        normalized_owner_uids = normalize_uid_list(
            result.get("owner_uids", []),
            result.get("owner_uid"),
        )
        if result.get("owner_uids") != normalized_owner_uids:
            result["owner_uids"] = normalized_owner_uids
            changed = True

        return result, changed
