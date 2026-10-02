"""
Keyfactor certificate service.

Business layer between the API router and the low-level ``KeyfactorClient``.
Responsibilities:
- Validate and shape inputs before calling Keyfactor.
- Normalize Keyfactor responses into a stable, UI-friendly schema.
- Compute a derived certificate status (valid / expiring / expired / revoked).
- Map ``KeyfactorError`` subclasses to friendly, structured domain errors so
  routers never leak raw upstream internals or stack traces.

Private key / PFX material is passed straight through in the enrollment result
and is never persisted or logged.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from ipaddress import ip_address
from typing import Any, TypeVar

import structlog
from cryptography import x509

from app.core.config import settings
from app.services.keyfactor_client import (
    REVOCATION_REASONS,
    KeyfactorClient,
    KeyfactorError,
    get_keyfactor_client,
)

logger = structlog.get_logger(__name__)

EXPIRING_SOON_DAYS = 30

_T = TypeVar("_T")


class CertificateServiceError(Exception):
    """Domain error with a friendly message and an HTTP status hint."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _first_present(source: dict[str, Any], *keys: str) -> Any:
    """First non-null value among ``keys``, matched case-insensitively.

    Keyfactor is inconsistent about the casing of its identifier fields —
    ``CertificateInformation`` carries ``KeyfactorID`` (capital ID) on
    ``/Enrollment/PFX`` and ``/Enrollment/CSR``, while other payloads use
    ``Id``. A plain ``.get("KeyfactorId")`` silently misses it, which drops the
    new certificate's id from every enrollment and renewal response and, in
    turn, from the key-escrow pointer written for it.
    """
    for key in keys:
        value = source.get(key)
        if value is not None:
            return value
    lowered = {k.lower(): v for k, v in source.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is not None:
            return value
    return None


def _parse_dt(value: Any) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    raw = value.strip()
    try:
        # Keyfactor verbose responses use ISO 8601; tolerate a trailing Z.
        return datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None


def _extract_sans(cert: dict[str, Any]) -> list[str]:
    sans: list[str] = []
    elements = cert.get("SubjectAltNameElements") or cert.get("SANs") or []
    if isinstance(elements, list):
        for el in elements:
            if isinstance(el, dict):
                val = el.get("Value") or el.get("value")
                if val:
                    sans.append(str(val))
            elif isinstance(el, str):
                sans.append(el)
    return sans


# Keyfactor reports SANs as SubjectAltNameElements tagged with a GeneralName
# type, but its enrollment endpoints take SANs grouped under named keys, so
# preserving SANs across a renewal means translating between the two.
_SAN_TYPE_KEYS: dict[str, str] = {
    "0": "other",
    "1": "email",
    "2": "dns",
    "6": "uri",
    "7": "ip4",
    "othername": "other",
    "other": "other",
    "rfc822name": "email",
    "email": "email",
    "dnsname": "dns",
    "dns": "dns",
    "uniformresourceidentifier": "uri",
    "uri": "uri",
    "ipaddress": "ip4",
    "ip": "ip4",
    "ip4": "ip4",
    "ip6": "ip6",
    "userprincipalname": "upn",
    "upn": "upn",
}


def _is_ip(value: str) -> bool:
    try:
        ip_address(value)
    except ValueError:
        return False
    return True


def _san_key(raw_type: Any, value: str) -> str:
    """Enrollment SAN key for one SubjectAltNameElement."""
    key = _SAN_TYPE_KEYS.get(str(raw_type).strip().lower()) if raw_type not in (None, "") else None
    if key is None:
        # Some Keyfactor responses omit the type; infer it from the value shape.
        key = "email" if "@" in value else ("ip4" if _is_ip(value) else "dns")
    if key in ("ip4", "ip6"):
        key = "ip6" if ":" in value else "ip4"
    return key


def _sans_for_enrollment(cert: dict[str, Any]) -> dict[str, list[str]]:
    """Group a certificate's SANs into the ``{type: [value]}`` shape enrollment takes."""
    grouped: dict[str, list[str]] = {}
    elements = cert.get("SubjectAltNameElements") or cert.get("SANs") or []
    if not isinstance(elements, list):
        return grouped
    for el in elements:
        if isinstance(el, dict):
            raw_value = el.get("Value") or el.get("value")
            raw_type = el.get("Type", el.get("type"))
        elif isinstance(el, str):
            raw_value, raw_type = el, None
        else:
            continue
        value = str(raw_value).strip() if raw_value else ""
        if not value:
            continue
        bucket = grouped.setdefault(_san_key(raw_type, value), [])
        if value not in bucket:
            bucket.append(value)
    return grouped


def _normalize_san_keys(sans: dict[str, list[str]] | None) -> dict[str, list[str]] | None:
    """Rewrite caller-supplied SAN type keys to the ones Keyfactor accepts.

    The UI offers plain labels like ``DNS`` and ``IP``; Keyfactor wants ``dns``
    and the address-family-specific ``ip4`` / ``ip6``. An unrecognized key is
    passed through untouched rather than guessed at, so a future SAN type the UI
    learns before this map does still reaches Keyfactor.
    """
    if not sans:
        return sans
    normalized: dict[str, list[str]] = {}
    for raw_key, values in sans.items():
        if not values:
            continue
        for raw_value in values:
            value = str(raw_value).strip()
            if not value:
                continue
            mapped = _SAN_TYPE_KEYS.get(str(raw_key).strip().lower())
            key = _san_key(raw_key, value) if mapped else str(raw_key)
            bucket = normalized.setdefault(key, [])
            if value not in bucket:
                bucket.append(value)
    return normalized or None


def _csr_declares_sans(csr: str) -> bool:
    """Whether a PEM CSR already carries a subjectAltName extension."""
    try:
        request = x509.load_pem_x509_csr(csr.encode("utf-8"))
        san = request.extensions.get_extension_for_class(x509.SubjectAlternativeName)
    except (ValueError, TypeError, x509.ExtensionNotFound):
        return False
    return bool(san.value)


def default_revocation_comment(reason: str, actor: str | None = None) -> str:
    """Comment recorded in Keyfactor when the caller leaves the field blank.

    Keyfactor requires a non-empty comment on revocation, so "optional" in the
    portal has to mean "we fill one in", not "we send nothing".
    """
    who = (actor or "").strip()
    by = f" by {who}" if who else ""
    return f"Revoked via OpsPortal{by} (reason: {reason})"


# Keyfactor's CertState enum. The API sends the number in ``CertState`` and a
# display form in ``CertStateString`` — which is "Revoked (2)", not "Revoked".
_CERT_STATE_BY_NAME = {"unknown": 0, "active": 1, "revoked": 2, "denied": 3, "failed": 4, "pending": 5}
_CERT_STATE_REVOKED = 2


def _cert_state_code(cert: dict[str, Any]) -> int | None:
    """Numeric Keyfactor CertState, or None when it cannot be determined.

    The numeric field is preferred because it is unambiguous. The display string
    is only parsed as a fallback, and has to tolerate the parenthesised form:
    matching it as a bare name left every revoked certificate looking active,
    which in turn got them filed under "Deleted" when they dropped out of their
    collection's saved search.
    """
    raw = cert.get("CertState")
    if raw is not None and not isinstance(raw, bool):
        try:
            return int(raw)
        except (TypeError, ValueError):
            pass
    label = str(cert.get("CertStateString") or "").strip().lower()
    if not label:
        return None
    if (match := re.search(r"\((\d+)\)", label)) is not None:
        return int(match.group(1))
    for name, value in _CERT_STATE_BY_NAME.items():
        if label.startswith(name):
            return value
    return None


def _compute_status(not_after: datetime | None, revoked: bool) -> str:
    if revoked:
        return "revoked"
    if not_after is None:
        return "unknown"
    now = datetime.now(UTC)
    naive_after = not_after if not_after.tzinfo else not_after.replace(tzinfo=UTC)
    if naive_after < now:
        return "expired"
    if naive_after <= now + timedelta(days=EXPIRING_SOON_DAYS):
        return "expiring_soon"
    return "valid"


def normalize_certificate(cert: dict[str, Any]) -> dict[str, Any]:
    """Map a raw Keyfactor certificate object to the portal schema."""
    state_code = _cert_state_code(cert)
    revocation_reason = cert.get("RevocationReason")
    # The state is authoritative when known. Only when it is missing entirely
    # does a revocation reason stand in for it — and reason 0 ("unspecified")
    # is indistinguishable from no reason at all, so it cannot be relied on.
    revoked = state_code == _CERT_STATE_REVOKED if state_code is not None else revocation_reason not in (None, "", 0)

    not_before = _parse_dt(cert.get("NotBefore"))
    not_after = _parse_dt(cert.get("NotAfter"))
    import_date = _parse_dt(cert.get("ImportDate"))
    effective_date = _parse_dt(cert.get("EffectiveDate") or cert.get("NotBefore"))

    sans = _extract_sans(cert)

    # Locations list
    locations = []
    raw_locations = cert.get("Locations") or []
    for loc in raw_locations:
        if isinstance(loc, dict):
            locations.append(
                {
                    "store_path": loc.get("StorePath") or "",
                    "agent_pool": loc.get("AgentPool") or "",
                    "alias": loc.get("Alias") or "",
                }
            )

    return {
        "id": cert.get("Id"),
        "common_name": cert.get("CN") or cert.get("IssuedCN") or "",
        "subject_dn": cert.get("IssuedDN") or cert.get("SubjectDN") or "",
        "issuer_dn": cert.get("IssuerDN") or "",
        "serial_number": cert.get("SerialNumber") or "",
        "thumbprint": cert.get("Thumbprint") or "",
        "template": cert.get("TemplateName") or cert.get("Template") or "",
        "certificate_authority": (
            cert.get("CertificateAuthorityName") or cert.get("CertificateAuthority") or cert.get("CAName") or ""
        ),
        "not_before": not_before.isoformat() if not_before else None,
        "not_after": not_after.isoformat() if not_after else None,
        "import_date": import_date.isoformat() if import_date else None,
        "effective_date": effective_date.isoformat() if effective_date else None,
        "sans": sans,
        "san_count": len(sans),
        "revoked": revoked,
        "revocation_reason": revocation_reason if revoked else None,
        "status": _compute_status(not_after, revoked),
        "metadata": cert.get("Metadata") if isinstance(cert.get("Metadata"), dict) else {},
        # Enriched fields from Keyfactor verbose response
        "key_algorithm": cert.get("KeyType") or cert.get("KeyAlgorithm") or "",
        "key_size": cert.get("KeySize") or cert.get("KeyLength") or 0,
        "key_usage": cert.get("KeyUsage") or "",
        "extended_key_usage": cert.get("ExtendedKeyUsage") or "",
        "signing_algorithm": cert.get("SigningAlgorithm") or "",
        "requester": cert.get("Requester") or cert.get("RequestedBy") or "",
        "principal_name": cert.get("PrincipalName") or "",
        "locations": locations,
        "location_count": len(locations),
        "collection": cert.get("CertificateCollectionName") or cert.get("Collection") or "",
        "has_private_key": bool(cert.get("HasPrivateKey", False)),
    }


def _template_or_pattern(template: str, enrollment_pattern_id: int | None) -> dict[str, Any]:
    """Enrollment selector: the pattern id when given, else the legacy template name.

    Keyfactor resolves a bare template to its default enrollment pattern and rejects
    the request when the template has none, so an explicit pattern id wins.
    """
    if enrollment_pattern_id is not None:
        return {"EnrollmentPatternId": enrollment_pattern_id}
    return {"Template": template}


def _ca_enrollment_value(ca: dict[str, Any]) -> str:
    """Return the ``HostName\\LogicalName`` string Keyfactor enrollment expects."""
    logical = str(ca.get("LogicalName") or ca.get("Name") or "").strip()
    host = str(ca.get("HostName") or "").strip()
    if "\\" in logical:
        return logical
    return f"{host}\\{logical}" if host and logical else logical


def _configured_default_authorities() -> list[dict[str, Any]]:
    """The single CA from ``KEYFACTOR_DEFAULT_CA``, or nothing if unset."""
    value = settings.KEYFACTOR_DEFAULT_CA.strip()
    if not value:
        return []
    host, _, logical = value.rpartition("\\")
    logical = logical or value
    return [
        {
            "id": 0,
            "name": logical,
            "logical_name": logical,
            "host_name": host,
            "value": value,
            "source": "configured-default",
        }
    ]


def _configured_default_templates() -> list[dict[str, Any]]:
    """The single template from ``KEYFACTOR_DEFAULT_TEMPLATE``, or nothing if unset."""
    name = settings.KEYFACTOR_DEFAULT_TEMPLATE.strip()
    if not name:
        return []
    return [
        {
            "id": 0,
            "common_name": name,
            "template_name": name,
            "oid": "",
            "key_size": "",
            "key_type": "",
            "source": "configured-default",
        }
    ]


# Keyfactor MetadataField DataType and Enrollment enums.
_METADATA_TYPES = {1: "string", 2: "integer", 3: "date", 4: "boolean", 5: "choice", 6: "text", 7: "email"}
_METADATA_REQUIRED = 1
_METADATA_HIDDEN = 2


def _configured_enrollment_patterns() -> list[dict[str, Any]]:
    """Patterns from ``KEYFACTOR_ENROLLMENT_PATTERNS`` (``id:name|template``); malformed entries are skipped."""
    patterns: list[dict[str, Any]] = []
    for entry in settings.KEYFACTOR_ENROLLMENT_PATTERNS.split(","):
        raw_id, sep, rest = entry.partition(":")
        name, _, template_name = rest.partition("|")
        raw_id, name = raw_id.strip(), name.strip()
        if not sep or not raw_id.isdigit() or not name or int(raw_id) < 1:
            continue
        patterns.append(
            {"id": int(raw_id), "name": name, "template_name": template_name.strip(), "source": "configured"}
        )
    return patterns


def _template_policy(template: dict[str, Any]) -> dict[str, Any]:
    """Group, allowed key algorithms and CAs for a PFX-context template."""
    policy = template.get("EnrollmentTemplatePolicy")
    key_info = (policy.get("KeyInfo") if isinstance(policy, dict) else None) or {}
    algorithms: list[dict[str, Any]] = []
    # Keyfactor reports ECDSA in policy but takes KeyType "ECC" on enrollment.
    for policy_key, key_type in (("RSA", "RSA"), ("ECDSA", "ECC")):
        info = key_info.get(policy_key) or {}
        sizes = [int(b) for b in info.get("bit_lengths") or [] if str(b).isdigit()]
        curves = [str(c) for c in info.get("curves") or [] if c]
        if sizes or curves:
            algorithms.append({"name": key_type, "key_sizes": sizes, "curves": curves})
    return {
        "group": template.get("Forest") or "",
        "key_algorithms": algorithms,
        "certificate_authorities": [
            str(ca["Name"]) for ca in template.get("CAs") or [] if isinstance(ca, dict) and ca.get("Name")
        ],
    }


def _with_template_policy(patterns: list[dict[str, Any]], templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Attach each pattern's template policy, matched on template or pattern name."""
    index: dict[str, dict[str, Any]] = {}
    for t in templates:
        if not isinstance(t, dict):
            continue
        for key in (t.get("Name"), t.get("DisplayName")):
            if key:
                index.setdefault(str(key).strip().lower(), t)
    empty: dict[str, Any] = {"group": "", "key_algorithms": [], "certificate_authorities": []}
    enriched = []
    for p in patterns:
        match = index.get(p["template_name"].lower()) or index.get(p["name"].lower())
        enriched.append({**p, **(_template_policy(match) if match else empty)})
    return enriched


class CertificateService:
    """High-level certificate lifecycle operations."""

    def __init__(self, client: KeyfactorClient | None = None) -> None:
        self._client = client or get_keyfactor_client()

    async def _guard(self, coro: Awaitable[_T]) -> _T:
        try:
            return await coro
        except KeyfactorError as exc:
            logger.warning(
                "keyfactor_operation_failed",
                error_type=type(exc).__name__,
                status=exc.status_code,
                detail=exc.detail,
            )
            raise CertificateServiceError(exc.detail, status_code=exc.status_code or 502) from exc

    # -- read -----------------------------------------------------------

    async def list_certificates(
        self,
        *,
        query: str | None,
        page: int,
        page_size: int,
        collection_id: int | None = None,
    ) -> dict[str, Any]:
        certs, total = await self._guard(
            self._client.search_certificates(query=query, page=page, page_size=page_size, collection_id=collection_id)
        )
        items = [normalize_certificate(c) for c in certs]
        return {
            "items": items,
            "total": total,
            "page": page,
            "page_size": page_size,
        }

    async def get_certificate(self, certificate_id: int, *, collection_id: int | None = None) -> dict[str, Any]:
        """Fetch one certificate.

        ``collection_id`` scopes the permission check. Keyfactor evaluates an
        unscoped read against every collection, which an identity granted only
        specific collections is refused for — so callers that know the
        collection should pass it. It scopes permission, not membership: a
        certificate that has left the collection is still returned.
        """
        cert = await self._guard(self._client.get_certificate(certificate_id, collection_id=collection_id))
        return normalize_certificate(cert)

    # -- write ----------------------------------------------------------

    async def enroll_csr(
        self,
        *,
        csr: str,
        certificate_authority: str,
        template: str,
        sans: dict[str, list[str]] | None,
        metadata: dict[str, Any] | None,
        include_chain: bool,
        enrollment_pattern_id: int | None = None,
        owner_role_name: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "CSR": csr,
            **_template_or_pattern(template, enrollment_pattern_id),
            "IncludeChain": include_chain,
            "Timestamp": datetime.now(UTC).isoformat(),
        }
        if certificate_authority.strip():
            payload["CertificateAuthority"] = certificate_authority.strip()
        if owner_role_name and owner_role_name.strip():
            payload["OwnerRoleName"] = owner_role_name.strip()
        normalized_sans = _normalize_san_keys(sans)
        if normalized_sans:
            payload["SANs"] = normalized_sans
        if metadata:
            payload["Metadata"] = metadata
        result = await self._guard(self._client.enroll_csr(payload))
        return self._shape_enrollment(result)

    async def enroll_pfx(
        self,
        *,
        subject: str,
        certificate_authority: str,
        template: str,
        password: str,
        key_type: str,
        key_length: int,
        sans: dict[str, list[str]] | None,
        metadata: dict[str, Any] | None,
        include_chain: bool,
        enrollment_pattern_id: int | None = None,
        owner_role_name: str | None = None,
        curve: str | None = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "Subject": subject,
            **_template_or_pattern(template, enrollment_pattern_id),
            "Password": password,
            "KeyType": key_type,
            "KeyLength": key_length,
            "IncludeChain": include_chain,
            "Timestamp": datetime.now(UTC).isoformat(),
        }
        # Blank means Keyfactor's "Auto-Select": the pattern picks the CA.
        if certificate_authority.strip():
            payload["CertificateAuthority"] = certificate_authority.strip()
        if curve and curve.strip():
            payload["Curve"] = curve.strip()
        if owner_role_name and owner_role_name.strip():
            payload["OwnerRoleName"] = owner_role_name.strip()
        normalized_sans = _normalize_san_keys(sans)
        if normalized_sans:
            payload["SANs"] = normalized_sans
        if metadata:
            payload["Metadata"] = metadata
        result = await self._guard(self._client.enroll_pfx(payload))
        return self._shape_enrollment(result, pfx=True)

    async def renew_certificate(
        self,
        *,
        certificate_id: int,
        mode: str,
        certificate_authority: str | None,
        template: str | None,
        collection_id: int | None = None,
        password: str | None = None,
        key_type: str | None = None,
        key_length: int | None = None,
        owner_role_name: str | None = None,
        csr: str | None = None,
    ) -> dict[str, Any]:
        source_certificate: dict[str, Any] | None = None
        if mode in ("pfx", "csr"):
            source_certificate = await self._guard(
                self._client.get_certificate(certificate_id, collection_id=collection_id)
            )

        def preserve_owner(payload: dict[str, Any]) -> None:
            if owner_role_name and owner_role_name.strip():
                payload["OwnerRoleName"] = owner_role_name.strip()
                return
            if source_certificate is None:
                return
            owner_role_id = source_certificate.get("OwnerRoleId")
            source_owner_role_name = source_certificate.get("OwnerRoleName")
            if owner_role_id is not None:
                payload["OwnerRoleId"] = owner_role_id
            elif isinstance(source_owner_role_name, str) and source_owner_role_name.strip():
                payload["OwnerRoleName"] = source_owner_role_name.strip()

        def preserve_metadata(payload: dict[str, Any]) -> None:
            if source_certificate is None:
                return
            metadata = source_certificate.get("Metadata")
            if isinstance(metadata, dict) and metadata:
                payload["Metadata"] = dict(metadata)

        def preserve_sans(payload: dict[str, Any], *, source_csr: str | None = None) -> None:
            # /Enrollment/PFX and /Enrollment/CSR build a brand-new request and
            # carry nothing over from the certificate being renewed, so every SAN
            # beyond the CN is silently dropped unless it is resent here. A CSR
            # that declares its own SANs is left alone: that is the caller's
            # explicit intent, and Keyfactor would merge the two lists.
            if source_certificate is None:
                return
            if source_csr and _csr_declares_sans(source_csr):
                return
            sans = _sans_for_enrollment(source_certificate)
            if sans:
                payload["SANs"] = sans

        def preserve_subject(payload: dict[str, Any]) -> None:
            # Reuse the existing certificate's exact Subject DN so template subject
            # policy (C/L/O/ST) validates; without it Keyfactor derives an invalid
            # subject from AD or empty defaults and rejects the renewal.
            if source_certificate is None:
                return
            subject = source_certificate.get("IssuedDN") or source_certificate.get("SubjectDN")
            if isinstance(subject, str) and subject.strip():
                payload["Subject"] = subject.strip()
                payload["PopulateMissingValuesFromAD"] = False

        if mode == "pfx":
            if not password or len(password.strip()) < 12:
                raise CertificateServiceError(
                    "Password must contain at least 12 non-blank characters for PFX renewal.",
                    status_code=422,
                )
            pfx_payload: dict[str, Any] = {
                "RenewalCertificateId": certificate_id,
                "Password": password,
                "IncludeChain": True,
                "Timestamp": datetime.now(UTC).isoformat(),
            }
            if certificate_authority:
                pfx_payload["CertificateAuthority"] = certificate_authority
            if template:
                pfx_payload["Template"] = template
            if key_type:
                pfx_payload["KeyType"] = key_type
            if key_length:
                pfx_payload["KeyLength"] = key_length
            preserve_owner(pfx_payload)
            preserve_metadata(pfx_payload)
            preserve_subject(pfx_payload)
            preserve_sans(pfx_payload)
            # Renewal is scoped to RenewalCertificateId alone: no directive is sent
            # that would replace this certificate across its existing locations.
            result = await self._guard(self._client.enroll_pfx(pfx_payload))
            return self._shape_enrollment(result, pfx=True)

        if mode == "csr":
            if not csr or not csr.strip():
                raise CertificateServiceError("CSR is required for CSR renewal.", status_code=422)
            csr_payload = {
                "CSR": csr.strip(),
                "RenewalCertificateId": certificate_id,
                "IncludeChain": True,
                "Timestamp": datetime.now(UTC).isoformat(),
            }
            if certificate_authority:
                csr_payload["CertificateAuthority"] = certificate_authority
            if template:
                csr_payload["Template"] = template
            preserve_owner(csr_payload)
            preserve_metadata(csr_payload)
            preserve_sans(csr_payload, source_csr=csr)
            result = await self._guard(self._client.enroll_csr(csr_payload))
            return self._shape_enrollment(result)

        renewal_payload: dict[str, Any] = {
            "CertificateId": certificate_id,
            "Timestamp": datetime.now(UTC).isoformat(),
        }
        if certificate_authority:
            renewal_payload["CertificateAuthority"] = certificate_authority
        if template:
            renewal_payload["Template"] = template
        if collection_id is not None:
            renewal_payload["CollectionId"] = collection_id
        result = await self._guard(self._client.renew_certificate(renewal_payload, collection_id=collection_id))
        return self._shape_enrollment(result)

    async def revoke_certificate(
        self,
        *,
        certificate_id: int,
        reason: str,
        comment: str,
        effective_date: datetime | None,
        collection_id: int | None = None,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Revoke a certificate, substituting a comment when the caller omits one.

        Keyfactor rejects a blank ``Comment`` on ``/Certificates/Revoke``, which
        would make the portal's optional comment field impossible to leave empty.
        Filling in who revoked it and why keeps the field genuinely optional and
        still leaves a useful trail in Keyfactor's own revocation record.

        Returns the comment actually sent so callers can audit what Keyfactor got.
        """
        if reason not in REVOCATION_REASONS:
            raise CertificateServiceError(
                f"Invalid revocation reason '{reason}'. Allowed: {', '.join(REVOCATION_REASONS)}.",
                status_code=422,
            )
        effective_comment = (comment or "").strip() or default_revocation_comment(reason, actor)
        payload: dict[str, Any] = {
            "CertificateIds": [certificate_id],
            "Reason": REVOCATION_REASONS[reason],
            "Comment": effective_comment,
            "EffectiveDate": (effective_date or datetime.now(UTC)).isoformat(),
        }
        if collection_id is not None:
            payload["CollectionId"] = collection_id
        await self._guard(self._client.revoke_certificate(payload, collection_id=collection_id))
        return {
            "certificate_id": certificate_id,
            "reason": reason,
            "revoked": True,
            "comment": effective_comment,
        }

    async def update_metadata(
        self,
        *,
        certificate_id: int,
        metadata: dict[str, Any],
    ) -> dict[str, Any]:
        if not metadata:
            raise CertificateServiceError("No metadata fields provided to update.", status_code=422)
        payload = {"Id": certificate_id, "Metadata": metadata}
        await self._guard(self._client.update_metadata(payload))
        return {"certificate_id": certificate_id, "updated_fields": sorted(metadata.keys())}

    async def delete_certificate(self, certificate_id: int, *, collection_id: int | None = None) -> dict[str, Any]:
        await self._guard(self._client.delete_certificate(certificate_id, collection_id=collection_id))
        return {"certificate_id": certificate_id, "deleted": True}

    async def download_certificate(
        self,
        certificate_id: int,
        *,
        file_format: str = "PEM",
        include_chain: bool = True,
        chain_order: str = "EndEntityFirst",
        collection_id: int | None = None,
        pfx_password: str | None = None,
    ) -> bytes:
        """Download a certificate in the specified format."""
        allowed_formats = ("PEM", "CER", "CRT", "DER", "P7B", "PFX")
        if file_format.upper() not in allowed_formats:
            raise CertificateServiceError(
                f"Invalid format '{file_format}'. Allowed: {', '.join(allowed_formats)}.",
                status_code=422,
            )
        if chain_order not in ("EndEntityFirst", "RootFirst"):
            raise CertificateServiceError(
                "chain_order must be 'EndEntityFirst' or 'RootFirst'.",
                status_code=422,
            )
        return await self._guard(
            self._client.download_certificate(
                certificate_id,
                file_format=file_format.upper(),
                include_chain=include_chain,
                chain_order=chain_order,
                collection_id=collection_id,
                pfx_password=pfx_password,
            )
        )

    async def list_collections(self) -> list[dict[str, Any]]:
        """Return available certificate collections."""
        raw = await self._guard(self._client.get_collections())
        return [
            {
                "id": c.get("Id"),
                "name": c.get("Name") or "",
                "description": c.get("Description") or "",
                "certificate_count": (
                    c.get("EstimatedCertificateCount")
                    or c.get("CertificateCount")
                    or c.get("Count")
                    or c.get("NodeCount")
                    or 0
                ),
                "query": c.get("Query") or "",
            }
            for c in raw
            if isinstance(c, dict)
        ]

    async def list_templates(self) -> list[dict[str, Any]]:
        """Return enrollment templates, falling back to the configured default.

        See :meth:`list_certificate_authorities` for why enumeration failures
        degrade instead of raising.
        """
        raw = await self._list_or_empty(self._client.get_enrollment_templates(), what="templates")
        templates = [
            {
                "id": t.get("Id"),
                "common_name": t.get("CommonName") or t.get("Name") or "",
                "template_name": t.get("TemplateName") or t.get("Name") or "",
                "oid": t.get("Oid") or "",
                "key_size": t.get("KeySize") or "",
                "key_type": t.get("KeyType") or "",
                "source": "keyfactor",
            }
            for t in raw
            if isinstance(t, dict)
        ]
        return templates or _configured_default_templates()

    async def list_certificate_authorities(self) -> list[dict[str, Any]]:
        """Return available CAs, falling back to the configured default.

        Listing CAs needs a Keyfactor permission (``CertificateAuthorities:
        Read``) that the portal's service account is frequently not granted even
        when it is allowed to enroll. Raising there empties the dropdown and
        blocks enrollment outright, so the failure degrades to
        ``KEYFACTOR_DEFAULT_CA`` and the entry is tagged
        ``source="configured-default"`` for the UI to explain itself.

        ``value`` is what enrollment must send: Keyfactor identifies a CA as
        ``HostName\\LogicalName``, not by its display name.
        """
        raw = await self._list_or_empty(self._client.get_certificate_authorities(), what="authorities")
        authorities = [
            {
                "id": ca.get("Id"),
                "name": ca.get("Name") or ca.get("LogicalName") or "",
                "logical_name": ca.get("LogicalName") or ca.get("Name") or "",
                "host_name": ca.get("HostName") or "",
                "value": _ca_enrollment_value(ca),
                "source": "keyfactor",
            }
            for ca in raw
            if isinstance(ca, dict)
        ]
        return [a for a in authorities if a["value"]] or _configured_default_authorities()

    async def list_enrollment_patterns(self) -> list[dict[str, Any]]:
        """Return enrollment patterns, falling back to ``KEYFACTOR_ENROLLMENT_PATTERNS``."""
        raw = await self._list_or_empty(self._client.get_enrollment_patterns(), what="enrollment_patterns")
        patterns: list[dict[str, Any]] = []
        for p in raw:
            if not isinstance(p, dict) or p.get("Id") is None:
                continue
            template = p.get("Template") if isinstance(p.get("Template"), dict) else {}
            patterns.append(
                {
                    "id": p.get("Id"),
                    "name": p.get("Name") or "",
                    "template_name": template.get("TemplateName") or template.get("CommonName") or "",
                    "source": "keyfactor",
                }
            )
        patterns = patterns or _configured_enrollment_patterns()
        if not patterns:
            return []
        templates = await self._list_or_empty(self._client.get_pfx_enrollment_context(), what="pfx_context")
        return _with_template_policy(patterns, templates)

    async def list_enrollment_metadata_fields(self) -> list[dict[str, Any]]:
        """Metadata fields shown on enrollment, with Keyfactor's allowed options and validation.

        Keyfactor's ``Enrollment`` flag is 0 = optional, 1 = required, 2 = hidden;
        hidden fields are left out.
        """
        raw = await self._list_or_empty(self._client.get_metadata_fields(), what="metadata_fields")
        fields = []
        for f in raw:
            if not isinstance(f, dict) or not f.get("Name") or f.get("Enrollment") == _METADATA_HIDDEN:
                continue
            options = [o.strip() for o in str(f.get("Options") or "").split(",") if o.strip()]
            fields.append(
                {
                    "name": str(f["Name"]),
                    "data_type": _METADATA_TYPES.get(f.get("DataType"), "string"),
                    "options": options,
                    "hint": f.get("Hint") or "",
                    "validation": f.get("Validation") or "",
                    "default_value": f.get("DefaultValue") or "",
                    "required": f.get("Enrollment") == _METADATA_REQUIRED,
                }
            )
        # Required first, keeping Keyfactor's order within each group.
        return sorted(fields, key=lambda f: not f["required"])

    async def _list_or_empty(self, coro: Awaitable[list[dict[str, Any]]], *, what: str) -> list[dict[str, Any]]:
        """Run a Keyfactor list call, returning ``[]`` instead of raising."""
        try:
            return await self._guard(coro)
        except CertificateServiceError as exc:
            logger.warning("keyfactor_enrollment_list_unavailable", what=what, detail=exc.message)
            return []

    # -- helpers --------------------------------------------------------

    @staticmethod
    def _shape_enrollment(result: dict[str, Any], *, pfx: bool = False) -> dict[str, Any]:
        """Return a safe enrollment result.

        The PFX/private-key blob is passed through once for the caller to stream
        to the user. It is never logged or persisted.
        """
        inner = result.get("CertificateInformation") or result
        shaped: dict[str, Any] = {
            "serial_number": inner.get("SerialNumber"),
            "thumbprint": inner.get("Thumbprint"),
            "certificate_id": _first_present(inner, "KeyfactorID", "KeyfactorId", "CertificateId", "Id"),
            "certificate_ids": _first_present(inner, "KeyfactorIDs", "KeyfactorIds"),
            "issuer_dn": inner.get("IssuerDN"),
        }
        # Enrollment returns the signed certificate(s) / chain — pass through.
        for key in ("Certificates", "Certificate", "Pkcs12Blob", "PKCS12"):
            if inner.get(key) is not None:
                shaped["certificate" if key in ("Certificate",) else key.lower()] = inner.get(key)
        if pfx and inner.get("Pkcs12Blob") is not None:
            shaped["pfx_base64"] = inner.get("Pkcs12Blob")
        return shaped


def _demo_certificate_list(page: int, page_size: int) -> dict[str, Any]:
    """Return synthetic certificate data for local development."""
    now = datetime.now(UTC)
    items = [
        {
            "id": 1001,
            "common_name": "app.dev.att.com",
            "subject_dn": "CN=app.dev.att.com,O=AT&T,L=Dallas,ST=TX,C=US",
            "issuer_dn": "CN=AT&T Internal CA,O=AT&T",
            "serial_number": "4A:3B:2C:1D:00:FF:EE:DD",
            "thumbprint": "A1B2C3D4E5F6789012345678ABCDEF0123456789",
            "template": "WebServer",
            "certificate_authority": "AT&T-Internal-CA",
            "not_before": (now - timedelta(days=30)).isoformat(),
            "not_after": (now + timedelta(days=335)).isoformat(),
            "sans": ["app.dev.att.com", "app-internal.dev.att.com"],
            "revoked": False,
            "revocation_reason": None,
            "status": "valid",
            "metadata": {},
        },
        {
            "id": 1002,
            "common_name": "api.staging.att.com",
            "subject_dn": "CN=api.staging.att.com,O=AT&T,L=Dallas,ST=TX,C=US",
            "issuer_dn": "CN=AT&T Internal CA,O=AT&T",
            "serial_number": "5B:4C:3D:2E:11:AA:BB:CC",
            "thumbprint": "B2C3D4E5F6A789012345678ABCDEF01234567890",
            "template": "WebServer",
            "certificate_authority": "AT&T-Internal-CA",
            "not_before": (now - timedelta(days=300)).isoformat(),
            "not_after": (now + timedelta(days=20)).isoformat(),
            "sans": ["api.staging.att.com"],
            "revoked": False,
            "revocation_reason": None,
            "status": "expiring_soon",
            "metadata": {},
        },
        {
            "id": 1003,
            "common_name": "legacy.att.com",
            "subject_dn": "CN=legacy.att.com,O=AT&T,L=Dallas,ST=TX,C=US",
            "issuer_dn": "CN=AT&T Internal CA,O=AT&T",
            "serial_number": "6C:5D:4E:3F:22:99:88:77",
            "thumbprint": "C3D4E5F6A7B89012345678ABCDEF012345678901",
            "template": "InternalServer",
            "certificate_authority": "AT&T-Internal-CA",
            "not_before": (now - timedelta(days=400)).isoformat(),
            "not_after": (now - timedelta(days=35)).isoformat(),
            "sans": ["legacy.att.com"],
            "revoked": False,
            "revocation_reason": None,
            "status": "expired",
            "metadata": {},
        },
        {
            "id": 1004,
            "common_name": "compromised.att.com",
            "subject_dn": "CN=compromised.att.com,O=AT&T,L=Dallas,ST=TX,C=US",
            "issuer_dn": "CN=AT&T Internal CA,O=AT&T",
            "serial_number": "7D:6E:5F:4A:33:66:55:44",
            "thumbprint": "D4E5F6A7B8C9012345678ABCDEF0123456789012",
            "template": "WebServer",
            "certificate_authority": "AT&T-Internal-CA",
            "not_before": (now - timedelta(days=200)).isoformat(),
            "not_after": (now + timedelta(days=165)).isoformat(),
            "sans": ["compromised.att.com"],
            "revoked": True,
            "revocation_reason": "keyCompromise",
            "status": "revoked",
            "metadata": {},
        },
    ]
    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "total": total,
        "page": page,
        "page_size": page_size,
    }


def _demo_certificate_detail(certificate_id: int) -> dict[str, Any]:
    """Return a single demo certificate for local development."""
    result = _demo_certificate_list(1, 100)
    for item in result["items"]:
        if item["id"] == certificate_id:
            return item
    return result["items"][0] | {"id": certificate_id}


def _demo_collections() -> list[dict[str, Any]]:
    """Demo certificate collections matching the Keyfactor Collection Manager."""
    return [
        {
            "id": 1,
            "name": "AP-KF-ATTCC-31599",
            "description": "ATTCC application certificates",
            "certificate_count": 28,
        },
        {"id": 2, "name": "_Acme_Metadata", "description": "ACME Metadata certificates", "certificate_count": 0},
        {"id": 3, "name": "_Akamai_Metadata", "description": "Akamai metadata certificates", "certificate_count": 0},
        {"id": 4, "name": "_Akamai_renewals", "description": "Akamai renewal certificates", "certificate_count": 20},
        {
            "id": 5,
            "name": "_Auto-Renewal",
            "description": "Auto-renewal eligible certificates",
            "certificate_count": 6930,
        },
        {"id": 6, "name": "_Auto-Renewal Failure", "description": "Auto-renewal failures", "certificate_count": 8},
        {"id": 7, "name": "_Auto-Renewal-2048", "description": "2048-bit auto-renewal certs", "certificate_count": 158},
        {
            "id": 8,
            "name": "_DigiCert_Upload",
            "description": "DigiCert uploaded certificates",
            "certificate_count": 48764,
        },
        {"id": 9, "name": "_Owner_Populate", "description": "Owner population collection", "certificate_count": 166},
        {"id": 10, "name": "_OwnerRole_Validation", "description": "Owner role validation", "certificate_count": 1},
        {
            "id": 11,
            "name": "_RSA 2048 Active Certificates",
            "description": "Active RSA 2048 certificates",
            "certificate_count": 2037,
        },
        {
            "id": 12,
            "name": "_temp certificate cleanup",
            "description": "Temp certificate cleanup",
            "certificate_count": 0,
        },
        {"id": 13, "name": "AP-KF-ACNR-22622", "description": "ACNR application certificates", "certificate_count": 15},
        {
            "id": 14,
            "name": "AP-KF-MOBILITY-40100",
            "description": "Mobility application certificates",
            "certificate_count": 42,
        },
        {
            "id": 15,
            "name": "AP-KF-NETWORK-35001",
            "description": "Network services certificates",
            "certificate_count": 87,
        },
        {"id": 16, "name": "AP-KF-CLOUD-28500", "description": "Cloud platform certificates", "certificate_count": 234},
        {
            "id": 17,
            "name": "AP-KF-SECURITY-19000",
            "description": "Security team certificates",
            "certificate_count": 56,
        },
    ]


def _demo_templates() -> list[dict[str, Any]]:
    """Demo enrollment templates."""
    return [
        {
            "id": 1,
            "common_name": "Digicert-Standard-SHA2-4096Key",
            "template_name": "Digicert-Standard-SHA2-4096Key",
            "oid": "1.2.3.4.5.6.7.8.1",
            "key_size": "4096",
            "key_type": "RSA",
        },
        {
            "id": 2,
            "common_name": "Digicert-Standard-SHA2-2048Key",
            "template_name": "Digicert-Standard-SHA2-2048Key",
            "oid": "1.2.3.4.5.6.7.8.2",
            "key_size": "2048",
            "key_type": "RSA",
        },
        {
            "id": 3,
            "common_name": "InternalServer-SHA2-4096",
            "template_name": "InternalServer-SHA2-4096",
            "oid": "1.2.3.4.5.6.7.8.3",
            "key_size": "4096",
            "key_type": "RSA",
        },
        {
            "id": 4,
            "common_name": "Wildcard-SHA2-4096Key",
            "template_name": "Wildcard-SHA2-4096Key",
            "oid": "1.2.3.4.5.6.7.8.4",
            "key_size": "4096",
            "key_type": "RSA",
        },
        {
            "id": 5,
            "common_name": "CodeSigning-SHA2",
            "template_name": "CodeSigning-SHA2",
            "oid": "1.2.3.4.5.6.7.8.5",
            "key_size": "4096",
            "key_type": "RSA",
        },
    ]


def _demo_certificate_authorities() -> list[dict[str, Any]]:
    """Demo CAs."""
    return [
        {"id": 1, "name": "DigiCert Global G2 TLS RSA SHA256 2020 CA1", "host_name": "digicert-ca.att.com"},
        {"id": 2, "name": "AT&T Internal CA G2", "host_name": "internal-ca.att.com"},
        {"id": 3, "name": "AT&T Services SHA256 CA", "host_name": "services-ca.att.com"},
    ]
