#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

OUTPUT_DIR="dist"
PACKAGE_NAME=""
INCLUDE_TESTS=1
DRY_RUN=0
CHECK_ONLY=0

usage() {
  cat <<'USAGE'
Usage: bash scripts/build_host_handoff_package.sh [options]

Build a safe host handoff tar.gz package for host-side / laptop-side NoneBot MVP testing.

Options:
  --dry-run            Print include/exclude plan only; do not generate files
  --check-only         Check whether the project is safe to package; do not generate files
  --output-dir DIR     Output directory (default: dist)
  --name NAME          Fixed base package name without extension
  --include-tests      Include tests/ (default)
  --no-tests           Exclude tests/
  -h, --help           Show this help
USAGE
}

log() {
  printf '[HOST_HANDOFF_PACKAGE] %s\n' "$1"
}

fail() {
  printf '[HOST_HANDOFF_PACKAGE][FAIL] %s\n' "$1" >&2
  exit 1
}

warn() {
  printf '[HOST_HANDOFF_PACKAGE][WARN] %s\n' "$1" >&2
}

pass() {
  printf '[HOST_HANDOFF_PACKAGE][PASS] %s\n' "$1"
}

cleanup_outputs() {
  rm -f -- "${PACKAGE_PATH:-}" "${MANIFEST_PATH:-}" "${SHA_PATH:-}" 2>/dev/null || true
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    --check-only)
      CHECK_ONLY=1
      shift
      ;;
    --output-dir)
      [ "$#" -ge 2 ] || fail '--output-dir requires a directory path'
      OUTPUT_DIR="$2"
      shift 2
      ;;
    --name)
      [ "$#" -ge 2 ] || fail '--name requires a package base name'
      PACKAGE_NAME="$2"
      shift 2
      ;;
    --include-tests)
      INCLUDE_TESTS=1
      shift
      ;;
    --no-tests)
      INCLUDE_TESTS=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      fail "unknown argument: $1"
      ;;
  esac
done

case "$OUTPUT_DIR" in
  "") fail 'output directory cannot be empty' ;;
esac

if [ -z "$PACKAGE_NAME" ]; then
  PACKAGE_NAME="yangyang_nonebot_mvp_host_handoff_$(date +%Y%m%d-%H%M%S)"
fi

OUTPUT_DIR_REL="$OUTPUT_DIR"
OUTPUT_DIR_ABS=$(python3 - <<'PY' "$ROOT_DIR" "$OUTPUT_DIR_REL"
import os, sys
print(os.path.abspath(os.path.join(sys.argv[1], sys.argv[2])))
PY
)

PACKAGE_PATH="$OUTPUT_DIR_ABS/${PACKAGE_NAME}.tar.gz"
MANIFEST_PATH="$OUTPUT_DIR_ABS/${PACKAGE_NAME}.MANIFEST.txt"
SHA_PATH="$OUTPUT_DIR_ABS/${PACKAGE_NAME}.sha256"

if [ "$DRY_RUN" -eq 1 ] && [ "$CHECK_ONLY" -eq 1 ]; then
  fail '--dry-run and --check-only cannot be used together'
fi

INCLUDE_ROOTS=(
  "bot.py"
  "src"
  "scripts"
  "README.md"
  "docs"
  "deploy"
  ".env.example"
  "pyproject.toml"
  "PROJECT_PROGRESS.md"
)
if [ "$INCLUDE_TESTS" -eq 1 ]; then
  INCLUDE_ROOTS+=("tests")
fi

EXCLUDE_DIRS=(
  ".git"
  ".venv"
  "venv"
  "__pycache__"
  ".pytest_cache"
  "logs"
  "dist"
  "backups"
  "src/backups"
  "src/plugins/yangyang/data"
)

EXCLUDE_SUFFIXES=(
  ".db"
  ".sqlite"
  ".sqlite3"
  ".log"
  ".pyc"
  ".tmp"
  ".bak"
  ".corrupted"
)

is_path_within() {
  local path="$1"
  local prefix="$2"
  case "$path" in
    "$prefix"|"$prefix"/*) return 0 ;;
    *) return 1 ;;
  esac
}

should_exclude_rel() {
  local rel="$1"
  local lower
  lower=$(printf '%s' "$rel" | tr '[:upper:]' '[:lower:]')

  if [ "$rel" = ".env" ] || is_path_within "$rel" ".env"; then
    return 0
  fi

  if [ "$rel" != ".env.example" ]; then
    case "$lower" in
      *token*|*secret*|*apikey*|*api_key*|*password*)
        return 0
        ;;
    esac
  fi

  local part
  IFS='/' read -r -a parts <<< "$rel"
  for part in "${parts[@]}"; do
    local part_lower
    part_lower=$(printf '%s' "$part" | tr '[:upper:]' '[:lower:]')
    case "$part_lower" in
      .git|.venv|venv|__pycache__|.pytest_cache|logs|dist|backups)
        return 0
        ;;
      *.backup-*|*.backup|*.bak|*.bak.*|*.corrupted|*.before_*)
        return 0
        ;;
    esac
  done

  if is_path_within "$rel" "src/backups"; then
    return 0
  fi
  if is_path_within "$rel" "src/plugins/yangyang/data"; then
    return 0
  fi

  case "$rel" in
    src/plugins/*.backup-*|src/plugins/*.backup-*/*|src/plugins/yangyang/core/isaac_agent/memory.jsonl)
      return 0
      ;;
  esac

  local suffix
  for suffix in "${EXCLUDE_SUFFIXES[@]}"; do
    case "$lower" in
      *"$suffix")
        return 0
        ;;
    esac
  done

  return 1
}

print_plan() {
  log "Project root: $ROOT_DIR"
  log "Output dir: $OUTPUT_DIR_ABS"
  log "Package base name: $PACKAGE_NAME"
  log "Include tests: $INCLUDE_TESTS"
  log 'Include roots:'
  local item
  for item in "${INCLUDE_ROOTS[@]}"; do
    printf '  + %s\n' "$item"
  done
  log 'Exclude rules:'
  printf '  - .env\n'
  printf '  - .venv/ venv/ __pycache__/ .pytest_cache/ .git/ logs/ dist/ backups/ src/backups/ src/plugins/yangyang/data/\n'
  printf '  - *.db *.sqlite *.sqlite3 *.log *.pyc *.tmp *.bak *.corrupted *.backup-* *.before_*\n'
  printf '  - *token* *secret* *apikey* *api_key* *password* (except .env.example)\n'
}

collect_files() {
  local include
  local found=0
  for include in "${INCLUDE_ROOTS[@]}"; do
    if [ ! -e "$include" ]; then
      case "$include" in
        docs|deploy|.env.example|PROJECT_PROGRESS.md|bot.py)
          warn "optional include path missing: $include"
          continue
          ;;
        *)
          fail "required include path missing: $include"
          ;;
      esac
    fi
    if [ -f "$include" ]; then
      if ! should_exclude_rel "$include"; then
        printf '%s\n' "$include"
        found=1
      fi
      continue
    fi
    while IFS= read -r path; do
      found=1
      printf '%s\n' "$path"
    done < <(find "$include" \
      \( -type d \( -name '.git' -o -name '.venv' -o -name 'venv' -o -name '__pycache__' -o -name '.pytest_cache' -o -name 'logs' -o -name 'dist' -o -name 'backups' \) -prune \) -o \
      -type f -print | sed 's#^\./##' | while IFS= read -r rel; do
        if ! should_exclude_rel "$rel"; then
          printf '%s\n' "$rel"
        fi
      done)
  done
}

print_plan

TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"; cleanup_outputs' ERR INT TERM
FILE_LIST="$TMP_DIR/file_list.txt"
SORTED_FILE_LIST="$TMP_DIR/file_list.sorted.txt"
TAR_LIST="$TMP_DIR/tar_list.txt"

collect_files > "$FILE_LIST"
if [ ! -s "$FILE_LIST" ]; then
  fail 'no files matched for packaging'
fi
sort -u "$FILE_LIST" > "$SORTED_FILE_LIST"

log 'Candidate files to include:'
cat "$SORTED_FILE_LIST"

PRECHECK_ISSUES=0
while IFS= read -r rel; do
  if should_exclude_rel "$rel"; then
    printf '[HOST_HANDOFF_PACKAGE][FAIL] sensitive or excluded path matched before package: %s\n' "$rel" >&2
    PRECHECK_ISSUES=1
  fi
done < "$SORTED_FILE_LIST"

[ "$PRECHECK_ISSUES" -eq 0 ] || fail 'pre-package safety scan failed'
pass 'pre-package safety scan passed'

if grep -Fxq '.env.example' "$SORTED_FILE_LIST"; then
  pass '.env.example will be included'
else
  fail '.env.example missing from package file list'
fi

if [ "$DRY_RUN" -eq 1 ]; then
  pass 'dry-run completed; no package generated'
  rm -rf "$TMP_DIR"
  trap - ERR INT TERM
  exit 0
fi

if [ "$CHECK_ONLY" -eq 1 ]; then
  pass 'check-only completed; package eligibility passed'
  rm -rf "$TMP_DIR"
  trap - ERR INT TERM
  exit 0
fi

mkdir -p "$OUTPUT_DIR_ABS"
rm -f -- "$PACKAGE_PATH" "$MANIFEST_PATH" "$SHA_PATH"

log "Building tar.gz: $PACKAGE_PATH"
tar -czf "$PACKAGE_PATH" -T "$SORTED_FILE_LIST"

tar -tzf "$PACKAGE_PATH" | sed 's#^\./##' | sort -u > "$TAR_LIST"
cp "$TAR_LIST" "$MANIFEST_PATH"

POSTCHECK_ISSUES=0
while IFS= read -r rel; do
  if should_exclude_rel "$rel"; then
    printf '[HOST_HANDOFF_PACKAGE][FAIL] sensitive or excluded path found after package: %s\n' "$rel" >&2
    POSTCHECK_ISSUES=1
  fi
done < "$TAR_LIST"

if ! grep -Fxq '.env.example' "$TAR_LIST"; then
  printf '[HOST_HANDOFF_PACKAGE][FAIL] packaged tar missing .env.example\n' >&2
  POSTCHECK_ISSUES=1
fi

if [ "$POSTCHECK_ISSUES" -ne 0 ]; then
  cleanup_outputs
  fail 'post-package safety scan failed; generated artifacts removed'
fi
pass 'post-package safety scan passed'

if command -v sha256sum >/dev/null 2>&1; then
  (cd "$OUTPUT_DIR_ABS" && sha256sum "$(basename "$PACKAGE_PATH")") > "$SHA_PATH.tmp"
elif command -v shasum >/dev/null 2>&1; then
  (cd "$OUTPUT_DIR_ABS" && shasum -a 256 "$(basename "$PACKAGE_PATH")") > "$SHA_PATH.tmp"
else
  cleanup_outputs
  fail 'sha256 tool not found (need sha256sum or shasum)'
fi
sed "s#$(basename "$PACKAGE_PATH")#$PACKAGE_PATH#" "$SHA_PATH.tmp" > "$SHA_PATH"
rm -f "$SHA_PATH.tmp"

pass "package created: $PACKAGE_PATH"
pass "manifest created: $MANIFEST_PATH"
pass "sha256 created: $SHA_PATH"

rm -rf "$TMP_DIR"
trap - ERR INT TERM
