# Repository Stack and Operating Boundary

Evidence: EV-REPO-004. Chunk: S01-C01. Verification: static source/configuration inspection only. No environment, service, database, cloud, installation, or excluded test execution.

## Verified Declarations

| Dimension | Declaration | Source locator | Qualification |
| --- | --- | --- | --- |
| Application | migration-intake 0.1.0, AWS Outposts intake application | pyproject.toml `[project]` | Name/version declarations, not deployed inventory |
| Python | >=3.13,<3.14; mypy python_version=3.13 | pyproject.toml `requires-python`, `[tool.mypy]` | Selected local interpreter not queried |
| Packaging | Hatchling; wheel packages src/migration_intake | pyproject.toml `[build-system]`, wheel target | Long force-include line was display-truncated; complete packaged-profile inventory not verified here |
| HTTP | FastAPI >=0.115,<1.0; Uvicorn >=0.30,<1.0 | pyproject.toml dependencies | Declared ranges, not resolved installed versions |
| Validation/configuration | Pydantic 2, pydantic-settings 2, python-dotenv | pyproject.toml dependencies | Active settings precedence needs production-source inspection |
| Views | Jinja2 >=3.1.4,<4.0 | pyproject.toml dependencies | Actual topology templates/routes traced in subsequent chunks |
| Persistence | SQLAlchemy 2 and Alembic >=1.13,<2.0 | pyproject.toml dependencies | Active database URL and schema head are not inspected or assumed |
| Oracle | python-oracledb >=2.2,<3.0; Instant Client in runtime image | pyproject.toml; Dockerfile Oracle build block | No connection made; SQLite/Oracle behavior requires later source mapping |
| Workbook processing | openpyxl >=3.1.2,<4.0 | pyproject.toml dependencies | Does not establish which workbook is authoritative |
| CLI entry | migration-intake -> migration_intake.main:run | pyproject.toml `[project.scripts]` | Configuration of run() requires later inspection |
| Container entry | python -m uvicorn migration_intake.main:get_app --factory, port 8000 | Dockerfile ENTRYPOINT/CMD | Factory code not read in this chunk |
| Container Python | Builder/runtime images declare 3.13.15 | Dockerfile FROM | No image pull/build; image availability unverified |
| Container identity | USER 1000:1000; evidence directory owned by app | Dockerfile USER and evidence directory block | Declarative isolation only |
| Build secrets | Package index/host read via BuildKit secret mounts | Dockerfile pip install RUN | No secret values accessed |
| Health check | HTTP GET /health/live | Dockerfile HEALTHCHECK | Endpoint behavior not executed |
| Static quality | mypy strict; Ruff rules; source-scoped full commands | pyproject.toml; Makefile | No full lint/type-check run in this chunk |

The Python dependency list does not declare an AWS discovery SDK, graph database, or queue engine. This is evidence about this manifest only, not proof of repository-wide absence or a requirement to add them.

## Product Boundary

- AGENTS.md `Product invariants`: evidence readers/importers/AI produce candidates, never approved facts; missing values stay unknown; scope/provenance and conflicts remain explicit.
- Reviewed canonical snapshots are the production consumer boundary. No live-answer official generation, invented values, or silent evidence conflict resolution is permitted.
- Source inspection must determine the implemented distinction between non-authoritative preview capture and approved official authority; documentation alone does not prove enforcement.
- Existing dirty work is preserved. tests/ and to_archive/ remain excluded even where these documents mention them.

## Declared Commands, Not Executed

| Purpose | Declared command | Permission/meaning |
| --- | --- | --- |
| Install | pip install -e ".[dev]" | Not authorized or executed for this review |
| Local entry | migration-intake | No service started |
| Full source lint | python -m ruff check src/ | Declared source-only gate; not observed passing |
| Full source types | python -m mypy src/migration_intake | Declared gate; not observed passing |
| Changed-source types | Makefile typecheck uses changed application Python files | Not equivalent to a full-project gate |
| Aggregate Make targets | verify/preflight/check include installation and excluded-suite execution | Do not invoke under current review scope |

Makefile's default lint target also includes paths in the excluded suite. It must not be invoked unchanged. References to testing frameworks/configuration are not used as evidence of coverage, correctness, or test results.

## Current Findings

- F-DOC-001, FACT / VERIFIED, Low: README `Prerequisites` says Python 3.12, while package requirements reject Python outside 3.13. This can give a developer an unusable installation prerequisite. Proposed correction: align setup guidance with the package/runtime contract after confirming intended support. No source behavior changed.
- F-DOC-002, FACT / VERIFIED, Low: Ruff targets py312 while package and mypy target 3.13. The configuration is inconsistent; a runtime defect is not proven. Proposed correction: explicitly ratify/update the lint target with source-only validation in an authorized implementation slice.
- README still labels the overall application a foundation scaffold and several application layers as future. Determine actual layer implementation in S01-C02 before classifying this as stale documentation.

## Remaining Work

- Identify production topology entry points and controlling abstractions.
- Determine actual UI libraries and rendering contracts from source, not manifest assumptions.
- Inspect production settings and persistence boundaries without reading .env or connection strings.
- Treat deployment availability, installed versions, CI outcomes, graph performance, and existing-test coverage as unverified or out of scope.