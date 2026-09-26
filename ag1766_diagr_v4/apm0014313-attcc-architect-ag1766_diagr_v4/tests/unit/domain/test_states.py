"""
Tests for domain state enumerations and transition policies.

These tests verify:
- State enumerations have expected values
- State transition policies reject invalid transitions
- Terminal states cannot transition further
"""

from __future__ import annotations

import pytest


class TestApplicationState:
    """Tests for ApplicationState enumeration."""

    def test_has_expected_states(self) -> None:
        """ApplicationState should have ACTIVE, ON_HOLD, ARCHIVED."""
        from migration_intake.domain.states import ApplicationState

        assert hasattr(ApplicationState, "ACTIVE")
        assert hasattr(ApplicationState, "ON_HOLD")
        assert hasattr(ApplicationState, "ARCHIVED")

    def test_active_can_transition_to_on_hold(self) -> None:
        """ACTIVE should be able to transition to ON_HOLD."""
        from migration_intake.domain.states import ApplicationState

        assert ApplicationState.ACTIVE.can_transition_to(ApplicationState.ON_HOLD)

    def test_active_can_transition_to_archived(self) -> None:
        """ACTIVE should be able to transition to ARCHIVED."""
        from migration_intake.domain.states import ApplicationState

        assert ApplicationState.ACTIVE.can_transition_to(ApplicationState.ARCHIVED)

    def test_on_hold_can_transition_to_active(self) -> None:
        """ON_HOLD should be able to transition back to ACTIVE."""
        from migration_intake.domain.states import ApplicationState

        assert ApplicationState.ON_HOLD.can_transition_to(ApplicationState.ACTIVE)

    def test_on_hold_can_transition_to_archived(self) -> None:
        """ON_HOLD should be able to transition to ARCHIVED."""
        from migration_intake.domain.states import ApplicationState

        assert ApplicationState.ON_HOLD.can_transition_to(ApplicationState.ARCHIVED)

    def test_archived_cannot_transition(self) -> None:
        """ARCHIVED is terminal and cannot transition."""
        from migration_intake.domain.states import ApplicationState

        assert not ApplicationState.ARCHIVED.can_transition_to(ApplicationState.ACTIVE)
        assert not ApplicationState.ARCHIVED.can_transition_to(ApplicationState.ON_HOLD)


class TestIntakeState:
    """Tests for IntakeState enumeration."""

    def test_has_expected_states(self) -> None:
        """IntakeState should have all workflow states."""
        from migration_intake.domain.states import IntakeState

        expected = [
            "DRAFT",
            "COLLECTING",
            "IN_REVIEW",
            "CHANGES_REQUESTED",
            "READY_TO_FREEZE",
            "FROZEN",
            "SUPERSEDED",
            "CANCELLED",
        ]
        for state in expected:
            assert hasattr(IntakeState, state), f"Missing state: {state}"

    def test_draft_can_transition_to_collecting(self) -> None:
        """DRAFT should transition to COLLECTING on first activity."""
        from migration_intake.domain.states import IntakeState

        assert IntakeState.DRAFT.can_transition_to(IntakeState.COLLECTING)

    def test_collecting_can_transition_to_in_review(self) -> None:
        """COLLECTING should transition to IN_REVIEW on submit."""
        from migration_intake.domain.states import IntakeState

        assert IntakeState.COLLECTING.can_transition_to(IntakeState.IN_REVIEW)

    def test_frozen_cannot_transition_backward(self) -> None:
        """FROZEN cannot transition back to earlier states."""
        from migration_intake.domain.states import IntakeState

        assert not IntakeState.FROZEN.can_transition_to(IntakeState.COLLECTING)
        assert not IntakeState.FROZEN.can_transition_to(IntakeState.DRAFT)

    def test_frozen_can_be_superseded(self) -> None:
        """FROZEN can transition to SUPERSEDED."""
        from migration_intake.domain.states import IntakeState

        assert IntakeState.FROZEN.can_transition_to(IntakeState.SUPERSEDED)


class TestAnswerApplicability:
    """Tests for AnswerApplicability enumeration."""

    def test_has_expected_values(self) -> None:
        """AnswerApplicability should have PENDING, APPLICABLE, NOT_APPLICABLE."""
        from migration_intake.domain.states import AnswerApplicability

        assert hasattr(AnswerApplicability, "PENDING")
        assert hasattr(AnswerApplicability, "APPLICABLE")
        assert hasattr(AnswerApplicability, "NOT_APPLICABLE")


class TestAnswerValueState:
    """Tests for AnswerValueState enumeration."""

    def test_has_expected_values(self) -> None:
        """AnswerValueState should have all value states."""
        from migration_intake.domain.states import AnswerValueState

        expected = [
            "UNANSWERED",
            "PROPOSED",
            "KNOWN",
            "CONFLICT",
            "INVALID",
            "NOT_APPLICABLE",
        ]
        for state in expected:
            assert hasattr(AnswerValueState, state), f"Missing state: {state}"


class TestAnswerReviewState:
    """Tests for AnswerReviewState enumeration."""

    def test_has_expected_values(self) -> None:
        """AnswerReviewState should have all review states."""
        from migration_intake.domain.states import AnswerReviewState

        expected = [
            "DRAFT",
            "ANSWERED",
            "NEEDS_EVIDENCE",
            "CHANGES_REQUESTED",
            "CONFIRMED",
        ]
        for state in expected:
            assert hasattr(AnswerReviewState, state), f"Missing state: {state}"


class TestCandidateState:
    """Tests for CandidateState enumeration."""

    def test_has_expected_values(self) -> None:
        """CandidateState should have all candidate states."""
        from migration_intake.domain.states import CandidateState

        expected = [
            "PROPOSED",
            "ACCEPTED",
            "ACCEPTED_WITH_EDIT",
            "REJECTED",
            "DEFERRED",
            "CONFLICT",
            "SUPERSEDED",
            "INVALID",
        ]
        for state in expected:
            assert hasattr(CandidateState, state), f"Missing state: {state}"

    def test_terminal_states(self) -> None:
        """Terminal candidate states should be identifiable."""
        from migration_intake.domain.states import CandidateState

        terminal = {
            CandidateState.ACCEPTED,
            CandidateState.ACCEPTED_WITH_EDIT,
            CandidateState.REJECTED,
            CandidateState.SUPERSEDED,
            CandidateState.INVALID,
        }
        for state in terminal:
            assert state.is_terminal


class TestEvidenceState:
    """Tests for EvidenceState enumeration."""

    def test_has_expected_values(self) -> None:
        """EvidenceState should have all evidence states."""
        from migration_intake.domain.states import EvidenceState

        expected = [
            "UPLOADED",
            "VALIDATING",
            "VALID",
            "INVALID",
            "QUARANTINED",
            "SUPERSEDED",
        ]
        for state in expected:
            assert hasattr(EvidenceState, state), f"Missing state: {state}"


class TestActorType:
    """Tests for ActorType enumeration."""

    def test_has_expected_values(self) -> None:
        """ActorType should have CONFIGURED, OIDC_USER, SYSTEM."""
        from migration_intake.domain.states import ActorType

        assert hasattr(ActorType, "CONFIGURED")
        assert hasattr(ActorType, "OIDC_USER")
        assert hasattr(ActorType, "SYSTEM")
