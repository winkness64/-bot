from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

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


def test_readme_contains_three_entry_titles_and_keywords() -> None:
    text = read_text(README)
    required = [
        "## README 首页三入口",
        "### 1. 开发 / 单测 / mock rehearsal（当前容器可执行）",
        "### 2. 宿主机部署（真实运行环境）",
        "### 3. 真实 current-session smoke（必须等 NoneBot + OneBot 已连接）",
    ]
    for item in required:
        assert_true(item in text, f"README missing: {item}")


def test_readme_contains_three_key_links() -> None:
    text = read_text(README)
    required = [
        "docs/host_nonebot_install.md",
        "deploy/host_deploy_checklist.md",
        "docs/napcat_onebot_setup.md",
        "docs/current_session_smoke_example.md",
    ]
    for item in required:
        assert_true(item in text, f"README missing link: {item}")


def test_readme_contains_runtime_and_install_warnings() -> None:
    text = read_text(README)
    assert_true(
        "当前 AstrBot/API 聊天窗口**不能替代** NoneBot runtime 的真实 `bot/event`" in text,
        "README missing bot/event warning",
    )
    assert_true(
        "不要在当前 AstrBot / Docker 容器执行真实安装" in text,
        "README missing container install warning",
    )


def test_readme_contains_real_smoke_behavior_notes() -> None:
    text = read_text(README)
    assert_true(
        "普通 `回应小维` 不会触发真实 smoke" in text,
        "README missing normal command smoke warning",
    )
    assert_true(
        "测试完成后立即执行 disable" in text or "测完后" in text,
        "README missing disable after test warning",
    )
    assert_true(
        "/yy-smoke-current 回应小维" in text,
        "README missing smoke command example",
    )


def test_readme_contains_required_command_examples() -> None:
    text = read_text(README)
    required = [
        "python3 scripts/check_project.py",
        "python3 scripts/check_napcat_onebot_config.py",
        "python3 scripts/run_current_session_smoke_rehearsal.py",
        "python3 scripts/run_current_session_smoke_rehearsal.py --mock-send",
        "bash scripts/host_preflight_check.sh",
        "bash scripts/host_setup_nonebot_env.sh --dry-run",
        "bash scripts/host_setup_nonebot_env.sh",
        ".venv/bin/python scripts/check_napcat_onebot_config.py",
        ".venv/bin/python scripts/check_nonebot_runtime_ready.py",
        ".venv/bin/python scripts/toggle_current_session_smoke.py --enable --yes",
        ".venv/bin/python scripts/check_current_session_smoke_ready.py",
        ".venv/bin/python scripts/inspect_owner_action_audit.py --tail-follow",
    ]
    for item in required:
        assert_true(item in text, f"README missing command: {item}")


def test_readme_contains_safe_statements() -> None:
    text = read_text(README)
    required = [
        "`current-session smoke` 默认关闭",
        "普通 owner action 不自动真发",
        "跨群 `send_group_message` 仍锁死",
    ]
    for item in required:
        assert_true(item in text, f"README missing safe statement: {item}")


def test_readme_has_no_real_token_secret_or_api_key() -> None:
    text = scrub_placeholders(read_text(README))
    for pattern in SENSITIVE_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            raise AssertionError(f"possible sensitive value found in README: {match.group(0)}")


if __name__ == "__main__":
    test_readme_contains_three_entry_titles_and_keywords()
    test_readme_contains_three_key_links()
    test_readme_contains_runtime_and_install_warnings()
    test_readme_contains_real_smoke_behavior_notes()
    test_readme_contains_required_command_examples()
    test_readme_contains_safe_statements()
    test_readme_has_no_real_token_secret_or_api_key()
    print("PASS")
