/**
 * CPU and memory utilisation history charts, from Azure Monitor:
 *
 * - a node pool: its scale set's "Percentage CPU" and memory used
 *   (100 - "Available Memory Percentage"), averaged across the pool's VMs, or
 *   split per node — the busiest nodes as their own lines, the rest as one;
 * - a cluster or one node: AKS platform metrics node_cpu_usage_percentage and
 *   node_memory_working_set_percentage, optionally split per node pool.
 *
 * Azure Monitor is read through Azure, so these work even when the cluster's
 * Kubernetes API can't be reached. One small chart per metric, like the VM
 * utilisation panel in Infra Alerts: one percentage axis each, average line,
 * peak in the tooltip and summary.
 */

import React, { useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import {
  ClusterMetrics,
  MetricLinePoint,
  NodeMetricLines,
  NodeMetricSummary,
  NodePoolMetricPoint,
  NodePoolMetricSummary,
  NodePoolMetricsRange,
  useClusterMetrics,
  useNodePoolMetrics,
} from "../../services/aksApi";
import { DetailGrid } from "./DetailGrid";
import { apiErrorDetail } from "./detailShared";
import { DetailCard } from "./ResourceDetailShell";

// Same metric colours as the VM utilisation charts (validated pair: CVD ΔE 12.9, normal 22.3).
const METRIC_COLORS = { cpu: "#2e80ac", memory: "#7a2e75" } as const;
// Categorical order for one line per node pool (validated: worst adjacent CVD ΔE 9.1,
// normal 19.6). Three hues sit under 3:1 on white, so the legend carries values and a
// table view is always available.
const POOL_COLORS = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"];
const MAX_POOL_LINES = POOL_COLORS.length;
// "Other nodes" is a fold, not an entity: neutral and dashed, never a ninth hue.
const OTHER_COLOR = "#7b8494";

const RANGES: { value: NodePoolMetricsRange; label: string; hours: number }[] = [
  { value: "1h", label: "1 hour", hours: 1 },
  { value: "6h", label: "6 hours", hours: 6 },
  { value: "24h", label: "24 hours", hours: 24 },
  { value: "7d", label: "7 days", hours: 168 },
  { value: "30d", label: "30 days", hours: 720 },
];

type Metric = "cpu" | "memory";
type Pool = NonNullable<ClusterMetrics["pools"]>[number];

function tickFormatter(hours: number) {
  return (iso: string) => {
    const d = new Date(iso);
    return hours <= 24
      ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
      : d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  };
}

const grain = (interval?: string) => (interval ? `, ${interval.replace("PT", "").toLowerCase()} intervals` : "");
const pctCell = (v: number | null | undefined) => <span className="text-xs tabular-nums">{v != null ? `${v}%` : "—"}</span>;

function Summary({ summary, label }: { summary: NodePoolMetricSummary | null | undefined; label: string }) {
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

function ChartFrame({ color, label, note, summary, children }: { color?: string; label: string; note: string; summary?: NodePoolMetricSummary | null; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-att-100 bg-white p-4">
      <div className="mb-2 flex flex-wrap items-start justify-between gap-3">
        <div className="flex items-center gap-2">
          {color && <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} aria-hidden="true" />}
          <div>
            <h4 className="text-sm font-semibold text-slate-800">{label}</h4>
            <p className="text-xs text-slate-500">{note}</p>
          </div>
        </div>
        <Summary summary={summary} label={label} />
      </div>
      {children}
    </div>
  );
}

const axes = (hours: number) => (
  <>
    <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" vertical={false} />
    <XAxis dataKey="t" tickFormatter={tickFormatter(hours)} tick={{ fontSize: 11, fill: "#64748b" }} minTickGap={36} axisLine={{ stroke: "#cbd5e1" }} tickLine={false} />
    <YAxis domain={[0, 100]} ticks={[0, 25, 50, 75, 100]} tick={{ fontSize: 11, fill: "#64748b" }} tickFormatter={(v: number) => `${v}%`} axisLine={false} tickLine={false} width={48} />
  </>
);

function MetricChart({
  metric,
  label,
  note,
  points,
  summary,
  hours,
  formatDate,
  emptyText,
  peakLabel,
}: {
  metric: Metric;
  label: string;
  note: string;
  points: NodePoolMetricPoint[];
  summary: NodePoolMetricSummary | null | undefined;
  hours: number;
  formatDate: (v: string) => string;
  emptyText: string;
  peakLabel: string;
}) {
  const color = METRIC_COLORS[metric];
  const avgKey = `${metric}_avg` as const;
  const peakKey = `${metric}_max` as const;
  const hasData = points.some((p) => p[avgKey] != null);
  return (
    <ChartFrame color={color} label={label} note={note} summary={summary}>
      {hasData ? (
        <ResponsiveContainer width="100%" height={180}>
          <LineChart data={points} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
            {axes(hours)}
            <Tooltip
              cursor={{ stroke: "#94a3b8", strokeWidth: 1 }}
              labelFormatter={(value: string) => formatDate(value)}
              formatter={(value: number, _name: string, item: { payload?: NodePoolMetricPoint }) => {
                const peak = item?.payload?.[peakKey];
                return [`${value}%${peak != null ? ` · ${peakLabel} ${peak}%` : ""}`, label];
              }}
              contentStyle={{ borderRadius: 8, borderColor: "#d5ecf7", fontSize: 12 }}
            />
            <Line type="monotone" dataKey={avgKey} stroke={color} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "#ffffff" }} connectNulls={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <p className="flex h-[180px] items-center justify-center px-4 text-center text-sm text-slate-400">{emptyText}</p>
      )}
    </ChartFrame>
  );
}

type ChartLine = {
  name: string;
  /** Legend and tooltip text; defaults to the name. */
  label?: string;
  color: string;
  points: MetricLinePoint[];
  value: number | null | undefined;
  /** Legend suffix, e.g. "removed". */
  note?: string;
  dashed?: boolean;
};

const lastValue = (points: MetricLinePoint[]) => [...points].reverse().find((p) => p.v != null)?.v ?? null;

/** Several lines on one percentage axis, with a legend carrying each line's latest value. */
function LinesChart({ label, note, lines, hours, formatDate, footnote }: { label: string; note: string; lines: ChartLine[]; hours: number; formatDate: (v: string) => string; footnote?: React.ReactNode }) {
  const rows = useMemo(() => {
    const byTime = new Map<string, Record<string, number | string | null>>();
    for (const line of lines) {
      for (const p of line.points) {
        const row = byTime.get(p.t) ?? { t: p.t };
        row[line.name] = p.v;
        byTime.set(p.t, row);
      }
    }
    return [...byTime.values()].sort((a, b) => String(a.t).localeCompare(String(b.t)));
  }, [lines]);
  return (
    <ChartFrame label={label} note={note}>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: -12 }}>
          {axes(hours)}
          <Tooltip
            cursor={{ stroke: "#94a3b8", strokeWidth: 1 }}
            labelFormatter={(value: string) => formatDate(value)}
            itemSorter={(item) => -Number(item.value ?? 0)}
            formatter={(value: number, name: string) => [`${value}%`, name]}
            contentStyle={{ borderRadius: 8, borderColor: "#d5ecf7", fontSize: 12 }}
          />
          {lines.map((line) => (
            <Line
              key={line.name}
              type="monotone"
              dataKey={line.name}
              name={line.label ?? line.name}
              stroke={line.color}
              strokeWidth={2}
              strokeDasharray={line.dashed ? "5 4" : undefined}
              dot={false}
              activeDot={{ r: 4, strokeWidth: 2, stroke: "#ffffff" }}
              connectNulls={false}
              isAnimationActive={false}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
      <ul className="mt-2 flex flex-wrap gap-x-4 gap-y-1" aria-label={`${label} legend`}>
        {lines.map((line) => (
          <li key={line.name} className="inline-flex items-center gap-1.5 text-xs text-slate-700" title={line.name}>
            <span
              className="h-0.5 w-4 rounded"
              style={line.dashed ? { backgroundImage: `linear-gradient(to right, ${line.color} 60%, transparent 60%)`, backgroundSize: "6px 2px" } : { background: line.color }}
              aria-hidden="true"
            />
            {line.label ?? line.name}
            <span className="tabular-nums text-slate-500">{line.value != null ? `${line.value}%` : "—"}</span>
            {line.note && <span className="text-slate-400">({line.note})</span>}
          </li>
        ))}
      </ul>
      {footnote && <p className="mt-1 text-xs text-slate-500">{footnote}</p>}
    </ChartFrame>
  );
}

/** One line per node pool, coloured by the pool's fixed position in the list (never by rank). */
function PoolsChart({ metric, label, pools, hours, formatDate }: { metric: Metric; label: string; pools: Pool[]; hours: number; formatDate: (v: string) => string }) {
  const key = `${metric}_avg` as const;
  const lines = useMemo(
    () => pools.map((pool, i) => ({ name: pool.name, color: POOL_COLORS[i], points: pool.series.map((p) => ({ t: p.t, v: p[key] ?? null })), value: pool[metric]?.current })),
    [pools, key, metric]
  );
  return <LinesChart label={label} note="Average across each pool's nodes, %" lines={lines} hours={hours} formatDate={formatDate} />;
}

/** "aks-np7-11356500-vmss000i1p" → "vmss000i1p": the part that differs between a pool's nodes. */
export const shortNodeName = (name: string) => name.replace(/^aks-[a-z0-9]+-\d+-/, "");

/** The busiest nodes of a pool, each its own line, and everything else as one dashed average. */
function NodesChart({ label, lines, nodes, hours, formatDate }: { label: string; lines: NodeMetricLines; nodes: NodeMetricSummary[]; hours: number; formatDate: (v: string) => string }) {
  const chartLines = useMemo(() => {
    const reporting = new Map(nodes.map((n) => [n.name, n.reporting]));
    const out: ChartLine[] = lines.top.map((line, i) => ({
      name: line.name,
      label: shortNodeName(line.name),
      color: POOL_COLORS[i],
      points: line.series,
      value: lastValue(line.series),
      note: reporting.get(line.name) === false ? "removed" : undefined,
    }));
    if (lines.other) {
      const name = `Other ${lines.other.count} node${lines.other.count === 1 ? "" : "s"}, average`;
      out.push({ name, color: OTHER_COLOR, points: lines.other.series, value: lastValue(lines.other.series), dashed: true });
    }
    return out;
  }, [lines, nodes]);
  const note = lines.other ? `The ${lines.top.length} busiest nodes by average, %` : "Each node, %";
  return <LinesChart label={label} note={note} lines={chartLines} hours={hours} formatDate={formatDate} />;
}

function NodesTable({ nodes, range, emptyText, onOpenNode }: { nodes: NodeMetricSummary[]; range: NodePoolMetricsRange; emptyText: string; onOpenNode?: (name: string) => void }) {
  return (
    <DetailGrid
      title={`Nodes, last ${RANGES.find((r) => r.value === range)?.label}`}
      rows={nodes}
      columns={[
        {
          key: "name",
          header: "Node",
          sortValue: (n) => n.name,
          render: (n) =>
            onOpenNode && n.reporting ? (
              <button type="button" onClick={() => onOpenNode(n.name)} className="text-left font-mono text-xs font-medium text-att-700 hover:text-att-900 hover:underline">
                {n.name}
              </button>
            ) : (
              <span className="font-mono text-xs text-slate-700">{n.name}</span>
            ),
        },
        {
          key: "reporting",
          header: "Status",
          sortValue: (n) => (n.reporting ? 1 : 0),
          render: (n) =>
            n.reporting ? (
              <span className="text-xs text-slate-700">Reporting</span>
            ) : (
              <span className="whitespace-nowrap text-xs text-slate-500" title={`Last reported ${n.last_seen}`}>Removed</span>
            ),
        },
        { key: "cpu_now", header: "CPU Now", align: "right", sortValue: (n) => n.cpu?.current ?? -1, render: (n) => pctCell(n.cpu?.current) },
        { key: "cpu_avg", header: "CPU Avg", align: "right", sortValue: (n) => n.cpu?.average ?? -1, render: (n) => pctCell(n.cpu?.average) },
        { key: "cpu_peak", header: "CPU Peak", align: "right", sortValue: (n) => n.cpu?.peak ?? -1, render: (n) => pctCell(n.cpu?.peak) },
        { key: "mem_now", header: "Memory Now", align: "right", sortValue: (n) => n.memory?.current ?? -1, render: (n) => pctCell(n.memory?.current) },
        { key: "mem_avg", header: "Memory Avg", align: "right", sortValue: (n) => n.memory?.average ?? -1, render: (n) => pctCell(n.memory?.average) },
        { key: "mem_peak", header: "Memory Peak", align: "right", sortValue: (n) => n.memory?.peak ?? -1, render: (n) => pctCell(n.memory?.peak) },
      ]}
      rowKey={(n) => n.name}
      searchText={(n) => n.name}
      searchPlaceholder="Search node…"
      emptyText={emptyText}
      initialSort={{ key: "cpu_avg", direction: "desc" }}
      defaultPageSize={25}
    />
  );
}

function ModeToggle<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: { value: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-att-200 bg-white p-0.5" role="group" aria-label={label}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          aria-pressed={value === o.value}
          onClick={() => onChange(o.value)}
          className={`rounded-md px-2.5 py-1 text-xs font-medium ${value === o.value ? "bg-att-500 text-white" : "text-slate-600 hover:bg-att-50"}`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function RangePicker({ range, onChange }: { range: NodePoolMetricsRange; onChange: (r: NodePoolMetricsRange) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-att-200 bg-white p-0.5" role="group" aria-label="Time range">
      {RANGES.map((r) => (
        <button
          key={r.value}
          type="button"
          aria-pressed={range === r.value}
          onClick={() => onChange(r.value)}
          className={`rounded-md px-2.5 py-1 text-xs font-medium ${range === r.value ? "bg-att-500 text-white" : "text-slate-600 hover:bg-att-50"}`}
        >
          {r.value}
        </button>
      ))}
    </div>
  );
}

const toggleBtn = "rounded-lg border border-att-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-att-50";

function SeriesTable({ points, range, formatDate, emptyText }: { points: NodePoolMetricPoint[]; range: NodePoolMetricsRange; formatDate: (v: string) => string; emptyText: string }) {
  return (
    <DetailGrid
      title={`Utilisation, last ${RANGES.find((r) => r.value === range)?.label}`}
      rows={[...points].reverse()}
      columns={[
        { key: "t", header: "Time", sortValue: (p) => p.t, render: (p) => <span className="whitespace-nowrap text-xs text-slate-700">{formatDate(p.t)}</span> },
        { key: "cpu", header: "CPU Avg", align: "right", sortValue: (p) => p.cpu_avg ?? -1, render: (p) => pctCell(p.cpu_avg) },
        { key: "cpu_max", header: "CPU Peak", align: "right", sortValue: (p) => p.cpu_max ?? -1, render: (p) => pctCell(p.cpu_max) },
        { key: "mem", header: "Memory Avg", align: "right", sortValue: (p) => p.memory_avg ?? -1, render: (p) => pctCell(p.memory_avg) },
        { key: "mem_max", header: "Memory Peak", align: "right", sortValue: (p) => p.memory_max ?? -1, render: (p) => pctCell(p.memory_max) },
      ]}
      rowKey={(p) => p.t}
      searchText={(p) => p.t}
      searchPlaceholder="Search time…"
      emptyText={emptyText}
    />
  );
}

function PanelState({ isError, error, isLoading, hasData }: { isError: boolean; error: unknown; isLoading: boolean; hasData: boolean }) {
  if (isError && !hasData) return <p className="text-sm text-red-600">{apiErrorDetail(error, "Unable to read utilisation from Azure Monitor.")}</p>;
  if (isLoading && !hasData) return <p className="py-10 text-center text-sm text-slate-500">Reading Azure Monitor…</p>;
  return null;
}

export function NodePoolUtilisation({
  clusterId,
  nodepoolName,
  formatDate,
  stopped,
  onOpenNode,
}: {
  clusterId: string;
  nodepoolName: string;
  formatDate: (value: string) => string;
  stopped: boolean;
  /** Open a node's detail from the per-node table. */
  onOpenNode?: (name: string) => void;
}) {
  const [range, setRange] = useState<NodePoolMetricsRange>("24h");
  const [mode, setMode] = useState<"pool" | "node">("pool");
  const [showTable, setShowTable] = useState(false);
  const byNode = mode === "node";
  const pool = useNodePoolMetrics(clusterId, nodepoolName, range);
  const perNode = useClusterMetrics(clusterId, range, { split: "node", nodepool: nodepoolName }, byNode);
  const { data, isLoading, isFetching, isError, error } = pool;
  const nodesData = perNode.data?.scope === "nodes" && perNode.data.nodepool === nodepoolName ? perNode.data : undefined;
  const hours = RANGES.find((r) => r.value === range)?.hours ?? 24;
  const points = data?.series ?? [];
  const empty = stopped ? "The pool is stopped, so its VMs report nothing." : "No data in this range. A pool with no nodes reports nothing.";
  const note = "Average across the pool's VMs, %";
  const nodes = nodesData?.nodes ?? [];
  const reportingNow = nodes.filter((n) => n.reporting).length;

  const subtitle = byNode
    ? `AKS metrics node_cpu_usage_percentage and node_memory_working_set_percentage${grain(nodesData?.interval)}${
        nodesData ? ` · ${reportingNow} node${reportingNow === 1 ? "" : "s"} reporting now, ${nodes.length} in this range` : ""
      }`
    : `Azure Monitor metrics of scale set ${data?.scale_set ?? "…"}${grain(data?.interval)}`;

  return (
    <DetailCard
      title="CPU & Memory Utilisation"
      subtitle={subtitle}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          <ModeToggle<"pool" | "node">
            label="Breakdown"
            value={mode}
            onChange={setMode}
            options={[
              { value: "pool", label: "Pool" },
              { value: "node", label: "By node" },
            ]}
          />
          <RangePicker range={range} onChange={setRange} />
          <button type="button" onClick={() => setShowTable((v) => !v)} className={toggleBtn} aria-pressed={showTable}>
            {showTable ? "Show charts" : "Show table"}
          </button>
        </div>
      }
    >
      {byNode ? (
        <>
          <PanelState isError={perNode.isError} error={perNode.error} isLoading={perNode.isLoading || (!!perNode.data && !nodesData)} hasData={!!nodesData} />
          {nodesData &&
            (showTable ? (
              <NodesTable nodes={nodes} range={range} emptyText={empty} onOpenNode={onOpenNode} />
            ) : nodes.length && nodesData.lines ? (
              <div className={`space-y-2 ${perNode.isFetching ? "opacity-70" : ""}`}>
                <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
                  <NodesChart label="CPU by node" lines={nodesData.lines.cpu} nodes={nodes} hours={hours} formatDate={formatDate} />
                  <NodesChart label="Memory working set by node" lines={nodesData.lines.memory} nodes={nodes} hours={hours} formatDate={formatDate} />
                </div>
                <p className="text-xs text-slate-500">
                  {nodesData.lines.cpu.other
                    ? "Each chart draws the busiest nodes on its own and averages the rest into the dashed line. Show table lists every node."
                    : "Show table lists every node with its current, average and peak use."}
                  {nodesData.truncated && " Azure Monitor returned its maximum number of nodes, so some may be missing."}
                </p>
              </div>
            ) : (
              <p className="py-10 text-center text-sm text-slate-400">{empty}</p>
            ))}
        </>
      ) : (
        <>
          <PanelState isError={isError} error={error} isLoading={isLoading} hasData={!!data} />
          {data &&
            (showTable ? (
              <SeriesTable points={points} range={range} formatDate={formatDate} emptyText={empty} />
            ) : (
              <div className={`grid grid-cols-1 gap-4 lg:grid-cols-2 ${isFetching ? "opacity-70" : ""}`}>
                <MetricChart metric="cpu" label="CPU" note={note} points={points} summary={data.cpu} hours={hours} formatDate={formatDate} emptyText={empty} peakLabel="peak" />
                <MetricChart metric="memory" label="Memory used" note={note} points={points} summary={data.memory} hours={hours} formatDate={formatDate} emptyText={data.memory_error ?? empty} peakLabel="peak" />
              </div>
            ))}
        </>
      )}
    </DetailCard>
  );
}

/**
 * Cluster-wide (optionally per node pool) or single-node utilisation history
 * from AKS platform metrics.
 */
export function ClusterUtilisation({
  clusterId,
  node,
  formatDate,
  title = "CPU & Memory Utilisation",
  actions,
}: {
  clusterId: string;
  /** Show one node instead of the whole cluster. */
  node?: string;
  formatDate: (value: string) => string;
  title?: string;
  /** Extra header controls, e.g. a cluster picker. */
  actions?: React.ReactNode;
}) {
  const [range, setRange] = useState<NodePoolMetricsRange>("24h");
  const [byPool, setByPool] = useState(false);
  const [showTable, setShowTable] = useState(false);
  const split = !node && byPool ? "nodepool" : "none";
  const { data, isLoading, isFetching, isError, error } = useClusterMetrics(clusterId, range, { node, split });
  // While the other mode loads, the previous response (other shape) is still shown — don't misread it.
  const current = data && (split === "nodepool" ? data.scope === "nodepools" : data.scope !== "nodepools") ? data : undefined;
  const hours = RANGES.find((r) => r.value === range)?.hours ?? 24;
  const points = current?.series ?? [];
  const pools = (current?.pools ?? []).slice(0, MAX_POOL_LINES);
  const empty = node ? "No data in this range. The node may have been removed or just joined." : "No data in this range. A stopped cluster reports nothing.";
  const note = node ? "This node, %" : "Average across the cluster's nodes, %";
  const peakLabel = node ? "peak" : "busiest node";

  return (
    <DetailCard
      title={title}
      subtitle={`AKS metrics node_cpu_usage_percentage and node_memory_working_set_percentage${grain(current?.interval)}${node ? "" : byPool ? " · one line per node pool" : " · peak is the busiest node"}`}
      actions={
        <div className="flex flex-wrap items-center gap-2">
          {actions}
          {!node && (
            <ModeToggle<"cluster" | "nodepool">
              label="Breakdown"
              value={byPool ? "nodepool" : "cluster"}
              onChange={(v) => setByPool(v === "nodepool")}
              options={[
                { value: "cluster", label: "Cluster" },
                { value: "nodepool", label: "By node pool" },
              ]}
            />
          )}
          <RangePicker range={range} onChange={setRange} />
          <button type="button" onClick={() => setShowTable((v) => !v)} className={toggleBtn} aria-pressed={showTable}>
            {showTable ? "Show charts" : "Show table"}
          </button>
        </div>
      }
    >
      <PanelState isError={isError} error={error} isLoading={isLoading || (!!data && !current)} hasData={!!current} />
      {current && split === "nodepool" ? (
        showTable ? (
          <DetailGrid
            title={`Node pools, last ${RANGES.find((r) => r.value === range)?.label}`}
            rows={current.pools ?? []}
            columns={[
              { key: "name", header: "Node Pool", sortValue: (p) => p.name, render: (p) => <span className="font-medium text-slate-800">{p.name}</span> },
              { key: "cpu_now", header: "CPU Now", align: "right", sortValue: (p) => p.cpu?.current ?? -1, render: (p) => pctCell(p.cpu?.current) },
              { key: "cpu_avg", header: "CPU Avg", align: "right", sortValue: (p) => p.cpu?.average ?? -1, render: (p) => pctCell(p.cpu?.average) },
              { key: "cpu_peak", header: "CPU Peak", align: "right", sortValue: (p) => p.cpu?.peak ?? -1, render: (p) => pctCell(p.cpu?.peak) },
              { key: "mem_now", header: "Memory Now", align: "right", sortValue: (p) => p.memory?.current ?? -1, render: (p) => pctCell(p.memory?.current) },
              { key: "mem_avg", header: "Memory Avg", align: "right", sortValue: (p) => p.memory?.average ?? -1, render: (p) => pctCell(p.memory?.average) },
              { key: "mem_peak", header: "Memory Peak", align: "right", sortValue: (p) => p.memory?.peak ?? -1, render: (p) => pctCell(p.memory?.peak) },
            ]}
            rowKey={(p) => p.name}
            searchText={(p) => p.name}
            searchPlaceholder="Search node pool…"
            emptyText={empty}
          />
        ) : pools.length ? (
          <div className={`space-y-2 ${isFetching ? "opacity-70" : ""}`}>
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <PoolsChart metric="cpu" label="CPU by node pool" pools={pools} hours={hours} formatDate={formatDate} />
              <PoolsChart metric="memory" label="Memory working set by node pool" pools={pools} hours={hours} formatDate={formatDate} />
            </div>
            {(current.pools?.length ?? 0) > MAX_POOL_LINES && (
              <p className="text-xs text-slate-500">Showing the first {MAX_POOL_LINES} of {current.pools!.length} pools; the table lists them all.</p>
            )}
          </div>
        ) : (
          <p className="py-10 text-center text-sm text-slate-400">{empty}</p>
        )
      ) : current ? (
        showTable ? (
          <SeriesTable points={points} range={range} formatDate={formatDate} emptyText={empty} />
        ) : (
          <div className={`grid grid-cols-1 gap-4 lg:grid-cols-2 ${isFetching ? "opacity-70" : ""}`}>
            <MetricChart metric="cpu" label="CPU" note={note} points={points} summary={current.cpu} hours={hours} formatDate={formatDate} emptyText={empty} peakLabel={peakLabel} />
            <MetricChart metric="memory" label="Memory working set" note={note} points={points} summary={current.memory} hours={hours} formatDate={formatDate} emptyText={empty} peakLabel={peakLabel} />
          </div>
        )
      ) : null}
    </DetailCard>
  );
}

export default NodePoolUtilisation;
