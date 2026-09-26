# Project Rules

These rules are tool-neutral and apply to Windsurf, VS Code agents, Claude Code, Devin, and other coding agents.

## Read order

1. Read `STATE.md` first.
2. Read only the primary document named in `STATE.md`.
3. Open supporting documents only when the current task requires them.
4. Search before opening large files; do not reconstruct history from every document.
5. Read `LEARNINGS.md` selectively by keyword or topic, not in full at session start.

## Product invariants

- The canonical intake is the production boundary: evidence readers propose data; Topology, ADS, and DDD consume reviewed canonical snapshots.
- Never invent a missing application value or infer `No` from absence.
- Never silently resolve conflicting evidence. Preserve scoped candidates and require an authorized decision.
- Keep facts typed and scoped with raw/normalized value, unit, lifecycle, environment, site/resource identity, source locator, provenance, confidence, and review state as applicable.
- Compare only like-for-like facts; semantic or scope differences are not automatically conflicts.
- Importers and runtime AI create candidates, never approved facts.
- Prefer deterministic extraction for known structured formats. AI may assist with unresolved or narrative fragments but cannot approve, overwrite, or make architect decisions.
- Renderers use immutable approved snapshots, never mutable live answers or arbitrary source files.
- Treat reusable template prose as `EXAMPLE` unless reviewed evidence supports it.
- Portal evidence requires source, record ID/reference, retrieval time, and collector where available. Do not store portal credentials in v1.
- Validate application, wave, environment, and freshness before treating a document as applicable evidence.

## Architecture and implementation

- Inspect neighboring code, manifests, tests, and established conventions before editing.
- Keep web routes, application services, domain policies, repositories, importers, and generators separated; routes do not write SQL and templates do not calculate workflow truth.
- Use append-only answer/register revisions and immutable catalog/snapshot releases where the design requires auditability.
- Avoid new abstractions with only one consumer unless they enforce a real boundary.
- Verify dependencies exist before importing them; add dependencies through the project package manager.
- Do not promote `_data/spike` constraints such as its five-module limit to the future production application.

## Working loop

1. Orient from `STATE.md` and the active document.
2. Search and understand the affected behavior and boundaries.
3. Plan non-trivial work, naming files and deterministic verification.
4. Make the smallest coherent change.
5. Run focused checks, then broader applicable verification before completion.
6. Review edge cases and the final diff.
7. Update `STATE.md` after a meaningful design or implementation slice.
8. Append to `LEARNINGS.md` only after a concrete discovery or correction worth preserving.

## Data handling

- `_data` contains private client evidence. Do not commit it, quote it externally, or copy it outside this workspace.
- Tests must use synthetic fixtures, not client evidence.
- Do not send client evidence to an external AI provider without explicit approval and an approved data-handling boundary.
- Never expose or commit credentials, tokens, or secrets.

## Verification

- Topology spike: from `_data/spike`, run `python -m pytest -q`.
- UI mockup JavaScript: from the workspace root, run `node --check _data/spike/mockup/app.js`.
- SQLite schema: use the focused in-memory integrity command documented in the active design handoff.
- Production application: from workspace root, run:
  - Install: `pip install -e ".[dev]"`
  - All tests: `python -m pytest tests/ -v` (788 tests as of C01)
  - Unit tests only: `python -m pytest tests/unit/ -v`
  - Domain tests: `python -m pytest tests/unit/domain/ -v`
  - Application tests: `python -m pytest tests/unit/application/ -v`
  - Catalog tests: `python -m pytest tests/unit/catalog/ -v`
  - Response type tests: `python -m pytest tests/unit/catalog/response_types/ -v`
  - Web tests: `python -m pytest tests/web/ -v`
  - Type check: `python -m mypy src/migration_intake`
  - Lint: `python -m ruff check src/`
