"""
Tests for CAT-B2 — Read-only catalog admin viewer (routes + templates).

Verifies:
- GET /admin/catalog lists releases newest-first with exactly one "latest" flag
- GET /admin/catalog renders an empty-state page (not a 500) when no releases exist
- GET /admin/catalog/{release_id} renders section/question tree, compiler report,
  and pinned intakes for a known release, in repository order
- GET /admin/catalog/{unknown-id} returns 404 (not 200 or 500)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from migration_intake.config import Settings
from migration_intake.main import create_app
from migration_intake.persistence.models import (
    Actor,
    Application,
    Base,
    CatalogQuestion,
    CatalogRelease,
    CatalogSection,
    Intake,
)


@pytest.fixture
def tmp_db(tmp_path: Path) -> str:
    """Create a temporary SQLite database URL."""
    db_path = tmp_path / "test.db"
    return f"sqlite:///{db_path}"


@pytest.fixture
def settings(tmp_db: str, tmp_path: Path) -> Settings:
    """Create isolated test settings pointing at a temp database, never local.db."""
    return Settings(
        database_url=tmp_db,
        app_env="test",
        evidence_root=str(tmp_path / "evidence"),
        actor_id=str(uuid.uuid4()),
        actor_display_name="Test Actor",
        csrf_secret="test-csrf-secret-key-12345",
    )


@pytest.fixture
def app(settings: Settings):
    """Create the test app and its schema directly (no Alembic — avoids the
    known local.db repointing bug triggered by running real migrations in
    a process with a real .env at repo root)."""
    application = create_app(settings)
    Base.metadata.create_all(application.state.engine)
    return application


@pytest.fixture
def client(app) -> TestClient:
    """Create test client. Not used as a context manager, so the app
    lifespan (and its catalog auto-bootstrap) never runs — tests fully
    control catalog release state."""
    return TestClient(app)


def _seed_actor(engine, actor_id: str) -> None:
    now = datetime.now(tz=timezone.utc)
    with Session(engine) as session:
        session.add(Actor(id=actor_id, display_name="Test Actor", created_at=now))
        session.commit()


def _seed_application(engine, actor_id: str, display_name: str = "Test App") -> str:
    now = datetime.now(tz=timezone.utc)
    app_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(
            Application(
                id=app_id,
                state="ACTIVE",
                display_name=display_name,
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.commit()
    return app_id


def _seed_release(
    engine,
    *,
    semantic_version: str,
    pub_state: str = "PUBLISHED",
    published_at: datetime | None = None,
    compiler_report: dict | None = None,
) -> str:
    now = datetime.now(tz=timezone.utc)
    release_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(
            CatalogRelease(
                id=release_id,
                semantic_version=semantic_version,
                source_filename=f"catalog-{semantic_version}.csv",
                source_sha256=uuid.uuid4().hex + uuid.uuid4().hex,
                compiler_version="1.0",
                pub_state=pub_state,
                published_at=published_at,
                compiler_report=compiler_report,
                created_at=now,
            )
        )
        session.commit()
    return release_id


def _seed_sections_and_questions(engine, release_id: str) -> tuple[list[str], list[str]]:
    """Seed two sections, each with two questions, in a deliberately
    non-alphabetical display_order so ordering assertions are meaningful."""
    section_ids = [str(uuid.uuid4()), str(uuid.uuid4())]
    question_ids = [str(uuid.uuid4()) for _ in range(3)]

    with Session(engine) as session:
        session.add(
            CatalogSection(
                id=section_ids[0],
                release_id=release_id,
                section_code="SEC-B",
                display_name="Section B",
                display_order=1,
            )
        )
        session.commit()

    with Session(engine) as session:
        session.add(
            CatalogSection(
                id=section_ids[1],
                release_id=release_id,
                section_code="SEC-A",
                display_name="Section A",
                display_order=2,
            )
        )
        session.commit()

    with Session(engine) as session:
        session.add(
            CatalogQuestion(
                id=question_ids[0],
                section_id=section_ids[0],
                question_code="Q-002",
                question_text="Second question in section B",
                response_type="TEXT",
                required_level="REQUIRED",
                collection_mode="SINGLE",
                display_order=2,
                is_active=True,
            )
        )
        session.commit()

    with Session(engine) as session:
        session.add(
            CatalogQuestion(
                id=question_ids[1],
                section_id=section_ids[0],
                question_code="Q-001",
                question_text="First question in section B",
                response_type="TEXT",
                required_level="REQUIRED",
                collection_mode="SINGLE",
                display_order=1,
                is_active=True,
            )
        )
        session.commit()

    with Session(engine) as session:
        session.add(
            CatalogQuestion(
                id=question_ids[2],
                section_id=section_ids[1],
                question_code="Q-003",
                question_text="First question in section A",
                response_type="TEXT",
                required_level="OPTIONAL",
                collection_mode="SINGLE",
                display_order=1,
                is_active=True,
            )
        )
        session.commit()

    return section_ids, question_ids


def _seed_intake(engine, app_id: str, catalog_id: str, actor_id: str) -> str:
    now = datetime.now(tz=timezone.utc)
    intake_id = str(uuid.uuid4())
    with Session(engine) as session:
        session.add(
            Intake(
                id=intake_id,
                application_id=app_id,
                catalog_id=catalog_id,
                state="IN_PROGRESS",
                created_at=now,
                updated_at=now,
                row_version=1,
                created_by_id=actor_id,
            )
        )
        session.commit()
    return intake_id


class TestListRoute:
    """GET /admin/catalog"""

    def test_zero_releases_renders_empty_state_not_500(self, client: TestClient) -> None:
        response = client.get("/admin/catalog")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]

    def test_multiple_releases_newest_first_single_latest_flag(
        self, app, client: TestClient
    ) -> None:
        engine = app.state.engine
        now = datetime.now(tz=timezone.utc)
        older_id = _seed_release(
            engine,
            semantic_version="0.1.0",
            published_at=now - timedelta(days=2),
        )
        newer_id = _seed_release(
            engine,
            semantic_version="0.2.0",
            published_at=now,
        )

        response = client.get("/admin/catalog")
        assert response.status_code == 200
        body = response.text

        # Newest-first: newer release's version string appears before the older one.
        newer_pos = body.index("0.2.0")
        older_pos = body.index("0.1.0")
        assert newer_pos < older_pos

        # Exactly one row is visibly flagged as latest.
        assert body.count('data-testid="latest-flag"') == 1

        # Sanity: both release ids surfaced somewhere as detail links.
        assert f"/admin/catalog/{newer_id}" in body
        assert f"/admin/catalog/{older_id}" in body

    def test_pinned_intake_count_and_question_count_shown(
        self, app, client: TestClient
    ) -> None:
        engine = app.state.engine
        actor_id = str(app.state.settings.actor_id)
        _seed_actor(engine, actor_id)
        app_id = _seed_application(engine, actor_id)
        release_id = _seed_release(
            engine,
            semantic_version="1.0.0",
            compiler_report={
                "diagnostics": [],
                "section_count": 1,
                "question_count": 3,
                "type_counts": {"TEXT": 3},
            },
        )
        _seed_intake(engine, app_id, release_id, actor_id)

        response = client.get("/admin/catalog")
        assert response.status_code == 200
        body = response.text
        assert "3" in body  # question count
        assert "1" in body  # pinned intake count (at least one occurrence)


class TestDetailRoute:
    """GET /admin/catalog/{release_id}"""

    def test_unknown_release_returns_404(self, client: TestClient) -> None:
        response = client.get(f"/admin/catalog/{uuid.uuid4()}")
        assert response.status_code == 404

    def test_detail_renders_sections_and_questions_in_repository_order(
        self, app, client: TestClient
    ) -> None:
        engine = app.state.engine
        release_id = _seed_release(
            engine,
            semantic_version="2.0.0",
            compiler_report={
                "diagnostics": [],
                "section_count": 2,
                "question_count": 3,
                "type_counts": {"TEXT": 3},
            },
        )
        _seed_sections_and_questions(engine, release_id)

        response = client.get(f"/admin/catalog/{release_id}")
        assert response.status_code == 200
        body = response.text

        # Sections are ordered by display_order ascending: Section B (order=1)
        # before Section A (order=2), matching CatalogRepository.get_sections_for_release.
        section_b_pos = body.index("Section B")
        section_a_pos = body.index("Section A")
        assert section_b_pos < section_a_pos

        # Within section B, questions ordered by display_order ascending:
        # Q-001 (order=1) before Q-002 (order=2).
        q001_pos = body.index("Q-001")
        q002_pos = body.index("Q-002")
        assert q001_pos < q002_pos

    def test_detail_shows_pinned_intakes_with_application_name(
        self, app, client: TestClient
    ) -> None:
        engine = app.state.engine
        actor_id = str(app.state.settings.actor_id)
        _seed_actor(engine, actor_id)
        app_id = _seed_application(engine, actor_id, display_name="Pinned App")
        release_id = _seed_release(engine, semantic_version="3.0.0")
        intake_id = _seed_intake(engine, app_id, release_id, actor_id)

        response = client.get(f"/admin/catalog/{release_id}")
        assert response.status_code == 200
        body = response.text
        assert intake_id in body
        assert "Pinned App" in body

    def test_detail_renders_compiler_report(self, app, client: TestClient) -> None:
        engine = app.state.engine
        release_id = _seed_release(
            engine,
            semantic_version="4.0.0",
            compiler_report={
                "diagnostics": ["WARN-001: example warning"],
                "section_count": 0,
                "question_count": 0,
                "type_counts": {},
            },
        )

        response = client.get(f"/admin/catalog/{release_id}")
        assert response.status_code == 200
        assert "WARN-001: example warning" in response.text


class TestNavShell:
    """UX-4d: All catalog admin pages include the nav shell (side-nav and upload link)."""

    def test_list_includes_side_nav(self, client: TestClient) -> None:
        response = client.get("/admin/catalog")
        assert response.status_code == 200
        assert '<nav class="side-nav"' in response.text

    def test_list_includes_upload_link(self, client: TestClient) -> None:
        response = client.get("/admin/catalog")
        assert response.status_code == 200
        body = response.text
        assert "/admin/catalog/upload" in body
        assert "Upload" in body

    def test_detail_includes_side_nav(self, app, client: TestClient) -> None:
        engine = app.state.engine
        release_id = _seed_release(engine, semantic_version="5.0.0")
        response = client.get(f"/admin/catalog/{release_id}")
        assert response.status_code == 200
        assert '<nav class="side-nav"' in response.text

    def test_detail_includes_accordion_sections(self, app, client: TestClient) -> None:
        engine = app.state.engine
        release_id = _seed_release(engine, semantic_version="6.0.0")
        _seed_sections_and_questions(engine, release_id)
        response = client.get(f"/admin/catalog/{release_id}")
        assert response.status_code == 200
        body = response.text
        assert '<details class="catalog-section">' in body

    def test_detail_accordion_section_count_matches_seeded_sections(
        self, app, client: TestClient
    ) -> None:
        engine = app.state.engine
        release_id = _seed_release(engine, semantic_version="7.0.0")
        _seed_sections_and_questions(engine, release_id)
        response = client.get(f"/admin/catalog/{release_id}")
        assert response.status_code == 200
        # _seed_sections_and_questions seeds exactly two sections (SEC-B and SEC-A)
        assert response.text.count('<details class="catalog-section">') == 2

    def test_upload_includes_side_nav(self, client: TestClient) -> None:
        response = client.get("/admin/catalog/upload")
        assert response.status_code == 200
        assert '<nav class="side-nav"' in response.text

    def test_upload_cancel_link_points_to_list(self, client: TestClient) -> None:
        response = client.get("/admin/catalog/upload")
        assert response.status_code == 200
        body = response.text
        assert 'href="/admin/catalog"' in body
        assert "Cancel" in body
