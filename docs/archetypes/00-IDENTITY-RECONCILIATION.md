# 00 — Identity Reconciliation: `ops-portal`

> **Authoritative Source Statement:** The authoritative source of truth for `ops-portal` is **the code** (`558` files, `213728` lines analysed directly from the repository tree). Where prose documentation or comments diverge from implementation, this archetype pack reconciles identity strictly to executable code and configuration.

## 1. Code-Derived Service Definition

- **Canonical Name:** `ops-portal`
- **Version (Code-Grounded):** `1.3.13` (`# src: .github/actions/python-ci/action.yml`)
- **One-Line Definition:** `ops-portal` is a TypeScript / Node.js + Python + YAML / Declarative Orchestration & Config + Shell / Automation Scripts codebase comprising 558 files (213728 lines of code/config) across 6 module boundary/boundaries, exposing 30 deterministic ingress path(s).
- **Dominant Technology Stack(s):** TypeScript / Node.js, Python, YAML / Declarative Orchestration & Config, Shell / Automation Scripts
- **Primary Framework / Runtime:** `React + REST API`
- **Primary Entry Artifact:** `.claude/agents/Auth_Buddy.agent.md`
- **Primary Configuration Artifact:** `.github/actions/python-ci/action.yml`

## 2. Repository Boundary & Module Reconciliation

| Module / Directory | File Count | Representative Source Files |
|---|---|---|
| `backend` | 245 | `backend/.env`, `backend/.env.example`, `backend/.pytest-compliance.exit`, `backend/.pytest-compliance.out` |
| `docs` | 17 | `docs/AGENTIC_AI_CONVERSION_OPTIONS.md`, `docs/AI_PRIMITIVES.md`, `docs/AKV_ENV_SECRET_TEMPLATES.md`, `docs/ARCHITECTURE.md` |
| `frontend` | 200 | `frontend/.env`, `frontend/eslint.config.js`, `frontend/index.html`, `frontend/package-lock.json` |
| `helm` | 15 | `helm/ops-portal/Chart.yaml`, `helm/ops-portal/templates/_helpers.tpl`, `helm/ops-portal/templates/azure-key-vault-secret.yaml`, `helm/ops-portal/templates/backend-deployment.yaml` |
| `memories` | 19 | `memories/repo/amortized-sync-notes.md`, `memories/repo/compliance-cache-removal.md`, `memories/repo/compliance-dashboard-fix-v2.md`, `memories/repo/endpoint_buddy/alerts.md` |
| `root` | 7 | `.endpoint-probe.out`, `.gitignore`, `.pre-commit-config.yaml`, `Bulk_Secret_Update_Sample.json` |

## 3. Identity Preconditions Confirmed

1. **Single-Service Scope:** All evidence in this pack is scoped exclusively to `ops-portal`.
2. **Deterministic Ingress Inventory:** 30 ingress/entry paths were extracted in Step 0.5 prior to batch generation.
3. **Configuration Grounding:** 25 configuration/manifest file(s) and 20 environment variable binding(s) were reconciled against source references.
