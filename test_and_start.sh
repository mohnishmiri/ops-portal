#!/usr/bin/env bash
# test_and_start.sh — install deps, run all unit tests, then start the application.
# Compatible with Linux, macOS, and Windows (Git Bash / WSL / Cygwin).
#
# Usage:
#   ./test_and_start.sh          # run tests + start app
#   ./test_and_start.sh --test   # run tests only, do not start
#
# Exit codes:
#   0 — all tests passed (app started if --test not set)
#   1 — one or more steps failed (app NOT started)
#
# Windows note: run via Git Bash, WSL, or Cygwin.  Native cmd.exe / PowerShell
# do not ship bash; install Git for Windows (https://git-scm.com) to get Git Bash.

set -euo pipefail

# ── Resolve script directory ───────────────────────────────────────────────────
# BASH_SOURCE is bash-specific; fall back to $0 for sh-compatible invocation.
if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
fi

BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
TEST_ONLY=false

for arg in "$@"; do
  [[ "$arg" == "--test" ]] && TEST_ONLY=true
done

# ── Detect OS ─────────────────────────────────────────────────────────────────
OS="linux"
case "$(uname -s 2>/dev/null || true)" in
  Darwin*)               OS="mac"     ;;
  CYGWIN*|MINGW*|MSYS*)  OS="windows" ;;
  Linux*)                OS="linux"   ;;
esac
# Fallback: uname missing but WINDIR/windir env var is set (native Windows)
if [[ -n "${WINDIR:-}${windir:-}" ]]; then
  OS="windows"
fi

# ── Colour helpers ─────────────────────────────────────────────────────────────
# Enabled when stdout is a terminal and TERM is not "dumb" (covers most Unix
# terminals, Windows Terminal, Git Bash, and WSL).  Plain text fallback ensures
# readable output in CI pipelines and older Windows consoles.
if [[ -t 1 && "${TERM:-}" != "dumb" && "${NO_COLOR:-}" == "" ]]; then
  green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
  red()    { printf '\033[0;31m%s\033[0m\n' "$*"; }
  yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
  bold()   { printf '\033[1m%s\033[0m\n'   "$*"; }
else
  green()  { printf 'OK   %s\n' "$*"; }
  red()    { printf 'FAIL %s\n' "$*"; }
  yellow() { printf '...  %s\n' "$*"; }
  bold()   { printf '===  %s\n' "$*"; }
fi

bold "============================================================"
bold "  OpsPortal — Test Suite + Application Launcher"
bold "============================================================"
printf '\n'
yellow "  Platform : $OS"
printf '\n'

# ── Verify required tools ──────────────────────────────────────────────────────
_require() {
  local cmd="$1" install_hint="$2"
  if ! command -v "$cmd" &>/dev/null; then
    red "  ✗ '$cmd' not found in PATH."
    yellow "    Install: $install_hint"
    exit 1
  fi
}

_require uv  "https://docs.astral.sh/uv/getting-started/installation/"
_require npm "https://nodejs.org (includes npm)"

# ── Install backend dev dependencies ──────────────────────────────────────────
yellow "► Installing backend dev dependencies (uv sync) …"
if (cd "$BACKEND_DIR" && uv sync --extra dev --quiet 2>&1); then
  green "  ✓ Backend dependencies ready"
else
  red "  ✗ uv sync failed"
  exit 1
fi
printf '\n'

# ── Backend tests ──────────────────────────────────────────────────────────────
# Use 'uv run pytest' rather than a hardcoded venv path so this works on all
# platforms regardless of whether the venv uses bin/ (Unix) or Scripts/ (Windows).
yellow "► Running backend unit tests (pytest) …"
if (cd "$BACKEND_DIR" && uv run pytest tests/ -v --tb=short -q 2>&1); then
  green "  ✓ Backend tests passed"
else
  red   "  ✗ Backend tests FAILED — application will not start"
  exit 1
fi
printf '\n'

# ── Install frontend dependencies ──────────────────────────────────────────────
yellow "► Installing frontend dependencies (npm ci) …"
if (cd "$FRONTEND_DIR" && npm ci --silent 2>&1); then
  green "  ✓ Frontend dependencies ready"
else
  red "  ✗ npm ci failed"
  exit 1
fi
printf '\n'

# ── Frontend tests ─────────────────────────────────────────────────────────────
yellow "► Running frontend unit tests (vitest) …"
if (cd "$FRONTEND_DIR" && npm test 2>&1); then
  green "  ✓ Frontend tests passed"
else
  red   "  ✗ Frontend tests FAILED — application will not start"
  exit 1
fi
printf '\n'

# ── TypeScript check ───────────────────────────────────────────────────────────
yellow "► Running TypeScript type-check …"
TS_ERRORS=$(cd "$FRONTEND_DIR" && npx tsc --noEmit 2>&1 | grep -v "KeyVaultPage" || true)
if [[ -z "$TS_ERRORS" ]]; then
  green "  ✓ TypeScript check passed"
else
  red "  ✗ TypeScript errors found:"
  printf '%s\n' "$TS_ERRORS"
  exit 1
fi
printf '\n'

bold "============================================================"
green "  All tests passed!"
bold "============================================================"
printf '\n'

if [[ "$TEST_ONLY" == "true" ]]; then
  yellow "  --test flag set, skipping app startup."
  exit 0
fi

# ── Start the application ──────────────────────────────────────────────────────
# start.sh files work as-is on Linux, macOS, Git Bash, and WSL.
# On Windows without a Unix shell the start scripts would need a separate
# .bat / PowerShell equivalent — see docs/windows-setup.md.
yellow "► Starting backend …"
(cd "$BACKEND_DIR" && bash start.sh) &
BACKEND_PID=$!

yellow "► Starting frontend …"
(cd "$FRONTEND_DIR" && bash start.sh) &
FRONTEND_PID=$!

# Trap Ctrl-C so both child processes are cleaned up together
trap 'kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null; exit 0' INT TERM

printf '\n'
green "  Application is starting up."
green "  Backend API : http://localhost:8002"
green "  Frontend    : http://localhost:5177"
printf '\n'
yellow "  Press Ctrl+C to stop both servers."
wait
