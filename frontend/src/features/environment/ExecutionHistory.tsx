/**
 * ExecutionHistory – Grid showing environment scaling execution history.
 *
 * Grid features (KeyVault-style):
 * - Search toolbar with count badge
 * - Page size selector (10 / 20 / 50 per page)
 * - Bottom pagination: Showing X-Y of Z | « Previous Page N of M Next »
 * - Proper descriptive column headers
 * - Expandable step details with search
 */

import React, { useState, useEffect } from "react";
import { gridStyles, SortableHeader, type SortState, nextSortState } from "../../components/gridStyles";
import type { ExecutionHistory } from "../../services/environmentApi";
import apiClient from "../../services/apiClient";

interface Props {
  history: ExecutionHistory[];
  isLoading: boolean;
}

type HistoryField = "started_at" | "operation" | "status" | "namespace";

const PAGE_SIZES = [10, 20, 50];

const statusColors: Record<string, string> = {
  completed: "bg-green-100 text-green-700",
  failed: "bg-red-100 text-red-700",
  running: "bg-blue-100 text-blue-700",
  pending: "bg-gray-100 text-gray-500",
  rolled_back: "bg-orange-100 text-orange-700",
  dry_run: "bg-purple-100 text-purple-700",
};

const ExecutionHistoryGrid: React.FC<Props> = ({ history, isLoading }) => {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortState<HistoryField>>({ key: "started_at", direction: "desc" });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [detailSearch, setDetailSearch] = useState("");
  const [runningElapsed, setRunningElapsed] = useState<Record<number, number>>({});
  const [logDeployment, setLogDeployment] = useState<string | null>(null);
  const [logContent, setLogContent] = useState<string>("");
  const [logLoading, setLogLoading] = useState(false);

  // Auto-expand running entries and track elapsed time
  const runningEntries = history.filter((h) => h.status === "running");

  useEffect(() => {
    if (runningEntries.length === 0) return;
    // Auto-expand the first running entry
    if (runningEntries.length > 0 && expandedId === null) {
      setExpandedId(runningEntries[0].id);
    }
    const timer = setInterval(() => {
      const elapsed: Record<number, number> = {};
      for (const entry of runningEntries) {
        if (entry.started_at) {
          elapsed[entry.id] = Math.floor((Date.now() - new Date(entry.started_at).getTime()) / 1000);
        }
      }
      setRunningElapsed(elapsed);
    }, 1000);
    return () => clearInterval(timer);
  }, [runningEntries.length]);

  const formatElapsed = (secs: number) => {
    const m = Math.floor(secs / 60);
    return m > 0 ? `${m}m ${secs % 60}s` : `${secs}s`;
  };

  const handleShowLog = async (entry: ExecutionHistory, deploymentName: string) => {
    setLogDeployment(deploymentName);
    setLogContent("");
    setLogLoading(true);
    try {
      const { data } = await apiClient.get("/aks/pods/logs", {
        params: { cluster_id: entry.cluster_id, namespace: entry.namespace, deployment_name: deploymentName, tail_lines: 100 },
        timeout: 10000,
      });
      setLogContent(data?.logs || data?.log || (typeof data === "string" ? data : JSON.stringify(data, null, 2)));
    } catch {
      // Fallback: show deployment events
      try {
        const { data } = await apiClient.get("/aks/deployments", {
          params: { cluster_id: entry.cluster_id, namespace: entry.namespace },
          timeout: 8000,
        });
        const dep = Array.isArray(data) ? data.find((d: Record<string, unknown>) => d.name === deploymentName) : null;
        if (dep) {
          const conditions = (dep.conditions || []) as { type: string; status: string; reason?: string; message?: string }[];
          setLogContent(
            `Deployment: ${deploymentName}\nReplicas: ${dep.replicas} desired, ${dep.ready_replicas || 0} ready, ${dep.available_replicas || 0} available\n\nConditions:\n` +
            conditions.map((c) => `  [${c.type}] ${c.status} — ${c.reason || ""} ${c.message || ""}`).join("\n")
          );
        } else {
          setLogContent(`Deployment ${deploymentName} — waiting for pods to be scheduled...`);
        }
      } catch {
        setLogContent(`Unable to fetch logs for ${deploymentName}. The deployment may still be initializing.`);
      }
    }
    setLogLoading(false);
  };

  const filtered = history.filter(
    (h) =>
      h.namespace.toLowerCase().includes(search.toLowerCase()) ||
      h.operation.toLowerCase().includes(search.toLowerCase()) ||
      h.execution_type.toLowerCase().includes(search.toLowerCase()) ||
      h.status.toLowerCase().includes(search.toLowerCase()) ||
      (h.initiated_by_email ?? "").toLowerCase().includes(search.toLowerCase()),
  );

  const sorted = [...filtered].sort((a, b) => {
    const aVal = String(a[sort.key] ?? "");
    const bVal = String(b[sort.key] ?? "");
    return sort.direction === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
  });

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const start = sorted.length === 0 ? 0 : (safePage - 1) * pageSize + 1;
  const end = Math.min(safePage * pageSize, sorted.length);
  const paginated = sorted.slice((safePage - 1) * pageSize, safePage * pageSize);

  // Detail filtering for expanded row
  const getFilteredDetails = (h: ExecutionHistory) => {
    if (!h.step_details) return [];
    if (!detailSearch) return h.step_details;
    return h.step_details.filter(
      (d) =>
        d.deployment.toLowerCase().includes(detailSearch.toLowerCase()) ||
        d.status.toLowerCase().includes(detailSearch.toLowerCase()),
    );
  };

  return (
    <div className="space-y-4">
      <div className={gridStyles.shell}>
        {/* Toolbar */}
        <div className={gridStyles.panelHeader}>
          <div className="flex flex-wrap items-center gap-3">
            <span className={gridStyles.countBadge}>{filtered.length} execution{filtered.length !== 1 ? "s" : ""}</span>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-3">
            <input type="text" placeholder="Search history..." value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} className={gridStyles.toolbarInput} />
            <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }} className="rounded-lg border border-att-200 bg-white px-2 py-2 text-sm text-gray-700">
              {PAGE_SIZES.map((n) => <option key={n} value={n}>{n} / page</option>)}
            </select>
          </div>
        </div>

        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              <th className={gridStyles.headerCell}><SortableHeader label="Started At" active={sort.key === "started_at"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "started_at"))} /></th>
              <th className={gridStyles.headerCell}>Execution Type</th>
              <th className={gridStyles.headerCell}><SortableHeader label="Namespace" active={sort.key === "namespace"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "namespace"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Operation" active={sort.key === "operation"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "operation"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Status" active={sort.key === "status"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "status"))} /></th>
              <th className={gridStyles.headerCellCenter}>Progress</th>
              <th className={gridStyles.headerCell}>Duration</th>
              <th className={gridStyles.headerCell}>Initiated By</th>
            </tr>
          </thead>
          <tbody>
            {paginated.map((h) => {
              // Derive progress from step_details for consistency
              const stepsCompleted = h.step_details ? h.step_details.filter((d) => d.status === "completed").length : h.completed_count;
              const stepsRunning = h.step_details ? h.step_details.filter((d) => d.status === "running").length : 0;
              const stepsFailed = h.step_details ? h.step_details.filter((d) => d.status === "failed").length : h.failed_count;
              const stepsDone = stepsCompleted + stepsFailed;
              return (
              <React.Fragment key={h.id}>
                <tr
                  className={`${gridStyles.row} cursor-pointer`}
                  onClick={() => { setExpandedId(expandedId === h.id ? null : h.id); setDetailSearch(""); }}
                >
                  <td className={gridStyles.cell}>
                    {h.started_at ? new Date(h.started_at).toLocaleString() : "-"}
                  </td>
                  <td className={gridStyles.cell}>
                    <span className="inline-flex rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-600 capitalize">
                      {h.execution_type}
                    </span>
                  </td>
                  <td className={gridStyles.cell}>{h.namespace}</td>
                  <td className={gridStyles.cell}>{h.operation.replace(/_/g, " ")}</td>
                  <td className={gridStyles.cell}>
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${statusColors[h.status] || "bg-gray-100 text-gray-600"}`}>
                      {h.status === "running" && <svg className="mr-1 h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" /></svg>}
                      {h.status.replace(/_/g, " ")}
                    </span>
                  </td>
                  <td className={gridStyles.centerCell}>
                    <div className="flex items-center gap-2">
                      <div className="h-2 w-16 rounded-full bg-gray-200 overflow-hidden">
                        <div
                          className={`h-2 rounded-full transition-all duration-700 ${h.status === "running" ? "bg-gradient-to-r from-att-400 to-att-600" : h.status === "failed" || stepsFailed > 0 ? "bg-red-500" : "bg-green-500"}`}
                          style={{ width: h.total_deployments > 0 ? `${(stepsDone / h.total_deployments) * 100}%` : "0%" }}
                        />
                      </div>
                      <span className="text-xs text-gray-500">
                        {stepsCompleted}/{h.total_deployments}
                      </span>
                    </div>
                  </td>
                  <td className={gridStyles.cell}>
                    {h.status === "running" ? (
                      <span className="font-mono text-xs font-semibold text-att-600">{formatElapsed(runningElapsed[h.id] || 0)}</span>
                    ) : h.duration_seconds != null ? formatElapsed(Math.round(h.duration_seconds)) : "-"}
                  </td>
                  <td className={gridStyles.cell}>
                    <span className="text-xs text-gray-500">{h.initiated_by_email || h.initiated_by}</span>
                  </td>
                </tr>
                {/* Expanded step details */}
                {expandedId === h.id && (
                  <tr>
                    <td colSpan={8} className="bg-gray-50 px-6 py-3 space-y-2">
                      {/* Running status header */}
                      {h.status === "running" && (
                        <div className="flex items-center gap-3 rounded-lg bg-blue-50 border border-blue-200 px-4 py-2.5 mb-2">
                          <svg className="h-4 w-4 animate-spin text-att-500" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" /></svg>
                          <span className="text-sm font-medium text-blue-800">Execution in progress</span>
                          <span className="ml-auto flex items-center gap-2 rounded bg-white px-2.5 py-1 text-xs font-mono font-semibold text-att-700 border border-blue-200">
                            <svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" /></svg>
                            {formatElapsed(runningElapsed[h.id] || 0)}
                          </span>
                          <span className="text-xs text-blue-600">{stepsCompleted} of {h.total_deployments} steps done{stepsRunning > 0 ? `, ${stepsRunning} running` : ""}</span>
                        </div>
                      )}
                      {/* Detail search */}
                      <div className="flex items-center gap-3">
                        <span className="text-xs font-semibold text-gray-600">{h.step_details ? getFilteredDetails(h).length : h.total_deployments} deployment step{(h.step_details ? getFilteredDetails(h).length : h.total_deployments) !== 1 ? "s" : ""}</span>
                        <input
                          type="text"
                          placeholder="Search steps..."
                          value={detailSearch}
                          onChange={(e) => setDetailSearch(e.target.value)}
                          onClick={(e) => e.stopPropagation()}
                          className="ml-auto w-48 rounded-lg border border-gray-300 px-2 py-1 text-xs focus:border-att-400 focus:ring-1 focus:ring-att-100"
                        />
                      </div>
                      {h.step_details && h.step_details.length > 0 ? (
                        <div className="max-h-48 overflow-y-auto rounded-lg border border-gray-200 bg-white">
                          <table className="w-full text-xs">
                            <thead className="bg-gray-50 sticky top-0">
                              <tr>
                                <th className="px-3 py-1.5 text-left font-semibold text-gray-600">Deployment Name</th>
                                <th className="px-3 py-1.5 text-center font-semibold text-gray-600">Target Replicas</th>
                                <th className="px-3 py-1.5 text-center font-semibold text-gray-600">Status</th>
                                <th className="px-3 py-1.5 text-center font-semibold text-gray-600">Duration</th>
                                <th className="px-3 py-1.5 text-left font-semibold text-gray-600">Error</th>
                              </tr>
                            </thead>
                            <tbody>
                              {getFilteredDetails(h).map((d, i) => (
                                <tr key={i} className={`border-t border-gray-100 ${d.status === "running" ? "bg-blue-50/50" : ""}`}>
                                  <td className="px-3 py-1.5 font-mono">
                                    {(d.status === "running" || d.status === "pending") && h.status === "running" ? (
                                      <button
                                        onClick={(e) => { e.stopPropagation(); handleShowLog(h, d.deployment); }}
                                        className="text-att-600 hover:text-att-800 hover:underline font-mono text-xs"
                                        title="View deployment events"
                                      >
                                        {d.deployment}
                                      </button>
                                    ) : (
                                      <span className="text-xs">{d.deployment}</span>
                                    )}
                                  </td>
                                  <td className="px-3 py-1.5 text-center">{d.target_replicas}</td>
                                  <td className="px-3 py-1.5 text-center">
                                    {d.status === "running" ? (
                                      <span className="inline-flex items-center gap-1 text-xs font-medium text-att-600">
                                        <svg className="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" /></svg>
                                        Running
                                      </span>
                                    ) : d.status === "pending" ? (
                                      <span className="inline-flex items-center gap-1 text-xs text-gray-400">
                                        <span className="h-2 w-2 rounded-full bg-gray-300"></span>
                                        Pending
                                      </span>
                                    ) : (
                                      <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${statusColors[d.status] || "bg-gray-100 text-gray-600"}`}>
                                        {d.status === "completed" && <svg width="10" height="10" fill="none" stroke="currentColor" strokeWidth="2.5" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg>}
                                        {d.status}
                                      </span>
                                    )}
                                  </td>
                                  <td className="px-3 py-1.5 text-center text-xs text-gray-500">
                                    {(d as unknown as Record<string, unknown>).duration_seconds != null
                                      ? formatElapsed(Math.round(Number((d as unknown as Record<string, unknown>).duration_seconds)))
                                      : d.status === "running" && (d as unknown as Record<string, unknown>).started_at
                                        ? <StepElapsedTimer startedAt={String((d as unknown as Record<string, unknown>).started_at)} />
                                        : "\u2014"}
                                  </td>
                                  <td className="px-3 py-1.5 text-red-500 max-w-xs truncate">{d.error || ""}</td>
                                </tr>
                              ))}
                              {getFilteredDetails(h).length === 0 && (
                                <tr><td colSpan={5} className="px-3 py-4 text-center text-gray-400">No matching steps</td></tr>
                              )}
                            </tbody>
                          </table>
                        </div>
                      ) : h.status === "running" ? (
                        <div className="rounded-lg border border-gray-200 bg-white p-4 text-center text-xs text-gray-400">
                          <svg className="mx-auto mb-2 h-5 w-5 animate-spin text-att-400" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" /></svg>
                          Waiting for deployment steps to complete — data will appear in real-time
                        </div>
                      ) : null}
                      {h.error_message && (
                        <p className="text-xs text-red-600">Error: {h.error_message}</p>
                      )}
                      {/* Deployment log viewer */}
                      {logDeployment && expandedId === h.id && (
                        <div className="mt-3 rounded-lg border border-gray-300 bg-gray-900 overflow-hidden">
                          <div className="flex items-center justify-between bg-gray-800 px-3 py-2">
                            <span className="text-xs font-medium text-gray-200">
                              <span className="text-green-400">$</span> {logDeployment} — {logLoading ? "fetching..." : "deployment status"}
                            </span>
                            <button onClick={(e) => { e.stopPropagation(); setLogDeployment(null); setLogContent(""); }} className="text-gray-400 hover:text-white text-xs">Close</button>
                          </div>
                          <div className="p-3 max-h-40 overflow-y-auto">
                            {logLoading ? (
                              <div className="flex items-center gap-2 text-xs text-gray-400">
                                <svg className="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" /></svg>
                                Fetching deployment info...
                              </div>
                            ) : (
                              <pre className="text-xs text-green-300 font-mono whitespace-pre-wrap leading-relaxed">{logContent || "No data available"}</pre>
                            )}
                          </div>
                        </div>
                      )}
                    </td>
                  </tr>
                )}
              </React.Fragment>
              );
            })}
            {paginated.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-8 text-center text-sm text-gray-400">
                  {isLoading ? "Loading execution history..." : "No execution history found"}
                </td>
              </tr>
            )}
          </tbody>
        </table>

        {/* Pagination — KeyVault style */}
        <div className={gridStyles.pager}>
          <span className="text-gray-600">Showing {start}-{end} of {sorted.length}</span>
          <div className="flex items-center gap-2">
            <button onClick={() => setPage(1)} disabled={safePage <= 1} className={gridStyles.pagerButton}>&laquo;</button>
            <button onClick={() => setPage(Math.max(1, safePage - 1))} disabled={safePage <= 1} className={gridStyles.pagerButton}>Previous</button>
            <span className="text-gray-600">Page {safePage} of {totalPages}</span>
            <button onClick={() => setPage(Math.min(totalPages, safePage + 1))} disabled={safePage >= totalPages} className={gridStyles.pagerButton}>Next</button>
            <button onClick={() => setPage(totalPages)} disabled={safePage >= totalPages} className={gridStyles.pagerButton}>&raquo;</button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default ExecutionHistoryGrid;

/** Live elapsed timer for a running deployment step. */
const StepElapsedTimer: React.FC<{ startedAt: string }> = ({ startedAt }) => {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    const start = new Date(startedAt).getTime();
    if (isNaN(start)) return;
    const update = () => setElapsed(Math.max(0, Math.floor((Date.now() - start) / 1000)));
    update();
    const timer = setInterval(update, 1000);
    return () => clearInterval(timer);
  }, [startedAt]);

  if (isNaN(new Date(startedAt).getTime())) return <span className="text-gray-400">—</span>;

  const m = Math.floor(elapsed / 60);
  const s = elapsed % 60;
  const display = m > 0 ? `${m}m ${s}s` : `${s}s`;

  return <span className="font-mono font-semibold text-att-600">{display}</span>;
};
