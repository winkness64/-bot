from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config import _utc_now
from ..constants import AVAILABLE_TOOLS, REGISTERED_SLASH_TOKENS
from ..results import _result
from ..types import OwnerToolboxLightResult


def handle_status(*, root: Path, tool: str = "status") -> OwnerToolboxLightResult:
    data = {
        "generated_at": _utc_now(),
        "default_cwd": str(root),
        "scope": "owner_private_host_filesystem",
        "sandbox": False,
        "tools": list(AVAILABLE_TOOLS),
        "slash_tokens": sorted(REGISTERED_SLASH_TOKENS),
    }
    output = (
        "Owner Toolbox Light 正常。\n"
        f"default_cwd={root}\n"
        "scope=owner_private_host_filesystem (no workspace sandbox, no keyword safety valve)\n"
        f"tools={','.join(AVAILABLE_TOOLS)}\n"
        "slash=/toolbox status | /toolbox max_steps 10 | /toolbox list . | /toolbox shell pwd"
    )
    return _result(reason="ok", reply="工具箱正常。", tool_name=tool, output=output, data=data)
