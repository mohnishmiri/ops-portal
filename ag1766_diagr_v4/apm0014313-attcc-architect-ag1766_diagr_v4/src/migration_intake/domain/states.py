"""
State enumerations and transition policies.

Each state enum defines allowed transitions through the can_transition_to method.
Terminal states return False for all transitions.
"""

from __future__ import annotations

from enum import Enum


class ApplicationState(Enum):
    """
    Application lifecycle states.

    Transitions:
    - ACTIVE -> ON_HOLD -> ACTIVE (bidirectional)
    - ACTIVE|ON_HOLD -> ARCHIVED (terminal)
    """

    ACTIVE = "ACTIVE"
    ON_HOLD = "ON_HOLD"
    ARCHIVED = "ARCHIVED"

    def can_transition_to(self, target: ApplicationState) -> bool:
        """Check if transition to target state is allowed."""
        allowed: dict[ApplicationState, set[ApplicationState]] = {
            ApplicationState.ACTIVE: {
                ApplicationState.ON_HOLD,
                ApplicationState.ARCHIVED,
            },
            ApplicationState.ON_HOLD: {
                ApplicationState.ACTIVE,
                ApplicationState.ARCHIVED,
            },
            ApplicationState.ARCHIVED: set(),  # Terminal
        }
        return target in allowed.get(self, set())


class IntakeState(Enum):
    """
    Intake workflow states.

    Transitions follow the workflow:
    DRAFT -> COLLECTING -> IN_REVIEW -> READY_TO_FREEZE -> FROZEN
    With CHANGES_REQUESTED as a return path from IN_REVIEW.
    CANCELLED and SUPERSEDED are terminal states.
    """

    DRAFT = "DRAFT"
    COLLECTING = "COLLECTING"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    READY_TO_FREEZE = "READY_TO_FREEZE"
    FROZEN = "FROZEN"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"

    def can_transition_to(self, target: IntakeState) -> bool:
        """Check if transition to target state is allowed."""
        allowed: dict[IntakeState, set[IntakeState]] = {
            IntakeState.DRAFT: {
                IntakeState.COLLECTING,
                IntakeState.CANCELLED,
            },
            IntakeState.COLLECTING: {
                IntakeState.IN_REVIEW,
                IntakeState.CANCELLED,
            },
            IntakeState.IN_REVIEW: {
                IntakeState.CHANGES_REQUESTED,
                IntakeState.READY_TO_FREEZE,
                IntakeState.CANCELLED,
            },
            IntakeState.CHANGES_REQUESTED: {
                IntakeState.COLLECTING,
                IntakeState.IN_REVIEW,
                IntakeState.CANCELLED,
            },
            IntakeState.READY_TO_FREEZE: {
                IntakeState.FROZEN,
                IntakeState.CHANGES_REQUESTED,
                IntakeState.CANCELLED,
            },
            IntakeState.FROZEN: {
                IntakeState.SUPERSEDED,
            },
            IntakeState.SUPERSEDED: set(),  # Terminal
            IntakeState.CANCELLED: set(),  # Terminal
        }
        return target in allowed.get(self, set())

    @property
    def is_terminal(self) -> bool:
        """Check if this is a terminal state."""
        return self in {IntakeState.SUPERSEDED, IntakeState.CANCELLED}


class AnswerApplicability(Enum):
    """
    Whether a question applies to this application.

    PENDING: Not yet determined
    APPLICABLE: Question applies and needs an answer
    NOT_APPLICABLE: Question does not apply (with reason)
    """

    PENDING = "PENDING"
    APPLICABLE = "APPLICABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AnswerValueState(Enum):
    """
    State of the answer value itself.

    UNANSWERED: No value provided yet
    PROPOSED: Value proposed by import/AI, not yet accepted
    KNOWN: Value is known and accepted
    CONFLICT: Multiple conflicting values exist
    INVALID: Value failed validation
    NOT_APPLICABLE: Question is not applicable
    """

    UNANSWERED = "UNANSWERED"
    PROPOSED = "PROPOSED"
    KNOWN = "KNOWN"
    CONFLICT = "CONFLICT"
    INVALID = "INVALID"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class AnswerReviewState(Enum):
    """
    Review state for an answer.

    DRAFT: Initial state, not yet reviewed
    ANSWERED: Value provided but not confirmed
    NEEDS_EVIDENCE: Requires supporting evidence
    CHANGES_REQUESTED: Reviewer requested changes
    CONFIRMED: Reviewed and confirmed
    """

    DRAFT = "DRAFT"
    ANSWERED = "ANSWERED"
    NEEDS_EVIDENCE = "NEEDS_EVIDENCE"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    CONFIRMED = "CONFIRMED"


class CandidateState(Enum):
    """
    State of a candidate value from import or AI.

    Candidates are proposed values that require review before
    becoming canonical answers.
    """

    PROPOSED = "PROPOSED"
    ACCEPTED = "ACCEPTED"
    ACCEPTED_WITH_EDIT = "ACCEPTED_WITH_EDIT"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"
    CONFLICT = "CONFLICT"
    SUPERSEDED = "SUPERSEDED"
    INVALID = "INVALID"

    @property
    def is_terminal(self) -> bool:
        """Check if this is a terminal state."""
        return self in {
            CandidateState.ACCEPTED,
            CandidateState.ACCEPTED_WITH_EDIT,
            CandidateState.REJECTED,
            CandidateState.SUPERSEDED,
            CandidateState.INVALID,
        }


class EvidenceState(Enum):
    """
    State of uploaded evidence.

    UPLOADED: File received, not yet validated
    VALIDATING: Validation in progress
    VALID: Passed validation
    INVALID: Failed validation
    QUARANTINED: Suspicious content, requires review
    SUPERSEDED: Replaced by newer evidence
    """

    UPLOADED = "UPLOADED"
    VALIDATING = "VALIDATING"
    VALID = "VALID"
    INVALID = "INVALID"
    QUARANTINED = "QUARANTINED"
    SUPERSEDED = "SUPERSEDED"

    def can_transition_to(self, target: EvidenceState) -> bool:
        """Check if transition to target state is allowed."""
        allowed: dict[EvidenceState, set[EvidenceState]] = {
            EvidenceState.UPLOADED: {EvidenceState.VALIDATING},
            EvidenceState.VALIDATING: {
                EvidenceState.VALID,
                EvidenceState.INVALID,
                EvidenceState.QUARANTINED,
            },
            EvidenceState.VALID: {EvidenceState.SUPERSEDED},
            EvidenceState.INVALID: set(),  # Terminal
            EvidenceState.QUARANTINED: {
                EvidenceState.VALID,
                EvidenceState.INVALID,
            },
            EvidenceState.SUPERSEDED: set(),  # Terminal
        }
        return target in allowed.get(self, set())


class ActorType(Enum):
    """
    Type of actor performing actions.

    CONFIGURED: Actor configured at startup (first slice)
    OIDC_USER: Actor authenticated via OIDC
    SYSTEM: System/automated actor
    """

    CONFIGURED = "CONFIGURED"
    OIDC_USER = "OIDC_USER"
    SYSTEM = "SYSTEM"


class ImportRunState(Enum):
    """
    State of an import run (workbook processing).

    QUEUED: Waiting to start
    VALIDATING: Validating input
    EXTRACTING: Extracting data
    RECONCILING: Reconciling with existing data
    COMPLETED: Finished successfully
    COMPLETED_WITH_FINDINGS: Finished with findings/warnings
    QUARANTINED: Suspicious content
    FAILED: Failed with error
    CANCELLED: Cancelled by user
    """

    QUEUED = "QUEUED"
    VALIDATING = "VALIDATING"
    EXTRACTING = "EXTRACTING"
    RECONCILING = "RECONCILING"
    COMPLETED = "COMPLETED"
    COMPLETED_WITH_FINDINGS = "COMPLETED_WITH_FINDINGS"
    QUARANTINED = "QUARANTINED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"

    @property
    def is_terminal(self) -> bool:
        """Check if this is a terminal state."""
        return self in {
            ImportRunState.COMPLETED,
            ImportRunState.COMPLETED_WITH_FINDINGS,
            ImportRunState.QUARANTINED,
            ImportRunState.FAILED,
            ImportRunState.CANCELLED,
        }


class WaveUtilRowState(Enum):
    """
    Lifecycle state of a WaveUtil row.

    ACTIVE: Row is current
    RETIRED: Row has been retired/removed
    """

    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class WaveUtilReviewState(Enum):
    """
    Review state of a WaveUtil row.

    DRAFT: Initial state
    PROPOSED_CHANGE: Change proposed from import
    NEEDS_RECONCILIATION: Conflicts need resolution
    CONFIRMED: Reviewed and confirmed
    """

    DRAFT = "DRAFT"
    PROPOSED_CHANGE = "PROPOSED_CHANGE"
    NEEDS_RECONCILIATION = "NEEDS_RECONCILIATION"
    CONFIRMED = "CONFIRMED"
