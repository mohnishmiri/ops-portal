"""
Access Control and Subscription Filter Middleware for granular RBAC/ABAC.
"""

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.models.auth import UserContext
from app.models.database import Permission, Resource


class AccessControlMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, db_session_factory):
        super().__init__(app)
        self.db_session_factory = db_session_factory

    async def dispatch(self, request: Request, call_next):
        user: UserContext = request.state.user if hasattr(request.state, "user") else None
        if not user:
            return await call_next(request)

        # Example: Extract resource info from route (customize as needed)
        route_name = request.scope.get("endpoint").__name__
        resource_name = route_name  # Map route to resource_name as per your convention
        method = request.method.lower()
        permission_type = "view" if method == "get" else "edit"

        async with self.db_session_factory() as db:
            resource = await db.execute(Resource.__table__.select().where(Resource.resource_name == resource_name))
            resource = resource.scalar_one_or_none()
            if not resource:
                # If resource not registered, allow by default (or deny, per policy)
                return await call_next(request)

            # Check permissions for user and roles
            allowed = False
            # User-based
            perm = await db.execute(
                Permission.__table__.select().where(
                    (Permission.subject_type == "user")
                    & (Permission.subject_id == user.user_id)
                    & (Permission.resource_id == resource.id)
                    & (Permission.permission_type == permission_type)
                )
            )
            if perm.scalar_one_or_none():
                allowed = True
            # Role-based
            for role in user.roles:
                perm = await db.execute(
                    Permission.__table__.select().where(
                        (Permission.subject_type == "role")
                        & (Permission.subject_id == role.value)
                        & (Permission.resource_id == resource.id)
                        & (Permission.permission_type == permission_type)
                    )
                )
                if perm.scalar_one_or_none():
                    allowed = True
                    break
            if not allowed:
                raise HTTPException(status_code=403, detail="Access denied for this resource.")
        return await call_next(request)


class SubscriptionFilterMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, db_session_factory):
        super().__init__(app)
        self.db_session_factory = db_session_factory

    async def dispatch(self, request: Request, call_next):
        user: UserContext = request.state.user if hasattr(request.state, "user") else None
        if not user:
            return await call_next(request)
        # Enforce subscription filtering
        selected_sub = request.query_params.get("subscription_id")
        if selected_sub and user.allowed_subscriptions and selected_sub not in user.allowed_subscriptions:
            raise HTTPException(status_code=403, detail="Subscription access denied.")
        return await call_next(request)
