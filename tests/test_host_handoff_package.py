from __future__ import annotations

import shutil
import subprocess
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/build_host_handoff_package.sh"
DOC = ROOT / "docs/host_handoff_package.md"
README = ROOT / "README.md"
CHECKLIST = ROOT / "deploy/host_deploy_checklist.md"
TEST_OUTPUT = ROOT / "dist/test_handoff"
PACKAGE_NAME = "test_handoff_package"
MANIFEST = TEST_OUTPUT / f"{PACKAGE_NAME}.MANIFEST.txt"
TAR_PATH = TEST_OUTPUT / f"{PACKAGE_NAME}.tar.gz"
SHA_PATH = TEST_OUTPUT / f"{PACKAGE_NAME}.sha256"
FORBIDDEN_EXACT = {".env"}
FORBIDDEN_SEGMENTS = [".venv", "logs", "dist", "backups", "src/plugins/yangyang/data"]
FORBIDDEN_SUFFIXES = [".db", ".sqlite", ".sqlite3", ".log", ".bak", ".corrupted"]
FORBIDDEN_KEYWORDS = ["token", "secret", "apikey", "api_key", "password"]


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def run_bash(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
    )


def is_forbidden_path(raw_path: str) -> bool:
    path = raw_path.removeprefix("./")
    lowered = path.lower()
    if lowered in FORBIDDEN_EXACT:
        return True
    parts = lowered.split("/")
    if any(segment in parts for segment in FORBIDDEN_SEGMENTS):
        return True
    if any(lowered.endswith(suffix) for suffix in FORBIDDEN_SUFFIXES):
        return True
    if any(part.endswith((".backup", ".bak")) or ".backup-" in part or ".before_" in part for part in parts):
        return True
    if path != ".env.example" and any(keyword in lowered for keyword in FORBIDDEN_KEYWORDS):
        return True
    return False


def test_script_exists_and_bash_n_ok() -> None:
    assert_true(SCRIPT.exists(), f"missing script: {SCRIPT}")
    result = subprocess.run(["bash", "-n", str(SCRIPT)], cwd=str(ROOT), text=True, capture_output=True)
    assert_true(result.returncode == 0, f"bash -n failed: {result.stderr}")


def test_doc_exists() -> None:
    assert_true(DOC.exists(), f"missing doc: {DOC}")


def test_readme_and_checklist_link_doc() -> None:
    readme_text = read_text(README)
    checklist_text = read_text(CHECKLIST)
    assert_true("docs/host_handoff_package.md" in readme_text, "README missing host_handoff_package doc link")
    assert_true("bash scripts/build_host_handoff_package.sh --dry-run" in readme_text, "README missing dry-run example")
    assert_true("bash scripts/build_host_handoff_package.sh" in readme_text, "README missing build example")
    assert_true("docs/host_handoff_package.md" in checklist_text, "host checklist missing host_handoff_package doc link")
    assert_true("通过宝塔下载交接包" in checklist_text, "host checklist missing bt handoff wording")


def test_dry_run_returns_zero() -> None:
    result = run_bash(["--dry-run"])
    assert_true(result.returncode == 0, f"dry-run failed: {result.stdout}\n{result.stderr}")


def test_check_only_returns_zero() -> None:
    result = run_bash(["--check-only"])
    assert_true(result.returncode == 0, f"check-only failed: {result.stdout}\n{result.stderr}")


def test_build_package_and_manifest_are_safe() -> None:
    if TEST_OUTPUT.exists():
        shutil.rmtree(TEST_OUTPUT)
    result = run_bash(["--name", PACKAGE_NAME, "--output-dir", str(TEST_OUTPUT.relative_to(ROOT))])
    assert_true(result.returncode == 0, f"package build failed: {result.stdout}\n{result.stderr}")
    assert_true(TAR_PATH.exists(), f"missing tar: {TAR_PATH}")
    assert_true(MANIFEST.exists(), f"missing manifest: {MANIFEST}")
    assert_true(SHA_PATH.exists(), f"missing sha256: {SHA_PATH}")

    manifest_paths = [line.strip() for line in read_text(MANIFEST).splitlines() if line.strip()]
    assert_true(".env.example" in manifest_paths, "manifest missing .env.example")
    for path in manifest_paths:
        assert_true(not is_forbidden_path(path), f"manifest contains forbidden path: {path}")
    assert_true(not any(path.startswith("src/plugins/yangyang/data/") for path in manifest_paths), "manifest contains runtime data directory")
    assert_true("src/plugins/yangyang/core/isaac_agent/memory.jsonl" not in manifest_paths, "manifest contains agent runtime memory")

    with tarfile.open(TAR_PATH, "r:gz") as tar:
        names = sorted(member.name.removeprefix("./") for member in tar.getmembers() if member.name and member.isfile())
    assert_true(any(name == ".env.example" for name in names), "tar missing .env.example")
    for path in names:
        assert_true(not is_forbidden_path(path), f"tar contains forbidden path: {path}")
    assert_true(not any(path.startswith("src/plugins/yangyang/data/") for path in names), "tar contains runtime data directory")
    assert_true("src/plugins/yangyang/core/isaac_agent/memory.jsonl" not in names, "tar contains agent runtime memory")


def cleanup() -> None:
    if TEST_OUTPUT.exists():
        shutil.rmtree(TEST_OUTPUT)


if __name__ == "__main__":
    try:
        test_script_exists_and_bash_n_ok()
        test_doc_exists()
        test_readme_and_checklist_link_doc()
        test_dry_run_returns_zero()
        test_check_only_returns_zero()
        test_build_package_and_manifest_are_safe()
        print("PASS")
    finally:
        cleanup()
