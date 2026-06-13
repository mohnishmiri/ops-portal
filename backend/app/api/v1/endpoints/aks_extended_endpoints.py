"""Extended AKS endpoints — resources, live watch, audit history."""

from datetime import UTC, datetime, timedelta

import structlog
from fastapi import Depends, HTTPException, Query, Request, WebSocket, WebSocketException
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user, get_current_user_from_token, require_role
from app.core.database import get_db
from app.models.auth import UserContext, UserRole
from app.models.database import AuditLog

logger = structlog.get_logger(__name__)


class CreateSecretRequest(BaseModel):
    cluster_id: str
    namespace: str
    name: str
    data: dict[str, str]
    secret_type: str = "Opaque"


class UpdateSecretRequest(BaseModel):
    cluster_id: str
    namespace: str
    name: str
    data: dict[str, str]


class CreateServiceRequest(BaseModel):
    cluster_id: str
    namespace: str
    name: str
    port: int = Field(ge=1, le=65535)
    target_port: int | str
    selector: dict[str, str]
    service_type: str = "ClusterIP"


class CreateConfigMapRequest(BaseModel):
    cluster_id: str
    namespace: str
    name: str
    data: dict[str, str]


class IngressPathRequest(BaseModel):
    path: str = "/"
    path_type: str = "Prefix"
    service_name: str
    service_port: int


class IngressRuleRequest(BaseModel):
    host: str | None = None
    paths: list[IngressPathRequest]


class IngressTLSRequest(BaseModel):
    hosts: list[str] | None = None
    secret_name: str


class CreateIngressRequest(BaseModel):
    cluster_id: str
    namespace: str
    name: str
    rules: list[IngressRuleRequest]
    tls: list[IngressTLSRequest] | None = None
    ingress_class: str | None = None


class HelmInstallRequest(BaseModel):
    cluster_id: str
    release_name: str
    chart: str
    namespace: str
    version: str | None = None
    values_yaml: str | None = None
    create_namespace: bool = False


class HelmUpgradeRequest(BaseModel):
    cluster_id: str
    release_name: str
    chart: str
    namespace: str
    version: str | None = None
    values_yaml: str | None = None


class HelmRollbackRequest(BaseModel):
    cluster_id: str
    release_name: str
    namespace: str
    revision: int = Field(ge=1)


def register_extended_routes(router, *, get_service, write_audit, serialize_audit):
    """Register extended routes on the AKS router."""

    @router.get("/namespaces", summary="List namespaces for cluster")
    async def list_namespaces(
        cluster_id: str = Query(...),
        user: UserContext = Depends(get_current_user),
        service=Depends(get_service),
    ) -> dict:
        namespaces = await service.list_namespaces_for_cluster(cluster_id)
        return {"namespaces": namespaces, "count": len(namespaces)}

    @router.get("/history", summary="AKS audit history")
    async def get_audit_history(
        cluster_id: str | None = Query(default=None),
        namespace: str | None = Query(default=None),
        days: int = Query(default=90, ge=1, le=365),
        limit: int = Query(default=200, ge=1, le=1000),
        user: UserContext = Depends(get_current_user),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        if db is None:
            return {"history": [], "count": 0}
        since = datetime.now(UTC).replace(tzinfo=None) - timedelta(days=days)
        stmt = (
            select(AuditLog)
            .where(AuditLog.timestamp >= since)
            .where(AuditLog.details["page"].astext == "AKSOperationsPage")
            .order_by(desc(AuditLog.timestamp))
            .limit(limit)
        )
        if cluster_id:
            stmt = stmt.where(AuditLog.details["cluster_id"].astext == cluster_id)
        if namespace:
            stmt = stmt.where(AuditLog.details["namespace"].astext == namespace)
        result = await db.execute(stmt)
        history = [serialize_audit(entry) for entry in result.scalars().all()]
        return {"history": history, "count": len(history)}

    @router.websocket("/watch")
    async def aks_live_watch(websocket: WebSocket, access_token: str | None = Query(default=None)) -> None:
        try:
            user = await get_current_user_from_token(access_token)
        except HTTPException as exc:
            raise WebSocketException(code=1008, reason=exc.detail) from exc
        if not user.has_role(UserRole.READ) and not user.is_admin:
            raise WebSocketException(code=1008, reason="Insufficient permissions")
        from app.services.aks_live_sync_hub import aks_live_sync_hub

        await aks_live_sync_hub.handle_client(websocket, user)

    # ── Secrets ────────────────────────────────────────────────────────

    @router.get("/secrets/cached")
    async def list_cached_secrets(
        cluster_id: str = Query(...),
        namespace: str | None = Query(default=None),
        user: UserContext = Depends(get_current_user),
        service=Depends(get_service),
    ) -> dict:
        items = await service.get_secrets_from_db(cluster_id, namespace)
        if items:
            return {"source": "db", "secrets": items, "count": len(items)}
        live = await service.list_secrets(cluster_id, namespace or "default")
        return {"source": "live", "secrets": live, "count": len(live)}

    @router.post("/secrets/sync")
    async def sync_secrets(
        cluster_id: str = Query(...),
        namespace: str | None = Query(default=None),
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
    ) -> dict:
        return await service.sync_secrets_to_db(cluster_id, namespace)

    @router.get("/secrets")
    async def list_secrets(
        cluster_id: str = Query(...),
        namespace: str = Query(...),
        user: UserContext = Depends(get_current_user),
        service=Depends(get_service),
    ) -> dict:
        secrets = await service.list_secrets(cluster_id, namespace)
        return {"secrets": secrets, "count": len(secrets)}

    @router.get("/secrets/detail")
    async def get_secret_detail(
        cluster_id: str = Query(...),
        namespace: str = Query(...),
        name: str = Query(...),
        reveal: bool = Query(default=False),
        http_request: Request = None,
        user: UserContext = Depends(get_current_user),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        if reveal and not user.has_role(UserRole.WRITE) and not user.is_admin:
            raise HTTPException(status_code=403, detail="WRITE role required to reveal secret values")
        detail = await service.get_secret_detail(cluster_id, namespace, name, reveal=reveal)
        if reveal:
            await write_audit(
                db,
                request=http_request,
                user=user,
                action="reveal_secret",
                resource_type="secret",
                resource_name=name,
                cluster_id=cluster_id,
                namespace=namespace,
                status="success",
                details={},
            )
        return detail

    @router.post("/secrets")
    async def create_secret(
        request: CreateSecretRequest,
        http_request: Request,
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        try:
            result = await service.create_secret(
                request.cluster_id, request.namespace, request.name, request.data, request.secret_type
            )
            await write_audit(
                db,
                request=http_request,
                user=user,
                action="create_secret",
                resource_type="secret",
                resource_name=request.name,
                cluster_id=request.cluster_id,
                namespace=request.namespace,
                status="success",
                details={"key_count": len(request.data)},
            )
            return result
        except Exception as e:
            await write_audit(
                db,
                request=http_request,
                user=user,
                action="create_secret",
                resource_type="secret",
                resource_name=request.name,
                cluster_id=request.cluster_id,
                namespace=request.namespace,
                status="failed",
                details={"error": str(e)},
            )
            raise HTTPException(status_code=502, detail=str(e)) from e

    @router.put("/secrets")
    async def update_secret(
        request: UpdateSecretRequest,
        http_request: Request,
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        try:
            result = await service.update_secret(request.cluster_id, request.namespace, request.name, request.data)
            await write_audit(
                db,
                request=http_request,
                user=user,
                action="update_secret",
                resource_type="secret",
                resource_name=request.name,
                cluster_id=request.cluster_id,
                namespace=request.namespace,
                status="success",
                details={},
            )
            return result
        except Exception as e:
            raise HTTPException(status_code=502, detail=str(e)) from e

    @router.delete("/secrets")
    async def delete_secret(
        cluster_id: str = Query(...),
        namespace: str = Query(...),
        name: str = Query(...),
        http_request: Request = None,
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        result = await service.delete_secret(cluster_id, namespace, name)
        await write_audit(
            db,
            request=http_request,
            user=user,
            action="delete_secret",
            resource_type="secret",
            resource_name=name,
            cluster_id=cluster_id,
            namespace=namespace,
            status="success",
            details={},
        )
        return result

    # ── Services ───────────────────────────────────────────────────────

    @router.get("/services/cached")
    async def list_cached_services(
        cluster_id: str = Query(...),
        namespace: str | None = Query(default=None),
        user: UserContext = Depends(get_current_user),
        service=Depends(get_service),
    ) -> dict:
        items = await service.get_services_from_db(cluster_id, namespace)
        if items:
            return {"source": "db", "services": items, "count": len(items)}
        if not namespace:
            return {"source": "db", "services": [], "count": 0}
        live = await service.list_services(cluster_id, namespace)
        return {"source": "live", "services": live, "count": len(live)}

    @router.post("/services/sync")
    async def sync_services(
        cluster_id: str = Query(...),
        namespace: str | None = Query(default=None),
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
    ) -> dict:
        return await service.sync_services_to_db(cluster_id, namespace)

    @router.get("/services")
    async def list_services(
        cluster_id: str = Query(...),
        namespace: str = Query(...),
        user: UserContext = Depends(get_current_user),
        service=Depends(get_service),
    ) -> dict:
        services = await service.list_services(cluster_id, namespace)
        return {"services": services, "count": len(services)}

    @router.get("/services/detail")
    async def get_service_detail(
        cluster_id: str = Query(...),
        namespace: str = Query(...),
        name: str = Query(...),
        user: UserContext = Depends(get_current_user),
        service=Depends(get_service),
    ) -> dict:
        return await service.get_service_detail(cluster_id, namespace, name)

    @router.post("/services")
    async def create_service(
        request: CreateServiceRequest,
        http_request: Request,
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        result = await service.create_service(
            request.cluster_id,
            request.namespace,
            request.name,
            request.port,
            request.target_port,
            request.selector,
            request.service_type,
        )
        await write_audit(
            db,
            request=http_request,
            user=user,
            action="create_service",
            resource_type="service",
            resource_name=request.name,
            cluster_id=request.cluster_id,
            namespace=request.namespace,
            status="success",
            details={"port": request.port},
        )
        return result

    @router.delete("/services")
    async def delete_service(
        cluster_id: str = Query(...),
        namespace: str = Query(...),
        name: str = Query(...),
        http_request: Request = None,
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        result = await service.delete_service(cluster_id, namespace, name)
        await write_audit(
            db,
            request=http_request,
            user=user,
            action="delete_service",
            resource_type="service",
            resource_name=name,
            cluster_id=cluster_id,
            namespace=namespace,
            status="success",
            details={},
        )
        return result

    # ── ConfigMaps (extended) ──────────────────────────────────────────

    @router.get("/configmaps/cached")
    async def list_cached_configmaps(
        cluster_id: str = Query(...),
        namespace: str | None = Query(default=None),
        user: UserContext = Depends(get_current_user),
        service=Depends(get_service),
    ) -> dict:
        items = await service.get_configmaps_from_db(cluster_id, namespace)
        if items:
            return {"source": "db", "configmaps": items, "count": len(items)}
        if not namespace:
            return {"source": "db", "configmaps": [], "count": 0}
        live = await service.list_configmaps(cluster_id, namespace)
        return {"source": "live", "configmaps": live, "count": len(live)}

    @router.post("/configmaps/sync")
    async def sync_configmaps(
        cluster_id: str = Query(...),
        namespace: str | None = Query(default=None),
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
    ) -> dict:
        return await service.sync_configmaps_to_db(cluster_id, namespace)

    @router.post("/configmaps")
    async def create_configmap(
        request: CreateConfigMapRequest,
        http_request: Request,
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        result = await service.create_configmap(request.cluster_id, request.namespace, request.name, request.data)
        await write_audit(
            db,
            request=http_request,
            user=user,
            action="create_configmap",
            resource_type="configmap",
            resource_name=request.name,
            cluster_id=request.cluster_id,
            namespace=request.namespace,
            status="success",
            details={"key_count": len(request.data)},
        )
        return result

    @router.put("/configmaps")
    async def update_configmap(
        request: CreateConfigMapRequest,
        http_request: Request,
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        result = await service.update_configmap(request.cluster_id, request.namespace, request.name, request.data)
        await write_audit(
            db,
            request=http_request,
            user=user,
            action="update_configmap",
            resource_type="configmap",
            resource_name=request.name,
            cluster_id=request.cluster_id,
            namespace=request.namespace,
            status="success",
            details={},
        )
        return result

    @router.delete("/configmaps")
    async def delete_configmap(
        cluster_id: str = Query(...),
        namespace: str = Query(...),
        name: str = Query(...),
        http_request: Request = None,
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        result = await service.delete_configmap(cluster_id, namespace, name)
        await write_audit(
            db,
            request=http_request,
            user=user,
            action="delete_configmap",
            resource_type="configmap",
            resource_name=name,
            cluster_id=cluster_id,
            namespace=namespace,
            status="success",
            details={},
        )
        return result

    # ── Ingress ────────────────────────────────────────────────────────

    @router.get("/ingress/cached")
    async def list_cached_ingress(
        cluster_id: str = Query(...),
        namespace: str | None = Query(default=None),
        user: UserContext = Depends(get_current_user),
        service=Depends(get_service),
    ) -> dict:
        items = await service.get_ingress_from_db(cluster_id, namespace)
        if items:
            return {"source": "db", "ingress": items, "count": len(items)}
        if not namespace:
            return {"source": "db", "ingress": [], "count": 0}
        live = await service._fetch_ingress_live(cluster_id, namespace)
        return {"source": "live", "ingress": live, "count": len(live)}

    @router.post("/ingress/sync")
    async def sync_ingress(
        cluster_id: str = Query(...),
        namespace: str | None = Query(default=None),
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
    ) -> dict:
        return await service.sync_ingress_to_db(cluster_id, namespace)

    @router.get("/ingress")
    async def list_ingress(
        cluster_id: str = Query(...),
        namespace: str = Query(...),
        user: UserContext = Depends(get_current_user),
        service=Depends(get_service),
    ) -> dict:
        items = await service._fetch_ingress_live(cluster_id, namespace)
        return {"ingress": items, "count": len(items)}

    @router.get("/ingress/detail")
    async def get_ingress_detail(
        cluster_id: str = Query(...),
        namespace: str = Query(...),
        name: str = Query(...),
        user: UserContext = Depends(get_current_user),
        service=Depends(get_service),
    ) -> dict:
        return await service.get_ingress_detail(cluster_id, namespace, name)

    @router.post("/ingress")
    async def create_ingress(
        request: CreateIngressRequest,
        http_request: Request,
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        rules = [{"host": r.host, "paths": [p.model_dump() for p in r.paths]} for r in request.rules]
        tls = [t.model_dump() for t in request.tls] if request.tls else None
        result = await service.create_ingress(
            request.cluster_id, request.namespace, request.name, rules, tls, request.ingress_class
        )
        await write_audit(
            db,
            request=http_request,
            user=user,
            action="create_ingress",
            resource_type="ingress",
            resource_name=request.name,
            cluster_id=request.cluster_id,
            namespace=request.namespace,
            status="success",
            details={"rule_count": len(request.rules)},
        )
        return result

    @router.delete("/ingress")
    async def delete_ingress(
        cluster_id: str = Query(...),
        namespace: str = Query(...),
        name: str = Query(...),
        http_request: Request = None,
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        result = await service.delete_ingress(cluster_id, namespace, name)
        await write_audit(
            db,
            request=http_request,
            user=user,
            action="delete_ingress",
            resource_type="ingress",
            resource_name=name,
            cluster_id=cluster_id,
            namespace=namespace,
            status="success",
            details={},
        )
        return result

    @router.post("/pods/sync")
    async def sync_pods(
        cluster_id: str = Query(...),
        namespace: str | None = Query(default=None),
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
    ) -> dict:
        return await service.sync_pods_to_db(cluster_id, namespace)

    # ── Helm ───────────────────────────────────────────────────────────

    @router.get("/helm/releases")
    async def list_helm_releases(
        cluster_id: str = Query(...),
        namespace: str | None = Query(default=None),
        user: UserContext = Depends(get_current_user),
        service=Depends(get_service),
    ) -> dict:
        from app.services.aks_helm_service import AKSHelmService

        helm = AKSHelmService(service)
        releases = await helm.list_releases(cluster_id, namespace)
        return {"releases": releases, "count": len(releases)}

    @router.post("/helm/install")
    async def helm_install(
        request: HelmInstallRequest,
        http_request: Request,
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        from app.services.aks_helm_service import AKSHelmService

        helm = AKSHelmService(service)
        result = await helm.install_release(
            request.cluster_id,
            request.release_name,
            request.chart,
            request.namespace,
            version=request.version,
            values_yaml=request.values_yaml,
            create_namespace=request.create_namespace,
        )
        status = "success" if result.get("success") else "failed"
        await write_audit(
            db,
            request=http_request,
            user=user,
            action="helm_install",
            resource_type="helm_release",
            resource_name=request.release_name,
            cluster_id=request.cluster_id,
            namespace=request.namespace,
            status=status,
            details={"chart": request.chart, "error": result.get("error")},
        )
        if not result.get("success"):
            raise HTTPException(status_code=502, detail=result.get("error", "Helm install failed"))
        return result

    @router.post("/helm/upgrade")
    async def helm_upgrade(
        request: HelmUpgradeRequest,
        http_request: Request,
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        from app.services.aks_helm_service import AKSHelmService

        helm = AKSHelmService(service)
        result = await helm.upgrade_release(
            request.cluster_id,
            request.release_name,
            request.chart,
            request.namespace,
            version=request.version,
            values_yaml=request.values_yaml,
        )
        status = "success" if result.get("success") else "failed"
        await write_audit(
            db,
            request=http_request,
            user=user,
            action="helm_upgrade",
            resource_type="helm_release",
            resource_name=request.release_name,
            cluster_id=request.cluster_id,
            namespace=request.namespace,
            status=status,
            details={"chart": request.chart, "error": result.get("error")},
        )
        if not result.get("success"):
            raise HTTPException(status_code=502, detail=result.get("error", "Helm upgrade failed"))
        return result

    @router.post("/helm/rollback")
    async def helm_rollback(
        request: HelmRollbackRequest,
        http_request: Request,
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        from app.services.aks_helm_service import AKSHelmService

        helm = AKSHelmService(service)
        result = await helm.rollback_release(
            request.cluster_id, request.release_name, request.namespace, request.revision
        )
        status = "success" if result.get("success") else "failed"
        await write_audit(
            db,
            request=http_request,
            user=user,
            action="helm_rollback",
            resource_type="helm_release",
            resource_name=request.release_name,
            cluster_id=request.cluster_id,
            namespace=request.namespace,
            status=status,
            details={"revision": request.revision, "error": result.get("error")},
        )
        if not result.get("success"):
            raise HTTPException(status_code=502, detail=result.get("error", "Helm rollback failed"))
        return result

    @router.delete("/helm/uninstall")
    async def helm_uninstall(
        cluster_id: str = Query(...),
        release_name: str = Query(...),
        namespace: str = Query(...),
        http_request: Request = None,
        user: UserContext = Depends(require_role(UserRole.WRITE)),
        service=Depends(get_service),
        db: AsyncSession = Depends(get_db),
    ) -> dict:
        from app.services.aks_helm_service import AKSHelmService

        helm = AKSHelmService(service)
        result = await helm.uninstall_release(cluster_id, release_name, namespace)
        status = "success" if result.get("success") else "failed"
        await write_audit(
            db,
            request=http_request,
            user=user,
            action="helm_uninstall",
            resource_type="helm_release",
            resource_name=release_name,
            cluster_id=cluster_id,
            namespace=namespace,
            status=status,
            details={"error": result.get("error")},
        )
        if not result.get("success"):
            raise HTTPException(status_code=502, detail=result.get("error", "Helm uninstall failed"))
        return result
