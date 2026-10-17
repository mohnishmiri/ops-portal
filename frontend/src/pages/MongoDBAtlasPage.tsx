/**
 * MongoDB Atlas — start/stop clusters, schedule it, watch utilization, and
 * administer projects through the portal's Atlas API key.
 *
 * Tabs: Clusters · Schedules · Activity · Administration · Audit log
 * (deep-linkable with ?tab=…).
 *
 * Access: the route needs the "mongodb_atlas" module (managed like every
 * other module in Admin → Permissions); it does not need an Azure
 * subscription grant. Each action is gated exactly as the API gates it — the
 * write role plus the action's capability (atlas_cluster_power,
 * atlas_schedule_manage, atlas_cluster_admin, atlas_database_access).
 */

import React, { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { MetricCard, MetricCardIcons } from "../components/MetricCard";
import Toast, { type ToastState } from "../components/Toast";
import { usePortalTimezone } from "../contexts/TimezoneContext";
import { ClusterDetail } from "../features/mongodbAtlas/ClusterDetail";
import { CLUSTER_FILTERS, type ClusterFilter, ClusterGrid } from "../features/mongodbAtlas/ClusterGrid";
import { ATTENTION_WINDOW_MS, AuditGrid, OperationsGrid } from "../features/mongodbAtlas/ActivityAndAudit";
import { PowerDialog } from "../features/mongodbAtlas/PowerDialog";
import { ConnectionPanel, ProjectAdmin } from "../features/mongodbAtlas/ProjectAdmin";
import { ScheduleManager } from "../features/mongodbAtlas/ScheduleManager";
import { relativeTime } from "../features/mongodbAtlas/shared";
import apiClient from "../services/apiClient";
import {
  atlasKeys,
  type AtlasCluster,
  type PowerAction,
  useAtlasClusters,
  useAtlasProjects,
  useAtlasStatus,
  useFleetUtilization,
  useOperations,
  useSchedules,
} from "../services/mongodbAtlasApi";

type Tab = "clusters" | "schedules" | "activity" | "admin" | "audit";
const TABS: { key: Tab; label: string }[] = [
  { key: "clusters", label: "Clusters" },
  { key: "schedules", label: "Schedules" },
  { key: "activity", label: "Activity" },
  { key: "admin", label: "Administration" },
  { key: "audit", label: "Audit log" },
];

const plural = (count: number, noun: string) => `${count} ${noun}${count === 1 ? "" : "s"}`;

const MongoDBAtlasPage: React.FC = () => {
  const [params, setParams] = useSearchParams();
  const tab = (TABS.some((t) => t.key === params.get("tab")) ? params.get("tab") : "clusters") as Tab;
  // ?filter= narrows the grid of the current tab; the KPI tiles set both.
  const filter = params.get("filter") ?? "";
  const openView = (next: Tab, nextFilter = "") => {
    const query: Record<string, string> = {};
    if (next !== "clusters") query.tab = next;
    if (nextFilter) query.filter = nextFilter;
    setParams(query, { replace: true });
  };
  const setTab = (next: Tab) => openView(next);
  const clusterFilter = (CLUSTER_FILTERS as readonly string[]).includes(filter) ? (filter as ClusterFilter) : "";
  const viewing = (t: Tab, f = "") => tab === t && filter === f;
  const { formatDate } = usePortalTimezone();
  const qc = useQueryClient();

  const status = useAtlasStatus();
  // Only ask Atlas for data once the status check reached it: otherwise every
  // tab waits out the same network failure the connection panel already shows.
  const ready = Boolean(status.data?.configured && status.data.reachable);
  const clusters = useAtlasClusters(ready);
  const projects = useAtlasProjects(ready);
  const utilization = useFleetUtilization(ready && Boolean(clusters.data?.clusters.some((c) => !c.paused)));
  const schedules = useSchedules();
  const operations = useOperations();

  const [power, setPower] = useState<{ cluster: AtlasCluster; action: PowerAction } | null>(null);
  const [openKey, setOpenKey] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);

  const all = useMemo(() => clusters.data?.clusters ?? [], [clusters.data]);
  // The detail view follows the live inventory, so a stop/start shows up in it too.
  const open = openKey ? all.find((c) => `${c.project_id}/${c.name}` === openKey) ?? null : null;

  const kpis = useMemo(() => {
    const running = all.filter((c) => !c.paused && c.state === "IDLE" && !c.operation_in_progress).length;
    const paused = all.filter((c) => c.paused).length;
    const changing = all.filter((c) => c.operation_in_progress || (c.state && c.state !== "IDLE")).length;
    const warnings = all.filter((c) => c.auto_resume_warning).length;
    const enabled = (schedules.data ?? []).filter((s) => s.is_enabled);
    const next = enabled
      .flatMap((s) => [s.next_stop_at, s.next_start_at])
      .filter((x): x is string => Boolean(x))
      .sort()[0];
    const weekAgo = Date.now() - ATTENTION_WINDOW_MS;
    const failed = (operations.data?.operations ?? []).filter(
      (o) => (o.status === "failed" || o.status === "partial") && new Date(o.requested_at).getTime() > weekAgo,
    ).length;
    return { running, paused, changing, warnings, enabled: enabled.length, next, failed };
  }, [all, schedules.data, operations.data]);

  const refresh = async () => {
    setRefreshing(true);
    try {
      // ?refresh=true skips the backend's short cache; then refetch everything here.
      await apiClient.get("/mongodb-atlas/clusters", { params: { refresh: true } });
      await qc.invalidateQueries({ queryKey: atlasKeys.all });
    } catch {
      setToast({ message: "Could not refresh from Atlas", type: "error" });
    } finally {
      setRefreshing(false);
    }
  };

  const attention = kpis.failed + kpis.warnings + (clusters.data?.errors.length ?? 0);

  return (
    <div className="space-y-5 py-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">MongoDB Atlas</h1>
          <p className="text-sm text-slate-500">
            Stop, start and schedule clusters, watch their utilization, and administer projects — every change audited.
          </p>
        </div>
        {status.data && (
          <span
            className={`inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-semibold ${
              status.data.configured && status.data.reachable ? "bg-green-50 text-green-700 ring-1 ring-green-200" : "bg-amber-50 text-amber-800 ring-1 ring-amber-200"
            }`}
            title={status.data.error ?? `API key ${status.data.public_key ?? ""}`}
          >
            <span className={`h-2 w-2 rounded-full ${status.data.configured && status.data.reachable ? "bg-green-500" : "bg-amber-500"}`} aria-hidden="true" />
            {!status.data.configured ? "Atlas not configured" : status.data.reachable ? `Connected · ${plural(status.data.project_count, "project")}` : "Atlas not reachable"}
          </span>
        )}
      </header>

      {status.data && !(status.data.configured && status.data.reachable) && (
        <ConnectionPanel status={status.data} isLoading={false} formatDate={formatDate} />
      )}

      {ready && (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
          {/* Each tile opens the view behind its number. */}
          <MetricCard
            compact
            title="Clusters"
            value={clusters.isLoading ? "…" : all.length}
            icon={MetricCardIcons.database()}
            subtitle={plural(clusters.data?.project_count ?? 0, "project")}
            onClick={() => openView("clusters")}
            active={viewing("clusters")}
            actionLabel="Show all clusters"
          />
          <MetricCard
            compact
            tone="green"
            title="Running"
            value={clusters.isLoading ? "…" : kpis.running}
            icon={MetricCardIcons.activity()}
            subtitle={kpis.changing ? `${kpis.changing} changing` : "IDLE in Atlas"}
            onClick={() => openView("clusters", "running")}
            active={viewing("clusters", "running")}
            actionLabel="Show running clusters"
          />
          <MetricCard
            compact
            tone="slate"
            title="Paused"
            value={clusters.isLoading ? "…" : kpis.paused}
            icon={MetricCardIcons.server()}
            subtitle="billed for storage only"
            onClick={() => openView("clusters", "paused")}
            active={viewing("clusters", "paused")}
            actionLabel="Show paused clusters"
          />
          <MetricCard
            compact
            tone="att"
            title="Schedules"
            value={schedules.isLoading ? "…" : kpis.enabled}
            icon={MetricCardIcons.calendar()}
            subtitle={kpis.next ? `next run ${relativeTime(kpis.next)}` : "none upcoming"}
            onClick={() => openView("schedules")}
            active={viewing("schedules")}
            actionLabel="Show start/stop schedules"
          />
          <MetricCard
            compact
            tone={attention ? "amber" : "emerald"}
            title="Needs attention"
            value={attention}
            icon={MetricCardIcons.alert()}
            subtitle={
              attention
                ? [kpis.failed && `${kpis.failed} failed (7d)`, kpis.warnings && `${kpis.warnings} near auto-start`, clusters.data?.errors.length && "project errors"]
                    .filter(Boolean)
                    .join(" · ")
                : "all clear"
            }
            // Cluster problems first (they need someone to act); else the failed stops/starts.
            onClick={
              attention
                ? () => (kpis.warnings || clusters.data?.errors.length ? openView("clusters", "attention") : openView("activity", "attention"))
                : undefined
            }
            active={viewing("clusters", "attention") || viewing("activity", "attention")}
            actionLabel="Show what needs attention"
          />
        </div>
      )}

      <nav className="flex flex-wrap gap-1 border-b border-att-100" role="tablist" aria-label="MongoDB Atlas sections">
        {TABS.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium transition ${
              tab === t.key ? "border-att-500 text-att-700" : "border-transparent text-slate-500 hover:text-att-600"
            }`}
          >
            {t.label}
            {t.key === "activity" && (operations.data?.in_progress ?? 0) > 0 && (
              <span className="ml-1.5 rounded-full bg-sky-100 px-1.5 text-[11px] font-semibold text-sky-700">{operations.data?.in_progress}</span>
            )}
          </button>
        ))}
      </nav>

      <div role="tabpanel">
        {tab === "clusters" &&
          (ready ? (
            <ClusterGrid
              inventory={clusters.data}
              isLoading={clusters.isLoading}
              error={clusters.error}
              utilization={utilization.data}
              onRefresh={refresh}
              refreshing={refreshing}
              onPower={(cluster, action) => setPower({ cluster, action })}
              onOpen={(cluster) => setOpenKey(`${cluster.project_id}/${cluster.name}`)}
              formatDate={formatDate}
              status={clusterFilter}
              onStatusChange={(next) => openView("clusters", next)}
            />
          ) : (
            !status.isLoading && (
              <p className="text-sm text-slate-500">
                {status.data?.configured
                  ? "Clusters load once Atlas is reachable — the connection test above shows where the connection breaks."
                  : "Configure the Atlas API key to list clusters."}
              </p>
            )
          ))}
        {tab === "schedules" && <ScheduleManager clusters={all} formatDate={formatDate} />}
        {tab === "activity" && (
          <OperationsGrid formatDate={formatDate} status={filter} onStatusChange={(next) => openView("activity", next)} />
        )}
        {tab === "admin" && (
          <ProjectAdmin projects={projects.data ?? []} clusters={all} status={status.data} statusLoading={status.isLoading} formatDate={formatDate} />
        )}
        {tab === "audit" && <AuditGrid formatDate={formatDate} />}
      </div>

      {power && (
        <PowerDialog
          cluster={power.cluster}
          action={power.action}
          onClose={() => setPower(null)}
          onStarted={(op) => {
            const verb = power.action === "pause" ? "Stop" : "Start";
            setToast(
              op.status === "failed"
                ? { message: `${verb} of ${power.cluster.name} failed: ${op.error_message ?? "Atlas refused it"}`, type: "error" }
                : op.status === "completed"
                  ? { message: `${power.cluster.name} was already ${power.action === "pause" ? "paused" : "running"}`, type: "info" }
                  : { message: `${verb} of ${power.cluster.name} sent to Atlas (operation #${op.id})`, type: "success" },
            );
          }}
        />
      )}
      {open && <ClusterDetail cluster={open} onClose={() => setOpenKey(null)} formatDate={formatDate} />}
      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
};

export default MongoDBAtlasPage;
