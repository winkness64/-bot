from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tarfile
from typing import Any, Mapping

from ..config import _config_get_int
from ..constants import DEFAULT_MAX_PACK_FILES
from ..paths import _resolve_user_path
from ..results import _result
from ..types import OwnerToolboxLightResult


def handle_pack(config: Any, argmap: Mapping[str, Any] | dict[str, Any], *, root: Path, tool: str = "pack") -> OwnerToolboxLightResult:
    argv = argmap.get("_argv") or []
    raw_paths = argmap.get("paths") or argv[:-1] or ["."]
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    output_arg = argmap.get("output") or (argv[-1] if len(argv) >= 2 else "")
    if not output_arg:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_arg = f"dist/owner_toolbox_light_{stamp}.tar.gz"
    ok, out_path, out_rel, reason = _resolve_user_path(output_arg, root, for_write=True)
    if not ok or out_path is None:
        return _result(allowed=False, reason=reason, reply=f"路径解析失败：{reason}", tool_name=tool)
    max_files = _config_get_int(config, "owner_toolbox_light_max_pack_files", DEFAULT_MAX_PACK_FILES, minimum=1, maximum=20000)
    added = 0
    with tarfile.open(out_path, "w:gz") as tar:
        for raw_item in raw_paths:
            ok, item_path, item_rel, reason = _resolve_user_path(raw_item, root)
            if not ok or item_path is None or not item_path.exists():
                continue
            if item_path.is_file():
                if item_path.resolve(strict=False) == out_path.resolve(strict=False):
                    continue
                tar.add(item_path, arcname=item_rel)
                added += 1
            else:
                for child in sorted(item_path.rglob("*")):
                    if added >= max_files:
                        break
                    if child.is_file():
                        if child.resolve(strict=False) == out_path.resolve(strict=False):
                            continue
                        try:
                            arcname = child.resolve(strict=False).relative_to(root).as_posix()
                        except Exception:
                            arcname = child.resolve(strict=False).as_posix()
                        tar.add(child, arcname=arcname)
                        added += 1
            if added >= max_files:
                break
    abs_output = out_path.resolve(strict=False).as_posix()
    output = f"pack output={out_rel} abs_output={abs_output} files={added}"
    return _result(reason="ok", reply=output, tool_name=tool, output=output, data={"output": out_rel, "abs_output": abs_output, "files": added})
