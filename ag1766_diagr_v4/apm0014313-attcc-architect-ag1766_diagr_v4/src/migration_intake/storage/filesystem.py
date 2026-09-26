"""
FilesystemStore: content-addressed evidence storage on the local filesystem.

Key design properties:
- Storage key is derived exclusively from content SHA-256 hash.
  Format: sha256[:2]/sha256  (two-char prefix directory for scalability).
- Writes are atomic: bytes go to a temp file, then os.replace() promotes it.
  An interrupted write leaves no corrupt content at the final path.
- User-supplied filenames are used only for MIME-type inference; they never
  appear in any storage path.
- Path traversal defense: every resolved path is checked to be within the
  configured storage root before any I/O is performed.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from pathlib import Path
from typing import BinaryIO

from migration_intake.storage.port import StorageReceipt

# Valid storage key: exactly two lowercase hex chars, '/', exactly 64 lowercase hex chars.
_STORAGE_KEY_RE = re.compile(r"^[0-9a-f]{2}/[0-9a-f]{64}$")

# MIME type map keyed by lowercase file extension
_EXTENSION_MEDIA_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".csv": "text/csv",
    ".txt": "text/plain",
    ".json": "application/json",
    ".xml": "application/xml",
    ".zip": "application/zip",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

_CHUNK_SIZE = 65_536  # 64 KiB read buffer


class FilesystemStore:
    """
    Content-addressed evidence store backed by the local filesystem.

    Files are addressed by SHA-256 hash. The directory layout uses the first
    two hex characters as a prefix directory to avoid filesystem limits on
    directory entry counts (same pattern as Git object storage).

    Example path for SHA-256 "abcd1234...":
        <root>/ab/abcd1234...

    The store is idempotent: storing the same bytes twice produces the same
    storage_key and does not create duplicate files.
    """

    def __init__(self, root: Path) -> None:
        """
        Initialise the store, creating the root directory if necessary.

        Args:
            root: Absolute path to the storage root directory.
        """
        self._root: Path = root.resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def store(self, stream: BinaryIO, original_filename: str) -> StorageReceipt:
        """
        Persist the byte stream and return a StorageReceipt.

        Streams through the content, computing SHA-256 concurrently.
        Writes to a temporary file first, then atomically renames to the
        final content-addressed path. If promotion fails, the temp file is
        removed so no partial content remains.

        Args:
            stream:            Readable binary stream.
            original_filename: Uploader-supplied name (used only for MIME type).

        Returns:
            StorageReceipt with hash-derived key, digest, size, and media type.
        """
        hasher = hashlib.sha256()
        size = 0

        # Write to a temp file inside the root so os.replace() is on the
        # same filesystem (guarantees atomic rename on POSIX and Windows).
        fd, tmp_str = tempfile.mkstemp(dir=str(self._root), prefix=".tmp_")
        tmp_path = Path(tmp_str)
        promoted = False

        try:
            with os.fdopen(fd, "wb") as fobj:
                for chunk in iter(lambda: stream.read(_CHUNK_SIZE), b""):
                    hasher.update(chunk)
                    fobj.write(chunk)
                    size += len(chunk)

            sha256_hex: str = hasher.hexdigest()
            storage_key: str = self._make_storage_key(sha256_hex)
            final_path: Path = self._root / sha256_hex[:2] / sha256_hex

            final_path.parent.mkdir(parents=True, exist_ok=True)

            if final_path.exists():
                # Idempotent dedup: content already present; discard temp.
                tmp_path.unlink(missing_ok=True)
            else:
                # Atomic promote: visible only after rename completes.
                # On Windows, os.replace() can raise PermissionError when two
                # threads concurrently promote different temp files to the same
                # destination (same content → same hash → same path). Catch it
                # and verify the destination now exists (another writer won the
                # race with identical content), which is a safe outcome.
                try:
                    os.replace(tmp_str, final_path)
                except PermissionError:
                    if final_path.exists():
                        tmp_path.unlink(missing_ok=True)
                    else:
                        raise

            promoted = True

        finally:
            if not promoted:
                # Cleanup temp on any failure so no partial file lingers.
                try:
                    tmp_path.unlink(missing_ok=True)
                except OSError:
                    pass

        return StorageReceipt(
            storage_key=storage_key,
            sha256_hex=sha256_hex,
            size_bytes=size,
            media_type=_guess_media_type(original_filename),
        )

    def retrieve(self, storage_key: str) -> BinaryIO:
        """
        Return an open binary stream for the stored content.

        Args:
            storage_key: Key previously returned by store().

        Returns:
            Open binary file object. Caller is responsible for closing it.

        Raises:
            ValueError:        storage_key is syntactically invalid or resolves
                               outside the storage root.
            FileNotFoundError: No content stored under this key.
        """
        path = self._resolve_key(storage_key)
        return open(path, "rb")

    def exists(self, storage_key: str) -> bool:
        """
        Return True if content for storage_key has been stored.

        Returns False for invalid keys (no exception propagated).

        Args:
            storage_key: Key to check.
        """
        try:
            path = self._resolve_key(storage_key)
            return path.is_file()
        except ValueError:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _make_storage_key(self, sha256_hex: str) -> str:
        """Derive storage key from a SHA-256 hex digest."""
        return f"{sha256_hex[:2]}/{sha256_hex}"

    def _resolve_key(self, storage_key: str) -> Path:
        """
        Validate storage_key and return the absolute path within the root.

        Path traversal defence:
        1. Regex gate: key must match ``[0-9a-f]{2}/[0-9a-f]{64}``.
        2. Resolution gate: the resolved path must be strictly under root
           (guards against symlink escapes on systems that allow them).

        Args:
            storage_key: Key to resolve.

        Returns:
            Absolute Path under self._root.

        Raises:
            ValueError: Key is malformed or resolves outside the root.
        """
        if not _STORAGE_KEY_RE.match(storage_key):
            raise ValueError(
                f"Invalid storage key {storage_key!r}: "
                "expected format '<2-hex-chars>/<64-hex-chars>'."
            )

        candidate = (self._root / storage_key).resolve()

        try:
            candidate.relative_to(self._root)
        except ValueError as exc:
            raise ValueError(
                f"storage_key {storage_key!r} resolves outside storage root."
            ) from exc

        return candidate


# ------------------------------------------------------------------
# Module-level helper
# ------------------------------------------------------------------

def _guess_media_type(filename: str) -> str:
    """
    Return the MIME type inferred from the filename extension.

    Falls back to 'application/octet-stream' for unrecognised extensions.

    Args:
        filename: Original filename (may contain path separators; only the
                  extension is examined).
    """
    suffix = Path(filename).suffix.lower()
    return _EXTENSION_MEDIA_TYPES.get(suffix, "application/octet-stream")
