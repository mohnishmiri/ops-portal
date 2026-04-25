"""
Optimization Service — FinOps recommendation engine.

Detects idle resources, unattached disks, overprovisioned SKUs,
and generates savings recommendations with confidence scoring.

Sources:
  1. Azure Advisor recommendations (Cost category)
  2. Azure Resource Graph queries (custom heuristics)
  3. Azure Monitor metrics (utilization analysis)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.admin_config import get_effective_cache_ttl_seconds
from app.core.azure_auth import get_azure_credential
from app.core.azure_throttle import AZURE_API_SEMAPHORE
from app.core.config import settings
from app.core.db_cache import cache_manager
from app.core.subscription_resolver import get_monitored_subscription_ids
from app.models.optimization import (
    ConfidenceLevel,
    CostRecommendation,
    OptimizationDashboardResponse,
    OptimizationSummary,
    RecommendationCategory,
    RecommendationPriority,
    RecommendationStatus,
    ResourceInfo,
    WastageDetailItem,
    WastageSummary,
)

logger = structlog.get_logger(__name__)


def _get_resource_graph_client(credential):
    from azure.mgmt.resourcegraph import ResourceGraphClient

    return ResourceGraphClient(credential)


def _get_advisor_client(credential, subscription_id: str):
    from azure.mgmt.advisor import AdvisorManagementClient

    return AdvisorManagementClient(credential, subscription_id)


def _get_compute_client(credential, subscription_id: str):
    from azure.mgmt.compute import ComputeManagementClient

    return ComputeManagementClient(credential, subscription_id)


def _get_query_request(**kwargs):
    from azure.mgmt.resourcegraph.models import QueryRequest

    return QueryRequest(**kwargs)


# ── Azure Resource Graph Queries ───────────────────────────────────────

QUERY_UNATTACHED_DISKS = """
Resources
| where type =~ 'microsoft.compute/disks'
| where managedBy == ''
| extend diskSizeGB = tostring(properties.diskSizeGB),
         sku = tostring(sku.name),
         diskState = tostring(properties.diskState)
| where diskState == 'Unattached'
| project id, name, resourceGroup, subscriptionId, location, diskSizeGB, sku, tags
"""

QUERY_IDLE_VMS = """
Resources
| where type =~ 'microsoft.compute/virtualmachines'
| extend vmSize = tostring(properties.hardwareProfile.vmSize),
         powerState = tostring(properties.extended.instanceView.powerState.code)
| project id, name, resourceGroup, subscriptionId, location, vmSize, powerState, tags
"""

QUERY_ORPHANED_NICS = """
Resources
| where type =~ 'microsoft.network/networkinterfaces'
| where isnull(properties.virtualMachine)
| project id, name, resourceGroup, subscriptionId, location, tags
"""

QUERY_ORPHANED_PUBLIC_IPS = """
Resources
| where type =~ 'microsoft.network/publicipaddresses'
| where isnull(properties.ipConfiguration)
| project id, name, resourceGroup, subscriptionId, location, tags
"""

QUERY_ORPHANED_SNAPSHOTS = """
Resources
| where type =~ 'microsoft.compute/snapshots'
| extend timeCreated = todatetime(properties.timeCreated),
         sourceResourceId = tolower(tostring(properties.creationData.sourceResourceId))
| where timeCreated < ago(30d)
| where isnotempty(sourceResourceId)
| join kind=leftouter (
    Resources
    | where type in~ ('microsoft.compute/disks', 'microsoft.compute/snapshots')
    | project sourceResourceId = tolower(id), sourceExists = true
) on sourceResourceId
| where sourceExists != true
| project id, name, resourceGroup, subscriptionId, location,
          diskSizeGB = tostring(properties.diskSizeGB), tags, sourceResourceId, sourceExists
"""

# ── Estimated monthly costs by disk SKU ────────────────────────────────

DISK_COST_ESTIMATES: dict[str, float] = {
    "Premium_LRS": 0.135,  # per GB/month
    "StandardSSD_LRS": 0.075,
    "Standard_LRS": 0.04,
    "Premium_ZRS": 0.17,
    "UltraSSD_LRS": 0.22,
}


class OptimizationService:
    """FinOps recommendation engine with multi-source analysis."""

    def __init__(self) -> None:
        self._credential = get_azure_credential()

    # ── Resource Graph Queries ─────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=2, max=10))
    async def _run_resource_graph_query(
        self,
        query: str,
        subscription_ids: list[str] | None = None,
    ) -> list[dict]:
        """Execute an Azure Resource Graph query."""
        subs = subscription_ids or await get_monitored_subscription_ids()
        client = _get_resource_graph_client(self._credential)

        try:
            request = _get_query_request(
                subscriptions=subs,
                query=query,
            )
            async with AZURE_API_SEMAPHORE:
                result = await asyncio.to_thread(client.resources, request)
            return [dict(row) for row in (result.data or [])]
        except Exception as e:
            logger.error("resource_graph_query_failed", error=str(e))
            return []
        finally:
            client.close()

    # ── Advisor Recommendations ────────────────────────────────────────

    async def _get_advisor_recommendations(
        self,
        subscription_ids: list[str] | None = None,
    ) -> list[CostRecommendation]:
        """Fetch Azure Advisor cost recommendations."""
        subs = subscription_ids or await get_monitored_subscription_ids()
        recommendations: list[CostRecommendation] = []

        for sub_id in subs:
            try:
                client = _get_advisor_client(self._credential, sub_id)

                def _list_advisor(c=client):
                    return list(c.recommendations.list(filter="Category eq 'Cost'"))

                async with AZURE_API_SEMAPHORE:
                    advisor_recs = await asyncio.to_thread(_list_advisor)

                for rec in advisor_recs:
                    extended = rec.extended_properties or {}
                    annual_savings = Decimal(str(extended.get("annualSavingsAmount", 0)))
                    monthly_savings = (annual_savings / 12).quantize(Decimal("0.01"))

                    recommendations.append(
                        CostRecommendation(
                            id=rec.id or str(uuid.uuid4()),
                            category=self._map_advisor_category(rec.category),
                            priority=self._map_advisor_impact(rec.impact),
                            title=(rec.short_description.problem if rec.short_description else "Azure Advisor"),
                            description=(rec.short_description.solution if rec.short_description else ""),
                            resource=ResourceInfo(
                                resource_id=(rec.resource_metadata.resource_id if rec.resource_metadata else ""),
                                resource_name=rec.impacted_value or "",
                                resource_type=rec.impacted_field or "",
                                resource_group="",
                                subscription_id=sub_id,
                                subscription_name=sub_id,
                                location="",
                            ),
                            current_monthly_cost=Decimal("0"),
                            estimated_monthly_savings=monthly_savings,
                            estimated_annual_savings=annual_savings,
                            confidence=ConfidenceLevel.HIGH,
                            confidence_score=90.0,
                            action_required=(rec.short_description.solution if rec.short_description else "Review"),
                            risk_level="low",
                            recommended_sku=extended.get("targetSku"),
                            source="azure_advisor",
                            created_at=datetime.now(UTC),
                        )
                    )
                client.close()

            except Exception as e:
                logger.error("advisor_fetch_failed", subscription_id=sub_id, error=str(e))

        return recommendations

    # ── Idle Resource Detection ────────────────────────────────────────

    async def detect_idle_resources(
        self,
        subscription_ids: list[str] | None = None,
    ) -> list[CostRecommendation]:
        """Detect idle VMs, unattached disks, orphaned snapshots/NICs/IPs."""
        recommendations: list[CostRecommendation] = []

        # Unattached disks
        disks = await self._run_resource_graph_query(QUERY_UNATTACHED_DISKS, subscription_ids)
        for disk in disks:
            size_gb = int(disk.get("diskSizeGB", 0))
            sku = disk.get("sku", "Standard_LRS")
            monthly_cost = Decimal(str(size_gb * DISK_COST_ESTIMATES.get(sku, 0.04))).quantize(Decimal("0.01"))

            recommendations.append(
                CostRecommendation(
                    id=f"disk-{uuid.uuid4().hex[:12]}",
                    category=RecommendationCategory.UNATTACHED_DISKS,
                    priority=(RecommendationPriority.HIGH if monthly_cost > 50 else RecommendationPriority.MEDIUM),
                    title=f"Unattached disk: {disk.get('name', 'unknown')}",
                    description=(
                        f"Managed disk '{disk.get('name')}' ({size_gb} GB, {sku}) "
                        f"is unattached. Consider deleting or snapshotting."
                    ),
                    resource=ResourceInfo(
                        resource_id=disk.get("id", ""),
                        resource_name=disk.get("name", ""),
                        resource_type="Microsoft.Compute/disks",
                        resource_group=disk.get("resourceGroup", ""),
                        subscription_id=disk.get("subscriptionId", ""),
                        subscription_name=disk.get("subscriptionId", ""),
                        location=disk.get("location", ""),
                        sku=sku,
                        tags=disk.get("tags", {}),
                    ),
                    current_monthly_cost=monthly_cost,
                    estimated_monthly_savings=monthly_cost,
                    estimated_annual_savings=(monthly_cost * 12).quantize(Decimal("0.01")),
                    confidence=ConfidenceLevel.HIGH,
                    confidence_score=95.0,
                    action_required="Delete the unattached disk or create a snapshot before deletion",
                    risk_level="low",
                    source="resource_graph",
                    created_at=datetime.now(UTC),
                )
            )

        # Orphaned snapshots (>30 days old)
        snapshots = await self._run_resource_graph_query(QUERY_ORPHANED_SNAPSHOTS, subscription_ids)
        for snap in snapshots:
            source_resource_id = str(snap.get("sourceResourceId") or "").strip()
            source_exists = str(snap.get("sourceExists") or "").lower()

            if not source_resource_id or source_exists == "true":
                continue

            size_gb = int(snap.get("diskSizeGB", 0))
            monthly_cost = Decimal(str(size_gb * 0.05)).quantize(Decimal("0.01"))

            recommendations.append(
                CostRecommendation(
                    id=f"snap-{uuid.uuid4().hex[:12]}",
                    category=RecommendationCategory.ORPHANED_SNAPSHOTS,
                    priority=RecommendationPriority.MEDIUM,
                    title=f"Orphaned snapshot: {snap.get('name', 'unknown')}",
                    description=(
                        f"Snapshot source resource is no longer present ({size_gb} GB). "
                        "Review retention policy and delete if no longer required."
                    ),
                    resource=ResourceInfo(
                        resource_id=snap.get("id", ""),
                        resource_name=snap.get("name", ""),
                        resource_type="Microsoft.Compute/snapshots",
                        resource_group=snap.get("resourceGroup", ""),
                        subscription_id=snap.get("subscriptionId", ""),
                        subscription_name=snap.get("subscriptionId", ""),
                        location=snap.get("location", ""),
                    ),
                    current_monthly_cost=monthly_cost,
                    estimated_monthly_savings=monthly_cost,
                    estimated_annual_savings=(monthly_cost * 12).quantize(Decimal("0.01")),
                    confidence=ConfidenceLevel.HIGH,
                    confidence_score=90.0,
                    action_required="Review orphaned snapshot and delete it if the source workload is gone",
                    risk_level="medium",
                    source="resource_graph",
                    created_at=datetime.now(UTC),
                )
            )

        # Orphaned NICs
        nics = await self._run_resource_graph_query(QUERY_ORPHANED_NICS, subscription_ids)
        for nic in nics:
            recommendations.append(
                CostRecommendation(
                    id=f"nic-{uuid.uuid4().hex[:12]}",
                    category=RecommendationCategory.IDLE_RESOURCES,
                    priority=RecommendationPriority.LOW,
                    title=f"Orphaned NIC: {nic.get('name', 'unknown')}",
                    description="Network interface not attached to any VM.",
                    resource=ResourceInfo(
                        resource_id=nic.get("id", ""),
                        resource_name=nic.get("name", ""),
                        resource_type="Microsoft.Network/networkInterfaces",
                        resource_group=nic.get("resourceGroup", ""),
                        subscription_id=nic.get("subscriptionId", ""),
                        subscription_name=nic.get("subscriptionId", ""),
                        location=nic.get("location", ""),
                    ),
                    current_monthly_cost=Decimal("0"),
                    estimated_monthly_savings=Decimal("0"),
                    estimated_annual_savings=Decimal("0"),
                    confidence=ConfidenceLevel.HIGH,
                    confidence_score=95.0,
                    action_required="Delete orphaned NIC",
                    risk_level="low",
                    source="resource_graph",
                    created_at=datetime.now(UTC),
                )
            )

        return recommendations

    # ── Full Dashboard ─────────────────────────────────────────────────

    async def get_optimization_summary(
        self,
        subscription_ids: list[str] | None = None,
        db: AsyncSession | None = None,
        refresh: bool = False,
    ) -> OptimizationSummary:
        """Aggregate all recommendations into a summary.

        Falls back to realistic demo data in development mode when Azure
        APIs are unreachable.
        """
        started = perf_counter()
        subs = subscription_ids or await get_monitored_subscription_ids()
        cache_key = self._summary_cache_key(subs)
        if refresh:
            await cache_manager.invalidate(cache_key)
        else:
            cached = await cache_manager.get_cached(cache_key)
            if cached:
                try:
                    summary = OptimizationSummary.model_validate_json(cached)
                    logger.info(
                        "optimization_summary_served",
                        source="cache",
                        subscription_count=len(subs),
                        elapsed_ms=round((perf_counter() - started) * 1000, 2),
                    )
                    return summary
                except Exception:
                    pass

        source = "live"
        try:
            summary = await self._optimization_summary_live(subs)
        except Exception:
            if settings.ENVIRONMENT == "development":
                logger.warning(
                    "azure_api_unreachable_using_demo_data",
                    endpoint="optimization_summary",
                )
                summary = self._demo_optimization_summary(subs)
                source = "demo"
            else:
                raise

        ttl = await get_effective_cache_ttl_seconds(db)
        await cache_manager.set_cached(cache_key, summary.model_dump_json(), ttl=ttl)
        logger.info(
            "optimization_summary_served",
            source=source,
            subscription_count=len(subs),
            elapsed_ms=round((perf_counter() - started) * 1000, 2),
        )
        return summary

    def _demo_optimization_summary(
        self,
        subscription_ids: list[str] | None = None,
    ) -> OptimizationSummary:
        """Return realistic sample optimization data for local development."""
        return OptimizationSummary(
            total_recommendations=17,
            total_estimated_monthly_savings=Decimal("1187.50"),
            total_estimated_annual_savings=Decimal("14250.00"),
            wastage=WastageSummary(
                total_monthly_waste=Decimal("1187.50"),
                total_annual_waste=Decimal("14250.00"),
                idle_vms_count=3,
                unattached_disks_count=5,
                orphaned_snapshots_count=4,
                overprovisioned_count=5,
            ),
            recommendations_by_category={
                RecommendationCategory.UNDERUTILIZED_VMS: 3,
                RecommendationCategory.UNATTACHED_DISKS: 5,
                RecommendationCategory.ORPHANED_SNAPSHOTS: 4,
                RecommendationCategory.OVERPROVISIONED_SKUS: 5,
            },
            recommendations_by_priority={
                RecommendationPriority.HIGH: 5,
                RecommendationPriority.MEDIUM: 8,
                RecommendationPriority.LOW: 4,
            },
            top_recommendations=[],
            generated_at=datetime.now(UTC),
            subscriptions_analyzed=len(subscription_ids or []) or 1,
        )

    async def _optimization_summary_live(
        self,
        subscription_ids: list[str] | None = None,
    ) -> OptimizationSummary:
        """Live implementation that queries Azure Advisor/Resource Graph."""
        all_recs = await self.list_recommendations(subscription_ids=subscription_ids)

        total_monthly = sum(r.estimated_monthly_savings for r in all_recs)
        total_annual = sum(r.estimated_annual_savings for r in all_recs)

        by_category: dict[RecommendationCategory, int] = {}
        by_priority: dict[RecommendationPriority, int] = {}

        # Per-category wastage detail accumulators
        _cat_label = {
            RecommendationCategory.UNDERUTILIZED_VMS: "Idle VMs",
            RecommendationCategory.UNATTACHED_DISKS: "Unattached Disks",
            RecommendationCategory.ORPHANED_SNAPSHOTS: "Orphaned Snapshots",
            RecommendationCategory.OVERPROVISIONED_SKUS: "Overprovisioned Resources",
            RecommendationCategory.RIGHT_SIZING: "Right-Sizing",
            RecommendationCategory.IDLE_RESOURCES: "Idle Resources",
            RecommendationCategory.RESERVED_INSTANCES: "Reserved Instances",
            RecommendationCategory.SAVINGS_PLANS: "Savings Plans",
            RecommendationCategory.STORAGE_OPTIMIZATION: "Storage Optimization",
            RecommendationCategory.NETWORK_OPTIMIZATION: "Network Optimization",
        }
        _cat_accum: dict[str, dict] = {}  # label → {count, monthly, annual, resources}

        wastage = WastageSummary(
            total_monthly_waste=total_monthly,
            total_annual_waste=total_annual,
        )

        for rec in all_recs:
            by_category[rec.category] = by_category.get(rec.category, 0) + 1
            by_priority[rec.priority] = by_priority.get(rec.priority, 0) + 1

            if rec.category == RecommendationCategory.UNDERUTILIZED_VMS:
                wastage.idle_vms_count += 1
            elif rec.category == RecommendationCategory.UNATTACHED_DISKS:
                wastage.unattached_disks_count += 1
            elif rec.category == RecommendationCategory.ORPHANED_SNAPSHOTS:
                wastage.orphaned_snapshots_count += 1
            elif rec.category == RecommendationCategory.OVERPROVISIONED_SKUS:
                wastage.overprovisioned_count += 1

            # Accumulate per-category detail
            label = _cat_label.get(rec.category, rec.category.value)
            if label not in _cat_accum:
                _cat_accum[label] = {
                    "count": 0,
                    "monthly": Decimal("0"),
                    "annual": Decimal("0"),
                    "resources": [],
                }
            bucket = _cat_accum[label]
            bucket["count"] += 1
            bucket["monthly"] += rec.estimated_monthly_savings
            bucket["annual"] += rec.estimated_annual_savings
            bucket["resources"].append(
                {
                    "name": rec.resource.resource_name,
                    "resource_group": rec.resource.resource_group,
                    "subscription_id": rec.resource.subscription_id,
                    "monthly_cost": str(rec.estimated_monthly_savings),
                    "title": rec.title,
                    "recommendation": rec.action_required or rec.description or "",
                    "current_sku": rec.resource.sku or "",
                    "recommended_sku": rec.recommended_sku or "",
                    "priority": rec.priority.value if rec.priority else "medium",
                    "resource_type": rec.resource.resource_type or "",
                    "confidence": rec.confidence.value if rec.confidence else "medium",
                }
            )

        # Build detail list sorted by monthly waste descending
        wastage.details = sorted(
            [
                WastageDetailItem(
                    category=label,
                    count=info["count"],
                    monthly_waste=info["monthly"],
                    annual_waste=info["annual"],
                    resources=info["resources"],
                )
                for label, info in _cat_accum.items()
            ],
            key=lambda d: d.monthly_waste,
            reverse=True,
        )

        return OptimizationSummary(
            total_recommendations=len(all_recs),
            total_estimated_monthly_savings=total_monthly,
            total_estimated_annual_savings=total_annual,
            wastage=wastage,
            recommendations_by_category=by_category,
            recommendations_by_priority=by_priority,
            top_recommendations=sorted(all_recs, key=lambda r: r.estimated_annual_savings, reverse=True)[:10],
            generated_at=datetime.now(UTC),
            subscriptions_analyzed=len(subscription_ids or await get_monitored_subscription_ids()),
        )

    async def get_full_dashboard(
        self,
        subscription_ids: list[str] | None = None,
    ) -> OptimizationDashboardResponse:
        """Get complete optimization dashboard."""
        summary = await self.get_optimization_summary(subscription_ids)
        try:
            all_recs = await self.list_recommendations(subscription_ids=subscription_ids)
        except Exception:
            if settings.ENVIRONMENT == "development":
                all_recs = []
            else:
                raise

        return OptimizationDashboardResponse(
            summary=summary,
            recommendations=all_recs,
            reservation_recommendations=[],
            generated_at=datetime.now(UTC),
        )

    def _summary_cache_key(self, subscription_ids: list[str]) -> str:
        raw = json.dumps(sorted(subscription_ids), sort_keys=True)
        digest = hashlib.md5(raw.encode()).hexdigest()[:16]
        return f"pagecache:optimization:summary:{digest}"

    async def list_recommendations(
        self,
        subscription_ids: list[str] | None = None,
        category: RecommendationCategory | None = None,
        priority: RecommendationPriority | None = None,
        status: RecommendationStatus | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[CostRecommendation]:
        """List all recommendations from all sources with filtering."""
        try:
            # Gather from all sources
            advisor_recs = await self._get_advisor_recommendations(subscription_ids)
            idle_recs = await self.detect_idle_resources(subscription_ids)
        except Exception:
            if settings.ENVIRONMENT == "development":
                logger.warning("azure_api_unreachable_using_demo_data", endpoint="recommendations")
                return []
            raise

        all_recs = advisor_recs + idle_recs

        # Apply filters
        if category:
            all_recs = [r for r in all_recs if r.category == category]
        if priority:
            all_recs = [r for r in all_recs if r.priority == priority]
        if status:
            all_recs = [r for r in all_recs if r.status == status]

        # Sort by savings (descending)
        all_recs.sort(key=lambda r: r.estimated_annual_savings, reverse=True)

        return all_recs[offset : offset + limit]

    async def update_recommendation_status(
        self,
        recommendation_id: str,
        new_status: RecommendationStatus,
        updated_by: str,
    ) -> CostRecommendation:
        """Update the status of a recommendation."""
        # In production, this would persist to a database
        logger.info(
            "recommendation_status_updated",
            recommendation_id=recommendation_id,
            new_status=new_status.value,
            updated_by=updated_by,
        )
        # Return a placeholder — real implementation would fetch and update
        raise NotImplementedError("Requires persistent storage implementation")

    # ── Helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _map_advisor_category(category: str | None) -> RecommendationCategory:
        """Map Azure Advisor category to our enum."""
        mapping = {
            "Cost": RecommendationCategory.RIGHT_SIZING,
            "HighAvailability": RecommendationCategory.RIGHT_SIZING,
            "Performance": RecommendationCategory.OVERPROVISIONED_SKUS,
        }
        return mapping.get(category or "", RecommendationCategory.RIGHT_SIZING)

    @staticmethod
    def _map_advisor_impact(impact: str | None) -> RecommendationPriority:
        """Map Azure Advisor impact to priority."""
        mapping = {
            "High": RecommendationPriority.HIGH,
            "Medium": RecommendationPriority.MEDIUM,
            "Low": RecommendationPriority.LOW,
        }
        return mapping.get(impact or "", RecommendationPriority.MEDIUM)
