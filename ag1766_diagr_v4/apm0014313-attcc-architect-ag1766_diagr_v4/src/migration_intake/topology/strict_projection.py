"""Strict v3 snapshot-to-multi-context projection for C4.3."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from migration_intake.topology.contracts import (
    HashMismatchError,
    NonCanonicalJsonError,
    TopologyContractError,
    canonical_json_bytes,
    load_snapshot_document,
    parse_canonical_json,
    sha256_hex,
)
from migration_intake.topology.guide_policy import normalize_interface_flow

if TYPE_CHECKING:
    from datetime import datetime

    from migration_intake.topology.scope import ContextKey, ScopeSelection


class StrictProjectionError(TopologyContractError):
    """Base error for strict v3 projection failures."""


class ProjectionIdentityMismatchError(StrictProjectionError):
    """Snapshot identity does not match the requested projection selection."""


class ProjectionMappingError(StrictProjectionError):
    """A response mapping or scope rule is invalid."""


class ProjectionIssueLevel(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"
    INFO = "INFO"


class MissingFactPolicy(StrEnum):
    ERROR = "ERROR"
    SKIP = "SKIP"


@dataclass(frozen=True, slots=True)
class StrictFactMapping:
    """Registered, response-type-aware answer selector."""

    question_code: str
    response_type: str
    output_key: str
    selector: str = "VALUE"
    missing_policy: MissingFactPolicy = MissingFactPolicy.ERROR


@dataclass(frozen=True, slots=True)
class StrictProjectionIssue:
    code: str
    level: ProjectionIssueLevel
    message: str
    subject: str
    blocking: bool


@dataclass(frozen=True, slots=True)
class ProjectedFact:
    output_key: str
    value: Any
    provenance: tuple[str, ...]
    source_question_code: str


@dataclass(frozen=True, slots=True, order=True)
class ProjectedScope:
    environment: str | None
    site_id: str | None
    account: str | None = None
    region: str | None = None
    state: str = "EXPLICIT"


@dataclass(frozen=True, slots=True, order=True)
class ProjectedNode:
    node_id: str
    kind: str
    scope: ProjectedScope
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, order=True)
class ProjectedFlow:
    source_id: str
    target_id: str
    direction: str
    relationship_type: str
    protocol: str | None
    port: str | None
    scope: ProjectedScope
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True, order=True)
class ProjectionExclusion:
    code: str
    source_id: str
    reason: str
    blocking: bool
    provenance: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ProjectionPartition:
    context: ContextKey
    facts: tuple[ProjectedFact, ...] = ()
    resources: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class StrictProjection:
    schema_version: str
    snapshot_id: str
    snapshot_hash: str
    application_id: str
    intake_id: str
    selection: ScopeSelection
    partitions: tuple[ProjectionPartition, ...]
    shared_resources: tuple[dict[str, Any], ...]
    relationships: tuple[dict[str, Any], ...]
    nodes: tuple[ProjectedNode, ...]
    flows: tuple[ProjectedFlow, ...]
    exclusions: tuple[ProjectionExclusion, ...]
    issues: tuple[StrictProjectionIssue, ...]
    projection_hash: str

    @property
    def has_blockers(self) -> bool:
        return any(issue.blocking for issue in self.issues)


def project_v3_snapshot(
    canonical_json: str,
    snapshot_hash: str,
    selection: ScopeSelection,
    mappings: tuple[StrictFactMapping, ...],
    projected_at: datetime,
) -> StrictProjection:
    """Project one validated v3 snapshot into selected context partitions."""
    if projected_at.tzinfo is None:
        raise StrictProjectionError("Projection timestamp must be timezone-aware")

    snapshot = load_snapshot_document(canonical_json, snapshot_hash)
    document = snapshot.document
    application = document["application"]
    intake = document["intake"]
    application_id = str(application["id"])
    intake_id = str(intake["id"])
    if application_id != selection.application_id:
        raise ProjectionIdentityMismatchError(
            f"Application mismatch: snapshot={application_id}, selection={selection.application_id}"
        )
    if intake_id != selection.intake_id:
        raise ProjectionIdentityMismatchError(
            f"Intake mismatch: snapshot={intake_id}, selection={selection.intake_id}"
        )

    mapping_by_code: dict[str, list[StrictFactMapping]] = {}
    output_keys: set[str] = set()
    for mapping in mappings:
        if mapping.output_key in output_keys:
            raise ProjectionMappingError(f"Duplicate projection output key: {mapping.output_key}")
        output_keys.add(mapping.output_key)
        mapping_by_code.setdefault(mapping.question_code, []).append(mapping)

    issues: list[StrictProjectionIssue] = []
    facts_by_context: dict[ContextKey, list[ProjectedFact]] = {
        context: [] for context in selection.ordered_contexts
    }
    for answer in document["answers"]:
        code = str(answer["question_code"])
        if answer["confirm_state"] != "CONFIRMED":
            continue
        answer_mappings = mapping_by_code.get(code)
        if answer_mappings is None:
            issues.append(
                StrictProjectionIssue(
                    "UNMAPPED_ANSWER",
                    ProjectionIssueLevel.ERROR,
                    f"No approved mapping for {code}",
                    f"answer:{code}",
                    True,
                )
            )
            continue
        for mapping in answer_mappings:
            if answer["response_type"] != mapping.response_type:
                raise ProjectionMappingError(
                    f"Response type mismatch for {code}: "
                    f"snapshot={answer['response_type']} mapping={mapping.response_type}"
                )
            value = select_fact_value(answer, mapping)
            if value is None:
                if mapping.missing_policy == MissingFactPolicy.ERROR:
                    issues.append(
                        StrictProjectionIssue(
                            "MISSING_FACT",
                            ProjectionIssueLevel.ERROR,
                            f"Missing value for {code}",
                            f"answer:{code}",
                            True,
                        )
                    )
                continue
            fact = ProjectedFact(
                mapping.output_key,
                value,
                tuple(sorted(str(item) for item in answer["provenance_references"])),
                code,
            )
            for context in selection.ordered_contexts:
                facts_by_context[context].append(fact)

    partitions = tuple(
        ProjectionPartition(
            context=context,
            facts=tuple(sorted(facts_by_context[context], key=lambda fact: fact.output_key)),
            resources=tuple(_resources_for_context(document["resources"], context, issues)),
        )
        for context in selection.ordered_contexts
    )
    selected_resources = [resource for partition in partitions for resource in partition.resources]
    shared_resources = tuple(
        resource for resource in document["resources"] if resource.get("global_scope") is True
    )
    selected_ids = {str(resource["resource_id"]) for resource in selected_resources}
    shared_ids = {str(resource["resource_id"]) for resource in shared_resources}
    relationships = _project_relationships(
        document["relationships"], selected_ids, shared_ids, issues
    )
    nodes, flows, exclusions = _project_semantic_graph(document, application_id, selection)
    issues.extend(
        StrictProjectionIssue(
            exclusion.code,
            ProjectionIssueLevel.ERROR if exclusion.blocking else ProjectionIssueLevel.WARNING,
            exclusion.reason,
            f"source:{exclusion.source_id}",
            exclusion.blocking,
        )
        for exclusion in exclusions
    )
    projection_document = {
        "schema_version": "1.0.0",
        "snapshot_id": intake_id,
        "snapshot_hash": snapshot_hash,
        "application_id": application_id,
        "intake_id": intake_id,
        "selection": selection.as_dict(),
        "partitions": [
            {
                "context": partition.context.as_dict(),
                "facts": [asdict(fact) for fact in partition.facts],
                "resources": [_json_value(resource) for resource in partition.resources],
            }
            for partition in partitions
        ],
        "shared_resources": [_json_value(resource) for resource in shared_resources],
        "relationships": [_json_value(relation) for relation in relationships],
        "nodes": [asdict(node) for node in nodes],
        "flows": [asdict(flow) for flow in flows],
        "exclusions": [asdict(exclusion) for exclusion in exclusions],
        "issues": [asdict(issue) for issue in sorted(issues, key=_issue_key)],
    }
    return StrictProjection(
        schema_version="1.0.0",
        snapshot_id=intake_id,
        snapshot_hash=snapshot_hash,
        application_id=application_id,
        intake_id=intake_id,
        selection=selection,
        partitions=partitions,
        shared_resources=shared_resources,
        relationships=tuple(relationships),
        nodes=nodes,
        flows=flows,
        exclusions=exclusions,
        issues=tuple(sorted(issues, key=_issue_key)),
        projection_hash=sha256_hex(canonical_json_bytes(projection_document)),
    )


def strict_projection_document(projection: StrictProjection) -> dict[str, Any]:
    """Return the canonical persisted document for a strict projection."""
    return {
        "schema_version": projection.schema_version,
        "snapshot_id": projection.snapshot_id,
        "snapshot_hash": projection.snapshot_hash,
        "application_id": projection.application_id,
        "intake_id": projection.intake_id,
        "selection": projection.selection.as_dict(),
        "partitions": [
            {
                "context": partition.context.as_dict(),
                "facts": [asdict(fact) for fact in partition.facts],
                "resources": [_json_value(resource) for resource in partition.resources],
            }
            for partition in projection.partitions
        ],
        "shared_resources": [_json_value(resource) for resource in projection.shared_resources],
        "relationships": [_json_value(relation) for relation in projection.relationships],
        "nodes": [asdict(node) for node in projection.nodes],
        "flows": [asdict(flow) for flow in projection.flows],
        "exclusions": [asdict(exclusion) for exclusion in projection.exclusions],
        "issues": [asdict(issue) for issue in projection.issues],
    }


def serialize_strict_projection(projection: StrictProjection) -> str:
    """Serialize and verify the exact strict projection bytes persisted for a run."""
    content = canonical_json_bytes(strict_projection_document(projection))
    actual_hash = sha256_hex(content)
    if actual_hash != projection.projection_hash:
        raise StrictProjectionError(
            f"Projection hash mismatch: expected {projection.projection_hash}, got {actual_hash}"
        )
    return content.decode("utf-8")


def load_strict_projection_document(canonical_json: str, expected_hash: str) -> Mapping[str, Any]:
    """Load canonical persisted projection bytes and reject malformed envelopes."""
    actual_hash = sha256_hex(canonical_json.encode("utf-8"))
    if actual_hash != expected_hash:
        raise HashMismatchError(
            f"Projection hash mismatch: expected {expected_hash}, got {actual_hash}"
        )
    document = parse_canonical_json(canonical_json)
    if canonical_json_bytes(document).decode("utf-8") != canonical_json:
        raise NonCanonicalJsonError("Stored projection bytes are not canonical")
    _require_keys(
        document,
        {
            "schema_version",
            "snapshot_id",
            "snapshot_hash",
            "application_id",
            "intake_id",
            "selection",
            "partitions",
            "shared_resources",
            "relationships",
            "nodes",
            "flows",
            "exclusions",
            "issues",
        },
        "projection",
    )
    if document["schema_version"] != "1.0.0":
        raise StrictProjectionError("Unsupported strict projection schema")
    for field in ("snapshot_id", "snapshot_hash", "application_id", "intake_id"):
        if not isinstance(document[field], str) or not document[field]:
            raise StrictProjectionError(f"Projection {field} must be a non-empty string")
    selection = document["selection"]
    if not isinstance(selection, Mapping):
        raise StrictProjectionError("Projection selection must be an object")
    _require_keys(
        selection,
        {"application_id", "intake_id", "contexts", "view_variant"},
        "projection selection",
    )
    if (
        selection["application_id"] != document["application_id"]
        or selection["intake_id"] != document["intake_id"]
    ):
        raise ProjectionIdentityMismatchError("Projection selection identity mismatch")
    contexts = selection["contexts"]
    if not isinstance(contexts, list) or not contexts:
        raise StrictProjectionError("Projection selection requires contexts")
    context_keys: list[tuple[str, str]] = []
    for context in contexts:
        if not isinstance(context, Mapping):
            raise StrictProjectionError("Projection context must be an object")
        _require_keys(context, {"environment", "site_id"}, "projection context")
        environment, site_id = context["environment"], context["site_id"]
        if not isinstance(environment, str) or not isinstance(site_id, str):
            raise StrictProjectionError("Projection context values must be strings")
        context_keys.append((environment, site_id))
    if len(set(context_keys)) != len(context_keys):
        raise StrictProjectionError("Projection contexts must be unique")
    partitions = document["partitions"]
    if not isinstance(partitions, list) or len(partitions) != len(context_keys):
        raise StrictProjectionError("Projection partitions must cover every context")
    partition_keys: list[tuple[str, str]] = []
    for partition in partitions:
        if not isinstance(partition, Mapping):
            raise StrictProjectionError("Projection partition must be an object")
        _require_keys(partition, {"context", "facts", "resources"}, "projection partition")
        context = partition["context"]
        if not isinstance(context, Mapping):
            raise StrictProjectionError("Projection partition context must be an object")
        _require_keys(context, {"environment", "site_id"}, "partition context")
        partition_keys.append((str(context["environment"]), str(context["site_id"])))
        if not isinstance(partition["facts"], list) or not isinstance(partition["resources"], list):
            raise StrictProjectionError("Projection facts and resources must be lists")
        for fact in partition["facts"]:
            if not isinstance(fact, Mapping):
                raise StrictProjectionError("Projection fact must be an object")
            _require_keys(
                fact,
                {"output_key", "value", "provenance", "source_question_code"},
                "projection fact",
            )
            if not isinstance(fact["output_key"], str) or not isinstance(fact["provenance"], list):
                raise StrictProjectionError("Projection fact identity or provenance is invalid")
    if sorted(partition_keys) != sorted(context_keys):
        raise StrictProjectionError("Projection partitions do not match selected contexts")
    for field in ("shared_resources", "relationships", "nodes", "flows", "exclusions", "issues"):
        if not isinstance(document[field], list):
            raise StrictProjectionError(f"Projection {field} must be a list")
    for node in document["nodes"]:
        if not isinstance(node, Mapping):
            raise StrictProjectionError("Projected node must be an object")
        _require_keys(node, {"node_id", "kind", "scope", "provenance"}, "projected node")
    for flow in document["flows"]:
        if not isinstance(flow, Mapping):
            raise StrictProjectionError("Projected flow must be an object")
        _require_keys(
            flow,
            {
                "source_id",
                "target_id",
                "direction",
                "relationship_type",
                "protocol",
                "port",
                "scope",
                "provenance",
            },
            "projected flow",
        )
    for exclusion in document["exclusions"]:
        if not isinstance(exclusion, Mapping):
            raise StrictProjectionError("Projection exclusion must be an object")
        _require_keys(
            exclusion,
            {"code", "source_id", "reason", "blocking", "provenance"},
            "projection exclusion",
        )
    for issue in document["issues"]:
        if not isinstance(issue, Mapping):
            raise StrictProjectionError("Projection issue must be an object")
        _require_keys(
            issue,
            {"code", "level", "message", "subject", "blocking"},
            "projection issue",
        )
    return document


def _require_keys(value: Mapping[str, Any], expected: set[str], subject: str) -> None:
    actual = set(value)
    if actual != expected:
        raise StrictProjectionError(
            f"{subject} fields mismatch: missing={sorted(expected - actual)}, "
            f"unknown={sorted(actual - expected)}"
        )


def _json_value(value: Any) -> Any:
    """Convert immutable contract mappings to ordinary JSON-compatible values."""
    if isinstance(value, Mapping):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_json_value(item) for item in value]
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def select_fact_value(answer: dict[str, Any], mapping: StrictFactMapping) -> Any:
    """Apply one registered response-type-aware selector to a canonical answer."""
    value = answer["value"]
    if mapping.selector == "VALUE":
        return value
    if mapping.selector.startswith("TEXT_PAIR."):
        if not isinstance(value, Mapping):
            raise ProjectionMappingError(
                f"TEXT_PAIR selector requires object for {mapping.question_code}"
            )
        return value.get(mapping.selector.split(".", 1)[1])
    if mapping.selector == "CONTROLLED_SET_CODES":
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            raise ProjectionMappingError(
                f"CONTROLLED_SET_CODES selector requires string list for {mapping.question_code}"
            )
        return tuple(sorted(value))
    raise ProjectionMappingError(f"Unsupported selector: {mapping.selector}")


def _resources_for_context(
    resources: list[dict[str, Any]],
    context: ContextKey,
    issues: list[StrictProjectionIssue],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for resource in resources:
        resource_id = str(resource["resource_id"])
        if resource["review_state"] != "CONFIRMED":
            issues.append(
                StrictProjectionIssue(
                    "UNCONFIRMED_RESOURCE",
                    ProjectionIssueLevel.ERROR,
                    f"Resource {resource_id} is not confirmed",
                    f"resource:{resource_id}",
                    True,
                )
            )
            continue
        if resource["lifecycle"] == "SOURCE":
            continue
        scope = resource.get("scope") or {}
        if scope.get("environment_state") == "UNKNOWN" or scope.get("site_state") == "UNKNOWN":
            issues.append(
                StrictProjectionIssue(
                    "UNKNOWN_RESOURCE_SCOPE",
                    ProjectionIssueLevel.ERROR,
                    f"Resource {resource_id} has unknown target scope",
                    f"resource:{resource_id}",
                    True,
                )
            )
            continue
        if resource.get("global_scope") is True:
            continue
        if (
            scope.get("environment") != context.environment
            or scope.get("site_id") != context.site_id
        ):
            continue
        selected.append(resource)
    return sorted(selected, key=lambda item: (item["kind"], item["logical_key"]))


def _project_semantic_graph(
    document: Mapping[str, Any],
    application_id: str,
    selection: ScopeSelection,
) -> tuple[tuple[ProjectedNode, ...], tuple[ProjectedFlow, ...], tuple[ProjectionExclusion, ...]]:
    nodes: dict[str, ProjectedNode] = {}
    exclusions: list[ProjectionExclusion] = []
    contexts = selection.ordered_contexts
    application_scope = ProjectedScope(
        contexts[0].environment if len(contexts) == 1 else None,
        contexts[0].site_id if len(contexts) == 1 else None,
        state="EXPLICIT" if len(contexts) == 1 else "MULTI_CONTEXT",
    )
    nodes[application_id] = ProjectedNode(application_id, "APPLICATION", application_scope)
    for resource in document["resources"]:
        resource_id = str(resource.get("resource_id") or resource.get("id") or "")
        if not resource_id:
            continue
        scope_data = resource.get("scope") or {}
        scope_state = "GLOBAL" if resource.get("global_scope") is True else "EXPLICIT"
        if (
            scope_data.get("environment_state") == "UNKNOWN"
            or scope_data.get("site_state") == "UNKNOWN"
        ):
            scope_state = "UNKNOWN"
        scope = ProjectedScope(
            scope_data.get("environment"),
            scope_data.get("site_id"),
            scope_data.get("account"),
            scope_data.get("region"),
            scope_state,
        )
        provenance = tuple(
            sorted(
                str(item) for item in resource.get("revision", {}).get("provenance_references", [])
            )
        )
        nodes[resource_id] = ProjectedNode(
            resource_id, str(resource.get("kind", "UNKNOWN")), scope, provenance
        )
    flow_members: dict[tuple[object, ...], set[str]] = {}
    flow_values: dict[tuple[object, ...], ProjectedFlow] = {}
    interface_rows = sorted(
        document["interface_register"]["rows"],
        key=lambda row: (
            str(row.get("id") or ""),
            str(row.get("interface_correlation_id") or ""),
        ),
    )
    for row in interface_rows:
        source_row = str(row.get("id") or row.get("interface_correlation_id") or "UNKNOWN")
        normalized = normalize_interface_flow(dict(row), application_id)
        provenance = tuple(sorted({source_row, str(row.get("origin") or "UNKNOWN")}))
        for item in normalized:
            if item.issue or item.source_id is None or item.target_id is None:
                exclusions.append(
                    ProjectionExclusion(
                        item.issue or "MISSING_ENDPOINT",
                        source_row,
                        item.issue or "Interface endpoint is missing",
                        True,
                        provenance,
                    )
                )
                continue
            row_env = str(row.get("environment")) if row.get("environment") else None
            row_site = str(row.get("site")) if row.get("site") else None
            row_has_scope = row_env is not None and row_site is not None
            if row_has_scope:
                scope_state = "EXPLICIT"
            elif application_scope.state == "MULTI_CONTEXT":
                scope_state = "UNKNOWN"
            else:
                # SL-PROJ-001: fail closed — do not inherit request context
                scope_state = "UNKNOWN"
            scope = ProjectedScope(
                row_env if row_env is not None else application_scope.environment,
                row_site if row_site is not None else application_scope.site_id,
                str(row.get("account")) if row.get("account") else None,
                str(row.get("region")) if row.get("region") else None,
                scope_state,
            )
            if scope.state == "UNKNOWN":
                exclusions.append(
                    ProjectionExclusion(
                        "UNKNOWN_FLOW_SCOPE",
                        source_row,
                        "Interface flow scope is unknown",
                        True,
                        provenance,
                    )
                )
                continue
            counterpart = item.source_id if item.source_id != application_id else item.target_id
            nodes.setdefault(
                counterpart, ProjectedNode(counterpart, "INTERFACE_ENDPOINT", scope, provenance)
            )
            flow = ProjectedFlow(
                item.source_id,
                item.target_id,
                item.direction or "UNKNOWN",
                "INTERFACE_FLOW",
                item.protocol,
                item.port,
                scope,
                provenance,
            )
            key = (
                flow.source_id,
                flow.target_id,
                flow.direction,
                flow.relationship_type,
                flow.protocol,
                flow.port,
                flow.scope,
            )
            flow_values[key] = flow
            flow_members.setdefault(key, set()).update(provenance)
    flows = tuple(
        sorted(
            (
                ProjectedFlow(
                    value.source_id,
                    value.target_id,
                    value.direction,
                    value.relationship_type,
                    value.protocol,
                    value.port,
                    value.scope,
                    tuple(sorted(flow_members[key])),
                )
                for key, value in flow_values.items()
            )
        )
    )
    return tuple(sorted(nodes.values())), flows, tuple(sorted(exclusions))


def _issue_key(issue: StrictProjectionIssue) -> tuple[str, str, str]:
    return issue.code, issue.subject, issue.message


def _project_relationships(
    relationships: list[dict[str, Any]],
    selected_ids: set[str],
    shared_ids: set[str],
    issues: list[StrictProjectionIssue],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    allowed_ids = selected_ids | shared_ids
    for relation in relationships:
        if relation["review_state"] != "CONFIRMED":
            issues.append(
                StrictProjectionIssue(
                    "UNCONFIRMED_RELATIONSHIP",
                    ProjectionIssueLevel.ERROR,
                    f"Relationship {relation['relationship_id']} is not confirmed",
                    f"relationship:{relation['relationship_id']}",
                    True,
                )
            )
            continue
        if (
            str(relation["source_resource_id"]) in allowed_ids
            and str(relation["target_resource_id"]) in allowed_ids
        ):
            result.append(relation)
    return sorted(result, key=lambda item: str(item["relationship_id"]))
