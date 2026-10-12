"""Schemas for the credential account inventory (Tools → Credential Check).

An inventory row describes a service account — never its password or token.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator, model_validator

AccountType = Literal["domain", "aaf", "jfrog"]

# Where each type of account can live.  The first is the default when an
# import names the type but not the directory.
DIRECTORIES: dict[str, tuple[str, ...]] = {
    "domain": ("ITSERVICES", "TESTITSERVICES"),
    "aaf": ("prod", "nonprod"),
    "jfrog": ("bronze", "gold"),
}


def _clean(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


class _AccountFields(BaseModel):
    """Fields shared by the form and the import."""

    application: str = Field(min_length=1, max_length=200)
    app_code: str | None = Field(default=None, max_length=32)
    account_type: AccountType
    directory: str = Field(description="ITSERVICES / TESTITSERVICES, prod / nonprod, or bronze / gold")
    account_name: str = Field(min_length=1, max_length=256, description="sAMAccountName, AAF identity or JFrog user")
    owner: str | None = Field(default=None, max_length=255)
    expiry_date: date | None = None
    password_changed_date: date | None = None
    last_login_date: date | None = None
    failed_logins: int | None = Field(default=None, ge=0, le=1_000_000)
    reset_url: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("application", "account_name", mode="before")
    @classmethod
    def _strip_required(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("app_code", "owner", "notes", "reset_url", mode="before")
    @classmethod
    def _strip_optional(cls, value: object) -> object:
        return _clean(value) if isinstance(value, str) or value is None else value

    @field_validator("reset_url")
    @classmethod
    def _http_only(cls, value: str | None) -> str | None:
        # Rendered as a link: anything but http(s) — javascript:, data: — is refused.
        if value is None:
            return None
        parts = urlsplit(value)
        if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
            raise ValueError("Reset link must be an http:// or https:// URL")
        return value

    @model_validator(mode="after")
    def _directory_fits_type(self) -> _AccountFields:
        allowed = DIRECTORIES[self.account_type]
        match = next((d for d in allowed if d.lower() == self.directory.strip().lower()), None)
        if match is None:
            raise ValueError(f"Directory for a {self.account_type} account must be one of: {', '.join(allowed)}")
        self.directory = match
        return self


class CredentialAccountIn(_AccountFields):
    """Add / edit form.  Every field is replaced on save."""

    never_expires: bool = False

    @model_validator(mode="after")
    def _never_or_date(self) -> CredentialAccountIn:
        if self.never_expires:
            self.expiry_date = None
        return self


class CredentialAccountImportRow(_AccountFields):
    """One imported row.

    ``None`` means "the file left this blank": an import fills in and
    corrects, it never erases what is already recorded.
    """

    never_expires: bool | None = None


class CredentialAccountOut(BaseModel):
    id: int
    application: str
    app_code: str | None
    account_type: AccountType
    directory: str
    account_name: str
    owner: str | None
    expiry_date: date | None
    never_expires: bool
    password_changed_date: date | None
    last_login_date: date | None
    failed_logins: int | None
    reset_url: str | None
    notes: str | None
    last_checked_at: datetime | None
    last_check_status: str | None
    last_checked_by: str | None
    created_by: str | None
    created_at: datetime | None
    updated_by: str | None
    updated_at: datetime | None

    model_config = {"from_attributes": True}


class ImportPreviewRow(BaseModel):
    row: int = Field(description="Spreadsheet row number")
    action: Literal["create", "update", "invalid"]
    account: CredentialAccountImportRow | None = None
    label: str = Field(description="What the row names, for the preview — valid or not")
    errors: list[str] = Field(default_factory=list)


class ImportPreview(BaseModel):
    rows: list[ImportPreviewRow]
    total: int
    create_count: int
    update_count: int
    invalid_count: int


class ImportApplyRequest(BaseModel):
    accounts: list[CredentialAccountImportRow] = Field(min_length=1, max_length=2000)


class ImportApplyResult(BaseModel):
    created: int
    updated: int
