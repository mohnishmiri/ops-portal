"""Auth API endpoint — returns the authenticated user's context and roles."""

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.models.auth import UserContext

router = APIRouter()


@router.get(
    "/me",
    summary="Current user context",
    response_model=None,
)
async def get_me(user: UserContext = Depends(get_current_user)) -> dict:
    """Return the authenticated user's identity and mapped roles."""
    return {
        "user_id": user.user_id,
        "display_name": user.display_name,
        "email": user.email,
        "roles": [r.value for r in user.roles],
        "is_admin": user.is_admin,
        "can_write": user.can_write,
        "tenant_id": user.tenant_id,
    }
