"""
Certificate Management API endpoints (Keyfactor Command integration).

Exposes the full certificate lifecycle — list/search, view, enroll (CSR & PFX),
renew, revoke, update metadata, and delete — backed by the Keyfactor Command
REST API.

RBAC:
- Read (list/view): any authenticated user with view access to the page.
- Enroll / renew / update metadata: WRITE role.
- Revoke / delete (destructive): ADMIN role.

Every write operation is recorded in the shared ``audit_logs`` table. Secrets,
private keys, and PFX material are never logged.
"""

from __future__ import annotations

import asyncio
import contextlib
from datetime import datetime
from typing import Any, Literal, NoReturn

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.core.config import settings
from app.core.database import get_db, get_db_session
from app.models.auth import UserContext, UserRole
from app.models.database import AuditLog, CertificateSnapshot
from app.services.certificate_escrow_service import CertificateEscrowService
from app.services.certificate_sync_service import CertificateSyncService
from app.services.keyfactor_client import REVOCATION_REASONS
from app.services.keyfactor_service import CertificateService, CertificateServiceError

logger = structlog.get_logger(__name__)
router = APIRouter()

# Keyfactor's ``CertState`` field is a numeric enum; the query API rejects state
# names (e.g. ``CertState -eq "Revoked"`` → "Invalid CertState value: Revoked.").
# Map the names we accept to their numeric value. Date-derived statuses
# (valid / expiring_soon / expired) are not Keyfactor states and are handled via
# the DB cache or ExpirationDate filters, so they are intentionally omitted.
_CERT_STATE_VALUES: dict[str, int] = {
    "unknown": 0,
    "active": 1,
    "revoked": 2,
    "denied": 3,
    "failed": 4,
    "pending": 5,
}


def _cert_state_clause(cert_status: str) -> str | None:
    """Build a numeric Keyfactor ``CertState`` filter clause, or None if the
    status is not a real Keyfactor state (so we never send an invalid query)."""
    value = _CERT_STATE_VALUES.get(cert_status.strip().lower())
    return f'CertState -eq "{value}"' if value is not None else None


def _get_service() -> CertificateService:
    return CertificateService()


async def _bg_sync(collection_id: int | None, *, triggered_by: str, skip_if_running: bool) -> None:
    """Background cache refresh so DB reads stay in sync after mutations/misses."""
    try:
        async for db in get_db_session():
            svc = CertificateSyncService(db)
            if skip_if_running and await svc.is_sync_running():
                return
            if collection_id is not None:
                await svc.sync_collection(collection_id, triggered_by=triggered_by)
            else:
                await svc.full_sync(triggered_by=triggered_by)
    except Exception as exc:  # pragma: no cover - best-effort cache refresh
        logger.warning("cert_bg_sync_failed", collection_id=collection_id, error=str(exc)[:200])


def _schedule_sync(collection_id: int | None, *, triggered_by: str = "mutation", skip_if_running: bool = False) -> None:
    """Fire-and-forget cache refresh; never blocks the request."""
    if settings.ENVIRONMENT == "test":
        return
    with contextlib.suppress(RuntimeError):  # no running event loop
        asyncio.create_task(_bg_sync(collection_id, triggered_by=triggered_by, skip_if_running=skip_if_running))


# ── Request models ─────────────────────────────────────────────────────


class EnrollRequest(BaseModel):
    """Enroll a new certificate via CSR or PFX enrollment."""

    enrollment_type: str = Field(..., description="'csr' or 'pfx'")
    certificate_authority: str = Field(..., min_length=1)
    template: str = Field(..., min_length=1)
    include_chain: bool = Field(default=True)
    sans: dict[str, list[str]] | None = Field(
        default=None,
        description="Subject alternative names keyed by type, e.g. {'dns': ['a.example.com']}",
    )
    metadata: dict[str, Any] | None = None

    # CSR enrollment
    csr: str | None = Field(default=None, description="PEM-encoded CSR (required for csr enrollment)")

    # PFX enrollment fields (matching Keyfactor PFX Enrollment form)
    subject: str | None = Field(default=None, description="Subject DN (required for pfx enrollment)")
    password: str | None = Field(default=None, description="PFX password (min 12 chars for pfx enrollment)")
    key_type: str = Field(default="RSA")
    key_length: int = Field(default=4096, ge=2048, le=8192)

    # Subject information fields (PFX enrollment)
    common_name: str | None = Field(default=None, description="Common Name (CN)")
    organization: str | None = Field(default=None, description="Organization (O)")
    organizational_unit: str | None = Field(default=None, description="Organizational Unit (OU)")
    city: str | None = Field(default=None, description="City / Locality (L)")
    state: str | None = Field(default=None, description="State / Province (ST)")
    country: str | None = Field(default=None, description="Country (C)")
    email: str | None = Field(default=None, description="Email address")
    custom_friendly_name: str | None = None

    # AT&T-specific certificate metadata (required by Keyfactor templates)
    mots_profile_id: str | None = Field(default=None, description="MOTS Profile ID or iTap number")
    requester_att_user_id: str | None = Field(default=None, description="AT&T User ID of requester")
    requester_att_manager_user_id: str | None = Field(default=None, description="Manager AT&T User ID")
    server_type: str | None = Field(default=None, description="Server type (e.g. Linux, Windows)")
    environment: str | None = Field(default=None, description="Environment (e.g. Production, Dev)")
    tls_port_services_internet_traffic: str | None = Field(
        default=None, description="TLS port/services internet traffic"
    )
    port: str | None = Field(default=None, description="Port(s) the certificate is bound to")
    pci_data: str | None = Field(default=None, description="Handles PCI data? (Yes/No)")

    # Delivery & ownership
    owner_role_name: str | None = None
    delivery_format: str = Field(default="PFX", description="PFX, PEM, etc.")
    use_legacy_encryption: bool = Field(default=True)

    @field_validator("enrollment_type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        if v not in ("csr", "pfx"):
            raise ValueError("enrollment_type must be 'csr' or 'pfx'")
        return v


class RenewRequest(BaseModel):
    mode: str = Field(default="one_click", description="'one_click', 'pfx', or 'csr'")
    certificate_authority: str | None = None
    template: str | None = None
    collection_id: int | None = Field(default=None, description="Collection context for the renewal")
    # PFX renewal fields
    password: str | None = None
    key_type: str | None = None
    key_length: int | None = None
    owner_role_name: str | None = None
    # CSR renewal field
    csr: str | None = None

    @field_validator("mode")
    @classmethod
    def _valid_mode(cls, v: str) -> str:
        if v not in ("one_click", "pfx", "csr"):
            raise ValueError("mode must be 'one_click', 'pfx', or 'csr'")
        return v

    @model_validator(mode="after")
    def _validate_mode_fields(self) -> RenewRequest:
        if self.mode == "pfx" and (not self.password or len(self.password.strip()) < 12):
            raise ValueError("password must contain at least 12 non-blank characters for PFX renewal")
        if self.mode == "csr" and not (self.csr and self.csr.strip()):
            raise ValueError("csr is required for CSR renewal")
        return self


# Formats that carry the private key and therefore need a keystore password and
# the WRITE role. JKS is built by the portal: Keyfactor has no JKS export.
_KEYSTORE_FORMATS = frozenset({"PFX", "JKS"})


class DownloadRequest(BaseModel):
    file_format: str = Field(default="PEM", description="PEM, CER, CRT, DER, P7B, PFX, or JKS")
    include_chain: bool = Field(default=True)
    chain_order: str = Field(default="EndEntityFirst", description="EndEntityFirst or RootFirst")
    include_subject_header: bool = Field(default=True)
    collection_id: int | None = Field(default=None, description="Collection context for the download")
    pfx_password: str | None = Field(
        default=None,
        description=(
            "Keystore password (min 12 chars) for the PFX and JKS formats. For JKS it "
            "protects both the keystore integrity check and the private-key entry."
        ),
    )
    jks_alias: str | None = Field(
        default=None,
        max_length=255,
        description=(
            "Entry alias for JKS downloads. Defaults to the certificate's common name. "
            "Java lowercases JKS aliases, so the value is normalized."
        ),
    )

    @model_validator(mode="after")
    def _validate_pfx_password(self) -> DownloadRequest:
        if self.file_format.upper() in _KEYSTORE_FORMATS and (
            not self.pfx_password or len(self.pfx_password.strip()) < 12
        ):
            raise ValueError(
                f"pfx_password must contain at least 12 non-blank characters for {self.file_format.upper()} download"
            )
        return self


class LoadToAkvRequest(BaseModel):
    """Load a certificate into Azure Key Vault after renewal or standalone."""

    subscription_id: str = Field(..., min_length=1, description="Azure Subscription ID")
    resource_group: str = Field(..., min_length=1, description="Resource group containing the Key Vault")
    vault_name: str = Field(..., min_length=1, description="Key Vault name")
    certificate_names: list[str] = Field(
        ...,
        min_length=1,
        description=(
            "Key Vault certificate names to import into. A multi-SAN certificate is often stored "
            "under one name per SAN, and the PFX exists only once, so every target is imported "
            "from the same key material in a single call."
        ),
    )
    certificate_data: str | None = Field(
        default=None,
        description=(
            "Base64-encoded PFX or PEM certificate data. Omit it to have the portal export the "
            "certificate's PFX (certificate + private key) from Keyfactor."
        ),
    )
    certificate_password: str | None = Field(
        default=None,
        description="Password for PFX data; never logged",
    )
    collection_id: int | None = Field(
        default=None,
        description="Collection context used when exporting the PFX from Keyfactor",
    )
    key_source: Literal["auto", "escrow", "keyfactor"] = Field(
        default="auto",
        description=(
            "Where the private key comes from when certificate_data is omitted. "
            "'auto' prefers the escrowed key and falls back to a live Keyfactor "
            "export; 'escrow' fails rather than falling back; 'keyfactor' skips escrow."
        ),
    )

    @field_validator("certificate_names")
    @classmethod
    def _valid_cert_names(cls, v: list[str]) -> list[str]:
        import re

        cleaned: list[str] = []
        for name in v:
            name = name.strip()
            if not (1 <= len(name) <= 127) or not re.match(r"^[a-zA-Z0-9-]+$", name):
                raise ValueError("certificate names must be 1-127 alphanumeric characters or hyphens")
            if name not in cleaned:
                cleaned.append(name)
        if not cleaned:
            raise ValueError("at least one certificate name is required")
        return cleaned


class RevokeRequest(BaseModel):
    reason: str = Field(..., description=f"One of: {', '.join(REVOCATION_REASONS)}")
    comment: str = Field(
        default="",
        max_length=1000,
        description=(
            "Optional. Keyfactor requires a non-empty revocation comment, so when this "
            "is blank the portal records who revoked the certificate and why."
        ),
    )
    effective_date: datetime | None = None
    collection_id: int | None = Field(default=None, description="Collection context for the operation")

    @field_validator("reason")
    @classmethod
    def _valid_reason(cls, v: str) -> str:
        if v not in REVOCATION_REASONS:
            raise ValueError(f"reason must be one of: {', '.join(REVOCATION_REASONS)}")
        return v


class UpdateMetadataRequest(BaseModel):
    metadata: dict[str, Any] = Field(..., description="Metadata / custom fields to update")

    @field_validator("metadata")
    @classmethod
    def _non_empty(cls, v: dict[str, Any]) -> dict[str, Any]:
        if not v:
            raise ValueError("metadata must contain at least one field")
        return v


# ── Helpers ────────────────────────────────────────────────────────────


def _raise_http(exc: CertificateServiceError) -> NoReturn:
    """Translate a domain error to a sanitized HTTP response."""
    code = exc.status_code
    message = exc.message or ""
    if "suspended workflow" in message.lower():
        # A previous renewal attempt left a pending (suspended) Keyfactor workflow
        # on this certificate, which blocks new renewal requests until resolved.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This certificate already has a pending renewal awaiting completion in "
                "Keyfactor Command. Resolve or cancel the existing renewal workflow before "
                f"starting a new one. Keyfactor reported: {message}"
            ),
        )
    if code == 404:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=exc.message)
    if code in (400, 422):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=exc.message)
    if code in (401, 403):
        # Keyfactor rejected the portal's service account (not the end user) —
        # its Keyfactor security role is missing a permission this operation
        # needs (e.g. certificate-collection read for download/renew). Surface
        # an actionable message so an admin fixes the Keyfactor role, instead of
        # a bare "service unavailable".
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=(
                "The certificate service account is missing a required Keyfactor permission "
                "for this operation. Ask a Keyfactor administrator to grant the portal's "
                "service role the needed access (e.g. certificate-collection read). "
                f"Keyfactor reported: {exc.message}"
            ),
        )
    # Other upstream failures (5xx / unexpected) → bad gateway.
    raise HTTPException(
        status_code=status.HTTP_502_BAD_GATEWAY,
        detail=exc.message or "Certificate service is unavailable. Please try again later.",
    )


async def _write_audit(
    db: AsyncSession,
    *,
    request: Request,
    user: UserContext,
    action: str,
    resource_id: str,
    summary: str,
    outcome: str,
    details: dict[str, Any],
) -> None:
    """Write a certificate audit row. Never contains secrets or key material."""
    try:
        entry = AuditLog(
            user_id=user.user_id,
            user_email=user.email,
            action=action,
            resource_type="certificate",
            resource_id=resource_id,
            details={
                "page": "CertificatesPage",
                "feature": "certificate_management",
                "summary": summary,
                **details,
            },
            ip_address=request.client.host if request.client else None,
            status=outcome,
        )
        db.add(entry)
        await db.commit()
    except Exception as exc:  # pragma: no cover - audit must never break the op
        await db.rollback()
        logger.warning("certificate_audit_log_failed", action=action, error=str(exc)[:200])


async def _cert_identity(db: AsyncSession, certificate_id: int | str) -> tuple[str, str | None]:
    """Return ``(label, common_name)`` for audit text.

    A bare Keyfactor id ("Revoked certificate 31069046") does not tell anyone
    which certificate was touched, so the common name is resolved from the
    cached snapshot and the label reads
    ``cesdataroutergears.dev.att.com (31069046)``. Falls back to the bare id
    when the certificate is not cached, so auditing never depends on the cache
    being warm.
    """
    label = str(certificate_id)
    if db is None:
        return label, None
    try:
        cert_id = int(certificate_id)
    except (TypeError, ValueError):
        return label, None
    try:
        result = await db.execute(
            select(CertificateSnapshot.common_name)
            .where(CertificateSnapshot.certificate_id == cert_id)
            .where(CertificateSnapshot.common_name.isnot(None))
            .limit(1)
        )
        common_name = result.scalar_one_or_none()
    except Exception as exc:  # pragma: no cover - audit text must never fail an op
        logger.warning("cert_identity_lookup_failed", certificate_id=cert_id, error=str(exc)[:200])
        return label, None
    if not common_name:
        return label, None
    return f"{common_name} ({cert_id})", common_name


async def _escrow_issued_key(
    db: AsyncSession,
    *,
    request: Request,
    user: UserContext,
    result: dict[str, Any],
    password: str | None,
    source: str,
    common_name: str | None,
) -> None:
    """Capture issuance-time PFX material into the escrow Key Vault.

    Keyfactor hands over the PFX only in the enrollment/renewal response, so
    this is the one chance to keep it. Best-effort by design: the certificate
    has already been issued by the time this runs, so an escrow failure must
    never turn a successful enrollment into an error — it downgrades to a
    warning and the certificate simply stays un-escrowed.

    The audit row records the vault pointer only, never the PFX or password.
    """
    if db is None or not CertificateEscrowService.is_enabled():
        return
    pfx_base64 = result.get("pfx_base64")
    thumbprint = result.get("thumbprint")
    if not pfx_base64 or not thumbprint:
        return

    try:
        pointer = await CertificateEscrowService(db).escrow(
            certificate_id=result.get("certificate_id"),
            thumbprint=str(thumbprint),
            common_name=common_name,
            pfx_base64=str(pfx_base64),
            password=password,
            source=source,
            actor=user.email or user.user_id,
        )
    except Exception as exc:  # pragma: no cover - escrow must never break issuance
        logger.warning("cert_escrow_hook_failed", source=source, error=str(exc)[:200])
        return
    if pointer is None:
        return

    result["key_escrowed"] = True
    await _write_audit(
        db,
        request=request,
        user=user,
        action="cert_key_escrow",
        resource_id=str(result.get("certificate_id") or thumbprint),
        summary=(
            f"Escrowed private key for {common_name or thumbprint} ({result.get('certificate_id') or 'new'}, {source})"
        ),
        outcome="success",
        details={
            "common_name": common_name,
            "vault_name": pointer["vault_name"],
            "secret_name": pointer["secret_name"],
            "thumbprint": pointer["thumbprint"],
            "source": source,
        },
        # Never log pfx_base64 or the PFX password
    )


async def _build_jks(
    *,
    service: CertificateService,
    db: AsyncSession,
    certificate_id: int,
    payload: DownloadRequest,
) -> tuple[bytes, str]:
    """Build a JKS keystore for a certificate, returning ``(bytes, key_source)``.

    Keyfactor cannot emit JKS, so PFX material is obtained first — from a live
    export under a throwaway transit password, or from the escrowed key — and
    converted locally. The transit password never leaves this function: the
    keystore the caller receives is protected by the password on their request.
    """
    import secrets

    from app.services.keystore_service import pfx_to_jks

    store_password = (payload.pfx_password or "").strip()
    upstream_error: str | None = None
    pfx_bytes: bytes | None = None
    pfx_password = ""
    key_source = "keyfactor"

    transit_password = secrets.token_urlsafe(24)
    try:
        pfx_bytes = await service.download_certificate(
            certificate_id,
            file_format="PFX",
            include_chain=payload.include_chain,
            chain_order=payload.chain_order,
            collection_id=payload.collection_id,
            pfx_password=transit_password,
        )
        pfx_password = transit_password
    except CertificateServiceError as exc:
        upstream_error = exc.message

    if pfx_bytes is None and db is not None:
        try:
            material = await CertificateEscrowService(db).get_material(certificate_id=certificate_id)
        except Exception as exc:  # pragma: no cover - fall through to the 409 below
            logger.warning(
                "cert_escrow_jks_lookup_failed",
                certificate_id=certificate_id,
                error=str(exc)[:200],
            )
            material = None
        if material is not None:
            pfx_bytes, pfx_password = material
            key_source = "escrow"

    if pfx_bytes is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "A JKS keystore needs the certificate's private key, which could not be "
                f"exported from Keyfactor ({upstream_error or 'no key available'}) and is not "
                "escrowed. Keyfactor returns the key only at the moment of issuance unless key "
                "archival is enabled on the template. Renew this certificate through the portal "
                "to escrow its key, after which JKS download works at any time."
            ),
        )

    try:
        content = pfx_to_jks(
            pfx_bytes,
            pfx_password=pfx_password,
            store_password=store_password,
            alias=payload.jks_alias,
            include_chain=payload.include_chain,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Could not build a JKS keystore for this certificate: {exc}",
        )
    return content, key_source


async def _decorate_escrow_status(db: AsyncSession, result: dict[str, Any]) -> dict[str, Any]:
    """Tag listed certificates with whether their private key is escrowed.

    The flag is attached only when escrow is configured, so a deployment
    without escrow shows no misleading "not escrowed" state in the grid.
    Decorates the item dicts in place — both callers build them per request.
    """
    items = result.get("items")
    if db is None or not isinstance(items, list) or not items or not CertificateEscrowService.is_enabled():
        return result
    try:
        escrowed = await CertificateEscrowService(db).escrowed_thumbprints(
            [str(i.get("thumbprint") or "") for i in items if isinstance(i, dict)]
        )
    except Exception as exc:  # pragma: no cover - status is advisory
        logger.warning("cert_escrow_status_failed", error=str(exc)[:200])
        return result
    for item in items:
        if isinstance(item, dict):
            item["key_escrowed"] = str(item.get("thumbprint") or "").strip().lower() in escrowed
    return result


# ── Read endpoints ─────────────────────────────────────────────────────


@router.get("")
async def list_certificates(
    q: str | None = Query(default=None, description="Keyfactor query string filter"),
    cn: str | None = Query(default=None, description="Filter by common name (contains)"),
    thumbprint: str | None = Query(default=None, description="Filter by thumbprint"),
    issuer: str | None = Query(default=None, description="Filter by issuer (contains)"),
    cert_status: str | None = Query(default=None, description="Keyfactor cert state, e.g. 'Active'"),
    collection_id: int | None = Query(default=None, description="Filter by collection ID"),
    expires_in_days: int | None = Query(default=None, ge=0, le=3650),
    deleted_only: bool = Query(
        default=False, description="Return only soft-deleted certificates (portal deletions + Keyfactor orphans)"
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    refresh: bool = Query(default=False, description="Bypass the DB cache and fetch live from Keyfactor"),
    user: UserContext = Depends(get_current_user),
    service: CertificateService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Paginated, filterable certificate list (served from the DB cache when available).

    By default returns only *active* certificates — neither revoked nor
    soft-deleted. Pass ``cert_status=revoked`` to see revoked ones, or
    ``deleted_only=true`` for soft-deleted certificates — those removed from
    Keyfactor since the last sync, or explicitly deleted via the portal.
    Deleted certificates are only available via the DB cache; the live
    Keyfactor path is skipped when ``deleted_only=true``.
    """
    # DB-first fast path: serve the cached snapshot for this collection.
    # ``deleted_only`` always uses the DB cache (no Keyfactor equivalent).
    if (not refresh or deleted_only) and collection_id is not None and db is not None:
        try:
            sync_service = CertificateSyncService(db)
            # ``deleted_only`` skips the has_certificates gate: an empty deleted
            # set must return an empty list, not fall through to Keyfactor and
            # answer "show me deleted certs" with every active one.
            if deleted_only or await sync_service.has_certificates(collection_id):
                cached = await sync_service.list_certificates_from_db(
                    collection_id=collection_id,
                    cn=cn,
                    thumbprint=thumbprint,
                    issuer=issuer,
                    cert_status=cert_status,
                    expires_in_days=expires_in_days,
                    deleted_only=deleted_only,
                    page=page,
                    page_size=page_size,
                )
                return await _decorate_escrow_status(db, cached)
        except Exception as exc:
            logger.warning("cert_list_db_fallback", error=str(exc)[:200])
            # Falling back to Keyfactor here would return active certificates
            # under the "Deleted" banner, which reads as mass deletion. The
            # deleted view is DB-only, so surface the failure instead.
            if deleted_only:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="The deleted-certificate view is unavailable because the local cache "
                    "could not be read. Check that the cert_certificates migrations have been applied.",
                ) from exc

    clauses: list[str] = []
    if cn:
        clauses.append(f'CN -contains "{_sanitize(cn)}"')
    if thumbprint:
        clauses.append(f'Thumbprint -eq "{_sanitize(thumbprint)}"')
    if issuer:
        clauses.append(f'IssuerDN -contains "{_sanitize(issuer)}"')
    if cert_status:
        state_clause = _cert_state_clause(cert_status)
        if state_clause:
            clauses.append(state_clause)
    if expires_in_days is not None:
        from datetime import timedelta

        expiry_date = (datetime.utcnow() + timedelta(days=expires_in_days)).strftime("%Y-%m-%dT%H:%M:%SZ")
        clauses.append(f'ExpirationDate -le "{expiry_date}"')
    if q:
        clauses.append(f"({_sanitize(q)})")
    query = " AND ".join(clauses) if clauses else None

    try:
        result = await service.list_certificates(
            query=query, page=page, page_size=page_size, collection_id=collection_id
        )
    except CertificateServiceError as exc:
        _raise_http(exc)

    # Lazy-populate the cache so the next load of this collection is instant.
    if collection_id is not None and db is not None:
        _schedule_sync(collection_id, triggered_by="lazy", skip_if_running=True)
    return await _decorate_escrow_status(db, result)


# ── Reference data endpoints (must precede /{certificate_id} to avoid path collision) ──


class EnabledCollectionsRequest(BaseModel):
    """Admin request to set which collections are visible in the certificate module."""

    collection_ids: list[int] = Field(..., description="List of enabled collection IDs")


@router.get("/collections/enabled")
async def get_enabled_collections(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get the list of enabled collection IDs (admin config)."""
    ids = await _get_enabled_collection_ids(db)
    return {"collection_ids": ids or [], "mode": "selected" if ids else "all"}


@router.put("/collections/enabled")
async def set_enabled_collections(
    payload: EnabledCollectionsRequest,
    request: Request,
    user: UserContext = Depends(require_role(UserRole.ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Admin: Set which collections are visible in the certificate module."""
    entry = AuditLog(
        user_id=user.user_id,
        user_email=user.email,
        action="cert_enabled_collections_config",
        resource_type="certificate_config",
        resource_id="enabled_collections",
        details={
            "page": "AdminDashboard",
            "feature": "certificate_collections",
            "collection_ids": payload.collection_ids,
            "summary": f"Enabled {len(payload.collection_ids)} collections for certificate module",
        },
        ip_address=request.client.host if request.client else None,
        status="success",
    )
    db.add(entry)
    await db.commit()
    return {"status": "saved", "collection_ids": payload.collection_ids}


def _filter_enabled_collections(
    collections: list[dict[str, Any]],
    enabled_ids: list[int] | None,
    *,
    include_all: bool,
) -> list[dict[str, Any]]:
    """Apply the admin 'enabled collections' visibility filter.

    Returns every collection when the admin panel asks for the full list
    (``include_all``) or when no restriction is configured (empty ``enabled_ids``);
    otherwise restricts the list to the admin-enabled ids.
    """
    if include_all or not enabled_ids:
        return collections
    enabled = set(enabled_ids)
    return [c for c in collections if c.get("id") in enabled]


async def _get_enabled_collection_ids(db: AsyncSession | None) -> list[int] | None:
    """Return the latest admin-configured enabled collection IDs.

    ``None`` means no restriction is configured (all collections visible);
    otherwise the stored list (which may be empty) is returned.
    """
    if db is None:
        return None
    from sqlalchemy import select

    stmt = (
        select(AuditLog)
        .where(AuditLog.action == "cert_enabled_collections_config")
        .where(AuditLog.resource_type == "certificate_config")
        .order_by(AuditLog.timestamp.desc())
        .limit(1)
    )
    result = await db.execute(stmt)
    entry = result.scalar_one_or_none()
    if entry and isinstance(entry.details, dict):
        return entry.details.get("collection_ids", [])
    return None


@router.get("/collections")
async def list_collections(
    refresh: bool = Query(default=False, description="Bypass the DB cache and fetch live from Keyfactor"),
    include_all: bool = Query(
        default=False,
        description="Return every collection unfiltered (admin panel); ignores the admin-enabled filter",
    ),
    user: UserContext = Depends(get_current_user),
    service: CertificateService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """Return available certificate collections (DB cache first, filtered by admin-enabled set)."""
    all_collections: list[dict[str, Any]] | None = None

    # DB-first: serve cached collections when available.
    if not refresh and db is not None:
        try:
            sync_service = CertificateSyncService(db)
            if await sync_service.has_collections():
                all_collections = await sync_service.list_collections_from_db()
        except Exception as exc:
            logger.warning("cert_collections_db_fallback", error=str(exc)[:200])

    if all_collections is None:
        try:
            all_collections = await service.list_collections()
        except CertificateServiceError as exc:
            _raise_http(exc)

    # The admin panel needs the full, unfiltered list to choose which collections
    # to enable — otherwise it could only ever see the already-enabled ones.
    if include_all:
        return all_collections

    # Otherwise, honor the admin-configured enabled set (if any).
    enabled_ids = await _get_enabled_collection_ids(db)
    return _filter_enabled_collections(all_collections, enabled_ids, include_all=False)


class SyncRequest(BaseModel):
    """Trigger a certificate cache sync (full, or a single collection)."""

    collection_id: int | None = Field(default=None, description="Sync one collection; null = full sync")


@router.post("/sync")
async def trigger_sync(
    payload: SyncRequest | None = None,
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Refresh the certificate cache from Keyfactor (full or single-collection)."""
    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not available.")
    sync_service = CertificateSyncService(db)
    collection_id = payload.collection_id if payload else None
    try:
        if collection_id is not None:
            return await sync_service.sync_collection(collection_id, triggered_by="manual")
        return await sync_service.full_sync(triggered_by="manual")
    except CertificateServiceError as exc:
        _raise_http(exc)


@router.get("/sync/status")
async def get_sync_status(
    limit: int = Query(default=5, ge=1, le=20),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return recent certificate sync jobs and cache counts (collections scoped to the admin-enabled set)."""
    if db is None:
        return {"certificates_in_db": 0, "collections_in_db": 0, "recent_syncs": []}
    sync_service = CertificateSyncService(db)
    enabled_ids = await _get_enabled_collection_ids(db)
    return await sync_service.get_sync_status(limit=limit, enabled_ids=enabled_ids)


@router.get("/templates")
async def list_templates(
    user: UserContext = Depends(get_current_user),
    service: CertificateService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """Return available enrollment templates."""
    try:
        return await service.list_templates()
    except CertificateServiceError as exc:
        _raise_http(exc)


@router.get("/authorities")
async def list_certificate_authorities(
    user: UserContext = Depends(get_current_user),
    service: CertificateService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """Return available certificate authorities."""
    try:
        return await service.list_certificate_authorities()
    except CertificateServiceError as exc:
        _raise_http(exc)


@router.get("/audit-history")
async def get_certificate_audit_history(
    days: int = Query(default=90, ge=1, le=365, description="Number of days of history"),
    limit: int = Query(default=200, ge=1, le=1000, description="Max records to return"),
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Get certificate audit history from the shared audit log."""
    from datetime import timedelta

    from sqlalchemy import desc, select

    if db is None:
        return {"history": [], "count": 0}

    cert_actions = (
        "enroll_certificate",
        "renew_certificate",
        "revoke_certificate",
        "update_certificate_metadata",
        "delete_certificate",
        "download_certificate",
        "cert_auto_renewal_run",
        "cert_alert_run",
        "cert_key_escrow",
        "load_certificate_to_akv",
    )
    since = datetime.utcnow() - timedelta(days=days)

    statement = (
        select(AuditLog)
        .where(AuditLog.action.in_(cert_actions))
        .where(AuditLog.timestamp >= since)
        .order_by(desc(AuditLog.timestamp))
        .limit(limit)
    )

    result = await db.execute(statement)
    entries = result.scalars().all()

    history = [
        {
            "id": entry.id,
            "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
            "action": entry.action,
            "resource_type": entry.resource_type or "certificate",
            "resource_id": entry.resource_id or "",
            "user_id": entry.user_id,
            "user_email": entry.user_email or "",
            "status": entry.status or "success",
            "summary": (entry.details or {}).get("summary", "") if isinstance(entry.details, dict) else "",
            "details": entry.details if isinstance(entry.details, dict) else {},
        }
        for entry in entries
    ]

    return {"history": history, "count": len(history)}


# ── Auto-Renewal & Alert Configuration ───────────────────────────────


class AutoRenewalCertificateRef(BaseModel):
    """A specific certificate targeted by an auto-renewal schedule."""

    id: int = Field(..., description="Keyfactor certificate ID")
    common_name: str = Field(default="", description="Certificate common name")
    thumbprint: str = Field(default="", description="Certificate thumbprint")


class AutoRenewalAkvTarget(BaseModel):
    """A Key Vault entry a renewed certificate is imported into."""

    subscription_id: str = Field(default="", description="Azure Subscription ID")
    resource_group: str = Field(default="", description="Resource group containing the Key Vault")
    vault_name: str = Field(..., min_length=1, description="Key Vault name")
    certificate_names: list[str] = Field(
        ..., min_length=1, description="Key Vault certificate names to import the renewal into"
    )

    @field_validator("certificate_names")
    @classmethod
    def _valid_names(cls, v: list[str]) -> list[str]:
        import re

        cleaned = []
        for name in v:
            name = name.strip()
            if not (1 <= len(name) <= 127) or not re.match(r"^[a-zA-Z0-9-]+$", name):
                raise ValueError("certificate names must be 1-127 alphanumeric characters or hyphens")
            cleaned.append(name)
        return cleaned


class AutoRenewalConfigRequest(BaseModel):
    """Configure auto-renewal for a whole collection or specific certificates."""

    collection_id: int = Field(..., description="Collection to auto-renew")
    collection_name: str = Field(default="", description="Collection display name")
    enabled: bool = Field(default=True)
    armed: bool = Field(
        default=False,
        description=(
            "Issue certificates unattended. An un-armed schedule runs on time and reports what "
            "it would renew without contacting the CA, so targets and recipients can be "
            "validated first."
        ),
    )
    days_before_expiry: int = Field(default=60, ge=7, le=365, description="Renew X days before expiry")
    notify_on_renewal: bool = Field(default=True)
    notification_emails: list[str] = Field(default=[])
    certificates: list[AutoRenewalCertificateRef] = Field(
        default=[],
        description="Specific certificates to renew; empty means the entire collection.",
    )
    akv_targets: list[AutoRenewalAkvTarget] = Field(
        default=[],
        description="Key Vault entries each renewed certificate is imported into.",
    )


class AlertConfigRequest(BaseModel):
    """Configure expiry alerts for certificates."""

    collection_id: int | None = Field(default=None, description="Scope to collection (null = all)")
    collection_name: str = Field(default="", description="Collection display name")
    enabled: bool = Field(default=True)
    warning_days: int = Field(default=60, ge=1, le=365, description="Warn X days before expiry")
    critical_days: int = Field(default=30, ge=1, le=365, description="Critical X days before expiry")
    notification_emails: list[str] = Field(default=[])
    # Only email delivery is implemented. The field is kept so configs stored
    # while the UI offered "teams" and "both" still parse; those rules already
    # sent email, which is now what the form says they do.
    notify_channel: str = Field(default="email", description="Delivery channel; only email is implemented")


@router.get("/auto-renewal/configs")
async def list_auto_renewal_configs(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List auto-renewal configurations (with last manual-run timestamps)."""
    from sqlalchemy import select

    if db is None:
        return []
    # Latest manual-run timestamp per collection, to surface "last triggered" in the UI.
    run_stmt = (
        select(AuditLog)
        .where(AuditLog.action == "cert_auto_renewal_run")
        .where(AuditLog.resource_type == "certificate_config")
        .order_by(AuditLog.timestamp.desc())
    )
    run_result = await db.execute(run_stmt)
    last_run_by_collection: dict[Any, str | None] = {}
    last_summary_by_config: dict[Any, str] = {}
    for run in run_result.scalars().all():
        if isinstance(run.details, dict):
            cid = run.details.get("collection_id")
            if cid is not None and cid not in last_run_by_collection:
                last_run_by_collection[cid] = run.timestamp.isoformat() if run.timestamp else None
            config_id = run.details.get("config_id")
            if config_id is not None and config_id not in last_summary_by_config:
                last_summary_by_config[config_id] = str(run.details.get("summary") or "")
    # Store configs in audit_logs as config entries (simple approach; production would use a dedicated table)
    stmt = (
        select(AuditLog)
        .where(AuditLog.action == "cert_auto_renewal_config")
        .where(AuditLog.resource_type == "certificate_config")
    )
    result = await db.execute(stmt)
    configs = []
    for entry in result.scalars().all():
        if isinstance(entry.details, dict):
            collection_id = entry.details.get("collection_id")
            configs.append(
                {
                    "id": entry.id,
                    "collection_id": collection_id,
                    "collection_name": entry.details.get("collection_name", ""),
                    "enabled": entry.details.get("enabled", True),
                    "days_before_expiry": entry.details.get("days_before_expiry", 60),
                    "notify_on_renewal": entry.details.get("notify_on_renewal", True),
                    "notification_emails": entry.details.get("notification_emails", []),
                    "certificates": entry.details.get("certificates", []),
                    "certificate_count": entry.details.get("certificate_count", 0),
                    "armed": entry.details.get("armed", False),
                    "akv_targets": entry.details.get("akv_targets", []),
                    "created_at": entry.timestamp.isoformat() if entry.timestamp else None,
                    "created_by": entry.user_email or entry.user_id,
                    "last_run_at": last_run_by_collection.get(collection_id),
                    "last_run_summary": last_summary_by_config.get(entry.id, ""),
                }
            )
    return configs


@router.post("/auto-renewal/configs")
async def create_auto_renewal_config(
    payload: AutoRenewalConfigRequest,
    request: Request,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create or update an auto-renewal configuration."""
    certificates = [c.model_dump() for c in payload.certificates]
    scope = f"{len(certificates)} certificate(s)" if certificates else "entire collection"
    entry = AuditLog(
        user_id=user.user_id,
        user_email=user.email,
        action="cert_auto_renewal_config",
        resource_type="certificate_config",
        resource_id=str(payload.collection_id),
        details={
            "page": "CertificatesPage",
            "feature": "auto_renewal",
            "collection_id": payload.collection_id,
            "collection_name": payload.collection_name,
            "enabled": payload.enabled,
            "armed": payload.armed,
            "days_before_expiry": payload.days_before_expiry,
            "notify_on_renewal": payload.notify_on_renewal,
            "notification_emails": payload.notification_emails,
            "certificates": certificates,
            "certificate_count": len(certificates),
            "akv_targets": [t.model_dump() for t in payload.akv_targets],
            "summary": (
                f"Auto-renewal config ({scope}): {payload.days_before_expiry} days before expiry, "
                f"{'armed' if payload.armed else 'dry run'}"
            ),
        },
        ip_address=request.client.host if request.client else None,
        status="success",
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return {
        "id": entry.id,
        "status": "created",
        "days_before_expiry": payload.days_before_expiry,
        "armed": payload.armed,
    }


@router.delete("/auto-renewal/configs/{config_id}")
async def delete_auto_renewal_config(
    config_id: int,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Delete an auto-renewal configuration."""
    from sqlalchemy import delete

    await db.execute(delete(AuditLog).where(AuditLog.id == config_id))
    await db.commit()
    return {"id": config_id, "status": "deleted"}


@router.post("/auto-renewal/configs/{config_id}/run")
async def run_auto_renewal_config(
    config_id: int,
    request: Request,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Run an auto-renewal schedule now.

    Honours the schedule's arm state: an un-armed schedule reports what it would
    renew and issues nothing. Either way the run is recorded in the audit log
    and the configured recipients get the report, which is what makes a dry run
    useful for validating targets and email content.
    """
    from app.services.certificate_automation_service import CertificateAutomationService

    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not available.")

    result = await db.execute(
        select(AuditLog).where(AuditLog.id == config_id).where(AuditLog.action == "cert_auto_renewal_config")
    )
    config = result.scalar_one_or_none()
    if config is None or not isinstance(config.details, dict):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Auto-renewal schedule not found.")

    outcome = await CertificateAutomationService(db).run_renewal_config(
        {"id": config.id, "created_by": config.user_email or config.user_id, **config.details},
        trigger="manual",
        actor=user.email or user.user_id,
    )
    return {"status": "completed", "config_id": config_id, **outcome}


@router.post("/alerts/configs/{config_id}/run")
async def run_alert_config_now(
    config_id: int,
    request: Request,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Evaluate one expiry alert rule now and send its report."""
    from app.services.certificate_automation_service import CertificateAutomationService

    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not available.")

    result = await db.execute(
        select(AuditLog).where(AuditLog.id == config_id).where(AuditLog.action == "cert_alert_config")
    )
    config = result.scalar_one_or_none()
    if config is None or not isinstance(config.details, dict):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert rule not found.")

    outcome = await CertificateAutomationService(db).run_alert_config(
        {"id": config.id, "created_by": config.user_email or config.user_id, **config.details},
        trigger="manual",
    )
    return {"status": "completed", **outcome}


@router.get("/alerts/configs")
async def list_alert_configs(
    user: UserContext = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[dict[str, Any]]:
    """List certificate expiry alert configurations."""
    from sqlalchemy import select

    if db is None:
        return []
    stmt = (
        select(AuditLog)
        .where(AuditLog.action == "cert_alert_config")
        .where(AuditLog.resource_type == "certificate_config")
    )
    result = await db.execute(stmt)
    configs = []
    for entry in result.scalars().all():
        if isinstance(entry.details, dict):
            configs.append(
                {
                    "id": entry.id,
                    "collection_id": entry.details.get("collection_id"),
                    "collection_name": entry.details.get("collection_name", ""),
                    "enabled": entry.details.get("enabled", True),
                    "warning_days": entry.details.get("warning_days", 60),
                    "critical_days": entry.details.get("critical_days", 30),
                    "notification_emails": entry.details.get("notification_emails", []),
                    "notify_channel": entry.details.get("notify_channel", "email"),
                    "created_at": entry.timestamp.isoformat() if entry.timestamp else None,
                    "created_by": entry.user_email or entry.user_id,
                }
            )
    return configs


@router.post("/alerts/configs")
async def create_alert_config(
    payload: AlertConfigRequest,
    request: Request,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Create a certificate expiry alert configuration."""
    entry = AuditLog(
        user_id=user.user_id,
        user_email=user.email,
        action="cert_alert_config",
        resource_type="certificate_config",
        resource_id=str(payload.collection_id or "all"),
        details={
            "page": "CertificatesPage",
            "feature": "expiry_alerts",
            "collection_id": payload.collection_id,
            "collection_name": payload.collection_name,
            "enabled": payload.enabled,
            "warning_days": payload.warning_days,
            "critical_days": payload.critical_days,
            "notification_emails": payload.notification_emails,
            "notify_channel": payload.notify_channel,
            "summary": f"Alert config: warn {payload.warning_days}d, critical {payload.critical_days}d",
        },
        ip_address=request.client.host if request.client else None,
        status="success",
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return {
        "id": entry.id,
        "status": "created",
        "warning_days": payload.warning_days,
        "critical_days": payload.critical_days,
    }


@router.delete("/alerts/configs/{config_id}")
async def delete_alert_config(
    config_id: int,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Delete an alert configuration."""
    from sqlalchemy import delete

    await db.execute(delete(AuditLog).where(AuditLog.id == config_id))
    await db.commit()
    return {"id": config_id, "status": "deleted"}


@router.get("/{certificate_id}")
async def get_certificate(
    certificate_id: int,
    user: UserContext = Depends(get_current_user),
    service: CertificateService = Depends(_get_service),
) -> dict[str, Any]:
    """Full metadata for a single certificate."""
    try:
        return await service.get_certificate(certificate_id)
    except CertificateServiceError as exc:
        _raise_http(exc)


# ── Write endpoints ────────────────────────────────────────────────────


@router.post("/enroll", status_code=status.HTTP_201_CREATED)
async def enroll_certificate(
    payload: EnrollRequest,
    request: Request,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: CertificateService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Request/issue a new certificate (CSR or PFX enrollment)."""
    try:
        if payload.enrollment_type == "csr":
            if not payload.csr:
                raise HTTPException(status_code=422, detail="csr is required for CSR enrollment")
            result = await service.enroll_csr(
                csr=payload.csr,
                certificate_authority=payload.certificate_authority,
                template=payload.template,
                sans=payload.sans,
                metadata=payload.metadata,
                include_chain=payload.include_chain,
            )
            target = "csr"
        else:
            # Build subject DN from individual fields if not provided directly
            subject_dn = payload.subject
            if not subject_dn and payload.common_name:
                parts = [f"CN={payload.common_name}"]
                if payload.organization:
                    parts.append(f"O={payload.organization}")
                if payload.organizational_unit:
                    parts.append(f"OU={payload.organizational_unit}")
                if payload.city:
                    parts.append(f"L={payload.city}")
                if payload.state:
                    parts.append(f"ST={payload.state}")
                if payload.country:
                    parts.append(f"C={payload.country}")
                subject_dn = ",".join(parts)

            if not subject_dn or not payload.password:
                raise HTTPException(
                    status_code=422,
                    detail="subject (or common_name) and password are required for PFX enrollment",
                )

            # Merge AT&T-specific metadata into the metadata dict
            merged_metadata = dict(payload.metadata or {})
            if payload.mots_profile_id:
                merged_metadata["MOTS-Profile-ID"] = payload.mots_profile_id
            if payload.requester_att_user_id:
                merged_metadata["Requester-ATT-User-ID"] = payload.requester_att_user_id
            if payload.requester_att_manager_user_id:
                merged_metadata["Requester-ATT-Manager-User-ID"] = payload.requester_att_manager_user_id
            if payload.server_type:
                merged_metadata["Server-Type"] = payload.server_type
            if payload.environment:
                merged_metadata["Environment"] = payload.environment
            if payload.tls_port_services_internet_traffic:
                merged_metadata["TLS-Port-Services-Internet-Traffic"] = payload.tls_port_services_internet_traffic
            if payload.port:
                merged_metadata["Port"] = payload.port
            if payload.pci_data:
                merged_metadata["PCI-Data"] = payload.pci_data

            result = await service.enroll_pfx(
                subject=subject_dn,
                certificate_authority=payload.certificate_authority,
                template=payload.template,
                password=payload.password,
                key_type=payload.key_type,
                key_length=payload.key_length,
                sans=payload.sans,
                metadata=merged_metadata or None,
                include_chain=payload.include_chain,
            )
            target = payload.common_name or subject_dn
    except CertificateServiceError as exc:
        await _write_audit(
            db,
            request=request,
            user=user,
            action="enroll_certificate",
            resource_id=str(payload.subject or "csr"),
            summary=(
                f"Enrollment failed for {payload.common_name or payload.subject or 'CSR request'} "
                f"({payload.enrollment_type})"
            ),
            outcome="failure",
            details={
                "common_name": payload.common_name or None,
                "enrollment_type": payload.enrollment_type,
                "template": payload.template,
            },
        )
        _raise_http(exc)

    enrolled_name = payload.common_name or (target if target != "csr" else None)
    await _write_audit(
        db,
        request=request,
        user=user,
        action="enroll_certificate",
        resource_id=str(result.get("certificate_id") or target),
        summary=(f"Enrolled {enrolled_name or 'certificate'} ({payload.enrollment_type}) via {payload.template}"),
        outcome="success",
        details={
            "common_name": enrolled_name,
            "enrollment_type": payload.enrollment_type,
            "template": payload.template,
            "certificate_authority": payload.certificate_authority,
            "thumbprint": result.get("thumbprint"),
        },
    )
    # Keyfactor returns the PFX only here, so escrow it now or lose it.
    await _escrow_issued_key(
        db,
        request=request,
        user=user,
        result=result,
        password=payload.password,
        source="enroll",
        common_name=enrolled_name,
    )
    _schedule_sync(None, triggered_by="mutation")
    return result


@router.post("/{certificate_id}/renew")
async def renew_certificate(
    certificate_id: int,
    payload: RenewRequest,
    request: Request,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: CertificateService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Renew an existing certificate."""
    try:
        result = await service.renew_certificate(
            certificate_id=certificate_id,
            mode=payload.mode,
            certificate_authority=payload.certificate_authority,
            template=payload.template,
            collection_id=payload.collection_id,
            password=payload.password,
            key_type=payload.key_type,
            key_length=payload.key_length,
            owner_role_name=payload.owner_role_name,
            csr=payload.csr,
        )
    except CertificateServiceError as exc:
        _raise_http(exc)

    cert_label, cert_cn = await _cert_identity(db, certificate_id)
    await _write_audit(
        db,
        request=request,
        user=user,
        action="renew_certificate",
        resource_id=str(certificate_id),
        summary=f"Renewed {cert_label}",
        outcome="success",
        details={"thumbprint": result.get("thumbprint"), "common_name": cert_cn},
    )
    # A PFX-mode renewal is the only moment the new key exists in the response;
    # escrowing it here is what makes later loads into further vaults possible.
    await _escrow_issued_key(
        db,
        request=request,
        user=user,
        result=result,
        password=payload.password,
        source="renew",
        common_name=cert_cn,
    )
    _schedule_sync(None, triggered_by="mutation")
    return result


@router.post("/{certificate_id}/revoke")
async def revoke_certificate(
    certificate_id: int,
    payload: RevokeRequest,
    request: Request,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: CertificateService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Revoke a certificate (WRITE role or above)."""
    try:
        result = await service.revoke_certificate(
            certificate_id=certificate_id,
            reason=payload.reason,
            comment=payload.comment,
            effective_date=payload.effective_date,
            collection_id=payload.collection_id,
            actor=user.email or user.user_id,
        )
    except CertificateServiceError as exc:
        _raise_http(exc)

    cert_label, cert_cn = await _cert_identity(db, certificate_id)

    # Reflect the revocation in the DB cache immediately so the grid shows the
    # new status without waiting for the eventually-consistent background sync.
    if db is not None:
        await CertificateSyncService(db).mark_certificate_revoked(
            certificate_id,
            collection_id=payload.collection_id,
            reason=REVOCATION_REASONS.get(payload.reason),
        )

    await _write_audit(
        db,
        request=request,
        user=user,
        action="revoke_certificate",
        resource_id=str(certificate_id),
        summary=f"Revoked {cert_label} ({payload.reason})",
        outcome="success",
        details={
            "common_name": cert_cn,
            "reason": payload.reason,
            "comment": str(result.get("comment") or payload.comment)[:200],
            "comment_supplied": bool(payload.comment.strip()),
        },
    )
    _schedule_sync(payload.collection_id, triggered_by="mutation")
    return result


@router.put("/{certificate_id}/metadata")
async def update_certificate_metadata(
    certificate_id: int,
    payload: UpdateMetadataRequest,
    request: Request,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: CertificateService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Update editable metadata / custom fields on a certificate."""
    try:
        result = await service.update_metadata(certificate_id=certificate_id, metadata=payload.metadata)
    except CertificateServiceError as exc:
        _raise_http(exc)

    cert_label, cert_cn = await _cert_identity(db, certificate_id)
    await _write_audit(
        db,
        request=request,
        user=user,
        action="update_certificate_metadata",
        resource_id=str(certificate_id),
        summary=f"Updated metadata on {cert_label}",
        outcome="success",
        details={"common_name": cert_cn, "updated_fields": result.get("updated_fields", [])},
    )
    _schedule_sync(None, triggered_by="mutation")
    return result


@router.delete("/{certificate_id}")
async def delete_certificate(
    certificate_id: int,
    request: Request,
    collection_id: int | None = Query(default=None, description="Collection context"),
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: CertificateService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Delete a certificate record (WRITE role or above).

    The certificate is removed from Keyfactor and soft-deleted in the local DB
    snapshot so it remains visible in the "Deleted Certificates" view.
    """
    # Resolved up front: after the delete the audit trail is the only place the
    # certificate's name still exists.
    cert_label, cert_cn = await _cert_identity(db, certificate_id)
    try:
        result = await service.delete_certificate(certificate_id, collection_id=collection_id)
    except CertificateServiceError as exc:
        _raise_http(exc)

    # Soft-delete the local DB snapshot immediately so the "Deleted" tile
    # reflects the change without waiting for the next background sync.
    if db is not None:
        await db.execute(
            update(CertificateSnapshot)
            .where(CertificateSnapshot.certificate_id == certificate_id)
            .where(CertificateSnapshot.deleted_at.is_(None))
            .values(deleted_at=datetime.utcnow())
        )
        await db.commit()

    await _write_audit(
        db,
        request=request,
        user=user,
        action="delete_certificate",
        resource_id=str(certificate_id),
        summary=f"Deleted {cert_label}",
        outcome="success",
        details={"common_name": cert_cn},
    )
    _schedule_sync(collection_id, triggered_by="mutation")
    return result


def _sanitize(value: str) -> str:
    """Strip characters that could break the Keyfactor query grammar."""
    return value.replace('"', "").replace("\\", "").replace("\n", "").replace("\r", "").strip()


@router.post("/{certificate_id}/download")
async def download_certificate(
    certificate_id: int,
    payload: DownloadRequest,
    request: Request,
    user: UserContext = Depends(get_current_user),
    service: CertificateService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Download a certificate in the specified format.

    PFX/PKCS#12 (private-key-containing) downloads require at least WRITE role.

    Keyfactor is tried first so chain options behave exactly as before, but it
    refuses to export a key it never archived. For PFX the escrowed key is then
    used instead, re-wrapped under the password supplied on this request — that
    is the difference between a working download and a 422 for every certificate
    without key archival.
    """
    from fastapi.responses import Response

    # PFX and JKS carry private key material — require WRITE role.
    requested_format = payload.file_format.upper()
    if requested_format in _KEYSTORE_FORMATS and not (user.is_admin or user.can_write):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Downloading {requested_format} (private key) format requires at least WRITE role.",
        )

    cert_label, cert_cn = await _cert_identity(db, certificate_id)

    if requested_format == "JKS":
        content, key_source = await _build_jks(
            service=service,
            db=db,
            certificate_id=certificate_id,
            payload=payload,
        )
        await _write_audit(
            db,
            request=request,
            user=user,
            action="download_certificate",
            resource_id=str(certificate_id),
            summary=f"Downloaded {cert_label} (JKS)",
            outcome="success",
            details={
                "common_name": cert_cn,
                "file_format": "JKS",
                "include_chain": payload.include_chain,
                "key_source": key_source,
            },
            # Never log the keystore password
        )
        return Response(
            content=content,
            media_type="application/x-java-keystore",
            headers={"Content-Disposition": 'attachment; filename="certificate.jks"'},
        )

    is_pfx = requested_format == "PFX"
    key_source = "keyfactor"
    try:
        content = await service.download_certificate(
            certificate_id,
            file_format=payload.file_format,
            include_chain=payload.include_chain,
            chain_order=payload.chain_order,
            collection_id=payload.collection_id,
            pfx_password=payload.pfx_password if is_pfx else None,
        )
    except CertificateServiceError as exc:
        escrowed_pfx = None
        if is_pfx and payload.pfx_password and db is not None:
            try:
                escrowed_pfx = await CertificateEscrowService(db).export_pfx(
                    certificate_id=certificate_id,
                    password=payload.pfx_password,
                    include_chain=payload.include_chain,
                )
            except Exception as escrow_exc:  # pragma: no cover - fall through to the original error
                logger.warning(
                    "cert_escrow_download_failed",
                    certificate_id=certificate_id,
                    error=str(escrow_exc)[:200],
                )
        if escrowed_pfx is None:
            if is_pfx:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Could not export this certificate's private key from Keyfactor "
                        f"({exc.message}), and no escrowed key is available for it. Keyfactor "
                        "returns the PFX only at the moment of issuance unless key archival is "
                        "enabled on the template. Renew this certificate through the portal to "
                        "escrow its key, after which PFX download works at any time."
                    ),
                )
            _raise_http(exc)
        content = escrowed_pfx
        key_source = "escrow"

    await _write_audit(
        db,
        request=request,
        user=user,
        action="download_certificate",
        resource_id=str(certificate_id),
        summary=f"Downloaded {cert_label} ({payload.file_format})",
        outcome="success",
        details={
            "common_name": cert_cn,
            "file_format": payload.file_format,
            "include_chain": payload.include_chain,
            "key_source": key_source,
        },
        # Never log pfx_password
    )

    ext = payload.file_format.lower()
    content_type = {
        "pem": "application/x-pem-file",
        "cer": "application/x-x509-ca-cert",
        "crt": "application/x-x509-ca-cert",
        "der": "application/x-x509-ca-cert",
        "p7b": "application/x-pkcs7-certificates",
        "pfx": "application/x-pkcs12",
    }.get(ext, "application/octet-stream")

    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="certificate.{ext}"'},
    )


@router.post("/{certificate_id}/load-to-akv")
async def load_certificate_to_akv(
    certificate_id: int,
    payload: LoadToAkvRequest,
    request: Request,
    user: UserContext = Depends(require_role(UserRole.WRITE)),
    service: CertificateService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Import a certificate into Azure Key Vault.

    Azure Key Vault only accepts a certificate that carries its private key. When
    the caller omits ``certificate_data`` the key comes from the escrow vault if
    the certificate was escrowed at issuance, otherwise from a live Keyfactor PFX
    export under a single-use password. Escrow is what makes a *second* vault
    reachable: Keyfactor releases the PFX only at issuance, so an un-escrowed
    certificate can be loaded exactly once.

    Private key material and passwords are never written to logs or the audit
    record; the response reports only which source was used.
    """
    import base64
    import secrets

    from app.services.keyvault_service import KeyVaultService

    import_password = payload.certificate_password
    key_source = "provided"
    if payload.certificate_data:
        # Decode the caller-supplied certificate data (may be PFX or PEM).
        try:
            cert_bytes = base64.b64decode(payload.certificate_data)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="certificate_data must be valid base64-encoded certificate content.",
            )
    else:
        # Prefer the escrowed key: unlike a Keyfactor export it stays available
        # long after issuance, which is what allows loading the same certificate
        # into a second (or third) environment's vault.
        escrowed: tuple[bytes, str] | None = None
        if payload.key_source in ("auto", "escrow") and db is not None:
            try:
                escrowed = await CertificateEscrowService(db).get_material(certificate_id=certificate_id)
            except Exception as exc:  # pragma: no cover - fall back to Keyfactor
                logger.warning(
                    "cert_escrow_lookup_failed",
                    certificate_id=certificate_id,
                    error=str(exc)[:200],
                )

        if escrowed is not None:
            cert_bytes, import_password = escrowed
            key_source = "escrow"
        elif payload.key_source == "escrow":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    "No escrowed private key is available for this certificate. Only "
                    "certificates issued or renewed through the portal after key escrow "
                    "was enabled have one; enroll or renew it here to escrow its key, or "
                    "retry with key_source='auto' to attempt a live Keyfactor export."
                ),
            )
        else:
            # The one-time password only protects the PFX in transit to Key Vault.
            key_source = "keyfactor"
            import_password = secrets.token_urlsafe(24)
            try:
                cert_bytes = await service.download_certificate(
                    certificate_id,
                    file_format="PFX",
                    include_chain=False,
                    collection_id=payload.collection_id,
                    pfx_password=import_password,
                )
            except CertificateServiceError as exc:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=(
                        "Could not export this certificate's private key from Keyfactor "
                        f"({exc.message}), and no escrowed key is available for it. Keyfactor "
                        "returns the PFX only at the moment of issuance unless key archival is "
                        "enabled on the template, so renewing an existing certificate does not "
                        "make its key exportable afterwards. Generate a new certificate with PFX "
                        "and load that — with escrow enabled its key is kept, so it can then be "
                        "loaded into any number of vaults later."
                    ),
                )

    cert_label, cert_cn = await _cert_identity(db, certificate_id)
    kv_service = KeyVaultService()
    vault_url = f"https://{payload.vault_name}.vault.azure.net"

    # One export, many targets: the PFX cannot be re-fetched for a second attempt.
    imported: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for cert_name in payload.certificate_names:
        try:
            result = await kv_service.import_certificate(
                vault_url,
                cert_name,
                cert_bytes,
                password=import_password,
            )
        except Exception as exc:
            failures.append({"certificate_name": cert_name, "error": str(exc)[:300]})
            continue
        imported.append(
            {
                "certificate_name": cert_name,
                "akv_id": result.get("id", ""),
                "enabled": result.get("attributes", {}).get("enabled", True),
            }
        )

    names_text = ", ".join(payload.certificate_names)
    if not imported:
        await _write_audit(
            db,
            request=request,
            user=user,
            action="load_certificate_to_akv",
            resource_id=str(certificate_id),
            summary=f"Failed to load {cert_label} to AKV {payload.vault_name}/{names_text}",
            outcome="failed",
            details={
                "common_name": cert_cn,
                "vault_name": payload.vault_name,
                "certificate_names": payload.certificate_names,
                "subscription_id": payload.subscription_id,
                "resource_group": payload.resource_group,
                "key_source": key_source,
                "errors": failures,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Failed to load certificate into Azure Key Vault: {failures[0]['error']}",
        )

    await _write_audit(
        db,
        request=request,
        user=user,
        action="load_certificate_to_akv",
        resource_id=str(certificate_id),
        summary=(
            f"Loaded {cert_label} to AKV {payload.vault_name}/{', '.join(i['certificate_name'] for i in imported)}"
        ),
        outcome="partial" if failures else "success",
        details={
            "common_name": cert_cn,
            "vault_name": payload.vault_name,
            "certificate_names": [i["certificate_name"] for i in imported],
            "subscription_id": payload.subscription_id,
            "resource_group": payload.resource_group,
            "key_source": key_source,
            **({"errors": failures} if failures else {}),
        },
        # Never log certificate_data or certificate_password
    )

    return {
        "status": "partial" if failures else "success",
        "vault_name": payload.vault_name,
        "certificates": imported,
        "failed": failures,
        "key_source": key_source,
    }
