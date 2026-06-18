from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping

from ..results import _result, _truncate
from ..types import OwnerToolboxLightResult


def _python_runner_code(code: str) -> str:
    """Print expression results while still supporting normal statements."""
    payload = json.dumps(str(code or ""))
    return (
        "import ast, json\n"
        f"code = json.loads({payload!r})\n"
        "try:\n"
        "    tree = ast.parse(code, mode='eval')\n"
        "except SyntaxError:\n"
        "    exec(compile(code, '<owner_toolbox_light>', 'exec'), {})\n"
        "else:\n"
        "    result = eval(compile(tree, '<owner_toolbox_light>', 'eval'), {})\n"
        "    if result is not None:\n"
        "        print(result)\n"
    )


def handle_shell_or_python(
    config: Any,
    argmap: Mapping[str, Any] | dict[str, Any],
    *,
    root: Path,
    max_output: int,
    timeout_func: Any,
    tool: str,
) -> OwnerToolboxLightResult:
    if tool == "shell":
        command = str(argmap.get("command") or argmap.get("_raw") or " ".join(argmap.get("_argv") or []) or "").strip()
        if not command:
            return _result(allowed=False, reason="missing_command", reply="缺 command。", tool_name=tool)
        proc = subprocess.run(
            command,
            shell=True,
            cwd=str(root),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout_func(config, argmap.get("timeout_seconds")),
            executable=os.environ.get("SHELL") or "/bin/bash",
        )
        output = _truncate((proc.stdout or "") + (proc.stderr or ""), max_output)
        reply = f"exit_code={proc.returncode}\n{output}".strip()
        return _result(
            allowed=proc.returncode == 0,
            reason="ok" if proc.returncode == 0 else "nonzero_exit",
            reply=reply,
            tool_name=tool,
            output=output,
            data={"exit_code": proc.returncode},
        )

    code = str(argmap.get("code") or argmap.get("_raw") or " ".join(argmap.get("_argv") or []) or "").strip()
    if not code:
        return _result(allowed=False, reason="missing_code", reply="缺 code。", tool_name=tool)
    run_code = _python_runner_code(code)
    proc = subprocess.run(
        ["python3", "-c", run_code],
        cwd=str(root),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout_func(config, argmap.get("timeout_seconds")),
    )
    output = _truncate((proc.stdout or "") + (proc.stderr or ""), max_output)
    reply = f"exit_code={proc.returncode}\n{output}".strip()
    return _result(
        allowed=proc.returncode == 0,
        reason="ok" if proc.returncode == 0 else "nonzero_exit",
        reply=reply,
        tool_name=tool,
        output=output,
        data={"exit_code": proc.returncode},
    )
