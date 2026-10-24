# 10 — Service Memories Seed (AI Agent & Onboarding Context): `ops-portal`

> Curated context bundle designed to seed AI coding agents and onboard engineers onto `ops-portal` with zero hallucination.

## 1. Mental Model of `ops-portal`

- **What it is:** `ops-portal` is a TypeScript / Node.js + Python + YAML / Declarative Orchestration & Config + Shell / Automation Scripts codebase comprising 558 files (213728 lines of code/config) across 6 module boundary/boundaries, exposing 30 deterministic ingress path(s).
- **Dominant Stack:** TypeScript / Node.js, Python, YAML / Declarative Orchestration & Config, Shell / Automation Scripts
- **Scale:** 558 files (213728 lines) partitioned across 6 module(s).
- **Primary Entrypoint:** `.claude/agents/Auth_Buddy.agent.md`
- **Primary Config:** `.github/actions/python-ci/action.yml`

## 2. High-Signal File Map (Read These First)

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
- `.claude/prompts/add-new-page.prompt.md`
- `.claude/prompts/add-new-plugin.prompt.md`
- `.claude/prompts/add-service.prompt.md`

## 3. Core Architectural Invariants

1. **Authoritative Source = Code:** Always verify route definitions, schemas, and parameters in `.claude/agents/Auth_Buddy.agent.md` and `.github/actions/python-ci/action.yml`.
2. **Ingress Completeness:** `ops-portal` exposes 30 active ingress/entry path(s); check `02-ARCHITECTURE.md` before modifying routing.
3. **Data & Symbol Continuity:** Core domain constructs (40 symbols discovered) are cataloged in `07-data-model.md`.

## 4. Safe Modification Playbook

- **Adding a feature or route:** Update the handler module, register the route/task, add validation, and run `npm test`.
- **Changing configuration:** Update `.github/actions/python-ci/action.yml` and document any new environment variable in `01-README.md`.
