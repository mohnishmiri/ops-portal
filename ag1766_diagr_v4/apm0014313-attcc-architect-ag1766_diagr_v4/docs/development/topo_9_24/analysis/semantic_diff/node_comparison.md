# Descriptive Node and Hierarchy Comparison

EV-DIFF-001; S05-C01. Generated only from the persisted redacted hierarchy artifacts. The prior stage-boundary check found no inspected source changes. Q-003 remains unresolved, so these differences are descriptive and are not approved target requirements.

Scope update after this chunk: D-009 confirms the two-page output as the expected target for this specific application. That supersedes the original target-role uncertainty above; label correspondence and per-page context limitations remain. D-010 excludes intake/XLSX analysis.

| Measure | Input | Candidate output page 1 | Candidate output page 2 |
| --- | ---: | ---: | ---: |
| Vertex cells | 98 | 179 | 184 |
| Unlabeled vertex cells | 17 | 34 | 34 |
| Shared normalized-label groups with input | n/a | 34 | 34 |
| Unique label candidates, one occurrence each side | n/a | 21 | 15 |
| Ambiguous repeated-label groups | n/a | 13 | 19 |

- All pages have internally valid effective-ID/parent references in the inspected category. This does not prove correct AWS/application topology.
- More pages/cells and repeated/unlabeled vertices make raw cell count or label-only matching insufficient as an acceptance oracle.
- Matching normalized labels cannot identify the same resource across unknown applications/accounts/environments/sites. No node candidate is marked an approved resource identity.
- Exact label/style hashes and opaque references permit later review without exposing raw identifiers. Differences in a hash are not automatically business-rule violations.
- Do not infer that output page 1 corresponds to a particular input environment or that page 2 is disaster recovery. That requires source/guide applicability evidence.

Proposed comparison contract: combine approved scoped canonical resource identities, explicit profile mappings, and typed relationship semantics. Retain duplicate/unknown candidates for review rather than collapsing them by label.