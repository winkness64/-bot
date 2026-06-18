from __future__ import annotations

import json
from typing import Any, Mapping

from .types import OwnerToolboxLightResult


def _format_profile_list_reply(data: dict[str, Any]) -> str:
    profiles = data.get("profiles") if isinstance(data.get("profiles"), list) else []
    lines = [
        f"scope={data.get('scope')} private_active={data.get('private_active')} group_active={data.get('group_active')}"
    ]
    for item in profiles:
        if not isinstance(item, Mapping):
            continue
        marks: list[str] = []
        if item.get("private_active"):
            marks.append("private_active")
        if item.get("group_active"):
            marks.append("group_active")
        mark_text = f" [{' '.join(marks)}]" if marks else ""
        enabled = "enabled" if item.get("enabled") else "disabled"
        lines.append(f"- [{item.get('index')}] {item.get('profile_id')}: {enabled} provider={item.get('provider')} model={item.get('model')}{mark_text}")
    return "\n".join(lines)


def _format_active_profile_reply(data: dict[str, Any]) -> str:
    profile = data.get("profile") if isinstance(data.get("profile"), Mapping) else {}
    return (
        f"scope={data.get('scope')} active={data.get('profile_id')} "
        f"provider={profile.get('provider')} model={profile.get('model')} "
        f"private_active={data.get('private_active')} group_active={data.get('group_active')}"
    ).strip()


def _format_set_profile_reply(data: dict[str, Any]) -> str:
    if not data.get("ok"):
        return f"没切成：{data.get('reason')}。scope={data.get('scope')} private_active={data.get('private_active')} group_active={data.get('group_active')}"
    return f"已把 {data.get('scope')} 模型从 {data.get('previous')} 切到 {data.get('current')}。"


def _format_test_profile_reply(data: dict[str, Any]) -> str:
    profile = data.get("profile") if isinstance(data.get("profile"), Mapping) else {}
    status = "ok" if data.get("ok") else f"failed:{data.get('reason')}"
    return (
        f"test {status} profile={data.get('profile_id')} provider={profile.get('provider')} "
        f"model={profile.get('model')} fallback_used={data.get('fallback_used', False)}"
    ).strip()


def _format_refresh_profiles_reply(data: dict[str, Any]) -> str:
    refreshed = data.get("refreshed") if isinstance(data.get("refreshed"), list) else []
    failed = data.get("failed") if isinstance(data.get("failed"), list) else []
    created_count = 0
    updated_count = 0
    skipped_count = 0
    lines = [f"refresh {data.get('reason', 'unknown')} enable_discovered={data.get('enable_discovered', False)}"]
    for item in refreshed:
        if not isinstance(item, Mapping):
            continue
        created = item.get("created") if isinstance(item.get("created"), list) else []
        updated = item.get("updated") if isinstance(item.get("updated"), list) else []
        skipped = item.get("skipped") if isinstance(item.get("skipped"), list) else []
        created_count += len(created)
        updated_count += len(updated)
        skipped_count += len(skipped)
        lines.append(
            f"- provider_profile={item.get('provider_profile_id')} models_seen={item.get('models_seen')} "
            f"created={len(created)} updated={len(updated)} skipped={len(skipped)}"
        )
        for prof in (created + updated)[:12]:
            if isinstance(prof, Mapping):
                state = "enabled" if prof.get("enabled") else "disabled"
                lines.append(f"  · {prof.get('profile_id')} model={prof.get('model')} {state}")
    if failed:
        lines.append(f"failed={len(failed)}")
        for item in failed[:8]:
            if isinstance(item, Mapping):
                lines.append(f"  · {item.get('provider_profile_id')}: {item.get('reason')}")
    lines.append(f"total created={created_count} updated={updated_count} skipped={skipped_count}")
    return "\n".join(lines)


def format_owner_toolbox_reply(result: OwnerToolboxLightResult, *, raw: bool = False, user_text: str = "") -> str:
    """Format an already-produced toolbox reply without front-end NL templates.

    Native tool loop replies must be model-authored.  This helper is only a
    thin compatibility shim for old explicit slash paths and raw/debug output;
    it deliberately does not branch on tool names to synthesize natural text.
    """
    if raw:
        return format_owner_toolbox_raw_details(result)
    return str(result.reply or result.output or "").strip()


def format_owner_toolbox_raw_details(result: OwnerToolboxLightResult) -> str:
    payload = {
        "handled": result.handled,
        "allowed": result.allowed,
        "reason": result.reason,
        "tool_name": result.tool_name,
        "reply": result.reply,
        "output": result.output,
        "data": result.data,
        "raw_trace": result.raw_trace or [],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)



def _format_enable_profile_reply(data: Mapping[str, Any]) -> str:
    if not data.get("ok"):
        return f"模型启用状态修改失败：{data.get('reason') or 'error'}。"
    profile = data.get("profile") if isinstance(data.get("profile"), Mapping) else {}
    pid = str(data.get("profile_id") or profile.get("profile_id") or "")
    model = str(profile.get("model") or "")
    enabled = bool(data.get("enabled"))
    state = "启用" if enabled else "禁用"
    prev = data.get("previous_enabled")
    prev_state = "启用" if bool(prev) else "禁用"
    if prev is None or bool(prev) == enabled:
        return f"{pid}（{model}）已保持{state}。"
    return f"{pid}（{model}）已从{prev_state}改为{state}。"
