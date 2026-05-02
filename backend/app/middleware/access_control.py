"""
Access Control Middleware for granular RBAC/ABAC.

The middleware checks whether the authenticated user (set on request.state.user
by the auth dependency) has permission to access the resource that corresponds
to the current request path.

Resource matching strategy (in priority order):
  1. Exact route_path match against ``resources.route_path``
  2. Prefix match (longest wins)
  3. If no resource is registered for the path → allow by default (open)

Admin users bypass all resource checks.

This middleware deliberately runs *after* the FastAPI router has resolved the
endpoint, so ``request.state.user`` is already populated by the auth
dependency.  Routes that do not set ``request.state.user`` (health checks,
metrics, login) are skipped.
"""

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.models.auth import UserContext
from app.models.database import Permission, Resource

# Paths that are always public — never blocked by this middleware
_PUBLIC_PATH_PREFIXES = ("/healthz", "/readyz", "/metrics", "/api/docs", "/api/redoc", "/openapi")


class AccessControlMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, db_session_factory):
        super().__init__(app)
        self.db_session_factory = db_session_factory

    async def dispatch(self, request: Request, call_next):
        # Skip public paths
        path = request.url.path
        if any(path.startswith(pfx) for pfx in _PUBLIC_PATH_PREFIXES):
            return await call_next(request)

        user: UserContext | None = getattr(request.state, "user", None)
        if not user:
            # No user context yet (unauthenticated or auth dependency not yet run)
            return await call_next(request)

        # Admins bypass all resource-level checks
        if user.is_admin:
            return await call_next(request)

        method = request.method.upper()
        permission_type = "view" if method == "GET" else "edit"

        async with self.db_session_factory() as db:
            from sqlalchemy import select

            # Find the best-matching resource for this path
            result = await db.execute(select(Resource).where(Resource.route_path.isnot(None)))
            resources: list[Resource] = result.scalars().all()

            matched_resource: Resource | None = None
            best_match_len = -1
            for r in resources:
                route = r.route_path or ""
                if (path == route or path.startswith(route.rstrip("/") + "/")) and len(route) > best_match_len:
                    matched_resource = r
                    best_match_len = len(route)

            if matched_resource is None:
                # No registered resource for this path → open by default
                return await call_next(request)

            # Collect all resource IDs to check: the matched resource + its parent module
            resource_ids_to_check: list[int] = [matched_resource.id]
            if matched_resource.parent_id:
                resource_ids_to_check.append(matched_resource.parent_id)

            role_values = [role.value for role in user.roles]

            allowed = False
            for res_id in resource_ids_to_check:
                # User-specific check
                perm_result = await db.execute(
                    select(Permission).where(
                        (Permission.subject_type == "user")
                        & (Permission.subject_id == user.user_id)
                        & (Permission.resource_id == res_id)
                        & (Permission.permission_type == permission_type)
                    )
                )
                if perm_result.scalar_one_or_none():
                    allowed = True
                    break

                # Role-based check
                for role_val in role_values:
                    perm_result = await db.execute(
                        select(Permission).where(
                            (Permission.subject_type == "role")
                            & (Permission.subject_id == role_val)
                            & (Permission.resource_id == res_id)
                            & (Permission.permission_type == permission_type)
                        )
                    )
                    if perm_result.scalar_one_or_none():
                        allowed = True
                        break
                if allowed:
                    break

            if not allowed:
                raise HTTPException(
                    status_code=403,
                    detail=f"Access denied: insufficient permissions for '{matched_resource.resource_name}'.",
                )

        return await call_next(request)


class SubscriptionFilterMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, db_session_factory):
        super().__init__(app)
        self.db_session_factory = db_session_factory

    async def dispatch(self, request: Request, call_next):
        user: UserContext | None = getattr(request.state, "user", None)
        if not user:
            return await call_next(request)
        selected_sub = request.query_params.get("subscription_id")
        if selected_sub and user.allowed_subscriptions and selected_sub not in user.allowed_subscriptions:
            raise HTTPException(status_code=403, detail="Subscription access denied.")
        return await call_next(request)
