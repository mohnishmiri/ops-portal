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

function ModalShell({
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
  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div
        className={`bg-white rounded-lg shadow-xl w-full ${wide ? "max-w-2xl" : "max-w-lg"} max-h-[90vh] overflow-y-auto`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b">
          <h3 className="text-lg font-semibold">{title}</h3>
          <button type="button" onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
        </div>
        <div className="px-6 py-4">{children}</div>
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
  const [reveal, setReveal] = useState(false);
  const { data, isLoading } = useSecretDetail(clusterId, namespace, name, reveal, true);

  return (
    <ModalShell title={`Secret: ${name}`} onClose={onClose} wide>
      {isLoading ? (
        <p className="text-sm text-gray-500">Loading...</p>
      ) : (
        <>
          <div className="flex flex-wrap gap-2 mb-4 text-sm text-gray-600">
            <span>Namespace: <strong>{namespace}</strong></span>
            <span>Type: <strong>{(data as SecretDetail)?.type}</strong></span>
          </div>
          {canWrite && (
            <label className="flex items-center gap-2 mb-3 text-sm">
              <input type="checkbox" checked={reveal} onChange={(e) => setReveal(e.target.checked)} />
              Reveal secret values
            </label>
          )}
          <KeyValueEditor data={(data as SecretDetail)?.data || {}} readOnly />
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
          <input className="w-full border rounded px-3 py-2 text-sm" value={namespace} onChange={(e) => setNamespace(e.target.value)} />
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
          <input className="w-full border rounded px-3 py-2 text-sm" value={namespace} onChange={(e) => setNamespace(e.target.value)} />
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

  return (
    <ModalShell title={`ConfigMap: ${name}`} onClose={onClose} wide>
      {isLoading || !cm ? (
        <p className="text-sm text-gray-500">Loading...</p>
      ) : (
        <>
          <p className="text-sm text-gray-600 mb-3">Namespace: <strong>{cm.namespace}</strong></p>
          <KeyValueEditor data={cm.data || {}} readOnly />
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
  const [kvText, setKvText] = useState("");

  useEffect(() => {
    if (data?.data) setKvText(kvToLines(data.data));
  }, [data]);

  return (
    <ModalShell title={`Edit ConfigMap: ${name}`} onClose={onClose} wide>
      {isLoading ? (
        <p className="text-sm text-gray-500">Loading...</p>
      ) : (
        <>
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
          <input className="w-full border rounded px-3 py-2 text-sm" value={namespace} onChange={(e) => setNamespace(e.target.value)} />
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
