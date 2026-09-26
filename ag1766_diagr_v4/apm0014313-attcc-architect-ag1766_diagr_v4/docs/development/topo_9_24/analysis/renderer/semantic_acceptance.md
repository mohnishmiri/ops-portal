# Application Target Semantic Acceptance

EV-DRAWIO-007; S10-C02. Redacted safe XML comparison of the supplied one-page input and user-confirmed two-page expected target. Source hashes remained unchanged and no raw cell IDs/labels were persisted.

## Measured Baseline

| Measure | Input | Target page 1 | Target page 2 |
| --- | ---: | ---: | ---: |
| Total cells | 141 | 244 | 262 |
| Vertices | 98 | 179 | 184 |
| Edges | 41 | 63 | 76 |
| Shared effective IDs with input | n/a | 0 | 0 |
| Target vertices without style | n/a | 0 | 0 |
| Target edges without style | n/a | 0 | 0 |

The two target pages share 104 effective cell IDs with each other. Draw.io cell identity is therefore page-qualified in this actual target. A document-global ID dictionary overwrites valid cells from one page with the other.

Zero shared IDs between input and target means the expected target was not produced by preserving source IDs. It does not mean the input's semantic/manual content was discarded; correspondence must be established through approved page/region/prototype/label/relationship mappings rather than raw IDs.

## Required Application Acceptance

### Evidence and Authority

- Pin exact input and target hashes, guide/policy version, application/intake identity, approved context decisions and production structural profile hash.
- All application-derived values originate from reviewed immutable authority with scope and provenance. Missing values remain UNKNOWN/blocking; selection never supplies missing source scope.
- LABEL_ONLY and STRUCTURAL results are separately identified; label-only success cannot satisfy this target.

### Semantic Graph

- Expected scoped node and flow sets are specified independently of Draw.io cell IDs.
- Endpoint identity includes namespace/context; guide category (ATT Internal/AWS/Azure) is part of typed flow/region identity.
- Exact duplicates union provenance; materially different direction/protocol/port/category/scope remain distinct.
- Every flow endpoint exists in the same projected graph; off-context/source/unknown resources follow explicit policy.
- Resource and interface provenance reaches report/manifest and review.

### Pages and Regions

- Exactly the two approved target pages are produced for this application, with explicit context/view roles from evidence/profile rather than hardcoded PROD/SITE_A.
- Every page/cell lookup is `(page identity, cell ID)`. The 104 cross-page repeated IDs must not collide or select the wrong cell.
- ATT Internal, AWS, Azure, standard regions and App-driven boxes follow the guide-rule matrix and approved target profile.
- Standard content is preserved separately from variable application resources; example prose is never promoted to fact.

### Visual and Structural Fidelity

- Generated nodes/edges clone exact approved page-scoped prototypes. All target vertex/edge cells are styled; an unstyled generated cell is a failure.
- Icons, styles, arrowheads, fills, fonts, routing metadata, parents and protected manual cells match the governed semantic target.
- Geometry stays within the declared container, avoids overlap/clipping and remains usable at desktop/mobile inspection sizes.
- Protected content equivalence uses explicit profile ownership and semantic signatures, not input/target ID equality.
- Render both pages through an approved Draw.io-compatible renderer and capture screenshots; XML counts alone do not certify appearance.

### Determinism and Capacity

- Same immutable input/profile/base/policies produces identical diagram/report/manifest bytes and receipts across fresh processes/restart.
- Semantic IDs include scope/category/relationship type; reruns do not duplicate generated content.
- Capacity boundary behavior matches the approved profile. CONTINUATION_PAGE must create governed deterministic pages, or the profile must explicitly use BLOCK.
- Measure full capture/database/projection/render/storage/finalization and browser inspection, not projection alone.

### Failure and Delivery

- Malformed base/profile/projection/hash, unresolved required mapping, unknown scope/category, capacity overflow and missing endpoint fail truthfully without partial completion.
- Completion commits exactly DIAGRAM/GAP_REPORT/MANIFEST metadata under atomic lease fencing. Partial/corrupt bundles expose no misleading active inspection controls.
- Download returns receipt-verified bytes with explicit bounded HTTP error contracts.
- Official review revalidates source authority, projection/hash, semantic identity, policies and complete bundle; preview/legacy remain unapprovable.

## Proposed Representative Fixtures

Future authorized verification should cover a linear chain, one-to-many, many-to-one, cycle, orphan, unsupported/unknown, cross-context and cross-account identities, duplicate source rows, retired/stale rows, partial capture failure, multiple typed edges, empty graph, capacity boundary/overflow, failed run and this application-specific target. These are proposed cases; tests/ is excluded and no test result is claimed.

## Acceptance Evidence Package

- Semantic expected/actual node-flow diff with scoped IDs and provenance.
- Per-page protected/generated cell diff, style/prototype audit and overlap/bounds report.
- Diagram/report/manifest bytes and hashes before/after restart.
- Desktop/mobile screenshots of both pages or exported page images, with manual architect signoff for application fidelity.
- Correlated run/phase logs and sanitized failure evidence.
- Explicit list of unverified/open visual decisions; no blanket "looks correct" approval.

## Limits

The supplied target establishes this application's intended result, not a universal template. The current comparison did not render Draw.io, inspect pixels, or determine semantic correspondence for each raw cell. Final visual certification remains pending a repaired production profile/projector/renderer and an authorized standalone journey.