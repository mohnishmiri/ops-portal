# Azure Ops Intelligence & Optimization Portal — Project Context

> **This file is Copilot's "brain" for the project.** It is loaded automatically so that every Copilot suggestion is grounded in accurate, up-to-date project knowledge.

---

## 1. What This Project Is

**Azure Ops Intelligence & Optimization Portal** is an internal, full-stack web application that gives AT&T Cloud Center (ATTCC) teams real-time visibility into Azure spending, infrastructure health, and compliance posture. It replaces fragmented spreadsheets and manual processes with a single pane of glass.

| Concern | Technology |
|---|---|
| Backend API | **FastAPI** (Python 3.11+), async, Pydantic v2 |
| Database | **PostgreSQL** via SQLAlchemy 2 async + asyncpg, Alembic migrations |
| Cache | **Redis** 5+ |
| Frontend | **React 18** + TypeScript, Vite 5, TailwindCSS 3.4 |
| State Management | **Zustand** 4.5 + **React Query** (@tanstack/react-query 5.50) |
| Auth | **Azure AD (Entra ID)** — MSAL.js (frontend), OIDC/JWT middleware (backend) |
| Container Runtime | **AKS** (Azure Kubernetes Service) via Helm 3 |
| CI/CD | **GitHub Actions** → ACR → AKS |
| Observability | Prometheus metrics, structlog JSON logging |

**Repo:** `ATT-DP5/apm0014313-attcc-ops-portal`  
**Path:** `azure-ops-portal/` (sub-directory of the mono-repo)  
**Branches:** `main` (production), `develop` (dev), `infra` (infrastructure work)

---

## 2. Directory Map

```
azure-ops-portal/
├── .copilot/                   # ← You are here
├── .github/
│   ├── copilot-instructions.md # Session-level coding standards
│   ├── prompts/                # Reusable task prompts
│   └── workflows/ci-cd.yaml   # Full CI/CD pipeline
│
├── backend/
│   ├── app/
│   │   ├── api/v1/             # Versioned API routers (mounted on /api/v1)
│   │   ├── auth/               # Azure AD / Entra ID token validation
│   │   ├── core/               # App-wide config & infra
│   │   │   ├── config.py       # Pydantic Settings (env-based)
│   │   │   ├── database.py     # Async SQLAlchemy engine + session factory
│   │   │   ├── redis.py        # Async Redis client
│   │   │   ├── azure_auth.py   # Token verification, RBAC helpers
│   │   │   ├── azure_throttle.py # Azure API rate-limit handling
│   │   │   ├── logging.py      # structlog configuration
│   │   │   └── subscription_resolver.py
│   │   ├── middleware/
│   │   │   ├── audit.py        # Request/response audit logging
│   │   │   └── rate_limit.py   # Per-endpoint rate limiting
│   │   ├── models/             # SQLAlchemy ORM models
│   │   │   ├── auth.py
│   │   │   ├── cost.py
│   │   │   ├── database.py
│   │   │   ├── notification.py
│   │   │   └── optimization.py
│   │   ├── schemas/            # Pydantic request/response schemas
│   │   │   └── checksum_schedules.py
│   │   ├── services/           # Business logic (22 service modules)
│   │   ├── plugins/            # Auto-discovered plugin packages
│   │   │   ├── aks_insights/
│   │   │   └── keyvault_ops/
│   │   ├── routes/             # Supplementary route modules
│   │   │   └── checksum_schedules.py
│   │   └── main.py             # FastAPI app factory & startup
│   └── tests/
│       ├── test_api.py
│       └── test_models.py
│
├── frontend/
│   ├── src/
│   │   ├── components/         # 16 React components (TSX)
│   │   ├── services/           # 6 API client modules (Axios-based)
│   │   ├── config/authConfig.ts
│   │   ├── App.tsx
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts
│
├── helm/ops-portal/           # Helm 3 chart
│   ├── Chart.yaml
│   ├── values.yaml / values-dev.yaml / values-prod.yaml
│   └── templates/
│       ├── backend-deployment.yaml / backend-service.yaml
│       ├── frontend-deployment.yaml / frontend-service.yaml
│       ├── ingress.yaml
│       ├── hpa.yaml
│       ├── networkpolicy.yaml
│       └── secret-provider.yaml
│
├── scripts/                    # Synapse checksum shell scripts
│   ├── config/ , output/
│   ├── synapse_attcc_*.sh
│   └── synapse_ces_*.sh
│
├── docs/
│   ├── ENTRA_AUTH_IMPLEMENTATION_PLAN.md
│   └── RBAC_ROLES_PLAN.md
│
├── ARCHITECTURE.md             # Canonical architecture reference (367 lines)
├── SETUP.md                    # Local dev bootstrap
├── Prompt.md                   # Original prompt used to scaffold the project
├── plugin_registry.yaml        # Plugin manifest & creation guide
├── docker-compose.yaml         # Local dev compose (backend, frontend, postgres, redis)
├── Dockerfile.backend
├── Dockerfile.frontend
└── pyproject.toml              # Python project & dependency manifest
```

---

## 3. Backend Services (22 Modules)

Each file lives under `backend/app/services/` and exposes async functions consumed by the API routers.

| Service File | Responsibility |
|---|---|
| `admin_service.py` | User administration, role management |
| `aks_operations_service.py` | AKS cluster CRUD, scaling, pod metrics |
| `amortized_cost_sync_service.py` | Sync amortized cost data from Azure Cost Management |
| `azure_resource_service.py` | Azure Resource Graph queries |
| `blob_cost_service.py` | Storage account / blob cost breakdown |
| `budget_service.py` | Azure Budget management & threshold alerts |
| `compliance_service.py` | Checksum drift detection, compliance scoring |
| `cost_service.py` | Core cost aggregation, trending, forecasting |
| `dashboard_service.py` | Leadership & operations dashboard data |
| `data_cache_service.py` | Redis-backed data caching layer |
| `email_notification_service.py` | SMTP / SendGrid email dispatch |
| `env_cost_sync_service.py` | Environment-level cost synchronization |
| `infra_alert_service.py` | Infrastructure alert management |
| `keyvault_service.py` | Azure Key Vault secret read/write |
| `keyvault_sync_service.py` | Periodic Key Vault sync to DB |
| `notification_service.py` | In-app notification CRUD |
| `optimization_service.py` | Azure Advisor recommendations & custom rules |
| `report_service.py` | PDF/Excel report generation (WeasyPrint + jsPDF) |
| `scheduler_service.py` | APScheduler job management |
| `synapse_checksum_bash_service.py` | Run Synapse pipeline checksum scripts |

---

## 4. Frontend Components (16)

Each TSX file lives under `frontend/src/components/`.

| Component | Purpose |
|---|---|
| `App.tsx` | Root: MSAL provider, routing, layout |
| `AdminDashboard.tsx` | User & role management panel |
| `AKSOperationsPage.tsx` | Cluster, deployment, pod management UI |
| `AmortizedCostDashboard.tsx` | Amortized cost visualizations |
| `ChecksumScheduleForm.tsx` | Create/edit checksum schedule |
| `ChecksumScheduleList.tsx` | List & manage schedules |
| `ChecksumScheduleManagement.tsx` | Schedule admin wrapper |
| `CompliancePage.tsx` | Drift detection & compliance score |
| `EnvCostDetailsPage.tsx` | Per-environment cost details |
| `EnvDailyCostPage.tsx` | Daily cost trend per environment |
| `InfraAlertPage.tsx` | Infrastructure alert viewer |
| `KeyVaultPage.tsx` | Key Vault secret browser |
| `LeadershipDashboard.tsx` | Exec-level cost summary |
| `OperationsDashboard.tsx` | Day-to-day ops cost dashboard |
| `OptimizationPage.tsx` | Advisor recommendations & savings |
| `Toast.tsx` | Global toast notification component |

**Frontend API Services** (`frontend/src/services/`):
`aksApi.ts`, `apiClient.ts` (Axios instance + MSAL interceptor), `checksumScheduleApi.ts`, `complianceApi.ts`, `costApi.ts`, `infraAlertApi.ts`

---

## 5. API Surface

### Core REST prefixes (all under `/api/v1`)

| Prefix | Description |
|---|---|
| `/costs` | Cost queries, daily/monthly aggregation, forecasting |
| `/optimize` | Optimization recommendations, savings tracking |
| `/auth` | Current user, roles, token refresh |
| `/notifications` | Notification CRUD & preferences |
| `/reports` | Generate & download PDF/Excel reports |
| `/admin` | User management, system settings |
| `/plugins` | Plugin registry, per-plugin sub-routes |

### AKS Operations (14 endpoints)

`GET /clusters`, `GET /clusters/{id}`, `GET /deployments`, `POST /deployments/{name}/scale`, `POST /deployments/{name}/restart`, `GET /pods`, `GET /pods/{name}/metrics`, `GET /pods/utilization`, `GET /cronjobs`, `POST /cronjobs/{name}/trigger`, `GET /scale-history`, etc.

### Compliance & Drift Detection (10 endpoints)

`POST /compliance/synapse/register`, `POST /compliance/aks/register`, `GET /compliance/synapse/checksums`, `GET /compliance/aks/checksums`, `GET /compliance/drift`, `POST /compliance/drift/detect`, `GET /compliance/scores`, `GET /compliance/dashboard`, etc.

---

## 6. Database Models (SQLAlchemy)

| Model | Table | Key Fields |
|---|---|---|
| AuditLog | `audit_logs` | action, user, timestamp, details |
| AKSClusterSnapshot | `aks_cluster_snapshots` | cluster, node count, status, snapshot_at |
| AKSNodePoolSnapshot | `aks_nodepool_snapshots` | pool name, vm_size, count |
| DeploymentScaleHistory | `deployment_scale_history` | deployment, from/to replicas, user |
| PodUtilizationHistory | `pod_utilization_history` | pod, cpu_pct, memory_pct |
| CronJobAuditHistory | `cronjob_audit_history` | cronjob, trigger type, status |
| SynapsePipelineChecksum | `synapse_pipeline_checksums` | pipeline, checksum, collected_at |
| SynapsePipelineDrift | `synapse_pipeline_drifts` | pipeline, old/new checksum, detected_at |
| AKSPodChecksum | `aks_pod_checksums` | pod, checksum, collected_at |
| AKSPodDrift | `aks_pod_drifts` | pod, old/new checksum, detected_at |
| ComplianceScore | `compliance_scores` | scope, score, factors, computed_at |

---

## 7. Plugin Architecture

Plugins live under `backend/app/plugins/<plugin_name>/` and are **auto-discovered** at startup via `pkgutil`. Each plugin implements the `PluginBase` interface:

```python
class PluginBase:
    name: str
    version: str
    def register_routes(self, router: APIRouter) -> None: ...
    def get_permissions(self) -> list[str]: ...
    def get_dashboard_widgets(self) -> list[DashboardWidget]: ...
```

**Shipped plugins:**
- `aks_insights` — cluster health scoring, capacity forecasting
- `keyvault_ops` — bulk secret rotation, expiry alerts

**Plugin manifest:** `plugin_registry.yaml`

---

## 8. Authentication & RBAC

| Layer | Mechanism |
|---|---|
| Frontend | `@azure/msal-react` 2.0 — authorization-code + PKCE flow |
| Backend | OIDC JWT validation via `python-jose` + Azure AD JWKS |
| RBAC | Claims-based roles: **Admin**, **Write**, **Read** |
| Workload Identity | AKS → Azure APIs via Workload Identity Federation (no static secrets) |

Config is in `frontend/src/config/authConfig.ts` and `backend/app/core/azure_auth.py`.

---

## 9. Infrastructure & Deployment

| Layer | Detail |
|---|---|
| Containers | `Dockerfile.backend` (Python 3.11), `Dockerfile.frontend` (Node 20 → nginx) |
| Orchestration | Helm 3 chart in `helm/ops-portal/` |
| Ingress | NGINX Ingress Controller + cert-manager TLS |
| HPA | Backend auto-scales 2→10 replicas at 70% CPU |
| Network Policy | Restricts inter-pod traffic when `networkPolicy.enabled=true` |
| Secret Provider | Azure Key Vault via CSI driver (`secret-provider.yaml`) |
| Registry | Azure Container Registry (ACR) |

### CI/CD Pipeline (`.github/workflows/ci-cd.yaml`)

```
push/PR → test-backend (ruff, mypy, pytest)
        → test-frontend (npm lint, build)
        → security-scan (bandit)
        → build-images (docker build → ACR, Trivy scan)
        → deploy-dev (Helm upgrade, rollout verify)
        → deploy-production (Helm upgrade, rollout verify, approval gate)
```

**Environments:** `dev` (namespace `opsportal`), `prod` (namespace `opsportal`)

---

## 10. Key Python Dependencies

```
fastapi>=0.115          uvicorn[standard]>=0.30
sqlalchemy[asyncio]>=2.0 asyncpg>=0.29  alembic>=1.13
redis>=5.0              pydantic>=2.8  pydantic-settings>=2.3
azure-identity>=1.17    azure-mgmt-costmanagement>=4.0
azure-mgmt-resource>=23.1  azure-mgmt-monitor>=6.0
azure-mgmt-advisor>=9.0  azure-mgmt-keyvault>=10.3
azure-keyvault-secrets>=4.8
azure-mgmt-containerservice>=30.0
kubernetes>=29.0
python-jose[cryptography]>=3.3  httpx>=0.27
apscheduler>=3.10       weasyprint>=62.0
structlog>=24.1         prometheus-client>=0.20
```

**Dev tools:** `ruff>=0.5`, `mypy>=1.10`, `bandit`, `safety`, `pytest>=8.0`, `pytest-asyncio`, `pytest-cov`, `pre-commit`

---

## 11. Key Frontend Dependencies

```
react 18.3              react-dom 18.3
react-router-dom 6.25   @azure/msal-browser 3.20  @azure/msal-react 2.0
@tanstack/react-query 5.50  zustand 4.5
axios 1.7               recharts 2.12
tailwindcss 3.4         lucide-react 0.408
jspdf 2.5               jspdf-autotable 3.8
```

---

## 12. Naming & Style Conventions

| Scope | Convention |
|---|---|
| Python files/dirs | `snake_case` — `cost_service.py`, `aks_operations_service.py` |
| Python classes | `PascalCase` — `CostService`, `AKSClusterSnapshot` |
| Python functions | `async def get_daily_costs(...)` |
| TS/TSX files | `PascalCase` components — `LeadershipDashboard.tsx` |
| TS services | `camelCase` files — `costApi.ts`, `apiClient.ts` |
| API routes | `/api/v1/<resource>` (plural, lowercase, hyphens) |
| Helm values | `camelCase` keys (`replicaCount`, `imageTag`) |
| Env vars | `UPPER_SNAKE_CASE` — `DATABASE_URL`, `REDIS_URL`, `AZURE_TENANT_ID` |
| Git branches | `main`, `develop`, `feature/<ticket>-<slug>`, `infra` |

---

## 13. Useful Commands

```bash
# ── Backend ──────────────────────────────────────────────
cd azure-ops-portal/backend
uv sync --native-tls          # install all deps (creates .venv)
uv run ruff check app/
uv run mypy app/ --strict
uv run pytest --cov=app tests/

# Start/stop via scripts (recommended — handles port cleanup)
bash start.sh                  # starts on port 8002, cleans dangling processes
bash stop.sh                   # graceful shutdown + port cleanup

# Or run manually
uv run uvicorn app.main:app --host 0.0.0.0 --port 8002 --reload

# ── Frontend ─────────────────────────────────────────────
cd azure-ops-portal/frontend
npm ci
npm run dev          # Vite dev server on port 5177
npm run build        # Production build
npm run lint

# Start/stop via scripts (recommended — handles port cleanup)
bash start.sh                  # starts on port 5177, waits for backend
bash stop.sh                   # graceful shutdown + port cleanup

# ── Docker (local) ───────────────────────────────────────
cd azure-ops-portal
docker compose up --build      # backend:8000, frontend:3000, redis:6379

# ── Helm ─────────────────────────────────────────────────
helm upgrade --install ops-portal helm/ops-portal -n opsportal --create-namespace -f helm/ops-portal/values-dev.yaml
```
