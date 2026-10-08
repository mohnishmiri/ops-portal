/**
 * Sequence run UI: the pre-run confirmation (a plan of exactly what will be
 * scaled), the delete confirmation, and the live progress panel fed by the
 * real execution record the server updates after every step.
 */

import React, { useEffect, useState } from "react";
import type { EnvironmentSchedule, EnvironmentSequence, ExecutionHistory } from "../../services/environmentApi";
import {
  ExecutionStepsTable,
  ScaleChange,
  StatusBadge,
  WAIT_LABELS,
  effectiveStepStatus,
  formatDuration,
  operationLabel,
  stepCounts,
  useElapsedSince,
  waitSummary,
} from "./executionStatus";
import type { LiveDeployment } from "./SequenceStepList";

// ── Modal shell ─────────────────────────────────────────────────────────

const Modal: React.FC<{ title: string; subtitle?: React.ReactNode; onClose: () => void; children: React.ReactNode; footer: React.ReactNode; wide?: boolean }> = ({
  title,
  subtitle,
  onClose,
  children,
  footer,
  wide,
}) => {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`flex max-h-[90vh] w-full flex-col rounded-xl bg-white shadow-2xl ${wide ? "max-w-4xl" : "max-w-lg"}`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="border-b border-gray-200 px-6 py-4">
          <h3 className="text-lg font-semibold text-gray-900">{title}</h3>
          {subtitle && <div className="mt-0.5 text-sm text-gray-500">{subtitle}</div>}
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4">{children}</div>
        <div className="flex items-center justify-end gap-2 border-t border-gray-200 bg-gray-50 px-6 py-3 rounded-b-xl">{footer}</div>
      </div>
    </div>
  );
};

const ErrorNote: React.FC<{ message: string | null }> = ({ message }) =>
  message ? (
    <div className="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800" role="alert">{message}</div>
  ) : null;

// ── Run confirmation ────────────────────────────────────────────────────

interface RunConfirmProps {
  sequence: EnvironmentSequence;
  liveByName: Map<string, LiveDeployment>;
  liveLoaded: boolean;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}

export const RunConfirmDialog: React.FC<RunConfirmProps> = ({ sequence, liveByName, liveLoaded, onCancel, onConfirm }) => {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const isShutdown = sequence.sequence_type === "shutdown";
  const steps = [...sequence.steps].sort((a, b) => a.order - b.order);

  const lastTarget = new Map<string, number>();
  const plan = steps.map((s, i) => {
    const live = liveByName.get(s.deployment_name);
    const from = lastTarget.has(s.deployment_name) ? lastTarget.get(s.deployment_name) : live?.replicas;
    const to = isShutdown ? 0 : s.replicas;
    lastTarget.set(s.deployment_name, to);
    return { position: i + 1, step: s, live, from, to, missing: liveLoaded && !live };
  });
  const missing = plan.filter((p) => p.missing);
  // A startup can scale some deployments down first; make that unmissable.
  const scaleDowns = isShutdown ? [] : plan.filter((p) => p.from != null && p.to < p.from);
  const deploymentCount = new Set(steps.map((s) => s.deployment_name)).size;
  const podWaits = isShutdown ? [] : steps.filter((s) => s.wait_condition !== "skip" && s.wait_condition !== "fixed_time");
  const fixedWaits = isShutdown ? 0 : steps.reduce((sum, s) => sum + (s.wait_condition === "fixed_time" ? s.timeout_seconds || 0 : 0), 0);

  const confirm = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await onConfirm();
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  };

  return (
    <Modal
      wide
      title={isShutdown ? "Run shutdown sequence?" : "Start startup sequence?"}
      subtitle={
        <>
          <span className="font-semibold text-gray-800">{sequence.name}</span> · namespace{" "}
          <span className="font-mono">{sequence.namespace}</span> · {steps.length} step{steps.length === 1 ? "" : "s"} across {deploymentCount} deployment{deploymentCount === 1 ? "" : "s"}
        </>
      }
      onClose={submitting ? () => undefined : onCancel}
      footer={
        <>
          <button type="button" onClick={onCancel} disabled={submitting} className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50">Cancel</button>
          <button
            type="button"
            onClick={confirm}
            disabled={submitting}
            className={`rounded-lg px-4 py-2 text-sm font-semibold text-white disabled:opacity-60 ${isShutdown ? "bg-orange-600 hover:bg-orange-700" : "bg-green-600 hover:bg-green-700"}`}
          >
            {submitting ? "Starting…" : isShutdown ? "Run shutdown" : "Start sequence"}
          </button>
        </>
      }
    >
      <div className="space-y-3">
        <div className="grid gap-2 text-xs text-gray-600 sm:grid-cols-3">
          <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
            <p className="font-semibold text-gray-800">Runs top to bottom</p>
            <p>{isShutdown ? "Each step scales a deployment to 0, then the next step starts." : "Each step scales one deployment and waits before the next starts."}</p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
            <p className="font-semibold text-gray-800">On failure</p>
            <p>
              {isShutdown
                ? "An aborting step stops the run; stopped deployments stay stopped."
                : sequence.rollback_on_failure
                  ? "An aborting step stops the run and returns scaled deployments to their previous counts."
                  : "An aborting step stops the run; nothing is rolled back."}
            </p>
          </div>
          <div className="rounded-lg border border-gray-200 bg-gray-50 px-3 py-2">
            <p className="font-semibold text-gray-800">Duration</p>
            <p>
              {isShutdown
                ? "Usually under a minute."
                : `${podWaits.length ? "Pod waits keep going while pods are still coming up and fail only when they stop progressing." : ""}${fixedWaits ? ` Fixed waits add ${formatDuration(fixedWaits)}.` : ""}`}{" "}
              Runs on the server; you can leave this page.
            </p>
          </div>
        </div>

        {scaleDowns.length > 0 && (
          <div className="rounded-lg border border-orange-200 bg-orange-50 px-3 py-2 text-sm text-orange-900">
            This startup also scales down {scaleDowns.length} deployment{scaleDowns.length === 1 ? "" : "s"}:{" "}
            {scaleDowns.map((p, i) => (
              <span key={p.position}>
                {i > 0 && ", "}
                <span className="font-mono">{p.step.deployment_name}</span> ({p.from} → {p.to}, step {p.position})
              </span>
            ))}
            .
          </div>
        )}
        {missing.length > 0 && (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900" role="alert">
            {missing.length} step{missing.length === 1 ? "" : "s"} reference deployments not found in {sequence.namespace}:{" "}
            <span className="font-mono">{[...new Set(missing.map((m) => m.step.deployment_name))].join(", ")}</span>. Those steps will fail.
          </div>
        )}

        <div className="max-h-80 overflow-y-auto rounded-lg border border-gray-200">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-gray-50 text-gray-600">
              <tr>
                <th className="w-10 px-3 py-2 text-left font-semibold">#</th>
                <th className="px-3 py-2 text-left font-semibold">Deployment</th>
                <th className="px-3 py-2 text-center font-semibold">Live now</th>
                <th className="px-3 py-2 text-center font-semibold">Planned</th>
                <th className="px-3 py-2 text-left font-semibold">Then</th>
                <th className="px-3 py-2 text-left font-semibold">If it fails</th>
              </tr>
            </thead>
            <tbody>
              {plan.map((p) => (
                <tr key={p.position} className={`border-t border-gray-100 ${p.missing ? "bg-amber-50/60" : ""}`}>
                  <td className="px-3 py-1.5 font-semibold text-gray-500">{p.position}</td>
                  <td className="px-3 py-1.5 font-mono text-gray-800 break-all">{p.step.deployment_name}</td>
                  <td className="px-3 py-1.5 text-center text-gray-500">{p.live ? `${p.live.ready_replicas}/${p.live.replicas}` : "—"}</td>
                  <td className="px-3 py-1.5 text-center"><ScaleChange from={p.from} to={p.to} /></td>
                  <td className="px-3 py-1.5 text-gray-500">
                    {isShutdown ? "No wait" : waitSummary(p.step.wait_condition, p.step.timeout_seconds, p.step.min_ready_percent)}
                  </td>
                  <td className={`px-3 py-1.5 ${p.step.on_failure === "continue" ? "text-amber-700" : "text-gray-500"}`}>{p.step.on_failure === "continue" ? "Continue" : "Abort"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ErrorNote message={error} />
      </div>
    </Modal>
  );
};

// ── Delete confirmation ─────────────────────────────────────────────────

interface DeleteProps {
  sequence: EnvironmentSequence;
  linkedSchedules: EnvironmentSchedule[];
  onCancel: () => void;
  onConfirm: () => Promise<void>;
}

export const DeleteSequenceDialog: React.FC<DeleteProps> = ({ sequence, linkedSchedules, onCancel, onConfirm }) => {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const blocked = linkedSchedules.length > 0;

  const confirm = async () => {
    setSubmitting(true);
    setError(null);
    try {
      await onConfirm();
    } catch (err) {
      setError((err as Error).message);
      setSubmitting(false);
    }
  };

  return (
    <Modal
      title="Delete sequence?"
      subtitle={<span className="font-semibold text-gray-800">{sequence.name}</span>}
      onClose={submitting ? () => undefined : onCancel}
      footer={
        <>
          <button type="button" onClick={onCancel} disabled={submitting} className="rounded-lg border border-gray-300 bg-white px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 disabled:opacity-50">Cancel</button>
          <button type="button" onClick={confirm} disabled={submitting || blocked} className="rounded-lg bg-red-600 px-4 py-2 text-sm font-semibold text-white hover:bg-red-700 disabled:opacity-50">
            {submitting ? "Deleting…" : "Delete sequence"}
          </button>
        </>
      }
    >
      {blocked ? (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
          Used by {linkedSchedules.length} schedule{linkedSchedules.length === 1 ? "" : "s"}:{" "}
          <span className="font-semibold">{linkedSchedules.map((s) => s.job_name).join(", ")}</span>. Unlink or delete
          {linkedSchedules.length === 1 ? " it" : " them"} on the Schedules tab first.
        </div>
      ) : (
        <p className="text-sm text-gray-600">
          The sequence and its {sequence.steps.length} step{sequence.steps.length === 1 ? "" : "s"} will be removed. Past executions stay in History. This can't be undone.
        </p>
      )}
      <ErrorNote message={error} />
    </Modal>
  );
};

// ── Live execution panel ────────────────────────────────────────────────

interface PanelProps {
  execution: ExecutionHistory;
  onClose: () => void;
  onViewHistory?: () => void;
}

const HEADLINE: Record<string, string> = {
  running: "Running",
  completed: "Completed",
  failed: "Failed",
  rolled_back: "Failed and rolled back",
};

export const SequenceExecutionPanel: React.FC<PanelProps> = ({ execution, onClose, onViewHistory }) => {
  const running = execution.status === "running";
  const liveElapsed = useElapsedSince(execution.started_at, running);
  const elapsed = running ? liveElapsed : execution.duration_seconds ?? liveElapsed;
  const steps = execution.step_details ?? [];
  const counts = stepCounts(steps, execution.status);
  const total = execution.total_deployments || steps.length;
  const finished = counts.completed + counts.failed;
  const pct = total > 0 ? Math.min(100, Math.round(((running ? finished : total) / total) * 100)) : 0;
  const current = steps.find((s) => effectiveStepStatus(s, execution.status) === "running");
  const tone =
    running ? "border-att-300" : execution.status === "completed" ? "border-green-300" : execution.status === "rolled_back" ? "border-orange-300" : "border-red-300";

  return (
    <section className={`space-y-4 rounded-xl border-2 bg-white p-5 shadow-sm ${tone}`} aria-live="polite">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={execution.status} size="md" />
            <h4 className="text-base font-semibold text-gray-900">
              {operationLabel(execution.operation)} {HEADLINE[execution.status]?.toLowerCase() ?? execution.status}:{" "}
              <span className="text-att-600">{execution.sequence_name ?? `#${execution.sequence_id}`}</span>
            </h4>
          </div>
          <p className="mt-1 text-xs text-gray-500">
            Execution #{execution.id} · namespace <span className="font-mono">{execution.namespace}</span> · started by{" "}
            {execution.initiated_by_email || execution.initiated_by}
            {execution.started_at && <> at {new Date(execution.started_at).toLocaleTimeString()}</>}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 rounded-lg bg-gray-100 px-3 py-1.5 font-mono text-sm font-semibold text-gray-700" title="Elapsed">
            <svg className="h-4 w-4 text-gray-500" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" /></svg>
            {formatDuration(elapsed)}
          </span>
          {onViewHistory && (
            <button type="button" onClick={onViewHistory} className="rounded-lg border border-att-200 bg-white px-3 py-1.5 text-sm font-medium text-att-700 hover:bg-att-50">View in History</button>
          )}
          <button type="button" onClick={onClose} className="rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-sm text-gray-600 hover:bg-gray-50" title={running ? "Hide this panel; the run continues on the server" : undefined}>
            {running ? "Hide" : "Close"}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {[
          { label: "Steps", value: total, cls: "border-gray-200 bg-gray-50 text-gray-900" },
          { label: "Completed", value: counts.completed, cls: "border-green-200 bg-green-50 text-green-800" },
          { label: "Failed", value: counts.failed, cls: "border-red-200 bg-red-50 text-red-800" },
          { label: running ? "Waiting" : "Not run", value: running ? counts.pending + counts.running : counts.not_run, cls: "border-gray-200 bg-white text-gray-700" },
          { label: "Rolled back", value: counts.rolledBack, cls: "border-orange-200 bg-orange-50 text-orange-800" },
        ].map((tile) => (
          <div key={tile.label} className={`rounded-lg border px-3 py-2 text-center ${tile.cls}`}>
            <div className="text-lg font-bold">{tile.value}</div>
            <div className="text-[11px] font-medium uppercase tracking-wide opacity-80">{tile.label}</div>
          </div>
        ))}
      </div>

      <div>
        <div className="mb-1 flex justify-between text-xs text-gray-500">
          <span>
            {running && current
              ? <>Step {current.step ?? "?"} of {total}: <span className="font-mono font-semibold text-gray-700">{current.deployment}</span> → {current.target_replicas} pods{current.pods_remaining != null && current.pods_remaining > current.target_replicas
                  ? `, ${current.pods_remaining} pods still stopping`
                  : current.ready_replicas != null
                  ? `, ${current.ready_replicas}/${current.target_replicas} ready${current.required_ready != null && current.required_ready < current.target_replicas ? ` (moves on at ${current.required_ready})` : ""}`
                  : current.wait_condition && current.wait_condition !== "skip" ? `, ${WAIT_LABELS[current.wait_condition]?.toLowerCase() ?? current.wait_condition}` : ""}</>
              : `${finished} of ${total} steps finished`}
          </span>
          <span>{pct}%</span>
        </div>
        <div className="h-2.5 w-full overflow-hidden rounded-full bg-gray-200">
          <div
            className={`h-2.5 rounded-full transition-all duration-700 ${
              running ? "bg-gradient-to-r from-att-400 to-att-600" : execution.status === "completed" ? "bg-green-500" : execution.status === "rolled_back" ? "bg-orange-500" : "bg-red-500"
            }`}
            style={{ width: `${pct}%` }}
          />
        </div>
      </div>

      <ExecutionStepsTable steps={steps} executionStatus={execution.status} maxHeightClass="max-h-80" />

      {execution.error_message && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">{execution.error_message}</div>
      )}
      {execution.status === "completed" && (
        <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm font-medium text-green-800">
          All {total} steps completed in {formatDuration(elapsed)}.
        </div>
      )}
      {running && (
        <p className="text-xs text-gray-400">Progress updates every few seconds. The run continues on the server if you leave this page; follow it on the History tab.</p>
      )}
    </section>
  );
};
