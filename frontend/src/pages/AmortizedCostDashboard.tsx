/**
 * Amortized Cost Dashboard — rich analytics from DB-synced amortized cost data.
 *
 * Features:
 * - KPI cards (total cost, row count, date range, env split)
 * - Daily cost trend (area chart with Prod / Non-Prod)
 * - Service breakdown (horizontal bar + pie-style donut)
 * - Daily cost by top services (stacked area)
 * - Resource group breakdown table
 * - Top resources table with drill-down
 * - Monthly pivot table (service × month)
 * - Location / subscription / charge-type / pricing-model breakdowns
 * - Environment comparison (Prod vs Non-Prod)
 * - Drill-down modal for filtered resource view
 */

import React, { useState, useMemo, useCallback, useEffect, useRef } from "react";
import { isAxiosError } from "axios";
import {
  AreaChart,
  Area,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
  PieChart,
  Pie,
  Cell,
  LineChart,
  Line,
} from "recharts";
import {
  useAmortizedCostSummary,
  useAmortizedDrilldown,
  useAmortizedCostSync,
  useAmortizedCostSyncStatus,
  AmortizedCostSummary,
  AmortizedBreakdownItem,
  AmortizedTopResource,
  AmortizedPivotService,
} from "../services/costApi";
import { usePortalTimezone } from "../contexts/TimezoneContext";
import { MetricCard, MetricCardIcons } from "../components/MetricCard";
import { gridStyles } from "../components/gridStyles";
import { useAuth } from "../contexts/AuthContext";
// ── Palette & Helpers ─────────────────────────────────────────────────

const COLORS = [
  "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
  "#ec4899", "#06b6d4", "#f97316", "#14b8a6", "#6366f1",
  "#84cc16", "#e11d48", "#0ea5e9", "#a855f7", "#22c55e",
];

const fmtUSD = (n: number) =>
  `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const fmtCompact = (n: number) =>
  n >= 1_000_000
    ? `$${(n / 1_000_000).toFixed(2)}M`
    : n >= 1_000
    ? `$${(n / 1_000).toFixed(1)}k`
    : `$${n.toFixed(2)}`;

const fmtDate = (d: string) => {
  if (!d) return "";
  const parts = d.split("-");
  if (parts.length === 3) {
    const months = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
    return `${months[Number(parts[1]) - 1]} ${Number(parts[2])}`;
  }
  return d;
};

const fmtPct = (n: number) => `${n.toFixed(1)}%`;

const getFriendlyErrorMessage = (error: unknown): string => {
  if (isAxiosError(error)) {
    const payload = error.response?.data as { detail?: unknown; error?: unknown } | undefined;
    const detail = payload?.detail;
    if (typeof detail === "string" && detail.trim()) {
      return detail;
    }
    const apiError = payload?.error;
    if (typeof apiError === "string" && apiError.trim()) {
      return apiError;
    }
    if (error.response?.status === 503) {
      return "Database is down. Please try again later.";
    }
    if (typeof error.message === "string" && error.message.trim()) {
      return error.message;
    }
  }

  if (error instanceof Error && error.message.trim()) {
    return error.message;
  }
  return "Unable to load amortized cost data right now. Please try again later.";
};

const DEFAULT_GRID_PAGE_SIZE = 10;

const matchesSearch = (
  query: string,
  values: Array<string | number | null | undefined>,
) => {
  if (!query) {
    return true;
  }

  const normalizedQuery = query.trim().toLowerCase();
  return values.some((value) => String(value ?? "").toLowerCase().includes(normalizedQuery));
};

function usePaginatedRows<T>(rows: T[], pageSize = DEFAULT_GRID_PAGE_SIZE) {
  const [page, setPage] = useState(0);

  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));

  useEffect(() => {
    setPage(0);
  }, [rows.length, pageSize]);

  useEffect(() => {
    if (page > totalPages - 1) {
      setPage(totalPages - 1);
    }
  }, [page, totalPages]);

  const pagedRows = useMemo(
    () => rows.slice(page * pageSize, (page + 1) * pageSize),
    [page, pageSize, rows],
  );

  return {
    page,
    setPage,
    totalPages,
    pagedRows,
  };
}

// ── Sub-components ────────────────────────────────────────────────────

const KPICard: React.FC<{
  label: string;
  value: string;
  sub?: string;
  icon: React.ReactNode;
  tone: "blue" | "emerald" | "amber" | "purple";
}> = ({ label, value, sub, icon, tone }) => (
  <MetricCard title={label} value={value} subtitle={sub} icon={icon} tone={tone} />
);

const SectionTitle: React.FC<{ title: string; sub?: string; compact?: boolean }> = ({ title, sub, compact = false }) => (
  <div className={compact ? "" : "mb-4"}>
    <h2 className="text-lg font-semibold text-gray-900">{title}</h2>
    {sub && <p className="text-sm text-gray-500">{sub}</p>}
  </div>
);

const GridSearchInput: React.FC<{
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
}> = ({ value, onChange, placeholder }) => (
  <input
    type="text"
    placeholder={placeholder}
    value={value}
    onChange={(event) => onChange(event.target.value)}
    className={`${gridStyles.toolbarInput} w-full sm:w-64`}
  />
);

const GridPager: React.FC<{
  page: number;
  totalPages: number;
  pageSize: number;
  totalItems: number;
  itemLabel: string;
  onPageChange: React.Dispatch<React.SetStateAction<number>>;
}> = ({ page, totalPages, pageSize, totalItems, itemLabel, onPageChange }) => {
  const start = totalItems === 0 ? 0 : page * pageSize + 1;
  const end = Math.min((page + 1) * pageSize, totalItems);

  return (
    <div className={gridStyles.pager}>
      <span className="text-gray-600">
        {totalItems === 0
          ? `Showing 0 ${itemLabel}`
          : `Showing ${start}-${end} of ${totalItems} ${itemLabel}`}
      </span>
      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={() => onPageChange((current) => Math.max(0, current - 1))}
          disabled={page === 0}
          className={gridStyles.pagerButton}
        >
          Previous
        </button>
        <span className="text-gray-700">
          Page {totalPages === 0 ? 0 : page + 1} of {totalPages}
        </span>
        <button
          type="button"
          onClick={() => onPageChange((current) => Math.min(totalPages - 1, current + 1))}
          disabled={page >= totalPages - 1}
          className={gridStyles.pagerButton}
        >
          Next
        </button>
      </div>
    </div>
  );
};

// ── Main Component ────────────────────────────────────────────────────

const AmortizedCostDashboard: React.FC = () => {
  const { formatDate } = usePortalTimezone();
  const { canWrite, isAdmin } = useAuth();
  const [env, setEnv] = useState("ALL");
  const [months, setMonths] = useState(3);
  const [activeTab, setActiveTab] = useState<"overview" | "services" | "resources" | "pivot" | "drilldown">("overview");
  const [drilldownFilter, setDrilldownFilter] = useState<{
    resource_group?: string;
    meter_category?: string;
    subscription?: string;
  }>({});
  const [drilldownEnabled, setDrilldownEnabled] = useState(false);

  const { data, isLoading, error, refetch, isFetching, dataUpdatedAt } = useAmortizedCostSummary(env, months);
  const {
    data: drilldownData,
    isLoading: drilldownLoading,
  } = useAmortizedDrilldown(env, months, drilldownFilter, drilldownEnabled);
  const syncMutation = useAmortizedCostSync();
  const { data: syncStatus } = useAmortizedCostSyncStatus();

  // Auto-refresh data when a background sync (stale-triggered) completes
  const prevSyncStatusRef = useRef<string | null>(null);
  useEffect(() => {
    const prev = prevSyncStatusRef.current;
    const curr = syncStatus?.status ?? null;
    prevSyncStatusRef.current = curr;
    if (prev === "running" && curr === "completed") {
      refetch();
    }
  }, [syncStatus?.status, refetch]);

  // Track "last refreshed X min ago" for the auto-refresh indicator
  const [lastRefreshLabel, setLastRefreshLabel] = useState("just now");
  useEffect(() => {
    const update = () => {
      if (!dataUpdatedAt) return;
      const ageMin = Math.floor((Date.now() - dataUpdatedAt) / 60_000);
      setLastRefreshLabel(ageMin < 1 ? "just now" : `${ageMin} min ago`);
    };
    update();
    const t = setInterval(update, 30_000);
    return () => clearInterval(t);
  }, [dataUpdatedAt]);

  // Detect data gaps: 3+ consecutive $0-cost days in the middle of the trend
  // (not the edges, which may genuinely have no data yet)
  const gapDaysDetected = useMemo(() => {
    const trend = data?.daily_trend;
    if (!trend || trend.length < 14) return 0;
    const middle = trend.slice(7, -3); // ignore first 7 and last 3 days
    let max = 0, run = 0;
    for (const day of middle) {
      if ((day as { cost: number }).cost === 0) { run++; max = Math.max(max, run); }
      else run = 0;
    }
    return max;
  }, [data?.daily_trend]);

  const handleSync = useCallback(
    (force = false) => {
      syncMutation.mutate({ months, force });
    },
    [months, syncMutation],
  );

  const handleDrilldown = (type: string, value: string) => {
    const filter: typeof drilldownFilter = {};
    if (type === "resource_group") filter.resource_group = value;
    if (type === "meter_category") filter.meter_category = value;
    if (type === "subscription") filter.subscription = value;
    setDrilldownFilter(filter);
    setDrilldownEnabled(true);
    setActiveTab("drilldown");
  };

  if (isLoading) {
    return (
      <div className="py-6">
        <div className="flex items-center justify-center h-96">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4" />
            <p className="text-gray-600">Loading amortized cost data...</p>
          </div>
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-6">
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center">
          <p className="text-red-800 font-medium">Failed to load amortized cost data</p>
          <p className="text-red-600 text-sm mt-2">{getFriendlyErrorMessage(error)}</p>
          <button
            onClick={() => refetch()}
            className="mt-4 px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 transition"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  const hasData = Boolean(data && data.row_count > 0);
  const summary = data ?? null;
  const tabs = [
    { id: "overview" as const, label: "Overview" },
    { id: "services" as const, label: "Services" },
    { id: "resources" as const, label: "Resources" },
    { id: "pivot" as const, label: "Monthly Pivot" },
    { id: "drilldown" as const, label: "Drill-down" },
  ];

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
            <svg className="h-8 w-8 text-att-500" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24"><path d="M12 1v22M17 5H9.5a3.5 3.5 0 0 0 0 7h5a3.5 3.5 0 0 1 0 7H6" /></svg>
            Amortized Cost Dashboard
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            {hasData
              ? `Auto-synced from Azure • ${summary?.date_range.start} to ${summary?.date_range.end} • ${summary?.row_count.toLocaleString()} line items`
              : "Auto-synced from Azure • no cached amortized rows available yet"}
          </p>
          <p className="text-xs text-gray-400 mt-0.5 flex items-center gap-1.5">
            <span className="inline-block w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
            Live · refreshes every 5 min · last refreshed {lastRefreshLabel}
          </p>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          <select
            value={env}
            onChange={(e) => setEnv(e.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white shadow-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          >
            <option value="ALL">All Environments</option>
            <option value="PROD">Production</option>
            <option value="NONPROD">Non-Production</option>
          </select>
          <select
            value={months}
            onChange={(e) => setMonths(Number(e.target.value))}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white shadow-sm focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          >
            {[1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12].map((m) => (
              <option key={m} value={m}>
                Last {m} {m === 1 ? "month" : "months"}
              </option>
            ))}
          </select>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg border border-gray-300 bg-white text-gray-700 hover:bg-gray-50 disabled:opacity-50 shadow-sm transition"
          >
            <svg
              className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
              />
            </svg>
            Refresh
          </button>
          {canWrite && (
            <button
              onClick={() => handleSync(false)}
              disabled={syncMutation.isPending}
              className="inline-flex items-center gap-1.5 px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-60 shadow-sm transition"
            >
              {syncMutation.isPending ? (
                <>
                  <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                  </svg>
                  Syncing…
                </>
              ) : (
                <>
                  <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M9 19l3 3m0 0l3-3m-3 3V10" />
                  </svg>
                  Sync from Azure
                </>
              )}
            </button>
          )}
          {isAdmin && (
            <button
              onClick={() => handleSync(true)}
              disabled={syncMutation.isPending}
              title="Wipe and re-fetch all months in the window (repairs location and resource metadata)"
              className="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-medium rounded-lg border border-amber-300 bg-amber-50 text-amber-900 hover:bg-amber-100 disabled:opacity-60 shadow-sm transition"
            >
              Force sync
            </button>
          )}
        </div>
      </div>

      {/* Sync status bar */}
      {syncStatus?.last_sync && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 px-4 py-3 flex items-center justify-between text-sm">
          <div className="flex flex-wrap items-center gap-2 text-gray-600">
            <span className={`inline-block w-2 h-2 rounded-full ${syncStatus.status === "completed" ? "bg-green-500" : syncStatus.status === "running" ? "bg-yellow-500 animate-pulse" : "bg-red-500"}`} />
            <span>Last sync: {formatDate(syncStatus.last_sync)}</span>
            {syncStatus.rows_synced != null && (
              <span className="text-gray-400">&bull; {syncStatus.rows_synced.toLocaleString()} rows</span>
            )}
            {syncStatus.triggered_by && (
              <span className="text-gray-400">&bull; triggered by {syncStatus.triggered_by}</span>
            )}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span
              className="inline-flex items-center rounded-full bg-att-50 px-2.5 py-1 text-xs font-medium text-att-700"
              title={syncStatus.monitored_subscription_ids?.join(", ") || "No monitored subscriptions configured"}
            >
              Sync scope: {syncStatus.monitored_subscription_count ?? 0} monitored subscription{(syncStatus.monitored_subscription_count ?? 0) === 1 ? "" : "s"}
            </span>
          </div>
        </div>
      )}

      {/* Sync error notification */}
      {syncMutation.isError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
          <span className="font-medium">Sync failed</span> — {String(syncMutation.error)}
        </div>
      )}

      {/* Data gap warning — shown when 3+ consecutive $0-cost days are detected
          in the middle of the trend, which indicates missing data rather than
          genuine zero spend.  Leadership should not report on data with gaps. */}
      {gapDaysDetected >= 3 && !syncMutation.isPending && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-800 flex items-start gap-3">
          <svg className="h-5 w-5 text-amber-500 flex-shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
          </svg>
          <div>
            <p className="font-semibold">Data gap detected — not ready for leadership reporting</p>
            <p className="mt-0.5 text-amber-700">
              The chart shows {gapDaysDetected} consecutive days with $0 cost, which indicates missing Azure data rather than genuine zero spend.
              Click <span className="font-medium">Sync from Azure</span> (with <span className="font-medium">Last 12 months</span> selected) to fill the gap.
              Repeat 2–3 times if Azure rate-limits the first attempt.
            </p>
          </div>
        </div>
      )}


      {hasData && summary ? (
        <>
          {/* KPI Cards */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            <KPICard
              label="Total Amortized Cost"
              value={fmtCompact(summary.total_cost)}
              sub={fmtUSD(summary.total_cost)}
              icon={MetricCardIcons.currency()}
              tone="blue"
            />
            <KPICard
              label="Production"
              value={fmtCompact(summary.env_comparison.totals["Prod"] ?? 0)}
              sub={`${((summary.env_comparison.totals["Prod"] ?? 0) / summary.total_cost * 100).toFixed(1)}% of total`}
              icon={MetricCardIcons.shield()}
              tone="emerald"
            />
            <KPICard
              label="Non-Production"
              value={fmtCompact(summary.env_comparison.totals["Non-Prod"] ?? 0)}
              sub={`${((summary.env_comparison.totals["Non-Prod"] ?? 0) / summary.total_cost * 100).toFixed(1)}% of total`}
              icon={MetricCardIcons.cloud()}
              tone="amber"
            />
            <KPICard
              label="Services / Resources"
              value={`${summary.service_breakdown.length} / ${summary.top_resources.length}+`}
              sub={`${summary.subscription_breakdown.length} subscription(s)`}
              icon={MetricCardIcons.layers()}
              tone="purple"
            />
          </div>

          {/* Tabs */}
          <div className="border-b border-gray-200">
            <nav className="flex gap-1 -mb-px">
              {tabs.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setActiveTab(t.id)}
                  className={`px-4 py-2.5 text-sm font-medium border-b-2 transition ${
                    activeTab === t.id
                      ? "border-blue-600 text-blue-600"
                      : "border-transparent text-gray-500 hover:text-gray-700"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </nav>
          </div>

          {/* Tab Content */}
          {activeTab === "overview" && <OverviewTab data={summary} onDrilldown={handleDrilldown} />}
          {activeTab === "services" && <ServicesTab data={summary} onDrilldown={handleDrilldown} />}
          {activeTab === "resources" && <ResourcesTab data={summary} onDrilldown={handleDrilldown} />}
          {activeTab === "pivot" && <PivotTab data={summary} />}
          {activeTab === "drilldown" && (
            <DrilldownTab
              data={drilldownData}
              loading={drilldownLoading}
              filters={drilldownFilter}
              onClearFilters={() => { setDrilldownFilter({}); setDrilldownEnabled(false); }}
            />
          )}

          {/* Footer */}
          <p className="text-xs text-gray-400 text-right">
            Generated at {summary.generated_at ? formatDate(summary.generated_at) : "—"}
          </p>
        </>
      ) : (
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-6 text-center">
          <p className="text-yellow-800 font-medium">No amortized cost data available</p>
          <p className="text-yellow-600 text-sm mt-2">No amortized cost data synced yet. Try triggering a manual sync from the header.</p>
        </div>
      )}
    </div>
  );
};

// ── OVERVIEW TAB ──────────────────────────────────────────────────────

const OverviewTab: React.FC<{
  data: AmortizedCostSummary;
  onDrilldown: (type: string, value: string) => void;
}> = ({ data, onDrilldown }) => {
  // Env comparison monthly chart data
  const envMonthly = useMemo(() => {
    const months = Object.keys(data.env_comparison.monthly).sort();
    return months.map((m) => ({
      month: m,
      Prod: data.env_comparison.monthly[m]["Prod"] ?? 0,
      "Non-Prod": data.env_comparison.monthly[m]["Non-Prod"] ?? 0,
    }));
  }, [data]);

  return (
    <div className="space-y-6">
      {/* Daily Trend — Prod vs Non-Prod */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <SectionTitle title="Daily Cost Trend" sub="Prod vs Non-Prod amortized cost per day" />
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={data.daily_trend}>
              <defs>
                <linearGradient id="gradProd" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="gradNP" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                  <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={fmtDate} />
              <YAxis tick={{ fontSize: 11 }} tickFormatter={(v: number) => fmtCompact(v)} />
              <Tooltip
                formatter={(val: number) => fmtUSD(val)}
                labelFormatter={(l: string) => `Date: ${l}`}
              />
              <Legend />
              <Area type="monotone" dataKey="prod" name="Prod" stroke="#3b82f6" fill="url(#gradProd)" strokeWidth={2} />
              <Area type="monotone" dataKey="non_prod" name="Non-Prod" stroke="#10b981" fill="url(#gradNP)" strokeWidth={2} />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Service Breakdown Donut */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <SectionTitle title="Cost by Service" sub="Top meters by amortized spend" />
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={data.service_breakdown.slice(0, 10)}
                  dataKey="cost"
                  nameKey="name"
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={100}
                  paddingAngle={2}
                  onClick={(entry) => onDrilldown("meter_category", entry.name)}
                  cursor="pointer"
                >
                  {data.service_breakdown.slice(0, 10).map((_, i) => (
                    <Cell key={i} fill={COLORS[i % COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip formatter={(val: number) => fmtUSD(val)} />
                <Legend
                  layout="vertical"
                  align="right"
                  verticalAlign="middle"
                  wrapperStyle={{ fontSize: 12 }}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Monthly Env Comparison */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <SectionTitle title="Monthly Env Comparison" sub="Prod vs Non-Prod by month" />
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={envMonthly}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="month" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} tickFormatter={(v: number) => fmtCompact(v)} />
                <Tooltip formatter={(val: number) => fmtUSD(val)} />
                <Legend />
                <Bar dataKey="Prod" fill="#3b82f6" radius={[4, 4, 0, 0]} />
                <Bar dataKey="Non-Prod" fill="#10b981" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      </div>

      {/* Daily by Service (stacked area) */}
      {data.daily_by_service && data.daily_by_service.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <SectionTitle title="Daily Cost by Service" sub="Top services stacked over time" />
          <div className="h-80">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={data.daily_by_service}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={fmtDate} />
                <YAxis tick={{ fontSize: 11 }} tickFormatter={(v: number) => fmtCompact(v)} />
                <Tooltip formatter={(val: number) => fmtUSD(val)} />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {(data.top_service_names || []).map((svc, i) => (
                  <Area
                    key={svc}
                    type="monotone"
                    dataKey={svc}
                    stackId="1"
                    stroke={COLORS[i % COLORS.length]}
                    fill={COLORS[i % COLORS.length]}
                    fillOpacity={0.6}
                  />
                ))}
                <Area
                  type="monotone"
                  dataKey="Other"
                  stackId="1"
                  stroke="#9ca3af"
                  fill="#9ca3af"
                  fillOpacity={0.4}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Quick breakdowns row */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <BreakdownCard title="By Location" items={data.location_breakdown} />
        <BreakdownCard title="By Charge Type" items={data.charge_type_breakdown as AmortizedBreakdownItem[]} />
        <BreakdownCard title="By Pricing Model" items={data.pricing_model_breakdown as AmortizedBreakdownItem[]} />
      </div>
    </div>
  );
};

// ── SERVICES TAB ──────────────────────────────────────────────────────

const ServicesTab: React.FC<{
  data: AmortizedCostSummary;
  onDrilldown: (type: string, value: string) => void;
}> = ({ data, onDrilldown }) => {
  const [serviceSearch, setServiceSearch] = useState("");
  const [subscriptionSearch, setSubscriptionSearch] = useState("");

  const filteredServices = useMemo(
    () => data.service_breakdown.filter((service) => matchesSearch(serviceSearch, [service.name, service.cost, service.pct])),
    [data.service_breakdown, serviceSearch],
  );
  const filteredSubscriptions = useMemo(
    () => data.subscription_breakdown.filter((subscription) =>
      matchesSearch(subscriptionSearch, [subscription.name, subscription.cost, subscription.pct]),
    ),
    [data.subscription_breakdown, subscriptionSearch],
  );

  const {
    page: servicePage,
    setPage: setServicePage,
    totalPages: serviceTotalPages,
    pagedRows: pagedServices,
  } = usePaginatedRows(filteredServices);
  const {
    page: subscriptionPage,
    setPage: setSubscriptionPage,
    totalPages: subscriptionTotalPages,
    pagedRows: pagedSubscriptions,
  } = usePaginatedRows(filteredSubscriptions);

  return (
  <div className="space-y-6">
    {/* Horizontal Bar Chart */}
    <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
      <SectionTitle title="Service Type Cost Ranking" sub="All meter categories by total amortized cost" />
      <div style={{ height: Math.max(400, data.service_breakdown.length * 32) }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data.service_breakdown} layout="vertical" margin={{ left: 180 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v: number) => fmtCompact(v)} />
            <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={170} />
            <Tooltip formatter={(val: number) => fmtUSD(val)} />
            <Bar dataKey="cost" fill="#3b82f6" radius={[0, 4, 4, 0]} cursor="pointer"
              onClick={(entry) => onDrilldown("meter_category", entry.name)} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>

    {/* Table */}
    <div className={gridStyles.shell}>
      <div className={gridStyles.panelHeader}>
        <SectionTitle
          title="Service Breakdown Table"
          sub={`Showing ${pagedServices.length} of ${filteredServices.length} services`}
          compact
        />
        <GridSearchInput
          value={serviceSearch}
          onChange={setServiceSearch}
          placeholder="Search services..."
        />
      </div>
      <div className="overflow-x-auto">
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              <th className={gridStyles.headerCell}>#</th>
              <th className={gridStyles.headerCell}>Service (Meter Category)</th>
              <th className={`${gridStyles.headerCell} text-right`}>Cost</th>
              <th className={`${gridStyles.headerCell} text-right`}>% of Total</th>
              <th className={gridStyles.headerCellCenter}>Action</th>
            </tr>
          </thead>
          <tbody>
            {pagedServices.map((s, i) => (
              <tr key={s.name} className={gridStyles.row}>
                <td className={gridStyles.cell}>{servicePage * DEFAULT_GRID_PAGE_SIZE + i + 1}</td>
                <td className={gridStyles.strongCell}>{s.name}</td>
                <td className={`${gridStyles.monoCell} text-right`}>{fmtUSD(s.cost)}</td>
                <td className={`${gridStyles.cell} text-right`}>
                  <div className="flex items-center justify-end gap-2">
                    <div className="h-2 w-16 rounded-full bg-att-100">
                      <div
                        className="h-2 rounded-full bg-att-500"
                        style={{ width: `${Math.min(s.pct, 100)}%` }}
                      />
                    </div>
                    <span className="text-gray-600 w-14 text-right">{fmtPct(s.pct)}</span>
                  </div>
                </td>
                <td className={gridStyles.centerCell}>
                  <button
                    onClick={() => onDrilldown("meter_category", s.name)}
                    className="text-att-700 hover:text-att-800 text-xs font-medium"
                  >
                    Drill-down
                  </button>
                </td>
              </tr>
            ))}
            {filteredServices.length === 0 && (
              <tr>
                <td colSpan={5} className="px-4 py-8 text-center text-sm text-gray-400">
                  No services match the current search.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <GridPager
        page={servicePage}
        totalPages={serviceTotalPages}
        pageSize={DEFAULT_GRID_PAGE_SIZE}
        totalItems={filteredServices.length}
        itemLabel="services"
        onPageChange={setServicePage}
      />
    </div>

    {/* Subscription breakdown */}
    <div className={gridStyles.shell}>
      <div className={gridStyles.panelHeader}>
        <SectionTitle
          title="By Subscription"
          sub={`Showing ${pagedSubscriptions.length} of ${filteredSubscriptions.length} subscriptions`}
          compact
        />
        <GridSearchInput
          value={subscriptionSearch}
          onChange={setSubscriptionSearch}
          placeholder="Search subscriptions..."
        />
      </div>
      <div className="overflow-x-auto">
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              <th className={gridStyles.headerCell}>Subscription</th>
              <th className={`${gridStyles.headerCell} text-right`}>Cost</th>
              <th className={`${gridStyles.headerCell} text-right`}>%</th>
              <th className={gridStyles.headerCellCenter}>Action</th>
            </tr>
          </thead>
          <tbody>
            {pagedSubscriptions.map((s) => (
              <tr key={s.name} className={gridStyles.row}>
                <td className={gridStyles.strongCell}>{s.name}</td>
                <td className={`${gridStyles.monoCell} text-right`}>{fmtUSD(s.cost)}</td>
                <td className={`${gridStyles.cell} text-right text-gray-600`}>{fmtPct(s.pct)}</td>
                <td className={gridStyles.centerCell}>
                  <button
                    onClick={() => onDrilldown("subscription", s.name)}
                    className="text-att-700 hover:text-att-800 text-xs font-medium"
                  >
                    Drill-down
                  </button>
                </td>
              </tr>
            ))}
            {filteredSubscriptions.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-sm text-gray-400">
                  No subscriptions match the current search.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <GridPager
        page={subscriptionPage}
        totalPages={subscriptionTotalPages}
        pageSize={DEFAULT_GRID_PAGE_SIZE}
        totalItems={filteredSubscriptions.length}
        itemLabel="subscriptions"
        onPageChange={setSubscriptionPage}
      />
    </div>
  </div>
  );
};

// ── RESOURCES TAB ─────────────────────────────────────────────────────

const ResourcesTab: React.FC<{
  data: AmortizedCostSummary;
  onDrilldown: (type: string, value: string) => void;
}> = ({ data, onDrilldown }) => {
  const [resourceSearch, setResourceSearch] = useState("");
  const [resourceTypeSearch, setResourceTypeSearch] = useState("");

  const filtered = useMemo(
    () =>
      data.top_resources.filter((resource) =>
        matchesSearch(resourceSearch, [
          resource.resource_name,
          resource.resource_group,
          resource.meter_category,
          resource.resource_type,
          resource.location,
          resource.subscription,
          resource.cost,
        ]),
      ),
    [data.top_resources, resourceSearch],
  );
  const filteredResourceTypes = useMemo(
    () =>
      data.resource_type_breakdown.filter((resourceType) =>
        matchesSearch(resourceTypeSearch, [resourceType.name, resourceType.cost, resourceType.pct]),
      ),
    [data.resource_type_breakdown, resourceTypeSearch],
  );

  const {
    page: resourcePage,
    setPage: setResourcePage,
    totalPages: resourceTotalPages,
    pagedRows: pagedResources,
  } = usePaginatedRows(filtered);
  const {
    page: resourceTypePage,
    setPage: setResourceTypePage,
    totalPages: resourceTypeTotalPages,
    pagedRows: pagedResourceTypes,
  } = usePaginatedRows(filteredResourceTypes);

  return (
    <div className="space-y-6">
      {/* Resource Group bar chart */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
        <SectionTitle title="Top Resource Groups" sub="Click a bar to drill down" />
        <div style={{ height: Math.max(300, Math.min(data.resource_group_breakdown.length, 20) * 30) }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart
              data={data.resource_group_breakdown.slice(0, 20)}
              layout="vertical"
              margin={{ left: 220 }}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={(v: number) => fmtCompact(v)} />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={210} />
              <Tooltip formatter={(val: number) => fmtUSD(val)} />
              <Bar
                dataKey="cost"
                fill="#8b5cf6"
                radius={[0, 4, 4, 0]}
                cursor="pointer"
                onClick={(entry) => onDrilldown("resource_group", entry.name)}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>

      {/* Top Resources Table */}
      <div className={gridStyles.shell}>
        <div className={gridStyles.panelHeader}>
          <SectionTitle title="Top Resources by Cost" sub={`Showing ${pagedResources.length} of ${filtered.length}`} compact />
          <GridSearchInput
            value={resourceSearch}
            onChange={setResourceSearch}
            placeholder="Search resources..."
          />
        </div>
        <div className="overflow-x-auto max-h-[600px] overflow-y-auto">
          <table className={gridStyles.table}>
            <thead className={`${gridStyles.head} ${gridStyles.stickyHead}`}>
              <tr>
                <th className={gridStyles.headerCell}>#</th>
                <th className={gridStyles.headerCell}>Resource</th>
                <th className={gridStyles.headerCell}>Resource Group</th>
                <th className={gridStyles.headerCell}>Service</th>
                <th className={gridStyles.headerCell}>Location</th>
                <th className={gridStyles.headerCell}>Subscription</th>
                <th className={`${gridStyles.headerCell} text-right`}>Cost</th>
              </tr>
            </thead>
            <tbody>
              {pagedResources.map((r, i) => (
                <tr key={`${r.resource_name}-${r.resource_group}-${i}`} className={gridStyles.row}>
                  <td className={gridStyles.cell}>{resourcePage * DEFAULT_GRID_PAGE_SIZE + i + 1}</td>
                  <td className={`${gridStyles.strongCell} max-w-xs truncate`} title={r.resource_name}>
                    {r.resource_name}
                  </td>
                  <td className={gridStyles.cell}>
                    {r.resource_group ? (
                      <button
                        onClick={() => onDrilldown("resource_group", r.resource_group)}
                        className="text-att-700 hover:underline"
                      >
                        {r.resource_group}
                      </button>
                    ) : (
                      <span className="text-gray-400" title="Azure did not attribute this charge to a resource group">
                        —
                      </span>
                    )}
                  </td>
                  <td className={gridStyles.cell}>{r.meter_category}</td>
                  <td className={gridStyles.cell}>
                    {r.location || (
                      <span className="text-gray-400" title="Location unavailable for subscription-level or partially enriched charges">
                        —
                      </span>
                    )}
                  </td>
                  <td className={`${gridStyles.cell} max-w-[160px] truncate`} title={r.subscription}>
                    {r.subscription}
                  </td>
                  <td className={`${gridStyles.monoCell} text-right font-medium text-gray-900`}>{fmtUSD(r.cost)}</td>
                </tr>
              ))}
              {filtered.length === 0 && (
                <tr>
                  <td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-400">
                    No resources match the current search.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <GridPager
          page={resourcePage}
          totalPages={resourceTotalPages}
          pageSize={DEFAULT_GRID_PAGE_SIZE}
          totalItems={filtered.length}
          itemLabel="resources"
          onPageChange={setResourcePage}
        />
      </div>

      {/* Resource Type breakdown */}
      <div className={gridStyles.shell}>
        <div className={gridStyles.panelHeader}>
          <SectionTitle
            title="By Resource Type"
            sub={`Showing ${pagedResourceTypes.length} of ${filteredResourceTypes.length} resource types`}
            compact
          />
          <GridSearchInput
            value={resourceTypeSearch}
            onChange={setResourceTypeSearch}
            placeholder="Search resource types..."
          />
        </div>
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}>Resource Type</th>
                <th className={`${gridStyles.headerCell} text-right`}>Cost</th>
                <th className={`${gridStyles.headerCell} text-right`}>%</th>
              </tr>
            </thead>
            <tbody>
              {pagedResourceTypes.map((r) => (
                <tr key={r.name} className={gridStyles.row}>
                  <td className={`${gridStyles.strongCell} max-w-md truncate`} title={r.name}>{r.name}</td>
                  <td className={`${gridStyles.monoCell} text-right`}>{fmtUSD(r.cost)}</td>
                  <td className={`${gridStyles.cell} text-right text-gray-600`}>{fmtPct(r.pct)}</td>
                </tr>
              ))}
              {filteredResourceTypes.length === 0 && (
                <tr>
                  <td colSpan={3} className="px-4 py-8 text-center text-sm text-gray-400">
                    No resource types match the current search.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <GridPager
          page={resourceTypePage}
          totalPages={resourceTypeTotalPages}
          pageSize={DEFAULT_GRID_PAGE_SIZE}
          totalItems={filteredResourceTypes.length}
          itemLabel="resource types"
          onPageChange={setResourceTypePage}
        />
      </div>
    </div>
  );
};

// ── MONTHLY PIVOT TAB ─────────────────────────────────────────────────

const PivotTab: React.FC<{ data: AmortizedCostSummary }> = ({ data }) => {
  const [pivotSearch, setPivotSearch] = useState("");
  const pivot = data.monthly_pivot;
  const pivotServices = pivot?.services ?? [];
  const pivotMonths = pivot?.months ?? [];
  const hasPivotData = pivotMonths.length > 0;

  const filteredServices = useMemo(
    () => pivotServices.filter((service) => matchesSearch(pivotSearch, [service.service_name, service.total])),
    [pivotServices, pivotSearch],
  );
  const {
    page: pivotPage,
    setPage: setPivotPage,
    totalPages: pivotTotalPages,
    pagedRows: pagedPivotServices,
  } = usePaginatedRows(filteredServices);

  if (!hasPivotData || !pivot) {
    return (
      <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-6 text-center">
        <p className="text-yellow-800">No monthly pivot data available.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className={gridStyles.shell}>
      <div className={gridStyles.panelHeader}>
        <SectionTitle
          title="Monthly Cost Pivot — Service x Month"
          sub={`Showing ${pagedPivotServices.length} of ${filteredServices.length} services`}
          compact
        />
        <GridSearchInput
          value={pivotSearch}
          onChange={setPivotSearch}
          placeholder="Search services..."
        />
      </div>
      <div className="overflow-x-auto max-h-[700px] overflow-y-auto">
        <table className={gridStyles.table}>
          <thead className={`${gridStyles.head} ${gridStyles.stickyHead}`}>
            <tr>
              <th className={`${gridStyles.headerCell} sticky left-0 z-20 min-w-[220px] bg-att-50/95`}>
                Service Type
              </th>
              {pivot.months.map((m) => (
                <th key={m} className={`${gridStyles.headerCell} min-w-[120px] text-right`}>
                  {pivot.month_labels[m] || m}
                </th>
              ))}
              <th className="min-w-[130px] bg-att-100 px-4 py-3 text-right text-xs font-bold uppercase tracking-[0.12em] text-att-800">
                Total
              </th>
            </tr>
          </thead>
          <tbody>
            {pagedPivotServices.map((svc, i) => (
              <tr key={svc.service_name} className={`${gridStyles.row} ${i < 3 ? "bg-amber-50/50" : ""}`}>
                <td className="sticky left-0 z-10 bg-white px-4 py-2.5 font-medium text-gray-900" title={svc.service_name}>
                  <div className="flex items-center gap-2">
                    {i < 3 && <span className="text-amber-500 text-xs">#{pivotPage * DEFAULT_GRID_PAGE_SIZE + i + 1}</span>}
                    <span className="truncate max-w-[200px]">{svc.service_name}</span>
                  </div>
                </td>
                {pivot.months.map((m) => (
                  <td key={m} className={`${gridStyles.monoCell} text-right`}>
                    {fmtUSD(svc.monthly_costs[m] ?? 0)}
                  </td>
                ))}
                <td className="bg-att-50 px-4 py-2.5 text-right font-mono font-semibold text-gray-900">
                  {fmtUSD(svc.total)}
                </td>
              </tr>
            ))}
            {filteredServices.length === 0 && (
              <tr>
                <td colSpan={pivot.months.length + 2} className="px-4 py-8 text-center text-sm text-gray-400">
                  No services match the current search.
                </td>
              </tr>
            )}
          </tbody>
          <tfoot className="sticky bottom-0 bg-gray-100">
            <tr className="font-bold">
              <td className="px-4 py-3 text-gray-900 sticky left-0 bg-gray-100">Grand Total</td>
              {pivot.months.map((m) => (
                <td key={m} className="px-4 py-3 text-right font-mono text-gray-900">
                  {fmtUSD(pivot.monthly_totals[m] ?? 0)}
                </td>
              ))}
              <td className="bg-att-100 px-4 py-3 text-right font-mono text-att-800">
                {fmtUSD(pivot.grand_total)}
              </td>
            </tr>
          </tfoot>
        </table>
      </div>
      <GridPager
        page={pivotPage}
        totalPages={pivotTotalPages}
        pageSize={DEFAULT_GRID_PAGE_SIZE}
        totalItems={filteredServices.length}
        itemLabel="services"
        onPageChange={setPivotPage}
      />
    </div>
    </div>
  );
};

// ── DRILLDOWN TAB ─────────────────────────────────────────────────────

const DrilldownTab: React.FC<{
  data: ReturnType<typeof useAmortizedDrilldown>["data"];
  loading: boolean;
  filters: Record<string, string | undefined>;
  onClearFilters: () => void;
}> = ({ data, loading, filters, onClearFilters }) => {
  const [resourceSearch, setResourceSearch] = useState("");
  const activeFilters = Object.entries(filters).filter(([, v]) => v);
  const drilldownResources = data?.resources ?? [];

  const filteredResources = useMemo(
    () =>
      drilldownResources.filter((resource) =>
        matchesSearch(resourceSearch, [
          resource.resource_name,
          resource.resource_group,
          resource.resource_type,
          resource.meter_category,
          resource.location,
          resource.active_days,
          resource.cost,
        ]),
      ),
    [drilldownResources, resourceSearch],
  );
  const {
    page: resourcePage,
    setPage: setResourcePage,
    totalPages: resourceTotalPages,
    pagedRows: pagedResources,
  } = usePaginatedRows(filteredResources);

  if (loading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600" />
      </div>
    );
  }

  if (!data && activeFilters.length === 0) {
    return (
      <div className="bg-blue-50 border border-blue-200 rounded-xl p-8 text-center">
        <p className="text-blue-800 font-medium text-lg mb-2">Select a drill-down target</p>
        <p className="text-blue-600 text-sm">
          Click on a service, resource group, or subscription in the other tabs to see
          resource-level details here.
        </p>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="space-y-6">
      {/* Filter badges */}
      <div className="flex items-center gap-3 flex-wrap">
        <span className="text-sm font-medium text-gray-700">Filters:</span>
        {activeFilters.map(([k, v]) => (
          <span
            key={k}
            className="inline-flex items-center gap-1 px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm font-medium"
          >
            {k.replace("_", " ")}: {v}
          </span>
        ))}
        <button
          onClick={onClearFilters}
          className="text-sm text-red-600 hover:text-red-800 font-medium"
        >
          Clear filters
        </button>
        <span className="text-sm text-gray-500 ml-auto">
          Total: {fmtUSD(data.total_cost)} &bull; {data.row_count.toLocaleString()} line items
        </span>
      </div>

      {/* Daily trend for filtered set */}
      {data.daily_trend.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-6">
          <SectionTitle title="Daily Cost (filtered)" />
          <div className="h-64">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data.daily_trend}>
                <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} tickFormatter={fmtDate} />
                <YAxis tick={{ fontSize: 11 }} tickFormatter={(v: number) => fmtCompact(v)} />
                <Tooltip formatter={(val: number) => fmtUSD(val)} />
                <Line type="monotone" dataKey="cost" stroke="#3b82f6" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Resource table */}
      <div className={gridStyles.shell}>
        <div className={gridStyles.panelHeader}>
          <SectionTitle
            title="Resources"
            sub={`Showing ${pagedResources.length} of ${filteredResources.length} resource(s)`}
            compact
          />
          <GridSearchInput
            value={resourceSearch}
            onChange={setResourceSearch}
            placeholder="Search drill-down resources..."
          />
        </div>
        <div className="overflow-x-auto max-h-[500px] overflow-y-auto">
          <table className={gridStyles.table}>
            <thead className={`${gridStyles.head} ${gridStyles.stickyHead}`}>
              <tr>
                <th className={gridStyles.headerCell}>#</th>
                <th className={gridStyles.headerCell}>Resource Name</th>
                <th className={gridStyles.headerCell}>Resource Group</th>
                <th className={gridStyles.headerCell}>Type</th>
                <th className={gridStyles.headerCell}>Service</th>
                <th className={gridStyles.headerCell}>Location</th>
                <th className={`${gridStyles.headerCell} text-right`}>Active Days</th>
                <th className={`${gridStyles.headerCell} text-right`}>Cost</th>
              </tr>
            </thead>
            <tbody>
              {pagedResources.map((r, i) => (
                <tr key={`${r.resource_name}-${i}`} className={gridStyles.row}>
                  <td className={gridStyles.cell}>{resourcePage * DEFAULT_GRID_PAGE_SIZE + i + 1}</td>
                  <td className={`${gridStyles.strongCell} max-w-xs truncate`} title={r.resource_name}>
                    {r.resource_name || <span className="text-gray-400 italic">—</span>}
                  </td>
                  <td className={gridStyles.cell}>{r.resource_group}</td>
                  <td className={`${gridStyles.cell} max-w-[160px] truncate`} title={r.resource_type || undefined}>
                    {r.resource_type || <span className="text-gray-400">—</span>}
                  </td>
                  <td className={gridStyles.cell}>{r.meter_category}</td>
                  <td className={gridStyles.cell}>
                    {r.location || <span className="text-gray-400">—</span>}
                  </td>
                  <td className={`${gridStyles.cell} text-right text-gray-600`}>{r.active_days}</td>
                  <td className={`${gridStyles.monoCell} text-right font-medium text-gray-900`}>{fmtUSD(r.cost)}</td>
                </tr>
              ))}
              {filteredResources.length === 0 && (
                <tr>
                  <td colSpan={8} className="px-4 py-8 text-center text-sm text-gray-400">
                    No resources match the current search.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
        <GridPager
          page={resourcePage}
          totalPages={resourceTotalPages}
          pageSize={DEFAULT_GRID_PAGE_SIZE}
          totalItems={filteredResources.length}
          itemLabel="resources"
          onPageChange={setResourcePage}
        />
      </div>
    </div>
  );
};

// ── Breakdown Card (reusable) ─────────────────────────────────────────

const BreakdownCard: React.FC<{
  title: string;
  items: AmortizedBreakdownItem[];
}> = ({ title, items }) => (
  <div className="bg-white rounded-xl shadow-sm border border-gray-200 p-5">
    <h3 className="text-sm font-semibold text-gray-700 mb-3">{title}</h3>
    <div className="space-y-2">
      {items.slice(0, 8).map((item) => (
        <div key={item.name} className="flex items-center justify-between text-sm">
          <span className="text-gray-700 truncate max-w-[60%]" title={item.name}>
            {item.name}
          </span>
          <span className="font-mono text-gray-900">{fmtCompact(item.cost)}</span>
        </div>
      ))}
    </div>
  </div>
);

export default AmortizedCostDashboard;
