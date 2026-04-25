#!/bin/bash
# Stop the Azure Ops Portal Frontend
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$SCRIPT_DIR/.frontend.pid"
PORT=5177

# ── Stop tracked PID ──
if [ -f "$PID_FILE" ]; then
    FRONTEND_PID=$(cat "$PID_FILE")
    if kill -0 "$FRONTEND_PID" 2>/dev/null; then
        echo "Stopping frontend (PID: $FRONTEND_PID)..."
        kill "$FRONTEND_PID"
        for i in $(seq 1 10); do
            if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
                break
            fi
            sleep 1
        done
        if kill -0 "$FRONTEND_PID" 2>/dev/null; then
            echo "Graceful shutdown timed out. Force killing..."
            kill -9 "$FRONTEND_PID" 2>/dev/null || true
        fi
        echo "Frontend stopped"
    else
        echo "Frontend process (PID: $FRONTEND_PID) is not running"
    fi
    rm -f "$PID_FILE"
else
    echo "No PID file found"
fi

# ── Clean up orphaned processes on port ──
echo "Checking for orphaned processes on port $PORT..."
if command -v netstat &>/dev/null; then
    PORT_PIDS=$(netstat -ano 2>/dev/null | grep ":$PORT " | grep LISTENING | awk '{print $NF}' | sort -u)
    if [ -n "$PORT_PIDS" ]; then
        for pid in $PORT_PIDS; do
            echo "  Killing orphaned process on port $PORT: PID $pid"
            taskkill //F //PID "$pid" 2>/dev/null || kill -9 "$pid" 2>/dev/null || true
        done
        sleep 2
    fi
elif command -v lsof &>/dev/null; then
    PORT_PIDS=$(lsof -ti ":$PORT" 2>/dev/null || true)
    if [ -n "$PORT_PIDS" ]; then
        echo "  Killing orphaned processes on port $PORT: $PORT_PIDS"
        echo "$PORT_PIDS" | xargs kill -9 2>/dev/null || true
        sleep 2
    fi
fi
echo "Port $PORT cleanup complete"
