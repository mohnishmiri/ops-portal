/**
 * Environment Scheduler Page — Environment Scaling & Scheduling management.
 *
 * Provides:
 * - Environment status dashboard with metric cards
 * - Manual environment scale up / down
 * - Scheduled auto-scaling management
 * - Startup/shutdown sequence designer
 * - Execution history
 */

import React, { useState, useCallback, useMemo } from "react";
import { useAuth } from "../contexts/AuthContext";
import Toast, { type ToastState } from "../components/Toast";
import { MetricCard, MetricCardIcons } from "../components/MetricCard";
import { AutoRefreshIndicator, SortableHeader, type SortState, nextSortState } from "../components/gridStyles";
import {
  useCachedClusters,
  useAksNamespaces,
  useCachedDeployments,
  type AKSCluster,
  type Deployment,
} from "../services/aksApi";
import {
  useEnvironmentStatus,
  useEnvironmentSchedules,
  useEnvironmentSequences,
  useExecutionHistory,
  useEnvironmentAuditLogs,
  useScaleEnvironment,
  useCreateSchedule,
  useUpdateSchedule,
  useDeleteSchedule,
  useRunScheduleNow,
  useCreateSequence,
  useUpdateSequence,
  useDeleteSequence,
  useStartSequence,
  useStopSequence,
  type AuditLogEntry,
} from "../services/environmentApi";
import EnvironmentScaleDialog from "../features/environment/EnvironmentScaleDialog";
import ScheduleManagement from "../features/environment/ScheduleManagement";
import SequenceDesigner from "../features/environment/SequenceDesigner";
import ExecutionHistoryGrid from "../features/environment/ExecutionHistory";

const Icons = {
  environment: (cls = "h-5 w-5") => (
    <svg className={cls} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
      <rect x="2" y="3" width="20" height="14" rx="2" />
      <path d="M8 21h8M12 17v4" />
    </svg>
  ),
  schedule: (cls = "h-5 w-5") => (
    <svg className={cls} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="10" />
      <path d="M12 6v6l4 2" />
    </svg>
  ),
  sequence: (cls = "h-5 w-5") => (
    <svg className={cls} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
      <path d="m12 3 9 4.5-9 4.5-9-4.5L12 3Z" />
      <path d="m3 12 9 4.5 9-4.5" />
      <path d="m3 16.5 9 4.5 9-4.5" />
    </svg>
  ),
  history: (cls = "h-5 w-5") => (
    <svg className={cls} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24">
      <path d="M3 3v5h5" />
      <path d="M3.05 13A9 9 0 1 0 6 5.3L3 8" />
      <path d="M12 7v5l4 2" />
    </svg>
  ),
};

type Tab = "dashboard" | "schedules" | "sequences" | "history" | "audit";

const EnvironmentSchedulerPage: React.FC = () => {
  const { canWrite } = useAuth();

  // ── Cluster/namespace selection ──
  const [selectedCluster, setSelectedCluster] = useState<AKSCluster | null>(null);
  const [selectedNamespace, setSelectedNamespace] = useState("default");
  const [activeTab, setActiveTab] = useState<Tab>("dashboard");
  const [showScaleDialog, setShowScaleDialog] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [cardFilter, setCardFilter] = useState<string | null>(null);
  const [cardDetailSearch, setCardDetailSearch] = useState("");
  const [clusterSearch, setClusterSearch] = useState("");

  // ── Data queries ──
  const { data: clustersData } = useCachedClusters();
  const { data: namespacesData } = useAksNamespaces(selectedCluster?.id ?? "");
  const { data: deploymentsData } = useCachedDeployments(selectedCluster?.id ?? "", selectedNamespace);
  const { data: envStatus } = useEnvironmentStatus(selectedCluster?.id ?? "", selectedNamespace);
  const { data: schedules, isLoading: schedulesLoading } = useEnvironmentSchedules(selectedCluster?.id, selectedNamespace);
  const { data: sequences, isLoading: sequencesLoading } = useEnvironmentSequences(selectedCluster?.id, selectedNamespace);
  const { data: history, isLoading: historyLoading } = useExecutionHistory(selectedCluster?.id, selectedNamespace);
  const { data: auditLogs } = useEnvironmentAuditLogs(100);

  const clusters = clustersData?.clusters ?? [];
  const deployments = deploymentsData?.deployments ?? [];

  // ── Mutations ──
  const scaleEnvironment = useScaleEnvironment();
  const createSchedule = useCreateSchedule();
  const updateSchedule = useUpdateSchedule();
  const deleteSchedule = useDeleteSchedule();
  const runScheduleNow = useRunScheduleNow();
  const createSequence = useCreateSequence();
  const updateSequence = useUpdateSequence();
  const deleteSequence = useDeleteSequence();
  const startSequence = useStartSequence();
  const stopSequence = useStopSequence();

  const nsList = useMemo(() => {
    const raw = namespacesData;
    if (Array.isArray(raw)) return raw as string[];
    if (raw && typeof raw === "object" && "namespaces" in raw) return (raw as { namespaces: string[] }).namespaces;
    return ["default"];
  }, [namespacesData]);
  const deploymentList = useMemo(() => (deployments ?? []) as Deployment[], [deployments]);
  const filteredClusters = useMemo(() => {
    const q = clusterSearch.trim().toLowerCase();
    if (!q) return clusters;
    return clusters.filter(
      (c: AKSCluster) =>
        c.name.toLowerCase().includes(q) ||
        c.location.toLowerCase().includes(q) ||
        (c.environment ?? "").toLowerCase().includes(q),
    );
  }, [clusters, clusterSearch]);

  const getFilteredDeployments = useCallback((filter: string) => {
    const deps = envStatus?.deployments ?? [];
    if (filter === "total") return deps;
    return deps.filter((d) => {
      const replicas = (d.replicas as number) || 0;
      const ready = (d.ready_replicas as number) || 0;
      const available = (d.available_replicas as number) || 0;
      if (filter === "running") return replicas > 0 && ready >= replicas && available >= replicas;
      if (filter === "stopped") return replicas === 0;
      if (filter === "scaling") return replicas > 0 && ready < replicas;
      if (filter === "failed") return replicas > 0 && ready < replicas && available < replicas && ready === 0;
      return true;
    });
  }, [envStatus]);

  // ── Handlers ──
  const handleScale = useCallback(
    async (request: Parameters<typeof scaleEnvironment.mutateAsync>[0]) => {
      const result = await scaleEnvironment.mutateAsync(request);
      const msg =
        result.status === "dry_run"
          ? `Dry run complete: ${result.total_deployments} deployments previewed`
          : `Scaled ${result.completed}/${result.total_deployments} deployments`;
      setToast({ message: msg, type: result.failed > 0 ? "warning" : "success" });
      return result;
    },
    [scaleEnvironment],
  );

  const handleCreateSchedule = useCallback(
    async (data: Parameters<typeof createSchedule.mutateAsync>[0]) => {
      await createSchedule.mutateAsync(data);
      setToast({ message: "Schedule created", type: "success" });
    },
    [createSchedule],
  );

  const handleUpdateSchedule = useCallback(
    async (id: number, data: Record<string, unknown>) => {
      await updateSchedule.mutateAsync({ id, ...data } as Parameters<typeof updateSchedule.mutateAsync>[0]);
      setToast({ message: "Schedule updated", type: "success" });
    },
    [updateSchedule],
  );

  const handleDeleteSchedule = useCallback(
    async (id: number) => {
      await deleteSchedule.mutateAsync(id);
      setToast({ message: "Schedule deleted", type: "success" });
    },
    [deleteSchedule],
  );

  const handleRunScheduleNow = useCallback(
    async (id: number) => {
      const result = await runScheduleNow.mutateAsync(id);
      setToast({
        message: `Schedule executed: ${result.completed}/${result.total_deployments} completed`,
        type: result.failed > 0 ? "warning" : "success",
      });
      return result;
    },
    [runScheduleNow],
  );

  const handleCreateSequence = useCallback(
    async (data: Parameters<typeof createSequence.mutateAsync>[0]) => {
      await createSequence.mutateAsync(data);
      setToast({ message: "Sequence created", type: "success" });
    },
    [createSequence],
  );

  const handleUpdateSequence = useCallback(
    async (id: number, data: Record<string, unknown>) => {
      await updateSequence.mutateAsync({ id, ...data } as Parameters<typeof updateSequence.mutateAsync>[0]);
      setToast({ message: "Sequence updated", type: "success" });
    },
    [updateSequence],
  );

  const handleDeleteSequence = useCallback(
    async (id: number) => {
      await deleteSequence.mutateAsync(id);
      setToast({ message: "Sequence deleted", type: "success" });
    },
    [deleteSequence],
  );

  const handleExecuteStart = useCallback(
    async (sequenceId: number, replicaCount: number, dryRun: boolean) => {
      const result = await startSequence.mutateAsync({
        sequence_id: sequenceId,
        replica_count: replicaCount,
        dry_run: dryRun,
      });
      setToast({
        message: `Startup sequence ${result.status}: ${result.completed}/${result.total_deployments} in ${result.details.length > 0 ? "completed" : "done"}`,
        type: result.failed > 0 ? "warning" : "success",
      });
      return result;
    },
    [startSequence],
  );

  const handleExecuteStop = useCallback(
    async (sequenceId: number, dryRun: boolean) => {
      const result = await stopSequence.mutateAsync({
        sequence_id: sequenceId,
        dry_run: dryRun,
      });
      setToast({
        message: `Shutdown sequence ${result.status}: ${result.completed}/${result.total_deployments}`,
        type: result.failed > 0 ? "warning" : "success",
      });
      return result;
    },
    [stopSequence],
  );

  const tabs: { key: Tab; label: string; icon: typeof Icons.environment }[] = [
    { key: "dashboard", label: "Dashboard", icon: Icons.environment },
    { key: "schedules", label: "Schedules", icon: Icons.schedule },
    { key: "sequences", label: "Sequences", icon: Icons.sequence },
    { key: "history", label: "History", icon: Icons.history },
    { key: "audit", label: "Audit Logs", icon: Icons.history },
  ];

  return (
    <div className="p-8 bg-gray-50 min-h-screen">
      <div className="max-w-7xl mx-auto space-y-8">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
              {Icons.environment("h-8 w-8 text-att-500")}
              Environment Scheduler
            </h1>
            <p className="mt-1 text-sm text-gray-500">
              Scale, schedule, and manage environment lifecycle
            </p>
          </div>
          <div className="flex items-center gap-3">
            <AutoRefreshIndicator />
            {canWrite && (
              <button
                onClick={() => setShowScaleDialog(true)}
                disabled={!selectedCluster}
                className="rounded-lg bg-att-500 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-att-600 disabled:opacity-50"
              >
                Environment Scale
              </button>
            )}
          </div>
        </div>

        {/* Cluster selection — clickable tiles */}
        <div className="space-y-3">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <label className="text-xs font-semibold uppercase tracking-wide text-gray-500">Cluster</label>
            <div className="flex flex-wrap items-center gap-2">
              <input
                aria-label="Search clusters"
                type="text"
                placeholder="Search clusters…"
                value={clusterSearch}
                onChange={(e) => setClusterSearch(e.target.value)}
                className="w-52 rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-att-400 focus:ring-1 focus:ring-att-100"
              />
              {selectedCluster && (
                <button
                  type="button"
                  onClick={() => {
                    setSelectedCluster(null);
                    setSelectedNamespace("default");
                  }}
                  className="text-xs font-medium text-att-600 hover:text-att-700"
                >
                  Clear selection
                </button>
              )}
            </div>
          </div>

          {clusters.length === 0 ? (
            <div className="rounded-xl border border-dashed border-att-200 bg-white p-4 text-center text-sm text-gray-500">
              No clusters available.
            </div>
          ) : filteredClusters.length > 0 ? (
            <div className="grid max-h-80 grid-cols-1 gap-3 overflow-y-auto pr-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {filteredClusters.map((c: AKSCluster) => {
                const active = selectedCluster?.id === c.id;
                const running = c.power_state === "Running";
                return (
                  <button
                    key={c.id}
                    type="button"
                    aria-pressed={active}
                    onClick={() => {
                      setSelectedCluster(active ? null : c);
                      setSelectedNamespace("default");
                    }}
                    className={`flex items-center gap-3 rounded-xl border p-4 text-left transition ${
                      active
                        ? "border-att-500 bg-att-50 ring-2 ring-att-200"
                        : "border-att-100 bg-white hover:border-att-300 hover:bg-att-50/50"
                    }`}
                  >
                    <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-att-100 text-att-700">
                      {MetricCardIcons.cloud("h-5 w-5")}
                    </div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-semibold text-gray-900" title={c.name}>
                        {c.name}
                      </p>
                      <p
                        className="truncate text-xs text-gray-500"
                        title={`${c.location} · ${c.node_count} node${c.node_count === 1 ? "" : "s"}`}
                      >
                        {c.location} · {c.node_count} node{c.node_count === 1 ? "" : "s"}
                      </p>
                      <div className="mt-1 flex items-center gap-1.5">
                        <span className={`h-1.5 w-1.5 rounded-full ${running ? "bg-green-500" : "bg-red-500"}`} />
                        <span className={`text-[11px] font-medium ${running ? "text-green-600" : "text-red-600"}`}>
                          {c.power_state || "Unknown"}
                        </span>
                      </div>
                    </div>
                    {active && (
                      <span className="shrink-0 rounded-full bg-att-100 px-2 py-0.5 text-xs font-medium text-att-600">
                        Active
                      </span>
                    )}
                  </button>
                );
              })}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-att-200 bg-white p-4 text-center text-sm text-gray-500">
              No clusters match your search.
            </div>
          )}

          {/* Namespace selector (depends on selected cluster) */}
          <div className="max-w-xs">
            <label className="text-xs font-semibold uppercase tracking-wide text-gray-500">Namespace</label>
            <select
              value={selectedNamespace}
              onChange={(e) => setSelectedNamespace(e.target.value)}
              disabled={!selectedCluster}
              className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-att-400 focus:ring-2 focus:ring-att-100 disabled:opacity-50 disabled:bg-gray-50"
            >
              {nsList.map((ns: string) => (
                <option key={ns} value={ns}>{ns}</option>
              ))}
            </select>
          </div>
        </div>

        {/* Metric cards */}
        {envStatus && (
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4 lg:grid-cols-5">
              {([
                { key: "total", title: "Total Deployments", value: envStatus.total_deployments, tone: "att" as const },
                { key: "running", title: "Running", value: envStatus.running, tone: "green" as const },
                { key: "stopped", title: "Stopped", value: envStatus.stopped, tone: "red" as const },
                { key: "scaling", title: "Scaling", value: envStatus.scaling, tone: "amber" as const },
                { key: "failed", title: "Failed", value: envStatus.failed, tone: "red" as const },
              ]).map((card) => (
                <button
                  key={card.key}
                  onClick={() => setCardFilter(cardFilter === card.key ? null : card.key)}
                  className={`text-left transition-all ${cardFilter === card.key ? "ring-2 ring-att-400 rounded-2xl" : "hover:scale-[1.02]"}`}
                >
                  <MetricCard
                    title={card.title}
                    value={card.value}
                    icon={MetricCardIcons.layers()}
                    tone={card.tone}
                  />
                </button>
              ))}
            </div>

            {/* Expanded card detail panel */}
            {cardFilter && (
              <div className="rounded-xl border border-att-100 bg-white shadow-sm overflow-hidden">
                <div className="border-b border-gray-200 bg-gray-50 px-5 py-3 flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <h4 className="text-sm font-semibold text-gray-800 capitalize">
                      {cardFilter === "total" ? "All" : cardFilter} Deployments
                    </h4>
                    <span className="inline-flex items-center rounded-full bg-att-50 px-2.5 py-0.5 text-xs font-medium text-att-700">
                      {getFilteredDeployments(cardFilter).length}
                    </span>
                  </div>
                  <div className="flex items-center gap-2">
                    <input
                      type="text"
                      placeholder="Search deployments..."
                      value={cardDetailSearch}
                      onChange={(e) => setCardDetailSearch(e.target.value)}
                      className="w-56 rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-att-400 focus:ring-1 focus:ring-att-100"
                    />
                    <button onClick={() => setCardFilter(null)} className="rounded-lg border border-gray-300 px-2.5 py-1.5 text-xs text-gray-600 hover:bg-gray-100">Close</button>
                  </div>
                </div>
                <div className="max-h-72 overflow-y-auto">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 sticky top-0">
                      <tr>
                        <th className="px-4 py-2 text-left text-xs font-semibold text-gray-600">Deployment Name</th>
                        <th className="px-4 py-2 text-center text-xs font-semibold text-gray-600">Replicas</th>
                        <th className="px-4 py-2 text-center text-xs font-semibold text-gray-600">Ready</th>
                        <th className="px-4 py-2 text-center text-xs font-semibold text-gray-600">Available</th>
                        <th className="px-4 py-2 text-center text-xs font-semibold text-gray-600">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {getFilteredDeployments(cardFilter)
                        .filter((d) => (d.name as string).toLowerCase().includes(cardDetailSearch.toLowerCase()))
                        .map((dep, idx) => {
                          const name = dep.name as string;
                          const replicas = (dep.replicas as number) || 0;
                          const ready = (dep.ready_replicas as number) || 0;
                          const available = (dep.available_replicas as number) || 0;
                          const status = replicas === 0 ? "stopped" : ready >= replicas ? "running" : ready < replicas ? "scaling" : "failed";
                          return (
                            <tr key={idx} className="border-t border-gray-100 hover:bg-gray-50">
                              <td className="px-4 py-2 font-mono text-xs">{name}</td>
                              <td className="px-4 py-2 text-center">{replicas}</td>
                              <td className="px-4 py-2 text-center">
                                <span className={ready >= replicas && replicas > 0 ? "text-green-600 font-medium" : "text-gray-500"}>{ready}</span>
                              </td>
                              <td className="px-4 py-2 text-center">{available}</td>
                              <td className="px-4 py-2 text-center">
                                <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                                  status === "running" ? "bg-green-100 text-green-700"
                                  : status === "stopped" ? "bg-gray-100 text-gray-600"
                                  : status === "scaling" ? "bg-yellow-100 text-yellow-700"
                                  : "bg-red-100 text-red-700"
                                }`}>
                                  {status}
                                </span>
                              </td>
                            </tr>
                          );
                        })}
                      {getFilteredDeployments(cardFilter).filter((d) => (d.name as string).toLowerCase().includes(cardDetailSearch.toLowerCase())).length === 0 && (
                        <tr><td colSpan={5} className="px-4 py-6 text-center text-sm text-gray-400">No deployments match</td></tr>
                      )}
                    </tbody>
                  </table>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Tab navigation */}
        <div className="border-b border-gray-200">
          <nav className="flex gap-1">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={`flex items-center gap-2 border-b-2 px-4 py-3 text-sm font-medium transition ${
                  activeTab === tab.key
                    ? "border-att-500 text-att-600"
                    : "border-transparent text-gray-500 hover:border-gray-300 hover:text-gray-700"
                }`}
              >
                {tab.icon("h-4 w-4")}
                {tab.label}
              </button>
            ))}
          </nav>
        </div>

        {/* Tab content */}
        {activeTab === "dashboard" && (
          <div className="space-y-6">
            {/* Upcoming schedules */}
            <div className="rounded-xl border border-att-100 bg-white p-5">
              <h3 className="text-lg font-semibold text-gray-800 mb-4">Upcoming Schedules</h3>
              {(schedules ?? []).filter((s) => s.is_enabled).length > 0 ? (
                <div className="space-y-2">
                  {(schedules ?? [])
                    .filter((s) => s.is_enabled)
                    .slice(0, 5)
                    .map((s) => (
                      <div key={s.id} className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
                        <div className="flex items-center gap-3">
                          {Icons.schedule("h-4 w-4 text-att-500")}
                          <span className="font-medium text-gray-800">{s.job_name}</span>
                          <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                            s.operation === "scale_up" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                          }`}>
                            {s.operation === "scale_up" ? "Scale Up" : "Scale Down"}
                          </span>
                        </div>
                        <div className="text-xs text-gray-500">
                          {s.next_run_at ? `Next: ${new Date(s.next_run_at).toLocaleString()}` : "Not scheduled"}
                        </div>
                      </div>
                    ))}
                </div>
              ) : (
                <p className="text-sm text-gray-400">No active schedules</p>
              )}
            </div>

            {/* Recent executions */}
            <div className="rounded-xl border border-att-100 bg-white p-5">
              <h3 className="text-lg font-semibold text-gray-800 mb-4">Recent Executions</h3>
              {(history ?? []).length > 0 ? (
                <div className="space-y-2">
                  {(history ?? []).slice(0, 5).map((h) => (
                    <div key={h.id} className="flex items-center justify-between rounded-lg bg-gray-50 px-4 py-3">
                      <div className="flex items-center gap-3">
                        {Icons.history("h-4 w-4 text-gray-400")}
                        <span className="text-sm text-gray-700">{h.operation.replace(/_/g, " ")}</span>
                        <span className="text-xs text-gray-400">{h.namespace}</span>
                      </div>
                      <div className="flex items-center gap-3">
                        <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                          h.status === "completed" ? "bg-green-100 text-green-700"
                          : h.status === "failed" ? "bg-red-100 text-red-700"
                          : "bg-blue-100 text-blue-700"
                        }`}>
                          {h.status}
                        </span>
                        <span className="text-xs text-gray-500">
                          {h.started_at ? new Date(h.started_at).toLocaleString() : ""}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="text-sm text-gray-400">No execution history</p>
              )}
            </div>
          </div>
        )}

        {selectedCluster && (
          <div className={activeTab === "schedules" ? "" : "hidden"}>
            <ScheduleManagement
              schedules={schedules ?? []}
              sequences={sequences ?? []}
              clusterId={selectedCluster.id}
              namespaces={nsList}
              onCreate={handleCreateSchedule}
              onUpdate={handleUpdateSchedule}
              onDelete={handleDeleteSchedule}
              onRunNow={handleRunScheduleNow}
              isLoading={schedulesLoading || createSchedule.isPending}
            />
          </div>
        )}

        {activeTab === "sequences" && selectedCluster && (
          <SequenceDesigner
            sequences={sequences ?? []}
            deployments={deploymentList}
            clusterId={selectedCluster.id}
            namespace={selectedNamespace}
            onCreate={handleCreateSequence}
            onUpdate={handleUpdateSequence}
            onDelete={handleDeleteSequence}
            onExecuteStart={handleExecuteStart}
            onExecuteStop={handleExecuteStop}
            isLoading={sequencesLoading || createSequence.isPending}
          />
        )}

        {activeTab === "history" && (
          <ExecutionHistoryGrid history={history ?? []} isLoading={historyLoading} />
        )}

        {activeTab === "audit" && (
          <AuditLogsTab logs={auditLogs ?? []} />
        )}

        {/* No cluster selected message */}
        {!selectedCluster && activeTab !== "dashboard" && (
          <div className="rounded-xl border border-att-100 bg-white p-12 text-center">
            <p className="text-gray-400">Select a cluster to manage environment scaling</p>
          </div>
        )}
      </div>

      {/* Scale Dialog */}
      {showScaleDialog && selectedCluster && (
        <EnvironmentScaleDialog
          open={showScaleDialog}
          onClose={() => setShowScaleDialog(false)}
          clusterId={selectedCluster.id}
          namespaces={nsList}
          onScale={handleScale}
          isScaling={scaleEnvironment.isPending}
        />
      )}

      {/* Toast */}
      {toast && (
        <Toast
          message={toast.message}
          type={toast.type}
          onClose={() => setToast(null)}
        />
      )}
    </div>
  );
};

export default EnvironmentSchedulerPage;

// ── Audit Logs Tab Component ──────────────────────────────────────────

const ACTION_LABELS: Record<string, string> = {
  create_schedule: "Created Schedule",
  update_schedule: "Updated Schedule",
  delete_schedule: "Deleted Schedule",
  run_schedule_manually: "Ran Schedule Manually",
  create_sequence: "Created Sequence",
  update_sequence: "Updated Sequence",
  delete_sequence: "Deleted Sequence",
  execute_start_sequence: "Executed Startup Sequence",
  execute_stop_sequence: "Executed Shutdown Sequence",
  environment_scale_up: "Scaled Up Environment",
  environment_scale_down: "Scaled Down Environment",
};

const AuditLogsTab: React.FC<{ logs: AuditLogEntry[] }> = ({ logs }) => {
  const [search, setSearch] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [sort, setSort] = React.useState<SortState<string>>({ key: "timestamp", direction: "desc" });
  const pageSize = 20;

  const filtered = logs.filter(
    (l) =>
      (l.action ?? "").toLowerCase().includes(search.toLowerCase()) ||
      (l.user_email ?? "").toLowerCase().includes(search.toLowerCase()) ||
      (l.resource_type ?? "").toLowerCase().includes(search.toLowerCase()) ||
      (l.status ?? "").toLowerCase().includes(search.toLowerCase()),
  );

  const sorted = [...filtered].sort((a, b) => {
    const aVal = String((a as unknown as Record<string, unknown>)[sort.key] ?? "");
    const bVal = String((b as unknown as Record<string, unknown>)[sort.key] ?? "");
    return sort.direction === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
  });

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const start = sorted.length === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const end = Math.min(safePage * pageSize, sorted.length);
  const paginated = sorted.slice((safePage - 1) * pageSize, safePage * pageSize);

  return (
    <div className="overflow-hidden rounded-xl border border-att-100 bg-white shadow-sm">
      <div className="border-b border-att-100 bg-att-50/70 px-4 py-3 flex flex-wrap items-center justify-between gap-3">
        <span className="inline-flex items-center rounded-full bg-att-50 px-2.5 py-1 text-xs font-medium text-att-700">
          {sorted.length} log{sorted.length !== 1 ? "s" : ""}
        </span>
        <input
          type="text"
          placeholder="Search audit logs..."
          value={search}
          onChange={(e) => { setSearch(e.target.value); setPage(1); }}
          className="w-64 rounded-lg border border-att-200 bg-white px-3 py-2 text-sm text-gray-700 shadow-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100"
        />
      </div>
      <table className="w-full bg-white">
        <thead className="bg-att-50/80">
          <tr>
            <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.12em] text-att-700"><SortableHeader label="Timestamp" active={sort.key === "timestamp"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "timestamp"))} /></th>
            <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.12em] text-att-700"><SortableHeader label="Action" active={sort.key === "action"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "action"))} /></th>
            <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.12em] text-att-700"><SortableHeader label="Resource" active={sort.key === "resource_type"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "resource_type"))} /></th>
            <th className="px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.12em] text-att-700"><SortableHeader label="Status" active={sort.key === "status"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "status"))} /></th>
            <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.12em] text-att-700"><SortableHeader label="User" active={sort.key === "user_email"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "user_email"))} /></th>
            <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.12em] text-att-700">Details</th>
          </tr>
        </thead>
        <tbody>
          {paginated.map((log) => (
            <tr key={log.id} className="border-t border-att-100 hover:bg-att-50/40">
              <td className="px-4 py-2.5 text-sm text-gray-700">
                {log.timestamp ? new Date(log.timestamp).toLocaleString() : "-"}
              </td>
              <td className="px-4 py-2.5 text-sm font-medium text-gray-800">
                {ACTION_LABELS[log.action] || log.action.replace(/_/g, " ")}
              </td>
              <td className="px-4 py-2.5 text-sm text-gray-600">
                <span className="inline-flex rounded bg-gray-100 px-1.5 py-0.5 text-xs font-medium text-gray-600">
                  {log.resource_type.replace("environment_", "")}
                </span>
                {log.resource_id && <span className="ml-1 text-xs text-gray-400">#{log.resource_id}</span>}
              </td>
              <td className="px-4 py-2.5 text-center">
                <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${log.status === "success" || log.status === "completed" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                  {log.status}
                </span>
              </td>
              <td className="px-4 py-2.5 text-xs text-gray-500">{log.user_email || log.user_id}</td>
              <td className="px-4 py-2.5 text-xs text-gray-500 max-w-xs truncate">
                {log.details ? Object.entries(log.details).map(([k, v]) => `${k}: ${v}`).join(", ") : "—"}
              </td>
            </tr>
          ))}
          {paginated.length === 0 && (
            <tr><td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-400">No audit logs found</td></tr>
          )}
        </tbody>
      </table>
      <div className="flex items-center justify-between border-t border-att-100 bg-att-50/40 px-4 py-3 text-sm">
        <span className="text-gray-600">Showing {start}-{end} of {sorted.length}</span>
        <div className="flex items-center gap-2">
          <button onClick={() => setPage(1)} disabled={safePage <= 1} className="rounded-lg border border-att-200 bg-white px-3 py-1.5 text-gray-700 hover:border-att-300 hover:bg-att-50 disabled:opacity-40">&laquo;</button>
          <button onClick={() => setPage(Math.max(1, safePage - 1))} disabled={safePage <= 1} className="rounded-lg border border-att-200 bg-white px-3 py-1.5 text-gray-700 hover:border-att-300 hover:bg-att-50 disabled:opacity-40">Previous</button>
          <span className="text-gray-600">Page {safePage} of {totalPages}</span>
          <button onClick={() => setPage(Math.min(totalPages, safePage + 1))} disabled={safePage >= totalPages} className="rounded-lg border border-att-200 bg-white px-3 py-1.5 text-gray-700 hover:border-att-300 hover:bg-att-50 disabled:opacity-40">Next</button>
          <button onClick={() => setPage(totalPages)} disabled={safePage >= totalPages} className="rounded-lg border border-att-200 bg-white px-3 py-1.5 text-gray-700 hover:border-att-300 hover:bg-att-50 disabled:opacity-40">&raquo;</button>
        </div>
      </div>
    </div>
  );
};
