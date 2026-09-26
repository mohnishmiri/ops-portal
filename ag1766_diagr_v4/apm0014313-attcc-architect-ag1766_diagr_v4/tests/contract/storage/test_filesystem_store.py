"""
Contract tests for FilesystemStore.

Verify that FilesystemStore satisfies the EvidenceStore protocol
and all behavioral contracts defined in the storage port.
"""

from __future__ import annotations

import hashlib
import io
import os
from pathlib import Path

import pytest

from migration_intake.storage.filesystem import FilesystemStore


def test_store_bytes_returns_sha256_key(tmp_path: Path) -> None:
    """store() receipt.storage_key contains sha256_hex."""
    store = FilesystemStore(root=tmp_path)
    content = b"hello world"
    sha256_hex = hashlib.sha256(content).hexdigest()

    receipt = store.store(io.BytesIO(content), original_filename="test.txt")

    assert receipt.sha256_hex == sha256_hex
    assert sha256_hex in receipt.storage_key


def test_store_same_bytes_twice_returns_same_key(tmp_path: Path) -> None:
    """Storing the same bytes twice returns the same storage_key (deduplication)."""
    store = FilesystemStore(root=tmp_path)
    content = b"deduplicated content"

    receipt1 = store.store(io.BytesIO(content), original_filename="file1.txt")
    receipt2 = store.store(io.BytesIO(content), original_filename="file2.txt")

    assert receipt1.storage_key == receipt2.storage_key


def test_sha256_hex_is_lowercase_64_chars(tmp_path: Path) -> None:
    """receipt.sha256_hex is lowercase 64-character hexadecimal."""
    store = FilesystemStore(root=tmp_path)
    content = b"test content for hash check"

    receipt = store.store(io.BytesIO(content), original_filename="data.bin")

    assert len(receipt.sha256_hex) == 64
    assert receipt.sha256_hex == receipt.sha256_hex.lower()
    assert all(c in "0123456789abcdef" for c in receipt.sha256_hex)


def test_original_filename_not_in_storage_path(tmp_path: Path) -> None:
    """User-supplied filename never appears anywhere in the storage key or path."""
    store = FilesystemStore(root=tmp_path)
    content = b"sensitive data"
    original_filename = "../../etc/passwd"

    receipt = store.store(io.BytesIO(content), original_filename=original_filename)

    assert "passwd" not in receipt.storage_key
    assert "etc" not in receipt.storage_key
    assert ".." not in receipt.storage_key


def test_retrieve_stored_bytes(tmp_path: Path) -> None:
    """store then retrieve returns the identical bytes."""
    store = FilesystemStore(root=tmp_path)
    content = b"retrieve me please"

    receipt = store.store(io.BytesIO(content), original_filename="file.txt")
    with store.retrieve(receipt.storage_key) as retrieved:
        assert retrieved.read() == content


def test_exists_true_after_store(tmp_path: Path) -> None:
    """exists() returns True after content has been stored."""
    store = FilesystemStore(root=tmp_path)
    content = b"existence check"

    receipt = store.store(io.BytesIO(content), original_filename="file.txt")

    assert store.exists(receipt.storage_key) is True


def test_exists_false_before_store(tmp_path: Path) -> None:
    """exists() returns False for an unknown (never-stored) storage key."""
    store = FilesystemStore(root=tmp_path)
    # Construct a syntactically valid key that has never been stored
    fake_sha = "a" * 64
    fake_key = f"{fake_sha[:2]}/{fake_sha}"

    assert store.exists(fake_key) is False


def test_interrupted_write_leaves_no_corrupt_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    A simulated failure during the atomic promote step leaves no corrupt content.

    The implementation writes to a temp file and uses os.replace() for the
    final promotion. If os.replace() raises, the final path must not exist.
    """
    store = FilesystemStore(root=tmp_path)
    content = b"important data"
    expected_sha256 = hashlib.sha256(content).hexdigest()
    final_path = tmp_path / expected_sha256[:2] / expected_sha256

    # Intercept os.replace: fail on the first call, succeed thereafter
    original_replace = os.replace
    calls: list[int] = []

    def fail_first_then_succeed(src: str, dst: object) -> None:
        if not calls:
            calls.append(1)
            raise OSError("Simulated atomic promote failure")
        original_replace(src, dst)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "replace", fail_first_then_succeed)

    with pytest.raises(OSError):
        store.store(io.BytesIO(content), original_filename="data.bin")

    # The final path must NOT exist; no partial/corrupt content was promoted
    assert not final_path.exists()

    # A second store (with os.replace working) must succeed and produce intact data
    receipt = store.store(io.BytesIO(content), original_filename="data.bin")
    assert final_path.exists()
    assert final_path.read_bytes() == content
    assert receipt.sha256_hex == expected_sha256


def test_size_bytes_matches_content(tmp_path: Path) -> None:
    """receipt.size_bytes equals len(content)."""
    store = FilesystemStore(root=tmp_path)
    content = b"exactly this many bytes"

    receipt = store.store(io.BytesIO(content), original_filename="file.txt")

    assert receipt.size_bytes == len(content)
