# Production Topology Entry Points

Evidence: EV-REPO-005. Chunk S01-C02 inspected declaration/import matches in exactly five production files. Neither excluded folder was searched. This is a navigation index, not proof of runtime call ordering or correctness.

## HTTP Surface

Source: src/migration_intake/web/routes/topology.py.

| Symbol | Line | Surface requiring body inspection |
| --- | --- | --- |
| get_topology_service | 87 | Existing generation service dependency |
| get_topology_review_service | 104 | Review service dependency |
| get_governed_preview_runner | 110 | Governed runner dependency |
| topology_landing | 166 | Base/run listing and eligibility |
| upload_base_diagram | 231 | Upload validation and persisted base state |
| generate_topology | 298 | Legacy generation and feature/capability containment |
| generate_governed_preview | 364 | Non-authoritative generation route |
| view_generation_run | 439 | Run detail and artifact inspection state |
| review_generation_run | 510 | Approval gate and review service boundary |
| download_diagram / download_manifest / download_report | 559 / 606 / 635 | Authorization and verified artifact retrieval |
| _read_upload_with_limit | 684 | Bounded upload handling |
| _require_topology_generation_enabled | 703 | Feature flag enforcement |

The route module imports both topology_generation and topology_runner services plus TopologyReviewService. Do not assume that the legacy and governed paths provide equivalent authority or artifact integrity.

## Application Orchestration

Source: src/migration_intake/application/services/topology_runner.py.

- PersistedLabelRenderer, line 75; __call__, line 90: inspect immutable-input loading and renderer selection.
- GovernedTopologyRunner, line 187: run_official (211), run_preview (271), _capture_preview (309), _project_reserve_render (422).
- Capture helpers for answers/resources/relationships/WaveUtil are declared at 664, 705, 751, 780. Their existence does not establish approved-data filtering.
- Imports include topology_finalization, TopologyRepository, contracts, profiles, renderer, and strict_projection. Exact call order and transaction boundaries remain for S02.

## Projection and Rendering

- src/migration_intake/topology/strict_projection.py declares StrictFactMapping, ProjectedFact, ProjectedScope, ProjectedNode, ProjectedFlow, ProjectionExclusion, ProjectionPartition, and StrictProjection.
- project_v3_snapshot (145), strict_projection_document (295), serialize_strict_projection (321), load_strict_projection_document (332), _resources_for_context (503), _project_semantic_graph (547), and _project_relationships (681) are the next semantic boundaries to inspect.
- src/migration_intake/topology/renderer/core.py declares parser limits, RenderInput/RenderOutput/RenderManifest, parse_diagram_safely (461), _governed_projection_data (599), render_label_only (676), _generated_cell_id (832), render_structural (837), and legacy render_diagram (1224).
- LABEL_ONLY versus STRUCTURAL behavior, safe parsing, exact endpoints, scoped identities, prototype preservation, and output status must be checked in bodies, not inferred from names.

## Persistence and Concurrency

Source: src/migration_intake/persistence/repositories/topology.py, TopologyRepository (35).

- Base artifact/compatibility persistence and review: create_base_artifact (41), create_topology_compatibility (76), mark_base_compatible (93), review_base_artifact (118).
- Immutable input/capture and reservation: create_topology_capture (163), create_topology_input (170), get_or_create_topology_input (180), reserve_generation_run (191).
- Leases/finalization: claim_generation_run (285), transition_leased_generation_phase (307), finalize_generation_run (332), fail_storing_generation_run (373), fail_leased_generation_run (390).
- Recovery/review: claim_expired_generation_run (410), mark_recovery_failed (450), review_generation_run (487), supersede_generation_run (534).
- Shared mutation helpers: _fail_leased_run (692), _next_attempt_number (726), _reserved_run (735), _cas_run (746), _cas_update (767).

A helper named CAS and a lease parameter are not proof of an atomic fenced update. Verify SQL predicates and transaction ordering during the concurrency chunk. Likewise, review method names do not prove complete immutable authority validation.

## Next Local Reads

1. Production settings/main/logging/database setup for permissions and runtime boundaries.
2. Upload route, landing template, existing upload service, and governed-base service.
3. Preview route/runner to immutable capture/projection/reservation.
4. Finalization/repository/download/detail template contracts.

No new architecture defect is concluded from this declaration inventory alone. Existing-suite coverage and runtime results remain outside the evidence gathered here.