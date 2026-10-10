/**
 * Building blocks shared by the AKS detail views (Deployment, Pod,
 * StatefulSet/DaemonSet, Job, AzureKeyVaultSecret) so every resource drills
 * down the same way. Every list is a DetailGrid: searchable, sortable, paged.
 */

import React, { useMemo, useState } from "react";
import { gridStyles } from "../../components/gridStyles";
import type { WorkloadCondition, WorkloadEvent, WorkloadPod, WorkloadStatus } from "../../services/aksApi";
import { DetailGrid, GridFilterSelect, type GridColumn } from "./DetailGrid";

export const iconProps = {
  width: 16,
  height: 16,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export const DetailIcons = {
  view: <svg {...iconProps}><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></svg>,
  logs: <svg {...iconProps}><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="16" y1="13" x2="8" y2="13" /><line x1="16" y1="17" x2="8" y2="17" /></svg>,
  trash: <svg {...iconProps}><polyline points="3 6 5 6 21 6" /><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" /><path d="M10 11v6" /><path d="M14 11v6" /><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2" /></svg>,
  download: <svg {...iconProps}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>,
  chevron: <svg {...iconProps} width={14} height={14}><polyline points="9 18 15 12 9 6" /></svg>,
};

// ── Badges and formatting ─────────────────────────────────────────────

export const WORKLOAD_STATUS_STYLES: Record<WorkloadStatus, string> = {
  Healthy: "bg-green-100 text-green-700",
  Updating: "bg-blue-100 text-blue-700",
  Degraded: "bg-amber-100 text-amber-700",
  Unavailable: "bg-red-100 text-red-700",
  Idle: "bg-gray-100 text-gray-600",
};

export function WorkloadStatusBadge({ status }: { status: WorkloadStatus }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium whitespace-nowrap ${WORKLOAD_STATUS_STYLES[status] ?? "bg-gray-100 text-gray-700"}`}>
      {status}
    </span>
  );
}

const POD_FAILURE = /BackOff|Err|Error|OOMKilled|Failed|Evicted|Invalid|Unknown|ContainerCannotRun|DeadlineExceeded/i;

/** Colour a kubectl-style pod status ("Running", "CrashLoopBackOff", "Init:0/1", ...). */
export function PodStatusBadge({ status }: { status: string | null | undefined }) {
  const value = status || "Unknown";
  const tone =
    value === "Running" ? "bg-green-100 text-green-800"
    : value === "Completed" || value === "Succeeded" ? "bg-blue-100 text-blue-800"
    : value === "Terminating" ? "bg-gray-100 text-gray-700"
    : POD_FAILURE.test(value) ? "bg-red-100 text-red-800"
    : "bg-yellow-100 text-yellow-800";
  return <span className={`px-2 py-0.5 rounded-full text-[11px] font-medium whitespace-nowrap ${tone}`}>{value}</span>;
}

export function ReadyBadge({ ready }: { ready: boolean }) {
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium ${ready ? "text-green-700" : "text-amber-700"}`}>
      <span className={`h-2 w-2 rounded-full ${ready ? "bg-green-500" : "bg-amber-500"}`} />
      {ready ? "Ready" : "Not ready"}
    </span>
  );
}

export function formatAge(iso: string | null | undefined): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  if (Number.isNaN(ms)) return "—";
  const hours = ms / 3_600_000;
  if (hours < 1) return `${Math.max(0, Math.round(hours * 60))}m`;
  if (hours < 24) return `${Math.floor(hours)}h`;
  return `${Math.floor(hours / 24)}d`;
}

/** Milliseconds since `iso`, for sorting by age; unknown sorts last. */
export function ageMs(iso: string | null | undefined): number {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isNaN(t) ? Number.MAX_SAFE_INTEGER : Date.now() - t;
}

export function apiErrorDetail(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
}

/** One-line text that truncates with the full value on hover. */
export function Truncate({ value, className = "", maxWidth = "max-w-[18rem]" }: { value: string | null | undefined; className?: string; maxWidth?: string }) {
  if (!value) return <span className="text-slate-400">—</span>;
  return <span className={`block truncate ${maxWidth} ${className}`} title={value}>{value}</span>;
}

// ── Small shared pieces ───────────────────────────────────────────────

export function KeyValue({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-att-100 py-1.5 text-sm">
      <span className="text-gray-500 shrink-0">{label}</span>
      <span className="text-right font-medium text-gray-800 break-all">{value ?? "—"}</span>
    </div>
  );
}

export function CopyButton({ value, label = "Copy" }: { value: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard access denied (insecure context or browser policy) — the value stays selectable.
    }
  };
  return (
    <button
      type="button"
      onClick={(e) => {
        e.stopPropagation();
        void copy();
      }}
      className="shrink-0 rounded border border-att-200 bg-white px-1.5 py-0.5 text-[11px] font-medium text-att-700 hover:bg-att-50"
    >
      {copied ? "Copied" : label}
    </button>
  );
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h4 className={`${gridStyles.sectionTitle} mt-4 mb-1`}>{children}</h4>;
}

const actionBtn = "p-1.5 rounded-lg disabled:opacity-50";

// ── Grids ─────────────────────────────────────────────────────────────

export type PodFilter = "all" | "ready" | "not-ready" | "restarted";

/** Pods of a workload, with drill-down into each pod plus logs and delete actions. */
export function WorkloadPodsGrid({
  pods,
  onOpenPod,
  onViewPodLogs,
  onDeletePod,
  canDeletePod,
  filter: controlledFilter,
  onFilterChange,
}: {
  pods: WorkloadPod[];
  onOpenPod?: (pod: WorkloadPod) => void;
  onViewPodLogs: (pod: WorkloadPod) => void;
  onDeletePod?: (pod: WorkloadPod) => void;
  canDeletePod: boolean;
  /** Optional controlled filter, so a KPI tile can open the grid pre-filtered. */
  filter?: PodFilter;
  onFilterChange?: (filter: PodFilter) => void;
}) {
  const [localFilter, setLocalFilter] = useState<PodFilter>("all");
  const filter = controlledFilter ?? localFilter;
  const setFilter = onFilterChange ?? setLocalFilter;
  const rows = useMemo(
    () =>
      pods.filter((p) =>
        filter === "all" ? true : filter === "ready" ? p.ready : filter === "not-ready" ? !p.ready : p.restarts > 0
      ),
    [pods, filter]
  );

  const columns: GridColumn<WorkloadPod>[] = [
    {
      key: "name",
      header: "Pod",
      sortValue: (p) => p.pod_name,
      render: (p) =>
        onOpenPod ? (
          <button
            type="button"
            onClick={() => onOpenPod(p)}
            title={`${p.pod_name} — view pod details`}
            className="block max-w-[22rem] truncate text-left font-mono text-xs text-blue-600 hover:text-blue-800 hover:underline"
          >
            {p.pod_name}
          </button>
        ) : (
          <Truncate value={p.pod_name} className="font-mono text-xs" maxWidth="max-w-[22rem]" />
        ),
    },
    { key: "status", header: "Status", sortValue: (p) => p.status ?? p.phase ?? "", render: (p) => <PodStatusBadge status={p.status ?? p.phase} /> },
    { key: "ready", header: "Ready", sortValue: (p) => (p.ready ? 1 : 0), render: (p) => <ReadyBadge ready={p.ready} /> },
    {
      key: "restarts",
      header: "Restarts",
      align: "center",
      sortValue: (p) => p.restarts,
      render: (p) => <span className={p.restarts > 0 ? "font-semibold text-red-600" : "text-slate-600"}>{p.restarts}</span>,
    },
    { key: "node", header: "Node", sortValue: (p) => p.node ?? "", render: (p) => <Truncate value={p.node} className="text-xs" maxWidth="max-w-[16rem]" /> },
    { key: "ip", header: "Pod IP", sortValue: (p) => p.pod_ip ?? "", render: (p) => <span className="whitespace-nowrap font-mono text-xs">{p.pod_ip ?? "—"}</span> },
    { key: "revision", header: "Revision", sortValue: (p) => p.revision ?? "", render: (p) => <span className="whitespace-nowrap font-mono text-xs">{p.revision ?? "—"}</span> },
    { key: "age", header: "Age", sortValue: (p) => ageMs(p.started_at), render: (p) => <span className="whitespace-nowrap font-mono text-xs">{formatAge(p.started_at)}</span> },
    {
      key: "actions",
      header: "Actions",
      align: "center",
      render: (p) => (
        <div className="flex items-center justify-center gap-1">
          <button type="button" title="View Logs" onClick={() => onViewPodLogs(p)} className={`${actionBtn} text-blue-600 hover:bg-blue-50`}>{DetailIcons.logs}</button>
          {canDeletePod && onDeletePod && (
            <button type="button" title="Delete Pod" onClick={() => onDeletePod(p)} className={`${actionBtn} text-red-600 hover:bg-red-50`}>{DetailIcons.trash}</button>
          )}
        </div>
      ),
    },
  ];

  const notReady = pods.filter((p) => !p.ready).length;
  const restarted = pods.filter((p) => p.restarts > 0).length;
  return (
    <DetailGrid
      title="Pods"
      rows={rows}
      columns={columns}
      rowKey={(p) => `${p.namespace}/${p.pod_name}`}
      searchText={(p) => [p.pod_name, p.status, p.phase, p.node, p.pod_ip, p.revision].join(" ")}
      searchPlaceholder="Search pod, node, IP, status…"
      emptyText={filter === "all" ? "No pods" : "No pods match this filter"}
      initialSort={{ key: "name", direction: "asc" }}
      toolbar={
        <GridFilterSelect<PodFilter>
          label="Filter pods"
          value={filter}
          onChange={setFilter}
          options={[
            { value: "all", label: `All pods (${pods.length})` },
            { value: "ready", label: `Ready (${pods.length - notReady})` },
            { value: "not-ready", label: `Not ready (${notReady})` },
            { value: "restarted", label: `Restarted (${restarted})` },
          ]}
        />
      }
    />
  );
}

export type EventFilter = "all" | "Warning" | "Normal";

export function EventsGrid({
  events,
  formatDate,
  showObject = false,
  title = "Events",
  type: controlledType,
  onTypeChange,
}: {
  events: WorkloadEvent[];
  formatDate: (v: string) => string;
  showObject?: boolean;
  title?: string;
  /** Optional controlled type filter, so a KPI tile can open the grid pre-filtered. */
  type?: EventFilter;
  onTypeChange?: (type: EventFilter) => void;
}) {
  const [localType, setLocalType] = useState<EventFilter>("all");
  const type = controlledType ?? localType;
  const setType = onTypeChange ?? setLocalType;
  const keyed = useMemo(() => events.map((e, i) => ({ ...e, _key: String(i) })), [events]);
  const rows = useMemo(() => keyed.filter((e) => type === "all" || e.type === type), [keyed, type]);
  const warnings = events.filter((e) => e.type === "Warning").length;

  const columns: GridColumn<(typeof keyed)[number]>[] = [
    {
      key: "type",
      header: "Type",
      sortValue: (e) => e.type ?? "",
      render: (e) => (
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold whitespace-nowrap ${e.type === "Warning" ? "bg-amber-100 text-amber-800" : "bg-slate-100 text-slate-600"}`}>
          {e.type ?? "—"}
        </span>
      ),
    },
    { key: "reason", header: "Reason", sortValue: (e) => e.reason ?? "", render: (e) => <span className="whitespace-nowrap font-medium text-slate-800">{e.reason ?? "—"}</span> },
    ...(showObject
      ? [{ key: "object", header: "Object", sortValue: (e: (typeof keyed)[number]) => e.object ?? "", render: (e: (typeof keyed)[number]) => <Truncate value={e.object} className="font-mono text-xs" maxWidth="max-w-[16rem]" /> }]
      : []),
    { key: "message", header: "Message", render: (e) => <span className="block min-w-[18rem] whitespace-normal break-words text-slate-700">{e.message ?? "—"}</span> },
    { key: "count", header: "Count", align: "center", sortValue: (e) => e.count, render: (e) => <span className="font-mono text-xs">{e.count}</span> },
    {
      key: "last_seen",
      header: "Last Seen",
      sortValue: (e) => e.last_seen ?? "",
      render: (e) => <span className="whitespace-nowrap text-xs text-slate-600">{e.last_seen ? formatDate(e.last_seen) : "—"}</span>,
    },
  ];

  return (
    <DetailGrid
      title={title}
      rows={rows}
      columns={columns}
      rowKey={(e) => e._key}
      searchText={(e) => [e.type, e.reason, e.message, e.object].join(" ")}
      searchPlaceholder="Search reason, message…"
      emptyText={type === "all" ? "No recent events — Kubernetes keeps events for about an hour." : `No ${type} events`}
      initialSort={{ key: "last_seen", direction: "desc" }}
      toolbar={
        <GridFilterSelect<EventFilter>
          label="Filter events"
          value={type}
          onChange={setType}
          options={[
            { value: "all", label: `All types (${events.length})` },
            { value: "Warning", label: `Warning (${warnings})` },
            { value: "Normal", label: `Normal (${events.length - warnings})` },
          ]}
        />
      }
    />
  );
}

export function ConditionsGrid({
  conditions,
  formatDate,
  healthyWhenFalse = [],
}: {
  conditions: WorkloadCondition[];
  formatDate: (v: string) => string;
  /** Condition types where "False" is the healthy state, e.g. a node's MemoryPressure. */
  healthyWhenFalse?: readonly string[];
}) {
  const healthy = (c: WorkloadCondition) => (healthyWhenFalse.includes(c.type) ? c.status === "False" : c.status === "True");
  const columns: GridColumn<WorkloadCondition>[] = [
    { key: "type", header: "Condition", sortValue: (c) => c.type, render: (c) => <span className="whitespace-nowrap font-medium text-slate-800">{c.type}</span> },
    {
      key: "status",
      header: "Status",
      sortValue: (c) => c.status,
      render: (c) => (
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${c.status === "Unknown" ? "bg-slate-100 text-slate-600" : healthy(c) ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-800"}`}>
          {c.status}
        </span>
      ),
    },
    { key: "reason", header: "Reason", sortValue: (c) => c.reason ?? "", render: (c) => <span className="whitespace-nowrap">{c.reason ?? "—"}</span> },
    { key: "message", header: "Message", render: (c) => <span className="block min-w-[16rem] whitespace-normal break-words text-slate-700">{c.message ?? "—"}</span> },
    {
      key: "transition",
      header: "Last Transition",
      sortValue: (c) => c.last_transition_time ?? "",
      render: (c) => <span className="whitespace-nowrap text-xs text-slate-600">{c.last_transition_time ? formatDate(c.last_transition_time) : "—"}</span>,
    },
  ];
  return (
    <DetailGrid
      title="Conditions"
      rows={conditions}
      columns={columns}
      rowKey={(c) => c.type}
      searchText={(c) => [c.type, c.status, c.reason, c.message].join(" ")}
      searchPlaceholder="Search conditions…"
      emptyText="No conditions reported"
    />
  );
}

/** Labels, annotations, selectors — any string map as a searchable key/value grid. */
export function KeyValueGrid({ title, entries, emptyText = "None" }: { title: string; entries: Record<string, string>; emptyText?: string }) {
  const rows = useMemo(() => Object.entries(entries).map(([key, value]) => ({ key, value })), [entries]);
  const columns: GridColumn<{ key: string; value: string }>[] = [
    { key: "key", header: "Key", sortValue: (r) => r.key, render: (r) => <span className="whitespace-nowrap font-mono text-xs text-slate-800">{r.key}</span> },
    { key: "value", header: "Value", sortValue: (r) => r.value, render: (r) => <span className="block min-w-[16rem] whitespace-normal break-all font-mono text-xs text-slate-600">{r.value || "—"}</span> },
  ];
  return (
    <DetailGrid
      title={title}
      rows={rows}
      columns={columns}
      rowKey={(r) => r.key}
      searchText={(r) => `${r.key} ${r.value}`}
      searchPlaceholder={`Search ${title.toLowerCase()}…`}
      emptyText={emptyText}
      initialSort={{ key: "key", direction: "asc" }}
    />
  );
}

export interface ContainerSpecRow {
  name: string;
  image: string;
  ports?: string[];
  cpu_request?: string;
  cpu_limit?: string;
  memory_request?: string;
  memory_limit?: string;
}

/** Split "registry/repo:tag" into the repository and the tag (version). */
export function splitImage(image: string): { repository: string; tag: string } {
  const at = image.indexOf("@");
  if (at >= 0) return { repository: image.slice(0, at), tag: image.slice(at + 1, at + 20) + "…" };
  const slash = image.lastIndexOf("/");
  const colon = image.lastIndexOf(":");
  return colon > slash ? { repository: image.slice(0, colon), tag: image.slice(colon + 1) } : { repository: image, tag: "latest" };
}

/** Container templates of a workload (image, version, ports, resources). */
export function ContainerSpecGrid({ containers }: { containers: ContainerSpecRow[] }) {
  const withResources = containers.some((c) => c.cpu_request !== undefined || c.memory_request !== undefined);
  const columns: GridColumn<ContainerSpecRow>[] = [
    { key: "name", header: "Container", sortValue: (c) => c.name, render: (c) => <span className="whitespace-nowrap font-medium text-slate-800">{c.name}</span> },
    { key: "image", header: "Image", sortValue: (c) => c.image, render: (c) => <Truncate value={splitImage(c.image).repository} className="font-mono text-xs" maxWidth="max-w-[40rem]" /> },
    {
      key: "version",
      header: "Version",
      sortValue: (c) => splitImage(c.image).tag,
      render: (c) => <span className="whitespace-nowrap rounded bg-indigo-50 px-2 py-0.5 font-mono text-xs font-semibold text-indigo-700">{splitImage(c.image).tag}</span>,
    },
    ...(containers.some((c) => c.ports && c.ports.length)
      ? [{ key: "ports", header: "Ports", render: (c: ContainerSpecRow) => <span className="whitespace-nowrap text-xs">{c.ports?.join(", ") || "—"}</span> }]
      : []),
    ...(withResources
      ? [
          { key: "cpu", header: "CPU Req / Limit", render: (c: ContainerSpecRow) => <span className="whitespace-nowrap font-mono text-xs">{c.cpu_request || "—"} / {c.cpu_limit || "—"}</span> },
          { key: "mem", header: "Memory Req / Limit", render: (c: ContainerSpecRow) => <span className="whitespace-nowrap font-mono text-xs">{c.memory_request || "—"} / {c.memory_limit || "—"}</span> },
        ]
      : []),
  ];
  return (
    <DetailGrid
      title="Containers"
      rows={containers}
      columns={columns}
      rowKey={(c) => c.name}
      searchText={(c) => `${c.name} ${c.image}`}
      searchPlaceholder="Search container or image…"
      emptyText="No containers"
    />
  );
}

/** Live manifest with line numbers, copy, and download. */
export function YamlViewer({ yaml, fileName }: { yaml: string; fileName: string }) {
  const lines = useMemo(() => (yaml ? yaml.replace(/\n$/, "").split("\n") : []), [yaml]);
  const download = () => {
    const url = URL.createObjectURL(new Blob([yaml], { type: "application/x-yaml" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = fileName;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };
  return (
    <section className="rounded-xl border border-att-100 bg-white shadow-sm">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-att-100 px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-800">Manifest</h3>
          <p className="text-xs text-slate-500">{lines.length} lines · live from the cluster, managedFields removed</p>
        </div>
        {yaml && (
          <div className="flex items-center gap-2">
            <CopyButton value={yaml} label="Copy YAML" />
            <button
              type="button"
              onClick={download}
              className="flex items-center gap-1 rounded border border-att-200 bg-white px-1.5 py-0.5 text-[11px] font-medium text-att-700 hover:bg-att-50"
            >
              {DetailIcons.download} Download
            </button>
          </div>
        )}
      </header>
      {yaml ? (
        <div className="max-h-[60vh] overflow-auto rounded-b-xl bg-slate-950 py-2 font-mono text-xs leading-5">
          <table className="border-collapse">
            <tbody>
              {lines.map((line, i) => (
                <tr key={i}>
                  <td className="select-none px-3 text-right align-top text-slate-500">{i + 1}</td>
                  <td className="whitespace-pre pr-6 text-slate-100">{line || " "}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="px-4 py-6 text-sm text-slate-400">Manifest unavailable</p>
      )}
    </section>
  );
}
