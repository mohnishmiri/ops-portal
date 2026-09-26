# Governed Profile and Token Mapping

EV-PROFILE-001; S09-C02. Five profile files inspected: loader plus the complete synthetic label-only manifest/slots/mappings/markers. Packaged directory inventory showed `synthetic_label_only` and `synthetic_structural`; structural contracts are deferred to S10. No profile loading or rendering executed.

## Loader Strengths

- Profile selection is explicit by ID; package loading maps ID to a packaged directory.
- Manifest shape is closed over five required components: slots, mappings, markers, issue rules and naming rules.
- Component filenames and SHA-256 values are validated; combined profile identity hashes manifest semantics.
- Every required component must be nonempty; duplicate slot/token/rule IDs are rejected.
- Slot types, unresolved policy, cardinality, page/cell matchers, token paths/scope/transform/defaults and generated-region contracts are typed.
- Filesystem loading rejects a symlink root. Governed BaseDiagramService was previously observed to use packaged `load_profile` by ID.

These checks establish profile integrity, not correctness or approval for a client/application target.

## Actual Label Profile

`SYNTHETIC_LABEL_ONLY` 1.0.0:

- Description and creator metadata explicitly identify it as synthetic/test material.
- Variant LABEL_ONLY; Draw.io target.
- One mandatory slot on page name `Overview`.
- One marker: `{{APPLICATION_NAME}}`.
- One token maps `APPLICATION_NAME` to `$.application.name`.
- No generated regions; no application acronym slot; no ATT/AWS/Azure category, flow, scope, legend, app-detail list or second-page mapping in inspected components.

The route-level fact mappings and strict projection shape are a separate contract. The renderer adapter must reconcile `$.application.name` with projected facts; that behavior is assessed in S10.

## F-PROFILE-001: No Packaged Production Profile For The Application Target

- FACT / VERIFIED static; severity Critical for feature completion.
- The packaged profile directory inventory contains only SYNTHETIC_LABEL_ONLY and SYNTHETIC_STRUCTURAL. The inspected label manifest is explicitly synthetic/test-created. No profile corresponding to the supplied Outposts input and user-confirmed two-page target is present.
- `load_profile` resolves package IDs; an absent application/target profile cannot be selected through this governed loader.
- Impact: upload/compatibility/renderer code may be technically present, but the actual application target has no reviewed, hash-pinned executable layout/mapping contract. Official activation or completion cannot be based on synthetic profile evidence.
- Proposed change: derive a versioned application/template profile from the supplied base, expected target, guide matrix and approved policy. Pin exact pages, protected/generated regions, prototypes, category-region bindings, capacities, labels, selectors and component hashes. Record approval metadata and migration/version strategy; do not repurpose synthetic fixtures as production policy.
- Acceptance proposal: the exact supplied base passes compatibility for the reviewed profile; unrelated/mutated bases fail; deterministic output matches the semantic target; all protected manual cells remain byte/semantic equivalent as designed.

## F-PROFILE-002: Label Profile Cannot Express Required Target Semantics

- FACT / VERIFIED static; severity High.
- The label profile binds only application name. The user-confirmed target and guide require at least two-page/application-specific composition, standard regions, repeated category-filtered interfaces, typed flows, shared legend and application-driven lists.
- A successful label-only render would therefore be a limited marker fill, not reproduction of the target topology. Its test-created profile metadata must not be cited as production capability/certification.
- Proposed change: keep LABEL_ONLY as a separately governed capability, with its claims explicitly bounded. Use a dedicated reviewed STRUCTURAL profile and typed projection fields for topology structure. UI/result labels must state which capability ran.

## H-PROFILE-001: Projection Version Contract Appears Misaligned

- HYPOTHESIS / PARTIALLY_VERIFIED; severity Medium until active call path is inspected.
- The label manifest declares compatible projection versions 3.0.0 through 3.x. StrictProjection schema is 1.0.0. `check_profile_compatibility` compares the supplied projection version to this range.
- If the active renderer passes StrictProjection.schema_version, this profile is incompatible. It may instead treat v3 snapshot schema as the profile compatibility version or bypass this helper; S10 must settle the controlling path.
- Required resolution: define and name one compatibility version contract (authority snapshot, typed projection, or profile API), then enforce it consistently in base inspection and renderer.

## Mapping Requirements From Prior Evidence

A production structural profile cannot compensate for missing semantics in projection. Before region mapping:

1. Preserve known/unknown environment/site/account/region rather than selection fallback.
2. Include approved ATT/AWS/Azure category in flow identity.
3. Preserve scoped endpoint identity and provenance.
4. Map guide standard content separately from application-derived facts.
5. Bind each selected context/category to exact target pages/regions without hardcoded PROD/SITE_A defaults.

Stage 09 is COMPLETE_WITH_LIMITATIONS: projection/profile source is mapped, but the actual structural profile and renderer behavior remain for S10, and no runtime compatibility/render evidence exists.