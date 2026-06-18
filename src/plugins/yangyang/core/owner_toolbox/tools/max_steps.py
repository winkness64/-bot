from __future__ import annotations

from typing import Any, Mapping

from ..config import get_owner_tool_loop_max_steps, set_owner_tool_loop_max_steps, TOOL_LOOP_MAX_STEPS_CONFIG_KEY
from ..results import _result
from ..types import OwnerToolboxLightResult


def handle_get_tool_loop_max_steps(config: Any, *, tool: str = "get_tool_loop_max_steps") -> OwnerToolboxLightResult:
    steps = get_owner_tool_loop_max_steps(config)
    output = f"max_steps={steps}"
    return _result(
        reason="ok",
        reply=str(steps),
        tool_name=tool,
        output=output,
        data={"max_steps": steps, "config_key": TOOL_LOOP_MAX_STEPS_CONFIG_KEY},
    )


def handle_set_tool_loop_max_steps(config: Any, argmap: Mapping[str, Any] | dict[str, Any], *, tool: str = "set_tool_loop_max_steps") -> OwnerToolboxLightResult:
    argv = argmap.get("_argv") or []
    raw_value = argmap.get("value")
    if raw_value is None and argv:
        raw_value = argv[0]
    if raw_value is None and argmap.get("_raw") is not None:
        raw_value = str(argmap.get("_raw") or "").strip()
    if raw_value is None or str(raw_value).strip() == "":
        return _result(allowed=False, reason="missing_value", reply="缺 value。", tool_name=tool)
    ok, steps, key = set_owner_tool_loop_max_steps(config, raw_value)
    output = f"max_steps={steps}"
    if ok:
        return _result(
            reason="ok",
            reply=str(steps),
            tool_name=tool,
            output=output,
            data={"max_steps": steps, "config_key": key},
        )
    return _result(
        allowed=False,
        reason="config_write_failed",
        reply="runtime_config write failed",
        tool_name=tool,
        output=output,
        data={"max_steps": steps, "config_key": key},
    )
