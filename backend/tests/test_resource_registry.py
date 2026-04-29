"""
Unit tests for the canonical resource registry (resource_registry.py).

Tests verify:
  • seed_resources inserts all expected modules and pages
  • parent_id is correctly resolved for pages
  • Running seed_resources twice is idempotent (no duplicates, no errors)
  • System flag is always True on seeded records

Uses the SQLite in-memory session from conftest.py.
"""

import pytest
from sqlalchemy import select

from app.core.resource_registry import RESOURCE_SEEDS, seed_resources
from app.models.database import Resource


# ── Seed tests ─────────────────────────────────────────────────────────────────

@pytest.mark.anyio
async def test_seed_creates_all_resources(db_session):
    await seed_resources(db_session)

    result = await db_session.execute(select(Resource))
    names = {r.resource_name for r in result.scalars().all()}
    expected = {s["resource_name"] for s in RESOURCE_SEEDS}
    assert expected == names


@pytest.mark.anyio
async def test_seed_all_resources_are_system(db_session):
    await seed_resources(db_session)

    result = await db_session.execute(select(Resource))
    for res in result.scalars().all():
        assert res.is_system is True, (
            f"Resource '{res.resource_name}' should be is_system=True"
        )


@pytest.mark.anyio
async def test_seed_modules_have_no_parent(db_session):
    await seed_resources(db_session)

    result = await db_session.execute(
        select(Resource).where(Resource.resource_type == "module")
    )
    for mod in result.scalars().all():
        assert mod.parent_id is None, (
            f"Module '{mod.resource_name}' should have no parent"
        )


@pytest.mark.anyio
async def test_seed_pages_have_parent_id(db_session):
    await seed_resources(db_session)

    result = await db_session.execute(
        select(Resource).where(Resource.resource_type == "page")
    )
    for page in result.scalars().all():
        assert page.parent_id is not None, (
            f"Page '{page.resource_name}' should have a parent_id"
        )


@pytest.mark.anyio
async def test_seed_parent_id_points_to_correct_module(db_session):
    await seed_resources(db_session)

    # Build name→id map
    result = await db_session.execute(select(Resource))
    resources = result.scalars().all()
    name_to_id = {r.resource_name: r.id for r in resources}
    id_to_type = {r.id: r.resource_type for r in resources}

    for seed in RESOURCE_SEEDS:
        if seed.get("parent_name"):
            res = next(r for r in resources if r.resource_name == seed["resource_name"])
            expected_parent_id = name_to_id[seed["parent_name"]]
            assert res.parent_id == expected_parent_id, (
                f"Page '{res.resource_name}' has wrong parent_id"
            )
            assert id_to_type[res.parent_id] == "module", (
                f"Page '{res.resource_name}' parent must be a module"
            )


@pytest.mark.anyio
async def test_seed_is_idempotent(db_session):
    """Running seed_resources twice must not create duplicate rows."""
    await seed_resources(db_session)
    await seed_resources(db_session)

    result = await db_session.execute(select(Resource))
    names = [r.resource_name for r in result.scalars().all()]
    assert len(names) == len(set(names)), "Duplicate resource names found after double seed"
    assert len(names) == len(RESOURCE_SEEDS)


@pytest.mark.anyio
async def test_seed_route_paths_match_registry(db_session):
    await seed_resources(db_session)

    result = await db_session.execute(select(Resource))
    name_to_route = {r.resource_name: r.route_path for r in result.scalars().all()}

    for seed in RESOURCE_SEEDS:
        assert name_to_route[seed["resource_name"]] == seed.get("route_path"), (
            f"Route path mismatch for '{seed['resource_name']}'"
        )


@pytest.mark.anyio
async def test_seed_descriptions_are_set(db_session):
    await seed_resources(db_session)

    result = await db_session.execute(select(Resource))
    for res in result.scalars().all():
        assert res.description, f"Resource '{res.resource_name}' has no description"


@pytest.mark.anyio
async def test_seed_known_modules_present(db_session):
    """Smoke test — assert the 5 known portal modules exist after seeding."""
    await seed_resources(db_session)

    result = await db_session.execute(
        select(Resource).where(Resource.resource_type == "module")
    )
    module_names = {r.resource_name for r in result.scalars().all()}
    assert {"cost_management", "aks_operations", "compliance",
            "keyvault", "infra_alerts"} <= module_names


@pytest.mark.anyio
async def test_seed_known_pages_present(db_session):
    """Smoke test — assert the 6 known portal pages exist after seeding."""
    await seed_resources(db_session)

    result = await db_session.execute(
        select(Resource).where(Resource.resource_type == "page")
    )
    page_names = {r.resource_name for r in result.scalars().all()}
    assert {"leadership_dashboard", "amortized_costs", "aks_main",
            "compliance_main", "keyvault_main", "infra_alerts_main"} <= page_names
