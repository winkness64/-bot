from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import asyncio
import ast
import fnmatch
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tarfile
import time
from typing import Any, Awaitable, Callable, Iterable, Literal, Mapping

try:
    from .isaac_readonly_health import build_readonly_health_snapshot
except Exception:  # pragma: no cover - direct file loading fallback for tests.
    build_readonly_health_snapshot = None  # type: ignore[assignment]


ToolboxRiskLevel = Literal["low", "medium", "high"]
ToolboxGateMode = Literal["execute", "dry_run", "require_confirm", "blocked"]

PROJECT_ROOT = Path(__file__).resolve().parents[4]
FORBIDDEN_PRODUCTION_ROOT = Path("/opt/yangyang_nonebot")

LOW_RISK_TOOLS: tuple[str, ...] = (
    "toolbox_status",
    "list_dir",
    "read_file",
    "grep",
    "find",
    "health",
    "log_tail",
    "sha256",
)
MEDIUM_RISK_TOOLS: tuple[str, ...] = (
    "write_file",
    "append_file",
    "edit_file",
    "mkdir",
    "rm",
    "pack_archive",
)
HIGH_RISK_TOOLS: tuple[str, ...] = (
    "shell",
    "python",
)
TOOL_ALLOWLIST: frozenset[str] = frozenset(LOW_RISK_TOOLS + MEDIUM_RISK_TOOLS + HIGH_RISK_TOOLS)

TOOL_ALIASES: dict[str, str] = {
    "status": "toolbox_status",
    "状态": "toolbox_status",
    "help": "toolbox_status",
    "帮助": "toolbox_status",
    "toolbox_status": "toolbox_status",
    "list": "list_dir",
    "ls": "list_dir",
    "dir": "list_dir",
    "列目录": "list_dir",
    "list_dir": "list_dir",
    "read": "read_file",
    "cat": "read_file",
    "读取": "read_file",
    "读": "read_file",
    "read_file": "read_file",
    "grep": "grep",
    "search": "grep",
    "搜索": "grep",
    "搜": "grep",
    "find": "find",
    "查找": "find",
    "health": "health",
    "健康": "health",
    "自检": "health",
    "log": "log_tail",
    "logs": "log_tail",
    "tail": "log_tail",
    "log_tail": "log_tail",
    "日志": "log_tail",
    "write": "write_file",
    "write_file": "write_file",
    "writefile": "write_file",
    "写": "write_file",
    "append": "append_file",
    "append_file": "append_file",
    "追加": "append_file",
    "mkdir": "mkdir",
    "md": "mkdir",
    "创建目录": "mkdir",
    "rm": "rm",
    "remove": "rm",
    "trash": "rm",
    "删除": "rm",
    "edit": "edit_file",
    "edit_file": "edit_file",
    "editfile": "edit_file",
    "改": "edit_file",
    "shell": "shell",
    "sh": "shell",
    "cmd": "shell",
    "命令": "shell",
    "执行": "shell",
    "python": "python",
    "py": "python",
    "pack": "pack_archive",
    "tar": "pack_archive",
    "archive": "pack_archive",
    "打包": "pack_archive",
    "sha256": "sha256",
    "checksum": "sha256",
    "hash": "sha256",
    "pack_sha256": "sha256",
}

SENSITIVE_PATH_MARKERS: tuple[str, ...] = (
    "token",
    "secret",
    "secrets",
    "passwd",
    "password",
    "credential",
    "credentials",
    "private_key",
    "api_key",
    "memories.jsonl",
)
SENSITIVE_EXACT_NAMES: frozenset[str] = frozenset(
    {
        ".env",
        ".env.local",
        ".env.production",
        ".env.prod",
        ".env.dev",
        ".env.example",
        "id_rsa",
        "id_ed25519",
        "known_hosts",
    }
)
SENSITIVE_SUFFIXES: tuple[str, ...] = (".pem", ".key", ".p12", ".pfx", ".crt", ".cer")
TEXT_SUFFIX_ALLOWLIST: frozenset[str] = frozenset(
    {
        "",
        ".txt",
        ".md",
        ".py",
        ".json",
        ".jsonl",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".csv",
        ".log",
        ".sh",
        ".rst",
        ".sql",
        ".html",
        ".css",
        ".js",
        ".ts",
        ".tsx",
        ".jsx",
    }
)
DEFAULT_MAX_READ_BYTES = 64 * 1024
DEFAULT_MAX_READ_LINES = 120
DEFAULT_MAX_LIST_ENTRIES = 80
DEFAULT_MAX_GREP_RESULTS = 30
DEFAULT_MAX_GREP_FILES = 200
DEFAULT_MAX_PACK_FILES = 100
DEFAULT_MAX_TAIL_LINES = 80
DEFAULT_EXEC_TIMEOUT_SECONDS = 30
DEFAULT_MAX_OUTPUT_CHARS = 6000
DEFAULT_AUDIT_PATH = "logs/owner_engineering_toolbox_audit.jsonl"
NL_SCHEMA_VERSION = "owner_engineering_toolbox.nl_v1.20260608"
NATURAL_TOOL_TRIGGER_HINTS: tuple[str, ...] = (
    "文件",
    "目录",
    "日志",
    "代码",
    "源码",
    "项目",
    "仓库",
    "路径",
    "脚本",
    "测试",
    "打包",
    "压缩",
    "创建",
    "新建",
    "写入",
    "追加",
    "替换",
    "修改",
    "删除",
    "移动",
    "读取",
    "看一下",
    "看看",
    "瞅一眼",
    "瞅一下",
    "瞅瞅",
    "列",
    "搜",
    "查找",
    "grep",
    "find",
    "sha256",
    "hash",
    "执行",
    "跑一下",
    "运行",
    "python",
    "shell",
    "命令",
    "pytest",
    "import ast",
    "自检",
    "健康",
    "状态",
    "报错",
    "尾部",
    "tail",
)
CHAT_ONLY_HINTS: tuple[str, ...] = (
    "早上好",
    "中午好",
    "晚上好",
    "晚安",
    "你好",
    "在吗",
    "辛苦了",
    "谢谢",
    "你是谁",
    "讲个笑话",
    "随便聊",
)
HIGH_RISK_NL_MARKERS: tuple[str, ...] = (
    "rm -rf",
    "sudo",
    "chmod -r",
    "chown -r",
    "mkfs",
    "dd if=",
    "systemctl",
    "service ",
    "reboot",
    "shutdown",
    "docker compose down",
    "docker-compose down",
    "kill -9",
    "pkill",
    "删库",
    "清库",
    "清空",
    "重启",
    "停服",
    "上线",
    "部署到生产",
    "生产部署",
)
HIGH_RISK_COMMAND_MARKERS: tuple[str, ...] = (
    "rm -rf",
    "sudo",
    "chmod -r",
    "chown -r",
    "mkfs",
    "dd if=",
    "systemctl",
    "service ",
    "reboot",
    "shutdown",
    "docker compose down",
    "docker-compose down",
    "kill -9",
    "pkill",
)


ToolboxIntentProvider = Callable[[str, dict[str, Any]], Mapping[str, Any] | str | Awaitable[Mapping[str, Any] | str]]
ToolboxResultFormatterProvider = Callable[[dict[str, Any], dict[str, Any]], str | Awaitable[str]]


@dataclass(frozen=True)
class ToolboxCommand:
    tool_name: str
    raw_tool_name: str
    args: tuple[str, ...]
    raw_text: str
    command_text: str
    debug: bool = False


@dataclass(frozen=True)
class ToolboxIntentPlan:
    action: str
    tool_name: str
    args: tuple[str, ...]
    raw_text: str
    command_text: str
    risk_level: ToolboxRiskLevel
    confidence: float
    reason: str
    source: str
    reply: str = ""
    raw_model_output: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolboxGateResult:
    allowed: bool
    mode: ToolboxGateMode
    reason: str
    actor: str
    tool_name: str
    risk_level: ToolboxRiskLevel
    requires_confirm: bool
    dry_run: bool
    safe_to_execute: bool
    workspace_root: str
    owner_private_required: bool = True
    blocked_by_config: bool = False


@dataclass(frozen=True)
class ToolboxExecutionResult:
    tool_name: str
    status: str
    reason: str
    risk_level: ToolboxRiskLevel
    mode: ToolboxGateMode
    real_write: bool = False
    real_execute: bool = False
    output: str = ""
    data: dict[str, Any] | None = None


@dataclass(frozen=True)
class ToolboxHandleResult:
    handled: bool
    allowed: bool
    reason: str
    reply: str
    tool_name: str | None = None
    command: ToolboxCommand | None = None
    gate: ToolboxGateResult | None = None
    execution: ToolboxExecutionResult | None = None
    intent_plan: ToolboxIntentPlan | None = None
    raw_reply: str = ""
    formatted_text: str = ""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _config_get(config: Any, path: str, default: Any = None) -> Any:
    getter = getattr(config, "get", None)
    if callable(getter):
        try:
            return getter(path, default)
        except TypeError:
            pass
    if isinstance(config, dict):
        cur: Any = config
        for part in path.split("."):
            if not isinstance(cur, dict) or part not in cur:
                return default
            cur = cur[part]
        return cur
    return default


def _config_get_bool(config: Any, path: str, default: bool = False) -> bool:
    getter = getattr(config, "get_bool", None)
    if callable(getter):
        try:
            return bool(getter(path, default))
        except TypeError:
            pass
    value = _config_get(config, path, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _config_get_int(config: Any, path: str, default: int, *, minimum: int = 1, maximum: int | None = None) -> int:
    raw = _config_get(config, path, default)
    try:
        value = int(raw)
    except Exception:
        value = int(default)
    value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def _is_owner_message(message: Any, config: Any) -> bool:
    if bool(getattr(message, "is_owner", False)):
        return True
    uid = str(getattr(message, "uid", "") or "").strip()
    if not uid:
        return False
    owner_uids = _config_get(config, "owner_uids", []) or []
    owner_uid = str(_config_get(config, "owner_uid", "335059272") or "335059272")
    normalized = {str(owner_uid)}
    if isinstance(owner_uids, Iterable) and not isinstance(owner_uids, (str, bytes)):
        normalized.update(str(item).strip() for item in owner_uids if str(item or "").strip())
    normalized.add("335059272")
    return uid in normalized


def _extract_toolbox_command_text(text: str) -> str | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    for prefix in ("工具箱", "toolbox", "Toolbox", "TOOLBOX"):
        if raw.startswith(prefix):
            return raw[len(prefix):].strip(" \t\r\n:：,，")
    return None


def _split_command_text(command_text: str) -> list[str]:
    raw = str(command_text or "").strip()
    if not raw:
        return []
    try:
        return [str(item) for item in shlex.split(raw) if str(item).strip()]
    except Exception:
        return [item for item in re.split(r"\s+", raw) if item]


def parse_toolbox_command(text_or_message: Any) -> ToolboxCommand | None:
    text = str(getattr(text_or_message, "text", "") or getattr(text_or_message, "raw_content", "") or text_or_message or "")
    command_text = _extract_toolbox_command_text(text)
    if command_text is None:
        return None
    debug = False
    effective_command_text = command_text
    debug_match = re.match(r"^(?:debug|raw|调试)(?:\s+|[:：]\s*)?(.*)$", command_text, flags=re.IGNORECASE)
    if debug_match:
        debug = True
        effective_command_text = (debug_match.group(1) or "").strip() or "status"
    tokens = _split_command_text(effective_command_text)
    raw_tool = tokens[0] if tokens else "status"
    tool = TOOL_ALIASES.get(raw_tool.strip().lower(), TOOL_ALIASES.get(raw_tool.strip(), raw_tool.strip().lower()))
    if not tool:
        tool = "toolbox_status"
    args = tuple(tokens[1:])
    normalized_raw_text = f"工具箱 {effective_command_text}".strip() if debug else text
    return ToolboxCommand(
        tool_name=tool,
        raw_tool_name=raw_tool,
        args=args,
        raw_text=normalized_raw_text,
        command_text=effective_command_text,
        debug=debug,
    )



def _message_text(message: Any) -> str:
    return str(getattr(message, "text", "") or getattr(message, "raw_content", "") or message or "")


def _risk_rank(level: str) -> int:
    return {"low": 0, "medium": 1, "high": 2}.get(str(level or "").lower(), 0)


def _normalize_risk(level: Any, default: ToolboxRiskLevel = "low") -> ToolboxRiskLevel:
    value = str(level or default).strip().lower()
    if value in {"critical", "danger", "blocked"}:
        return "high"
    if value in {"high", "medium", "low"}:
        return value  # type: ignore[return-value]
    return default


def _normalize_plan_action(action: Any) -> str:
    value = str(action or "").strip().lower().replace("-", "_")
    aliases = {
        "run": "execute",
        "call": "execute",
        "tool": "execute",
        "tool_call": "execute",
        "ask": "clarify",
        "clarification": "clarify",
        "clarification_required": "clarify",
        "need_clarification": "clarify",
        "require_confirm": "confirm",
        "needs_confirmation": "confirm",
        "confirmation": "confirm",
        "deny": "blocked",
        "block": "blocked",
        "chat": "none",
        "no_tool": "none",
        "ignore": "none",
    }
    value = aliases.get(value, value)
    return value if value in {"execute", "clarify", "confirm", "blocked", "none"} else "clarify"


def _natural_tool_hint_present(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    lowered = value.lower()
    compact = re.sub(r"\s+", "", lowered)
    if _extract_toolbox_command_text(value) is not None:
        return True
    if re.search(r"(^|\s)(ls|cat|grep|find|tail|pytest|python3?|bash|sh|git|tar|sha256sum)(\s|$)", lowered):
        return True
    if re.search(r"[\w./-]+\.(py|md|txt|json|jsonl|ya?ml|toml|log|sh|ini|cfg|csv|html|css|js|ts|tsx|jsx)\b", lowered):
        return True
    return any(str(hint).lower().replace(" ", "") in compact for hint in NATURAL_TOOL_TRIGGER_HINTS)


def _looks_like_chat_only(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return True
    if _high_risk_marker_for_text(value):
        return False
    lowered = value.lower()
    compact = re.sub(r"[\s，。！？!?,.]+", "", lowered)
    if any(hint in compact for hint in CHAT_ONLY_HINTS):
        return not _natural_tool_hint_present(value)
    if len(value) <= 12 and not _natural_tool_hint_present(value):
        return True
    return False


def _should_skip_toolbox_nl_for_other_router(text: str) -> bool:
    # I线 / Isaac 有独立 owner-private 路由；NL 工具箱不得抢占。
    return bool(re.search(r"(?i)i叔|艾萨克|isaac", str(text or "")))


def _high_risk_marker_for_text(text: str) -> str | None:
    return _high_risk_marker_for_text_with_markers(text, HIGH_RISK_NL_MARKERS)


def _high_risk_marker_for_command(text: str) -> str | None:
    return _high_risk_marker_for_text_with_markers(text, HIGH_RISK_COMMAND_MARKERS)


def _high_risk_marker_for_text_with_markers(text: str, markers: Iterable[str]) -> str | None:
    lowered = str(text or "").lower()
    compact = re.sub(r"\s+", "", lowered)
    for marker in markers:
        m = marker.lower()
        if m in lowered or m.replace(" ", "") in compact:
            return marker
    return None


def _redline_plan_for_text(text: str) -> ToolboxIntentPlan | None:
    raw = str(text or "")
    if not raw.strip():
        return None
    if "冷备" in raw or "冷备份" in raw:
        cold_backup_tool_markers = ("目录", "文件", "路径", "里面", "下有", "列", "看下", "看一下", "看看", "展开", "翻", "读取", "打开", "ls", "dir", "cat")
        if any(marker in raw.lower() for marker in cold_backup_tool_markers):
            return ToolboxIntentPlan(
                action="clarify",
                tool_name="list_dir",
                args=(),
                raw_text=raw,
                command_text="",
                risk_level="low",
                confidence=1.0,
                reason="missing_controlled_workspace_path",
                source="redline_rules",
                reply="冷备相关不能直接展开路径；请给相对工作区路径，或走受控交接。",
            )
    has_tool_hint = _natural_tool_hint_present(raw)
    forbidden = _forbidden_command_reason(raw)
    if forbidden and has_tool_hint:
        return ToolboxIntentPlan(
            action="blocked",
            tool_name="none",
            args=(),
            raw_text=raw,
            command_text="",
            risk_level="high",
            confidence=1.0,
            reason=forbidden,
            source="redline_rules",
            reply=f"工具箱已拦截：reason={forbidden}。",
        )
    marker = _high_risk_marker_for_text(raw)
    if marker:
        action = "blocked" if marker.lower() in {"rm -rf", "mkfs", "dd if=", "清库", "删库"} else "confirm"
        return ToolboxIntentPlan(
            action=action,
            tool_name="shell" if re.search(r"(^|\s)(rm|sudo|systemctl|service|reboot|shutdown|docker|kill|pkill|dd|mkfs)(\s|$)", raw.lower()) else "none",
            args=(),
            raw_text=raw,
            command_text="",
            risk_level="high",
            confidence=1.0,
            reason=f"high_risk_marker:{marker}",
            source="redline_rules",
            reply="工具箱识别到高风险动作，未直接执行；需要显式确认或改为低风险步骤。",
        )
    return None


def _json_object_from_text(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        decoded = json.loads(raw)
        return dict(decoded) if isinstance(decoded, Mapping) else None
    except Exception:
        pass
    match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL | re.IGNORECASE)
    if match:
        try:
            decoded = json.loads(match.group(1))
            return dict(decoded) if isinstance(decoded, Mapping) else None
        except Exception:
            return None
    start = raw.find("{")
    end = raw.rfind("}")
    if start >= 0 and end > start:
        try:
            decoded = json.loads(raw[start : end + 1])
            return dict(decoded) if isinstance(decoded, Mapping) else None
        except Exception:
            return None
    return None


def _mapping_from_provider_output(provider_output: Any) -> dict[str, Any] | None:
    if isinstance(provider_output, Mapping):
        return dict(provider_output)
    if isinstance(provider_output, str):
        return _json_object_from_text(provider_output)
    return None


def _redacted_raw_model_output(raw: Mapping[str, Any] | None, *, error: str | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if raw:
        for key, value in raw.items():
            if key in {"content", "old", "new", "command", "code"}:
                payload[str(key)] = {"sha256_16": _hash16(str(value)), "chars": len(str(value))}
            else:
                payload[str(key)] = _redact_sensitive_text(str(value))[:500] if isinstance(value, str) else value
    if error:
        payload["error"] = error
    return payload


def _first_str(*values: Any, default: str = "") -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return default


def _args_mapping(raw_args: Any) -> dict[str, Any]:
    if isinstance(raw_args, Mapping):
        return dict(raw_args)
    return {}


def _args_list(raw_args: Any) -> list[str]:
    if isinstance(raw_args, (list, tuple)):
        return [str(item) for item in raw_args]
    if isinstance(raw_args, str) and raw_args.strip():
        return _split_command_text(raw_args)
    return []


def _coerce_tool_name(raw_tool: Any) -> str:
    raw = str(raw_tool or "").strip()
    if not raw:
        return "none"
    return TOOL_ALIASES.get(raw.lower(), TOOL_ALIASES.get(raw, raw.lower()))


def _build_command_text(tool_name: str, args: tuple[str, ...], argmap: Mapping[str, Any]) -> str:
    if tool_name in {"write_file", "append_file"}:
        content = str(argmap.get("content") or argmap.get("text") or argmap.get("body") or "")
        return f"{tool_name} {args[0] if args else ''} <<<\n{content}\n>>>".strip()
    if tool_name == "edit_file":
        old = str(argmap.get("old") or argmap.get("old_text") or "")
        new = str(argmap.get("new") or argmap.get("new_text") or "")
        return f"{tool_name} {args[0] if args else ''} <<<\nOLD\n{old}\nOLD\nNEW\n{new}\nNEW\n>>>".strip()
    if tool_name == "python":
        code = str(argmap.get("code") or argmap.get("python") or argmap.get("content") or "")
        if code:
            if _looks_like_python_expression(code):
                code = f"print({code})"
            return f"python <<<\n{code}\n>>>"
    if tool_name == "shell":
        command = str(argmap.get("command") or argmap.get("cmd") or argmap.get("shell") or " ".join(args))
        return f"shell {command}".strip()
    return " ".join([tool_name] + list(args)).strip()


def _args_from_plan(tool_name: str, raw_args: Any, raw: Mapping[str, Any]) -> tuple[tuple[str, ...], dict[str, Any], str | None]:
    argmap = _args_mapping(raw_args)
    if not argmap:
        argmap = _args_mapping(raw.get("parameters")) or _args_mapping(raw.get("params"))
    if not argmap:
        argmap = {key: raw[key] for key in ("path", "query", "pattern", "command", "cmd", "code", "content", "text", "old", "new", "lines", "start_line") if key in raw}
    list_args = _args_list(raw_args)
    if list_args:
        return tuple(list_args), argmap, None

    def required_path() -> str | None:
        return _first_str(argmap.get("path"), argmap.get("file"), argmap.get("dir"), argmap.get("target"), default="") or None

    if tool_name == "toolbox_status":
        return (), argmap, None
    if tool_name == "list_dir":
        return (_first_str(argmap.get("path"), argmap.get("dir"), default="."),), argmap, None
    if tool_name == "read_file":
        path = required_path()
        if not path:
            return (), argmap, "missing_path"
        args = [path]
        if argmap.get("start_line") is not None:
            args.append(str(argmap.get("start_line")))
        if argmap.get("lines") is not None:
            if len(args) == 1:
                args.append("1")
            args.append(str(argmap.get("lines")))
        return tuple(args), argmap, None
    if tool_name == "grep":
        query = _first_str(argmap.get("query"), argmap.get("keyword"), argmap.get("pattern"), default="")
        if not query:
            return (), argmap, "missing_query"
        return (query, _first_str(argmap.get("path"), argmap.get("dir"), default=".")), argmap, None
    if tool_name == "find":
        pattern = _first_str(argmap.get("pattern"), argmap.get("name"), default="*")
        return (pattern, _first_str(argmap.get("path"), argmap.get("dir"), default=".")), argmap, None
    if tool_name == "log_tail":
        args = [_first_str(argmap.get("path"), argmap.get("file"), default="dist/current_task_result.md")]
        if argmap.get("lines") is not None:
            args.append(str(argmap.get("lines")))
        return tuple(args), argmap, None
    if tool_name == "sha256":
        path = required_path()
        if not path:
            return (), argmap, "missing_path"
        return (path,), argmap, None
    if tool_name in {"write_file", "append_file"}:
        path = required_path()
        if not path:
            return (), argmap, "missing_path"
        if not _first_str(argmap.get("content"), argmap.get("text"), argmap.get("body"), default=""):
            return (path,), argmap, "missing_content"
        return (path,), argmap, None
    if tool_name == "edit_file":
        path = required_path()
        if not path:
            return (), argmap, "missing_path"
        if not _first_str(argmap.get("old"), argmap.get("old_text"), default=""):
            return (path,), argmap, "missing_old"
        if "new" not in argmap and "new_text" not in argmap:
            return (path,), argmap, "missing_new"
        return (path,), argmap, None
    if tool_name in {"mkdir", "rm"}:
        path = required_path()
        if not path:
            return (), argmap, "missing_path"
        return (path,), argmap, None
    if tool_name == "pack_archive":
        return (_first_str(argmap.get("path"), argmap.get("dir"), default="."),), argmap, None
    if tool_name == "shell":
        command = _first_str(argmap.get("command"), argmap.get("cmd"), argmap.get("shell"), default="")
        if not command:
            return (), argmap, "missing_command"
        return tuple(_split_command_text(command)), {**argmap, "command": command}, None
    if tool_name == "python":
        code = _first_str(argmap.get("code"), argmap.get("python"), argmap.get("content"), default="")
        if not code:
            return (), argmap, "missing_code"
        if _looks_like_python_expression(code):
            code = f"print({code})"
        return (), {**argmap, "code": code}, None
    return (), argmap, "tool_not_allowlisted"


def _default_intent_plan_risk(tool_name: str, args: tuple[str, ...], argmap: Mapping[str, Any]) -> ToolboxRiskLevel:
    if tool_name not in TOOL_ALLOWLIST:
        return "low"
    if tool_name == "shell":
        command = _first_str(argmap.get("command"), argmap.get("cmd"), argmap.get("shell"), " ".join(args), default="")
        return "high" if _high_risk_marker_for_command(command) else "medium"
    if tool_name == "python":
        code = _first_str(argmap.get("code"), argmap.get("python"), argmap.get("content"), default="")
        return "high" if _high_risk_marker_for_command(code) else "medium"
    return _tool_risk_level(tool_name)


def _looks_like_python_expression(text: str) -> bool:
    raw = str(text or "").strip()
    if not raw or "\n" in raw:
        return False
    if re.search(r"[^0-9\s+\-*/%().]", raw):
        return False
    try:
        ast.parse(raw, mode="eval")
        return True
    except Exception:
        return False


def _coerce_llm_plan(raw: Mapping[str, Any], raw_text: str, *, source: str) -> ToolboxIntentPlan:
    action = _normalize_plan_action(raw.get("action") or raw.get("plan_action") or raw.get("decision"))
    tool_name = _coerce_tool_name(raw.get("tool") or raw.get("tool_name") or raw.get("name"))
    if action == "none":
        tool_name = "none"
    if action in {"execute", "confirm"} and tool_name == "none":
        action = "clarify"
    if tool_name not in TOOL_ALLOWLIST and tool_name != "none":
        action = "blocked"
    try:
        confidence = float(raw.get("confidence", 0.0))
    except Exception:
        confidence = 0.0
    if not 0.0 <= confidence <= 1.0:
        confidence = 0.0
    args, argmap, arg_error = _args_from_plan(tool_name, raw.get("args") if "args" in raw else raw.get("arguments"), raw)
    declared_risk = _normalize_risk(raw.get("risk") or raw.get("risk_level"), default=_default_intent_plan_risk(tool_name, args, argmap))
    if action == "execute" and (arg_error or confidence < 0.55):
        action = "clarify"
    if action == "execute" and declared_risk == "high":
        action = "confirm"
    command_text = _first_str(raw.get("command_text"), default="")
    if not command_text and tool_name in TOOL_ALLOWLIST:
        command_text = _build_command_text(tool_name, args, argmap)
    reply = _first_str(raw.get("reply"), raw.get("question"), raw.get("clarification"), default="")
    reason = _first_str(raw.get("reason"), arg_error, default="llm_intent_plan")[:240]
    return ToolboxIntentPlan(
        action=action,
        tool_name=tool_name,
        args=args,
        raw_text=raw_text,
        command_text=command_text,
        risk_level=declared_risk,
        confidence=confidence,
        reason=reason,
        source=source,
        reply=reply,
        raw_model_output=_redacted_raw_model_output(raw),
    )


def _extract_quoted(text: str) -> str:
    match = re.search(r"[‘'\"“](.*?)[’'\"”]", str(text or ""))
    return match.group(1).strip() if match else ""


def _extract_path_guess(text: str, *, default: str = ".") -> str:
    raw = str(text or "")
    path_match = re.search(r"([A-Za-z0-9_./-]+\.(?:py|md|txt|json|jsonl|ya?ml|toml|log|sh|ini|cfg|csv|html|css|js|ts|tsx|jsx))\b", raw)
    if path_match:
        return path_match.group(1).strip("，。,.；;：:")
    dir_match = re.search(r"\b((?:tmp|src|tests|docs|dist|logs|scripts|tools|data)(?:/[A-Za-z0-9_.-]+)*)\b", raw)
    if dir_match:
        return dir_match.group(1).strip("，。,.；;：:")
    quoted = _extract_quoted(raw)
    if quoted and "/" in quoted:
        return quoted
    return default


def _extract_python_calc_guess(text: str) -> str:
    raw = str(text or "").strip()
    if not raw:
        return ""
    candidates: list[str] = []
    patterns = (
        r".*?python\s*(?:算一下|算下|计算一下|计算|跑一下|运行一下)?",
        r".*?py\s*(?:算一下|算下|计算一下|计算|跑一下|运行一下)?",
        r".*?(?:算一下|算下|计算一下|计算)",
    )
    for pattern in patterns:
        candidate = re.sub(pattern, "", raw, count=1, flags=re.IGNORECASE).strip(" ：:，,。")
        if candidate and candidate != raw:
            candidates.append(candidate)
    expr_match = re.search(r"([0-9][0-9\s+\-*/%().]*[0-9)])", raw)
    if expr_match:
        candidates.append(expr_match.group(1).strip())
    for candidate in candidates:
        candidate = re.sub(r"^(?:一下|下|结果|等于|=)\s*", "", candidate.strip(), flags=re.IGNORECASE).strip(" ：:，,。")
        if _looks_like_python_expression(candidate):
            return candidate
    return ""


def _deterministic_safe_intent_parse(text: str) -> ToolboxIntentPlan | None:
    # Hotfix guardrail: a few unambiguous owner-private NL commands must not depend
    # on the formatter/LLM package, otherwise high-confidence clarifications can
    # shadow safe local tools.  Keep this narrow and only return low/medium tools.
    raw = str(text or "").strip()
    if not raw or _looks_like_chat_only(raw) or _should_skip_toolbox_nl_for_other_router(raw):
        return None
    lowered = raw.lower()
    if "python" in lowered or " py " in f" {lowered} " or any(word in raw for word in ("算一下", "算下", "计算一下", "计算")):
        expr = _extract_python_calc_guess(raw)
        if expr:
            code = f"print({expr})"
            return ToolboxIntentPlan("execute", "python", (), raw, f"python <<<\n{code}\n>>>", "medium", 0.91, "deterministic_python_expression", "local_hotfix")
    if any(word in raw for word in ("帮助", "怎么用", "能干嘛", "功能")) and ("工具箱" in raw or "toolbox" in lowered):
        return ToolboxIntentPlan("execute", "toolbox_status", (), raw, "toolbox_status", "low", 0.88, "deterministic_status", "local_hotfix")
    if ("nonebot" in lowered or "系统" in raw or "服务" in raw or "插件" in raw) and any(word in raw for word in ("状态", "健康", "自检", "有没有异常", "报错", "看下", "看一下")):
        return ToolboxIntentPlan("execute", "health", (), raw, "health", "low", 0.89, "deterministic_health_status", "local_hotfix")
    if any(word in raw for word in ("列目录", "列一下", "目录", "下面有什么", "里面有什么", "有什么")) or re.search(r"\b(ls|dir)\b", lowered):
        path = _extract_path_guess(raw)
        if path != "." or re.search(r"\b(ls|dir)\b", lowered):
            return ToolboxIntentPlan("execute", "list_dir", (path,), raw, f"list_dir {path}", "low", 0.88, "deterministic_list_dir", "local_hotfix")
    return None


def _extract_shell_guess(text: str) -> str:
    raw = str(text or "").strip()
    for marker in ("执行", "运行", "跑一下", "跑下", "跑", "命令"):
        idx = raw.find(marker)
        if idx >= 0:
            return raw[idx + len(marker):].strip(" ：:，,")
    return ""


def _fallback_rule_intent_parse(text: str) -> ToolboxIntentPlan:
    # 兜底只保障离线可测和 LLM 不可用时的可用性；主路径仍是 provider/model JSON plan。
    raw = str(text or "").strip()
    if not raw or _looks_like_chat_only(raw) or _should_skip_toolbox_nl_for_other_router(raw):
        return ToolboxIntentPlan("none", "none", (), raw, "", "low", 0.92, "ordinary_chat_or_other_router", "local_fallback")
    redline = _redline_plan_for_text(raw)
    if redline is not None:
        return redline
    lowered = raw.lower()
    if not _natural_tool_hint_present(raw):
        return ToolboxIntentPlan("none", "none", (), raw, "", "low", 0.70, "no_tool_hint", "local_fallback")
    if any(word in raw for word in ("帮助", "怎么用", "能干嘛", "功能")):
        return ToolboxIntentPlan("execute", "toolbox_status", (), raw, "toolbox_status", "low", 0.78, "fallback_status", "local_fallback")
    if any(word in raw for word in ("健康", "自检", "状态", "有没有异常", "报错情况", "系统状态", "服务状态")):
        return ToolboxIntentPlan("execute", "health", (), raw, "health", "low", 0.76, "fallback_health", "local_fallback")
    if re.search(r"\b(sha256|sha256sum|checksum|hash)\b", lowered):
        path = _extract_path_guess(raw)
        return ToolboxIntentPlan("execute", "sha256", (path,), raw, f"sha256 {path}", "low", 0.78, "fallback_sha256", "local_fallback")
    if any(word in raw for word in ("日志", "尾部", "tail")):
        path = _extract_path_guess(raw, default="dist/current_task_result.md")
        return ToolboxIntentPlan("execute", "log_tail", (path,), raw, f"log_tail {path}", "low", 0.74, "fallback_log_tail", "local_fallback")
    if any(word in raw for word in ("搜索", "搜", "grep", "查找包含")):
        query = _extract_quoted(raw) or _first_str(re.sub(r".*?(?:搜索|搜|grep|查找包含)", "", raw).strip(" ：:，,"), default="")
        path = _extract_path_guess(raw)
        if not query:
            return ToolboxIntentPlan("clarify", "grep", (), raw, "", "low", 0.50, "missing_query", "local_fallback", reply="要搜什么关键词？")
        return ToolboxIntentPlan("execute", "grep", (query, path), raw, f"grep {shlex.quote(query)} {path}", "low", 0.73, "fallback_grep", "local_fallback")
    if any(word in raw for word in ("查找文件", "找文件", "find")):
        pattern = _extract_quoted(raw) or "*"
        path = _extract_path_guess(raw)
        return ToolboxIntentPlan("execute", "find", (pattern, path), raw, f"find {shlex.quote(pattern)} {path}", "low", 0.72, "fallback_find", "local_fallback")
    if any(word in raw for word in ("列目录", "列一下", "目录", "下面有什么", "ls")):
        path = _extract_path_guess(raw)
        return ToolboxIntentPlan("execute", "list_dir", (path,), raw, f"list_dir {path}", "low", 0.76, "fallback_list_dir", "local_fallback")
    if any(word in raw for word in ("读取", "读", "打开", "看一下", "看看")):
        path = _extract_path_guess(raw)
        if path != ".":
            return ToolboxIntentPlan("execute", "read_file", (path,), raw, f"read_file {path}", "low", 0.72, "fallback_read_file", "local_fallback")
    if "python" in lowered or " py " in f" {lowered} " or any(word in raw for word in ("算一下", "计算")):
        code = raw
        for pattern in (r".*?python\s*", r".*?py\s*", r".*?算一下", r".*?计算"):
            candidate = re.sub(pattern, "", code, count=1, flags=re.IGNORECASE).strip(" ：:，,")
            if candidate != code:
                code = candidate
                break
        if code:
            code = re.sub(r"^(?:算一下|算下|计算一下|计算|一下|下)\s*", "", code.strip(), flags=re.IGNORECASE).strip(" ：:，,")
            if _looks_like_python_expression(code):
                code = f"print({code})"
            return ToolboxIntentPlan("execute", "python", (), raw, f"python <<<\n{code}\n>>>", "medium", 0.72, "fallback_python", "local_fallback")
    shell_cmd = _extract_shell_guess(raw)
    if shell_cmd:
        risk = "high" if _high_risk_marker_for_text(shell_cmd) else "medium"
        action = "confirm" if risk == "high" else "execute"
        return ToolboxIntentPlan(action, "shell", tuple(_split_command_text(shell_cmd)), raw, f"shell {shell_cmd}", risk, 0.70, "fallback_shell", "local_fallback")
    return ToolboxIntentPlan("clarify", "none", (), raw, "", "low", 0.45, "ambiguous_tool_request", "local_fallback", reply="你想让我用哪个工程工具？可以说读文件、搜关键词、列目录、跑命令或打包。")


def _build_intent_prompt(user_text: str, workspace_root: Path) -> list[dict[str, str]]:
    tools = {
        "low": list(LOW_RISK_TOOLS),
        "medium": list(MEDIUM_RISK_TOOLS),
        "executor": list(HIGH_RISK_TOOLS),
    }
    schema = {
        "schema_version": NL_SCHEMA_VERSION,
        "action": "execute|clarify|confirm|blocked|none",
        "tool": "one allowlisted tool name, or none",
        "risk_level": "low|medium|high",
        "confidence": 0.0,
        "args": {"path": "relative path", "query": "keyword", "command": "shell command", "content": "text"},
        "reason": "short reason",
        "reply": "clarification question when needed",
    }
    return [
        {
            "role": "system",
            "content": (
                "你是 Owner 工程工具箱自然语言 intent parser。只输出一个 JSON object，不要输出解释。"
                "主目标：判断 owner 私聊是否真的要调用本地工程工具；普通闲聊输出 action=none。"
                "能确定且 low/medium 风险时输出 execute；不确定输出 clarify；明显高危输出 confirm 或 blocked。"
                "禁止触碰 /opt/yangyang_nonebot、.env、token/key/secret/password、memories.jsonl、路径逃逸。"
                "用户不必固定句式，你要提取真实 intent 和参数。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "schema": schema,
                    "allowed_tools": tools,
                    "workspace_root_hint": workspace_root.as_posix(),
                    "user_text": user_text,
                },
                ensure_ascii=False,
            ),
        },
    ]


async def _call_intent_provider(provider: ToolboxIntentProvider, text: str, context: dict[str, Any]) -> Mapping[str, Any] | str:
    result = provider(text, context)
    if inspect.isawaitable(result):
        result = await result  # type: ignore[assignment]
    return result  # type: ignore[return-value]


async def parse_toolbox_intent_plan(
    text: str,
    config: Any,
    *,
    project_root: str | Path | None = None,
    intent_provider: ToolboxIntentProvider | None = None,
    model_router: Any | None = None,
) -> ToolboxIntentPlan:
    raw_text = str(text or "").strip()
    fixed = parse_toolbox_command(raw_text)
    if fixed is not None:
        return ToolboxIntentPlan(
            action="execute",
            tool_name=fixed.tool_name,
            args=fixed.args,
            raw_text=fixed.raw_text,
            command_text=fixed.command_text,
            risk_level=_tool_risk_level(fixed.tool_name),
            confidence=1.0,
            reason="fixed_toolbox_command",
            source="fixed_command",
        )
    if _should_skip_toolbox_nl_for_other_router(raw_text):
        return ToolboxIntentPlan("none", "none", (), raw_text, "", "low", 0.95, "other_owner_router", "pre_gate_rules")
    if _looks_like_chat_only(raw_text):
        return ToolboxIntentPlan("none", "none", (), raw_text, "", "low", 0.95, "ordinary_chat", "pre_gate_rules")

    redline = _redline_plan_for_text(raw_text)
    if redline is not None:
        return redline

    workspace_root = _resolve_workspace_root(config, project_root=project_root)
    context = {
        "schema_version": NL_SCHEMA_VERSION,
        "workspace_root": str(workspace_root),
        "allowed_tools": sorted(TOOL_ALLOWLIST),
        "risk_policy": "redline rules first; LLM parser primary; deterministic fallback if LLM unavailable or low confidence",
    }

    raw_plan: dict[str, Any] | None = None
    source = "llm_intent_provider"
    llm_primary_enabled = _config_get_bool(config, "owner_engineering_toolbox_llm_parser_primary_enabled", True)
    if llm_primary_enabled and intent_provider is not None:
        try:
            provider_output = await _call_intent_provider(intent_provider, raw_text, context)
            raw_plan = _mapping_from_provider_output(provider_output)
        except Exception as exc:
            raw_plan = {"action": "clarify", "tool": "none", "risk_level": "low", "confidence": 0.0, "reason": f"provider_exception:{exc.__class__.__name__}"}
    elif llm_primary_enabled and model_router is not None and _config_get_bool(config, "owner_engineering_toolbox_llm_parser_enabled", True):
        try:
            timeout = _config_get_int(config, "owner_engineering_toolbox_llm_parser_timeout_seconds", 12, minimum=1, maximum=60)
            tier = str(_config_get(config, "owner_engineering_toolbox_llm_parser_tier", "v4_flash") or "v4_flash")
            response_text, actual_tier = await asyncio.wait_for(
                model_router.call(tier, _build_intent_prompt(raw_text, workspace_root), temperature=0.0, session_id="owner_toolbox_nl", timeout_bucket="progress", interaction_phase="tool_intent_parse", allow_streaming=False),
                timeout=timeout,
            )
            source = f"llm_model_router:{actual_tier}"
            raw_plan = _mapping_from_provider_output(response_text)
        except Exception as exc:
            raw_plan = {"action": "clarify", "tool": "none", "risk_level": "low", "confidence": 0.0, "reason": f"model_parser_exception:{exc.__class__.__name__}"}

    deterministic = _deterministic_safe_intent_parse(raw_text)
    if raw_plan is not None:
        plan = _coerce_llm_plan(raw_plan, raw_text, source=source)
        if plan.action == "clarify":
            # LLM/provider may be overly cautious.  A narrow deterministic-safe plan
            # can rescue obvious commands like "用 python 算一下 1+1" or "nonebot 系统状态".
            if deterministic is not None:
                return deterministic
            if plan.confidence >= 0.55:
                return plan
        elif plan.action == "none" and deterministic is not None:
            return deterministic
        else:
            return plan
        # LLM/provider failed to produce a usable plan; keep working with a conservative local fallback.

    if deterministic is not None:
        return deterministic
    return _fallback_rule_intent_parse(raw_text)


def _command_from_intent_plan(plan: ToolboxIntentPlan) -> ToolboxCommand | None:
    if plan.tool_name not in TOOL_ALLOWLIST or plan.action not in {"execute", "confirm"}:
        return None
    command_text = plan.command_text or " ".join([plan.tool_name] + list(plan.args)).strip()
    raw_text = f"工具箱 {command_text}".strip()
    return ToolboxCommand(
        tool_name=plan.tool_name,
        raw_tool_name=plan.tool_name,
        args=plan.args,
        raw_text=raw_text,
        command_text=command_text,
    )


def _format_high_risk_confirm_reply(command: ToolboxCommand, gate: ToolboxGateResult) -> str:
    return _natural_block_message(gate.reason or "high_risk_requires_confirm", tool=command.tool_name, action="confirm")


def _format_plan_non_execute_reply(plan: ToolboxIntentPlan) -> str:
    if plan.action == "none":
        return ""
    return _natural_block_message(
        plan.reason,
        tool=plan.tool_name,
        action=plan.action,
        detail=plan.reply,
        raw_text=plan.raw_text,
    )


def _format_plan_raw_reply(plan: ToolboxIntentPlan) -> str:
    if plan.action == "none":
        return ""
    if plan.action == "clarify":
        detail = plan.reply or "我还不能确定要调用哪个工具，请补充 path/query/command/content。"
        return f"[owner_toolbox_nl] clarification_required reason={plan.reason} confidence={plan.confidence:.2f}\n{detail}"
    if plan.action == "confirm":
        return (
            f"[owner_toolbox_nl] high_risk_requires_confirm reason={plan.reason} risk={plan.risk_level} "
            f"tool={plan.tool_name} real_write=false real_execute=false\n"
            "高风险动作未直接执行。请拆成低风险检查步骤，或后续接入显式确认口令后再执行。"
        )
    return (
        f"[owner_toolbox_nl] blocked reason={plan.reason} risk={plan.risk_level} "
        f"tool={plan.tool_name} real_write=false real_execute=false"
    )


async def handle_owner_engineering_toolbox_message_nl_async(
    message: Any,
    config: Any,
    *,
    project_root: str | Path | None = None,
    intent_provider: ToolboxIntentProvider | None = None,
    result_formatter_provider: ToolboxResultFormatterProvider | None = None,
    model_router: Any | None = None,
    persona: str | None = None,
) -> ToolboxHandleResult:
    persona_name = _persona_from_config(config, persona)
    fixed = parse_toolbox_command(message)
    if fixed is not None:
        return handle_owner_engineering_toolbox_message(message, config, project_root=project_root, persona=persona_name)

    text = _message_text(message).strip()
    if not text:
        return ToolboxHandleResult(handled=False, allowed=False, reason="empty_message", reply="")
    if not _config_get_bool(config, "owner_engineering_toolbox_nl_enabled", True):
        return ToolboxHandleResult(handled=False, allowed=False, reason="nl_disabled", reply="")

    actor = _resolve_actor(message, config)
    if actor != "owner_private":
        if _natural_tool_hint_present(text) or _high_risk_marker_for_text(text):
            dummy = ToolboxCommand("none", "none", (), text, "")
            gate = evaluate_toolbox_gate(dummy, message, config, project_root=project_root)
            if str(getattr(message, "channel", "") or "") != "private":
                return ToolboxHandleResult(handled=True, allowed=False, reason="private_only", reply="", command=dummy, gate=gate)
            return ToolboxHandleResult(handled=True, allowed=False, reason="owner_only", reply="工具箱只在 owner 私聊可用。", command=dummy, gate=gate, raw_reply="工具箱不可用：owner_private_only。", formatted_text="工具箱只在 owner 私聊可用。")
        return ToolboxHandleResult(handled=False, allowed=False, reason="not_owner_private", reply="")

    plan = await parse_toolbox_intent_plan(text, config, project_root=project_root, intent_provider=intent_provider, model_router=model_router)
    if plan.action == "none":
        return ToolboxHandleResult(handled=False, allowed=False, reason=plan.reason, reply="", intent_plan=plan)

    command = _command_from_intent_plan(plan)
    if plan.action in {"clarify", "confirm", "blocked"} or command is None:
        gate = evaluate_toolbox_gate(command, message, config, project_root=project_root) if command is not None else None
        if command is not None and gate is not None:
            _write_audit_record(command, gate, None, config, success=False, error=plan.reason, duration_ms=0)
        raw_reply = _format_plan_raw_reply(plan)
        if command is not None and _raw_report_requested(command, config):
            reply = raw_reply
        else:
            base_reply = _format_plan_non_execute_reply(plan)
            reply = _format_natural_with_persona({"plan": plan, "base_text": base_reply}, persona=persona_name)
        return ToolboxHandleResult(
            handled=True,
            allowed=False,
            reason=plan.reason,
            reply=reply,
            tool_name=plan.tool_name if plan.tool_name != "none" else None,
            command=command,
            gate=gate,
            intent_plan=plan,
            raw_reply=raw_reply,
            formatted_text=reply,
        )

    gate = evaluate_toolbox_gate(command, message, config, project_root=project_root)
    if _risk_rank(plan.risk_level) >= _risk_rank("high"):
        _write_audit_record(command, gate, None, config, success=False, error="high_risk_requires_confirm", duration_ms=0)
        confirm_plan = ToolboxIntentPlan(
            action="confirm",
            tool_name=plan.tool_name,
            args=plan.args,
            raw_text=plan.raw_text,
            command_text=plan.command_text,
            risk_level="high",
            confidence=plan.confidence,
            reason="high_risk_requires_confirm",
            source=plan.source,
            raw_model_output=plan.raw_model_output,
        )
        raw_reply = _format_plan_raw_reply(confirm_plan)
        if _raw_report_requested(command, config):
            reply = raw_reply
        else:
            base_reply = _format_plan_non_execute_reply(confirm_plan)
            reply = _format_natural_with_persona({"plan": confirm_plan, "base_text": base_reply}, persona=persona_name)
        return ToolboxHandleResult(
            handled=True,
            allowed=False,
            reason="high_risk_requires_confirm",
            reply=reply,
            tool_name=command.tool_name,
            command=command,
            gate=gate,
            intent_plan=confirm_plan,
            raw_reply=raw_reply,
            formatted_text=reply,
        )
    if not gate.allowed:
        if gate.reason == "private_only":
            _write_audit_record(command, gate, None, config, success=False, error=gate.reason, duration_ms=0)
            return ToolboxHandleResult(handled=True, allowed=False, reason=gate.reason, reply="", tool_name=command.tool_name, command=command, gate=gate, intent_plan=plan)
        raw_reply = _format_gate_block_reply(gate, raw=True)
        if _raw_report_requested(command, config):
            reply = raw_reply
        else:
            base_reply = _format_high_risk_confirm_reply(command, gate) if gate.reason == "high_risk_requires_confirm" else _format_gate_block_reply(gate)
            reply = _format_natural_with_persona({"gate": gate, "base_text": base_reply}, persona=persona_name)
        _write_audit_record(command, gate, None, config, success=False, error=gate.reason, duration_ms=0)
        return ToolboxHandleResult(handled=True, allowed=False, reason=gate.reason, reply=reply, tool_name=command.tool_name, command=command, gate=gate, intent_plan=plan, raw_reply=raw_reply, formatted_text=reply)

    start_time = time.monotonic()
    execution: ToolboxExecutionResult | None = None
    try:
        execution = execute_toolbox_command(command, gate, config)
        raw_reply = _format_toolbox_raw_reply(gate, execution)
        reply = await format_toolbox_reply_async(
            gate,
            execution,
            command=command,
            config=config,
            persona=persona_name,
            model_router=model_router,
            result_formatter_provider=result_formatter_provider,
            original_text=text,
            plan=plan,
        )
        return ToolboxHandleResult(
            handled=True,
            allowed=execution.status in {"ok", "dry_run"},
            reason=execution.reason,
            reply=reply,
            tool_name=command.tool_name,
            command=command,
            gate=gate,
            execution=execution,
            intent_plan=plan,
            raw_reply=raw_reply,
            formatted_text=reply,
        )
    finally:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        _write_audit_record(
            command,
            gate,
            execution,
            config,
            success=bool(execution and execution.status == "ok"),
            error="" if execution and execution.status == "ok" else (execution.reason if execution else "tool_error"),
            duration_ms=duration_ms,
        )

def _tool_risk_level(tool_name: str) -> ToolboxRiskLevel:
    if tool_name in HIGH_RISK_TOOLS:
        return "high"
    if tool_name in MEDIUM_RISK_TOOLS:
        return "medium"
    return "low"


def _tool_gate_command_risk_level(command: ToolboxCommand | None) -> ToolboxRiskLevel:
    if command is None:
        return "low"
    risk = _tool_risk_level(command.tool_name)
    if command.tool_name in {"shell", "python"}:
        payload = _extract_payload(command.raw_text) if command.tool_name == "python" else _extract_command_after_tool(command.raw_text, command.raw_tool_name)
        if _high_risk_marker_for_command(payload):
            return "high"
        return "medium"
    return risk


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.resolve().relative_to(parent.resolve())
        return True
    except Exception:
        return False


def _is_forbidden_production_path(path: Path) -> bool:
    return _is_relative_to(path, FORBIDDEN_PRODUCTION_ROOT)


def _is_forbidden_workspace_root(path: Path) -> bool:
    try:
        resolved = Path(path).resolve()
    except Exception:
        return True
    if _is_forbidden_production_path(resolved):
        return True
    # A workspace root must be a scoped directory, not a broad filesystem/home root
    # or a path that already advertises sensitive material.
    if resolved == Path(resolved.anchor) or resolved.as_posix() in {"/root", "/home", "/tmp"}:
        return True
    return bool(_sensitive_marker_for_path(resolved.as_posix()))


def _resolve_workspace_root(config: Any, project_root: str | Path | None = None) -> Path:
    fallback = Path(project_root or PROJECT_ROOT).resolve()
    raw = str(_config_get(config, "owner_engineering_toolbox_workspace_root", "") or "").strip()
    if not raw:
        return fallback
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = fallback / candidate
    try:
        return candidate.resolve()
    except Exception:
        return fallback


def evaluate_toolbox_gate(
    command: ToolboxCommand | None,
    message: Any,
    config: Any,
    *,
    project_root: str | Path | None = None,
) -> ToolboxGateResult:
    workspace_root = _resolve_workspace_root(config, project_root=project_root)
    tool_name = str(getattr(command, "tool_name", "") or "").strip() or "unknown"
    risk = _tool_gate_command_risk_level(command)
    actor = _resolve_actor(message, config)

    if command is None:
        return _gate(False, "blocked", "no_command", actor, "none", "low", False, True, False, workspace_root)
    if actor != "owner_private":
        reason = "private_only" if str(getattr(message, "channel", "") or "") != "private" else "owner_only"
        return _gate(False, "blocked", reason, actor, tool_name, risk, False, True, False, workspace_root)
    if tool_name not in TOOL_ALLOWLIST:
        return _gate(False, "blocked", "tool_not_allowlisted", actor, tool_name, risk, False, True, False, workspace_root)
    if not _config_get_bool(config, "owner_engineering_toolbox_enabled", True):
        return _gate(False, "blocked", "toolbox_disabled", actor, tool_name, risk, False, True, False, workspace_root, blocked_by_config=True)
    if _is_forbidden_workspace_root(workspace_root) and tool_name != "toolbox_status":
        return _gate(False, "blocked", "forbidden_workspace_root", actor, tool_name, risk, False, True, False, workspace_root)

    if risk == "low":
        if not _config_get_bool(config, "owner_engineering_toolbox_low_risk_enabled", True):
            return _gate(False, "blocked", "low_risk_tools_disabled", actor, tool_name, risk, False, True, False, workspace_root, blocked_by_config=True)
        return _gate(True, "execute", "low_risk_allowed", actor, tool_name, risk, False, False, True, workspace_root)

    if risk == "medium":
        if tool_name in HIGH_RISK_TOOLS:
            executor_key = "owner_engineering_toolbox_shell_enabled" if tool_name == "shell" else "owner_engineering_toolbox_python_enabled"
            if _config_get_bool(config, executor_key, True):
                return _gate(True, "execute", "executor_allowed", actor, tool_name, risk, False, False, True, workspace_root)
            return _gate(False, "blocked", "executor_disabled", actor, tool_name, risk, True, True, False, workspace_root, blocked_by_config=True)
        if _config_get_bool(config, "owner_engineering_toolbox_write_enabled", True):
            return _gate(True, "execute", "write_tools_allowed", actor, tool_name, risk, False, False, True, workspace_root)
        return _gate(True, "dry_run", "write_tools_dry_run_require_confirm", actor, tool_name, risk, True, True, False, workspace_root, blocked_by_config=True)

    return _gate(False, "require_confirm", "high_risk_requires_confirm", actor, tool_name, risk, True, True, False, workspace_root)


def _resolve_actor(message: Any, config: Any) -> str:
    channel = str(getattr(message, "channel", "") or "").strip()
    if channel == "private" and _is_owner_message(message, config):
        return "owner_private"
    if channel == "private":
        return "private_non_owner"
    if channel == "group":
        return "group"
    return channel or "unknown"


def _gate(
    allowed: bool,
    mode: ToolboxGateMode,
    reason: str,
    actor: str,
    tool_name: str,
    risk: ToolboxRiskLevel,
    requires_confirm: bool,
    dry_run: bool,
    safe_to_execute: bool,
    workspace_root: Path,
    *,
    blocked_by_config: bool = False,
) -> ToolboxGateResult:
    return ToolboxGateResult(
        allowed=bool(allowed),
        mode=mode,
        reason=reason,
        actor=actor,
        tool_name=tool_name,
        risk_level=risk,
        requires_confirm=bool(requires_confirm),
        dry_run=bool(dry_run),
        safe_to_execute=bool(safe_to_execute),
        workspace_root=str(workspace_root),
        blocked_by_config=bool(blocked_by_config),
    )


def handle_owner_engineering_toolbox_message(
    message: Any,
    config: Any,
    *,
    project_root: str | Path | None = None,
    persona: str | None = None,
) -> ToolboxHandleResult:
    persona_name = _persona_from_config(config, persona)
    command = parse_toolbox_command(message)
    if command is None:
        return ToolboxHandleResult(handled=False, allowed=False, reason="not_toolbox_command", reply="")

    gate = evaluate_toolbox_gate(command, message, config, project_root=project_root)
    start_time = time.monotonic()
    execution: ToolboxExecutionResult | None = None
    if not gate.allowed and gate.reason == "private_only":
        # 群聊不可见：吞掉工具箱触发，不向群内暴露内部能力。
        _write_audit_record(command, gate, None, config, success=False, error=gate.reason, duration_ms=0)
        return ToolboxHandleResult(
            handled=True,
            allowed=False,
            reason=gate.reason,
            reply="",
            tool_name=command.tool_name,
            command=command,
            gate=gate,
        )
    if not gate.allowed:
        raw_reply = _format_gate_block_reply(gate, raw=True)
        if _raw_report_requested(command, config):
            reply = raw_reply
        else:
            base_reply = _format_high_risk_confirm_reply(command, gate) if gate.reason == "high_risk_requires_confirm" else _format_gate_block_reply(gate)
            reply = _format_natural_with_persona({"gate": gate, "base_text": base_reply}, persona=persona_name)
        _write_audit_record(command, gate, None, config, success=False, error=gate.reason, duration_ms=0)
        return ToolboxHandleResult(
            handled=True,
            allowed=False,
            reason=gate.reason,
            reply=reply,
            tool_name=command.tool_name,
            command=command,
            gate=gate,
            raw_reply=raw_reply,
            formatted_text=reply,
        )

    try:
        execution = execute_toolbox_command(command, gate, config)
        raw_reply = _format_toolbox_raw_reply(gate, execution)
        reply = format_toolbox_reply(gate, execution, command=command, config=config, persona=persona_name)
        return ToolboxHandleResult(
            handled=True,
            allowed=execution.status == "ok" or execution.status == "dry_run",
            reason=execution.reason,
            reply=reply,
            tool_name=command.tool_name,
            command=command,
            gate=gate,
            execution=execution,
            raw_reply=raw_reply,
            formatted_text=reply,
        )
    finally:
        duration_ms = int((time.monotonic() - start_time) * 1000)
        _write_audit_record(
            command,
            gate,
            execution,
            config,
            success=bool(execution and execution.status == "ok"),
            error="" if execution and execution.status == "ok" else (execution.reason if execution else "tool_error"),
            duration_ms=duration_ms,
        )


def execute_toolbox_command(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    if not gate.allowed:
        return _execution(command.tool_name, "blocked", gate.reason, gate.risk_level, gate.mode)
    tool_name = command.tool_name
    try:
        if tool_name == "toolbox_status":
            return _execute_status(command, gate, config)
        if tool_name == "list_dir":
            return _execute_list_dir(command, gate, config)
        if tool_name == "read_file":
            return _execute_read_file(command, gate, config)
        if tool_name == "grep":
            return _execute_grep(command, gate, config)
        if tool_name == "find":
            return _execute_find(command, gate, config)
        if tool_name == "health":
            return _execute_health(command, gate, config)
        if tool_name == "log_tail":
            return _execute_log_tail(command, gate, config)
        if tool_name == "sha256":
            return _execute_sha256(command, gate, config)
        if tool_name == "pack_archive":
            return _execute_pack_archive(command, gate, config)
        if tool_name in {"write_file", "append_file", "edit_file", "mkdir", "rm"}:
            if gate.mode == "dry_run" or gate.dry_run:
                return _execute_write_dry_run(command, gate, config)
            if tool_name == "write_file":
                return _execute_write_file(command, gate, config)
            if tool_name == "append_file":
                return _execute_append_file(command, gate, config)
            if tool_name == "edit_file":
                return _execute_edit_file(command, gate, config)
            if tool_name == "mkdir":
                return _execute_mkdir(command, gate, config)
            if tool_name == "rm":
                return _execute_rm(command, gate, config)
        if tool_name == "shell":
            return _execute_shell(command, gate, config)
        if tool_name == "python":
            return _execute_python(command, gate, config)
        return _execution(tool_name, "blocked", "tool_not_allowlisted", gate.risk_level, "blocked")
    except Exception as exc:  # pragma: no cover - defensive fail-closed.
        return _execution(tool_name, "blocked", f"tool_error:{exc.__class__.__name__}", gate.risk_level, "blocked")


def _execute_status(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    del command
    data = {
        "generated_at": _utc_now(),
        "enabled": _config_get_bool(config, "owner_engineering_toolbox_enabled", True),
        "owner_private_only": True,
        "group_visible": False,
        "non_owner_private_available": False,
        "workspace_root": _display_workspace_root(Path(gate.workspace_root)),
        "low_risk_enabled": _config_get_bool(config, "owner_engineering_toolbox_low_risk_enabled", True),
        "write_enabled": _config_get_bool(config, "owner_engineering_toolbox_write_enabled", True),
        "shell_enabled": _config_get_bool(config, "owner_engineering_toolbox_shell_enabled", True),
        "python_enabled": _config_get_bool(config, "owner_engineering_toolbox_python_enabled", True),
        "executor_enabled": _config_get_bool(config, "owner_engineering_toolbox_shell_enabled", True) or _config_get_bool(config, "owner_engineering_toolbox_python_enabled", True),
        "timeout_seconds": _config_get_int(config, "owner_engineering_toolbox_timeout_seconds", DEFAULT_EXEC_TIMEOUT_SECONDS, minimum=1, maximum=300),
        "max_output_chars": _config_get_int(config, "owner_engineering_toolbox_max_output_chars", DEFAULT_MAX_OUTPUT_CHARS, minimum=200, maximum=50000),
        "allowed_low_risk_tools": list(LOW_RISK_TOOLS),
        "write_tools": list(MEDIUM_RISK_TOOLS),
        "executor_tools": list(HIGH_RISK_TOOLS),
        "boundaries": {
            "no_opt_yangyang_nonebot": True,
            "no_runtime_config_env_write": True,
            "no_service_restart": True,
            "no_production_memories_write": True,
            "sensitive_paths_blocked": True,
            "dynamic_tokens_redacted": True,
        },
    }
    output = (
        "工具箱 full v1 状态\n"
        f"enabled={_bool_text(data['enabled'])} owner_private_only=true group_visible=false non_owner_private_available=false\n"
        f"workspace_root={data['workspace_root']} timeout_seconds={data['timeout_seconds']} max_output_chars={data['max_output_chars']}\n"
        "low_risk_tools=toolbox_status,list_dir,read_file,grep,find,health,log_tail,sha256\n"
        f"write_enabled={_bool_text(data['write_enabled'])} shell_enabled={_bool_text(data['shell_enabled'])} python_enabled={_bool_text(data['python_enabled'])} executor_enabled={_bool_text(data['executor_enabled'])} host_action_executed=false\n"
        "tools=shell,python,write,append,read,edit,mkdir,rm,pack,sha256,list,grep,find\n"
        "boundaries: no_opt_yangyang_nonebot=true no_runtime_config_env_write=true no_service_restart=true "
        "no_production_memories_write=true sensitive_paths_blocked=true dynamic_tokens_redacted=true"
    )
    return _execution("toolbox_status", "ok", "status_ok", gate.risk_level, gate.mode, output=output, data=data)


def _execute_list_dir(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    rel = command.args[0] if command.args else "."
    resolved = _resolve_user_path(rel, gate)
    if not resolved.ok:
        return _execution("list_dir", "blocked", resolved.reason, gate.risk_level, "blocked", output=resolved.reason)
    path = resolved.path
    if path is None or not path.exists():
        return _execution("list_dir", "blocked", "path_not_found", gate.risk_level, "blocked")
    if not path.is_dir():
        return _execution("list_dir", "blocked", "not_directory", gate.risk_level, "blocked")
    max_entries = _config_get_int(config, "owner_engineering_toolbox_max_list_entries", DEFAULT_MAX_LIST_ENTRIES, minimum=1, maximum=500)
    entries = []
    hidden_count = 0
    for child in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
        rel_child = _safe_rel(child, Path(gate.workspace_root))
        if _sensitive_marker_for_path(rel_child):
            hidden_count += 1
            continue
        marker = "dir" if child.is_dir() else "file"
        try:
            size = child.stat().st_size if child.is_file() else 0
        except Exception:
            size = 0
        entries.append(f"{marker}\t{rel_child}\t{size}")
        if len(entries) >= max_entries:
            break
    truncated = len(entries) >= max_entries
    header = f"list_dir path={resolved.rel_display} entries={len(entries)} hidden_sensitive={hidden_count} truncated={_bool_text(truncated)}"
    return _execution("list_dir", "ok", "list_ok", gate.risk_level, gate.mode, output="\n".join([header] + entries), data={"entries": len(entries), "hidden_sensitive": hidden_count, "truncated": truncated})


def _execute_read_file(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    if not command.args:
        return _execution("read_file", "blocked", "missing_path", gate.risk_level, "blocked")
    rel = command.args[0]
    start_line = _parse_positive_int(command.args[1], 1) if len(command.args) >= 2 else 1
    requested_lines = _parse_positive_int(command.args[2], DEFAULT_MAX_READ_LINES) if len(command.args) >= 3 else DEFAULT_MAX_READ_LINES
    max_lines = _config_get_int(config, "owner_engineering_toolbox_max_read_lines", DEFAULT_MAX_READ_LINES, minimum=1, maximum=1000)
    line_count = min(requested_lines, max_lines)
    max_bytes = _config_get_int(config, "owner_engineering_toolbox_max_read_bytes", DEFAULT_MAX_READ_BYTES, minimum=1, maximum=1024 * 1024)
    resolved = _resolve_user_path(rel, gate, require_text_file=True)
    if not resolved.ok:
        return _execution("read_file", "blocked", resolved.reason, gate.risk_level, "blocked", output=resolved.reason)
    path = resolved.path
    if path is None or not path.exists():
        return _execution("read_file", "blocked", "path_not_found", gate.risk_level, "blocked")
    if not path.is_file():
        return _execution("read_file", "blocked", "not_file", gate.risk_level, "blocked")
    data = path.read_bytes()
    size_bytes = len(data)
    byte_truncated = size_bytes > max_bytes
    text = data[:max_bytes].decode("utf-8", errors="replace")
    lines = text.splitlines()
    start_idx = max(0, start_line - 1)
    selected = lines[start_idx : start_idx + line_count]
    line_truncated = len(lines) > start_idx + len(selected)
    numbered = [f"{start_idx + idx + 1}: {_redact_sensitive_text(line)}" for idx, line in enumerate(selected)]
    header = (
        f"read_file path={resolved.rel_display} start_line={start_line} requested_lines={requested_lines} "
        f"returned_lines={len(selected)} max_lines={max_lines} size_bytes={size_bytes} max_bytes={max_bytes} "
        f"byte_truncated={_bool_text(byte_truncated)} line_truncated={_bool_text(line_truncated)}"
    )
    return _execution(
        "read_file",
        "ok",
        "read_ok",
        gate.risk_level,
        gate.mode,
        output="\n".join([header] + numbered),
        data={"returned_lines": len(selected), "byte_truncated": byte_truncated, "line_truncated": line_truncated, "size_bytes": size_bytes},
    )


def _execute_grep(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    if not command.args:
        return _execution("grep", "blocked", "missing_query", gate.risk_level, "blocked")
    query = command.args[0]
    rel = command.args[1] if len(command.args) >= 2 else "."
    max_results = _config_get_int(config, "owner_engineering_toolbox_max_grep_results", DEFAULT_MAX_GREP_RESULTS, minimum=1, maximum=500)
    max_files = _config_get_int(config, "owner_engineering_toolbox_max_grep_files", DEFAULT_MAX_GREP_FILES, minimum=1, maximum=2000)
    max_bytes = _config_get_int(config, "owner_engineering_toolbox_max_read_bytes", DEFAULT_MAX_READ_BYTES, minimum=1, maximum=1024 * 1024)
    resolved = _resolve_user_path(rel, gate)
    if not resolved.ok:
        return _execution("grep", "blocked", resolved.reason, gate.risk_level, "blocked", output=resolved.reason)
    path = resolved.path
    if path is None or not path.exists():
        return _execution("grep", "blocked", "path_not_found", gate.risk_level, "blocked")
    root = Path(gate.workspace_root)
    files = _iter_text_files(path, root=root, max_files=max_files)
    results: list[str] = []
    searched_files = 0
    skipped_sensitive = 0
    for file_path, skipped_reason in files:
        if skipped_reason:
            skipped_sensitive += 1
            continue
        searched_files += 1
        text = file_path.read_bytes()[:max_bytes].decode("utf-8", errors="replace")
        for line_no, line in enumerate(text.splitlines(), start=1):
            if query.lower() not in line.lower():
                continue
            rel_file = _safe_rel(file_path, root)
            snippet = _redact_sensitive_text(line.strip())[:180]
            results.append(f"{rel_file}:{line_no}: {snippet}")
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break
    truncated = len(results) >= max_results
    header = (
        f"grep query_sha256_16={_hash16(query)} path={resolved.rel_display} results={len(results)} "
        f"max_results={max_results} searched_files={searched_files} skipped_sensitive={skipped_sensitive} truncated={_bool_text(truncated)}"
    )
    return _execution("grep", "ok", "grep_ok", gate.risk_level, gate.mode, output="\n".join([header] + results), data={"results": len(results), "truncated": truncated, "searched_files": searched_files, "skipped_sensitive": skipped_sensitive})


def _execute_find(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    pattern = command.args[0] if command.args else "*"
    rel = command.args[1] if len(command.args) >= 2 else "."
    max_entries = _config_get_int(config, "owner_engineering_toolbox_max_list_entries", DEFAULT_MAX_LIST_ENTRIES, minimum=1, maximum=500)
    resolved = _resolve_user_path(rel, gate)
    if not resolved.ok:
        return _execution("find", "blocked", resolved.reason, gate.risk_level, "blocked", output=resolved.reason)
    path = resolved.path
    if path is None or not path.exists():
        return _execution("find", "blocked", "path_not_found", gate.risk_level, "blocked")
    root = Path(gate.workspace_root)
    hits: list[str] = []
    skipped_sensitive = 0
    candidates = [path] if path.is_file() else sorted(path.rglob("*"), key=lambda item: _safe_rel(item, root))
    for item in candidates:
        rel_item = _safe_rel(item, root)
        if _sensitive_marker_for_path(rel_item):
            skipped_sensitive += 1
            continue
        if fnmatch.fnmatch(item.name, pattern) or fnmatch.fnmatch(rel_item, pattern):
            hits.append(f"{'dir' if item.is_dir() else 'file'}\t{rel_item}")
        if len(hits) >= max_entries:
            break
    truncated = len(hits) >= max_entries
    header = f"find pattern={_redact_sensitive_text(pattern)} path={resolved.rel_display} results={len(hits)} max_results={max_entries} skipped_sensitive={skipped_sensitive} truncated={_bool_text(truncated)}"
    return _execution("find", "ok", "find_ok", gate.risk_level, gate.mode, output="\n".join([header] + hits), data={"results": len(hits), "truncated": truncated})


def _execute_health(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    del command, config
    if build_readonly_health_snapshot is None:
        output = "health status=WARN builder_unavailable=true read_only=true workspace_only=true executor_enabled=false"
        return _execution("health", "ok", "health_builder_unavailable", gate.risk_level, gate.mode, output=output)
    snapshot = build_readonly_health_snapshot(project_root=Path(gate.workspace_root), plugin_loaded_marker=True, handler_available=True)  # type: ignore[misc]
    gate_state = dict(snapshot.get("gate_state") or {})
    recent = dict(snapshot.get("recent_errors") or {})
    baseline = dict(snapshot.get("baseline") or {})
    effects = dict(snapshot.get("external_effects") or {})
    output = (
        f"health status={snapshot.get('overall_status') or 'unknown'} schema={snapshot.get('schema_version') or '-'} read_only=true workspace_only=true\n"
        f"gate owner_private_only={_bool_text(gate_state.get('owner_private_only'))} group_exposure={_bool_text(gate_state.get('group_exposure'))} "
        f"high_risk_blocked={_bool_text(gate_state.get('high_risk_blocked'))} executor_enabled={_bool_text(gate_state.get('executor_enabled'))}\n"
        f"recent_errors status={recent.get('status') or 'unknown'} error_markers={recent.get('error_marker_count', 0)} tracebacks={recent.get('traceback_marker_count', 0)} failed_tests={recent.get('failed_test_marker_count', 0)}\n"
        f"baseline conclusion={baseline.get('conclusion') or 'unknown'} date={baseline.get('baseline_date') or '-'}\n"
        f"effects shell_used={_bool_text(effects.get('shell_used'))} network_used={_bool_text(effects.get('network_used'))} host_action_executed={_bool_text(effects.get('host_action_executed'))}"
    )
    return _execution("health", "ok", "health_ok", gate.risk_level, gate.mode, output=output, data={"overall_status": snapshot.get("overall_status"), "schema_version": snapshot.get("schema_version")})


def _execute_log_tail(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    rel = command.args[0] if command.args else "dist/current_task_result.md"
    requested = _parse_positive_int(command.args[1], DEFAULT_MAX_TAIL_LINES) if len(command.args) >= 2 else DEFAULT_MAX_TAIL_LINES
    max_tail = _config_get_int(config, "owner_engineering_toolbox_max_tail_lines", DEFAULT_MAX_TAIL_LINES, minimum=1, maximum=300)
    line_count = min(requested, max_tail)
    resolved = _resolve_user_path(rel, gate, require_text_file=True)
    if not resolved.ok:
        return _execution("log_tail", "blocked", resolved.reason, gate.risk_level, "blocked", output=resolved.reason)
    path = resolved.path
    if path is None or not path.exists():
        return _execution("log_tail", "blocked", "controlled_log_source_unavailable", gate.risk_level, "blocked")
    if not path.is_file():
        return _execution("log_tail", "blocked", "not_file", gate.risk_level, "blocked")
    max_bytes = _config_get_int(config, "owner_engineering_toolbox_max_read_bytes", DEFAULT_MAX_READ_BYTES, minimum=1, maximum=1024 * 1024)
    text = path.read_bytes()[-max_bytes:].decode("utf-8", errors="replace")
    lines = text.splitlines()[-line_count:]
    redacted = [_redact_sensitive_text(line) for line in lines]
    header = f"log_tail path={resolved.rel_display} returned_lines={len(redacted)} max_tail_lines={max_tail} raw_log_body_output=false"
    return _execution("log_tail", "ok", "tail_ok", gate.risk_level, gate.mode, output="\n".join([header] + redacted), data={"returned_lines": len(redacted)})


def _execute_sha256(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    del config
    if not command.args:
        return _execution("sha256", "blocked", "missing_path", gate.risk_level, "blocked")
    resolved = _resolve_user_path(command.args[0], gate)
    if not resolved.ok:
        return _execution("sha256", "blocked", resolved.reason, gate.risk_level, "blocked", output=resolved.reason)
    path = resolved.path
    if path is None or not path.exists():
        return _execution("sha256", "blocked", "path_not_found", gate.risk_level, "blocked")
    if not path.is_file():
        return _execution("sha256", "blocked", "not_file", gate.risk_level, "blocked")
    digest = _sha256_file(path)
    output = f"sha256 path={resolved.rel_display} sha256={digest}"
    return _execution("sha256", "ok", "sha256_ok", gate.risk_level, gate.mode, output=output, data={"sha256": digest, "path": resolved.rel_display})


def _execute_pack_archive(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    rel = command.args[0] if command.args else "."
    max_files = _config_get_int(config, "owner_engineering_toolbox_max_pack_files", DEFAULT_MAX_PACK_FILES, minimum=1, maximum=5000)
    resolved = _resolve_user_path(rel, gate)
    if not resolved.ok:
        return _execution("pack_archive", "blocked", resolved.reason, gate.risk_level, "blocked", output=resolved.reason)
    path = resolved.path
    if path is None or not path.exists():
        return _execution("pack_archive", "blocked", "path_not_found", gate.risk_level, "blocked")
    root = Path(gate.workspace_root).resolve()
    export_dir = (root / "dist" / "toolbox_exports").resolve()
    if not _is_relative_to(export_dir, root):
        return _execution("pack_archive", "blocked", "path_escape_blocked", gate.risk_level, "blocked")
    export_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", path.name or "workspace").strip("._") or "workspace"
    archive_path = export_dir / f"toolbox_{base_name}_{ts}.tar.gz"
    files: list[Path] = []
    skipped_sensitive = 0
    if path.is_file():
        marker = _sensitive_marker_for_path(_safe_rel(path, root))
        if marker:
            return _execution("pack_archive", "blocked", f"sensitive_path_blocked:{marker}", gate.risk_level, "blocked")
        files = [path]
    else:
        for file_path in sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: _safe_rel(item, root)):
            rel_file = _safe_rel(file_path, root)
            marker = _sensitive_marker_for_path(rel_file)
            if marker:
                skipped_sensitive += 1
                continue
            if _is_relative_to(file_path, export_dir) or "/.toolbox_trash/" in f"/{rel_file}":
                continue
            files.append(file_path)
            if len(files) >= max_files:
                break
    if not files:
        return _execution("pack_archive", "blocked", "no_files_to_pack", gate.risk_level, "blocked")
    with tarfile.open(archive_path, "w:gz") as tf:
        for file_path in files:
            tf.add(file_path, arcname=_safe_rel(file_path, root), recursive=False)
    digest = _sha256_file(archive_path)
    sha_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    sha_path.write_text(f"{digest}  {archive_path.name}\n", encoding="utf-8")
    truncated = len(files) >= max_files
    output = (
        f"pack_archive path={resolved.rel_display} archive={_safe_rel(archive_path, root)} sha256={digest} "
        f"files={len(files)} max_files={max_files} skipped_sensitive={skipped_sensitive} truncated={_bool_text(truncated)} archive_written=true"
    )
    return _execution("pack_archive", "ok", "pack_ok", gate.risk_level, gate.mode, real_write=True, output=output, data={"archive": _safe_rel(archive_path, root), "sha256": digest, "files": len(files)})


def _execute_write_dry_run(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    del config
    rel = command.args[0] if command.args else "."
    resolved = _resolve_user_path(rel, gate)
    if not resolved.ok:
        return _execution(command.tool_name, "blocked", resolved.reason, gate.risk_level, "blocked", output=resolved.reason)
    content = _extract_payload(command.raw_text) if command.tool_name in {"write_file", "append_file"} else " ".join(command.args[1:])
    output = (
        f"{command.tool_name} status=dry_run path={resolved.rel_display} requires_confirm=true dry_run=true "
        f"real_write=false preview_sha256_16={_hash16(content)} production_runtime_config_write=false production_memories_write=false"
    )
    return _execution(command.tool_name, "dry_run", "write_dry_run_only", gate.risk_level, "dry_run", output=output, data={"real_write": False, "requires_confirm": True})


def _execute_write_file(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    del config
    if not command.args:
        return _execution("write_file", "blocked", "missing_path", gate.risk_level, "blocked")
    resolved = _resolve_user_path(command.args[0], gate, for_write=True)
    if not resolved.ok:
        return _execution("write_file", "blocked", resolved.reason, gate.risk_level, "blocked", output=resolved.reason)
    path = resolved.path
    if path is None:
        return _execution("write_file", "blocked", "invalid_path", gate.risk_level, "blocked")
    content = _extract_payload(command.raw_text)
    if content == "" and len(command.args) > 1:
        content = " ".join(command.args[1:])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    output = f"write_file path={resolved.rel_display} bytes={len(content.encode('utf-8'))} real_write=true"
    return _execution("write_file", "ok", "write_ok", gate.risk_level, gate.mode, real_write=True, output=output, data={"path": resolved.rel_display})


def _execute_append_file(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    del config
    if not command.args:
        return _execution("append_file", "blocked", "missing_path", gate.risk_level, "blocked")
    resolved = _resolve_user_path(command.args[0], gate, for_write=True)
    if not resolved.ok:
        return _execution("append_file", "blocked", resolved.reason, gate.risk_level, "blocked", output=resolved.reason)
    path = resolved.path
    if path is None:
        return _execution("append_file", "blocked", "invalid_path", gate.risk_level, "blocked")
    content = _extract_payload(command.raw_text)
    if content == "" and len(command.args) > 1:
        content = " ".join(command.args[1:])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(content)
    output = f"append_file path={resolved.rel_display} bytes={len(content.encode('utf-8'))} real_write=true"
    return _execution("append_file", "ok", "append_ok", gate.risk_level, gate.mode, real_write=True, output=output, data={"path": resolved.rel_display})


def _execute_edit_file(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    del config
    if not command.args:
        return _execution("edit_file", "blocked", "missing_path", gate.risk_level, "blocked")
    resolved = _resolve_user_path(command.args[0], gate, require_text_file=True, for_write=True)
    if not resolved.ok:
        return _execution("edit_file", "blocked", resolved.reason, gate.risk_level, "blocked", output=resolved.reason)
    path = resolved.path
    if path is None or not path.exists():
        return _execution("edit_file", "blocked", "path_not_found", gate.risk_level, "blocked")
    if not path.is_file():
        return _execution("edit_file", "blocked", "not_file", gate.risk_level, "blocked")
    parsed = _extract_old_new_blocks(command.raw_text)
    if parsed is None:
        return _execution("edit_file", "blocked", "missing_old_new_blocks", gate.risk_level, "blocked")
    old, new_text = parsed
    body = path.read_text(encoding="utf-8", errors="replace")
    if old not in body:
        return _execution("edit_file", "blocked", "old_text_not_found", gate.risk_level, "blocked")
    updated = body.replace(old, new_text, 1)
    path.write_text(updated, encoding="utf-8")
    output = f"edit_file path={resolved.rel_display} replacements=1 old_sha256_16={_hash16(old)} new_sha256_16={_hash16(new_text)} real_write=true"
    return _execution("edit_file", "ok", "edit_ok", gate.risk_level, gate.mode, real_write=True, output=output, data={"path": resolved.rel_display, "replacements": 1})


def _execute_mkdir(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    del config
    if not command.args:
        return _execution("mkdir", "blocked", "missing_path", gate.risk_level, "blocked")
    resolved = _resolve_user_path(command.args[0], gate, for_write=True)
    if not resolved.ok:
        return _execution("mkdir", "blocked", resolved.reason, gate.risk_level, "blocked", output=resolved.reason)
    path = resolved.path
    if path is None:
        return _execution("mkdir", "blocked", "invalid_path", gate.risk_level, "blocked")
    path.mkdir(parents=True, exist_ok=True)
    output = f"mkdir path={resolved.rel_display} real_write=true"
    return _execution("mkdir", "ok", "mkdir_ok", gate.risk_level, gate.mode, real_write=True, output=output, data={"path": resolved.rel_display})


def _execute_rm(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    del config
    if not command.args:
        return _execution("rm", "blocked", "missing_path", gate.risk_level, "blocked")
    resolved = _resolve_user_path(command.args[0], gate, for_write=True)
    if not resolved.ok:
        return _execution("rm", "blocked", resolved.reason, gate.risk_level, "blocked", output=resolved.reason)
    path = resolved.path
    if path is None or not path.exists():
        return _execution("rm", "blocked", "path_not_found", gate.risk_level, "blocked")
    root = Path(gate.workspace_root).resolve()
    if path == root:
        return _execution("rm", "blocked", "cannot_trash_workspace_root", gate.risk_level, "blocked")
    trash_dir = root / ".toolbox_trash"
    trash_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = trash_dir / f"{ts}_{path.name}"
    counter = 1
    while dest.exists():
        dest = trash_dir / f"{ts}_{counter}_{path.name}"
        counter += 1
    shutil.move(str(path), str(dest))
    output = f"rm path={resolved.rel_display} trashed_to={_safe_rel(dest, root)} hard_delete=false real_write=true"
    return _execution("rm", "ok", "trash_ok", gate.risk_level, gate.mode, real_write=True, output=output, data={"path": resolved.rel_display, "trashed_to": _safe_rel(dest, root)})


def _execute_shell(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    if not _config_get_bool(config, "owner_engineering_toolbox_shell_enabled", True):
        return _execution("shell", "blocked", "executor_disabled", gate.risk_level, "blocked", output="executor_enabled=false host_action_executed=false")
    cmd = _extract_command_after_tool(command.raw_text, command.raw_tool_name).strip()
    if not cmd:
        return _execution("shell", "blocked", "missing_command", gate.risk_level, "blocked")
    forbidden_reason = _forbidden_command_reason(cmd, Path(gate.workspace_root))
    if forbidden_reason:
        return _execution("shell", "blocked", forbidden_reason, gate.risk_level, "blocked", output=forbidden_reason)
    timeout = _config_get_int(config, "owner_engineering_toolbox_timeout_seconds", DEFAULT_EXEC_TIMEOUT_SECONDS, minimum=1, maximum=300)
    max_chars = _config_get_int(config, "owner_engineering_toolbox_max_output_chars", DEFAULT_MAX_OUTPUT_CHARS, minimum=200, maximum=50000)
    env = {key: value for key, value in os.environ.items() if not _looks_sensitive_name(key)}
    try:
        cp = subprocess.run(cmd, shell=True, cwd=gate.workspace_root, text=True, capture_output=True, timeout=timeout, env=env)
        combined = (cp.stdout or "") + (("\n[stderr]\n" + cp.stderr) if cp.stderr else "")
        output_body, truncated = _truncate_output(_redact_sensitive_text(combined), max_chars)
        status = "ok" if cp.returncode == 0 else "error"
        reason = "shell_ok" if cp.returncode == 0 else f"shell_exit_{cp.returncode}"
        header = f"shell returncode={cp.returncode} timeout_seconds={timeout} output_truncated={_bool_text(truncated)} real_execute=true"
        return _execution("shell", status, reason, gate.risk_level, gate.mode, real_execute=True, output="\n".join([header, output_body]).strip(), data={"returncode": cp.returncode, "truncated": truncated})
    except subprocess.TimeoutExpired as exc:
        partial = ((exc.stdout or "") if isinstance(exc.stdout, str) else "") + (("\n[stderr]\n" + exc.stderr) if isinstance(exc.stderr, str) and exc.stderr else "")
        output_body, truncated = _truncate_output(_redact_sensitive_text(partial), max_chars)
        header = f"shell timeout=true timeout_seconds={timeout} output_truncated={_bool_text(truncated)} real_execute=true"
        return _execution("shell", "timeout", "timeout", gate.risk_level, gate.mode, real_execute=True, output="\n".join([header, output_body]).strip(), data={"timeout": timeout})


def _execute_python(command: ToolboxCommand, gate: ToolboxGateResult, config: Any) -> ToolboxExecutionResult:
    if not _config_get_bool(config, "owner_engineering_toolbox_python_enabled", True):
        return _execution("python", "blocked", "executor_disabled", gate.risk_level, "blocked", output="executor_enabled=false host_action_executed=false")
    code = _extract_payload(command.raw_text)
    if not code:
        code = _extract_command_after_tool(command.raw_text, command.raw_tool_name)
    if not code.strip():
        return _execution("python", "blocked", "missing_code", gate.risk_level, "blocked")
    forbidden_reason = _forbidden_command_reason(code, Path(gate.workspace_root))
    if forbidden_reason:
        return _execution("python", "blocked", forbidden_reason, gate.risk_level, "blocked", output=forbidden_reason)
    timeout = _config_get_int(config, "owner_engineering_toolbox_timeout_seconds", DEFAULT_EXEC_TIMEOUT_SECONDS, minimum=1, maximum=300)
    max_chars = _config_get_int(config, "owner_engineering_toolbox_max_output_chars", DEFAULT_MAX_OUTPUT_CHARS, minimum=200, maximum=50000)
    env = {key: value for key, value in os.environ.items() if not _looks_sensitive_name(key)}
    try:
        cp = subprocess.run(["python3", "-c", code], cwd=gate.workspace_root, text=True, capture_output=True, timeout=timeout, env=env)
        combined = (cp.stdout or "") + (("\n[stderr]\n" + cp.stderr) if cp.stderr else "")
        output_body, truncated = _truncate_output(_redact_sensitive_text(combined), max_chars)
        status = "ok" if cp.returncode == 0 else "error"
        reason = "python_ok" if cp.returncode == 0 else f"python_exit_{cp.returncode}"
        header = f"python returncode={cp.returncode} timeout_seconds={timeout} output_truncated={_bool_text(truncated)} real_execute=true"
        return _execution("python", status, reason, gate.risk_level, gate.mode, real_execute=True, output="\n".join([header, output_body]).strip(), data={"returncode": cp.returncode, "truncated": truncated})
    except subprocess.TimeoutExpired as exc:
        partial = ((exc.stdout or "") if isinstance(exc.stdout, str) else "") + (("\n[stderr]\n" + exc.stderr) if isinstance(exc.stderr, str) and exc.stderr else "")
        output_body, truncated = _truncate_output(_redact_sensitive_text(partial), max_chars)
        header = f"python timeout=true timeout_seconds={timeout} output_truncated={_bool_text(truncated)} real_execute=true"
        return _execution("python", "timeout", "timeout", gate.risk_level, gate.mode, real_execute=True, output="\n".join([header, output_body]).strip(), data={"timeout": timeout})


def _execution(
    tool_name: str,
    status: str,
    reason: str,
    risk_level: ToolboxRiskLevel,
    mode: ToolboxGateMode,
    *,
    real_write: bool = False,
    real_execute: bool = False,
    output: str = "",
    data: dict[str, Any] | None = None,
) -> ToolboxExecutionResult:
    return ToolboxExecutionResult(
        tool_name=tool_name,
        status=status,
        reason=reason,
        risk_level=risk_level,
        mode=mode,
        real_write=bool(real_write),
        real_execute=bool(real_execute),
        output=output,
        data=data,
    )


@dataclass(frozen=True)
class _ResolvedPath:
    ok: bool
    reason: str
    path: Path | None
    rel_display: str


def _resolve_user_path(raw_path: str, gate: ToolboxGateResult, *, require_text_file: bool = False, for_write: bool = False) -> _ResolvedPath:
    raw = str(raw_path or "").strip() or "."
    if "\x00" in raw:
        return _ResolvedPath(False, "invalid_path", None, raw)
    raw_path_obj = Path(raw)
    if any(part == ".." for part in raw_path_obj.parts):
        return _ResolvedPath(False, "path_traversal_blocked", None, raw)
    workspace_root = Path(gate.workspace_root).resolve()
    candidate = raw_path_obj if raw_path_obj.is_absolute() else workspace_root / raw_path_obj
    try:
        resolved = candidate.resolve()
    except Exception:
        return _ResolvedPath(False, "invalid_path", None, raw)
    if _is_forbidden_production_path(resolved):
        return _ResolvedPath(False, "production_path_blocked", None, raw)
    if not _is_relative_to(resolved, workspace_root):
        return _ResolvedPath(False, "path_escape_blocked", None, raw)
    rel_display = _safe_rel(resolved, workspace_root)
    sensitive = _sensitive_marker_for_path(rel_display)
    if sensitive:
        return _ResolvedPath(False, f"sensitive_path_blocked:{sensitive}", None, rel_display)
    if (require_text_file or for_write) and resolved.exists() and resolved.is_file():
        suffix = resolved.suffix.lower()
        if suffix not in TEXT_SUFFIX_ALLOWLIST:
            return _ResolvedPath(False, "non_text_file_blocked", None, rel_display)
        if _looks_binary(resolved):
            return _ResolvedPath(False, "binary_file_blocked", None, rel_display)
    if for_write and not resolved.exists():
        suffix = resolved.suffix.lower()
        if suffix and suffix not in TEXT_SUFFIX_ALLOWLIST:
            return _ResolvedPath(False, "non_text_file_blocked", None, rel_display)
    return _ResolvedPath(True, "ok", resolved, rel_display)


def _sensitive_marker_for_path(rel_path: str) -> str | None:
    text = str(rel_path or "").replace("\\", "/")
    lowered = text.lower()
    if "/opt/yangyang_nonebot" in lowered:
        return "production_root"
    parts = [part for part in lowered.split("/") if part]
    for part in parts:
        if part in SENSITIVE_EXACT_NAMES:
            return part
        if part.endswith(SENSITIVE_SUFFIXES):
            return Path(part).suffix or "sensitive_suffix"
        if re.search(r"(^|[._-])key([._-]|$)", part):
            return "key"
        for marker in SENSITIVE_PATH_MARKERS:
            if marker in part:
                return marker
    return None


def _iter_text_files(path: Path, *, root: Path, max_files: int) -> Iterable[tuple[Path, str | None]]:
    count = 0
    candidates: Iterable[Path]
    if path.is_file():
        candidates = [path]
    else:
        candidates = sorted((item for item in path.rglob("*") if item.is_file()), key=lambda item: _safe_rel(item, root))
    for file_path in candidates:
        rel = _safe_rel(file_path, root)
        sensitive = _sensitive_marker_for_path(rel)
        if sensitive:
            yield file_path, sensitive
            continue
        if file_path.suffix.lower() not in TEXT_SUFFIX_ALLOWLIST:
            continue
        if _looks_binary(file_path):
            continue
        yield file_path, None
        count += 1
        if count >= max_files:
            break


def _looks_binary(path: Path) -> bool:
    try:
        chunk = path.read_bytes()[:4096]
    except Exception:
        return True
    return b"\x00" in chunk


def _safe_rel(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return path.name


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        while True:
            chunk = fp.read(65536)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _hash16(text: str) -> str:
    return hashlib.sha256(str(text or "").encode("utf-8", errors="ignore")).hexdigest()[:16]


def _parse_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else default
    except Exception:
        return default


def _extract_command_after_tool(raw_text: str, raw_tool_name: str) -> str:
    command_text = _extract_toolbox_command_text(raw_text) or ""
    raw_tool = str(raw_tool_name or "").strip()
    if raw_tool and command_text.startswith(raw_tool):
        return command_text[len(raw_tool):].strip(" \t\r\n:：")
    parts = command_text.split(maxsplit=1)
    return parts[1] if len(parts) > 1 else ""


def _extract_payload(raw_text: str) -> str:
    text = str(raw_text or "")
    marker = "<<<"
    start = text.find(marker)
    if start < 0:
        return ""
    body = text[start + len(marker):]
    end = body.rfind(">>>")
    if end >= 0:
        body = body[:end]
    return body.strip("\r\n")


def _extract_old_new_blocks(raw_text: str) -> tuple[str, str] | None:
    text = str(raw_text or "")
    pattern = re.compile(r"OLD\r?\n(.*?)\r?\nOLD\r?\nNEW\r?\n(.*?)\r?\nNEW", re.DOTALL)
    match = pattern.search(text)
    if not match:
        return None
    return match.group(1), match.group(2)


def _truncate_output(text: str, max_chars: int) -> tuple[str, bool]:
    value = str(text or "")
    if len(value) <= max_chars:
        return value, False
    return value[:max_chars] + f"\n[truncated to {max_chars} chars]", True


def _looks_sensitive_name(name: str) -> bool:
    lowered = str(name or "").lower()
    return any(marker in lowered for marker in ("token", "secret", "password", "passwd", "credential", "api_key", "apikey", "private_key"))


def _forbidden_command_reason(text: str, workspace_root: Path | None = None) -> str:
    value = str(text or "")
    lowered = value.lower()
    if "/opt/yangyang_nonebot" in lowered:
        return "production_path_blocked"
    if "../" in value or "..\\" in value or re.search(r"(^|\s)\.\.($|\s|/|\\)", value):
        return "path_traversal_blocked"
    if "$HOME" in value or "${HOME}" in value or re.search(r"(^|\s)~(/|\s|$)", value):
        return "path_escape_blocked"
    sensitive_patterns = [
        r"(^|[/\s'\"`])\.env([/\s'\"`).]|$)",
        r"memories\.jsonl",
        r"credentials?",
        r"api[_-]?key",
        r"secret",
        r"token",
        r"password",
        r"passwd",
        r"private[_-]?key",
        r"id_rsa",
        r"id_ed25519",
    ]
    if any(re.search(pattern, lowered) for pattern in sensitive_patterns):
        return "sensitive_path_blocked"
    if workspace_root is not None:
        root = Path(workspace_root).resolve()
        token_candidates: list[str] = []
        try:
            token_candidates.extend(shlex.split(value))
        except Exception:
            token_candidates.extend(re.split(r"\s+", value))
        token_candidates.extend(match.group(1) for match in re.finditer(r"['\"](/[^'\"]+)['\"]", value))
        for token in token_candidates:
            raw = str(token or "").strip()
            if not raw or "://" in raw:
                continue
            cleaned = raw.strip("`'\"()[]{};,|&<>")
            marker_path = cleaned
            while marker_path.startswith("./"):
                marker_path = marker_path[2:]
            if marker_path and _sensitive_marker_for_path(marker_path):
                return "sensitive_path_blocked"
            if cleaned.startswith("~"):
                return "path_escape_blocked"
            if not cleaned.startswith("/"):
                continue
            try:
                resolved = Path(cleaned).resolve()
            except Exception:
                return "invalid_path"
            if _is_forbidden_production_path(resolved):
                return "production_path_blocked"
            if not _is_relative_to(resolved, root):
                return "path_escape_blocked"
    return ""


def _command_has_forbidden_target(text: str) -> bool:
    return bool(_forbidden_command_reason(text))


def _audit_path(config: Any, workspace_root: Path) -> Path:
    raw = str(_config_get(config, "owner_engineering_toolbox_audit_path", DEFAULT_AUDIT_PATH) or DEFAULT_AUDIT_PATH).strip()
    path = Path(raw)
    if not path.is_absolute():
        path = workspace_root / path
    try:
        resolved = path.resolve()
    except Exception:
        resolved = workspace_root / DEFAULT_AUDIT_PATH
    if _is_forbidden_production_path(resolved) or not _is_relative_to(resolved, workspace_root):
        resolved = workspace_root / DEFAULT_AUDIT_PATH
    return resolved


def _audit_summary(command: ToolboxCommand) -> dict[str, Any]:
    if command.tool_name in {"shell"}:
        cmd = _extract_command_after_tool(command.raw_text, command.raw_tool_name)
        first_word = ""
        try:
            parts = shlex.split(cmd)
            first_word = str(parts[0])[:40] if parts else ""
        except Exception:
            first_word = str(cmd).strip().split(maxsplit=1)[0][:40] if str(cmd).strip() else ""
        return {"command_sha256_16": _hash16(cmd), "command_chars": len(cmd), "command": _redact_sensitive_text(first_word)}
    if command.tool_name in {"python"}:
        code = _extract_payload(command.raw_text) or _extract_command_after_tool(command.raw_text, command.raw_tool_name)
        return {"code_sha256_16": _hash16(code), "code_chars": len(code)}
    path = command.args[0] if command.args else ""
    data: dict[str, Any] = {"path": _redact_sensitive_text(path)[:240]}
    if command.tool_name in {"write_file", "append_file", "edit_file"}:
        payload = _extract_payload(command.raw_text)
        data["payload_sha256_16"] = _hash16(payload)
        data["payload_chars"] = len(payload)
    return data


def _write_audit_record(
    command: ToolboxCommand,
    gate: ToolboxGateResult,
    execution: ToolboxExecutionResult | None,
    config: Any,
    *,
    success: bool,
    error: str,
    duration_ms: int,
) -> None:
    if not _config_get_bool(config, "owner_engineering_toolbox_audit_enabled", True):
        return
    workspace_root = Path(gate.workspace_root).resolve()
    path = _audit_path(config, workspace_root)
    record = {
        "ts": _utc_now(),
        "schema_version": NL_SCHEMA_VERSION,
        "tool": command.tool_name,
        "actor": gate.actor,
        "mode": gate.mode,
        "risk_level": gate.risk_level,
        "gate_reason": gate.reason,
        "success": bool(success),
        "error": _redact_sensitive_text(str(error or ""))[:240],
        "duration_ms": int(duration_ms),
        "summary": _audit_summary(command),
        "status": getattr(execution, "status", None),
        "reason": getattr(execution, "reason", gate.reason),
        "real_write": bool(getattr(execution, "real_write", False)),
        "real_execute": bool(getattr(execution, "real_execute", False)),
        "raw_report_fields": {
            "tool": command.tool_name,
            "status": getattr(execution, "status", None),
            "reason": getattr(execution, "reason", gate.reason),
            "risk": gate.risk_level,
            "mode": gate.mode,
            "owner_private_only": bool(gate.owner_private_required),
            "requires_confirm": bool(gate.requires_confirm),
            "dry_run": bool(gate.dry_run),
            "real_write": bool(getattr(execution, "real_write", False)),
            "real_execute": bool(getattr(execution, "real_execute", False)),
        },
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
    except Exception:
        # 审计失败不能反向泄露或打断工具主流程。
        return


def _redact_sensitive_text(text: str) -> str:
    value = str(text or "")
    patterns = [
        r"(?i)(api[_-]?key|token|secret|password|passwd|authorization)\s*[:=]\s*['\"]?[^\s'\"，,;]+",
        r"(?i)bearer\s+[a-z0-9._\-]+",
        r"sk-[A-Za-z0-9_\-]{12,}",
        r"(?i)(AKIA|ASIA)[A-Z0-9]{12,}",
    ]
    for pattern in patterns:
        value = re.sub(pattern, "[REDACTED]", value)
    return value


def _display_workspace_root(root: Path) -> str:
    resolved = root.resolve()
    if _is_forbidden_production_path(resolved):
        return "[blocked:production_root]"
    return resolved.as_posix()


def _bool_text(value: Any) -> str:
    return str(bool(value)).lower()


def _format_gate_block_reply(gate: ToolboxGateResult, *, raw: bool = False) -> str:
    if raw:
        return (
            "工具箱已拦截："
            f"reason={gate.reason} tool={gate.tool_name} risk={gate.risk_level} mode={gate.mode} "
            "owner_private_only=true executor_enabled=false host_action_executed=false"
        )
    return _natural_block_message(gate.reason, tool=gate.tool_name, action="blocked")


def _format_toolbox_raw_reply(gate: ToolboxGateResult, execution: ToolboxExecutionResult) -> str:
    output = (execution.output or "").strip()
    header = (
        f"[owner_toolbox] tool={execution.tool_name} status={execution.status} reason={execution.reason} "
        f"risk={execution.risk_level} mode={execution.mode} owner_private_only=true "
        f"requires_confirm={_bool_text(gate.requires_confirm)} dry_run={_bool_text(gate.dry_run)} "
        f"real_write={_bool_text(execution.real_write)} real_execute={_bool_text(execution.real_execute)}"
    )
    if not output:
        return header
    return f"{header}\n{output}"


def _raw_report_requested(command: ToolboxCommand | None = None, config: Any | None = None) -> bool:
    if bool(getattr(command, "debug", False)):
        return True
    return _config_get_bool(config, "owner_engineering_toolbox_raw_report_enabled", False) or _config_get_bool(
        config,
        "owner_engineering_toolbox_debug_raw_enabled",
        False,
    )


def _parse_output_header(output: str) -> dict[str, str]:
    line = (str(output or "").splitlines() or [""])[0]
    return {match.group(1): match.group(2) for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)", line)}


def _output_lines_after_header(output: str) -> list[str]:
    lines = str(output or "").splitlines()
    if not lines:
        return []
    first = lines[0]
    if re.search(r"(^|\s)[A-Za-z_][A-Za-z0-9_]*=", first) or first.startswith(("list_dir ", "read_file ", "grep ", "find ", "shell ", "python ", "log_tail ", "health ")):
        return lines[1:]
    return lines


def _clean_tool_output_body(output: str) -> str:
    return "\n".join(_output_lines_after_header(output)).strip()


def _sanitize_user_detail(text: str) -> str:
    value = _redact_sensitive_text(str(text or "")).strip()
    value = re.sub(r"/opt/[^\s，。,;；]+", "受控外路径", value)
    value = re.sub(r"\b(reason|status|confidence|risk|mode|owner_private_only|real_write|real_execute|tool)=[^\s]+", "", value)
    value = value.replace("[owner_toolbox_nl]", "").replace("[owner_toolbox]", "")
    return re.sub(r"[ \t]{2,}", " ", value).strip()


PERSONA_FORMATTER_VERSION = "owner_engineering_toolbox.persona_formatter_v1.20260608"


_PERSONA_RAW_FIELD_NAMES: tuple[str, ...] = (
    "tool",
    "risk",
    "mode",
    "reason",
    "status",
    "confidence",
    "owner_private_only",
    "real_write",
    "real_execute",
    "workspace_root",
    "requires_confirm",
    "dry_run",
)


_PERSONA_ALIASES: dict[str, str] = {
    "": "default",
    "default": "default",
    "plain": "default",
    "normal": "default",
    "none": "default",
    "yangyang": "yangyang",
    "秧秧": "yangyang",
    "yang": "yangyang",
    "yy": "yangyang",
    "yaya": "yaya",
    "娅娅": "yaya",
    "ya": "yaya",
    "isaac": "isaac",
    "ishu": "isaac",
    "i叔": "isaac",
    "I叔": "isaac",
    "艾萨克": "isaac",
    "is叔": "isaac",
}


def _normalize_persona(persona: str | None) -> str:
    """Normalize public persona names into deterministic formatter buckets."""
    raw = str(persona or "").strip()
    if not raw:
        return "default"
    return _PERSONA_ALIASES.get(raw, _PERSONA_ALIASES.get(raw.lower(), "default"))


def _persona_from_config(config: Any | None, explicit: str | None = None) -> str:
    normalized = _normalize_persona(explicit)
    if explicit is not None and str(explicit).strip():
        return normalized
    for key in (
        "owner_engineering_toolbox_formatter_persona",
        "owner_engineering_toolbox_persona",
        "owner_toolbox_persona",
    ):
        value = _config_get(config, key, None)
        if value is not None and str(value).strip():
            return _normalize_persona(str(value))
    return "default"


def _persona_variant(options: tuple[str, ...], *parts: Any) -> str:
    if not options:
        return ""
    digest = hashlib.sha256("|".join(str(part) for part in parts).encode("utf-8", errors="ignore")).hexdigest()
    return options[int(digest[:8], 16) % len(options)]


def _classify_safe_reason(reason: str, *, base_text: str = "", raw_text: str = "") -> str:
    haystack = f"{reason}\n{base_text}\n{raw_text}".lower()
    if "冷备" in base_text or "冷备" in raw_text or "missing_controlled_workspace_path" in haystack:
        return "cold_backup"
    if "high_risk" in haystack or "requires_confirm" in haystack:
        return "high_risk"
    if "timeout" in haystack:
        return "timeout"
    if "permission" in haystack or "permission_denied" in haystack:
        return "permission"
    if "not_found" in haystack or "不存在" in base_text or "没找到" in base_text:
        return "not_found"
    if "production_path" in haystack or "production_root" in haystack or "forbidden_workspace_root" in haystack:
        return "production_root"
    if "path_traversal" in haystack or "path_escape" in haystack:
        return "outside_workspace"
    if "sensitive_path" in haystack or "non_text_file" in haystack or "binary_file" in haystack:
        return "sensitive"
    if "owner_only" in haystack or "private_only" in haystack:
        return "access_boundary"
    return "low"


def _safe_target_label(value: Any, *, fallback: str = "目标") -> str:
    label = _friendly_path(str(value or "").strip() or fallback)
    label = re.sub(r"\s+目录$", "", label).strip()
    return label or fallback


def _extract_list_facts(execution: ToolboxExecutionResult) -> tuple[str, bool, tuple[str, ...]]:
    header = _parse_output_header(execution.output)
    data = execution.data or {}
    path_label = _safe_target_label(header.get("path") or data.get("path") or ".", fallback="当前目录")
    try:
        entries_count = int(header.get("entries") or data.get("entries") or 0)
    except Exception:
        entries_count = 0
    base = str(header.get("path") or ".").strip().rstrip("/")
    names: list[str] = []
    for line in _output_lines_after_header(execution.output):
        parts = line.split("\t")
        rel = (parts[1] if len(parts) >= 2 else line).strip().rstrip("/")
        if not rel:
            continue
        if base and base not in {".", "./"}:
            prefix = base + "/"
            if rel.startswith(prefix):
                name = rel[len(prefix):].split("/", 1)[0]
            else:
                name = Path(rel).name or rel
        else:
            name = rel.split("/", 1)[0]
        name = _sanitize_user_detail(name)
        if name and name not in names:
            names.append(name)
    return path_label, entries_count <= 0, tuple(names[:8])


def _extract_executor_value(execution: ToolboxExecutionResult) -> str:
    body = _clean_tool_output_body(execution.output)
    if not body:
        return ""
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if not lines:
        return ""
    if execution.status == "ok" and len(lines) == 1 and not lines[0].startswith("[stderr]"):
        return _sanitize_user_detail(lines[0])[:120]
    safe = "；".join(_sanitize_user_detail(line) for line in lines[:2] if line.strip())
    return safe[:160]


def _facts_from_execution(gate: ToolboxGateResult | None, execution: ToolboxExecutionResult, base_text: str) -> dict[str, Any]:
    data = execution.data or {}
    header = _parse_output_header(execution.output)
    facts: dict[str, Any] = {
        "kind": "execution",
        "tool_name": execution.tool_name,
        "status": str(execution.status or ""),
        "reason": str(execution.reason or ""),
        "risk_level": execution.risk_level,
        "mode": execution.mode,
        "base_text": base_text,
        "target_label": _safe_target_label(data.get("path") or header.get("path") or "", fallback="目标"),
        "items": (),
        "empty": False,
        "value": "",
        "safe_hint": "请提供相对工作区路径，或走受控交接。",
        "safety_class": _classify_safe_reason(execution.reason, base_text=base_text),
        "real_write": bool(execution.real_write),
        "real_execute": bool(execution.real_execute),
        "requires_confirm": bool(getattr(gate, "requires_confirm", False)),
    }
    if gate is not None and (gate.mode == "require_confirm" or gate.requires_confirm):
        facts["requires_confirm"] = True
        if facts["safety_class"] == "high_risk":
            facts["status"] = "need_confirm"
    if execution.tool_name == "list_dir":
        target, empty, items = _extract_list_facts(execution)
        facts.update({"target_label": target, "empty": empty, "items": items})
    elif execution.tool_name in {"python", "shell"}:
        facts["value"] = _extract_executor_value(execution)
    elif execution.tool_name == "toolbox_status":
        facts["target_label"] = "工具箱"
    elif execution.tool_name == "pack_archive":
        facts["target_label"] = _safe_target_label(data.get("archive") or header.get("archive") or "产物", fallback="产物")
        facts["value"] = _sanitize_user_detail(str(data.get("sha256") or header.get("sha256") or ""))
    elif execution.tool_name == "sha256":
        facts["value"] = _sanitize_user_detail(str(data.get("sha256") or header.get("sha256") or ""))
    if str(execution.status or "") in {"blocked", "error", "timeout"}:
        facts["safety_class"] = _classify_safe_reason(execution.reason, base_text=base_text)
    return facts


def _facts_from_plan(plan: ToolboxIntentPlan, base_text: str) -> dict[str, Any]:
    status = "need_confirm" if plan.action == "confirm" else ("blocked" if plan.action == "blocked" else "clarify")
    safety_class = _classify_safe_reason(plan.reason, base_text=base_text, raw_text=plan.raw_text)
    if plan.action == "confirm":
        safety_class = "high_risk"
    return {
        "kind": "plan",
        "tool_name": plan.tool_name,
        "status": status,
        "action": plan.action,
        "reason": plan.reason,
        "risk_level": plan.risk_level,
        "base_text": base_text,
        "target_label": "目标",
        "items": (),
        "empty": False,
        "value": "",
        "safe_hint": "请提供相对工作区路径，或走受控交接。",
        "safety_class": safety_class,
        "requires_confirm": plan.action == "confirm",
    }


def _facts_from_gate(gate: ToolboxGateResult, base_text: str, *, action: str = "blocked") -> dict[str, Any]:
    status = "need_confirm" if action == "confirm" or gate.mode == "require_confirm" or gate.requires_confirm else "blocked"
    safety_class = _classify_safe_reason(gate.reason, base_text=base_text)
    if status == "need_confirm":
        safety_class = "high_risk"
    return {
        "kind": "gate",
        "tool_name": gate.tool_name,
        "status": status,
        "action": action,
        "reason": gate.reason,
        "risk_level": gate.risk_level,
        "mode": gate.mode,
        "base_text": base_text,
        "target_label": "目标",
        "items": (),
        "empty": False,
        "value": "",
        "safe_hint": "请提供相对工作区路径，或走受控交接。",
        "safety_class": safety_class,
        "requires_confirm": bool(gate.requires_confirm),
    }


def _looks_like_raw_toolbox_reply(text: str) -> bool:
    value = str(text or "")
    return value.startswith("[owner_toolbox]") or value.startswith("[owner_toolbox_nl]")


def _persona_safety_scrub(text: str, facts: Mapping[str, Any], persona: str) -> str:
    del persona
    value = _redact_sensitive_text(str(text or "")).strip()
    value = value.replace("[owner_toolbox_nl]", "").replace("[owner_toolbox]", "")
    fields = "|".join(re.escape(name) for name in _PERSONA_RAW_FIELD_NAMES)
    value = re.sub(rf"\b(?:{fields})=[^\s，。；;]+", "", value)
    value = re.sub(r"(?i)/opt(?:/[^\s，。；;]*)?", "受控外路径", value)
    value = re.sub(r"/AstrBot(?:/[^\s，。；;]*)?", "受控外路径", value)
    value = re.sub(r"(?i)/(?:etc|root|home|var|usr)(?:/[^\s，。；;]*)?", "受控外路径", value)
    value = re.sub(r"(?i)\.env(?:\.[a-z0-9_-]+)?", "敏感配置文件", value)
    value = re.sub(r"(?i)(token|secret|password|passwd|private[_-]?key|api[_-]?key)\s*[:=]\s*[^\s，。；;]+", "敏感字段已隐藏", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    value = re.sub(r"\s+([，。；：])", r"\1", value)
    value = re.sub(r"([，；：])\s+", r"\1", value).strip(" \t\r\n；;，,")
    if not value:
        value = str(facts.get("base_text") or "操作没有执行，请补充更明确的下一步。").strip()
    status = str(facts.get("status") or "")
    safety_class = str(facts.get("safety_class") or "")
    if status in {"blocked", "need_confirm", "failed", "error", "timeout"} or safety_class in {"sensitive", "production_root", "cold_backup", "outside_workspace", "high_risk"}:
        guard_words = (
            "不能",
            "未执行",
            "没执行",
            "不执行",
            "不碰",
            "不直接",
            "不展开",
            "拦",
            "暂停",
            "停住",
            "确认",
            "先刹",
            "别硬",
            "硬看",
            "硬闯",
            "踩线",
            "受控交接",
            "相对工作区",
            "失败",
            "没跑成",
            "未完成",
            "没完成",
            "没成功",
            "超时",
            "没有权限",
        )
        if not any(word in value for word in guard_words):
            if safety_class == "high_risk" or status == "need_confirm":
                value = "高风险动作已暂停，需要 owner 确认。"
            elif safety_class in {"sensitive", "production_root", "cold_backup", "outside_workspace"} or status == "blocked":
                value = "这个位置不能直接展开；请提供相对工作区路径，或走受控交接。"
            elif status == "timeout" or safety_class == "timeout":
                value = "执行超时，未拿到结果。建议缩小范围后重试。"
            else:
                value = "这次没完成，请按安全提示调整后重试。"
    return value


def _apply_persona_style(base_text: str, facts: Mapping[str, Any], persona: str | None = "default") -> str:
    persona_name = _normalize_persona(persona)
    base = str(base_text or "").strip()
    if persona_name == "default" or not base or _looks_like_raw_toolbox_reply(base):
        return base

    tool = str(facts.get("tool_name") or "")
    status = str(facts.get("status") or "")
    safety_class = str(facts.get("safety_class") or "low")
    target = str(facts.get("target_label") or "目标")
    value = str(facts.get("value") or "").strip()
    items = tuple(str(item) for item in (facts.get("items") or ()) if str(item).strip())
    fingerprint = (persona_name, tool, status, safety_class, target, value, "|".join(items), str(facts.get("reason") or ""))

    text = base
    if safety_class == "high_risk" or status == "need_confirm" or bool(facts.get("requires_confirm")):
        variants = {
            "yangyang": (
                "这个命令风险偏高，我先停住了。漂♂总确认后我再继续。",
                "这一步风险有点高，漂♂总，我先不执行；等你确认后再继续。",
            ),
            "yaya": (
                "这条不能直接冲，风险高。你确认，我再跑。",
                "高风险动作先刹住了，确认以后再跑。",
            ),
            "isaac": (
                "高风险命令，已暂停。需要 owner 确认。",
                "高风险操作未执行，等待 owner 确认。",
            ),
        }
        text = _persona_variant(variants[persona_name], *fingerprint)
    elif safety_class in {"cold_backup", "production_root", "sensitive", "outside_workspace"} or status == "blocked":
        subtype = safety_class
        if subtype == "cold_backup":
            variants = {
                "yangyang": (
                    "冷备这块不能直接展开，漂♂总。给我相对工作区路径，或走受控交接会更稳。",
                    "冷备位置我不能直接翻，漂♂总。换相对工作区路径，或者走受控交接。",
                ),
                "yaya": (
                    "冷备不能硬看，会踩线。换相对工作区路径，或者走受控交接。",
                    "冷备这块先别硬闯，给相对工作区路径更稳。",
                ),
                "isaac": (
                    "冷备路径不直接展开。请提供相对工作区路径，或走受控交接。",
                    "冷备路径已拦截，未展开。请走相对工作区路径或受控交接。",
                ),
            }
        elif subtype == "production_root":
            variants = {
                "yangyang": (
                    "生产目录我不能直接翻，漂♂总。要看内容请走受控交接。",
                    "生产位置不直接展开，漂♂总；这块请走受控交接。",
                ),
                "yaya": (
                    "生产根不能直接碰，这条我先拦住。",
                    "生产目录别硬冲，我先拦住，走受控交接。",
                ),
                "isaac": (
                    "生产目录禁止直接展开，未执行。",
                    "生产路径已拦截，未执行。请走受控交接。",
                ),
            }
        else:
            variants = {
                "yangyang": (
                    "这个位置不能直接展开，漂♂总。换成相对工作区路径，或走受控交接会更稳。",
                    "这块我先不碰，漂♂总。请给相对工作区路径，或走受控交接。",
                ),
                "yaya": (
                    "这块不能硬看，会踩线。给相对工作区路径，或者走受控交接。",
                    "这个位置先拦住，别硬闯；换相对工作区路径。",
                ),
                "isaac": (
                    "该路径不直接展开。请提供相对工作区路径，或走受控交接。",
                    "路径已拦截，未执行。请改用相对工作区路径。",
                ),
            }
        text = _persona_variant(variants[persona_name], *fingerprint)
    elif status == "timeout" or safety_class == "timeout":
        variants = {
            "yangyang": (
                "这次等太久没拿到结果，漂♂总。可以缩小范围再试一次。",
                "这次超时了，漂♂总。缩小范围后再跑会更稳。",
            ),
            "yaya": (
                "超时了，没跑完。缩小一下范围再蹬比较稳。",
                "这次跑过头超时了，缩小范围再来。",
            ),
            "isaac": (
                "执行超时。建议缩小范围后重试。",
                "超时，未完成。请缩小范围后重试。",
            ),
        }
        text = _persona_variant(variants[persona_name], *fingerprint)
    elif status in {"error", "failed"} or base.startswith("执行失败"):
        summary = value or _sanitize_user_detail(base.replace("执行失败，输出：", "").replace("执行失败", "")).strip(" ：:")[:80]
        variants = {
            "yangyang": (
                f"这次没跑成，漂♂总。{summary or '可以检查参数后再试一次。'}",
                f"结果没成功，漂♂总；{summary or '先缩小范围再试。'}",
            ),
            "yaya": (
                f"没跑成，先别当完成。{summary or '检查一下参数再来。'}",
                f"执行失败了，没糊弄成成功。{summary or '换个更小范围再试。'}",
            ),
            "isaac": (
                f"执行失败。{summary or '请检查参数后重试。'}",
                f"未完成。{summary or '建议检查命令或参数。'}",
            ),
        }
        text = _persona_variant(variants[persona_name], *fingerprint)
    elif tool == "list_dir" and status == "ok" and bool(facts.get("empty")):
        variants = {
            "yangyang": (
                f"{target} 现在是空的，漂♂总。",
                f"漂♂总，{target} 里暂时没有东西。",
                f"{target} 当前为空，漂♂总。",
            ),
            "yaya": (
                f"{target} 是空的，没藏东西。",
                f"{target} 空空的，清清爽爽。",
                f"{target} 当前为空，没多余包袱。",
            ),
            "isaac": (
                f"{target} 为空。",
                f"{target} 当前无内容。",
                f"{target}：空。",
            ),
        }
        text = _persona_variant(variants[persona_name], *fingerprint)
    elif tool == "list_dir" and status == "ok" and items:
        items_short = "、".join(items[:5])
        variants = {
            "yangyang": (
                f"{target} 里有：{items_short}，漂♂总。",
                f"漂♂总，{target} 下能看到：{items_short}。",
            ),
            "yaya": (
                f"{target} 有：{items_short}，东西都摆这儿了。",
                f"看到了，{target} 里主要是：{items_short}。",
            ),
            "isaac": (
                f"{target} 内容：{items_short}。",
                f"{target} 下有：{items_short}。",
            ),
        }
        text = _persona_variant(variants[persona_name], *fingerprint)
    elif tool == "python" and status == "ok" and value:
        variants = {
            "yangyang": (
                f"算出来是 {value}，漂♂总。",
                f"漂♂总，结果是 {value}。",
            ),
            "yaya": (
                f"结果是 {value}，没跑偏。",
                f"算完了，结果 {value}。",
            ),
            "isaac": (
                f"结果：{value}。",
                f"计算结果：{value}。",
            ),
        }
        text = _persona_variant(variants[persona_name], *fingerprint)
    elif tool == "toolbox_status" and status == "ok":
        variants = {
            "yangyang": (
                "工具箱状态正常，漂♂总，可以继续用。",
                "这边工具箱正常，漂♂总。",
            ),
            "yaya": (
                "工具箱活着，能使唤。",
                "工具箱活着，可以继续开工。",
            ),
            "isaac": (
                "工具箱正常。",
                "状态正常，可以继续。",
            ),
        }
        text = _persona_variant(variants[persona_name], *fingerprint)
    elif status == "ok" and "\n" not in base and len(base) <= 120:
        tails = {
            "yangyang": ("漂♂总。", "这边好了，漂♂总。"),
            "yaya": ("搞定。", "这下清楚了。"),
            "isaac": ("完成。", "已完成。"),
        }
        tail = _persona_variant(tails[persona_name], *fingerprint)
        if persona_name == "yangyang" and "漂♂总" not in base:
            text = base.rstrip("。") + f"，{tail}"
        elif persona_name == "yaya" and not any(word in base for word in ("搞定", "清楚")):
            text = base.rstrip("。") + f"，{tail}"
        elif persona_name == "isaac":
            text = base

    return _persona_safety_scrub(text, facts, persona_name)


def _format_natural_with_persona(result: Any, persona: str | None = "default") -> str:
    """Format an owner-toolbox result through the persona layer.

    The input may be a ToolboxHandleResult, a mapping containing gate/execution/plan,
    or a plain string.  Facts stay deterministic; persona only paraphrases safe facts.
    """
    base_text = ""
    gate = None
    execution = None
    plan = None
    if isinstance(result, Mapping):
        base_text = str(result.get("base_text") or result.get("formatted_text") or result.get("reply") or "")
        gate = result.get("gate")
        execution = result.get("execution")
        plan = result.get("plan") or result.get("intent_plan")
    else:
        base_text = str(getattr(result, "formatted_text", "") or getattr(result, "reply", "") or result or "")
        gate = getattr(result, "gate", None)
        execution = getattr(result, "execution", None)
        plan = getattr(result, "intent_plan", None)
    if execution is not None:
        if not base_text:
            base_text = _format_toolbox_execution_natural(gate, execution) if gate is not None else _clean_tool_output_body(getattr(execution, "output", ""))
        facts = _facts_from_execution(gate, execution, base_text)
    elif plan is not None:
        if not base_text:
            base_text = _format_plan_non_execute_reply(plan)
        facts = _facts_from_plan(plan, base_text)
    elif gate is not None:
        if not base_text:
            base_text = _natural_block_message(gate.reason, tool=gate.tool_name, action="blocked")
        facts = _facts_from_gate(gate, base_text)
    else:
        facts = {"kind": "text", "tool_name": "unknown", "status": "", "base_text": base_text, "safety_class": _classify_safe_reason("", base_text=base_text)}
    return _apply_persona_style(base_text, facts, persona)


def _friendly_path(path_value: str | None) -> str:
    value = _sanitize_user_detail(path_value or ".") or "."
    if value in {".", "./"}:
        return "当前目录"
    return value.rstrip("/") or "当前目录"


def _sentence_for_path_dir(path_value: str | None) -> str:
    path = _friendly_path(path_value)
    return path if path.endswith("目录") else f"{path} 目录"


def _limited_lines(lines: Iterable[str], *, limit: int = 12) -> list[str]:
    cleaned = [_sanitize_user_detail(line) for line in lines if str(line or "").strip()]
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit] + [f"……还有 {len(cleaned) - limit} 条未显示。"]


def _natural_block_message(
    reason: str,
    *,
    tool: str | None = None,
    action: str = "blocked",
    detail: str = "",
    raw_text: str = "",
) -> str:
    reason_text = str(reason or "").strip()
    haystack = f"{reason_text}\n{raw_text}"
    if "missing_controlled_workspace_path" in reason_text or "冷备" in haystack or "冷备份" in haystack:
        return "冷备相关不能直接展开路径；请给相对工作区路径，或走受控交接。"
    if action == "clarify":
        clean_detail = _sanitize_user_detail(detail)
        if clean_detail:
            return clean_detail
        if "missing_query" in reason_text:
            return "要搜什么关键词？请补充关键词，也可以附上相对工作区路径。"
        if "missing_path" in reason_text:
            return "要看哪个相对工作区路径？请给一个相对路径。"
        if "missing_command" in reason_text:
            return "要执行哪条命令？请补充命令内容。"
        if "missing_code" in reason_text:
            return "要运行哪段 Python？请补充代码或表达式。"
        if "missing_content" in reason_text:
            return "要写入什么内容？请补充目标相对路径和文本。"
        return "我还不能确定要调用哪个工程工具，请补充相对路径、关键词或命令。"
    if action == "confirm" or "high_risk" in reason_text or "requires_confirm" in reason_text:
        return "这个动作属于高风险，我不能直接执行。请拆成只读检查步骤，或走显式确认流程。"
    if "owner_only" in reason_text:
        return "工具箱只在 owner 私聊可用。"
    if "private_only" in reason_text:
        return "工具箱只在私聊可用。"
    if "disabled" in reason_text:
        if tool in {"shell", "python"} or "executor" in reason_text:
            return "执行器现在关闭，不能跑这个命令。可以先用读取或搜索类工具检查。"
        if tool in {"write_file", "append_file", "edit_file", "mkdir", "rm", "pack_archive"}:
            return "写入类工具现在关闭。可以先用只读检查。"
        return "工具箱当前未启用。"
    if "path_traversal" in reason_text or "path_escape" in reason_text or "production_path" in reason_text:
        return "这个路径不在受控工作区里，我不能直接操作。请给相对工作区路径。"
    if "sensitive_path" in reason_text or "non_text_file" in reason_text or "binary_file" in reason_text:
        return "这个路径看起来包含敏感或非文本内容，我不能直接操作。请换一个非敏感的相对工作区路径。"
    if "path_not_found" in reason_text:
        return "没找到这个路径，请确认相对工作区路径。"
    if "not_directory" in reason_text:
        return "这个路径不是目录，请给目录路径。"
    if "not_file" in reason_text:
        return "这个路径不是文件，请给文件路径。"
    if "old_text_not_found" in reason_text:
        return "没找到要替换的原文，文件没有被修改。"
    if "missing_old_new" in reason_text:
        return "编辑需要 OLD/NEW 两段内容，请补齐后再试。"
    if "timeout" in reason_text:
        return "执行超时了，可能命令跑太久。"
    if "tool_not_allowlisted" in reason_text:
        return "这个工具不在允许列表里，我不能执行。"
    if action == "blocked":
        return "这个操作被安全规则拦截了。请改用受控工作区内的低风险步骤。"
    return "操作没有执行，请补充更明确的下一步。"


def _format_list_dir_natural(execution: ToolboxExecutionResult) -> str:
    header = _parse_output_header(execution.output)
    path = header.get("path") or "."
    try:
        entries_count = int(header.get("entries") or (execution.data or {}).get("entries") or 0)
    except Exception:
        entries_count = 0
    hidden = int((execution.data or {}).get("hidden_sensitive") or header.get("hidden_sensitive") or 0)
    truncated = str((execution.data or {}).get("truncated") or header.get("truncated") or "false").lower() == "true"
    if entries_count <= 0:
        text = f"{_sentence_for_path_dir(path)}是空的。"
    else:
        base = str(path or ".").strip().rstrip("/")
        names: list[str] = []
        for line in _output_lines_after_header(execution.output):
            parts = line.split("\t")
            rel = parts[1] if len(parts) >= 2 else line.strip()
            rel = rel.strip().rstrip("/")
            name = rel
            if base and base not in {".", "./"}:
                prefix = base + "/"
                if rel.startswith(prefix):
                    name = rel[len(prefix):].split("/", 1)[0]
                else:
                    name = Path(rel).name or rel
            else:
                name = rel.split("/", 1)[0] if "/" in rel else rel
            if name and name not in names:
                names.append(name)
        suffix = "等" if truncated else ""
        display_path = _friendly_path(path)
        connector = "里" if display_path == "当前目录" else " 里"
        text = f"{display_path}{connector}有：{'、'.join(names[:20])}{suffix}。"
    if hidden > 0:
        text += f"已隐藏 {hidden} 个敏感项。"
    return text


def _format_read_file_natural(execution: ToolboxExecutionResult) -> str:
    header = _parse_output_header(execution.output)
    path = _friendly_path(header.get("path") or (execution.data or {}).get("path") or ".")
    lines = _limited_lines(_output_lines_after_header(execution.output), limit=40)
    body = "\n".join(lines).strip()
    if not body:
        return f"{path} 没有可显示的内容。"
    return f"这是 {path} 的内容：\n{body}"


def _format_search_natural(execution: ToolboxExecutionResult, *, label: str = "匹配项") -> str:
    data = execution.data or {}
    header = _parse_output_header(execution.output)
    try:
        count = int(data.get("results") if data.get("results") is not None else header.get("results") or 0)
    except Exception:
        count = 0
    if count <= 0:
        return "没找到匹配项。"
    lines = _limited_lines(_output_lines_after_header(execution.output), limit=20)
    return f"找到了 {count} 条{label}：\n" + "\n".join(lines)


def _format_executor_natural(execution: ToolboxExecutionResult) -> str:
    if execution.status == "timeout":
        return "执行超时了，可能命令跑太久。"
    body = _clean_tool_output_body(execution.output)
    if execution.status == "ok":
        if not body:
            return "执行成功，没有输出。"
        if execution.tool_name == "python":
            lines = [line.strip() for line in body.splitlines() if line.strip()]
            if len(lines) == 1 and not lines[0].startswith("[stderr]") and len(lines[0]) <= 120:
                return f"结果是 {lines[0]}。"
        return "执行成功，输出：\n" + body
    if body:
        return "执行失败，输出：\n" + body
    return "执行失败了，请检查命令或参数后再试。"


def _format_status_natural(execution: ToolboxExecutionResult) -> str:
    """Return one-line human status for owner default reply.

    Raw/debug status keeps the full internal report; default owner chat should
    not dump workspace paths/capability toggles/boundary lines.
    """
    if str(getattr(execution, "status", "") or "") != "ok":
        return "工具箱状态暂时异常；需要细节可以用 `工具箱 debug status`。"
    return "工具箱正常。"

def _format_success_mutation_natural(execution: ToolboxExecutionResult) -> str:
    data = execution.data or {}
    tool = execution.tool_name
    path = _friendly_path(str(data.get("path") or _parse_output_header(execution.output).get("path") or "."))
    if execution.status == "dry_run":
        return f"这是预演，没有实际写入。目标：{path}。"
    if tool == "write_file":
        return f"已写入 {path}。"
    if tool == "append_file":
        return f"已追加到 {path}。"
    if tool == "edit_file":
        return f"已修改 {path}。"
    if tool == "mkdir":
        return f"已创建目录 {path}。"
    if tool == "rm":
        trashed = _friendly_path(str(data.get("trashed_to") or "工具箱回收区"))
        return f"已移到工具箱回收区：{trashed}。"
    return "操作已完成。"


def _format_toolbox_execution_natural(gate: ToolboxGateResult, execution: ToolboxExecutionResult) -> str:
    if execution.status == "blocked":
        return _natural_block_message(execution.reason, tool=execution.tool_name, action="blocked")
    if execution.status == "error" and execution.tool_name not in {"shell", "python"}:
        return _natural_block_message(execution.reason, tool=execution.tool_name, action="blocked")
    if execution.tool_name == "toolbox_status":
        return _format_status_natural(execution)
    if execution.tool_name == "list_dir":
        if execution.status != "ok":
            return _natural_block_message(execution.reason, tool=execution.tool_name, action="blocked")
        return _format_list_dir_natural(execution)
    if execution.tool_name == "read_file":
        if execution.status != "ok":
            return _natural_block_message(execution.reason, tool=execution.tool_name, action="blocked")
        return _format_read_file_natural(execution)
    if execution.tool_name == "grep":
        if execution.status != "ok":
            return _natural_block_message(execution.reason, tool=execution.tool_name, action="blocked")
        return _format_search_natural(execution)
    if execution.tool_name == "find":
        if execution.status != "ok":
            return _natural_block_message(execution.reason, tool=execution.tool_name, action="blocked")
        return _format_search_natural(execution)
    if execution.tool_name in {"shell", "python"}:
        return _format_executor_natural(execution)
    if execution.tool_name in {"write_file", "append_file", "edit_file", "mkdir", "rm"}:
        if execution.status not in {"ok", "dry_run"}:
            return _natural_block_message(execution.reason, tool=execution.tool_name, action="blocked")
        return _format_success_mutation_natural(execution)
    if execution.tool_name == "pack_archive":
        if execution.status != "ok":
            return _natural_block_message(execution.reason, tool=execution.tool_name, action="blocked")
        data = execution.data or {}
        archive = _friendly_path(str(data.get("archive") or _parse_output_header(execution.output).get("archive") or ""))
        digest = _sanitize_user_detail(str(data.get("sha256") or _parse_output_header(execution.output).get("sha256") or ""))
        return f"已打包：{archive}\nSHA256：{digest}"
    if execution.tool_name == "sha256":
        if execution.status != "ok":
            return _natural_block_message(execution.reason, tool=execution.tool_name, action="blocked")
        data = execution.data or {}
        digest = _sanitize_user_detail(str(data.get("sha256") or _parse_output_header(execution.output).get("sha256") or ""))
        path = _friendly_path(str(data.get("path") or _parse_output_header(execution.output).get("path") or "目标文件"))
        return f"{path} 的 SHA256 是：{digest}"
    if execution.tool_name == "log_tail":
        if execution.status != "ok":
            return _natural_block_message(execution.reason, tool=execution.tool_name, action="blocked")
        body = "\n".join(_limited_lines(_output_lines_after_header(execution.output), limit=40)).strip()
        return f"这是日志尾部：\n{body}" if body else "日志里没有可显示的内容。"
    if execution.tool_name == "health":
        return "健康检查结果：\n" + "\n".join(_limited_lines(str(execution.output or "").splitlines(), limit=12))
    return _clean_tool_output_body(execution.output) or "执行完成。"


def _format_raw_report_string_for_user(raw_report: str, *, persona: str | None = None) -> str:
    raw = str(raw_report or "").strip()
    persona_name = _normalize_persona(persona)
    if not raw:
        return "没有可显示的结果。"
    first, _, rest = raw.partition("\n")
    fields = {match.group(1): match.group(2) for match in re.finditer(r"([A-Za-z_][A-Za-z0-9_]*)=([^\s]+)", first)}
    reason = fields.get("reason", "")
    tool = fields.get("tool") or "unknown"
    status = fields.get("status") or ""

    def _style_raw_base(base: str, *, status_override: str | None = None, action: str = "") -> str:
        safe_status = status_override or status
        facts = {
            "kind": "raw_report",
            "tool_name": tool,
            "status": safe_status,
            "action": action,
            "reason": reason,
            "risk_level": fields.get("risk") or "low",
            "mode": fields.get("mode") or "execute",
            "base_text": base,
            "target_label": "目标",
            "items": (),
            "empty": False,
            "value": _sanitize_user_detail(rest)[:160],
            "safe_hint": "请提供相对工作区路径，或走受控交接。",
            "safety_class": _classify_safe_reason(reason, base_text=base, raw_text=raw),
            "requires_confirm": bool(fields.get("requires_confirm", "").lower() == "true" or "requires_confirm" in reason),
        }
        return _apply_persona_style(base, facts, persona_name)

    if "clarification_required" in first:
        base = _natural_block_message(reason or "clarification_required", tool=tool, action="clarify", detail=rest)
        return _style_raw_base(base, status_override="clarify", action="clarify")
    if "blocked" in first or status == "blocked":
        base = _natural_block_message(reason, tool=tool, action="blocked")
        return _style_raw_base(base, status_override="blocked", action="blocked")
    if status == "timeout":
        return _style_raw_base("执行超时了，可能命令跑太久。", status_override="timeout")
    if tool in TOOL_ALLOWLIST and status:
        execution = ToolboxExecutionResult(tool, status, reason or status, "low", "execute", output=rest)
        gate = ToolboxGateResult(True, "execute", "ok", "owner_private", tool, "low", False, False, True, str(PROJECT_ROOT))
        base = _format_toolbox_execution_natural(gate, execution)
        return _format_natural_with_persona({"gate": gate, "execution": execution, "base_text": base}, persona=persona_name)
    return _style_raw_base(_sanitize_user_detail(rest or raw), status_override=status or "unknown")


def format_owner_toolbox_result_for_user(
    gate: ToolboxGateResult | None = None,
    execution: ToolboxExecutionResult | None = None,
    *,
    command: ToolboxCommand | None = None,
    config: Any | None = None,
    plan: ToolboxIntentPlan | None = None,
    raw_report: str | None = None,
    persona: str | None = None,
) -> str:
    persona_name = _persona_from_config(config, persona)
    if raw_report is not None and execution is None:
        return _format_raw_report_string_for_user(raw_report, persona=persona_name)
    if plan is not None and execution is None:
        base_reply = _format_plan_non_execute_reply(plan)
        return _format_natural_with_persona({"plan": plan, "base_text": base_reply}, persona=persona_name)
    if execution is not None and gate is not None:
        base_reply = _format_toolbox_execution_natural(gate, execution)
        return _format_natural_with_persona({"gate": gate, "execution": execution, "base_text": base_reply}, persona=persona_name)
    return "操作已完成。"



def _result_formatter_enabled(config: Any | None) -> bool:
    return _config_get_bool(config, "owner_toolbox_result_llm_formatter_enabled", False)


def _result_formatter_safe_for_llm(gate: ToolboxGateResult | None, execution: ToolboxExecutionResult, facts: Mapping[str, Any]) -> bool:
    if execution is None:
        return False
    if str(execution.status or "") not in {"ok", "dry_run"}:
        return False
    if str(facts.get("safety_class") or "low") != "low":
        return False
    if bool(facts.get("requires_confirm")):
        return False
    if execution.tool_name in {"read_file", "log_tail"}:
        # Potentially large or sensitive user/project content. Keep deterministic until a separate scrubber exists.
        return False
    if gate is not None and not bool(gate.allowed):
        return False
    return execution.tool_name in {"toolbox_status", "list_dir", "grep", "find", "health", "sha256", "pack_archive", "shell", "python", "write_file", "append_file", "edit_file", "mkdir", "rm"}


def _facts_for_llm_formatter(
    gate: ToolboxGateResult | None,
    execution: ToolboxExecutionResult,
    *,
    command: ToolboxCommand | None = None,
    plan: ToolboxIntentPlan | None = None,
    base_text: str,
    persona: str,
    original_text: str = "",
) -> dict[str, Any]:
    facts = _facts_from_execution(gate, execution, base_text)
    max_items = 10
    items = list(facts.get("items") or ())[:max_items]
    payload: dict[str, Any] = {
        "schema_version": "owner_toolbox.result_formatter_facts.v1.20260608",
        "persona": _normalize_persona(persona),
        "user_text": _sanitize_user_detail(original_text)[:300],
        "base_text": _sanitize_user_detail(base_text)[:600],
        "tool_name": execution.tool_name,
        "status": str(execution.status or ""),
        "reason_class": str(facts.get("safety_class") or "low"),
        "target_label": _sanitize_user_detail(str(facts.get("target_label") or ""))[:120],
        "empty": bool(facts.get("empty")),
        "items": [_sanitize_user_detail(str(item))[:80] for item in items],
        "value": _sanitize_user_detail(str(facts.get("value") or ""))[:300],
        "real_write": bool(execution.real_write),
        "real_execute": bool(execution.real_execute),
        "requires_confirm": bool(facts.get("requires_confirm")),
        "deterministic_must_keep": {
            "must_not_change_status": str(execution.status or ""),
            "must_not_invent_paths": True,
            "must_not_expose_raw_fields": True,
            "must_not_turn_failure_into_success": True,
        },
    }
    if plan is not None:
        payload["intent"] = {
            "action": plan.action,
            "tool_name": plan.tool_name,
            "confidence_bucket": "high" if plan.confidence >= 0.8 else "mid" if plan.confidence >= 0.55 else "low",
            "source": plan.source,
        }
    if command is not None:
        payload["command_debug"] = {"tool_name": command.tool_name, "debug": bool(command.debug)}
    return payload


def _build_result_formatter_prompt(facts: Mapping[str, Any]) -> list[dict[str, str]]:
    persona = str(facts.get("persona") or "default")
    persona_rules = {
        "yangyang": "秧秧：温柔、简洁，像给漂♂总递小纸条；可以自然称呼漂♂总，但不要卖萌过度。",
        "yaya": "娅娅：利落、活泼，可以轻微吐槽；不要攻击用户，不泄密。",
        "isaac": "I叔：工程师短报文，可靠、干脆；不要冷冰冰 dump 字段。",
        "default": "默认：自然、简短、清楚。",
    }.get(persona, "默认：自然、简短、清楚。")
    return [
        {
            "role": "system",
            "content": (
                "你是 Owner 工程工具箱的结果润色器，只把已执行工具的结构化事实改写成自然中文。"
                "你不是工具执行器，不能改变事实，不能新增执行结果，不能把失败/拦截/需要确认写成成功。"
                "输出 1 到 2 句，默认不超过 80 个中文字符；必要时可保留列表项目。"
                "禁止输出 raw 字段、JSON、Markdown 表格、tool=/risk=/reason=/confidence= 等内部字段。"
                "禁止输出 /opt、/AstrBot、/etc、/root、.env、token、secret、password 等敏感路径或字段。"
                "若事实不足，只能基于 base_text 轻润色。"
                f"风格：{persona_rules}"
            ),
        },
        {
            "role": "user",
            "content": json.dumps({"facts": facts}, ensure_ascii=False, sort_keys=True),
        },
    ]


async def _call_result_formatter_provider(provider: ToolboxResultFormatterProvider, facts: dict[str, Any], context: dict[str, Any]) -> str:
    result = provider(facts, context)
    if inspect.isawaitable(result):
        result = await result  # type: ignore[assignment]
    return str(result or "")


async def _format_toolbox_reply_with_llm_if_enabled(
    gate: ToolboxGateResult,
    execution: ToolboxExecutionResult,
    *,
    command: ToolboxCommand | None = None,
    config: Any | None = None,
    persona: str | None = None,
    model_router: Any | None = None,
    result_formatter_provider: ToolboxResultFormatterProvider | None = None,
    original_text: str = "",
    plan: ToolboxIntentPlan | None = None,
    base_reply: str = "",
) -> str | None:
    persona_name = _persona_from_config(config, persona)
    base = base_reply or _format_toolbox_execution_natural(gate, execution)
    base_persona = _format_natural_with_persona({"gate": gate, "execution": execution, "base_text": base}, persona=persona_name)
    facts = _facts_from_execution(gate, execution, base_persona)
    if not _result_formatter_enabled(config):
        return None
    if _raw_report_requested(command, config):
        return None
    if not _result_formatter_safe_for_llm(gate, execution, facts):
        return None
    llm_facts = _facts_for_llm_formatter(gate, execution, command=command, plan=plan, base_text=base_persona, persona=persona_name, original_text=original_text)
    context = {
        "schema_version": "owner_toolbox.result_formatter_context.v1.20260608",
        "persona": persona_name,
        "safety_policy": "facts_only_no_sensitive_no_raw",
    }
    raw_text = ""
    try:
        if result_formatter_provider is not None:
            raw_text = await _call_result_formatter_provider(result_formatter_provider, llm_facts, context)
        elif model_router is not None:
            timeout = _config_get_int(config, "owner_toolbox_result_llm_formatter_timeout_seconds", 12, minimum=1, maximum=60)
            tier = str(_config_get(config, "owner_toolbox_result_llm_formatter_tier", "v4_flash") or "v4_flash")
            response_text, _actual_tier = await asyncio.wait_for(
                model_router.call(tier, _build_result_formatter_prompt(llm_facts), temperature=0.35, session_id="owner_toolbox_result_formatter", timeout_bucket="progress", interaction_phase="tool_result_format", allow_streaming=False),
                timeout=timeout,
            )
            raw_text = str(response_text or "")
        else:
            return None
    except Exception:
        return None
    max_chars = _config_get_int(config, "owner_toolbox_result_llm_formatter_max_output_chars", 220, minimum=40, maximum=1000)
    cleaned = _persona_safety_scrub(raw_text, facts, persona_name).strip()
    cleaned = re.sub(r"```.*?```", "", cleaned, flags=re.DOTALL).strip()
    cleaned = re.sub(r"^[-*]\s*", "", cleaned).strip()
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip("，,；;：: ") + "。"
    if not cleaned:
        return None
    # Do not allow a model to drop critical numeric/list facts for simple executor outputs.
    tool = execution.tool_name
    if tool == "python" and str(llm_facts.get("value") or "") and str(llm_facts.get("value")) not in cleaned:
        return None
    if tool == "list_dir" and llm_facts.get("empty") and not any(word in cleaned for word in ("空", "没有", "无内容")):
        return None
    for item in list(llm_facts.get("items") or [])[:3]:
        if item and item not in cleaned and tool == "list_dir":
            return None
    return cleaned


async def format_toolbox_reply_async(
    gate: ToolboxGateResult,
    execution: ToolboxExecutionResult,
    *,
    command: ToolboxCommand | None = None,
    config: Any | None = None,
    persona: str | None = None,
    model_router: Any | None = None,
    result_formatter_provider: ToolboxResultFormatterProvider | None = None,
    original_text: str = "",
    plan: ToolboxIntentPlan | None = None,
) -> str:
    if _raw_report_requested(command, config):
        return _format_toolbox_raw_reply(gate, execution)
    base = _format_toolbox_execution_natural(gate, execution)
    llm_reply = await _format_toolbox_reply_with_llm_if_enabled(
        gate,
        execution,
        command=command,
        config=config,
        persona=persona,
        model_router=model_router,
        result_formatter_provider=result_formatter_provider,
        original_text=original_text,
        plan=plan,
        base_reply=base,
    )
    if llm_reply:
        return llm_reply
    return format_owner_toolbox_result_for_user(gate, execution, command=command, config=config, persona=persona)

def format_toolbox_reply(
    gate: ToolboxGateResult,
    execution: ToolboxExecutionResult,
    *,
    command: ToolboxCommand | None = None,
    config: Any | None = None,
    persona: str | None = None,
) -> str:
    if _raw_report_requested(command, config):
        return _format_toolbox_raw_reply(gate, execution)
    return format_owner_toolbox_result_for_user(gate, execution, command=command, config=config, persona=persona)


__all__ = [
    "ToolboxCommand",
    "ToolboxGateResult",
    "ToolboxExecutionResult",
    "ToolboxHandleResult",
    "ToolboxIntentPlan",
    "parse_toolbox_command",
    "parse_toolbox_intent_plan",
    "evaluate_toolbox_gate",
    "execute_toolbox_command",
    "format_toolbox_reply",
    "format_toolbox_reply_async",
    "format_owner_toolbox_result_for_user",
    "_normalize_persona",
    "_format_natural_with_persona",
    "_apply_persona_style",
    "handle_owner_engineering_toolbox_message",
    "handle_owner_engineering_toolbox_message_nl_async",
]
