"""Scheduled certificate automation: expiry alerts and auto-renewal.

Both features previously stored configuration and did nothing with it. This
module is what actually executes them, driven by the scheduler jobs in
``scheduler_service``:

* **Expiry alerts** — for each enabled rule, find cached certificates inside the
  warning/critical windows and send one consolidated report to the configured
  recipients. One digest per rule, never one email per certificate: these go to
  leadership.
* **Auto-renewal** — for each enabled schedule, find certificates inside the
  renewal window, renew them in PFX mode, escrow the fresh key, import it into
  the schedule's Key Vault targets, and report the outcome by email.

Two safety properties are deliberate:

* A schedule is **not armed** by default. An un-armed schedule runs on time and
  reports exactly what it *would* renew without issuing anything, so targets and
  recipients can be validated before the CA sees traffic.
* Runs are **idempotent per day**. The jobs tick hourly so a restart cannot skip
  a day, and a per-config run record stops the same schedule firing twice.

Private key material and PFX passwords never reach logs, audit rows or email.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.database import AuditLog
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

# The jobs tick hourly so a restart cannot lose a day; this window stops the
# same config running twice within one day.
_RUN_DEDUPE_HOURS = 20

# Cap the certificates one scheduled run will renew. A misconfigured schedule
# should not fire hundreds of enrollments at the CA before anyone notices.
_MAX_RENEWALS_PER_RUN = 25


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
        """True when this config already produced a run record today."""
        cutoff = datetime.utcnow() - timedelta(hours=_RUN_DEDUPE_HOURS)
        result = await self.db.execute(
            select(AuditLog)
            .where(AuditLog.action == action)
            .where(AuditLog.timestamp >= cutoff)
            .order_by(AuditLog.timestamp.desc())
            .limit(50)
        )
        for entry in result.scalars().all():
            details = entry.details if isinstance(entry.details, dict) else {}
            if details.get("config_id") == config_id and details.get("trigger") == "schedule":
                return True
        return False

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
            if trigger == "schedule" and await self._ran_recently(ALERT_RUN_ACTION, config["id"]):
                continue
            try:
                results.append(await self.run_alert_config(config, trigger=trigger))
            except Exception as exc:  # noqa: BLE001 - one bad rule must not stop the rest
                logger.error("cert_alert_config_failed", config_id=config.get("id"), error=str(exc)[:300])
                results.append({"config_id": config.get("id"), "status": "failed", "error": str(exc)[:200]})
        return {"configs_evaluated": len(results), "results": results}

    async def run_alert_config(self, config: dict[str, Any], *, trigger: str = "manual") -> dict[str, Any]:
        """Evaluate one alert rule and email its report."""
        warning_days = int(config.get("warning_days") or 60)
        critical_days = int(config.get("critical_days") or 30)
        recipients = [e for e in (config.get("notification_emails") or []) if e and e.strip()]
        scope = config.get("collection_name") or (
            f"collection {config['collection_id']}" if config.get("collection_id") else "All collections"
        )

        due = await self.sync.list_due_certificates(
            collection_id=config.get("collection_id"),
            days_before_expiry=max(warning_days, critical_days),
        )

        rows = []
        for cert in due:
            days = _days_until(cert.get("not_after"))
            if days is None:
                continue
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

        if not rows:
            await self._record_run(
                action=ALERT_RUN_ACTION,
                config=config,
                summary=f"Expiry alert check for {scope}: no certificates within {warning_days} days",
                details={"trigger": trigger, "critical": 0, "warning": 0, "emails_sent": 0},
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
            f"Expiry alert for {scope}: {len(critical)} critical, {len(warning)} warning "
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
            if trigger == "schedule" and await self._ran_recently(RENEWAL_RUN_ACTION, config["id"]):
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
        recipients = [e for e in (config.get("notification_emails") or []) if e and e.strip()]
        targets = [t for t in (config.get("akv_targets") or []) if isinstance(t, dict)]
        scope = config.get("collection_name") or f"collection {config.get('collection_id')}"
        cert_ids = [c.get("id") for c in (config.get("certificates") or []) if isinstance(c, dict) and c.get("id")]

        due = await self.sync.list_due_certificates(
            collection_id=config.get("collection_id"),
            days_before_expiry=days_before,
            certificate_ids=cert_ids or None,
        )
        capped = due[:_MAX_RENEWALS_PER_RUN]

        renewed: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []

        if armed:
            for cert in capped:
                outcome = await self._renew_one(cert, config=config, targets=targets, actor=actor)
                (renewed if outcome.get("renewed") else failed).append(outcome)

        planned = [
            {
                "common_name": c.get("common_name") or f"Certificate {c.get('id')}",
                "certificate_id": c.get("id"),
                "not_after": c.get("not_after"),
                "days_until_expiry": _days_until(c.get("not_after")),
            }
            for c in capped
        ]

        delivery: dict[str, Any] = {"success": 0}
        if recipients and (capped or not armed):
            delivery = await self.email.send_certificate_renewal_report(
                recipient_emails=recipients,
                scope_label=scope,
                armed=armed,
                planned=planned,
                renewed=renewed,
                failed=failed,
                days_before_expiry=days_before,
                truncated=len(due) - len(capped),
                config_id=config["id"],
            )

        mode = "renewed" if armed else "would renew"
        summary = (
            f"Auto-renewal {'run' if armed else 'dry run'} for {scope}: "
            f"{len(renewed) if armed else len(capped)} {mode}, {len(failed)} failed "
            f"({delivery.get('success', 0)}/{len(recipients)} emails sent)"
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
                "failed": [{"common_name": f["common_name"], "error": f.get("error", "")} for f in failed],
                "emails_sent": delivery.get("success", 0),
                "akv_targets": [t.get("vault_name") for t in targets],
            },
            outcome="partial" if failed else "success",
            actor=actor or config.get("created_by") or "scheduler",
        )
        return {
            "config_id": config["id"],
            "armed": armed,
            "certificates_due": len(due),
            "renewed": len(renewed),
            "failed": len(failed),
            "emails_sent": delivery.get("success", 0),
        }

    async def _renew_one(
        self,
        cert: dict[str, Any],
        *,
        config: dict[str, Any],
        targets: list[dict[str, Any]],
        actor: str | None,
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
            return record
        except Exception as exc:  # noqa: BLE001 - report, never abort the schedule
            record["error"] = str(exc)[:200]
            return record

        record["renewed"] = True
        record["thumbprint"] = result.get("thumbprint") or ""
        new_certificate_id = result.get("certificate_id") or certificate_id
        record["new_certificate_id"] = new_certificate_id

        pfx_base64 = result.get("pfx_base64")
        if pfx_base64:
            try:
                await CertificateEscrowService(self.db).escrow(
                    certificate_id=new_certificate_id,
                    thumbprint=str(result.get("thumbprint") or ""),
                    common_name=common_name,
                    pfx_base64=str(pfx_base64),
                    password=pfx_password,
                    source="auto_renewal",
                    actor=actor or "scheduler",
                )
                record["escrowed"] = True
            except Exception as exc:  # noqa: BLE001 - renewal already succeeded
                logger.warning(
                    "cert_auto_renewal_escrow_failed", certificate_id=new_certificate_id, error=str(exc)[:200]
                )
                record["escrowed"] = False

        if targets:
            record["akv"] = await self._load_to_targets(pfx_base64=pfx_base64, password=pfx_password, targets=targets)
        return record

    async def _load_to_targets(
        self,
        *,
        pfx_base64: str | None,
        password: str,
        targets: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Import the freshly issued PFX into every configured vault entry."""
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
