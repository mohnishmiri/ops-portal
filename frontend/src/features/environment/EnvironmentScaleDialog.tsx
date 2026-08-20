/**
 * EnvironmentScaleDialog – Modal dialog for manual environment scale up/down.
 *
 * Features:
 * - Search in deployment selection list with select-all
 * - Live animated progress indicator during scaling
 * - Search + pagination in results detail table (KeyVault-style)
 */

import React, { useState, useEffect, useRef } from "react";
import { gridStyles } from "../../components/gridStyles";
import { useCachedDeployments } from "../../services/aksApi";
import type { EnvironmentScaleRequest, EnvironmentScaleResult, StepDetail } from "../../services/environmentApi";

interface Props {
  open: boolean;
  onClose: () => void;
  clusterId: string;
  namespaces: string[];
  onScale: (request: EnvironmentScaleRequest) => Promise<EnvironmentScaleResult>;
  isScaling: boolean;
}

const PAGE_SIZES = [10, 20, 50];

const EnvironmentScaleDialog: React.FC<Props> = ({
  open,
  onClose,
  clusterId,
  namespaces,
  onScale,
  isScaling,
}) => {
  const [scope, setScope] = useState<"namespace" | "selected">("namespace");
  const [namespace, setNamespace] = useState(namespaces[0] || "default");
  const [operation, setOperation] = useState<"scale_up" | "scale_down">("scale_up");
  const [replicaCount, setReplicaCount] = useState(1);
  const [customReplica, setCustomReplica] = useState(false);
  const [selectedDeployments, setSelectedDeployments] = useState<string[]>([]);
  const [dryRun, setDryRun] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [result, setResult] = useState<EnvironmentScaleResult | null>(null);

  // Search in deployment picker
  const [depSearch, setDepSearch] = useState("");
  // Search in result details
  const [resultSearch, setResultSearch] = useState("");
  const [resultPage, setResultPage] = useState(1);
  const [resultPageSize, setResultPageSize] = useState(20);

  // Live progress tracking
  const [liveProgress, setLiveProgress] = useState(0);
  const progressTimer = useRef<ReturnType<typeof setInterval> | null>(null);

  // Deployments are fetched for the dialog's own selected namespace so switching
  // the namespace here always loads the matching deployment list.
  const { data: deploymentsData } = useCachedDeployments(clusterId, namespace, open);
  const deployments = deploymentsData?.deployments ?? [];
  const filteredDeployments = deployments.filter((d) => d.namespace === namespace);
  const searchedDeployments = filteredDeployments.filter((d) =>
    d.name.toLowerCase().includes(depSearch.toLowerCase()),
  );

  useEffect(() => {
    if (isScaling && !result) {
      const total = scope === "selected" ? selectedDeployments.length : filteredDeployments.length;
      setLiveProgress(0);
      progressTimer.current = setInterval(() => {
        setLiveProgress((prev) => Math.min(prev + 1, total - 1));
      }, 800);
    } else {
      if (progressTimer.current) {
        clearInterval(progressTimer.current);
        progressTimer.current = null;
      }
    }
    return () => {
      if (progressTimer.current) clearInterval(progressTimer.current);
    };
  }, [isScaling, result, scope, selectedDeployments.length, filteredDeployments.length]);

  const handleToggleDeployment = (name: string) => {
    setSelectedDeployments((prev) =>
      prev.includes(name) ? prev.filter((n) => n !== name) : [...prev, name],
    );
  };

  const handleSelectAll = () => {
    const visibleNames = searchedDeployments.map((d) => d.name);
    const allSelected = visibleNames.every((n) => selectedDeployments.includes(n));
    if (allSelected) {
      setSelectedDeployments((prev) => prev.filter((n) => !visibleNames.includes(n)));
    } else {
      setSelectedDeployments((prev) => [...new Set([...prev, ...visibleNames])]);
    }
  };

  const handleExecute = async () => {
    const request: EnvironmentScaleRequest = {
      cluster_id: clusterId,
      namespace,
      operation,
      scope,
      deployment_names: scope === "selected" ? selectedDeployments : undefined,
      replica_count: operation === "scale_down" ? 0 : replicaCount,
      dry_run: dryRun,
    };

    try {
      const r = await onScale(request);
      setResult(r);
      setShowConfirm(false);
      setResultPage(1);
    } catch {
      // handled by parent
    }
  };

  const handleSubmit = () => {
    if (operation === "scale_down" && !dryRun) {
      setShowConfirm(true);
    } else {
      handleExecute();
    }
  };

  // Result pagination
  const resultDetails = (result?.details ?? []).filter((d) =>
    d.deployment.toLowerCase().includes(resultSearch.toLowerCase()) ||
    d.status.toLowerCase().includes(resultSearch.toLowerCase()),
  );
  const resultTotalPages = Math.max(1, Math.ceil(resultDetails.length / resultPageSize));
  const resultSafePage = Math.min(resultPage, resultTotalPages);
  const resultStart = resultDetails.length === 0 ? 0 : (resultSafePage - 1) * resultPageSize + 1;
  const resultEnd = Math.min(resultSafePage * resultPageSize, resultDetails.length);
  const paginatedResults = resultDetails.slice((resultSafePage - 1) * resultPageSize, resultSafePage * resultPageSize);

  if (!open) return null;

  const totalTarget = scope === "selected" ? selectedDeployments.length : filteredDeployments.length;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-3xl rounded-xl bg-white shadow-2xl">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-gray-200 px-6 py-4">
          <div>
            <h2 className="text-xl font-bold text-gray-900">Environment Scale</h2>
            <p className="mt-0.5 text-xs text-gray-500">Scale deployments up or down across a namespace</p>
          </div>
          <button onClick={onClose} className="rounded-lg p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600">
            <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24">
              <path d="M18 6 6 18M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="max-h-[75vh] overflow-y-auto px-6 py-4 space-y-5">
          {/* Live scaling progress */}
          {isScaling && !result && (
            <div className="rounded-xl border-2 border-att-200 bg-att-50/50 p-5 space-y-4">
              <div className="flex items-center gap-3">
                <svg className="h-5 w-5 animate-spin text-att-500" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                </svg>
                <span className="font-semibold text-att-700">
                  Scaling {operation === "scale_down" ? "Down" : "Up"} in Progress...
                </span>
              </div>
              <div className="grid grid-cols-3 gap-3 text-center">
                <div className="rounded-lg bg-white p-3 shadow-sm">
                  <div className="text-xl font-bold text-gray-900">{totalTarget}</div>
                  <div className="text-xs text-gray-500">Total Deployments</div>
                </div>
                <div className="rounded-lg bg-white p-3 shadow-sm">
                  <div className="text-xl font-bold text-green-600">{Math.min(liveProgress, totalTarget)}</div>
                  <div className="text-xs text-green-600">Processing</div>
                </div>
                <div className="rounded-lg bg-white p-3 shadow-sm">
                  <div className="text-xl font-bold text-att-600">{Math.max(0, totalTarget - liveProgress)}</div>
                  <div className="text-xs text-gray-500">Remaining</div>
                </div>
              </div>
              <div className="space-y-1">
                <div className="flex justify-between text-xs text-gray-500">
                  <span>Progress</span>
                  <span>{totalTarget > 0 ? Math.min(Math.round((liveProgress / totalTarget) * 100), 99) : 0}%</span>
                </div>
                <div className="h-3 w-full overflow-hidden rounded-full bg-gray-200">
                  <div
                    className="h-3 rounded-full bg-gradient-to-r from-att-400 to-att-600 transition-all duration-500"
                    style={{ width: totalTarget > 0 ? `${Math.min((liveProgress / totalTarget) * 100, 99)}%` : "0%" }}
                  />
                </div>
              </div>
              <p className="text-xs text-gray-500 italic">Please wait while deployments are being scaled. Do not close this dialog.</p>
            </div>
          )}

          {/* Confirmation overlay */}
          {showConfirm && !isScaling && (
            <div className="rounded-xl border-2 border-red-300 bg-red-50 p-5 space-y-3">
              <div className="flex items-center gap-2">
                <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" className="text-red-600">
                  <path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0zM12 9v4M12 17h.01" />
                </svg>
                <p className="text-lg font-semibold text-red-800">Confirm Scale Down</p>
              </div>
              <div className="text-sm text-red-700 space-y-1.5">
                <p>Namespace: <span className="font-mono font-semibold">{namespace}</span></p>
                <p>Total Deployments: <span className="font-semibold">{totalTarget}</span></p>
                <p className="rounded bg-red-100 px-2 py-1 text-red-700 font-medium">
                  This will set all replicas to 0 and may make the environment unavailable.
                </p>
              </div>
              <div className="flex gap-2 pt-1">
                <button onClick={handleExecute} disabled={isScaling} className="rounded-lg bg-red-600 px-5 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50">
                  Yes, Proceed
                </button>
                <button onClick={() => setShowConfirm(false)} className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">
                  Cancel
                </button>
              </div>
            </div>
          )}

          {/* Result display */}
          {result && !isScaling && (
            <div className="space-y-4">
              <div className="flex items-center gap-3">
                {result.status === "completed" || result.status === "dry_run" ? (
                  <svg width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" className="text-green-600"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg>
                ) : (
                  <svg width="24" height="24" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" className="text-red-600"><circle cx="12" cy="12" r="10" /><path d="m15 9-6 6M9 9l6 6" /></svg>
                )}
                <span className={`inline-flex rounded-full px-3 py-1 text-sm font-semibold ${result.status === "completed" || result.status === "dry_run" ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"}`}>
                  {result.status === "dry_run" ? "Dry Run Complete" : result.status === "completed" ? "Scaling Completed" : "Scaling Failed"}
                </span>
              </div>

              <div className="grid grid-cols-4 gap-3">
                <div className="rounded-lg border border-gray-200 bg-white p-3 text-center shadow-sm">
                  <div className="text-xl font-bold text-gray-900">{result.total_deployments}</div>
                  <div className="text-xs font-medium text-gray-500">Total</div>
                </div>
                <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-center shadow-sm">
                  <div className="text-xl font-bold text-green-700">{result.completed}</div>
                  <div className="text-xs font-medium text-green-600">Completed</div>
                </div>
                <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-center shadow-sm">
                  <div className="text-xl font-bold text-red-700">{result.failed}</div>
                  <div className="text-xs font-medium text-red-600">Failed</div>
                </div>
                <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-center shadow-sm">
                  <div className="text-xl font-bold text-yellow-700">{result.skipped}</div>
                  <div className="text-xs font-medium text-yellow-600">Skipped</div>
                </div>
              </div>

              <div className="h-3 w-full overflow-hidden rounded-full bg-gray-200">
                <div className="h-3 rounded-full bg-gradient-to-r from-green-400 to-green-600" style={{ width: result.total_deployments > 0 ? `${((result.completed + result.skipped) / result.total_deployments) * 100}%` : "0%" }} />
              </div>

              {/* Result details grid with search + pagination */}
              <div className={gridStyles.shell}>
                <div className={gridStyles.panelHeader}>
                  <span className={gridStyles.countBadge}>{resultDetails.length} deployment{resultDetails.length !== 1 ? "s" : ""}</span>
                  <div className="ml-auto flex items-center gap-3">
                    <input type="text" placeholder="Search deployments..." value={resultSearch} onChange={(e) => { setResultSearch(e.target.value); setResultPage(1); }} className={gridStyles.toolbarInput} />
                    <select value={resultPageSize} onChange={(e) => { setResultPageSize(Number(e.target.value)); setResultPage(1); }} className="rounded-lg border border-att-200 bg-white px-2 py-2 text-sm text-gray-700">
                      {PAGE_SIZES.map((n) => <option key={n} value={n}>{n} / page</option>)}
                    </select>
                  </div>
                </div>
                <table className={gridStyles.table}>
                  <thead className={gridStyles.head}>
                    <tr>
                      <th className={gridStyles.headerCell}>Deployment Name</th>
                      <th className={gridStyles.headerCellCenter}>Current Replicas</th>
                      <th className={gridStyles.headerCellCenter}>Target Replicas</th>
                      <th className={gridStyles.headerCellCenter}>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {paginatedResults.map((d: StepDetail, i: number) => (
                      <tr key={i} className={gridStyles.row}>
                        <td className={gridStyles.strongCell}>{d.deployment}</td>
                        <td className={gridStyles.centerCell}>{d.current_replicas ?? "-"}</td>
                        <td className={gridStyles.centerCell}>{d.target_replicas}</td>
                        <td className={gridStyles.centerCell}>
                          <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${d.status === "completed" ? "bg-green-100 text-green-700" : d.status === "failed" ? "bg-red-100 text-red-700" : d.status === "skipped" ? "bg-yellow-100 text-yellow-700" : d.status === "dry_run" ? "bg-purple-100 text-purple-700" : "bg-blue-100 text-blue-700"}`}>
                            {d.status === "dry_run" ? "Preview" : d.status}
                          </span>
                        </td>
                      </tr>
                    ))}
                    {paginatedResults.length === 0 && (
                      <tr><td colSpan={4} className="px-4 py-6 text-center text-sm text-gray-400">No matching deployments</td></tr>
                    )}
                  </tbody>
                </table>
                <div className={gridStyles.pager}>
                  <span className="text-gray-600">Showing {resultStart}-{resultEnd} of {resultDetails.length}</span>
                  <div className="flex items-center gap-2">
                    <button onClick={() => setResultPage(1)} disabled={resultSafePage <= 1} className={gridStyles.pagerButton}>&laquo;</button>
                    <button onClick={() => setResultPage(Math.max(1, resultSafePage - 1))} disabled={resultSafePage <= 1} className={gridStyles.pagerButton}>Previous</button>
                    <span className="text-gray-600">Page {resultSafePage} of {resultTotalPages}</span>
                    <button onClick={() => setResultPage(Math.min(resultTotalPages, resultSafePage + 1))} disabled={resultSafePage >= resultTotalPages} className={gridStyles.pagerButton}>Next</button>
                    <button onClick={() => setResultPage(resultTotalPages)} disabled={resultSafePage >= resultTotalPages} className={gridStyles.pagerButton}>&raquo;</button>
                  </div>
                </div>
              </div>

              <button onClick={() => { setResult(null); onClose(); }} className="w-full rounded-lg bg-att-500 px-4 py-2.5 text-sm font-medium text-white hover:bg-att-600">Done</button>
            </div>
          )}

          {/* Scale form */}
          {!result && !showConfirm && !isScaling && (
            <>
              <div>
                <label className="text-sm font-semibold text-gray-700">Scale Scope</label>
                <div className="mt-2 flex gap-4">
                  <label className="flex items-center gap-2 cursor-pointer rounded-lg border border-gray-200 px-4 py-2.5 text-sm hover:bg-gray-50">
                    <input type="radio" checked={scope === "namespace"} onChange={() => setScope("namespace")} className="text-att-500 focus:ring-att-400" />
                    Entire Namespace
                  </label>
                  <label className="flex items-center gap-2 cursor-pointer rounded-lg border border-gray-200 px-4 py-2.5 text-sm hover:bg-gray-50">
                    <input type="radio" checked={scope === "selected"} onChange={() => setScope("selected")} className="text-att-500 focus:ring-att-400" />
                    Selected Deployments
                  </label>
                </div>
              </div>

              <div>
                <label className="text-sm font-semibold text-gray-700">Namespace</label>
                <select value={namespace} onChange={(e) => { setNamespace(e.target.value); setSelectedDeployments([]); setDepSearch(""); }} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-att-400 focus:ring-2 focus:ring-att-100">
                  {namespaces.map((ns) => <option key={ns} value={ns}>{ns}</option>)}
                </select>
              </div>

              {scope === "selected" && (
                <div>
                  <div className="flex items-center justify-between">
                    <label className="text-sm font-semibold text-gray-700">Select Deployments ({selectedDeployments.length} of {filteredDeployments.length} selected)</label>
                    <button onClick={handleSelectAll} className="text-xs font-medium text-att-600 hover:text-att-700">
                      {searchedDeployments.length > 0 && searchedDeployments.every((d) => selectedDeployments.includes(d.name)) ? "Deselect All" : "Select All Visible"}
                    </button>
                  </div>
                  <input type="text" placeholder="Search deployments..." value={depSearch} onChange={(e) => setDepSearch(e.target.value)} className="mt-2 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-att-400 focus:ring-2 focus:ring-att-100" />
                  <div className="mt-2 max-h-48 overflow-y-auto rounded-lg border border-gray-200">
                    {searchedDeployments.length === 0 ? (
                      <p className="p-4 text-center text-sm text-gray-400">No deployments match search</p>
                    ) : (
                      searchedDeployments.map((dep) => (
                        <label key={dep.name} className="flex items-center gap-2 border-b border-gray-100 px-3 py-2 text-sm hover:bg-gray-50 last:border-0 cursor-pointer">
                          <input type="checkbox" checked={selectedDeployments.includes(dep.name)} onChange={() => handleToggleDeployment(dep.name)} className="text-att-500 focus:ring-att-400" />
                          <span className="flex-1 font-mono text-xs">{dep.name}</span>
                          <span className={`text-xs font-medium ${dep.ready_replicas >= dep.replicas && dep.replicas > 0 ? "text-green-600" : dep.replicas === 0 ? "text-gray-400" : "text-yellow-600"}`}>
                            {dep.ready_replicas}/{dep.replicas}
                          </span>
                        </label>
                      ))
                    )}
                  </div>
                </div>
              )}

              <div>
                <label className="text-sm font-semibold text-gray-700">Scale Action</label>
                <div className="mt-2 flex gap-2">
                  <button onClick={() => setOperation("scale_up")} className={`flex-1 rounded-lg px-4 py-2.5 text-sm font-medium transition ${operation === "scale_up" ? "bg-green-600 text-white shadow-sm" : "border border-gray-300 text-gray-700 hover:bg-gray-50"}`}>
                    Scale Up Environment
                  </button>
                  <button onClick={() => setOperation("scale_down")} className={`flex-1 rounded-lg px-4 py-2.5 text-sm font-medium transition ${operation === "scale_down" ? "bg-red-600 text-white shadow-sm" : "border border-gray-300 text-gray-700 hover:bg-gray-50"}`}>
                    Scale Down Environment
                  </button>
                </div>
              </div>

              {operation === "scale_up" && (
                <div>
                  <label className="text-sm font-semibold text-gray-700">Replica Count</label>
                  <div className="mt-2 flex flex-wrap gap-2">
                    {[1, 2, 3, 5].map((n) => (
                      <button key={n} onClick={() => { setReplicaCount(n); setCustomReplica(false); }} className={`rounded-lg px-4 py-2 text-sm font-medium transition ${!customReplica && replicaCount === n ? "bg-att-500 text-white" : "border border-gray-300 text-gray-700 hover:bg-gray-50"}`}>{n}</button>
                    ))}
                    <button onClick={() => setCustomReplica(true)} className={`rounded-lg px-4 py-2 text-sm font-medium transition ${customReplica ? "bg-att-500 text-white" : "border border-gray-300 text-gray-700 hover:bg-gray-50"}`}>Custom</button>
                  </div>
                  {customReplica && (
                    <input type="number" min={1} max={100} value={replicaCount} onChange={(e) => setReplicaCount(Math.max(1, Math.min(100, parseInt(e.target.value) || 1)))} className="mt-2 w-24 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-att-400 focus:ring-2 focus:ring-att-100" />
                  )}
                </div>
              )}

              <label className="flex items-center gap-2 text-sm cursor-pointer">
                <input type="checkbox" checked={dryRun} onChange={(e) => setDryRun(e.target.checked)} className="text-att-500 focus:ring-att-400" />
                Dry Run (preview changes without executing)
              </label>

              <button onClick={handleSubmit} disabled={isScaling || (scope === "selected" && selectedDeployments.length === 0)} className="w-full rounded-lg bg-att-500 px-4 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-att-600 disabled:opacity-50">
                {operation === "scale_down" ? "Scale Down" : "Scale Up"} ({totalTarget} deployments)
              </button>
            </>
          )}
        </div>
      </div>
    </div>
  );
};

export default EnvironmentScaleDialog;
