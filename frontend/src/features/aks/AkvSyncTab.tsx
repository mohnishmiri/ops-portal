/**
 * AKV Sync tab — Azure Key Vault → AKS sync status for akv2k8s `AzureKeyVaultSecret` (`kubectl get akvs`).
 *
 * One row per AzureKeyVaultSecret: the Key Vault object it reads, the Secret or
 * ConfigMap it writes, when the controller last synced it, and its latest
 * controller event. Like Deployments, the grid reads the DB inventory and a
 * background job refreshes it from the cluster. Secret values are never returned.
 */

import React, { useCallback, useMemo, useState } from "react";
import { gridStyles, SortableHeader, nextSortState } from "../../components/gridStyles";
import { MetricCard, MetricCardIcons } from "../../components/MetricCard";
import {
  AKSCluster,
  AkvsItem,
  AkvsStatus,
  AkvsVaultCheck,
  useAksBackgroundSync,
  useAkvsController,
  useAkvsDetail,
  useAkvsVaultCheck,
  useCachedAkvs,
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

type AkvSyncTabProps = {
  cluster: AKSCluster;
  namespace: string;
  namespaces: string[];
  onNamespaceChange: (ns: string) => void;
  showToast: (msg: string, type?: "success" | "error") => void;
  formatDate: (value: string) => string;
};

const STATUS_STYLES: Record<AkvsStatus, string> = {
  Synced: "bg-green-100 text-green-700",
  Failed: "bg-red-100 text-red-700",
  Degraded: "bg-amber-100 text-amber-700",
  Pending: "bg-blue-100 text-blue-700",
  EnvInjector: "bg-indigo-100 text-indigo-700",
};

const STATUS_LABELS: Record<AkvsStatus, string> = {
  Synced: "Synced",
  Failed: "Failed",
  Degraded: "Degraded",
  Pending: "Pending",
  EnvInjector: "Env Injector",
};

const STATUS_FILTERS: (AkvsStatus | "All")[] = ["All", "Synced", "Failed", "Degraded", "Pending", "EnvInjector"];

function errorDetail(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : fallback;
}

function StatusPill({ status }: { status: AkvsStatus }) {
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[status] ?? "bg-gray-100 text-gray-700"}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

function outputLabel(item: AkvsItem): string {
  if (item.output_kind === "env-injection") return "Env injection";
  const key = item.output_data_key ? ` : ${item.output_data_key}` : "";
  return `${item.output_kind === "configmap" ? "ConfigMap" : "Secret"} ${item.output_name}${key}`;
}

export const AkvSyncTab: React.FC<AkvSyncTabProps> = ({
  cluster,
  namespace,
  namespaces,
  onNamespaceChange,
  showToast,
  formatDate,
}) => {
  const [statusFilter, setStatusFilter] = useState<AkvsStatus | "All">("All");
  const [selected, setSelected] = useState<{ namespace: string; name: string } | null>(null);

  const nsFilter = namespace || undefined;
  const { data, isFetching, isError, refetch } = useCachedAkvs(cluster.id, nsFilter);
  const controller = useAkvsController(cluster.id);
  // Same three sync paths as the Deployments tab: background sync job, live-watch push, and the cached poll.
  const backgroundSync = useAksBackgroundSync({
    resourceType: "akvs",
    clusterId: cluster.id,
    namespace: nsFilter,
    throttleMs: 10_000,
  });
  useAksLiveWatch({ clusterId: cluster.id, namespace: nsFilter, resources: ["akvs"] });
  const isLoading = isFetching && !data;
  const allItems = useMemo(() => data?.items ?? [], [data]);
  const summary = data?.summary;

  const filteredByStatus = useMemo(
    () => (statusFilter === "All" ? allItems : allItems.filter((i) => i.status === statusFilter)),
    [allItems, statusFilter]
  );

  const accessor = useCallback((item: AkvsItem, key: string): string | number => {
    switch (key) {
      case "namespace": return item.namespace.toLowerCase();
      case "status": return item.status.toLowerCase();
      case "vault": return (item.vault_name ?? "").toLowerCase();
      case "output": return (item.output_name ?? "").toLowerCase();
      case "synced": return item.last_azure_update ?? "";
      default: return item.name.toLowerCase();
    }
  }, []);
  const { sort, setSort, sorted } = useGridSort(filteredByStatus, accessor, { key: "status", direction: "asc" });

  const searchFn = useCallback(
    (item: AkvsItem, q: string) =>
      item.name.toLowerCase().includes(q) ||
      item.namespace.toLowerCase().includes(q) ||
      (item.vault_name ?? "").toLowerCase().includes(q) ||
      (item.object_name ?? "").toLowerCase().includes(q) ||
      (item.output_name ?? "").toLowerCase().includes(q) ||
      (item.output_data_key ?? "").toLowerCase().includes(q),
    []
  );
  const { search, setSearch, page, setPage, paged, filtered, totalPages } = useSearchPagination(sorted, searchFn);

  const header = (label: string, key: string) => (
    <SortableHeader label={label} active={sort.key === key} direction={sort.direction} onClick={() => setSort(nextSortState(sort, key))} />
  );

  const ctl = controller.data;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-xl font-semibold text-gray-800">AKV Secret Sync</h2>
          <p className="text-sm text-gray-500">Azure Key Vault → AKS sync status (akv2k8s AzureKeyVaultSecret)</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <NamespaceSelect namespaces={namespaces} value={namespace} onChange={onNamespaceChange} />
          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value as AkvsStatus | "All");
              setPage(1);
            }}
            className={gridStyles.toolbarInput}
            aria-label="Filter by sync status"
          >
            {STATUS_FILTERS.map((s) => (
              <option key={s} value={s}>{s === "All" ? "All Statuses" : STATUS_LABELS[s]}</option>
            ))}
          </select>
          <SyncFromKubernetesButton sync={backgroundSync} title="Refresh AzureKeyVaultSecrets from Kubernetes" />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 text-xs">
        {ctl && (
          <span className={`px-2 py-1 rounded-full font-medium ${ctl.installed ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-600"}`}>
            akv2k8s: {ctl.installed == null ? "Unknown" : ctl.installed ? `Installed (${ctl.versions.join(", ")})` : "Not installed"}
          </span>
        )}
        {ctl?.components.map((c) => (
          <span
            key={c.component}
            title={c.image ?? undefined}
            className={`px-2 py-1 rounded-full font-medium ${c.ready === c.pods && c.pods > 0 ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"}`}
          >
            {c.component}: {c.ready}/{c.pods} ready ({c.namespace})
          </span>
        ))}
      </div>

      {ctl && ctl.installed === false && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          akv2k8s is not installed on this cluster (no <code>azurekeyvaultsecrets.spv.no</code> CRD), so no
          AzureKeyVaultSecret objects can be synced.
        </div>
      )}

      <CachedSyncStatus source={data?.source} lastSync={data?.last_sync} sync={backgroundSync} formatDate={formatDate} />

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard title="AzureKeyVaultSecrets" value={summary?.total ?? 0} icon={MetricCardIcons.shield()} subtitle={`${summary?.vaults ?? 0} Key Vault(s) · ${summary?.outputs ?? 0} outputs`} tone="att" />
        <MetricCard title="Synced" value={summary?.Synced ?? 0} icon={MetricCardIcons.checkCircle()} subtitle="Key Vault object written to Kubernetes" tone="green" />
        <MetricCard title="Failed / Degraded" value={(summary?.Failed ?? 0) + (summary?.Degraded ?? 0)} icon={MetricCardIcons.alert()} subtitle="Vault read errors or missing output keys" tone="red" />
        <MetricCard title="Pending / Env Injector" value={(summary?.Pending ?? 0) + (summary?.EnvInjector ?? 0)} icon={MetricCardIcons.cloud()} subtitle="Not yet synced, or injected into pods" tone="slate" />
      </div>

      {isError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Unable to load secret sync status.{" "}
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
          placeholder="Search name, vault, object, or output secret..."
          isSyncing={isFetching || backgroundSync.isRunning}
        />
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}>{header("Name", "name")}</th>
                <th className={gridStyles.headerCell}>{header("Namespace", "namespace")}</th>
                <th className={gridStyles.headerCell}>{header("Status", "status")}</th>
                <th className={gridStyles.headerCell}>{header("Key Vault", "vault")}</th>
                <th className={gridStyles.headerCell}>Vault Object</th>
                <th className={gridStyles.headerCell}>{header("Output", "output")}</th>
                <th className={gridStyles.headerCell}>{header("Last Azure Sync", "synced")}</th>
                <th className={gridStyles.headerCell}>Last Event</th>
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {paged.length === 0 && (
                <GridStateRow
                  colSpan={9}
                  isLoading={isLoading}
                  emptyText={
                    !data?.last_sync
                      ? "Not synced yet — syncing from the cluster..."
                      : allItems.length === 0
                        ? `No AzureKeyVaultSecrets found in ${namespace ? `namespace "${namespace}"` : "this cluster"}.`
                        : "No AzureKeyVaultSecrets match the current filters"
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
                    <span title={item.status_reason}><StatusPill status={item.status} /></span>
                  </td>
                  <td className={gridStyles.cell}><span className="font-mono text-xs">{item.vault_name ?? "—"}</span></td>
                  <td className={gridStyles.cell}>
                    <span className="text-xs">
                      {item.object_name}
                      <span className="ml-1 text-gray-400">({item.object_type}{item.object_version ? ` @ ${item.object_version.slice(0, 8)}` : ""})</span>
                    </span>
                  </td>
                  <td className={gridStyles.cell}>
                    <span className={`text-xs ${item.output_exists === false || item.key_present === false ? "text-amber-700 font-semibold" : ""}`}>
                      {outputLabel(item)}
                    </span>
                  </td>
                  <td className={gridStyles.cell}>
                    <span className="text-xs text-gray-600">{item.last_azure_update ? formatDate(item.last_azure_update) : "—"}</span>
                  </td>
                  <td className={gridStyles.cell}>
                    {item.last_event ? (
                      <span
                        title={item.last_event.message ?? undefined}
                        className={`text-xs ${item.last_event.type === "Warning" ? "text-red-600" : "text-gray-600"}`}
                      >
                        {item.last_event.reason}
                        {item.last_event.last_seen && <span className="text-gray-400"> · {formatDate(item.last_event.last_seen)}</span>}
                      </span>
                    ) : (
                      <span className="text-xs text-gray-400">—</span>
                    )}
                  </td>
                  <td className={gridStyles.centerCell}>
                    <button
                      type="button"
                      onClick={() => setSelected({ namespace: item.namespace, name: item.name })}
                      className="text-sm text-blue-600 hover:underline"
                    >
                      Details
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <GridPager page={page} totalPages={totalPages} onPage={setPage} />
      </div>

      {selected && (
        <AkvsDetailModal
          clusterId={cluster.id}
          namespace={selected.namespace}
          name={selected.name}
          formatDate={formatDate}
          showToast={showToast}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
};

function AkvsDetailModal({
  clusterId,
  namespace,
  name,
  formatDate,
  showToast,
  onClose,
}: {
  clusterId: string;
  namespace: string;
  name: string;
  formatDate: (value: string) => string;
  showToast: (msg: string, type?: "success" | "error") => void;
  onClose: () => void;
}) {
  const { data: item, isLoading, isError } = useAkvsDetail(clusterId, namespace, name);
  const vaultCheckMut = useAkvsVaultCheck();
  const [vaultCheck, setVaultCheck] = useState<AkvsVaultCheck | null>(null);
  const fmt = (v: string | null | undefined) => (v ? formatDate(v) : "—");

  const runVaultCheck = () =>
    vaultCheckMut.mutate(
      { clusterId, namespace, name },
      {
        onSuccess: (res) => setVaultCheck(res.vault_check ?? null),
        onError: (e) => showToast(errorDetail(e, "Key Vault comparison failed"), "error"),
      }
    );

  const kv = (label: string, value: React.ReactNode) => (
    <div key={label} className="flex justify-between gap-4 border-b border-att-100 py-1.5">
      <span className="text-gray-500">{label}</span>
      <span className="text-right font-medium text-gray-800 break-all">{value ?? "—"}</span>
    </div>
  );

  return (
    <ModalShell title={`AzureKeyVaultSecret: ${namespace}/${name}`} onClose={onClose} wide>
      {isLoading && <p className="text-sm text-gray-500">Loading…</p>}
      {isError && <p className="text-sm text-red-600">Failed to load sync details.</p>}
      {item && (
        <div className="space-y-5">
          <div className="flex flex-wrap items-center gap-2">
            <StatusPill status={item.status} />
            <span className="text-sm text-gray-600 break-all">{item.status_reason}</span>
          </div>

          <div className="grid grid-cols-1 gap-x-6 text-sm md:grid-cols-2">
            <div>
              {kv("Key Vault", item.vault_name)}
              {kv("Object", item.object_name)}
              {kv("Object Type", item.object_type)}
              {kv("Version", item.object_version ?? "latest")}
              {item.content_type && kv("Content Type", item.content_type)}
              {kv("Last Azure Sync", fmt(item.last_azure_update))}
            </div>
            <div>
              {kv("Output", outputLabel(item))}
              {item.output_type && kv("Output Type", item.output_type)}
              {kv("Transforms", item.transforms.length ? item.transforms.join(", ") : "—")}
              {kv(
                "Output Exists",
                item.output_exists == null ? "n/a" : item.output_exists ? "Yes" : <span className="text-red-600">No</span>
              )}
              {kv("Content Hash", <span className="font-mono text-xs">{item.secret_hash ?? "—"}</span>)}
              {kv("Created", fmt(item.created_at))}
            </div>
          </div>

          {item.output_kind !== "env-injection" && (
            <section>
              <h4 className={gridStyles.sectionTitle}>
                Keys in {item.output_kind === "configmap" ? "ConfigMap" : "Secret"} {item.output_name}
              </h4>
              <div className="mt-2 flex flex-wrap gap-1">
                {item.output_keys.length === 0 && <span className="text-sm text-gray-400">No keys found.</span>}
                {item.output_keys.map((k) => (
                  <span
                    key={k}
                    className={`rounded px-1.5 py-0.5 text-xs ${k === item.output_data_key ? "bg-green-100 text-green-700 font-semibold" : "bg-att-50 text-att-700"}`}
                  >
                    {k}
                  </span>
                ))}
                {item.output_data_key && !item.output_keys.includes(item.output_data_key) && (
                  <span className="rounded bg-red-100 px-1.5 py-0.5 text-xs text-red-700">{item.output_data_key} (missing)</span>
                )}
              </div>
            </section>
          )}

          <section>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <h4 className={gridStyles.sectionTitle}>Key Vault Comparison</h4>
              <button
                type="button"
                onClick={runVaultCheck}
                disabled={vaultCheckMut.isPending}
                className="px-3 py-1.5 bg-att-500 text-white rounded-lg text-sm hover:bg-att-600 disabled:opacity-50"
              >
                {vaultCheckMut.isPending ? "Checking Key Vault..." : "Compare with Key Vault"}
              </button>
            </div>
            {!vaultCheck && (
              <p className="mt-2 text-sm text-gray-500">
                Checks whether Key Vault has a newer version than the last time akv2k8s synced this object.
              </p>
            )}
            {vaultCheck && (vaultCheck.error || !vaultCheck.checked) && (
              <p className="mt-2 text-sm text-amber-700 break-all">{vaultCheck.error}</p>
            )}
            {vaultCheck?.checked && vaultCheck.latest_version && (
              <div className="mt-2 grid grid-cols-1 gap-x-6 text-sm md:grid-cols-2">
                <div>
                  {kv("Newest Version", <span className="font-mono text-xs">{vaultCheck.latest_version}</span>)}
                  {kv("Version Created", fmt(vaultCheck.latest_version_created))}
                  {kv("Version Expires", fmt(vaultCheck.latest_version_expires))}
                </div>
                <div>
                  {kv("Last Azure Sync", fmt(item.last_azure_update))}
                  {kv(
                    "In Sync",
                    vaultCheck.in_sync === true ? (
                      <span className="px-2 py-0.5 rounded-full text-xs bg-green-100 text-green-700">Yes</span>
                    ) : vaultCheck.in_sync === false ? (
                      <span className="px-2 py-0.5 rounded-full text-xs bg-red-100 text-red-700">Newer version not synced</span>
                    ) : (
                      <span className="text-xs text-gray-500">{vaultCheck.pinned_version ? "Pinned version" : "Unknown"}</span>
                    )
                  )}
                  {kv("Checked", fmt(vaultCheck.checked_at))}
                </div>
              </div>
            )}
          </section>

          <section>
            <h4 className={gridStyles.sectionTitle}>Controller Events</h4>
            <ul className="mt-2 space-y-2">
              {item.events.length === 0 && <li className="text-sm text-gray-400">No recent events (Kubernetes keeps events for about an hour).</li>}
              {item.events.map((ev, i) => (
                <li key={i} className={`rounded-lg border px-3 py-2 text-sm ${ev.type === "Warning" ? "border-red-200 bg-red-50" : "border-att-100"}`}>
                  <div className="flex justify-between gap-2">
                    <span className={`font-medium ${ev.type === "Warning" ? "text-red-800" : "text-gray-800"}`}>
                      {ev.reason}
                      {ev.count > 1 && <span className="text-gray-500"> ×{ev.count}</span>}
                    </span>
                    <span className="text-xs text-gray-500">{fmt(ev.last_seen)}</span>
                  </div>
                  <p className="text-gray-700 break-all">{ev.message}</p>
                </li>
              ))}
            </ul>
          </section>
        </div>
      )}
    </ModalShell>
  );
}

export default AkvSyncTab;
