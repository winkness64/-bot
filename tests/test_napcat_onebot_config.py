from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/napcat_onebot_setup.md"
ENV_EXAMPLE = ROOT / ".env.example"
README = ROOT / "README.md"
CHECKLIST = ROOT / "deploy/host_deploy_checklist.md"
SCRIPT = ROOT / "scripts/check_napcat_onebot_config.py"

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
    "<YOUR_ONEBOT_ACCESS_TOKEN>",
    "<YOUR_ONEBOT_SECRET>",
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


def run_script(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=str(cwd or ROOT),
        text=True,
        capture_output=True,
        env=dict(os.environ),
    )


def test_doc_exists_and_contains_required_terms() -> None:
    text = read_text(DOC)
    required = [
        "反向 WebSocket",
        "NapCat",
        "/onebot/v11/ws",
        "不要贴群",
        "测试号 / 测试群",
    ]
    for item in required:
        assert_true(item in text, f"napcat doc missing: {item}")


def test_env_example_contains_napcat_partition_and_keys() -> None:
    text = read_text(ENV_EXAMPLE)
    required = [
        "# NapCat / OneBot v11 接入占位",
        "DRIVER=~fastapi+~httpx+~websockets",
        "HOST=127.0.0.1",
        "PORT=8080",
        "LOG_LEVEL=INFO",
        "ONEBOT_ACCESS_TOKEN=",
        "ONEBOT_SECRET=",
        "NAPCAT_CONNECTION_MODE=reverse_ws",
        "NAPCAT_REVERSE_WS_URL=ws://127.0.0.1:8080/onebot/v11/ws",
    ]
    for item in required:
        assert_true(item in text, f".env.example missing: {item}")


def test_script_runs_and_prints_header() -> None:
    result = run_script([])
    assert_true(result.returncode == 0, f"script should exit 0 in current project, got {result.returncode}: {result.stdout} {result.stderr}")
    assert_true("[NAPCAT_ONEBOT_CONFIG_CHECK]" in result.stdout, "missing config check header")


def test_missing_env_warns_but_exits_zero() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "bot.py").write_text((ROOT / "bot.py").read_text(encoding="utf-8"), encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text((ROOT / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8")
        (tmp_path / ".env.example").write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
        result = run_script(["--root", str(tmp_path)])
        assert_true(result.returncode == 0, f"missing .env should only WARN, got {result.returncode}")
        lowered = result.stdout.lower()
        assert_true("[warn]" in lowered and ".env" in lowered, "missing .env warning not found")


def test_env_token_value_not_printed() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "bot.py").write_text((ROOT / "bot.py").read_text(encoding="utf-8"), encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text((ROOT / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8")
        (tmp_path / ".env.example").write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
        secret = "SUPER_SECRET_TOKEN_123456789"
        (tmp_path / ".env").write_text(
            "DRIVER=~fastapi+~httpx+~websockets\nHOST=127.0.0.1\nPORT=8080\nONEBOT_ACCESS_TOKEN=" + secret + "\nONEBOT_SECRET=ANOTHER_SECRET_123456789\nNAPCAT_CONNECTION_MODE=reverse_ws\n",
            encoding="utf-8",
        )
        result = run_script(["--root", str(tmp_path)])
        assert_true(result.returncode == 0, f"script should still pass with local env: {result.returncode}")
        assert_true(secret not in result.stdout, "script leaked token value")
        assert_true("ANOTHER_SECRET_123456789" not in result.stdout, "script leaked secret value")
        assert_true("ONEBOT_ACCESS_TOKEN" in result.stdout, "token key state missing")


def test_port_non_numeric_fails() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        (tmp_path / "bot.py").write_text((ROOT / "bot.py").read_text(encoding="utf-8"), encoding="utf-8")
        (tmp_path / "pyproject.toml").write_text((ROOT / "pyproject.toml").read_text(encoding="utf-8"), encoding="utf-8")
        (tmp_path / ".env.example").write_text((ROOT / ".env.example").read_text(encoding="utf-8"), encoding="utf-8")
        (tmp_path / ".env").write_text(
            "DRIVER=~fastapi+~httpx+~websockets\nHOST=127.0.0.1\nPORT=abc\nONEBOT_ACCESS_TOKEN=placeholder_token\nONEBOT_SECRET=\n",
            encoding="utf-8",
        )
        result = run_script(["--root", str(tmp_path)])
        assert_true(result.returncode == 1, f"non numeric port should fail, got {result.returncode}")
        assert_true("PORT is not numeric" in result.stdout, "expected port failure message missing")


def test_readme_and_checklist_link_doc_and_script() -> None:
    readme_text = read_text(README)
    checklist_text = read_text(CHECKLIST)
    assert_true("docs/napcat_onebot_setup.md" in readme_text, "README missing napcat doc link")
    assert_true("python3 scripts/check_napcat_onebot_config.py" in readme_text, "README missing project command")
    assert_true(".venv/bin/python scripts/check_napcat_onebot_config.py" in readme_text, "README missing host command")
    assert_true("docs/napcat_onebot_setup.md" in checklist_text, "checklist missing napcat doc link")
    assert_true(".venv/bin/python scripts/check_napcat_onebot_config.py" in checklist_text, "checklist missing config check command")
    assert_true("通过 `.venv/bin/python scripts/check_napcat_onebot_config.py` 后，再继续启动 NoneBot" in checklist_text, "checklist missing start-after-check warning")


def test_no_real_token_secret_api_key_plaintext() -> None:
    for path in [DOC, ENV_EXAMPLE, README, CHECKLIST, SCRIPT]:
        text = scrub_placeholders(read_text(path))
        for pattern in SENSITIVE_PATTERNS:
            match = pattern.search(text)
            if match is not None:
                raise AssertionError(f"possible sensitive value found in {path}: {match.group(0)}")


if __name__ == "__main__":
    test_doc_exists_and_contains_required_terms()
    test_env_example_contains_napcat_partition_and_keys()
    test_script_runs_and_prints_header()
    test_missing_env_warns_but_exits_zero()
    test_env_token_value_not_printed()
    test_port_non_numeric_fails()
    test_readme_and_checklist_link_doc_and_script()
    test_no_real_token_secret_api_key_plaintext()
    print("PASS")
