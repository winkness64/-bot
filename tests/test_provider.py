from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
import re

import pytest

from mock_pipeline_runtime import prepare_modules  # type: ignore

mods = prepare_modules()
RuntimeConfig = mods['RuntimeConfig']
DEFAULTS = mods['DEFAULTS']
ModelRouter = mods['ModelRouter']

from plugins.yangyang.core.model.provider_base import ProviderResponse
from plugins.yangyang.core.model.provider_deepseek import DeepSeekV4Provider
from plugins.yangyang.core.model.provider_mock import MockProvider
from plugins.yangyang.core.model.provider_openai_compat import OpenAICompatibleProvider


class DictConfig:
    def __init__(self, data: dict):
        self.data = data

    def get(self, path: str, default=None):
        cur = self.data
        for part in path.split('.'):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def get_bool(self, path: str, default: bool = False, env_key: str | None = None) -> bool:
        value = self.get(path, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {'1', 'true', 'yes', 'on'}


@pytest.mark.asyncio
async def test_mock_provider_complete() -> None:
    provider = MockProvider(response_text='ok', model_used='mock-x', token_usage={'total_tokens': 7}, latency_ms=9)
    result = await provider.complete(
        tier='v4_flash',
        model='deepseek-v4-flash',
        messages=[{'role': 'user', 'content': 'hi'}],
        request_id='r1',
    )
    assert isinstance(result, ProviderResponse)
    assert result.content == 'ok'
    assert result.model_used == 'mock-x'
    assert result.token_usage['total_tokens'] == 7
    assert result.latency_ms == 9
    assert provider.calls[0]['request_id'] == 'r1'


@pytest.mark.asyncio
async def test_router_with_mock_provider_injection() -> None:
    cfg = DictConfig(
        {
            'dry_run': False,
            'models': {'v4_flash': {'model': 'deepseek-v4-flash', 'enabled': True}},
            'providers': {'v4_flash': {'provider': 'mock', 'model': 'deepseek-v4-flash', 'timeout': 30, 'cooldown_on_fail': 60, 'enabled': True}},
        }
    )
    router = ModelRouter(cfg)
    mock = MockProvider(response_text='injected response')
    router.register_provider(mock)
    response, actual_tier = await router.call('v4_flash', [{'role': 'user', 'content': 'hello'}], session_id='s1')
    assert response == 'injected response'
    assert actual_tier == 'v4_flash'
    assert len(mock.calls) == 1


def test_runtime_config_loads_providers(tmp_path: Path) -> None:
    cfg_path = tmp_path / 'runtime_config.json'
    cfg_path.write_text(json.dumps(DEFAULTS, ensure_ascii=False, indent=2), encoding='utf-8')
    cfg = RuntimeConfig(DEFAULTS, path=cfg_path)
    assert cfg.get('providers.v4_flash.provider') == 'deepseek'
    assert cfg.get('providers.v4_pro.enabled') is True
    assert cfg.get('models.v4_pro.enabled') is True
    assert cfg.get('models.gpt_5_5.enabled') is False
    assert cfg.get('providers.m2_7.enabled') is False


@pytest.mark.asyncio
async def test_router_fallback_when_provider_unavailable() -> None:
    cfg = DictConfig(
        {
            'dry_run': False,
            'models': {
                'v4_flash': {'model': 'deepseek-v4-flash', 'enabled': True},
                'v4_pro': {'model': 'deepseek-v4-pro', 'enabled': True},
            },
            'providers': {
                'v4_flash': {'provider': 'mock_unavailable', 'model': 'deepseek-v4-flash', 'timeout': 30, 'cooldown_on_fail': 60, 'enabled': True},
                'v4_pro': {'provider': 'mock_ok', 'model': 'deepseek-v4-pro', 'timeout': 60, 'cooldown_on_fail': 120, 'enabled': True},
            },
            'model_profile_switcher': {'fallback_profiles_private': ['v4_pro']},
        }
    )
    router = ModelRouter(cfg)

    class UnavailableProvider(MockProvider):
        @property
        def provider_name(self) -> str:
            return 'mock_unavailable'

    class OkProvider(MockProvider):
        @property
        def provider_name(self) -> str:
            return 'mock_ok'

    router.register_provider(UnavailableProvider(available=False))
    router.register_provider(OkProvider(response_text='fallback ok'))
    response, actual_tier = await router.call('v4_flash', [{'role': 'user', 'content': 'hello'}], channel='private')
    assert response == 'fallback ok'
    assert actual_tier == 'v4_pro'


@pytest.mark.asyncio
async def test_router_fallback_when_first_provider_raises() -> None:
    cfg = DictConfig(
        {
            'dry_run': False,
            'models': {
                'v4_flash': {'model': 'deepseek-v4-flash', 'enabled': True},
                'v4_pro': {'model': 'deepseek-v4-pro', 'enabled': True},
            },
            'providers': {
                'v4_flash': {'provider': 'mock_bad', 'model': 'deepseek-v4-flash', 'timeout': 30, 'cooldown_on_fail': 60, 'enabled': True},
                'v4_pro': {'provider': 'mock_ok', 'model': 'deepseek-v4-pro', 'timeout': 60, 'cooldown_on_fail': 120, 'enabled': True},
            },
            'model_profile_switcher': {'fallback_profiles_private': ['v4_pro']},
        }
    )
    router = ModelRouter(cfg)

    class BadProvider(MockProvider):
        @property
        def provider_name(self) -> str:
            return 'mock_bad'

    class OkProvider(MockProvider):
        @property
        def provider_name(self) -> str:
            return 'mock_ok'

    router.register_provider(BadProvider(error=TimeoutError('boom timeout')))
    ok = OkProvider(response_text='second tier answer')
    router.register_provider(ok)
    response, actual_tier = await router.call('v4_flash', [{'role': 'user', 'content': 'hello'}], channel='private')
    assert response == 'second tier answer'
    assert actual_tier == 'v4_pro'
    assert len(ok.calls) == 1


@pytest.mark.asyncio
async def test_router_timeout_bucket_overrides_provider_timeout_when_enabled() -> None:
    cfg = DictConfig(
        {
            'dry_run': False,
            'llm_timeout_bucket_enabled': True,
            'llm_timeout_bucket_override_provider_timeout': True,
            'llm_timeout_buckets': {'tool_followup': 91},
            'models': {'v4_flash': {'model': 'deepseek-v4-flash', 'enabled': True}},
            'providers': {'v4_flash': {'provider': 'mock', 'model': 'deepseek-v4-flash', 'timeout': 30, 'cooldown_on_fail': 60, 'enabled': True}},
        }
    )
    router = ModelRouter(cfg)
    mock = MockProvider(response_text='bucket ok')
    router.register_provider(mock)

    response, actual_tier = await router.call(
        'v4_flash',
        [{'role': 'user', 'content': 'hello'}],
        timeout_bucket='tool_followup',
    )

    assert response == 'bucket ok'
    assert actual_tier == 'v4_flash'
    assert router.last_call_timeout_bucket == 'tool_followup'
    assert router.last_call_timeout_seconds == 91.0
    assert mock.calls[0]['timeout'] == 91.0


@pytest.mark.asyncio
async def test_router_stream_flag_passthrough_respects_global_switch() -> None:
    cfg = DictConfig(
        {
            'dry_run': False,
            'llm_streaming_enabled': True,
            'models': {'v4_flash': {'model': 'deepseek-v4-flash', 'enabled': True}},
            'providers': {'v4_flash': {'provider': 'mock', 'model': 'deepseek-v4-flash', 'timeout': 30, 'cooldown_on_fail': 60, 'enabled': True}},
        }
    )
    router = ModelRouter(cfg)
    mock = MockProvider(response_text='stream ok')
    router.register_provider(mock)

    response, actual_tier = await router.call(
        'v4_flash',
        [{'role': 'user', 'content': 'hello'}],
        allow_streaming=True,
    )

    assert response == 'stream ok'
    assert actual_tier == 'v4_flash'
    assert router.last_call_streaming_enabled is True
    assert mock.calls[0]['stream'] is True


@pytest.mark.asyncio
async def test_router_stream_flag_stays_off_when_global_switch_disabled() -> None:
    cfg = DictConfig(
        {
            'dry_run': False,
            'llm_streaming_enabled': False,
            'models': {'v4_flash': {'model': 'deepseek-v4-flash', 'enabled': True}},
            'providers': {'v4_flash': {'provider': 'mock', 'model': 'deepseek-v4-flash', 'timeout': 30, 'cooldown_on_fail': 60, 'enabled': True}},
        }
    )
    router = ModelRouter(cfg)
    mock = MockProvider(response_text='stream off')
    router.register_provider(mock)

    response, actual_tier = await router.call(
        'v4_flash',
        [{'role': 'user', 'content': 'hello'}],
        allow_streaming=True,
    )

    assert response == 'stream off'
    assert actual_tier == 'v4_flash'
    assert router.last_call_streaming_enabled is False
    assert mock.calls[0]['stream'] is False


class _FakeStream:
    def __init__(self, chunks, delays=None):
        self._chunks = list(chunks)
        self._delays = list(delays or [0.0] * len(self._chunks))

    def __aiter__(self):
        self._idx = 0
        return self

    async def __anext__(self):
        if self._idx >= len(self._chunks):
            raise StopAsyncIteration
        delay = self._delays[self._idx] if self._idx < len(self._delays) else 0.0
        if delay:
            await asyncio.sleep(delay)
        item = self._chunks[self._idx]
        self._idx += 1
        return item


def _stream_chunk(*, content=None, tool_calls=None, usage=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)], usage=usage)




def test_private_streaming_buffer_flush_policy_is_more_eager() -> None:
    src = Path('src/plugins/yangyang/__init__.py').read_text(encoding='utf-8')
    assert 'min_stream_chars = 16' in src
    assert 'eager_stream_chars = 32' in src
    assert 'max_stream_idle_seconds = 0.45' in src
    assert 'len(pending) < min_stream_chars' in src
    assert 'len(stream_state["buffer"]) >= eager_stream_chars' in src
    assert 'now - float(stream_state["last_flush_ts"])' in src

@pytest.mark.asyncio
async def test_openai_compat_provider_stream_consumes_async_chunks() -> None:
    provider = OpenAICompatibleProvider(runtime_cfg=None)
    stream = _FakeStream(
        [
            _stream_chunk(content='hello '),
            _stream_chunk(content='world', usage=SimpleNamespace(prompt_tokens=3, completion_tokens=2, total_tokens=5)),
        ]
    )

    class _FakeCompletions:
        async def create(self, **kwargs):
            assert kwargs['stream'] is True
            return stream

    class _FakeClient:
        chat = SimpleNamespace(completions=_FakeCompletions())

    provider._get_client = lambda tier: _FakeClient()
    result = await provider.complete(
        tier='gpt_5_4',
        model='gpt-5.4',
        messages=[{'role': 'user', 'content': 'hi'}],
        timeout=1,
        stream=True,
    )

    assert result.content == 'hello world'
    assert result.model_used == 'gpt-5.4'
    assert result.token_usage['total_tokens'] == 5


@pytest.mark.asyncio
async def test_deepseek_provider_stream_consumes_async_chunks() -> None:
    provider = DeepSeekV4Provider(runtime_cfg=None)
    stream = _FakeStream(
        [
            _stream_chunk(content='deep'),
            _stream_chunk(content='seek', usage=SimpleNamespace(prompt_tokens=4, completion_tokens=2, total_tokens=6)),
        ]
    )

    class _FakeCompletions:
        async def create(self, **kwargs):
            assert kwargs['stream'] is True
            return stream

    class _FakeClient:
        chat = SimpleNamespace(completions=_FakeCompletions())

    provider._get_client = lambda tier: _FakeClient()
    result = await provider.complete(
        tier='v4_flash',
        model='deepseek-v4-flash',
        messages=[{'role': 'user', 'content': 'hi'}],
        timeout=1,
        stream=True,
    )

    assert result.content == 'deepseek'
    assert result.model_used == 'deepseek-v4-flash'
    assert result.token_usage['total_tokens'] == 6


@pytest.mark.asyncio
async def test_openai_compat_provider_stream_timeout_raises() -> None:
    provider = OpenAICompatibleProvider(runtime_cfg=None)
    stream = _FakeStream([_stream_chunk(content='late')], delays=[0.05])

    class _FakeCompletions:
        async def create(self, **kwargs):
            return stream

    class _FakeClient:
        chat = SimpleNamespace(completions=_FakeCompletions())

    provider._get_client = lambda tier: _FakeClient()
    with pytest.raises(TimeoutError):
        await provider.complete(
            tier='gpt_5_4',
            model='gpt-5.4',
            messages=[{'role': 'user', 'content': 'hi'}],
            timeout=0.01,
            stream=True,
        )
