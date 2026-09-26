# Catalog Automation and Admin Editing — Implementation Plan and Parallel-Agent Execution Guide

**Version:** 0.1
**Created:** 2026-09-10
**Author:** Architect brainstorm session, verified against the current source tree at commit `ac4adf8` on `ag1766_diagr_v4`
**Implementation root:** `src/migration_intake`
**Architecture source:** `src/PRODUCTION_FOUNDATION_ARCHITECTURE_AND_TECHNICAL_DESIGN.md` (rules on catalog immutability, sections 23–30)
**Related handoff:** `to_archive/handoff_9_10.md` (historical capability-wiring analysis)

> This plan follows the same execution convention as `src/PRODUCTION_FOUNDATION_TDD_IMPLEMENTATION_PLAN.md`: packets have explicit file ownership so multiple agents can work concurrently without merge collisions. An agent should read this document's own "Read scope" line for its packet plus the architecture sections named there — not the whole architecture document.

---

## 1. Problem statement

Today, standing up a new environment requires an admin to remember to run `migration-intake-bootstrap-catalog` after `alembic upgrade head`. If they forget, `/health/ready` reports `catalog: {"ok": false}` and the app is otherwise unusable (no active catalog means no questionnaire). Separately, the *only* way to change what questions exist is to edit `src/migration_intake/catalog/data/catalog-0.2.0.csv` on disk and re-run the CLI — there is no in-app way to review, upload, or publish a revised catalog.

This plan covers two independent but related workstreams:

- **A — Automate the manual bootstrap step** so a fresh install is usable immediately after migrations run, with no CLI step required.
- **B — Give admins an in-app way to view and publish new catalog versions**, without weakening the existing immutable-release architecture (intakes pin a specific release; publishing a new version never rewrites history).

### 1.1 What this plan is *not*

`_data/App Data Capture_intake_1.xlsx` was considered and explicitly ruled out as a catalog source during brainstorming — it is an *evidence* workbook (`App/iTAP/WaveUtil/Infra/Database/TSS/Provisioning` sheets matching the existing B02–B05 sheet adapters), not a question-catalog definition, and per `AGENTS.md` nothing under `_data/` may ship inside the installed application anyway. It is out of scope for this plan.

### 1.2 Verified current-state facts this plan depends on

These were confirmed by reading the code, not assumed — packet owners can treat them as ground truth:

1. `publish_catalog()` (`src/migration_intake/catalog/bootstrap.py:61`) is already a plain, idempotent function: compile CSV → `CatalogPublicationService.publish_release()`. `publish_release()` (`src/migration_intake/application/services/catalogs.py:40`) is idempotent on `(version, hash)` and raises `CatalogVersionConflictError` on a version reused with different content. No new persistence logic is needed for either automation or admin publishing — only new callers.
2. `main.py` already has a `lifespan` hook, and `/health/ready` (`src/migration_intake/web/health.py:150`) already checks "at least one `PUBLISHED` `CatalogRelease` exists" — the exact condition auto-bootstrap needs to check.
3. `CatalogRepository` (`persistence/repositories/catalogs.py`) has no `list_releases()` method today — only lookups by id/version/hash and "latest published." A release-listing admin view needs this added.
4. `IntakeRepository` (`persistence/repositories/intakes.py`) has no "count/list intakes pinned to a given catalog release" method. `intakes.catalog_id` is the FK column (`persistence/models.py:369`, constraint `fk_intk_crel`) — the query is a simple filter, but the method doesn't exist yet.
5. **`get_actor_context()` is duplicated in five route files** (`applications.py`, `evidence.py`, `questionnaire.py`, `readiness.py`, `wave_util.py`) and every copy constructs `ActorContext(actor_id=str(settings.actor_id))` **with no `role_codes`**, which defaults to `frozenset()`. `Capability`, `has_capability()`, `require_capability()`, and `CONFIGURED_ACTOR_CAPABILITIES = frozenset(Capability)` already exist in `web/security.py` (lines 36–68) but `require_capability` is called from **zero routes** anywhere in the codebase. This means: if any packet in this plan wires `require_capability` into a new route without also fixing actor-context construction, it will lock out the configured actor entirely (100% failure, not a partial gap). This plan treats fixing that construction as a first-class, explicitly-scoped packet (CAT-SEC1), not an incidental side effect.
6. `EvidenceItem.application_id` is `nullable=False` (`persistence/models_evidence.py:110`). A catalog-CSV upload has no natural application to attach to, so the existing evidence-upload pipeline **cannot** be reused as-is to archive the raw uploaded catalog bytes without a schema change. See the open decision in Section 6.

---

## 2. Design principles carried over from the existing architecture

- **Catalog releases stay immutable.** Nothing in this plan edits a `PUBLISHED` release in place. "Editing the catalog" always means: compile a new CSV → publish a new semantic version → existing intakes keep their existing pin.
- **The compiler is the single source of validation truth.** Every path that creates a release (CLI, auto-bootstrap, admin upload, and any future in-browser editor) must go through the same `CatalogCompiler().compile(...)` call and the same `CatalogPublicationService.publish_release(...)` call. No packet should re-implement or bypass catalog validation.
- **Ownership checks and capability checks are two different gates.** (Carried forward from `to_archive/handoff_9_10.md` Section 0.2/10.13.) The new admin routes must not assume CSRF + actor-id presence is "authorization" — they need an explicit capability check, and that check must be backed by an actor context that actually carries capabilities.
- **Never block application boot on catalog problems.** `/health/ready` already exists as the place to *report* a missing/broken catalog. Auto-bootstrap failures should log loudly and let `/health/ready` reflect the failure, not crash the process.

---

## 3. Execution gates (parallel-agent structure)

Packets within a gate have **no file overlap** and **no dependency on each other** — they can be assigned to separate agents simultaneously. A gate's packets must all land before the next gate starts, except where a packet explicitly says otherwise.

| Gate | Packets | Can run in parallel | Shared-file coordination needed |
|------|---------|----------------------|----------------------------------|
| **CAT-0 — Independent foundations** | CAT-A1, CAT-B1, CAT-SEC1a | Yes — 3 agents, zero shared files | None |
| **CAT-1 — Admin surface** | CAT-B2, CAT-B3 | Yes — 2 agents, separate router files by design (see below) | Both register a router in `main.py`; additive one-line changes, resolve at integration |
| **CAT-2 — Wire enforcement end-to-end** | CAT-SEC1b | No — single owner, sequential, highest regression risk | Touches 5 existing, already-shipped route files |
| **CAT-3 — Deferred design spike** | CAT-B4 | N/A — not started this wave | Depends on CAT-1 being used for a real cycle first |

Total for the first wave: **5 packets, up to 5 agents**, with CAT-0's three packets startable immediately and in parallel right now.

---

## 4. Packet definitions

### CAT-A1 — Auto-publish catalog on first boot

**Depends on:** none
**Parallel with:** CAT-B1, CAT-SEC1a
**Read scope:** Section 1.2 items 1–2 of this document; `src/migration_intake/catalog/bootstrap.py`; `src/migration_intake/web/health.py` lines 140–156

**Exclusive files:**
```text
src/migration_intake/catalog/bootstrap.py   (add function only — do not change publish_catalog's signature)
src/migration_intake/main.py                (lifespan: one additive call — coordinate with CAT-B2's router-registration line at integration, not a blocker)
tests/integration/test_catalog_bootstrap.py (extend)
```

**Design:**

Add `ensure_catalog_published(session_factory: sessionmaker) -> None` to `bootstrap.py`, next to the existing `publish_catalog()`:

```python
def ensure_catalog_published(session_factory: sessionmaker) -> None:
    """Publish the packaged catalog on first boot only; never overwrite an existing release."""
    if CatalogPublicationService(session_factory).get_latest_published() is not None:
        return
    try:
        publish_catalog(session_factory, packaged_catalog_path())
    except Exception:
        logger.exception("catalog.autobootstrap.failed")  # use O01 structured logging conventions
```

Call this once from `main.py`'s `lifespan`, after the engine/session factory are constructed and before `yield`, wrapped so a failure here **never** prevents the app from starting — `/health/ready` is the correct place for this to surface, not a crash on boot.

**Red tests / acceptance criteria:**

- Fresh DB (migrations applied, zero catalog releases) → app factory boots → `/health/ready` reports `catalog: {"ok": true}` with **no** manual CLI invocation in the test.
- DB with an existing published release (including a non-default custom one) → boot leaves the `cat_releases` table row count unchanged — auto-bootstrap must not run at all when something is already published.
- Simulated compile failure in the packaged CSV (monkeypatch `packaged_catalog_path()` to a broken fixture) → `/health/live` still returns 200, `/health/ready` still reports `catalog: {"ok": false}`, and the failure is logged at ERROR with a stable event code.
- `migration-intake-bootstrap-catalog` CLI continues to work unchanged (ops re-publish path for a newer packaged CSV without a restart).

---

### CAT-B1 — Catalog admin read model

**Depends on:** none
**Parallel with:** CAT-A1, CAT-SEC1a
**Read scope:** Section 1.2 items 3–4; `persistence/repositories/catalogs.py`; `persistence/repositories/intakes.py`

**Exclusive files:**
```text
src/migration_intake/persistence/repositories/catalogs.py       (add list_releases() — additive)
src/migration_intake/persistence/repositories/intakes.py        (add count_by_catalog_id() — additive)
src/migration_intake/application/services/catalog_admin_queries.py   (new)
tests/contract/persistence/test_catalog_repository.py           (extend)
tests/unit/application/test_catalog_admin_queries.py            (new)
```

**Design:**

- `CatalogRepository.list_releases() -> list[dict]` — all releases, `pub_state`, `semantic_version`, `published_at`, `source_filename`, `compiler_report` (already stored as JSON on the release row), ordered newest-first.
- `IntakeRepository.count_by_catalog_id(catalog_id: str) -> int` — simple filtered count.
- `CatalogAdminQueryService` (new, application layer):
  - `list_releases() -> list[dict]` — decorates repository output with `is_latest: bool` (true for exactly one row — the one returned by the existing `get_latest_published_release()`) and `pinned_intake_count: int`.
  - `get_release_detail(release_id: str) -> dict | None` — sections + questions via the existing `get_sections_for_release` / `get_questions_for_section` (same read path the questionnaire itself uses — do not build a second traversal), plus `pinned_intake_count` and the stored `compiler_report`.

**Red tests / acceptance criteria:**

- `list_releases()` returns every release, newest-first, with exactly one `is_latest: true` even when multiple `PUBLISHED` releases exist.
- `pinned_intake_count` matches the number of `intakes` rows with that `catalog_id` exactly (including zero).
- `get_release_detail()` question/section ordering matches what `get_questionnaire_page()` would render for an intake pinned to that release — verified with a shared fixture release used by both tests, not two independently-authored fixtures that could silently drift.
- Unknown `release_id` returns `None` (not an exception) — the route layer decides the HTTP status.

---

### CAT-SEC1a — Add `CATALOG_MANAGE` capability (enum only, no wiring yet)

**Depends on:** none
**Parallel with:** CAT-A1, CAT-B1
**Read scope:** `web/security.py` lines 32–68

**Exclusive files:**
```text
src/migration_intake/web/security.py   (add enum member only)
tests/web/test_security.py             (extend)
```

**Design:** add `CATALOG_MANAGE = "CATALOG_MANAGE"` to the `Capability` enum. Nothing else changes in this packet — `CONFIGURED_ACTOR_CAPABILITIES = frozenset(Capability)` picks it up automatically since it's derived from the enum. This is intentionally split from CAT-SEC1b (below) so the enum exists before CAT-B3 needs to reference it, without waiting for the higher-risk actor-context rewiring.

**Red tests / acceptance criteria:**

- `Capability.CATALOG_MANAGE` exists and is included in `CONFIGURED_ACTOR_CAPABILITIES`.
- `has_capability({"CATALOG_MANAGE"}, Capability.CATALOG_MANAGE)` is `True`; empty set is `False`.

---

### CAT-B2 — Read-only catalog viewer (routes + templates)

**Depends on:** CAT-B1
**Parallel with:** CAT-B3
**Read scope:** `web/routes/applications.py` (for the `ActorContextDep`/`SessionFactoryDep` pattern to copy), `web/templates/evidence/list.html` (for template conventions)

**Exclusive files:**
```text
src/migration_intake/web/routes/catalog_admin.py            (new — GET routes only in this packet)
src/migration_intake/web/templates/catalog_admin/list.html   (new)
src/migration_intake/web/templates/catalog_admin/detail.html (new)
src/migration_intake/main.py                                 (register router — one additive line; coordinate with CAT-A1 at integration)
tests/integration/web/test_catalog_admin_routes.py           (new)
```

**Design:**

- `GET /admin/catalog` — list from `CatalogAdminQueryService.list_releases()`: version, state, published date, question count (from `compiler_report`), pinned-intake count, a link to detail, and a call-to-action link to the upload form (CAT-B3) even before CAT-B3 exists (dead link is fine mid-build; wire it up at integration).
- `GET /admin/catalog/{release_id}` — full section/question tree, compiler diagnostics, and a table of pinned intakes (id + application name — join through the existing intake/application read paths, do not add a new join method beyond what CAT-B1 provides for the count).
- No POST routes, no CSRF, no capability gate in this packet — it is read-only and this phase has no anonymous-write risk (single configured actor, no multi-tenant auth yet). State that explicitly in the route file's docstring so it isn't mistaken for an oversight later.

**Red tests / acceptance criteria:**

- Zero-release state (shouldn't happen after CAT-A1, but must not 500) renders an empty-state page.
- Multiple releases render newest-first with exactly one row visibly flagged latest.
- Detail page for an unknown id returns 404, not a 500 or empty-body 200.
- Detail page section/question order matches the questionnaire's own rendering for the same release (shared fixture, per CAT-B1's test note).

---

### CAT-B3 — CSV upload → validate → publish

**Depends on:** CAT-SEC1a (needs the `CATALOG_MANAGE` enum member to exist)
**Parallel with:** CAT-B2
**Read scope:** `catalog/bootstrap.py` (`publish_catalog` as the pattern to follow), `catalog/compiler.py` (`CatalogCompiler.compile()` signature and `CompileResult` shape)

**Exclusive files:**
```text
src/migration_intake/application/services/catalog_admin_publish.py   (new — separate file from CAT-B1's query service to avoid merge collision)
src/migration_intake/web/routes/catalog_admin_publish.py             (new — separate router file from CAT-B2's, mounted under the same URL prefix, to avoid both packets touching one route file in parallel)
src/migration_intake/web/templates/catalog_admin/upload.html         (new)
src/migration_intake/main.py                                          (register router — one additive line)
tests/unit/application/test_catalog_admin_publish_service.py         (new)
tests/integration/web/test_catalog_admin_publish_routes.py           (new)
```

**Design:**

- `CatalogAdminPublishService.preview(content: bytes, filename: str, semantic_version: str) -> CompileResult` — calls `CatalogCompiler().compile(...)` and returns the full diagnostics report (errors, warnings, section/question counts, type counts). **Does not touch the database.**
- `CatalogAdminPublishService.publish(content: bytes, filename: str, semantic_version: str, actor: ActorContext) -> dict` — re-runs `preview()` internally (never trust a client-held preview result as proof of validity), and on success calls the existing, unchanged `CatalogPublicationService.publish_release(...)`. `CatalogVersionConflictError` propagates as a 409 at the route layer, not a 500.
- Routes: `POST /admin/catalog/preview` (multipart file + version string, returns diagnostics JSON, no persistence) and `POST /admin/catalog/publish` (same inputs, persists on success). Both require the multipart/form `_csrf_token` (same pattern as `gap_workbook.py`) and both call `require_capability(actor_ctx.role_codes, Capability.CATALOG_MANAGE)` as the *first* line in the handler, before reading the uploaded file.
- **Raw uploaded bytes are not archived in this packet.** `EvidenceItem.application_id` is `NOT NULL` (Section 1.2 item 6), so the existing evidence pipeline doesn't fit without a schema change. `cat_releases.source_filename` + `source_sha256` (already persisted by `publish_release`) are sufficient for v1 integrity/audit — the hash proves what was published even without keeping the original file. See Section 6 for the fast-follow option if exact-byte retention becomes a real requirement.

**Red tests / acceptance criteria:**

- Valid CSV + unused version compiles clean on `/preview` (no DB row created), then publishes on `/publish` and immediately appears in CAT-B2's list view.
- Invalid CSV (duplicate question code, unknown response type, unparseable condition AST) returns full diagnostics from `/preview` and — critically — `/publish` on the same content also refuses and creates no release row (never trust the client to have called preview first).
- Reusing an existing version with different content returns 409 with both hashes in the error detail (matching `CatalogVersionConflictError`'s existing message shape); the existing release is untouched.
- Re-publishing identical bytes+version is idempotent (returns the existing release, matching `publish_release`'s existing contract) rather than erroring.
- Missing CSRF token is rejected before the file is read at all.
- Missing `CATALOG_MANAGE` capability is rejected with 403 before the file is read at all (requires `app.dependency_overrides[get_actor_context]` in the test to simulate a capability-less actor — CAT-SEC1a's enum member is sufficient for this test; CAT-SEC1b's real-actor wiring is not required yet).

---

### CAT-SEC1b — Wire capability enforcement into actor context (sequential, highest-risk packet)

**Depends on:** CAT-B3 landed (so `CATALOG_MANAGE` is actually consumed somewhere) and CAT-SEC1a
**Parallel with:** nothing — single owner, run this alone
**Read scope:** `web/security.py`; the five duplicated `get_actor_context()` functions; `to_archive/handoff_9_10.md` Section 0.2 (why this gap exists and its original blast-radius assessment)

**Exclusive files:**
```text
src/migration_intake/web/routes/applications.py    (get_actor_context: add role_codes)
src/migration_intake/web/routes/evidence.py        (get_actor_context: add role_codes)
src/migration_intake/web/routes/questionnaire.py   (get_actor_context: add role_codes)
src/migration_intake/web/routes/readiness.py       (get_actor_context: add role_codes)
src/migration_intake/web/routes/wave_util.py       (get_actor_context: add role_codes)
tests/web/test_actor_context_capabilities.py       (new — regression guard for this exact fix)
```

**Design:** change every copy of

```python
return ActorContext(actor_id=str(settings.actor_id))
```

to

```python
return ActorContext(actor_id=str(settings.actor_id), role_codes=CONFIGURED_ACTOR_CAPABILITIES)
```

This is a **one-line change repeated in five files**, deliberately kept as its own packet rather than folded into CAT-B3 because it is the only change in this entire plan that touches already-shipped, already-tested route files. Do not attempt to deduplicate the five copies into a shared helper as part of this packet — that's a legitimate follow-up refactor, but bundling it here increases the diff size of the one packet that most needs a small, reviewable diff.

**Red tests / acceptance criteria:**

- New regression test asserts `get_actor_context()` in each of the five files returns an `ActorContext` whose `role_codes` is non-empty and contains every `Capability` value (i.e., equals `CONFIGURED_ACTOR_CAPABILITIES`).
- **Full existing test suite (`python -m pytest tests/ -q`) passes unchanged** — this is the acceptance bar, not a focused subset, because this packet is the one place in the plan that could silently break already-working evidence/candidate/questionnaire/readiness/wave-util flows if `require_capability` were also (incorrectly) added somewhere unexpected as part of this change. This packet adds capabilities to the actor; it does not add new `require_capability` calls anywhere except where CAT-B3 already placed them.
- CAT-B3's "missing capability → 403" test (written against a dependency-override actor in its own packet) continues to pass unmodified — proving the override path and the real path both work.

---

### CAT-B4 — In-browser structured catalog editor (deferred design spike)

**Depends on:** CAT-B2 and CAT-B3 in production use for at least one real publish cycle
**Status:** **Not started this wave.** Recorded here so the next owner doesn't have to reconstruct the reasoning, not as a committed contract.

CSV-upload-and-compile (CAT-B3) already gives admins a way to change the catalog without CLI/filesystem access, reusing 100% of the existing, trusted compiler. A structured per-question editor is a strictly larger investment (new draft persistence, per-response-type input widgets, a diff-against-latest view) and its correct shape depends on whether admins actually find hand-editing a CSV workable. Evaluate two directions when this is picked up, in this order:

1. **Thin editor (start here):** a textarea pre-filled with the current catalog's CSV text, "Compile & Preview" reusing CAT-B3's exact `preview()` call. Zero new persistence. This is a UI-only improvement on top of CAT-B3.
2. **Structured editor (only if #1 proves unworkable):** real `CatalogDraft` / `CatalogDraftQuestion` tables, per-field form inputs, serialized to CSV text server-side before being fed to the same `CatalogCompiler` — the compiler remains the single validation authority either way, so this is additive UI/persistence, not new validation logic.

Do not begin schema work for option 2 speculatively; write a short follow-up packet definition once #1 has been tried.

---

## 5. Data model changes in this plan

**None required for CAT-A1, CAT-B1, CAT-B2, CAT-SEC1a, or CAT-SEC1b.** They are all additive read paths, a new startup call, or a one-line actor-context fix.

**CAT-B3 requires no migration either**, by design (Section 1.2 item 6 / packet design note) — it reuses `cat_releases.source_filename`/`source_sha256` as-is and does not attempt to archive raw uploaded bytes in v1.

If exact-byte retention of uploaded catalog CSVs becomes a real requirement later, the smallest fix is a new standalone table (e.g. `cat_release_sources`: `release_id` FK, `raw_content` blob, `uploaded_by_actor_id`, `uploaded_at`) rather than relaxing `EvidenceItem.application_id` — keep catalog governance artifacts decoupled from application-scoped evidence. This is an open decision, not a committed packet (see Section 6).

---

## 6. Open decisions requiring a human sign-off

1. **Should `CAT-B2`'s viewer really be capability-ungated?** This plan assumes yes for this phase (no multi-tenant auth exists yet, so gating a read-only page adds process without adding real security). Revisit when real authentication lands.
2. **Raw catalog-CSV byte retention** (Section 5) — ship without it (this plan's default) or add `cat_release_sources` now? Recommend deferring until an actual audit requirement names it.
3. **Semantic version selection UX in CAT-B3** — this plan has the admin type the version string manually (matches today's CLI, which hardcodes `CATALOG_VERSION = "0.2.0"` and requires a code change to bump). An auto-suggest ("last was 0.2.0, pick 0.3.0 or 1.0.0") is a small UX nicety that can be added inside CAT-B3 without changing its contract — left to the implementing agent's judgment rather than specified here.
4. **CAT-SEC1b's five-file duplication** — this plan explicitly defers deduplicating `get_actor_context()` into a shared helper to keep the risky packet's diff small. Track as a follow-up cleanup, not part of this plan.
5. **Deduplicating `require_capability` for evidence/candidate/gap-workbook routes** (the broader gap first identified in `to_archive/handoff_9_10.md` Section 0.2) is explicitly **out of scope** for this plan — CAT-SEC1b only wires actor capabilities correctly so that *this plan's own new routes* can use them safely. Wiring `require_capability` into the pre-existing routes is a separate, already-tracked P1 item.

---

## 7. Verification commands

Per packet, before marking it done:

```powershell
python -m pytest tests/unit/ -q          # CAT-A1, CAT-B1, CAT-SEC1a, CAT-B3 service layer
python -m pytest tests/integration/ -q   # CAT-A1, CAT-B2, CAT-B3 routes
python -m pytest tests/contract/ -q      # CAT-B1 repository additions
python -m ruff check src/migration_intake
python -m mypy src/migration_intake
```

Before merging **CAT-SEC1b** specifically:

```powershell
python -m pytest tests/ -q               # full suite — see CAT-SEC1b acceptance criteria
```

At the end of Gate CAT-1 (both CAT-B2 and CAT-B3 landed), run the manual end-to-end check:

1. Fresh DB, boot the app — confirm CAT-A1 auto-published the packaged catalog, `/health/ready` is green, no CLI command run.
2. Open `/admin/catalog` — confirm the auto-published release is listed and flagged latest.
3. Upload a modified synthetic catalog CSV with a new version through `/admin/catalog/publish` — confirm it appears in the list, the prior release is untouched, and an intake created before the upload still renders using its original pinned version.
4. Attempt the same publish with `role_codes=frozenset()` (dependency override) — confirm 403 before any file processing, once CAT-SEC1b has landed.
