"""Tests for the SAN filter on the cached certificate grid.

A certificate is very often looked up by a name that is *not* its CN — a
multi-SAN cert is issued once and then reached under each of the hostnames it
covers, so a grid that only searches the CN cannot find it by the name the
person actually has in hand. These cover that lookup and the two ways it could
quietly go wrong: matching a certificate whose SAN list does not contain the
term, and stacking wrongly against the other toolbar filters.
"""

import json

from sqlalchemy import text

from app.services.certificate_sync_service import CertificateSyncService

COLLECTION_ID = 2573


async def _seed(db_session, *, cert_id: int, cn: str, sans: list[str]) -> None:
    await db_session.execute(
        text(
            "INSERT INTO cert_certificates "
            "(collection_id, certificate_id, common_name, thumbprint, sans, san_count, "
            " issuer_dn, revoked, synced_at, deleted_at) "
            "VALUES (:col, :cid, :cn, :tp, :sans, :n, :issuer, 0, CURRENT_TIMESTAMP, NULL)"
        ),
        {
            "col": COLLECTION_ID,
            "cid": cert_id,
            "cn": cn,
            "tp": f"TP{cert_id}",
            "sans": json.dumps(sans),
            "n": len(sans),
            "issuer": "CN=ATT Issuing CA",
        },
    )
    await db_session.commit()


async def test_finds_a_certificate_by_a_san_that_is_not_its_common_name(db_session):
    await _seed(db_session, cert_id=1, cn="attccgui.dev.att.com", sans=["attccgui.dev.att.com", "portal.dev.att.com"])
    service = CertificateSyncService(db_session)

    found = await service.list_certificates_from_db(collection_id=COLLECTION_ID, page=1, page_size=25, san="portal.dev")

    assert found["total"] == 1
    assert found["items"][0]["common_name"] == "attccgui.dev.att.com"


async def test_san_search_is_case_insensitive(db_session):
    await _seed(db_session, cert_id=1, cn="a.att.com", sans=["Portal.Dev.ATT.com"])
    service = CertificateSyncService(db_session)

    found = await service.list_certificates_from_db(
        collection_id=COLLECTION_ID, page=1, page_size=25, san="portal.dev.att.com"
    )

    assert found["total"] == 1


async def test_san_search_excludes_certificates_without_a_matching_san(db_session):
    # The filter has to narrow the grid; a term present on no SAN must return
    # nothing rather than fall through to the unfiltered list.
    await _seed(db_session, cert_id=1, cn="a.att.com", sans=["a.att.com"])
    await _seed(db_session, cert_id=2, cn="b.att.com", sans=["b.att.com", "alias.att.com"])
    service = CertificateSyncService(db_session)

    found = await service.list_certificates_from_db(
        collection_id=COLLECTION_ID, page=1, page_size=25, san="alias.att.com"
    )

    assert found["total"] == 1
    assert found["items"][0]["id"] == 2

    missing = await service.list_certificates_from_db(
        collection_id=COLLECTION_ID, page=1, page_size=25, san="nothing-here.att.com"
    )

    assert missing["total"] == 0
    assert missing["items"] == []


async def test_san_search_combines_with_the_other_filters(db_session):
    # Filters are ANDed: a SAN match on a certificate excluded by the common
    # name filter must not be returned.
    await _seed(db_session, cert_id=1, cn="alpha.att.com", sans=["shared.att.com"])
    await _seed(db_session, cert_id=2, cn="beta.att.com", sans=["shared.att.com"])
    service = CertificateSyncService(db_session)

    found = await service.list_certificates_from_db(
        collection_id=COLLECTION_ID, page=1, page_size=25, san="shared.att.com", cn="alpha"
    )

    assert found["total"] == 1
    assert found["items"][0]["common_name"] == "alpha.att.com"


async def test_no_san_term_leaves_the_grid_unfiltered(db_session):
    await _seed(db_session, cert_id=1, cn="a.att.com", sans=["a.att.com"])
    await _seed(db_session, cert_id=2, cn="b.att.com", sans=[])
    service = CertificateSyncService(db_session)

    found = await service.list_certificates_from_db(collection_id=COLLECTION_ID, page=1, page_size=25)

    assert found["total"] == 2
