# Proposed Standalone Runtime Boundary

Status: USER CONFIRMATION REQUIRED. No command in this document has been executed. Existing `tests/` and `to_archive/` remain excluded from inspection, imports and evidence.

## Permitted Target If Approved

- Python process uses the repository's selected/declared Python 3.13 environment only after interpreter/dependency facts are checked.
- Working directory: a new disposable directory under `docs/development/topo_9_24/runtime_sandbox/`, not repository root.
- Database: new SQLite file inside that sandbox. No existing SQLite/Oracle URL, schema or service.
- Evidence/artifacts/cache/logs: sandbox paths only.
- Settings: constructed with `_env_file=None` and explicit synthetic actor/application/intake/CSRF values. Sanitize inherited AWS_OUTPOST_*, APP_ENV, DATABASE_URL, ORACLE_*, LLM_*, cloud and proxy-sensitive application variables before process launch.
- LLM/provider network: disabled/mock; no outbound provider calls.
- Cloud/portal: no credentials, SDK calls or resource mutation.
- Source/reference files: read-only. Any helper scripts and normalized outputs stay in the analysis workspace.
- Data: synthetic only. Do not use `_data`, client workbooks, tests fixtures or archived evidence. The supplied Draw.io/guide references may be read only for an explicitly scoped semantic check.

## Proposed Stages Requiring Separate Go Decisions

1. Environment preflight: selected interpreter, installed imports, no inherited sensitive aliases, output directories. Read-only.
2. Disposable schema: migrate a newly created sandbox SQLite database; verify FK pragma/head/integrity. Mutates sandbox only.
3. One standalone pure/source probe per verified hypothesis, written under analysis workspace and importing production modules without tests.
4. Optional local server/browser journey on sandbox DB/storage. Startup catalog publication and readiness storage writes are allowed only inside sandbox. Bind loopback only and stop/cleanly retain evidence afterward.
5. Concurrency probes: independent sessions against disposable SQLite; Oracle behavior remains UNKNOWN unless separately approved with an explicitly authorized disposable schema.

## Initial Proposed Probes

- F-OBS-001 readiness healthy/degraded response after importing `literal` is not fixed in this review; characterize current failure only if useful.
- F-PIPE-001 populated capture with an additional confirmed answer and two approved mappings/profile alternatives.
- F-PROJ-001 missing scope and multi-context behavior.
- F-DATA-006 reparent head/revision mismatch.
- F-REC-001 repeated expired lease claims and recovery counter behavior.
- H-PIPE-001 two-session recovery replacement during finalization, including emitted SQL predicate evidence.
- F-AUTH-001 malformed projection/source-authority review rejection.
- Real upload-to-governed-base-to-preview journey only after a production target profile/governance UI exists; synthetic terminal-state seeding is not a substitute.

Each probe is its own chunk, persists exact source commit/hashes/input/output, and cannot be called a test-suite pass.

## Prohibited

- Existing database URLs, Oracle instances, Docker services, production-like services or cloud credentials without a new explicit approval.
- `pytest`, imports from tests/, test fixtures, hidden historical output, root `.env`, application root SQLite defaults or root evidence storage.
- Package installation, source/test edits, commits/pushes, deployment, or feature-flag activation.
- External OCR/AI transmission of supplied evidence.

## Approval Needed

Approve only if sandbox SQLite migration/service writes and standalone production-module probes are acceptable. Browser/server and any Oracle work should remain separate approvals. Until approval, S12-C02 through S12-C04 are BLOCKED and all report conclusions remain static/partial where runtime evidence is required.