"""Pod waits for large scale-ups: the timeout restarts while pods keep coming
up, a stalled wait says why, and a step can move on at a share of its pods."""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles

from app.models.database import AuditLog, EnvironmentExecutionHistory, EnvironmentSchedule, EnvironmentSequence
from app.services import environment_scaling_service as env_module
from app.services.environment_scaling_service import EnvironmentScalingService


@compiles(JSONB, "sqlite")
def _jsonb_as_json_on_sqlite(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture(autouse=True)
def _fast_polling(monkeypatch):
    monkeypatch.setattr(env_module, "POLL_SECONDS", 0.05)
    monkeypatch.setattr(env_module, "DIAGNOSE_AFTER_SECONDS", 0.1)


def _pod(phase="Pending", scheduled_message=None, waiting=None, ready=False):
    conditions = (
        [SimpleNamespace(type="PodScheduled", status="False", message=scheduled_message, reason="Unschedulable")]
        if scheduled_message
        else []
    )
    containers = (
        []
        if phase == "Pending" and scheduled_message
        else [
            SimpleNamespace(
                state=SimpleNamespace(waiting=SimpleNamespace(reason=waiting) if waiting else None),
                last_state=SimpleNamespace(terminated=None),
                ready=ready,
                restart_count=0,
            )
        ]
    )
    return SimpleNamespace(
        metadata=SimpleNamespace(deletion_timestamp=None),
        status=SimpleNamespace(
            phase=phase, conditions=conditions, init_container_statuses=None, container_statuses=containers
        ),
    )


class RampingCluster:
    """Ready pods follow a script, one entry per status read (the last repeats)."""

    def __init__(self, ready_script, pods=(), conditions=()):
        self.ready_script = list(ready_script)
        self.reads = 0
        self.pods = list(pods)
        self.conditions = list(conditions)
        self.replicas: dict[str, int] = {}

    async def scale_deployment(self, *, cluster_id, namespace, deployment_name, replicas, user_id, user_email):
        previous = self.replicas.get(deployment_name, 0)
        self.replicas[deployment_name] = replicas
        return {"previous_replicas": previous}

    async def _get_k8s_clients(self, cluster_id):
        def read_status(name, namespace):
            ready = self.ready_script[min(self.reads, len(self.ready_script) - 1)]
            self.reads += 1
            return SimpleNamespace(
                spec=SimpleNamespace(selector=SimpleNamespace(match_labels={"app": name})),
                status=SimpleNamespace(ready_replicas=ready, available_replicas=ready, conditions=self.conditions),
            )

        def list_pods(namespace, label_selector=None, _request_timeout=None):
            return SimpleNamespace(items=self.pods)

        return (
            SimpleNamespace(read_namespaced_deployment_status=read_status),
            SimpleNamespace(list_namespaced_pod=list_pods),
            None,
        )


async def _wait(cluster, *, desired, timeout, percent=100, progress=None):
    service = EnvironmentScalingService(None)
    service._aks = cluster

    async def on_progress(ready, required, issue):
        if progress is not None:
            progress.append((ready, required, issue))

    return await service._wait_for_deployment(
        cluster_id="c1",
        namespace="apps",
        deployment_name="reportmanager",
        desired_replicas=desired,
        timeout_seconds=timeout,
        wait_condition="pods_ready",
        min_ready_percent=percent,
        on_progress=on_progress,
    )


@pytest.mark.anyio
async def test_a_slow_scale_up_that_keeps_progressing_is_not_failed():
    # 0 → 12 pods, one more every poll: ~0.6s in total against a 0.3s window.
    cluster = RampingCluster(range(0, 13))
    progress: list = []

    reached = await _wait(cluster, desired=12, timeout=0.3, progress=progress)

    assert reached == 12
    assert [p[0] for p in progress][-1] == 12  # the UI saw every step of the ramp


@pytest.mark.anyio
async def test_a_stalled_scale_up_fails_and_says_the_cluster_is_full():
    pods = [_pod(phase="Running", ready=True)] * 2 + [
        _pod(scheduled_message="0/12 nodes are available: 12 Insufficient cpu.")
    ] * 3
    progress: list = []

    with pytest.raises(TimeoutError) as exc:
        await _wait(RampingCluster([0, 1, 2], pods=pods), desired=5, timeout=0.3, progress=progress)

    message = str(exc.value)
    assert message.startswith("only 2/5 pods ready; no new pod became ready for 0.3s")
    assert "3 pods unschedulable (0/12 nodes are available: 12 Insufficient cpu)" in message
    assert "node pool autoscaler" in message
    # While it was stuck, the reason was already reported live.
    assert any(issue and "Insufficient cpu" in issue for _, _, issue in progress)


@pytest.mark.anyio
async def test_crashing_containers_are_named_with_a_dont_wait_hint():
    pods = [_pod(phase="Running", waiting="CrashLoopBackOff")] * 4
    with pytest.raises(TimeoutError) as exc:
        await _wait(RampingCluster([0], pods=pods), desired=4, timeout=0.2)
    assert "4 pods CrashLoopBackOff" in str(exc.value)
    assert "waiting longer won't help" in str(exc.value)


@pytest.mark.anyio
async def test_a_quota_that_blocks_pod_creation_is_reported():
    quota = SimpleNamespace(
        type="ReplicaFailure",
        status="True",
        reason="FailedCreate",
        message='pods "reportmanager-x" is forbidden: exceeded quota: compute, requested: cpu=2',
    )
    with pytest.raises(TimeoutError) as exc:
        await _wait(RampingCluster([0], conditions=[quota]), desired=60, timeout=0.2)
    assert 'Pods cannot be created: pods "reportmanager-x" is forbidden: exceeded quota' in str(exc.value)


@pytest.mark.anyio
async def test_a_step_can_move_on_once_a_share_of_its_pods_is_ready():
    # Stuck at 48 of 60 — but 80% is enough for the next service to start.
    reached = await _wait(RampingCluster([10, 30, 48]), desired=60, timeout=0.3, percent=80)
    assert reached == 48


@pytest.fixture
async def factory(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'env.db'}")
    async with engine.begin() as conn:
        for model in (EnvironmentSequence, EnvironmentSchedule, EnvironmentExecutionHistory, AuditLog):
            await conn.run_sync(lambda c, m=model: m.__table__.create(c))
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.mark.anyio
async def test_the_executor_records_live_counts_and_a_threshold_note(factory):
    async with factory() as db:
        seq = EnvironmentSequence(
            name="UI_Startup",
            cluster_id="c1",
            namespace="apps",
            sequence_type="startup",
            rollback_on_failure=True,
            created_by="u1",
            steps=[
                {
                    "order": 1,
                    "deployment_name": "reportmanager",
                    "replicas": 60,
                    "wait_condition": "pods_ready",
                    "timeout_seconds": 1,
                    "min_ready_percent": 80,
                    "on_failure": "abort",
                }
            ],
        )
        db.add(seq)
        await db.commit()
        service = EnvironmentScalingService(db)
        service._aks = RampingCluster([0, 20, 40, 48])
        result = await service.execute_sequence(
            sequence_id=seq.id, replica_count=1, dry_run=False, user_id="u1", user_email="u1@example.com"
        )

    step = result["details"][0]
    assert result["status"] == "completed"
    assert (step["ready_replicas"], step["required_ready"]) == (48, 48)
    assert step["note"].startswith("Continued with 48/60 ready (80% threshold)")
    assert "last_progress_at" in step and "pod_issues" not in step


def test_a_long_running_wait_that_is_still_progressing_is_not_swept():
    now = datetime.utcnow()
    row = EnvironmentExecutionHistory(
        execution_type="sequence",
        status="running",
        started_at=now - timedelta(hours=1),
        step_details=[
            {
                "step": 1,
                "deployment": "reportmanager",
                "status": "running",
                "timeout_seconds": 600,
                "started_at": (now - timedelta(minutes=50)).isoformat() + "Z",
                "last_progress_at": (now - timedelta(seconds=30)).isoformat() + "Z",
            }
        ],
    )
    # 50 minutes in, but a pod became ready 30s ago: alive for another ~10 min + grace.
    assert EnvironmentScalingService._abandon_deadline(row) > now + timedelta(minutes=9)
