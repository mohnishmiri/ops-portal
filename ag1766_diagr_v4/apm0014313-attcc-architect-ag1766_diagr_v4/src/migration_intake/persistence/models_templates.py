"""Template release persistence model for topology template admin."""

from __future__ import annotations

from typing import Any

from sqlalchemy import Column, ForeignKeyConstraint, Integer, String, UniqueConstraint

from migration_intake.persistence.naming import Base
from migration_intake.persistence.types import CanonicalJSON, PortableUTC, PortableUUID, Sha256Hex

__all__ = ["TemplateRelease"]


class TemplateRelease(Base):
    """Immutable published topology template release metadata."""

    __tablename__ = "tpl_releases"
    __table_args__ = (
        UniqueConstraint("source_sha256", name="uq_trel_sha"),
        ForeignKeyConstraint(["published_by_id"], ["actors.id"], name="fk_trel_actor"),
    )

    id: Any = Column(PortableUUID(), primary_key=True)
    template_version: Any = Column(String(32), nullable=False)
    source_filename: Any = Column(String(255), nullable=False)
    source_sha256: Any = Column(Sha256Hex(), nullable=False)
    content_address: Any = Column(String(255), nullable=False)
    size_bytes: Any = Column(Integer, nullable=False)
    tab_count: Any = Column(Integer, nullable=False)
    variant_manifest: Any = Column(CanonicalJSON(), nullable=False)
    compiler_version: Any = Column(String(32), nullable=False)
    compiler_report: Any = Column(CanonicalJSON(), nullable=True)
    pub_state: Any = Column(String(32), nullable=False)
    published_at: Any = Column(PortableUTC(), nullable=True)
    published_by_id: Any = Column(PortableUUID(), nullable=True)
    retired_at: Any = Column(PortableUTC(), nullable=True)
    created_at: Any = Column(PortableUTC(), nullable=False)
