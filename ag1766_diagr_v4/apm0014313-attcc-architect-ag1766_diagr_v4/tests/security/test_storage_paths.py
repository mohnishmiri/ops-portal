"""
Security tests for storage path handling.

Verify that FilesystemStore resists path traversal and related attacks.
All storage paths must be derived exclusively from content hashes;
user-supplied filenames must never influence the storage path.
"""

from __future__ import annotations

import hashlib
import io
from pathlib import Path

import pytest

from migration_intake.storage.filesystem import FilesystemStore


def test_path_traversal_rejected(tmp_path: Path) -> None:
    """storage_key containing '../' or an absolute path raises ValueError."""
    store = FilesystemStore(root=tmp_path)

    with pytest.raises(ValueError):
        store.retrieve("../../../etc/passwd")

    with pytest.raises(ValueError):
        store.retrieve("/etc/passwd")


def test_symlink_escape_rejected(tmp_path: Path) -> None:
    """
    If a storage key resolves to a path outside the root (e.g. via symlink),
    retrieve() raises ValueError.
    """
    store = FilesystemStore(root=tmp_path)

    escape_target = tmp_path.parent / "outside_storage_root"
    escape_target.mkdir(exist_ok=True)

    link_dir = tmp_path / "ab"
    link_dir.mkdir(exist_ok=True)
    link_name = "a" * 64
    link_path = link_dir / link_name

    try:
        link_path.symlink_to(escape_target)
    except OSError:
        pytest.skip("Symlinks not supported or not permitted on this platform")

    key = f"ab/{link_name}"
    with pytest.raises((ValueError, OSError)):
        store.retrieve(key)


def test_user_filename_with_traversal_not_used_as_path(tmp_path: Path) -> None:
    """
    original_filename='../../../etc/passwd' stores safely using only the
    content hash; the user-supplied name never touches the filesystem path.
    """
    store = FilesystemStore(root=tmp_path)
    content = b"safe content"

    # Must not raise; must ignore the malicious filename entirely
    receipt = store.store(io.BytesIO(content), original_filename="../../../etc/passwd")

    sha256_hex = hashlib.sha256(content).hexdigest()
    assert sha256_hex in receipt.storage_key
    assert "passwd" not in receipt.storage_key
    assert "etc" not in receipt.storage_key
    assert ".." not in receipt.storage_key

    # Content must be retrievable and intact
    with store.retrieve(receipt.storage_key) as retrieved:
        assert retrieved.read() == content


def test_storage_key_must_be_hex_string(tmp_path: Path) -> None:
    """
    Invalid storage keys (non-hex, empty, traversal patterns) raise ValueError.
    The storage key format is strictly two-hex-char prefix + '/' + 64-hex-char hash.
    """
    store = FilesystemStore(root=tmp_path)

    invalid_keys = [
        "not-a-hex-key",
        "",
        "../etc/passwd",
        "ZZ/" + "Z" * 64,
        "ab",                  # missing separator and hash
        "ab/short",            # hash too short
        "ab/" + "g" * 64,     # non-hex characters in hash
    ]

    for key in invalid_keys:
        with pytest.raises(ValueError):
            store.retrieve(key)
