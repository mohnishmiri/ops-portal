/**
 * Leadership Dashboard — Executive-ready KPIs, trends, and savings.
 *
 * Primary audience: VPs, Directors, FinOps stakeholders.
 */

import React from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  BarChart,
  Bar,
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  Legend,
} from "recharts";
import {
  useLeadershipDashboard,
  useOptimizationSummary,
  refreshLeadershipDashboard,
  refreshOptimizationSummary,
  useNonProdVsProdTrend,
  useLeadershipSyncStatus,
  useLeadershipCostAdvisor,
  useLeadershipCostForecast,
  useOllamaStatus,
  KPIMetric,
  MonthlyCostPoint,
  NonProdVsProdPoint,
  WastageDetailItem,
} from "../services/costApi";
import type {
  LeadershipDashboard as LeadershipDashboardData,
  OptimizationSummary,
  NonProdVsProdTrend,
} from "../services/costApi";
import { usePortalTimezone } from "../contexts/TimezoneContext";
import { MetricCard, MetricCardIcons } from "../components/MetricCard";

const COLORS = [
  "#1976d2",
  "#388e3c",
  "#f57c00",
  "#d32f2f",
  "#7b1fa2",
  "#0097a7",
  "#fbc02d",
  "#455a64",
];

// ── KPI Card ──────────────────────────────────────────────────────────

interface KPICardProps {
  metric: KPIMetric;
}

const KPICard: React.FC<KPICardProps> = ({ metric }) => {
  const trendIcon =
    metric.trend === "up" ? "▲" : metric.trend === "down" ? "▼" : "●";
  const trendColor =
    metric.trend === "up"
      ? "text-red-500"
      : metric.trend === "down"
      ? "text-green-500"
      : "text-gray-400";

  const formatValue = (value: number, unit: string) => {
    if (unit === "USD" || unit === "USD/year") {
      return `$${value.toLocaleString(undefined, {
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
      })}`;
    }
    if (unit === "%") return `${value.toFixed(1)}%`;
    return value.toLocaleString();
  };

  const metricName = metric.name.toLowerCase();
  const tone = metricName.includes("savings")
    ? "green"
    : metricName.includes("recommend")
      ? "purple"
      : metricName.includes("budget")
        ? "amber"
        : "blue";
  const icon = metricName.includes("savings")
    ? MetricCardIcons.chart()
    : metricName.includes("recommend")
      ? MetricCardIcons.layers()
      : metricName.includes("budget")
        ? MetricCardIcons.alert()
        : MetricCardIcons.currency();

  return (
    <MetricCard
      title={metric.name}
      value={formatValue(metric.value, metric.unit)}
      subtitle={metric.description}
      icon={icon}
      tone={tone}
      meta={
        <span className={`text-sm font-semibold ${trendColor}`}>
          {trendIcon} {Math.abs(metric.change_pct).toFixed(1)}%
        </span>
      }
    />
  );
};

// ── Cost Trend Chart ──────────────────────────────────────────────────

interface TrendChartProps {
  data: Array<{ date: string; cost: number; group_value?: string }>;
}

interface TrendPivotPoint {
  date: string;
  total: number;
  [key: string]: string | number;
}

const SUB_COLORS: Record<string, string> = {};
const PALETTE = ["#1976d2", "#e65100", "#2e7d32", "#7b1fa2", "#c62828", "#00838f"];

const CostTrendChart: React.FC<TrendChartProps> = ({ data }) => {
  const { timezone } = usePortalTimezone();
  // Pivot: one row per date, one column per subscription + total
  const { pivoted, subs } = React.useMemo(() => {
    const subsSet = new Set<string>();
    const dateMap = new Map<string, Record<string, number>>();

    for (const d of data) {
      const cost = typeof d.cost === "string" ? parseFloat(d.cost) : d.cost;
      const sub = d.group_value || "Unknown";
      subsSet.add(sub);
      if (!dateMap.has(d.date)) dateMap.set(d.date, { total: 0 });
      const row = dateMap.get(d.date)!;
      row[sub] = (row[sub] || 0) + cost;
      row.total = (row.total || 0) + cost;
    }

    const sortedDates = Array.from(dateMap.keys()).sort();
    const pivoted: TrendPivotPoint[] = sortedDates.map((date) => {
      const row = dateMap.get(date) || { total: 0 };
      return {
        date,
        total: Number(row.total || 0),
        ...row,
      };
    });

    const subs = Array.from(subsSet);
    // Assign stable colors
    subs.forEach((s, i) => {
      if (!SUB_COLORS[s]) SUB_COLORS[s] = PALETTE[i % PALETTE.length];
    });

    return { pivoted, subs };
  }, [data]);

  const trendSummary = React.useMemo(() => {
    if (!pivoted.length) return null;

    const latest = pivoted[pivoted.length - 1];
    const previous = pivoted.length > 1 ? pivoted[pivoted.length - 2] : null;
    const peak = pivoted.reduce((highest, point) =>
      Number(point.total || 0) > Number(highest.total || 0) ? point : highest
    );
    const average = pivoted.reduce((sum, point) => sum + Number(point.total || 0), 0) / pivoted.length;
    const delta = previous?.total
      ? ((Number(latest.total || 0) - Number(previous.total || 0)) / Number(previous.total || 0)) * 100
      : null;

    return {
      latest,
      peak,
      average,
      delta,
    };
  }, [pivoted]);

  return (
    <section className="relative overflow-hidden rounded-2xl border border-att-100 bg-gradient-to-br from-white via-white to-att-50/70 p-6 shadow-sm shadow-att-100/40">
      <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-att-300 via-att-500 to-blue-300" />
      <div className="mb-5">
        <div className="max-w-3xl">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-att-100 px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-att-700">Short-Horizon Trend</span>
            <span className="rounded-full bg-white/90 px-3 py-1 text-xs font-medium text-slate-600 ring-1 ring-att-100">Last 15 days</span>
            <span className="rounded-full bg-white/90 px-3 py-1 text-xs font-medium text-slate-600 ring-1 ring-att-100">{subs.length} subscriptions tracked</span>
          </div>
          <div className="mt-4 flex items-start gap-3">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-att-100 text-att-700 ring-1 ring-white/60">
              {MetricCardIcons.activity()}
            </div>
            <h3 className="text-xl font-semibold text-slate-900">Daily Cost Trend</h3>
          </div>
        </div>
        {trendSummary ? (
          <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-3">
            <MetricCard
              title="Latest Day"
              value={fmtCompact(Number(trendSummary.latest.total || 0))}
              subtitle={new Date(trendSummary.latest.date).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: timezone })}
              icon={MetricCardIcons.currency()}
              tone="att"
              valueClassName="text-xl"
              meta={trendSummary.delta != null ? (
                <span className={`text-xs font-semibold ${trendSummary.delta >= 0 ? "text-amber-600" : "text-emerald-600"}`}>
                  {trendSummary.delta >= 0 ? "▲" : "▼"} {fmtPercent(Math.abs(trendSummary.delta))}
                </span>
              ) : undefined}
            />
            <MetricCard
              title="Peak Day"
              value={fmtCompact(Number(trendSummary.peak.total || 0))}
              subtitle={new Date(trendSummary.peak.date).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: timezone })}
              icon={MetricCardIcons.alert()}
              tone="amber"
              valueClassName="text-xl"
            />
            <MetricCard
              title="Daily Average"
              value={fmtCompact(trendSummary.average)}
              subtitle="Average across current window"
              icon={MetricCardIcons.chart()}
              tone="blue"
              valueClassName="text-xl"
            />
          </div>
        ) : null}
      </div>
      <div className="rounded-2xl border border-att-100 bg-white/90 p-4 shadow-sm">
        <ResponsiveContainer width="100%" height={320}>
          <LineChart data={pivoted}>
            <CartesianGrid strokeDasharray="3 3" stroke="#d5ecf7" />
            <XAxis
              dataKey="date"
              tick={{ fontSize: 12 }}
              tickFormatter={(val) => new Date(val).toLocaleDateString("en-US", { day: "numeric", month: "short", timeZone: timezone })}
            />
            <YAxis
              tick={{ fontSize: 12 }}
              tickFormatter={(val) => `$${(val / 1000).toFixed(1)}k`}
            />
            <Tooltip
              formatter={(value: number, name: string) => [
                `$${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`,
                name === "total" ? "Total" : name,
              ]}
              labelFormatter={(label) =>
                new Date(label).toLocaleDateString("en-US", {
                  month: "long",
                  day: "numeric",
                  year: "numeric",
                  timeZone: timezone,
                })
              }
              contentStyle={{ borderRadius: "16px", border: "1px solid #b0d8ee", boxShadow: "0 10px 30px rgba(63,155,202,0.12)" }}
            />
            <Legend
              formatter={(value: string) => (value === "total" ? "Total" : value)}
              wrapperStyle={{ fontSize: 12, paddingTop: 12 }}
            />
            {subs.map((sub) => (
              <Line
                key={sub}
                type="monotone"
                dataKey={sub}
                name={sub}
                stroke={SUB_COLORS[sub]}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 5 }}
              />
            ))}
            <Line
              type="monotone"
              dataKey="total"
              name="total"
              stroke="#2d7aa8"
              strokeWidth={3}
              dot={{ r: 2 }}
              activeDot={{ r: 6 }}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
};

// ── Helper formatters ─────────────────────────────────────────────────

const fmtUSD = (v: number) =>
  `$${v.toLocaleString(undefined, { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;

const fmtCompact = (v: number) =>
  v >= 1_000_000
    ? `$${(v / 1_000_000).toFixed(1)}M`
    : v >= 1_000
    ? `$${(v / 1_000).toFixed(1)}k`
    : `$${v.toFixed(0)}`;

const fmtPercent = (v: number) => `${v.toFixed(1)}%`;

// ── Enhanced Wastage Detail Tile ──────────────────────────────────────

interface WastageDetailTileProps {
  wastage: {
    total_monthly_waste: number;
    idle_vms_count: number;
    unattached_disks_count: number;
    orphaned_snapshots_count: number;
    overprovisioned_count: number;
    details: WastageDetailItem[];
  };
  totalAnnualSavings: number;
}

const PRIORITY_COLORS: Record<string, string> = {
  critical: "bg-red-100 text-red-700",
  high: "bg-orange-100 text-orange-700",
  medium: "bg-yellow-100 text-yellow-700",
  low: "bg-green-100 text-green-700",
};

const PAGE_SIZE_OPTIONS = [5, 10, 20, 50];

const WastageDetailTile: React.FC<WastageDetailTileProps> = ({
  wastage,
  totalAnnualSavings,
}) => {
  const [expandedCat, setExpandedCat] = React.useState<string | null>(null);
  const [categorySearch, setCategorySearch] = React.useState("");
  // Per-category resource search + pagination state
  const [resourceSearch, setResourceSearch] = React.useState<Record<string, string>>({});
  const [currentPage, setCurrentPage] = React.useState<Record<string, number>>({});
  const [pageSize, setPageSize] = React.useState<Record<string, number>>({});

  const getResourceSearch = (cat: string) => resourceSearch[cat] || "";
  const getCurrentPage = (cat: string) => currentPage[cat] || 1;
  const getPageSize = (cat: string) => pageSize[cat] || 10;

  // Filter categories by search
  const filteredDetails = React.useMemo(() => {
    if (!wastage.details) return [];
    if (!categorySearch.trim()) return wastage.details;
    const q = categorySearch.toLowerCase();
    return wastage.details.filter(
      (d) =>
        d.category.toLowerCase().includes(q) ||
        d.resources.some(
          (r) =>
            (r.name || r.title || "").toLowerCase().includes(q) ||
            (r.resource_group || "").toLowerCase().includes(q)
        )
    );
  }, [wastage.details, categorySearch]);

  // Filter + paginate resources for a given category
  const getFilteredResources = React.useCallback(
    (detail: WastageDetailItem) => {
      const q = getResourceSearch(detail.category).toLowerCase();
      let resources = detail.resources;
      if (q) {
        resources = resources.filter(
          (r) =>
            (r.name || r.title || "").toLowerCase().includes(q) ||
            (r.resource_group || "").toLowerCase().includes(q) ||
            (r.recommendation || "").toLowerCase().includes(q) ||
            (r.current_sku || "").toLowerCase().includes(q) ||
            (r.recommended_sku || "").toLowerCase().includes(q)
        );
      }
      return resources;
    },
    [resourceSearch]
  );

  const getPaginatedResources = React.useCallback(
    (detail: WastageDetailItem) => {
      const filtered = getFilteredResources(detail);
      const page = getCurrentPage(detail.category);
      const size = getPageSize(detail.category);
      const start = (page - 1) * size;
      return {
        items: filtered.slice(start, start + size),
        totalFiltered: filtered.length,
        totalPages: Math.ceil(filtered.length / size),
      };
    },
    [getFilteredResources, currentPage, pageSize]
  );

  const wastageCards = [
    {
      title: "Idle VMs",
      value: wastage.idle_vms_count.toLocaleString(),
      subtitle: "No meaningful utilization",
      icon: MetricCardIcons.server(),
      tone: "orange" as const,
    },
    {
      title: "Unattached Disks",
      value: wastage.unattached_disks_count.toLocaleString(),
      subtitle: "Detached from workloads",
      icon: MetricCardIcons.database(),
      tone: "amber" as const,
    },
    {
      title: "Orphaned Snapshots",
      value: wastage.orphaned_snapshots_count.toLocaleString(),
      subtitle: "Likely retirable",
      icon: MetricCardIcons.layers(),
      tone: "red" as const,
    },
    {
      title: "Overprovisioned",
      value: wastage.overprovisioned_count.toLocaleString(),
      subtitle: "Sized above observed demand",
      icon: MetricCardIcons.alert(),
      tone: "amber" as const,
    },
    {
      title: "Annual Savings Potential",
      value: fmtUSD(totalAnnualSavings),
      subtitle: "Recoverable from current waste",
      icon: MetricCardIcons.chart(),
      tone: "green" as const,
    },
  ];

  return (
    <section className="relative overflow-hidden rounded-2xl border border-att-100 bg-gradient-to-br from-white via-white to-att-50/70 p-6 shadow-sm shadow-att-100/40">
      <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-orange-200 via-orange-500 to-emerald-300" />
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="max-w-3xl">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-att-100 px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-att-700">Wastage Summary</span>
            <span className="rounded-full bg-white/90 px-3 py-1 text-xs font-medium text-slate-600 ring-1 ring-att-100">Monthly waste: {fmtUSD(wastage.total_monthly_waste)}</span>
            <span className="rounded-full bg-white/90 px-3 py-1 text-xs font-medium text-slate-600 ring-1 ring-att-100">Annual opportunity: {fmtUSD(totalAnnualSavings)}</span>
          </div>
          <h3 className="mt-4 text-xl font-semibold text-slate-900">Resource Waste Signals</h3>
        </div>
        <div className="rounded-xl bg-att-50 px-4 py-3 text-right">
          <p className="text-xs font-semibold uppercase tracking-[0.12em] text-att-700">Waste Categories</p>
          <p className="mt-1 text-2xl font-bold text-slate-900">{wastage.details?.length ?? 0}</p>
          <p className="text-xs text-slate-500">Current optimization groupings</p>
        </div>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
        {wastageCards.map((card) => (
          <MetricCard
            key={card.title}
            title={card.title}
            value={card.value}
            subtitle={card.subtitle}
            icon={card.icon}
            tone={card.tone}
            className="h-full"
            valueClassName="text-3xl"
          />
        ))}
      </div>

      {/* Per-category breakdown */}
      {wastage.details && wastage.details.length > 0 && (
        <div className="mt-6 rounded-2xl border border-att-100 bg-white/90 p-5 shadow-sm">
          <div className="mb-4 flex items-center justify-between gap-3">
            <h4 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-600">
              Breakdown by Category
            </h4>
            <div className="relative">
              <svg xmlns="http://www.w3.org/2000/svg" className="absolute left-2.5 top-2 w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><circle cx="11" cy="11" r="8"/><path strokeLinecap="round" d="m21 21-4.35-4.35"/></svg>
              <input
                type="text"
                placeholder="Search categories..."
                value={categorySearch}
                onChange={(e) => setCategorySearch(e.target.value)}
                className="w-56 rounded-xl border border-att-100 bg-white pl-8 pr-3 py-2 text-xs text-slate-700 shadow-sm focus:outline-none focus:ring-2 focus:ring-att-300"
              />
              {categorySearch && (
                <button
                  onClick={() => setCategorySearch("")}
                  className="absolute right-2 top-2 text-gray-400 hover:text-gray-600"
                >
                  <svg xmlns="http://www.w3.org/2000/svg" className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" d="M6 18L18 6M6 6l12 12"/></svg>
                </button>
              )}
            </div>
          </div>

          {filteredDetails.length === 0 && (
            <p className="text-sm text-gray-500 text-center py-4">No categories match your search.</p>
          )}

          {filteredDetails.map((detail) => {
            const { items: paginatedResources, totalFiltered, totalPages } =
              getPaginatedResources(detail);
            const page = getCurrentPage(detail.category);
            const size = getPageSize(detail.category);

            return (
              <div
                key={detail.category}
                className="overflow-hidden rounded-2xl border border-att-100 bg-gradient-to-br from-white via-white to-att-50/50"
              >
                <button
                  className="flex w-full items-center justify-between px-4 py-3 transition hover:bg-att-50/80"
                  onClick={() =>
                    setExpandedCat(
                      expandedCat === detail.category ? null : detail.category
                    )
                  }
                >
                  <div className="flex items-center gap-3">
                    <span className="font-medium text-slate-800">
                      {detail.category}
                    </span>
                    <span className="rounded-full bg-att-100 px-2 py-0.5 text-xs text-att-700">
                      {detail.count} items
                    </span>
                  </div>
                  <div className="flex items-center gap-4 text-sm">
                    <span className="font-semibold text-amber-600">
                      ${detail.monthly_waste.toLocaleString()}/mo
                    </span>
                    <span className="text-emerald-600">
                      ${detail.annual_waste.toLocaleString()}/yr
                    </span>
                    <span className="text-gray-400">
                      {expandedCat === detail.category ? "▲" : "▼"}
                    </span>
                  </div>
                </button>

                {expandedCat === detail.category &&
                  detail.resources.length > 0 && (
                    <div className="border-t border-att-100 px-4 pb-3">
                      <div className="mb-2 mt-2 flex items-center justify-between gap-3">
                        <div className="relative flex-1 max-w-xs">
                          <svg xmlns="http://www.w3.org/2000/svg" className="absolute left-2.5 top-2 w-4 h-4 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><circle cx="11" cy="11" r="8"/><path strokeLinecap="round" d="m21 21-4.35-4.35"/></svg>
                          <input
                            type="text"
                            placeholder="Search resources..."
                            value={getResourceSearch(detail.category)}
                            onChange={(e) => {
                              setResourceSearch((prev) => ({
                                ...prev,
                                [detail.category]: e.target.value,
                              }));
                              setCurrentPage((prev) => ({
                                ...prev,
                                [detail.category]: 1,
                              }));
                            }}
                            className="w-full rounded-xl border border-att-100 bg-white pl-8 pr-3 py-2 text-xs text-slate-700 shadow-sm focus:outline-none focus:ring-2 focus:ring-att-300"
                          />
                          {getResourceSearch(detail.category) && (
                            <button
                              onClick={() => {
                                setResourceSearch((prev) => ({
                                  ...prev,
                                  [detail.category]: "",
                                }));
                                setCurrentPage((prev) => ({
                                  ...prev,
                                  [detail.category]: 1,
                                }));
                              }}
                              className="absolute right-2 top-2 text-gray-400 hover:text-gray-600"
                            >
                              <svg xmlns="http://www.w3.org/2000/svg" className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" d="M6 18L18 6M6 6l12 12"/></svg>
                            </button>
                          )}
                        </div>

                        <div className="flex items-center gap-2 text-xs text-gray-500">
                          <span>Show</span>
                          <select
                            value={size}
                            onChange={(e) => {
                              setPageSize((prev) => ({
                                ...prev,
                                [detail.category]: Number(e.target.value),
                              }));
                              setCurrentPage((prev) => ({
                                ...prev,
                                [detail.category]: 1,
                              }));
                            }}
                            className="rounded-lg border border-att-100 px-1.5 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-att-300"
                          >
                            {PAGE_SIZE_OPTIONS.map((opt) => (
                              <option key={opt} value={opt}>
                                {opt}
                              </option>
                            ))}
                          </select>
                          <span>
                            of {totalFiltered} resource{totalFiltered !== 1 ? "s" : ""}
                          </span>
                        </div>
                      </div>

                      {/* Resource table */}
                      <div className="overflow-x-auto">
                        <table className="w-full text-xs">
                          <thead>
                            <tr className="border-b border-att-100 text-gray-500">
                              <th className="text-left py-1.5 pr-2">Resource</th>
                              <th className="text-left py-1.5 pr-2">Resource Group</th>
                              <th className="text-left py-1.5 pr-2">Recommendation</th>
                              <th className="text-left py-1.5 pr-2">SKU</th>
                              <th className="text-center py-1.5 pr-2">Priority</th>
                              <th className="text-right py-1.5">Monthly Cost</th>
                            </tr>
                          </thead>
                          <tbody>
                            {paginatedResources.length === 0 && (
                              <tr>
                                <td colSpan={6} className="py-4 text-center text-gray-400">
                                  No resources match your search.
                                </td>
                              </tr>
                            )}
                            {paginatedResources.map((res, i) => (
                              <tr key={i} className="border-b border-att-50 hover:bg-att-50/60">
                                <td className="py-1.5 pr-2 text-gray-700 font-medium max-w-[180px] truncate" title={res.name || res.title}>
                                  {res.name || res.title}
                                </td>
                                <td className="py-1.5 pr-2 text-gray-500 max-w-[140px] truncate" title={res.resource_group || "—"}>
                                  {res.resource_group || "—"}
                                </td>
                                <td className="py-1.5 pr-2 text-gray-600 max-w-[250px]">
                                  <span className="block truncate" title={res.recommendation || "—"}>
                                    {res.recommendation || "—"}
                                  </span>
                                  {res.recommended_sku && (
                                    <span className="text-[10px] text-blue-600 block mt-0.5">
                                      Target: {res.recommended_sku}
                                    </span>
                                  )}
                                </td>
                                <td className="py-1.5 pr-2 text-gray-500 text-[11px]">
                                  {res.current_sku || "—"}
                                </td>
                                <td className="py-1.5 pr-2 text-center">
                                  {res.priority && (
                                    <span
                                      className={`inline-block text-[10px] px-1.5 py-0.5 rounded-full font-medium capitalize ${
                                        PRIORITY_COLORS[res.priority] || "bg-gray-100 text-gray-600"
                                      }`}
                                    >
                                      {res.priority}
                                    </span>
                                  )}
                                </td>
                                <td className="py-1.5 text-right text-orange-600 font-medium whitespace-nowrap">
                                  ${Number(res.monthly_cost).toLocaleString()}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>

                      {/* Pagination controls */}
                      {totalPages > 1 && (
                        <div className="mt-2 flex items-center justify-between border-t border-att-100 pt-2">
                          <span className="text-xs text-gray-500">
                            Page {page} of {totalPages}
                          </span>
                          <div className="flex items-center gap-1">
                            <button
                              onClick={() =>
                                setCurrentPage((prev) => ({
                                  ...prev,
                                  [detail.category]: 1,
                                }))
                              }
                              disabled={page <= 1}
                              className="rounded-lg border border-att-100 px-2 py-1 text-xs hover:bg-att-50 disabled:cursor-not-allowed disabled:opacity-40"
                              title="First page"
                            >
                              &laquo;
                            </button>
                            <button
                              onClick={() =>
                                setCurrentPage((prev) => ({
                                  ...prev,
                                  [detail.category]: Math.max(1, page - 1),
                                }))
                              }
                              disabled={page <= 1}
                              className="rounded-lg border border-att-100 px-2 py-1 text-xs hover:bg-att-50 disabled:cursor-not-allowed disabled:opacity-40"
                            >
                              &lsaquo; Prev
                            </button>
                            <button
                              onClick={() =>
                                setCurrentPage((prev) => ({
                                  ...prev,
                                  [detail.category]: Math.min(totalPages, page + 1),
                                }))
                              }
                              disabled={page >= totalPages}
                              className="rounded-lg border border-att-100 px-2 py-1 text-xs hover:bg-att-50 disabled:cursor-not-allowed disabled:opacity-40"
                            >
                              Next &rsaquo;
                            </button>
                            <button
                              onClick={() =>
                                setCurrentPage((prev) => ({
                                  ...prev,
                                  [detail.category]: totalPages,
                                }))
                              }
                              disabled={page >= totalPages}
                              className="rounded-lg border border-att-100 px-2 py-1 text-xs hover:bg-att-50 disabled:cursor-not-allowed disabled:opacity-40"
                              title="Last page"
                            >
                              &raquo;
                            </button>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};

// ── Executive Forecast + AI Advisory ─────────────────────────────────

interface ForecastPoint {
  month: string;
  totalActual: number | null;
  totalForecast: number | null;
  prodActual: number | null;
  prodForecast: number | null;
  nonProdActual: number | null;
  nonProdForecast: number | null;
}

interface ForecastView {
  source: string;
  model: string;
  generatedAt: string;
  summary: string;
  year: number;
  series: ForecastPoint[];
  yearEndProd: number;
  yearEndNonProd: number;
  yearEndTotal: number;
  remainingMonths: number;
}

const CostForecastChart: React.FC<{
  forecast?: {
    source: string;
    model: string;
    generated_at: string;
    summary: string;
    forecast_year: number;
    forecast_months: number;
    points: Array<{
      month_label: string;
      total_actual: number | null;
      total_forecast: number | null;
      prod_actual: number | null;
      prod_forecast: number | null;
      non_prod_actual: number | null;
      non_prod_forecast: number | null;
    }>;
  };
  isLoading: boolean;
}> = ({ forecast, isLoading }) => {
  const forecastView = React.useMemo<ForecastView | null>(() => {
    if (!forecast?.points?.length) return null;

    const series = forecast.points.map((point) => ({
      month: point.month_label,
      totalActual: point.total_actual,
      totalForecast: point.total_forecast,
      prodActual: point.prod_actual,
      prodForecast: point.prod_forecast,
      nonProdActual: point.non_prod_actual,
      nonProdForecast: point.non_prod_forecast,
    }));
    const finalForecast = [...forecast.points].reverse().find((point) => point.total_forecast != null);

    return {
      source: forecast.source,
      model: forecast.model,
      generatedAt: forecast.generated_at,
      summary: forecast.summary,
      year: forecast.forecast_year,
      series,
      yearEndProd: Number(finalForecast?.prod_forecast || 0),
      yearEndNonProd: Number(finalForecast?.non_prod_forecast || 0),
      yearEndTotal: Number(finalForecast?.total_forecast || 0),
      remainingMonths: forecast.forecast_months,
    };
  }, [forecast]);

  if (isLoading && !forecastView) {
    return (
      <section className="relative overflow-hidden rounded-2xl border border-att-100 bg-gradient-to-br from-white via-white to-att-50/70 p-6 shadow-sm shadow-att-100/40">
        <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-att-300 via-att-500 to-emerald-300" />
        <div className="flex h-[420px] items-center justify-center">
          <div className="text-center">
            <div className="mx-auto h-10 w-10 animate-spin rounded-full border-b-2 border-att-500" />
            <p className="mt-4 text-sm text-slate-500">Generating six-month forecast…</p>
          </div>
        </div>
      </section>
    );
  }

  if (!forecastView) {
    return null;
  }

  const { series, year, yearEndProd, yearEndNonProd, yearEndTotal, remainingMonths } = forecastView;

  return (
    <section className="relative overflow-hidden rounded-2xl border border-att-100 bg-gradient-to-br from-white via-white to-att-50/70 p-6 shadow-sm shadow-att-100/40">
      <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-att-300 via-att-500 to-emerald-300" />
      <div className="mb-5">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-att-600">Executive Forecast</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-900">Prod &amp; Non-Prod Through {year}</h3>
          </div>
          <div className="rounded-xl bg-att-50 px-4 py-3 text-right">
            <p className="text-xs font-semibold uppercase tracking-[0.12em] text-att-700">Year-End Combined</p>
            <p className="mt-1 text-2xl font-bold text-slate-900">{fmtCompact(yearEndTotal)}</p>
            <p className="text-xs text-slate-500">{remainingMonths} forecast month{remainingMonths === 1 ? "" : "s"} remaining</p>
          </div>
        </div>
        <div className="mt-5 grid grid-cols-1 gap-3 md:grid-cols-3">
          <MetricCard
            title="Projected Prod"
            value={fmtCompact(yearEndProd)}
            subtitle={`Prod run-rate by Dec ${year}`}
            icon={MetricCardIcons.shield()}
            tone="blue"
            valueClassName="text-xl"
          />
          <MetricCard
            title="Projected Non-Prod"
            value={fmtCompact(yearEndNonProd)}
            subtitle={`Non-prod run-rate by Dec ${year}`}
            icon={MetricCardIcons.activity()}
            tone="orange"
            valueClassName="text-xl"
          />
          <MetricCard
            title="Forecast Balance"
            value={yearEndTotal ? fmtPercent((yearEndProd / yearEndTotal) * 100) : "0.0%"}
            subtitle={`${forecastView.source === "ollama" ? forecastView.model : "Local"} forecast`}
            icon={MetricCardIcons.chart()}
            tone="att"
            valueClassName="text-xl"
          />
        </div>
      </div>
      <div className="rounded-2xl border border-att-100 bg-white/90 p-4 shadow-sm">
        <ResponsiveContainer width="100%" height={320}>
        <AreaChart data={series}>
          <CartesianGrid strokeDasharray="3 3" stroke="#d5ecf7" />
          <XAxis dataKey="month" tick={{ fontSize: 12 }} />
          <YAxis tickFormatter={(value) => fmtCompact(Number(value))} tick={{ fontSize: 12 }} />
          <Tooltip
            formatter={(value: number | null, name: string) => {
              const labels: Record<string, string> = {
                prodActual: "Prod actual",
                prodForecast: "Prod forecast",
                nonProdActual: "Non-prod actual",
                nonProdForecast: "Non-prod forecast",
                totalActual: "Total actual",
                totalForecast: "Total forecast",
              };
              return [value == null ? "—" : fmtUSD(Number(value)), labels[name] || name];
            }}
          />
          <Legend />
          <Area type="monotone" dataKey="prodActual" name="Prod actual" stroke="#3f9bca" fill="#d5ecf7" strokeWidth={3} connectNulls={false} />
          <Area type="monotone" dataKey="prodForecast" name="Prod forecast" stroke="#3f9bca" fill="#d5ecf7" strokeDasharray="8 4" strokeWidth={3} connectNulls={false} fillOpacity={0.16} />
          <Area type="monotone" dataKey="nonProdActual" name="Non-prod actual" stroke="#f97316" fill="#fed7aa" strokeWidth={3} connectNulls={false} />
          <Area type="monotone" dataKey="nonProdForecast" name="Non-prod forecast" stroke="#f97316" fill="#fed7aa" strokeDasharray="8 4" strokeWidth={3} connectNulls={false} fillOpacity={0.16} />
        </AreaChart>
        </ResponsiveContainer>
      </div>
    </section>
  );
};

interface AICostAdvisorProps {
  summary: string;
  source: string;
  model: string;
  generatedAt: string;
  focusAreas: string[];
  risks: string[];
  opportunities: Array<{ title: string; detail: string; estimated_savings?: string }>;
  isRunning: boolean;
  onRefresh: () => void;
  syncStatus: string | null | undefined;
  syncTimestamp: string | null | undefined;
  azurePricingStatus: string | null | undefined;
  azurePricingDetails: string | null | undefined;
  azurePricingResources: number | null | undefined;
}

const AICostAdvisor: React.FC<AICostAdvisorProps> = ({
  summary,
  source,
  model,
  generatedAt,
  focusAreas,
  risks,
  opportunities,
  isRunning,
  onRefresh,
  syncStatus,
  syncTimestamp,
  azurePricingStatus,
  azurePricingDetails,
  azurePricingResources,
}) => {
  const { formatDate } = usePortalTimezone();
  const pricingLabel =
    azurePricingStatus === "connected"
      ? "Ollama + Azure Pricing API"
      : "Ollama-only mode";

  const detailCardShell =
    "relative overflow-hidden rounded-2xl border border-att-100 bg-gradient-to-br from-white via-white to-att-50/70 p-5 shadow-sm shadow-att-100/30";

  return (
    <section className="relative overflow-hidden rounded-2xl border border-att-100 bg-gradient-to-br from-white via-white to-att-50/70 p-6 shadow-sm shadow-att-100/40">
      <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-att-300 via-att-500 to-emerald-300" />
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div className="max-w-3xl">
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-att-100 px-3 py-1 text-xs font-semibold uppercase tracking-[0.14em] text-att-700">AI Cost Advisor</span>
            <span className="rounded-full bg-white/90 px-3 py-1 text-xs font-medium text-slate-600 ring-1 ring-att-100">Model: {model}</span>
            <span className="rounded-full bg-white/90 px-3 py-1 text-xs font-medium text-slate-600 ring-1 ring-att-100">AI mode: {pricingLabel}</span>
            <span className={`rounded-full px-3 py-1 text-xs font-medium ring-1 ${syncStatus === "running" ? "bg-amber-50 text-amber-700 ring-amber-200" : "bg-emerald-50 text-emerald-700 ring-emerald-200"}`}>
              {syncStatus === "running" ? "Snapshot Refresh Running" : "Snapshot Ready"}
            </span>
          </div>
          <h2 className="mt-4 text-xl font-semibold text-slate-900">AI Cost Advisor</h2>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">{summary}</p>
          <div className="mt-3 flex flex-wrap gap-3 text-xs text-slate-500">
            <span>Source: {source === "ollama" ? `Ollama (${model})` : "Local fallback"}</span>
            <span>Generated: {formatDate(generatedAt)}</span>
            {syncTimestamp && <span>Snapshot: {formatDate(syncTimestamp)}</span>}
          </div>
        </div>
        <button
          onClick={onRefresh}
          disabled={isRunning}
          className="inline-flex items-center justify-center gap-2 rounded-xl bg-att-500 px-4 py-3 text-sm font-semibold text-white shadow-sm transition hover:bg-att-600 disabled:opacity-60"
        >
          <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={`h-4 w-4 ${isRunning ? "animate-spin" : ""}`}>
            <path d="M21 12a9 9 0 1 1-2.64-6.36" />
            <path d="M21 3v6h-6" />
          </svg>
          {isRunning ? "Generating Guidance…" : "Refresh AI Guidance"}
        </button>
      </div>

      <div className="mt-6 grid grid-cols-1 gap-4 xl:grid-cols-[1.2fr_0.9fr_1.1fr]">
        <div className={detailCardShell}>
          <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-att-300 via-att-500 to-att-300" />
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-att-100 text-att-700">
              {MetricCardIcons.chart()}
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Focus Areas</p>
              <p className="text-sm text-slate-600">Where leadership attention should go first</p>
            </div>
          </div>
          <div className="mt-4 space-y-3">
            {focusAreas.map((item, index) => (
              <div key={index} className="rounded-xl bg-att-50/70 p-3 text-sm text-slate-700 ring-1 ring-att-100">
                {item}
              </div>
            ))}
          </div>
        </div>

        <div className={detailCardShell}>
          <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-amber-200 via-amber-500 to-amber-200" />
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-amber-100 text-amber-700">
              {MetricCardIcons.alert()}
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Risks</p>
              <p className="text-sm text-slate-600">Signals that may increase spend pressure</p>
            </div>
          </div>
          <div className="mt-4 space-y-3">
            {risks.map((item, index) => (
              <div key={index} className="rounded-xl bg-amber-50 p-3 text-sm text-slate-700 ring-1 ring-amber-100">
                {item}
              </div>
            ))}
          </div>
        </div>

        <div className={detailCardShell}>
          <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-emerald-200 via-emerald-500 to-emerald-200" />
          <div className="flex items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-xl bg-emerald-100 text-emerald-700">
              {MetricCardIcons.activity()}
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-500">Savings Plays</p>
              <p className="text-sm text-slate-600">Actions suitable for LLM-led investigation</p>
            </div>
          </div>
          <div className="mt-4 space-y-3">
            {opportunities.map((item, index) => (
              <div key={index} className="rounded-xl bg-emerald-50/80 p-3 ring-1 ring-emerald-100">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <p className="text-sm font-semibold text-slate-800">{item.title}</p>
                    <p className="mt-1 text-sm text-slate-600">{item.detail}</p>
                  </div>
                  {item.estimated_savings ? (
                    <span className="whitespace-nowrap rounded-full bg-white px-2.5 py-1 text-xs font-semibold text-emerald-700 ring-1 ring-emerald-200">
                      {item.estimated_savings}
                    </span>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
};

// ── Insight Metrics Row ───────────────────────────────────────────────

interface InsightMetricsProps {
  dashboard: LeadershipDashboardData;
  optimization: OptimizationSummary | undefined;
  trendData: NonProdVsProdTrend | undefined;
}

const InsightMetrics: React.FC<InsightMetricsProps> = ({ dashboard, optimization, trendData }) => {
  const cards = React.useMemo(() => {
    const result: { title: string; value: string; subtitle: string; icon: React.ReactNode; tone: "att" | "blue" | "green" | "amber" | "orange" | "red" | "purple" }[] = [];

    // Stable baseline for percentage tiles. KPI[0] is the current partial
    // month's spend — using it as a denominator early in a month inflated
    // waste/savings ratios above 200%. Prefer the last full month from
    // six_month_trend; fall back to KPI[0] if no history is available.
    const sortedTrend = [...dashboard.six_month_trend].sort((a, b) =>
      a.month.localeCompare(b.month)
    );
    const lastFullMonth = sortedTrend.length ? sortedTrend[sortedTrend.length - 1] : null;
    const lastFullMonthSpend = lastFullMonth ? Number(lastFullMonth.total_cost) : 0;
    const baselineSpend = lastFullMonthSpend > 0 ? lastFullMonthSpend : Number(dashboard.kpis[0]?.value || 0);

    // Prod vs Non-Prod split — prefer the last full month from the
    // amortized DB (carries env_label set from AdminSubscription); fall
    // back to /costs/nonprod-vs-prod if not yet loaded.
    if (lastFullMonth && Number(lastFullMonth.total_cost) > 0) {
      const prod = Number(lastFullMonth.prod_cost);
      const total = Number(lastFullMonth.total_cost);
      const prodPct = total > 0 ? (prod / total) * 100 : 0;
      result.push({
        title: "Prod Spend Share",
        value: fmtPercent(prodPct),
        subtitle: `${fmtCompact(prod)} of ${fmtCompact(total)} (${lastFullMonth.month_label})`,
        icon: MetricCardIcons.shield(),
        tone: "blue",
      });
    } else if (trendData?.data?.length) {
      const latest = trendData.data[trendData.data.length - 1];
      const prodPct = latest.total > 0 ? (latest.prod / latest.total) * 100 : 0;
      result.push({
        title: "Prod Spend Share",
        value: fmtPercent(prodPct),
        subtitle: `${fmtCompact(latest.prod)} of ${fmtCompact(latest.total)}`,
        icon: MetricCardIcons.shield(),
        tone: "blue",
      });
    }

    // Monthly waste rate vs last full month's spend (stable denominator).
    if (optimization && baselineSpend > 0) {
      const wastePct = (optimization.wastage.total_monthly_waste / baselineSpend) * 100;
      result.push({
        title: "Waste Rate",
        value: fmtPercent(wastePct),
        subtitle: `${fmtCompact(optimization.wastage.total_monthly_waste)}/mo waste`,
        icon: MetricCardIcons.alert(),
        tone: wastePct > 20 ? "red" : wastePct > 10 ? "amber" : "green",
      });
    }

    // 6-month trend direction — also based on six_month_trend (which now
    // excludes the partial current month, so no fake "-98%" drop).
    if (sortedTrend.length >= 2) {
      const first = sortedTrend[0];
      const last = sortedTrend[sortedTrend.length - 1];
      const firstCost = Number(first.total_cost);
      const lastCost = Number(last.total_cost);
      const delta = firstCost > 0 ? ((lastCost - firstCost) / firstCost) * 100 : 0;
      result.push({
        title: "6-Month Trend",
        value: `${delta >= 0 ? "+" : ""}${fmtPercent(delta)}`,
        subtitle: `${fmtCompact(firstCost)} → ${fmtCompact(lastCost)}`,
        icon: MetricCardIcons.activity(),
        tone: delta > 5 ? "red" : delta < -5 ? "green" : "att",
      });
    }

    return result;
  }, [dashboard, optimization, trendData]);

  if (!cards.length) return null;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {cards.map((card) => (
        <MetricCard
          key={card.title}
          title={card.title}
          value={card.value}
          subtitle={card.subtitle}
          icon={card.icon}
          tone={card.tone}
          valueClassName="text-xl"
        />
      ))}
    </div>
  );
};

// ── Main Dashboard Component ──────────────────────────────────────────

const LeadershipDashboard: React.FC = () => {
  const { formatDate } = usePortalTimezone();
  const { data: dashboard, isLoading: dashLoading, error: dashError, refetch: refetchDashboard } = useLeadershipDashboard();
  const { data: optimization, isLoading: optLoading } = useOptimizationSummary();
  const { data: syncStatus } = useLeadershipSyncStatus();
  const { data: ollamaStatus } = useOllamaStatus();
  const ollamaEnabled = ollamaStatus?.enabled ?? false;
  const advisor = useLeadershipCostAdvisor();
  const { data: trendData } = useNonProdVsProdTrend(6);

  // Auto-refresh dashboard data when a background sync completes
  const prevSyncStatusRef = React.useRef<string | null>(null);
  React.useEffect(() => {
    const prev = prevSyncStatusRef.current;
    const curr = syncStatus?.status ?? null;
    prevSyncStatusRef.current = curr;
    if (prev === "running" && curr === "completed") {
      refetchDashboard();
    }
  }, [syncStatus?.status, refetchDashboard]);
  const forecastInput = React.useMemo(
    () =>
      dashboard
        ? {
            dashboard,
            optimization: optimization ?? null,
            trend: trendData ?? null,
            syncStatus: syncStatus ?? null,
          }
        : undefined,
    [dashboard, optimization, trendData, syncStatus]
  );
  const forecast = useLeadershipCostForecast(forecastInput, ollamaEnabled && Boolean(dashboard));
  const autoAdvisorReportRef = React.useRef<string | null>(null);
  const [dashRefreshing, setDashRefreshing] = React.useState(false);
  const [refreshError, setRefreshError] = React.useState<string | null>(null);
  const queryClient = useQueryClient();

  const handleDashRefresh = async () => {
    setDashRefreshing(true);
    setRefreshError(null);
    try {
      await Promise.all([
        refreshLeadershipDashboard(queryClient),
        refreshOptimizationSummary(queryClient),
      ]);
      queryClient.invalidateQueries({ queryKey: ["dashboard", "leadership-sync-status"] });
      queryClient.invalidateQueries({ queryKey: ["dashboard", "leadership", "forecast"] });
      autoAdvisorReportRef.current = null;
    } catch (err) {
      const detail =
        (err as { response?: { data?: { detail?: string; error?: string } } })?.response?.data?.detail ??
        (err as { response?: { data?: { detail?: string; error?: string } } })?.response?.data?.error ??
        (err as Error)?.message ??
        "Unknown error";
      setRefreshError(`Refresh failed — ${detail}`);
    }
    setDashRefreshing(false);
  };

  const handleAdvisorRefresh = React.useCallback(() => {
    if (!ollamaEnabled || !dashboard) return;
    autoAdvisorReportRef.current = dashboard.report_date;
    advisor.mutate({
      dashboard,
      optimization: optimization ?? null,
      trend: trendData ?? null,
      syncStatus: syncStatus ?? null,
    });
  }, [ollamaEnabled, advisor, dashboard, optimization, trendData, syncStatus]);

  React.useEffect(() => {
    if (!ollamaEnabled || !dashboard || advisor.data || advisor.isPending) return;
    if (autoAdvisorReportRef.current === dashboard.report_date) return;
    autoAdvisorReportRef.current = dashboard.report_date;
    handleAdvisorRefresh();
  }, [ollamaEnabled, advisor.data, advisor.isPending, dashboard, handleAdvisorRefresh]);

  if (dashLoading) {
    return (
      <div className="flex items-center justify-center h-96">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto" />
          <p className="mt-4 text-sm text-gray-500">Loading Azure cost data…</p>
        </div>
      </div>
    );
  }

  if (dashError || !dashboard) {
    return (
      <div className="bg-red-50 border border-red-200 rounded-lg p-6 m-6">
        <p className="text-red-800">Failed to load dashboard data. Please retry.</p>
      </div>
    );
  }

  // Merge the single optimization-driven KPI that earns its place on the
  // forecast view — the dollar opportunity, not the count of items.
  const allKpis = [...dashboard.kpis];
  if (optimization) {
    allKpis.push({
      name: "Total Savings Opportunities",
      value: optimization.total_estimated_annual_savings,
      unit: "USD/year",
      trend: "down" as const,
      change_pct: 0,
      description: "Estimated annual savings from all recommendations",
    });
  }

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            Cost Forecast
          </h1>
          <p className="text-sm text-gray-500">
            Cost Forecast — Updated{" "}
            {formatDate(dashboard.report_date)}
          </p>
          <div className="mt-1 flex flex-wrap items-center gap-3 text-xs text-gray-400">
            {dashboard.cost_trend.length > 0 && (
              <span>
                Data through{" "}
                {new Date(
                  [...dashboard.cost_trend].sort((a, b) => b.date.localeCompare(a.date))[0].date
                ).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}
              </span>
            )}
            {syncStatus?.last_sync && (
              <span>Last sync: {formatDate(syncStatus.last_sync)}</span>
            )}
            {syncStatus?.duration_seconds != null && (
              <span>({syncStatus.duration_seconds.toFixed(1)}s)</span>
            )}
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium ${
                syncStatus?.status === "running"
                  ? "bg-amber-50 text-amber-600 ring-1 ring-amber-200"
                  : syncStatus?.status === "failed"
                    ? "bg-red-50 text-red-600 ring-1 ring-red-200"
                    : "bg-emerald-50 text-emerald-600 ring-1 ring-emerald-200"
              }`}
            >
              <span className={`h-1.5 w-1.5 rounded-full ${
                syncStatus?.status === "running"
                  ? "bg-amber-500 animate-pulse"
                  : syncStatus?.status === "failed"
                    ? "bg-red-500"
                    : "bg-emerald-500"
              }`} />
              {syncStatus?.status === "running" ? "Syncing" : syncStatus?.status === "failed" ? "Sync Failed" : "Live"}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleDashRefresh}
            disabled={dashRefreshing}
            className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50 transition flex items-center gap-2"
            title="Refresh the leadership snapshot from Azure-backed source data"
          >
          {dashRefreshing ? (
            <>
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}><circle cx="12" cy="12" r="10" strokeOpacity="0.25" /><path d="M4 12a8 8 0 018-8" /></svg>
              Refreshing…
            </>
          ) : (
            <>
              <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" /></svg>
              Refresh Data
            </>
          )}
          </button>
        </div>
      </div>

      {/* Refresh error banner — surfaces the real backend error so the user
          knows why the dashboard didn't update (was previously swallowed). */}
      {refreshError && (
        <div className="flex items-start justify-between rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          <div className="flex items-start gap-2">
            <svg className="mt-0.5 h-4 w-4 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
            </svg>
            <span>{refreshError}</span>
          </div>
          <button
            onClick={() => setRefreshError(null)}
            className="ml-4 text-red-500 hover:text-red-700"
            aria-label="Dismiss"
          >
            ×
          </button>
        </div>
      )}

      {/* KPI Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {allKpis.map((kpi, i) => (
          <KPICard key={i} metric={kpi} />
        ))}
        {optLoading && !optimization && (
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6 flex items-center justify-center col-span-2">
            <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-400 mr-3" />
            <span className="text-sm text-gray-400">Loading optimization data…</span>
          </div>
        )}
      </div>

      {/* Derived Insight Metrics */}
      <InsightMetrics dashboard={dashboard} optimization={optimization} trendData={trendData} />

      {ollamaEnabled && (
        <AICostAdvisor
          summary={advisor.data?.summary || "Generating executive guidance from the current cost dashboard, optimization recommendations, and snapshot status."}
          source={advisor.data?.source || "fallback"}
          model={advisor.data?.model || "pending"}
          generatedAt={advisor.data?.generated_at || dashboard.report_date}
          focusAreas={advisor.data?.focus_areas || []}
          risks={advisor.data?.risks || []}
          opportunities={advisor.data?.opportunities || []}
          isRunning={advisor.isPending}
          onRefresh={handleAdvisorRefresh}
          syncStatus={syncStatus?.status}
          syncTimestamp={syncStatus?.last_sync}
          azurePricingStatus={advisor.data?.azure_pricing?.status}
          azurePricingDetails={advisor.data?.azure_pricing?.details}
          azurePricingResources={advisor.data?.azure_pricing?.resources_considered}
        />
      )}

      {ollamaEnabled && (
        <div className="grid grid-cols-1 gap-6">
          <CostForecastChart forecast={forecast.data} isLoading={forecast.isLoading} />
        </div>
      )}

      {/* Charts Grid */}
      <div className="grid grid-cols-1 gap-6">
        <CostTrendChart data={dashboard.cost_trend} />
      </div>

      {/* Enhanced Wastage Summary */}
      {optimization && (
        <WastageDetailTile
          wastage={optimization.wastage}
          totalAnnualSavings={optimization.total_estimated_annual_savings}
        />
      )}
    </div>
  );
};

export default LeadershipDashboard;
