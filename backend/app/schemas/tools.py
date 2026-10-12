"""Schemas for the Tools module (credential checks).

Secrets are ``SecretStr`` so they cannot be printed, logged or serialised by
accident — ``model_dump()`` renders them as ``**********``.  Nothing here
echoes a secret back to the caller.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, SecretStr

DomainName = Literal["ITSERVICES", "TESTITSERVICES"]
AafEnvironment = Literal["prod", "nonprod"]
JFrogInstance = Literal["bronze", "gold"]


class DomainCheckRequest(BaseModel):
    """One domain account.  Deliberately singular — never a list."""

    domain: DomainName
    username: str = Field(min_length=1, max_length=128, description="sAMAccountName, e.g. m52142")
    password: SecretStr


class JFrogCheckRequest(BaseModel):
    instance: JFrogInstance = Field(default="bronze", description="Artifactory Bronze or Gold")
    username: str = Field(
        min_length=1,
        max_length=256,
        description="JFrog user the token belongs to, e.g. m52142@att.com",
    )
    token: SecretStr = Field(description="JFrog identity/access token or API key")


class AafCheckRequest(BaseModel):
    environment: AafEnvironment
    account: str = Field(
        min_length=1,
        max_length=256,
        description="Fully qualified AAF identity, e.g. m52142@com.att.attcc",
    )
    password: SecretStr


class CredentialAccountDetails(BaseModel):
    """What the source reports about the credential beyond yes / no.

    Every field is optional: AD, Artifactory and AAF each expose a different
    subset, and ``None`` means "not reported", never "none".  Datetimes are
    UTC.
    """

    display_name: str | None = Field(default=None, description="AD display name, or the JFrog token description")
    expires_at: datetime | None = Field(default=None, description="When this password / token stops working")
    never_expires: bool = Field(default=False, description="The source says explicitly that it does not expire")
    last_changed_at: datetime | None = Field(default=None, description="Password last set, or token issued")
    last_used_at: datetime | None = None
    last_used_note: str | None = Field(
        default=None,
        description="How far to trust last_used_at, or why it is not shown",
    )
    account_expires_at: datetime | None = Field(
        default=None,
        description="AD account (not password) expiry; None when the account does not expire",
    )
    failed_sign_ins: int | None = Field(
        default=None,
        description="Failed sign-ins counted against the lockout policy on the domain controller that answered",
    )
    last_failed_at: datetime | None = Field(default=None, description="When a wrong password was last presented")
    failed_sign_ins_note: str | None = None
    notes: list[str] = Field(default_factory=list, description="Other caveats about where the details came from")


class CredentialCheckResponse(BaseModel):
    """Outcome of a single check.  Carries no credential material."""

    kind: Literal["domain", "jfrog", "aaf"]
    target: str = Field(description="The account or user that was checked")
    valid: bool
    status: str = Field(description="valid | invalid | expired | locked | disabled | must_change | denied | error")
    message: str
    checked_at: datetime
    details: dict = Field(default_factory=dict)
    account: CredentialAccountDetails | None = Field(
        default=None,
        description="Expiry / last-used details, when the source would report them",
    )
    inventory_updated: bool = Field(
        default=False,
        description="The account is in the inventory and its row now holds this verdict",
    )
    # What was checked, so the page can add the account to the inventory
    # without re-reading a form that may have changed since.
    directory: str | None = Field(
        default=None,
        description="ITSERVICES / TESTITSERVICES, prod / nonprod, or bronze / gold",
    )
    account_name: str | None = None
