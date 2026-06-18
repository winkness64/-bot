from __future__ import annotations

import re
import shlex
from typing import Any

from .constants import AVAILABLE_TOOLS, REGISTERED_SLASH_TOKENS, TOOL_ALIASES
from .types import SlashCommand, ToolInvocation, ToolLoopMaxStepsCommand


def _message_text(message_or_text: Any) -> str:
    text = getattr(message_or_text, "text", None)
    if not str(text or "").strip():
        raw_content = getattr(message_or_text, "raw_content", None)
        if raw_content is not None:
            text = raw_content
    if text is None:
        text = message_or_text
    return str(text or "")

def _split_argv(text: str) -> tuple[str, ...]:
    raw = str(text or "").strip()
    if not raw:
        return ()
    try:
        return tuple(str(item) for item in shlex.split(raw) if str(item).strip())
    except Exception:
        return tuple(item for item in re.split(r"\s+", raw) if item)

def _split_first_word(text: str) -> tuple[str, str]:
    raw = str(text or "").strip()
    if not raw:
        return "", ""
    match = re.match(r"^(\S+)(?:\s+(.*))?$", raw, flags=re.S)
    if not match:
        return raw, ""
    return match.group(1), (match.group(2) or "").strip()

def _normalize_tool_name(name: Any) -> str:
    raw = str(name or "").strip()
    lowered = raw.lower()
    return TOOL_ALIASES.get(lowered, TOOL_ALIASES.get(raw, lowered))

def parse_slash_command(text_or_message: Any, *, registered_tokens: set[str] | frozenset[str] | None = None) -> SlashCommand | None:
    """Parse explicit slash fallback commands.

    Only a trimmed message whose first character is "/" and whose first token is
    registered will match.  Examples: "/toolbox status" and "/toolbox/status"
    match; "/root/xxx 记一下" and plain chat do not.
    """
    raw = _message_text(text_or_message).strip()
    if not raw.startswith("/"):
        return None

    registered = {str(item).casefold() for item in (registered_tokens or REGISTERED_SLASH_TOKENS)}
    body = raw[1:]
    match = re.match(r"^([^\s/:：]+)(.*)$", body, flags=re.S)
    if not match:
        return None
    token = match.group(1).casefold()
    if token not in registered:
        return None

    tail = match.group(2) or ""
    if tail and not (tail[0].isspace() or tail[0] in "/:："):
        # /toolboxStatus must not be treated as /toolbox.
        return None
    rest = tail.lstrip("/:：").strip()
    return SlashCommand(token=token, rest=rest, argv=_split_argv(rest), raw_text=raw)

def _usage() -> str:
    return (
        "Owner Toolbox Light 用法：\n"
        "/toolbox status\n"
        "/toolbox max_steps [N>=1，owner 可控无上限]\n"
        "/toolbox list .\n"
        "/toolbox read README.md [start] [lines]\n"
        "/toolbox log_tail logs/app.log [lines]\n"
        "/toolbox python 1+1\n"
        "/toolbox shell pwd\n"
        "/toolbox write notes/a.txt 内容\n"
        "/toolbox pack src dist/src.tar.gz\n"
        "注册 slash token：/help /toolbox /isaac /i叔 /I叔 /艾萨克 /confirm"
    )

def is_legacy_toolbox_prefix(text_or_message: Any) -> bool:
    text = _message_text(text_or_message).strip()
    return text.startswith(("工具箱", "toolbox", "Toolbox", "TOOLBOX"))

def _invocation_from_toolbox_text(text: str, *, source: str = "slash") -> ToolInvocation:
    raw = str(text or "").strip()
    if not raw:
        return ToolInvocation("status", {}, source, raw)
    first, rest = _split_first_word(raw)
    tool = _normalize_tool_name(first)
    if tool not in AVAILABLE_TOOLS:
        # Treat bare /toolbox foo as status/help-ish instead of guessing unsafe magic.
        return ToolInvocation("status", {}, source, raw)
    if tool == "shell":
        return ToolInvocation(tool, {"command": rest}, source, raw)
    if tool == "python":
        return ToolInvocation(tool, {"code": rest}, source, raw)
    if tool == "write":
        argv = _split_argv(rest)
        if argv:
            # Preserve spaces in content by splitting once instead of relying only on shlex.
            path, content = _split_first_word(rest)
            return ToolInvocation(tool, {"path": path, "content": content}, source, raw)
        return ToolInvocation(tool, {}, source, raw)
    argv = _split_argv(rest)
    if tool == "list":
        return ToolInvocation(tool, {"path": argv[0] if argv else "."}, source, raw)
    if tool == "read":
        return ToolInvocation(
            tool,
            {
                "path": argv[0] if argv else "",
                "start_line": int(argv[1]) if len(argv) >= 2 and str(argv[1]).isdigit() else 1,
                "lines": int(argv[2]) if len(argv) >= 3 and str(argv[2]).isdigit() else 120,
            },
            source,
            raw,
        )
    if tool == "log_tail":
        return ToolInvocation(
            tool,
            {"path": argv[0] if argv else "", "lines": int(argv[1]) if len(argv) >= 2 and str(argv[1]).isdigit() else 80},
            source,
            raw,
        )
    if tool == "pack":
        if len(argv) >= 2:
            return ToolInvocation(tool, {"paths": argv[:-1], "output": argv[-1]}, source, raw)
        return ToolInvocation(tool, {"paths": argv or ["."]}, source, raw)
    return ToolInvocation(tool, {}, source, raw)

def parse_natural_tool_invocation(text_or_message: Any) -> ToolInvocation | None:
    """Tiny deterministic owner-private NL wrapper.

    This is deliberately small: it avoids keyword blacklists and only catches
    clear tool-shaped requests.  Native LLM tool loop can replace it later.
    """
    text = _message_text(text_or_message).strip()
    if not text:
        return None
    compact = re.sub(r"\s+", " ", text)
    lowered = compact.lower()

    # Legacy/handy prefixes from the old toolbox, now routed through Light.
    for prefix in ("工具箱", "toolbox", "Toolbox", "TOOLBOX"):
        if compact.startswith(prefix):
            rest = compact[len(prefix):].strip(" ：:,，")
            return _invocation_from_toolbox_text(rest or "status", source="natural_prefix")

    if lowered in {"status", "toolbox status", "工具箱状态", "看一下状态", "看下状态", "状态"}:
        return ToolInvocation("status", {}, "natural", text)

    first, rest = _split_first_word(compact)
    first_tool = _normalize_tool_name(first)
    if first_tool in AVAILABLE_TOOLS:
        return _invocation_from_toolbox_text(compact, source="natural_direct")

    m = re.match(r"^(?:列一下|列出|看看|看一下|看下)?(?:目录|文件列表)\s*(.*)$", compact)
    if m:
        return ToolInvocation("list", {"path": (m.group(1) or ".").strip() or "."}, "natural", text)

    m = re.match(r"^(?:读|读取|打开|看一下|看下|看看)\s+(.+)$", compact)
    if m:
        return ToolInvocation("read", {"path": m.group(1).strip()}, "natural", text)

    m = re.match(r"^(?:看一下|看下|看看|tail)?\s*(?:日志|log)\s+(.+)$", compact, flags=re.I)
    if m:
        return ToolInvocation("log_tail", {"path": m.group(1).strip(), "lines": 80}, "natural", text)

    m = re.match(r"^(?:用\s*)?python\s*(?:算一下|跑一下|执行|运行|:|：)?\s*(.+)$", compact, flags=re.I)
    if m:
        return ToolInvocation("python", {"code": m.group(1).strip()}, "natural", text)

    m = re.match(r"^(?:shell|sh|cmd|执行命令|跑命令|运行命令)\s*(?:[:：])?\s*(.+)$", compact, flags=re.I)
    if m:
        return ToolInvocation("shell", {"command": m.group(1).strip()}, "natural", text)

    m = re.match(r"^(?:写入|写)\s+(\S+)\s+(.+)$", compact, flags=re.S)
    if m:
        return ToolInvocation("write", {"path": m.group(1).strip(), "content": m.group(2)}, "natural", text)

    m = re.match(r"^(?:打包|压缩|pack)\s+(.+?)(?:\s+(?:到|为|->)\s+|\s+)(\S+\.tar\.gz)$", compact, flags=re.I)
    if m:
        paths = [item for item in _split_argv(m.group(1)) if item]
        return ToolInvocation("pack", {"paths": paths or [m.group(1).strip()], "output": m.group(2).strip()}, "natural", text)

    return None

def parse_owner_tool_loop_max_steps_command(text_or_message: Any) -> ToolLoopMaxStepsCommand | None:
    """Parse only the explicit slash fallback for max_steps.

    Natural-language max_steps query/set is intentionally not parsed here: it
    must go through the native LLM tool loop and call get_tool_loop_max_steps /
    set_tool_loop_max_steps by tool_call.
    """
    text = _message_text(text_or_message).strip()
    if not text:
        return None
    slash = parse_slash_command(text)
    if slash is None or slash.token != "toolbox":
        return None
    rest = slash.rest.strip()
    m = re.match(r"^(?:max_steps|max-steps|maxsteps)(?:\s+([+-]?\d+))?$", rest, flags=re.I)
    if not m:
        return None
    return ToolLoopMaxStepsCommand("set" if m.group(1) else "query", int(m.group(1)) if m.group(1) else None, text)

def is_owner_tool_loop_max_steps_intent(text_or_message: Any) -> bool:
    return parse_owner_tool_loop_max_steps_command(text_or_message) is not None

