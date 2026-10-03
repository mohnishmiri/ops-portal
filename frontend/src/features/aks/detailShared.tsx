/**
 * Building blocks shared by the AKS detail modals (Deployment, Pod,
 * StatefulSet/DaemonSet) so every resource drills down the same way.
 */

import React from "react";
import { gridStyles } from "../../components/gridStyles";
import type { WorkloadCondition, WorkloadEvent, WorkloadPod, WorkloadStatus } from "../../services/aksApi";
import { GridStateRow } from "./aksGridShared";

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
};

export const WORKLOAD_STATUS_STYLES: Record<WorkloadStatus, string> = {
  Healthy: "bg-green-100 text-green-700",
  Updating: "bg-blue-100 text-blue-700",
  Degraded: "bg-amber-100 text-amber-700",
  Unavailable: "bg-red-100 text-red-700",
  Idle: "bg-gray-100 text-gray-600",
};

export function WorkloadStatusBadge({ status }: { status: WorkloadStatus }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${WORKLOAD_STATUS_STYLES[status] ?? "bg-gray-100 text-gray-700"}`}>
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
  return <span className={`px-1.5 py-0.5 rounded-full text-[11px] font-medium whitespace-nowrap ${tone}`}>{value}</span>;
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

export function apiErrorDetail(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
}

export function DetailTabs<T extends string>({
  tabs,
  active,
  onChange,
}: {
  tabs: { key: T; label: string }[];
  active: T;
  // NoInfer: infer T from the tabs, not from a setState passed as onChange.
  onChange: (key: NoInfer<T>) => void;
}) {
  return (
    <div className="flex flex-wrap gap-1 border-b border-att-100">
      {tabs.map((t) => (
        <button
          key={t.key}
          type="button"
          onClick={() => onChange(t.key)}
          className={`px-3 py-2 text-sm border-b-2 -mb-px ${active === t.key ? "border-att-500 text-att-700 font-medium" : "border-transparent text-gray-500 hover:text-gray-700"}`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function KeyValue({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex justify-between gap-4 border-b border-att-100 py-1.5 text-sm">
      <span className="text-gray-500 shrink-0">{label}</span>
      <span className="text-right font-medium text-gray-800 break-all">{value ?? "—"}</span>
    </div>
  );
}

export function SectionTitle({ children }: { children: React.ReactNode }) {
  return <h4 className={`${gridStyles.sectionTitle} mt-4 mb-1`}>{children}</h4>;
}

export function LabelChips({ labels, empty = "None" }: { labels: Record<string, string>; empty?: string }) {
  const entries = Object.entries(labels);
  if (entries.length === 0) return <p className="text-sm text-gray-400">{empty}</p>;
  return (
    <div className="flex flex-wrap gap-1">
      {entries.map(([k, v]) => (
        <span key={k} className="rounded bg-att-50 px-2 py-0.5 font-mono text-[11px] text-gray-700 break-all">
          {k}={v}
        </span>
      ))}
    </div>
  );
}

export function ConditionList({ conditions, formatDate }: { conditions: WorkloadCondition[]; formatDate: (v: string) => string }) {
  if (conditions.length === 0) return <p className="text-sm text-gray-400">No conditions reported</p>;
  return (
    <ul className="space-y-1 text-sm">
      {conditions.map((c) => (
        <li key={c.type} className="flex flex-wrap gap-x-2">
          <span className="font-medium">{c.type}</span>
          <span className={c.status === "True" ? "text-green-700" : "text-amber-700"}>{c.status}</span>
          {c.reason && <span className="text-gray-500">({c.reason})</span>}
          {c.message && <span className="text-gray-700">{c.message}</span>}
          {c.last_transition_time && <span className="text-xs text-gray-400">{formatDate(c.last_transition_time)}</span>}
        </li>
      ))}
    </ul>
  );
}

export function EventList({
  events,
  formatDate,
  showObject = false,
}: {
  events: WorkloadEvent[];
  formatDate: (v: string) => string;
  showObject?: boolean;
}) {
  if (events.length === 0) {
    return <p className="text-sm text-gray-400">No recent events — Kubernetes keeps events for about an hour.</p>;
  }
  return (
    <ul className="space-y-2">
      {events.map((ev, i) => (
        <li key={i} className={`rounded-lg border px-3 py-2 text-sm ${ev.type === "Warning" ? "border-amber-200 bg-amber-50" : "border-att-100"}`}>
          <div className="flex justify-between gap-2">
            <span className="font-medium">
              {ev.reason}
              {ev.count > 1 && <span className="text-gray-500"> ×{ev.count}</span>}
              {showObject && ev.object && <span className="ml-2 font-mono text-xs font-normal text-gray-500">{ev.object}</span>}
            </span>
            <span className="text-xs text-gray-500 shrink-0">{ev.last_seen ? formatDate(ev.last_seen) : "—"}</span>
          </div>
          <p className="text-gray-700 break-words">{ev.message}</p>
        </li>
      ))}
    </ul>
  );
}

export function YamlView({ yaml }: { yaml: string }) {
  return (
    <pre className="max-h-[55vh] overflow-auto rounded-lg bg-gray-900 p-3 text-xs text-gray-100">{yaml || "Manifest unavailable"}</pre>
  );
}

const iconBtn = "p-1 rounded disabled:opacity-50";

/** Pods of a workload, with drill-down into each pod plus logs and delete actions. */
export function WorkloadPodsTable({
  pods,
  onOpenPod,
  onViewPodLogs,
  onDeletePod,
  canDeletePod,
}: {
  pods: WorkloadPod[];
  onOpenPod?: (pod: WorkloadPod) => void;
  onViewPodLogs: (pod: WorkloadPod) => void;
  onDeletePod?: (pod: WorkloadPod) => void;
  canDeletePod: boolean;
}) {
  return (
    <div className="overflow-x-auto">
      <table className={gridStyles.table}>
        <thead className={gridStyles.head}>
          <tr>
            <th className={gridStyles.headerCell}>Pod</th>
            <th className={gridStyles.headerCell}>Status</th>
            <th className={gridStyles.headerCell}>Ready</th>
            <th className={gridStyles.headerCell}>Node</th>
            <th className={gridStyles.headerCell}>Restarts</th>
            <th className={gridStyles.headerCell}>Revision</th>
            <th className={gridStyles.headerCell}>Age</th>
            <th className={gridStyles.headerCellCenter}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {pods.length === 0 && <GridStateRow colSpan={8} emptyText="No pods" />}
          {pods.map((p) => (
            <tr key={`${p.namespace}/${p.pod_name}`} className={gridStyles.row}>
              <td className={gridStyles.cell}>
                {onOpenPod ? (
                  <button
                    type="button"
                    onClick={() => onOpenPod(p)}
                    className="font-mono text-xs text-blue-600 hover:text-blue-800 hover:underline text-left break-all"
                  >
                    {p.pod_name}
                  </button>
                ) : (
                  <span className="font-mono text-xs break-all">{p.pod_name}</span>
                )}
              </td>
              <td className={gridStyles.cell}><PodStatusBadge status={p.status ?? p.phase} /></td>
              <td className={gridStyles.cell}>{p.ready ? <span className="text-green-700">Yes</span> : <span className="text-amber-700">No</span>}</td>
              <td className={gridStyles.cell}><span className="text-xs">{p.node ?? "—"}</span></td>
              <td className={gridStyles.cell}><span className={p.restarts > 0 ? "text-red-600 font-semibold" : ""}>{p.restarts}</span></td>
              <td className={gridStyles.cell}><span className="font-mono text-xs">{p.revision ?? "—"}</span></td>
              <td className={gridStyles.cell}><span className="font-mono text-xs">{formatAge(p.started_at)}</span></td>
              <td className={gridStyles.centerCell}>
                <div className="flex items-center justify-center gap-1">
                  <button type="button" title="View Logs" onClick={() => onViewPodLogs(p)} className={`${iconBtn} hover:bg-blue-50 text-blue-600`}>{DetailIcons.logs}</button>
                  {canDeletePod && onDeletePod && (
                    <button type="button" title="Delete Pod" onClick={() => onDeletePod(p)} className={`${iconBtn} hover:bg-red-50 text-red-600`}>{DetailIcons.trash}</button>
                  )}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
