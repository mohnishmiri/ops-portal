# ADR-004: Error Handling, Security Guardrails & Operational Telemetry for `ops-portal`

- **Status:** Accepted (verified in repository)
- **Evidence:** `.claude/agents/Auth_Buddy.agent.md`

## Context
Production operation of `ops-portal` requires structured failure handling (20 error patterns detected), security boundary enforcement (12 controls detected), and operational visibility.

## Decision
Surface domain and I/O failures through explicit error handlers and enforce authentication/configuration guardrails at the service boundary.

## Consequences
- **Positive:** Predictable failure behavior and auditable security controls.
- **Trade-off:** Uncaught downstream timeouts must be monitored via runbook triage procedures.
