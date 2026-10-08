"""Scheduled certificate automation: expiry alerts and auto-renewal.

Driven by the scheduler jobs in ``scheduler_service``:

* **Expiry alerts** — for each enabled rule, find cached certificates inside the
  warning/critical windows and send one consolidated report to the configured
  recipients. One digest per rule, never one email per certificate: these go to
  leadership. A certificate that has already been renewed is left out.
* **Auto-renewal** — for each enabled schedule, find certificates inside the
  renewal window, renew them in PFX mode, escrow the fresh key, import it into
  the schedule's Key Vault targets, and report the outcome by email.

Deliberate safety properties:

* A schedule is **not armed** by default. An un-armed schedule runs on time and
  reports exactly what it *would* renew without issuing anything, so targets and
  recipients can be validated before the CA sees traffic.
* Scheduled runs happen **once per UTC day per config**. Every uvicorn worker on
  every replica runs its own scheduler, so a read-then-act check let all of them
  through at the same minute. The day's slot is taken by inserting against a
  unique key (``cert_automation_claims``), so exactly one process wins.
* A certificate is **renewed once**. Renewal leaves the old certificate in
  Keyfactor, unrevoked and still inside the window; without remembering the
  renewal, every daily run would issue yet another replacement.
* A schedule covering several certificates only replaces a Key Vault entry that
  currently holds the certificate being renewed, so renewals cannot overwrite
  each other in a shared entry.

Private key material and PFX passwords never reach logs, audit rows or email.
"""

from __future__ import annotations

import os
import socket
from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AuditLog, CertificateAutomationClaim
from app.services.certificate_escrow_service import CertificateEscrowService
from app.services.certificate_sync_service import CertificateSyncService
from app.services.email_notification_service import EmailNotificationService
from app.services.keyfactor_service import CertificateService, CertificateServiceError
from app.services.keyvault_service import KeyVaultService

logger = structlog.get_logger(__name__)

ALERT_CONFIG_ACTION = "cert_alert_config"
ALERT_RUN_ACTION = "cert_alert_run"
RENEWAL_CONFIG_ACTION = "cert_auto_renewal_config"
RENEWAL_RUN_ACTION = "cert_auto_renewal_run"
# Audit action written by the portal's own Renew button.
MANUAL_RENEW_ACTION = "renew_certificate"
RENEW_CERTIFICATE_CLAIM = "renew_certificate"

# The day claim alone would let a run at 23:30 UTC be followed by another at
# 00:30; this floor keeps scheduled reports roughly a day apart.
_RUN_DEDUPE_HOURS = 20

# Cap the certificates one scheduled run will renew. A misconfigured schedule
# should not fire hundreds of enrollments at the CA before anyone notices.
_MAX_RENEWALS_PER_RUN = 25

# Certificates last at most 397 days, so an older renewal replaced a certificate
# that has since expired, and expired certificates are never auto-renewed.
_LINEAGE_LOOKBACK_DAYS = 400


def _severity_for(days_until_expiry: int, warning_days: int, critical_days: int) -> str:
    if days_until_expiry <= critical_days:
        return "critical"
    if days_until_expiry <= warning_days:
        return "warning"
    return "info"


def _days_until(not_after: str | None) -> int | None:
    raw = (not_after or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return (parsed - datetime.now(UTC)).days


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _as_int(value: Any) -> int | None:
    """A Keyfactor id, or ``None`` for anything absent or unusable (including 0)."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number or None


def _recipients(config: dict[str, Any]) -> list[str]:
    """Configured addresses without blanks or case-insensitive repeats."""
    seen: set[str] = set()
    recipients: list[str] = []
    for raw in config.get("notification_emails") or []:
        email = raw.strip() if isinstance(raw, str) else ""
        if email and email.lower() not in seen:
            seen.add(email.lower())
            recipients.append(email)
    return recipients


def _identity(cert: dict[str, Any]) -> tuple[str, frozenset[str]]:
    """What a certificate secures: its common name and SAN set, case-insensitive."""
    sans = cert.get("sans") or []
    return (
        (cert.get("common_name") or "").strip().lower(),
        frozenset(str(s).strip().lower() for s in sans if str(s).strip()),
    )


def _follow(lineage: dict[int, int | None], certificate_id: int) -> int:
    """The newest known certificate in a renewal chain."""
    seen = {certificate_id}
    current = certificate_id
    while (successor := lineage.get(current)) and successor not in seen:
        seen.add(successor)
        current = successor
    return current


class CertificateAutomationService:
    """Executes certificate expiry alert rules and auto-renewal schedules."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.sync = CertificateSyncService(db)
        self.email = EmailNotificationService(db)

    # ── Config loading ─────────────────────────────────────────────────

    async def _load_configs(self, action: str) -> list[dict[str, Any]]:
        """Configs are stored as audit rows; return the enabled ones."""
        result = await self.db.execute(
            select(AuditLog).where(AuditLog.action == action).where(AuditLog.resource_type == "certificate_config")
        )
        configs: list[dict[str, Any]] = []
        for entry in result.scalars().all():
            if not isinstance(entry.details, dict):
                continue
            if not entry.details.get("enabled", True):
                continue
            configs.append({"id": entry.id, "created_by": entry.user_email or entry.user_id, **entry.details})
        return configs

    async def _ran_recently(self, action: str, config_id: int) -> bool:
        """True when this config produced a scheduled run record within the dedupe floor."""
        cutoff = datetime.utcnow() - timedelta(hours=_RUN_DEDUPE_HOURS)
        result = await self.db.execute(
            select(AuditLog)
            .where(AuditLog.action == action)
            .where(AuditLog.timestamp >= cutoff)
            .order_by(AuditLog.timestamp.desc())
            .limit(200)
        )
        for entry in result.scalars().all():
            details = entry.details if isinstance(entry.details, dict) else {}
            if details.get("config_id") == config_id and details.get("trigger") == "schedule":
                return True
        return False

    # ── Once-a-day claims ──────────────────────────────────────────────

    async def _claim(self, claim_type: str, subject_id: int) -> str | None:
        """Take today's slot for one unit of work; ``None`` when another process holds it."""
        claim_date = _today()
        self.db.add(
            CertificateAutomationClaim(
                claim_type=claim_type,
                subject_id=subject_id,
                claim_date=claim_date,
                claimed_by=f"{socket.gethostname()}:{os.getpid()}",
            )
        )
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            return None
        return claim_date

    async def _release(self, claim_type: str, subject_id: int, claim_date: str) -> None:
        """Give a slot back after a failure so a later tick or a retry can redo the work."""
        try:
            await self.db.execute(
                delete(CertificateAutomationClaim)
                .where(CertificateAutomationClaim.claim_type == claim_type)
                .where(CertificateAutomationClaim.subject_id == subject_id)
                .where(CertificateAutomationClaim.claim_date == claim_date)
            )
            await self.db.commit()
        except Exception as exc:  # pragma: no cover - worst case the work waits a day
            await self.db.rollback()
            logger.warning("cert_automation_claim_release_failed", claim_type=claim_type, error=str(exc)[:200])

    async def _claim_scheduled_run(self, action: str, config_id: int) -> str | None:
        if await self._ran_recently(action, config_id):
            return None
        return await self._claim(action, config_id)

    async def _record_run(
        self,
        *,
        action: str,
        config: dict[str, Any],
        summary: str,
        details: dict[str, Any],
        outcome: str,
        actor: str,
    ) -> None:
        try:
            self.db.add(
                AuditLog(
                    user_id="scheduler",
                    user_email=actor,
                    action=action,
                    resource_type="certificate_config",
                    resource_id=str(config.get("collection_id") or config.get("id")),
                    details={
                        "page": "CertificatesPage",
                        "feature": "auto_renewal" if action == RENEWAL_RUN_ACTION else "expiry_alerts",
                        "config_id": config.get("id"),
                        # The panels key "last run" off the collection, so a run
                        # record without it never surfaces in the UI.
                        "collection_id": config.get("collection_id"),
                        "collection_name": config.get("collection_name", ""),
                        "summary": summary,
                        **details,
                    },
                    status=outcome,
                )
            )
            await self.db.commit()
        except Exception as exc:  # pragma: no cover - a run must not fail on bookkeeping
            await self.db.rollback()
            logger.warning("cert_automation_run_record_failed", action=action, error=str(exc)[:200])

    # ── Expiry alerts ──────────────────────────────────────────────────

    async def run_expiry_alerts(self, *, trigger: str = "schedule") -> dict[str, Any]:
        """Evaluate every enabled alert rule and send the due reports."""
        configs = await self._load_configs(ALERT_CONFIG_ACTION)
        results = []
        for config in configs:
            claim_date = None
            if trigger == "schedule":
                claim_date = await self._claim_scheduled_run(ALERT_RUN_ACTION, config["id"])
                if claim_date is None:
                    continue
            try:
                results.append(await self.run_alert_config(config, trigger=trigger))
            except Exception as exc:  # noqa: BLE001 - one bad rule must not stop the rest
                logger.error("cert_alert_config_failed", config_id=config.get("id"), error=str(exc)[:300])
                results.append({"config_id": config.get("id"), "status": "failed", "error": str(exc)[:200]})
                if claim_date:
                    await self.db.rollback()
                    await self._release(ALERT_RUN_ACTION, config["id"], claim_date)
        return {"configs_evaluated": len(results), "results": results}

    async def run_alert_config(self, config: dict[str, Any], *, trigger: str = "manual") -> dict[str, Any]:
        """Evaluate one alert rule and email its report.

        The rule is always evaluated inside the admin module's enabled
        collections. The cache holds every collection Keyfactor exposes, so an
        "all collections" rule left unfiltered would report certificates the
        portal does not manage — the report has to match what the Certificates
        page shows.
        """
        warning_days = int(config.get("warning_days") or 60)
        critical_days = int(config.get("critical_days") or 30)
        recipients = _recipients(config)
        collection_id = config.get("collection_id")
        # Empty/None means the admin has not restricted the module (same rule as
        # the collections endpoint), so every cached collection stays in scope.
        enabled_ids = await self.sync.get_enabled_collection_ids()
        restricted = bool(enabled_ids)

        if collection_id is None:
            scope = "All enabled collections" if restricted else "All collections"
        else:
            scope = config.get("collection_name") or f"collection {collection_id}"

        if collection_id is not None and restricted and int(collection_id) not in set(enabled_ids or []):
            # The collection was de-selected in the admin module after this rule
            # was written; reporting on it would leak data the portal no longer
            # manages.
            await self._record_run(
                action=ALERT_RUN_ACTION,
                config=config,
                summary=f"Expiry alert for {scope} skipped: collection is not enabled in the admin module",
                details={"trigger": trigger, "critical": 0, "warning": 0, "emails_sent": 0, "skipped": True},
                # The audit grid renders anything but "success" as a failure, and
                # a deliberate skip is not one; the summary carries the reason.
                outcome="success",
                actor=config.get("created_by") or "scheduler",
            )
            return {
                "config_id": config["id"],
                "status": "collection_not_enabled",
                "critical": 0,
                "warning": 0,
                "emails_sent": 0,
            }

        window = max(warning_days, critical_days)
        due = await self.sync.list_due_certificates(
            collection_id=collection_id,
            days_before_expiry=window,
            collection_ids=enabled_ids,
        )
        # A certificate that has already been renewed is not a risk to report.
        due, renewed_already = await self._without_replaced(
            due, lineage=await self._renewal_lineage(), days_before=window
        )

        rows = []
        # The cache holds one row per collection a certificate belongs to, so
        # an all-collections rule would otherwise list it once per collection.
        seen_ids: set[int] = set()
        for cert in due:
            days = _days_until(cert.get("not_after"))
            if days is None:
                continue
            cert_id = _as_int(cert.get("id"))
            if cert_id is not None:
                if cert_id in seen_ids:
                    continue
                seen_ids.add(cert_id)
            rows.append(
                {
                    "common_name": cert.get("common_name") or f"Certificate {cert.get('id')}",
                    "certificate_id": cert.get("id"),
                    "thumbprint": cert.get("thumbprint") or "",
                    "not_after": cert.get("not_after"),
                    "days_until_expiry": days,
                    "severity": _severity_for(days, warning_days, critical_days),
                    "collection": cert.get("collection") or scope,
                }
            )

        critical = [r for r in rows if r["severity"] == "critical"]
        warning = [r for r in rows if r["severity"] == "warning"]
        excluded = {"renewed_excluded": [s["common_name"] for s in renewed_already[:50]]} if renewed_already else {}
        excluded_note = f", {len(renewed_already)} already renewed left out" if renewed_already else ""

        if not rows:
            await self._record_run(
                action=ALERT_RUN_ACTION,
                config=config,
                summary=f"Expiry alert check for {scope}: no certificates within {warning_days} days{excluded_note}",
                details={"trigger": trigger, "critical": 0, "warning": 0, "emails_sent": 0, **excluded},
                outcome="success",
                actor=config.get("created_by") or "scheduler",
            )
            return {"config_id": config["id"], "status": "no_certificates_due", "critical": 0, "warning": 0}

        delivery: dict[str, Any] = {"success": 0, "recipients": 0}
        if recipients:
            delivery = await self.email.send_certificate_expiry_report(
                recipient_emails=recipients,
                scope_label=scope,
                critical=critical,
                warning=warning,
                warning_days=warning_days,
                critical_days=critical_days,
                config_id=config["id"],
            )

        summary = (
            f"Expiry alert for {scope}: {len(critical)} critical, {len(warning)} warning{excluded_note} "
            f"({delivery.get('success', 0)}/{len(recipients)} emails sent)"
        )
        await self._record_run(
            action=ALERT_RUN_ACTION,
            config=config,
            summary=summary,
            details={
                "trigger": trigger,
                "critical": len(critical),
                "warning": len(warning),
                "emails_sent": delivery.get("success", 0),
                "recipients": recipients,
                "certificates": [r["common_name"] for r in rows[:50]],
                **excluded,
            },
            outcome="success" if recipients else "partial",
            actor=config.get("created_by") or "scheduler",
        )
        return {
            "config_id": config["id"],
            "status": "sent" if recipients else "no_recipients",
            "critical": len(critical),
            "warning": len(warning),
            "emails_sent": delivery.get("success", 0),
        }

    # ── Auto-renewal ───────────────────────────────────────────────────

    async def run_auto_renewals(self, *, trigger: str = "schedule") -> dict[str, Any]:
        """Execute every enabled auto-renewal schedule that is due."""
        configs = await self._load_configs(RENEWAL_CONFIG_ACTION)
        results = []
        for config in configs:
            claim_date = None
            if trigger == "schedule":
                claim_date = await self._claim_scheduled_run(RENEWAL_RUN_ACTION, config["id"])
                if claim_date is None:
                    continue
            try:
                results.append(await self.run_renewal_config(config, trigger=trigger))
            except Exception as exc:  # noqa: BLE001 - isolate one bad schedule
                logger.error(
                    "cert_auto_renewal_config_failed",
                    config_id=config.get("id"),
                    error=str(exc)[:300],
                )
                results.append({"config_id": config.get("id"), "status": "failed", "error": str(exc)[:200]})
                if claim_date:
                    await self.db.rollback()
                    await self._release(RENEWAL_RUN_ACTION, config["id"], claim_date)
        return {"schedules_run": len(results), "results": results}

    async def run_renewal_config(
        self,
        config: dict[str, Any],
        *,
        trigger: str = "manual",
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Renew the certificates a schedule covers, then load them to AKV.

        An un-armed schedule reports what it would do and issues nothing.
        """
        armed = bool(config.get("armed", False))
        days_before = int(config.get("days_before_expiry") or 60)
        recipients = _recipients(config) if config.get("notify_on_renewal", True) else []
        targets = [t for t in (config.get("akv_targets") or []) if isinstance(t, dict)]
        collection_id = config.get("collection_id")
        scope = config.get("collection_name") or f"collection {collection_id}"
        configured_ids = [
            cert_id
            for c in (config.get("certificates") or [])
            if isinstance(c, dict) and (cert_id := _as_int(c.get("id")))
        ]

        lineage = await self._renewal_lineage()
        # The schedule stores the certificate it was saved with; following the
        # renewal chain keeps it covering that certificate's replacements.
        cert_ids = sorted({_follow(lineage, cert_id) for cert_id in configured_ids})

        due = await self.sync.list_due_certificates(
            collection_id=collection_id,
            days_before_expiry=days_before,
            certificate_ids=cert_ids or None,
            # Unattended issuance is for certificates still in service. An
            # expired one may have been abandoned, and long-expired certificates
            # sort first, so they would otherwise use up the per-run cap.
            include_expired=False,
        )
        eligible, skipped = await self._without_replaced(due, lineage=lineage, days_before=days_before)
        capped = eligible[:_MAX_RENEWALS_PER_RUN]
        # One named certificate owns its targets outright. With several, an
        # entry is only replaced if it holds the certificate being renewed.
        match_targets = len(configured_ids) != 1

        renewed: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        if armed:
            for cert in capped:
                outcome = await self._renew_one(
                    cert, config=config, targets=targets, actor=actor, match_targets=match_targets
                )
                if outcome.get("skipped"):
                    skipped.append(outcome)
                else:
                    (renewed if outcome.get("renewed") else failed).append(outcome)

        planned = [
            {
                "common_name": c.get("common_name") or f"Certificate {c.get('id')}",
                "certificate_id": c.get("id"),
                "thumbprint": c.get("thumbprint") or "",
                "collection": c.get("collection") or scope,
                "not_after": c.get("not_after"),
                "days_until_expiry": _days_until(c.get("not_after")),
            }
            for c in capped
        ]

        # "Run now" on a dry run always mails, which is how recipients get
        # validated. Otherwise only send when there is something to report.
        has_news = bool(renewed or failed) if armed else bool(capped)
        delivery: dict[str, Any] = {"success": 0}
        if recipients and (has_news or (trigger != "schedule" and not armed)):
            delivery = await self.email.send_certificate_renewal_report(
                recipient_emails=recipients,
                scope_label=scope,
                armed=armed,
                planned=planned,
                renewed=renewed,
                failed=failed,
                days_before_expiry=days_before,
                truncated=len(eligible) - len(capped),
                config_id=config["id"],
            )

        mode = "renewed" if armed else "would renew"
        summary = (
            f"Auto-renewal {'run' if armed else 'dry run'} for {scope}: "
            f"{len(renewed) if armed else len(capped)} {mode}, {len(failed)} failed"
            + (f", {len(skipped)} already renewed" if skipped else "")
            + f" ({delivery.get('success', 0)}/{len(recipients)} emails sent)"
        )
        await self._record_run(
            action=RENEWAL_RUN_ACTION,
            config=config,
            summary=summary,
            details={
                "trigger": trigger,
                "armed": armed,
                "certificates_due": len(due),
                "certificates_processed": len(capped),
                "renewed": [r["common_name"] for r in renewed],
                # Read back by _renewal_lineage: this is what stops the old
                # certificate being renewed again on the next run.
                "renewals": [
                    {
                        "certificate_id": r["certificate_id"],
                        "new_certificate_id": r.get("new_certificate_id"),
                        "thumbprint": r.get("thumbprint") or "",
                    }
                    for r in renewed
                ],
                "failed": [{"common_name": f["common_name"], "error": f.get("error", "")} for f in failed],
                "skipped": [{"common_name": s["common_name"], "reason": s.get("reason", "")} for s in skipped],
                "emails_sent": delivery.get("success", 0),
                "akv_targets": [t.get("vault_name") for t in targets],
            },
            outcome="partial" if failed else "success",
            actor=actor or config.get("created_by") or "scheduler",
        )
        return {
            "config_id": config["id"],
            "collection_id": collection_id,
            "armed": armed,
            "certificates_due": len(due),
            "renewed": len(renewed),
            "failed": len(failed),
            "skipped": len(skipped),
            "emails_sent": delivery.get("success", 0),
        }

    async def _renewal_lineage(self) -> dict[int, int | None]:
        """Keyfactor id of each certificate the portal renewed → its replacement (``None`` if unknown).

        Built from auto-renewal run records and the Renew button's audit rows,
        oldest first so a later renewal of the same certificate wins.
        """
        since = datetime.utcnow() - timedelta(days=_LINEAGE_LOOKBACK_DAYS)
        result = await self.db.execute(
            select(AuditLog)
            .where(AuditLog.action.in_((RENEWAL_RUN_ACTION, MANUAL_RENEW_ACTION)))
            .where(AuditLog.timestamp >= since)
            .order_by(AuditLog.timestamp.asc())
        )
        lineage: dict[int, int | None] = {}

        def note(old: int | None, new: int | None) -> None:
            if old is None:
                return
            if new == old:
                new = None
            if new is not None or old not in lineage:
                lineage[old] = new

        for entry in result.scalars().all():
            details = entry.details if isinstance(entry.details, dict) else {}
            if entry.action == MANUAL_RENEW_ACTION:
                if entry.status != "failed":
                    note(_as_int(entry.resource_id), _as_int(details.get("new_certificate_id")))
                continue
            for renewal in details.get("renewals") or []:
                if isinstance(renewal, dict):
                    note(_as_int(renewal.get("certificate_id")), _as_int(renewal.get("new_certificate_id")))
        return lineage

    async def _without_replaced(
        self,
        due: list[dict[str, Any]],
        *,
        lineage: dict[int, int | None],
        days_before: int,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """Split due certificates into those still needing action and those already replaced.

        Two signals mark a certificate as replaced: a renewal the portal
        recorded (unless its replacement has since been revoked or deleted), or
        — for renewals done directly in Keyfactor — an active certificate for
        the same names that expires beyond the renewal window.
        """
        if not due:
            return [], []
        successors = {s for c in due if (s := lineage.get(c.get("id")))}
        names = {name for c in due if (name := _identity(c)[0])}
        rows = await self.sync.find_certificates(certificate_ids=successors, common_names=names)
        active = [r for r in rows if not r.get("revoked") and not r.get("deleted_at")]
        active_ids = {r["id"] for r in active}
        withdrawn = {r["id"] for r in rows} - active_ids

        eligible: list[dict[str, Any]] = []
        skipped: list[dict[str, Any]] = []
        for cert in due:
            cert_id = cert.get("id")
            reason = None
            if cert_id in lineage:
                successor = lineage[cert_id]
                if successor is None:
                    reason = "already renewed through the portal"
                elif successor not in withdrawn:
                    reason = f"already renewed through the portal (replacement certificate {successor})"
            if reason is None:
                identity = _identity(cert)
                for other in active:
                    if other["id"] == cert_id or _identity(other) != identity:
                        continue
                    remaining = _days_until(other.get("not_after"))
                    if remaining is not None and remaining > days_before:
                        reason = (
                            f"replacement certificate {other['id']} already issued "
                            f"(expires {str(other.get('not_after') or '')[:10]})"
                        )
                        break
            if reason:
                skipped.append(
                    {
                        "common_name": cert.get("common_name") or f"Certificate {cert_id}",
                        "certificate_id": cert_id,
                        "reason": reason,
                    }
                )
            else:
                eligible.append(cert)
        return eligible, skipped

    async def _renew_one(
        self,
        cert: dict[str, Any],
        *,
        config: dict[str, Any],
        targets: list[dict[str, Any]],
        actor: str | None,
        match_targets: bool,
    ) -> dict[str, Any]:
        """Renew one certificate, escrow the key, and load it to each target."""
        import secrets

        common_name = cert.get("common_name") or f"Certificate {cert.get('id')}"
        certificate_id = int(cert.get("id") or 0)
        record: dict[str, Any] = {
            "common_name": common_name,
            "certificate_id": certificate_id,
            "renewed": False,
            "akv": [],
        }

        # A manual "Run now", or a second schedule naming the same certificate,
        # may be renewing it at this moment.
        claim_date = await self._claim(RENEW_CERTIFICATE_CLAIM, certificate_id)
        if claim_date is None:
            return {
                "common_name": common_name,
                "certificate_id": certificate_id,
                "skipped": True,
                "reason": "already renewed or being renewed by another run today",
            }

        # Single-use: protects the PFX in transit and becomes the escrowed
        # password. Never logged, never emailed.
        pfx_password = secrets.token_urlsafe(24)
        try:
            result = await CertificateService().renew_certificate(
                certificate_id=certificate_id,
                mode="pfx",
                certificate_authority=cert.get("certificate_authority") or None,
                template=cert.get("template") or None,
                collection_id=config.get("collection_id"),
                password=pfx_password,
                key_type="RSA",
                key_length=cert.get("key_size") if cert.get("key_size") in (2048, 3072, 4096, 8192) else 4096,
            )
        except CertificateServiceError as exc:
            record["error"] = exc.message[:200]
            await self._release(RENEW_CERTIFICATE_CLAIM, certificate_id, claim_date)
            return record
        except Exception as exc:  # noqa: BLE001 - report, never abort the schedule
            record["error"] = str(exc)[:200]
            await self._release(RENEW_CERTIFICATE_CLAIM, certificate_id, claim_date)
            return record

        record["renewed"] = True
        record["thumbprint"] = result.get("thumbprint") or ""
        new_certificate_id = _as_int(result.get("certificate_id"))
        record["new_certificate_id"] = new_certificate_id if new_certificate_id != certificate_id else None

        pfx_base64 = result.get("pfx_base64")
        if pfx_base64:
            escrow_id = record["new_certificate_id"] or certificate_id
            try:
                await CertificateEscrowService(self.db).escrow(
                    certificate_id=escrow_id,
                    thumbprint=str(result.get("thumbprint") or ""),
                    common_name=common_name,
                    pfx_base64=str(pfx_base64),
                    password=pfx_password,
                    source="auto_renewal",
                    actor=actor or "scheduler",
                )
                record["escrowed"] = True
            except Exception as exc:  # noqa: BLE001 - renewal already succeeded
                logger.warning("cert_auto_renewal_escrow_failed", certificate_id=escrow_id, error=str(exc)[:200])
                record["escrowed"] = False

        if targets:
            record["akv"] = await self._load_to_targets(
                pfx_base64=pfx_base64,
                password=pfx_password,
                targets=targets,
                replaces_thumbprint=cert.get("thumbprint") or "",
                match_existing=match_targets,
            )
        return record

    async def _load_to_targets(
        self,
        *,
        pfx_base64: str | None,
        password: str,
        targets: list[dict[str, Any]],
        replaces_thumbprint: str,
        match_existing: bool,
    ) -> list[dict[str, Any]]:
        """Import the freshly issued PFX into the schedule's vault entries.

        With ``match_existing`` an entry is only replaced when it currently
        holds the certificate being renewed.
        """
        import base64

        if not pfx_base64:
            return [
                {
                    "vault_name": t.get("vault_name", ""),
                    "certificate_name": name,
                    "status": "skipped",
                    "error": "renewal returned no PFX",
                }
                for t in targets
                for name in (t.get("certificate_names") or [])
            ]

        try:
            cert_bytes = base64.b64decode(pfx_base64)
        except Exception:
            return [
                {
                    "vault_name": t.get("vault_name", ""),
                    "certificate_name": name,
                    "status": "failed",
                    "error": "PFX material was not decodable",
                }
                for t in targets
                for name in (t.get("certificate_names") or [])
            ]

        kv = KeyVaultService()
        results: list[dict[str, Any]] = []
        for target in targets:
            vault_name = (target.get("vault_name") or "").strip()
            if not vault_name:
                continue
            vault_url = f"https://{vault_name}.vault.azure.net"
            for name in target.get("certificate_names") or []:
                entry = {"vault_name": vault_name, "certificate_name": name}
                if match_existing:
                    mismatch = await self._entry_mismatch(kv, f"{vault_url}/", name, replaces_thumbprint)
                    if mismatch:
                        entry["status"] = "skipped"
                        entry["error"] = mismatch
                        results.append(entry)
                        continue
                try:
                    await kv.import_certificate(vault_url, name, cert_bytes, password=password)
                    entry["status"] = "imported"
                except Exception as exc:  # noqa: BLE001 - report per entry
                    entry["status"] = "failed"
                    entry["error"] = str(exc)[:200]
                    logger.warning(
                        "cert_auto_renewal_akv_import_failed",
                        vault=vault_name,
                        certificate_name=name,
                        error=str(exc)[:200],
                    )
                results.append(entry)
        return results

    @staticmethod
    async def _entry_mismatch(kv: KeyVaultService, vault_url: str, name: str, thumbprint: str) -> str | None:
        """Why an entry must not take this renewal, or ``None`` if it holds the certificate being replaced."""
        try:
            held = (await kv.get_certificate(vault_url, name)).get("thumbprint") or ""
        except Exception as exc:  # noqa: BLE001 - reported per entry
            return f"could not confirm the entry holds this certificate: {str(exc)[:150]}"
        if not thumbprint or held.strip().upper() != thumbprint.strip().upper():
            return (
                "entry holds a different certificate; a schedule covering several certificates "
                "only replaces the entry holding the one renewed"
            )
        return None
