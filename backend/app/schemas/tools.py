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


class DomainCheckRequest(BaseModel):
    """One domain account.  Deliberately singular — never a list."""

    domain: DomainName
    username: str = Field(min_length=1, max_length=128, description="sAMAccountName, e.g. m52142")
    password: SecretStr


class JFrogCheckRequest(BaseModel):
    token: SecretStr = Field(description="JFrog access token or API key")


class AafCheckRequest(BaseModel):
    environment: AafEnvironment
    account: str = Field(
        min_length=1,
        max_length=256,
        description="Fully qualified AAF identity, e.g. m52142@com.att.attcc",
    )
    password: SecretStr


class CredentialCheckResponse(BaseModel):
    """Outcome of a single check.  Carries no credential material."""

    kind: Literal["domain", "jfrog", "aaf"]
    target: str = Field(description="What was checked — an account name or a token fingerprint")
    valid: bool
    status: str = Field(description="valid | invalid | expired | locked | disabled | must_change | denied | error")
    message: str
    checked_at: datetime
    details: dict = Field(default_factory=dict)


class CredentialCheckHistoryEntry(BaseModel):
    id: int
    checked_at: datetime | None = None
    user_email: str | None = None
    target: str | None = None
    kind: str = ""
    status: str = ""
    message: str = ""
    valid: bool = False
