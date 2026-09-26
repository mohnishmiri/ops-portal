# UI Questionnaire Architecture Decisions

**Date:** 2026-09-04
**Status:** proposed decisions; team confirmation required where marked OPEN

## Accepted design defaults

### ADR-UI-001 - Internal application UUID

**Decision:** Use a system-generated UUID text key for `applications.id`.
External IDs are typed child records.

**Reason:** iTAP ID, Correlation ID, MOTS ID, name, acronym, wave, and site have
different lifecycles and cannot all be a stable primary key.

### ADR-UI-002 - Separate state machines

**Decision:** Keep application, intake, section, answer value, answer review,
register, evidence, issue, job, and deliverable states separate.

**Reason:** A single status cannot represent partially approved sections,
stale evidence, open issues, and independently ready deliverables.

### ADR-UI-003 - Immutable catalog releases

**Decision:** Compile catalog CSV into an immutable release. An intake references
one release and does not silently change when a newer catalog is published.

**Reason:** Question text, conditions, response types, and output mappings are
part of the audit contract.

### ADR-UI-004 - Append-only revisions

**Decision:** Answer and register-row values use append-only revisions with a
current pointer. Approved intake snapshots are immutable.

**Reason:** Reviewers must know what changed, by whom, why, and against which
evidence.

### ADR-UI-005 - Evidence outside SQLite

**Decision:** Store file bytes in content-addressed filesystem storage and store
metadata/provenance in SQLite.

**Reason:** Large Office packages and diagrams do not belong in the database;
hash reuse also avoids duplicate storage.

### ADR-UI-006 - Server-rendered Python UI

**Decision:** Start with FastAPI, SQLAlchemy/Alembic, Jinja2, HTMX, and SQLite
WAL in one process.

**Reason:** This reuses the Python spike and fits the dense internal workflow
without introducing a separate SPA deployment.

### ADR-UI-007 - Generated artifacts use snapshots

**Decision:** Topology, ADS, and DDD generation consumes only an immutable
canonical intake snapshot.

**Reason:** Live-answer generation cannot provide reproducibility or meaningful
approval lineage.

### ADR-UI-008 - Portal tasks, not portal credentials

**Decision:** Human users access TSS/iTAP/SUD/PORT/DXC and upload/reference the
result. The application does not store portal credentials in v1.

**Reason:** This respects the stated human-in-the-loop workflow and avoids an
unapproved credential/security boundary.

## Open decisions

### OPEN-UI-001 - External identifier semantics

Confirm whether iTAP ID, Correlation ID, and MOTS ID are distinct fields or
aliases. Until confirmed, store them independently and prohibit duplicate typed
values globally.

### OPEN-UI-002 - Name and acronym uniqueness

Pilot default: case-insensitive global uniqueness for application name and
acronym. Confirm whether real enterprise data contains collisions or aliases.

### OPEN-UI-003 - Actor provisioning

Choose who can create applications and assign primary Application Owner and
Migration Application Architect roles.

### OPEN-UI-004 - Separation of duties

Define which section, risk, intake, and deliverable decisions prohibit
self-approval.

### OPEN-UI-005 - Evidence freshness

Define freshness periods per source: iTAP, TSS, SUD, PORT, DXC, Wave sizing,
Wave execution, and capacity baseline.

### OPEN-UI-006 - Pilot deployment

Confirm local workstation versus shared internal server, expected application
count, active users, and concurrent editors. This determines whether SQLite is
appropriate beyond development.

### OPEN-UI-007 - SSO

Identify the AT&T OIDC/SSO integration, required claims, group mappings, and
local-development fallback.

### OPEN-UI-008 - Artifact storage

Choose pilot filesystem root, backup location, retention, access controls, and
future enterprise repository/object-store integration.

### OPEN-UI-009 - Approval meaning

Confirm whether intake approval means facts are approved or only that the
snapshot is ready for deliverable generation. Default: ready for generation;
each deliverable is approved separately.

### OPEN-UI-010 - DDD contract

Supply the official DDD template/version and approver so the DDD readiness and
output mapping can be designed.

### OPEN-UI-011 - Catalog response schemas

Approve structured schemas for the six currently underspecified controls:
`CTL-001`, `CTL-002`, `APP-002`, `APP-004`, `WAV-005`, and `TGT-002`.

### OPEN-UI-012 - Catalog role vocabulary

Normalize `DBA|Security Architect` and all human labels into stable role codes.
Define primary, collaborator, and reviewer semantics.

### OPEN-UI-013 - Risk acceptance authority

Define who may accept Critical, High, Medium, and Low risks and whether review
expiry is mandatory per severity.

### OPEN-UI-014 - Notification channel

Choose in-app only, email, Teams, or another approved channel for assignments,
due dates, change requests, and approvals.
