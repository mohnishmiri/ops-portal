# Intake UX Redesign — Implementation Plan and Parallel-Agent Execution Guide

**Version:** 0.1
**Created:** 2026-09-10
**Approved mockups:** `_data/ux_mockups/intake_ux_mockups.html` (gitignored; open locally)
**Implementation root:** `src/migration_intake`
**Convention:** same packet format as `src/docs/plan_catalog_automation.md` — exclusive file ownership so packets run in parallel.

> Read your assigned packet plus Sections 1–3. Do not read the whole document.

---

## 1. Why this work exists

The intake is functionally correct and practically unusable. Measured on the live app, not estimated:

- The `APPLICATION` questionnaire section renders **3,882px tall for 8 questions** — 56 inputs and 14 buttons on one page.
- Section navigation renders as an **unstyled bullet list stacked above the content**, not in the design system's side rail.
- Every question permanently shows **Save / Clear / Confirm**, so answering a section is a sequence of individual form posts.
- Answer provenance is shown raw: `Last updated: 2026-09-10T19:18:44.531622+00:00 by Unknown Reason: Accepted from candidate 1bc7e59e-8659-42b7-9592-24d88ce07e25`.
- Imported proposals — the entire output of the evidence pipeline — are surfaced as a small link reading "2 pending review" at the bottom of a card. A user with 17 pending proposals reported the app looked like nothing had imported.
- Accepting those 17 proposals costs 17 separate page round-trips.

### Approved decisions

1. **Autosave.** Fields save on blur/change with a "✓ Saved" confirmation. Per-question Save buttons are removed.
2. **Proposals reviewable in both places.** An inline accept/reject strip on the question itself, *and* a bulk review table for clearing a whole import. Both drive the same existing candidate-decision services.

---

## 2. Constraints every packet must respect

- **No inline event handlers and no external assets.** `tests/web/test_ui_shell.py` asserts both, and a CSP is applied by `web/security.py`. All behaviour goes in `/static/js/app.js` (or a file it imports) and binds listeners programmatically.
- **Design tokens only.** The same audit caps hard-coded colours per stylesheet. Use `var(--color-*)`, `var(--space-*)`, `var(--radius-*)`.
- **Each packet owns exactly one stylesheet.** `questionnaire.css`, `hub.css`, `review.css` already exist and are already linked from `base.html`. Do not edit `components.css`, `layout.css` or `base.html`.
- **Importers propose, humans approve.** Nothing in this work may write a canonical answer without an explicit user action (`AGENTS.md`).
- **Stable selectors are a contract.** The browser suite locates elements by domain-keyed ids — `#question-<CODE>`, `#q-<CODE>-input`, `#q-<CODE>-yes|-no|-unknown`. Keep them. Changing an id breaks the response-type matrix and both journey specs.

### The verification gate

```
python -m pytest tests/browser/ -m browser -q -p no:unraisableexception     # currently 21 passed
python -m pytest tests/ -q --ignore=tests/integration/migrations --ignore=tests/browser   # 1897 passed, 1 skipped, 9 errors
```

The **9 errors are pre-existing and unrelated** — a known `.env`/Alembic `DATABASE_URL` test-isolation bug in `tests/unit/web/test_health.py` and `tests/web/test_health_bootstrap.py`. Do not fix them; confirm the count is unchanged.

---

## 3. Gates

| Gate | Packets | Parallel | Shared-file coordination |
|------|---------|----------|--------------------------|
| **UX-0** | UX-1, UX-2, UX-3 | Yes — three agents, disjoint file sets | `main.py` router registration (UX-2 only, one line) |
| **UX-1 follow-up** | UX-4 (measurement/people editors), UX-5 (accessibility pass) | After UX-0 | — |

---

## 4. Packets

### UX-1 — Questionnaire redesign (autosave, inline proposals, collapse)

**Depends on:** none · **Parallel with:** UX-2, UX-3

**Exclusive files**
```
src/migration_intake/web/templates/questionnaire/section.html
src/migration_intake/web/routes/questionnaire.py
src/migration_intake/web/static/js/app.js
src/migration_intake/web/static/css/questionnaire.css
src/migration_intake/application/queries.py        (get_questionnaire_page only)
tests/browser/matrix_support.py                    (see coupling note)
tests/browser/test_questionnaire_ux.py             (new)
```

**Build**

1. **Side rail.** Render sections in the design system's side-nav column instead of a bullet list: per-section completion dot, `answered/required` count, and a badge when that section has pending proposals. Add a "Hide derived questions" toggle — 37 of 93 required questions are computed types nobody can answer, and hiding them is the single biggest reduction in apparent workload.
2. **Collapse answered questions** to one line: code, question text, and the formatted current value. Unanswered and proposal-bearing questions stay expanded.
3. **Inline proposal strip** on any question with a `PROPOSED` candidate: the proposed value rendered readably, its source locator and confidence, and Accept / Reject buttons posting to the **existing** candidate-decision routes. Do not duplicate that logic.
4. **Autosave.** On blur/change, submit the answer and show a "✓ Saved" chip; show a retryable inline error on failure. Remove per-question Save buttons; keep Clear and Confirm as secondary actions. The route needs a non-redirecting response for this path (e.g. content-negotiated JSON or a sibling endpoint) that returns the **new `revision_number`** so the client updates its concurrency token in place — otherwise the second edit of the same field 409s.
5. **Humanise metadata**: relative time ("2 minutes ago"), the actor's display name, and no UUIDs. Keep provenance reachable behind a "history" affordance.
6. **Sticky section footer**: progress, "Skip to next unanswered", "Next section".

**Coupling note — read this before changing the Save button.** `tests/browser/matrix_support.py::run_round_trip` currently clicks `button:has-text('Save')`. With autosave that button disappears and **every response-type matrix case fails**. You own `matrix_support.py`: change `run_round_trip` to blur the field and wait for the saved indicator. Do not change any `test_matrix_*.py` case file, and keep `#q-<CODE>-input` and `#question-<CODE>` intact — `test_evidence_journey.py` and `test_intake_form_journey.py` assert on them and are owned by UX-3.

**Red tests** (`test_questionnaire_ux.py`)
- Editing a field and blurring persists the value with no Save click, and a saved indicator appears.
- Editing the same field twice in a row succeeds — proves the concurrency token is refreshed rather than stale.
- An answered question renders collapsed and shows its value; expanding reveals the editor.
- A question with a pending proposal shows the inline strip; Accept makes it the current answer and the strip disappears.
- The derived-questions toggle hides computed types.
- No inline `on*` handlers exist in the rendered HTML.

---

### UX-2 — Intake hub (new landing page)

**Depends on:** none · **Parallel with:** UX-1, UX-3

**Exclusive files**
```
src/migration_intake/web/routes/intake_hub.py            (new)
src/migration_intake/web/templates/intake/hub.html       (new)
src/migration_intake/application/services/intake_hub.py  (new)
src/migration_intake/web/static/css/hub.css
src/migration_intake/main.py                             (one added router registration line)
tests/browser/test_intake_hub.py                         (new)
tests/unit/application/test_intake_hub_service.py        (new)
```

**Do not edit `application/queries.py`** — UX-1 owns it. Put the aggregate read model in your own service.

**Build** `GET /applications/{app_id}/intakes/{intake_id}` (or `/hub` if that path is taken) showing:

- Application identity: display name, correlation id, catalog version, intake state.
- **Three counters, which must be computed, not guessed:** required answered vs total; pending proposals awaiting decision; and questions that need a human — i.e. required, not computed, and with no proposal available. For the reference intake these are 18/93, 17, and 38.
- A section grid: per-section progress bar, answered/required, and a "N new" badge for pending proposals. Sections whose questions are entirely computed should say so rather than showing 0%.
- A primary "Continue where I left off" action linking to the first section containing an unanswered required question.

Link to the hub from the application workspace and the questionnaire breadcrumb.

**Red tests**
- Counters match a seeded fixture exactly, including the computed-question exclusion.
- A fully-computed section renders its explanatory state, not "0 of 3".
- "Continue where I left off" targets the first section with an unanswered required question.
- Hub renders with zero answers and with all answers (no divide-by-zero, no empty-state crash).

---

### UX-3 — Evidence lanes and bulk proposal review

**Depends on:** none · **Parallel with:** UX-1, UX-2

**Exclusive files**
```
src/migration_intake/web/templates/evidence/list.html
src/migration_intake/web/templates/evidence/import_coverage.html
src/migration_intake/web/routes/evidence.py
src/migration_intake/web/static/css/review.css
tests/browser/test_evidence_journey.py
tests/browser/test_intake_form_journey.py
tests/integration/web/test_evidence_routes.py
tests/browser/test_review_ux.py                (new)
```

**Build**

1. **Two lanes on the sources page**: "Source documents" (UAQ, Interface Tracking, WaveUtil — we read them and propose) and "Intake form" (download blank, return completed). The distinction must be unmissable: a user already uploaded a completed intake form into the evidence uploader and got an `UNRECOGNIZED_SHEET` result.
2. **Imports table** stating outcome plainly per row: identity verdict, proposal count, problem count, and a primary action ("Review 17 →"). A quarantined row must explain the mismatch and offer a "How to fix" affordance rather than a dead end.
3. **Bulk review** on the coverage page: a checkbox per proposal, "Accept selected (N)" and "Reject selected", each row showing **current answer vs proposed value**. Rows that would **replace an existing answer are visually flagged and never pre-selected** — silent overwrites are how the `APP-002` owner value was previously lost. Keep the existing per-row Accept for one-at-a-time work.
4. Bulk accept must reuse `CandidateService` per candidate and report partial failure honestly (e.g. "12 accepted, 1 skipped — stale"), never a silent all-or-nothing.

**Coupling note.** You own the two journey specs because you are changing the coverage markup they assert on (`article.card`, `form[action$="/accept"]`). Keep them passing. Do not change questionnaire selectors — UX-1 owns those.

**Red tests**
- Sources page renders both lanes and the intake-form download link.
- Bulk accept of N proposals creates N canonical answers in one action.
- A proposal that would replace an existing answer is flagged and unchecked by default.
- Bulk accept with one stale candidate reports a partial result and still accepts the rest.
- The quarantined row shows the identity mismatch and its remediation affordance.

---

## 5. Sequencing and integration

1. Launch UX-1, UX-2, UX-3 together.
2. On landing, run the full gate. The browser suite must be **≥ 21 passing** with no regression in the matrix or journeys.
3. Re-screenshot the questionnaire and compare against the approved mockup before declaring done.
4. Update `STATE.md` with a dated checkpoint (agents leave this to the integrator to avoid concurrent edits).

## 6. Explicitly out of scope

- The 9 response types still listed in `PENDING_COVERAGE` in the matrix.
- Expanding the UAQ column mapping (governance work, tracked separately).
- The three catalog data-model gaps recorded in `STATE.md` (`COUNT_PAIR` unit, `NET-007` options, NULL `field_name`).
- Any change that writes a canonical answer without explicit user action.
