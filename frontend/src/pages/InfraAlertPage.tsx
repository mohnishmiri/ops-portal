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

import React, { useState, useMemo, useCallback } from "react";
import { useAuth } from "../contexts/AuthContext";
import Toast, { type ToastState } from "../components/Toast";
import { AutoRefreshIndicator, gridStyles, type SortState, nextSortState, SortableHeader } from "../components/gridStyles";
import { MetricCard } from "../components/MetricCard";
import {
  AlertScheduleConfig,
  CreateAlertScheduleConfigRequest,
  CreateExpiryConfigRequest,
  CreatePGFlexConfigRequest,
  CreateStorageAlertConfigRequest,
  CreateVMThresholdConfigRequest,
  ExpiryAlert,
  ExpiryAlertType,
  ExpiryConfig,
  PGFlexServerAlert,
  PGFlexServerConfig,
  StorageAlertConfig,
  UpdateAlertScheduleConfigRequest,
  UpdateExpiryConfigRequest,
  UpdatePGFlexConfigRequest,
  UpdateStorageAlertConfigRequest,
  UpdateVMThresholdConfigRequest,
  VMThresholdAlert,
  VMThresholdConfig,
  formatRelativeTime,
  getAlertTypeLabel,
  getNotificationStatusColor,
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
  useCreateExpiryConfig,
  useCreatePGFlexConfig,
  useCreateStorageAlertConfig,
  useCreateVMThresholdConfig,
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
  useUpdateExpiryConfig,
  useUpdatePGFlexConfig,
  useUpdateStorageAlertConfig,
  useUpdateVMThresholdConfig,
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

const defaultAlertScheduleFormData: CreateAlertScheduleConfigRequest = {
  name: "",
  description: "",
  schedule_type: "interval",
  interval_minutes: 15,
  cron_expression: "",
  check_vm_thresholds: true,
  check_storage_thresholds: true,
  check_disk_thresholds: true,
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

const PIE_COLORS = [COLORS.active, COLORS.acknowledged, COLORS.resolved];

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
    onClick={onClick}
    disabled={disabled}
    title={title}
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

const SeverityBadge: React.FC<{ severity: string }> = ({ severity }) => {
  const bgColor = severity === "critical" ? "bg-red-100 text-red-700" : "bg-yellow-100 text-yellow-700";
  return (
    <span className={`px-2 py-1 rounded-full text-xs font-medium ${bgColor}`}>
      {severity}
    </span>
  );
};

const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const colors: Record<string, string> = {
    active: "bg-red-100 text-red-700",
    acknowledged: "bg-blue-100 text-blue-700",
    resolved: "bg-green-100 text-green-700",
    snoozed: "bg-gray-100 text-gray-700",
  };
  return (
    <span className={`px-2 py-1 rounded-full text-xs font-medium ${colors[status] || "bg-gray-100"}`}>
      {status}
    </span>
  );
};

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

// ── Main Component ────────────────────────────────────────────────────

const InfraAlertPage: React.FC = () => {
  const { canWrite } = useAuth();
  const { timezone, formatDate } = usePortalTimezone();
  const [activeTab, setActiveTab] = useState<TabKey>("dashboard");
  const [showAddVMConfig, setShowAddVMConfig] = useState(false);
  const [showAddExpiryConfig, setShowAddExpiryConfig] = useState(false);
  const [editingVMConfig, setEditingVMConfig] = useState<VMThresholdConfig | null>(null);
  const [editingExpiryConfig, setEditingExpiryConfig] = useState<ExpiryConfig | null>(null);
  const [showAddStorageConfig, setShowAddStorageConfig] = useState(false);
  const [editingStorageConfig, setEditingStorageConfig] = useState<StorageAlertConfig | null>(null);
  const [showAddPGConfig, setShowAddPGConfig] = useState(false);
  const [editingPGConfig, setEditingPGConfig] = useState<PGFlexServerConfig | null>(null);
  const [showAlertScheduleEditor, setShowAlertScheduleEditor] = useState(false);
  const [editingAlertSchedule, setEditingAlertSchedule] = useState<AlertScheduleConfig | null>(null);
  const [pgAlertStatusFilter, setPgAlertStatusFilter] = useState<string>("");
  const [alertStatusFilter, setAlertStatusFilter] = useState<string>("");
  const [testEmail, setTestEmail] = useState<string>("");
  const [alertScheduleFormData, setAlertScheduleFormData] = useState<CreateAlertScheduleConfigRequest>(
    defaultAlertScheduleFormData,
  );
  const [alertScheduleRecipientsInput, setAlertScheduleRecipientsInput] = useState("");

  // Form state for VM Config
  const [vmFormData, setVmFormData] = useState<CreateVMThresholdConfigRequest>({
    subscription_id: "",
    resource_group: "",
    vm_name: "",
    vm_id: "",
    cpu_warning_threshold: 80,
    cpu_critical_threshold: 90,
    memory_warning_threshold: 80,
    memory_critical_threshold: 90,
    disk_warning_threshold: 80,
    disk_critical_threshold: 90,
    notification_emails: [],
  });

  // Form state for Expiry Config
  const [expiryFormData, setExpiryFormData] = useState<CreateExpiryConfigRequest>({
    alert_type: "certificate",
    resource_name: "",
    resource_identifier: "",
    expiry_date: "",
    description: "",
    warning_days_before: 30,
    critical_days_before: 7,
    notification_emails: [],
  });

  // Form state for Storage Alert Config
  const [storageFormData, setStorageFormData] = useState<CreateStorageAlertConfigRequest>({
    subscription_id: "",
    resource_group: "",
    account_name: "",
    account_id: "",
    capacity_warning_gb: 100,
    capacity_critical_gb: 500,
    transactions_warning: 100000,
    transactions_critical: 500000,
    egress_warning_gb: 50,
    egress_critical_gb: 200,
    notification_emails: [],
  });

  // Form state for PG Flex Server Config
  const [pgFormData, setPgFormData] = useState<CreatePGFlexConfigRequest>({
    subscription_id: "",
    resource_group: "",
    server_name: "",
    server_id: "",
    cpu_warning_threshold: 70,
    cpu_critical_threshold: 90,
    memory_warning_threshold: 75,
    memory_critical_threshold: 90,
    storage_warning_threshold: 80,
    storage_critical_threshold: 95,
    notification_emails: [],
  });

  const [emailInput, setEmailInput] = useState("");

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
  const { data: vmAlerts = [], isLoading: vmAlertsLoading } = useVMThresholdAlerts(alertStatusFilter || undefined);
  const { data: expiryAlerts = [], isLoading: expiryAlertsLoading } = useExpiryAlerts(undefined, alertStatusFilter || undefined);
  const { data: vmConfigs = [] } = useVMThresholdConfigs();
  const { data: expiryConfigs = [] } = useExpiryConfigs();
  const { data: storageConfigs = [] } = useStorageAlertConfigs();
  const { data: pgConfigs = [] } = usePGFlexConfigs();
  const { data: pgAlerts = [], isLoading: pgAlertsLoading } = usePGFlexAlerts(pgAlertStatusFilter || undefined);
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
  const createVMConfig = useCreateVMThresholdConfig();
  const updateVMConfig = useUpdateVMThresholdConfig();
  const createExpiryConfigMutation = useCreateExpiryConfig();
  const updateExpiryConfigMutation = useUpdateExpiryConfig();
  const triggerVMCheck = useTriggerVMCheck();
  const triggerExpiryCheck = useTriggerExpiryCheck();
  const triggerResourceSync = useTriggerResourceSync();
  const syncResources = useSyncResources();
  const createStorageConfigMut = useCreateStorageAlertConfig();
  const updateStorageConfigMut = useUpdateStorageAlertConfig();
  const deleteStorageConfigMut = useDeleteStorageAlertConfig();
  const createPGConfigMut = useCreatePGFlexConfig();
  const updatePGConfigMut = useUpdatePGFlexConfig();
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
  const [vmActionTarget, setVMActionTarget] = useState<string | null>(null);
  const [pgActionTarget, setPGActionTarget] = useState<string | null>(null);
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
    const vmItems = vmAlerts
      .filter((alert) => alert.status === "active")
      .map((alert) => ({
        id: `vm-${alert.id}`,
        title: alert.vm_name,
        detail: `${alert.metric_type.toUpperCase()}: ${alert.current_value}%`,
        severity: alert.severity,
        createdAt: alert.created_at,
      }));

    const expiryItems = expiryAlerts
      .filter((alert) => alert.status === "active")
      .map((alert) => ({
        id: `expiry-${alert.id}`,
        title: alert.resource_name,
        detail: `Expires: ${formatDateOnly(alert.expiry_date)}`,
        severity: alert.severity,
        createdAt: alert.created_at,
      }));

    const pgItems = pgAlerts
      .filter((alert) => alert.status === "active")
      .map((alert) => ({
        id: `pg-${alert.id}`,
        title: alert.server_name,
        detail: `${alert.metric_type.toUpperCase()}: ${alert.current_value}%`,
        severity: alert.severity,
        createdAt: alert.created_at,
      }));

    return [...vmItems, ...expiryItems, ...pgItems]
      .sort((left, right) => new Date(right.createdAt).getTime() - new Date(left.createdAt).getTime())
      .slice(0, 5);
  }, [expiryAlerts, pgAlerts, vmAlerts]);

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

  const renderDashboard = () => (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          title="Total Active Alerts"
          value={summary?.total_active_alerts || 0}
          subtitle={`${totalVmAlerts + totalExpiryAlerts + totalPgAlerts} total alerts tracked`}
          icon={Icons.alert("text-red-600")}
          color="red"
        />
        <StatCard
          title="Active VM Alerts"
          value={activeVmAlerts}
          subtitle={`${totalVmAlerts} total across CPU, memory, and disk`}
          icon={Icons.server("text-blue-600")}
          color="blue"
        />
        <StatCard
          title="Active Expiry Alerts"
          value={activeExpiryAlerts}
          subtitle={`${totalExpiryAlerts} total across expiry rules`}
          icon={Icons.clock("text-orange-600")}
          color="orange"
        />
        <StatCard
          title="Configs Monitored"
          value={vmConfigs.length + expiryConfigs.length + pgConfigs.length}
          subtitle="Active configurations"
          icon={Icons.settings("text-gray-600")}
          color="gray"
        />
      </div>

      {/* PG Flex Server Alert Card (extra row) */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard
          title="Active PG Alerts"
          value={activePgAlerts}
          subtitle={`${totalPgAlerts} total across PG metrics`}
          icon={Icons.database("text-purple-600")}
          color="purple"
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Status Distribution */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">Alert Status Distribution</h3>
          {statusPieData.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
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
                  {statusPieData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-[250px] text-gray-400">
              No alert data available
            </div>
          )}
        </div>

        {/* Recent Alerts */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">Recent Active Alerts</h3>
          <div className="space-y-3 max-h-[250px] overflow-y-auto">
            {recentActiveAlerts.map((alert) => (
                <div
                  key={alert.id}
                  className="flex items-center justify-between p-3 bg-gray-50 rounded-lg"
                >
                  <div>
                    <p className="font-medium text-gray-800">{alert.title}</p>
                    <p className="text-sm text-gray-500">{alert.detail}</p>
                  </div>
                  <SeverityBadge severity={alert.severity} />
                </div>
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
      vmAlerts,
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
            value={alertStatusFilter}
            onChange={(e) => setAlertStatusFilter(e.target.value)}
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
            {pagedVMAlerts.map((alert) => (
              <tr key={alert.id} className={gridStyles.row}>
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
                          onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to acknowledge VM alert", "error"),
                        })}
                        title="Acknowledge"
                        tone="blue"
                      >
                        {Icons.check()}
                      </GridActionButton>
                    )}
                    {canWrite && alert.status !== "resolved" && (
                      <GridActionButton
                        onClick={() => resolveVMAlert.mutate({ alertId: alert.id }, {
                          onSuccess: () => showToast("VM alert resolved"),
                          onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to resolve VM alert", "error"),
                        })}
                        title="Resolve"
                        tone="green"
                      >
                        {Icons.check()}
                      </GridActionButton>
                    )}
                  </div>
                </td>
              </tr>
            ))}
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
      pgAlerts,
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
          <button
            onClick={() => checkPGAlerts.mutate(undefined, {
              onSuccess: () => showToast("PG alert check completed"),
              onError: (e: any) => showToast(e?.response?.data?.detail || "PG alert check failed", "error"),
            })}
            disabled={checkPGAlerts.isPending}
            className={buttonStyles.purpleSoft}
          >
            {Icons.play()} {checkPGAlerts.isPending ? "Checking..." : "Run PG Check"}
          </button>
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
            {pagedPGAlerts.map((alert) => (
              <tr key={alert.id} className={gridStyles.row}>
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
                          onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to acknowledge PG alert", "error"),
                        })}
                        title="Acknowledge"
                        tone="blue"
                      >
                        {Icons.check()}
                      </GridActionButton>
                    )}
                    {canWrite && alert.status !== "resolved" && (
                      <GridActionButton
                        onClick={() => resolvePGAlert.mutate({ alertId: alert.id }, {
                          onSuccess: () => showToast("PG alert resolved"),
                          onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to resolve PG alert", "error"),
                        })}
                        title="Resolve"
                        tone="green"
                      >
                        {Icons.check()}
                      </GridActionButton>
                    )}
                  </div>
                </td>
              </tr>
            ))}
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
            value={alertStatusFilter}
            onChange={(e) => setAlertStatusFilter(e.target.value)}
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
        <button
          onClick={() => checkExpiry.mutate(undefined, {
            onSuccess: () => showToast("Expiry alert check completed"),
            onError: (e: any) => showToast(e?.response?.data?.detail || "Expiry alert check failed", "error"),
          })}
          disabled={checkExpiry.isPending}
          className={buttonStyles.blueSoft}
        >
          {Icons.refresh(checkExpiry.isPending ? "animate-spin" : "")}
          Check Expiry Alerts
        </button>
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
            {pagedExpAlerts.map((alert) => (
              <tr key={alert.id} className={gridStyles.row}>
                <td className={gridStyles.strongCell}>
                  {getAlertTypeLabel(alert.alert_type)}
                </td>
                <td className={gridStyles.cell}>{alert.resource_name}</td>
                <td className={gridStyles.cell}>
                  {formatDateOnly(alert.expiry_date)}
                </td>
                <td className={gridStyles.cell}>
                  <span className={alert.days_until_expiry <= 0 ? "text-red-600 font-bold" : "text-gray-900"}>
                    {alert.days_until_expiry <= 0 ? "EXPIRED" : `${alert.days_until_expiry} days`}
                  </span>
                </td>
                <td className={gridStyles.cell}><SeverityBadge severity={alert.severity} /></td>
                <td className={gridStyles.cell}><StatusBadge status={alert.status} /></td>
                <td className={gridStyles.centerCell}>
                  <div className="flex items-center justify-center gap-1">
                    {canWrite && alert.status === "active" && (
                      <GridActionButton
                        onClick={() => acknowledgeExpiryAlert.mutate(alert.id, {
                          onSuccess: () => showToast("Expiry alert acknowledged"),
                          onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to acknowledge expiry alert", "error"),
                        })}
                        title="Acknowledge"
                        tone="blue"
                      >
                        {Icons.check()}
                      </GridActionButton>
                    )}
                    {canWrite && alert.status !== "resolved" && (
                      <GridActionButton
                        onClick={() => resolveExpiryAlert.mutate({ alertId: alert.id }, {
                          onSuccess: () => showToast("Expiry alert resolved"),
                          onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to resolve expiry alert", "error"),
                        })}
                        title="Resolve"
                        tone="green"
                      >
                        {Icons.check()}
                      </GridActionButton>
                    )}
                  </div>
                </td>
              </tr>
            ))}
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

  const renderConfigs = () => {
    const vmConfigSort = tblSort("vmConfigs", "vm_name", "asc");
    const expiryConfigSort = tblSort("expiryConfigs", "resource_name", "asc");
    const storageConfigSort = tblSort("storageConfigs", "account_name", "asc");
    const pgConfigSort = tblSort("pgConfigs", "server_name", "asc");
    const { items: pagedVMConfigs, total: totalVMConfigs, page: vmCfgPage } = filterAndPaginate(
      vmConfigs,
      tbl("vmConfigs").search,
      tbl("vmConfigs").page,
      (c) => [c.vm_name, c.resource_group],
      vmConfigSort,
      {
        vm_name: (c) => c.vm_name,
        resource_group: (c) => c.resource_group,
        cpu_warning_threshold: (c) => c.cpu_warning_threshold,
        memory_warning_threshold: (c) => c.memory_warning_threshold,
        disk_warning_threshold: (c) => c.disk_warning_threshold,
        is_enabled: (c) => c.is_enabled,
      },
    );
    const { items: pagedExpConfigs, total: totalExpConfigs, page: expCfgPage } = filterAndPaginate(
      expiryConfigs,
      tbl("expiryConfigs").search,
      tbl("expiryConfigs").page,
      (c) => [getAlertTypeLabel(c.alert_type), c.resource_name],
      expiryConfigSort,
      {
        alert_type: (c) => getAlertTypeLabel(c.alert_type),
        resource_name: (c) => c.resource_name,
        expiry_date: (c) => c.expiry_date,
        warning_days_before: (c) => c.warning_days_before,
        critical_days_before: (c) => c.critical_days_before,
        is_enabled: (c) => c.is_enabled,
      },
    );
    const { items: pagedStorageConfigs, total: totalStorageConfigs, page: storageCfgPage } = filterAndPaginate(
      storageConfigs,
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

    return (
    <div className="space-y-8">
      {/* VM Threshold Configs */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-800">VM Threshold Configurations</h3>
          <div className="flex items-center gap-3">
            <SearchBar
              value={tbl("vmConfigs").search}
              onChange={(v) => setTblSearch("vmConfigs", v)}
              placeholder="Search VM configs..."
            />
            {canWrite && (
              <button
                onClick={() => setShowAddVMConfig(true)}
                className={buttonStyles.primary}
              >
                {Icons.plus()} Add VM Config
              </button>
            )}
          </div>
        </div>
        <div className={gridStyles.shell}>
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}><SortableHeader label="VM Name" active={vmConfigSort.key === "vm_name"} direction={vmConfigSort.direction} onClick={() => setTblSort("vmConfigs", "vm_name", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Resource Group" active={vmConfigSort.key === "resource_group"} direction={vmConfigSort.direction} onClick={() => setTblSort("vmConfigs", "resource_group", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="CPU (Warn/Crit)" active={vmConfigSort.key === "cpu_warning_threshold"} direction={vmConfigSort.direction} onClick={() => setTblSort("vmConfigs", "cpu_warning_threshold", "desc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Memory (Warn/Crit)" active={vmConfigSort.key === "memory_warning_threshold"} direction={vmConfigSort.direction} onClick={() => setTblSort("vmConfigs", "memory_warning_threshold", "desc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Disk (Warn/Crit)" active={vmConfigSort.key === "disk_warning_threshold"} direction={vmConfigSort.direction} onClick={() => setTblSort("vmConfigs", "disk_warning_threshold", "desc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Status" active={vmConfigSort.key === "is_enabled"} direction={vmConfigSort.direction} onClick={() => setTblSort("vmConfigs", "is_enabled", "asc")} /></th>
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pagedVMConfigs.map((config) => (
                <tr key={config.id} className={gridStyles.row}>
                  <td className={gridStyles.strongCell}>{config.vm_name}</td>
                  <td className={gridStyles.cell}>{config.resource_group}</td>
                  <td className={gridStyles.cell}>
                    {config.cpu_warning_threshold}% / {config.cpu_critical_threshold}%
                  </td>
                  <td className={gridStyles.cell}>
                    {config.memory_warning_threshold}% / {config.memory_critical_threshold}%
                  </td>
                  <td className={gridStyles.cell}>
                    {config.disk_warning_threshold}% / {config.disk_critical_threshold}%
                  </td>
                  <td className={gridStyles.cell}>
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${config.is_enabled ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-700"}`}>
                      {config.is_enabled ? "Enabled" : "Disabled"}
                    </span>
                  </td>
                  <td className={gridStyles.centerCell}>
                    <div className="flex items-center justify-center gap-1">
                      {canWrite && (
                      <GridActionButton
                        onClick={() => {
                          setEditingVMConfig(config);
                          setVmFormData({
                            subscription_id: config.subscription_id,
                            resource_group: config.resource_group,
                            vm_name: config.vm_name,
                            vm_id: config.vm_id,
                            cpu_warning_threshold: config.cpu_warning_threshold,
                            cpu_critical_threshold: config.cpu_critical_threshold,
                            memory_warning_threshold: config.memory_warning_threshold,
                            memory_critical_threshold: config.memory_critical_threshold,
                            disk_warning_threshold: config.disk_warning_threshold,
                            disk_critical_threshold: config.disk_critical_threshold,
                            notification_emails: config.notification_emails || [],
                          });
                        }}
                        title="Edit"
                        tone="blue"
                      >
                        {Icons.edit()}
                      </GridActionButton>
                      )}
                      {canWrite && (
                      <GridActionButton
                        onClick={() => deleteVMConfig.mutate(config.id, {
                          onSuccess: () => showToast("VM config deleted"),
                          onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to delete VM config", "error"),
                        })}
                        title="Delete"
                        tone="red"
                      >
                        {Icons.trash()}
                      </GridActionButton>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {totalVMConfigs === 0 && (
            <div className="text-center py-12 text-gray-400">No VM threshold configurations</div>
          )}
          <TablePagination
            currentPage={vmCfgPage}
            totalItems={totalVMConfigs}
            onPageChange={(p) => setTblPage("vmConfigs", p)}
          />
        </div>
      </div>

      {/* Expiry Configs */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-800">Expiry Alert Configurations</h3>
          <div className="flex items-center gap-3">
            <SearchBar
              value={tbl("expiryConfigs").search}
              onChange={(v) => setTblSearch("expiryConfigs", v)}
              placeholder="Search expiry configs..."
            />
            {canWrite && (
              <button
                onClick={() => setShowAddExpiryConfig(true)}
                className={buttonStyles.primary}
              >
                {Icons.plus()} Add Expiry Config
              </button>
            )}
          </div>
        </div>
        <div className={gridStyles.shell}>
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}><SortableHeader label="Type" active={expiryConfigSort.key === "alert_type"} direction={expiryConfigSort.direction} onClick={() => setTblSort("expiryConfigs", "alert_type", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Resource" active={expiryConfigSort.key === "resource_name"} direction={expiryConfigSort.direction} onClick={() => setTblSort("expiryConfigs", "resource_name", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Expiry Date" active={expiryConfigSort.key === "expiry_date"} direction={expiryConfigSort.direction} onClick={() => setTblSort("expiryConfigs", "expiry_date", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Warning (days)" active={expiryConfigSort.key === "warning_days_before"} direction={expiryConfigSort.direction} onClick={() => setTblSort("expiryConfigs", "warning_days_before", "desc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Critical (days)" active={expiryConfigSort.key === "critical_days_before"} direction={expiryConfigSort.direction} onClick={() => setTblSort("expiryConfigs", "critical_days_before", "desc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Status" active={expiryConfigSort.key === "is_enabled"} direction={expiryConfigSort.direction} onClick={() => setTblSort("expiryConfigs", "is_enabled", "asc")} /></th>
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pagedExpConfigs.map((config) => (
                <tr key={config.id} className={gridStyles.row}>
                  <td className={gridStyles.strongCell}>
                    {getAlertTypeLabel(config.alert_type)}
                  </td>
                  <td className={gridStyles.cell}>{config.resource_name}</td>
                  <td className={gridStyles.cell}>
                    {formatDateOnly(config.expiry_date)}
                  </td>
                  <td className={gridStyles.cell}>{config.warning_days_before}</td>
                  <td className={gridStyles.cell}>{config.critical_days_before}</td>
                  <td className={gridStyles.cell}>
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${config.is_enabled ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-700"}`}>
                      {config.is_enabled ? "Enabled" : "Disabled"}
                    </span>
                  </td>
                  <td className={gridStyles.centerCell}>
                    <div className="flex items-center justify-center gap-1">
                      {canWrite && (
                      <GridActionButton
                        onClick={() => {
                          setEditingExpiryConfig(config);
                          setExpiryFormData({
                            alert_type: config.alert_type,
                            resource_name: config.resource_name,
                            resource_identifier: config.resource_identifier,
                            expiry_date: toDateInputValue(config.expiry_date),
                            description: config.description || '',
                            warning_days_before: config.warning_days_before,
                            critical_days_before: config.critical_days_before,
                            notification_emails: config.notification_emails || [],
                          });
                        }}
                        title="Edit"
                        tone="blue"
                      >
                        {Icons.edit()}
                      </GridActionButton>
                      )}
                      {canWrite && (
                      <GridActionButton
                        onClick={() => deleteExpiryConfig.mutate(config.id, {
                          onSuccess: () => showToast("Expiry config deleted"),
                          onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to delete expiry config", "error"),
                        })}
                        title="Delete"
                        tone="red"
                      >
                        {Icons.trash()}
                      </GridActionButton>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {totalExpConfigs === 0 && (
            <div className="text-center py-12 text-gray-400">No expiry alert configurations</div>
          )}
          <TablePagination
            currentPage={expCfgPage}
            totalItems={totalExpConfigs}
            onPageChange={(p) => setTblPage("expiryConfigs", p)}
          />
        </div>
      </div>

      {/* Storage Alert Configs */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-800">Storage Alert Configurations</h3>
          <div className="flex items-center gap-3">
            <SearchBar value={tbl("storageConfigs").search} onChange={(v) => setTblSearch("storageConfigs", v)} placeholder="Search storage configs..." />
            {canWrite && (
              <button
                onClick={() => setShowAddStorageConfig(true)}
                className={buttonStyles.primary}
              >
                {Icons.plus()} Add Storage Config
              </button>
            )}
          </div>
        </div>
        <div className={gridStyles.shell}>
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}><SortableHeader label="Account Name" active={storageConfigSort.key === "account_name"} direction={storageConfigSort.direction} onClick={() => setTblSort("storageConfigs", "account_name", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Resource Group" active={storageConfigSort.key === "resource_group"} direction={storageConfigSort.direction} onClick={() => setTblSort("storageConfigs", "resource_group", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Capacity (Warn/Crit) GB" active={storageConfigSort.key === "capacity_warning_gb"} direction={storageConfigSort.direction} onClick={() => setTblSort("storageConfigs", "capacity_warning_gb", "desc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Transactions (Warn/Crit)" active={storageConfigSort.key === "transactions_warning"} direction={storageConfigSort.direction} onClick={() => setTblSort("storageConfigs", "transactions_warning", "desc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Egress (Warn/Crit) GB" active={storageConfigSort.key === "egress_warning_gb"} direction={storageConfigSort.direction} onClick={() => setTblSort("storageConfigs", "egress_warning_gb", "desc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Status" active={storageConfigSort.key === "is_enabled"} direction={storageConfigSort.direction} onClick={() => setTblSort("storageConfigs", "is_enabled", "asc")} /></th>
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pagedStorageConfigs.map((config) => (
                <tr key={config.id} className={gridStyles.row}>
                  <td className={gridStyles.strongCell}>{config.account_name}</td>
                  <td className={gridStyles.cell}>{config.resource_group}</td>
                  <td className={gridStyles.cell}>
                    {config.capacity_warning_gb} / {config.capacity_critical_gb}
                  </td>
                  <td className={gridStyles.cell}>
                    {config.transactions_warning?.toLocaleString()} / {config.transactions_critical?.toLocaleString()}
                  </td>
                  <td className={gridStyles.cell}>
                    {config.egress_warning_gb} / {config.egress_critical_gb}
                  </td>
                  <td className={gridStyles.cell}>
                    <span className={`px-2 py-1 rounded-full text-xs font-medium ${config.is_enabled ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-700"}`}>
                      {config.is_enabled ? "Enabled" : "Disabled"}
                    </span>
                  </td>
                  <td className={gridStyles.centerCell}>
                    <div className="flex items-center justify-center gap-1">
                      {canWrite && (
                      <GridActionButton
                        onClick={() => {
                          setEditingStorageConfig(config);
                          setStorageFormData({
                            subscription_id: config.subscription_id,
                            resource_group: config.resource_group,
                            account_name: config.account_name,
                            account_id: config.account_id || "",
                            capacity_warning_gb: config.capacity_warning_gb,
                            capacity_critical_gb: config.capacity_critical_gb,
                            transactions_warning: config.transactions_warning,
                            transactions_critical: config.transactions_critical,
                            egress_warning_gb: config.egress_warning_gb,
                            egress_critical_gb: config.egress_critical_gb,
                            notification_emails: config.notification_emails || [],
                          });
                          setShowAddStorageConfig(true);
                        }}
                        title="Edit"
                        tone="blue"
                      >
                        {Icons.edit()}
                      </GridActionButton>
                      )}
                      {canWrite && (
                      <GridActionButton
                        onClick={() => deleteStorageConfigMut.mutate(config.id, {
                          onSuccess: () => showToast("Storage config deleted"),
                          onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to delete storage config", "error"),
                        })}
                        title="Delete"
                        tone="red"
                      >
                        {Icons.trash()}
                      </GridActionButton>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {totalStorageConfigs === 0 && (
            <div className="text-center py-12 text-gray-400">No storage alert configurations</div>
          )}
          <TablePagination
            currentPage={storageCfgPage}
            totalItems={totalStorageConfigs}
            onPageChange={(p) => setTblPage("storageConfigs", p)}
          />
        </div>
      </div>

      {/* PG Flex Server Alert Configs */}
      <div>
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-gray-800">PostgreSQL Flexible Server Configurations</h3>
          <div className="flex items-center gap-3">
            <SearchBar value={tbl("pgConfigs").search} onChange={(v) => setTblSearch("pgConfigs", v)} placeholder="Search PG configs..." />
            {canWrite && (
              <button
                onClick={() => setShowAddPGConfig(true)}
                className={buttonStyles.purpleSoft}
              >
                {Icons.plus()} Add PG Config
              </button>
            )}
          </div>
        </div>
        <div className={gridStyles.shell}>
          {(() => {
            const { items: pagedPGConfigs, total: totalPGConfigs, page: pgCfgPage } = filterAndPaginate(
              pgConfigs, tbl("pgConfigs").search, tbl("pgConfigs").page,
              (c) => [c.server_name, c.resource_group],
              pgConfigSort,
              {
                server_name: (c) => c.server_name,
                resource_group: (c) => c.resource_group,
                cpu_warning_threshold: (c) => c.cpu_warning_threshold,
                memory_warning_threshold: (c) => c.memory_warning_threshold,
                storage_warning_threshold: (c) => c.storage_warning_threshold,
                is_enabled: (c) => c.is_enabled,
              },
            );
            return (
              <>
                <table className={gridStyles.table}>
                  <thead className={gridStyles.head}>
                    <tr>
                      <th className={gridStyles.headerCell}><SortableHeader label="Server Name" active={pgConfigSort.key === "server_name"} direction={pgConfigSort.direction} onClick={() => setTblSort("pgConfigs", "server_name", "asc")} /></th>
                      <th className={gridStyles.headerCell}><SortableHeader label="Resource Group" active={pgConfigSort.key === "resource_group"} direction={pgConfigSort.direction} onClick={() => setTblSort("pgConfigs", "resource_group", "asc")} /></th>
                      <th className={gridStyles.headerCell}><SortableHeader label="CPU (Warn/Crit) %" active={pgConfigSort.key === "cpu_warning_threshold"} direction={pgConfigSort.direction} onClick={() => setTblSort("pgConfigs", "cpu_warning_threshold", "desc")} /></th>
                      <th className={gridStyles.headerCell}><SortableHeader label="Memory (Warn/Crit) %" active={pgConfigSort.key === "memory_warning_threshold"} direction={pgConfigSort.direction} onClick={() => setTblSort("pgConfigs", "memory_warning_threshold", "desc")} /></th>
                      <th className={gridStyles.headerCell}><SortableHeader label="Storage (Warn/Crit) %" active={pgConfigSort.key === "storage_warning_threshold"} direction={pgConfigSort.direction} onClick={() => setTblSort("pgConfigs", "storage_warning_threshold", "desc")} /></th>
                      <th className={gridStyles.headerCell}><SortableHeader label="Status" active={pgConfigSort.key === "is_enabled"} direction={pgConfigSort.direction} onClick={() => setTblSort("pgConfigs", "is_enabled", "asc")} /></th>
                      <th className={gridStyles.headerCellCenter}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pagedPGConfigs.map((config) => (
                      <tr key={config.id} className={gridStyles.row}>
                        <td className={gridStyles.strongCell}>{config.server_name}</td>
                        <td className={gridStyles.cell}>{config.resource_group}</td>
                        <td className={gridStyles.cell}>{config.cpu_warning_threshold} / {config.cpu_critical_threshold}</td>
                        <td className={gridStyles.cell}>{config.memory_warning_threshold} / {config.memory_critical_threshold}</td>
                        <td className={gridStyles.cell}>{config.storage_warning_threshold} / {config.storage_critical_threshold}</td>
                        <td className={gridStyles.cell}>
                          <span className={`px-2 py-1 rounded-full text-xs font-medium ${config.is_enabled ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-700"}`}>
                            {config.is_enabled ? "Enabled" : "Disabled"}
                          </span>
                        </td>
                        <td className={gridStyles.centerCell}>
                          <div className="flex items-center justify-center gap-1">
                            {canWrite && (
                            <GridActionButton
                              onClick={() => {
                                setEditingPGConfig(config);
                                setPgFormData({
                                  subscription_id: config.subscription_id,
                                  resource_group: config.resource_group,
                                  server_name: config.server_name,
                                  server_id: config.server_id || "",
                                  cpu_warning_threshold: config.cpu_warning_threshold,
                                  cpu_critical_threshold: config.cpu_critical_threshold,
                                  memory_warning_threshold: config.memory_warning_threshold,
                                  memory_critical_threshold: config.memory_critical_threshold,
                                  storage_warning_threshold: config.storage_warning_threshold,
                                  storage_critical_threshold: config.storage_critical_threshold,
                                  notification_emails: config.notification_emails || [],
                                });
                                setShowAddPGConfig(true);
                              }}
                              title="Edit"
                              tone="blue"
                            >
                              {Icons.edit()}
                            </GridActionButton>
                            )}
                            {canWrite && (
                            <GridActionButton
                              onClick={() => deletePGConfigMut.mutate(config.id, {
                                onSuccess: () => showToast("PG config deleted"),
                                onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to delete PG config", "error"),
                              })}
                              title="Delete"
                              tone="red"
                            >
                              {Icons.trash()}
                            </GridActionButton>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {totalPGConfigs === 0 && (
                  <div className="text-center py-12 text-gray-400">No PostgreSQL Flexible Server configurations</div>
                )}
                <TablePagination currentPage={pgCfgPage} totalItems={totalPGConfigs} onPageChange={(p) => setTblPage("pgConfigs", p)} />
              </>
            );
          })()}
        </div>
      </div>
    </div>
  );
  };

  // ── Main Render ─────────────────────────────────────────────────────

  return (
    <div className="py-6">
      {/* Header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-gray-900">Infrastructure Alerts</h1>
        <p className="text-gray-600 mt-1">
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

      {/* Add/Edit VM Config Modal */}
      {(showAddVMConfig || editingVMConfig) && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
            <h3 className="text-lg font-semibold mb-4">
              {editingVMConfig ? "Edit VM Threshold Configuration" : "Add VM Threshold Configuration"}
            </h3>
            <form onSubmit={(e) => {
              e.preventDefault();
              if (editingVMConfig) {
                updateVMConfig.mutate({
                  configId: editingVMConfig.id,
                  data: {
                    cpu_warning_threshold: vmFormData.cpu_warning_threshold,
                    cpu_critical_threshold: vmFormData.cpu_critical_threshold,
                    memory_warning_threshold: vmFormData.memory_warning_threshold,
                    memory_critical_threshold: vmFormData.memory_critical_threshold,
                    disk_warning_threshold: vmFormData.disk_warning_threshold,
                    disk_critical_threshold: vmFormData.disk_critical_threshold,
                    notification_emails: vmFormData.notification_emails,
                  },
                }, {
                  onSuccess: () => {
                    setEditingVMConfig(null);
                    resetVMForm();
                  },
                });
              } else {
                createVMConfig.mutate(vmFormData, {
                  onSuccess: () => {
                    setShowAddVMConfig(false);
                    resetVMForm();
                  },
                });
              }
            }}>
              <div className="grid grid-cols-2 gap-4 mb-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Subscription *</label>
                  <select
                    value={vmFormData.subscription_id}
                    onChange={(e) => setVmFormData({ ...vmFormData, subscription_id: e.target.value, resource_group: "", vm_name: "", vm_id: "" })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 bg-white"
                    required
                    disabled={!!editingVMConfig}
                  >
                    <option value="">-- Select Subscription --</option>
                    {[...new Set(azureVMs.map((vm) => vm.subscription_id || vm.id?.split("/")[2]).filter(Boolean))].map((sub) => (
                      <option key={sub} value={sub!}>{subNameMap.get(sub!) || sub}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Resource Group *</label>
                  <select
                    value={vmFormData.resource_group}
                    onChange={(e) => setVmFormData({ ...vmFormData, resource_group: e.target.value, vm_name: "", vm_id: "" })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 bg-white"
                    required
                    disabled={!!editingVMConfig || !vmFormData.subscription_id}
                  >
                    <option value="">-- Select Resource Group --</option>
                    {[...new Set(
                      azureVMs
                        .filter((vm) => !vmFormData.subscription_id || (vm.subscription_id || vm.id?.split("/")[2]) === vmFormData.subscription_id)
                        .map((vm) => vm.resource_group)
                        .filter(Boolean)
                    )].map((rg) => (
                      <option key={rg} value={rg!}>{rg}</option>
                    ))}
                  </select>
                </div>
                <div className="col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-1">VM Name *</label>
                  <select
                    value={vmFormData.vm_name}
                    onChange={(e) => {
                      const selectedVM = azureVMs.find(
                        (vm) =>
                          vm.name === e.target.value &&
                          vm.resource_group === vmFormData.resource_group
                      );
                      setVmFormData({
                        ...vmFormData,
                        vm_name: e.target.value,
                        vm_id: selectedVM?.id || "",
                      });
                    }}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 bg-white"
                    required
                    disabled={!!editingVMConfig || !vmFormData.resource_group}
                  >
                    <option value="">-- Select VM --</option>
                    {azureVMs
                      .filter(
                        (vm) =>
                          (!vmFormData.subscription_id || (vm.subscription_id || vm.id?.split("/")[2]) === vmFormData.subscription_id) &&
                          (!vmFormData.resource_group || vm.resource_group === vmFormData.resource_group)
                      )
                      .map((vm) => (
                        <option key={vm.id} value={vm.name}>{vm.name}</option>
                      ))}
                  </select>
                </div>
              </div>
              
              <div className="border-t border-gray-200 pt-4 mb-4">
                <h4 className="text-sm font-semibold text-gray-700 mb-3">Threshold Settings (%)</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">CPU Warning</label>
                    <input
                      type="number"
                      min="0"
                      max="100"
                      value={vmFormData.cpu_warning_threshold}
                      onChange={(e) => setVmFormData({ ...vmFormData, cpu_warning_threshold: Number(e.target.value) })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">CPU Critical</label>
                    <input
                      type="number"
                      min="0"
                      max="100"
                      value={vmFormData.cpu_critical_threshold}
                      onChange={(e) => setVmFormData({ ...vmFormData, cpu_critical_threshold: Number(e.target.value) })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">Memory Warning</label>
                    <input
                      type="number"
                      min="0"
                      max="100"
                      value={vmFormData.memory_warning_threshold}
                      onChange={(e) => setVmFormData({ ...vmFormData, memory_warning_threshold: Number(e.target.value) })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">Memory Critical</label>
                    <input
                      type="number"
                      min="0"
                      max="100"
                      value={vmFormData.memory_critical_threshold}
                      onChange={(e) => setVmFormData({ ...vmFormData, memory_critical_threshold: Number(e.target.value) })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">Disk Warning</label>
                    <input
                      type="number"
                      min="0"
                      max="100"
                      value={vmFormData.disk_warning_threshold}
                      onChange={(e) => setVmFormData({ ...vmFormData, disk_warning_threshold: Number(e.target.value) })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">Disk Critical</label>
                    <input
                      type="number"
                      min="0"
                      max="100"
                      value={vmFormData.disk_critical_threshold}
                      onChange={(e) => setVmFormData({ ...vmFormData, disk_critical_threshold: Number(e.target.value) })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                </div>
              </div>

              <div className="border-t border-gray-200 pt-4 mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-2">Notification Emails</label>
                <div className="flex gap-2 mb-2">
                  <input
                    type="email"
                    value={emailInput}
                    onChange={(e) => setEmailInput(e.target.value)}
                    placeholder="Enter email and press Add"
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-lg"
                  />
                  <button
                    type="button"
                    onClick={() => {
                      if (emailInput && !vmFormData.notification_emails?.includes(emailInput)) {
                        setVmFormData({
                          ...vmFormData,
                          notification_emails: [...(vmFormData.notification_emails || []), emailInput],
                        });
                        setEmailInput("");
                      }
                    }}
                    className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
                  >
                    Add
                  </button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {vmFormData.notification_emails?.map((email, idx) => (
                    <span key={idx} className="px-3 py-1 bg-blue-100 text-blue-700 rounded-full text-sm flex items-center gap-1">
                      {email}
                      <button
                        type="button"
                        onClick={() => setVmFormData({
                          ...vmFormData,
                          notification_emails: vmFormData.notification_emails?.filter((_, i) => i !== idx),
                        })}
                        className="text-blue-500 hover:text-blue-700"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
                <button
                  type="button"
                  onClick={() => {
                    setShowAddVMConfig(false);
                    setEditingVMConfig(null);
                    resetVMForm();
                  }}
                  className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createVMConfig.isPending || updateVMConfig.isPending}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                  {createVMConfig.isPending || updateVMConfig.isPending ? "Saving..." : "Save Configuration"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Add/Edit Expiry Config Modal */}
      {(showAddExpiryConfig || editingExpiryConfig) && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-xl p-6 max-w-2xl w-full mx-4 max-h-[90vh] overflow-y-auto">
            <h3 className="text-lg font-semibold mb-4">
              {editingExpiryConfig ? "Edit Expiry Alert Configuration" : "Add Expiry Alert Configuration"}
            </h3>
            <form onSubmit={(e) => {
              e.preventDefault();
              if (editingExpiryConfig) {
                updateExpiryConfigMutation.mutate({
                  configId: editingExpiryConfig.id,
                  data: {
                    resource_name: expiryFormData.resource_name,
                    description: expiryFormData.description,
                    expiry_date: expiryFormData.expiry_date,
                    warning_days_before: expiryFormData.warning_days_before,
                    critical_days_before: expiryFormData.critical_days_before,
                    notification_emails: expiryFormData.notification_emails,
                  },
                }, {
                  onSuccess: () => {
                    setEditingExpiryConfig(null);
                    resetExpiryForm();
                  },
                });
              } else {
                createExpiryConfigMutation.mutate(expiryFormData, {
                  onSuccess: () => {
                    setShowAddExpiryConfig(false);
                    resetExpiryForm();
                  },
                });
              }
            }}>
              <div className="grid grid-cols-2 gap-4 mb-4">
                <div className="col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-1">Alert Type *</label>
                  <select
                    value={expiryFormData.alert_type}
                    onChange={(e) => setExpiryFormData({ ...expiryFormData, alert_type: e.target.value as ExpiryAlertType })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    disabled={!!editingExpiryConfig}
                  >
                    <option value="certificate">Certificate Expiry</option>
                    <option value="mech_id">MechID Expiry</option>
                    <option value="aaf_account">AAF Account Expiry</option>
                    <option value="database_account">Database Account Expiry</option>
                    <option value="itservices_domain">ITServices Domain Expiry</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Resource Name *</label>
                  <input
                    type="text"
                    value={expiryFormData.resource_name}
                    onChange={(e) => setExpiryFormData({ ...expiryFormData, resource_name: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="e.g., api-server-cert"
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Resource Identifier *</label>
                  <input
                    type="text"
                    value={expiryFormData.resource_identifier}
                    onChange={(e) => setExpiryFormData({ ...expiryFormData, resource_identifier: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="Unique identifier or path"
                    required
                    disabled={!!editingExpiryConfig}
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Expiry Date *</label>
                  <input
                    type="date"
                    value={expiryFormData.expiry_date}
                    onChange={(e) => setExpiryFormData({ ...expiryFormData, expiry_date: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    required
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Description</label>
                  <input
                    type="text"
                    value={expiryFormData.description || ""}
                    onChange={(e) => setExpiryFormData({ ...expiryFormData, description: e.target.value })}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    placeholder="Optional description"
                  />
                </div>
              </div>

              <div className="border-t border-gray-200 pt-4 mb-4">
                <h4 className="text-sm font-semibold text-gray-700 mb-3">Alert Thresholds (Days Before Expiry)</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">Warning Days</label>
                    <input
                      type="number"
                      min="1"
                      max="365"
                      value={expiryFormData.warning_days_before}
                      onChange={(e) => setExpiryFormData({ ...expiryFormData, warning_days_before: Number(e.target.value) })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">Critical Days</label>
                    <input
                      type="number"
                      min="1"
                      max="365"
                      value={expiryFormData.critical_days_before}
                      onChange={(e) => setExpiryFormData({ ...expiryFormData, critical_days_before: Number(e.target.value) })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                </div>
              </div>

              <div className="border-t border-gray-200 pt-4 mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-2">Notification Emails</label>
                <div className="flex gap-2 mb-2">
                  <input
                    type="email"
                    value={emailInput}
                    onChange={(e) => setEmailInput(e.target.value)}
                    placeholder="Enter email and press Add"
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-lg"
                  />
                  <button
                    type="button"
                    onClick={() => {
                      if (emailInput && !expiryFormData.notification_emails?.includes(emailInput)) {
                        setExpiryFormData({
                          ...expiryFormData,
                          notification_emails: [...(expiryFormData.notification_emails || []), emailInput],
                        });
                        setEmailInput("");
                      }
                    }}
                    className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
                  >
                    Add
                  </button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {expiryFormData.notification_emails?.map((email, idx) => (
                    <span key={idx} className="px-3 py-1 bg-blue-100 text-blue-700 rounded-full text-sm flex items-center gap-1">
                      {email}
                      <button
                        type="button"
                        onClick={() => setExpiryFormData({
                          ...expiryFormData,
                          notification_emails: expiryFormData.notification_emails?.filter((_, i) => i !== idx),
                        })}
                        className="text-blue-500 hover:text-blue-700"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
                <button
                  type="button"
                  onClick={() => {
                    setShowAddExpiryConfig(false);
                    setEditingExpiryConfig(null);
                    resetExpiryForm();
                  }}
                  className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createExpiryConfigMutation.isPending || updateExpiryConfigMutation.isPending}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                  {createExpiryConfigMutation.isPending || updateExpiryConfigMutation.isPending ? "Saving..." : "Save Configuration"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Storage Config Modal */}
      {showAddStorageConfig && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl shadow-xl max-w-lg w-full mx-4 p-6 max-h-[90vh] overflow-y-auto">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">
              {editingStorageConfig ? "Edit Storage Alert Config" : "Add Storage Alert Config"}
            </h3>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (editingStorageConfig) {
                  updateStorageConfigMut.mutate(
                    { configId: editingStorageConfig.id, data: storageFormData as any },
                    {
                      onSuccess: () => {
                        showToast("Storage config updated successfully");
                        setShowAddStorageConfig(false);
                        setEditingStorageConfig(null);
                        resetStorageForm();
                      },
                      onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to update storage config", "error"),
                    }
                  );
                } else {
                  createStorageConfigMut.mutate(storageFormData, {
                    onSuccess: () => {
                      showToast("Storage config created successfully");
                      setShowAddStorageConfig(false);
                      resetStorageForm();
                    },
                    onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to create storage config", "error"),
                  });
                }
              }}
            >
              <div className="space-y-4 mb-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Storage Account *</label>
                  <select
                    value={storageFormData.account_name}
                    onChange={(e) => {
                      const selected = storageAccounts.find((sa) => sa.name === e.target.value);
                      if (selected) {
                        setStorageFormData({
                          ...storageFormData,
                          account_name: selected.name,
                          account_id: selected.id || "",
                          resource_group: selected.resource_group || "",
                          subscription_id: selected.subscription_id || "",
                        });
                      }
                    }}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500"
                    required
                    disabled={!!editingStorageConfig}
                  >
                    <option value="">Select a Storage Account</option>
                    {storageAccounts.map((sa) => (
                      <option key={sa.id || sa.name} value={sa.name}>
                        {sa.name} ({sa.resource_group})
                      </option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="border-t border-gray-200 pt-4 mb-4">
                <h4 className="text-sm font-semibold text-gray-700 mb-3">Capacity Thresholds (GB)</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">Warning</label>
                    <input
                      type="number"
                      min="0"
                      value={storageFormData.capacity_warning_gb}
                      onChange={(e) => setStorageFormData({ ...storageFormData, capacity_warning_gb: Number(e.target.value) })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">Critical</label>
                    <input
                      type="number"
                      min="0"
                      value={storageFormData.capacity_critical_gb}
                      onChange={(e) => setStorageFormData({ ...storageFormData, capacity_critical_gb: Number(e.target.value) })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                </div>
              </div>

              <div className="border-t border-gray-200 pt-4 mb-4">
                <h4 className="text-sm font-semibold text-gray-700 mb-3">Transaction Thresholds</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">Warning</label>
                    <input
                      type="number"
                      min="0"
                      value={storageFormData.transactions_warning}
                      onChange={(e) => setStorageFormData({ ...storageFormData, transactions_warning: Number(e.target.value) })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">Critical</label>
                    <input
                      type="number"
                      min="0"
                      value={storageFormData.transactions_critical}
                      onChange={(e) => setStorageFormData({ ...storageFormData, transactions_critical: Number(e.target.value) })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                </div>
              </div>

              <div className="border-t border-gray-200 pt-4 mb-4">
                <h4 className="text-sm font-semibold text-gray-700 mb-3">Egress Thresholds (GB)</h4>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">Warning</label>
                    <input
                      type="number"
                      min="0"
                      value={storageFormData.egress_warning_gb}
                      onChange={(e) => setStorageFormData({ ...storageFormData, egress_warning_gb: Number(e.target.value) })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                  <div>
                    <label className="block text-sm text-gray-600 mb-1">Critical</label>
                    <input
                      type="number"
                      min="0"
                      value={storageFormData.egress_critical_gb}
                      onChange={(e) => setStorageFormData({ ...storageFormData, egress_critical_gb: Number(e.target.value) })}
                      className="w-full px-3 py-2 border border-gray-300 rounded-lg"
                    />
                  </div>
                </div>
              </div>

              <div className="border-t border-gray-200 pt-4 mb-4">
                <label className="block text-sm font-medium text-gray-700 mb-2">Notification Emails</label>
                <div className="flex gap-2 mb-2">
                  <input
                    type="email"
                    value={emailInput}
                    onChange={(e) => setEmailInput(e.target.value)}
                    placeholder="Enter email and press Add"
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-lg"
                  />
                  <button
                    type="button"
                    onClick={() => {
                      if (emailInput && !storageFormData.notification_emails?.includes(emailInput)) {
                        setStorageFormData({
                          ...storageFormData,
                          notification_emails: [...(storageFormData.notification_emails || []), emailInput],
                        });
                        setEmailInput("");
                      }
                    }}
                    className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
                  >
                    Add
                  </button>
                </div>
                <div className="flex flex-wrap gap-2">
                  {storageFormData.notification_emails?.map((email, idx) => (
                    <span key={idx} className="px-3 py-1 bg-blue-100 text-blue-700 rounded-full text-sm flex items-center gap-1">
                      {email}
                      <button
                        type="button"
                        onClick={() => setStorageFormData({
                          ...storageFormData,
                          notification_emails: storageFormData.notification_emails?.filter((_, i) => i !== idx),
                        })}
                        className="text-blue-500 hover:text-blue-700"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
                <button
                  type="button"
                  onClick={() => {
                    setShowAddStorageConfig(false);
                    setEditingStorageConfig(null);
                    resetStorageForm();
                  }}
                  className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createStorageConfigMut.isPending || updateStorageConfigMut.isPending}
                  className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
                >
                  {createStorageConfigMut.isPending || updateStorageConfigMut.isPending ? "Saving..." : "Save Configuration"}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* PG Flex Server Config Modal */}
      {showAddPGConfig && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-2xl shadow-xl max-w-lg w-full mx-4 p-6 max-h-[90vh] overflow-y-auto">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">
              {editingPGConfig ? "Edit PG Flex Server Config" : "Add PG Flex Server Config"}
            </h3>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                if (editingPGConfig) {
                  updatePGConfigMut.mutate(
                    { configId: editingPGConfig.id, data: pgFormData as any },
                    {
                      onSuccess: () => {
                        showToast("PG config updated successfully");
                        setShowAddPGConfig(false);
                        setEditingPGConfig(null);
                        resetPGForm();
                      },
                      onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to update PG config", "error"),
                    },
                  );
                } else {
                  createPGConfigMut.mutate(pgFormData as any, {
                    onSuccess: () => {
                      showToast("PG config created successfully");
                      setShowAddPGConfig(false);
                      resetPGForm();
                    },
                    onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to create PG config", "error"),
                  });
                }
              }}
              className="space-y-4"
            >
              {/* PG Server Selector */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">PostgreSQL Server</label>
                <select
                  value={pgFormData.server_id}
                  onChange={(e) => {
                    const server = pgServers.find((s) => s.id === e.target.value);
                    if (server) {
                      setPgFormData((prev) => ({
                        ...prev,
                        server_id: server.id || "",
                        server_name: server.name || "",
                        subscription_id: server.subscription_id || "",
                        resource_group: server.resource_group || "",
                      }));
                    }
                  }}
                  className="w-full px-3 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-purple-500"
                  required
                >
                  <option value="">Select a PG Flex Server</option>
                  {pgServers.map((s) => (
                    <option key={s.id} value={s.id}>{s.name} ({s.resource_group})</option>
                  ))}
                </select>
              </div>

              {/* CPU Thresholds */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">CPU Warning %</label>
                  <input type="number" min={0} max={100} value={pgFormData.cpu_warning_threshold}
                    onChange={(e) => setPgFormData((p) => ({ ...p, cpu_warning_threshold: +e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg" required />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">CPU Critical %</label>
                  <input type="number" min={0} max={100} value={pgFormData.cpu_critical_threshold}
                    onChange={(e) => setPgFormData((p) => ({ ...p, cpu_critical_threshold: +e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg" required />
                </div>
              </div>

              {/* Memory Thresholds */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Memory Warning %</label>
                  <input type="number" min={0} max={100} value={pgFormData.memory_warning_threshold}
                    onChange={(e) => setPgFormData((p) => ({ ...p, memory_warning_threshold: +e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg" required />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Memory Critical %</label>
                  <input type="number" min={0} max={100} value={pgFormData.memory_critical_threshold}
                    onChange={(e) => setPgFormData((p) => ({ ...p, memory_critical_threshold: +e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg" required />
                </div>
              </div>

              {/* Storage Thresholds */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Storage Warning %</label>
                  <input type="number" min={0} max={100} value={pgFormData.storage_warning_threshold}
                    onChange={(e) => setPgFormData((p) => ({ ...p, storage_warning_threshold: +e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg" required />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1">Storage Critical %</label>
                  <input type="number" min={0} max={100} value={pgFormData.storage_critical_threshold}
                    onChange={(e) => setPgFormData((p) => ({ ...p, storage_critical_threshold: +e.target.value }))}
                    className="w-full px-3 py-2 border border-gray-300 rounded-lg" required />
                </div>
              </div>

              {/* Notification Emails */}
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Notification Emails</label>
                <div className="flex gap-2">
                  <input
                    type="email"
                    value={emailInput}
                    onChange={(e) => setEmailInput(e.target.value)}
                    placeholder="Add email..."
                    className="flex-1 px-3 py-2 border border-gray-300 rounded-lg"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        if (emailInput.trim()) {
                          setPgFormData((p) => ({
                            ...p,
                            notification_emails: [...(p.notification_emails || []), emailInput.trim()],
                          }));
                          setEmailInput("");
                        }
                      }
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => {
                      if (emailInput.trim()) {
                        setPgFormData((p) => ({
                          ...p,
                          notification_emails: [...(p.notification_emails || []), emailInput.trim()],
                        }));
                        setEmailInput("");
                      }
                    }}
                    className="px-3 py-2 bg-gray-200 rounded-lg hover:bg-gray-300"
                  >
                    Add
                  </button>
                </div>
                <div className="flex flex-wrap gap-2 mt-2">
                  {(pgFormData.notification_emails || []).map((email, idx) => (
                    <span key={idx} className="flex items-center gap-1 px-2 py-1 bg-purple-50 text-purple-700 rounded-full text-sm">
                      {email}
                      <button
                        type="button"
                        onClick={() => setPgFormData((p) => ({
                          ...p,
                          notification_emails: (p.notification_emails || []).filter((_, i) => i !== idx),
                        }))}
                        className="text-purple-500 hover:text-purple-700"
                      >
                        ×
                      </button>
                    </span>
                  ))}
                </div>
              </div>

              <div className="flex justify-end gap-3 pt-4 border-t border-gray-200">
                <button
                  type="button"
                  onClick={() => {
                    setShowAddPGConfig(false);
                    setEditingPGConfig(null);
                    resetPGForm();
                  }}
                  className="px-4 py-2 border border-gray-300 rounded-lg hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={createPGConfigMut.isPending || updatePGConfigMut.isPending}
                  className="px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50"
                >
                  {createPGConfigMut.isPending || updatePGConfigMut.isPending ? "Saving..." : "Save Configuration"}
                </button>
              </div>
            </form>
          </div>
        </div>
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

  // Form reset helpers
  function resetVMForm() {
    setVmFormData({
      subscription_id: "",
      resource_group: "",
      vm_name: "",
      vm_id: "",
      cpu_warning_threshold: 80,
      cpu_critical_threshold: 90,
      memory_warning_threshold: 80,
      memory_critical_threshold: 90,
      disk_warning_threshold: 80,
      disk_critical_threshold: 90,
      notification_emails: [],
    });
    setEmailInput("");
  }

  function resetExpiryForm() {
    setExpiryFormData({
      alert_type: "certificate",
      resource_name: "",
      resource_identifier: "",
      expiry_date: "",
      description: "",
      warning_days_before: 30,
      critical_days_before: 7,
      notification_emails: [],
    });
    setEmailInput("");
  }

  function resetStorageForm() {
    setStorageFormData({
      subscription_id: "",
      resource_group: "",
      account_name: "",
      account_id: "",
      capacity_warning_gb: 100,
      capacity_critical_gb: 500,
      transactions_warning: 100000,
      transactions_critical: 500000,
      egress_warning_gb: 50,
      egress_critical_gb: 200,
      notification_emails: [],
    });
    setEmailInput("");
  }

  function resetPGForm() {
    setPgFormData({
      subscription_id: "",
      resource_group: "",
      server_name: "",
      server_id: "",
      cpu_warning_threshold: 70,
      cpu_critical_threshold: 90,
      memory_warning_threshold: 75,
      memory_critical_threshold: 90,
      storage_warning_threshold: 80,
      storage_critical_threshold: 95,
      notification_emails: [],
    });
    setEmailInput("");
  }

  // ── Resources Tab ───────────────────────────────────────────────────

  function renderResources() {
    const vmSort = tblSort("vms", "name", "asc");
    const storageSort = tblSort("storageAccounts", "name", "asc");
    const diskSort = tblSort("disks", "name", "asc");
    const pgServerSort = tblSort("pgServers", "name", "asc");
    const { items: pagedVMs, total: totalVMs, page: vmPage } = filterAndPaginate(
      azureVMs, tbl("vms").search, tbl("vms").page,
      (v) => [v.name, v.resource_group, v.location, v.vm_size, v.power_state],
      vmSort,
      {
        name: (v) => v.name,
        resource_group: (v) => v.resource_group,
        location: (v) => v.location,
        vm_size: (v) => v.vm_size,
        power_state: (v) => v.power_state,
      },
    );
    const { items: pagedSA, total: totalSA, page: saPage } = filterAndPaginate(
      storageAccounts, tbl("storageAccounts").search, tbl("storageAccounts").page,
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
      disks, tbl("disks").search, tbl("disks").page,
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
        {/* Resource Summary */}
        <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
          <StatCard
            title="Total Resources"
            value={inventorySummary?.total_resources || 0}
            icon={Icons.database("text-blue-600")}
            color="blue"
          />
          <StatCard
            title="Virtual Machines"
            value={azureVMs.length}
            icon={Icons.server("text-green-600")}
            color="green"
          />
          <StatCard
            title="Storage Accounts"
            value={storageAccounts.length}
            icon={Icons.database("text-purple-600")}
            color="purple"
          />
          <StatCard
            title="Managed Disks"
            value={disks.length}
            icon={Icons.database("text-orange-600")}
            color="orange"
          />
          <StatCard
            title="PG Flex Servers"
            value={pgServers.length}
            icon={Icons.database("text-indigo-600")}
            color="indigo"
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

        {/* VMs Table */}
        <div className={gridStyles.shell}>
          <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
            <h3 className="text-lg font-semibold text-gray-800">Virtual Machines</h3>
            <SearchBar value={tbl("vms").search} onChange={(v) => setTblSearch("vms", v)} placeholder="Search VMs..." />
          </div>
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}><SortableHeader label="Name" active={vmSort.key === "name"} direction={vmSort.direction} onClick={() => setTblSort("vms", "name", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Resource Group" active={vmSort.key === "resource_group"} direction={vmSort.direction} onClick={() => setTblSort("vms", "resource_group", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Location" active={vmSort.key === "location"} direction={vmSort.direction} onClick={() => setTblSort("vms", "location", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Size" active={vmSort.key === "vm_size"} direction={vmSort.direction} onClick={() => setTblSort("vms", "vm_size", "asc")} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Status" active={vmSort.key === "power_state"} direction={vmSort.direction} onClick={() => setTblSort("vms", "power_state", "asc")} /></th>
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pagedVMs.map((vm) => (
                <tr key={vm.id} className={gridStyles.row}>
                  <td className={gridStyles.strongCell}>{vm.name}</td>
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
                  <td className={gridStyles.centerCell}>
                    <div className="flex justify-center gap-1">
                      {canWrite && vm.power_state !== "running" && (
                        <GridActionButton
                          onClick={() => {
                            setVMActionTarget(vm.name);
                            startVMMut.mutate(
                              { resource_group: vm.resource_group, vm_name: vm.name },
                              {
                                onSuccess: () => { showToast(`VM '${vm.name}' started successfully`); syncResources.mutate("vms"); },
                                onError: (e: any) => showToast(e?.response?.data?.detail || `Failed to start VM '${vm.name}'`, "error"),
                                onSettled: () => setVMActionTarget(null),
                              },
                            );
                          }}
                          disabled={vmActionTarget === vm.name}
                          title="Start VM"
                          tone="green"
                        >
                          {vmActionTarget === vm.name && startVMMut.isPending ? Icons.refresh("animate-spin") : Icons.play()}
                        </GridActionButton>
                      )}
                      {canWrite && vm.power_state === "running" && (
                        <>
                          <GridActionButton
                            onClick={() => {
                              setVMActionTarget(vm.name);
                              stopVMMut.mutate(
                                { resource_group: vm.resource_group, vm_name: vm.name },
                                {
                                  onSuccess: () => { showToast(`VM '${vm.name}' stopped (deallocated) successfully`); syncResources.mutate("vms"); },
                                  onError: (e: any) => showToast(e?.response?.data?.detail || `Failed to stop VM '${vm.name}'`, "error"),
                                  onSettled: () => setVMActionTarget(null),
                                },
                              );
                            }}
                            disabled={vmActionTarget === vm.name}
                            title="Stop (Deallocate) VM"
                            tone="red"
                          >
                            {vmActionTarget === vm.name && stopVMMut.isPending ? Icons.refresh("animate-spin") : Icons.stop()}
                          </GridActionButton>
                          <GridActionButton
                            onClick={() => {
                              setVMActionTarget(vm.name);
                              restartVMMut.mutate(
                                { resource_group: vm.resource_group, vm_name: vm.name },
                                {
                                  onSuccess: () => { showToast(`VM '${vm.name}' restarted successfully`); syncResources.mutate("vms"); },
                                  onError: (e: any) => showToast(e?.response?.data?.detail || `Failed to restart VM '${vm.name}'`, "error"),
                                  onSettled: () => setVMActionTarget(null),
                                },
                              );
                            }}
                            disabled={vmActionTarget === vm.name}
                            title="Restart VM"
                            tone="orange"
                          >
                            {vmActionTarget === vm.name && restartVMMut.isPending ? Icons.refresh("animate-spin") : Icons.restart()}
                          </GridActionButton>
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {totalVMs === 0 && (
            <div className="text-center py-12 text-gray-400">No VMs found. Click "Sync Resources" to load from Azure.</div>
          )}
          <TablePagination currentPage={vmPage} totalItems={totalVMs} onPageChange={(p) => setTblPage("vms", p)} />
        </div>

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
                <tr key={sa.id} className={gridStyles.row}>
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

        {/* Managed Disks Table with Usage Bars */}
        <div className={gridStyles.shell}>
          <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
            <h3 className="text-lg font-semibold text-gray-800">Managed Disks</h3>
            <SearchBar value={tbl("disks").search} onChange={(v) => setTblSearch("disks", v)} placeholder="Search disks..." />
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
                      <tr key={disk.id} className={gridStyles.row}>
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
                            {disk.disk_state === "Unattached" && (
                              <GridActionButton
                                onClick={() => {
                                  setConfirmDialog({
                                    title: "Delete unattached disk?",
                                    message: `Permanently delete "${disk.name}" in ${disk.resource_group}? This cannot be undone.`,
                                    confirmLabel: "Delete",
                                    onConfirm: () => {
                                      setDiskActionTarget(disk.name);
                                      deleteDiskMut.mutate(
                                        {
                                          subscription_id: disk.subscription_id,
                                          resource_group: disk.resource_group,
                                          disk_name: disk.name,
                                        },
                                        {
                                          onSuccess: () => {
                                            showToast(`Disk '${disk.name}' deleted successfully`);
                                            syncResources.mutate("disk");
                                          },
                                          onError: (e: unknown) => {
                                            const detail =
                                              (e as { response?: { data?: { detail?: string } } })
                                                ?.response?.data?.detail ||
                                              `Failed to delete disk '${disk.name}'`;
                                            showToast(detail, "error");
                                          },
                                          onSettled: () => setDiskActionTarget(null),
                                        }
                                      );
                                    },
                                  });
                                }}
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

        {/* PG Flex Servers Table */}
        <div className={gridStyles.shell}>
          <div className="px-6 py-4 border-b border-gray-200 flex items-center justify-between">
            <h3 className="text-lg font-semibold text-gray-800">PostgreSQL Flexible Servers</h3>
            <SearchBar value={tbl("pgServers").search} onChange={(v) => setTblSearch("pgServers", v)} placeholder="Search PG servers..." />
          </div>
          {(() => {
            const { items: pagedPGServers, total: totalPGServers, page: pgSrvPage } = filterAndPaginate(
              pgServers, tbl("pgServers").search, tbl("pgServers").page,
              (s) => [s.name, s.resource_group, s.location, s.state, s.version, s.sku_name],
              pgServerSort,
              {
                name: (s) => s.name,
                resource_group: (s) => s.resource_group,
                location: (s) => s.location,
                state: (s) => s.state,
                version: (s) => s.version,
                sku_name: (s) => s.sku_name,
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
                      <th className={gridStyles.headerCellCenter}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {pagedPGServers.map((server) => (
                      <tr key={server.id} className={gridStyles.row}>
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
                        <td className={gridStyles.centerCell}>
                          <div className="flex justify-center gap-1">
                            {canWrite && server.state === "Stopped" && (
                              <GridActionButton
                                onClick={() => {
                                  setPGActionTarget(server.name);
                                  startPGServerMut.mutate(
                                    { resource_group: server.resource_group, server_name: server.name },
                                    {
                                      onSuccess: () => { showToast(`PG Server '${server.name}' started successfully`); syncResources.mutate("pg-servers"); },
                                      onError: (e: any) => showToast(e?.response?.data?.detail || `Failed to start PG Server '${server.name}'`, "error"),
                                      onSettled: () => setPGActionTarget(null),
                                    },
                                  );
                                }}
                                disabled={pgActionTarget === server.name}
                                title="Start PG Server"
                                tone="green"
                              >
                                {pgActionTarget === server.name && startPGServerMut.isPending ? Icons.refresh("animate-spin") : Icons.play()}
                              </GridActionButton>
                            )}
                            {canWrite && server.state === "Ready" && (
                              <>
                                <GridActionButton
                                  onClick={() => {
                                    setPGActionTarget(server.name);
                                    stopPGServerMut.mutate(
                                      { resource_group: server.resource_group, server_name: server.name },
                                      {
                                        onSuccess: () => { showToast(`PG Server '${server.name}' stopped successfully`); syncResources.mutate("pg-servers"); },
                                        onError: (e: any) => showToast(e?.response?.data?.detail || `Failed to stop PG Server '${server.name}'`, "error"),
                                        onSettled: () => setPGActionTarget(null),
                                      },
                                    );
                                  }}
                                  disabled={pgActionTarget === server.name}
                                  title="Stop PG Server"
                                  tone="red"
                                >
                                  {pgActionTarget === server.name && stopPGServerMut.isPending ? Icons.refresh("animate-spin") : Icons.stop()}
                                </GridActionButton>
                                <GridActionButton
                                  onClick={() => {
                                    setPGActionTarget(server.name);
                                    restartPGServerMut.mutate(
                                      { resource_group: server.resource_group, server_name: server.name },
                                      {
                                        onSuccess: () => { showToast(`PG Server '${server.name}' restarted successfully`); syncResources.mutate("pg-servers"); },
                                        onError: (e: any) => showToast(e?.response?.data?.detail || `Failed to restart PG Server '${server.name}'`, "error"),
                                        onSettled: () => setPGActionTarget(null),
                                      },
                                    );
                                  }}
                                  disabled={pgActionTarget === server.name}
                                  title="Restart PG Server"
                                  tone="orange"
                                >
                                  {pgActionTarget === server.name && restartPGServerMut.isPending ? Icons.refresh("animate-spin") : Icons.restart()}
                                </GridActionButton>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
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

        {/* ── Resource Usage Charts ──────────────────────────────── */}
        {(disks.length > 0 || storageAccounts.length > 0) && (
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
          onError: (error: any) =>
            showToast(error?.response?.data?.detail || "Failed to update schedule", "error"),
        },
      );
      return;
    }

    createAlertScheduleMut.mutate(payload, {
      onSuccess: () => {
        showToast(`Schedule \"${payload.name}\" created`);
        resetAlertScheduleEditor();
      },
      onError: (error: any) =>
        showToast(error?.response?.data?.detail || "Failed to create schedule", "error"),
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
                      className={`${gridStyles.toolbarInput} w-full`}
                      placeholder="0 */2 * * *"
                    />
                  </label>
                )}

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
                </label>

                <label className="space-y-2 text-sm text-gray-700 md:col-span-2 xl:col-span-4">
                  <span className="font-medium text-gray-800">Digest Recipients</span>
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
                  { key: "check_vm_thresholds", label: "Run VM threshold checks" },
                  { key: "check_pg_thresholds", label: "Run PG threshold checks" },
                  { key: "check_expiry_alerts", label: "Run expiry checks" },
                  { key: "check_storage_thresholds", label: "Run storage checks" },
                  { key: "check_disk_thresholds", label: "Run disk checks" },
                  { key: "send_daily_digest", label: "Include daily digest" },
                ].map((item) => (
                  <label
                    key={item.key}
                    className="flex items-center gap-3 rounded-xl border border-att-100 bg-white px-4 py-3 text-sm text-gray-700"
                  >
                    <input
                      type="checkbox"
                      checked={Boolean(alertScheduleFormData[item.key as keyof CreateAlertScheduleConfigRequest])}
                      onChange={(event) =>
                        setAlertScheduleFormData((prev) => ({
                          ...prev,
                          [item.key]: event.target.checked,
                        }))
                      }
                      className="h-4 w-4 rounded border-att-300 text-att-600 focus:ring-att-500"
                    />
                    <span>{item.label}</span>
                  </label>
                ))}
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
                    schedule.check_storage_thresholds ? "Storage" : null,
                    schedule.check_disk_thresholds ? "Disk" : null,
                    schedule.send_daily_digest ? "Digest" : null,
                  ].filter(Boolean);

                  return (
                    <tr key={schedule.id} className={gridStyles.row}>
                      <td className={gridStyles.strongCell}>
                        <div>
                          <div>{schedule.name}</div>
                          {schedule.description && (
                            <div className="mt-1 text-xs font-normal text-gray-500">{schedule.description}</div>
                          )}
                        </div>
                      </td>
                      <td className={gridStyles.cell}>
                        {schedule.schedule_type === "interval"
                          ? `Every ${schedule.interval_minutes} min`
                          : schedule.cron_expression || "Cron"}
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
                        {schedule.next_run_at
                          ? formatDate(schedule.next_run_at)
                          : schedule.send_daily_digest
                            ? `Digest at ${schedule.digest_time_utc} UTC`
                            : "Not scheduled"}
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
                            onClick={() =>
                              deleteAlertScheduleMut.mutate(schedule.id, {
                                onSuccess: () => showToast(`Schedule \"${schedule.name}\" deleted`),
                                onError: (error: any) =>
                                  showToast(error?.response?.data?.detail || "Failed to delete schedule", "error"),
                              })
                            }
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
                onSuccess: () => showToast("VM check completed"),
                onError: (e: any) => showToast(e?.response?.data?.detail || "VM check failed", "error"),
              })}
              disabled={triggerVMCheck.isPending}
              tone="blue"
              title="Run VM Check"
              icon={triggerVMCheck.isPending ? Icons.refresh("animate-spin") : Icons.play()}
            />
            <ActionTileButton
              onClick={() => triggerPGCheck.mutate(undefined, {
                onSuccess: () => showToast("PG check completed"),
                onError: (e: any) => showToast(e?.response?.data?.detail || "PG check failed", "error"),
              })}
              disabled={triggerPGCheck.isPending}
              tone="purple"
              title="Run PG Check"
              icon={triggerPGCheck.isPending ? Icons.refresh("animate-spin") : Icons.database()}
            />
            <ActionTileButton
              onClick={() => triggerExpiryCheck.mutate(undefined, {
                onSuccess: () => showToast("Expiry check completed"),
                onError: (e: any) => showToast(e?.response?.data?.detail || "Expiry check failed", "error"),
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
            <h3 className="text-lg font-semibold text-gray-800">Notification History</h3>
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
                      <tr key={notification.id} className={gridStyles.row}>
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
                        <td className={gridStyles.cell}>
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
