/**
 * Pod drill-down — the portal's `kubectl describe pod`: status, every
 * container's current and last state (OOMKilled, exit codes), the running
 * image checksum, probes, mounts, volumes (expandable to their source),
 * events, metadata, and the live manifest.
 */

import React, { useMemo, useState } from "react";
import { MetricCard, MetricCardIcons } from "../../components/MetricCard";
import { ContainerStateDetail, PodContainerDetail, PodDetail, PodVolume, usePodDetail, WorkloadPod } from "../../services/aksApi";
import { DetailGrid, type GridColumn } from "./DetailGrid";
import {
  apiErrorDetail,
  ConditionsGrid,
  CopyButton,
  DetailIcons,
  EventsGrid,
  formatAge,
  KeyValueGrid,
  PodStatusBadge,
  ReadyBadge,
  splitImage,
  Truncate,
  YamlViewer,
} from "./detailShared";
import { DownloadLogsButton, LogArchiveDownload } from "./LogArchiveDownload";
import { PodVolumeDetail, VolumeMountRef } from "./PodVolumeDetail";
import { DetailCard, KpiRow, PropertyList, ResourceDetailShell, ResourceKindIcons } from "./ResourceDetailShell";

type Section = "overview" | "containers" | "volumes" | "events" | "metadata" | "yaml";

const POD_FAILURE = /BackOff|Err|Error|OOMKilled|Failed|Evicted|Unknown|DeadlineExceeded/i;

/** Shape the page's log viewer accepts — the same one the workload pod tables pass. */
export function podDetailToWorkloadPod(pod: PodDetail): WorkloadPod {
  return {
    pod_name: pod.name,
    namespace: pod.namespace,
    phase: pod.phase,
    status: pod.status,
    ready: pod.total_containers > 0 && pod.ready_containers === pod.total_containers,
    node: pod.node,
    pod_ip: pod.pod_ip,
    started_at: pod.started_at,
    restarts: pod.restarts,
    containers: [...pod.init_containers, ...pod.containers].map((c) => c.name),
    revision: null,
  };
}

function stateText(state: ContainerStateDetail | null, fmt: (v: string | null | undefined) => string): string {
  if (!state) return "—";
  if (state.state === "running") return `Running since ${fmt(state.started_at)}`;
  if (state.state === "waiting") return `Waiting: ${state.reason ?? "unknown"}${state.message ? ` — ${state.message}` : ""}`;
  const exit = state.signal ? `signal ${state.signal}` : `exit code ${state.exit_code ?? "?"}`;
  return `Terminated: ${state.reason ?? "unknown"} (${exit}) at ${fmt(state.finished_at)}${state.message ? ` — ${state.message}` : ""}`;
}

function StateBadge({ state }: { state: ContainerStateDetail | null }) {
  if (!state) return <span className="text-slate-400">—</span>;
  const label = state.state === "running" ? "Running" : state.reason || (state.state === "waiting" ? "Waiting" : "Terminated");
  const tone =
    state.state === "running" ? "bg-green-100 text-green-800"
    : state.state === "terminated" && state.exit_code === 0 ? "bg-blue-100 text-blue-800"
    : state.state === "waiting" && !POD_FAILURE.test(label) ? "bg-yellow-100 text-yellow-800"
    : "bg-red-100 text-red-800";
  return <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-medium ${tone}`}>{label}</span>;
}

function lastTermination(state: ContainerStateDetail | null): string | null {
  if (!state || state.state !== "terminated") return null;
  return `${state.reason ?? "Terminated"} · ${state.signal ? `signal ${state.signal}` : `exit ${state.exit_code ?? "?"}`}`;
}

function ImageChecksum({ value, full = false }: { value: string | null; full?: boolean }) {
  if (!value) return <span className="text-slate-400">not available — the container has not started</span>;
  return (
    <span className="inline-flex max-w-full items-center gap-2">
      <span className={`font-mono text-xs text-slate-800 ${full ? "break-all" : "whitespace-nowrap"}`} title={value}>
        {full ? value : `${value.slice(0, 12)}…`}
      </span>
      <CopyButton value={value} />
    </span>
  );
}

function containerKey(c: PodContainerDetail): string {
  return `${c.init ? "init:" : ""}${c.name}`;
}

function ContainerDetailPanel({
  c,
  fmt,
  onOpenVolume,
}: {
  c: PodContainerDetail;
  fmt: (v: string | null | undefined) => string;
  onOpenVolume: (name: string) => void;
}) {
  return (
    <div className="rounded-lg border border-att-100 bg-white p-4">
      <PropertyList
        items={[
          { label: "Image", value: c.image, mono: true, wide: true },
          { label: "Image checksum (sha256)", value: <ImageChecksum value={c.image_checksum} full />, wide: true },
          c.image_id && { label: "Image ID", value: c.image_id, mono: true, wide: true },
          { label: "State", value: stateText(c.state, fmt), wide: true },
          c.last_state && { label: "Last State", value: <span className="text-red-700">{stateText(c.last_state, fmt)}</span>, wide: true },
          { label: "CPU Request / Limit", value: `${c.cpu_request || "—"} / ${c.cpu_limit || "—"}`, mono: true },
          { label: "Memory Request / Limit", value: `${c.memory_request || "—"} / ${c.memory_limit || "—"}`, mono: true },
          c.ports.length > 0 && { label: "Ports", value: c.ports.join(", ") },
          ...Object.entries(c.probes).map(([kind, summary]) => ({ label: `${kind} probe`, value: summary, mono: true, wide: true })),
          c.volume_mounts.length > 0 && {
            label: "Volume Mounts",
            wide: true,
            value: (
              <ul className="space-y-1">
                {c.volume_mounts.map((m) => (
                  <li key={`${m.name}:${m.mount_path}`} className="flex flex-wrap items-center gap-x-2 text-xs">
                    <span className="font-mono text-slate-800">{m.mount_path}</span>
                    <span className="text-slate-400">←</span>
                    <button type="button" onClick={() => onOpenVolume(m.name)} className="text-blue-600 hover:text-blue-800 hover:underline" title="View volume details">
                      {m.name}
                    </button>
                    {m.sub_path && <span className="text-slate-500">subPath {m.sub_path}</span>}
                    {m.read_only && <span className="rounded bg-orange-50 px-1.5 text-orange-700">read-only</span>}
                  </li>
                ))}
              </ul>
            ),
          },
        ]}
      />
    </div>
  );
}

function ContainersGrid({
  containers,
  fmt,
  onOpenVolume,
}: {
  containers: PodContainerDetail[];
  fmt: (v: string | null | undefined) => string;
  onOpenVolume: (name: string) => void;
}) {
  // A single container is the common case — open it so the detail is one click closer.
  const [expanded, setExpanded] = useState<string | null>(containers.length === 1 ? containerKey(containers[0]) : null);
  const columns: GridColumn<PodContainerDetail>[] = [
    {
      key: "name",
      header: "Container",
      sortValue: (c) => c.name,
      render: (c) => (
        <button type="button" aria-expanded={expanded === containerKey(c)} className="inline-flex items-center gap-1.5 whitespace-nowrap font-medium text-slate-800">
          <span className={`text-slate-400 transition-transform ${expanded === containerKey(c) ? "rotate-90" : ""}`}>{DetailIcons.chevron}</span>
          {c.name}
          {c.init && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600">{c.sidecar ? "sidecar" : "init"}</span>}
        </button>
      ),
    },
    {
      key: "version",
      header: "Image Version",
      sortValue: (c) => splitImage(c.image).tag,
      render: (c) => (
        <span className="inline-flex items-center gap-2" title={c.image}>
          <span className="whitespace-nowrap rounded bg-indigo-50 px-2 py-0.5 font-mono text-xs font-semibold text-indigo-700">{splitImage(c.image).tag}</span>
        </span>
      ),
    },
    { key: "state", header: "State", sortValue: (c) => c.state?.state ?? "", render: (c) => <StateBadge state={c.state} /> },
    { key: "ready", header: "Ready", sortValue: (c) => (c.ready ? 1 : 0), render: (c) => <ReadyBadge ready={c.ready} /> },
    {
      key: "restarts",
      header: "Restarts",
      align: "center",
      sortValue: (c) => c.restart_count,
      render: (c) => <span className={c.restart_count > 0 ? "font-semibold text-red-600" : "text-slate-600"}>{c.restart_count}</span>,
    },
    {
      key: "last",
      header: "Last Termination",
      render: (c) => {
        const text = lastTermination(c.last_state);
        return text ? <span className="whitespace-nowrap text-xs font-medium text-red-700">{text}</span> : <span className="text-slate-400">—</span>;
      },
    },
    { key: "checksum", header: "Image Checksum", render: (c) => <ImageChecksum value={c.image_checksum} /> },
  ];
  return (
    <DetailGrid
      title="Containers"
      rows={containers}
      columns={columns}
      rowKey={containerKey}
      searchText={(c) => `${c.name} ${c.image} ${c.image_checksum ?? ""} ${c.state?.reason ?? ""}`}
      searchPlaceholder="Search container, image, checksum…"
      emptyText="No containers"
      expandedKey={expanded}
      onRowClick={(c) => setExpanded(expanded === containerKey(c) ? null : containerKey(c))}
      renderExpanded={(c) => <ContainerDetailPanel c={c} fmt={fmt} onOpenVolume={onOpenVolume} />}
    />
  );
}

function VolumesGrid({
  clusterId,
  namespace,
  volumes,
  mountsOf,
  expanded,
  onToggle,
  formatDate,
}: {
  clusterId: string;
  namespace: string;
  volumes: PodVolume[];
  mountsOf: (volume: string) => VolumeMountRef[];
  expanded: string | null;
  onToggle: (volume: string) => void;
  formatDate: (v: string) => string;
}) {
  const columns: GridColumn<PodVolume>[] = [
    {
      key: "name",
      header: "Volume",
      sortValue: (v) => v.name,
      render: (v) => (
        // The row handles the click; the button gives keyboard access.
        <button type="button" aria-expanded={expanded === v.name} className="inline-flex items-center gap-1.5 whitespace-nowrap text-left text-blue-600 hover:text-blue-800 hover:underline">
          <span className={`transition-transform ${expanded === v.name ? "rotate-90" : ""}`}>{DetailIcons.chevron}</span>
          {v.name}
        </button>
      ),
    },
    { key: "type", header: "Type", sortValue: (v) => v.type, render: (v) => <span className="whitespace-nowrap rounded bg-att-50 px-2 py-0.5 text-xs font-medium text-att-700">{v.type}</span> },
    { key: "source", header: "Source", sortValue: (v) => v.source ?? "", render: (v) => <Truncate value={v.source} className="font-mono text-xs" maxWidth="max-w-[18rem]" /> },
    {
      key: "mounts",
      header: "Mounted At",
      render: (v) => <Truncate value={mountsOf(v.name).map((m) => `${m.container}:${m.mount_path}`).join(", ")} className="font-mono text-xs" maxWidth="max-w-[22rem]" />,
    },
  ];
  return (
    <DetailGrid
      title="Volumes"
      rows={volumes}
      columns={columns}
      rowKey={(v) => v.name}
      searchText={(v) => `${v.name} ${v.type} ${v.source ?? ""} ${mountsOf(v.name).map((m) => m.mount_path).join(" ")}`}
      searchPlaceholder="Search volume, source, mount path…"
      emptyText="No volumes"
      initialSort={{ key: "name", direction: "asc" }}
      expandedKey={expanded}
      onRowClick={(v) => onToggle(v.name)}
      renderExpanded={(v) => (
        <PodVolumeDetail clusterId={clusterId} namespace={namespace} volume={v} mounts={mountsOf(v.name)} formatDate={formatDate} />
      )}
    />
  );
}

function Overview({ pod, formatDate }: { pod: PodDetail; formatDate: (v: string) => string }) {
  const fmt = (v: string | null | undefined) => (v ? formatDate(v) : null);
  const failing = POD_FAILURE.test(pod.status);
  const allReady = pod.total_containers > 0 && pod.ready_containers === pod.total_containers;
  return (
    <>
      {pod.status_message && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">{pod.status_message}</div>
      )}
      <KpiRow>
        <MetricCard
          title="Status"
          value={pod.status}
          subtitle={`Phase ${pod.phase ?? "unknown"}`}
          icon={MetricCardIcons.activity()}
          tone={pod.status === "Running" ? "green" : failing ? "red" : "amber"}
          valueClassName="text-xl"
        />
        <MetricCard
          title="Containers Ready"
          value={`${pod.ready_containers}/${pod.total_containers}`}
          subtitle={pod.init_containers.length ? `${pod.init_containers.length} init container${pod.init_containers.length === 1 ? "" : "s"}` : "No init containers"}
          icon={MetricCardIcons.checkCircle()}
          tone={allReady ? "green" : "amber"}
        />
        <MetricCard
          title="Restarts"
          value={pod.restarts}
          subtitle={pod.restarts ? "See Containers for the last termination" : "No container has restarted"}
          icon={MetricCardIcons.alert()}
          tone={pod.restarts > 0 ? "red" : "green"}
        />
        <MetricCard
          title="Age"
          value={formatAge(pod.started_at ?? pod.created_at)}
          subtitle={pod.started_at ? `Started ${formatDate(pod.started_at)}` : "Not started"}
          icon={MetricCardIcons.calendar()}
          tone="att"
        />
      </KpiRow>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <DetailCard title="Placement & Networking">
          <PropertyList
            items={[
              { label: "Controlled By", value: pod.workload ? `${pod.workload.kind}/${pod.workload.name}` : pod.owner ? `${pod.owner.kind}/${pod.owner.name}` : "None" },
              pod.workload && pod.owner && pod.owner.kind !== pod.workload.kind && { label: pod.owner.kind, value: pod.owner.name, mono: true },
              { label: "Node", value: pod.node, mono: true },
              { label: "Pod IP", value: pod.pod_ips.length > 1 ? pod.pod_ips.join(", ") : pod.pod_ip, mono: true },
              { label: "Host IP", value: pod.host_ip, mono: true },
              { label: "Created", value: fmt(pod.created_at) },
              pod.deletion_timestamp && { label: "Deletion Requested", value: fmt(pod.deletion_timestamp) },
            ]}
          />
        </DetailCard>
        <DetailCard title="Runtime">
          <PropertyList
            items={[
              { label: "Image Checksum", value: <ImageChecksum value={pod.image_checksum} full />, wide: true },
              { label: "QoS Class", value: pod.qos_class },
              { label: "Service Account", value: pod.service_account },
              { label: "Restart Policy", value: pod.restart_policy },
              { label: "Priority Class", value: pod.priority_class },
              { label: "Termination Grace", value: pod.termination_grace_period_seconds != null ? `${pod.termination_grace_period_seconds}s` : null },
            ]}
          />
        </DetailCard>
      </div>

      <ConditionsGrid conditions={pod.conditions} formatDate={formatDate} />
    </>
  );
}

function TolerationsGrid({ tolerations }: { tolerations: string[] }) {
  const rows = useMemo(() => tolerations.map((t, i) => ({ t, i })), [tolerations]);
  return (
    <DetailGrid
      title="Tolerations"
      rows={rows}
      columns={[{ key: "t", header: "Toleration", sortValue: (r) => r.t, render: (r) => <span className="font-mono text-xs">{r.t}</span> }]}
      rowKey={(r) => String(r.i)}
      searchText={(r) => r.t}
      searchPlaceholder="Search tolerations…"
      emptyText="None"
    />
  );
}

export function PodDetailModal({
  clusterId,
  namespace,
  name,
  formatDate,
  logDownload,
  onViewLogs,
  onClose,
}: {
  clusterId: string;
  namespace: string;
  name: string;
  formatDate: (value: string) => string;
  logDownload: LogArchiveDownload;
  onViewLogs: (pod: WorkloadPod) => void;
  onClose: () => void;
}) {
  const [section, setSection] = useState<Section>("overview");
  const [expandedVolume, setExpandedVolume] = useState<string | null>(null);
  const { data: pod, isLoading, isError, error } = usePodDetail(clusterId, namespace, name);
  const fmt = (v: string | null | undefined) => (v ? formatDate(v) : "—");
  const allContainers = useMemo(() => (pod ? [...pod.init_containers, ...pod.containers] : []), [pod]);
  const mountsOf = (volume: string): VolumeMountRef[] =>
    allContainers.flatMap((c) => c.volume_mounts.filter((m) => m.name === volume).map((m) => ({ container: c.name, ...m })));
  const openVolume = (volume: string) => {
    setExpandedVolume(volume);
    setSection("volumes");
  };
  const warnings = (pod?.events ?? []).filter((e) => e.type === "Warning").length;

  return (
    <ResourceDetailShell
      kind="Pod"
      name={name}
      namespace={namespace}
      icon={ResourceKindIcons.pod}
      status={pod && <PodStatusBadge status={pod.status} />}
      meta={
        pod && (
          <>
            <span className="font-mono">{pod.ready_containers}/{pod.total_containers} containers ready</span>
            <span className={pod.restarts > 0 ? "font-semibold text-red-600" : ""}>{pod.restarts} restarts</span>
            {pod.node && <span title={pod.node}>Node <span className="font-mono text-slate-700">{pod.node}</span></span>}
          </>
        )
      }
      actions={
        pod && (
          <>
            <button
              type="button"
              onClick={() => onViewLogs(podDetailToWorkloadPod(pod))}
              className="flex items-center gap-2 rounded-lg border border-att-200 bg-white px-3 py-1.5 text-sm text-att-700 hover:bg-att-50"
            >
              {DetailIcons.logs} View logs
            </button>
            <DownloadLogsButton
              download={logDownload}
              downloadKey={`pod:${namespace}/${name}`}
              request={{ clusterId, kind: "pods", pods: [{ namespace, name }] }}
              label={`Pod ${namespace}/${name}`}
            />
          </>
        )
      }
      tabs={[
        { key: "overview", label: "Overview" },
        { key: "containers", label: "Containers", count: pod ? allContainers.length : undefined },
        { key: "volumes", label: "Volumes", count: pod?.volumes.length },
        { key: "events", label: "Events", count: pod?.events.length, attention: warnings > 0 },
        { key: "metadata", label: "Metadata" },
        { key: "yaml", label: "YAML" },
      ]}
      activeTab={section}
      onTabChange={setSection}
      isLoading={isLoading}
      error={isError && !pod ? apiErrorDetail(error, "Failed to load pod details.") : null}
      onClose={onClose}
    >
      {pod && section === "overview" && <Overview pod={pod} formatDate={formatDate} />}
      {pod && section === "containers" && <ContainersGrid containers={allContainers} fmt={fmt} onOpenVolume={openVolume} />}
      {pod && section === "volumes" && (
        <VolumesGrid
          clusterId={clusterId}
          namespace={namespace}
          volumes={pod.volumes}
          mountsOf={mountsOf}
          expanded={expandedVolume}
          onToggle={(v) => setExpandedVolume(expandedVolume === v ? null : v)}
          formatDate={formatDate}
        />
      )}
      {pod && section === "events" && <EventsGrid events={pod.events} formatDate={formatDate} />}
      {pod && section === "metadata" && (
        <>
          <KeyValueGrid title="Labels" entries={pod.labels} />
          <KeyValueGrid title="Annotations" entries={pod.annotations} />
          <KeyValueGrid title="Node Selector" entries={pod.node_selector} />
          <TolerationsGrid tolerations={pod.tolerations} />
        </>
      )}
      {pod && section === "yaml" && <YamlViewer yaml={pod.yaml} fileName={`${namespace}_${name}_pod.yaml`} />}
    </ResourceDetailShell>
  );
}

export default PodDetailModal;
