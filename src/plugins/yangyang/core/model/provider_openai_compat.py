from __future__ import annotations

import asyncio
import os
import time
from typing import Any


from .provider_base import ModelProvider, ProviderResponse
from .provider_deepseek import _normalize_tool_calls


class OpenAICompatibleProvider(ModelProvider):
    """Generic OpenAI-compatible chat provider driven by runtime profile env names.

    Each profile may define:
      - api_key_env: env var name for the API key
      - base_url_env: env var name for the base URL
      - base_url: optional non-secret base URL fallback from runtime config

    The provider never logs or returns secret values.
    """

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
                        for tc_delta in raw_tool_calls:
                            tc_idx = getattr(tc_delta, "index", None)
                            if tc_idx is None and isinstance(tc_delta, dict):
                                tc_idx = tc_delta.get("index")
                            if tc_idx is None:
                                tc_idx = 0
                            while len(tool_calls) <= tc_idx:
                                tool_calls.append({"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
                            entry = tool_calls[tc_idx]
                            tid = getattr(tc_delta, "id", None) or (tc_delta.get("id") if isinstance(tc_delta, dict) else "")
                            if tid:
                                entry["id"] = str(tid)
                            ttype = getattr(tc_delta, "type", None) or (tc_delta.get("type") if isinstance(tc_delta, dict) else "")
                            if ttype:
                                entry["type"] = str(ttype)
                            tfunc = getattr(tc_delta, "function", None) or (tc_delta.get("function") if isinstance(tc_delta, dict) else None)
                            if tfunc is not None:
                                fname = getattr(tfunc, "name", None) or (tfunc.get("name") if isinstance(tfunc, dict) else "")
                                if fname:
                                    entry.setdefault("function", {})["name"] = str(fname)
                                fargs = getattr(tfunc, "arguments", None) or (tfunc.get("arguments") if isinstance(tfunc, dict) else "")
                                if fargs:
                                    current_args = entry.get("function", {}).get("arguments", "")
                                    entry.setdefault("function", {})["arguments"] = str(current_args) + str(fargs)
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

    def __init__(self, runtime_cfg: Any, provider_name: str = "openai_compat"):
        self.runtime_cfg = runtime_cfg
        self._provider_name = str(provider_name or "openai_compat")
        self._clients: dict[tuple[str, str], Any] = {}

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def is_available(self) -> bool:
        # Availability is tier-specific, so the router still performs the real
        # check in complete().  Returning True lets disabled/missing-key profiles
        # fail with a sanitized reason instead of hiding the provider object.
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

    def _resolve_credentials(self, tier: str) -> tuple[str, str]:
        api_ref = str(self._cfg_get(f"providers.{tier}.api_registry_id", "") or "").strip()
        api_key = ""
        base_url = ""
        if api_ref:
            api_key_env_ref = str(self._cfg_get(f"api_registry.{api_ref}.api_key_env", "") or "").strip()
            api_key = os.getenv(api_key_env_ref) if api_key_env_ref else ""
            if not api_key:
                api_key = str(self._cfg_get(f"api_registry.{api_ref}.api_key", "") or "").strip()
            base_url_env_ref = str(self._cfg_get(f"api_registry.{api_ref}.base_url_env", "") or "").strip()
            base_url = os.getenv(base_url_env_ref) if base_url_env_ref else ""
            if not base_url:
                base_url = str(self._cfg_get(f"api_registry.{api_ref}.base_url", "") or "").strip()
        api_key_env = self._profile_env(tier, "api_key_env")
        base_url_env = self._profile_env(tier, "base_url_env")
        if not api_key:
            api_key = os.getenv(api_key_env) if api_key_env else ""
        if not base_url:
            base_url = os.getenv(base_url_env) if base_url_env else ""
        if not base_url:
            base_url = str(self._cfg_get(f"providers.{tier}.base_url", "") or "").strip()
        if not api_key:
            raise RuntimeError(f"missing_api_key:{api_ref or api_key_env or 'unset'}")
        if not base_url:
            raise RuntimeError(f"missing_base_url:{api_ref or base_url_env or 'unset'}")
        return str(api_key), str(base_url)

    def _get_client(self, tier: str) -> Any:
        api_key, base_url = self._resolve_credentials(tier)
        cache_key = (tier, base_url)
        if cache_key in self._clients:
            return self._clients[cache_key]
        try:
            from openai import AsyncOpenAI  # type: ignore
        except Exception as exc:
            raise RuntimeError("openai package is required for OpenAICompatibleProvider") from exc
        client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._clients[cache_key] = client
        return client

    async def list_models(self, *, tier: str, timeout: float = 30) -> list[str]:
        """List model ids from the provider's OpenAI-compatible /models endpoint.

        Only sanitized model identifiers are returned.  Credentials and base_url
        are resolved internally from env/runtime config and are never returned.
        """
        client = self._get_client(tier)
        response = await asyncio.wait_for(client.models.list(), timeout=float(timeout))
        data = getattr(response, "data", None) or []
        model_ids: list[str] = []
        for item in data:
            mid = str(getattr(item, "id", "") or (item.get("id") if isinstance(item, dict) else "") or "").strip()
            if mid and mid not in model_ids:
                model_ids.append(mid)
        return model_ids

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
        del session_id, request_id
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
        response = await asyncio.wait_for(client.chat.completions.create(**request_kwargs), timeout=float(timeout))
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
