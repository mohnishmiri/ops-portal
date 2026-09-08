"""Tests for scheduled certificate expiry alerts and auto-renewal.

Both features previously stored configuration and executed nothing, so these
cover the behaviour end to end: which certificates are selected, what the email
reports, what reaches Keyfactor and Key Vault, and — most importantly — that an
un-armed schedule issues nothing.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select, text

from app.models.database import AuditLog
from app.services.certificate_automation_service import (
    ALERT_CONFIG_ACTION,
    ALERT_RUN_ACTION,
    RENEWAL_CONFIG_ACTION,
    RENEWAL_RUN_ACTION,
    CertificateAutomationService,
)
from app.services.keyfactor_service import CertificateServiceError


class FakeEmail:
    """Captures the reports instead of sending them."""

    def __init__(self) -> None:
        self.expiry_reports: list[dict] = []
        self.renewal_reports: list[dict] = []

    async def send_certificate_expiry_report(self, **kwargs):
        self.expiry_reports.append(kwargs)
        return {"recipients": len(kwargs["recipient_emails"]), "success": len(kwargs["recipient_emails"])}

    async def send_certificate_renewal_report(self, **kwargs):
        self.renewal_reports.append(kwargs)
        return {"recipients": len(kwargs["recipient_emails"]), "success": len(kwargs["recipient_emails"])}


class FakeKeyfactor:
    """Renewal stub: records calls and can fail for chosen certificates."""

    def __init__(self, fail_ids: set[int] | None = None) -> None:
        self.calls: list[dict] = []
        self.fail_ids = fail_ids or set()

    async def renew_certificate(self, **kwargs):
        self.calls.append(kwargs)
        cert_id = kwargs["certificate_id"]
        if cert_id in self.fail_ids:
            raise CertificateServiceError("Pending renewal workflow.", status_code=400)
        return {
            "thumbprint": f"NEW{cert_id}",
            "certificate_id": cert_id + 1000,
            "pfx_base64": "UEZYREFUQQ==",
        }


class FakeVault:
    """Key Vault import stub."""

    def __init__(self, fail_names: set[str] | None = None) -> None:
        self.imports: list[dict] = []
        self.fail_names = fail_names or set()

    async def import_certificate(self, vault_uri, name, cert_bytes, *, password=None, **kwargs):
        if name in self.fail_names:
            raise RuntimeError(f"forbidden: {name}")
        self.imports.append({"vault_uri": vault_uri, "name": name, "cert_bytes": cert_bytes, "password": password})
        return {"id": f"{vault_uri}/certificates/{name}"}


@pytest.fixture
def automation(db_session):
    """Service with email delivery replaced by a capture."""
    service = CertificateAutomationService(db_session)
    service.email = FakeEmail()
    return service


async def _cache_cert(db_session, *, cert_id: int, cn: str, days_out: int, collection_id: int = 2573):
    expiry = (datetime.now(UTC) + timedelta(days=days_out)).strftime("%Y-%m-%dT%H:%M:%S%z")
    await db_session.execute(
        text(
            "INSERT INTO cert_certificates "
            "(collection_id, certificate_id, common_name, not_after, revoked, thumbprint, key_size) "
            "VALUES (:col, :cid, :cn, :na, 0, :tp, 4096)"
        ),
        {"col": collection_id, "cid": cert_id, "cn": cn, "na": expiry, "tp": f"TP{cert_id}"},
    )
    await db_session.commit()


async def _add_config(db_session, action: str, details: dict) -> int:
    entry = AuditLog(
        user_id="admin",
        user_email="admin@example.com",
        action=action,
        resource_type="certificate_config",
        resource_id="2573",
        details=details,
        status="success",
    )
    db_session.add(entry)
    await db_session.commit()
    await db_session.refresh(entry)
    return entry.id


async def _runs(db_session, action: str) -> list[AuditLog]:
    result = await db_session.execute(select(AuditLog).where(AuditLog.action == action))
    return list(result.scalars().all())


# ── Expiry alerts ──────────────────────────────────────────────────────


async def test_alert_reports_certificates_split_by_severity(db_session, automation):
    await _cache_cert(db_session, cert_id=1, cn="critical.att.com", days_out=10)
    await _cache_cert(db_session, cert_id=2, cn="warning.att.com", days_out=45)
    await _cache_cert(db_session, cert_id=3, cn="safe.att.com", days_out=200)
    await _add_config(
        db_session,
        ALERT_CONFIG_ACTION,
        {
            "collection_id": 2573,
            "collection_name": "AP-KF-ATTCC-31599",
            "enabled": True,
            "warning_days": 60,
            "critical_days": 30,
            "notification_emails": ["leadership@att.com"],
        },
    )

    result = await automation.run_expiry_alerts(trigger="manual")

    assert result["configs_evaluated"] == 1
    report = automation.email.expiry_reports[0]
    assert [c["common_name"] for c in report["critical"]] == ["critical.att.com"]
    assert [w["common_name"] for w in report["warning"]] == ["warning.att.com"]
    # Outside both windows, so it must not appear at all.
    assert "safe.att.com" not in str(report)
    assert report["recipient_emails"] == ["leadership@att.com"]
    assert report["scope_label"] == "AP-KF-ATTCC-31599"


async def test_alert_includes_already_expired_certificates(db_session, automation):
    # An expired certificate is the most urgent thing a report can carry.
    await _cache_cert(db_session, cert_id=1, cn="expired.att.com", days_out=-5)
    await _add_config(
        db_session,
        ALERT_CONFIG_ACTION,
        {
            "collection_id": 2573,
            "enabled": True,
            "warning_days": 60,
            "critical_days": 30,
            "notification_emails": ["leadership@att.com"],
        },
    )

    await automation.run_expiry_alerts(trigger="manual")

    critical = automation.email.expiry_reports[0]["critical"]
    assert critical[0]["common_name"] == "expired.att.com"
    assert critical[0]["days_until_expiry"] < 0


async def test_alert_sends_nothing_when_no_certificate_is_due(db_session, automation):
    await _cache_cert(db_session, cert_id=1, cn="safe.att.com", days_out=300)
    await _add_config(
        db_session,
        ALERT_CONFIG_ACTION,
        {
            "collection_id": 2573,
            "enabled": True,
            "warning_days": 60,
            "critical_days": 30,
            "notification_emails": ["leadership@att.com"],
        },
    )

    result = await automation.run_expiry_alerts(trigger="manual")

    assert result["results"][0]["status"] == "no_certificates_due"
    assert automation.email.expiry_reports == []
    # The check itself is still recorded, so silence is provably not a failure.
    assert len(await _runs(db_session, ALERT_RUN_ACTION)) == 1


async def test_disabled_alert_rule_is_skipped(db_session, automation):
    await _cache_cert(db_session, cert_id=1, cn="critical.att.com", days_out=5)
    await _add_config(
        db_session,
        ALERT_CONFIG_ACTION,
        {
            "collection_id": 2573,
            "enabled": False,
            "warning_days": 60,
            "critical_days": 30,
            "notification_emails": ["leadership@att.com"],
        },
    )

    result = await automation.run_expiry_alerts(trigger="manual")

    assert result["configs_evaluated"] == 0
    assert automation.email.expiry_reports == []


async def test_scheduled_alert_runs_once_per_day(db_session, automation):
    # The job ticks hourly so a restart cannot skip a day; dedupe stops repeats.
    await _cache_cert(db_session, cert_id=1, cn="critical.att.com", days_out=5)
    await _add_config(
        db_session,
        ALERT_CONFIG_ACTION,
        {
            "collection_id": 2573,
            "enabled": True,
            "warning_days": 60,
            "critical_days": 30,
            "notification_emails": ["leadership@att.com"],
        },
    )

    first = await automation.run_expiry_alerts(trigger="schedule")
    second = await automation.run_expiry_alerts(trigger="schedule")

    assert first["configs_evaluated"] == 1
    assert second["configs_evaluated"] == 0
    assert len(automation.email.expiry_reports) == 1

    # A human asking for it now is never deduped.
    await automation.run_expiry_alerts(trigger="manual")
    assert len(automation.email.expiry_reports) == 2


async def test_alert_rule_without_recipients_still_records_the_run(db_session, automation):
    await _cache_cert(db_session, cert_id=1, cn="critical.att.com", days_out=5)
    await _add_config(
        db_session,
        ALERT_CONFIG_ACTION,
        {"collection_id": 2573, "enabled": True, "warning_days": 60, "critical_days": 30, "notification_emails": []},
    )

    result = await automation.run_expiry_alerts(trigger="manual")

    assert result["results"][0]["status"] == "no_recipients"
    assert automation.email.expiry_reports == []
    assert len(await _runs(db_session, ALERT_RUN_ACTION)) == 1


async def test_alert_scoped_to_all_collections(db_session, automation):
    await _cache_cert(db_session, cert_id=1, cn="a.att.com", days_out=5, collection_id=1)
    await _cache_cert(db_session, cert_id=2, cn="b.att.com", days_out=5, collection_id=2)
    await _add_config(
        db_session,
        ALERT_CONFIG_ACTION,
        {
            "collection_id": None,
            "enabled": True,
            "warning_days": 60,
            "critical_days": 30,
            "notification_emails": ["leadership@att.com"],
        },
    )

    await automation.run_expiry_alerts(trigger="manual")

    names = {c["common_name"] for c in automation.email.expiry_reports[0]["critical"]}
    assert names == {"a.att.com", "b.att.com"}


# ── Auto-renewal ───────────────────────────────────────────────────────


_TARGETS = [
    {
        "subscription_id": "sub-1",
        "resource_group": "rg-1",
        "vault_name": "attcc-eastus2-perf-kv",
        "certificate_names": ["cesdataroutergearsperf-test-att-com"],
    }
]


async def _renewal_config(db_session, **overrides) -> int:
    details = {
        "collection_id": 2573,
        "collection_name": "AP-KF-ATTCC-31599",
        "enabled": True,
        "armed": False,
        "days_before_expiry": 60,
        "notification_emails": ["leadership@att.com"],
        "certificates": [],
        "akv_targets": _TARGETS,
    }
    details.update(overrides)
    return await _add_config(db_session, RENEWAL_CONFIG_ACTION, details)


async def test_unarmed_schedule_issues_nothing(db_session, automation, monkeypatch):
    # The whole point of the arm toggle: a dry run must not contact the CA.
    keyfactor = FakeKeyfactor()
    monkeypatch.setattr("app.services.certificate_automation_service.CertificateService", lambda: keyfactor)
    await _cache_cert(db_session, cert_id=1, cn="due.att.com", days_out=20)
    await _renewal_config(db_session, armed=False)

    result = await automation.run_auto_renewals(trigger="manual")

    assert keyfactor.calls == []
    assert result["results"][0]["renewed"] == 0
    assert result["results"][0]["certificates_due"] == 1
    report = automation.email.renewal_reports[0]
    assert report["armed"] is False
    assert [p["common_name"] for p in report["planned"]] == ["due.att.com"]
    assert report["renewed"] == []


async def test_armed_schedule_renews_escrows_and_loads_to_akv(db_session, automation, monkeypatch):
    keyfactor = FakeKeyfactor()
    vault = FakeVault()
    monkeypatch.setattr("app.services.certificate_automation_service.CertificateService", lambda: keyfactor)
    monkeypatch.setattr("app.services.certificate_automation_service.KeyVaultService", lambda: vault)
    await _cache_cert(db_session, cert_id=1, cn="due.att.com", days_out=20)
    await _renewal_config(db_session, armed=True)

    result = await automation.run_auto_renewals(trigger="manual")

    # Renewed in PFX mode — the only mode that yields a key to escrow and load.
    assert len(keyfactor.calls) == 1
    assert keyfactor.calls[0]["mode"] == "pfx"
    assert keyfactor.calls[0]["certificate_id"] == 1
    assert keyfactor.calls[0]["password"]

    # Imported into the schedule's explicit target, under the renewal's own
    # password — no human supplies one.
    assert len(vault.imports) == 1
    assert vault.imports[0]["name"] == "cesdataroutergearsperf-test-att-com"
    assert vault.imports[0]["password"] == keyfactor.calls[0]["password"]
    assert "attcc-eastus2-perf-kv" in vault.imports[0]["vault_uri"]

    assert result["results"][0]["renewed"] == 1
    report = automation.email.renewal_reports[0]
    assert report["armed"] is True
    assert report["renewed"][0]["common_name"] == "due.att.com"
    assert report["renewed"][0]["akv"][0]["status"] == "imported"


async def test_a_failed_renewal_does_not_stop_the_others(db_session, automation, monkeypatch):
    keyfactor = FakeKeyfactor(fail_ids={1})
    monkeypatch.setattr("app.services.certificate_automation_service.CertificateService", lambda: keyfactor)
    monkeypatch.setattr("app.services.certificate_automation_service.KeyVaultService", lambda: FakeVault())
    await _cache_cert(db_session, cert_id=1, cn="broken.att.com", days_out=10)
    await _cache_cert(db_session, cert_id=2, cn="fine.att.com", days_out=20)
    await _renewal_config(db_session, armed=True)

    result = await automation.run_auto_renewals(trigger="manual")

    assert result["results"][0]["renewed"] == 1
    assert result["results"][0]["failed"] == 1
    report = automation.email.renewal_reports[0]
    assert [f["common_name"] for f in report["failed"]] == ["broken.att.com"]
    assert "Pending renewal workflow" in report["failed"][0]["error"]
    assert [r["common_name"] for r in report["renewed"]] == ["fine.att.com"]


async def test_akv_import_failure_is_reported_per_entry(db_session, automation, monkeypatch):
    # The certificate was still renewed; only the import failed, and the report
    # has to make that distinction or someone will re-run a renewal needlessly.
    keyfactor = FakeKeyfactor()
    vault = FakeVault(fail_names={"cesdataroutergearsperf-test-att-com"})
    monkeypatch.setattr("app.services.certificate_automation_service.CertificateService", lambda: keyfactor)
    monkeypatch.setattr("app.services.certificate_automation_service.KeyVaultService", lambda: vault)
    await _cache_cert(db_session, cert_id=1, cn="due.att.com", days_out=20)
    await _renewal_config(db_session, armed=True)

    result = await automation.run_auto_renewals(trigger="manual")

    assert result["results"][0]["renewed"] == 1
    akv = automation.email.renewal_reports[0]["renewed"][0]["akv"]
    assert akv[0]["status"] == "failed"
    assert "forbidden" in akv[0]["error"]


async def test_schedule_scoped_to_specific_certificates(db_session, automation, monkeypatch):
    keyfactor = FakeKeyfactor()
    monkeypatch.setattr("app.services.certificate_automation_service.CertificateService", lambda: keyfactor)
    monkeypatch.setattr("app.services.certificate_automation_service.KeyVaultService", lambda: FakeVault())
    await _cache_cert(db_session, cert_id=1, cn="picked.att.com", days_out=10)
    await _cache_cert(db_session, cert_id=2, cn="ignored.att.com", days_out=10)
    await _renewal_config(db_session, armed=True, certificates=[{"id": 1, "common_name": "picked.att.com"}])

    await automation.run_auto_renewals(trigger="manual")

    assert [c["certificate_id"] for c in keyfactor.calls] == [1]


async def test_renewal_run_is_capped_per_execution(db_session, automation, monkeypatch):
    # A misconfigured schedule must not fire hundreds of enrollments at the CA.
    keyfactor = FakeKeyfactor()
    monkeypatch.setattr("app.services.certificate_automation_service.CertificateService", lambda: keyfactor)
    monkeypatch.setattr("app.services.certificate_automation_service.KeyVaultService", lambda: FakeVault())
    for i in range(1, 31):
        await _cache_cert(db_session, cert_id=i, cn=f"cert{i}.att.com", days_out=10)
    await _renewal_config(db_session, armed=True)

    await automation.run_auto_renewals(trigger="manual")

    assert len(keyfactor.calls) == 25
    # The overflow is stated in the report rather than silently dropped.
    assert automation.email.renewal_reports[0]["truncated"] == 5


async def test_renewal_records_an_audit_run(db_session, automation, monkeypatch):
    keyfactor = FakeKeyfactor()
    monkeypatch.setattr("app.services.certificate_automation_service.CertificateService", lambda: keyfactor)
    monkeypatch.setattr("app.services.certificate_automation_service.KeyVaultService", lambda: FakeVault())
    await _cache_cert(db_session, cert_id=1, cn="due.att.com", days_out=20)
    await _renewal_config(db_session, armed=True)

    await automation.run_auto_renewals(trigger="manual")

    runs = await _runs(db_session, RENEWAL_RUN_ACTION)
    assert len(runs) == 1
    details = runs[0].details
    assert details["armed"] is True
    assert details["renewed"] == ["due.att.com"]
    assert details["akv_targets"] == ["attcc-eastus2-perf-kv"]
    assert "1 renewed" in details["summary"]
    # Key material must never reach the audit trail.
    assert "pfx" not in str(details).lower()


async def test_disabled_schedule_is_skipped(db_session, automation, monkeypatch):
    keyfactor = FakeKeyfactor()
    monkeypatch.setattr("app.services.certificate_automation_service.CertificateService", lambda: keyfactor)
    await _cache_cert(db_session, cert_id=1, cn="due.att.com", days_out=10)
    await _renewal_config(db_session, armed=True, enabled=False)

    result = await automation.run_auto_renewals(trigger="manual")

    assert result["schedules_run"] == 0
    assert keyfactor.calls == []


async def test_scheduled_renewal_runs_once_per_day(db_session, automation, monkeypatch):
    keyfactor = FakeKeyfactor()
    monkeypatch.setattr("app.services.certificate_automation_service.CertificateService", lambda: keyfactor)
    monkeypatch.setattr("app.services.certificate_automation_service.KeyVaultService", lambda: FakeVault())
    await _cache_cert(db_session, cert_id=1, cn="due.att.com", days_out=20)
    await _renewal_config(db_session, armed=True)

    await automation.run_auto_renewals(trigger="schedule")
    await automation.run_auto_renewals(trigger="schedule")

    assert len(keyfactor.calls) == 1
