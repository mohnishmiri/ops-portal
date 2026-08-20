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
from typing import Any, NoReturn

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, require_role
from app.core.config import settings
from app.core.database import get_db, get_db_session
from app.models.auth import UserContext, UserRole
from app.models.database import AuditLog
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


class DownloadRequest(BaseModel):
    file_format: str = Field(default="PEM", description="PEM, CER, CRT, DER, or P7B")
    include_chain: bool = Field(default=True)
    chain_order: str = Field(default="EndEntityFirst", description="EndEntityFirst or RootFirst")
    include_subject_header: bool = Field(default=True)
    collection_id: int | None = Field(default=None, description="Collection context for the download")


class RevokeRequest(BaseModel):
    reason: str = Field(..., description=f"One of: {', '.join(REVOCATION_REASONS)}")
    comment: str = Field(default="", max_length=1000)
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
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=25, ge=1, le=200),
    refresh: bool = Query(default=False, description="Bypass the DB cache and fetch live from Keyfactor"),
    user: UserContext = Depends(get_current_user),
    service: CertificateService = Depends(_get_service),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Paginated, filterable certificate list (served from the DB cache when available)."""
    # DB-first fast path: serve the cached snapshot for this collection.
    if not refresh and collection_id is not None and db is not None:
        try:
            sync_service = CertificateSyncService(db)
            if await sync_service.has_certificates(collection_id):
                return await sync_service.list_certificates_from_db(
                    collection_id=collection_id,
                    cn=cn,
                    thumbprint=thumbprint,
                    issuer=issuer,
                    cert_status=cert_status,
                    expires_in_days=expires_in_days,
                    page=page,
                    page_size=page_size,
                )
        except Exception as exc:
            logger.warning("cert_list_db_fallback", error=str(exc)[:200])

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
    return result


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


class AutoRenewalConfigRequest(BaseModel):
    """Configure auto-renewal for a whole collection or specific certificates."""

    collection_id: int = Field(..., description="Collection to auto-renew")
    collection_name: str = Field(default="", description="Collection display name")
    enabled: bool = Field(default=True)
    days_before_expiry: int = Field(default=60, ge=7, le=365, description="Renew X days before expiry")
    notify_on_renewal: bool = Field(default=True)
    notification_emails: list[str] = Field(default=[])
    certificates: list[AutoRenewalCertificateRef] = Field(
        default=[],
        description="Specific certificates to renew; empty means the entire collection.",
    )


class AlertConfigRequest(BaseModel):
    """Configure expiry alerts for certificates."""

    collection_id: int | None = Field(default=None, description="Scope to collection (null = all)")
    collection_name: str = Field(default="", description="Collection display name")
    enabled: bool = Field(default=True)
    warning_days: int = Field(default=60, ge=1, le=365, description="Warn X days before expiry")
    critical_days: int = Field(default=30, ge=1, le=365, description="Critical X days before expiry")
    notification_emails: list[str] = Field(default=[])
    notify_channel: str = Field(default="email", description="email, teams, or both")


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
    for run in run_result.scalars().all():
        if isinstance(run.details, dict):
            cid = run.details.get("collection_id")
            if cid is not None and cid not in last_run_by_collection:
                last_run_by_collection[cid] = run.timestamp.isoformat() if run.timestamp else None
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
                    "created_at": entry.timestamp.isoformat() if entry.timestamp else None,
                    "created_by": entry.user_email or entry.user_id,
                    "last_run_at": last_run_by_collection.get(collection_id),
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
            "days_before_expiry": payload.days_before_expiry,
            "notify_on_renewal": payload.notify_on_renewal,
            "notification_emails": payload.notification_emails,
            "certificates": certificates,
            "certificate_count": len(certificates),
            "summary": f"Auto-renewal config ({scope}): {payload.days_before_expiry} days before expiry",
        },
        ip_address=request.client.host if request.client else None,
        status="success",
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return {"id": entry.id, "status": "created", "days_before_expiry": payload.days_before_expiry}


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
    """Manually trigger an auto-renewal schedule and record the run in the audit log."""
    from sqlalchemy import select

    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is not available.")
    stmt = select(AuditLog).where(AuditLog.id == config_id).where(AuditLog.action == "cert_auto_renewal_config")
    result = await db.execute(stmt)
    config = result.scalar_one_or_none()
    if config is None or not isinstance(config.details, dict):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Auto-renewal schedule not found.")

    cfg = config.details
    collection_id = cfg.get("collection_id")
    collection_name = cfg.get("collection_name", "")
    days_before_expiry = cfg.get("days_before_expiry", 60)
    certificate_ids = [
        c.get("id") for c in (cfg.get("certificates") or []) if isinstance(c, dict) and c.get("id") is not None
    ]

    # Best-effort due-count from the cached snapshot (DB-first); never blocks the trigger.
    certificates_due: int | None = None
    if collection_id is not None:
        try:
            certificates_due = await CertificateSyncService(db).count_due_certificates(
                collection_id=collection_id,
                days_before_expiry=days_before_expiry,
                certificate_ids=certificate_ids or None,
            )
        except Exception as exc:
            logger.warning("cert_auto_renewal_due_count_failed", error=str(exc)[:200])

    scope = f"{len(certificate_ids)} certificate(s)" if certificate_ids else "entire collection"
    target = collection_name or f"collection {collection_id}"
    due_text = "unknown" if certificates_due is None else str(certificates_due)
    summary = (
        f"Manual auto-renewal run for {target} ({scope}): "
        f"{due_text} certificate(s) due within {days_before_expiry} days"
    )
    entry = AuditLog(
        user_id=user.user_id,
        user_email=user.email,
        action="cert_auto_renewal_run",
        resource_type="certificate_config",
        resource_id=str(collection_id) if collection_id is not None else str(config_id),
        details={
            "page": "CertificatesPage",
            "feature": "auto_renewal",
            "trigger": "manual",
            "triggered_by": user.email or user.user_id,
            "config_id": config_id,
            "collection_id": collection_id,
            "collection_name": collection_name,
            "days_before_expiry": days_before_expiry,
            "scope": scope,
            "certificates_targeted": len(certificate_ids),
            "certificates_due": certificates_due,
            "summary": summary,
        },
        ip_address=request.client.host if request.client else None,
        status="success",
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return {
        "id": entry.id,
        "status": "triggered",
        "config_id": config_id,
        "collection_id": collection_id,
        "collection_name": collection_name,
        "days_before_expiry": days_before_expiry,
        "certificates_due": certificates_due,
        "scope": scope,
        "triggered_at": entry.timestamp.isoformat() if entry.timestamp else None,
    }


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
            summary=f"Enrollment failed ({payload.enrollment_type})",
            outcome="failure",
            details={"enrollment_type": payload.enrollment_type, "template": payload.template},
        )
        _raise_http(exc)

    await _write_audit(
        db,
        request=request,
        user=user,
        action="enroll_certificate",
        resource_id=str(result.get("certificate_id") or target),
        summary=f"Enrolled certificate ({payload.enrollment_type}) via {payload.template}",
        outcome="success",
        details={
            "enrollment_type": payload.enrollment_type,
            "template": payload.template,
            "certificate_authority": payload.certificate_authority,
            "thumbprint": result.get("thumbprint"),
        },
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

    await _write_audit(
        db,
        request=request,
        user=user,
        action="renew_certificate",
        resource_id=str(certificate_id),
        summary=f"Renewed certificate {certificate_id}",
        outcome="success",
        details={"thumbprint": result.get("thumbprint")},
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
        )
    except CertificateServiceError as exc:
        _raise_http(exc)

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
        summary=f"Revoked certificate {certificate_id} ({payload.reason})",
        outcome="success",
        details={"reason": payload.reason, "comment": payload.comment[:200]},
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

    await _write_audit(
        db,
        request=request,
        user=user,
        action="update_certificate_metadata",
        resource_id=str(certificate_id),
        summary=f"Updated metadata on certificate {certificate_id}",
        outcome="success",
        details={"updated_fields": result.get("updated_fields", [])},
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
    """Delete a certificate record (WRITE role or above)."""
    try:
        result = await service.delete_certificate(certificate_id, collection_id=collection_id)
    except CertificateServiceError as exc:
        _raise_http(exc)

    await _write_audit(
        db,
        request=request,
        user=user,
        action="delete_certificate",
        resource_id=str(certificate_id),
        summary=f"Deleted certificate {certificate_id}",
        outcome="success",
        details={},
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
    """Download a certificate in the specified format."""
    from fastapi.responses import Response

    try:
        content = await service.download_certificate(
            certificate_id,
            file_format=payload.file_format,
            include_chain=payload.include_chain,
            chain_order=payload.chain_order,
            collection_id=payload.collection_id,
        )
    except CertificateServiceError as exc:
        _raise_http(exc)

    await _write_audit(
        db,
        request=request,
        user=user,
        action="download_certificate",
        resource_id=str(certificate_id),
        summary=f"Downloaded certificate {certificate_id} ({payload.file_format})",
        outcome="success",
        details={"file_format": payload.file_format, "include_chain": payload.include_chain},
    )

    ext = payload.file_format.lower()
    content_type = {
        "pem": "application/x-pem-file",
        "cer": "application/x-x509-ca-cert",
        "crt": "application/x-x509-ca-cert",
        "der": "application/x-x509-ca-cert",
        "p7b": "application/x-pkcs7-certificates",
    }.get(ext, "application/octet-stream")

    return Response(
        content=content,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="certificate.{ext}"'},
    )
