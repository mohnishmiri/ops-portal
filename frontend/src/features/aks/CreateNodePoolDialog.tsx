/**
 * "Add a node pool" — the Azure portal's create form for an AKS node pool,
 * in four steps: Basics, Optional settings, Tags, and Review + create.
 *
 * The choices come from the backend's view of the cluster (VM sizes the
 * subscription can deploy in the region, Kubernetes versions, the subnets the
 * cluster's pools use and their free IPs), and every field is checked as it's
 * entered. The backend repeats the checks before calling Azure.
 */

import React, { useMemo, useState } from "react";
import {
  CreateNodePoolPayload,
  NodePoolCreateOptions,
  NodePoolVmSize,
  useCreateNodePool,
  useNodePoolCreateOptions,
} from "../../services/aksApi";
import { apiErrorDetail } from "./detailShared";
import { DetailCard, PropertyList } from "./ResourceDetailShell";

type Step = "basics" | "optional" | "tags" | "review";
const STEPS: { key: Step; label: string }[] = [
  { key: "basics", label: "Basics" },
  { key: "optional", label: "Optional settings" },
  { key: "tags", label: "Tags" },
  { key: "review", label: "Review + create" },
];

const MAX_NODES = 1000;
export const TAINT_EFFECTS = ["NoSchedule", "PreferNoSchedule", "NoExecute"] as const;
/** The Azure portal's OS disk sizes; "" leaves the size to Azure. */
const DISK_SIZES = [128, 256, 512, 1024, 2048];
const OS_SKUS = {
  Linux: [
    { value: "Ubuntu", label: "Ubuntu Linux" },
    { value: "AzureLinux", label: "Azure Linux" },
  ],
  Windows: [
    { value: "Windows2022", label: "Windows Server 2022" },
    { value: "Windows2019", label: "Windows Server 2019" },
  ],
} as const;

export interface KV {
  key: string;
  value: string;
}
export interface TaintRow extends KV {
  effect: string;
}

export interface NodePoolForm {
  name: string;
  mode: "User" | "System";
  osType: "Linux" | "Windows";
  osSku: string;
  version: string;
  zones: string[];
  spot: boolean;
  vmSize: string;
  osDiskType: "" | "Managed" | "Ephemeral";
  osDiskSize: string;
  scaleMethod: "auto" | "manual";
  nodeCount: string;
  minCount: string;
  maxCount: string;
  maxPods: string;
  surgeMode: "default" | "count" | "percent";
  surgeValue: string;
  subnetId: string;
  labels: KV[];
  taints: TaintRow[];
  tags: KV[];
}

type Field = keyof NodePoolForm;
const FIELD_STEP: Record<Field, Step> = {
  name: "basics",
  mode: "basics",
  osType: "basics",
  osSku: "basics",
  version: "basics",
  zones: "basics",
  spot: "basics",
  vmSize: "basics",
  osDiskType: "basics",
  osDiskSize: "basics",
  scaleMethod: "basics",
  nodeCount: "basics",
  minCount: "basics",
  maxCount: "basics",
  maxPods: "optional",
  surgeMode: "optional",
  surgeValue: "optional",
  subnetId: "optional",
  labels: "optional",
  taints: "optional",
  tags: "tags",
};

const FIELD_LABEL: Record<Field, string> = {
  name: "Node pool name",
  mode: "Mode",
  osType: "OS type",
  osSku: "OS SKU",
  version: "Kubernetes version",
  zones: "Availability zones",
  spot: "Azure Spot",
  vmSize: "Node size",
  osDiskType: "OS disk type",
  osDiskSize: "OS disk size",
  scaleMethod: "Scale method",
  nodeCount: "Node count",
  minCount: "Minimum node count",
  maxCount: "Maximum node count",
  maxPods: "Max pods per node",
  surgeMode: "Maximum surge",
  surgeValue: "Maximum surge",
  subnetId: "Subnet",
  labels: "Labels",
  taints: "Taints",
  tags: "Tags",
};

// ── Rules (the backend enforces the same) ─────────────────────────────

const LABEL_NAME = "[A-Za-z0-9]([-A-Za-z0-9_.]{0,61}[A-Za-z0-9])?";
const DNS_PREFIX = "[a-z0-9]([-a-z0-9]*[a-z0-9])?(\\.[a-z0-9]([-a-z0-9]*[a-z0-9])?)*";
const LABEL_KEY_RE = new RegExp(`^(?:(${DNS_PREFIX})/)?${LABEL_NAME}$`);
const LABEL_VALUE_RE = new RegExp(`^(?:${LABEL_NAME})?$`);
const RESERVED_DOMAINS = ["kubernetes.azure.com", "kubernetes.io", "k8s.io"];
const TAG_FORBIDDEN = /[<>%&\\?/]/;
const whole = (v: string) => /^\d+$/.test(v.trim());

export function labelKeyError(key: string): string | null {
  const match = LABEL_KEY_RE.exec(key);
  if (!match) return "Not a valid Kubernetes label key.";
  const prefix = match[1] ?? "";
  if (prefix && RESERVED_DOMAINS.some((d) => prefix === d || prefix.endsWith(`.${d}`))) {
    return "This domain is reserved by Kubernetes or AKS.";
  }
  return null;
}

/** Label and taint rows as Kubernetes and AKS accept them; empty rows are ignored. */
export function validateLabelsAndTaints(labels: KV[], taints: TaintRow[]): { labels?: string; taints?: string } {
  const errors: { labels?: string; taints?: string } = {};
  const labelKeys = new Set<string>();
  for (const { key, value } of labels) {
    if (!key && !value) continue;
    const keyError = labelKeyError(key);
    if (keyError) errors.labels = `${key || "(empty key)"}: ${keyError}`;
    else if (!LABEL_VALUE_RE.test(value)) errors.labels = `${key}: not a valid label value.`;
    else if (labelKeys.has(key)) errors.labels = `${key} is set twice.`;
    labelKeys.add(key);
  }
  const taintKeys = new Set<string>();
  for (const { key, value, effect } of taints) {
    if (!key && !value && !effect) continue;
    if (!LABEL_KEY_RE.test(key)) errors.taints = `${key || "(empty key)"}: not a valid taint key.`;
    else if (!LABEL_VALUE_RE.test(value)) errors.taints = `${key}: not a valid taint value.`;
    else if (!effect) errors.taints = `${key}: choose an effect.`;
    else if (taintKeys.has(`${key}:${effect}`)) errors.taints = `${key} with effect ${effect} is set twice.`;
    taintKeys.add(`${key}:${effect}`);
  }
  return errors;
}

/** "key=value:Effect" strings for the API. */
export function taintStrings(rows: TaintRow[]): string[] {
  return rows.filter((t) => t.key).map((t) => `${t.key.trim()}${t.value ? `=${t.value.trim()}` : ""}:${t.effect}`);
}

/** Subnet IPs a node reserves: classic Azure CNI gives every pod a VNet IP. */
export function ipsPerNode(options: NodePoolCreateOptions, podSubnet: boolean, maxPods: number): number {
  const azureCni = (options.network_plugin ?? "").toLowerCase() === "azure" && (options.network_plugin_mode ?? "").toLowerCase() !== "overlay";
  return azureCni && !podSubnet ? maxPods + 1 : 1;
}

export function sizeLabel(name: string): string {
  return name.replace(/_/g, " ");
}

export function defaultForm(options: NodePoolCreateOptions): NodePoolForm {
  const surge = options.defaults.max_surge;
  return {
    name: "",
    mode: "User",
    osType: "Linux",
    osSku: "Ubuntu",
    version: options.control_plane_version,
    zones: options.defaults.availability_zones.filter((z) => options.zones.includes(z)),
    spot: false,
    vmSize: options.defaults.vm_size ?? "",
    osDiskType: "",
    osDiskSize: "",
    scaleMethod: "auto",
    nodeCount: "1",
    minCount: "1",
    maxCount: "5",
    maxPods: String(Math.min(options.defaults.max_pods || 30, options.max_pods_limit)),
    surgeMode: !surge ? "default" : surge.endsWith("%") ? "percent" : "count",
    surgeValue: surge ? surge.replace("%", "") : "",
    subnetId: options.subnets[0]?.id ?? "",
    labels: [],
    taints: [],
    tags: [],
  };
}

export function validateForm(form: NodePoolForm, options: NodePoolCreateOptions): Partial<Record<Field, string>> {
  const errors: Partial<Record<Field, string>> = {};
  const windows = form.osType === "Windows";
  const nameRe = windows ? /^[a-z][a-z0-9]{0,5}$/ : /^[a-z][a-z0-9]{0,11}$/;
  if (!form.name) errors.name = "Enter a name.";
  else if (!nameRe.test(form.name)) errors.name = `Use 1–${windows ? 6 : 12} lowercase letters and digits, starting with a letter.`;
  else if (options.existing_pools.includes(form.name)) errors.name = "This cluster already has a node pool with this name.";

  if (windows && !options.windows_supported) errors.osType = "This cluster wasn't created with Windows support.";
  if (windows && form.mode === "System") errors.mode = "Windows node pools must be User pools.";
  if (form.spot && form.mode === "System") errors.spot = "Spot node pools must be User pools.";

  const size = options.vm_sizes.find((s) => s.name.toLowerCase() === form.vmSize.toLowerCase());
  if (!form.vmSize) errors.vmSize = "Choose a node size.";
  else if (options.vm_sizes.length && !size) errors.vmSize = `${form.vmSize} isn't available to this subscription in ${options.location}.`;
  else if (!options.vm_sizes.length && !/^Standard_[A-Za-z0-9_]{2,60}$/.test(form.vmSize)) errors.vmSize = "Enter a size like Standard_D8s_v3.";
  if (size) {
    if (form.mode === "System" && (size.vcpus < 2 || size.memory_gb < 4)) errors.vmSize = "System pools need at least 2 vCPUs and 4 GiB of memory.";
    else if (form.spot && !size.spot) errors.vmSize = `${size.name} can't run as Spot capacity.`;
    else if (windows && size.arch !== "x64") errors.vmSize = "Windows pools need an x64 VM size.";
    const missing = form.zones.filter((z) => !size.zones.includes(z));
    if (missing.length) errors.zones = `${sizeLabel(size.name)} isn't offered in zone ${missing.join(", ")} here.`;
  }

  const disk = form.osDiskSize ? Number(form.osDiskSize) : null;
  if (disk !== null && !DISK_SIZES.includes(disk)) errors.osDiskSize = "Choose a disk size.";
  else if (form.osDiskType === "Ephemeral" && size) {
    if (!size.ephemeral_os_disk) errors.osDiskType = `${sizeLabel(size.name)} doesn't support ephemeral OS disks.`;
    else if (disk !== null && disk > size.max_ephemeral_os_disk_gb) errors.osDiskSize = `An ephemeral OS disk on this size can be at most ${size.max_ephemeral_os_disk_gb} GiB.`;
  }

  const floor = form.mode === "System" ? 1 : 0;
  if (form.scaleMethod === "auto") {
    const min = Number(form.minCount);
    const max = Number(form.maxCount);
    if (!whole(form.minCount) || min < floor || min > MAX_NODES) errors.minCount = `Use ${floor}–${MAX_NODES}.`;
    if (!whole(form.maxCount) || max < 1 || max > MAX_NODES) errors.maxCount = `Use 1–${MAX_NODES}.`;
    else if (!errors.minCount && min > max) errors.maxCount = "Must be at least the minimum.";
  } else if (!whole(form.nodeCount) || Number(form.nodeCount) < floor || Number(form.nodeCount) > MAX_NODES) {
    errors.nodeCount = `Use ${floor}–${MAX_NODES}.`;
  }

  const maxPods = Number(form.maxPods);
  if (!whole(form.maxPods) || maxPods < 10 || maxPods > options.max_pods_limit) errors.maxPods = `Use 10–${options.max_pods_limit}.`;
  if (form.surgeMode === "percent" && !(whole(form.surgeValue) && Number(form.surgeValue) >= 1 && Number(form.surgeValue) <= 100)) errors.surgeValue = "Use 1–100%.";
  if (form.surgeMode === "count" && !(whole(form.surgeValue) && Number(form.surgeValue) >= 1 && Number(form.surgeValue) <= 1000)) errors.surgeValue = "Use 1–1000 nodes.";

  Object.assign(errors, validateLabelsAndTaints(form.labels, form.taints));
  const tagKeys = new Set<string>();
  for (const { key, value } of form.tags) {
    if (!key && !value) continue;
    if (!key || key.length > 512 || TAG_FORBIDDEN.test(key)) errors.tags = `${key || "(empty name)"}: tag names are 1–512 characters without < > % & \\ ? /.`;
    else if (value.length > 256) errors.tags = `${key}: values can be at most 256 characters.`;
    else if (tagKeys.has(key)) errors.tags = `${key} is set twice.`;
    tagKeys.add(key);
  }

  const subnet = options.subnets.find((s) => s.id === form.subnetId);
  if (subnet?.free_ips != null && !errors.maxPods) {
    const initial = (form.scaleMethod === "auto" ? Number(form.minCount) : Number(form.nodeCount)) || 0;
    const needed = initial * ipsPerNode(options, subnet.pod_subnet, maxPods);
    if (needed > subnet.free_ips) errors.subnetId = `${subnet.name} has ${subnet.free_ips.toLocaleString()} free IPs; the first ${initial} nodes need ${needed.toLocaleString()}.`;
  }
  return errors;
}

export function toPayload(clusterId: string, form: NodePoolForm): CreateNodePoolPayload {
  const pairs = (rows: KV[]) => Object.fromEntries(rows.filter((r) => r.key).map((r) => [r.key.trim(), r.value.trim()]));
  const auto = form.scaleMethod === "auto";
  return {
    cluster_id: clusterId,
    name: form.name,
    mode: form.mode,
    os_type: form.osType,
    os_sku: form.osSku,
    kubernetes_version: form.version,
    availability_zones: form.zones,
    spot: form.spot,
    vm_size: form.vmSize,
    os_disk_type: form.osDiskType || null,
    os_disk_size_gb: form.osDiskSize ? Number(form.osDiskSize) : null,
    enable_auto_scaling: auto,
    node_count: auto ? null : Number(form.nodeCount),
    min_count: auto ? Number(form.minCount) : null,
    max_count: auto ? Number(form.maxCount) : null,
    max_pods: Number(form.maxPods),
    max_surge: form.surgeMode === "default" ? null : form.surgeMode === "percent" ? `${form.surgeValue}%` : form.surgeValue,
    subnet_id: form.subnetId || null,
    node_labels: pairs(form.labels),
    node_taints: taintStrings(form.taints),
    tags: pairs(form.tags),
  };
}

// ── Building blocks ───────────────────────────────────────────────────

const inputCls =
  "w-full rounded-lg border border-att-200 bg-white px-3 py-2 text-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100 disabled:bg-slate-50 disabled:text-slate-400";
const btn = {
  primary: "rounded-lg bg-att-500 px-4 py-2 text-sm font-medium text-white hover:bg-att-600 disabled:opacity-50",
  secondary: "rounded-lg border border-att-200 bg-white px-4 py-2 text-sm text-gray-700 hover:bg-att-50 disabled:opacity-50",
  link: "text-sm font-medium text-att-600 hover:text-att-800 hover:underline",
};

function Row({ label, htmlFor, hint, error, required, children }: {
  label: string;
  htmlFor?: string;
  hint?: React.ReactNode;
  error?: string;
  required?: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="grid grid-cols-1 gap-2 border-b border-slate-100 py-4 last:border-0 md:grid-cols-[14rem_1fr] md:gap-6">
      <label htmlFor={htmlFor} className="pt-2 text-sm font-medium text-slate-700">
        {label}
        {required && <span className="ml-0.5 text-red-600">*</span>}
      </label>
      <div className="min-w-0">
        {children}
        {error ? <p className="mt-1 text-xs text-red-600" role="alert">{error}</p> : hint ? <p className="mt-1 text-xs text-slate-500">{hint}</p> : null}
      </div>
    </div>
  );
}

function Radio<V extends string>({ name, value, options, onChange, disabled }: {
  name: string;
  value: V;
  options: { value: V; label: string; description?: string; disabled?: boolean }[];
  onChange: (v: V) => void;
  disabled?: boolean;
}) {
  return (
    <div className="space-y-2 pt-1.5" role="radiogroup">
      {options.map((o) => (
        <label key={o.value} className={`flex items-start gap-2 text-sm ${o.disabled || disabled ? "text-slate-400" : "text-slate-700"}`}>
          <input type="radio" name={name} value={o.value} checked={value === o.value} disabled={o.disabled || disabled} onChange={() => onChange(o.value)} className="mt-0.5 accent-att-500" />
          <span>
            {o.label}
            {o.description && <span className="block text-xs text-slate-500">{o.description}</span>}
          </span>
        </label>
      ))}
    </div>
  );
}

export function PairsEditor({ name, rows, onChange, keyLabel, valueLabel, addLabel, effects }: {
  /** Names the inputs for screen readers, e.g. "Label" → "Label key 1". */
  name: string;
  rows: (KV | TaintRow)[];
  onChange: (rows: (KV | TaintRow)[]) => void;
  keyLabel: string;
  valueLabel: string;
  addLabel: string;
  effects?: boolean;
}) {
  const update = (i: number, patch: Partial<TaintRow>) => onChange(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));
  return (
    <div className="space-y-2">
      {rows.length > 0 && (
        <div className={`grid gap-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500 ${effects ? "grid-cols-[1fr_1fr_11rem_2rem]" : "grid-cols-[1fr_1fr_2rem]"}`}>
          <span>{keyLabel}</span>
          <span>{valueLabel}</span>
          {effects && <span>Effect</span>}
        </div>
      )}
      {rows.map((row, i) => (
        <div key={i} className={`grid items-center gap-2 ${effects ? "grid-cols-[1fr_1fr_11rem_2rem]" : "grid-cols-[1fr_1fr_2rem]"}`}>
          <input aria-label={`${name} ${keyLabel.toLowerCase()} ${i + 1}`} value={row.key} onChange={(e) => update(i, { key: e.target.value })} className={inputCls} />
          <input aria-label={`${name} ${valueLabel.toLowerCase()} ${i + 1}`} value={row.value} onChange={(e) => update(i, { value: e.target.value })} className={inputCls} />
          {effects && (
            <select aria-label={`${name} effect ${i + 1}`} value={(row as TaintRow).effect} onChange={(e) => update(i, { effect: e.target.value })} className={inputCls}>
              <option value="">Select…</option>
              {TAINT_EFFECTS.map((eff) => <option key={eff} value={eff}>{eff}</option>)}
            </select>
          )}
          <button type="button" title="Remove" aria-label={`Remove row ${i + 1}`} onClick={() => onChange(rows.filter((_, j) => j !== i))} className="rounded p-1.5 text-red-600 hover:bg-red-50">
            <svg width={16} height={16} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6" /><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" /></svg>
          </button>
        </div>
      ))}
      <button type="button" onClick={() => onChange([...rows, effects ? { key: "", value: "", effect: "NoSchedule" } : { key: "", value: "" }])} className={btn.link}>
        + {addLabel}
      </button>
    </div>
  );
}

function VmSizePicker({ sizes, value, onChange, osType, spot }: {
  sizes: NodePoolVmSize[];
  value: string;
  onChange: (name: string) => void;
  osType: "Linux" | "Windows";
  spot: boolean;
}) {
  const [open, setOpen] = useState(!value);
  const [search, setSearch] = useState("");
  const selected = sizes.find((s) => s.name === value);
  const matches = useMemo(() => {
    const q = search.trim().toLowerCase().replace(/\s+/g, "_");
    return sizes
      .filter((s) => (!q || s.name.toLowerCase().includes(q) || (s.family ?? "").toLowerCase().includes(q)) && (osType === "Linux" || s.arch === "x64") && (!spot || s.spot))
      .slice(0, 60);
  }, [sizes, search, osType, spot]);

  return (
    <div>
      {selected && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-l-4 border-green-500 bg-slate-50 px-3 py-2">
          <div>
            <div className="text-sm font-semibold text-slate-800">{sizeLabel(selected.name)}</div>
            <div className="text-xs text-slate-600">
              {selected.vcpus} vCPUs, {selected.memory_gb} GiB memory{selected.arch !== "x64" ? ` · ${selected.arch}` : ""}
            </div>
          </div>
          <button type="button" onClick={() => setOpen((v) => !v)} className={btn.link}>{open ? "Done" : "Choose a size"}</button>
        </div>
      )}
      {open && (
        <div className="mt-2 rounded-lg border border-att-100">
          <input
            aria-label="Search VM sizes"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search sizes, e.g. D32s v5, E16, Standard_F8s"
            className="w-full rounded-t-lg border-b border-att-100 px-3 py-2 text-sm focus:outline-none"
          />
          <div className="max-h-64 overflow-y-auto" role="listbox" aria-label="VM sizes">
            {matches.length === 0 && <p className="px-3 py-4 text-sm text-slate-500">No sizes match.</p>}
            {matches.map((s) => (
              <button
                key={s.name}
                type="button"
                role="option"
                aria-selected={s.name === value}
                onClick={() => {
                  onChange(s.name);
                  setOpen(false);
                }}
                className={`grid w-full grid-cols-[1fr_5rem_6rem_auto] items-center gap-3 px-3 py-2 text-left text-sm hover:bg-att-50 ${s.name === value ? "bg-att-50" : ""}`}
              >
                <span className="font-medium text-slate-800">{sizeLabel(s.name)}</span>
                <span className="text-xs text-slate-600">{s.vcpus} vCPUs</span>
                <span className="text-xs text-slate-600">{s.memory_gb} GiB</span>
                <span className="flex gap-1">
                  {s.ephemeral_os_disk && <span className="rounded bg-slate-100 px-1.5 text-[10px] text-slate-600">Ephemeral OS</span>}
                  {s.spot && <span className="rounded bg-orange-50 px-1.5 text-[10px] text-orange-700">Spot</span>}
                  <span className="rounded bg-slate-100 px-1.5 text-[10px] text-slate-600">Zones {s.zones.join(",") || "—"}</span>
                </span>
              </button>
            ))}
          </div>
          {matches.length === 60 && <p className="border-t border-att-100 px-3 py-1.5 text-[11px] text-slate-500">Showing the first 60 matches; refine the search.</p>}
        </div>
      )}
    </div>
  );
}

// ── Dialog ────────────────────────────────────────────────────────────

export function CreateNodePoolDialog({
  clusterId,
  clusterName,
  onClose,
  onCreated,
}: {
  clusterId: string;
  clusterName: string;
  onClose: () => void;
  onCreated: (name: string) => void;
}) {
  const { data: options, isLoading, isError, error } = useNodePoolCreateOptions(clusterId, true);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4" role="dialog" aria-modal="true" aria-label="Add a node pool">
      <div className="flex h-[90vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-att-100">
        <header className="flex items-start justify-between gap-4 border-b border-att-100 bg-gradient-to-r from-att-50 to-white px-6 py-4">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-att-700">Node Pools</p>
            <h2 className="text-xl font-semibold text-slate-900">Add a node pool</h2>
            <p className="text-sm text-slate-500">Cluster {clusterName}{options ? ` · ${options.location} · Kubernetes ${options.control_plane_version}` : ""}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600">✕</button>
        </header>
        {isLoading && <div className="flex flex-1 items-center justify-center text-sm text-slate-500">Reading the cluster's settings from Azure…</div>}
        {isError && (
          <div className="m-6 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
            {apiErrorDetail(error, "Unable to read the cluster's node pool settings from Azure.")}
          </div>
        )}
        {options && <CreateNodePoolForm clusterId={clusterId} options={options} onClose={onClose} onCreated={onCreated} />}
      </div>
    </div>
  );
}

function CreateNodePoolForm({ clusterId, options, onClose, onCreated }: {
  clusterId: string;
  options: NodePoolCreateOptions;
  onClose: () => void;
  onCreated: (name: string) => void;
}) {
  const [step, setStep] = useState<Step>("basics");
  const [form, setForm] = useState<NodePoolForm>(() => defaultForm(options));
  const [touched, setTouched] = useState<Set<Step>>(new Set());
  const create = useCreateNodePool();
  const set = <K extends Field>(key: K, value: NodePoolForm[K]) => setForm((f) => ({ ...f, [key]: value }));

  const errors = useMemo(() => validateForm(form, options), [form, options]);
  const stepErrors = (s: Step) => Object.keys(errors).filter((f) => FIELD_STEP[f as Field] === s).length;
  // Errors appear once a step has been visited and left, or on Review.
  const show = (f: Field) => (touched.has(FIELD_STEP[f]) || step === "review" ? errors[f] : undefined);
  const go = (next: Step) => {
    setTouched((t) => new Set(t).add(step));
    setStep(next);
  };
  const index = STEPS.findIndex((s) => s.key === step);
  const size = options.vm_sizes.find((s) => s.name === form.vmSize);
  const subnet = options.subnets.find((s) => s.id === form.subnetId);
  const maxPods = Number(form.maxPods) || 0;
  const perNode = ipsPerNode(options, !!subnet?.pod_subnet, maxPods);
  const auto = form.scaleMethod === "auto";
  const initialNodes = (auto ? Number(form.minCount) : Number(form.nodeCount)) || 0;
  const peakNodes = (auto ? Number(form.maxCount) : Number(form.nodeCount)) || 0;
  const errorCount = Object.keys(errors).length;
  const ephemeralFits = !!size?.ephemeral_os_disk && (!form.osDiskSize || Number(form.osDiskSize) <= size.max_ephemeral_os_disk_gb);

  const submit = () =>
    create.mutate(toPayload(clusterId, form), {
      onSuccess: () => onCreated(form.name),
    });

  return (
    <>
      <nav className="flex shrink-0 gap-1 border-b border-att-100 px-6" role="tablist" aria-label="Steps">
        {STEPS.map((s) => {
          const count = s.key === "review" ? 0 : stepErrors(s.key);
          return (
            <button
              key={s.key}
              type="button"
              role="tab"
              aria-selected={step === s.key}
              onClick={() => go(s.key)}
              className={`-mb-px border-b-2 px-3 py-3 text-sm font-medium ${step === s.key ? "border-att-500 text-att-700" : "border-transparent text-slate-500 hover:text-slate-800"}`}
            >
              {s.label}
              {count > 0 && touched.has(s.key) && <span className="ml-1.5 rounded-full bg-red-100 px-1.5 text-[11px] font-semibold text-red-700">{count}</span>}
            </button>
          );
        })}
      </nav>

      <div className="flex-1 overflow-y-auto px-6 py-2">
        {step === "basics" && (
          <>
            <Row label="Node pool name" htmlFor="np-name" required error={show("name")} hint={`Lowercase letters and digits, starting with a letter; up to ${form.osType === "Windows" ? 6 : 12} characters.`}>
              <input id="np-name" value={form.name} onChange={(e) => set("name", e.target.value.trim())} className={inputCls} autoFocus />
            </Row>
            <Row label="Mode" error={show("mode")} hint={form.mode === "System" ? "System pools run critical add-ons such as CoreDNS. Microsoft recommends at least 2 nodes, 3 for production." : undefined}>
              <Radio name="np-mode" value={form.mode} onChange={(v) => setForm((f) => ({ ...f, mode: v, spot: v === "System" ? false : f.spot }))}
                options={[{ value: "User", label: "User" }, { value: "System", label: "System", disabled: form.osType === "Windows" }]} />
            </Row>
            <Row label="OS type" error={show("osType")} hint={!options.windows_supported ? "This cluster wasn't created with Windows support." : undefined}>
              <Radio name="np-os" value={form.osType} onChange={(v) => setForm((f) => ({ ...f, osType: v, osSku: OS_SKUS[v][0].value, mode: v === "Windows" ? "User" : f.mode }))}
                options={[{ value: "Linux", label: "Linux" }, { value: "Windows", label: "Windows", disabled: !options.windows_supported }]} />
            </Row>
            <Row label="OS SKU" htmlFor="np-sku">
              <select id="np-sku" value={form.osSku} onChange={(e) => set("osSku", e.target.value)} className={inputCls}>
                {OS_SKUS[form.osType].map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </Row>
            <Row label="Kubernetes version" htmlFor="np-version" hint="New pools can run the control plane's version or a version an existing pool runs.">
              <select id="np-version" value={form.version} onChange={(e) => set("version", e.target.value)} className={inputCls}>
                {options.kubernetes_versions.map((v) => <option key={v} value={v}>{v}{v === options.control_plane_version ? " (control plane)" : ""}</option>)}
              </select>
            </Row>
            <Row label="Availability zones" error={show("zones")} hint={form.zones.length ? undefined : "No zones: nodes go wherever Azure places them in the region."}>
              <div className="flex flex-wrap gap-4 pt-2">
                {options.zones.map((z) => (
                  <label key={z} className="flex items-center gap-2 text-sm text-slate-700">
                    <input type="checkbox" checked={form.zones.includes(z)} onChange={(e) => set("zones", e.target.checked ? [...form.zones, z].sort() : form.zones.filter((x) => x !== z))} className="accent-att-500" />
                    Zone {z}
                  </label>
                ))}
              </div>
            </Row>
            <Row label="Azure Spot instances" error={show("spot")} hint={form.spot ? "Spot nodes can be evicted at any time. AKS taints them (kubernetes.azure.com/scalesetpriority=spot:NoSchedule), so only pods that tolerate it run there. Evicted nodes are deleted; the price is capped at on-demand. This can't be changed later." : undefined}>
              <label className="flex items-center gap-2 pt-2 text-sm text-slate-700">
                <input type="checkbox" checked={form.spot} disabled={form.mode === "System"} onChange={(e) => set("spot", e.target.checked)} className="accent-att-500" />
                Use Spot capacity{form.mode === "System" && <span className="text-xs text-slate-400">(User pools only)</span>}
              </label>
            </Row>
            <Row label="Node size" required error={show("vmSize")} hint={options.vm_sizes_error ?? `${options.vm_sizes.length.toLocaleString()} size${options.vm_sizes.length === 1 ? "" : "s"} available to this subscription in ${options.location}.`}>
              {options.vm_sizes.length ? (
                <VmSizePicker sizes={options.vm_sizes} value={form.vmSize} onChange={(v) => set("vmSize", v)} osType={form.osType} spot={form.spot} />
              ) : (
                <input aria-label="Node size" value={form.vmSize} onChange={(e) => set("vmSize", e.target.value.trim())} placeholder="Standard_D8s_v3" className={inputCls} />
              )}
            </Row>
            <Row label="OS disk type" htmlFor="np-disktype" required error={show("osDiskType")}>
              <select id="np-disktype" value={form.osDiskType} onChange={(e) => set("osDiskType", e.target.value as NodePoolForm["osDiskType"])} className={inputCls}>
                <option value="">Default (based on selected VM: {size ? (ephemeralFits ? "Ephemeral" : "Managed") : "Azure decides"})</option>
                <option value="Ephemeral" disabled={!!size && !size.ephemeral_os_disk}>Ephemeral</option>
                <option value="Managed">Managed</option>
              </select>
            </Row>
            <Row label="OS disk size (GiB)" htmlFor="np-disksize" required error={show("osDiskSize")} hint={size?.ephemeral_os_disk ? `Ephemeral on this size: up to ${size.max_ephemeral_os_disk_gb} GiB.` : undefined}>
              <select id="np-disksize" value={form.osDiskSize} onChange={(e) => set("osDiskSize", e.target.value)} className={inputCls}>
                <option value="">{size ? "Default (based on selected VM)" : "Default (select a VM size)"}</option>
                {DISK_SIZES.map((gb) => (
                  <option key={gb} value={String(gb)} disabled={form.osDiskType === "Ephemeral" && !!size && gb > size.max_ephemeral_os_disk_gb}>
                    {gb}
                  </option>
                ))}
              </select>
            </Row>
            <Row label="Scale method">
              <Radio name="np-scale" value={form.scaleMethod} onChange={(v) => set("scaleMethod", v)} options={[
                { value: "auto", label: "Autoscale (recommended)", description: "Adjusts the number of nodes to your workloads' resource demands." },
                { value: "manual", label: "Manual", description: "A fixed number of nodes you change yourself." },
              ]} />
            </Row>
            {auto ? (
              <>
                <Row label="Minimum node count" htmlFor="np-min" required error={show("minCount")}>
                  <input id="np-min" type="number" min={form.mode === "System" ? 1 : 0} max={MAX_NODES} value={form.minCount} onChange={(e) => set("minCount", e.target.value)} className={inputCls} />
                </Row>
                <Row label="Maximum node count" htmlFor="np-max" required error={show("maxCount")} hint="AKS allows up to 1,000 nodes per node pool and 5,000 across the cluster's pools.">
                  <input id="np-max" type="number" min={1} max={MAX_NODES} value={form.maxCount} onChange={(e) => set("maxCount", e.target.value)} className={inputCls} />
                </Row>
              </>
            ) : (
              <Row label="Node count" htmlFor="np-count" required error={show("nodeCount")}>
                <input id="np-count" type="number" min={form.mode === "System" ? 1 : 0} max={MAX_NODES} value={form.nodeCount} onChange={(e) => set("nodeCount", e.target.value)} className={inputCls} />
              </Row>
            )}
          </>
        )}

        {step === "optional" && (
          <>
            <Row label="Max pods per node" htmlFor="np-maxpods" required error={show("maxPods")} hint={`10–${options.max_pods_limit}. Existing pools mostly use ${options.defaults.max_pods}.`}>
              <input id="np-maxpods" type="number" min={10} max={options.max_pods_limit} value={form.maxPods} onChange={(e) => set("maxPods", e.target.value)} className={inputCls} />
            </Row>
            <Row label="Maximum surge" error={show("surgeValue")} hint="Extra nodes added while upgrading, so pods move without losing capacity.">
              <Radio name="np-surge" value={form.surgeMode} onChange={(v) => set("surgeMode", v)} options={[
                { value: "default", label: "Default (10%)" },
                { value: "count", label: "Define by node count" },
                { value: "percent", label: "Define by percentage" },
              ]} />
              {form.surgeMode !== "default" && (
                <div className="mt-2 flex max-w-xs items-center gap-2">
                  <input aria-label="Maximum surge" type="number" min={1} value={form.surgeValue} onChange={(e) => set("surgeValue", e.target.value)} className={inputCls} />
                  <span className="text-sm text-slate-500">{form.surgeMode === "percent" ? "%" : "nodes"}</span>
                </div>
              )}
            </Row>
            <Row label="Subnet" htmlFor="np-subnet" error={show("subnetId")} hint={options.subnets.length ? "The cluster's pools share this VNet; a new pool can use a subnet they already use." : "This cluster uses an AKS-managed network."}>
              {options.subnets.length > 0 && (
                <>
                  <select id="np-subnet" value={form.subnetId} onChange={(e) => set("subnetId", e.target.value)} className={inputCls}>
                    {options.subnets.map((s) => (
                      <option key={s.id} value={s.id}>
                        {s.name}{s.free_ips != null ? ` · ${s.free_ips.toLocaleString()} of ${s.total_ips?.toLocaleString()} IPs free` : ""}
                      </option>
                    ))}
                  </select>
                  <IpPlan perNode={perNode} initialNodes={initialNodes} peakNodes={peakNodes} freeIps={subnet?.free_ips ?? null} />
                </>
              )}
            </Row>
            <Row label="Labels" error={show("labels")} hint="Applied to every node in the pool, e.g. nodepool=ruleengine for workload placement.">
              <PairsEditor name="Label" rows={form.labels} onChange={(rows) => set("labels", rows as KV[])} keyLabel="Key" valueLabel="Value" addLabel="Add label" />
            </Row>
            <Row label="Taints" error={show("taints")} hint="Only pods that tolerate a taint are scheduled on these nodes.">
              <PairsEditor name="Taint" rows={form.taints} onChange={(rows) => set("taints", rows as TaintRow[])} keyLabel="Key" valueLabel="Value" addLabel="Add taint" effects />
            </Row>
          </>
        )}

        {step === "tags" && (
          <Row label="Tags" error={show("tags")} hint="Azure tags on the pool's scale set, used for cost reporting and policy.">
            <PairsEditor name="Tag" rows={form.tags} onChange={(rows) => set("tags", rows as KV[])} keyLabel="Name" valueLabel="Value" addLabel="Add tag" />
          </Row>
        )}

        {step === "review" && (
          <div className="space-y-4 py-4">
            {errorCount > 0 ? (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800" role="alert">
                <p className="font-semibold">Fix {errorCount} problem{errorCount === 1 ? "" : "s"} before creating:</p>
                <ul className="mt-1 list-disc pl-5">
                  {Object.entries(errors).map(([f, msg]) => (
                    <li key={f}>
                      <span className="font-medium">{FIELD_LABEL[f as Field]}:</span> {msg}{" "}
                      <button type="button" className={btn.link} onClick={() => go(FIELD_STEP[f as Field])}>Go to {STEPS.find((s) => s.key === FIELD_STEP[f as Field])?.label}</button>
                    </li>
                  ))}
                </ul>
              </div>
            ) : (
              <div className="rounded-lg border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">Validation passed. Azure creates the pool in the background; it usually takes several minutes.</div>
            )}
            {create.isError && (
              <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700" role="alert">
                {apiErrorDetail(create.error, "Azure rejected the node pool.")}
              </div>
            )}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
              <DetailCard title="Basics">
                <PropertyList items={[
                  { label: "Name", value: form.name, mono: true },
                  { label: "Mode", value: form.mode },
                  { label: "OS", value: `${form.osType} · ${OS_SKUS[form.osType].find((o) => o.value === form.osSku)?.label ?? form.osSku}` },
                  { label: "Kubernetes", value: form.version, mono: true },
                  { label: "Node Size", value: size ? `${sizeLabel(size.name)} (${size.vcpus} vCPUs, ${size.memory_gb} GiB)` : form.vmSize },
                  { label: "Availability Zones", value: form.zones.length ? form.zones.join(", ") : "None" },
                  { label: "Priority", value: form.spot ? "Spot (evictable, delete on eviction)" : "Regular" },
                  { label: "OS Disk", value: `${form.osDiskSize ? `${form.osDiskSize} GiB` : "Default size"} · ${form.osDiskType || "Default type"}` },
                  { label: "Scale", value: auto ? `Autoscale ${form.minCount}–${form.maxCount} nodes` : `${form.nodeCount} nodes (manual)` },
                ]} />
              </DetailCard>
              <DetailCard title="Optional Settings">
                <PropertyList items={[
                  { label: "Max Pods per Node", value: form.maxPods },
                  { label: "Maximum Surge", value: form.surgeMode === "default" ? "Default (10%)" : `${form.surgeValue}${form.surgeMode === "percent" ? "%" : " nodes"}` },
                  { label: "Labels", value: form.labels.filter((l) => l.key).map((l) => `${l.key}=${l.value}`).join(", ") || "None", wide: true },
                  { label: "Taints", value: toPayload(clusterId, form).node_taints.join(", ") || "None", wide: true },
                  { label: "Tags", value: form.tags.filter((t) => t.key).map((t) => `${t.key}=${t.value}`).join(", ") || "None", wide: true },
                ]} />
              </DetailCard>
              <DetailCard title="Network & Security" subtitle={options.inherited.source_pool ? `Taken from ${options.inherited.source_pool}, so the pool matches the cluster's existing pools.` : undefined}>
                <PropertyList items={[
                  { label: "Subnet", value: subnet ? subnet.name : "AKS-managed", mono: true },
                  { label: "IPs Needed", value: perNode > 1 ? `${(initialNodes * perNode).toLocaleString()} now · ${(peakNodes * perNode).toLocaleString()} at ${peakNodes} nodes` : `${initialNodes}–${peakNodes} (one per node)` },
                  { label: "Free IPs", value: subnet?.free_ips != null ? subnet.free_ips.toLocaleString() : "Unknown" },
                  { label: "Node Public IPs", value: "Off" },
                  { label: "Encryption at Host", value: options.inherited.encryption_at_host ? "On" : "Off" },
                  { label: "FIPS", value: options.inherited.fips ? "On" : "Off" },
                ]} />
              </DetailCard>
            </div>
          </div>
        )}
      </div>

      <footer className="flex shrink-0 flex-wrap items-center justify-between gap-2 border-t border-att-100 bg-slate-50 px-6 py-3">
        <div className="flex gap-2">
          <button type="button" className={btn.secondary} disabled={index === 0} onClick={() => go(STEPS[index - 1].key)}>&lt; Previous</button>
          {step !== "review" && (
            <button type="button" className={btn.secondary} onClick={() => go(STEPS[index + 1].key)}>Next: {STEPS[index + 1].label} &gt;</button>
          )}
          {step !== "review" ? (
            <button type="button" className={btn.primary} onClick={() => go("review")}>Review + create</button>
          ) : (
            <button type="button" className={btn.primary} disabled={errorCount > 0 || create.isPending} onClick={submit}>
              {create.isPending ? "Creating…" : "Create"}
            </button>
          )}
        </div>
        <button type="button" className={btn.secondary} onClick={onClose}>Cancel</button>
      </footer>
    </>
  );
}

function IpPlan({ perNode, initialNodes, peakNodes, freeIps }: { perNode: number; initialNodes: number; peakNodes: number; freeIps: number | null }) {
  if (freeIps == null) return null;
  const now = initialNodes * perNode;
  const peak = peakNodes * perNode;
  const tone = now > freeIps ? "text-red-700" : peak > freeIps ? "text-amber-700" : "text-slate-600";
  return (
    <p className={`mt-2 text-xs ${tone}`}>
      {perNode > 1 ? `Each node reserves ${perNode} IPs (max pods + 1). ` : ""}
      Needs {now.toLocaleString()} IP{now === 1 ? "" : "s"} for the first {initialNodes} node{initialNodes === 1 ? "" : "s"} and {peak.toLocaleString()} at {peakNodes}
      {"; "}
      {freeIps.toLocaleString()} free.
      {peak > freeIps && now <= freeIps && " The pool can't reach its maximum on this subnet."}
    </p>
  );
}

export default CreateNodePoolDialog;
