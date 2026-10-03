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
import { DetailGrid } from "./DetailGrid";
import { EventsGrid, formatAge, KeyValueGrid } from "./detailShared";
import { DetailCard, KpiRow, PropertyList, ResourceDetailShell, ResourceKindIcons } from "./ResourceDetailShell";

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

type AkvsSection = "overview" | "keys" | "events" | "metadata";

const STATUS_NOTICE: Record<AkvsStatus, string> = {
  Synced: "border-green-200 bg-green-50 text-green-800",
  Failed: "border-red-200 bg-red-50 text-red-800",
  Degraded: "border-amber-200 bg-amber-50 text-amber-800",
  Pending: "border-blue-200 bg-blue-50 text-blue-800",
  EnvInjector: "border-indigo-200 bg-indigo-50 text-indigo-800",
};

const STATUS_TONE: Record<AkvsStatus, "green" | "red" | "amber" | "blue" | "indigo"> = {
  Synced: "green",
  Failed: "red",
  Degraded: "amber",
  Pending: "blue",
  EnvInjector: "indigo",
};

export function AkvsDetailModal({
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
  const [section, setSection] = useState<AkvsSection>("overview");
  const fmt = (v: string | null | undefined) => (v ? formatDate(v) : null);

  const runVaultCheck = () =>
    vaultCheckMut.mutate(
      { clusterId, namespace, name },
      {
        onSuccess: (res) => setVaultCheck(res.vault_check ?? null),
        onError: (e) => showToast(errorDetail(e, "Key Vault comparison failed"), "error"),
      }
    );

  const hasOutputKeys = !!item && item.output_kind !== "env-injection";
  const keyRows = useMemo(() => {
    if (!item) return [];
    const rows = item.output_keys.map((key) => ({ key, role: key === item.output_data_key ? "synced" : "other" }));
    if (item.output_data_key && !item.output_keys.includes(item.output_data_key)) {
      rows.push({ key: item.output_data_key, role: "missing" });
    }
    return rows;
  }, [item]);
  const warnings = (item?.events ?? []).filter((e) => e.type === "Warning").length;
  const outputKind = item?.output_kind === "configmap" ? "ConfigMap" : "Secret";

  return (
    <ResourceDetailShell
      kind="AzureKeyVaultSecret"
      name={name}
      namespace={namespace}
      icon={ResourceKindIcons.keyvault}
      status={item && <StatusPill status={item.status} />}
      meta={
        item && (
          <>
            <span>
              Key Vault <span className="font-mono text-slate-700">{item.vault_name ?? "—"}</span> / <span className="font-mono text-slate-700">{item.object_name ?? "—"}</span>
            </span>
            <span>→ {outputLabel(item)}</span>
          </>
        )
      }
      tabs={[
        { key: "overview", label: "Overview" },
        ...(hasOutputKeys ? [{ key: "keys" as const, label: "Output Keys", count: keyRows.length, attention: keyRows.some((r) => r.role === "missing") }] : []),
        { key: "events", label: "Controller Events", count: item?.events.length, attention: warnings > 0 },
        { key: "metadata", label: "Metadata" },
      ]}
      activeTab={section}
      onTabChange={setSection}
      isLoading={isLoading}
      error={isError && !item ? "Failed to load sync details." : null}
      onClose={onClose}
    >
      {item && section === "overview" && (
        <>
          {item.status_reason && (
            <div className={`rounded-xl border px-4 py-3 text-sm break-words ${STATUS_NOTICE[item.status] ?? "border-slate-200 bg-slate-50 text-slate-700"}`}>
              {item.status_reason}
            </div>
          )}
          <KpiRow>
            <MetricCard title="Sync Status" value={STATUS_LABELS[item.status] ?? item.status} subtitle={item.last_event?.reason ?? "No recent controller event"} icon={MetricCardIcons.activity()} tone={STATUS_TONE[item.status] ?? "slate"} valueClassName="text-xl" />
            <MetricCard
              title="Output"
              value={item.output_kind === "env-injection" ? "Env" : item.output_exists == null ? "n/a" : item.output_exists ? "Present" : "Missing"}
              subtitle={item.output_kind === "env-injection" ? "Injected into pod environment" : `${outputKind} ${item.output_name ?? ""}`}
              icon={MetricCardIcons.shield()}
              tone={item.output_exists === false ? "red" : "att"}
              valueClassName="text-xl"
            />
            <MetricCard
              title="Output Keys"
              value={hasOutputKeys ? item.output_keys.length : "—"}
              subtitle={item.output_data_key ? `Data key ${item.output_data_key}${item.key_present === false ? " (missing)" : ""}` : "All keys from the object"}
              icon={MetricCardIcons.layers()}
              tone={item.key_present === false ? "red" : "indigo"}
            />
            <MetricCard
              title="Last Azure Sync"
              value={formatAge(item.last_azure_update)}
              subtitle={fmt(item.last_azure_update) ?? "Never synced"}
              icon={MetricCardIcons.calendar()}
              tone={item.last_azure_update ? "att" : "amber"}
            />
          </KpiRow>

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <DetailCard title="Azure Key Vault Source">
              <PropertyList
                items={[
                  { label: "Key Vault", value: item.vault_name, mono: true },
                  { label: "Object", value: item.object_name, mono: true },
                  { label: "Object Type", value: item.object_type },
                  { label: "Version", value: item.object_version ?? "latest", mono: true },
                  item.content_type && { label: "Content Type", value: item.content_type },
                  { label: "Last Azure Sync", value: fmt(item.last_azure_update) },
                ]}
              />
            </DetailCard>
            <DetailCard title="Kubernetes Target">
              <PropertyList
                items={[
                  { label: "Output", value: outputLabel(item), wide: true },
                  item.output_type && { label: "Output Type", value: item.output_type },
                  {
                    label: "Output Exists",
                    value: item.output_exists == null ? "n/a" : item.output_exists ? "Yes" : <span className="font-semibold text-red-600">No</span>,
                  },
                  { label: "Transforms", value: item.transforms.length ? item.transforms.join(", ") : null },
                  { label: "Content Hash", value: item.secret_hash, mono: true, wide: true },
                  { label: "Created", value: fmt(item.created_at) },
                ]}
              />
            </DetailCard>
          </div>

          <DetailCard
            title="Key Vault Comparison"
            subtitle="Checks whether Key Vault has a newer version than the one akv2k8s last synced."
            actions={
              <button
                type="button"
                onClick={runVaultCheck}
                disabled={vaultCheckMut.isPending}
                className="rounded-lg bg-att-500 px-3 py-1.5 text-sm text-white hover:bg-att-600 disabled:opacity-50"
              >
                {vaultCheckMut.isPending ? "Checking Key Vault..." : "Compare with Key Vault"}
              </button>
            }
          >
            {!vaultCheck && <p className="text-sm text-slate-500">Not checked yet.</p>}
            {vaultCheck && (vaultCheck.error || !vaultCheck.checked) && <p className="text-sm text-amber-700 break-all">{vaultCheck.error}</p>}
            {vaultCheck?.checked && vaultCheck.latest_version && (
              <PropertyList
                items={[
                  {
                    label: "In Sync",
                    value:
                      vaultCheck.in_sync === true ? (
                        <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-700">Yes</span>
                      ) : vaultCheck.in_sync === false ? (
                        <span className="rounded-full bg-red-100 px-2 py-0.5 text-xs font-semibold text-red-700">Newer version not synced</span>
                      ) : (
                        <span className="text-xs text-slate-500">{vaultCheck.pinned_version ? "Pinned version" : "Unknown"}</span>
                      ),
                  },
                  { label: "Checked", value: fmt(vaultCheck.checked_at) },
                  { label: "Newest Version", value: vaultCheck.latest_version, mono: true, wide: true },
                  { label: "Version Created", value: fmt(vaultCheck.latest_version_created) },
                  { label: "Version Expires", value: fmt(vaultCheck.latest_version_expires) },
                ]}
              />
            )}
          </DetailCard>
        </>
      )}

      {item && section === "keys" && (
        <DetailGrid
          title={`Keys in ${outputKind} ${item.output_name ?? ""}`}
          rows={keyRows}
          columns={[
            { key: "key", header: "Key", sortValue: (r) => r.key, render: (r) => <span className="font-mono text-xs text-slate-800">{r.key}</span> },
            {
              key: "role",
              header: "Synced From Key Vault",
              sortValue: (r) => r.role,
              render: (r) =>
                r.role === "synced" ? (
                  <span className="rounded-full bg-green-100 px-2 py-0.5 text-[11px] font-semibold text-green-700">Yes — {item.object_name}</span>
                ) : r.role === "missing" ? (
                  <span className="rounded-full bg-red-100 px-2 py-0.5 text-[11px] font-semibold text-red-700">Missing from output</span>
                ) : (
                  <span className="text-xs text-slate-400">Other key</span>
                ),
            },
          ]}
          rowKey={(r) => `${r.role}:${r.key}`}
          searchText={(r) => r.key}
          searchPlaceholder="Search keys…"
          emptyText="No keys found."
          initialSort={{ key: "key", direction: "asc" }}
        />
      )}

      {item && section === "events" && <EventsGrid title="Controller Events" events={item.events} formatDate={formatDate} />}

      {item && section === "metadata" && <KeyValueGrid title="Labels" entries={item.labels} />}
    </ResourceDetailShell>
  );
}
