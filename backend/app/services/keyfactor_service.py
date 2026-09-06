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

from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import Any, TypeVar

import structlog

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
    state = (cert.get("CertStateString") or cert.get("CertState") or "").__str__().lower()
    revocation_reason = cert.get("RevocationReason")
    revoked = state == "revoked" or (revocation_reason not in (None, "", 0) and state != "active")

    not_before = _parse_dt(cert.get("NotBefore"))
    not_after = _parse_dt(cert.get("NotAfter"))
    import_date = _parse_dt(cert.get("ImportDate"))
    effective_date = _parse_dt(cert.get("EffectiveDate") or cert.get("NotBefore"))

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
        "sans": _extract_sans(cert),
        "san_count": len(_extract_sans(cert)),
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

    async def get_certificate(self, certificate_id: int) -> dict[str, Any]:
        cert = await self._guard(self._client.get_certificate(certificate_id))
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
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "CSR": csr,
            "CertificateAuthority": certificate_authority,
            "Template": template,
            "IncludeChain": include_chain,
            "Timestamp": datetime.now(UTC).isoformat(),
        }
        if sans:
            payload["SANs"] = sans
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
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "Subject": subject,
            "CertificateAuthority": certificate_authority,
            "Template": template,
            "Password": password,
            "KeyType": key_type,
            "KeyLength": key_length,
            "IncludeChain": include_chain,
            "Timestamp": datetime.now(UTC).isoformat(),
        }
        if sans:
            payload["SANs"] = sans
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
            result = await self._guard(self._client.enroll_pfx(pfx_payload, replace_existing=True))
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
    ) -> dict[str, Any]:
        if reason not in REVOCATION_REASONS:
            raise CertificateServiceError(
                f"Invalid revocation reason '{reason}'. Allowed: {', '.join(REVOCATION_REASONS)}.",
                status_code=422,
            )
        payload: dict[str, Any] = {
            "CertificateIds": [certificate_id],
            "Reason": REVOCATION_REASONS[reason],
            "Comment": comment,
            "EffectiveDate": (effective_date or datetime.now(UTC)).isoformat(),
        }
        if collection_id is not None:
            payload["CollectionId"] = collection_id
        await self._guard(self._client.revoke_certificate(payload, collection_id=collection_id))
        return {"certificate_id": certificate_id, "reason": reason, "revoked": True}

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
        """Return enrollment templates."""
        raw = await self._guard(self._client.get_enrollment_templates())
        return [
            {
                "id": t.get("Id"),
                "common_name": t.get("CommonName") or t.get("Name") or "",
                "template_name": t.get("TemplateName") or t.get("Name") or "",
                "oid": t.get("Oid") or "",
                "key_size": t.get("KeySize") or "",
                "key_type": t.get("KeyType") or "",
            }
            for t in raw
            if isinstance(t, dict)
        ]

    async def list_certificate_authorities(self) -> list[dict[str, Any]]:
        """Return available CAs."""
        raw = await self._guard(self._client.get_certificate_authorities())
        return [
            {
                "id": ca.get("Id"),
                "name": ca.get("Name") or ca.get("LogicalName") or "",
                "host_name": ca.get("HostName") or "",
            }
            for ca in raw
            if isinstance(ca, dict)
        ]

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
            "certificate_id": inner.get("KeyfactorId") or inner.get("Id"),
            "certificate_ids": inner.get("KeyfactorIDs"),
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
