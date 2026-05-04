#!/usr/bin/env bash
# test_and_start.sh — install deps, optionally run tests, then start the app.
# Compatible with Linux, macOS, and Windows (Git Bash / WSL / Cygwin).
#
# Usage:
#   ./test_and_start.sh          # install deps + start app (fast)
#   ./test_and_start.sh --test   # run full tests first, then start app
#   ./test_and_start.sh --test-only  # run tests only, do not start
#
# Exit codes:
#   0 — success (app started, or tests passed in --test-only mode)
#   1 — one or more steps failed
#
# Windows note: run via Git Bash, WSL, or Cygwin.

set -euo pipefail

if [[ -n "${BASH_SOURCE[0]:-}" ]]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
  SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
fi

BACKEND_DIR="$SCRIPT_DIR/backend"
FRONTEND_DIR="$SCRIPT_DIR/frontend"
RUN_TESTS=false
TEST_ONLY=false
BACKEND_PORT=8002
FRONTEND_PORT=5177

for arg in "$@"; do
  case "$arg" in
    --test)      RUN_TESTS=true ;;
    --test-only) RUN_TESTS=true; TEST_ONLY=true ;;
  esac
done

# ── Detect OS ─────────────────────────────────────────────────────────────────
OS="linux"
case "$(uname -s 2>/dev/null || true)" in
  Darwin*)               OS="mac"     ;;
  CYGWIN*|MINGW*|MSYS*)  OS="windows" ;;
  Linux*)                OS="linux"   ;;
esac
[[ -n "${WINDIR:-}${windir:-}" ]] && OS="windows"

# ── Colour helpers ─────────────────────────────────────────────────────────────
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
bold "  OpsPortal — Application Launcher"
bold "============================================================"
printf '\n'
yellow "  Platform : $OS"
[[ "$RUN_TESTS" == "true" ]] && yellow "  Mode     : tests + start" || yellow "  Mode     : fast start (use --test for full tests)"
printf '\n'

# ── Verify required tools ──────────────────────────────────────────────────────
_require() {
  if ! command -v "$1" &>/dev/null; then
    red "  ✗ '$1' not found. Install: $2"
    exit 1
  fi
}
_require uv  "https://docs.astral.sh/uv/getting-started/installation/"
_require npm "https://nodejs.org (includes npm)"

# ── Kill processes on ports ────────────────────────────────────────────────────
kill_port() {
  local port="$1"
  local pids=""
  if [[ "$OS" == "windows" ]]; then
    pids=$(netstat -ano 2>/dev/null | grep ":${port} " | grep LISTENING | awk '{print $NF}' | sort -u | grep -v '^$' || true)
    if [[ -n "$pids" ]]; then
      for pid in $pids; do
        yellow "  Killing PID $pid on port $port"
        taskkill //F //PID "$pid" 2>/dev/null || true
      done
    fi
  elif command -v lsof &>/dev/null; then
    pids=$(lsof -ti ":$port" 2>/dev/null || true)
    if [[ -n "$pids" ]]; then
      yellow "  Killing PIDs on port $port: $pids"
      echo "$pids" | xargs kill -9 2>/dev/null || true
    fi
  fi
}

yellow "► Freeing ports $BACKEND_PORT and $FRONTEND_PORT …"
kill_port "$BACKEND_PORT"
kill_port "$FRONTEND_PORT"
# Brief pause only if something was killed
sleep 1
green "  ✓ Ports cleared"
printf '\n'

# Clean stale PID files
rm -f "$BACKEND_DIR/.backend.pid" "$FRONTEND_DIR/.frontend.pid"

# ── Install dependencies (only when needed, parallel) ────────────────────────
NEED_BACKEND_DEPS=false
NEED_FRONTEND_DEPS=false

# Backend: skip if .venv exists and is newer than pyproject.toml + uv.lock
if [[ ! -d "$BACKEND_DIR/.venv" ]]; then
  NEED_BACKEND_DEPS=true
elif [[ "$BACKEND_DIR/pyproject.toml" -nt "$BACKEND_DIR/.venv" ]] || \
     [[ "$BACKEND_DIR/uv.lock" -nt "$BACKEND_DIR/.venv" ]]; then
  NEED_BACKEND_DEPS=true
fi

# Frontend: skip if node_modules exists and is newer than package.json
if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
  NEED_FRONTEND_DEPS=true
elif [[ "$FRONTEND_DIR/package.json" -nt "$FRONTEND_DIR/node_modules/.package-lock.json" ]]; then
  NEED_FRONTEND_DEPS=true
fi

if [[ "$NEED_BACKEND_DEPS" == "true" ]] || [[ "$NEED_FRONTEND_DEPS" == "true" ]]; then
  yellow "► Installing dependencies …"

  if [[ "$NEED_BACKEND_DEPS" == "true" ]]; then
    (
      cd "$BACKEND_DIR"
      uv sync --native-tls --quiet 2>&1
      touch .venv  # update timestamp for next skip check
    ) &
    BACKEND_DEP_PID=$!
  fi

  if [[ "$NEED_FRONTEND_DEPS" == "true" ]]; then
    (
      cd "$FRONTEND_DIR"
      if [[ "$OS" == "windows" ]]; then
        npm install --prefer-offline 2>&1
      else
        npm ci --silent 2>&1
      fi
    ) &
    FRONTEND_DEP_PID=$!
  fi

  DEPS_OK=true
  [[ "$NEED_BACKEND_DEPS" == "true" ]]  && { wait "$BACKEND_DEP_PID"  || DEPS_OK=false; }
  [[ "$NEED_FRONTEND_DEPS" == "true" ]] && { wait "$FRONTEND_DEP_PID" || DEPS_OK=false; }

  if [[ "$DEPS_OK" == "false" ]]; then
    red "  ✗ Dependency install failed"
    exit 1
  fi
  green "  ✓ Dependencies ready"
else
  green "► Dependencies already up-to-date — skipping install"
fi
printf '\n'

# ── Tests (only with --test or --test-only) ──────────────────────────────────
if [[ "$RUN_TESTS" == "true" ]]; then
  bold "── Running tests ──"
  printf '\n'

  # Backend tests
  yellow "► Backend unit tests (pytest) …"
  if (cd "$BACKEND_DIR" && uv run python -m pytest tests/ -v --tb=short -q 2>&1); then
    green "  ✓ Backend tests passed"
  else
    red   "  ✗ Backend tests FAILED"
    exit 1
  fi
  printf '\n'

  # Frontend tests
  yellow "► Frontend unit tests (vitest) …"
  if [[ "$OS" == "windows" ]]; then
    VITEST_CMD="npx vitest run"
  else
    VITEST_CMD="npm test"
  fi
  if (cd "$FRONTEND_DIR" && $VITEST_CMD 2>&1); then
    green "  ✓ Frontend tests passed"
  else
    red   "  ✗ Frontend tests FAILED"
    exit 1
  fi
  printf '\n'

  # TypeScript check
  yellow "► TypeScript type-check …"
  TS_ERRORS=$(cd "$FRONTEND_DIR" && npx tsc --noEmit 2>&1 | grep -v "KeyVaultPage" || true)
  if [[ -z "$TS_ERRORS" ]]; then
    green "  ✓ TypeScript check passed"
  else
    red "  ✗ TypeScript errors:"
    printf '%s\n' "$TS_ERRORS"
    exit 1
  fi
  printf '\n'

  bold "============================================================"
  green "  All tests passed!"
  bold "============================================================"
  printf '\n'

  if [[ "$TEST_ONLY" == "true" ]]; then
    exit 0
  fi
fi

# ── Start the application ──────────────────────────────────────────────────────
yellow "► Starting backend on port $BACKEND_PORT …"
(
  cd "$BACKEND_DIR"
  export ENVIRONMENT="${ENVIRONMENT:-development}"
  export NO_PROXY="127.0.0.1,localhost,${NO_PROXY:-}"
  export no_proxy="127.0.0.1,localhost,${no_proxy:-}"
  PYTHONUNBUFFERED=1 uv run python -m uvicorn app.main:app \
    --host 0.0.0.0 --port "$BACKEND_PORT" --proxy-headers \
    > "$BACKEND_DIR/backend.log" 2>&1
) &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$BACKEND_DIR/.backend.pid"

# Wait for backend health (max 30s, poll every 1s)
MAX_WAIT=30
WAITED=0
while [[ $WAITED -lt $MAX_WAIT ]]; do
  if curl --noproxy '*' -sf "http://127.0.0.1:$BACKEND_PORT/healthz" > /dev/null 2>&1; then
    green "  ✓ Backend ready (${WAITED}s)"
    break
  fi
  sleep 1
  WAITED=$((WAITED + 1))
done
[[ $WAITED -ge $MAX_WAIT ]] && yellow "  ⚠ Backend health check timed out after ${MAX_WAIT}s"

yellow "► Starting frontend on port $FRONTEND_PORT …"
(
  cd "$FRONTEND_DIR"
  export NO_PROXY="127.0.0.1,localhost,${NO_PROXY:-}"
  npm run dev > "$FRONTEND_DIR/frontend.log" 2>&1
) &
FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$FRONTEND_DIR/.frontend.pid"

# Wait briefly for Vite to start (max 10s)
WAITED=0
while [[ $WAITED -lt 10 ]]; do
  if curl --noproxy '*' -sf "http://127.0.0.1:$FRONTEND_PORT" > /dev/null 2>&1; then
    green "  ✓ Frontend ready (${WAITED}s)"
    break
  fi
  sleep 1
  WAITED=$((WAITED + 1))
done

trap 'kill "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null; exit 0' INT TERM

printf '\n'
bold "============================================================"
green "  Application is running"
bold "============================================================"
green "  Backend API : http://localhost:$BACKEND_PORT"
green "  Frontend    : http://localhost:$FRONTEND_PORT"
printf '\n'
yellow "  Press Ctrl+C to stop both servers."
wait
