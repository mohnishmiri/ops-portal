"""Tests for the certificate report tables rendered into email.

The rows recipients act on are identified by thumbprint and collection — the
internal Keyfactor certificate id is meaningless in the portal's search and in
Keyfactor Command, so it is not what the report carries.
"""

from app.services.email_notification_service import (
    CERT_REPORT_SECTION,
    EmailNotificationService,
)

ROW = {
    "common_name": "hznrep-cd.dev.att.com",
    "certificate_id": 24319915,
    "thumbprint": "3E49931A64AE04D987533E0DD1C237BDA701DA2C",
    "collection": "AP-KF-HZNREP18296",
    "not_after": "2026-10-15T18:54:00+0000",
    "days_until_expiry": 32,
}


def _render(rows: list[dict]) -> str:
    return CERT_REPORT_SECTION.format(
        title="Warning",
        accent="#b54708",
        count=len(rows),
        rows=EmailNotificationService._cert_rows_html(rows, accent="#b54708"),
    )


def test_report_row_carries_thumbprint_and_collection() -> None:
    html = _render([ROW])

    assert "<th>Thumbprint</th>" in html
    assert "<th>Collection</th>" in html
    assert "3E49931A64AE04D987533E0DD1C237BDA701DA2C" in html
    assert "AP-KF-HZNREP18296" in html
    assert "hznrep-cd.dev.att.com" in html
    assert "2026-10-15" in html
    assert "32 d" in html


def test_report_row_no_longer_exposes_the_internal_certificate_id() -> None:
    html = _render([ROW])

    assert "<th>ID</th>" not in html
    assert "24319915" not in html


def test_report_row_falls_back_when_thumbprint_or_collection_is_missing() -> None:
    html = _render([{**ROW, "thumbprint": "", "collection": None}])

    # A dash, never an empty cell or the word "None".
    assert html.count("&mdash;") == 0
    assert "None" not in html
    assert html.count("—") == 2


def test_expired_certificate_reads_as_expired() -> None:
    html = _render([{**ROW, "days_until_expiry": -1}])

    assert "Expired 1 d ago" in html


def test_report_row_escapes_html_in_certificate_fields() -> None:
    html = _render([{**ROW, "common_name": "<script>x</script>", "collection": "A&B"}])

    assert "<script>" not in html
    assert "&lt;script&gt;x&lt;/script&gt;" in html
    assert "A&amp;B" in html
