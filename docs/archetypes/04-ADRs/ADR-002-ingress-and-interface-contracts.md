# ADR-002: Deterministic Ingress & Interface Contracts for `ops-portal`

- **Status:** Accepted (verified in repository)
- **Evidence:** `.claude/agents/Auth_Buddy.agent.md` (30 ingress paths inventoried)

## Context
External callers and automation triggers interact with `ops-portal` through 30 defined ingress/entry path(s).

## Decision
Expose explicit route/trigger handlers (such as `/action` in `.claude/skills/ui-buddy-page-builder/templates/backend-page-mutation-template.py`) and validate inputs prior to domain execution.

## Consequences
- **Positive:** Every active ingress path is traceable to a concrete file and line number.
- **Trade-off:** Route/contract modifications require synchronized updates in downstream consumers.
