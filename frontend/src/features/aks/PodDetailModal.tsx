/**
 * Pod drill-down — the portal's `kubectl describe pod`: status, every
 * container's current and last state (OOMKilled, exit codes), the running
 * image checksum, probes, mounts, volumes (expandable to their source),
 * events, and the live manifest.
 */

import React, { useState } from "react";
import { gridStyles, Spinner } from "../../components/gridStyles";
import { ContainerStateDetail, PodContainerDetail, PodDetail, usePodDetail, WorkloadPod } from "../../services/aksApi";
import { GridStateRow } from "./aksGridShared";
import {
  apiErrorDetail,
  ConditionList,
  CopyButton,
  DetailIcons,
  DetailTabs,
  EventList,
  KeyValue,
  LabelChips,
  PodStatusBadge,
  SectionTitle,
  YamlView,
} from "./detailShared";
import { ModalShell } from "./K8sResourceModals";
import { DownloadLogsButton, LogArchiveDownload } from "./LogArchiveDownload";
import { PodVolumeDetail, VolumeMountRef } from "./PodVolumeDetail";

type Section = "overview" | "containers" | "events" | "volumes" | "yaml";

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

function stateTone(state: ContainerStateDetail | null): string {
  if (!state) return "text-gray-500";
  if (state.state === "running") return "text-green-700";
  if (state.state === "terminated" && state.exit_code === 0) return "text-blue-700";
  return "text-red-700";
}

function ImageChecksum({ value }: { value: string | null }) {
  if (!value) return <span className="text-gray-400">not available — the container has not started</span>;
  return (
    <span className="inline-flex items-start gap-2">
      <span className="font-mono text-xs text-gray-800 break-all">{value}</span>
      <CopyButton value={value} />
    </span>
  );
}

function ContainerCard({
  c,
  fmt,
  onOpenVolume,
}: {
  c: PodContainerDetail;
  fmt: (v: string | null | undefined) => string;
  onOpenVolume: (name: string) => void;
}) {
  return (
    <div className="rounded-lg border border-att-100 p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="font-semibold text-gray-900">{c.name}</span>
          {c.init && (
            <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-700">{c.sidecar ? "sidecar" : "init"}</span>
          )}
          <span className={c.ready ? "text-xs text-green-700" : "text-xs text-amber-700"}>{c.ready ? "ready" : "not ready"}</span>
        </div>
        <span className={c.restart_count > 0 ? "text-xs font-semibold text-red-600" : "text-xs text-gray-500"}>
          {c.restart_count} restart{c.restart_count === 1 ? "" : "s"}
        </span>
      </div>
      <p className="mt-1 font-mono text-xs text-gray-600 break-all">{c.image}</p>
      <div className="mt-1 flex items-start gap-2 text-xs">
        <span className="shrink-0 text-gray-500">Image checksum (sha256):</span>
        <ImageChecksum value={c.image_checksum} />
      </div>
      {c.image_id && <p className="text-[11px] text-gray-400 break-all">Image ID: <span className="font-mono">{c.image_id}</span></p>}
      <div className="mt-2 space-y-0.5">
        <p className={stateTone(c.state)}><span className="text-gray-500">State: </span>{stateText(c.state, fmt)}</p>
        {c.last_state && (
          <p className={stateTone(c.last_state)}><span className="text-gray-500">Last state: </span>{stateText(c.last_state, fmt)}</p>
        )}
      </div>
      <div className="mt-2 grid grid-cols-1 gap-x-4 text-xs text-gray-600 md:grid-cols-2">
        <p><span className="text-gray-500">CPU req / limit:</span> {c.cpu_request || "—"} / {c.cpu_limit || "—"}</p>
        <p><span className="text-gray-500">Memory req / limit:</span> {c.memory_request || "—"} / {c.memory_limit || "—"}</p>
        {c.ports.length > 0 && <p><span className="text-gray-500">Ports:</span> {c.ports.join(", ")}</p>}
      </div>
      {Object.keys(c.probes).length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-gray-600">
          {Object.entries(c.probes).map(([kind, summary]) => (
            <li key={kind}><span className="capitalize text-gray-500">{kind}:</span> <span className="font-mono break-all">{summary}</span></li>
          ))}
        </ul>
      )}
      {c.volume_mounts.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs text-gray-600">
          {c.volume_mounts.map((m) => (
            <li key={`${m.name}:${m.mount_path}`}>
              <span className="font-mono">{m.mount_path}</span> ←{" "}
              <button type="button" onClick={() => onOpenVolume(m.name)} className="text-blue-600 hover:text-blue-800 hover:underline" title="View volume details">
                {m.name}
              </button>
              {m.sub_path && <span className="text-gray-500"> (subPath {m.sub_path})</span>}
              {m.read_only && <span className="ml-1 text-orange-600">read-only</span>}
            </li>
          ))}
        </ul>
      )}
    </div>
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
  const allContainers = pod ? [...pod.init_containers, ...pod.containers] : [];
  const mountsOf = (volume: string): VolumeMountRef[] =>
    allContainers.flatMap((c) => c.volume_mounts.filter((m) => m.name === volume).map((m) => ({ container: c.name, ...m })));
  const openVolume = (volume: string) => {
    setExpandedVolume(volume);
    setSection("volumes");
  };

  const tabs: { key: Section; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "containers", label: `Containers${pod ? ` (${allContainers.length})` : ""}` },
    { key: "events", label: `Events${pod ? ` (${pod.events.length})` : ""}` },
    { key: "volumes", label: `Volumes${pod ? ` (${pod.volumes.length})` : ""}` },
    { key: "yaml", label: "YAML" },
  ];

  return (
    <ModalShell title={`Pod: ${namespace}/${name}`} onClose={onClose} wide>
      {isLoading && (
        <div className="flex items-center justify-center gap-2 py-8 text-sm text-gray-500"><Spinner className="h-4 w-4" />Loading pod…</div>
      )}
      {isError && !pod && <p className="text-sm text-red-600">{apiErrorDetail(error, "Failed to load pod details.")}</p>}
      {pod && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex flex-wrap items-center gap-2 text-sm text-gray-600">
              <PodStatusBadge status={pod.status} />
              <span className="font-mono">{pod.ready_containers}/{pod.total_containers} ready</span>
              <span className={pod.restarts > 0 ? "font-semibold text-red-600" : ""}>· {pod.restarts} restarts</span>
            </div>
            <div className="flex items-center gap-2">
              <button
                type="button"
                onClick={() => onViewLogs(podDetailToWorkloadPod(pod))}
                className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-att-200 text-sm text-att-700 hover:bg-att-50"
              >
                {DetailIcons.logs} View logs
              </button>
              <DownloadLogsButton
                download={logDownload}
                downloadKey={`pod:${namespace}/${name}`}
                request={{ clusterId, kind: "pods", pods: [{ namespace, name }] }}
                label={`Pod ${namespace}/${name}`}
              />
            </div>
          </div>
          {pod.status_message && (
            <p className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">{pod.status_message}</p>
          )}

          <DetailTabs tabs={tabs} active={section} onChange={setSection} />

          {section === "overview" && (
            <div className="grid grid-cols-1 gap-x-6 md:grid-cols-2">
              <div>
                <KeyValue label="Phase" value={pod.phase} />
                <KeyValue label="Image checksum" value={<ImageChecksum value={pod.image_checksum} />} />
                <KeyValue label="Controlled By" value={pod.workload ? `${pod.workload.kind}/${pod.workload.name}` : pod.owner ? `${pod.owner.kind}/${pod.owner.name}` : "None"} />
                {pod.workload && pod.owner && pod.owner.kind !== pod.workload.kind && (
                  <KeyValue label={pod.owner.kind} value={pod.owner.name} />
                )}
                <KeyValue label="Node" value={pod.node} />
                <KeyValue label="Pod IP" value={pod.pod_ips.length > 1 ? pod.pod_ips.join(", ") : pod.pod_ip} />
                <KeyValue label="Host IP" value={pod.host_ip} />
                <KeyValue label="Created" value={fmt(pod.created_at)} />
                <KeyValue label="Started" value={fmt(pod.started_at)} />
                {pod.deletion_timestamp && <KeyValue label="Deletion requested" value={fmt(pod.deletion_timestamp)} />}
              </div>
              <div>
                <KeyValue label="QoS Class" value={pod.qos_class} />
                <KeyValue label="Service Account" value={pod.service_account} />
                <KeyValue label="Restart Policy" value={pod.restart_policy} />
                <KeyValue label="Priority Class" value={pod.priority_class ?? "—"} />
                <KeyValue label="Termination Grace" value={pod.termination_grace_period_seconds != null ? `${pod.termination_grace_period_seconds}s` : "—"} />
                <KeyValue label="Node Selector" value={Object.entries(pod.node_selector).map(([k, v]) => `${k}=${v}`).join(", ") || "—"} />
              </div>
              <div className="md:col-span-2">
                <SectionTitle>Conditions</SectionTitle>
                <ConditionList conditions={pod.conditions} formatDate={formatDate} />
                <SectionTitle>Labels</SectionTitle>
                <LabelChips labels={pod.labels} />
                <SectionTitle>Annotations</SectionTitle>
                <LabelChips labels={pod.annotations} />
                <SectionTitle>Tolerations</SectionTitle>
                {pod.tolerations.length === 0 ? (
                  <p className="text-sm text-gray-400">None</p>
                ) : (
                  <ul className="space-y-0.5 font-mono text-xs text-gray-700">
                    {pod.tolerations.map((t) => <li key={t}>{t}</li>)}
                  </ul>
                )}
              </div>
            </div>
          )}

          {section === "containers" && (
            <div className="space-y-3">
              {allContainers.map((c) => (
                <ContainerCard key={`${c.init ? "init:" : ""}${c.name}`} c={c} fmt={fmt} onOpenVolume={openVolume} />
              ))}
            </div>
          )}

          {section === "events" && <EventList events={pod.events} formatDate={formatDate} />}

          {section === "volumes" && (
            <div className="overflow-x-auto">
              <table className={gridStyles.table}>
                <thead className={gridStyles.head}>
                  <tr>
                    <th className={gridStyles.headerCell}>Volume</th>
                    <th className={gridStyles.headerCell}>Type</th>
                    <th className={gridStyles.headerCell}>Source</th>
                    <th className={gridStyles.headerCell}>Mounted At</th>
                  </tr>
                </thead>
                <tbody>
                  {pod.volumes.length === 0 && <GridStateRow colSpan={4} emptyText="No volumes" />}
                  {pod.volumes.map((v) => {
                    const mounts = mountsOf(v.name);
                    const expanded = expandedVolume === v.name;
                    return (
                      <React.Fragment key={v.name}>
                        <tr
                          className={`${gridStyles.row} cursor-pointer ${expanded ? gridStyles.selectedRow : ""}`}
                          onClick={() => setExpandedVolume(expanded ? null : v.name)}
                        >
                          <td className={gridStyles.cell}>
                            {/* The row handles the click; the button gives keyboard access. */}
                            <button type="button" aria-expanded={expanded} className="inline-flex items-center gap-1 text-left text-blue-600 hover:text-blue-800 hover:underline">
                              <svg width={12} height={12} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} className={`shrink-0 transition-transform ${expanded ? "rotate-90" : ""}`}><polyline points="9 18 15 12 9 6" /></svg>
                              {v.name}
                            </button>
                          </td>
                          <td className={gridStyles.cell}>{v.type}</td>
                          <td className={gridStyles.cell}><span className="font-mono text-xs break-all">{v.source ?? "—"}</span></td>
                          <td className={gridStyles.cell}>
                            <span className="font-mono text-xs break-all">{mounts.map((m) => `${m.container}:${m.mount_path}`).join(", ") || "—"}</span>
                          </td>
                        </tr>
                        {expanded && (
                          <tr className="border-t border-att-100">
                            <td colSpan={4} className="bg-att-50/40 px-4 pb-4 pt-1">
                              <PodVolumeDetail clusterId={clusterId} namespace={namespace} volume={v} mounts={mounts} formatDate={formatDate} />
                            </td>
                          </tr>
                        )}
                      </React.Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}

          {section === "yaml" && <YamlView yaml={pod.yaml} />}
        </div>
      )}
    </ModalShell>
  );
}

export default PodDetailModal;
