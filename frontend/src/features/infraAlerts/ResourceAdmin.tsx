/**
 * Utilization charts, disks, Run Command and administration panels for the
 * Infrastructure Alerts resource detail views.
 *
 * Chart palette (validated with the dataviz checks — lightness, chroma, CVD
 * separation, normal-vision floor, contrast all pass on white): CPU ATT blue
 * #2e80ac, memory plum #7a2e75, disk / storage aqua #25a37c. Each metric is
 * its own small chart (one y-axis, one series), so warning / critical lines
 * belong to exactly one metric. Amber and red stay reserved for those lines
 * and for the status bars in the grids.
 */

import React, { useMemo, useState } from "react";
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Spinner } from "../../components/gridStyles";
import { apiErrorMessage, type ManagedDisk, type PGFlexServer, type VMInfo } from "../../services/infraAlertApi";
import {
  type AdminResourceType,
  azurePortalUrl,
  type MetricKind,
  type MetricsPoint,
  type PGDatabase,
  type PGOverview,
  type RunHistoryItem,
  TERMINAL_RUN_STATES,
  useAvailableSizes,
  useBootDiagnostics,
  useExpandDisk,
  useMetricsHistory,
  usePGOverview,
  useRedeployVM,
  useReplaceTags,
  useResizeVM,
  useRunCommandHistory,
  useRunCommandStatus,
  useSnapshotDisk,
  useStartRunCommand,
  type VMTarget,
} from "../../services/infraResourceAdminApi";
import { DetailGrid, type GridColumn } from "../aks/DetailGrid";
import { DetailCard, PropertyList } from "../aks/ResourceDetailShell";
import { formatBytes, InfraIcons } from "./shared";

export const METRIC_COLORS: Record<string, string> = {
  cpu: "#2e80ac",
  memory: "#7a2e75",
  disk: "#25a37c",
  storage: "#25a37c",
  connections: "#2e80ac",
};
const WARNING_COLOR = "#d97706";
const CRITICAL_COLOR = "#dc2626";

export interface ConfirmRequest {
  title: string;
  message: string;
  confirmLabel: string;
  onConfirm: () => void;
}

type Toast = (message: string, type?: "success" | "error" | "info") => void;

const button =
  "inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg border px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 [&>svg]:h-4 [&>svg]:w-4";
const tone = {
  neutral: "border-att-200 bg-white text-slate-700 hover:bg-att-50",
  primary: "border-att-600 bg-att-600 text-white hover:bg-att-700",
  amber: "border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100",
  red: "border-red-200 bg-red-50 text-red-700 hover:bg-red-100",
};
const inputClass =
  "rounded-lg border border-att-200 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100";

// ── Inline utilization bar (grids) ────────────────────────────────────

/** "62%" with a thin bar coloured by state: below warning, warning, critical. */
export function UtilizationBar({ value, warning = 70, critical = 90, title }: { value: number | null | undefined; warning?: number; critical?: number; title?: string }) {
  if (value == null) return <span className="text-xs text-slate-400">—</span>;
  const color = value >= critical ? CRITICAL_COLOR : value >= warning ? WARNING_COLOR : "#16a34a";
  const label = value >= critical ? "critical" : value >= warning ? "warning" : "normal";
  return (
    <div className="w-24" title={title ? `${title}: ${value}% (${label})` : `${value}%`}>
      <div className="flex items-baseline justify-between">
        <span className="text-xs font-semibold text-slate-800">{value.toFixed(0)}%</span>
        {value >= warning && <span className="text-[10px] font-semibold uppercase" style={{ color }}>{label}</span>}
      </div>
      <div className="mt-0.5 h-1.5 overflow-hidden rounded-full bg-slate-100">
        <div className="h-full rounded-full" style={{ width: `${Math.min(100, Math.max(2, value))}%`, background: color }} />
      </div>
    </div>
  );
}

// ── Utilization history ───────────────────────────────────────────────

const RANGES = [
  { hours: 1, label: "1h" },
  { hours: 6, label: "6h" },
  { hours: 24, label: "24h" },
  { hours: 168, label: "7d" },
  { hours: 720, label: "30d" },
];

interface MetricSpec {
  key: keyof MetricsPoint & string;
  label: string;
  unit: "%" | "";
  warning?: number;
  critical?: number;
}

function tickFormatter(hours: number) {
  return (value: string) => {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return hours <= 24
      ? date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
      : date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
  };
}

function MetricChart({ spec, points, hours, formatDate }: { spec: MetricSpec; points: MetricsPoint[]; hours: number; formatDate: (v: string) => string }) {
  const color = METRIC_COLORS[spec.key] ?? METRIC_COLORS.cpu;
  const peakKey = `${spec.key}_max` as keyof MetricsPoint;
  const hasData = points.some((p) => p[spec.key] != null);
  return (
    <div className="rounded-xl border border-att-100 bg-white p-4">
      <div className="mb-1 flex items-center gap-2">
        <span className="h-2.5 w-2.5 rounded-full" style={{ background: color }} aria-hidden="true" />
        <h4 className="text-sm font-semibold text-slate-800">{spec.label}</h4>
        <span className="text-xs text-slate-500">average per interval{spec.unit === "%" ? ", %" : ""}</span>
      </div>
      {hasData ? (
        <ResponsiveContainer width="100%" height={170}>
          <LineChart data={points} margin={{ top: 8, right: 56, bottom: 0, left: -12 }}>
            <CartesianGrid stroke="#e5e7eb" strokeDasharray="3 3" vertical={false} />
            <XAxis dataKey="time" tickFormatter={tickFormatter(hours)} tick={{ fontSize: 11, fill: "#64748b" }} minTickGap={36} axisLine={{ stroke: "#cbd5e1" }} tickLine={false} />
            <YAxis
              domain={spec.unit === "%" ? [0, 100] : [0, "auto"]}
              tick={{ fontSize: 11, fill: "#64748b" }}
              tickFormatter={(v: number) => `${v}${spec.unit}`}
              axisLine={false}
              tickLine={false}
              width={48}
            />
            <Tooltip
              cursor={{ stroke: "#94a3b8", strokeWidth: 1 }}
              labelFormatter={(value: string) => formatDate(value)}
              formatter={(value: number, _name: string, item: { payload?: MetricsPoint }) => {
                const peak = item?.payload?.[peakKey] as number | undefined;
                return [`${value}${spec.unit}${peak != null ? ` · peak ${peak}${spec.unit}` : ""}`, spec.label];
              }}
              contentStyle={{ borderRadius: 8, borderColor: "#d5ecf7", fontSize: 12 }}
            />
            {spec.warning != null && (
              <ReferenceLine y={spec.warning} stroke={WARNING_COLOR} strokeDasharray="4 4" label={{ value: `Warn ${spec.warning}${spec.unit}`, position: "right", fill: "#92400e", fontSize: 10 }} />
            )}
            {spec.critical != null && (
              <ReferenceLine y={spec.critical} stroke={CRITICAL_COLOR} strokeDasharray="4 4" label={{ value: `Crit ${spec.critical}${spec.unit}`, position: "right", fill: "#991b1b", fontSize: 10 }} />
            )}
            <Line type="monotone" dataKey={spec.key} stroke={color} strokeWidth={2} dot={false} activeDot={{ r: 4, strokeWidth: 2, stroke: "#ffffff" }} connectNulls={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
      ) : (
        <p className="flex h-[170px] items-center justify-center text-sm text-slate-400">No data in this range — a stopped resource reports nothing.</p>
      )}
    </div>
  );
}

export function UtilizationPanel({
  kind,
  subscriptionId,
  resourceGroup,
  name,
  thresholds,
  formatDate,
  defaultHours = 24,
  only,
}: {
  kind: MetricKind;
  subscriptionId: string;
  resourceGroup: string;
  name: string;
  thresholds?: Partial<Record<string, { warning: number; critical: number }>>;
  formatDate: (value: string) => string;
  defaultHours?: number;
  /** Show only these metrics (e.g. the one an alert is about). */
  only?: string[];
}) {
  const [hours, setHours] = useState(defaultHours);
  const [showTable, setShowTable] = useState(false);
  const { data, isLoading, isError, error, isFetching } = useMetricsHistory(kind, subscriptionId, resourceGroup, name, hours);
  const specs: MetricSpec[] = (
    kind === "vm"
      ? [
          { key: "cpu", label: "CPU", unit: "%" },
          { key: "memory", label: "Memory in use", unit: "%" },
          { key: "disk", label: "Disk I/O (busiest disk)", unit: "%" },
        ]
      : [
          { key: "cpu", label: "CPU", unit: "%" },
          { key: "memory", label: "Memory", unit: "%" },
          { key: "storage", label: "Storage used", unit: "%" },
          { key: "connections", label: "Active connections", unit: "" },
        ]
  )
    .filter((spec) => !only || only.includes(spec.key))
    .map((spec) => ({ ...spec, ...(thresholds?.[spec.key] ?? {}) })) as MetricSpec[];
  const points = data?.points ?? [];

  const tableColumns: GridColumn<MetricsPoint>[] = [
    { key: "time", header: "Time", sortValue: (p) => p.time, render: (p) => <span className="whitespace-nowrap text-xs">{formatDate(p.time)}</span> },
    ...specs.map((spec) => ({
      key: spec.key,
      header: `${spec.label} (avg / peak)`,
      align: "right" as const,
      sortValue: (p: MetricsPoint) => (p[spec.key] as number | undefined) ?? -1,
      render: (p: MetricsPoint) => (
        <span className="text-xs">
          {p[spec.key] ?? "—"}
          {p[`${spec.key}_max` as keyof MetricsPoint] != null && <span className="text-slate-400"> / {p[`${spec.key}_max` as keyof MetricsPoint]}</span>}
        </span>
      ),
    })),
  ];

  return (
    <DetailCard
      title="Utilization"
      subtitle={data ? `Azure Monitor · ${data.interval.replace("PT", "").toLowerCase()} intervals${isFetching ? " · refreshing…" : ""}` : "Azure Monitor platform metrics"}
      actions={
        <div className="flex items-center gap-2">
          <div className="inline-flex rounded-lg border border-att-200 bg-white p-0.5" role="radiogroup" aria-label="Time range">
            {RANGES.map((range) => (
              <button
                key={range.hours}
                type="button"
                role="radio"
                aria-checked={hours === range.hours}
                onClick={() => setHours(range.hours)}
                className={`rounded-md px-2.5 py-1 text-xs font-semibold ${hours === range.hours ? "bg-att-600 text-white" : "text-slate-600 hover:bg-att-50"}`}
              >
                {range.label}
              </button>
            ))}
          </div>
          <button type="button" onClick={() => setShowTable((v) => !v)} className={`${button} ${tone.neutral} text-xs`}>
            {showTable ? "Charts" : "Table"}
          </button>
        </div>
      }
    >
      {isLoading ? (
        <div className="flex items-center gap-2 py-10 text-sm text-slate-500">
          <Spinner /> Reading metrics…
        </div>
      ) : isError ? (
        <p className="text-sm text-red-700">{apiErrorMessage(error, "Could not read metrics")}</p>
      ) : (
        <>
          <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
            {specs.map((spec) => {
              const summary = data?.summary?.[spec.key];
              return (
                <div key={spec.key} className="rounded-xl border border-att-100 bg-att-50/40 px-3 py-2">
                  <p className="flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-slate-500">
                    <span className="h-2 w-2 rounded-full" style={{ background: METRIC_COLORS[spec.key] }} aria-hidden="true" />
                    {spec.label}
                  </p>
                  <div className="mt-1 flex items-baseline gap-3 text-sm text-slate-700">
                    <span>
                      now <span className="text-base font-bold text-slate-900">{summary?.latest ?? "—"}{summary?.latest != null ? spec.unit : ""}</span>
                    </span>
                    <span>avg {summary?.average ?? "—"}{summary?.average != null ? spec.unit : ""}</span>
                    <span>peak {summary?.peak ?? "—"}{summary?.peak != null ? spec.unit : ""}</span>
                  </div>
                </div>
              );
            })}
          </div>
          {showTable ? (
            <DetailGrid
              title="Readings"
              rows={points}
              columns={tableColumns}
              rowKey={(p) => p.time}
              searchText={(p) => p.time}
              searchPlaceholder="Filter by time…"
              initialSort={{ key: "time", direction: "desc" }}
              emptyText="No readings in this range."
            />
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              {specs.map((spec) => (
                <MetricChart key={spec.key} spec={spec} points={points} hours={hours} formatDate={formatDate} />
              ))}
            </div>
          )}
        </>
      )}
    </DetailCard>
  );
}

// ── Disks ─────────────────────────────────────────────────────────────

interface DiskRow {
  role: "OS" | "Data";
  lun: number | null;
  name: string;
  sizeGb: number | null;
  sku: string | null;
  caching: string | null;
  iops: number | null;
  mbps: number | null;
  encryption: string | null;
  disk?: ManagedDisk & Record<string, unknown>;
}

/** Every disk of a VM, one per row — joined with the disk inventory for SKU, IOPS and throughput. */
export function VMDisksGrid({ vm, disks, onOpenDisk }: { vm: VMInfo & Record<string, unknown>; disks: (ManagedDisk & Record<string, unknown>)[]; onOpenDisk: (disk: ManagedDisk) => void }) {
  const rows = useMemo<DiskRow[]>(() => {
    const attached = disks.filter((d) => String(d.managed_by || "").toLowerCase() === vm.id.toLowerCase());
    const byName = new Map(attached.map((d) => [d.name.toLowerCase(), d]));
    const result: DiskRow[] = [];
    const osName = (vm.os_disk_name as string | null) || attached.find((d) => d.os_type)?.name || null;
    if (osName) {
      const disk = byName.get(osName.toLowerCase());
      result.push({
        role: "OS",
        lun: null,
        name: osName,
        sizeGb: (vm.os_disk_size_gb as number | null) ?? disk?.size_gb ?? null,
        sku: disk?.sku ?? ((vm.os_disk_type as string | null) || null),
        caching: null,
        iops: (disk?.disk_iops_read_write as number | null) ?? null,
        mbps: (disk?.disk_mbps_read_write as number | null) ?? null,
        encryption: (disk?.encryption_type as string | null) ?? null,
        disk,
      });
    }
    const dataDisks = (vm.data_disks as { name: string; size_gb: number | null; lun: number; caching?: string | null; storage_account_type?: string | null }[] | undefined) ?? [];
    const seen = new Set(result.map((r) => r.name.toLowerCase()));
    for (const d of [...dataDisks].sort((a, b) => a.lun - b.lun)) {
      const disk = byName.get(d.name.toLowerCase());
      seen.add(d.name.toLowerCase());
      result.push({
        role: "Data",
        lun: d.lun,
        name: d.name,
        sizeGb: d.size_gb ?? disk?.size_gb ?? null,
        sku: disk?.sku ?? d.storage_account_type ?? null,
        caching: d.caching ?? null,
        iops: (disk?.disk_iops_read_write as number | null) ?? null,
        mbps: (disk?.disk_mbps_read_write as number | null) ?? null,
        encryption: (disk?.encryption_type as string | null) ?? null,
        disk,
      });
    }
    // Attached disks the VM record did not list (older sync data).
    for (const disk of attached.filter((d) => !seen.has(d.name.toLowerCase()))) {
      result.push({
        role: disk.os_type ? "OS" : "Data",
        lun: null,
        name: disk.name,
        sizeGb: disk.size_gb ?? null,
        sku: disk.sku ?? null,
        caching: null,
        iops: (disk.disk_iops_read_write as number | null) ?? null,
        mbps: (disk.disk_mbps_read_write as number | null) ?? null,
        encryption: (disk.encryption_type as string | null) ?? null,
        disk,
      });
    }
    return result;
  }, [vm, disks]);

  const total = rows.reduce((sum, r) => sum + (r.sizeGb || 0), 0);
  const columns: GridColumn<DiskRow>[] = [
    {
      key: "role",
      header: "Role",
      sortValue: (r) => (r.role === "OS" ? -1 : r.lun ?? 999),
      render: (r) => (
        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${r.role === "OS" ? "bg-att-50 text-att-800 ring-1 ring-att-200" : "bg-slate-100 text-slate-700"}`}>
          {r.role === "OS" ? "OS disk" : `Data · LUN ${r.lun ?? "?"}`}
        </span>
      ),
    },
    {
      key: "name",
      header: "Disk",
      sortValue: (r) => r.name,
      render: (r) =>
        r.disk ? (
          <button type="button" onClick={() => onOpenDisk(r.disk as ManagedDisk)} className="text-left font-mono text-xs font-medium text-att-700 hover:underline">
            {r.name}
          </button>
        ) : (
          <span className="font-mono text-xs">{r.name}</span>
        ),
    },
    { key: "size", header: "Size", align: "right", sortValue: (r) => r.sizeGb ?? 0, render: (r) => <span className="whitespace-nowrap text-xs font-semibold">{r.sizeGb != null ? `${r.sizeGb.toLocaleString()} GB` : "—"}</span> },
    { key: "sku", header: "Type", sortValue: (r) => r.sku ?? "", render: (r) => <span className="text-xs">{r.sku ?? "—"}</span> },
    { key: "caching", header: "Caching", sortValue: (r) => r.caching ?? "", render: (r) => <span className="text-xs">{r.caching ?? (r.role === "OS" ? "—" : "None")}</span> },
    { key: "perf", header: "IOPS / MBps", align: "right", sortValue: (r) => r.iops ?? 0, render: (r) => <span className="whitespace-nowrap text-xs">{r.iops ?? "—"} / {r.mbps ?? "—"}</span> },
    { key: "encryption", header: "Encryption", sortValue: (r) => r.encryption ?? "", render: (r) => <span className="text-xs">{(r.encryption || "—").replace("EncryptionAtRestWith", "")}</span> },
  ];
  return (
    <DetailGrid
      title={`Disks · ${total.toLocaleString()} GB total`}
      rows={rows}
      columns={columns}
      rowKey={(r) => `${r.role}-${r.lun ?? ""}-${r.name}`}
      searchText={(r) => `${r.name} ${r.sku ?? ""} ${r.role}`}
      searchPlaceholder="Search disks…"
      initialSort={{ key: "role", direction: "asc" }}
      emptyText="No disk details synced for this VM — run Sync from Azure."
      onRowClick={(r) => r.disk && onOpenDisk(r.disk)}
    />
  );
}

// ── Run Command ───────────────────────────────────────────────────────

const LINUX_TEMPLATES = [
  { label: "Uptime & load", script: "uptime" },
  { label: "Disk usage", script: "df -hT -x tmpfs -x devtmpfs" },
  { label: "Memory", script: "free -m" },
  { label: "Top CPU processes", script: "ps aux --sort=-%cpu | head -15" },
  { label: "Top memory processes", script: "ps aux --sort=-%mem | head -15" },
  { label: "Failed services", script: "systemctl --failed --no-pager" },
  { label: "Recent system log", script: "journalctl -n 100 --no-pager" },
  { label: "Listening ports", script: "ss -tulpn" },
  { label: "OS & kernel", script: "cat /etc/os-release; uname -a" },
];
const WINDOWS_TEMPLATES = [
  { label: "Uptime", script: "(Get-Date) - (Get-CimInstance Win32_OperatingSystem).LastBootUpTime" },
  { label: "Disk usage", script: "Get-Volume | Format-Table -AutoSize" },
  { label: "Top processes", script: "Get-Process | Sort-Object CPU -Descending | Select-Object -First 15" },
  { label: "Stopped auto services", script: "Get-Service | Where-Object { $_.StartType -eq 'Automatic' -and $_.Status -ne 'Running' }" },
  { label: "OS info", script: "Get-ComputerInfo -Property OsName,OsVersion,CsName" },
];
const TIMEOUTS = [
  { seconds: 60, label: "1 min" },
  { seconds: 300, label: "5 min" },
  { seconds: 900, label: "15 min" },
  { seconds: 1800, label: "30 min" },
];

const stateStyles: Record<string, string> = {
  Pending: "bg-slate-100 text-slate-700",
  Running: "bg-blue-50 text-blue-700",
  Succeeded: "bg-green-50 text-green-700",
  Failed: "bg-red-50 text-red-700",
  TimedOut: "bg-red-50 text-red-700",
  Canceled: "bg-slate-100 text-slate-700",
};

function Console({ output, error }: { output: string | null | undefined; error: string | null | undefined }) {
  return (
    <div className="space-y-2">
      <pre className="max-h-96 min-h-[6rem] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-slate-900 px-4 py-3 font-mono text-xs leading-relaxed text-slate-100">
        {output || <span className="text-slate-500">(no output)</span>}
      </pre>
      {error && (
        <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg border border-red-200 bg-red-50 px-4 py-3 font-mono text-xs text-red-800">{error}</pre>
      )}
    </div>
  );
}

export function RunCommandPanel({
  vm,
  tier,
  formatDate,
}: {
  vm: VMInfo;
  tier: "prod" | "nonprod" | null | undefined;
  formatDate: (value: string) => string;
}) {
  const target: VMTarget = { subscription_id: vm.subscription_id || "", resource_group: vm.resource_group || "", vm_name: vm.name };
  const windows = (vm.os_type || "").toLowerCase().includes("windows");
  const templates = windows ? WINDOWS_TEMPLATES : LINUX_TEMPLATES;
  const isProd = tier !== "nonprod";
  const [script, setScript] = useState("");
  const [timeout, setTimeoutSeconds] = useState(300);
  const [confirmName, setConfirmName] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [viewing, setViewing] = useState<RunHistoryItem | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const start = useStartRunCommand();
  const status = useRunCommandStatus(target, runId);
  const history = useRunCommandHistory(target, true);
  const running = !!runId && !(status.data && TERMINAL_RUN_STATES.includes(status.data.state));
  const confirmed = !isProd || confirmName.trim().toLowerCase() === vm.name.toLowerCase();
  const canRun = vm.power_state === "running" && !!script.trim() && confirmed && !start.isPending && !running;

  const run = () => {
    setStartError(null);
    setViewing(null);
    start.mutate(
      { ...target, script, timeout_seconds: timeout, confirm_name: isProd ? confirmName.trim() : undefined },
      { onSuccess: (data) => setRunId(data.run_id), onError: (e) => setStartError(apiErrorMessage(e, "Could not start the command")) },
    );
  };

  const historyColumns: GridColumn<RunHistoryItem>[] = [
    { key: "when", header: "Requested", sortValue: (h) => h.requested_at ?? "", render: (h) => <span className="whitespace-nowrap text-xs">{h.requested_at ? formatDate(h.requested_at) : "—"}</span> },
    { key: "who", header: "By", sortValue: (h) => h.requested_by, render: (h) => <span className="text-xs">{h.requested_by}</span> },
    { key: "script", header: "Command", render: (h) => <span className="block max-w-md truncate font-mono text-xs" title={h.script ?? ""}>{h.script}</span> },
    {
      key: "state",
      header: "Result",
      sortValue: (h) => h.state ?? h.status,
      render: (h) => (
        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${stateStyles[h.state ?? ""] ?? (h.status === "blocked" ? "bg-amber-50 text-amber-800" : "bg-slate-100 text-slate-700")}`}>
          {h.status === "blocked" ? "Refused" : h.state ?? h.status}
          {h.exit_code != null && h.exit_code !== 0 ? ` (exit ${h.exit_code})` : ""}
        </span>
      ),
    },
  ];

  const shown = viewing
    ? { state: viewing.state, exit_code: viewing.exit_code, output: viewing.output, error: viewing.error, script: viewing.script }
    : status.data;

  return (
    <div className="space-y-5">
      <DetailCard
        title={`Run a ${windows ? "PowerShell" : "shell"} command`}
        subtitle={`Azure Run Command · runs as ${windows ? "SYSTEM" : "root"} · output keeps the last 4 KB · every run is audited`}
      >
        {vm.power_state !== "running" && (
          <p className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">This VM is {vm.power_state || "not running"} — start it to run commands.</p>
        )}
        <div className="mb-2 flex flex-wrap gap-1.5">
          {templates.map((template) => (
            <button
              key={template.label}
              type="button"
              onClick={() => setScript(template.script)}
              className="rounded-full border border-att-200 bg-white px-2.5 py-1 text-xs font-medium text-slate-700 hover:bg-att-50"
            >
              {template.label}
            </button>
          ))}
        </div>
        <label className="sr-only" htmlFor="run-command-script">Command</label>
        <textarea
          id="run-command-script"
          value={script}
          onChange={(e) => setScript(e.target.value)}
          rows={6}
          spellCheck={false}
          maxLength={16000}
          placeholder={windows ? "Get-Service | Where-Object Status -eq 'Stopped'" : "#!/bin/bash\nsystemctl status nginx --no-pager"}
          className="w-full resize-y rounded-lg border border-slate-700 bg-slate-900 px-4 py-3 font-mono text-xs leading-relaxed text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-2 focus:ring-att-300"
        />
        <div className="mt-3 flex flex-wrap items-end justify-between gap-3">
          <div className="flex flex-wrap items-end gap-3">
            <label className="text-xs font-semibold uppercase tracking-wide text-slate-600">
              Timeout
              <select value={timeout} onChange={(e) => setTimeoutSeconds(Number(e.target.value))} className={`${inputClass} mt-1 block`}>
                {TIMEOUTS.map((t) => (
                  <option key={t.seconds} value={t.seconds}>
                    {t.label}
                  </option>
                ))}
              </select>
            </label>
            {isProd && (
              <label className="text-xs font-semibold uppercase tracking-wide text-red-700">
                Production — type the VM name to confirm
                <input value={confirmName} onChange={(e) => setConfirmName(e.target.value)} placeholder={vm.name} className={`${inputClass} mt-1 block w-80 font-mono`} />
              </label>
            )}
          </div>
          <button type="button" onClick={run} disabled={!canRun} className={`${button} ${tone.primary}`}>
            {start.isPending || running ? <Spinner className="h-4 w-4 text-white" /> : InfraIcons.play}
            {running ? "Running…" : "Run command"}
          </button>
        </div>
        {startError && <p className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">{startError}</p>}
      </DetailCard>

      {shown && (
        <DetailCard
          title={viewing ? "Earlier run" : "Result"}
          subtitle={shown.script ? <span className="font-mono">{shown.script.split("\n")[0].slice(0, 120)}</span> : undefined}
          actions={
            <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${stateStyles[shown.state ?? ""] ?? "bg-slate-100 text-slate-700"}`}>
              {shown.state ?? "—"}
              {shown.exit_code != null ? ` · exit ${shown.exit_code}` : ""}
            </span>
          }
        >
          {!viewing && running && (
            <p className="mb-2 flex items-center gap-2 text-xs text-slate-500">
              <Spinner /> Waiting for the VM agent… the first run on a VM can take a minute while Azure installs the Run Command extension.
            </p>
          )}
          <Console output={shown.output} error={shown.error} />
        </DetailCard>
      )}

      <DetailGrid
        title="Recent runs on this VM"
        rows={history.data ?? []}
        columns={historyColumns}
        rowKey={(h) => String(h.id)}
        searchText={(h) => `${h.script ?? ""} ${h.requested_by} ${h.state ?? ""}`}
        searchPlaceholder="Search command, user…"
        emptyText={history.isLoading ? "Loading…" : "No commands have been run on this VM from the portal."}
        initialSort={{ key: "when", direction: "desc" }}
        onRowClick={(h) => setViewing(h)}
      />
    </div>
  );
}

// ── Tags ──────────────────────────────────────────────────────────────

export function TagEditor({
  resourceId,
  resourceType,
  tags,
  canEdit,
  onToast,
}: {
  resourceId: string;
  resourceType: AdminResourceType;
  tags: Record<string, string>;
  canEdit: boolean;
  onToast: Toast;
}) {
  const initial = useMemo(() => Object.entries(tags ?? {}).sort(([a], [b]) => a.localeCompare(b)), [tags]);
  const [rows, setRows] = useState<[string, string][]>(initial);
  const [editing, setEditing] = useState(false);
  const [filter, setFilter] = useState("");
  const save = useReplaceTags();
  const keys = rows.map(([k]) => k.trim().toLowerCase());
  const duplicate = keys.find((k, i) => k && keys.indexOf(k) !== i);
  const invalid = rows.find(([k]) => !k.trim() || /[<>%&\\?/]/.test(k));
  const visible = rows.map((row, index) => ({ row, index })).filter(({ row }) => !filter || `${row[0]} ${row[1]}`.toLowerCase().includes(filter.toLowerCase()));

  const submit = () =>
    save.mutate(
      { resource_id: resourceId, resource_type: resourceType, tags: Object.fromEntries(rows.map(([k, v]) => [k.trim(), v.trim()])) },
      {
        onSuccess: () => {
          onToast("Tags saved");
          setEditing(false);
        },
        onError: (e) => onToast(apiErrorMessage(e, "Failed to save tags"), "error"),
      },
    );

  return (
    <DetailCard
      title={`Tags (${rows.length})`}
      subtitle={editing ? "Changes replace the resource's tags in Azure when you save." : undefined}
      actions={
        <div className="flex items-center gap-2">
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter tags…" className={`${inputClass} w-48 py-1.5`} />
          {canEdit && !editing && (
            <button type="button" className={`${button} ${tone.neutral}`} onClick={() => setEditing(true)}>
              {InfraIcons.edit} Edit tags
            </button>
          )}
          {editing && (
            <>
              <button type="button" className={`${button} ${tone.neutral}`} onClick={() => { setRows(initial); setEditing(false); }}>
                Cancel
              </button>
              <button type="button" className={`${button} ${tone.primary}`} disabled={!!duplicate || !!invalid || save.isPending} onClick={submit}>
                {save.isPending && <Spinner className="h-4 w-4 text-white" />} Save tags
              </button>
            </>
          )}
        </div>
      }
    >
      {(duplicate || (editing && invalid)) && (
        <p className="mb-3 text-xs font-medium text-red-600">{duplicate ? `Tag "${duplicate}" appears twice.` : "Tag names cannot be empty or contain < > % & \\ ? /"}</p>
      )}
      <div className="overflow-hidden rounded-lg border border-att-100">
        <table className="w-full text-sm">
          <thead className="bg-att-50/80 text-left text-xs font-semibold uppercase tracking-[0.12em] text-att-700">
            <tr>
              <th className="px-3 py-2">Name</th>
              <th className="px-3 py-2">Value</th>
              {editing && <th className="w-12 px-3 py-2" />}
            </tr>
          </thead>
          <tbody>
            {visible.map(({ row: [key, value], index }) => (
              <tr key={index} className="border-t border-att-100">
                <td className="px-3 py-1.5 align-top">
                  {editing ? (
                    <input value={key} onChange={(e) => setRows((prev) => prev.map((r, i) => (i === index ? [e.target.value, r[1]] : r)))} className={`${inputClass} w-full py-1 font-mono text-xs`} />
                  ) : (
                    <span className="font-mono text-xs font-semibold text-slate-800">{key}</span>
                  )}
                </td>
                <td className="px-3 py-1.5 align-top">
                  {editing ? (
                    <input value={value} onChange={(e) => setRows((prev) => prev.map((r, i) => (i === index ? [r[0], e.target.value] : r)))} className={`${inputClass} w-full py-1 text-xs`} />
                  ) : (
                    <span className="break-all text-xs text-slate-700">{value || <span className="text-slate-400">(empty)</span>}</span>
                  )}
                </td>
                {editing && (
                  <td className="px-3 py-1.5 text-center">
                    <button type="button" aria-label={`Remove tag ${key}`} onClick={() => setRows((prev) => prev.filter((_, i) => i !== index))} className="rounded p-1 text-red-600 hover:bg-red-50 [&>svg]:h-4 [&>svg]:w-4">
                      {InfraIcons.trash}
                    </button>
                  </td>
                )}
              </tr>
            ))}
            {!visible.length && (
              <tr>
                <td colSpan={3} className="px-3 py-6 text-center text-sm text-slate-400">
                  {rows.length ? "No tags match." : "No tags."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {editing && (
        <button type="button" onClick={() => setRows((prev) => [...prev, ["", ""]])} className="mt-3 text-sm font-semibold text-att-700 hover:underline">
          + Add tag
        </button>
      )}
    </DetailCard>
  );
}

// ── VM administration ─────────────────────────────────────────────────

function AdminAction({ title, description, children }: { title: string; description: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-att-100 py-3 first:border-t-0 first:pt-0">
      <div className="min-w-[16rem] flex-1">
        <p className="text-sm font-semibold text-slate-800">{title}</p>
        <p className="text-xs text-slate-500">{description}</p>
      </div>
      <div className="flex flex-wrap items-center gap-2">{children}</div>
    </div>
  );
}

export function VMAdminPanel({
  vm,
  canAdmin,
  canPower,
  powerPending,
  onPower,
  onConfirm,
  onToast,
}: {
  vm: VMInfo;
  canAdmin: boolean;
  canPower: boolean;
  powerPending: boolean;
  onPower: (action: "start" | "stop" | "restart") => void;
  onConfirm: (request: ConfirmRequest) => void;
  onToast: Toast;
}) {
  const target: VMTarget = { subscription_id: vm.subscription_id || "", resource_group: vm.resource_group || "", vm_name: vm.name };
  const [showSizes, setShowSizes] = useState(false);
  const [size, setSize] = useState("");
  const [sizeFilter, setSizeFilter] = useState("");
  const [showLog, setShowLog] = useState(false);
  const sizes = useAvailableSizes(target, showSizes);
  const resize = useResizeVM();
  const redeploy = useRedeployVM();
  const boot = useBootDiagnostics(target, showLog);
  const running = vm.power_state === "running";
  const stopped = vm.power_state === "deallocated" || vm.power_state === "stopped";
  const filteredSizes = (sizes.data ?? []).filter((s) => !sizeFilter || s.name.toLowerCase().includes(sizeFilter.toLowerCase()));
  const chosen = sizes.data?.find((s) => s.name === size);

  return (
    <div className="space-y-5">
      <DetailCard title="Administration" subtitle="Changes run against Azure directly and are recorded in the audit log.">
        <AdminAction title="Power" description="Start, stop (deallocate — compute billing stops) or restart. Stop and restart ask for confirmation.">
          {!canPower && <span className="text-xs text-slate-400">Needs the VM power permission</span>}
          {canPower && powerPending && <Spinner />}
          {canPower && stopped && (
            <button type="button" className={`${button} ${tone.neutral}`} disabled={powerPending} onClick={() => onPower("start")}>
              {InfraIcons.play} Start
            </button>
          )}
          {canPower && running && (
            <>
              <button type="button" className={`${button} ${tone.amber}`} disabled={powerPending} onClick={() => onPower("restart")}>
                {InfraIcons.restart} Restart
              </button>
              <button type="button" className={`${button} ${tone.red}`} disabled={powerPending} onClick={() => onPower("stop")}>
                {InfraIcons.stop} Stop (deallocate)
              </button>
            </>
          )}
        </AdminAction>

        <AdminAction title="Resize" description={`Currently ${vm.vm_size || "unknown"}. Resizing restarts the VM; only sizes available on its host cluster are listed.`}>
          {canAdmin ? (
            <button type="button" className={`${button} ${tone.neutral}`} onClick={() => setShowSizes((v) => !v)}>
              {InfraIcons.server} {showSizes ? "Hide sizes" : "Choose size"}
            </button>
          ) : (
            <span className="text-xs text-slate-400">Needs the resource admin permission</span>
          )}
        </AdminAction>
        {showSizes && (
          <div className="mb-3 rounded-xl border border-att-100 bg-att-50/40 p-3">
            {sizes.isLoading ? (
              <p className="flex items-center gap-2 text-sm text-slate-500"><Spinner /> Loading sizes…</p>
            ) : sizes.isError ? (
              <p className="text-sm text-red-700">{apiErrorMessage(sizes.error, "Could not list sizes")}</p>
            ) : (
              <div className="flex flex-wrap items-end gap-3">
                <input value={sizeFilter} onChange={(e) => setSizeFilter(e.target.value)} placeholder="Filter, e.g. D8 or E16" className={`${inputClass} w-56`} />
                <select value={size} onChange={(e) => setSize(e.target.value)} className={`${inputClass} w-80`} aria-label="New size">
                  <option value="">Select a size ({filteredSizes.length})</option>
                  {filteredSizes.map((s) => (
                    <option key={s.name} value={s.name} disabled={s.name === vm.vm_size}>
                      {s.name} — {s.cores} vCPU · {s.memory_gb} GB{s.name === vm.vm_size ? " (current)" : ""}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className={`${button} ${tone.primary}`}
                  disabled={!size || resize.isPending}
                  onClick={() =>
                    onConfirm({
                      title: `Resize ${vm.name}?`,
                      message: `${vm.name} will change from ${vm.vm_size} to ${chosen?.name} (${chosen?.cores} vCPU, ${chosen?.memory_gb} GB) and restart. Running workloads are interrupted.`,
                      confirmLabel: "Resize",
                      onConfirm: () =>
                        resize.mutate(
                          { ...target, size },
                          {
                            onSuccess: () => onToast(`Resize of ${vm.name} to ${size} started — the VM restarts in a few minutes`),
                            onError: (e) => onToast(apiErrorMessage(e, "Resize failed"), "error"),
                          },
                        ),
                    })
                  }
                >
                  {resize.isPending && <Spinner className="h-4 w-4 text-white" />} Resize
                </button>
              </div>
            )}
          </div>
        )}

        <AdminAction title="Redeploy" description="Moves the VM to a new Azure host — the fix for host-level faults. The VM restarts and the temporary disk is wiped.">
          {canAdmin ? (
            <button
              type="button"
              className={`${button} ${tone.amber}`}
              disabled={redeploy.isPending}
              onClick={() =>
                onConfirm({
                  title: `Redeploy ${vm.name}?`,
                  message: `${vm.name} moves to a new host and restarts. Data on the temporary (resource) disk is lost.`,
                  confirmLabel: "Redeploy",
                  onConfirm: () =>
                    redeploy.mutate(target, {
                      onSuccess: () => onToast(`Redeploy of ${vm.name} started`),
                      onError: (e) => onToast(apiErrorMessage(e, "Redeploy failed"), "error"),
                    }),
                })
              }
            >
              {InfraIcons.restart} Redeploy
            </button>
          ) : (
            <span className="text-xs text-slate-400">Needs the resource admin permission</span>
          )}
        </AdminAction>

        <AdminAction title="Boot diagnostics" description="The serial console log — what the VM printed while booting. Useful when a VM does not come back after a restart.">
          <button type="button" className={`${button} ${tone.neutral}`} onClick={() => setShowLog((v) => !v)}>
            {InfraIcons.eye} {showLog ? "Hide log" : "View serial log"}
          </button>
        </AdminAction>
        {showLog && (
          <div className="mb-3">
            {boot.isLoading ? (
              <p className="flex items-center gap-2 text-sm text-slate-500"><Spinner /> Fetching the serial log…</p>
            ) : boot.isError ? (
              <p className="text-sm text-red-700">{apiErrorMessage(boot.error, "Boot diagnostics are not available")}</p>
            ) : boot.data?.available ? (
              <>
                {boot.data.truncated && <p className="mb-1 text-xs text-slate-500">Showing the last 250 KB.</p>}
                <Console output={boot.data.log} error={null} />
              </>
            ) : (
              <p className="text-sm text-slate-500">Boot diagnostics are not enabled on this VM.</p>
            )}
          </div>
        )}

        <AdminAction title="Azure portal" description="Open the VM in the Azure portal for anything not offered here.">
          <a href={azurePortalUrl(vm.id)} target="_blank" rel="noreferrer" className={`${button} ${tone.neutral}`}>
            {InfraIcons.globe} Open in Azure
          </a>
        </AdminAction>
      </DetailCard>
    </div>
  );
}

// ── PG Flexible Server ────────────────────────────────────────────────

const SYSTEM_DATABASES = new Set(["azure_sys", "azure_maintenance"]);

function StorageTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-att-100 bg-white px-3 py-2">
      <p className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-0.5 text-base font-bold text-slate-900">{value}</p>
      {hint && <p className="text-[11px] text-slate-500">{hint}</p>}
    </div>
  );
}

function growthText(db: PGDatabase): { text: string; tone: string } {
  if (db.size_bytes == null) return { text: "—", tone: "text-slate-400" };
  if (db.size_7d_ago_bytes == null) return { text: "new", tone: "text-slate-500" };
  const delta = db.size_bytes - db.size_7d_ago_bytes;
  if (Math.abs(delta) < 1024 * 1024) return { text: "no change", tone: "text-slate-500" };
  const pct = db.size_7d_ago_bytes ? (delta / db.size_7d_ago_bytes) * 100 : 0;
  return {
    text: `${delta > 0 ? "+" : "−"}${formatBytes(Math.abs(delta))} (${delta > 0 ? "+" : "−"}${Math.abs(pct).toFixed(1)}%)`,
    tone: delta > 0 ? "font-semibold text-slate-800" : "text-green-700",
  };
}

export function PGDatabasesPanel({ server, formatDate }: { server: PGFlexServer; formatDate: (value: string) => string }) {
  const overview = usePGOverview(server.subscription_id, server.resource_group, server.name, true);
  if (overview.isLoading) {
    return (
      <p className="flex items-center gap-2 py-10 text-sm text-slate-500">
        <Spinner /> Reading databases, sizes and firewall rules…
      </p>
    );
  }
  if (overview.isError) return <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{apiErrorMessage(overview.error, "Could not read the server")}</p>;
  type Rule = PGOverview["firewall_rules"][number];
  const data = overview.data;
  const databases = data?.databases ?? [];
  const storage = data?.storage;
  const total = storage?.databases_total_bytes ?? databases.reduce((sum, d) => sum + (d.size_bytes || 0), 0);
  const sizedAt = databases.map((d) => d.size_at).filter(Boolean).sort().pop();
  const provisionedBytes = storage?.provisioned_gb ? storage.provisioned_gb * 1024 ** 3 : null;
  const percent = storage?.percent ?? (storage?.used_bytes != null && provisionedBytes ? (storage.used_bytes / provisionedBytes) * 100 : null);
  const allowsAzure = (data?.firewall_rules ?? []).some((r) => r.start_ip === "0.0.0.0" && r.end_ip === "0.0.0.0");
  const openToAll = (data?.firewall_rules ?? []).some((r) => r.start_ip === "0.0.0.0" && r.end_ip === "255.255.255.255");

  const columns: GridColumn<PGDatabase>[] = [
    {
      key: "name",
      header: "Database",
      sortValue: (d) => d.name,
      render: (d) => (
        <span className="flex items-center gap-2">
          <span className="font-mono text-xs font-semibold">{d.name}</span>
          {SYSTEM_DATABASES.has(d.name) && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-500">Azure system</span>}
          {d.name === "postgres" && <span className="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-500">Default</span>}
        </span>
      ),
    },
    {
      key: "size",
      header: "Size",
      align: "right",
      sortValue: (d) => d.size_bytes ?? -1,
      render: (d) => <span className="whitespace-nowrap text-xs font-semibold text-slate-900" title={d.size_bytes != null ? `${d.size_bytes.toLocaleString()} bytes` : "Not reported yet"}>{formatBytes(d.size_bytes)}</span>,
    },
    {
      key: "share",
      header: "Share of databases",
      sortValue: (d) => d.size_bytes ?? -1,
      render: (d) => {
        if (d.size_bytes == null || !total) return <span className="text-xs text-slate-400">—</span>;
        const share = (d.size_bytes / total) * 100;
        return (
          <div className="flex w-40 items-center gap-2">
            <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full" style={{ width: `${Math.max(1, share)}%`, background: METRIC_COLORS.storage }} />
            </div>
            <span className="w-10 text-right text-xs text-slate-600">{share < 1 ? "<1" : share.toFixed(0)}%</span>
          </div>
        );
      },
    },
    {
      key: "growth",
      header: "7-day change",
      align: "right",
      sortValue: (d) => (d.size_bytes != null && d.size_7d_ago_bytes != null ? d.size_bytes - d.size_7d_ago_bytes : -Infinity),
      render: (d) => {
        const growth = growthText(d);
        return (
          <span className={`whitespace-nowrap text-xs ${growth.tone}`} title={d.size_7d_ago_at ? `Compared with ${formatDate(d.size_7d_ago_at)}` : undefined}>
            {growth.text}
          </span>
        );
      },
    },
    { key: "encoding", header: "Encoding", sortValue: (d) => `${d.charset ?? ""} ${d.collation ?? ""}`, render: (d) => <span className="text-xs text-slate-600">{[d.charset, d.collation].filter(Boolean).join(" · ") || "—"}</span> },
  ];

  return (
    <div className="space-y-5">
      <DetailCard
        title="Storage"
        subtitle={storage?.used_bytes != null ? "Server storage from Azure Monitor. Used includes data, transaction logs (WAL), temporary files and server logs." : "Storage metrics are not available for this server."}
      >
        {percent != null && (
          <div className="mb-3">
            <div className="mb-1 flex items-baseline justify-between text-sm">
              <span className="font-semibold text-slate-800">
                {formatBytes(storage?.used_bytes)} used{storage?.provisioned_gb ? ` of ${storage.provisioned_gb} GB provisioned` : ""}
              </span>
              <span className={`font-semibold ${percent >= 90 ? "text-red-600" : percent >= 80 ? "text-amber-700" : "text-slate-700"}`}>{percent.toFixed(1)}%</span>
            </div>
            <div className="h-2.5 overflow-hidden rounded-full bg-slate-100">
              <div className="h-full rounded-full" style={{ width: `${Math.min(100, percent)}%`, background: percent >= 90 ? CRITICAL_COLOR : percent >= 80 ? WARNING_COLOR : METRIC_COLORS.storage }} />
            </div>
          </div>
        )}
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <StorageTile label="Databases total" value={formatBytes(total || null)} hint={`${databases.length} databases`} />
          <StorageTile label="Free" value={formatBytes(storage?.free_bytes)} hint="before storage auto-grow or a resize is needed" />
          <StorageTile label="Transaction logs" value={formatBytes(storage?.txlogs_bytes)} hint="WAL kept on the server" />
          <StorageTile label="Backups" value={formatBytes(storage?.backup_bytes)} hint="billed separately, not in provisioned storage" />
        </div>
      </DetailCard>

      {data?.size_error && (
        <p className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">Database sizes could not be read from Azure Monitor: {data.size_error}</p>
      )}
      <DetailGrid<PGDatabase>
        title={`Databases${total ? ` · ${formatBytes(total)}` : ""}${sizedAt ? ` · sizes as of ${formatDate(sizedAt)}` : ""}`}
        rows={databases}
        columns={columns}
        rowKey={(d) => d.name}
        searchText={(d) => d.name}
        searchPlaceholder="Search databases…"
        initialSort={{ key: "size", direction: "desc" }}
        emptyText="No databases."
      />
      {openToAll && (
        <p className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">A firewall rule allows every IPv4 address (0.0.0.0 – 255.255.255.255).</p>
      )}
      <DetailGrid<Rule>
        title={`Firewall rules${allowsAzure ? " · allows Azure services" : ""}`}
        rows={data?.firewall_rules ?? []}
        columns={[
          { key: "name", header: "Rule", sortValue: (r) => r.name, render: (r) => <span className="font-mono text-xs">{r.name}</span> },
          { key: "start", header: "Start IP", sortValue: (r) => r.start_ip, render: (r) => <span className="font-mono text-xs">{r.start_ip}</span> },
          { key: "end", header: "End IP", sortValue: (r) => r.end_ip, render: (r) => <span className="font-mono text-xs">{r.end_ip}</span> },
        ]}
        rowKey={(r) => r.name}
        searchText={(r) => `${r.name} ${r.start_ip} ${r.end_ip}`}
        searchPlaceholder="Search rules, IPs…"
        initialSort={{ key: "name", direction: "asc" }}
        emptyText="No firewall rules — the server is reachable only through private networking (or not at all)."
      />
    </div>
  );
}

export function PGAdminPanel({
  server,
  canPower,
  powerPending,
  onPower,
}: {
  server: PGFlexServer;
  canPower: boolean;
  powerPending: boolean;
  onPower: (action: "start" | "stop" | "restart") => void;
}) {
  return (
    <DetailCard title="Administration" subtitle="Changes run against Azure directly and are recorded in the audit log.">
      <AdminAction title="Power" description="Start, stop or restart the server. A stopped server restarts by itself after 7 days (Azure limit).">
        {!canPower && <span className="text-xs text-slate-400">Needs the PG power permission</span>}
        {canPower && powerPending && <Spinner />}
        {canPower && server.state === "Stopped" && (
          <button type="button" className={`${button} ${tone.neutral}`} disabled={powerPending} onClick={() => onPower("start")}>
            {InfraIcons.play} Start
          </button>
        )}
        {canPower && server.state === "Ready" && (
          <>
            <button type="button" className={`${button} ${tone.amber}`} disabled={powerPending} onClick={() => onPower("restart")}>
              {InfraIcons.restart} Restart
            </button>
            <button type="button" className={`${button} ${tone.red}`} disabled={powerPending} onClick={() => onPower("stop")}>
              {InfraIcons.stop} Stop
            </button>
          </>
        )}
      </AdminAction>
      <AdminAction title="Azure portal" description="Scaling, parameters, backups and networking are managed in the Azure portal.">
        <a href={azurePortalUrl(server.id)} target="_blank" rel="noreferrer" className={`${button} ${tone.neutral}`}>
          {InfraIcons.globe} Open in Azure
        </a>
      </AdminAction>
    </DetailCard>
  );
}

// ── Disks ─────────────────────────────────────────────────────────────

export function DiskAdminPanel({
  disk,
  canAdmin,
  canDelete,
  onDelete,
  onConfirm,
  onToast,
}: {
  disk: ManagedDisk & Record<string, unknown>;
  canAdmin: boolean;
  canDelete: boolean;
  onDelete: () => void;
  onConfirm: (request: ConfirmRequest) => void;
  onToast: Toast;
}) {
  const snapshot = useSnapshotDisk();
  const expand = useExpandDisk();
  const current = Number(disk.size_gb || 0);
  const [newSize, setNewSize] = useState(current ? current * 2 : 128);
  const target = { subscription_id: disk.subscription_id, resource_group: disk.resource_group, disk_name: disk.name };
  return (
    <DetailCard title="Administration" subtitle="Changes run against Azure directly and are recorded in the audit log.">
      <AdminAction title="Snapshot" description="An incremental snapshot in the disk's resource group — take one before risky changes. Tagged created-by=opsportal.">
        {canAdmin ? (
          <button
            type="button"
            className={`${button} ${tone.neutral}`}
            disabled={snapshot.isPending}
            onClick={() =>
              onConfirm({
                title: `Snapshot ${disk.name}?`,
                message: `An incremental snapshot of "${disk.name}" is created in ${disk.resource_group}. Snapshots are billed for the data they hold.`,
                confirmLabel: "Create snapshot",
                onConfirm: () =>
                  snapshot.mutate(target, {
                    onSuccess: (result) => onToast(`Snapshot ${String(result.snapshot_name ?? "")} is being created`),
                    onError: (e) => onToast(apiErrorMessage(e, "Snapshot failed"), "error"),
                  }),
              })
            }
          >
            {snapshot.isPending ? <Spinner /> : InfraIcons.disk} Create snapshot
          </button>
        ) : (
          <span className="text-xs text-slate-400">Needs the resource admin permission</span>
        )}
      </AdminAction>
      <AdminAction title="Expand" description={`Currently ${current || "?"} GB. Disks can only grow — the file system must then be extended inside the VM.`}>
        {canAdmin ? (
          <>
            <input type="number" min={current + 1} max={65536} value={newSize} onChange={(e) => setNewSize(Number(e.target.value))} className={`${inputClass} w-28`} aria-label="New size in GB" />
            <span className="text-xs text-slate-500">GB</span>
            <button
              type="button"
              className={`${button} ${tone.neutral}`}
              disabled={expand.isPending || !(newSize > current)}
              onClick={() =>
                onConfirm({
                  title: `Grow ${disk.name} to ${newSize} GB?`,
                  message: `"${disk.name}" grows from ${current} GB to ${newSize} GB. This cannot be undone — Azure disks cannot shrink. Some disk types must be detached or the VM deallocated first; Azure will say so if needed.`,
                  confirmLabel: "Expand",
                  onConfirm: () =>
                    expand.mutate(
                      { ...target, size_gb: newSize },
                      {
                        onSuccess: () => onToast(`${disk.name} is now ${newSize} GB`),
                        onError: (e) => onToast(apiErrorMessage(e, "Expand failed"), "error"),
                      },
                    ),
                })
              }
            >
              {expand.isPending && <Spinner />} Expand
            </button>
          </>
        ) : (
          <span className="text-xs text-slate-400">Needs the resource admin permission</span>
        )}
      </AdminAction>
      {disk.disk_state === "Unattached" && (
        <AdminAction title="Delete" description="Unattached disks are still billed. Deleting is permanent.">
          {canDelete ? (
            <button type="button" className={`${button} ${tone.red}`} onClick={onDelete}>
              {InfraIcons.trash} Delete disk
            </button>
          ) : (
            <span className="text-xs text-slate-400">Needs the resource cleanup permission</span>
          )}
        </AdminAction>
      )}
      <AdminAction title="Azure portal" description="Open the disk in the Azure portal.">
        <a href={azurePortalUrl(disk.id)} target="_blank" rel="noreferrer" className={`${button} ${tone.neutral}`}>
          {InfraIcons.globe} Open in Azure
        </a>
      </AdminAction>
    </DetailCard>
  );
}

export function PortalLinkCard({ resourceId, label }: { resourceId: string; label: string }) {
  return (
    <DetailCard title="Administration">
      <PropertyList
        items={[
          {
            label: "Azure portal",
            value: (
              <a href={azurePortalUrl(resourceId)} target="_blank" rel="noreferrer" className="font-semibold text-att-700 hover:underline">
                Open {label} in Azure ↗
              </a>
            ),
          },
        ]}
      />
    </DetailCard>
  );
}
