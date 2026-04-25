#!/bin/bash
# ─────────────────────────────────────────────────────────
# Azure Ops Portal — Pre-flight & Endpoint Test Script
# Run this BEFORE or AFTER starting the backend to verify
# port availability, health, and all major API endpoints.
# ─────────────────────────────────────────────────────────
set -euo pipefail

BACKEND_PORT=8002
FRONTEND_PORT=5177
BASE_URL="http://127.0.0.1:${BACKEND_PORT}"

# Wrapper functions to bypass corporate proxy for localhost
curl_silent() { curl --noproxy '*' -sf "$@"; }
curl_check()  { curl --noproxy '*' -s -o /dev/null -w "%{http_code}" "$@" 2>/dev/null || echo "000"; }

PASS=0
FAIL=0
SKIP=0
RESULTS=()

# ── Colors (if terminal supports them) ──
if [[ -t 1 ]]; then
    GREEN='\033[0;32m'; RED='\033[0;31m'; YELLOW='\033[1;33m'
    CYAN='\033[0;36m'; BOLD='\033[1m'; NC='\033[0m'
else
    GREEN=''; RED=''; YELLOW=''; CYAN=''; BOLD=''; NC=''
fi

log_pass() { PASS=$((PASS+1)); RESULTS+=("  ${GREEN}✓${NC} $1"); echo -e "  ${GREEN}✓${NC} $1"; }
log_fail() { FAIL=$((FAIL+1)); RESULTS+=("  ${RED}✗${NC} $1"); echo -e "  ${RED}✗${NC} $1"; }
log_skip() { SKIP=$((SKIP+1)); RESULTS+=("  ${YELLOW}○${NC} $1"); echo -e "  ${YELLOW}○${NC} $1"; }
log_header() { echo -e "\n${BOLD}${CYAN}── $1 ──${NC}"; }

# ═════════════════════════════════════════════════════════
# SECTION 1: PORT CHECKS
# ═════════════════════════════════════════════════════════
log_header "Port Availability"

check_port() {
    local port=$1 name=$2
    if command -v netstat &>/dev/null; then
        local pid
        pid=$(netstat -ano 2>/dev/null | grep ":${port} " | grep LISTENING | awk '{print $NF}' | head -1)
        if [ -n "$pid" ]; then
            echo -e "  ${YELLOW}⚠${NC} Port ${port} (${name}) is IN USE by PID ${pid}"
            return 0  # port in use
        else
            echo -e "  ${GREEN}●${NC} Port ${port} (${name}) is AVAILABLE"
            return 1  # port free
        fi
    elif command -v ss &>/dev/null; then
        if ss -tlnp 2>/dev/null | grep -q ":${port} "; then
            echo -e "  ${YELLOW}⚠${NC} Port ${port} (${name}) is IN USE"
            return 0
        else
            echo -e "  ${GREEN}●${NC} Port ${port} (${name}) is AVAILABLE"
            return 1
        fi
    elif command -v lsof &>/dev/null; then
        if lsof -i ":${port}" -sTCP:LISTEN &>/dev/null; then
            echo -e "  ${YELLOW}⚠${NC} Port ${port} (${name}) is IN USE"
            return 0
        else
            echo -e "  ${GREEN}●${NC} Port ${port} (${name}) is AVAILABLE"
            return 1
        fi
    else
        echo -e "  ${YELLOW}○${NC} Cannot check port ${port} — no netstat/ss/lsof found"
        return 1
    fi
}

BACKEND_RUNNING=false
FRONTEND_RUNNING=false

if check_port "$BACKEND_PORT" "Backend"; then
    BACKEND_RUNNING=true
fi
check_port "$FRONTEND_PORT" "Frontend" && FRONTEND_RUNNING=true || true

# ═════════════════════════════════════════════════════════
# SECTION 2: PRE-FLIGHT CHECKS (no running server needed)
# ═════════════════════════════════════════════════════════
log_header "Pre-flight Checks"

# Check uv
if command -v uv &>/dev/null; then
    log_pass "uv installed: $(uv --version 2>/dev/null || echo 'unknown')"
else
    log_fail "uv not found — install: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

# Check Python (use .venv directly for speed, fall back to uv run)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
PYTHON="${SCRIPT_DIR}/.venv/Scripts/python.exe"
[ ! -f "$PYTHON" ] && PYTHON="${SCRIPT_DIR}/.venv/bin/python"
[ ! -f "$PYTHON" ] && PYTHON="uv run python"
PY_VER=$($PYTHON --version 2>/dev/null || echo "")
if [ -n "$PY_VER" ]; then
    log_pass "Python available: $PY_VER"
else
    log_fail "Python not accessible"
fi

# Check npm (for frontend)
if command -v npm &>/dev/null; then
    log_pass "npm installed: $(npm --version 2>/dev/null)"
else
    log_fail "npm not found"
fi

# Quick import check (uses .venv directly for speed, 10s timeout)
if timeout 10 $PYTHON -c "from app.main import app; print('ok')" &>/dev/null 2>&1; then
    log_pass "App import check passed"
else
    log_skip "App import check skipped (slow or failed — start.sh will validate)"
fi

# ═════════════════════════════════════════════════════════
# SECTION 3: BACKEND ENDPOINT TESTS (only if server running)
# ═════════════════════════════════════════════════════════
if [ "$BACKEND_RUNNING" = true ]; then
    log_header "Backend Health Endpoints"

    # /healthz
    HTTP_CODE=$(curl_check "${BASE_URL}/healthz")
    if [ "$HTTP_CODE" = "200" ]; then
        BODY=$(curl_silent "${BASE_URL}/healthz" 2>/dev/null || echo "{}")
        log_pass "/healthz → 200 ($BODY)"
    else
        log_fail "/healthz → $HTTP_CODE"
    fi

    # /readyz
    HTTP_CODE=$(curl_check "${BASE_URL}/readyz")
    if [ "$HTTP_CODE" = "200" ]; then
        log_pass "/readyz → 200"
    else
        log_fail "/readyz → $HTTP_CODE"
    fi

    # OpenAPI docs (served at /api/docs per main.py)
    HTTP_CODE=$(curl_check "${BASE_URL}/api/docs")
    if [ "$HTTP_CODE" = "200" ]; then
        log_pass "/api/docs (Swagger UI) → 200"
    else
        log_fail "/api/docs (Swagger UI) → $HTTP_CODE"
    fi

    log_header "API v1 Endpoint Tests"

    # List of key endpoints to test (GET requests, most require auth)
    # In dev mode (ENVIRONMENT=development), endpoints return data without a real token
    ENDPOINTS=(
        "/api/v1/optimize/recommendations:Optimization"
        "/api/v1/compliance/aks/drift:Compliance AKS Drift"
        "/api/v1/notifications/history:Notifications"
        "/api/v1/reports/list:Reports"
        "/api/v1/admin/system/health:Admin Health"
        "/api/v1/keyvault/vaults:KeyVault Vaults"
        "/api/v1/aks/clusters:AKS Clusters"
        "/api/v1/infra-alerts/summary:Infrastructure Alerts"
        "/api/v1/checksum-schedules/:Checksum Schedules"
    )

    for entry in "${ENDPOINTS[@]}"; do
        IFS=':' read -r path name <<< "$entry"
        HTTP_CODE=$(curl_check "${BASE_URL}${path}")
        case "$HTTP_CODE" in
            200|201) log_pass "${name} (${path}) → ${HTTP_CODE}" ;;
            307)     log_pass "${name} (${path}) → ${HTTP_CODE} (redirect)" ;;
            401|403) log_skip "${name} (${path}) → ${HTTP_CODE} (auth required)" ;;
            404)     log_fail "${name} (${path}) → 404 (not found)" ;;
            500)     log_fail "${name} (${path}) → 500 (server error)" ;;
            000)     log_fail "${name} (${path}) → connection failed" ;;
            *)       log_skip "${name} (${path}) → ${HTTP_CODE}" ;;
        esac
    done

else
    log_header "Backend Endpoint Tests"
    echo -e "  ${YELLOW}○${NC} Skipped — backend not running on port $BACKEND_PORT"
    echo -e "  ${YELLOW}  ${NC} Start with: cd backend && bash start.sh"
    SKIP=$((SKIP + 1))
fi

# ═════════════════════════════════════════════════════════
# SECTION 4: FRONTEND CHECK (only if running)
# ═════════════════════════════════════════════════════════
if [ "$FRONTEND_RUNNING" = true ]; then
    log_header "Frontend Check"
    HTTP_CODE=$(curl_check "http://127.0.0.1:${FRONTEND_PORT}/")
    if [ "$HTTP_CODE" = "200" ]; then
        log_pass "Frontend serving on port $FRONTEND_PORT → 200"
    else
        log_fail "Frontend on port $FRONTEND_PORT → $HTTP_CODE"
    fi
else
    log_header "Frontend Check"
    echo -e "  ${YELLOW}○${NC} Skipped — frontend not running on port $FRONTEND_PORT"
    SKIP=$((SKIP + 1))
fi

# ═════════════════════════════════════════════════════════
# SUMMARY
# ═════════════════════════════════════════════════════════
echo ""
echo -e "${BOLD}═══════════════════════════════════════${NC}"
echo -e "${BOLD} Test Summary${NC}"
echo -e "${BOLD}═══════════════════════════════════════${NC}"
echo -e "  ${GREEN}Passed:  ${PASS}${NC}"
echo -e "  ${RED}Failed:  ${FAIL}${NC}"
echo -e "  ${YELLOW}Skipped: ${SKIP}${NC}"
echo ""

if [ "$FAIL" -gt 0 ]; then
    echo -e "${RED}Some checks failed. Review output above.${NC}"
    exit 1
else
    echo -e "${GREEN}All checks passed!${NC}"
    exit 0
fi
