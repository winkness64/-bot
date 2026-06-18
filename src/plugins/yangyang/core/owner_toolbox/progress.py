from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

SENSITIVE_KEY_MARKERS = ("key", "token", "secret", "password", "passwd", "base_url", "api")
# owner_toolbox/progress.py -> owner_toolbox -> core -> yangyang -> plugins -> src -> <project_root>
PROJECT_ROOT = Path(__file__).resolve().parents[5]


def _cfg_get(config: Any, path: str, default: Any = None) -> Any:
    try:
        if config is not None and hasattr(config, "get"):
            value = config.get(path, default)
            return default if value is None else value
    except Exception:
        return default
    if isinstance(config, dict):
        cur: Any = config
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur
    return default


def _cfg_bool(config: Any, path: str, default: bool = False) -> bool:
    try:
        if config is not None and hasattr(config, "get_bool"):
            return bool(config.get_bool(path, default))
    except Exception:
        pass
    value = _cfg_get(config, path, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def resolve_progress_audit_path(config: Any = None, *, project_root: str | Path | None = None) -> Path:
    raw = str(_cfg_get(config, "owner_toolbox_native_audit_path", "logs/owner_toolbox_native_audit.jsonl") or "logs/owner_toolbox_native_audit.jsonl")
    path = Path(raw)
    if not path.is_absolute():
        root = Path(project_root).resolve() if project_root is not None else PROJECT_ROOT
        path = root / path
    return path


def _short_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:12]


def _summarize_value(key: str, value: Any) -> Any:
    lowered = str(key or "").lower()
    if any(marker in lowered for marker in SENSITIVE_KEY_MARKERS):
        return "<redacted>"
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [ _summarize_value(key, item) for item in list(value)[:6] ]
    if isinstance(value, dict):
        return sanitize_mapping(value)
    text = str(value)
    if len(text) <= 120 and "\n" not in text:
        # Avoid broadcasting sensitive absolute host layout in progress reports.
        if text.startswith("/"):
            return f"<path:{Path(text).name or '/'}>"
        return text
    return {"chars": len(text), "sha256_12": _short_hash(text)}


def sanitize_mapping(data: Mapping[str, Any] | dict[str, Any] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in dict(data or {}).items():
        skey = str(key)
        if skey.startswith("_context") or skey in {"_session_id"}:
            continue
        result[skey] = _summarize_value(skey, value)
    return result


def summarize_tool_result(content: Any) -> dict[str, Any]:
    raw = str(content or "")
    summary: dict[str, Any] = {"chars": len(raw)}
    try:
        payload = json.loads(raw)
    except Exception:
        if raw:
            summary["sha256_12"] = _short_hash(raw)
        return summary
    if not isinstance(payload, dict):
        return summary
    summary["allowed"] = payload.get("allowed")
    summary["reason"] = str(payload.get("reason") or "")[:120]
    summary["tool_name"] = str(payload.get("tool_name") or "")[:80]
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    if data:
        summary["data_keys"] = sorted(str(k) for k in data.keys())[:20]
    output = str(payload.get("output") or payload.get("reply") or "")
    if output:
        summary["output_chars"] = len(output)
        summary["output_sha256_12"] = _short_hash(output)
    return summary


def append_progress_audit(config: Any, event: str, payload: Mapping[str, Any] | dict[str, Any], *, project_root: str | Path | None = None) -> bool:
    if not _cfg_bool(config, "owner_toolbox_native_audit_enabled", True):
        return False
    path = resolve_progress_audit_path(config, project_root=project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "event": str(event or ""),
    }
    record.update(sanitize_mapping(dict(payload or {})))
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False, sort_keys=True, default=str) + "\n")
    return True


def format_progress_message(event: str, payload: Mapping[str, Any] | dict[str, Any]) -> str:
    data = dict(payload or {})
    step = data.get("step")
    tool = str(data.get("tool_name") or data.get("tool") or "").strip()
    run_id = str(data.get("run_id") or "")[-8:]
    suffix = f" #{run_id}" if run_id else ""
    if event == "run_start":
        return f"阶段开始{suffix}：我先判断这件事要不要调用工具。"
    if event == "llm_request_start":
        return f"阶段{step or ''}：正在让模型判断下一步。".replace("阶段：", "阶段：")
    if event == "llm_response":
        count = int(data.get("tool_call_count") or 0)
        if count > 0:
            names = data.get("tool_names") or []
            joined = "、".join(str(x) for x in names[:3]) if isinstance(names, list) else str(names)
            return f"阶段{step or ''}：模型决定调用 {count} 个工具" + (f"：{joined}" if joined else "") + "。"
        return f"阶段{step or ''}：模型没有继续要工具，准备汇总回复。"
    if event == "tool_start":
        return f"阶段{step or ''}：开始调用工具 {tool or 'unknown'}。"
    if event == "tool_done":
        ok = data.get("ok")
        status = "完成" if ok is not False else "失败"
        return f"阶段{step or ''}：工具 {tool or 'unknown'} {status}。"
    if event == "tool_error":
        return f"阶段{step or ''}：工具 {tool or 'unknown'} 报错，我会带着错误继续收口。"
    if event == "max_steps_hit":
        return "阶段提醒：工具调用步数到上限了，我开始基于已有结果收口。"
    if event == "run_done":
        return "阶段完成：工具链结束，我开始整理最终回复。"
    return "阶段更新：工具链状态有变化。"


_TOOL_CN = {
    "list": "看目录",
    "read": "读文件",
    "log_tail": "看日志",
    "python": "跑 Python 校验",
    "shell": "执行命令",
    "write": "修改文件",
    "pack": "打包",
    "query_token_usage": "查 token 用量",
    "list_model_profiles": "查模型列表",
    "get_active_model_profile": "查当前模型",
    "set_active_model_profile": "切模型",
    "set_model_profile_enabled": "启用/禁用模型",
    "test_model_profile": "测试模型",
    "refresh_model_profiles": "刷新模型列表",
}


def format_compact_progress_message(event: str, payload: Mapping[str, Any] | dict[str, Any]) -> str:
    data = dict(payload or {})
    step = data.get("step") or ""
    names = data.get("tool_names") or []
    if event == "llm_response":
        count = int(data.get("tool_call_count") or 0)
        if count <= 0:
            return ""
        if isinstance(names, list):
            cn = [_TOOL_CN.get(str(name), str(name)) for name in names if str(name).strip()]
        else:
            cn = [_TOOL_CN.get(str(names), str(names))]
        shown = "、".join(cn[:4])
        more = "等" if len(cn) > 4 else ""
        return f"我先跑第 {step} 轮工具：{shown}{more}。"
    if event == "max_steps_hit":
        return "工具步数到上限了，我先基于已有结果收口。"
    if event == "run_done":
        trace_len = int(data.get("trace_len") or 0)
        if trace_len <= 0:
            return ""
        return f"工具部分跑完了，共调用 {trace_len} 次，我现在整理结果。"
    if event == "tool_error":
        tool = str(data.get("tool_name") or data.get("tool") or "工具")
        return f"{_TOOL_CN.get(tool, tool)} 这一步报错了，我会带着错误继续处理。"
    return ""


_PROGRESS_LLM_SYSTEM_PROMPT = """你是秧秧的工程进度播报器，正在私聊告诉阿漂你现在准备怎么干活。
要求：
- 只输出一句自然中文，像真人边干边汇报。
- 不要输出 JSON、tool name、trace、run_id、英文事件名。
- 不要说“阶段1/阶段2”这种机器格式。
- 语气可以像：我先看目录和说明，确认要改哪；我准备读脚本和数据，先复现失败；我跑完工具了，开始整理结论。
- 不要假装已经完成没做过的事；只能根据给你的摘要说“准备/正在/已经跑完工具部分”。
"""


def build_progress_llm_messages(event: str, payload: Mapping[str, Any] | dict[str, Any], *, user_text: str = "") -> list[dict[str, str]]:
    data = dict(payload or {})
    names = data.get("tool_names") or []
    if isinstance(names, list):
        tasks = [_TOOL_CN.get(str(name), str(name)) for name in names if str(name).strip()]
    else:
        tasks = [_TOOL_CN.get(str(names), str(names))] if str(names).strip() else []
    summary = {
        "event": str(event or ""),
        "step": data.get("step"),
        "tool_call_count": data.get("tool_call_count"),
        "tasks": tasks[:8],
        "trace_len": data.get("trace_len"),
        "max_steps_hit": data.get("max_steps_hit"),
    }
    return [
        {"role": "system", "content": _PROGRESS_LLM_SYSTEM_PROMPT},
        {"role": "user", "content": "用户原始任务：" + str(user_text or "")[:500]},
        {"role": "user", "content": "进度摘要：" + json.dumps(summary, ensure_ascii=False, sort_keys=True, default=str)},
    ]


def sanitize_progress_llm_text(text: str, *, fallback: str = "") -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return fallback
    # keep it as one short progress line
    cleaned = " ".join(line.strip() for line in cleaned.splitlines() if line.strip())
    if len(cleaned) > 160:
        cleaned = cleaned[:157].rstrip() + "..."
    bad_markers = ("tool_call", "tool_calls", "tool_name", "raw_trace", "{", "}")
    if any(marker in cleaned for marker in bad_markers):
        return fallback or "我先按工具结果继续推进。"
    return cleaned
