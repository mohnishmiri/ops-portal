# Architecture Review Integration Analysis
## Topology Generation Design (2026-09-14) — Codebase Mapping

**Date:** 2026-09-14  
**Scope:** Detailed mapping of design findings and recommendations to current codebase implementation  
**Status:** Ready for implementation planning

---

## Executive Summary

The design review identifies **3 critical gaps** and **6 high-priority gaps** that must be closed before topology generation can be safely implemented. The current codebase has **strong foundations** in place (answer service, snapshot serialization, readiness checks) but **three critical paths are incomplete**:

1. **Snapshot answers are empty** — `_build_canonical_answers()` returns `[]`
2. **Confirmation route is a stub** — no call to `AnswerService.confirm_answer()`
3. **Readiness is intake-grade, not topology-grade** — missing topology-specific checks

**Good news:** The answer service (`AnswerService.confirm_answer()` and `mark_not_applicable()`) is **fully implemented and tested**. The routes just need to wire them up.

---

## Critical Finding 1: Empty Canonical Answers

### Current State

**File:** `src/migration_intake/application/services/snapshots.py:238–247`

```python
def _build_canonical_answers(
    self,
    answer_repo: AnswerRepository,
    application_id: str,
    intake_id: str,
) -> list[CanonicalAnswer]:
    """Build canonical answers for the payload."""
    # Get all confirmed answers for this intake
    # For now, return empty list - full implementation would query answers
    return []
```

**Impact:** The frozen snapshot contains no questionnaire answers. Topology generation cannot proceed without confirmed values in the snapshot.

### What Needs to Happen

The method must:
1. Query all answer instances for the intake
2. Load the current revision for each instance
3. Filter to **confirmed answers only** (and explicit `NOT_APPLICABLE` decisions)
4. Exclude `DRAFT`, `CLEARED`, and unreviewed answers
5. Build `CanonicalAnswer` objects with:
   - `question_id`, `question_code`, `section_code`, `response_type`
   - `value_json` (the confirmed response payload)
   - `review_state` (`CONFIRMED` or `NOT_APPLICABLE`)
   - `revision_number` (from the confirmed revision)
   - `provenance_references` (evidence links from `answer_evidence_links` table)

### Implementation Path

**Location:** `src/migration_intake/application/services/snapshots.py`

**Pseudo-code:**
```
1. Call answer_repo.list_instances(intake_id)
2. For each instance:
   a. Get current_revision via answer_repo.get_current_revision(instance_id)
   b. If confirm_state != "CONFIRMED" and confirm_state != "NOT_APPLICABLE": skip
   c. Load question metadata from catalog (section_code, response_type)
   d. Query answer_evidence_links for this revision_id → provenance_references
   e. Build CanonicalAnswer(...)
3. Return sorted list by (section_code, question_code)
```

**Tests Required:**
- Accepted candidate becomes a canonical answer revision
- Confirmed revision appears in the frozen snapshot
- Candidate-only and draft/unconfirmed values do NOT appear
- Evidence provenance survives confirmation
- Editing after freeze cannot alter the stored snapshot

**Verification:** Run `python -m pytest tests/unit/application/test_snapshots.py -v` after implementation

---

## Critical Finding 2: Confirmation Route is a Stub

### Current State

**File:** `src/migration_intake/web/routes/questionnaire.py:468–495`

```python
@router.post(
    "/applications/{app_id}/intakes/{intake_id}/questions/{question_code}/confirm",
)
async def confirm_answer(
    request: Request,
    app_id: str,
    intake_id: str,
    question_code: str,
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
) -> RedirectResponse:
    """
    Confirm an answer for a question.

    TODO: Implement confirm logic in answer service.
    """
    # Validate CSRF
    if not validate_csrf_token(csrf_token, request.app.state.settings.csrf_secret):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid CSRF token",
        )

    # TODO: Implement confirm in answer service

    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/questionnaire",
        status_code=status.HTTP_303_SEE_OTHER,
    )
```

**Impact:** Users cannot confirm answers through the UI. The questionnaire-to-snapshot workflow is broken.

### What Needs to Happen

The route must:
1. Extract `ActorContext` from the request (user ID, display name)
2. Call `AnswerService.confirm_answer(intake_id, question_code, actor, rationale="")`
3. Handle errors:
   - `NoCurrentRevisionError` → 400 (no answer to confirm)
   - `IntakeNotOpenError` → 409 (intake frozen or closed)
   - `QuestionNotFoundError` → 404
4. On success, redirect back to questionnaire
5. On error, render error page or flash message

### Implementation Path

**Location:** `src/migration_intake/web/routes/questionnaire.py:468–495`

**Pattern to follow:** See `save_answer()` route at line ~400 for the established pattern

**Code sketch:**
```python
@router.post(
    "/applications/{app_id}/intakes/{intake_id}/questions/{question_code}/confirm",
)
async def confirm_answer(
    request: Request,
    app_id: str,
    intake_id: str,
    question_code: str,
    csrf_token: Annotated[str, Form(alias="_csrf_token")],
) -> RedirectResponse:
    """Confirm an answer for a question."""
    if not validate_csrf_token(csrf_token, request.app.state.settings.csrf_secret):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")

    actor = ActorContext(
        actor_id=str(request.user.id),
        display_name=request.user.display_name,
    )
    
    answer_service = get_answer_service(request)
    try:
        answer_service.confirm_answer(intake_id, question_code, actor)
    except (NoCurrentRevisionError, IntakeNotOpenError, QuestionNotFoundError) as e:
        # Handle error — render error page or flash message
        raise HTTPException(status_code=400, detail=str(e))

    return RedirectResponse(
        url=f"/applications/{app_id}/intakes/{intake_id}/questionnaire",
        status_code=303,
    )
```

**Tests Required:**
- Confirm route calls `AnswerService.confirm_answer()`
- Confirmed revision appears in snapshot after freeze
- CSRF validation blocks invalid tokens
- Error handling for missing/frozen intakes

**Verification:** `python -m pytest tests/web/test_questionnaire_routes.py::test_confirm_answer -v`

---

## Critical Finding 3: Freeze Readiness ≠ Topology Readiness

### Current State

**File:** `src/migration_intake/application/services/readiness.py:80–100+`

The `ReadinessService.check_readiness()` method checks:
- Intake state
- Proposed candidates
- Deferred candidates
- Snapshot existence
- WaveUtil presence

**Impact:** An intake can be frozen with incomplete topology inputs. The snapshot may lack required values for diagram generation.

### What Needs to Happen

**Two separate readiness concepts:**

1. **Intake Freeze Readiness** (current) — can the intake be frozen?
   - Basic completeness checks
   - Candidate review status
   - No unresolved conflicts

2. **Topology Readiness** (new) — can topology be generated?
   - All required topology answers are confirmed
   - Base diagram is compatible and approved
   - Renderer configuration is pinned
   - No unsupported response schemas
   - Scope (environment, site, account) is explicit and valid

### Implementation Path

**New file:** `src/migration_intake/application/services/topology_readiness.py`

**Class:** `TopologyReadinessService`

**Method:** `check_topology_readiness(intake_id: str, base_diagram_id: str) -> TopologyReadinessResult`

**Dimensions to check:**
```
NOT_READY
  ├─ Missing required topology inputs (region, VPC, subnet, etc.)
  ├─ Unsupported response schemas in snapshot
  ├─ Ambiguous scope (environment/site/account)
  ├─ Base diagram invalid or incompatible
  └─ Configuration drift

READY_TO_GENERATE
  ├─ All required inputs confirmed
  ├─ Base diagram valid and approved
  ├─ Configuration pinned and compatible
  └─ Scope unambiguous

GENERATED_WITH_GAPS
  ├─ Output exists
  └─ Explicitly permitted gaps documented

READY_FOR_REVIEW
  ├─ Output exists
  └─ Awaits architect approval

APPROVED
  ├─ Architect approved exact run
  └─ Supersession references tracked

SUPERSEDED
  └─ Later snapshot/base/config replaces it
```

**Minimum required topology inputs** (from design section "Required Canonical Inputs"):
- Application acronym and correlation identity
- Target environment and site
- AWS region and Outpost logical ID
- Target account identifier
- VPC and subnet identifiers
- Workload subnet CIDR
- Security group, VM, and ENI identifiers
- Explicit topology variant decision

**Tests Required:**
- Intake can freeze without topology readiness
- Topology readiness fails if required answers missing
- Topology readiness fails if response schema unsupported
- Topology readiness passes when all inputs confirmed

---

## High Priority Finding 4: Candidate vs. Confirmation Contract

### Current State

**File:** `src/migration_intake/application/services/candidates.py`

The candidate acceptance flow:
1. Candidate in `PROPOSED` state
2. User accepts → candidate moves to `ACCEPTED`
3. `AnswerService` creates a canonical answer revision

**Issue:** The design requires a clear distinction:
- **Acceptance** = adopt proposed value as an answer revision (may be edited)
- **Confirmation** = approve exact revision for snapshot (immutable)

### What Needs to Happen

The current implementation is **correct**. The design is clarifying the terminology:
- Accepted candidates become answer revisions (editable)
- Confirmed revisions are immutable and appear in snapshots
- The snapshot boundary is confirmed revisions, not accepted candidates

**No code change required** — this is a clarification of existing behavior.

**Tests Required:**
- Accepted candidate creates answer revision with `confirm_state=DRAFT`
- Confirmed revision has `confirm_state=CONFIRMED`
- Only confirmed revisions appear in snapshot
- Editing after confirmation creates new revision (not overwrite)

---

## High Priority Finding 5: Confirmation Provenance

### Current State

**File:** `src/migration_intake/application/services/answers.py:409–464`

The `confirm_answer()` method:
1. Loads current revision
2. Creates new revision with `confirm_state=CONFIRMED`
3. Copies `response_json` from current revision
4. **Does NOT copy evidence links**

**Issue:** Evidence provenance is lost when confirming. The confirmed revision has no link to source evidence.

### What Needs to Happen

When confirming an answer:
1. Load current revision's evidence links via `answer_evidence_links` table
2. Copy evidence links to the new confirmed revision
3. Preserve source locator, record ID, retrieval time, collector

**Implementation Path**

**File:** `src/migration_intake/application/services/answers.py:444–450`

After creating the confirmed revision, copy evidence links:

```python
# Get evidence links from current revision
evidence_links = uow.answers.get_evidence_links(current["revision_id"])

# Copy to confirmed revision
for link in evidence_links:
    uow.answers.add_evidence_link(
        revision_id=revision_id,  # new confirmed revision
        evidence_id=link["evidence_id"],
        source_locator=link["source_locator"],
        record_id=link["record_id"],
        retrieval_time=link["retrieval_time"],
        collector=link["collector"],
    )
```

**Tests Required:**
- Evidence links survive confirmation
- Confirmed revision is traceable to source evidence
- Editing after confirmation preserves provenance of previous revision

---

## High Priority Finding 6: Questionnaire Status ≠ Topology Facts

### Current State

The questionnaire contains status fields like:
- `REGISTER_STATUS=COMPLETE`
- `IMPORT_STATUS=PROCESSED`

**Issue:** These are review-progress indicators, not topology facts. The adapter cannot render a diagram from status codes.

### What Needs to Happen

The topology adapter must:
1. Reject unknown question codes
2. Require typed, scoped values (not status strings)
3. Validate response schemas are supported
4. Fail closed for ambiguous scope or invalid values

**Implementation Path**

**New file:** `src/migration_intake/topology/adapter.py`

**Class:** `SnapshotToTopologyAdapter`

**Method:** `adapt(snapshot_id: str, snapshot_json: str, snapshot_sha256: str) -> TopologyFacts`

**Contract:**
```python
def adapt(
    self,
    snapshot_id: str,
    snapshot_json: str,
    snapshot_sha256: str,
    base_diagram_artifact_id: str,
    base_diagram_sha256: str,
    renderer_configuration_release: str,
    renderer_configuration_sha256: str,
) -> TopologyAdapterResult:
    """
    Adapt a frozen snapshot to topology facts.
    
    Returns:
    - typed_scoped_topology_facts
    - render_tokens
    - readiness_result
    - issue_references
    - provenance_references
    
    Fails closed for:
    - Unknown question codes
    - Unsupported response schemas
    - Ambiguous scope
    - Invalid values
    - Configuration drift
    """
```

**Tests Required:**
- Adapter rejects unknown question codes
- Adapter validates response schemas
- Adapter fails for ambiguous scope
- Adapter produces render tokens for supported questions
- Adapter preserves provenance references

---

## High Priority Finding 7: Interface Data Not in Snapshot

### Current State

**File:** `src/migration_intake/application/services/snapshots.py:249–273`

The snapshot includes WaveUtil rows but **not interface register data**.

**Issue:** Interface imports create candidates, but the canonical snapshot contains no reviewed interface register. The first value-only renderer can defer interface-driven structural rendering.

### What Needs to Happen

**For the first release (value-only renderer):**
- Do NOT add interface register to snapshot yet
- Focus on questionnaire answers only
- Document that interface coverage is deferred

**For future releases:**
- Add interface register facts to snapshot
- Include interface-to-topology mappings
- Validate required interface data before generation

**No code change required for M1** — this is a scope clarification.

---

## High Priority Finding 8: Generation Persistence Not Implemented

### Current State

**Files:**
- `src/migration_intake/persistence/models.py` — no `GenerationRun` or `GeneratedArtifact` ORM models
- No Alembic migration for generation tables
- No repository for generation records
- No service for persisting runs

**Issue:** Generation runs and artifacts exist in the design but not in the ORM.

### What Needs to Happen

**New ORM models:**

```python
class GenerationRun(Base):
    """Immutable record of a topology generation run."""
    __tablename__ = "gen_runs"
    
    id: str  # UUID
    application_id: str  # FK
    intake_id: str  # FK
    snapshot_id: str  # FK
    snapshot_sha256: str  # Pinned hash
    base_diagram_artifact_id: str  # FK
    base_diagram_sha256: str  # Pinned hash
    renderer_config_release: str  # Version
    renderer_config_sha256: str  # Pinned hash
    generator_version: str
    state: str  # PENDING, RUNNING, SUCCESS, FAILED, SUPERSEDED
    requested_by_id: str  # FK to Actor
    requested_at: datetime
    completed_at: datetime | None
    readiness_result_json: dict  # TopologyReadinessResult
    issue_summary_json: dict  # Blocking issues
    approval_state: str  # PENDING, APPROVED, REJECTED, SUPERSEDED
    approved_by_id: str | None  # FK to Actor
    approved_at: datetime | None
    approval_rationale: str | None
    superseded_by_id: str | None  # FK to GenerationRun

class GeneratedArtifact(Base):
    """Immutable artifact from a generation run."""
    __tablename__ = "gen_artifacts"
    
    id: str  # UUID
    generation_run_id: str  # FK
    artifact_type: str  # "DIAGRAM" or "GAP_REPORT"
    filename: str
    mime_type: str
    size_bytes: int
    sha256_hex: str
    content_address: str  # Filesystem path or S3 key
    created_at: datetime
```

**New Alembic migration:**
- Create `gen_runs` table
- Create `gen_artifacts` table
- Add foreign keys to `applications`, `intakes`, `snapshots`, `evidence`

**New repository:**
- `GenerationRepository` with CRUD and state transitions

**New service:**
- `GenerationService` with `create_run()`, `complete_run()`, `approve_run()`

**Tests Required:**
- Generation run is immutable
- Artifacts are paired and hashed
- Approval references exact run
- Supersession links are transitive

---

## High Priority Finding 9: Base Diagram Labels Can Be Stale

### Current State

The renderer preserves unbound labels and selected suffixes from the base diagram.

**Issue:** XML validity alone is not enough. The base diagram must be reviewed for retained application-specific content, scope, environment, and variant.

### What Needs to Happen

**Base diagram metadata:**
1. Link to application and intake
2. Record environment, site, and variant scope
3. Validate uncompressed `mxfile` XML before acceptance
4. Validate required semantic slot cardinality before generation
5. Store content SHA-256, original filename, uploader, upload time, review state
6. Pin exact base artifact ID and hash to each generation run
7. Keep prior versions immutable
8. Review retained labels and suffixes for stale or out-of-scope values

**Implementation Path**

**New ORM model:**

```python
class TopologyBaseArtifact(Base):
    """Approved base diagram for topology generation."""
    __tablename__ = "topo_base"
    
    id: str  # UUID
    application_id: str  # FK
    intake_id: str  # FK
    environment: str  # e.g., "PROD", "DEV"
    site: str  # e.g., "US-EAST-1"
    variant: str  # e.g., "DEFAULT", "HA"
    filename: str
    mime_type: str  # "application/vnd.jgraph.mxfile"
    size_bytes: int
    sha256_hex: str
    content_address: str  # Filesystem path
    uploaded_by_id: str  # FK to Actor
    uploaded_at: datetime
    review_state: str  # DRAFT, APPROVED, DEPRECATED
    approved_by_id: str | None  # FK to Actor
    approved_at: datetime | None
    approval_notes: str | None
    created_at: datetime
```

**Validation:**
- Parse XML defensively
- Reject compressed XML
- Validate required slot cardinality
- Check for stale labels

**Tests Required:**
- Base diagram is immutable
- Prior versions are retained
- Approval is recorded with actor and timestamp
- Invalid XML is rejected

---

## Summary: Implementation Roadmap

### Slice 1: Repair the Canonical Boundary (Critical)

**Goal:** Prove that a reviewed questionnaire value survives import/UI review, confirmation, freeze, and snapshot export with expected value, revision, and provenance.

**Tasks:**
1. Implement `SnapshotService._build_canonical_answers()` ✓ (location identified)
2. Wire confirmation route to `AnswerService.confirm_answer()` ✓ (location identified)
3. Wire not-applicable route to `AnswerService.mark_not_applicable()` ✓ (location identified)
4. Copy evidence links during confirmation ✓ (location identified)
5. Add snapshot tests with real synthetic accepted and confirmed answers

**Files to modify:**
- `src/migration_intake/application/services/snapshots.py` (lines 238–247)
- `src/migration_intake/web/routes/questionnaire.py` (lines 468–495, 503–529)
- `src/migration_intake/application/services/answers.py` (lines 444–450)

**Verification:**
```bash
python -m pytest tests/unit/application/test_snapshots.py -v
python -m pytest tests/web/test_questionnaire_routes.py -v
python -m pytest tests/integration/web/test_questionnaire_routes.py -v
```

### Slice 2: Prove One Topology Mapping (High)

**Goal:** One synthetic frozen snapshot produces a deterministic diagram and report without reading raw source files.

**Tasks:**
1. Create `TopologyReadinessService` (new file)
2. Define topology-specific readiness dimensions
3. Implement pure snapshot adapter
4. Reuse spike's deterministic draw.io mutation logic
5. Add topology-specific tests

**Files to create:**
- `src/migration_intake/application/services/topology_readiness.py`
- `src/migration_intake/topology/adapter.py`
- `src/migration_intake/topology/__init__.py`

**Tests to create:**
- `tests/unit/application/test_topology_readiness.py`
- `tests/unit/topology/test_adapter.py`

### Slice 3: Persist and Review Runs (High)

**Goal:** An architect can review and approve one exact generated run, and a changed input cannot mutate it.

**Tasks:**
1. Add ORM models for `GenerationRun` and `GeneratedArtifact`
2. Create Alembic migration
3. Implement `GenerationRepository`
4. Implement `GenerationService`
5. Add routes for download and approval
6. Add immutable supersession links

**Files to create:**
- `src/migration_intake/persistence/models.py` (add models)
- `src/migration_intake/persistence/repositories/generations.py`
- `src/migration_intake/application/services/generations.py`
- `src/migration_intake/web/routes/topology.py`
- Alembic migration file

### Slice 4: Expand Coverage (Future)

Only after Slice 1–3 work:
- Add interface register facts
- Add additional diagram variants
- Add richer gap rules
- Add asynchronous execution
- Add external artifact storage

---

## Critical Path Dependencies

```
Slice 1: Canonical Boundary
  ├─ _build_canonical_answers() [CRITICAL]
  ├─ confirm_answer route [CRITICAL]
  ├─ mark_not_applicable route [CRITICAL]
  └─ evidence link preservation [HIGH]
        ↓
Slice 2: Topology Mapping
  ├─ TopologyReadinessService [HIGH]
  ├─ SnapshotToTopologyAdapter [HIGH]
  └─ Deterministic renderer [HIGH]
        ↓
Slice 3: Persistence
  ├─ GenerationRun ORM [HIGH]
  ├─ GeneratedArtifact ORM [HIGH]
  ├─ GenerationService [HIGH]
  └─ Approval routes [HIGH]
```

---

## Testing Strategy

### Unit Tests (Slice 1)

**File:** `tests/unit/application/test_snapshots.py`

```python
def test_canonical_answers_includes_confirmed_revisions():
    """Confirmed answers appear in snapshot."""
    
def test_canonical_answers_excludes_draft_revisions():
    """Draft answers do not appear in snapshot."""
    
def test_canonical_answers_includes_not_applicable():
    """NOT_APPLICABLE decisions appear in snapshot."""
    
def test_canonical_answers_preserves_provenance():
    """Evidence links survive confirmation."""
    
def test_canonical_answers_deterministic_ordering():
    """Answers are sorted by (section_code, question_code)."""
```

### Integration Tests (Slice 1)

**File:** `tests/integration/web/test_questionnaire_routes.py`

```python
def test_confirm_answer_route_calls_service():
    """POST /confirm calls AnswerService.confirm_answer()."""
    
def test_confirm_answer_appears_in_snapshot():
    """Confirmed answer appears in frozen snapshot."""
    
def test_not_applicable_route_calls_service():
    """POST /not-applicable calls AnswerService.mark_not_applicable()."""
    
def test_not_applicable_appears_in_snapshot():
    """NOT_APPLICABLE decision appears in frozen snapshot."""
```

### Browser Tests (Slice 1)

**File:** `tests/browser/test_confirmation_journey.py`

```python
def test_user_can_confirm_answer():
    """User fills, saves, and confirms answer through UI."""
    
def test_confirmed_answer_survives_freeze():
    """Confirmed answer persists through freeze."""
    
def test_snapshot_contains_confirmed_value():
    """Frozen snapshot includes confirmed answer."""
```

---

## Verification Checklist

### Before Slice 1 is Complete

- [ ] `_build_canonical_answers()` returns non-empty list for confirmed answers
- [ ] Confirmation route calls `AnswerService.confirm_answer()`
- [ ] Not-applicable route calls `AnswerService.mark_not_applicable()`
- [ ] Evidence links are copied to confirmed revision
- [ ] Snapshot tests pass with real synthetic data
- [ ] Browser journey test passes end-to-end
- [ ] All 1853+ existing tests still pass
- [ ] Type check passes: `python -m mypy src/migration_intake`
- [ ] Lint passes: `python -m ruff check src/`

### Before Slice 2 is Complete

- [ ] `TopologyReadinessService` correctly identifies missing inputs
- [ ] Adapter rejects unknown question codes
- [ ] Adapter validates response schemas
- [ ] Adapter produces render tokens for supported questions
- [ ] Deterministic generation produces byte-identical artifacts
- [ ] All tests pass

### Before Slice 3 is Complete

- [ ] Generation runs are immutable
- [ ] Artifacts are paired and hashed
- [ ] Approval references exact run
- [ ] Supersession links are transitive
- [ ] All tests pass

---

## Risk Assessment

### Low Risk (Slice 1)

- **Answer service is fully implemented** — routes just need to wire it up
- **Snapshot serialization is proven** — just need to populate answers
- **Evidence links are already tracked** — just need to copy them

### Medium Risk (Slice 2)

- **Adapter is new code** — needs careful design and testing
- **Topology readiness is new concept** — requires clear dimension definitions
- **Renderer integration is complex** — depends on spike's draw.io logic

### Medium Risk (Slice 3)

- **ORM models are new** — requires Alembic migration
- **Generation service is new** — requires careful state management
- **Approval workflow is new** — requires clear authorization rules

---

## Success Criteria

**Slice 1 complete when:**
- A reviewed questionnaire value reaches the frozen snapshot unchanged
- Revision number and provenance are intact
- Confirmation route is wired and tested
- All existing tests still pass

**Slice 2 complete when:**
- One synthetic frozen snapshot produces a deterministic diagram
- Gap report is generated without reading raw source files
- Topology readiness correctly identifies blocking issues

**Slice 3 complete when:**
- An architect can review and approve one exact generated run
- A changed input creates a new run (does not mutate existing)
- Supersession links are tracked and immutable

---

## Next Steps

1. **Review this analysis** with the team
2. **Prioritize Slice 1** for immediate implementation
3. **Create detailed task tickets** for each file modification
4. **Assign ownership** and estimate effort
5. **Begin with `_build_canonical_answers()`** — smallest, highest-impact change
6. **Wire confirmation routes** — already implemented, just needs integration
7. **Add tests** — verify end-to-end journey
8. **Plan Slice 2** after Slice 1 is verified

---

## References

- **Design Document:** `ARCHITECTURE_REVIEW_TOPOLOGY_GENERATION_2026-09-14.md`
- **Project Rules:** `AGENTS.md`
- **Project State:** `STATE.md`
- **Answer Service:** `src/migration_intake/application/services/answers.py`
- **Snapshot Service:** `src/migration_intake/application/services/snapshots.py`
- **Questionnaire Routes:** `src/migration_intake/web/routes/questionnaire.py`
- **Readiness Service:** `src/migration_intake/application/services/readiness.py`

