"""Tests for Key Vault bulk secret validation and file parsing."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from app.services.keyvault_bulk_service import (
    BULK_SECRET_MAX_COUNT,
    parse_bulk_secrets_csv,
    parse_bulk_secrets_file,
    parse_bulk_secrets_json,
    validate_bulk_secrets,
)
from app.services.keyvault_service import KeyVaultService, _normalize_vault_uri


def test_validate_bulk_secrets_happy_path():
    secrets = [
        {"name": "app-config", "value": "secret-one"},
        {"name": "db-password", "value": "secret-two"},
    ]
    result = validate_bulk_secrets(secrets, vault_uri="https://vault.vault.azure.net/")
    assert result["valid"] is True
    assert result["valid_count"] == 2
    assert result["invalid_count"] == 0


def test_validate_bulk_secrets_rejects_duplicate_names():
    secrets = [
        {"name": "dup-name", "value": "a"},
        {"name": "dup-name", "value": "b"},
    ]
    result = validate_bulk_secrets(secrets, vault_uri="https://vault.vault.azure.net/")
    assert result["valid"] is False
    assert any("Duplicate" in err["error"] for err in result["errors"])


def test_validate_bulk_secrets_rejects_invalid_name():
    result = validate_bulk_secrets(
        [{"name": "bad_name", "value": "x"}],
        vault_uri="https://vault.vault.azure.net/",
    )
    assert result["valid"] is False
    assert any("alphanumeric" in err["error"] for err in result["errors"])


def test_validate_bulk_secrets_rejects_oversized_value():
    huge = "x" * (25 * 1024 + 1)
    result = validate_bulk_secrets(
        [{"name": "big-secret", "value": huge}],
        vault_uri="https://vault.vault.azure.net/",
    )
    assert result["valid"] is False
    assert any("exceeds" in err["error"] for err in result["errors"])


def test_validate_bulk_secrets_rejects_over_limit():
    secrets = [{"name": f"s-{i}", "value": "v"} for i in range(BULK_SECRET_MAX_COUNT + 1)]
    result = validate_bulk_secrets(secrets, vault_uri="https://vault.vault.azure.net/")
    assert result["valid"] is False


def test_parse_bulk_secrets_csv():
    content = b"secret_name,secret_value,content_type\nmy-secret,abc123,text/plain\n"
    rows = parse_bulk_secrets_csv(content)
    assert rows == [{"name": "my-secret", "value": "abc123", "content_type": "text/plain"}]


def test_parse_bulk_secrets_json():
    payload = {"secrets": [{"name": "a", "value": "1"}, {"name": "b", "value": "2"}]}
    rows = parse_bulk_secrets_json(json.dumps(payload).encode("utf-8"))
    assert len(rows) == 2
    assert rows[0]["name"] == "a"


def test_parse_bulk_secrets_file_rejects_unknown_extension():
    with pytest.raises(ValueError, match="Unsupported file type"):
        parse_bulk_secrets_file("secrets.txt", b"name,value\n")


def _make_pem_cert() -> bytes:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test.example.com")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC))
        .not_valid_after(datetime.now(UTC) + timedelta(days=30))
        .sign(key, hashes.SHA256())
    )
    return cert.public_bytes(serialization.Encoding.PEM)


def test_validate_certificate_content_pem():
    pem = _make_pem_cert()
    meta = KeyVaultService.validate_certificate_content(pem, "pem")
    assert meta["format"] == "pem"
    assert "CN=test.example.com" in meta["subject"]


def test_validate_certificate_content_pfx_requires_password():
    pem = _make_pem_cert()
    with pytest.raises(ValueError, match="Password is required"):
        KeyVaultService.validate_certificate_content(pem, "pfx")


def test_normalize_vault_uri_adds_trailing_slash():
    assert _normalize_vault_uri("https://vault.vault.azure.net") == "https://vault.vault.azure.net/"
    assert _normalize_vault_uri("https://vault.vault.azure.net/") == "https://vault.vault.azure.net/"


def test_certificate_conflict_kind_detects_deleted_and_pending():
    deleted_msg = (
        "HTTP Error 409: Conflict — Certificate test is currently in a deleted but recoverable state"
    )
    pending_msg = (
        "HTTP Error 409: Conflict — A new key vault certificate can not be created or imported "
        "while a pending key vault certificate's status is inProgress."
    )
    assert KeyVaultService._certificate_conflict_kind(deleted_msg) == "deleted"
    assert KeyVaultService._certificate_conflict_kind(pending_msg) == "pending"
    assert KeyVaultService._certificate_conflict_kind("HTTP Error 409: Conflict — unknown") is None
