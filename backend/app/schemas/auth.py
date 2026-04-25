"""
Pydantic models for Authentication, Authorization, and RBAC.
"""

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class UserRole(str, Enum):
    """RBAC roles for the Ops Portal."""

    ADMIN = "admin"
    WRITE = "write"
    READ = "read"


class TokenClaims(BaseModel):
    """Decoded Azure AD JWT token claims."""

    sub: str = Field(description="Subject / User ID")
    oid: str = Field(description="Object ID in Azure AD")
    name: str = Field(default="Unknown")
    email: str = Field(default="")
    preferred_username: str = Field(default="")
    roles: list[str] = Field(default_factory=list, description="App roles from Azure AD")
    groups: list[str] = Field(default_factory=list, description="Group memberships")
    tenant_id: str = Field(alias="tid", default="")
    iss: str = Field(default="", description="Token issuer")
    aud: str = Field(default="", description="Token audience")
    exp: int = Field(description="Token expiration timestamp")
    iat: int = Field(description="Token issued-at timestamp")

    model_config = {"populate_by_name": True}


class UserContext(BaseModel):
    """Authenticated user context available throughout request lifecycle."""

    user_id: str
    object_id: str
    display_name: str
    email: str
    roles: list[UserRole]
    raw_roles: list[str]
    tenant_id: str
    allowed_subscriptions: list[str] = Field(
        default_factory=list,
        description="Subscriptions this user can access (empty = all)",
    )

    def has_role(self, role: UserRole) -> bool:
        """Check if user has a specific role."""
        return role in self.roles

    @property
    def is_admin(self) -> bool:
        return UserRole.ADMIN in self.roles

    @property
    def can_write(self) -> bool:
        return UserRole.ADMIN in self.roles or UserRole.WRITE in self.roles


class AuditLogEntry(BaseModel):
    """Audit log entry for all API operations."""

    timestamp: datetime
    user_id: str
    user_email: str
    action: str
    resource_path: str
    method: str
    status_code: int
    client_ip: str
    user_agent: str
    duration_ms: float
    details: dict | None = None


class SubscriptionAccess(BaseModel):
    """Subscription access configuration."""

    subscription_id: str
    subscription_name: str
    allowed_roles: list[UserRole]
    enabled: bool = True
