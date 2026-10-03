"""Bulk export of complete pod logs as a streamed ZIP archive.

One archive covers a Deployment, StatefulSet, DaemonSet, or an explicit list of
pods.  Every container (init containers included) contributes its full log as
Kubernetes retains it — no tail limit — and, for containers that restarted, the
log of the previous instance too.

The archive is produced incrementally so neither the backend nor the ingress
holds it in memory, and backend replicas stay stateless:

* Logs are fetched a few streams ahead of the ZIP writer, each into a spooled
  temp file (memory up to ``SPOOL_MEMORY_BYTES``, then disk).  This keeps the
  per-request footprint bounded however large a container log is.
* Fetches run on a dedicated small thread pool so a large export cannot starve
  the default executor every other Kubernetes call in the portal relies on.
* One failing stream (container never started, pod deleted mid-export) is
  recorded in ``SUMMARY.txt`` instead of aborting the archive.
"""

from __future__ import annotations

import asyncio
import json
import tempfile
import zipfile
from collections import deque
from collections.abc import AsyncIterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import IO, Any, Literal

import structlog
from kubernetes.client.rest import ApiException

from app.services.aks_workload_operations import _label_selector

logger = structlog.get_logger(__name__)

ArchiveKind = Literal["deployment", "statefulset", "daemonset", "pods"]

MAX_ARCHIVE_PODS = 500
FETCH_WINDOW = 4  # log streams fetched ahead of the ZIP writer
CHUNK_BYTES = 256 * 1024
SPOOL_MEMORY_BYTES = 2 * 1024 * 1024
LOG_REQUEST_TIMEOUT = (10, 300)  # (connect, read) seconds for one container log

_KIND_LABEL: dict[str, str] = {"deployment": "Deployment", "statefulset": "StatefulSet", "daemonset": "DaemonSet"}
_READ_CALL: dict[str, str] = {
    "deployment": "read_namespaced_deployment",
    "statefulset": "read_namespaced_stateful_set",
    "daemonset": "read_namespaced_daemon_set",
}

_fetch_executor = ThreadPoolExecutor(max_workers=8, thread_name_prefix="aks-log-archive")


# ── Plan ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LogStream:
    namespace: str
    pod: str
    container: str
    init: bool = False
    previous: bool = False

    @property
    def arcname(self) -> str:
        folder = f"{self.namespace}/{self.pod}" + ("/init" if self.init else "")
        return f"{folder}/{self.container}{'.previous' if self.previous else ''}.log"

    @property
    def instance(self) -> str:
        return "previous" if self.previous else "current"


@dataclass
class LogArchivePlan:
    cluster_name: str
    target: str
    root: str
    pod_count: int
    streams: list[LogStream]
    missing_pods: list[str] = field(default_factory=list)

    @property
    def filename(self) -> str:
        return f"{self.root}.zip"


@dataclass
class _StreamResult:
    stream: LogStream
    size: int
    status: Literal["ok", "partial", "failed"]
    note: str = ""


def pod_log_streams(pod: Any, include_previous: bool) -> list[LogStream]:
    """Every log stream a pod can serve: init containers first, then app containers."""
    ns, name = pod.metadata.namespace, pod.metadata.name
    streams: list[LogStream] = []
    groups = (
        (True, pod.spec.init_containers, pod.status.init_container_statuses),
        (False, pod.spec.containers, pod.status.container_statuses),
    )
    for init, specs, statuses in groups:
        restarts = {cs.name: cs.restart_count or 0 for cs in (statuses or [])}
        for c in specs or []:
            streams.append(LogStream(ns, name, c.name, init=init))
            # Kubernetes keeps exactly one terminated instance of a restarted container.
            if include_previous and restarts.get(c.name, 0) > 0:
                streams.append(LogStream(ns, name, c.name, init=init, previous=True))
    return streams


def _archive_root(cluster_name: str, kind: str, label: str, now: datetime) -> str:
    return f"{cluster_name}_{kind}_{label}_{now.strftime('%Y%m%dT%H%M%SZ')}"


def _human_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def render_summary(plan: LogArchivePlan, results: list[_StreamResult], generated_at: datetime) -> str:
    failed = sum(1 for r in results if r.status == "failed")
    partial_count = sum(1 for r in results if r.status == "partial")
    lines = [
        "AKS log archive",
        "",
        f"Cluster:      {plan.cluster_name}",
        f"Target:       {plan.target}",
        f"Generated:    {generated_at.strftime('%Y-%m-%dT%H:%M:%SZ')}",
        f"Pods:         {plan.pod_count}",
        f"Log streams:  {len(results)} ({len(results) - failed - partial_count} complete, "
        f"{partial_count} partial, {failed} failed)",
        f"Total size:   {_human_size(sum(r.size for r in results))} uncompressed",
        "",
        "Notes",
        "- Each .log file is the complete output Kubernetes retains for that container since it",
        "  started, with an RFC 3339 timestamp on every line. If the kubelet rotated a container's",
        "  log after it hit the node's size limit, the Kubernetes API serves only the newest file;",
        "  older output is available only in Log Analytics / Container Insights.",
        "- *.previous.log is the last terminated instance of a container that restarted.",
        "  Kubernetes keeps only one previous instance per container.",
        "- Init container logs are under <pod>/init/.",
    ]
    if plan.missing_pods:
        lines += ["", "Pods no longer present (skipped):"] + [f"- {p}" for p in plan.missing_pods]

    rows = [("POD", "CONTAINER", "INSTANCE", "STATUS", "SIZE", "NOTE")]
    for r in results:
        s = r.stream
        container = f"{s.container} (init)" if s.init else s.container
        rows.append((f"{s.namespace}/{s.pod}", container, s.instance, r.status, _human_size(r.size), r.note))
    widths = [max(len(row[i]) for row in rows) for i in range(5)]
    lines.append("")
    for row in rows:
        lines.append("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row[:5])) + "  " + row[5])
    return "\n".join(line.rstrip() for line in lines) + "\n"


# ── Streaming primitives ──────────────────────────────────────────────


class _ZipSink:
    """Write-only, unseekable target for ``zipfile`` that hands back what was written."""

    def __init__(self) -> None:
        self._buffer = bytearray()

    def write(self, data: bytes) -> int:
        self._buffer += data
        return len(data)

    def flush(self) -> None:
        pass

    def drain(self) -> bytes:
        data = bytes(self._buffer)
        self._buffer.clear()
        return data


def _k8s_error(exc: ApiException) -> str:
    try:
        message = json.loads(exc.body or b"{}").get("message")
    except (ValueError, TypeError, AttributeError):
        message = None
    return str(message or f"HTTP {exc.status} {exc.reason or ''}".strip())[:300]


def _spool_log(core_v1: Any, stream: LogStream) -> tuple[IO[bytes] | None, int, str | None]:
    """Blocking: copy one container log into a spooled temp file.

    Returns ``(spool, size, None)`` on success, ``(spool, size, note)`` when the
    stream broke off part-way (the bytes received are kept), and
    ``(None, 0, error)`` when the log could not be read at all.
    """
    # Ownership passes to the caller, which closes it after copying into the archive.
    spool = tempfile.SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES)  # noqa: SIM115
    received = 0
    try:
        resp = core_v1.read_namespaced_pod_log(
            name=stream.pod,
            namespace=stream.namespace,
            container=stream.container,
            previous=stream.previous,
            timestamps=True,
            _preload_content=False,
            _request_timeout=LOG_REQUEST_TIMEOUT,
        )
        try:
            for chunk in resp.stream(CHUNK_BYTES):
                spool.write(chunk)
                received += len(chunk)
        finally:
            resp.release_conn()
    except ApiException as e:
        spool.close()
        return None, 0, _k8s_error(e)
    except Exception as e:
        logger.warning("log_archive_stream_interrupted", pod=stream.pod, container=stream.container, error=str(e))
        if not received:
            spool.close()
            return None, 0, f"log stream failed: {type(e).__name__}"
        spool.seek(0)
        return spool, received, f"stream interrupted after {_human_size(received)}: {type(e).__name__}"
    spool.seek(0)
    return spool, received, None


def _entry_info(arcname: str, size: int) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(arcname, date_time=datetime.now().timetuple()[:6])
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    # A known size lets zipfile omit Zip64 headers, which some unzip tools (macOS
    # Archive Utility) mishandle in streamed archives.
    info.file_size = size
    return info


def _copy_chunk(source: IO[bytes], entry: IO[bytes]) -> int:
    chunk = source.read(CHUNK_BYTES)
    if chunk:
        entry.write(chunk)
    return len(chunk)


def _close_spool(task: asyncio.Future[Any]) -> None:
    if task.cancelled() or task.exception() is not None:
        return
    spool = task.result()[0]
    if spool is not None:
        spool.close()


# ── Service mixin ─────────────────────────────────────────────────────


class AKSLogArchiveMixin:
    """Plan and stream complete-log archives. Relies on ``AKSDetailOperationsMixin`` for ownership lookups."""

    async def _workload_pods_raw(self, apps_v1: Any, core_v1: Any, kind: str, namespace: str, name: str) -> list[Any]:
        obj = await asyncio.to_thread(getattr(apps_v1, _READ_CALL[kind]), name, namespace)
        selector = _label_selector(dict(obj.spec.selector.match_labels or {}) if obj.spec.selector else {})
        owner_uids = {obj.metadata.uid}
        if kind == "deployment":
            # Deployment pods are owned by its ReplicaSets, not by the Deployment itself.
            replica_sets = await self._owned_replica_sets(  # type: ignore[attr-defined]
                apps_v1, namespace, selector, obj.metadata.uid
            )
            owner_uids = {rs.metadata.uid for rs in replica_sets}
        return await self._owned_pods(core_v1, namespace, selector, owner_uids)  # type: ignore[attr-defined, no-any-return]

    async def _requested_pods(self, core_v1: Any, refs: list[tuple[str, str]]) -> tuple[list[Any], list[str]]:
        by_namespace: dict[str, set[str]] = {}
        for ns, pod in refs:
            by_namespace.setdefault(ns, set()).add(pod)
        found: list[Any] = []
        for ns, names in by_namespace.items():
            if len(names) == 1:
                (only,) = names
                try:
                    found.append(await asyncio.to_thread(core_v1.read_namespaced_pod, only, ns))
                except ApiException as e:
                    if e.status != 404:
                        raise
            else:
                pod_list = await asyncio.to_thread(core_v1.list_namespaced_pod, ns)
                found.extend(p for p in pod_list.items if p.metadata.name in names)
        present = {(p.metadata.namespace, p.metadata.name) for p in found}
        missing = sorted(f"{ns}/{pod}" for ns, pod in set(refs) - present)
        return found, missing

    async def plan_log_archive(
        self,
        cluster_id: str,
        kind: ArchiveKind,
        *,
        namespace: str | None = None,
        name: str | None = None,
        pods: list[tuple[str, str]] | None = None,
        include_previous: bool = True,
    ) -> LogArchivePlan:
        """Resolve the pods behind a target and the log streams the archive will contain.

        Raises ``ApiException`` (e.g. 404 for an unknown workload), ``LookupError``
        when none of the requested pods exist, and ``ValueError`` for an empty or
        oversized target.
        """
        apps_v1, core_v1, _ = await self._get_k8s_clients(cluster_id)  # type: ignore[attr-defined]
        cluster_name = cluster_id.rstrip("/").rsplit("/", 1)[-1]
        now = datetime.now(UTC)
        missing: list[str] = []

        if kind == "pods":
            refs = pods or []
            raw, missing = await self._requested_pods(core_v1, refs)
            if not raw:
                raise LookupError("None of the requested pods exist any more.")
            if len(refs) == 1:
                target = f"Pod {refs[0][0]}/{refs[0][1]}"
                root = _archive_root(cluster_name, "pod", refs[0][1], now)
            else:
                target = f"{len(raw)} selected pods"
                root = _archive_root(cluster_name, "pods", str(len(raw)), now)
        else:
            if not namespace or not name:
                raise ValueError("namespace and name are required for a workload log archive.")
            raw = await self._workload_pods_raw(apps_v1, core_v1, kind, namespace, name)
            target = f"{_KIND_LABEL[kind]} {namespace}/{name}"
            root = _archive_root(cluster_name, kind, name, now)
            if not raw:
                raise ValueError(f"{target} has no pods, so there are no logs to download.")

        if len(raw) > MAX_ARCHIVE_PODS:
            raise ValueError(
                f"{target} has {len(raw)} pods; a log archive is limited to {MAX_ARCHIVE_PODS}. "
                "Narrow the selection and download in batches."
            )
        raw.sort(key=lambda p: (p.metadata.namespace, p.metadata.name))
        streams = [s for p in raw for s in pod_log_streams(p, include_previous)]
        return LogArchivePlan(
            cluster_name=cluster_name,
            target=target,
            root=root,
            pod_count=len(raw),
            streams=streams,
            missing_pods=missing,
        )

    async def stream_log_archive(self, cluster_id: str, plan: LogArchivePlan) -> AsyncIterator[bytes]:
        """Yield the ZIP archive for ``plan`` chunk by chunk."""
        _, core_v1, _ = await self._get_k8s_clients(cluster_id)  # type: ignore[attr-defined]
        loop = asyncio.get_running_loop()
        upcoming = iter(plan.streams)
        pending: deque[tuple[LogStream, asyncio.Future[Any]]] = deque()
        results: list[_StreamResult] = []
        sink = _ZipSink()

        def fill_window() -> None:
            while len(pending) < FETCH_WINDOW and (stream := next(upcoming, None)) is not None:
                pending.append((stream, loop.run_in_executor(_fetch_executor, _spool_log, core_v1, stream)))

        try:
            with zipfile.ZipFile(sink, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                fill_window()
                while pending:
                    stream, fetch = pending.popleft()
                    spool, size, note = await fetch
                    fill_window()
                    if spool is None:
                        results.append(_StreamResult(stream, 0, "failed", note or "unavailable"))
                        continue
                    with spool, zf.open(_entry_info(f"{plan.root}/{stream.arcname}", size), "w") as entry:
                        while await asyncio.to_thread(_copy_chunk, spool, entry):
                            if data := sink.drain():
                                yield data
                    results.append(
                        _StreamResult(stream, size, "partial" if note else "ok", note or ("" if size else "no output"))
                    )
                    if data := sink.drain():
                        yield data
                zf.writestr(f"{plan.root}/SUMMARY.txt", render_summary(plan, results, datetime.now(UTC)))
            yield sink.drain()
            logger.info(
                "log_archive_completed",
                target=plan.target,
                pods=plan.pod_count,
                streams=len(results),
                failed=sum(1 for r in results if r.status == "failed"),
                bytes=sum(r.size for r in results),
            )
        finally:
            # Client disconnected or the export failed: release spools still being fetched.
            for _, fetch in pending:
                fetch.add_done_callback(_close_spool)
