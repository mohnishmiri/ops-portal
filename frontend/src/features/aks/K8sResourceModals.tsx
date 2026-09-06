/**
 * Modals for AKS extended K8s resources — view, edit, create, delete confirm.
 */

import React, { useEffect, useState } from "react";
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

export function ModalShell({
  title,
  onClose,
  children,
  wide,
}: {
  title: string;
  onClose: () => void;
  children: React.ReactNode;
  wide?: boolean;
}) {
  // Only close on a clean click (mousedown+mouseup both on the backdrop).
  // This prevents closing when the user drags a textarea resize handle
  // outside the modal boundary.
  const backdropRef = React.useRef<HTMLDivElement>(null);
  const mouseDownOnBackdrop = React.useRef(false);

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4"
      onMouseDown={(e) => { mouseDownOnBackdrop.current = e.target === backdropRef.current; }}
      onMouseUp={(e) => {
        if (mouseDownOnBackdrop.current && e.target === backdropRef.current) onClose();
        mouseDownOnBackdrop.current = false;
      }}
    >
      <div
        className={`bg-white rounded-lg shadow-xl w-full ${wide ? "max-w-3xl" : "max-w-lg"} max-h-[90vh] flex flex-col resize overflow-hidden`}
        onClick={(e) => e.stopPropagation()}
        onMouseDown={(e) => e.stopPropagation()}
        style={{ minWidth: 360, minHeight: 200 }}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b shrink-0">
          <h3 className="text-lg font-semibold">{title}</h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
        </div>
        <div className="px-6 py-4 overflow-y-auto flex-1">{children}</div>
      </div>
    </div>
  );
}

function KeyValueEditor({
  data,
  onChange,
  readOnly,
}: {
  data: Record<string, string>;
  onChange?: (d: Record<string, string>) => void;
  readOnly?: boolean;
}) {
  const entries = Object.entries(data);
  if (entries.length === 0) {
    return <p className="text-sm text-gray-500">No data keys</p>;
  }
  return (
    <div className="space-y-2 max-h-96 overflow-y-auto">
      {entries.map(([key, value]) => (
        <div key={key} className="grid grid-cols-3 gap-2 items-start">
          <span className="text-sm font-mono text-gray-700 break-all col-span-1">{key}</span>
          {readOnly ? (
            <span className="text-sm font-mono text-gray-600 break-all col-span-2">{value}</span>
          ) : (
            <textarea
              className="col-span-2 border rounded px-2 py-1 text-sm font-mono min-h-[2.5rem]"
              value={value}
              onChange={(e) => onChange?.({ ...data, [key]: e.target.value })}
            />
          )}
        </div>
      ))}
    </div>
  );
}

function kvFromLines(text: string): Record<string, string> {
  // Try JSON parse first (handles multi-line values correctly)
  try {
    const parsed = JSON.parse(text);
    if (typeof parsed === "object" && parsed !== null && !Array.isArray(parsed)) {
      const out: Record<string, string> = {};
      for (const [k, v] of Object.entries(parsed)) {
        out[k] = String(v);
      }
      return out;
    }
  } catch {
    // Not JSON — fall through to legacy line-based parsing
  }
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
  // Use JSON for data with multi-line values; simple key=value otherwise
  const hasMultiLine = Object.values(data).some((v) => v.includes("\n"));
  if (hasMultiLine) {
    return JSON.stringify(data, null, 2);
  }
  return Object.entries(data).map(([k, v]) => `${k}=${v}`).join("\n");
}

// ── Secret modals ────────────────────────────────────────────────────

export function SecretViewModal({
  clusterId,
  namespace,
  name,
  canWrite,
  onClose,
}: {
  clusterId: string;
  namespace: string;
  name: string;
  canWrite: boolean;
  onClose: () => void;
}) {
  const { data, isLoading } = useSecretDetail(clusterId, namespace, name, true, true);
  const [search, setSearch] = useState("");

  const entries = Object.entries((data as SecretDetail)?.data || {});
  const filtered = search.trim()
    ? entries.filter(([k, v]) => k.toLowerCase().includes(search.toLowerCase()) || v.toLowerCase().includes(search.toLowerCase()))
    : entries;

  return (
    <ModalShell title={`Secret: ${name}`} onClose={onClose} wide>
      {isLoading ? (
        <p className="text-sm text-gray-500">Loading...</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-4 mb-4 pb-3 border-b">
            <span className="text-sm text-gray-600">Namespace: <strong className="text-gray-800">{namespace}</strong></span>
            <span className="text-sm text-gray-600">Type: <strong className="text-gray-800">{(data as SecretDetail)?.type}</strong></span>
            <span className="text-sm text-gray-600">Keys: <strong className="text-gray-800">{entries.length}</strong></span>
          </div>
          <div className="mb-3">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search keys or values..."
              className="w-full border rounded-lg px-3 py-2 text-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100"
            />
          </div>
          {filtered.length === 0 ? (
            <p className="text-sm text-gray-500 py-4 text-center">No matching keys found</p>
          ) : (
            <div className="max-h-[400px] overflow-y-auto border rounded-lg">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="text-left px-3 py-2 font-medium text-gray-600 w-1/3">Key</th>
                    <th className="text-left px-3 py-2 font-medium text-gray-600">Value</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {filtered.map(([key, value]) => (
                    <tr key={key} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-mono text-xs text-gray-700 break-all align-top">{key}</td>
                      <td className="px-3 py-2 font-mono text-xs text-gray-600 break-all">{value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
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
        <p className="text-sm text-gray-500">Loading...</p>
      ) : (
        <>
          <p className="text-sm text-gray-500 mb-2">One key=value pair per line</p>
          <textarea
            className="w-full border rounded px-3 py-2 font-mono text-sm min-h-[200px]"
            value={kvText}
            onChange={(e) => setKvText(e.target.value)}
          />
          <div className="flex justify-end gap-2 mt-4">
            <button type="button" onClick={onClose} className="px-4 py-2 border rounded-lg text-sm">Cancel</button>
            <button
              type="button"
              disabled={saving}
              onClick={() => onSave(kvFromLines(kvText))}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm disabled:opacity-50"
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
  namespaces,
  onClose,
  onSave,
  saving,
}: {
  defaultNamespace: string;
  namespaces?: string[];
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
          {namespaces && namespaces.length > 0 ? (
            <select className="w-full border rounded px-3 py-2 text-sm" value={namespace} onChange={(e) => setNamespace(e.target.value)}>
              {namespaces.map((ns) => <option key={ns} value={ns}>{ns}</option>)}
            </select>
          ) : (
            <input className="w-full border rounded px-3 py-2 text-sm" value={namespace} onChange={(e) => setNamespace(e.target.value)} />
          )}
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Name</label>
          <input className="w-full border rounded px-3 py-2 text-sm" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Type</label>
          <input className="w-full border rounded px-3 py-2 text-sm" value={secretType} onChange={(e) => setSecretType(e.target.value)} />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Data (key=value per line)</label>
          <textarea className="w-full border rounded px-3 py-2 font-mono text-sm min-h-[120px]" value={kvText} onChange={(e) => setKvText(e.target.value)} />
        </div>
      </div>
      <div className="flex justify-end gap-2 mt-4">
        <button type="button" onClick={onClose} className="px-4 py-2 border rounded-lg text-sm">Cancel</button>
        <button
          type="button"
          disabled={saving || !name.trim()}
          onClick={() => onSave({ namespace, name: name.trim(), data: kvFromLines(kvText), secretType })}
          className="px-4 py-2 bg-green-600 text-white rounded-lg text-sm disabled:opacity-50"
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
  const { data, isLoading } = useServiceDetail(clusterId, namespace, name, true);
  const svc = data as ServiceDetail | undefined;

  return (
    <ModalShell title={`Service: ${name}`} onClose={onClose} wide>
      {isLoading || !svc ? (
        <p className="text-sm text-gray-500">Loading...</p>
      ) : (
        <div className="space-y-3 text-sm">
          <p><span className="text-gray-500">Namespace:</span> {svc.namespace}</p>
          <p><span className="text-gray-500">Type:</span> {svc.type}</p>
          <p><span className="text-gray-500">Cluster IP:</span> {svc.cluster_ip || "—"}</p>
          <div>
            <p className="text-gray-500 mb-1">Ports</p>
            <ul className="list-disc pl-5">
              {(svc.ports || []).map((p) => (
                <li key={`${p.port}-${p.protocol}`}>{p.port} → {p.target_port} ({p.protocol})</li>
              ))}
            </ul>
          </div>
          <div>
            <p className="text-gray-500 mb-1">Selector</p>
            <pre className="bg-gray-50 p-2 rounded text-xs overflow-x-auto">{JSON.stringify(svc.selector || {}, null, 2)}</pre>
          </div>
        </div>
      )}
    </ModalShell>
  );
}

export function ServiceCreateModal({
  defaultNamespace,
  namespaces,
  onClose,
  onSave,
  saving,
}: {
  defaultNamespace: string;
  namespaces?: string[];
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
          {namespaces && namespaces.length > 0 ? (
            <select className="w-full border rounded px-3 py-2 text-sm" value={namespace} onChange={(e) => setNamespace(e.target.value)}>
              {namespaces.map((ns) => <option key={ns} value={ns}>{ns}</option>)}
            </select>
          ) : (
            <input className="w-full border rounded px-3 py-2 text-sm" value={namespace} onChange={(e) => setNamespace(e.target.value)} />
          )}
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Name</label>
          <input className="w-full border rounded px-3 py-2 text-sm" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium mb-1">Port</label>
            <input type="number" className="w-full border rounded px-3 py-2 text-sm" value={port} onChange={(e) => setPort(Number(e.target.value))} />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">Target Port</label>
            <input className="w-full border rounded px-3 py-2 text-sm" value={targetPort} onChange={(e) => setTargetPort(e.target.value)} />
          </div>
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Type</label>
          <select className="w-full border rounded px-3 py-2 text-sm" value={serviceType} onChange={(e) => setServiceType(e.target.value)}>
            <option value="ClusterIP">ClusterIP</option>
            <option value="NodePort">NodePort</option>
            <option value="LoadBalancer">LoadBalancer</option>
          </select>
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Selector (key=value, comma-separated)</label>
          <input className="w-full border rounded px-3 py-2 text-sm font-mono" value={selectorText} onChange={(e) => setSelectorText(e.target.value)} />
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

export function ServiceEditModal({
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
  const { data, isLoading } = useServiceDetail(clusterId, namespace, name, true);
  const svc = data as ServiceDetail | undefined;

  const [port, setPort] = useState(80);
  const [targetPort, setTargetPort] = useState("80");
  const [serviceType, setServiceType] = useState("ClusterIP");
  const [selectorText, setSelectorText] = useState("");

  useEffect(() => {
    if (svc) {
      const firstPort = svc.ports?.[0];
      setPort(firstPort?.port || 80);
      setTargetPort(String(firstPort?.target_port || firstPort?.port || 80));
      setServiceType(svc.type || "ClusterIP");
      setSelectorText(
        Object.entries(svc.selector || {}).map(([k, v]) => `${k}=${v}`).join(", ")
      );
    }
  }, [svc]);

  return (
    <ModalShell title={`Edit Service: ${name}`} onClose={onClose} wide>
      {isLoading || !svc ? (
        <p className="text-sm text-gray-500">Loading...</p>
      ) : (
        <>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium mb-1">Port</label>
                <input type="number" className="w-full border rounded px-3 py-2 text-sm" value={port} onChange={(e) => setPort(Number(e.target.value))} />
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Target Port</label>
                <input className="w-full border rounded px-3 py-2 text-sm" value={targetPort} onChange={(e) => setTargetPort(e.target.value)} />
              </div>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Type</label>
              <select className="w-full border rounded px-3 py-2 text-sm" value={serviceType} onChange={(e) => setServiceType(e.target.value)}>
                <option value="ClusterIP">ClusterIP</option>
                <option value="NodePort">NodePort</option>
                <option value="LoadBalancer">LoadBalancer</option>
              </select>
            </div>
            <div>
              <label className="block text-sm font-medium mb-1">Selector (key=value, comma-separated)</label>
              <input className="w-full border rounded px-3 py-2 text-sm font-mono" value={selectorText} onChange={(e) => setSelectorText(e.target.value)} />
            </div>
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <button type="button" onClick={onClose} className="px-4 py-2 border rounded-lg text-sm">Cancel</button>
            <button
              type="button"
              disabled={saving}
              onClick={() => {
                const selector: Record<string, string> = {};
                selectorText.split(",").forEach((part) => {
                  const [k, v] = part.split("=").map((s) => s.trim());
                  if (k && v) selector[k] = v;
                });
                onSave({ namespace, name, port, targetPort, selector, serviceType });
              }}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </>
      )}
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
  const { data, isLoading } = useConfigMapDetail(clusterId, namespace, name);
  const cm = data as ConfigMapDetail | undefined;
  const [search, setSearch] = useState("");

  const entries = Object.entries(cm?.data || {});
  const filtered = search.trim()
    ? entries.filter(([k, v]) => k.toLowerCase().includes(search.toLowerCase()) || v.toLowerCase().includes(search.toLowerCase()))
    : entries;

  return (
    <ModalShell title={`ConfigMap: ${name}`} onClose={onClose} wide>
      {isLoading || !cm ? (
        <p className="text-sm text-gray-500">Loading...</p>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-4 mb-4 pb-3 border-b">
            <span className="text-sm text-gray-600">Namespace: <strong className="text-gray-800">{cm.namespace}</strong></span>
            <span className="text-sm text-gray-600">Keys: <strong className="text-gray-800">{entries.length}</strong></span>
          </div>
          <div className="mb-3">
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search keys or values..."
              className="w-full border rounded-lg px-3 py-2 text-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100"
            />
          </div>
          {filtered.length === 0 ? (
            <p className="text-sm text-gray-500 py-4 text-center">No matching keys found</p>
          ) : (
            <div className="max-h-[400px] overflow-y-auto border rounded-lg">
              <table className="w-full text-sm">
                <thead className="bg-gray-50 sticky top-0">
                  <tr>
                    <th className="text-left px-3 py-2 font-medium text-gray-600 w-1/3">Key</th>
                    <th className="text-left px-3 py-2 font-medium text-gray-600">Value</th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {filtered.map(([key, value]) => (
                    <tr key={key} className="hover:bg-gray-50">
                      <td className="px-3 py-2 font-mono text-xs text-gray-700 break-all align-top">{key}</td>
                      <td className="px-3 py-2 font-mono text-xs text-gray-600 break-all whitespace-pre-wrap">{value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
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
  const [entries, setEntries] = useState<Array<{ key: string; value: string }>>([]);

  useEffect(() => {
    if (data?.data) {
      setEntries(Object.entries(data.data).map(([key, value]) => ({ key, value })));
    }
  }, [data]);

  const updateValue = (idx: number, value: string) => {
    setEntries((prev) => prev.map((e, i) => (i === idx ? { ...e, value } : e)));
  };

  const handleSave = () => {
    const result: Record<string, string> = {};
    for (const { key, value } of entries) {
      if (key.trim()) result[key.trim()] = value;
    }
    onSave(result);
  };

  return (
    <ModalShell title={`Edit ConfigMap: ${name}`} onClose={onClose} wide>
      {isLoading ? (
        <p className="text-sm text-gray-500">Loading...</p>
      ) : (
        <>
          <div className="space-y-4 max-h-[60vh] overflow-y-auto">
            {entries.map((entry, idx) => (
              <div key={entry.key} className="border rounded-lg p-3">
                <label className="block text-xs font-semibold text-gray-700 mb-1 font-mono">{entry.key}</label>
                <textarea
                  className="w-full border rounded px-3 py-2 font-mono text-sm min-h-[120px] whitespace-pre"
                  value={entry.value}
                  onChange={(e) => updateValue(idx, e.target.value)}
                />
              </div>
            ))}
            {entries.length === 0 && (
              <p className="text-sm text-gray-500">No data keys in this ConfigMap.</p>
            )}
          </div>
          <div className="flex justify-end gap-2 mt-4">
            <button type="button" onClick={onClose} className="px-4 py-2 border rounded-lg text-sm">Cancel</button>
            <button
              type="button"
              disabled={saving}
              onClick={handleSave}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm disabled:opacity-50"
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
  namespaces,
  onClose,
  onSave,
  saving,
}: {
  defaultNamespace: string;
  namespaces?: string[];
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
          {namespaces && namespaces.length > 0 ? (
            <select className="w-full border rounded px-3 py-2 text-sm" value={namespace} onChange={(e) => setNamespace(e.target.value)}>
              {namespaces.map((ns) => <option key={ns} value={ns}>{ns}</option>)}
            </select>
          ) : (
            <input className="w-full border rounded px-3 py-2 text-sm" value={namespace} onChange={(e) => setNamespace(e.target.value)} />
          )}
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Name</label>
          <input className="w-full border rounded px-3 py-2 text-sm" value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div>
          <label className="block text-sm font-medium mb-1">Data (key=value per line)</label>
          <textarea className="w-full border rounded px-3 py-2 font-mono text-sm min-h-[120px]" value={kvText} onChange={(e) => setKvText(e.target.value)} />
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
  const { data, isLoading } = useIngressDetail(clusterId, namespace, name, true);
  const ing = data as IngressDetail | undefined;

  return (
    <ModalShell title={`Ingress: ${name}`} onClose={onClose} wide>
      {isLoading || !ing ? (
        <p className="text-sm text-gray-500">Loading...</p>
      ) : (
        <div className="space-y-3 text-sm">
          <p><span className="text-gray-500">Namespace:</span> {ing.namespace}</p>
          <p><span className="text-gray-500">Class:</span> {ing.ingress_class || "—"}</p>
          <p><span className="text-gray-500">Address:</span> {ing.address || "—"}</p>
          <div>
            <p className="text-gray-500 mb-1">Rules</p>
            <pre className="bg-gray-50 p-2 rounded text-xs overflow-x-auto">{JSON.stringify(ing.rules || [], null, 2)}</pre>
          </div>
          <div>
            <p className="text-gray-500 mb-1">Linked Services</p>
            <p>{(ing.linked_services || []).join(", ") || "—"}</p>
          </div>
        </div>
      )}
    </ModalShell>
  );
}

export function IngressEditModal({
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
  onSave: (vars: {
    namespace: string;
    name: string;
    rules: Array<{ host?: string; paths: Array<{ path: string; path_type: string; service_name: string; service_port: number }> }>;
    tls?: Array<{ hosts?: string[]; secret_name: string }> | null;
    ingressClass?: string | null;
  }) => void;
  saving?: boolean;
}) {
  const { data, isLoading } = useIngressDetail(clusterId, namespace, name, true);
  const ing = data as IngressDetail | undefined;

  const [rulesJson, setRulesJson] = useState("");
  const [ingressClass, setIngressClass] = useState("");
  const [tlsJson, setTlsJson] = useState("");
  const [jsonError, setJsonError] = useState("");

  useEffect(() => {
    if (ing) {
      // Convert flat rules to nested format for editing
      const grouped: Record<string, Array<{ path: string; path_type: string; service_name: string; service_port: number }>> = {};
      for (const r of ing.rules || []) {
        const host = r.host || "";
        if (!grouped[host]) grouped[host] = [];
        grouped[host].push({
          path: r.path || "/",
          path_type: r.path_type || "Prefix",
          service_name: r.service_name || "",
          service_port: r.service_port || 80,
        });
      }
      const rulesArr = Object.entries(grouped).map(([host, paths]) => ({
        host: host || undefined,
        paths,
      }));
      setRulesJson(JSON.stringify(rulesArr, null, 2));
      setIngressClass(ing.ingress_class || "");
      if (ing.tls && ing.tls.length > 0) {
        setTlsJson(JSON.stringify(ing.tls, null, 2));
      }
    }
  }, [ing]);

  const handleSave = () => {
    try {
      const rules = JSON.parse(rulesJson);
      const tls = tlsJson.trim() ? JSON.parse(tlsJson) : null;
      setJsonError("");
      onSave({ namespace, name, rules, tls, ingressClass: ingressClass || null });
    } catch {
      setJsonError("Invalid JSON in rules or TLS");
    }
  };

  return (
    <ModalShell title={`Edit Ingress: ${name}`} onClose={onClose} wide>
      {isLoading || !ing ? (
        <p className="text-sm text-gray-500">Loading...</p>
      ) : (
        <div className="space-y-4">
          <div>
            <label className="text-xs text-gray-500 block mb-1">Ingress Class</label>
            <input
              value={ingressClass}
              onChange={(e) => setIngressClass(e.target.value)}
              className="w-full border rounded px-2 py-1 text-sm"
              placeholder="nginx"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">Rules (JSON)</label>
            <textarea
              value={rulesJson}
              onChange={(e) => setRulesJson(e.target.value)}
              className="w-full border rounded px-2 py-1 text-sm font-mono h-48"
            />
          </div>
          <div>
            <label className="text-xs text-gray-500 block mb-1">TLS (JSON, optional)</label>
            <textarea
              value={tlsJson}
              onChange={(e) => setTlsJson(e.target.value)}
              className="w-full border rounded px-2 py-1 text-sm font-mono h-24"
              placeholder='[{"hosts": ["example.com"], "secret_name": "tls-secret"}]'
            />
          </div>
          {jsonError && <p className="text-xs text-red-500">{jsonError}</p>}
          <div className="flex justify-end gap-2 mt-4">
            <button type="button" onClick={onClose} className="px-4 py-2 border rounded-lg text-sm">Cancel</button>
            <button
              type="button"
              disabled={saving}
              onClick={handleSave}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm disabled:opacity-50"
            >
              {saving ? "Saving..." : "Save"}
            </button>
          </div>
        </div>
      )}
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
      {/* whitespace-pre-line so callers can separate the question from status
          and consequence details with blank lines. */}
      <p className="text-sm text-gray-600 mb-4 whitespace-pre-line">{message}</p>
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
