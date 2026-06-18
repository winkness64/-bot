from __future__ import annotations

import json
import os
import time
from typing import Any

from .provider_base import ModelProvider, ProviderResponse


class AnthropicCompatProvider(ModelProvider):
    """Minimal Anthropic Messages-compatible chat provider.

    Intentionally does NOT depend on the upstream ``anthropic`` SDK so we
    avoid pulling another large package into the production venv.  We use
    the already-pinned ``httpx`` to POST JSON to the provider's
    ``/v1/messages`` endpoint.

    Each profile may define:
      - api_key_env: env var name for the API key
      - base_url_env: env var name for the base URL (Anthropic compatible)
      - base_url: optional non-secret base URL fallback from runtime config

    The provider never logs or returns secret values.  Output is sanitized
    and only safe text/tool calls are returned.  Failures are translated
    into a stable reason so the router can apply the C1 fuse without
    leaking the original error text.
    """

    _SENSITIVE_FALLBACK = "upstream_error"

    def __init__(self, runtime_cfg: Any, provider_name: str = "anthropic_compat"):
        self.runtime_cfg = runtime_cfg
        self._provider_name = str(provider_name or "anthropic_compat")
        self._clients: dict[tuple[str, str], Any] = {}

    @property
    def provider_name(self) -> str:
        return self._provider_name

    @property
    def is_available(self) -> bool:
        # Per-tier credentials are checked in complete().  Returning True
        # keeps disabled profiles fail-soft instead of vanishing.
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
        return str(api_key), str(base_url).rstrip("/")

    def _endpoint(self, base_url: str) -> str:
        # Anthropic Messages endpoint.  If the env base_url already ends in
        # ``/v1`` we just append ``/messages``; otherwise we insert ``/v1``.
        clean = str(base_url or "").rstrip("/")
        if clean.endswith("/v1"):
            return f"{clean}/messages"
        return f"{clean}/v1/messages"

    def _get_client(self, tier: str) -> Any:
        api_key, base_url = self._resolve_credentials(tier)
        cache_key = (tier, base_url)
        if cache_key in self._clients:
            return self._clients[cache_key]
        try:
            import httpx  # type: ignore
        except Exception as exc:  # pragma: no cover - exercised by tests
            raise RuntimeError("httpx is required for AnthropicCompatProvider") from exc
        client = httpx.AsyncClient(timeout=httpx.Timeout(connect=10.0, read=30.0, write=10.0, pool=10.0))
        self._clients[cache_key] = (client, api_key, base_url)
        return self._clients[cache_key]

    async def list_models(self, *, tier: str, timeout: float = 30) -> list[str]:
        """Anthropic-compatible providers do not expose /models.

        We deliberately return an empty list so the profile switcher
        refresh path skips this tier without raising.  Callers must seed
        profile catalogs manually.
        """
        del tier, timeout
        return []

    def _translate_messages(self, messages: list[dict[str, Any]]) -> tuple[str | None, list[dict[str, Any]]]:
        """Convert OpenAI-style messages to Anthropic system+messages."""
        system_text: str | None = None
        converted: list[dict[str, Any]] = []
        for item in messages or []:
            role = str(item.get("role") or "").strip()
            content = item.get("content")
            if role == "system":
                if isinstance(content, str) and content:
                    system_text = (system_text + "\n\n" + content) if system_text else content
                continue
            if role not in {"user", "assistant"}:
                continue
            converted.append({"role": role, "content": str(content or "")})
        return (system_text or None), converted

    def _translate_tools(self, tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
        if not tools:
            return None
        translated: list[dict[str, Any]] = []
        for item in tools:
            if not isinstance(item, dict):
                continue
            function = item.get("function") if isinstance(item.get("function"), dict) else None
            name = ""
            description = ""
            parameters: dict[str, Any] = {"type": "object", "properties": {}}
            if function is not None:
                name = str(function.get("name") or "").strip()
                description = str(function.get("description") or "")
                params = function.get("parameters")
                if isinstance(params, dict):
                    parameters = dict(params)
            else:
                name = str(item.get("name") or "").strip()
                description = str(item.get("description") or "")
                params = item.get("parameters")
                if isinstance(params, dict):
                    parameters = dict(params)
            if not name:
                continue
            translated.append(
                {
                    "name": name,
                    "description": description,
                    "input_schema": parameters,
                }
            )
        return translated or None

    def _normalize_tool_calls(self, content_blocks: Any) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for idx, block in enumerate(content_blocks or []):
            if not isinstance(block, dict):
                continue
            if str(block.get("type") or "") != "tool_use":
                continue
            name = str(block.get("name") or "").strip()
            if not name:
                continue
            arguments = block.get("input", {})
            if not isinstance(arguments, dict):
                arguments = {"value": arguments}
            normalized.append(
                {
                    "id": str(block.get("id") or f"tool_call_{idx}"),
                    "type": "function",
                    "name": name,
                    "arguments": arguments,
                }
            )
        return normalized

    def _extract_text(self, content_blocks: Any) -> str:
        parts: list[str] = []
        for block in content_blocks or []:
            if not isinstance(block, dict):
                continue
            if str(block.get("type") or "") == "text":
                text = str(block.get("text") or "")
                if text:
                    parts.append(text)
        return "".join(parts).strip()

    def _normalize_error_type(self, status_code: int, body_text: str) -> str:
        blob = (str(status_code) + " " + str(body_text or "")).lower()
        if "sensitive" in blob or "content_filter" in blob or "filtered" in blob:
            return "sensitive_words_detected"
        if status_code in (401, 403):
            return "auth_failed"
        if status_code == 404:
            return "model_not_found"
        if status_code == 429:
            return "rate_limited"
        if status_code in (408, 504, 524):
            return "upstream_timeout"
        if status_code in (500, 502, 503):
            return "upstream_error"
        return self._SENSITIVE_FALLBACK

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
    ) -> ProviderResponse:
        del session_id, request_id
        start = time.perf_counter()
        try:
            client, api_key, base_url = self._get_client(tier)
        except RuntimeError:
            raise
        endpoint = self._endpoint(base_url)
        system_text, converted_messages = self._translate_messages(messages)
        payload: dict[str, Any] = {
            "model": str(model),
            "messages": converted_messages,
            "max_tokens": 1024,
            "temperature": float(temperature),
        }
        if system_text:
            payload["system"] = system_text
        translated_tools = self._translate_tools(tools)
        if translated_tools is not None:
            payload["tools"] = translated_tools
            if tool_choice is not None:
                # OpenAI tool_choice values: "auto" / "none" / {"type":"function","function":{"name":...}}
                if isinstance(tool_choice, str):
                    choice_map = {"auto": "auto", "none": "none", "any": "any"}
                    payload["tool_choice"] = {"type": choice_map.get(tool_choice.lower(), "auto")}
                elif isinstance(tool_choice, dict):
                    fn = tool_choice.get("function") if isinstance(tool_choice.get("function"), dict) else None
                    name = str((fn or {}).get("name") or "").strip()
                    if name:
                        payload["tool_choice"] = {"type": "tool", "name": name}

        try:
            import httpx  # type: ignore
        except Exception as exc:  # pragma: no cover
            raise RuntimeError("httpx is required for AnthropicCompatProvider") from exc

        try:
            response = await client.post(
                endpoint,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json=payload,
                timeout=float(timeout),
            )
        except httpx.TimeoutException as exc:
            raise TimeoutError(f"anthropic_compat_timeout:{tier}") from exc
        except Exception as exc:
            raise RuntimeError(f"anthropic_compat_request_failed:{exc.__class__.__name__}") from exc

        latency_ms = int((time.perf_counter() - start) * 1000)
        if response.status_code >= 400:
            body_text = ""
            try:
                body_text = response.text
            except Exception:
                body_text = ""
            error_type = self._normalize_error_type(response.status_code, body_text)
            if error_type == "sensitive_words_detected":
                # Match the OpenAI provider's fuse marker so the router
                # can apply the C1 sanitized fallback uniformly.
                class _SensitiveError(Exception):
                    pass

                raise _SensitiveError(f"sensitive_words_detected:{tier}")
            raise RuntimeError(f"anthropic_compat_http_{response.status_code}:{error_type}")

        try:
            data = response.json()
        except Exception as exc:
            raise RuntimeError(f"anthropic_compat_bad_json:{exc.__class__.__name__}") from exc

        content_blocks = data.get("content") or []
        text = self._extract_text(content_blocks)
        tool_calls = self._normalize_tool_calls(content_blocks)
        usage = data.get("usage") or {}
        token_usage = {
            "prompt_tokens": usage.get("input_tokens"),
            "completion_tokens": usage.get("output_tokens"),
            "total_tokens": (usage.get("input_tokens") or 0) + (usage.get("output_tokens") or 0) or None,
        }
        return ProviderResponse(
            content=text,
            model_used=str(model),
            token_usage=token_usage,
            latency_ms=latency_ms,
            tier=tier,
            tool_calls=tool_calls,
        )

    async def aclose(self) -> None:
        for entry in self._clients.values():
            client = entry[0]
            try:
                await client.aclose()
            except Exception:
                pass
        self._clients.clear()
