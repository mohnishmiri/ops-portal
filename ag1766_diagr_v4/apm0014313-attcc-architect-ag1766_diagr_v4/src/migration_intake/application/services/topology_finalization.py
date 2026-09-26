"""C7.2 complete artifact bundle storage and T2 finalization."""

from __future__ import annotations

import hashlib
import io
import json
import re
import uuid
from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from migration_intake.persistence.repositories.topology import (
    GenerationConflictError,
    TopologyRepository,
)
from migration_intake.persistence.unit_of_work import uow_context
from migration_intake.topology.contracts import TopologyResultStatus

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

    from migration_intake.storage.port import EvidenceStore


class ArtifactFinalizationError(RuntimeError):
    """Artifact storage or lease-fenced T2 finalization failed."""


_MAX_ARTIFACT_BYTES = 50 * 1024 * 1024
_SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")


def finalize_render_output(
    session_factory: sessionmaker[Any],
    storage: EvidenceStore,
    *,
    run_id: str,
    lease_token: str,
    expected_row_version: int,
    output: Any,
    actor_id: str,
) -> dict[str, Any]:
    """Store, read back, and atomically finalize DIAGRAM/GAP_REPORT/MANIFEST."""
    try:
        with session_factory() as session:
            repository = TopologyRepository(session)
            run = repository.get_generation_run(run_id)
            if run is None or not run.get("input_id"):
                raise ArtifactFinalizationError("Finalization run or input pin is unavailable")
            persisted_input = repository.get_topology_input(str(run["input_id"]))
        if persisted_input is None:
            raise ArtifactFinalizationError("Finalization input is unavailable")
        diagram = _bytes_value(output.diagram_bytes, "diagram")
        report = output.report_html.encode("utf-8")
        manifest_payload = _manifest_bytes(output)
        contents = (
            ("DIAGRAM", diagram, "application/vnd.jgraph.mxfile+xml", "drawio"),
            ("GAP_REPORT", report, "text/html", "html"),
            ("MANIFEST", manifest_payload, "application/json", "json"),
        )
        receipts: list[dict[str, Any]] = []
        for artifact_type, content, mime_type, extension in contents:
            receipt = storage.store(
                io.BytesIO(content), f"{run_id}-{artifact_type.lower()}.{extension}"
            )
            _verify_receipt(storage, receipt.storage_key, content, receipt.sha256_hex)
            receipts.append(
                {
                    "artifact_id": str(uuid.uuid4()),
                    "artifact_type": artifact_type,
                    "filename": _safe_filename(run_id, artifact_type, extension),
                    "mime_type": mime_type,
                    "size_bytes": len(content),
                    "sha256_hex": receipt.sha256_hex,
                    "content_address": receipt.storage_key,
                }
            )
        manifest_hash = next(
            item["sha256_hex"] for item in receipts if item["artifact_type"] == "MANIFEST"
        )
        manifest_status = (
            output.manifest.get("result_status") if isinstance(output.manifest, dict) else None
        )
        output_status = getattr(output, "result_status", None)
        if (
            manifest_status is not None
            and output_status is not None
            and manifest_status != output_status
        ):
            raise ArtifactFinalizationError("Renderer manifest status disagrees with render result")
        result_status = output_status or manifest_status or "READY_FOR_REVIEW"
        allowed_statuses = {status.value for status in TopologyResultStatus}
        if result_status not in allowed_statuses:
            raise ArtifactFinalizationError("Renderer result status is unsupported")
        output_success = bool(getattr(output, "success", True))
        if output_success != (result_status != TopologyResultStatus.FAILED.value):
            raise ArtifactFinalizationError("Renderer success flag disagrees with result status")
        manifest = output.manifest if isinstance(output.manifest, dict) else {}
        for field, expected in (
            ("projection_hash", persisted_input["projection_sha256"]),
            ("base_diagram_hash", persisted_input["base_sha256"]),
            ("profile_hash", persisted_input["profile_hash"]),
        ):
            if field in manifest and manifest[field] != expected:
                raise ArtifactFinalizationError(f"Manifest {field} does not match immutable input")
        readiness = {
            "status": result_status,
            "success": output_success,
            "artifact_types": [item["artifact_type"] for item in receipts],
            "artifact_hashes": {item["artifact_type"]: item["sha256_hex"] for item in receipts},
        }
        with uow_context(session_factory) as uow:
            repository = TopologyRepository(uow._session)
            result = repository.finalize_generation_run(
                run_id=run_id,
                expected_row_version=expected_row_version,
                lease_token=lease_token,
                manifest_hash=manifest_hash,
                readiness_json=readiness,
                artifacts=receipts,
                actor_id=actor_id,
                finalized_at=datetime.now(tz=UTC),
            )
            uow.commit()
        with session_factory() as session:
            result["artifacts"] = TopologyRepository(session).list_artifacts_for_run(run_id)
        return result
    except GenerationConflictError as error:
        raise ArtifactFinalizationError(f"Artifact finalization lease failed: {error}") from error
    except ArtifactFinalizationError:
        raise
    except Exception as error:
        _record_finalization_failure(
            session_factory,
            run_id=run_id,
            expected_row_version=expected_row_version,
            lease_token=lease_token,
            error_message=f"{type(error).__name__}: artifact finalization failed",
        )
        raise ArtifactFinalizationError(
            f"Artifact finalization failed: {type(error).__name__}"
        ) from error


def _record_finalization_failure(
    session_factory: sessionmaker[Any],
    *,
    run_id: str,
    expected_row_version: int,
    lease_token: str,
    error_message: str,
) -> None:
    try:
        with uow_context(session_factory) as uow:
            TopologyRepository(uow._session).fail_storing_generation_run(
                run_id=run_id,
                expected_row_version=expected_row_version,
                lease_token=lease_token,
                error_message=error_message,
            )
            uow.commit()
    except GenerationConflictError:
        return


def _bytes_value(value: Any, subject: str) -> bytes:
    if not isinstance(value, bytes):
        raise ArtifactFinalizationError(f"{subject} output must be bytes")
    if len(value) > _MAX_ARTIFACT_BYTES:
        raise ArtifactFinalizationError(f"{subject} artifact exceeds size limit")
    return value


def _manifest_bytes(output: Any) -> bytes:
    manifest = output.manifest
    if is_dataclass(manifest) and not isinstance(manifest, type):
        manifest = asdict(manifest)
    if isinstance(manifest, Mapping):
        manifest = dict(manifest)
    if not isinstance(manifest, dict):
        raise ArtifactFinalizationError("Renderer manifest must be a mapping")
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )


def _verify_receipt(
    storage: EvidenceStore, storage_key: str, expected: bytes, expected_hash: str
) -> None:
    try:
        with storage.retrieve(storage_key) as stream:
            actual = stream.read(_MAX_ARTIFACT_BYTES + 1)
    except (OSError, ValueError) as error:
        raise ArtifactFinalizationError("Stored artifact cannot be read back") from error
    if len(actual) > _MAX_ARTIFACT_BYTES or actual != expected:
        raise ArtifactFinalizationError("Stored artifact read-back differs from renderer bytes")
    if hashlib.sha256(actual).hexdigest() != expected_hash:
        raise ArtifactFinalizationError("Stored artifact digest differs from receipt")


def _safe_filename(run_id: str, artifact_type: str, extension: str) -> str:
    safe_run = _SAFE_NAME.sub("-", run_id)[:80]
    return f"topology-{safe_run}-{artifact_type.lower()}.{extension}"
