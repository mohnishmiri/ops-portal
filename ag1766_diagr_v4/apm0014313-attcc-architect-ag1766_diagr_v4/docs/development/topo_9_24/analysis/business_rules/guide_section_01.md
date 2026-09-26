# Guide Section 01: ATT Internal Interfaces

Evidence: EV-DOCX-002. Source: `Topology Guide.docx`, blocks 1-5, plus the two embedded images referenced by blocks 2 and 5. The DOCX hash remained unchanged. Images were reviewed locally; no external relationships were followed.

## Verified Text Rules

- Section label: `ATT Internal Interfaces`.
- Source selector: Interface-sheet column G.
- Candidate values named by the guide: Midrange, Hybrid, Private, Conexus, and OnPrem.
- The prose says matching interfaces are listed in this section for **Inbound connectivity**, grouped by columns N and R.
- Arrow color coding is also based on grouping by columns N and R.

These are source-document claims. Intake/import correctness is out of scope by D-010; topology must consume the already reviewed canonical equivalent of these fields rather than reading a workbook during rendering.

## Image Evidence

- Block 2 contains the application-specific visual example for the ATT Internal Interfaces area.
- Block 5 contains a visible arrow-color legend. The legend includes entries for both `IN` and `OUT` direction values.
- The images establish intended presentation candidates for this application, not canonical facts by themselves. Colors must remain tied to an approved accessible legend and deterministic field mapping.

## F-RULE-001: Direction Contract Is Internally Ambiguous

- Kind: FACT; verification: VERIFIED against extracted text and locally viewed embedded image; severity: High for semantic correctness.
- Conflict: block 3 limits the listed connectivity to inbound, while the block-5 legend visibly distinguishes both IN and OUT.
- Risk: an implementation may omit legitimate outbound flows, include unapproved outbound flows, or assign colors/directions inconsistently while still appearing visually plausible.
- Required decision: approve one explicit rule for this application and reusable policy: inbound-only, or both directions with exact inclusion and color semantics. Preserve unknown/unsupported direction as a review blocker or typed exclusion; never infer direction from arrow geometry alone.
- Proposed deterministic mapping boundary: reviewed canonical interface fields corresponding to source category (column G), direction/group fields (columns N/R), scoped endpoint identity, and provenance. Rendering consumes the approved projection; it does not reopen the intake workbook.
- Alternatives considered:
  - Inbound-only: matches prose but leaves the OUT legend unexplained.
  - Both directions: matches the legend but departs from the prose unless explicitly approved.
  - Presentation-only OUT legend: possible, but must be stated; otherwise it is misleading.
- Acceptance proposal: a small application fixture with one IN, one OUT, one unknown direction, and each approved column-G category produces exactly the approved node/edge set and legend mapping. Unknown values remain visible as gaps/exclusions. This is a proposed future check, not an executed test.

## Open Items

- Exact page/region binding in the profile is not yet correlated to this guide image.
- Exact N/R value-to-color pairs should be transcribed as a reviewed policy only after the direction conflict is resolved and accessibility is assessed.
- The expected two-page target is authoritative for this application by D-009, but it does not resolve contradictory guide prose automatically.