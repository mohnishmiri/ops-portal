/**
 * Operations Dashboard — infrastructure cost insights.
 *
 * Shows daily spend trend, cost by resource type & resource group,
 * cost by region, anomaly detection, and per-subscription breakdown.
 */

import React from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  LineChart,
  Line,
  ReferenceLine,
  PieChart,
  Pie,
  Cell,
  Legend,
} from "recharts";
import {
  useOpsDashboard,
  CostByGroup,
  DailySpendPoint,
  Anomaly,
} from "../services/costApi";
import { usePortalTimezone } from "../contexts/TimezoneContext";
import { MetricCard, MetricCardIcons } from "../components/MetricCard";

// ── Helpers ───────────────────────────────────────────────────────────

const fmt = (n: number) =>
  n >= 1000
    ? `$${(n / 1000).toFixed(1)}k`
    : `$${n.toFixed(2)}`;

const fmtFull = (n: number) =>
  `$${n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const COLORS = [
  "#3b82f6", "#10b981", "#f59e0b", "#ef4444", "#8b5cf6",
  "#ec4899", "#14b8a6", "#f97316", "#6366f1", "#84cc16",
];

// ── Daily Spend Chart ─────────────────────────────────────────────────

const DailySpendChart: React.FC<{
  data: DailySpendPoint[];
  avg: number;
  prevAvg: number;
  anomalies: Anomaly[];
}> = ({ data, avg, prevAvg, anomalies }) => {
  const { timezone } = usePortalTimezone();
  const anomalyDates = new Set(anomalies.map((a) => a.date));

  const enriched = data.map((d) => ({
    ...d,
    fill: anomalyDates.has(d.date) ? "#ef4444" : "#3b82f6",
  }));

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-800">Daily Spend — Current Month</h3>
        <div className="flex gap-4 text-sm text-gray-500">
          <span>Avg: <strong className="text-gray-900">{fmtFull(avg)}</strong>/day</span>
          <span>Prev Month Avg: <strong className="text-gray-900">{fmtFull(prevAvg)}</strong>/day</span>
        </div>
      </div>
      <ResponsiveContainer width="100%" height={280}>
        <BarChart data={enriched}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis
            dataKey="date"
            tick={{ fontSize: 11 }}
            tickFormatter={(v: string) =>
              new Date(v).toLocaleDateString("en-US", { day: "numeric", month: "short", timeZone: timezone })
            }
          />
          <YAxis tickFormatter={(v: number) => fmt(v)} tick={{ fontSize: 11 }} />
          <Tooltip
            formatter={(v: number) => [fmtFull(v), "Cost"]}
            labelFormatter={(l: string) =>
              new Date(l).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", timeZone: timezone })
            }
          />
          <ReferenceLine y={avg} stroke="#f59e0b" strokeDasharray="6 4" label={{ value: "Avg", fontSize: 11, fill: "#f59e0b" }} />
          <Bar dataKey="cost" radius={[4, 4, 0, 0]}>
            {enriched.map((entry, idx) => (
              <Cell key={idx} fill={entry.fill} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
      {anomalies.length > 0 && (
        <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg">
          <p className="text-sm font-semibold text-red-700 mb-1">
            <svg xmlns="http://www.w3.org/2000/svg" className="inline-block w-4 h-4 mr-1 text-red-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}><path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4.5c-.77-.833-2.694-.833-3.464 0L3.34 16.5c-.77.833.192 2.5 1.732 2.5z" /></svg>
            {anomalies.length} anomaly day(s) detected (cost &gt; 1.5× daily avg)
          </p>
          <div className="flex flex-wrap gap-2">
            {anomalies.map((a) => (
              <span key={a.date} className="text-xs bg-red-100 text-red-800 px-2 py-1 rounded">
                {new Date(a.date).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: timezone })}: {fmtFull(a.cost)}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
};

// ── Resource Type Breakdown ───────────────────────────────────────────

const ResourceTypeChart: React.FC<{ data: CostByGroup[] }> = ({ data }) => {
  const top = data.slice(0, 10);
  // Shorten type names for display
  const cleaned = top.map((d) => ({
    ...d,
    label: d.group_value.replace("microsoft.", "").replace("Microsoft.", "").split("/").pop() || d.group_value,
  }));

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-4">Cost by Resource Type</h3>
      <ResponsiveContainer width="100%" height={Math.max(250, cleaned.length * 32)}>
        <BarChart data={cleaned} layout="vertical" margin={{ left: 120 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
          <XAxis type="number" tickFormatter={(v: number) => fmt(v)} tick={{ fontSize: 11 }} />
          <YAxis dataKey="label" type="category" tick={{ fontSize: 11 }} width={110} />
          <Tooltip formatter={(v: number) => [fmtFull(v), "Cost"]} />
          <Bar dataKey="total_cost" fill="#3b82f6" radius={[0, 4, 4, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
};

// ── Resource Group Table ──────────────────────────────────────────────

const ResourceGroupTable: React.FC<{ data: CostByGroup[] }> = ({ data }) => {
  const top = data.slice(0, 15);

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-4">Top Resource Groups</h3>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200">
              <th className="text-left py-2 px-3 font-semibold text-gray-600">#</th>
              <th className="text-left py-2 px-3 font-semibold text-gray-600">Resource Group</th>
              <th className="text-right py-2 px-3 font-semibold text-gray-600">Cost</th>
              <th className="text-right py-2 px-3 font-semibold text-gray-600">% of Total</th>
              <th className="text-left py-2 px-3 font-semibold text-gray-600">Share</th>
            </tr>
          </thead>
          <tbody>
            {top.map((rg, idx) => (
              <tr key={rg.group_value} className="border-b border-gray-50 hover:bg-gray-50">
                <td className="py-2 px-3 text-gray-400">{idx + 1}</td>
                <td className="py-2 px-3 font-medium text-gray-900">{rg.group_value || "(empty)"}</td>
                <td className="py-2 px-3 text-right font-mono text-gray-900">{fmtFull(rg.total_cost)}</td>
                <td className="py-2 px-3 text-right text-gray-600">{rg.percentage_of_total.toFixed(1)}%</td>
                <td className="py-2 px-3">
                  <div className="w-full bg-gray-100 rounded-full h-2">
                    <div
                      className="bg-blue-500 rounded-full h-2"
                      style={{ width: `${Math.min(rg.percentage_of_total, 100)}%` }}
                    />
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// ── Location Pie ──────────────────────────────────────────────────────

const LocationPie: React.FC<{ data: CostByGroup[] }> = ({ data }) => {
  const top = data.slice(0, 8);

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-4">Cost by Region</h3>
      <ResponsiveContainer width="100%" height={280}>
        <PieChart>
          <Pie
            data={top}
            dataKey="total_cost"
            nameKey="group_value"
            cx="50%"
            cy="50%"
            outerRadius={100}
            label={({ group_value, percentage_of_total }: { group_value: string; percentage_of_total: number }) =>
              `${group_value} (${percentage_of_total.toFixed(0)}%)`
            }
            labelLine={{ stroke: "#999", strokeWidth: 1 }}
          >
            {top.map((_, index) => (
              <Cell key={index} fill={COLORS[index % COLORS.length]} />
            ))}
          </Pie>
          <Tooltip formatter={(v: number) => fmtFull(v)} />
        </PieChart>
      </ResponsiveContainer>
    </div>
  );
};

// ── Subscription Cost Cards ───────────────────────────────────────────

const SubscriptionCards: React.FC<{
  subs: { subscription_id: string; cost: number }[];
}> = ({ subs }) => {
  const total = subs.reduce((s, x) => s + x.cost, 0);

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-4">
        Subscription Cost Breakdown
      </h3>
      <div className="space-y-3">
        {subs.map((sub) => {
          const pct = total > 0 ? (sub.cost / total) * 100 : 0;
          return (
            <div key={sub.subscription_id}>
              <div className="flex justify-between text-sm mb-1">
                <span className="font-medium text-gray-700 truncate max-w-xs" title={sub.subscription_id}>
                  {sub.subscription_id.slice(0, 8)}…
                </span>
                <span className="font-mono text-gray-900">{fmtFull(sub.cost)} ({pct.toFixed(1)}%)</span>
              </div>
              <div className="w-full bg-gray-100 rounded-full h-2.5">
                <div
                  className="bg-blue-500 rounded-full h-2.5 transition-all"
                  style={{ width: `${Math.min(pct, 100)}%` }}
                />
              </div>
            </div>
          );
        })}
        <div className="pt-3 border-t border-gray-200 flex justify-between font-semibold text-sm">
          <span>Total</span>
          <span className="font-mono">{fmtFull(total)}</span>
        </div>
      </div>
    </div>
  );
};

// ── Main Component ────────────────────────────────────────────────────

const OperationsDashboard: React.FC = () => {
  const { data, isLoading, error } = useOpsDashboard();

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto" />
          <p className="mt-4 text-gray-500">Loading operations data…</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="py-6">
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center">
          <p className="text-red-700 font-semibold">Failed to load operations dashboard</p>
          <p className="text-red-600 text-sm mt-1">{String(error)}</p>
        </div>
      </div>
    );
  }

  const resourceTypes = data.cost_by_resource_type?.breakdown ?? [];
  const resourceGroups = data.cost_by_resource_group?.breakdown ?? [];
  const locations = data.cost_by_location?.breakdown ?? [];

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Operations Dashboard</h1>
          <p className="text-sm text-gray-500">
            {data.subscriptions_monitored} subscription(s) monitored •
            generated {new Date(data.generated_at).toLocaleTimeString()}
          </p>
        </div>
      </div>

      {/* KPI Row */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          title="Current Month Total"
          value={fmtFull(data.cost_by_resource_type?.summary?.total_cost ?? 0)}
          icon={MetricCardIcons.currency()}
          tone="blue"
        />
        <MetricCard
          title="Daily Average"
          value={fmtFull(data.daily_avg)}
          icon={MetricCardIcons.activity()}
          tone="green"
        />
        <MetricCard
          title="Prev Month Daily Avg"
          value={fmtFull(data.prev_month_daily_avg)}
          icon={MetricCardIcons.chart()}
          tone="amber"
        />
        <MetricCard
          title="Anomaly Days"
          value={data.anomalies.length}
          icon={MetricCardIcons.alert()}
          tone={data.anomalies.length > 0 ? "red" : "slate"}
        />
      </div>

      {/* Daily Spend */}
      <DailySpendChart
        data={data.daily_spend}
        avg={data.daily_avg}
        prevAvg={data.prev_month_daily_avg}
        anomalies={data.anomalies}
      />

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <ResourceTypeChart data={resourceTypes} />
        <LocationPie data={locations} />
      </div>

      {/* Subscription breakdown */}
      {data.subscription_costs.length > 1 && (
        <SubscriptionCards subs={data.subscription_costs} />
      )}

      {/* Resource Group Table */}
      <ResourceGroupTable data={resourceGroups} />
    </div>
  );
};

export default OperationsDashboard;
