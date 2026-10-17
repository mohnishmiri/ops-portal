/**
 * Automatic stop / start of Atlas clusters.
 *
 * A schedule covers one or more clusters and has two optional legs — stop
 * and start. Recurring legs are cron expressions built from a day preset and
 * a time (or typed by hand); one-time legs are a date and time. Both are read
 * in the schedule's timezone, and the editor previews the next runs as the
 * backend computes them, so what you see is what the runner will do.
 *
 * Gating matches the API: changes need write + "atlas_schedule_manage", and
 * "Run now" additionally needs "atlas_cluster_power".
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { gridStyles, SortableHeader } from "../../components/gridStyles";
import { ConfirmDialog, GridHeader, GridMessageRow, GridPagerBar, Modal, textMatches, useGridRows } from "../access/accessShared";
import { TIMEZONE_OPTIONS, usePortalTimezone } from "../../contexts/TimezoneContext";
import { formatAxiosError } from "../../services/apiErrors";
import {
  type AtlasCluster,
  type AtlasSchedule,
  type Leg,
  type NotifyOn,
  type ScheduleInput,
  useDeleteSchedule,
  useRunScheduleLeg,
  useSaveSchedule,
  useSchedulePreview,
  useSchedules,
  useSkipScheduleLeg,
} from "../../services/mongodbAtlasApi";
import { invalidEmails, NOTIFY_OPTIONS } from "../environment/NotificationFields";
import { OperationProgress } from "./PowerDialog";
import {
  ATLAS_PAGE_SIZE,
  AtlasIcons,
  buttonTone,
  clusterKey,
  EnvironmentChip,
  IconAction,
  InfoNote,
  inputClass,
  labelClass,
  OperationStatusChip,
  relativeTime,
  useAtlasCan,
} from "./shared";

// ── Cron helpers ─────────────────────────────────────────────────────────────

const DAY_PRESETS = [
  { value: "1-5", label: "Weekdays (Mon–Fri)" },
  { value: "*", label: "Every day" },
  { value: "0,6", label: "Weekends (Sat, Sun)" },
  { value: "1-6", label: "Mon–Sat" },
];

/** "0 20 * * 1-5" → { days: "1-5", time: "20:00" } when it fits a preset. */
export function parsePresetCron(cron: string | null): { days: string; time: string } | null {
  const match = /^(\d{1,2}) (\d{1,2}) \* \* (\S+)$/.exec(cron ?? "");
  if (!match || !DAY_PRESETS.some((p) => p.value === match[3])) return null;
  return { days: match[3], time: `${match[2].padStart(2, "0")}:${match[1].padStart(2, "0")}` };
}

export function buildCron(days: string, time: string): string {
  const [h, m] = time.split(":").map((v) => Number(v));
  return `${m || 0} ${h || 0} * * ${days}`;
}

// ── Form state ───────────────────────────────────────────────────────────────

interface FormState {
  name: string;
  description: string;
  targets: Record<string, AtlasCluster | { project_id: string; project_name?: string | null; cluster_name: string }>;
  scheduleType: "recurring" | "one_time";
  mode: "preset" | "cron";
  days: string;
  stopEnabled: boolean;
  startEnabled: boolean;
  stopTime: string;
  startTime: string;
  stopCron: string;
  startCron: string;
  stopAt: string;
  startAt: string;
  timezone: string;
  notifyOn: NotifyOn;
  emails: string;
  remind: number;
  enabled: boolean;
  ackProduction: boolean;
}

function initialForm(schedule: AtlasSchedule | null, clusters: AtlasCluster[], portalTz: string): FormState {
  const targets: FormState["targets"] = {};
  for (const t of schedule?.targets ?? []) {
    const match = clusters.find((c) => c.project_id === t.project_id && c.name === t.cluster_name);
    targets[`${t.project_id}/${t.cluster_name}`] = match ?? t;
  }
  const stopPreset = parsePresetCron(schedule?.stop_cron ?? null);
  const startPreset = parsePresetCron(schedule?.start_cron ?? null);
  const presetOk =
    !schedule ||
    schedule.schedule_type === "one_time" ||
    ((!schedule.stop_cron || stopPreset) && (!schedule.start_cron || startPreset) && (!stopPreset || !startPreset || stopPreset.days === startPreset.days));
  return {
    name: schedule?.name ?? "",
    description: schedule?.description ?? "",
    targets,
    scheduleType: schedule?.schedule_type ?? "recurring",
    mode: presetOk ? "preset" : "cron",
    days: stopPreset?.days ?? startPreset?.days ?? "1-5",
    stopEnabled: schedule ? Boolean(schedule.stop_cron || schedule.stop_at) : true,
    startEnabled: schedule ? Boolean(schedule.start_cron || schedule.start_at) : true,
    stopTime: stopPreset?.time ?? "20:00",
    startTime: startPreset?.time ?? "07:00",
    stopCron: schedule?.stop_cron ?? "0 20 * * 1-5",
    startCron: schedule?.start_cron ?? "0 7 * * 1-5",
    stopAt: schedule?.stop_at?.slice(0, 16) ?? "",
    startAt: schedule?.start_at?.slice(0, 16) ?? "",
    timezone: schedule?.timezone ?? portalTz ?? "UTC",
    notifyOn: schedule?.notify_on ?? "always",
    emails: schedule?.notification_emails ?? "",
    remind: schedule?.remind_minutes_before ?? 30,
    enabled: schedule?.is_enabled ?? true,
    ackProduction: false,
  };
}

function timing(form: FormState) {
  if (form.scheduleType === "one_time") {
    return {
      schedule_type: "one_time" as const,
      stop_cron: null,
      start_cron: null,
      stop_at: form.stopEnabled && form.stopAt ? form.stopAt : null,
      start_at: form.startEnabled && form.startAt ? form.startAt : null,
    };
  }
  const stop = form.stopEnabled ? (form.mode === "preset" ? buildCron(form.days, form.stopTime) : form.stopCron.trim()) : null;
  const start = form.startEnabled ? (form.mode === "preset" ? buildCron(form.days, form.startTime) : form.startCron.trim()) : null;
  return { schedule_type: "recurring" as const, stop_cron: stop || null, start_cron: start || null, stop_at: null, start_at: null };
}

// ── Editor ───────────────────────────────────────────────────────────────────

const ClusterPicker: React.FC<{
  clusters: AtlasCluster[];
  selected: FormState["targets"];
  onToggle: (cluster: AtlasCluster) => void;
}> = ({ clusters, selected, onToggle }) => {
  const [q, setQ] = useState("");
  const shown = clusters.filter((c) => !q || textMatches(q.toLowerCase(), c.name, c.project_name, c.environment));
  return (
    <div className="rounded-lg border border-att-200">
      <div className="border-b border-att-100 bg-att-50/50 px-3 py-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a cluster…" aria-label="Find a cluster" className={inputClass} />
      </div>
      <ul className="max-h-48 divide-y divide-att-50 overflow-y-auto">
        {shown.map((c) => {
          const key = clusterKey(c);
          const checked = key in selected;
          return (
            <li key={key}>
              <label
                className={`flex items-center gap-2 px-3 py-1.5 text-sm ${c.pausable ? "cursor-pointer hover:bg-att-50/50" : "cursor-not-allowed opacity-50"}`}
                title={c.pausable ? undefined : c.pause_blocker ?? "Cannot be paused"}
              >
                <input type="checkbox" checked={checked} disabled={!c.pausable && !checked} onChange={() => onToggle(c)} className="h-4 w-4 rounded border-att-300" />
                <span className="font-mono text-slate-800">{c.name}</span>
                <span className="text-xs text-slate-500">{c.project_name}</span>
                <span className="text-xs text-slate-400">{c.tier}</span>
                <span className="ml-auto">
                  <EnvironmentChip environment={c.environment} />
                </span>
              </label>
            </li>
          );
        })}
        {shown.length === 0 && <li className="px-3 py-3 text-center text-xs text-slate-400">No cluster matches.</li>}
      </ul>
    </div>
  );
};

const LegFields: React.FC<{ form: FormState; set: (patch: Partial<FormState>) => void; leg: Leg }> = ({ form, set, leg }) => {
  const enabledKey = leg === "stop" ? "stopEnabled" : "startEnabled";
  const enabled = form[enabledKey];
  const label = leg === "stop" ? "Stop (pause)" : "Start (resume)";
  return (
    <div className={`rounded-lg border p-3 ${enabled ? (leg === "stop" ? "border-red-100 bg-red-50/30" : "border-green-100 bg-green-50/30") : "border-att-100"}`}>
      <label className="flex items-center gap-2 text-sm font-semibold text-slate-800">
        <input type="checkbox" checked={enabled} onChange={(e) => set({ [enabledKey]: e.target.checked } as Partial<FormState>)} className="h-4 w-4 rounded border-att-300" />
        {label}
      </label>
      {enabled && (
        <div className="mt-2">
          {form.scheduleType === "one_time" ? (
            <input
              type="datetime-local"
              aria-label={`${label} date and time`}
              value={leg === "stop" ? form.stopAt : form.startAt}
              onChange={(e) => set(leg === "stop" ? { stopAt: e.target.value } : { startAt: e.target.value })}
              className={inputClass}
            />
          ) : form.mode === "preset" ? (
            <input
              type="time"
              aria-label={`${label} time`}
              value={leg === "stop" ? form.stopTime : form.startTime}
              onChange={(e) => set(leg === "stop" ? { stopTime: e.target.value } : { startTime: e.target.value })}
              className={inputClass}
            />
          ) : (
            <input
              aria-label={`${label} cron`}
              value={leg === "stop" ? form.stopCron : form.startCron}
              onChange={(e) => set(leg === "stop" ? { stopCron: e.target.value } : { startCron: e.target.value })}
              placeholder="minute hour day month weekday"
              className={`${inputClass} font-mono`}
            />
          )}
        </div>
      )}
    </div>
  );
};

export const ScheduleEditor: React.FC<{
  schedule: AtlasSchedule | null;
  clusters: AtlasCluster[];
  onClose: () => void;
  onSaved: (schedule: AtlasSchedule) => void;
}> = ({ schedule, clusters, onClose, onSaved }) => {
  const { timezone: portalTz, formatDate } = usePortalTimezone();
  const [form, setForm] = useState<FormState>(() => initialForm(schedule, clusters, portalTz));
  const set = useCallback((patch: Partial<FormState>) => setForm((f) => ({ ...f, ...patch })), []);
  const save = useSaveSchedule();

  const t = timing(form);
  const previewParams = useMemo(() => {
    const params: Record<string, string | undefined> = { schedule_type: t.schedule_type, timezone: form.timezone };
    if (t.stop_cron) params.stop_cron = t.stop_cron;
    if (t.start_cron) params.start_cron = t.start_cron;
    if (t.stop_at) params.stop_at = t.stop_at;
    if (t.start_at) params.start_at = t.start_at;
    return t.stop_cron || t.start_cron || t.stop_at || t.start_at ? params : null;
  }, [t.schedule_type, t.stop_cron, t.start_cron, t.stop_at, t.start_at, form.timezone]);
  // Debounce: preview once typing pauses.
  const [debounced, setDebounced] = useState(previewParams);
  const previewKey = JSON.stringify(previewParams);
  useEffect(() => {
    const handle = window.setTimeout(() => setDebounced(previewParams), 400);
    return () => window.clearTimeout(handle);
  }, [previewKey]);
  const preview = useSchedulePreview(debounced);

  const targets = Object.values(form.targets);
  const production = targets.filter((x): x is AtlasCluster => "is_production" in x && x.is_production);
  const badEmails = invalidEmails(form.emails);
  const blockers: string[] = [];
  if (!form.name.trim()) blockers.push("Name the schedule.");
  if (!targets.length) blockers.push("Choose at least one cluster.");
  if (!(t.stop_cron || t.start_cron || t.stop_at || t.start_at)) blockers.push("Give a stop time, a start time, or both.");
  if (preview.data && !preview.data.valid) blockers.push(preview.data.error ?? "The timing is not valid.");
  if (badEmails.length) blockers.push(`Not a valid email address: ${badEmails.slice(0, 2).join(", ")}`);
  if (production.length && !form.ackProduction) blockers.push("Confirm that this schedule may stop production clusters.");

  const submit = () => {
    const input: ScheduleInput = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      targets: targets.map((x) => ("name" in x ? { project_id: x.project_id, project_name: x.project_name, cluster_name: x.name } : x)),
      ...t,
      timezone: form.timezone,
      is_enabled: form.enabled,
      notify_on: form.notifyOn,
      notification_emails: form.emails.trim() || null,
      remind_minutes_before: form.notifyOn === "never" ? 0 : form.remind,
      acknowledge_production: form.ackProduction,
    };
    save.mutate({ id: schedule?.id, input }, { onSuccess: onSaved });
  };

  const tzOptions = TIMEZONE_OPTIONS.some((o) => o.value === form.timezone)
    ? TIMEZONE_OPTIONS
    : [{ value: form.timezone, label: form.timezone }, ...TIMEZONE_OPTIONS];

  return (
    <Modal
      title={schedule ? `Edit schedule — ${schedule.name}` : "New start/stop schedule"}
      subtitle="Runs in the background on every portal replica; exactly one of them acts on each run."
      onClose={onClose}
      widthClass="max-w-4xl"
      footer={
        <>
          <button type="button" onClick={onClose} className={buttonTone.neutral} disabled={save.isPending}>
            Cancel
          </button>
          <button type="button" onClick={submit} className={buttonTone.primary} disabled={blockers.length > 0 || save.isPending}>
            {save.isPending ? "Saving…" : schedule ? "Save changes" : "Create schedule"}
          </button>
        </>
      }
    >
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label htmlFor="sch-name" className={labelClass}>Name</label>
          <input id="sch-name" value={form.name} maxLength={200} onChange={(e) => set({ name: e.target.value })} placeholder="Non-prod off-hours" className={inputClass} />
        </div>
        <div>
          <label htmlFor="sch-desc" className={labelClass}>Description <span className="font-normal text-slate-400">(optional)</span></label>
          <input id="sch-desc" value={form.description} maxLength={2000} onChange={(e) => set({ description: e.target.value })} className={inputClass} />
        </div>
      </div>

      <div>
        <p className={labelClass}>Clusters ({targets.length} selected) — only M10+ clusters without NVMe storage can be paused</p>
        <ClusterPicker
          clusters={clusters}
          selected={form.targets}
          onToggle={(c) =>
            setForm((f) => {
              const next = { ...f.targets };
              const key = clusterKey(c);
              if (key in next) delete next[key];
              else next[key] = c;
              return { ...f, targets: next };
            })
          }
        />
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <div>
          <label htmlFor="sch-type" className={labelClass}>Repeats</label>
          <select id="sch-type" value={form.scheduleType} onChange={(e) => set({ scheduleType: e.target.value as FormState["scheduleType"] })} className={inputClass}>
            <option value="recurring">Recurring</option>
            <option value="one_time">Once</option>
          </select>
        </div>
        {form.scheduleType === "recurring" && (
          <div>
            <label htmlFor="sch-days" className={labelClass}>Days</label>
            <select
              id="sch-days"
              value={form.mode === "cron" ? "cron" : form.days}
              onChange={(e) => (e.target.value === "cron" ? set({ mode: "cron", stopCron: t.stop_cron ?? form.stopCron, startCron: t.start_cron ?? form.startCron }) : set({ mode: "preset", days: e.target.value }))}
              className={inputClass}
            >
              {DAY_PRESETS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
              <option value="cron">Custom (cron expressions)</option>
            </select>
          </div>
        )}
        <div>
          <label htmlFor="sch-tz" className={labelClass}>Timezone</label>
          <select id="sch-tz" value={form.timezone} onChange={(e) => set({ timezone: e.target.value })} className={inputClass}>
            {tzOptions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <LegFields form={form} set={set} leg="stop" />
        <LegFields form={form} set={set} leg="start" />
      </div>
      {form.mode === "cron" && form.scheduleType === "recurring" && (
        <p className="text-xs text-slate-500">
          Standard cron: minute hour day-of-month month day-of-week (0 or 7 = Sunday). Each leg may run at most once an hour.
        </p>
      )}

      <div className="rounded-lg border border-att-100 bg-att-50/40 p-3">
        <p className="text-xs font-semibold text-slate-600">Next runs ({form.timezone})</p>
        {!debounced ? (
          <p className="mt-1 text-xs text-slate-400">Choose a stop or start time to see when it runs.</p>
        ) : preview.isLoading ? (
          <p className="mt-1 text-xs text-slate-400">Working it out…</p>
        ) : preview.data && !preview.data.valid ? (
          <p className="mt-1 text-xs text-red-600">{preview.data.error}</p>
        ) : preview.data ? (
          <div className="mt-1 grid gap-3 text-xs md:grid-cols-2">
            {(["stop", "start"] as const).map((leg) =>
              preview.data![leg].length ? (
                <div key={leg}>
                  <span className={leg === "stop" ? "font-semibold text-red-700" : "font-semibold text-green-700"}>
                    {leg === "stop" ? "Stop" : "Start"}
                  </span>{" "}
                  <span className="text-slate-500">{leg === "stop" ? preview.data!.stop_description : preview.data!.start_description}</span>
                  <ul className="mt-1 space-y-0.5 text-slate-700">
                    {preview.data![leg].map((at) => (
                      <li key={at}>{new Date(at).toLocaleString(undefined, { timeZone: form.timezone, weekday: "short", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}</li>
                    ))}
                  </ul>
                </div>
              ) : null,
            )}
          </div>
        ) : null}
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <div>
          <label htmlFor="sch-notify" className={labelClass}>Email a summary</label>
          <select id="sch-notify" value={form.notifyOn} onChange={(e) => set({ notifyOn: e.target.value as NotifyOn })} className={inputClass}>
            {NOTIFY_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label htmlFor="sch-remind" className={labelClass}>Heads-up email before each run</label>
          <select
            id="sch-remind"
            value={form.remind}
            disabled={form.notifyOn === "never"}
            onChange={(e) => set({ remind: Number(e.target.value) })}
            className={inputClass}
          >
            <option value={0}>None</option>
            <option value={15}>15 minutes before</option>
            <option value={30}>30 minutes before</option>
            <option value={60}>1 hour before</option>
            <option value={120}>2 hours before</option>
            <option value={1440}>1 day before</option>
          </select>
        </div>
        <div>
          <label htmlFor="sch-emails" className={labelClass}>Also send to</label>
          <input
            id="sch-emails"
            value={form.emails}
            disabled={form.notifyOn === "never"}
            onChange={(e) => set({ emails: e.target.value })}
            placeholder="team-dl@att.com"
            aria-invalid={badEmails.length > 0 || undefined}
            className={`${inputClass} ${badEmails.length ? "border-red-300" : ""}`}
          />
        </div>
      </div>
      <p className="-mt-2 text-xs text-slate-400">
        {schedule ? "The schedule's creator" : "You"} always receive{schedule ? "s" : ""} the summaries. A summary is sent when Atlas has finished — it says which clusters stopped or started and why any failed.
      </p>

      <label className="flex items-center gap-2 text-sm text-slate-700">
        <input type="checkbox" checked={form.enabled} onChange={(e) => set({ enabled: e.target.checked })} className="h-4 w-4 rounded border-att-300" />
        Enabled
      </label>

      {production.length > 0 && (
        <label className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          <input type="checkbox" checked={form.ackProduction} onChange={(e) => set({ ackProduction: e.target.checked })} className="mt-0.5 h-4 w-4 rounded border-red-300" />
          <span>
            {production.map((c) => c.name).join(", ")} {production.length === 1 ? "is" : "are"} production or unclassified. I confirm this schedule may stop{" "}
            {production.length === 1 ? "it" : "them"}.
          </span>
        </label>
      )}

      {blockers.length > 0 && !save.isPending && (
        <InfoNote tone="warning">
          <ul className="list-disc pl-4">
            {blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </InfoNote>
      )}
      {save.isError && <InfoNote tone="error">{formatAxiosError(save.error, "Could not save the schedule")}</InfoNote>}
      {schedule && <p className="text-[11px] text-slate-400">Last changed by {schedule.updated_by ?? schedule.created_by}, {formatDate(schedule.updated_at)}.</p>}
    </Modal>
  );
};

// ── Grid ─────────────────────────────────────────────────────────────────────

type SortKey = "name" | "next" | "clusters" | "status";

function nextOf(s: AtlasSchedule): string {
  return [s.next_stop_at, s.next_start_at].filter(Boolean).sort()[0] ?? "9999";
}

const LegCell: React.FC<{ s: AtlasSchedule; leg: Leg; formatDate: (v: string | null | undefined) => string }> = ({ s, leg, formatDate }) => {
  const description = leg === "stop" ? s.stop_description : s.start_description;
  const next = leg === "stop" ? s.next_stop_at : s.next_start_at;
  const skipped = leg === "stop" ? s.skip_next_stop : s.skip_next_start;
  if (!description) return <span className="text-xs text-slate-400">—</span>;
  return (
    <div>
      <div className="text-slate-800">{description}</div>
      {next && s.is_enabled && (
        <div className={`text-[11px] ${skipped ? "text-amber-700" : "text-slate-500"}`} title={formatDate(next)}>
          {skipped ? "next run skipped · " : "next "}
          {relativeTime(next)}
        </div>
      )}
    </div>
  );
};

export const ScheduleManager: React.FC<{ clusters: AtlasCluster[]; formatDate: (v: string | null | undefined) => string }> = ({ clusters, formatDate }) => {
  const can = useAtlasCan();
  const canManage = can("atlas_schedule_manage");
  const canRun = canManage && can("atlas_cluster_power");
  const { data, isLoading, error } = useSchedules();
  const remove = useDeleteSchedule();
  const skip = useSkipScheduleLeg();
  const run = useRunScheduleLeg();
  const save = useSaveSchedule();
  const [editing, setEditing] = useState<AtlasSchedule | null | "new">(null);
  const [deleting, setDeleting] = useState<AtlasSchedule | null>(null);
  const [running, setRunning] = useState<{ schedule: AtlasSchedule; leg: Leg } | null>(null);
  const [runOpId, setRunOpId] = useState<number | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const rows = useMemo(() => data ?? [], [data]);
  const grid = useGridRows<AtlasSchedule, SortKey>(rows, {
    matches: useCallback(
      (s: AtlasSchedule, q: string) => textMatches(q, s.name, s.description, s.created_by, ...s.targets.map((t) => `${t.project_name} ${t.cluster_name}`)),
      [],
    ),
    accessor: useCallback((s: AtlasSchedule, key: SortKey) => {
      if (key === "next") return s.is_enabled ? nextOf(s) : "9999z";
      if (key === "clusters") return s.targets.length;
      if (key === "status") return s.last_run_status ?? "";
      return s.name.toLowerCase();
    }, []),
    initialSort: { key: "next", direction: "asc" },
    pageSize: ATLAS_PAGE_SIZE,
  });

  const header = (label: string, key: SortKey) => (
    <th className={gridStyles.headerCell}>
      <SortableHeader label={label} active={grid.sort.key === key} direction={grid.sort.direction} onClick={() => grid.toggleSort(key)} />
    </th>
  );
  const onError = (e: unknown) => setActionError(formatAxiosError(e, "The change failed"));

  return (
    <div className="space-y-3">
      <InfoNote>
        Schedules stop and start clusters automatically. Atlas bills a paused cluster for storage only, will not pause one within
        60 minutes of starting it, and starts any cluster left paused for 30 days.
      </InfoNote>
      {actionError && <InfoNote tone="error">{actionError}</InfoNote>}
      <div className={gridStyles.shell}>
        <GridHeader
          title="Start/stop schedules"
          subtitle={`${rows.filter((s) => s.is_enabled).length} enabled of ${rows.length}`}
          search={grid.search}
          onSearch={grid.setSearch}
          placeholder="Search name, cluster, owner…"
        >
          {canManage && (
            <button type="button" className={buttonTone.primary} onClick={() => setEditing("new")}>
              <AtlasIcons.plus />
              New schedule
            </button>
          )}
        </GridHeader>
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                {header("Schedule", "name")}
                {header("Clusters", "clusters")}
                <th className={gridStyles.headerCell}>Stop</th>
                <th className={gridStyles.headerCell}>Start</th>
                {header("Last run", "status")}
                {header("Next", "next")}
                <th className={gridStyles.headerCellCenter}>Enabled</th>
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <GridMessageRow colSpan={8}>Loading schedules…</GridMessageRow>
              ) : error ? (
                <GridMessageRow colSpan={8} tone="error">
                  {formatAxiosError(error, "Could not load schedules")}
                </GridMessageRow>
              ) : grid.pageRows.length === 0 ? (
                <GridMessageRow colSpan={8}>{rows.length ? "No schedule matches." : "No schedules yet."}</GridMessageRow>
              ) : (
                grid.pageRows.map((s) => (
                  <tr key={s.id} className={gridStyles.row}>
                    <td className={gridStyles.strongCell}>
                      {s.name}
                      <div className="text-[11px] font-normal text-slate-500">
                        {s.schedule_type === "one_time" ? "Once" : "Recurring"} · {s.timezone}
                        {s.remind_minutes_before ? ` · heads-up ${s.remind_minutes_before}m` : ""}
                      </div>
                      {s.description && <div className="text-[11px] font-normal text-slate-400">{s.description}</div>}
                    </td>
                    <td className={gridStyles.cell}>
                      <div className="max-w-[16rem] truncate font-mono text-xs" title={s.targets.map((t) => `${t.project_name}/${t.cluster_name}`).join("\n")}>
                        {s.targets.map((t) => t.cluster_name).join(", ")}
                      </div>
                      <div className="text-[11px] text-slate-500">{s.targets.length} cluster{s.targets.length === 1 ? "" : "s"}</div>
                    </td>
                    <td className={gridStyles.cell}>
                      <LegCell s={s} leg="stop" formatDate={formatDate} />
                    </td>
                    <td className={gridStyles.cell}>
                      <LegCell s={s} leg="start" formatDate={formatDate} />
                    </td>
                    <td className={gridStyles.cell}>
                      {s.last_run_status ? <OperationStatusChip status={s.last_run_status} /> : <span className="text-xs text-slate-400">Not run yet</span>}
                    </td>
                    <td className={gridStyles.cell}>
                      {s.is_enabled && nextOf(s) !== "9999" ? <span title={formatDate(nextOf(s))}>{relativeTime(nextOf(s))}</span> : <span className="text-xs text-slate-400">—</span>}
                    </td>
                    <td className={gridStyles.centerCell}>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={s.is_enabled}
                        aria-label={`${s.is_enabled ? "Disable" : "Enable"} ${s.name}`}
                        disabled={!canManage || save.isPending}
                        onClick={() => save.mutate({ id: s.id, input: { is_enabled: !s.is_enabled } }, { onError })}
                        className={`relative inline-flex h-5 w-9 items-center rounded-full transition disabled:opacity-50 ${s.is_enabled ? "bg-att-500" : "bg-slate-300"}`}
                      >
                        <span className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition ${s.is_enabled ? "translate-x-4" : "translate-x-0.5"}`} />
                      </button>
                    </td>
                    <td className={gridStyles.centerCell}>
                      <div className="flex items-center justify-center gap-0.5">
                        {(["stop", "start"] as const).map((leg) => {
                          const next = leg === "stop" ? s.next_stop_at : s.next_start_at;
                          const skipped = leg === "stop" ? s.skip_next_stop : s.skip_next_start;
                          return (
                            <IconAction
                              key={leg}
                              title={skipped ? `Un-skip the next ${leg}` : `Skip the next ${leg} only${next ? ` (${relativeTime(next)})` : ""}`}
                              tone={skipped ? "amber" : leg === "stop" ? "red" : "green"}
                              disabled={!canManage || !next || !s.is_enabled || skip.isPending}
                              onClick={() => skip.mutate({ id: s.id, leg, skip: !skipped }, { onError })}
                            >
                              <AtlasIcons.skip />
                            </IconAction>
                          );
                        })}
                        <IconAction
                          title="Run the stop or start now"
                          tone="att"
                          disabled={!canRun}
                          onClick={() => setRunning({ schedule: s, leg: s.stop_description ? "stop" : "start" })}
                        >
                          <AtlasIcons.bolt />
                        </IconAction>
                        <IconAction title="Edit" disabled={!canManage} onClick={() => setEditing(s)}>
                          <AtlasIcons.edit />
                        </IconAction>
                        <IconAction title="Delete" tone="red" disabled={!canManage} onClick={() => setDeleting(s)}>
                          <AtlasIcons.trash />
                        </IconAction>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <GridPagerBar page={grid.page} totalPages={grid.totalPages} total={grid.total} pageSize={grid.pageSize} onPage={grid.setPage} noun="schedules" />
      </div>

      {editing && (
        <ScheduleEditor
          schedule={editing === "new" ? null : editing}
          clusters={clusters}
          onClose={() => setEditing(null)}
          onSaved={() => setEditing(null)}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title="Delete schedule"
          message={
            <>
              Delete <b>{deleting.name}</b>? Its clusters stay as they are now; past runs remain in Activity and the audit log.
            </>
          }
          confirmLabel="Delete"
          busy={remove.isPending}
          error={remove.isError ? formatAxiosError(remove.error, "Delete failed") : null}
          onCancel={() => setDeleting(null)}
          onConfirm={() => remove.mutate(deleting.id, { onSuccess: () => setDeleting(null) })}
        />
      )}
      {running && (
        <Modal
          title={`Run now — ${running.schedule.name}`}
          subtitle="Runs once, now. The timetable is unchanged."
          onClose={() => {
            setRunning(null);
            setRunOpId(null);
            run.reset();
          }}
          footer={
            runOpId ? (
              <button type="button" className={buttonTone.primary} onClick={() => (setRunning(null), setRunOpId(null), run.reset())}>
                Close
              </button>
            ) : (
              <>
                <button type="button" className={buttonTone.neutral} onClick={() => setRunning(null)} disabled={run.isPending}>
                  Cancel
                </button>
                <button
                  type="button"
                  className={running.leg === "stop" ? buttonTone.stop : buttonTone.start}
                  disabled={run.isPending}
                  onClick={() => run.mutate({ id: running.schedule.id, leg: running.leg }, { onSuccess: (op) => setRunOpId(op.id) })}
                >
                  {run.isPending ? "Sending to Atlas…" : `${running.leg === "stop" ? "Stop" : "Start"} ${running.schedule.targets.length} cluster${running.schedule.targets.length === 1 ? "" : "s"}`}
                </button>
              </>
            )
          }
        >
          {runOpId ? (
            <OperationProgress operationId={runOpId} />
          ) : (
            <>
              <div className="flex gap-2" role="radiogroup" aria-label="Which leg">
                {(["stop", "start"] as const).map((leg) => (
                  <label key={leg} className="flex items-center gap-2 text-sm">
                    <input type="radio" name="run-leg" checked={running.leg === leg} onChange={() => setRunning({ ...running, leg })} />
                    {leg === "stop" ? "Stop (pause)" : "Start (resume)"}
                  </label>
                ))}
              </div>
              <ul className="rounded-lg border border-att-100 text-sm">
                {running.schedule.targets.map((t) => (
                  <li key={`${t.project_id}/${t.cluster_name}`} className="border-b border-att-50 px-3 py-1.5 last:border-0">
                    <span className="font-mono">{t.cluster_name}</span> <span className="text-xs text-slate-500">{t.project_name}</span>
                  </li>
                ))}
              </ul>
              {run.isError && <InfoNote tone="error">{formatAxiosError(run.error, "Could not run the schedule")}</InfoNote>}
            </>
          )}
        </Modal>
      )}
    </div>
  );
};
