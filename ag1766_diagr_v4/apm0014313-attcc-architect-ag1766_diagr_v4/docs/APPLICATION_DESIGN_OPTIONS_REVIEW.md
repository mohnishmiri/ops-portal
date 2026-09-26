# Application-wide design options review

## Decision summary

Three complete, isolated UI directions are available under `/design-options`.
They cover the same 19 primary screen patterns and preserve equivalent-page
switching between A, B, and C. No concept action writes production data and no
production route has been replaced.

Option B, the compact operational experience, is recommended. Migration Intake
is primarily a repeated operational workflow: users scan registers, review
proposals, complete long questionnaires, and compare readiness details. Option B
uses laptop space most efficiently while retaining the same accessible shared
components and workflow coverage as A and C.

## Route and screen inventory

| Area | Production route family | Preview screen | A/B/C |
| --- | --- | --- | --- |
| Portfolio | `/applications/` | Applications | Covered |
| Portfolio | `/applications/{id}` | Application workspace | Covered |
| Portfolio | `/applications/new`, edit | Application form | Covered |
| Intake | application intake routes | Intake overview | Covered |
| Intake | questionnaire section routes | Questionnaire | Covered |
| Intake | source/evidence routes | Evidence | Covered |
| Intake | import-run routes | Import detail | Covered |
| Intake | candidate review routes | Proposal review | Covered |
| Registers | interface routes | Interfaces | Covered |
| Registers | interface create/edit | Interface form | Covered |
| Registers | WaveUtil routes | WaveUtil | Covered |
| Registers | WaveUtil detail | WaveUtil detail | Covered |
| Delivery | readiness routes | Readiness | Covered |
| Delivery | snapshot routes | Snapshot | Covered |
| Delivery | topology routes | Topology | Covered |
| Delivery | generation run routes | Topology run | Covered |
| Administration | catalog admin routes | Catalog releases | Covered |
| Administration | catalog release detail | Catalog detail | Covered |
| Administration | catalog publication | Catalog upload | Covered |

The comparison and route index is `/design-options`. A specific equivalent
screen follows `/design-options/{a|b|c}/{screen}`.

## Shared system

The previews use one Jinja component layer, one screen template, centralized
tokens, a shared CSS component system, and one JavaScript behavior module.
Shared patterns include application shell and navigation, breadcrumbs, status
indicators, metrics, search/filter/sort controls, cards, dense tables, forms,
questionnaire accordions, tabs, dialogs, menus, drawers, toasts, progress,
loading, empty, error, validation, confirmation, and success states.

Design tokens now include semantic surface, text, action, focus, layout,
control, and motion values. Preview components contain no inline styles or raw
hex colors. Reduced-motion behavior and visible focus are centralized.

## Options

### A: Balanced SaaS workspace

Best for broad teams and moderate portfolios. It balances orientation,
discoverability, and information density. Its main risk is that medium-density
layouts require more scrolling for expert, high-volume operators. Relative
implementation effort: Medium.

### B: Compact operational experience

Best for frequent operators and larger datasets. Aligned rows, tighter rhythm,
and restrained chrome make scanning and repeated action fastest on laptop
screens. Its main risk is that future metadata must retain strict priority to
avoid clutter. Relative implementation effort: Low.

### C: Curated premium workspace

Best for occasional users and guided review sessions. It provides strong
grouping and progressive disclosure. Its lower density and more expressive
composition cost vertical space and require more implementation effort.
Relative implementation effort: High.

## Application-wide comparison

Scores are 1 (weak) to 5 (strong). For implementation effort, 5 means lower
effort.

| Criterion | A | B | C |
| --- | ---: | ---: | ---: |
| Application consistency | 5 | 5 | 5 |
| Navigation clarity | 5 | 5 | 4 |
| Workflow simplicity | 4 | 5 | 4 |
| Visual clarity | 5 | 4 | 5 |
| Ease of scanning | 4 | 5 | 4 |
| Information density | 4 | 5 | 3 |
| Form usability | 5 | 5 | 5 |
| Accessibility | 5 | 5 | 5 |
| Desktop efficiency | 4 | 5 | 3 |
| Cross-browser robustness | 5 | 5 | 4 |
| Component reuse | 5 | 5 | 5 |
| Maintainability | 5 | 5 | 4 |
| Implementation effort | 4 | 5 | 3 |
| Modern SaaS appearance | 5 | 4 | 5 |
| **Total** | **65** | **68** | **59** |

## Validation evidence

- Route matrix: 57 option/screen combinations return HTTP 200, render exactly
  one `h1`, and preserve equivalent A/B/C links.
- Integrated Chromium: all options have no document overflow at 1280x720,
  1366x768, 1440x900, and 1920x1080 on the Applications screen; all 57 routes
  passed the shared overflow check at the integrated browser viewport.
- Integrated Chromium: search, menu, confirmation dialog, state switching,
  form validation, questionnaire drawer, direct URLs, equivalent option
  switching, and back/forward navigation passed. No console or page errors were
  observed across representative screens in every workflow area.
- `python -m pytest tests/unit/web/test_design_options.py -q`: 3 passed.
- Focused Ruff and mypy: passed.
- `node --check src/migration_intake/web/static/js/design-lab.js`: passed.
- `git diff --check`: passed.
- Automated Python Playwright tests are authored in
  `tests/browser/test_design_options.py`; they require the optional browser
  environment and were not executed in this session.
- Firefox, WebKit, and actual Safari were unavailable. No coverage is claimed
  for those engines. The progress implementation avoids typed CSS `attr()` to
  reduce known Safari compatibility risk.

## Production integration gate

Stop at review. Obtain product approval for one complete direction before
adapting production templates. If Option B is approved, migrate shared tokens
and components by workflow area, retain route/service boundaries, and run each
existing browser journey after its corresponding screen family changes.
