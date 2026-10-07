/**
 * Execution-order editor for the Sequence Designer.
 *
 * - One card per step; the deployment name is always visible (it used to be
 *   squeezed to nothing by the inputs beside it).
 * - Reorder by dragging the handle (the drag preview and a banner name the
 *   step being moved) or with the arrow buttons.
 * - A deployment may appear in several steps, e.g. scale to 1 early and to 50
 *   later, so steps are keyed by a client id, never by deployment name.
 */

import React, { useEffect, useRef, useState } from "react";
import type { SequenceStep } from "../../services/environmentApi";

export type DraftStep = SequenceStep & { uid: string };

export interface LiveDeployment {
  name: string;
  replicas: number;
  ready_replicas: number;
}

let uidSeq = 0;
export const newStepUid = () => `step-${++uidSeq}`;

export const MAX_REPLICAS = 100;
export const MAX_TIMEOUT_SECONDS = 3600;
export const DEFAULT_TIMEOUT_SECONDS = 600;
export const DEFAULT_FIXED_WAIT_SECONDS = 30;

export const WAIT_OPTIONS: { value: SequenceStep["wait_condition"]; label: string }[] = [
  { value: "pods_ready", label: "Wait until pods ready" },
  { value: "deployment_available", label: "Wait until available" },
  { value: "fixed_time", label: "Wait a fixed time" },
  { value: "skip", label: "Don't wait" },
];

export const FAILURE_OPTIONS: { value: SequenceStep["on_failure"]; label: string }[] = [
  { value: "abort", label: "Abort sequence" },
  { value: "continue", label: "Continue to next step" },
];

export const renumber = (steps: DraftStep[]): DraftStep[] =>
  steps.map((s, i) => (s.order === i + 1 ? s : { ...s, order: i + 1 }));

const selectCls =
  "rounded-md border border-gray-300 bg-white px-2 py-1 text-xs text-gray-700 focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100";

// ── Number field ────────────────────────────────────────────────────────

interface NumberFieldProps {
  value: number;
  min: number;
  max: number;
  onCommit: (value: number) => void;
  ariaLabel: string;
  stepper?: boolean;
  widthClass?: string;
}

/**
 * Integer input that may be emptied while typing. The old field re-clamped on
 * every keystroke, so clearing "1" snapped straight back to 1 and typing 60
 * produced 160 → 100. Valid values commit as typed; blur clamps or restores.
 */
export const NumberField: React.FC<NumberFieldProps> = ({
  value,
  min,
  max,
  onCommit,
  ariaLabel,
  stepper = false,
  widthClass = "w-12",
}) => {
  const [draft, setDraft] = useState(String(value));
  const [editing, setEditing] = useState(false);

  useEffect(() => {
    if (!editing) setDraft(String(value));
  }, [value, editing]);

  const parsed = draft === "" ? NaN : Number(draft);
  const outOfRange = draft !== "" && (parsed < min || parsed > max);
  const clamp = (n: number) => Math.min(max, Math.max(min, n));

  const commitDraft = () => {
    setEditing(false);
    if (draft === "") {
      setDraft(String(value));
      return;
    }
    const n = clamp(parsed);
    setDraft(String(n));
    if (n !== value) onCommit(n);
  };

  const bump = (delta: number) => {
    const n = clamp((Number.isNaN(parsed) ? value : parsed) + delta);
    setDraft(String(n));
    if (n !== value) onCommit(n);
  };

  const field = (
    <input
      type="text"
      inputMode="numeric"
      autoComplete="off"
      aria-label={ariaLabel}
      aria-invalid={outOfRange || undefined}
      title={`${min}–${max}`}
      value={draft}
      onFocus={(e) => {
        setEditing(true);
        e.currentTarget.select();
      }}
      onChange={(e) => {
        const digits = e.target.value.replace(/\D/g, "").slice(0, String(max).length);
        setDraft(digits);
        if (digits !== "") {
          const n = Number(digits);
          if (n >= min && n <= max && n !== value) onCommit(n);
        }
      }}
      onBlur={commitDraft}
      onKeyDown={(e) => {
        if (e.key === "Enter") e.currentTarget.blur();
        else if (e.key === "ArrowUp") {
          e.preventDefault();
          bump(1);
        } else if (e.key === "ArrowDown") {
          e.preventDefault();
          bump(-1);
        }
      }}
      className={`${widthClass} rounded-md border px-1.5 py-1 text-center font-mono text-xs font-semibold text-gray-900 focus:outline-none focus:ring-2 ${
        outOfRange || draft === ""
          ? "border-red-300 focus:border-red-400 focus:ring-red-100"
          : "border-gray-300 focus:border-att-400 focus:ring-att-100"
      }`}
    />
  );

  if (!stepper) return field;
  const btn = "flex h-6 w-6 items-center justify-center rounded-md border border-gray-300 bg-white text-gray-600 hover:bg-gray-50 disabled:opacity-40";
  return (
    <span className="inline-flex items-center gap-1">
      <button type="button" className={btn} onClick={() => bump(-1)} disabled={value <= min} aria-label={`Decrease ${ariaLabel}`}>−</button>
      {field}
      <button type="button" className={btn} onClick={() => bump(1)} disabled={value >= max} aria-label={`Increase ${ariaLabel}`}>+</button>
    </span>
  );
};

// ── Icons ───────────────────────────────────────────────────────────────

const Svg: React.FC<{ d: React.ReactNode; className?: string }> = ({ d, className = "h-3.5 w-3.5" }) => (
  <svg className={className} fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24" aria-hidden="true">
    {d}
  </svg>
);
const GripIcon = () => (
  <svg className="h-4 w-4" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
    {[5, 12, 19].flatMap((y) => [9, 15].map((x) => <circle key={`${x}-${y}`} cx={x} cy={y} r="1.6" />))}
  </svg>
);

// ── Step list ───────────────────────────────────────────────────────────

interface StepListProps {
  steps: DraftStep[];
  onChange: (update: (prev: DraftStep[]) => DraftStep[]) => void;
  isShutdown: boolean;
  liveByName: Map<string, LiveDeployment>;
  /** Live deployments have loaded, so a name missing from them really is missing. */
  liveLoaded: boolean;
  namespace: string;
  highlightUid: string | null;
}

export const SequenceStepList: React.FC<StepListProps> = ({
  steps,
  onChange,
  isShutdown,
  liveByName,
  liveLoaded,
  namespace,
  highlightUid,
}) => {
  const [armedUid, setArmedUid] = useState<string | null>(null);
  const [dragUid, setDragUid] = useState<string | null>(null);
  const [dropIndex, setDropIndex] = useState<number | null>(null);

  // Rows are only draggable while the handle is held, so text selection and
  // clicks in the inputs keep working.
  useEffect(() => {
    if (!armedUid || dragUid) return;
    const disarm = () => setArmedUid(null);
    window.addEventListener("pointerup", disarm);
    return () => window.removeEventListener("pointerup", disarm);
  }, [armedUid, dragUid]);

  const update = (uid: string, changes: Partial<SequenceStep>) =>
    onChange((prev) => prev.map((s) => (s.uid === uid ? { ...s, ...changes } : s)));

  const moveTo = (uid: string, insertion: number) =>
    onChange((prev) => {
      const from = prev.findIndex((s) => s.uid === uid);
      if (from < 0) return prev;
      const to = insertion > from ? insertion - 1 : insertion;
      if (to === from) return prev;
      const items = [...prev];
      const [moved] = items.splice(from, 1);
      items.splice(to, 0, moved);
      return renumber(items);
    });

  const endDrag = () => {
    setDragUid(null);
    setDropIndex(null);
    setArmedUid(null);
  };

  const dragFrom = dragUid ? steps.findIndex((s) => s.uid === dragUid) : -1;
  const draggedStep = dragFrom >= 0 ? steps[dragFrom] : null;
  // Dropping right above or below itself changes nothing; don't draw a target there.
  const effectiveDrop = dropIndex != null && dropIndex !== dragFrom && dropIndex !== dragFrom + 1 ? dropIndex : null;

  const totals = new Map<string, number>();
  for (const s of steps) totals.set(s.deployment_name, (totals.get(s.deployment_name) ?? 0) + 1);
  const seen = new Map<string, number>();
  const lastTarget = new Map<string, number>();

  return (
    <div className="relative">
      {draggedStep && (
        <div className="sticky top-0 z-20 flex items-center gap-2 border-b border-att-200 bg-att-600 px-3 py-2 text-xs font-medium text-white shadow-sm" role="status">
          <Svg d={<><path d="M12 5v14" /><path d="m19 12-7 7-7-7" /></>} />
          Moving step {dragFrom + 1}: <span className="font-mono font-semibold">{draggedStep.deployment_name}</span>
          <span className="opacity-80">— drop it where it should run</span>
        </div>
      )}
      {steps.map((step, idx) => {
        const name = step.deployment_name;
        const occurrence = (seen.get(name) ?? 0) + 1;
        seen.set(name, occurrence);
        const of = totals.get(name) ?? 1;
        const live = liveByName.get(name);
        const missing = liveLoaded && !live;
        const from = lastTarget.has(name) ? lastTarget.get(name) : live?.replicas;
        const target = isShutdown ? 0 : step.replicas;
        lastTarget.set(name, target);
        const isDragging = dragUid === step.uid;
        const showBefore = effectiveDrop === idx;
        const showAfter = effectiveDrop === steps.length && idx === steps.length - 1;
        const waits = !isShutdown && step.wait_condition !== "skip";

        return (
          <div
            key={step.uid}
            data-testid="sequence-step"
            draggable={armedUid === step.uid}
            onDragStart={(e) => {
              setDragUid(step.uid);
              e.dataTransfer.effectAllowed = "move";
              try {
                e.dataTransfer.setData("text/plain", name);
              } catch {
                /* some browsers restrict setData; the drag still works */
              }
              // A compact preview naming the step, instead of a screenshot of the whole card.
              if (typeof e.dataTransfer.setDragImage === "function") {
                const ghost = document.createElement("div");
                ghost.textContent = `Step ${idx + 1} · ${name}${isShutdown ? "" : ` → ${step.replicas} pod${step.replicas === 1 ? "" : "s"}`}`;
                Object.assign(ghost.style, {
                  position: "fixed",
                  top: "-1000px",
                  left: "-1000px",
                  padding: "6px 12px",
                  background: "#246690",
                  color: "#fff",
                  borderRadius: "8px",
                  font: "600 12px ui-monospace, SFMono-Regular, Menlo, monospace",
                  boxShadow: "0 6px 16px rgba(0,0,0,.25)",
                  whiteSpace: "nowrap",
                });
                document.body.appendChild(ghost);
                e.dataTransfer.setDragImage(ghost, 14, 14);
                setTimeout(() => ghost.remove(), 0);
              }
            }}
            onDragOver={(e) => {
              if (!dragUid) return;
              e.preventDefault();
              e.dataTransfer.dropEffect = "move";
              const rect = e.currentTarget.getBoundingClientRect();
              const insertion = e.clientY < rect.top + rect.height / 2 ? idx : idx + 1;
              if (insertion !== dropIndex) setDropIndex(insertion);
            }}
            onDrop={(e) => {
              e.preventDefault();
              if (dragUid && dropIndex != null) moveTo(dragUid, dropIndex);
              endDrag();
            }}
            onDragEnd={endDrag}
            className={`relative border-b border-gray-100 px-3 py-2.5 transition-colors last:border-b-0 ${
              isDragging ? "bg-att-50 opacity-50" : highlightUid === step.uid ? "bg-green-50" : "bg-white hover:bg-gray-50/80"
            }`}
          >
            {showBefore && <div className="pointer-events-none absolute inset-x-2 -top-0.5 z-10 h-1 rounded-full bg-att-500" />}
            {showAfter && <div className="pointer-events-none absolute inset-x-2 -bottom-0.5 z-10 h-1 rounded-full bg-att-500" />}

            <div className="flex items-center gap-2">
              <button
                type="button"
                onPointerDown={() => setArmedUid(step.uid)}
                className="flex h-7 w-5 shrink-0 cursor-grab items-center justify-center rounded text-gray-400 hover:bg-gray-100 hover:text-gray-600 active:cursor-grabbing"
                title="Drag to reorder"
                aria-label={`Drag to reorder step ${idx + 1} ${name}`}
              >
                <GripIcon />
              </button>
              <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-att-100 text-xs font-bold text-att-700">
                {idx + 1}
              </span>
              <div className="min-w-0 flex-1">
                <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-0.5">
                  <span className="truncate font-mono text-[13px] font-semibold text-gray-900" title={name}>{name}</span>
                  {of > 1 && (
                    <span
                      className="shrink-0 rounded-full bg-indigo-50 px-1.5 py-0.5 text-[10px] font-semibold text-indigo-700 ring-1 ring-inset ring-indigo-200"
                      title={`${name} is scaled in ${of} steps of this sequence`}
                    >
                      Scale {occurrence} of {of}
                    </span>
                  )}
                  {missing && (
                    <span
                      className="shrink-0 rounded-full bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800 ring-1 ring-inset ring-amber-200"
                      title={`No deployment named ${name} in ${namespace}; this step will fail`}
                    >
                      Not found in {namespace}
                    </span>
                  )}
                </div>
                {live && (
                  <p className="text-[11px] text-gray-500">
                    Live now: {live.ready_replicas}/{live.replicas} ready
                  </p>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-0.5 text-gray-500">
                <button type="button" onClick={() => moveTo(step.uid, idx - 1)} disabled={idx === 0} className="rounded p-1 hover:bg-gray-100 hover:text-gray-800 disabled:opacity-30" title="Move up" aria-label={`Move step ${idx + 1} up`}>
                  <Svg d={<path d="m18 15-6-6-6 6" />} />
                </button>
                <button type="button" onClick={() => moveTo(step.uid, idx + 2)} disabled={idx === steps.length - 1} className="rounded p-1 hover:bg-gray-100 hover:text-gray-800 disabled:opacity-30" title="Move down" aria-label={`Move step ${idx + 1} down`}>
                  <Svg d={<path d="m6 9 6 6 6-6" />} />
                </button>
                <button
                  type="button"
                  onClick={() =>
                    onChange((prev) => {
                      const items = [...prev];
                      items.splice(idx + 1, 0, { ...step, uid: newStepUid() });
                      return renumber(items);
                    })
                  }
                  className="rounded p-1 hover:bg-gray-100 hover:text-gray-800"
                  title="Duplicate step (scale this deployment again later)"
                  aria-label={`Duplicate step ${idx + 1}`}
                >
                  <Svg d={<><rect x="9" y="9" width="13" height="13" rx="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></>} />
                </button>
                <button
                  type="button"
                  onClick={() => onChange((prev) => renumber(prev.filter((s) => s.uid !== step.uid)))}
                  className="rounded p-1 text-red-400 hover:bg-red-50 hover:text-red-600"
                  title="Remove step"
                  aria-label={`Remove step ${idx + 1}`}
                >
                  <Svg d={<path d="M18 6 6 18M6 6l12 12" />} />
                </button>
              </div>
            </div>

            <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2 pl-14 text-xs text-gray-600">
              {isShutdown ? (
                <span>
                  Scale <span className="font-mono font-semibold">{from ?? "?"}</span> →{" "}
                  <span className="font-mono font-semibold text-red-700">0</span> pods (stop)
                </span>
              ) : (
                <>
                  <span className="flex items-center gap-1.5">
                    Scale{from != null && <span className="font-mono text-gray-500">{from} →</span>}
                    <NumberField
                      value={step.replicas}
                      min={1}
                      max={MAX_REPLICAS}
                      stepper
                      ariaLabel={`Replicas for step ${idx + 1}`}
                      onCommit={(n) => update(step.uid, { replicas: n })}
                    />
                    pods
                  </span>
                  <label className="flex items-center gap-1.5">
                    then
                    <select
                      value={step.wait_condition}
                      onChange={(e) => {
                        const wait = e.target.value as SequenceStep["wait_condition"];
                        const changes: Partial<SequenceStep> = { wait_condition: wait };
                        // Moving between a fixed wait and a pod wait, carry a sensible default.
                        if (wait === "fixed_time" && step.timeout_seconds === DEFAULT_TIMEOUT_SECONDS) changes.timeout_seconds = DEFAULT_FIXED_WAIT_SECONDS;
                        if (wait !== "fixed_time" && step.wait_condition === "fixed_time" && step.timeout_seconds === DEFAULT_FIXED_WAIT_SECONDS) changes.timeout_seconds = DEFAULT_TIMEOUT_SECONDS;
                        update(step.uid, changes);
                      }}
                      className={selectCls}
                      aria-label={`Wait condition for step ${idx + 1}`}
                    >
                      {WAIT_OPTIONS.map((w) => <option key={w.value} value={w.value}>{w.label}</option>)}
                    </select>
                  </label>
                  {waits && (
                    <span className="flex items-center gap-1.5" title={step.wait_condition === "fixed_time" ? "Seconds to wait before the next step" : "Fail the step if not ready within this many seconds"}>
                      {step.wait_condition === "fixed_time" ? "for" : "timeout"}
                      <NumberField
                        value={step.timeout_seconds}
                        min={1}
                        max={MAX_TIMEOUT_SECONDS}
                        widthClass="w-14"
                        ariaLabel={`${step.wait_condition === "fixed_time" ? "Wait seconds" : "Timeout seconds"} for step ${idx + 1}`}
                        onCommit={(n) => update(step.uid, { timeout_seconds: n })}
                      />
                      s
                    </span>
                  )}
                </>
              )}
              <label className="flex items-center gap-1.5">
                if it fails
                <select
                  value={step.on_failure}
                  onChange={(e) => update(step.uid, { on_failure: e.target.value as SequenceStep["on_failure"] })}
                  className={`${selectCls} ${step.on_failure === "continue" ? "text-amber-700" : ""}`}
                  aria-label={`On failure for step ${idx + 1}`}
                >
                  {FAILURE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              </label>
            </div>
          </div>
        );
      })}
    </div>
  );
};
