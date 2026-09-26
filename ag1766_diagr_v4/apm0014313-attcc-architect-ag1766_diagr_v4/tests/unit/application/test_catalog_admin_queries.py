"""
Tests for CAT-B1 — CatalogAdminQueryService.

Verifies:
- list_releases() returns every release, newest-first, with exactly one
  is_latest True even when multiple PUBLISHED releases exist.
- pinned_intake_count matches the actual intake count for that catalog_id,
  including the zero case.
- get_release_detail() section/question ordering matches what the existing
  questionnaire read path (get_questionnaire_page) renders for an intake
  pinned to the same release — using the shared fixture helpers from
  test_questionnaire_read_model.py so both paths are proven against one
  release, not two independently-authored fixtures.
- An unknown release_id returns None without raising.
"""

from __future__ import annotations

import hashlib
import uuid

from migration_intake.application.commands import (
    CreateApplicationCommand,
    CreateIntakeCommand,
)
from migration_intake.application.dto import ActorContext
from migration_intake.application.queries import ApplicationQueryService
from migration_intake.application.services.applications import ApplicationService
from migration_intake.application.services.catalog_admin_queries import (
    CatalogAdminQueryService,
)
from migration_intake.application.services.catalogs import CatalogPublicationService

# Reuse the exact same seeding helpers the questionnaire read-model tests use,
# so the shared-fixture release proves the admin detail view can never drift
# from what questionnaire itself renders (CAT-B1 acceptance criterion 3).
from tests.unit.application.test_questionnaire_read_model import (
    _seed_actor,
    _seed_application,
    _seed_catalog_with_sections,
    _seed_intake,
)


class TestListReleases:
    """Tests for CatalogAdminQueryService.list_releases()."""

    def test_returns_every_release_newest_first(self, session_factory) -> None:
        catalog_service = CatalogPublicationService(session_factory)
        v1 = catalog_service.publish_release(
            semantic_version="1.0.0",
            source_filename="catalog_v1.yaml",
            source_sha256=hashlib.sha256(b"admin-list-v1").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )
        v2 = catalog_service.publish_release(
            semantic_version="2.0.0",
            source_filename="catalog_v2.yaml",
            source_sha256=hashlib.sha256(b"admin-list-v2").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )

        service = CatalogAdminQueryService(session_factory)
        releases = service.list_releases()

        assert [r["id"] for r in releases] == [v2["id"], v1["id"]]

    def test_exactly_one_is_latest_when_multiple_published_exist(
        self, session_factory
    ) -> None:
        """Publishing two PUBLISHED releases still yields exactly one is_latest=True."""
        catalog_service = CatalogPublicationService(session_factory)
        v1 = catalog_service.publish_release(
            semantic_version="1.0.0",
            source_filename="catalog_v1.yaml",
            source_sha256=hashlib.sha256(b"admin-latest-v1").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )
        v2 = catalog_service.publish_release(
            semantic_version="2.0.0",
            source_filename="catalog_v2.yaml",
            source_sha256=hashlib.sha256(b"admin-latest-v2").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )

        service = CatalogAdminQueryService(session_factory)
        releases = service.list_releases()

        latest_flags = {r["id"]: r["is_latest"] for r in releases}
        assert sum(latest_flags.values()) == 1
        # The existing get_latest_published_release() is the source of truth,
        # and it orders by published_at desc — v2 was published after v1.
        assert latest_flags[v2["id"]] is True
        assert latest_flags[v1["id"]] is False


class TestPinnedIntakeCount:
    """Tests for pinned_intake_count decoration in list_releases()."""

    def _create_intake(self, session_factory, catalog_id: str) -> str:
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

    def test_zero_when_no_intakes_pinned(self, session_factory) -> None:
        catalog_service = CatalogPublicationService(session_factory)
        release = catalog_service.publish_release(
            semantic_version="1.0.0",
            source_filename="catalog.yaml",
            source_sha256=hashlib.sha256(b"pin-count-zero").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )

        service = CatalogAdminQueryService(session_factory)
        releases = service.list_releases()

        listed = next(r for r in releases if r["id"] == release["id"])
        assert listed["pinned_intake_count"] == 0

    def test_matches_exact_count_of_pinned_intakes(self, session_factory) -> None:
        catalog_service = CatalogPublicationService(session_factory)
        release = catalog_service.publish_release(
            semantic_version="1.0.0",
            source_filename="catalog.yaml",
            source_sha256=hashlib.sha256(b"pin-count-exact").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )
        other_release = catalog_service.publish_release(
            semantic_version="2.0.0",
            source_filename="catalog_other.yaml",
            source_sha256=hashlib.sha256(b"pin-count-other").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
        )

        self._create_intake(session_factory, release["id"])
        self._create_intake(session_factory, release["id"])
        self._create_intake(session_factory, other_release["id"])

        service = CatalogAdminQueryService(session_factory)
        releases = service.list_releases()

        counts = {r["id"]: r["pinned_intake_count"] for r in releases}
        assert counts[release["id"]] == 2
        assert counts[other_release["id"]] == 1


class TestGetReleaseDetail:
    """Tests for CatalogAdminQueryService.get_release_detail()."""

    def test_unknown_release_id_returns_none(self, session_factory) -> None:
        service = CatalogAdminQueryService(session_factory)
        assert service.get_release_detail(str(uuid.uuid4())) is None

    def test_malformed_release_id_returns_none_not_raise(self, session_factory) -> None:
        """
        ``cat_releases.id`` is a ``PortableUUID`` column that validates its
        bind parameter, so a syntactically-invalid id must be treated the
        same as "not found" rather than surfacing as an unhandled error.
        """
        service = CatalogAdminQueryService(session_factory)
        assert service.get_release_detail("does-not-exist") is None

    def test_section_and_question_order_matches_questionnaire_read_path(
        self, tmp_engine, session_factory
    ) -> None:
        """
        Uses the SAME fixture release/intake as the questionnaire read-model
        tests (via the shared seeding helpers) to prove get_release_detail()
        cannot drift from what get_questionnaire_page() renders.
        """
        actor_id = str(uuid.uuid4())
        _seed_actor(tmp_engine, actor_id)
        cat_id, section_ids, question_ids = _seed_catalog_with_sections(tmp_engine)
        app_id = _seed_application(tmp_engine, actor_id)
        intake_id = _seed_intake(tmp_engine, app_id, cat_id, actor_id)

        admin_service = CatalogAdminQueryService(session_factory)
        detail = admin_service.get_release_detail(cat_id)
        assert detail is not None

        questionnaire_service = ApplicationQueryService(session_factory)

        # Compare section order and, within each section, question order,
        # against the same underlying repository traversal the
        # questionnaire page itself uses.
        assert [s["section_code"] for s in detail["sections"]] == [
            "SEC-001",
            "SEC-002",
            "SEC-003",
        ]

        for section in detail["sections"]:
            page = questionnaire_service.get_questionnaire_page(
                intake_id, section["section_code"]
            )
            assert page is not None
            assert [q["question_code"] for q in section["questions"]] == [
                q["code"] for q in page["questions"]
            ]

    def test_includes_pinned_intake_count_and_compiler_report(
        self, session_factory
    ) -> None:
        catalog_service = CatalogPublicationService(session_factory)
        release = catalog_service.publish_release(
            semantic_version="1.0.0",
            source_filename="catalog.yaml",
            source_sha256=hashlib.sha256(b"detail-report").hexdigest(),
            compiler_version="1.0.0",
            sections=[],
            compiler_report={"warnings": [], "question_count": 0},
        )

        admin_service = CatalogAdminQueryService(session_factory)
        detail = admin_service.get_release_detail(release["id"])

        assert detail is not None
        assert detail["pinned_intake_count"] == 0
        assert detail["compiler_report"] == {"warnings": [], "question_count": 0}
        assert detail["sections"] == []
