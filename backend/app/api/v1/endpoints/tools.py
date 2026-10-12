"""Tools — credential checks, surfaced as a tab under Compliance.

Does an ITSERVICES / TESTITSERVICES domain password, a JFrog username and
token, or an AAF account password still work?  Compliance -> Expiry Tracking
knows when a credential is *due* to expire but not whether it still
authenticates.

The credential is never stored or logged: the request carries it, the
response carries the verdict plus whatever the source reports about expiry
and last use.  There is no audit row and no history of checks.  The one
thing kept: when the checked account is in the inventory below the checks,
its row records the verdict and the reported expiry / last sign-in, so the
inventory stays current without anyone retyping dates.

Authorization is the WRITE role plus the ``credential_check`` capability.  A
check alters nothing anywhere, but a failed bind counts against the AD
lockout policy, so it is deliberately not open to READ users and stays
revocable on its own from the Permissions UI.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime

import structlog
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.authz import require_capability
from app.core.database import get_db
from app.models.auth import UserContext
from app.schemas.tools import (
    AafCheckRequest,
    CredentialCheckResponse,
    DomainCheckRequest,
    JFrogCheckRequest,
)
from app.services.credential_check_service import (
    JFROG_INSTANCE_LABELS,
    CheckKind,
    CheckOutcome,
    CredentialCheckError,
    CredentialCheckService,
    assert_target_not_blocked,
    record_outcome,
)
from app.services.credential_inventory_service import CredentialInventoryService

logger = structlog.get_logger(__name__)
router = APIRouter()

_CHECK_CAPABILITY = require_capability("credential_check")
_service = CredentialCheckService()


async def _record_in_inventory(
    db: AsyncSession | None,
    *,
    kind: CheckKind,
    directory: str,
    account_name: str,
    outcome: CheckOutcome,
    user: UserContext,
) -> bool:
    """Save the verdict on the account's inventory row, if it has one.  Never fails the check."""
    if db is None:
        return False
    try:
        return await CredentialInventoryService(db).record_check(
            account_type=kind,
            directory=directory,
            account_name=account_name,
            outcome=outcome,
            checked_by=user.email or user.user_id,
        )
    except Exception as exc:
        await db.rollback()
        logger.warning("credential_check_inventory_update_failed", kind=kind, error=str(exc)[:200])
        return False


async def _run_check(
    *,
    kind: CheckKind,
    directory: str,
    account_name: str,
    target: str,
    check: Callable[[], Awaitable[CheckOutcome]],
    user: UserContext,
    db: AsyncSession | None,
) -> CredentialCheckResponse:
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
    inventory_updated = await _record_in_inventory(
        db, kind=kind, directory=directory, account_name=account_name, outcome=outcome, user=user
    )

    return CredentialCheckResponse(
        kind=kind,
        target=target,
        valid=outcome.valid,
        status=outcome.status,
        message=outcome.message,
        checked_at=datetime.utcnow(),
        details=outcome.details,
        account=outcome.account,
        inventory_updated=inventory_updated,
        directory=directory,
        account_name=account_name.strip(),
    )


@router.post(
    "/credential-checks/domain",
    response_model=CredentialCheckResponse,
    summary="Check an ITSERVICES / TESTITSERVICES domain password",
)
async def check_domain_password(
    payload: DomainCheckRequest,
    user: UserContext = Depends(_CHECK_CAPABILITY),
    db: AsyncSession = Depends(get_db),
) -> CredentialCheckResponse:
    return await _run_check(
        kind="domain",
        directory=payload.domain,
        account_name=payload.username,
        target=f"{payload.domain}\\{payload.username}",
        user=user,
        db=db,
        check=lambda: _service.check_domain(
            payload.domain,
            payload.username,
            payload.password.get_secret_value(),
        ),
    )


@router.post(
    "/credential-checks/jfrog",
    response_model=CredentialCheckResponse,
    summary="Check a JFrog Artifactory (Bronze or Gold) username and token",
)
async def check_jfrog_token(
    payload: JFrogCheckRequest,
    user: UserContext = Depends(_CHECK_CAPABILITY),
    db: AsyncSession = Depends(get_db),
) -> CredentialCheckResponse:
    username = payload.username.strip()
    return await _run_check(
        kind="jfrog",
        directory=payload.instance,
        account_name=username,
        # Bronze and Gold are separate instances: separate lockout counts.
        target=f"{username} ({JFROG_INSTANCE_LABELS[payload.instance]})",
        user=user,
        db=db,
        check=lambda: _service.check_jfrog(username, payload.token.get_secret_value(), payload.instance),
    )


@router.post(
    "/credential-checks/aaf",
    response_model=CredentialCheckResponse,
    summary="Check an AAF account password",
)
async def check_aaf_password(
    payload: AafCheckRequest,
    user: UserContext = Depends(_CHECK_CAPABILITY),
    db: AsyncSession = Depends(get_db),
) -> CredentialCheckResponse:
    account = payload.account.strip()
    return await _run_check(
        kind="aaf",
        directory=payload.environment,
        account_name=account,
        target=account,
        user=user,
        db=db,
        check=lambda: _service.check_aaf(
            payload.environment,
            account,
            payload.password.get_secret_value(),
        ),
    )
