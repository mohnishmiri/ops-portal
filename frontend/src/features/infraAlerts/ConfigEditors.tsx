/**
 * Add / edit dialogs for every Infrastructure Alerts configuration type.
 *
 * Each editor owns its form state, validates as you type (warning below
 * critical, valid unique recipients, a resource picked, no duplicate config),
 * shows the API's own error inline instead of a toast, and previews what the
 * configuration will do — e.g. "Critical today: an alert is raised and emailed
 * to 2 recipients when you save".
 */

import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import { Spinner } from "../../components/gridStyles";
import { useAuth } from "../../contexts/AuthContext";
import {
  apiErrorMessage,
  type CreateExpiryConfigRequest,
  type EnvClassification,
  type ExpiryAlertType,
  type ExpiryConfig,
  type PGFlexServer,
  type PGFlexServerConfig,
  type StorageAccount,
  type StorageAlertConfig,
  type VMInfo,
  type VMThresholdConfig,
  useAzurePGServers,
  useAzureStorageAccounts,
  useAzureVMs,
  useCreateExpiryConfig,
  useCreatePGFlexConfig,
  useCreateStorageAlertConfig,
  useCreateVMThresholdConfig,
  useExpiryConfigs,
  usePGFlexConfigs,
  usePGMetrics,
  useStorageAlertConfigs,
  useUpdateExpiryConfig,
  useUpdatePGFlexConfig,
  useUpdateStorageAlertConfig,
  useUpdateVMThresholdConfig,
  useVMMetrics,
  useVMThresholdConfigs,
} from "../../services/infraAlertApi";
import {
  addDays,
  daysLeftText,
  daysUntil,
  EXPIRY_TYPE_META,
  EXPIRY_TYPE_ORDER,
  ExpiryHealthBadge,
  ExpiryWindowBar,
  expiryHealth,
  InfraIcons,
  isSnoozed,
  PowerStateBadge,
  ThresholdBar,
  todayIso,
} from "./shared";

export type ConfigKind = "vm" | "pg" | "storage" | "expiry";

export type ConfigEditorTarget =
  | { kind: "vm"; config: VMThresholdConfig | null; preset?: { resourceId?: string } }
  | { kind: "pg"; config: PGFlexServerConfig | null; preset?: { resourceId?: string } }
  | { kind: "storage"; config: StorageAlertConfig | null; preset?: { resourceId?: string } }
  | { kind: "expiry"; config: ExpiryConfig | null; preset?: { alertType?: ExpiryAlertType } };

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;

const inputClass =
  "w-full rounded-lg border border-att-200 bg-white px-3 py-2 text-sm text-slate-800 shadow-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100 disabled:bg-slate-50 disabled:text-slate-500";
const labelClass = "mb-1 block text-xs font-semibold uppercase tracking-wide text-slate-600";

// ── Building blocks ───────────────────────────────────────────────────

function ConfigModalShell({
  title,
  subtitle,
  icon,
  error,
  saving,
  canSave,
  saveLabel,
  footerNote,
  onSave,
  onClose,
  children,
}: {
  title: string;
  subtitle: string;
  icon: React.ReactNode;
  error: string | null;
  saving: boolean;
  canSave: boolean;
  saveLabel: string;
  footerNote?: React.ReactNode;
  onSave: () => void;
  onClose: () => void;
  children: React.ReactNode;
}) {
  const titleId = useId();
  const backdrop = useRef<HTMLDivElement>(null);
  const downOnBackdrop = useRef(false);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !saving) onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, saving]);

  return (
    <div
      ref={backdrop}
      className="fixed inset-0 z-[55] flex items-center justify-center bg-slate-900/50 p-4"
      onMouseDown={(e) => {
        downOnBackdrop.current = e.target === backdrop.current;
      }}
      onMouseUp={(e) => {
        if (downOnBackdrop.current && e.target === backdrop.current && !saving) onClose();
        downOnBackdrop.current = false;
      }}
    >
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="flex max-h-[92vh] w-full max-w-3xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-att-100"
        onSubmit={(e) => {
          e.preventDefault();
          if (canSave && !saving) onSave();
        }}
      >
        <header className="relative shrink-0 border-b border-att-100 bg-gradient-to-r from-att-50 via-white to-white px-6 pb-4 pt-5">
          <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-att-300 via-att-500 to-att-300" />
          <div className="flex items-start gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-att-100 text-att-700">{icon}</div>
            <div className="min-w-0 flex-1">
              <h2 id={titleId} className="text-lg font-semibold text-slate-900">
                {title}
              </h2>
              <p className="text-sm text-slate-500">{subtitle}</p>
            </div>
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              aria-label="Close"
              className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600 disabled:opacity-40"
            >
              <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </header>
        <div className="flex-1 space-y-6 overflow-y-auto px-6 py-5">
          {error && (
            <div role="alert" className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
              <p className="font-semibold">Could not save</p>
              <p className="mt-0.5">{error}</p>
            </div>
          )}
          {children}
        </div>
        <footer className="flex shrink-0 flex-wrap items-center justify-between gap-3 border-t border-att-100 bg-att-50/40 px-6 py-3">
          <p className="text-xs text-slate-500">{footerNote}</p>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              disabled={saving}
              className="rounded-lg border border-att-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-att-50 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="submit"
              disabled={!canSave || saving}
              className="inline-flex items-center gap-2 rounded-lg bg-att-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-att-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {saving && <Spinner className="h-4 w-4 text-white" />}
              {saving ? "Saving…" : saveLabel}
            </button>
          </div>
        </footer>
      </form>
    </div>
  );
}

function Section({ title, description, children }: { title: string; description?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section>
      <div className="mb-3">
        <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
        {description && <p className="text-xs text-slate-500">{description}</p>}
      </div>
      {children}
    </section>
  );
}

function FieldError({ children }: { children: React.ReactNode }) {
  return <p className="mt-1 text-xs font-medium text-red-600">{children}</p>;
}

/** Recipient list: Enter, comma, semicolon, space or paste adds; invalid and duplicate addresses are refused. */
export function EmailChipsInput({
  value,
  onChange,
  label = "Notification recipients",
  help,
}: {
  value: string[];
  onChange: (next: string[]) => void;
  label?: string;
  help?: React.ReactNode;
}) {
  const { email: myEmail } = useAuth();
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);
  const inputId = useId();

  const add = (raw: string) => {
    const candidates = raw.split(/[\s,;]+/).map((s) => s.trim()).filter(Boolean);
    if (!candidates.length) return;
    const next = [...value];
    const rejected: string[] = [];
    for (const candidate of candidates) {
      if (!EMAIL_RE.test(candidate)) {
        rejected.push(candidate);
        continue;
      }
      if (!next.some((existing) => existing.toLowerCase() === candidate.toLowerCase())) next.push(candidate);
    }
    onChange(next);
    setDraft(rejected.join(" "));
    setError(rejected.length ? `Not a valid email: ${rejected.join(", ")}` : null);
  };

  const canAddMe = !!myEmail && EMAIL_RE.test(myEmail) && !value.some((v) => v.toLowerCase() === myEmail.toLowerCase());

  return (
    <div>
      <label htmlFor={inputId} className={labelClass}>
        {label}
      </label>
      <div className="flex min-h-[44px] flex-wrap items-center gap-1.5 rounded-lg border border-att-200 bg-white px-2 py-1.5 shadow-sm focus-within:border-att-400 focus-within:ring-2 focus-within:ring-att-100">
        {value.map((email) => (
          <span key={email.toLowerCase()} className="inline-flex items-center gap-1 rounded-full bg-att-50 px-2.5 py-1 text-xs font-medium text-att-800 ring-1 ring-att-200">
            {email}
            <button
              type="button"
              aria-label={`Remove ${email}`}
              onClick={() => onChange(value.filter((v) => v !== email))}
              className="rounded-full px-1 text-att-500 hover:bg-att-100 hover:text-att-800"
            >
              ×
            </button>
          </span>
        ))}
        <input
          id={inputId}
          type="text"
          inputMode="email"
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            setError(null);
          }}
          onKeyDown={(e) => {
            if (["Enter", ",", ";", " ", "Tab"].includes(e.key) && draft.trim()) {
              e.preventDefault();
              add(draft);
            } else if (e.key === "Enter") {
              // Never submit the whole dialog from the recipients box.
              e.preventDefault();
            } else if (e.key === "Backspace" && !draft && value.length) {
              onChange(value.slice(0, -1));
            }
          }}
          onBlur={() => draft.trim() && add(draft)}
          onPaste={(e) => {
            const text = e.clipboardData.getData("text");
            if (/[\s,;]/.test(text.trim())) {
              e.preventDefault();
              add(text);
            }
          }}
          placeholder={value.length ? "Add another…" : "name@att.com — press Enter to add"}
          className="min-w-[12rem] flex-1 border-0 bg-transparent px-1 py-1 text-sm text-slate-800 focus:outline-none"
        />
      </div>
      <div className="mt-1 flex flex-wrap items-center justify-between gap-2">
        {error ? <FieldError>{error}</FieldError> : <p className="text-xs text-slate-500">{help ?? "Paste a list or separate addresses with commas."}</p>}
        {canAddMe && (
          <button type="button" onClick={() => onChange([...value, myEmail])} className="text-xs font-semibold text-att-700 hover:text-att-900 hover:underline">
            + Add me ({myEmail})
          </button>
        )}
      </div>
    </div>
  );
}

function Toggle({ checked, onChange, label, description }: { checked: boolean; onChange: (v: boolean) => void; label: string; description?: string }) {
  return (
    <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-att-100 bg-white px-4 py-3">
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 inline-flex h-5 w-9 shrink-0 rounded-full transition ${checked ? "bg-att-600" : "bg-slate-300"}`}
      >
        <span className={`absolute top-0.5 h-4 w-4 rounded-full bg-white shadow transition ${checked ? "left-[1.125rem]" : "left-0.5"}`} />
      </button>
      <span>
        <span className="block text-sm font-medium text-slate-800">{label}</span>
        {description && <span className="block text-xs text-slate-500">{description}</span>}
      </span>
    </label>
  );
}

const SNOOZE_CHOICES = [
  { label: "1 hour", hours: 1 },
  { label: "4 hours", hours: 4 },
  { label: "24 hours", hours: 24 },
  { label: "3 days", hours: 72 },
  { label: "1 week", hours: 168 },
];

/** Snooze control. ``value`` is an ISO time, or null for not snoozed. */
function SnoozeField({ value, onChange, formatDate }: { value: string | null; onChange: (v: string | null) => void; formatDate: (v: string) => string }) {
  const snoozed = isSnoozed(value);
  return (
    <div className="rounded-xl border border-att-100 bg-white px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-slate-800">Snooze notifications</p>
          <p className="text-xs text-slate-500">
            {snoozed ? `Snoozed until ${formatDate(value as string)} — checks are skipped until then.` : "Pause checks and emails for a while, e.g. during maintenance."}
          </p>
        </div>
        {snoozed && (
          <button type="button" onClick={() => onChange(null)} className="text-xs font-semibold text-att-700 hover:underline">
            Clear snooze
          </button>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {SNOOZE_CHOICES.map((choice) => (
          <button
            key={choice.hours}
            type="button"
            onClick={() => onChange(new Date(Date.now() + choice.hours * 3_600_000).toISOString())}
            className="rounded-full border border-att-200 bg-white px-3 py-1 text-xs font-medium text-slate-700 hover:border-att-300 hover:bg-att-50"
          >
            {choice.label}
          </button>
        ))}
      </div>
    </div>
  );
}

interface ThresholdSpec {
  key: string;
  label: string;
  help?: string;
  warning: number;
  critical: number;
  unit: string;
  max?: number;
  step?: number;
  current?: number | null;
}

function ThresholdRows({ specs, onChange }: { specs: ThresholdSpec[]; onChange: (key: string, field: "warning" | "critical", value: number) => void }) {
  return (
    <div className="space-y-3">
      {specs.map((spec) => {
        const invalid = spec.warning >= spec.critical;
        const outOfRange = spec.max !== undefined && (spec.warning > spec.max || spec.critical > spec.max);
        return (
          <div key={spec.key} className={`rounded-xl border px-4 py-3 ${invalid || outOfRange ? "border-red-200 bg-red-50/40" : "border-att-100 bg-white"}`}>
            <div className="flex flex-wrap items-end gap-4">
              <div className="min-w-[9rem] flex-1">
                <p className="text-sm font-semibold text-slate-800">{spec.label}</p>
                {spec.help && <p className="text-xs text-slate-500">{spec.help}</p>}
                {spec.current != null && (
                  <p className="text-xs text-slate-600">
                    Current: <span className="font-semibold">{spec.current}{spec.unit}</span>
                  </p>
                )}
              </div>
              {(["warning", "critical"] as const).map((field) => (
                <label key={field} className="w-32">
                  <span className={`mb-1 block text-[11px] font-semibold uppercase tracking-wide ${field === "warning" ? "text-amber-700" : "text-red-700"}`}>
                    {field} {spec.unit && `(${spec.unit})`}
                  </span>
                  <input
                    type="number"
                    min={0}
                    max={spec.max}
                    step={spec.step ?? 1}
                    value={Number.isFinite(spec[field]) ? spec[field] : ""}
                    onChange={(e) => onChange(spec.key, field, e.target.value === "" ? NaN : Number(e.target.value))}
                    className={inputClass}
                    required
                  />
                </label>
              ))}
            </div>
            <div className="mt-3">
              <ThresholdBar value={spec.current} warning={spec.warning || 0} critical={spec.critical || 0} max={spec.max ?? Math.max(spec.critical * 1.2, 1)} unit={spec.unit} />
            </div>
            {invalid && <FieldError>Warning must be lower than critical, or the warning level is never reached.</FieldError>}
            {outOfRange && <FieldError>Percentages must be between 0 and {spec.max}.</FieldError>}
          </div>
        );
      })}
    </div>
  );
}

const PERCENT_PRESETS = [
  { label: "Sensitive", warning: 60, critical: 80 },
  { label: "Balanced", warning: 70, critical: 90 },
  { label: "Relaxed", warning: 80, critical: 95 },
];

function PresetButtons({ onApply }: { onApply: (warning: number, critical: number) => void }) {
  return (
    <div className="flex flex-wrap items-center gap-1.5">
      <span className="text-xs text-slate-500">Apply to all:</span>
      {PERCENT_PRESETS.map((preset) => (
        <button
          key={preset.label}
          type="button"
          onClick={() => onApply(preset.warning, preset.critical)}
          className="rounded-full border border-att-200 bg-white px-3 py-1 text-xs font-medium text-slate-700 hover:border-att-300 hover:bg-att-50"
        >
          {preset.label} {preset.warning}/{preset.critical}%
        </button>
      ))}
    </div>
  );
}

/** Searchable single-choice list of synced resources; already-configured ones are shown but locked. */
function ResourcePicker<T extends { id: string; name: string; resource_group: string | null; subscription_id?: string }>({
  resources,
  selectedId,
  configuredIds,
  subscriptionNames,
  onSelect,
  describe,
  emptyText,
}: {
  resources: T[];
  selectedId: string;
  configuredIds: Set<string>;
  subscriptionNames: Map<string, string>;
  onSelect: (resource: T) => void;
  describe: (resource: T) => React.ReactNode;
  emptyText: string;
}) {
  const [query, setQuery] = useState("");
  const [subscription, setSubscription] = useState("");
  const subscriptions = useMemo(() => [...new Set(resources.map((r) => r.subscription_id).filter(Boolean))] as string[], [resources]);
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return resources
      .filter((r) => !subscription || r.subscription_id === subscription)
      .filter((r) => !q || `${r.name} ${r.resource_group ?? ""}`.toLowerCase().includes(q))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [resources, query, subscription]);

  return (
    <div className="rounded-xl border border-att-100 bg-white">
      <div className="flex flex-wrap gap-2 border-b border-att-100 bg-att-50/50 px-3 py-2">
        <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search name or resource group…" className={`${inputClass} flex-1`} />
        {subscriptions.length > 1 && (
          <select value={subscription} onChange={(e) => setSubscription(e.target.value)} className={`${inputClass} w-56`} aria-label="Subscription">
            <option value="">All subscriptions</option>
            {subscriptions.map((sub) => (
              <option key={sub} value={sub}>
                {subscriptionNames.get(sub) || sub}
              </option>
            ))}
          </select>
        )}
      </div>
      <ul className="max-h-64 divide-y divide-att-50 overflow-y-auto" role="listbox">
        {visible.map((resource) => {
          const configured = configuredIds.has(resource.id.toLowerCase());
          const selected = resource.id === selectedId;
          return (
            <li key={resource.id}>
              <button
                type="button"
                role="option"
                aria-selected={selected}
                disabled={configured}
                onClick={() => onSelect(resource)}
                className={`flex w-full items-center gap-3 px-3 py-2 text-left text-sm transition ${
                  selected ? "bg-att-50 ring-1 ring-inset ring-att-300" : configured ? "cursor-not-allowed opacity-60" : "hover:bg-slate-50"
                }`}
              >
                <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full border ${selected ? "border-att-600 bg-att-600" : "border-slate-300"}`}>
                  {selected && <span className="h-1.5 w-1.5 rounded-full bg-white" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium text-slate-800">{resource.name}</span>
                  <span className="block truncate text-xs text-slate-500">
                    {resource.resource_group} · {subscriptionNames.get(resource.subscription_id || "") || resource.subscription_id}
                  </span>
                </span>
                <span className="shrink-0">{configured ? <span className="text-xs font-medium text-slate-500">Already configured</span> : describe(resource)}</span>
              </button>
            </li>
          );
        })}
        {!visible.length && <li className="px-3 py-6 text-center text-sm text-slate-400">{emptyText}</li>}
      </ul>
    </div>
  );
}

function SelectedResourceCard({ name, resourceGroup, subscription, extra }: { name: string; resourceGroup: string; subscription: string; extra?: React.ReactNode }) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-att-100 bg-att-50/50 px-4 py-3">
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-sm font-semibold text-slate-900">{name}</p>
        <p className="truncate text-xs text-slate-500">
          {resourceGroup} · {subscription}
        </p>
      </div>
      {extra}
    </div>
  );
}

function useSaveState() {
  const [error, setError] = useState<string | null>(null);
  return { error, setError, fail: (e: unknown, fallback: string) => setError(apiErrorMessage(e, fallback)) };
}

interface EditorProps {
  subscriptionNames: Map<string, string>;
  formatDate: (value: string) => string;
  onClose: () => void;
  onSaved: (message: string) => void;
}

const validPair = (warning: number, critical: number, max?: number) =>
  Number.isFinite(warning) && Number.isFinite(critical) && warning >= 0 && warning < critical && (max === undefined || critical <= max);

// ── VM thresholds ─────────────────────────────────────────────────────

export function VMConfigEditor({ config, presetResourceId, ...props }: EditorProps & { config: VMThresholdConfig | null; presetResourceId?: string }) {
  const { data: vmResponse } = useAzureVMs();
  const { data: existing = [] } = useVMThresholdConfigs();
  const create = useCreateVMThresholdConfig();
  const update = useUpdateVMThresholdConfig();
  const { error, setError, fail } = useSaveState();
  const vms = vmResponse?.resources ?? [];
  const isEdit = !!config;

  const [vmId, setVmId] = useState(config?.vm_id ?? presetResourceId ?? "");
  const [values, setValues] = useState({
    cpu: { warning: config?.cpu_warning_threshold ?? 70, critical: config?.cpu_critical_threshold ?? 90 },
    memory: { warning: config?.memory_warning_threshold ?? 75, critical: config?.memory_critical_threshold ?? 90 },
    disk: { warning: config?.disk_warning_threshold ?? 80, critical: config?.disk_critical_threshold ?? 95 },
  });
  const [emails, setEmails] = useState<string[]>(config?.notification_emails ?? []);
  const [enabled, setEnabled] = useState(config?.is_enabled ?? true);
  const [snooze, setSnooze] = useState<string | null>(config?.snooze_until ?? null);

  const selected: VMInfo | undefined = vms.find((vm) => vm.id.toLowerCase() === vmId.toLowerCase());
  const subscriptionId = config?.subscription_id ?? selected?.subscription_id ?? "";
  const resourceGroup = config?.resource_group ?? selected?.resource_group ?? "";
  const vmName = config?.vm_name ?? selected?.name ?? "";
  const { data: live } = useVMMetrics(subscriptionId, resourceGroup, vmName);
  const configuredIds = useMemo(() => new Set(existing.filter((c) => c.id !== config?.id).map((c) => c.vm_id.toLowerCase())), [existing, config]);

  const pairsValid = (Object.values(values) as { warning: number; critical: number }[]).every((p) => validPair(p.warning, p.critical, 100));
  const canSave = pairsValid && (isEdit || (!!selected && !configuredIds.has(vmId.toLowerCase())));
  const saving = create.isPending || update.isPending;

  const thresholdPayload = {
    cpu_warning_threshold: values.cpu.warning,
    cpu_critical_threshold: values.cpu.critical,
    memory_warning_threshold: values.memory.warning,
    memory_critical_threshold: values.memory.critical,
    disk_warning_threshold: values.disk.warning,
    disk_critical_threshold: values.disk.critical,
    notification_emails: emails,
    is_enabled: enabled,
  };

  const save = () => {
    setError(null);
    if (isEdit && config) {
      update.mutate(
        { configId: config.id, data: { ...thresholdPayload, snooze_until: isSnoozed(snooze) ? snooze : null } },
        { onSuccess: () => props.onSaved(`Thresholds for ${config.vm_name} saved`), onError: (e) => fail(e, "Failed to update the VM configuration") },
      );
    } else if (selected) {
      create.mutate(
        { subscription_id: selected.subscription_id as string, resource_group: selected.resource_group as string, vm_name: selected.name, vm_id: selected.id, ...thresholdPayload },
        { onSuccess: () => props.onSaved(`Monitoring ${selected.name} — checked on the next scheduled run`), onError: (e) => fail(e, "Failed to create the VM configuration") },
      );
    }
  };

  const setPair = (key: string, field: "warning" | "critical", value: number) =>
    setValues((prev) => ({ ...prev, [key]: { ...prev[key as keyof typeof prev], [field]: value } }));

  return (
    <ConfigModalShell
      title={isEdit ? `Edit VM thresholds — ${config?.vm_name}` : "Monitor a virtual machine"}
      subtitle="Alert when CPU, memory or disk I/O stays above your thresholds. Readings come from Azure Monitor platform metrics."
      icon={InfraIcons.server}
      error={error}
      saving={saving}
      canSave={canSave}
      saveLabel={isEdit ? "Save changes" : "Start monitoring"}
      footerNote="Checked by the alert schedules (every 15 minutes by default)."
      onSave={save}
      onClose={props.onClose}
    >
      <Section title="Virtual machine" description={isEdit ? undefined : "Pick a VM from the synced inventory. VMs that already have thresholds are locked."}>
        {isEdit && config ? (
          <SelectedResourceCard
            name={config.vm_name}
            resourceGroup={config.resource_group}
            subscription={props.subscriptionNames.get(config.subscription_id) || config.subscription_id}
            extra={selected && <PowerStateBadge state={selected.power_state} />}
          />
        ) : (
          <ResourcePicker
            resources={vms}
            selectedId={selected?.id ?? ""}
            configuredIds={configuredIds}
            subscriptionNames={props.subscriptionNames}
            onSelect={(vm) => setVmId(vm.id)}
            describe={(vm) => <PowerStateBadge state={vm.power_state} />}
            emptyText="No VMs match. Sync resources on the Resources tab if a VM is missing."
          />
        )}
      </Section>

      <Section title="Thresholds" description="Warning and critical levels in percent. An alert opens at warning and escalates (and emails again) at critical.">
        <div className="mb-3">
          <PresetButtons onApply={(w, c) => setValues({ cpu: { warning: w, critical: c }, memory: { warning: w, critical: c }, disk: { warning: w, critical: c } })} />
        </div>
        <ThresholdRows
          onChange={setPair}
          specs={[
            { key: "cpu", label: "CPU", help: "Percentage CPU", unit: "%", max: 100, ...values.cpu, current: live?.cpu },
            { key: "memory", label: "Memory", help: "Memory in use (100 − available %)", unit: "%", max: 100, ...values.memory, current: live?.memory },
            { key: "disk", label: "Disk I/O", help: "Busiest OS/data disk IOPS or throughput consumed — not disk space", unit: "%", max: 100, ...values.disk, current: live?.disk },
          ]}
        />
        {live?.collected_at && <p className="mt-2 text-xs text-slate-500">Current values from Azure Monitor at {props.formatDate(live.collected_at)}.</p>}
      </Section>

      <Section title="Notifications">
        <EmailChipsInput value={emails} onChange={setEmails} help="Emailed when an alert opens, escalates, or recovers. The daily digest has its own recipients." />
      </Section>

      <Section title="State">
        <div className="grid gap-3 md:grid-cols-2">
          <Toggle checked={enabled} onChange={setEnabled} label="Monitoring enabled" description="Disabling closes any open alert for this VM." />
          {isEdit && <SnoozeField value={snooze} onChange={setSnooze} formatDate={props.formatDate} />}
        </div>
      </Section>
    </ConfigModalShell>
  );
}

// ── PG Flexible Server thresholds ─────────────────────────────────────

export function PGConfigEditor({ config, presetResourceId, ...props }: EditorProps & { config: PGFlexServerConfig | null; presetResourceId?: string }) {
  const { data: serverResponse } = useAzurePGServers();
  const { data: existing = [] } = usePGFlexConfigs();
  const create = useCreatePGFlexConfig();
  const update = useUpdatePGFlexConfig();
  const { error, setError, fail } = useSaveState();
  const servers = serverResponse?.resources ?? [];
  const isEdit = !!config;

  const [serverId, setServerId] = useState(config?.server_id ?? presetResourceId ?? "");
  const [values, setValues] = useState({
    cpu: { warning: config?.cpu_warning_threshold ?? 70, critical: config?.cpu_critical_threshold ?? 90 },
    memory: { warning: config?.memory_warning_threshold ?? 75, critical: config?.memory_critical_threshold ?? 90 },
    storage: { warning: config?.storage_warning_threshold ?? 80, critical: config?.storage_critical_threshold ?? 95 },
  });
  const [emails, setEmails] = useState<string[]>(config?.notification_emails ?? []);
  const [enabled, setEnabled] = useState(config?.is_enabled ?? true);
  const [snooze, setSnooze] = useState<string | null>(config?.snooze_until ?? null);

  const selected: PGFlexServer | undefined = servers.find((s) => s.id.toLowerCase() === serverId.toLowerCase());
  const { data: live } = usePGMetrics(
    config?.subscription_id ?? selected?.subscription_id ?? "",
    config?.resource_group ?? selected?.resource_group ?? "",
    config?.server_name ?? selected?.name ?? "",
  );
  const configuredIds = useMemo(() => new Set(existing.filter((c) => c.id !== config?.id).map((c) => c.server_id.toLowerCase())), [existing, config]);
  const pairsValid = (Object.values(values) as { warning: number; critical: number }[]).every((p) => validPair(p.warning, p.critical, 100));
  const canSave = pairsValid && (isEdit || (!!selected && !configuredIds.has(serverId.toLowerCase())));
  const saving = create.isPending || update.isPending;

  const payload = {
    cpu_warning_threshold: values.cpu.warning,
    cpu_critical_threshold: values.cpu.critical,
    memory_warning_threshold: values.memory.warning,
    memory_critical_threshold: values.memory.critical,
    storage_warning_threshold: values.storage.warning,
    storage_critical_threshold: values.storage.critical,
    notification_emails: emails,
    is_enabled: enabled,
  };

  const save = () => {
    setError(null);
    if (isEdit && config) {
      update.mutate(
        { configId: config.id, data: { ...payload, snooze_until: isSnoozed(snooze) ? snooze : null } },
        { onSuccess: () => props.onSaved(`Thresholds for ${config.server_name} saved`), onError: (e) => fail(e, "Failed to update the PG configuration") },
      );
    } else if (selected) {
      create.mutate(
        { subscription_id: selected.subscription_id, resource_group: selected.resource_group, server_name: selected.name, server_id: selected.id, ...payload },
        { onSuccess: () => props.onSaved(`Monitoring ${selected.name} — checked on the next scheduled run`), onError: (e) => fail(e, "Failed to create the PG configuration") },
      );
    }
  };

  const setPair = (key: string, field: "warning" | "critical", value: number) =>
    setValues((prev) => ({ ...prev, [key]: { ...prev[key as keyof typeof prev], [field]: value } }));

  return (
    <ConfigModalShell
      title={isEdit ? `Edit PG thresholds — ${config?.server_name}` : "Monitor a PostgreSQL Flexible Server"}
      subtitle="Alert when CPU, memory or storage use stays above your thresholds."
      icon={InfraIcons.database}
      error={error}
      saving={saving}
      canSave={canSave}
      saveLabel={isEdit ? "Save changes" : "Start monitoring"}
      footerNote="Checked by the alert schedules (every 15 minutes by default)."
      onSave={save}
      onClose={props.onClose}
    >
      <Section title="Server" description={isEdit ? undefined : "Pick a server from the synced inventory."}>
        {isEdit && config ? (
          <SelectedResourceCard
            name={config.server_name}
            resourceGroup={config.resource_group}
            subscription={props.subscriptionNames.get(config.subscription_id) || config.subscription_id}
            extra={selected && <PowerStateBadge state={selected.state} />}
          />
        ) : (
          <ResourcePicker
            resources={servers}
            selectedId={selected?.id ?? ""}
            configuredIds={configuredIds}
            subscriptionNames={props.subscriptionNames}
            onSelect={(server) => setServerId(server.id)}
            describe={(server) => <PowerStateBadge state={server.state} />}
            emptyText="No servers match. Sync resources on the Resources tab if one is missing."
          />
        )}
      </Section>
      <Section title="Thresholds" description="Warning and critical levels in percent.">
        <div className="mb-3">
          <PresetButtons onApply={(w, c) => setValues({ cpu: { warning: w, critical: c }, memory: { warning: w, critical: c }, storage: { warning: w, critical: c } })} />
        </div>
        <ThresholdRows
          onChange={setPair}
          specs={[
            { key: "cpu", label: "CPU", unit: "%", max: 100, ...values.cpu, current: live?.cpu },
            { key: "memory", label: "Memory", unit: "%", max: 100, ...values.memory, current: live?.memory },
            { key: "storage", label: "Storage", help: "Share of provisioned storage in use", unit: "%", max: 100, ...values.storage, current: live?.storage },
          ]}
        />
      </Section>
      <Section title="Notifications">
        <EmailChipsInput value={emails} onChange={setEmails} help="Emailed when an alert opens, escalates, or recovers." />
      </Section>
      <Section title="State">
        <div className="grid gap-3 md:grid-cols-2">
          <Toggle checked={enabled} onChange={setEnabled} label="Monitoring enabled" description="Disabling closes any open alert for this server." />
          {isEdit && <SnoozeField value={snooze} onChange={setSnooze} formatDate={props.formatDate} />}
        </div>
      </Section>
    </ConfigModalShell>
  );
}

// ── Storage account thresholds ────────────────────────────────────────

export function StorageConfigEditor({ config, presetResourceId, ...props }: EditorProps & { config: StorageAlertConfig | null; presetResourceId?: string }) {
  const { data: accountResponse } = useAzureStorageAccounts();
  const { data: existing = [] } = useStorageAlertConfigs();
  const create = useCreateStorageAlertConfig();
  const update = useUpdateStorageAlertConfig();
  const { error, setError, fail } = useSaveState();
  const accounts = (accountResponse?.resources ?? []) as StorageAccount[];
  const isEdit = !!config;

  const [accountId, setAccountId] = useState(config?.account_id ?? presetResourceId ?? "");
  const [values, setValues] = useState({
    capacity: { warning: config?.capacity_warning_gb ?? 100, critical: config?.capacity_critical_gb ?? 500 },
    transactions: { warning: config?.transactions_warning ?? 100000, critical: config?.transactions_critical ?? 500000 },
    egress: { warning: config?.egress_warning_gb ?? 50, critical: config?.egress_critical_gb ?? 200 },
  });
  const [emails, setEmails] = useState<string[]>(config?.notification_emails ?? []);
  const [enabled, setEnabled] = useState(config?.is_enabled ?? true);
  const [snooze, setSnooze] = useState<string | null>(config?.snooze_until ?? null);

  const selected = accounts.find((a) => a.id.toLowerCase() === accountId.toLowerCase());
  const configuredIds = useMemo(() => new Set(existing.filter((c) => c.id !== config?.id).map((c) => c.account_id.toLowerCase())), [existing, config]);
  const pairsValid = (Object.values(values) as { warning: number; critical: number }[]).every((p) => validPair(p.warning, p.critical));
  const canSave = pairsValid && (isEdit || (!!selected && !configuredIds.has(accountId.toLowerCase())));
  const saving = create.isPending || update.isPending;

  const payload = {
    capacity_warning_gb: values.capacity.warning,
    capacity_critical_gb: values.capacity.critical,
    transactions_warning: values.transactions.warning,
    transactions_critical: values.transactions.critical,
    egress_warning_gb: values.egress.warning,
    egress_critical_gb: values.egress.critical,
    notification_emails: emails,
    is_enabled: enabled,
  };

  const save = () => {
    setError(null);
    if (isEdit && config) {
      update.mutate(
        { configId: config.id, data: { ...payload, snooze_until: isSnoozed(snooze) ? snooze : null } },
        { onSuccess: () => props.onSaved(`Thresholds for ${config.account_name} saved`), onError: (e) => fail(e, "Failed to update the storage configuration") },
      );
    } else if (selected) {
      create.mutate(
        { subscription_id: selected.subscription_id, resource_group: selected.resource_group, account_name: selected.name, account_id: selected.id, ...payload },
        { onSuccess: () => props.onSaved(`Thresholds saved for ${selected.name}`), onError: (e) => fail(e, "Failed to create the storage configuration") },
      );
    }
  };

  const setPair = (key: string, field: "warning" | "critical", value: number) =>
    setValues((prev) => ({ ...prev, [key]: { ...prev[key as keyof typeof prev], [field]: value } }));

  return (
    <ConfigModalShell
      title={isEdit ? `Edit storage thresholds — ${config?.account_name}` : "Storage account thresholds"}
      subtitle="Capacity, transaction and egress limits for a storage account."
      icon={InfraIcons.storage}
      error={error}
      saving={saving}
      canSave={canSave}
      saveLabel={isEdit ? "Save changes" : "Save thresholds"}
      onSave={save}
      onClose={props.onClose}
    >
      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        <p className="font-semibold">Saved, but not evaluated yet</p>
        <p className="mt-0.5 text-amber-800">
          The alert schedules do not check storage accounts yet, so these thresholds will not raise alerts or emails until storage checks are added.
        </p>
      </div>
      <Section title="Storage account">
        {isEdit && config ? (
          <SelectedResourceCard
            name={config.account_name}
            resourceGroup={config.resource_group}
            subscription={props.subscriptionNames.get(config.subscription_id) || config.subscription_id}
          />
        ) : (
          <ResourcePicker
            resources={accounts}
            selectedId={selected?.id ?? ""}
            configuredIds={configuredIds}
            subscriptionNames={props.subscriptionNames}
            onSelect={(account) => setAccountId(account.id)}
            describe={(account) => <span className="text-xs text-slate-500">{account.sku || account.kind}</span>}
            emptyText="No storage accounts match."
          />
        )}
      </Section>
      <Section title="Thresholds">
        <ThresholdRows
          onChange={setPair}
          specs={[
            { key: "capacity", label: "Used capacity", unit: " GB", ...values.capacity },
            { key: "transactions", label: "Transactions", unit: "", step: 1000, ...values.transactions },
            { key: "egress", label: "Egress", unit: " GB", ...values.egress },
          ]}
        />
      </Section>
      <Section title="Notifications">
        <EmailChipsInput value={emails} onChange={setEmails} />
      </Section>
      <Section title="State">
        <div className="grid gap-3 md:grid-cols-2">
          <Toggle checked={enabled} onChange={setEnabled} label="Enabled" />
          {isEdit && <SnoozeField value={snooze} onChange={setSnooze} formatDate={props.formatDate} />}
        </div>
      </Section>
    </ConfigModalShell>
  );
}

// ── Expiry ────────────────────────────────────────────────────────────

const DAY_PRESETS = [
  { warning: 30, critical: 7 },
  { warning: 45, critical: 14 },
  { warning: 60, critical: 14 },
  { warning: 90, critical: 30 },
];

export function ExpiryConfigEditor({ config, presetType, ...props }: EditorProps & { config: ExpiryConfig | null; presetType?: ExpiryAlertType }) {
  const { data: existing = [] } = useExpiryConfigs();
  const create = useCreateExpiryConfig();
  const update = useUpdateExpiryConfig();
  const { error, setError, fail } = useSaveState();
  const isEdit = !!config;

  const [alertType, setAlertType] = useState<ExpiryAlertType>(config?.alert_type ?? presetType ?? "itservices_domain");
  const meta = EXPIRY_TYPE_META[alertType];
  const [name, setName] = useState(config?.resource_name ?? "");
  const [identifier, setIdentifier] = useState(config?.resource_identifier ?? "");
  const [identifierTouched, setIdentifierTouched] = useState(isEdit);
  const [environment, setEnvironment] = useState<EnvClassification>(config?.environment ?? "non_prod");
  const [expiryDate, setExpiryDate] = useState(config?.expiry_date?.slice(0, 10) ?? "");
  const [warningDays, setWarningDays] = useState(config?.warning_days_before ?? meta.defaultWarning);
  const [criticalDays, setCriticalDays] = useState(config?.critical_days_before ?? meta.defaultCritical);
  const [description, setDescription] = useState(config?.description ?? "");
  const [emails, setEmails] = useState<string[]>(config?.notification_emails ?? []);
  const [enabled, setEnabled] = useState(config?.is_enabled ?? true);
  const [snooze, setSnooze] = useState<string | null>(config?.snooze_until ?? null);

  const effectiveIdentifier = (identifierTouched || !meta.identifierMirrorsName ? identifier : name).trim();
  const duplicate = existing.find(
    (c) => c.id !== config?.id && c.alert_type === alertType && c.resource_identifier.trim().toLowerCase() === effectiveIdentifier.toLowerCase(),
  );
  const days = daysUntil(expiryDate);
  const health = expiryHealth(days, warningDays, criticalDays);
  const daysValid = Number.isInteger(warningDays) && Number.isInteger(criticalDays) && criticalDays >= 1 && warningDays > criticalDays && warningDays <= 730;
  const canSave = !!name.trim() && !!effectiveIdentifier && !!expiryDate && daysValid && !duplicate;
  const saving = create.isPending || update.isPending;

  const chooseType = (type: ExpiryAlertType) => {
    if (isEdit) return;
    const previous = EXPIRY_TYPE_META[alertType];
    setAlertType(type);
    // Keep the user's own day choices; only swap in the new type's defaults if untouched.
    if (warningDays === previous.defaultWarning && criticalDays === previous.defaultCritical) {
      setWarningDays(EXPIRY_TYPE_META[type].defaultWarning);
      setCriticalDays(EXPIRY_TYPE_META[type].defaultCritical);
    }
  };

  const save = () => {
    setError(null);
    const common = {
      resource_name: name.trim(),
      description: description.trim() || undefined,
      environment,
      expiry_date: expiryDate,
      warning_days_before: warningDays,
      critical_days_before: criticalDays,
      notification_emails: emails,
      is_enabled: enabled,
    };
    const willAlert = enabled && health !== "ok";
    if (isEdit && config) {
      update.mutate(
        { configId: config.id, data: { ...common, description: description.trim(), snooze_until: isSnoozed(snooze) ? snooze : null } },
        {
          onSuccess: () =>
            props.onSaved(
              config.expiry_date.slice(0, 10) !== expiryDate && health === "ok"
                ? `${name} renewed to ${expiryDate} — its open alert was resolved`
                : `${name} saved`,
            ),
          onError: (e) => fail(e, "Failed to update the expiry configuration"),
        },
      );
    } else {
      const payload: CreateExpiryConfigRequest = { ...common, alert_type: alertType, resource_identifier: effectiveIdentifier };
      create.mutate(payload, {
        onSuccess: () => props.onSaved(willAlert ? `${name} added — it is already due, so an alert was raised` : `${name} added — monitoring starts now`),
        onError: (e) => fail(e, "Failed to create the expiry configuration"),
      });
    }
  };

  const preview = (() => {
    if (!expiryDate || days == null) return null;
    if (!enabled) return "Monitoring is disabled — no alerts will be raised.";
    const recipients = emails.length ? `emailed to ${emails.length} recipient${emails.length === 1 ? "" : "s"}` : "shown here (no recipients to email)";
    if (health === "ok") return `Healthy — the warning alert will open on ${addDays(expiryDate, -warningDays)} and be ${recipients}.`;
    return `Already ${health === "expired" ? "expired" : `in the ${health} window`} — saving raises a ${health === "warning" ? "warning" : "critical"} alert now, ${recipients}.`;
  })();

  return (
    <ConfigModalShell
      title={isEdit ? `Edit expiry tracking — ${config?.resource_name}` : "Track an expiry date"}
      subtitle="Get warned before an account, ID or certificate expires — and again when it becomes critical."
      icon={InfraIcons.clock}
      error={error}
      saving={saving}
      canSave={canSave}
      saveLabel={isEdit ? "Save changes" : "Start tracking"}
      footerNote="Renewed? Update the expiry date — the open alert resolves automatically."
      onSave={save}
      onClose={props.onClose}
    >
      <Section title="What are you tracking?" description={isEdit ? "The type cannot change after creation." : undefined}>
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
          {EXPIRY_TYPE_ORDER.map((type) => {
            const typeMeta = EXPIRY_TYPE_META[type];
            const active = type === alertType;
            return (
              <button
                key={type}
                type="button"
                onClick={() => chooseType(type)}
                disabled={isEdit && !active}
                aria-pressed={active}
                className={`rounded-xl border px-3 py-2.5 text-left transition ${
                  active ? "border-att-500 bg-att-50 ring-2 ring-att-200" : "border-att-100 bg-white hover:border-att-300 disabled:opacity-40"
                }`}
              >
                <span className="block text-sm font-semibold text-slate-800">{typeMeta.label}</span>
                <span className="block text-xs text-slate-500">{typeMeta.description}</span>
              </button>
            );
          })}
        </div>
      </Section>

      <Section title="Details">
        <div className="grid gap-4 md:grid-cols-2">
          <label className="block">
            <span className={labelClass}>{meta.nameLabel} *</span>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder={meta.namePlaceholder} className={inputClass} required maxLength={255} autoFocus={!isEdit} />
          </label>
          <label className="block">
            <span className={labelClass}>{meta.identifierLabel} *</span>
            <input
              value={identifierTouched || !meta.identifierMirrorsName ? identifier : name}
              onChange={(e) => {
                setIdentifierTouched(true);
                setIdentifier(e.target.value);
              }}
              placeholder={meta.identifierPlaceholder}
              className={inputClass}
              disabled={isEdit}
              maxLength={500}
            />
            {duplicate ? (
              <FieldError>Already tracked as “{duplicate.resource_name}” — edit that configuration instead.</FieldError>
            ) : (
              <p className="mt-1 text-xs text-slate-500">{isEdit ? "The identifier cannot change after creation." : meta.identifierHelp}</p>
            )}
          </label>
          <div>
            <span className={labelClass}>Environment *</span>
            <div className="inline-flex rounded-lg border border-att-200 bg-white p-0.5 shadow-sm" role="radiogroup" aria-label="Environment">
              {(["prod", "non_prod"] as EnvClassification[]).map((env) => (
                <button
                  key={env}
                  type="button"
                  role="radio"
                  aria-checked={environment === env}
                  onClick={() => setEnvironment(env)}
                  className={`rounded-md px-4 py-1.5 text-sm font-semibold transition ${environment === env ? (env === "prod" ? "bg-green-600 text-white" : "bg-amber-500 text-white") : "text-slate-600 hover:bg-slate-50"}`}
                >
                  {env === "prod" ? "PROD" : "NPROD"}
                </button>
              ))}
            </div>
          </div>
          <label className="block">
            <span className={labelClass}>Expiry date *</span>
            <input type="date" value={expiryDate} onChange={(e) => setExpiryDate(e.target.value)} className={inputClass} required />
            <div className="mt-1.5 flex flex-wrap gap-1.5">
              {[30, 60, 90, 180, 365].map((offset) => (
                <button
                  key={offset}
                  type="button"
                  onClick={() => setExpiryDate(addDays(todayIso(), offset))}
                  className="rounded-full border border-att-200 bg-white px-2.5 py-0.5 text-[11px] font-medium text-slate-600 hover:bg-att-50"
                >
                  +{offset === 365 ? "1 year" : `${offset} days`}
                </button>
              ))}
            </div>
          </label>
          <label className="block md:col-span-2">
            <span className={labelClass}>Description</span>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              placeholder="Owner, renewal procedure, ticket queue…"
              rows={2}
              className={`${inputClass} resize-y`}
            />
          </label>
        </div>
      </Section>

      <Section title="When to alert" description="Days before the expiry date. Warning first, then critical — each emails your recipients.">
        <div className="mb-3 flex flex-wrap items-center gap-1.5">
          <span className="text-xs text-slate-500">Presets:</span>
          {DAY_PRESETS.map((preset) => (
            <button
              key={`${preset.warning}-${preset.critical}`}
              type="button"
              onClick={() => {
                setWarningDays(preset.warning);
                setCriticalDays(preset.critical);
              }}
              className={`rounded-full border px-3 py-1 text-xs font-medium ${
                warningDays === preset.warning && criticalDays === preset.critical ? "border-att-500 bg-att-50 text-att-800" : "border-att-200 bg-white text-slate-700 hover:bg-att-50"
              }`}
            >
              {preset.warning} / {preset.critical} days
            </button>
          ))}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <label className="block">
            <span className={`${labelClass} text-amber-700`}>Warning — days before</span>
            <input type="number" min={2} max={730} value={Number.isFinite(warningDays) ? warningDays : ""} onChange={(e) => setWarningDays(Number(e.target.value))} className={inputClass} />
          </label>
          <label className="block">
            <span className={`${labelClass} text-red-700`}>Critical — days before</span>
            <input type="number" min={1} max={729} value={Number.isFinite(criticalDays) ? criticalDays : ""} onChange={(e) => setCriticalDays(Number(e.target.value))} className={inputClass} />
          </label>
        </div>
        {!daysValid && <FieldError>Critical must be at least 1 day and fewer days than warning (e.g. warn at 30, critical at 7).</FieldError>}
        {expiryDate && daysValid && (
          <div className="mt-4 rounded-xl border border-att-100 bg-white px-4 py-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-sm font-semibold text-slate-800">{daysLeftText(days)}</p>
              <ExpiryHealthBadge health={health} />
            </div>
            <ExpiryWindowBar expiryDate={expiryDate} warningDays={warningDays} criticalDays={criticalDays} />
            {preview && <p className={`mt-3 text-xs ${health === "ok" ? "text-slate-600" : "font-medium text-red-700"}`}>{preview}</p>}
          </div>
        )}
      </Section>

      <Section title="Notifications">
        <EmailChipsInput value={emails} onChange={setEmails} help="Emailed when the alert opens, escalates, and when it is resolved." />
      </Section>

      <Section title="State">
        <div className="grid gap-3 md:grid-cols-2">
          <Toggle checked={enabled} onChange={setEnabled} label="Tracking enabled" description="Disabling closes any open alert for this item." />
          {isEdit && <SnoozeField value={snooze} onChange={setSnooze} formatDate={props.formatDate} />}
        </div>
      </Section>
    </ConfigModalShell>
  );
}

/** Opens the right editor for a target. */
export function ConfigEditor({ target, ...props }: EditorProps & { target: ConfigEditorTarget }) {
  switch (target.kind) {
    case "vm":
      return <VMConfigEditor config={target.config} presetResourceId={target.preset?.resourceId} {...props} />;
    case "pg":
      return <PGConfigEditor config={target.config} presetResourceId={target.preset?.resourceId} {...props} />;
    case "storage":
      return <StorageConfigEditor config={target.config} presetResourceId={target.preset?.resourceId} {...props} />;
    case "expiry":
      return <ExpiryConfigEditor config={target.config} presetType={target.preset?.alertType} {...props} />;
  }
}

