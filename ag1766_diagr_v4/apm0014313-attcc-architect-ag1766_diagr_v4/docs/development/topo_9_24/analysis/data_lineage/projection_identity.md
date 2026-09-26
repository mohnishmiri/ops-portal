# Projection Identity, Scope and UNKNOWN Handling

EV-PROJ-001; S09-C01. Static inspection of scope.py, guide_policy.py and strict_projection.py, correlated with prior route/capture and guide evidence. No runtime probes or excluded-suite evidence.

## Intended Contracts

- Scope states explicitly include KNOWN, GLOBAL, UNKNOWN and NOT_APPLICABLE for persisted resource scope keys.
- Resource persistence hashes lifecycle/environment/site/tier with UNKNOWN preserved for absent dimensions.
- Explicit ScopeSelection requires application, intake, at least one unique environment/site context and a view variant.
- Target resources with unknown environment/site create blocking projection issues; confirmed reviewed relationships are filtered to selected/shared endpoint IDs.
- Interface normalization accepts INBOUND, OUTBOUND and BIDIRECTIONAL; unknown direction, missing endpoint and invalid port become blocking exclusions. The approved policy therefore supports both IN and OUT semantics, while the guide's inbound-only prose remains a documentation conflict.
- Flow exact-duplicate identity includes endpoint direction/type/protocol/port/scope and unions provenance.

## F-PROJ-001: Missing Interface Scope Is Replaced With Requested Context

- FACT / VERIFIED static; severity Critical for diagram correctness and cross-context integrity.
- Interface `PROJECTION_FIELDS` contains no environment, site, account or region fields.
- Semantic projection nevertheless reads those keys. For a single selected context, absent row values fall back to `application_scope.environment/site_id`, and scope state becomes `EXPLICIT`.
- The current UI sends hidden PROD/SITE_A and the route builds exactly one context (EV-FLOW-001/002). Thus this active path labels every otherwise accepted interface flow as explicit PROD/SITE_A even though the captured interface row does not establish that scope.
- Multi-context selection does not distribute flows: absent scope falls back to null with state UNKNOWN, so each flow is blocked as UNKNOWN_FLOW_SCOPE.
- Impact: the single-context preview invents certainty; a true two-page/multi-context application target cannot assign interface flows deterministically from current capture fields.
- Proposed change: add reviewed canonical scope fields or an explicit authorized scope-decision record per interface/flow. Missing dimensions remain UNKNOWN and block/route to review; never inherit selected context as source evidence. Selection filters known facts, it does not manufacture their scope.
- Acceptance proposal: missing scope never becomes EXPLICIT; known matching scope appears only in its context; known nonmatching scope is excluded; multi-context flows partition deterministically; global/not-applicable semantics are explicit.

## F-PROJ-002: Endpoint Node Identity Omits Scope

- FACT / VERIFIED static; severity High.
- Semantic nodes use a dictionary keyed only by counterpart ID and `setdefault`, while flows include ProjectedScope.
- If the same counterpart ID occurs in multiple scoped flows, only the first endpoint node survives; later flows retain their own scopes but refer to that same unscoped node ID.
- Scope contracts elsewhere require context for non-global resources, so this endpoint identity is weaker than the canonical resource identity model.
- Impact: account/region/environment/site variants can collapse, make edge/node scope disagree and create downstream generated-ID collisions or misleading topology.
- Proposed change: define canonical interface endpoint identity from stable counterpart ID plus approved scope dimensions/namespace, or create a scoped endpoint key with display identity separate. Preserve exact duplicates only when all semantic identity dimensions match.

## F-PROJ-003: Guide Region Category Is Dropped Before Rendering

- FACT / VERIFIED static; severity High for reproducing the application target.
- Guide policy computes `ApprovedFlow.group` from interface location aliases, but ProjectedFlow has no group/category field. The flow constructor and dedup key omit it.
- The guide requires distinct ATT Internal, AWS and Azure regions. Internal source values named in the guide include Midrange, Hybrid, Private and Conexus; current aliases do not map those values, although OnPrem variants map to INTERNAL.
- Unknown location produces group UNKNOWN but no exclusion, and then even that group is discarded.
- Impact: downstream rendering cannot deterministically choose the required target region from persisted projection data. Otherwise identical AWS/Azure/internal flows may deduplicate when endpoints/protocol/port/scope match.
- Proposed change: make a versioned typed region/category part of flow identity and persisted projection, expand aliases only through approved policy, and block unknown mandatory category rather than dropping it. Tie category-to-profile-region mappings to profile/version hashes.
- Acceptance proposal: each approved source category maps to exactly one expected region; unknown/unsupported category is a typed blocker; same endpoints in different regions remain distinct; no sensitive free text becomes a label.

## F-PROV-001: Resource Node Provenance Reads The Wrong Shape

- FACT / VERIFIED static; severity High for traceability.
- Preview capture stores `provenance_references` at the resource top level (EV-FLOW-002).
- Semantic projection reads `resource.get("revision", {}).get("provenance_references", [])`. No `revision` wrapper exists in the captured shape.
- Result: ProjectedNode provenance is empty even though confirmed revision provenance was captured.
- Proposed change: define one typed resource contract and consume its top-level provenance, with strict shape validation. Persist lineage through projection, renderer manifest/report and review.
- Acceptance proposal: every generated application-derived resource node cites the exact captured revision provenance; malformed/missing required provenance blocks instead of silently becoming empty.

## F-PROJ-004: Semantic Resource Nodes Ignore Selected Context

- FACT / VERIFIED static; severity High, subject to renderer-consumption confirmation in S10.
- Partition resources are filtered to confirmed TARGET records matching each context; shared globals are separate.
- `_project_semantic_graph` independently loops over every document resource and adds a node without lifecycle, review-state or selection filtering.
- Impact: persisted `nodes` can include source/off-context/unknown-scope resources that are absent from selected partitions. If structural rendering consumes this list directly, selection boundaries can leak into output.
- Proposed change: construct semantic nodes from the explicitly selected/shared sets, with an intentional typed path for any SOURCE context needed by the view. Validate that every flow endpoint exists in the same projected semantic graph.

## Other Static Observations

- ProjectedScope.state is a free string rather than ScopeState, allowing values such as EXPLICIT/MULTI_CONTEXT outside the persistence enum.
- Strict persisted-projection loading validates envelope fields and hashes but only shallowly validates node/flow scope contents, endpoint existence, uniqueness and semantic identity.
- Application node scope uses the sole selected context or an unscoped MULTI_CONTEXT state; per-page application anchors need explicit target design.
- Facts from mapped answers are copied into every selected context. This is appropriate only for truly application-global facts; mappings need scope semantics if context-specific answers are introduced.
- Relationship types are allowlisted and reviewed in the resource graph contract, but the current explicit-link writer gap limits that source in ordinary workflows.

## Target Implication

The user-confirmed two-page target cannot be produced safely by hardcoding PROD/SITE_A or cloning an unscoped flow across pages. The projection must first retain approved category and context identity, then the profile may bind each partition/category to the corresponding protected/generated region. UNKNOWN and conflicting values remain reviewable blockers.