"""
Session bootstrap endpoint — the frontend's authorization gate.

This router is mounted **outside** ``api_router`` on purpose.  Every
``/api/v1/*`` route inherits ``enforce_portal_access``, which returns 403 for
an authenticated-but-unentitled identity.  That is correct for protected APIs
but useless for the UI, which needs a route that can say *"you are
authenticated, and you are not authorized"* so it can render Access Denied
instead of a broken shell.

Consequently this endpoint:
  • requires a valid token (401 if missing/invalid/expired)
  • returns 200 with ``authorized: false`` when the identity holds no role
  • never returns subscription, cluster, or any other privileged data

Nothing here initializes privileged clients or leaks inventory, satisfying the
"do not load data for unauthorized users" requirement.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_authenticated_identity
from app.core.authz import granted_capabilities
from app.core.database import get_db
from app.models.auth import UserContext

router = APIRouter()


@router.get("/session", summary="Authentication + portal authorization status")
async def get_session(
    identity: UserContext | None = Depends(get_authenticated_identity),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Report whether the caller is authenticated and authorized for the portal.

    Response shape (contract consumed by the frontend auth gate)::

        {
          "authenticated": true,
          "authorized": true,
          "user": {"user_id": ..., "display_name": ..., "email": ...},
          "roles": ["write"],
          "is_admin": false,
          "can_write": true,
          "permissions": ["AKS_VIEW", "AKS_POD_DELETE", ...]
        }

    ``permissions`` is upper-cased so the frontend contract reads as documented
    (``AKS_POD_DELETE``) while the database keeps the lower-case resource
    naming used everywhere else in the registry.
    """
    if identity is None:
        # Only reachable for the signed dashboard launch/proxy carve-out,
        # which never calls this endpoint.
        return {"authenticated": False, "authorized": False, "permissions": []}

    authorized = bool(identity.roles)

    if not authorized:
        # Authenticated but unentitled: report the denial and nothing else.
        return {
            "authenticated": True,
            "authorized": False,
            "user": {
                "user_id": identity.user_id,
                "display_name": identity.display_name,
                "email": identity.email,
            },
            "roles": [],
            "is_admin": False,
            "can_write": False,
            "permissions": [],
        }

    capabilities = await granted_capabilities(db, identity)

    return {
        "authenticated": True,
        "authorized": True,
        "user": {
            "user_id": identity.user_id,
            "display_name": identity.display_name,
            "email": identity.email,
        },
        "roles": [r.value for r in identity.roles],
        "is_admin": identity.is_admin,
        "can_write": identity.can_write,
        "permissions": [c.upper() for c in capabilities],
    }
