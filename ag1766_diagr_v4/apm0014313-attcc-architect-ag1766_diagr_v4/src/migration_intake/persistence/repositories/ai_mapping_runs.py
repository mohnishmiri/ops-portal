"""
Repository for ai_mapping_runs lineage records.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import select, update

from migration_intake.persistence.models_ai import AIMappingRun

if TYPE_CHECKING:
    from datetime import datetime

    from sqlalchemy.orm import Session


class AIMappingRunRepository:
    """Persistence adapter for append-only AI mapping run lineage."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_run(
        self,
        *,
        run_id: str,
        application_id: str,
        intake_id: str,
        evidence_item_id: str,
        provider_id: str,
        profile_id: str,
        model_id: str,
        prompt_template_version: str,
        classification: str,
        fragment_count: int,
        started_at: datetime,
        created_by_id: str,
        created_at: datetime,
    ) -> dict[str, Any]:
        row = AIMappingRun(
            id=run_id,
            application_id=application_id,
            intake_id=intake_id,
            evidence_item_id=evidence_item_id,
            provider_id=provider_id,
            profile_id=profile_id,
            model_id=model_id,
            prompt_template_version=prompt_template_version,
            classification=classification,
            fragment_count=fragment_count,
            status="PENDING",
            started_at=started_at,
            created_by_id=created_by_id,
            created_at=created_at,
            attempt_count=1,
            candidate_count=0,
            finding_count=0,
        )
        self._session.add(row)
        self._session.flush()
        return self._to_dict(row)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        stmt = select(AIMappingRun).where(AIMappingRun.id == run_id)
        row = self._session.execute(stmt).scalar_one_or_none()
        if row is None:
            return None
        return self._to_dict(row)

    def list_runs_for_intake(self, intake_id: str) -> list[dict[str, Any]]:
        stmt = (
            select(AIMappingRun)
            .where(AIMappingRun.intake_id == intake_id)
            .order_by(AIMappingRun.created_at.desc())
        )
        rows = self._session.execute(stmt).scalars().all()
        return [self._to_dict(row) for row in rows]

    def mark_running(self, run_id: str) -> bool:
        stmt = (
            update(AIMappingRun)
            .where(AIMappingRun.id == run_id, AIMappingRun.status == "PENDING")
            .values(status="RUNNING")
        )
        result = self._session.execute(stmt)
        self._session.flush()
        return (result.rowcount or 0) == 1

    def mark_completed(
        self,
        run_id: str,
        *,
        request_hash: str,
        response_hash: str,
        attempt_count: int,
        candidate_count: int,
        finding_count: int,
        finished_at: datetime,
        metrics_json: dict[str, Any] | None = None,
    ) -> bool:
        stmt = (
            update(AIMappingRun)
            .where(AIMappingRun.id == run_id, AIMappingRun.status == "RUNNING")
            .values(
                status="COMPLETED",
                request_hash=request_hash,
                response_hash=response_hash,
                attempt_count=attempt_count,
                candidate_count=candidate_count,
                finding_count=finding_count,
                finished_at=finished_at,
                metrics_json=metrics_json,
            )
        )
        result = self._session.execute(stmt)
        self._session.flush()
        return (result.rowcount or 0) == 1

    def mark_failed(
        self,
        run_id: str,
        *,
        attempt_count: int,
        failure_category: str,
        failure_detail_redacted: str | None,
        finished_at: datetime,
        metrics_json: dict[str, Any] | None = None,
    ) -> bool:
        stmt = (
            update(AIMappingRun)
            .where(AIMappingRun.id == run_id)
            .where(AIMappingRun.status.in_(("PENDING", "RUNNING")))
            .values(
                status="FAILED",
                attempt_count=attempt_count,
                failure_category=failure_category,
                failure_detail_redacted=failure_detail_redacted,
                finished_at=finished_at,
                metrics_json=metrics_json,
            )
        )
        result = self._session.execute(stmt)
        self._session.flush()
        return (result.rowcount or 0) == 1

    @staticmethod
    def _to_dict(row: AIMappingRun) -> dict[str, Any]:
        return {
            "id": str(row.id),
            "application_id": str(row.application_id),
            "intake_id": str(row.intake_id),
            "evidence_item_id": str(row.evidence_item_id),
            "provider_id": row.provider_id,
            "profile_id": row.profile_id,
            "model_id": row.model_id,
            "prompt_template_version": row.prompt_template_version,
            "classification": row.classification,
            "fragment_count": row.fragment_count,
            "request_hash": row.request_hash,
            "response_hash": row.response_hash,
            "attempt_count": row.attempt_count,
            "status": row.status,
            "failure_category": row.failure_category,
            "failure_detail_redacted": row.failure_detail_redacted,
            "metrics_json": row.metrics_json,
            "candidate_count": row.candidate_count,
            "finding_count": row.finding_count,
            "started_at": row.started_at,
            "finished_at": row.finished_at,
            "created_by_id": str(row.created_by_id),
            "created_at": row.created_at,
        }
