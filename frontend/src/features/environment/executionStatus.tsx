/**
 * Shared execution/step status presentation for the Environment Scheduler:
 * the live sequence panel, the History grid and the dashboard all render
 * statuses through these helpers so one state always looks the same.
 */

import React, { useEffect, useState } from "react";
import type { StepDetail } from "../../services/environmentApi";
import { SortableHeader, type SortState } from "../../components/gridStyles";

const spinner = (cls: string) => (
  <svg className={`${cls} animate-spin`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
  </svg>
);

const icon = (path: React.ReactNode) => (cls: string) => (
  <svg className={cls} fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24" aria-hidden="true">
    {path}
  </svg>
);

const ICONS = {
  check: icon(<polyline points="20 6 9 17 4 12" />),
  cross: icon(<path d="M18 6 6 18M6 6l12 12" />),
  undo: icon(<><path d="M3 7v6h6" /><path d="M21 17a9 9 0 0 0-15-6.7L3 13" /></>),
  skip: icon(<><path d="m5 4 10 8-10 8V4z" /><path d="M19 5v14" /></>),
  minus: icon(<path d="M5 12h14" />),
  alert: icon(<><path d="M12 9v4M12 17h.01" /><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z" /></>),
  eye: icon(<><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></>),
  clock: icon(<><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></>),
};

interface StatusMeta {
  label: string;
  className: string;
  icon: (cls: string) => JSX.Element;
}

export const STATUS_META: Record<string, StatusMeta> = {
  completed: { label: "Completed", className: "bg-green-100 text-green-800 ring-green-200", icon: ICONS.check },
  failed: { label: "Failed", className: "bg-red-100 text-red-800 ring-red-200", icon: ICONS.cross },
  running: { label: "Running", className: "bg-blue-100 text-blue-800 ring-blue-200", icon: spinner },
  started: { label: "Started", className: "bg-blue-100 text-blue-800 ring-blue-200", icon: ICONS.clock },
  pending: { label: "Pending", className: "bg-gray-100 text-gray-600 ring-gray-200", icon: ICONS.clock },
  not_run: { label: "Not run", className: "bg-gray-100 text-gray-500 ring-gray-200", icon: ICONS.minus },
  interrupted: { label: "Interrupted", className: "bg-amber-100 text-amber-800 ring-amber-200", icon: ICONS.alert },
  skipped: { label: "Skipped", className: "bg-yellow-100 text-yellow-800 ring-yellow-200", icon: ICONS.skip },
  rolled_back: { label: "Rolled back", className: "bg-orange-100 text-orange-800 ring-orange-200", icon: ICONS.undo },
  rollback_failed: { label: "Rollback failed", className: "bg-red-100 text-red-800 ring-red-200", icon: ICONS.alert },
  dry_run: { label: "Dry run", className: "bg-purple-100 text-purple-800 ring-purple-200", icon: ICONS.eye },
};

export function statusLabel(status: string): string {
  return STATUS_META[status]?.label ?? status.replace(/_/g, " ");
}

export const StatusBadge: React.FC<{ status: string; size?: "sm" | "md" }> = ({ status, size = "sm" }) => {
  const meta = STATUS_META[status] ?? {
    label: statusLabel(status),
    className: "bg-gray-100 text-gray-700 ring-gray-200",
    icon: ICONS.minus,
  };
  const pad = size === "md" ? "px-2.5 py-1 text-xs" : "px-2 py-0.5 text-[11px]";
  return (
    <span className={`inline-flex items-center gap-1 whitespace-nowrap rounded-full font-semibold ring-1 ring-inset ${pad} ${meta.className}`}>
      {meta.icon(size === "md" ? "h-3.5 w-3.5" : "h-3 w-3")}
      {meta.label}
    </span>
  );
};

/**
 * A finished execution can still hold steps saved as "pending"/"running" by
 * older runs or a crashed executor; show what they mean now.
 */
export function effectiveStepStatus(step: StepDetail, executionStatus: string): string {
  if (executionStatus === "running") return step.status;
  if (step.status === "pending") return "not_run";
  if (step.status === "running") return "interrupted";
  return step.status;
}

export function stepCounts(steps: StepDetail[], executionStatus: string) {
  const counts = { completed: 0, failed: 0, running: 0, pending: 0, not_run: 0, other: 0, rolledBack: 0 };
  for (const s of steps) {
    const st = effectiveStepStatus(s, executionStatus);
    if (st === "completed" || st === "dry_run" || st === "skipped") counts.completed += 1;
    else if (st === "failed" || st === "interrupted") counts.failed += 1;
    else if (st === "running") counts.running += 1;
    else if (st === "pending") counts.pending += 1;
    else if (st === "not_run") counts.not_run += 1;
    else counts.other += 1;
    if (s.rollback_status === "rolled_back") counts.rolledBack += 1;
  }
  return counts;
}

export const WAIT_LABELS: Record<string, string> = {
  pods_ready: "Pods ready",
  deployment_available: "Deployment available",
  health_endpoint: "Pods ready",
  fixed_time: "Fixed wait",
  skip: "No wait",
};

export function operationLabel(operation: string): string {
  switch (operation) {
    case "sequence_startup": return "Startup sequence";
    case "sequence_shutdown": return "Shutdown sequence";
    case "scale_up": return "Scale up";
    case "scale_down": return "Scale down";
    default: return operation.replace(/_/g, " ");
  }
}

export function formatDuration(secs: number): string {
  const s = Math.max(0, Math.round(secs));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  if (h > 0) return m > 0 ? `${h}h ${m}m` : `${h}h`;
  if (m > 0) return s % 60 ? `${m}m ${s % 60}s` : `${m}m`;
  return `${s}s`;
}

/** Seconds since an ISO timestamp, ticking every second. */
export function useElapsedSince(startedAt: string | null | undefined, active: boolean): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [active]);
  const start = startedAt ? new Date(startedAt).getTime() : NaN;
  return isNaN(start) ? 0 : Math.max(0, Math.floor((now - start) / 1000));
}

const LiveElapsed: React.FC<{ startedAt: string }> = ({ startedAt }) => {
  const secs = useElapsedSince(startedAt, true);
  return <span className="font-mono font-semibold text-att-600">{formatDuration(secs)}</span>;
};

export const ScaleChange: React.FC<{ from?: number | null; to: number }> = ({ from, to }) => {
  if (from == null) return <span className="font-mono">{to}</span>;
  const tone = to > from ? "text-green-700" : to < from ? "text-red-700" : "text-gray-600";
  return (
    <span className="inline-flex items-center gap-1 font-mono">
      <span className="text-gray-500">{from}</span>
      <svg className="h-3 w-3 text-gray-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M5 12h14M12 5l7 7-7 7" /></svg>
      <span className={`font-semibold ${tone}`}>{to}</span>
    </span>
  );
};

export type StepSortKey = "step" | "deployment" | "change" | "status" | "duration";

interface StepsTableProps {
  steps: StepDetail[];
  executionStatus: string;
  sort?: SortState<StepSortKey>;
  onSort?: (key: StepSortKey) => void;
  onShowLog?: (deployment: string) => void;
  maxHeightClass?: string;
}

/** Per-step table: position, deployment, change, wait, status, duration, details. */
export const ExecutionStepsTable: React.FC<StepsTableProps> = ({
  steps,
  executionStatus,
  sort,
  onSort,
  onShowLog,
  maxHeightClass = "max-h-96",
}) => {
  const header = (label: string, key: StepSortKey, align: "left" | "center" = "left") =>
    sort && onSort ? (
      <SortableHeader label={label} active={sort.key === key} direction={sort.direction} onClick={() => onSort(key)} align={align} />
    ) : (
      label
    );
  const running = executionStatus === "running";

  return (
    <div className={`${maxHeightClass} overflow-y-auto rounded-lg border border-gray-200 bg-white`}>
      <table className="w-full text-xs">
        <thead className="sticky top-0 z-10 bg-gray-50">
          <tr className="text-gray-600">
            <th className="w-12 px-3 py-2 text-left font-semibold">{header("#", "step")}</th>
            <th className="px-3 py-2 text-left font-semibold">{header("Deployment", "deployment")}</th>
            <th className="px-3 py-2 text-center font-semibold">{header("Replicas", "change", "center")}</th>
            <th className="px-3 py-2 text-left font-semibold">Wait</th>
            <th className="px-3 py-2 text-left font-semibold">{header("Status", "status")}</th>
            <th className="px-3 py-2 text-right font-semibold">{header("Duration", "duration")}</th>
            <th className="px-3 py-2 text-left font-semibold">Details</th>
          </tr>
        </thead>
        <tbody>
          {steps.map((d, i) => {
            const status = effectiveStepStatus(d, executionStatus);
            const position = d.step ?? d.order ?? i + 1;
            const rowTone =
              status === "running" ? "bg-blue-50/70" : status === "failed" || status === "interrupted" ? "bg-red-50/60" : "";
            return (
              <tr key={`${position}-${d.deployment}-${i}`} className={`border-t border-gray-100 align-top ${rowTone}`}>
                <td className="px-3 py-2">
                  <span className={`flex h-6 w-6 items-center justify-center rounded-full text-[11px] font-bold ${
                    status === "completed" ? "bg-green-100 text-green-700"
                    : status === "failed" || status === "interrupted" ? "bg-red-100 text-red-700"
                    : status === "running" ? "bg-att-100 text-att-700 ring-2 ring-att-300"
                    : "bg-gray-100 text-gray-500"
                  }`}>{position}</span>
                </td>
                <td className="px-3 py-2 font-mono text-[12px] text-gray-800">
                  {onShowLog && running && (status === "running" || status === "pending") ? (
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); onShowLog(d.deployment); }}
                      className="break-all text-left text-att-600 hover:text-att-800 hover:underline"
                      title="View deployment status"
                    >
                      {d.deployment}
                    </button>
                  ) : (
                    <span className="break-all">{d.deployment}</span>
                  )}
                </td>
                <td className="px-3 py-2 text-center"><ScaleChange from={d.current_replicas} to={d.target_replicas} /></td>
                <td className="px-3 py-2 whitespace-nowrap text-gray-500">
                  {d.wait_condition ? WAIT_LABELS[d.wait_condition] ?? d.wait_condition : "—"}
                  {d.wait_condition && d.wait_condition !== "skip" && d.timeout_seconds != null && (
                    <span className="text-gray-400"> · {d.wait_condition === "fixed_time" ? "" : "≤ "}{formatDuration(d.timeout_seconds)}</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <div className="flex flex-col items-start gap-1">
                    <StatusBadge status={status} />
                    {d.rollback_status && (
                      <span title={d.rollback_error || (d.rolled_back_to != null ? `Restored to ${d.rolled_back_to} replica(s)` : undefined)}>
                        <StatusBadge status={d.rollback_status} />
                      </span>
                    )}
                  </div>
                </td>
                <td className="px-3 py-2 text-right whitespace-nowrap text-gray-600">
                  {d.duration_seconds != null
                    ? formatDuration(d.duration_seconds)
                    : status === "running" && d.started_at
                      ? <LiveElapsed startedAt={d.started_at} />
                      : "—"}
                </td>
                <td className="px-3 py-2 text-[11px]">
                  {d.error && <p className="break-words text-red-700">{d.error}</p>}
                  {d.rollback_status === "rolled_back" && d.rolled_back_to != null && (
                    <p className="text-orange-700">Restored to {d.rolled_back_to} replica{d.rolled_back_to === 1 ? "" : "s"}</p>
                  )}
                  {d.rollback_error && <p className="break-words text-red-700">Rollback: {d.rollback_error}</p>}
                  {status === "not_run" && <p className="text-gray-400">Not run: the sequence stopped before this step</p>}
                  {status === "interrupted" && <p className="text-amber-700">Run stopped while this step was in progress</p>}
                </td>
              </tr>
            );
          })}
          {steps.length === 0 && (
            <tr><td colSpan={7} className="px-3 py-6 text-center text-gray-400">No matching steps</td></tr>
          )}
        </tbody>
      </table>
    </div>
  );
};

/** Best message from an API error (FastAPI `detail`), else the fallback. */
export function apiErrorMessage(err: unknown, fallback: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string; loc?: unknown[] };
    if (first?.msg) return `${fallback}: ${first.msg}`;
  }
  const message = (err as { message?: string })?.message;
  return message ? `${fallback}: ${message}` : fallback;
}
