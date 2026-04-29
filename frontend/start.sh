#!/bin/bash
# Start the Azure Ops Portal Frontend (Vite dev server)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PID_FILE="$SCRIPT_DIR/.frontend.pid"
LOG_FILE="$SCRIPT_DIR/frontend.log"
PORT=5177

# ── Cleanup: kill any existing process on the frontend port ──
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

if [ -f "$PID_FILE" ]; then
    EXISTING_PID=$(cat "$PID_FILE")
    if kill -0 "$EXISTING_PID" 2>/dev/null; then
        echo "Frontend is already running (PID: $EXISTING_PID)"
        exit 1
    else
        echo "Stale PID file found. Cleaning up..."
        rm -f "$PID_FILE"
    fi
fi

# Clean up any orphaned processes on the port
cleanup_port

# Install dependencies if node_modules is missing
if [ ! -d "node_modules" ]; then
    echo "Installing dependencies..."
    npm install
fi

# Wait for backend to be ready before starting frontend
BACKEND_URL="http://127.0.0.1:8002/healthz"
MAX_WAIT=60
WAITED=0
echo "Waiting for backend at $BACKEND_URL ..."
while [ $WAITED -lt $MAX_WAIT ]; do
    if curl --noproxy '*' -sf "$BACKEND_URL" > /dev/null 2>&1; then
        echo "Backend is ready (waited ${WAITED}s)"
        break
    fi
    sleep 2
    WAITED=$((WAITED + 2))
done
if [ $WAITED -ge $MAX_WAIT ]; then
    echo "WARNING: Backend not available after ${MAX_WAIT}s — starting frontend anyway"
fi

echo "Starting frontend dev server..."
NO_PROXY="127.0.0.1,localhost,$NO_PROXY" nohup npm run dev > "$LOG_FILE" 2>&1 &
FRONTEND_PID=$!
echo "$FRONTEND_PID" > "$PID_FILE"

echo "Frontend started (PID: $FRONTEND_PID)"
echo "Logs: $LOG_FILE"
echo "URL:  http://localhost:5177"
