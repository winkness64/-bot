from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "deploy/napcat_reverse_ws_host_checklist.md"
README = ROOT / "README.md"
NAPCAT_DOC = ROOT / "docs/napcat_onebot_setup.md"
HOST_CHECKLIST = ROOT / "deploy/host_deploy_checklist.md"

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


def test_doc_exists() -> None:
    assert_true(DOC.exists(), f"missing file: {DOC}")


def test_doc_contains_required_strings() -> None:
    text = read_text(DOC)
    required = [
        "127.0.0.1:8080/onebot/v11/ws",
        "192.168",
        "HOST=0.0.0.0",
        "ONEBOT_ACCESS_TOKEN",
        "journalctl",
        "yangyang-nonebot.service",
        "回应小维",
        "toggle_current_session_smoke.py --disable --yes",
    ]
    for item in required:
        assert_true(item in text, f"doc missing: {item}")


def test_related_docs_link_new_checklist() -> None:
    for path in [README, NAPCAT_DOC, HOST_CHECKLIST]:
        text = read_text(path)
        assert_true(
            "deploy/napcat_reverse_ws_host_checklist.md" in text,
            f"missing checklist link in {path}",
        )


def test_doc_has_no_real_token_secret_or_api_key() -> None:
    text = scrub_placeholders(read_text(DOC))
    for pattern in SENSITIVE_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            raise AssertionError(f"possible sensitive value found in {DOC}: {match.group(0)}")


if __name__ == "__main__":
    test_doc_exists()
    test_doc_contains_required_strings()
    test_related_docs_link_new_checklist()
    test_doc_has_no_real_token_secret_or_api_key()
    print("PASS")
