"""Credential account inventory: import parsing, export, check write-back, access.

The import is the part most likely to meet messy input — people's mechID
sheets are not written to a template — so most of the coverage is there.
"""

import io
from datetime import UTC, date, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from openpyxl import Workbook, load_workbook
from sqlalchemy import select

from app.auth import get_current_user
from app.core.database import get_db
from app.models.database import AuditLog, CredentialAccount
from app.schemas.auth import UserContext, UserRole
from app.schemas.credential_inventory import CredentialAccountCreate, CredentialAccountImportRow, CredentialAccountIn
from app.schemas.tools import CredentialAccountDetails
from app.services import credential_inventory_service as inv
from app.services.credential_check_service import CheckOutcome

TODAY = date(2026, 10, 12)


def _writer() -> UserContext:
    return UserContext(
        user_id="test-writer",
        object_id="22222222-2222-2222-2222-222222222222",
        display_name="Test Writer",
        email="writer@example.com",
        roles=[UserRole.WRITE],
        raw_roles=["write"],
        tenant_id="tenant-test",
        allowed_subscriptions=[],
    )


def _account(**overrides) -> CredentialAccountIn:
    values = {
        "application": "ATTCC",
        "account_type": "domain",
        "directory": "ITSERVICES",
        "account_name": "m52142",
        "owner": "Jane Doe",
    }
    values.update(overrides)
    return CredentialAccountIn(**values)


def _xlsx(rows: list[list], header_at: int = 1) -> bytes:
    workbook = Workbook()
    ws = workbook.active
    for _ in range(header_at - 1):
        ws.append(["AT&T Proprietary (Restricted)"])
    for row in rows:
        ws.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


# ── Reading a row ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("type_cell", "directory_cell", "expected"),
    [
        ("ITSERVICES", None, ("domain", "ITSERVICES")),
        ("testitservices", None, ("domain", "TESTITSERVICES")),
        ("Domain", "TESTITSERVICES", ("domain", "TESTITSERVICES")),
        ("AAF", None, ("aaf", "prod")),
        ("AAF", "IST", ("aaf", "nonprod")),
        ("AAF - Non-Prod", None, ("aaf", "nonprod")),
        ("JFrog", None, ("jfrog", "bronze")),
        ("JFrog Gold", None, ("jfrog", "gold")),
        ("Artifactory", "artifact-gold.it.att.com", ("jfrog", "gold")),
        (None, "Gold", ("jfrog", "gold")),  # no Type column: the directory says it
        (None, "ITSERVICES", ("domain", "ITSERVICES")),
    ],
)
def test_import_reads_the_ways_people_write_the_type(type_cell, directory_cell, expected):
    row, errors = inv.parse_import_row(
        {"application": "ATTCC", "account_type": type_cell, "directory": directory_cell, "account_name": "m1"}
    )
    assert errors == []
    assert (row.account_type, row.directory) == expected


@pytest.mark.parametrize(
    ("type_cell", "directory_cell", "fragment"),
    [
        ("Kerberos", None, "is not one of"),
        ("JFrog", "IST", "does not fit a JFrog account"),
        ("AAF", "Platinum", "is not recognised"),
    ],
)
def test_import_names_a_bad_type_or_directory(type_cell, directory_cell, fragment):
    row, errors = inv.parse_import_row(
        {"application": "ATTCC", "account_type": type_cell, "directory": directory_cell, "account_name": "m1"}
    )
    assert row is None
    assert fragment in errors[0]


@pytest.mark.parametrize(
    ("cell", "expected", "never"),
    [
        (datetime(2026, 12, 14, 9, 30), date(2026, 12, 14), None),
        ("2026-12-14", date(2026, 12, 14), None),
        ("12/14/2026", date(2026, 12, 14), None),
        ("14-Dec-2026", date(2026, 12, 14), None),
        (46370, date(2026, 12, 14), None),  # an Excel serial in an unformatted cell
        ("Never", None, True),
        ("N/A", None, None),
    ],
)
def test_import_reads_expiry_dates(cell, expected, never):
    row, errors = inv.parse_import_row(
        {"application": "ATTCC", "account_type": "AAF", "account_name": "m1@com.att.attcc", "expiry_date": cell}
    )
    assert errors == []
    assert row.expiry_date == expected
    assert row.never_expires is (never if never is not None else (False if expected else None))


def test_import_collects_every_problem_in_a_row():
    row, errors = inv.parse_import_row(
        {
            "account_type": "ITSERVICES",
            "account_name": "",
            "expiry_date": "next tuesday",
            "failed_logins": "lots",
        }
    )
    assert row is None
    assert any(e.startswith("Expiry Date:") for e in errors)
    assert any(e.startswith("Failed Logins:") for e in errors)
    assert "Application: required" in errors
    assert "Account: required" in errors


def test_a_reset_link_must_be_a_web_link():
    """It is rendered as a link — javascript: would run in the reader's browser."""
    row, errors = inv.parse_import_row(
        {
            "application": "ATTCC",
            "account_type": "ITSERVICES",
            "account_name": "m1",
            "reset_url": "javascript:alert(1)",
        }
    )
    assert row is None
    assert errors == ["Reset Link: Reset link must be an http:// or https:// URL"]


# ── Reading a file ─────────────────────────────────────────────────────


def test_import_finds_the_header_below_a_title_so_an_export_imports_back():
    content = _xlsx(
        [["Application", "Type", "Account", "Owner"], ["ATTCC", "ITSERVICES", "m52142", "Jane"]],
        header_at=4,
    )
    rows = inv.read_import_file("accounts.xlsx", content)
    expected = {"application": "ATTCC", "account_type": "ITSERVICES", "account_name": "m52142", "owner": "Jane"}
    assert rows == [(5, expected)]


def test_import_reads_header_aliases():
    content = _xlsx(
        [["App Name", "Account Type", "MechID", "Expiration Date", "Comments"], ["DWS", "AAF", "m1", None, "x"]]
    )
    ((_, raw),) = inv.read_import_file("ids.xlsx", content)
    assert set(raw) == {"application", "account_type", "account_name", "expiry_date", "notes"}


def test_import_reads_a_windows_excel_csv():
    """Excel on Windows saves "CSV" in the ANSI code page, not UTF-8."""
    content = "Application,Type,Account,Owner\r\nATTCC,ITSERVICES,m1,José\r\n".encode("cp1252")
    ((_, raw),) = inv.read_import_file("ids.csv", content)
    assert raw["owner"] == "José"


@pytest.mark.parametrize(
    ("filename", "content", "fragment"),
    [
        ("ids.xls", b"\xd0\xcf", "save it as .xlsx or .csv"),
        ("ids.txt", b"x", "Upload an Excel"),
        ("ids.xlsx", b"not a zip", "could not be read"),
        ("ids.csv", b"Name,Value\r\na,b\r\n", "No header row found"),
    ],
)
def test_import_refuses_files_it_cannot_read(filename, content, fragment):
    with pytest.raises(ValueError) as excinfo:
        inv.read_import_file(filename, content)
    assert fragment in str(excinfo.value)


def test_import_caps_the_row_count(monkeypatch):
    monkeypatch.setattr(inv, "IMPORT_MAX_ROWS", 2)
    content = "Application,Type,Account\r\n" + "".join(f"A,ITSERVICES,m{i}\r\n" for i in range(3))
    with pytest.raises(ValueError, match="more than 2 accounts"):
        inv.read_import_file("ids.csv", content.encode())


def test_the_template_imports_cleanly_and_holds_no_example_rows():
    content = inv.import_template_xlsx()
    workbook = load_workbook(io.BytesIO(content))
    assert workbook.sheetnames == ["Accounts", "How to fill"]
    assert inv.read_import_file("template.xlsx", content) == []


# ── Export ─────────────────────────────────────────────────────────────


def _row(**overrides) -> CredentialAccount:
    values = {
        "id": 1,
        "application": "ATTCC",
        "app_code": "31599",
        "account_type": "domain",
        "directory": "ITSERVICES",
        "account_name": "m52142",
        "account_key": "m52142",
        "owner": "Jane",
        "expiry_date": date(2026, 12, 14),
        "never_expires": False,
        "failed_logins": 0,
        "notes": None,
        "reset_url": None,
        "last_check_status": None,
        "last_checked_at": None,
        "password_changed_date": None,
        "last_login_date": None,
    }
    values.update(overrides)
    return CredentialAccount(**values)


def test_csv_export_neutralises_formulas():
    content = inv.export_csv([_row(notes='=HYPERLINK("http://x")', owner="+1 call")], today=TODAY).decode("utf-8-sig")
    assert "'=HYPERLINK" in content
    assert "'+1 call" in content


def test_xlsx_export_keeps_a_formula_like_note_as_text():
    content = inv.export_xlsx([_row(notes="=1+1")], today=TODAY, generated_at=datetime(2026, 10, 12, tzinfo=UTC))
    ws = load_workbook(io.BytesIO(content)).active
    notes_col = [c.value for c in ws[4]].index("Notes") + 1
    cell = ws.cell(row=5, column=notes_col)
    assert cell.data_type == "s"
    assert cell.value == "=1+1"


def test_an_export_imports_back_as_the_same_accounts():
    rows = [_row(), _row(id=2, account_type="jfrog", directory="gold", account_name="svc@att.com", never_expires=True)]
    content = inv.export_xlsx(rows, today=TODAY, generated_at=datetime(2026, 10, 12, tzinfo=UTC))

    parsed = [inv.parse_import_row(raw) for _, raw in inv.read_import_file("export.xlsx", content)]

    assert all(errors == [] for _, errors in parsed)
    first, second = (row for row, _ in parsed)
    assert (first.account_type, first.directory, first.expiry_date) == ("domain", "ITSERVICES", date(2026, 12, 14))
    assert (second.account_type, second.directory, second.never_expires) == ("jfrog", "gold", True)


def test_filters_match_the_grid_tiles():
    expired = _row(id=1, expiry_date=date(2026, 10, 1))
    expiring = _row(id=2, expiry_date=date(2026, 10, 30))
    later = _row(id=3, expiry_date=date(2027, 6, 1))
    never = _row(id=4, expiry_date=None, never_expires=True)
    locked = _row(id=5, expiry_date=None, last_check_status="locked")
    failed = _row(id=6, expiry_date=None, failed_logins=3)
    everything = [expired, expiring, later, never, locked, failed]

    def ids(view):
        return [a.id for a in inv.filter_accounts(everything, inv.AccountFilter(view=view), today=TODAY)]

    assert ids("expired") == [1]
    assert ids("expiring") == [2]
    assert ids("failing") == [5, 6]
    searched = inv.filter_accounts(everything, inv.AccountFilter(q="jane"), today=TODAY)
    assert [a.id for a in searched] == [1, 2, 3, 4, 5, 6]


# ── Service: create, import, check write-back ──────────────────────────


@pytest.mark.anyio
async def test_the_same_account_cannot_be_listed_twice_in_any_case(db_session):
    service = inv.CredentialInventoryService(db_session)
    await service.create(_account(), _writer())
    with pytest.raises(inv.DuplicateAccountError):
        await service.create(_account(account_name="M52142", application="DWS"), _writer())
    # Same name in another directory is another account.
    await service.create(_account(directory="TESTITSERVICES"), _writer())


@pytest.mark.anyio
async def test_preview_says_create_update_or_why_not(db_session):
    service = inv.CredentialInventoryService(db_session)
    await service.create(_account(), _writer())
    content = (
        b"Application,Type,Account,Failed Logins\r\n"
        b"ATTCC,ITSERVICES,M52142,2\r\n"
        b"ATTCC,AAF,m1@com.att.attcc,\r\n"
        b"ATTCC,aaf,M1@com.att.attcc,\r\n"
        b",JFrog,svc,\r\n"
    )

    preview = await service.preview_import("ids.csv", content)

    assert [(r.row, r.action) for r in preview.rows] == [(2, "update"), (3, "create"), (4, "invalid"), (5, "invalid")]
    assert preview.rows[2].errors == ["Same account as row 3"]
    assert preview.rows[3].errors == ["Application: required"]
    assert (preview.create_count, preview.update_count, preview.invalid_count) == (1, 1, 2)


@pytest.mark.anyio
async def test_an_import_fills_in_but_never_erases(db_session):
    service = inv.CredentialInventoryService(db_session)
    created = await service.create(
        _account(expiry_date=date(2026, 12, 14), notes="rotate via CyberArk", failed_logins=1), _writer()
    )

    result = await service.apply_import(
        [
            CredentialAccountImportRow(
                application="ATTCC",
                account_type="domain",
                directory="ITSERVICES",
                account_name="M52142",
                failed_logins=4,
            ),
            CredentialAccountImportRow(application="DWS", account_type="aaf", directory="prod", account_name="m1"),
        ],
        _writer(),
    )

    assert (result.created, result.updated) == (1, 1)
    row = await service.get(created.id)
    assert row.failed_logins == 4
    assert row.expiry_date == date(2026, 12, 14)  # blank in the file: kept
    assert row.notes == "rotate via CyberArk"


@pytest.mark.anyio
async def test_a_check_writes_its_verdict_and_details_onto_the_listed_account(db_session):
    service = inv.CredentialInventoryService(db_session)
    created = await service.create(_account(failed_logins=2), _writer())
    outcome = CheckOutcome(
        valid=True,
        status="valid",
        message="ok",
        account=CredentialAccountDetails(
            expires_at=datetime(2026, 12, 14, 15, 0, tzinfo=UTC),
            last_used_at=datetime(2026, 10, 1, 8, 0, tzinfo=UTC),
            last_changed_at=datetime(2026, 9, 15, tzinfo=UTC),
        ),
    )

    updated = await service.record_check(
        account_type="domain", directory="ITSERVICES", account_name="M52142", outcome=outcome, checked_by="w@x.com"
    )

    assert updated is True
    row = await service.get(created.id)
    assert (row.last_check_status, row.last_checked_by) == ("valid", "w@x.com")
    assert row.expiry_date == date(2026, 12, 14)
    assert row.last_login_date == date(2026, 10, 1)
    assert row.password_changed_date == date(2026, 9, 15)
    assert row.failed_logins == 2  # never taken from a check


@pytest.mark.anyio
async def test_an_unreachable_check_and_an_unlisted_account_change_nothing(db_session):
    service = inv.CredentialInventoryService(db_session)
    created = await service.create(_account(), _writer())
    error = CheckOutcome(valid=False, status="error", message="timed out")

    assert (
        await service.record_check(
            account_type="domain", directory="ITSERVICES", account_name="m52142", outcome=error, checked_by="w"
        )
        is False
    )
    assert (
        await service.record_check(
            account_type="domain",
            directory="ITSERVICES",
            account_name="someone-else",
            outcome=CheckOutcome(valid=True, status="valid", message="ok"),
            checked_by="w",
        )
        is False
    )
    assert (await service.get(created.id)).last_check_status is None


# ── API ────────────────────────────────────────────────────────────────


@pytest.fixture
async def writer_client(app, db_session):
    async def _db():
        yield db_session

    async def _user():
        return _writer()

    app.dependency_overrides[get_db] = _db
    app.dependency_overrides[get_current_user] = _user
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()


_BODY = {"application": "ATTCC", "account_type": "domain", "directory": "itservices", "account_name": "m52142"}


@pytest.mark.anyio
async def test_a_reader_sees_the_inventory_but_cannot_change_it(reader_client):
    assert (await reader_client.get("/api/v1/tools/accounts")).status_code == 200
    assert (await reader_client.post("/api/v1/tools/accounts", json=_BODY)).status_code == 403
    files = {"file": ("ids.csv", b"Application,Type,Account\r\nA,ITSERVICES,m1\r\n", "text/csv")}
    assert (await reader_client.post("/api/v1/tools/accounts/import/preview", files=files)).status_code == 403


@pytest.mark.anyio
async def test_adding_an_account_is_audited_and_never_takes_a_password(writer_client, db_session):
    response = await writer_client.post("/api/v1/tools/accounts", json={**_BODY, "password": "hunter2"})

    assert response.status_code == 201
    assert response.json()["directory"] == "ITSERVICES"
    assert "password" not in response.json()
    audit = (await db_session.execute(select(AuditLog))).scalars().one()
    assert audit.action == "create_credential_account"
    assert audit.details["feature"] == "credential_inventory"
    assert "hunter2" not in str(audit.details)

    duplicate = await writer_client.post("/api/v1/tools/accounts", json={**_BODY, "account_name": "M52142"})
    assert duplicate.status_code == 409


@pytest.mark.anyio
async def test_export_returns_the_filtered_rows(writer_client):
    await writer_client.post("/api/v1/tools/accounts", json=_BODY)
    await writer_client.post(
        "/api/v1/tools/accounts", json={**_BODY, "application": "DWS", "account_type": "jfrog", "directory": "gold"}
    )

    response = await writer_client.get("/api/v1/tools/accounts/export", params={"format": "csv", "application": "DWS"})

    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]
    lines = response.content.decode("utf-8-sig").strip().splitlines()
    assert len(lines) == 2 and "Gold" in lines[1]


@pytest.mark.anyio
async def test_a_check_of_a_listed_account_updates_its_row(writer_client, monkeypatch):
    from app.api.v1.endpoints import tools

    await writer_client.post(
        "/api/v1/tools/accounts",
        json={**_BODY, "account_type": "jfrog", "directory": "gold", "account_name": "svc@att.com"},
    )
    seen = {}

    async def _fake_check(username, token, instance="bronze"):
        seen["instance"] = instance
        return CheckOutcome(valid=True, status="valid", message="ok")

    monkeypatch.setattr(tools._service, "check_jfrog", _fake_check)

    response = await writer_client.post(
        "/api/v1/tools/credential-checks/jfrog",
        json={"instance": "gold", "username": "svc@att.com", "token": "t"},
    )

    assert response.status_code == 200
    assert response.json()["inventory_updated"] is True
    assert response.json()["target"] == "svc@att.com (Gold)"
    assert seen["instance"] == "gold"
    rows = (await writer_client.get("/api/v1/tools/accounts")).json()
    assert rows[0]["last_check_status"] == "valid"


# ── The directory's name for the account ──────────────────────────────


@pytest.mark.anyio
async def test_a_domain_check_keeps_the_directorys_name_for_the_account(db_session):
    """For a mechID the AD displayName names the person behind it."""
    service = inv.CredentialInventoryService(db_session)
    domain = await service.create(_account(), _writer())
    jfrog = await service.create(_account(account_type="jfrog", directory="bronze", account_name="svc"), _writer())

    async def _check(account_type, directory, name, display):
        await service.record_check(
            account_type=account_type,
            directory=directory,
            account_name=name,
            outcome=CheckOutcome(
                valid=True, status="valid", message="ok", account=CredentialAccountDetails(display_name=display)
            ),
            checked_by="w",
        )

    await _check("domain", "ITSERVICES", "m52142", "m52142 - KAREN RIDGEWAY (kr873u)")
    await _check("jfrog", "bronze", "svc", "pipeline token")  # a token description, not a name

    assert (await service.get(domain.id)).display_name == "m52142 - KAREN RIDGEWAY (kr873u)"
    assert (await service.get(jfrog.id)).display_name is None


@pytest.mark.anyio
async def test_editing_an_account_never_erases_the_directorys_name(db_session):
    service = inv.CredentialInventoryService(db_session)
    created = await service.create(CredentialAccountCreate(**_account().model_dump(), display_name="Karen"), _writer())

    await service.update(created.id, _account(owner="Someone else"), _writer())

    row = await service.get(created.id)
    assert (row.owner, row.display_name) == ("Someone else", "Karen")


@pytest.mark.anyio
async def test_a_check_says_what_it_checked_so_the_page_can_list_it(writer_client, monkeypatch):
    from app.api.v1.endpoints import tools

    async def _fake_check(domain, username, password):
        return CheckOutcome(valid=True, status="valid", message="ok")

    monkeypatch.setattr(tools._service, "check_domain", _fake_check)

    response = await writer_client.post(
        "/api/v1/tools/credential-checks/domain",
        json={"domain": "TESTITSERVICES", "username": "m47355", "password": "p"},
    )

    body = response.json()
    assert (body["directory"], body["account_name"], body["inventory_updated"]) == ("TESTITSERVICES", "m47355", False)


@pytest.mark.anyio
async def test_adding_from_a_check_result_keeps_its_details(writer_client):
    response = await writer_client.post(
        "/api/v1/tools/accounts",
        json={
            **_BODY,
            "expiry_date": "2027-09-30",
            "password_changed_date": "2026-09-30",
            "last_login_date": "2026-10-11",
            "display_name": "m52142 - KAREN RIDGEWAY (kr873u)",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["expiry_date"], body["display_name"]) == ("2027-09-30", "m52142 - KAREN RIDGEWAY (kr873u)")
