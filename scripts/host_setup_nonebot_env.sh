#!/usr/bin/env bash
set -euo pipefail

DRY_RUN=0
SKIP_CHECK=0
PYTHON_BIN="python3"

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --skip-check)
      SKIP_CHECK=1
      shift
      ;;
    --python)
      if [ "$#" -lt 2 ]; then
        echo "[ERROR] --python requires a path" >&2
        exit 2
      fi
      PYTHON_BIN="$2"
      shift 2
      ;;
    -h|--help)
      cat <<'USAGE'
Usage: bash scripts/host_setup_nonebot_env.sh [--dry-run] [--python PATH] [--skip-check]

Prepare host-side NoneBot virtualenv for this project.
This script should be run on the host / bare metal Ubuntu machine.
Do not use it as proof that the current Docker/container dev environment is suitable.
USAGE
      exit 0
      ;;
    *)
      echo "[ERROR] unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

run_cmd() {
  echo "+ $*"
  if [ "$DRY_RUN" -eq 1 ]; then
    return 0
  fi
  "$@"
}

printf '%s\n' '[INFO] Host-side NoneBot install prep script'
printf '%s\n' '[WARN] This script is intended for host / bare metal execution.'
printf '%s\n' '[WARN] Running it inside the current Docker/container dev environment is not recommended.'
printf '[INFO] Project root: %s\n' "$ROOT_DIR"
printf '[INFO] Python: %s\n' "$PYTHON_BIN"

if [ ! -f "pyproject.toml" ] || [ ! -f "bot.py" ]; then
  echo "[ERROR] Current directory does not look like project root: $ROOT_DIR" >&2
  exit 1
fi

run_cmd "$PYTHON_BIN" -m venv .venv
run_cmd .venv/bin/python -m pip install -U pip
run_cmd .venv/bin/python -m pip install -e ".[nonebot]"

if [ "$SKIP_CHECK" -eq 1 ]; then
  echo '[INFO] Skip runtime ready check by --skip-check'
else
  echo '[INFO] Running read-only runtime ready check after install.'
  echo '[INFO] FAIL/WARN output below is for visibility; this script will continue.'
  if [ "$DRY_RUN" -eq 1 ]; then
    echo "+ .venv/bin/python scripts/check_nonebot_runtime_ready.py"
  else
    set +e
    .venv/bin/python scripts/check_nonebot_runtime_ready.py
    CHECK_EXIT=$?
    set -e
    echo "[INFO] check_nonebot_runtime_ready.py exit code: $CHECK_EXIT"
  fi
fi

echo '[DONE] Host-side environment preparation steps completed.'
echo '[DONE] Bot was not started; OneBot was not connected; .env was not modified.'
