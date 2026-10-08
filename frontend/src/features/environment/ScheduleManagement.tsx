/**
 * ScheduleManagement – CRUD UI for environment scaling schedules.
 *
 * Grid features (KeyVault-style):
 * - Search toolbar with count badge
 * - Page size selector (10 / 20 / 50 per page)
 * - Bottom pagination: Showing X-Y of Z | « Previous Page N of M Next »
 * - Proper sortable column headers
 */

import React, { useState, useEffect, useRef } from "react";
import { gridStyles, SortableHeader, type SortState, nextSortState } from "../../components/gridStyles";
import { StatusBadge, apiErrorMessage } from "./executionStatus";
import { SequenceExecutionPanel } from "./SequenceRunPanels";
import { NotificationFields, invalidEmails } from "./NotificationFields";
import {
  fetchSchedulePreview,
  type EnvironmentSchedule,
  type EnvironmentSequence,
  type EnvironmentScaleResult,
  type ExecutionHistory,
  type NotifyOn,
  type SchedulePreview,
  type ScheduleCreateRequest,
  type StepDetail,
} from "../../services/environmentApi";

interface Props {
  schedules: EnvironmentSchedule[];
  sequences: EnvironmentSequence[];
  clusterId: string;
  namespaces: string[];
  onCreate: (data: ScheduleCreateRequest) => Promise<void>;
  onUpdate: (id: number, data: Partial<ScheduleCreateRequest>) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
  onRunNow: (id: number) => Promise<EnvironmentScaleResult>;
  /** A sequence run being followed live (Run Now of a sequence-linked schedule). */
  trackedExecution?: ExecutionHistory | null;
  onDismissExecution?: () => void;
  onViewHistory?: () => void;
  isLoading: boolean;
  /** Write role: create, edit, enable/disable, run, and delete. Read-only users only view. */
  canWrite: boolean;
}

type ScheduleField = "job_name" | "namespace" | "operation" | "schedule_type" | "is_enabled" | "last_run_status";

const PAGE_SIZES = [10, 20, 50];
const TIMEZONES = [
  "UTC", "US/Eastern", "US/Central", "US/Mountain", "US/Pacific",
  "Europe/London", "Europe/Berlin", "Asia/Tokyo", "Asia/Kolkata",
];

/** Human-readable description for common cron patterns. */
function describeCron(expr: string): string {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return `cron: ${expr}`;
  const [min, hour, , , dow] = parts;

  const timeStr = `${hour.padStart(2, "0")}:${min.padStart(2, "0")}`;

  const dowMap: Record<string, string> = {
    "*": "every day",
    "1-5": "weekdays (Mon–Fri)",
    "1-6": "Mon–Sat",
    "0,6": "weekends",
    "0": "Sunday",
    "1": "Monday",
    "2": "Tuesday",
    "3": "Wednesday",
    "4": "Thursday",
    "5": "Friday",
    "6": "Saturday",
  };

  const dayDesc = dowMap[dow] || `days: ${dow}`;
  return `Runs at ${timeStr} ${dayDesc}`;
}

const ScheduleManagement: React.FC<Props> = ({
  canWrite,
  schedules,
  sequences,
  clusterId,
  namespaces,
  onCreate,
  onUpdate,
  onDelete,
  onRunNow,
  trackedExecution = null,
  onDismissExecution,
  onViewHistory,
  isLoading,
}) => {
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState<SortState<ScheduleField>>({ key: "job_name", direction: "asc" });
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  // Execution tracking
  const [runningSchedule, setRunningSchedule] = useState<EnvironmentSchedule | null>(null);
  const [execResult, setExecResult] = useState<EnvironmentScaleResult | null>(null);
  const [execElapsed, setExecElapsed] = useState(0);
  const [execRunning, setExecRunning] = useState(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  const handleRunWithTracking = async (s: EnvironmentSchedule) => {
    setRunningSchedule(s);
    setExecResult(null);
    setExecElapsed(0);
    setExecRunning(true);
    const startTime = Date.now();
    timerRef.current = setInterval(() => setExecElapsed(Math.floor((Date.now() - startTime) / 1000)), 1000);
    try {
      const result = await onRunNow(s.id);
      if (result.status === "running") {
        // Sequence-linked: it runs on the server and the live panel follows it.
        setRunningSchedule(null);
        return;
      }
      setExecResult(result);
    } catch { /* handled by parent */ }
    finally {
      setExecRunning(false);
      if (timerRef.current) clearInterval(timerRef.current);
      setExecElapsed(Math.floor((Date.now() - startTime) / 1000));
    }
  };

  const closeExecPanel = () => { setRunningSchedule(null); setExecResult(null); setExecElapsed(0); };
  const formatTime = (s: number) => { const m = Math.floor(s / 60); return m > 0 ? `${m}m ${s % 60}s` : `${s}s`; };

  const defaultForm: ScheduleCreateRequest = {
    job_name: "",
    cluster_id: clusterId,
    namespace: namespaces[0] || "default",
    operation: "scale_up",
    replica_count: 1,
    schedule_type: "daily",
    timezone: "UTC",
    is_enabled: true,
    retry_count: 3,
    notify_on: "always",
  };

  const [form, setForm] = useState<ScheduleCreateRequest>(defaultForm);
  const [formError, setFormError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [preview, setPreview] = useState<{ data: SchedulePreview | null; error: string | null; loading: boolean }>({
    data: null,
    error: null,
    loading: false,
  });

  // The next runs, computed by the server with the same rules the scheduler uses.
  useEffect(() => {
    if (!showForm) return;
    const needsStart = form.schedule_type !== "cron";
    if ((form.schedule_type === "cron" && !form.cron_expression) || (needsStart && !form.start_date)) {
      setPreview({ data: null, error: null, loading: false });
      return;
    }
    let cancelled = false;
    setPreview((p) => ({ ...p, loading: true }));
    const timer = setTimeout(() => {
      fetchSchedulePreview({
        schedule_type: form.schedule_type,
        cron_expression: form.cron_expression,
        timezone: form.timezone ?? "UTC",
        start_date: form.start_date,
        end_date: form.end_date,
      })
        .then((data) => !cancelled && setPreview({ data, error: null, loading: false }))
        .catch((err) => !cancelled && setPreview({ data: null, error: apiErrorMessage(err, "Could not compute the next runs"), loading: false }));
    }, 400);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [showForm, form.schedule_type, form.cron_expression, form.timezone, form.start_date, form.end_date]);

  const formBlockers: string[] = [];
  if (!form.job_name.trim()) formBlockers.push("Enter a job name.");
  if (form.schedule_type === "cron" && !form.cron_expression?.trim()) formBlockers.push("Enter a cron expression.");
  if (form.schedule_type !== "cron" && !form.start_date) {
    formBlockers.push(form.schedule_type === "one_time" ? "Choose when it should run." : "Choose the start date and time; it sets the time of day the schedule runs.");
  }
  if (invalidEmails(form.failure_notification).length) formBlockers.push(`Fix the notification address: ${invalidEmails(form.failure_notification)[0]}`);
  if (preview.error) formBlockers.push(preview.error);

  const filtered = schedules.filter(
    (s) =>
      s.job_name.toLowerCase().includes(search.toLowerCase()) ||
      s.namespace.toLowerCase().includes(search.toLowerCase()) ||
      s.operation.toLowerCase().includes(search.toLowerCase()) ||
      s.schedule_type.toLowerCase().includes(search.toLowerCase()),
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

  const handleSubmit = async () => {
    if (formBlockers.length) {
      setFormError(formBlockers[0]);
      return;
    }
    setSaving(true);
    setFormError(null);
    try {
      if (editingId) {
        // Explicit nulls clear an end date, the extra recipients or the sequence link.
        await onUpdate(editingId, {
          ...form,
          cluster_id: clusterId,
          cron_expression: form.schedule_type === "cron" ? form.cron_expression : null,
          start_date: form.start_date || null,
          end_date: form.end_date || null,
          failure_notification: form.failure_notification?.trim() || null,
          sequence_id: form.sequence_id ?? null,
        } as Partial<ScheduleCreateRequest>);
      } else {
        await onCreate({ ...form, cluster_id: clusterId, failure_notification: form.failure_notification?.trim() || undefined });
      }
      setShowForm(false);
      setEditingId(null);
      setForm(defaultForm);
    } catch (err) {
      setFormError(apiErrorMessage(err, "Could not save the schedule"));
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = (s: EnvironmentSchedule) => {
    setEditingId(s.id);
    setForm({
      job_name: s.job_name,
      cluster_id: s.cluster_id,
      namespace: s.namespace,
      operation: s.operation as "scale_up" | "scale_down",
      replica_count: s.replica_count,
      schedule_type: s.schedule_type as ScheduleCreateRequest["schedule_type"],
      cron_expression: s.cron_expression || undefined,
      timezone: s.timezone,
      start_date: s.start_date ? s.start_date.slice(0, 16) : undefined,
      end_date: s.end_date ? s.end_date.slice(0, 16) : undefined,
      is_enabled: s.is_enabled,
      retry_count: s.retry_count,
      failure_notification: s.failure_notification || undefined,
      notify_on: s.notify_on ?? "always",
      sequence_id: s.sequence_id || undefined,
    });
    setFormError(null);
    setShowForm(true);
  };

  const handleCancelForm = () => {
    setFormError(null);
    setShowForm(false);
    setEditingId(null);
    setForm(defaultForm);
  };

  const handleToggle = async (s: EnvironmentSchedule) => {
    try {
      await onUpdate(s.id, { is_enabled: !s.is_enabled });
    } catch {
      /* the page shows the reason, e.g. a one-time schedule whose time has passed */
    }
  };

  return (
    <div className="space-y-4">
      {/* Create form */}
      {showForm && (
        <div className="rounded-xl border border-att-200 bg-white shadow-sm">
          {/* Form header */}
          <div className="border-b border-gray-200 px-6 py-4">
            <h4 className="text-lg font-semibold text-gray-800">{editingId ? "Edit Schedule" : "New Schedule"}</h4>
            <p className="mt-0.5 text-xs text-gray-500">{editingId ? "Modify the schedule configuration" : "Configure automated environment scaling on a schedule"}</p>
          </div>

          <div className="px-6 py-5 space-y-6">
            {/* Section 1: What to scale */}
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-att-100 text-xs font-bold text-att-700">1</span>
                <h5 className="text-sm font-semibold text-gray-700">What to Scale</h5>
              </div>

              {/* Sequence selector — first, since it controls other fields */}
              <div>
                <label className="text-xs font-semibold text-gray-600">Execution Mode</label>
                <select
                  value={form.sequence_id ?? ""}
                  onChange={(e) => {
                    const seqId = e.target.value ? Number(e.target.value) : undefined;
                    const seq = sequences.find((s) => s.id === seqId);
                    if (seq) {
                      setForm({
                        ...form,
                        sequence_id: seqId,
                        namespace: seq.namespace,
                        operation: seq.sequence_type === "shutdown" ? "scale_down" : "scale_up",
                        replica_count: seq.sequence_type === "shutdown" ? 0 : 1,
                      });
                    } else {
                      setForm({ ...form, sequence_id: undefined });
                    }
                  }}
                  className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
                >
                  <option value="">Scale All — scale entire namespace at once</option>
                  {sequences.map((seq) => (
                    <option key={seq.id} value={seq.id}>
                      Sequence: {seq.name} ({seq.sequence_type}) — {seq.steps.length} steps with dependency order
                    </option>
                  ))}
                </select>
                {form.sequence_id && (
                  <div className="mt-2 rounded-lg bg-att-50 border border-att-100 px-3 py-2 text-xs text-att-700">
                    <span className="font-semibold">Sequence mode:</span> Deployments will be scaled in defined order with wait conditions between each step.
                  </div>
                )}
              </div>

              {/* Namespace / Operation / Replicas — hidden when sequence selected */}
              {!form.sequence_id && (
                <div className="grid grid-cols-3 gap-4">
                  <div>
                    <label className="text-xs font-semibold text-gray-600">Namespace</label>
                    <select value={form.namespace} onChange={(e) => setForm({ ...form, namespace: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm">
                      {namespaces.map((ns) => <option key={ns} value={ns}>{ns}</option>)}
                    </select>
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-gray-600">Operation</label>
                    <select value={form.operation} onChange={(e) => setForm({ ...form, operation: e.target.value as "scale_up" | "scale_down" })} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm">
                      <option value="scale_up">Scale Up</option>
                      <option value="scale_down">Scale Down</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs font-semibold text-gray-600">Replica Count</label>
                    <input type="number" min={0} max={100} value={form.replica_count} onChange={(e) => setForm({ ...form, replica_count: parseInt(e.target.value) || 1 })} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
                  </div>
                </div>
              )}
            </div>

            {/* Section 2: When to run */}
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-att-100 text-xs font-bold text-att-700">2</span>
                <h5 className="text-sm font-semibold text-gray-700">When to Run</h5>
              </div>

              {/* Quick presets */}
              <div>
                <label className="text-xs font-semibold text-gray-600 mb-2 block">Quick Presets</label>
                <div className="flex flex-wrap gap-2">
                  {[
                    { label: "Weekdays 8 AM", cron: "0 8 * * 1-5", type: "cron" as const },
                    { label: "Weekdays 8 PM", cron: "0 20 * * 1-5", type: "cron" as const },
                    { label: "Every Day 6 AM", cron: "0 6 * * *", type: "cron" as const },
                    { label: "Every Day 10 PM", cron: "0 22 * * *", type: "cron" as const },
                    { label: "Mon-Sat 7 AM", cron: "0 7 * * 1-6", type: "cron" as const },
                    { label: "Custom", cron: "", type: "cron" as const },
                  ].map((preset) => (
                    <button
                      key={preset.label}
                      type="button"
                      onClick={() => setForm({ ...form, schedule_type: preset.type, cron_expression: preset.cron || form.cron_expression })}
                      className={`rounded-lg border px-3 py-1.5 text-xs font-medium transition ${
                        form.schedule_type === "cron" && form.cron_expression === preset.cron && preset.cron
                          ? "border-att-400 bg-att-50 text-att-700"
                          : "border-gray-200 text-gray-600 hover:border-att-200 hover:bg-gray-50"
                      }`}
                    >
                      {preset.label}
                    </button>
                  ))}
                </div>
              </div>

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="text-xs font-semibold text-gray-600">Schedule Type</label>
                  <select value={form.schedule_type} onChange={(e) => setForm({ ...form, schedule_type: e.target.value as ScheduleCreateRequest["schedule_type"] })} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm">
                    <option value="one_time">One time</option>
                    <option value="daily">Daily (at the start time)</option>
                    <option value="weekly">Weekly (on the start date's weekday)</option>
                    <option value="monthly">Monthly (on the start date's day)</option>
                    <option value="cron">Cron expression (advanced)</option>
                  </select>
                </div>
                <div>
                  <label className="text-xs font-semibold text-gray-600">Timezone</label>
                  <select value={form.timezone} onChange={(e) => setForm({ ...form, timezone: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm">
                    {TIMEZONES.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
                  </select>
                </div>
              </div>

              {form.schedule_type === "cron" && (
                <div>
                  <label className="text-xs font-semibold text-gray-600">Cron Expression</label>
                  <input value={form.cron_expression || ""} onChange={(e) => setForm({ ...form, cron_expression: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono" placeholder="minute hour day-of-month month day-of-week" />
                  <p className="mt-1 text-xs text-gray-400">
                    {form.cron_expression ? describeCron(form.cron_expression) : "Format: MIN HOUR DOM MON DOW — e.g. \"0 8 * * 1-5\" = 8:00 AM weekdays"}
                  </p>
                </div>
              )}

              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label htmlFor="sched-start" className="text-xs font-semibold text-gray-600">
                    {form.schedule_type === "one_time" ? "Run at" : "Start"}{" "}
                    <span className="font-normal text-gray-400">
                      ({form.schedule_type === "cron" ? "optional, " : ""}{form.timezone} time)
                    </span>
                  </label>
                  <input id="sched-start" type="datetime-local" value={form.start_date || ""} onChange={(e) => setForm({ ...form, start_date: e.target.value || undefined })} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
                  {["daily", "weekly", "monthly"].includes(form.schedule_type) && (
                    <p className="mt-1 text-xs text-gray-400">
                      {form.schedule_type === "daily" ? "Runs every day at this time." : form.schedule_type === "weekly" ? "Runs every week on this weekday at this time." : "Runs every month on this day at this time (the 29th–31st run on the month's last day when it is shorter)."}
                    </p>
                  )}
                </div>
                <div>
                  <label htmlFor="sched-end" className="text-xs font-semibold text-gray-600">End <span className="text-gray-400 font-normal">(optional, {form.timezone} time)</span></label>
                  <input id="sched-end" type="datetime-local" value={form.end_date || ""} onChange={(e) => setForm({ ...form, end_date: e.target.value || undefined })} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm" />
                </div>
              </div>

              <div className="rounded-lg border border-att-100 bg-att-50/50 px-4 py-3" aria-live="polite">
                <p className="text-xs font-semibold text-gray-600">Next runs</p>
                {preview.loading ? (
                  <p className="mt-1 text-xs text-gray-400">Calculating…</p>
                ) : preview.error ? (
                  <p className="mt-1 text-xs text-red-600">{preview.error}</p>
                ) : preview.data && preview.data.runs.length > 0 ? (
                  <ul className="mt-1 space-y-0.5 text-xs text-gray-700">
                    {preview.data.runs.map((r) => <li key={r.utc} className="font-mono">{r.local}</li>)}
                  </ul>
                ) : preview.data ? (
                  <p className="mt-1 text-xs text-amber-700">No upcoming runs (check the start and end dates).</p>
                ) : (
                  <p className="mt-1 text-xs text-gray-400">{form.schedule_type === "cron" ? "Enter a cron expression to see when it will run." : "Choose a start date and time to see when it will run."}</p>
                )}
              </div>
            </div>

            {/* Section 3: Settings */}
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <span className="flex h-6 w-6 items-center justify-center rounded-full bg-att-100 text-xs font-bold text-att-700">3</span>
                <h5 className="text-sm font-semibold text-gray-700">Settings</h5>
              </div>
              <div>
                <label htmlFor="sched-name" className="text-xs font-semibold text-gray-600">Job Name</label>
                <input id="sched-name" value={form.job_name} onChange={(e) => setForm({ ...form, job_name: e.target.value })} className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm md:w-1/2" placeholder="e.g. Dev Morning Scale Up" />
              </div>
              <NotificationFields
                idPrefix="sched"
                notifyOn={(form.notify_on ?? "always") as NotifyOn}
                onNotifyOnChange={(v) => setForm({ ...form, notify_on: v })}
                emails={form.failure_notification ?? ""}
                onEmailsChange={(v) => setForm({ ...form, failure_notification: v || undefined })}
                alwaysIncluded="The schedule's owner (and whoever presses Run now)"
              />
            </div>

            {/* Summary preview */}
            <div className="rounded-lg bg-gray-50 border border-gray-200 px-4 py-3">
              <p className="text-xs font-semibold text-gray-600 mb-1">Schedule Summary</p>
              <p className="text-sm text-gray-800">
                {form.job_name || "Unnamed"} — {form.sequence_id ? `Run sequence (${sequences.find((s) => s.id === form.sequence_id)?.name})` : `${form.operation === "scale_up" ? "Scale Up" : "Scale Down"} to ${form.replica_count} replica(s)`}
                {" "}{form.schedule_type === "cron" && form.cron_expression ? describeCron(form.cron_expression) : form.schedule_type !== "cron" ? form.schedule_type.replace(/_/g, " ") : ""}
                {" "}({form.timezone})
              </p>
            </div>
          </div>

          {/* Form footer */}
          <div className="flex items-center justify-end gap-2 border-t border-gray-200 px-6 py-4">
            {formError && <p className="mr-auto text-sm text-red-600" role="alert">{formError}</p>}
            <button onClick={handleCancelForm} className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">Cancel</button>
            <button onClick={handleSubmit} disabled={!form.job_name || isLoading || saving} className="rounded-lg bg-att-500 px-5 py-2 text-sm font-medium text-white hover:bg-att-600 disabled:opacity-50">{saving ? "Saving…" : editingId ? "Update Schedule" : "Create Schedule"}</button>
          </div>
        </div>
      )}

      {trackedExecution && (
        <SequenceExecutionPanel execution={trackedExecution} onClose={() => onDismissExecution?.()} onViewHistory={onViewHistory} />
      )}

      {/* Execution Progress Panel */}
      {runningSchedule && (
        <div className="rounded-xl border border-att-200 bg-white shadow-sm p-5 space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              {execRunning ? (
                <svg className="h-5 w-5 animate-spin text-att-500" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" /><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v4a4 4 0 00-4 4H4z" /></svg>
              ) : execResult?.status === "completed" ? (
                <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" className="text-green-600"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg>
              ) : (
                <svg width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" className="text-red-600"><circle cx="12" cy="12" r="10" /><path d="m15 9-6 6M9 9l6 6" /></svg>
              )}
              <div>
                <h4 className="text-sm font-semibold text-gray-800">{execRunning ? "Executing Schedule" : "Execution Complete"}</h4>
                <p className="text-xs text-gray-500">{runningSchedule.job_name} — {runningSchedule.namespace}</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 rounded-lg bg-gray-100 px-3 py-1.5">
                <svg width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24" className="text-gray-500"><circle cx="12" cy="12" r="10" /><path d="M12 6v6l4 2" /></svg>
                <span className="font-mono text-sm font-semibold text-gray-700">{formatTime(execElapsed)}</span>
              </div>
              {!execRunning && <button onClick={closeExecPanel} className="rounded-lg border border-gray-300 px-3 py-1.5 text-xs text-gray-600 hover:bg-gray-50">Close</button>}
            </div>
          </div>

          {/* Live progress bar */}
          {execRunning && (
            <div className="space-y-2">
              <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200">
                <div className="h-2 rounded-full bg-gradient-to-r from-att-400 to-att-600 animate-pulse" style={{ width: "70%" }} />
              </div>
              <p className="text-xs text-gray-500 italic">Scaling deployments in progress — please wait...</p>
            </div>
          )}

          {/* Result summary */}
          {execResult && (
            <div className="space-y-4">
              <div className="grid grid-cols-5 gap-3">
                <div className="rounded-lg border border-gray-200 bg-gray-50 p-3 text-center">
                  <div className="text-xl font-bold text-gray-900">{execResult.total_deployments}</div>
                  <div className="text-[10px] font-semibold text-gray-500 uppercase">Total</div>
                </div>
                <div className="rounded-lg border border-green-200 bg-green-50 p-3 text-center">
                  <div className="text-xl font-bold text-green-700">{execResult.completed}</div>
                  <div className="text-[10px] font-semibold text-green-600 uppercase">Completed</div>
                </div>
                <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-center">
                  <div className="text-xl font-bold text-red-700">{execResult.failed}</div>
                  <div className="text-[10px] font-semibold text-red-600 uppercase">Failed</div>
                </div>
                <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-3 text-center">
                  <div className="text-xl font-bold text-yellow-700">{execResult.skipped}</div>
                  <div className="text-[10px] font-semibold text-yellow-600 uppercase">Skipped</div>
                </div>
                <div className="rounded-lg border border-att-200 bg-att-50 p-3 text-center">
                  <div className="text-xl font-bold text-att-700">{formatTime(execElapsed)}</div>
                  <div className="text-[10px] font-semibold text-att-600 uppercase">Duration</div>
                </div>
              </div>

              {/* Completion progress bar */}
              <div className="h-2 w-full overflow-hidden rounded-full bg-gray-200">
                <div className={`h-2 rounded-full transition-all ${execResult.failed > 0 ? "bg-red-500" : "bg-green-500"}`} style={{ width: `${execResult.total_deployments > 0 ? ((execResult.completed + execResult.skipped) / execResult.total_deployments) * 100 : 0}%` }} />
              </div>

              {/* Step details */}
              {execResult.details && execResult.details.length > 0 && (
                <div className="max-h-48 overflow-y-auto rounded-lg border border-gray-200">
                  <table className="w-full text-xs">
                    <thead className="bg-gray-50 sticky top-0">
                      <tr>
                        <th className="px-3 py-2 text-left font-semibold text-gray-600">Deployment</th>
                        <th className="px-3 py-2 text-center font-semibold text-gray-600">Replicas</th>
                        <th className="px-3 py-2 text-center font-semibold text-gray-600">Status</th>
                      </tr>
                    </thead>
                    <tbody>
                      {execResult.details.map((d: StepDetail, i: number) => (
                        <tr key={i} className="border-t border-gray-100">
                          <td className="px-3 py-1.5 font-mono">{d.deployment}</td>
                          <td className="px-3 py-1.5 text-center">{d.target_replicas}</td>
                          <td className="px-3 py-1.5 text-center">
                            <span className={`inline-flex items-center gap-1 text-xs font-medium ${d.status === "completed" ? "text-green-600" : d.status === "failed" ? "text-red-600" : d.status === "skipped" ? "text-yellow-600" : "text-gray-500"}`}>
                              ● {d.status}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {execResult.status === "completed" && (
                <div className="rounded-lg bg-green-50 border border-green-200 px-4 py-2.5 text-sm font-medium text-green-800">
                  Schedule executed successfully in {formatTime(execElapsed)}
                </div>
              )}
              {execResult.failed > 0 && (
                <div className="rounded-lg bg-red-50 border border-red-200 px-4 py-2.5 text-sm font-medium text-red-800">
                  Execution {execResult.status} — {execResult.failed} deployment(s) failed after {formatTime(execElapsed)}
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* Grid */}
      <div className={gridStyles.shell}>
        {/* Toolbar */}
        <div className={gridStyles.panelHeader}>
          <div className="flex flex-wrap items-center gap-3">
            <span className={gridStyles.countBadge}>{filtered.length} schedule{filtered.length !== 1 ? "s" : ""}</span>
          </div>
          <div className="ml-auto flex flex-wrap items-center gap-3">
            <input type="text" placeholder="Search schedules..." value={search} onChange={(e) => { setSearch(e.target.value); setPage(1); }} className={gridStyles.toolbarInput} />
            <select value={pageSize} onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }} className="rounded-lg border border-att-200 bg-white px-2 py-2 text-sm text-gray-700">
              {PAGE_SIZES.map((n) => <option key={n} value={n}>{n} / page</option>)}
            </select>
            {canWrite && <button onClick={() => { setEditingId(null); setForm(defaultForm); setShowForm(!showForm); }} className="rounded-lg bg-att-500 px-4 py-2 text-sm font-medium text-white hover:bg-att-600">+ Create Schedule</button>}
          </div>
        </div>
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              <th className={gridStyles.headerCell}><SortableHeader label="Job Name" active={sort.key === "job_name"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "job_name"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Namespace" active={sort.key === "namespace"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "namespace"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Operation" active={sort.key === "operation"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "operation"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Schedule Type" active={sort.key === "schedule_type"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "schedule_type"))} /></th>
              <th className={gridStyles.headerCellCenter}>Replica Count</th>
              <th className={gridStyles.headerCellCenter}><SortableHeader label="Enabled" active={sort.key === "is_enabled"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "is_enabled"))} /></th>
              <th className={gridStyles.headerCell}>Last Run</th>
              <th className={gridStyles.headerCell}>Next Run</th>
              <th className={gridStyles.headerCellCenter}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginated.map((s) => {
              const linkedSeq = s.sequence_id ? sequences.find((seq) => seq.id === s.sequence_id) : null;
              return (
              <tr key={s.id} className={gridStyles.row}>
                <td className={gridStyles.strongCell}>
                  {s.job_name}
                  {linkedSeq && <span className="ml-2 inline-flex rounded bg-att-50 px-1.5 py-0.5 text-[10px] font-medium text-att-600">Seq: {linkedSeq.name}</span>}
                </td>
                <td className={gridStyles.cell}>{s.namespace}</td>
                <td className={gridStyles.cell}>
                  <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${s.operation === "scale_up" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}>
                    {s.operation === "scale_up" ? "Scale Up" : "Scale Down"}
                  </span>
                </td>
                <td className={gridStyles.cell}>
                  <span className="text-sm">{s.schedule_description ?? s.schedule_type.replace(/_/g, " ")}</span>
                  {s.notify_on === "never" ? (
                    <span className="block text-[11px] text-gray-400">No emails</span>
                  ) : s.notify_on === "failure" ? (
                    <span className="block text-[11px] text-gray-400">Emails on failure</span>
                  ) : null}
                </td>
                <td className={gridStyles.centerCell}>{s.replica_count}</td>
                <td className={gridStyles.centerCell}>
                  {canWrite ? (
                    <button onClick={() => handleToggle(s)} className={`relative inline-flex h-6 w-11 rounded-full transition ${s.is_enabled ? "bg-green-500" : "bg-gray-300"}`}>
                      <span className={`inline-block h-5 w-5 transform rounded-full bg-white shadow transition ${s.is_enabled ? "translate-x-5" : "translate-x-0.5"} mt-0.5`} />
                    </button>
                  ) : (
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${s.is_enabled ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-600"}`}>
                      {s.is_enabled ? "Enabled" : "Disabled"}
                    </span>
                  )}
                </td>
                <td className={gridStyles.cell}>
                  {s.last_run_at ? (
                    <div>
                      <div className="text-xs">{new Date(s.last_run_at).toLocaleString()}</div>
                      {s.last_run_status && <StatusBadge status={s.last_run_status} />}
                    </div>
                  ) : (
                    <span className="text-xs text-gray-400">Never</span>
                  )}
                </td>
                <td className={gridStyles.cell}>
                  {s.next_run_at && s.is_enabled ? (
                    <span className="text-xs" title={s.next_run_at_utc ? `${new Date(s.next_run_at_utc).toUTCString()}` : undefined}>
                      {/* next_run_at is wall-clock time in the schedule's timezone */}
                      {new Date(s.next_run_at).toLocaleString([], { weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                      <span className="block text-[11px] text-gray-400">{s.timezone}</span>
                    </span>
                  ) : (
                    <span className="text-xs text-gray-400">-</span>
                  )}
                </td>
                <td className={gridStyles.centerCell}>
                  {!canWrite ? <span className="text-xs text-gray-400">—</span> : (
                  <div className="flex items-center justify-center gap-1">
                    <button onClick={() => handleRunWithTracking(s)} disabled={isLoading || execRunning} className="rounded bg-green-500 px-2 py-1 text-xs font-medium text-white hover:bg-green-600 disabled:opacity-50" title="Run Now">
                      <svg width="12" height="12" fill="currentColor" viewBox="0 0 24 24"><path d="M8 5v14l11-7z" /></svg>
                    </button>
                    <button onClick={() => handleEdit(s)} className="rounded p-1 text-blue-500 hover:bg-blue-50" title="Edit Schedule">
                      <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg>
                    </button>
                    <button onClick={() => onDelete(s.id)} className="rounded p-1 text-red-500 hover:bg-red-50" title="Delete Schedule">
                      <svg width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2" viewBox="0 0 24 24"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>
                    </button>
                  </div>
                  )}
                </td>
              </tr>
              );
            })}
            {paginated.length === 0 && (
              <tr><td colSpan={9} className="px-4 py-8 text-center text-sm text-gray-400">No schedules found</td></tr>
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

export default ScheduleManagement;
