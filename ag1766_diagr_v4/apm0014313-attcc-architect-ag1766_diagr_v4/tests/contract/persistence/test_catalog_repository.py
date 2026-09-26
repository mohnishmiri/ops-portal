"""
Contract tests for CAT-B1 catalog admin read-model additions.

Covers:
- ``CatalogRepository.list_releases()`` — all releases, any pub_state,
  newest-first by ``published_at`` with never-published releases sorted
  last.
- ``IntakeRepository.count_by_catalog_id()`` — exact intake count pinned to
  a given catalog release, including the zero case.

Follows the fixture style of ``test_catalog_publication.py``: the shared
``session_factory`` fixture from ``conftest.py``, publication via
``CatalogPublicationService``, and direct ``uow.catalogs.add_release`` calls
when a genuinely unpublished (``DRAFT``) release is needed.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone

from migration_intake.application.commands import (
    CreateApplicationCommand,
    CreateIntakeCommand,
)
from migration_intake.application.dto import ActorContext
from migration_intake.application.services.applications import ApplicationService
from migration_intake.application.services.catalogs import CatalogPublicationService
from migration_intake.persistence.unit_of_work import uow_context


class TestListReleases:
    """Tests for CatalogRepository.list_releases()."""

    def test_returns_all_releases_regardless_of_pub_state(
        self, session_factory
    ) -> None:
        """A DRAFT (never-published) release is included alongside PUBLISHED ones."""
        catalog_service = CatalogPublicationService(session_factory)
        catalog_service.publish_release(
            semantic_version="1.0.0",
            source_filename="catalog_v1.yaml",
            source_sha256=hashlib.sha256(b"list-releases-published").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )

        # A DRAFT release that is never published (published_at stays None).
        with uow_context(session_factory) as uow:
            uow.catalogs.add_release(
                release_id=str(uuid.uuid4()),
                semantic_version="2.0.0-draft",
                source_filename="catalog_v2_draft.yaml",
                source_sha256=hashlib.sha256(b"list-releases-draft").hexdigest(),
                compiler_version="1.0.0",
                pub_state="DRAFT",
                created_at=datetime.now(tz=timezone.utc),
            )
            uow.commit()

        with uow_context(session_factory) as uow:
            releases = uow.catalogs.list_releases()

        pub_states = {r["pub_state"] for r in releases}
        assert len(releases) == 2
        assert pub_states == {"PUBLISHED", "DRAFT"}

    def test_orders_newest_first_by_published_at(self, session_factory) -> None:
        """Multiple PUBLISHED releases sort with the most recently published first."""
        catalog_service = CatalogPublicationService(session_factory)

        v1 = catalog_service.publish_release(
            semantic_version="1.0.0",
            source_filename="catalog_v1.yaml",
            source_sha256=hashlib.sha256(b"order-v1").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )
        v2 = catalog_service.publish_release(
            semantic_version="2.0.0",
            source_filename="catalog_v2.yaml",
            source_sha256=hashlib.sha256(b"order-v2").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )

        with uow_context(session_factory) as uow:
            releases = uow.catalogs.list_releases()

        assert [r["id"] for r in releases] == [v2["id"], v1["id"]]

    def test_never_published_release_sorts_after_published_releases(
        self, session_factory
    ) -> None:
        """A release with published_at=None never outranks a published one."""
        catalog_service = CatalogPublicationService(session_factory)
        published = catalog_service.publish_release(
            semantic_version="1.0.0",
            source_filename="catalog_v1.yaml",
            source_sha256=hashlib.sha256(b"draft-vs-published").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )

        draft_id = str(uuid.uuid4())
        with uow_context(session_factory) as uow:
            uow.catalogs.add_release(
                release_id=draft_id,
                semantic_version="9.0.0-draft",
                source_filename="catalog_draft.yaml",
                source_sha256=hashlib.sha256(b"draft-only").hexdigest(),
                compiler_version="1.0.0",
                pub_state="DRAFT",
                created_at=datetime.now(tz=timezone.utc),
            )
            uow.commit()

        with uow_context(session_factory) as uow:
            releases = uow.catalogs.list_releases()

        ids_in_order = [r["id"] for r in releases]
        assert ids_in_order[0] == published["id"]
        assert ids_in_order[-1] == draft_id
        draft_row = next(r for r in releases if r["id"] == draft_id)
        assert draft_row["published_at"] is None

    def test_release_shape_matches_release_to_dict_fields(
        self, session_factory
    ) -> None:
        """list_releases() reuses _release_to_dict, so fields match get_release()."""
        catalog_service = CatalogPublicationService(session_factory)
        result = catalog_service.publish_release(
            semantic_version="1.0.0",
            source_filename="catalog_v1.yaml",
            source_sha256=hashlib.sha256(b"shape-check").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )

        with uow_context(session_factory) as uow:
            releases = uow.catalogs.list_releases()
            single = uow.catalogs.get_release(result["id"])

        listed = next(r for r in releases if r["id"] == result["id"])
        assert listed.keys() == single.keys()


class TestCountByCatalogId:
    """Tests for IntakeRepository.count_by_catalog_id()."""

    def _create_application_and_intake(
        self, session_factory, catalog_id: str
    ) -> str:
        app_service = ApplicationService(session_factory)
        actor = ActorContext(actor_id=str(uuid.uuid4()))
        app_result = app_service.create_application(
            CreateApplicationCommand(
                display_name=f"App {uuid.uuid4()}",
                identifiers=(),
                actor=actor,
            )
        )
        intake_result = app_service.create_intake(
            CreateIntakeCommand(
                application_id=app_result["id"],
                catalog_release_id=catalog_id,
                actor=actor,
            )
        )
        return intake_result["id"]

    def test_count_is_zero_when_no_intakes_pinned(self, session_factory) -> None:
        """A brand-new release with no intakes pinned counts exactly zero."""
        catalog_service = CatalogPublicationService(session_factory)
        release = catalog_service.publish_release(
            semantic_version="1.0.0",
            source_filename="catalog_v1.yaml",
            source_sha256=hashlib.sha256(b"count-zero").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )

        with uow_context(session_factory) as uow:
            count = uow.intakes.count_by_catalog_id(release["id"])

        assert count == 0

    def test_count_matches_exact_number_of_pinned_intakes(
        self, session_factory
    ) -> None:
        """Count reflects exactly the intakes whose catalog_id matches, no more."""
        catalog_service = CatalogPublicationService(session_factory)
        release_a = catalog_service.publish_release(
            semantic_version="1.0.0",
            source_filename="catalog_a.yaml",
            source_sha256=hashlib.sha256(b"count-a").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )
        release_b = catalog_service.publish_release(
            semantic_version="2.0.0",
            source_filename="catalog_b.yaml",
            source_sha256=hashlib.sha256(b"count-b").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )

        # Two intakes pinned to release_a, one pinned to release_b.
        self._create_application_and_intake(session_factory, release_a["id"])
        self._create_application_and_intake(session_factory, release_a["id"])
        self._create_application_and_intake(session_factory, release_b["id"])

        with uow_context(session_factory) as uow:
            count_a = uow.intakes.count_by_catalog_id(release_a["id"])
            count_b = uow.intakes.count_by_catalog_id(release_b["id"])

        assert count_a == 2
        assert count_b == 1
