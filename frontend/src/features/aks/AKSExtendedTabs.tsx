/**
 * Extended AKS resource tabs — Secrets, Services, ConfigMaps, Ingress, Helm, Audit History.
 */

import React, { useCallback, useState } from "react";
import { gridStyles } from "../../components/gridStyles";
import {
  AKSCluster,
  K8sIngress,
  K8sSecret,
  K8sService,
  ConfigMap,
  useCachedSecrets,
  useCachedServices,
  useCachedConfigMaps,
  useCachedIngress,
  useHelmReleases,
  useAksAuditHistory,
  useAksBackgroundSync,
  useDeleteSecret,
  useDeleteService,
  useDeleteConfigMap,
  useDeleteIngress,
  useUpdateIngress,
  useUninstallHelmRelease,
  useCreateSecret,
  useUpdateSecret,
  useCreateService,
  useUpdateService,
  useCreateConfigMap,
  useUpdateConfigMap,
} from "../../services/aksApi";
import {
  CacheSourceBadge,
  ExtendedTabToolbar,
  GridPager,
  GridSearchBar,
  NamespaceSelect,
  useSearchPagination,
} from "./aksGridShared";
import { ResourceActionButtons } from "./ResourceActionButtons";
import {
  ConfigMapCreateModal,
  ConfigMapEditModal,
  ConfigMapViewModal,
  DeleteConfirmModal,
  IngressEditModal,
  IngressViewModal,
  SecretCreateModal,
  SecretEditModal,
  SecretViewModal,
  ServiceCreateModal,
  ServiceEditModal,
  ServiceViewModal,
} from "./K8sResourceModals";

type TabProps = {
  cluster: AKSCluster;
  namespace: string;
  namespaces: string[];
  onNamespaceChange: (ns: string) => void;
  canWrite: boolean;
  showToast: (msg: string, type?: "success" | "error") => void;
  formatDate: (value: string) => string;
};

type ResourceRef = { namespace: string; name: string };
type AksBackgroundSyncState = ReturnType<typeof useAksBackgroundSync>;

function useNsFilter(namespace: string) {
  return namespace || undefined;
}

function BackgroundRefreshStatus({ sync }: { sync?: AksBackgroundSyncState }) {
  if (!sync) return null;
  if (sync.isRetrying) {
    return <span className="text-sm text-amber-600">Refresh delayed, retrying...</span>;
  }
  if (sync.isRunning) {
    return <span className="text-sm text-blue-600">Syncing from Kubernetes...</span>;
  }
  if (sync.error) {
    return <span className="text-sm text-red-600">{sync.error}</span>;
  }
  return null;
}

function ExtendedResourceGrid<T extends { name: string; namespace?: string }>({
  title,
  namespace,
  namespaces,
  onNamespaceChange,
  canWrite,
  formatDate,
  source,
  lastSync,
  onSync,
  syncing,
  onCreate,
  createLabel,
  backgroundSync,
  isLoading,
  items,
  searchPlaceholder,
  searchFn,
  columns,
  renderRow,
}: {
  title: string;
  namespace: string;
  namespaces: string[];
  onNamespaceChange: (ns: string) => void;
  canWrite: boolean;
  formatDate: (value: string) => string;
  source?: string;
  lastSync?: string | null;
  onSync?: () => void;
  syncing?: boolean;
  onCreate?: () => void;
  createLabel?: string;
  backgroundSync?: AksBackgroundSyncState;
  isLoading: boolean;
  items: T[];
  searchPlaceholder: string;
  searchFn: (item: T, q: string) => boolean;
  columns: React.ReactNode;
  renderRow: (item: T) => React.ReactNode;
}) {
  const pag = useSearchPagination(items, searchFn);
  const showNsCol = !namespace;

  return (
    <div className="space-y-4">
      <ExtendedTabToolbar
        title={title}
        namespaceSelect={
          <NamespaceSelect namespaces={namespaces} value={namespace} onChange={onNamespaceChange} />
        }
        onSync={onSync}
        syncing={syncing}
        onCreate={onCreate}
        createLabel={createLabel}
        canWrite={canWrite}
      />
      <CacheSourceBadge source={source} lastSync={lastSync} formatDate={formatDate} />
      <BackgroundRefreshStatus sync={backgroundSync} />
      {isLoading ? (
        <div className="text-center py-8 text-gray-500">Loading...</div>
      ) : (
        <div className={gridStyles.shell}>
          <GridSearchBar
            search={pag.search}
            onSearch={pag.setSearch}
            onPage={pag.setPage}
            totalItems={items.length}
            shownItems={pag.filtered.length}
            placeholder={searchPlaceholder}
          />
          <div className="overflow-x-auto">
            <table className={gridStyles.table}>
              <thead className={gridStyles.head}>
                <tr>
                  {showNsCol && <th className={gridStyles.headerCell}>Namespace</th>}
                  {columns}
                  <th className={gridStyles.headerCellCenter}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pag.paged.length === 0 ? (
                  <tr>
                    <td colSpan={10} className="py-6 text-center text-sm text-gray-400">No resources found</td>
                  </tr>
                ) : (
                  pag.paged.map((item) => renderRow(item))
                )}
              </tbody>
            </table>
          </div>
          <GridPager page={pag.page} totalPages={pag.totalPages} onPage={pag.setPage} />
        </div>
      )}
    </div>
  );
}

export const SecretsTab: React.FC<TabProps> = ({
  cluster, namespace, namespaces, onNamespaceChange, canWrite, showToast, formatDate,
}) => {
  const nsFilter = useNsFilter(namespace);
  const { data, isLoading } = useCachedSecrets(cluster.id, nsFilter);
  const backgroundSync = useAksBackgroundSync({
    resourceType: "secrets",
    clusterId: cluster.id,
    namespace: nsFilter,
    auto: false,
  });
  const deleteMut = useDeleteSecret();
  const createMut = useCreateSecret();
  const updateMut = useUpdateSecret();
  const items = data?.secrets || [];

  const [viewTarget, setViewTarget] = useState<ResourceRef | null>(null);
  const [editTarget, setEditTarget] = useState<ResourceRef | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ResourceRef | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const searchFn = useCallback((s: K8sSecret, q: string) => s.name.toLowerCase().includes(q), []);
  const defaultNs = namespace || namespaces[0] || "default";

  return (
    <>
      <ExtendedResourceGrid
        title="Secrets"
        namespace={namespace}
        namespaces={namespaces}
        onNamespaceChange={onNamespaceChange}
        canWrite={canWrite}
        formatDate={formatDate}
        source={data?.source}
        lastSync={data?.last_sync}
        onSync={() => backgroundSync.start(false)}
        syncing={backgroundSync.isRunning}
        backgroundSync={backgroundSync}
        onCreate={() => setShowCreate(true)}
        createLabel="Create Secret"
        isLoading={isLoading}
        items={items}
        searchPlaceholder="Search secrets..."
        searchFn={searchFn}
        columns={
          <>
            <th className={gridStyles.headerCell}>Name</th>
            <th className={gridStyles.headerCell}>Type</th>
            <th className={gridStyles.headerCell}>Keys</th>
          </>
        }
        renderRow={(s) => (
          <tr key={`${s.namespace}/${s.name}`} className={gridStyles.row}>
            {!namespace && <td className={gridStyles.cell}>{s.namespace}</td>}
            <td className={gridStyles.strongCell}>{s.name}</td>
            <td className={gridStyles.cell}>{s.type}</td>
            <td className={gridStyles.cell}>{s.key_count ?? s.keys?.length ?? 0}</td>
            <td className={gridStyles.centerCell}>
              <ResourceActionButtons
                canWrite={canWrite}
                onView={() => setViewTarget({ namespace: s.namespace, name: s.name })}
                onEdit={() => setEditTarget({ namespace: s.namespace, name: s.name })}
                onDelete={() => setDeleteTarget({ namespace: s.namespace, name: s.name })}
              />
            </td>
          </tr>
        )}
      />
      {viewTarget && (
        <SecretViewModal
          clusterId={cluster.id}
          namespace={viewTarget.namespace}
          name={viewTarget.name}
          canWrite={canWrite}
          onClose={() => setViewTarget(null)}
        />
      )}
      {editTarget && (
        <SecretEditModal
          clusterId={cluster.id}
          namespace={editTarget.namespace}
          name={editTarget.name}
          saving={updateMut.isPending}
          onClose={() => setEditTarget(null)}
          onSave={(secretData) => updateMut.mutate(
            { clusterId: cluster.id, namespace: editTarget.namespace, name: editTarget.name, data: secretData },
            {
              onSuccess: () => { showToast("Secret updated"); setEditTarget(null); },
              onError: () => showToast("Update failed", "error"),
            }
          )}
        />
      )}
      {deleteTarget && (
        <DeleteConfirmModal
          title="Delete Secret"
          message={`Delete secret "${deleteTarget.name}" in namespace "${deleteTarget.namespace}"?`}
          confirming={deleteMut.isPending}
          onClose={() => setDeleteTarget(null)}
          onConfirm={() => deleteMut.mutate(
            { clusterId: cluster.id, namespace: deleteTarget.namespace, name: deleteTarget.name },
            {
              onSuccess: () => { showToast(`Deleted ${deleteTarget.name}`); setDeleteTarget(null); },
              onError: () => showToast("Delete failed", "error"),
            }
          )}
        />
      )}
      {showCreate && (
        <SecretCreateModal
          defaultNamespace={defaultNs}
          namespaces={namespaces}
          saving={createMut.isPending}
          onClose={() => setShowCreate(false)}
          onSave={(vars) => createMut.mutate(
            { clusterId: cluster.id, ...vars },
            {
              onSuccess: () => { showToast("Secret created"); setShowCreate(false); },
              onError: () => showToast("Create failed", "error"),
            }
          )}
        />
      )}
    </>
  );
};

export const ServicesTab: React.FC<TabProps> = ({
  cluster, namespace, namespaces, onNamespaceChange, canWrite, showToast, formatDate,
}) => {
  const nsFilter = useNsFilter(namespace);
  const { data, isLoading } = useCachedServices(cluster.id, nsFilter);
  const backgroundSync = useAksBackgroundSync({
    resourceType: "services",
    clusterId: cluster.id,
    namespace: nsFilter,
    auto: false,
  });
  const deleteMut = useDeleteService();
  const createMut = useCreateService();
  const updateMut = useUpdateService();
  const items = data?.services || [];

  const [viewTarget, setViewTarget] = useState<ResourceRef | null>(null);
  const [editTarget, setEditTarget] = useState<ResourceRef | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ResourceRef | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const searchFn = useCallback((s: K8sService, q: string) => s.name.toLowerCase().includes(q), []);
  const defaultNs = namespace || namespaces[0] || "default";

  return (
    <>
      <ExtendedResourceGrid
        title="Services"
        namespace={namespace}
        namespaces={namespaces}
        onNamespaceChange={onNamespaceChange}
        canWrite={canWrite}
        formatDate={formatDate}
        source={data?.source}
        lastSync={data?.last_sync}
        onSync={() => backgroundSync.start(false)}
        syncing={backgroundSync.isRunning}
        backgroundSync={backgroundSync}
        onCreate={() => setShowCreate(true)}
        createLabel="Create Service"
        isLoading={isLoading}
        items={items}
        searchPlaceholder="Search services..."
        searchFn={searchFn}
        columns={
          <>
            <th className={gridStyles.headerCell}>Name</th>
            <th className={gridStyles.headerCell}>Type</th>
            <th className={gridStyles.headerCell}>Cluster IP</th>
            <th className={gridStyles.headerCell}>Ports</th>
          </>
        }
        renderRow={(s) => (
          <tr key={`${s.namespace}/${s.name}`} className={gridStyles.row}>
            {!namespace && <td className={gridStyles.cell}>{s.namespace}</td>}
            <td className={gridStyles.strongCell}>{s.name}</td>
            <td className={gridStyles.cell}>{s.type}</td>
            <td className={gridStyles.cell}>{s.cluster_ip || "—"}</td>
            <td className={gridStyles.cell}>{(s.ports || []).map((p) => p.port).join(", ") || "—"}</td>
            <td className={gridStyles.centerCell}>
              <ResourceActionButtons
                canWrite={canWrite}
                showEdit={true}
                onView={() => setViewTarget({ namespace: s.namespace, name: s.name })}
                onEdit={() => setEditTarget({ namespace: s.namespace, name: s.name })}
                onDelete={() => setDeleteTarget({ namespace: s.namespace, name: s.name })}
              />
            </td>
          </tr>
        )}
      />
      {viewTarget && (
        <ServiceViewModal
          clusterId={cluster.id}
          namespace={viewTarget.namespace}
          name={viewTarget.name}
          onClose={() => setViewTarget(null)}
        />
      )}
      {editTarget && (
        <ServiceEditModal
          clusterId={cluster.id}
          namespace={editTarget.namespace}
          name={editTarget.name}
          saving={updateMut.isPending}
          onClose={() => setEditTarget(null)}
          onSave={(vars) => updateMut.mutate(
            { clusterId: cluster.id, ...vars },
            {
              onSuccess: () => { showToast("Service updated"); setEditTarget(null); },
              onError: () => showToast("Update failed", "error"),
            }
          )}
        />
      )}
      {deleteTarget && (
        <DeleteConfirmModal
          title="Delete Service"
          message={`Delete service "${deleteTarget.name}" in namespace "${deleteTarget.namespace}"?`}
          confirming={deleteMut.isPending}
          onClose={() => setDeleteTarget(null)}
          onConfirm={() => deleteMut.mutate(
            { clusterId: cluster.id, namespace: deleteTarget.namespace, name: deleteTarget.name },
            {
              onSuccess: () => { showToast(`Deleted ${deleteTarget.name}`); setDeleteTarget(null); },
              onError: () => showToast("Delete failed", "error"),
            }
          )}
        />
      )}
      {showCreate && (
        <ServiceCreateModal
          defaultNamespace={defaultNs}
          namespaces={namespaces}
          saving={createMut.isPending}
          onClose={() => setShowCreate(false)}
          onSave={(vars) => createMut.mutate(
            { clusterId: cluster.id, ...vars },
            {
              onSuccess: () => { showToast("Service created"); setShowCreate(false); },
              onError: () => showToast("Create failed", "error"),
            }
          )}
        />
      )}
    </>
  );
};

export const ConfigMapsTab: React.FC<TabProps> = ({
  cluster, namespace, namespaces, onNamespaceChange, canWrite, showToast, formatDate,
}) => {
  const nsFilter = useNsFilter(namespace);
  const { data, isLoading } = useCachedConfigMaps(cluster.id, nsFilter);
  const backgroundSync = useAksBackgroundSync({
    resourceType: "configmaps",
    clusterId: cluster.id,
    namespace: nsFilter,
    auto: false,
  });
  const deleteMut = useDeleteConfigMap();
  const createMut = useCreateConfigMap();
  const updateMut = useUpdateConfigMap();
  const items = data?.configmaps || [];

  const [viewTarget, setViewTarget] = useState<ResourceRef | null>(null);
  const [editTarget, setEditTarget] = useState<ResourceRef | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ResourceRef | null>(null);
  const [showCreate, setShowCreate] = useState(false);

  const searchFn = useCallback((c: ConfigMap, q: string) => c.name.toLowerCase().includes(q), []);
  const defaultNs = namespace || namespaces[0] || "default";

  return (
    <>
      <ExtendedResourceGrid
        title="ConfigMaps"
        namespace={namespace}
        namespaces={namespaces}
        onNamespaceChange={onNamespaceChange}
        canWrite={canWrite}
        formatDate={formatDate}
        source={data?.source}
        lastSync={data?.last_sync}
        onSync={() => backgroundSync.start(false)}
        syncing={backgroundSync.isRunning}
        backgroundSync={backgroundSync}
        onCreate={() => setShowCreate(true)}
        createLabel="Create ConfigMap"
        isLoading={isLoading}
        items={items}
        searchPlaceholder="Search configmaps..."
        searchFn={searchFn}
        columns={
          <>
            <th className={gridStyles.headerCell}>Name</th>
            <th className={gridStyles.headerCell}>Keys</th>
            <th className={gridStyles.headerCell}>Created</th>
          </>
        }
        renderRow={(c) => (
          <tr key={`${c.namespace}/${c.name}`} className={gridStyles.row}>
            {!namespace && <td className={gridStyles.cell}>{c.namespace}</td>}
            <td className={gridStyles.strongCell}>{c.name}</td>
            <td className={gridStyles.cell}>{(c.data_keys || []).join(", ") || "—"}</td>
            <td className={gridStyles.cell}>{c.created_at ? formatDate(c.created_at) : "—"}</td>
            <td className={gridStyles.centerCell}>
              <ResourceActionButtons
                canWrite={canWrite}
                onView={() => setViewTarget({ namespace: c.namespace, name: c.name })}
                onEdit={() => setEditTarget({ namespace: c.namespace, name: c.name })}
                onDelete={() => setDeleteTarget({ namespace: c.namespace, name: c.name })}
              />
            </td>
          </tr>
        )}
      />
      {viewTarget && (
        <ConfigMapViewModal
          clusterId={cluster.id}
          namespace={viewTarget.namespace}
          name={viewTarget.name}
          onClose={() => setViewTarget(null)}
        />
      )}
      {editTarget && (
        <ConfigMapEditModal
          clusterId={cluster.id}
          namespace={editTarget.namespace}
          name={editTarget.name}
          saving={updateMut.isPending}
          onClose={() => setEditTarget(null)}
          onSave={(cmData) => updateMut.mutate(
            { clusterId: cluster.id, namespace: editTarget.namespace, name: editTarget.name, data: cmData },
            {
              onSuccess: () => { showToast("ConfigMap updated"); setEditTarget(null); },
              onError: () => showToast("Update failed", "error"),
            }
          )}
        />
      )}
      {deleteTarget && (
        <DeleteConfirmModal
          title="Delete ConfigMap"
          message={`Delete configmap "${deleteTarget.name}" in namespace "${deleteTarget.namespace}"?`}
          confirming={deleteMut.isPending}
          onClose={() => setDeleteTarget(null)}
          onConfirm={() => deleteMut.mutate(
            { clusterId: cluster.id, namespace: deleteTarget.namespace, name: deleteTarget.name },
            {
              onSuccess: () => { showToast(`Deleted ${deleteTarget.name}`); setDeleteTarget(null); },
              onError: () => showToast("Delete failed", "error"),
            }
          )}
        />
      )}
      {showCreate && (
        <ConfigMapCreateModal
          defaultNamespace={defaultNs}
          namespaces={namespaces}
          saving={createMut.isPending}
          onClose={() => setShowCreate(false)}
          onSave={(vars) => createMut.mutate(
            { clusterId: cluster.id, ...vars },
            {
              onSuccess: () => { showToast("ConfigMap created"); setShowCreate(false); },
              onError: () => showToast("Create failed", "error"),
            }
          )}
        />
      )}
    </>
  );
};

export const IngressTab: React.FC<TabProps> = ({
  cluster, namespace, namespaces, onNamespaceChange, canWrite, showToast, formatDate,
}) => {
  const nsFilter = useNsFilter(namespace);
  const { data, isLoading } = useCachedIngress(cluster.id, nsFilter);
  const backgroundSync = useAksBackgroundSync({
    resourceType: "ingress",
    clusterId: cluster.id,
    namespace: nsFilter,
    auto: false,
  });
  const deleteMut = useDeleteIngress();
  const updateMut = useUpdateIngress();
  const items = data?.ingress || [];

  const [viewTarget, setViewTarget] = useState<ResourceRef | null>(null);
  const [editTarget, setEditTarget] = useState<ResourceRef | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<ResourceRef | null>(null);

  const searchFn = useCallback((i: K8sIngress, q: string) => i.name.toLowerCase().includes(q), []);

  return (
    <>
      <ExtendedResourceGrid
        title="Ingress"
        namespace={namespace}
        namespaces={namespaces}
        onNamespaceChange={onNamespaceChange}
        canWrite={canWrite}
        formatDate={formatDate}
        source={data?.source}
        lastSync={data?.last_sync}
        onSync={() => backgroundSync.start(false)}
        syncing={backgroundSync.isRunning}
        backgroundSync={backgroundSync}
        isLoading={isLoading}
        items={items}
        searchPlaceholder="Search ingress..."
        searchFn={searchFn}
        columns={
          <>
            <th className={gridStyles.headerCell}>Name</th>
            <th className={gridStyles.headerCell}>Hosts</th>
            <th className={gridStyles.headerCell}>Services</th>
            <th className={gridStyles.headerCell}>Address</th>
          </>
        }
        renderRow={(i) => (
          <tr key={`${i.namespace}/${i.name}`} className={gridStyles.row}>
            {!namespace && <td className={gridStyles.cell}>{i.namespace}</td>}
            <td className={gridStyles.strongCell}>{i.name}</td>
            <td className={gridStyles.cell}>{(i.hosts || []).join(", ") || "—"}</td>
            <td className={gridStyles.cell}>{(i.backend_services || []).join(", ") || "—"}</td>
            <td className={gridStyles.cell}>{i.address || "—"}</td>
            <td className={gridStyles.centerCell}>
              <ResourceActionButtons
                canWrite={canWrite}
                showEdit={true}
                onView={() => setViewTarget({ namespace: i.namespace, name: i.name })}
                onEdit={() => setEditTarget({ namespace: i.namespace, name: i.name })}
                onDelete={() => setDeleteTarget({ namespace: i.namespace, name: i.name })}
              />
            </td>
          </tr>
        )}
      />
      {viewTarget && (
        <IngressViewModal
          clusterId={cluster.id}
          namespace={viewTarget.namespace}
          name={viewTarget.name}
          onClose={() => setViewTarget(null)}
        />
      )}
      {editTarget && (
        <IngressEditModal
          clusterId={cluster.id}
          namespace={editTarget.namespace}
          name={editTarget.name}
          saving={updateMut.isPending}
          onClose={() => setEditTarget(null)}
          onSave={(vars) => updateMut.mutate(
            { clusterId: cluster.id, ...vars },
            {
              onSuccess: () => { showToast(`Updated ${editTarget.name}`); setEditTarget(null); },
              onError: () => showToast("Update failed", "error"),
            }
          )}
        />
      )}
      {deleteTarget && (
        <DeleteConfirmModal
          title="Delete Ingress"
          message={`Delete ingress "${deleteTarget.name}" in namespace "${deleteTarget.namespace}"?`}
          confirming={deleteMut.isPending}
          onClose={() => setDeleteTarget(null)}
          onConfirm={() => deleteMut.mutate(
            { clusterId: cluster.id, namespace: deleteTarget.namespace, name: deleteTarget.name },
            {
              onSuccess: () => { showToast(`Deleted ${deleteTarget.name}`); setDeleteTarget(null); },
              onError: () => showToast("Delete failed", "error"),
            }
          )}
        />
      )}
    </>
  );
};

export const HelmTab: React.FC<TabProps> = ({
  cluster, namespace, namespaces, onNamespaceChange, canWrite, showToast,
}) => {
  const nsFilter = useNsFilter(namespace);
  const { data, isLoading } = useHelmReleases(cluster.id, nsFilter);
  const uninstallMut = useUninstallHelmRelease();
  const items = data?.releases || [];
  const pag = useSearchPagination(items, useCallback((r, q) => r.name.toLowerCase().includes(q), []));
  const [deleteTarget, setDeleteTarget] = useState<{ namespace: string; name: string } | null>(null);

  return (
    <div className="space-y-4">
      <ExtendedTabToolbar
        title="Helm Releases"
        namespaceSelect={<NamespaceSelect namespaces={namespaces} value={namespace} onChange={onNamespaceChange} />}
        canWrite={canWrite}
      />
      {isLoading ? (
        <div className="text-center py-8 text-gray-500">Loading...</div>
      ) : (
        <div className={gridStyles.shell}>
          <GridSearchBar
            search={pag.search}
            onSearch={pag.setSearch}
            onPage={pag.setPage}
            totalItems={items.length}
            shownItems={pag.filtered.length}
            placeholder="Search releases..."
          />
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}>Release</th>
                <th className={gridStyles.headerCell}>Namespace</th>
                <th className={gridStyles.headerCell}>Chart</th>
                <th className={gridStyles.headerCell}>Revision</th>
                <th className={gridStyles.headerCell}>Status</th>
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pag.paged.map((r) => (
                <tr key={`${r.namespace}/${r.name}`} className={gridStyles.row}>
                  <td className={gridStyles.strongCell}>{r.name}</td>
                  <td className={gridStyles.cell}>{r.namespace}</td>
                  <td className={gridStyles.cell}>{r.chart}</td>
                  <td className={gridStyles.cell}>{r.revision}</td>
                  <td className={gridStyles.cell}>{r.status}</td>
                  <td className={gridStyles.centerCell}>
                    {canWrite && (
                      <ResourceActionButtons
                        canWrite={canWrite}
                        showEdit={false}
                        showView={false}
                        onDelete={() => setDeleteTarget({ namespace: r.namespace, name: r.name })}
                      />
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <GridPager page={pag.page} totalPages={pag.totalPages} onPage={pag.setPage} />
        </div>
      )}
      {deleteTarget && (
        <DeleteConfirmModal
          title="Uninstall Helm Release"
          message={`Uninstall release "${deleteTarget.name}" in namespace "${deleteTarget.namespace}"?`}
          confirming={uninstallMut.isPending}
          onClose={() => setDeleteTarget(null)}
          onConfirm={() => uninstallMut.mutate(
            { clusterId: cluster.id, releaseName: deleteTarget.name, namespace: deleteTarget.namespace },
            {
              onSuccess: () => { showToast(`Uninstalled ${deleteTarget.name}`); setDeleteTarget(null); },
              onError: () => showToast("Uninstall failed", "error"),
            }
          )}
        />
      )}
    </div>
  );
};

export const AuditHistoryTab: React.FC<{ clusterId?: string; namespace?: string }> = ({
  clusterId, namespace,
}) => {
  const { data, isLoading } = useAksAuditHistory(clusterId, namespace);
  const items = data?.history || [];
  const pag = useSearchPagination(items, useCallback((h, q) =>
    h.resource_name.toLowerCase().includes(q) ||
    h.action.toLowerCase().includes(q) ||
    h.user_email.toLowerCase().includes(q), []));

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-gray-800">Audit History</h2>
      {isLoading ? (
        <div className="text-center py-8 text-gray-500">Loading...</div>
      ) : (
        <div className={gridStyles.shell}>
          <GridSearchBar
            search={pag.search}
            onSearch={pag.setSearch}
            onPage={pag.setPage}
            totalItems={items.length}
            shownItems={pag.filtered.length}
            placeholder="Search audit history..."
          />
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}>Time</th>
                <th className={gridStyles.headerCell}>User</th>
                <th className={gridStyles.headerCell}>Action</th>
                <th className={gridStyles.headerCell}>Resource</th>
                <th className={gridStyles.headerCell}>Status</th>
                <th className={gridStyles.headerCell}>Summary</th>
              </tr>
            </thead>
            <tbody>
              {pag.paged.map((h) => (
                <tr key={h.id} className={gridStyles.row}>
                  <td className={gridStyles.cell}>{h.timestamp ? new Date(h.timestamp).toLocaleString() : "—"}</td>
                  <td className={gridStyles.cell}>{h.user_email}</td>
                  <td className={gridStyles.cell}>{h.action}</td>
                  <td className={gridStyles.cell}>{h.resource_name}</td>
                  <td className={gridStyles.cell}>{h.status}</td>
                  <td className={gridStyles.cell}>{h.summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <GridPager page={pag.page} totalPages={pag.totalPages} onPage={pag.setPage} />
        </div>
      )}
    </div>
  );
};
