from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import os
import time
import uuid
from collections.abc import Callable
from typing import Any

from nonebot.log import logger

from .model.provider_base import ModelProvider
from .model.provider_deepseek import DeepSeekV4Provider
from .model.provider_minimax import MiniMaxM2Provider
from .model.provider_openai_compat import OpenAICompatibleProvider
from .model.provider_anthropic import AnthropicCompatProvider
from .token_usage import append_token_usage_event
from .model_profile_switcher import (
    choose_profile_for_channel,
    get_model_profile_descriptor,
    iter_profile_ids,
    refresh_model_profiles_from_models,
    validate_model_profile_enabled,
)


class ModelRouter:
    """模型路由与降级调用。

    MVP 阶段优先只使用 V4 Flash；V4 Pro / GPT-5.5 保留配置占位。
    OpenAI 兼容客户端按需懒加载，避免未安装 openai 时插件导入失败。
    """

    TIERS: dict[str, dict[str, Any]] = {
        "v4_flash": {
            "provider": "deepseek",
            "model": "deepseek-v4-flash",
            "timeout": 30,
            "cooldown_on_fail": 60,
            "description": "日常水群 / 简单回复",
        },
        "v4_pro": {
            "provider": "deepseek",
            "model": "deepseek-v4-pro",
            "timeout": 60,
            "cooldown_on_fail": 120,
            "description": "架构分析 / 长文报告",
        },
        "gpt_5_4": {
            "provider": "openai_compat",
            "model": "gpt-5.4",
            "timeout": 120,
            "cooldown_on_fail": 300,
            "description": "GPT 5.4 / 代码生成 / 复杂开发",
        },
        "gpt_5_5": {
            "provider": "openai_compat",
            "model": "gpt-5.5",
            "timeout": 120,
            "cooldown_on_fail": 300,
            "description": "GPT 5.5 / 代码生成 / 复杂开发",
        },
        "m2_7": {
            "provider": "openai_compat",
            "model": "MiniMax-M2.7",
            "timeout": 60,
            "cooldown_on_fail": 120,
            "description": "MiniMax M2.7 / 群聊与低风险氛围",
        },
        "gemini_3_1_pro_high": {
            "provider": "openai_compat",
            "model": "gemini-3.1-pro-high",
            "timeout": 120,
            "cooldown_on_fail": 300,
            "description": "Gemini 3.1 Pro High / 情绪价值与低风险测试",
        },
    }

    ORDER = ["v4_flash", "v4_pro", "gpt_5_4", "gpt_5_5", "m2_7", "gemini_3_1_pro_high"]
    DRY_RUN_TEXT = "[dry_run] 模拟回复：主链路已跑通。"
    LOCAL_SAFE_TEXT = "我这边先换个安全说法：刚才那段内容不适合直接展开，我可以继续帮你做概括、改写或给出下一步建议。"
    SENSITIVE_ERROR_TYPES = ("sensitive_words_detected", "content_filter")

    def __init__(self, runtime_cfg: Any):
        self.runtime_cfg = runtime_cfg
        self.fail_until: dict[str, float] = {}
        self.providers: dict[str, ModelProvider] = self._build_default_providers()
        self.last_call_sensitive_failure: bool = False
        self.last_call_error_type: str = ""
        self.last_call_request_id: str = ""
        self.last_call_hash: str = ""
        self.last_call_messages_len: int = 0
        self.last_call_tool_calls: list[dict[str, Any]] = []
        self.last_call_requested_tier: str = ""
        self.last_call_resolved_profile: str = ""
        self.last_call_channel_scope: str = ""
        self.last_call_fallback_used: bool = False
        self.last_call_fallback_from: str = ""
        self.last_call_fallback_to: str = ""
        self.last_call_fallback_reason: str = ""
        self.last_call_fallback_at: float = 0.0
        self.fallback_history: list[dict[str, Any]] = []
        self.fallback_stats: dict[str, Any] = {"from_profiles": {}, "to_profiles": {}, "scope_counts": {}, "reason_counts": {}, "total_hits": 0}
        self.last_tool_loop_max_steps: int = 0
        self.last_call_timeout_bucket: str = ""
        self.last_call_timeout_seconds: float = 0.0
        self.last_call_interaction_phase: str = ""
        self.last_call_streaming_enabled: bool = False

    def _cfg_get(self, path: str, default: Any = None) -> Any:
        try:
            if self.runtime_cfg is not None and hasattr(self.runtime_cfg, "get"):
                value = self.runtime_cfg.get(path, default)
                return default if value is None else value
        except Exception:
            logger.exception("ModelRouter: failed to read config: %s", path)
        return default

    def _is_dry_run(self) -> bool:
        env_value = os.getenv("YANGYANG_DRY_RUN")
        if env_value is not None:
            return str(env_value).strip().lower() in {"1", "true", "yes", "on"}

        if self.runtime_cfg is not None and hasattr(self.runtime_cfg, "get_bool"):
            try:
                return bool(self.runtime_cfg.get_bool("dry_run", False))
            except Exception:
                logger.exception("ModelRouter: failed to read dry_run from runtime config")

        return bool(self._cfg_get("dry_run", False))

    def _build_default_providers(self) -> dict[str, ModelProvider]:
        return {
            "deepseek": DeepSeekV4Provider(self.runtime_cfg),
            "minimax": MiniMaxM2Provider(available=False),
            "openai_compat": OpenAICompatibleProvider(self.runtime_cfg),
            "anthropic_compat": AnthropicCompatProvider(self.runtime_cfg),
        }

    def register_provider(self, provider: ModelProvider) -> None:
        self.providers[provider.provider_name] = provider

    def _tier_enabled(self, tier: str) -> bool:
        providers_enabled = self._cfg_get(f"providers.{tier}.enabled", None)
        if providers_enabled is not None:
            return bool(providers_enabled)
        models_enabled = self._cfg_get(f"models.{tier}.enabled", None)
        if models_enabled is not None:
            return bool(models_enabled)
        if tier in self.TIERS:
            return bool(self.TIERS[tier].get("enabled", False))
        return False

    def _provider_name(self, tier: str) -> str:
        return str(
            self._cfg_get(
                f"providers.{tier}.provider",
                self.TIERS.get(tier, {}).get("provider", "deepseek"),
            )
        )

    def _model_name(self, tier: str) -> str:
        provider_model = self._cfg_get(f"providers.{tier}.model", None)
        if provider_model:
            return str(provider_model)
        fallback_model = self.TIERS.get(tier, {}).get("model", tier)
        return str(self._cfg_get(f"models.{tier}.model", fallback_model))

    def _tier_timeout(self, tier: str) -> float:
        fallback_timeout = self.TIERS.get(tier, {}).get("timeout", 30)
        return float(self._cfg_get(f"providers.{tier}.timeout", fallback_timeout))

    def _timeout_bucket_enabled(self) -> bool:
        return bool(self._cfg_get("llm_timeout_bucket_enabled", False))

    def _streaming_enabled(self, allow_streaming: bool | None = None) -> bool:
        configured = bool(self._cfg_get("llm_streaming_enabled", False))
        if allow_streaming is None:
            return configured
        return bool(allow_streaming) and configured

    def _resolve_timeout_bucket(self, timeout_bucket: str | None = None) -> str:
        bucket = str(timeout_bucket or self._cfg_get("llm_timeout_bucket_default", "") or "").strip()
        return bucket or "provider_default"

    def _bucket_timeout_seconds(self, bucket: str) -> float | None:
        buckets = self._cfg_get("llm_timeout_buckets", {})
        if not isinstance(buckets, dict):
            return None
        value = buckets.get(bucket)
        if value is None:
            return None
        try:
            return max(1.0, min(600.0, float(value)))
        except Exception:
            return None

    def _resolve_timeout_seconds(self, tier: str, timeout_bucket: str | None = None) -> tuple[str, float]:
        bucket = self._resolve_timeout_bucket(timeout_bucket)
        provider_timeout = self._tier_timeout(tier)
        if not self._timeout_bucket_enabled() or bucket in {"", "provider_default", "default", "tier_default"}:
            return bucket, provider_timeout
        bucket_timeout = self._bucket_timeout_seconds(bucket)
        if bucket_timeout is None:
            return bucket, provider_timeout
        override_provider = bool(self._cfg_get("llm_timeout_bucket_override_provider_timeout", False))
        if override_provider:
            return bucket, bucket_timeout
        return bucket, max(provider_timeout, bucket_timeout)

    def _tier_cooldown_on_fail(self, tier: str) -> float:
        fallback_cooldown = self.TIERS.get(tier, {}).get("cooldown_on_fail", 60)
        return float(self._cfg_get(f"providers.{tier}.cooldown_on_fail", fallback_cooldown))

    def _is_available(self, model: str) -> bool:
        return time.time() >= self.fail_until.get(model, 0.0)

    def _mark_fail(self, model: str, cooldown: float) -> None:
        self.fail_until[model] = time.time() + max(float(cooldown), 0.0)

    def _configured_fallback_profiles(self, *, requested_tier: str, resolved_tier: str, resolved_channel: str) -> list[str]:
        raw: list[Any] = []
        if resolved_channel == "private":
            chain = self._cfg_get("model_profile_switcher.fallback_profiles_private", None)
            if isinstance(chain, list):
                raw.extend(chain)
            legacy = str(self._cfg_get("model_profile_switcher.fallback_profile_private", "") or "").strip()
            if legacy:
                raw.append(legacy)
        elif resolved_channel == "group":
            chain = self._cfg_get("model_profile_switcher.fallback_profiles_group", None)
            if isinstance(chain, list):
                raw.extend(chain)
            legacy = str(self._cfg_get("model_profile_switcher.fallback_profile_group", "") or "").strip()
            if legacy:
                raw.append(legacy)
        else:
            isaac_primary = str(self._cfg_get("isaac.model_profile", "") or "").strip()
            if requested_tier == isaac_primary or resolved_tier == isaac_primary:
                chain = self._cfg_get("isaac.fallback_profiles", None)
                if isinstance(chain, list):
                    raw.extend(chain)
                legacy = str(self._cfg_get("isaac.fallback_model_profile", "") or "").strip()
                if legacy:
                    raw.append(legacy)
        out: list[str] = []
        for item in raw:
            pid = str(item or "").strip()
            if pid and pid != resolved_tier and pid not in out:
                out.append(pid)
        return out

    def _is_retryable_fallback_reason(self, reason: str, exc: Exception | None = None) -> bool:
        blob = str(reason or "").strip().lower()
        if exc is not None:
            blob = (blob + " " + exc.__class__.__name__ + " " + str(exc)).lower()
        retryable_markers = (
            "timeout",
            "timedout",
            "provider_unavailable",
            "rate_limited",
            "upstream_timeout",
            "upstream_error",
            "request_failed",
            "apiconnectionerror",
            "apiconnection",
            "connectionerror",
            "connecterror",
            "remotedisconnected",
            "serviceunavailable",
            "temporar",
            "502",
            "503",
            "504",
            "429",
        )
        fatal_markers = (
            "sensitive_words_detected",
            "content_filter",
            "auth_failed",
            "model_not_found",
            "missing_api_key",
            "missing_base_url_env",
            "missing openai_api_key",
            "profile_not_found",
            "profile_disabled",
        )
        if any(m in blob for m in fatal_markers):
            return False
        return any(m in blob for m in retryable_markers)

    def _trim_fallback_history(self, limit: int = 50) -> None:
        keep = max(1, int(limit or 50))
        if len(self.fallback_history) > keep:
            self.fallback_history = self.fallback_history[-keep:]

    def _snapshot_fallback_runtime(self) -> dict[str, Any]:
        return {
            "used": bool(self.last_call_fallback_used),
            "from_profile": str(self.last_call_fallback_from or ""),
            "to_profile": str(self.last_call_fallback_to or ""),
            "reason": str(self.last_call_fallback_reason or ""),
            "at": float(self.last_call_fallback_at or 0.0),
            "requested_tier": str(self.last_call_requested_tier or ""),
            "resolved_profile": str(self.last_call_resolved_profile or ""),
            "channel_scope": str(self.last_call_channel_scope or ""),
        }

    def _fallback_observability(self) -> dict[str, Any]:
        return {
            "runtime": self._snapshot_fallback_runtime(),
            "history": list(self.fallback_history),
            "stats": dict(self.fallback_stats),
        }

    def _record_request_fallback(self, *, from_profile: str, to_profile: str, reason: str) -> None:
        self.last_call_fallback_used = True
        self.last_call_fallback_from = str(from_profile or "")
        self.last_call_fallback_to = str(to_profile or "")
        self.last_call_fallback_reason = str(reason or "")
        self.last_call_fallback_at = time.time()
        scope = str(self.last_call_channel_scope or "")
        event = {
            "from_profile": self.last_call_fallback_from,
            "to_profile": self.last_call_fallback_to,
            "reason": self.last_call_fallback_reason,
            "at": self.last_call_fallback_at,
            "requested_tier": str(self.last_call_requested_tier or ""),
            "resolved_profile": str(self.last_call_resolved_profile or ""),
            "channel_scope": scope,
            "request_id": str(self.last_call_request_id or ""),
        }
        self.fallback_history.append(event)
        self._trim_fallback_history()
        self.fallback_stats["total_hits"] = int(self.fallback_stats.get("total_hits") or 0) + 1
        for bucket, key in (("from_profiles", self.last_call_fallback_from), ("to_profiles", self.last_call_fallback_to), ("scope_counts", scope or "unknown"), ("reason_counts", self.last_call_fallback_reason or "unknown")):
            mapping = self.fallback_stats.get(bucket)
            if not isinstance(mapping, dict):
                mapping = {}
                self.fallback_stats[bucket] = mapping
            mapping[str(key or "unknown")] = int(mapping.get(str(key or "unknown")) or 0) + 1

    def _messages_fingerprint(self, messages: list[dict[str, Any]]) -> tuple[str, int]:
        """返回 messages 的不可逆哈希与总长度；禁止写入原文。"""
        lengths: list[int] = []
        roles: list[str] = []
        h = hashlib.sha256()
        for item in messages or []:
            role = str(item.get("role", ""))
            content = str(item.get("content", ""))
            roles.append(role)
            lengths.append(len(content))
            h.update(role.encode("utf-8", errors="ignore"))
            h.update(b"\0")
            h.update(content.encode("utf-8", errors="ignore"))
            h.update(b"\0")
        meta = {"roles": roles, "lengths": lengths, "count": len(messages or [])}
        h.update(json.dumps(meta, sort_keys=True).encode("utf-8"))
        return h.hexdigest()[:16], sum(lengths)

    def _detect_sensitive_error_type(self, exc: Exception) -> str:
        """识别供应商敏感/内容过滤类错误，不记录错误原文。"""
        candidates: list[str] = [exc.__class__.__name__]
        for attr in ("code", "type", "param"):
            value = getattr(exc, attr, None)
            if value:
                candidates.append(str(value))
        response = getattr(exc, "response", None)
        if response is not None:
            try:
                candidates.append(str(getattr(response, "status_code", "")))
            except Exception:
                pass
        lowered = " ".join(candidates).lower()
        if "sensitive_words_detected" in lowered or "sensitive" in lowered:
            return "sensitive_words_detected"
        if "content_filter" in lowered or "contentfilter" in lowered or "filtered" in lowered:
            return "content_filter"
        # 最后一层仅用于识别错误类型，绝不把异常文本写入日志。
        text = str(exc).lower()
        if "sensitive_words_detected" in text or "sensitive" in text:
            return "sensitive_words_detected"
        if "content_filter" in text or "contentfilter" in text or "filtered" in text:
            return "content_filter"
        return ""

    def _build_safe_fallback_messages(self, messages: list[dict[str, Any]], error_type: str) -> list[dict[str, Any]]:
        """构造脱敏 fallback messages：只保留角色、长度、轮次数，不带原文。"""
        role_counts: dict[str, int] = {}
        total_len = 0
        for item in messages or []:
            role = str(item.get("role", "unknown"))[:24]
            role_counts[role] = role_counts.get(role, 0) + 1
            total_len += len(str(item.get("content", "")))
        return [
            {
                "role": "system",
                "content": (
                    "你是安全改写 fallback。上游请求触发内容安全保险丝；"
                    "不要复述、猜测或还原原始内容，只给出简短、合规、可继续对话的回复。"
                ),
            },
            {
                "role": "user",
                "content": (
                    f"原始消息已脱敏丢弃。error_type={error_type}; "
                    f"message_count={len(messages or [])}; total_length={total_len}; roles={role_counts}. "
                    "请用自然中文说明可以改为安全摘要、改写或继续提供下一步帮助。"
                ),
            },
        ]

    def _normalize_tools_for_provider(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        normalized: list[dict[str, Any]] = []
        for item in tools:
            if not isinstance(item, dict):
                continue
            function = item.get("function") if isinstance(item.get("function"), dict) else None
            if str(item.get("type") or "") == "function" and function is not None:
                normalized.append(item)
                continue
            name = str(item.get("name") or (function or {}).get("name") or "").strip()
            if not name:
                continue
            normalized.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": str(item.get("description") or ""),
                        "parameters": item.get("parameters") or {"type": "object", "properties": {}},
                    },
                }
            )
        return normalized or None

    def _normalize_tool_calls(self, tool_calls: Any) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for idx, call in enumerate(tool_calls or []):
            call_id = f"tool_call_{idx}"
            call_type = "function"
            name = ""
            arguments: Any = {}
            if isinstance(call, dict):
                call_id = str(call.get("id") or call_id)
                call_type = str(call.get("type") or call_type)
                function = call.get("function") if isinstance(call.get("function"), dict) else {}
                name = str(call.get("name") or function.get("name") or "").strip()
                arguments = call.get("arguments", function.get("arguments", {}))
            else:
                call_id = str(getattr(call, "id", "") or call_id)
                call_type = str(getattr(call, "type", "") or call_type)
                function = getattr(call, "function", None)
                name = str(getattr(function, "name", "") or getattr(call, "name", "") or "").strip()
                arguments = getattr(function, "arguments", None)
                if arguments is None:
                    arguments = getattr(call, "arguments", {})
            if not name:
                continue
            normalized.append({"id": call_id, "type": call_type or "function", "name": name, "arguments": arguments})
        return normalized

    def _parse_tool_call_arguments(self, arguments: Any) -> dict[str, Any]:
        if isinstance(arguments, dict):
            return dict(arguments)
        if arguments is None:
            return {}
        if isinstance(arguments, str):
            raw = arguments.strip()
            if not raw:
                return {}
            try:
                parsed = json.loads(raw)
                return dict(parsed) if isinstance(parsed, dict) else {"value": parsed}
            except Exception:
                return {"_raw": arguments}
        return {"value": arguments}

    def _tool_call_message_payload(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        arguments = tool_call.get("arguments", {})
        if not isinstance(arguments, str):
            arguments = json.dumps(arguments if arguments is not None else {}, ensure_ascii=False)
        return {
            "id": str(tool_call.get("id") or "tool_call"),
            "type": "function",
            "function": {"name": str(tool_call.get("name") or ""), "arguments": arguments},
        }

    def _tool_result_to_content(self, result: Any) -> str:
        if isinstance(result, str):
            return result
        if isinstance(result, dict):
            return json.dumps(result, ensure_ascii=False)
        payload: dict[str, Any] = {}
        for attr in ("handled", "allowed", "reason", "reply", "tool_name", "output", "data"):
            if hasattr(result, attr):
                payload[attr] = getattr(result, attr)
        if payload:
            return json.dumps(payload, ensure_ascii=False, default=str)
        return str(result)

    async def call_with_tool_loop(
        self,
        tier: str,
        messages: list[dict[str, Any]],
        *,
        tools: list[dict[str, Any]],
        tool_executor: Callable[[str, dict[str, Any]], Any],
        temperature: float = 0.72,
        session_id: str | None = None,
        tool_choice: Any = "auto",
        max_steps: int | None = None,
        channel: str | None = None,
        message: Any = None,
        progress_callback: Callable[[str, dict[str, Any]], Any] | None = None,
        run_id: str | None = None,
        timeout_bucket: str | None = None,
        interaction_phase: str | None = None,
        allow_streaming: bool | None = None,
    ) -> tuple[str, str, list[dict[str, Any]]]:
        """Run a small OpenAI-compatible tool loop and return natural model text.

        The router only moves tool calls between model/provider and the supplied
        executor.  It does not expose traces to users; callers decide whether to
        show trace/debug output.
        """
        active_messages: list[dict[str, Any]] = [dict(item) for item in (messages or [])]
        trace: list[dict[str, Any]] = []
        seen_tool_call_keys: set[str] = set()
        actual_tier = tier
        configured_steps = self._cfg_get("owner_toolbox_light_native_loop_max_steps", None)
        if configured_steps is None:
            configured_steps = self._cfg_get("owner_toolbox_tool_loop_max_steps", None)
        if configured_steps is None:
            configured_steps = self._cfg_get("model_tool_loop_max_steps", 5)
        raw_steps = configured_steps if max_steps is None else max_steps
        try:
            steps = int(raw_steps)
        except Exception:
            steps = 5
        # Owner 私聊工具 loop 全权限：只保留最低值 1，不做 30 等代码侧上限裁剪。
        steps = max(1, steps)
        self.last_tool_loop_max_steps = steps

        async def _emit(event: str, payload: dict[str, Any]) -> None:
            if progress_callback is None:
                return
            try:
                payload.setdefault("run_id", run_id or self.last_call_request_id or "")
                emitted = progress_callback(event, payload)
                if inspect.isawaitable(emitted):
                    await emitted
            except Exception:
                logger.exception("ModelRouter: progress callback failed event=%s", event)

        await _emit("run_start", {"max_steps": steps, "session_id": session_id or "", "channel": channel or ""})
        for step in range(steps):
            await _emit("llm_request_start", {"step": step + 1, "trace_len": len(trace)})
            response_text, actual_tier = await self.call(
                tier,
                active_messages,
                temperature=temperature,
                session_id=session_id,
                tools=tools,
                tool_choice=tool_choice,
                channel=channel,
                message=message,
                timeout_bucket=timeout_bucket,
                interaction_phase=interaction_phase,
                allow_streaming=allow_streaming,
            )
            tool_calls = list(self.last_call_tool_calls or [])
            await _emit("llm_response", {
                "step": step + 1,
                "tier": actual_tier,
                "tool_call_count": len(tool_calls),
                "tool_names": [str(call.get("name") or "") for call in tool_calls],
                "assistant_content_chars": len(str(response_text or "")),
            })
            if tool_calls and str(response_text or "").strip():
                await _emit("assistant_prelude", {
                    "step": step + 1,
                    "tier": actual_tier,
                    "text": str(response_text or ""),
                    "tool_call_count": len(tool_calls),
                    "tool_names": [str(call.get("name") or "") for call in tool_calls],
                })
            if not tool_calls:
                await _emit("run_done", {"steps_used": step + 1, "trace_len": len(trace), "final": True})
                return response_text, actual_tier, trace

            active_messages.append(
                {
                    "role": "assistant",
                    "content": response_text or "",
                    "tool_calls": [self._tool_call_message_payload(call) for call in tool_calls],
                }
            )
            for call in tool_calls:
                name = str(call.get("name") or "").strip()
                args = self._parse_tool_call_arguments(call.get("arguments"))
                call_id = str(call.get("id") or f"tool_call_{len(trace)}")
                ok = True
                loop_guarded = False
                call_key = json.dumps({"name": name, "args": args}, ensure_ascii=False, sort_keys=True, default=str)
                if call_key in seen_tool_call_keys:
                    ok = False
                    loop_guarded = True
                    content = json.dumps(
                        {
                            "handled": True,
                            "allowed": False,
                            "reason": "duplicate_tool_call_loop_guard",
                            "tool_name": name,
                            "data": {"args": args},
                        },
                        ensure_ascii=False,
                        default=str,
                    )
                else:
                    seen_tool_call_keys.add(call_key)
                    await _emit("tool_start", {"step": step + 1, "tool_name": name, "args": args})
                    try:
                        executed = tool_executor(name, args)
                        if inspect.isawaitable(executed):
                            executed = await executed
                        content = self._tool_result_to_content(executed)
                        await _emit("tool_done", {"step": step + 1, "tool_name": name, "ok": True, "result": content})
                    except Exception as exc:
                        ok = False
                        await _emit("tool_error", {"step": step + 1, "tool_name": name, "ok": False, "error_type": exc.__class__.__name__})
                        content = json.dumps(
                            {"handled": True, "allowed": False, "reason": f"tool_exception:{exc.__class__.__name__}"},
                            ensure_ascii=False,
                        )
                active_messages.append({"role": "tool", "tool_call_id": call_id, "name": name, "content": content})
                trace.append(
                    {
                        "step": step + 1,
                        "tool_name": name,
                        "args": args,
                        "ok": ok,
                        "loop_guarded": loop_guarded,
                        "result": content,
                    }
                )

        await _emit("max_steps_hit", {"max_steps": steps, "trace_len": len(trace)})
        active_messages.append(
            {
                "role": "system",
                "content": "工具调用步数已到上限。请只根据已有工具结果，用自然中文直接回复用户；不要继续请求工具。",
            }
        )
        response_text, actual_tier = await self.call(
            tier,
            active_messages,
            temperature=temperature,
            session_id=session_id,
            channel=channel,
            message=message,
            timeout_bucket=timeout_bucket,
            interaction_phase=interaction_phase,
            allow_streaming=allow_streaming,
        )
        await _emit("run_done", {"steps_used": steps, "trace_len": len(trace), "max_steps_hit": True})
        return response_text, actual_tier, trace

    async def call(
        self,
        tier: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.72,
        session_id: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        channel: str | None = None,
        message: Any = None,
        timeout_bucket: str | None = None,
        interaction_phase: str | None = None,
        allow_streaming: bool | None = None,
        stream_callback: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> tuple[str, str]:
        """调用模型，返回 (response_text, actual_tier_used)。

        C1 保险丝：主模型触发 sensitive_words_detected/content_filter 后，禁止原文
        继续重试；后续 tier 仅使用脱敏摘要。日志只保留 request_id/session/hash/长度/错误类型。
        """
        self.last_call_sensitive_failure = False
        self.last_call_error_type = ""
        self.last_call_request_id = uuid.uuid4().hex[:12]
        self.last_call_hash, self.last_call_messages_len = self._messages_fingerprint(messages)
        self.last_call_tool_calls = []
        self.last_call_fallback_used = False
        self.last_call_fallback_from = ""
        self.last_call_fallback_to = ""
        self.last_call_fallback_reason = ""
        self.last_call_timeout_bucket = self._resolve_timeout_bucket(timeout_bucket)
        self.last_call_timeout_seconds = 0.0
        self.last_call_interaction_phase = str(interaction_phase or "")
        self.last_call_streaming_enabled = self._streaming_enabled(allow_streaming)
        requested_tier = str(tier or "v4_flash")
        resolved_tier, resolved_channel = choose_profile_for_channel(
            self.runtime_cfg,
            requested_tier,
            channel=channel,
            message=message,
            session_id=session_id,
        )
        self.last_call_requested_tier = requested_tier
        self.last_call_resolved_profile = resolved_tier
        self.last_call_channel_scope = resolved_channel
        safe_messages: list[dict[str, Any]] | None = None
        provider_tools = self._normalize_tools_for_provider(tools)
        provider_tool_choice = tool_choice if provider_tools is not None else None

        tier = resolved_tier

        if self._is_dry_run():
            logger.info("ModelRouter: dry_run enabled, skip real model call request_id=%s", self.last_call_request_id)
            return self.DRY_RUN_TEXT, "dry_run"

        configured_fallbacks = self._configured_fallback_profiles(requested_tier=requested_tier, resolved_tier=tier, resolved_channel=resolved_channel)
        candidate_order: list[str] = [tier]
        for configured_fallback in configured_fallbacks:
            if configured_fallback and configured_fallback not in candidate_order:
                candidate_order.append(configured_fallback)
        last_error_type = "unknown"
        attempted_primary = False

        for cur_tier in candidate_order:
            if not attempted_primary:
                attempted_primary = True
            elif not self._is_retryable_fallback_reason(last_error_type):
                continue
            if not self._tier_enabled(cur_tier):
                continue

            model = self._model_name(cur_tier)
            if not self._is_available(model):
                continue

            active_messages = safe_messages if safe_messages is not None else messages
            try:
                provider_name = self._provider_name(cur_tier)
                provider = self.providers.get(provider_name)
                if provider is None or not provider.is_available:
                    last_error_type = f"provider_unavailable:{provider_name}"
                    logger.warning(
                        "ModelRouter: provider unavailable request_id=%s session=%s hash=%s length=%s tier=%s provider=%s error_type=%s",
                        self.last_call_request_id,
                        session_id or "",
                        self.last_call_hash,
                        self.last_call_messages_len,
                        cur_tier,
                        provider_name,
                        last_error_type,
                    )
                    if cur_tier == tier:
                        last_error_type = f"provider_unavailable:{provider_name}"
                    continue

                resolved_timeout_bucket, timeout = self._resolve_timeout_seconds(cur_tier, timeout_bucket)
                self.last_call_timeout_bucket = resolved_timeout_bucket
                self.last_call_timeout_seconds = float(timeout)
                complete_kwargs = {
                    "tier": cur_tier,
                    "model": model,
                    "messages": active_messages,
                    "temperature": temperature,
                    "timeout": timeout,
                    "session_id": session_id,
                    "request_id": self.last_call_request_id,
                    "tools": provider_tools,
                    "tool_choice": provider_tool_choice,
                }
                try:
                    provider_params = inspect.signature(provider.complete).parameters
                    if "stream" in provider_params:
                        complete_kwargs["stream"] = self.last_call_streaming_enabled
                    if "stream_callback" in provider_params:
                        complete_kwargs["stream_callback"] = stream_callback if self.last_call_streaming_enabled else None
                except Exception:
                    pass
                response = await provider.complete(**complete_kwargs)
                self.last_call_tool_calls = self._normalize_tool_calls(getattr(response, "tool_calls", []))
                try:
                    append_token_usage_event(
                        self.runtime_cfg,
                        request_id=self.last_call_request_id,
                        session_id=session_id or "",
                        channel=channel or "",
                        tier=cur_tier,
                        model=model,
                        provider=provider_name,
                        token_usage=getattr(response, "token_usage", {}) or {},
                        tool_call_count=len(self.last_call_tool_calls),
                    )
                except Exception:
                    logger.exception("ModelRouter: failed to append token usage request_id=%s", self.last_call_request_id)
                if cur_tier != tier:
                    self._record_request_fallback(from_profile=tier, to_profile=cur_tier, reason=last_error_type or 'primary_failed')
                return str(response.content).strip(), cur_tier
            except asyncio.TimeoutError:
                last_error_type = "timeout"
                logger.warning(
                    "ModelRouter: model timeout request_id=%s session=%s hash=%s length=%s tier=%s error_type=%s",
                    self.last_call_request_id,
                    session_id or "",
                    self.last_call_hash,
                    self.last_call_messages_len,
                    cur_tier,
                    last_error_type,
                )
                self._mark_fail(model, self._tier_cooldown_on_fail(cur_tier))
            except Exception as exc:
                sensitive_type = self._detect_sensitive_error_type(exc)
                if sensitive_type:
                    self.last_call_sensitive_failure = True
                    self.last_call_error_type = sensitive_type
                    last_error_type = sensitive_type
                    if safe_messages is None:
                        safe_messages = self._build_safe_fallback_messages(messages, sensitive_type)
                    logger.warning(
                        "ModelRouter: sensitive failure request_id=%s session=%s hash=%s length=%s tier=%s error_type=%s",
                        self.last_call_request_id,
                        session_id or "",
                        self.last_call_hash,
                        self.last_call_messages_len,
                        cur_tier,
                        sensitive_type,
                    )
                    self._mark_fail(model, self._tier_cooldown_on_fail(cur_tier))
                    continue

                detected_error = self._detect_sensitive_error_type(exc)
                last_error_type = detected_error or str(exc.__class__.__name__)
                exc_text = str(exc or "").strip()
                if exc_text:
                    last_error_type = f"{last_error_type}:{exc_text}" if last_error_type else exc_text
                self.last_call_error_type = str(last_error_type or "")
                logger.warning(
                    "ModelRouter: model call failed request_id=%s session=%s hash=%s length=%s tier=%s error_type=%s",
                    self.last_call_request_id,
                    session_id or "",
                    self.last_call_hash,
                    self.last_call_messages_len,
                    cur_tier,
                    self.last_call_error_type,
                )
                self._mark_fail(model, self._tier_cooldown_on_fail(cur_tier) * 2)

        logger.warning(
            "ModelRouter: all tiers exhausted, returning local safe template request_id=%s session=%s hash=%s length=%s error_type=%s",
            self.last_call_request_id,
            session_id or "",
            self.last_call_hash,
            self.last_call_messages_len,
            self.last_call_error_type or last_error_type,
        )
        return self.LOCAL_SAFE_TEXT, "local_safe_template"


    async def refresh_model_profiles(
        self,
        *,
        provider_profile_id: str | None = None,
        enable_discovered: bool = False,
        timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        """Refresh runtime model profiles from OpenAI-compatible /models.

        The result is sanitized: model ids and profile ids only.  API key env
        names, base_url env names, actual keys, tokens, and endpoint values are
        never returned.
        """
        ids: list[str] = []
        if provider_profile_id:
            ids = [str(provider_profile_id).strip()]
        else:
            for pid in iter_profile_ids(self.runtime_cfg):
                descriptor = get_model_profile_descriptor(self.runtime_cfg, pid)
                if str(descriptor.get("provider") or "") == "openai_compat" and pid not in ids:
                    ids.append(pid)
        ids = [pid for pid in ids if pid]
        if not ids:
            return {"ok": False, "reason": "no_openai_compat_profiles", "refreshed": [], "failed": []}

        refreshed: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        timeout = max(1.0, min(300.0, float(timeout_seconds or 30)))
        seen_sources: set[tuple[str, str]] = set()
        for pid in ids:
            descriptor = get_model_profile_descriptor(self.runtime_cfg, pid)
            provider_name = str(descriptor.get("provider") or self._provider_name(pid) or "")
            if provider_name != "openai_compat":
                failed.append({"provider_profile_id": pid, "reason": "unsupported_provider", "provider": provider_name})
                continue
            # Avoid hitting the same provider endpoint repeatedly when multiple
            # placeholder profiles share one env pair.  The key contains only env
            # variable names, and it is not returned to the user.
            api_env = str(self._cfg_get(f"providers.{pid}.api_key_env", "") or "")
            base_env = str(self._cfg_get(f"providers.{pid}.base_url_env", "") or "")
            dedupe_key = (api_env, base_env)
            if dedupe_key != ("", "") and dedupe_key in seen_sources:
                continue
            if dedupe_key != ("", ""):
                seen_sources.add(dedupe_key)
            provider = self.providers.get(provider_name)
            if provider is None or not provider.is_available or not hasattr(provider, "list_models"):
                failed.append({"provider_profile_id": pid, "reason": f"provider_unavailable:{provider_name}"})
                continue
            try:
                model_ids = await provider.list_models(tier=pid, timeout=timeout)
                data = refresh_model_profiles_from_models(
                    self.runtime_cfg,
                    provider_profile_id=pid,
                    model_ids=model_ids,
                    enable_discovered=enable_discovered,
                    timeout=descriptor.get("timeout"),
                    cooldown_on_fail=descriptor.get("cooldown_on_fail"),
                )
                if data.get("ok"):
                    refreshed.append(data)
                else:
                    failed.append({"provider_profile_id": pid, "reason": data.get("reason") or "refresh_failed"})
            except asyncio.TimeoutError:
                failed.append({"provider_profile_id": pid, "reason": "timeout"})
            except Exception as exc:
                failed.append({"provider_profile_id": pid, "reason": self._detect_sensitive_error_type(exc) or exc.__class__.__name__})
        return {
            "ok": bool(refreshed) and not failed,
            "reason": "ok" if refreshed and not failed else ("partial" if refreshed else "failed"),
            "refreshed": refreshed,
            "failed": failed,
            "enable_discovered": bool(enable_discovered),
        }

    async def test_model_profile(
        self,
        profile_id: str,
        *,
        timeout_seconds: int | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        """Directly test one provider/model profile without ORDER fallback.

        This diagnostic path intentionally does not call ``self.call``. It sends
        one minimal ping to the target provider/model and reports only sanitized
        metadata; no secret/base_url/token/error text is returned.
        """
        pid = str(profile_id or "").strip()
        ok, reason, descriptor = validate_model_profile_enabled(self.runtime_cfg, pid)
        if not ok:
            return {
                "ok": False,
                "reason": reason,
                "profile_id": pid,
                "profile": descriptor,
                "fallback_used": False,
            }

        provider_name = str(descriptor.get("provider") or self._provider_name(pid) or "")
        provider = self.providers.get(provider_name)
        if provider is None or not provider.is_available:
            return {
                "ok": False,
                "reason": f"provider_unavailable:{provider_name}",
                "profile_id": pid,
                "profile": descriptor,
                "fallback_used": False,
            }

        timeout = float(timeout_seconds or descriptor.get("timeout") or self._tier_timeout(pid))
        timeout = max(1.0, min(300.0, timeout))
        request_id = uuid.uuid4().hex[:12]
        messages = [
            {"role": "system", "content": "You are a diagnostic ping endpoint. Reply with a short OK."},
            {"role": "user", "content": "ping"},
        ]
        started = time.perf_counter()
        try:
            response = await provider.complete(
                tier=pid,
                model=str(descriptor.get("model") or self._model_name(pid)),
                messages=messages,
                temperature=0.0,
                timeout=timeout,
                session_id=session_id,
                request_id=request_id,
            )
            latency_ms = int(getattr(response, "latency_ms", 0) or ((time.perf_counter() - started) * 1000))
            preview = str(getattr(response, "content", "") or "").strip()[:120]
            return {
                "ok": True,
                "reason": "ok",
                "profile_id": pid,
                "profile": get_model_profile_descriptor(self.runtime_cfg, pid),
                "latency_ms": latency_ms,
                "content_preview": preview,
                "request_id": request_id,
                "fallback_used": False,
            }
        except asyncio.TimeoutError:
            return {
                "ok": False,
                "reason": "timeout",
                "profile_id": pid,
                "profile": descriptor,
                "request_id": request_id,
                "fallback_used": False,
            }
        except Exception as exc:
            sensitive_type = self._detect_sensitive_error_type(exc)
            return {
                "ok": False,
                "reason": sensitive_type or exc.__class__.__name__,
                "profile_id": pid,
                "profile": descriptor,
                "request_id": request_id,
                "fallback_used": False,
            }
    def call_via_tier(
        self,
        tier: str,
        messages: list[dict[str, Any]],
        target_agent: str = "",
    ) -> dict[str, Any]:
        """同步壳：把 async call() 包成 {content, tier} 同步 dict，给 I叔/Agent Bus 等
        想直接调、又不跑 asyncio 的代码用。不动私聊/群聊 active，只走指定 tier。

        call() 返回 (text, tier) 二元组；call_with_tool_loop 才返回三元。
        兼容两者：优先按二元解包，拿到 trace 时并入返回。
        """
        import asyncio as _aio
        import concurrent.futures as _cf
        coro = self.call(
            tier=tier,
            messages=messages,
            session_id=f"{target_agent or 'call_via_tier'}",
        )
        with _cf.ThreadPoolExecutor(max_workers=1) as _pool:
            future = _pool.submit(_aio.run, coro)
            raw = future.result(timeout=120)
        if isinstance(raw, tuple) and len(raw) == 3:
            text, used_tier, _trace = raw
        elif isinstance(raw, tuple) and len(raw) == 2:
            text, used_tier = raw
        else:
            text, used_tier = (raw if isinstance(raw, str) else ""), "unknown"
        return {"content": text or "", "tier": used_tier, "target_agent": target_agent}


