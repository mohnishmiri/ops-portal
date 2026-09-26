# Renderer and Structural Profile Capabilities

EV-RENDER-001; S10-C01. Static inspection of the renderer, compatibility inspector and complete synthetic structural manifest/slots/mappings. No rendering executed and no target profile exists.

## Positive Contracts

- Label rendering checks approved compatibility, exact base hash, compatibility base/profile hashes and loaded profile identity.
- Projection hash is recomputed before token adaptation; conflicting fact values across partitions fail.
- XML uses the bounded safe parser; slot/cell/marker references are checked before mutation.
- Marker writes are allowlisted by slot and profile marker; unresolved mandatory values fail.
- Structural mode requires a STRUCTURAL profile, runs label mutation first, sorts nodes/flows deterministically and fails if an edge endpoint was not generated.
- Compatibility pins base inventory/hash, profile/selection/capability/parser policy, selected page mapping, slot matches and issues.
- Selected contexts must map to distinct named pages.

These controls do not establish target fidelity; current packaged structural data is explicitly synthetic.

## Actual Synthetic Structural Profile

- One page: `Overview`.
- One mandatory application-name marker/token.
- One generated region selecting top-level `nodes` and `flows`.
- Capacity 100, row capacity 25; declares CONTINUATION_PAGE with `Overview {page}`.
- Container/prototype IDs are synthetic numeric cells; edge prototype ID equals the declared container ID.
- Profile metadata says synthetic-test and compatibility 3.0.0..3.x.

It cannot represent the user-confirmed two-page application target or category-specific ATT/AWS/Azure regions.

## F-PROFILE-003: Declared Projection Compatibility Is Not Enforced On The Active Path

- FACT / VERIFIED static; severity High.
- Loader provides `check_profile_compatibility` for projection version and required resource kinds.
- `inspect_base` has no projection version/hash/resource-kind input and never calls that function. It checks profile variant/region declarations and diagram shape only.
- `render_label_only`/`render_structural` validate hashes/slots but do not compare profile min/max projection version or required resource kinds.
- Therefore the synthetic manifest's declared 3.x range is not evaluated against StrictProjection 1.0.0; H-PROFILE-001 is resolved as an unenforced contract rather than an observed compatibility failure.
- Proposed change: make a single typed compatibility gate consume exact projection schema/hash/resource kinds and persist its result with base/profile/selection/capability. Renderer must revalidate the same pins.

## F-RENDER-001: Declared Prototypes Are Verified But Ignored

- FACT / VERIFIED static; severity Critical for reproducing the visual target.
- Compatibility requires container, node prototype and edge prototype IDs to exist.
- Structural rendering never loads/clones either prototype. It constructs new `mxCell` elements with ID/value/vertex-or-edge/parent and basic geometry only; no style is copied.
- Generated node labels are raw semantic IDs truncated to 80 characters. Edges contain protocol/port text only.
- Impact: generated cells cannot inherit the target's AWS icons, fonts, fills, borders, arrows, routing, metadata or accessibility conventions. Prototype checks create false confidence without governing mutations.
- Proposed change: clone exact approved prototypes, generate new IDs, replace only governed label/endpoints/geometry attributes, retain style/metadata, and audit every changed attribute. Validate that prototypes belong to the declared page/region.

## F-RENDER-002: Generated Identity Omits Scope, Category And Relationship Type

- FACT / VERIFIED static; severity High.
- Node ID hash uses only `node_id`; node lookup also keys only semantic node ID.
- Edge ID hash uses source, target, direction, protocol and port. It omits scope, category/guide region and relationship type.
- Combined with EV-PROJ-001, scoped endpoint variants and same-flow tuples in different guide regions can collapse or generate duplicate IDs, and endpoint lookup cannot distinguish scoped nodes.
- Proposed change: define one canonical persisted semantic identity including scoped endpoint keys, typed relationship, category/region and applicable protocol/port/direction. Renderer hashes that identity; display labels remain separate.

## F-RENDER-003: CONTINUATION_PAGE Is Declared But Not Implemented

- FACT / VERIFIED static; severity High for large graphs/two-page behavior.
- Loader requires a continuation naming pattern when overflow policy is CONTINUATION_PAGE.
- Renderer does not branch on overflow policy. If either node or flow count exceeds page capacity, it raises `Generated region ... exceeds page capacity`.
- It never clones a page/region or uses continuation_page_pattern.
- Proposed options: implement governed continuation-page cloning with deterministic page IDs/names/profile regions and protected content rules, or change the approved profile to BLOCK and document the limit. Do not claim continuation capability until executable/visual evidence exists.

## F-RENDER-004: Region Cell Checks Are Not Page-Scoped

- FACT / VERIFIED static; severity Medium.
- Compatibility builds one `cells_by_id` dictionary across every page and checks container/prototype existence globally, not on `region.page_name`.
- Slot lookup also dereferences page cell IDs through that global dictionary. Structural renderer similarly builds one global cell-ID dictionary before selecting the region page.
- If IDs repeat across pages, later cells overwrite earlier entries; a region may pass because required IDs exist on another page. The target has two pages, so page-qualified identity is required even if its current IDs happen to be globally unique.
- Proposed change: key every compatibility/renderer cell reference by `(page identity, cell ID)` and require container/prototypes to belong to the exact region page and expected hierarchy.

## Additional Behavioral Limits

- Structural region selectors read only top-level projection fields. Current profile has one region, so all nodes/flows are placed together; guide categories/partitions cannot select separate target regions.
- Both node and edge count are compared independently to one page_capacity, not region-specific node/edge capacities.
- Grid placement uses fixed width/height and row capacity without bounding actual container geometry or collision with protected cells.
- The renderer rebuilds XML with ElementTree; byte equality with the source is not expected. Semantic preservation must be checked explicitly for protected pages/cells/styles/parents/edges.
- Result report/manifest captures mutation counts and hashes but not a complete protected-cell equivalence proof.
- Structural renderer catches all exceptions into failed output; finalization handling of failed/status-invalid output has separate gaps (F-PIPE-002).

## Target Direction

A production profile for this application must declare two exact pages and category-specific generated regions, with scoped selectors and cloned prototypes. The renderer must consume repaired projection semantics first; a profile cannot recover category, scope or provenance that projection discarded.