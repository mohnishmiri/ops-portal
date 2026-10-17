/**
 * Every cluster the portal's API key can see, with its state, current CPU /
 * memory (busiest node), schedules, and stop / start.
 */

import React, { useCallback, useMemo, useState } from "react";
import { gridStyles, SortableHeader } from "../../components/gridStyles";
import { GridHeader, GridMessageRow, GridPagerBar, textMatches, useGridRows } from "../access/accessShared";
import { UtilizationBar } from "../infraAlerts/ResourceAdmin";
import { formatAxiosError } from "../../services/apiErrors";
import type { AtlasCluster, ClusterInventory, FleetUtilization, PowerAction } from "../../services/mongodbAtlasApi";
import { exportToCsv } from "../../utils/csvExport";
import {
  ATLAS_PAGE_SIZE,
  AtlasIcons,
  buttonTone,
  ClusterStatusChip,
  clusterKey,
  EnvironmentChip,
  IconAction,
  InfoNote,
  relativeTime,
  useAtlasCan,
} from "./shared";

type SortKey = "name" | "project" | "status" | "tier" | "cpu" | "memory" | "next";

function nextRun(cluster: AtlasCluster): { at: string; leg: "stop" | "start" } | null {
  let best: { at: string; leg: "stop" | "start" } | null = null;
  for (const s of cluster.schedules ?? []) {
    if (!s.is_enabled) continue;
    for (const [leg, at] of [
      ["stop", s.next_stop_at],
      ["start", s.next_start_at],
    ] as const) {
      if (at && (!best || at < best.at)) best = { at, leg };
    }
  }
  return best;
}

export const ClusterGrid: React.FC<{
  inventory: ClusterInventory | undefined;
  isLoading: boolean;
  error: unknown;
  utilization: FleetUtilization | undefined;
  onRefresh: () => void;
  refreshing: boolean;
  onPower: (cluster: AtlasCluster, action: PowerAction) => void;
  onOpen: (cluster: AtlasCluster) => void;
  formatDate: (v: string | null | undefined) => string;
}> = ({ inventory, isLoading, error, utilization, onRefresh, refreshing, onPower, onOpen, formatDate }) => {
  const can = useAtlasCan();
  const canPower = can("atlas_cluster_power");
  const [project, setProject] = useState("");
  const [status, setStatus] = useState<"" | "running" | "paused" | "busy">("");

  const clusters = useMemo(() => inventory?.clusters ?? [], [inventory]);
  const projects = useMemo(() => [...new Set(clusters.map((c) => c.project_name))].sort(), [clusters]);
  const filtered = useMemo(
    () =>
      clusters.filter((c) => {
        if (project && c.project_name !== project) return false;
        if (status === "running") return !c.paused && c.state === "IDLE" && !c.operation_in_progress;
        if (status === "paused") return c.paused;
        if (status === "busy") return Boolean(c.operation_in_progress) || c.state !== "IDLE";
        return true;
      }),
    [clusters, project, status],
  );
  const usage = useCallback((c: AtlasCluster) => utilization?.clusters[clusterKey(c)], [utilization]);

  const grid = useGridRows<AtlasCluster, SortKey>(filtered, {
    matches: useCallback(
      (c: AtlasCluster, q: string) =>
        textMatches(q, c.name, c.project_name, c.tier, c.provider, c.regions.join(" "), c.environment, c.mongo_version, ...c.tags.map((t) => `${t.key}=${t.value}`)),
      [],
    ),
    accessor: useCallback(
      (c: AtlasCluster, key: SortKey) => {
        switch (key) {
          case "project":
            return c.project_name;
          case "status":
            return c.paused ? "paused" : c.status;
          case "tier":
            return Number((c.tier ?? "").replace(/\D/g, "")) || 0;
          case "cpu":
            return usage(c)?.cpu ?? -1;
          case "memory":
            return usage(c)?.memory ?? -1;
          case "next":
            return nextRun(c)?.at ?? "9999";
          default:
            return c.name.toLowerCase();
        }
      },
      [usage],
    ),
    initialSort: { key: "project", direction: "asc" },
    pageSize: ATLAS_PAGE_SIZE,
  });

  const header = (label: string, key: SortKey, align: "left" | "center" = "left") => (
    <th className={align === "center" ? gridStyles.headerCellCenter : gridStyles.headerCell}>
      <SortableHeader label={label} active={grid.sort.key === key} direction={grid.sort.direction} onClick={() => grid.toggleSort(key)} align={align} />
    </th>
  );

  const exportCsv = () =>
    exportToCsv<AtlasCluster>("mongodb-atlas-clusters", filtered, [
      { header: "Project", value: (c) => c.project_name },
      { header: "Cluster", value: (c) => c.name },
      { header: "Environment", value: (c) => c.environment },
      { header: "Status", value: (c) => (c.paused ? "paused" : c.status) },
      { header: "Atlas state", value: (c) => c.state ?? "" },
      { header: "Tier", value: (c) => c.tier ?? "" },
      { header: "Provider", value: (c) => c.provider ?? "" },
      { header: "Regions", value: (c) => c.regions.join(" ") },
      { header: "MongoDB", value: (c) => c.mongo_version ?? "" },
      { header: "Nodes", value: (c) => c.node_count },
      { header: "Disk GB", value: (c) => c.disk_size_gb ?? "" },
      { header: "CPU %", value: (c) => usage(c)?.cpu ?? "" },
      { header: "Memory %", value: (c) => usage(c)?.memory ?? "" },
      { header: "Paused since", value: (c) => c.paused_since ?? "" },
      { header: "Schedules", value: (c) => (c.schedules ?? []).map((s) => s.name).join("; ") },
    ]);

  return (
    <div className="space-y-3">
      {inventory?.errors.map((e) => (
        <InfoNote key={e.project_id} tone="warning">
          Could not read clusters of project <b>{e.project_name}</b>: {e.error}
        </InfoNote>
      ))}
      <div className={gridStyles.shell}>
        <GridHeader
          title="Clusters"
          subtitle={
            inventory
              ? `${filtered.length} of ${clusters.length} clusters in ${inventory.project_count} project${inventory.project_count === 1 ? "" : "s"} · read ${relativeTime(inventory.fetched_at)}`
              : "Loading from Atlas…"
          }
          search={grid.search}
          onSearch={grid.setSearch}
          placeholder="Search cluster, project, tier, tag…"
        >
          <select value={project} onChange={(e) => setProject(e.target.value)} aria-label="Filter by project" className="rounded-lg border border-att-200 bg-white px-2 py-2 text-sm">
            <option value="">All projects</option>
            {projects.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <select value={status} onChange={(e) => setStatus(e.target.value as typeof status)} aria-label="Filter by status" className="rounded-lg border border-att-200 bg-white px-2 py-2 text-sm">
            <option value="">Any status</option>
            <option value="running">Running</option>
            <option value="paused">Paused</option>
            <option value="busy">Changing</option>
          </select>
          <button type="button" onClick={exportCsv} className={buttonTone.neutral} disabled={!filtered.length} title="Export the filtered clusters to CSV">
            <AtlasIcons.download />
            CSV
          </button>
          <button type="button" onClick={onRefresh} className={buttonTone.neutral} disabled={refreshing} title="Read again from Atlas">
            <AtlasIcons.refresh />
            {refreshing ? "Refreshing…" : "Refresh"}
          </button>
        </GridHeader>
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                {header("Cluster", "name")}
                {header("Project", "project")}
                {header("Status", "status")}
                {header("Tier", "tier")}
                <th className={gridStyles.headerCell}>Provider · region</th>
                {header("CPU", "cpu")}
                {header("Memory", "memory")}
                {header("Next scheduled", "next")}
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <GridMessageRow colSpan={9}>Loading clusters from Atlas…</GridMessageRow>
              ) : error ? (
                <GridMessageRow colSpan={9} tone="error">
                  {formatAxiosError(error, "Could not load clusters")}
                </GridMessageRow>
              ) : grid.pageRows.length === 0 ? (
                <GridMessageRow colSpan={9}>{clusters.length ? "No cluster matches the filters." : "The API key sees no clusters."}</GridMessageRow>
              ) : (
                grid.pageRows.map((c) => {
                  const u = usage(c);
                  const next = nextRun(c);
                  const busy = Boolean(c.operation_in_progress) || c.state !== "IDLE";
                  const action: PowerAction = c.paused ? "resume" : "pause";
                  const powerTitle = !canPower
                    ? "You need the atlas_cluster_power permission"
                    : busy
                      ? `Atlas is busy with this cluster (${c.operation_in_progress ? "stop/start in progress" : c.state})`
                      : action === "pause" && !c.pausable
                        ? c.pause_blocker ?? "Cannot be paused"
                        : action === "pause"
                          ? "Stop (pause) this cluster"
                          : "Start (resume) this cluster";
                  return (
                    <tr key={clusterKey(c)} className={gridStyles.row}>
                      <td className={gridStyles.strongCell}>
                        <button type="button" onClick={() => onOpen(c)} className="text-left hover:text-att-600 hover:underline">
                          {c.name}
                        </button>
                        <div className="mt-0.5 flex flex-wrap items-center gap-1">
                          <EnvironmentChip environment={c.environment} />
                          {c.auto_resume_warning && (
                            <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-amber-700" title="Atlas starts a paused cluster after 30 days">
                              <span className="h-3 w-3 [&>svg]:h-3 [&>svg]:w-3"><AtlasIcons.warning /></span>
                              auto-start in {30 - (c.paused_days ?? 0)}d
                            </span>
                          )}
                        </div>
                      </td>
                      <td className={gridStyles.cell}>{c.project_name}</td>
                      <td className={gridStyles.cell}>
                        <ClusterStatusChip cluster={c} />
                        {c.paused && c.paused_since && (
                          <div className="mt-0.5 text-[11px] text-slate-500" title={formatDate(c.paused_since)}>
                            since {relativeTime(c.paused_since).replace(" ago", "")}
                          </div>
                        )}
                      </td>
                      <td className={gridStyles.cell}>
                        <span className="font-semibold text-slate-800">{c.tier ?? "—"}</span>
                        <div className="text-[11px] text-slate-500">
                          {c.node_count} nodes{c.shard_count > 1 ? ` · ${c.shard_count} shards` : ""}
                        </div>
                      </td>
                      <td className={gridStyles.cell}>
                        {c.provider ?? "—"}
                        <div className="text-[11px] text-slate-500">{c.regions.join(", ")}</div>
                      </td>
                      <td className={gridStyles.cell}>
                        {c.paused ? <span className="text-xs text-slate-400">—</span> : <UtilizationBar value={u?.cpu} title="CPU, busiest node" />}
                      </td>
                      <td className={gridStyles.cell}>
                        {c.paused ? <span className="text-xs text-slate-400">—</span> : <UtilizationBar value={u?.memory} warning={80} critical={92} title="Memory, busiest node" />}
                      </td>
                      <td className={gridStyles.cell}>
                        {next ? (
                          <span title={formatDate(next.at)}>
                            <span className={next.leg === "stop" ? "font-semibold text-red-700" : "font-semibold text-green-700"}>
                              {next.leg === "stop" ? "Stop" : "Start"}
                            </span>{" "}
                            <span className="text-slate-600">{relativeTime(next.at)}</span>
                          </span>
                        ) : (
                          <span className="text-xs text-slate-400">—</span>
                        )}
                      </td>
                      <td className={gridStyles.centerCell}>
                        <div className="flex items-center justify-center gap-1">
                          <IconAction
                            title={powerTitle}
                            tone={action === "pause" ? "red" : "green"}
                            disabled={!canPower || busy || (action === "pause" && !c.pausable)}
                            onClick={() => onPower(c, action)}
                          >
                            {action === "pause" ? <AtlasIcons.stop /> : <AtlasIcons.start />}
                          </IconAction>
                          <IconAction title="Details, utilization and administration" tone="att" onClick={() => onOpen(c)}>
                            <AtlasIcons.details />
                          </IconAction>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
        <GridPagerBar page={grid.page} totalPages={grid.totalPages} total={grid.total} pageSize={grid.pageSize} onPage={grid.setPage} noun="clusters" />
      </div>
    </div>
  );
};
