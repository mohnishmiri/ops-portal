# 09 — Reconciled Tier-3 Service Rules: `ops-portal`

> Reconciles global platform rules (Tier-1) and domain rules (Tier-2) into concrete, code-grounded Tier-3 guardrails specific to `ops-portal`.

## 1. Tier Reconciliation Matrix

| Rule ID | Tier-1 / Tier-2 Requirement | `ops-portal` Tier-3 Service Rule | Code Evidence | Status |
|---|---|---|---|---|
| `T3-001` | Deterministic Ingress & Contract Safety | All inbound requests/triggers MUST route through declared handlers in the Step 0.5 inventory (30 paths). | `.claude/agents/Auth_Buddy.agent.md` | ✅ Reconciled |
| `T3-002` | Externalized Environment Configuration | Environment-specific endpoints, credentials, and toggles MUST be externalized via `.github/actions/python-ci/action.yml` or env vars (20 bindings). | `.github/actions/python-ci/action.yml` | ✅ Reconciled |
| `T3-003` | Structured Error Propagation | Errors MUST NOT be silently swallowed; all failure paths listed in `08-error-taxonomy.md` must log context and return structured status. | `.claude/agents/Auth_Buddy.agent.md` | ✅ Reconciled |
| `T3-004` | Automated Verification Gate | Every new ingress route or schema change MUST include corroborating test coverage under `.claude/instructions/tests.instructions.md`. | `.claude/instructions/tests.instructions.md` | ✅ Reconciled |
| `T3-005` | Secret & Credential Hygiene | Secrets, PATs, and private keys MUST NEVER be committed to `ops-portal` source or configuration files. | `.github/actions/python-ci/action.yml` | ✅ Reconciled |

## 2. Mandatory Guardrails for AI Agents & Engineers Modifying `ops-portal`

1. **Do not add undocumented ingress routes:** Any new endpoint, job, or playbook task must be added to the Step 0.5 Ingress Inventory and paired with a sequence diagram in `06-sequence-diagrams.md`.
2. **Preserve schema compatibility:** Modifications to symbols listed in `07-data-model.md` must maintain backward compatibility with existing callers.
3. **Keep `03-SERVICE-MANIFEST.yaml` synchronized:** Dependency or entrypoint changes require updating the canonical manifest.
