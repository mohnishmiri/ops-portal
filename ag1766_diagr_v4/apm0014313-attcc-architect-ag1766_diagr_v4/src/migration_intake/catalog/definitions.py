"""
Catalog definitions for questionnaire structure.

This module defines the immutable data structures for catalog releases,
sections, questions, and their relationships. These structures are
populated by the catalog compiler and stored in the database.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class RequiredLevel(Enum):
    """
    Required level for a question.

    REQUIRED: Must be answered for intake completion
    CONDITIONAL: Required when applicability condition is true
    OPTIONAL: May be skipped
    COMPUTED: Value is computed, not directly entered
    """

    REQUIRED = "REQUIRED"
    CONDITIONAL = "CONDITIONAL"
    OPTIONAL = "OPTIONAL"
    COMPUTED = "COMPUTED"


class CollectionMode(Enum):
    """
    How a question's answer is collected.

    DIRECT: User enters value directly
    IMPORT: Value comes from workbook/external source
    COMPUTED: Value is calculated from other answers
    APPROVAL: Value comes from approval workflow
    """

    DIRECT = "DIRECT"
    IMPORT = "IMPORT"
    COMPUTED = "COMPUTED"
    APPROVAL = "APPROVAL"


@dataclass(frozen=True)
class AllowedValue:
    """
    An allowed value for controlled vocabulary questions.

    Attributes:
        code: Machine-readable code (uppercase)
        label: Human-readable display label
        description: Optional longer description
        is_default: Whether this is the default selection
        is_other: Whether this represents "Other" with free text
    """

    code: str
    label: str
    description: str | None = None
    is_default: bool = False
    is_other: bool = False

    def __post_init__(self) -> None:
        # Normalize code to uppercase
        if self.code != self.code.upper():
            object.__setattr__(self, "code", self.code.upper())


@dataclass(frozen=True)
class ApplicabilityCondition:
    """
    Condition that determines when a question applies.

    Attributes:
        raw_expression: Original prose expression from catalog
        compiled_ast: Compiled JSON AST for evaluation, or None if pending
        is_pending: Whether condition could not be compiled
    """

    raw_expression: str
    compiled_ast: dict[str, Any] | None = None
    is_pending: bool = False


@dataclass(frozen=True)
class SourceRelationship:
    """
    Relationship to a data source for a question.

    Attributes:
        source_label: Source identifier (e.g., "Workbook", "iTAP")
        priority: Priority order (1 = preferred, higher = fallback)
    """

    source_label: str
    priority: int = 1


@dataclass(frozen=True)
class OwnerRelationship:
    """
    Relationship to an owner role for a question.

    Attributes:
        role_code: Role code (uppercase with underscores)
    """

    role_code: str

    def __post_init__(self) -> None:
        # Normalize role code: uppercase, spaces to underscores
        normalized = self.role_code.upper().replace(" ", "_")
        if self.role_code != normalized:
            object.__setattr__(self, "role_code", normalized)


@dataclass(frozen=True)
class DestinationMapping:
    """
    Mapping to a destination for a question's answer.

    Attributes:
        target_type: Type of target (REGISTER, OUTPUT, ANSWER)
        target_identifier: Identifier of the target
    """

    target_type: str
    target_identifier: str


@dataclass(frozen=True)
class Section:
    """
    A section in the questionnaire catalog.

    Attributes:
        code: Machine-readable section code (uppercase)
        title: Human-readable section title
        order: Display order within the catalog
        description: Optional section description
    """

    code: str
    title: str
    order: int
    description: str | None = None

    def __post_init__(self) -> None:
        # Normalize code to uppercase
        if self.code != self.code.upper():
            object.__setattr__(self, "code", self.code.upper())


@dataclass(frozen=True)
class QuestionDefinition:
    """
    Definition of a question in the catalog.

    Attributes:
        question_id: Unique question identifier (e.g., CTL-001)
        section_code: Section this question belongs to
        question_text: The question text displayed to users
        response_type: Response type code (e.g., BOOLEAN, TEXT)
        response_schema_version: Version of the response type schema
        required_level: Whether/when the question is required
        order: Display order within the section
        help_text: Optional help text for users
        collection_mode: How the answer is collected
        allowed_values: Allowed values for controlled vocabularies
        applicability_condition: Condition for when question applies
        sources: Data sources for this question
        owners: Owner roles for this question
        destinations: Where the answer is used
        units: Allowed units for measurement types
        field_names: Named fields for pair/set types
    """

    question_id: str
    section_code: str
    question_text: str
    response_type: str
    response_schema_version: str
    required_level: str
    order: int
    help_text: str | None = None
    collection_mode: str = "DIRECT"
    allowed_values: tuple[AllowedValue, ...] = field(default_factory=tuple)
    applicability_condition: ApplicabilityCondition | None = None
    sources: tuple[SourceRelationship, ...] = field(default_factory=tuple)
    owners: tuple[OwnerRelationship, ...] = field(default_factory=tuple)
    destinations: tuple[DestinationMapping, ...] = field(default_factory=tuple)
    units: tuple[str, ...] = field(default_factory=tuple)
    field_names: dict[str, str] | None = None


@dataclass(frozen=True)
class CatalogRelease:
    """
    An immutable catalog release.

    A release contains the compiled catalog definitions and is referenced
    by intakes. Once published, a release cannot be modified.

    Attributes:
        release_id: Unique release identifier (UUID)
        version: Semantic version string
        source_filename: Original source file name
        source_hash: SHA-256 hash of source file
        compiler_version: Version of compiler used
        published: Whether the release is published
        published_at: When the release was published
        sections: Ordered sections in the catalog
        questions: Questions indexed by question_id
        canonical_hash: Hash of canonical serialization
    """

    release_id: str
    version: str
    source_filename: str
    source_hash: str
    compiler_version: str
    published: bool = False
    published_at: datetime | None = None
    sections: tuple[Section, ...] = field(default_factory=tuple)
    questions: dict[str, QuestionDefinition] = field(default_factory=dict)
    canonical_hash: str | None = None

    def get_section(self, code: str) -> Section | None:
        """Get a section by code."""
        for section in self.sections:
            if section.code == code.upper():
                return section
        return None

    def get_question(self, question_id: str) -> QuestionDefinition | None:
        """Get a question by ID."""
        return self.questions.get(question_id)

    def get_questions_for_section(self, section_code: str) -> tuple[QuestionDefinition, ...]:
        """Get all questions for a section, ordered."""
        questions = [
            q for q in self.questions.values()
            if q.section_code == section_code.upper()
        ]
        return tuple(sorted(questions, key=lambda q: q.order))

    def question_count(self) -> int:
        """Get total number of questions."""
        return len(self.questions)

    def section_count(self) -> int:
        """Get total number of sections."""
        return len(self.sections)
