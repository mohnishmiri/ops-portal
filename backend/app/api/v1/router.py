"""
API v1 Router — aggregates all endpoint routers.
"""

from fastapi import APIRouter

from app.api.v1.endpoints import (
    admin,
    aks_operations,
    auth,
    checksum_schedules,
    compliance,
    costs,
    dashboards,
    infra_alerts,
    keyvault,
    notifications,
    optimization,
    permissions,
    reports,
)

api_router = APIRouter()

# Auth — user context & role introspection
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])

# Module 1: Cost Visibility & FinOps Intelligence
api_router.include_router(costs.router, prefix="/costs", tags=["costs"])
api_router.include_router(optimization.router, prefix="/optimize", tags=["optimization"])
api_router.include_router(dashboards.router, prefix="/dashboards", tags=["dashboards"])
api_router.include_router(reports.router, prefix="/reports", tags=["reports"])
api_router.include_router(notifications.router, prefix="/notifications", tags=["notifications"])
api_router.include_router(admin.router, prefix="/admin", tags=["admin"])
api_router.include_router(keyvault.router, prefix="/keyvault", tags=["keyvault"])

# Module 2: AKS Operations & Control Center
api_router.include_router(aks_operations.router, prefix="/aks", tags=["aks-operations"])

# Module 3: Compliance & Drift Detection
api_router.include_router(compliance.router, prefix="/compliance", tags=["compliance"])

# Access Control Management (Admin)
api_router.include_router(permissions.router, prefix="/permissions", tags=["permissions"])

# Module 4: Infrastructure Alerts
api_router.include_router(infra_alerts.router, prefix="/infra-alerts", tags=["infra-alerts"])

# Module 5: Checksum Schedule Management
api_router.include_router(checksum_schedules.router, prefix="/checksum-schedules", tags=["checksum-schedules"])
