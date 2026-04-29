#!/bin/bash
# Start the Azure Ops Portal Backend (FastAPI + Uvicorn)
# Uses uv for dependency management and process execution
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="$SCRIPT_DIR/.backend.pid"
LOG_FILE="$SCRIPT_DIR/backend.log"
PORT=8002

# ── Environment defaults ──
export ENVIRONMENT="${ENVIRONMENT:-development}"
export NO_PROXY="127.0.0.1,localhost,${NO_PROXY:-}"
export no_proxy="127.0.0.1,localhost,${no_proxy:-}"

# ── Cleanup: kill any existing process on the backend port ──
cleanup_port() {
    echo "Checking for existing processes on port $PORT..."
    if command -v netstat &>/dev/null; then
        PORT_PIDS=$(netstat -ano 2>/dev/null | grep ":$PORT " | grep LISTENING | awk '{print $NF}' | sort -u)
        if [ -n "$PORT_PIDS" ]; then
            for pid in $PORT_PIDS; do
                echo "  Killing existing process on port $PORT: PID $pid"
                taskkill //F //PID "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
            done
            sleep 2
        fi
    elif command -v lsof &>/dev/null; then
        PORT_PIDS=$(lsof -ti ":$PORT" 2>/dev/null || true)
        if [ -n "$PORT_PIDS" ]; then
            echo "  Killing existing processes on port $PORT: $PORT_PIDS"
            echo "$PORT_PIDS" | xargs kill -9 2>/dev/null || true
            sleep 2
        fi
    fi
}

# ── Handle stale PID file ──
if [ -f "$PID_FILE" ]; then
    EXISTING_PID=$(cat "$PID_FILE")
    if kill -0 "$EXISTING_PID" 2>/dev/null; then
        echo "Backend is already running (PID: $EXISTING_PID). Stopping it first..."
        kill "$EXISTING_PID" 2>/dev/null || true
        sleep 2
        kill -9 "$EXISTING_PID" 2>/dev/null || true
    fi
    rm -f "$PID_FILE"
fi

# Clean up any orphaned processes on the port
cleanup_port

# ── Ensure uv is available ──
if ! command -v uv &>/dev/null; then
    echo "ERROR: uv is not installed. Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
    exit 1
fi

# ── Sync dependencies via uv ──
echo "Syncing dependencies with uv..."
uv sync --native-tls

# ── Pre-flight: verify app can import cleanly ──
echo "Running pre-flight import check..."
if ! uv run python -c "from app.main import app; print('Import check: OK')" 2>&1; then
    echo "ERROR: App import failed. Check logs above for missing modules."
    exit 1
fi

# ── Start the backend via uv run ──
echo "Starting backend server on port $PORT (ENVIRONMENT=$ENVIRONMENT)..."
PYTHONUNBUFFERED=1 nohup uv run python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --proxy-headers > "$LOG_FILE" 2>&1 &
BACKEND_PID=$!
echo "$BACKEND_PID" > "$PID_FILE"

# ── Wait for backend to become healthy ──
MAX_WAIT=30
WAITED=0
echo "Waiting for backend to be ready..."
while [ $WAITED -lt $MAX_WAIT ]; do
    if curl --noproxy '*' -sf "http://127.0.0.1:$PORT/healthz" > /dev/null 2>&1; then
        echo "Backend is healthy (took ${WAITED}s)"
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
done
if [ $WAITED -ge $MAX_WAIT ]; then
    echo "WARNING: Backend health check timed out after ${MAX_WAIT}s"
fi

echo "Backend started (PID: $BACKEND_PID)"
echo "Logs: $LOG_FILE"
echo "URL:  http://localhost:$PORT"
