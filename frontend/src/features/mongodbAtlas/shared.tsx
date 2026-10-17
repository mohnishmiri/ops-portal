/**
 * Shared building blocks for the MongoDB Atlas page: chips, buttons, icons,
 * the capability gate and small formatters.
 */

import React from "react";
import { useAuth } from "../../contexts/AuthContext";
import { usePermissions } from "../../contexts/PermissionsContext";
import type { AtlasCluster, Environment, OperationStatus, TargetStatus } from "../../services/mongodbAtlasApi";

export const ATLAS_PAGE_SIZE = 10;

export type AtlasCapability = "atlas_cluster_power" | "atlas_schedule_manage" | "atlas_cluster_admin" | "atlas_database_access";

/** Mirrors the API exactly: write role AND the operation's capability. */
export function useAtlasCan() {
  const { canWrite } = useAuth();
  const { hasCapability } = usePermissions();
  return (capability: AtlasCapability) => canWrite && hasCapability(capability);
}

// ── Buttons & inputs ─────────────────────────────────────────────────────────

const buttonBase =
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded-lg border px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 [&>svg]:h-4 [&>svg]:w-4";
export const buttonTone = {
  neutral: `${buttonBase} border-att-200 bg-white text-slate-700 hover:bg-att-50`,
  primary: `${buttonBase} border-att-500 bg-att-500 text-white hover:bg-att-600`,
  stop: `${buttonBase} border-red-200 bg-red-50 text-red-700 hover:bg-red-100`,
  start: `${buttonBase} border-green-200 bg-green-50 text-green-700 hover:bg-green-100`,
  amber: `${buttonBase} border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100`,
};
export const inputClass =
  "w-full rounded-lg border border-att-200 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100 disabled:bg-slate-50";
export const labelClass = "mb-1 block text-xs font-semibold text-slate-600";

// ── Chips ────────────────────────────────────────────────────────────────────

const chip = "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold whitespace-nowrap";

const CLUSTER_STATUS: Record<string, { label: string; cls: string; dot: string }> = {
  running: { label: "Running", cls: "bg-green-50 text-green-700 ring-1 ring-green-200", dot: "bg-green-500" },
  paused: { label: "Paused", cls: "bg-slate-100 text-slate-700 ring-1 ring-slate-200", dot: "bg-slate-400" },
  updating: { label: "Updating", cls: "bg-sky-50 text-sky-700 ring-1 ring-sky-200", dot: "bg-sky-500 animate-pulse" },
  creating: { label: "Creating", cls: "bg-sky-50 text-sky-700 ring-1 ring-sky-200", dot: "bg-sky-500 animate-pulse" },
  repairing: { label: "Repairing", cls: "bg-amber-50 text-amber-800 ring-1 ring-amber-200", dot: "bg-amber-500 animate-pulse" },
  deleting: { label: "Deleting", cls: "bg-red-50 text-red-700 ring-1 ring-red-200", dot: "bg-red-500 animate-pulse" },
};

export const ClusterStatusChip: React.FC<{ cluster: Pick<AtlasCluster, "status" | "paused" | "state" | "operation_in_progress"> }> = ({
  cluster,
}) => {
  const busy = cluster.operation_in_progress;
  if (busy) {
    const label = busy.action === "pause" ? "Stopping…" : "Starting…";
    return (
      <span className={`${chip} bg-sky-50 text-sky-700 ring-1 ring-sky-200`} title={`Atlas state ${cluster.state ?? "—"}`}>
        <span className="h-1.5 w-1.5 rounded-full bg-sky-500 animate-pulse" aria-hidden="true" />
        {label}
      </span>
    );
  }
  // While paused and UPDATING Atlas is resuming or still pausing; show both facts.
  const key = cluster.paused && cluster.state === "IDLE" ? "paused" : cluster.status;
  const style = CLUSTER_STATUS[key] ?? { label: cluster.state ?? key, cls: "bg-slate-100 text-slate-700", dot: "bg-slate-400" };
  return (
    <span className={`${chip} ${style.cls}`} title={`Atlas state ${cluster.state ?? "—"}${cluster.paused ? " · paused" : ""}`}>
      <span className={`h-1.5 w-1.5 rounded-full ${style.dot}`} aria-hidden="true" />
      {style.label}
    </span>
  );
};

const ENV_STYLE: Record<Environment, { label: string; cls: string; title: string }> = {
  production: { label: "Prod", cls: "bg-red-50 text-red-700 ring-1 ring-red-200", title: "Production — stops need the cluster name typed" },
  non_production: { label: "Non-prod", cls: "bg-emerald-50 text-emerald-700 ring-1 ring-emerald-200", title: "Non-production" },
  unclassified: {
    label: "Unclassified",
    cls: "bg-amber-50 text-amber-800 ring-1 ring-amber-200",
    title: "No environment tag or recognisable name — treated as production. Tag the cluster environment=nonprod in Atlas to change this.",
  },
};

export const EnvironmentChip: React.FC<{ environment: Environment }> = ({ environment }) => {
  const style = ENV_STYLE[environment];
  return (
    <span className={`${chip} ${style.cls}`} title={style.title}>
      {style.label}
    </span>
  );
};

const OP_STATUS: Record<OperationStatus, { label: string; cls: string }> = {
  in_progress: { label: "In progress", cls: "bg-sky-50 text-sky-700 ring-1 ring-sky-200" },
  completed: { label: "Completed", cls: "bg-green-50 text-green-700 ring-1 ring-green-200" },
  partial: { label: "Partly failed", cls: "bg-amber-50 text-amber-800 ring-1 ring-amber-200" },
  failed: { label: "Failed", cls: "bg-red-50 text-red-700 ring-1 ring-red-200" },
  skipped: { label: "Skipped", cls: "bg-slate-100 text-slate-600 ring-1 ring-slate-200" },
};

export const OperationStatusChip: React.FC<{ status: OperationStatus }> = ({ status }) => {
  const style = OP_STATUS[status] ?? { label: status, cls: "bg-slate-100 text-slate-700" };
  return <span className={`${chip} ${style.cls}`}>{style.label}</span>;
};

const TARGET_STATUS: Record<TargetStatus, { label: string; cls: string }> = {
  pending: { label: "Not started", cls: "text-slate-500" },
  in_progress: { label: "In progress", cls: "text-sky-700" },
  completed: { label: "Done", cls: "text-green-700" },
  no_change: { label: "Already there", cls: "text-slate-500" },
  skipped: { label: "Skipped", cls: "text-slate-500" },
  failed: { label: "Failed", cls: "text-red-700" },
};

export const TargetStatusText: React.FC<{ status: TargetStatus }> = ({ status }) => {
  const style = TARGET_STATUS[status] ?? { label: status, cls: "text-slate-600" };
  return <span className={`text-xs font-semibold ${style.cls}`}>{style.label}</span>;
};

export const ACTION_LABEL = { pause: "Stop", resume: "Start" } as const;
export const TRIGGER_LABEL = { manual: "Manual", scheduled: "Schedule", run_now: "Schedule · run now" } as const;

// ── Formatters ───────────────────────────────────────────────────────────────

export function formatDuration(seconds: number | null | undefined): string {
  if (seconds == null) return "—";
  const total = Math.max(0, Math.round(seconds));
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  if (h) return `${h}h ${m}m`;
  if (m) return s ? `${m}m ${s}s` : `${m}m`;
  return `${s}s`;
}

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes == null) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let value = bytes;
  let unit = 0;
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024;
    unit += 1;
  }
  return `${value.toFixed(value >= 10 || unit === 0 ? 0 : 1)} ${units[unit]}`;
}

/** "in 3h 20m" / "5m ago" relative to now. */
export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const diff = t - now;
  const abs = Math.abs(diff);
  const mins = Math.round(abs / 60000);
  const text = mins < 60 ? `${mins}m` : mins < 48 * 60 ? `${Math.floor(mins / 60)}h ${mins % 60}m` : `${Math.round(mins / 1440)}d`;
  if (mins === 0) return "now";
  return diff >= 0 ? `in ${text}` : `${text} ago`;
}

export function clusterKey(c: { project_id: string; name?: string; cluster_name?: string }): string {
  return `${c.project_id}/${c.name ?? c.cluster_name}`;
}

// ── Icons (24px stroke, sized by the button) ─────────────────────────────────

const svg = {
  xmlns: "http://www.w3.org/2000/svg",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
  "aria-hidden": true,
};

export const AtlasIcons = {
  stop: () => (
    <svg {...svg}>
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  ),
  start: () => (
    <svg {...svg}>
      <path d="m7 4 13 8-13 8V4Z" />
    </svg>
  ),
  details: () => (
    <svg {...svg}>
      <path d="M3 3v18h18" />
      <path d="m7 15 4-4 3 3 5-6" />
    </svg>
  ),
  refresh: () => (
    <svg {...svg}>
      <path d="M21 12a9 9 0 1 1-2.64-6.36" />
      <path d="M21 3v6h-6" />
    </svg>
  ),
  plus: () => (
    <svg {...svg}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  ),
  edit: () => (
    <svg {...svg}>
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
    </svg>
  ),
  trash: () => (
    <svg {...svg}>
      <path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  ),
  skip: () => (
    <svg {...svg}>
      <path d="m5 4 10 8-10 8V4Z" />
      <path d="M19 5v14" />
    </svg>
  ),
  bolt: () => (
    <svg {...svg}>
      <path d="M13 2 3 14h9l-1 8 10-12h-9l1-8Z" />
    </svg>
  ),
  key: () => (
    <svg {...svg}>
      <circle cx="7.5" cy="15.5" r="5.5" />
      <path d="m21 2-9.6 9.6M15.5 7.5l3 3L22 7l-3-3" />
    </svg>
  ),
  copy: () => (
    <svg {...svg}>
      <rect x="9" y="9" width="13" height="13" rx="2" />
      <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  ),
  clock: () => (
    <svg {...svg}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 3" />
    </svg>
  ),
  warning: () => (
    <svg {...svg}>
      <path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0Z" />
      <path d="M12 9v4M12 17h.01" />
    </svg>
  ),
  download: () => (
    <svg {...svg}>
      <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
      <path d="m7 10 5 5 5-5M12 15V3" />
    </svg>
  ),
};

/** Icon-only grid action, 18px, with a tooltip and an accessible name. */
export const IconAction: React.FC<{
  title: string;
  onClick: () => void;
  tone?: "neutral" | "red" | "green" | "amber" | "att";
  disabled?: boolean;
  children: React.ReactNode;
}> = ({ title, onClick, tone = "neutral", disabled, children }) => {
  const toneClass = {
    neutral: "text-slate-600 hover:bg-slate-100",
    red: "text-red-600 hover:bg-red-50",
    green: "text-green-700 hover:bg-green-50",
    amber: "text-amber-700 hover:bg-amber-50",
    att: "text-att-600 hover:bg-att-50",
  }[tone];
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={title}
      className={`rounded-lg p-1.5 disabled:cursor-not-allowed disabled:opacity-40 [&>svg]:h-[18px] [&>svg]:w-[18px] ${toneClass}`}
    >
      {children}
    </button>
  );
};

export const InfoNote: React.FC<{ tone?: "info" | "warning" | "error"; children: React.ReactNode }> = ({ tone = "info", children }) => {
  const cls = {
    info: "border-att-100 bg-att-50/60 text-att-800",
    warning: "border-amber-200 bg-amber-50 text-amber-900",
    error: "border-red-200 bg-red-50 text-red-700",
  }[tone];
  return (
    <div className={`rounded-lg border px-3 py-2 text-xs leading-relaxed ${cls}`} role={tone === "error" ? "alert" : undefined}>
      {children}
    </div>
  );
};

/** Copies text and briefly says so. */
export const CopyButton: React.FC<{ value: string; label?: string }> = ({ value, label = "Copy" }) => {
  const [copied, setCopied] = React.useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(value);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      }}
      className={buttonTone.neutral}
      title={label}
    >
      <AtlasIcons.copy />
      {copied ? "Copied" : label}
    </button>
  );
};
