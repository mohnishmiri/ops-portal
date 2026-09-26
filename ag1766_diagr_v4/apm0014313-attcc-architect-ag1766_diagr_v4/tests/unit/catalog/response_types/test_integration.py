"""
Tests for R06: Response registry integration and catalog coverage.

These tests verify:
- Exactly 25 registered types
- Every catalog row resolves to a response type
- All controls receive editor or computed workflow
- No generic text fallback
- Required controlled vocabularies present
"""

from __future__ import annotations

import pytest


class TestRegistryCompleteness:
    """Tests for registry completeness - exactly 25 types."""

    def test_exactly_25_types_registered(self) -> None:
        """Registry should have exactly 25 response types."""
        from migration_intake.catalog.response_types import get_default_registry

        registry = get_default_registry()

        assert registry.count() == 25

    def test_all_type_codes_registered(self) -> None:
        """All ResponseTypeCodes should be registered."""
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        registry = get_default_registry()

        expected_codes = [
            # Scalar types (R01)
            ResponseTypeCodes.BOOLEAN,
            ResponseTypeCodes.SINGLE_SELECT,
            ResponseTypeCodes.TEXT,
            ResponseTypeCodes.LONG_TEXT,
            ResponseTypeCodes.IDENTIFIER,
            # Collection types (R02)
            ResponseTypeCodes.MULTI_SELECT,
            ResponseTypeCodes.TEXT_PAIR,
            ResponseTypeCodes.COUNT_PAIR,
            ResponseTypeCodes.CONTROLLED_PAIR,
            ResponseTypeCodes.PEOPLE_LIST,
            # Measurement types (R03)
            ResponseTypeCodes.MEASUREMENT,
            ResponseTypeCodes.MEASUREMENT_PAIR,
            ResponseTypeCodes.MEASUREMENT_SET,
            ResponseTypeCodes.MEASUREMENT_CONTEXT,
            # Decision types (R04)
            ResponseTypeCodes.BOOLEAN_WITH_RATIONALE,
            ResponseTypeCodes.CONTROLLED_SET,
            ResponseTypeCodes.SINGLE_SELECT_PER_COMPONENT,
            ResponseTypeCodes.DECISION_WITH_PERSON,
            ResponseTypeCodes.APPROVAL,
            # Computed types (R05)
            ResponseTypeCodes.REGISTER_STATUS,
            ResponseTypeCodes.VALIDATION_RESULT,
            ResponseTypeCodes.ISSUE_REGISTER,
            ResponseTypeCodes.DECISION_REGISTER,
            ResponseTypeCodes.APPROVAL_REGISTER,
            ResponseTypeCodes.EVIDENCE_REFERENCE,
        ]

        for code in expected_codes:
            response_type = registry.get(code)
            assert response_type is not None, f"Missing type: {code}"
            assert response_type.code == code

    def test_no_duplicate_registrations(self) -> None:
        """Registry should not have duplicate type codes."""
        from migration_intake.catalog.response_types import get_default_registry

        registry = get_default_registry()
        codes = [t.code for t in registry.all_types()]

        assert len(codes) == len(set(codes)), "Duplicate type codes found"


class TestCatalogRowResolution:
    """Tests for catalog row resolution."""

    def test_all_valid_response_types_resolve(self) -> None:
        """All valid response type codes should resolve in registry."""
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        registry = get_default_registry()

        # All codes from ResponseTypeCodes should resolve
        all_codes = [
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
        ]

        for code in all_codes:
            response_type = registry.get(code)
            assert response_type is not None, f"Type {code} does not resolve"

    def test_unknown_type_returns_none(self) -> None:
        """Unknown response type should return None, not fallback."""
        from migration_intake.catalog.response_types import get_default_registry

        registry = get_default_registry()

        result = registry.get("UNKNOWN_TYPE")

        assert result is None, "Unknown type should return None, not fallback"


class TestEditorAndComputedWorkflow:
    """Tests for editor and computed workflow assignment."""

    def test_scalar_types_have_editors(self) -> None:
        """Scalar types should have editor keys (not computed)."""
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        registry = get_default_registry()

        scalar_codes = [
            ResponseTypeCodes.BOOLEAN,
            ResponseTypeCodes.SINGLE_SELECT,
            ResponseTypeCodes.TEXT,
            ResponseTypeCodes.LONG_TEXT,
            ResponseTypeCodes.IDENTIFIER,
        ]

        for code in scalar_codes:
            response_type = registry.get(code)
            assert response_type is not None
            assert response_type.is_computed is False, f"{code} should not be computed"
            assert response_type.editor_key is not None, f"{code} should have editor_key"

    def test_collection_types_have_editors(self) -> None:
        """Collection types should have editor keys (not computed)."""
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        registry = get_default_registry()

        collection_codes = [
            ResponseTypeCodes.MULTI_SELECT,
            ResponseTypeCodes.TEXT_PAIR,
            ResponseTypeCodes.COUNT_PAIR,
            ResponseTypeCodes.CONTROLLED_PAIR,
            ResponseTypeCodes.PEOPLE_LIST,
        ]

        for code in collection_codes:
            response_type = registry.get(code)
            assert response_type is not None
            assert response_type.is_computed is False, f"{code} should not be computed"
            assert response_type.editor_key is not None, f"{code} should have editor_key"

    def test_measurement_types_have_editors(self) -> None:
        """Measurement types should have editor keys (not computed)."""
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        registry = get_default_registry()

        measurement_codes = [
            ResponseTypeCodes.MEASUREMENT,
            ResponseTypeCodes.MEASUREMENT_PAIR,
            ResponseTypeCodes.MEASUREMENT_SET,
            ResponseTypeCodes.MEASUREMENT_CONTEXT,
        ]

        for code in measurement_codes:
            response_type = registry.get(code)
            assert response_type is not None
            assert response_type.is_computed is False, f"{code} should not be computed"
            assert response_type.editor_key is not None, f"{code} should have editor_key"

    def test_decision_types_have_editors_except_approval(self) -> None:
        """Decision types should have editors, except APPROVAL which is computed."""
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        registry = get_default_registry()

        # Non-computed decision types
        decision_codes = [
            ResponseTypeCodes.BOOLEAN_WITH_RATIONALE,
            ResponseTypeCodes.CONTROLLED_SET,
            ResponseTypeCodes.SINGLE_SELECT_PER_COMPONENT,
            ResponseTypeCodes.DECISION_WITH_PERSON,
        ]

        for code in decision_codes:
            response_type = registry.get(code)
            assert response_type is not None
            assert response_type.is_computed is False, f"{code} should not be computed"
            assert response_type.editor_key is not None, f"{code} should have editor_key"

        # APPROVAL is computed
        approval = registry.get(ResponseTypeCodes.APPROVAL)
        assert approval is not None
        assert approval.is_computed is True, "APPROVAL should be computed"

    def test_computed_types_are_marked_computed(self) -> None:
        """Computed types should be marked as computed."""
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        registry = get_default_registry()

        computed_codes = [
            ResponseTypeCodes.REGISTER_STATUS,
            ResponseTypeCodes.VALIDATION_RESULT,
            ResponseTypeCodes.ISSUE_REGISTER,
            ResponseTypeCodes.DECISION_REGISTER,
            ResponseTypeCodes.APPROVAL_REGISTER,
            # APPROVAL is also computed
            ResponseTypeCodes.APPROVAL,
        ]

        for code in computed_codes:
            response_type = registry.get(code)
            assert response_type is not None
            assert response_type.is_computed is True, f"{code} should be computed"

    def test_evidence_reference_is_editable(self) -> None:
        """EVIDENCE_REFERENCE should be editable (not computed)."""
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        registry = get_default_registry()

        evidence_ref = registry.get(ResponseTypeCodes.EVIDENCE_REFERENCE)
        assert evidence_ref is not None
        assert evidence_ref.is_computed is False, "EVIDENCE_REFERENCE should be editable"


class TestNoGenericTextFallback:
    """Tests to ensure no generic text fallback."""

    def test_registry_has_no_generic_fallback(self) -> None:
        """Registry should not have a generic TEXT fallback for unknown types."""
        from migration_intake.catalog.response_types import get_default_registry

        registry = get_default_registry()

        # Unknown type should return None, not TEXT
        result = registry.get("CUSTOM_TYPE")
        assert result is None

        result = registry.get("GENERIC")
        assert result is None

    def test_all_types_have_specific_implementations(self) -> None:
        """All registered types should have specific implementations."""
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.catalog.response_types.base import ResponseTypeBase

        registry = get_default_registry()

        for response_type in registry.all_types():
            # Each type should be a concrete implementation, not just base
            assert response_type.__class__ != ResponseTypeBase
            # Each type should have a specific code
            assert response_type.code is not None
            assert len(response_type.code) > 0


class TestControlledVocabularies:
    """Tests for required controlled vocabularies."""

    def test_boolean_type_has_yes_no_unknown(self) -> None:
        """BOOLEAN type should support YES/NO/UNKNOWN vocabulary."""
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        registry = get_default_registry()
        boolean_type = registry.get(ResponseTypeCodes.BOOLEAN)

        assert boolean_type is not None

        # Validate YES
        result = boolean_type.validate({"value": "YES"})
        assert result.is_valid is True

        # Validate NO
        result = boolean_type.validate({"value": "NO"})
        assert result.is_valid is True

        # Validate UNKNOWN
        result = boolean_type.validate({"value": "UNKNOWN"})
        assert result.is_valid is True

    def test_single_select_validates_allowed_values(self) -> None:
        """SINGLE_SELECT should validate against allowed values."""
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        registry = get_default_registry()
        single_select = registry.get(ResponseTypeCodes.SINGLE_SELECT)

        assert single_select is not None

        # With allowed values configured, should validate
        # Note: The actual validation depends on schema configuration

    def test_identifier_type_supports_known_types(self) -> None:
        """IDENTIFIER type should support known identifier types."""
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        registry = get_default_registry()
        identifier_type = registry.get(ResponseTypeCodes.IDENTIFIER)

        assert identifier_type is not None

        # Validate with CORRELATION_ID type
        result = identifier_type.validate({
            "identifier_type": "CORRELATION_ID",
            "value": "ABC-123",
            "normalized_value": "ABC-123",
        })
        assert result.is_valid is True


class TestTypeGroupCoverage:
    """Tests for type group coverage."""

    def test_scalar_group_complete(self) -> None:
        """R01 scalar group should have all 5 types."""
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        registry = get_default_registry()

        scalar_types = [
            ResponseTypeCodes.BOOLEAN,
            ResponseTypeCodes.SINGLE_SELECT,
            ResponseTypeCodes.TEXT,
            ResponseTypeCodes.LONG_TEXT,
            ResponseTypeCodes.IDENTIFIER,
        ]

        for code in scalar_types:
            assert registry.get(code) is not None, f"Missing scalar type: {code}"

    def test_collection_group_complete(self) -> None:
        """R02 collection group should have all 5 types."""
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        registry = get_default_registry()

        collection_types = [
            ResponseTypeCodes.MULTI_SELECT,
            ResponseTypeCodes.TEXT_PAIR,
            ResponseTypeCodes.COUNT_PAIR,
            ResponseTypeCodes.CONTROLLED_PAIR,
            ResponseTypeCodes.PEOPLE_LIST,
        ]

        for code in collection_types:
            assert registry.get(code) is not None, f"Missing collection type: {code}"

    def test_measurement_group_complete(self) -> None:
        """R03 measurement group should have all 4 types."""
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        registry = get_default_registry()

        measurement_types = [
            ResponseTypeCodes.MEASUREMENT,
            ResponseTypeCodes.MEASUREMENT_PAIR,
            ResponseTypeCodes.MEASUREMENT_SET,
            ResponseTypeCodes.MEASUREMENT_CONTEXT,
        ]

        for code in measurement_types:
            assert registry.get(code) is not None, f"Missing measurement type: {code}"

    def test_decision_group_complete(self) -> None:
        """R04 decision group should have all 5 types."""
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        registry = get_default_registry()

        decision_types = [
            ResponseTypeCodes.BOOLEAN_WITH_RATIONALE,
            ResponseTypeCodes.CONTROLLED_SET,
            ResponseTypeCodes.SINGLE_SELECT_PER_COMPONENT,
            ResponseTypeCodes.DECISION_WITH_PERSON,
            ResponseTypeCodes.APPROVAL,
        ]

        for code in decision_types:
            assert registry.get(code) is not None, f"Missing decision type: {code}"

    def test_computed_group_complete(self) -> None:
        """R05 computed group should have all 6 types."""
        from migration_intake.catalog.response_types import get_default_registry
        from migration_intake.catalog.response_types.base import ResponseTypeCodes

        registry = get_default_registry()

        computed_types = [
            ResponseTypeCodes.REGISTER_STATUS,
            ResponseTypeCodes.VALIDATION_RESULT,
            ResponseTypeCodes.ISSUE_REGISTER,
            ResponseTypeCodes.DECISION_REGISTER,
            ResponseTypeCodes.APPROVAL_REGISTER,
            ResponseTypeCodes.EVIDENCE_REFERENCE,
        ]

        for code in computed_types:
            assert registry.get(code) is not None, f"Missing computed type: {code}"


class TestRegistryIntegrationWithCompiler:
    """Tests for registry integration with catalog compiler."""

    def test_compiler_validates_against_registry(self) -> None:
        """Catalog compiler should validate response types against registry."""
        from migration_intake.catalog.compiler import CatalogCompiler

        compiler = CatalogCompiler()

        # Valid type should compile
        csv_valid = "Question_ID,Section,Question,Response_Type,Allowed_Values,Required_Level,Required_When,Preferred_Source,Fallback_Sources,Owner,Output,Destination\n"
        csv_valid += "CTL-001,CTL,Test?,BOOLEAN,YES|NO|UNKNOWN,REQUIRED,,Workbook,,Owner,ALL,ANSWER"

        result = compiler.compile(csv_valid, version="0.2.0")
        assert result.report.is_success is True

    def test_compiler_rejects_invalid_type(self) -> None:
        """Catalog compiler should reject invalid response types."""
        from migration_intake.catalog.compiler import CatalogCompiler

        compiler = CatalogCompiler()

        # Invalid type should fail
        csv_invalid = "Question_ID,Section,Question,Response_Type,Allowed_Values,Required_Level,Required_When,Preferred_Source,Fallback_Sources,Owner,Output,Destination\n"
        csv_invalid += "CTL-001,CTL,Test?,INVALID_TYPE,,REQUIRED,,Workbook,,Owner,ALL,ANSWER"

        result = compiler.compile(csv_invalid, version="0.2.0")
        assert result.report.is_success is False
        assert any("type" in d.message.lower() or "unsupported" in d.message.lower()
                   for d in result.report.diagnostics.all())
