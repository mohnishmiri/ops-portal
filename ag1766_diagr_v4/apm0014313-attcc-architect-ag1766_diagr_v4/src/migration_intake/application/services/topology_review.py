"""Fail-closed review and verified delivery for governed topology runs."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from migration_intake.persistence.repositories.topology import (
    GenerationConflictError,
    TopologyRepository,
)
from migration_intake.persistence.unit_of_work import uow_context

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

    from migration_intake.storage.port import EvidenceStore


class TopologyReviewError(RuntimeError):
    """A topology review or delivery request failed closed."""


class TopologyReviewService:
    """Review immutable generation bundles and serve verified bytes."""

    def __init__(self, session_factory: sessionmaker[Any], storage: EvidenceStore) -> None:
        self._session_factory = session_factory
        self._storage = storage

    def review_run(
        self,
        *,
        run_id: str,
        application_id: str,
        intake_id: str,
        actor_id: str,
        actor_capabilities: set[str] | frozenset[str],
        decision: str,
        rationale: str,
        issue_decisions: dict[str, str] | None = None,
        expected_row_version: int | None = None,
    ) -> dict[str, Any]:
        """Review one exact run after revalidating its persisted bundle."""
        if decision not in {"APPROVED", "REJECTED"}:
            raise TopologyReviewError("Unsupported review decision")
        required_capability = (
            "TOPOLOGY_RUN_APPROVE" if decision == "APPROVED" else "TOPOLOGY_RUN_REJECT"
        )
        if (
            required_capability not in actor_capabilities
            and "TOPOLOGY_APPROVE" not in actor_capabilities
        ):
            raise TopologyReviewError(f"Actor lacks {required_capability} capability")
        rationale = rationale.strip()
        if not rationale:
            raise TopologyReviewError("Review rationale is required")
        issue_decisions = dict(issue_decisions or {})
        if any(
            not isinstance(value, str) or not value.strip() for value in issue_decisions.values()
        ):
            raise TopologyReviewError("Every warning rationale must be nonblank")

        with uow_context(self._session_factory) as uow:
            repository = TopologyRepository(uow._session)
            run = repository.get_generation_run_for_intake(run_id, application_id, intake_id)
            if run is None:
                raise TopologyReviewError("Generation run not found")
            self._validate_reviewable_run(repository, run, issue_decisions)
            if expected_row_version is not None and run["row_version"] != expected_row_version:
                raise TopologyReviewError("Generation run review is stale")
            try:
                updated = repository.review_generation_run(
                    run_id=run_id,
                    expected_row_version=run["row_version"],
                    expected_approval_status="PENDING",
                    decision=decision,
                    actor_id=actor_id,
                    rationale=rationale,
                    issue_decisions=issue_decisions,
                    reviewed_at=datetime.now(tz=UTC),
                    self_review=actor_id == run["requested_by_id"],
                )
            except GenerationConflictError as error:
                raise TopologyReviewError(str(error)) from error
            uow.commit()
            return updated

    def supersede_run(
        self,
        *,
        predecessor_run_id: str,
        successor_run_id: str,
        application_id: str,
        intake_id: str,
        actor_id: str,
        actor_capabilities: set[str] | frozenset[str],
        rationale: str,
        expected_row_version: int | None = None,
    ) -> dict[str, Any]:
        """Supersede one approved run with a matching approved successor."""
        rationale = rationale.strip()
        if not rationale:
            raise TopologyReviewError("Supersession rationale is required")
        if (
            "TOPOLOGY_RUN_SUPERSEDE" not in actor_capabilities
            and "TOPOLOGY_APPROVE" not in actor_capabilities
        ):
            raise TopologyReviewError("Actor lacks TOPOLOGY_RUN_SUPERSEDE capability")
        if predecessor_run_id == successor_run_id:
            raise TopologyReviewError("A run cannot supersede itself")

        with uow_context(self._session_factory) as uow:
            repository = TopologyRepository(uow._session)
            predecessor = repository.get_generation_run_for_intake(
                predecessor_run_id, application_id, intake_id
            )
            successor = repository.get_generation_run_for_intake(
                successor_run_id, application_id, intake_id
            )
            if predecessor is None or successor is None:
                raise TopologyReviewError("Both runs must exist in the requested scope")
            if predecessor["approval_status"] != "APPROVED":
                raise TopologyReviewError("Predecessor must be approved")
            if successor["approval_status"] != "APPROVED":
                raise TopologyReviewError("Successor must be approved")
            for key in (
                "application_id",
                "intake_id",
                "base_artifact_id",
                "base_sha256",
                "capability",
                "input_id",
                "semantic_input_hash",
            ):
                if predecessor[key] != successor[key]:
                    raise TopologyReviewError(f"Run selection pin mismatch: {key}")
            if predecessor["superseded_by_id"] is not None:
                raise TopologyReviewError("Predecessor is already superseded")
            if (
                expected_row_version is not None
                and predecessor["row_version"] != expected_row_version
            ):
                raise TopologyReviewError("Generation supersession is stale")
            try:
                updated = repository.supersede_generation_run(
                    predecessor_run_id=predecessor_run_id,
                    successor_run_id=successor_run_id,
                    expected_row_version=predecessor["row_version"],
                    actor_id=actor_id,
                    rationale=rationale,
                    reviewed_at=datetime.now(tz=UTC),
                )
            except GenerationConflictError as error:
                raise TopologyReviewError(str(error)) from error
            uow.commit()
            return updated

    def verified_artifact(
        self,
        *,
        run_id: str,
        application_id: str,
        intake_id: str,
        artifact_type: str,
    ) -> tuple[bytes, str, str]:
        """Return only bytes matching the immutable persisted receipt."""
        with self._session_factory() as session:
            repository = TopologyRepository(session)
            run = repository.get_generation_run_for_intake(run_id, application_id, intake_id)
            if run is None:
                raise TopologyReviewError("Generation run not found")
            if run["approval_status"] != "APPROVED":
                raise TopologyReviewError("Only approved runs may be downloaded")
            artifact = self._artifact_for_verified_download(repository, run_id, artifact_type)

        return self._read_verified_artifact(artifact)

    def verified_preview_artifact(
        self,
        *,
        run_id: str,
        application_id: str,
        intake_id: str,
        artifact_type: str,
    ) -> tuple[bytes, str, str]:
        """Return receipt-verified bytes from a completed draft preview only."""
        with self._session_factory() as session:
            repository = TopologyRepository(session)
            run = repository.get_generation_run_for_intake(run_id, application_id, intake_id)
            if run is None:
                raise TopologyReviewError("Generation run not found")
            if run["mode"] != "DRAFT_PREVIEW" or run["phase"] != "COMPLETED":
                raise TopologyReviewError("Only completed draft previews may be downloaded")
            artifact = self._artifact_for_verified_download(repository, run_id, artifact_type)

        return self._read_verified_artifact(artifact)

    @staticmethod
    def _artifact_for_verified_download(
        repository: TopologyRepository, run_id: str, artifact_type: str
    ) -> dict[str, Any]:
        artifact = repository.get_artifact_by_type(run_id, artifact_type)
        if artifact is None:
            raise TopologyReviewError("Requested artifact is unavailable")
        return artifact

    def _read_verified_artifact(self, artifact: dict[str, Any]) -> tuple[bytes, str, str]:
        try:
            with self._storage.retrieve(artifact["content_address"]) as stream:
                content = stream.read(50 * 1024 * 1024 + 1)
        except (OSError, ValueError) as error:
            raise TopologyReviewError("Verified artifact is unavailable") from error
        if len(content) != artifact["size_bytes"]:
            raise TopologyReviewError("Verified artifact size does not match receipt")
        if hashlib.sha256(content).hexdigest() != artifact["sha256_hex"]:
            raise TopologyReviewError("Verified artifact hash does not match receipt")
        return content, artifact["filename"], artifact["mime_type"]

    def _validate_reviewable_run(
        self,
        repository: TopologyRepository,
        run: dict[str, Any],
        issue_decisions: dict[str, str],
    ) -> None:
        if run["mode"] != "OFFICIAL_SNAPSHOT" or run["authority"] != "OFFICIAL_SNAPSHOT":
            raise TopologyReviewError("Preview or legacy runs cannot be approved")
        if run["phase"] != "COMPLETED" or run["status"] not in {
            "READY_FOR_REVIEW",
            "GENERATED_WITH_GAPS",
        }:
            raise TopologyReviewError("Only completed runs ready for review may be reviewed")
        if run["approval_status"] != "PENDING":
            raise TopologyReviewError("Generation run has already been reviewed")
        if not run["input_id"] or not run["manifest_hash"]:
            raise TopologyReviewError("Immutable input and manifest pins are required")
        input_record = repository.get_topology_input(run["input_id"])
        if input_record is None:
            raise TopologyReviewError("Immutable topology input is unavailable")
        base = repository.get_base_artifact(str(run["base_artifact_id"]))
        if (
            base is None
            or base["review_state"] != "APPROVED"
            or base["lifecycle"] != "ACTIVE"
            or base["compatibility_id"] != input_record["compatibility_id"]
            or base["profile_hash"] != input_record["profile_hash"]
            or base["capability"] != input_record["capability"]
        ):
            raise TopologyReviewError("Governed base is no longer eligible for review")
        compatibility_id = input_record.get("compatibility_id")
        if compatibility_id is None:
            raise TopologyReviewError("Immutable topology input lacks compatibility pins")
        compatibility = repository.get_topology_compatibility(str(compatibility_id))
        if (
            compatibility is None
            or compatibility["compatibility_key"] != input_record["compatibility_key"]
            or compatibility["result_hash"] != input_record["compatibility_result_hash"]
        ):
            raise TopologyReviewError("Base compatibility pins are stale")
        for run_key, input_key in (
            ("base_artifact_id", "base_artifact_id"),
            ("base_sha256", "base_sha256"),
            ("capability", "capability"),
            ("semantic_input_hash", "semantic_input_hash"),
        ):
            if run[run_key] != input_record[input_key]:
                raise TopologyReviewError(f"Run pin mismatch: {run_key}")

        artifacts = {
            item["artifact_type"]: item for item in repository.list_artifacts_for_run(run["id"])
        }
        if set(artifacts) != {"DIAGRAM", "GAP_REPORT", "MANIFEST"}:
            raise TopologyReviewError("Complete diagram, report, and manifest bundle is required")
        for artifact_type in ("DIAGRAM", "GAP_REPORT", "MANIFEST"):
            self._read_verified_artifact(artifacts[artifact_type])
        manifest_artifact = artifacts["MANIFEST"]
        if manifest_artifact["sha256_hex"] != run["manifest_hash"]:
            raise TopologyReviewError("Manifest hash does not match the run")
        try:
            with self._storage.retrieve(manifest_artifact["content_address"]) as stream:
                manifest_bytes = stream.read(50 * 1024 * 1024 + 1)
            if len(manifest_bytes) != manifest_artifact["size_bytes"]:
                raise TopologyReviewError("Manifest size does not match receipt")
            if hashlib.sha256(manifest_bytes).hexdigest() != manifest_artifact["sha256_hex"]:
                raise TopologyReviewError("Manifest digest does not match receipt")
            manifest = json.loads(manifest_bytes.decode("utf-8"))
        except (OSError, ValueError, UnicodeError) as error:
            raise TopologyReviewError("Manifest cannot be verified") from error
        if not isinstance(manifest, dict):
            raise TopologyReviewError("Manifest must be an object")
        if manifest.get("result_status") != run["status"]:
            raise TopologyReviewError("Manifest status disagrees with run status")
        readiness = run.get("readiness_json") or {}
        if readiness.get("status") != run["status"]:
            raise TopologyReviewError("Readiness status disagrees with run status")
        blockers = readiness.get("blockers") or []
        if blockers:
            raise TopologyReviewError("Blocking readiness issues cannot be approved")
        warnings = readiness.get("warnings") or []
        warning_ids = {str(issue) for issue in warnings}
        missing = sorted(warning_ids - set(issue_decisions))
        unknown = sorted(set(issue_decisions) - warning_ids)
        if missing:
            raise TopologyReviewError("Every warning requires an issue-level rationale")
        if unknown:
            raise TopologyReviewError("Unknown warning issue decision")
