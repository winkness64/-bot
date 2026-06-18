from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse
from nonebot import get_driver, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, PrivateMessageEvent
from nonebot.log import logger
from nonebot.rule import Rule

from .admin.runtime_config import DEFAULTS, RuntimeConfig
from .core.cooldown_manager import CooldownManager
from .core.decision_engine import DecisionEngine
from .core.event_adapter import EventAdapter
from .core.owner_action_delivery import (
    format_owner_action_delivery_summary,
)
from .core.owner_action_delivery_safety import (
    format_owner_action_delivery_safety_summary,
)
from .output.current_session_smoke_trigger import (
    handle_current_session_smoke_trigger_if_matched,
    parse_current_session_smoke_trigger_command,
)
from .output.current_session_delivery_integration import (
    deliver_owner_action_current_session_if_enabled,
)
from .output.current_session_manual_smoke import (
    run_current_session_manual_smoke_if_enabled,
)
from .core.owner_action_gate import evaluate_owner_action_gate
from .core.owner_action_executor import build_owner_action_execution_plan
from .core.owner_action_context_resolver import (
    format_owner_action_context_summary,
    resolve_owner_action_context,
)
from .core.owner_action_reply_draft import (
    build_owner_action_reply_draft,
    format_owner_action_reply_draft_summary,
)
from .core.model_router import ModelRouter
from .core.model_profile_switcher import get_active_model_profile, list_model_profiles, set_active_model_profile
from .core.owner_action_router import parse_owner_action
from .core.isaac_agent_bus_p0 import handle_isaac_agent_bus_p0_message
from .core.owner_engineering_toolbox import (
    handle_owner_engineering_toolbox_message,
    handle_owner_engineering_toolbox_message_nl_async,
)
from .core.owner_toolbox_light import (
    build_owner_toolbox_tools,
    coerce_owner_toolbox_human_reply,
    execute_owner_toolbox_tool,
    execute_owner_toolbox_tool_async,
    get_owner_tool_loop_max_steps,
    handle_owner_toolbox_light_message,
    is_legacy_toolbox_prefix,
    parse_slash_command,
    prepare_owner_tool_loop_messages,
)
from .core.owner_toolbox.progress import (
    append_progress_audit,
    build_progress_llm_messages,
    format_compact_progress_message,
    format_progress_message,
    sanitize_mapping,
    sanitize_progress_llm_text,
    summarize_tool_result,
)
from .core.owner_rules import normalize_uid_list
from .core.prompt_builder import PromptBuilder
from .core.runtime_compat import escape_log_preview, resolve_memory_root, resolve_plugin_init_config
from .memory.skill_loader import SkillLoader
from .memory.store import MemoryStore
from .memory.explicit_handler import (
    handle_explicit_memory_message,
    handle_explicit_memory_message_async,
)
from .output.sender import Sender
from .output.sender_adapter import NoneBotCurrentSessionSenderAdapter


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parents[2] if len(BASE_DIR.parents) >= 3 else BASE_DIR.parent
DATA_DIR = BASE_DIR / "data"




def _build_runtime_config(plugin_settings: dict[str, Any] | None = None) -> RuntimeConfig:
    runtime_defaults = dict(DEFAULTS)
    explicit_overrides = {key: value for key, value in (plugin_settings or {}).items() if value is not None}
    if explicit_overrides:
        runtime_defaults.update(explicit_overrides)
    return RuntimeConfig(runtime_defaults, path=DATA_DIR / "runtime_config.json", explicit_overrides=explicit_overrides)


def _runtime_config_mapping_for_explicit_memory(config_obj: Any) -> dict[str, Any] | None:
    if isinstance(config_obj, dict):
        return config_obj
    overrides = getattr(config_obj, "overrides", None)
    if isinstance(overrides, dict):
        return overrides
    data = getattr(config_obj, "data", None)
    if isinstance(data, dict):
        return data
    return None


def _memory_injection_enabled_for_message(msg) -> bool:
    if not cfg.get_bool("memory_prompt_injection_enabled", False):
        return False
    channel = str(getattr(msg, "channel", "") or "")
    if channel == "private":
        if not bool(getattr(msg, "is_owner", False)):
            return False
        return cfg.get_bool("memory_prompt_injection_private_enabled", True)
    if channel == "group":
        # 今日只开 owner 私聊灰度；群聊长期记忆注入显式保持关闭。
        return False
    return False


def _collect_memory_observation(msg, decision, *, captured: bool, session_id: str | None = None, messages: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    resolved_session_id = session_id or _get_session_id(msg)
    channel = str(getattr(msg, "channel", "") or "")
    is_mentioned = bool(getattr(msg, "is_at_bot", False))
    will_reply = bool(getattr(decision, "should_reply", False))
    prompt_injected = False
    memory_items_used = 0
    memory_prompt_chars = 0
    truncated = False
    if messages:
        system_content = "\n\n".join(
            str(item.get("content") or "")
            for item in messages
            if isinstance(item, dict) and item.get("role") == "system"
        )
        prompt_injected = (
            "[短期上下文记忆]" in system_content
            or "[长期用户画像]" in system_content
            or "[用户印象]" in system_content
            or "[关系图谱]" in system_content
            or "[来自长期记忆的事实]" in system_content
        )
        memory_prompt_chars = len(system_content) if prompt_injected else 0
        memory_items_used = system_content.count("- ") if prompt_injected else 0
        truncated = "[记忆裁剪提示]" in system_content
    return {
        "session_id": resolved_session_id,
        "channel": channel,
        "is_mentioned": is_mentioned,
        "captured": bool(captured),
        "will_reply": will_reply,
        "prompt_injected": prompt_injected,
        "memory_items_used": memory_items_used,
        "memory_prompt_chars": memory_prompt_chars,
        "truncated": truncated,
    }


def _resolve_plugin_memory_root(plugin_settings: dict[str, Any] | None = None) -> Path:
    return resolve_memory_root(
        plugin_config=plugin_settings or {},
        data_dir=DATA_DIR,
        project_root=PROJECT_ROOT,
        cwd=Path.cwd(),
        env=os.environ,
    )


def _build_store_with_settings(cfg_obj: RuntimeConfig, plugin_settings: dict[str, Any] | None = None) -> MemoryStore:
    resolved_memory_root = _resolve_plugin_memory_root(plugin_settings)
    plugin_settings = dict(plugin_settings or {})
    plugin_settings["resolved_memory_root"] = str(resolved_memory_root)
    cfg_obj.overrides["resolved_memory_root"] = str(resolved_memory_root)
    logger.info(f"yangyang plugin: resolved_memory_root={resolved_memory_root}")
    return MemoryStore(
        str(DATA_DIR / "chat_history.db"),
        str(DATA_DIR / "cache"),
        memory_root=resolved_memory_root,
    )


def _is_loopback_host(host: str | None) -> bool:
    raw = str(host or '').strip().lower()
    if not raw:
        return False
    if raw.startswith('[') and raw.endswith(']'):
        raw = raw[1:-1]
    if ':' in raw and raw.count(':') == 1 and raw.rsplit(':', 1)[1].isdigit():
        raw = raw.rsplit(':', 1)[0]
    return raw in {'127.0.0.1', '::1', 'localhost'}


def register_internal_model_switch_api() -> None:
    try:
        driver = get_driver()
    except Exception:
        logger.warning('yangyang plugin: driver unavailable; skip internal model switch api registration')
        return
    app = getattr(driver, 'server_app', None)
    if app is None:
        logger.warning('yangyang plugin: server_app unavailable; skip internal model switch api registration')
        return
    if getattr(app.state, '_yy_model_switch_api_registered', False):
        for _name in (
            '_yy_internal_model_switch',
            '_yy_internal_model_reload',
            '_yy_internal_model_probe_fallback',
            '_yy_internal_chat_send_stream',
            '_yy_internal_model_status',
        ):
            _handler = getattr(app.state, _name, None)
            if _handler is not None:
                globals()[_name] = _handler
        return

    def _client_host(request: Request) -> str | None:
        client_host = getattr(getattr(request, 'client', None), 'host', None)
        forwarded = request.headers.get('x-forwarded-for', '')
        if forwarded:
            client_host = forwarded.split(',')[0].strip() or client_host
        return client_host

    @app.post('/yy/api/model/switch')
    async def _yy_internal_model_switch(request: Request) -> JSONResponse:
        if not _is_loopback_host(_client_host(request)):
            return JSONResponse({'ok': False, 'error': 'forbidden'}, status_code=403)
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        scope = str((payload or {}).get('scope') or 'private').strip() or 'private'
        profile = str((payload or {}).get('profile') or '').strip()
        if not profile:
            return JSONResponse({'ok': False, 'error': 'missing_profile'}, status_code=400)
        result = set_active_model_profile(cfg, profile_id=profile, scope=scope, context_channel='private' if scope != 'group' else 'group')
        if not bool(result.get('ok')):
            return JSONResponse({'ok': False, 'error': str(result.get('reason') or 'switch_failed'), 'data': result}, status_code=400)
        try:
            _sync_runtime_components()
        except Exception:
            logger.exception('yangyang plugin: sync runtime components failed after model switch')
            return JSONResponse({'ok': False, 'error': 'sync_runtime_failed', 'data': result}, status_code=500)
        return JSONResponse({'ok': True, 'mode': 'hot_switch', 'data': result})


    @app.post('/yy/api/model/reload')
    async def _yy_internal_model_reload(request: Request) -> JSONResponse:
        if not _is_loopback_host(_client_host(request)):
            return JSONResponse({'ok': False, 'error': 'forbidden'}, status_code=403)
        try:
            cfg.reload()
            _sync_runtime_components()
        except Exception:
            logger.exception('yangyang plugin: runtime reload failed via internal api')
            return JSONResponse({'ok': False, 'error': 'reload_failed'}, status_code=500)
        return JSONResponse({'ok': True, 'mode': 'reloaded'})


    @app.post('/yy/api/model/probe_fallback')
    async def _yy_internal_model_probe_fallback(request: Request) -> JSONResponse:
        if not _is_loopback_host(_client_host(request)):
            return JSONResponse({'ok': False, 'error': 'forbidden'}, status_code=403)
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        scope = str((payload or {}).get('scope') or 'private').strip().lower() or 'private'
        if scope not in {'private', 'group', 'isaac'}:
            scope = 'private'
        try:
            from .core.model.provider_base import ProviderResponse
            original_providers = dict(router.providers)
            provider_calls: dict[str, int] = {'primary': 0, 'fallback1': 0, 'fallback2': 0}

            class _ProbePrimary:
                provider_name = 'probe_primary'
                @property
                def is_available(self):
                    return True
                async def complete(self, **kwargs):
                    provider_calls['primary'] += 1
                    raise RuntimeError('upstream_timeout')

            class _ProbeFallback1:
                provider_name = 'probe_fallback1'
                @property
                def is_available(self):
                    return True
                async def complete(self, **kwargs):
                    provider_calls['fallback1'] += 1
                    raise RuntimeError('503 upstream_error')

            class _ProbeFallback2:
                provider_name = 'probe_fallback2'
                @property
                def is_available(self):
                    return True
                async def complete(self, **kwargs):
                    provider_calls['fallback2'] += 1
                    tier = str(kwargs.get('tier') or '')
                    model = str(kwargs.get('model') or '')
                    return ProviderResponse(content='probe-fallback-ok', model_used=model, tier=tier)

            cfg.reload()
            original_cfg = {
                'isaac_model_profile': str(cfg.get('isaac.model_profile', '') or ''),
                'isaac_fallback_profiles': list(cfg.get('isaac.fallback_profiles', []) or []),
                'private_profile': str(cfg.get('model_profile_switcher.active_profile_private', '') or ''),
                'private_fallback_profiles': list(cfg.get('model_profile_switcher.fallback_profiles_private', []) or []),
                'group_profile': str(cfg.get('model_profile_switcher.active_profile_group', '') or ''),
                'group_fallback_profiles': list(cfg.get('model_profile_switcher.fallback_profiles_group', []) or []),
            }
            if scope == 'private':
                cfg.set('model_profile_switcher.active_profile_private', 'probe_main_private')
                cfg.set('model_profile_switcher.fallback_profiles_private', ['probe_fb1_private', 'probe_fb2_private'])
                cfg.set('providers.probe_main_private', {'provider':'probe_primary','model':'probe-main-private','enabled':True,'timeout':3,'cooldown_on_fail':0})
                cfg.set('providers.probe_fb1_private', {'provider':'probe_fallback1','model':'probe-fb1-private','enabled':True,'timeout':3,'cooldown_on_fail':0})
                cfg.set('providers.probe_fb2_private', {'provider':'probe_fallback2','model':'probe-fb2-private','enabled':True,'timeout':3,'cooldown_on_fail':0})
                cfg.set('models.probe_main_private', {'model':'probe-main-private','enabled':True})
                cfg.set('models.probe_fb1_private', {'model':'probe-fb1-private','enabled':True})
                cfg.set('models.probe_fb2_private', {'model':'probe-fb2-private','enabled':True})
                requested_tier='v4_flash'; channel='private'; session_id='probe_fallback_private'
            elif scope == 'group':
                cfg.set('model_profile_switcher.active_profile_group', 'probe_main_group')
                cfg.set('model_profile_switcher.fallback_profiles_group', ['probe_fb1_group', 'probe_fb2_group'])
                cfg.set('providers.probe_main_group', {'provider':'probe_primary','model':'probe-main-group','enabled':True,'timeout':3,'cooldown_on_fail':0})
                cfg.set('providers.probe_fb1_group', {'provider':'probe_fallback1','model':'probe-fb1-group','enabled':True,'timeout':3,'cooldown_on_fail':0})
                cfg.set('providers.probe_fb2_group', {'provider':'probe_fallback2','model':'probe-fb2-group','enabled':True,'timeout':3,'cooldown_on_fail':0})
                cfg.set('models.probe_main_group', {'model':'probe-main-group','enabled':True})
                cfg.set('models.probe_fb1_group', {'model':'probe-fb1-group','enabled':True})
                cfg.set('models.probe_fb2_group', {'model':'probe-fb2-group','enabled':True})
                requested_tier='v4_flash'; channel='group'; session_id='probe_fallback_group'
            else:
                cfg.set('isaac.model_profile', 'probe_main_isaac')
                cfg.set('isaac.fallback_profiles', ['probe_fb1_isaac', 'probe_fb2_isaac'])
                cfg.set('providers.probe_main_isaac', {'provider':'probe_primary','model':'probe-main-isaac','enabled':True,'timeout':3,'cooldown_on_fail':0})
                cfg.set('providers.probe_fb1_isaac', {'provider':'probe_fallback1','model':'probe-fb1-isaac','enabled':True,'timeout':3,'cooldown_on_fail':0})
                cfg.set('providers.probe_fb2_isaac', {'provider':'probe_fallback2','model':'probe-fb2-isaac','enabled':True,'timeout':3,'cooldown_on_fail':0})
                cfg.set('models.probe_main_isaac', {'model':'probe-main-isaac','enabled':True})
                cfg.set('models.probe_fb1_isaac', {'model':'probe-fb1-isaac','enabled':True})
                cfg.set('models.probe_fb2_isaac', {'model':'probe-fb2-isaac','enabled':True})
                requested_tier='probe_main_isaac'; channel=''; session_id='probe_fallback_isaac'
            _sync_runtime_components()
            router.providers['probe_primary'] = _ProbePrimary()
            router.providers['probe_fallback1'] = _ProbeFallback1()
            router.providers['probe_fallback2'] = _ProbeFallback2()
            result = await router.call(requested_tier, [{'role':'user','content':'probe fallback please'}], session_id=session_id, channel=channel, timeout_bucket="normal", interaction_phase="fallback_probe", allow_streaming=False)
            snap = {
                'ok': True,
                'scope': scope,
                'result': result,
                'provider_calls': provider_calls,
                'fallback_runtime': {
                    'used': bool(getattr(router, 'last_call_fallback_used', False)),
                    'from_profile': str(getattr(router, 'last_call_fallback_from', '') or ''),
                    'to_profile': str(getattr(router, 'last_call_fallback_to', '') or ''),
                    'reason': str(getattr(router, 'last_call_fallback_reason', '') or ''),
                    'at': float(getattr(router, 'last_call_fallback_at', 0.0) or 0.0),
                    'requested_tier': str(getattr(router, 'last_call_requested_tier', '') or ''),
                    'resolved_profile': str(getattr(router, 'last_call_resolved_profile', '') or ''),
                    'channel_scope': str(getattr(router, 'last_call_channel_scope', '') or ''),
                },
                'fallback_history_tail': list(getattr(router, 'fallback_history', []) or [])[-3:],
                'fallback_stats': dict(getattr(router, 'fallback_stats', {}) or {}),
            }
        except Exception as exc:
            return JSONResponse({'ok': False, 'error': f'probe_failed:{exc.__class__.__name__}:{exc}'}, status_code=500)
        finally:
            try:
                if scope == 'private':
                    cfg.set('model_profile_switcher.active_profile_private', original_cfg.get('private_profile', 'v4_flash'))
                    cfg.set('model_profile_switcher.fallback_profiles_private', list(original_cfg.get('private_fallback_profiles', []) or []))
                elif scope == 'group':
                    cfg.set('model_profile_switcher.active_profile_group', original_cfg.get('group_profile', 'v4_flash'))
                    cfg.set('model_profile_switcher.fallback_profiles_group', list(original_cfg.get('group_fallback_profiles', []) or []))
                else:
                    cfg.set('isaac.model_profile', original_cfg.get('isaac_model_profile', 'v4_pro'))
                    cfg.set('isaac.fallback_profiles', list(original_cfg.get('isaac_fallback_profiles', []) or []))
                for probe_key in [
                    'providers.probe_main_private','providers.probe_fb1_private','providers.probe_fb2_private',
                    'providers.probe_main_group','providers.probe_fb1_group','providers.probe_fb2_group',
                    'providers.probe_main_isaac','providers.probe_fb1_isaac','providers.probe_fb2_isaac',
                    'models.probe_main_private','models.probe_fb1_private','models.probe_fb2_private',
                    'models.probe_main_group','models.probe_fb1_group','models.probe_fb2_group',
                    'models.probe_main_isaac','models.probe_fb1_isaac','models.probe_fb2_isaac',
                ]:
                    cfg.delete(probe_key)
                cfg.reload()
                router.providers.clear()
                router.providers.update(original_providers)
                _sync_runtime_components()
            except Exception:
                logger.exception('yangyang plugin: failed to restore runtime after probe_fallback')
        return JSONResponse(snap)

    def _yy_sse_encode(event: str, payload: dict[str, Any] | None = None) -> bytes:
        body = json.dumps(payload or {}, ensure_ascii=False)
        return f"event: {event}\ndata: {body}\n\n".encode('utf-8')

    @app.post('/yy/api/chat/send_stream', response_model=None)
    async def _yy_internal_chat_send_stream(request: Request) -> StreamingResponse | JSONResponse:
        if not _is_loopback_host(_client_host(request)):
            return JSONResponse({'ok': False, 'error': 'forbidden'}, status_code=403)
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        payload = payload or {}
        text = str(payload.get('text') or payload.get('message') or '').strip()
        incoming_messages = payload.get('messages')
        if isinstance(incoming_messages, list) and incoming_messages:
            messages = [item for item in incoming_messages if isinstance(item, dict)]
        else:
            messages = []
        if not messages and text:
            messages = [{'role': 'user', 'content': text}]
        if not messages:
            return JSONResponse({'ok': False, 'error': 'missing_text'}, status_code=400)

        scope = str(payload.get('scope') or 'private').strip().lower() or 'private'
        if scope not in {'private', 'group', 'isaac'}:
            scope = 'private'
        requested_tier = str(payload.get('tier') or payload.get('profile') or 'v4_flash').strip() or 'v4_flash'
        session_id = str(payload.get('session_id') or f"webui:{scope}:{int(time.time() * 1000)}")
        channel = 'group' if scope == 'group' else ('private' if scope == 'private' else '')

        async def _event_stream():
            queue: asyncio.Queue[tuple[str, dict[str, Any]]] = asyncio.Queue()
            finished = asyncio.Event()
            client_disconnected = False

            async def _on_stream_delta(delta_text, meta):
                if finished.is_set():
                    return
                delta = str(delta_text or '')
                if not delta:
                    return
                await queue.put((
                    'plain',
                    {
                        'text': delta,
                        'delta': delta,
                        'session_id': session_id,
                        'meta': dict(meta) if isinstance(meta, dict) else {},
                    },
                ))

            async def _run_model_call():
                try:
                    response_text, actual_tier = await router.call(
                        requested_tier,
                        messages,
                        session_id=session_id,
                        channel=channel,
                        timeout_bucket='normal',
                        interaction_phase='webui_internal_stream',
                        allow_streaming=True,
                        stream_callback=_on_stream_delta,
                    )
                    if finished.is_set():
                        return
                    await queue.put((
                        'agent_stats',
                        {
                            'session_id': session_id,
                            'request_id': str(getattr(router, 'last_call_request_id', '') or ''),
                            'requested_tier': requested_tier,
                            'actual_tier': actual_tier,
                            'resolved_profile': str(getattr(router, 'last_call_resolved_profile', '') or ''),
                            'fallback_used': bool(getattr(router, 'last_call_fallback_used', False)),
                            'fallback_from': str(getattr(router, 'last_call_fallback_from', '') or ''),
                            'fallback_to': str(getattr(router, 'last_call_fallback_to', '') or ''),
                            'fallback_reason': str(getattr(router, 'last_call_fallback_reason', '') or ''),
                        },
                    ))
                    await queue.put((
                        'end',
                        {
                            'ok': True,
                            'session_id': session_id,
                            'response': response_text,
                            'actual_tier': actual_tier,
                        },
                    ))
                except asyncio.CancelledError:
                    logger.info('yangyang plugin: internal sse stream cancelled session_id=%s', session_id)
                    raise
                except Exception as exc:
                    logger.exception('yangyang plugin: internal sse stream failed session_id=%s', session_id)
                    if not finished.is_set():
                        await queue.put((
                            'error',
                            {
                                'ok': False,
                                'session_id': session_id,
                                'error': str(getattr(router, 'last_call_error_type', '') or 'stream_call_failed'),
                                'detail': str(exc),
                                'request_id': str(getattr(router, 'last_call_request_id', '') or ''),
                            },
                        ))
                finally:
                    finished.set()

            yield _yy_sse_encode('proxy_open', {
                'ok': True,
                'scope': scope,
                'session_id': session_id,
                'requested_tier': requested_tier,
            })
            yield _yy_sse_encode('session_id', {'session_id': session_id})

            task = asyncio.create_task(_run_model_call())
            try:
                while True:
                    if await request.is_disconnected():
                        client_disconnected = True
                        logger.info('yangyang plugin: internal sse client disconnected session_id=%s', session_id)
                        break
                    if finished.is_set() and queue.empty():
                        break
                    try:
                        event_name, event_payload = await asyncio.wait_for(queue.get(), timeout=0.25)
                    except asyncio.TimeoutError:
                        continue
                    yield _yy_sse_encode(event_name, event_payload)
            finally:
                finished.set()
                if not task.done():
                    task.cancel()
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            if not client_disconnected:
                yield _yy_sse_encode('proxy_closed', {'session_id': session_id})

        return StreamingResponse(
            _event_stream(),
            media_type='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no',
            },
        )

    globals()['_yy_internal_model_switch'] = _yy_internal_model_switch
    globals()['_yy_internal_model_reload'] = _yy_internal_model_reload
    globals()['_yy_internal_model_probe_fallback'] = _yy_internal_model_probe_fallback
    globals()['_yy_internal_chat_send_stream'] = _yy_internal_chat_send_stream

    app.state._yy_internal_model_switch = _yy_internal_model_switch
    app.state._yy_internal_model_reload = _yy_internal_model_reload
    app.state._yy_internal_model_probe_fallback = _yy_internal_model_probe_fallback
    app.state._yy_internal_chat_send_stream = _yy_internal_chat_send_stream

    @app.get('/yy/api/model/status')
    async def _yy_internal_model_status(request: Request) -> JSONResponse:
        if not _is_loopback_host(_client_host(request)):
            return JSONResponse({'ok': False, 'error': 'forbidden'}, status_code=403)
        private_data = get_active_model_profile(cfg, scope='private', context_channel='private')
        group_data = get_active_model_profile(cfg, scope='group', context_channel='group')
        profiles = list_model_profiles(cfg, scope='private', include_disabled=True, context_channel='private')
        isaac_profile = str(cfg.get('isaac.model_profile', '') or '')
        isaac_fallback = str(cfg.get('isaac.fallback_model_profile', '') or '')
        private_fallback = str(cfg.get('model_profile_switcher.fallback_profile_private', '') or '')
        group_fallback = str(cfg.get('model_profile_switcher.fallback_profile_group', '') or '')
        isaac_fallback_chain = list(cfg.get('isaac.fallback_profiles', []) or [])
        private_fallback_chain = list(cfg.get('model_profile_switcher.fallback_profiles_private', []) or [])
        group_fallback_chain = list(cfg.get('model_profile_switcher.fallback_profiles_group', []) or [])
        fallback_runtime = {
            'used': bool(getattr(router, 'last_call_fallback_used', False)),
            'from_profile': str(getattr(router, 'last_call_fallback_from', '') or ''),
            'to_profile': str(getattr(router, 'last_call_fallback_to', '') or ''),
            'reason': str(getattr(router, 'last_call_fallback_reason', '') or ''),
            'at': float(getattr(router, 'last_call_fallback_at', 0.0) or 0.0),
            'requested_tier': str(getattr(router, 'last_call_requested_tier', '') or ''),
            'resolved_profile': str(getattr(router, 'last_call_resolved_profile', '') or ''),
            'channel_scope': str(getattr(router, 'last_call_channel_scope', '') or ''),
        }
        fallback_history = list(getattr(router, 'fallback_history', []) or [])
        fallback_stats = dict(getattr(router, 'fallback_stats', {}) or {})
        return JSONResponse({
            'ok': True,
            'mode': 'runtime_status',
            'private_active': private_data.get('profile_id'),
            'group_active': group_data.get('profile_id'),
            'private_profile': private_data.get('profile'),
            'group_profile': group_data.get('profile'),
            'isaac_profile': isaac_profile,
            'isaac_fallback_profile': isaac_fallback,
            'private_fallback_profile': private_fallback,
            'group_fallback_profile': group_fallback,
            'isaac_fallback_profiles': isaac_fallback_chain,
            'private_fallback_profiles': private_fallback_chain,
            'group_fallback_profiles': group_fallback_chain,
            'fallback_runtime': fallback_runtime,
            'fallback_history': fallback_history,
            'fallback_stats': fallback_stats,
            'profiles': profiles.get('profiles', []),
        })

    globals()['_yy_internal_model_status'] = _yy_internal_model_status
    app.state._yy_internal_model_status = _yy_internal_model_status
    app.state._yy_model_switch_api_registered = True
    logger.info('yangyang plugin: registered internal model switch api at /yy/api/model/switch and /yy/api/chat/send_stream')


def _sync_runtime_components() -> None:
    global adapter
    store.configure_short_term_limit(int(cfg.get("memory_short_term_limit", 100) or 100))
    memory_system = getattr(store, "memory_system", None)
    if memory_system is not None:
        try:
            memory_system.prompt_char_budget = max(400, int(cfg.get("memory_prompt_char_budget", getattr(memory_system, "prompt_char_budget", 2400)) or getattr(memory_system, "prompt_char_budget", 2400)))
        except Exception:
            pass
        try:
            memory_system.prompt_short_term_item_limit = max(1, int(cfg.get("memory_prompt_short_term_item_limit", getattr(memory_system, "prompt_short_term_item_limit", 8)) or getattr(memory_system, "prompt_short_term_item_limit", 8)))
        except Exception:
            pass
    injection_enabled = cfg.get_bool("memory_prompt_injection_enabled", False)
    builder.memory_enabled = injection_enabled
    # C4 总闸同源控制 PromptBuilder 与 MemoryStore 检索，避免“分闸开了但 store 仍 skipped”。
    store.configure_retrieval(
        enabled=injection_enabled,
        private_only=True,
        top_k=int(cfg.get("memory_long_term_retrieval_top_k", 3) or 3),
        char_budget=int(cfg.get("memory_long_term_retrieval_char_budget", 500) or 500),
        grounding_enabled=cfg.get_bool("memory_long_term_retrieval_grounding_enabled", False),
    )
    store.owner_id = str(cfg.get("owner_uid", "335059272") or "335059272")
    if hasattr(builder, "configure_knowledge"):
        builder.configure_knowledge(
            enabled=cfg.get_bool("knowledge_enabled", False, env_key="YANGYANG_KNOWLEDGE_ENABLED"),
            root_dir=cfg.get("knowledge_root_dir", str(DATA_DIR / "knowledge")),
            top_k=int(cfg.get("knowledge_top_k", 3) or 3),
            char_budget=int(cfg.get("knowledge_char_budget", 900) or 900),
            min_score=float(cfg.get("knowledge_min_score", 0.18) or 0.18),
        )
    adapter = EventAdapter(
        owner_id=str(cfg.get("owner_uid", "335059272")),
        owner_uids=normalize_uid_list(cfg.get("owner_uids", []), cfg.get("owner_uid", "335059272")),
    )


def initialize_plugin(context: Any = None, config: Any = None, plugin_config: Any = None) -> dict[str, Any]:
    global cfg, store, skill_loader, cooldown, router, builder, engine, adapter
    plugin_settings = resolve_plugin_init_config(context=context, config=config, plugin_config=plugin_config)
    cfg = _build_runtime_config(plugin_settings)
    store = _build_store_with_settings(cfg, plugin_settings)
    skill_loader = SkillLoader(str(DATA_DIR / "skills"))
    cooldown = CooldownManager(cfg)
    router = ModelRouter(cfg)
    builder = PromptBuilder(store, skill_loader)
    engine = DecisionEngine(store, skill_loader)
    _sync_runtime_components()
    return plugin_settings


plugin_init_settings = initialize_plugin()
register_internal_model_switch_api()

# 加载 MemoryPipeline 定时任务；必须在 store/cfg 初始化后注册 driver hooks。
from . import tasks as _tasks_init  # noqa: F401,E402


# Legacy /yy-web WebUI disabled on 2026-06-14.
# Canonical operations console is agentbus-factory-webui.service on port 8787.
# Do not register the old monkey-version /yy-web route; it interferes with the real console.


async def _is_group_or_private(event) -> bool:
    return isinstance(event, (GroupMessageEvent, PrivateMessageEvent))


def _is_dry_run_enabled() -> bool:
    return cfg.get_bool("dry_run", False, env_key="YANGYANG_DRY_RUN")


def _reload_runtime_config_for_smoke() -> str:
    try:
        cfg.reload()
        _sync_runtime_components()
        return "ok"
    except Exception:
        logger.exception("yangyang plugin: current-session smoke trigger reload failed")
        return "error"


def _get_session_id(msg) -> str:
    if getattr(msg, "channel", "") == "group":
        return f"group:{str(getattr(msg, 'group_id', '') or '')}"
    return f"private:{str(getattr(msg, 'uid', '') or '')}"


def _handle_local_model_command(msg) -> str | None:
    text = str(getattr(msg, 'text', '') or getattr(msg, 'raw_content', '') or '').strip()
    if text not in {'/model', 'model', '模型', '现在什么模型'}:
        return None
    channel = str(getattr(msg, 'channel', '') or '')
    if channel == 'group':
        data = get_active_model_profile(cfg, scope='group', context_channel='group')
        fallback = list(cfg.get('model_profile_switcher.fallback_profiles_group', []) or [])
        scope = 'group'
        legacy_fb = str(cfg.get('model_profile_switcher.fallback_profile_group', '') or '').strip()
    else:
        data = get_active_model_profile(cfg, scope='private', context_channel='private')
        fallback = list(cfg.get('model_profile_switcher.fallback_profiles_private', []) or [])
        scope = 'private'
        legacy_fb = str(cfg.get('model_profile_switcher.fallback_profile_private', '') or '').strip()
    if legacy_fb and legacy_fb not in fallback:
        fallback.append(legacy_fb)
    profile = data.get('profile') or {}
    pid = str(data.get('profile_id') or '')
    provider = str(profile.get('provider') or '')
    model = str(profile.get('model') or '')
    enabled = bool(profile.get('enabled', False))

    explicit_fb = [x for x in fallback if str(x).strip() and str(x).strip() != pid]
    explicit_fb_text = ' -> '.join(explicit_fb) if explicit_fb else '无'

    return (
        f'当前{scope}模型：{pid or "(未设置)"}\n'
        f'provider：{provider or "(未知)"}\n'
        f'model：{model or "(未知)"}\n'
        f'enabled：{enabled}\n'
        f'显式fallback：{explicit_fb_text}'
    )


def _legacy_owner_engineering_toolbox_requested(msg) -> bool:
    return is_legacy_toolbox_prefix(msg)


def _owner_tool_loop_max_steps() -> int:
    return get_owner_tool_loop_max_steps(cfg)


def _memory_audit_path() -> Path:
    raw_path = str(cfg.get("memory_capture_audit_path", "logs/memory_capture_audit.jsonl") or "logs/memory_capture_audit.jsonl")
    path = Path(raw_path)
    if not path.is_absolute():
        base_dir = Path(str(cfg.get("resolved_memory_root", DATA_DIR / "memory") or (DATA_DIR / "memory")))
        path = (base_dir / path).resolve()
    return path


def _text_sha256_16(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()[:16]


def _message_raw_hash_and_length(msg) -> tuple[str, int]:
    raw = str(getattr(msg, "text", "") or getattr(msg, "raw_content", "") or "")
    return _text_sha256_16(raw), len(raw)


def _write_memory_capture_audit(msg, session_id: str) -> None:
    if not cfg.get_bool("memory_capture_audit_enabled", True):
        return
    try:
        path = _memory_audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        raw_hash, raw_length = _message_raw_hash_and_length(msg)
        sensitive_failure = bool(getattr(msg, "sensitive_failure", False))
        record = {
            "timestamp": getattr(msg, "timestamp", 0),
            "session_id": session_id,
            "user_id": str(getattr(msg, "uid", "") or ""),
            "channel": str(getattr(msg, "channel", "") or ""),
            "group_id": str(getattr(msg, "group_id", "") or ""),
            "raw_hash": raw_hash,
            "raw_length": raw_length,
            "raw_dropped": sensitive_failure,
            "request_id": str(getattr(msg, "sensitive_failure_request_id", "") or ""),
            "error_type": str(getattr(msg, "sensitive_failure_error_type", "") or ""),
        }
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info(
            f"yangyang plugin: memory_capture_audit session_id={record['session_id']} "
            f"user_id={record['user_id']} channel={record['channel']} hash={record['raw_hash']} "
            f"length={record['raw_length']} raw_dropped={record['raw_dropped']} "
            f"error_type={record['error_type']} request_id={record['request_id']}"
        )
    except Exception:
        logger.exception("yangyang plugin: failed to write memory capture audit")


def _capture_short_term_memory(msg) -> bool:
    if not cfg.get_bool("memory_short_term_capture_enabled", False):
        return False
    try:
        limit = int(cfg.get("memory_short_term_limit", 100) or 100)
        store.configure_short_term_limit(limit)
        session_id = _get_session_id(msg)
        raw_hash, raw_length = _message_raw_hash_and_length(msg)
        sensitive_failure = bool(getattr(msg, "sensitive_failure", False))
        safe_text = "[raw_dropped:sensitive_failure]" if sensitive_failure else str(getattr(msg, "text", "") or getattr(msg, "raw_content", "") or "")
        payload = {
            "uid": str(getattr(msg, "uid", "") or ""),
            "user_id": str(getattr(msg, "uid", "") or ""),
            "text": safe_text,
            "raw_content": safe_text,
            "timestamp": float(getattr(msg, "timestamp", 0) or 0),
            "message_id": str(getattr(msg, "msg_id", "") or ""),
            "type": "message" if not sensitive_failure else "sensitive_failure_event",
            "group_id": str(getattr(msg, "group_id", "") or ""),
            "nick": str(getattr(msg, "nick", "") or ""),
            "channel": str(getattr(msg, "channel", "") or ""),
            "session_id": session_id,
            "raw_dropped": sensitive_failure,
            "raw_hash": raw_hash,
            "raw_length": raw_length,
            "request_id": str(getattr(msg, "sensitive_failure_request_id", "") or ""),
            "error_type": str(getattr(msg, "sensitive_failure_error_type", "") or ""),
        }
        store.memory_system.add_to_short_term(session_id, payload)
        _write_memory_capture_audit(msg, session_id)
        return True
    except Exception:
        logger.exception("yangyang plugin: failed to capture short term memory")
        return False


def _log_current_session_smoke_trigger_result(msg, smoke_command, reload_status: str) -> None:
    logger.info(
        "yangyang plugin: current-session smoke trigger matched uid=%s channel=%s reload_status=%s enabled=%s dry_run=%s reason=%s inner_text=%s",
        getattr(msg, "uid", ""),
        getattr(msg, "channel", ""),
        reload_status,
        cfg.get_bool("owner_action_manual_smoke_enabled", False),
        _is_dry_run_enabled(),
        getattr(smoke_command, "reason", ""),
        getattr(smoke_command, "inner_text", ""),
    )

def _summarize_text_for_log(text: str, limit: int = 80) -> str:
    return escape_log_preview(text, limit=limit)


def _should_log_decision_trace(msg, decision) -> bool:
    return bool(
        getattr(msg, "is_owner", False)
        or getattr(msg, "is_at_bot", False)
        or bool(getattr(msg, "at_user_ids", None))
        or getattr(decision, "should_reply", False)
    )


def _log_decision_trace(msg, decision) -> None:
    if not _should_log_decision_trace(msg, decision):
        return

    logger.info(
        "yangyang plugin: decision_trace uid=%s group_id=%s channel=%s bot_self_id=%s text=%s at_user_ids=%s is_at_bot=%s is_owner=%s owner_command=%s explicit_command=%s should_reply=%s reason=%s is_forced=%s model_tier=%s",
        getattr(msg, "uid", ""),
        getattr(msg, "group_id", ""),
        getattr(msg, "channel", ""),
        getattr(msg, "bot_self_id", ""),
        _summarize_text_for_log(getattr(msg, "text", "")),
        getattr(msg, "at_user_ids", []),
        getattr(msg, "is_at_bot", False),
        getattr(msg, "is_owner", False),
        getattr(msg, "owner_command", False),
        getattr(msg, "explicit_command", False),
        getattr(decision, "should_reply", False),
        getattr(decision, "reason", ""),
        getattr(decision, "is_forced", False),
        getattr(decision, "model_tier", None),
    )


def _format_owner_action_summary(action) -> str:
    if action is None:
        return ""

    target_group = action.target_group_id or "-"
    target_user = action.target_user_id or "-"
    reason = str(action.reason or "").replace("\n", " ").strip() or "-"
    return (
        "[dry_run][owner_action] "
        f"action={action.action_type} "
        f"style={action.style} "
        f"target_group={target_group} "
        f"target_user={target_user} "
        f"reason={reason}"
    )



def _format_owner_action_gate_summary(gate) -> str:
    if gate is None:
        return ""

    reason = str(gate.reason or "").replace("\n", " ").strip() or "-"
    return (
        "[dry_run][owner_action_gate] "
        f"mode={gate.mode} "
        f"allowed={str(bool(gate.allowed)).lower()} "
        f"reason={reason} "
        f"safe={str(bool(gate.safe_to_execute)).lower()} "
        f"execution_enabled={str(bool(getattr(gate, 'execution_enabled', False))).lower()} "
        f"blocked_by_config={str(bool(getattr(gate, 'blocked_by_config', False))).lower()} "
        f"permission={getattr(gate, 'permission', 'none')}"
    )


def _format_owner_action_execution_plan_summary(plan) -> str:
    if plan is None:
        return ""

    reason = str(plan.reason or "").replace("\n", " ").strip() or "-"
    destination = plan.destination_type
    if plan.destination_id:
        destination = f"{destination}:{plan.destination_id}"
    return (
        "[dry_run][owner_action_executor] "
        f"action={plan.action_type} "
        f"destination={destination} "
        f"status={plan.status} "
        f"real_send={str(bool(plan.real_send)).lower()} "
        f"reason={reason}"
    )


def _format_owner_action_delivery_summary(delivery) -> str:
    return format_owner_action_delivery_summary(delivery)


def _build_recent_owner_action_messages(msg):
    try:
        if msg.channel == "group":
            return store.get_recent_messages(msg.group_id, limit=12, channel="group")
        return store.get_recent_messages("", limit=12, channel=None)
    except Exception:
        logger.exception("yangyang plugin: failed to load recent messages for owner action context")
        return []


def _is_known_bot_uid(uid: str, bot_uid: str) -> bool:
    uid = str(uid or "")
    if not uid:
        return False

    known = {str(bot_uid or "")}
    configured = cfg.get("known_bot_uids", []) or []
    if isinstance(configured, list):
        known.update(str(item) for item in configured if str(item or ""))
    return uid in known


def _bot_loop_guard_enabled() -> bool:
    return cfg.get_bool("behavior.bot_loop_enabled", True)


def _should_block_by_bot_loop(msg, decision, bot_uid: str) -> bool:
    """群聊 bot loop 防护：最近窗口内多 bot 交替则触发群级冷却。"""
    try:
        if msg.channel != "group":
            return False
        if not _bot_loop_guard_enabled():
            return False

        current_is_known_bot = _is_known_bot_uid(msg.uid, bot_uid)
        if decision.is_forced:
            return current_is_known_bot and not getattr(msg, "owner_command", False)

        group_id = str(msg.group_id or "")
        if cooldown.is_group_bot_loop_cooling(group_id):
            return True

        recent_limit = int(cfg.get("behavior.bot_loop_recent_limit", 8) or 8)
        min_bot_messages = int(cfg.get("behavior.bot_loop_min_bot_messages", 3) or 3)
        if recent_limit <= 0 or min_bot_messages <= 0:
            return False

        recent = store.get_recent_messages(group_id, limit=recent_limit, channel="group")

        bot_rows = [row for row in recent if _is_known_bot_uid(str(row.get("uid", "")), bot_uid)]
        if current_is_known_bot:
            bot_rows.append({"uid": str(msg.uid)})

        if len(bot_rows) < min_bot_messages:
            return False

        bot_uids = [str(row.get("uid", "")) for row in bot_rows if str(row.get("uid", ""))]
        unique_bot_uids = set(bot_uids)
        if len(unique_bot_uids) < 2:
            return False

        alternations = 0
        for idx in range(1, len(bot_uids)):
            if bot_uids[idx] != bot_uids[idx - 1]:
                alternations += 1

        if alternations < 1:
            return False

        cooldown.activate_group_bot_loop_cooldown(group_id)
        logger.info(
            "yangyang plugin: activate bot loop cooldown group=%s bot_messages=%s unique_bots=%s alternations=%s uid=%s",
            group_id,
            len(bot_uids),
            len(unique_bot_uids),
            alternations,
            msg.uid,
        )
        return True
    except Exception:
        logger.exception("yangyang plugin: failed to check bot loop guard")
        return False


matcher = on_message(rule=Rule(_is_group_or_private), priority=50, block=False)


@matcher.handle()
async def handle_message(bot: Bot, event):
    """NoneBot 插件主入口。"""
    try:
        if isinstance(event, GroupMessageEvent):
            msg = adapter.adapt_group_msg(event)
        elif isinstance(event, PrivateMessageEvent):
            msg = adapter.adapt_private_msg(event)
        else:
            return

        smoke_command = parse_current_session_smoke_trigger_command(getattr(msg, "text", None) or getattr(msg, "raw_content", None))
        smoke_trigger_matched = bool(getattr(smoke_command, "matched", False))
        smoke_reload_status = "skipped"
        if smoke_trigger_matched:
            smoke_reload_status = _reload_runtime_config_for_smoke()
            _log_current_session_smoke_trigger_result(msg, smoke_command, smoke_reload_status)

        owner_action = parse_owner_action(msg, cfg)
        if owner_action is not None and getattr(msg, "is_owner", False):
            setattr(msg, "owner_command", True)
            setattr(msg, "explicit_command", True)
        # I叔 slash 兜底必须在 owner_toolbox_light 之前处理。
        # 自然语言是否调用 I叔，只允许后续 LLM/tool-call 判断，不能关键词粗暴劫持。
        isaac_p0_pre_result = None
        if (
            bool(getattr(msg, "is_owner", False))
            and str(getattr(msg, "channel", "") or "") == "private"
            and bool(
                getattr(msg, "explicit_command", False)
                or getattr(msg, "isaac_p0_natural_delegate", False)
                or getattr(msg, "natural_llm_delegate", False)
                or re.match(r"^/(?:i叔|I叔|艾萨克)(?=$|[\s/:：])", str(getattr(msg, "text", "") or getattr(msg, "raw_content", "") or ""))
            )
        ):
            try:
                isaac_p0_pre_result = handle_isaac_agent_bus_p0_message(msg, model_router=router)
            except Exception as exc:  # noqa: BLE001
                logger.warning("yangyang plugin: isaac_p0 pre bus call failed: %s", type(exc).__name__)
        if isaac_p0_pre_result is not None and isaac_p0_pre_result.handled:
            decision = engine.decide(msg)
            _log_decision_trace(msg, decision)
            store.record_message(msg, is_bot=False)
            sender = Sender(bot, store, cooldown, bot_uid=str(getattr(bot, "self_id", "")), dry_run=_is_dry_run_enabled(), config=cfg)
            await sender.send(msg, decision, isaac_p0_pre_result.reply, actual_tier="local")
            logger.info(
                f"yangyang plugin: isaac_p0 pre handled allowed={isaac_p0_pre_result.allowed} "
                f"reason={isaac_p0_pre_result.reason} task_type={isaac_p0_pre_result.task_type} "
                f"normal_prompt_bypassed=True memory_builder_skipped=True"
            )
            return

        # 明确 slash 兜底入口保持早退：/toolbox、/help、/confirm 等。
        # 普通 owner 私聊不在这里被 Light 自然语言解析抢占；后面走正常 PromptBuilder + ModelRouter native tool loop。
        # max_steps 自然语言查询/设置也不在这里做固定句式匹配，统一由 LLM tool_call 配置工具完成。
        slash_command = parse_slash_command(msg)
        owner_toolbox_light_result = None
        if slash_command is not None:
            owner_toolbox_light_result = await handle_owner_toolbox_light_message(
                msg,
                cfg,
                project_root=PROJECT_ROOT,
                model_router=router,
            )
        setattr(msg, "owner_toolbox_light_result", owner_toolbox_light_result)
        if owner_toolbox_light_result is not None and owner_toolbox_light_result.handled:
            toolbox_user_reply = getattr(owner_toolbox_light_result, "reply", "") or getattr(owner_toolbox_light_result, "output", "")
            if toolbox_user_reply:
                decision = engine.decide(msg)
                _log_decision_trace(msg, decision)
                store.record_message(msg, is_bot=False)
                sender = Sender(
                    bot,
                    store,
                    cooldown,
                    bot_uid=str(getattr(bot, "self_id", "")),
                    dry_run=_is_dry_run_enabled(),
                    config=cfg,
                )
                await sender.send(msg, decision, toolbox_user_reply, actual_tier="owner_toolbox_light")
            else:
                store.record_message(msg, is_bot=False)
            logger.info(
                "yangyang plugin: owner_toolbox_light handled tool=%s allowed=%s reason=%s channel=%s owner=%s",
                owner_toolbox_light_result.tool_name,
                owner_toolbox_light_result.allowed,
                owner_toolbox_light_result.reason,
                getattr(msg, "channel", ""),
                getattr(msg, "is_owner", False),
            )
            return

        if _legacy_owner_engineering_toolbox_requested(msg):
            toolbox_result = await handle_owner_engineering_toolbox_message_nl_async(
                msg,
                cfg,
                project_root=PROJECT_ROOT,
                model_router=router,
            )
        else:
            toolbox_result = None
        setattr(msg, "owner_engineering_toolbox_result", toolbox_result)
        if toolbox_result is not None and toolbox_result.handled:
            toolbox_user_reply = getattr(toolbox_result, "formatted_text", None) or toolbox_result.reply
            if toolbox_user_reply:
                decision = engine.decide(msg)
                _log_decision_trace(msg, decision)
                store.record_message(msg, is_bot=False)
                sender = Sender(
                    bot,
                    store,
                    cooldown,
                    bot_uid=str(getattr(bot, "self_id", "")),
                    dry_run=_is_dry_run_enabled(),
                    config=cfg,
                )
                await sender.send(msg, decision, toolbox_user_reply, actual_tier="local_toolbox")
            else:
                store.record_message(msg, is_bot=False)
            logger.info(
                "yangyang plugin: owner_engineering_toolbox handled tool=%s allowed=%s reason=%s actor=%s mode=%s intent_action=%s intent_source=%s real_write=%s real_execute=%s",
                toolbox_result.tool_name,
                toolbox_result.allowed,
                toolbox_result.reason,
                getattr(toolbox_result.gate, "actor", None),
                getattr(toolbox_result.gate, "mode", None),
                getattr(getattr(toolbox_result, "intent_plan", None), "action", None),
                getattr(getattr(toolbox_result, "intent_plan", None), "source", None),
                bool(getattr(toolbox_result.execution, "real_write", False)) if toolbox_result.execution is not None else False,
                bool(getattr(toolbox_result.execution, "real_execute", False)) if toolbox_result.execution is not None else False,
            )
            return

        # I叔 P0/Agent Bus v0.1 wiring: owner+private slash /i叔|/艾萨克 OR a
        # natural-language delegation from upstream LLM/tool loop reaches the
        # bus.  Group / non-owner remains locked (the bus itself enforces
        # channel=private and is_owner=True).  The model_router is forwarded
        # so the optional IsaacAgent decision layer can call V4 Pro.
        isaac_p0_result = None
        if (
            bool(getattr(msg, "is_owner", False))
            and str(getattr(msg, "channel", "") or "") == "private"
            and bool(getattr(msg, "explicit_command", False) or getattr(msg, "isaac_p0_natural_delegate", False) or getattr(msg, "natural_llm_delegate", False))
        ):
            try:
                isaac_p0_result = handle_isaac_agent_bus_p0_message(
                    msg,
                    model_router=router,
                )
            except Exception as exc:  # noqa: BLE001 - fail-soft to native loop.
                try:
                    logger.warning(
                        "yangyang plugin: isaac_p0 bus call failed: %s",
                        type(exc).__name__,
                    )
                except Exception:
                    pass
                isaac_p0_result = None
        # P0 regex fallback is slash-only and handled by explicit slash entry above.
        # Natural language mentioning I叔/艾萨克 stays on the normal LLM/native
        # tool loop so the model decides whether to call isaac_p0.
        setattr(msg, "isaac_p0_result", isaac_p0_result)
        if isaac_p0_result is not None and isaac_p0_result.handled:
            decision = engine.decide(msg)
            _log_decision_trace(msg, decision)
            store.record_message(msg, is_bot=False)
            sender = Sender(
                bot,
                store,
                cooldown,
                bot_uid=str(getattr(bot, "self_id", "")),
                dry_run=_is_dry_run_enabled(),
                config=cfg,
            )
            await sender.send(msg, decision, isaac_p0_result.reply, actual_tier="local")
            logger.info(
                f"yangyang plugin: isaac_p0 handled allowed={isaac_p0_result.allowed} "
                f"reason={isaac_p0_result.reason} task_type={isaac_p0_result.task_type} "
                f"normal_prompt_bypassed=True memory_builder_skipped=True"
            )
            return

        decision = engine.decide(msg)
        _log_decision_trace(msg, decision)
        captured = False
        memory_observation = _collect_memory_observation(msg, decision, captured=captured)
        setattr(msg, "memory_observation", memory_observation)

        setattr(msg, "owner_action", owner_action)
        owner_action_context = None
        owner_action_gate = None
        owner_action_execution_plan = None
        owner_action_reply_draft = None
        if owner_action is not None:
            owner_action_context = resolve_owner_action_context(
                owner_action,
                msg,
                recent_messages=_build_recent_owner_action_messages(msg),
                store=store,
                config=cfg,
            )
            setattr(msg, "owner_action_context", owner_action_context)
            owner_action_gate = evaluate_owner_action_gate(owner_action, msg, cfg)
            setattr(msg, "owner_action_gate", owner_action_gate)
            owner_action_execution_plan = build_owner_action_execution_plan(owner_action, owner_action_gate, msg, cfg)
            setattr(msg, "owner_action_execution_plan", owner_action_execution_plan)
            logger.info(
                "yangyang plugin: parsed owner_action action=%s style=%s target_group=%s target_user=%s context_source=%s context_messages=%s context_reason=%s reason=%s dry_run=%s gate_mode=%s gate_allowed=%s gate_reason=%s exec_destination_type=%s exec_destination_id=%s exec_status=%s exec_real_send=%s exec_reason=%s",
                owner_action.action_type,
                owner_action.style,
                owner_action.target_group_id,
                owner_action.target_user_id,
                getattr(owner_action_context, "source", None),
                len(getattr(owner_action_context, "target_messages", None) or []),
                getattr(owner_action_context, "reason", None),
                owner_action.reason,
                _is_dry_run_enabled(),
                owner_action_gate.mode,
                owner_action_gate.allowed,
                owner_action_gate.reason,
                owner_action_execution_plan.destination_type,
                owner_action_execution_plan.destination_id,
                owner_action_execution_plan.status,
                owner_action_execution_plan.real_send,
                owner_action_execution_plan.reason,
            )

        history = []
        if msg.channel == "group":
            history = store.get_recent_messages(msg.group_id, limit=12, channel="group")
        elif msg.channel == "private":
            # Owner-private native tool loop needs recent dialogue turns for multi-turn
            # parameter completion (e.g. "补一句 X" -> "文件是 Y").
            # This is conversational context, not long-term memory promotion.
            history = store.get_recent_messages("", limit=12, channel="private")

        current_session_smoke_trigger_result = None
        if smoke_trigger_matched:
            setattr(msg, "_current_session_smoke_recent_messages", history)
            current_session_smoke_trigger_result = await handle_current_session_smoke_trigger_if_matched(
                msg,
                cfg,
                bot=bot,
                event=event,
                dry_run=_is_dry_run_enabled(),
                config=cfg,
            )
            setattr(msg, "current_session_smoke_trigger_result", current_session_smoke_trigger_result)
            if not decision.should_reply:
                store.record_message(msg, is_bot=False)
                return

        # 静默消息也要入库，保证后续上下文闭环。
        if not decision.should_reply:
            setattr(msg, "memory_observation", memory_observation)
            store.record_message(msg, is_bot=False)
            return

        # bot loop 防护：只拦普通群聊链路，不拦私聊 / @bot / owner 强制响应。
        if _should_block_by_bot_loop(msg, decision, str(getattr(bot, "self_id", ""))):
            store.record_message(msg, is_bot=False)
            logger.info(f"yangyang plugin: blocked by bot loop guard group={msg.group_id} uid={msg.uid}")
            return

        if not cooldown.can_reply(msg.group_id, topic_hint="", is_forced=decision.is_forced):
            store.record_message(msg, is_bot=False)
            return

        # 先取历史，再记录当前消息，避免 PromptBuilder 里当前消息重复出现。
        store.record_message(msg, is_bot=False)

        session_id = _get_session_id(msg)
        explicit_memory_result = await handle_explicit_memory_message_async(
            msg,
            store,
            session_id=session_id,
            config=_runtime_config_mapping_for_explicit_memory(cfg),
            router=router,
        )
        setattr(msg, "explicit_memory_result", explicit_memory_result)
        if explicit_memory_result.handled:
            logger.info(
                f"yangyang plugin: explicit_memory handled action={explicit_memory_result.action} "
                f"entry_id={explicit_memory_result.entry_id} uid={msg.uid} session_id={session_id}"
            )
            sender = Sender(
                bot,
                store,
                cooldown,
                bot_uid=str(getattr(bot, "self_id", "")),
                dry_run=_is_dry_run_enabled(),
                config=cfg,
            )
            await sender.send(msg, decision, explicit_memory_result.reply, actual_tier="local")
            return

        builder.memory_enabled = _memory_injection_enabled_for_message(msg)
        if str(getattr(msg, "channel", "") or "") == "private" and bool(getattr(msg, "is_owner", False)):
            logger.info(
                f"yangyang plugin: memory_injection_gate "
                f"uid={str(getattr(msg, 'uid', '') or '')} "
                f"session_id={session_id} "
                f"channel={str(getattr(msg, 'channel', '') or '')} "
                f"is_owner={bool(getattr(msg, 'is_owner', False))} "
                f"target_uid={str(getattr(decision, 'target_uid', '') or '')} "
                f"total_enabled={cfg.get_bool('memory_prompt_injection_enabled', False)} "
                f"private_enabled={cfg.get_bool('memory_prompt_injection_private_enabled', True)} "
                f"builder_enabled={bool(getattr(builder, 'memory_enabled', False))} "
                f"store_retrieval_enabled={bool(getattr(store, 'retrieval_enabled', False))} "
                f"store_private_only={bool(getattr(store, 'retrieval_private_only', False))}"
            )
        messages = builder.build_messages(msg, decision, history, session_id=session_id)
        memory_observation = _collect_memory_observation(msg, decision, captured=captured, session_id=session_id, messages=messages)
        setattr(msg, "memory_observation", memory_observation)
        owner_toolbox_light_llm_result = None
        local_model_reply = _handle_local_model_command(msg)
        if local_model_reply is not None:
            response, actual_tier = local_model_reply, 'local_model_command'
        elif str(getattr(msg, "channel", "") or "") == "private" and bool(getattr(msg, "is_owner", False)) and cfg.get_bool("owner_toolbox_light_native_loop_enabled", True):
            def _owner_toolbox_executor(name, args):
                context_channel = str(getattr(msg, "channel", "") or "private")
                argmap = dict(args or {}) if isinstance(args, dict) else args
                if isinstance(argmap, dict):
                    argmap.setdefault("_context_channel", context_channel)
                    argmap.setdefault("_session_id", session_id)
                if str(name or "").strip() == "test_model_profile":
                    return execute_owner_toolbox_tool_async(
                        name,
                        argmap,
                        cfg,
                        project_root=PROJECT_ROOT,
                        model_router=router,
                        context_channel=context_channel,
                    )
                return execute_owner_toolbox_tool(name, argmap, cfg, project_root=PROJECT_ROOT)

            progress_run_id = f"owner-{int(time.time() * 1000)}"

            prelude_sent_texts = set()
            owner_progress_sender = NoneBotCurrentSessionSenderAdapter(bot=bot, event=event, config=cfg)

            async def _push_owner_toolbox_progress_text(push_text, *, log_context):
                value = str(push_text or "").strip()
                if not value:
                    return
                result = await owner_progress_sender.send_current_session(msg, value)
                if not bool(getattr(result, "delivered", False)):
                    logger.warning(
                        "yangyang plugin: owner toolbox progress push not delivered context=%s mode=%s reason=%s",
                        log_context,
                        getattr(result, "mode", ""),
                        getattr(result, "reason", ""),
                    )

            def _sanitize_owner_toolbox_prelude(text):
                value = str(text or "").strip()
                if not value:
                    return ""
                # Keep only a short natural line.  Tool names/JSON belong to audit, not QQ.
                value = value.replace("\r", "\n")
                lines = [line.strip() for line in value.splitlines() if line.strip()]
                value = " ".join(lines[:2]).strip()
                value = re.sub(r"^\s*(?:秧秧|娅娅|达妮娅|assistant|Assistant|AI|ai)\s*[：:]\s*", "", value).strip()
                lowered = value.lower()
                bad_markers = ("tool_call", "tool_calls", "tool_name", "raw_trace", "executor raw", "{", "}", "```")
                if any(marker in lowered for marker in bad_markers):
                    return ""
                if len(value) > 80:
                    value = value[:77].rstrip() + "..."
                return value

            async def _owner_toolbox_progress(event_name, payload):
                payload = dict(payload or {})
                payload.setdefault("run_id", progress_run_id)
                if event_name == "assistant_prelude":
                    audit_payload = sanitize_mapping({k: v for k, v in payload.items() if k != "text"})
                    audit_payload["text_summary"] = str(payload.get("text") or "")[:120]
                    append_progress_audit(cfg, event_name, audit_payload, project_root=PROJECT_ROOT)
                    if not cfg.get_bool("owner_toolbox_assistant_prelude_push_enabled", True):
                        return
                    prelude_text = _sanitize_owner_toolbox_prelude(payload.get("text", ""))
                    if not prelude_text or prelude_text in prelude_sent_texts:
                        return
                    prelude_sent_texts.add(prelude_text)
                    try:
                        await _push_owner_toolbox_progress_text(prelude_text, log_context='assistant_prelude')
                    except Exception:
                        logger.exception("yangyang plugin: owner toolbox assistant prelude push failed")
                    return
                if event_name in {"tool_done"}:
                    payload["result_summary"] = summarize_tool_result(payload.pop("result", ""))
                else:
                    payload = sanitize_mapping(payload)
                append_progress_audit(cfg, event_name, payload, project_root=PROJECT_ROOT)
                if not cfg.get_bool("owner_toolbox_progress_push_enabled", True):
                    return
                # Keep private progress compact; full detail stays in JSONL audit.
                configured_events = cfg.get("owner_toolbox_progress_push_events", ["llm_response", "tool_error", "max_steps_hit", "run_done"])
                allowed_events = {str(x) for x in configured_events} if isinstance(configured_events, list) else {"llm_response", "tool_error", "max_steps_hit", "run_done"}
                if event_name not in allowed_events:
                    return
                if event_name == "llm_response" and int(payload.get("tool_call_count") or 0) <= 0:
                    return
                if event_name == "run_done" and int(payload.get("trace_len") or 0) <= 0:
                    return
                try:
                    fallback_text = format_compact_progress_message(event_name, payload) if cfg.get_bool("owner_toolbox_progress_push_compact", True) else format_progress_message(event_name, payload)
                    progress_text = fallback_text
                    if cfg.get_bool("owner_toolbox_progress_llm_enabled", True) and event_name in {"llm_response", "run_done", "max_steps_hit"}:
                        try:
                            progress_raw, _progress_tier = await asyncio.wait_for(
                                router.call(
                                    str(cfg.get("owner_toolbox_progress_llm_tier", "v4_flash") or "v4_flash"),
                                    build_progress_llm_messages(event_name, payload, user_text=getattr(msg, "text", "") or getattr(msg, "raw_content", "")),
                                    temperature=0.25,
                                    session_id=f"{session_id}:progress",
                                    tools=None,
                                    tool_choice="none",
                                    channel=str(getattr(msg, "channel", "") or ""),
                                    timeout_bucket="progress",
                                    interaction_phase="progress_update",
                                    allow_streaming=False,
                                ),
                                timeout=max(1, int(cfg.get("owner_toolbox_progress_llm_timeout_seconds", 8) or 8)),
                            )
                            progress_text = sanitize_progress_llm_text(progress_raw, fallback=fallback_text)
                        except Exception:
                            logger.exception("yangyang plugin: owner toolbox progress llm failed event=%s", event_name)
                            progress_text = fallback_text
                    if not progress_text:
                        return
                    await _push_owner_toolbox_progress_text(progress_text, log_context=event_name)
                except Exception:
                    logger.exception("yangyang plugin: owner toolbox progress push failed event=%s", event_name)

            response, actual_tier, owner_tool_trace = await router.call_with_tool_loop(
                decision.model_tier or "v4_flash",
                prepare_owner_tool_loop_messages(messages),
                tools=build_owner_toolbox_tools(),
                tool_executor=_owner_toolbox_executor,
                temperature=0.2,
                session_id=session_id,
                tool_choice="auto",
                max_steps=_owner_tool_loop_max_steps(),
                channel=str(getattr(msg, "channel", "") or ""),
                progress_callback=_owner_toolbox_progress,
                run_id=progress_run_id,
                timeout_bucket="tool_followup",
                interaction_phase="tool_followup",
                allow_streaming=False,
            )
            response = coerce_owner_toolbox_human_reply(response, owner_tool_trace, user_text=str(getattr(msg, "text", "") or getattr(msg, "raw_content", "") or ""))
            owner_toolbox_light_llm_result = type("OwnerToolLoopObservation", (), {
                "handled": bool(owner_tool_trace),
                "allowed": True,
                "reason": "ok" if owner_tool_trace else "no_tool_call",
                "tool_name": (owner_tool_trace[-1].get("tool_name") if owner_tool_trace else None),
                "data": {"tier": actual_tier, "tool_call_count": len(owner_tool_trace)},
                "raw_trace": owner_tool_trace,
            })()
            setattr(msg, "owner_toolbox_light_llm_result", owner_toolbox_light_llm_result)
            if owner_tool_trace:
                trace_names = [str(item.get("tool_name") or "") for item in owner_tool_trace]
                trace_args = [item.get("args") for item in owner_tool_trace]
                logger.info(
                    f"yangyang plugin: owner_toolbox_light_llm handled "
                    f"tool={owner_toolbox_light_llm_result.tool_name} calls={len(owner_tool_trace)} "
                    f"reason={owner_toolbox_light_llm_result.reason} channel={getattr(msg, 'channel', '')} "
                    f"owner={getattr(msg, 'is_owner', False)} trace_names={trace_names} trace_args={trace_args}"
                )
        else:
            direct_stream_sender = NoneBotCurrentSessionSenderAdapter(bot=bot, event=event, config=cfg)
            stream_state = {
                "buffer": "",
                "sent_text": "",
                "enabled": str(getattr(msg, "channel", "") or "") == "private",
                "last_flush_ts": time.monotonic(),
            }
            min_stream_chars = 16
            eager_stream_chars = 32
            max_stream_idle_seconds = 0.45

            async def _flush_direct_stream_buffer(force: bool = False):
                if not stream_state["enabled"]:
                    stream_state["buffer"] = ""
                    return
                pending = str(stream_state["buffer"] or "")
                if not pending.strip():
                    stream_state["buffer"] = ""
                    return
                if (not force) and len(pending) < min_stream_chars and (not re.search(r"[。！？!?\n]$", pending)):
                    return
                stream_state["buffer"] = ""
                result = await direct_stream_sender.send_current_session(msg, pending)
                if bool(getattr(result, "delivered", False)):
                    stream_state["sent_text"] += pending
                stream_state["last_flush_ts"] = time.monotonic()

            async def _on_direct_stream_delta(delta_text, meta):
                delta = str(delta_text or "")
                if (not stream_state["enabled"]) or (not delta):
                    return
                stream_state["buffer"] += delta
                now = time.monotonic()
                if (
                    len(stream_state["buffer"]) >= eager_stream_chars
                    or re.search(r"[。！？!?\n]$", stream_state["buffer"])
                    or ((now - float(stream_state["last_flush_ts"])) >= max_stream_idle_seconds and len(stream_state["buffer"]) >= min_stream_chars)
                ):
                    await _flush_direct_stream_buffer(force=False)

            response, actual_tier = await router.call(
                decision.model_tier or "v4_flash",
                messages,
                session_id=session_id,
                channel=str(getattr(msg, "channel", "") or ""),
                timeout_bucket="normal",
                interaction_phase="direct_reply",
                allow_streaming=True,
                stream_callback=_on_direct_stream_delta,
            )
            await _flush_direct_stream_buffer(force=True)
            if stream_state["sent_text"]:
                setattr(msg, "_streaming_sent_text", stream_state["sent_text"])
        if getattr(router, "last_call_sensitive_failure", False):
            setattr(msg, "sensitive_failure", True)
            setattr(msg, "sensitive_failure_request_id", getattr(router, "last_call_request_id", ""))
            setattr(msg, "sensitive_failure_error_type", getattr(router, "last_call_error_type", ""))
            setattr(msg, "sensitive_failure_hash", getattr(router, "last_call_hash", ""))
            setattr(msg, "sensitive_failure_length", getattr(router, "last_call_messages_len", 0))
        captured = _capture_short_term_memory(msg)
        memory_observation = _collect_memory_observation(msg, decision, captured=captured, session_id=session_id, messages=messages)
        setattr(msg, "memory_observation", memory_observation)
        owner_action_delivery_result = None
        owner_action_delivery_integration_result = None
        owner_action_delivery_safety_result = None
        if owner_action_execution_plan is not None:
            owner_action_reply_draft = build_owner_action_reply_draft(
                owner_action,
                owner_action_execution_plan,
                response,
                msg,
                cfg,
            )
            setattr(msg, "owner_action_reply_draft", owner_action_reply_draft)
            logger.info(
                "yangyang plugin: owner_action_reply_draft destination_type=%s destination_id=%s status=%s length=%s real_send=%s reason=%s",
                owner_action_reply_draft.destination_type,
                owner_action_reply_draft.destination_id,
                owner_action_reply_draft.status,
                owner_action_reply_draft.content_length,
                owner_action_reply_draft.real_send,
                owner_action_reply_draft.reason,
            )
            # 当前会话真实投递集成入口：默认 explicit_enable=False，不接管生产，仅保留明确薄层注入点。
            # 若要做 owner 手动 smoke test，请显式调用 run_current_session_manual_smoke_if_enabled(...)
            # 并同时满足：manual_smoke_enabled + nonebot_sender_enabled + execution_enabled +
            # allow_reply_current + current_session_delivery_enabled + explicit_enable=True + bot/event 注入。
            owner_action_delivery_integration_result = await deliver_owner_action_current_session_if_enabled(
                owner_action_reply_draft,
                owner_action,
                owner_action_execution_plan,
                msg,
                cfg,
                bot=bot,
                event=event,
                explicit_enable=False,
                dry_run=_is_dry_run_enabled(),
                gate=owner_action_gate,
            )
            if smoke_trigger_matched:
                setattr(msg, "_current_session_smoke_model_reply", response)
                setattr(msg, "_current_session_smoke_recent_messages", history)
            setattr(msg, "owner_action_delivery_integration_result", owner_action_delivery_integration_result)
            owner_action_delivery_result = getattr(msg, "owner_action_delivery_result", None)
            owner_action_delivery_safety_result = getattr(msg, "owner_action_delivery_safety_result", None)
            if owner_action_delivery_result is not None:
                logger.info(
                    "yangyang plugin: owner_action_delivery_result mode=%s attempted=%s delivered=%s real_send=%s reason=%s",
                    owner_action_delivery_result.mode,
                    owner_action_delivery_result.attempted,
                    owner_action_delivery_result.delivered,
                    owner_action_delivery_result.real_send,
                    owner_action_delivery_result.reason,
                )
        if _is_dry_run_enabled() and owner_action is not None:
            action_summary = _format_owner_action_summary(owner_action)
            context_summary = format_owner_action_context_summary(owner_action_context)
            gate_summary = _format_owner_action_gate_summary(owner_action_gate)
            execution_plan_summary = _format_owner_action_execution_plan_summary(owner_action_execution_plan)
            reply_draft_summary = format_owner_action_reply_draft_summary(owner_action_reply_draft)
            delivery_summary = _format_owner_action_delivery_summary(owner_action_delivery_result)
            safety_summary = format_owner_action_delivery_safety_summary(owner_action_delivery_safety_result)
            if action_summary:
                logger.info(f"yangyang plugin: {action_summary}")
                response = f"{response}\n{action_summary}".strip()
            if context_summary:
                logger.info(f"yangyang plugin: {context_summary}")
                response = f"{response}\n{context_summary}".strip()
            if gate_summary:
                logger.info(f"yangyang plugin: {gate_summary}")
                response = f"{response}\n{gate_summary}".strip()
            if execution_plan_summary:
                logger.info(f"yangyang plugin: {execution_plan_summary}")
                response = f"{response}\n{execution_plan_summary}".strip()
            if reply_draft_summary:
                logger.info(f"yangyang plugin: {reply_draft_summary}")
                response = f"{response}\n{reply_draft_summary}".strip()
            if delivery_summary:
                logger.info(f"yangyang plugin: {delivery_summary}")
                response = f"{response}\n{delivery_summary}".strip()
            if safety_summary:
                logger.info(f"yangyang plugin: {safety_summary}")
                response = f"{response}\n{safety_summary}".strip()

        sender = Sender(
            bot,
            store,
            cooldown,
            bot_uid=str(getattr(bot, "self_id", "")),
            dry_run=_is_dry_run_enabled(),
        )
        await sender.send(msg, decision, response, actual_tier=actual_tier)
    except Exception:
        logger.exception("yangyang plugin: handle_message failed")
