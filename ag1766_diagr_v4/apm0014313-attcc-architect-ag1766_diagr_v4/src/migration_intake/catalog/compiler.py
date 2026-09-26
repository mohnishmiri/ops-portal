"""
Catalog CSV compiler.

This module compiles the authoritative question catalog CSV into an
immutable catalog release. It validates, normalizes, and transforms
the CSV rows into structured definitions.
"""

from __future__ import annotations

import csv
import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from io import StringIO
from typing import Any

from migration_intake.catalog.conditions import ConditionCompiler, CycleDetector
from migration_intake.catalog.definitions import (
    AllowedValue,
    ApplicabilityCondition,
    CatalogRelease,
    DestinationMapping,
    OwnerRelationship,
    QuestionDefinition,
    Section,
    SourceRelationship,
)
from migration_intake.catalog.diagnostics import (
    CompilerReport,
    DiagnosticCodes,
    DiagnosticCollector,
)
from migration_intake.catalog.response_types.base import ResponseTypeCodes

# Compiler version for tracking
COMPILER_VERSION = "1.0.0"

# Required CSV columns
REQUIRED_COLUMNS = {
    "Question_ID",
    "Section",
    "Question",
    "Response_Type",
    "Allowed_Values",
    "Required_Level",
    "Required_When",
    "Preferred_Source",
    "Fallback_Sources",
    "Owner",
    "Output",
    "Destination",
}

# Column aliases (typos and variations)
COLUMN_ALIASES = {
    "Resonse": "Response",
    "Allowed_Values_or_Unit": "Allowed_Values",
    "Question_Text": "Question",
    "Default_Owner": "Owner",
    "Target_Outputs": "Output",
    "Response": "Response_Value",  # If present, treat as response value
}

# Known sources
KNOWN_SOURCES = {
    "WORKBOOK", "ITAP", "MOTS", "MANUAL", "PORTAL", "API", "IMPORT",
}

# Known owner roles
KNOWN_ROLES = {
    "APPLICATION_OWNER", "DBA", "NETWORK_ADMIN", "SECURITY_ADMIN",
    "ARCHITECT", "DEVELOPER", "OPERATIONS", "MANAGER",
}

# Known outputs
KNOWN_OUTPUTS = {
    "TOPOLOGY", "ADS", "DDD", "ALL",
}

# Known destinations
KNOWN_DESTINATIONS = {
    "ANSWER", "REGISTER", "ISSUE_REGISTER", "DECISION_REGISTER",
    "APPROVAL_REGISTER", "EVIDENCE",
}

# Valid response types (from ResponseTypeCodes)
VALID_RESPONSE_TYPES = {
    ResponseTypeCodes.BOOLEAN,
    ResponseTypeCodes.SINGLE_SELECT,
    ResponseTypeCodes.TEXT,
    ResponseTypeCodes.LONG_TEXT,
    ResponseTypeCodes.IDENTIFIER,
    ResponseTypeCodes.MULTI_SELECT,
    ResponseTypeCodes.TEXT_PAIR,
    ResponseTypeCodes.COUNT_PAIR,
    ResponseTypeCodes.CONTROLLED_PAIR,
    ResponseTypeCodes.PEOPLE_LIST,
    ResponseTypeCodes.MEASUREMENT,
    ResponseTypeCodes.MEASUREMENT_PAIR,
    ResponseTypeCodes.MEASUREMENT_SET,
    ResponseTypeCodes.MEASUREMENT_CONTEXT,
    ResponseTypeCodes.BOOLEAN_WITH_RATIONALE,
    ResponseTypeCodes.CONTROLLED_SET,
    ResponseTypeCodes.SINGLE_SELECT_PER_COMPONENT,
    ResponseTypeCodes.DECISION_WITH_PERSON,
    ResponseTypeCodes.APPROVAL,
    ResponseTypeCodes.REGISTER_STATUS,
    ResponseTypeCodes.VALIDATION_RESULT,
    ResponseTypeCodes.ISSUE_REGISTER,
    ResponseTypeCodes.DECISION_REGISTER,
    ResponseTypeCodes.APPROVAL_REGISTER,
    ResponseTypeCodes.EVIDENCE_REFERENCE,
}


@dataclass
class CompileResult:
    """
    Result of catalog compilation.

    Attributes:
        release: Compiled catalog release (None if compilation failed)
        report: Compiler report with diagnostics
    """

    release: CatalogRelease | None
    report: CompilerReport


class CatalogCompiler:
    """
    Compiles catalog CSV to immutable release.

    Pipeline:
    1. Read and hash bytes
    2. Require exact CSV columns
    3. Validate unique question IDs
    4. Normalize sections, sources, owners, outputs, destinations
    5. Parse allowed values and units
    6. Attach response-type schema
    7. Compile Required_When to safe AST
    8. Validate cross-question references
    9. Detect dependency cycles
    10. Assign deterministic order
    11. Emit diagnostics and canonical serialization
    12. Hash and create release
    """

    def __init__(self) -> None:
        self._condition_compiler = ConditionCompiler()
        self._cycle_detector = CycleDetector()

    def compile(
        self,
        csv_content: str,
        version: str,
        source_filename: str = "catalog.csv",
    ) -> CompileResult:
        """Compile CSV content to catalog release."""
        diagnostics = DiagnosticCollector()

        # Step 1: Hash source content
        source_hash = hashlib.sha256(csv_content.encode("utf-8")).hexdigest()

        # Step 2: Parse CSV
        try:
            rows = self._parse_csv(csv_content, diagnostics)
        except Exception as e:
            diagnostics.error(
                DiagnosticCodes.MISSING_REQUIRED_FIELD,
                f"Failed to parse CSV: {e}",
            )
            return self._create_failed_result(
                source_filename, source_hash, diagnostics
            )

        if not rows:
            diagnostics.error(
                DiagnosticCodes.MISSING_REQUIRED_FIELD,
                "CSV contains no data rows",
            )
            return self._create_failed_result(
                source_filename, source_hash, diagnostics
            )

        # Step 3: Validate unique IDs
        question_ids = self._validate_unique_ids(rows, diagnostics)

        # Step 4-6: Parse questions
        questions: dict[str, QuestionDefinition] = {}
        sections: dict[str, Section] = {}
        type_counts: dict[str, int] = {}

        for row_num, row in enumerate(rows, start=2):  # Start at 2 (header is 1)
            question = self._parse_question(row, row_num, diagnostics)
            if question:
                questions[question.question_id] = question

                # Track sections
                if question.section_code not in sections:
                    sections[question.section_code] = Section(
                        code=question.section_code,
                        title=question.section_code,  # Use code as title for now
                        order=len(sections) + 1,
                    )

                # Track type counts
                type_counts[question.response_type] = (
                    type_counts.get(question.response_type, 0) + 1
                )

        # Step 7-8: Validate cross-references and detect cycles
        self._validate_references(questions, diagnostics)
        self._detect_cycles(questions, diagnostics)

        # Check if we have errors
        if diagnostics.has_errors():
            return self._create_failed_result(
                source_filename, source_hash, diagnostics, type_counts,
                len(sections), len(questions)
            )

        # Step 9-10: Create release
        release = self._create_release(
            questions, sections, version, source_filename, source_hash
        )

        # Create report
        report = CompilerReport(
            source_filename=source_filename,
            source_hash=source_hash,
            compiler_version=COMPILER_VERSION,
            diagnostics=diagnostics,
            section_count=len(sections),
            question_count=len(questions),
            type_counts=type_counts,
        )

        return CompileResult(release=release, report=report)

    def _parse_csv(
        self, content: str, diagnostics: DiagnosticCollector
    ) -> list[dict[str, str]]:
        """Parse CSV content and validate columns."""
        reader = csv.DictReader(StringIO(content))

        if reader.fieldnames is None:
            diagnostics.error(
                DiagnosticCodes.MISSING_REQUIRED_FIELD,
                "CSV has no header row",
            )
            return []

        # Normalize column names
        normalized_fields = {}
        for field in reader.fieldnames:
            normalized = field.strip()
            # Check for aliases
            if normalized in COLUMN_ALIASES:
                alias_target = COLUMN_ALIASES[normalized]
                diagnostics.info(
                    DiagnosticCodes.ALIAS_NORMALIZED,
                    f"Column alias '{normalized}' normalized to '{alias_target}'",
                )
                normalized = alias_target
            normalized_fields[field] = normalized

        # Check for required columns
        present_columns = set(normalized_fields.values())
        missing_columns = REQUIRED_COLUMNS - present_columns

        if missing_columns:
            diagnostics.error(
                DiagnosticCodes.MISSING_REQUIRED_FIELD,
                f"Missing required columns: {', '.join(sorted(missing_columns))}",
            )
            return []

        # Read rows with normalized column names
        rows = []
        for row in reader:
            normalized_row = {
                normalized_fields[k]: v for k, v in row.items()
            }
            rows.append(normalized_row)

        return rows

    def _validate_unique_ids(
        self, rows: list[dict[str, str]], diagnostics: DiagnosticCollector
    ) -> set[str]:
        """Validate that all question IDs are unique."""
        seen_ids: set[str] = set()
        unique_ids: set[str] = set()

        for row_num, row in enumerate(rows, start=2):
            question_id = row.get("Question_ID", "").strip()
            if not question_id:
                diagnostics.error(
                    DiagnosticCodes.MISSING_REQUIRED_FIELD,
                    "Missing Question_ID",
                    row_number=row_num,
                )
                continue

            if question_id in seen_ids:
                diagnostics.error(
                    DiagnosticCodes.DUPLICATE_ID,
                    f"Duplicate Question_ID: {question_id}",
                    row_number=row_num,
                    question_id=question_id,
                )
            else:
                seen_ids.add(question_id)
                unique_ids.add(question_id)

        return unique_ids

    def _parse_question(
        self,
        row: dict[str, str],
        row_num: int,
        diagnostics: DiagnosticCollector,
    ) -> QuestionDefinition | None:
        """Parse a single question from a CSV row."""
        question_id = row.get("Question_ID", "").strip()
        if not question_id:
            return None

        section_code = row.get("Section", "").strip().upper()
        question_text = row.get("Question", "").strip()
        response_type = row.get("Response_Type", "").strip().upper()
        collection_mode = row.get("Collection_Mode", "DIRECT").strip().upper()
        allowed_values_str = row.get("Allowed_Values", "").strip()
        required_level = row.get("Required_Level", "").strip().upper()
        required_when = row.get("Required_When", "").strip()
        preferred_source = row.get("Preferred_Source", "").strip()
        fallback_sources = row.get("Fallback_Sources", "").strip()
        owner = row.get("Owner", "").strip()
        output = row.get("Output", "").strip().upper()
        destination = row.get("Destination", "").strip().upper()

        # Validate response type
        if response_type not in VALID_RESPONSE_TYPES:
            diagnostics.error(
                DiagnosticCodes.UNSUPPORTED_RESPONSE_TYPE,
                f"Unsupported response type: {response_type}",
                row_number=row_num,
                question_id=question_id,
                field="Response_Type",
                raw_value=response_type,
            )
            return None

        # Parse allowed values
        allowed_values = self._parse_allowed_values(
            allowed_values_str, row_num, question_id, diagnostics
        )

        # Parse sources
        sources = self._parse_sources(
            preferred_source, fallback_sources, row_num, question_id, diagnostics
        )

        # Parse owners
        owners = self._parse_owners(owner, row_num, question_id, diagnostics)

        # Parse destinations
        destinations = self._parse_destinations(
            output, destination, row_num, question_id, diagnostics
        )

        # Compile condition
        applicability_condition = None
        if required_when:
            result = self._condition_compiler.compile(required_when)
            if result.success:
                applicability_condition = ApplicabilityCondition(
                    raw_expression=required_when,
                    compiled_ast=result.ast,
                )
            elif result.is_pending:
                applicability_condition = ApplicabilityCondition(
                    raw_expression=required_when,
                    is_pending=True,
                )
                diagnostics.warning(
                    DiagnosticCodes.MISSING_HELP_TEXT,  # Reuse for pending
                    f"Condition pending resolution: {required_when}",
                    row_number=row_num,
                    question_id=question_id,
                )
            else:
                diagnostics.error(
                    DiagnosticCodes.MALFORMED_CONDITION,
                    f"Invalid condition: {result.errors[0] if result.errors else 'unknown'}",
                    row_number=row_num,
                    question_id=question_id,
                    field="Required_When",
                    raw_value=required_when,
                )

        return QuestionDefinition(
            question_id=question_id,
            section_code=section_code,
            question_text=question_text,
            response_type=response_type,
            response_schema_version="1.0",
            required_level=required_level or "OPTIONAL",
            order=row_num - 1,  # 0-based order
            collection_mode=collection_mode or "DIRECT",
            allowed_values=tuple(allowed_values),
            applicability_condition=applicability_condition,
            sources=tuple(sources),
            owners=tuple(owners),
            destinations=tuple(destinations),
        )

    def _parse_allowed_values(
        self,
        values_str: str,
        row_num: int,
        question_id: str,
        diagnostics: DiagnosticCollector,
    ) -> list[AllowedValue]:
        """Parse pipe-delimited allowed values."""
        if not values_str:
            return []

        values = []
        for value in values_str.split("|"):
            value = value.strip()
            if value:
                # Normalize to uppercase
                code = value.upper()
                values.append(AllowedValue(code=code, label=value))

        return values

    def _parse_sources(
        self,
        preferred: str,
        fallbacks: str,
        row_num: int,
        question_id: str,
        diagnostics: DiagnosticCollector,
    ) -> list[SourceRelationship]:
        """Parse source relationships with priority."""
        sources = []
        priority = 1

        # Preferred source(s)
        if preferred:
            for source in preferred.split("|"):
                source = source.strip()
                if source:
                    normalized = source.upper().replace(" ", "_")
                    if normalized not in KNOWN_SOURCES:
                        diagnostics.warning(
                            DiagnosticCodes.BROAD_SOURCE_LABEL,
                            f"Unknown source: {source}",
                            row_number=row_num,
                            question_id=question_id,
                            field="Preferred_Source",
                            raw_value=source,
                        )
                    sources.append(SourceRelationship(
                        source_label=source,
                        priority=priority,
                    ))
                    priority += 1

        # Fallback sources
        if fallbacks:
            for source in fallbacks.split("|"):
                source = source.strip()
                if source:
                    normalized = source.upper().replace(" ", "_")
                    if normalized not in KNOWN_SOURCES:
                        diagnostics.warning(
                            DiagnosticCodes.BROAD_SOURCE_LABEL,
                            f"Unknown fallback source: {source}",
                            row_number=row_num,
                            question_id=question_id,
                            field="Fallback_Sources",
                            raw_value=source,
                        )
                    sources.append(SourceRelationship(
                        source_label=source,
                        priority=priority,
                    ))
                    priority += 1

        return sources

    def _parse_owners(
        self,
        owner_str: str,
        row_num: int,
        question_id: str,
        diagnostics: DiagnosticCollector,
    ) -> list[OwnerRelationship]:
        """Parse owner relationships."""
        if not owner_str:
            return []

        owners = []
        for owner in owner_str.split("|"):
            owner = owner.strip()
            if owner:
                # Normalize: uppercase, spaces to underscores
                normalized = owner.upper().replace(" ", "_")
                if normalized not in KNOWN_ROLES:
                    diagnostics.warning(
                        DiagnosticCodes.BROAD_SOURCE_LABEL,  # Reuse for unknown role
                        f"Unknown owner role: {owner}",
                        row_number=row_num,
                        question_id=question_id,
                        field="Owner",
                        raw_value=owner,
                    )
                owners.append(OwnerRelationship(role_code=normalized))

        return owners

    def _parse_destinations(
        self,
        output: str,
        destination: str,
        row_num: int,
        question_id: str,
        diagnostics: DiagnosticCollector,
    ) -> list[DestinationMapping]:
        """Parse destination mappings."""
        destinations = []

        # Handle output (Topology, ADS, DDD, ALL)
        if output:
            if output == "ALL":
                # Expand ALL to all outputs
                for out in ["TOPOLOGY", "ADS", "DDD"]:
                    destinations.append(DestinationMapping(
                        target_type="OUTPUT",
                        target_identifier=out,
                    ))
            elif output in KNOWN_OUTPUTS:
                destinations.append(DestinationMapping(
                    target_type="OUTPUT",
                    target_identifier=output,
                ))
            else:
                diagnostics.warning(
                    DiagnosticCodes.BROAD_SOURCE_LABEL,
                    f"Unknown output: {output}",
                    row_number=row_num,
                    question_id=question_id,
                    field="Output",
                    raw_value=output,
                )

        # Handle destination (ANSWER, REGISTER, etc.)
        if destination:
            if destination in KNOWN_DESTINATIONS:
                destinations.append(DestinationMapping(
                    target_type="DESTINATION",
                    target_identifier=destination,
                ))
            else:
                diagnostics.warning(
                    DiagnosticCodes.BROAD_SOURCE_LABEL,
                    f"Unknown destination: {destination}",
                    row_number=row_num,
                    question_id=question_id,
                    field="Destination",
                    raw_value=destination,
                )

        return destinations

    def _validate_references(
        self,
        questions: dict[str, QuestionDefinition],
        diagnostics: DiagnosticCollector,
    ) -> None:
        """Validate cross-question references in conditions."""
        for question_id, question in questions.items():
            if question.applicability_condition and question.applicability_condition.compiled_ast:
                refs = self._extract_question_refs(question.applicability_condition.compiled_ast)
                for ref in refs:
                    if ref not in questions:
                        diagnostics.error(
                            DiagnosticCodes.UNRESOLVED_DEPENDENCY,
                            f"Condition references unknown question: {ref}",
                            question_id=question_id,
                            field="Required_When",
                        )

    def _extract_question_refs(self, ast: dict[str, Any]) -> set[str]:
        """Extract question references from condition AST."""
        refs: set[str] = set()

        if "question" in ast:
            refs.add(ast["question"])

        if "operand" in ast and isinstance(ast["operand"], dict):
            refs.update(self._extract_question_refs(ast["operand"]))

        if "conditions" in ast and isinstance(ast["conditions"], list):
            for cond in ast["conditions"]:
                if isinstance(cond, dict):
                    refs.update(self._extract_question_refs(cond))

        return refs

    def _detect_cycles(
        self,
        questions: dict[str, QuestionDefinition],
        diagnostics: DiagnosticCollector,
    ) -> None:
        """Detect dependency cycles in conditions."""
        # Build dependency graph
        dependencies: dict[str, list[str]] = {}
        for question_id, question in questions.items():
            deps: list[str] = []
            if question.applicability_condition and question.applicability_condition.compiled_ast:
                refs = self._extract_question_refs(question.applicability_condition.compiled_ast)
                deps = list(refs)
            dependencies[question_id] = deps

        # Detect cycles
        cycles = self._cycle_detector.detect(dependencies)
        for cycle in cycles:
            diagnostics.error(
                DiagnosticCodes.DEPENDENCY_CYCLE,
                f"Dependency cycle detected: {' -> '.join(cycle)}",
            )

    def _create_release(
        self,
        questions: dict[str, QuestionDefinition],
        sections: dict[str, Section],
        version: str,
        source_filename: str,
        source_hash: str,
    ) -> CatalogRelease:
        """Create the catalog release."""
        # Sort sections by order
        sorted_sections = tuple(sorted(sections.values(), key=lambda s: s.order))

        # Compute canonical hash
        canonical_data = self._canonical_serialize(questions, sorted_sections)
        canonical_hash = hashlib.sha256(canonical_data.encode("utf-8")).hexdigest()

        return CatalogRelease(
            release_id=str(uuid.uuid4()),
            version=version,
            source_filename=source_filename,
            source_hash=source_hash,
            compiler_version=COMPILER_VERSION,
            published=True,
            published_at=datetime.now(UTC),
            sections=sorted_sections,
            questions=questions,
            canonical_hash=canonical_hash,
        )

    def _canonical_serialize(
        self,
        questions: dict[str, QuestionDefinition],
        sections: tuple[Section, ...],
    ) -> str:
        """Create canonical JSON serialization for hashing."""
        data = {
            "sections": [
                {"code": s.code, "title": s.title, "order": s.order}
                for s in sections
            ],
            "questions": {
                qid: {
                    "question_id": q.question_id,
                    "section_code": q.section_code,
                    "question_text": q.question_text,
                    "response_type": q.response_type,
                    "required_level": q.required_level,
                    "order": q.order,
                }
                for qid, q in sorted(questions.items())
            },
        }
        return json.dumps(data, sort_keys=True, separators=(",", ":"))

    def _create_failed_result(
        self,
        source_filename: str,
        source_hash: str,
        diagnostics: DiagnosticCollector,
        type_counts: dict[str, int] | None = None,
        section_count: int = 0,
        question_count: int = 0,
    ) -> CompileResult:
        """Create a failed compilation result."""
        report = CompilerReport(
            source_filename=source_filename,
            source_hash=source_hash,
            compiler_version=COMPILER_VERSION,
            diagnostics=diagnostics,
            section_count=section_count,
            question_count=question_count,
            type_counts=type_counts or {},
        )
        return CompileResult(release=None, report=report)
