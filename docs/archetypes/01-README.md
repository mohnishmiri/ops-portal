# 01 — Operator README & Pack Overview: `ops-portal`

## 1. Purpose & Responsibility Boundary

`ops-portal` is a TypeScript / Node.js + Python + YAML / Declarative Orchestration & Config + Shell / Automation Scripts codebase comprising 558 files (213728 lines of code/config) across 6 module boundary/boundaries, exposing 30 deterministic ingress path(s).

### What `ops-portal` DOES
- Implements 30 distinct ingress/execution path(s) across 6 top-level module(s).
- Enforces domain structures across 40 discovered code symbols/models (`TypeScript / Node.js, Python, YAML / Declarative Orchestration & Config, Shell / Automation Scripts`).
- Manages runtime configuration through `.github/actions/python-ci/action.yml` and 20 environment binding(s).

### What `ops-portal` Does NOT Do
- Does **not** manage external identity provider (IdP) user directories outside its authentication boundary.
- Does **not** mutate external upstream systems without an explicit egress/output contract.
- Does **not** bypass repository-level configuration and schema contracts defined in `.github/actions/python-ci/action.yml`.

## 2. Build, Run & Verification Commands

```bash
# Build / Prepare
npm install && npm run build

# Execute Verification / Test Suite
npm test
```

## 3. Runtime Ports & Network Listeners

- **Port `8000`** — declared in `.claude/agents/Endpoint_Buddy.agent.md:264`
- **Port `6379`** — declared in `.claude/agents/Endpoint_Buddy.agent.md:266`
- **Port `5432`** — declared in `.claude/agents/Endpoint_Buddy.agent.md:267`
- **Port `80`** — declared in `Dockerfile.frontend:114`
- **Port `3000`** — declared in `backend/.env.example:36`
- **Port `8080`** — declared in `backend/app/core/config.py:402`
- **Port `443`** — declared in `backend/app/services/mongodb_atlas_service.py:216`
- **Port `5173`** — declared in `backend/tests/test_admin_cors_config.py:10`

## 4. Environment Variables & Runtime Configuration

- **`PIP_INDEX_URL`** — referenced at `.github/actions/python-ci/action.yml:74`
- **`UV_DEFAULT_INDEX`** — referenced at `.github/actions/python-ci/action.yml:74`
- **`UV_INDEX_URL`** — referenced at `.github/actions/python-ci/action.yml:74`
- **`GITHUB_ENV`** — referenced at `.github/actions/python-ci/action.yml:75`
- **`COVERAGE_ARGS`** — referenced at `.github/actions/python-ci/action.yml:112`
- **`GITHUB_REF_NAME`** — referenced at `.github/actions/python-ci/action.yml:124`
- **`SAFE_REF_NAME`** — referenced at `.github/actions/python-ci/action.yml:125`
- **`GITHUB_OUTPUT`** — referenced at `.github/actions/python-ci/action.yml:125`
- **`BANDIT_CONFIG_PATH`** — referenced at `.github/actions/python-ci/action.yml:150`
- **`BANDIT_ARGS`** — referenced at `.github/actions/python-ci/action.yml:157`
- **`BACKEND_VERSION`** — referenced at `.github/workflows/ci-cd.yaml:156`
- **`FRONTEND_VERSION`** — referenced at `.github/workflows/ci-cd.yaml:160`
- **`GITHUB_REF`** — referenced at `.github/workflows/ci-cd.yaml:168`
- **`GITHUB_SHA`** — referenced at `.github/workflows/ci-cd.yaml:169`
- **`BACKEND_VERSION_TAG`** — referenced at `.github/workflows/ci-cd.yaml:175`

## 5. Direct Dependencies (Code-Grounded)

| Dependency | Version / Spec | Ecosystem | Source Reference |
|---|---|---|---|
| `@azure/msal-browser` | `^3.20.0` | npm | `frontend/package.json:16` |
| `@azure/msal-react` | `^2.0.0` | npm | `frontend/package.json:17` |
| `@tanstack/react-query` | `^5.50.0` | npm | `frontend/package.json:18` |
| `axios` | `^1.7.0` | npm | `frontend/package.json:19` |
| `jspdf` | `^4.2.1` | npm | `frontend/package.json:20` |
| `jspdf-autotable` | `^5.0.7` | npm | `frontend/package.json:21` |
| `react` | `^18.3.0` | npm | `frontend/package.json:22` |
| `react-dom` | `^18.3.0` | npm | `frontend/package.json:23` |
| `react-router-dom` | `^6.25.0` | npm | `frontend/package.json:24` |
| `recharts` | `^2.12.0` | npm | `frontend/package.json:25` |
| `zustand` | `^4.5.0` | npm | `frontend/package.json:26` |
| `@testing-library/dom` | `^10.4.1` | npm | `frontend/package.json:29` |
| `@testing-library/jest-dom` | `^6.9.1` | npm | `frontend/package.json:30` |
| `@testing-library/react` | `^16.3.2` | npm | `frontend/package.json:31` |
| `@testing-library/user-event` | `^14.6.1` | npm | `frontend/package.json:32` |
| `@types/react` | `^18.3.0` | npm | `frontend/package.json:33` |
| `@types/react-dom` | `^18.3.0` | npm | `frontend/package.json:34` |
| `@vitejs/plugin-react` | `^4.3.0` | npm | `frontend/package.json:35` |
| `@vitest/ui` | `^4.1.5` | npm | `frontend/package.json:36` |
| `autoprefixer` | `^10.4.0` | npm | `frontend/package.json:37` |

## 6. Ownership & Governance Metadata

- **Service Identifier:** `ops-portal`
- **Primary Configuration File:** `.github/actions/python-ci/action.yml`
- **Bounded Context Deliverable:** [`../BOUNDED-CONTEXT-ops-portal.md`](../BOUNDED-CONTEXT-ops-portal.md)
- **Canonical Manifest:** [`03-SERVICE-MANIFEST.yaml`](03-SERVICE-MANIFEST.yaml)
