# Project AWS OutPost Migration
# Standalone Architecture Review Handoff: Evidence Upload, Document Extraction, Questionnaire Prefill, and AI-Assisted Mapping

**Prepared:** 2026-09-05  
**Document purpose:** Supply a complete, self-contained architecture briefing to a fresh principal architect, technical architect, or AI architecture reviewer who cannot access the original source documents, repository, spike implementation, mockup, question catalog, database schema, or earlier design records.  
**Review stage:** Design exploration before production implementation.  
**Implementation status:** No production questionnaire application or AI-assisted document-ingestion capability has been implemented. A limited topology-generation spike and a static UI prototype have been completed, but this handoff does not assume the reviewer can inspect either one.  
**Requested reviewer behavior:** Review the problem and proposed architecture independently, challenge assumptions, compare viable options, identify missing controls, and recommend a concrete target architecture and phased implementation approach. Do not assume the recommendation in this document is final.

---

## 1. Executive summary

The project is building an internal application-migration intake platform for AWS Outposts migration work. For each enterprise application being migrated, application teams, owners, analysts, and architects must collect and reconcile a large body of information from existing questionnaires, portal records, spreadsheets, Word documents, PowerPoint templates, architecture diagrams, tickets, and direct human answers.

Today, much of that information is scattered across multiple artifacts. The same fact may be copied into several documents, may use different terminology in each source, may be stale, may have incomplete provenance, or may conflict with another source. Architects currently spend substantial effort locating information, manually copying it into deliverables, asking application teams repetitive questions, and deciding which values are sufficiently trustworthy to use.

The original UI concept was a structured, per-application questionnaire backed initially by SQLite. Users would create an application intake, upload evidence, answer missing questions, maintain structured registers such as servers and interfaces, resolve conflicts, approve sections, and generate migration deliverables from a reviewed canonical snapshot.

The redesign explored in this session expands evidence upload from a passive attachment feature into a first-class ingestion workflow. An architect who has already collected information in existing source documents should not have to retype every answer into the UI. Instead, the architect should be able to upload or reference those documents. The system should identify the source type, extract facts and register rows, map them into the standard questionnaire model, validate them, reconcile them against existing evidence, and present proposed changes and findings for human review.

The system must not allow deterministic parsers or an AI model to silently create approved answers. Uploaded documents produce **candidate facts**, not canonical truth. The reviewer or assigned owner accepts, edits, rejects, defers, or requests clarification. Accepted candidates create append-only answer or register revisions. Only an explicitly approved and immutable canonical intake snapshot may feed Topology, Architecture Design Specification (ADS), or Detailed Design Document (DDD) generation.

Three broad ingestion architectures are under consideration:

1. **Deterministic adapters only:** Python parsers for every supported source contract.
2. **LLM-first extraction:** An AI model interprets most uploaded content and returns structured mappings.
3. **Hybrid deterministic-first extraction with bounded AI assistance:** Known structured sources use deterministic adapters; AI is used only for unresolved, narrative, unfamiliar, or ambiguous fragments. All results remain proposals requiring validation and review.

The current architectural recommendation is Option 3, the hybrid model. This is not a final decision; an independent reviewer is specifically asked to evaluate it against the other options and propose alternatives if warranted.

---

## 2. Business and operational context

### 2.1 Migration documentation problem

The migration team must prepare multiple deliverables for each application. The primary deliverables currently in scope are:

- **Topology:** A target architecture/topology diagram based on an existing template or an AMP-portal-generated base diagram.
- **ADS:** An Architecture Design Specification, currently represented by a PowerPoint template.
- **DDD:** A Detailed Design Document. The exact official DDD template and field-to-section contract have not yet been supplied.

Although each output has a different format and purpose, many required facts overlap:

- Application identity and ownership.
- Current environments and architecture style.
- Server inventory and utilization.
- Operating systems, middleware, runtimes, and third-party technologies.
- Interfaces, protocols, endpoints, ports, dependencies, and authentication.
- Databases, storage, backup, recovery, and resiliency.
- Security classifications and controls.
- Network requirements and target connectivity.
- Batch processing and operational tooling.
- Migration wave, sizing, sequencing, and site capacity.
- Target-state architectural decisions.

The project goal is to normalize these facts once, preserve their evidence and review history, and reuse the approved result across all outputs.

### 2.2 Principal users

The anticipated users and stakeholders include:

- Application Owner.
- Client Application Owner.
- Migration Application Architect.
- Application Architect.
- Application Technical Lead.
- Migration Lead.
- Migration Analyst.
- Compute Architect or Compute Analyst.
- Network Architect.
- Security Architect.
- Database Administrator and Database Architect.
- Storage Architect.
- Resilience Architect.
- Platform SME or Platform Architect.
- Interface Lead.
- Operations Architect.
- Capacity Architect and Wave Lead.
- Reviewers and deliverable approvers.
- System administrators and catalog maintainers.

Role vocabulary and separation-of-duty rules are not yet finalized. Some decisions must restrict who may accept a risk, approve a section, approve an intake, or approve a final deliverable.

### 2.3 Application identity

Each application has business identifiers and metadata such as:

- iTAP ID.
- Correlation ID.
- MOTS ID.
- Approved application name.
- Acronym.
- Application owner.
- Migration application architect.
- Other assigned domain owners and reviewers.
- Migration wave and cohort.
- Source and target site information.

The current architecture proposes a system-generated internal UUID as the database primary key. Correlation ID, MOTS ID, iTAP ID, and other external identifiers are stored as typed child records because their exact semantics and alias relationships have not yet been confirmed. Name, acronym, wave, or external IDs should not be overloaded as the permanent database identity.

---

## 3. Existing evidence landscape

The original evidence set contains several representative source formats. The fresh reviewer does not need the original files to understand the architectural implications described below.

### 3.1 UAQ — Unified Assessment Questionnaire

A CSV export contains 217 fields and is the richest structured application source currently available. In the representative file:

- The first row is a SharePoint `ListSchema` metadata blob and is not aligned to the CSV columns.
- The second row is the actual 217-column header.
- Subsequent rows contain application records.
- One pilot application had 205 of 217 fields populated.
- The file is multi-application, so the system must select the correct record using application identity rather than assuming one file equals one application.
- Some values are tool-generated, detected, estimated, or explicitly marked for validation and therefore should not be treated as confirmed facts.
- The metadata contains controlled vocabularies useful for validation.

Architectural implication: this source should use a deterministic, version-aware CSV parser rather than an LLM.

### 3.2 Application Questionnaire workbook

An XLSX workbook contains one worksheet per application and represents a legacy questionnaire process. Analysis found:

- 28 application-specific worksheets.
- 1,699 total question rows.
- 82 normalized question variants.
- Only 28 questions were common across all application sheets.
- The pilot application had 60 questions but only 21 answered.
- Owner, dependency, and remarks metadata were inconsistently used.
- Question numbering drift and duplication existed.

Architectural implication: this workbook is useful evidence and a historical question seed, but the one-sheet-per-application pattern is not suitable as the canonical production model. A stable question catalog with immutable question IDs is required.

### 3.3 Deep Dive Notes

A DOCX document for the pilot application includes:

- Narrative application information.
- Current-state architecture descriptions and embedded images.
- A server table.
- Database questions and answers.
- Technology stack information.
- Human-confirmed details.
- Facts copied from other portals or documents.
- Assumptions and statements with uneven provenance.

Architectural implication: deterministic DOCX extraction can preserve headings, paragraphs, tables, rows, and source locations. Semantic mapping of inconsistent narrative content may benefit from bounded AI assistance. However, the document cannot be assumed authoritative as a whole because it mixes primary evidence, copied values, interpretations, and assumptions.

### 3.4 Interface Tracking workbook

An XLSX workbook contains:

- A migrating-application summary with copied iTAP-style fields.
- A directional interface register.
- Contacts and data-impact details.
- Scan observations.
- Provider and consumer flows.
- Protocol and port information.

The pilot contained 11 directional interface rows. Curated interface declarations and scan observations can disagree. Scan observations are evidence but must not automatically create architecture nodes or approved flows.

Architectural implication: interfaces require a first-class structured register, reconciliation rules, stable row keys, and evidence lineage. They should not be represented as a single long-text questionnaire answer.

### 3.5 Wave sizing workbook

A large XLSX workbook provides schema evidence for migration-wave sizing:

- 10,285 server records across 106 applications.
- Source allocations and utilization metrics.
- Formula-derived target recommendations.
- External workbook links.
- Thousands of cached formula errors.
- Incomplete utilization fields.
- Fallback/default calculations when utilization is missing.

The representative workbook belongs to Wave 3, while the pilot application belongs to Wave 4 and does not appear in the workbook. It is therefore a structurally valid source but not applicable evidence for the pilot application.

Architectural implications:

- Structural validity is separate from application applicability.
- The system needs application and wave membership gates before importing rows.
- Raw/observed values must be separated from formula-derived recommendations.
- Formula text, cached values, workbook hashes, external links, defaults, algorithm version, and approval must be preserved.
- A valid file may have the application association state `NOT_MATCHED`.
- Wave sizing, wave execution, and site-capacity evidence are distinct concepts.

### 3.6 Naming and tagging workbook

An XLSX workbook contains enterprise naming formats, abbreviation tables, and tagging requirements.

Architectural implication: naming should be a deterministic derived service using reviewed inputs. Naming standards do not provide application-specific target values and should not be treated as questionnaire answers.

### 3.7 ADS template

A PowerPoint ADS template contains approximately 19 slides and acts as an output contract. It also contains sample or asserted prose that is not proven for the pilot application.

Architectural implication: template sample content must be classified as `EXAMPLE`, cleared, or replaced unless reviewed application evidence supports it. Output templates are not sources of truth.

### 3.8 Topology diagrams

A pilot topology spike used:

- An AMP-generated application-specific draw.io diagram.
- A multi-page draw.io template with base, ALB, and F5 variants.

The spike demonstrated deterministic, value-only mutation of the application-specific diagram. It filled known labels while preserving layout and emitted issue markers for unresolved or conflicting values. It did not use AI in the final fill path.

Architectural implication: renderers must consume reviewed canonical facts. They must not directly interpret arbitrary evidence during generation.

### 3.9 Portal sources not available as standalone exports

The evidence review identified several source systems whose standalone export or screenshot contracts were absent:

- TSS.
- iTAP.
- SUD.
- PORT.
- DXC ticketing.
- Pilot-applicable Wave 4 sizing.
- Wave execution plan.
- Target-site capacity baseline.
- Official DDD template.

Facts copied from a portal into another document remain useful, but they are not equivalent to a first-party portal export unless the intake also records portal identity, record ID, retrieval time, collector, and suitable evidence.

---

## 4. Source-system vocabulary

The ingestion architecture must distinguish semantic source type from physical file format.

### 4.1 Semantic source types

Candidate source types include:

- `UAQ` — Unified Assessment Questionnaire.
- `TSS` — Technology Standards System or equivalent technology lifecycle/approval source.
- `ITAP` — application portfolio/identity and assessment source.
- `SUD` — server inventory and utilization source.
- `PORT` — authoritative host/application/dependency record source.
- `DXC_TICKET` — target build, request, approval, and implementation-ticket evidence.
- `DEEP_DIVE_NOTES`.
- `INTERFACE_TRACKING`.
- `WAVE_SIZING`.
- `WAVE_EXECUTION`.
- `WAVE_CAPACITY`.
- `APPLICATION_QUESTIONNAIRE`.
- `NAMING_STANDARD`.
- `ARCHITECTURE_DIAGRAM`.
- `APPLICATION_DOCUMENTATION`.
- `COMMAND_OUTPUT`.
- `NETWORK_MONITORING_EXPORT`.
- `FIREWALL_EXPORT`.
- `DB_EXPORT`.
- `SECURITY_REVIEW`.
- `OTHER`.

### 4.2 Physical formats

Potential formats include:

- CSV.
- XLSX.
- DOCX.
- PPTX.
- PDF.
- PNG, JPEG, and screenshots.
- draw.io XML.
- Structured JSON or YAML exports.
- A portal URL/reference with manually captured provenance.

The same format can represent many source types. The ingestion system must not equate `.xlsx` with SUD or `.docx` with Deep Dive Notes. It should allow the user to declare a source type, allow the system to propose one, or use both with confirmation when confidence is below a defined threshold.

---

## 5. Deliverable-oriented source profiles

Source requirements should be modeled as configurable evidence profiles rather than hard-coded upload checklists.

### 5.1 Deep Dive evidence profile

Expected or useful sources may include:

- UAQ.
- TSS.
- iTAP.
- SUD.
- PORT.
- DXC ticket.
- Existing application documentation.
- Existing architecture diagrams.
- Application-owner responses.

### 5.2 ADS evidence profile

Expected or useful sources may include:

- Approved canonical Deep Dive facts, not merely the generated document.
- Wave sizing.
- Wave execution plan.
- Capacity baseline.
- UAQ.
- iTAP.
- SUD.
- Interface Tracking.
- TSS.
- DXC target-state decisions and approvals.

### 5.3 Topology evidence profile

Expected or useful sources may include:

- Approved application identity.
- Current and target server/database registers.
- Interface register.
- Network rules and target design decisions.
- Region, account, site/Outpost, CIDR, DNS, load-balancer, and security-group decisions.
- Approved naming-standard derivations.

### 5.4 DDD evidence profile

The definitive profile remains open because the official DDD template and contract are unavailable. It will likely require the most detailed canonical facts and design decisions.

### 5.5 Important architecture rule

An existing Deep Dive or ADS document may be uploaded as evidence, but it should not become an authoritative intermediate database. The preferred dependency flow is:

```text
Raw evidence documents ───────────────┐
Portal captures and exports ──────────┤
Application-owner answers ────────────┼─> Reviewed canonical intake snapshot
Architect decisions ──────────────────┤          ├─> Topology
Existing Deep Dive/ADS documents ─────┘          ├─> ADS
                                                  └─> DDD
```

Avoid a compounded chain in which ADS facts are extracted only from a generated Deep Dive document when the original evidence is available. The canonical intake should be the shared production boundary.

---

## 6. Original questionnaire application concept

### 6.1 Product objective

Create one versioned intake per application assessment. The application should:

1. Register the application and external identifiers.
2. Assign the application owner, migration application architect, and domain roles.
3. Pin the intake to one immutable question-catalog release.
4. Select required deliverables.
5. Upload or reference evidence.
6. Import proposed scalar answers and structured register rows.
7. Ask users only for missing, conditional, ambiguous, or review-required data.
8. Track section ownership and review.
9. Detect missing, invalid, stale, conflicting, and unverified information.
10. Record architect decisions and accepted risks.
11. Freeze an approved intake revision.
12. Generate deliverables from the frozen canonical snapshot.

### 6.2 Proposed initial technical stack

The current baseline proposes:

- Python 3.12.
- FastAPI.
- SQLAlchemy 2.x.
- Alembic.
- Pydantic.
- Jinja2.
- HTMX.
- Vanilla CSS with a small reusable component layer.
- SQLite in WAL mode for an initial single-process pilot.
- pytest.
- Playwright.

The server-rendered design was selected because this is a dense internal operations workflow rather than a public consumer application. The architecture must use service and repository boundaries and portable SQL to permit migration to PostgreSQL when concurrency, scale, or multi-node deployment requires it.

### 6.3 Storage approach

The baseline decision is:

- Store Office documents, diagrams, generated artifacts, and other binary bytes in content-addressed file storage.
- Store hashes, metadata, provenance, workflow, mappings, states, reviews, and audit records in the database.
- Do not store large Office packages as SQLite BLOBs.
- Plan for future enterprise object storage or document repository integration.

### 6.4 Dependency rules

The intended layering is:

```text
Web routes and templates
    -> application services
        -> domain policies and state transitions
        -> repository interfaces
            -> SQLite/PostgreSQL implementation
        -> document import adapters
        -> validation and reconciliation services
        -> deliverable generators
```

Rules:

- Web routes do not issue arbitrary SQL.
- Templates do not calculate workflow truth.
- Importers do not silently confirm facts.
- Renderers do not read live mutable answers directly.
- State changes use named domain transitions.
- Every material state change writes an audit event in the same transaction.

---

## 7. Question catalog model

A draft catalog currently contains:

- 112 unique controls.
- 20 logical sections.
- 25 response types.
- 30 auto-import controls.
- 47 owner human-in-the-loop controls.
- 8 portal human-in-the-loop controls.
- 21 architect-decision controls.
- 6 derived controls.
- 40 register-status controls.
- 19 conditional controls.

### 7.1 Collection modes

- `AUTO_IMPORT`: expected to be proposed from evidence when available.
- `HITL_OWNER`: assigned owner supplies or confirms the value.
- `HITL_PORTAL`: a human accesses a portal and captures or uploads evidence; the product does not store portal credentials in the initial release.
- `ARCHITECT_DECISION`: a restricted role records a target-state or governance decision.
- `DERIVED`: calculated from canonical facts and not directly editable.

### 7.2 Why the catalog cannot directly render CSV rows as forms

The catalog requires a compilation step because:

- Pipe-delimited owners, sources, outputs, and allowed choices require normalization.
- Human-readable conditional text must become a safe executable condition language or AST.
- Response types require typed JSON schemas and renderer registrations.
- Register-status controls are aggregate gates and should navigate to a structured register, not render a free-text input.
- Destination labels must map to known semantic registers, not dynamic table names.
- Several complex response types remain underspecified.

### 7.3 Representative sections

The domain spans sections such as:

- Intake Control.
- Application.
- Current Architecture.
- Compute.
- Platform.
- Technology Standards.
- Network.
- Interfaces.
- Database.
- Storage and Backup.
- Security and Compliance.
- Identity and Access.
- Resilience and Disaster Recovery.
- Operations and Monitoring.
- Batch and Scheduling.
- Target Design.
- Migration and Cutover.
- Wave and Capacity.

### 7.4 Structured registers

Registers are required for repeated entities such as:

- Servers.
- Interfaces.
- Databases.
- Storage volumes and mount points.
- Technologies and TSS lifecycle decisions.
- Network/firewall/security-group rules.
- Batch jobs.
- IAM/service-account mappings.
- Target design components.
- Wave sizing and capacity records.

A question such as “Is the server inventory complete?” is a computed register gate. Users update server rows, and the system computes completeness. It is not an ordinary scalar answer.

---

## 8. Current UI concept

A static, in-memory prototype exists but is not available to the intended fresh reviewer. Its relevant conceptual views are summarized here:

### 8.1 Global views

- Portfolio.
- Application Workspace.
- My Work.
- Review Queue.
- Catalog administration.

### 8.2 Application workspace views

- Overview.
- Sources.
- Questionnaire.
- Registers.
- Issues.
- Reviews.
- Deliverables.
- History.

### 8.3 Application context

The workspace displays:

- Application name and acronym.
- Correlation ID.
- iTAP ID where known.
- Application lifecycle status.
- Intake collection status.
- Assigned owner and architect.
- Intake and catalog version.

### 8.4 Interaction ideas already represented

- Create an application intake.
- Upload evidence.
- Display source status and provenance.
- Review sectioned questions.
- Show current value, source, confidence, owner, and target outputs.
- Maintain server, interface, and database registers.
- Review issues and competing candidate values.
- Record architect rationale and evidence.
- Track review and deliverable readiness.
- Display audit/history information.

The prototype currently uses a generic file picker. The redesign requires replacing that simplistic interaction with a source-aware, application-aware document-ingestion wizard and dedicated candidate/finding review workbench.

---

## 9. Proven architecture principles

The following principles should be treated as strong defaults unless the reviewer identifies a compelling reason to change them.

### 9.1 Never invent a value

Missing facts remain unknown. A blank, absence of wording, or model inference must not be converted to `No`, `None`, or another definitive answer.

### 9.2 Never silently resolve a conflict

When peer or differently scoped sources disagree, preserve the candidates and require a domain-authorized decision. Authority may vary by field; there is no safe single global source precedence.

### 9.3 Every fact is typed, scoped, and attributable

A useful fact may need:

- Canonical path.
- Lifecycle: current or target.
- Environment.
- Site or region.
- Resource identity.
- Raw value.
- Normalized value.
- Unit.
- Source item and version.
- Exact source locator.
- Collector or author.
- Retrieval or effective date.
- Confidence.
- Review state.

### 9.4 Compare only like-for-like facts

Examples:

- Database TDE is not equivalent to backup encryption.
- PCI storage, PCI processing, PCI interfacing, and PCI-DSS validation are separate dimensions.
- Internet-facing ingress is not the same as private third-party connectivity.
- Source server allocation is not the same as a formula-derived target recommendation.

### 9.5 Canonical intake is the production boundary

Source readers populate proposals. Topology, ADS, and DDD render only reviewed canonical facts from an immutable snapshot.

### 9.6 Templates are not application evidence

Example text in a PowerPoint or Word template must not become an application fact without supporting reviewed evidence.

### 9.7 Portal facts require provenance

Where practical, record:

- Portal/source type.
- Record ID.
- Record URL or reference, subject to policy.
- Last-modified timestamp.
- Retrieval timestamp.
- Collector.
- Export or screenshot evidence.

### 9.8 Application applicability must be validated

A structurally valid source file may belong to the wrong application, wave, environment, or date range. Structural parsing success must never imply applicability.

---

## 10. Redesign goal: document-driven questionnaire prefill

### 10.1 User problem

An architect may already possess a completed or partially completed set of source artifacts. Requiring the architect to manually re-enter every answer into a web form would:

- Duplicate effort.
- Increase transcription errors.
- Lose source lineage.
- Encourage shortcuts and copy/paste.
- Make the UI less useful than existing documents.
- Reduce adoption.

### 10.2 Desired capability

The system should allow an authorized user to:

1. Open an application intake.
2. Select the intended evidence purpose or source type.
3. Upload one or more files or record approved external references.
4. Associate the evidence with the correct application.
5. Validate file safety, source contract, identity, wave, environment, and freshness.
6. Extract scalar facts and repeated register rows.
7. Map extracted information to standard questions and register schemas.
8. Validate response types, allowed values, units, scope, and required fields.
9. Reconcile new candidates with existing answers and other evidence.
10. Review clean candidates, changes, conflicts, and unmatched findings.
11. Accept, edit, reject, defer, or assign each proposal.
12. Preserve all evidence and processing lineage.
13. Ask application teams only for unresolved or review-required information.

### 10.3 Non-goal

The product is not intended to become an autonomous system that ingests arbitrary documents and declares them true. Automation reduces data-entry and triage effort; human accountability remains explicit.

---

## 11. Critical architectural distinction: evidence, extraction, candidate, canonical fact, and output

These concepts must not be conflated.

### 11.1 Evidence item

A logical source artifact, such as “FACET Deep Dive Notes” or “iTAP export for record 8375.”

### 11.2 Evidence version

A specific immutable byte representation or referenced version, identified by content hash and metadata.

### 11.3 Extracted fragment

A structural piece of the evidence:

- CSV field.
- XLSX cell or table row.
- DOCX heading, paragraph, or table cell.
- PPTX slide, shape, note, or table cell.
- PDF page region.
- OCR text block.

### 11.4 Candidate fact

A proposed mapping from extracted content to a canonical scalar question or register field/row.

### 11.5 Canonical answer or register revision

A versioned domain record created only after an authorized user or defined rule accepts a candidate or manually enters a value.

### 11.6 Approved snapshot

An immutable, reproducible representation of the reviewed intake at a specific approval point.

### 11.7 Generated output

A Topology, ADS, or DDD artifact generated from the approved snapshot, not directly from the evidence files.

---

## 12. Architecture options for document extraction and mapping

### 12.1 Option 1 — Deterministic adapter architecture

Build source-specific Python adapters for each known document contract and version.

#### Example adapters

- UAQ SharePoint CSV v4 adapter.
- Application Questionnaire XLSX adapter.
- Interface Tracking XLSX adapter.
- Deep Dive DOCX adapter.
- Wave Sizing XLSX adapter.
- Future TSS/iTAP/SUD/PORT/DXC export adapters.

#### Flow

```text
Upload
  -> safety and format validation
  -> source type and version selection
  -> contract fingerprinting
  -> deterministic parsing
  -> deterministic mapping
  -> canonical schema validation
  -> reconciliation
  -> human review
```

#### Advantages

- Highest reproducibility.
- Exact provenance down to sheet/cell, row/column, paragraph, table, or slide shape.
- Strong automated testability.
- No model hallucination.
- No LLM data disclosure.
- Low runtime cost.
- Excellent for standardized, structured exports.
- Aligns with the existing proven Python extraction approach.

#### Disadvantages

- New and changed templates require engineering work.
- Brittle when headings, sheets, columns, and layouts drift.
- Weak semantic interpretation of narrative prose.
- Slow expansion across many locally customized documents.
- Unknown formats produce little value until an adapter exists.

#### Best fit

- UAQ CSV.
- Interface Tracking XLSX.
- Wave Sizing XLSX.
- Standard portal exports.
- Stable tables in known DOCX/PPTX contracts.

#### Assessment

This is an essential foundation but may be insufficient as the only ingestion mechanism.

### 12.2 Option 2 — LLM-first interpretation architecture

Use local structural extraction only to obtain text/tables, then ask an LLM to identify source type and map most content into the canonical questionnaire/register schema.

#### Flow

```text
Upload
  -> safety validation
  -> generic text/table extraction
  -> chunking
  -> LLM classification and mapping
  -> structured response validation
  -> reconciliation
  -> human review
```

#### Advantages

- Faster support for unfamiliar documents.
- Better semantic handling of narrative content and synonyms.
- Can identify likely mappings despite layout changes.
- Can explain ambiguous and unmatched information.
- Reduces adapter development for one-off documents.

#### Disadvantages

- Non-deterministic behavior.
- Hallucination and unsupported inference risk.
- Harder reproduction and testing.
- Potential data-governance concerns.
- Prompt-injection exposure from document content.
- Context-window and chunk-boundary problems.
- Higher latency and runtime cost.
- Exact provenance becomes difficult unless deterministic preprocessing is still comprehensive.
- Model/provider changes may alter results.
- LLM may flatten scope, confuse similar concepts, or infer values from absence.

#### Assessment

Not recommended as the sole authoritative ingestion mechanism. It may be acceptable for proposal generation with strict local validation and mandatory human review.

### 12.3 Option 3 — Hybrid deterministic-first with bounded AI assistance

Use deterministic adapters for recognized source contracts and local generic structure extraction for all supported formats. Invoke AI only for unresolved, narrative, unfamiliar, or ambiguous fragments.

#### Flow

```text
Upload
  -> security validation
  -> application/source association
  -> contract classification
  -> deterministic structural extraction
  -> deterministic known mappings
  -> identify unresolved fragments
  -> optional bounded AI mapping
  -> strict schema validation
  -> cross-source reconciliation
  -> candidate/finding review
  -> append-only canonical revisions
```

#### Advantages

- Deterministic treatment of known sources.
- Flexible treatment of narrative and changed templates.
- Small, targeted prompts instead of whole-document prompts.
- Better provenance because locators are created before AI mapping.
- Reduced data exposure, token cost, latency, and hallucination surface.
- Allows rollout before an AI endpoint is ready.
- Supports comparison between deterministic and AI suggestions.
- Creates a learning path: repeated AI-assisted mappings can become tested deterministic rules in future contract releases.

#### Disadvantages

- Most complex orchestration model.
- Requires multiple extraction and mapping states.
- Needs strong UX for clean candidates, ambiguous candidates, and findings.
- Requires versioned prompt and model lineage.
- More metadata and audit records.
- Must define when AI assistance is permitted and who can trigger it.

#### Current recommendation

Option 3 is the preferred target architecture, but the independent reviewer should test whether its benefits justify its complexity for the first release.

---

## 13. Proposed target ingestion architecture

```text
Browser / Server-rendered UI
  |
  | upload file or record evidence reference
  v
Evidence Application Service
  |-- authorization
  |-- application association
  |-- source declaration
  |-- metadata and provenance capture
  |-- hash and duplicate detection
  v
Secure Evidence Storage
  |-- immutable content-addressed bytes
  |-- no file execution
  v
Document Processing Orchestrator
  |-- validation and quarantine step
  |-- source/contract classifier
  |-- deterministic document adapter registry
  |-- generic Office structure extractor
  |-- deterministic mapping engine
  |-- optional AI-assisted mapping provider
  |-- canonical schema validator
  |-- applicability and identity validator
  |-- reconciliation engine
  |-- finding generator
  v
Candidate Staging Layer
  |-- scalar answer candidates
  |-- register-row candidates
  |-- candidate provenance
  |-- mapping/extraction diagnostics
  |-- conflicts and findings
  v
Architect / Owner Review Workbench
  |-- bulk accept safe candidates
  |-- accept with edit
  |-- reject with rationale
  |-- defer or request evidence
  |-- manually map unmatched content
  |-- resolve conflicts under role policy
  v
Versioned Canonical Intake
  |-- append-only answer revisions
  |-- append-only register-row revisions
  |-- independent review states
  |-- audit trail
  v
Immutable Approved Snapshot
  |-- Topology generator
  |-- ADS generator
  `-- DDD generator
```

### 13.1 Architectural boundaries

- Storage knows bytes and metadata, not questionnaire semantics.
- Adapters know source contracts and structural locators.
- Mapping knows catalog and register schemas.
- Validation knows typed canonical constraints.
- Reconciliation knows candidate comparison and field-specific authority policies.
- Review services know authorization and state transitions.
- Renderers know only immutable canonical snapshots and output contracts.
- AI is one optional mapper behind an interface, not embedded in business logic.

---

## 14. Proposed upload and processing user journey

### 14.1 Step 1 — Choose purpose

The user identifies why the evidence is being added:

- Deep Dive evidence.
- ADS evidence.
- Topology evidence.
- DDD evidence.
- General supporting evidence.

Purpose may influence completeness reporting and recommended sources but should not restrict reuse of accepted canonical facts.

### 14.2 Step 2 — Select or detect source type

The user selects a source type or chooses auto-detection. Examples:

- UAQ.
- TSS.
- iTAP.
- SUD.
- PORT.
- DXC ticket.
- Deep Dive Notes.
- Interface Tracking.
- Wave Sizing.
- Other.

If auto-detection confidence is not high, the user must confirm the proposed type before semantic import.

### 14.3 Step 3 — Associate application

When uploading from an application workspace, the current application is preselected. Display key identity fields prominently. For multi-application exports, the system must identify candidate records and require explicit selection if more than one record could match.

### 14.4 Step 4 — Capture provenance

Collect or derive:

- Source-system record ID.
- Source-system URL/reference where allowed.
- Document title and version.
- Source last-modified timestamp.
- Retrieval timestamp.
- Retrieved by/collector.
- Effective date.
- Environment.
- Wave/cohort.
- Notes.
- Declared authoritative scope, if applicable.

### 14.5 Step 5 — Validate file and identity

Validation dimensions:

- Is the physical file supported and safe to parse?
- Does the document match a known source contract/version?
- Does it contain the current application identity?
- Does it belong to the current wave/environment?
- Is it multi-application?
- Is it current enough under source freshness policy?
- Is it a duplicate of an existing evidence version?

Application-association outcomes might be:

- `MATCHED`.
- `NOT_MATCHED`.
- `AMBIGUOUS`.
- `MULTI_APPLICATION`.
- `NO_APPLICATION_ID`.

### 14.6 Step 6 — Preview processing plan

Before execution, tell the user whether the run will use:

- A deterministic known adapter.
- Generic structural extraction.
- AI assistance for unresolved fragments.
- OCR, if later enabled.
- Expected target sections and registers.

### 14.7 Step 7 — Process asynchronously

Large Office files and AI calls should not block an HTTP request. The UI should show processing steps and allow the user to leave and return.

### 14.8 Step 8 — Review result summary

Provide counts such as:

- Proposed scalar answers.
- Proposed register rows.
- Values unchanged from current canonical facts.
- Proposed changes to existing values.
- Conflicts.
- Invalid values or units.
- Partial mappings.
- Unmapped fragments.
- Application/wave mismatches.
- Low-confidence AI proposals.

### 14.9 Step 9 — Human disposition

Actions include:

- Accept.
- Accept with edit.
- Reject with rationale.
- Defer.
- Assign to a role/user.
- Request clarification/evidence.
- Map manually to a question/register field.
- Identify a catalog gap.
- Mark as irrelevant.

---

## 15. Candidate fact contract

A candidate should carry enough information to validate, compare, review, audit, and reproduce it.

### 15.1 Recommended fields

```text
candidate_id
application_id
intake_id
evidence_item_id
evidence_version_id
processing_job_id
source_type
document_contract_code
document_contract_version
extractor_kind: DETERMINISTIC | AI_ASSISTED | MANUAL
extractor_version
mapping_rule_version
prompt_template_version, if AI-assisted
model/provider/run ID, if AI-assisted
question_code, nullable
register_key, nullable
register_stable_key, nullable
canonical_field_path
lifecycle_scope
environment_scope
site_scope
resource_scope
raw_value
normalized_value
unit
source_locator
confidence
validation_state
mapping_explanation
candidate_state
created_at
reviewed_by
reviewed_at
review_rationale
```

A candidate must target exactly one of:

- A scalar question/answer path.
- A register row or register field.

### 15.2 Source locator examples

CSV:

```json
{"record_key":"8375","row":2,"column":"INV4"}
```

XLSX:

```json
{"sheet":"Interfaces","row":17,"column":"Destination Port","cell":"K17"}
```

DOCX:

```json
{"heading":"Database","table":2,"row":4,"column":"Version"}
```

PPTX:

```json
{"slide":7,"shape_id":14,"shape_name":"Technology Table","row":3,"column":2}
```

### 15.3 Confidence vocabulary

A possible vocabulary is:

- `AUTHORITATIVE_EXPORT`.
- `STATED`.
- `CORROBORATED`.
- `OPERATOR_CONFIRMED`.
- `DERIVED_VERIFIED`.
- `DERIVED_UNVERIFIED`.
- `OBSERVED`.
- `INFERRED_PROPOSAL`.
- `AI_PROPOSED`.
- `LOW_CONFIDENCE`.
- `UNKNOWN`.

Confidence is not the same as approval or source authority.

---

## 16. Document contract registry

Known formats need versioned, data-driven contracts rather than hard-coded filename assumptions.

### 16.1 Example contract

```yaml
source_type: DEEP_DIVE_NOTES
contract_code: DEEP_DIVE_DOCX_V1
accepted_mime_types:
  - application/vnd.openxmlformats-officedocument.wordprocessingml.document
fingerprint:
  required_headings:
    - Application Overview
    - Database
  optional_headings:
    - Technology Stack
  table_signatures:
    server_inventory:
      required_columns:
        - Hostname
        - Operating System
mapping_release: deep-dive-map-1.0
ai_fallback_policy: UNRESOLVED_FRAGMENTS_ONLY
```

### 16.2 Contract-match states

- `MATCHED`.
- `PARTIAL_MATCH`.
- `UNKNOWN_VERSION`.
- `AMBIGUOUS`.
- `UNSUPPORTED`.

A partial match should not necessarily reject the file. The system may parse known structures, preserve unknown fragments as findings, and optionally invoke AI on those fragments.

### 16.3 Versioning

Changing a source mapping must create a new immutable mapping/contract release. Reprocessing historical evidence should record which release produced each candidate.

---

## 17. Deterministic extraction responsibilities

Even in the hybrid architecture, deterministic local processing remains responsible for:

- File hashing.
- MIME and package validation.
- CSV row and column identification.
- Workbook sheets, cells, formulas, cached values, named ranges, tables, hidden states, and external links.
- DOCX paragraphs, heading levels, tables, runs, relationships, and embedded media references.
- PPTX slides, shapes, tables, notes, and media references.
- Exact source locators.
- Known field mappings.
- Controlled vocabulary normalization.
- Unit parsing where unambiguous.
- Application/wave identity extraction when defined by contract.
- Canonical schema validation.
- Duplicate and stable-key detection.

The AI should not replace deterministic work that can be expressed and tested reliably.

---

## 18. Bounded AI-assistance design

### 18.1 Appropriate AI tasks

- Classify an unfamiliar document from locally extracted metadata and small samples.
- Map a narrative paragraph to likely catalog question IDs.
- Convert prose into a proposed typed value.
- Identify synonyms for changed table headers.
- Suggest a proposed register row from narrative evidence.
- Explain why extracted content does not satisfy the target schema.
- Summarize unmapped content.
- Identify apparent contradictions within one document.
- Suggest a future deterministic mapping rule for repeated structures.

### 18.2 Prohibited AI authority

An AI model must not:

- Confirm an answer.
- Approve a section, intake, risk, or deliverable.
- Resolve a conflict authoritatively.
- Make an architect decision.
- Overwrite current answers or registers.
- Determine final source authority without policy and human review.
- Infer `No` from missing text.
- Guess missing units, environments, identities, sites, or resource names.
- Treat output-template sample text as evidence.
- Modify original evidence.
- Generate or mutate an approved snapshot directly.

### 18.3 Prompt scope

Prompts should contain only:

- The smallest relevant document fragment.
- Its deterministic source locator.
- Source metadata.
- A relevant subset of question definitions.
- A relevant register schema, when applicable.
- Allowed values and units.
- Explicit non-inference rules.

Do not send an entire large workbook and all 112 controls in one prompt.

### 18.4 Structured response

The AI response should conform to a strict local schema, for example:

```json
{
  "mappings": [
    {
      "target_kind": "QUESTION",
      "target_code": "CMP-003",
      "raw_value": "No, licensing is not bound to MAC address",
      "proposed_value": "NO",
      "scope": {},
      "supporting_quote": "...",
      "confidence": 0.91,
      "reason": "The paragraph explicitly answers the licensing dependency question"
    }
  ],
  "unmapped": [],
  "warnings": []
}
```

Local code must reject malformed output, unknown question IDs, invalid values, invented locators, and schema violations.

### 18.5 Provider abstraction

A related migration-automation project designed a provider-independent runtime AI client with providers such as:

- `mock` for tests and offline development.
- AWS Bedrock.
- Anthropic.
- OpenAI or OpenAI-compatible endpoints.
- An AT&T internal Copilot Plugin Service using an OpenAI-compatible API.

The relevant design principles are reusable:

- Runtime AI is separate from IDE/development-time AI.
- Provider selection is configuration, not business logic.
- Tests always use a mock provider and make no network calls.
- Credentials are never committed.
- Callers depend on one interface.

The referenced internal Copilot service was described as not yet fully deployed. Its sample configuration used an HTTP endpoint. Before adoption, the team must verify production availability, HTTPS/TLS, authentication, retention, audit logging, rate limits, model availability, data handling, and service ownership.

For this product, a generic free-text `generate(prompt)` interface may be too weak. Prefer task-oriented, structured operations or a structured-generation capability while retaining provider abstraction.

### 18.6 AI run lineage

Record at least:

- Provider.
- Model.
- Endpoint class, not secrets.
- Prompt template ID/version.
- Catalog release.
- Register-schema release.
- Evidence hash.
- Fragment IDs and locators.
- Request hash.
- Response hash.
- Sampling/settings.
- Token counts where provided.
- Start/end timestamps.
- Outcome and validation errors.
- User who initiated or policy that triggered the call.

---

## 19. Reconciliation and source authority

### 19.1 No universal source precedence

Different sources may be authoritative for different fields. Examples:

- iTAP may be preferred for identity, owner, and business criticality.
- Interface Tracking may be preferred for curated directional interfaces.
- SUD may be preferred for observed server inventory/utilization.
- TSS may be preferred for technology lifecycle and exceptions.
- DXC may be preferred for approved target build values.
- An architect decision may be required for target topology choices.

Authority rules should be field-specific, scoped, versioned, and visible.

### 19.2 Reconciliation outcomes

For each candidate versus current canonical value and peer evidence:

- `NEW_VALUE`.
- `SAME_VALUE`.
- `MORE_COMPLETE`.
- `LESS_COMPLETE`.
- `NEWER_EVIDENCE`.
- `STALE_EVIDENCE`.
- `CONFLICT`.
- `SCOPE_DIFFERENCE`.
- `INVALID`.
- `NOT_APPLICABLE`.
- `NOT_MATCHED`.

### 19.3 Existing confirmed values

A new upload must never silently overwrite an owner-confirmed or approved value. It should produce a proposed change, conflict, or freshness finding with a side-by-side diff.

### 19.4 Reprocessing

Uploading a new evidence version or publishing a new extractor must create a new processing run and candidate set. Historical candidates and accepted revisions remain intact. Reprocessing should show differences rather than resetting questionnaire state.

---

## 20. Findings and exception workflow

Anything that cannot be mapped or validated should become a typed finding rather than being discarded or represented as one generic error.

### 20.1 Proposed finding types

- `UNMAPPED_CONTENT`.
- `UNSUPPORTED_STRUCTURE`.
- `UNKNOWN_DOCUMENT_VERSION`.
- `UNKNOWN_QUESTION`.
- `AMBIGUOUS_MAPPING`.
- `INVALID_VALUE`.
- `INVALID_UNIT`.
- `PARTIAL_VALUE`.
- `MISSING_SCOPE`.
- `MISSING_PROVENANCE`.
- `APPLICATION_MISMATCH`.
- `WAVE_MISMATCH`.
- `ENVIRONMENT_MISMATCH`.
- `DUPLICATE_RECORD`.
- `CONFLICT`.
- `STALE_EVIDENCE`.
- `LOW_CONFIDENCE`.
- `EXTRA_REGISTER_FIELD`.
- `MISSING_REQUIRED_REGISTER_FIELD`.
- `POSSIBLE_SECRET`.
- `PROMPT_INJECTION_DETECTED`.
- `CATALOG_GAP`.
- `PARSER_FAILURE`.

### 20.2 Finding lifecycle

- `OPEN`.
- `ASSIGNED`.
- `IN_REVIEW`.
- `RESOLVED`.
- `DEFERRED`.
- `DISMISSED`.

### 20.3 User actions

- Map content to an existing question.
- Map content to a register field/row.
- Split one fragment into multiple scoped candidates.
- Merge duplicate fragments.
- Edit a proposed normalized value.
- Mark irrelevant.
- Request clarification.
- Reject with rationale.
- Flag a catalog or source-contract gap.
- Assign to a domain owner.

Repeated manual mappings should feed a controlled learning process for future deterministic contract releases; they should not automatically retrain or alter runtime rules.

---

## 21. Candidate review experience

### 21.1 Review lane A — Clean deterministic candidates

Bulk acceptance may be allowed only if policy permits and all conditions are met:

- A deterministic adapter produced the candidate.
- The document contract matched.
- Application/wave/environment association matched.
- Value passed schema and business validation.
- No peer-source conflict exists.
- The candidate does not replace a confirmed or approved value.
- It is not an architect decision or restricted risk decision.
- Exact provenance is present.

Acceptance should normally produce an answered/proposed revision, not automatic owner confirmation.

### 21.2 Review lane B — Proposed changes

Show side-by-side differences:

```text
Canonical value: Yes
Canonical evidence: UAQ, retrieved 2026-07-15
Review state: Owner confirmed

New candidate: No
New evidence: Deep Dive Notes, Database section, paragraph 47
Extraction: AI-assisted

Actions: Keep current | Accept new | Create/retain conflict | Assign review
```

### 21.3 Review lane C — Ambiguity and findings

Show the exact evidence location, extracted text/value, suggested target, validation problem, and possible actions.

### 21.4 Register review

The system must support:

- New rows.
- Updates to existing rows by stable key.
- Possible duplicates.
- Split/merge decisions.
- Field-level conflicts within one row.
- Bulk review with drill-down.
- Completeness and expected-count reconciliation.

---

## 22. State-management model

A single `status` field cannot represent this domain. States should remain independent.

### 22.1 Application lifecycle

- `ACTIVE`.
- `ON_HOLD`.
- `ARCHIVED`.

### 22.2 Intake workflow

A possible lifecycle:

- `DRAFT`.
- `COLLECTING`.
- `IN_REVIEW`.
- `CHANGES_REQUESTED`.
- `READY_FOR_APPROVAL`.
- `APPROVED`.
- `SUPERSEDED`.
- `CANCELLED`.

### 22.3 Evidence state

- `UPLOADED`.
- `VALIDATING`.
- `VALID`.
- `INVALID`.
- `QUARANTINED`.
- `SUPERSEDED`.

### 22.4 Evidence/application association

- `PENDING`.
- `MATCHED`.
- `NOT_MATCHED`.
- `AMBIGUOUS`.
- `MULTI_APPLICATION`.

### 22.5 Document processing job

- `QUEUED`.
- `VALIDATING`.
- `CLASSIFYING`.
- `EXTRACTING`.
- `MAPPING`.
- `AI_ASSISTING`.
- `SCHEMA_VALIDATING`.
- `RECONCILING`.
- `AWAITING_REVIEW`.
- `COMPLETED`.
- `COMPLETED_WITH_FINDINGS`.
- `FAILED`.
- `CANCELLED`.

### 22.6 Candidate state

- `PROPOSED`.
- `ACCEPTED`.
- `ACCEPTED_WITH_EDIT`.
- `REJECTED`.
- `CONFLICT`.
- `DEFERRED`.
- `SUPERSEDED`.

### 22.7 Answer value state

- `UNKNOWN`.
- `PROPOSED`.
- `KNOWN`.
- `CONFLICT`.
- `NOT_APPLICABLE`.

### 22.8 Answer review state

- `DRAFT`.
- `ANSWERED`.
- `NEEDS_EVIDENCE`.
- `CHANGES_REQUESTED`.
- `CONFIRMED`.
- `APPROVED` where policy requires a separate approval.

### 22.9 Section state

Computed or transitioned independently from individual answers, for example:

- `NOT_STARTED`.
- `IN_PROGRESS`.
- `READY_FOR_REVIEW`.
- `IN_REVIEW`.
- `CHANGES_REQUESTED`.
- `APPROVED`.

### 22.10 Issue/finding state

Keep the issue type, severity, ownership, and workflow state separate.

### 22.11 Deliverable state

Each of Topology, ADS, and DDD must have an independent state because one may be ready while another is blocked:

- `NOT_REQUESTED`.
- `BLOCKED`.
- `READY`.
- `GENERATING`.
- `GENERATED_WITH_GAPS`.
- `GENERATED`.
- `IN_REVIEW`.
- `APPROVED`.
- `REJECTED`.
- `FAILED`.
- `SUPERSEDED`.

### 22.12 Progress

Progress is a computed projection rather than a mutable status. It may include:

- Applicable required questions answered.
- Required answers confirmed.
- Register rows complete.
- Evidence valid and current.
- Blocking conflicts/findings open.
- Sections approved.
- Deliverable prerequisites satisfied.

---

## 23. Data model implications

A draft SQLite schema already exists with approximately 46 tables and supports many baseline concepts, including users, roles, applications, external identifiers, immutable catalog releases, questions, registers, evidence, import candidates, answer revisions, issues, reviews, snapshots, jobs, outputs, and audit events.

The redesign should review or add explicit models for:

- `source_type_definitions`.
- `document_contracts`.
- `document_contract_versions`.
- `evidence_classifications`.
- `document_fragments` or a bounded structural-fragment representation.
- `processing_jobs`.
- `processing_job_steps`.
- `extraction_runs`.
- `mapping_runs`.
- `llm_runs`.
- `candidate_field_values` if candidate payloads need field-level normalization.
- `processing_findings`.
- `finding_dispositions`.
- `candidate_review_batches`.
- `candidate_review_actions`.
- `mapping_rule_releases`.

### 23.1 Avoid unnecessary duplication

Do not necessarily persist a full generic parse tree indefinitely. Preserve enough to audit and reproduce:

- Original immutable bytes.
- Hashes and metadata.
- Extractor and contract versions.
- Relevant extracted fragments.
- Exact locators.
- Candidates.
- Findings and diagnostics.
- AI request/response hashes and validated structured results.

### 23.2 Append-only revisions

Answer and register changes should be append-only with a current pointer. Approved snapshots are immutable. This permits efficient current reads without losing who changed what, when, why, and against which evidence.

### 23.3 SQLite boundary

SQLite in WAL mode is acceptable for a local or limited single-process pilot. It is not the long-term answer for multiple application servers or high concurrent write volume. Avoid SQLite-specific business logic and maintain repository boundaries to support PostgreSQL migration.

---

## 24. Security, privacy, and document-handling threat model

Uploaded documents are untrusted input even when supplied by internal users.

### 24.1 File safety controls

- MIME detection rather than extension trust.
- Explicit allowlist of formats.
- File-size limits.
- Office ZIP expansion limits.
- Row, cell, paragraph, page, slide, and embedded-object limits.
- Reject or quarantine macro-enabled documents unless explicitly approved.
- Detect external links and relationships.
- Preserve formulas as data; do not execute them.
- Reject unsafe OLE/embedded executables.
- Handle password-protected files explicitly.
- Malware scanning integration where available.
- Prevent path traversal and unsafe archive extraction.
- Never launch Office applications during server-side processing.

### 24.2 Sensitive content

- Classify evidence sensitivity.
- Restrict original-file download.
- Encrypt in transit and at rest according to enterprise policy.
- Establish retention and deletion rules.
- Avoid copying document content into general logs.
- Detect likely credentials, tokens, keys, or passwords and quarantine/flag them.
- Do not send secret-like values to an AI provider.

### 24.3 AI-specific threats

- Treat all document content as data, never instruction.
- Delimit evidence fragments in prompts.
- Ignore instructions embedded inside the document.
- Apply strict output schemas.
- Enforce allowed target question/register IDs locally.
- Validate source quotes against the provided fragment.
- Use minimum necessary fragments.
- Define approved providers and data boundaries.
- Record AI lineage without recording credentials.
- Rate-limit and authorize AI use.

### 24.4 Portal credentials

The initial design prohibits storing portal credentials. Humans access TSS, iTAP, SUD, PORT, and DXC under existing controls and upload or reference evidence. Direct portal integration would require a separate security and integration design.

---

## 25. Audit and reproducibility requirements

For each accepted canonical value, the system should answer:

- What is the value and scope?
- Which application and intake revision does it belong to?
- Which evidence item/version supports it?
- Where exactly in the evidence did it appear?
- Which extractor and mapping release produced it?
- Was AI involved? If so, which provider/model/prompt version?
- What validation occurred?
- Did another source disagree?
- Who accepted, edited, confirmed, or approved it?
- What rationale was recorded?
- Which approved snapshot included it?
- Which output artifacts used that snapshot?

For each generated deliverable, record:

- Snapshot ID/hash.
- Generator version.
- Template version/hash.
- Output hash.
- Generation timestamp.
- Gaps and warnings.
- Review and approval lineage.

---

## 26. Implementation phasing recommendation

### Phase 0 — Resolve contracts and governance

- Confirm external identifier semantics.
- Confirm roles and separation of duties.
- Confirm deployment and expected concurrency.
- Confirm storage, backup, retention, and access control.
- Confirm SSO/OIDC integration.
- Define evidence freshness.
- Define risk acceptance authority.
- Supply official DDD template.
- Normalize catalog response schemas, conditions, roles, and registers.
- Define first-release file formats and source contracts.
- Define AI data-governance boundary.

### Phase 1 — Deterministic ingestion foundation

Implement without a production AI dependency:

- Secure evidence upload and content-addressed storage.
- Evidence metadata and application association.
- Processing-job framework.
- UAQ CSV adapter.
- Application Questionnaire XLSX adapter.
- Interface Tracking XLSX adapter.
- Wave Sizing XLSX adapter.
- Known Deep Dive DOCX table/heading extraction.
- Candidate staging.
- Typed validation.
- Candidate review and findings.
- Append-only answer/register revisions.

### Phase 2 — Generic Office structural extraction

- Generic DOCX structure extraction.
- Generic XLSX structure extraction.
- PPTX slide/shape/table extraction.
- Contract fingerprinting.
- Manual mapping of unmatched content.
- Contract-version administration.
- Reprocessing and diff workflow.

PDF and OCR should be added only if business value and security complexity justify them.

### Phase 3 — Bounded AI-assisted mapping

- Provider abstraction.
- Mock provider for all automated tests.
- Approved internal provider integration.
- Structured output schemas.
- Prompt-template versioning.
- Unresolved-fragment selection.
- AI lineage and audit.
- Mandatory human review.
- Prompt-injection controls.
- Cost, latency, and quality metrics.

### Phase 4 — Learning and adapter hardening

- Analyze repeated manual mappings.
- Convert stable recurring mappings into deterministic rules.
- Test against a controlled document corpus.
- Publish immutable mapping/contract releases.
- Reduce AI dependence for known document families.

### Phase 5 — Deliverable expansion

- Preserve proven deterministic topology generation.
- Finalize ADS output contract and remove unsafe template examples.
- Implement DDD only after its official contract exists.
- Maintain separate deliverable reviews and approvals.

---

## 27. Testing and quality strategy

### 27.1 Deterministic parser tests

- Golden-file fixtures for every supported contract/version.
- Exact extraction and locator assertions.
- Template drift tests.
- Corrupt and malicious package tests.
- Large-file limits.
- Formula/cached-value lineage tests.
- Multi-application row-selection tests.
- Application/wave mismatch tests.

### 27.2 Mapping and validation tests

- Every question response type.
- Every register schema.
- Allowed-value and unit validation.
- Conditional applicability.
- Scope comparison.
- Stable-key duplicate handling.
- Field-specific authority.
- Conflict generation.
- Reprocessing diffs.

### 27.3 AI tests

- Mock provider only in automated tests.
- No API keys or network in pytest.
- Schema-conforming canned responses.
- Invalid JSON and unknown target IDs.
- Hallucinated locator rejection.
- Prompt injection fixtures.
- Unsupported inference fixtures.
- Manual, controlled integration tests against approved providers.

### 27.4 Workflow tests

- Authorization and separation of duties.
- Bulk-accept eligibility.
- Append-only revision behavior.
- Evidence supersession.
- Snapshot immutability.
- Audit event atomicity.
- Independent deliverable readiness.

### 27.5 End-to-end acceptance scenarios

1. Upload a matching UAQ export and propose clean scalar answers.
2. Upload a multi-application UAQ and select the correct record.
3. Upload a valid Wave workbook that does not contain the application and prohibit row import.
4. Upload Interface Tracking and create/update directional register rows.
5. Upload Deep Dive Notes, deterministically extract known tables, and AI-map only unresolved narrative.
6. Upload newer evidence that conflicts with an owner-confirmed answer and require explicit review.
7. Reject an AI proposal without changing canonical state.
8. Approve an intake snapshot and generate a deterministic topology from it.

---

## 28. Operational and observability requirements

Track metrics such as:

- Upload count by source type and format.
- Contract match rate.
- Deterministic mapping rate.
- AI-assistance rate.
- Candidate acceptance, edit, and rejection rates.
- Findings by type.
- Conflict frequency by field/source pair.
- Average review backlog.
- Processing duration by phase.
- AI tokens, cost, failures, and latency where available.
- Parser failures and document-version drift.
- Percentage of questions prefilled versus manually answered.
- Deliverable readiness blockers.

Avoid logging sensitive extracted values. Use IDs, hashes, counts, and error categories where possible.

---

## 29. Existing accepted defaults

The following design defaults have already been proposed and should be reviewed but are not casual assumptions:

1. Use an internal application UUID; external IDs are typed child records.
2. Keep application, intake, section, answer value, answer review, register, evidence, issue, job, and deliverable states separate.
3. Compile question catalogs into immutable releases.
4. Use append-only answer and register-row revisions.
5. Store evidence bytes outside SQLite in content-addressed storage.
6. Start with a server-rendered Python UI and SQLite WAL for the pilot.
7. Generate artifacts only from immutable canonical snapshots.
8. Model portal access as human tasks and evidence capture; do not store portal credentials initially.

---

## 30. Open decisions inherited from the original UI design

1. Are iTAP ID, Correlation ID, and MOTS ID distinct fields or aliases?
2. What are the global/scoped uniqueness rules for application name and acronym?
3. Who may create applications and assign owners/architects?
4. Which decisions prohibit self-approval?
5. What freshness period applies to each source type?
6. Is the pilot local, a shared internal server, or another deployment model?
7. What are expected application counts, users, and concurrent editors?
8. What SSO/OIDC provider, claims, and group mappings apply?
9. What storage root, backup, retention, and access-control policies apply?
10. Does intake approval mean facts are approved, generation-ready, or both?
11. Who approves Topology, ADS, and DDD independently?
12. What is the official DDD template and contract?
13. What are the exact typed schemas for complex catalog response types?
14. What stable role codes and primary/collaborator/reviewer semantics apply?
15. Who may accept risks by severity, and when is expiry mandatory?
16. What notification channels are approved?

---

## 31. New decisions introduced by the document-ingestion redesign

1. Is AI-assisted extraction permitted for internal evidence at all?
2. Which source types and sensitivity levels may be sent to an AI provider?
3. Must all AI processing remain on the internal network?
4. Which runtime provider is approved, available, supported, and auditable?
5. Must users always declare source type, or may auto-detection proceed automatically above a threshold?
6. Which first-release formats are supported: CSV, XLSX, DOCX, PPTX, PDF, and/or images?
7. Is OCR in scope?
8. Are external repository links references only, or may the product fetch content?
9. What maximum file, workbook, row, page, and slide sizes apply?
10. May clean deterministic candidates be bulk-accepted?
11. Does candidate acceptance require owner confirmation before section approval?
12. Can AI-assisted candidates ever be bulk-accepted? The current recommendation is no.
13. Who may manually map unmatched content?
14. How are field-specific source-authority rules governed and versioned?
15. How are multi-application documents handled in v1?
16. How are password-protected documents handled?
17. How long are raw extracted fragments and AI payloads retained?
18. Must documents be redacted before AI processing?
19. How are possible credentials and secrets handled?
20. What evidence and processing states block deliverable generation?
21. What quality threshold is required before enabling AI beyond pilot use?
22. Who owns document contract maintenance and mapping releases?

---

## 32. Key architecture risks

### 32.1 Canonical-model overreach

Attempting to model every possible document field in the initial release could create an unmanageable schema. Mitigation: prioritize the question catalog and first registers, preserve unmatched evidence as findings, and evolve immutable schema releases.

### 32.2 AI trust leakage

Users may assume a fluent AI proposal is authoritative. Mitigation: explicit visual labeling, mandatory review, provenance display, no AI confirmation privileges, and acceptance metrics.

### 32.3 Source drift

Locally modified spreadsheets and documents may defeat deterministic adapters. Mitigation: contract fingerprinting, partial-match handling, generic extraction, typed findings, and bounded AI fallback.

### 32.4 Review overload

If every imported field requires individual confirmation, the workflow may save little time. Mitigation: risk-based review lanes, deterministic bulk acceptance policy, unchanged-value collapsing, and section/register batch review.

### 32.5 Conflict explosion

Naive cross-source comparison may create false conflicts across environments, dates, or semantic dimensions. Mitigation: typed scope, compare like-for-like facts, and field-specific authority.

### 32.6 SQLite concurrency

A shared deployment may outgrow SQLite. Mitigation: validate deployment assumptions early, preserve repository boundaries, and define a PostgreSQL transition trigger.

### 32.7 Evidence security

Office documents can contain malicious packages, secrets, sensitive data, or external links. Mitigation: strong ingestion sandbox and governance before broad upload support.

### 32.8 Provider dependency

The intended internal AI endpoint may be unavailable or not meet security requirements. Mitigation: deterministic foundation, provider abstraction, feature flags, mock testing, and no AI dependency in core workflows.

### 32.9 Output contamination

Example text in output templates may be mistaken for approved facts. Mitigation: classify template content as example-only and require canonical support for rendered claims.

---

## 33. Recommended target principles

The current recommendation can be summarized as follows:

1. Upload once, normalize once, review once, and reuse across outputs.
2. Documents create candidates, not approved answers.
3. Known structured formats use deterministic Python adapters.
4. AI processes only unresolved or semantically ambiguous fragments.
5. Every proposal retains an exact source locator.
6. Scalar questions and structured registers remain separate.
7. Unmatched content becomes a typed finding instead of being discarded.
8. Application, wave, environment, and freshness gates run before canonical import.
9. Accepted candidates append revisions and never erase history.
10. Confirmed values are never silently overwritten by newer uploads.
11. Source authority is field-specific, scoped, versioned, and reviewable.
12. AI has no approval, conflict-resolution, or architect-decision authority.
13. Topology, ADS, and DDD consume immutable reviewed snapshots only.
14. The system can operate usefully without a live AI provider.
15. Repeated stable AI/manual mappings should become deterministic contract rules.

---

## 34. Requested independent architecture review

The fresh reviewer should provide a rigorous principal-architect assessment covering the following.

### 34.1 Problem framing

- Is the canonical-intake model the correct product boundary?
- Are evidence, candidates, canonical facts, snapshots, and outputs separated correctly?
- Are any major business actors or workflows missing?

### 34.2 Option analysis

Evaluate at least:

- Deterministic-only adapters.
- LLM-first interpretation.
- Hybrid deterministic-first with bounded AI assistance.

For each, address:

- Correctness.
- Auditability.
- Security/privacy.
- Maintainability.
- Extensibility.
- User experience.
- Runtime cost and latency.
- Testing and reproducibility.
- Time-to-value.
- Vendor/provider dependency.

The reviewer may propose a fourth option if materially different.

### 34.3 Target architecture

Recommend:

- Service/component boundaries.
- Synchronous versus asynchronous processing.
- Document contract and mapping-release strategy.
- Candidate and finding models.
- State machines.
- Storage boundaries.
- AI provider interface.
- Reconciliation and authority policy.
- Review UX.
- Deployment topology.
- SQLite-to-PostgreSQL transition criteria.

### 34.4 Security architecture

Evaluate:

- Office file threats.
- Sensitive-data handling.
- Prompt injection.
- Secret detection.
- AI data egress.
- Authentication and authorization.
- Evidence retention.
- Audit logging.
- Model/provider governance.

### 34.5 Delivery plan

Recommend a phased plan that identifies:

- Minimum viable deterministic ingestion.
- Sources/formats to support first.
- Capabilities that must precede AI.
- AI pilot entry/exit criteria.
- Required architecture decision records.
- Testing gates.
- Operational readiness gates.

### 34.6 Required response format

The reviewer should return:

1. Executive assessment.
2. Critical assumptions and corrections.
3. Option comparison table.
4. Recommended target architecture.
5. Data/state model recommendations.
6. Security and governance findings.
7. Phased implementation recommendation.
8. Top architecture risks with mitigations.
9. Decisions that must be answered before coding.
10. Explicit verdict: proceed, revise, or reject the current hybrid recommendation.

---

## 35. Constraints for the independent reviewer

- Assume no access to the original files or code.
- Do not infer additional facts about the pilot application beyond this document.
- Treat all numerical source-analysis findings in this handoff as supplied evidence.
- Do not design direct portal credential storage into the initial release.
- Do not allow AI to approve or silently overwrite canonical facts.
- Preserve deterministic output generation and immutable snapshots.
- Clearly separate confirmed requirements from recommendations and unresolved decisions.
- Identify any area where lack of a real TSS, iTAP, SUD, PORT, DXC, or DDD contract prevents final design.

---

## 36. Concise reviewer prompt

The following prompt can accompany this file when handing it to a fresh architecture-review agent:

> Act as a principal enterprise, data, application, security, and AI architect. You have no access to the original repository or source evidence; this handoff is your complete context. Independently review the proposed redesign for uploading migration evidence, extracting and mapping facts into a canonical questionnaire/register model, optionally using bounded runtime AI, reconciling conflicts, preserving provenance, and generating approved deliverables from immutable snapshots. Compare deterministic-only, LLM-first, and hybrid approaches. Challenge the proposed hybrid recommendation, identify missing architecture and governance controls, recommend a concrete target architecture and phased delivery plan, and enumerate decisions that must be resolved before implementation. Do not write code.

---

## 37. Final context statement

This project is not primarily a form builder and is not primarily a document-generation utility. It is an evidence-backed migration decision system whose UI happens to include a questionnaire and whose outputs happen to include diagrams and documents.

The central architectural challenge is to transform heterogeneous, partially trusted, differently scoped, and sometimes conflicting source material into a canonical, reviewable, versioned, and reproducible application assessment without making users retype known information and without allowing automation—especially AI—to manufacture truth.
