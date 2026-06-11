"""
Compliance & Drift Detection Service.

Provides:
- Synapse pipeline checksum tracking and drift detection
- AKS pod checksum monitoring and change detection
- Compliance scoring and reporting
- Synapse checksum verification via native Python (Azure SDK)
"""

import asyncio
import csv
import hashlib
import io
import json
import time
import urllib.parse
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import structlog
from apscheduler.triggers.cron import CronTrigger
from azure.identity import DefaultAzureCredential
from azure.mgmt.synapse import SynapseManagementClient
from kubernetes.client.rest import ApiException
from sqlalchemy import and_, desc, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.subscription_scope import get_scoped_subscription_ids
from app.models.database import (
    AKSPodChecksum,
    AKSPodDrift,
    AzureResourceInventory,
    ChecksumResult,
    ChecksumRun,
    ChecksumScheduleConfig,
    ComplianceScore,
    SynapsePipelineChecksum,
    SynapsePipelineDrift,
)
from app.services.email_notification_service import EmailNotificationService

logger = structlog.get_logger(__name__)


class ComplianceService:
    """
    Enterprise Compliance & Drift Detection Service.

    Provides:
    - Synapse pipeline checksum tracking
    - AKS pod specification monitoring
    - Drift detection and alerting
    - Compliance scoring
    """

    # Maximum seconds to wait for a single Azure SDK call (connect + read).
    # ATTCC workspaces behind private endpoints / firewalls may silently drop
    # packets, causing the SDK to hang indefinitely.  A timeout ensures the
    # UI receives a clear error rather than appearing frozen.
    _AZURE_SDK_TIMEOUT_SECONDS: int = 60

    def __init__(self, db_session: AsyncSession):
        self.db = db_session
        try:
            self.credential = DefaultAzureCredential()
        except Exception as exc:
            logger.warning(
                "azure_credential_init_failed",
                error=str(exc)[:200],
            )
            self.credential = None

    @staticmethod
    def _normalize_schedule_id(schedule_id: str | int) -> int:
        return int(schedule_id)

    async def _resolve_scoped_subscription_ids(
        self,
        subscription_ids: list[str] | None = None,
    ) -> list[str]:
        """Resolve the effective dashboard scope from Admin-monitored subscriptions.

        If no admin subscriptions are configured AND no env-var fallback exists,
        returns all distinct subscription IDs found in the checksum tables so
        the dashboard can still show existing data.
        """
        monitored_subscription_ids = await get_scoped_subscription_ids()
        if not subscription_ids:
            if monitored_subscription_ids:
                return monitored_subscription_ids
            # Fallback: discover subscription IDs from existing data so the
            # dashboard is never empty when data has been collected.
            return await self._discover_subscription_ids_from_data()

        if not monitored_subscription_ids:
            # No admin scoping configured — trust the caller's list as-is.
            return subscription_ids

        monitored_set = set(monitored_subscription_ids)
        return [subscription_id for subscription_id in subscription_ids if subscription_id in monitored_set]

    async def _discover_subscription_ids_from_data(self) -> list[str]:
        """Return distinct subscription IDs present in checksum tables.

        Used as a last-resort fallback when neither the admin_subscriptions
        table nor the AZURE_SUBSCRIPTION_IDS env-var is populated.
        """
        if self.db is None:
            return []

        ids: set[str] = set()
        try:
            synapse_stmt = select(SynapsePipelineChecksum.subscription_id).distinct().limit(100)
            synapse_result = await self.db.execute(synapse_stmt)
            ids.update(row[0] for row in synapse_result.all() if row[0])

            aks_stmt = select(AKSPodChecksum.cluster_id).distinct().limit(100)
            aks_result = await self.db.execute(aks_stmt)
            for (cluster_id,) in aks_result.all():
                sub_id = self._extract_subscription_id_from_resource_id(cluster_id)
                if sub_id:
                    ids.add(sub_id)
        except Exception:
            logger.warning("discover_subscription_ids_from_data_failed", exc_info=True)

        if ids:
            logger.info("subscription_ids_discovered_from_data", count=len(ids))
        return list(ids)

    @staticmethod
    def _extract_subscription_id_from_resource_id(
        resource_id: str | None,
    ) -> str | None:
        if not resource_id:
            return None

        marker = "/subscriptions/"
        lowered = resource_id.lower()
        start = lowered.find(marker)
        if start < 0:
            return None

        remainder = resource_id[start + len(marker) :]
        subscription_id = remainder.split("/", 1)[0].strip()
        return subscription_id or None

    @classmethod
    def _cluster_matches_subscription_scope(
        cls,
        cluster_id: str | None,
        subscription_ids: list[str] | None,
    ) -> bool:
        if not subscription_ids:
            return False

        cluster_subscription_id = cls._extract_subscription_id_from_resource_id(cluster_id)
        if not cluster_subscription_id:
            return False

        return cluster_subscription_id in set(subscription_ids)

    @classmethod
    def _filter_aks_rows_by_subscription_scope(
        cls,
        rows: list[Any],
        subscription_ids: list[str] | None,
    ) -> list[Any]:
        return [
            row
            for row in rows
            if cls._cluster_matches_subscription_scope(getattr(row, "cluster_id", None), subscription_ids)
        ]

    @staticmethod
    def _aks_subscription_scope_clause(
        column: Any,
        subscription_ids: list[str],
    ) -> Any:
        """Return a SQLAlchemy WHERE clause that filters an AKS cluster_id
        column to rows whose embedded subscription ID is in *subscription_ids*.

        This pushes subscription filtering into the database instead of
        loading all rows and filtering in Python.
        """
        return or_(*[column.ilike(f"%/subscriptions/{sid}/%") for sid in subscription_ids])

    @staticmethod
    def _filter_workspaces_by_subscription_scope(
        workspaces: list[dict[str, str]],
        subscription_ids: list[str] | None,
    ) -> list[dict[str, str]]:
        if not subscription_ids:
            return []

        allowed = set(subscription_ids)
        return [workspace for workspace in workspaces if workspace.get("subscription_id") in allowed]

    async def _get_allowed_synapse_workspace_names(self) -> set[str]:
        workspaces = await self.get_workspace_list()
        return {workspace["workspace_name"] for workspace in workspaces if workspace.get("workspace_name")}

    async def _get_allowed_aks_cluster_names(
        self,
        subscription_ids: list[str] | None = None,
    ) -> set[str]:
        if self.db is None:
            return set()

        # Serve from class-level cache if fresh
        now = time.monotonic()
        if (
            ComplianceService._aks_cluster_cache
            and (now - ComplianceService._aks_cluster_cache_ts) < self._AKS_CLUSTER_CACHE_TTL
            and subscription_ids is None
        ):
            return set(ComplianceService._aks_cluster_cache)

        scoped_subscription_ids = await self._resolve_scoped_subscription_ids(subscription_ids)
        if not scoped_subscription_ids:
            return set()

        allowed_clusters: set[str] = set()

        inventory_stmt = select(AzureResourceInventory.name, AzureResourceInventory.resource_id).where(
            AzureResourceInventory.resource_type == "aks_cluster"
        )
        inventory_result = await self.db.execute(inventory_stmt)
        for cluster_name, resource_id in inventory_result.all():
            if cluster_name and self._cluster_matches_subscription_scope(resource_id, scoped_subscription_ids):
                allowed_clusters.add(cluster_name)

        # Limit to last 30 days to avoid scanning the entire table
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        checksum_stmt = (
            select(AKSPodChecksum.cluster_name, AKSPodChecksum.cluster_id)
            .where(AKSPodChecksum.snapshot_date >= thirty_days_ago)
            .distinct()
        )
        checksum_result = await self.db.execute(checksum_stmt)
        for cluster_name, cluster_id in checksum_result.all():
            if cluster_name and self._cluster_matches_subscription_scope(cluster_id, scoped_subscription_ids):
                allowed_clusters.add(cluster_name)

        # Update class-level cache for default scope queries
        if subscription_ids is None and allowed_clusters:
            ComplianceService._aks_cluster_cache = allowed_clusters
            ComplianceService._aks_cluster_cache_ts = now

        return allowed_clusters

    async def _is_checksum_schedule_in_scope(self, schedule: "ChecksumScheduleConfig") -> bool:
        if schedule.module_type == "synapse":
            allowed_workspaces = await self._get_allowed_synapse_workspace_names()
            return bool(schedule.workspace_name and schedule.workspace_name in allowed_workspaces)

        if schedule.module_type == "aks":
            scoped_subscription_ids = await self._resolve_scoped_subscription_ids()
            return self._cluster_matches_subscription_scope(schedule.cluster_id, scoped_subscription_ids)

        return False

    async def _get_scoped_checksum_schedule_record(
        self,
        schedule_id: str | int,
    ) -> "ChecksumScheduleConfig":
        normalized_schedule_id = self._normalize_schedule_id(schedule_id)
        stmt = select(ChecksumScheduleConfig).where(ChecksumScheduleConfig.id == normalized_schedule_id)
        result = await self.db.execute(stmt)
        schedule = result.scalar_one_or_none()

        if schedule is None or not await self._is_checksum_schedule_in_scope(schedule):
            raise ValueError("Schedule not found")

        return schedule

    async def _validate_checksum_schedule_target(
        self,
        *,
        module_type: str,
        workspace_name: str | None = None,
        cluster_id: str | None = None,
    ) -> None:
        if module_type == "synapse":
            allowed_workspaces = await self._get_allowed_synapse_workspace_names()
            if not workspace_name or workspace_name not in allowed_workspaces:
                raise ValueError("Selected Synapse workspace is outside the Admin monitored subscription scope")
            return

        if module_type == "aks":
            scoped_subscription_ids = await self._resolve_scoped_subscription_ids()
            if not cluster_id or not self._cluster_matches_subscription_scope(cluster_id, scoped_subscription_ids):
                raise ValueError("Selected AKS cluster is outside the Admin monitored subscription scope")
            return

        raise ValueError("module_type must be 'synapse' or 'aks'")

    # =========================================================================
    # A. SYNAPSE PIPELINE CHECKSUM TRACKING
    # =========================================================================

    async def collect_synapse_pipeline_checksums(
        self,
        subscription_ids: list[str] | None = None,
        workspace_name: str | None = None,
    ) -> dict[str, Any]:
        """Collect checksums for Synapse pipelines.

        Uses the **workspace registry** (``SYNAPSE_WORKSPACES``) and connects
        directly to each workspace's Synapse REST API via ``ArtifactsClient``.
        This is the same approach that ``run_checksum_verification()`` uses and
        ensures both ATTCC and CES workspaces are collected reliably without
        depending on subscription-level discovery.

        When *workspace_name* is provided only that single workspace is
        collected; otherwise all known workspaces are processed.

        Returns:
            Summary of collected checksums.
        """
        snapshot_date = datetime.utcnow()
        results: dict[str, Any] = {"workspaces": 0, "pipelines": 0, "errors": []}

        loop = asyncio.get_running_loop()
        scoped_subscription_ids = await self._resolve_scoped_subscription_ids(subscription_ids)

        # Build target workspace list from the monitored workspace registry.
        target_workspaces = await self.get_workspace_list()
        if workspace_name:
            target_workspaces = [ws for ws in target_workspaces if ws["workspace_name"] == workspace_name]
            if not target_workspaces:
                # Workspace not in filtered registry — try a fresh live scoped discovery.
                try:
                    live = self._filter_workspaces_by_subscription_scope(
                        await self._fetch_live_synapse_workspaces(),
                        scoped_subscription_ids,
                    )
                    target_workspaces = [ws for ws in live if ws["workspace_name"] == workspace_name]
                except Exception:
                    pass

        for ws_meta in target_workspaces:
            ws_name = ws_meta["workspace_name"]
            subscription_id = ws_meta.get("subscription_id", "")

            try:
                # Use direct REST API calls to avoid Azure SDK
                # DeserializationError on complex ATTCC Synapse pipelines
                pipelines = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        self._list_pipelines_rest,
                        ws_name,
                    ),
                    timeout=self._AZURE_SDK_TIMEOUT_SECONDS,
                )

                results["workspaces"] += 1

                for raw_bytes, pipeline in pipelines:
                    # Match bash: curl ... | tr -d '\r' => $() strips
                    # trailing newlines => echo adds one back.
                    checksum_input = raw_bytes.replace(b"\r", b"").rstrip(b"\n") + b"\n"
                    checksum = hashlib.sha256(checksum_input).hexdigest()

                    pipeline_checksum = SynapsePipelineChecksum(
                        snapshot_date=snapshot_date,
                        subscription_id=subscription_id,
                        subscription_name=None,
                        workspace_name=ws_name,
                        workspace_id=f"/subscriptions/{subscription_id}/workspaces/{ws_name}",
                        pipeline_name=pipeline.get("name"),
                        checksum_sha256=checksum,
                        pipeline_definition=pipeline,
                        activities_count=len(pipeline.get("properties", {}).get("activities", [])),
                        last_modified=self._parse_datetime(pipeline.get("properties", {}).get("lastPublishTime")),
                    )
                    self.db.add(pipeline_checksum)
                    results["pipelines"] += 1

            except TimeoutError:
                error_msg = (
                    f"Timed out after {self._AZURE_SDK_TIMEOUT_SECONDS}s connecting to "
                    f"{ws_name}. The workspace may be behind a private endpoint or "
                    f"firewall that blocks access from this server."
                )
                results["errors"].append({"workspace": ws_name, "error": error_msg})
                logger.error(
                    "synapse_pipeline_fetch_timeout",
                    workspace=ws_name,
                    timeout=self._AZURE_SDK_TIMEOUT_SECONDS,
                )
            except Exception as e:
                results["errors"].append(
                    {
                        "workspace": ws_name,
                        "error": str(e),
                    }
                )
                logger.error(
                    "synapse_pipeline_fetch_failed",
                    workspace=ws_name,
                    error=str(e),
                )

        await self.db.commit()
        logger.info(
            "synapse_checksum_collection_complete",
            workspaces=results["workspaces"],
            pipelines=results["pipelines"],
            errors=len(results["errors"]),
        )

        return results

    async def detect_synapse_pipeline_drift(
        self,
        workspace_name: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Compare today's checksums with yesterday's to detect drift.

        Returns:
            List of detected drift events
        """
        today = datetime.utcnow().date()
        yesterday = today - timedelta(days=1)

        # Query for today and yesterday checksums
        today_stmt = select(SynapsePipelineChecksum).where(func.date(SynapsePipelineChecksum.snapshot_date) == today)
        yesterday_stmt = select(SynapsePipelineChecksum).where(
            func.date(SynapsePipelineChecksum.snapshot_date) == yesterday
        )

        if workspace_name:
            today_stmt = today_stmt.where(SynapsePipelineChecksum.workspace_name == workspace_name)
            yesterday_stmt = yesterday_stmt.where(SynapsePipelineChecksum.workspace_name == workspace_name)

        today_result = await self.db.execute(today_stmt)
        yesterday_result = await self.db.execute(yesterday_stmt)
        today_checksums = {(r.workspace_name, r.pipeline_name): r for r in today_result.scalars().all()}
        yesterday_checksums = {(r.workspace_name, r.pipeline_name): r for r in yesterday_result.scalars().all()}

        drifts = []
        detection_date = datetime.utcnow()

        # Check for modified and deleted pipelines
        for key, yesterday_data in yesterday_checksums.items():
            if key in today_checksums:
                today_data = today_checksums[key]
                if yesterday_data.checksum_sha256 != today_data.checksum_sha256:
                    # Pipeline modified
                    diff = self._compute_diff(
                        yesterday_data.pipeline_definition,
                        today_data.pipeline_definition,
                    )

                    drift = SynapsePipelineDrift(
                        detection_date=detection_date,
                        workspace_id=yesterday_data.workspace_id,
                        workspace_name=yesterday_data.workspace_name,
                        pipeline_name=yesterday_data.pipeline_name,
                        drift_type="modified",
                        previous_checksum=yesterday_data.checksum_sha256,
                        current_checksum=today_data.checksum_sha256,
                        previous_definition=yesterday_data.pipeline_definition,
                        current_definition=today_data.pipeline_definition,
                        diff_summary=diff,
                    )
                    self.db.add(drift)
                    drifts.append(self._format_drift(drift))
            else:
                # Pipeline deleted
                drift = SynapsePipelineDrift(
                    detection_date=detection_date,
                    workspace_id=yesterday_data.workspace_id,
                    workspace_name=yesterday_data.workspace_name,
                    pipeline_name=yesterday_data.pipeline_name,
                    drift_type="deleted",
                    previous_checksum=yesterday_data.checksum_sha256,
                    current_checksum=None,
                    previous_definition=yesterday_data.pipeline_definition,
                    current_definition=None,
                )
                self.db.add(drift)
                drifts.append(self._format_drift(drift))

        # Check for new pipelines
        for key, today_data in today_checksums.items():
            if key not in yesterday_checksums:
                drift = SynapsePipelineDrift(
                    detection_date=detection_date,
                    workspace_id=today_data.workspace_id,
                    workspace_name=today_data.workspace_name,
                    pipeline_name=today_data.pipeline_name,
                    drift_type="added",
                    previous_checksum=None,
                    current_checksum=today_data.checksum_sha256,
                    previous_definition=None,
                    current_definition=today_data.pipeline_definition,
                )
                self.db.add(drift)
                drifts.append(self._format_drift(drift))

        await self.db.commit()
        logger.info("synapse_drift_detection_complete", drifts_detected=len(drifts))

        return drifts

    async def get_synapse_drifts(
        self,
        workspace_name: str | None = None,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """Return persisted Synapse drift events without re-running detection."""
        stmt = select(SynapsePipelineDrift)

        if workspace_name and workspace_name != "all":
            stmt = stmt.where(SynapsePipelineDrift.workspace_name == workspace_name)

        if days > 0:
            start_date = datetime.utcnow() - timedelta(days=days)
            stmt = stmt.where(SynapsePipelineDrift.detection_date >= start_date)

        result = await self.db.execute(stmt.order_by(desc(SynapsePipelineDrift.detection_date)))
        return [self._format_drift(drift) for drift in result.scalars().all()]

    async def get_synapse_drift_summary(
        self,
        days: int = 7,
        workspace_name: str | None = None,
    ) -> dict[str, Any]:
        """
        Get drift summary dashboard data.

        Includes ``total_pipelines``, ``compliant_pipelines``,
        ``drifted_pipelines`` and ``acknowledged_drifts`` so the
        frontend summary cards always have concrete values.
        """
        start_date = datetime.utcnow() - timedelta(days=days)

        stmt = select(SynapsePipelineDrift).where(SynapsePipelineDrift.detection_date >= start_date)

        if workspace_name:
            stmt = stmt.where(SynapsePipelineDrift.workspace_name == workspace_name)

        result = await self.db.execute(stmt)
        drifts = result.scalars().all()

        # Aggregate by type
        by_type = {"added": 0, "modified": 0, "deleted": 0}
        by_workspace: dict[str, int] = {}
        by_date: dict[str, int] = {}

        acknowledged_count = 0
        for d in drifts:
            by_type[d.drift_type] = by_type.get(d.drift_type, 0) + 1

            ws_name = d.workspace_name
            by_workspace[ws_name] = by_workspace.get(ws_name, 0) + 1

            date_str = d.detection_date.strftime("%Y-%m-%d")
            by_date[date_str] = by_date.get(date_str, 0) + 1

            if d.acknowledged:
                acknowledged_count += 1

        # Derive total_pipelines from the latest ChecksumRun for this scope
        total_pipelines = 0
        compliant_pipelines = 0
        try:
            run_stmt = (
                select(ChecksumRun)
                .where(ChecksumRun.module_type == "synapse")
                .order_by(desc(ChecksumRun.execution_date))
                .limit(1)
            )
            if workspace_name:
                run_stmt = run_stmt.where(ChecksumRun.workspace_name == workspace_name)
            run_result = await self.db.execute(run_stmt)
            latest_run = run_result.scalar_one_or_none()
            if latest_run is not None:
                total_pipelines = latest_run.total_pipelines or 0
                compliant_pipelines = latest_run.passed or 0
        except Exception:
            # Non-critical; default to zero if the query fails
            pass

        drifted_pipelines = len(drifts)
        unacknowledged = len(drifts) - acknowledged_count

        return {
            "total_drifts": len(drifts),
            "total_pipelines": total_pipelines,
            "compliant_pipelines": compliant_pipelines,
            "drifted_pipelines": drifted_pipelines,
            "acknowledged_drifts": acknowledged_count,
            "by_type": by_type,
            "by_workspace": by_workspace,
            "timeline": [{"date": k, "count": v} for k, v in sorted(by_date.items())],
            "unacknowledged": unacknowledged,
        }

    async def acknowledge_synapse_drift(
        self,
        drift_id: int,
        user_id: str,
        user_email: str,
    ) -> dict[str, Any]:
        """
        Acknowledge a drift event.
        """
        result = await self.db.execute(select(SynapsePipelineDrift).where(SynapsePipelineDrift.id == drift_id))
        drift = result.scalars().first()

        if not drift:
            return {"success": False, "error": "Drift not found"}

        drift.acknowledged = True
        drift.acknowledged_by = user_email
        drift.acknowledged_at = datetime.utcnow()
        drift.compliance_status = "acknowledged"

        await self.db.commit()

        return {
            "success": True,
            "drift_id": drift_id,
            "acknowledged_by": user_email,
        }

    # =========================================================================
    # B. AKS POD CHECKSUM MONITORING
    # =========================================================================

    async def collect_pod_checksums(
        self,
        cluster_id: str,
        namespaces: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Collect checksums for all pods in specified namespaces.
        """
        from app.services.aks_operations_service import AKSOperationsService

        aks_service = AKSOperationsService(self.db)

        _, core_v1, _ = await aks_service._get_k8s_clients(cluster_id)
        snapshot_date = datetime.utcnow()
        cluster_name = aks_service._extract_cluster_name(cluster_id)
        results = {"pods": 0, "namespaces": 0, "errors": []}

        try:
            if namespaces:
                pod_list_items = []
                for ns in namespaces:
                    ns_pods = await asyncio.to_thread(core_v1.list_namespaced_pod, ns)
                    pod_list_items.extend(ns_pods.items)
                    results["namespaces"] += 1
            else:
                pod_list = await asyncio.to_thread(core_v1.list_pod_for_all_namespaces)
                pod_list_items = pod_list.items

            for pod in pod_list_items:
                try:
                    # Extract components for checksums
                    pod_spec = self._serialize_pod_spec(pod.spec)
                    container_images = [c.image for c in (pod.spec.containers or [])]
                    # Use actual image SHA256 digests from pod status (imageID)
                    # rather than hashing the image tag string.
                    image_shas = self._extract_image_shas(pod.status)
                    # Fallback: actual runtime-resolved image refs from
                    # container_statuses (NOT init containers / spec).
                    actual_images = self._extract_actual_container_images(pod.status)
                    env_vars = self._extract_env_vars(pod.spec.containers)
                    volumes = self._serialize_volumes(pod.spec.volumes)
                    resource_limits = self._extract_resource_limits(pod.spec.containers)

                    # Generate checksums
                    spec_checksum = self._compute_checksum(pod_spec)
                    # Hash the sorted image SHA digests into a single 64-char
                    # checksum so it fits the String(64) column.
                    if image_shas:
                        images_checksum = self._compute_checksum(sorted(image_shas))
                    elif actual_images:
                        # Prefer actual container runtime images over spec
                        # (init) values — these reflect the running state.
                        images_checksum = self._compute_checksum(sorted(actual_images))
                    else:
                        images_checksum = self._compute_checksum(container_images)
                    env_checksum = self._compute_checksum(env_vars)
                    volumes_checksum = self._compute_checksum(volumes)
                    resources_checksum = self._compute_checksum(resource_limits)

                    # Overall checksum combining all components
                    overall_checksum = self._compute_checksum(
                        {
                            "spec": spec_checksum,
                            "images": images_checksum,
                            "env": env_checksum,
                            "volumes": volumes_checksum,
                            "resources": resources_checksum,
                        }
                    )

                    # Get owner reference
                    owner_kind = None
                    owner_name = None
                    if pod.metadata.owner_references:
                        owner_ref = pod.metadata.owner_references[0]
                        owner_kind = owner_ref.kind
                        owner_name = owner_ref.name

                    # Store checksum
                    pod_checksum = AKSPodChecksum(
                        snapshot_date=snapshot_date,
                        cluster_id=cluster_id,
                        cluster_name=cluster_name,
                        namespace=pod.metadata.namespace,
                        pod_name=pod.metadata.name,
                        owner_kind=owner_kind,
                        owner_name=owner_name,
                        checksum_sha256=overall_checksum,
                        spec_checksum=spec_checksum,
                        container_images_checksum=images_checksum,
                        env_vars_checksum=env_checksum,
                        volumes_checksum=volumes_checksum,
                        resource_limits_checksum=resources_checksum,
                        image_digests=image_shas or None,
                        # Prefer actual runtime images over spec (init) values
                        container_images=actual_images if actual_images else container_images,
                        env_vars=env_vars,
                        volumes=volumes,
                        resource_limits=resource_limits,
                        pod_spec=pod_spec,
                    )
                    self.db.add(pod_checksum)
                    results["pods"] += 1

                except Exception as e:
                    results["errors"].append(
                        {
                            "pod": pod.metadata.name,
                            "namespace": pod.metadata.namespace,
                            "error": str(e),
                        }
                    )

        except ApiException as e:
            results["errors"].append({"cluster": cluster_id, "error": str(e)})
            logger.error("pod_checksum_collection_failed", cluster_id=cluster_id, error=str(e))

        await self.db.commit()
        logger.info(
            "pod_checksum_collection_complete",
            cluster=cluster_name,
            pods=results["pods"],
        )

        return results

    async def detect_pod_drift(
        self,
        cluster_id: str,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Detect drift in pod configurations compared to previous snapshot.
        """
        today = datetime.utcnow().date()
        yesterday = today - timedelta(days=1)

        # Query today and yesterday checksums
        today_stmt = select(AKSPodChecksum).where(
            AKSPodChecksum.cluster_id == cluster_id,
            func.date(AKSPodChecksum.snapshot_date) == today,
        )
        yesterday_stmt = select(AKSPodChecksum).where(
            AKSPodChecksum.cluster_id == cluster_id,
            func.date(AKSPodChecksum.snapshot_date) == yesterday,
        )

        if namespace:
            today_stmt = today_stmt.where(AKSPodChecksum.namespace == namespace)
            yesterday_stmt = yesterday_stmt.where(AKSPodChecksum.namespace == namespace)

        # Group by owner (deployment/statefulset) for better comparison
        today_result = await self.db.execute(today_stmt)
        today_checksums = {}
        for r in today_result.scalars().all():
            ms_name = self._derive_microservice_key(r.owner_kind, r.owner_name) or r.pod_name
            key = (r.namespace, r.owner_kind, ms_name)
            today_checksums[key] = r

        yesterday_result = await self.db.execute(yesterday_stmt)
        yesterday_checksums = {}
        for r in yesterday_result.scalars().all():
            ms_name = self._derive_microservice_key(r.owner_kind, r.owner_name) or r.pod_name
            key = (r.namespace, r.owner_kind, ms_name)
            yesterday_checksums[key] = r

        drifts = []
        detection_date = datetime.utcnow()
        cluster_name = self._extract_cluster_name(cluster_id)

        for key, yesterday_data in yesterday_checksums.items():
            if key in today_checksums:
                today_data = today_checksums[key]

                # Check each component for drift
                drift_detected = False
                drift_details = []

                # Image changes
                if yesterday_data.container_images_checksum != today_data.container_images_checksum:
                    drift_details.append(
                        {
                            "category": "container_image",
                            "previous": yesterday_data.container_images,
                            "current": today_data.container_images,
                            "severity": "high",
                        }
                    )
                    drift_detected = True

                # Config drift (env vars)
                if yesterday_data.env_vars_checksum != today_data.env_vars_checksum:
                    drift_details.append(
                        {
                            "category": "env_vars",
                            "previous": yesterday_data.env_vars,
                            "current": today_data.env_vars,
                            "severity": "medium",
                        }
                    )
                    drift_detected = True

                # Volume changes
                if yesterday_data.volumes_checksum != today_data.volumes_checksum:
                    drift_details.append(
                        {
                            "category": "volumes",
                            "previous": yesterday_data.volumes,
                            "current": today_data.volumes,
                            "severity": "medium",
                        }
                    )
                    drift_detected = True

                # Resource limit changes
                if yesterday_data.resource_limits_checksum != today_data.resource_limits_checksum:
                    drift_details.append(
                        {
                            "category": "resources",
                            "previous": yesterday_data.resource_limits,
                            "current": today_data.resource_limits,
                            "severity": "low",
                        }
                    )
                    drift_detected = True

                if drift_detected:
                    for detail in drift_details:
                        drift = AKSPodDrift(
                            detection_date=detection_date,
                            cluster_id=cluster_id,
                            cluster_name=cluster_name,
                            namespace=yesterday_data.namespace,
                            pod_name=yesterday_data.pod_name,
                            owner_kind=yesterday_data.owner_kind,
                            owner_name=yesterday_data.owner_name,
                            drift_type=self._categorize_drift_type(detail["category"]),
                            drift_category=detail["category"],
                            previous_value=detail["previous"],
                            current_value=detail["current"],
                            previous_checksum=yesterday_data.checksum_sha256,
                            current_checksum=today_data.checksum_sha256,
                            severity=detail["severity"],
                        )
                        self.db.add(drift)
                        drifts.append(self._format_pod_drift(drift))

        await self.db.commit()
        logger.info("pod_drift_detection_complete", cluster=cluster_name, drifts=len(drifts))

        return drifts

    async def get_pod_drifts(
        self,
        cluster_id: str,
        namespace: str | None = None,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """Return persisted AKS pod drift events without re-running detection."""
        stmt = select(AKSPodDrift).where(AKSPodDrift.cluster_id == cluster_id)

        if namespace:
            stmt = stmt.where(AKSPodDrift.namespace == namespace)

        if days > 0:
            start_date = datetime.utcnow() - timedelta(days=days)
            stmt = stmt.where(AKSPodDrift.detection_date >= start_date)

        result = await self.db.execute(stmt.order_by(desc(AKSPodDrift.detection_date)))
        return [self._format_pod_drift(drift) for drift in result.scalars().all()]

    async def get_pod_drift_timeline(
        self,
        cluster_id: str,
        days: int = 30,
        namespace: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get drift timeline for visualization.
        """
        start_date = datetime.utcnow() - timedelta(days=days)

        stmt = select(AKSPodDrift).where(
            AKSPodDrift.cluster_id == cluster_id,
            AKSPodDrift.detection_date >= start_date,
        )

        if namespace:
            stmt = stmt.where(AKSPodDrift.namespace == namespace)

        result = await self.db.execute(stmt.order_by(AKSPodDrift.detection_date))
        drifts = result.scalars().all()

        return [self._format_pod_drift(d) for d in drifts]

    async def acknowledge_pod_drift(
        self,
        drift_id: int,
        user_id: str,
        user_email: str,
    ) -> dict[str, Any]:
        """Acknowledge a pod drift event."""
        result = await self.db.execute(select(AKSPodDrift).where(AKSPodDrift.id == drift_id))
        drift = result.scalars().first()

        if not drift:
            return {"success": False, "error": "Pod drift not found"}

        drift.acknowledged = True
        drift.acknowledged_by = user_email
        drift.acknowledged_at = datetime.utcnow()
        drift.compliance_status = "acknowledged"

        await self.db.commit()

        return {
            "success": True,
            "drift_id": drift_id,
            "acknowledged_by": user_email,
        }

    # =========================================================================
    # C. COMPLIANCE SCORING
    # =========================================================================

    async def calculate_compliance_score(
        self,
        resource_type: str,
        resource_id: str,
        resource_name: str,
        subscription_id: str,
    ) -> dict[str, Any]:
        """
        Calculate compliance score for a resource.

        When *resource_type* is ``"all"`` the method discovers every Synapse
        workspace and AKS cluster that has checksum or drift data within the
        monitored subscription scope and scores each one.

        Score is based on:
        - Number of unacknowledged drifts
        - Severity of drifts
        - Time since last drift
        """

        if resource_type == "all":
            return await self._calculate_all_compliance_scores()

        return await self._calculate_single_compliance_score(
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            subscription_id=subscription_id,
        )

    async def _collect_fresh_data_for_scoring(
        self,
        subscription_ids: list[str],
    ) -> None:
        """Best-effort Synapse + AKS data collection before scoring."""

        # ── Synapse checksums ──────────────────────────────────────
        try:
            result = await self.collect_synapse_pipeline_checksums(
                subscription_ids=subscription_ids,
            )
            logger.info(
                "score_calc_synapse_collected",
                pipelines=result.get("pipelines", 0),
            )
        except Exception as exc:
            logger.warning(
                "score_calc_synapse_collection_failed",
                error=str(exc)[:500],
            )

        try:
            await self.detect_synapse_pipeline_drift()
        except Exception as exc:
            logger.warning(
                "score_calc_synapse_drift_failed",
                error=str(exc)[:500],
            )

        # ── AKS checksums ─────────────────────────────────────────
        try:
            cluster_ids: set[str] = set()

            inv_stmt = select(
                AzureResourceInventory.resource_id,
            ).where(
                AzureResourceInventory.resource_type == "aks_cluster",
            )
            inv_result = await self.db.execute(inv_stmt)
            for (rid,) in inv_result.all():
                if rid and self._cluster_matches_subscription_scope(rid, subscription_ids):
                    cluster_ids.add(rid)

            cs_stmt = select(AKSPodChecksum.cluster_id).distinct()
            cs_result = await self.db.execute(cs_stmt)
            for (cid,) in cs_result.all():
                if cid and self._cluster_matches_subscription_scope(cid, subscription_ids):
                    cluster_ids.add(cid)

            for cluster_id in cluster_ids:
                try:
                    await self.collect_pod_checksums(cluster_id=cluster_id)
                    await self.detect_pod_drift(cluster_id=cluster_id)
                except Exception as exc:
                    logger.warning(
                        "score_calc_aks_failed",
                        cluster=cluster_id,
                        error=str(exc)[:300],
                    )
        except Exception as exc:
            logger.warning(
                "score_calc_aks_discovery_failed",
                error=str(exc)[:500],
            )

    async def _calculate_all_compliance_scores(self) -> dict[str, Any]:
        """Bulk-calculate compliance scores for every known resource.

        Collects fresh checksum data from Azure first so there is always
        something to score — even on first run with empty tables.
        """
        subscription_ids = await self._resolve_scoped_subscription_ids()
        if not subscription_ids:
            logger.warning("calculate_all_no_subscriptions")
            return {
                "resource_id": "all",
                "resource_name": "Full Recalculation",
                "overall_score": 0,
                "drift_score": 0,
                "issues": {
                    "critical": 0,
                    "high": 0,
                    "medium": 0,
                    "low": 0,
                    "unacknowledged": 0,
                },
                "grade": "N/A",
                "resources_scored": 0,
                "results": [],
                "message": "No monitored subscriptions configured",
            }

        # ── Collect fresh data before scoring ──────────────────────
        await self._collect_fresh_data_for_scoring(subscription_ids)

        results: list[dict[str, Any]] = []
        score_date = datetime.utcnow()
        week_ago = score_date - timedelta(days=7)

        # ── Synapse workspaces ──────────────────────────────────────
        synapse_ws_stmt = (
            select(
                SynapsePipelineChecksum.workspace_id,
                SynapsePipelineChecksum.workspace_name,
                SynapsePipelineChecksum.subscription_id,
            )
            .where(SynapsePipelineChecksum.subscription_id.in_(subscription_ids))
            .distinct()
        )
        synapse_ws_result = await self.db.execute(synapse_ws_stmt)
        synapse_workspaces = synapse_ws_result.all()

        for ws_id, ws_name, sub_id in synapse_workspaces:
            result = await self._calculate_single_compliance_score(
                resource_type="synapse_workspace",
                resource_id=ws_id,
                resource_name=ws_name or ws_id,
                subscription_id=sub_id,
                _score_date=score_date,
                _week_ago=week_ago,
            )
            results.append(result)

        # ── AKS clusters ───────────────────────────────────────────
        aks_cluster_stmt = select(
            AKSPodChecksum.cluster_id,
            AKSPodChecksum.cluster_name,
        ).distinct()
        aks_cluster_result = await self.db.execute(aks_cluster_stmt)
        aks_clusters = [
            (cid, cname)
            for cid, cname in aks_cluster_result.all()
            if self._cluster_matches_subscription_scope(cid, subscription_ids)
        ]

        for cluster_id, cluster_name in aks_clusters:
            sub_id = self._extract_subscription_id_from_resource_id(cluster_id) or ""
            result = await self._calculate_single_compliance_score(
                resource_type="aks_cluster",
                resource_id=cluster_id,
                resource_name=cluster_name or cluster_id,
                subscription_id=sub_id,
                _score_date=score_date,
                _week_ago=week_ago,
            )
            results.append(result)

        total_scored = len(results)
        avg_score = round(sum(r.get("overall_score", 0) for r in results) / total_scored, 1) if total_scored else 0

        logger.info(
            "calculate_all_compliance_scores_complete",
            total=total_scored,
            avg_score=avg_score,
        )

        return {
            "resource_id": "all",
            "resource_name": "Full Recalculation",
            "overall_score": avg_score,
            "drift_score": avg_score,
            "issues": {
                "critical": sum(r.get("issues", {}).get("critical", 0) for r in results),
                "high": sum(r.get("issues", {}).get("high", 0) for r in results),
                "medium": sum(r.get("issues", {}).get("medium", 0) for r in results),
                "low": sum(r.get("issues", {}).get("low", 0) for r in results),
                "unacknowledged": sum(r.get("issues", {}).get("unacknowledged", 0) for r in results),
            },
            "grade": self._score_to_grade(avg_score),
            "resources_scored": total_scored,
            "results": results,
        }

    async def _calculate_single_compliance_score(
        self,
        resource_type: str,
        resource_id: str,
        resource_name: str,
        subscription_id: str,
        *,
        _score_date: datetime | None = None,
        _week_ago: datetime | None = None,
    ) -> dict[str, Any]:
        """Calculate and persist a compliance score for a single resource."""
        score_date = _score_date or datetime.utcnow()
        week_ago = _week_ago or (score_date - timedelta(days=7))

        if resource_type == "aks_cluster":
            result = await self.db.execute(
                select(AKSPodDrift).where(
                    AKSPodDrift.cluster_id == resource_id,
                    AKSPodDrift.detection_date >= week_ago,
                )
            )
            drifts = result.scalars().all()
        elif resource_type == "synapse_workspace":
            result = await self.db.execute(
                select(SynapsePipelineDrift).where(
                    SynapsePipelineDrift.workspace_id == resource_id,
                    SynapsePipelineDrift.detection_date >= week_ago,
                )
            )
            drifts = result.scalars().all()
        else:
            return {"error": "Unknown resource type"}

        # Count by severity
        critical = sum(1 for d in drifts if getattr(d, "severity", "medium") == "critical")
        high = sum(1 for d in drifts if getattr(d, "severity", "medium") == "high")
        medium = sum(1 for d in drifts if getattr(d, "severity", "medium") == "medium")
        low = sum(1 for d in drifts if getattr(d, "severity", "medium") == "low")

        # Calculate score (100 - penalties)
        base_score = 100.0
        penalties = (
            critical * 20  # Critical issues heavily penalize
            + high * 10  # High issues moderately penalize
            + medium * 5  # Medium issues lightly penalize
            + low * 2  # Low issues minimally penalize
        )

        overall_score = max(0, base_score - penalties)

        # Separate scores
        drift_score = max(0, 100 - len(drifts) * 5)
        unacknowledged = sum(1 for d in drifts if not d.acknowledged)

        # Store score
        compliance_score = ComplianceScore(
            score_date=score_date,
            resource_type=resource_type,
            resource_id=resource_id,
            resource_name=resource_name,
            subscription_id=subscription_id,
            overall_score=overall_score,
            drift_score=drift_score,
            total_resources=len(drifts),
            drifted_resources=len(drifts),
            critical_issues=critical,
            high_issues=high,
            medium_issues=medium,
            low_issues=low,
        )
        self.db.add(compliance_score)
        await self.db.commit()

        return {
            "resource_id": resource_id,
            "resource_name": resource_name,
            "overall_score": round(overall_score, 1),
            "drift_score": round(drift_score, 1),
            "issues": {
                "critical": critical,
                "high": high,
                "medium": medium,
                "low": low,
                "unacknowledged": unacknowledged,
            },
            "grade": self._score_to_grade(overall_score),
        }

    async def _get_latest_compliance_scores(
        self,
        subscription_ids: list[str] | None,
    ) -> list[ComplianceScore]:
        if not subscription_ids:
            return []

        subquery = (
            select(
                ComplianceScore.resource_id,
                func.max(ComplianceScore.score_date).label("max_date"),
            )
            .where(ComplianceScore.subscription_id.in_(subscription_ids))
            .group_by(ComplianceScore.resource_id)
            .subquery()
        )

        stmt = (
            select(ComplianceScore)
            .join(
                subquery,
                and_(
                    ComplianceScore.resource_id == subquery.c.resource_id,
                    ComplianceScore.score_date == subquery.c.max_date,
                ),
            )
            .where(ComplianceScore.subscription_id.in_(subscription_ids))
        )

        result = await self.db.execute(stmt)
        return result.scalars().all()

    async def _get_compliance_score_trend(
        self,
        subscription_ids: list[str] | None,
        days: int = 30,
    ) -> list[dict[str, Any]]:
        """Return daily average compliance scores for the last *days* days."""
        if not subscription_ids:
            return []

        cutoff = datetime.utcnow() - timedelta(days=days)
        date_label = func.date(ComplianceScore.score_date).label("day")

        stmt = (
            select(
                date_label,
                func.avg(ComplianceScore.overall_score).label("avg_score"),
            )
            .where(
                ComplianceScore.subscription_id.in_(subscription_ids),
                ComplianceScore.score_date >= cutoff,
            )
            .group_by(date_label)
            .order_by(date_label)
        )

        result = await self.db.execute(stmt)
        return [{"date": str(row.day), "score": round(float(row.avg_score), 1)} for row in result.all()]

    async def _get_latest_scoped_aks_snapshot_date(
        self,
        subscription_ids: list[str] | None,
    ) -> datetime | None:
        if not subscription_ids:
            return None

        stmt = select(func.max(AKSPodChecksum.snapshot_date)).where(
            self._aks_subscription_scope_clause(AKSPodChecksum.cluster_id, subscription_ids)
        )
        return await self.db.scalar(stmt)

    async def _get_latest_scoped_aks_drift_date(
        self,
        subscription_ids: list[str] | None,
    ) -> datetime | None:
        if not subscription_ids:
            return None

        stmt = select(func.max(AKSPodDrift.detection_date)).where(
            self._aks_subscription_scope_clause(AKSPodDrift.cluster_id, subscription_ids)
        )
        return await self.db.scalar(stmt)

    async def _get_dashboard_synapse_summary(
        self,
        subscription_ids: list[str] | None,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "total_pipelines": 0,
            "compliant_pipelines": 0,
            "drifted_pipelines": 0,
        }
        if not subscription_ids:
            return summary

        latest_snapshot_stmt = select(func.max(SynapsePipelineChecksum.snapshot_date)).where(
            SynapsePipelineChecksum.subscription_id.in_(subscription_ids)
        )
        latest_snapshot = await self.db.scalar(latest_snapshot_stmt)
        if latest_snapshot is None:
            return summary

        snapshot_stmt = select(
            SynapsePipelineChecksum.workspace_name,
            SynapsePipelineChecksum.pipeline_name,
        ).where(
            SynapsePipelineChecksum.snapshot_date == latest_snapshot,
            SynapsePipelineChecksum.subscription_id.in_(subscription_ids),
        )
        snapshot_result = await self.db.execute(snapshot_stmt)
        snapshot_rows = [
            (workspace_name, pipeline_name)
            for workspace_name, pipeline_name in snapshot_result.all()
            if workspace_name and pipeline_name
        ]
        if not snapshot_rows:
            return summary

        allowed_workspaces = {workspace_name for workspace_name, _ in snapshot_rows}
        summary["total_pipelines"] = len(snapshot_rows)

        latest_drift_stmt = select(func.max(SynapsePipelineDrift.detection_date)).where(
            SynapsePipelineDrift.workspace_name.in_(allowed_workspaces)
        )
        latest_drift_date = await self.db.scalar(latest_drift_stmt)

        if latest_drift_date is not None:
            drift_stmt = select(
                SynapsePipelineDrift.workspace_name,
                SynapsePipelineDrift.pipeline_name,
            ).where(
                SynapsePipelineDrift.detection_date == latest_drift_date,
                SynapsePipelineDrift.workspace_name.in_(allowed_workspaces),
                SynapsePipelineDrift.acknowledged == False,  # noqa: E712
            )
            drift_result = await self.db.execute(drift_stmt)
            drifted_pipelines = {
                (workspace_name, pipeline_name)
                for workspace_name, pipeline_name in drift_result.all()
                if workspace_name and pipeline_name
            }
            summary["drifted_pipelines"] = len(drifted_pipelines)

        summary["compliant_pipelines"] = max(
            summary["total_pipelines"] - summary["drifted_pipelines"],
            0,
        )
        return summary

    async def _get_dashboard_aks_summary(
        self,
        subscription_ids: list[str] | None,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "clusters": 0,
            "total_pods": 0,
            "compliant_clusters": 0,
            "drifted_clusters": 0,
            "drifted_pods": 0,
        }
        if not subscription_ids:
            return summary

        latest_snapshot = await self._get_latest_scoped_aks_snapshot_date(subscription_ids)
        if latest_snapshot is None:
            return summary

        pod_stmt = select(AKSPodChecksum).where(
            AKSPodChecksum.snapshot_date == latest_snapshot,
            self._aks_subscription_scope_clause(AKSPodChecksum.cluster_id, subscription_ids),
        )
        pod_result = await self.db.execute(pod_stmt)
        pods = pod_result.scalars().all()
        if not pods:
            return summary

        cluster_set = {pod.cluster_id for pod in pods}
        summary["total_pods"] = len(pods)
        summary["clusters"] = len(cluster_set)

        latest_drift_date = await self._get_latest_scoped_aks_drift_date(subscription_ids)
        if latest_drift_date is not None:
            drift_stmt = select(AKSPodDrift).where(
                AKSPodDrift.detection_date == latest_drift_date,
                AKSPodDrift.acknowledged == False,  # noqa: E712
                self._aks_subscription_scope_clause(AKSPodDrift.cluster_id, subscription_ids),
            )
            drift_result = await self.db.execute(drift_stmt)
            drifts = drift_result.scalars().all()
            summary["drifted_pods"] = len(drifts)
            drifted_clusters = {drift.cluster_id for drift in drifts}
            summary["drifted_clusters"] = len(drifted_clusters)

        summary["compliant_clusters"] = max(summary["clusters"] - summary["drifted_clusters"], 0)
        return summary

    def _build_dashboard_from_scores(
        self,
        scores: list[ComplianceScore],
        *,
        calculated_at: datetime | None,
        synapse_summary: dict[str, Any],
        aks_summary: dict[str, Any],
        score_trend: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        by_type: dict[str, Any] = {}
        by_grade: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
        total_critical = 0
        total_high = 0

        for score in scores:
            if score.resource_type not in by_type:
                by_type[score.resource_type] = {
                    "count": 0,
                    "avg_score": 0,
                    "total_score": 0,
                }
            by_type[score.resource_type]["count"] += 1
            by_type[score.resource_type]["total_score"] += score.overall_score

            grade = self._score_to_grade(score.overall_score)
            by_grade[grade] = by_grade.get(grade, 0) + 1

            total_critical += score.critical_issues or 0
            total_high += score.high_issues or 0

        for resource_type in by_type:
            if by_type[resource_type]["count"] > 0:
                by_type[resource_type]["avg_score"] = round(
                    by_type[resource_type]["total_score"] / by_type[resource_type]["count"],
                    1,
                )
            del by_type[resource_type]["total_score"]

        overall_avg = sum(score.overall_score for score in scores) / len(scores)

        return {
            "overall_score": round(overall_avg, 1),
            "overall_grade": self._score_to_grade(overall_avg),
            "calculated_at": calculated_at.isoformat() if calculated_at else None,
            "total_resources": len(scores),
            "by_type": by_type,
            "by_grade": by_grade,
            "critical_issues": total_critical,
            "high_issues": total_high,
            "score_trend": score_trend or [],
            "synapse_summary": synapse_summary,
            "aks_summary": aks_summary,
            "resources": [
                {
                    "id": score.resource_id,
                    "name": score.resource_name,
                    "type": score.resource_type,
                    "score": round(score.overall_score, 1),
                    "grade": self._score_to_grade(score.overall_score),
                    "critical_issues": score.critical_issues,
                }
                for score in sorted(scores, key=lambda item: item.overall_score)[:10]
            ],
        }

    async def get_compliance_dashboard(
        self,
        subscription_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """
        Get compliance dashboard data across all resources.

        When ``ComplianceScore`` records exist the dashboard is built from
        those.  Otherwise it falls back to deriving scores, grade
        distribution, trend, and resource data from actual ``ChecksumRun``
        records so the dashboard is never empty.
        """
        subscription_ids = await self._resolve_scoped_subscription_ids(subscription_ids)

        if not subscription_ids:
            logger.warning(
                "compliance_dashboard_no_subscriptions",
                hint="Neither admin_subscriptions DB, AZURE_SUBSCRIPTION_IDS env, nor checksum data found",
            )
            return {
                "overall_score": 0,
                "total_resources": 0,
                "compliant_resources": 0,
                "non_compliant_resources": 0,
                "by_grade": {},
                "critical_issues": 0,
                "high_issues": 0,
                "score_trend": [],
                "synapse_summary": {
                    "total_workspaces": 0,
                    "total_pipelines": 0,
                    "drifted_pipelines": 0,
                    "last_scan": None,
                },
                "aks_summary": {
                    "total_clusters": 0,
                    "total_pods": 0,
                    "drifted_pods": 0,
                    "last_scan": None,
                },
                "resources": [],
                "calculated_at": datetime.utcnow().isoformat(),
                "message": "No monitored subscriptions configured",
            }

        synapse_summary = await self._get_dashboard_synapse_summary(subscription_ids)
        aks_summary = await self._get_dashboard_aks_summary(subscription_ids)
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        snapshot_dashboard = await self._build_dashboard_from_checksum_snapshots(
            subscription_ids=subscription_ids,
            start_date=thirty_days_ago,
            synapse_summary=synapse_summary,
            aks_summary=aks_summary,
        )
        if snapshot_dashboard.get("total_resources", 0) > 0:
            return snapshot_dashboard

        scores = await self._get_latest_compliance_scores(subscription_ids)
        calculated_at = await self._get_dashboard_calculated_at(subscription_ids=subscription_ids)
        if scores:
            # Build 30-day score trend from ComplianceScore history
            score_trend = await self._get_compliance_score_trend(
                subscription_ids=subscription_ids,
                days=30,
            )
            return self._build_dashboard_from_scores(
                scores,
                calculated_at=calculated_at,
                synapse_summary=synapse_summary,
                aks_summary=aks_summary,
                score_trend=score_trend,
            )

        return snapshot_dashboard

    async def _build_dashboard_from_checksum_snapshots(
        self,
        *,
        subscription_ids: list[str] | None,
        start_date: datetime,
        synapse_summary: dict[str, Any],
        aks_summary: dict[str, Any],
    ) -> dict[str, Any]:
        latest_synapse_snapshot_stmt = select(func.max(SynapsePipelineChecksum.snapshot_date))
        latest_synapse_snapshot_stmt = latest_synapse_snapshot_stmt.where(
            SynapsePipelineChecksum.subscription_id.in_(subscription_ids)
        )
        latest_synapse_snapshot = await self.db.scalar(latest_synapse_snapshot_stmt)

        synapse_checksums: list[SynapsePipelineChecksum] = []
        if latest_synapse_snapshot:
            synapse_stmt = select(SynapsePipelineChecksum).where(
                SynapsePipelineChecksum.snapshot_date == latest_synapse_snapshot
            )
            synapse_stmt = synapse_stmt.where(SynapsePipelineChecksum.subscription_id.in_(subscription_ids))
            synapse_result = await self.db.execute(synapse_stmt)
            synapse_checksums = synapse_result.scalars().all()

        latest_aks_snapshot = await self._get_latest_scoped_aks_snapshot_date(subscription_ids)

        aks_checksums: list[AKSPodChecksum] = []
        if latest_aks_snapshot:
            aks_stmt = select(AKSPodChecksum).where(
                AKSPodChecksum.snapshot_date == latest_aks_snapshot,
                self._aks_subscription_scope_clause(AKSPodChecksum.cluster_id, subscription_ids),
            )
            aks_result = await self.db.execute(aks_stmt)
            aks_checksums = aks_result.scalars().all()

        synapse_drift_stmt = select(SynapsePipelineDrift).where(
            SynapsePipelineDrift.detection_date >= start_date,
            SynapsePipelineDrift.acknowledged == False,  # noqa: E712
        )
        synapse_workspace_stmt = select(SynapsePipelineChecksum.workspace_name).where(
            SynapsePipelineChecksum.subscription_id.in_(subscription_ids)
        )
        synapse_workspace_result = await self.db.execute(synapse_workspace_stmt)
        allowed_workspaces = {row[0] for row in synapse_workspace_result.all()}
        if allowed_workspaces:
            synapse_drift_stmt = synapse_drift_stmt.where(SynapsePipelineDrift.workspace_name.in_(allowed_workspaces))
        else:
            synapse_drift_stmt = synapse_drift_stmt.where(SynapsePipelineDrift.id.in_([]))
        synapse_drift_result = await self.db.execute(synapse_drift_stmt)
        synapse_drifts = synapse_drift_result.scalars().all()

        aks_drift_stmt = select(AKSPodDrift).where(
            AKSPodDrift.detection_date >= start_date,
            AKSPodDrift.acknowledged == False,  # noqa: E712
            self._aks_subscription_scope_clause(AKSPodDrift.cluster_id, subscription_ids),
        )
        aks_drift_result = await self.db.execute(aks_drift_stmt)
        aks_drifts = aks_drift_result.scalars().all()

        resources: list[dict[str, Any]] = []
        by_grade: dict[str, int] = {"A": 0, "B": 0, "C": 0, "D": 0, "F": 0}
        by_type: dict[str, dict[str, float | int]] = {}

        synapse_drifted_by_workspace: dict[str, set[str]] = {}
        critical_issues = 0
        high_issues = 0
        for drift in synapse_drifts:
            synapse_drifted_by_workspace.setdefault(drift.workspace_name, set()).add(drift.pipeline_name)
            severity = self._drift_type_to_severity(drift.drift_type)
            if severity == "critical":
                critical_issues += 1
            elif severity == "high":
                high_issues += 1

        synapse_checksums_by_workspace: dict[str, list[SynapsePipelineChecksum]] = {}
        for checksum in synapse_checksums:
            synapse_checksums_by_workspace.setdefault(checksum.workspace_name, []).append(checksum)

        for (
            workspace_name,
            workspace_checksums,
        ) in synapse_checksums_by_workspace.items():
            total = len(workspace_checksums)
            drifted = len(synapse_drifted_by_workspace.get(workspace_name, set()))
            score = ((total - drifted) / total * 100) if total > 0 else 0
            grade = self._score_to_grade(score)
            by_grade[grade] += 1
            by_type.setdefault("Synapse", {"count": 0, "avg_score": 0.0, "total_score": 0.0})
            by_type["Synapse"]["count"] += 1
            by_type["Synapse"]["total_score"] += score
            resources.append(
                {
                    "id": workspace_name,
                    "name": workspace_name,
                    "type": "synapse_workspace",
                    "score": round(score, 1),
                    "grade": grade,
                    "critical_issues": drifted,
                }
            )

        aks_drifted_by_cluster: dict[str, set[str]] = {}
        for drift in aks_drifts:
            aks_drifted_by_cluster.setdefault(drift.cluster_name, set()).add(drift.pod_name)
            if drift.severity == "critical":
                critical_issues += 1
            elif drift.severity == "high":
                high_issues += 1

        aks_checksums_by_cluster: dict[str, list[AKSPodChecksum]] = {}
        for checksum in aks_checksums:
            aks_checksums_by_cluster.setdefault(checksum.cluster_name, []).append(checksum)

        for cluster_name, cluster_checksums in aks_checksums_by_cluster.items():
            total = len(cluster_checksums)
            drifted = len(aks_drifted_by_cluster.get(cluster_name, set()))
            score = ((total - drifted) / total * 100) if total > 0 else 0
            grade = self._score_to_grade(score)
            by_grade[grade] += 1
            by_type.setdefault("AKS", {"count": 0, "avg_score": 0.0, "total_score": 0.0})
            by_type["AKS"]["count"] += 1
            by_type["AKS"]["total_score"] += score
            resources.append(
                {
                    "id": cluster_name,
                    "name": cluster_name,
                    "type": "aks_cluster",
                    "score": round(score, 1),
                    "grade": grade,
                    "critical_issues": drifted,
                }
            )

        for resource_type in list(by_type):
            count = by_type[resource_type]["count"]
            total_score = by_type[resource_type].pop("total_score")
            by_type[resource_type]["avg_score"] = round(float(total_score) / max(int(count), 1), 1)

        # ── Fetch ALL checksums within 30-day window for score trend ──
        # The latest-snapshot queries above are used for *current* scores.
        # For the 30-day trend we need every snapshot date in the window.
        synapse_trend_checksums: list[SynapsePipelineChecksum] = []
        synapse_trend_stmt = select(SynapsePipelineChecksum).where(
            SynapsePipelineChecksum.snapshot_date >= start_date,
            SynapsePipelineChecksum.subscription_id.in_(subscription_ids),
        )
        synapse_trend_result = await self.db.execute(synapse_trend_stmt)
        synapse_trend_checksums = synapse_trend_result.scalars().all()

        aks_trend_stmt = select(AKSPodChecksum).where(
            AKSPodChecksum.snapshot_date >= start_date,
            self._aks_subscription_scope_clause(AKSPodChecksum.cluster_id, subscription_ids),
        )
        aks_trend_result = await self.db.execute(aks_trend_stmt)
        aks_trend_checksums = aks_trend_result.scalars().all()

        synapse_daily_totals: dict[str, set[tuple[str, str]]] = {}
        for checksum in synapse_trend_checksums:
            date_key = checksum.snapshot_date.strftime("%Y-%m-%d")
            synapse_daily_totals.setdefault(date_key, set()).add((checksum.workspace_name, checksum.pipeline_name))

        aks_daily_totals: dict[str, set[tuple[str, str]]] = {}
        for checksum in aks_trend_checksums:
            date_key = checksum.snapshot_date.strftime("%Y-%m-%d")
            aks_daily_totals.setdefault(date_key, set()).add((checksum.cluster_name, checksum.pod_name))

        synapse_daily_drifts: dict[str, set[tuple[str, str]]] = {}
        for drift in synapse_drifts:
            date_key = drift.detection_date.strftime("%Y-%m-%d")
            synapse_daily_drifts.setdefault(date_key, set()).add((drift.workspace_name, drift.pipeline_name))

        aks_daily_drifts: dict[str, set[tuple[str, str]]] = {}
        for drift in aks_drifts:
            date_key = drift.detection_date.strftime("%Y-%m-%d")
            aks_daily_drifts.setdefault(date_key, set()).add((drift.cluster_name, drift.pod_name))

        score_trend: list[dict[str, Any]] = []
        all_dates = sorted(
            set(synapse_daily_totals) | set(aks_daily_totals) | set(synapse_daily_drifts) | set(aks_daily_drifts)
        )
        for date_key in all_dates:
            total_items = len(synapse_daily_totals.get(date_key, set())) + len(aks_daily_totals.get(date_key, set()))
            drift_items = len(synapse_daily_drifts.get(date_key, set())) + len(aks_daily_drifts.get(date_key, set()))
            if total_items <= 0:
                continue
            score_trend.append(
                {
                    "date": date_key,
                    "score": round(max(total_items - drift_items, 0) / total_items * 100, 1),
                }
            )

        total_items = len(synapse_checksums) + len(aks_checksums)
        total_drifted_items = sum(len(items) for items in synapse_drifted_by_workspace.values()) + sum(
            len(items) for items in aks_drifted_by_cluster.values()
        )
        overall_score = (
            round(max(total_items - total_drifted_items, 0) / total_items * 100, 1) if total_items > 0 else 0.0
        )

        # ── Reconcile summaries with the actual drift data used above ──
        # The pre-computed summaries may disagree because they use a
        # different time window.  Override with the authoritative counts
        # derived from the same 30-day drift queryset so every tile on the
        # dashboard is driven by one consistent data set.
        total_drifted_synapse_pipelines = sum(len(items) for items in synapse_drifted_by_workspace.values())
        synapse_summary["total_pipelines"] = len(synapse_checksums)
        synapse_summary["drifted_pipelines"] = total_drifted_synapse_pipelines
        synapse_summary["compliant_pipelines"] = max(len(synapse_checksums) - total_drifted_synapse_pipelines, 0)

        total_drifted_aks_pods = sum(len(items) for items in aks_drifted_by_cluster.values())
        drifted_cluster_count = len(aks_drifted_by_cluster)
        aks_summary["total_pods"] = len(aks_checksums)
        aks_summary["clusters"] = len(aks_checksums_by_cluster)
        aks_summary["drifted_pods"] = total_drifted_aks_pods
        aks_summary["drifted_clusters"] = drifted_cluster_count
        aks_summary["compliant_clusters"] = max(len(aks_checksums_by_cluster) - drifted_cluster_count, 0)

        return {
            "overall_score": overall_score,
            "overall_grade": self._score_to_grade(overall_score),
            "calculated_at": await self._latest_iso_timestamp(
                latest_synapse_snapshot,
                latest_aks_snapshot,
                max((drift.detection_date for drift in synapse_drifts), default=None),
                max((drift.detection_date for drift in aks_drifts), default=None),
            ),
            "total_resources": len(resources),
            "by_type": by_type,
            "by_grade": by_grade,
            "critical_issues": critical_issues,
            "high_issues": high_issues,
            "score_trend": score_trend,
            "synapse_summary": synapse_summary,
            "aks_summary": aks_summary,
            "resources": sorted(resources, key=lambda x: x["score"])[:10],
        }

    async def _get_dashboard_calculated_at(
        self,
        subscription_ids: list[str] | None = None,
    ) -> datetime | None:
        if not subscription_ids:
            subscription_ids = await self._resolve_scoped_subscription_ids(subscription_ids)

        score_stmt = select(func.max(ComplianceScore.score_date))
        score_stmt = score_stmt.where(ComplianceScore.subscription_id.in_(subscription_ids))
        latest_score = await self.db.scalar(score_stmt)

        run_stmt = select(func.max(ChecksumRun.execution_date))
        latest_run = await self.db.scalar(run_stmt)

        synapse_snapshot_stmt = select(func.max(SynapsePipelineChecksum.snapshot_date))
        synapse_snapshot_stmt = synapse_snapshot_stmt.where(
            SynapsePipelineChecksum.subscription_id.in_(subscription_ids)
        )
        latest_synapse_snapshot = await self.db.scalar(synapse_snapshot_stmt)

        latest_aks_snapshot = await self._get_latest_scoped_aks_snapshot_date(subscription_ids)

        workspace_stmt = select(SynapsePipelineChecksum.workspace_name).where(
            SynapsePipelineChecksum.subscription_id.in_(subscription_ids)
        )
        workspace_result = await self.db.execute(workspace_stmt)
        allowed_workspaces = {row[0] for row in workspace_result.all() if row[0]}

        latest_synapse_drift = None
        if allowed_workspaces:
            latest_synapse_drift_stmt = select(func.max(SynapsePipelineDrift.detection_date)).where(
                SynapsePipelineDrift.workspace_name.in_(allowed_workspaces)
            )
            latest_synapse_drift = await self.db.scalar(latest_synapse_drift_stmt)

        latest_aks_drift = await self._get_latest_scoped_aks_drift_date(subscription_ids)

        return self._latest_timestamp(
            latest_score,
            latest_run,
            latest_synapse_snapshot,
            latest_aks_snapshot,
            latest_synapse_drift,
            latest_aks_drift,
        )

    def _latest_timestamp(self, *values: datetime | None) -> datetime | None:
        timestamps = [value for value in values if value is not None]
        return max(timestamps) if timestamps else None

    async def _latest_iso_timestamp(self, *values: datetime | None) -> str | None:
        latest = self._latest_timestamp(*values)
        return latest.isoformat() if latest else None

    # =========================================================================
    # SYNAPSE WORKSPACE REGISTRY
    # =========================================================================

    SYNAPSE_WORKSPACES: list[dict[str, str]] = [
        # ATTCC workspaces
        {
            "workspace_name": "attcc-eastus2-perf-synapse-wkspace",
            "system": "attcc",
            "environment": "perf",
            "region": "eastus2",
        },
        {
            "workspace_name": "attcc-eastus2-poc-synapse-wkspace",
            "system": "attcc",
            "environment": "poc",
            "region": "eastus2",
        },
        {
            "workspace_name": "attcc-eastus2-prod-bussynapse-wkspace",
            "system": "attcc",
            "environment": "prod",
            "region": "eastus2",
        },
        {
            "workspace_name": "attcc-eastus2-prod-synapse-wkspace",
            "system": "attcc",
            "environment": "prod",
            "region": "eastus2",
        },
        {
            "workspace_name": "attcc-eastus2-stage-synapse-wkspace",
            "system": "attcc",
            "environment": "stage",
            "region": "eastus2",
        },
        {
            "workspace_name": "attcc-eastus2-uat-bussynapse-wkspace",
            "system": "attcc",
            "environment": "uat",
            "region": "eastus2",
        },
        {
            "workspace_name": "attcc-eastus2-uat-synapse-wkspace",
            "system": "attcc",
            "environment": "uat",
            "region": "eastus2",
        },
        {
            "workspace_name": "attcc-westus2-dr-bussynapse-wkspace",
            "system": "attcc",
            "environment": "dr",
            "region": "westus2",
        },
        {
            "workspace_name": "attcc-westus2-dr-synapse-wkspace",
            "system": "attcc",
            "environment": "dr",
            "region": "westus2",
        },
        # CES workspaces
        {
            "workspace_name": "ces-eastus2-dev-synapse",
            "system": "ces",
            "environment": "dev",
            "region": "eastus2",
        },
        {
            "workspace_name": "ces-eastus2-perf-synapse",
            "system": "ces",
            "environment": "perf",
            "region": "eastus2",
        },
        {
            "workspace_name": "ces-eastus2-prod-synapse",
            "system": "ces",
            "environment": "prod",
            "region": "eastus2",
        },
        {
            "workspace_name": "ces-eastus2-uat-synapse",
            "system": "ces",
            "environment": "uat",
            "region": "eastus2",
        },
    ]

    # =========================================================================
    # SYNAPSE CHECKSUM VERIFICATION (Multi-Environment)
    # =========================================================================

    # In-memory cache for live workspace discovery
    _workspace_cache: list[dict[str, str]] = []
    _workspace_cache_ts: float = 0.0
    _WORKSPACE_CACHE_TTL: float = 300.0  # 5 minutes

    # In-memory cache for AKS cluster names (avoids repeated full-table DISTINCT)
    _aks_cluster_cache: set[str] = set()
    _aks_cluster_cache_ts: float = 0.0
    _AKS_CLUSTER_CACHE_TTL: float = 300.0  # 5 minutes

    @staticmethod
    def _parse_workspace_metadata(name: str, location: str) -> dict[str, str]:
        """Infer *system*, *environment*, and *region* from a workspace name.

        Naming conventions observed in the estate:
          - ``attcc-<region>-<env>-synapse-wkspace``
          - ``attcc-<region>-<env>-bussynapse-wkspace``
          - ``ces-<region>-<env>-synapse``

        Falls back to ``"unknown"`` for fields that cannot be parsed.
        """
        known_systems = {"attcc", "ces"}
        known_envs = {"prod", "uat", "perf", "poc", "stage", "dev", "dr"}
        parts = name.lower().split("-")

        system = parts[0] if parts and parts[0] in known_systems else "unknown"
        region = location.lower().replace(" ", "") if location else (parts[1] if len(parts) > 1 else "unknown")

        # Environment is typically the 3rd segment
        environment = "unknown"
        for p in parts[2:]:
            if p in known_envs:
                environment = p
                break

        return {
            "workspace_name": name,
            "system": system,
            "environment": environment,
            "region": region,
        }

    async def _fetch_live_synapse_workspaces(self) -> list[dict[str, str]]:
        """Discover Synapse workspaces from Azure across monitored subscriptions.

        Uses ``SynapseManagementClient.workspaces.list()`` for each
        subscription returned by the admin resolver.  Results are cached for
        ``_WORKSPACE_CACHE_TTL`` seconds to avoid repeated Azure API calls.
        """
        now = time.monotonic()
        if self._workspace_cache and (now - self._workspace_cache_ts) < self._WORKSPACE_CACHE_TTL:
            return list(self._workspace_cache)

        subs = await self._get_subscriptions()
        if not subs:
            logger.warning("live_workspace_discovery_no_subscriptions")
            return []

        discovered: list[dict[str, str]] = []
        seen_names: set[str] = set()

        for sub in subs:
            try:
                synapse_client = SynapseManagementClient(self.credential, sub["id"])
                # workspaces.list() is a sync pager — run in executor to avoid
                # blocking the event loop.  Wrap with timeout to avoid hanging
                # on subscriptions with network restrictions.
                loop = asyncio.get_running_loop()
                workspaces = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda c=synapse_client: list(c.workspaces.list())),
                    timeout=self._AZURE_SDK_TIMEOUT_SECONDS,
                )
                for ws in workspaces:
                    ws_name: str = ws.name  # type: ignore[union-attr]
                    if ws_name in seen_names:
                        continue
                    seen_names.add(ws_name)
                    meta = self._parse_workspace_metadata(
                        ws_name,
                        getattr(ws, "location", "") or "",
                    )
                    meta["subscription_id"] = sub["id"]
                    meta["resource_group"] = getattr(ws, "resource_group", "") or ""
                    discovered.append(meta)
            except Exception:
                logger.warning(
                    "live_workspace_discovery_subscription_error",
                    subscription_id=sub["id"],
                    exc_info=True,
                )

        if discovered:
            # Update class-level cache
            ComplianceService._workspace_cache = discovered
            ComplianceService._workspace_cache_ts = now
            logger.info(
                "live_workspace_discovery_complete",
                count=len(discovered),
                subscriptions=len(subs),
            )
        else:
            logger.warning("live_workspace_discovery_empty_fallback_static")

        return discovered

    async def get_workspace_list(
        self,
        system: str | None = None,
        environment: str | None = None,
    ) -> list[dict[str, str]]:
        """Return Synapse workspaces, optionally filtered.

        Resolution order:
            1. Live discovery via Azure ``SynapseManagementClient``
               (cached for 5 min).
            2. Fall back to the static ``SYNAPSE_WORKSPACES`` registry when
               Azure is unreachable or returns no results.

        Args:
            system: ``"attcc"`` or ``"ces"`` filter.
            environment: ``"prod"``, ``"uat"``, etc.
        """
        try:
            ws = await self._fetch_live_synapse_workspaces()
        except Exception:
            logger.warning(
                "live_workspace_discovery_failed_fallback_static",
                exc_info=True,
            )
            ws = []

        if not ws:
            ws = list(self.SYNAPSE_WORKSPACES)

        ws = self._filter_workspaces_by_subscription_scope(
            ws,
            await self._resolve_scoped_subscription_ids(),
        )

        if system:
            ws = [w for w in ws if w.get("system", "").lower() == system.lower()]
        if environment:
            ws = [w for w in ws if w.get("environment", "").lower() == environment.lower()]
        return ws

    async def _get_latest_synapse_snapshot_dates(
        self,
        workspace_name: str,
        limit: int = 2,
    ) -> list[datetime]:
        if self.db is None:
            return []

        stmt = (
            select(SynapsePipelineChecksum.snapshot_date)
            .where(SynapsePipelineChecksum.workspace_name == workspace_name)
            .distinct()
            .order_by(desc(SynapsePipelineChecksum.snapshot_date))
            .limit(limit)
        )
        result = await self.db.execute(stmt)
        return [row[0] for row in result.all() if row and row[0] is not None]

    async def _load_synapse_snapshot_maps(
        self,
        workspace_name: str,
        snapshot_date: datetime,
    ) -> tuple[dict[str, str], dict[str, str]]:
        if self.db is None:
            return {}, {}

        stmt = (
            select(
                SynapsePipelineChecksum.pipeline_name,
                SynapsePipelineChecksum.checksum_sha256,
                SynapsePipelineChecksum.last_modified,
            )
            .where(SynapsePipelineChecksum.workspace_name == workspace_name)
            .where(SynapsePipelineChecksum.snapshot_date == snapshot_date)
        )
        result = await self.db.execute(stmt)

        checksum_map: dict[str, str] = {}
        last_modified_map: dict[str, str] = {}
        for pipeline_name, checksum_sha256, last_modified in result.all():
            checksum_map[pipeline_name] = checksum_sha256
            last_modified_map[pipeline_name] = last_modified.isoformat() if last_modified else ""

        return checksum_map, last_modified_map

    async def run_checksum_verification(self, workspace_name: str) -> dict[str, Any]:
        """Execute a Synapse checksum comparison for a single workspace.

        Verification prefers persisted checksum snapshots when at least two
        distinct snapshots already exist for the workspace. This keeps the UI
        operational for workspaces that are no longer reachable directly from
        the app server. When fewer than two snapshots exist, the method falls
        back to a live Synapse REST fetch to bootstrap comparison data.

        Args:
            workspace_name: Full Synapse workspace name (e.g.
                ``"attcc-eastus2-prod-synapse-wkspace"``).

        Returns:
            Dict with run metadata and full results list.
        """
        # Resolve workspace metadata from live discovery (with static fallback)
        all_ws = await self.get_workspace_list()
        ws_meta = next(
            (w for w in all_ws if w["workspace_name"] == workspace_name),
            None,
        )
        if ws_meta is None:
            raise ValueError(
                f"Unknown workspace '{workspace_name}'. Use GET /checksum/workspaces for the available list."
            )

        system = ws_meta["system"]
        environment = ws_meta["environment"]

        run_id = str(uuid.uuid4())
        execution_date = datetime.utcnow()

        logger.info(
            "checksum_verification_started",
            workspace=workspace_name,
            system=system,
            environment=environment,
            run_id=run_id,
        )

        try:
            # ------------------------------------------------------------------
            # Step 1: Prefer the latest two persisted snapshots for this workspace.
            # ------------------------------------------------------------------
            baseline_map: dict[str, str] = {}  # pipeline_name -> sha256
            present_map: dict[str, str] = {}  # pipeline_name -> sha256
            last_modified_map: dict[str, str] = {}  # pipeline_name -> last_publish_date
            baseline_snapshot_date: datetime | None = None
            present_snapshot_date: datetime | None = None
            latest_persisted_map: dict[str, str] = {}
            latest_persisted_last_modified_map: dict[str, str] = {}
            previous_persisted_map: dict[str, str] = {}
            snapshot_dates: list[datetime] = []

            if self.db is not None:
                snapshot_dates = await self._get_latest_synapse_snapshot_dates(workspace_name)
                if snapshot_dates:
                    present_snapshot_date = snapshot_dates[0]
                    latest_persisted_map, latest_persisted_last_modified_map = await self._load_synapse_snapshot_maps(
                        workspace_name,
                        present_snapshot_date,
                    )
                if len(snapshot_dates) >= 2:
                    baseline_snapshot_date = snapshot_dates[1]
                    previous_persisted_map, _ = await self._load_synapse_snapshot_maps(
                        workspace_name,
                        baseline_snapshot_date,
                    )
                    logger.info(
                        "checksum_snapshot_pair_loaded",
                        workspace=workspace_name,
                        present_date=present_snapshot_date.isoformat(),
                        baseline_date=baseline_snapshot_date.isoformat(),
                        pipeline_count=len(previous_persisted_map),
                    )
                elif len(snapshot_dates) == 1:
                    baseline_snapshot_date = snapshot_dates[0]
                    baseline_map = dict(latest_persisted_map)
                    logger.info(
                        "checksum_baseline_loaded",
                        workspace=workspace_name,
                        baseline_date=baseline_snapshot_date.isoformat(),
                        pipeline_count=len(baseline_map),
                    )
                else:
                    logger.warning(
                        "checksum_no_baseline_found",
                        workspace=workspace_name,
                    )

            # ------------------------------------------------------------------
            # Step 2: Fetch current pipeline definitions live when possible so
            # each successful verification persists a new snapshot. If live
            # access fails, fall back to the latest two persisted snapshots.
            # ------------------------------------------------------------------
            snapshot_date = datetime.utcnow()
            loop = asyncio.get_running_loop()

            try:
                # Use direct REST API calls to avoid Azure SDK
                # DeserializationError on complex ATTCC Synapse pipelines
                pipelines = await asyncio.wait_for(
                    loop.run_in_executor(
                        None,
                        self._list_pipelines_rest,
                        workspace_name,
                    ),
                    timeout=self._AZURE_SDK_TIMEOUT_SECONDS,
                )

                for raw_bytes, pipeline in pipelines:
                    p_name = pipeline.get("name", "unknown")
                    # Match bash: curl ... | tr -d '\r' => $() strips
                    # trailing newlines => echo adds one back.
                    checksum_input = raw_bytes.replace(b"\r", b"").rstrip(b"\n") + b"\n"
                    checksum = hashlib.sha256(checksum_input).hexdigest()
                    present_map[p_name] = checksum

                    last_pub = pipeline.get("properties", {}).get("lastPublishTime", "") or ""
                    last_modified_map[p_name] = last_pub

                    # Persist the current snapshot for future baselines.
                    if self.db is not None:
                        subscription_id = ws_meta.get("subscription_id", "")
                        self.db.add(
                            SynapsePipelineChecksum(
                                snapshot_date=snapshot_date,
                                subscription_id=subscription_id,
                                subscription_name=None,
                                workspace_name=workspace_name,
                                workspace_id=f"/subscriptions/{subscription_id}/workspaces/{workspace_name}",
                                pipeline_name=p_name,
                                checksum_sha256=checksum,
                                pipeline_definition=pipeline,
                                activities_count=len(pipeline.get("properties", {}).get("activities", [])),
                                last_modified=(self._parse_datetime(last_pub) if last_pub else None),
                            )
                        )

                if latest_persisted_map:
                    baseline_map = dict(latest_persisted_map)
                    baseline_snapshot_date = present_snapshot_date

                logger.info(
                    "checksum_present_collected",
                    workspace=workspace_name,
                    pipeline_count=len(present_map),
                    baseline_pipeline_count=len(baseline_map),
                )

            except TimeoutError:
                if len(snapshot_dates) >= 2:
                    present_map = dict(latest_persisted_map)
                    last_modified_map = dict(latest_persisted_last_modified_map)
                    baseline_map = dict(previous_persisted_map)
                    logger.warning(
                        "checksum_live_fetch_timeout_using_snapshots",
                        workspace=workspace_name,
                        timeout=self._AZURE_SDK_TIMEOUT_SECONDS,
                        present_date=present_snapshot_date.isoformat() if present_snapshot_date else None,
                        baseline_date=baseline_snapshot_date.isoformat() if baseline_snapshot_date else None,
                    )
                else:
                    error_msg = (
                        f"Timed out after {self._AZURE_SDK_TIMEOUT_SECONDS}s connecting to "
                        f"{workspace_name}. The workspace may be behind a private endpoint "
                        f"or firewall that blocks access from this server."
                    )
                    logger.error(
                        "checksum_pipeline_fetch_timeout",
                        workspace=workspace_name,
                        timeout=self._AZURE_SDK_TIMEOUT_SECONDS,
                    )
                    if self.db is not None:
                        failed_run = ChecksumRun(
                            run_id=run_id,
                            module_type="synapse",
                            system=system,
                            environment=environment,
                            workspace_name=workspace_name,
                            execution_date=execution_date,
                            total_pipelines=0,
                            passed=0,
                            failed=0,
                            status="failed",
                        )
                        self.db.add(failed_run)
                        try:
                            await self.db.commit()
                        except Exception:
                            await self.db.rollback()

                    return {
                        "run_id": run_id,
                        "module_type": "synapse",
                        "system": system,
                        "environment": environment,
                        "workspace_name": workspace_name,
                        "execution_date": execution_date.isoformat(),
                        "total": 0,
                        "passed": 0,
                        "failed": 0,
                        "status": "failed",
                        "error": error_msg,
                        "results": [],
                        "baseline_pipeline_count": len(baseline_map),
                        "present_pipeline_count": 0,
                    }

            except Exception as e:
                if len(snapshot_dates) >= 2:
                    present_map = dict(latest_persisted_map)
                    last_modified_map = dict(latest_persisted_last_modified_map)
                    baseline_map = dict(previous_persisted_map)
                    logger.warning(
                        "checksum_live_fetch_failed_using_snapshots",
                        workspace=workspace_name,
                        error=str(e),
                        present_date=present_snapshot_date.isoformat() if present_snapshot_date else None,
                        baseline_date=baseline_snapshot_date.isoformat() if baseline_snapshot_date else None,
                    )
                else:
                    logger.error(
                        "checksum_pipeline_fetch_failed",
                        workspace=workspace_name,
                        error=str(e),
                    )
                    # Instead of crashing, persist a failed run so the UI shows
                    # a meaningful result rather than a blank 500 error.
                    if self.db is not None:
                        failed_run = ChecksumRun(
                            run_id=run_id,
                            module_type="synapse",
                            system=system,
                            environment=environment,
                            workspace_name=workspace_name,
                            execution_date=execution_date,
                            total_pipelines=0,
                            passed=0,
                            failed=0,
                            status="failed",
                        )
                        self.db.add(failed_run)
                        try:
                            await self.db.commit()
                        except Exception:
                            await self.db.rollback()

                    return {
                        "run_id": run_id,
                        "module_type": "synapse",
                        "system": system,
                        "environment": environment,
                        "workspace_name": workspace_name,
                        "execution_date": execution_date.isoformat(),
                        "total": 0,
                        "passed": 0,
                        "failed": 0,
                        "status": "failed",
                        "error": f"Failed to fetch pipelines from {workspace_name}: {e}",
                        "results": [],
                        "baseline_pipeline_count": len(baseline_map),
                        "present_pipeline_count": 0,
                    }

            # ------------------------------------------------------------------
            # Step 3: Compare baseline vs present
            # ------------------------------------------------------------------
            all_pipeline_names = sorted(set(baseline_map.keys()) | set(present_map.keys()))

            results: list[dict[str, Any]] = []
            for p_name in all_pipeline_names:
                baseline_hash = baseline_map.get(p_name, "")
                present_hash = present_map.get(p_name, "")
                last_pub = last_modified_map.get(p_name, "")

                if not baseline_hash:
                    # New pipeline — no baseline to compare, mark as FAIL (new)
                    status = "FAIL"
                elif not present_hash:
                    # Pipeline removed — mark as FAIL (deleted)
                    status = "FAIL"
                elif baseline_hash == present_hash:
                    status = "PASS"
                else:
                    status = "FAIL"

                results.append(
                    {
                        "pipeline_name": p_name,
                        "yesterday_hash": baseline_hash,
                        "present_hash": present_hash,
                        "last_published_date": last_pub,
                        "result": status,
                    }
                )

        except Exception as e:
            logger.error(
                "checksum_verification_error",
                workspace=workspace_name,
                run_id=run_id,
                error=str(e),
            )
            # Persist a failed run record so the UI has visibility
            if self.db is not None:
                failed_run = ChecksumRun(
                    run_id=run_id,
                    module_type="synapse",
                    system=system,
                    environment=environment,
                    workspace_name=workspace_name,
                    execution_date=execution_date,
                    total_pipelines=0,
                    passed=0,
                    failed=0,
                    status="failed",
                )
                self.db.add(failed_run)
                try:
                    await self.db.commit()
                except Exception:
                    await self.db.rollback()
            return {
                "run_id": run_id,
                "module_type": "synapse",
                "system": system,
                "environment": environment,
                "workspace_name": workspace_name,
                "execution_date": execution_date.isoformat(),
                "total": 0,
                "passed": 0,
                "failed": 0,
                "status": "failed",
                "error": str(e),
                "results": [],
                "baseline_pipeline_count": len(baseline_map),
                "present_pipeline_count": len(present_map),
            }

        passed = sum(1 for r in results if r.get("result") == "PASS")
        failed = sum(1 for r in results if r.get("result") == "FAIL")

        # Persist run header and results (skip when DB is unavailable)
        if self.db is not None:
            run_record = ChecksumRun(
                run_id=run_id,
                module_type="synapse",
                system=system,
                environment=environment,
                workspace_name=workspace_name,
                execution_date=execution_date,
                total_pipelines=len(results),
                passed=passed,
                failed=failed,
                status="completed",
            )
            self.db.add(run_record)

            # Persist per-pipeline results
            for idx, r in enumerate(results, start=1):
                result_record = ChecksumResult(
                    run_id=run_id,
                    slno=idx,
                    pipeline_name=r.get("pipeline_name"),
                    yesterday_hash=r.get("yesterday_hash"),
                    present_hash=r.get("present_hash"),
                    last_published_date=r.get("last_published_date"),
                    result=r.get("result"),
                    details=r,
                )
                self.db.add(result_record)

            try:
                await self.db.commit()
            except Exception as e:
                await self.db.rollback()
                logger.error("checksum_persist_failed", run_id=run_id, error=str(e))
                raise
        else:
            logger.warning(
                "run_checksum_verification: database unavailable, skipping persistence",
                run_id=run_id,
            )

        logger.info(
            "checksum_verification_completed",
            workspace=workspace_name,
            run_id=run_id,
            total=len(results),
            passed=passed,
            failed=failed,
        )

        # Always return a dict, even if results is empty
        return {
            "run_id": run_id,
            "module_type": "synapse",
            "system": system,
            "environment": environment,
            "workspace_name": workspace_name,
            "execution_date": execution_date.isoformat(),
            "total": len(results),
            "passed": passed,
            "failed": failed,
            "results": results,
        }

    # ------------------------------------------------------------------
    # Batch: run ALL Synapse workspaces
    # ------------------------------------------------------------------

    async def run_all_checksum_verifications(
        self,
        system: str | None = None,
        environment: str | None = None,
    ) -> dict[str, Any]:
        """Run checksum verification for every workspace in the registry.

        Workspaces are processed **sequentially** to avoid overloading bash
        sub-processes and the shared DB session.  Per-workspace failures are
        caught and recorded so a single bad workspace does not abort the
        entire batch.

        Args:
            system: Optional ``"attcc"`` / ``"ces"`` filter.
            environment: Optional ``"prod"`` / ``"uat"`` / … filter.

        Returns:
            Aggregated dict with ``passed``/``failed`` totals and per-
            workspace summaries.
        """
        workspaces = await self.get_workspace_list(system=system, environment=environment)
        if not workspaces:
            raise ValueError("No workspaces found matching the given filters.")

        batch_run_id = str(uuid.uuid4())
        execution_date = datetime.utcnow()

        workspace_summaries: list[dict[str, Any]] = []
        total_passed = 0
        total_failed = 0
        total_errors = 0

        for ws in workspaces:
            ws_name = ws["workspace_name"]
            try:
                ws_result = await self.run_checksum_verification(ws_name)
                total_passed += ws_result.get("passed", 0)
                total_failed += ws_result.get("failed", 0)
                workspace_summaries.append(ws_result)
            except Exception as exc:
                total_errors += 1
                logger.warning(
                    "batch_verify_workspace_failed",
                    workspace=ws_name,
                    error=str(exc),
                )
                workspace_summaries.append(
                    {
                        "workspace_name": ws_name,
                        "system": ws["system"],
                        "environment": ws["environment"],
                        "total": 0,
                        "passed": 0,
                        "failed": 0,
                        "error": str(exc),
                        "results": [],
                    }
                )

        return {
            "run_id": batch_run_id,
            "module_type": "synapse",
            "mode": "batch",
            "execution_date": execution_date.isoformat(),
            "workspaces_processed": len(workspaces),
            "workspaces_failed": total_errors,
            "total": total_passed + total_failed,
            "passed": total_passed,
            "failed": total_failed,
            "workspace_results": workspace_summaries,
            "results": [],
        }

    async def run_aks_checksum(
        self,
        cluster_id: str,
        system: str,
        environment: str,
        namespaces: list[str] | None = None,
    ) -> dict[str, Any]:
        """Collect AKS pod checksums and detect drift for a cluster.

        Stores per-pod results (PASS / FAIL) using image checksum comparison
        between yesterday and today, mirroring the Synapse pipeline pattern.
        """
        if self.db is None:
            raise RuntimeError("Database unavailable for AKS checksum run")

        scoped_subscription_ids = await self._resolve_scoped_subscription_ids()
        if not self._cluster_matches_subscription_scope(cluster_id, scoped_subscription_ids):
            raise ValueError("Selected AKS cluster is outside the Admin monitored subscription scope")

        run_id = str(uuid.uuid4())
        execution_date = datetime.utcnow()

        from app.services.aks_operations_service import AKSOperationsService

        aks_service = AKSOperationsService(self.db)
        cluster_name = aks_service._extract_cluster_name(cluster_id)

        # 1. Collect today's checksums
        await self.collect_pod_checksums(cluster_id=cluster_id, namespaces=namespaces)

        # 2. Compare yesterday vs today pod image checksums
        today = datetime.utcnow().date()
        yesterday = today - timedelta(days=1)

        today_stmt = select(AKSPodChecksum).where(
            AKSPodChecksum.cluster_id == cluster_id,
            func.date(AKSPodChecksum.snapshot_date) == today,
        )
        yesterday_stmt = select(AKSPodChecksum).where(
            AKSPodChecksum.cluster_id == cluster_id,
            func.date(AKSPodChecksum.snapshot_date) == yesterday,
        )
        if namespaces:
            today_stmt = today_stmt.where(AKSPodChecksum.namespace.in_(namespaces))
            yesterday_stmt = yesterday_stmt.where(AKSPodChecksum.namespace.in_(namespaces))

        today_result = await self.db.execute(today_stmt)
        today_pods: dict[tuple[str, str | None, str | None], Any] = {}
        for p in today_result.scalars().all():
            ms_name = self._derive_microservice_key(p.owner_kind, p.owner_name) or p.pod_name
            key = (p.namespace, p.owner_kind, ms_name)
            today_pods[key] = p

        yesterday_result = await self.db.execute(yesterday_stmt)
        yesterday_pods: dict[tuple[str, str | None, str | None], Any] = {}
        for p in yesterday_result.scalars().all():
            ms_name = self._derive_microservice_key(p.owner_kind, p.owner_name) or p.pod_name
            key = (p.namespace, p.owner_kind, ms_name)
            yesterday_pods[key] = p

        # Detect drift + store per-pod results
        all_keys = set(today_pods.keys()) | set(yesterday_pods.keys())

        results_list: list[dict[str, Any]] = []
        passed = 0
        failed = 0

        for idx, key in enumerate(sorted(all_keys), start=1):
            ns, owner_kind, owner_name = key
            # Show Deployment for ReplicaSet-backed pods since we merged
            # across RS revisions via _derive_microservice_key.
            display_kind = "Deployment" if owner_kind == "ReplicaSet" else (owner_kind or "Pod")
            label = f"{ns}/{display_kind}/{owner_name}" if owner_kind else f"{ns}/{owner_name}"

            today_p = today_pods.get(key)
            yesterday_p = yesterday_pods.get(key)

            yesterday_img_hash = self._comparable_image_checksum(yesterday_p) if yesterday_p else None
            today_img_hash = self._comparable_image_checksum(today_p) if today_p else None

            if yesterday_img_hash and today_img_hash and yesterday_img_hash == today_img_hash:
                result_status = "PASS"
                passed += 1
            else:
                result_status = "FAIL"
                failed += 1

            self.db.add(
                ChecksumResult(
                    run_id=run_id,
                    slno=idx,
                    pipeline_name=label,
                    yesterday_hash=yesterday_img_hash,
                    present_hash=today_img_hash,
                    last_published_date=None,
                    result=result_status,
                )
            )

            results_list.append(
                {
                    "slno": idx,
                    "pipeline_name": label,
                    "yesterday_hash": yesterday_img_hash,
                    "present_hash": today_img_hash,
                    "result": result_status,
                }
            )

        total_pods = passed + failed

        run_record = ChecksumRun(
            run_id=run_id,
            module_type="aks",
            system=system.lower(),
            environment=environment.lower(),
            workspace_name=cluster_name,
            execution_date=execution_date,
            total_pipelines=total_pods,
            passed=passed,
            failed=failed,
            status="completed",
        )
        self.db.add(run_record)

        # Also persist AKSPodDrift rows for unacknowledged drift tracking
        detection_date = datetime.utcnow()
        for key in all_keys:
            ns, owner_kind, owner_name = key
            today_p = today_pods.get(key)
            yesterday_p = yesterday_pods.get(key)
            if yesterday_p and today_p:
                y_hash = self._comparable_image_checksum(yesterday_p)
                t_hash = self._comparable_image_checksum(today_p)
                if y_hash and t_hash and y_hash != t_hash:
                    drift = AKSPodDrift(
                        detection_date=detection_date,
                        cluster_id=cluster_id,
                        cluster_name=cluster_name,
                        namespace=ns,
                        pod_name=today_p.pod_name,
                        owner_kind=owner_kind,
                        owner_name=owner_name,
                        drift_type="container_image",
                        drift_category="container_image",
                        previous_value=yesterday_p.container_images,
                        current_value=today_p.container_images,
                        previous_checksum=y_hash,
                        current_checksum=t_hash,
                        severity="high",
                    )
                    self.db.add(drift)

        await self.db.commit()

        return {
            "run_id": run_id,
            "module_type": "aks",
            "system": system.lower(),
            "environment": environment.lower(),
            "workspace_name": cluster_name,
            "execution_date": execution_date.isoformat(),
            "total": total_pods,
            "passed": passed,
            "failed": failed,
            "results": results_list,
        }

    # ------------------------------------------------------------------
    # Batch: run ALL known AKS clusters
    # ------------------------------------------------------------------

    async def run_all_aks_checksums(
        self,
        system: str = "attcc",
        environment: str = "prod",
        namespaces: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run AKS checksum verification for every cluster with existing data.

        Discovers clusters by querying distinct ``cluster_id`` values from
        the ``AKSPodChecksum`` table.  Each cluster is processed
        sequentially so we don't overwhelm the shared DB session.

        Returns:
            Aggregated dict with ``passed``/``failed`` totals and per-
            cluster summaries.
        """
        if self.db is None:
            raise RuntimeError("Database unavailable for AKS batch checksum run")

        result = await self.db.execute(select(AKSPodChecksum.cluster_id).distinct())
        scoped_subscription_ids = await self._resolve_scoped_subscription_ids()
        cluster_ids = [
            row[0]
            for row in result.fetchall()
            if row[0] and self._cluster_matches_subscription_scope(row[0], scoped_subscription_ids)
        ]

        batch_run_id = str(uuid.uuid4())
        execution_date = datetime.utcnow()

        if not cluster_ids:
            logger.info("run_all_aks_checksums: no known clusters in DB")
            return {
                "run_id": batch_run_id,
                "module_type": "aks",
                "mode": "batch",
                "execution_date": execution_date.isoformat(),
                "clusters_processed": 0,
                "total": 0,
                "passed": 0,
                "failed": 0,
                "message": ("No known AKS clusters found. Run 'Collect Checksums' first to discover clusters."),
                "results": [],
            }

        cluster_summaries: list[dict[str, Any]] = []
        total_passed = 0
        total_failed = 0
        total_errors = 0

        for cid in cluster_ids:
            try:
                cs_result = await self.run_aks_checksum(
                    cluster_id=cid,
                    system=system,
                    environment=environment,
                    namespaces=namespaces,
                )
                total_passed += cs_result.get("passed", 0)
                total_failed += cs_result.get("failed", 0)
                cluster_summaries.append(cs_result)
            except Exception as exc:
                total_errors += 1
                logger.warning(
                    "batch_verify_cluster_failed",
                    cluster_id=cid,
                    error=str(exc),
                )
                cluster_summaries.append(
                    {
                        "cluster_id": cid,
                        "total": 0,
                        "passed": 0,
                        "failed": 0,
                        "error": str(exc),
                        "results": [],
                    }
                )

        return {
            "run_id": batch_run_id,
            "module_type": "aks",
            "mode": "batch",
            "execution_date": execution_date.isoformat(),
            "clusters_processed": len(cluster_ids),
            "clusters_failed": total_errors,
            "total": total_passed + total_failed,
            "passed": total_passed,
            "failed": total_failed,
            "cluster_results": cluster_summaries,
            "results": [],
        }

    async def list_checksum_schedules(self) -> list[dict[str, Any]]:
        """List configured checksum schedules."""
        if self.db is None:
            return []

        result = await self.db.execute(
            select(ChecksumScheduleConfig).order_by(ChecksumScheduleConfig.created_at.desc())
        )
        schedules = result.scalars().all()
        scoped_subscription_ids = await self._resolve_scoped_subscription_ids()
        allowed_workspaces = await self._get_allowed_synapse_workspace_names()
        schedules = [
            schedule
            for schedule in schedules
            if (
                (schedule.module_type == "synapse" and schedule.workspace_name in allowed_workspaces)
                or (
                    schedule.module_type == "aks"
                    and self._cluster_matches_subscription_scope(schedule.cluster_id, scoped_subscription_ids)
                )
            )
        ]
        return [self._format_checksum_schedule(s) for s in schedules]

    async def create_checksum_schedule(
        self,
        payload: dict[str, Any],
        created_by: str,
    ) -> dict[str, Any]:
        """Create a new checksum schedule configuration."""
        module_type = payload.get("module_type", "").lower()
        if module_type not in ("synapse", "aks"):
            raise ValueError("module_type must be 'synapse' or 'aks'")

        if module_type == "synapse" and not payload.get("workspace_name"):
            raise ValueError("workspace_name is required for synapse schedules")
        if module_type == "aks" and not payload.get("cluster_id"):
            raise ValueError("cluster_id is required for aks schedules")

        await self._validate_checksum_schedule_target(
            module_type=module_type,
            workspace_name=payload.get("workspace_name"),
            cluster_id=payload.get("cluster_id"),
        )

        schedule = ChecksumScheduleConfig(
            name=payload["name"],
            description=payload.get("description"),
            created_by=created_by,
            module_type=module_type,
            system=(payload.get("system") or "").lower() or None,
            environment=(payload.get("environment") or "").lower() or None,
            workspace_name=payload.get("workspace_name"),
            cluster_id=payload.get("cluster_id"),
            cluster_name=payload.get("cluster_name"),
            namespaces=payload.get("namespaces") or [],
            schedule_type=payload.get("schedule_type", "interval"),
            interval_hours=int(payload.get("interval_hours", 24)),
            cron_expression=payload.get("cron_expression"),
            timezone=payload.get("timezone", "UTC"),
            notification_emails=payload.get("notification_emails") or [],
            is_enabled=bool(payload.get("is_enabled", True)),
        )
        schedule.next_run_at = self.compute_next_run_at(schedule)

        self.db.add(schedule)
        await self.db.commit()
        await self.db.refresh(schedule)
        return self._format_checksum_schedule(schedule)

    async def toggle_checksum_schedule(
        self,
        schedule_id: int,
        toggled_by: str,
    ) -> dict[str, Any]:
        """Toggle a schedule's is_enabled flag."""
        if self.db is None:
            raise RuntimeError("Database unavailable")

        schedule = await self._get_scoped_checksum_schedule_record(schedule_id)

        schedule.is_enabled = not schedule.is_enabled
        schedule.updated_by = toggled_by
        schedule.next_run_at = self.compute_next_run_at(schedule)
        await self.db.commit()
        await self.db.refresh(schedule)

        return {
            "success": True,
            "schedule_id": str(schedule_id),
            "is_enabled": schedule.is_enabled,
            "next_run_at": ((schedule.next_run_at.isoformat() + "Z") if schedule.next_run_at else None),
            "message": f"Schedule {'enabled' if schedule.is_enabled else 'disabled'} successfully",
        }

    async def update_checksum_schedule(
        self,
        schedule_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Update a checksum schedule configuration."""
        if self.db is None:
            raise RuntimeError("Database unavailable for schedule update")

        schedule = await self._get_scoped_checksum_schedule_record(schedule_id)

        module_type = (payload.get("module_type") or schedule.module_type or "").lower()
        workspace_name = payload.get("workspace_name", schedule.workspace_name)
        cluster_id = payload.get("cluster_id", schedule.cluster_id)
        await self._validate_checksum_schedule_target(
            module_type=module_type,
            workspace_name=workspace_name,
            cluster_id=cluster_id,
        )

        for field in (
            "name",
            "description",
            "module_type",
            "system",
            "environment",
            "workspace_name",
            "cluster_id",
            "cluster_name",
            "namespaces",
            "schedule_type",
            "interval_hours",
            "cron_expression",
            "timezone",
            "notification_emails",
            "is_enabled",
        ):
            if field in payload and payload[field] is not None:
                setattr(schedule, field, payload[field])

        schedule.next_run_at = self.compute_next_run_at(schedule)
        await self.db.commit()
        await self.db.refresh(schedule)
        return self._format_checksum_schedule(schedule)

    async def run_checksum_schedule(self, schedule_id: int) -> dict[str, Any]:
        """Run a configured schedule immediately."""
        if self.db is None:
            raise RuntimeError("Database unavailable for schedule run")

        schedule = await self._get_scoped_checksum_schedule_record(schedule_id)

        run = await self._execute_checksum_schedule(schedule)
        schedule.last_run_at = datetime.utcnow()
        schedule.next_run_at = self.compute_next_run_at(schedule)
        await self.db.commit()

        return run

    async def _execute_checksum_schedule(self, schedule: "ChecksumScheduleConfig") -> dict[str, Any]:
        if schedule.module_type == "synapse":
            run = await self.run_checksum_verification(schedule.workspace_name)
        else:
            run = await self.run_aks_checksum(
                cluster_id=schedule.cluster_id,
                system=schedule.system or "attcc",
                environment=schedule.environment or "prod",
                namespaces=schedule.namespaces or None,
            )

        if schedule.notification_emails:
            await self.send_checksum_report(
                run_id=run["run_id"],
                recipient_emails=schedule.notification_emails,
            )
        return run

    async def send_checksum_report(
        self,
        run_id: str,
        recipient_emails: list[str],
    ) -> dict[str, Any]:
        """Send checksum report email for a run.

        Uses the same ``_build_checksum_html_report`` template as the
        direct ``send_checksum_email`` endpoint so both paths produce
        identical HTML output.
        """
        if self.db is None:
            raise RuntimeError("Database unavailable for email reporting")

        result = await self.db.execute(select(ChecksumRun).where(ChecksumRun.run_id == run_id))
        run = result.scalar_one_or_none()
        if run is None:
            raise ValueError("Run not found")

        results = await self.get_checksum_results(run_id=run_id, days=30)

        module_type = run.module_type or "synapse"
        workspace_name = run.workspace_name or "unknown"
        exec_date = run.execution_date.isoformat() if run.execution_date else "N/A"
        passed = run.passed or 0
        failed = run.failed or 0
        type_label = "AKS Checksum" if module_type == "aks" else "Synapse Checksum"

        html_body = self._build_checksum_html_report(
            results,
            workspace_name,
            run_id,
            exec_date,
            module_type=module_type,
        )

        subject = (
            f"[{type_label}] {workspace_name} — {passed} PASS / {failed} FAIL — "
            f"{exec_date[:10] if len(exec_date) > 10 else exec_date}"
        )

        email_service = EmailNotificationService(self.db)
        send_results = await email_service._send_email_batch(
            recipient_emails=recipient_emails,
            subject=subject,
            html_body=html_body,
            alert_type="checksum_verification",
            alert_id=0,
        )

        return {
            "run_id": run_id,
            "recipients": len(recipient_emails),
            "success": sum(1 for r in send_results if r["status"] == "sent"),
        }

    def compute_next_run_at(
        self,
        schedule: "ChecksumScheduleConfig",
        from_time: datetime | None = None,
    ) -> datetime | None:
        """Compute next run timestamp for a schedule."""
        if not schedule.is_enabled:
            return None

        now = from_time or datetime.now(UTC)
        if schedule.schedule_type == "cron" and schedule.cron_expression:
            tz = ZoneInfo(schedule.timezone or "UTC")
            trigger = CronTrigger.from_crontab(schedule.cron_expression, timezone=tz)
            next_fire = trigger.get_next_fire_time(None, now)
            # Store as naive UTC to match the DB column type
            if next_fire is not None and next_fire.tzinfo is not None:
                next_fire = next_fire.astimezone(UTC).replace(tzinfo=None)
            return next_fire

        interval_hours = schedule.interval_hours or 24
        # Return naive UTC
        now_naive = now.replace(tzinfo=None) if now.tzinfo else now
        return now_naive + timedelta(hours=interval_hours)

    def _format_checksum_schedule(self, schedule: "ChecksumScheduleConfig") -> dict[str, Any]:
        return {
            "id": schedule.id,
            "name": schedule.name,
            "description": schedule.description,
            "module_type": schedule.module_type,
            "system": schedule.system,
            "environment": schedule.environment,
            "workspace_name": schedule.workspace_name,
            "cluster_id": schedule.cluster_id,
            "cluster_name": schedule.cluster_name,
            "namespaces": schedule.namespaces or [],
            "schedule_type": schedule.schedule_type,
            "interval_hours": schedule.interval_hours,
            "cron_expression": schedule.cron_expression,
            "timezone": schedule.timezone,
            "notification_emails": schedule.notification_emails or [],
            "is_enabled": schedule.is_enabled,
            "last_run_at": ((schedule.last_run_at.isoformat() + "Z") if schedule.last_run_at else None),
            "next_run_at": ((schedule.next_run_at.isoformat() + "Z") if schedule.next_run_at else None),
            "created_at": ((schedule.created_at.isoformat() + "Z") if schedule.created_at else None),
            "created_by": schedule.created_by,
        }

    # ------ query helpers ---------------------------------------------------

    async def get_checksum_runs(
        self,
        system: str | None = None,
        environment: str | None = None,
        workspace_name: str | None = None,
        days: int = 30,
        module_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return recent checksum runs with summary info."""
        if self.db is None:
            logger.warning("get_checksum_runs: database unavailable, returning empty list")
            return []
        since = datetime.utcnow() - timedelta(days=days)
        stmt = select(ChecksumRun).where(ChecksumRun.execution_date >= since).order_by(desc(ChecksumRun.execution_date))
        if module_type:
            stmt = stmt.where(ChecksumRun.module_type == module_type.lower())
        if system:
            stmt = stmt.where(ChecksumRun.system == system.lower())
        if environment:
            stmt = stmt.where(ChecksumRun.environment == environment.lower())
        if workspace_name:
            stmt = stmt.where(ChecksumRun.workspace_name == workspace_name)

        result = await self.db.execute(stmt)
        rows = result.scalars().all()

        allowed_workspaces = await self._get_allowed_synapse_workspace_names()
        allowed_aks_clusters = await self._get_allowed_aks_cluster_names()
        rows = [
            row
            for row in rows
            if (
                (row.module_type == "synapse" and row.workspace_name in allowed_workspaces)
                or (row.module_type == "aks" and row.workspace_name in allowed_aks_clusters)
            )
        ]

        return [
            {
                "run_id": r.run_id,
                "module_type": r.module_type,
                "system": r.system,
                "environment": r.environment,
                "workspace_name": r.workspace_name,
                "execution_date": (r.execution_date.isoformat() if r.execution_date else None),
                "total_pipelines": r.total_pipelines,
                "passed": r.passed,
                "failed": r.failed,
                "status": r.status,
            }
            for r in rows
        ]

    async def get_checksum_results(
        self,
        run_id: str | None = None,
        system: str | None = None,
        environment: str | None = None,
        workspace_name: str | None = None,
        status_filter: str | None = None,
        days: int = 30,
        module_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Query per-pipeline checksum results with flexible filters."""
        if self.db is None:
            logger.warning("get_checksum_results: database unavailable, returning empty list")
            return []
        since = datetime.utcnow() - timedelta(days=days)
        stmt = (
            select(ChecksumResult, ChecksumRun)
            .join(ChecksumRun, ChecksumResult.run_id == ChecksumRun.run_id)
            .where(ChecksumRun.execution_date >= since)
            .order_by(desc(ChecksumRun.execution_date), ChecksumResult.slno)
        )
        if module_type:
            stmt = stmt.where(ChecksumRun.module_type == module_type.lower())
        if run_id:
            stmt = stmt.where(ChecksumResult.run_id == run_id)
        if system:
            stmt = stmt.where(ChecksumRun.system == system.lower())
        if environment:
            stmt = stmt.where(ChecksumRun.environment == environment.lower())
        if workspace_name:
            stmt = stmt.where(ChecksumRun.workspace_name == workspace_name)
        if status_filter:
            stmt = stmt.where(ChecksumResult.result == status_filter.upper())

        result = await self.db.execute(stmt)
        rows = result.all()

        allowed_workspaces = await self._get_allowed_synapse_workspace_names()
        allowed_aks_clusters = await self._get_allowed_aks_cluster_names()
        rows = [
            row
            for row in rows
            if (
                (row[1].module_type == "synapse" and row[1].workspace_name in allowed_workspaces)
                or (row[1].module_type == "aks" and row[1].workspace_name in allowed_aks_clusters)
            )
        ]

        return [
            {
                "id": cr.id,
                "run_id": cr.run_id,
                "slno": cr.slno,
                "pipeline_name": cr.pipeline_name,
                "yesterday_hash": cr.yesterday_hash,
                "present_hash": cr.present_hash,
                "last_published_date": cr.last_published_date,
                "result": cr.result,
                "workspace_name": run.workspace_name,
                "system": run.system,
                "environment": run.environment,
                "module_type": run.module_type,
                "execution_date": (run.execution_date.isoformat() if run.execution_date else None),
            }
            for cr, run in rows
        ]

    async def get_checksum_metrics(self, days: int = 30, module_type: str | None = None) -> dict[str, Any]:
        """Aggregate pass/fail counts by date, system, and workspace.

        Only the **latest** run per workspace per day is counted so that
        re-runs on the same day don't inflate the totals or graph bars.
        """
        if self.db is None:
            logger.warning("get_checksum_metrics: database unavailable, returning empty metrics")
            return {
                "daily": [],
                "summary": {
                    "attcc": {"pass": 0, "fail": 0, "total": 0},
                    "ces": {"pass": 0, "fail": 0, "total": 0},
                },
            }
        since = datetime.utcnow() - timedelta(days=days)

        # Fetch all runs in the window — we'll deduplicate in Python to
        # keep only the latest run per (workspace_name, date).
        stmt = (
            select(
                func.date(ChecksumRun.execution_date).label("exec_date"),
                ChecksumRun.execution_date,
                ChecksumRun.module_type,
                ChecksumRun.system,
                ChecksumRun.workspace_name,
                ChecksumRun.passed,
                ChecksumRun.failed,
            )
            .where(ChecksumRun.execution_date >= since)
            .order_by(ChecksumRun.execution_date.desc())
        )
        if module_type:
            stmt = stmt.where(ChecksumRun.module_type == module_type.lower())
        result = await self.db.execute(stmt)
        rows = result.all()

        allowed_workspaces = await self._get_allowed_synapse_workspace_names()
        allowed_aks_clusters = await self._get_allowed_aks_cluster_names()
        rows = [
            row
            for row in rows
            if (
                (row.module_type == "synapse" and row.workspace_name in allowed_workspaces)
                or (row.module_type == "aks" and row.workspace_name in allowed_aks_clusters)
            )
        ]

        # Keep only the latest run per workspace per day
        seen: set[tuple[str, str]] = set()
        latest_rows: list[Any] = []
        for row in rows:
            key = (str(row.exec_date), row.workspace_name)
            if key not in seen:
                seen.add(key)
                latest_rows.append(row)

        daily_map: dict[str, dict[str, Any]] = {}
        summary: dict[str, dict[str, int]] = {
            "attcc": {"pass": 0, "fail": 0, "total": 0},
            "ces": {"pass": 0, "fail": 0, "total": 0},
        }

        for row in latest_rows:
            date_str = str(row.exec_date)
            if date_str not in daily_map:
                daily_map[date_str] = {
                    "date": date_str,
                    "attcc_pass": 0,
                    "attcc_fail": 0,
                    "ces_pass": 0,
                    "ces_fail": 0,
                }
            pass_cnt = int(row.passed or 0)
            fail_cnt = int(row.failed or 0)
            daily_map[date_str][f"{row.system}_pass"] += pass_cnt
            daily_map[date_str][f"{row.system}_fail"] += fail_cnt

            if row.system in summary:
                summary[row.system]["pass"] += pass_cnt
                summary[row.system]["fail"] += fail_cnt
                summary[row.system]["total"] += pass_cnt + fail_cnt

        return {
            "daily": sorted(daily_map.values(), key=lambda d: d["date"]),
            "summary": summary,
        }

    async def generate_checksum_csv(self, run_id: str) -> bytes:
        """Generate a CSV file for a specific verification run."""
        if self.db is None:
            raise ValueError("Database unavailable — cannot generate CSV without stored results.")
        results = await self.get_checksum_results(run_id=run_id, days=365)
        if not results:
            raise ValueError(f"No results found for run_id={run_id}")

        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=[
                "slno",
                "pipeline_name",
                "yesterday_hash",
                "present_hash",
                "last_published_date",
                "result",
                "workspace_name",
                "system",
                "environment",
                "execution_date",
            ],
        )
        writer.writeheader()
        for r in results:
            writer.writerow(
                {
                    "slno": r["slno"],
                    "pipeline_name": r["pipeline_name"],
                    "yesterday_hash": r["yesterday_hash"],
                    "present_hash": r["present_hash"],
                    "last_published_date": r["last_published_date"],
                    "result": r["result"],
                    "workspace_name": r["workspace_name"],
                    "system": r["system"],
                    "environment": r["environment"],
                    "execution_date": r["execution_date"],
                }
            )

        return output.getvalue().encode("utf-8")

    # ------ HTML report (matches shell-script theme) ------------------------

    def _build_checksum_html_report(
        self,
        results: list[dict[str, Any]],
        workspace_name: str,
        run_id: str,
        exec_date: str,
        module_type: str = "synapse",
    ) -> str:
        """Build a professional HTML checksum report for email delivery.

        Produces an enterprise-grade email with a dark header bar,
        summary statistics cards, and a well-formatted table with
        appropriate column widths for each module type.
        """
        passed = sum(1 for r in results if r["result"] == "PASS")
        failed = sum(1 for r in results if r["result"] == "FAIL")
        total = len(results)
        is_aks = module_type.lower() == "aks"
        type_label = "AKS" if is_aks else "Synapse"
        name_col = "Pod Name" if is_aks else "Pipeline Name"

        # ── colour tokens ────────────────────────────────────────────
        hdr_bg = "#0568ae"  # AT&T blue
        hdr_fg = "#ffffff"
        pass_clr = "#16a34a"
        fail_clr = "#dc2626"
        border = "#d1d5db"
        th_bg = "#f3f4f6"
        stripe_bg = "#f9fafb"
        body_fg = "#1f2937"

        # ── column widths (AKS has no "Last Published" column) ───────
        if is_aks:
            col_widths = "4%|36%|25%|25%|10%"
        else:
            col_widths = "4%|30%|22%|22%|12%|10%"
        widths = col_widths.split("|")

        # ── shared cell styles ───────────────────────────────────────
        _td = f"border:1px solid {border};padding:8px 10px;text-align:left;font-size:13px;color:{body_fg};"
        _td_mono = f"{_td}font-family:'Courier New',Courier,monospace;font-size:11px;word-break:break-all;"
        _th = (
            f"border:1px solid {border};padding:10px;text-align:left;"
            f"font-size:13px;font-weight:600;background:{th_bg};color:{body_fg};"
        )

        # ── build table rows ────────────────────────────────────────
        rows_html = ""
        for idx, r in enumerate(results):
            result_val = r["result"]
            clr = pass_clr if result_val == "PASS" else fail_clr
            bg = stripe_bg if idx % 2 == 1 else "#ffffff"
            rows_html += (
                f"<tr style='background:{bg};'>"
                f"<td style='{_td}text-align:center;'>{r['slno']}</td>"
                f"<td style='{_td}'>{r['pipeline_name']}</td>"
                f"<td style='{_td_mono}'>{r.get('yesterday_hash') or 'N/A'}</td>"
                f"<td style='{_td_mono}'>{r.get('present_hash') or 'N/A'}</td>"
            )
            if not is_aks:
                rows_html += f"<td style='{_td}text-align:center;'>{r.get('last_published_date') or 'N/A'}</td>"
            rows_html += (
                f"<td style='{_td}text-align:center;'>"
                f"<span style='color:{clr};font-weight:700;'>{result_val}</span></td>"
                f"</tr>\n"
            )

        # ── col group ────────────────────────────────────────────────
        col_group = "".join(f"<col style='width:{w};'/>" for w in widths)

        # ── "Last Published" header ──────────────────────────────────
        last_pub_th = f"<th style='{_th}text-align:center;'>Last Published</th>" if not is_aks else ""

        # ── summary card helper ──────────────────────────────────────
        def _card(label: str, value: int | str, color: str = body_fg) -> str:
            return (
                f"<td style='text-align:center;padding:12px 8px;'>"
                f"<div style='font-size:22px;font-weight:700;color:{color};'>{value}</div>"
                f"<div style='font-size:11px;color:#6b7280;margin-top:2px;'>{label}</div>"
                f"</td>"
            )

        # ── final HTML ───────────────────────────────────────────────
        return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="utf-8"/></head>
<body style="margin:0;padding:0;background:#f3f4f6;font-family:'Segoe UI',Arial,Helvetica,sans-serif;color:{body_fg};">
<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;background:#f3f4f6;">
<tr><td style="padding:24px 16px;">
<table role="presentation" cellpadding="0" cellspacing="0" style="max-width:960px;width:100%;margin:0 auto;background:#ffffff;border-radius:8px;overflow:hidden;border:1px solid {border};">

  <!-- Header bar -->
  <tr><td style="background:{hdr_bg};padding:20px 28px;">
    <h1 style="margin:0;font-size:20px;font-weight:700;color:{hdr_fg};">{type_label} &mdash; Checksum Verification Report</h1>
    <p style="margin:6px 0 0;font-size:13px;color:rgba(255,255,255,0.85);">{workspace_name} &nbsp;&bull;&nbsp; {exec_date[:10] if len(exec_date) > 10 else exec_date}</p>
  </td></tr>

  <!-- AT&T proprietary notice -->
  <tr><td style="padding:12px 28px 0;font-size:11px;color:#6b7280;">
    AT&amp;T Proprietary (Restricted) &mdash; Not for use or disclosure outside the AT&amp;T companies except under written agreement.
  </td></tr>

  <!-- Summary cards -->
  <tr><td style="padding:16px 28px;">
    <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;border:1px solid {border};border-radius:6px;border-collapse:separate;">
      <tr>
        {_card("Total", total)}
        {_card("Passed", passed, pass_clr)}
        {_card("Failed", failed, fail_clr if failed else body_fg)}
      </tr>
    </table>
  </td></tr>

  <!-- FAIL banner (only when failures exist) -->
  {"<tr><td style='padding:0 28px 8px;'><div style='background:#fef2f2;border:1px solid #fecaca;border-radius:4px;padding:8px 14px;font-size:12px;color:" + fail_clr + ";font-weight:600;'>" + str(failed) + " item(s) failed checksum verification</div></td></tr>" if failed else ""}

  <!-- Results table -->
  <tr><td style="padding:8px 28px 24px;">
    <table cellpadding="0" cellspacing="0" style="width:100%;border-collapse:collapse;border:1px solid {border};">
      <colgroup>{col_group}</colgroup>
      <thead>
        <tr>
          <th style="{_th}text-align:center;">Slno</th>
          <th style="{_th}">{name_col}</th>
          <th style="{_th}">Yesterday Hash Value</th>
          <th style="{_th}">Present Hash Value</th>
          {last_pub_th}
          <th style="{_th}text-align:center;">Result</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </td></tr>

  <!-- Run metadata -->
  <tr><td style="padding:0 28px 16px;font-size:12px;color:#6b7280;">
    <b>Run ID:</b> {run_id} &nbsp;&bull;&nbsp; <b>Date:</b> {exec_date}
  </td></tr>

  <!-- Footer -->
  <tr><td style="background:#f9fafb;padding:14px 28px;border-top:1px solid {border};font-size:11px;color:#6b7280;text-align:center;">
    Generated by ATTCC Compliance Automation &nbsp;&bull;&nbsp; AT&amp;T Proprietary (Restricted)
  </td></tr>

</table>
</td></tr>
</table>
</body>
</html>"""

    async def send_checksum_email(
        self,
        run_id: str,
        recipient_email: str,
    ) -> dict[str, Any]:
        """Build an HTML report for a verification run and email it.

        Uses the existing ``EmailNotificationService`` SMTP infrastructure.
        """
        if self.db is None:
            raise ValueError("Database unavailable — cannot send email without stored results.")

        results = await self.get_checksum_results(run_id=run_id, days=365)
        if not results:
            raise ValueError(f"No results found for run_id={run_id}")

        module_type = results[0].get("module_type", "synapse")
        workspace_name = results[0].get("workspace_name", "unknown")
        exec_date = results[0].get("execution_date", "N/A")
        passed = sum(1 for r in results if r["result"] == "PASS")
        failed = sum(1 for r in results if r["result"] == "FAIL")

        type_label = "AKS Checksum" if module_type == "aks" else "Synapse Checksum"

        html_body = self._build_checksum_html_report(
            results,
            workspace_name,
            run_id,
            exec_date,
            module_type=module_type,
        )

        subject = (
            f"[{type_label}] {workspace_name} — {passed} PASS / {failed} FAIL — "
            f"{exec_date[:10] if len(exec_date) > 10 else exec_date}"
        )

        email_service = EmailNotificationService(self.db)
        send_results = await email_service._send_email_batch(
            recipient_emails=[recipient_email],
            subject=subject,
            html_body=html_body,
            alert_type="checksum_verification",
            alert_id=0,
        )

        status = send_results[0]["status"] if send_results else "unknown"
        error = send_results[0].get("error") if send_results else None
        if status == "failed":
            raise RuntimeError(error or "Email delivery failed")

        return {
            "run_id": run_id,
            "recipient": recipient_email,
            "status": status,
            "error": error,
        }

    # =========================================================================
    # HELPER METHODS
    # =========================================================================

    async def _get_subscriptions(
        self,
        subscription_ids: list[str] | None = None,
    ) -> list[dict[str, str]]:
        """Get list of subscriptions."""
        # Use provided subscription IDs or fall back to admin-enabled subscriptions
        subs = subscription_ids or await get_scoped_subscription_ids()
        if not subs:
            logger.warning("No subscriptions configured. Set SUBSCRIPTION_IDS environment variable.")
            return []

        return [{"id": sid, "name": sid} for sid in subs]

    def _list_pipelines_rest(
        self,
        workspace_name: str,
    ) -> list[tuple[bytes, dict]]:
        """Fetch every pipeline definition from a Synapse workspace.

        Mirrors the bash checksum script logic:
        1. List pipeline **names** via the paginated ``/pipelines`` endpoint.
        2. ``GET /pipelines/{name}?api-version=2020-12-01`` for each pipeline
           to obtain the exact same JSON payload that the bash script feeds
           into ``sha256sum``.

        Returns a list of ``(raw_bytes, parsed_dict)`` tuples so callers can
        compute checksums on the raw response bytes (matching bash) while
        still having the parsed dict for metadata extraction.
        """
        token = self.credential.get_token("https://dev.azuresynapse.net/.default")
        headers = {"Authorization": f"Bearer {token.token}"}
        base_url = f"https://{workspace_name}.dev.azuresynapse.net"
        timeout = self._AZURE_SDK_TIMEOUT_SECONDS

        # Step 1: collect pipeline names from the paginated list endpoint
        names: list[str] = []
        url: str | None = f"{base_url}/pipelines?api-version=2020-12-01"
        while url:
            resp = httpx.get(url, headers=headers, timeout=timeout, verify=False)
            resp.raise_for_status()
            data = resp.json()
            for p in data.get("value", []):
                names.append(p["name"])
            url = data.get("nextLink") or None

        # Step 2: fetch each pipeline individually (same call as bash script)
        results: list[tuple[bytes, dict]] = []
        for name in names:
            encoded = urllib.parse.quote(name, safe="")
            resp = httpx.get(
                f"{base_url}/pipelines/{encoded}?api-version=2020-12-01",
                headers=headers,
                timeout=timeout,
                verify=False,
            )
            resp.raise_for_status()
            results.append((resp.content, resp.json()))

        return results

    def _parse_datetime(self, value: str | None) -> datetime | None:
        """Parse datetime string, returning a naive-UTC datetime.

        The database columns use ``TIMESTAMP WITHOUT TIME ZONE`` and
        ``snapshot_date`` is generated via ``datetime.utcnow()`` (naive).
        Returning a naive datetime here avoids asyncpg errors when both
        values appear in the same INSERT.
        """
        if not value:
            return None
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            # Strip timezone to stay consistent with naive snapshot_date
            return dt.replace(tzinfo=None)
        except Exception:
            return None

    def _compute_diff(self, old: dict | None, new: dict | None) -> dict:
        """Compute structured diff between two dictionaries."""
        if old is None:
            return {"type": "added", "new": new}
        if new is None:
            return {"type": "deleted", "old": old}

        added = [k for k in new if k not in old]
        removed = [k for k in old if k not in new]
        changed = {
            k: {"old_value": old[k], "new_value": new[k]}
            for k in old
            if k in new
            and json.dumps(old[k], sort_keys=True, default=str) != json.dumps(new[k], sort_keys=True, default=str)
        }
        return {
            "added": added,
            "removed": removed,
            "changed": changed,
        }

    def _compute_checksum(self, data: Any) -> str:
        """Compute SHA256 checksum of data."""
        json_str = json.dumps(data, sort_keys=True, default=str)
        return hashlib.sha256(json_str.encode()).hexdigest()

    def _comparable_image_checksum(self, pod_row) -> str | None:
        """Return **one** raw 64-char image SHA256 digest for the pod's
        primary actual (non-init) container so the UI displays a single
        real container image fingerprint.

        Only the first digest is used — init containers are already
        excluded at collection time, and for multi-container pods
        (e.g. app + sidecar) the first container is the primary
        application container by Kubernetes convention.

        Legacy rows (no *image_digests* stored) fall back to the stored
        ``container_images_checksum`` value as-is.
        """
        digests = getattr(pod_row, "image_digests", None)
        if digests:
            # Always return only the first actual container's raw digest
            return digests[0]

        # Legacy / fallback — use the pre-computed column directly
        raw = pod_row.container_images_checksum
        return raw if raw else None

    @staticmethod
    def _derive_microservice_key(
        owner_kind: str | None,
        owner_name: str | None,
    ) -> str | None:
        """Derive a stable microservice-level grouping name.

        For **ReplicaSet** owners the name follows the Kubernetes pattern
        ``{deployment-name}-{pod-template-hash}`` where the hash is an
        8-10 character alphanumeric suffix appended by the Deployment
        controller.  Stripping it gives the Deployment name so that pods
        across different ReplicaSet revisions map to a single row.

        For all other owner kinds (DaemonSet, StatefulSet, Job, …) the
        ``owner_name`` is already the stable identity.
        """
        if owner_kind != "ReplicaSet" or not owner_name:
            return owner_name
        parts = owner_name.rsplit("-", 1)
        if len(parts) == 2 and len(parts[1]) >= 8 and parts[1].isalnum():
            return parts[0]
        return owner_name

    @staticmethod
    def _extract_image_shas(pod_status) -> list[str]:
        """Extract SHA256 digests from **actual running** container status
        ``imageID`` fields (not init containers).

        The ``imageID`` reported by the container runtime varies by engine:

        * Docker / CRI-O:
          ``registry/repo/image@sha256:9dc0c284ac65...``
        * containerd (some versions):
          ``sha256:9dc0c284ac65...``

        We extract just the 64-char hex digest after ``sha256:``.
        Falls back to an empty list when status information is unavailable.
        """
        shas: list[str] = []
        if not pod_status:
            return shas
        for cs in pod_status.container_statuses or []:
            image_id = getattr(cs, "image_id", None) or ""
            if "@sha256:" in image_id:
                sha = image_id.split("@sha256:", 1)[1]
                shas.append(sha)
            elif image_id.startswith("sha256:"):
                # containerd-style imageID without '@' prefix
                shas.append(image_id[len("sha256:") :])
        return shas

    @staticmethod
    def _extract_actual_container_images(pod_status) -> list[str]:
        """Return image references from the **actual running** container
        statuses (``container_statuses``), NOT from init containers.

        This is a fallback for pods whose ``imageID`` does not contain a
        ``sha256:`` digest.  The ``image`` field on each container status
        is the runtime-resolved image reference (e.g.
        ``registry.example.com/app@sha256:…`` or ``registry/app:tag``),
        which is more accurate than the declared tag in the pod spec.
        """
        images: list[str] = []
        if not pod_status:
            return images
        for cs in pod_status.container_statuses or []:
            img = getattr(cs, "image", None)
            if img:
                images.append(img)
        return images

    def _serialize_pod_spec(self, spec) -> dict:
        """Serialize pod spec to dictionary."""
        if not spec:
            return {}
        return {
            "service_account_name": spec.service_account_name,
            "restart_policy": spec.restart_policy,
            "node_selector": dict(spec.node_selector) if spec.node_selector else {},
            "tolerations": [
                {"key": t.key, "operator": t.operator, "effect": t.effect} for t in (spec.tolerations or [])
            ],
        }

    def _extract_env_vars(self, containers) -> list[dict]:
        """Extract environment variables from containers."""
        env_vars = []
        for container in containers or []:
            for env in container.env or []:
                env_vars.append(
                    {
                        "container": container.name,
                        "name": env.name,
                        "value": env.value,
                        "value_from": str(env.value_from) if env.value_from else None,
                    }
                )
        return env_vars

    def _serialize_volumes(self, volumes) -> list[dict]:
        """Serialize volumes to dictionary."""
        if not volumes:
            return []
        result = []
        for vol in volumes:
            vol_data = {"name": vol.name}
            if vol.secret:
                vol_data["type"] = "secret"
                vol_data["secret_name"] = vol.secret.secret_name
            elif vol.config_map:
                vol_data["type"] = "configMap"
                vol_data["config_map_name"] = vol.config_map.name
            elif vol.persistent_volume_claim:
                vol_data["type"] = "pvc"
                vol_data["claim_name"] = vol.persistent_volume_claim.claim_name
            else:
                vol_data["type"] = "other"
            result.append(vol_data)
        return result

    def _extract_resource_limits(self, containers) -> list[dict]:
        """Extract resource requests and limits."""
        resources = []
        for container in containers or []:
            if container.resources:
                resources.append(
                    {
                        "container": container.name,
                        "requests": dict(container.resources.requests or {}),
                        "limits": dict(container.resources.limits or {}),
                    }
                )
        return resources

    def _categorize_drift_type(self, category: str) -> str:
        """Categorize drift type based on change category."""
        if category == "container_image":
            return "image_change"
        if category == "env_vars":
            return "config_drift"
        if category == "volumes":
            return "secret_change"
        return "resource_change"

    @staticmethod
    def _drift_type_to_severity(drift_type: str) -> str:
        """Derive severity from drift_type."""
        return {
            "deleted": "critical",
            "modified": "high",
            "added": "medium",
        }.get(drift_type, "low")

    def _format_drift(self, drift: SynapsePipelineDrift) -> dict:
        """Format drift event for API response."""
        return {
            "id": drift.id,
            "detection_date": (drift.detection_date.isoformat() if drift.detection_date else None),
            "workspace_name": drift.workspace_name,
            "pipeline_name": drift.pipeline_name,
            "drift_type": drift.drift_type,
            "severity": self._drift_type_to_severity(drift.drift_type),
            "previous_checksum": drift.previous_checksum,
            "current_checksum": drift.current_checksum,
            "diff_summary": drift.diff_summary,
            "acknowledged": drift.acknowledged,
            "acknowledged_by": drift.acknowledged_by,
            "compliance_status": drift.compliance_status,
        }

    def _format_pod_drift(self, drift: AKSPodDrift) -> dict:
        """Format pod drift for API response."""
        return {
            "id": drift.id,
            "detection_date": (drift.detection_date.isoformat() if drift.detection_date else None),
            "cluster_name": drift.cluster_name,
            "namespace": drift.namespace,
            "pod_name": drift.pod_name,
            "owner_kind": drift.owner_kind,
            "owner_name": drift.owner_name,
            "drift_type": drift.drift_type,
            "drift_category": drift.drift_category,
            "severity": drift.severity,
            "previous_value": drift.previous_value,
            "current_value": drift.current_value,
            "acknowledged": drift.acknowledged,
            "compliance_status": drift.compliance_status,
        }

    def _extract_cluster_name(self, resource_id: str) -> str:
        """Extract cluster name from resource ID."""
        parts = resource_id.split("/")
        return parts[-1] if parts else ""

    def _score_to_grade(self, score: float) -> str:
        """Convert numeric score to letter grade."""
        if score >= 90:
            return "A"
        if score >= 80:
            return "B"
        if score >= 70:
            return "C"
        if score >= 60:
            return "D"
        return "F"

    # =========================================================================
    # CHECKSUM SCHEDULE MANAGEMENT (extended)
    # =========================================================================

    async def seed_default_checksum_schedules(self) -> dict[str, Any]:
        """Ensure every known Synapse workspace has a checksum schedule.

        Called once at application startup so that ATTCC and CES workspaces
        are both covered by the background scheduler.  Existing schedules are
        never modified — only *missing* ones are created.
        """
        if self.db is None:
            return {"created": 0, "skipped": 0, "error": "database unavailable"}

        workspaces = self.SYNAPSE_WORKSPACES
        created = 0
        skipped = 0

        for ws in workspaces:
            ws_name = ws["workspace_name"]
            system = ws["system"]
            environment = ws["environment"]

            # Check if a schedule already exists for this workspace
            existing = await self.db.execute(
                select(ChecksumScheduleConfig).where(
                    ChecksumScheduleConfig.workspace_name == ws_name,
                    ChecksumScheduleConfig.module_type == "synapse",
                )
            )
            if existing.scalar_one_or_none() is not None:
                skipped += 1
                continue

            schedule = ChecksumScheduleConfig(
                name=f"synapse-{ws_name}",
                description=f"Auto-seeded schedule for {ws_name}",
                module_type="synapse",
                system=system,
                environment=environment,
                workspace_name=ws_name,
                schedule_type="interval",
                interval_hours=24,
                timezone="UTC",
                notification_emails=[],
                is_enabled=True,
                created_by="system-auto-seed",
                created_at=datetime.utcnow(),
                next_run_at=datetime.utcnow(),  # eligible to run immediately
            )
            self.db.add(schedule)
            created += 1

        if created:
            await self.db.commit()

        logger.info(
            "seed_default_checksum_schedules_completed",
            created=created,
            skipped=skipped,
        )
        return {"created": created, "skipped": skipped}

    async def get_checksum_schedule(
        self,
        schedule_id: str | int,
    ) -> dict[str, Any] | None:
        """Get a specific checksum schedule."""
        try:
            schedule = await self._get_scoped_checksum_schedule_record(schedule_id)

            return {
                "id": schedule.id,
                "name": schedule.name,
                "description": schedule.description,
                "module_type": schedule.module_type,
                "system": schedule.system,
                "environment": schedule.environment,
                "workspace_name": schedule.workspace_name,
                "cluster_id": schedule.cluster_id,
                "cluster_name": schedule.cluster_name,
                "namespaces": schedule.namespaces or [],
                "schedule_type": schedule.schedule_type,
                "interval_hours": schedule.interval_hours,
                "cron_expression": schedule.cron_expression,
                "timezone": schedule.timezone,
                "notification_emails": schedule.notification_emails,
                "is_enabled": schedule.is_enabled,
                "last_run_at": (schedule.last_run_at.isoformat() if schedule.last_run_at else None),
                "next_run_at": (schedule.next_run_at.isoformat() if schedule.next_run_at else None),
                "created_at": (schedule.created_at.isoformat() if schedule.created_at else None),
                "created_by": schedule.created_by,
            }

        except ValueError:
            logger.warning("get_checksum_schedule_invalid_id", schedule_id=schedule_id)
            return None
        except Exception as e:
            logger.error("get_checksum_schedule_failed", schedule_id=schedule_id, error=str(e))
            return None

    async def delete_checksum_schedule(
        self,
        schedule_id: str,
        deleted_by: str,
    ) -> dict[str, Any]:
        """Delete a checksum schedule."""
        try:
            normalized_schedule_id = self._normalize_schedule_id(schedule_id)
            schedule = await self._get_scoped_checksum_schedule_record(normalized_schedule_id)

            schedule_name = schedule.name
            await self.db.delete(schedule)
            await self.db.commit()

            logger.info(
                "checksum_schedule_deleted",
                schedule_id=schedule_id,
                deleted_by=deleted_by,
            )

            return {
                "success": True,
                "schedule_id": str(normalized_schedule_id),
                "message": f"Schedule '{schedule_name}' deleted successfully",
            }

        except ValueError:
            raise
        except Exception as e:
            await self.db.rollback()
            logger.error("delete_checksum_schedule_failed", schedule_id=schedule_id, error=str(e))
            raise

    async def test_checksum_schedule(
        self,
        schedule_id: str,
        executed_by: str,
    ) -> dict[str, Any]:
        """Test a checksum schedule by executing it immediately."""
        try:
            normalized_schedule_id = self._normalize_schedule_id(schedule_id)
            schedule = await self._get_scoped_checksum_schedule_record(normalized_schedule_id)

            # Actually execute the verification (and send email if configured)
            run = await self._execute_checksum_schedule(schedule)

            # Update last run timestamp and next run
            schedule.last_run_at = datetime.utcnow()
            schedule.next_run_at = self.compute_next_run_at(schedule)
            schedule.updated_by = executed_by

            self.db.add(schedule)
            await self.db.commit()

            logger.info(
                "checksum_schedule_tested",
                schedule_id=schedule_id,
                module_type=schedule.module_type,
                executed_by=executed_by,
                run_id=run.get("run_id"),
            )

            return {
                "success": True,
                "schedule_id": str(normalized_schedule_id),
                "name": schedule.name,
                "last_run_at": schedule.last_run_at.isoformat(),
                "run_id": run.get("run_id"),
                "message": f"Schedule executed successfully — {run.get('passed', 0)} PASS, {run.get('failed', 0)} FAIL",
            }

        except ValueError:
            raise
        except Exception as e:
            await self.db.rollback()
            logger.error("test_checksum_schedule_failed", schedule_id=schedule_id, error=str(e))
            raise


# Factory function
def get_compliance_service(db_session: AsyncSession) -> ComplianceService:
    """Create Compliance Service instance."""
    return ComplianceService(db_session)
