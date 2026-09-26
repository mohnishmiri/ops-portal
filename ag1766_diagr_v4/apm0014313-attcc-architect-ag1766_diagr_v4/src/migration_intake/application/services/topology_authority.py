"""Publish immutable topology v3 authority from reviewed canonical state."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from migration_intake.application.errors import ConcurrencyConflictError
from migration_intake.persistence.repositories.answers import AnswerRepository
from migration_intake.persistence.repositories.applications import ApplicationRepository
from migration_intake.persistence.repositories.catalogs import CatalogRepository
from migration_intake.persistence.repositories.intakes import IntakeRepository
from migration_intake.persistence.repositories.interfaces import InterfaceRepository
from migration_intake.persistence.repositories.resources import ResourceRepository
from migration_intake.persistence.repositories.snapshots import SnapshotRepository
from migration_intake.persistence.repositories.wave_util import WaveUtilRepository
from migration_intake.persistence.unit_of_work import uow_context
from migration_intake.topology.contracts import normalize_timestamp, serialize_snapshot_document

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker


class TopologyAuthorityError(RuntimeError):
    """The immutable topology authority could not be published safely."""


class TopologyAuthorityService:
    """Create immutable v3 snapshots while retaining legacy snapshot bytes."""

    def __init__(self, session_factory: sessionmaker[Any]) -> None:
        self._session_factory = session_factory

    def publish_v3(self, intake_id: str, actor_id: str) -> dict[str, object]:
        now = datetime.now(UTC)
        with uow_context(self._session_factory) as uow:
            session = uow._session
            intake_repo = IntakeRepository(session)
            intake_repo.begin_capture_fence()
            intake = intake_repo.get_for_update(intake_id)
            if intake is None:
                raise TopologyAuthorityError("Intake was not found")
            if intake["state"] != "FROZEN":
                raise TopologyAuthorityError("Official topology authority requires a frozen intake")
            existing = SnapshotRepository(session).get_by_intake_id(intake_id)
            if existing is not None:
                if existing["schema_version"] == "3.0.0":
                    return existing
                raise TopologyAuthorityError(
                    "Legacy snapshot is immutable and cannot be relabeled as topology v3"
                )
            app_repo = ApplicationRepository(session)
            application = app_repo.get_for_update(intake["application_id"])
            catalog = CatalogRepository(session).get_release(intake["catalog_id"])
            if application is None or catalog is None or not catalog["catalog_hash"]:
                raise TopologyAuthorityError("Application or compiled catalog is unavailable")
            interface_epoch, interfaces = InterfaceRepository(session).capture_projection_rows(
                application["id"]
            )
            if interface_epoch != application["interface_epoch"]:
                raise ConcurrencyConflictError("Interface register changed during publication")
            resources = self._resources(ResourceRepository(session), intake_id)
            relationships = self._relationships(ResourceRepository(session), intake_id)
            document = {
                "schema_version": "3.0.0",
                "application": {
                    "id": application["id"],
                    "name": application["display_name"],
                    "acronym": self._acronym(AnswerRepository(session), intake_id),
                    "identifiers": app_repo.list_identifiers(application["id"]),
                },
                "catalog": {
                    "id": catalog["id"],
                    "version": catalog["semantic_version"],
                    "source_sha256": catalog["source_sha256"],
                    "catalog_hash": catalog["catalog_hash"],
                    "compiler_version": catalog["compiler_version"],
                },
                "intake": {
                    "id": intake_id,
                    "state": intake["state"],
                    "frozen_at": normalize_timestamp(intake["updated_at"]),
                    "frozen_by": intake["created_by_id"],
                    "row_version": intake["row_version"],
                    "content_epoch": intake["content_epoch"],
                },
                "answers": self._answers(AnswerRepository(session), intake_id),
                "interface_register": {
                    "interface_epoch": interface_epoch,
                    "rows": interfaces,
                },
                "resources": resources,
                "relationships": relationships,
                "wave_util_rows": self._wave_rows(
                    WaveUtilRepository(session), application["id"]
                ),
                "permitted_gaps": [],
            }
            contract = serialize_snapshot_document(document)
            created = SnapshotRepository(session).create_snapshot(
                snapshot_id=__import__("uuid").uuid4().hex,
                intake_id=intake_id,
                catalog_id=intake["catalog_id"],
                schema_version="3.0.0",
                catalog_sha256=catalog["source_sha256"],
                canonical_json=contract.canonical_json,
                sha256_hex=contract.sha256_hex,
                created_at=now,
                created_by_id=actor_id,
            )
            uow.commit()
            return created

    @staticmethod
    def _answers(repository: AnswerRepository, intake_id: str) -> list[dict[str, object]]:
        return [
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
            for answer in repository.get_confirmed_answers_for_intake(intake_id)
        ]

    @staticmethod
    def _acronym(repository: AnswerRepository, intake_id: str) -> str:
        for answer in repository.get_confirmed_answers_for_intake(intake_id):
            value = answer["response_json"]
            if answer["question_code"] == "CTL-002" and isinstance(value, dict):
                acronym = value.get("second")
                if isinstance(acronym, str) and acronym:
                    return acronym
        raise TopologyAuthorityError("Confirmed application acronym is required")

    @staticmethod
    def _resources(repository: ResourceRepository, intake_id: str) -> list[dict[str, object]]:
        result = []
        for resource in repository.list_resources_for_intake(intake_id, state="ACTIVE"):
            revision = repository.get_revision(resource["id"], resource["revision_number"])
            if revision is None or revision["review_state"] != "CONFIRMED":
                continue
            result.append(_json_safe({**resource, "revision": revision}))
        return cast("list[dict[str, object]]", result)

    @staticmethod
    def _relationships(repository: ResourceRepository, intake_id: str) -> list[dict[str, object]]:
        result = []
        for link in repository.list_links_for_intake(intake_id, state="ACTIVE"):
            revision = repository.get_link_revision(link["id"], link["revision_number"])
            if revision is None or revision["review_state"] != "CONFIRMED":
                continue
            result.append(_json_safe({**link, "revision": revision}))
        return cast("list[dict[str, object]]", result)

    @staticmethod
    def _wave_rows(repository: WaveUtilRepository, application_id: str) -> list[dict[str, object]]:
        result = []
        for row in repository.list_rows_for_application(application_id, state="ACTIVE"):
            revision = repository.get_current_revision(row["id"])
            result.append(_json_safe({**row, "revision": revision}))
        return cast("list[dict[str, object]]", result)


def _json_safe(value: object) -> object:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
