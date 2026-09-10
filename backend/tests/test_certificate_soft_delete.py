"""Tests for certificate soft-delete (the "Deleted Certificates" view).

Soft-delete infers deletion from absence: a cached certificate missing from
Keyfactor's response is stamped with ``deleted_at``. That inference is only
sound when the response is complete, so these cover the failure modes where it
is not — an empty response and a truncated one — because acting on either files
live certificates under "Deleted" and empties the active grid.
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from app.services.certificate_sync_service import CertificateSyncService

COLLECTION_ID = 2573


def _kf_cert(cert_id: int, cn: str) -> dict:
    return {"id": cert_id, "IssuedCN": cn, "Thumbprint": f"TP{cert_id}", "NotAfter": "2027-03-15T00:00:00Z"}


async def _seed_active(db_session, ids: list[int]) -> None:
    for cert_id in ids:
        await db_session.execute(
            text(
                "INSERT INTO cert_certificates "
                "(collection_id, certificate_id, common_name, thumbprint, synced_at, deleted_at) "
                "VALUES (:col, :cid, :cn, :tp, CURRENT_TIMESTAMP, NULL)"
            ),
            {"col": COLLECTION_ID, "cid": cert_id, "cn": f"cert{cert_id}.att.com", "tp": f"TP{cert_id}"},
        )
    await db_session.commit()


async def _counts(db_session) -> tuple[int, int]:
    """Return (active, deleted) row counts for the collection."""
    result = await db_session.execute(
        text(
            "SELECT COUNT(*) FILTER (WHERE deleted_at IS NULL), "
            "COUNT(*) FILTER (WHERE deleted_at IS NOT NULL) "
            "FROM cert_certificates WHERE collection_id = :col"
        ),
        {"col": COLLECTION_ID},
    )
    active, deleted = result.one()
    return active, deleted


def _service(db_session, pages: list[dict]) -> CertificateSyncService:
    """Sync service whose Keyfactor walk yields the supplied pages."""
    service = CertificateSyncService(db_session)
    queue = list(pages)

    async def _list_certificates(**_kwargs):
        return queue.pop(0) if queue else {"items": [], "total": 0}

    service.service.list_certificates = _list_certificates  # type: ignore[method-assign]
    return service


# ── Unsound inference: incomplete responses ────────────────────────────────────


async def test_empty_response_does_not_soft_delete_the_collection(db_session):
    # A failing Keyfactor call that yields no items must not be read as "every
    # certificate was deleted" — that fills the Deleted view with live certs.
    await _seed_active(db_session, [1, 2, 3])
    service = _service(db_session, [{"items": [], "total": 0}])

    await service._sync_collection_certs(COLLECTION_ID, "AP-KF-ATTCC-31599")

    assert await _counts(db_session) == (3, 0)


async def test_empty_response_does_not_blank_the_active_snapshot(db_session):
    # The snapshot replacement deletes active rows before re-inserting, so an
    # empty response would otherwise leave the collection with nothing at all.
    await _seed_active(db_session, [1, 2, 3])
    service = _service(db_session, [{"items": [], "total": 0}])

    retained = await service._sync_collection_certs(COLLECTION_ID, "AP-KF-ATTCC-31599")

    assert retained == 3
    active, _deleted = await _counts(db_session)
    assert active == 3


async def test_partial_page_walk_does_not_soft_delete_the_unfetched(db_session):
    # Keyfactor reports 3 certs but only returns 1: the other 2 were never
    # fetched, so they are missing from the response without being deleted.
    await _seed_active(db_session, [1, 2, 3])
    service = _service(db_session, [{"items": [_kf_cert(1, "cert1.att.com")], "total": 3}])

    await service._sync_collection_certs(COLLECTION_ID, "AP-KF-ATTCC-31599")

    _active, deleted = await _counts(db_session)
    assert deleted == 0


# ── Sound inference: the feature still works ───────────────────────────────────


async def test_complete_response_soft_deletes_genuine_orphans(db_session):
    # Keyfactor's total agrees with what was returned, so cert 3's absence is a
    # real deletion and belongs in the Deleted view.
    await _seed_active(db_session, [1, 2, 3])
    service = _service(
        db_session,
        [{"items": [_kf_cert(1, "cert1.att.com"), _kf_cert(2, "cert2.att.com")], "total": 2}],
    )

    await service._sync_collection_certs(COLLECTION_ID, "AP-KF-ATTCC-31599")

    active, deleted = await _counts(db_session)
    assert (active, deleted) == (2, 1)
    row = await db_session.execute(
        text("SELECT certificate_id FROM cert_certificates WHERE deleted_at IS NOT NULL AND collection_id = :col"),
        {"col": COLLECTION_ID},
    )
    assert row.scalar() == 3


async def test_a_reappearing_certificate_returns_to_the_active_grid(db_session):
    # A cert that comes back must not linger as a duplicate deleted row.
    await _seed_active(db_session, [1, 2])
    orphaning = _service(db_session, [{"items": [_kf_cert(1, "cert1.att.com")], "total": 1}])
    await orphaning._sync_collection_certs(COLLECTION_ID, "AP-KF-ATTCC-31599")
    assert await _counts(db_session) == (1, 1)

    reviving = _service(
        db_session,
        [{"items": [_kf_cert(1, "cert1.att.com"), _kf_cert(2, "cert2.att.com")], "total": 2}],
    )
    await reviving._sync_collection_certs(COLLECTION_ID, "AP-KF-ATTCC-31599")

    assert await _counts(db_session) == (2, 0)


async def test_deleted_rows_are_excluded_from_the_default_listing(db_session):
    await _seed_active(db_session, [1, 2, 3])
    service = _service(
        db_session,
        [{"items": [_kf_cert(1, "cert1.att.com"), _kf_cert(2, "cert2.att.com")], "total": 2}],
    )
    await service._sync_collection_certs(COLLECTION_ID, "AP-KF-ATTCC-31599")

    active = await service.list_certificates_from_db(collection_id=COLLECTION_ID, page=1, page_size=25)
    deleted = await service.list_certificates_from_db(
        collection_id=COLLECTION_ID, page=1, page_size=25, deleted_only=True
    )

    assert active["total"] == 2
    assert deleted["total"] == 1
    # The view depends on this field to strike the row through; without it the
    # grid renders a deleted cert as a normal valid one.
    assert deleted["items"][0]["deleted_at"] is not None


# ── Collection tile count ──────────────────────────────────────────────────────


async def test_tile_count_matches_the_grid_after_a_renewal(db_session):
    # A renewal adds a certificate, but Keyfactor's collection total lags a few
    # minutes behind. Trusting it put "32 certs" on the tile beside a grid
    # listing 33.
    await _seed_active(db_session, [1, 2])
    await db_session.execute(
        text(
            "INSERT INTO cert_collections (collection_id, name, certificate_count, synced_at) "
            "VALUES (:col, 'AP-KF-ATTCC-31599', 2, CURRENT_TIMESTAMP)"
        ),
        {"col": COLLECTION_ID},
    )
    await db_session.commit()

    renewed = [_kf_cert(1, "cert1.att.com"), _kf_cert(2, "cert2.att.com"), _kf_cert(3, "renewed.att.com")]
    service = _service(db_session, [{"items": renewed, "total": 2}])  # total still says 2
    await service._sync_collection_certs(COLLECTION_ID, "AP-KF-ATTCC-31599")

    grid = await service.list_certificates_from_db(collection_id=COLLECTION_ID, page=1, page_size=25)
    tile = next(c for c in await service.list_collections_from_db() if c["id"] == COLLECTION_ID)
    assert grid["total"] == 3
    assert tile["certificate_count"] == grid["total"]


async def test_tile_count_ignores_soft_deleted_rows(db_session):
    await _seed_active(db_session, [1, 2, 3])
    await db_session.execute(
        text(
            "INSERT INTO cert_collections (collection_id, name, certificate_count, synced_at) "
            "VALUES (:col, 'AP-KF-ATTCC-31599', 3, CURRENT_TIMESTAMP)"
        ),
        {"col": COLLECTION_ID},
    )
    await db_session.commit()

    service = _service(
        db_session,
        [{"items": [_kf_cert(1, "cert1.att.com"), _kf_cert(2, "cert2.att.com")], "total": 2}],
    )
    await service._sync_collection_certs(COLLECTION_ID, "AP-KF-ATTCC-31599")

    tile = next(c for c in await service.list_collections_from_db() if c["id"] == COLLECTION_ID)
    assert tile["certificate_count"] == 2


def test_tile_count_prefers_the_stored_total_only_when_truncated():
    from app.services.certificate_sync_service import _MAX_CERTS_PER_COLLECTION

    count = CertificateSyncService._tile_count
    # Stale stored total loses to what is actually cached.
    assert count(33, 32) == 33
    # Nothing cached yet: the stored total is all there is.
    assert count(0, 32) == 32
    # A collection larger than the cap keeps its true size on the tile.
    assert count(_MAX_CERTS_PER_COLLECTION, 15_000) == 15_000


# ── Revoked certificates ───────────────────────────────────────────────────────


async def _seed_revoked(db_session, cert_id: int) -> None:
    """A certificate revoked through the portal, as mark_certificate_revoked leaves it."""
    await db_session.execute(
        text(
            "INSERT INTO cert_certificates "
            "(collection_id, certificate_id, common_name, thumbprint, revoked, status, synced_at, deleted_at) "
            "VALUES (:col, :cid, :cn, :tp, 1, 'revoked', CURRENT_TIMESTAMP, NULL)"
        ),
        {
            "col": COLLECTION_ID,
            "cid": cert_id,
            "cn": "customeraccountanalyser.test.att.com",
            "tp": f"TP{cert_id}",
        },
    )
    await db_session.commit()


async def test_a_revoked_certificate_is_not_filed_as_deleted(db_session):
    # Revoking drops the cert out of the collection's saved search, so it is
    # absent from the next sync. Reading that as a deletion put the user's
    # revocation under "Deleted" and left the Revoked tile on 0.
    await _seed_active(db_session, [1])
    await _seed_revoked(db_session, 9)

    service = _service(db_session, [{"items": [_kf_cert(1, "cert1.att.com")], "total": 1}])
    await service._sync_collection_certs(COLLECTION_ID, "AP-KF-ATTCC-31599")

    _active, deleted = await _counts(db_session)
    assert deleted == 0


async def test_a_revoked_certificate_survives_the_snapshot_replacement(db_session):
    # The replacement deletes active rows before re-inserting; the fresh response
    # does not carry the revoked cert, so without an exemption it vanishes.
    await _seed_active(db_session, [1])
    await _seed_revoked(db_session, 9)

    service = _service(db_session, [{"items": [_kf_cert(1, "cert1.att.com")], "total": 1}])
    await service._sync_collection_certs(COLLECTION_ID, "AP-KF-ATTCC-31599")

    row = await db_session.execute(
        text("SELECT revoked, status, deleted_at FROM cert_certificates WHERE certificate_id = 9")
    )
    revoked, status, deleted_at = row.one()
    assert bool(revoked) is True
    assert status == "revoked"
    assert deleted_at is None


async def test_the_revoked_filter_finds_it_after_a_sync(db_session):
    await _seed_active(db_session, [1])
    await _seed_revoked(db_session, 9)

    service = _service(db_session, [{"items": [_kf_cert(1, "cert1.att.com")], "total": 1}])
    await service._sync_collection_certs(COLLECTION_ID, "AP-KF-ATTCC-31599")

    revoked = await service.list_certificates_from_db(
        collection_id=COLLECTION_ID, page=1, page_size=25, cert_status="Revoked"
    )
    assert revoked["total"] == 1
    assert revoked["items"][0]["common_name"] == "customeraccountanalyser.test.att.com"


async def test_the_collection_card_excludes_a_preserved_revoked_certificate(db_session):
    # The card predicts the grid, and the grid is active-only — so a card that
    # counted the revoked row would change number the moment it was clicked.
    await _seed_active(db_session, [1])
    await _seed_revoked(db_session, 9)
    await db_session.execute(
        text(
            "INSERT INTO cert_collections (collection_id, name, certificate_count, synced_at) "
            "VALUES (:col, 'AP-KF-ATTCC-31599', 2, CURRENT_TIMESTAMP)"
        ),
        {"col": COLLECTION_ID},
    )
    await db_session.commit()

    service = _service(db_session, [{"items": [_kf_cert(1, "cert1.att.com")], "total": 1}])
    await service._sync_collection_certs(COLLECTION_ID, "AP-KF-ATTCC-31599")

    grid = await service.list_certificates_from_db(collection_id=COLLECTION_ID, page=1, page_size=25)
    tile = next(c for c in await service.list_collections_from_db() if c["id"] == COLLECTION_ID)
    assert grid["total"] == 1
    assert tile["certificate_count"] == grid["total"]


async def test_a_genuinely_deleted_certificate_is_still_soft_deleted(db_session):
    # The exemption is only for revoked rows; an ordinary disappearance must
    # still reach the Deleted view.
    await _seed_active(db_session, [1, 2])
    await _seed_revoked(db_session, 9)

    service = _service(db_session, [{"items": [_kf_cert(1, "cert1.att.com")], "total": 1}])
    await service._sync_collection_certs(COLLECTION_ID, "AP-KF-ATTCC-31599")

    row = await db_session.execute(text("SELECT certificate_id FROM cert_certificates WHERE deleted_at IS NOT NULL"))
    assert row.scalar() == 2


# ── Expiry windows exclude revoked and deleted ─────────────────────────────────


async def _seed_expiring(db_session, *, cert_id: int, days_out: int, revoked: bool = False) -> None:
    expiry = (datetime.now(UTC) + timedelta(days=days_out)).strftime("%Y-%m-%dT%H:%M:%S%z")
    await db_session.execute(
        text(
            "INSERT INTO cert_certificates "
            "(collection_id, certificate_id, common_name, thumbprint, not_after, revoked, status, synced_at) "
            "VALUES (:col, :cid, :cn, :tp, :na, :rev, :st, CURRENT_TIMESTAMP)"
        ),
        {
            "col": COLLECTION_ID,
            "cid": cert_id,
            "cn": f"cert{cert_id}.att.com",
            "tp": f"TP{cert_id}",
            "na": expiry,
            "rev": 1 if revoked else 0,
            "st": "revoked" if revoked else "valid",
        },
    )
    await db_session.commit()


async def test_expiry_window_excludes_revoked_certificates(db_session):
    # The 60d tile read 5 while two of those five were revoked. A revoked cert
    # is never going to be renewed, so it does not belong on a renewal worklist.
    await _seed_expiring(db_session, cert_id=1, days_out=40)
    await _seed_expiring(db_session, cert_id=2, days_out=45)
    await _seed_expiring(db_session, cert_id=3, days_out=50, revoked=True)
    service = CertificateSyncService(db_session)

    due = await service.list_certificates_from_db(collection_id=COLLECTION_ID, page=1, page_size=25, expires_in_days=60)

    assert due["total"] == 2
    assert all(item["revoked"] is False for item in due["items"])


async def test_expiry_window_excludes_deleted_certificates(db_session):
    await _seed_expiring(db_session, cert_id=1, days_out=40)
    await _seed_expiring(db_session, cert_id=2, days_out=45)
    await db_session.execute(
        text("UPDATE cert_certificates SET deleted_at = CURRENT_TIMESTAMP WHERE certificate_id = 2")
    )
    await db_session.commit()
    service = CertificateSyncService(db_session)

    due = await service.list_certificates_from_db(collection_id=COLLECTION_ID, page=1, page_size=25, expires_in_days=60)

    assert due["total"] == 1


async def test_an_explicit_revoked_search_still_returns_them(db_session):
    # Excluding revoked from expiry windows must not break the toolbar filter
    # that exists specifically to find them.
    await _seed_expiring(db_session, cert_id=1, days_out=40)
    await _seed_expiring(db_session, cert_id=3, days_out=50, revoked=True)
    service = CertificateSyncService(db_session)

    found = await service.list_certificates_from_db(
        collection_id=COLLECTION_ID, page=1, page_size=25, cert_status="Revoked"
    )

    assert found["total"] == 1
    assert found["items"][0]["revoked"] is True


async def test_the_default_grid_hides_revoked_certificates(db_session):
    # The default view is active-only: a revoked certificate is an end-of-life
    # record, not something anyone acts on from the main grid.
    await _seed_expiring(db_session, cert_id=1, days_out=40)
    await _seed_expiring(db_session, cert_id=3, days_out=50, revoked=True)
    service = CertificateSyncService(db_session)

    default_view = await service.list_certificates_from_db(collection_id=COLLECTION_ID, page=1, page_size=25)

    assert default_view["total"] == 1
    assert default_view["items"][0]["revoked"] is False


async def test_hiding_revoked_does_not_discard_the_row(db_session):
    # Hidden from the default grid, but still cached and still reachable — the
    # revocation must not be lost just because it is filtered out by default.
    await _seed_expiring(db_session, cert_id=3, days_out=50, revoked=True)
    service = CertificateSyncService(db_session)

    found = await service.list_certificates_from_db(
        collection_id=COLLECTION_ID, page=1, page_size=25, cert_status="revoked"
    )

    assert found["total"] == 1
    assert found["items"][0]["deleted_at"] is None
