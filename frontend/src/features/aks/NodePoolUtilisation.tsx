/**
 * CPU and memory utilisation history of a node pool's scale set, from Azure
 * Monitor ("Percentage CPU" and 100 - "Available Memory Percentage", averaged
 * across the pool's VMs). Azure Monitor is read through Azure, so this works
 * even when the cluster's Kubernetes API can't be reached.
 *
 * One small chart per metric, like the VM utilisation panel in Infra Alerts:
 * one percentage axis each, average line, peak in the tooltip and summary.
 */

import React, { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { NodePoolMetricPoint, NodePoolMetricSummary, NodePoolMetricsRange, useNodePoolMetrics } from "../../services/aksApi";
import { DetailGrid } from "./DetailGrid";
import { apiErrorDetail } from "./detailShared";
import { DetailCard } from "./ResourceDetailShell";

// Same metric colours as the VM utilisation charts (validated pair: CVD ΔE 12.9, normal 22.3).
const METRIC_COLORS = { cpu: "#2e80ac", memory: "#7a2e75" } as const;
const RANGES: { value: NodePoolMetricsRange; label: string; hours: number }[] = [
  { value: "1h", label: "1 hour", hours: 1 },
  { value: "6h", label: "6 hours", hours: 6 },
  { value: "24h", label: "24 hours", hours: 24 },
  { value: "7d", label: "7 days", hours: 168 },
  { value: "30d", label: "30 days", hours: 720 },
];

function tickFormatter(hours: number) {
  return (iso: string) => {
    const d = new Date(iso);
    return hours <= 24
      ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
      : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  };
}

function Summary({ summary, label }: { summary: NodePoolMetricSummary | null; label: string }) {
  if (!summary) return null;
  return (
    <dl className="flex gap-4 text-right" aria-label={`${label} summary`}>
      {(["current", "average", "peak"] as const).map((k) => (
        <div key={k}>
          <dt className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{k === "current" ? "Now" : k === "average" ? "Avg" : "Peak"}</dt>
          <dd className="text-sm font-semibold text-slate-800">{summary[k]}%</dd>
        </div>
      ))}
    </dl>
  );
}

function MetricChart({
  metric,
  label,
  points,
  summary,
  hours,
  formatDate,
  emptyText,
}: {
  metric: "cpu" | "memory";
  label: string;
  points: NodePoolMetricPoint[];
  summary: NodePoolMetricSummary | null;
  hours: number;
  formatDate: (v: string) => string;
  emptyText: string;
}) {
  const color = METRIC_COLORS[metric];
  const avgKey = `${metric}_avg` as const;
  const peakKey = `${metric}_max` as const;
  const hasData = points.some((p) => p[avgKey] != null);
  return (
    <div className="rounded-xl border border-att-100 bg-white p-4">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} aria-hidden="true" />
          <div>
            <h4 className="text-sm font-semibold text-slate-800">{label}</h4>
            <p className="text-xs text-slate-500">Average across the pool's VMs, %</p>
          </div>
        </div>
        <Summary summary={summary} label={label} />
      </div>
      {hasData ? (
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="t" tickFormatter={tickFormatter(hours)} tick={{ fontSize: 11, fill: "#64748b" }} minTickGap={36} axisLine={{ stroke: "#cbd5e1" }} tickLine={false} />
            <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={{ fontSize: 11, fill: "#64748b" }} tickFormatter={(v: number) => `${v}%`} axisLine={false} tickLine={false} width={48} />
            <Tooltip
              cursor={{ stroke: "#94a3b8", strokeWidth: 1 }}
              labelFormatter={(value: string) => formatDate(value)}
              formatter={(value: number, _name: string, item: { payload?: NodePoolMetricPoint }) => {
                const peak = item?.payload?.[peakKey];
                return [`${value}%${peak != null ? ` · peak ${peak}%` : ""}`, label];
              }}
              contentStyle={{ borderRadius: 8, borderColor: "#d5ecf7", fontSize: 12 }}
            />
            <Line type="monotone" dataKey={avgKey} stroke={color} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "#ffffff" }} connectNulls={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <p className="flex h-[180px] items-center justify-center px-4 text-center text-sm text-slate-400">{emptyText}</p>
      )}
    </div>
  );
}

export function NodePoolUtilisation({
  clusterId,
  nodepoolName,
  formatDate,
  stopped,
}: {
  clusterId: string;
  nodepoolName: string;
  formatDate: (value: string) => string;
  stopped: boolean;
}) {
  const [range, setRange] = useState<NodePoolMetricsRange>("24h");
  const [showTable, setShowTable] = useState(false);
  const { data, isLoading, isFetching, isError, error } = useNodePoolMetrics(clusterId, nodepoolName, range);
  const hours = RANGES.find((r) => r.value === range)?.hours ?? 24;
  const points = data?.series ?? [];
  const empty = stopped ? "The pool is stopped, so its VMs report nothing." : "No data in this range. A pool with no nodes reports nothing.";

  return (
    <DetailCard
      title="CPU & Memory Utilisation"
      subtitle={`Azure Monitor metrics of scale set ${data?.scale_set ?? "…"}${data ? `, ${data.interval.replace("PT", "").toLowerCase()} intervals` : ""}`}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-lg border border-att-200 bg-white p-0.5" role="group" aria-label="Time range">
            {RANGES.map((r) => (
              <button
                key={r.value}
                type="button"
                aria-pressed={range === r.value}
                onClick={() => setRange(r.value)}
                className={`rounded-md px-2.5 py-1 text-xs font-medium ${range === r.value ? "bg-att-500 text-white" : "text-slate-600 hover:bg-att-50"}`}
              >
                {r.value}
              </button>
            ))}
          </div>
          <button type="button" onClick={() => setShowTable((v) => !v)} className="rounded-lg border border-att-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-att-50" aria-pressed={showTable}>
            {showTable ? "Show charts" : "Show table"}
          </button>
        </div>
      }
    >
      {isError && !data ? (
        <p className="text-sm text-red-600">{apiErrorDetail(error, "Unable to read utilisation from Azure Monitor.")}</p>
      ) : isLoading && !data ? (
        <p className="py-10 text-center text-sm text-slate-500">Reading Azure Monitor…</p>
      ) : showTable ? (
        <DetailGrid
          title={`Utilisation, last ${RANGES.find((r) => r.value === range)?.label}`}
          rows={[...points].reverse()}
          columns={[
            { key: "t", header: "Time", sortValue: (p) => p.t, render: (p) => <span className="whitespace-nowrap text-xs text-slate-700">{formatDate(p.t)}</span> },
            { key: "cpu", header: "CPU Avg", align: "right", sortValue: (p) => p.cpu_avg ?? -1, render: (p) => <span className="text-xs">{p.cpu_avg ?? "—"}{p.cpu_avg != null ? "%" : ""}</span> },
            { key: "cpu_max", header: "CPU Peak", align: "right", sortValue: (p) => p.cpu_max ?? -1, render: (p) => <span className="text-xs">{p.cpu_max ?? "—"}{p.cpu_max != null ? "%" : ""}</span> },
            { key: "mem", header: "Memory Avg", align: "right", sortValue: (p) => p.memory_avg ?? -1, render: (p) => <span className="text-xs">{p.memory_avg ?? "—"}{p.memory_avg != null ? "%" : ""}</span> },
            { key: "mem_max", header: "Memory Peak", align: "right", sortValue: (p) => p.memory_max ?? -1, render: (p) => <span className="text-xs">{p.memory_max ?? "—"}{p.memory_max != null ? "%" : ""}</span> },
          ]}
          rowKey={(p) => p.t}
          searchText={(p) => p.t}
          searchPlaceholder="Search time…"
          emptyText={empty}
        />
      ) : (
        <div className={`grid grid-cols-1 gap-4 lg:grid-cols-2 ${isFetching ? "opacity-70" : ""}`}>
          <MetricChart metric="cpu" label="CPU" points={points} summary={data?.cpu ?? null} hours={hours} formatDate={formatDate} emptyText={empty} />
          <MetricChart
            metric="memory"
            label="Memory used"
            points={points}
            summary={data?.memory ?? null}
            hours={hours}
            formatDate={formatDate}
            emptyText={data?.memory_error ?? empty}
          />
        </div>
      )}
    </DetailCard>
  );
}

export default NodePoolUtilisation;
