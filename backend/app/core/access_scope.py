"""
Project / app / subscription access — *where* a user may work.

Entra app roles decide *what* a user may do (READ views, WRITE changes, ADMIN
administers).  This module decides *where*: which Azure subscriptions the user
may see and which they may change.  The hierarchy is

    Project (e.g. Commissions) → App (e.g. ATTCC) → Subscription (Prod / Non-Prod)

Rules
-----
* **Super Admin** (Entra-only app role) — every subscription, read and write.
* **Project Admin** — holds the Entra Admin role *and* is assigned to a project
  by a Super Admin: every subscription of that project, read and write.
* **Everyone else** — the union of their grants.  A grant names a project or an
  app plus a tier (prod / nonprod), or a single subscription, at level read or
  write.  Project and app grants cover subscriptions added there later.
* The Entra role is a ceiling: a READ user granted write can still only read.
* No grant → no subscriptions.  A subscription not yet placed in an app, or in
  an inactive project, is visible to Super Admins only.  An unset tier counts
  as prod, so a classification mistake fails closed.

The structural part (which subscription sits in which app, project and tier)
changes rarely and is cached per process for a few seconds; grants are read on
every request so an approval or revocation takes effect immediately.
"""

from __future__ import annotations

import re
import time
from contextvars import ContextVar
from dataclasses import dataclass, field

import structlog
from fastapi import HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AccessGrant, AdminSubscription, Project, ProjectAdmin, ProjectApp
from app.schemas.auth import UserContext, UserRole

logger = structlog.get_logger(__name__)

TIERS: tuple[str, ...] = ("prod", "nonprod")
LEVELS: tuple[str, ...] = ("read", "write")
SCOPE_TYPES: tuple[str, ...] = ("project", "app", "subscription")

EVERYONE_SUBJECT = "*"


# ── Classification ─────────────────────────────────────────────────────────

# ACC-PROD-31599-ATTCC / ACC-NPRD-17805-DWS
_SUBSCRIPTION_NAME = re.compile(r"^ACC-(PROD|PRD|NPRD|NPROD|NONPROD)-(\d+)-(.+)$", re.IGNORECASE)

# Non-prod words.  PreProd is non-prod; DR is prod (it serves production when
# invoked), so neither "dr" nor "prod" appears here.
_NONPROD_TOKENS = frozenset(
    {
        "nonprod",
        "nonproduction",
        "nprd",
        "nprod",
        "preprod",
        "dev",
        "development",
        "test",
        "qa",
        "uat",
        "stg",
        "stage",
        "staging",
        "perf",
        "sandbox",
        "poc",
    }
)


def classify_tier(text: str | None) -> str:
    """``prod`` or ``nonprod`` for free text such as a subscription name.

    Anything unrecognised is prod: being wrong in that direction only hides a
    subscription from non-prod users, never exposes production.
    """
    raw = (text or "").lower()
    tokens = {t for t in re.split(r"[^a-z0-9]+", raw) if t}
    flat = re.sub(r"[^a-z0-9]", "", raw)
    if tokens & _NONPROD_TOKENS or "nonprod" in flat or "preprod" in flat:
        return "nonprod"
    return "prod"


@dataclass(frozen=True)
class NameClassification:
    app_code: str | None
    app_name: str | None
    tier: str


def classify_subscription(name: str | None, environment: str | None = None) -> NameClassification:
    """App and tier suggested by a subscription's name.

    Names following ``ACC-{PROD|NPRD}-{AppID}-{Name}`` give both.  Otherwise
    only the tier is suggested, from the admin-set environment or the name.
    """
    match = _SUBSCRIPTION_NAME.match((name or "").strip())
    if match:
        tier = "prod" if match.group(1).upper() in {"PROD", "PRD"} else "nonprod"
        return NameClassification(app_code=match.group(2), app_name=match.group(3).strip(), tier=tier)
    return NameClassification(app_code=None, app_name=None, tier=classify_tier(environment or name))


def normalize_tier(tier: str | None) -> str:
    return tier if tier in TIERS else "prod"


# ── Topology (cached) ───────────────────────────────────────────────────────


@dataclass(frozen=True)
class Placement:
    subscription_id: str  # lower-case
    app_id: int
    project_id: int
    tier: str


@dataclass(frozen=True)
class AccessTopology:
    placements: dict[str, Placement]
    by_project_tier: dict[tuple[int, str], frozenset[str]]
    by_app_tier: dict[tuple[int, str], frozenset[str]]
    by_project: dict[int, frozenset[str]]


_TOPOLOGY_TTL_SECONDS = 30.0
_topology: AccessTopology | None = None
_topology_ts = 0.0


def invalidate_access_topology() -> None:
    """Drop the cached topology.  Call after any project/app/placement change.

    Only this process's cache is cleared; other replicas pick the change up
    within ``_TOPOLOGY_TTL_SECONDS``.
    """
    global _topology, _topology_ts
    _topology = None
    _topology_ts = 0.0


async def load_topology(db: AsyncSession) -> AccessTopology:
    global _topology, _topology_ts

    now = time.monotonic()
    if _topology is not None and now - _topology_ts < _TOPOLOGY_TTL_SECONDS:
        return _topology

    # No lock: two concurrent misses just load the same small result twice.
    rows = (
        await db.execute(
            select(AdminSubscription.subscription_id, AdminSubscription.tier, ProjectApp.id, ProjectApp.project_id)
            .join(ProjectApp, AdminSubscription.app_id == ProjectApp.id)
            .join(Project, ProjectApp.project_id == Project.id)
            .where(Project.is_active.is_(True))
        )
    ).all()

    placements: dict[str, Placement] = {}
    by_project_tier: dict[tuple[int, str], set[str]] = {}
    by_app_tier: dict[tuple[int, str], set[str]] = {}
    by_project: dict[int, set[str]] = {}
    for sub_id, tier, app_id, project_id in rows:
        sid = str(sub_id).lower()
        t = normalize_tier(tier)
        placements[sid] = Placement(sid, app_id, project_id, t)
        by_project_tier.setdefault((project_id, t), set()).add(sid)
        by_app_tier.setdefault((app_id, t), set()).add(sid)
        by_project.setdefault(project_id, set()).add(sid)

    _topology = AccessTopology(
        placements=placements,
        by_project_tier={k: frozenset(v) for k, v in by_project_tier.items()},
        by_app_tier={k: frozenset(v) for k, v in by_app_tier.items()},
        by_project={k: frozenset(v) for k, v in by_project.items()},
    )
    _topology_ts = time.monotonic()
    return _topology


# ── Per-user scope ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AccessScope:
    """Subscriptions (lower-case IDs) a user may read and write."""

    unrestricted: bool = False
    readable: frozenset[str] = field(default_factory=frozenset)
    writable: frozenset[str] = field(default_factory=frozenset)
    admin_project_ids: frozenset[int] = field(default_factory=frozenset)

    def can_read(self, subscription_id: str) -> bool:
        return self.unrestricted or subscription_id.lower() in self.readable

    def can_write(self, subscription_id: str) -> bool:
        return self.unrestricted or subscription_id.lower() in self.writable

    def allows(self, subscription_id: str, level: str) -> bool:
        return self.can_write(subscription_id) if level == "write" else self.can_read(subscription_id)

    def administers(self, project_id: int) -> bool:
        return self.unrestricted or project_id in self.admin_project_ids

    @property
    def has_any_access(self) -> bool:
        return self.unrestricted or bool(self.readable)


UNRESTRICTED = AccessScope(unrestricted=True)

_current_scope: ContextVar[AccessScope | None] = ContextVar("current_access_scope", default=None)


def current_access_scope() -> AccessScope | None:
    """The scope bound for the current request, or None outside a request."""
    return _current_scope.get()


def bind_access_scope(scope: AccessScope):  # noqa: ANN201 — returns a contextvar Token
    return _current_scope.set(scope)


def _role_ceiling(user: UserContext) -> str:
    from app.auth import effective_roles

    return "write" if UserRole.WRITE in effective_roles(user) else "read"


def subscriptions_for_grant(topology: AccessTopology, grant: AccessGrant) -> frozenset[str]:
    """Subscriptions a grant currently covers."""
    if grant.scope_type == "project":
        return topology.by_project_tier.get((grant.project_id, normalize_tier(grant.tier)), frozenset())
    if grant.scope_type == "app" and grant.app_id is not None:
        return topology.by_app_tier.get((grant.app_id, normalize_tier(grant.tier)), frozenset())
    if grant.scope_type == "subscription" and grant.subscription_id:
        sid = grant.subscription_id.lower()
        placement = topology.placements.get(sid)
        # Only placed subscriptions in the grant's own project count, so a
        # stale grant cannot follow a subscription into another project.
        if placement is not None and placement.project_id == grant.project_id:
            return frozenset({sid})
    return frozenset()


async def compute_access_scope(db: AsyncSession | None, user: UserContext) -> AccessScope:
    """Resolve ``user``'s scope (no request memoization).

    Fails closed: when the database is unavailable only a Super Admin (whose
    role comes from the token) gets through.
    """
    if user.is_super_admin:
        return UNRESTRICTED
    return await _scope_from_db(db, user)


async def _scope_from_db(db: AsyncSession | None, user: UserContext) -> AccessScope:
    """Grants and project-admin assignments → scope.  The single DB entry point."""
    if db is None:
        logger.error("access_scope_unavailable", user_id=user.user_id, reason="database_unavailable")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Access could not be verified right now. Please try again shortly.",
        )
    topology = await load_topology(db)

    grants = (
        (
            await db.execute(
                select(AccessGrant).where(
                    or_(
                        (AccessGrant.subject_type == "user") & (AccessGrant.subject_id == user.user_id),
                        AccessGrant.subject_type == "everyone",
                    )
                )
            )
        )
        .scalars()
        .all()
    )

    ceiling = _role_ceiling(user)
    readable: set[str] = set()
    writable: set[str] = set()
    for grant in grants:
        subs = subscriptions_for_grant(topology, grant)
        readable |= subs
        if grant.level == "write" and ceiling == "write":
            writable |= subs

    admin_projects: frozenset[int] = frozenset()
    if user.is_admin:
        admin_projects = frozenset(
            (await db.execute(select(ProjectAdmin.project_id).where(ProjectAdmin.user_id == user.user_id)))
            .scalars()
            .all()
        )
        for project_id in admin_projects:
            subs = topology.by_project.get(project_id, frozenset())
            readable |= subs
            writable |= subs

    return AccessScope(
        unrestricted=False,
        readable=frozenset(readable),
        writable=frozenset(writable),
        admin_project_ids=admin_projects,
    )


async def resolve_access_scope(
    request: Request | None,
    user: UserContext,
    db: AsyncSession | None,
) -> AccessScope:
    """The user's scope (see :func:`compute_access_scope`), memoized on the request."""
    if request is not None:
        cached = getattr(request.state, "_access_scope", None)
        if cached is not None:
            return cached

    scope = await compute_access_scope(db, user)

    if request is not None:
        request.state._access_scope = scope
    return scope


# ── Checks ─────────────────────────────────────────────────────────────────

_ARM_SUBSCRIPTION = re.compile(r"/subscriptions/([0-9a-fA-F-]{36})", re.IGNORECASE)


def subscriptions_in_text(text: str) -> set[str]:
    """Lower-case subscription IDs embedded in ARM resource IDs inside ``text``."""
    return {m.lower() for m in _ARM_SUBSCRIPTION.findall(text or "")}


def access_denied(level: str) -> HTTPException:
    verb = "change" if level == "write" else "view"
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"You do not have access to {verb} resources in this subscription.",
    )


def assert_subscription_access(
    scope: AccessScope | None,
    subscription_ids: set[str] | list[str],
    level: str,
    *,
    user_id: str | None = None,
    context: str = "",
) -> None:
    """Raise 403 unless ``scope`` allows ``level`` on every subscription given.

    ``scope`` None means "no request context" (a background job), which runs
    with the portal's own authority and is not checked here.
    """
    if scope is None or scope.unrestricted:
        return
    denied = sorted({s.lower() for s in subscription_ids if s and not scope.allows(s, level)})
    if denied:
        logger.warning(
            "subscription_access_denied",
            user_id=user_id,
            level=level,
            subscription_ids=denied,
            context=context,
        )
        raise access_denied(level)


# ── Row-level helpers for records loaded by database ID ─────────────────────
#
# The target check (app.core.target_access) sees only what a request names.
# A route addressing a stored row — /schedule/{id}, /configs/{id} — names no
# subscription; the row does.  Services call these after loading such rows.

_GUID = re.compile(r"^[0-9a-fA-F-]{36}$")


def subscription_of(value: str | None) -> str | None:
    """Lower-case subscription of an ARM resource ID or a bare subscription ID."""
    if not value:
        return None
    subs = subscriptions_in_text(value)
    if subs:
        return next(iter(subs))
    value = value.strip()
    return value.lower() if _GUID.match(value) else None


def assert_resource_access(value: str | None, level: str, *, context: str = "") -> None:
    """403 unless the current request may ``level`` the row's subscription.

    ``value`` is the row's ARM resource ID or subscription ID.  A row whose
    subscription cannot be determined is refused for restricted users.  No
    bound scope (a background job) means no check.
    """
    scope = current_access_scope()
    if scope is None or scope.unrestricted:
        return
    sub = subscription_of(value)
    if sub is None or not scope.allows(sub, level):
        logger.warning("row_access_denied", level=level, subscription_id=sub, context=context)
        raise access_denied(level)


def arm_scope_clause(column):  # noqa: ANN201 — SQLAlchemy clause
    """Filter for an ARM-resource-ID column: rows in readable subscriptions only.

    ``None`` when the current request is unrestricted (or there is none).
    """
    from sqlalchemy import false, func

    scope = current_access_scope()
    if scope is None or scope.unrestricted:
        return None
    if not scope.readable:
        return false()
    return or_(*(func.lower(column).like(f"/subscriptions/{sub}/%") for sub in sorted(scope.readable)))


def subscription_scope_clause(column):  # noqa: ANN201 — SQLAlchemy clause
    """Filter for a subscription-ID column: readable subscriptions only."""
    from sqlalchemy import false, func

    scope = current_access_scope()
    if scope is None or scope.unrestricted:
        return None
    if not scope.readable:
        return false()
    return func.lower(column).in_(sorted(scope.readable))
