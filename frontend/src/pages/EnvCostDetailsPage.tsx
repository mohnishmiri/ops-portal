/**
 * Environment-wise Cost Details — pivot-table view.
 *
 * Shows Azure costs broken down by MeterCategory (service type)
 * across monthly columns for a selected environment (PROD, DEV, PERF, DR, ALL).
 * Matches the user's spreadsheet format with Grand Total row.
 */

import React, { useState } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import {
  useEnvCostDetails,
  useNonProdVsProdTrend,
  EnvCostService,
  NonProdVsProdPoint,
} from "../services/costApi";
import { usePortalTimezone } from "../contexts/TimezoneContext";
import { MetricCard, MetricCardIcons } from "../components/MetricCard";

// ── Helpers ───────────────────────────────────────────────────────────

const fmtUSD = (n: number) =>
  `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const fmtCompact = (n: number) =>
  n >= 1_000_000
    ? `$${(n / 1_000_000).toFixed(2)}M`
    : n >= 1_000
    ? `$${(n / 1_000).toFixed(1)}k`
    : `$${n.toFixed(2)}`;

// ── Main Component ────────────────────────────────────────────────────

const EnvCostDetailsPage: React.FC = () => {
  const { formatDate } = usePortalTimezone();
  const [environment, setEnvironment] = useState("PROD");
  const [months, setMonths] = useState(3);
  const [search, setSearch] = useState("");
  const [trendMonths, setTrendMonths] = useState(6);

  const { data, isLoading, error, refetch } = useEnvCostDetails(environment, months);
  const {
    data: trendData,
    isLoading: trendLoading,
  } = useNonProdVsProdTrend(trendMonths);

  // Filtered services
  const filteredServices: EnvCostService[] = (data?.services ?? []).filter((s) =>
    s.service_name.toLowerCase().includes(search.toLowerCase())
  );

  // Top 3 spenders for highlighting
  const top3 = new Set(
    (data?.services ?? []).slice(0, 3).map((s) => s.service_name)
  );

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            Environment Cost Details
          </h1>
          <p className="text-sm text-gray-500">
            Monthly cost breakdown by Azure service type per environment
          </p>
        </div>

        <div className="flex items-center gap-3 flex-wrap">
          {/* Environment selector */}
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-gray-700">Environment</label>
            <select
              value={environment}
              onChange={(e) => setEnvironment(e.target.value)}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white shadow-sm
                         focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            >
              {(data?.available_environments ?? ["PROD", "DEV", "PERF", "DR", "ALL"]).map(
                (env) => (
                  <option key={env} value={env}>
                    {env}
                  </option>
                )
              )}
            </select>
          </div>

          {/* Months selector */}
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-gray-700">Months</label>
            <select
              value={months}
              onChange={(e) => setMonths(Number(e.target.value))}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white shadow-sm
                         focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            >
              {[1, 2, 3, 4, 6, 9, 12].map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>

          {/* Search */}
          <input
            type="text"
            placeholder="Search service…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white shadow-sm w-48
                       focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
          />

          {/* Refresh */}
          <button
            onClick={() => refetch()}
            disabled={isLoading}
            className="px-4 py-2 text-sm font-medium bg-blue-600 text-white rounded-lg
                       hover:bg-blue-700 disabled:opacity-50 transition shadow-sm"
          >
            {isLoading ? "Loading…" : "Refresh"}
          </button>
        </div>
      </div>

      {/* ── Non-Prod vs Prod Stacked Bar Chart ─────────────────────── */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <div className="flex items-center justify-between mb-4 flex-wrap gap-3">
          <div className="flex items-center gap-2">
            <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5 text-green-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
            </svg>
            <h3 className="text-lg font-semibold text-gray-800">
              {trendMonths}-Month Cost Trend (Non-Prod vs Prod)
            </h3>
          </div>
          <div className="flex items-center gap-2">
            <label className="text-sm font-medium text-gray-700">Months</label>
            <select
              value={trendMonths}
              onChange={(e) => setTrendMonths(Number(e.target.value))}
              className="rounded-lg border border-gray-300 px-3 py-2 text-sm bg-white shadow-sm
                         focus:border-blue-500 focus:ring-1 focus:ring-blue-500"
            >
              {[3, 6, 9, 12].map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
          </div>
        </div>

        {trendLoading && (
          <div className="flex items-center justify-center h-[280px]">
            <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600" />
          </div>
        )}

        {trendData && !trendLoading && (
          <>
            <ResponsiveContainer width="100%" height={320}>
              <BarChart data={trendData.data} barGap={0} barCategoryGap="20%">
                <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                <XAxis dataKey="month" tick={{ fontSize: 12 }} />
                <YAxis
                  tickFormatter={(v: number) =>
                    v >= 1000 ? `$${(v / 1000).toFixed(0)}k` : `$${v}`
                  }
                  tick={{ fontSize: 11 }}
                />
                <Tooltip
                  formatter={(v: number, name: string) => [
                    fmtUSD(v),
                    name === "non_prod" ? "Non-Prod" : "Prod",
                  ]}
                  labelFormatter={(label: string) => label}
                  contentStyle={{ borderRadius: "8px", border: "1px solid #e5e7eb" }}
                />
                <Legend
                  formatter={(value: string) =>
                    value === "non_prod" ? "Non-Prod" : "Prod"
                  }
                />
                <Bar
                  dataKey="non_prod"
                  fill="#f97316"
                  radius={[4, 4, 0, 0]}
                  name="non_prod"
                />
                <Bar
                  dataKey="prod"
                  fill="#3b82f6"
                  radius={[4, 4, 0, 0]}
                  name="prod"
                />
              </BarChart>
            </ResponsiveContainer>

            {/* Monthly summary cards */}
            <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3 mt-5">
              {trendData.data.map((dp: NonProdVsProdPoint) => (
                <div
                  key={dp.month_key}
                  className="bg-gray-50 rounded-xl border border-gray-200 p-3 text-center"
                >
                  <p className="text-xs text-gray-500 font-medium">{dp.month}</p>
                  <p className="text-lg font-bold text-gray-900 mt-1">
                    {fmtCompact(dp.total)}
                  </p>
                  <div className="flex justify-center gap-2 mt-1 text-xs">
                    <span className="text-orange-600">
                      NP: {fmtCompact(dp.non_prod)}
                    </span>
                    <span className="text-blue-600">
                      P: {fmtCompact(dp.prod)}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center justify-center h-[40vh]">
          <div className="text-center">
            <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto" />
            <p className="mt-4 text-gray-500">Loading {environment} cost data…</p>
          </div>
        </div>
      )}

      {/* Error */}
      {error && !isLoading && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center">
          <p className="text-red-700 font-semibold">Failed to load cost data</p>
          <p className="text-red-600 text-sm mt-1">{String(error)}</p>
        </div>
      )}

      {/* Content */}
      {data && !isLoading && (
        <>
          {/* KPI Row */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
            <MetricCard
              title="Environment"
              value={data.environment}
              icon={MetricCardIcons.globe()}
              tone="blue"
            />
            <MetricCard
              title="Grand Total"
              value={fmtCompact(data.grand_total)}
              icon={MetricCardIcons.currency()}
              tone="green"
            />
            <MetricCard
              title="Service Types"
              value={data.services.length}
              icon={MetricCardIcons.layers()}
              tone="purple"
            />
            <MetricCard
              title="Months Covered"
              value={data.months.length}
              icon={MetricCardIcons.calendar()}
              tone="amber"
            />
          </div>

          {/* Pivot Table */}
          <div className="bg-white rounded-xl shadow-sm border border-gray-100 overflow-hidden">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-semibold text-gray-600 uppercase tracking-wider sticky left-0 bg-gray-50 z-10">
                      Service Type
                    </th>
                    {data.months.map((m) => (
                      <th
                        key={m}
                        className="px-4 py-3 text-right text-xs font-semibold text-gray-600 uppercase tracking-wider whitespace-nowrap"
                      >
                        {data.month_labels[m] || m}
                      </th>
                    ))}
                    <th className="px-4 py-3 text-right text-xs font-semibold text-gray-800 uppercase tracking-wider bg-gray-100">
                      Total
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {filteredServices.map((svc, idx) => {
                    const isTop = top3.has(svc.service_name);
                    return (
                      <tr
                        key={svc.service_name}
                        className={
                          isTop
                            ? "bg-yellow-50 hover:bg-yellow-100"
                            : idx % 2 === 0
                            ? "bg-white hover:bg-gray-50"
                            : "bg-gray-50/50 hover:bg-gray-100/50"
                        }
                      >
                        <td className="px-4 py-2.5 text-sm text-gray-900 font-medium sticky left-0 bg-inherit whitespace-nowrap">
                          {isTop && (
                            <span className="inline-block w-2 h-2 bg-yellow-400 rounded-full mr-2" />
                          )}
                          {svc.service_name}
                        </td>
                        {data.months.map((m) => (
                          <td
                            key={m}
                            className="px-4 py-2.5 text-sm text-gray-700 text-right font-mono whitespace-nowrap"
                          >
                            {svc.monthly_costs[m]
                              ? fmtUSD(svc.monthly_costs[m])
                              : "—"}
                          </td>
                        ))}
                        <td className="px-4 py-2.5 text-sm text-gray-900 text-right font-mono font-semibold bg-gray-50/80 whitespace-nowrap">
                          {fmtUSD(svc.total)}
                        </td>
                      </tr>
                    );
                  })}

                  {/* No results */}
                  {filteredServices.length === 0 && (
                    <tr>
                      <td
                        colSpan={data.months.length + 2}
                        className="px-4 py-8 text-center text-gray-500 text-sm"
                      >
                        {search
                          ? `No services matching "${search}"`
                          : "No cost data available for this environment"}
                      </td>
                    </tr>
                  )}
                </tbody>

                {/* Grand Total Footer */}
                {filteredServices.length > 0 && !search && (
                  <tfoot>
                    <tr className="bg-blue-50 border-t-2 border-blue-200 font-bold">
                      <td className="px-4 py-3 text-sm text-blue-900 sticky left-0 bg-blue-50">
                        Grand Total
                      </td>
                      {data.months.map((m) => (
                        <td
                          key={m}
                          className="px-4 py-3 text-sm text-blue-900 text-right font-mono"
                        >
                          {fmtUSD(data.monthly_totals[m] ?? 0)}
                        </td>
                      ))}
                      <td className="px-4 py-3 text-sm text-blue-900 text-right font-mono bg-blue-100/50">
                        {fmtUSD(data.grand_total)}
                      </td>
                    </tr>
                  </tfoot>
                )}
              </table>
            </div>

            {/* Footer info */}
            <div className="border-t border-gray-100 px-4 py-2 flex items-center justify-between text-xs text-gray-400">
              <span>
                {filteredServices.length} of {data.services.length} services
                {search ? ` matching "${search}"` : ""}
              </span>
              <span>
                Generated {formatDate(data.generated_at)}
              </span>
            </div>
          </div>

          {/* Top spenders legend */}
          <div className="flex items-center gap-2 text-xs text-gray-500">
            <span className="inline-block w-2 h-2 bg-yellow-400 rounded-full" />
            <span>Highlighted rows indicate top 3 cost-contributing services</span>
          </div>
        </>
      )}
    </div>
  );
};

export default EnvCostDetailsPage;
