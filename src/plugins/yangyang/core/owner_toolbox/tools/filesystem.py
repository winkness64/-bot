from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from ..config import _config_get_int
from ..constants import DEFAULT_MAX_LIST_ENTRIES, DEFAULT_MAX_READ_BYTES
from ..parser import _split_first_word
from ..paths import _resolve_user_path
from ..results import _result, _truncate
from ..types import OwnerToolboxLightResult


def handle_list(config: Any, argmap: Mapping[str, Any] | dict[str, Any], *, root: Path, max_output: int, tool: str = "list") -> OwnerToolboxLightResult:
    path_arg = argmap.get("path") or (argmap.get("_argv") or ["."])[0]
    ok, path, rel, reason = _resolve_user_path(path_arg, root)
    if not ok or path is None:
        return _result(allowed=False, reason=reason, reply=f"路径解析失败：{reason}", tool_name=tool)
    if not path.exists():
        return _result(allowed=False, reason="path_not_found", reply="路径不存在。", tool_name=tool)
    if not path.is_dir():
        return _result(allowed=False, reason="not_directory", reply="不是目录。", tool_name=tool)
    limit = _config_get_int(config, "owner_toolbox_light_max_list_entries", DEFAULT_MAX_LIST_ENTRIES, minimum=1, maximum=5000)
    lines: list[str] = [f"list path={rel}"]
    for idx, child in enumerate(sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))):
        if idx >= limit:
            lines.append(f"...[truncated entries over {limit}]")
            break
        marker = "dir" if child.is_dir() else "file"
        try:
            size = child.stat().st_size if child.is_file() else 0
        except Exception:
            size = 0
        try:
            child_rel = child.resolve(strict=False).relative_to(root).as_posix()
        except Exception:
            child_rel = child.resolve(strict=False).as_posix()
        lines.append(f"{marker}\t{child_rel}\t{size}")
    abs_path = path.resolve(strict=False).as_posix()
    output = _truncate("\n".join([f"abs_path={abs_path}"] + lines), max_output)
    return _result(reason="ok", reply=output, tool_name=tool, output=output, data={"path": rel, "abs_path": abs_path})


def handle_read_or_log_tail(config: Any, argmap: Mapping[str, Any] | dict[str, Any], *, root: Path, max_output: int, tool: str) -> OwnerToolboxLightResult:
    argv = argmap.get("_argv") or []
    path_arg = argmap.get("path") or (argv[0] if argv else "")
    if not path_arg:
        return _result(allowed=False, reason="missing_path", reply="缺 path。", tool_name=tool)
    ok, path, rel, reason = _resolve_user_path(path_arg, root)
    if not ok or path is None:
        return _result(allowed=False, reason=reason, reply=f"路径解析失败：{reason}", tool_name=tool)
    if not path.exists() or not path.is_file():
        return _result(allowed=False, reason="file_not_found", reply="文件不存在。", tool_name=tool)
    max_bytes = _config_get_int(config, "owner_toolbox_light_max_read_bytes", DEFAULT_MAX_READ_BYTES, minimum=1, maximum=5 * 1024 * 1024)
    text = path.read_bytes()[:max_bytes].decode("utf-8", errors="replace")
    all_lines = text.splitlines()
    if tool == "read":
        start_line = int(argmap.get("start_line") or (argv[1] if len(argv) >= 2 else 1) or 1)
        wanted = int(argmap.get("lines") or (argv[2] if len(argv) >= 3 else 120) or 120)
        start_idx = max(0, start_line - 1)
        selected = all_lines[start_idx : start_idx + max(1, wanted)]
        body = [f"{start_idx + idx + 1}: {line}" for idx, line in enumerate(selected)]
        abs_path = path.resolve(strict=False).as_posix()
        output = _truncate("\n".join([f"read path={rel} abs_path={abs_path} lines={len(selected)}"] + body), max_output)
        return _result(reason="ok", reply=output, tool_name=tool, output=output, data={"path": rel, "abs_path": abs_path, "lines": len(selected)})
    wanted = int(argmap.get("lines") or (argv[1] if len(argv) >= 2 else 80) or 80)
    selected = all_lines[-max(1, wanted) :]
    abs_path = path.resolve(strict=False).as_posix()
    output = _truncate("\n".join([f"log_tail path={rel} abs_path={abs_path} lines={len(selected)}"] + selected), max_output)
    return _result(reason="ok", reply=output, tool_name=tool, output=output, data={"path": rel, "abs_path": abs_path, "lines": len(selected)})


def handle_write(argmap: Mapping[str, Any] | dict[str, Any], *, root: Path, tool: str = "write") -> OwnerToolboxLightResult:
    argv = argmap.get("_argv") or []
    path_arg = argmap.get("path") or (argv[0] if argv else "")
    content = argmap.get("content")
    if content is None and len(argv) >= 2:
        content = " ".join(argv[1:])
    if content is None and argmap.get("_raw"):
        path_arg, content = _split_first_word(str(argmap.get("_raw") or ""))
    if not path_arg:
        return _result(allowed=False, reason="missing_path", reply="缺 path。", tool_name=tool)
    ok, path, rel, reason = _resolve_user_path(path_arg, root, for_write=True)
    if not ok or path is None:
        return _result(allowed=False, reason=reason, reply=f"路径解析失败：{reason}", tool_name=tool)
    append = bool(argmap.get("append", False))
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as fp:
        fp.write(str(content or ""))
    abs_path = path.resolve(strict=False).as_posix()
    output = f"write path={rel} abs_path={abs_path} bytes={len(str(content or '').encode('utf-8'))} append={str(append).lower()}"
    return _result(reason="ok", reply=output, tool_name=tool, output=output, data={"path": rel, "abs_path": abs_path, "append": append}, allowed=True)
