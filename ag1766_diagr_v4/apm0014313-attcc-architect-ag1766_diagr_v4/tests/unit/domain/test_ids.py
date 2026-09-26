"""
Tests for domain ID types.

These tests verify:
- UUID-backed IDs parse valid UUIDs and reject malformed ones
- IDs are immutable and hashable
- Different ID types are not equal even with same UUID value
- IDs have proper string representation
"""

from __future__ import annotations

import uuid

import pytest


class TestApplicationId:
    """Tests for ApplicationId."""

    def test_create_from_valid_uuid_string(self) -> None:
        """ApplicationId should accept valid UUID string."""
        from migration_intake.domain.ids import ApplicationId

        uuid_str = "550e8400-e29b-41d4-a716-446655440000"
        app_id = ApplicationId(uuid_str)

        assert str(app_id) == uuid_str

    def test_create_from_uuid_object(self) -> None:
        """ApplicationId should accept UUID object."""
        from migration_intake.domain.ids import ApplicationId

        uuid_obj = uuid.UUID("550e8400-e29b-41d4-a716-446655440000")
        app_id = ApplicationId(uuid_obj)

        assert app_id.value == uuid_obj

    def test_reject_malformed_uuid(self) -> None:
        """ApplicationId should reject malformed UUID strings."""
        from migration_intake.domain.ids import ApplicationId

        with pytest.raises(ValueError, match="[Ii]nvalid"):
            ApplicationId("not-a-uuid")

    def test_reject_empty_string(self) -> None:
        """ApplicationId should reject empty string."""
        from migration_intake.domain.ids import ApplicationId

        with pytest.raises(ValueError):
            ApplicationId("")

    def test_reject_none(self) -> None:
        """ApplicationId should reject None."""
        from migration_intake.domain.ids import ApplicationId

        with pytest.raises((ValueError, TypeError)):
            ApplicationId(None)  # type: ignore[arg-type]

    def test_ids_are_immutable(self) -> None:
        """ApplicationId should be immutable."""
        from migration_intake.domain.ids import ApplicationId

        app_id = ApplicationId("550e8400-e29b-41d4-a716-446655440000")

        with pytest.raises((AttributeError, TypeError)):
            app_id.value = uuid.uuid4()  # type: ignore[misc]

    def test_ids_are_hashable(self) -> None:
        """ApplicationId should be hashable for use in sets/dicts."""
        from migration_intake.domain.ids import ApplicationId

        app_id = ApplicationId("550e8400-e29b-41d4-a716-446655440000")

        # Should not raise
        hash(app_id)
        {app_id: "test"}
        {app_id}

    def test_equal_ids_have_same_hash(self) -> None:
        """Equal ApplicationIds should have the same hash."""
        from migration_intake.domain.ids import ApplicationId

        id1 = ApplicationId("550e8400-e29b-41d4-a716-446655440000")
        id2 = ApplicationId("550e8400-e29b-41d4-a716-446655440000")

        assert id1 == id2
        assert hash(id1) == hash(id2)

    def test_generate_new_id(self) -> None:
        """ApplicationId.generate() should create a new unique ID."""
        from migration_intake.domain.ids import ApplicationId

        id1 = ApplicationId.generate()
        id2 = ApplicationId.generate()

        assert id1 != id2
        assert isinstance(id1.value, uuid.UUID)


class TestIntakeId:
    """Tests for IntakeId."""

    def test_create_from_valid_uuid(self) -> None:
        """IntakeId should accept valid UUID."""
        from migration_intake.domain.ids import IntakeId

        intake_id = IntakeId("550e8400-e29b-41d4-a716-446655440000")

        assert intake_id.value == uuid.UUID("550e8400-e29b-41d4-a716-446655440000")

    def test_reject_malformed_uuid(self) -> None:
        """IntakeId should reject malformed UUID."""
        from migration_intake.domain.ids import IntakeId

        with pytest.raises(ValueError):
            IntakeId("invalid")


class TestCatalogReleaseId:
    """Tests for CatalogReleaseId."""

    def test_create_from_valid_uuid(self) -> None:
        """CatalogReleaseId should accept valid UUID."""
        from migration_intake.domain.ids import CatalogReleaseId

        catalog_id = CatalogReleaseId("550e8400-e29b-41d4-a716-446655440000")

        assert catalog_id.value == uuid.UUID("550e8400-e29b-41d4-a716-446655440000")


class TestActorId:
    """Tests for ActorId."""

    def test_create_from_valid_uuid(self) -> None:
        """ActorId should accept valid UUID."""
        from migration_intake.domain.ids import ActorId

        actor_id = ActorId("550e8400-e29b-41d4-a716-446655440000")

        assert actor_id.value == uuid.UUID("550e8400-e29b-41d4-a716-446655440000")


class TestIdTypeDistinction:
    """Tests that different ID types are distinct."""

    def test_different_id_types_not_equal(self) -> None:
        """Different ID types should not be equal even with same UUID."""
        from migration_intake.domain.ids import ActorId, ApplicationId, IntakeId

        uuid_str = "550e8400-e29b-41d4-a716-446655440000"

        app_id = ApplicationId(uuid_str)
        intake_id = IntakeId(uuid_str)
        actor_id = ActorId(uuid_str)

        assert app_id != intake_id
        assert app_id != actor_id
        assert intake_id != actor_id

    def test_same_type_same_uuid_are_equal(self) -> None:
        """Same ID type with same UUID should be equal."""
        from migration_intake.domain.ids import ApplicationId

        uuid_str = "550e8400-e29b-41d4-a716-446655440000"

        id1 = ApplicationId(uuid_str)
        id2 = ApplicationId(uuid_str)

        assert id1 == id2


class TestExternalIdentifier:
    """Tests for ExternalIdentifier (typed external IDs like iTAP, MOTS)."""

    def test_create_with_type_and_value(self) -> None:
        """ExternalIdentifier should store type and value."""
        from migration_intake.domain.ids import ExternalIdentifier, ExternalIdType

        ext_id = ExternalIdentifier(ExternalIdType.ITAP, "APP-12345")

        assert ext_id.id_type == ExternalIdType.ITAP
        assert ext_id.value == "APP-12345"

    def test_normalize_value(self) -> None:
        """ExternalIdentifier should normalize whitespace."""
        from migration_intake.domain.ids import ExternalIdentifier, ExternalIdType

        ext_id = ExternalIdentifier(ExternalIdType.ITAP, "  APP-12345  ")

        assert ext_id.value == "APP-12345"

    def test_reject_empty_value(self) -> None:
        """ExternalIdentifier should reject empty value."""
        from migration_intake.domain.ids import ExternalIdentifier, ExternalIdType

        with pytest.raises(ValueError, match="[Ee]mpty"):
            ExternalIdentifier(ExternalIdType.ITAP, "")

    def test_reject_whitespace_only(self) -> None:
        """ExternalIdentifier should reject whitespace-only value."""
        from migration_intake.domain.ids import ExternalIdentifier, ExternalIdType

        with pytest.raises(ValueError, match="[Ee]mpty"):
            ExternalIdentifier(ExternalIdType.ITAP, "   ")
