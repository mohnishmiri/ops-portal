"""Unit tests for CertificateSyncService running-state handling.

Guards against orphaned 'running' sync rows (crashed/restarted process) that
otherwise pin the certificate page's sync badge on 'Syncing…' forever and keep
lazy cache refreshes skipping.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services.certificate_sync_service import (
    _RUNNING_SYNC_TIMEOUT_MINUTES,
    CertificateSyncService,
)


class _FakeResult:
    def __init__(self, *, scalar: object = None, rowcount: int = 0) -> None:
        self._scalar = scalar
        self.rowcount = rowcount

    def scalar_one_or_none(self) -> object:
        return self._scalar

    def scalar(self) -> object:
        return self._scalar


class _ScalarsView:
    def __init__(self, objs: list[object]) -> None:
        self._objs = objs

    def all(self) -> list[object]:
        return self._objs


class _RowsResult:
    """Result supporting both .all() (row tuples) and .scalars().all() (ORM rows)."""

    def __init__(self, *, rows: list[object] | None = None, scalars: list[object] | None = None) -> None:
        self._rows = rows or []
        self._scalars = scalars or []

    def all(self) -> list[object]:
        return self._rows

    def scalars(self) -> _ScalarsView:
        return _ScalarsView(self._scalars)


class _FakeSession:
    """Returns queued results for each execute() call and counts commits."""

    def __init__(self, results: list[object]) -> None:
        self._results = list(results)
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, _statement: object) -> object:
        return self._results.pop(0) if self._results else _FakeResult()

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _CaptureSession:
    """Session that records ORM rows added via .add() and ignores execute()."""

    def __init__(self) -> None:
        self.added: list[object] = []
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, _statement: object) -> object:
        return _FakeResult()

    def add(self, obj: object) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


class _FakeCertService:
    """Stands in for CertificateService.list_certificates, returning queued pages."""

    def __init__(self, pages: list[dict[str, object]]) -> None:
        self._pages = pages

    async def list_certificates(
        self, *, query: object, page: int, page_size: int, collection_id: int | None = None
    ) -> dict[str, object]:
        idx = page - 1
        if 0 <= idx < len(self._pages):
            return self._pages[idx]
        return {"items": [], "total": 0, "page": page, "page_size": page_size}


async def test_is_sync_running_true_for_recent_row() -> None:
    recent = datetime.utcnow() - timedelta(minutes=1)
    svc = CertificateSyncService(_FakeSession([_FakeResult(scalar=recent)]))
    assert await svc.is_sync_running() is True


async def test_is_sync_running_false_for_abandoned_row() -> None:
    stale = datetime.utcnow() - timedelta(minutes=_RUNNING_SYNC_TIMEOUT_MINUTES + 5)
    svc = CertificateSyncService(_FakeSession([_FakeResult(scalar=stale)]))
    assert await svc.is_sync_running() is False


async def test_is_sync_running_false_when_no_running_row() -> None:
    svc = CertificateSyncService(_FakeSession([_FakeResult(scalar=None)]))
    assert await svc.is_sync_running() is False


async def test_expire_abandoned_running_rows_commits_when_stale() -> None:
    session = _FakeSession([_FakeResult(rowcount=2)])
    svc = CertificateSyncService(session)
    expired = await svc._expire_abandoned_running_rows()
    assert expired == 2
    assert session.commits == 1


async def test_expire_abandoned_running_rows_noop_when_nothing_stale() -> None:
    session = _FakeSession([_FakeResult(rowcount=0)])
    svc = CertificateSyncService(session)
    expired = await svc._expire_abandoned_running_rows()
    assert expired == 0
    assert session.commits == 0


async def test_mark_certificate_revoked_updates_cache_and_commits() -> None:
    captured: dict[str, object] = {}

    class _CaptureExecSession(_FakeSession):
        async def execute(self, statement: object) -> object:
            captured["stmt"] = statement
            return _FakeResult(rowcount=1)

    session = _CaptureExecSession([])
    svc = CertificateSyncService(session)
    updated = await svc.mark_certificate_revoked(42, collection_id=7, reason=1)
    assert updated == 1
    assert session.commits == 1
    assert session.rollbacks == 0
    assert captured["stmt"].table.name == "cert_certificates"


async def test_mark_certificate_revoked_rolls_back_on_error() -> None:
    class _BoomSession(_FakeSession):
        async def execute(self, _statement: object) -> object:
            raise RuntimeError("no such table: cert_certificates")

    session = _BoomSession([])
    svc = CertificateSyncService(session)
    updated = await svc.mark_certificate_revoked(42)
    assert updated == 0
    assert session.rollbacks == 1
    assert session.commits == 0


async def test_list_collections_from_db_prefers_stored_total() -> None:
    # Authoritative Keyfactor total persisted on the snapshot wins over cached rows.
    col = SimpleNamespace(collection_id=7, name="AP-KF-ATTCC-31599", description="", certificate_count=42, query="")
    session = _FakeSession([_RowsResult(rows=[(7, 5)]), _RowsResult(scalars=[col])])
    svc = CertificateSyncService(session)
    out = await svc.list_collections_from_db()
    assert out[0]["certificate_count"] == 42


async def test_list_collections_from_db_falls_back_to_cached_rows() -> None:
    # When the stored total is 0 (cached before the count fix), self-heal from
    # the actual number of cached certificate rows instead of showing 0.
    col = SimpleNamespace(collection_id=7, name="AP-KF-ATTCC-31599", description="", certificate_count=0, query="")
    session = _FakeSession([_RowsResult(rows=[(7, 5)]), _RowsResult(scalars=[col])])
    svc = CertificateSyncService(session)
    out = await svc.list_collections_from_db()
    assert out[0]["certificate_count"] == 5


async def test_count_collections_scopes_to_admin_enabled_set() -> None:
    # The sync-status "Collections" count must mirror the admin-enabled filter:
    # empty/None => count all; a non-empty set restricts to those collections.
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    from app.models.database import CertificateCollectionSnapshot

    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    try:
        async with engine.begin() as conn:
            await conn.run_sync(CertificateCollectionSnapshot.__table__.create)
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            session.add_all(
                [
                    CertificateCollectionSnapshot(collection_id=1, name="A"),
                    CertificateCollectionSnapshot(collection_id=2, name="B"),
                    CertificateCollectionSnapshot(collection_id=3, name="C"),
                ]
            )
            await session.commit()
            svc = CertificateSyncService(session)
            assert await svc.count_collections() == 3
            assert await svc.count_collections(None) == 3
            assert await svc.count_collections([]) == 3
            assert await svc.count_collections([1]) == 1
            assert await svc.count_collections([1, 2]) == 2
            assert await svc.count_collections([999]) == 0
    finally:
        await engine.dispose()


async def test_count_due_certificates_returns_db_count() -> None:
    # Smoke test: the due-count query returns the DB scalar. The expiry/id WHERE
    # clauses mirror list_certificates_from_db and are covered end-to-end by the
    # certificates API tests.
    session = _FakeSession([_FakeResult(scalar=3)])
    svc = CertificateSyncService(session)
    assert await svc.count_due_certificates(collection_id=1, days_before_expiry=60) == 3


async def test_count_due_certificates_scoped_to_ids() -> None:
    session = _FakeSession([_FakeResult(scalar=1)])
    svc = CertificateSyncService(session)
    assert await svc.count_due_certificates(collection_id=1, days_before_expiry=30, certificate_ids=[5]) == 1


async def test_sync_collection_certs_dedups_certificate_ids() -> None:
    # Keyfactor pagination overlap / missing ids must not violate the
    # (collection_id, certificate_id) unique constraint.
    session = _CaptureSession()
    svc = CertificateSyncService(session)
    svc.service = _FakeCertService(
        [
            {
                "items": [
                    {"id": 1, "common_name": "a"},
                    {"id": 1, "common_name": "a-dup"},
                    {"id": 2, "common_name": "b"},
                    {"id": None, "common_name": "no-id-1"},
                    {"id": None, "common_name": "no-id-2"},
                ],
                "total": 5,
            }
        ]
    )
    count = await svc._sync_collection_certs(7, "coll")
    # ids 1, 2, and one 0 (from the first missing id) — the rest are dropped.
    assert count == 3
    assert sorted(r.certificate_id for r in session.added) == [0, 1, 2]
    assert session.rollbacks == 0


async def test_to_row_coerces_non_string_and_numeric_fields() -> None:
    # Keyfactor sends KeyUsage as an int and RevocationReason sometimes as a
    # string; both must be coerced so asyncpg never raises a DataError.
    row = CertificateSyncService._to_row(
        {
            "id": 5,
            "key_usage": 5,
            "extended_key_usage": ["serverAuth", "clientAuth"],
            "revocation_reason": "2",
            "key_size": "2048",
        },
        collection_id=1,
        collection_name="c",
        synced_at=datetime.utcnow(),
    )
    assert row.key_usage == "5"
    assert isinstance(row.extended_key_usage, str)
    assert row.revocation_reason == 2
    assert row.key_size == 2048


async def test_to_row_clips_overlong_strings() -> None:
    row = CertificateSyncService._to_row(
        {"id": 1, "thumbprint": "A" * 500, "common_name": "B" * 1000},
        collection_id=1,
        collection_name="c",
        synced_at=datetime.utcnow(),
    )
    assert len(row.thumbprint) == 100  # String(100)
    assert len(row.common_name) == 500  # String(500)
