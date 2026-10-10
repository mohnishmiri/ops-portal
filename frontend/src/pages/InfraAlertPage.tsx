/**
 * Infrastructure Alert Page — VM Threshold & Custom Expiry Alerts.
 * 
 * Module 4: Infrastructure Alert System
 * - VM CPU/Memory/Disk threshold monitoring
 * - Custom expiry alerts (MechID, Certificate, AAF, Database, ITServices Domain)
 * - Alert configuration and management
 * - Dashboard with active alert summary
 * - Azure resource inventory
 * - Scheduler management and notification history
 */

import React, { useState, useMemo, useCallback, useEffect } from "react";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import { usePermissions } from "../contexts/PermissionsContext";
import { useSubscriptionScope } from "../contexts/SubscriptionContext";
import Toast, { type ToastState } from "../components/Toast";
import { AutoRefreshIndicator, gridStyles, type SortState, nextSortState, SortableHeader } from "../components/gridStyles";
import { MetricCard } from "../components/MetricCard";
import {
  AlertScheduleConfig,
  CreateAlertScheduleConfigRequest,
  UpdateAlertScheduleConfigRequest,
  apiErrorMessage,
  formatRelativeTime,
  getAlertTypeLabel,
  getEnvLabel,
  getNotificationTypeLabel,
  useAcknowledgeExpiryAlert,
  useAcknowledgePGFlexAlert,
  useAcknowledgeVMAlert,
  useAlertScheduleConfigs,
  useAlertSummary,
  useAzureDisks,
  useAzurePGServers,
  useAzureStorageAccounts,
  useAzureVMs,
  useCheckExpiryAlerts,
  useCheckPGAlerts,
  useCreateAlertScheduleConfig,
  useDeleteVMThresholdConfig,
  useDeleteAlertScheduleConfig,
  useDeleteExpiryConfig,
  useDeleteStorageAlertConfig,
  useDeletePGFlexConfig,
  useExpiryAlerts,
  useExpiryConfigs,
  useNotificationHistory,
  usePGFlexAlerts,
  usePGFlexConfigs,
  useResolveExpiryAlert,
  useResolvePGFlexAlert,
  useResolveVMAlert,
  useResourceInventorySummary,
  useRestartPGServer,
  useRestartVM,
  useSchedulerStatus,
  useSendTestNotification,
  useStartPGServer,
  useStartScheduler,
  useStartVM,
  useStopPGServer,
  useStopScheduler,
  useStopVM,
  useStorageAlertConfigs,
  useSyncResources,
  useTriggerExpiryCheck,
  useTriggerPGCheck,
  useTriggerResourceSync,
  useTriggerVMCheck,
  useUpdateAlertScheduleConfig,
  useVMThresholdAlerts,
  useVMThresholdConfigs,
} from "../services/infraAlertApi";
import { useDeleteUnattachedDisk } from "../services/costApi";
import {
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  Tooltip,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Legend,
} from "recharts";
import { usePortalTimezone } from "../contexts/TimezoneContext";
import { useAdminSubscriptions } from "../services/costApi";
import { ConfigEditor, type ConfigEditorTarget } from "../features/infraAlerts/ConfigEditors";
import { UtilizationBar } from "../features/infraAlerts/ResourceAdmin";
import { useResourceUtilization } from "../services/infraResourceAdminApi";
import {
  InfraAlertDetailHost,
  type InfraDetailTarget,
  type PowerAction,
  type PowerKind,
  type PowerTarget,
} from "../features/infraAlerts/DetailViews";
import {
  AlertStatusBadge as StatusBadge,
  clickableRow,
  ConfigStateBadge,
  daysLeftText,
  daysLeftTone,
  describeSchedule,
  ExpiryHealthBadge,
  expiryHealth,
  SeverityBadge,
} from "../features/infraAlerts/shared";

// ── SVG Icons ─────────────────────────────────────────────────────────

const Icons = {
  alert: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  ),
  server: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
      <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
      <line x1="6" y1="6" x2="6.01" y2="6" /><line x1="6" y1="18" x2="6.01" y2="18" />
    </svg>
  ),
  clock: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" />
    </svg>
  ),
  check: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <polyline points="20 6 9 17 4 12" />
    </svg>
  ),
  settings: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z" />
    </svg>
  ),
  plus: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  ),
  trash: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  ),
  refresh: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <polyline points="23 4 23 10 17 10" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
    </svg>
  ),
  eye: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" />
    </svg>
  ),
  database: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <ellipse cx="12" cy="5" rx="9" ry="3" />
      <path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" />
      <path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" />
    </svg>
  ),
  play: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <polygon points="5 3 19 12 5 21 5 3" />
    </svg>
  ),
  stop: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <rect x="6" y="6" width="12" height="12" rx="1" />
    </svg>
  ),
  restart: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M21 2v6h-6" />
      <path d="M3 12a9 9 0 0 1 15.55-6.36L21 8" />
      <path d="M3 22v-6h6" />
      <path d="M21 12a9 9 0 0 1-15.55 6.36L3 16" />
    </svg>
  ),
  mail: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
      <polyline points="22,6 12,13 2,6" />
    </svg>
  ),
  edit: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
    </svg>
  ),
};

// ── Tab Types ─────────────────────────────────────────────────────────

type TabKey = "dashboard" | "vm-thresholds" | "pg-thresholds" | "expiry-alerts" | "resources" | "configs" | "scheduler";
const TAB_KEYS: TabKey[] = ["dashboard", "vm-thresholds", "pg-thresholds", "expiry-alerts", "resources", "configs", "scheduler"];

const defaultAlertScheduleFormData: CreateAlertScheduleConfigRequest = {
  name: "",
  description: "",
  schedule_type: "interval",
  interval_minutes: 15,
  cron_expression: "",
  check_vm_thresholds: true,
  // Not evaluated by the scheduler yet — offered disabled in the editor.
  check_storage_thresholds: false,
  check_disk_thresholds: false,
  check_expiry_alerts: true,
  check_pg_thresholds: true,
  send_daily_digest: false,
  digest_time_utc: "08:00",
  digest_recipients: [],
  is_enabled: true,
};

// ── Color Constants ───────────────────────────────────────────────────

const COLORS = {
  critical: "#ef4444",
  warning: "#f59e0b",
  active: "#ef4444",
  acknowledged: "#3b82f6",
  resolved: "#10b981",
};

// Keyed by slice name: zero-value slices are filtered out, so colouring by
// index painted "Acknowledged" red whenever nothing was active.
const PIE_COLORS: Record<string, string> = {
  Active: COLORS.active,
  Acknowledged: COLORS.acknowledged,
  Resolved: COLORS.resolved,
};

const CHART_COLORS = ["#3b82f6", "#10b981", "#f59e0b", "#8b5cf6", "#ef4444", "#06b6d4", "#ec4899", "#14b8a6", "#f97316", "#6366f1"];

const buttonStyles = {
  primary:
    "inline-flex items-center gap-2 rounded-lg bg-att-600 px-4 py-2 text-sm font-semibold text-white transition hover:bg-att-700 disabled:cursor-not-allowed disabled:opacity-50",
  subtle:
    "inline-flex items-center gap-2 rounded-lg border border-att-200 bg-white px-4 py-2 text-sm font-medium text-gray-700 transition hover:border-att-300 hover:bg-att-50 disabled:cursor-not-allowed disabled:opacity-50",
  blueSoft:
    "inline-flex items-center gap-2 rounded-lg border border-att-200 bg-att-50 px-4 py-2 text-sm font-medium text-att-700 transition hover:bg-att-100 disabled:cursor-not-allowed disabled:opacity-50",
  greenSoft:
    "inline-flex items-center gap-2 rounded-lg border border-green-200 bg-green-50 px-4 py-2 text-sm font-medium text-green-700 transition hover:bg-green-100 disabled:cursor-not-allowed disabled:opacity-50",
  redSoft:
    "inline-flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm font-medium text-red-700 transition hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-50",
  orangeSoft:
    "inline-flex items-center gap-2 rounded-lg border border-orange-200 bg-orange-50 px-4 py-2 text-sm font-medium text-orange-700 transition hover:bg-orange-100 disabled:cursor-not-allowed disabled:opacity-50",
  purpleSoft:
    "inline-flex items-center gap-2 rounded-lg border border-purple-200 bg-purple-50 px-4 py-2 text-sm font-medium text-purple-700 transition hover:bg-purple-100 disabled:cursor-not-allowed disabled:opacity-50",
};

const actionButtonTones = {
  blue: "text-att-700 hover:bg-att-50",
  green: "text-green-700 hover:bg-green-50",
  red: "text-red-700 hover:bg-red-50",
  purple: "text-purple-700 hover:bg-purple-50",
  orange: "text-orange-700 hover:bg-orange-50",
};

// ── Helper Components ─────────────────────────────────────────────────

const StatCard: React.FC<{
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ReactNode;
  color?: string;
}> = ({ title, value, subtitle, icon, color = "blue" }) => (
  <MetricCard
    title={title}
    value={value}
    subtitle={subtitle}
    icon={icon}
    tone={
      color === "red"
        ? "red"
        : color === "green"
          ? "green"
          : color === "orange"
            ? "orange"
            : color === "purple"
              ? "purple"
              : color === "indigo"
                ? "indigo"
                : color === "gray"
                  ? "slate"
                  : "blue"
    }
  />
);

const GridActionButton: React.FC<{
  title: string;
  tone: keyof typeof actionButtonTones;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}> = ({ title, tone, onClick, disabled = false, children }) => (
  <button
    type="button"
    // Grid rows open their detail view on click; an action must not do that too.
    onClick={(event) => {
      event.stopPropagation();
      onClick();
    }}
    onKeyDown={(event) => event.stopPropagation()}
    disabled={disabled}
    title={title}
    aria-label={title}
    className={`rounded-lg p-2 transition disabled:opacity-40 ${actionButtonTones[tone]}`}
  >
    {children}
  </button>
);

const ActionTileButton: React.FC<{
  title: string;
  tone: keyof typeof actionButtonTones;
  icon: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
}> = ({ title, tone, icon, onClick, disabled = false }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    title={title}
    className={`flex min-h-[88px] flex-col items-center justify-center gap-2 rounded-xl border px-4 py-4 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-50 ${
      tone === "green"
        ? "border-green-200 bg-green-50 text-green-700 hover:bg-green-100"
        : tone === "red"
          ? "border-red-200 bg-red-50 text-red-700 hover:bg-red-100"
          : tone === "orange"
            ? "border-orange-200 bg-orange-50 text-orange-700 hover:bg-orange-100"
            : tone === "purple"
              ? "border-purple-200 bg-purple-50 text-purple-700 hover:bg-purple-100"
              : "border-att-200 bg-att-50 text-att-700 hover:bg-att-100"
    }`}
  >
    <span className="flex h-10 w-10 items-center justify-center rounded-full bg-white/80 ring-1 ring-current/10">
      {icon}
    </span>
    <span className="text-center leading-tight">{title}</span>
  </button>
);

// ── Pagination & Search Helpers ───────────────────────────────────────

const PAGE_SIZE = 10;

/** Generic search + paginate over an array. */
function filterAndPaginate<T>(
  data: T[],
  search: string,
  page: number,
  fields: (item: T) => (string | number | null | undefined)[],
  sort?: SortState<string>,
  sortAccessors?: Record<string, (item: T) => string | number | boolean | null | undefined>,
) {
  const lower = search.toLowerCase().trim();
  const filtered = lower
    ? data.filter((item) =>
        fields(item).some((f) => f != null && String(f).toLowerCase().includes(lower)),
      )
    : data;
  const sorted = sort && sortAccessors?.[sort.key]
    ? [...filtered].sort((left, right) => {
        const accessor = sortAccessors[sort.key];
        const a = accessor(left);
        const b = accessor(right);
        const dir = sort.direction === "asc" ? 1 : -1;

        if (a == null && b == null) return 0;
        if (a == null) return 1;
        if (b == null) return -1;

        const av = typeof a === "boolean" ? Number(a) : a;
        const bv = typeof b === "boolean" ? Number(b) : b;

        if (av < bv) return -dir;
        if (av > bv) return dir;
        return 0;
      })
    : filtered;
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  return {
    items: sorted.slice((safePage - 1) * PAGE_SIZE, safePage * PAGE_SIZE),
    total: filtered.length,
    page: safePage,
  };
}

function toDateInputValue(value: string | null | undefined): string {
  if (!value) return "";

  const match = value.match(/^\d{4}-\d{2}-\d{2}/);
  if (match) return match[0];

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "";

  return parsed.toISOString().slice(0, 10);
}

function formatDateOnly(value: string | null | undefined): string {
  const normalized = toDateInputValue(value);
  if (!normalized) return value || "-";

  const [year, month, day] = normalized.split("-").map(Number);
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "numeric",
    day: "numeric",
  }).format(new Date(year, month - 1, day));
}

function parseEmailList(value: string): string[] {
  return value
    .split(/[\n,;]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

/** "Expiry check: 1 raised, 2 resolved" from a check endpoint's summary. */
function checkSummary(label: string, result: Record<string, unknown> | undefined): string {
  const data = ((result?.result as Record<string, unknown>) ?? result ?? {}) as Record<string, unknown>;
  const parts = [
    ["created", "raised"],
    ["escalated", "escalated"],
    ["resolved", "resolved"],
  ]
    .map(([key, word]) => (Number(data[key]) ? `${data[key]} ${word}` : null))
    .filter(Boolean);
  const errors = Array.isArray(data.errors) ? data.errors.length : 0;
  return `${label} check finished: ${parts.length ? parts.join(", ") : "no changes"}${errors ? ` · ${errors} resource(s) could not be read` : ""}`;
}

function totalFromStatusMap(counts: Record<string, number> | undefined): number {
  return Object.values(counts || {}).reduce((total, count) => total + count, 0);
}

const SearchBar: React.FC<{
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}> = ({ value, onChange, placeholder = "Search..." }) => (
  <div className="flex items-center gap-3">
    <AutoRefreshIndicator />
    <div className="relative w-72 max-w-full">
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
        width={16}
        height={16}
        className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400"
      >
        <circle cx="11" cy="11" r="8" />
        <line x1="21" y1="21" x2="16.65" y2="16.65" />
      </svg>
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className={`${gridStyles.toolbarInput} w-full pl-10`}
      />
    </div>
  </div>
);

const TablePagination: React.FC<{
  currentPage: number;
  totalItems: number;
  onPageChange: (page: number) => void;
}> = ({ currentPage, totalItems, onPageChange }) => {
  const totalPages = Math.max(1, Math.ceil(totalItems / PAGE_SIZE));
  const startItem = totalItems === 0 ? 0 : (currentPage - 1) * PAGE_SIZE + 1;
  const endItem = Math.min(currentPage * PAGE_SIZE, totalItems);

  if (totalItems === 0) return null;

  // Build page numbers with ellipsis
  const pages: (number | "...")[] = [];
  for (let p = 1; p <= totalPages; p++) {
    if (p === 1 || p === totalPages || Math.abs(p - currentPage) <= 1) {
      pages.push(p);
    } else if (pages[pages.length - 1] !== "...") {
      pages.push("...");
    }
  }

  return (
    <div className={gridStyles.pager}>
      <span className="text-sm text-gray-600">
        Showing {startItem}–{endItem} of {totalItems}
      </span>
      <div className="flex items-center gap-1">
        <button
          onClick={() => onPageChange(1)}
          disabled={currentPage <= 1}
          className={`${gridStyles.pagerButton} px-2 py-1 text-xs`}
        >
          «
        </button>
        <button
          onClick={() => onPageChange(currentPage - 1)}
          disabled={currentPage <= 1}
          className={gridStyles.pagerButton}
        >
          Prev
        </button>
        {pages.map((p, i) =>
          p === "..." ? (
            <span key={`e${i}`} className="px-1 text-gray-400 text-sm">
              …
            </span>
          ) : (
            <button
              key={p}
              onClick={() => onPageChange(p)}
              className={`min-w-[2.25rem] font-semibold ${
                currentPage === p
                  ? "rounded-lg border border-att-500 bg-att-500 px-3 py-1.5 text-white shadow-sm hover:bg-att-600"
                  : `${gridStyles.pagerButton} text-gray-700`
              }`}
            >
              {p}
            </button>
          ),
        )}
        <button
          onClick={() => onPageChange(currentPage + 1)}
          disabled={currentPage >= totalPages}
          className={gridStyles.pagerButton}
        >
          Next
        </button>
        <button
          onClick={() => onPageChange(totalPages)}
          disabled={currentPage >= totalPages}
          className={`${gridStyles.pagerButton} px-2 py-1 text-xs`}
        >
          »
        </button>
      </div>
    </div>
  );
};

// Module level, not inside the page: a component declared during render is a
// new type every render, so React would remount it and the search box would
// lose focus on each keystroke.
const ConfigSection: React.FC<{
  title: string;
  count: number;
  description: React.ReactNode;
  search: string;
  onSearch: (value: string) => void;
  searchPlaceholder: string;
  addLabel: string;
  canAdd: boolean;
  onAdd: () => void;
  children: React.ReactNode;
}> = ({ title, count, description, search, onSearch, searchPlaceholder, addLabel, canAdd, onAdd, children }) => (
  <div>
    <div className="mb-3 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h3 className="flex items-center gap-2 text-lg font-semibold text-gray-800">
          {title}
          <span className={gridStyles.countBadge}>{count}</span>
        </h3>
        <p className="text-sm text-gray-500">{description}</p>
      </div>
      <div className="flex items-center gap-3">
        <SearchBar value={search} onChange={onSearch} placeholder={searchPlaceholder} />
        {canAdd && (
          <button onClick={onAdd} className={buttonStyles.primary}>
            {Icons.plus()} {addLabel}
          </button>
        )}
      </div>
    </div>
    <div className={gridStyles.shell}>{children}</div>
  </div>
);

const RowActions: React.FC<{ canWrite: boolean; onEdit: () => void; onDelete: () => void; name: string }> = ({ canWrite, onEdit, onDelete, name }) =>
  canWrite ? (
    <div className="flex items-center justify-center gap-1">
      <GridActionButton onClick={onEdit} title={`Edit ${name}`} tone="blue">
        {Icons.edit()}
      </GridActionButton>
      <GridActionButton onClick={onDelete} title={`Delete ${name}`} tone="red">
        {Icons.trash()}
      </GridActionButton>
    </div>
  ) : (
    <span className="text-xs text-gray-400">View</span>
  );

const OpenAlertsCell: React.FC<{ count: number }> = ({ count }) =>
  count ? (
    <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs font-semibold text-red-700 ring-1 ring-red-200">{count} open</span>
  ) : (
    <span className="text-xs text-gray-400">None</span>
  );

// ── Main Component ────────────────────────────────────────────────────

const InfraAlertPage: React.FC = () => {
  const { canWrite } = useAuth();
  // Deleting a disk is a capability (cost_resource_cleanup, default-granted to write) like VM power.
  const { hasCapability } = usePermissions();
  const canCleanupResources = canWrite && hasCapability("COST_RESOURCE_CLEANUP");
  // Gate exactly like the API: the power routes check these capabilities.
  const canPowerVM = canWrite && hasCapability("INFRA_VM_POWER");
  const canPowerPG = canWrite && hasCapability("INFRA_PG_SERVER_POWER");
  const canRunCommand = canWrite && hasCapability("INFRA_VM_RUN_COMMAND");
  const canAdminResources = canWrite && hasCapability("INFRA_RESOURCE_ADMIN");
  const { timezone, formatDate } = usePortalTimezone();
  const { availableSubscriptions, effectiveSubscriptionIds } = useSubscriptionScope();
  const scopedSubscriptions = useMemo(
    () => availableSubscriptions.filter((s) => effectiveSubscriptionIds.includes(s.subscription_id)),
    [availableSubscriptions, effectiveSubscriptionIds],
  );
  // Prod / Non-Prod per subscription — Run Command asks for an extra confirmation on Prod.
  const subscriptionTiers = useMemo(() => {
    const map = new Map<string, "prod" | "nonprod">();
    availableSubscriptions.forEach((s) => s.tier && map.set(s.subscription_id.toLowerCase(), s.tier));
    return map;
  }, [availableSubscriptions]);
  const [searchParams, setSearchParams] = useSearchParams();
  const [activeTab, setActiveTabState] = useState<TabKey>(() => {
    const requested = searchParams.get("tab");
    return requested && TAB_KEYS.includes(requested as TabKey) ? (requested as TabKey) : "dashboard";
  });
  const setActiveTab = useCallback((tab: TabKey) => {
    setActiveTabState(tab);
    setSearchParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("tab", tab);
      next.delete("alert");
      return next;
    }, { replace: true });
  }, [setSearchParams]);
  const [subscriptionFilter, setSubscriptionFilter] = useState<string>("");
  const [editor, setEditor] = useState<ConfigEditorTarget | null>(null);
  const [detail, setDetail] = useState<InfraDetailTarget | null>(null);
  const [showAlertScheduleEditor, setShowAlertScheduleEditor] = useState(false);
  const [editingAlertSchedule, setEditingAlertSchedule] = useState<AlertScheduleConfig | null>(null);
  const [pgAlertStatusFilter, setPgAlertStatusFilter] = useState<string>("");
  // Separate filters: one shared value used to filter the VM and expiry tabs together.
  const [vmAlertStatusFilter, setVmAlertStatusFilter] = useState<string>("");
  const [expiryAlertStatusFilter, setExpiryAlertStatusFilter] = useState<string>("");
  const [testEmail, setTestEmail] = useState<string>("");
  const [alertScheduleFormData, setAlertScheduleFormData] = useState<CreateAlertScheduleConfigRequest>(
    defaultAlertScheduleFormData,
  );
  const [alertScheduleRecipientsInput, setAlertScheduleRecipientsInput] = useState("");

  // Table search + pagination state (single object for all 9 tables)
  const [tblState, setTblState] = useState<Record<string, { search: string; page: number }>>({});
  const [tblSortState, setTblSortState] = useState<Record<string, SortState<string>>>({});
  const tbl = (key: string) => tblState[key] || { search: "", page: 1 };
  const tblSort = (key: string, defaultKey: string, defaultDirection: "asc" | "desc" = "asc") =>
    tblSortState[key] || { key: defaultKey, direction: defaultDirection };
  const setTblSearch = (key: string, search: string) =>
    setTblState((prev) => ({ ...prev, [key]: { search, page: 1 } }));
  const setTblPage = (key: string, page: number) =>
    setTblState((prev) => ({
      ...prev,
      [key]: { ...(prev[key] || { search: "", page: 1 }), page },
    }));
  const setTblSort = (table: string, key: string, defaultDirection: "asc" | "desc" = "asc") =>
    setTblSortState((prev) => ({
      ...prev,
      [table]: nextSortState(prev[table] || { key, direction: defaultDirection }, key),
    }));

  // Queries
  const { data: summary, isLoading: summaryLoading } = useAlertSummary();
  const { data: vmAlerts = [] } = useVMThresholdAlerts(vmAlertStatusFilter || undefined);
  const { data: expiryAlerts = [] } = useExpiryAlerts(undefined, expiryAlertStatusFilter || undefined);
  // Unfiltered copies (same cache as the detail views) for the dashboard.
  const { data: allVmAlerts = [] } = useVMThresholdAlerts();
  const { data: allExpiryAlerts = [] } = useExpiryAlerts();
  const { data: vmConfigs = [] } = useVMThresholdConfigs();
  const { data: expiryConfigs = [] } = useExpiryConfigs();
  const { data: storageConfigs = [] } = useStorageAlertConfigs();
  const { data: pgConfigs = [] } = usePGFlexConfigs();
  const { data: pgAlerts = [] } = usePGFlexAlerts(pgAlertStatusFilter || undefined);
  const { data: allPgAlerts = [] } = usePGFlexAlerts();
  const { data: vmResponse } = useAzureVMs();
  const { data: adminSubscriptions } = useAdminSubscriptions();
  const { data: storageResponse } = useAzureStorageAccounts();
  const { data: diskResponse } = useAzureDisks();
  const { data: pgServerResponse } = useAzurePGServers();
  const azureVMs = vmResponse?.resources || [];
  const storageAccounts = storageResponse?.resources || [];
  const disks = diskResponse?.resources || [];
  const pgServers = pgServerResponse?.resources || [];
  const lastSyncTime = vmResponse?.last_sync || storageResponse?.last_sync || diskResponse?.last_sync;
  const dataSource = vmResponse?.source || "db";
  const subNameMap = useMemo(() => {
    const map = new Map<string, string>();
    adminSubscriptions?.forEach((s) => map.set(s.subscription_id, s.subscription_name || s.name));
    return map;
  }, [adminSubscriptions]);

  // Subscription-filtered data
  const filteredAzureVMs = useMemo(
    () => subscriptionFilter ? azureVMs.filter((v) => v.subscription_id === subscriptionFilter) : azureVMs,
    [azureVMs, subscriptionFilter],
  );
  const filteredStorageAccounts = useMemo(
    () => subscriptionFilter ? storageAccounts.filter((s) => s.subscription_id === subscriptionFilter) : storageAccounts,
    [storageAccounts, subscriptionFilter],
  );
  const filteredDisks = useMemo(
    () => subscriptionFilter ? disks.filter((d) => d.subscription_id === subscriptionFilter) : disks,
    [disks, subscriptionFilter],
  );
  const filteredPGServers = useMemo(
    () => subscriptionFilter ? pgServers.filter((p) => p.subscription_id === subscriptionFilter) : pgServers,
    [pgServers, subscriptionFilter],
  );
  const filteredVMConfigs = useMemo(
    () => subscriptionFilter ? vmConfigs.filter((c) => c.subscription_id === subscriptionFilter) : vmConfigs,
    [vmConfigs, subscriptionFilter],
  );
  const filteredStorageConfigs = useMemo(
    () => subscriptionFilter ? storageConfigs.filter((c) => c.subscription_id === subscriptionFilter) : storageConfigs,
    [storageConfigs, subscriptionFilter],
  );
  const filteredPGConfigs = useMemo(
    () => subscriptionFilter ? pgConfigs.filter((c) => c.subscription_id === subscriptionFilter) : pgConfigs,
    [pgConfigs, subscriptionFilter],
  );
  const filteredVMAlerts = useMemo(() => {
    if (!subscriptionFilter) return vmAlerts;
    const configIds = new Set(filteredVMConfigs.map((c) => c.id));
    return vmAlerts.filter((a) => configIds.has(a.config_id));
  }, [vmAlerts, subscriptionFilter, filteredVMConfigs]);
  const filteredPGAlerts = useMemo(() => {
    if (!subscriptionFilter) return pgAlerts;
    const configIds = new Set(filteredPGConfigs.map((c) => c.id));
    return pgAlerts.filter((a) => configIds.has(a.config_id));
  }, [pgAlerts, subscriptionFilter, filteredPGConfigs]);

  const { data: inventorySummary } = useResourceInventorySummary();
  const { data: schedulerStatus } = useSchedulerStatus();
  const { data: alertScheduleConfigs = [] } = useAlertScheduleConfigs();
  const { data: notificationHistory = [] } = useNotificationHistory();

  // Mutations
  const acknowledgeVMAlert = useAcknowledgeVMAlert();
  const resolveVMAlert = useResolveVMAlert();
  const acknowledgeExpiryAlert = useAcknowledgeExpiryAlert();
  const resolveExpiryAlert = useResolveExpiryAlert();
  const deleteVMConfig = useDeleteVMThresholdConfig();
  const deleteExpiryConfig = useDeleteExpiryConfig();
  const checkExpiry = useCheckExpiryAlerts();
  const triggerVMCheck = useTriggerVMCheck();
  const triggerExpiryCheck = useTriggerExpiryCheck();
  const triggerResourceSync = useTriggerResourceSync();
  const syncResources = useSyncResources();
  const deleteStorageConfigMut = useDeleteStorageAlertConfig();
  const deletePGConfigMut = useDeletePGFlexConfig();
  const acknowledgePGAlert = useAcknowledgePGFlexAlert();
  const resolvePGAlert = useResolvePGFlexAlert();
  const checkPGAlerts = useCheckPGAlerts();
  const triggerPGCheck = useTriggerPGCheck();
  const sendTestNotification = useSendTestNotification();
  const startSchedulerMut = useStartScheduler();
  const stopSchedulerMut = useStopScheduler();
  const createAlertScheduleMut = useCreateAlertScheduleConfig();
  const updateAlertScheduleMut = useUpdateAlertScheduleConfig();
  const deleteAlertScheduleMut = useDeleteAlertScheduleConfig();
  const startVMMut = useStartVM();
  const stopVMMut = useStopVM();
  const restartVMMut = useRestartVM();
  const startPGServerMut = useStartPGServer();
  const stopPGServerMut = useStopPGServer();
  const restartPGServerMut = useRestartPGServer();
  const [powerPendingKey, setPowerPendingKey] = useState<string | null>(null);
  // Resources tab: which resource type the tiles focus, and per-grid state filters.
  const [resourceView, setResourceView] = useState<"all" | "vm" | "pg" | "storage" | "disk">("all");
  const [vmStateFilter, setVmStateFilter] = useState<"all" | "running" | "stopped">("all");
  const [pgStateFilter, setPgStateFilter] = useState<"all" | "running" | "stopped">("all");
  const [diskStateFilter, setDiskStateFilter] = useState<"all" | "attached" | "unattached">("all");
  const { data: vmUtilization } = useResourceUtilization("vm", activeTab === "resources");
  const { data: pgUtilization } = useResourceUtilization("pg", activeTab === "resources");
  const [diskActionTarget, setDiskActionTarget] = useState<string | null>(null);
  const deleteDiskMut = useDeleteUnattachedDisk();
  const [confirmDialog, setConfirmDialog] = useState<{
    title: string;
    message: string;
    confirmLabel: string;
    onConfirm: () => void;
  } | null>(null);

  // Toast notification (consistent with AKS Operations page)
  const [toast, setToast] = useState<ToastState | null>(null);
  const showToast = useCallback((message: string, type: ToastState["type"] = "success") => setToast({ message, type }), []);
  const toastError = useCallback((error: unknown, fallback: string) => showToast(apiErrorMessage(error, fallback), "error"), [showToast]);

  // Email links land on ?alert=vm-12 / pg-3 / expiry-7 (older mails: ?alert=12, a VM alert).
  useEffect(() => {
    const requested = searchParams.get("alert");
    if (!requested) return;
    const match = requested.match(/^(?:(vm|pg|expiry)-)?(\d+)$/);
    if (match) {
      const kind = (match[1] || "vm") as "vm" | "pg" | "expiry";
      setDetail({ kind: `${kind}-alert` as "vm-alert", id: Number(match[2]) });
      setActiveTabState(kind === "expiry" ? "expiry-alerts" : kind === "pg" ? "pg-thresholds" : "vm-thresholds");
    }
    // Only on arrival; closing the detail clears the parameter.
  }, []);

  const closeDetail = useCallback(() => {
    setDetail(null);
    if (searchParams.get("alert")) {
      setSearchParams((prev) => {
        const next = new URLSearchParams(prev);
        next.delete("alert");
        return next;
      }, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  const deleteConfigMutations = {
    vm: deleteVMConfig,
    pg: deletePGConfigMut,
    storage: deleteStorageConfigMut,
    expiry: deleteExpiryConfig,
  };
  const requestDeleteConfig = (kind: "vm" | "pg" | "storage" | "expiry", id: number, name: string) => {
    const label = { vm: "VM threshold", pg: "PG server", storage: "storage", expiry: "expiry" }[kind];
    setConfirmDialog({
      title: `Delete ${label} configuration?`,
      message:
        kind === "storage"
          ? `Stop tracking thresholds for "${name}". This cannot be undone.`
          : `Stop monitoring "${name}" and delete its alert history. Open alerts disappear and no further emails are sent. This cannot be undone.`,
      confirmLabel: "Delete",
      onConfirm: () =>
        deleteConfigMutations[kind].mutate(id, {
          onSuccess: () => {
            showToast(`Configuration for ${name} deleted`);
            setDetail(null);
          },
          onError: (e: unknown) => toastError(e, "Failed to delete the configuration"),
        }),
    });
  };
  const requestDeleteSchedule = (schedule: AlertScheduleConfig) =>
    setConfirmDialog({
      title: "Delete alert schedule?",
      message: `"${schedule.name}" stops running immediately on every worker. Checks it ran will no longer happen unless another schedule covers them.`,
      confirmLabel: "Delete",
      onConfirm: () =>
        deleteAlertScheduleMut.mutate(schedule.id, {
          onSuccess: () => {
            showToast(`Schedule "${schedule.name}" deleted`);
            setDetail(null);
          },
          onError: (e: unknown) => toastError(e, "Failed to delete schedule"),
        }),
    });

  const requestDeleteDisk = (disk: { name: string; resource_group: string; subscription_id: string }) =>
    setConfirmDialog({
      title: "Delete unattached disk?",
      message: `Permanently delete "${disk.name}" in ${disk.resource_group}? This cannot be undone.`,
      confirmLabel: "Delete",
      onConfirm: () => {
        setDiskActionTarget(disk.name);
        deleteDiskMut.mutate(
          { subscription_id: disk.subscription_id, resource_group: disk.resource_group, disk_name: disk.name },
          {
            onSuccess: () => {
              showToast(`Disk '${disk.name}' deleted`);
              setDetail(null);
              syncResources.mutate("disk");
            },
            onError: (e: unknown) => toastError(e, `Failed to delete disk '${disk.name}'`),
            onSettled: () => setDiskActionTarget(null),
          },
        );
      },
    });

  const powerMutations = {
    vm: { start: startVMMut, stop: stopVMMut, restart: restartVMMut },
    pg: { start: startPGServerMut, stop: stopPGServerMut, restart: restartPGServerMut },
  };
  const runPower = (kind: PowerKind, action: PowerAction, resource: PowerTarget) => {
    const key = `${kind}:${resource.subscription_id}:${resource.name}`;
    const label = kind === "vm" ? "VM" : "PG server";
    const verb = { start: "started", stop: kind === "vm" ? "stopped (deallocated)" : "stopped", restart: "restarted" }[action];
    const execute = () => {
      setPowerPendingKey(key);
      const body =
        kind === "vm"
          ? { resource_group: resource.resource_group, vm_name: resource.name, subscription_id: resource.subscription_id }
          : { resource_group: resource.resource_group, server_name: resource.name, subscription_id: resource.subscription_id };
      (powerMutations[kind][action].mutate as (b: typeof body, o: object) => void)(body, {
        onSuccess: (result: { power_state?: string | null }) =>
          showToast(`${label} '${resource.name}' ${verb}${result?.power_state ? ` — now ${result.power_state}` : ""}`),
        onError: (e: unknown) => toastError(e, `Failed to ${action} ${label} '${resource.name}'`),
        onSettled: () => setPowerPendingKey(null),
      });
    };
    if (action === "start") {
      execute();
      return;
    }
    const subscription = subNameMap.get(resource.subscription_id || "") || resource.subscription_id || "its subscription";
    setConfirmDialog({
      title: `${action === "stop" ? "Stop" : "Restart"} ${resource.name}?`,
      message:
        action === "stop"
          ? `${label} "${resource.name}" in ${resource.resource_group} (${subscription}) will be ${kind === "vm" ? "deallocated — everything running on it stops" : "stopped — every connection is dropped"}. This can take a few minutes.`
          : `${label} "${resource.name}" in ${resource.resource_group} (${subscription}) will restart. Running workloads are interrupted.`,
      confirmLabel: action === "stop" ? "Stop" : "Restart",
      onConfirm: execute,
    });
  };

  // Tab navigation
  const tabs = [
    { key: "dashboard" as TabKey, label: "Dashboard", icon: Icons.alert },
    { key: "vm-thresholds" as TabKey, label: "VM Alerts", icon: Icons.server },
    { key: "pg-thresholds" as TabKey, label: "PG Alerts", icon: Icons.database },
    { key: "expiry-alerts" as TabKey, label: "Expiry Alerts", icon: Icons.clock },
    { key: "resources" as TabKey, label: "Resources", icon: Icons.database },
    { key: "configs" as TabKey, label: "Configuration", icon: Icons.settings },
    { key: "scheduler" as TabKey, label: "Scheduler", icon: Icons.play },
  ];

  const vmStatusTotals = summary?.vm_threshold_alerts?.by_status || {};
  const expiryStatusTotals = summary?.expiry_alerts?.by_status || {};
  const pgStatusTotals = summary?.pg_flex_alerts?.by_status || {};

  const activeVmAlerts = vmStatusTotals.active || 0;
  const activeExpiryAlerts = expiryStatusTotals.active || 0;
  const activePgAlerts = pgStatusTotals.active || 0;

  const totalVmAlerts = totalFromStatusMap(vmStatusTotals);
  const totalExpiryAlerts = totalFromStatusMap(expiryStatusTotals);
  const totalPgAlerts = totalFromStatusMap(pgStatusTotals);

  const statusPieData = useMemo(() => {
    const byStatus = {
      active: activeVmAlerts + activeExpiryAlerts + activePgAlerts,
      acknowledged: (vmStatusTotals.acknowledged || 0) + (expiryStatusTotals.acknowledged || 0) + (pgStatusTotals.acknowledged || 0),
      resolved: (vmStatusTotals.resolved || 0) + (expiryStatusTotals.resolved || 0) + (pgStatusTotals.resolved || 0),
    };

    return [
      { name: "Active", value: byStatus.active || 0 },
      { name: "Acknowledged", value: byStatus.acknowledged || 0 },
      { name: "Resolved", value: byStatus.resolved || 0 },
    ].filter(d => d.value > 0);
  }, [activeExpiryAlerts, activePgAlerts, activeVmAlerts, expiryStatusTotals.acknowledged, expiryStatusTotals.resolved, pgStatusTotals.acknowledged, pgStatusTotals.resolved, vmStatusTotals.acknowledged, vmStatusTotals.resolved]);

  const recentActiveAlerts = useMemo(() => {
    const vmItems = allVmAlerts
      .filter((alert) => alert.status === "active")
      .map((alert) => ({
        id: `vm-${alert.id}`,
        target: { kind: "vm-alert", id: alert.id, snapshot: alert } as InfraDetailTarget,
        kindLabel: "VM",
        title: alert.vm_name,
        detail: `${alert.metric_type.toUpperCase()} at ${alert.current_value.toFixed(1)}%`,
        detailTone: "text-slate-500",
        severity: alert.severity,
        createdAt: alert.created_at,
      }));

    const expiryItems = allExpiryAlerts
      .filter((alert) => alert.status === "active")
      .map((alert) => ({
        id: `expiry-${alert.id}`,
        target: { kind: "expiry-alert", id: alert.id, snapshot: alert } as InfraDetailTarget,
        kindLabel: getAlertTypeLabel(alert.alert_type).replace(" Expiry", ""),
        title: alert.resource_name,
        // "Expires: 6/28/2026" read as upcoming for something that lapsed months ago.
        detail: `${daysLeftText(alert.days_until_expiry)} · ${formatDateOnly(alert.expiry_date)}`,
        detailTone: daysLeftTone(alert.days_until_expiry),
        severity: alert.severity,
        createdAt: alert.created_at,
      }));

    const pgItems = allPgAlerts
      .filter((alert) => alert.status === "active")
      .map((alert) => ({
        id: `pg-${alert.id}`,
        target: { kind: "pg-alert", id: alert.id, snapshot: alert } as InfraDetailTarget,
        kindLabel: "PG",
        title: alert.server_name,
        detail: `${alert.metric_type.toUpperCase()} at ${alert.current_value.toFixed(1)}%`,
        detailTone: "text-slate-500",
        severity: alert.severity,
        createdAt: alert.created_at,
      }));

    const rank = (severity: string) => (severity === "critical" ? 0 : 1);
    return [...vmItems, ...expiryItems, ...pgItems]
      .sort((left, right) => rank(left.severity) - rank(right.severity) || right.createdAt.localeCompare(left.createdAt))
      .slice(0, 8);
  }, [allExpiryAlerts, allPgAlerts, allVmAlerts]);

  const configCounts = useMemo(() => {
    const all = [...vmConfigs, ...expiryConfigs, ...pgConfigs, ...storageConfigs];
    return { total: all.length, enabled: all.filter((c) => c.is_enabled).length };
  }, [vmConfigs, expiryConfigs, pgConfigs, storageConfigs]);

  const openAlertsTotal =
    summary?.total_open_alerts ??
    activeVmAlerts + activeExpiryAlerts + activePgAlerts + (vmStatusTotals.acknowledged || 0) + (expiryStatusTotals.acknowledged || 0) + (pgStatusTotals.acknowledged || 0);

  const resetAlertScheduleEditor = useCallback(() => {
    setShowAlertScheduleEditor(false);
    setEditingAlertSchedule(null);
    setAlertScheduleFormData(defaultAlertScheduleFormData);
    setAlertScheduleRecipientsInput("");
  }, []);

  const openNewAlertScheduleEditor = useCallback(() => {
    setEditingAlertSchedule(null);
    setAlertScheduleFormData(defaultAlertScheduleFormData);
    setAlertScheduleRecipientsInput("");
    setShowAlertScheduleEditor(true);
  }, []);

  const openEditAlertScheduleEditor = useCallback((config: AlertScheduleConfig) => {
    setEditingAlertSchedule(config);
    setAlertScheduleFormData({
      name: config.name,
      description: config.description || "",
      schedule_type: config.schedule_type,
      interval_minutes: config.interval_minutes,
      cron_expression: config.cron_expression || "",
      check_vm_thresholds: config.check_vm_thresholds,
      check_storage_thresholds: config.check_storage_thresholds,
      check_disk_thresholds: config.check_disk_thresholds,
      check_expiry_alerts: config.check_expiry_alerts,
      check_pg_thresholds: config.check_pg_thresholds,
      send_daily_digest: config.send_daily_digest,
      digest_time_utc: config.digest_time_utc,
      digest_recipients: config.digest_recipients,
      is_enabled: config.is_enabled,
    });
    setAlertScheduleRecipientsInput((config.digest_recipients || []).join(", "));
    setShowAlertScheduleEditor(true);
  }, []);

  // ── Dashboard Tab ───────────────────────────────────────────────────

  const openAlertsTab = (tab: TabKey, status: string) => {
    if (tab === "vm-thresholds") setVmAlertStatusFilter(status);
    if (tab === "expiry-alerts") setExpiryAlertStatusFilter(status);
    if (tab === "pg-thresholds") setPgAlertStatusFilter(status);
    setActiveTab(tab);
  };

  const renderDashboard = () => (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-5">
        <MetricCard
          title="Active Alerts"
          value={summary?.total_active_alerts ?? 0}
          subtitle={`${openAlertsTotal} open incl. acknowledged · ${totalVmAlerts + totalExpiryAlerts + totalPgAlerts} tracked`}
          icon={Icons.alert("text-red-600")}
          tone="red"
        />
        <MetricCard
          title="Active VM Alerts"
          value={activeVmAlerts}
          subtitle={`${vmStatusTotals.acknowledged || 0} acknowledged · ${totalVmAlerts} total`}
          icon={Icons.server("text-blue-600")}
          tone="blue"
          onClick={() => openAlertsTab("vm-thresholds", "active")}
          actionLabel="Show active VM alerts"
        />
        <MetricCard
          title="Active PG Alerts"
          value={activePgAlerts}
          subtitle={`${pgStatusTotals.acknowledged || 0} acknowledged · ${totalPgAlerts} total`}
          icon={Icons.database("text-purple-600")}
          tone="purple"
          onClick={() => openAlertsTab("pg-thresholds", "active")}
          actionLabel="Show active PG alerts"
        />
        <MetricCard
          title="Active Expiry Alerts"
          value={activeExpiryAlerts}
          subtitle={`${expiryStatusTotals.acknowledged || 0} acknowledged · ${totalExpiryAlerts} total`}
          icon={Icons.clock("text-orange-600")}
          tone="orange"
          onClick={() => openAlertsTab("expiry-alerts", "active")}
          actionLabel="Show active expiry alerts"
        />
        <MetricCard
          title="Configs Monitored"
          value={configCounts.enabled}
          subtitle={`${configCounts.enabled} enabled of ${configCounts.total} configurations`}
          icon={Icons.settings("text-gray-600")}
          tone="slate"
          onClick={() => setActiveTab("configs")}
          actionLabel="Open configuration"
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Status Distribution */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h3 className="text-lg font-semibold text-gray-800">Alert Status Distribution</h3>
          <p className="mb-2 text-xs text-gray-500">VM, PG and expiry alerts together</p>
          {statusPieData.length > 0 ? (
            <ResponsiveContainer width="100%" height={260}>
              <PieChart>
                <Pie
                  data={statusPieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={100}
                  dataKey="value"
                  label={({ name, value }) => `${name}: ${value}`}
                >
                  {statusPieData.map((entry) => (
                    <Cell key={entry.name} fill={PIE_COLORS[entry.name]} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend verticalAlign="bottom" height={24} />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-[260px] text-gray-400">
              No alert data available
            </div>
          )}
        </div>

        {/* Recent Alerts */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h3 className="text-lg font-semibold text-gray-800">Active Alerts</h3>
          <p className="mb-3 text-xs text-gray-500">Critical first, newest first · click for details</p>
          <div className="space-y-2 max-h-[260px] overflow-y-auto">
            {recentActiveAlerts.map((alert) => (
              <button
                key={alert.id}
                type="button"
                onClick={() => setDetail(alert.target)}
                className="flex w-full items-center justify-between gap-3 rounded-lg border border-transparent bg-gray-50 p-3 text-left transition hover:border-att-200 hover:bg-att-50/60 focus:outline-none focus-visible:ring-2 focus-visible:ring-att-300"
              >
                <div className="min-w-0">
                  <p className="truncate font-medium text-gray-800">
                    <span className="mr-2 rounded bg-white px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-gray-500 ring-1 ring-gray-200">{alert.kindLabel}</span>
                    {alert.title}
                  </p>
                  <p className={`text-sm ${alert.detailTone}`}>{alert.detail}</p>
                </div>
                <SeverityBadge severity={alert.severity} />
              </button>
            ))}
            {recentActiveAlerts.length === 0 && (
              <p className="text-center text-gray-400 py-8">No active alerts</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );

  // ── VM Threshold Alerts Tab ─────────────────────────────────────────

  const renderVMAlerts = () => {
    const vmAlertSort = tblSort("vmAlerts", "created_at", "desc");
    const { items: pagedVMAlerts, total: totalVMAlerts, page: vmAlertPage } = filterAndPaginate(
      filteredVMAlerts,
      tbl("vmAlerts").search,
      tbl("vmAlerts").page,
      (a) => [a.vm_name, a.metric_type, a.severity, a.status],
      vmAlertSort,
      {
        vm_name: (a) => a.vm_name,
        metric_type: (a) => a.metric_type,
        current_value: (a) => a.current_value,
        threshold_value: (a) => a.threshold_value,
        severity: (a) => a.severity,
        status: (a) => a.status,
        created_at: (a) => a.created_at,
      },
    );

    return (
    <div className="space-y-6">
      {/* Filters */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <select
            value={subscriptionFilter}
            onChange={(e) => setSubscriptionFilter(e.target.value)}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All Subscriptions</option>
            {scopedSubscriptions.map((s) => (
              <option key={s.subscription_id} value={s.subscription_id}>
                {s.subscription_name}
              </option>
            ))}
          </select>
          <select
            value={vmAlertStatusFilter}
            onChange={(e) => setVmAlertStatusFilter(e.target.value)}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All Statuses</option>
            <option value="active">Active</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
          </select>
          <SearchBar
            value={tbl("vmAlerts").search}
            onChange={(v) => setTblSearch("vmAlerts", v)}
            placeholder="Search VM alerts..."
          />
        </div>
        <span className="text-sm text-gray-500">
          {totalVMAlerts} alerts found
        </span>
      </div>

      {/* Alerts Table */}
      <div className={gridStyles.shell}>
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              <th className={gridStyles.headerCell}><SortableHeader label="VM" active={vmAlertSort.key === "vm_name"} direction={vmAlertSort.direction} onClick={() => setTblSort("vmAlerts", "vm_name", "asc")} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Metric" active={vmAlertSort.key === "metric_type"} direction={vmAlertSort.direction} onClick={() => setTblSort("vmAlerts", "metric_type", "asc")} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Value" active={vmAlertSort.key === "current_value"} direction={vmAlertSort.direction} onClick={() => setTblSort("vmAlerts", "current_value", "desc")} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Threshold" active={vmAlertSort.key === "threshold_value"} direction={vmAlertSort.direction} onClick={() => setTblSort("vmAlerts", "threshold_value", "desc")} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Severity" active={vmAlertSort.key === "severity"} direction={vmAlertSort.direction} onClick={() => setTblSort("vmAlerts", "severity", "asc")} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Status" active={vmAlertSort.key === "status"} direction={vmAlertSort.direction} onClick={() => setTblSort("vmAlerts", "status", "asc")} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Created" active={vmAlertSort.key === "created_at"} direction={vmAlertSort.direction} onClick={() => setTblSort("vmAlerts", "created_at", "desc")} /></th>
              <th className={gridStyles.headerCellCenter}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {pagedVMAlerts.map((alert) => {
              const open = clickableRow(() => setDetail({ kind: "vm-alert", id: alert.id, snapshot: alert }), `Open VM alert on ${alert.vm_name}`);
              return (
              <tr key={alert.id} {...open} className={`${gridStyles.row} ${open.className}`}>
                <td className={gridStyles.strongCell}>{alert.vm_name}</td>
                <td className={gridStyles.cell}>{alert.metric_type.toUpperCase()}</td>
                <td className={gridStyles.cell}>{alert.current_value.toFixed(1)}%</td>
                <td className={gridStyles.cell}>{alert.threshold_value}%</td>
                <td className={gridStyles.cell}><SeverityBadge severity={alert.severity} /></td>
                <td className={gridStyles.cell}><StatusBadge status={alert.status} /></td>
                <td className={gridStyles.cell}>
                  {formatDate(alert.created_at)}
                </td>
                <td className={gridStyles.centerCell}>
                  <div className="flex items-center justify-center gap-1">
                    {canWrite && alert.status === "active" && (
                      <GridActionButton
                        onClick={() => acknowledgeVMAlert.mutate(alert.id, {
                          onSuccess: () => showToast("VM alert acknowledged"),
                          onError: (e: unknown) => toastError(e, "Failed to acknowledge VM alert"),
                        })}
                        title="Acknowledge"
                        tone="blue"
                      >
                        {Icons.eye()}
                      </GridActionButton>
                    )}
                    {canWrite && alert.status !== "resolved" && (
                      <GridActionButton
                        onClick={() => resolveVMAlert.mutate({ alertId: alert.id }, {
                          onSuccess: () => showToast("VM alert resolved"),
                          onError: (e: unknown) => toastError(e, "Failed to resolve VM alert"),
                        })}
                        title="Resolve (open the alert to add notes)"
                        tone="green"
                      >
                        {Icons.check()}
                      </GridActionButton>
                    )}
                  </div>
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
        {totalVMAlerts === 0 && (
          <div className="text-center py-12 text-gray-400">No VM threshold alerts found</div>
        )}
        <TablePagination
          currentPage={vmAlertPage}
          totalItems={totalVMAlerts}
          onPageChange={(p) => setTblPage("vmAlerts", p)}
        />
      </div>
    </div>
  );
  };

  // ── PG Flex Server Alerts Tab ───────────────────────────────────────

  const renderPGAlerts = () => {
    const pgAlertSort = tblSort("pgAlerts", "created_at", "desc");
    const { items: pagedPGAlerts, total: totalPGAlerts, page: pgAlertPage } = filterAndPaginate(
      filteredPGAlerts,
      tbl("pgAlerts").search,
      tbl("pgAlerts").page,
      (a) => [a.server_name, a.metric_type, a.severity, a.status],
      pgAlertSort,
      {
        server_name: (a) => a.server_name,
        metric_type: (a) => a.metric_type,
        current_value: (a) => a.current_value,
        threshold_value: (a) => a.threshold_value,
        severity: (a) => a.severity,
        status: (a) => a.status,
        created_at: (a) => a.created_at,
      },
    );

    return (
    <div className="space-y-6">
      {/* Filters */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <select
            value={subscriptionFilter}
            onChange={(e) => setSubscriptionFilter(e.target.value)}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All Subscriptions</option>
            {scopedSubscriptions.map((s) => (
              <option key={s.subscription_id} value={s.subscription_id}>
                {s.subscription_name}
              </option>
            ))}
          </select>
          <select
            value={pgAlertStatusFilter}
            onChange={(e) => setPgAlertStatusFilter(e.target.value)}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All Statuses</option>
            <option value="active">Active</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
          </select>
          <SearchBar
            value={tbl("pgAlerts").search}
            onChange={(v) => setTblSearch("pgAlerts", v)}
            placeholder="Search PG alerts..."
          />
          {canWrite && (
          <button
            onClick={() => checkPGAlerts.mutate(undefined, {
              onSuccess: (result: Record<string, unknown>) => showToast(checkSummary("PG", result)),
              onError: (e: unknown) => toastError(e, "PG alert check failed"),
            })}
            disabled={checkPGAlerts.isPending}
            className={buttonStyles.purpleSoft}
          >
            {Icons.play()} {checkPGAlerts.isPending ? "Checking..." : "Run PG Check"}
          </button>
          )}
        </div>
        <span className="text-sm text-gray-500">
          {totalPGAlerts} alerts found
        </span>
      </div>

      {/* Alerts Table */}
      <div className={gridStyles.shell}>
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              <th className={gridStyles.headerCell}><SortableHeader label="Server" active={pgAlertSort.key === "server_name"} direction={pgAlertSort.direction} onClick={() => setTblSort("pgAlerts", "server_name", "asc")} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Metric" active={pgAlertSort.key === "metric_type"} direction={pgAlertSort.direction} onClick={() => setTblSort("pgAlerts", "metric_type", "asc")} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Value" active={pgAlertSort.key === "current_value"} direction={pgAlertSort.direction} onClick={() => setTblSort("pgAlerts", "current_value", "desc")} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Threshold" active={pgAlertSort.key === "threshold_value"} direction={pgAlertSort.direction} onClick={() => setTblSort("pgAlerts", "threshold_value", "desc")} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Severity" active={pgAlertSort.key === "severity"} direction={pgAlertSort.direction} onClick={() => setTblSort("pgAlerts", "severity", "asc")} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Status" active={pgAlertSort.key === "status"} direction={pgAlertSort.direction} onClick={() => setTblSort("pgAlerts", "status", "asc")} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Created" active={pgAlertSort.key === "created_at"} direction={pgAlertSort.direction} onClick={() => setTblSort("pgAlerts", "created_at", "desc")} /></th>
              <th className={gridStyles.headerCellCenter}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {pagedPGAlerts.map((alert) => {
              const open = clickableRow(() => setDetail({ kind: "pg-alert", id: alert.id, snapshot: alert }), `Open PG alert on ${alert.server_name}`);
              return (
              <tr key={alert.id} {...open} className={`${gridStyles.row} ${open.className}`}>
                <td className={gridStyles.strongCell}>{alert.server_name}</td>
                <td className={gridStyles.cell}>{alert.metric_type.toUpperCase()}</td>
                <td className={gridStyles.cell}>{alert.current_value.toFixed(1)}%</td>
                <td className={gridStyles.cell}>{alert.threshold_value}%</td>
                <td className={gridStyles.cell}><SeverityBadge severity={alert.severity} /></td>
                <td className={gridStyles.cell}><StatusBadge status={alert.status} /></td>
                <td className={gridStyles.cell}>
                  {formatDate(alert.created_at)}
                </td>
                <td className={gridStyles.centerCell}>
                  <div className="flex items-center justify-center gap-1">
                    {canWrite && alert.status === "active" && (
                      <GridActionButton
                        onClick={() => acknowledgePGAlert.mutate(alert.id, {
                          onSuccess: () => showToast("PG alert acknowledged"),
                          onError: (e: unknown) => toastError(e, "Failed to acknowledge PG alert"),
                        })}
                        title="Acknowledge"
                        tone="blue"
                      >
                        {Icons.eye()}
                      </GridActionButton>
                    )}
                    {canWrite && alert.status !== "resolved" && (
                      <GridActionButton
                        onClick={() => resolvePGAlert.mutate({ alertId: alert.id }, {
                          onSuccess: () => showToast("PG alert resolved"),
                          onError: (e: unknown) => toastError(e, "Failed to resolve PG alert"),
                        })}
                        title="Resolve (open the alert to add notes)"
                        tone="green"
                      >
                        {Icons.check()}
                      </GridActionButton>
                    )}
                  </div>
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
        {totalPGAlerts === 0 && (
          <div className="text-center py-12 text-gray-400">No PostgreSQL Flexible Server alerts found</div>
        )}
        <TablePagination
          currentPage={pgAlertPage}
          totalItems={totalPGAlerts}
          onPageChange={(p) => setTblPage("pgAlerts", p)}
        />
      </div>
    </div>
  );
  };

  // ── Expiry Alerts Tab ───────────────────────────────────────────────

  const renderExpiryAlerts = () => {
    const expiryAlertSort = tblSort("expiryAlerts", "expiry_date", "asc");
    const { items: pagedExpAlerts, total: totalExpAlerts, page: expAlertPage } = filterAndPaginate(
      expiryAlerts,
      tbl("expiryAlerts").search,
      tbl("expiryAlerts").page,
      (a) => [getAlertTypeLabel(a.alert_type), a.resource_name, a.severity, a.status],
      expiryAlertSort,
      {
        alert_type: (a) => getAlertTypeLabel(a.alert_type),
        resource_name: (a) => a.resource_name,
        expiry_date: (a) => a.expiry_date,
        days_until_expiry: (a) => a.days_until_expiry,
        severity: (a) => a.severity,
        status: (a) => a.status,
      },
    );

    return (
    <div className="space-y-6">
      {/* Actions */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <select
            value={expiryAlertStatusFilter}
            onChange={(e) => setExpiryAlertStatusFilter(e.target.value)}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All Statuses</option>
            <option value="active">Active</option>
            <option value="acknowledged">Acknowledged</option>
            <option value="resolved">Resolved</option>
          </select>
          <SearchBar
            value={tbl("expiryAlerts").search}
            onChange={(v) => setTblSearch("expiryAlerts", v)}
            placeholder="Search expiry alerts..."
          />
        </div>
        {canWrite && (
        <button
          onClick={() => checkExpiry.mutate(undefined, {
            onSuccess: (result: Record<string, unknown>) => showToast(checkSummary("Expiry", result)),
            onError: (e: unknown) => toastError(e, "Expiry alert check failed"),
          })}
          disabled={checkExpiry.isPending}
          className={buttonStyles.blueSoft}
        >
          {Icons.refresh(checkExpiry.isPending ? "animate-spin" : "")}
          Check Expiry Alerts
        </button>
        )}
      </div>

      {/* Alerts Table */}
      <div className={gridStyles.shell}>
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              <th className={gridStyles.headerCell}><SortableHeader label="Type" active={expiryAlertSort.key === "alert_type"} direction={expiryAlertSort.direction} onClick={() => setTblSort("expiryAlerts", "alert_type", "asc")} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Resource" active={expiryAlertSort.key === "resource_name"} direction={expiryAlertSort.direction} onClick={() => setTblSort("expiryAlerts", "resource_name", "asc")} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Expiry Date" active={expiryAlertSort.key === "expiry_date"} direction={expiryAlertSort.direction} onClick={() => setTblSort("expiryAlerts", "expiry_date", "asc")} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Days Left" active={expiryAlertSort.key === "days_until_expiry"} direction={expiryAlertSort.direction} onClick={() => setTblSort("expiryAlerts", "days_until_expiry", "asc")} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Severity" active={expiryAlertSort.key === "severity"} direction={expiryAlertSort.direction} onClick={() => setTblSort("expiryAlerts", "severity", "asc")} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Status" active={expiryAlertSort.key === "status"} direction={expiryAlertSort.direction} onClick={() => setTblSort("expiryAlerts", "status", "asc")} /></th>
              <th className={gridStyles.headerCellCenter}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {pagedExpAlerts.map((alert) => {
              const open = clickableRow(() => setDetail({ kind: "expiry-alert", id: alert.id, snapshot: alert }), `Open expiry alert for ${alert.resource_name}`);
              return (
              <tr key={alert.id} {...open} className={`${gridStyles.row} ${open.className}`}>
                <td className={gridStyles.strongCell}>
                  {getAlertTypeLabel(alert.alert_type)}
                </td>
                <td className={gridStyles.cell}>{alert.resource_name}</td>
                <td className={gridStyles.cell}>
                  {formatDateOnly(alert.expiry_date)}
                </td>
                <td className={gridStyles.cell}>
                  {/* "EXPIRED" used to show for anything due today or tomorrow too. */}
                  <span className={daysLeftTone(alert.days_until_expiry)}>{daysLeftText(alert.days_until_expiry)}</span>
                </td>
                <td className={gridStyles.cell}><SeverityBadge severity={alert.severity} /></td>
                <td className={gridStyles.cell}><StatusBadge status={alert.status} /></td>
                <td className={gridStyles.centerCell}>
                  <div className="flex items-center justify-center gap-1">
                    {canWrite && alert.status === "active" && (
                      <GridActionButton
                        onClick={() => acknowledgeExpiryAlert.mutate(alert.id, {
                          onSuccess: () => showToast("Expiry alert acknowledged"),
                          onError: (e: unknown) => toastError(e, "Failed to acknowledge expiry alert"),
                        })}
                        title="Acknowledge"
                        tone="blue"
                      >
                        {Icons.eye()}
                      </GridActionButton>
                    )}
                    {canWrite && alert.status !== "resolved" && (
                      <GridActionButton
                        onClick={() => resolveExpiryAlert.mutate({ alertId: alert.id }, {
                          onSuccess: () => showToast("Expiry alert resolved — it stays resolved for this expiry date unless it gets worse"),
                          onError: (e: unknown) => toastError(e, "Failed to resolve expiry alert"),
                        })}
                        title="Resolve (open the alert to add notes)"
                        tone="green"
                      >
                        {Icons.check()}
                      </GridActionButton>
                    )}
                  </div>
                </td>
              </tr>
              );
            })}
          </tbody>
        </table>
        {totalExpAlerts === 0 && (
          <div className="text-center py-12 text-gray-400">No expiry alerts found</div>
        )}
        <TablePagination
          currentPage={expAlertPage}
          totalItems={totalExpAlerts}
          onPageChange={(p) => setTblPage("expiryAlerts", p)}
        />
      </div>
    </div>
  );
  };

  // ── Configuration Tab ───────────────────────────────────────────────

  const openAlertsByConfig = (alerts: { config_id: number; status: string }[]) => {
    const counts = new Map<number, number>();
    alerts.forEach((a) => {
      if (a.status !== "resolved") counts.set(a.config_id, (counts.get(a.config_id) || 0) + 1);
    });
    return counts;
  };

  const renderConfigs = () => {
    const vmOpen = openAlertsByConfig(allVmAlerts);
    const pgOpen = openAlertsByConfig(allPgAlerts);
    const expiryOpen = openAlertsByConfig(allExpiryAlerts);
    const vmConfigSort = tblSort("vmConfigs", "vm_name", "asc");
    const expiryConfigSort = tblSort("expiryConfigs", "days_until_expiry", "asc");
    const storageConfigSort = tblSort("storageConfigs", "account_name", "asc");
    const pgConfigSort = tblSort("pgConfigs", "server_name", "asc");
    const { items: pagedVMConfigs, total: totalVMConfigs, page: vmCfgPage } = filterAndPaginate(
      filteredVMConfigs,
      tbl("vmConfigs").search,
      tbl("vmConfigs").page,
      (c) => [c.vm_name, c.resource_group, ...(c.notification_emails || [])],
      vmConfigSort,
      {
        vm_name: (c) => c.vm_name,
        resource_group: (c) => c.resource_group,
        cpu_warning_threshold: (c) => c.cpu_warning_threshold,
        memory_warning_threshold: (c) => c.memory_warning_threshold,
        disk_warning_threshold: (c) => c.disk_warning_threshold,
        open: (c) => vmOpen.get(c.id) || 0,
        is_enabled: (c) => c.is_enabled,
      },
    );
    const { items: pagedExpConfigs, total: totalExpConfigs, page: expCfgPage } = filterAndPaginate(
      expiryConfigs,
      tbl("expiryConfigs").search,
      tbl("expiryConfigs").page,
      (c) => [getAlertTypeLabel(c.alert_type), c.resource_name, c.resource_identifier, getEnvLabel(c.environment), c.description],
      expiryConfigSort,
      {
        alert_type: (c) => getAlertTypeLabel(c.alert_type),
        resource_name: (c) => c.resource_name,
        environment: (c) => getEnvLabel(c.environment),
        expiry_date: (c) => c.expiry_date,
        days_until_expiry: (c) => c.days_until_expiry ?? Number.MAX_SAFE_INTEGER,
        warning_days_before: (c) => c.warning_days_before,
        open: (c) => expiryOpen.get(c.id) || 0,
        is_enabled: (c) => c.is_enabled,
      },
    );
    const { items: pagedStorageConfigs, total: totalStorageConfigs, page: storageCfgPage } = filterAndPaginate(
      filteredStorageConfigs,
      tbl("storageConfigs").search,
      tbl("storageConfigs").page,
      (c) => [c.account_name, c.resource_group],
      storageConfigSort,
      {
        account_name: (c) => c.account_name,
        resource_group: (c) => c.resource_group,
        capacity_warning_gb: (c) => c.capacity_warning_gb,
        transactions_warning: (c) => c.transactions_warning || 0,
        egress_warning_gb: (c) => c.egress_warning_gb,
        is_enabled: (c) => c.is_enabled,
      },
    );
    const { items: pagedPGConfigs, total: totalPGConfigs, page: pgCfgPage } = filterAndPaginate(
      filteredPGConfigs,
      tbl("pgConfigs").search,
      tbl("pgConfigs").page,
      (c) => [c.server_name, c.resource_group],
      pgConfigSort,
      {
        server_name: (c) => c.server_name,
        resource_group: (c) => c.resource_group,
        cpu_warning_threshold: (c) => c.cpu_warning_threshold,
        memory_warning_threshold: (c) => c.memory_warning_threshold,
        storage_warning_threshold: (c) => c.storage_warning_threshold,
        open: (c) => pgOpen.get(c.id) || 0,
        is_enabled: (c) => c.is_enabled,
      },
    );
    const header = (table: string, sort: SortState<string>, key: string, label: string, dir: "asc" | "desc" = "asc") => (
      <th className={gridStyles.headerCell}>
        <SortableHeader label={label} active={sort.key === key} direction={sort.direction} onClick={() => setTblSort(table, key, dir)} />
      </th>
    );
    const pair = (w: number, c: number, unit = "%") => (
      <span className="whitespace-nowrap">
        <span className="text-amber-700">{w}{unit}</span>
        <span className="text-gray-400"> / </span>
        <span className="text-red-700">{c}{unit}</span>
      </span>
    );

    return (
    <div className="space-y-8">
      {/* Subscription Filter */}
      <div className="flex flex-wrap items-center justify-between gap-4">
        <select
          value={subscriptionFilter}
          onChange={(e) => setSubscriptionFilter(e.target.value)}
          className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
        >
          <option value="">All Subscriptions</option>
          {scopedSubscriptions.map((s) => (
            <option key={s.subscription_id} value={s.subscription_id}>
              {s.subscription_name}
            </option>
          ))}
        </select>
        <p className="text-sm text-gray-500">Click any row for its details, live metrics and alert history.</p>
      </div>

      <ConfigSection
        title="Expiry Tracking"
        count={expiryConfigs.length}
        description="MechIDs, domain accounts, AAF and database accounts, certificates — warned before they expire."
        search={tbl("expiryConfigs").search}
        onSearch={(v) => setTblSearch("expiryConfigs", v)}
        canAdd={canWrite}
        searchPlaceholder="Search name, identifier…"
        addLabel="Track Expiry"
        onAdd={() => setEditor({ kind: "expiry", config: null })}
      >
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              {header("expiryConfigs", expiryConfigSort, "alert_type", "Type")}
              {header("expiryConfigs", expiryConfigSort, "resource_name", "Resource")}
              {header("expiryConfigs", expiryConfigSort, "environment", "Env")}
              {header("expiryConfigs", expiryConfigSort, "expiry_date", "Expiry Date")}
              {header("expiryConfigs", expiryConfigSort, "days_until_expiry", "Days Left")}
              {header("expiryConfigs", expiryConfigSort, "warning_days_before", "Warn / Crit", "desc")}
              {header("expiryConfigs", expiryConfigSort, "open", "Alerts", "desc")}
              {header("expiryConfigs", expiryConfigSort, "is_enabled", "Status")}
              <th className={gridStyles.headerCellCenter}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {pagedExpConfigs.map((config) => {
              const open = clickableRow(() => setDetail({ kind: "expiry-config", id: config.id }), `Open ${config.resource_name}`);
              const health = expiryHealth(config.days_until_expiry, config.warning_days_before, config.critical_days_before);
              return (
                <tr key={config.id} {...open} className={`${gridStyles.row} ${open.className}`}>
                  <td className={gridStyles.strongCell}>{getAlertTypeLabel(config.alert_type)}</td>
                  <td className={gridStyles.cell}>
                    <div className="font-medium text-gray-800">{config.resource_name}</div>
                    {config.resource_identifier !== config.resource_name && <div className="font-mono text-xs text-gray-500">{config.resource_identifier}</div>}
                  </td>
                  <td className={gridStyles.cell}>
                    {config.environment ? (
                      <span className={`px-2 py-1 rounded-full text-xs font-medium ${config.environment === "prod" ? "bg-green-100 text-green-700" : "bg-amber-100 text-amber-700"}`}>
                        {getEnvLabel(config.environment)}
                      </span>
                    ) : (
                      <span className="text-gray-400">—</span>
                    )}
                  </td>
                  <td className={gridStyles.cell}>{formatDateOnly(config.expiry_date)}</td>
                  <td className={gridStyles.cell}>
                    <div className={daysLeftTone(config.days_until_expiry, config.warning_days_before, config.critical_days_before)}>{daysLeftText(config.days_until_expiry)}</div>
                    {config.is_enabled && health !== "ok" && <ExpiryHealthBadge health={health} />}
                  </td>
                  <td className={gridStyles.cell}>
                    <span className="whitespace-nowrap">
                      <span className="text-amber-700">{config.warning_days_before}d</span>
                      <span className="text-gray-400"> / </span>
                      <span className="text-red-700">{config.critical_days_before}d</span>
                    </span>
                  </td>
                  <td className={gridStyles.cell}><OpenAlertsCell count={expiryOpen.get(config.id) || 0} /></td>
                  <td className={gridStyles.cell}><ConfigStateBadge enabled={config.is_enabled} snoozeUntil={config.snooze_until} /></td>
                  <td className={gridStyles.centerCell}>
                    <RowActions
                      canWrite={canWrite}
                      name={config.resource_name}
                      onEdit={() => setEditor({ kind: "expiry", config })}
                      onDelete={() => requestDeleteConfig("expiry", config.id, config.resource_name)}
                    />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {totalExpConfigs === 0 && (
          <div className="py-12 text-center text-gray-400">
            {expiryConfigs.length ? "No expiry configurations match your search" : "Nothing tracked yet — add a MechID, domain account or certificate to get warned before it expires."}
          </div>
        )}
        <TablePagination currentPage={expCfgPage} totalItems={totalExpConfigs} onPageChange={(p) => setTblPage("expiryConfigs", p)} />
      </ConfigSection>

      <ConfigSection
        title="VM Thresholds"
        count={filteredVMConfigs.length}
        description="CPU, memory and disk I/O limits read from Azure Monitor on every scheduled check."
        search={tbl("vmConfigs").search}
        onSearch={(v) => setTblSearch("vmConfigs", v)}
        canAdd={canWrite}
        searchPlaceholder="Search VM, resource group…"
        addLabel="Monitor VM"
        onAdd={() => setEditor({ kind: "vm", config: null })}
      >
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              {header("vmConfigs", vmConfigSort, "vm_name", "VM Name")}
              {header("vmConfigs", vmConfigSort, "resource_group", "Resource Group")}
              {header("vmConfigs", vmConfigSort, "cpu_warning_threshold", "CPU (Warn/Crit)", "desc")}
              {header("vmConfigs", vmConfigSort, "memory_warning_threshold", "Memory (Warn/Crit)", "desc")}
              {header("vmConfigs", vmConfigSort, "disk_warning_threshold", "Disk I/O (Warn/Crit)", "desc")}
              {header("vmConfigs", vmConfigSort, "open", "Alerts", "desc")}
              {header("vmConfigs", vmConfigSort, "is_enabled", "Status")}
              <th className={gridStyles.headerCellCenter}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {pagedVMConfigs.map((config) => {
              const open = clickableRow(() => setDetail({ kind: "vm-config", id: config.id }), `Open ${config.vm_name}`);
              return (
                <tr key={config.id} {...open} className={`${gridStyles.row} ${open.className}`}>
                  <td className={gridStyles.strongCell}>{config.vm_name}</td>
                  <td className={gridStyles.cell}>{config.resource_group}</td>
                  <td className={gridStyles.cell}>{pair(config.cpu_warning_threshold, config.cpu_critical_threshold)}</td>
                  <td className={gridStyles.cell}>{pair(config.memory_warning_threshold, config.memory_critical_threshold)}</td>
                  <td className={gridStyles.cell}>{pair(config.disk_warning_threshold, config.disk_critical_threshold)}</td>
                  <td className={gridStyles.cell}><OpenAlertsCell count={vmOpen.get(config.id) || 0} /></td>
                  <td className={gridStyles.cell}><ConfigStateBadge enabled={config.is_enabled} snoozeUntil={config.snooze_until} /></td>
                  <td className={gridStyles.centerCell}>
                    <RowActions canWrite={canWrite} name={config.vm_name} onEdit={() => setEditor({ kind: "vm", config })} onDelete={() => requestDeleteConfig("vm", config.id, config.vm_name)} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {totalVMConfigs === 0 && <div className="py-12 text-center text-gray-400">No VM threshold configurations</div>}
        <TablePagination currentPage={vmCfgPage} totalItems={totalVMConfigs} onPageChange={(p) => setTblPage("vmConfigs", p)} />
      </ConfigSection>

      <ConfigSection
        title="PostgreSQL Flexible Server Thresholds"
        count={filteredPGConfigs.length}
        description="CPU, memory and storage limits for PG Flexible Servers."
        search={tbl("pgConfigs").search}
        onSearch={(v) => setTblSearch("pgConfigs", v)}
        canAdd={canWrite}
        searchPlaceholder="Search server, resource group…"
        addLabel="Monitor PG Server"
        onAdd={() => setEditor({ kind: "pg", config: null })}
      >
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              {header("pgConfigs", pgConfigSort, "server_name", "Server Name")}
              {header("pgConfigs", pgConfigSort, "resource_group", "Resource Group")}
              {header("pgConfigs", pgConfigSort, "cpu_warning_threshold", "CPU (Warn/Crit)", "desc")}
              {header("pgConfigs", pgConfigSort, "memory_warning_threshold", "Memory (Warn/Crit)", "desc")}
              {header("pgConfigs", pgConfigSort, "storage_warning_threshold", "Storage (Warn/Crit)", "desc")}
              {header("pgConfigs", pgConfigSort, "open", "Alerts", "desc")}
              {header("pgConfigs", pgConfigSort, "is_enabled", "Status")}
              <th className={gridStyles.headerCellCenter}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {pagedPGConfigs.map((config) => {
              const open = clickableRow(() => setDetail({ kind: "pg-config", id: config.id }), `Open ${config.server_name}`);
              return (
                <tr key={config.id} {...open} className={`${gridStyles.row} ${open.className}`}>
                  <td className={gridStyles.strongCell}>{config.server_name}</td>
                  <td className={gridStyles.cell}>{config.resource_group}</td>
                  <td className={gridStyles.cell}>{pair(config.cpu_warning_threshold, config.cpu_critical_threshold)}</td>
                  <td className={gridStyles.cell}>{pair(config.memory_warning_threshold, config.memory_critical_threshold)}</td>
                  <td className={gridStyles.cell}>{pair(config.storage_warning_threshold, config.storage_critical_threshold)}</td>
                  <td className={gridStyles.cell}><OpenAlertsCell count={pgOpen.get(config.id) || 0} /></td>
                  <td className={gridStyles.cell}><ConfigStateBadge enabled={config.is_enabled} snoozeUntil={config.snooze_until} /></td>
                  <td className={gridStyles.centerCell}>
                    <RowActions canWrite={canWrite} name={config.server_name} onEdit={() => setEditor({ kind: "pg", config })} onDelete={() => requestDeleteConfig("pg", config.id, config.server_name)} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {totalPGConfigs === 0 && <div className="py-12 text-center text-gray-400">No PostgreSQL Flexible Server configurations</div>}
        <TablePagination currentPage={pgCfgPage} totalItems={totalPGConfigs} onPageChange={(p) => setTblPage("pgConfigs", p)} />
      </ConfigSection>

      <ConfigSection
        title="Storage Account Thresholds"
        count={filteredStorageConfigs.length}
        description={<span>Capacity, transaction and egress limits. <span className="font-medium text-amber-700">Saved but not evaluated by the schedules yet.</span></span>}
        search={tbl("storageConfigs").search}
        onSearch={(v) => setTblSearch("storageConfigs", v)}
        canAdd={canWrite}
        searchPlaceholder="Search storage configs…"
        addLabel="Add Storage Config"
        onAdd={() => setEditor({ kind: "storage", config: null })}
      >
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              {header("storageConfigs", storageConfigSort, "account_name", "Account Name")}
              {header("storageConfigs", storageConfigSort, "resource_group", "Resource Group")}
              {header("storageConfigs", storageConfigSort, "capacity_warning_gb", "Capacity (Warn/Crit)", "desc")}
              {header("storageConfigs", storageConfigSort, "transactions_warning", "Transactions (Warn/Crit)", "desc")}
              {header("storageConfigs", storageConfigSort, "egress_warning_gb", "Egress (Warn/Crit)", "desc")}
              {header("storageConfigs", storageConfigSort, "is_enabled", "Status")}
              <th className={gridStyles.headerCellCenter}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {pagedStorageConfigs.map((config) => {
              const open = clickableRow(() => setDetail({ kind: "storage-config", id: config.id }), `Open ${config.account_name}`);
              return (
                <tr key={config.id} {...open} className={`${gridStyles.row} ${open.className}`}>
                  <td className={gridStyles.strongCell}>{config.account_name}</td>
                  <td className={gridStyles.cell}>{config.resource_group}</td>
                  <td className={gridStyles.cell}>{pair(config.capacity_warning_gb, config.capacity_critical_gb, " GB")}</td>
                  <td className={gridStyles.cell}>
                    {config.transactions_warning?.toLocaleString()} / {config.transactions_critical?.toLocaleString()}
                  </td>
                  <td className={gridStyles.cell}>{pair(config.egress_warning_gb, config.egress_critical_gb, " GB")}</td>
                  <td className={gridStyles.cell}><ConfigStateBadge enabled={config.is_enabled} snoozeUntil={config.snooze_until} /></td>
                  <td className={gridStyles.centerCell}>
                    <RowActions canWrite={canWrite} name={config.account_name} onEdit={() => setEditor({ kind: "storage", config })} onDelete={() => requestDeleteConfig("storage", config.id, config.account_name)} />
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {totalStorageConfigs === 0 && <div className="py-12 text-center text-gray-400">No storage alert configurations</div>}
        <TablePagination currentPage={storageCfgPage} totalItems={totalStorageConfigs} onPageChange={(p) => setTblPage("storageConfigs", p)} />
      </ConfigSection>
    </div>
  );
  };

  // ── Main Render ─────────────────────────────────────────────────────

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
          {Icons.alert("h-8 w-8 text-att-500")}
          Infrastructure Alerts
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Monitor VM thresholds (CPU, Memory, Disk) and track expiry dates for critical resources
        </p>
      </div>

      {/* Tab Navigation */}
      <div className="mb-6 border-b border-gray-200">
        <nav className="flex space-x-8">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-2 py-4 px-1 border-b-2 font-medium text-sm transition-colors ${
                activeTab === tab.key
                  ? "border-blue-500 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300"
              }`}
            >
              {tab.icon()}
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab Content */}
      {activeTab === "dashboard" && renderDashboard()}
      {activeTab === "vm-thresholds" && renderVMAlerts()}
      {activeTab === "pg-thresholds" && renderPGAlerts()}
      {activeTab === "expiry-alerts" && renderExpiryAlerts()}
      {activeTab === "resources" && renderResources()}
      {activeTab === "configs" && renderConfigs()}
      {activeTab === "scheduler" && renderScheduler()}

      {editor && (
        <ConfigEditor
          key={`${editor.kind}-${editor.config?.id ?? "new"}`}
          target={editor}
          subscriptionNames={subNameMap}
          formatDate={formatDate}
          onClose={() => setEditor(null)}
          onSaved={(message) => {
            setEditor(null);
            showToast(message);
          }}
        />
      )}

      {detail && (
        <InfraAlertDetailHost
          target={detail}
          onOpen={setDetail}
          onClose={closeDetail}
          onEditConfig={setEditor}
          onEditSchedule={(schedule) => {
            setDetail(null);
            setActiveTab("scheduler");
            openEditAlertScheduleEditor(schedule);
          }}
          onDeleteConfig={requestDeleteConfig}
          onDeleteSchedule={requestDeleteSchedule}
          onPower={runPower}
          powerPendingKey={powerPendingKey}
          onToast={showToast}
          onConfirm={setConfirmDialog}
          onDeleteDisk={requestDeleteDisk}
          canWrite={canWrite}
          canPowerVM={canPowerVM}
          canPowerPG={canPowerPG}
          canRunCommand={canRunCommand}
          canAdminResources={canAdminResources}
          canDeleteDisks={canCleanupResources}
          subscriptionNames={subNameMap}
          subscriptionTiers={subscriptionTiers}
          formatDate={formatDate}
        />
      )}

      {confirmDialog && (
        <div
          className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4 backdrop-blur-sm"
          onClick={() => setConfirmDialog(null)}
        >
          <div
            className="w-full max-w-md rounded-2xl bg-white p-6 shadow-2xl"
            onClick={(e) => e.stopPropagation()}
          >
            <h3 className="text-lg font-semibold text-gray-900">{confirmDialog.title}</h3>
            <p className="mt-2 text-sm leading-relaxed text-gray-600">{confirmDialog.message}</p>
            <div className="mt-5 flex justify-end gap-3">
              <button
                type="button"
                onClick={() => setConfirmDialog(null)}
                className="rounded-lg bg-gray-100 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-200"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={() => {
                  confirmDialog.onConfirm();
                  setConfirmDialog(null);
                }}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700"
              >
                {confirmDialog.confirmLabel}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Toast Notification */}
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}
    </div>
  );

  // ── Resources Tab ───────────────────────────────────────────────────

  function renderResources() {
    const vmUtil = (id: string) => vmUtilization?.items[id.toLowerCase()];
    const pgUtil = (id: string) => pgUtilization?.items[id.toLowerCase()];
    const vmConfigById = new Map(vmConfigs.map((c) => [c.vm_id.toLowerCase(), c]));
    const pgConfigById = new Map(pgConfigs.map((c) => [c.server_id.toLowerCase(), c]));
    const isStoppedVm = (state?: string | null) => state === "deallocated" || state === "stopped";
    const runningVMs = filteredAzureVMs.filter((v) => v.power_state === "running").length;
    const readyPG = filteredPGServers.filter((p) => p.state === "Ready").length;
    const unattachedDisks = filteredDisks.filter((d) => d.disk_state === "Unattached");
    const vmRows = filteredAzureVMs.filter((v) =>
      vmStateFilter === "all" ? true : vmStateFilter === "running" ? v.power_state === "running" : isStoppedVm(v.power_state),
    );
    const pgRows = filteredPGServers.filter((p) =>
      pgStateFilter === "all" ? true : pgStateFilter === "running" ? p.state === "Ready" : p.state === "Stopped",
    );
    const diskRows = filteredDisks.filter((d) =>
      diskStateFilter === "all" ? true : diskStateFilter === "unattached" ? d.disk_state === "Unattached" : d.disk_state !== "Unattached",
    );
    const show = (view: "vm" | "pg" | "storage" | "disk") => resourceView === "all" || resourceView === view;
    const focus = (view: typeof resourceView) => setResourceView((current) => (current === view ? "all" : view));
    const vmSort = tblSort("vms", "name", "asc");
    const storageSort = tblSort("storageAccounts", "name", "asc");
    const diskSort = tblSort("disks", "name", "asc");
    const pgServerSort = tblSort("pgServers", "name", "asc");
    const { items: pagedVMs, total: totalVMs, page: vmPage } = filterAndPaginate(
      vmRows, tbl("vms").search, tbl("vms").page,
      (v) => [v.name, v.resource_group, v.location, v.vm_size, v.power_state],
      vmSort,
      {
        name: (v) => v.name,
        resource_group: (v) => v.resource_group,
        location: (v) => v.location,
        vm_size: (v) => v.vm_size,
        power_state: (v) => v.power_state,
        cpu: (v) => vmUtil(v.id)?.cpu ?? null,
        memory: (v) => vmUtil(v.id)?.memory ?? null,
      },
    );
    const { items: pagedSA, total: totalSA, page: saPage } = filterAndPaginate(
      filteredStorageAccounts, tbl("storageAccounts").search, tbl("storageAccounts").page,
      (s) => [s.name, s.resource_group, s.location, s.kind, s.sku],
      storageSort,
      {
        name: (s) => s.name,
        resource_group: (s) => s.resource_group,
        location: (s) => s.location,
        kind: (s) => s.kind,
        sku: (s) => s.sku,
        access_tier: (s) => s.access_tier,
        provisioning_state: (s) => s.provisioning_state,
      },
    );
    const { items: pagedDisks, total: totalDisks, page: diskPage } = filterAndPaginate(
      diskRows, tbl("disks").search, tbl("disks").page,
      (d) => [d.name, d.resource_group, d.location, d.sku, d.os_type, d.disk_state],
      diskSort,
      {
        name: (d) => d.name,
        resource_group: (d) => d.resource_group,
        location: (d) => d.location,
        size_gb: (d) => d.size_gb || 0,
        sku: (d) => d.sku,
        os_type: (d) => d.os_type,
        disk_state: (d) => d.disk_state,
      },
    );
    return (
      <div className="space-y-6">
        {/* Subscription Filter */}
        <div className="flex items-center gap-4">
          <select
            value={subscriptionFilter}
            onChange={(e) => setSubscriptionFilter(e.target.value)}
            className="px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
          >
            <option value="">All Subscriptions</option>
            {scopedSubscriptions.map((s) => (
              <option key={s.subscription_id} value={s.subscription_id}>
                {s.subscription_name}
              </option>
            ))}
          </select>
        </div>

        {/* Resource Summary — each tile focuses its grid; click again for everything */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
          <MetricCard
            title="Total Resources"
            value={filteredAzureVMs.length + filteredStorageAccounts.length + filteredDisks.length + filteredPGServers.length}
            subtitle={resourceView === "all" ? "Showing every type" : "Click to show every type"}
            icon={Icons.database("text-blue-600")}
            tone="blue"
            onClick={() => setResourceView("all")}
            active={resourceView === "all"}
            actionLabel="Show every resource type"
          />
          <MetricCard
            title="Virtual Machines"
            value={filteredAzureVMs.length}
            subtitle={`${runningVMs} running · ${filteredAzureVMs.length - runningVMs} not running`}
            icon={Icons.server("text-green-600")}
            tone="green"
            onClick={() => focus("vm")}
            active={resourceView === "vm"}
            actionLabel="Show virtual machines"
          />
          <MetricCard
            title="PG Flex Servers"
            value={filteredPGServers.length}
            subtitle={`${readyPG} ready · ${filteredPGServers.length - readyPG} stopped or other`}
            icon={Icons.database("text-indigo-600")}
            tone="indigo"
            onClick={() => focus("pg")}
            active={resourceView === "pg"}
            actionLabel="Show PostgreSQL servers"
          />
          <MetricCard
            title="Storage Accounts"
            value={filteredStorageAccounts.length}
            subtitle={`${new Set(filteredStorageAccounts.map((a) => a.resource_group)).size} resource groups`}
            icon={Icons.database("text-purple-600")}
            tone="purple"
            onClick={() => focus("storage")}
            active={resourceView === "storage"}
            actionLabel="Show storage accounts"
          />
          <MetricCard
            title="Managed Disks"
            value={filteredDisks.length}
            subtitle={`${unattachedDisks.length} unattached (still billed)`}
            icon={Icons.database("text-orange-600")}
            tone="orange"
            onClick={() => focus("disk")}
            active={resourceView === "disk"}
            actionLabel="Show managed disks"
          />
        </div>

        {/* Sync Button + Last Sync Info */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className={`px-2 py-1 rounded-full text-xs font-medium ${
              dataSource === "db" ? "bg-blue-100 text-blue-700" : "bg-green-100 text-green-700"
            }`}>
              Source: {dataSource === "db" ? "Database" : "Azure Live"}
            </span>
            {lastSyncTime && (
              <span className="text-sm text-gray-500">
                Last synced: {formatDate(lastSyncTime)}
              </span>
            )}
            {!lastSyncTime && (
              <span className="text-sm text-yellow-600">
                Not synced yet — click Sync to load from Azure
              </span>
            )}
          </div>
          {canWrite && (
          <button
            onClick={() => syncResources.mutate(undefined, {
              onSuccess: () => showToast("Resources synced from Azure"),
              onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to sync resources", "error"),
            })}
            disabled={syncResources.isPending}
            className={buttonStyles.primary}
          >
            {Icons.refresh(syncResources.isPending ? "animate-spin" : "")}
            {syncResources.isPending ? "Syncing..." : "Sync from Azure"}
          </button>
          )}
        </div>

        {show("vm") && (
        <>
        {/* VMs Table */}
        <div className={gridStyles.shell}>
          <div className="px-6 py-4 border-b border-gray-200 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-lg font-semibold text-gray-800">Virtual Machines</h3>
              <p className="text-xs text-gray-500">
                CPU and memory from Azure Monitor{vmUtilization ? ` · updated ${formatRelativeTime(vmUtilization.generated_at)}` : " · loading…"} · click a VM for charts, disks, commands and admin
              </p>
            </div>
            <div className="flex items-center gap-3">
              <select value={vmStateFilter} onChange={(e) => setVmStateFilter(e.target.value as typeof vmStateFilter)} className={gridStyles.toolbarInput.replace("w-64", "w-36")} aria-label="Filter VMs by state">
                <option value="all">All states</option>
                <option value="running">Running</option>
                <option value="stopped">Stopped</option>
              </select>
              <SearchBar value={tbl("vms").search} onChange={(v) => setTblSearch("vms", v)} placeholder="Search VMs..." />
            </div>
          </div>
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}><SortableHeader label="Name" active={vmSort.key === "name"} direction={vmSort.direction} onClick={() => setTblSort("vms", "name", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Resource Group" active={vmSort.key === "resource_group"} direction={vmSort.direction} onClick={() => setTblSort("vms", "resource_group", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Location" active={vmSort.key === "location"} direction={vmSort.direction} onClick={() => setTblSort("vms", "location", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Size" active={vmSort.key === "vm_size"} direction={vmSort.direction} onClick={() => setTblSort("vms", "vm_size", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Status" active={vmSort.key === "power_state"} direction={vmSort.direction} onClick={() => setTblSort("vms", "power_state", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="CPU" active={vmSort.key === "cpu"} direction={vmSort.direction} onClick={() => setTblSort("vms", "cpu", "desc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Memory" active={vmSort.key === "memory"} direction={vmSort.direction} onClick={() => setTblSort("vms", "memory", "desc")} /></th>
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pagedVMs.map((vm) => {
                const open = clickableRow(() => setDetail({ kind: "vm", id: vm.id }), `Open ${vm.name}`);
                const target = { name: vm.name, resource_group: vm.resource_group || "", subscription_id: vm.subscription_id };
                const busy = powerPendingKey === `vm:${vm.subscription_id}:${vm.name}`;
                const configured = vmConfigs.some((c) => c.vm_id.toLowerCase() === vm.id.toLowerCase());
                return (
                <tr key={vm.id} {...open} className={`${gridStyles.row} ${open.className}`}>
                  <td className={gridStyles.strongCell}>
                    {vm.name}
                    {configured && <span className="ml-2 rounded bg-att-50 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-att-700 ring-1 ring-att-200">Monitored</span>}
                  </td>
                  <td className={gridStyles.cell}>{vm.resource_group}</td>
                  <td className={gridStyles.cell}>{vm.location}</td>
                  <td className={gridStyles.cell}>{vm.vm_size}</td>
                  <td className={gridStyles.cell}>
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                      vm.power_state === "running" ? "bg-green-100 text-green-700" :
                      vm.power_state === "deallocated" ? "bg-red-100 text-red-700" :
                      vm.power_state === "stopped" ? "bg-yellow-100 text-yellow-700" :
                      "bg-gray-100 text-gray-700"
                    }`}>
                      {vm.power_state || "Unknown"}
                    </span>
                  </td>
                  <td className={gridStyles.cell}>
                    <UtilizationBar title="CPU" value={vmUtil(vm.id)?.cpu} warning={vmConfigById.get(vm.id.toLowerCase())?.cpu_warning_threshold} critical={vmConfigById.get(vm.id.toLowerCase())?.cpu_critical_threshold} />
                  </td>
                  <td className={gridStyles.cell}>
                    <UtilizationBar title="Memory in use" value={vmUtil(vm.id)?.memory} warning={vmConfigById.get(vm.id.toLowerCase())?.memory_warning_threshold ?? 75} critical={vmConfigById.get(vm.id.toLowerCase())?.memory_critical_threshold} />
                  </td>
                  <td className={gridStyles.centerCell}>
                    <div className="flex justify-center gap-1">
                      {busy && Icons.refresh("animate-spin text-att-600")}
                      {canPowerVM && !busy && vm.power_state !== "running" && (
                        <GridActionButton onClick={() => runPower("vm", "start", target)} title="Start VM" tone="green">
                          {Icons.play()}
                        </GridActionButton>
                      )}
                      {canPowerVM && !busy && vm.power_state === "running" && (
                        <>
                          <GridActionButton onClick={() => runPower("vm", "stop", target)} title="Stop (deallocate) VM" tone="red">
                            {Icons.stop()}
                          </GridActionButton>
                          <GridActionButton onClick={() => runPower("vm", "restart", target)} title="Restart VM" tone="orange">
                            {Icons.restart()}
                          </GridActionButton>
                        </>
                      )}
                      {!canPowerVM && <span className="text-xs text-gray-400">View</span>}
                    </div>
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
          {totalVMs === 0 && (
            <div className="text-center py-12 text-gray-400">No VMs found. Click "Sync Resources" to load from Azure.</div>
          )}
          <TablePagination currentPage={vmPage} totalItems={totalVMs} onPageChange={(p) => setTblPage("vms", p)} />
        </div>
        </>
        )}

        {show("pg") && (
        <>
        {/* PG Flex Servers Table */}
        <div className={gridStyles.shell}>
          <div className="px-6 py-4 border-b border-gray-200 flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="text-lg font-semibold text-gray-800">PostgreSQL Flexible Servers</h3>
              <p className="text-xs text-gray-500">
                CPU, memory and storage from Azure Monitor{pgUtilization ? ` · updated ${formatRelativeTime(pgUtilization.generated_at)}` : " · loading…"}
              </p>
            </div>
            <div className="flex items-center gap-3">
              <select value={pgStateFilter} onChange={(e) => setPgStateFilter(e.target.value as typeof pgStateFilter)} className={gridStyles.toolbarInput.replace("w-64", "w-36")} aria-label="Filter servers by state">
                <option value="all">All states</option>
                <option value="running">Ready</option>
                <option value="stopped">Stopped</option>
              </select>
              <SearchBar value={tbl("pgServers").search} onChange={(v) => setTblSearch("pgServers", v)} placeholder="Search PG servers..." />
            </div>
          </div>
          {(() => {
            const { items: pagedPGServers, total: totalPGServers, page: pgSrvPage } = filterAndPaginate(
              pgRows, tbl("pgServers").search, tbl("pgServers").page,
              (s) => [s.name, s.resource_group, s.location, s.state, s.version, s.sku_name],
              pgServerSort,
              {
                name: (s) => s.name,
                resource_group: (s) => s.resource_group,
                location: (s) => s.location,
                state: (s) => s.state,
                version: (s) => s.version,
                sku_name: (s) => s.sku_name,
                cpu: (s) => pgUtil(s.id)?.cpu ?? null,
                memory: (s) => pgUtil(s.id)?.memory ?? null,
                storage: (s) => pgUtil(s.id)?.storage ?? null,
              },
            );
            return (
              <>
                <table className={gridStyles.table}>
                  <thead className={gridStyles.head}>
                    <tr>
                      <th className={gridStyles.headerCell}><SortableHeader label="Name" active={pgServerSort.key === "name"} direction={pgServerSort.direction} onClick={() => setTblSort("pgServers", "name", "asc")} /></th>
                      <th className={gridStyles.headerCell}><SortableHeader label="Resource Group" active={pgServerSort.key === "resource_group"} direction={pgServerSort.direction} onClick={() => setTblSort("pgServers", "resource_group", "asc")} /></th>
                      <th className={gridStyles.headerCell}><SortableHeader label="Location" active={pgServerSort.key === "location"} direction={pgServerSort.direction} onClick={() => setTblSort("pgServers", "location", "asc")} /></th>
                      <th className={gridStyles.headerCell}><SortableHeader label="State" active={pgServerSort.key === "state"} direction={pgServerSort.direction} onClick={() => setTblSort("pgServers", "state", "asc")} /></th>
                      <th className={gridStyles.headerCell}><SortableHeader label="Version" active={pgServerSort.key === "version"} direction={pgServerSort.direction} onClick={() => setTblSort("pgServers", "version", "asc")} /></th>
                      <th className={gridStyles.headerCell}><SortableHeader label="SKU" active={pgServerSort.key === "sku_name"} direction={pgServerSort.direction} onClick={() => setTblSort("pgServers", "sku_name", "asc")} /></th>
                      <th className={gridStyles.headerCell}><SortableHeader label="CPU" active={pgServerSort.key === "cpu"} direction={pgServerSort.direction} onClick={() => setTblSort("pgServers", "cpu", "desc")} /></th>
                      <th className={gridStyles.headerCell}><SortableHeader label="Memory" active={pgServerSort.key === "memory"} direction={pgServerSort.direction} onClick={() => setTblSort("pgServers", "memory", "desc")} /></th>
                      <th className={gridStyles.headerCell}><SortableHeader label="Storage" active={pgServerSort.key === "storage"} direction={pgServerSort.direction} onClick={() => setTblSort("pgServers", "storage", "desc")} /></th>
                      <th className={gridStyles.headerCellCenter}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pagedPGServers.map((server) => {
                      const open = clickableRow(() => setDetail({ kind: "pg-server", id: server.id }), `Open ${server.name}`);
                      const target = { name: server.name, resource_group: server.resource_group, subscription_id: server.subscription_id };
                      const busy = powerPendingKey === `pg:${server.subscription_id}:${server.name}`;
                      return (
                      <tr key={server.id} {...open} className={`${gridStyles.row} ${open.className}`}>
                        <td className={gridStyles.strongCell}>{server.name}</td>
                        <td className={gridStyles.cell}>{server.resource_group}</td>
                        <td className={gridStyles.cell}>{server.location}</td>
                        <td className={gridStyles.cell}>
                          <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                            server.state === "Ready" ? "bg-green-100 text-green-700" :
                            server.state === "Stopped" ? "bg-red-100 text-red-700" :
                            "bg-yellow-100 text-yellow-700"
                          }`}>{server.state || "Unknown"}</span>
                        </td>
                        <td className={gridStyles.cell}>{server.version || "—"}</td>
                        <td className={gridStyles.cell}>{server.sku_name || "—"}</td>
                        <td className={gridStyles.cell}>
                          <UtilizationBar title="CPU" value={pgUtil(server.id)?.cpu} warning={pgConfigById.get(server.id.toLowerCase())?.cpu_warning_threshold} critical={pgConfigById.get(server.id.toLowerCase())?.cpu_critical_threshold} />
                        </td>
                        <td className={gridStyles.cell}>
                          <UtilizationBar title="Memory" value={pgUtil(server.id)?.memory} warning={pgConfigById.get(server.id.toLowerCase())?.memory_warning_threshold ?? 75} critical={pgConfigById.get(server.id.toLowerCase())?.memory_critical_threshold} />
                        </td>
                        <td className={gridStyles.cell}>
                          <UtilizationBar title="Storage used" value={pgUtil(server.id)?.storage} warning={pgConfigById.get(server.id.toLowerCase())?.storage_warning_threshold ?? 80} critical={pgConfigById.get(server.id.toLowerCase())?.storage_critical_threshold ?? 95} />
                        </td>
                        <td className={gridStyles.centerCell}>
                          <div className="flex justify-center gap-1">
                            {busy && Icons.refresh("animate-spin text-att-600")}
                            {canPowerPG && !busy && server.state === "Stopped" && (
                              <GridActionButton onClick={() => runPower("pg", "start", target)} title="Start PG Server" tone="green">
                                {Icons.play()}
                              </GridActionButton>
                            )}
                            {canPowerPG && !busy && server.state === "Ready" && (
                              <>
                                <GridActionButton onClick={() => runPower("pg", "stop", target)} title="Stop PG Server" tone="red">
                                  {Icons.stop()}
                                </GridActionButton>
                                <GridActionButton onClick={() => runPower("pg", "restart", target)} title="Restart PG Server" tone="orange">
                                  {Icons.restart()}
                                </GridActionButton>
                              </>
                            )}
                            {!canPowerPG && <span className="text-xs text-gray-400">View</span>}
                          </div>
                        </td>
                      </tr>
                      );
                    })}
                  </tbody>
                </table>
                {totalPGServers === 0 && (
                  <div className="text-center py-12 text-gray-400">No PostgreSQL Flexible Servers found. Click &quot;Sync Resources&quot; to load from Azure.</div>
                )}
                <TablePagination currentPage={pgSrvPage} totalItems={totalPGServers} onPageChange={(p) => setTblPage("pgServers", p)} />
              </>
            );
          })()}
        </div>
        </>
        )}

        {show("storage") && (
        <>
        {/* Storage Accounts Table */}
        <div className={gridStyles.shell}>
          <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
            <h3 className="text-lg font-semibold text-gray-800">Storage Accounts</h3>
            <SearchBar value={tbl("storageAccounts").search} onChange={(v) => setTblSearch("storageAccounts", v)} placeholder="Search storage accounts..." />
          </div>
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}><SortableHeader label="Name" active={storageSort.key === "name"} direction={storageSort.direction} onClick={() => setTblSort("storageAccounts", "name", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Resource Group" active={storageSort.key === "resource_group"} direction={storageSort.direction} onClick={() => setTblSort("storageAccounts", "resource_group", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Location" active={storageSort.key === "location"} direction={storageSort.direction} onClick={() => setTblSort("storageAccounts", "location", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Kind" active={storageSort.key === "kind"} direction={storageSort.direction} onClick={() => setTblSort("storageAccounts", "kind", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="SKU" active={storageSort.key === "sku"} direction={storageSort.direction} onClick={() => setTblSort("storageAccounts", "sku", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Access Tier" active={storageSort.key === "access_tier"} direction={storageSort.direction} onClick={() => setTblSort("storageAccounts", "access_tier", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Status" active={storageSort.key === "provisioning_state"} direction={storageSort.direction} onClick={() => setTblSort("storageAccounts", "provisioning_state", "asc")} /></th>
              </tr>
            </thead>
            <tbody>
              {pagedSA.map((sa) => (
                <tr key={sa.id} {...clickableRow(() => setDetail({ kind: "storage-account", id: sa.id }), `Open ${sa.name}`)} className={`${gridStyles.row} cursor-pointer focus:outline-none focus-visible:bg-att-50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-att-300`}>
                  <td className={gridStyles.strongCell}>{sa.name}</td>
                  <td className={gridStyles.cell}>{sa.resource_group}</td>
                  <td className={gridStyles.cell}>{sa.location}</td>
                  <td className={gridStyles.cell}>{sa.kind || "-"}</td>
                  <td className={gridStyles.cell}>{sa.sku || "-"}</td>
                  <td className={gridStyles.cell}>{sa.access_tier || "-"}</td>
                  <td className={gridStyles.cell}>
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                      sa.provisioning_state === "Succeeded" ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-700"
                    }`}>
                      {sa.provisioning_state || "Unknown"}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {totalSA === 0 && (
            <div className="text-center py-12 text-gray-400">No storage accounts found. Click "Sync Resources" to load from Azure.</div>
          )}
          <TablePagination currentPage={saPage} totalItems={totalSA} onPageChange={(p) => setTblPage("storageAccounts", p)} />
        </div>
        </>
        )}

        {show("disk") && (
        <>
        {/* Managed Disks Table with Usage Bars */}
        <div className={gridStyles.shell}>
          <div className="px-6 py-4 border-b border-gray-200 flex flex-wrap items-center justify-between gap-3">
            <h3 className="text-lg font-semibold text-gray-800">Managed Disks</h3>
            <div className="flex items-center gap-3">
              <select value={diskStateFilter} onChange={(e) => setDiskStateFilter(e.target.value as typeof diskStateFilter)} className={gridStyles.toolbarInput.replace("w-64", "w-40")} aria-label="Filter disks by state">
                <option value="all">All disks</option>
                <option value="attached">Attached</option>
                <option value="unattached">Unattached</option>
              </select>
              <SearchBar value={tbl("disks").search} onChange={(v) => setTblSearch("disks", v)} placeholder="Search disks..." />
            </div>
          </div>
          {(() => {
            const maxDiskSize = Math.max(...disks.map(d => d.size_gb || 0), 1);
            return (
              <table className={gridStyles.table}>
                <thead className={gridStyles.head}>
                  <tr>
                    <th className={gridStyles.headerCell}><SortableHeader label="Name" active={diskSort.key === "name"} direction={diskSort.direction} onClick={() => setTblSort("disks", "name", "asc")} /></th>
                    <th className={gridStyles.headerCell}><SortableHeader label="Resource Group" active={diskSort.key === "resource_group"} direction={diskSort.direction} onClick={() => setTblSort("disks", "resource_group", "asc")} /></th>
                    <th className={gridStyles.headerCell}><SortableHeader label="Location" active={diskSort.key === "location"} direction={diskSort.direction} onClick={() => setTblSort("disks", "location", "asc")} /></th>
                    <th className={gridStyles.headerCell}><SortableHeader label="Capacity" active={diskSort.key === "size_gb"} direction={diskSort.direction} onClick={() => setTblSort("disks", "size_gb", "desc")} /></th>
                    <th className={gridStyles.headerCell}><SortableHeader label="SKU" active={diskSort.key === "sku"} direction={diskSort.direction} onClick={() => setTblSort("disks", "sku", "asc")} /></th>
                    <th className={gridStyles.headerCell}><SortableHeader label="OS Type" active={diskSort.key === "os_type"} direction={diskSort.direction} onClick={() => setTblSort("disks", "os_type", "asc")} /></th>
                    <th className={gridStyles.headerCell}><SortableHeader label="State" active={diskSort.key === "disk_state"} direction={diskSort.direction} onClick={() => setTblSort("disks", "disk_state", "asc")} /></th>
                    {canWrite && <th className={gridStyles.headerCellCenter}>Actions</th>}
                  </tr>
                </thead>
                <tbody>
                  {pagedDisks.map((disk) => {
                    const totalGB = disk.size_gb || 0;
                    const pct = maxDiskSize > 0 ? (totalGB / maxDiskSize) * 100 : 0;
                    // Color: <50% green, 50-80% blue, >80% red-orange
                    const barColor = pct > 80 ? "#ef4444" : pct > 50 ? "#3b82f6" : "#22c55e";
                    return (
                      <tr key={disk.id} {...clickableRow(() => setDetail({ kind: "disk", id: disk.id }), `Open ${disk.name}`)} className={`${gridStyles.row} cursor-pointer focus:outline-none focus-visible:bg-att-50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-att-300`}>
                        <td className={gridStyles.strongCell} title={disk.name}>{disk.name && disk.name.length > 30 ? disk.name.slice(0, 30) + "..." : disk.name}</td>
                        <td className={gridStyles.cell} title={disk.resource_group}>{disk.resource_group && disk.resource_group.length > 35 ? disk.resource_group.slice(0, 35) + "..." : disk.resource_group}</td>
                        <td className={gridStyles.cell}>{disk.location}</td>
                        <td className={gridStyles.cell}>
                          <div className="flex flex-col gap-1">
                            <div className="w-full bg-gray-200 rounded-full h-5 overflow-hidden relative" title={`${totalGB} GB`}>
                              <div
                                className="h-full rounded-full transition-all duration-300"
                                style={{ width: `${pct}%`, backgroundColor: barColor }}
                              />
                              <span className="absolute inset-0 flex items-center justify-center text-[10px] font-semibold text-gray-800">
                                {totalGB} GB
                              </span>
                            </div>
                            <div className="flex items-center justify-between text-[10px] text-gray-500">
                              <span>Total: <b>{totalGB}</b> GB</span>
                              <span className="text-gray-400">{pct.toFixed(0)}% of max</span>
                            </div>
                          </div>
                        </td>
                        <td className={gridStyles.cell}>{disk.sku || "-"}</td>
                        <td className={gridStyles.cell}>{disk.os_type || "-"}</td>
                        <td className={gridStyles.cell}>
                          <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                            disk.disk_state === "Attached" ? "bg-green-100 text-green-700" :
                            disk.disk_state === "Unattached" ? "bg-yellow-100 text-yellow-700" :
                            "bg-gray-100 text-gray-700"
                          }`}>
                            {disk.disk_state || "Unknown"}
                          </span>
                        </td>
                        {canWrite && (
                          <td className={gridStyles.centerCell}>
                            {disk.disk_state === "Unattached" && canCleanupResources && (
                              <GridActionButton
                                onClick={() => requestDeleteDisk(disk)}
                                disabled={diskActionTarget === disk.name}
                                title="Delete unattached disk"
                                tone="red"
                              >
                                {diskActionTarget === disk.name && deleteDiskMut.isPending
                                  ? Icons.refresh("animate-spin")
                                  : Icons.trash()}
                              </GridActionButton>
                            )}
                          </td>
                        )}
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            );
          })()}
          {totalDisks === 0 && (
            <div className="text-center py-12 text-gray-400">No managed disks found. Click &quot;Sync Resources&quot; to load from Azure.</div>
          )}
          <TablePagination currentPage={diskPage} totalItems={totalDisks} onPageChange={(p) => setTblPage("disks", p)} />
        </div>
        </>
        )}

        {/* ── Resource Usage Charts ──────────────────────────────── */}
        {(disks.length > 0 || storageAccounts.length > 0) && (resourceView === "all" || resourceView === "disk" || resourceView === "storage") && (
          <div>
            <h3 className="text-lg font-semibold text-gray-800 mb-4">Resource Usage Overview</h3>
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

              {/* Disk Size Distribution */}
              {disks.length > 0 && (
                <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                  <h4 className="text-sm font-semibold text-gray-700 mb-4">Disk Size Distribution (GB)</h4>
                  <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={disks.slice(0, 15).map(d => ({ name: d.name?.length > 12 ? d.name.slice(0, 12) + '…' : d.name, size: d.size_gb || 0 }))}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" angle={-45} textAnchor="end" height={80} tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 12 }} />
                      <Tooltip formatter={(value: number) => [`${value} GB`, 'Size']} />
                      <Bar dataKey="size" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}

              {/* Disk SKU Breakdown */}
              {disks.length > 0 && (() => {
                const skuCounts: Record<string, number> = {};
                disks.forEach(d => { const s = d.sku || "Unknown"; skuCounts[s] = (skuCounts[s] || 0) + 1; });
                const skuData = Object.entries(skuCounts).map(([name, value]) => ({ name, value }));
                return (
                  <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                    <h4 className="text-sm font-semibold text-gray-700 mb-4">Disk SKU Breakdown</h4>
                    <ResponsiveContainer width="100%" height={300}>
                      <PieChart>
                        <Pie data={skuData} cx="50%" cy="50%" outerRadius={100} dataKey="value" nameKey="name" label={({ name, percent }) => `${name} (${(percent * 100).toFixed(0)}%)`}>
                          {skuData.map((_, index) => (
                            <Cell key={`sku-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                          ))}
                        </Pie>
                        <Tooltip />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                );
              })()}

              {/* Disk State Distribution */}
              {disks.length > 0 && (() => {
                const stateCounts: Record<string, number> = {};
                disks.forEach(d => { const s = d.disk_state || "Unknown"; stateCounts[s] = (stateCounts[s] || 0) + 1; });
                const stateData = Object.entries(stateCounts).map(([name, value]) => ({ name, value }));
                return (
                  <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                    <h4 className="text-sm font-semibold text-gray-700 mb-4">Disk State Distribution</h4>
                    <ResponsiveContainer width="100%" height={300}>
                      <PieChart>
                        <Pie data={stateData} cx="50%" cy="50%" outerRadius={100} dataKey="value" nameKey="name" label={({ name, percent }) => `${name} (${(percent * 100).toFixed(0)}%)`}>
                          {stateData.map((_, index) => (
                            <Cell key={`state-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                          ))}
                        </Pie>
                        <Tooltip />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                );
              })()}

              {/* Storage Account SKU Distribution */}
              {storageAccounts.length > 0 && (() => {
                const skuCounts: Record<string, number> = {};
                storageAccounts.forEach(sa => { const s = sa.sku || "Unknown"; skuCounts[s] = (skuCounts[s] || 0) + 1; });
                const skuData = Object.entries(skuCounts).map(([name, value]) => ({ name, value }));
                return (
                  <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
                    <h4 className="text-sm font-semibold text-gray-700 mb-4">Storage Account SKU Distribution</h4>
                    <ResponsiveContainer width="100%" height={300}>
                      <PieChart>
                        <Pie data={skuData} cx="50%" cy="50%" outerRadius={100} dataKey="value" nameKey="name" label={({ name, percent }) => `${name} (${(percent * 100).toFixed(0)}%)`}>
                          {skuData.map((_, index) => (
                            <Cell key={`sa-sku-${index}`} fill={CHART_COLORS[index % CHART_COLORS.length]} />
                          ))}
                        </Pie>
                        <Tooltip />
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                );
              })()}

            </div>
          </div>
        )}
      </div>
    );
  }

  // ── Scheduler Tab ───────────────────────────────────────────────────

  function saveAlertSchedule() {
    const payload: CreateAlertScheduleConfigRequest = {
      ...alertScheduleFormData,
      name: alertScheduleFormData.name.trim(),
      description: alertScheduleFormData.description?.trim() || "",
      cron_expression:
        alertScheduleFormData.schedule_type === "cron"
          ? alertScheduleFormData.cron_expression?.trim() || ""
          : "",
      digest_recipients: parseEmailList(alertScheduleRecipientsInput),
    };

    if (!payload.name) {
      showToast("Schedule name is required", "error");
      return;
    }

    if (payload.schedule_type === "cron" && !payload.cron_expression) {
      showToast("Cron expression is required for cron schedules", "error");
      return;
    }

    if (editingAlertSchedule) {
      const updatePayload: UpdateAlertScheduleConfigRequest = { ...payload };
      updateAlertScheduleMut.mutate(
        { configId: editingAlertSchedule.id, data: updatePayload },
        {
          onSuccess: () => {
            showToast(`Schedule \"${payload.name}\" updated`);
            resetAlertScheduleEditor();
          },
          onError: (error: unknown) => toastError(error, "Failed to update schedule"),
        },
      );
      return;
    }

    createAlertScheduleMut.mutate(payload, {
      onSuccess: () => {
        showToast(`Schedule \"${payload.name}\" created`);
        resetAlertScheduleEditor();
      },
      onError: (error: unknown) => toastError(error, "Failed to create schedule"),
    });
  }

  function renderScheduler() {
    const notificationSort = tblSort("notifHistory", "sent_at", "desc");
    const scheduleSort = tblSort("alertSchedules", "name", "asc");
    const { items: pagedSchedules, total: totalSchedules, page: schedulePage } = filterAndPaginate(
      alertScheduleConfigs,
      tbl("alertSchedules").search,
      tbl("alertSchedules").page,
      (schedule) => [
        schedule.name,
        schedule.description,
        schedule.schedule_type,
        schedule.digest_time_utc,
        schedule.is_enabled ? "enabled" : "disabled",
      ],
      scheduleSort,
      {
        name: (schedule) => schedule.name,
        schedule_type: (schedule) => schedule.schedule_type,
        interval_minutes: (schedule) => schedule.interval_minutes,
        digest_time_utc: (schedule) => schedule.digest_time_utc,
        is_enabled: (schedule) => schedule.is_enabled,
        next_run_at: (schedule) => schedule.next_run_at || "",
      },
    );

    return (
      <div className="space-y-6">
        <div className="rounded-2xl border border-att-100 bg-white p-6 shadow-sm">
          <div className="mb-4 flex items-start justify-between gap-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-800">Alert Schedule Configuration</h3>
              <p className="mt-1 text-sm text-gray-500">
                These schedules are persisted in the database for infra alert checks and daily digest planning.
              </p>
            </div>
            {canWrite && (
            <button type="button" onClick={openNewAlertScheduleEditor} className={buttonStyles.primary}>
              {Icons.plus()}
              Add Schedule
            </button>
            )}
          </div>

          {canWrite && showAlertScheduleEditor && (
            <div className="mb-6 rounded-2xl border border-att-100 bg-att-50/40 p-5">
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <h4 className="text-base font-semibold text-gray-800">
                    {editingAlertSchedule ? `Edit ${editingAlertSchedule.name}` : "Create Alert Schedule"}
                  </h4>
                  <p className="text-sm text-gray-500">
                    Configure which infra alert checks run and when the digest should be prepared.
                  </p>
                </div>
                <button type="button" onClick={resetAlertScheduleEditor} className={buttonStyles.subtle}>
                  Cancel
                </button>
              </div>

              <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
                <label className="space-y-2 text-sm text-gray-700">
                  <span className="font-medium text-gray-800">Name</span>
                  <input
                    type="text"
                    value={alertScheduleFormData.name}
                    onChange={(event) =>
                      setAlertScheduleFormData((prev) => ({ ...prev, name: event.target.value }))
                    }
                    className={`${gridStyles.toolbarInput} w-full`}
                    placeholder="Daily Infra Alert Checks"
                  />
                </label>

                <label className="space-y-2 text-sm text-gray-700 md:col-span-2">
                  <span className="font-medium text-gray-800">Description</span>
                  <input
                    type="text"
                    value={alertScheduleFormData.description || ""}
                    onChange={(event) =>
                      setAlertScheduleFormData((prev) => ({ ...prev, description: event.target.value }))
                    }
                    className={`${gridStyles.toolbarInput} w-full`}
                    placeholder="Runs alert checks and digest preparation"
                  />
                </label>

                <label className="space-y-2 text-sm text-gray-700">
                  <span className="font-medium text-gray-800">Status</span>
                  <select
                    value={alertScheduleFormData.is_enabled ? "enabled" : "disabled"}
                    onChange={(event) =>
                      setAlertScheduleFormData((prev) => ({
                        ...prev,
                        is_enabled: event.target.value === "enabled",
                      }))
                    }
                    className={`${gridStyles.toolbarInput} w-full`}
                  >
                    <option value="enabled">Enabled</option>
                    <option value="disabled">Disabled</option>
                  </select>
                </label>

                <label className="space-y-2 text-sm text-gray-700">
                  <span className="font-medium text-gray-800">Schedule Type</span>
                  <select
                    value={alertScheduleFormData.schedule_type}
                    onChange={(event) =>
                      setAlertScheduleFormData((prev) => ({
                        ...prev,
                        schedule_type: event.target.value as "interval" | "cron",
                      }))
                    }
                    className={`${gridStyles.toolbarInput} w-full`}
                  >
                    <option value="interval">Interval</option>
                    <option value="cron">Cron</option>
                  </select>
                </label>

                {alertScheduleFormData.schedule_type === "interval" ? (
                  <label className="space-y-2 text-sm text-gray-700">
                    <span className="font-medium text-gray-800">Interval Minutes</span>
                    <input
                      type="number"
                      min={1}
                      value={alertScheduleFormData.interval_minutes}
                      onChange={(event) =>
                        setAlertScheduleFormData((prev) => ({
                          ...prev,
                          interval_minutes: Number(event.target.value) || 1,
                        }))
                      }
                      className={`${gridStyles.toolbarInput} w-full`}
                    />
                  </label>
                ) : (
                  <label className="space-y-2 text-sm text-gray-700 md:col-span-2">
                    <span className="font-medium text-gray-800">Cron Expression</span>
                    <input
                      type="text"
                      value={alertScheduleFormData.cron_expression || ""}
                      onChange={(event) =>
                        setAlertScheduleFormData((prev) => ({
                          ...prev,
                          cron_expression: event.target.value,
                        }))
                      }
                      className={`${gridStyles.toolbarInput} w-full font-mono`}
                      placeholder="0 8 * * *"
                    />
                    <span className="flex flex-wrap items-center gap-1.5 text-xs text-gray-500">
                      <span>Standard 5-field cron, UTC.</span>
                      {[
                        ["Daily 08:00", "0 8 * * *"],
                        ["Weekdays 08:00", "0 8 * * 1-5"],
                        ["Every 2 hours", "0 */2 * * *"],
                        ["Hourly", "0 * * * *"],
                      ].map(([label, expression]) => (
                        <button
                          key={expression}
                          type="button"
                          onClick={() => setAlertScheduleFormData((prev) => ({ ...prev, cron_expression: expression }))}
                          className="rounded-full border border-att-200 bg-white px-2 py-0.5 font-medium text-gray-600 hover:bg-att-50"
                        >
                          {label}
                        </button>
                      ))}
                    </span>
                  </label>
                )}

                {alertScheduleFormData.schedule_type === "interval" && alertScheduleFormData.send_daily_digest && (
                  <label className="space-y-2 text-sm text-gray-700">
                    <span className="font-medium text-gray-800">Digest Time (UTC)</span>
                    <input
                      type="time"
                      value={alertScheduleFormData.digest_time_utc}
                      onChange={(event) =>
                        setAlertScheduleFormData((prev) => ({ ...prev, digest_time_utc: event.target.value }))
                      }
                      className={`${gridStyles.toolbarInput} w-full`}
                    />
                    <span className="block text-xs text-gray-500">Sent once a day, on the first run at or after this time.</span>
                  </label>
                )}

                <label className="space-y-2 text-sm text-gray-700 md:col-span-2 xl:col-span-4">
                  <span className="font-medium text-gray-800">
                    Digest Recipients{" "}
                    <span className="font-normal text-gray-500">— empty sends the digest to every alert configuration's recipients</span>
                  </span>
                  <textarea
                    value={alertScheduleRecipientsInput}
                    onChange={(event) => setAlertScheduleRecipientsInput(event.target.value)}
                    className={`${gridStyles.toolbarInput} min-h-[88px] w-full resize-y py-3`}
                    placeholder="name@att.com, team@att.com"
                  />
                </label>
              </div>

              <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                {[
                  { key: "check_vm_thresholds", label: "Run VM threshold checks", hint: "CPU, memory and disk I/O from Azure Monitor" },
                  { key: "check_pg_thresholds", label: "Run PG threshold checks", hint: "CPU, memory and storage" },
                  { key: "check_expiry_alerts", label: "Run expiry checks", hint: "Raise, escalate and auto-resolve expiry alerts" },
                  { key: "send_daily_digest", label: "Send daily digest", hint: "At most once per day per schedule" },
                  { key: "check_storage_thresholds", label: "Run storage checks", hint: "Not evaluated yet", unsupported: true },
                  { key: "check_disk_thresholds", label: "Run disk checks", hint: "Not evaluated yet", unsupported: true },
                ].map((item) => {
                  const checked = Boolean(alertScheduleFormData[item.key as keyof CreateAlertScheduleConfigRequest]);
                  // A check that is already on stays editable so it can be switched off.
                  const locked = item.unsupported && !checked;
                  return (
                    <label
                      key={item.key}
                      className={`flex items-start gap-3 rounded-xl border border-att-100 bg-white px-4 py-3 text-sm text-gray-700 ${locked ? "opacity-60" : "cursor-pointer"}`}
                    >
                      <input
                        type="checkbox"
                        checked={checked}
                        disabled={locked}
                        onChange={(event) =>
                          setAlertScheduleFormData((prev) => ({
                            ...prev,
                            [item.key]: event.target.checked,
                          }))
                        }
                        className="mt-0.5 h-4 w-4 rounded border-att-300 text-att-600 focus:ring-att-500"
                      />
                      <span>
                        <span className="block font-medium text-gray-800">{item.label}</span>
                        <span className={`block text-xs ${item.unsupported ? "text-amber-700" : "text-gray-500"}`}>{item.hint}</span>
                      </span>
                    </label>
                  );
                })}
              </div>

              <div className="mt-5 flex items-center justify-end gap-3">
                <button type="button" onClick={resetAlertScheduleEditor} className={buttonStyles.subtle}>
                  Cancel
                </button>
                <button
                  type="button"
                  onClick={saveAlertSchedule}
                  disabled={createAlertScheduleMut.isPending || updateAlertScheduleMut.isPending}
                  className={buttonStyles.primary}
                >
                  {(createAlertScheduleMut.isPending || updateAlertScheduleMut.isPending)
                    ? Icons.refresh("animate-spin")
                    : Icons.check()}
                  {editingAlertSchedule ? "Save Changes" : "Create Schedule"}
                </button>
              </div>
            </div>
          )}

          <div className={gridStyles.shell}>
            <div className={gridStyles.panelHeader}>
              <div>
                <h4 className="text-base font-semibold text-gray-800">Persisted Alert Schedules</h4>
                <p className="text-sm text-gray-500">
                  Showing {pagedSchedules.length} of {totalSchedules} saved schedules
                </p>
              </div>
              <SearchBar
                value={tbl("alertSchedules").search}
                onChange={(value) => setTblSearch("alertSchedules", value)}
                placeholder="Search schedules..."
              />
            </div>

            <table className={gridStyles.table}>
              <thead className={gridStyles.head}>
                <tr>
                  <th className={gridStyles.headerCell}>
                    <SortableHeader
                      label="Name"
                      active={scheduleSort.key === "name"}
                      direction={scheduleSort.direction}
                      onClick={() => setTblSort("alertSchedules", "name", "asc")}
                    />
                  </th>
                  <th className={gridStyles.headerCell}>
                    <SortableHeader
                      label="Type"
                      active={scheduleSort.key === "schedule_type"}
                      direction={scheduleSort.direction}
                      onClick={() => setTblSort("alertSchedules", "schedule_type", "asc")}
                    />
                  </th>
                  <th className={gridStyles.headerCell}>Checks</th>
                  <th className={gridStyles.headerCell}>
                    <SortableHeader
                      label="Status"
                      active={scheduleSort.key === "is_enabled"}
                      direction={scheduleSort.direction}
                      onClick={() => setTblSort("alertSchedules", "is_enabled", "desc")}
                    />
                  </th>
                  <th className={gridStyles.headerCell}>
                    <SortableHeader
                      label="Next Run"
                      active={scheduleSort.key === "next_run_at"}
                      direction={scheduleSort.direction}
                      onClick={() => setTblSort("alertSchedules", "next_run_at", "asc")}
                    />
                  </th>
                  <th className={gridStyles.headerCellCenter}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pagedSchedules.map((schedule) => {
                  const enabledChecks = [
                    schedule.check_vm_thresholds ? "VM" : null,
                    schedule.check_pg_thresholds ? "PG" : null,
                    schedule.check_expiry_alerts ? "Expiry" : null,
                    schedule.check_storage_thresholds ? "Storage (not evaluated)" : null,
                    schedule.check_disk_thresholds ? "Disk (not evaluated)" : null,
                    schedule.send_daily_digest ? "Digest" : null,
                  ].filter(Boolean);

                  const open = clickableRow(() => setDetail({ kind: "schedule", id: schedule.id }), `Open schedule ${schedule.name}`);
                  return (
                    <tr key={schedule.id} {...open} className={`${gridStyles.row} ${open.className}`}>
                      <td className={gridStyles.strongCell}>
                        <div>
                          <div>{schedule.name}</div>
                          {schedule.description && (
                            <div className="mt-1 text-xs font-normal text-gray-500">{schedule.description}</div>
                          )}
                        </div>
                      </td>
                      <td className={gridStyles.cell}>
                        <div>{describeSchedule(schedule.schedule_type, schedule.interval_minutes, schedule.cron_expression)}</div>
                        {schedule.schedule_type === "cron" && <div className="font-mono text-xs text-gray-400">{schedule.cron_expression}</div>}
                      </td>
                      <td className={gridStyles.cell}>{enabledChecks.join(", ") || "No checks selected"}</td>
                      <td className={gridStyles.cell}>
                        <span
                          className={`rounded-full px-2 py-1 text-xs font-medium ${
                            schedule.is_enabled ? "bg-green-100 text-green-700" : "bg-slate-100 text-slate-600"
                          }`}
                        >
                          {schedule.is_enabled ? "Enabled" : "Disabled"}
                        </span>
                      </td>
                      <td className={gridStyles.cell}>
                        <div>{schedule.next_run_at ? formatDate(schedule.next_run_at) : schedule.is_enabled ? "Scheduling…" : "Paused"}</div>
                        <div className="text-xs text-gray-400">
                          {schedule.last_run_at ? `Last run ${formatRelativeTime(schedule.last_run_at)}` : "Not run yet"}
                        </div>
                      </td>
                      <td className={gridStyles.centerCell}>
                        <div className="flex items-center justify-center gap-1">
                          {canWrite && (
                          <GridActionButton
                            onClick={() => openEditAlertScheduleEditor(schedule)}
                            title="Edit Schedule"
                            tone="blue"
                          >
                            {Icons.edit()}
                          </GridActionButton>
                          )}
                          {canWrite && (
                          <GridActionButton
                            onClick={() => requestDeleteSchedule(schedule)}
                            disabled={deleteAlertScheduleMut.isPending}
                            title="Delete Schedule"
                            tone="red"
                          >
                            {Icons.trash()}
                          </GridActionButton>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>

            {totalSchedules === 0 && (
              <div className="py-12 text-center text-gray-400">No persisted alert schedules found</div>
            )}

            <TablePagination
              currentPage={schedulePage}
              totalItems={totalSchedules}
              onPageChange={(page) => setTblPage("alertSchedules", page)}
            />
          </div>
        </div>

        {/* Scheduler Status */}
        <div className="rounded-2xl border border-att-100 bg-white p-6 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <div>
              <h3 className="text-lg font-semibold text-gray-800">Runtime Scheduler Status</h3>
              <p className="mt-1 text-sm text-gray-500">
                Platform-managed runtime jobs currently loaded in the background scheduler.
              </p>
            </div>
            <div className="flex items-center gap-3">
              <span className={`px-3 py-1 rounded-full text-sm font-medium ${
                schedulerStatus?.scheduler_running ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
              }`}>
                {schedulerStatus?.scheduler_running ? "Running" : "Stopped"}
              </span>
              {canWrite && schedulerStatus?.scheduler_running ? (
                <button
                  onClick={() => stopSchedulerMut.mutate(undefined, {
                    onSuccess: () => showToast("Scheduler stopped successfully"),
                    onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to stop scheduler", "error"),
                  })}
                  disabled={stopSchedulerMut.isPending}
                  className={buttonStyles.redSoft}
                >
                  {stopSchedulerMut.isPending ? Icons.refresh("animate-spin") : Icons.stop()}
                  {stopSchedulerMut.isPending ? "Stopping..." : "Stop Scheduler"}
                </button>
              ) : canWrite && !schedulerStatus?.scheduler_running ? (
                <button
                  onClick={() => startSchedulerMut.mutate(undefined, {
                    onSuccess: () => showToast("Scheduler started successfully"),
                    onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to start scheduler", "error"),
                  })}
                  disabled={startSchedulerMut.isPending}
                  className={buttonStyles.greenSoft}
                >
                  {startSchedulerMut.isPending ? Icons.refresh("animate-spin") : Icons.play()}
                  {startSchedulerMut.isPending ? "Starting..." : "Start Scheduler"}
                </button>
              ) : null}
            </div>
          </div>
          
          {canWrite && (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4 mb-6">
            <ActionTileButton
              onClick={() => triggerVMCheck.mutate(undefined, {
                onSuccess: (result) => showToast(checkSummary("VM", result as unknown as Record<string, unknown>)),
                onError: (e: unknown) => toastError(e, "VM check failed"),
              })}
              disabled={triggerVMCheck.isPending}
              tone="blue"
              title="Run VM Check"
              icon={triggerVMCheck.isPending ? Icons.refresh("animate-spin") : Icons.play()}
            />
            <ActionTileButton
              onClick={() => triggerPGCheck.mutate(undefined, {
                onSuccess: (result) => showToast(checkSummary("PG", result as unknown as Record<string, unknown>)),
                onError: (e: unknown) => toastError(e, "PG check failed"),
              })}
              disabled={triggerPGCheck.isPending}
              tone="purple"
              title="Run PG Check"
              icon={triggerPGCheck.isPending ? Icons.refresh("animate-spin") : Icons.database()}
            />
            <ActionTileButton
              onClick={() => triggerExpiryCheck.mutate(undefined, {
                onSuccess: (result) => showToast(checkSummary("Expiry", result as unknown as Record<string, unknown>)),
                onError: (e: unknown) => toastError(e, "Expiry check failed"),
              })}
              disabled={triggerExpiryCheck.isPending}
              tone="orange"
              title="Run Expiry Check"
              icon={triggerExpiryCheck.isPending ? Icons.refresh("animate-spin") : Icons.clock()}
            />
            <ActionTileButton
              onClick={() => triggerResourceSync.mutate(undefined, {
                onSuccess: () => showToast("Resources synced successfully"),
                onError: (e: any) => showToast(e?.response?.data?.detail || "Resource sync failed", "error"),
              })}
              disabled={triggerResourceSync.isPending}
              tone="green"
              title="Sync Resources"
              icon={triggerResourceSync.isPending ? Icons.refresh("animate-spin") : Icons.refresh()}
            />
            <div className="flex items-center gap-2">
              <input
                type="email"
                value={testEmail}
                onChange={(e) => setTestEmail(e.target.value)}
                placeholder="Test email"
                className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm"
              />
              <GridActionButton
                onClick={() => testEmail && sendTestNotification.mutate(testEmail, {
                  onSuccess: () => showToast(`Test email sent to ${testEmail}`),
                  onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to send test email", "error"),
                })}
                disabled={sendTestNotification.isPending || !testEmail}
                title="Send Test Email"
                tone="purple"
              >
                {sendTestNotification.isPending ? Icons.refresh("animate-spin") : Icons.mail()}
              </GridActionButton>
            </div>
          </div>
          )}

          {/* Scheduled Jobs */}
          {schedulerStatus?.jobs && schedulerStatus.jobs.length > 0 && (
            <div className="border-t border-gray-200 pt-4">
              <h4 className="text-sm font-semibold text-gray-700 mb-3">Runtime Jobs</h4>
              <div className="space-y-2">
                {schedulerStatus.jobs.map((job) => (
                  <div key={job.job_id} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
                    <div>
                      <p className="font-medium text-gray-800">{job.name}</p>
                      <p className="text-sm text-gray-500">Trigger: {job.trigger}</p>
                    </div>
                    <div className="text-right">
                      <p className="text-sm text-gray-500">Next run:</p>
                      <p className="text-sm font-medium text-gray-700">
                        {job.next_run_time ? formatDate(job.next_run_time) : "N/A"}
                      </p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Notification History */}
        <div className={gridStyles.shell}>
          <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
            <div>
              <h3 className="text-lg font-semibold text-gray-800">Notification History</h3>
              <p className="text-sm text-gray-500">Infra alert emails only — the 100 most recent. Click a row for delivery details.</p>
            </div>
            <SearchBar value={tbl("notifHistory").search} onChange={(v) => setTblSearch("notifHistory", v)} placeholder="Search notifications..." />
          </div>
          {(() => {
            const { items: pagedNotifs, total: totalNotifs, page: notifPage } = filterAndPaginate(
              notificationHistory, tbl("notifHistory").search, tbl("notifHistory").page,
              (n) => [n.notification_type, n.recipient_email, n.subject, n.status],
              notificationSort,
              {
                notification_type: (n) => getNotificationTypeLabel(n.notification_type),
                recipient_email: (n) => n.recipient_email,
                subject: (n) => n.subject,
                status: (n) => n.status,
                sent_at: (n) => n.sent_at || "",
              },
            );
            return (
              <>
                <table className={gridStyles.table}>
                  <thead className={gridStyles.head}>
                    <tr>
                      <th className={gridStyles.headerCell}><SortableHeader label="Type" active={notificationSort.key === "notification_type"} direction={notificationSort.direction} onClick={() => setTblSort("notifHistory", "notification_type", "asc")} /></th>
                      <th className={gridStyles.headerCell}><SortableHeader label="Recipient" active={notificationSort.key === "recipient_email"} direction={notificationSort.direction} onClick={() => setTblSort("notifHistory", "recipient_email", "asc")} /></th>
                      <th className={gridStyles.headerCell}><SortableHeader label="Subject" active={notificationSort.key === "subject"} direction={notificationSort.direction} onClick={() => setTblSort("notifHistory", "subject", "asc")} /></th>
                      <th className={gridStyles.headerCell}><SortableHeader label="Status" active={notificationSort.key === "status"} direction={notificationSort.direction} onClick={() => setTblSort("notifHistory", "status", "asc")} /></th>
                      <th className={gridStyles.headerCell}><SortableHeader label="Sent" active={notificationSort.key === "sent_at"} direction={notificationSort.direction} onClick={() => setTblSort("notifHistory", "sent_at", "desc")} /></th>
                    </tr>
                  </thead>
                  <tbody>
                    {pagedNotifs.map((notification) => (
                      <tr
                        key={notification.id}
                        {...clickableRow(() => setDetail({ kind: "notification", id: notification.id, snapshot: notification }), `Open notification to ${notification.recipient_email}`)}
                        className={`${gridStyles.row} cursor-pointer focus:outline-none focus-visible:bg-att-50 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-att-300`}
                      >
                        <td className={gridStyles.strongCell}>
                          {getNotificationTypeLabel(notification.notification_type)}
                        </td>
                        <td className={gridStyles.cell}>{notification.recipient_email}</td>
                        <td className={`${gridStyles.cell} max-w-xs truncate`}>{notification.subject}</td>
                        <td className={gridStyles.cell}>
                          <span className={`px-2 py-1 rounded-full text-xs font-medium ${
                            notification.status === "sent" ? "bg-green-100 text-green-700" :
                            notification.status === "failed" ? "bg-red-100 text-red-700" :
                            "bg-yellow-100 text-yellow-700"
                          }`}>
                            {notification.status}
                          </span>
                        </td>
                        <td className={gridStyles.cell} title={notification.sent_at ? formatDate(notification.sent_at) : undefined}>
                          {notification.sent_at ? formatRelativeTime(notification.sent_at) : "Pending"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {totalNotifs === 0 && (
                  <div className="text-center py-12 text-gray-400">No notification history</div>
                )}
                <TablePagination currentPage={notifPage} totalItems={totalNotifs} onPageChange={(p) => setTblPage("notifHistory", p)} />
              </>
            );
          })()}
        </div>
      </div>
    );
  }
}

export default InfraAlertPage;
