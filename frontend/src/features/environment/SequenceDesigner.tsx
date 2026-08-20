/**
 * SequenceDesigner – Drag-and-drop sequence builder for ordered startup/shutdown.
 *
 * Grid features (KeyVault-style):
 * - Search in available deployments list
 * - Search + page size picker + bottom pagination on sequence grid
 * - Proper column headers
 */

import React, { useState, useCallback, useEffect, useRef } from "react";
import type {
  EnvironmentSequence,
  EnvironmentScaleResult,
  SequenceCreateRequest,
  SequenceStep,
  StepDetail,
} from "../../services/environmentApi";
import { gridStyles, SortableHeader, type SortState, nextSortState } from "../../components/gridStyles";

interface Deployment {
  name: string;
  namespace: string;
  replicas: number;
  ready_replicas: number;
}

interface Props {
  sequences: EnvironmentSequence[];
  deployments: Deployment[];
  clusterId: string;
  namespace: string;
  onCreate: (data: SequenceCreateRequest) => Promise<void>;
  onUpdate: (id: number, data: Partial<SequenceCreateRequest>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  onExecuteStart: (sequenceId: number, replicaCount: number, dryRun: boolean) => Promise<EnvironmentScaleResult>;
  onExecuteStop: (sequenceId: number, dryRun: boolean) => Promise<EnvironmentScaleResult>;
  isLoading: boolean;
}

const PAGE_SIZES = [10, 20, 50];
const WAIT_CONDITIONS: { value: SequenceStep["wait_condition"]; label: string }[] = [
  { value: "pods_ready", label: "Wait Until Pods Ready" },
  { value: "deployment_available", label: "Wait Until Deployment Available" },
  { value: "health_endpoint", label: "Wait Until Health Endpoint Returns 200" },
  { value: "fixed_time", label: "Wait Fixed Time" },
  { value: "skip", label: "Skip Wait" },
];

const SequenceDesigner: React.FC<Props> = ({
  sequences,
  deployments,
  clusterId,
  namespace,
  onCreate,
  onUpdate,
  onDelete,
  onExecuteStart,
  onExecuteStop,
  isLoading,
}) => {
  const [showBuilder, setShowBuilder] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [seqName, setSeqName] = useState("");
  const [seqType, setSeqType] = useState<"startup" | "shutdown">("startup");
  const [rollback, setRollback] = useState(true);
  const [steps, setSteps] = useState<SequenceStep[]>([]);
  const [dragIdx, setDragIdx] = useState<number | null>(null);
  const [expandedSeq, setExpandedSeq] = useState<number | null>(null);

  // Execution tracking state
  const [executingSeq, setExecutingSeq] = useState<EnvironmentSequence | null>(null);
  const [execResult, setExecResult] = useState<EnvironmentScaleResult | null>(null);
  const [execElapsed, setExecElapsed] = useState(0);
  const [execRunning, setExecRunning] = useState(false);
  const [execLiveStep, setExecLiveStep] = useState(0);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const stepTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Builder deployment search
  const [builderSearch, setBuilderSearch] = useState("");

  // Sequence grid search + pagination + sort
  const [gridSearch, setGridSearch] = useState("");
  const [gridPage, setGridPage] = useState(1);
  const [gridPageSize, setGridPageSize] = useState(20);
  const [gridSort, setGridSort] = useState<SortState<string>>({ key: "name", direction: "asc" });

  const namespaceDeps = deployments.filter((d) => d.namespace === namespace);
  const availableDeployments = namespaceDeps
    .filter((d) => !steps.some((s) => s.deployment_name === d.name))
    .filter((d) => d.name.toLowerCase().includes(builderSearch.toLowerCase()));

  // Grid filtering + sorting
  const filteredSequences = sequences.filter(
    (s) =>
      s.name.toLowerCase().includes(gridSearch.toLowerCase()) ||
      s.namespace.toLowerCase().includes(gridSearch.toLowerCase()) ||
      s.sequence_type.toLowerCase().includes(gridSearch.toLowerCase()),
  );
  const sortedSequences = [...filteredSequences].sort((a, b) => {
    const aVal = String((a as unknown as Record<string, unknown>)[gridSort.key] ?? "");
    const bVal = String((b as unknown as Record<string, unknown>)[gridSort.key] ?? "");
    return gridSort.direction === "asc" ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
  });
  const gridTotalPages = Math.max(1, Math.ceil(sortedSequences.length / gridPageSize));
  const gridSafePage = Math.min(gridPage, gridTotalPages);
  const gridStart = sortedSequences.length === 0 ? 0 : (gridSafePage - 1) * gridPageSize + 1;
  const gridEnd = Math.min(gridSafePage * gridPageSize, sortedSequences.length);
  const paginatedSequences = sortedSequences.slice((gridSafePage - 1) * gridPageSize, gridSafePage * gridPageSize);

  const addStep = useCallback(
    (depName: string) => {
      const newStep: SequenceStep = {
        order: steps.length + 1, deployment_name: depName, replicas: seqType === "shutdown" ? 0 : 1,
        wait_condition: "pods_ready", timeout_seconds: 600, retry_count: 3, on_failure: "abort",
      };
      setSteps((prev) => [...prev, newStep]);
    },
    [steps.length, seqType],
  );

  const removeStep = useCallback((idx: number) => {
    setSteps((prev) => prev.filter((_, i) => i !== idx).map((s, i) => ({ ...s, order: i + 1 })));
  }, []);

  const updateStep = useCallback(
    (idx: number, updates: Partial<SequenceStep>) => {
      setSteps((prev) => prev.map((s, i) => (i === idx ? { ...s, ...updates } : s)));
    },
    [],
  );

  const handleDragStart = (idx: number) => setDragIdx(idx);

  const handleDrop = (targetIdx: number) => {
    if (dragIdx === null || dragIdx === targetIdx) return;
    setSteps((prev) => {
      const items = [...prev];
      const [moved] = items.splice(dragIdx, 1);
      items.splice(targetIdx, 0, moved);
      return items.map((s, i) => ({ ...s, order: i + 1 }));
    });
    setDragIdx(null);
  };

  const handleSave = async () => {
    if (editingId) {
      await onUpdate(editingId, {
        name: seqName,
        steps,
        rollback_on_failure: rollback,
      });
    } else {
      await onCreate({
        name: seqName, cluster_id: clusterId, namespace,
        sequence_type: seqType, steps, rollback_on_failure: rollback,
      });
    }
    setShowBuilder(false);
    setEditingId(null);
    setSteps([]);
    setSeqName("");
    setBuilderSearch("");
  };

  const handleEdit = (seq: EnvironmentSequence) => {
    setEditingId(seq.id);
    setSeqName(seq.name);
    setSeqType(seq.sequence_type);
    setRollback(seq.rollback_on_failure);
    setSteps(seq.steps.map((s, i) => ({
      order: s.order ?? i + 1,
      deployment_name: s.deployment_name,
      replicas: s.replicas ?? 1,
      wait_condition: s.wait_condition ?? "pods_ready",
      timeout_seconds: s.timeout_seconds ?? 600,
      retry_count: s.retry_count ?? 3,
      on_failure: s.on_failure ?? "abort",
    })));
    setShowBuilder(true);
    setBuilderSearch("");
  };

  const handleCancelBuilder = () => {
    setShowBuilder(false);
    setEditingId(null);
    setSteps([]);
    setSeqName("");
    setBuilderSearch("");
  };

  // ── Execution handlers with live tracking ──

  const startExecution = async (seq: EnvironmentSequence, mode: "start" | "stop") => {
    setExecutingSeq(seq);
    setExecResult(null);
    setExecElapsed(0);
    setExecRunning(true);
    setExecLiveStep(0);

    // Start elapsed timer
    const startTime = Date.now();
    timerRef.current = setInterval(() => {
      setExecElapsed(Math.floor((Date.now() - startTime) / 1000));
    }, 1000);

    // Simulate step progress (each step ~3-5s estimate)
    const totalSteps = seq.steps.length;
    let stepIdx = 0;
    stepTimerRef.current = setInterval(() => {
      stepIdx = Math.min(stepIdx + 1, totalSteps - 1);
      setExecLiveStep(stepIdx);
    }, 3000);

    try {
      let result: EnvironmentScaleResult;
      if (mode === "start") {
        result = await onExecuteStart(seq.id, 1, false);
      } else {
        result = await onExecuteStop(seq.id, false);
      }
      setExecResult(result);
      setExecLiveStep(totalSteps);
    } catch {
      // error is handled by parent toast
    } finally {
      setExecRunning(false);
      if (timerRef.current) clearInterval(timerRef.current);
      if (stepTimerRef.current) clearInterval(stepTimerRef.current);
      // Capture final elapsed
      setExecElapsed(Math.floor((Date.now() - startTime) / 1000));
    }
  };

  const closeExecution = () => {
    setExecutingSeq(null);
    setExecResult(null);
    setExecElapsed(0);
    setExecRunning(false);
    setExecLiveStep(0);
  };

  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      if (stepTimerRef.current) clearInterval(stepTimerRef.current);
    };
  }, []);

  const formatElapsed = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return m > 0 ? `${m}m ${s}s` : `${s}s`;
  };

  return (
    <div className="space-y-4">
      {/* ── Live Execution Panel ── */}
      {executingSeq && (
        <div className="rounded-xl border-2 border-att-200 bg-white p-5 space-y-4 shadow-sm">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {execRunning ? (
                <svg className="h-5 w-5 animate-spin text-att-500" viewBox="0 0 24 24" fill="none">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" />
                </svg>
              ) : execResult?.status === "completed" ? (
                <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" className="text-green-600"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg>
              ) : (
                <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" className="text-red-600"><circle cx="12" cy="12" r="10" /><path d="m15 9-6 6M9 9l6 6" /></svg>
              )}
              <h4 className="font-semibold text-gray-800">
                {execRunning ? "Executing" : "Execution Complete"}: <span className="text-att-600">{executingSeq.name}</span>
              </h4>
            </div>
            <div className="flex items-center gap-4">
              <div className="flex items-center gap-2 rounded-lg bg-gray-100 px-3 py-1.5">
                <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" className="text-gray-500"><circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" /></svg>
                <span className="font-mono text-sm font-semibold text-gray-700">{formatElapsed(execElapsed)}</span>
              </div>
              {!execRunning && (
                <button onClick={closeExecution} className="rounded-lg border border-gray-300 px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50">Close</button>
              )}
            </div>
          </div>

          {/* Summary cards */}
          {execResult && (
            <div className="grid grid-cols-5 gap-3">
              <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-center">
                <div className="text-lg font-bold text-gray-900">{execResult.total_deployments}</div>
                <div className="text-xs text-gray-500">Total Steps</div>
              </div>
              <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-center">
                <div className="text-lg font-bold text-green-700">{execResult.completed}</div>
                <div className="text-xs text-green-600">Completed</div>
              </div>
              <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-center">
                <div className="text-lg font-bold text-red-700">{execResult.failed}</div>
                <div className="text-xs text-red-600">Failed</div>
              </div>
              <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-center">
                <div className="text-lg font-bold text-yellow-700">{execResult.skipped}</div>
                <div className="text-xs text-yellow-600">Skipped</div>
              </div>
              <div className="rounded-lg border border-att-200 bg-att-50 p-3 text-center">
                <div className="text-lg font-bold text-att-700">{formatElapsed(execElapsed)}</div>
                <div className="text-xs text-att-600">Total Time</div>
              </div>
            </div>
          )}

          {/* Step-by-step progress */}
          <div className="space-y-1">
            <div className="flex justify-between text-xs text-gray-500 mb-1">
              <span>Step {Math.min(execLiveStep + 1, executingSeq.steps.length)} of {executingSeq.steps.length}</span>
              <span>{executingSeq.steps.length > 0 ? Math.min(Math.round(((execResult ? execResult.completed + execResult.skipped : execLiveStep) / executingSeq.steps.length) * 100), 100) : 0}%</span>
            </div>
            <div className="h-2.5 w-full overflow-hidden rounded-full bg-gray-200">
              <div
                className={`h-2.5 rounded-full transition-all duration-700 ${execResult ? (execResult.failed > 0 ? "bg-red-500" : "bg-green-500") : "bg-gradient-to-r from-att-400 to-att-600"}`}
                style={{ width: `${executingSeq.steps.length > 0 ? Math.min(((execResult ? execResult.completed + execResult.skipped : execLiveStep) / executingSeq.steps.length) * 100, 100) : 0}%` }}
              />
            </div>
          </div>

          {/* Step details table */}
          <div className="max-h-60 overflow-y-auto rounded-lg border border-gray-200">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 sticky top-0">
                <tr>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-gray-600 w-10">Step</th>
                  <th className="px-3 py-2 text-left text-xs font-semibold text-gray-600">Deployment</th>
                  <th className="px-3 py-2 text-center text-xs font-semibold text-gray-600">Replicas</th>
                  <th className="px-3 py-2 text-center text-xs font-semibold text-gray-600">Wait Condition</th>
                  <th className="px-3 py-2 text-center text-xs font-semibold text-gray-600">Status</th>
                </tr>
              </thead>
              <tbody>
                {executingSeq.steps.sort((a, b) => a.order - b.order).map((step, idx) => {
                  const detail = execResult?.details?.find((d: StepDetail) => d.deployment === step.deployment_name);
                  const stepStatus = detail?.status ?? (execRunning && idx <= execLiveStep ? (idx < execLiveStep ? "running" : "in_progress") : "pending");
                  return (
                    <tr key={idx} className="border-t border-gray-100">
                      <td className="px-3 py-2">
                        <span className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${
                          stepStatus === "completed" ? "bg-green-100 text-green-700"
                          : stepStatus === "failed" ? "bg-red-100 text-red-700"
                          : stepStatus === "in_progress" || stepStatus === "running" ? "bg-att-100 text-att-700 animate-pulse"
                          : "bg-gray-100 text-gray-500"
                        }`}>{step.order}</span>
                      </td>
                      <td className="px-3 py-2 font-mono text-xs">{step.deployment_name}</td>
                      <td className="px-3 py-2 text-center text-xs">{step.replicas}</td>
                      <td className="px-3 py-2 text-center text-xs text-gray-500">{step.wait_condition.replace(/_/g, " ")}</td>
                      <td className="px-3 py-2 text-center">
                        {stepStatus === "completed" && <span className="inline-flex items-center gap-1 text-xs font-medium text-green-600"><svg width="12" height="12" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12" /></svg>Done</span>}
                        {stepStatus === "failed" && <span className="inline-flex rounded-full bg-red-100 px-2 py-0.5 text-xs font-medium text-red-700">Failed</span>}
                        {stepStatus === "skipped" && <span className="inline-flex rounded-full bg-yellow-100 px-2 py-0.5 text-xs font-medium text-yellow-700">Skipped</span>}
                        {(stepStatus === "in_progress" || stepStatus === "running") && <span className="inline-flex items-center gap-1 text-xs font-medium text-att-600"><svg className="h-3 w-3 animate-spin" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" /></svg>Running</span>}
                        {stepStatus === "pending" && <span className="text-xs text-gray-400">Waiting</span>}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {execResult?.status === "completed" && (
            <div className="rounded-lg bg-green-50 border border-green-200 px-4 py-3 flex items-center gap-3">
              <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" className="text-green-600"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg>
              <span className="text-sm font-medium text-green-800">Sequence completed successfully in {formatElapsed(execElapsed)}</span>
            </div>
          )}
          {execResult && execResult.failed > 0 && (
            <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-3 flex items-center gap-3">
              <svg width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" className="text-red-600"><circle cx="12" cy="12" r="10" /><path d="m15 9-6 6M9 9l6 6" /></svg>
              <span className="text-sm font-medium text-red-800">Sequence {execResult.status} — {execResult.failed} step(s) failed after {formatElapsed(execElapsed)}</span>
            </div>
          )}
        </div>
      )}

      {/* Builder */}
      {showBuilder && (
        <div className="rounded-xl border border-att-200 bg-att-50/30 p-5 space-y-5">
          <h4 className="font-semibold text-gray-800">{editingId ? "Edit Sequence" : "Sequence Designer"}</h4>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <label className="text-xs font-semibold text-gray-600">Sequence Name</label>
              <input value={seqName} onChange={(e) => setSeqName(e.target.value)} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" placeholder="e.g. Dev Startup Order" />
            </div>
            <div>
              <label className="text-xs font-semibold text-gray-600">Sequence Type</label>
              <select value={seqType} onChange={(e) => { const t = e.target.value as "startup" | "shutdown"; setSeqType(t); setSteps((prev) => prev.map((s) => ({ ...s, replicas: t === "shutdown" ? 0 : Math.max(s.replicas, 1) }))); }} disabled={!!editingId} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm disabled:opacity-60">
                <option value="startup">Startup</option>
                <option value="shutdown">Shutdown</option>
              </select>
            </div>
            <label className="flex items-end gap-2 pb-2 text-sm">
              <input type="checkbox" checked={rollback} onChange={(e) => setRollback(e.target.checked)} className="text-att-500" />
              Rollback on Failure
            </label>
          </div>

          <div className="grid grid-cols-2 gap-6">
            {/* Available Deployments with search */}
            <div>
              <h5 className="mb-2 text-xs font-semibold uppercase text-gray-500">Available Deployments</h5>
              <input
                type="text"
                placeholder="Search deployments..."
                value={builderSearch}
                onChange={(e) => setBuilderSearch(e.target.value)}
                className="mb-2 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-att-400 focus:ring-2 focus:ring-att-100"
              />
              <div className="max-h-64 overflow-y-auto rounded-lg border border-gray-200 bg-white">
                {availableDeployments.length === 0 ? (
                  <p className="p-4 text-center text-sm text-gray-400">
                    {builderSearch ? "No deployments match search" : "All deployments added"}
                  </p>
                ) : (
                  availableDeployments.map((dep) => (
                    <button
                      key={dep.name}
                      onClick={() => addStep(dep.name)}
                      className="flex w-full items-center justify-between border-b border-gray-100 px-4 py-2.5 text-left text-sm hover:bg-att-50 last:border-0"
                    >
                      <span className="font-mono text-xs text-gray-700">{dep.name}</span>
                      <span className="flex items-center gap-2">
                        <span className={`text-xs ${dep.replicas > 0 ? "text-green-600" : "text-gray-400"}`}>{dep.ready_replicas}/{dep.replicas}</span>
                        <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" className="text-att-500"><path d="M12 5v14M5 12h14" /></svg>
                      </span>
                    </button>
                  ))
                )}
              </div>
            </div>

            {/* Execution Order */}
            <div>
              <h5 className="mb-2 text-xs font-semibold uppercase text-gray-500">Execution Order (drag to reorder)</h5>
              <div className="mb-2 text-xs text-gray-400">{steps.length} step{steps.length !== 1 ? "s" : ""} configured</div>
              <div className="max-h-64 overflow-y-auto rounded-lg border border-gray-200 bg-white">
                {steps.length === 0 ? (
                  <p className="p-4 text-center text-sm text-gray-400">Add deployments from the left</p>
                ) : (
                  steps.map((step, idx) => (
                    <div
                      key={step.deployment_name}
                      draggable
                      onDragStart={() => handleDragStart(idx)}
                      onDragOver={(e) => e.preventDefault()}
                      onDrop={() => handleDrop(idx)}
                      className={`flex items-center gap-2 border-b border-gray-100 px-3 py-2 text-sm last:border-0 ${dragIdx === idx ? "bg-att-50" : "hover:bg-gray-50"}`}
                    >
                      <span className="cursor-grab text-gray-400">&#9776;</span>
                      <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-att-100 text-xs font-bold text-att-700">{step.order}</span>
                      <span className="flex-1 font-mono text-xs truncate">{step.deployment_name}</span>
                      <input
                        type="number"
                        min={seqType === "shutdown" ? 0 : 1}
                        max={100}
                        value={step.replicas}
                        onChange={(e) => updateStep(idx, { replicas: Math.max(seqType === "shutdown" ? 0 : 1, Math.min(100, parseInt(e.target.value) || 0)) })}
                        className="w-14 rounded border border-gray-200 px-1.5 py-1 text-xs text-center"
                        title="Replicas"
                      />
                      <select value={step.wait_condition} onChange={(e) => updateStep(idx, { wait_condition: e.target.value as SequenceStep["wait_condition"] })} className="rounded border border-gray-200 px-2 py-1 text-xs">
                        {WAIT_CONDITIONS.map((w) => <option key={w.value} value={w.value}>{w.label}</option>)}
                      </select>
                      <select value={step.on_failure} onChange={(e) => updateStep(idx, { on_failure: e.target.value as "abort" | "continue" })} className="rounded border border-gray-200 px-2 py-1 text-xs">
                        <option value="abort">Abort on Failure</option>
                        <option value="continue">Continue on Failure</option>
                      </select>
                      <button onClick={() => removeStep(idx)} className="text-red-400 hover:text-red-600">
                        <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M18 6 6 18M6 6l12 12" /></svg>
                      </button>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>

          <div className="flex justify-end gap-2">
            <button onClick={handleCancelBuilder} className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">Cancel</button>
            <button onClick={handleSave} disabled={!seqName || steps.length === 0 || isLoading} className="rounded-lg bg-att-500 px-4 py-2 text-sm font-medium text-white hover:bg-att-600 disabled:opacity-50">{editingId ? "Update Sequence" : "Save Sequence"}</button>
          </div>
        </div>
      )}

      {/* Sequences grid */}
      <div className={gridStyles.shell}>
        {/* Toolbar */}
        <div className={gridStyles.panelHeader}>
          <div className="flex flex-wrap items-center gap-3">
            <span className={gridStyles.countBadge}>{filteredSequences.length} sequence{filteredSequences.length !== 1 ? "s" : ""}</span>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-3">
            <input type="text" placeholder="Search sequences..." value={gridSearch} onChange={(e) => { setGridSearch(e.target.value); setGridPage(1); }} className={gridStyles.toolbarInput} />
            <select value={gridPageSize} onChange={(e) => { setGridPageSize(Number(e.target.value)); setGridPage(1); }} className="rounded-lg border border-att-200 bg-white px-2 py-2 text-sm text-gray-700">
              {PAGE_SIZES.map((n) => <option key={n} value={n}>{n} / page</option>)}
            </select>
            <button onClick={() => { setEditingId(null); setShowBuilder(!showBuilder); setSteps([]); setSeqName(""); }} className="rounded-lg bg-att-500 px-4 py-2 text-sm font-medium text-white hover:bg-att-600">+ Create Sequence</button>
          </div>
        </div>
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              <th className={gridStyles.headerCell}><SortableHeader label="Sequence Name" active={gridSort.key === "name"} direction={gridSort.direction} onClick={() => setGridSort(nextSortState(gridSort, "name"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Sequence Type" active={gridSort.key === "sequence_type"} direction={gridSort.direction} onClick={() => setGridSort(nextSortState(gridSort, "sequence_type"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Namespace" active={gridSort.key === "namespace"} direction={gridSort.direction} onClick={() => setGridSort(nextSortState(gridSort, "namespace"))} /></th>
              <th className={gridStyles.headerCellCenter}>Steps</th>
              <th className={gridStyles.headerCellCenter}>Rollback on Failure</th>
              <th className={gridStyles.headerCell}><SortableHeader label="Created Date" active={gridSort.key === "created_at"} direction={gridSort.direction} onClick={() => setGridSort(nextSortState(gridSort, "created_at"))} /></th>
              <th className={gridStyles.headerCellCenter}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedSequences.map((seq) => (
              <React.Fragment key={seq.id}>
                <tr className={gridStyles.row}>
                  <td className={gridStyles.strongCell}>
                    <button onClick={() => setExpandedSeq(expandedSeq === seq.id ? null : seq.id)} className="flex items-center gap-1 text-left hover:text-att-600">
                      <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" className={`transition-transform ${expandedSeq === seq.id ? "rotate-90" : ""}`}><path d="m9 18 6-6-6-6" /></svg>
                      {seq.name}
                    </button>
                  </td>
                  <td className={gridStyles.cell}>
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${seq.sequence_type === "startup" ? "bg-green-100 text-green-700" : "bg-orange-100 text-orange-700"}`}>
                      {seq.sequence_type === "startup" ? "Startup" : "Shutdown"}
                    </span>
                  </td>
                  <td className={gridStyles.cell}>{seq.namespace}</td>
                  <td className={gridStyles.centerCell}>{seq.steps.length}</td>
                  <td className={gridStyles.centerCell}>
                    {seq.rollback_on_failure ? <span className="text-green-600 font-medium">Yes</span> : <span className="text-gray-400">No</span>}
                  </td>
                  <td className={gridStyles.cell}>{seq.created_at ? new Date(seq.created_at).toLocaleDateString() : "-"}</td>
                  <td className={gridStyles.centerCell}>
                    <div className="flex items-center justify-center gap-1">
                      {seq.sequence_type === "startup" ? (
                        <button onClick={() => startExecution(seq, "start")} disabled={isLoading || execRunning} className="rounded bg-green-500 px-2.5 py-1 text-xs font-medium text-white hover:bg-green-600 disabled:opacity-50" title="Run Startup Sequence">Start</button>
                      ) : (
                        <button onClick={() => startExecution(seq, "stop")} disabled={isLoading || execRunning} className="rounded bg-orange-500 px-2.5 py-1 text-xs font-medium text-white hover:bg-orange-600 disabled:opacity-50" title="Run Shutdown Sequence">Stop</button>
                      )}
                      <button onClick={() => handleEdit(seq)} className="rounded p-1 text-blue-500 hover:bg-blue-50" title="Edit Sequence">
                        <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg>
                      </button>
                      <button onClick={() => onDelete(seq.id)} className="rounded p-1 text-red-500 hover:bg-red-50" title="Delete Sequence">
                        <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
                      </button>
                    </div>
                  </td>
                </tr>
                {expandedSeq === seq.id && (
                  <tr>
                    <td colSpan={7} className="bg-gray-50 px-6 py-3">
                      <div className="text-xs font-semibold text-gray-600 mb-2">{seq.steps.length} deployment step{seq.steps.length !== 1 ? "s" : ""}</div>
                      <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
                        <table className="w-full text-xs">
                          <thead className="bg-gray-50">
                            <tr>
                              <th className="px-3 py-1.5 text-left font-semibold text-gray-600 w-10">Step</th>
                              <th className="px-3 py-1.5 text-left font-semibold text-gray-600">Deployment Name</th>
                              <th className="px-3 py-1.5 text-center font-semibold text-gray-600">Replicas</th>
                              <th className="px-3 py-1.5 text-center font-semibold text-gray-600">Wait Condition</th>
                              <th className="px-3 py-1.5 text-center font-semibold text-gray-600">Timeout</th>
                              <th className="px-3 py-1.5 text-center font-semibold text-gray-600">On Failure</th>
                            </tr>
                          </thead>
                          <tbody>
                            {seq.steps.sort((a, b) => a.order - b.order).map((step, idx) => (
                              <tr key={idx} className="border-t border-gray-100">
                                <td className="px-3 py-1.5"><span className="flex h-5 w-5 items-center justify-center rounded-full bg-att-100 text-xs font-bold text-att-700">{step.order}</span></td>
                                <td className="px-3 py-1.5 font-mono">{step.deployment_name}</td>
                                <td className="px-3 py-1.5 text-center">{step.replicas}</td>
                                <td className="px-3 py-1.5 text-center text-gray-500">{step.wait_condition.replace(/_/g, " ")}</td>
                                <td className="px-3 py-1.5 text-center text-gray-500">{step.timeout_seconds}s</td>
                                <td className="px-3 py-1.5 text-center"><span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${step.on_failure === "abort" ? "bg-red-50 text-red-600" : "bg-yellow-50 text-yellow-600"}`}>{step.on_failure}</span></td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </td>
                  </tr>
                )}
              </React.Fragment>
            ))}
            {paginatedSequences.length === 0 && (
              <tr><td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-400">No sequences found</td></tr>
            )}
          </tbody>
        </table>
        {/* Pagination — KeyVault style */}
        <div className={gridStyles.pager}>
          <span className="text-gray-600">Showing {gridStart}-{gridEnd} of {sortedSequences.length}</span>
          <div className="flex items-center gap-2">
            <button onClick={() => setGridPage(1)} disabled={gridSafePage <= 1} className={gridStyles.pagerButton}>&laquo;</button>
            <button onClick={() => setGridPage(Math.max(1, gridSafePage - 1))} disabled={gridSafePage <= 1} className={gridStyles.pagerButton}>Previous</button>
            <span className="text-gray-600">Page {gridSafePage} of {gridTotalPages}</span>
            <button onClick={() => setGridPage(Math.min(gridTotalPages, gridSafePage + 1))} disabled={gridSafePage >= gridTotalPages} className={gridStyles.pagerButton}>Next</button>
            <button onClick={() => setGridPage(gridTotalPages)} disabled={gridSafePage >= gridTotalPages} className={gridStyles.pagerButton}>&raquo;</button>
          </div>
        </div>
      </div>
    </div>
  );
};

export default SequenceDesigner;
