"""
Domain-level application service errors — A01.

All application service errors are subclasses of ApplicationServiceError.
Callers (e.g. web adapters) should catch specific error types to map them
to appropriate HTTP responses.
"""

from __future__ import annotations


class ApplicationServiceError(Exception):
    """Base for all application service errors."""


class DuplicateIdentifierError(ApplicationServiceError):
    """Normalized identifier already exists on another application."""


class ApplicationNotActiveError(ApplicationServiceError):
    """Application is not in ACTIVE state; cannot accept new intakes."""


class CatalogNotPublishedError(ApplicationServiceError):
    """Catalog release is not in PUBLISHED state."""


class CatalogVersionConflictError(ApplicationServiceError):
    """Same semantic version already published with different content hash."""


class OpenIntakeExistsError(ApplicationServiceError):
    """Application already has an open (non-terminal) intake."""


class ConcurrencyConflictError(ApplicationServiceError):
    """Expected row version does not match current; stale update rejected."""


class ApplicationNotFoundError(ApplicationServiceError):
    """Application ID does not correspond to any known application."""


class EvidenceTooLargeError(ApplicationServiceError):
    """Evidence stream exceeds the maximum allowed size."""


class EvidenceMediaTypeNotAllowedError(ApplicationServiceError):
    """Media type is not in the allowed set for evidence uploads."""


# ---------------------------------------------------------------------------
# A02 — Answer service errors
# ---------------------------------------------------------------------------


class IntakeNotOpenError(ApplicationServiceError):
    """Intake state does not allow new answers."""


class QuestionNotFoundError(ApplicationServiceError):
    """Question code not found in the intake's catalog release."""


class InvalidResponseTypeError(ApplicationServiceError):
    """Computed/register/approval types cannot be directly saved."""


class InvalidResponseError(ApplicationServiceError):
    """Response payload failed validation."""


class ClearReasonRequiredError(ApplicationServiceError):
    """Clearing a confirmed answer requires an explicit reason."""


class NoCurrentRevisionError(ApplicationServiceError):
    """Cannot confirm or clear an answer with no current revision."""


class RationaleRequiredError(ApplicationServiceError):
    """This operation requires a non-empty rationale."""


# ---------------------------------------------------------------------------
# B06 — Workbook orchestration service errors
# ---------------------------------------------------------------------------


class EvidenceNotFoundError(ApplicationServiceError):
    """Evidence item ID does not exist."""


class EvidenceApplicationMismatchError(ApplicationServiceError):
    """Evidence item belongs to a different application."""


class WorkbookQuarantinedError(ApplicationServiceError):
    """Workbook failed security inspection and is quarantined."""
