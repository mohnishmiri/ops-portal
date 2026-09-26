# Open Questions

## Q-001: Baseline Permission

- Status: RESOLVED on 2026-09-24; user resolved the merge and requested continuation.
- Scoped Git verification at 13:34:20-05:00 reports zero unmerged paths; staged changes remain preserved. See EV-REPO-003.
- Continue read-only review. Runtime/service/database boundaries still require explicit verification and permission; no merge resolution was performed by the investigation.

## Q-002: Intake Workbook

- Status: RESOLVED AS OUT_OF_SCOPE_BY_USER (D-010).
- The user accepts intake as working and does not need workbook/intake analysis. Stage 07 is excluded, not blocked on a missing path.
- Do not request or inspect workbooks/importers to verify intake correctness. Topology consumption of already reviewed canonical data remains in scope.

## Scope Limitation: Existing Tests

- Status: OUT_OF_SCOPE_BY_USER, not an unanswered request for access.
- The user excluded tests/ entirely. Do not inspect, execute, import, or cite the suite or use old suite results as current review evidence.
- Propose future validation without claiming existing test coverage or exact existing test locations were verified.

## Q-003: Diagram Applicability

- Status: TARGET ROLE RESOLVED BY USER (D-009).
- The supplied two-page output is the expected target to reproduce for the specific migrating application, used as an example. Do not turn its structure into universal requirements for other applications.
- Per-page environment/site meanings and guide-rule applicability still need evidence; target-role confirmation is not permission to invent missing canonical values.