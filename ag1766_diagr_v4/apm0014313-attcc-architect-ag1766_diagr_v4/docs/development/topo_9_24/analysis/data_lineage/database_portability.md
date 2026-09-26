# Persistence Portability and Migration Boundary

EV-DATA-004; S08-C03. Static inspection of portable type decorators, metadata naming, Alembic environment/configuration and Docker Compose. Prior migration/schema evidence is reused, not reread. No database connection, migration, container or application execution.

## Portable Storage Contracts

- `PortableUUID`: accepts UUID/string, stores canonical lowercase hyphenated text and returns UUID objects. ORM implementation is `String(36)` while migrations commonly declare `CHAR(36)`; runtime Oracle reflection/binding equivalence is not certified here.
- `PortableUTC`: rejects naive/non-datetime input, converts aware values to UTC ISO text and returns UTC-aware datetime. Physical storage is text, avoiding dialect timestamp differences.
- `PortableDecimal`: rejects floats and returns Decimal.
- `CanonicalJSON`: sorts keys and round-trips JSON through Text. It is deterministic for ordinary dict/list values but uses default separators and default `allow_nan=True`; it is not the stricter topology-contract canonical serializer.
- `Sha256Hex`: validates/normalizes lowercase 64-character hex on bind; result processing lowercases but does not independently validate stored corruption.
- Shared metadata naming is deterministic, with explicit short names used for constraints that could exceed Oracle's conservative identifier budget.

These decorators provide an application boundary, not database CHECK constraints. Direct SQL can bypass Python validation.

## Alembic Model Registration and Modes

- Alembic imports current topology, interface, resource and snapshot model modules into shared metadata, so those reviewed tables are visible to autogeneration.
- Offline mode requires a URL and emits SQL without a live connection; SQLite URLs enable batch rendering.
- Online mode uses NullPool, initializes optional Oracle Thick mode, and enables SQLite cross-thread connection args.
- The environment does not import full Settings, which avoids application startup/catalog publication. It does import dotenv and may load a working-directory `.env` under the condition below.
- The current Alembic config holds an empty URL placeholder and contains no credentials.

## F-OPS-001: Migration Target Can Be Loaded Implicitly From Working-Directory `.env`

- FACT / VERIFIED static; severity High operational risk.
- When neither AWS_OUTPOST_DATABASE_URL nor a programmatic Alembic URL is set, env.py calls `load_dotenv(Path.cwd() / ".env")`; `_get_url` then consumes the environment value.
- A developer invoking Alembic from a repository/client-evidence workspace can therefore target a database configured in that directory without an explicit URL on the command line or confirmation of environment/database identity.
- Impact: an ordinary migration command may mutate an unintended existing Oracle/SQLite database. This review deliberately avoided Alembic execution for that reason.
- Proposed change: require an explicit migration URL/environment acknowledgement for online mode, or require an explicit opt-in before dotenv loading. Print only redacted target classification and revision intent, never credentials. Production/shared targets should require a stronger deployment procedure than local defaults.
- Acceptance proposal: no URL fails before engine creation; isolated programmatic URL wins; dotenv is ignored unless explicitly opted in; redacted target/environment mismatch blocks; offline SQL remains available safely.

## F-DATA-007: SQLite Migration Connections Omit Application Integrity Pragmas

- FACT / VERIFIED static; severity Medium.
- Application engine creation registers SQLite `foreign_keys=ON`, WAL, synchronous and busy timeout. Alembic online mode creates a separate engine directly and sets only `check_same_thread=False`.
- SQLite foreign-key enforcement is connection-scoped and normally disabled by default. Migration/data-fix operations can therefore run without the same FK enforcement as application sessions; no post-migration `foreign_key_check` appears in env.py.
- Proposed change: configure the migration SQLite connection with the required integrity pragmas and perform/document a post-upgrade foreign-key check in controlled deployment tooling. Evaluate WAL/locking pragmas separately; migrations may require different journal behavior.
- Acceptance proposal: disposable migration connection reports FK enabled, invalid FK writes fail, and post-upgrade integrity returns no violations. No such runtime result is claimed here.

## F-OBS-002: Container Health Is Liveness, Not Readiness

- FACT / VERIFIED static; severity Medium.
- Docker Compose health calls `/health/live`, which intentionally checks only process/event-loop response. It does not check database, schema, storage or catalog.
- A container can therefore be marked healthy while `/health/ready` is degraded. Prior source evidence also found an undefined symbol in readiness, so changing the URL alone is not currently sufficient.
- Proposed change: first repair and independently validate readiness, then use readiness for orchestration health while retaining liveness for process restart semantics where the platform supports separate probes.
- Acceptance proposal: process alive but missing schema/storage/catalog is not ready; transient dependency failures do not cause inappropriate process restarts; responses remain redacted.

## Static Type/Canonical Risks

- `CanonicalJSON` allows non-finite float serialization by default and is not byte-compatible with the strict topology canonical serializer. Use strict contract serializers for authority/hash inputs and reject NaN/infinity at domain boundaries.
- Text-based JSON/time/UUID choices aid portability but do not add relational query constraints or native type validation.
- Model/migration use of String versus CHAR for UUID/hash needs actual Oracle reflection/binding evidence before being declared equivalent or defective.
- Docker Compose defaults to local SQLite volumes, mock AI mode and local development settings; those defaults are not production certification.
- Full model-registration coverage outside topology was not audited because this review is topology-scoped.

## Stage 08 Outcome

Schema declarations and lineage were mapped, with strong uniqueness/FK foundations and several missing authority/current-revision constraints. Portability is COMPLETE_WITH_LIMITATIONS: no deployed schema, Oracle behavior, SQLite migration pragmas or concurrency schedule was executed. A later authorized standalone environment must be disposable, explicit and independent of tests/.