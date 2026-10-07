/**
 * SequenceDesigner – builds and runs ordered startup/shutdown sequences.
 *
 * - Builder: pick deployments (the same one may be added again to scale it
 *   further later), reorder by drag or arrows, set replicas / wait / failure
 *   behaviour per step, with validation before save.
 * - Runs are confirmed against a plan of what will change, then execute on the
 *   server; the live panel follows the real execution record.
 * - Grid (KeyVault-style): search, sort, page size, bottom pagination.
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type {
  EnvironmentSchedule,
  EnvironmentScaleResult,
  EnvironmentSequence,
  ExecutionHistory,
  SequenceCreateRequest,
  SequenceStep,
} from "../../services/environmentApi";
import { gridStyles, SortableHeader, type SortState, nextSortState } from "../../components/gridStyles";
import { StatusBadge, apiErrorMessage, waitSummary } from "./executionStatus";
import {
  DEFAULT_TIMEOUT_SECONDS,
  FAILURE_OPTIONS,
  WAIT_OPTIONS,
  SequenceStepList,
  newStepUid,
  renumber,
  type DraftStep,
  type LiveDeployment,
} from "./SequenceStepList";
import { DeleteSequenceDialog, RunConfirmDialog, SequenceExecutionPanel } from "./SequenceRunPanels";

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
  /** Schedules in this namespace, to show and block deletes of linked sequences. */
  schedules?: EnvironmentSchedule[];
  /** Most recent execution per sequence id, for the Last Run column. */
  lastRuns?: Record<number, ExecutionHistory>;
  onCreate: (data: SequenceCreateRequest) => Promise<void>;
  onUpdate: (id: number, data: Partial<SequenceCreateRequest>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  onExecuteStart: (sequenceId: number, replicaCount: number, dryRun: boolean) => Promise<EnvironmentScaleResult>;
  onExecuteStop: (sequenceId: number, dryRun: boolean) => Promise<EnvironmentScaleResult>;
  /** The run being followed in the live panel (polled by the page). */
  trackedExecution?: ExecutionHistory | null;
  onDismissExecution?: () => void;
  onViewHistory?: () => void;
  isLoading: boolean;
  /** Write role: create, edit, run, and delete. Read-only users only view. */
  canWrite: boolean;
}

const PAGE_SIZES = [10, 20, 50];
const toolbarSelect =
  "rounded-md border border-gray-300 bg-white px-2 py-1 text-xs text-gray-600 focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100";

const toDraft = (s: SequenceStep, i: number): DraftStep => ({
  uid: newStepUid(),
  order: i + 1,
  deployment_name: s.deployment_name,
  replicas: s.replicas ?? 1,
  // "Health endpoint" never had a URL to probe; the server now treats it as pods ready.
  wait_condition: s.wait_condition === "health_endpoint" ? "pods_ready" : s.wait_condition ?? "pods_ready",
  timeout_seconds: s.timeout_seconds ?? DEFAULT_TIMEOUT_SECONDS,
  min_ready_percent: s.min_ready_percent ?? 100,
  retry_count: s.retry_count ?? 3,
  on_failure: s.on_failure ?? "abort",
});

const toPayload = (steps: DraftStep[]): SequenceStep[] =>
  steps.map(({ uid: _uid, ...step }, i) => ({ ...step, order: i + 1 }));

const snapshot = (name: string, rollback: boolean, steps: DraftStep[]) =>
  JSON.stringify({ name: name.trim(), rollback, steps: toPayload(steps) });

const SequenceDesigner: React.FC<Props> = ({
  canWrite,
  sequences,
  deployments,
  clusterId,
  namespace,
  schedules = [],
  lastRuns = {},
  onCreate,
  onUpdate,
  onDelete,
  onExecuteStart,
  onExecuteStop,
  trackedExecution = null,
  onDismissExecution,
  onViewHistory,
  isLoading,
}) => {
  // ── Builder state ──
  const [showBuilder, setShowBuilder] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [seqName, setSeqName] = useState("");
  const [seqType, setSeqType] = useState<"startup" | "shutdown">("startup");
  const [rollback, setRollback] = useState(true);
  const [steps, setSteps] = useState<DraftStep[]>([]);
  const [builderSearch, setBuilderSearch] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [nameTouched, setNameTouched] = useState(false);
  const [highlightUid, setHighlightUid] = useState<string | null>(null);
  const initialSnapshot = useRef("");
  const builderRef = useRef<HTMLDivElement>(null);
  const stepsScrollRef = useRef<HTMLDivElement>(null);

  // ── Grid + dialogs ──
  const [expandedSeq, setExpandedSeq] = useState<number | null>(null);
  const [confirmRun, setConfirmRun] = useState<EnvironmentSequence | null>(null);
  const [confirmDelete, setConfirmDelete] = useState<EnvironmentSequence | null>(null);
  const [gridSearch, setGridSearch] = useState("");
  const [gridPage, setGridPage] = useState(1);
  const [gridPageSize, setGridPageSize] = useState(20);
  const [gridSort, setGridSort] = useState<SortState<string>>({ key: "name", direction: "asc" });

  const isShutdown = seqType === "shutdown";

  const namespaceDeps = useMemo(() => deployments.filter((d) => d.namespace === namespace), [deployments, namespace]);
  const liveByName = useMemo(() => {
    const map = new Map<string, LiveDeployment>();
    for (const d of namespaceDeps) map.set(d.name, { name: d.name, replicas: d.replicas ?? 0, ready_replicas: d.ready_replicas ?? 0 });
    return map;
  }, [namespaceDeps]);
  const liveLoaded = namespaceDeps.length > 0;

  const stepCountByName = useMemo(() => {
    const map = new Map<string, number>();
    for (const s of steps) map.set(s.deployment_name, (map.get(s.deployment_name) ?? 0) + 1);
    return map;
  }, [steps]);

  // Every deployment stays available: adding one again scales it a second time.
  const availableDeployments = useMemo(() => {
    const q = builderSearch.trim().toLowerCase();
    return [...namespaceDeps].filter((d) => d.name.toLowerCase().includes(q)).sort((a, b) => a.name.localeCompare(b.name));
  }, [namespaceDeps, builderSearch]);
  const notYetAdded = availableDeployments.filter((d) => !stepCountByName.has(d.name));

  // ── Grid filtering + sorting ──
  const filteredSequences = sequences.filter((s) => {
    const q = gridSearch.toLowerCase();
    return (
      s.name.toLowerCase().includes(q) ||
      s.namespace.toLowerCase().includes(q) ||
      s.sequence_type.toLowerCase().includes(q) ||
      s.steps.some((step) => step.deployment_name.toLowerCase().includes(q))
    );
  });
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

  // ── Validation ──
  const trimmedName = seqName.trim();
  const nameTaken = sequences.some((s) => s.id !== editingId && s.namespace === namespace && s.name.trim() === trimmedName);
  const missingSteps = liveLoaded ? steps.filter((s) => !liveByName.has(s.deployment_name)) : [];
  const blockers: string[] = [];
  if (!trimmedName) blockers.push("Enter a sequence name.");
  else if (nameTaken) blockers.push(`A sequence named "${trimmedName}" already exists in ${namespace}.`);
  if (steps.length === 0) blockers.push("Add at least one step.");
  const isDirty = showBuilder && snapshot(seqName, rollback, steps) !== initialSnapshot.current;

  useEffect(() => {
    if (!highlightUid) return;
    const t = setTimeout(() => setHighlightUid(null), 1500);
    return () => clearTimeout(t);
  }, [highlightUid]);

  const openBuilder = (init: { id: number | null; name: string; type: "startup" | "shutdown"; rollback: boolean; steps: DraftStep[] }) => {
    setEditingId(init.id);
    setSeqName(init.name);
    setSeqType(init.type);
    setRollback(init.rollback);
    setSteps(init.steps);
    setBuilderSearch("");
    setSaveError(null);
    setNameTouched(false);
    initialSnapshot.current = snapshot(init.name, init.rollback, init.steps);
    setShowBuilder(true);
    requestAnimationFrame(() => builderRef.current?.scrollIntoView?.({ behavior: "smooth", block: "start" }));
  };

  const closeBuilder = () => {
    setShowBuilder(false);
    setEditingId(null);
    setSteps([]);
    setSeqName("");
    setBuilderSearch("");
    setSaveError(null);
  };

  const handleCancelBuilder = () => {
    if (isDirty && !window.confirm("Discard your unsaved changes to this sequence?")) return;
    closeBuilder();
  };

  const handleCreateNew = () => {
    if (showBuilder && editingId === null) {
      handleCancelBuilder();
      return;
    }
    if (isDirty && !window.confirm("Discard your unsaved changes to this sequence?")) return;
    openBuilder({ id: null, name: "", type: "startup", rollback: true, steps: [] });
  };

  const handleEdit = (seq: EnvironmentSequence) => {
    if (isDirty && !window.confirm("Discard your unsaved changes to this sequence?")) return;
    openBuilder({
      id: seq.id,
      name: seq.name,
      type: seq.sequence_type,
      rollback: seq.rollback_on_failure,
      steps: [...seq.steps].sort((a, b) => a.order - b.order).map(toDraft),
    });
  };

  const handleDuplicate = (seq: EnvironmentSequence) => {
    if (isDirty && !window.confirm("Discard your unsaved changes to this sequence?")) return;
    let name = `${seq.name} (copy)`;
    for (let n = 2; sequences.some((s) => s.name === name); n += 1) name = `${seq.name} (copy ${n})`;
    openBuilder({
      id: null,
      name,
      type: seq.sequence_type,
      rollback: seq.rollback_on_failure,
      steps: [...seq.steps].sort((a, b) => a.order - b.order).map(toDraft),
    });
  };

  const addStep = useCallback(
    (depName: string) => {
      const uid = newStepUid();
      setSteps((prev) =>
        renumber([
          ...prev,
          {
            uid,
            order: prev.length + 1,
            deployment_name: depName,
            replicas: isShutdown ? 0 : 1,
            wait_condition: isShutdown ? "skip" : "pods_ready",
            timeout_seconds: DEFAULT_TIMEOUT_SECONDS,
            min_ready_percent: 100,
            retry_count: 3,
            on_failure: "abort",
          },
        ]),
      );
      setHighlightUid(uid);
      requestAnimationFrame(() => {
        const el = stepsScrollRef.current;
        if (el) el.scrollTop = el.scrollHeight;
      });
    },
    [isShutdown],
  );

  const addAllNotYetAdded = () => notYetAdded.forEach((d) => addStep(d.name));

  const applyToAll = (changes: Partial<SequenceStep>) => setSteps((prev) => prev.map((s) => ({ ...s, ...changes })));

  const handleSave = async () => {
    setNameTouched(true);
    if (blockers.length > 0) return;
    setSaving(true);
    setSaveError(null);
    try {
      const payload = toPayload(steps);
      if (editingId) {
        await onUpdate(editingId, { name: trimmedName, steps: payload, rollback_on_failure: rollback });
      } else {
        await onCreate({ name: trimmedName, cluster_id: clusterId, namespace, sequence_type: seqType, steps: payload, rollback_on_failure: rollback });
      }
      closeBuilder();
    } catch (err) {
      setSaveError(apiErrorMessage(err, "Could not save the sequence"));
    } finally {
      setSaving(false);
    }
  };

  const runSequence = async (seq: EnvironmentSequence) => {
    try {
      if (seq.sequence_type === "startup") await onExecuteStart(seq.id, 1, false);
      else await onExecuteStop(seq.id, false);
      setConfirmRun(null);
    } catch (err) {
      throw new Error(apiErrorMessage(err, "Could not start the sequence"));
    }
  };

  const deleteSequence = async (seq: EnvironmentSequence) => {
    try {
      await onDelete(seq.id);
      setConfirmDelete(null);
      if (editingId === seq.id) closeBuilder();
    } catch (err) {
      throw new Error(apiErrorMessage(err, "Could not delete the sequence"));
    }
  };

  const trackedRunning = trackedExecution?.status === "running";

  return (
    <div className="space-y-4">
      {/* ── Live execution ── */}
      {trackedExecution && (
        <SequenceExecutionPanel execution={trackedExecution} onClose={() => onDismissExecution?.()} onViewHistory={onViewHistory} />
      )}

      {/* ── Builder ── */}
      {showBuilder && (
        <div ref={builderRef} className="scroll-mt-4 space-y-5 rounded-xl border border-att-200 bg-att-50/30 p-5">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <h4 className="font-semibold text-gray-800">{editingId ? "Edit Sequence" : "New Sequence"}</h4>
              <p className="text-xs text-gray-500">
                Namespace <span className="font-mono">{namespace}</span> · steps run top to bottom, one at a time.
              </p>
            </div>
            {isDirty && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-medium text-amber-800 ring-1 ring-inset ring-amber-200">Unsaved changes</span>}
          </div>

          <div className="grid gap-4 md:grid-cols-3">
            <div>
              <label htmlFor="seq-name" className="text-xs font-semibold text-gray-600">Sequence Name</label>
              <input
                id="seq-name"
                value={seqName}
                onChange={(e) => setSeqName(e.target.value)}
                onBlur={() => setNameTouched(true)}
                maxLength={255}
                className={`mt-1 w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 ${
                  nameTouched && (!trimmedName || nameTaken) ? "border-red-300 focus:ring-red-100" : "border-gray-300 focus:border-att-400 focus:ring-att-100"
                }`}
                placeholder="e.g. Dev Startup Order"
              />
              {nameTouched && nameTaken && <p className="mt-1 text-xs text-red-600">That name is already used in {namespace}.</p>}
            </div>
            <div>
              <label htmlFor="seq-type" className="text-xs font-semibold text-gray-600">Sequence Type</label>
              <select
                id="seq-type"
                value={seqType}
                onChange={(e) => {
                  const t = e.target.value as "startup" | "shutdown";
                  setSeqType(t);
                  setSteps((prev) =>
                    prev.map((s) => ({
                      ...s,
                      replicas: t === "shutdown" ? 0 : Math.max(s.replicas, 1),
                      wait_condition: t === "shutdown" ? "skip" : s.wait_condition === "skip" ? "pods_ready" : s.wait_condition,
                    })),
                  );
                }}
                disabled={!!editingId}
                title={editingId ? "The type of a saved sequence can't change; duplicate it instead" : undefined}
                className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm disabled:bg-gray-50 disabled:opacity-70"
              >
                <option value="startup">Startup (scale up)</option>
                <option value="shutdown">Shutdown (scale to 0)</option>
              </select>
            </div>
            <div className="pt-5">
              <label className={`flex items-center gap-2 text-sm ${isShutdown ? "text-gray-400" : "text-gray-700"}`}>
                <input type="checkbox" checked={!isShutdown && rollback} disabled={isShutdown} onChange={(e) => setRollback(e.target.checked)} className="text-att-500" />
                Rollback on failure
              </label>
              <p className="mt-1 text-xs text-gray-500">
                {isShutdown
                  ? "Not used for shutdowns: a failed shutdown leaves stopped deployments stopped."
                  : "If an aborting step fails, deployments this run scaled go back to their previous replica counts, newest first."}
              </p>
            </div>
          </div>

          <div className="grid gap-5 lg:grid-cols-5">
            {/* Available deployments */}
            <div className="lg:col-span-2">
              <div className="mb-2 flex items-center justify-between gap-2">
                <h5 className="text-xs font-semibold uppercase text-gray-500">Available Deployments</h5>
                {notYetAdded.length > 0 && (
                  <button type="button" onClick={addAllNotYetAdded} className="text-xs font-medium text-att-600 hover:text-att-800" title="Add every listed deployment that isn't in the sequence yet">
                    + Add all not yet added ({notYetAdded.length})
                  </button>
                )}
              </div>
              <input
                type="text"
                placeholder="Search deployments..."
                aria-label="Search deployments"
                value={builderSearch}
                onChange={(e) => setBuilderSearch(e.target.value)}
                className="mb-2 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-att-400 focus:ring-2 focus:ring-att-100"
              />
              <div className="max-h-[28rem] overflow-y-auto rounded-lg border border-gray-200 bg-white">
                {availableDeployments.length === 0 ? (
                  <p className="p-4 text-center text-sm text-gray-400">
                    {builderSearch ? "No deployments match the search" : `No deployments found in ${namespace}`}
                  </p>
                ) : (
                  availableDeployments.map((dep) => {
                    const used = stepCountByName.get(dep.name) ?? 0;
                    return (
                      <button
                        type="button"
                        key={dep.name}
                        onClick={() => addStep(dep.name)}
                        title={used > 0 ? `Add ${dep.name} again (it is already in ${used} step${used === 1 ? "" : "s"})` : `Add ${dep.name} as step ${steps.length + 1}`}
                        className="flex w-full items-center gap-2 border-b border-gray-100 px-3 py-2 text-left text-sm last:border-0 hover:bg-att-50"
                      >
                        <span className="min-w-0 flex-1 truncate font-mono text-xs text-gray-700">{dep.name}</span>
                        {used > 0 && (
                          <span className="shrink-0 rounded-full bg-att-100 px-1.5 py-0.5 text-[10px] font-semibold text-att-700">
                            In sequence{used > 1 ? ` ×${used}` : ""}
                          </span>
                        )}
                        <span className={`shrink-0 font-mono text-xs ${dep.replicas > 0 ? "text-green-600" : "text-gray-400"}`} title="Ready / desired replicas">
                          {dep.ready_replicas}/{dep.replicas}
                        </span>
                        <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" className="shrink-0 text-att-500" aria-hidden="true"><path d="M12 5v14M5 12h14" /></svg>
                      </button>
                    );
                  })
                )}
              </div>
            </div>

            {/* Execution order */}
            <div className="lg:col-span-3">
              <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                <div>
                  <h5 className="text-xs font-semibold uppercase text-gray-500">Execution Order</h5>
                  <p className="text-xs text-gray-400">
                    {steps.length} step{steps.length !== 1 ? "s" : ""} · {stepCountByName.size} deployment{stepCountByName.size !== 1 ? "s" : ""} · drag the handle or use the arrows to reorder
                  </p>
                </div>
                {steps.length > 1 && (
                  <div className="flex flex-wrap items-center gap-2">
                    {!isShutdown && (
                      <select value="" onChange={(e) => e.target.value && applyToAll({ wait_condition: e.target.value as SequenceStep["wait_condition"] })} className={toolbarSelect} aria-label="Set wait condition for all steps">
                        <option value="">Set wait for all…</option>
                        {WAIT_OPTIONS.map((w) => <option key={w.value} value={w.value}>{w.label}</option>)}
                      </select>
                    )}
                    <select value="" onChange={(e) => e.target.value && applyToAll({ on_failure: e.target.value as SequenceStep["on_failure"] })} className={toolbarSelect} aria-label="Set on-failure for all steps">
                      <option value="">Set on-failure for all…</option>
                      {FAILURE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                    </select>
                    <button type="button" onClick={() => window.confirm(`Remove all ${steps.length} steps?`) && setSteps([])} className="text-xs font-medium text-red-500 hover:text-red-700">
                      Clear all
                    </button>
                  </div>
                )}
              </div>
              <div ref={stepsScrollRef} className="max-h-[28rem] overflow-y-auto rounded-lg border border-gray-200 bg-white">
                {steps.length === 0 ? (
                  <div className="p-6 text-center text-sm text-gray-400">
                    <p>Add deployments from the left.</p>
                    <p className="mt-1 text-xs">You can add the same deployment more than once, e.g. 1 pod early and 50 pods later.</p>
                  </div>
                ) : (
                  <SequenceStepList
                    steps={steps}
                    onChange={setSteps}
                    isShutdown={isShutdown}
                    liveByName={liveByName}
                    liveLoaded={liveLoaded}
                    namespace={namespace}
                    highlightUid={highlightUid}
                  />
                )}
              </div>
            </div>
          </div>

          {(missingSteps.length > 0 || saveError || (nameTouched && blockers.length > 0)) && (
            <div className="space-y-2">
              {missingSteps.length > 0 && (
                <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  {missingSteps.length} step{missingSteps.length === 1 ? "" : "s"} reference deployments not found in {namespace}:{" "}
                  <span className="font-mono">{[...new Set(missingSteps.map((s) => s.deployment_name))].join(", ")}</span>. They will fail when the sequence runs.
                </div>
              )}
              {nameTouched && blockers.length > 0 && (
                <ul className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                  {blockers.map((b) => <li key={b}>{b}</li>)}
                </ul>
              )}
              {saveError && <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">{saveError}</div>}
            </div>
          )}

          <div className="flex justify-end gap-2">
            <button type="button" onClick={handleCancelBuilder} disabled={saving} className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50">Cancel</button>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving || isLoading || (nameTouched && blockers.length > 0) || steps.length === 0}
              className="rounded-lg bg-att-500 px-4 py-2 text-sm font-medium text-white hover:bg-att-600 disabled:opacity-50"
            >
              {saving ? "Saving…" : editingId ? "Update Sequence" : "Save Sequence"}
            </button>
          </div>
        </div>
      )}

      {/* ── Sequences grid ── */}
      <div className={gridStyles.shell}>
        <div className={gridStyles.panelHeader}>
          <div className="flex flex-wrap items-center gap-3">
            <span className={gridStyles.countBadge}>{filteredSequences.length} sequence{filteredSequences.length !== 1 ? "s" : ""}</span>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-3">
            <input type="text" placeholder="Search sequences or deployments..." aria-label="Search sequences" value={gridSearch} onChange={(e) => { setGridSearch(e.target.value); setGridPage(1); }} className={gridStyles.toolbarInput} />
            <select value={gridPageSize} onChange={(e) => { setGridPageSize(Number(e.target.value)); setGridPage(1); }} className="rounded-lg border border-att-200 bg-white px-2 py-2 text-sm text-gray-700" aria-label="Rows per page">
              {PAGE_SIZES.map((n) => <option key={n} value={n}>{n} / page</option>)}
            </select>
            {canWrite && <button type="button" onClick={handleCreateNew} className="rounded-lg bg-att-500 px-4 py-2 text-sm font-medium text-white hover:bg-att-600">+ Create Sequence</button>}
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
              <th className={gridStyles.headerCell}>Last Run</th>
              <th className={gridStyles.headerCell}><SortableHeader label="Created Date" active={gridSort.key === "created_at"} direction={gridSort.direction} onClick={() => setGridSort(nextSortState(gridSort, "created_at"))} /></th>
              <th className={gridStyles.headerCellCenter}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginatedSequences.map((seq) => {
              const ordered = [...seq.steps].sort((a, b) => a.order - b.order);
              const deploymentCount = new Set(ordered.map((s) => s.deployment_name)).size;
              const lastRun = lastRuns[seq.id];
              const runningHere = (trackedRunning && trackedExecution?.sequence_id === seq.id) || lastRun?.status === "running";
              const seqShutdown = seq.sequence_type === "shutdown";
              return (
                <React.Fragment key={seq.id}>
                  <tr className={gridStyles.row}>
                    <td className={gridStyles.strongCell}>
                      <button type="button" onClick={() => setExpandedSeq(expandedSeq === seq.id ? null : seq.id)} className="flex items-center gap-1 text-left hover:text-att-600" aria-expanded={expandedSeq === seq.id}>
                        <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" className={`shrink-0 transition-transform ${expandedSeq === seq.id ? "rotate-90" : ""}`} aria-hidden="true"><path d="m9 18 6-6-6-6" /></svg>
                        {seq.name}
                      </button>
                    </td>
                    <td className={gridStyles.cell}>
                      <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${seqShutdown ? "bg-orange-100 text-orange-700" : "bg-green-100 text-green-700"}`}>
                        {seqShutdown ? "Shutdown" : "Startup"}
                      </span>
                    </td>
                    <td className={gridStyles.cell}>{seq.namespace}</td>
                    <td className={gridStyles.centerCell}>
                      <span className="font-semibold">{seq.steps.length}</span>
                      {deploymentCount !== seq.steps.length && <span className="block text-[11px] text-gray-400">{deploymentCount} deployments</span>}
                    </td>
                    <td className={gridStyles.centerCell}>
                      {seqShutdown ? <span className="text-gray-400" title="Rollback applies to startup sequences">N/A</span> : seq.rollback_on_failure ? <span className="font-medium text-green-600">Yes</span> : <span className="text-gray-400">No</span>}
                    </td>
                    <td className={gridStyles.cell}>
                      {lastRun ? (
                        <span className="flex flex-col items-start gap-0.5">
                          <StatusBadge status={lastRun.status} />
                          <span className="text-[11px] text-gray-400">{lastRun.started_at ? new Date(lastRun.started_at).toLocaleString() : ""}</span>
                        </span>
                      ) : (
                        <span className="text-xs text-gray-400">Never</span>
                      )}
                    </td>
                    <td className={gridStyles.cell}>{seq.created_at ? new Date(seq.created_at).toLocaleDateString() : "-"}</td>
                    <td className={gridStyles.centerCell}>
                      {!canWrite ? <span className="text-xs text-gray-400">—</span> : (
                        <div className="flex items-center justify-center gap-1">
                          {seqShutdown ? (
                            <button type="button" onClick={() => setConfirmRun(seq)} disabled={isLoading || runningHere || seq.steps.length === 0} className="rounded bg-orange-500 px-2.5 py-1 text-xs font-medium text-white hover:bg-orange-600 disabled:opacity-50" title={runningHere ? "This sequence is running" : "Run Shutdown Sequence"}>
                              {runningHere ? "Running…" : "Stop"}
                            </button>
                          ) : (
                            <button type="button" onClick={() => setConfirmRun(seq)} disabled={isLoading || runningHere || seq.steps.length === 0} className="rounded bg-green-500 px-2.5 py-1 text-xs font-medium text-white hover:bg-green-600 disabled:opacity-50" title={runningHere ? "This sequence is running" : "Run Startup Sequence"}>
                              {runningHere ? "Running…" : "Start"}
                            </button>
                          )}
                          <button type="button" onClick={() => handleEdit(seq)} className="rounded p-1 text-blue-500 hover:bg-blue-50" title="Edit Sequence" aria-label={`Edit ${seq.name}`}>
                            <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" aria-hidden="true"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg>
                          </button>
                          <button type="button" onClick={() => handleDuplicate(seq)} className="rounded p-1 text-gray-500 hover:bg-gray-100" title="Duplicate Sequence" aria-label={`Duplicate ${seq.name}`}>
                            <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></svg>
                          </button>
                          <button type="button" onClick={() => setConfirmDelete(seq)} className="rounded p-1 text-red-500 hover:bg-red-50" title="Delete Sequence" aria-label={`Delete ${seq.name}`}>
                            <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
                          </button>
                        </div>
                      )}
                    </td>
                  </tr>
                  {expandedSeq === seq.id && (
                    <tr>
                      <td colSpan={8} className="bg-gray-50 px-6 py-3">
                        <div className="mb-2 text-xs font-semibold text-gray-600">
                          {seq.steps.length} step{seq.steps.length !== 1 ? "s" : ""}, run top to bottom
                        </div>
                        <div className="overflow-hidden rounded-lg border border-gray-200 bg-white">
                          <table className="w-full text-xs">
                            <thead className="bg-gray-50 text-gray-600">
                              <tr>
                                <th className="w-10 px-3 py-1.5 text-left font-semibold">Step</th>
                                <th className="px-3 py-1.5 text-left font-semibold">Deployment Name</th>
                                <th className="px-3 py-1.5 text-center font-semibold">Replicas</th>
                                <th className="px-3 py-1.5 text-left font-semibold">Then</th>
                                <th className="px-3 py-1.5 text-left font-semibold">If it fails</th>
                              </tr>
                            </thead>
                            <tbody>
                              {ordered.map((step, idx) => (
                                <tr key={idx} className="border-t border-gray-100">
                                  <td className="px-3 py-1.5"><span className="flex h-5 w-5 items-center justify-center rounded-full bg-att-100 text-xs font-bold text-att-700">{idx + 1}</span></td>
                                  <td className="px-3 py-1.5 font-mono">{step.deployment_name}</td>
                                  <td className="px-3 py-1.5 text-center font-mono">{seqShutdown ? 0 : step.replicas}</td>
                                  <td className="px-3 py-1.5 text-gray-500">
                                    {seqShutdown ? "No wait" : waitSummary(step.wait_condition, step.timeout_seconds, step.min_ready_percent)}
                                  </td>
                                  <td className="px-3 py-1.5">
                                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${step.on_failure === "continue" ? "bg-yellow-50 text-yellow-700" : "bg-red-50 text-red-600"}`}>
                                      {step.on_failure === "continue" ? "Continue" : "Abort"}
                                    </span>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
            {paginatedSequences.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-8 text-center text-sm text-gray-400">{gridSearch ? "No sequences match the search" : "No sequences in this namespace yet"}</td></tr>
            )}
          </tbody>
        </table>
        <div className={gridStyles.pager}>
          <span className="text-gray-600">Showing {gridStart}-{gridEnd} of {sortedSequences.length}</span>
          <div className="flex items-center gap-2">
            <button type="button" onClick={() => setGridPage(1)} disabled={gridSafePage <= 1} className={gridStyles.pagerButton}>&laquo;</button>
            <button type="button" onClick={() => setGridPage(Math.max(1, gridSafePage - 1))} disabled={gridSafePage <= 1} className={gridStyles.pagerButton}>Previous</button>
            <span className="text-gray-600">Page {gridSafePage} of {gridTotalPages}</span>
            <button type="button" onClick={() => setGridPage(Math.min(gridTotalPages, gridSafePage + 1))} disabled={gridSafePage >= gridTotalPages} className={gridStyles.pagerButton}>Next</button>
            <button type="button" onClick={() => setGridPage(gridTotalPages)} disabled={gridSafePage >= gridTotalPages} className={gridStyles.pagerButton}>&raquo;</button>
          </div>
        </div>
      </div>

      {confirmRun && (
        <RunConfirmDialog
          sequence={confirmRun}
          liveByName={liveByName}
          liveLoaded={liveLoaded}
          onCancel={() => setConfirmRun(null)}
          onConfirm={() => runSequence(confirmRun)}
        />
      )}
      {confirmDelete && (
        <DeleteSequenceDialog
          sequence={confirmDelete}
          linkedSchedules={schedules.filter((s) => s.sequence_id === confirmDelete.id)}
          onCancel={() => setConfirmDelete(null)}
          onConfirm={() => deleteSequence(confirmDelete)}
        />
      )}
    </div>
  );
};

export default SequenceDesigner;
