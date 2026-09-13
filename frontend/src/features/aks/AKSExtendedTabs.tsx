/**
 * Extended AKS resource tabs — Secrets, Services, ConfigMaps, Ingress, Helm, Audit History.
 */

import React, { useCallback, useState } from "react";
import { gridStyles, SortableHeader, nextSortState, type SortState } from "../../components/gridStyles";
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
  GridStateRow,
  useGridSort,
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
  isError,
  sort,
  onSort,
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
  isError?: boolean;
  /** Supplied when the tab sorts; lets the grid-owned Namespace column sort too. */
  sort?: SortState<string>;
  onSort?: (key: string) => void;
  items: T[];
  searchPlaceholder: string;
  searchFn: (item: T, q: string) => boolean;
  columns: React.ReactNode;
  renderRow: (item: T) => React.ReactNode;
}) {
  const pag = useSearchPagination(items, searchFn);
  const showNsCol = !namespace;
  // colSpan must match the real column count (caller columns + optional Namespace).
  const columnCount = React.Children.count(columns) + (showNsCol ? 1 : 0);

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
      {(
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
                  {showNsCol && (
                    <th className={gridStyles.headerCell}>
                      {sort && onSort ? (
                        <SortableHeader label="Namespace" active={sort.key === "namespace"} direction={sort.direction} onClick={() => onSort("namespace")} />
                      ) : "Namespace"}
                    </th>
                  )}
                  {columns}
                  <th className={gridStyles.headerCellCenter}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {pag.paged.length === 0 ? (
                  <GridStateRow
                    colSpan={columnCount}
                    isLoading={isLoading}
                    isError={isError}
                    emptyText={pag.search ? "No resources match your search" : "No resources found"}
                  />
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
  const { data, isLoading, isError } = useCachedSecrets(cluster.id, nsFilter);
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
  const secretsAccessor = useCallback((r: K8sSecret, key: string): string | number => {
    switch (key) {
      case "namespace": return r.namespace.toLowerCase();
      case "type": return (r.type || "").toLowerCase();
      case "keys": return r.key_count ?? r.keys?.length ?? 0;
      default: return r.name.toLowerCase();
    }
  }, []);
  const { sort, setSort, sorted } = useGridSort(items, secretsAccessor, { key: "name", direction: "asc" });

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
        isError={isError}
        sort={sort}
        onSort={(k) => setSort(nextSortState(sort, k))}
        items={sorted}
        searchPlaceholder="Search secrets..."
        searchFn={searchFn}
        columns={
          <>
            <th className={gridStyles.headerCell}><SortableHeader label="Name" active={sort.key === "name"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "name"))} /></th>
            <th className={gridStyles.headerCell}><SortableHeader label="Type" active={sort.key === "type"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "type"))} /></th>
            <th className={gridStyles.headerCell}><SortableHeader label="Keys" active={sort.key === "keys"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "keys"))} /></th>
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
  const { data, isLoading, isError } = useCachedServices(cluster.id, nsFilter);
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
  const servicesAccessor = useCallback((r: K8sService, key: string): string | number => {
    switch (key) {
      case "namespace": return r.namespace.toLowerCase();
      case "type": return (r.type || "").toLowerCase();
      case "clusterIp": return (r.cluster_ip || "").toLowerCase();
      case "ports": return (r.ports || []).length;
      default: return r.name.toLowerCase();
    }
  }, []);
  const { sort, setSort, sorted } = useGridSort(items, servicesAccessor, { key: "name", direction: "asc" });

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
        isError={isError}
        sort={sort}
        onSort={(k) => setSort(nextSortState(sort, k))}
        items={sorted}
        searchPlaceholder="Search services..."
        searchFn={searchFn}
        columns={
          <>
            <th className={gridStyles.headerCell}><SortableHeader label="Name" active={sort.key === "name"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "name"))} /></th>
            <th className={gridStyles.headerCell}><SortableHeader label="Type" active={sort.key === "type"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "type"))} /></th>
            <th className={gridStyles.headerCell}><SortableHeader label="Cluster IP" active={sort.key === "clusterIp"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "clusterIp"))} /></th>
            <th className={gridStyles.headerCell}><SortableHeader label="Ports" active={sort.key === "ports"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "ports"))} /></th>
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
  const { data, isLoading, isError } = useCachedConfigMaps(cluster.id, nsFilter);
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
  const configMapsAccessor = useCallback((r: ConfigMap, key: string): string | number => {
    switch (key) {
      case "namespace": return r.namespace.toLowerCase();
      case "keys": return (r.data_keys || []).length;
      case "created": return r.created_at || "";
      default: return r.name.toLowerCase();
    }
  }, []);
  const { sort, setSort, sorted } = useGridSort(items, configMapsAccessor, { key: "name", direction: "asc" });

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
        isError={isError}
        sort={sort}
        onSort={(k) => setSort(nextSortState(sort, k))}
        items={sorted}
        searchPlaceholder="Search configmaps..."
        searchFn={searchFn}
        columns={
          <>
            <th className={gridStyles.headerCell}><SortableHeader label="Name" active={sort.key === "name"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "name"))} /></th>
            <th className={gridStyles.headerCell}><SortableHeader label="Keys" active={sort.key === "keys"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "keys"))} /></th>
            <th className={gridStyles.headerCell}><SortableHeader label="Created" active={sort.key === "created"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "created"))} /></th>
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
  const { data, isLoading, isError } = useCachedIngress(cluster.id, nsFilter);
  const backgroundSync = useAksBackgroundSync({
    resourceType: "ingress",
    clusterId: cluster.id,
    namespace: nsFilter,
    auto: false,
  });
  const deleteMut = useDeleteIngress();
  const updateMut = useUpdateIngress();
  const items = data?.ingress || [];
  const ingressAccessor = useCallback((r: K8sIngress, key: string): string | number => {
    switch (key) {
      case "namespace": return r.namespace.toLowerCase();
      case "hosts": return (r.hosts || []).join(",").toLowerCase();
      case "address": return (r.address || "").toLowerCase();
      default: return r.name.toLowerCase();
    }
  }, []);
  const { sort, setSort, sorted } = useGridSort(items, ingressAccessor, { key: "name", direction: "asc" });

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
        isError={isError}
        sort={sort}
        onSort={(k) => setSort(nextSortState(sort, k))}
        items={sorted}
        searchPlaceholder="Search ingress..."
        searchFn={searchFn}
        columns={
          <>
            <th className={gridStyles.headerCell}><SortableHeader label="Name" active={sort.key === "name"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "name"))} /></th>
            <th className={gridStyles.headerCell}><SortableHeader label="Hosts" active={sort.key === "hosts"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "hosts"))} /></th>
            <th className={gridStyles.headerCell}>Services</th>
            <th className={gridStyles.headerCell}><SortableHeader label="Address" active={sort.key === "address"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "address"))} /></th>
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
  const { data, isLoading, isError, refetch, isFetching } = useHelmReleases(cluster.id, nsFilter);
  const uninstallMut = useUninstallHelmRelease();
  const items = data?.releases || [];
  const helmAccessor = useCallback((r: typeof items[0], key: string): string | number => {
    switch (key) {
      case "namespace": return r.namespace.toLowerCase();
      case "chart": return (r.chart || "").toLowerCase();
      case "revision": return Number(r.revision) || 0;
      case "status": return (r.status || "").toLowerCase();
      default: return r.name.toLowerCase();
    }
  }, []);
  const { sort, setSort, sorted } = useGridSort(items, helmAccessor, { key: "name", direction: "asc" });
  const pag = useSearchPagination(sorted, useCallback((r, q) => r.name.toLowerCase().includes(q), []));
  const [deleteTarget, setDeleteTarget] = useState<{ namespace: string; name: string } | null>(null);

  return (
    <div className="space-y-4">
      <ExtendedTabToolbar
        title="Helm Releases"
        namespaceSelect={<NamespaceSelect namespaces={namespaces} value={namespace} onChange={onNamespaceChange} />}
        onSync={() => refetch()}
        syncing={isFetching}
        canWrite={canWrite}
      />
      {(
        <div className={gridStyles.shell}>
          <GridSearchBar
            search={pag.search}
            onSearch={pag.setSearch}
            onPage={pag.setPage}
            totalItems={items.length}
            shownItems={pag.filtered.length}
            placeholder="Search releases..."
          />
          <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}><SortableHeader label="Release" active={sort.key === "name"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "name"))} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Namespace" active={sort.key === "namespace"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "namespace"))} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Chart" active={sort.key === "chart"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "chart"))} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Revision" active={sort.key === "revision"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "revision"))} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Status" active={sort.key === "status"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "status"))} /></th>
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pag.paged.length === 0 && (
                <GridStateRow colSpan={6} isLoading={isLoading} isError={isError} emptyText="No Helm releases found" />
              )}
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
          </div>
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
  const { data, isLoading, isError } = useAksAuditHistory(clusterId, namespace);
  const items = data?.history || [];
  const auditAccessor = useCallback((h: typeof items[0], key: string): string | number => {
    switch (key) {
      case "user": return (h.user_email || "").toLowerCase();
      case "action": return (h.action || "").toLowerCase();
      case "resource": return (h.resource_name || "").toLowerCase();
      case "status": return (h.status || "").toLowerCase();
      case "summary": return (h.summary || "").toLowerCase();
      default: return h.timestamp || "";
    }
  }, []);
  const { sort, setSort, sorted } = useGridSort(items, auditAccessor, { key: "time", direction: "desc" });
  // status and summary are displayed, so they should be searchable too.
  const pag = useSearchPagination(sorted, useCallback((h, q) =>
    h.resource_name.toLowerCase().includes(q) ||
    h.action.toLowerCase().includes(q) ||
    (h.status || "").toLowerCase().includes(q) ||
    (h.summary || "").toLowerCase().includes(q) ||
    h.user_email.toLowerCase().includes(q), []));

  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-gray-800">Audit History</h2>
      {(
        <div className={gridStyles.shell}>
          <GridSearchBar
            search={pag.search}
            onSearch={pag.setSearch}
            onPage={pag.setPage}
            totalItems={items.length}
            shownItems={pag.filtered.length}
            placeholder="Search audit history..."
          />
          <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}><SortableHeader label="Time" active={sort.key === "time"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "time"))} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="User" active={sort.key === "user"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "user"))} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Action" active={sort.key === "action"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "action"))} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Resource" active={sort.key === "resource"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "resource"))} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Status" active={sort.key === "status"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "status"))} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Summary" active={sort.key === "summary"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "summary"))} /></th>
              </tr>
            </thead>
            <tbody>
              {pag.paged.length === 0 && (
                <GridStateRow colSpan={6} isLoading={isLoading} isError={isError} emptyText="No audit events recorded" />
              )}
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
          </div>
          <GridPager page={pag.page} totalPages={pag.totalPages} onPage={pag.setPage} />
        </div>
      )}
    </div>
  );
};
