from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/host_nonebot_install.md"
SETUP_SH = ROOT / "scripts/host_setup_nonebot_env.sh"
PREFLIGHT_SH = ROOT / "scripts/host_preflight_check.sh"
SYSTEMD = ROOT / "deploy/systemd/yangyang-nonebot.service.example"
README = ROOT / "README.md"


SENSITIVE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{10,}"),
    re.compile(r"(?i)token\s*=\s*['\"]?[A-Za-z0-9_\-]{12,}"),
    re.compile(r"(?i)secret\s*=\s*['\"]?[A-Za-z0-9_\-]{12,}"),
]

ALLOWED_PLACEHOLDERS = {
    "ONEBOT_ACCESS_TOKEN=",
    "ONEBOT_SECRET=",
    "OPENAI_API_KEY=",
    "DEEPSEEK_API_KEY=",
}


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_required_files_exist() -> None:
    for path in [DOC, SETUP_SH, PREFLIGHT_SH, SYSTEMD]:
        assert_true(path.exists(), f"missing file: {path}")


def test_shell_scripts_bash_n() -> None:
    for path in [SETUP_SH, PREFLIGHT_SH]:
        result = subprocess.run(["bash", "-n", str(path)], cwd=ROOT, capture_output=True, text=True)
        assert_true(result.returncode == 0, f"bash -n failed for {path}: {result.stderr}")


def test_systemd_template_contains_required_fields() -> None:
    text = read_text(SYSTEMD)
    assert_true("WorkingDirectory=/opt/yangyang_nonebot_mvp" in text, "missing WorkingDirectory")
    assert_true(
        "ExecStart=/opt/yangyang_nonebot_mvp/.venv/bin/python /opt/yangyang_nonebot_mvp/bot.py" in text,
        "missing ExecStart",
    )
    assert_true("EnvironmentFile=/opt/yangyang_nonebot_mvp/.env" in text, "missing EnvironmentFile")
    assert_true("Restart=on-failure" in text, "missing Restart=on-failure")


def test_readme_contains_host_install_entry() -> None:
    text = read_text(README)
    assert_true("Host-side NoneBot Install" in text, "README missing host install heading")
    assert_true("docs/host_nonebot_install.md" in text, "README missing host install doc link")
    assert_true("bash scripts/host_preflight_check.sh" in text, "README missing preflight command")
    assert_true("bash scripts/host_setup_nonebot_env.sh --dry-run" in text, "README missing dry-run command")


def test_no_real_token_or_secret_leak() -> None:
    for path in [DOC, SETUP_SH, PREFLIGHT_SH, SYSTEMD, README]:
        text = read_text(path)
        for placeholder in ALLOWED_PLACEHOLDERS:
            text = text.replace(placeholder, "")
        for pattern in SENSITIVE_PATTERNS:
            match = pattern.search(text)
            if match is not None:
                raise AssertionError(
                    f"possible sensitive value found in {path}: {match.group(0)}"
                )


if __name__ == "__main__":
    test_required_files_exist()
    test_shell_scripts_bash_n()
    test_systemd_template_contains_required_fields()
    test_readme_contains_host_install_entry()
    test_no_real_token_or_secret_leak()
    print("PASS")
