/**
 * Extended AKS resource tabs — Secrets, Services, ConfigMaps, Ingress, Helm, Audit History.
 */

import React, { useMemo, useState } from "react";
import { gridStyles } from "../../components/gridStyles";
import {
  useCachedSecrets,
  useCachedServices,
  useCachedConfigMaps,
  useCachedIngress,
  useHelmReleases,
  useAksAuditHistory,
  useSyncSecrets,
  useSyncServices,
  useSyncConfigMaps,
  useSyncIngress,
  useDeleteSecret,
  useDeleteService,
  useDeleteConfigMap,
  useDeleteIngress,
  useUninstallHelmRelease,
  AKSCluster,
} from "../../services/aksApi";
import { LiveStatusBadge, LiveWatchStatus } from "../../hooks/useAksLiveWatch";

const PAGE_SIZE = 15;

function SimplePager({ page, totalPages, onPage }: { page: number; totalPages: number; onPage: (p: number) => void }) {
  return (
    <div className={gridStyles.pager}>
      <button type="button" className={gridStyles.pagerButton} disabled={page <= 1} onClick={() => onPage(page - 1)}>Prev</button>
      <span className="text-sm text-gray-600">Page {page} of {totalPages}</span>
      <button type="button" className={gridStyles.pagerButton} disabled={page >= totalPages} onClick={() => onPage(page + 1)}>Next</button>
    </div>
  );
}

function NamespaceSelect({
  namespaces,
  value,
  onChange,
}: {
  namespaces: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={gridStyles.toolbarInput}
    >
      <option value="">All Namespaces</option>
      {namespaces.map((ns) => (
        <option key={ns} value={ns}>{ns}</option>
      ))}
    </select>
  );
}

function ResourceGridShell({
  title,
  liveStatus,
  namespaceSelect,
  search,
  onSearch,
  onSync,
  syncing,
  children,
  page,
  totalPages,
  onPage,
}: {
  title: string;
  liveStatus?: LiveWatchStatus;
  namespaceSelect?: React.ReactNode;
  search: string;
  onSearch: (v: string) => void;
  onSync?: () => void;
  syncing?: boolean;
  children: React.ReactNode;
  page: number;
  totalPages: number;
  onPage: (p: number) => void;
}) {
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <h2 className="text-xl font-semibold text-gray-800">{title}</h2>
          {liveStatus && <LiveStatusBadge status={liveStatus} />}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {namespaceSelect}
          <input
            type="search"
            placeholder="Search…"
            value={search}
            onChange={(e) => onSearch(e.target.value)}
            className={gridStyles.toolbarInput}
          />
          {onSync && (
            <button
              type="button"
              onClick={onSync}
              disabled={syncing}
              className="px-3 py-2 text-sm bg-att-600 text-white rounded-lg hover:bg-att-700 disabled:opacity-50"
            >
              {syncing ? "Syncing…" : "Sync"}
            </button>
          )}
        </div>
      </div>
      <div className={gridStyles.shell}>{children}</div>
      <SimplePager page={page} totalPages={totalPages} onPage={onPage} />
    </div>
  );
}

type TabProps = {
  cluster: AKSCluster;
  namespace: string;
  namespaces: string[];
  onNamespaceChange: (ns: string) => void;
  liveStatus: LiveWatchStatus;
  canWrite: boolean;
  showToast: (msg: string, type?: "success" | "error") => void;
};

export const SecretsTab: React.FC<TabProps> = ({
  cluster, namespace, namespaces, onNamespaceChange, liveStatus, canWrite, showToast,
}) => {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const ns = namespace || namespaces[0] || "default";
  const { data, isLoading } = useCachedSecrets(cluster.id, ns);
  const syncMut = useSyncSecrets();
  const deleteMut = useDeleteSecret();
  const items = data?.secrets || [];
  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return q ? items.filter((s) => s.name.toLowerCase().includes(q)) : items;
  }, [items, search]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <ResourceGridShell
      title="Secrets"
      liveStatus={liveStatus}
      namespaceSelect={<NamespaceSelect namespaces={namespaces} value={namespace} onChange={onNamespaceChange} />}
      search={search}
      onSearch={(v) => { setSearch(v); setPage(1); }}
      onSync={() => syncMut.mutate({ clusterId: cluster.id, namespace: ns }, {
        onSuccess: () => showToast("Secrets synced"),
        onError: () => showToast("Sync failed", "error"),
      })}
      syncing={syncMut.isPending}
      page={page}
      totalPages={totalPages}
      onPage={setPage}
    >
      <table className={gridStyles.table}>
        <thead><tr>
          <th className={gridStyles.headerCell}>Name</th>
          <th className={gridStyles.headerCell}>Namespace</th>
          <th className={gridStyles.headerCell}>Type</th>
          <th className={gridStyles.headerCell}>Keys</th>
          {canWrite && <th className={gridStyles.headerCellCenter}>Actions</th>}
        </tr></thead>
        <tbody>
          {isLoading ? (
            <tr><td colSpan={5} className="py-6 text-center text-sm text-gray-400">Loading…</td></tr>
          ) : paged.length === 0 ? (
            <tr><td colSpan={5} className="py-6 text-center text-sm text-gray-400">No secrets found</td></tr>
          ) : paged.map((s) => (
            <tr key={`${s.namespace}/${s.name}`} className={gridStyles.row}>
              <td className="font-medium">{s.name}</td>
              <td>{s.namespace}</td>
              <td>{s.type}</td>
              <td>{s.key_count ?? s.keys?.length ?? 0}</td>
              {canWrite && (
                <td className="text-center">
                  <button
                    type="button"
                    className="text-red-600 text-sm hover:underline"
                    onClick={() => deleteMut.mutate(
                      { clusterId: cluster.id, namespace: s.namespace, name: s.name },
                      { onSuccess: () => showToast(`Deleted ${s.name}`), onError: () => showToast("Delete failed", "error") }
                    )}
                  >Delete</button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </ResourceGridShell>
  );
};

export const ServicesTab: React.FC<TabProps> = ({
  cluster, namespace, namespaces, onNamespaceChange, liveStatus, canWrite, showToast,
}) => {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const ns = namespace || namespaces[0] || "default";
  const { data, isLoading } = useCachedServices(cluster.id, ns);
  const syncMut = useSyncServices();
  const deleteMut = useDeleteService();
  const items = data?.services || [];
  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return q ? items.filter((s) => s.name.toLowerCase().includes(q)) : items;
  }, [items, search]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <ResourceGridShell
      title="Services"
      liveStatus={liveStatus}
      namespaceSelect={<NamespaceSelect namespaces={namespaces} value={namespace} onChange={onNamespaceChange} />}
      search={search}
      onSearch={(v) => { setSearch(v); setPage(1); }}
      onSync={() => syncMut.mutate({ clusterId: cluster.id, namespace: ns })}
      syncing={syncMut.isPending}
      page={page}
      totalPages={totalPages}
      onPage={setPage}
    >
      <table className={gridStyles.table}>
        <thead><tr>
          <th className={gridStyles.headerCell}>Name</th>
          <th className={gridStyles.headerCell}>Type</th>
          <th className={gridStyles.headerCell}>Cluster IP</th>
          <th className={gridStyles.headerCell}>Ports</th>
          {canWrite && <th className={gridStyles.headerCellCenter}>Actions</th>}
        </tr></thead>
        <tbody>
          {isLoading ? (
            <tr><td colSpan={5} className="py-6 text-center text-sm text-gray-400">Loading…</td></tr>
          ) : paged.map((s) => (
            <tr key={s.name} className={gridStyles.row}>
              <td className="font-medium">{s.name}</td>
              <td>{s.type}</td>
              <td>{s.cluster_ip}</td>
              <td>{(s.ports || []).map((p) => p.port).join(", ")}</td>
              {canWrite && (
                <td className="text-center">
                  <button type="button" className="text-red-600 text-sm hover:underline"
                    onClick={() => deleteMut.mutate({ clusterId: cluster.id, namespace: ns, name: s.name })}
                  >Delete</button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </ResourceGridShell>
  );
};

export const ConfigMapsTab: React.FC<TabProps> = ({
  cluster, namespace, namespaces, onNamespaceChange, liveStatus, showToast,
}) => {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const ns = namespace || namespaces[0] || "default";
  const { data, isLoading } = useCachedConfigMaps(cluster.id, ns);
  const syncMut = useSyncConfigMaps();
  const deleteMut = useDeleteConfigMap();
  const items = data?.configmaps || [];
  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return q ? items.filter((c) => c.name.toLowerCase().includes(q)) : items;
  }, [items, search]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <ResourceGridShell
      title="ConfigMaps"
      liveStatus={liveStatus}
      namespaceSelect={<NamespaceSelect namespaces={namespaces} value={namespace} onChange={onNamespaceChange} />}
      search={search}
      onSearch={(v) => { setSearch(v); setPage(1); }}
      onSync={() => syncMut.mutate({ clusterId: cluster.id, namespace: ns })}
      syncing={syncMut.isPending}
      page={page}
      totalPages={totalPages}
      onPage={setPage}
    >
      <table className={gridStyles.table}>
        <thead><tr>
          <th className={gridStyles.headerCell}>Name</th>
          <th className={gridStyles.headerCell}>Keys</th>
          <th className={gridStyles.headerCell}>Created</th>
        </tr></thead>
        <tbody>
          {isLoading ? (
            <tr><td colSpan={3} className="py-6 text-center text-sm text-gray-400">Loading…</td></tr>
          ) : paged.map((c) => (
            <tr key={c.name} className={gridStyles.row}>
              <td className="font-medium">{c.name}</td>
              <td>{(c.data_keys || []).join(", ")}</td>
              <td>{c.created_at ? new Date(c.created_at).toLocaleString() : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </ResourceGridShell>
  );
};

export const IngressTab: React.FC<TabProps> = ({
  cluster, namespace, namespaces, onNamespaceChange, liveStatus, canWrite, showToast,
}) => {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const ns = namespace || namespaces[0] || "default";
  const { data, isLoading } = useCachedIngress(cluster.id, ns);
  const syncMut = useSyncIngress();
  const deleteMut = useDeleteIngress();
  const items = data?.ingress || [];
  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return q ? items.filter((i) => i.name.toLowerCase().includes(q)) : items;
  }, [items, search]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <ResourceGridShell
      title="Ingress"
      liveStatus={liveStatus}
      namespaceSelect={<NamespaceSelect namespaces={namespaces} value={namespace} onChange={onNamespaceChange} />}
      search={search}
      onSearch={(v) => { setSearch(v); setPage(1); }}
      onSync={() => syncMut.mutate({ clusterId: cluster.id, namespace: ns })}
      syncing={syncMut.isPending}
      page={page}
      totalPages={totalPages}
      onPage={setPage}
    >
      <table className={gridStyles.table}>
        <thead><tr>
          <th className={gridStyles.headerCell}>Name</th>
          <th className={gridStyles.headerCell}>Hosts</th>
          <th className={gridStyles.headerCell}>Services</th>
          <th className={gridStyles.headerCell}>Address</th>
          {canWrite && <th className={gridStyles.headerCellCenter}>Actions</th>}
        </tr></thead>
        <tbody>
          {isLoading ? (
            <tr><td colSpan={5} className="py-6 text-center text-sm text-gray-400">Loading…</td></tr>
          ) : paged.map((i) => (
            <tr key={i.name} className={gridStyles.row}>
              <td className="font-medium">{i.name}</td>
              <td>{(i.hosts || []).join(", ")}</td>
              <td>{(i.backend_services || []).join(", ")}</td>
              <td>{i.address || "—"}</td>
              {canWrite && (
                <td className="text-center">
                  <button type="button" className="text-red-600 text-sm hover:underline"
                    onClick={() => deleteMut.mutate({ clusterId: cluster.id, namespace: ns, name: i.name })}
                  >Delete</button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </ResourceGridShell>
  );
};

export const HelmTab: React.FC<TabProps> = ({
  cluster, namespace, namespaces, onNamespaceChange, liveStatus, canWrite,
}) => {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const { data, isLoading } = useHelmReleases(cluster.id, namespace || undefined);
  const uninstallMut = useUninstallHelmRelease();
  const items = data?.releases || [];
  const filtered = useMemo(() => {
    const q = search.toLowerCase();
    return q ? items.filter((r) => r.name.toLowerCase().includes(q)) : items;
  }, [items, search]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const paged = filtered.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <ResourceGridShell
      title="Helm Releases"
      liveStatus={liveStatus}
      namespaceSelect={<NamespaceSelect namespaces={namespaces} value={namespace} onChange={onNamespaceChange} />}
      search={search}
      onSearch={(v) => { setSearch(v); setPage(1); }}
      page={page}
      totalPages={totalPages}
      onPage={setPage}
    >
      <table className={gridStyles.table}>
        <thead><tr>
          <th className={gridStyles.headerCell}>Release</th>
          <th className={gridStyles.headerCell}>Namespace</th>
          <th className={gridStyles.headerCell}>Chart</th>
          <th className={gridStyles.headerCell}>Revision</th>
          <th className={gridStyles.headerCell}>Status</th>
          {canWrite && <th className={gridStyles.headerCellCenter}>Actions</th>}
        </tr></thead>
        <tbody>
          {isLoading ? (
            <tr><td colSpan={6} className="py-6 text-center text-sm text-gray-400">Loading…</td></tr>
          ) : paged.map((r) => (
            <tr key={`${r.namespace}/${r.name}`} className={gridStyles.row}>
              <td className="font-medium">{r.name}</td>
              <td>{r.namespace}</td>
              <td>{r.chart}</td>
              <td>{r.revision}</td>
              <td>{r.status}</td>
              {canWrite && (
                <td className="text-center">
                  <button type="button" className="text-red-600 text-sm hover:underline"
                    onClick={() => uninstallMut.mutate({ clusterId: cluster.id, releaseName: r.name, namespace: r.namespace })}
                  >Uninstall</button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </ResourceGridShell>
  );
};

export const AuditHistoryTab: React.FC<{ clusterId?: string; namespace?: string }> = ({
  clusterId, namespace,
}) => {
  const [page, setPage] = useState(1);
  const { data, isLoading } = useAksAuditHistory(clusterId, namespace);
  const items = data?.history || [];
  const totalPages = Math.max(1, Math.ceil(items.length / PAGE_SIZE));
  const paged = items.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-gray-800">Audit History</h2>
      <div className={gridStyles.shell}>
        <table className={gridStyles.table}>
          <thead><tr>
            <th className={gridStyles.headerCell}>Time</th>
            <th className={gridStyles.headerCell}>User</th>
            <th className={gridStyles.headerCell}>Action</th>
            <th className={gridStyles.headerCell}>Resource</th>
            <th className={gridStyles.headerCell}>Status</th>
            <th className={gridStyles.headerCell}>Summary</th>
          </tr></thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={6} className="py-6 text-center text-sm text-gray-400">Loading…</td></tr>
            ) : paged.map((h) => (
              <tr key={h.id} className={gridStyles.row}>
                <td>{h.timestamp ? new Date(h.timestamp).toLocaleString() : "—"}</td>
                <td>{h.user_email}</td>
                <td>{h.action}</td>
                <td>{h.resource_name}</td>
                <td>{h.status}</td>
                <td>{h.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <SimplePager page={page} totalPages={totalPages} onPage={setPage} />
    </div>
  );
};
