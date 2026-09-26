"""
Canonical command objects for state-changing operations — G1.

Commands contain user intent, target IDs, expected version tokens,
command-specific data, and the actor context. The actor context is
constructed by the web adapter from authenticated/configured sources.

All IDs are string-typed for simpler HTTP serialization. The service layer
resolves and validates UUIDs internally.

Browser forms never submit actor IDs, actor types, roles, or audit fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from migration_intake.application.dto import ActorContext

# ---------------------------------------------------------------------------
# Identifier input for external IDs
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class IdentifierInput:
    """
    A single external identifier supplied by the caller.

    Attributes:
        identifier_type: Type code (e.g., "ITAP", "MOTS", "CORRELATION")
        raw_value: The value as the user typed it; the service derives
                   normalized_value = raw_value.strip().lower()
    """

    identifier_type: str
    raw_value: str


# ---------------------------------------------------------------------------
# Application commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CreateApplicationCommand:
    """
    Command to create a new application with optional identifiers.

    Attributes:
        display_name: Application display name
        identifiers: Tuple of external identifiers (iTAP, MOTS, etc.)
        actor: Actor context for the operation
    """

    display_name: str
    identifiers: tuple[IdentifierInput, ...]
    actor: ActorContext


@dataclass(frozen=True, slots=True)
class UpdateApplicationIdentityCommand:
    """
    Command to update an application's display_name and identifiers.

    Requires expected_version for optimistic concurrency control.

    Attributes:
        application_id: Target application ID (UUID string)
        display_name: New display name
        identifiers: New set of identifiers
        expected_version: Expected row version for concurrency check
        actor: Actor context for the operation
    """

    application_id: str
    display_name: str
    identifiers: tuple[IdentifierInput, ...]
    expected_version: int
    actor: ActorContext


@dataclass(frozen=True, slots=True)
class ArchiveApplicationCommand:
    """
    Command to archive an application.

    Archived applications cannot receive new intakes without restore.

    Attributes:
        application_id: Target application ID (UUID string)
        expected_version: Expected row version for concurrency check
        reason: Optional reason for archiving
    """

    application_id: str
    expected_version: int
    reason: str | None = None


# ---------------------------------------------------------------------------
# Intake commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CreateIntakeCommand:
    """
    Command to create an intake for an existing application.

    Attributes:
        application_id: Target application ID (UUID string)
        catalog_release_id: Published catalog release ID (UUID string)
        actor: Actor context for the operation
    """

    application_id: str
    catalog_release_id: str
    actor: ActorContext


@dataclass(frozen=True, slots=True)
class SubmitIntakeForReviewCommand:
    """
    Command to submit an intake for review.

    Attributes:
        intake_id: Target intake ID (UUID string)
        expected_version: Expected row version for concurrency check
    """

    intake_id: str
    expected_version: int


@dataclass(frozen=True, slots=True)
class FreezeIntakeCommand:
    """
    Command to freeze an intake (create immutable snapshot).

    Attributes:
        intake_id: Target intake ID (UUID string)
        expected_version: Expected row version for concurrency check
    """

    intake_id: str
    expected_version: int


# ---------------------------------------------------------------------------
# Answer commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SaveAnswerCommand:
    """
    Command to save an answer value.

    Attributes:
        intake_id: Target intake ID (UUID string)
        question_code: Control code for the question (e.g., "APP-001")
        value: Answer value (type depends on response type)
        response_schema_version: Version of the response schema
        expected_version: Expected answer row version (None for first save)
    """

    intake_id: str
    question_code: str
    value: Any  # Type varies by response type
    response_schema_version: str
    expected_version: int | None = None


@dataclass(frozen=True, slots=True)
class ClearAnswerCommand:
    """
    Command to clear an answer value.

    Attributes:
        intake_id: Target intake ID (UUID string)
        question_code: Control code for the question
        reason: Reason for clearing the answer
        expected_version: Expected answer row version for concurrency check
    """

    intake_id: str
    question_code: str
    reason: str
    expected_version: int


@dataclass(frozen=True, slots=True)
class ConfirmAnswerCommand:
    """
    Command to confirm an answer (mark as reviewed).

    Attributes:
        intake_id: Target intake ID (UUID string)
        question_code: Control code for the question
        expected_version: Expected answer row version for concurrency check
    """

    intake_id: str
    question_code: str
    expected_version: int


@dataclass(frozen=True, slots=True)
class MarkNotApplicableCommand:
    """
    Command to mark a question as not applicable.

    Attributes:
        intake_id: Target intake ID (UUID string)
        question_code: Control code for the question
        reason: Reason why the question is not applicable
        expected_version: Expected answer row version (None if no prior answer)
    """

    intake_id: str
    question_code: str
    reason: str
    expected_version: int | None = None


# ---------------------------------------------------------------------------
# Evidence commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class UploadEvidenceCommand:
    """
    Command to upload evidence.

    Attributes:
        application_id: Target application ID (UUID string)
        filename: Original filename
        content_type: MIME type
        size_bytes: File size in bytes
        intake_id: Optional target intake ID (UUID string)
    """

    application_id: str
    filename: str
    content_type: str
    size_bytes: int
    intake_id: str | None = None


@dataclass(frozen=True, slots=True)
class ProcessWorkbookCommand:
    """
    Command to process an uploaded workbook.

    Attributes:
        evidence_id: ID of the uploaded workbook evidence (UUID string)
        intake_id: Target intake ID (UUID string)
    """

    evidence_id: str
    intake_id: str


# ---------------------------------------------------------------------------
# Candidate commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AcceptCandidateCommand:
    """
    Command to accept a candidate value.

    Attributes:
        candidate_id: ID of the candidate to accept (UUID string)
        intake_id: Target intake ID (UUID string)
        question_code: Control code for the question
        edited_value: Optional edited value (if accepting with edit)
    """

    candidate_id: str
    intake_id: str
    question_code: str
    edited_value: Any | None = None


@dataclass(frozen=True, slots=True)
class RejectCandidateCommand:
    """
    Command to reject a candidate value.

    Attributes:
        candidate_id: ID of the candidate to reject (UUID string)
        intake_id: Target intake ID (UUID string)
        question_code: Control code for the question
        reason: Optional rejection reason
    """

    candidate_id: str
    intake_id: str
    question_code: str
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class DeferCandidateCommand:
    """
    Command to defer a candidate for later review.

    Attributes:
        candidate_id: ID of the candidate to defer (UUID string)
        intake_id: Target intake ID (UUID string)
        question_code: Control code for the question
        reason: Optional reason for deferral
    """

    candidate_id: str
    intake_id: str
    question_code: str
    reason: str | None = None


# ---------------------------------------------------------------------------
# WaveUtil commands
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class AcceptWaveUtilBatchCommand:
    """
    Command to accept a batch of WaveUtil row revisions.

    Attributes:
        application_id: Target application ID (UUID string)
        row_versions: Mapping of row_id to expected_version
    """

    application_id: str
    row_versions: dict[str, int]


@dataclass(frozen=True, slots=True)
class RetireWaveUtilRowCommand:
    """
    Command to retire a WaveUtil row.

    Attributes:
        application_id: Target application ID (UUID string)
        row_id: ID of the row to retire (UUID string)
        expected_version: Expected row version for concurrency check
        reason: Reason for retirement
    """

    application_id: str
    row_id: str
    expected_version: int
    reason: str
