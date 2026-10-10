/**
 * Small pieces shared by the Infrastructure Alerts grids, detail views and
 * configuration editors: badges, the expiry-window maths, metric bars, and
 * the per-type wording for expiry configurations.
 */

import React from "react";
import type { AlertSeverity, ExpiryAlertType } from "../../services/infraAlertApi";

const svg = {
  width: 20,
  height: 20,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export const InfraIcons = {
  server: <svg {...svg}><rect x="2" y="2" width="20" height="8" rx="2" /><rect x="2" y="14" width="20" height="8" rx="2" /><line x1="6" y1="6" x2="6.01" y2="6" /><line x1="6" y1="18" x2="6.01" y2="18" /></svg>,
  database: <svg {...svg}><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" /><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" /></svg>,
  clock: <svg {...svg}><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>,
  storage: <svg {...svg}><path d="M22 12H2" /><path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z" /><line x1="6" y1="16" x2="6.01" y2="16" /><line x1="10" y1="16" x2="10.01" y2="16" /></svg>,
  disk: <svg {...svg}><circle cx="12" cy="12" r="10" /><circle cx="12" cy="12" r="3" /></svg>,
  calendar: <svg {...svg}><rect x="3" y="4" width="18" height="18" rx="2" /><line x1="16" y1="2" x2="16" y2="6" /><line x1="8" y1="2" x2="8" y2="6" /><line x1="3" y1="10" x2="21" y2="10" /></svg>,
  mail: <svg {...svg}><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" /><polyline points="22,6 12,13 2,6" /></svg>,
  alert: <svg {...svg}><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>,
  schedule: <svg {...svg}><polygon points="5 3 19 12 5 21 5 3" /></svg>,
  check: <svg {...svg}><polyline points="20 6 9 17 4 12" /></svg>,
  checkCircle: <svg {...svg}><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg>,
  eye: <svg {...svg}><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></svg>,
  edit: <svg {...svg}><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg>,
  trash: <svg {...svg}><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>,
  bellOff: <svg {...svg}><path d="M13.73 21a2 2 0 0 1-3.46 0" /><path d="M18.63 13A17.89 17.89 0 0 1 18 8" /><path d="M6.26 6.26A5.86 5.86 0 0 0 6 8c0 7-3 9-3 9h14" /><path d="M18 8a6 6 0 0 0-9.33-5" /><line x1="1" y1="1" x2="23" y2="23" /></svg>,
  power: <svg {...svg}><path d="M18.36 6.64a9 9 0 1 1-12.73 0" /><line x1="12" y1="2" x2="12" y2="12" /></svg>,
  play: <svg {...svg}><polygon points="5 3 19 12 5 21 5 3" /></svg>,
  stop: <svg {...svg}><rect x="6" y="6" width="12" height="12" rx="1" /></svg>,
  restart: <svg {...svg}><path d="M21 2v6h-6" /><path d="M3 12a9 9 0 0 1 15.55-6.36L21 8" /><path d="M3 22v-6h6" /><path d="M21 12a9 9 0 0 1-15.55 6.36L3 16" /></svg>,
  plus: <svg {...svg}><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></svg>,
  key: <svg {...svg}><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" /></svg>,
  user: <svg {...svg}><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" /><circle cx="12" cy="7" r="4" /></svg>,
  shield: <svg {...svg}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" /></svg>,
  globe: <svg {...svg}><circle cx="12" cy="12" r="10" /><line x1="2" y1="12" x2="22" y2="12" /><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" /></svg>,
};

// ── Badges ────────────────────────────────────────────────────────────

const pill = "inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-semibold";

export function SeverityBadge({ severity }: { severity: AlertSeverity | string | null | undefined }) {
  const style = severity === "critical" ? "bg-red-100 text-red-700 ring-1 ring-red-200" : "bg-amber-100 text-amber-800 ring-1 ring-amber-200";
  return <span className={`${pill} ${style}`}>{severity === "critical" ? "Critical" : severity === "warning" ? "Warning" : severity || "—"}</span>;
}

export function AlertStatusBadge({ status }: { status: string | null | undefined }) {
  const styles: Record<string, string> = {
    active: "bg-red-50 text-red-700 ring-1 ring-red-200",
    acknowledged: "bg-blue-50 text-blue-700 ring-1 ring-blue-200",
    resolved: "bg-green-50 text-green-700 ring-1 ring-green-200",
  };
  const label = status ? status.charAt(0).toUpperCase() + status.slice(1) : "—";
  return <span className={`${pill} ${styles[status || ""] || "bg-slate-100 text-slate-700"}`}>{label}</span>;
}

/** Enabled / Disabled / Snoozed for a configuration. */
export function ConfigStateBadge({ enabled, snoozeUntil }: { enabled: boolean; snoozeUntil?: string | null }) {
  if (!enabled) return <span className={`${pill} bg-slate-100 text-slate-600 ring-1 ring-slate-200`}>Disabled</span>;
  if (isSnoozed(snoozeUntil)) return <span className={`${pill} bg-violet-50 text-violet-700 ring-1 ring-violet-200`}>Snoozed</span>;
  return <span className={`${pill} bg-green-50 text-green-700 ring-1 ring-green-200`}>Enabled</span>;
}

export function isSnoozed(snoozeUntil?: string | null): boolean {
  if (!snoozeUntil) return false;
  const until = new Date(/[zZ]|[+-]\d\d:\d\d$/.test(snoozeUntil) ? snoozeUntil : `${snoozeUntil}Z`);
  return !Number.isNaN(until.getTime()) && until.getTime() > Date.now();
}

export function PowerStateBadge({ state }: { state: string | null | undefined }) {
  const value = (state || "").toLowerCase();
  const style =
    value === "running" || value === "ready"
      ? "bg-green-50 text-green-700 ring-1 ring-green-200"
      : value === "deallocated" || value === "stopped"
        ? "bg-red-50 text-red-700 ring-1 ring-red-200"
        : value.endsWith("ing")
          ? "bg-amber-50 text-amber-800 ring-1 ring-amber-200"
          : "bg-slate-100 text-slate-700";
  return <span className={`${pill} ${style}`}>{state || "Unknown"}</span>;
}

// ── Expiry window ─────────────────────────────────────────────────────

export type ExpiryHealth = "ok" | "warning" | "critical" | "expired";

/** Calendar days from today to a YYYY-MM-DD(...) date, in the browser's calendar. */
export function daysUntil(dateValue: string | null | undefined, today = new Date()): number | null {
  const match = dateValue?.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return null;
  const target = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  const base = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((target - base) / 86_400_000);
}

export function expiryHealth(days: number | null | undefined, warningDays: number, criticalDays: number): ExpiryHealth {
  if (days == null) return "ok";
  if (days < 0) return "expired";
  if (days <= criticalDays) return "critical";
  if (days <= warningDays) return "warning";
  return "ok";
}

export function daysLeftText(days: number | null | undefined): string {
  if (days == null) return "—";
  if (days < 0) return `Expired ${Math.abs(days)} day${Math.abs(days) === 1 ? "" : "s"} ago`;
  if (days === 0) return "Expires today";
  return `${days} day${days === 1 ? "" : "s"} left`;
}

export function ExpiryHealthBadge({ health }: { health: ExpiryHealth }) {
  const styles: Record<ExpiryHealth, [string, string]> = {
    ok: ["Healthy", "bg-green-50 text-green-700 ring-1 ring-green-200"],
    warning: ["Warning window", "bg-amber-50 text-amber-800 ring-1 ring-amber-200"],
    critical: ["Critical window", "bg-red-50 text-red-700 ring-1 ring-red-200"],
    expired: ["Expired", "bg-red-600 text-white"],
  };
  const [label, style] = styles[health];
  return <span className={`${pill} ${style}`}>{label}</span>;
}

/** Text colour for a days-left figure. */
export function daysLeftTone(days: number | null | undefined, warningDays = 30, criticalDays = 7): string {
  const health = expiryHealth(days, warningDays, criticalDays);
  return health === "expired" || health === "critical" ? "font-semibold text-red-600" : health === "warning" ? "font-semibold text-amber-700" : "text-slate-700";
}

export function addDays(dateValue: string, days: number): string {
  const match = dateValue.match(/^(\d{4})-(\d{2})-(\d{2})/);
  const base = match ? new Date(Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]))) : new Date();
  base.setUTCDate(base.getUTCDate() + days);
  return base.toISOString().slice(0, 10);
}

export function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
}

export function formatCalendar(dateValue: string | null | undefined): string {
  const match = dateValue?.match(/^(\d{4})-(\d{2})-(\d{2})/);
  if (!match) return dateValue || "—";
  return new Intl.DateTimeFormat(undefined, { year: "numeric", month: "short", day: "numeric" }).format(
    new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])),
  );
}

/**
 * Timeline of an expiry config: when the warning and critical windows open,
 * the expiry date, and where today sits.
 */
export function ExpiryWindowBar({
  expiryDate,
  warningDays,
  criticalDays,
}: {
  expiryDate: string;
  warningDays: number;
  criticalDays: number;
}) {
  const days = daysUntil(expiryDate);
  if (days == null) return null;
  const span = Math.max(warningDays * 1.25, warningDays + 5, days + 5, 10);
  // Position along the bar: 0 = `span` days before expiry, 100% = expiry day.
  const at = (daysBeforeExpiry: number) => `${Math.min(100, Math.max(0, ((span - daysBeforeExpiry) / span) * 100))}%`;
  const todayPosition = days < 0 ? "100%" : at(days);
  return (
    <div>
      <div className="relative mt-6 h-3 rounded-full bg-gradient-to-r from-green-200 via-green-200 to-green-200">
        <div className="absolute inset-y-0 rounded-r-full bg-amber-200" style={{ left: at(warningDays), right: 0 }} />
        <div className="absolute inset-y-0 rounded-r-full bg-red-300" style={{ left: at(criticalDays), right: 0 }} />
        <div className="absolute -top-6 -translate-x-1/2 text-center" style={{ left: todayPosition }}>
          <span className="rounded bg-slate-900 px-1.5 py-0.5 text-[10px] font-semibold text-white">Today</span>
        </div>
        <div className="absolute -top-1 h-5 w-0.5 -translate-x-1/2 bg-slate-900" style={{ left: todayPosition }} />
      </div>
      <div className="mt-2 grid grid-cols-3 gap-2 text-[11px] text-slate-600">
        <div>
          <p className="font-semibold text-amber-700">Warning from</p>
          <p>{formatCalendar(addDays(expiryDate, -warningDays))}</p>
        </div>
        <div className="text-center">
          <p className="font-semibold text-red-700">Critical from</p>
          <p>{formatCalendar(addDays(expiryDate, -criticalDays))}</p>
        </div>
        <div className="text-right">
          <p className="font-semibold text-slate-800">Expires</p>
          <p>{formatCalendar(expiryDate)}</p>
        </div>
      </div>
    </div>
  );
}

// ── Metric thresholds ─────────────────────────────────────────────────

/** A 0–max bar with warning and critical zones, and the current value when known. */
export function ThresholdBar({
  value,
  warning,
  critical,
  max = 100,
  unit = "%",
}: {
  value?: number | null;
  warning: number;
  critical: number;
  max?: number;
  unit?: string;
}) {
  const top = Math.max(max, critical * 1.1, value ?? 0);
  const pos = (v: number) => `${Math.min(100, Math.max(0, (v / top) * 100))}%`;
  const valueTone = value == null ? "" : value >= critical ? "bg-red-600" : value >= warning ? "bg-amber-500" : "bg-green-600";
  return (
    <div>
      <div className="relative h-2.5 rounded-full bg-green-100">
        <div className="absolute inset-y-0 bg-amber-200" style={{ left: pos(warning), right: 0 }} />
        <div className="absolute inset-y-0 rounded-r-full bg-red-300" style={{ left: pos(critical), right: 0 }} />
        {value != null && (
          <div
            className={`absolute -top-1 w-1.5 -translate-x-1/2 rounded ${valueTone}`}
            style={{ left: pos(value), height: "1.125rem" }}
            title={`Current ${value}${unit}`}
          />
        )}
      </div>
      <div className="mt-1 flex justify-between text-[11px] text-slate-500">
        <span>0{unit}</span>
        <span className="text-amber-700">warn {warning}{unit}</span>
        <span className="text-red-700">crit {critical}{unit}</span>
        {max === 100 && unit === "%" && <span>100%</span>}
      </div>
    </div>
  );
}

// ── Expiry configuration types ────────────────────────────────────────

export interface ExpiryTypeMeta {
  label: string;
  short: string;
  description: string;
  nameLabel: string;
  namePlaceholder: string;
  identifierLabel: string;
  identifierPlaceholder: string;
  identifierHelp: string;
  /** For account types the identifier usually equals the name. */
  identifierMirrorsName: boolean;
  defaultWarning: number;
  defaultCritical: number;
}

export const EXPIRY_TYPE_META: Record<ExpiryAlertType, ExpiryTypeMeta> = {
  itservices_domain: {
    label: "ITServices Domain Account",
    short: "ITServices",
    description: "Password or account expiry of an account in the ITServices AD domain.",
    nameLabel: "Account name",
    namePlaceholder: "m52142",
    identifierLabel: "Domain account",
    identifierPlaceholder: "ITSERVICES\\m52142",
    identifierHelp: "Unique per type — usually DOMAIN\\account or the sAMAccountName.",
    identifierMirrorsName: true,
    defaultWarning: 30,
    defaultCritical: 7,
  },
  mech_id: {
    label: "MechID",
    short: "MechID",
    description: "Mechanized (service) ID whose password or access expires.",
    nameLabel: "MechID",
    namePlaceholder: "m12345",
    identifierLabel: "MechID identifier",
    identifierPlaceholder: "m12345",
    identifierHelp: "Usually the MechID itself.",
    identifierMirrorsName: true,
    defaultWarning: 30,
    defaultCritical: 7,
  },
  certificate: {
    label: "Certificate",
    short: "Certificate",
    description: "TLS / signing certificate tracked outside the Certificates module.",
    nameLabel: "Certificate name",
    namePlaceholder: "api-gateway-tls",
    identifierLabel: "Common name, thumbprint or Key Vault ID",
    identifierPlaceholder: "CN=api.example.att.com",
    identifierHelp: "Anything that uniquely identifies the certificate.",
    identifierMirrorsName: false,
    defaultWarning: 45,
    defaultCritical: 14,
  },
  aaf_account: {
    label: "AAF Account",
    short: "AAF",
    description: "AAF identity or credential with an expiry date.",
    nameLabel: "AAF identity",
    namePlaceholder: "m12345@app.att.com",
    identifierLabel: "AAF credential / namespace",
    identifierPlaceholder: "com.att.app.m12345",
    identifierHelp: "The AAF ID or namespace the credential belongs to.",
    identifierMirrorsName: true,
    defaultWarning: 30,
    defaultCritical: 7,
  },
  database_account: {
    label: "Database Account",
    short: "Database",
    description: "Database login whose password rotates or expires.",
    nameLabel: "Database user",
    namePlaceholder: "app_user",
    identifierLabel: "Server / database / user",
    identifierPlaceholder: "attcc-prod-psql/appdb/app_user",
    identifierHelp: "Include the server so the same user on two servers stays distinct.",
    identifierMirrorsName: false,
    defaultWarning: 30,
    defaultCritical: 7,
  },
};

export const EXPIRY_TYPE_ORDER: ExpiryAlertType[] = ["itservices_domain", "mech_id", "aaf_account", "database_account", "certificate"];

// ── Misc ──────────────────────────────────────────────────────────────

export function humanize(key: string): string {
  return key
    .replace(/^_+/, "")
    .replace(/_/g, " ")
    .replace(/\b(id|sku|os|ha|fqdn|gb|ip|vm|pg)\b/gi, (m) => m.toUpperCase())
    .replace(/^\w/, (c) => c.toUpperCase());
}

/** "every 15 min" / "cron 0 8 * * *" with a plain-English hint for common crons. */
export function describeSchedule(type: string, intervalMinutes: number, cron: string | null | undefined): string {
  if (type !== "cron") {
    if (intervalMinutes % 1440 === 0) return `Every ${intervalMinutes / 1440} day${intervalMinutes === 1440 ? "" : "s"}`;
    if (intervalMinutes % 60 === 0) return `Every ${intervalMinutes / 60} hour${intervalMinutes === 60 ? "" : "s"}`;
    return `Every ${intervalMinutes} min`;
  }
  const expression = (cron || "").trim();
  const daily = expression.match(/^(\d{1,2}) (\d{1,2}) \* \* \*$/);
  if (daily) return `Daily at ${daily[2].padStart(2, "0")}:${daily[1].padStart(2, "0")} UTC`;
  const weekdays = expression.match(/^(\d{1,2}) (\d{1,2}) \* \* 1-5$/);
  if (weekdays) return `Weekdays at ${weekdays[2].padStart(2, "0")}:${weekdays[1].padStart(2, "0")} UTC`;
  const hourly = expression.match(/^(\d{1,2}) \* \* \* \*$/);
  if (hourly) return `Hourly at :${hourly[1].padStart(2, "0")}`;
  return `Cron ${expression || "—"} (UTC)`;
}

/** Row props that make a table row open its detail view by mouse or keyboard. */
export function clickableRow(onOpen: () => void, label: string) {
  return {
    onClick: onOpen,
    onKeyDown: (event: React.KeyboardEvent) => {
      if (event.target !== event.currentTarget) return;
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        onOpen();
      }
    },
    tabIndex: 0,
    "aria-description": label,
    className: "cursor-pointer focus:outline-none focus-visible:bg-att-50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-att-300",
  };
}

/** Wrap a grid action so clicking it does not also open the row's detail view. */
export function stop<E extends React.SyntheticEvent>(handler: () => void) {
  return (event: E) => {
    event.stopPropagation();
    handler();
  };
}
