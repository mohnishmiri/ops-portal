# 13 — Observability Contract (Metrics, Health & Logging): `ops-portal`

## 1. Code-Grounded Telemetry & Logging Signals

- `.claude/agents/Endpoint_Buddy.agent.md:155` — `| 'backend/app/main.py' | App-level routes ('/healthz', '/readyz', '/metric`
- `.claude/agents/Endpoint_Buddy.agent.md:187` — `| 3 | GET | /healthz | dev | None | 200 | 12ms | ✅ PASS | |`
- `.claude/agents/Endpoint_Buddy.agent.md:255` — `- System routes: '/healthz' (liveness), '/readyz' (readiness), '/metrics' (`
- `.claude/agents/Endpoint_Buddy.agent.md:260` — `- '/healthz' and '/metrics' are unauthenticated`
- `.claude/instructions/backend.instructions.md:14` — `- Use 'structlog' for logging. Do not add 'print()' calls.`
- `.claude/prompts/add-service.prompt.md:44` — `logger.info("fetching_{{resource}}")`
- `.claude/prompts/add-service.prompt.md:58` — `logger.info("created_{{resource}}", id=str(obj.id))`
- `.copilot/context.md:21` — `| Observability | Prometheus metrics, structlog JSON logging |`
- `.copilot/context.md:49` — `│   │   │   ├── logging.py      # structlog configuration`
- `.copilot/context.md:191` — `'GET /clusters', 'GET /clusters/{id}', 'GET /deployments', 'POST /deploymen`
- `.copilot/context.md:296` — `structlog>=24.1         prometheus-client>=0.20`
- `.github/agents/Endpoint_Buddy.agent.md:155` — `| 'backend/app/main.py' | App-level routes ('/healthz', '/readyz', '/metric`

## 2. Health, Readiness & Liveness Contract

| Probe / Signal | Path / Mechanism | Expected Healthy Output | Source Location |
|---|---|---|---|
| Primary Entry / Health Check | `/action` | HTTP 200 / Exit Code 0 | `.claude/skills/ui-buddy-page-builder/templates/backend-page-mutation-template.py:22` |
| Configuration Load Check | Startup parse of `.github/actions/python-ci/action.yml` | Validated config state | `.github/actions/python-ci/action.yml` |

## 3. Recommended SLI / SLO & Alerting Contract

| Indicator (SLI) | Target Objective (SLO) | Alert Condition |
|---|---|---|
| Ingress Availability | >= 99.9% successful execution across 30 active path(s) | 5xx / failure rate > 1% over 5 minutes |
| Execution Latency | p95 within operational SLA | p95 latency > threshold for 10 minutes |
| Error Rate | < 0.5% unhandled exceptions (`08-error-taxonomy.md`) | Spike in error logs from `.claude/agents/Auth_Buddy.agent.md` |
