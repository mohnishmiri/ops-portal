# 14 — Operational Runbook & On-Call Triage Playbook: `ops-portal`

## 1. Incident Triage Flow (`flowchart TD`)

```mermaid
flowchart TD
ALERT(["Alert / Incident Reported on ops-portal"]) --> CHECK_CFG{"Config & Env Vars Valid? (.github/actions/python-ci/action.yml)"}
CHECK_CFG -->|"No"| FIX_CFG["Restore missing env var / config in .github/actions/python-ci/action.yml & restart"]
CHECK_CFG -->|"Yes"| CHECK_ING{"Ingress Handler Reachable? (.claude/agents/Auth_Buddy.agent.md)"}
CHECK_ING -->|"No"| RESTART["Inspect process/container logs & redeploy ops-portal"]
CHECK_ING -->|"Yes"| CHECK_DEPS{"Downstream Store / Dependency Healthy?"}
CHECK_DEPS -->|"No"| MITIGATE_DEP["Failover or throttle requests to downstream dependency"]
CHECK_DEPS -->|"Yes"| TRACE_ERR["Inspect structured error logs against 08-error-taxonomy.md"]
FIX_CFG --> VERIFY(["Run Post-Recovery Verification Checklist"])
RESTART --> VERIFY
MITIGATE_DEP --> VERIFY
TRACE_ERR --> VERIFY
```

## 2. Pre-Flight & Startup Checklist

- [ ] Confirm `.github/actions/python-ci/action.yml` is present and passes syntax validation.
- [ ] Confirm all 20 environment variable binding(s) documented in `01-README.md` are populated.
- [ ] Confirm build/preparation command succeeds: `npm install && npm run build`.
- [ ] Confirm verification suite passes: `npm test`.
- [ ] Verify primary ingress path (`/action`) responds as expected.

## 3. Symptom -> Diagnostics -> Recovery Playbooks

| Symptom | Diagnostic Step | Recovery Action |
|---|---|---|
| Startup / Initialization Failure | Check logs around `.github/actions/python-ci/action.yml` and environment variable resolution | Supply missing environment variables or restore last known-good `.github/actions/python-ci/action.yml` |
| Ingress Request / Task Rejection | Inspect handler at `.claude/agents/Auth_Buddy.agent.md` and compare input payload against `07-data-model.md` | Correct caller payload or roll back incompatible schema change |
| Elevated Failure Rate | Correlate error logs with `08-error-taxonomy.md` | Roll back recent deployment and verify downstream connectivity |
