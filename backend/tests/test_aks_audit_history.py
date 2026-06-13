"""Tests for AKS audit history endpoint."""

from datetime import UTC, datetime

from app.api.v1.endpoints.aks_operations import _audit_summary, _serialize_aks_audit_entry
from app.models.database import AuditLog


def test_audit_summary_scale_deployment():
    assert "Scaled" in _audit_summary("scale_deployment", "deployment", "api")


def test_serialize_aks_audit_entry():
    entry = AuditLog(
        id=1,
        user_id="u1",
        user_email="user@test.com",
        action="create_secret",
        resource_type="secret",
        resource_id="my-secret",
        details={
            "page": "AKSOperationsPage",
            "cluster_id": "/subscriptions/x/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/c1",
            "cluster_name": "c1",
            "namespace": "default",
            "resource_name": "my-secret",
            "summary": "Created secret my-secret",
        },
        status="success",
        timestamp=datetime.now(UTC),
    )
    serialized = _serialize_aks_audit_entry(entry)
    assert serialized["action"] == "create_secret"
    assert serialized["resource_name"] == "my-secret"
    assert serialized["cluster_name"] == "c1"
