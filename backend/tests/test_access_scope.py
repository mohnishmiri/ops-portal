"""Who may see and change which subscriptions — the resolution rules."""

import pytest

from app.core.access_scope import (
    AccessScope,
    assert_subscription_access,
    classify_subscription,
    classify_tier,
    compute_access_scope,
    invalidate_access_topology,
)
from app.models.database import AccessGrant, AdminSubscription, Project
from app.schemas.auth import UserRole
from tests.access_helpers import (
    BDS_ALL,
    COMMISSIONS_ALL,
    COMMISSIONS_NONPROD,
    COMMISSIONS_PROD,
    SUB,
    build_world,
    grant,
    make_project_admin,
    make_user,
)

pytestmark = pytest.mark.real_access


# ── Classification ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("name", "code", "app", "tier"),
    [
        ("ACC-PROD-31599-ATTCC", "31599", "ATTCC", "prod"),
        ("ACC-NPRD-17805-DWS", "17805", "DWS", "nonprod"),
        ("acc-nprd-18296-hznrep", "18296", "hznrep", "nonprod"),
        ("ATTCC Sandbox", None, None, "nonprod"),
        ("Legacy Shared", None, None, "prod"),
    ],
)
def test_subscription_names_suggest_app_and_tier(name, code, app, tier):
    c = classify_subscription(name)
    assert (c.app_code, c.app_name, c.tier) == (code, app, tier)


@pytest.mark.parametrize(
    ("text", "tier"),
    [("attcc-preprod-aks", "nonprod"), ("attcc-dr-aks", "prod"), ("attcc-uat", "nonprod"), ("", "prod")],
)
def test_preprod_is_nonprod_and_dr_is_prod(text, tier):
    assert classify_tier(text) == tier


def test_admin_set_environment_wins_over_the_name():
    assert classify_subscription("Shared Platform", environment="non-prod").tier == "nonprod"


# ── Resolution ──────────────────────────────────────────────────────


async def test_super_admin_sees_everything(db_session):
    scope = await compute_access_scope(db_session, make_user("boss", UserRole.SUPER_ADMIN))
    assert scope.unrestricted
    assert scope.can_write(SUB["bds_prod"]) and scope.can_write(SUB["unplaced"])


async def test_no_grant_means_no_subscription(db_session):
    await build_world(db_session)
    scope = await compute_access_scope(db_session, make_user("newbie", UserRole.WRITE))
    assert not scope.has_any_access


async def test_dev_team_gets_commissions_nonprod_only(db_session):
    w = await build_world(db_session)
    await grant(db_session, "dev", project_id=w.commissions, tier="nonprod", level="write")

    scope = await compute_access_scope(db_session, make_user("dev", UserRole.WRITE))

    assert scope.readable == scope.writable == COMMISSIONS_NONPROD
    assert not scope.can_read(SUB["attcc_prod"])
    assert not scope.can_read(SUB["bds_nprd"])


async def test_ops_user_gets_commissions_prod_and_nonprod_write(db_session):
    w = await build_world(db_session)
    for tier in ("prod", "nonprod"):
        await grant(db_session, "ops", project_id=w.commissions, tier=tier, level="write")

    scope = await compute_access_scope(db_session, make_user("ops", UserRole.WRITE))

    assert scope.writable == COMMISSIONS_ALL
    assert not scope.readable & BDS_ALL


async def test_app_grant_covers_only_that_app(db_session):
    w = await build_world(db_session)
    await grant(db_session, "u", project_id=w.commissions, scope_type="app", app_id=w.dws, tier="nonprod")

    scope = await compute_access_scope(db_session, make_user("u", UserRole.READ))

    assert scope.readable == {SUB["dws_nprd"]}
    assert scope.writable == frozenset()


async def test_subscription_grant(db_session):
    w = await build_world(db_session)
    await grant(db_session, "u", project_id=w.commissions, scope_type="subscription", subscription_id=SUB["attcc_prod"])
    scope = await compute_access_scope(db_session, make_user("u", UserRole.READ))
    assert scope.readable == {SUB["attcc_prod"]}


async def test_entra_role_caps_the_grant(db_session):
    """A READ-group user granted write can still only read."""
    w = await build_world(db_session)
    await grant(db_session, "reader", project_id=w.commissions, tier="nonprod", level="write")

    scope = await compute_access_scope(db_session, make_user("reader", UserRole.READ))

    assert scope.readable == COMMISSIONS_NONPROD
    assert scope.writable == frozenset()


async def test_project_admin_gets_their_whole_project(db_session):
    w = await build_world(db_session)
    admin = make_user("cadmin", UserRole.ADMIN)
    await make_project_admin(db_session, admin, w.commissions)

    scope = await compute_access_scope(db_session, admin)

    assert scope.writable == COMMISSIONS_ALL
    assert scope.admin_project_ids == {w.commissions}
    assert not scope.readable & BDS_ALL


async def test_project_admin_assignment_needs_the_entra_admin_role(db_session):
    """An assignment left behind after the user lost the Admin role grants nothing."""
    w = await build_world(db_session)
    former = make_user("former", UserRole.WRITE)
    await make_project_admin(db_session, former, w.commissions)

    scope = await compute_access_scope(db_session, former)

    assert not scope.has_any_access
    assert scope.admin_project_ids == frozenset()


async def test_entra_admin_without_a_project_sees_nothing(db_session):
    await build_world(db_session)
    scope = await compute_access_scope(db_session, make_user("lonely-admin", UserRole.ADMIN))
    assert not scope.has_any_access


async def test_everyone_transition_grant(db_session):
    w = await build_world(db_session)
    db_session.add(
        AccessGrant(
            subject_type="everyone",
            subject_id="*",
            scope_type="project",
            project_id=w.commissions,
            tier="prod",
            level="write",
        )
    )
    await db_session.commit()

    scope = await compute_access_scope(db_session, make_user("anyone", UserRole.WRITE))

    assert scope.writable == COMMISSIONS_PROD


async def test_unplaced_subscription_is_super_admin_only(db_session):
    w = await build_world(db_session)
    for tier in ("prod", "nonprod"):
        await grant(db_session, "ops", project_id=w.commissions, tier=tier, level="write")
    scope = await compute_access_scope(db_session, make_user("ops", UserRole.WRITE))
    assert not scope.can_read(SUB["unplaced"])


async def test_inactive_project_grants_nothing(db_session):
    w = await build_world(db_session)
    await grant(db_session, "dev", project_id=w.commissions, tier="nonprod", level="write")
    project = await db_session.get(Project, w.commissions)
    project.is_active = False
    await db_session.commit()
    invalidate_access_topology()

    scope = await compute_access_scope(db_session, make_user("dev", UserRole.WRITE))

    assert not scope.has_any_access


async def test_grant_covers_subscriptions_added_later(db_session):
    w = await build_world(db_session)
    await grant(db_session, "dev", project_id=w.commissions, tier="nonprod", level="write")
    await compute_access_scope(db_session, make_user("dev", UserRole.WRITE))  # warm the cache

    new_sub = "11111111-0000-0000-0000-000000000099"
    db_session.add(
        AdminSubscription(
            subscription_id=new_sub, subscription_name="ACC-NPRD-31599-ATTCC-2", app_id=w.attcc, tier="nonprod"
        )
    )
    await db_session.commit()
    invalidate_access_topology()

    scope = await compute_access_scope(db_session, make_user("dev", UserRole.WRITE))
    assert scope.can_write(new_sub)


async def test_unset_tier_counts_as_prod(db_session):
    w = await build_world(db_session)
    await grant(db_session, "dev", project_id=w.commissions, tier="nonprod", level="write")
    row = (
        await db_session.execute(
            AdminSubscription.__table__.select().where(AdminSubscription.subscription_id == SUB["attcc_nprd"])
        )
    ).first()
    assert row is not None
    await db_session.execute(
        AdminSubscription.__table__.update()
        .where(AdminSubscription.subscription_id == SUB["attcc_nprd"])
        .values(tier=None)
    )
    await db_session.commit()
    invalidate_access_topology()

    scope = await compute_access_scope(db_session, make_user("dev", UserRole.WRITE))

    assert not scope.can_read(SUB["attcc_nprd"])


async def test_subscription_ids_compare_case_insensitively(db_session):
    w = await build_world(db_session)
    await grant(db_session, "dev", project_id=w.commissions, tier="nonprod", level="write")
    scope = await compute_access_scope(db_session, make_user("dev", UserRole.WRITE))
    assert scope.can_write(SUB["attcc_nprd"].upper())


async def test_database_unavailable_fails_closed():
    with pytest.raises(Exception) as exc:
        await compute_access_scope(None, make_user("dev", UserRole.WRITE))
    assert getattr(exc.value, "status_code", None) == 503


def test_assert_subscription_access_reports_403():
    scope = AccessScope(readable=frozenset({"a"}), writable=frozenset())
    assert_subscription_access(scope, ["A"], "read")
    with pytest.raises(Exception) as exc:
        assert_subscription_access(scope, ["a"], "write")
    assert exc.value.status_code == 403
