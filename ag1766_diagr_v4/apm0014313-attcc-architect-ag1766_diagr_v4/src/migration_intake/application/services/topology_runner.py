"""C7.1 persisted authority adapters and immutable topology runner."""

from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import TYPE_CHECKING

from sqlalchemy import select

from migration_intake.application.services.base_diagram import (
    BaseDiagramService,
    BaseDiagramServiceError,
)
from migration_intake.application.services.topology_finalization import (
    ArtifactFinalizationError,
    finalize_render_output,
)
from migration_intake.persistence.models import AuditEvent
from migration_intake.persistence.repositories.answers import AnswerRepository
from migration_intake.persistence.repositories.applications import ApplicationRepository
from migration_intake.persistence.repositories.catalogs import CatalogRepository
from migration_intake.persistence.repositories.intakes import IntakeRepository
from migration_intake.persistence.repositories.interfaces import InterfaceRepository
from migration_intake.persistence.repositories.resources import ResourceRepository
from migration_intake.persistence.repositories.snapshots import SnapshotRepository
from migration_intake.persistence.repositories.topology import (
    GenerationConflictError,
    TopologyRepository,
)
from migration_intake.persistence.repositories.wave_util import WaveUtilRepository
from migration_intake.persistence.unit_of_work import uow_context
from migration_intake.topology.contracts import (
    GenerationMode,
    RenderCapability,
    TopologyInputIdentity,
    canonical_json_bytes,
    load_snapshot_document,
    normalize_timestamp,
    serialize_snapshot_document,
    sha256_hex,
)
from migration_intake.topology.profiles import load_profile
from migration_intake.topology.renderer import (
    RenderContext,
    RenderInput,
    RunMode,
    XmlParserLimits,
    render_label_only,
    render_structural,
)
from migration_intake.topology.strict_projection import (
    StrictFactMapping,
    load_strict_projection_document,
    project_v3_snapshot,
    select_fact_value,
    serialize_strict_projection,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.orm import sessionmaker

    from migration_intake.storage.port import EvidenceStore
    from migration_intake.topology.scope import ContextKey, ScopeSelection


class GovernedRunnerError(RuntimeError):
    """The governed runner cannot capture, reserve, or execute an input."""


class PersistedLabelRenderer:
    """Render governed output from a persisted immutable input envelope."""

    def __init__(
        self,
        session_factory: sessionmaker,
        storage: EvidenceStore,
        *,
        xml_limits: XmlParserLimits | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._xml_limits = xml_limits or XmlParserLimits()
        self.last_output: object | None = None

    def __call__(self, immutable_input: dict[str, object]) -> None:
        capability = str(immutable_input["capability"])
        if capability not in {
            RenderCapability.LABEL_ONLY.value,
            RenderCapability.STRUCTURAL.value,
        }:
            raise GovernedRunnerError(f"Unsupported persisted render capability: {capability}")
        with self._session_factory() as session:
            repository = TopologyRepository(session)
            persisted_input = repository.get_topology_input(str(immutable_input["input_id"]))
            base = repository.get_base_artifact(str(immutable_input["base_artifact_id"]))
            compatibility = repository.get_topology_compatibility(
                str(immutable_input["compatibility_id"])
            )
        if (
            persisted_input is None
            or persisted_input != {key: immutable_input.get(key) for key in persisted_input}
            or immutable_input.get("input_id") != persisted_input["id"]
        ):
            raise GovernedRunnerError("Renderer input does not match persisted topology input")
        if base is None or compatibility is None:
            raise GovernedRunnerError("Renderer base or compatibility record is missing")
        try:
            with self._storage.retrieve(str(base["content_address"])) as stream:
                base_bytes = stream.read()
        except (OSError, ValueError) as error:
            raise GovernedRunnerError("Renderer base bytes are unavailable") from error
        profile = load_profile(str(persisted_input["profile_id"]))
        if (
            persisted_input["base_sha256"] != base["sha256_hex"]
            or persisted_input["profile_hash"] != profile.profile_hash
            or compatibility["base_artifact_id"] != base["id"]
            or compatibility["selection_hash"] != persisted_input["selection_sha256"]
            or compatibility["capability"] != persisted_input["capability"]
            or compatibility["parser_policy_hash"] != persisted_input["parser_policy_hash"]
            or persisted_input["compatibility_key"] != compatibility["compatibility_key"]
            or persisted_input["compatibility_result_hash"] != compatibility["result_hash"]
            or persisted_input["parser_policy_hash"]
            != sha256_hex(canonical_json_bytes(asdict(self._xml_limits)))
        ):
            raise GovernedRunnerError("Renderer persisted pins do not match source records")
        projection = load_strict_projection_document(
            str(persisted_input["projection_json"]),
            str(persisted_input["projection_sha256"]),
        )
        contexts = persisted_input["selection_json"]["contexts"]
        first_context = contexts[0]
        render_mode = (
            RunMode.OFFICIAL
            if persisted_input["mode"] == GenerationMode.OFFICIAL_SNAPSHOT.value
            else RunMode.DRAFT_PREVIEW
        )
        render_function = (
            render_structural
            if capability == RenderCapability.STRUCTURAL.value
            else render_label_only
        )
        output = render_function(
            RenderInput(
                projection=dict(projection),
                projection_hash=str(persisted_input["projection_sha256"]),
                base_diagram_bytes=base_bytes,
                base_diagram_hash=str(persisted_input["base_sha256"]),
                profile=profile,
                profile_hash=str(persisted_input["profile_hash"]),
                render_context=RenderContext(
                    environment=str(first_context["environment"]),
                    site=str(first_context["site_id"]),
                    variant=profile.manifest.variant,
                    run_id=str(immutable_input["run_id"]),
                    run_mode=render_mode,
                    created_by=str(persisted_input["captured_by_id"]),
                    intake_status="CAPTURED",
                    readiness_status="READY",
                ),
                recorded_timestamp=persisted_input["captured_at"],
            ),
            SimpleNamespace(
                is_compatible=True,
                base_hash=compatibility["base_sha256"],
                profile_hash=compatibility["profile_hash"],
                slot_matches=tuple(
                    SimpleNamespace(
                        slot_id=item["slot_id"],
                        page_name=item["page_name"],
                        cell_ids=tuple(item["cell_ids"]),
                    )
                    for item in compatibility["result_json"]["slot_matches"]
                ),
            ),
            self._xml_limits,
        )
        if not output.success:
            raise GovernedRunnerError(output.error_message or "Governed renderer failed")
        self.last_output = output


class GovernedTopologyRunner:
    """Capture immutable authority, commit T1, then invoke a renderer outside SQL."""

    _PREVIEW_STATES = frozenset(
        {
            "DRAFT",
            "COLLECTING",
            "IN_PROGRESS",
            "IN_REVIEW",
            "CHANGES_REQUESTED",
            "READY_TO_FREEZE",
        }
    )

    def __init__(
        self,
        session_factory: sessionmaker,
        storage: EvidenceStore,
        renderer: Callable[[dict[str, object]], None],
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._renderer = renderer

    def run_official(
        self,
        *,
        snapshot_id: str,
        selection: ScopeSelection,
        partition_views: dict[ContextKey, str],
        mappings: tuple[StrictFactMapping, ...],
        capability: RenderCapability,
        base_artifact_id: str,
        requested_by_id: str,
        generator_version: str,
        parser_policy_hash: str,
        layout_policy_hash: str,
        result_policy_hash: str,
        rerun_reason: str | None = None,
    ) -> dict[str, object]:
        """Load and verify a persisted v3 snapshot before projection and T1."""
        if rerun_reason is not None and not rerun_reason.strip():
            raise GovernedRunnerError("A rerun requires a non-empty reason")
        with self._session_factory() as session:
            snapshot = SnapshotRepository(session).get_by_id(snapshot_id)
        if snapshot is None:
            raise GovernedRunnerError("Official topology snapshot was not found")
        if snapshot["schema_version"] != "3.0.0":
            raise GovernedRunnerError("Official topology generation requires a v3 snapshot")
        try:
            contract = load_snapshot_document(snapshot["canonical_json"], snapshot["sha256_hex"])
        except ValueError as error:
            raise GovernedRunnerError(
                f"Official v3 snapshot failed integrity validation: {error}"
            ) from error
        if (
            str(contract.document["intake"]["id"]) != snapshot["intake_id"]
            or str(contract.document["catalog"]["id"]) != snapshot["catalog_id"]
            or str(contract.document["catalog"]["source_sha256"]) != snapshot["catalog_sha256"]
        ):
            raise GovernedRunnerError(
                "Official v3 snapshot metadata does not match its persisted row"
            )
        if contract.document["intake"]["state"] != "FROZEN":
            raise GovernedRunnerError("Official v3 snapshot must record a frozen intake")
        return self._project_reserve_render(
            mode=GenerationMode.OFFICIAL_SNAPSHOT,
            canonical_json=snapshot["canonical_json"],
            authority_hash=snapshot["sha256_hex"],
            snapshot_id=snapshot_id,
            capture_id=None,
            selection=selection,
            partition_views=partition_views,
            mappings=mappings,
            capability=capability,
            base_artifact_id=base_artifact_id,
            requested_by_id=requested_by_id,
            generator_version=generator_version,
            parser_policy_hash=parser_policy_hash,
            layout_policy_hash=layout_policy_hash,
            result_policy_hash=result_policy_hash,
            rerun_reason=rerun_reason,
        )

    def run_preview(
        self,
        *,
        selection: ScopeSelection,
        partition_views: dict[ContextKey, str],
        mappings: tuple[StrictFactMapping, ...],
        capability: RenderCapability,
        base_artifact_id: str,
        requested_by_id: str,
        generator_version: str,
        parser_policy_hash: str,
        layout_policy_hash: str,
        result_policy_hash: str,
        rerun_reason: str | None = None,
    ) -> dict[str, object]:
        """Persist a canonical v3 capture before projection or renderer execution."""
        if rerun_reason is not None and not rerun_reason.strip():
            raise GovernedRunnerError("A rerun requires a non-empty reason")
        capture = self._capture_preview(selection.intake_id, mappings, requested_by_id)
        return self._project_reserve_render(
            mode=GenerationMode.DRAFT_PREVIEW,
            canonical_json=str(capture["canonical_json"]),
            authority_hash=str(capture["sha256_hex"]),
            snapshot_id=None,
            capture_id=str(capture["id"]),
            selection=selection,
            partition_views=partition_views,
            mappings=mappings,
            capability=capability,
            base_artifact_id=base_artifact_id,
            requested_by_id=requested_by_id,
            generator_version=generator_version,
            parser_policy_hash=parser_policy_hash,
            layout_policy_hash=layout_policy_hash,
            result_policy_hash=result_policy_hash,
            rerun_reason=rerun_reason,
        )

    def _capture_preview(
        self,
        intake_id: str,
        mappings: tuple[StrictFactMapping, ...],
        captured_by_id: str,
    ) -> dict[str, object]:
        captured_at = datetime.now(tz=UTC)
        with uow_context(self._session_factory) as uow:
            session = uow._session
            intake_repository = IntakeRepository(session)
            intake_repository.begin_capture_fence()
            observed_intake = intake_repository.get(intake_id)
            if observed_intake is None:
                raise GovernedRunnerError("Preview intake was not found")
            application_repository = ApplicationRepository(session)
            application = application_repository.get_for_update(observed_intake["application_id"])
            intake = intake_repository.get_for_update(intake_id)
            catalog = CatalogRepository(session).get_release(intake["catalog_id"])
            if (
                application is None
                or intake is None
                or intake["application_id"] != observed_intake["application_id"]
                or catalog is None
            ):
                raise GovernedRunnerError("Preview application or catalog was not found")
            if intake["state"] not in self._PREVIEW_STATES:
                raise GovernedRunnerError(
                    f"Intake state {intake['state']} is not eligible for preview capture"
                )
            if not catalog["catalog_hash"]:
                raise GovernedRunnerError("Preview catalog lacks a compiled contract hash")

            answer_repository = AnswerRepository(session)
            answers = self._capture_answers(answer_repository, intake_id)
            acronym = self._application_acronym(answers, mappings)
            identifiers = application_repository.list_identifiers(intake["application_id"])
            if any(not identifier["normalized_value"] for identifier in identifiers):
                raise GovernedRunnerError(
                    "Preview identifiers include an empty normalized value"
                )
            resources = self._capture_resources(ResourceRepository(session), intake_id)
            relationships = self._capture_relationships(ResourceRepository(session), intake_id)
            interface_epoch, interfaces = InterfaceRepository(session).capture_projection_rows(
                intake["application_id"]
            )
            if interface_epoch != application["interface_epoch"]:
                raise GovernedRunnerError("Interface register changed during preview capture")
            wave_rows = self._capture_wave_rows(
                WaveUtilRepository(session), intake["application_id"], intake_id
            )
            document = {
                "schema_version": "3.0.0",
                "application": {
                    "id": application["id"],
                    "name": application["display_name"],
                    "acronym": acronym,
                    "identifiers": [],
                },
                "catalog": {
                    "id": catalog["id"],
                    "version": catalog["semantic_version"],
                    "source_sha256": catalog["source_sha256"],
                    "catalog_hash": catalog["catalog_hash"],
                    "compiler_version": catalog["compiler_version"],
                },
                "intake": {
                    "id": intake["id"],
                    "state": intake["state"],
                    "frozen_at": normalize_timestamp(intake["updated_at"]),
                    "frozen_by": intake["created_by_id"],
                    "row_version": intake["row_version"],
                    "content_epoch": intake["content_epoch"],
                },
                "answers": answers,
                "interface_register": {
                    "interface_epoch": interface_epoch,
                    "rows": interfaces,
                },
                "resources": resources,
                "relationships": relationships,
                "wave_util_rows": wave_rows,
                "permitted_gaps": [],
            }
            contract = serialize_snapshot_document(document)
            capture = TopologyRepository(session).create_topology_capture(
                capture_id=str(uuid.uuid4()),
                intake_id=intake_id,
                content_epoch=intake["content_epoch"],
                schema_version="3.0.0",
                canonical_json=contract.canonical_json,
                sha256_hex=contract.sha256_hex,
                captured_by_id=captured_by_id,
                captured_at=captured_at,
            )
            session.add(
                AuditEvent(
                    id=str(uuid.uuid4()),
                    entity_type="topology_capture",
                    entity_id=capture["id"],
                    event_code="TOPOLOGY_PREVIEW_CAPTURED",
                    actor_id=captured_by_id,
                    occurred_at=captured_at,
                    payload={
                        "intake_id": intake_id,
                        "content_epoch": intake["content_epoch"],
                        "sha256_hex": contract.sha256_hex,
                    },
                )
            )
            session.flush()
            uow.commit()
            return capture

    def _project_reserve_render(
        self,
        *,
        mode: GenerationMode,
        canonical_json: str,
        authority_hash: str,
        snapshot_id: str | None,
        capture_id: str | None,
        selection: ScopeSelection,
        partition_views: dict[ContextKey, str],
        mappings: tuple[StrictFactMapping, ...],
        capability: RenderCapability,
        base_artifact_id: str,
        requested_by_id: str,
        generator_version: str,
        parser_policy_hash: str,
        layout_policy_hash: str,
        result_policy_hash: str,
        rerun_reason: str | None,
    ) -> dict[str, object]:
        projected_at = datetime.now(tz=UTC)
        projection = project_v3_snapshot(
            canonical_json, authority_hash, selection, mappings, projected_at
        )
        if projection.has_blockers:
            raise GovernedRunnerError("Strict topology projection contains blocking issues")
        projection_json = serialize_strict_projection(projection)
        with self._session_factory() as session:
            repository = TopologyRepository(session)
            try:
                base = BaseDiagramService(repository, self._storage).eligible_base(
                    base_artifact_id,
                    official=mode == GenerationMode.OFFICIAL_SNAPSHOT,
                    selection=selection,
                    capability=capability,
                    partition_views=partition_views,
                )
            except BaseDiagramServiceError as error:
                raise GovernedRunnerError(f"Governed base is not eligible: {error}") from error
            compatibility = repository.get_topology_compatibility(str(base["compatibility_id"]))
            if compatibility is None:
                raise GovernedRunnerError("Governed base compatibility result was not found")
            if compatibility["parser_policy_hash"] != parser_policy_hash:
                raise GovernedRunnerError("Parser policy differs from approved base compatibility")

        identity = TopologyInputIdentity(
            mode=mode,
            capability=capability,
            projection_hash=projection.projection_hash,
            selection_hash=selection.selection_hash,
            base_hash=str(base["sha256_hex"]),
            compatibility_key=str(compatibility["compatibility_key"]),
            profile_hash=str(base["profile_hash"]),
            catalog_hash=str(
                load_snapshot_document(canonical_json, authority_hash).document["catalog"][
                    "catalog_hash"
                ]
            ),
            generator_version=generator_version,
            parser_policy_hash=parser_policy_hash,
            layout_policy_hash=layout_policy_hash,
            result_policy_hash=result_policy_hash,
            contexts=tuple((item.environment, item.site_id) for item in selection.ordered_contexts),
        )
        captured_at = datetime.now(tz=UTC)
        with uow_context(self._session_factory) as uow:
            repository = TopologyRepository(uow._session)
            intake_repository = IntakeRepository(uow._session)
            intake_repository.begin_capture_fence()
            observed_intake = intake_repository.get(selection.intake_id)
            if observed_intake is None:
                raise GovernedRunnerError("Selected intake was not found during T1")
            if (
                ApplicationRepository(uow._session).get_for_update(
                    observed_intake["application_id"]
                )
                is None
            ):
                raise GovernedRunnerError("Selected application was not found during T1")
            locked_intake = intake_repository.get_for_update(selection.intake_id)
            locked_base = repository.get_base_artifact_for_update(base_artifact_id)
            if (
                locked_intake is None
                or locked_intake["application_id"] != selection.application_id
                or (mode == GenerationMode.OFFICIAL_SNAPSHOT and locked_intake["state"] != "FROZEN")
                or (
                    mode == GenerationMode.DRAFT_PREVIEW
                    and locked_intake["state"] not in self._PREVIEW_STATES
                )
                or locked_base is None
                or locked_base["row_version"] != base["row_version"]
                or locked_base["review_state"] != base["review_state"]
                or locked_base["compatibility_id"] != base["compatibility_id"]
            ):
                raise GovernedRunnerError("Intake or governed base changed before T1")
            input_record = repository.get_or_create_topology_input(
                input_id=str(uuid.uuid4()),
                application_id=selection.application_id,
                intake_id=selection.intake_id,
                mode=mode.value,
                snapshot_id=snapshot_id,
                capture_id=capture_id,
                projection_json=projection_json,
                projection_sha256=projection.projection_hash,
                selection_json=selection.as_dict(),
                selection_sha256=selection.selection_hash,
                capability=capability.value,
                base_artifact_id=base_artifact_id,
                base_sha256=base["sha256_hex"],
                compatibility_id=compatibility["id"],
                compatibility_key=compatibility["compatibility_key"],
                compatibility_result_hash=compatibility["result_hash"],
                profile_id=base["profile_id"],
                profile_hash=base["profile_hash"],
                catalog_sha256=identity.catalog_hash,
                generator_version=generator_version,
                parser_policy_hash=parser_policy_hash,
                layout_policy_hash=layout_policy_hash,
                result_policy_hash=result_policy_hash,
                semantic_input_hash=identity.input_hash,
                captured_by_id=requested_by_id,
                captured_at=captured_at,
            )
            run = repository.reserve_generation_run(
                run_id=str(uuid.uuid4()),
                input_id=str(input_record["id"]),
                application_id=selection.application_id,
                intake_id=selection.intake_id,
                semantic_input_hash=identity.input_hash,
                requested_by_id=requested_by_id,
                requested_at=captured_at,
                rerun_reason=rerun_reason,
            )
            existing_audit = uow._session.execute(
                select(AuditEvent.id).where(
                    AuditEvent.entity_id == run["id"],
                    AuditEvent.event_code == "TOPOLOGY_RUN_RESERVED",
                )
            ).scalar_one_or_none()
            if existing_audit is None:
                uow._session.add(
                    AuditEvent(
                        id=str(uuid.uuid4()),
                        entity_type="topology_run",
                        entity_id=str(run["id"]),
                        event_code="TOPOLOGY_RUN_RESERVED",
                        actor_id=requested_by_id,
                        occurred_at=captured_at,
                        payload={"input_id": str(input_record["id"])},
                    )
                )
            uow.commit()

        if run["phase"] != "PENDING":
            return run
        lease_token = str(uuid.uuid4())
        with uow_context(self._session_factory) as uow:
            repository = TopologyRepository(uow._session)
            try:
                claimed = repository.claim_generation_run(
                    run_id=str(run["id"]),
                    expected_row_version=int(run["row_version"]),
                    lease_token=lease_token,
                    lease_expires_at=captured_at + timedelta(minutes=5),
                )
            except GenerationConflictError as error:
                current = repository.get_generation_run(str(run["id"]))
                if current is None:
                    raise GovernedRunnerError(
                        "Reserved run disappeared before execution"
                    ) from error
                return current
            persisted_input = repository.get_topology_input(str(claimed["input_id"]))
            if persisted_input is None:
                raise GovernedRunnerError("Reserved immutable input was not found")
            uow.commit()

        try:
            persisted_projection = load_strict_projection_document(
                str(persisted_input["projection_json"]),
                str(persisted_input["projection_sha256"]),
            )
        except ValueError as error:
            raise GovernedRunnerError(
                f"Persisted topology input failed integrity validation: {error}"
            ) from error
        if (
            persisted_input["semantic_input_hash"] != identity.input_hash
            or persisted_input["base_sha256"] != base["sha256_hex"]
            or persisted_input["compatibility_key"] != compatibility["compatibility_key"]
            or persisted_input["compatibility_result_hash"] != compatibility["result_hash"]
            or persisted_projection["application_id"] != selection.application_id
            or persisted_projection["intake_id"] != selection.intake_id
        ):
            raise GovernedRunnerError("Persisted topology input pins do not match T1")

        try:
            self._renderer(
                {
                    "run_id": claimed["id"],
                    "input_id": persisted_input["id"],
                    **persisted_input,
                }
            )
        except Exception as error:
            with uow_context(self._session_factory) as uow:
                failed = TopologyRepository(uow._session).fail_leased_generation_run(
                    run_id=str(claimed["id"]),
                    expected_row_version=int(claimed["row_version"]),
                    expected_phase="RENDERING",
                    lease_token=lease_token,
                    error_message=f"{type(error).__name__}: renderer execution failed",
                )
                uow.commit()
            raise GovernedRunnerError(f"Governed renderer failed for run {failed['id']}") from error

        with uow_context(self._session_factory) as uow:
            storing = TopologyRepository(uow._session).transition_leased_generation_phase(
                run_id=str(claimed["id"]),
                expected_row_version=int(claimed["row_version"]),
                expected_phase="RENDERING",
                new_phase="STORING",
                lease_token=lease_token,
            )
            uow.commit()
        render_output = getattr(self._renderer, "last_output", None)
        if render_output is not None:
            try:
                return finalize_render_output(
                    self._session_factory,
                    self._storage,
                    run_id=str(storing["id"]),
                    lease_token=lease_token,
                    expected_row_version=int(storing["row_version"]),
                    output=render_output,
                    actor_id=str(persisted_input["captured_by_id"]),
                )
            except ArtifactFinalizationError as error:
                raise GovernedRunnerError(str(error)) from error
        return storing

    @staticmethod
    def _capture_answers(repository: AnswerRepository, intake_id: str) -> list[dict[str, object]]:
        answers = []
        for answer in repository.get_confirmed_answers_for_intake(intake_id):
            answers.append(
                {
                    "question_code": answer["question_code"],
                    "response_type": answer["response_type"],
                    "value": answer["response_json"],
                    "confirm_state": answer["confirm_state"],
                    "review_state": answer["review_state"],
                    "revision_number": answer["revision_number"],
                    "provenance_references": repository.get_provenance_references_for_revision(
                        answer["revision_id"]
                    ),
                }
            )
        return sorted(answers, key=lambda item: str(item["question_code"]))

    @staticmethod
    def _application_acronym(
        answers: list[dict[str, object]], mappings: tuple[StrictFactMapping, ...]
    ) -> str:
        acronym_mapping = next(
            (mapping for mapping in mappings if mapping.output_key == "application.acronym"), None
        )
        if acronym_mapping is None:
            raise GovernedRunnerError(
                "Preview capture requires an approved application.acronym mapping"
            )
        answer = next(
            (item for item in answers if item["question_code"] == acronym_mapping.question_code),
            None,
        )
        if answer is None:
            raise GovernedRunnerError("Preview capture lacks a confirmed application acronym")
        value = select_fact_value(answer, acronym_mapping)
        if not isinstance(value, str) or not value:
            raise GovernedRunnerError("Preview application acronym is empty")
        return value

    @staticmethod
    def _capture_resources(
        repository: ResourceRepository, intake_id: str
    ) -> list[dict[str, object]]:
        captured = []
        for resource in repository.list_resources_for_intake(intake_id, state="ACTIVE"):
            revision = repository.get_revision(resource["id"], resource["revision_number"])
            if (
                revision is None
                or revision["id"] != resource["current_revision_id"]
                or revision["revision_number"] != resource["revision_number"]
                or revision["resource_state"] != resource["resource_state"]
                or revision["parent_id"] != resource["parent_id"]
                or revision["review_state"] != "CONFIRMED"
            ):
                raise GovernedRunnerError(
                    f"Active resource {resource['id']} lacks a confirmed current revision"
                )
            global_scope = resource["environment"] is None and resource["site"] is None
            captured.append(
                {
                    "resource_id": resource["id"],
                    "logical_key": resource["logical_key"],
                    "kind": resource["kind"],
                    "lifecycle": resource["lifecycle"],
                    "scope": {
                        "environment": resource["environment"],
                        "site_id": resource["site"],
                        "tier": resource["tier"],
                        "environment_state": "GLOBAL"
                        if global_scope
                        else ("KNOWN" if resource["environment"] is not None else "UNKNOWN"),
                        "site_state": "GLOBAL"
                        if global_scope
                        else ("KNOWN" if resource["site"] is not None else "UNKNOWN"),
                    },
                    "global_scope": global_scope,
                    "parent_id": revision["parent_id"],
                    "review_state": revision["review_state"],
                    "revision_number": revision["revision_number"],
                    "provenance_references": revision["provenance_references"],
                    "attributes": revision["payload"],
                }
            )
        return captured

    @staticmethod
    def _capture_relationships(
        repository: ResourceRepository, intake_id: str
    ) -> list[dict[str, object]]:
        captured = []
        for link in repository.list_links_for_intake(intake_id, state="ACTIVE"):
            revision = repository.get_link_revision(link["id"], link["revision_number"])
            if (
                revision is None
                or revision["id"] != link["current_revision_id"]
                or revision["revision_number"] != link["revision_number"]
                or revision["review_state"] != "CONFIRMED"
            ):
                raise GovernedRunnerError(
                    f"Active relationship {link['id']} lacks a confirmed current revision"
                )
            captured.append(
                {
                    "relationship_id": link["id"],
                    "relationship_type": link["relationship_type"],
                    "source_resource_id": link["source_resource_id"],
                    "target_resource_id": link["target_resource_id"],
                    "review_state": revision["review_state"],
                    "revision_number": revision["revision_number"],
                    "provenance_references": revision["provenance_references"],
                }
            )
        return captured

    @staticmethod
    def _capture_wave_rows(
        repository: WaveUtilRepository, application_id: str, intake_id: str
    ) -> list[dict[str, object]]:
        captured = []
        for row in repository.list_rows_for_application(application_id, state="ACTIVE"):
            if row["intake_id"] not in {None, intake_id}:
                continue
            revision = repository.get_current_revision(row["id"])
            if revision is None:
                raise GovernedRunnerError(f"WaveUtil row {row['id']} lacks a current revision")
            captured.append(
                {
                    "row_id": row["id"],
                    "server_name": row["server_name"],
                    "normalized_server_name": row["normalized_server_name"],
                    "environment": row["environment"],
                    "scope": row["scope"],
                    "state": row["state"],
                    "revision_number": revision["revision_number"],
                    "field_values": revision["field_values_json"],
                }
            )
        return captured
