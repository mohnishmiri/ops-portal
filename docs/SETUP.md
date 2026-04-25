# Azure Ops Intelligence Portal — Setup & Startup Guide

> Comprehensive instructions for running the frontend and backend application locally and via Docker.

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Repository Structure](#2-repository-structure)
3. [Environment Configuration](#3-environment-configuration)
4. [Backend Setup (FastAPI)](#4-backend-setup-fastapi)
5. [Frontend Setup (React + Vite)](#5-frontend-setup-react--vite)
6. [Running Both Services Together](#6-running-both-services-together)
7. [Starting & Stopping Services (Shell Scripts)](#7-starting--stopping-services-shell-scripts)
8. [Docker Compose (Containerised)](#8-docker-compose-containerised)
9. [AKS Deployment (Helm)](#9-aks-deployment-helm)
10. [API Endpoints Reference](#10-api-endpoints-reference)
11. [Port Reference](#11-port-reference)
12. [Troubleshooting](#12-troubleshooting)

---

## 1. Prerequisites

| Tool          | Minimum Version | Purpose                                  |
|---------------|-----------------|------------------------------------------|
| Python        | 3.11+           | Backend runtime                          |
| uv            | 0.4+            | Python package & project manager         |
| Node.js       | 20+             | Frontend build tooling                   |
| npm           | 9+              | Frontend package manager                 |
| Git           | 2.40+           | Source control                           |
| Docker        | 24+ (optional)  | Containerised deployment                 |
| Azure CLI     | 2.60+ (optional)| Azure authentication fallback            |

### Azure Service Principal

The application requires a Service Principal with **Reader** access to the target Azure subscriptions and **Key Vault Secrets User / Key Vault Reader** roles on monitored Key Vaults.

| Credential             | Example Value                                     |
|-------------------------|-------------------------------------------------|
| `AZURE_TENANT_ID`       | `e741d71c-c6b6-47b0-803c-0f3b32b07556`          |
| `AZURE_CLIENT_ID`       | `68a52619-4061-448c-8264-922aedba1b5b`           |
| `AZURE_CLIENT_SECRET`   | *(your client secret)*                           |
| `AZURE_SUBSCRIPTION_IDS`| Comma-separated subscription GUIDs               |

---

## 2. Repository Structure

```
azure-ops-portal/
├── backend/                    # FastAPI backend (Python)
│   ├── app/
│   │   ├── api/                # REST API route handlers
│   │   ├── auth/               # Azure AD / MSAL authentication
│   │   ├── core/               # Config, Redis, Azure auth helpers
│   │   ├── middleware/         # CORS, rate limiting, logging
│   │   ├── models/             # Pydantic data models
│   │   ├── plugins/            # Plugin system (AKS Insights, Key Vault)
│   │   ├── services/           # Business logic services
│   │   └── main.py             # FastAPI app entrypoint
│   ├── tests/                  # pytest test suite
│   ├── .env                    # Local environment variables
│   └── pyproject.toml          # Python dependencies & tooling config
│
├── frontend/                   # React + TypeScript frontend
│   ├── src/
│   │   ├── components/         # React page components
│   │   ├── services/           # API client & React Query hooks
│   │   └── ...
│   ├── package.json            # Node.js dependencies
│   ├── vite.config.ts          # Vite dev server & proxy config
│   ├── tailwind.config.js      # Tailwind CSS configuration
│   └── tsconfig.json           # TypeScript configuration
│
├── helm/ops-portal/           # Helm chart for AKS deployment
├── Dockerfile.backend          # Multi-stage backend Docker image
├── Dockerfile.frontend         # Multi-stage frontend Docker image
├── docker-compose.yaml         # Local Docker Compose stack
└── ARCHITECTURE.md             # Architecture documentation
```

---

## 3. Environment Configuration

### Backend `.env` File

Create or edit `backend/.env` with your Azure credentials:

```dotenv
# ── Application ──────────────────────────────────────────
ENVIRONMENT=development
LOG_LEVEL=DEBUG

# ── Azure AD / Service Principal ─────────────────────────
AZURE_TENANT_ID=<your-tenant-id>
AZURE_CLIENT_ID=<your-client-id>
AZURE_CLIENT_SECRET=<your-client-secret>
AZURE_SUBSCRIPTION_IDS=<sub-id-1>,<sub-id-2>

# ── Redis Cache ──────────────────────────────────────────
# Local Redis:
# REDIS_URL=redis://localhost:6379/0
# Azure Redis Cache (SSL):
REDIS_URL=rediss://:<access-key>@<hostname>.redis.cache.windows.net:6380/0

# ── CORS (allow local frontend origins) ──────────────────
CORS_ORIGINS=["http://localhost:3000","http://localhost:5177"]

# ── SMTP (optional — for email notifications) ────────────
SMTP_HOST=localhost
SMTP_PORT=25
SMTP_FROM_ADDRESS=dev@localhost

# ── Key Vault (optional) ────────────────────────────────
KEYVAULT_URL=
```

> **Important**: Never commit secrets to Git. The `.env` file should be in `.gitignore`.

---

## 4. Backend Setup (FastAPI)

### 4.1 Create Python Virtual Environment

```bash
cd azure-ops-portal/backend
```

> **Note:** `uv` manages the virtual environment automatically — no need to create or activate `.venv` manually.

### 4.2 Install Dependencies

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync the project and all dependencies (creates .venv automatically)
uv sync --native-tls
```

> **Corporate proxy / TLS — REQUIRED for AT&T network:**
>
> If `uv sync` fails with `invalid peer certificate: UnknownIssuer`, the
> corporate proxy is intercepting TLS. Two things must be in place:
>
> 1. **`native-tls = true`** in `pyproject.toml` under `[tool.uv]` (already set).
> 2. **`SSL_CERT_FILE`** must point to the corporate CA bundle.
>
> Run this instead:
> ```bash
> SSL_CERT_FILE="/c/binary/cacert.pem" uv sync --native-tls
> ```
>
> To avoid typing it every session, add to your `~/.bashrc` or `~/.bash_profile`:
> ```bash
> export SSL_CERT_FILE="/c/binary/cacert.pem"
> ```

> **Hatchling build error — `Unable to determine which files to ship`:**
>
> If `uv sync` passes the download phase but fails with a hatchling
> `ValueError: Unable to determine which files to ship inside the wheel`,
> ensure `pyproject.toml` contains:
> ```toml
> [tool.hatch.build.targets.wheel]
> packages = ["app"]
> ```
> This tells the build backend that the source code is in `app/` (not the
> default `azure_ops_portal/` derived from the project name).

This installs:
- **Runtime**: FastAPI, Uvicorn, Azure SDKs, Redis, structlog, Pydantic, etc.
- **Dev**: pytest, ruff, mypy, bandit

### 4.3 Start the Backend Server

```bash
# Development mode with auto-reload (port 8002)
uv run uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

| Parameter     | Description                                    |
|---------------|------------------------------------------------|
| `--host`      | Bind address (`0.0.0.0` for all interfaces)    |
| `--port`      | HTTP port (`8002` for local dev)               |
| `--reload`    | Auto-restart on code changes (dev only)        |

### 4.4 Verify Backend is Running

```bash
# Health check (should return JSON)
curl http://localhost:8002/healthz

# Swagger/OpenAPI docs
open http://localhost:8002/docs

# Test Key Vault API
curl --noproxy localhost http://localhost:8002/api/v1/keyvault/vaults
```

The Swagger/OpenAPI docs are available at **http://localhost:8002/docs**.

### 4.5 Backend Architecture

| Component          | Port  | Framework     | Description                            |
|--------------------|-------|---------------|----------------------------------------|
| FastAPI App        | 8002  | Uvicorn       | REST API server (local dev)            |
| Redis Cache        | 6380  | redis.asyncio | Response caching (circuit-breaker)     |
| Azure ARM API      | —     | urllib        | Vault/subscription discovery           |
| Key Vault REST API | —     | urllib        | Secrets, Keys, Certificates operations |

---

## 5. Frontend Setup (React + Vite)

### 5.1 Install Node.js Dependencies

```bash
cd azure-ops-portal/frontend

# Install all packages
npm install
```

### 5.2 Start the Frontend Dev Server

```bash
npm run dev
```

This starts the Vite development server on **http://localhost:5177**.

### 5.3 Vite Proxy Configuration

The frontend proxies all `/api` requests to the backend automatically (configured in `vite.config.ts`):

```
Frontend (localhost:5177)  →  /api/*  →  Backend (localhost:8002)
```

No manual CORS configuration is needed during local development.

### 5.4 Frontend Architecture

| Component         | Version     | Purpose                                  |
|-------------------|-------------|------------------------------------------|
| React             | 18.3+       | UI framework                             |
| TypeScript        | 5.5+        | Type safety                              |
| Vite              | 5.3+        | Build tool & dev server                  |
| Tailwind CSS      | 3.4+        | Utility-first CSS styling                |
| React Query       | 5.50+       | Server state management & caching        |
| React Router      | 6.25+       | Client-side routing                      |
| Axios             | 1.7+        | HTTP client                              |
| Recharts          | 2.12+       | Charts and data visualization            |
| MSAL React        | 2.0+        | Azure AD authentication                  |
| Zustand           | 4.5+        | Client state management                  |

### 5.5 Build for Production

```bash
# Type-check and build optimised bundle
npm run build

# Preview the production build locally
npm run preview
```

The build output is written to `frontend/dist/`.

---

## 6. Running Both Services Together

### Quick Start (2 Terminal Windows)

**Terminal 1 — Backend:**
```bash
cd azure-ops-portal/backend
uv run uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload
```

**Terminal 2 — Frontend:**
```bash
cd azure-ops-portal/frontend
npm run dev
```

### Access Points

| Service          | URL                          | Description              |
|------------------|------------------------------|--------------------------|
| Frontend App     | http://localhost:5177         | React application        |
| Backend API      | http://localhost:8002/api/v1  | REST API base URL        |
| API Docs         | http://localhost:8002/docs    | Swagger / OpenAPI UI     |
| API Redoc        | http://localhost:8002/redoc   | ReDoc API documentation  |

### Startup Order

1. Start the **backend** first (port 8002)
2. Start the **frontend** second (port 5177)
3. Open **http://localhost:5177** in your browser

The frontend will not work without the backend running because all API calls are proxied through Vite to `localhost:8002`.

---

## 7. Starting & Stopping Services (Shell Scripts)

Both services include shell scripts for managed start/stop with **automatic port cleanup** to prevent dangling processes.

### 7.1 Start Backend

```bash
cd azure-ops-portal/backend
bash start.sh
```

What the script does:
1. Kills any existing process on port **8002** (prevents "port already in use" errors)
2. Cleans up stale PID files from previous runs
3. Runs `uv sync --native-tls` to install/update dependencies
4. Starts Uvicorn in the background, logging to `backend.log`
5. Waits up to 30s for the health check (`/healthz`) to pass

### 7.2 Stop Backend

```bash
cd azure-ops-portal/backend
bash stop.sh
```

What the script does:
1. Sends SIGTERM to the tracked PID (graceful shutdown, 10s timeout)
2. Force-kills (SIGKILL) if the process doesn't stop
3. Scans port **8002** for any orphaned processes and kills them
4. Cleans up the `.backend.pid` file

### 7.3 Start Frontend

```bash
cd azure-ops-portal/frontend
bash start.sh
```

What the script does:
1. Kills any existing process on port **5177** (prevents "port already in use" errors)
2. Cleans up stale PID files from previous runs
3. Installs `node_modules` if missing (`npm install`)
4. Waits up to 60s for the backend at `http://127.0.0.1:8002/healthz`
5. Starts the Vite dev server in the background, logging to `frontend.log`

### 7.4 Stop Frontend

```bash
cd azure-ops-portal/frontend
bash stop.sh
```

What the script does:
1. Sends SIGTERM to the tracked PID (graceful shutdown, 10s timeout)
2. Force-kills (SIGKILL) if the process doesn't stop
3. Scans port **5177** for any orphaned processes and kills them
4. Cleans up the `.frontend.pid` file

### 7.5 Quick Reference

| Action         | Command                                          |
|----------------|--------------------------------------------------|
| Start backend  | `cd backend && bash start.sh`                    |
| Stop backend   | `cd backend && bash stop.sh`                     |
| Start frontend | `cd frontend && bash start.sh`                   |
| Stop frontend  | `cd frontend && bash stop.sh`                    |
| Start both     | `cd backend && bash start.sh && cd ../frontend && bash start.sh` |
| Stop both      | `cd frontend && bash stop.sh && cd ../backend && bash stop.sh`   |

### 7.6 Manual Port Cleanup (if scripts fail)

If a dangling process is blocking a port, clean it up manually:

**Windows (Git Bash / PowerShell):**
```bash
# Find the process using a port
netstat -ano | grep :8002
netstat -ano | grep :5177

# Kill by PID
taskkill /F /PID <pid>
```

**macOS / Linux:**
```bash
# Find and kill processes on a port
lsof -ti :8002 | xargs kill -9
lsof -ti :5177 | xargs kill -9
```

---

## 8. Docker Compose (Containerised)

For a fully containerised local environment with Redis:

```bash
cd azure-ops-portal

# Create a .env file at the project root with your Azure credentials
# (the docker-compose.yaml reads from it)

# Build and start all services
docker-compose up --build

# Or run in detached mode
docker-compose up --build -d
```

### Docker Compose Services

| Service   | Image              | Port  | Description                     |
|-----------|--------------------|-------|---------------------------------|
| backend   | Dockerfile.backend | 8000  | FastAPI API server (4 workers)  |
| frontend  | Dockerfile.frontend| 3000  | NGINX serving React SPA         |
| redis     | redis:7-alpine     | 6379  | In-memory cache                 |

### Docker Image Details

**Backend Image** (`Dockerfile.backend`):
- Base: `python:3.11-slim`
- Multi-stage build (builder → production)
- Runs as non-root `appuser`
- Health check: `curl -f http://localhost:8000/healthz`
- CMD: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4`

**Frontend Image** (`Dockerfile.frontend`):
- Base: `node:20-alpine` (build) → `nginx:1.27-alpine` (serve)
- Multi-stage build with Vite production build
- NGINX SPA routing with API proxy
- Security headers (CSP, X-Frame-Options, etc.)
- Static asset caching (1 year, immutable)
- Health check: `wget --spider http://localhost:80/`

### Stop Services

```bash
docker-compose down

# With volume cleanup
docker-compose down -v
```

---

## 9. AKS Deployment (Helm)

The Helm chart is located at `helm/ops-portal/`.

```bash
# Non-prod: create one Azure Key Vault secret per environment variable listed
# in helm/ops-portal/values.yaml. The chart creates one AzureKeyVaultSecret per
# mapping and akv2k8s syncs each one into a Kubernetes Secret in opsportal.

# Non-prod deploy
helm upgrade --install ops-portal ./helm/ops-portal \
  -f helm/ops-portal/values.yaml \
  -f helm/ops-portal/values-dev.yaml \
  --namespace opsportal \
  --create-namespace \
  --set backend.azureKeyVaultSecrets.vaultName=<dev-keyvault-name> \
  --set frontend.azureKeyVaultSecrets.vaultName=<dev-keyvault-name>

# Production deploy
helm upgrade --install ops-portal ./helm/ops-portal \
  -f helm/ops-portal/values.yaml \
  -f helm/ops-portal/values-prod.yaml \
  --namespace opsportal \
  --create-namespace \
  --set backend.azureKeyVaultSecrets.vaultName=<prod-keyvault-name> \
  --set frontend.azureKeyVaultSecrets.vaultName=<prod-keyvault-name>
```

The chart now creates one `AzureKeyVaultSecret` per environment variable in the `opsportal` namespace and expects the akv2k8s controller CRD to be installed already. Those CRs sync each Azure Key Vault secret into a Kubernetes `Secret`. The backend and frontend Deployments then read those synced Kubernetes secrets as environment variables with `secretKeyRef`.

The same chart can also sync an exportable Azure Key Vault certificate into the Kubernetes TLS secret referenced by `ingress.tls[].secretName` by enabling `ingress.azureKeyVaultCertificates`. akv2k8s formats the destination secret as `kubernetes.io/tls` with `tls.crt` and `tls.key`.

If ingress TLS is sourced from Azure Key Vault, do not point the same ingress at cert-manager for the same secret name. Remove or override `cert-manager.io/cluster-issuer` in that environment unless you intentionally want cert-manager to own TLS instead of akv2k8s.

Secret and object count:

- Per environment: `22` AKV secret objects, `22` `AzureKeyVaultSecret` objects in AKS, and `22` Kubernetes Secrets in AKS.
- Across both environments: `44` AKV secret objects total and, if `dev` and `prod` are separate AKS clusters, `44` `AzureKeyVaultSecret` objects total.

See [docs/AKV_ENV_SECRET_TEMPLATES.md](h:/ATTCC/GITHUB/apm0014313-attcc-ops-portal/docs/AKV_ENV_SECRET_TEMPLATES.md) for full backend/frontend Key Vault payload templates and AKS troubleshooting commands.

The recommended Key Vault object format for this flow is the normal Azure Key Vault `secret` object type, with one AKV secret per environment variable.

Frontend `VITE_*` values are exposed to the browser by design. They can be stored in a Kubernetes Secret for deployment consistency, but they should still be treated as public client configuration rather than confidential backend secrets.

---

## 10. API Endpoints Reference

### Cost Management

| Method | Endpoint                     | Description                    |
|--------|------------------------------|--------------------------------|
| GET    | `/api/v1/costs/summary`      | Cost summary across subs       |
| GET    | `/api/v1/costs/breakdown`    | Cost breakdown by service      |
| GET    | `/api/v1/costs/trends`       | Cost trend analysis            |

### Key Vault Operations

| Method | Endpoint                              | Description                       |
|--------|---------------------------------------|-----------------------------------|
| GET    | `/api/v1/keyvault/dashboard`          | Dashboard summary (KPIs)          |
| GET    | `/api/v1/keyvault/vaults`             | List all discovered vaults        |
| GET    | `/api/v1/keyvault/secrets`            | List secrets in a vault           |
| GET    | `/api/v1/keyvault/secret-value`       | Get secret value                  |
| POST   | `/api/v1/keyvault/secrets`            | Create/update a secret            |
| DELETE | `/api/v1/keyvault/secrets`            | Delete a secret                   |
| GET    | `/api/v1/keyvault/keys`               | List keys in a vault              |
| GET    | `/api/v1/keyvault/key`                | Get key details                   |
| POST   | `/api/v1/keyvault/keys`               | Create/update a key               |
| DELETE | `/api/v1/keyvault/keys`               | Delete a key                      |
| GET    | `/api/v1/keyvault/certificates`       | List certificates in a vault      |
| GET    | `/api/v1/keyvault/certificate`        | Get certificate details           |

### AKS Insights

| Method | Endpoint                     | Description                    |
|--------|------------------------------|--------------------------------|
| GET    | `/api/v1/aks/clusters`       | List AKS clusters              |
| GET    | `/api/v1/aks/cluster/{name}` | Cluster details                |

---

## 11. Port Reference

All port assignments in one place — local dev vs Docker vs production.

| Service         | Local Dev | Docker Compose | AKS (Helm)   |
|-----------------|-----------|----------------|---------------|
| Backend API     | **8002**  | 8000           | 8000          |
| Frontend        | **5177**  | 3000 → 80      | 80            |
| Redis           | 6379      | 6379           | 6380 (SSL)    |
| PostgreSQL      | 5432      | 5432           | Managed       |

> **Why different ports?** Local dev uses non-standard ports (8002, 5177) to avoid
> clashing with other services or previous instances. Docker and production use
> standard ports because containers are isolated.

---

## 12. Troubleshooting

### Backend Won't Start

| Issue                          | Solution                                                    |
|--------------------------------|-------------------------------------------------------------|
| Port 8002 already in use       | Run `bash stop.sh` or kill manually: `netstat -ano \| grep :8002` then `taskkill /F /PID <pid>` |
| `.env` not loading             | Ensure `.env` is in `backend/` directory (not project root) |
| Azure auth fails               | Verify `AZURE_TENANT_ID`, `CLIENT_ID`, `CLIENT_SECRET` are correct |
| Module not found errors        | Re-run `uv sync` inside the `backend/` directory             |
| `uv sync` fails with `UnknownIssuer` | Corporate proxy TLS issue — run: `SSL_CERT_FILE="/c/binary/cacert.pem" uv sync --native-tls` |
| `uv sync` fails with `Unable to determine which files to ship` | Ensure `[tool.hatch.build.targets.wheel] packages = ["app"]` exists in `pyproject.toml` |
| WatchFiles reloader crash      | Delete any stale `.py` temp files in `backend/` and restart |

### Frontend Won't Start

| Issue                           | Solution                                                   |
|---------------------------------|------------------------------------------------------------|
| Port 5177 already in use        | Run `bash stop.sh` or kill manually: `netstat -ano \| grep :5177` then `taskkill /F /PID <pid>` |
| `node_modules` corruption       | Delete `node_modules` and `package-lock.json`, run `npm install` |
| API calls returning 502/ECONNREFUSED | Ensure backend is running on port 8002 first (`curl http://localhost:8002/healthz`) |
| TypeScript errors               | Run `npx tsc --noEmit` to check for type issues            |

### API Requests Hang / Slow Response

| Issue                           | Solution                                                   |
|---------------------------------|------------------------------------------------------------|
| Redis timeout blocking requests | Socket timeout is set to 3s with circuit-breaker fallback; if Redis is unreachable the first call may take ~3s, subsequent calls bypass Redis for 30s |
| Key Vault API 403 errors        | Verify the Service Principal has Key Vault access policies or RBAC roles |
| Corporate proxy blocking vaults | Vault API calls bypass proxy by default (`ProxyHandler({})`) |
| Dashboard slow on first load    | Dashboard queries 5 vaults sequentially; expect 10-30s on first call |

### Redis Cache

| Issue                           | Solution                                                   |
|---------------------------------|------------------------------------------------------------|
| Redis unreachable               | Application degrades gracefully — caching is disabled, all data fetched live from Azure |
| Circuit breaker tripped         | Resets after 30 seconds; check Redis connectivity with `redis-cli -h <host> -p 6380 --tls ping` |
| Stale cached data               | Cache auto-expires (vaults: 10min, dashboard: 5min, lists: 3min) |

### General Tips

- **Logs**: Backend logs are structured JSON via `structlog`. Watch the terminal output for `[warning]` or `[error]` entries.
- **Proxy**: If behind a corporate proxy, set `HTTPS_PROXY` for Azure ARM calls. Key Vault calls bypass the proxy automatically.
- **uv behind proxy**: Always use `SSL_CERT_FILE="/c/binary/cacert.pem" uv sync --native-tls`. Add `export SSL_CERT_FILE="/c/binary/cacert.pem"` to your shell profile to avoid typing it every time.
- **Python version**: The project requires Python 3.11+. Check with `python --version`.
- **Node version**: The project requires Node.js 20+. Check with `node --version`.

---

*Last updated: March 2026*
