from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
ROOT = SCRIPT_PATH.parents[1]
HEADER = "[NAPCAT_ONEBOT_CONFIG_CHECK]"
REQUIRED_ENV_KEYS = ["DRIVER", "HOST", "PORT", "ONEBOT_ACCESS_TOKEN"]
OPTIONAL_ENV_KEYS = ["ONEBOT_SECRET", "LOG_LEVEL"]
DOC_HELPER_KEYS = ["NAPCAT_CONNECTION_MODE", "NAPCAT_REVERSE_WS_URL"]
PLACEHOLDER_MARKERS = {
    "",
    "<YOUR_ONEBOT_ACCESS_TOKEN>",
    "<YOUR_ONEBOT_SECRET>",
    "<PLACEHOLDER>",
    "CHANGE_ME",
    "your_token_here",
    "your_secret_here",
}
SENSITIVE_LINE_PATTERNS = [
    re.compile(r"(?i)^\s*(onebot_access_token|onebot_secret|api[_-]?key|token|secret)\s*=\s*([^\s#]+)\s*$"),
]


@dataclass
class CheckResult:
    level: str
    message: str


class Reporter:
    def __init__(self) -> None:
        self.results: list[CheckResult] = []

    def pass_(self, message: str) -> None:
        self.results.append(CheckResult("PASS", message))

    def warn(self, message: str) -> None:
        self.results.append(CheckResult("WARN", message))

    def fail(self, message: str) -> None:
        self.results.append(CheckResult("FAIL", message))

    def print(self) -> None:
        print(HEADER)
        for item in self.results:
            print(f"[{item.level}] {item.message}")
        summary = self.summary()
        print(f"[SUMMARY] pass={summary['PASS']} warn={summary['WARN']} fail={summary['FAIL']}")

    def summary(self) -> dict[str, int]:
        return {
            "PASS": sum(1 for item in self.results if item.level == "PASS"),
            "WARN": sum(1 for item in self.results if item.level == "WARN"),
            "FAIL": sum(1 for item in self.results if item.level == "FAIL"),
        }

    def exit_code(self) -> int:
        return 1 if any(item.level == "FAIL" for item in self.results) else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Read-only NapCat / OneBot v11 config readiness check")
    parser.add_argument("--root", default=str(ROOT), help="Project root path")
    parser.add_argument("--env", default=".env", help="Env file path, relative to --root by default")
    parser.add_argument("--example", default=".env.example", help="Example env file path, relative to --root by default")
    return parser


def resolve_path(root: Path, raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute():
        return path
    return root / path


def safe_read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def parse_env_file(path: Path) -> dict[str, str]:
    data: dict[str, str] = {}
    for raw_line in safe_read_text(path).splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        data[key.strip()] = value.strip()
    return data


def looks_like_real_secret(value: str) -> bool:
    cleaned = value.strip().strip('"').strip("'")
    if cleaned in PLACEHOLDER_MARKERS:
        return False
    if not cleaned:
        return False
    if any(marker in cleaned.lower() for marker in ["placeholder", "your_", "change_me", "example", "dummy", "test"]):
        return False
    return len(cleaned) >= 16 and re.fullmatch(r"[A-Za-z0-9_\-]+", cleaned) is not None


def check_files(bot_py: Path, pyproject: Path, env_example: Path, env_file: Path, reporter: Reporter, root: Path) -> None:
    for path in [bot_py, pyproject, env_example]:
        if path.exists():
            reporter.pass_(f"file {path.relative_to(root)} exists")
        else:
            reporter.fail(f"file {path.relative_to(root)} missing")
    if env_file.exists():
        reporter.pass_(f"file {env_file.relative_to(root)} exists")
    else:
        reporter.warn(f"file {env_file.relative_to(root)} missing; create from .env.example before host runtime")


def check_dependencies(pyproject: Path, reporter: Reporter) -> None:
    text = safe_read_text(pyproject).lower()
    if "nonebot2" in text:
        reporter.pass_("pyproject.toml declares nonebot2")
    else:
        reporter.fail("pyproject.toml missing nonebot2")
    if "nonebot-adapter-onebot" in text:
        reporter.pass_("pyproject.toml declares nonebot-adapter-onebot")
    else:
        reporter.fail("pyproject.toml missing nonebot-adapter-onebot")


def check_bot_py(bot_py: Path, reporter: Reporter) -> None:
    if not bot_py.exists():
        reporter.fail("bot.py static checks skipped because file is missing")
        return
    text = safe_read_text(bot_py)
    try:
        ast.parse(text, filename=str(bot_py))
        reporter.pass_("bot.py ast parse ok")
    except Exception as exc:
        reporter.fail(f"bot.py ast parse failed: {exc.__class__.__name__}: {exc}")
        return

    if "load_dotenv" in text and ".env" in text:
        reporter.pass_("bot.py loads .env")
    else:
        reporter.fail("bot.py missing .env loading")

    if "register_adapter(OneBotV11Adapter)" in text or "register_adapter(OneBotV11Adapter" in text:
        reporter.pass_("bot.py registers OneBot v11 adapter")
    else:
        reporter.fail("bot.py missing OneBot v11 adapter registration")

    if "load_plugins" in text and "plugins" in text:
        reporter.pass_("bot.py loads plugin directory")
    else:
        reporter.fail("bot.py missing plugin directory loading")


def check_env_example(env_example: Path, reporter: Reporter) -> None:
    if not env_example.exists():
        reporter.fail(".env.example checks skipped because file is missing")
        return
    text = safe_read_text(env_example)
    data = parse_env_file(env_example)

    missing = [key for key in REQUIRED_ENV_KEYS if key not in data]
    if missing:
        reporter.fail(".env.example missing required keys: " + ", ".join(missing))
    else:
        reporter.pass_(".env.example includes required NoneBot / OneBot keys")

    optional_present = [key for key in OPTIONAL_ENV_KEYS if key in data]
    if optional_present:
        reporter.pass_(".env.example includes optional keys: " + ", ".join(optional_present))
    else:
        reporter.warn(".env.example missing optional keys: " + ", ".join(OPTIONAL_ENV_KEYS))

    if any(key in text for key in DOC_HELPER_KEYS):
        reporter.pass_(".env.example includes NapCat helper hints")
    else:
        reporter.warn(".env.example missing NapCat helper hints such as NAPCAT_CONNECTION_MODE / NAPCAT_REVERSE_WS_URL")

    helper_url = data.get("NAPCAT_REVERSE_WS_URL", "")
    if helper_url:
        check_reverse_ws_url(helper_url, reporter, source=".env.example NAPCAT_REVERSE_WS_URL")

    check_example_sensitive_values(env_example, reporter)


def check_example_sensitive_values(path: Path, reporter: Reporter) -> None:
    flagged = []
    for raw_line in safe_read_text(path).splitlines():
        for pattern in SENSITIVE_LINE_PATTERNS:
            match = pattern.match(raw_line.strip())
            if not match:
                continue
            value = match.group(2).strip().strip('"').strip("'")
            if looks_like_real_secret(value):
                flagged.append(match.group(1))
    if flagged:
        reporter.fail(f"{path.name} may contain real secret-like values for keys: {', '.join(sorted(set(flagged)))}")
    else:
        reporter.pass_(f"{path.name} does not appear to contain real token/secret values")


def report_token_state(data: dict[str, str], key: str, reporter: Reporter, source_name: str) -> None:
    if key not in data:
        reporter.fail(f"{source_name} missing key: {key}")
        return
    value = data.get(key, "")
    if value == "":
        reporter.warn(f"{source_name} key {key} present but empty")
    else:
        reporter.pass_(f"{source_name} key {key} present and non-empty")


def check_reverse_ws_url(value: str, reporter: Reporter, source: str) -> None:
    if value.startswith("ws://") or value.startswith("wss://"):
        reporter.pass_(f"{source} uses ws:// or wss://")
    else:
        reporter.warn(f"{source} should start with ws:// or wss://")
        return
    lowered = value.lower()
    if "onebot" in lowered or "v11" in lowered:
        reporter.pass_(f"{source} path contains onebot or v11 hint")
    else:
        reporter.warn(f"{source} path does not contain onebot or v11 hint")


def check_env_file(env_file: Path, reporter: Reporter) -> None:
    if not env_file.exists():
        reporter.warn(".env not found; host runtime values were not checked")
        return

    data = parse_env_file(env_file)
    missing = [key for key in REQUIRED_ENV_KEYS if key not in data]
    if missing:
        reporter.fail(".env missing required keys: " + ", ".join(missing))
    else:
        reporter.pass_(".env includes required NoneBot / OneBot keys")

    host_value = data.get("HOST")
    if host_value == "0.0.0.0":
        reporter.warn(".env HOST=0.0.0.0; confirm firewall and public exposure risk")
    elif host_value:
        reporter.pass_(".env HOST present")

    port_value = data.get("PORT", "")
    if not port_value.isdigit():
        reporter.fail(".env PORT is not numeric")
    else:
        port_num = int(port_value)
        if 1 <= port_num <= 65535:
            reporter.pass_(".env PORT looks valid")
        else:
            reporter.fail(".env PORT out of range")

    report_token_state(data, "ONEBOT_ACCESS_TOKEN", reporter, ".env")
    if "ONEBOT_SECRET" in data:
        if data.get("ONEBOT_SECRET", "") == "":
            reporter.warn(".env key ONEBOT_SECRET present but empty")
        else:
            reporter.pass_(".env key ONEBOT_SECRET present and non-empty")
    else:
        reporter.warn(".env key ONEBOT_SECRET missing")

    if "NAPCAT_REVERSE_WS_URL" in data:
        check_reverse_ws_url(data["NAPCAT_REVERSE_WS_URL"], reporter, source=".env NAPCAT_REVERSE_WS_URL")

    mode = data.get("NAPCAT_CONNECTION_MODE")
    if mode is None:
        reporter.warn(".env missing NAPCAT_CONNECTION_MODE; recommended reverse_ws")
    elif mode.strip().lower() == "reverse_ws":
        reporter.pass_(".env NAPCAT_CONNECTION_MODE uses recommended reverse_ws")
    else:
        reporter.warn(".env NAPCAT_CONNECTION_MODE is not reverse_ws; reverse_ws is recommended")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()
    env_file = resolve_path(root, args.env)
    env_example = resolve_path(root, args.example)
    bot_py = root / "bot.py"
    pyproject = root / "pyproject.toml"

    reporter = Reporter()
    check_files(bot_py, pyproject, env_example, env_file, reporter, root)
    check_dependencies(pyproject, reporter)
    check_bot_py(bot_py, reporter)
    check_env_example(env_example, reporter)
    check_env_file(env_file, reporter)
    reporter.print()
    return reporter.exit_code()


if __name__ == "__main__":
    raise SystemExit(main())
