"""Tests for TemplateRepository persistence behavior."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from migration_intake.persistence.models import Actor
from migration_intake.persistence.repositories.templates import TemplateRepository


def _seed_actor(session_factory, actor_id: str) -> None:
    with session_factory() as session:
        session.add(
            Actor(
                id=actor_id,
                display_name="Template Admin",
                created_at=datetime.now(tz=UTC),
            )
        )
        session.commit()


def _add_release(
    session_factory,
    *,
    template_version: str = "1.7",
    source_sha256: str = "a" * 64,
    pub_state: str = "DRAFT",
    published_at: datetime | None = None,
    created_at: datetime | None = None,
    actor_id: str | None = None,
) -> dict:
    with session_factory() as session:
        repo = TemplateRepository(session)
        now = created_at or datetime.now(tz=UTC)
        row = repo.add_release(
            release_id=str(uuid.uuid4()),
            template_version=template_version,
            source_filename=f"outpost_v{template_version}.drawio",
            source_sha256=source_sha256,
            content_address=f"templates/{template_version}.drawio",
            size_bytes=12345,
            tab_count=4,
            variant_manifest=[
                {"variant": "basic", "tab_name": "Without LBs", "role_count": 45}
            ],
            compiler_version="1.0.0",
            compiler_report={"diagnostics": []},
            pub_state=pub_state,
            published_at=published_at,
            published_by_id=actor_id,
            created_at=now,
        )
        session.commit()
        return row


class TestTemplateRepository:
    def test_add_release_returns_dict_with_all_fields(self, session_factory) -> None:
        _seed_actor(session_factory, "00000000-0000-0000-0000-000000000001")
        row = _add_release(
            session_factory,
            actor_id="00000000-0000-0000-0000-000000000001",
            pub_state="PUBLISHED",
            published_at=datetime.now(tz=UTC),
        )

        assert row["template_version"] == "1.7"
        assert row["source_filename"] == "outpost_v1.7.drawio"
        assert row["pub_state"] == "PUBLISHED"
        assert row["variant_manifest"][0]["variant"] == "basic"

    def test_get_release_returns_none_for_unknown_id(self, session_factory) -> None:
        with session_factory() as session:
            repo = TemplateRepository(session)
            assert repo.get_release(str(uuid.uuid4())) is None

    def test_get_release_returns_dict_for_existing(self, session_factory) -> None:
        row = _add_release(session_factory)

        with session_factory() as session:
            repo = TemplateRepository(session)
            found = repo.get_release(row["id"])

        assert found is not None
        assert found["id"] == row["id"]

    def test_get_latest_published_returns_most_recent(self, session_factory) -> None:
        _seed_actor(session_factory, "00000000-0000-0000-0000-000000000001")
        now = datetime.now(tz=UTC)
        older = _add_release(
            session_factory,
            template_version="1.7",
            source_sha256="1" * 64,
            pub_state="PUBLISHED",
            published_at=now - timedelta(days=1),
            actor_id="00000000-0000-0000-0000-000000000001",
        )
        newer = _add_release(
            session_factory,
            template_version="1.8",
            source_sha256="2" * 64,
            pub_state="PUBLISHED",
            published_at=now,
            actor_id="00000000-0000-0000-0000-000000000001",
        )
        _add_release(session_factory, template_version="1.9", source_sha256="3" * 64)

        with session_factory() as session:
            repo = TemplateRepository(session)
            latest = repo.get_latest_published_release()

        assert latest is not None
        assert latest["id"] == newer["id"]
        assert latest["id"] != older["id"]

    def test_list_releases_returns_newest_first(self, session_factory) -> None:
        first = _add_release(
            session_factory,
            template_version="1.7",
            source_sha256="4" * 64,
            created_at=datetime.now(tz=UTC) - timedelta(days=1),
        )
        second = _add_release(
            session_factory,
            template_version="1.8",
            source_sha256="5" * 64,
            created_at=datetime.now(tz=UTC),
        )

        with session_factory() as session:
            repo = TemplateRepository(session)
            rows = repo.list_releases()

        assert [rows[0]["id"], rows[1]["id"]] == [second["id"], first["id"]]

    def test_get_release_by_version_and_hash_deduplicates(self, session_factory) -> None:
        row = _add_release(session_factory, template_version="1.8", source_sha256="6" * 64)

        with session_factory() as session:
            repo = TemplateRepository(session)
            found = repo.get_release_by_version_and_hash("1.8", "6" * 64)
            missing = repo.get_release_by_version_and_hash("1.8", "7" * 64)

        assert found is not None and found["id"] == row["id"]
        assert missing is None

    def test_get_release_by_version_returns_none_for_unknown(self, session_factory) -> None:
        _add_release(session_factory, template_version="1.7", source_sha256="8" * 64)

        with session_factory() as session:
            repo = TemplateRepository(session)
            assert repo.get_release_by_version("9.9") is None

    def test_update_pub_state_to_retired_sets_timestamp(self, session_factory) -> None:
        row = _add_release(session_factory, source_sha256="9" * 64, pub_state="PUBLISHED")

        with session_factory() as session:
            repo = TemplateRepository(session)
            updated = repo.update_pub_state(
                row["id"],
                pub_state="RETIRED",
                retired_at=datetime.now(tz=UTC),
            )
            session.commit()

        assert updated["pub_state"] == "RETIRED"
        assert updated["retired_at"] is not None

    def test_duplicate_source_sha256_raises_integrity_error(self, session_factory) -> None:
        _add_release(session_factory, source_sha256="f" * 64)
        with session_factory() as session:
            repo = TemplateRepository(session)
            with pytest.raises(Exception):
                repo.add_release(
                    release_id=str(uuid.uuid4()),
                    template_version="1.8",
                    source_filename="dup.drawio",
                    source_sha256="f" * 64,
                    content_address="templates/dup.drawio",
                    size_bytes=123,
                    tab_count=4,
                    variant_manifest=[],
                    compiler_version="1.0.0",
                    compiler_report={"diagnostics": []},
                    pub_state="DRAFT",
                    published_at=None,
                    published_by_id=None,
                    created_at=datetime.now(tz=UTC),
                )
