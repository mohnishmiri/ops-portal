"""C7.3 diagnostic recovery and reconciliation primitives."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

from migration_intake.persistence.repositories.topology import (
    GenerationConflictError,
    TopologyRepository,
)
from migration_intake.persistence.unit_of_work import uow_context

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

    from migration_intake.storage.port import EvidenceStore


class RecoveryConflictError(RuntimeError):
    """Recovery cannot safely claim or reconcile the requested run."""


class RecoveryService:
    """Read-only inventory and lease-fenced recovery; deletion is intentionally absent."""

    MAX_INVENTORY_RUNS = 100
    MAX_ARTIFACT_BYTES = 50 * 1024 * 1024
    MAX_RECOVERY_ATTEMPTS = 3

    def __init__(self, session_factory: sessionmaker[Any], storage: EvidenceStore) -> None:
        self._session_factory = session_factory
        self._storage = storage

    def inventory(self, *, intake_id: str | None = None) -> dict[str, Any]:
        """Inspect durable DB and storage state without changing either."""
        now = datetime.now(tz=UTC)
        with self._session_factory() as session:
            repository = TopologyRepository(session)
            runs = repository.list_runs_with_leases(intake_id)
            run_inventory: list[dict[str, Any]] = []
            for run in runs[: self.MAX_INVENTORY_RUNS]:
                artifacts = repository.list_artifacts_for_run(run["id"])
                artifact_inventory = []
                for artifact in artifacts:
                    available = self._storage.exists(artifact["content_address"])
                    verified = False
                    if available:
                        try:
                            with self._storage.retrieve(artifact["content_address"]) as stream:
                                content = stream.read(self.MAX_ARTIFACT_BYTES + 1)
                            verified = (
                                len(content) == artifact["size_bytes"]
                                and hashlib.sha256(content).hexdigest() == artifact["sha256_hex"]
                            )
                        except (OSError, ValueError):
                            verified = False
                    artifact_inventory.append(
                        {
                            **artifact,
                            "available": available,
                            "verified": verified,
                        }
                    )
                run_inventory.append(
                    {
                        **run,
                        "lease_expired": bool(
                            run["lease_expires_at"] is not None and run["lease_expires_at"] < now
                        ),
                        "artifacts": artifact_inventory,
                    }
                )
            return {
                "generated_at": now,
                "deletion_enabled": False,
                "runs": run_inventory,
                "truncated": len(runs) > self.MAX_INVENTORY_RUNS,
                "run_limit": self.MAX_INVENTORY_RUNS,
            }

    def claim_expired_run(self, *, run_id: str, actor_id: str) -> dict[str, Any]:
        """Claim an expired active run with a new fencing lease."""
        now = datetime.now(tz=UTC)
        token = str(uuid.uuid4())
        with self._session_factory() as session:
            existing = TopologyRepository(session).get_generation_run(run_id)
        if existing is None:
            raise RecoveryConflictError("Run was not found for recovery")
        if int(existing.get("attempt_number") or 0) >= self.MAX_RECOVERY_ATTEMPTS:
            raise RecoveryConflictError("Recovery attempt limit reached")
        with uow_context(self._session_factory) as uow:
            try:
                run = TopologyRepository(uow._session).claim_expired_generation_run(
                    run_id=run_id,
                    actor_id=actor_id,
                    now=now,
                    new_lease_token=token,
                    lease_expires_at=now + timedelta(minutes=5),
                )
            except GenerationConflictError as error:
                raise RecoveryConflictError(str(error)) from error
            uow.commit()
            return run

    def reconcile_run(self, *, run_id: str, actor_id: str) -> dict[str, Any]:
        """Return diagnostic state for a run; never rebuilds from current answers."""
        inventory = self.inventory()
        for run in inventory["runs"]:
            if run["id"] == run_id:
                return {
                    "run_id": run_id,
                    "input_id": run["input_id"],
                    "artifacts": run["artifacts"],
                    "requires_replay_from_input": run["input_id"] is not None,
                    "deletion_enabled": False,
                    "actor_id": actor_id,
                }
        raise RecoveryConflictError("Run was not found for reconciliation")

    def fail_abandoned_run(self, *, run_id: str, actor_id: str) -> dict[str, Any]:
        """Record a bounded recovery failure; storage history is retained."""
        claimed = self.claim_expired_run(run_id=run_id, actor_id=actor_id)
        now = datetime.now(tz=UTC)
        with uow_context(self._session_factory) as uow:
            try:
                result = TopologyRepository(uow._session).mark_recovery_failed(
                    run_id=run_id,
                    expected_row_version=int(claimed["row_version"]),
                    lease_token=str(claimed["lease_token"]),
                    actor_id=actor_id,
                    error_message="Expired worker lease reconciled as failed",
                    reviewed_at=now,
                )
            except GenerationConflictError as error:
                raise RecoveryConflictError(str(error)) from error
            uow.commit()
            return result
