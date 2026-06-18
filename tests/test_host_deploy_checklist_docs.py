from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHECKLIST = ROOT / "deploy/host_deploy_checklist.md"
README = ROOT / "README.md"
HOST_DOC = ROOT / "docs/host_nonebot_install.md"
SMOKE_DOC = ROOT / "docs/current_session_smoke_example.md"

SENSITIVE_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{10,}"),
    re.compile(r'(?i)token\s*=\s*[\'\"]?[A-Za-z0-9_\-]{12,}'),
    re.compile(r'(?i)secret\s*=\s*[\'\"]?[A-Za-z0-9_\-]{12,}'),
    re.compile(r'(?i)api[_-]?key\s*=\s*[\'\"]?[A-Za-z0-9_\-]{12,}'),
]

ALLOWED_PLACEHOLDERS = {
    "ONEBOT_ACCESS_TOKEN",
    "ONEBOT_SECRET",
    "OPENAI_API_KEY",
    "DEEPSEEK_API_KEY",
}


def assert_true(value: bool, message: str) -> None:
    if not value:
        raise AssertionError(message)


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def scrub_placeholders(text: str) -> str:
    for item in ALLOWED_PLACEHOLDERS:
        text = text.replace(item, "")
    return text


def test_checklist_exists() -> None:
    assert_true(CHECKLIST.exists(), f"missing file: {CHECKLIST}")


def test_checklist_contains_required_sections_and_commands() -> None:
    text = read_text(CHECKLIST)
    required = [
        "## A. 前置原则",
        "## B. 宿主机准备",
        "## C. 预检",
        "## D. 创建 venv 与安装 NoneBot",
        "## E. `.env` 准备",
        "## F. OneBot / NapCat / Lagrange 对接占位",
        "## G. systemd 部署",
        "## H. 首次真实 smoke 流程",
        "## I. 回滚与故障处理",
        "docs/napcat_onebot_setup.md",
        "bash scripts/host_preflight_check.sh",
        "bash scripts/host_setup_nonebot_env.sh --dry-run",
        "bash scripts/host_setup_nonebot_env.sh",
        ".venv/bin/python scripts/check_napcat_onebot_config.py",
        ".venv/bin/python scripts/check_nonebot_runtime_ready.py",
        "python3 scripts/toggle_current_session_smoke.py --enable --yes",
        "python3 scripts/toggle_current_session_smoke.py --disable --yes",
        "python3 scripts/inspect_owner_action_audit.py --tail-follow",
        "systemctl daemon-reload",
        "systemctl enable yangyang-nonebot.service",
        "systemctl start yangyang-nonebot.service",
        "systemctl status yangyang-nonebot.service",
        "journalctl -u yangyang-nonebot.service",
        "/yy-smoke-current 回应小维",
    ]
    for item in required:
        assert_true(item in text, f"checklist missing: {item}")


def test_readme_links_checklist() -> None:
    text = read_text(README)
    assert_true("deploy/host_deploy_checklist.md" in text, "README missing checklist link")


def test_host_install_doc_links_checklist() -> None:
    text = read_text(HOST_DOC)
    assert_true("deploy/host_deploy_checklist.md" in text, "host install doc missing checklist link")


def test_smoke_doc_links_checklist_and_connection_note() -> None:
    text = read_text(SMOKE_DOC)
    assert_true("deploy/host_deploy_checklist.md" in text, "smoke doc missing checklist link")
    assert_true("真实 smoke 必须等 NoneBot runtime 与 OneBot 已连接后再做" in text, "smoke doc missing connection warning")


def test_no_real_token_secret_or_api_key_leak() -> None:
    for path in [CHECKLIST, README, HOST_DOC, SMOKE_DOC]:
        text = scrub_placeholders(read_text(path))
        for pattern in SENSITIVE_PATTERNS:
            match = pattern.search(text)
            if match is not None:
                raise AssertionError(f"possible sensitive value found in {path}: {match.group(0)}")


def test_readme_pip_install_context_mentions_host_and_venv() -> None:
    text = read_text(README)
    needle = 'pip install -e ".[nonebot]"'
    assert_true(needle in text, "README missing pip install command")
    idx = text.index(needle)
    window = text[max(0, idx - 220): idx + 260]
    assert_true(("宿主机" in window or "旧笔记本 Ubuntu" in window) and ".venv" in window, "README pip install context missing host/.venv guidance")


if __name__ == "__main__":
    test_checklist_exists()
    test_checklist_contains_required_sections_and_commands()
    test_readme_links_checklist()
    test_host_install_doc_links_checklist()
    test_smoke_doc_links_checklist_and_connection_note()
    test_no_real_token_secret_or_api_key_leak()
    test_readme_pip_install_context_mentions_host_and_venv()
    print("PASS")
