# Candidate Expected-Output Hierarchy

EV-DRAWIO-005; S04-C02. Safe, wrapper-aware parsing left the supplied reference hash unchanged. Only opaque references and label/style digests were persisted.

- Two pages, 506 total cell records.
- Five anonymous mxCells obtain effective IDs from wrapper objects.
- Zero missing effective identities, duplicate effective IDs within a page, dangling parents, or containment cycles were found.
- 59 cells have children across both pages, compared with eight in the input inventory. This is a verified structural difference, not proof that all additional containment is a required generated feature.
- Identity is page-local for this inventory. Do not conflate reused IDs across pages or infer account/environment/site meaning from page placement.
- Protected/generated-region authority and intended correspondence with the input require profile/guide/applicability analysis. Valid containment alone does not establish correct or approved topology.

Next: inspect connection references and point anchors on the expected-output pages before making any edge comparison.