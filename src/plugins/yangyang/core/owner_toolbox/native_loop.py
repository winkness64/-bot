from __future__ import annotations

import asyncio
import json
from pathlib import Path
import re
from typing import Any

from .config import TOOL_LOOP_MAX_STEPS_CONFIG_KEY, _config_get_bool, get_owner_tool_loop_max_steps, set_owner_tool_loop_max_steps
from .executor import execute_owner_toolbox_tool, execute_owner_toolbox_tool_async, handle_isaac_agent_bus_p0_message
from .formatters import format_owner_toolbox_reply, format_owner_toolbox_raw_details
from .parser import (
    _invocation_from_toolbox_text,
    _message_text,
    parse_natural_tool_invocation,
    parse_owner_tool_loop_max_steps_command,
    parse_slash_command,
    is_legacy_toolbox_prefix,
    _usage,
)
from .permissions import is_owner_private
from .results import _result
from .schemas import build_owner_toolbox_tools
from .types import OwnerToolboxLightResult
from .plan_only_gate import classify_owner_intent, CLARIFY_REPLY, plan_only_messages


def handle_owner_tool_loop_max_steps_message(message: Any, config: Any = None) -> OwnerToolboxLightResult:
    command = parse_owner_tool_loop_max_steps_command(message)
    if command is None:
        return _result(handled=False, allowed=False, reason="no_tool_loop_config_intent")
    if not is_owner_private(message, config):
        return _result(handled=False, allowed=False, reason="not_owner_private")

    if command.action == "query":
        steps = get_owner_tool_loop_max_steps(config)
        return _result(
            reason="ok",
            reply=f"当前工具 loop 调用上限是 {steps} 步。",
            tool_name="get_tool_loop_max_steps",
            data={"max_steps": steps, "config_key": TOOL_LOOP_MAX_STEPS_CONFIG_KEY},
        )

    ok, steps, key = set_owner_tool_loop_max_steps(config, command.value)
    if ok:
        return _result(
            reason="ok",
            reply=f"已把工具 loop 调用上限设为 {steps} 步，已写入 runtime_config。",
            tool_name="set_tool_loop_max_steps",
            data={"max_steps": steps, "config_key": key},
        )
    return _result(
        allowed=False,
        reason="config_write_failed",
        reply="没写成：runtime_config 写入失败。",
        tool_name="set_tool_loop_max_steps",
        data={"max_steps": steps, "config_key": key},
    )


def wants_owner_toolbox_raw_details(text_or_message: Any) -> bool:
    text = _message_text(text_or_message)
    if not text:
        return False
    lowered = text.lower()
    chinese_markers = ("原始", "调试", "工具细节", "工具详情")
    if any(marker in lowered for marker in chinese_markers):
        return True
    # ASCII markers must be explicit tokens.  Avoid treating words like
    # "draw" as a raw/debug request just because they contain "raw".
    return bool(re.search(r"(?<![a-z0-9_])(?:raw|debug|tool[_\s-]*trace|trace|stdout|stderr)(?![a-z0-9_])", lowered))


def _strip_raw_mode_markers(text: str) -> str:
    cleaned = str(text or "")
    for marker in ("原始", "调试", "工具细节", "工具详情"):
        cleaned = cleaned.replace(marker, " ")
    cleaned = re.sub(r"(?<![A-Za-z0-9_])(?:raw|debug|tool[_\s-]*trace|trace|stdout|stderr)(?![A-Za-z0-9_])", " ", cleaned, flags=re.I)
    return re.sub(r"\s+", " ", cleaned).strip()


def _owner_tool_loop_system_prompt() -> str:
    return (
        "你是I叔，正在和漂♂总私聊。回复必须像真人聊天，简短自然，但口吻要像工程硬汉。\n"
        "你可以按需使用工程工具；工具只是后台动作，不是前台嘴巴。\n"
        "如果你决定调用工具，且能自然地先回一句，就用一句简短中文告诉漂♂总你准备做什么；不要暴露工具名、JSON、阶段编号或参数。\n"
        "不要在回复开头写角色名前缀，例如‘I叔:’、‘I叔：’、‘Assistant:’；直接说正文。\n"
        "Owner Toolbox 没有前台自然语言模板：每次都根据用户原话、上下文和工具结果自由组织最终回复。\n"
        "工具结果会作为 tool message / structured result 回灌给你；拿到结果后由你判断下一步，"
        "可继续调用工具，也可直接给出最终回复。\n"
        "排障任务按 native tool loop 自主多步推进，不要假设固定流程；代码只提供可配置 max_steps 防循环。\n"
        "如果 owner 询问或要求调整工具 loop 的 max_steps、最大调用步数、工具调用上限，"
        "由你理解意图后调用 get_tool_loop_max_steps 或 set_tool_loop_max_steps(value)，不要要求 owner 背固定口令。\n"
        "只有读目录、读文件、看明确文件路径日志、打包、写文件、执行明确命令/代码等需求才调用工具；"
        "简单数学和普通聊天不要硬调工具。\n"
        "写文件/追加/修改前必须确认目标路径是具体文件：用户只说‘那个txt’、‘那个文件’、‘冷备份那个’、‘上次那个’等模糊说法时，"
        "先 list/read/shell 查候选并让 owner 确认，不许脑补成某个 txt 直接 write；用户明确给出文件名/路径（例如 xxx.txt 或 /path/xxx）时才可写。\n"
        "owner 说‘补一句/再补一句/补一行/追加一句/加一句/把这句话补上’时，通常是在要求写入文件，不许回复‘我在心里补上’；"
        "如果目标文件或要补的内容不明确，就简短追问，不能假装完成。\n"
        "owner 说‘等下/先别写/等我告诉你文件’这类预告时，不要调用 write，也不要说已经写好；"
        "用I叔自己的口吻自然确认即可，例如称呼漂♂总，说明先记住这句话、等他说文件再动手，不要套固定模板。\n"
        "如果你刚列出多个候选，owner 只回复‘1/2/第一个/第二个’，要当作选择候选处理；如果当前上下文拿不到候选，"
        "就问‘这个 1 是选哪个候选？’，不要当成普通闲聊。\n"
        "看 systemd 服务日志/服务状态时优先调用 shell 跑真实宿主命令："
        "journalctl -u <service> -n <N> --no-pager，或 systemctl status <service> --no-pager -l；"
        "journalctl/systemctl 不可用就返回真实错误，不能假装。log_tail 只用于用户明确给出日志文件路径。\n"
        "服务日志默认只总结 error/exception/traceback、最近异常和状态线索；不要把几十行原样贴出，除非用户明确要原文。\n"
        "不要因为重启、冷备、systemctl、密码、nonebot 等词自行拦截或触发工具；只看用户真实意图。\n"
        "当漂♂总在 owner 私聊自然提到 I叔/艾萨克 并要求只读诊断、health/status、workspace report、help 或 dry_run plan 时，"
        "可以调用 isaac_p0；裸自然语言是否调用由你判断，代码层只对 /i叔、/I叔、/艾萨克 做 slash 兜底。\n"
        "默认最终回复只输出自然语言 content；不要展示 tool_call、JSON、tool name、args、stdout/stderr、executor raw 日志。\n"
        "向漂♂总报告文件位置时，必须以工具结果里的 abs_path/abs_output 为准；不要根据默认 cwd 或自己猜测编路径。\n"
        "如果漂♂总问‘脚本目录/文件路径/项目根路径/项目根目录/目录在哪/项目在哪/发我路径/目录发我’，必须先调用 list/read/shell 等工具查真实宿主路径；"
        "没有工具结果时不许报任何绝对路径，也不许从记忆或上下文里编 /home、/opt、/root、/Users 之类路径。\n"
        "如果漂♂总在私聊问‘当前模型/现在什么模型/你现在用什么模型/fallback/回退模型/回退链/后备模型’，不要凭感觉口胡；"
        "优先调用 get_model_runtime_chain(scope) 一次拿当前主模型与 fallback 链；只有这个工具拿不到时，才退回 get_active_model_profile(scope) 或 list_model_profiles(scope, include_disabled=true)。"
        "若本轮工具结果拿不到 fallback 链，就明确说‘我先查到当前主模型，fallback 链这轮没有直接状态，得继续查配置’，不要编造诸如 GPT-4o 一类笼统名称。\n"
        "群聊里若被问当前模型或 fallback，不主动暴露 profile_id、provider、api_registry、base_url、env 名；默认用模糊安全口径简短带过，除非漂♂总明确要求公开说。\n"
        "写入/创建文件后的最终汇报，尽量附上工具返回的真实 abs_path，方便漂♂总之后查找。\n"
        "只有用户明确要求 raw/debug/tool trace/stdout/stderr 时，才允许展示受控调试细节。"
    )


def _extract_systemd_service_name(text: str) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if not compact:
        return ""
    candidates = re.findall(r"(?<![/\w.-])([A-Za-z0-9_.@-]+(?:\.service)?)(?![/\w.-])", compact)
    for item in candidates:
        lowered = item.lower()
        if lowered in {"systemd", "systemctl", "journalctl", "status", "error", "exception", "traceback", "log", "logs"}:
            continue
        if lowered.endswith(".service") or "nonebot" in lowered or "yangyang" in lowered or "-" in lowered:
            return item
    return ""


def _owner_tool_loop_systemd_hint(text: str) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if not compact:
        return ""
    lowered = compact.lower()
    asks_logs_or_status = any(token in lowered for token in ("log", "logs", "status", "error", "exception", "traceback")) or any(
        token in compact for token in ("日志", "状态", "报错", "错误", "异常")
    )
    if not asks_logs_or_status:
        return ""
    service = _extract_systemd_service_name(compact)
    has_systemd_marker = any(token in lowered for token in ("systemd", "systemctl", "journalctl")) or "服务" in compact
    if not service and not has_systemd_marker:
        return ""
    line_match = re.search(r"最近\s*(\d{1,4})\s*(?:行|lines?)", compact, flags=re.I)
    lines = int(line_match.group(1)) if line_match else 50
    lines = max(1, min(1000, lines))
    service_name = service or "<service>"
    return (
        "本条 owner 请求命中 systemd 服务日志/状态意图。优先调用 shell 执行真实命令："
        f"日志用 `journalctl -u {service_name} -n {lines} --no-pager`；"
        f"状态用 `systemctl status {service_name} --no-pager -l`；"
        "若要筛 error/exception/traceback，可在 journalctl 输出后用 grep/模型总结。"
        "不要把服务名当文件路径交给 log_tail；log_tail 只适用于明确日志文件路径。"
        "最终回复做摘要，不要原样贴满日志，除非 owner 明确要原文。"
    )




def _is_model_profile_list_request(user_text: str) -> bool:
    text = str(user_text or "").strip().lower()
    if not text:
        return False
    model_markers = (
        "模型列表", "模型清单", "有哪些模型", "有几个模型", "显示模型", "列出模型",
        "可用模型", "启用模型", "能用的模型", "可切模型", "可选模型", "现在能用",
        "model list", "models",
    )
    refresh_markers = ("刷新", "拉取", "更新", "refresh")
    if any(marker in text for marker in refresh_markers):
        return False
    return any(marker in text for marker in model_markers)


def _wants_enabled_only_model_profile_list(user_text: str) -> bool:
    text = str(user_text or "").strip().lower()
    enabled_only_markers = ("可用模型", "启用模型", "能用的模型", "可切模型", "可选模型", "现在能用", "enabled models", "available models")
    return any(marker in text for marker in enabled_only_markers)


def _wants_full_model_profile_list(user_text: str) -> bool:
    text = str(user_text or "").strip().lower()
    if _wants_enabled_only_model_profile_list(text):
        return False
    full_markers = (
        "全量", "全部", "所有", "完整", "禁用", "disabled", "include_disabled",
        "完整列表", "全列表", "把禁用也列", "禁用也列",
    )
    return any(marker in text for marker in full_markers)


def _tool_payload_from_trace_item(item: dict[str, Any]) -> dict[str, Any]:
    result_text = str(item.get("result") or "")
    try:
        parsed = json.loads(result_text)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        return {}


def _trace_model_profile_list_data(trace: list[dict[str, Any]] | None) -> dict[str, Any]:
    for item in reversed(trace or []):
        if not isinstance(item, dict):
            continue
        if str(item.get("tool_name") or "") != "list_model_profiles":
            continue
        payload = _tool_payload_from_trace_item(item)
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        profiles = data.get("profiles") if isinstance(data.get("profiles"), list) else []
        if profiles:
            return data
    return {}


def _format_model_profile_list_from_trace(data: dict[str, Any], *, user_text: str = "") -> str:
    raw_profiles = data.get("profiles") if isinstance(data.get("profiles"), list) else []
    if not raw_profiles:
        return "我没拿到模型列表结果。"
    enabled_only = _wants_enabled_only_model_profile_list(user_text)
    profiles = [
        item for item in raw_profiles
        if isinstance(item, dict) and (not enabled_only or bool(item.get("enabled")))
    ]
    if not profiles:
        return "当前没有启用中的模型。" if enabled_only else "我没拿到模型列表结果。"
    total = len(profiles)
    enabled_count = sum(1 for item in profiles if isinstance(item, dict) and bool(item.get("enabled")))
    disabled_count = total - enabled_count
    wants_full = (not enabled_only) and (_wants_full_model_profile_list(user_text) or total <= 20)
    show_limit = total if wants_full or enabled_only else min(total, 20)
    summary_word = "可用模型" if enabled_only else "模型列表"
    lines = [
        f"漂♂总，真实{summary_word}我从工具结果里拿到了：共 {total} 个，启用 {enabled_count} 个，禁用 {disabled_count} 个。",
    ]
    private_active = str(data.get("private_active") or "")
    group_active = str(data.get("group_active") or "")
    if private_active or group_active:
        lines.append(f"私聊活跃：`{private_active or '-'}`；群聊活跃：`{group_active or '-'}`。")
    lines.append("")
    lines.append("| # | ID | 模型 | 状态 |")
    lines.append("|---|-----|------|------|")
    for item in profiles[:show_limit]:
        if not isinstance(item, dict):
            continue
        idx = item.get("index")
        pid = str(item.get("profile_id") or "")
        model = str(item.get("model") or "")
        enabled = bool(item.get("enabled"))
        badges = []
        if item.get("private_active"):
            badges.append("私聊活跃")
        if item.get("group_active"):
            badges.append("群聊活跃")
        state = "启用" if enabled else "禁用"
        if badges:
            state += "（" + "+".join(badges) + "）"
        lines.append(f"| {idx} | `{pid}` | {model} | {state} |")
    remaining = total - show_limit
    if remaining > 0:
        lines.append("")
        lines.append(f"还有 {remaining} 个未展示；要看完整列表就说“全量模型列表”。")
    return "\n".join(lines)


def _write_target_is_ambiguous(user_text: str, tool_name: str, args: Any) -> bool:
    """Block same-turn writes when owner used vague file references.

    This is a mouth guard for the LLM, not a filesystem permission limit: an
    explicit path/filename still writes normally, but phrases like “那个txt”
    must be resolved and confirmed before mutation.
    """
    if str(tool_name or "").strip() != "write":
        return False
    text = str(user_text or "").strip()
    if not text:
        return False
    ambiguous_markers = (
        "那个txt", "那个 txt", "那个TXT", "那个 TXT",
        "那个文件", "那个文档", "那个文本", "那个记事本",
        "冷备份那个", "冷备那个", "备份那个",
        "上次那个", "刚才那个", "之前那个", "那个里面",
    )
    if not any(marker in text for marker in ambiguous_markers):
        return False
    # Explicit filename/path in the owner request means the target is concrete.
    if re.search(r"[^\s，。；;：:]+\.(?:txt|md|json|jsonl|py|log|yaml|yml|toml|ini|conf)\b", text, flags=re.I):
        return False
    if re.search(r"(?:^|[\s，。；;：:])(?:/|\./|\.\./|~)[^\s，。；;]+", text):
        return False
    return True


def _is_deferred_write_request(user_text: str) -> bool:
    text = str(user_text or "").strip()
    if not text:
        return False
    deferred_markers = ("先别写", "先不要写", "等我告诉你文件", "等我告诉你路径", "等下", "待会", "先别动")
    write_intent_markers = (
        "写", "写入", "追加", "加一行", "加一句", "补一句", "补一行", "再补", "补上", "保存",
    )
    return any(marker in text for marker in deferred_markers) and any(marker in text for marker in write_intent_markers)


def _deferred_write_ack_reply(user_text: str) -> str:
    text = str(user_text or "").strip()
    m = re.search(r'[“"]([^”"]{1,200})[”"]', text)
    content = m.group(1).strip() if m else ""
    if not content:
        # Common form: “我等下要补一句 测试上下文接力”
        m2 = re.search(r'(?:补一句|补一行|加一句|加一行|追加一句)\s*([^，。；;\n]{1,200})', text)
        content = m2.group(1).strip() if m2 else ""
    if content:
        return f"好，我先不写。待补内容是「{content}」，等漂♂总告诉我具体文件。"
    return "好，我先不写。等漂♂总告诉我具体文件和内容后再动手。"



def _owner_tool_loop_path_hint(text: str) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if not compact:
        return ""
    path_markers = ("脚本目录", "文件目录", "文件路径", "项目根路径", "项目根目录", "项目在哪", "路径", "目录发我", "路径发我", "在哪", "哪里", "发我")
    if not any(marker in compact for marker in path_markers):
        return ""
    fileish = re.findall(r"[^\s，。；;：:]+\.(?:txt|md|json|jsonl|py|log|yaml|yml|toml|ini|conf|tar\.gz)\b", compact, flags=re.I)
    filename_hint = f" 当前消息明确提到的文件名候选：{', '.join(fileish)}。" if fileish else " 如果当前消息没给文件名，要结合最近上下文里的文件名/脚本名后再查；拿不准就先问。"
    return (
        "本条 owner 请求是在询问文件/脚本的真实路径或目录。必须调用工具确认真实宿主路径，"
        "优先用 list/read/shell(find/stat/pwd) 获取 abs_path；没有工具结果时禁止直接报 /home、/opt、/root、/Users 等绝对路径。"
        f"{filename_hint} 最终回复用工具结果里的 abs_path/abs_output。"
    )

def _owner_tool_loop_messages(text: str) -> list[dict[str, Any]]:
    messages = [{"role": "system", "content": _owner_tool_loop_system_prompt()}]
    hint = _owner_tool_loop_systemd_hint(text)
    if hint:
        messages.append({"role": "system", "content": hint})
    path_hint = _owner_tool_loop_path_hint(text)
    if path_hint:
        messages.append({"role": "system", "content": path_hint})
    messages.append({"role": "user", "content": str(text or "")})
    return messages


def prepare_owner_tool_loop_messages(messages_or_text: Any) -> list[dict[str, Any]]:
    """Attach Owner Toolbox native-tool instructions to normal PromptBuilder messages."""
    if isinstance(messages_or_text, str):
        return _owner_tool_loop_messages(messages_or_text)
    prepared: list[dict[str, Any]] = [{"role": "system", "content": _owner_tool_loop_system_prompt()}]
    last_user_text = ""
    for item in messages_or_text or []:
        if isinstance(item, dict):
            if str(item.get("role") or "") == "user":
                last_user_text = str(item.get("content") or "")
            prepared.append(dict(item))
    hint = _owner_tool_loop_systemd_hint(last_user_text)
    if hint:
        prepared.insert(1, {"role": "system", "content": hint})
    path_hint = _owner_tool_loop_path_hint(last_user_text)
    if path_hint:
        insert_at = 2 if hint else 1
        prepared.insert(insert_at, {"role": "system", "content": path_hint})
    return prepared


def coerce_owner_toolbox_human_reply(text: str, trace: list[dict[str, Any]], *, user_text: str = "") -> str:
    return _model_final_content(text, trace=trace, user_text=user_text)


def _looks_like_frontend_tool_payload(text: str) -> bool:
    stripped = str(text or "").strip()
    if not stripped:
        return False
    if stripped.startswith(('{', '[')) and any(token in stripped for token in ('"tool_calls"', '"tool_call"', '"tool_name"', '"args"', '"raw_trace"')):
        return True
    lowered = stripped.lower()
    return any(token in lowered for token in ('tool_call', 'tool calls', 'tool_name', 'raw_trace', 'executor raw'))


def _fallback_human_reply_from_trace(trace: list[dict[str, Any]], *, user_text: str = "") -> str:
    if not trace:
        return "处理完了。"
    last = trace[-1] if isinstance(trace[-1], dict) else {}
    name = str(last.get("tool_name") or "").strip()
    args = last.get("args") if isinstance(last.get("args"), dict) else {}
    result_text = str(last.get("result") or "")
    payload: dict[str, Any] = {}
    try:
        parsed = json.loads(result_text)
        if isinstance(parsed, dict):
            payload = parsed
    except Exception:
        payload = {}
    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    allowed = payload.get("allowed", True)
    reason = str(payload.get("reason") or "")
    if allowed is False:
        return f"没处理成：{reason or '工具执行失败'}。"
    if name == "list":
        rel = str(data.get("abs_path") or args.get("path") or data.get("path") or ".")
        entries = data.get("entries") if isinstance(data.get("entries"), list) else []
        if not entries:
            return f"{rel} 目录是空的。"
        names = []
        for item in entries[:8]:
            if isinstance(item, dict):
                names.append(str(item.get("name") or item.get("path") or "").strip())
            else:
                names.append(str(item).strip())
        names = [item for item in names if item]
        suffix = " 等" if len(entries) > len(names) else ""
        return f"{rel} 目录里有：{', '.join(names)}{suffix}。" if names else f"{rel} 目录有内容。"
    if name in {"read", "log_tail"}:
        rel = str(data.get("abs_path") or args.get("path") or data.get("path") or "目标文件")
        output = str(payload.get("output") or payload.get("reply") or "").strip()
        if output:
            head = "\n".join(output.splitlines()[:8])
            return f"看过 {rel} 了，主要内容是：\n{head}"
        return f"看过 {rel} 了。"
    if name == "python":
        output = str(payload.get("output") or payload.get("reply") or "").strip()
        output = output.replace("stdout=", "").replace("stderr=", "").strip()
        return output or "算完了。"
    if name == "shell":
        return str(payload.get("reply") or "命令执行完了。").strip()
    if name == "write":
        return str(payload.get("reply") or "写完了。").strip()
    if name == "pack":
        return str(payload.get("reply") or "打包完了。").strip()
    if name == "get_tool_loop_max_steps":
        steps = data.get("max_steps")
        return f"当前工具 loop 调用上限是 {steps} 步。" if steps is not None else "查完了。"
    if name == "set_tool_loop_max_steps":
        steps = data.get("max_steps")
        return f"已把工具 loop 调用上限设为 {steps} 步。" if steps is not None else "设置完了。"
    if name == "query_token_usage":
        return str(payload.get("reply") or payload.get("output") or "Token 用量查完了。").strip()
    if name in {"list_model_profiles", "get_active_model_profile", "set_active_model_profile", "test_model_profile"}:
        return str(payload.get("reply") or payload.get("output") or "处理完了。").strip()
    return str(payload.get("reply") or "处理完了。").strip()


def _write_like_request_requires_successful_mutation(user_text: str) -> bool:
    text = str(user_text or "").strip()
    if not text:
        return False
    deferred_markers = ("先别写", "先不要写", "别写", "不要写", "等我告诉你文件", "等我告诉你路径", "等下", "待会", "先别动")
    if any(marker in text for marker in deferred_markers):
        return False
    # This is not a permission/safety keyword gate.  It only prevents the
    # model from claiming a filesystem mutation succeeded when no mutating
    # tool actually succeeded in the trace.
    write_verbs = (
        "写", "写入", "追加", "加一行", "加一句", "加上", "添加", "修改", "改一下",
        "补一句", "补一行", "补上", "再补", "追加一句", "把这句话补上",
        "删", "删除", "创建", "新建", "保存",
    )
    file_hints = (
        "文件", "目录", "txt", "TXT", ".txt", ".md", ".json", ".jsonl", ".py",
        "冷备份", "备份", "里面", "这个TXT", "这个txt", "这句话",
    )
    return any(verb in text for verb in write_verbs) and any(hint in text for hint in file_hints)


def _trace_has_successful_mutation(trace: list[dict[str, Any]] | None) -> bool:
    if not trace:
        return False
    mutating_tools = {"write", "shell", "python", "pack"}
    for item in trace:
        if not isinstance(item, dict):
            continue
        name = str(item.get("tool_name") or "").strip()
        if name not in mutating_tools:
            continue
        result_text = str(item.get("result") or "")
        payload: dict[str, Any] = {}
        try:
            parsed = json.loads(result_text)
            if isinstance(parsed, dict):
                payload = parsed
        except Exception:
            payload = {}
        if payload.get("allowed", True) is not False and str(payload.get("reason") or "ok") == "ok":
            return True
    return False


def _missing_mutation_reply(user_text: str) -> str:
    text = str(user_text or "").strip()
    if re.fullmatch(r"\s*(?:第?\d+|[一二三四五六七八九十]+|第[一二三四五六七八九十]+个)\s*", text):
        return "这个编号我没法可靠对应到候选。漂♂总把要选的文件路径或候选名称再说一遍，我再继续。"
    return "我没看到写入工具成功结果，所以不能说已经写进去了。漂♂总给我明确文件路径和要追加的内容，我再实际调用 write/shell 去写。"




def _looks_like_write_completion_claim(text: str) -> bool:
    compact = str(text or "").strip()
    if not compact:
        return False
    done_markers = ("写好了", "补好了", "补好啦", "加好了", "搞定", "完成", "已经加", "已经写", "写进", "加到", "文件末尾", "末尾加上")
    return any(marker in compact for marker in done_markers)



def _is_path_location_request(user_text: str) -> bool:
    text = str(user_text or "").strip()
    if not text:
        return False
    markers = ("脚本目录", "文件目录", "文件路径", "路径", "目录发我", "路径发我", "在哪", "哪里", "发我")
    return any(marker in text for marker in markers)


def _extract_abs_paths_from_trace(trace: list[dict[str, Any]] | None) -> list[str]:
    paths: list[str] = []
    for item in trace or []:
        if not isinstance(item, dict):
            continue
        result_text = str(item.get("result") or "")
        payload: dict[str, Any] = {}
        try:
            parsed = json.loads(result_text)
            if isinstance(parsed, dict):
                payload = parsed
        except Exception:
            payload = {}
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        for key in ("abs_path", "abs_output"):
            value = str(data.get(key) or "").strip()
            if value and value not in paths:
                paths.append(value)
        output = str(payload.get("output") or "")
        for match in re.findall(r"\babs_(?:path|output)=([^\s]+)", output):
            if match and match not in paths:
                paths.append(match)
    return paths


def _is_nonebot_project_root_request(user_text: str) -> bool:
    text = str(user_text or "").strip().lower()
    if not text:
        return False
    has_nonebot = "nonebot" in text
    has_root = any(marker in text for marker in ("项目根路径", "项目根目录", "项目在哪", "根路径", "根目录"))
    return has_nonebot and has_root


def _deterministic_path_probe_reply(config: Any, project_root: str | Path | None, user_text: str) -> OwnerToolboxLightResult | None:
    if not _is_nonebot_project_root_request(user_text):
        return None
    root_hint = str(project_root or "/opt/yangyang_nonebot").strip() or "/opt/yangyang_nonebot"
    script = f"""from pathlib import Path
candidates = [Path({root_hint!r}), Path('/opt/yangyang_nonebot'), Path('/mnt/warehouse/opt_moved/yangyang_nonebot')]
seen = []
for p in candidates:
    rp = str(p.resolve()) if p.exists() else str(p)
    if rp not in seen:
        seen.append(rp)
for item in seen:
    print(item)
"""
    command = "python3 - <<'PY'\
" + script + "PY"
    executed = execute_owner_toolbox_tool("shell", {"command": command}, config, project_root=project_root)
    paths: list[str] = []
    if isinstance(executed.data, dict):
        for key in ("abs_path", "abs_output"):
            value = str(executed.data.get(key) or "").strip()
            if value and value not in paths:
                paths.append(value)
    output = str(executed.output or executed.reply or "").strip()
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("/") and line not in paths:
            paths.append(line)
    trace_item = {
        "tool_name": "shell",
        "args": {"command": command},
        "ok": bool(executed.allowed),
        "result": json.dumps({
            "allowed": executed.allowed,
            "reason": executed.reason,
            "reply": executed.reply,
            "output": executed.output,
            "data": executed.data,
        }, ensure_ascii=False, default=str),
    }
    if executed.allowed and paths:
        joined = "\n".join(f"- `{p}`" for p in paths)
        return _result(
            handled=True,
            allowed=True,
            reason="deterministic_path_probe",
            reply=f"Sir♂！实查完毕，NoneBot 项目根路径候选在这：\n{joined}",
            tool_name="shell",
            output=executed.output,
            data={"tier": "deterministic_path_probe", "tool_call_count": 1},
            raw_trace=[trace_item],
        )
    return _result(
        handled=True,
        allowed=bool(executed.allowed),
        reason=executed.reason or "deterministic_path_probe_failed",
        reply="花♂Q，这次实查链路没给我吐出准坐标。漂♂总，再给我一句，我继续顺着工具往下刨。",
        tool_name="shell",
        output=executed.output,
        data={"tier": "deterministic_path_probe", "tool_call_count": 1},
        raw_trace=[trace_item],
    )


def _contains_absolute_path(text: str) -> bool:
    return bool(re.search(r"(?:^|[\s`：:，。])(?:/|~|[A-Za-z]:\\)[^\s`，。]+", str(text or "")))

def _format_isaac_p0_authoritative_reply(reply: str) -> str:
    lines = [line.strip() for line in str(reply or "").splitlines() if line.strip()]
    if not lines:
        return "I叔查完了，但没有返回可读报告。"
    task = _extract_report_value(lines, "task=")
    latest_run = _extract_report_value(lines, "latest_run=")
    status = _extract_report_value(lines, "status=")
    validation = next((line for line in lines if line.startswith("validation ")), "")
    collector = next((line for line in lines if line.startswith("collector ")), "")
    controller = next((line for line in lines if line.startswith("controller ")), "")
    dispatcher = next((line for line in lines if line.startswith("dispatcher ")), "")
    read_only = "read_only=true" in reply
    shell_used = "shell_used=true" in reply
    host_action = "host_action_executed=true" in reply

    summary = ["漂♂总，I叔已经通过 AgentBus P0 只读链路查过黑奴工厂了："]
    if latest_run or status:
        summary.append(f"- 最近一次工厂运行：`{latest_run or 'unknown'}`，状态 `{status or 'unknown'}`。")
    if validation:
        summary.append(f"- 验收结果：{validation.replace('validation ', '')}。")
    if collector:
        summary.append(f"- 收集器：{collector.replace('collector ', '')}。")
    if controller:
        summary.append(f"- 控制器：{controller.replace('controller ', '')}。")
    if dispatcher:
        summary.append(f"- 调度器：{dispatcher.replace('dispatcher ', '')}。")
    safety = []
    safety.append("只读" if read_only else "非只读标记缺失")
    safety.append("未用 shell" if not shell_used else "使用过 shell")
    safety.append("未执行宿主动作" if not host_action else "执行过宿主动作")
    summary.append(f"- 安全标记：{'，'.join(safety)}。")
    if task:
        summary.append(f"原始任务：`{task}`。")
    return "\n".join(summary)


def _extract_report_value(lines: list[str], key: str) -> str:
    for line in lines:
        if key not in line:
            continue
        tail = line.split(key, 1)[1]
        return tail.split()[0].strip()
    return ""


def _isaac_p0_authoritative_reply_from_trace(trace: list[dict[str, Any]] | None) -> str:
    for item in trace or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("tool_name") or "").strip() != "isaac_p0":
            continue
        result_text = str(item.get("result") or "")
        payload: dict[str, Any] = {}
        try:
            parsed = json.loads(result_text)
            if isinstance(parsed, dict):
                payload = parsed
        except Exception:
            payload = {}
        if payload.get("allowed", True) is False:
            continue
        reply = str(payload.get("reply") or payload.get("output") or "").strip()
        if "agentbus_factory_check=readonly_latest_run_v1" in reply:
            return _format_isaac_p0_authoritative_reply(reply)
    return ""


def _model_final_content(text: str, trace: list[dict[str, Any]] | None = None, *, user_text: str = "") -> str:
    """Return natural model-authored content; hide accidental tool payloads."""
    isaac_reply = _isaac_p0_authoritative_reply_from_trace(trace)
    if isaac_reply:
        return isaac_reply
    compact_user = str(user_text or "").strip()
    if re.fullmatch(r"(?:第?\d+|[一二三四五六七八九十]+|第[一二三四五六七八九十]+个)", compact_user) and not trace:
        return "这个编号我没法可靠对应到候选。漂♂总把要选的文件路径或候选名称再说一遍，我再继续。"
    cleaned = str(text or "").strip()
    if _is_deferred_write_request(user_text) and not _trace_has_successful_mutation(trace):
        if cleaned and not _looks_like_frontend_tool_payload(cleaned) and not _looks_like_write_completion_claim(cleaned):
            return cleaned
        return _deferred_write_ack_reply(user_text)
    if _write_like_request_requires_successful_mutation(user_text) and not _trace_has_successful_mutation(trace):
        return _missing_mutation_reply(user_text)
    if _is_path_location_request(user_text):
        abs_paths = _extract_abs_paths_from_trace(trace)
        if abs_paths:
            if cleaned and not _looks_like_frontend_tool_payload(cleaned) and any(path in cleaned for path in abs_paths):
                return cleaned
            joined = "\n".join(f"- `{path}`" for path in abs_paths)
            return f"漂♂总，我查到的真实路径是：\n{joined}"
        if cleaned and _contains_absolute_path(cleaned):
            return "花♂Q，这个坐标我还没亲手扫过，不报假数。等我实查完真实路径，再给你准坐标。"
    if trace:
        model_list_data = _trace_model_profile_list_data(trace)
        if model_list_data:
            return _format_model_profile_list_from_trace(model_list_data, user_text=user_text)
    if cleaned and not _looks_like_frontend_tool_payload(cleaned):
        return cleaned
    if trace:
        return _fallback_human_reply_from_trace(trace, user_text=user_text)
    return cleaned


async def handle_owner_toolbox_light_llm_message(
    message: Any,
    config: Any = None,
    *,
    model_router: Any,
    project_root: str | Path | None = None,
    tier: str = "v4_flash",
    session_id: str | None = None,
) -> OwnerToolboxLightResult:
    slash = parse_slash_command(message)
    if slash is not None:
        return await handle_slash_command(message, config, project_root=project_root)
    if not is_owner_private(message, config):
        return _result(handled=False, allowed=False, reason="not_owner_private")
    if not _config_get_bool(config, "owner_toolbox_light_native_loop_enabled", True):
        return _result(handled=False, allowed=False, reason="native_loop_disabled")
    if model_router is None or not hasattr(model_router, "call_with_tool_loop"):
        return _result(handled=False, allowed=False, reason="native_loop_unavailable")

    user_text = _message_text(message).strip()
    raw_mode = wants_owner_toolbox_raw_details(user_text)
    clean_text = _strip_raw_mode_markers(user_text) if raw_mode else user_text

    deterministic_path_result = _deterministic_path_probe_reply(config, project_root, clean_text or user_text)
    if deterministic_path_result is not None:
        return deterministic_path_result

    def _executor(name: str, args: dict[str, Any]) -> OwnerToolboxLightResult | Any:
        context_channel = str(getattr(message, "channel", "") or "private")
        argmap: Any = dict(args or {}) if isinstance(args, dict) else args
        if isinstance(argmap, dict):
            argmap.setdefault("_context_channel", context_channel)
            context_uid = str(getattr(message, "uid", "") or getattr(message, "user_id", "") or "").strip()
            if context_uid:
                argmap.setdefault("_context_user_id", context_uid)
                argmap.setdefault("_context_uid", context_uid)
            if session_id:
                argmap.setdefault("_session_id", session_id)
            if str(name or "").strip() == "list_model_profiles":
                if _wants_enabled_only_model_profile_list(user_text):
                    argmap["include_disabled"] = False
                    argmap.setdefault("_raw", user_text)
                elif _wants_full_model_profile_list(user_text):
                    argmap["include_disabled"] = True
                    argmap.setdefault("_raw", user_text)
        if str(name or "").strip() == "write" and _is_deferred_write_request(user_text):
            return _result(
                allowed=False,
                reason="deferred_write_not_ready",
                reply=_deferred_write_ack_reply(user_text),
                tool_name="write",
                data={"deferred": True, "needs_target_path": True},
            )
        if _write_target_is_ambiguous(user_text, str(name or ""), argmap):
            return _result(
                allowed=False,
                reason="ambiguous_write_target",
                reply="目标文件不够明确。请先确认具体文件路径后我再写入，不能把‘那个 txt’脑补成某个文件。",
                tool_name="write",
                data={"needs_confirmed_path": True},
            )
        if str(name or "").strip() in {"test_model_profile", "isaac_p0", "refresh_model_profiles"}:
            return execute_owner_toolbox_tool_async(
                name,
                argmap,
                config,
                project_root=project_root,
                model_router=model_router,
                context_channel=context_channel,
            )
        return execute_owner_toolbox_tool(name, argmap, config, project_root=project_root)

    if _is_model_profile_list_request(clean_text):
        context_channel = str(getattr(message, "channel", "") or "private")
        include_disabled = _wants_full_model_profile_list(clean_text)
        executed = execute_owner_toolbox_tool(
            "list_model_profiles",
            {
                "scope": "current",
                "include_disabled": include_disabled,
                "_context_channel": context_channel,
                "_raw": clean_text,
            },
            config,
            project_root=project_root,
        )
        reply = _format_model_profile_list_from_trace(executed.data if isinstance(executed.data, dict) else {}, user_text=clean_text)
        if raw_mode:
            reply = format_owner_toolbox_raw_details(executed)
        trace_item = {
            "tool_name": "list_model_profiles",
            "args": {"scope": "current", "include_disabled": include_disabled},
            "ok": bool(executed.allowed),
            "result": json.dumps({
                "allowed": executed.allowed,
                "reason": executed.reason,
                "reply": executed.reply,
                "output": executed.output,
                "data": executed.data,
            }, ensure_ascii=False, default=str),
        }
        return _result(
            handled=True,
            allowed=executed.allowed,
            reason=executed.reason,
            reply=reply,
            tool_name="list_model_profiles",
            output=executed.output,
            data={"tier": tier, "tool_call_count": 1},
            raw_trace=[trace_item],
        )

    # ---- plan-only gate: classify intent before entering tool loop ----
    # Can be disabled by setting owner_toolbox_light_plan_only_gate_enabled=false
    if not raw_mode and _config_get_bool(config, "owner_toolbox_light_plan_only_gate_enabled", True):
        gate_mode = await classify_owner_intent(
            clean_text or user_text,
            model_router,
            tier,
            session_id=session_id,
            channel=str(getattr(message, "channel", "") or ""),
        )
        if gate_mode == "plan_only":
            plan_response, plan_tier = await model_router.call(
                tier,
                plan_only_messages(clean_text or user_text),
                temperature=0.2,
                session_id=session_id,
                channel=str(getattr(message, "channel", "") or ""),
                timeout_bucket="longform",
                interaction_phase="plan_only_delivery",
                allow_streaming=False,
            )
            return _result(
                handled=True,
                allowed=True,
                reason="plan_only",
                reply=_model_final_content(plan_response, [], user_text=user_text),
                tool_name=None,
                output=plan_response,
                data={"tier": plan_tier, "plan_only_mode": True, "tool_call_count": 0},
            )
        elif gate_mode == "clarify":
            return _result(
                handled=True,
                allowed=True,
                reason="clarify",
                reply=CLARIFY_REPLY,
                tool_name=None,
                data={"plan_only_clarify": True},
            )
    # ---- end plan-only gate ----

    response_text, actual_tier, trace = await model_router.call_with_tool_loop(
        tier,
        _owner_tool_loop_messages(clean_text or user_text),
        tools=build_owner_toolbox_tools(),
        tool_executor=_executor,
        temperature=0.2,
        session_id=session_id,
        tool_choice="auto",
        max_steps=get_owner_tool_loop_max_steps(config),
        channel=str(getattr(message, "channel", "") or ""),
        timeout_bucket="tool_followup",
        interaction_phase="tool_followup",
        allow_streaming=False,
    )
    reply = format_owner_toolbox_raw_details(
        _result(reason="ok", reply=response_text, tool_name="llm_tool_loop", data={"tier": actual_tier}, raw_trace=trace)
    ) if raw_mode else _model_final_content(response_text, trace, user_text=user_text)
    return _result(
        handled=True,
        allowed=True,
        reason="ok" if trace else "no_tool_call",
        reply=reply,
        tool_name=(trace[-1].get("tool_name") if trace else None),
        output=response_text,
        data={"tier": actual_tier, "tool_call_count": len(trace)},
        raw_trace=trace,
    )


async def handle_slash_command(
    message: Any,
    config: Any = None,
    *,
    project_root: str | Path | None = None,
    model_router: Any = None,
) -> OwnerToolboxLightResult:
    command = parse_slash_command(message)
    if command is None:
        return _result(handled=False, allowed=False, reason="not_slash_command")
    if not is_owner_private(message, config):
        if command.token in {"i叔", "艾萨克"} and handle_isaac_agent_bus_p0_message is not None:
            try:
                handle_isaac_agent_bus_p0_message(message)
            except Exception:
                pass
        return _result(handled=False, allowed=False, reason="not_owner_private", slash_command=command)

    if command.token == "toolbox" and command.argv and command.argv[0].lower() in {"max_steps", "max-steps", "maxsteps"}:
        parsed = parse_owner_tool_loop_max_steps_command(command.raw_text)
        if parsed is None:
            return _result(reason="ok", reply=f"当前工具 loop 调用上限是 {get_owner_tool_loop_max_steps(config)} 步。", tool_name="get_tool_loop_max_steps", slash_command=command)
        proxy_message = type("ToolboxMaxStepsMessage", (), {
            "text": command.raw_text,
            "raw_content": command.raw_text,
            "uid": getattr(message, "uid", ""),
            "user_id": getattr(message, "user_id", ""),
            "channel": getattr(message, "channel", ""),
            "is_owner": getattr(message, "is_owner", False),
        })()
        result = handle_owner_tool_loop_max_steps_message(proxy_message, config)
        return _result(
            handled=result.handled,
            allowed=result.allowed,
            reason=result.reason,
            reply=result.reply,
            tool_name=result.tool_name,
            output=result.output,
            data=result.data,
            slash_command=command,
        )

    if command.token == "token":
        channel = str(getattr(message, "channel", "") or "private")
        uid = str(getattr(message, "uid", "") or getattr(message, "user_id", "") or "")
        group_id = str(getattr(message, "group_id", "") or "")
        current_session_id = f"group:{group_id}" if channel == "group" and group_id else (f"private:{uid}" if uid else "")
        rest = str(command.rest or "").strip().lower()
        args = {"_session_id": current_session_id}
        if any(x in rest for x in ("hour", "小时", "本小时")):
            args["period"] = "hour"
        if any(x in rest for x in ("today", "day", "今日", "今天")):
            args["period"] = "today"
        if any(x in rest for x in ("month", "本月", "这个月")):
            args["period"] = "month"
        if any(x in rest for x in ("model", "模型")):
            args["group_by"] = "model"
        if any(x in rest for x in ("byhour", "按小时", "hourly")):
            args["group_by"] = "hour"
        if any(x in rest for x in ("byday", "按天", "daily")):
            args["group_by"] = "day"
        if any(x in rest for x in ("bymonth", "按月", "monthly")):
            args["group_by"] = "month"
        if any(x in rest for x in ("all", "全部", "全维度")):
            args["group_by"] = "all"
        executed = execute_owner_toolbox_tool("query_token_usage", args, config, project_root=project_root)
        return _result(
            allowed=executed.allowed,
            reason=executed.reason,
            reply=executed.reply,
            tool_name=executed.tool_name,
            output=executed.output,
            data=executed.data,
            slash_command=command,
        )
    if command.token == "help":
        return _result(reason="ok", reply=_usage(), tool_name="help", slash_command=command)
    if command.token == "confirm":
        return _result(reason="ok", reply="Light 版不走 confirm 流程，直接用 /toolbox 执行。", tool_name="confirm", slash_command=command)
    if command.token in {"i叔", "艾萨克"}:
        context_uid = str(getattr(message, "uid", "") or getattr(message, "user_id", "") or "").strip()
        executed = await execute_owner_toolbox_tool_async(
            "isaac_p0",
            {
                # Preserve the slash head for explicit /i叔 fallback so P0
                # audit records slash_fallback and P0 does not see a bare body.
                "command_text": str(command.raw_text or getattr(message, "text", "") or getattr(message, "raw_content", "") or "").strip() or f"/{command.token}",
                "_context_channel": str(getattr(message, "channel", "") or "private"),
                "_context_user_id": context_uid,
                "_context_uid": context_uid,
            },
            config,
            project_root=project_root,
            model_router=model_router,
            context_channel=str(getattr(message, "channel", "") or "private"),
        )
        return _result(
            allowed=executed.allowed,
            reason=executed.reason,
            reply=executed.reply,
            tool_name=executed.tool_name,
            output=executed.output,
            data=executed.data,
            slash_command=command,
        )

    if command.token == "isaac":
        if command.rest.strip():
            invocation = parse_natural_tool_invocation(command.rest)
            if invocation is not None:
                executed = execute_owner_toolbox_tool(invocation.tool_name, invocation.args, config, project_root=project_root)
                return _result(
                    allowed=executed.allowed,
                    reason=executed.reason,
                    reply=executed.reply,
                    tool_name=executed.tool_name,
                    output=executed.output,
                    data=executed.data,
                    slash_command=command,
                )
        return _result(reason="ok", reply="Isaac 轻量入口已接上；P0 slash 兜底请用 /i叔 或 /艾萨克。工程工具请用 /toolbox。", tool_name="isaac", slash_command=command)

    invocation = _invocation_from_toolbox_text(command.rest or "status", source="slash")
    executed = execute_owner_toolbox_tool(invocation.tool_name, invocation.args, config, project_root=project_root)
    return _result(
        allowed=executed.allowed,
        reason=executed.reason,
        reply=executed.reply,
        tool_name=executed.tool_name,
        output=executed.output,
        data=executed.data,
        slash_command=command,
    )


async def handle_owner_toolbox_light_message(
    message: Any,
    config: Any = None,
    *,
    project_root: str | Path | None = None,
    model_router: Any = None,
) -> OwnerToolboxLightResult:
    slash = parse_slash_command(message)
    if slash is not None:
        return await handle_slash_command(message, config, project_root=project_root, model_router=model_router)
    if not is_owner_private(message, config):
        return _result(handled=False, allowed=False, reason="not_owner_private")
    # Native NL path must go through LLM tool loop.  This explicit legacy
    # prefix is kept only as a manual slash-like fallback for old habits.
    if not is_legacy_toolbox_prefix(message):
        return _result(handled=False, allowed=False, reason="no_tool_intent")
    invocation = parse_natural_tool_invocation(message)
    if invocation is None:
        return _result(handled=False, allowed=False, reason="no_tool_intent")
    executed = execute_owner_toolbox_tool(invocation.tool_name, invocation.args, config, project_root=project_root)
    return _result(
        allowed=executed.allowed,
        reason=executed.reason,
        reply=executed.reply,
        tool_name=executed.tool_name,
        output=executed.output,
        data=executed.data,
    )


def handle_owner_toolbox_light_message_sync(
    message: Any,
    config: Any = None,
    *,
    project_root: str | Path | None = None,
) -> OwnerToolboxLightResult:
    return asyncio.run(handle_owner_toolbox_light_message(message, config, project_root=project_root))
