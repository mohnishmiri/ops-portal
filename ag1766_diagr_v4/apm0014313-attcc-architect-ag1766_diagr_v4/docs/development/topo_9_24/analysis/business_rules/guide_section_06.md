# Guide Section 06: Application-Driven Box

EV-DOCX-007; blocks 20-22 and image6.png. The guide explicitly says the box's data should be picked up from `App`. This is distinct from nearby standard-content captions.

- VERIFIED prose: application data is the source; the fragment does not specify exact canonical field IDs or a complete selection/grouping rule.
- Qualified local OCR: recognizable NAS, details, EC2 and list-related text; another short label is not reliably transcribed. Preserve the raw OCR without silently correcting it into a product/service name.
- INFERENCE: the illustration contains application-dependent list/detail placeholders. Exact resource types, cardinality, ownership and scope still require the approved topology mapping/profile.
- Proposed boundary: consume existing reviewed canonical application/resource facts from immutable capture/snapshot data; support repeated details where the approved mapping requires them. Do not fill these lists from reusable example text.
- Missing data remains UNKNOWN or a typed gap/exclusion, not an invented empty list or `No` answer. List membership needs scoped identity/provenance, not OCR labels.
- The ambiguity is in the topology-consumption contract, not a finding that intake import is broken. Intake/XLSX correctness remains assumed working by D-010.
- Next policy work: identify the exact approved mapping for this region, required/optional fields, repeated-item identity, and protected/static versus variable content. No production edit or runtime claim is made here.