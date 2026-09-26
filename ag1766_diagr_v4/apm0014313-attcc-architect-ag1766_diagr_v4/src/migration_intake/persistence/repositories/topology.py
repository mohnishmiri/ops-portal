"""Persistence adapter for legacy and governed topology records."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import desc, func, select, update
from sqlalchemy.exc import IntegrityError

from migration_intake.persistence.models_topology import (
    GeneratedArtifact,
    GenerationReservation,
    GenerationRun,
    TopologyBaseArtifact,
    TopologyCapture,
    TopologyCompatibility,
    TopologyInput,
    TopologyReview,
)

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session


class GenerationConflictError(RuntimeError):
    """A reservation, version, phase, or lease compare-and-swap failed."""


class DuplicateArtifactError(RuntimeError):
    """A run already has an artifact of the requested type."""


class TopologyRepository:
    """Repository whose transaction is owned by the supplied session."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_base_artifact(self, **values: Any) -> dict[str, Any]:
        artifact_id = values.pop("artifact_id")
        artifact = TopologyBaseArtifact(id=artifact_id, **values)
        self._session.add(artifact)
        self._session.flush()
        return self._to_dict(artifact)

    def get_base_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        return self._one(TopologyBaseArtifact, artifact_id)

    def get_base_artifact_for_update(self, artifact_id: str) -> dict[str, Any] | None:
        row = self._session.execute(
            select(TopologyBaseArtifact)
            .where(TopologyBaseArtifact.id == artifact_id)
            .with_for_update()
        ).scalar_one_or_none()
        return self._to_dict(row) if row is not None else None

    def get_base_artifact_by_hash(self, sha256_hex: str) -> dict[str, Any] | None:
        row = self._session.execute(
            select(TopologyBaseArtifact)
            .where(TopologyBaseArtifact.sha256_hex == sha256_hex)
            .order_by(desc(TopologyBaseArtifact.created_at))
            .limit(1)
        ).scalars().first()
        return self._to_dict(row) if row is not None else None

    def list_base_artifacts_for_intake(self, intake_id: str) -> list[dict[str, Any]]:
        rows = self._session.execute(
            select(TopologyBaseArtifact)
            .where(TopologyBaseArtifact.intake_id == intake_id)
            .order_by(desc(TopologyBaseArtifact.created_at))
        ).scalars().all()
        return [self._to_dict(row) for row in rows]

    def create_topology_compatibility(self, **values: Any) -> dict[str, Any]:
        row = TopologyCompatibility(**values)
        self._session.add(row)
        self._session.flush()
        return self._to_dict(row)

    def get_topology_compatibility(self, compatibility_id: str) -> dict[str, Any] | None:
        return self._one(TopologyCompatibility, compatibility_id)

    def list_compatibility_for_base(self, base_artifact_id: str) -> list[dict[str, Any]]:
        rows = self._session.execute(
            select(TopologyCompatibility)
            .where(TopologyCompatibility.base_artifact_id == base_artifact_id)
            .order_by(TopologyCompatibility.checked_at)
        ).scalars().all()
        return [self._to_dict(row) for row in rows]

    def mark_base_compatible(
        self,
        *,
        artifact_id: str,
        expected_row_version: int,
        **values: Any,
    ) -> dict[str, Any]:
        allowed = {
            "compatibility_id",
            "profile_id",
            "profile_version",
            "profile_hash",
            "capability",
            "selection_json",
            "selection_hash",
        }
        values = {key: value for key, value in values.items() if key in allowed}
        values.update(review_state="COMPATIBLE", row_version=expected_row_version + 1)
        return self._cas_update(
            TopologyBaseArtifact,
            artifact_id,
            expected_row_version,
            values,
        )

    def review_base_artifact(
        self,
        *,
        artifact_id: str,
        review_id: str,
        decision: str,
        actor_id: str,
        rationale: str,
        reviewed_at: datetime,
        expected_row_version: int,
        compatibility_result_hash: str | None = None,
        issue_decisions: dict[str, Any] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        state = {"APPROVE": "APPROVED", "REJECT": "REJECTED", "SUPERSEDE": "SUPERSEDED"}[decision]
        base = self._cas_update(
            TopologyBaseArtifact,
            artifact_id,
            expected_row_version,
            {
                "review_state": state,
                "authority": "OFFICIAL_SNAPSHOT" if decision == "APPROVE" else "LEGACY_UNPINNED",
                "reviewed_by_id": actor_id,
                "reviewed_at": reviewed_at,
                "review_rationale": rationale,
                "row_version": expected_row_version + 1,
            },
        )
        self._session.add(
            TopologyReview(
                id=review_id,
                entity_type="BASE",
                entity_id=artifact_id,
                base_artifact_id=artifact_id,
                decision=decision,
                compatibility_result_hash=compatibility_result_hash,
                rationale=rationale,
                issue_decisions=issue_decisions,
                actor_id=actor_id,
                reviewed_at=reviewed_at,
            )
        )
        self._session.flush()
        return base

    def create_topology_capture(self, **values: Any) -> dict[str, Any]:
        capture_id = values.pop("capture_id")
        row = TopologyCapture(id=capture_id, **values)
        self._session.add(row)
        self._session.flush()
        return self._to_dict(row)

    def create_topology_input(self, **values: Any) -> dict[str, Any]:
        input_id = values.pop("input_id")
        row = TopologyInput(id=input_id, **values)
        self._session.add(row)
        self._session.flush()
        return self._to_dict(row)

    def get_topology_input(self, input_id: str) -> dict[str, Any] | None:
        return self._one(TopologyInput, input_id)

    def get_or_create_topology_input(self, **values: Any) -> dict[str, Any]:
        existing = self._session.execute(
            select(TopologyInput).where(
                TopologyInput.intake_id == values["intake_id"],
                TopologyInput.semantic_input_hash == values["semantic_input_hash"],
            )
        ).scalar_one_or_none()
        if existing is not None:
            return self._to_dict(existing)
        return self.create_topology_input(**values)

    def reserve_generation_run(
        self,
        *,
        run_id: str,
        input_id: str,
        application_id: str,
        intake_id: str,
        semantic_input_hash: str,
        requested_by_id: str,
        requested_at: datetime,
        mode: str | None = None,
        capability: str | None = None,
        base_artifact_id: str | None = None,
        base_sha256: str | None = None,
        snapshot_id: str | None = None,
        snapshot_sha256: str | None = None,
        catalog_sha256: str | None = None,
        rerun_reason: str | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        existing = self._reserved_run(intake_id, semantic_input_hash)
        if existing is not None and rerun_reason is None:
            return existing
        attempt_number = 0
        if existing is not None:
            attempt_number = self._next_attempt_number(intake_id, semantic_input_hash)
        input_row = self._session.get(TopologyInput, input_id)
        if (
            input_row is None
            or str(input_row.intake_id) != intake_id
            or str(input_row.application_id) != application_id
        ):
            raise GenerationConflictError("TOPOLOGY_INPUT_SCOPE_CONFLICT")
        run = GenerationRun(
            id=run_id,
            input_id=input_id,
            application_id=application_id,
            intake_id=intake_id,
            snapshot_id=snapshot_id or input_row.snapshot_id,
            snapshot_sha256=snapshot_sha256,
            catalog_sha256=catalog_sha256 or input_row.catalog_sha256,
            base_artifact_id=base_artifact_id or input_row.base_artifact_id,
            base_sha256=base_sha256 or input_row.base_sha256,
            mode=mode or input_row.mode,
            capability=capability or input_row.capability,
            authority=(
                "DRAFT_PREVIEW"
                if (mode or input_row.mode) == "DRAFT_PREVIEW"
                else "SNAPSHOT_PINNED"
            ),
            phase="PENDING",
            status="PENDING",
            semantic_input_hash=semantic_input_hash,
            attempt_number=attempt_number,
            rerun_reason=rerun_reason,
            requested_by_id=requested_by_id,
            requested_at=requested_at,
            created_at=requested_at,
        )
        reservation = None
        if existing is None:
            reservation = GenerationReservation(
                id=run_id,
                intake_id=intake_id,
                semantic_input_hash=semantic_input_hash,
                run_id=run_id,
                created_at=requested_at,
            )
        try:
            with self._session.begin_nested():
                self._session.add(run)
                self._session.flush()
                if reservation is not None:
                    self._session.add(reservation)
                    self._session.flush()
        except IntegrityError:
            existing = self._reserved_run(intake_id, semantic_input_hash)
            if existing is None:
                raise GenerationConflictError("GENERATION_RESERVATION_CONFLICT") from None
            return existing
        return self._to_dict(run)

    def transition_generation_phase(
        self,
        *,
        run_id: str,
        expected_row_version: int,
        expected_phase: str,
        new_phase: str,
        **values: Any,
    ) -> dict[str, Any]:
        values.update(phase=new_phase, row_version=expected_row_version + 1)
        return self._cas_run(run_id, expected_row_version, expected_phase, values)

    def claim_generation_run(
        self,
        *,
        run_id: str,
        expected_row_version: int,
        lease_token: str,
        lease_expires_at: datetime,
        **_: Any,
    ) -> dict[str, Any]:
        return self._cas_run(
            run_id,
            expected_row_version,
            "PENDING",
            {
                "phase": "RENDERING",
                "status": "RUNNING",
                "lease_token": lease_token,
                "lease_expires_at": lease_expires_at,
                "row_version": expected_row_version + 1,
            },
        )

    def transition_leased_generation_phase(
        self,
        *,
        run_id: str,
        expected_row_version: int,
        expected_phase: str,
        new_phase: str,
        lease_token: str,
    ) -> dict[str, Any]:
        result = self._session.execute(
            update(GenerationRun)
            .where(
                GenerationRun.id == run_id,
                GenerationRun.row_version == expected_row_version,
                GenerationRun.phase == expected_phase,
                GenerationRun.lease_token == lease_token,
            )
            .values(phase=new_phase, row_version=expected_row_version + 1)
        )
        if getattr(result, "rowcount", 0) != 1:
            raise GenerationConflictError("generation lease conflict")
        self._session.flush()
        self._session.expire_all()
        return self.get_generation_run(run_id) or self._missing_run()

    def finalize_generation_run(
        self,
        *,
        run_id: str,
        expected_row_version: int,
        lease_token: str,
        manifest_hash: str,
        readiness_json: dict[str, Any],
        artifacts: list[dict[str, Any]],
        actor_id: str,
        finalized_at: datetime,
    ) -> dict[str, Any]:
        _ = actor_id
        run = self._session.execute(
            select(GenerationRun).where(
                GenerationRun.id == run_id,
                GenerationRun.row_version == expected_row_version,
                GenerationRun.phase == "STORING",
                GenerationRun.lease_token == lease_token,
            )
        ).scalar_one_or_none()
        if run is None:
            raise GenerationConflictError("GENERATION_LEASE_CONFLICT")
        with self._session.begin_nested():
            for artifact in artifacts:
                self.create_generated_artifact(
                    generation_run_id=run_id,
                    created_at=finalized_at,
                    **artifact,
                )
        run.phase = "COMPLETED"
        run.status = str(readiness_json["status"])
        run.readiness_json = readiness_json
        run.manifest_hash = manifest_hash
        run.completed_at = finalized_at
        run.lease_token = None
        run.lease_expires_at = None
        run.row_version = expected_row_version + 1
        self._session.flush()
        return self._to_dict(run)

    def fail_storing_generation_run(
        self,
        *,
        run_id: str,
        expected_row_version: int,
        lease_token: str,
        error_message: str,
    ) -> dict[str, Any]:
        return self._fail_leased_run(
            run_id=run_id,
            expected_row_version=expected_row_version,
            lease_token=lease_token,
            expected_phase="STORING",
            error_message=error_message,
            readiness_json={"failure_phase": "STORING"},
        )

    def fail_leased_generation_run(
        self,
        *,
        run_id: str,
        expected_row_version: int,
        lease_token: str,
        expected_phase: str,
        error_message: str,
        readiness_json: dict[str, Any] | None = None,
        **_: Any,
    ) -> dict[str, Any]:
        return self._fail_leased_run(
            run_id=run_id,
            expected_row_version=expected_row_version,
            lease_token=lease_token,
            expected_phase=expected_phase,
            error_message=error_message,
            readiness_json=readiness_json or {"failure_phase": expected_phase},
        )

    def claim_expired_generation_run(
        self,
        *,
        run_id: str,
        actor_id: str,
        now: datetime,
        new_lease_token: str,
        lease_expires_at: datetime,
    ) -> dict[str, Any]:
        run = self._session.get(GenerationRun, run_id)
        if (
            run is None
            or run.lease_expires_at is None
            or run.lease_expires_at >= now
            or run.phase in {"COMPLETED", "FAILED"}
        ):
            raise GenerationConflictError("Run has a healthy lease or is terminal")
        expected_version = int(run.row_version)
        original_phase = str(run.phase)
        result = self._session.execute(
            update(GenerationRun)
            .where(
                GenerationRun.id == run_id,
                GenerationRun.row_version == expected_version,
                GenerationRun.lease_token == run.lease_token,
                GenerationRun.lease_expires_at < now,
            )
            .values(
                lease_token=new_lease_token,
                lease_expires_at=lease_expires_at,
                row_version=expected_version + 1,
                readiness_json={"recovery_phase": original_phase, "claimed_by": actor_id},
            )
        )
        if getattr(result, "rowcount", 0) != 1:
            raise GenerationConflictError("GENERATION_RECOVERY_CONFLICT")
        self._session.flush()
        self._session.expire_all()
        return self.get_generation_run(run_id) or self._missing_run()

    def mark_recovery_failed(
        self,
        *,
        run_id: str,
        expected_row_version: int,
        lease_token: str,
        actor_id: str,
        error_message: str,
        reviewed_at: datetime,
    ) -> dict[str, Any]:
        run = self._session.get(GenerationRun, run_id)
        if run is None or int(run.row_version) != expected_row_version:
            raise GenerationConflictError("GENERATION_RECOVERY_CONFLICT")
        failure_phase = (run.readiness_json or {}).get("recovery_phase", run.phase)
        result = self._fail_leased_run(
            run_id=run_id,
            expected_row_version=expected_row_version,
            lease_token=lease_token,
            expected_phase=str(run.phase),
            error_message=error_message,
            readiness_json={"failure_phase": failure_phase, "recovered": True},
        )
        self._session.add(
            TopologyReview(
                id=run_id,
                entity_type="RUN_RECOVERY",
                entity_id=run_id,
                run_id=run_id,
                decision="FAILED",
                rationale=error_message,
                actor_id=actor_id,
                reviewed_at=reviewed_at,
            )
        )
        self._session.flush()
        return result

    def review_generation_run(
        self,
        *,
        run_id: str,
        expected_row_version: int,
        expected_approval_status: str,
        decision: str,
        actor_id: str,
        rationale: str,
        issue_decisions: dict[str, str],
        reviewed_at: datetime,
        self_review: bool,
    ) -> dict[str, Any]:
        result = self._session.execute(
            update(GenerationRun)
            .where(
                GenerationRun.id == run_id,
                GenerationRun.row_version == expected_row_version,
                GenerationRun.approval_status == expected_approval_status,
            )
            .values(
                approval_status=decision,
                approved_by_id=actor_id,
                approved_at=reviewed_at,
                approval_rationale=rationale,
                row_version=expected_row_version + 1,
            )
        )
        if getattr(result, "rowcount", 0) != 1:
            raise GenerationConflictError("Generation run has already been reviewed")
        self._session.add(
            TopologyReview(
                id=str(__import__("uuid").uuid4()),
                entity_type="RUN",
                entity_id=run_id,
                run_id=run_id,
                decision=decision,
                rationale=rationale,
                issue_decisions=issue_decisions,
                actor_id=actor_id,
                self_review=int(self_review),
                reviewed_at=reviewed_at,
            )
        )
        self._session.flush()
        return self.get_generation_run(run_id) or self._missing_run()

    def supersede_generation_run(
        self,
        *,
        predecessor_run_id: str,
        successor_run_id: str,
        expected_row_version: int,
        actor_id: str,
        rationale: str,
        reviewed_at: datetime,
    ) -> dict[str, Any]:
        result = self._session.execute(
            update(GenerationRun)
            .where(
                GenerationRun.id == predecessor_run_id,
                GenerationRun.row_version == expected_row_version,
                GenerationRun.approval_status == "APPROVED",
                GenerationRun.superseded_by_id.is_(None),
            )
            .values(
                approval_status="SUPERSEDED",
                superseded_by_id=successor_run_id,
                row_version=expected_row_version + 1,
            )
        )
        if getattr(result, "rowcount", 0) != 1:
            raise GenerationConflictError("GENERATION_SUPERSESSION_CONFLICT")
        self._session.add(
            TopologyReview(
                id=str(__import__("uuid").uuid4()),
                entity_type="RUN_SUPERSESSION",
                entity_id=predecessor_run_id,
                run_id=predecessor_run_id,
                decision="SUPERSEDED",
                rationale=rationale,
                issue_decisions={"successor_run_id": successor_run_id},
                actor_id=actor_id,
                reviewed_at=reviewed_at,
            )
        )
        self._session.flush()
        return self.get_generation_run(predecessor_run_id) or self._missing_run()

    def create_generation_run(self, **values: Any) -> dict[str, Any]:
        run_id = values.pop("run_id")
        row = GenerationRun(id=run_id, **values)
        self._session.add(row)
        self._session.flush()
        return self._to_dict(row)

    def get_generation_run(self, run_id: str) -> dict[str, Any] | None:
        return self._one(GenerationRun, run_id)

    def get_approved_official_run_for_snapshot(
        self, *, application_id: str, intake_id: str, snapshot_id: str
    ) -> dict[str, Any] | None:
        row = self._session.execute(
            select(GenerationRun)
            .where(
                GenerationRun.application_id == application_id,
                GenerationRun.intake_id == intake_id,
                GenerationRun.snapshot_id == snapshot_id,
                GenerationRun.mode == "OFFICIAL_SNAPSHOT",
                GenerationRun.authority.in_({"OFFICIAL_SNAPSHOT", "SNAPSHOT_PINNED"}),
                GenerationRun.phase == "COMPLETED",
                GenerationRun.approval_status == "APPROVED",
                GenerationRun.superseded_by_id.is_(None),
            )
            .order_by(desc(GenerationRun.completed_at), desc(GenerationRun.created_at))
            .limit(1)
        ).scalars().first()
        return self._to_dict(row) if row is not None else None

    def get_generation_run_for_intake(
        self, run_id: str, application_id: str, intake_id: str
    ) -> dict[str, Any] | None:
        row = self._session.execute(
            select(GenerationRun).where(
                GenerationRun.id == run_id,
                GenerationRun.application_id == application_id,
                GenerationRun.intake_id == intake_id,
            )
        ).scalar_one_or_none()
        return self._to_dict(row) if row is not None else None

    def list_generation_runs_for_intake(self, intake_id: str) -> list[dict[str, Any]]:
        rows = self._session.execute(
            select(GenerationRun)
            .where(GenerationRun.intake_id == intake_id)
            .order_by(desc(GenerationRun.created_at))
        ).scalars().all()
        return [self._to_dict(row) for row in rows]

    def list_runs_with_leases(self, intake_id: str | None) -> list[dict[str, Any]]:
        statement = select(GenerationRun).where(GenerationRun.lease_token.is_not(None))
        if intake_id is not None:
            statement = statement.where(GenerationRun.intake_id == intake_id)
        rows = self._session.execute(
            statement.order_by(GenerationRun.created_at)
        ).scalars().all()
        return [self._to_dict(row) for row in rows]

    def update_run_status(self, run_id: str, status: str, **values: Any) -> dict[str, Any] | None:
        row = self._session.get(GenerationRun, run_id)
        if row is None:
            return None
        row.status = status
        for key, value in values.items():
            if value is not None:
                setattr(row, key, value)
        self._session.flush()
        return self._to_dict(row)

    def update_run_approval(
        self, run_id: str, approval_status: str, **values: Any
    ) -> dict[str, Any] | None:
        row = self._session.get(GenerationRun, run_id)
        if row is None:
            return None
        row.approval_status = approval_status
        for key, value in values.items():
            if value is not None:
                setattr(row, key, value)
        self._session.flush()
        return self._to_dict(row)

    def create_generated_artifact(self, **values: Any) -> dict[str, Any]:
        artifact_id = values.pop("artifact_id")
        if self.get_artifact_by_type(values["generation_run_id"], values["artifact_type"]):
            raise DuplicateArtifactError("DUPLICATE_ARTIFACT_TYPE")
        row = GeneratedArtifact(id=artifact_id, **values)
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError as error:
            raise DuplicateArtifactError("DUPLICATE_ARTIFACT_TYPE") from error
        return self._to_dict(row)

    def get_generated_artifact(self, artifact_id: str) -> dict[str, Any] | None:
        return self._one(GeneratedArtifact, artifact_id)

    def list_artifacts_for_run(self, run_id: str) -> list[dict[str, Any]]:
        rows = self._session.execute(
            select(GeneratedArtifact)
            .where(GeneratedArtifact.generation_run_id == run_id)
            .order_by(GeneratedArtifact.artifact_type)
        ).scalars().all()
        return [self._to_dict(row) for row in rows]

    def get_artifact_by_type(self, run_id: str, artifact_type: str) -> dict[str, Any] | None:
        row = self._session.execute(
            select(GeneratedArtifact).where(
                GeneratedArtifact.generation_run_id == run_id,
                GeneratedArtifact.artifact_type == artifact_type,
            )
        ).scalar_one_or_none()
        return self._to_dict(row) if row is not None else None

    def _fail_leased_run(
        self,
        *,
        run_id: str,
        expected_row_version: int,
        lease_token: str,
        expected_phase: str,
        error_message: str,
        readiness_json: dict[str, Any],
    ) -> dict[str, Any]:
        result = self._session.execute(
            update(GenerationRun)
            .where(
                GenerationRun.id == run_id,
                GenerationRun.row_version == expected_row_version,
                GenerationRun.phase == expected_phase,
                GenerationRun.lease_token == lease_token,
            )
            .values(
                phase="FAILED",
                status="FAILED",
                error_message=error_message,
                readiness_json=readiness_json,
                lease_token=None,
                lease_expires_at=None,
                row_version=expected_row_version + 1,
            )
        )
        if getattr(result, "rowcount", 0) != 1:
            raise GenerationConflictError("generation lease conflict")
        self._session.flush()
        self._session.expire_all()
        return self.get_generation_run(run_id) or self._missing_run()

    def _next_attempt_number(self, intake_id: str, semantic_input_hash: str) -> int:
        current = self._session.execute(
            select(func.max(GenerationRun.attempt_number)).where(
                GenerationRun.intake_id == intake_id,
                GenerationRun.semantic_input_hash == semantic_input_hash,
            )
        ).scalar_one()
        return int(current or 0) + 1

    def _reserved_run(self, intake_id: str, semantic_input_hash: str) -> dict[str, Any] | None:
        row = self._session.execute(
            select(GenerationRun)
            .join(GenerationReservation, GenerationReservation.run_id == GenerationRun.id)
            .where(
                GenerationReservation.intake_id == intake_id,
                GenerationReservation.semantic_input_hash == semantic_input_hash,
            )
        ).scalar_one_or_none()
        return self._to_dict(row) if row is not None else None

    def _cas_run(
        self,
        run_id: str,
        expected_row_version: int,
        expected_phase: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        result = self._session.execute(
            update(GenerationRun)
            .where(
                GenerationRun.id == run_id,
                GenerationRun.row_version == expected_row_version,
                GenerationRun.phase == expected_phase,
            )
            .values(**values)
        )
        if getattr(result, "rowcount", 0) != 1:
            raise GenerationConflictError("GENERATION_CAS_CONFLICT")
        self._session.flush()
        return self.get_generation_run(run_id) or self._missing_run()

    def _cas_update(
        self,
        model: type[Any],
        entity_id: str,
        expected_row_version: int,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        result = self._session.execute(
            update(model)
            .where(model.id == entity_id, model.row_version == expected_row_version)
            .values(**values)
        )
        if getattr(result, "rowcount", 0) != 1:
            raise GenerationConflictError("TOPOLOGY_CAS_CONFLICT")
        self._session.flush()
        row = self._session.get(model, entity_id)
        if row is None:
            return self._missing_run()
        return self._to_dict(row)

    def _one(self, model: type[Any], entity_id: str) -> dict[str, Any] | None:
        row = self._session.get(model, entity_id)
        return self._to_dict(row) if row is not None else None

    @staticmethod
    def _to_dict(row: Any) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for column in row.__table__.columns:
            value = getattr(row, column.name)
            if value is not None and (column.name == "id" or column.name.endswith("_id")):
                value = str(value)
            result[column.name] = value
        return result

    @staticmethod
    def _missing_run() -> dict[str, Any]:
        raise GenerationConflictError("GENERATION_RUN_NOT_FOUND")
