"""Governed base-diagram upload, compatibility, and review commands."""

from __future__ import annotations

import hashlib
import io
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

from migration_intake.persistence.repositories.topology import (
    TopologyRepository,
)
from migration_intake.storage.port import EvidenceStore
from migration_intake.topology.compatibility import CompatibilityResult, inspect_base
from migration_intake.topology.contracts import RenderCapability
from migration_intake.topology.profiles import Profile, load_profile
from migration_intake.topology.renderer import XmlParserLimits, parse_diagram_safely
from migration_intake.topology.scope import ContextKey, ScopeSelection


class BaseDiagramServiceError(RuntimeError):
    """Base error for governed base commands."""


class DiagramValidationError(BaseDiagramServiceError):
    """Stored diagram content is unsafe or does not match its record."""


class IncompatibleDiagramError(BaseDiagramServiceError):
    """A base cannot transition because compatibility is not satisfied."""


class ReviewError(BaseDiagramServiceError):
    """A review transition is not eligible."""


@dataclass(frozen=True)
class UploadResult:
    base_artifact_id: str
    state: str
    sha256_hex: str


@dataclass(frozen=True)
class CompatibilityCheckResult:
    base_artifact_id: str
    compatibility_id: str
    compatibility_key: str
    result_hash: str
    state: str
    row_version: int


@dataclass(frozen=True)
class ReviewResult:
    base_artifact_id: str
    state: str
    row_version: int


class BaseDiagramService:
    """Application boundary for base state transitions over immutable stored bytes."""

    def __init__(
        self,
        repository: TopologyRepository,
        storage: EvidenceStore,
        *,
        xml_limits: XmlParserLimits | None = None,
        profile_loader: Callable[[str], Profile] = load_profile,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._xml_limits = xml_limits or XmlParserLimits()
        self._profile_loader = profile_loader

    def upload_base_diagram(
        self,
        *,
        application_id: str,
        intake_id: str,
        filename: str,
        diagram_bytes: bytes,
        uploaded_by_id: str,
    ) -> UploadResult:
        """Validate and store a draft; upload has no approval effect."""
        self._validate(diagram_bytes)
        receipt = self._storage.store(io.BytesIO(diagram_bytes), filename)
        if receipt.sha256_hex != hashlib.sha256(diagram_bytes).hexdigest():
            raise DiagramValidationError("Storage receipt hash does not match uploaded bytes")
        artifact_id = str(uuid.uuid4())
        now = datetime.now(tz=UTC)
        self._repository.create_base_artifact(
            artifact_id=artifact_id,
            application_id=application_id,
            intake_id=intake_id,
            filename=filename,
            mime_type=receipt.media_type,
            size_bytes=receipt.size_bytes,
            sha256_hex=receipt.sha256_hex,
            content_address=receipt.storage_key,
            uploaded_by_id=uploaded_by_id,
            uploaded_at=now,
            created_at=now,
        )
        return UploadResult(artifact_id, "DRAFT", receipt.sha256_hex)

    def check_compatibility(
        self,
        *,
        base_artifact_id: str,
        profile: Profile,
        selection: ScopeSelection,
        capability: RenderCapability,
        partition_views: dict[ContextKey, str],
        checked_by_id: str,
        expected_row_version: int,
    ) -> CompatibilityCheckResult:
        """Inspect exact stored bytes and atomically pin a compatible draft."""
        base, base_bytes = self._load_verified_base(base_artifact_id)
        self._assert_profile_is_trusted(profile)
        result = inspect_base(
            base_bytes,
            profile,
            selection,
            capability=capability,
            parser_policy=self._xml_limits,
            partition_views=partition_views,
        )
        if not result.is_compatible:
            raise IncompatibleDiagramError(self._issue_message(result))
        if base["application_id"] != selection.application_id or base["intake_id"] != selection.intake_id:
            raise IncompatibleDiagramError("Selection does not belong to the stored base")
        now = datetime.now(tz=UTC)
        compatibility_id = str(uuid.uuid4())
        with self._repository._session.begin_nested():
            self._repository.create_topology_compatibility(
                id=compatibility_id,
                base_artifact_id=base_artifact_id,
                base_sha256=result.base_hash,
                profile_id=profile.profile_id,
                profile_version=profile.version,
                profile_hash=profile.profile_hash,
                selection_json=selection.as_dict(),
                selection_hash=selection.selection_hash,
                capability=capability.value,
                parser_policy_hash=result.parser_policy_hash,
                compatibility_key=result.compatibility_key,
                result_json=self._result_document(result),
                result_hash=result.result_hash,
                checked_by_id=checked_by_id,
                checked_at=now,
            )
            updated = self._repository.mark_base_compatible(
                artifact_id=base_artifact_id,
                compatibility_id=compatibility_id,
                profile_id=profile.profile_id,
                profile_version=profile.version,
                profile_hash=profile.profile_hash,
                capability=capability.value,
                selection_json=selection.as_dict(),
                selection_hash=selection.selection_hash,
                review_id=str(uuid.uuid4()),
                actor_id=checked_by_id,
                reviewed_at=now,
                compatibility_result_hash=result.result_hash,
                expected_row_version=expected_row_version,
            )
        return CompatibilityCheckResult(
            base_artifact_id,
            compatibility_id,
            result.compatibility_key,
            result.result_hash,
            str(updated["review_state"]),
            int(updated["row_version"]),
        )

    def approve_base_diagram(
        self,
        *,
        base_artifact_id: str,
        selection: ScopeSelection,
        capability: RenderCapability,
        partition_views: dict[ContextKey, str],
        approved_by_id: str,
        rationale: str,
        expected_row_version: int,
    ) -> ReviewResult:
        """Recompute all pins from stored bytes before official approval."""
        base, base_bytes = self._load_verified_base(base_artifact_id)
        if base["review_state"] != "COMPATIBLE":
            raise ReviewError("Only a compatible base can be approved")
        profile = self._profile_loader(str(base["profile_id"]))
        self._assert_profile_is_trusted(profile)
        result = inspect_base(
            base_bytes,
            profile,
            selection,
            capability=capability,
            parser_policy=self._xml_limits,
            partition_views=partition_views,
        )
        if not result.is_compatible or not self._pins_match(base, profile, selection, capability, result):
            raise ReviewError("Base compatibility pins are stale or no longer eligible")
        compatibility = self._repository.get_topology_compatibility(str(base["compatibility_id"]))
        if compatibility is None or compatibility["compatibility_key"] != result.compatibility_key or compatibility["result_hash"] != result.result_hash:
            raise ReviewError("Persisted compatibility result no longer matches stored base pins")
        updated = self._repository.review_base_artifact(
            artifact_id=base_artifact_id,
            review_id=str(uuid.uuid4()),
            decision="APPROVE",
            actor_id=approved_by_id,
            reviewed_at=datetime.now(tz=UTC),
            rationale=rationale,
            compatibility_result_hash=result.result_hash,
            expected_row_version=expected_row_version,
        )
        return ReviewResult(base_artifact_id, str(updated["review_state"]), int(updated["row_version"]))

    def reject_base_diagram(
        self,
        *,
        base_artifact_id: str,
        rejected_by_id: str,
        rationale: str,
        expected_row_version: int,
    ) -> ReviewResult:
        """Reject a draft after revalidating its stored bytes."""
        self._load_verified_base(base_artifact_id)
        updated = self._repository.review_base_artifact(
            artifact_id=base_artifact_id,
            review_id=str(uuid.uuid4()),
            decision="REJECT",
            actor_id=rejected_by_id,
            reviewed_at=datetime.now(tz=UTC),
            rationale=rationale,
            compatibility_result_hash=None,
            expected_row_version=expected_row_version,
        )
        return ReviewResult(base_artifact_id, str(updated["review_state"]), int(updated["row_version"]))

    def supersede_base_diagram(
        self,
        *,
        base_artifact_id: str,
        superseded_by_id: str,
        rationale: str,
        expected_row_version: int,
    ) -> ReviewResult:
        """Retire an approved base so it cannot support future official runs."""
        self._load_verified_base(base_artifact_id)
        updated = self._repository.review_base_artifact(
            artifact_id=base_artifact_id,
            review_id=str(uuid.uuid4()),
            decision="SUPERSEDE",
            actor_id=superseded_by_id,
            reviewed_at=datetime.now(tz=UTC),
            rationale=rationale,
            compatibility_result_hash=None,
            expected_row_version=expected_row_version,
        )
        return ReviewResult(base_artifact_id, str(updated["review_state"]), int(updated["row_version"]))

    def eligible_base(
        self,
        base_artifact_id: str,
        *,
        official: bool,
        selection: ScopeSelection | None = None,
        capability: RenderCapability | None = None,
        partition_views: dict[ContextKey, str] | None = None,
    ) -> dict[str, object]:
        """Return the C7-eligible base after optional full compatibility replay."""
        base, base_bytes = self._load_verified_base(base_artifact_id)
        expected_state = "APPROVED" if official else "COMPATIBLE"
        if base["review_state"] != expected_state and not (not official and base["review_state"] == "APPROVED"):
            raise ReviewError(f"Base is {base['review_state']}, not eligible for this mode")
        if not base["compatibility_id"] or not base["profile_hash"] or not base["selection_hash"]:
            raise ReviewError("Base has no governed compatibility pins")
        supplied = (selection, capability, partition_views)
        if any(item is not None for item in supplied):
            if selection is None or capability is None or partition_views is None:
                raise ReviewError("Full selection, capability, and page mapping are required")
            profile = self._profile_loader(str(base["profile_id"]))
            self._assert_profile_is_trusted(profile)
            result = inspect_base(
                base_bytes,
                profile,
                selection,
                capability=capability,
                parser_policy=self._xml_limits,
                partition_views=partition_views,
            )
            compatibility = self._repository.get_topology_compatibility(
                str(base["compatibility_id"])
            )
            if (
                not result.is_compatible
                or not self._pins_match(base, profile, selection, capability, result)
                or compatibility is None
                or compatibility["compatibility_key"] != result.compatibility_key
                or compatibility["result_hash"] != result.result_hash
            ):
                raise ReviewError("Base compatibility replay does not match approved pins")
        return base

    def _load_verified_base(self, base_artifact_id: str) -> tuple[dict[str, object], bytes]:
        base = self._repository.get_base_artifact(base_artifact_id)
        if base is None:
            raise ReviewError("Base artifact was not found")
        try:
            with self._storage.retrieve(str(base["content_address"])) as stream:
                content = stream.read()
        except (OSError, ValueError) as error:
            raise DiagramValidationError("Stored base bytes are unavailable") from error
        if hashlib.sha256(content).hexdigest() != base["sha256_hex"]:
            raise DiagramValidationError("Stored base bytes do not match their recorded hash")
        self._validate(content)
        return base, content

    def _validate(self, content: bytes) -> None:
        try:
            parse_diagram_safely(content, self._xml_limits)
        except Exception as error:
            raise DiagramValidationError(f"Diagram XML validation failed: {error}") from error

    def _assert_profile_is_trusted(self, profile: Profile) -> None:
        loaded = self._profile_loader(profile.profile_id)
        if loaded.profile_hash != profile.profile_hash or loaded.version != profile.version:
            raise ReviewError("Profile does not match the trusted packaged release")

    @staticmethod
    def _pins_match(
        base: dict[str, object],
        profile: Profile,
        selection: ScopeSelection,
        capability: RenderCapability,
        result: CompatibilityResult,
    ) -> bool:
        return all((
            base["sha256_hex"] == result.base_hash,
            base["profile_id"] == profile.profile_id,
            base["profile_version"] == profile.version,
            base["profile_hash"] == profile.profile_hash,
            base["capability"] == capability.value,
            base["selection_hash"] == selection.selection_hash,
            base["compatibility_id"] is not None,
        ))

    @staticmethod
    def _result_document(result: CompatibilityResult) -> dict[str, object]:
        return {
            "inventory_hash": result.inventory.inventory_hash,
            "slot_matches": [asdict(match) for match in result.slot_matches],
            "issues": [asdict(issue) for issue in result.issues],
            "warnings": [asdict(issue) for issue in result.warnings],
        }

    @staticmethod
    def _issue_message(result: CompatibilityResult) -> str:
        return "; ".join(issue.message for issue in result.blocking_issues)
