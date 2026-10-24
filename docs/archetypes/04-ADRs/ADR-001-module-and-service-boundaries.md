# ADR-001: Module Partitioning & Technology Stack Selection for `ops-portal`

- **Status:** Accepted (verified in repository)
- **Evidence:** `.github/actions/python-ci/action.yml`, `.claude/agents/Auth_Buddy.agent.md`

## Context
`ops-portal` requires a maintainable structure for its 558 files (213728 lines) across 6 top-level module(s) using **TypeScript / Node.js, Python, YAML / Declarative Orchestration & Config, Shell / Automation Scripts**.

## Decision
Organize the codebase into explicit module directories (`backend`, `docs`, `frontend`, `helm`, `memories`, `root`) managed via `npm install && npm run build` and configured through `.github/actions/python-ci/action.yml`.

## Consequences
- **Positive:** Clear separation of concerns between entrypoints, domain logic, and configuration.
- **Trade-off:** Changes spanning multiple modules require coordinated testing across `25` test file(s).
