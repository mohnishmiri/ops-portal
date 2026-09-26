"""
Storage port: protocol and receipt type for evidence persistence.

The EvidenceStore protocol defines the boundary between application logic
and storage backends. Storage keys are always hash-derived; user-supplied
filenames must never influence storage paths.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import BinaryIO, Protocol


@dataclass(frozen=True, slots=True)
class StorageReceipt:
    """
    Immutable receipt returned after successfully storing evidence.

    Attributes:
        storage_key: Hash-derived path used to retrieve the content later.
                     Format: sha256[:2]/sha256  (e.g. "ab/abcd...64chars").
                     Never contains any user-supplied filename.
        sha256_hex:  Lowercase 64-character hex SHA-256 digest of the content.
        size_bytes:  Exact byte count of the stored content.
        media_type:  MIME type inferred from the original filename extension.
    """

    storage_key: str
    sha256_hex: str
    size_bytes: int
    media_type: str


class EvidenceStore(Protocol):
    """
    Protocol for content-addressed evidence storage backends.

    Implementations must be idempotent for identical content (same bytes →
    same storage_key) and must never use user-supplied filenames in paths.
    """

    def store(self, stream: BinaryIO, original_filename: str) -> StorageReceipt:
        """
        Persist the byte stream and return a receipt.

        Args:
            stream:            Readable binary stream of the evidence file.
            original_filename: Original name supplied by the uploader.
                               Used only for MIME-type inference; never for paths.

        Returns:
            StorageReceipt with hash-derived key, digest, size, and media type.
        """
        ...

    def retrieve(self, storage_key: str) -> BinaryIO:
        """
        Return an open binary stream for the given storage_key.

        Args:
            storage_key: Key previously returned in a StorageReceipt.

        Raises:
            ValueError:       If storage_key is syntactically invalid or resolves
                              outside the storage root.
            FileNotFoundError: If no content exists for this key.
        """
        ...

    def exists(self, storage_key: str) -> bool:
        """
        Return True if content for storage_key has been stored.

        Args:
            storage_key: Key to check.

        Returns:
            True if content exists, False otherwise (including invalid keys).
        """
        ...
