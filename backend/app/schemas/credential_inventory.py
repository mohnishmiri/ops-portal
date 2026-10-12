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


class CredentialAccountIn(BaseModel):
    """What a person types in: which account, listed under which application.

    Nothing here is read from a directory, and nothing a directory reports is
    here.  The name the directory holds for the account, its password expiry,
    when the password last changed, when it was last used and how many
    sign-ins have failed are all written by a check — never typed in.
    """

    application: str = Field(min_length=1, max_length=200)
    app_code: str | None = Field(default=None, max_length=32, description="MOTS / app ID, e.g. 31599")
    account_type: AccountType
    directory: str = Field(description="ITSERVICES / TESTITSERVICES, prod / nonprod, or bronze / gold")
    account_name: str = Field(min_length=1, max_length=256, description="sAMAccountName, AAF identity or JFrog user")
    reset_url: str | None = Field(default=None, max_length=1000, description="Where this account's password is reset")
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("application", "account_name", mode="before")
    @classmethod
    def _strip_required(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("app_code", "notes", "reset_url", mode="before")
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
    def _directory_fits_type(self) -> CredentialAccountIn:
        allowed = DIRECTORIES[self.account_type]
        match = next((d for d in allowed if d.lower() == self.directory.strip().lower()), None)
        if match is None:
            raise ValueError(f"Directory for a {self.account_type} account must be one of: {', '.join(allowed)}")
        self.directory = match
        return self


class CredentialAccountCreate(CredentialAccountIn):
    """Add an account.

    The extra fields carry what a check has *just* read about the account, so
    listing it from a check result keeps that answer instead of showing an
    empty row until someone checks it again.  The Add form leaves them unset,
    and editing never touches them: from then on only a check writes them.
    """

    owner: str | None = Field(default=None, max_length=255, description="The directory's name for the account")
    expiry_date: date | None = None
    never_expires: bool = False
    password_changed_date: date | None = None
    last_login_date: date | None = None
    failed_logins: int | None = Field(default=None, ge=0, le=1_000_000)

    @field_validator("owner", mode="before")
    @classmethod
    def _strip_owner(cls, value: object) -> object:
        return _clean(value) if isinstance(value, str) or value is None else value

    @model_validator(mode="after")
    def _never_or_date(self) -> CredentialAccountCreate:
        if self.never_expires:
            self.expiry_date = None
        return self


class CredentialAccountImportRow(CredentialAccountIn):
    """One imported row — the same fields the Add form takes.

    A file may well carry an Expiry Date or Owner column; those are ignored
    rather than imported, because a check reads them from the directory and
    would overwrite anything the file said.
    """


class CredentialAccountOut(BaseModel):
    id: int
    application: str
    app_code: str | None
    account_type: AccountType
    directory: str
    account_name: str
    owner: str | None = Field(default=None, description="The directory's name for the account, from a check")
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
