# Resource and Relationship Revision Lineage

EV-DATA-003; S08-C04. Five production files inspected: models/repository/service and migrations 0018/0019. A bounded `src/migration_intake/**` search located model/read usages but no resource-link writer. No database or excluded-suite execution.

## Resource Revision Path

The schema separates a mutable resource head from append-intent immutable revisions:

- `res_resources`: stable scoped identity, lifecycle/scope, current parent/revision/state/successor, revision and row versions.
- `res_revisions`: unique resource+revision number, canonical payload, review state, parent and resource state at that revision, change reason, provenance and author/time.
- Unique head identity: intake + logical key + lifecycle + computed scope key.
- Parent/successor and revision parent IDs reference stable resource heads.

Repository create:

1. Locks the intake content epoch.
2. Validates parent existence/kind/cycle, computes scope key and inserts head.
3. Inserts revision 1 with payload/review/provenance/parent/state.
4. Points head at revision ID and increments intake content epoch.

Repository revision:

1. Loads resource, locks intake epoch, refreshes it and verifies expected revision.
2. Inserts the next append-only revision.
3. Conditionally updates head by ID and expected revision, setting current revision ID/number, row version and timestamp.
4. Raises a concurrency conflict on zero updated rows; owning UoW is expected to roll back the inserted revision.
5. Advances intake content epoch after success.

ResourceService validates registered kinds, payload keys, lifecycle/site rules, parent resolution and review transitions before repository calls. These are application contracts, not database CHECK constraints.

## Topology Capture Read

The previously inspected runner:

- Lists ACTIVE resources deterministically by kind/logical key.
- Loads the revision by resource ID and head revision number.
- Requires revision ID = head current revision, revision number/state/parent agreement and CONFIRMED review state.
- Captures scope, parent, provenance and payload into immutable v3 authority.

This fail-closed read detects several head/revision mismatches. It cannot prevent those mismatches from being stored.

## Relationship Schema and Read Path

- `res_links`: typed source/target stable IDs, intake, current revision pointer/number/version/state and unique intake+type+source+target identity.
- `res_link_revisions`: unique link+revision number, review state, provenance and author/time.
- Capture lists ACTIVE links deterministically and requires the current revision pointer/number and CONFIRMED review state before including a typed relationship.
- A full production-source search found no instantiation of `TopologyResourceLink` or `TopologyResourceLinkRevision` outside their model definitions, and no `create_link`/relationship command in ResourceRepository/ResourceService. Migration/model definitions and read methods exist, but no normal production writer was located.

## F-DATA-005: Current-Revision Pointers Are Not Referentially/Owner Enforced

- FACT / VERIFIED static; severity High.
- `res_resources.current_revision_id` and `res_links.current_revision_id` are nullable UUID columns with no FK in ORM or migrations 0018/0019.
- Even a simple FK to revision ID would not prove ownership; the pointed revision must belong to the same resource/link and agree with the head revision number.
- Impact: orphan/wrong-owner pointers are structurally possible. Topology capture then fails, but other readers may trust stale/mismatched heads, and database integrity queries cannot rely on FKs.
- Proposed change: audit current rows, then add portable ownership enforcement (for example a composite unique revision identity plus composite FK from head pointer/identity), or a rigorously tested database-specific equivalent. Preserve initial create ordering through deferrable/altered constraints or a clearly bounded nullable bootstrap.
- Acceptance proposal: missing, cross-owner and number-mismatched current revisions fail storage; initial creation and atomic CAS revision advancement remain portable; historical revision rows cannot be cascaded away.

## F-DATA-006: Reparenting Leaves Head And Current Revision Inconsistent

- FACT / VERIFIED static; severity High.
- `reparent_resource` validates the new parent and calls `create_revision(... parent_id=new_parent_id, preserve_parent=False)`.
- `create_revision` stores the new parent in the revision, but its conditional head UPDATE changes only current revision ID/number, row version and updated time. It does not set `TargetResource.parent_id`.
- No subsequent reparent-specific head update exists. The captured revision parent therefore differs from the head parent after a successful reparent.
- Prior runner source explicitly rejects this mismatch, so a valid application-level reparent can make topology capture fail closed. This path has not been executed in the current review.
- Proposed fix: include the effective parent and effective resource state in the same conditional head update that advances current revision; avoid a second unfenced update. Review retire/supersede callers to remove redundant post-CAS state writes once the common update owns all current-state fields.
- Acceptance proposal: reparent creates one immutable revision and atomically changes head parent/pointer/version/epoch; stale writer rolls back; cross-intake/scope/cycle parent fails without a revision; capture sees exact agreement.

## F-PIPE-003: Typed Relationship Persistence Has No Production Writer

- FACT / VERIFIED static; severity Medium, potentially High where the target requires explicit resource relationships.
- Models, migrations, list/read/capture methods exist, but the bounded production-source search found no writer/command creating or revising `res_links`/`res_link_revisions`.
- Impact: ordinary application workflows cannot establish reviewed explicit resource relationships through this service boundary. Capture can consume only externally/directly seeded rows or no rows; provenance/review lifecycle cannot be completed through the located API.
- Proposed change: either implement a scoped, reviewed, CAS/epoch-fenced relationship command/repository contract in a dedicated vertical slice, or explicitly remove/defer this unused authority path and rely on a documented interface-flow source. Do not silently infer canonical links from diagram geometry.
- Acceptance proposal: create/review/retire a typed link with scoped endpoints and provenance; enforce same-intake endpoint ownership, unique identity and stale-write conflicts; capture includes only active confirmed current revisions.

## Additional Integrity Observations

- Resource/link revisions are append-only by repository convention, not database update/delete prevention.
- Head parent/successor/source/target FKs do not enforce same intake/scope. Reparent/supersede service paths check scope; `create_resource` repository parent validation checks kind/cycle but not explicitly same intake/scope. Normal ResourceService parent lookup is scoped, but direct repository callers remain a risk.
- Link endpoint FKs likewise do not enforce that endpoint resources match `res_links.intake_id`.
- Actor authors are strings, not actor FKs; provenance is JSON and not referentially constrained.
- Schema enum/state/kind/positive-version rules are mostly application-owned.
- Migration 0019 correctly adds parent/state/change reason to revisions so capture can compare revision lineage with the head.

Next: inspect portable types, Alembic environment and Oracle/SQLite migration branches statically in S08-C03. No database migration or execution is authorized by this analysis.