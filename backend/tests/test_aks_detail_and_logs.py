"""
Tests for Deployment / Pod detail views and the complete-log archive download.
"""

import io
import json
import zipfile
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from kubernetes import client as k8s
from kubernetes.client.rest import ApiException

from app.api.v1.endpoints import aks_operations
from app.api.v1.endpoints.aks_operations import _get_service
from app.auth import get_current_user
from app.core.database import get_db
from app.models.database import Permission, Resource
from app.schemas.auth import UserContext, UserRole
from app.services import aks_log_archive as archive
from app.services.aks_detail_operations import image_checksum, serialize_deployment, serialize_pod_detail
from app.services.aks_operations_service import AKSOperationsService
from app.services.aks_workload_operations import pod_status_reason

CLUSTER_ID = "/subscriptions/s1/resourceGroups/rg1/providers/Microsoft.ContainerService/managedClusters/aks-prod-01"
CREATED = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
NS = "apps"


# ── Builders (real client models, so attribute names are checked) ────


def _owner(kind, name, uid):
    return k8s.V1OwnerReference(api_version="apps/v1", kind=kind, name=name, uid=uid, controller=True)


def _meta(name, *, uid=None, labels=None, annotations=None, owner=None):
    return k8s.V1ObjectMeta(
        name=name,
        namespace=NS,
        uid=uid or f"uid-{name}",
        labels=labels or {},
        annotations=annotations,
        creation_timestamp=CREATED,
        generation=1,
        owner_references=[owner] if owner else None,
    )


def _running():
    return k8s.V1ContainerState(running=k8s.V1ContainerStateRunning(started_at=CREATED))


def _status(name, *, ready=True, restarts=0, state=None, last_state=None):
    return k8s.V1ContainerStatus(
        name=name,
        image=f"repo/{name}:1",
        image_id=f"repo/{name}@sha256:abc",
        ready=ready,
        restart_count=restarts,
        state=state or _running(),
        last_state=last_state,
    )


def make_pod(
    name,
    *,
    owner=None,
    labels=None,
    containers=("app",),
    statuses=None,
    init_containers=(),
    init_statuses=None,
    phase="Running",
    annotations=None,
):
    return k8s.V1Pod(
        api_version="v1",
        kind="Pod",
        metadata=_meta(name, labels=labels, owner=owner, annotations=annotations),
        spec=k8s.V1PodSpec(
            containers=[k8s.V1Container(name=c, image=f"repo/{c}:1") for c in containers],
            init_containers=[k8s.V1Container(name=c, image=f"repo/{c}:1") for c in init_containers] or None,
            node_name="aks-node-1",
            service_account_name="default",
        ),
        status=k8s.V1PodStatus(
            phase=phase,
            pod_ip="10.0.0.5",
            start_time=CREATED,
            container_statuses=statuses if statuses is not None else [_status(c) for c in containers],
            init_container_statuses=init_statuses,
        ),
    )


def _template(hash_=None):
    labels = {"app": "administration"}
    if hash_:
        labels["pod-template-hash"] = hash_
    return k8s.V1PodTemplateSpec(
        metadata=k8s.V1ObjectMeta(labels=labels),
        spec=k8s.V1PodSpec(containers=[k8s.V1Container(name="app", image="repo/administration:1.0.158")]),
    )


def make_deployment(name="administration", *, uid="dep-1", replicas=2, ready=2, revision="3", conditions=None):
    return k8s.V1Deployment(
        api_version="apps/v1",
        kind="Deployment",
        metadata=_meta(
            name,
            uid=uid,
            annotations={
                "deployment.kubernetes.io/revision": revision,
                "kubectl.kubernetes.io/last-applied-configuration": "{...}",
            },
        ),
        spec=k8s.V1DeploymentSpec(
            replicas=replicas,
            selector=k8s.V1LabelSelector(match_labels={"app": "administration"}),
            template=_template(),
            strategy=k8s.V1DeploymentStrategy(
                type="RollingUpdate",
                rolling_update=k8s.V1RollingUpdateDeployment(max_surge="25%", max_unavailable="25%"),
            ),
            revision_history_limit=10,
            progress_deadline_seconds=600,
        ),
        status=k8s.V1DeploymentStatus(
            replicas=replicas,
            ready_replicas=ready,
            updated_replicas=ready,
            available_replicas=ready,
            observed_generation=1,
            conditions=conditions,
        ),
    )


def make_replica_set(name, *, revision, owner_uid, hash_, replicas, owner_name="administration"):
    return k8s.V1ReplicaSet(
        metadata=_meta(
            name,
            uid=f"rs-{hash_}",
            labels={"app": "administration", "pod-template-hash": hash_},
            annotations={"deployment.kubernetes.io/revision": str(revision)},
            owner=_owner("Deployment", owner_name, owner_uid),
        ),
        spec=k8s.V1ReplicaSetSpec(
            replicas=replicas,
            selector=k8s.V1LabelSelector(match_labels={"app": "administration"}),
            template=_template(hash_),
        ),
        status=k8s.V1ReplicaSetStatus(replicas=replicas, ready_replicas=replicas, available_replicas=replicas),
    )


def make_event(kind, name, reason, *, type_="Normal", message="msg"):
    return k8s.CoreV1Event(
        metadata=k8s.V1ObjectMeta(name=f"{name}.{reason}"),
        involved_object=k8s.V1ObjectReference(kind=kind, name=name, namespace=NS),
        reason=reason,
        message=message,
        type=type_,
        count=1,
        last_timestamp=CREATED,
    )


def _api_error(status, message=""):
    exc = ApiException(status=status, reason="Error")
    exc.body = json.dumps({"message": message}).encode()
    return exc


# ── Fake Kubernetes APIs ──────────────────────────────────────────────


class FakeLogResponse:
    def __init__(self, data: bytes, fail_after_first_chunk: bool = False):
        self.data = data
        self.fail = fail_after_first_chunk
        self.released = False

    def stream(self, amt):
        for i in range(0, len(self.data), amt):
            yield self.data[i : i + amt]
            if self.fail:
                raise ConnectionError("connection reset")

    def release_conn(self):
        self.released = True


class FakeApps:
    def __init__(self, deployments=(), replica_sets=()):
        self.deployments = {d.metadata.name: d for d in deployments}
        self.replica_sets = list(replica_sets)

    def read_namespaced_deployment(self, name, namespace):
        if name not in self.deployments:
            raise _api_error(404, f'deployments.apps "{name}" not found')
        return self.deployments[name]

    def list_namespaced_replica_set(self, namespace, label_selector=None):
        return SimpleNamespace(items=self.replica_sets)

    def read_namespaced_replica_set(self, name, namespace):
        rs = next((r for r in self.replica_sets if r.metadata.name == name), None)
        if rs is None:
            raise _api_error(404)
        return rs


class FakeCore:
    def __init__(self, pods=(), events=(), logs=None, claims=()):
        self.pods = list(pods)
        self.events = list(events)
        self.logs = logs or {}
        self.claims = {c.metadata.name: c for c in claims}
        self.log_calls: list[tuple[str, str, bool]] = []

    def read_namespaced_persistent_volume_claim(self, name, namespace):
        if name not in self.claims:
            raise _api_error(404, f'persistentvolumeclaims "{name}" not found')
        return self.claims[name]

    def list_namespaced_pod(self, namespace, label_selector=None):
        return SimpleNamespace(items=[p for p in self.pods if p.metadata.namespace == namespace])

    def read_namespaced_pod(self, name, namespace):
        pod = next((p for p in self.pods if p.metadata.name == name), None)
        if pod is None:
            raise _api_error(404, f'pods "{name}" not found')
        return pod

    def list_namespaced_event(self, namespace, field_selector=""):
        wanted = dict(part.split("=", 1) for part in field_selector.split(","))
        return SimpleNamespace(
            items=[
                e
                for e in self.events
                if e.involved_object.kind == wanted["involvedObject.kind"]
                and e.involved_object.name == wanted.get("involvedObject.name", e.involved_object.name)
            ]
        )

    def read_namespaced_pod_log(self, *, name, namespace, container, previous, timestamps, **_kwargs):
        assert timestamps is True
        self.log_calls.append((name, container, previous))
        value = self.logs.get((name, container, previous), b"")
        if isinstance(value, Exception):
            raise value
        if isinstance(value, FakeLogResponse):
            return value
        return FakeLogResponse(value)


def build_service(apps, core):
    svc = AKSOperationsService.__new__(AKSOperationsService)
    svc.db = None

    async def _clients(_cluster_id):
        return (apps, core, None)

    svc._get_k8s_clients = _clients
    return svc


# The "administration" Deployment and a sibling "administration-4-1-d2a" whose
# ReplicaSet and pods share its labels and name prefix — ownership, not names
# or labels, must decide which pods belong to which Deployment.
RS_OLD = make_replica_set("administration-6d4f", revision=2, owner_uid="dep-1", hash_="6d4f", replicas=0)
RS_CUR = make_replica_set("administration-7b9c", revision=3, owner_uid="dep-1", hash_="7b9c", replicas=2)
RS_SIBLING = make_replica_set(
    "administration-4-1-d2a-55aa",
    revision=1,
    owner_uid="dep-2",
    hash_="55aa",
    replicas=1,
    owner_name="administration-4-1-d2a",
)


def _rs_pod(name, rs, **kwargs):
    hash_ = rs.metadata.labels["pod-template-hash"]
    return make_pod(
        name,
        owner=_owner("ReplicaSet", rs.metadata.name, rs.metadata.uid),
        labels={"app": "administration", "pod-template-hash": hash_},
        **kwargs,
    )


POD_A = _rs_pod(
    "administration-7b9c-a",
    RS_CUR,
    init_containers=("init-db",),
    init_statuses=[
        _status(
            "init-db",
            ready=False,
            state=k8s.V1ContainerState(terminated=k8s.V1ContainerStateTerminated(exit_code=0, reason="Completed")),
        )
    ],
    statuses=[
        _status(
            "app",
            restarts=2,
            last_state=k8s.V1ContainerState(
                terminated=k8s.V1ContainerStateTerminated(exit_code=137, reason="OOMKilled", finished_at=CREATED)
            ),
        )
    ],
)
POD_B = _rs_pod("administration-7b9c-b", RS_CUR)
POD_SIBLING = _rs_pod("administration-4-1-d2a-55aa-x", RS_SIBLING)


def deployment_fakes(**core_kwargs):
    apps = FakeApps(deployments=[make_deployment()], replica_sets=[RS_OLD, RS_CUR, RS_SIBLING])
    core = FakeCore(pods=[POD_B, POD_SIBLING, POD_A], **core_kwargs)
    return apps, core


# ── Pod status (kubectl STATUS column) ────────────────────────────────


def _waiting(reason):
    return k8s.V1ContainerState(waiting=k8s.V1ContainerStateWaiting(reason=reason))


@pytest.mark.parametrize(
    ("pod", "expected"),
    [
        (make_pod("ok"), "Running"),
        (
            make_pod("crash", statuses=[_status("app", ready=False, state=_waiting("CrashLoopBackOff"))]),
            "CrashLoopBackOff",
        ),
        (
            make_pod(
                "oom",
                phase="Failed",
                statuses=[
                    _status(
                        "app",
                        ready=False,
                        state=k8s.V1ContainerState(
                            terminated=k8s.V1ContainerStateTerminated(exit_code=137, reason="OOMKilled")
                        ),
                    )
                ],
            ),
            "OOMKilled",
        ),
        (
            make_pod(
                "init-pull",
                phase="Pending",
                init_containers=("init-db",),
                init_statuses=[_status("init-db", ready=False, state=_waiting("ErrImagePull"))],
                statuses=[_status("app", ready=False, state=_waiting("PodInitializing"))],
            ),
            "Init:ErrImagePull",
        ),
        (
            make_pod(
                "init-running",
                phase="Pending",
                init_containers=("init-db",),
                init_statuses=[_status("init-db", ready=False)],
                statuses=[_status("app", ready=False, state=_waiting("PodInitializing"))],
            ),
            "Init:0/1",
        ),
    ],
)
def test_pod_status_reason(pod, expected):
    assert pod_status_reason(pod) == expected


def test_terminating_pod_status():
    pod = make_pod("leaving")
    pod.metadata.deletion_timestamp = CREATED
    assert pod_status_reason(pod) == "Terminating"


def test_running_sidecar_init_container_does_not_block_status():
    pod = make_pod("with-sidecar", init_containers=("proxy",), init_statuses=[_status("proxy")])
    pod.spec.init_containers[0].restart_policy = "Always"
    pod.status.init_container_statuses[0].started = True
    assert pod_status_reason(pod) == "Running"


# ── Serialization ─────────────────────────────────────────────────────


def test_pod_detail_surfaces_last_termination_probes_and_volumes():
    pod = make_pod("web-1", annotations={"kubectl.kubernetes.io/last-applied-configuration": "{}", "team": "ops"})
    container = pod.spec.containers[0]
    container.ports = [k8s.V1ContainerPort(container_port=8080, name="http")]
    container.liveness_probe = k8s.V1Probe(http_get=k8s.V1HTTPGetAction(path="/healthz", port=8080), period_seconds=5)
    container.readiness_probe = k8s.V1Probe(_exec=k8s.V1ExecAction(command=["cat", "/tmp/ready"]))
    container.volume_mounts = [k8s.V1VolumeMount(name="config", mount_path="/etc/app", read_only=True)]
    pod.spec.volumes = [
        k8s.V1Volume(name="config", config_map=k8s.V1ConfigMapVolumeSource(name="app-config")),
        k8s.V1Volume(name="data", persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(claim_name="data-0")),
        k8s.V1Volume(
            name="kube-api-access",
            projected=k8s.V1ProjectedVolumeSource(
                sources=[
                    k8s.V1VolumeProjection(service_account_token=k8s.V1ServiceAccountTokenProjection(path="token")),
                    k8s.V1VolumeProjection(config_map=k8s.V1ConfigMapProjection(name="kube-root-ca.crt")),
                ]
            ),
        ),
    ]
    pod.status.container_statuses = [
        _status(
            "app",
            restarts=3,
            last_state=k8s.V1ContainerState(
                terminated=k8s.V1ContainerStateTerminated(exit_code=137, reason="OOMKilled", finished_at=CREATED)
            ),
        )
    ]

    detail = serialize_pod_detail(pod)

    app = detail["containers"][0]
    assert app["restart_count"] == 3
    assert app["state"]["state"] == "running"
    assert app["last_state"] == {
        "state": "terminated",
        "reason": "OOMKilled",
        "message": None,
        "exit_code": 137,
        "signal": None,
        "started_at": None,
        "finished_at": CREATED.isoformat(),
    }
    assert app["ports"] == ["8080/TCP (http)"]
    assert app["probes"]["liveness"].startswith("http-get http://:8080/healthz")
    assert "period=5s" in app["probes"]["liveness"]
    assert app["probes"]["readiness"].startswith("exec [cat /tmp/ready]")
    assert app["volume_mounts"] == [{"name": "config", "mount_path": "/etc/app", "read_only": True, "sub_path": None}]
    assert [(v["name"], v["type"], v["source"]) for v in detail["volumes"]] == [
        ("config", "ConfigMap", "app-config"),
        ("data", "PersistentVolumeClaim", "data-0"),
        ("kube-api-access", "Projected", "serviceAccountToken, configMap:kube-root-ca.crt"),
    ]
    assert detail["restarts"] == 3
    assert detail["annotations"] == {"team": "ops"}


@pytest.mark.parametrize(
    ("image_id", "expected"),
    [
        ("artifact.it.att.com:22609/repo/app@sha256:" + "a" * 64, "a" * 64),
        ("docker-pullable://repo/app@sha256:" + "b" * 64, "b" * 64),
        ("sha256:" + "c" * 64, "c" * 64),  # containerd without the repository
        ("", None),
        (None, None),
    ],
)
def test_image_checksum_matches_compliance_parsing(image_id, expected):
    assert image_checksum(image_id) == expected


def test_pod_image_checksum_uses_first_status_like_compliance():
    pod = make_pod("web-1", containers=("app", "istio-proxy"))
    pod.status.container_statuses[0].image_id = "repo/app@sha256:" + "1" * 64
    pod.status.container_statuses[1].image_id = "repo/proxy@sha256:" + "2" * 64

    detail = serialize_pod_detail(pod)

    assert detail["image_checksum"] == "1" * 64
    assert [c["image_checksum"] for c in detail["containers"]] == ["1" * 64, "2" * 64]


def test_pod_without_started_containers_has_no_checksum():
    pod = make_pod("pending", statuses=[])
    detail = serialize_pod_detail(pod)
    assert detail["image_checksum"] is None
    assert detail["containers"][0]["image_checksum"] is None


def test_volume_spec_is_manifest_shaped():
    pod = make_pod("web-1")
    pod.spec.volumes = [
        k8s.V1Volume(
            name="config",
            config_map=k8s.V1ConfigMapVolumeSource(
                name="app-config", default_mode=420, items=[k8s.V1KeyToPath(key="log4j2.xml", path="log4j2.xml")]
            ),
        ),
        k8s.V1Volume(
            name="attcc-volume",
            csi=k8s.V1CSIVolumeSource(
                driver="file.csi.azure.com",
                volume_attributes={"shareName": "logs", "secretName": "azure-files"},
            ),
        ),
    ]

    config, csi = serialize_pod_detail(pod)["volumes"]

    assert config["spec"] == {
        "defaultMode": 420,
        "items": [{"key": "log4j2.xml", "path": "log4j2.xml"}],
        "name": "app-config",
    }
    assert csi["source"] == "file.csi.azure.com"
    assert csi["spec"] == {
        "driver": "file.csi.azure.com",
        "volumeAttributes": {"shareName": "logs", "secretName": "azure-files"},
    }


async def test_pod_detail_attaches_bound_claims():
    pod = make_pod("db-0")
    pod.spec.volumes = [
        k8s.V1Volume(
            name="data", persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(claim_name="data-db-0")
        ),
        k8s.V1Volume(
            name="gone", persistent_volume_claim=k8s.V1PersistentVolumeClaimVolumeSource(claim_name="missing")
        ),
    ]
    claim = k8s.V1PersistentVolumeClaim(
        metadata=k8s.V1ObjectMeta(name="data-db-0", creation_timestamp=CREATED),
        spec=k8s.V1PersistentVolumeClaimSpec(
            access_modes=["ReadWriteOnce"],
            storage_class_name="managed-csi",
            volume_name="pvc-123",
            resources=k8s.V1VolumeResourceRequirements(requests={"storage": "10Gi"}),
        ),
        status=k8s.V1PersistentVolumeClaimStatus(phase="Bound", capacity={"storage": "10Gi"}),
    )
    core = FakeCore(pods=[pod], claims=[claim])

    detail = await build_service(FakeApps(), core).get_pod_detail(CLUSTER_ID, NS, "db-0")

    data, gone = detail["volumes"]
    assert data["claim"] == {
        "name": "data-db-0",
        "phase": "Bound",
        "capacity": "10Gi",
        "requested": "10Gi",
        "access_modes": ["ReadWriteOnce"],
        "storage_class": "managed-csi",
        "volume_name": "pvc-123",
        "volume_mode": None,
        "created_at": CREATED.isoformat(),
    }
    assert gone["claim"] is None


def test_serialize_deployment_fields():
    item = serialize_deployment(make_deployment())

    assert item["status"] == "Healthy"
    assert (item["desired"], item["ready"], item["revision"]) == (2, 2, "3")
    assert (item["update_strategy"], item["max_surge"], item["max_unavailable"]) == ("RollingUpdate", "25%", "25%")
    assert "kubectl.kubernetes.io/last-applied-configuration" not in item["annotations"]


def test_stalled_rollout_is_degraded():
    stalled = k8s.V1DeploymentCondition(type="Progressing", status="False", reason="ProgressDeadlineExceeded")
    assert serialize_deployment(make_deployment(conditions=[stalled]))["status"] == "Degraded"


def test_scaled_down_deployment_is_idle():
    assert serialize_deployment(make_deployment(replicas=0, ready=0))["status"] == "Idle"


# ── Deployment / Pod detail service ───────────────────────────────────


async def test_deployment_detail_uses_ownership_not_name_prefix():
    apps, core = deployment_fakes(
        events=[
            make_event("Deployment", "administration", "ScalingReplicaSet"),
            make_event("ReplicaSet", "administration-7b9c", "FailedCreate", type_="Warning", message="exceeded quota"),
            make_event("ReplicaSet", "administration-4-1-d2a-55aa", "SuccessfulCreate"),
        ]
    )

    detail = await build_service(apps, core).get_deployment_detail(CLUSTER_ID, NS, "administration")

    assert [p["pod_name"] for p in detail["pods"]] == ["administration-7b9c-a", "administration-7b9c-b"]
    # Pods report the ReplicaSet revision number rather than the template hash.
    assert {p["revision"] for p in detail["pods"]} == {"3"}
    assert [(r["revision"], r["is_current"]) for r in detail["revisions"]] == [(3, True), (2, False)]
    assert {e["object"] for e in detail["events"]} == {"Deployment/administration", "ReplicaSet/administration-7b9c"}
    assert detail["hpa"] is None
    assert "name: administration" in detail["yaml"]
    assert "managedFields" not in detail["yaml"]


async def test_pod_detail_resolves_deployment_behind_replicaset():
    apps, core = deployment_fakes(events=[make_event("Pod", "administration-7b9c-a", "BackOff", type_="Warning")])

    detail = await build_service(apps, core).get_pod_detail(CLUSTER_ID, NS, "administration-7b9c-a")

    assert detail["owner"] == {"kind": "ReplicaSet", "name": "administration-7b9c"}
    assert detail["workload"] == {"kind": "Deployment", "name": "administration"}
    assert [c["name"] for c in detail["init_containers"]] == ["init-db"]
    assert detail["containers"][0]["last_state"]["reason"] == "OOMKilled"
    assert [e["reason"] for e in detail["events"]] == ["BackOff"]


# ── Log archive: planning ─────────────────────────────────────────────


async def test_plan_deployment_archive_lists_every_stream():
    apps, core = deployment_fakes()

    plan = await build_service(apps, core).plan_log_archive(
        CLUSTER_ID, "deployment", namespace=NS, name="administration"
    )

    assert plan.pod_count == 2
    assert plan.target == "Deployment apps/administration"
    assert plan.filename.startswith("aks-prod-01_deployment_administration_")
    assert [s.arcname for s in plan.streams] == [
        "apps/administration-7b9c-a/init/init-db.log",
        "apps/administration-7b9c-a/app.log",
        "apps/administration-7b9c-a/app.previous.log",  # restarted twice
        "apps/administration-7b9c-b/app.log",
    ]


async def test_plan_without_previous_logs():
    apps, core = deployment_fakes()

    plan = await build_service(apps, core).plan_log_archive(
        CLUSTER_ID, "deployment", namespace=NS, name="administration", include_previous=False
    )

    assert not any(s.previous for s in plan.streams)


async def test_plan_unknown_deployment_raises_404():
    apps, core = deployment_fakes()

    with pytest.raises(ApiException) as exc:
        await build_service(apps, core).plan_log_archive(CLUSTER_ID, "deployment", namespace=NS, name="missing")

    assert exc.value.status == 404


async def test_plan_rejects_workload_without_pods():
    apps = FakeApps(deployments=[make_deployment(replicas=0, ready=0)], replica_sets=[RS_OLD])

    with pytest.raises(ValueError, match="has no pods"):
        await build_service(apps, FakeCore()).plan_log_archive(
            CLUSTER_ID, "deployment", namespace=NS, name="administration"
        )


async def test_plan_rejects_oversized_archive(monkeypatch):
    monkeypatch.setattr(archive, "MAX_ARCHIVE_PODS", 1)
    apps, core = deployment_fakes()

    with pytest.raises(ValueError, match="limited to 1"):
        await build_service(apps, core).plan_log_archive(CLUSTER_ID, "deployment", namespace=NS, name="administration")


async def test_plan_selected_pods_reports_missing():
    apps, core = deployment_fakes()

    plan = await build_service(apps, core).plan_log_archive(
        CLUSTER_ID, "pods", pods=[(NS, "administration-7b9c-b"), (NS, "gone-pod")]
    )

    assert plan.pod_count == 1
    assert plan.missing_pods == ["apps/gone-pod"]


async def test_plan_single_missing_pod_raises_lookup_error():
    apps, core = deployment_fakes()

    with pytest.raises(LookupError):
        await build_service(apps, core).plan_log_archive(CLUSTER_ID, "pods", pods=[(NS, "gone-pod")])


# ── Log archive: streaming ────────────────────────────────────────────


async def _collect(svc, plan):
    return [chunk async for chunk in svc.stream_log_archive(CLUSTER_ID, plan)]


async def test_archive_contains_complete_logs_and_summary():
    big = b"".join(f"2026-10-03T00:00:00Z line {i}\n".encode() for i in range(40_000))  # > several chunks
    apps, core = deployment_fakes(
        logs={
            ("administration-7b9c-a", "init-db", False): b"migrations applied\n",
            ("administration-7b9c-a", "app", False): big,
            ("administration-7b9c-a", "app", True): b"java.lang.OutOfMemoryError\n",
            ("administration-7b9c-b", "app", False): _api_error(
                400, 'container "app" in pod "administration-7b9c-b" is waiting to start: ContainerCreating'
            ),
        }
    )
    svc = build_service(apps, core)
    plan = await svc.plan_log_archive(CLUSTER_ID, "deployment", namespace=NS, name="administration")

    chunks = await _collect(svc, plan)

    assert len(chunks) > 2  # streamed, not built in one piece
    zf = zipfile.ZipFile(io.BytesIO(b"".join(chunks)))
    assert zf.testzip() is None
    root = plan.root
    assert zf.read(f"{root}/apps/administration-7b9c-a/app.log") == big
    assert zf.read(f"{root}/apps/administration-7b9c-a/app.previous.log") == b"java.lang.OutOfMemoryError\n"
    assert zf.read(f"{root}/apps/administration-7b9c-a/init/init-db.log") == b"migrations applied\n"
    assert f"{root}/apps/administration-7b9c-b/app.log" not in zf.namelist()
    assert ("administration-7b9c-a", "app", True) in core.log_calls
    # Entries are written without Zip64 headers unless a log actually needs them.
    assert all(not info.extra for info in zf.infolist())

    summary = zf.read(f"{root}/SUMMARY.txt").decode()
    assert "Deployment apps/administration" in summary
    assert "3 complete, 0 partial, 1 failed" in summary
    assert "is waiting to start: ContainerCreating" in summary


async def test_interrupted_stream_keeps_partial_log():
    apps, core = deployment_fakes(
        logs={
            ("administration-7b9c-b", "app", False): FakeLogResponse(
                b"x" * (archive.CHUNK_BYTES * 2), fail_after_first_chunk=True
            )
        }
    )
    svc = build_service(apps, core)
    plan = await svc.plan_log_archive(CLUSTER_ID, "pods", pods=[(NS, "administration-7b9c-b")])

    zf = zipfile.ZipFile(io.BytesIO(b"".join(await _collect(svc, plan))))

    assert len(zf.read(f"{plan.root}/apps/administration-7b9c-b/app.log")) == archive.CHUNK_BYTES
    summary = zf.read(f"{plan.root}/SUMMARY.txt").decode()
    assert "partial" in summary
    assert "stream interrupted" in summary


# ── API ───────────────────────────────────────────────────────────────


def make_user(*roles: UserRole, user_id: str = "u-test") -> UserContext:
    return UserContext(
        user_id=user_id,
        object_id="00000000-0000-0000-0000-000000000000",
        display_name="Test User",
        email=f"{user_id}@example.com",
        roles=list(roles),
        raw_roles=[r.value for r in roles],
        tenant_id="tenant-test",
        allowed_subscriptions=[],
    )


async def _seed(db_session, capability: str, *, granted_to: str, permission_type: str = "view") -> None:
    res = Resource(resource_type="operation", resource_name=capability, description=capability, is_system=True)
    db_session.add(res)
    await db_session.commit()
    await db_session.refresh(res)
    db_session.add(
        Permission(
            subject_type="role",
            subject_id=granted_to,
            resource_id=res.id,
            permission_type=permission_type,
            environment_scope="all",
        )
    )
    await db_session.commit()


@asynccontextmanager
async def client(app, db_session, user: UserContext, service):
    async def _get_db_override():
        yield db_session

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_current_user] = lambda: user
    app.dependency_overrides[_get_service] = lambda: service
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
            yield ac
    finally:
        app.dependency_overrides.clear()


async def test_download_archive_endpoint_streams_zip_and_audits(app, db_session):
    await _seed(db_session, "aks_pod_view", granted_to="read")
    aks_operations._in_memory_audit_log.clear()
    apps, core = deployment_fakes(logs={("administration-7b9c-b", "app", False): b"hello\n"})
    body = {"cluster_id": CLUSTER_ID, "kind": "deployment", "namespace": NS, "name": "administration"}

    async with client(app, db_session, make_user(UserRole.READ, user_id="u-reader"), build_service(apps, core)) as ac:
        resp = await ac.post("/api/v1/aks/logs/archive", json=body)

    entries = [e for e in aks_operations._in_memory_audit_log if e["action"] == "download_logs"]
    aks_operations._in_memory_audit_log.clear()

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    disposition = resp.headers["content-disposition"]
    assert disposition.startswith('attachment; filename="aks-prod-01_deployment_administration_')
    assert resp.headers["x-log-archive-pods"] == "2"
    names = zipfile.ZipFile(io.BytesIO(resp.content)).namelist()
    assert any(n.endswith("apps/administration-7b9c-b/app.log") for n in names)
    assert len(entries) == 1
    assert entries[0]["user_id"] == "u-reader"
    assert entries[0]["status"] == "success"


async def test_download_archive_requires_pod_view_capability(app, db_session):
    await _seed(db_session, "aks_pod_view", granted_to="write")
    apps, core = deployment_fakes()
    body = {"cluster_id": CLUSTER_ID, "kind": "pods", "pods": [{"namespace": NS, "name": "administration-7b9c-b"}]}

    async with client(app, db_session, make_user(UserRole.READ), build_service(apps, core)) as ac:
        resp = await ac.post("/api/v1/aks/logs/archive", json=body)

    assert resp.status_code == 403


@pytest.mark.parametrize(
    "body",
    [
        {"kind": "pods"},
        {"kind": "deployment", "namespace": NS},
        {"kind": "deployment", "namespace": NS, "name": "Bad_Name"},
        {"kind": "replicaset", "namespace": NS, "name": "x"},
    ],
)
async def test_download_archive_validates_target(app, db_session, body):
    async with client(app, db_session, make_user(UserRole.ADMIN), build_service(*deployment_fakes())) as ac:
        resp = await ac.post("/api/v1/aks/logs/archive", json={"cluster_id": CLUSTER_ID, **body})

    assert resp.status_code == 422


async def test_download_archive_unknown_deployment_is_404(app, db_session):
    body = {"cluster_id": CLUSTER_ID, "kind": "deployment", "namespace": NS, "name": "missing"}

    async with client(app, db_session, make_user(UserRole.ADMIN), build_service(*deployment_fakes())) as ac:
        resp = await ac.post("/api/v1/aks/logs/archive", json=body)

    assert resp.status_code == 404
    assert resp.json()["detail"] == "Deployment 'missing' was not found in namespace 'apps'."


async def test_download_archive_empty_workload_is_400(app, db_session):
    apps = FakeApps(deployments=[make_deployment(replicas=0, ready=0)], replica_sets=[RS_OLD])
    body = {"cluster_id": CLUSTER_ID, "kind": "deployment", "namespace": NS, "name": "administration"}

    async with client(app, db_session, make_user(UserRole.ADMIN), build_service(apps, FakeCore())) as ac:
        resp = await ac.post("/api/v1/aks/logs/archive", json=body)

    assert resp.status_code == 400
    assert "has no pods" in resp.json()["detail"]


async def test_pod_detail_endpoint(app, db_session):
    params = {"cluster_id": CLUSTER_ID, "namespace": NS, "name": "administration-7b9c-a"}

    async with client(app, db_session, make_user(UserRole.ADMIN), build_service(*deployment_fakes())) as ac:
        ok = await ac.get("/api/v1/aks/pods/detail", params=params)
        missing = await ac.get("/api/v1/aks/pods/detail", params={**params, "name": "gone-pod"})

    assert ok.status_code == 200
    assert ok.json()["workload"]["kind"] == "Deployment"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Pod 'gone-pod' was not found in namespace 'apps'."


async def test_deployment_detail_endpoint_maps_404(app, db_session):
    params = {"cluster_id": CLUSTER_ID, "namespace": NS, "name": "missing"}

    async with client(app, db_session, make_user(UserRole.ADMIN), build_service(*deployment_fakes())) as ac:
        resp = await ac.get("/api/v1/aks/deployments/details", params=params)

    assert resp.status_code == 404
