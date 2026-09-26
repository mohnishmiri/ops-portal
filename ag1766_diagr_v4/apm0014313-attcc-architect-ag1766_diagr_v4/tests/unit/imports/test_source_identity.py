from migration_intake.imports.source_identity import (
    IdentityDecision,
    compare_source_identity,
    normalize_identifier,
)


def test_normalize_identifier_is_case_and_separator_insensitive() -> None:
    assert normalize_identifier(" Corr-123 / A ") == "corr123a"


def test_matching_source_identifier_is_accepted() -> None:
    decision = compare_source_identity(
        source_id="CORR-123",
        application_identifiers=[("app-one", "CORRELATION", "corr123")],
        selected_application_id="app-one",
    )

    assert decision.outcome is IdentityDecision.MATCHED
    assert decision.normalized_source_id == "corr123"


def test_missing_source_identifier_is_quarantined() -> None:
    decision = compare_source_identity(
        source_id="",
        application_identifiers=[("app-one", "CORRELATION", "corr123")],
    )

    assert decision.outcome is IdentityDecision.MISSING


def test_mismatched_source_identifier_is_quarantined() -> None:
    decision = compare_source_identity(
        source_id="CORR-999",
        application_identifiers=[("app-one", "CORRELATION", "corr123")],
        selected_application_id="app-one",
    )

    assert decision.outcome is IdentityDecision.MISMATCH


def test_multiple_matching_identifiers_are_ambiguous() -> None:
    decision = compare_source_identity(
        source_id="CORR-123",
        application_identifiers=[
            ("app-one", "CORRELATION", "corr123"),
            ("app-two", "CORRELATION", "corr123"),
        ],
        selected_application_id="app-one",
    )

    assert decision.outcome is IdentityDecision.AMBIGUOUS
