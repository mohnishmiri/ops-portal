"""Helpers for reading admin-managed configuration values from the database."""

from __future__ import annotations

import json
from collections.abc import Iterable
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.database import AdminConfig

CORS_CONFIG_KEY = "cors_origins"


def _split_origin_string(raw_value: str) -> list[str]:
    lines = [line.strip() for line in raw_value.replace(",", "\n").splitlines()]
    return [line for line in lines if line]


def parse_cors_origins(
    raw_value: str | Iterable[str] | None,
    *,
    strict: bool = False,
) -> list[str]:
    """Parse a CORS origin list from JSON, CSV, newline text, or an iterable."""
    if raw_value is None:
        return []

    values: list[str]
    if isinstance(raw_value, str):
        candidate = raw_value.strip()
        if not candidate:
            return []

        if candidate.startswith("["):
            try:
                loaded = json.loads(candidate)
            except json.JSONDecodeError:
                loaded = _split_origin_string(candidate)
            else:
                if isinstance(loaded, list):
                    values = [str(item).strip() for item in loaded]
                else:
                    values = _split_origin_string(candidate)
                candidate = ""
        if candidate:
            values = _split_origin_string(candidate)
    else:
        values = [str(item).strip() for item in raw_value if str(item).strip()]

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        origin = value.rstrip("/")
        if not origin:
            continue
        if origin == "*":
            if strict:
                raise ValueError("Wildcard CORS origins are not allowed.")
            continue

        parsed = urlparse(origin)
        is_valid = parsed.scheme in {"http", "https"} and bool(parsed.netloc) and parsed.path in {"", "/"}
        if not is_valid:
            if strict:
                raise ValueError(f"Invalid CORS origin: {value}")
            continue

        if origin not in seen:
            seen.add(origin)
            normalized.append(origin)

    return normalized


def serialize_cors_origins(origins: Iterable[str]) -> str:
    """Serialize normalized CORS origins for DB storage."""
    return json.dumps(parse_cors_origins(origins, strict=True))


async def get_admin_config_value(
    db: AsyncSession | None,
    key: str,
    default: str | None = None,
) -> str | None:
    """Return a raw admin config value, or the supplied default."""
    if db is None:
        return default

    try:
        result = await db.execute(select(AdminConfig.config_value).where(AdminConfig.config_key == key))
        value = result.scalar_one_or_none()
        return value if value not in (None, "") else default
    except Exception:
        return default


async def get_admin_int_config(
    db: AsyncSession | None,
    key: str,
    default: int,
    *,
    min_value: int | None = None,
    max_value: int | None = None,
) -> int:
    """Return an integer admin config value with optional bounds."""
    raw_value = await get_admin_config_value(db, key, str(default))
    try:
        parsed = int(raw_value) if raw_value is not None else default
    except (TypeError, ValueError):
        parsed = default

    if min_value is not None:
        parsed = max(min_value, parsed)
    if max_value is not None:
        parsed = min(max_value, parsed)
    return parsed


async def get_effective_cache_ttl_seconds(db: AsyncSession | None) -> int:
    """Return the effective page-cache TTL in seconds.

    A value of ``0`` means keep page-cache keys indefinitely until they are
    explicitly released from the Admin panel.
    """
    raw_value = await get_admin_config_value(
        db,
        "cache_ttl_seconds",
        str(settings.CACHE_TTL_SECONDS),
    )
    try:
        parsed = int(raw_value) if raw_value is not None else settings.CACHE_TTL_SECONDS
    except (TypeError, ValueError):
        parsed = settings.CACHE_TTL_SECONDS

    if parsed <= 0:
        return 0
    return min(max(parsed, 60), 7 * 24 * 60 * 60)


async def get_cache_enabled(db: AsyncSession | None) -> bool:
    """Return whether page caching is enabled (admin toggle).

    Defaults to ``True`` so caching behaves normally unless an admin
    explicitly sets ``cache_enabled`` to ``"false"`` in the config table.
    """
    raw = await get_admin_config_value(db, "cache_enabled", "true")
    return (raw or "true").strip().lower() in ("true", "1", "yes")


async def get_ollama_enabled(db: AsyncSession | None) -> bool:
    """Return whether Ollama LLM generation is enabled (admin toggle).

    Defaults to ``True`` so Ollama is attempted unless an admin
    explicitly sets ``ollama_enabled`` to ``"false"`` in the config table.
    """
    raw = await get_admin_config_value(db, "ollama_enabled", "true")
    return (raw or "true").strip().lower() in ("true", "1", "yes")


async def get_effective_cors_origins(db: AsyncSession | None) -> list[str]:
    """Return the effective CORS origins from DB, falling back to env defaults."""
    raw_value = await get_admin_config_value(
        db,
        CORS_CONFIG_KEY,
        serialize_cors_origins(settings.CORS_ORIGINS),
    )
    parsed = parse_cors_origins(raw_value, strict=False)
    return parsed or parse_cors_origins(settings.CORS_ORIGINS, strict=False)
