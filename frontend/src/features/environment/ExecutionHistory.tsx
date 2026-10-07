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
import type { ExecutionHistory, StepDetail } from "../../services/environmentApi";
import apiClient from "../../services/apiClient";
import {
  ExecutionStepsTable,
  StatusBadge,
  effectiveStepStatus,
  formatDuration,
  operationLabel,
  statusLabel,
  stepCounts,
  type StepSortKey,
} from "./executionStatus";

interface Props {
  history: ExecutionHistory[];
  isLoading: boolean;
}

type HistoryField = "started_at" | "operation" | "status" | "namespace";

const PAGE_SIZES = [10, 20, 50];

const ExecutionHistoryGrid: React.FC<Props> = ({ history, isLoading }) => {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortState<HistoryField>>({ key: "started_at", direction: "desc" });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [expandedId, setExpandedId] = useState<number | null>(null);
  const [detailSearch, setDetailSearch] = useState("");
  // Execution order by default: that is how a sequence is read.
  const [stepSort, setStepSort] = useState<SortState<StepSortKey>>({ key: "step", direction: "asc" });
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

  const formatElapsed = formatDuration;

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

  const q = search.toLowerCase();
  const filtered = history.filter(
    (h) =>
      h.namespace.toLowerCase().includes(q) ||
      h.operation.toLowerCase().includes(q) ||
      operationLabel(h.operation).toLowerCase().includes(q) ||
      h.execution_type.toLowerCase().includes(q) ||
      h.status.toLowerCase().includes(q) ||
      statusLabel(h.status).toLowerCase().includes(q) ||
      (h.sequence_name ?? "").toLowerCase().includes(q) ||
      (h.schedule_name ?? "").toLowerCase().includes(q) ||
      (h.initiated_by_email ?? "").toLowerCase().includes(q) ||
      (h.step_details ?? []).some((d) => d.deployment.toLowerCase().includes(q)),
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
    const term = detailSearch.toLowerCase();
    // Keep each step's execution position: older rows predate the "step" field.
    const numbered = h.step_details.map((d, i) => (d.step != null ? d : { ...d, step: d.order ?? i + 1 }));
    const rows = term
      ? numbered.filter(
          (d) =>
            d.deployment.toLowerCase().includes(term) ||
            statusLabel(effectiveStepStatus(d, h.status)).toLowerCase().includes(term),
        )
      : numbered;

    const dir = stepSort.direction === "asc" ? 1 : -1;
    const compare = (a: StepDetail, b: StepDetail): number => {
      switch (stepSort.key) {
        // Sort the change column by its magnitude, not its rendered text.
        case "change": return (a.target_replicas - (a.current_replicas ?? 0)) - (b.target_replicas - (b.current_replicas ?? 0));
        case "duration": return (a.duration_seconds ?? 0) - (b.duration_seconds ?? 0);
        case "status": return effectiveStepStatus(a, h.status).localeCompare(effectiveStepStatus(b, h.status));
        case "deployment": return a.deployment.localeCompare(b.deployment);
        default: return (a.step ?? 0) - (b.step ?? 0);
      }
    };
    return [...rows].sort((a, b) => {
      const c = compare(a, b);
      return c !== 0 ? c * dir : (a.step ?? 0) - (b.step ?? 0);
    });
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
              const counts = h.step_details ? stepCounts(h.step_details, h.status) : null;
              const stepsCompleted = counts ? counts.completed : h.completed_count;
              const stepsRunning = counts ? counts.running : 0;
              const stepsFailed = counts ? counts.failed : h.failed_count;
              const stepsNotRun = counts ? counts.not_run : 0;
              const stepsDone = h.status === "running" ? stepsCompleted + stepsFailed : h.total_deployments;
              const runName = h.sequence_name ?? h.schedule_name;
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
                  <td className={gridStyles.cell}>
                    <span className="block">{operationLabel(h.operation)}</span>
                    {runName && <span className="block text-xs font-semibold text-gray-900" title={h.schedule_name && h.sequence_name ? `Schedule: ${h.schedule_name}` : undefined}>{runName}</span>}
                  </td>
                  <td className={gridStyles.cell}>
                    <StatusBadge status={h.status} size="md" />
                  </td>
                  <td className={gridStyles.centerCell}>
                    <div className="flex items-center gap-2" title={`${stepsCompleted} completed, ${stepsFailed} failed${stepsNotRun ? `, ${stepsNotRun} not run` : ""} of ${h.total_deployments}`}>
                      <div className="h-2 w-16 rounded-full bg-gray-200 overflow-hidden">
                        <div
                          className={`h-2 rounded-full transition-all duration-700 ${h.status === "running" ? "bg-gradient-to-r from-att-400 to-att-600" : h.status === "rolled_back" ? "bg-orange-500" : h.status === "failed" || stepsFailed > 0 ? "bg-red-500" : "bg-green-500"}`}
                          style={{ width: h.total_deployments > 0 ? `${Math.min(100, (stepsDone / h.total_deployments) * 100)}%` : "0%" }}
                        />
                      </div>
                      <span className="whitespace-nowrap text-xs text-gray-500">
                        {stepsCompleted}/{h.total_deployments}
                        {stepsFailed > 0 && <span className="ml-1 font-semibold text-red-600">· {stepsFailed} failed</span>}
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
                      {/* Summary + detail search */}
                      <div className="flex flex-wrap items-center gap-2">
                        {counts && (
                          <>
                            <span className="rounded-full bg-green-50 px-2 py-0.5 text-xs font-medium text-green-700 ring-1 ring-inset ring-green-200">{counts.completed} completed</span>
                            {counts.failed > 0 && <span className="rounded-full bg-red-50 px-2 py-0.5 text-xs font-medium text-red-700 ring-1 ring-inset ring-red-200">{counts.failed} failed</span>}
                            {counts.running > 0 && <span className="rounded-full bg-blue-50 px-2 py-0.5 text-xs font-medium text-blue-700 ring-1 ring-inset ring-blue-200">{counts.running} running</span>}
                            {counts.pending > 0 && <span className="rounded-full bg-gray-50 px-2 py-0.5 text-xs font-medium text-gray-600 ring-1 ring-inset ring-gray-200">{counts.pending} pending</span>}
                            {counts.not_run > 0 && <span className="rounded-full bg-gray-50 px-2 py-0.5 text-xs font-medium text-gray-600 ring-1 ring-inset ring-gray-200">{counts.not_run} not run</span>}
                            {counts.rolledBack > 0 && <span className="rounded-full bg-orange-50 px-2 py-0.5 text-xs font-medium text-orange-700 ring-1 ring-inset ring-orange-200">{counts.rolledBack} rolled back</span>}
                          </>
                        )}
                        <span className="text-xs text-gray-400">
                          {h.step_details ? getFilteredDetails(h).length : h.total_deployments} step{(h.step_details ? getFilteredDetails(h).length : h.total_deployments) !== 1 ? "s" : ""}
                          {h.initiated_by_email && <> · started by {h.initiated_by_email}</>}
                          {h.completed_at && <> · finished {new Date(h.completed_at).toLocaleString()}</>}
                        </span>
                        <input
                          type="text"
                          placeholder="Search steps..."
                          aria-label="Search steps"
                          value={detailSearch}
                          onChange={(e) => setDetailSearch(e.target.value)}
                          onClick={(e) => e.stopPropagation()}
                          className="ml-auto w-48 rounded-lg border border-gray-300 px-2 py-1 text-xs focus:border-att-400 focus:ring-1 focus:ring-att-100"
                        />
                      </div>
                      {h.error_message && (
                        <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800" role="alert">{h.error_message}</div>
                      )}
                      {h.step_details && h.step_details.length > 0 ? (
                        <div onClick={(e) => e.stopPropagation()}>
                          <ExecutionStepsTable
                            steps={getFilteredDetails(h)}
                            executionStatus={h.status}
                            sort={stepSort}
                            onSort={(key) => setStepSort(nextSortState(stepSort, key))}
                            onShowLog={(dep) => handleShowLog(h, dep)}
                            maxHeightClass="max-h-[26rem]"
                          />
                        </div>
                      ) : h.status === "running" ? (
                        <div className="rounded-lg border border-gray-200 bg-white p-4 text-center text-xs text-gray-400">
                          <svg className="mx-auto mb-2 h-5 w-5 animate-spin text-att-400" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" /></svg>
                          Waiting for deployment steps to complete — data will appear in real-time
                        </div>
                      ) : null}
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
