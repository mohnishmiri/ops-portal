/**
 * Node Pools tab — each AKS agent pool with its Azure configuration and the
 * live state of its nodes.
 *
 * Azure supplies the configuration and node count; the Kubernetes API supplies
 * node readiness and running pods. When the cluster's API server can't be
 * reached the backend marks node details unavailable, and the grid shows "—"
 * rather than zero. Like the other AKS tabs, the grid reads the DB inventory
 * and a background job refreshes it.
 */

import React, { useCallback, useMemo, useState } from "react";
import { gridStyles, SortableHeader, nextSortState } from "../../components/gridStyles";
import { MetricCard, MetricCardIcons } from "../../components/MetricCard";
import {
  AKSCluster,
  NodeDetail,
  NodePoolDetails,
  useAksBackgroundSync,
  useCachedNodePools,
  useScaleNodePool,
  useUpdateAutoscaling,
} from "../../services/aksApi";
import { parseApiDate } from "../../utils/dateFormat";
import {
  CachedSyncStatus,
  GridPager,
  GridSearchBar,
  GridStateRow,
  SyncFromKubernetesButton,
  TileFilterNotice,
  useGridSort,
  useSearchPagination,
} from "./aksGridShared";
import { DetailGrid, GridFilterSelect, type GridColumn } from "./DetailGrid";
import { apiErrorDetail, DetailIcons, formatAge, iconProps, KeyValueGrid, ReadyBadge, Truncate } from "./detailShared";
import { ModalShell } from "./K8sResourceModals";
import { DetailCard, KpiRow, PropertyList, ResourceDetailShell, ResourceKindIcons } from "./ResourceDetailShell";

type Tile = "all" | "with-nodes" | "autoscaling" | "attention";
type ModeFilter = "all" | "System" | "User";
type NodeFilter = "all" | "not-ready" | "cordoned" | "pressure";
type DetailSection = "overview" | "nodes" | "labels";

/** A sync older than this means the automatic refresh isn't completing. */
const STALE_AFTER_MS = 10 * 60_000;
const MAX_NODES_PER_POOL = 1000;

// ── Formatting ────────────────────────────────────────────────────────

/** "AKSUbuntu-2204gen2containerd-202602.13.0" → version "202602.13.0", released 13 Feb 2026. */
export function nodeImageVersion(full: string | null | undefined): { version: string; released: Date | null } {
  if (!full) return { version: "—", released: null };
  const match = /(\d{4})(\d{2})\.(\d{2})\.\d+$/.exec(full);
  if (!match) return { version: full, released: null };
  const released = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return { version: match[0], released: Number.isNaN(released.getTime()) ? null : released };
}

/** Kubernetes CPU quantity ("31580m", "32") in cores; NaN when unparseable. */
function cpuCores(value: string | null | undefined): number {
  if (!value) return NaN;
  return value.endsWith("m") ? Number(value.slice(0, -1)) / 1000 : Number(value);
}

/** "31580m" → "31.6 cores". */
export function formatCpu(value: string | null | undefined): string {
  const cores = cpuCores(value);
  if (Number.isNaN(cores)) return value || "—";
  return `${Number.isInteger(cores) ? cores : cores.toFixed(1)} cores`;
}

const MEMORY_UNITS: Record<string, number> = { Ki: 2 ** 10, Mi: 2 ** 20, Gi: 2 ** 30, Ti: 2 ** 40, K: 1e3, M: 1e6, G: 1e9, T: 1e12 };

/** Kubernetes memory quantity ("123456Ki") in bytes; NaN when unparseable. */
function memoryBytes(value: string | null | undefined): number {
  const match = value ? /^(\d+(?:\.\d+)?)([KMGT]i?)?$/.exec(value) : null;
  if (!match) return NaN;
  return Number(match[1]) * (match[2] ? MEMORY_UNITS[match[2]] ?? 1 : 1);
}

/** "123456Ki" → "0.1 GiB". */
export function formatMemory(value: string | null | undefined): string {
  const bytes = memoryBytes(value);
  return Number.isNaN(bytes) ? value || "—" : `${(bytes / 2 ** 30).toFixed(1)} GiB`;
}

function formatDuration(ms: number): string {
  const minutes = Math.round(ms / 60_000);
  if (minutes < 60) return `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  if (hours < 48) return `${hours} h ${minutes % 60} min`;
  return `${Math.floor(hours / 24)} days`;
}

const hasNodeDetails = (p: NodePoolDetails) => p.node_details_available !== false;
const isSystem = (p: NodePoolDetails) => p.mode === "System";
const atAutoscaleMax = (p: NodePoolDetails) => p.enable_auto_scaling && !!p.max_count && p.count >= p.max_count;
const registeredNodes = (p: NodePoolDetails) => p.nodes?.length ?? 0;
const notReadyNodes = (p: NodePoolDetails) =>
  hasNodeDetails(p) && p.ready_nodes != null ? Math.max(0, registeredNodes(p) - p.ready_nodes) : 0;

/** What an operator should look at for this pool; empty when it's healthy. */
export function poolIssues(p: NodePoolDetails): string[] {
  const issues: string[] = [];
  if (p.provisioning_state && p.provisioning_state !== "Succeeded") {
    issues.push(p.provisioning_state === "Failed" ? "Provisioning failed" : `${p.provisioning_state} in progress`);
  }
  if (p.power_state && p.power_state !== "Running") issues.push(`Power state ${p.power_state}`);
  const notReady = notReadyNodes(p);
  if (notReady) issues.push(`${notReady} node${notReady === 1 ? "" : "s"} not ready`);
  if (p.cordoned_nodes) issues.push(`${p.cordoned_nodes} cordoned`);
  if ((p.nodes ?? []).some((n) => n.pressure?.length)) issues.push("Node resource pressure");
  if (atAutoscaleMax(p)) issues.push("At autoscaling maximum");
  return issues;
}

// ── Cells ─────────────────────────────────────────────────────────────

const ActionIcons = {
  view: DetailIcons.view,
  scale: <svg {...iconProps}><polyline points="15 3 21 3 21 9" /><polyline points="9 21 3 21 3 15" /><line x1="21" y1="3" x2="14" y2="10" /><line x1="3" y1="21" x2="10" y2="14" /></svg>,
  autoscale: <svg {...iconProps}><line x1="4" y1="21" x2="4" y2="14" /><line x1="4" y1="10" x2="4" y2="3" /><line x1="12" y1="21" x2="12" y2="12" /><line x1="12" y1="8" x2="12" y2="3" /><line x1="20" y1="21" x2="20" y2="16" /><line x1="20" y1="12" x2="20" y2="3" /><line x1="1" y1="14" x2="7" y2="14" /><line x1="9" y1="8" x2="15" y2="8" /><line x1="17" y1="16" x2="23" y2="16" /></svg>,
};

const iconBtn = "rounded p-1.5 disabled:cursor-not-allowed disabled:opacity-40";

function ModeBadge({ pool }: { pool: NodePoolDetails }) {
  return (
    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${isSystem(pool) ? "bg-purple-100 text-purple-800" : "bg-blue-100 text-blue-800"}`}>
      {pool.mode}
    </span>
  );
}

function PoolState({ pool }: { pool: NodePoolDetails }) {
  const running = pool.power_state === "Running";
  const prov = pool.provisioning_state;
  return (
    <div className="flex flex-col items-start gap-1">
      <span className={`inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium ${running ? "text-green-700" : "text-slate-500"}`}>
        <span className={`h-2 w-2 rounded-full ${running ? "bg-green-500" : "bg-slate-400"}`} />
        {pool.power_state || "Unknown"}
      </span>
      {prov && prov !== "Succeeded" && (
        <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-[11px] font-semibold ${prov === "Failed" ? "bg-red-100 text-red-700" : "bg-amber-100 text-amber-800"}`}>
          {prov}
        </span>
      )}
    </div>
  );
}

/** Fill for a usage bar: red when nearly full, amber when getting there. */
const usageColor = (pct: number) => (pct >= 90 ? "bg-red-500" : pct >= 75 ? "bg-amber-500" : "bg-att-500");

function UsageBar({ pct, color = usageColor(pct) }: { pct: number; color?: string }) {
  return (
    <div className="mt-1 h-1.5 w-full rounded-full bg-slate-100" aria-hidden>
      <div className={`h-1.5 rounded-full ${color}`} style={{ width: `${Math.min(100, Math.max(0, pct))}%` }} />
    </div>
  );
}

function NodesCell({ pool }: { pool: NodePoolDetails }) {
  const notReady = notReadyNodes(pool);
  const underPressure = (pool.nodes ?? []).filter((n) => n.pressure?.length).length;
  return (
    <div className="min-w-[5rem]">
      <div className="text-sm font-semibold text-slate-800">{pool.count}</div>
      {hasNodeDetails(pool) && pool.ready_nodes != null && registeredNodes(pool) > 0 && (
        <div className={`whitespace-nowrap text-[11px] font-medium ${notReady ? "text-amber-700" : "text-green-700"}`}>
          {notReady ? `${notReady} not ready` : "All ready"}
        </div>
      )}
      {!!pool.cordoned_nodes && <div className="whitespace-nowrap text-[11px] font-medium text-amber-700">{pool.cordoned_nodes} cordoned</div>}
      {!!underPressure && <div className="whitespace-nowrap text-[11px] font-medium text-red-700">{underPressure} under pressure</div>}
    </div>
  );
}

function PodsCell({ pool }: { pool: NodePoolDetails }) {
  if (!hasNodeDetails(pool) || pool.total_pods == null) {
    return (
      <span className="text-xs text-slate-400" title={pool.node_details_error ?? "Pod counts are unavailable"}>
        —
      </span>
    );
  }
  const capacity = pool.pod_capacity ?? 0;
  return (
    <div className="min-w-[6.5rem]">
      <div className="whitespace-nowrap text-sm font-semibold text-slate-800">
        {pool.total_pods.toLocaleString()}
        {capacity > 0 && <span className="ml-1 text-xs font-normal text-slate-500">/ {capacity.toLocaleString()}</span>}
      </div>
      {capacity > 0 && <UsageBar pct={(pool.total_pods / capacity) * 100} />}
    </div>
  );
}

function AutoscaleCell({ pool }: { pool: NodePoolDetails }) {
  if (!pool.enable_auto_scaling) return <span className="text-xs text-slate-500">Manual</span>;
  const min = pool.min_count ?? 0;
  const max = pool.max_count ?? 0;
  const pct = max > min ? ((pool.count - min) / (max - min)) * 100 : 100;
  return (
    <div className="min-w-[7rem]" title={`${pool.count} nodes; autoscaler range ${min}–${max}`}>
      <div className="flex items-center gap-2 whitespace-nowrap text-xs">
        <span className="font-medium text-slate-700">{min}–{max}</span>
        {atAutoscaleMax(pool) && <span className="rounded bg-red-100 px-1.5 text-[10px] font-semibold text-red-700">At max</span>}
      </div>
      {/* Red only at the maximum, where the autoscaler can't add nodes. */}
      <UsageBar pct={pct} color={atAutoscaleMax(pool) ? "bg-red-500" : pct >= 75 ? "bg-amber-500" : "bg-purple-500"} />
    </div>
  );
}

function NodeImageCell({ value }: { value: string | null | undefined }) {
  const { version, released } = nodeImageVersion(value);
  return (
    <div title={value ?? undefined}>
      <div className="whitespace-nowrap font-mono text-xs text-slate-700">{version}</div>
      {released && (
        <div className="whitespace-nowrap text-[11px] text-slate-500">
          {released.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}
        </div>
      )}
    </div>
  );
}

// ── Tab ───────────────────────────────────────────────────────────────

export const NodePoolsTab: React.FC<{
  cluster: AKSCluster;
  showToast: (msg: string, type?: "success" | "error") => void;
  formatDate: (value: string) => string;
  canManage: boolean;
}> = ({ cluster, showToast, formatDate, canManage }) => {
  const [tile, setTile] = useState<Tile>("all");
  const [mode, setMode] = useState<ModeFilter>("all");
  const [selected, setSelected] = useState<string | null>(null);
  const [scalePool, setScalePool] = useState<NodePoolDetails | null>(null);
  const [autoscalePool, setAutoscalePool] = useState<NodePoolDetails | null>(null);

  const { data, isFetching, isPlaceholderData, isError, error } = useCachedNodePools(cluster.id);
  // Pool configuration comes from Azure and changes slowly; once a minute is
  // plenty and keeps Azure management calls down. "Sync from Azure" is immediate.
  const sync = useAksBackgroundSync({ resourceType: "nodepools", clusterId: cluster.id, throttleMs: 60_000 });
  const scaleMut = useScaleNodePool();
  const autoscaleMut = useUpdateAutoscaling();
  const isLoading = isFetching && isPlaceholderData;

  const pools = useMemo(() => data?.node_pools ?? [], [data]);
  const selectedPool = selected ? pools.find((p) => p.name === selected) : undefined;

  const kpis = useMemo(() => {
    const withDetails = pools.filter(hasNodeDetails);
    return {
      system: pools.filter(isSystem).length,
      nodes: pools.reduce((n, p) => n + p.count, 0),
      pods: withDetails.reduce((n, p) => n + (p.total_pods ?? 0), 0),
      notReady: pools.reduce((n, p) => n + notReadyNodes(p), 0),
      nodeDetails: withDetails.length > 0,
      autoscaling: pools.filter((p) => p.enable_auto_scaling).length,
      atMax: pools.filter(atAutoscaleMax).length,
      attention: pools.filter((p) => poolIssues(p).length > 0).length,
    };
  }, [pools]);
  const k8sError = pools.find((p) => !hasNodeDetails(p))?.node_details_error;

  const filtered = useMemo(
    () =>
      pools.filter(
        (p) =>
          (mode === "all" || p.mode === mode) &&
          (tile === "with-nodes" ? p.count > 0
            : tile === "autoscaling" ? p.enable_auto_scaling
            : tile === "attention" ? poolIssues(p).length > 0
            : true)
      ),
    [pools, mode, tile]
  );
  const accessor = useCallback((p: NodePoolDetails, key: string): string | number => {
    switch (key) {
      case "vm_size": return p.vm_size.toLowerCase();
      case "count": return p.count;
      case "autoscaling": return p.enable_auto_scaling ? p.max_count ?? 0 : -1;
      case "pods": return p.total_pods ?? -1;
      case "kubernetes": return p.kubernetes_version ?? "";
      case "image": return p.node_image_version ?? "";
      case "zones": return p.availability_zones.join(",");
      case "state": return poolIssues(p).length ? 0 : 1;
      default: return p.name.toLowerCase();
    }
  }, []);
  const { sort, setSort, sorted } = useGridSort(filtered, accessor, { key: "name", direction: "asc" });
  const searchFn = useCallback(
    (p: NodePoolDetails, q: string) =>
      [p.name, p.vm_size, p.mode, p.kubernetes_version, p.node_image_version ?? "", ...Object.entries(p.node_labels ?? {}).map(([k, v]) => `${k}=${v}`)]
        .join(" ")
        .toLowerCase()
        .includes(q),
    []
  );
  const { search, setSearch, page, setPage, paged, filtered: searched, totalPages } = useSearchPagination(sorted, searchFn);

  const applyTile = (next: Tile) => {
    setTile((prev) => (prev === next ? "all" : next));
    setPage(1);
  };
  const tileLabel =
    tile === "with-nodes" ? "Pools with nodes" : tile === "autoscaling" ? "Autoscaling pools" : tile === "attention" ? "Pools that need attention" : null;

  const lastSyncAt = parseApiDate(data?.last_sync)?.getTime();
  const staleFor = lastSyncAt ? Date.now() - lastSyncAt : 0;

  const header = (label: string, key: string, align?: "center") => (
    <SortableHeader label={label} active={sort.key === key} direction={sort.direction} onClick={() => setSort(nextSortState(sort, key))} align={align} />
  );

  const submitScale = (pool: NodePoolDetails, nodeCount: number) =>
    scaleMut.mutate(
      { clusterId: cluster.id, nodepoolName: pool.name, nodeCount },
      {
        onSuccess: () => {
          showToast(`Scaling ${pool.name} to ${nodeCount} nodes. Azure applies this in the background and it can take a few minutes.`);
          setScalePool(null);
          sync.start(false);
        },
        onError: (e) => showToast(apiErrorDetail(e, `Failed to scale ${pool.name}`), "error"),
      }
    );

  const submitAutoscale = (pool: NodePoolDetails, enable: boolean, minCount: number, maxCount: number) =>
    autoscaleMut.mutate(
      {
        clusterId: cluster.id,
        nodepoolName: pool.name,
        enableAutoScaling: enable,
        minCount: enable ? minCount : undefined,
        maxCount: enable ? maxCount : undefined,
      },
      {
        onSuccess: () => {
          showToast(
            enable
              ? `Autoscaling ${pool.name} between ${minCount} and ${maxCount} nodes. Azure is applying the change.`
              : `Autoscaling turned off for ${pool.name}; it keeps its current nodes.`
          );
          setAutoscalePool(null);
          sync.start(false);
        },
        onError: (e) => showToast(apiErrorDetail(e, `Failed to update autoscaling for ${pool.name}`), "error"),
      }
    );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-gray-800">Node Pools</h2>
          <p className="text-sm text-gray-500">{cluster.name} · Azure agent pools with live node and pod state</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <GridFilterSelect<ModeFilter>
            label="Filter by pool mode"
            value={mode}
            onChange={(v) => {
              setMode(v);
              setPage(1);
            }}
            options={[
              { value: "all", label: "All modes" },
              { value: "System", label: `System (${kpis.system})` },
              { value: "User", label: `User (${pools.length - kpis.system})` },
            ]}
          />
          <SyncFromKubernetesButton sync={sync} label="Sync from Azure" title="Read the node pools from Azure and the cluster now" />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <CachedSyncStatus source={data?.last_sync ? data.source : undefined} lastSync={data?.last_sync} sync={sync} formatDate={formatDate} />
        {staleFor > STALE_AFTER_MS && (
          <span className="text-sm text-amber-700">
            This data is {formatDuration(staleFor)} old: no sync has completed since then.{" "}
            {sync.isRunning ? "A sync is running now." : "Use Sync from Azure to retry."}
          </span>
        )}
      </div>

      {pools.length > 0 && !kpis.nodeDetails && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          Node health and pod counts are unavailable: {k8sError ?? "the cluster's Kubernetes API couldn't be read at the last sync."} Node counts,
          versions, and configuration come from Azure and are current.
        </div>
      )}

      {isError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {apiErrorDetail(error, "Unable to load node pools.")}
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard title="Node Pools" value={pools.length} subtitle={`${kpis.system} System · ${pools.length - kpis.system} User`} icon={MetricCardIcons.layers()} tone="att"
          onClick={() => { setTile("all"); setMode("all"); setPage(1); }} actionLabel="Show all node pools" />
        <MetricCard
          title="Nodes"
          value={kpis.nodes}
          subtitle={kpis.nodeDetails ? `${kpis.pods.toLocaleString()} pods · ${kpis.notReady ? `${kpis.notReady} not ready` : "all ready"}` : "Node health unavailable"}
          icon={MetricCardIcons.server()}
          tone={!kpis.nodeDetails ? "slate" : kpis.notReady ? "amber" : "green"}
          onClick={() => applyTile("with-nodes")}
          active={tile === "with-nodes"}
          actionLabel="Show node pools that have nodes"
        />
        <MetricCard
          title="Autoscaling"
          value={kpis.autoscaling}
          subtitle={
            kpis.atMax ? `${kpis.atMax} at maximum` : kpis.autoscaling === pools.length ? "All pools autoscale" : `${pools.length - kpis.autoscaling} manually sized`
          }
          icon={MetricCardIcons.activity()}
          tone={kpis.atMax ? "red" : "purple"}
          onClick={() => applyTile("autoscaling")}
          active={tile === "autoscaling"}
          actionLabel="Show autoscaling node pools"
        />
        <MetricCard
          title="Needs Attention"
          value={kpis.attention}
          subtitle={kpis.attention ? "Provisioning, node health, or capacity" : kpis.nodeDetails ? "All pools healthy" : "Node health unknown"}
          icon={MetricCardIcons.alert()}
          tone={kpis.attention ? "red" : kpis.nodeDetails ? "green" : "slate"}
          onClick={() => applyTile("attention")}
          active={tile === "attention"}
          actionLabel="Show node pools that need attention"
        />
      </div>
      <TileFilterNotice label={tileLabel} onClear={() => applyTile("all")} />

      <div className={gridStyles.shell}>
        <GridSearchBar
          search={search}
          onSearch={setSearch}
          onPage={setPage}
          totalItems={pools.length}
          shownItems={searched.length}
          placeholder="Search pool, VM size, version, label..."
          isSyncing={sync.isRunning}
        />
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}>{header("Name", "name")}</th>
                <th className={gridStyles.headerCell}>{header("VM Size", "vm_size")}</th>
                <th className={gridStyles.headerCell}>{header("Nodes", "count")}</th>
                <th className={gridStyles.headerCell}>{header("Autoscaling", "autoscaling")}</th>
                <th className={gridStyles.headerCell}>{header("Pods / Capacity", "pods")}</th>
                <th className={gridStyles.headerCell}>{header("Kubernetes", "kubernetes")}</th>
                <th className={gridStyles.headerCell}>{header("Node Image", "image")}</th>
                <th className={gridStyles.headerCell}>{header("Zones", "zones")}</th>
                <th className={gridStyles.headerCell}>{header("State", "state")}</th>
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {paged.length === 0 && (
                <GridStateRow
                  colSpan={10}
                  isLoading={isLoading}
                  emptyText={
                    !data?.last_sync ? "Not synced yet. Reading the node pools from Azure..." : pools.length === 0 ? "This cluster has no node pools." : "No node pools match the current filters"
                  }
                />
              )}
              {paged.map((pool) => {
                const labels = Object.entries(pool.node_labels ?? {});
                const issues = poolIssues(pool);
                return (
                  <tr key={pool.name} className={gridStyles.row}>
                    <td className={gridStyles.cell}>
                      <div className="flex items-center gap-2">
                        <button type="button" onClick={() => setSelected(pool.name)} className="whitespace-nowrap text-left font-semibold text-att-700 hover:text-att-900 hover:underline">
                          {pool.name}
                        </button>
                        <ModeBadge pool={pool} />
                        {pool.scale_set_priority === "Spot" && <span className="rounded-full bg-orange-100 px-2 py-0.5 text-[11px] font-semibold text-orange-800">Spot</span>}
                      </div>
                      {labels.length > 0 && (
                        <div className="mt-0.5 whitespace-nowrap text-[11px] text-slate-500" title={labels.map(([k, v]) => `${k}=${v}`).join("\n")}>
                          {labels[0][0]}={labels[0][1]}
                          {labels.length > 1 && <span className="text-slate-400"> +{labels.length - 1}</span>}
                        </div>
                      )}
                    </td>
                    <td className={gridStyles.cell}><span className="whitespace-nowrap font-mono text-xs text-slate-700">{pool.vm_size}</span></td>
                    <td className={gridStyles.cell}><NodesCell pool={pool} /></td>
                    <td className={gridStyles.cell}><AutoscaleCell pool={pool} /></td>
                    <td className={gridStyles.cell}><PodsCell pool={pool} /></td>
                    <td className={gridStyles.cell}><span className="whitespace-nowrap font-mono text-xs text-slate-700">{pool.kubernetes_version || "—"}</span></td>
                    <td className={gridStyles.cell}><NodeImageCell value={pool.node_image_version} /></td>
                    <td className={gridStyles.cell}><span className="whitespace-nowrap text-xs text-slate-600">{pool.availability_zones.length ? pool.availability_zones.join(", ") : "—"}</span></td>
                    <td className={gridStyles.cell}>
                      <div title={issues.join("\n") || undefined}><PoolState pool={pool} /></div>
                    </td>
                    <td className={gridStyles.centerCell}>
                      <div className="flex items-center justify-center gap-1">
                        <button type="button" title="View details" onClick={() => setSelected(pool.name)} className={`${iconBtn} text-blue-600 hover:bg-blue-50`}>
                          {ActionIcons.view}
                        </button>
                        {canManage && (
                          <>
                            <button
                              type="button"
                              title={pool.enable_auto_scaling ? "Autoscaling manages this pool's size. Change the range or turn autoscaling off first." : "Scale node pool"}
                              aria-label="Scale node pool"
                              disabled={pool.enable_auto_scaling}
                              onClick={() => setScalePool(pool)}
                              className={`${iconBtn} text-att-600 hover:bg-att-50`}
                            >
                              {ActionIcons.scale}
                            </button>
                            <button type="button" title="Configure autoscaling" onClick={() => setAutoscalePool(pool)} className={`${iconBtn} text-purple-600 hover:bg-purple-50`}>
                              {ActionIcons.autoscale}
                            </button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <GridPager page={page} totalPages={totalPages} onPage={setPage} />
      </div>

      {selected && (
        <NodePoolDetailModal
          pool={selectedPool}
          name={selected}
          clusterName={cluster.name}
          lastSync={data?.last_sync ?? null}
          formatDate={formatDate}
          isLoading={isLoading}
          onClose={() => setSelected(null)}
        />
      )}
      {scalePool && (
        <ScaleNodePoolDialog pool={scalePool} busy={scaleMut.isPending} onClose={() => setScalePool(null)} onSubmit={(n) => submitScale(scalePool, n)} />
      )}
      {autoscalePool && (
        <AutoscaleDialog
          pool={autoscalePool}
          busy={autoscaleMut.isPending}
          onClose={() => setAutoscalePool(null)}
          onSubmit={(enable, min, max) => submitAutoscale(autoscalePool, enable, min, max)}
        />
      )}
    </div>
  );
};

// ── Detail ────────────────────────────────────────────────────────────

function parseTaint(taint: string): { key: string; value: string; effect: string } {
  const [kv, effect = ""] = taint.split(":");
  const [key, value = ""] = kv.split("=");
  return { key, value, effect };
}

function NodesGrid({ pool, filter, onFilterChange }: { pool: NodePoolDetails; filter: NodeFilter; onFilterChange: (f: NodeFilter) => void }) {
  const nodes = pool.nodes ?? [];
  const matches = (n: NodeDetail, f: NodeFilter) =>
    f === "not-ready" ? n.ready === false : f === "cordoned" ? !!n.unschedulable : f === "pressure" ? !!n.pressure?.length : true;
  const count = (f: NodeFilter) => nodes.filter((n) => matches(n, f)).length;
  const columns: GridColumn<NodeDetail>[] = [
    { key: "name", header: "Node", sortValue: (n) => n.name, render: (n) => <Truncate value={n.name} className="font-mono text-xs" maxWidth="max-w-[22rem]" /> },
    {
      key: "status",
      header: "Status",
      sortValue: (n) => (n.ready === false ? 0 : 1),
      render: (n) => (
        <div className="flex flex-wrap items-center gap-1.5">
          {n.ready === undefined ? <span className="text-xs text-slate-400">—</span> : <ReadyBadge ready={n.ready} />}
          {n.unschedulable && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-[11px] font-semibold text-amber-800">Cordoned</span>}
          {n.pressure?.map((p) => (
            <span key={p} className="rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-semibold text-red-700">{p}</span>
          ))}
        </div>
      ),
    },
    { key: "zone", header: "Zone", sortValue: (n) => n.zone ?? "", render: (n) => <span className="whitespace-nowrap text-xs text-slate-600">{n.zone ?? "—"}</span> },
    {
      key: "pods",
      header: "Pods",
      sortValue: (n) => n.pod_count,
      render: (n) => {
        const max = Number(n.allocatable_pods) || 0;
        return (
          <div className="min-w-[5.5rem]">
            <span className="whitespace-nowrap text-sm font-semibold text-slate-800">
              {n.pod_count}
              {max > 0 && <span className="ml-1 text-xs font-normal text-slate-500">/ {max}</span>}
            </span>
            {max > 0 && <UsageBar pct={(n.pod_count / max) * 100} />}
          </div>
        );
      },
    },
    { key: "cpu", header: "Allocatable CPU", sortValue: (n) => cpuCores(n.allocatable_cpu) || 0, render: (n) => <span className="whitespace-nowrap text-xs text-slate-700">{formatCpu(n.allocatable_cpu)}</span> },
    { key: "memory", header: "Allocatable Memory", sortValue: (n) => memoryBytes(n.allocatable_memory) || 0, render: (n) => <span className="whitespace-nowrap text-xs text-slate-700">{formatMemory(n.allocatable_memory)}</span> },
    { key: "kubelet", header: "Kubelet", sortValue: (n) => n.kubelet_version ?? "", render: (n) => <span className="whitespace-nowrap font-mono text-xs text-slate-600">{n.kubelet_version ?? "—"}</span> },
    { key: "age", header: "Age", sortValue: (n) => n.created_at ?? "", render: (n) => <span className="whitespace-nowrap text-xs text-slate-600">{formatAge(n.created_at)}</span> },
  ];
  return (
    <DetailGrid
      title="Nodes"
      rows={nodes.filter((n) => matches(n, filter))}
      columns={columns}
      rowKey={(n) => n.name}
      toolbar={
        <GridFilterSelect<NodeFilter>
          label="Filter nodes"
          value={filter}
          onChange={onFilterChange}
          options={[
            { value: "all", label: `All nodes (${nodes.length})` },
            { value: "not-ready", label: `Not ready (${count("not-ready")})` },
            { value: "cordoned", label: `Cordoned (${count("cordoned")})` },
            { value: "pressure", label: `Under pressure (${count("pressure")})` },
          ]}
        />
      }
      searchText={(n) => `${n.name} ${n.zone ?? ""} ${n.kubelet_version ?? ""}`}
      searchPlaceholder="Search node, zone, version…"
      emptyText={filter === "all" ? "No nodes are registered for this pool." : "No nodes match this filter."}
      initialSort={{ key: "name", direction: "asc" }}
      defaultPageSize={25}
    />
  );
}

export function NodePoolDetailModal({
  pool,
  name,
  clusterName,
  lastSync,
  formatDate,
  isLoading,
  onClose,
}: {
  pool: NodePoolDetails | undefined;
  name: string;
  clusterName: string;
  lastSync: string | null;
  formatDate: (value: string) => string;
  isLoading: boolean;
  onClose: () => void;
}) {
  const [section, setSection] = useState<DetailSection>("overview");
  const [nodeFilter, setNodeFilter] = useState<NodeFilter>("all");
  const showNodes = (filter: NodeFilter) => {
    setNodeFilter(filter);
    setSection("nodes");
  };
  const details = !!pool && hasNodeDetails(pool);
  const notReady = pool ? notReadyNodes(pool) : 0;
  const image = nodeImageVersion(pool?.node_image_version);
  const issues = pool ? poolIssues(pool) : [];

  return (
    <ResourceDetailShell
      kind="Node Pool"
      name={name}
      icon={ResourceKindIcons.nodepool}
      status={pool && <PoolState pool={pool} />}
      meta={
        pool && (
          <>
            <span>Cluster <span className="font-medium text-slate-700">{clusterName}</span></span>
            <span className="font-mono">{pool.vm_size}</span>
            <ModeBadge pool={pool} />
          </>
        )
      }
      tabs={[
        { key: "overview", label: "Overview" },
        { key: "nodes", label: "Nodes", count: pool?.nodes?.length, attention: notReady > 0 },
        { key: "labels", label: "Labels & Taints", count: pool ? Object.keys(pool.node_labels ?? {}).length + pool.node_taints.length : undefined },
      ]}
      activeTab={section}
      onTabChange={setSection}
      isLoading={isLoading && !pool}
      error={!isLoading && !pool ? `Node pool ${name} is no longer in this cluster's inventory.` : null}
      onClose={onClose}
    >
      {pool && section === "overview" && (
        <>
          {issues.length > 0 && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">{issues.join(" · ")}</div>
          )}
          {!details && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
              Node health and pod counts are unavailable: {pool.node_details_error ?? "the Kubernetes API couldn't be read at the last sync."}
            </div>
          )}
          <KpiRow>
            <MetricCard
              title="Nodes"
              value={details && pool.ready_nodes != null ? `${pool.ready_nodes}/${pool.count}` : pool.count}
              subtitle={details ? (notReady ? `${notReady} not ready` : "Ready nodes / total") : "Live count from Azure"}
              icon={MetricCardIcons.server()}
              tone={notReady ? "amber" : "green"}
              onClick={() => showNodes(notReady ? "not-ready" : "all")}
              actionLabel="Show this pool's nodes"
            />
            <MetricCard
              title="Pods"
              value={details && pool.total_pods != null ? pool.total_pods.toLocaleString() : "—"}
              subtitle={details && pool.pod_capacity ? `of ${pool.pod_capacity.toLocaleString()} capacity (${Math.round(((pool.total_pods ?? 0) / pool.pod_capacity) * 100)}%)` : `Max ${pool.max_pods} per node`}
              icon={MetricCardIcons.layers()}
              tone="att"
              onClick={() => showNodes("all")}
              actionLabel="Show pods per node"
            />
            <MetricCard
              title="Autoscaling"
              value={pool.enable_auto_scaling ? `${pool.min_count}–${pool.max_count}` : "Manual"}
              subtitle={atAutoscaleMax(pool) ? "At maximum: can't add nodes" : `${pool.count} nodes now`}
              icon={MetricCardIcons.activity()}
              tone={atAutoscaleMax(pool) ? "red" : "purple"}
              onClick={() => showNodes("all")}
              actionLabel="Show the nodes the autoscaler manages"
            />
            <MetricCard
              title="Kubernetes"
              value={pool.kubernetes_version || "—"}
              subtitle={image.released ? `Node image ${image.released.toLocaleDateString(undefined, { month: "short", year: "numeric" })}` : "Node image unknown"}
              icon={MetricCardIcons.cloud()}
              tone="indigo"
              valueClassName="text-xl"
              onClick={() => showNodes("all")}
              actionLabel="Show kubelet versions per node"
            />
          </KpiRow>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <DetailCard title="Configuration">
              <PropertyList
                items={[
                  { label: "VM Size", value: pool.vm_size, mono: true },
                  { label: "Mode", value: pool.mode },
                  { label: "OS", value: [pool.os_type, pool.os_sku].filter(Boolean).join(" · ") },
                  { label: "OS Disk", value: [pool.os_disk_size_gb ? `${pool.os_disk_size_gb} GB` : null, pool.os_disk_type].filter(Boolean).join(" · ") },
                  { label: "Max Pods per Node", value: pool.max_pods },
                  { label: "Availability Zones", value: pool.availability_zones.length ? pool.availability_zones.join(", ") : "None" },
                  { label: "Priority", value: pool.scale_set_priority },
                  { label: "Scale-down Mode", value: pool.scale_down_mode },
                  { label: "Upgrade Max Surge", value: pool.max_surge },
                ]}
              />
            </DetailCard>
            <DetailCard title="Status & Versions">
              <PropertyList
                items={[
                  { label: "Provisioning State", value: pool.provisioning_state },
                  { label: "Power State", value: pool.power_state },
                  { label: "Kubernetes Version", value: pool.kubernetes_version, mono: true },
                  { label: "Node Image Released", value: image.released?.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) },
                  { label: "Node Image Version", value: pool.node_image_version, mono: true, wide: true },
                  { label: "Last Synced", value: lastSync ? formatDate(lastSync) : null, wide: true },
                ]}
              />
            </DetailCard>
          </div>
        </>
      )}

      {pool && section === "nodes" &&
        (details ? (
          <NodesGrid pool={pool} filter={nodeFilter} onFilterChange={setNodeFilter} />
        ) : (
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            Node details are unavailable: {pool.node_details_error ?? "the Kubernetes API couldn't be read at the last sync."}
          </div>
        ))}

      {pool && section === "labels" && (
        <>
          <KeyValueGrid title="Node Labels" entries={pool.node_labels ?? {}} emptyText="No labels are set on this pool." />
          <DetailGrid
            title="Taints"
            rows={pool.node_taints.map(parseTaint)}
            columns={[
              { key: "key", header: "Key", sortValue: (t) => t.key, render: (t) => <span className="font-mono text-xs text-slate-800">{t.key}</span> },
              { key: "value", header: "Value", sortValue: (t) => t.value, render: (t) => <span className="font-mono text-xs text-slate-700">{t.value || "—"}</span> },
              { key: "effect", header: "Effect", sortValue: (t) => t.effect, render: (t) => <span className="text-xs text-slate-700">{t.effect || "—"}</span> },
            ]}
            rowKey={(t) => `${t.key}=${t.value}:${t.effect}`}
            searchText={(t) => `${t.key} ${t.value} ${t.effect}`}
            searchPlaceholder="Search taints…"
            emptyText="No taints: any pod can be scheduled on this pool."
          />
        </>
      )}
    </ResourceDetailShell>
  );
}

// ── Dialogs ───────────────────────────────────────────────────────────

const inputCls =
  "w-full rounded-lg border border-att-200 px-3 py-2 text-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100";
const btn = {
  primary: "rounded-lg bg-att-500 px-4 py-2 text-sm text-white hover:bg-att-600 disabled:opacity-50",
  secondary: "rounded-lg border border-att-200 px-4 py-2 text-sm text-gray-700 hover:bg-att-50",
};

const minNodes = (pool: NodePoolDetails) => (isSystem(pool) ? 1 : 0);
const wholeNumber = (v: string) => /^\d+$/.test(v.trim());

export function ScaleNodePoolDialog({
  pool,
  busy,
  onClose,
  onSubmit,
}: {
  pool: NodePoolDetails;
  busy: boolean;
  onClose: () => void;
  onSubmit: (nodeCount: number) => void;
}) {
  const [value, setValue] = useState(String(pool.count));
  const n = Number(value);
  const error = !wholeNumber(value)
    ? "Enter a whole number of nodes."
    : n < minNodes(pool)
      ? `${pool.name} is a System pool and needs at least 1 node.`
      : n > MAX_NODES_PER_POOL
        ? `A node pool can have at most ${MAX_NODES_PER_POOL.toLocaleString()} nodes.`
        : n === pool.count
          ? `${pool.name} already has ${n} nodes.`
          : null;
  return (
    <ModalShell title={`Scale ${pool.name}`} onClose={onClose}>
      <div className="space-y-4">
        <p className="text-sm text-gray-600">
          Set a fixed node count for this {pool.mode} pool. It has {pool.count} node{pool.count === 1 ? "" : "s"} ({pool.vm_size}).
        </p>
        <div>
          <label htmlFor="nodepool-scale-count" className="mb-1 block text-sm font-medium text-gray-700">Node count</label>
          <input id="nodepool-scale-count" type="number" min={minNodes(pool)} max={MAX_NODES_PER_POOL} value={value} onChange={(e) => setValue(e.target.value)} className={inputCls} />
          {error ? (
            <p className="mt-1 text-xs text-red-600">{error}</p>
          ) : n < pool.count ? (
            <p className="mt-1 text-xs text-amber-700">
              Removes {pool.count - n} node{pool.count - n === 1 ? "" : "s"}. Their pods are evicted and rescheduled on the remaining nodes.
            </p>
          ) : (
            <p className="mt-1 text-xs text-slate-600">Adds {n - pool.count} {pool.vm_size} node{n - pool.count === 1 ? "" : "s"}.</p>
          )}
        </div>
        <p className="text-xs text-slate-500">Azure applies the change in the background, which can take several minutes. The pool shows as Scaling until it finishes.</p>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className={btn.secondary}>Cancel</button>
          <button type="button" disabled={busy || !!error} onClick={() => onSubmit(n)} className={btn.primary}>
            {busy ? "Scaling..." : "Scale"}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}

export function AutoscaleDialog({
  pool,
  busy,
  onClose,
  onSubmit,
}: {
  pool: NodePoolDetails;
  busy: boolean;
  onClose: () => void;
  onSubmit: (enable: boolean, minCount: number, maxCount: number) => void;
}) {
  const [enable, setEnable] = useState(pool.enable_auto_scaling);
  const [minValue, setMinValue] = useState(String(pool.min_count ?? Math.max(minNodes(pool), Math.min(pool.count, 1))));
  const [maxValue, setMaxValue] = useState(String(pool.max_count ?? Math.max(pool.count * 2, pool.count + 3)));
  const min = Number(minValue);
  const max = Number(maxValue);
  const unchanged = enable === pool.enable_auto_scaling && (!enable || (min === pool.min_count && max === pool.max_count));
  const error = !enable
    ? null
    : !wholeNumber(minValue) || !wholeNumber(maxValue)
      ? "Enter whole numbers for the minimum and maximum."
      : min < minNodes(pool)
        ? `${pool.name} is a System pool; its minimum must be at least 1 node.`
        : max > MAX_NODES_PER_POOL
          ? `A node pool can have at most ${MAX_NODES_PER_POOL.toLocaleString()} nodes.`
          : min > max
            ? "The minimum can't be greater than the maximum."
            : max < 1
              ? "The maximum must be at least 1 node."
              : null;
  const outsideRange = enable && !error && (pool.count < min || pool.count > max);

  return (
    <ModalShell title={`Autoscaling: ${pool.name}`} onClose={onClose}>
      <div className="space-y-4">
        <label className="flex items-center justify-between gap-3 rounded-lg border border-att-100 px-3 py-2">
          <span>
            <span className="block text-sm font-medium text-gray-800">Cluster autoscaler</span>
            <span className="block text-xs text-slate-500">Adds nodes when pods can't be scheduled and removes underused ones.</span>
          </span>
          <input type="checkbox" role="switch" aria-label="Enable autoscaling" checked={enable} onChange={(e) => setEnable(e.target.checked)} className="h-5 w-5 accent-att-500" />
        </label>
        {enable ? (
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label htmlFor="nodepool-min" className="mb-1 block text-sm font-medium text-gray-700">Minimum nodes</label>
              <input id="nodepool-min" type="number" min={minNodes(pool)} max={MAX_NODES_PER_POOL} value={minValue} onChange={(e) => setMinValue(e.target.value)} className={inputCls} />
            </div>
            <div>
              <label htmlFor="nodepool-max" className="mb-1 block text-sm font-medium text-gray-700">Maximum nodes</label>
              <input id="nodepool-max" type="number" min={1} max={MAX_NODES_PER_POOL} value={maxValue} onChange={(e) => setMaxValue(e.target.value)} className={inputCls} />
            </div>
          </div>
        ) : (
          pool.enable_auto_scaling && (
            <p className="text-sm text-gray-600">The pool keeps its current {pool.count} nodes and stops scaling automatically.</p>
          )
        )}
        {error && <p className="text-xs text-red-600">{error}</p>}
        {outsideRange && (
          <p className="text-xs text-amber-700">
            The pool has {pool.count} nodes, outside {min}–{max}. Azure may reject the change.
          </p>
        )}
        <p className="text-xs text-slate-500">Currently {pool.enable_auto_scaling ? `autoscaling ${pool.min_count}–${pool.max_count}` : "manually sized"} with {pool.count} nodes.</p>
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className={btn.secondary}>Cancel</button>
          <button type="button" disabled={busy || !!error || unchanged} onClick={() => onSubmit(enable, min, max)} className={btn.primary}>
            {busy ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}

export default NodePoolsTab;
