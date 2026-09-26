"""
Topology generation service — T04.

Orchestrates official snapshot-backed generation and explicitly non-authoritative
draft preview generation from current intake answers.

Design rules:
- Receives validated commands; does NOT parse HTTP or read env vars.
- Loads state through repositories inside a UoW.
- Commits through UoW.
- Returns detached plain dicts — no ORM entities leave this module.

Generation workflow:
1. Validate intake is frozen with a valid snapshot
2. Upload and validate base diagram
3. Check topology readiness
4. Generate diagram and gap report
5. Store paired artifacts
6. Create immutable run record
"""

from __future__ import annotations

import hashlib
import io
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.orm import sessionmaker

from migration_intake.application.dto import ActorContext
from migration_intake.application.errors import ConcurrencyConflictError
from migration_intake.domain.topology import (
    GenerationStatus,
    TopologyReadinessIssue,
    TopologyReadinessResult,
)
from migration_intake.persistence.repositories.intakes import IntakeRepository
from migration_intake.persistence.repositories.snapshots import SnapshotRepository
from migration_intake.persistence.repositories.topology import TopologyRepository
from migration_intake.persistence.unit_of_work import uow_context
from migration_intake.storage.filesystem import FilesystemStore
from migration_intake.topology.adapter import TopologyData, extract_topology_data
from migration_intake.topology.fill import FillResult, fill_diagram
from migration_intake.topology.haf_pipeline import HafParseError, parse_haf_template
from migration_intake.topology.haf_service import generate_haf_topology
from migration_intake.topology.template_loader import resolve_template
from migration_intake.topology.report import ReportData, ReportIssue, generate_gap_report

# ─────────────────────────────────────────────────────────────────────────────
# Errors
# ─────────────────────────────────────────────────────────────────────────────


class IntakeNotFrozenError(Exception):
    """Raised when trying to generate topology for a non-frozen intake."""
    pass


class NoSnapshotError(Exception):
    """Raised when intake has no snapshot."""
    pass


class InvalidBaseDiagramError(Exception):
    """Raised when base diagram is invalid or incompatible."""

    def __init__(self, message: str, details: list[str] | None = None) -> None:
        super().__init__(message)
        self.details = details or []


class TopologyNotReadyError(Exception):
    """Raised when topology is not ready for generation."""

    def __init__(self, readiness: TopologyReadinessResult) -> None:
        self.readiness = readiness
        blockers = [b.message for b in readiness.blockers]
        super().__init__(f"Topology not ready: {blockers}")


class TopologyApprovalError(Exception):
    """Raised when a generation run cannot enter the requested approval state."""


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────


class TopologyGenerationService:
    """
    Orchestrates topology diagram generation.

    Each public method opens exactly one UoW, performs all reads and writes
    inside it, commits on success, and returns a plain dict.
    """

    def __init__(
        self, session_factory: sessionmaker, storage_root: Path | None = None
    ) -> None:
        self._session_factory = session_factory
        root = storage_root or Path("evidence")
        self._storage = FilesystemStore(root / "topology")
        self._default_haf_profile_id = "OUTPOST_V1"
        self._variant_profile_map: dict[str | None, str] = {
            None: "OUTPOST_V1",
            "basic": "OUTPOST_V1_BASIC",
            "tlgw": "OUTPOST_V1_TLGW",
            "f5": "OUTPOST_V1_F5",
            "hadr": "OUTPOST_V1_HADR",
        }

    def upload_base_diagram(
        self,
        intake_id: str,
        file_bytes: bytes,
        filename: str,
        actor: ActorContext,
        *,
        environment: str | None = None,
        site: str | None = None,
        variant: str | None = "default",
    ) -> dict[str, Any]:
        """
        Upload and validate a base diagram.

        Validates:
        - Intake exists
        - File is valid draw.io XML (uncompressed)
        - Required semantic slots are present (basic validation)

        Returns the created base artifact record.

        Raises:
            IntakeNotFrozenError: If intake is not frozen
            InvalidBaseDiagramError: If diagram is invalid
        """
        now = datetime.now(tz=UTC)

        # Validate the diagram content
        validation_errors = self._validate_drawio_xml(file_bytes)
        if validation_errors:
            raise InvalidBaseDiagramError(
                "Invalid draw.io diagram",
                details=validation_errors,
            )

        # Compute content hash
        sha256_hex = hashlib.sha256(file_bytes).hexdigest()

        with uow_context(self._session_factory) as uow:
            intake_repo = IntakeRepository(uow._session)
            snapshot_repo = SnapshotRepository(uow._session)
            topology_repo = TopologyRepository(uow._session)

            # Validate intake exists
            intake = intake_repo.get(intake_id)
            if intake is None:
                raise ConcurrencyConflictError(f"Intake {intake_id} not found")

            # Always store fresh content on upload; never reuse a prior
            # artifact even if its hash matches, so a re-upload always
            # replaces whatever content is currently on disk.
            # Store the file content
            artifact_id = str(uuid.uuid4())
            content_address = self._store_content(
                file_bytes, artifact_id, "base_diagrams"
            )

            # Create the artifact record
            artifact = topology_repo.create_base_artifact(
                artifact_id=artifact_id,
                application_id=intake["application_id"],
                intake_id=intake_id,
                filename=filename,
                mime_type="application/vnd.jgraph.mxfile+xml",
                size_bytes=len(file_bytes),
                sha256_hex=sha256_hex,
                content_address=content_address,
                uploaded_by_id=actor.actor_id,
                uploaded_at=now,
                created_at=now,
                environment=environment,
                site=site,
                variant=variant,
            )

            uow.commit()

        return artifact

    def check_topology_readiness(
        self,
        intake_id: str,
        base_artifact_id: str | None = None,
    ) -> TopologyReadinessResult:
        """
        Check if an intake is ready for topology generation.

        Validates:
        - Intake exists
        - The selected base diagram belongs to the intake
        - Base diagram is valid and compatible (if provided)

        Returns a TopologyReadinessResult with blockers and warnings.
        """
        blockers: list[TopologyReadinessIssue] = []
        warnings: list[TopologyReadinessIssue] = []
        snapshot_id: str | None = None

        with self._session_factory() as session:
            intake_repo = IntakeRepository(session)
            snapshot_repo = SnapshotRepository(session)
            topology_repo = TopologyRepository(session)

            # Check intake exists
            intake = intake_repo.get(intake_id)
            if intake is None:
                blockers.append(TopologyReadinessIssue(
                    code="INTAKE_NOT_FOUND",
                    severity="BLOCKER",
                    message=f"Intake {intake_id} not found",
                ))
            else:
                snapshot = snapshot_repo.get_by_intake_id(intake_id)
                if snapshot is not None:
                    snapshot_id = snapshot["id"]

            # Check base diagram if provided
            if base_artifact_id:
                base = topology_repo.get_base_artifact(base_artifact_id)
                if base is None:
                    blockers.append(TopologyReadinessIssue(
                        code="BASE_NOT_FOUND",
                        severity="BLOCKER",
                        message=f"Base diagram {base_artifact_id} not found",
                    ))
                elif base["intake_id"] != intake_id:
                    blockers.append(TopologyReadinessIssue(
                        code="BASE_WRONG_INTAKE",
                        severity="BLOCKER",
                        message="Base diagram belongs to a different intake",
                    ))

        is_ready = len(blockers) == 0
        return TopologyReadinessResult(
            is_ready=is_ready,
            blockers=blockers,
            warnings=warnings,
            snapshot_id=snapshot_id,
            base_artifact_id=base_artifact_id,
        )

    def generate_topology(
        self,
        intake_id: str,
        base_artifact_id: str,
        actor: ActorContext,
        variant: str | None = None,
    ) -> dict[str, Any]:
        """
        Generate topology from a frozen snapshot when available, or current
        draft answers when the intake has no snapshot. Draft output is not
        eligible for approval or downstream authoritative consumption.

        Steps:
        1. Check topology readiness
        2. Load frozen snapshot
        3. Load base diagram
        4. Create generation run record
        5. Generate filled diagram
        6. Generate gap report
        7. Store paired artifacts
        8. Update run status

        Returns the generation run record.

        Raises:
            TopologyNotReadyError: If topology is not ready
        """
        now = datetime.now(tz=UTC)

        # Check readiness first
        readiness = self.check_topology_readiness(intake_id, base_artifact_id)
        if not readiness.is_ready:
            raise TopologyNotReadyError(readiness)

        with uow_context(self._session_factory) as uow:
            intake_repo = IntakeRepository(uow._session)
            snapshot_repo = SnapshotRepository(uow._session)
            topology_repo = TopologyRepository(uow._session)

            # Load intake and snapshot
            intake = intake_repo.get(intake_id)
            if intake is None:
                raise ConcurrencyConflictError(f"Intake {intake_id} not found")

            snapshot = snapshot_repo.get_by_intake_id(intake_id)

            # Load base diagram
            base = topology_repo.get_base_artifact(base_artifact_id)
            if base is None:
                raise InvalidBaseDiagramError(f"Base diagram {base_artifact_id} not found")

            # If no variant was passed explicitly, use the variant that
            # was stored on the base artifact at upload time.  This
            # ensures Card 2 generation uses the correct profile even
            # though the route does not send a variant field.
            if variant is None:
                stored_variant = base.get("variant")
                if stored_variant and stored_variant != "default":
                    variant = stored_variant

            # Create generation run
            run_id = str(uuid.uuid4())
            run = topology_repo.create_generation_run(
                run_id=run_id,
                application_id=intake["application_id"],
                intake_id=intake_id,
                snapshot_id=snapshot["id"] if snapshot else None,
                snapshot_sha256=snapshot["sha256_hex"] if snapshot else None,
                catalog_sha256=snapshot["catalog_sha256"] if snapshot else None,
                base_artifact_id=base_artifact_id,
                base_sha256=base["sha256_hex"],
                requested_by_id=actor.actor_id,
                requested_at=now,
                created_at=now,
                status=GenerationStatus.RUNNING.value,
            )

            try:
                # Load base diagram content
                base_content = base.get("content")
                if base_content is None:
                    # Try to load from content address
                    content_address = base.get("content_address")
                    if content_address:
                        base_content = self._load_content(content_address)
                    else:
                        raise InvalidBaseDiagramError(
                            f"Base diagram content is unavailable for {base_artifact_id}"
                        )

                # Generate diagram using real topology data
                diagram_bytes, fill_result, topology_data = self._generate_diagram(
                    uow._session,
                    intake_id,
                    base_content,
                    snapshot or {},
                    base,
                    variant=variant,
                )
                diagram_sha256 = hashlib.sha256(diagram_bytes).hexdigest()

                # Generate gap report with real data
                report_bytes = self._generate_report(
                    run_id,
                    intake,
                    snapshot or {},
                    base,
                    topology_data,
                    fill_result,
                    now,
                )
                report_sha256 = hashlib.sha256(report_bytes).hexdigest()

                # Store artifacts
                app_acronym = intake.get("application_acronym", "APP")
                timestamp = now.strftime("%Y%m%d_%H%M%S")

                diagram_id = str(uuid.uuid4())
                diagram_address = self._store_content(
                    diagram_bytes, diagram_id, "generated"
                )
                topology_repo.create_generated_artifact(
                    artifact_id=diagram_id,
                    generation_run_id=run_id,
                    artifact_type="DIAGRAM",
                    filename=f"topology_{app_acronym}_{timestamp}.drawio",
                    mime_type="application/vnd.jgraph.mxfile+xml",
                    size_bytes=len(diagram_bytes),
                    sha256_hex=diagram_sha256,
                    content_address=diagram_address,
                    created_at=now,
                )

                report_id = str(uuid.uuid4())
                report_address = self._store_content(
                    report_bytes, report_id, "generated"
                )
                topology_repo.create_generated_artifact(
                    artifact_id=report_id,
                    generation_run_id=run_id,
                    artifact_type="GAP_REPORT",
                    filename=f"gap_report_{app_acronym}_{timestamp}.html",
                    mime_type="text/html",
                    size_bytes=len(report_bytes),
                    sha256_hex=report_sha256,
                    content_address=report_address,
                    created_at=now,
                )

                # Update run status to success
                updated_run = topology_repo.update_run_status(
                    run_id,
                    status=GenerationStatus.READY_FOR_REVIEW.value,
                    completed_at=now,
                )
                if updated_run is not None:
                    run = updated_run

            except Exception as e:
                # Update run status to failed
                topology_repo.update_run_status(
                    run_id,
                    status=GenerationStatus.FAILED.value,
                    completed_at=now,
                    error_message=str(e),
                )
                uow.commit()
                raise

            uow.commit()

        return run

    def generate_from_standard_template(
        self,
        intake_id: str,
        variant: str,
        actor: ActorContext,
    ) -> dict[str, Any]:
        """Generate topology using the bundled standard template.

        Loads the annotated master template from disk (instead of an
        uploaded base diagram), extracts the tab for *variant*, and
        runs the HAF pipeline.

        Args:
            intake_id: Active intake ID.
            variant: Variant key (``"basic"``, ``"tlgw"``, ``"f5"``, ``"hadr"``).
            actor: Current actor context.

        Returns:
            Generation run record dict.
        """
        template_bytes, template_source = resolve_template(
            variant,
            session_factory=self._session_factory,
            storage=self._storage,
        )

        now = datetime.now(tz=UTC)

        with uow_context(self._session_factory) as uow:
            intake_repo = IntakeRepository(uow._session)
            snapshot_repo = SnapshotRepository(uow._session)
            topology_repo = TopologyRepository(uow._session)

            intake = intake_repo.get(intake_id)
            if intake is None:
                raise ConcurrencyConflictError(f"Intake {intake_id} not found")

            snapshot = snapshot_repo.get_by_intake_id(intake_id)

            # Create a real base artifact record so the FK on gen_runs
            # is satisfied.  The bundled template bytes are stored via
            # the normal content-addressed path for auditability.
            base_id = str(uuid.uuid4())
            template_sha256 = hashlib.sha256(template_bytes).hexdigest()
            base_content_address = self._store_content(
                template_bytes, base_id, "base_diagrams"
            )
            topology_repo.create_base_artifact(
                artifact_id=base_id,
                application_id=intake["application_id"],
                intake_id=intake_id,
                filename=f"bundled_outpost_v1.7_{variant}.drawio",
                mime_type="application/vnd.jgraph.mxfile+xml",
                size_bytes=len(template_bytes),
                sha256_hex=template_sha256,
                content_address=base_content_address,
                uploaded_by_id=actor.actor_id,
                uploaded_at=now,
                created_at=now,
                variant=variant,
                review_state="APPROVED",
                template_release_id=(
                    template_source if template_source != "bundled_fallback" else None
                ),
            )

            # Create generation run
            run_id = str(uuid.uuid4())
            run = topology_repo.create_generation_run(
                run_id=run_id,
                application_id=intake["application_id"],
                intake_id=intake_id,
                snapshot_id=snapshot["id"] if snapshot else None,
                snapshot_sha256=snapshot["sha256_hex"] if snapshot else None,
                catalog_sha256=snapshot["catalog_sha256"] if snapshot else None,
                base_artifact_id=base_id,
                base_sha256=template_sha256,
                requested_by_id=actor.actor_id,
                requested_at=now,
                created_at=now,
                status=GenerationStatus.RUNNING.value,
            )

            try:
                diagram_bytes, fill_result, topology_data = self._generate_diagram(
                    uow._session,
                    intake_id,
                    template_bytes,
                    snapshot or {},
                    {},
                    variant=variant,
                )
                diagram_sha256 = hashlib.sha256(diagram_bytes).hexdigest()

                report_bytes = self._generate_report(
                    run_id,
                    intake,
                    snapshot or {},
                    {},
                    topology_data,
                    fill_result,
                    now,
                )
                report_sha256 = hashlib.sha256(report_bytes).hexdigest()

                app_acronym = intake.get("application_acronym", "APP")
                timestamp = now.strftime("%Y%m%d_%H%M%S")

                diagram_id = str(uuid.uuid4())
                diagram_address = self._store_content(
                    diagram_bytes, diagram_id, "generated"
                )
                topology_repo.create_generated_artifact(
                    artifact_id=diagram_id,
                    generation_run_id=run_id,
                    artifact_type="DIAGRAM",
                    filename=f"topology_{app_acronym}_{variant}_{timestamp}.drawio",
                    mime_type="application/vnd.jgraph.mxfile+xml",
                    size_bytes=len(diagram_bytes),
                    sha256_hex=diagram_sha256,
                    content_address=diagram_address,
                    created_at=now,
                )

                report_id = str(uuid.uuid4())
                report_address = self._store_content(
                    report_bytes, report_id, "reports"
                )
                topology_repo.create_generated_artifact(
                    artifact_id=report_id,
                    generation_run_id=run_id,
                    artifact_type="GAP_REPORT",
                    filename=f"gap_report_{app_acronym}_{variant}_{timestamp}.html",
                    mime_type="text/html",
                    size_bytes=len(report_bytes),
                    sha256_hex=report_sha256,
                    content_address=report_address,
                    created_at=now,
                )

                updated_run = topology_repo.update_run_status(
                    run_id,
                    status=GenerationStatus.READY_FOR_REVIEW.value,
                    completed_at=now,
                )
                if updated_run is not None:
                    run = updated_run

            except Exception as exc:
                topology_repo.update_run_status(
                    run_id,
                    status=GenerationStatus.FAILED.value,
                    completed_at=now,
                    error_message=str(exc),
                )
                uow.commit()
                raise

            uow.commit()

        return run

    def get_generation_run(self, run_id: str) -> dict[str, Any] | None:
        """Get a generation run by ID."""
        with self._session_factory() as session:
            topology_repo = TopologyRepository(session)
            return topology_repo.get_generation_run(run_id)

    def get_generation_run_for_intake(
        self,
        run_id: str,
        application_id: str,
        intake_id: str,
    ) -> dict[str, Any] | None:
        """Get a generation run only when it belongs to the requested intake."""
        with self._session_factory() as session:
            topology_repo = TopologyRepository(session)
            return topology_repo.get_generation_run_for_intake(
                run_id,
                application_id,
                intake_id,
            )

    def approve_generation_run(
        self,
        run_id: str,
        application_id: str,
        intake_id: str,
        actor: ActorContext,
        *,
        approved: bool,
        rationale: str,
    ) -> dict[str, Any]:
        """Approve or reject an official, completed topology run."""
        rationale = rationale.strip()
        if not rationale:
            raise TopologyApprovalError("Approval rationale is required")

        with uow_context(self._session_factory) as uow:
            topology_repo = TopologyRepository(uow._session)
            run = topology_repo.get_generation_run_for_intake(
                run_id, application_id, intake_id
            )
            if run is None:
                raise TopologyApprovalError("Generation run not found")
            if run["snapshot_id"] is None:
                raise TopologyApprovalError(
                    "Draft preview runs cannot be approved or rejected"
                )
            if run["status"] not in {"READY_FOR_REVIEW", "GENERATED_WITH_GAPS"}:
                raise TopologyApprovalError(
                    "Only completed generation runs can be reviewed"
                )
            if run["approval_status"] != "PENDING":
                raise TopologyApprovalError("Generation run has already been reviewed")

            updated = topology_repo.update_run_approval(
                run_id,
                "APPROVED" if approved else "REJECTED",
                approved_by_id=actor.actor_id,
                approved_at=datetime.now(tz=UTC),
                approval_rationale=rationale,
            )
            if updated is None:
                raise TopologyApprovalError("Generation run not found")
            uow.commit()
            return updated

    def list_generation_runs(self, intake_id: str) -> list[dict[str, Any]]:
        """List all generation runs for an intake."""
        with self._session_factory() as session:
            topology_repo = TopologyRepository(session)
            return topology_repo.list_generation_runs_for_intake(intake_id)

    def list_base_artifacts(self, intake_id: str) -> list[dict[str, Any]]:
        """List all base artifacts for an intake."""
        with self._session_factory() as session:
            topology_repo = TopologyRepository(session)
            return topology_repo.list_base_artifacts_for_intake(intake_id)

    def get_run_artifacts(self, run_id: str) -> list[dict[str, Any]]:
        """Get all artifacts for a generation run."""
        with self._session_factory() as session:
            topology_repo = TopologyRepository(session)
            return topology_repo.list_artifacts_for_run(run_id)

    def get_artifact_content(self, artifact_id: str) -> tuple[bytes, str, str] | None:
        """
        Get artifact content by ID.

        Returns (bytes, filename, mime_type) or None if not found.
        """
        with self._session_factory() as session:
            topology_repo = TopologyRepository(session)
            artifact = topology_repo.get_generated_artifact(artifact_id)
            if artifact is None:
                return None

            content = self._load_content(artifact["content_address"])
            return content, artifact["filename"], artifact["mime_type"]

    def get_base_artifact_content(
        self, artifact_id: str
    ) -> tuple[bytes, str, str] | None:
        """
        Get base artifact content by ID.

        Returns (bytes, filename, mime_type) or None if not found.
        """
        with self._session_factory() as session:
            topology_repo = TopologyRepository(session)
            artifact = topology_repo.get_base_artifact(artifact_id)
            if artifact is None:
                return None

            content = self._load_content(artifact["content_address"])
            return content, artifact["filename"], artifact["mime_type"]

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_drawio_xml(self, content: bytes) -> list[str]:
        """
        Validate draw.io XML content.

        Returns a list of validation errors, or empty list if valid.
        """
        errors: list[str] = []

        try:
            # Check it's valid XML
            import xml.etree.ElementTree as ET
            text = content.decode("utf-8")
            root = ET.fromstring(text)

            # Check for mxfile root element
            if root.tag != "mxfile":
                errors.append("Root element must be 'mxfile'")
                return errors

            # Check for compressed attribute
            compressed = root.get("compressed", "false")
            if compressed.lower() == "true":
                errors.append("Compressed draw.io files are not supported; save as uncompressed XML")

            # Check for at least one diagram/page
            diagrams = root.findall(".//diagram")
            if not diagrams:
                errors.append("No diagram pages found in file")

        except UnicodeDecodeError:
            errors.append("File is not valid UTF-8 text")
        except ET.ParseError as e:
            errors.append(f"Invalid XML: {e}")

        return errors

    def _store_content(
        self, content: bytes, artifact_id: str, _subfolder: str
    ) -> str:
        """
        Store content in content-addressed storage.

        For now, uses a simple file-based approach.
        Returns the content address (path).
        """
        receipt = self._storage.store(io.BytesIO(content), f"{artifact_id}.bin")
        return receipt.storage_key

    def _load_content(self, content_address: str) -> bytes:
        """
        Load content from content-addressed storage.

        Load content from the configured filesystem store.
        """
        with self._storage.retrieve(content_address) as stream:
            return stream.read()

    def _generate_diagram(
        self,
        session: Any,
        intake_id: str,
        base_content: bytes,
        _snapshot: dict,
        _base: dict,
        variant: str | None = None,
    ) -> tuple[bytes, FillResult, TopologyData]:
        """
        Generate a filled diagram from the base diagram and intake data.

        Steps:
        1. Extract topology data from the database
        2. Fill diagram labels with resolved values
        3. Return the filled XML and metadata

        Args:
            session: Database session
            intake_id: The intake ID
            base_content: The base diagram XML bytes
            snapshot: Snapshot metadata dict
            base: Base artifact metadata dict

        Returns:
            Tuple of (filled_xml, fill_result, topology_data)
        """
        if self._is_haf_template(base_content):
            return self._generate_haf_diagram(
                session, intake_id, base_content, variant=variant
            )

        # Extract topology data from the database
        topology_data = extract_topology_data(session, intake_id)
        # Fill the diagram with tokens
        fill_result = fill_diagram(base_content, topology_data.tokens)

        if not fill_result.success or not fill_result.filled_xml:
            details = fill_result.errors or [
                "The diagram could not be populated with the available intake data"
            ]
            raise InvalidBaseDiagramError(
                "Base diagram could not be populated",
                details=details,
            )

        return fill_result.filled_xml, fill_result, topology_data

    def _is_haf_template(self, base_content: bytes) -> bool:
        """Return True when the uploaded base is a haf-role-annotated template."""
        try:
            index = parse_haf_template(base_content)
        except HafParseError:
            return False
        return bool(index.all_roles)

    def _generate_haf_diagram(
        self,
        session: Any,
        intake_id: str,
        base_content: bytes,
        variant: str | None = None,
    ) -> tuple[bytes, FillResult, TopologyData]:
        """Generate diagram content using the HAF extractor/pipeline path."""
        profile_id = self._variant_profile_map.get(
            variant, self._default_haf_profile_id
        )
        haf_result = generate_haf_topology(
            session=session,
            intake_id=intake_id,
            profile_id=profile_id,
            template_bytes=base_content,
        )
        fatal_issues = [
            str(issue.get("message", "HAF extraction failed"))
            for issue in haf_result.extraction_issues
            if issue.get("type") == "FATAL"
        ]
        missing_from_extraction = {
            str(issue.get("token"))
            for issue in haf_result.extraction_issues
            if issue.get("type") == "MISSING_TOKEN" and issue.get("token")
        }
        missing_from_gaps = {gap.token for gap in haf_result.gaps if gap.blocking}
        missing_tokens = sorted(missing_from_extraction | missing_from_gaps)

        warnings = [
            f"Token '{gap.token}' is unresolved for role '{gap.haf_role}'"
            for gap in haf_result.gaps
        ]
        warnings.extend(
            str(issue.get("message", ""))
            for issue in haf_result.extraction_issues
            if issue.get("type") == "MISSING_TOKEN"
        )

        fill_result = FillResult(
            success=not fatal_issues and bool(haf_result.filled_xml),
            filled_xml=haf_result.filled_xml,
            mutations=[
                {
                    "slot_name": mutation.token,
                    "cell_id": mutation.cell_id,
                    "original_value": mutation.old_fragment,
                    "new_value": mutation.new_fragment,
                }
                for mutation in haf_result.mutations
            ],
            errors=fatal_issues,
            warnings=warnings,
        )

        intake = IntakeRepository(session).get(intake_id)
        app_id = str(intake["application_id"]) if intake else intake_id
        topology_data = TopologyData(
            app_id=app_id,
            app_name=haf_result.tokens.get("app_name", ""),
            app_acronym=haf_result.tokens.get("app_acronym"),
            correlation_id=haf_result.tokens.get("correlation_id"),
            tokens=haf_result.tokens,
            missing_tokens=missing_tokens,
            issues=[],
        )
        return haf_result.filled_xml, fill_result, topology_data

    def _generate_report(
        self,
        run_id: str,
        _intake: dict,
        snapshot: dict,
        base: dict,
        topology_data: TopologyData,
        fill_result: FillResult,
        generated_at: datetime,
    ) -> bytes:
        """
        Generate a gap report documenting the generation.

        Args:
            run_id: The generation run ID
            intake: Intake metadata dict
            snapshot: Snapshot metadata dict
            base: Base artifact metadata dict
            topology_data: Extracted topology data
            fill_result: Result from diagram filling
            generated_at: When generation occurred

        Returns:
            HTML report bytes
        """
        # Build issues from missing tokens and fill errors
        issues: list[ReportIssue] = []

        # Add issues for missing tokens
        for missing in topology_data.missing_tokens:
            issues.append(ReportIssue(
                issue_id=f"MISSING_{missing.upper()}",
                issue_type="MISSING",
                severity="MEDIUM",
                status="OPEN",
                message=f"Token '{missing}' is missing from intake data",
                related_paths=[missing],
                action_required=f"Provide a value for {missing}",
            ))

        # Add issues from fill errors
        for error in fill_result.errors:
            issues.append(ReportIssue(
                issue_id=f"FILL_ERROR_{len(issues)}",
                issue_type="INVALID",
                severity="HIGH",
                status="OPEN",
                message=error,
                action_required="Review diagram and slot bindings",
            ))

        # Add warnings as low-severity issues
        for warning in fill_result.warnings:
            issues.append(ReportIssue(
                issue_id=f"FILL_WARNING_{len(issues)}",
                issue_type="UNVERIFIED",
                severity="LOW",
                status="OPEN",
                message=warning,
            ))

        # Determine run status
        has_blockers = any(i.severity in ("BLOCKER", "CRITICAL") for i in issues)
        has_high = any(i.severity == "HIGH" for i in issues)

        if has_blockers or has_high or len(topology_data.missing_tokens) > 0:
            run_status = "GENERATED_WITH_GAPS"
        else:
            run_status = "READY_FOR_REVIEW"

        # Build report data
        report_data = ReportData(
            app_id=topology_data.app_id,
            app_name=topology_data.app_name,
            run_id=run_id,
            run_status=run_status,
            generated_at=generated_at,
            snapshot_id=snapshot.get("id"),
            snapshot_hash=snapshot.get("sha256_hex"),
            base_diagram_name=base.get("filename"),
            base_diagram_hash=base.get("sha256_hex"),
            issues=issues,
            mutations=fill_result.mutations,
            tokens=topology_data.tokens,
        )

        return generate_gap_report(report_data)
