"""Tools — credential checks, surfaced as a tab under Compliance.

Does an ITSERVICES / TESTITSERVICES domain password, a JFrog username and
token, or an AAF account password still work?  Compliance -> Expiry Tracking
knows when a credential is *due* to expire but not whether it still
authenticates.

Nothing is stored: no audit row, no history.  The request carries the
credential, the response carries the verdict — plus whatever the source
reports about expiry and last use — and that is the end of it.

Authorization is the WRITE role plus the ``credential_check`` capability.  A
check alters nothing anywhere, but a failed bind counts against the AD
lockout policy, so it is deliberately not open to READ users and stays
revocable on its own from the Permissions UI.
"""

from __future__ import annotations

from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, status

from app.core.authz import require_capability
from app.models.auth import UserContext
from app.schemas.tools import (
    AafCheckRequest,
    CredentialCheckResponse,
    DomainCheckRequest,
    JFrogCheckRequest,
)
from app.services.credential_check_service import (
    CheckKind,
    CheckOutcome,
    CredentialCheckError,
    CredentialCheckService,
    assert_target_not_blocked,
    record_outcome,
)

logger = structlog.get_logger(__name__)
router = APIRouter()

_CHECK_CAPABILITY = require_capability("credential_check")
_service = CredentialCheckService()


async def _run_check(*, kind: CheckKind, target: str, check) -> CredentialCheckResponse:
    """Guard, run, report — the same shape for every credential type."""
    try:
        assert_target_not_blocked(target)
        outcome: CheckOutcome = await check()
    except CredentialCheckError as exc:
        # 429 for the lockout guard, 400 for a configuration problem the
        # operator has to fix; neither says anything about the credential.
        code = status.HTTP_429_TOO_MANY_REQUESTS if exc.status == "lockout_guard" else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=code, detail=str(exc))

    record_outcome(target, outcome)
    # Target and verdict only — the credential is never logged.
    logger.info("credential_checked", kind=kind, target=target, outcome=outcome.status)

    return CredentialCheckResponse(
        kind=kind,
        target=target,
        valid=outcome.valid,
        status=outcome.status,
        message=outcome.message,
        checked_at=datetime.utcnow(),
        details=outcome.details,
        account=outcome.account,
    )


@router.post(
    "/credential-checks/domain",
    response_model=CredentialCheckResponse,
    summary="Check an ITSERVICES / TESTITSERVICES domain password",
)
async def check_domain_password(
    payload: DomainCheckRequest,
    _user: UserContext = Depends(_CHECK_CAPABILITY),
) -> CredentialCheckResponse:
    return await _run_check(
        kind="domain",
        target=f"{payload.domain}\\{payload.username}",
        check=lambda: _service.check_domain(
            payload.domain,
            payload.username,
            payload.password.get_secret_value(),
        ),
    )


@router.post(
    "/credential-checks/jfrog",
    response_model=CredentialCheckResponse,
    summary="Check a JFrog Artifactory username and token",
)
async def check_jfrog_token(
    payload: JFrogCheckRequest,
    _user: UserContext = Depends(_CHECK_CAPABILITY),
) -> CredentialCheckResponse:
    username = payload.username.strip()
    return await _run_check(
        kind="jfrog",
        target=username,
        check=lambda: _service.check_jfrog(username, payload.token.get_secret_value()),
    )


@router.post(
    "/credential-checks/aaf",
    response_model=CredentialCheckResponse,
    summary="Check an AAF account password",
)
async def check_aaf_password(
    payload: AafCheckRequest,
    _user: UserContext = Depends(_CHECK_CAPABILITY),
) -> CredentialCheckResponse:
    account = payload.account.strip()
    return await _run_check(
        kind="aaf",
        target=account,
        check=lambda: _service.check_aaf(
            payload.environment,
            account,
            payload.password.get_secret_value(),
        ),
    )
