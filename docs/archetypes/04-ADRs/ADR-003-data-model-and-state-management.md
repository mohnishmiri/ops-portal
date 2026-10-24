# ADR-003: Data Model, Schema & Configuration State Management for `ops-portal`

- **Status:** Accepted (verified in repository)
- **Evidence:** `.claude/prompts/add-database-model.prompt.md`, `.github/actions/python-ci/action.yml`

## Context
`ops-portal` defines 40 code symbols/models and 25 data/schema artifact(s) that govern runtime state.

## Decision
Maintain explicit type/schema definitions in `.claude/prompts/add-database-model.prompt.md` and externalize environment-specific parameters via `.github/actions/python-ci/action.yml`.

## Consequences
- **Positive:** Schema changes and configuration overrides are version-controlled alongside code.
- **Trade-off:** Schema migrations or configuration key renames must be coordinated during deployment.
