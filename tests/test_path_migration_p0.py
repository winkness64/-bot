import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_module(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, str(PROJECT_ROOT / rel))
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(mod)
    return mod


isaac_workspace_report = _load_module(
    "isaac_workspace_report_under_test",
    "src/plugins/yangyang/core/isaac_workspace_report.py",
)
runtime_compat = _load_module(
    "runtime_compat_under_test",
    "src/plugins/yangyang/core/runtime_compat.py",
)


def test_isaac_workspace_report_project_root_is_dynamic():
    expected = Path(isaac_workspace_report.__file__).resolve().parents[4]
    assert isaac_workspace_report.PROJECT_ROOT == expected
    assert isaac_workspace_report.PROJECT_ROOT.as_posix() != "/opt/yangyang_nonebot"


def test_isaac_workspace_report_format_uses_placeholder_not_absolute():
    text = isaac_workspace_report.format_workspace_report(
        {
            "project_name": "yangyang_nonebot",
            "directories": {},
            "audit": {},
            "recent_files": [],
        }
    )
    assert "/<fixed-runtime-root>/yangyang_nonebot" in text
    assert "/opt/yangyang_nonebot" not in text


def test_strip_legacy_project_root_prefix_exact_root():
    assert runtime_compat._strip_legacy_project_root_prefix(Path("/opt/yangyang_nonebot")) == Path(".")


def test_resolve_memory_root_normalizes_legacy_prefix(tmp_path):
    project_root = tmp_path / "yangyang_nonebot"
    data_dir = project_root / "src/plugins/yangyang/data"
    expected = project_root / "src/plugins/yangyang/data/memory"
    got = runtime_compat.resolve_memory_root(
        plugin_config={"memory_root": "/opt/yangyang_nonebot/src/plugins/yangyang/data/memory"},
        data_dir=data_dir,
        project_root=project_root,
        env={},
    )
    assert got == expected.resolve()


def test_resolve_memory_root_empty_value_uses_data_dir(tmp_path):
    data_dir = tmp_path / "data"
    got = runtime_compat.resolve_memory_root(plugin_config={"memory_root": ""}, data_dir=data_dir, env={})
    assert got == (data_dir / "memory").resolve()


def test_resolve_memory_root_relative_value_unchanged(tmp_path):
    data_dir = tmp_path / "data"
    got = runtime_compat.resolve_memory_root(plugin_config={"memory_root": "custom_memory"}, data_dir=data_dir, env={})
    assert got == (data_dir / "custom_memory").resolve()


def test_resolve_memory_root_unrelated_absolute_path_preserved(tmp_path):
    unrelated = tmp_path / "external_memory"
    got = runtime_compat.resolve_memory_root(plugin_config={"memory_root": str(unrelated)}, data_dir=tmp_path / "data", env={})
    assert got == unrelated.resolve()


def test_legacy_prefix_constant_is_stable():
    assert "/opt/yangyang_nonebot" in runtime_compat._LEGACY_PROJECT_ROOT_PREFIXES
