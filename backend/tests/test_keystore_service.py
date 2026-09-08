"""Tests for PKCS#12 → JKS conversion.

The output is read back with pyjks and the certificates re-parsed, so these
assert the keystore is genuinely loadable rather than merely non-empty. Java 8
is in service here, so the container must be legacy JKS (magic 0xFEEDFEED) and
not a PKCS#12 file wearing a .jks name.
"""

from datetime import UTC, datetime, timedelta

import jks
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.serialization import pkcs12
from cryptography.x509.oid import NameOID

from app.services.keystore_service import DEFAULT_ALIAS, pfx_to_jks, sanitize_alias

JKS_MAGIC = bytes.fromhex("feedfeed")
STORE_PASSWORD = "keystore-password"


def _self_signed(cn: str):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _pfx(password: str, *, cn: str = "cesdataroutergears.dev.att.com", with_chain: bool = True) -> bytes:
    key, cert = _self_signed(cn)
    chain = [_self_signed("Test Issuing CA")[1]] if with_chain else None
    return pkcs12.serialize_key_and_certificates(
        name=b"escrowed",
        key=key,
        cert=cert,
        cas=chain,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode())
        if password
        else serialization.NoEncryption(),
    )


# ── Alias normalization ────────────────────────────────────────────────


def test_alias_is_lowercased_to_match_java():
    # Java lowercases JKS aliases, so a caller-supplied alias must be normalized
    # or the application will look up a name that does not exist.
    assert sanitize_alias("CesDataRouterGears.DEV.att.com") == "cesdataroutergears.dev.att.com"


def test_alias_falls_back_to_a_default():
    assert sanitize_alias(None) == DEFAULT_ALIAS
    assert sanitize_alias("   ") == DEFAULT_ALIAS


def test_alias_is_truncated_to_the_jks_limit():
    assert len(sanitize_alias("a" * 400)) == 255


# ── Conversion ─────────────────────────────────────────────────────────


def test_produces_a_legacy_jks_container():
    blob = pfx_to_jks(_pfx("src-pw"), pfx_password="src-pw", store_password=STORE_PASSWORD)
    # A PKCS#12 file named .jks would not carry this magic and would fail on Java 8.
    assert blob[:4] == JKS_MAGIC


def test_keystore_round_trips_key_and_chain():
    blob = pfx_to_jks(_pfx("src-pw"), pfx_password="src-pw", store_password=STORE_PASSWORD)
    store = jks.KeyStore.loads(blob, STORE_PASSWORD)

    alias, entry = next(iter(store.private_keys.items()))
    assert alias == "cesdataroutergears.dev.att.com"
    assert entry.is_decrypted()
    # Leaf first, then the issuer — the order Java walks the chain in.
    assert len(entry.cert_chain) == 2
    leaf = x509.load_der_x509_certificate(entry.cert_chain[0][1])
    issuer = x509.load_der_x509_certificate(entry.cert_chain[1][1])
    assert leaf.subject.rfc4514_string() == "CN=cesdataroutergears.dev.att.com"
    assert issuer.subject.rfc4514_string() == "CN=Test Issuing CA"

    # The private key is usable, not just present.
    loaded_key = serialization.load_der_private_key(entry.pkey_pkcs8, password=None)
    assert loaded_key.key_size == 2048


def test_keystore_password_is_enforced():
    blob = pfx_to_jks(_pfx("src-pw"), pfx_password="src-pw", store_password=STORE_PASSWORD)
    with pytest.raises(jks.util.KeystoreSignatureException):
        jks.KeyStore.loads(blob, "wrong-password")


def test_alias_override_is_used():
    blob = pfx_to_jks(
        _pfx("src-pw"),
        pfx_password="src-pw",
        store_password=STORE_PASSWORD,
        alias="Tomcat-TLS",
    )
    store = jks.KeyStore.loads(blob, STORE_PASSWORD)
    assert list(store.private_keys) == ["tomcat-tls"]


def test_include_chain_false_keeps_only_the_leaf():
    blob = pfx_to_jks(
        _pfx("src-pw"),
        pfx_password="src-pw",
        store_password=STORE_PASSWORD,
        include_chain=False,
    )
    store = jks.KeyStore.loads(blob, STORE_PASSWORD)
    _alias, entry = next(iter(store.private_keys.items()))
    assert len(entry.cert_chain) == 1


def test_accepts_a_password_free_pfx():
    # Escrowed material may carry an empty password.
    blob = pfx_to_jks(_pfx(""), pfx_password="", store_password=STORE_PASSWORD)
    assert jks.KeyStore.loads(blob, STORE_PASSWORD).private_keys


def test_alias_defaults_when_the_certificate_has_no_common_name():
    key, _ = _self_signed("x")
    cert = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([]))
        .issuer_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "CA")]))
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(UTC) - timedelta(days=1))
        .not_valid_after(datetime.now(UTC) + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    blob = pfx_to_jks(
        pkcs12.serialize_key_and_certificates(
            name=None,
            key=key,
            cert=cert,
            cas=None,
            encryption_algorithm=serialization.NoEncryption(),
        ),
        pfx_password="",
        store_password=STORE_PASSWORD,
    )
    assert list(jks.KeyStore.loads(blob, STORE_PASSWORD).private_keys) == [DEFAULT_ALIAS]


# ── Failure modes ──────────────────────────────────────────────────────


def test_rejects_a_missing_store_password():
    with pytest.raises(ValueError, match="keystore password is required"):
        pfx_to_jks(_pfx("src-pw"), pfx_password="src-pw", store_password="")


def test_rejects_unreadable_material_without_leaking_it():
    with pytest.raises(ValueError) as excinfo:
        pfx_to_jks(b"not-a-pfx", pfx_password="src-pw", store_password=STORE_PASSWORD)
    message = str(excinfo.value)
    assert "could not read the PKCS#12 material" in message
    # Only the exception type is surfaced, never bytes that could carry key data.
    assert "not-a-pfx" not in message


def test_rejects_a_wrong_pfx_password():
    with pytest.raises(ValueError, match="could not read the PKCS#12 material"):
        pfx_to_jks(_pfx("src-pw"), pfx_password="wrong-pw", store_password=STORE_PASSWORD)


def test_rejects_a_certificate_only_pkcs12():
    # A PKCS#12 with no private key cannot become a usable keystore entry.
    _key, cert = _self_signed("a.example.com")
    blob = pkcs12.serialize_key_and_certificates(
        name=None,
        key=None,
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.NoEncryption(),
    )
    with pytest.raises(ValueError, match="no private key or certificate"):
        pfx_to_jks(blob, pfx_password="", store_password=STORE_PASSWORD)
