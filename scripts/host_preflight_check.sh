#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

warn() {
  printf '[WARN] %s\n' "$1"
}

pass() {
  printf '[PASS] %s\n' "$1"
}

info() {
  printf '[INFO] %s\n' "$1"
}

printf '%s\n' '[HOST_PREFLIGHT_CHECK]'
info "Project root: $ROOT_DIR"
info 'This script is read-only: no install, no start, no message send.'

if [ -f '/.dockerenv' ]; then
  warn 'Detected /.dockerenv; this looks like a container, not the final host.'
fi
if grep -Eqi '(docker|containerd|kubepods|podman|lxc)' /proc/1/cgroup 2>/dev/null; then
  warn 'Detected container markers in /proc/1/cgroup; host-side execution is recommended.'
fi

if command -v python3 >/dev/null 2>&1; then
  pass "python3 found: $(command -v python3)"
else
  warn 'python3 not found'
fi

if command -v pip >/dev/null 2>&1; then
  pass "pip found: $(command -v pip)"
else
  warn 'pip not found (host_setup can still use python -m pip after venv creation)'
fi

if command -v git >/dev/null 2>&1; then
  pass "git found: $(command -v git)"
else
  warn 'git not found'
fi

if [ -f 'pyproject.toml' ] && [ -f 'bot.py' ] && [ -d 'src/plugins/yangyang' ]; then
  pass 'Current directory looks like project root'
else
  warn 'Current directory may not be the project root; expected pyproject.toml, bot.py, src/plugins/yangyang'
fi

if [ -d '.venv' ]; then
  pass '.venv exists'
else
  warn '.venv does not exist yet'
fi

if [ -f '.env' ]; then
  pass '.env exists (values not printed)'
else
  warn '.env missing; copy from .env.example on the host before real runtime'
fi

info 'Port configuration reminder only; this script does not probe or bind ports.'
info 'Check .env for HOST / PORT / ONEBOT_WS_URL / ONEBOT_API_ROOT / ONEBOT_WS_REVERSE_URL as needed.'
info 'If NapCat / Lagrange is used, verify address, token, and direction mode on the host manually.'
