"""
SEC02 — Evidence store integrity tests.


Verifies content-addressing correctness, hash derivation, idempotency,
concurrency safety, and StorageReceipt field accuracy for FilesystemStore.

These tests cover properties NOT already exercised by test_storage_paths.py
(E01), which focuses on path-traversal resistance and key format validation.

All fixtures use synthetic in-memory bytes — no real client data.

Do NOT modify this file; it is owned exclusively by SEC02.
"""
from __future__ import annotations

import hashlib
import io
import re
import sys
import threading
from pathlib import Path

import pytest

from migration_intake.storage.filesystem import FilesystemStore


# ---------------------------------------------------------------------------
# Content-addressing correctness
# ---------------------------------------------------------------------------


def test_same_content_produces_same_hash(tmp_path: Path) -> None:
    """
    Identical bytes stored under different original filenames produce the
    same storage_key (content-addressed deduplication).

    This verifies that the storage key is derived exclusively from content,
    not from the user-supplied filename.
    """
    store = FilesystemStore(root=tmp_path)
    receipt_a = store.store(io.BytesIO(b"hello world"), "a.xlsx")
    receipt_b = store.store(io.BytesIO(b"hello world"), "b.xlsx")
    assert receipt_a.storage_key == receipt_b.storage_key
    assert receipt_a.sha256_hex == receipt_b.sha256_hex


def test_different_content_produces_different_hash(tmp_path: Path) -> None:
    """
    Different bytes produce different storage_keys.

    Verifies collision resistance at the application level — two distinct
    files must never share a storage key.
    """
    store = FilesystemStore(root=tmp_path)
    receipt_x = store.store(io.BytesIO(b"content-alpha"), "x.xlsx")
    receipt_y = store.store(io.BytesIO(b"content-beta"), "y.xlsx")
    assert receipt_x.storage_key != receipt_y.storage_key
    assert receipt_x.sha256_hex != receipt_y.sha256_hex


def test_stored_bytes_match_original(tmp_path: Path) -> None:
    """
    Bytes retrieved via retrieve() are byte-for-byte identical to the
    original stored content.

    Detects any accidental truncation, padding, or encoding corruption in
    the write path.
    """
    store = FilesystemStore(root=tmp_path)
    original = b"\x00\xff\x0d\x0a" * 1_024  # 4 KiB of mixed bytes
    receipt = store.store(io.BytesIO(original), "evidence.xlsx")
    with store.retrieve(receipt.storage_key) as fh:
        retrieved = fh.read()
    assert retrieved == original


def test_empty_bytes_stored_with_empty_hash(tmp_path: Path) -> None:
    """
    Empty bytes (b"") are stored successfully and the SHA-256 matches the
    well-known digest of the empty string.

    FilesystemStore does not reject empty content; it stores it under the
    SHA-256 of b"" and returns size_bytes=0.
    """
    store = FilesystemStore(root=tmp_path)
    receipt = store.store(io.BytesIO(b""), "empty.xlsx")

    expected_sha = hashlib.sha256(b"").hexdigest()
    assert receipt.sha256_hex == expected_sha
    assert receipt.size_bytes == 0
    # Content must be retrievable and empty
    with store.retrieve(receipt.storage_key) as fh:
        assert fh.read() == b""


# ---------------------------------------------------------------------------
# Storage key format
# ---------------------------------------------------------------------------


def test_storage_key_format_and_sha256_hex(tmp_path: Path) -> None:
    """
    StorageReceipt fields have the correct formats:

    - ``sha256_hex``   : exactly 64 lowercase hex characters (pure SHA-256 digest)
    - ``storage_key``  : ``"{sha256[:2]}/{sha256}"`` (67 chars, prefix-sharded path)

    The prefix sharding mirrors Git object storage and avoids filesystem
    directory-entry count limits.
    """
    store = FilesystemStore(root=tmp_path)
    receipt = store.store(io.BytesIO(b"test content for key format check"), "test.xlsx")

    # sha256_hex must be 64 lowercase hex characters
    assert re.match(r"^[0-9a-f]{64}$", receipt.sha256_hex), (
        f"sha256_hex is not 64-char lowercase hex: {receipt.sha256_hex!r}"
    )
    # storage_key must be "<2-hex-prefix>/<64-hex-hash>"
    assert re.match(r"^[0-9a-f]{2}/[0-9a-f]{64}$", receipt.storage_key), (
        f"storage_key does not match expected format: {receipt.storage_key!r}"
    )
    # The two-character prefix must match the first two chars of the digest
    prefix, sha_part = receipt.storage_key.split("/", 1)
    assert prefix == receipt.sha256_hex[:2]
    assert sha_part == receipt.sha256_hex


def test_original_filename_not_in_storage_key(tmp_path: Path) -> None:
    """
    The storage_key must not contain any part of the original filename.

    User-supplied filenames are used only for MIME-type inference; they must
    never appear in storage paths.
    """
    store = FilesystemStore(root=tmp_path)
    sensitive_name = "confidential_client_data_Q4_2024.xlsx"
    receipt = store.store(io.BytesIO(b"probe content"), sensitive_name)

    assert "confidential" not in receipt.storage_key
    assert "client" not in receipt.storage_key
    assert "Q4" not in receipt.storage_key
    assert "2024" not in receipt.storage_key
    # Also verify against sha256_hex for completeness
    assert sensitive_name not in receipt.sha256_hex


# ---------------------------------------------------------------------------
# Concurrency safety
# ---------------------------------------------------------------------------


def test_concurrent_duplicate_store_is_safe(tmp_path: Path) -> None:
    """
    Storing identical content concurrently from multiple threads does not
    corrupt the stored file and all receipts carry the same storage_key.

    The store's atomic-write design (temp file → os.replace()) must handle
    the race where multiple threads promote the same content simultaneously.

    NOTE: xfail on Windows — see decorator for details.
    """
    store = FilesystemStore(root=tmp_path)
    content = b"concurrent test content " * 100  # 2,400 bytes
    results: list[object] = []
    errors: list[BaseException] = []

    def _store() -> None:
        try:
            results.append(store.store(io.BytesIO(content), "file.xlsx"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_store) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Thread errors: {errors}"
    assert len(results) == 5, "All five threads must complete"

    # All receipts must share the same storage_key (content-addressed)
    storage_keys = {r.storage_key for r in results}  # type: ignore[union-attr]
    assert len(storage_keys) == 1, (
        f"Concurrent stores of identical content produced multiple keys: {storage_keys}"
    )

    # Retrieved content must be byte-for-byte correct (no corruption)
    key = next(iter(storage_keys))
    with store.retrieve(key) as fh:
        assert fh.read() == content


# ---------------------------------------------------------------------------
# StorageReceipt field accuracy
# ---------------------------------------------------------------------------


def test_store_works_with_tmp_path(tmp_path: Path) -> None:
    """
    FilesystemStore initialises and operates correctly with an arbitrary
    writable directory (e.g. pytest's tmp_path).

    This test confirms the store accepts non-source-controlled paths without
    error, creating the directory hierarchy as needed.
    """
    nested = tmp_path / "level1" / "level2" / "store_root"
    # Directory does not yet exist — store must create it
    store = FilesystemStore(root=nested)
    receipt = store.store(io.BytesIO(b"writable path test"), "probe.xlsx")
    assert store.exists(receipt.storage_key)


def test_receipt_contains_correct_byte_count(tmp_path: Path) -> None:
    """
    StorageReceipt.size_bytes equals the exact byte count of the stored
    content — not an approximation or compressed size.
    """
    store = FilesystemStore(root=tmp_path)
    content = b"measure me exactly"
    receipt = store.store(io.BytesIO(content), "f.xlsx")
    assert receipt.size_bytes == len(content), (
        f"Expected size_bytes={len(content)}, got {receipt.size_bytes}"
    )


def test_receipt_size_bytes_for_large_content(tmp_path: Path) -> None:
    """
    size_bytes is accurate for content larger than a single read chunk.

    FilesystemStore reads in 64 KiB chunks; this test uses 200 KiB to
    exercise the multi-chunk accumulation path.
    """
    store = FilesystemStore(root=tmp_path)
    content = b"X" * (200 * 1_024)  # 200 KiB
    receipt = store.store(io.BytesIO(content), "large.xlsx")
    assert receipt.size_bytes == len(content)
    # SHA-256 must also match
    expected_sha = hashlib.sha256(content).hexdigest()
    assert receipt.sha256_hex == expected_sha
