"""Tools — operational self-service checks.

Today this is credential validation: does an ITSERVICES / TESTITSERVICES
domain password, a JFrog token or an AAF account password still work?  It
complements Infrastructure Alerts → Expiry Tracking, which knows when a
credential is *due* to expire but not whether it still authenticates.

Authorization: WRITE plus the ``credential_check`` capability.  A check is a
POST that changes nothing anywhere, but a failed bind counts against the AD
lockout policy, so it is deliberately not open to READ users and is
revocable on its own from the Permissions UI.

Every attempt is audited — target and outcome, never the secret.  The
service refuses rate-limit and lockout-guard breaches before any credential
leaves the portal, and those refusals are audited too.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.core.authz import require_capability
from app.core.database import get_db
from app.models.auth import UserContext
from app.schemas.tools import (
    AafCheckRequest,
    CredentialCheckHistoryEntry,
    CredentialCheckResponse,
    DomainCheckRequest,
    JFrogCheckRequest,
)
from app.services.credential_check_service import (
    CheckKind,
    CheckOutcome,
    CredentialCheckError,
    CredentialCheckService,
)

logger = structlog.get_logger(__name__)
router = APIRouter()

_CHECK_CAPABILITY = require_capability("credential_check")


async def _service(db: AsyncSession = Depends(get_db)) -> CredentialCheckService:
    return CredentialCheckService(db)


def _token_fingerprint(token: str) -> str:
    """Stable, non-reversible label for a token.

    The lockout guard and the history grid both need to recognise "the same
    token again" without the portal ever holding the token itself.
    """
    return f"jfrog-token:{hashlib.sha256(token.encode()).hexdigest()[:12]}"


async def _run_check(
    service: CredentialCheckService,
    request: Request,
    user: UserContext,
    *,
    kind: CheckKind,
    target: str,
    check,
) -> CredentialCheckResponse:
    """Guard, run, audit — the same order for every credential type."""
    ip = request.client.host if request.client else None

    try:
        await service.assert_within_limits(user, target)
        outcome: CheckOutcome = await check()
    except CredentialCheckError as exc:
        refused = CheckOutcome(valid=False, status=exc.status, message=str(exc))
        await service.record(user=user, ip=ip, kind=kind, target=target, outcome=refused)
        # 429 for the two volume guards, 400 for a configuration problem the
        # operator has to fix; neither says anything about the credential.
        code = (
            status.HTTP_429_TOO_MANY_REQUESTS
            if exc.status in ("rate_limited", "lockout_guard")
            else status.HTTP_400_BAD_REQUEST
        )
        raise HTTPException(status_code=code, detail=str(exc))

    await service.record(user=user, ip=ip, kind=kind, target=target, outcome=outcome)
    logger.info(
        "credential_checked",
        kind=kind,
        target=target,
        outcome=outcome.status,
        user_id=user.user_id,
    )
    return CredentialCheckResponse(
        kind=kind,
        target=target,
        valid=outcome.valid,
        status=outcome.status,
        message=outcome.message,
        checked_at=datetime.utcnow(),
        details=outcome.details,
    )


@router.post(
    "/credential-checks/domain",
    response_model=CredentialCheckResponse,
    summary="Check an ITSERVICES / TESTITSERVICES domain password",
)
async def check_domain_password(
    payload: DomainCheckRequest,
    request: Request,
    user: UserContext = Depends(_CHECK_CAPABILITY),
    service: CredentialCheckService = Depends(_service),
) -> CredentialCheckResponse:
    target = f"{payload.domain}\\{payload.username}"
    return await _run_check(
        service,
        request,
        user,
        kind="domain",
        target=target,
        check=lambda: service.check_domain(
            payload.domain,
            payload.username,
            payload.password.get_secret_value(),
        ),
    )


@router.post(
    "/credential-checks/jfrog",
    response_model=CredentialCheckResponse,
    summary="Check a JFrog Artifactory token",
)
async def check_jfrog_token(
    payload: JFrogCheckRequest,
    request: Request,
    user: UserContext = Depends(_CHECK_CAPABILITY),
    service: CredentialCheckService = Depends(_service),
) -> CredentialCheckResponse:
    token = payload.token.get_secret_value()
    return await _run_check(
        service,
        request,
        user,
        kind="jfrog",
        target=_token_fingerprint(token),
        check=lambda: service.check_jfrog(token),
    )


@router.post(
    "/credential-checks/aaf",
    response_model=CredentialCheckResponse,
    summary="Check an AAF account password",
)
async def check_aaf_password(
    payload: AafCheckRequest,
    request: Request,
    user: UserContext = Depends(_CHECK_CAPABILITY),
    service: CredentialCheckService = Depends(_service),
) -> CredentialCheckResponse:
    return await _run_check(
        service,
        request,
        user,
        kind="aaf",
        target=payload.account,
        check=lambda: service.check_aaf(
            payload.environment,
            payload.account,
            payload.password.get_secret_value(),
        ),
    )


@router.get(
    "/credential-checks/history",
    response_model=list[CredentialCheckHistoryEntry],
    summary="Past credential checks (your own; everyone's for a Super Admin)",
)
async def credential_check_history(
    user: UserContext = Depends(get_current_user),
    service: CredentialCheckService = Depends(_service),
) -> list[CredentialCheckHistoryEntry]:
    rows = await service.history(user)
    return [CredentialCheckHistoryEntry.model_validate(row) for row in rows]
