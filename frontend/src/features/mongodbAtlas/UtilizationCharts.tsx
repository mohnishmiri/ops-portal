/**
 * Cluster utilization over time — CPU, memory, connections and disk, one
 * small chart per metric (never two scales on one plot), one line per node.
 *
 * Node colours come from the validated categorical palette in fixed order and
 * are assigned by host name, not by role, so a failover (a new primary) does
 * not repaint the lines. The shared legend names each node, its role and its
 * latest value, and a table view lists every sample — three of the palette
 * hues sit below 3:1 on white, so identity never rests on colour alone.
 *
 * More than eight nodes (large sharded clusters) fold into "Busiest node"
 * and "Average" rather than inventing a ninth hue.
 */

import React, { useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { gridStyles, Spinner } from "../../components/gridStyles";
import { formatAxiosError } from "../../services/apiErrors";
import { type ClusterMetrics, type MetricPeriod, type MetricRow, useClusterMetrics } from "../../services/mongodbAtlasApi";
import { InfoNote } from "./shared";

// Validated (light surface): every adjacent pair passes CVD ΔE ≥ 8 and the
// normal-vision floor; slots 3–5 need the legend/table relief, which is here.
export const NODE_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"];
const MAX_NODE_LINES = NODE_COLORS.length;

const PERIODS: { value: MetricPeriod; label: string }[] = [
  { value: "PT1H", label: "1h" },
  { value: "PT6H", label: "6h" },
  { value: "PT24H", label: "24h" },
  { value: "P7D", label: "7d" },
  { value: "P30D", label: "30d" },
];

type MetricKey = "cpu" | "memory" | "connections" | "disk";

const METRICS: { key: MetricKey; label: string; unit: "%" | ""; help: string }[] = [
  { key: "cpu", label: "CPU", unit: "%", help: "Normalized system CPU, user + kernel" },
  { key: "memory", label: "Memory in use", unit: "%", help: "Used ÷ (used + available)" },
  { key: "connections", label: "Connections", unit: "", help: "Open connections per node" },
  { key: "disk", label: "Disk space used", unit: "%", help: "Data partition" },
];

interface Series {
  key: string;
  label: string;
  role: string;
  color: string;
}

/** Series to draw: one per node, or busiest/average when there are too many. */
function useSeries(data: ClusterMetrics | undefined): { series: Series[]; rows: Record<MetricKey, MetricRow[]>; folded: boolean } {
  return useMemo(() => {
    const empty = { cpu: [], memory: [], connections: [], disk: [] } as Record<MetricKey, MetricRow[]>;
    if (!data) return { series: [], rows: empty, folded: false };
    const nodes = [...data.nodes].sort((a, b) => a.label.localeCompare(b.label, undefined, { numeric: true }));
    if (nodes.length <= MAX_NODE_LINES) {
      return {
        series: nodes.map((n, i) => ({ key: n.key, label: n.label, role: n.role, color: NODE_COLORS[i] })),
        rows: data.series as Record<MetricKey, MetricRow[]>,
        folded: false,
      };
    }
    const keys = nodes.map((n) => n.key);
    const fold = (rows: MetricRow[]): MetricRow[] =>
      rows.map((row) => {
        const values = keys.map((k) => row[k]).filter((v): v is number => typeof v === "number");
        return {
          time: row.time,
          max: values.length ? Math.max(...values) : null,
          avg: values.length ? Math.round((values.reduce((a, b) => a + b, 0) / values.length) * 10) / 10 : null,
        };
      });
    return {
      series: [
        { key: "max", label: "Busiest node", role: `of ${nodes.length}`, color: NODE_COLORS[0] },
        { key: "avg", label: "Average", role: `of ${nodes.length}`, color: NODE_COLORS[1] },
      ],
      rows: {
        cpu: fold(data.series.cpu),
        memory: fold(data.series.memory),
        connections: fold(data.series.connections),
        disk: fold(data.series.disk),
      },
      folded: true,
    };
  }, [data]);
}

function lastValue(rows: MetricRow[], key: string): number | null {
  for (let i = rows.length - 1; i >= 0; i -= 1) {
    const v = rows[i][key];
    if (typeof v === "number") return v;
  }
  return null;
}

function tickFormatter(period: MetricPeriod) {
  const short = period === "PT1H" || period === "PT6H" || period === "PT24H";
  return (value: string) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return short
      ? date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
      : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  };
}

const MetricChart: React.FC<{
  metric: (typeof METRICS)[number];
  rows: MetricRow[];
  series: Series[];
  period: MetricPeriod;
  formatDate: (v: string) => string;
}> = ({ metric, rows, series, period, formatDate }) => {
  const hasData = rows.some((row) => series.some((s) => typeof row[s.key] === "number"));
  const peak = series.reduce<number | null>((best, s) => {
    const v = lastValue(rows, s.key);
    return v == null ? best : best == null ? v : Math.max(best, v);
  }, null);
  return (
    <figure className="rounded-xl border border-att-100 bg-white p-4">
      <figcaption className="mb-1 flex items-baseline justify-between gap-2">
        <span>
          <span className="text-sm font-semibold text-slate-800">{metric.label}</span>
          <span className="ml-2 text-xs text-slate-500">{metric.help}</span>
        </span>
        {peak != null && (
          <span className="text-xs text-slate-500">
            now <span className="font-semibold text-slate-800">{peak}{metric.unit}</span>
            {series.length > 1 ? " (highest node)" : ""}
          </span>
        )}
      </figcaption>
      {hasData ? (
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="#eef2f6" vertical={false} />
            <XAxis
              dataKey="time"
              tickFormatter={tickFormatter(period)}
              tick={{ fontSize: 11, fill: "#64748b" }}
              minTickGap={40}
              axisLine={{ stroke: "#cbd5e1" }}
              tickLine={false}
            />
            <YAxis
              domain={metric.unit === "%" ? [0, 100] : [0, "auto"]}
              tick={{ fontSize: 11, fill: "#64748b" }}
              tickFormatter={(v: number) => `${v}${metric.unit}`}
              axisLine={false}
              tickLine={false}
              width={48}
              allowDecimals={false}
            />
            <Tooltip
              cursor={{ stroke: "#94a3b8", strokeWidth: 1 }}
              labelFormatter={(value: string) => formatDate(value)}
              formatter={(value: number, name: string) => {
                const s = series.find((x) => x.key === name);
                return [`${value}${metric.unit}`, s ? `${s.label} · ${s.role}` : name];
              }}
              contentStyle={{ borderRadius: 8, borderColor: "#d5ecf7", fontSize: 12 }}
            />
            {series.map((s) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.key}
                stroke={s.color}
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, strokeWidth: 2, stroke: "#ffffff" }}
                connectNulls={false}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <p className="flex h-[180px] items-center justify-center text-sm text-slate-400">No samples in this range.</p>
      )}
    </figure>
  );
};

const MetricsTable: React.FC<{ rows: Record<MetricKey, MetricRow[]>; series: Series[]; formatDate: (v: string) => string }> = ({
  rows,
  series,
  formatDate,
}) => {
  const [metric, setMetric] = useState<MetricKey>("cpu");
  const spec = METRICS.find((m) => m.key === metric)!;
  const data = [...rows[metric]].reverse();
  return (
    <div className={gridStyles.shell}>
      <div className={gridStyles.panelHeader}>
        <span className={gridStyles.sectionTitle}>Samples (newest first)</span>
        <select
          value={metric}
          onChange={(e) => setMetric(e.target.value as MetricKey)}
          aria-label="Metric shown in the table"
          className="rounded-lg border border-att-200 bg-white px-2 py-1.5 text-sm"
        >
          {METRICS.map((m) => (
            <option key={m.key} value={m.key}>
              {m.label}
            </option>
          ))}
        </select>
      </div>
      <div className="max-h-72 overflow-auto">
        <table className={gridStyles.table}>
          <thead className={gridStyles.stickyHead}>
            <tr>
              <th className={gridStyles.headerCell}>Time</th>
              {series.map((s) => (
                <th key={s.key} className={`${gridStyles.headerCell} text-right`}>
                  {s.label} <span className="font-normal normal-case tracking-normal text-slate-500">{s.role}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((row) => (
              <tr key={row.time} className={gridStyles.row}>
                <td className={gridStyles.cell}>{formatDate(row.time)}</td>
                {series.map((s) => (
                  <td key={s.key} className={`${gridStyles.cell} text-right tabular-nums`}>
                    {typeof row[s.key] === "number" ? `${row[s.key]}${spec.unit}` : "—"}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

export const UtilizationCharts: React.FC<{
  projectId: string;
  clusterName: string;
  paused: boolean;
  formatDate: (value: string) => string;
}> = ({ projectId, clusterName, paused, formatDate }) => {
  const [period, setPeriod] = useState<MetricPeriod>("PT24H");
  const [showTable, setShowTable] = useState(false);
  const { data, isLoading, isError, error, isFetching } = useClusterMetrics(projectId, clusterName, period, !paused);
  const { series, rows, folded } = useSeries(data);

  if (paused) {
    return <InfoNote>The cluster is paused. Atlas records no CPU or memory while it is stopped — start it to see utilization.</InfoNote>;
  }

  return (
    <section aria-label="Cluster utilization" className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* One legend for all four charts: the nodes are the same in each. */}
        <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-slate-700" aria-label="Nodes">
          {series.map((s) => {
            const cpu = lastValue(rows.cpu, s.key);
            return (
              <li key={s.key} className="inline-flex items-center gap-1.5">
                <span className="h-0.5 w-4 rounded-full" style={{ background: s.color }} aria-hidden="true" />
                <span className="font-semibold">{s.label}</span>
                <span className="text-slate-500">{s.role}</span>
                {cpu != null && <span className="text-slate-500">· CPU {cpu}%</span>}
              </li>
            );
          })}
        </ul>
        <div className="flex items-center gap-2">
          {isFetching && <Spinner />}
          <div className="inline-flex overflow-hidden rounded-lg border border-att-200" role="group" aria-label="Time range">
            {PERIODS.map((p) => (
              <button
                key={p.value}
                type="button"
                onClick={() => setPeriod(p.value)}
                aria-pressed={period === p.value}
                className={`px-2.5 py-1 text-xs font-medium ${period === p.value ? "bg-att-500 text-white" : "bg-white text-slate-600 hover:bg-att-50"}`}
              >
                {p.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setShowTable((v) => !v)}
            aria-pressed={showTable}
            className="rounded-lg border border-att-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-att-50"
          >
            {showTable ? "Charts" : "Table"}
          </button>
        </div>
      </div>

      {isLoading ? (
        <div className="flex h-40 items-center justify-center gap-2 text-sm text-slate-500">
          <Spinner /> Loading metrics from Atlas…
        </div>
      ) : isError ? (
        <InfoNote tone="error">{formatAxiosError(error, "Could not load metrics")}</InfoNote>
      ) : (
        <>
          {data?.notes.map((note) => (
            <InfoNote key={note} tone="warning">
              {note}
            </InfoNote>
          ))}
          {folded && <InfoNote>This cluster has {data?.nodes.length} nodes; the charts show the busiest node and the average.</InfoNote>}
          {showTable ? (
            <MetricsTable rows={rows} series={series} formatDate={formatDate} />
          ) : (
            <div className="grid gap-3 lg:grid-cols-2">
              {METRICS.map((m) => (
                <MetricChart key={m.key} metric={m} rows={rows[m.key]} series={series} period={period} formatDate={formatDate} />
              ))}
            </div>
          )}
          <p className="text-[11px] text-slate-400">
            Sampled every {data?.granularity === "PT1M" ? "minute" : data?.granularity === "PT5M" ? "5 minutes" : "hour"} by Atlas.
            Memory is computed from Atlas's used and available memory; Atlas publishes no percentage.
          </p>
        </>
      )}
    </section>
  );
};
