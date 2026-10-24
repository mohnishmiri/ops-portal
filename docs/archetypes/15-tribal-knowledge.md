# 15 — Tribal Knowledge & Senior-Engineer Warnings: `ops-portal`

> "Learned by getting burned" operational caveats, implicit coupling, and non-obvious code behaviors discovered in `ops-portal`.

## 1. Critical Codebase Gotchas

1. **Configuration Precedence (`.github/actions/python-ci/action.yml`):** Environment variables and declarative configuration files interact at startup; changing `.github/actions/python-ci/action.yml` without checking active environment overrides can leave runtime behavior unchanged.
2. **Implicit Coupling Between Ingress & Data Contracts (`.claude/agents/Auth_Buddy.agent.md` <-> `.claude/prompts/add-database-model.prompt.md`):** Handler logic in `.claude/agents/Auth_Buddy.agent.md` assumes inputs conform to the structure defined in `.claude/prompts/add-database-model.prompt.md`. Renaming fields without updating both breaks downstream consumers.
3. **Module Boundary Assumptions:** `ops-portal` spans 6 top-level module(s) (`backend`, `docs`, `frontend`, `helm`, `memories`, `root`); shared utilities or configurations modified in one module affect all 30 active ingress path(s).
4. **Test Coverage Blind Spots:** Only 25 dedicated test file(s) were detected across 558 total files — always run manual smoke verification on modified ingress paths in addition to automated tests.

## 2. Pre-Merge Review Checklist for Senior Engineers

- Did any route/task signature in `.claude/agents/Auth_Buddy.agent.md` change without updating `03-SERVICE-MANIFEST.yaml` and `06-sequence-diagrams.md`?
- Were any new environment variables introduced without a safe default or startup validation check?
- Do all Mermaid diagrams and flow parity checks in `ARCHETYPE-SUMMARY.md` remain green?
