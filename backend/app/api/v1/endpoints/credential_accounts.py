"""Tools — credential account inventory, shown under the Credential Check.

The service accounts the team owns (domain accounts, AAF identities, JFrog
users) by application: owner, expiry, last login, failed logins, reset link.
No password or token is ever accepted or stored here.

Authorization follows the portal policy (READ views, WRITE changes) through
the Credential Check page resource, so it can be revoked from the
Permissions UI with the page: viewing and exporting need ``view`` on
``credential_check_main``, every change needs ``edit``.  Every change is
written to ``audit_logs``.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Literal

import structlog
from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, Response, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import require_capability
from app.core.database import get_db
from app.models.auth import UserContext, UserRole
from app.schemas.credential_inventory import (
    CredentialAccountCreate,
    CredentialAccountIn,
    CredentialAccountOut,
    ImportApplyRequest,
    ImportApplyResult,
    ImportPreview,
)
from app.services.credential_inventory_service import (
    IMPORT_MAX_BYTES,
    AccountFilter,
    CredentialInventoryService,
    DuplicateAccountError,
    account_label,
    export_csv,
    export_xlsx,
    filter_accounts,
    import_template_xlsx,
)

logger = structlog.get_logger(__name__)
router = APIRouter()

_PAGE = "credential_check_main"
_VIEW = require_capability(_PAGE, permission_type="view", fallback_role=UserRole.READ)
_EDIT = require_capability(_PAGE, permission_type="edit", fallback_role=UserRole.WRITE)

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Seeded by "Add to inventory" on a check result: that check has just read the
# account, so adding it must not immediately read it again.
_DIRECTORY_FIELDS = {"owner", "expiry_date", "never_expires", "password_changed_date", "last_login_date"}


def _service(db: AsyncSession | None) -> CredentialInventoryService:
    if db is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Database is unavailable")
    return CredentialInventoryService(db)


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


@router.get("", response_model=list[CredentialAccountOut], summary="List the credential account inventory")
async def list_accounts(
    _user: UserContext = Depends(_VIEW),
    db: AsyncSession = Depends(get_db),
) -> list[CredentialAccountOut]:
    if db is None:
        return []
    return [CredentialAccountOut.model_validate(a) for a in await CredentialInventoryService(db).list_accounts()]


@router.post(
    "",
    response_model=CredentialAccountOut,
    status_code=status.HTTP_201_CREATED,
    summary="Add an account to the inventory",
)
async def create_account(
    payload: CredentialAccountCreate,
    request: Request,
    user: UserContext = Depends(_EDIT),
    db: AsyncSession = Depends(get_db),
) -> CredentialAccountOut:
    service = _service(db)
    try:
        account = await service.create(payload, user)
    except DuplicateAccountError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # Fill the row in straight away, so a domain account is listed with its
    # name and expiry rather than waiting to be checked.  Best effort: a row
    # with no details is still a row, and the Refresh action says why.
    if not payload.model_fields_set & _DIRECTORY_FIELDS:
        await service.sync_from_directory(account)

    out = CredentialAccountOut.model_validate(account)
    await service.record_audit(
        user,
        "create_credential_account",
        resource_id=str(out.id),
        summary=f"Added {account_label(out)} to {out.application}",
        details={"account": account_label(out), "application": out.application},
        ip_address=_client_ip(request),
    )
    return out


@router.post("/{account_id}/refresh", summary="Read this account's details from its directory")
async def refresh_account(
    account_id: int,
    request: Request,
    user: UserContext = Depends(_EDIT),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Re-read one account from Active Directory with the portal's reader account.

    Reads attributes only — no password is read, and the account's own
    credential is neither needed nor touched.  The verdict from its last
    check is left as it was.
    """
    service = _service(db)
    try:
        account = await service.get(account_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    lookup = await service.sync_from_directory(account)
    if lookup.status == "ok":
        await service.record_audit(
            user,
            "refresh_credential_account",
            resource_id=str(account_id),
            summary=f"Read {account_label(account)} from the {account.directory} directory",
            details={"account": account_label(account), "application": account.application},
            ip_address=_client_ip(request),
        )
    return {
        "status": lookup.status,
        "reason": lookup.reason,
        "account": CredentialAccountOut.model_validate(account),
    }


@router.put("/{account_id}", response_model=CredentialAccountOut, summary="Edit an inventory account")
async def update_account(
    account_id: int,
    payload: CredentialAccountIn,
    request: Request,
    user: UserContext = Depends(_EDIT),
    db: AsyncSession = Depends(get_db),
) -> CredentialAccountOut:
    service = _service(db)
    try:
        account, changed = await service.update(account_id, payload, user)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except DuplicateAccountError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    out = CredentialAccountOut.model_validate(account)
    await service.record_audit(
        user,
        "update_credential_account",
        resource_id=str(out.id),
        summary=f"Edited {account_label(out)}",
        details={"account": account_label(out), "application": out.application, "changed_fields": changed},
        ip_address=_client_ip(request),
    )
    return out


@router.delete("/{account_id}", summary="Remove an account from the inventory")
async def delete_account(
    account_id: int,
    request: Request,
    user: UserContext = Depends(_EDIT),
    db: AsyncSession = Depends(get_db),
) -> dict:
    service = _service(db)
    try:
        account = await service.delete(account_id)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    label = account_label(account)
    await service.record_audit(
        user,
        "delete_credential_account",
        resource_id=str(account_id),
        summary=f"Removed {label} from {account.application}",
        details={"account": label, "application": account.application},
        ip_address=_client_ip(request),
    )
    return {"deleted": account_id}


# ── Import ─────────────────────────────────────────────────────────────


@router.post("/import/preview", response_model=ImportPreview, summary="Read an Excel / CSV file and preview the import")
async def preview_import(
    file: UploadFile = File(...),
    _user: UserContext = Depends(_EDIT),
    db: AsyncSession = Depends(get_db),
) -> ImportPreview:
    """Validates every row and says what importing it would do.  Writes nothing."""
    service = _service(db)
    content = await file.read(IMPORT_MAX_BYTES + 1)
    if len(content) > IMPORT_MAX_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"The file is larger than {IMPORT_MAX_BYTES // (1024 * 1024)} MB.",
        )
    try:
        return await service.preview_import(file.filename or "", content)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/import", response_model=ImportApplyResult, summary="Import previewed accounts")
async def apply_import(
    payload: ImportApplyRequest,
    request: Request,
    user: UserContext = Depends(_EDIT),
    db: AsyncSession = Depends(get_db),
) -> ImportApplyResult:
    """Creates new accounts and fills in existing ones; blank cells keep what is recorded."""
    service = _service(db)
    result = await service.apply_import(payload.accounts, user)
    await service.record_audit(
        user,
        "import_credential_accounts",
        resource_id=None,
        summary=f"Imported {len(payload.accounts)} accounts ({result.created} new, {result.updated} updated)",
        details={
            "rows": len(payload.accounts),
            "created": result.created,
            "updated": result.updated,
            "applications": sorted({row.application for row in payload.accounts})[:50],
        },
        ip_address=_client_ip(request),
    )
    return result


@router.get("/import-template", summary="Download the Excel import template")
async def download_import_template(_user: UserContext = Depends(_VIEW)) -> Response:
    return Response(
        content=import_template_xlsx(),
        media_type=_XLSX,
        headers={"Content-Disposition": 'attachment; filename="credential-accounts-template.xlsx"'},
    )


# ── Export ─────────────────────────────────────────────────────────────


@router.get("/export", summary="Export the inventory as Excel or CSV")
async def export_accounts(
    export_format: Literal["xlsx", "csv"] = Query("xlsx", alias="format"),
    application: str | None = Query(None),
    account_type: str | None = Query(None),
    directory: str | None = Query(None),
    view: Literal["expired", "expiring", "failing"] | None = Query(None),
    q: str | None = Query(None, max_length=200),
    _user: UserContext = Depends(_VIEW),
    db: AsyncSession = Depends(get_db),
) -> Response:
    """The rows the grid is showing: the same filters, every page."""
    service = _service(db)
    today = date.today()
    rows = filter_accounts(
        await service.list_accounts(),
        AccountFilter(application=application, account_type=account_type, directory=directory, view=view, q=q),
        today=today,
    )
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M")
    if export_format == "csv":
        content, media_type = export_csv(rows, today=today), "text/csv; charset=utf-8"
    else:
        content, media_type = export_xlsx(rows, today=today, generated_at=datetime.now(UTC)), _XLSX
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="credential-accounts-{stamp}.{export_format}"'},
    )
