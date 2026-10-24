# Archetype Generation — Shared Evidence & Gap Register
# Service: ops-portal
# MS Root: .
# Profile: FULL

## Ingress Inventory (deterministic, orchestrator-run)

| # | Route / Trigger / Entry | Handler / Symbol | Kind | Active (Y/N) | Source Location |
|---|---|---|---|---|---|
| 1 | `/action` | `backend-page-mutation-template::line_22` | REST POST | Y | `.claude/skills/ui-buddy-page-builder/templates/backend-page-mutation-template.py:22` |
| 2 | `task:Set up uv` | `.github/actions/python-ci/action.yml:47` | Automation Task | Y | `.github/actions/python-ci/action.yml:47` |
| 3 | `task:Cache uv global cache` | `.github/actions/python-ci/action.yml:52` | Automation Task | Y | `.github/actions/python-ci/action.yml:52` |
| 4 | `task:Cache virtual environment` | `.github/actions/python-ci/action.yml:62` | Automation Task | Y | `.github/actions/python-ci/action.yml:62` |
| 5 | `task:Bridge pip index auth to uv` | `.github/actions/python-ci/action.yml:71` | Automation Task | Y | `.github/actions/python-ci/action.yml:71` |
| 6 | `task:Sync workspace` | `.github/actions/python-ci/action.yml:79` | Automation Task | Y | `.github/actions/python-ci/action.yml:79` |
| 7 | `task:Lint (ruff)` | `.github/actions/python-ci/action.yml:85` | Automation Task | Y | `.github/actions/python-ci/action.yml:85` |
| 8 | `task:Format check (ruff)` | `.github/actions/python-ci/action.yml:91` | Automation Task | Y | `.github/actions/python-ci/action.yml:91` |
| 9 | `task:Type check (mypy)` | `.github/actions/python-ci/action.yml:97` | Automation Task | Y | `.github/actions/python-ci/action.yml:97` |
| 10 | `task:Tests with coverage` | `.github/actions/python-ci/action.yml:104` | Automation Task | Y | `.github/actions/python-ci/action.yml:104` |
| 11 | `task:Sanitize ref name for artifact usage` | `.github/actions/python-ci/action.yml:120` | Automation Task | Y | `.github/actions/python-ci/action.yml:120` |
| 12 | `task:Upload coverage HTML Report` | `.github/actions/python-ci/action.yml:127` | Automation Task | Y | `.github/actions/python-ci/action.yml:127` |
| 13 | `task:Upload coverage XML Report` | `.github/actions/python-ci/action.yml:135` | Automation Task | Y | `.github/actions/python-ci/action.yml:135` |
| 14 | `task:Run bandit (security static analysis` | `.github/actions/python-ci/action.yml:143` | Automation Task | Y | `.github/actions/python-ci/action.yml:143` |
| 15 | `task:Upload bandit report` | `.github/actions/python-ci/action.yml:159` | Automation Task | Y | `.github/actions/python-ci/action.yml:159` |
| 16 | `/action` | `backend-page-mutation-template::line_22` | REST POST | Y | `.github/skills/ui-buddy-page-builder/templates/backend-page-mutation-template.py:22` |
| 17 | `/me` | `access::line_64` | REST GET | Y | `backend/app/api/v1/endpoints/access.py:64` |
| 18 | `/catalog` | `access::line_74` | REST GET | Y | `backend/app/api/v1/endpoints/access.py:74` |
| 19 | `/requests` | `access::line_95` | REST POST | Y | `backend/app/api/v1/endpoints/access.py:95` |
| 20 | `/requests/mine` | `access::line_120` | REST GET | Y | `backend/app/api/v1/endpoints/access.py:120` |
| 21 | `/requests/{request_id}/cancel` | `access::line_128` | REST POST | Y | `backend/app/api/v1/endpoints/access.py:128` |
| 22 | `/admin/projects` | `access::line_142` | REST GET | Y | `backend/app/api/v1/endpoints/access.py:142` |
| 23 | `/admin/projects` | `access::line_164` | REST POST | Y | `backend/app/api/v1/endpoints/access.py:164` |
| 24 | `/admin/projects/{project_id}` | `access::line_177` | REST GET | Y | `backend/app/api/v1/endpoints/access.py:177` |
| 25 | `/admin/projects/{project_id}` | `access::line_191` | REST DELETE | Y | `backend/app/api/v1/endpoints/access.py:191` |
| 26 | `/admin/projects/{project_id}/apps` | `access::line_215` | REST POST | Y | `backend/app/api/v1/endpoints/access.py:215` |
| 27 | `/admin/apps/{app_id}` | `access::line_234` | REST GET | Y | `backend/app/api/v1/endpoints/access.py:234` |
| 28 | `/admin/apps/{app_id}` | `access::line_248` | REST DELETE | Y | `backend/app/api/v1/endpoints/access.py:248` |
| 29 | `/admin/projects/{project_id}/admins` | `access::line_263` | REST POST | Y | `backend/app/api/v1/endpoints/access.py:263` |
| 30 | `/admin/projects/{project_id}/admins/{user_id}` | `access::line_275` | REST DELETE | Y | `backend/app/api/v1/endpoints/access.py:275` |

## Batch 1 — Identity & Foundation
### Key files read
- `.github/actions/python-ci/action.yml`
- `.claude/agents/Auth_Buddy.agent.md`
- `.claude/agents/Auth_Buddy.agent.md`
- `.claude/agents/DataFlow_Buddy.agent.md`
- `.claude/agents/Endpoint_Buddy.agent.md`
- `.claude/agents/UI_Buddy.agent.md`
- `.claude/instructions/backend.instructions.md`
- `.claude/instructions/frontend.instructions.md`
- `.claude/instructions/plugins.instructions.md`
- `.claude/instructions/tests.instructions.md`
- `.claude/prompts/add-api-endpoint.prompt.md`
- `.claude/prompts/add-azure-service-integration.prompt.md`
- `.claude/prompts/add-dashboard-chart.prompt.md`
- `.claude/prompts/add-database-model.prompt.md`
### Facts established / corrected
- Dominant stack(s): TypeScript / Node.js, Python, YAML / Declarative Orchestration & Config, Shell / Automation Scripts (558 files, 213728 lines across 6 modules)
- Canonical version: `1.3.13`
### Artifacts written
- `docs/archetypes/00-IDENTITY-RECONCILIATION.md`
- `docs/archetypes/01-README.md`
- `docs/archetypes/02-ARCHITECTURE.md`
- `docs/archetypes/03-SERVICE-MANIFEST.yaml`
### Ingress coverage (Batches 1 & 2 only)
- Inventory rows covered: 30/30

## Batch 2 — Design & Flow
### Facts established / corrected
- Reconstructed 4 Architecture Decision Records (`ADR-001`..`ADR-004`).
- Generated component diagram and 12 dedicated sequence diagrams.
- Cataloged 40 symbols/entities in `07-data-model.md`.
### Ingress coverage (Batches 1 & 2 only)
- Inventory rows covered: 30/30

## Batch 3 — Failure & Governance
### Facts established / corrected
- Cataloged 20 error patterns in `08-error-taxonomy.md`.
- Reconciled 5 Tier-3 service rules in `09-tier3-service-rules.md`.
- Authored onboarding context bundle in `10-service-memories-seed.md`.

## Batch 4 — Quality, Security & Operations
### Facts established / corrected
- Audited 25 test file(s) in `11-test-strategy.md`.
- Built STRIDE threat model and trust-boundary diagram in `12-threat-model.md`.
- Defined health/logging/SLO contract in `13-observability-contract.md`.

## Batch 5 — Close-out
### Artifacts written
- `docs/archetypes/00-IDENTITY-RECONCILIATION.md`
- `docs/archetypes/01-README.md`
- `docs/archetypes/02-ARCHITECTURE.md`
- `docs/archetypes/03-SERVICE-MANIFEST.yaml`
- `docs/archetypes/04-ADRs/README.md`
- `docs/archetypes/04-ADRs/ADR-001-module-and-service-boundaries.md`
- `docs/archetypes/04-ADRs/ADR-002-ingress-and-interface-contracts.md`
- `docs/archetypes/04-ADRs/ADR-003-data-model-and-state-management.md`
- `docs/archetypes/04-ADRs/ADR-004-error-handling-security-and-operations.md`
- `docs/archetypes/05-component-diagram.md`
- `docs/archetypes/06-sequence-diagrams.md`
- `docs/archetypes/07-data-model.md`
- `docs/archetypes/08-error-taxonomy.md`
- `docs/archetypes/09-tier3-service-rules.md`
- `docs/archetypes/10-service-memories-seed.md`
- `docs/archetypes/11-test-strategy.md`
- `docs/archetypes/12-threat-model.md`
- `docs/archetypes/13-observability-contract.md`
- `docs/archetypes/14-runbook.md`
- `docs/archetypes/15-tribal-knowledge.md`
- `docs/archetypes/00-INDEX.md`
- `docs/archetypes/ARCHETYPE-SUMMARY.md`

## Batch 6 — Bounded Context
### Artifacts written
- `docs/BOUNDED-CONTEXT-ops-portal.md`

## Gap Register (append-only, cumulative)
| Batch | Open Question / Unverified Assumption | Severity | Status |
|---|---|---|---|
| 4 | Confirm upstream gateway rate-limit thresholds for `ops-portal` | medium | open |
| 6 | Confirm CI coverage enforcement gate for `ops-portal` | low | open |
