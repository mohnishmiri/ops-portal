"""
Subscription check on the resources a request names.

The subscription scope (``subscription_scope.py``) narrows *lists*.  On its own
it does not stop a request that names its target directly — a cluster's ARM
ID, a Key Vault URI, a subscription ID in the body — so it is a filter, not a
boundary.  :func:`enforce_target_access` closes that: every subscription a
request names must be one the user may read (GET, and the read-only mutations
in ``route_policy``) or change (every other state-changing request).

Targets recognised wherever they appear — path, query string, JSON body:

* any ARM resource ID, ``/subscriptions/{guid}/...`` (``cluster_id``,
  ``resource_id``, ``workspace_id``, ...);
* a field named like a subscription ID (``subscription_id``,
  ``subscriptionIds``, ``sub_id``, ...) — any value, so a malformed ID is
  refused rather than ignored;
* a Key Vault named by URI or name (``vault_uri``, ``vault_name``, ...),
  resolved to its subscription from the portal's vault inventory.  A vault
  the inventory does not know is refused.

Not covered here, and checked where the record is loaded instead: rows
addressed by a database ID, and targets that are not Azure subscriptions.
"""

from __future__ import annotations

import contextlib
import json
import re
from urllib.parse import urlparse

import structlog
from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access_scope import assert_subscription_access, resolve_access_scope, subscriptions_in_text
from app.core.authz import enforce_portal_access
from app.core.database import get_db
from app.core.route_policy import required_level
from app.models.database import KeyVaultSnapshot
from app.schemas.auth import UserContext

logger = structlog.get_logger(__name__)

# Routes whose handlers authorize their own targets: the access-management API
# (a request *for* a subscription must not require access to it already) and
# the Super-Admin-only consoles.
_EXEMPT_PREFIXES: tuple[str, ...] = ("/api/v1/access", "/api/v1/admin", "/api/v1/permissions")

_SUBSCRIPTION_KEYS = frozenset(
    {"subscriptionid", "subscriptionids", "subid", "subids", "subscription", "subscriptions"}
)
_VAULT_KEYS = frozenset(
    {
        "vaulturi",
        "vaulturis",
        "vaulturl",
        "vaulturls",
        "vaultname",
        "vaultnames",
        "keyvaultname",
        "keyvaulturi",
        "keyvaulturl",
        "kvname",
    }
)


def _norm_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", key.lower())


class _Targets:
    def __init__(self) -> None:
        self.subscriptions: set[str] = set()
        self.vaults: set[str] = set()  # lower-case vault names

    def add(self, key: str | None, value: object) -> None:
        """Record targets from one (key, value) pair; recurses into containers."""
        stack: list[tuple[str | None, object]] = [(key, value)]
        while stack:
            k, v = stack.pop()
            nk = _norm_key(k) if k else ""
            if isinstance(v, dict):
                stack.extend((str(ck), cv) for ck, cv in v.items())
            elif isinstance(v, list | tuple):
                stack.extend((k, item) for item in v)
            elif isinstance(v, str):
                self.subscriptions |= subscriptions_in_text(v)
                if nk in _SUBSCRIPTION_KEYS and v.strip():
                    self.subscriptions.add(v.strip().lower())
                elif nk in _VAULT_KEYS and v.strip():
                    self.vaults.add(_vault_name(v))

    def __bool__(self) -> bool:
        return bool(self.subscriptions or self.vaults)


def _vault_name(ref: str) -> str:
    """Vault name from a URI (``https://kv-x.vault.azure.net/``) or a bare name."""
    ref = ref.strip()
    if "://" in ref:
        host = urlparse(ref).hostname or ""
        return host.split(".", 1)[0].lower()
    return ref.lower()


async def collect_targets(request: Request) -> _Targets:
    targets = _Targets()
    for key, value in request.path_params.items():
        targets.add(key, value)
    for key, value in request.query_params.multi_items():
        # The picker's view filter; bind_subscription_scope narrows it to
        # what the user may see, so it is not a target.
        if key == "subscription_ids":
            continue
        targets.add(key, value)

    if request.method.upper() not in {"GET", "HEAD", "OPTIONS"} and request.headers.get(
        "content-type", ""
    ).lower().startswith("application/json"):
        # ``Request.body()`` caches the bytes, so the route still reads the body
        # normally afterwards.
        raw = await request.body()
        if raw:
            # Malformed JSON: the route itself rejects it with a 422.
            with contextlib.suppress(ValueError, UnicodeDecodeError):
                targets.add(None, json.loads(raw))
    return targets


async def _vault_subscriptions(db: AsyncSession, names: set[str]) -> tuple[set[str], set[str]]:
    """(subscriptions of the known vaults, names the inventory does not know)."""
    rows = (
        await db.execute(
            select(func.lower(KeyVaultSnapshot.name), KeyVaultSnapshot.subscription_id).where(
                func.lower(KeyVaultSnapshot.name).in_(sorted(names))
            )
        )
    ).all()
    found = {name: sub for name, sub in rows if sub}
    return {sub.lower() for sub in found.values()}, names - found.keys()


async def enforce_target_access(
    request: Request,
    user: UserContext | None = Depends(enforce_portal_access),
    db: AsyncSession | None = Depends(get_db),
) -> None:
    """Router-level dependency: refuse requests naming a subscription out of scope."""
    if user is None:  # signed K8s dashboard session; it carries its own grant
        return
    path = request.url.path
    if path.startswith(_EXEMPT_PREFIXES):
        return

    scope = await resolve_access_scope(request, user, db)
    if scope.unrestricted:
        return

    targets = await collect_targets(request)
    if not targets:
        return

    route = request.scope.get("route")
    level = required_level(request.method, getattr(route, "path", None))

    subscriptions = set(targets.subscriptions)
    if targets.vaults:
        vault_subs, unknown = await _vault_subscriptions(db, targets.vaults)
        if unknown:
            logger.warning(
                "target_access_unknown_vault",
                user_id=user.user_id,
                path=path,
                vaults=sorted(unknown),
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="This Key Vault is not in the portal inventory, so access to it cannot be confirmed.",
            )
        subscriptions |= vault_subs

    assert_subscription_access(scope, subscriptions, level, user_id=user.user_id, context=f"{request.method} {path}")
