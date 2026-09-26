# Migration Intake

AWS Outposts Migration Intake Application for managing application questionnaires, evidence collection, and migration readiness assessment.

## Status

**Development Phase:** Foundation scaffold (F01)

This is the production foundation for the Migration Intake application. Production code is being developed using TDD (Test-Driven Development).

### Topology generation stabilization status

Topology generation is in stabilization, not release or activation. A developer-led browser walkthrough of the real supported workflow (upload, governed capture, projection, rendering, finalization, inspection, and restart) is required before treating the feature as complete. UI testing must be paired with backend integration tests because the review found defects that a seeded or isolated UI test cannot expose.

The 2026-09-24 review confirmed corrective work is still required for lease/CAS fencing, recovery-attempt accounting, finalization failure transitions, review authority and projection-hash validation, unknown scope preservation, scoped renderer identities and prototype styles, partial artifact-link handling, and the upload-to-governed-base workflow. Focused topology and route tests pass, but those passes are not full certification. Official generation and approval remain disabled.

The next implementation slices should be small, executable regression tests first, followed by the corresponding fixes and a real end-to-end browser journey. After those tests exist, a bounded TLA+ model is appropriate for reservation, leases, finalization, recovery, duplicate requests, crashes, and approval-state invariants; Lean is not currently justified.

## Quick Start

### Prerequisites

- Python 3.12
- pip

### Installation

```bash
# Install with development dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Start development server
migration-intake
```

### Configuration

The application is configured via environment variables. For local development, create a `.env` file:

```bash
AWS_OUTPOST_APP_ENV=local
AWS_OUTPOST_EVIDENCE_ROOT=/path/to/evidence/storage
AWS_OUTPOST_ACTOR_ID=00000000-0000-0000-0000-000000000001
AWS_OUTPOST_ACTOR_DISPLAY_NAME="Development User"
AWS_OUTPOST_CSRF_SECRET=your-secret-at-least-32-characters-long
```

See `src/migration_intake/config.py` for all available settings.

## Development

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=migration_intake

# Run specific test categories
pytest -m unit
pytest -m web
```

### Code Quality

```bash
# Type checking
mypy src/migration_intake

# Linting
ruff check src/
```

## Project Structure

```
src/migration_intake/
├── __init__.py      # Package version
├── config.py        # Configuration settings
├── main.py          # FastAPI application factory
├── domain/          # Domain models and policies (future)
├── application/     # Application services (future)
├── catalog/         # Catalog compiler (future)
├── imports/         # Workbook importers (future)
├── persistence/     # Database repositories (future)
├── web/             # Web routes and templates (future)
└── observability/   # Logging and health (future)
```

## Documentation

- [STATE.md](STATE.md) - Current project state and next actions
- [AGENTS.md](AGENTS.md) - Agent/tool configuration rules
- [Developer setup](docs/development/DEVELOPER_SETUP.md) - Local environment and verification
- [Operations guide](docs/operations/README_DEPLOYMENT.md) - Deployment and runtime operations
- [Architecture plans](docs/architecture/) - Current topology and provider-integration designs
- [Production implementation plan](src/PRODUCTION_FOUNDATION_TDD_IMPLEMENTATION_PLAN.md)
- [Production architecture](src/PRODUCTION_FOUNDATION_ARCHITECTURE_AND_TECHNICAL_DESIGN.md)
