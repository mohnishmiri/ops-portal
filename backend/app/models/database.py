"""
PostgreSQL Database Schema for Azure Ops Portal.

Includes schema for:
- Cost Management (existing)
- AKS Operations (Module 2)
- Compliance & Drift Detection (Module 3)
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker

from app.core.config import settings

Base = declarative_base()


# =============================================================================
# ACCESS CONTROL MODELS (Granular RBAC/ABAC)
# =============================================================================


class Resource(Base):
    """Represents a module or page for access control."""

    __tablename__ = "resources"

    id = Column(Integer, primary_key=True, autoincrement=True)
    resource_type = Column(String(50), nullable=False)  # 'module' or 'page'
    resource_name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    # Hierarchy: a page's parent_id points to its module resource
    parent_id = Column(Integer, ForeignKey("resources.id"), nullable=True, index=True)
    # Frontend route path this resource maps to (e.g. '/aks', '/env-costs')
    route_path = Column(String(500), nullable=True)
    # System resources are seeded on startup and cannot be deleted via API
    is_system = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    permissions = relationship("Permission", back_populates="resource", cascade="all, delete-orphan")


class Permission(Base):
    """Grants a user, role, or group access to a resource (module/page) with a specific permission type."""

    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subject_type = Column(String(10), nullable=False)  # 'user', 'role', or 'group'
    subject_id = Column(String(255), nullable=False)  # user_id, role name, or team name
    resource_id = Column(Integer, ForeignKey("resources.id"), nullable=False)
    permission_type = Column(String(50), nullable=False)  # e.g., 'view', 'edit'
    # Environment scope: 'all' (default), 'prod', or 'nonprod'
    environment_scope = Column(String(20), nullable=False, default="all")
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    resource = relationship("Resource", back_populates="permissions")


class Team(Base):
    """App-managed team for group-based permission grants."""

    __tablename__ = "teams"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_name = Column(String(255), nullable=False, unique=True, index=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    members = relationship("TeamMembership", back_populates="team", cascade="all, delete-orphan")


class TeamMembership(Base):
    """Maps a user to a team."""

    __tablename__ = "team_memberships"

    id = Column(Integer, primary_key=True, autoincrement=True)
    team_id = Column(Integer, ForeignKey("teams.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    user_email = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    team = relationship("Team", back_populates="members")

    __table_args__ = (UniqueConstraint("team_id", "user_id", name="uq_team_user"),)


# =============================================================================
# COMMON / SHARED MODELS
# =============================================================================


class AuditLog(Base):
    """Central audit log for all operations."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    user_email = Column(String(255), nullable=True)
    action = Column(String(100), nullable=False, index=True)
    resource_type = Column(String(100), nullable=False)
    resource_id = Column(String(500), nullable=True)
    details = Column(JSONB, nullable=True)
    ip_address = Column(String(50), nullable=True)
    status = Column(String(20), default="success")

    __table_args__ = (
        Index("ix_audit_logs_user_action", "user_id", "action"),
        Index("ix_audit_logs_timestamp_action", "timestamp", "action"),
    )


# =============================================================================
# MODULE 2: AKS OPERATIONS MODELS
# =============================================================================


class AKSClusterSnapshot(Base):
    """Historical snapshots of AKS cluster metadata."""

    __tablename__ = "aks_cluster_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_date = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    cluster_id = Column(String(500), nullable=False, index=True)  # Azure resource ID
    cluster_name = Column(String(255), nullable=False, index=True)
    subscription_id = Column(String(50), nullable=False, index=True)
    subscription_name = Column(String(255), nullable=True)
    resource_group = Column(String(255), nullable=False)
    location = Column(String(100), nullable=False)
    kubernetes_version = Column(String(50), nullable=False)
    provisioning_state = Column(String(50), nullable=False)
    power_state = Column(String(50), nullable=True)
    fqdn = Column(String(500), nullable=True)
    node_pools = Column(JSONB, nullable=True)  # Array of node pool details
    network_profile = Column(JSONB, nullable=True)
    addon_profiles = Column(JSONB, nullable=True)
    identity = Column(JSONB, nullable=True)
    tags = Column(JSONB, nullable=True)
    raw_data = Column(JSONB, nullable=True)  # Complete response for diff

    __table_args__ = (
        UniqueConstraint("cluster_id", "snapshot_date", name="uq_cluster_snapshot"),
        Index("ix_aks_cluster_sub_date", "subscription_id", "snapshot_date"),
    )


class AKSNodePoolSnapshot(Base):
    """Historical snapshots of AKS node pool configurations."""

    __tablename__ = "aks_nodepool_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_date = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    cluster_id = Column(String(500), nullable=False, index=True)
    nodepool_name = Column(String(255), nullable=False, index=True)
    vm_size = Column(String(100), nullable=False)
    os_type = Column(String(50), nullable=False)
    os_disk_size_gb = Column(Integer, nullable=True)
    node_count = Column(Integer, nullable=False)
    min_count = Column(Integer, nullable=True)
    max_count = Column(Integer, nullable=True)
    enable_auto_scaling = Column(Boolean, default=False)
    node_image_version = Column(String(255), nullable=True)
    node_labels = Column(JSONB, nullable=True)
    node_taints = Column(JSONB, nullable=True)
    provisioning_state = Column(String(50), nullable=True)
    power_state = Column(String(50), nullable=True)
    mode = Column(String(50), nullable=True)  # System/User
    raw_data = Column(JSONB, nullable=True)

    __table_args__ = (Index("ix_nodepool_cluster_date", "cluster_id", "snapshot_date"),)


class DeploymentScaleHistory(Base):
    """History of deployment scaling operations."""

    __tablename__ = "deployment_scale_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    cluster_id = Column(String(500), nullable=False, index=True)
    cluster_name = Column(String(255), nullable=False)
    namespace = Column(String(255), nullable=False, index=True)
    deployment_name = Column(String(255), nullable=False, index=True)
    action = Column(String(50), nullable=False)  # scale_up, scale_down, restart
    previous_replicas = Column(Integer, nullable=True)
    new_replicas = Column(Integer, nullable=True)
    initiated_by = Column(String(255), nullable=False)
    initiated_by_email = Column(String(255), nullable=True)
    status = Column(String(50), default="pending")  # pending, completed, failed
    error_message = Column(Text, nullable=True)
    approval_required = Column(Boolean, default=False)
    approved_by = Column(String(255), nullable=True)
    approval_timestamp = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_deploy_scale_cluster_ns", "cluster_id", "namespace"),
        Index("ix_deploy_scale_timestamp", "timestamp", "cluster_id"),
    )


class PodUtilizationHistory(Base):
    """Aggregated pod CPU/memory utilization for historical analysis."""

    __tablename__ = "pod_utilization_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    cluster_id = Column(String(500), nullable=False, index=True)
    namespace = Column(String(255), nullable=False, index=True)
    pod_name = Column(String(255), nullable=False, index=True)
    deployment_name = Column(String(255), nullable=True)
    container_name = Column(String(255), nullable=True)

    # CPU metrics (in millicores)
    cpu_request_millicores = Column(Integer, nullable=True)
    cpu_limit_millicores = Column(Integer, nullable=True)
    cpu_usage_millicores = Column(Integer, nullable=True)
    cpu_utilization_pct = Column(Float, nullable=True)

    # Memory metrics (in bytes)
    memory_request_bytes = Column(Integer, nullable=True)
    memory_limit_bytes = Column(Integer, nullable=True)
    memory_usage_bytes = Column(Integer, nullable=True)
    memory_utilization_pct = Column(Float, nullable=True)

    # Aggregation period
    aggregation_period = Column(String(20), default="5m")  # 5m, 1h, 1d

    __table_args__ = (
        Index("ix_pod_util_cluster_ns_ts", "cluster_id", "namespace", "timestamp"),
        Index("ix_pod_util_pod_ts", "pod_name", "timestamp"),
    )


class CronJobAuditHistory(Base):
    """Audit history for cronjob changes."""

    __tablename__ = "cronjob_audit_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    cluster_id = Column(String(500), nullable=False, index=True)
    cluster_name = Column(String(255), nullable=False)
    namespace = Column(String(255), nullable=False, index=True)
    cronjob_name = Column(String(255), nullable=False, index=True)
    action = Column(String(50), nullable=False)  # create, update, suspend, resume, delete
    previous_state = Column(JSONB, nullable=True)
    new_state = Column(JSONB, nullable=True)
    initiated_by = Column(String(255), nullable=False)
    initiated_by_email = Column(String(255), nullable=True)
    status = Column(String(50), default="completed")
    error_message = Column(Text, nullable=True)

    __table_args__ = (Index("ix_cronjob_audit_cluster_ns", "cluster_id", "namespace"),)


# =============================================================================
# MODULE 3: COMPLIANCE & DRIFT DETECTION MODELS
# =============================================================================


class SynapsePipelineChecksum(Base):
    """Checksum tracking for Synapse pipeline definitions."""

    __tablename__ = "synapse_pipeline_checksums"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_date = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    subscription_id = Column(String(50), nullable=False, index=True)
    subscription_name = Column(String(255), nullable=True)
    workspace_name = Column(String(255), nullable=False, index=True)
    workspace_id = Column(String(500), nullable=False)
    pipeline_name = Column(String(255), nullable=False, index=True)
    checksum_sha256 = Column(String(64), nullable=False, index=True)
    pipeline_definition = Column(JSONB, nullable=True)  # Store for diff comparison
    activities_count = Column(Integer, nullable=True)
    last_modified = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id",
            "pipeline_name",
            "snapshot_date",
            name="uq_synapse_pipeline_checksum",
        ),
        Index("ix_synapse_pipeline_ws_date", "workspace_id", "snapshot_date"),
    )


class SynapsePipelineDrift(Base):
    """Detected drift events for Synapse pipelines."""

    __tablename__ = "synapse_pipeline_drifts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    detection_date = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    workspace_id = Column(String(500), nullable=False, index=True)
    workspace_name = Column(String(255), nullable=False)
    pipeline_name = Column(String(255), nullable=False, index=True)
    drift_type = Column(String(50), nullable=False)  # added, modified, deleted
    previous_checksum = Column(String(64), nullable=True)
    current_checksum = Column(String(64), nullable=True)
    previous_definition = Column(JSONB, nullable=True)
    current_definition = Column(JSONB, nullable=True)
    diff_summary = Column(JSONB, nullable=True)  # Structured diff output
    acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(String(255), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    compliance_status = Column(String(50), default="pending_review")

    __table_args__ = (
        Index("ix_synapse_drift_ws_date", "workspace_id", "detection_date"),
        Index("ix_synapse_drift_status", "compliance_status", "detection_date"),
    )


class AKSPodChecksum(Base):
    """Checksum tracking for AKS pod specifications."""

    __tablename__ = "aks_pod_checksums"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_date = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    cluster_id = Column(String(500), nullable=False, index=True)
    cluster_name = Column(String(255), nullable=False)
    namespace = Column(String(255), nullable=False, index=True)
    pod_name = Column(String(255), nullable=False, index=True)
    owner_kind = Column(String(100), nullable=True)  # Deployment, StatefulSet, DaemonSet
    owner_name = Column(String(255), nullable=True)
    checksum_sha256 = Column(String(64), nullable=False, index=True)

    # Checksums for specific components
    spec_checksum = Column(String(64), nullable=True)
    container_images_checksum = Column(String(64), nullable=True)
    env_vars_checksum = Column(String(64), nullable=True)
    volumes_checksum = Column(String(64), nullable=True)
    resource_limits_checksum = Column(String(64), nullable=True)

    # Stored data for comparison
    image_digests = Column(JSONB, nullable=True)  # Raw SHA256 digests from imageID
    container_images = Column(JSONB, nullable=True)
    env_vars = Column(JSONB, nullable=True)
    volumes = Column(JSONB, nullable=True)
    resource_limits = Column(JSONB, nullable=True)
    pod_spec = Column(JSONB, nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "cluster_id",
            "namespace",
            "pod_name",
            "snapshot_date",
            name="uq_aks_pod_checksum",
        ),
        Index("ix_aks_pod_cluster_ns_date", "cluster_id", "namespace", "snapshot_date"),
    )


class AKSPodDrift(Base):
    """Detected drift events for AKS pods."""

    __tablename__ = "aks_pod_drifts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    detection_date = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    cluster_id = Column(String(500), nullable=False, index=True)
    cluster_name = Column(String(255), nullable=False)
    namespace = Column(String(255), nullable=False, index=True)
    pod_name = Column(String(255), nullable=False, index=True)
    owner_kind = Column(String(100), nullable=True)
    owner_name = Column(String(255), nullable=True)
    drift_type = Column(String(50), nullable=False)  # image_change, config_drift, secret_change, resource_change
    drift_category = Column(String(100), nullable=False)  # container_image, env_vars, volumes, resources
    previous_value = Column(JSONB, nullable=True)
    current_value = Column(JSONB, nullable=True)
    previous_checksum = Column(String(64), nullable=True)  # raw SHA digest
    current_checksum = Column(String(64), nullable=True)  # raw SHA digest
    severity = Column(String(20), default="medium")  # low, medium, high, critical
    acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(String(255), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    compliance_status = Column(String(50), default="pending_review")

    __table_args__ = (
        Index("ix_aks_pod_drift_cluster_date", "cluster_id", "detection_date"),
        Index("ix_aks_pod_drift_severity", "severity", "detection_date"),
        Index("ix_aks_pod_drift_status", "compliance_status", "detection_date"),
    )


class ComplianceScore(Base):
    """Daily compliance scores for clusters and workspaces."""

    __tablename__ = "compliance_scores"

    id = Column(Integer, primary_key=True, autoincrement=True)
    score_date = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    resource_type = Column(String(50), nullable=False)  # aks_cluster, synapse_workspace
    resource_id = Column(String(500), nullable=False, index=True)
    resource_name = Column(String(255), nullable=False)
    subscription_id = Column(String(50), nullable=False, index=True)

    # Scores (0-100)
    overall_score = Column(Float, nullable=False)
    image_compliance_score = Column(Float, nullable=True)
    config_compliance_score = Column(Float, nullable=True)
    drift_score = Column(Float, nullable=True)

    # Counts
    total_resources = Column(Integer, default=0)
    compliant_resources = Column(Integer, default=0)
    drifted_resources = Column(Integer, default=0)
    critical_issues = Column(Integer, default=0)
    high_issues = Column(Integer, default=0)
    medium_issues = Column(Integer, default=0)
    low_issues = Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("resource_id", "score_date", name="uq_compliance_score"),
        Index("ix_compliance_score_type_date", "resource_type", "score_date"),
    )


class ChecksumRun(Base):
    """Run-level metadata for checksum verification executions.

    One row per workspace per execution.  Future modules (e.g. AKS) reuse
    the same table by setting ``module_type`` accordingly.
    """

    __tablename__ = "checksum_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    run_id = Column(String(36), nullable=False, unique=True, index=True)
    module_type = Column(String(20), nullable=False, index=True)  # "synapse" | "aks"
    system = Column(String(10), nullable=False, index=True)  # "attcc" | "ces"
    environment = Column(String(20), nullable=False, index=True)  # "prod" | "uat" | …
    workspace_name = Column(String(200), nullable=False, index=True)
    execution_date = Column(DateTime, nullable=False, index=True)

    total_pipelines = Column(Integer, default=0)
    passed = Column(Integer, default=0)
    failed = Column(Integer, default=0)
    status = Column(String(20), nullable=False, default="completed")  # completed | failed | timeout

    # Relationship to results
    results = relationship("ChecksumResult", back_populates="run", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_chk_run_date_sys", "execution_date", "system"),
        Index("ix_chk_run_module_env", "module_type", "environment"),
    )


class ChecksumResult(Base):
    """Per-pipeline result row linked to a :class:`ChecksumRun`.

    Stores the hash comparison for a single pipeline/artifact within a
    workspace verification run.
    """

    __tablename__ = "checksum_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    run_id = Column(String(36), ForeignKey("checksum_runs.run_id"), nullable=False, index=True)
    slno = Column(Integer, nullable=False)  # Serial number
    pipeline_name = Column(String(500), nullable=False, index=True)
    yesterday_hash = Column(String(64), nullable=True)  # raw SHA digest
    present_hash = Column(String(64), nullable=True)  # raw SHA digest
    last_published_date = Column(String(100), nullable=True)
    result = Column(String(10), nullable=False, index=True)  # "PASS" | "FAIL"

    # Flexible extra data
    details = Column(JSONB, default=dict)

    # Relationship back to run
    run = relationship("ChecksumRun", back_populates="results")

    __table_args__ = (Index("ix_chk_result_run_status", "run_id", "result"),)


class ChecksumScheduleConfig(Base):
    """Configuration for scheduled checksum runs."""

    __tablename__ = "checksum_schedule_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(255), nullable=False)

    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)

    # Target selection
    module_type = Column(String(20), nullable=False, index=True)  # synapse | aks
    system = Column(String(10), nullable=True, index=True)  # attcc | ces
    environment = Column(String(20), nullable=True, index=True)  # prod | uat | perf | poc
    workspace_name = Column(String(255), nullable=True, index=True)
    cluster_id = Column(String(500), nullable=True, index=True)
    cluster_name = Column(String(255), nullable=True)
    namespaces = Column(JSONB, default=list)

    # Schedule configuration
    schedule_type = Column(String(50), default="interval", nullable=False)  # interval | cron
    interval_hours = Column(Integer, default=24, nullable=False)
    cron_expression = Column(String(100), nullable=True)
    timezone = Column(String(50), default="UTC", nullable=False)

    # Notifications
    notification_emails = Column(JSONB, default=list)

    # Status tracking
    is_enabled = Column(Boolean, default=True, nullable=False)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index("ix_chk_schedule_module_env", "module_type", "environment"),
        Index("ix_chk_schedule_system", "system"),
    )


# =============================================================================
# INFRASTRUCTURE ALERT SYSTEM (Module 4)
# =============================================================================


class AlertSeverity(str, Enum):
    """Alert severity levels."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class AlertStatus(str, Enum):
    """Alert status values."""

    ACTIVE = "active"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"
    SNOOZED = "snoozed"


class ExpiryAlertType(str, Enum):
    """Types of expiry alerts."""

    MECH_ID = "mech_id"
    CERTIFICATE = "certificate"
    AAF_ACCOUNT = "aaf_account"
    DATABASE_ACCOUNT = "database_account"
    ITSERVICES_DOMAIN = "itservices_domain"


class VMThresholdAlertConfig(Base):
    """Configuration for VM threshold alerts (CPU, Memory, Disk)."""

    __tablename__ = "vm_threshold_alert_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(255), nullable=False)

    # VM identification
    subscription_id = Column(String(50), nullable=False, index=True)
    resource_group = Column(String(255), nullable=False)
    vm_name = Column(String(255), nullable=False, index=True)
    vm_id = Column(String(500), nullable=False, unique=True)

    # Thresholds (percentage 0-100)
    cpu_warning_threshold = Column(Float, default=70.0, nullable=False)
    cpu_critical_threshold = Column(Float, default=90.0, nullable=False)
    memory_warning_threshold = Column(Float, default=75.0, nullable=False)
    memory_critical_threshold = Column(Float, default=90.0, nullable=False)
    disk_warning_threshold = Column(Float, default=80.0, nullable=False)
    disk_critical_threshold = Column(Float, default=95.0, nullable=False)

    # Alert settings
    is_enabled = Column(Boolean, default=True, nullable=False)
    notification_emails = Column(JSONB, default=list)  # List of email addresses
    snooze_until = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_vm_threshold_sub_rg", "subscription_id", "resource_group"),)


class VMThresholdAlert(Base):
    """Active/historical VM threshold alerts."""

    __tablename__ = "vm_threshold_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    config_id = Column(Integer, ForeignKey("vm_threshold_alert_configs.id"), nullable=False)
    vm_id = Column(String(500), nullable=False, index=True)
    vm_name = Column(String(255), nullable=False)

    # Alert details
    metric_type = Column(String(50), nullable=False)  # cpu, memory, disk
    current_value = Column(Float, nullable=False)
    threshold_value = Column(Float, nullable=False)
    severity = Column(String(20), default="medium")  # warning, critical
    status = Column(String(50), default="active", index=True)  # active, acknowledged, resolved

    # Resolution tracking
    acknowledged_by = Column(String(255), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)

    config = relationship("VMThresholdAlertConfig", backref="alerts")

    __table_args__ = (
        Index("ix_vm_alert_status_date", "status", "created_at"),
        Index("ix_vm_alert_severity", "severity", "status"),
    )


class CustomExpiryAlertConfig(Base):
    """Configuration for custom expiry alerts (MechID, Certificates, etc.)."""

    __tablename__ = "custom_expiry_alert_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(255), nullable=False)

    # Alert type and identification
    alert_type = Column(
        String(50), nullable=False, index=True
    )  # mech_id, certificate, aaf_account, database_account, itservices_domain
    resource_name = Column(String(255), nullable=False, index=True)
    resource_identifier = Column(String(500), nullable=False)  # Unique ID for the resource
    description = Column(Text, nullable=True)

    # Environment classification so operators can tell prod vs non-prod accounts apart
    environment = Column(String(20), nullable=True)  # prod, non_prod

    # Expiry information
    expiry_date = Column(DateTime, nullable=False, index=True)

    # Alert thresholds (days before expiry to alert)
    warning_days_before = Column(Integer, default=30, nullable=False)
    critical_days_before = Column(Integer, default=7, nullable=False)

    # Alert settings
    is_enabled = Column(Boolean, default=True, nullable=False)
    notification_emails = Column(JSONB, default=list)
    snooze_until = Column(DateTime, nullable=True)

    # Additional metadata
    extra_data = Column(JSONB, default=dict)  # Extra info specific to alert type

    __table_args__ = (
        UniqueConstraint("alert_type", "resource_identifier", name="uq_expiry_alert_resource"),
        Index("ix_expiry_alert_type_date", "alert_type", "expiry_date"),
    )


class CustomExpiryAlert(Base):
    """Active/historical custom expiry alerts."""

    __tablename__ = "custom_expiry_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    config_id = Column(Integer, ForeignKey("custom_expiry_alert_configs.id"), nullable=False)
    alert_type = Column(String(50), nullable=False, index=True)
    resource_name = Column(String(255), nullable=False)

    # Alert details
    expiry_date = Column(DateTime, nullable=False)
    days_until_expiry = Column(Integer, nullable=False)
    severity = Column(String(20), default="medium")  # warning, critical
    status = Column(String(50), default="active", index=True)  # active, acknowledged, resolved, expired

    # Resolution tracking
    acknowledged_by = Column(String(255), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)

    config = relationship("CustomExpiryAlertConfig", backref="alerts")

    __table_args__ = (
        Index("ix_expiry_alert_status_date", "status", "created_at"),
        Index("ix_expiry_alert_expiry", "expiry_date", "status"),
    )


class AlertNotificationHistory(Base):
    """History of alert notifications sent."""

    __tablename__ = "alert_notification_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sent_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    alert_type = Column(String(50), nullable=False)  # vm_threshold, custom_expiry
    alert_id = Column(Integer, nullable=False)
    recipient_email = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=True)  # email subject line
    notification_method = Column(String(50), default="email")  # email, teams, slack
    status = Column(String(50), default="sent")  # sent, failed, bounced
    error_message = Column(Text, nullable=True)

    __table_args__ = (Index("ix_notification_alert_type_id", "alert_type", "alert_id"),)


class AzureResourceInventory(Base):
    """Azure resource inventory cache for VMs, Storage, Disks, etc."""

    __tablename__ = "azure_resource_inventory"

    id = Column(Integer, primary_key=True, autoincrement=True)
    last_sync = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Resource identification
    resource_id = Column(String(1000), nullable=False, unique=True)  # Azure resource ID
    name = Column(String(255), nullable=False, index=True)
    resource_type = Column(
        String(100), nullable=False, index=True
    )  # virtual_machine, storage_account, managed_disk, etc.
    resource_group = Column(String(255), nullable=False, index=True)
    location = Column(String(100), nullable=True)
    subscription_id = Column(String(50), nullable=False, index=True)

    # Status
    provisioning_state = Column(String(50), nullable=True)

    # Metadata
    tags = Column(JSONB, default=dict)
    resource_details = Column(JSONB, default=dict)  # Full resource details

    __table_args__ = (
        Index("ix_resource_type_rg", "resource_type", "resource_group"),
        Index("ix_resource_subscription", "subscription_id", "resource_type"),
    )


class StorageAlertConfig(Base):
    """Configuration for Storage account threshold alerts."""

    __tablename__ = "storage_alert_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(255), nullable=False)

    # Storage account identification
    subscription_id = Column(String(50), nullable=False, index=True)
    resource_group = Column(String(255), nullable=False)
    account_name = Column(String(255), nullable=False, index=True)
    account_id = Column(String(500), nullable=False, unique=True)

    # Capacity thresholds (in GB)
    capacity_warning_gb = Column(Float, default=100.0, nullable=False)
    capacity_critical_gb = Column(Float, default=500.0, nullable=False)

    # Transaction thresholds
    transactions_warning = Column(Integer, default=100000, nullable=False)
    transactions_critical = Column(Integer, default=500000, nullable=False)

    # Egress thresholds (in GB)
    egress_warning_gb = Column(Float, default=50.0, nullable=False)
    egress_critical_gb = Column(Float, default=200.0, nullable=False)

    # Alert settings
    is_enabled = Column(Boolean, default=True, nullable=False)
    notification_emails = Column(JSONB, default=list)
    snooze_until = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_storage_alert_sub_rg", "subscription_id", "resource_group"),)


class DiskAlertConfig(Base):
    """Configuration for Managed Disk threshold alerts."""

    __tablename__ = "disk_alert_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(255), nullable=False)

    # Disk identification
    subscription_id = Column(String(50), nullable=False, index=True)
    resource_group = Column(String(255), nullable=False)
    disk_name = Column(String(255), nullable=False, index=True)
    disk_id = Column(String(500), nullable=False, unique=True)

    # IOPS thresholds (percentage of max)
    iops_warning_percent = Column(Float, default=70.0, nullable=False)
    iops_critical_percent = Column(Float, default=90.0, nullable=False)

    # Throughput thresholds (percentage of max)
    throughput_warning_percent = Column(Float, default=70.0, nullable=False)
    throughput_critical_percent = Column(Float, default=90.0, nullable=False)

    # Used capacity thresholds (percentage)
    capacity_warning_percent = Column(Float, default=80.0, nullable=False)
    capacity_critical_percent = Column(Float, default=95.0, nullable=False)

    # Alert settings
    is_enabled = Column(Boolean, default=True, nullable=False)
    notification_emails = Column(JSONB, default=list)
    snooze_until = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_disk_alert_sub_rg", "subscription_id", "resource_group"),)


class AlertScheduleConfig(Base):
    """Configuration for scheduled alert checks."""

    __tablename__ = "alert_schedule_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(255), nullable=False)

    # Schedule identification
    name = Column(String(255), nullable=False, unique=True)
    description = Column(Text, nullable=True)

    # Schedule settings (cron format or interval)
    schedule_type = Column(String(50), default="interval", nullable=False)  # interval, cron
    interval_minutes = Column(Integer, default=15, nullable=False)
    cron_expression = Column(String(100), nullable=True)

    # Alert types to check
    check_vm_thresholds = Column(Boolean, default=True, nullable=False)
    check_storage_thresholds = Column(Boolean, default=True, nullable=False)
    check_disk_thresholds = Column(Boolean, default=True, nullable=False)
    check_expiry_alerts = Column(Boolean, default=True, nullable=False)

    # Email digest settings
    send_daily_digest = Column(Boolean, default=True, nullable=False)
    digest_time_utc = Column(String(10), default="08:00", nullable=False)
    digest_recipients = Column(JSONB, default=list)

    # PostgreSQL Flexible Server checks
    check_pg_thresholds = Column(Boolean, default=True, nullable=False)

    # Status
    is_enabled = Column(Boolean, default=True, nullable=False)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)


class PGFlexServerAlertConfig(Base):
    """Configuration for PostgreSQL Flexible Server threshold alerts (CPU, Memory, Storage)."""

    __tablename__ = "pg_flex_server_alert_configs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    created_by = Column(String(255), nullable=False)

    # Server identification
    subscription_id = Column(String(50), nullable=False, index=True)
    resource_group = Column(String(255), nullable=False)
    server_name = Column(String(255), nullable=False, index=True)
    server_id = Column(String(500), nullable=False, unique=True)

    # Thresholds (percentage 0-100)
    cpu_warning_threshold = Column(Float, default=70.0, nullable=False)
    cpu_critical_threshold = Column(Float, default=90.0, nullable=False)
    memory_warning_threshold = Column(Float, default=75.0, nullable=False)
    memory_critical_threshold = Column(Float, default=90.0, nullable=False)
    storage_warning_threshold = Column(Float, default=80.0, nullable=False)
    storage_critical_threshold = Column(Float, default=95.0, nullable=False)

    # Alert settings
    is_enabled = Column(Boolean, default=True, nullable=False)
    notification_emails = Column(JSONB, default=list)  # List of email addresses
    snooze_until = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_pg_flex_alert_sub_rg", "subscription_id", "resource_group"),)


class PGFlexServerAlert(Base):
    """Active/historical PostgreSQL Flexible Server threshold alerts."""

    __tablename__ = "pg_flex_server_alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    config_id = Column(Integer, ForeignKey("pg_flex_server_alert_configs.id"), nullable=False)
    server_id = Column(String(500), nullable=False, index=True)
    server_name = Column(String(255), nullable=False)

    # Alert details
    metric_type = Column(String(50), nullable=False)  # cpu, memory, storage
    current_value = Column(Float, nullable=False)
    threshold_value = Column(Float, nullable=False)
    severity = Column(String(20), default="medium")  # warning, critical
    status = Column(String(50), default="active", index=True)  # active, acknowledged, resolved

    # Resolution tracking
    acknowledged_by = Column(String(255), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    resolution_notes = Column(Text, nullable=True)

    config = relationship("PGFlexServerAlertConfig", backref="alerts")

    __table_args__ = (
        Index("ix_pg_alert_status_date", "status", "created_at"),
        Index("ix_pg_alert_severity", "severity", "status"),
    )


# =============================================================================
# MODULE 5: KEY VAULT CACHE (Persistent PG-backed vault/secret/key/cert cache)
# =============================================================================


class KeyVaultSnapshot(Base):
    """Cached snapshot of a discovered Azure Key Vault."""

    __tablename__ = "kv_vaults"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_uri = Column(String(500), nullable=False, unique=True, index=True)
    name = Column(String(255), nullable=False, index=True)
    resource_id = Column(String(1000), nullable=True)
    location = Column(String(100), nullable=True)
    resource_group = Column(String(255), nullable=True)
    subscription_id = Column(String(100), nullable=True, index=True)
    tenant_id = Column(String(100), nullable=True)
    soft_delete_enabled = Column(Boolean, default=False)
    purge_protection_enabled = Column(Boolean, default=False)
    rbac_enabled = Column(Boolean, default=False)
    provisioning_state = Column(String(50), nullable=True)
    sku = Column(String(50), nullable=True)
    tags = Column(JSONB, default=dict)

    secrets_count = Column(Integer, default=0)
    keys_count = Column(Integer, default=0)
    certificates_count = Column(Integer, default=0)

    synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    # Relationships
    secrets = relationship("KeyVaultSecretSnapshot", back_populates="vault", cascade="all, delete-orphan")
    keys = relationship("KeyVaultKeySnapshot", back_populates="vault", cascade="all, delete-orphan")
    certificates = relationship("KeyVaultCertSnapshot", back_populates="vault", cascade="all, delete-orphan")

    __table_args__ = (Index("ix_kv_vaults_sub_name", "subscription_id", "name"),)


class KeyVaultSecretSnapshot(Base):
    """Cached metadata for a Key Vault secret (never stores the value)."""

    __tablename__ = "kv_secrets"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_id = Column(
        Integer,
        ForeignKey("kv_vaults.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    secret_id = Column(String(1000), nullable=True)
    content_type = Column(String(255), nullable=True)
    enabled = Column(Boolean, default=True)
    created = Column(String(50), nullable=True)
    updated = Column(String(50), nullable=True)
    expires = Column(String(50), nullable=True)
    not_before = Column(String(50), nullable=True)
    managed = Column(Boolean, default=False)
    tags = Column(JSONB, default=dict)
    synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    vault = relationship("KeyVaultSnapshot", back_populates="secrets")

    __table_args__ = (
        UniqueConstraint("vault_id", "name", name="uq_kv_secret_vault_name"),
        Index("ix_kv_secrets_expires", "expires"),
    )


class KeyVaultKeySnapshot(Base):
    """Cached metadata for a Key Vault key."""

    __tablename__ = "kv_keys"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_id = Column(
        Integer,
        ForeignKey("kv_vaults.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    kid = Column(String(1000), nullable=True)
    enabled = Column(Boolean, default=True)
    created = Column(String(50), nullable=True)
    updated = Column(String(50), nullable=True)
    expires = Column(String(50), nullable=True)
    not_before = Column(String(50), nullable=True)
    managed = Column(Boolean, default=False)
    tags = Column(JSONB, default=dict)
    synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    vault = relationship("KeyVaultSnapshot", back_populates="keys")

    __table_args__ = (
        UniqueConstraint("vault_id", "name", name="uq_kv_key_vault_name"),
        Index("ix_kv_keys_expires", "expires"),
    )


class KeyVaultCertSnapshot(Base):
    """Cached metadata for a Key Vault certificate."""

    __tablename__ = "kv_certificates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    vault_id = Column(
        Integer,
        ForeignKey("kv_vaults.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name = Column(String(255), nullable=False)
    cert_id = Column(String(1000), nullable=True)
    enabled = Column(Boolean, default=True)
    created = Column(String(50), nullable=True)
    updated = Column(String(50), nullable=True)
    expires = Column(String(50), nullable=True)
    not_before = Column(String(50), nullable=True)
    cn_name = Column(String(500), nullable=True)
    san = Column(JSONB, default=list)
    serial_number = Column(String(255), nullable=True)
    thumbprint = Column(String(100), nullable=True)
    tags = Column(JSONB, default=dict)
    synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    vault = relationship("KeyVaultSnapshot", back_populates="certificates")

    __table_args__ = (
        UniqueConstraint("vault_id", "name", name="uq_kv_cert_vault_name"),
        Index("ix_kv_certs_expires", "expires"),
    )


class KeyVaultSyncStatus(Base):
    """Tracks the last successful sync job for KeyVault data."""

    __tablename__ = "kv_sync_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sync_type = Column(String(50), nullable=False, index=True)  # 'full', 'vault', 'incremental'
    status = Column(String(20), nullable=False, default="running")  # running, completed, failed
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    vaults_synced = Column(Integer, default=0)
    secrets_synced = Column(Integer, default=0)
    keys_synced = Column(Integer, default=0)
    certificates_synced = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    triggered_by = Column(String(100), nullable=True)  # 'scheduler', 'manual', 'mutation'


# =============================================================================
# MODULE 6: ENVIRONMENT DAILY COST (Auto-synced from Azure Cost Management API)
# =============================================================================


class EnvDailyCost(Base):
    """Daily cost per environment, synced from Azure Cost Management API.

    Each row stores the total cost for one environment on one date,
    separated by subscription type (prod / nonprod).
    """

    __tablename__ = "env_daily_costs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subscription_type = Column(
        String(20),
        nullable=False,
        index=True,
    )  # 'prod' or 'nonprod'
    environment = Column(
        String(30),
        nullable=False,
        index=True,
    )  # PROD, DR, DEV, PERF, POC, STAGE, TEST, UAT, MISC
    cost_date = Column(DateTime, nullable=False, index=True)  # date of the cost
    cost_amount = Column(Float, nullable=False, default=0.0)
    currency = Column(String(10), nullable=False, default="USD")
    synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint(
            "subscription_type",
            "environment",
            "cost_date",
            name="uq_env_daily_cost_type_env_date",
        ),
        Index("ix_env_daily_cost_date_range", "cost_date", "subscription_type"),
        Index("ix_env_daily_cost_env", "environment", "cost_date"),
    )


class EnvCostSyncStatus(Base):
    """Tracks sync jobs for environment daily cost data."""

    __tablename__ = "env_cost_sync_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sync_type = Column(String(50), nullable=False, index=True)  # 'full', 'incremental'
    status = Column(String(20), nullable=False, default="running")  # running, completed, failed, partial
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    days_synced = Column(Integer, default=0)
    environments_synced = Column(Integer, default=0)
    total_cost = Column(Float, default=0.0)
    error_message = Column(Text, nullable=True)
    triggered_by = Column(String(100), nullable=True)  # 'scheduler', 'manual', 'startup'


# =============================================================================
# ADMIN CONFIGURATION MODELS
# =============================================================================


class AdminSubscription(Base):
    """Managed Azure subscriptions — persisted in DB so admins can
    enable / disable monitoring from the Admin panel."""

    __tablename__ = "admin_subscriptions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    subscription_id = Column(String(50), nullable=False, unique=True, index=True)
    subscription_name = Column(String(255), nullable=False)
    state = Column(String(50), nullable=True, default="Unknown")
    enabled = Column(Boolean, nullable=False, default=True)
    monitored = Column(Boolean, nullable=False, default=True)
    environment = Column(String(50), nullable=True)  # dev, staging, prod, etc.
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(String(255), nullable=True)
    updated_by = Column(String(255), nullable=True)

    __table_args__ = (Index("ix_admin_sub_enabled", "enabled"),)


class UserSubscriptionPreference(Base):
    """Per-user subscription picker scope (does not affect other users)."""

    __tablename__ = "user_subscription_preferences"

    user_id = Column(String(255), primary_key=True)
    selected_subscription_ids = Column(Text, nullable=False, default="[]")
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class AdminConfig(Base):
    """Key-value admin configuration stored in DB so it can be
    managed through the Admin panel without redeploying."""

    __tablename__ = "admin_config"

    id = Column(Integer, primary_key=True, autoincrement=True)
    config_key = Column(String(255), nullable=False, unique=True, index=True)
    config_value = Column(Text, nullable=False)
    config_type = Column(String(20), nullable=False, default="string")  # string, int, bool, json
    description = Column(Text, nullable=True)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by = Column(String(255), nullable=True)

    __table_args__ = (Index("ix_admin_config_key", "config_key"),)


# =============================================================================
# MODULE 8: AMORTIZED COST (DB-cached from Azure Cost Management APIs)
# =============================================================================


class AmortizedCostRecord(Base):
    """Individual amortized cost line items synced from Azure Cost Management APIs.

    Each row mirrors a single detailed cost record so that analytics can be built
    from SQL instead of re-querying Azure on every request. The table is
    truncated-and-reloaded on each sync for the selected date window.
    """

    __tablename__ = "amortized_cost_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cost_date = Column(String(10), nullable=False, index=True)  # YYYY-MM-DD
    cost_amount = Column(Float, nullable=False, default=0.0)
    meter_category = Column(String(255), nullable=True)
    meter_subcategory = Column(String(255), nullable=True)
    meter_name = Column(String(255), nullable=True)
    resource_group = Column(String(255), nullable=True, index=True)
    resource_name = Column(String(500), nullable=True)
    resource_type = Column(String(255), nullable=True)
    resource_location = Column(String(100), nullable=True)
    subscription_name = Column(String(255), nullable=True)
    subscription_id = Column(String(50), nullable=True, index=True)
    service_name = Column(String(255), nullable=True)
    charge_type = Column(String(100), nullable=True)
    pricing_model = Column(String(100), nullable=True)
    publisher_type = Column(String(100), nullable=True)
    frequency = Column(String(50), nullable=True)
    currency = Column(String(10), nullable=False, default="USD")
    env_label = Column(String(20), nullable=False, index=True)  # Prod / Non-Prod
    synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_amortized_date_env", "cost_date", "env_label"),
        Index("ix_amortized_meter_cat", "meter_category"),
        Index("ix_amortized_sub_name", "subscription_name"),
    )


class AmortizedCostSyncStatus(Base):
    """Tracks sync jobs for amortized cost data from Azure Cost Management APIs."""

    __tablename__ = "amortized_cost_sync_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sync_type = Column(String(50), nullable=False, index=True)  # 'full'
    status = Column(String(20), nullable=False, default="running")  # running, completed, failed
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    months_synced = Column(Integer, default=0)
    rows_synced = Column(Integer, default=0)
    total_cost = Column(Float, default=0.0)
    error_message = Column(Text, nullable=True)
    triggered_by = Column(String(100), nullable=True)  # 'startup', 'manual', 'scheduler'


class AmortizedCostDailySummary(Base):
    """Daily aggregated amortized cost summary for faster time-series queries."""

    __tablename__ = "amortized_cost_daily_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cost_date = Column(String(10), nullable=False, unique=True, index=True)  # YYYY-MM-DD
    total_cost = Column(Float, nullable=False, default=0.0)
    production_cost = Column(Float, nullable=False, default=0.0)
    non_production_cost = Column(Float, nullable=False, default=0.0)
    service_count = Column(Integer, nullable=False, default=0)
    resource_count = Column(Integer, nullable=False, default=0)
    aggregated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (Index("ix_daily_summary_date", "cost_date"),)


class AmortizedCostWeeklySummary(Base):
    """Weekly aggregated amortized cost summary for trend analysis."""

    __tablename__ = "amortized_cost_weekly_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start_date = Column(String(10), nullable=False, unique=True, index=True)  # YYYY-MM-DD (Monday)
    total_cost = Column(Float, nullable=False, default=0.0)
    production_cost = Column(Float, nullable=False, default=0.0)
    non_production_cost = Column(Float, nullable=False, default=0.0)
    service_count = Column(Integer, nullable=False, default=0)
    resource_count = Column(Integer, nullable=False, default=0)
    aggregated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (Index("ix_weekly_summary_date", "week_start_date"),)


class AmortizedCostMonthlySummary(Base):
    """Monthly aggregated amortized cost summary for billing and reporting."""

    __tablename__ = "amortized_cost_monthly_summary"

    id = Column(Integer, primary_key=True, autoincrement=True)
    month_year = Column(String(7), nullable=False, unique=True, index=True)  # YYYY-MM
    total_cost = Column(Float, nullable=False, default=0.0)
    production_cost = Column(Float, nullable=False, default=0.0)
    non_production_cost = Column(Float, nullable=False, default=0.0)
    service_count = Column(Integer, nullable=False, default=0)
    resource_count = Column(Integer, nullable=False, default=0)
    aggregated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (Index("ix_monthly_summary_date", "month_year"),)


class LeadershipDashboardSnapshot(Base):
    """Stores pre-computed leadership dashboard data for fast loading."""

    __tablename__ = "leadership_dashboard_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_date = Column(DateTime, nullable=False, index=True)
    payload = Column(Text, nullable=False)  # JSON-serialised dashboard response
    environment = Column(String(20), nullable=False, default="ALL")
    synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    triggered_by = Column(String(100), nullable=True)

    __table_args__ = (Index("ix_leadership_snap_date_env", "snapshot_date", "environment"),)


class LeadershipSyncStatus(Base):
    """Tracks sync jobs for leadership dashboard data."""

    __tablename__ = "leadership_sync_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sync_type = Column(String(50), nullable=False, default="full")
    status = Column(String(20), nullable=False, default="running")
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    triggered_by = Column(String(100), nullable=True)


class SyncJob(Base):
    """Generic queue row driving the SyncWorker background loop.

    Replaces the request-blocking pattern (``POST /sync`` runs the sync
    synchronously) with a queue: callers insert a row, the worker picks it
    up, the UI polls status by ``id``. Idempotency: the worker treats a
    ``(job_type, idempotency_key)`` already in ``queued`` or ``running`` as
    the same job, so a frenzied "Refresh Data" click won't pile up jobs.
    """

    __tablename__ = "sync_jobs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_type = Column(String(50), nullable=False, index=True)  # 'amortized' | 'leadership'
    status = Column(String(20), nullable=False, default="queued", index=True)
    idempotency_key = Column(String(120), nullable=True, index=True)
    payload = Column(Text, nullable=True)  # JSON-encoded job params (months, force, etc.)
    triggered_by = Column(String(100), nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    result = Column(Text, nullable=True)  # JSON-encoded final result payload
    enqueued_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    __table_args__ = (Index("ix_sync_jobs_type_status", "job_type", "status"),)


class ComplianceDashboardSnapshot(Base):
    """Stores pre-computed compliance dashboard data for fast loading."""

    __tablename__ = "compliance_dashboard_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_type = Column(String(50), nullable=False, default="dashboard")
    snapshot_date = Column(DateTime, nullable=False, index=True)
    payload = Column(Text, nullable=False)
    synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    triggered_by = Column(String(100), nullable=True)

    __table_args__ = (Index("ix_compliance_snap_type_date", "snapshot_type", "snapshot_date"),)


class ComplianceSyncStatus(Base):
    """Tracks sync jobs for compliance dashboard data."""

    __tablename__ = "compliance_sync_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sync_type = Column(String(50), nullable=False, default="full")
    status = Column(String(20), nullable=False, default="running")
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    triggered_by = Column(String(100), nullable=True)


# =============================================================================
# PAGE / APPLICATION CACHE (replaces Redis)
# =============================================================================


# =============================================================================
# MODULE: CERTIFICATE MANAGEMENT (Cached from Keyfactor Command for fast loads)
# =============================================================================


class CertificateCollectionSnapshot(Base):
    """Cached Keyfactor certificate collection for fast listing."""

    __tablename__ = "cert_collections"

    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(Integer, nullable=False, unique=True, index=True)
    name = Column(String(500), nullable=False, index=True)
    description = Column(Text, nullable=True)
    query = Column(Text, nullable=True)
    certificate_count = Column(Integer, default=0)
    synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)


class CertificateSnapshot(Base):
    """Cached Keyfactor certificate (scoped per collection) for fast listing."""

    __tablename__ = "cert_certificates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    collection_id = Column(Integer, nullable=False, index=True)
    certificate_id = Column(Integer, nullable=False, index=True)  # Keyfactor certificate Id
    common_name = Column(String(500), nullable=True, index=True)
    subject_dn = Column(Text, nullable=True)
    issuer_dn = Column(Text, nullable=True)
    serial_number = Column(String(255), nullable=True)
    thumbprint = Column(String(100), nullable=True, index=True)
    template = Column(String(500), nullable=True)
    certificate_authority = Column(String(500), nullable=True)
    not_before = Column(String(50), nullable=True)
    not_after = Column(String(50), nullable=True, index=True)
    import_date = Column(String(50), nullable=True)
    effective_date = Column(String(50), nullable=True)
    sans = Column(JSONB, default=list)
    san_count = Column(Integer, default=0)
    revoked = Column(Boolean, default=False)
    revocation_reason = Column(Integer, nullable=True)
    status = Column(String(30), nullable=True, index=True)
    cert_metadata = Column(JSONB, default=dict)
    key_algorithm = Column(String(50), nullable=True)
    key_size = Column(Integer, default=0)
    key_usage = Column(String(500), nullable=True)
    extended_key_usage = Column(String(500), nullable=True)
    signing_algorithm = Column(String(100), nullable=True)
    requester = Column(String(255), nullable=True)
    principal_name = Column(String(255), nullable=True)
    locations = Column(JSONB, default=list)
    location_count = Column(Integer, default=0)
    collection = Column(String(500), nullable=True)
    has_private_key = Column(Boolean, nullable=True, default=False)
    synced_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        UniqueConstraint("collection_id", "certificate_id", name="uq_cert_collection_cert"),
        Index("ix_cert_certs_cn_status", "common_name", "status"),
    )


class CertificateKeyEscrow(Base):
    """Pointer to a certificate's escrowed PFX in the dedicated escrow Key Vault.

    Deliberately holds no key material: the PFX and the password protecting it
    live in the Key Vault secret named by ``secret_name``, which is where the
    HSM storage, RBAC, soft-delete and Azure audit trail come from. This table
    is separate from ``cert_certificates`` on purpose — that snapshot is deleted
    per collection on every sync, which would destroy escrow bookkeeping.

    ``thumbprint`` is stored lowercase so lookups are case-insensitive against
    Keyfactor (uppercase) and Key Vault secret names (lowercase).
    """

    __tablename__ = "cert_key_escrow"

    id = Column(Integer, primary_key=True, autoincrement=True)
    certificate_id = Column(Integer, nullable=False, index=True)  # Keyfactor certificate Id
    thumbprint = Column(String(100), nullable=False, index=True)
    common_name = Column(String(500), nullable=True)
    vault_name = Column(String(255), nullable=False)
    secret_name = Column(String(127), nullable=False)
    # Filled in by escrow reconciliation once the certificate appears in a
    # synced collection; purge never runs against an unknown expiry.
    not_after = Column(String(50), nullable=True, index=True)
    source = Column(String(20), nullable=False, default="renew")  # enroll | renew
    escrowed_by = Column(String(255), nullable=True)
    escrowed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    purged_at = Column(DateTime, nullable=True)

    __table_args__ = (UniqueConstraint("thumbprint", name="uq_cert_escrow_thumbprint"),)


class CertificateSyncStatus(Base):
    """Tracks the last certificate sync job (Keyfactor → PostgreSQL)."""

    __tablename__ = "cert_sync_status"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sync_type = Column(String(50), nullable=False, index=True)  # 'full', 'collection'
    status = Column(String(20), nullable=False, default="running")  # running, completed, partial, failed
    started_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    collections_synced = Column(Integer, default=0)
    certificates_synced = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    triggered_by = Column(String(100), nullable=True)  # 'scheduler', 'manual', 'mutation', 'startup'


class PageCache(Base):
    """Key-value cache stored in PostgreSQL, replacing Redis for page/application caching."""

    __tablename__ = "page_cache"

    id = Column(Integer, primary_key=True, autoincrement=True)
    cache_key = Column(String(512), nullable=False, unique=True, index=True)
    payload = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=True, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class StartupTaskLock(Base):
    """Distributed startup task lock stored in PostgreSQL, replacing Redis SET NX."""

    __tablename__ = "startup_task_locks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_name = Column(String(255), nullable=False, unique=True, index=True)
    locked_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)


# =============================================================================
# MODULE 6: ENVIRONMENT SCALING & SCHEDULING
# =============================================================================


class EnvironmentSchedule(Base):
    """Scheduled environment scaling jobs."""

    __tablename__ = "environment_schedules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    job_name = Column(String(255), nullable=False, index=True)
    cluster_id = Column(String(500), nullable=False, index=True)
    namespace = Column(String(255), nullable=False, index=True)
    operation = Column(String(50), nullable=False)  # scale_up, scale_down
    replica_count = Column(Integer, nullable=False, default=1)
    schedule_type = Column(String(50), nullable=False)  # one_time, daily, weekly, monthly, cron
    cron_expression = Column(String(255), nullable=True)
    timezone = Column(String(100), nullable=False, default="UTC")
    start_date = Column(DateTime, nullable=True)
    end_date = Column(DateTime, nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=True)
    retry_count = Column(Integer, nullable=False, default=3)
    failure_notification = Column(String(500), nullable=True)  # email or webhook
    sequence_id = Column(Integer, ForeignKey("environment_sequences.id"), nullable=True)
    created_by = Column(String(255), nullable=False)
    created_by_email = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, nullable=True)
    last_run_status = Column(String(50), nullable=True)

    __table_args__ = (
        Index("ix_env_schedule_cluster_ns", "cluster_id", "namespace"),
        Index("ix_env_schedule_enabled", "is_enabled", "next_run_at"),
    )


class EnvironmentSequence(Base):
    """Startup/shutdown sequence definitions for ordered deployment scaling."""

    __tablename__ = "environment_sequences"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(255), nullable=False, index=True)
    cluster_id = Column(String(500), nullable=False, index=True)
    namespace = Column(String(255), nullable=False, index=True)
    sequence_type = Column(String(50), nullable=False)  # startup, shutdown
    steps = Column(JSONB, nullable=False)  # [{order, deployment_name, replicas, wait_condition, timeout_seconds}]
    rollback_on_failure = Column(Boolean, nullable=False, default=True)
    created_by = Column(String(255), nullable=False)
    created_by_email = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    __table_args__ = (
        UniqueConstraint("name", "cluster_id", "namespace", name="uq_env_sequence_name_cluster_ns"),
        Index("ix_env_sequence_cluster_ns", "cluster_id", "namespace"),
    )


class EnvironmentExecutionHistory(Base):
    """Execution history for environment scaling operations."""

    __tablename__ = "environment_execution_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    execution_type = Column(String(50), nullable=False)  # manual, scheduled, sequence
    cluster_id = Column(String(500), nullable=False, index=True)
    namespace = Column(String(255), nullable=False, index=True)
    operation = Column(String(50), nullable=False)  # scale_up, scale_down, sequence_start, sequence_stop
    status = Column(String(50), nullable=False, default="running")  # running, completed, failed, rolled_back
    total_deployments = Column(Integer, nullable=False, default=0)
    completed_count = Column(Integer, nullable=False, default=0)
    failed_count = Column(Integer, nullable=False, default=0)
    skipped_count = Column(Integer, nullable=False, default=0)
    replica_count = Column(Integer, nullable=True)
    schedule_id = Column(Integer, nullable=True)
    sequence_id = Column(Integer, nullable=True)
    step_details = Column(JSONB, nullable=True)  # [{deployment, status, old_replicas, new_replicas, error}]
    initiated_by = Column(String(255), nullable=False)
    initiated_by_email = Column(String(255), nullable=True)
    started_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    completed_at = Column(DateTime, nullable=True)
    duration_seconds = Column(Float, nullable=True)
    error_message = Column(Text, nullable=True)

    __table_args__ = (
        Index("ix_env_exec_cluster_ns", "cluster_id", "namespace"),
        Index("ix_env_exec_started", "started_at"),
    )


# =============================================================================
# DATABASE ENGINE SETUP
# =============================================================================


def create_database_engine():
    """Create SQLAlchemy engine with connection pool."""
    engine = create_engine(
        settings.DATABASE_URL,
        pool_size=10,
        max_overflow=20,
        pool_pre_ping=True,
        pool_recycle=3600,
        echo=settings.DEBUG,
    )
    return engine


def create_session_factory(engine):
    """Create session factory for database operations."""
    return sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_database(engine):
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)
