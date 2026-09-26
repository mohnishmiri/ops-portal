"""Tests for DB-first template resolution."""

from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import sessionmaker

from migration_intake.persistence.database import create_engine_from_url
from migration_intake.persistence.models import Actor, Base
from migration_intake.persistence.repositories.templates import TemplateRepository
from migration_intake.storage.filesystem import FilesystemStore


def _build_session_factory(tmp_path: Path):
    engine = create_engine_from_url(
        f"sqlite:///{tmp_path / 'template-resolution.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


def _seed_published_release(session_factory, storage: FilesystemStore, content: bytes) -> dict:
    actor_id = "00000000-0000-0000-0000-000000000001"
    with session_factory() as session:
        session.add(Actor(id=actor_id, display_name="Template Admin", created_at=datetime.now(tz=UTC)))
        session.commit()
        receipt = storage.store(io.BytesIO(content), "outpost_v1.8.drawio")
        repo = TemplateRepository(session)
        row = repo.add_release(
            release_id=str(uuid.uuid4()),
            template_version="1.8",
            source_filename="outpost_v1.8.drawio",
            source_sha256=receipt.sha256_hex,
            content_address=receipt.storage_key,
            size_bytes=receipt.size_bytes,
            tab_count=4,
            variant_manifest=[],
            compiler_version="1.0.0",
            compiler_report={"diagnostics": []},
            pub_state="PUBLISHED",
            published_at=datetime.now(tz=UTC),
            published_by_id=actor_id,
            created_at=datetime.now(tz=UTC),
        )
        session.commit()
        return row


def test_resolve_template_returns_db_published_when_available(tmp_path) -> None:
    from migration_intake.topology.template_loader import resolve_template

    session_factory = _build_session_factory(tmp_path)
    storage = FilesystemStore(tmp_path / "evidence" / "topology" / "templates")
    db_template = (
        b'<mxfile><diagram name="Without LBs"><mxGraphModel><root><mxCell id="db"/></root>'
        b"</mxGraphModel></diagram></mxfile>"
    )
    release = _seed_published_release(session_factory, storage, db_template)

    data, source = resolve_template("basic", session_factory=session_factory, storage=storage)

    assert source == release["id"]
    assert b'id="db"' in data


def test_resolve_template_falls_back_to_bundled_when_no_published(tmp_path) -> None:
    from migration_intake.topology.template_loader import resolve_template

    session_factory = _build_session_factory(tmp_path)
    storage = FilesystemStore(tmp_path / "evidence" / "topology" / "templates")
    data, source = resolve_template("basic", session_factory=session_factory, storage=storage)

    assert source == "bundled_fallback"
    assert b"Without LBs" in data
