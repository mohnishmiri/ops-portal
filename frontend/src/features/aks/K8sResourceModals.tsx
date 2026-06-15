/**
 * Modals for AKS extended K8s resources — view, edit, create, delete confirm.
 */

import React, { useEffect, useMemo, useState } from "react";
import {
  ConfigMapDetail,
  IngressDetail,
  SecretDetail,
  ServiceDetail,
  useConfigMapDetail,
  useIngressDetail,
  useSecretDetail,
  useServiceDetail,
} from "../../services/aksApi";

function ModalShell({
  title,
  subtitle,
  onClose,
  children,
  wide,
}: {
  title: string;
  subtitle?: string;
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
}) {
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className={`bg-white rounded-lg shadow-xl border border-att-100 w-full ${wide ? "max-w-2xl" : "max-w-lg"} max-h-[90vh] flex flex-col`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-start justify-between px-6 py-4 border-b border-att-100 bg-att-50/60 rounded-t-lg">
          <div>
            <h3 className="text-lg font-semibold text-att-800">{title}</h3>
            {subtitle ? <p className="text-sm text-gray-500 mt-0.5">{subtitle}</p> : null}
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-400 hover:text-att-700 text-xl leading-none ml-4"
            aria-label="Close"
          >
            &times;
          </button>
        </div>
        <div className="px-6 py-4 overflow-y-auto flex-1">{children}</div>
      </div>
    </div>
  );
}

function ModalSearchBar({
  value,
  onChange,
  placeholder,
  resultCount,
  totalCount,
}: {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  resultCount: number;
  totalCount: number;
}) {
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2">
      <div className="relative flex-1 min-w-[200px]">
        <input
          type="search"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={placeholder}
          className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-att-400 focus:border-att-400"
        />
      </div>
      <span className="text-xs text-gray-500 whitespace-nowrap">
        {resultCount} of {totalCount} shown
      </span>
    </div>
  );
}

function ModalLoadingState({ label = "Loading..." }: { label?: string }) {
  return (
    <div className="py-8 flex flex-col items-center gap-3 text-gray-500">
      <div className="h-8 w-8 rounded-full border-2 border-att-200 border-t-att-500 animate-spin" />
      <p className="text-sm">{label}</p>
    </div>
  );
}

function DetailSourceBadge({ source, lastSync }: { source?: string; lastSync?: string | null }) {
  if (!source) return null;
  const label = source === "db" ? "Cached inventory" : source === "live" ? "Live cluster" : source;
  return (
    <p className="text-xs text-gray-400 mb-3">
      Source: {label}
      {lastSync ? ` · synced ${lastSync}` : null}
    </p>
  );
}

function KeyValueEditor({
  data,
  onChange,
  readOnly,
  searchPlaceholder = "Search keys or values...",
}: {
  data: Record<string, string>;
  onChange?: (d: Record<string, string>) => void;
  readOnly?: boolean;
  searchPlaceholder?: string;
}) {
  const [search, setSearch] = useState("");
  const entries = Object.entries(data);
  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return entries;
    return entries.filter(([key, value]) => key.toLowerCase().includes(q) || value.toLowerCase().includes(q));
  }, [entries, search]);

  if (entries.length === 0) {
    return <p className="text-sm text-gray-500">No data keys</p>;
  }

  return (
    <div>
      {entries.length > 3 ? (
        <ModalSearchBar
          value={search}
          onChange={setSearch}
          placeholder={searchPlaceholder}
          resultCount={filtered.length}
          totalCount={entries.length}
        />
      ) : null}
      <div className="space-y-2 max-h-96 overflow-y-auto">
        {filtered.length === 0 ? (
          <p className="text-sm text-gray-400 py-4 text-center">No keys match your search</p>
        ) : (
          filtered.map(([key, value]) => (
            <div key={key} className="grid grid-cols-3 gap-2 items-start border border-gray-100 rounded-lg p-2 bg-gray-50/50">
              <span className="text-sm font-mono text-att-800 break-all col-span-1">{key}</span>
              {readOnly ? (
                <span className="text-sm font-mono text-gray-600 break-all col-span-2">{value}</span>
              ) : (
                <textarea
                  className="col-span-2 border rounded px-2 py-1 text-sm font-mono min-h-[2.5rem] focus:outline-none focus:ring-2 focus:ring-att-400"
                  value={value}
                  onChange={(e) => onChange?.({ ...data, [key]: e.target.value })}
                />
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}

function kvFromLines(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  text.split("\n").forEach((line) => {
    const idx = line.indexOf("=");
    if (idx > 0) {
      out[line.slice(0, idx).trim()] = line.slice(idx + 1);
    }
  });
  return out;
}

function kvToLines(data: Record<string, string>): string {
  return Object.entries(data).map(([k, v]) => `${k}=${v}`).join("\n");
}

function filterListItems<T>(items: T[], search: string, matcher: (item: T, q: string) => boolean): T[] {
  const q = search.trim().toLowerCase();
  if (!q) return items;
  return items.filter((item) => matcher(item, q));
}

// ── Secret modals ────────────────────────────────────────────────────

export function SecretViewModal({
  clusterId,
  namespace,
  name,
  canWrite,
  onClose,
  initialKeys,
}: {
  clusterId: string;
  namespace: string;
  name: string;
  canWrite: boolean;
  onClose: () => void;
  initialKeys?: string[];
}) {
  const [reveal, setReveal] = useState(false);
  const placeholderData = useMemo<SecretDetail | undefined>(() => {
    if (!initialKeys?.length) return undefined;
    return {
      name,
      namespace,
      type: "Opaque",
      data: Object.fromEntries(initialKeys.map((k) => [k, "***"])),
      keys: initialKeys,
      detail_source: "db",
    };
  }, [initialKeys, name, namespace]);

  const { data, isLoading, isFetching } = useSecretDetail(clusterId, namespace, name, reveal, true, placeholderData);
  const detail = data as SecretDetail | undefined;

  return (
    <ModalShell title={`Secret: ${name}`} subtitle={`Namespace: ${namespace}`} onClose={onClose} wide>
      {isLoading && !detail ? (
        <ModalLoadingState />
      ) : (
        <>
          <div className="flex flex-wrap gap-3 mb-4 text-sm text-gray-600">
            <span>Type: <strong>{detail?.type || "—"}</strong></span>
            {isFetching ? <span className="text-att-500 text-xs">Refreshing…</span> : null}
          </div>
          <DetailSourceBadge source={detail?.detail_source} lastSync={detail?._last_sync} />
          {canWrite && (
            <label className="flex items-center gap-2 mb-3 text-sm">
              <input type="checkbox" checked={reveal} onChange={(e) => setReveal(e.target.checked)} />
              Reveal secret values (requires live cluster access)
            </label>
          )}
          {detail?.detail_source === "db_masked" && detail.data_unavailable_reason ? (
            <p className="text-xs text-amber-600 mb-3">{detail.data_unavailable_reason}</p>
          ) : null}
          <KeyValueEditor data={detail?.data || {}} readOnly searchPlaceholder="Search secret keys..." />
        </>
      )}
    </ModalShell>
  );
}

export function SecretEditModal({
  clusterId,
  namespace,
  name,
  onClose,
  onSave,
  saving,
}: {
  clusterId: string;
  namespace: string;
  name: string;
  onClose: () => void;
  onSave: (data: Record<string, string>) => void;
  saving?: boolean;
}) {
  const { data, isLoading } = useSecretDetail(clusterId, namespace, name, true, true);
  const [kvText, setKvText] = useState("");

  useEffect(() => {
    if (data?.data) setKvText(kvToLines(data.data));
  }, [data]);

  return (
    <ModalShell title={`Edit Secret: ${name}`} onClose={onClose} wide>
      {isLoading ? (
        <ModalLoadingState />
      ) : (
        <>
          <p className="text-sm text-gray-500 mb-2">One key=value pair per line</p>
          <textarea
            className="w-full border rounded-lg px-3 py-2 font-mono text-sm min-h-[200px] focus:outline-none focus:ring-2 focus:ring-att-400"
            value={kvText}
            onChange={(e) => setKvText(e.target.value)}
          />
          <div className="flex justify-end gap-2 mt-4">
            <button type="button" onClick={onClose} className="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50">Cancel</button>
            <button
              type="button"
              disabled={saving}
              onClick={() => onSave(kvFromLines(kvText))}
              className="px-4 py-2 bg-att-500 text-white rounded-lg text-sm hover:bg-att-600 disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </>
      )}
    </ModalShell>
  );
}

export function SecretCreateModal({
  defaultNamespace,
  onClose,
  onSave,
  saving,
}: {
  defaultNamespace: string;
  onClose: () => void;
  onSave: (vars: { namespace: string; name: string; data: Record<string, string>; secretType: string }) => void;
  saving?: boolean;
}) {
  const [namespace, setNamespace] = useState(defaultNamespace || "default");
  const [name, setName] = useState("");
  const [secretType, setSecretType] = useState("Opaque");
  const [kvText, setKvText] = useState("");

  return (
    <ModalShell title="Create Secret" onClose={onClose} wide>
      <div className="space-y-3">
        <div>
          <label className="block text-sm font-medium mb-1">Namespace</label>
          <input className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-att-400" value={namespace} onChange={(e) => setNamespace(e.target.value)} />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Name</label>
          <input className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-att-400" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Type</label>
          <input className="w-full border rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-att-400" value={secretType} onChange={(e) => setSecretType(e.target.value)} />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Data (key=value per line)</label>
          <textarea className="w-full border rounded-lg px-3 py-2 font-mono text-sm min-h-[120px] focus:outline-none focus:ring-2 focus:ring-att-400" value={kvText} onChange={(e) => setKvText(e.target.value)} />
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-4">
        <button type="button" onClick={onClose} className="px-4 py-2 border rounded-lg text-sm hover:bg-gray-50">Cancel</button>
        <button
          type="button"
          disabled={saving || !name.trim()}
          onClick={() => onSave({ namespace, name: name.trim(), data: kvFromLines(kvText), secretType })}
          className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm hover:bg-green-700 disabled:opacity-50"
        >
          {saving ? "Creating..." : "Create"}
        </button>
      </div>
    </ModalShell>
  );
}

// ── Service modals ───────────────────────────────────────────────────

export function ServiceViewModal({
  clusterId,
  namespace,
  name,
  onClose,
}: {
  clusterId: string;
  namespace: string;
  name: string;
  onClose: () => void;
}) {
  const { data, isLoading, isFetching } = useServiceDetail(clusterId, namespace, name, true);
  const svc = data as ServiceDetail | undefined;
  const [search, setSearch] = useState("");
  const ports = svc?.ports || [];
  const filteredPorts = filterListItems(ports, search, (p, q) =>
    `${p.port} ${p.target_port} ${p.protocol} ${p.name || ""}`.toLowerCase().includes(q)
  );
  const selectorEntries = Object.entries(svc?.selector || {});
  const filteredSelector = filterListItems(selectorEntries, search, ([k, v], q) =>
    `${k} ${v}`.toLowerCase().includes(q)
  );

  return (
    <ModalShell title={`Service: ${name}`} subtitle={`Namespace: ${namespace}`} onClose={onClose} wide>
      {isLoading && !svc ? (
        <ModalLoadingState />
      ) : svc ? (
        <div className="space-y-3 text-sm">
          {isFetching ? <span className="text-att-500 text-xs">Refreshing…</span> : null}
          <DetailSourceBadge source={svc.detail_source} lastSync={svc._last_sync} />
          <ModalSearchBar
            value={search}
            onChange={setSearch}
            placeholder="Search ports, selector, fields..."
            resultCount={filteredPorts.length + filteredSelector.length}
            totalCount={ports.length + selectorEntries.length}
          />
          <p><span className="text-gray-500">Type:</span> {svc.type}</p>
          <p><span className="text-gray-500">Cluster IP:</span> {svc.cluster_ip || "—"}</p>
          <div>
            <p className="text-gray-500 mb-1">Ports</p>
            {filteredPorts.length === 0 ? (
              <p className="text-gray-400 text-xs">No matching ports</p>
            ) : (
              <ul className="list-disc pl-5">
                {filteredPorts.map((p) => (
                  <li key={`${p.port}-${p.protocol}`}>{p.port} → {p.target_port} ({p.protocol})</li>
                ))}
              </ul>
            )}
          </div>
          <div>
            <p className="text-gray-500 mb-1">Selector</p>
            {filteredSelector.length === 0 ? (
              <p className="text-gray-400 text-xs">No matching selector entries</p>
            ) : (
              <pre className="bg-gray-50 p-2 rounded text-xs overflow-x-auto border border-gray-100">
                {JSON.stringify(Object.fromEntries(filteredSelector), null, 2)}
              </pre>
            )}
          </div>
        </div>
      ) : null}
    </ModalShell>
  );
}

export function ServiceCreateModal({
  defaultNamespace,
  onClose,
  onSave,
  saving,
}: {
  defaultNamespace: string;
  onClose: () => void;
  onSave: (vars: {
    namespace: string;
    name: string;
    port: number;
    targetPort: number | string;
    selector: Record<string, string>;
    serviceType: string;
  }) => void;
  saving?: boolean;
}) {
  const [namespace, setNamespace] = useState(defaultNamespace || "default");
  const [name, setName] = useState("");
  const [port, setPort] = useState(80);
  const [targetPort, setTargetPort] = useState("80");
  const [serviceType, setServiceType] = useState("ClusterIP");
  const [selectorText, setSelectorText] = useState("app=my-app");

  return (
    <ModalShell title="Create Service" onClose={onClose} wide>
      <div className="space-y-3">
        <div>
          <label className="block text-sm font-medium mb-1">Namespace</label>
          <input className="w-full border rounded-lg px-3 py-2 text-sm" value={namespace} onChange={(e) => setNamespace(e.target.value)} />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Name</label>
          <input className="w-full border rounded-lg px-3 py-2 text-sm" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium mb-1">Port</label>
            <input type="number" className="w-full border rounded-lg px-3 py-2 text-sm" value={port} onChange={(e) => setPort(Number(e.target.value))} />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Target Port</label>
            <input className="w-full border rounded-lg px-3 py-2 text-sm" value={targetPort} onChange={(e) => setTargetPort(e.target.value)} />
          </div>
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Type</label>
          <select className="w-full border rounded-lg px-3 py-2 text-sm" value={serviceType} onChange={(e) => setServiceType(e.target.value)}>
            <option value="ClusterIP">ClusterIP</option>
            <option value="NodePort">NodePort</option>
            <option value="LoadBalancer">LoadBalancer</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Selector (key=value, comma-separated)</label>
          <input className="w-full border rounded-lg px-3 py-2 text-sm font-mono" value={selectorText} onChange={(e) => setSelectorText(e.target.value)} />
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-4">
        <button type="button" onClick={onClose} className="px-4 py-2 border rounded-lg text-sm">Cancel</button>
        <button
          type="button"
          disabled={saving || !name.trim()}
          onClick={() => {
            const selector: Record<string, string> = {};
            selectorText.split(",").forEach((part) => {
              const [k, v] = part.split("=").map((s) => s.trim());
              if (k && v) selector[k] = v;
            });
            onSave({ namespace, name: name.trim(), port, targetPort, selector, serviceType });
          }}
          className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm disabled:opacity-50"
        >
          {saving ? "Creating..." : "Create"}
        </button>
      </div>
    </ModalShell>
  );
}

// ── ConfigMap modals ─────────────────────────────────────────────────

export function ConfigMapViewModal({
  clusterId,
  namespace,
  name,
  onClose,
}: {
  clusterId: string;
  namespace: string;
  name: string;
  onClose: () => void;
}) {
  const { data, isLoading, isFetching } = useConfigMapDetail(clusterId, namespace, name);
  const cm = data as ConfigMapDetail | undefined;

  return (
    <ModalShell title={`ConfigMap: ${name}`} subtitle={`Namespace: ${namespace}`} onClose={onClose} wide>
      {isLoading && !cm ? (
        <ModalLoadingState />
      ) : cm ? (
        <>
          {isFetching ? <span className="text-att-500 text-xs block mb-2">Refreshing…</span> : null}
          <DetailSourceBadge source={cm.detail_source} lastSync={cm._last_sync} />
          {cm.detail_source === "unavailable" && cm.data_unavailable_reason ? (
            <p className="text-xs text-amber-600 mb-3">{cm.data_unavailable_reason}</p>
          ) : null}
          <KeyValueEditor data={cm.data || {}} readOnly searchPlaceholder="Search config keys..." />
        </>
      ) : null}
    </ModalShell>
  );
}

export function ConfigMapEditModal({
  clusterId,
  namespace,
  name,
  onClose,
  onSave,
  saving,
}: {
  clusterId: string;
  namespace: string;
  name: string;
  onClose: () => void;
  onSave: (data: Record<string, string>) => void;
  saving?: boolean;
}) {
  const { data, isLoading } = useConfigMapDetail(clusterId, namespace, name);
  const [kvText, setKvText] = useState("");

  useEffect(() => {
    if (data?.data) setKvText(kvToLines(data.data));
  }, [data]);

  return (
    <ModalShell title={`Edit ConfigMap: ${name}`} onClose={onClose} wide>
      {isLoading ? (
        <ModalLoadingState />
      ) : (
        <>
          <textarea
            className="w-full border rounded-lg px-3 py-2 font-mono text-sm min-h-[200px] focus:outline-none focus:ring-2 focus:ring-att-400"
            value={kvText}
            onChange={(e) => setKvText(e.target.value)}
          />
          <div className="flex justify-end gap-2 mt-4">
            <button type="button" onClick={onClose} className="px-4 py-2 border rounded-lg text-sm">Cancel</button>
            <button
              type="button"
              disabled={saving}
              onClick={() => onSave(kvFromLines(kvText))}
              className="px-4 py-2 bg-att-500 text-white rounded-lg text-sm disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </>
      )}
    </ModalShell>
  );
}

export function ConfigMapCreateModal({
  defaultNamespace,
  onClose,
  onSave,
  saving,
}: {
  defaultNamespace: string;
  onClose: () => void;
  onSave: (vars: { namespace: string; name: string; data: Record<string, string> }) => void;
  saving?: boolean;
}) {
  const [namespace, setNamespace] = useState(defaultNamespace || "default");
  const [name, setName] = useState("");
  const [kvText, setKvText] = useState("");

  return (
    <ModalShell title="Create ConfigMap" onClose={onClose} wide>
      <div className="space-y-3">
        <div>
          <label className="block text-sm font-medium mb-1">Namespace</label>
          <input className="w-full border rounded-lg px-3 py-2 text-sm" value={namespace} onChange={(e) => setNamespace(e.target.value)} />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Name</label>
          <input className="w-full border rounded-lg px-3 py-2 text-sm" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Data (key=value per line)</label>
          <textarea className="w-full border rounded-lg px-3 py-2 font-mono text-sm min-h-[120px]" value={kvText} onChange={(e) => setKvText(e.target.value)} />
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-4">
        <button type="button" onClick={onClose} className="px-4 py-2 border rounded-lg text-sm">Cancel</button>
        <button
          type="button"
          disabled={saving || !name.trim()}
          onClick={() => onSave({ namespace, name: name.trim(), data: kvFromLines(kvText) })}
          className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm disabled:opacity-50"
        >
          {saving ? "Creating..." : "Create"}
        </button>
      </div>
    </ModalShell>
  );
}

// ── Ingress modals ───────────────────────────────────────────────────

export function IngressViewModal({
  clusterId,
  namespace,
  name,
  onClose,
}: {
  clusterId: string;
  namespace: string;
  name: string;
  onClose: () => void;
}) {
  const { data, isLoading, isFetching } = useIngressDetail(clusterId, namespace, name, true);
  const ing = data as IngressDetail | undefined;
  const [search, setSearch] = useState("");
  const rules = ing?.rules || [];
  const filteredRules = filterListItems(rules, search, (rule, q) => JSON.stringify(rule).toLowerCase().includes(q));
  const linkedServices = ing?.linked_services || [];
  const filteredServices = filterListItems(linkedServices, search, (svc, q) => svc.toLowerCase().includes(q));

  return (
    <ModalShell title={`Ingress: ${name}`} subtitle={`Namespace: ${namespace}`} onClose={onClose} wide>
      {isLoading && !ing ? (
        <ModalLoadingState />
      ) : ing ? (
        <div className="space-y-3 text-sm">
          {isFetching ? <span className="text-att-500 text-xs">Refreshing…</span> : null}
          <DetailSourceBadge source={ing.detail_source} lastSync={ing._last_sync} />
          <ModalSearchBar
            value={search}
            onChange={setSearch}
            placeholder="Search rules, services, hosts..."
            resultCount={filteredRules.length + filteredServices.length}
            totalCount={rules.length + linkedServices.length}
          />
          <p><span className="text-gray-500">Class:</span> {ing.ingress_class || "—"}</p>
          <p><span className="text-gray-500">Address:</span> {ing.address || "—"}</p>
          <div>
            <p className="text-gray-500 mb-1">Rules ({filteredRules.length})</p>
            {filteredRules.length === 0 ? (
              <p className="text-gray-400 text-xs">No matching rules</p>
            ) : (
              <pre className="bg-gray-50 p-2 rounded text-xs overflow-x-auto border border-gray-100 max-h-48 overflow-y-auto">
                {JSON.stringify(filteredRules, null, 2)}
              </pre>
            )}
          </div>
          <div>
            <p className="text-gray-500 mb-1">Linked Services</p>
            <p>{filteredServices.join(", ") || "—"}</p>
          </div>
        </div>
      ) : null}
    </ModalShell>
  );
}

export function DeleteConfirmModal({
  title,
  message,
  onClose,
  onConfirm,
  confirming,
}: {
  title: string;
  message: string;
  onClose: () => void;
  onConfirm: () => void;
  confirming?: boolean;
}) {
  return (
    <ModalShell title={title} onClose={onClose}>
      <p className="text-sm text-gray-600 mb-4">{message}</p>
      <div className="flex justify-end gap-2">
        <button type="button" onClick={onClose} className="px-4 py-2 border rounded-lg text-sm">Cancel</button>
        <button
          type="button"
          disabled={confirming}
          onClick={onConfirm}
          className="px-4 py-2 bg-red-600 text-white rounded-lg text-sm disabled:opacity-50"
        >
          {confirming ? "Deleting..." : "Delete"}
        </button>
      </div>
    </ModalShell>
  );
}
