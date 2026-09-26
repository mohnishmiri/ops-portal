"""
Evidence storage package.

Public surface:
    EvidenceStore    – Protocol that storage backends must satisfy.
    StorageReceipt   – Immutable receipt returned by EvidenceStore.store().
    FilesystemStore  – Local-filesystem content-addressed store.
"""

from __future__ import annotations

from migration_intake.storage.filesystem import FilesystemStore
from migration_intake.storage.port import EvidenceStore, StorageReceipt

__all__ = ["EvidenceStore", "FilesystemStore", "StorageReceipt"]
