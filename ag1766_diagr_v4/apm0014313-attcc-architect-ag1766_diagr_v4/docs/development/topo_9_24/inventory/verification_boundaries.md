# Production Verification Boundaries

Evidence: EV-REPO-006 and EV-DIAG-001. Chunk S01-C03. Five production files inspected; no tests/, to_archive/, .env, credentials, database connection, application import, or service execution.

## Configuration and Startup

- config.py `Settings.__init__` and `model_config`: ordinary construction may load .env; `_env_file=None` explicitly disables it. APP_ENV/AWS_OUTPOST_APP_ENV equal to test also disables default dotenv loading. These are source facts, not the actual process environment.
- Settings fields use prefixed and unprefixed validation aliases. A standalone probe must provide explicit synthetic values and isolate inherited aliases; never assume a terminal's unprefixed override controls all inputs.
- `topology_generation_enabled` defaults False. Its actual route coverage is checked in S02, not inferred from the field alone.
- `llm_enabled` defaults False and provider defaults mock. Additional provider validation exists; do not infer permission for external calls from configuration support.
- `effective_database_url` defaults to a local relative SQLite file only for local/test with no explicit URL. Thus executing ordinary Settings/create_app from repository root is not an isolated read-only operation.
- `validate_environment_constraints` requires a nonempty non-SQLite URL for shared_test/production. The message says Oracle; the checked predicate alone is not full dialect validation.
- main.py `create_app` constructs settings when absent, configures logging/optional Oracle client, creates an engine/session factory, and registers the topology router. `get_app` caches the application instance.
- The lifespan invokes `ensure_catalog_published(session_factory)`. Its implementation was not inspected in this chunk; regard startup as potentially database-mutating until that contract is examined or a disposable boundary is approved.
- Static assets are mounted locally. This is not evidence of a particular interactive graph library.

## Database and Health Semantics

- persistence/database.py `create_engine_from_url` registers SQLite connection pragmas: foreign keys ON, WAL, NORMAL synchronous mode, and a 5-second busy timeout. Even a connection can alter operational database settings.
- `create_session_factory` disables autoflush/autocommit and expires objects on commit. This does not prove every service observes the transaction policy.
- `configure_oracle_client` can initialize Thick mode when configured. Do not invoke it against inherited client/connection settings for review.
- `check_schema_current` reads alembic_version and compares repository migration heads; it does not run migrations. Actual schema state remains unknown.
- web/health.py `liveness` returns an OK response without external checks.
- `readiness` connects for a scalar query, checks schema and catalog, and creates/writes/deletes a temporary file in evidence storage. It is unsuitable as a read-only probe of an existing service/storage environment.
- Readiness responses contain booleans rather than raw connection/path errors. Internal broad exception handling can conceal programming defects as dependency failures.

## F-OBS-001: Readiness Uses an Undefined Symbol

- Kind: FACT; verification: VERIFIED static; severity: High for operational readiness, subject to runtime confirmation in an approved environment.
- Source: src/migration_intake/web/health.py line 37 imports `func, select, text`; line 91 calls `conn.scalar(select(literal(1)))`.
- Pylance: reportUndefinedVariable, line 91, message `"literal" is not defined`. See EV-DIAG-001.
- Current code has no import/definition for literal. The connectivity try/except catches exceptions and sets the database check false.
- Expected impact (INFERENCE): even when engine.connect succeeds, evaluating the query raises NameError and the route reports degraded/503. No runtime request was made to demonstrate the HTTP result.
- Proposed smallest correction in an authorized implementation slice: import the intended SQLAlchemy expression constructor and verify dialect-compatible connectivity plus degraded/healthy readiness behavior using independent synthetic validation. Do not use this review to resolve the source defect.
- Alternative: replace the query with another dialect-portable SQLAlchemy construct; it is a larger change and unnecessary if the intended import is the only defect.
- Schema/API impact: no schema or response-shape change expected; visible readiness result corrected. Rollback: revert only the approved import/query correction, never user merge work.
- Acceptance: no undefined-symbol diagnostic; controlled healthy database/schema/storage/catalog returns ready, and explicit dependency failures remain degraded. These checks are proposed, not executed.

## Logging Observations

- observability/logging.py declares URL credential redaction, UUID correlation validation, stable event codes, and a StructuredLogger with bounded field names for operation/outcome/identity/duration/count/exception class.
- Only the first 210 lines were inspected; logger emit methods and topology call-site adoption remain unverified.
- No dedicated topology run/stage field or topology event code appears in the inspected section. This is a scoped observation, not proof that topology observability is absent elsewhere.
- The Pylance response also reports unresolved SQLAlchemy in editor analysis. pyproject.toml declares SQLAlchemy; do not label this a missing project dependency or runtime import failure without checking the selected analysis environment.

## Safe Next Work

- Continue source and reference-document inspection without starting the application.
- Any proposed runtime environment must disable dotenv/inherited endpoints, use explicit synthetic data and workspace-owned disposable storage, avoid excluded fixtures, and require permission for database/service activity.
- Stage 01 is complete as a bounded inventory. Topology behavior, schema lineage, diagram semantics, and actual UI states remain for the following chunks.