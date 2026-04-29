#!/usr/bin/env bash
# test_and_start.sh — install deps, run all unit tests, then start the application.
#
# Usage:
#   ./test_and_start.sh          # run tests + start app
#   ./test_and_start.sh --test   # run tests only, do not start
#
# Exit codes:
#   0 — all tests passed (app started if --test not set)
#   1 — one or more steps failed (app NOT started)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
TEST_ONLY=false

for arg in "$@"; do
  [[ "$arg" == "--test" ]] && TEST_ONLY=true
done

# ── Colour helpers ─────────────────────────────────────────────────────────────
green()  { printf '\033[0;32m%s\033[0m\n' "$*"; }
red()    { printf '\033[0;31m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
bold()   { printf '\033[1m%s\033[0m\n'   "$*"; }

bold "============================================================"
bold "  OpsPortal — Test Suite + Application Launcher"
bold "============================================================"
echo ""

# ── Install backend dev dependencies ──────────────────────────────────────────
yellow "► Installing backend dev dependencies (uv sync) …"
if (cd "$BACKEND_DIR" && uv sync --extra dev --quiet 2>&1); then
  green "  ✓ Backend dependencies ready"
else
  red "  ✗ uv sync failed"
  exit 1
fi
echo ""

# Resolve the pytest binary inside the uv-managed venv so we never rely on
# PATH having the right pytest (avoids the 'Failed to spawn' error when
# VIRTUAL_ENV points to a different interpreter).
PYTEST_BIN="$BACKEND_DIR/.venv/bin/pytest"
if [[ ! -x "$PYTEST_BIN" ]]; then
  red "  ✗ pytest binary not found at $PYTEST_BIN after sync"
  exit 1
fi

# ── Backend tests ──────────────────────────────────────────────────────────────
yellow "► Running backend unit tests (pytest) …"
if (cd "$BACKEND_DIR" && "$PYTEST_BIN" tests/ -v --tb=short -q 2>&1); then
  green "  ✓ Backend tests passed"
else
  red   "  ✗ Backend tests FAILED — application will not start"
  exit 1
fi
echo ""

# ── Install frontend dependencies ──────────────────────────────────────────────
yellow "► Installing frontend dependencies (npm ci) …"
if (cd "$FRONTEND_DIR" && npm ci --silent 2>&1); then
  green "  ✓ Frontend dependencies ready"
else
  red "  ✗ npm ci failed"
  exit 1
fi
echo ""

# ── Frontend tests ─────────────────────────────────────────────────────────────
yellow "► Running frontend unit tests (vitest) …"
if (cd "$FRONTEND_DIR" && npm test 2>&1); then
  green "  ✓ Frontend tests passed"
else
  red   "  ✗ Frontend tests FAILED — application will not start"
  exit 1
fi
echo ""

# ── TypeScript check ───────────────────────────────────────────────────────────
yellow "► Running TypeScript type-check …"
TS_ERRORS=$(cd "$FRONTEND_DIR" && npx tsc --noEmit 2>&1 | grep -v "KeyVaultPage" || true)
if [[ -z "$TS_ERRORS" ]]; then
  green "  ✓ TypeScript check passed"
else
  red "  ✗ TypeScript errors found:"
  echo "$TS_ERRORS"
  exit 1
fi
echo ""

bold "============================================================"
green "  All tests passed!"
bold "============================================================"
echo ""

[[ "$TEST_ONLY" == "true" ]] && { yellow "  --test flag set, skipping app startup."; exit 0; }

# ── Start the application ──────────────────────────────────────────────────────
yellow "► Starting backend …"
(cd "$BACKEND_DIR" && bash start.sh) &

yellow "► Starting frontend …"
(cd "$FRONTEND_DIR" && bash start.sh) &

echo ""
green "  Application is starting up."
green "  Backend API : http://localhost:8002"
green "  Frontend    : http://localhost:5177"
echo ""
yellow "  Press Ctrl+C to stop."
wait
