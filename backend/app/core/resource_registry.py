"""
Canonical module/page resource registry for OpsPortal access management.

All portal modules and pages are declared here.  The seeder runs on every
startup (upsert semantics) so new resources appear automatically without
manual DB intervention.  System resources carry ``is_system=True`` and
cannot be deleted via the API — they can only be deactivated by revoking
permission records.

Hierarchy:
  module  →  root-level feature group (maps to a nav item)
  page    →  a specific view within a module (child of a module)

Adding a new module/page:
  1. Append an entry to RESOURCE_SEEDS below.
  2. (Optionally) wrap the matching React route in a ProtectedRoute.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Canonical resource definitions
# ---------------------------------------------------------------------------

RESOURCE_SEEDS: list[dict] = [
    # ── Modules ──────────────────────────────────────────────────────────
    {
        "resource_type": "module",
        "resource_name": "cost_management",
        "description": "Cost management, FinOps, and financial intelligence",
        "route_path": None,
        "parent_name": None,
        "is_system": True,
    },
    {
        "resource_type": "module",
        "resource_name": "aks_operations",
        "description": "AKS cluster and workload operations",
        "route_path": "/aks",
        "parent_name": None,
        "is_system": True,
    },
    {
        "resource_type": "module",
        "resource_name": "compliance",
        "description": "Compliance and configuration drift detection",
        "route_path": "/compliance",
        "parent_name": None,
        "is_system": True,
    },
    {
        "resource_type": "module",
        "resource_name": "keyvault",
        "description": "Azure Key Vault secrets, keys, and certificate lifecycle",
        "route_path": "/keyvault",
        "parent_name": None,
        "is_system": True,
    },
    {
        "resource_type": "module",
        "resource_name": "infra_alerts",
        "description": "Infrastructure alerting and threshold monitoring",
        "route_path": "/infra-alerts",
        "parent_name": None,
        "is_system": True,
    },
    {
        "resource_type": "module",
        "resource_name": "certificates",
        "description": "Certificate lifecycle management via Keyfactor Command",
        "route_path": "/certificates",
        "parent_name": None,
        "is_system": True,
    },
    # ── Pages under cost_management ──────────────────────────────────────
    {
        "resource_type": "page",
        "resource_name": "leadership_dashboard",
        "description": "Leadership summary dashboard with cost KPIs and AI advisor",
        "route_path": "/",
        "parent_name": "cost_management",
        "is_system": True,
    },
    {
        "resource_type": "page",
        "resource_name": "amortized_costs",
        "description": "Amortized cost breakdown and trend analysis",
        "route_path": "/env-costs",
        "parent_name": "cost_management",
        "is_system": True,
    },
    # ── Pages under aks_operations ───────────────────────────────────────
    {
        "resource_type": "page",
        "resource_name": "aks_main",
        "description": "AKS cluster overview and workload management",
        "route_path": "/aks",
        "parent_name": "aks_operations",
        "is_system": True,
    },
    {
        "resource_type": "page",
        "resource_name": "env_scheduler",
        "description": "Environment scaling, scheduling, and sequence management",
        "route_path": "/env-scheduler",
        "parent_name": "aks_operations",
        "is_system": True,
    },
    {
        "resource_type": "page",
        "resource_name": "k8s_dashboard",
        "description": "Kubernetes Dashboard one-click SSO access",
        "route_path": None,
        "parent_name": "aks_operations",
        "is_system": True,
    },
    {
        "resource_type": "page",
        "resource_name": "k8s_dashboard_prod",
        "description": "Production K8s Dashboard access",
        "route_path": None,
        "parent_name": "aks_operations",
        "is_system": True,
    },
    {
        "resource_type": "page",
        "resource_name": "k8s_dashboard_preprod",
        "description": "PreProd K8s Dashboard access",
        "route_path": None,
        "parent_name": "aks_operations",
        "is_system": True,
    },
    {
        "resource_type": "page",
        "resource_name": "k8s_dashboard_perf",
        "description": "Performance K8s Dashboard access",
        "route_path": None,
        "parent_name": "aks_operations",
        "is_system": True,
    },
    {
        "resource_type": "page",
        "resource_name": "k8s_dashboard_uat",
        "description": "UAT K8s Dashboard access",
        "route_path": None,
        "parent_name": "aks_operations",
        "is_system": True,
    },
    {
        "resource_type": "page",
        "resource_name": "k8s_dashboard_dev",
        "description": "Development K8s Dashboard access",
        "route_path": None,
        "parent_name": "aks_operations",
        "is_system": True,
    },
    {
        "resource_type": "page",
        "resource_name": "k8s_dashboard_dr",
        "description": "DR K8s Dashboard access",
        "route_path": None,
        "parent_name": "aks_operations",
        "is_system": True,
    },
    # ── Pages under compliance ───────────────────────────────────────────
    {
        "resource_type": "page",
        "resource_name": "compliance_main",
        "description": "Compliance score and drift history",
        "route_path": "/compliance",
        "parent_name": "compliance",
        "is_system": True,
    },
    # ── Pages under keyvault ─────────────────────────────────────────────
    {
        "resource_type": "page",
        "resource_name": "keyvault_main",
        "description": "Key Vault inventory and expiry tracking",
        "route_path": "/keyvault",
        "parent_name": "keyvault",
        "is_system": True,
    },
    # ── Pages under infra_alerts ─────────────────────────────────────────
    {
        "resource_type": "page",
        "resource_name": "infra_alerts_main",
        "description": "Infrastructure alert dashboard",
        "route_path": "/infra-alerts",
        "parent_name": "infra_alerts",
        "is_system": True,
    },
    # ── Pages under certificates ─────────────────────────────────────────
    {
        "resource_type": "page",
        "resource_name": "certificates_main",
        "description": "Certificate lifecycle dashboard (list, enroll, renew, revoke, delete)",
        "route_path": "/certificates",
        "parent_name": "certificates",
        "is_system": True,
    },
    # ── Admin module ─────────────────────────────────────────────────────
    {
        "resource_type": "module",
        "resource_name": "admin",
        "description": "System administration — subscriptions, config, and access control",
        "route_path": "/admin",
        "parent_name": None,
        "is_system": True,
    },
    # ── Pages under admin ────────────────────────────────────────────────
    {
        "resource_type": "page",
        "resource_name": "admin_dashboard",
        "description": "Subscription management, system health, and admin configuration",
        "route_path": "/admin",
        "parent_name": "admin",
        "is_system": True,
    },
    {
        "resource_type": "page",
        "resource_name": "admin_permissions",
        "description": "Module and page-level access control and role/user permission management",
        "route_path": "/admin/permissions",
        "parent_name": "admin",
        "is_system": True,
    },
]


async def seed_resources(db: AsyncSession) -> None:
    """
    Upsert all system resources into the DB.

    Safe to call on every startup — existing records are updated in-place,
    new ones are inserted.  The ``is_system`` flag is always forced to True
    for seed entries so they cannot be deleted via the API.

    Collects seeds from both RESOURCE_SEEDS (static) and plugin-declared
    resources registered via register_plugin_resources().
    """
    from app.models.database import Resource  # local import to avoid circular deps

    all_seeds = get_all_resource_seeds()

    # Build a name→id map for existing records in one query
    result = await db.execute(select(Resource.resource_name, Resource.id))
    existing: dict[str, int] = {row.resource_name: row.id for row in result}

    # First pass: insert/update all resources (parent_id resolved in second pass)
    for seed in all_seeds:
        name = seed["resource_name"]
        if name in existing:
            await db.execute(
                update(Resource)
                .where(Resource.id == existing[name])
                .values(
                    resource_type=seed["resource_type"],
                    description=seed["description"],
                    route_path=seed.get("route_path"),
                    is_system=True,
                )
            )
        else:
            new_res = Resource(
                resource_type=seed["resource_type"],
                resource_name=name,
                description=seed["description"],
                route_path=seed.get("route_path"),
                is_system=True,
            )
            db.add(new_res)

    await db.flush()

    # Refresh name→id map after inserts
    result2 = await db.execute(select(Resource.resource_name, Resource.id))
    name_to_id: dict[str, int] = {row.resource_name: row.id for row in result2}

    # Second pass: resolve parent_id
    for seed in all_seeds:
        parent_name = seed.get("parent_name")
        if parent_name and parent_name in name_to_id:
            child_id = name_to_id.get(seed["resource_name"])
            if child_id:
                await db.execute(
                    update(Resource).where(Resource.id == child_id).values(parent_id=name_to_id[parent_name])
                )

    await db.commit()
    logger.info("resource_seeds_applied", total=len(all_seeds))


# Default role → resource permission grants.
# These are inserted ONCE (skip if already exists).  Admins can change them
# freely through the UI — this list is only consulted when no matching
# permission record exists at all.
#
# Format: (subject_id/role, resource_name, permission_type)
# Admin resources are intentionally omitted — admin pages are role-gated, not
# permission-record gated.
_ADMIN_SKIP = {"admin", "admin_dashboard", "admin_permissions"}

DEFAULT_PERMISSION_SEEDS: list[tuple[str, str, str]] = [
    # read role — view-only on all non-admin resources
    ("read", "cost_management", "view"),
    ("read", "aks_operations", "view"),
    ("read", "compliance", "view"),
    ("read", "keyvault", "view"),
    ("read", "infra_alerts", "view"),
    ("read", "leadership_dashboard", "view"),
    ("read", "amortized_costs", "view"),
    ("read", "aks_main", "view"),
    ("read", "compliance_main", "view"),
    ("read", "keyvault_main", "view"),
    ("read", "infra_alerts_main", "view"),
    ("read", "certificates", "view"),
    ("read", "certificates_main", "view"),
    # write role — view + edit on all non-admin resources
    ("write", "cost_management", "view"),
    ("write", "cost_management", "edit"),
    ("write", "aks_operations", "view"),
    ("write", "aks_operations", "edit"),
    ("write", "compliance", "view"),
    ("write", "compliance", "edit"),
    ("write", "keyvault", "view"),
    ("write", "keyvault", "edit"),
    ("write", "infra_alerts", "view"),
    ("write", "infra_alerts", "edit"),
    ("write", "leadership_dashboard", "view"),
    ("write", "leadership_dashboard", "edit"),
    ("write", "amortized_costs", "view"),
    ("write", "amortized_costs", "edit"),
    ("write", "aks_main", "view"),
    ("write", "aks_main", "edit"),
    ("write", "compliance_main", "view"),
    ("write", "compliance_main", "edit"),
    ("write", "keyvault_main", "view"),
    ("write", "keyvault_main", "edit"),
    ("write", "infra_alerts_main", "view"),
    ("write", "infra_alerts_main", "edit"),
    ("write", "certificates", "view"),
    ("write", "certificates", "edit"),
    ("write", "certificates_main", "view"),
    ("write", "certificates_main", "edit"),
]


async def seed_permissions(db: AsyncSession) -> None:
    """
    Insert default role-based permission records if they don't already exist.

    Safe to run on every startup — existing records are left untouched so
    admins can customise permissions without having them reset on restart.
    Only genuinely missing rows are inserted.
    """
    from app.models.database import Permission, Resource  # local import

    # Build resource_name → id map
    res_result = await db.execute(select(Resource.resource_name, Resource.id))
    name_to_id: dict[str, int] = {row.resource_name: row.id for row in res_result}

    # Build set of existing (subject_id, resource_id, permission_type) tuples
    perm_result = await db.execute(
        select(Permission.subject_id, Permission.resource_id, Permission.permission_type).where(
            Permission.subject_type == "role"
        )
    )
    existing_perms: set[tuple[str, int, str]] = {
        (row.subject_id, row.resource_id, row.permission_type) for row in perm_result
    }

    inserted = 0
    for role, resource_name, perm_type in DEFAULT_PERMISSION_SEEDS:
        res_id = name_to_id.get(resource_name)
        if not res_id:
            continue
        key = (role, res_id, perm_type)
        if key in existing_perms:
            continue
        db.add(
            Permission(
                subject_type="role",
                subject_id=role,
                resource_id=res_id,
                permission_type=perm_type,
            )
        )
        inserted += 1

    if inserted:
        await db.commit()
    logger.info("permission_seeds_applied", inserted=inserted, skipped=len(DEFAULT_PERMISSION_SEEDS) - inserted)


# ---------------------------------------------------------------------------
# Plugin-declared resource collection
# ---------------------------------------------------------------------------

# Plugins and routers can register resources by appending to this list at
# import time.  The seeder picks them up on startup alongside RESOURCE_SEEDS.
_plugin_resources: list[dict] = []


def register_plugin_resources(resources: list[dict]) -> None:
    """Register plugin-declared resources for auto-seeding.

    Call this from a plugin's __init__.py or create_plugin() entry point:

        from app.core.resource_registry import register_plugin_resources
        register_plugin_resources([
            {"resource_type": "module", "resource_name": "my_plugin", ...},
            {"resource_type": "page", "resource_name": "my_page", "parent_name": "my_plugin", ...},
        ])
    """
    _plugin_resources.extend(resources)
    logger.info("plugin_resources_registered", count=len(resources))


def get_all_resource_seeds() -> list[dict]:
    """Return combined static + plugin-declared resource definitions."""
    return RESOURCE_SEEDS + _plugin_resources
