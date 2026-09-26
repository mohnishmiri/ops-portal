# Full UI Consistency — Implementation Plan and Parallel-Agent Execution Guide

**Version:** 0.1
**Created:** 2026-09-10
**Approved mockups:** `_data/ux_mockups/full_ui_consistency_mockup.html` (gitignored; open locally)
**Predecessor plans:** `src/docs/plan_intake_ux_redesign.md` (UX-0, complete), `src/docs/plan_catalog_automation.md` (complete)
**Convention:** same packet format — exclusive file ownership so packets run in parallel.

> Read your assigned packet plus Sections 1–3. Do not read the whole document.

---

## 1. Why this work exists

The four pages rebuilt in UX-0 (hub, questionnaire, evidence sources, bulk review) now use a consistent design system. The remaining 12 pages do not. The gap ranges from minor (missing nav context blocks) to critical:

- **Readiness** (`readiness/status.html`, `freeze_success.html`, `freeze_error.html`, `snapshot.html`) uses **Tailwind CSS utility classes** (`bg-white shadow rounded-lg p-6 bg-green-100 text-green-800`) — an entirely different framework from the rest of the app. It visually clashes with every path that ends in a freeze. The freeze POST also has no CSRF token.
- **Application workspace** (`applications/workspace.html`) has an inline `style=` attribute on line 52, only one nav entry ("Overview"), and no link to the intake hub — the primary new entry point.
- **Applications list** (`applications/list.html`) has an embedded create form in the same page as the list. No proposal or evidence counts.
- **WaveUtil** uses CSS class names (`filter-select`, `summary-stats`, `stat`) that don't exist in `components.css`.
- **Catalog admin** and **readiness** routes are missing the `app_name`, `nav_items`, and `command_actions` context variables that `base.html` expects.

### Design principles (same as UX-0)

- Design tokens only: `var(--color-*)`, `var(--space-*)`, `var(--radius-*)`. No hex literals.
- No inline `style=""` attributes. No Tailwind utility classes.
- No inline `on*` event handlers. All JS in `/static/js/app.js`.
- No external assets.
- Every page: `global-header` → `command-bar` → `workspace-shell` (side rail + main). Every template must fill `title`, `global_nav`, `command_actions`, `content` blocks.
- Responsive: all grids use `grid-template-columns: repeat(auto-fit, minmax(0, 280px))` (never bare `1fr` without `minmax`). Columns collapse at ≤768px.

---

## 2. Coordinator pre-work (done before agents are dispatched)

The coordinator has already completed:

- Created `src/migration_intake/web/routes/_nav.py` with `app_nav_items()` and `global_nav_items()` — shared helpers so no two packets independently invent nav construction.
- Created stub CSS files already linked in `base.html`: `applications.css`, `readiness.css`, `wave_util.css`.

`_nav.py` is **not owned by any packet** — import from it freely, never modify it. If you find a nav item missing, raise it in code review; do not edit `_nav.py` mid-packet.

---

## 3. Constraints every packet must respect

- **Stable selectors are a contract.** `#question-<CODE>`, `#q-<CODE>-input`, `#q-<CODE>-yes|-no|-unknown` are browser-suite anchors. Never touch them.
- **`_nav.py` is read-only during implementation.** Import, don't edit.
- **`base.html` is read-only.** CSS links are already in place. Do not add more.
- **`app.js` is owned by UX-4c** (WaveUtil needs filter behaviour). Other packets must not edit it. If you need JS, add a `{% block extra_scripts %}` in your template and inline a `<script>` that only binds on your own elements. UX-4b (readiness freeze confirmation) may do this for the freeze confirm dialog.
- **`application/queries.py` is owned by UX-4a.** UX-4b, UX-4c, UX-4d put their own queries in their own service files.
- **Importers propose, humans approve.** Nothing here writes a canonical answer without explicit user action.

### The verification gate

```
python -m pytest tests/browser/ -m browser -q -p no:unraisableexception     # currently 38 passed
python -m pytest tests/ -q --ignore=tests/integration/migrations --ignore=tests/browser   # 1926 passed, 1 skipped, 9 errors
```

The **9 errors are pre-existing** — a known `.env`/Alembic `DATABASE_URL` isolation bug. Confirm count is unchanged.

---

## 4. Gates

| Gate | Packets | Parallel | Coordination |
|------|---------|----------|--------------|
| **UX-4** | UX-4a, UX-4b, UX-4c, UX-4d | Yes — four agents, disjoint file sets | `_nav.py` shared read-only |
| **UX-5** | Accessibility pass, measurement/people editors | After UX-4 | — |

---

## 5. Packets

---

### UX-4a — Application shell (list, workspace, create, edit)

**Depends on:** coordinator pre-work · **Parallel with:** UX-4b, UX-4c, UX-4d

**Exclusive files**
```
src/migration_intake/web/routes/applications.py
src/migration_intake/web/templates/applications/list.html
src/migration_intake/web/templates/applications/workspace.html
src/migration_intake/web/templates/applications/new.html
src/migration_intake/web/templates/applications/edit.html
src/migration_intake/web/static/css/applications.css
src/migration_intake/application/services/application_summary.py    (new)
src/migration_intake/application/queries.py                          (list/workspace queries only)
tests/browser/test_applications_ux.py                               (new)
tests/unit/application/test_application_summary_service.py          (new)
```

**Do not edit** `_nav.py`, `base.html`, `app.js`.

#### Backend changes

1. **New service** `application/services/application_summary.py`:
   - `get_application_list_stats(session, app_ids: list[str]) -> dict[str, AppStats]`
     - Single query joining `intakes → import_runs → candidates` to count `pending_proposal_count` per app
     - Single query on `evidence_files` for `evidence_count` per app
     - Returns `AppStats(evidence_count, pending_proposal_count, has_open_intake, open_intake_id)`
   - `get_workspace_summary(session, app_id: str) -> WorkspaceSummary`
     - Existing workspace query extended with: `hub_href`, `proposal_count`, `evidence_count`, `readiness_state`
     - `hub_href` = `/applications/{app_id}/intakes/{intake_id}` for the open intake

2. **`routes/applications.py`**:
   - `list_applications`: add `command_actions` block context; call `get_application_list_stats()` to enrich each app row with counts.
   - `get_application_new`: add `app_name=None`, `nav_items=global_nav_items("applications")`, `command_actions` breadcrumb context.
   - `get_application` (workspace): import `app_nav_items` from `_nav`; expand `nav_items` from `["Overview"]` to full app rail (hub / questionnaire / sources / wave-util / readiness); pass `hub_href`, `proposal_count`, `evidence_count`.
   - `get_application_edit`: add `app_name=workspace.display_name`, `nav_items=app_nav_items(...)`, `command_actions`.
   - Remove the embedded create form from the list route entirely — `GET /applications/new` is now the only create entry point.

#### Template build

**`applications/list.html`**
- Remove embedded create form (it moves to `/applications/new`)
- Command bar: "Applications" breadcrumb | "New application →" (cyan button linking to `/applications/new`)
- Global nav: `global_nav_items("applications")`
- Main: heading "Applications" + search input (filter client-side by name) + status filter (`<select>`)
- Application card grid (`display: grid; grid-template-columns: repeat(auto-fit, minmax(0, 320px))`)
  - Each card: display name (large), state pill, correlation ID line, "N files · N proposals" counts, "Open workspace →" button
- Empty state: single centred card "No applications yet" with "Register your first →" link

**`applications/workspace.html`**
- Remove inline `style=` on line 52 — replace with CSS class in `applications.css`
- Side rail: full app nav via `app_nav_items(app_id, intake_id, "workspace")`
- Command bar: "Applications → {app_name}" breadcrumb | "Edit" ghost button
- Main: application identity card (name, state, identifiers, catalog version)
- 2×2 action card grid (CSS class `.app-action-grid`):
  1. **Intake Hub** — "18 of 93 answered · 17 pending proposals" → "Open hub →" (primary, hub_href)
  2. **Evidence** — "N files imported · N proposals" → "Review sources →"
  3. **WaveUtil** — "N servers" → "View servers →"
  4. **Readiness** — "Not ready · N dimensions incomplete" or "Ready" → "Check readiness →"
- No duplicate button grid below the cards (remove old "workspace actions" section)

**`applications/new.html`** and **`applications/edit.html`**
- Full shell with global nav, command bar (breadcrumb: "Applications → New application" / "Applications → {name} → Edit")
- Single card "Register application" / "Edit application"
- Three fields: display name (required), identifier type (select), identifier value (conditional)
- Buttons: "Register →" / "Save changes →" (cyan) | "Cancel" (ghost, links back)

#### Tests (`test_applications_ux.py`, `test_application_summary_service.py`)

- List page renders app cards (not a table with embedded form)
- Each card shows evidence and proposal counts from seeded fixture
- "New application →" navigates to `/applications/new`
- Workspace shows hub link (`a[href*="/intakes/"]`) as primary action
- Workspace 2×2 grid renders all four action cards
- Create form submits and redirects to workspace
- No inline `style=` attributes on any applications page (regex assert)
- Unit: `get_application_list_stats` returns correct counts for seeded apps with/without open intakes

---

### UX-4b — Readiness rebuild (Tailwind → design system)

**Depends on:** coordinator pre-work · **Parallel with:** UX-4a, UX-4c, UX-4d

**Exclusive files**
```
src/migration_intake/web/routes/readiness.py
src/migration_intake/web/templates/readiness/report.html
src/migration_intake/web/templates/readiness/freeze_success.html
src/migration_intake/web/templates/readiness/freeze_error.html
src/migration_intake/web/templates/readiness/snapshot.html
src/migration_intake/web/static/css/readiness.css
tests/browser/test_readiness_ux.py                                  (new)
tests/integration/web/test_readiness_routes.py                      (new or extend)
```

**Do not edit** `_nav.py`, `base.html`, `app.js`, `application/queries.py`.

#### Backend changes

**The key constraint**: The readiness router is mounted at `prefix="/intakes/{intake_id}"` — `app_id` is not in the path. You must resolve it with a DB lookup.

1. **New private helper in `readiness.py`**:
   ```python
   async def _resolve_app_id(intake_id: str, session: AsyncSession) -> str | None:
       """One-join lookup: intake → application_id."""
       row = await session.execute(
           select(ApplicationIntake.application_id)
           .where(ApplicationIntake.id == intake_id)
       )
       return row.scalar_one_or_none()
   ```

2. **All four readiness routes** — add to context:
   ```python
   app_id = await _resolve_app_id(intake_id, session)
   nav_items = app_nav_items(app_id, intake_id, "readiness") if app_id else []
   app_name = ...  # second query or join if needed
   command_actions = {...}
   ```
   If `app_id` is `None` (orphaned intake), render the page without the nav rail rather than crashing.

3. **CSRF on the freeze form**: the freeze POST currently has no CSRF token and the route doesn't validate one. Add:
   - `csrf_token` to the `GET /intakes/{id}/readiness` context
   - `<input type="hidden" name="_csrf_token" value="{{ csrf_token }}">` to the freeze form
   - CSRF validation in `POST /intakes/{id}/freeze` (follow the same pattern as other POST routes)

#### Template build — zero Tailwind classes allowed

**`readiness/report.html`**
- Command bar: "Applications → {app_name} → Readiness" breadcrumb | "Refresh" ghost button
- Side rail: `app_nav_items(app_id, intake_id, "readiness")`
- Main:
  - **Status hero card** (`.readiness-status`): large icon (✓ or ✗), heading "Ready to freeze" / "Not ready", `checked_at` displayed as relative time ("Checked 3 minutes ago")
  - State modifier classes: `.readiness-status--ready` (success tint) / `.readiness-status--not-ready` (warning tint)
  - **Dimensions list**: each as a row card — dimension name (bold), status pill (`PASS` / `FAIL` / `PENDING`), description. Failed rows: `var(--color-danger-bg)` background, danger border-left.
  - **Freeze section** (shown only when `readiness.is_ready`): card with "Freeze this intake" heading, warning "This action is irreversible. The intake will be locked.", "Freeze →" cyan button, CSRF token hidden input.
  - When not ready: warning card "Resolve all failing dimensions before freezing."
- **No** `bg-white`, `shadow`, `rounded-lg`, `p-6`, `flex`, `items-center`, `text-green-800`, `bg-green-100`, or any other Tailwind utility class anywhere in the file.

**`readiness/freeze_success.html`**
- Full shell with nav.
- Centered success card: checkmark icon (SVG, inline, `color: var(--color-success)`), "Intake frozen" heading, "This intake is now locked and cannot be modified.", "View snapshot →" (cyan) | "Back to workspace" (ghost) buttons.

**`readiness/freeze_error.html`**
- Full shell with nav.
- Centered error card: ✗ icon, "Freeze failed" heading, error detail, "Try again →" | "Back to readiness" buttons.

**`readiness/snapshot.html`**
- Full shell with nav.
- Frozen snapshot banner (info tint, full width): "This intake was frozen on {date} and is read-only."
- Same dimensions list as report.html but read-only — no freeze form, no buttons.

**`readiness.css`** — styles for `.readiness-status`, `.readiness-status--ready`, `.readiness-status--not-ready`, `.readiness-dimension`, `.readiness-dimension--fail`. Tokens only.

#### Tests (`test_readiness_ux.py`, `test_readiness_routes.py`)

- Readiness page renders zero Tailwind classes (regex: no class matching `bg-[a-z]+-[0-9]+` or `text-[a-z]+-[0-9]+` or `rounded-lg`)
- Nav rail present and "Readiness" item is active
- FAIL dimension rendered with danger tint class
- Freeze button absent when not ready, present when ready
- CSRF token in freeze form — route rejects POST without it (403)
- Freeze success page renders success card with correct links
- Snapshot page shows frozen banner, no freeze button
- `app_id=None` (orphaned intake): page renders without crashing, nav rail omitted

---

### UX-4c — WaveUtil + Import detail

**Depends on:** coordinator pre-work · **Parallel with:** UX-4a, UX-4b, UX-4d

**Exclusive files**
```
src/migration_intake/web/routes/wave_util.py
src/migration_intake/web/templates/wave_util/list.html
src/migration_intake/web/templates/wave_util/detail.html
src/migration_intake/web/templates/evidence/import_detail.html
src/migration_intake/web/static/css/wave_util.css
src/migration_intake/web/static/js/app.js                           (filter behaviour only)
tests/browser/test_wave_util_ux.py                                  (new)
tests/integration/web/test_wave_util_routes.py                      (extend)
```

**Do not edit** `_nav.py`, `base.html`, `application/queries.py`. Do not touch any questionnaire, hub, evidence sources, or bulk-review files.

#### Backend changes

**`routes/wave_util.py`** — both GET routes, add:
```python
from migration_intake.web.routes._nav import app_nav_items

nav_items = app_nav_items(app_id, intake_id, "wave_util")
app_name = ...  # already available via application lookup — check existing context
command_actions = {...}  # "Export →" button for list; "Back to list" for detail
```

No new service needed — wave_util already has `app_id` and `intake_id` in the path; the application name can be resolved via the existing workspace query or a lightweight name-only query.

#### Template build

**`wave_util/list.html`**
- Command bar: "Applications → {app_name} → WaveUtil" | "Export →" button
- Side rail: `app_nav_items(app_id, intake_id, "wave_util")`
- Main:
  - Summary stat bar (`.stat-bar`): "247 servers · 3 PROD · 12 TEST · 232 DEV" — single row of `<span class="stat-chip">` chips
  - Filter row: environment pills (ALL / DEV / PROD / TEST — toggle buttons, not a select), state filter (select: ALL / ACTIVE / DECOMMISSIONED), text search input. All client-side filtering via `app.js` (see below).
  - Data table (`.data-table`): hostname, environment pill, state pill, OS, last updated (relative), "View →"
  - Pagination: `← Prev  Page {n} of {total}  Next →`
- Replace ALL non-design-system class names (`filter-select`, `summary-stats`, `stat`, `server-table`, `state-badge`) with design-system equivalents (`data-table`, `status-pill`, `stat-chip`)

**`wave_util/detail.html`**
- Command bar: "Applications → {app_name} → WaveUtil → {hostname}" | "Back to list" button
- Side rail: `app_nav_items(app_id, intake_id, "wave_util")`
- Main: server detail card — 2-column `<dl>` layout with `<dt>` (label) and `<dd>` (value). Fields: hostname, environment, state, OS, CPU, RAM, disk, last seen, wave assignment.
- Pending candidates section (if `pending_candidates`): same card-based proposal strip as questionnaire (read `.qx-proposal` styles from `questionnaire.css` — do not re-invent).

**`evidence/import_detail.html`**
- Command bar: "Applications → {app_name} → Evidence → {run label}" | "Back to sources" button
- Side rail: app nav, "Evidence" active
- Main:
  - Run summary card: identity verdict pill, upload time (formatted), uploader name, "N proposals · M problems", "Review proposals →" button
  - Findings accordion grouped by severity: ERROR (danger tint), WARNING (warning tint), INFO (neutral). Each finding: code badge (`<span class="tag">`), message, expandable raw context (`<details>`).

**`app.js`** additions — WaveUtil filter behaviour:
- `data-filter-group="environment"` toggle buttons: clicking one filters `.data-table tbody tr` by `data-environment` attribute. All = show all.
- State select: filters by `data-state` attribute.
- Text search: filters by `data-hostname` substring.
- Filters compose (AND logic). No server round-trip — client-side only.
- `data-wave-util-list` marks the table so only these listeners activate on WaveUtil pages, not everywhere.

**`wave_util.css`** — `.stat-bar`, `.stat-chip`, `.filter-pill`, `.filter-pill--active`. Tokens only.

#### Tests (`test_wave_util_ux.py`, `test_wave_util_routes.py`)

- List page: nav rail present and "WaveUtil" active
- List page: no non-design-system class names (`filter-select`, `summary-stats`, `stat`) in rendered HTML
- Filter pills present; clicking "PROD" hides DEV rows (browser test)
- Detail page: all server fields in `<dl>` layout
- Import detail: findings grouped by severity, run summary card shows verdict
- No inline `on*` handlers on any wave-util or import-detail page

---

### UX-4d — Catalog admin nav + detail

**Depends on:** coordinator pre-work · **Parallel with:** UX-4a, UX-4b, UX-4c

**Exclusive files**
```
src/migration_intake/web/routes/catalog_admin.py
src/migration_intake/web/routes/catalog_admin_publish.py
src/migration_intake/web/templates/catalog_admin/list.html
src/migration_intake/web/templates/catalog_admin/detail.html
src/migration_intake/web/templates/catalog_admin/upload.html
tests/integration/web/test_catalog_admin_routes.py                  (extend)
```

**Do not edit** `_nav.py`, `base.html`, `app.js`, any UX-4a/4b/4c files.

#### Backend changes

**`routes/catalog_admin.py`** and **`routes/catalog_admin_publish.py`** — add to every route context:
```python
from migration_intake.web.routes._nav import global_nav_items

nav_items = global_nav_items("catalog_admin")
command_actions = {...}  # varies per page (see below)
```

No new queries needed — catalog admin data is already correctly fetched.

#### Template build

**`catalog_admin/list.html`**
- Command bar: "Catalog Admin" breadcrumb | "Upload new catalog →" cyan button (links to `/admin/catalog/upload`)
- Side rail: `global_nav_items("catalog_admin")`
- Main: existing data table already uses design-system classes — keep it. Add: "Latest" badge styling fix if missing. Confirm `status-pill` classes are correct.

**`catalog_admin/detail.html`**
- Command bar: "Catalog Admin → v{version}" breadcrumb | "Back to catalog list" ghost button
- Side rail: `global_nav_items("catalog_admin")`
- Main: accordion tree — `<details><summary>` per section, question count badge in summary. Expanded: question rows with code, text (truncated), response type pill, required `*` indicator. Use `<table class="data-table">` inside each `<details>`.

**`catalog_admin/upload.html`**
- Command bar: "Catalog Admin → Upload" breadcrumb | "Cancel" ghost button (links to `/admin/catalog`)
- Side rail: `global_nav_items("catalog_admin")`
- Existing form fields and buttons keep their existing structure — just add the shell.

#### Tests (`test_catalog_admin_routes.py`)

- List: `<nav>` present, "Catalog Admin" link is active
- Detail: accordion sections present, question count badges
- Upload: nav present, cancel link goes to list
- No `global_nav` block missing from any catalog admin page (assert `<nav class="side-nav">` in response body)

---

## 6. Sequencing and integration

1. Coordinator creates `_nav.py` + three CSS stubs + links in `base.html` (DONE).
2. Launch UX-4a, UX-4b, UX-4c, UX-4d together — four agents, disjoint file sets.
3. On landing, run the full verification gate. Browser suite must be **≥ 38 passing** with no regression in matrix or journeys.
4. Two items UX-4a cannot do itself (they touch templates outside its set — UX-2's `hub.html` and UX-1's `section.html`):
   - Add "Back to application" link from hub to workspace (workspace.html owns this, UX-4a does it)
   - The questionnaire breadcrumb's "Intake overview" link already points to hub (UX-1 done this)
5. Update `STATE.md` with a dated checkpoint (integrator only — agents do not touch it).

## 7. Explicitly out of scope for UX-4

- The 9 response types still in `PENDING_COVERAGE` in the matrix (UX-5 work).
- Drag-and-drop file zones (needs `app.js` additions beyond UX-4c's filter scope — UX-5).
- Live "Accept selected (N)" counter following checkbox ticks (same).
- Changing the readiness URL prefix from `/intakes/{id}` to `/applications/{app_id}/intakes/{id}` — UX-4b resolves the app via a DB lookup instead, which is a non-breaking change.
- Any change that writes a canonical answer without explicit user action.

## 8. Design reference

See `_data/ux_mockups/full_ui_consistency_mockup.html` — open locally in a browser.
Screen numbering: 1=App list, 2=Create, 3=Workspace, 4=Edit, 5=Hub (done), 6=Questionnaire (done), 7=Sources (done), 8=Bulk review (done), 9=Import detail, 10=WaveUtil list, 11=WaveUtil detail, 12=Readiness status, 13=Freeze success, 14=Snapshot, 15=Catalog list, 16=Catalog detail.
