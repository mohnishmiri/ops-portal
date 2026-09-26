| EV-REPORT-001 | REPORT-001 | report/topology-review-report.html | Assembled source-grounded architecture review, current pipeline assessment, findings summary, target architecture, remediation portfolio and certification gates | Final report | READY_WITH_LIMITATIONS; not runtime certification | REPORT |

| EV-HANDOFF-001 | REPORT-001 | topology_review_workspace/README.md | Lightweight requested handoff workspace pointing to canonical parent evidence without duplication | Handoff index | READY; implementation and runtime certification remain pending | REPORT |
# Evidence Index

Artifact paths are relative to this workspace. Initialization metadata is not semantic topology or release certification.

| Evidence ID | Chunk | Artifact | Source | Description and method | Kind | Reliability | Related work |
| --- | --- | --- | --- | --- | --- | --- | --- |
| EV-REPO-001 | S00-C01 | evidence/repository/baseline.json | Scoped Git metadata | Root/branch/commit, changed paths, unresolved paths, timestamp; excludes both folders and generated workspace from path inventory | Raw metadata | Captured and JSON-validated at 2026-09-24T13:27:34.5687523-05:00 | Q-001; all future baseline checks |
| EV-REPO-002 | S00-C01 | state/inspected_files.json | Seven named references and orientation files | Ten metadata records; seven protected reference hashes unchanged; CSV derivative in inventory/relevant_files.csv | Normalized metadata | Capture and CSV validation passed; semantic content not established | Source freshness; Q-003 |
| EV-SCOPE-001 | S00-C01 | state/decisions.json | User instructions in this conversation | Analysis output root, read-only scope, explicit to_archive/ and tests/ exclusions | Decision record | User-approved scope recorded; other recommendations marked proposed | All stages |
| EV-CHECK-001 | S00-C01 | evidence/repository/initialization_validation.json | Workspace JSON, CSV, artifact references, plan, protected hashes, and scoped Git metadata | Standalone initialization-control validation only | Generated validation receipt | Result and timestamp in artifact; not an application test result | Initialization publication |

Initialization completion requires EV-CHECK-001 to report PASS and STATE.json to name the completed immutable checkpoint. Hashes are not proof of diagram semantics.

Do not add evidence from either excluded directory or treat historical test-suite results as verification for this review.
| EV-REPO-003 | S00-C02 | evidence/repository/resume-2026-09-24.json | Scoped Git metadata and recovery artifacts | Merge resolved; old evidence remains readable and unchanged | Normalized metadata | VERIFIED; not runtime certification | 00 |

| EV-REPO-004 | S01-C01 | inventory/repository_inventory.md | Five configuration/instruction files with locators in artifact | Declared stack, command boundary, and Python-documentation drift | Interpreted static evidence | VERIFIED declarations; runtime unknown | 01 |

| EV-REPO-005 | S01-C02 | inventory/symbols_and_entry_points.md | Five production topology modules with line/symbol locators | Bounded declaration/import inventory, not a runtime trace | Normalized source index | VERIFIED symbol declarations; behavior unverified | 01 |

| EV-REPO-006 | S01-C03 | inventory/verification_boundaries.md | Five recorded production files | Settings/startup/database/logging/readiness boundaries | Interpreted static evidence | VERIFIED source; runtime unverified | 01 |

| EV-DIAG-001 | S01-C03 | evidence/repository/health-diagnostics.json | src/migration_intake/web/health.py | File-specific Pylance undefined literal diagnostic | Normalized diagnostic | VERIFIED editor diagnostic; no HTTP request | 01 |

| EV-FLOW-001 | S02-C01 | evidence/runtime_trace/upload_base.md | Five recorded production files and bounded web symbol search | Actual upload payload/state versus preview eligibility and missing named governance integration | Interpreted static trace | VERIFIED source; browser/runtime not exercised | 02 |

| EV-FLOW-002 | S02-C02 | evidence/runtime_trace/capture_reservation.md | Route, runner, strict projector, v3 contract, and legacy serializer distinction | Immutable preview/official authority path, mapping blocker and T1 handoff | Interpreted static trace | VERIFIED source; no SQL/browser/runtime certification | 02 |

| EV-FLOW-003 | S02-C03 | evidence/runtime_trace/render_inspection.md | Finalization/repository/routes/template/review service | Completion/failure and delivery/review boundaries; source sequence diagram | Interpreted static trace | VERIFIED source conditions; concurrency/runtime not certified | 02 |

| EV-DRAWIO-001 | S03-C01 | evidence/drawio/input_inventory.json | Supplied input Draw.io | Safe structural page/cell inventory with no raw labels or identifiers | Normalized document metadata | VERIFIED counts; semantics/applicability not verified | 03 |

| EV-DRAWIO-002 | S03-C02 | evidence/drawio/input_hierarchy.json | Supplied input Draw.io hierarchy | Opaque cell hierarchy with wrapper identity resolution; analysis in input_hierarchy.md | Normalized structural evidence | VERIFIED structural checks; semantics/authority unverified | 03 |

| EV-DRAWIO-003 | S03-C03 | evidence/drawio/input_connections.json | Supplied input Draw.io edges | Opaque endpoint/point/arrow inventory; no business direction inferred | Normalized structural evidence | VERIFIED structural checks; relationship semantics unverified | 03 |

| EV-DRAWIO-004 | S04-C01 | evidence/drawio/expected_inventory.json | Supplied expected-output candidate | Two-page structural inventory, not approved target semantics | Normalized document metadata | VERIFIED counts; applicability unverified | 04 |

| EV-DRAWIO-005 | S04-C02 | evidence/drawio/expected_hierarchy.json | Expected-output candidate, hierarchy category | Per-page opaque hierarchy with resolved wrapper IDs | Normalized structural evidence | VERIFIED structure; semantic authority unknown | 04 |

| EV-DRAWIO-006 | S04-C03 | evidence/drawio/expected_connections.json | Expected-output candidate connection category | Opaque per-page endpoint and geometry/arrow records | Normalized structural evidence | VERIFIED structure; business meaning/application scope unverified | 04 |

| EV-DIFF-001 | S05-C01 | analysis/semantic_diff/node_comparison.json | EV-DRAWIO-002 and EV-DRAWIO-005 | Descriptive normalized-label candidate comparison with ambiguity retained | Interpreted comparison | VERIFIED descriptive counts; canonical identity/applicability unverified | 05 |

| EV-DIFF-002 | S05-C02 | analysis/semantic_diff/edge_comparison.json | EV-DRAWIO-002/003/005/006 | Qualified edge-descriptor comparison; target role subsequently confirmed in D-009 | Interpreted comparison | VERIFIED descriptor counts; not canonical flow certification | 05 |

| EV-SCOPE-002 | S05-C02 | state/decisions.json | Latest explicit user clarification | Application-specific expected target and intake/XLSX scope exclusion | User scope decision | USER_APPROVED scope; intake correctness assumed, not independently verified | 05 |

| EV-DOCX-001 | S06-C01 | evidence/docx/guide_inventory.json | Supplied guide DOCX package | Document block/image relationship inventory for bounded extraction | Normalized document metadata | VERIFIED structure; prose/image meaning uninspected | 06 |

| EV-DOCX-002 | S06-C02 | evidence/docx/section-001.json | Topology Guide.docx blocks 1-5 and extracted media image1/image2 | ATT Internal Interfaces source/grouping prose and IN/OUT visual-legend conflict | Raw bounded text plus interpreted visual evidence | VERIFIED document evidence; policy decision unresolved | 06 |

| EV-DOCX-003 | S06-C03 | analysis/business_rules/guide_section_02.md | Guide blocks 6-7, original image and local Windows OCR transcription | Verified standard-section prose with explicitly qualified image-label transcription | Interpreted text and qualified OCR | Text VERIFIED; image labels PARTIALLY_VERIFIED; no connection semantics inferred | 06 |

| EV-DOCX-004 | S06-C04 | analysis/business_rules/guide_section_03.md | Guide blocks 8-13, image4 and qualified local OCR | AWS Tier 1 category/direction/grouping rule with illustration limits | Interpreted prose and qualified OCR | Text VERIFIED; visual relationships unverified | 06 |

| EV-DOCX-005 | S06-C05 | analysis/business_rules/guide_section_04.md | Guide blocks 14-16 and shared image2 | Repeated N/R legend instruction; OCR row limitations preserved | Verified prose and qualified OCR | Prose VERIFIED; detailed visual mapping unverified | 06 |

| EV-DOCX-006 | S06-C06 | analysis/business_rules/guide_section_05.md | Guide blocks 17-19 and image5 OCR | Standard-content prose and qualified DNS label candidate | Verified prose and qualified OCR | Prose VERIFIED; resource/visual semantics unverified | 06 |

| EV-DOCX-007 | S06-C07 | analysis/business_rules/guide_section_06.md | Guide blocks 20-22 and image6 OCR | App-sourced variable box and unresolved topology field mapping | Verified prose and qualified OCR | Prose VERIFIED; exact resource/visual semantics unverified | 06 |

| EV-DOCX-008 | S06-C08 | analysis/business_rules/guide_section_07.md | Guide blocks 23-24 and image7 OCR | Standard-region presentation with variable identifier boundaries | Verified prose and qualified OCR | Prose VERIFIED; visual/binding details unverified | 06 |

| EV-DOCX-009 | S06-C09 | analysis/business_rules/guide_section_08.md | Guide blocks 25-27 and image8 OCR | Standard service/API illustration with no inferred access or deployment facts | Verified prose and qualified OCR | Prose VERIFIED; visual/resource semantics unverified | 06 |

| EV-DOCX-010 | S06-C10 | analysis/business_rules/guide_section_09.md | Guide blocks 28-32 and image9 OCR | Azure interface selection/direction/grouping rule | Verified prose and qualified OCR | Prose VERIFIED; visual/resource correspondence unverified | 06 |

| EV-DOCX-011 | S06-C11 | analysis/business_rules/guide_section_10.md | Guide blocks 33-37 and reused legend evidence | Shared legend reuse, with no invented new direction rule | Verified prose and evidence reuse | Reuse/prose VERIFIED; exact visual mapping unverified | 06 |

| EV-DOCX-012 | S06-C12 | analysis/business_rules/guide_section_11.md | Guide blocks 38-39 and image10 OCR | Reusable network label versus unverified application connection facts | Verified prose and qualified OCR | Prose VERIFIED; operational/visual semantics unverified | 06 |

| EV-DOCX-013 | S06-C13 | analysis/business_rules/guide_section_12.md | Guide blocks 40-45 and image11 OCR | Standard box with unresolved conditional-annotation association | Verified prose and qualified OCR | Prose VERIFIED; conditional visual semantics unverified | 06 |

| EV-RULES-001 | S06-C13 | analysis/business_rules/guide_rule_matrix.md | EV-DOCX-002 through EV-DOCX-013 | Guide-wide rule/uncertainty matrix from independently persisted fragments | Evidence synthesis | COMPLETE_WITH_LIMITATIONS; not visual or release certification | 06 |

| EV-DATA-001 | S08-C01 | evidence/database_mapping/topology_schema.md | Current topology ORM and four governing migrations | Table/constraint/evolution map and database-integrity gaps | Interpreted static schema evidence | VERIFIED declarations; deployed parity unverified | 08 |

| EV-DATA-002 | S08-C02 | analysis/data_lineage/canonical_snapshot.md | Application/intake/snapshot/interface models and repositories | Official snapshot and mutable-interface-to-immutable-capture lineage with concurrency/audit gaps | Interpreted static lineage evidence | VERIFIED source; database concurrency/privileges unverified | 08 |

| EV-DATA-003 | S08-C04 | analysis/data_lineage/resource_relationship_revisions.md | Resource/link models, repository/service and migrations 0018/0019 | Revision/CAS/capture lineage and referential/writer gaps | Interpreted static lineage evidence | VERIFIED source; transaction/runtime effects unverified | 08 |

| EV-DATA-004 | S08-C03 | analysis/data_lineage/database_portability.md | Portable types, metadata naming, Alembic environment/config and Compose | Static portability and migration-target/integrity/health boundaries | Interpreted configuration evidence | VERIFIED source; deployed/runtime behavior unverified | 08 |

| EV-PROJ-001 | S09-C01 | analysis/data_lineage/projection_identity.md | Scope, approved guide policy and strict projector modules | Scoped identity, UNKNOWN, category, dedup and provenance behavior | Interpreted static projection evidence | VERIFIED source; renderer/runtime impact partially pending | 09 |

| EV-PROFILE-001 | S09-C02 | analysis/business_rules/token_mappings.md | Profile loader, packaged inventory and synthetic label-only components | Integrity model, actual token/slot capability and missing production target profile | Interpreted static profile evidence | VERIFIED files; runtime structural compatibility pending | 09 |

| EV-RENDER-001 | S10-C01 | analysis/renderer/capabilities.md | Renderer, compatibility inspector and structural profile components | Actual mutation, identity, prototype, overflow and compatibility behavior | Interpreted static renderer evidence | VERIFIED source; runtime/visual target fidelity unverified | 10 |

| EV-DRAWIO-007 | S10-C02 | evidence/drawio/target_preservation.json | Supplied input and application-specific target Draw.io files | Per-page preservation/style/cross-page ID metrics with no raw values | Normalized target comparison | VERIFIED XML metrics; visual/semantic correspondence pending | 10 |

| EV-ACCEPT-001 | S10-C02 | analysis/renderer/semantic_acceptance.md | Persisted source/guide/projector/renderer/diagram evidence | Target-specific semantic, structural, visual, integrity and delivery acceptance gates | Proposed verification contract | PROPOSED gates; not execution evidence | 10 |

| EV-STATUS-001 | S11-C01 | analysis/statuses/run_state_machine.md | Recovery service, run model and topology repository transitions | State machine, fencing strengths, attempt-cap and diagnostic-scope defects | Interpreted static state evidence | VERIFIED source; interleaving/runtime unverified | 11 |

| EV-STATUS-002 | S11-C02 | analysis/statuses/review_ui_integrity.md | Review/legacy services, HTTP routes, run detail template and composition-root handler search | Actual review/delivery wiring and visible-state inconsistencies | Interpreted static web/application evidence | VERIFIED source; HTTP/browser behavior unexecuted | 11 |

| EV-RUNTIME-001 | S12-C01 | evidence/runtime_trace/runtime_authorization.md | Persisted repository configuration and safety evidence | Proposed standalone synthetic execution boundary and stop conditions | Proposed authorization contract | PROPOSED; not executed | 12 |

| EV-DOC-001 | S13-C01 | analysis/implementation_plan_gap/assessment_claims.md | Assessment HTML section 7 and current evidence index | Historical-to-current gap disposition without reusing old test claims | Evidence reconciliation | Current source classifications verified; runtime qualifiers retained | 13 |

| EV-DOC-002 | S13-C02 | analysis/implementation_plan_gap/current_plan.md | Active Markdown/HTML completion records and current evidence index | Current plan claim contradictions, reopening dispositions and synchronization drift | Evidence reconciliation | Current source/doc claims VERIFIED; historical executions unreviewed | 13 |

| EV-ROOT-001 | S14-C01 | analysis/architecture/root_causes.md | Validated findings and evidence EV-FLOW through EV-DOC | Seven root causes, causal chains and remediation ownership order | Evidence synthesis | Source-grounded; runtime-dependent hypotheses retained | 14 |

| EV-OPTION-001 | S15-C01 | analysis/remediation_options/options.md | Root-cause model and project/target constraints | Five-option trade-off analysis and recommended evolutionary direction | Architecture decision proposal | PROPOSED; implementation not approved | 15 |

| EV-ARCH-001 | S15-C02 | analysis/architecture/target.md | Validated current-state/root-cause/options evidence | Proposed component, sequence, state, ER, security, observability, ADR and rollout design | Target architecture proposal | PROPOSED; not implemented or runtime-certified | 15 |

| EV-PLAN-001 | S16-C01 | analysis/remediation_options/first_slice.md | F-PROJ-001 and EV-ARCH-001 | Agent-executable first corrective slice with 42-field contract | Implementation plan proposal | PROPOSED; not approved or executed | 16 |

| EV-PLAN-002 | S16-C02 | analysis/remediation_options/slice_dependencies.md | EV-ROOT-001, EV-ARCH-001 and EV-PLAN-001 | Full slice portfolio, dependency graph, critical path, releases and stop/go gates | Implementation portfolio proposal | PROPOSED; detailed slices/implementation pending | 16 |

| EV-PLAN-003 | S16-C03 | analysis/remediation_options/slices/SL-PROJ-002.md | F-PROJ-001 and target architecture | Reviewed interface scope authority slice | Implementation plan proposal | PROPOSED | 16 |

| EV-PLAN-004 | S16-C04 | analysis/remediation_options/slices/SL-PROJ-003.md | Projection findings and scope-authority contract | Projection v2 slice specification | Implementation plan proposal | PROPOSED | 16 |
