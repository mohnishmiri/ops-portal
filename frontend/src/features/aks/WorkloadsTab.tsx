/**
 * StatefulSets / DaemonSets tab for the AKS Operations Center.
 *
 * One component serves both workload kinds; kind-specific controls (scale,
 * partition, volume claims for StatefulSets; maxUnavailable/maxSurge for
 * DaemonSets) are switched on `kind`. Mutating actions are hidden unless the
 * page grants the matching capability — the API authorizes every call itself.
 */

import React, { useCallback, useMemo, useState } from "react";
import { gridStyles, SortableHeader, nextSortState } from "../../components/gridStyles";
import { MetricCard, MetricCardIcons } from "../../components/MetricCard";
import {
  AKSCluster,
  K8sWorkload,
  WorkloadDetail,
  WorkloadKind,
  WorkloadPod,
  WorkloadStatus,
  useAksBackgroundSync,
  useCachedWorkloads,
  useDeleteWorkload,
  useRestartWorkload,
  useRollbackWorkload,
  useScaleWorkload,
  useUpdateWorkloadImage,
  useUpdateWorkloadStrategy,
  useWorkloadDetail,
} from "../../services/aksApi";
import {
  CachedSyncStatus,
  GridPager,
  GridSearchBar,
  GridStateRow,
  NamespaceSelect,
  SyncFromKubernetesButton,
  useGridSort,
  useSearchPagination,
} from "./aksGridShared";
import { useAksLiveWatch } from "../../hooks/useAksLiveWatch";
import { ModalShell } from "./K8sResourceModals";
import {
  apiErrorDetail,
  DetailIcons,
  DetailTabs,
  EventList,
  formatAge,
  iconProps,
  KeyValue,
  WORKLOAD_STATUS_STYLES,
  WorkloadPodsTable,
  YamlView,
} from "./detailShared";
import { DownloadLogsButton, LogArchiveDownload } from "./LogArchiveDownload";

type WorkloadsTabProps = {
  kind: WorkloadKind;
  cluster: AKSCluster;
  namespace: string;
  namespaces: string[];
  onNamespaceChange: (ns: string) => void;
  showToast: (msg: string, type?: "success" | "error") => void;
  formatDate: (value: string) => string;
  canManage: boolean;
  canDelete: boolean;
  canDeletePod: boolean;
  logDownload: LogArchiveDownload;
  onOpenPod?: (pod: WorkloadPod) => void;
  onViewPodLogs: (pod: WorkloadPod) => void;
  onDeletePod?: (pod: WorkloadPod) => void;
};

type ModalState =
  | { type: "scale"; item: K8sWorkload; replicas: number }
  | { type: "image"; item: K8sWorkload; container: string; image: string }
  | {
      type: "strategy";
      item: K8sWorkload;
      strategyType: "RollingUpdate" | "OnDelete";
      partition: string;
      maxUnavailable: string;
      maxSurge: string;
    }
  | { type: "restart"; item: K8sWorkload }
  | { type: "delete"; item: K8sWorkload; policy: "Background" | "Orphan" }
  | { type: "rollback"; item: K8sWorkload; revision: number }
  | null;

const STATUS_FILTERS: (WorkloadStatus | "All")[] = ["All", "Healthy", "Updating", "Degraded", "Unavailable", "Idle"];

const LABELS: Record<WorkloadKind, { singular: string; plural: string }> = {
  statefulset: { singular: "StatefulSet", plural: "StatefulSets" },
  daemonset: { singular: "DaemonSet", plural: "DaemonSets" },
};

const btn = {
  primary: "px-4 py-2 bg-att-500 text-white rounded-lg text-sm hover:bg-att-600 disabled:opacity-50",
  secondary: "px-4 py-2 border border-att-200 rounded-lg text-sm text-gray-700 hover:bg-att-50",
  danger: "px-4 py-2 bg-red-600 text-white rounded-lg text-sm hover:bg-red-700 disabled:opacity-50",
  icon: "p-1 rounded disabled:opacity-50",
};

const inputCls =
  "w-full rounded-lg border border-att-200 px-3 py-2 text-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100";

function strategyLabel(item: K8sWorkload): string {
  if (item.update_strategy !== "RollingUpdate") return item.update_strategy ?? "—";
  if (item.kind === "StatefulSet") return item.partition ? `RollingUpdate (partition ${item.partition})` : "RollingUpdate";
  const parts = [
    item.max_unavailable ? `maxUnavail ${item.max_unavailable}` : null,
    item.max_surge && item.max_surge !== "0" ? `maxSurge ${item.max_surge}` : null,
  ].filter(Boolean);
  return parts.length ? `RollingUpdate (${parts.join(", ")})` : "RollingUpdate";
}

// Inline SVG action icons, matching the stroke style used across the AKS page.
const ActionIcons = {
  view: DetailIcons.view,
  scale: <svg {...iconProps}><polyline points="15 3 21 3 21 9" /><polyline points="9 21 3 21 3 15" /><line x1="21" y1="3" x2="14" y2="10" /><line x1="3" y1="21" x2="10" y2="14" /></svg>,
  restart: <svg {...iconProps}><polyline points="23 4 23 10 17 10" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" /></svg>,
  image: <svg {...iconProps}><rect x="3" y="3" width="18" height="18" rx="2" /><path d="M3 9h18" /><path d="M9 21V9" /></svg>,
  strategy: <svg {...iconProps}><line x1="4" y1="21" x2="4" y2="14" /><line x1="4" y1="10" x2="4" y2="3" /><line x1="12" y1="21" x2="12" y2="12" /><line x1="12" y1="8" x2="12" y2="3" /><line x1="20" y1="21" x2="20" y2="16" /><line x1="20" y1="12" x2="20" y2="3" /><line x1="1" y1="14" x2="7" y2="14" /><line x1="9" y1="8" x2="15" y2="8" /><line x1="17" y1="16" x2="23" y2="16" /></svg>,
  trash: DetailIcons.trash,
};

export const WorkloadsTab: React.FC<WorkloadsTabProps> = ({
  kind,
  cluster,
  namespace,
  namespaces,
  onNamespaceChange,
  showToast,
  formatDate,
  canManage,
  canDelete,
  canDeletePod,
  logDownload,
  onOpenPod,
  onViewPodLogs,
  onDeletePod,
}) => {
  const labels = LABELS[kind];
  const [statusFilter, setStatusFilter] = useState<WorkloadStatus | "All">("All");
  const [selected, setSelected] = useState<{ namespace: string; name: string } | null>(null);
  const [modal, setModal] = useState<ModalState>(null);

  const { data, isFetching, isError, refetch } = useCachedWorkloads(kind, cluster.id, namespace || undefined);
  const isLoading = isFetching && !data;
  const syncResource = kind === "statefulset" ? "statefulsets" : "daemonsets";
  // Same three sync paths as the Deployments tab: background sync job, live-watch push, and the 5s cached poll.
  const backgroundSync = useAksBackgroundSync({
    resourceType: syncResource,
    clusterId: cluster.id,
    namespace: namespace || undefined,
    throttleMs: 10_000,
  });
  useAksLiveWatch({
    clusterId: cluster.id,
    namespace: namespace || undefined,
    resources: [syncResource],
  });
  const detail = useWorkloadDetail(kind, cluster.id, selected?.namespace, selected?.name, !!selected);
  const scaleMut = useScaleWorkload();
  const restartMut = useRestartWorkload();
  const imageMut = useUpdateWorkloadImage();
  const strategyMut = useUpdateWorkloadStrategy();
  const rollbackMut = useRollbackWorkload();
  const deleteMut = useDeleteWorkload();
  const busy =
    scaleMut.isPending || restartMut.isPending || imageMut.isPending || strategyMut.isPending ||
    rollbackMut.isPending || deleteMut.isPending;

  const allItems = useMemo(() => data?.items ?? [], [data]);

  const kpis = useMemo(() => {
    const count = (s: WorkloadStatus) => allItems.filter((i) => i.status === s).length;
    return {
      total: allItems.length,
      healthy: count("Healthy"),
      attention: count("Updating") + count("Degraded"),
      unavailable: count("Unavailable"),
      ready: allItems.reduce((n, i) => n + i.ready, 0),
      desired: allItems.reduce((n, i) => n + i.desired, 0),
    };
  }, [allItems]);

  const filteredByStatus = useMemo(
    () => (statusFilter === "All" ? allItems : allItems.filter((i) => i.status === statusFilter)),
    [allItems, statusFilter]
  );

  const accessor = useCallback((item: K8sWorkload, key: string): string | number => {
    switch (key) {
      case "namespace": return item.namespace.toLowerCase();
      case "status": return item.status.toLowerCase();
      case "ready": return item.desired ? item.ready / item.desired : 1;
      case "age": return item.created_at || "";
      default: return item.name.toLowerCase();
    }
  }, []);
  const { sort, setSort, sorted } = useGridSort(filteredByStatus, accessor, { key: "name", direction: "asc" });

  const searchFn = useCallback(
    (item: K8sWorkload, q: string) =>
      item.name.toLowerCase().includes(q) ||
      item.namespace.toLowerCase().includes(q) ||
      item.images.some((img) => img.toLowerCase().includes(q)),
    []
  );
  const { search, setSearch, page, setPage, paged, filtered, totalPages } = useSearchPagination(sorted, searchFn);

  const ref = (item: K8sWorkload) => ({ clusterId: cluster.id, kind, namespace: item.namespace, name: item.name });
  const done = (msg: string) => {
    showToast(msg);
    setModal(null);
    // Like Deployments: force a Kubernetes sync so the DB-backed grid reflects the change right away.
    backgroundSync.start(false);
  };
  const failed = (e: unknown, msg: string) => showToast(apiErrorDetail(e, msg), "error");

  const submitModal = () => {
    if (!modal) return;
    const item = modal.item;
    switch (modal.type) {
      case "scale":
        scaleMut.mutate({ ...ref(item), replicas: modal.replicas }, {
          onSuccess: () => done(`Scaling ${item.name} to ${modal.replicas} replicas`),
          onError: (e) => failed(e, "Scale failed"),
        });
        break;
      case "restart":
        restartMut.mutate(ref(item), {
          onSuccess: () => done(`Rolling restart started for ${item.name}`),
          onError: (e) => failed(e, "Restart failed"),
        });
        break;
      case "image":
        imageMut.mutate({ ...ref(item), container: modal.container, image: modal.image.trim() }, {
          onSuccess: () => done(`Updated ${modal.container} image on ${item.name}`),
          onError: (e) => failed(e, "Image update failed"),
        });
        break;
      case "strategy":
        strategyMut.mutate(
          {
            ...ref(item),
            strategyType: modal.strategyType,
            partition: kind === "statefulset" && modal.partition !== "" ? Number(modal.partition) : null,
            maxUnavailable: kind === "daemonset" ? modal.maxUnavailable.trim() : null,
            maxSurge: kind === "daemonset" ? modal.maxSurge.trim() : null,
          },
          {
            onSuccess: () => done(`Update strategy changed for ${item.name}`),
            onError: (e) => failed(e, "Strategy update failed"),
          }
        );
        break;
      case "rollback":
        rollbackMut.mutate({ ...ref(item), revision: modal.revision }, {
          onSuccess: () => done(`Rolling ${item.name} back to revision ${modal.revision}`),
          onError: (e) => failed(e, "Rollback failed"),
        });
        break;
      case "delete":
        deleteMut.mutate({ ...ref(item), propagationPolicy: modal.policy }, {
          onSuccess: () => {
            if (selected?.name === item.name && selected.namespace === item.namespace) setSelected(null);
            done(`Deleted ${labels.singular} ${item.name}`);
          },
          onError: (e) => failed(e, "Delete failed"),
        });
        break;
    }
  };

  const openStrategy = (item: K8sWorkload) =>
    setModal({
      type: "strategy",
      item,
      strategyType: item.update_strategy === "OnDelete" ? "OnDelete" : "RollingUpdate",
      partition: String(item.partition ?? 0),
      maxUnavailable: item.max_unavailable ?? "1",
      maxSurge: item.max_surge ?? "0",
    });

  const header = (label: string, key: string) => (
    <SortableHeader label={label} active={sort.key === key} direction={sort.direction} onClick={() => setSort(nextSortState(sort, key))} />
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold text-gray-800">{labels.plural}</h2>
        <div className="flex flex-wrap items-center gap-2">
          <NamespaceSelect namespaces={namespaces} value={namespace} onChange={onNamespaceChange} />
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value as WorkloadStatus | "All");
              setPage(1);
            }}
            className={gridStyles.toolbarInput}
            aria-label="Filter by status"
          >
            {STATUS_FILTERS.map((s) => (
              <option key={s} value={s}>{s === "All" ? "All Statuses" : s}</option>
            ))}
          </select>
          <SyncFromKubernetesButton sync={backgroundSync} title={`Refresh ${labels.plural} from Kubernetes`} />
        </div>
      </div>

      <CachedSyncStatus source={data?.source} lastSync={data?.last_sync} sync={backgroundSync} formatDate={formatDate} />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard title={labels.plural} value={kpis.total} icon={MetricCardIcons.layers()} subtitle={namespace ? `Namespace ${namespace}` : "All namespaces"} tone="att" />
        <MetricCard title="Healthy" value={kpis.healthy} icon={MetricCardIcons.checkCircle()} subtitle={`${kpis.ready}/${kpis.desired} pods ready`} tone="green" />
        <MetricCard title="Updating / Degraded" value={kpis.attention} icon={MetricCardIcons.activity()} subtitle="Rollout in progress or pods not ready" tone="amber" />
        <MetricCard title="Unavailable" value={kpis.unavailable} icon={MetricCardIcons.alert()} subtitle="No ready pods" tone="red" />
      </div>

      {isError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Unable to load {labels.plural} from this cluster.{" "}
          <button type="button" onClick={() => refetch()} className="underline font-medium">Try again</button>
        </div>
      )}

      <div className={gridStyles.shell}>
        <GridSearchBar
          search={search}
          onSearch={setSearch}
          onPage={setPage}
          totalItems={allItems.length}
          shownItems={filtered.length}
          placeholder={`Search ${labels.plural.toLowerCase()}, namespace, or image...`}
          isSyncing={isFetching || backgroundSync.isRunning}
        />
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}>{header("Name", "name")}</th>
                <th className={gridStyles.headerCell}>{header("Namespace", "namespace")}</th>
                <th className={gridStyles.headerCell}>{header("Status", "status")}</th>
                <th className={gridStyles.headerCell}>{header("Ready", "ready")}</th>
                <th className={gridStyles.headerCell}>Up-to-date</th>
                <th className={gridStyles.headerCell}>Available</th>
                {kind === "daemonset" && <th className={gridStyles.headerCell}>Node Selector</th>}
                <th className={gridStyles.headerCell}>Strategy</th>
                <th className={gridStyles.headerCell}>Images</th>
                <th className={gridStyles.headerCell}>{header("Age", "age")}</th>
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {paged.length === 0 && (
                <GridStateRow
                  colSpan={kind === "daemonset" ? 11 : 10}
                  isLoading={isLoading}
                  emptyText={
                    allItems.length === 0
                      ? `No ${labels.plural} found in ${namespace ? `namespace "${namespace}"` : "this cluster"}.`
                      : `No ${labels.plural} match the current filters`
                  }
                />
              )}
              {paged.map((item) => (
                <tr key={`${item.namespace}/${item.name}`} className={gridStyles.row}>
                  <td className={gridStyles.cell}>
                    <button
                      type="button"
                      onClick={() => setSelected({ namespace: item.namespace, name: item.name })}
                      className="font-medium text-blue-600 hover:text-blue-800 hover:underline text-left"
                    >
                      {item.name}
                    </button>
                  </td>
                  <td className={gridStyles.cell}>{item.namespace}</td>
                  <td className={gridStyles.cell}>
                    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${WORKLOAD_STATUS_STYLES[item.status] ?? "bg-gray-100 text-gray-700"}`}>
                      {item.status}
                    </span>
                  </td>
                  <td className={gridStyles.cell}>
                    <span className={`font-mono text-xs ${item.ready < item.desired ? "text-amber-700 font-semibold" : ""}`}>
                      {item.ready}/{item.desired}
                    </span>
                  </td>
                  <td className={gridStyles.cell}><span className="font-mono text-xs">{item.updated}</span></td>
                  <td className={gridStyles.cell}><span className="font-mono text-xs">{item.available}</span></td>
                  {kind === "daemonset" && (
                    <td className={gridStyles.cell}>
                      <span className="text-xs text-gray-600">
                        {Object.entries(item.node_selector).map(([k, v]) => `${k}=${v}`).join(", ") || "—"}
                      </span>
                    </td>
                  )}
                  <td className={gridStyles.cell}><span className="text-xs">{strategyLabel(item)}</span></td>
                  <td className={gridStyles.cell}>
                    <span className="font-mono text-xs text-gray-600 break-all" title={item.images.join("\n")}>
                      {item.images[0] ?? "—"}
                      {item.images.length > 1 && <span className="ml-1 text-gray-400">+{item.images.length - 1}</span>}
                    </span>
                  </td>
                  <td className={gridStyles.cell}><span className="font-mono text-xs">{formatAge(item.created_at)}</span></td>
                  <td className={gridStyles.centerCell}>
                    <div className="flex items-center justify-center gap-1">
                      <button type="button" title="View Details" onClick={() => setSelected({ namespace: item.namespace, name: item.name })} className={`${btn.icon} hover:bg-blue-50 text-blue-600`}>
                        {ActionIcons.view}
                      </button>
                      {canManage && kind === "statefulset" && (
                        <button type="button" title="Scale" disabled={busy} onClick={() => setModal({ type: "scale", item, replicas: item.desired })} className={`${btn.icon} hover:bg-att-50 text-att-600`}>
                          {ActionIcons.scale}
                        </button>
                      )}
                      {canManage && (
                        <>
                          <button type="button" title="Rolling Restart" disabled={busy} onClick={() => setModal({ type: "restart", item })} className={`${btn.icon} hover:bg-amber-50 text-amber-600`}>
                            {ActionIcons.restart}
                          </button>
                          <button type="button" title="Update Image" disabled={busy} onClick={() => setModal({ type: "image", item, container: item.containers[0]?.name ?? "", image: item.containers[0]?.image ?? "" })} className={`${btn.icon} hover:bg-indigo-50 text-indigo-600`}>
                            {ActionIcons.image}
                          </button>
                          <button type="button" title="Update Strategy" disabled={busy} onClick={() => openStrategy(item)} className={`${btn.icon} hover:bg-slate-100 text-slate-600`}>
                            {ActionIcons.strategy}
                          </button>
                        </>
                      )}
                      {canDelete && (
                        <button type="button" title={`Delete ${labels.singular}`} disabled={busy} onClick={() => setModal({ type: "delete", item, policy: "Background" })} className={`${btn.icon} hover:bg-red-50 text-red-600`}>
                          {ActionIcons.trash}
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <GridPager page={page} totalPages={totalPages} onPage={setPage} />
      </div>

      {selected && (
        <WorkloadDetailModal
          kind={kind}
          clusterId={cluster.id}
          target={selected}
          title={`${labels.singular}: ${selected.namespace}/${selected.name}`}
          detail={detail.data}
          isLoading={detail.isLoading}
          isError={detail.isError}
          formatDate={formatDate}
          canManage={canManage}
          canDeletePod={canDeletePod}
          logDownload={logDownload}
          onOpenPod={onOpenPod}
          onViewPodLogs={onViewPodLogs}
          onDeletePod={onDeletePod}
          onRollback={(item, revision) => setModal({ type: "rollback", item, revision })}
          onClose={() => setSelected(null)}
        />
      )}

      {modal && (
        <WorkloadActionModal
          kind={kind}
          modal={modal}
          setModal={setModal}
          busy={busy}
          onSubmit={submitModal}
        />
      )}
    </div>
  );
};

// ── Action modal ─────────────────────────────────────────────────────

function WorkloadActionModal({
  kind,
  modal,
  setModal,
  busy,
  onSubmit,
}: {
  kind: WorkloadKind;
  modal: NonNullable<ModalState>;
  setModal: (m: ModalState) => void;
  busy: boolean;
  onSubmit: () => void;
}) {
  const label = LABELS[kind].singular;
  const item = modal.item;
  const close = () => setModal(null);

  let title = "";
  let body: React.ReactNode = null;
  let confirmLabel = "Apply";
  let danger = false;
  let valid = true;

  switch (modal.type) {
    case "scale":
      title = `Scale ${label}`;
      valid = Number.isInteger(modal.replicas) && modal.replicas >= 0 && modal.replicas <= 100;
      body = (
        <>
          <p className="text-sm text-gray-600 mb-3">
            {item.name} currently has {item.desired} replica(s). StatefulSet pods are created and removed in ordinal
            order; scaling down does not delete their PersistentVolumeClaims
            {item.pvc_retention_policy?.when_scaled === "Delete" ? " (retention policy: Delete — PVCs WILL be removed)" : ""}.
          </p>
          <label className="block text-sm font-medium text-gray-700 mb-1">Replicas (0–100)</label>
          <input type="number" min={0} max={100} value={modal.replicas} onChange={(e) => setModal({ ...modal, replicas: Number(e.target.value) })} className={inputCls} />
        </>
      );
      confirmLabel = "Scale";
      break;
    case "restart":
      title = `Restart ${label}`;
      body = (
        <p className="text-sm text-gray-600">
          Trigger a rolling restart of {item.namespace}/{item.name}? Pods are replaced according to the{" "}
          {item.update_strategy ?? "current"} strategy.
          {item.update_strategy === "OnDelete" && " With OnDelete, pods are only replaced when you delete them manually."}
        </p>
      );
      confirmLabel = "Restart";
      break;
    case "image":
      title = `Update Container Image`;
      valid = !!modal.container && /^\S+$/.test(modal.image.trim());
      body = (
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Container</label>
            <select
              value={modal.container}
              onChange={(e) =>
                setModal({ ...modal, container: e.target.value, image: item.containers.find((c) => c.name === e.target.value)?.image ?? "" })
              }
              className={inputCls}
            >
              {item.containers.map((c) => (
                <option key={c.name} value={c.name}>{c.name}</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Image</label>
            <input type="text" value={modal.image} onChange={(e) => setModal({ ...modal, image: e.target.value })} className={`${inputCls} font-mono`} />
          </div>
          <p className="text-xs text-gray-500">Changing the image creates a new revision and starts a rollout.</p>
        </div>
      );
      break;
    case "strategy":
      title = `Update Strategy`;
      valid =
        kind === "statefulset"
          ? modal.partition === "" || /^\d+$/.test(modal.partition)
          : /^\d{1,3}%?$/.test(modal.maxUnavailable.trim() || "0") && /^\d{1,3}%?$/.test(modal.maxSurge.trim() || "0");
      body = (
        <div className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Type</label>
            <select value={modal.strategyType} onChange={(e) => setModal({ ...modal, strategyType: e.target.value as "RollingUpdate" | "OnDelete" })} className={inputCls}>
              <option value="RollingUpdate">RollingUpdate</option>
              <option value="OnDelete">OnDelete</option>
            </select>
          </div>
          {modal.strategyType === "RollingUpdate" && kind === "statefulset" && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Partition</label>
              <input type="number" min={0} value={modal.partition} onChange={(e) => setModal({ ...modal, partition: e.target.value })} className={inputCls} />
              <p className="mt-1 text-xs text-gray-500">Only pods with an ordinal ≥ partition are updated — use it for canary or staged rollouts.</p>
            </div>
          )}
          {modal.strategyType === "RollingUpdate" && kind === "daemonset" && (
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Max Unavailable</label>
                <input type="text" value={modal.maxUnavailable} onChange={(e) => setModal({ ...modal, maxUnavailable: e.target.value })} placeholder="1 or 10%" className={inputCls} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Max Surge</label>
                <input type="text" value={modal.maxSurge} onChange={(e) => setModal({ ...modal, maxSurge: e.target.value })} placeholder="0 or 10%" className={inputCls} />
              </div>
              <p className="col-span-2 text-xs text-gray-500">Kubernetes requires maxUnavailable to be 0 when maxSurge is set, and vice versa.</p>
            </div>
          )}
          {modal.strategyType === "OnDelete" && (
            <p className="text-xs text-amber-700">With OnDelete, template changes apply only when pods are deleted manually.</p>
          )}
        </div>
      );
      break;
    case "rollback":
      title = `Roll Back ${label}`;
      body = (
        <p className="text-sm text-gray-600">
          Roll {item.namespace}/{item.name} back to revision {modal.revision}? The pod template from that revision is
          re-applied and a new rollout starts.
        </p>
      );
      confirmLabel = "Roll Back";
      danger = true;
      break;
    case "delete":
      title = `Delete ${label}`;
      danger = true;
      confirmLabel = "Delete";
      body = (
        <div className="space-y-3">
          <p className="text-sm text-gray-600">
            Permanently delete {label} "{item.name}" from namespace "{item.namespace}"? Current status: {item.status}.
          </p>
          {kind === "statefulset" && (
            <p className="text-sm text-amber-700">
              PersistentVolumeClaims created from volume claim templates are
              {item.pvc_retention_policy?.when_deleted === "Delete" ? " deleted with it (retention policy: Delete)." : " retained and must be cleaned up separately."}
            </p>
          )}
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Pods</label>
            <select value={modal.policy} onChange={(e) => setModal({ ...modal, policy: e.target.value as "Background" | "Orphan" })} className={inputCls}>
              <option value="Background">Delete pods (cascade)</option>
              <option value="Orphan">Keep pods running (orphan)</option>
            </select>
          </div>
        </div>
      );
      break;
  }

  return (
    <ModalShell title={title} onClose={close}>
      <div className="space-y-4">
        {body}
        <div className="flex justify-end gap-2">
          <button type="button" onClick={close} className={btn.secondary}>Cancel</button>
          <button type="button" disabled={busy || !valid} onClick={onSubmit} className={danger ? btn.danger : btn.primary}>
            {busy ? "Working..." : confirmLabel}
          </button>
        </div>
      </div>
    </ModalShell>
  );
}

// ── Detail modal ─────────────────────────────────────────────────────

type DetailSection = "overview" | "pods" | "revisions" | "volumes" | "events" | "yaml";

function WorkloadDetailModal({
  kind,
  clusterId,
  target,
  title,
  detail,
  isLoading,
  isError,
  formatDate,
  canManage,
  canDeletePod,
  logDownload,
  onOpenPod,
  onViewPodLogs,
  onDeletePod,
  onRollback,
  onClose,
}: {
  kind: WorkloadKind;
  clusterId: string;
  target: { namespace: string; name: string };
  title: string;
  detail: WorkloadDetail | undefined;
  isLoading: boolean;
  isError: boolean;
  formatDate: (value: string) => string;
  canManage: boolean;
  canDeletePod: boolean;
  logDownload: LogArchiveDownload;
  onOpenPod?: (pod: WorkloadPod) => void;
  onViewPodLogs: (pod: WorkloadPod) => void;
  onDeletePod?: (pod: WorkloadPod) => void;
  onRollback: (item: K8sWorkload, revision: number) => void;
  onClose: () => void;
}) {
  const [section, setSection] = useState<DetailSection>("overview");
  const sections: { key: DetailSection; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "pods", label: `Pods${detail ? ` (${detail.pods.length})` : ""}` },
    { key: "revisions", label: "Revisions" },
    ...(kind === "statefulset" ? [{ key: "volumes" as const, label: "Volumes" }] : []),
    { key: "events", label: `Events${detail ? ` (${detail.events.length})` : ""}` },
    { key: "yaml", label: "YAML" },
  ];
  const fmt = (v: string | null | undefined) => (v ? formatDate(v) : "—");
  const kv = (label: string, value: React.ReactNode) => <KeyValue label={label} value={value} />;

  return (
    <ModalShell title={title} onClose={onClose} wide>
      {isLoading && <p className="text-sm text-gray-500">Loading…</p>}
      {isError && <p className="text-sm text-red-600">Failed to load details.</p>}
      {detail && (
        <div className="space-y-4">
          <div className="flex justify-end">
            <DownloadLogsButton
              download={logDownload}
              downloadKey={`${kind}:${target.namespace}/${target.name}`}
              request={{ clusterId, kind, namespace: target.namespace, name: target.name }}
              label={`${LABELS[kind].singular} ${target.namespace}/${target.name}`}
              podCount={detail.pods.length}
            />
          </div>
          <DetailTabs tabs={sections} active={section} onChange={setSection} />

          {section === "overview" && (
            <div className="grid grid-cols-1 gap-x-6 md:grid-cols-2">
              <div>
                {kv("Status", <span className={`px-2 py-0.5 rounded-full text-xs ${WORKLOAD_STATUS_STYLES[detail.status]}`}>{detail.status}</span>)}
                {kv("Ready / Desired", `${detail.ready}/${detail.desired}`)}
                {kv("Up-to-date", detail.updated)}
                {kv("Available", detail.available)}
                {kv("Strategy", strategyLabel(detail))}
                {kv("Min Ready Seconds", detail.min_ready_seconds)}
                {kv("Generation", `${detail.observed_generation ?? "—"} / ${detail.generation ?? "—"}`)}
                {kv("Created", fmt(detail.created_at))}
              </div>
              <div>
                {kind === "statefulset" ? (
                  <>
                    {kv("Service", detail.service_name)}
                    {kv("Pod Management", detail.pod_management_policy)}
                    {kv("Current Revision", detail.current_revision)}
                    {kv("Update Revision", detail.update_revision)}
                    {kv("PVC Retention", detail.pvc_retention_policy ? `deleted: ${detail.pvc_retention_policy.when_deleted}, scaled: ${detail.pvc_retention_policy.when_scaled}` : "Retain (default)")}
                  </>
                ) : (
                  <>
                    {kv("Unavailable", detail.unavailable)}
                    {kv("Misscheduled", detail.misscheduled)}
                    {kv("Tolerations", detail.tolerations)}
                    {kv("Node Selector", Object.entries(detail.node_selector).map(([k, v]) => `${k}=${v}`).join(", ") || "—")}
                  </>
                )}
                {kv("Service Account", detail.service_account)}
                {kv("CPU req / limit", `${detail.cpu_request || "—"} / ${detail.cpu_limit || "—"}`)}
                {kv("Memory req / limit", `${detail.memory_request || "—"} / ${detail.memory_limit || "—"}`)}
              </div>
              <div className="md:col-span-2 mt-3">
                <h4 className={gridStyles.sectionTitle}>Containers</h4>
                <ul className="mt-1 space-y-1">
                  {detail.containers.map((c) => (
                    <li key={c.name} className="text-sm"><span className="font-medium">{c.name}</span> <span className="font-mono text-xs text-gray-600">{c.image}</span></li>
                  ))}
                </ul>
              </div>
              {detail.conditions.length > 0 && (
                <div className="md:col-span-2 mt-3">
                  <h4 className={gridStyles.sectionTitle}>Conditions</h4>
                  <ul className="mt-1 space-y-1 text-sm">
                    {detail.conditions.map((c) => (
                      <li key={c.type}><span className="font-medium">{c.type}</span>={c.status} {c.reason && <span className="text-gray-500">({c.reason})</span>} {c.message}</li>
                    ))}
                  </ul>
                </div>
              )}
              {kind === "statefulset" && (detail.volume_claim_templates?.length ?? 0) > 0 && (
                <div className="md:col-span-2 mt-3">
                  <h4 className={gridStyles.sectionTitle}>Volume Claim Templates</h4>
                  <ul className="mt-1 space-y-1 text-sm">
                    {detail.volume_claim_templates!.map((t) => (
                      <li key={t.name}>{t.name}: {t.storage ?? "?"} · {t.storage_class ?? "default class"} · {t.access_modes.join(", ")}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}

          {section === "pods" && (
            <WorkloadPodsTable
              pods={detail.pods}
              onOpenPod={onOpenPod}
              onViewPodLogs={onViewPodLogs}
              onDeletePod={onDeletePod}
              canDeletePod={canDeletePod}
            />
          )}

          {section === "revisions" && (
            <table className={gridStyles.table}>
              <thead className={gridStyles.head}>
                <tr>
                  <th className={gridStyles.headerCell}>Revision</th>
                  <th className={gridStyles.headerCell}>Name</th>
                  <th className={gridStyles.headerCell}>Images</th>
                  <th className={gridStyles.headerCell}>Created</th>
                  <th className={gridStyles.headerCellCenter}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {detail.revisions.length === 0 && <GridStateRow colSpan={5} emptyText="No revision history" />}
                {detail.revisions.map((r) => (
                  <tr key={r.name} className={gridStyles.row}>
                    <td className={gridStyles.cell}>
                      {r.revision}
                      {r.is_current && <span className="ml-2 px-1.5 py-0.5 rounded bg-green-100 text-green-700 text-[10px] font-medium">current</span>}
                    </td>
                    <td className={gridStyles.cell}><span className="font-mono text-xs">{r.name}</span></td>
                    <td className={gridStyles.cell}><span className="font-mono text-xs break-all">{r.images.join(", ") || "—"}</span></td>
                    <td className={gridStyles.cell}><span className="text-xs">{fmt(r.created_at)}</span></td>
                    <td className={gridStyles.centerCell}>
                      {canManage && !r.is_current && (
                        <button type="button" onClick={() => onRollback(detail, r.revision)} className="text-sm text-att-600 hover:underline">
                          Roll back
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {section === "volumes" && (
            <table className={gridStyles.table}>
              <thead className={gridStyles.head}>
                <tr>
                  <th className={gridStyles.headerCell}>PVC</th>
                  <th className={gridStyles.headerCell}>Phase</th>
                  <th className={gridStyles.headerCell}>Capacity</th>
                  <th className={gridStyles.headerCell}>Storage Class</th>
                  <th className={gridStyles.headerCell}>Volume</th>
                </tr>
              </thead>
              <tbody>
                {(detail.pvcs ?? []).length === 0 && <GridStateRow colSpan={5} emptyText="No PersistentVolumeClaims" />}
                {(detail.pvcs ?? []).map((v) => (
                  <tr key={v.name} className={gridStyles.row}>
                    <td className={gridStyles.cell}>{v.name}</td>
                    <td className={gridStyles.cell}>{v.phase ?? "—"}</td>
                    <td className={gridStyles.cell}>{v.capacity ?? "—"}</td>
                    <td className={gridStyles.cell}>{v.storage_class ?? "—"}</td>
                    <td className={gridStyles.cell}><span className="font-mono text-xs">{v.volume_name ?? "—"}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}

          {section === "events" && <EventList events={detail.events} formatDate={formatDate} />}

          {section === "yaml" && <YamlView yaml={detail.yaml} />}
        </div>
      )}
    </ModalShell>
  );
}

export default WorkloadsTab;
