from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run_step(name: str, command: list[str]) -> bool:
    print(f"[CHECK] {name}")
    result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True)
    if result.stdout:
        print(result.stdout.rstrip())
    if result.stderr:
        print(result.stderr.rstrip())
    if result.returncode == 0:
        print(f"[PASS] {name}\n")
        return True
    print(f"[FAIL] {name} (exit={result.returncode})\n")
    return False


def main() -> int:
    steps = [
        ("python compileall", [sys.executable, "-m", "compileall", "src", "tests", "scripts"]),
        ("mock pipeline test", [sys.executable, "tests/mock_pipeline_test.py"]),
    ]
    ok = True
    for name, command in steps:
        ok = run_step(name, command) and ok
    print("[SUMMARY] PASS" if ok else "[SUMMARY] FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
