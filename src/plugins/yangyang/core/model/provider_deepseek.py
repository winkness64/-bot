from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from .provider_base import ModelProvider, ProviderResponse


class DeepSeekV4Provider(ModelProvider):
    def __init__(self, runtime_cfg: Any):
        self.runtime_cfg = runtime_cfg
        self._clients: dict[tuple[str, str], Any] = {}

    @staticmethod
    def _message_content_to_text(content: Any) -> str:
        if content is None:
            return ""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, dict):
                    if item.get("type") == "text" and item.get("text") is not None:
                        parts.append(str(item.get("text") or ""))
                    elif item.get("text") is not None:
                        parts.append(str(item.get("text") or ""))
                else:
                    text = getattr(item, "text", None)
                    if text is not None:
                        parts.append(str(text or ""))
            return "".join(parts)
        return str(content)

    async def _consume_stream_response(self, response: Any, *, tier: str, model: str, timeout: float, start: float, stream_callback: Any = None) -> ProviderResponse:
        deadline = asyncio.get_running_loop().time() + max(float(timeout), 0.001)
        chunks: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        usage_obj: Any = None
        async with asyncio.timeout_at(deadline):
            async for chunk in response:
                choices = getattr(chunk, "choices", None) or []
                if choices:
                    delta = getattr(choices[0], "delta", None) or {}
                    content = getattr(delta, "content", None)
                    if content is None and isinstance(delta, dict):
                        content = delta.get("content")
                    text = self._message_content_to_text(content)
                    if text:
                        chunks.append(text)
                        if stream_callback is not None:
                            emitted = stream_callback(text, {"tier": tier, "model": str(model), "delta": text})
                            if asyncio.iscoroutine(emitted):
                                await emitted
                    raw_tool_calls = getattr(delta, "tool_calls", None)
                    if raw_tool_calls is None and isinstance(delta, dict):
                        raw_tool_calls = delta.get("tool_calls")
                    if raw_tool_calls:
                        tool_calls.extend(_normalize_tool_calls(raw_tool_calls))
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    usage_obj = usage
        latency_ms = int((time.perf_counter() - start) * 1000)
        token_usage = {
            "prompt_tokens": getattr(usage_obj, "prompt_tokens", None),
            "completion_tokens": getattr(usage_obj, "completion_tokens", None),
            "total_tokens": getattr(usage_obj, "total_tokens", None),
        }
        return ProviderResponse(
            content="".join(chunks).strip(),
            model_used=str(model),
            token_usage=token_usage,
            latency_ms=latency_ms,
            tier=tier,
            tool_calls=tool_calls,
        )

    @property
    def provider_name(self) -> str:
        return "deepseek"

    @property
    def is_available(self) -> bool:
        return True

    def _cfg_get(self, path: str, default: Any = None) -> Any:
        try:
            if self.runtime_cfg is not None and hasattr(self.runtime_cfg, "get"):
                value = self.runtime_cfg.get(path, default)
                return default if value is None else value
        except Exception:
            return default
        return default


    def _profile_env(self, tier: str, key: str, default: str = "") -> str:
        return str(self._cfg_get(f"providers.{tier}.{key}", default) or "").strip()

    def _resolve_credentials(self, tier: str) -> tuple[str, str | None]:
        api_ref = str(self._cfg_get(f"providers.{tier}.api_registry_id", "") or "").strip()
        api_key = ""
        base_url: str | None = None
        if api_ref:
            api_key_env_ref = str(self._cfg_get(f"api_registry.{api_ref}.api_key_env", "") or "").strip()
            api_key = os.getenv(api_key_env_ref) if api_key_env_ref else ""
            if not api_key:
                api_key = str(self._cfg_get(f"api_registry.{api_ref}.api_key", "") or "").strip()
            base_url_env_ref = str(self._cfg_get(f"api_registry.{api_ref}.base_url_env", "") or "").strip()
            base_url = os.getenv(base_url_env_ref) if base_url_env_ref else ""
            if not base_url:
                base_url = str(self._cfg_get(f"api_registry.{api_ref}.base_url", "") or "").strip() or None
        api_key_env = self._profile_env(tier, "api_key_env")
        base_url_env = self._profile_env(tier, "base_url_env")
        if not api_key:
            api_key = os.getenv(api_key_env) if api_key_env else ""
        if not base_url:
            base_url = os.getenv(base_url_env) if base_url_env else None
        if not api_key:
            api_key = os.getenv("OPENAI_API_KEY") or os.getenv("DEEPSEEK_API_KEY") or str(self._cfg_get("api.api_key", ""))
        if not base_url:
            base_url = os.getenv("OPENAI_BASE_URL") or os.getenv("DEEPSEEK_BASE_URL") or self._cfg_get("api.base_url", None)
        if not api_key:
            raise RuntimeError(f"missing_api_key:{api_ref or api_key_env or 'unset'}")
        return str(api_key), (str(base_url).strip() if base_url else None)

    def _get_client(self, tier: str) -> Any:
        api_key, base_url = self._resolve_credentials(tier)
        cache_key = (tier, str(base_url or ''))
        if cache_key in self._clients:
            return self._clients[cache_key]

        try:
            from openai import AsyncOpenAI  # type: ignore
        except Exception as exc:
            raise RuntimeError("openai package is required for DeepSeekV4Provider") from exc

        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._clients[cache_key] = client
        return client

    async def complete(
        self,
        *,
        tier: str,
        model: str,
        messages: list[dict[str, Any]],
        temperature: float = 0.72,
        timeout: float = 30,
        session_id: str | None = None,
        request_id: str | None = None,
        tools: list[dict[str, Any]] | None = None,
        tool_choice: Any = None,
        stream: bool = False,
        stream_callback: Any = None,
    ) -> ProviderResponse:
        start = time.perf_counter()
        client = self._get_client(tier)
        request_kwargs: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools is not None:
            request_kwargs["tools"] = tools
        if tool_choice is not None:
            request_kwargs["tool_choice"] = tool_choice
        request_kwargs["stream"] = bool(stream)
        response = await asyncio.wait_for(
            client.chat.completions.create(**request_kwargs),
            timeout=float(timeout),
        )
        if stream:
            return await self._consume_stream_response(response, tier=tier, model=model, timeout=timeout, start=start, stream_callback=stream_callback)
        latency_ms = int((time.perf_counter() - start) * 1000)
        message = response.choices[0].message
        usage = getattr(response, "usage", None)
        token_usage = {
            "prompt_tokens": getattr(usage, "prompt_tokens", None),
            "completion_tokens": getattr(usage, "completion_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
        return ProviderResponse(
            content=self._message_content_to_text(getattr(message, "content", "")).strip(),
            model_used=str(model),
            token_usage=token_usage,
            latency_ms=latency_ms,
            tier=tier,
            tool_calls=_normalize_tool_calls(getattr(message, "tool_calls", None)),
        )


def _normalize_tool_calls(raw_tool_calls: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for idx, call in enumerate(raw_tool_calls or []):
        function = getattr(call, "function", None)
        name = getattr(function, "name", None)
        arguments = getattr(function, "arguments", None)
        if name is None and isinstance(call, dict):
            function = call.get("function") or {}
            if isinstance(function, dict):
                name = function.get("name")
                arguments = function.get("arguments")
            else:
                name = call.get("name")
                arguments = call.get("arguments")
        if not name:
            continue
        result.append(
            {
                "id": str(getattr(call, "id", "") or (call.get("id") if isinstance(call, dict) else "") or f"tool_call_{idx}"),
                "type": str(getattr(call, "type", "") or (call.get("type") if isinstance(call, dict) else "") or "function"),
                "name": str(name),
                "arguments": arguments if arguments is not None else {},
            }
        )
    return result
