/**
 * Helm management — the full command surface for the AKS Operations Center.
 *
 * Covers: repo add / repo update / repo remove / search repo / install / upgrade /
 * rollback / list / status / history / uninstall / template / lint.
 *
 * Two scopes are in play and the UI keeps them visually separate:
 *  - Repository and chart-authoring commands (repo *, search, template, lint) run
 *    against the Helm *client* on the server and need no cluster.
 *  - Release commands (install/upgrade/rollback/status/history/uninstall) act on
 *    the selected cluster.
 *
 * Write actions are hidden without `canWrite`. That is UX only — every mutating
 * endpoint is authorized server-side.
 */

import React, { useCallback, useMemo, useState } from "react";
import { gridStyles, SortableHeader, Spinner, nextSortState } from "../../components/gridStyles";
import {
  AKSCluster,
  HelmChartSearchResult,
  HelmRelease,
  HelmRevision,
  useHelmReleases,
  useHelmRepos,
  useAddHelmRepo,
  useUpdateHelmRepos,
  useRemoveHelmRepo,
  useHelmChartSearch,
  useHelmStatus,
  useHelmHistory,
  useInstallHelmRelease,
  useUpgradeHelmRelease,
  useRollbackHelmRelease,
  useUninstallHelmRelease,
  useTemplateHelmChart,
  useLintHelmChart,
} from "../../services/aksApi";
import {
  CacheSourceBadge,
  ExtendedTabToolbar,
  GridPager,
  GridSearchBar,
  GridStateRow,
  NamespaceSelect,
  useGridSort,
  useSearchPagination,
} from "./aksGridShared";
import { ModalShell } from "./K8sResourceModals";
import { IconActionButton } from "./ResourceActionButtons";

type ToastFn = (message: string, type?: "success" | "error" | "info" | "warning") => void;

interface Props {
  cluster: AKSCluster;
  namespace: string;
  namespaces: string[];
  onNamespaceChange: (ns: string) => void;
  canWrite: boolean;
  showToast: ToastFn;
}

const fieldLabel = "block text-xs font-semibold uppercase tracking-wide text-gray-500 mb-1";
const fieldInput =
  "w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-att-400 focus:ring-2 focus:ring-att-100";
const monoBox =
  "max-h-80 overflow-auto rounded-lg border border-gray-200 bg-gray-900 p-3 font-mono text-xs text-gray-100 whitespace-pre-wrap break-words";

/** Surfaces the backend's command envelope, which reports failure without throwing. */
function CommandOutput({ result }: { result?: { success?: boolean; output?: string; error?: string } }) {
  if (!result) return null;
  const text = result.error || result.output || (result.success ? "Command completed with no output." : "");
  if (!text) return null;
  return (
    <div className="space-y-1">
      <p className={`text-xs font-semibold ${result.success ? "text-green-700" : "text-red-700"}`}>
        {result.success ? "Success" : "Failed"}
      </p>
      <pre className={monoBox}>{text}</pre>
    </div>
  );
}

function errText(e: unknown, fallback: string): string {
  const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
  return detail || (e as Error)?.message || fallback;
}

// ── Repositories ──────────────────────────────────────────────────────

function RepoManagerModal({ onClose, canWrite, showToast }: { onClose: () => void; canWrite: boolean; showToast: ToastFn }) {
  const { data, isLoading, isError } = useHelmRepos();
  const addMut = useAddHelmRepo();
  const updateMut = useUpdateHelmRepos();
  const removeMut = useRemoveHelmRepo();

  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  const repos = data?.repos ?? [];

  const handleAdd = async () => {
    try {
      await addMut.mutateAsync({
        name: name.trim(),
        url: url.trim(),
        username: username.trim() || undefined,
        password: password || undefined,
      });
      showToast(`Repository "${name.trim()}" added`);
      setName("");
      setUrl("");
      setUsername("");
      setPassword("");
    } catch (e) {
      showToast(errText(e, "helm repo add failed"), "error");
    }
  };

  return (
    <ModalShell title="Helm Repositories" onClose={onClose} wide>
      <p className="mb-4 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
        Repositories are stored by the Helm client on the server, not per cluster. In a
        multi-replica deployment a repo added here may not be visible to other replicas.
      </p>

      {canWrite && (
        <div className="mb-5 rounded-lg border border-att-100 bg-att-50/40 p-4">
          <p className="mb-3 text-sm font-semibold text-gray-800">Add repository</p>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div>
              <label className={fieldLabel}>Name *</label>
              <input className={fieldInput} value={name} onChange={(e) => setName(e.target.value)} placeholder="bitnami" />
            </div>
            <div>
              <label className={fieldLabel}>URL *</label>
              <input className={fieldInput} value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://charts.bitnami.com/bitnami" />
            </div>
            <div>
              <label className={fieldLabel}>Username</label>
              <input className={fieldInput} value={username} onChange={(e) => setUsername(e.target.value)} placeholder="optional" />
            </div>
            <div>
              <label className={fieldLabel}>Password</label>
              <input type="password" className={fieldInput} value={password} onChange={(e) => setPassword(e.target.value)} placeholder="optional" />
            </div>
          </div>
          <div className="mt-3 flex items-center gap-2">
            <button
              type="button"
              onClick={handleAdd}
              disabled={!name.trim() || !url.trim() || addMut.isPending}
              className="inline-flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-medium text-white hover:bg-green-700 disabled:opacity-50"
            >
              {addMut.isPending && <Spinner className="h-4 w-4" />}
              {addMut.isPending ? "Adding…" : "helm repo add"}
            </button>
            <button
              type="button"
              onClick={async () => {
                try {
                  await updateMut.mutateAsync(undefined);
                  showToast("Repository indexes refreshed");
                } catch (e) {
                  showToast(errText(e, "helm repo update failed"), "error");
                }
              }}
              disabled={updateMut.isPending}
              className="inline-flex items-center gap-2 rounded-lg border border-att-200 bg-white px-4 py-2 text-sm font-medium text-att-700 hover:bg-att-50 disabled:opacity-50"
            >
              {updateMut.isPending && <Spinner className="h-4 w-4" />}
              {updateMut.isPending ? "Updating…" : "helm repo update"}
            </button>
          </div>
          <CommandOutput result={addMut.data ?? updateMut.data} />
        </div>
      )}

      <div className={gridStyles.shell}>
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              <th className={gridStyles.headerCell}>Repository</th>
              <th className={gridStyles.headerCell}>URL</th>
              {canWrite && <th className={gridStyles.headerCellCenter}>Actions</th>}
            </tr>
          </thead>
          <tbody>
            {repos.length === 0 && (
              <GridStateRow
                colSpan={canWrite ? 3 : 2}
                isLoading={isLoading}
                isError={isError}
                errorText="Could not read repositories. The Helm CLI may not be installed on the server."
                emptyText="No repositories configured yet."
              />
            )}
            {repos.map((r) => (
              <tr key={r.name} className={gridStyles.row}>
                <td className={gridStyles.strongCell}>{r.name}</td>
                <td className={gridStyles.monoCell}>{r.url}</td>
                {canWrite && (
                  <td className={gridStyles.centerCell}>
                    <div className="flex justify-center">
                      <IconActionButton
                        icon="delete"
                        tone="red"
                        title="Remove repository (helm repo remove)"
                        disabled={removeMut.isPending}
                        onClick={async () => {
                          try {
                            await removeMut.mutateAsync(r.name);
                            showToast(`Repository "${r.name}" removed`);
                          } catch (e) {
                            showToast(errText(e, "helm repo remove failed"), "error");
                          }
                        }}
                      />
                    </div>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </ModalShell>
  );
}

// ── Chart search ──────────────────────────────────────────────────────

function ChartSearchModal({
  onClose,
  onInstall,
  canWrite,
}: {
  onClose: () => void;
  onInstall: (chart: string, version: string) => void;
  canWrite: boolean;
}) {
  const [keyword, setKeyword] = useState("");
  const [submitted, setSubmitted] = useState("");
  const { data, isLoading, isError, isFetching } = useHelmChartSearch(submitted, submitted !== "" || submitted === "");
  const charts = data?.charts ?? [];

  const pag = useSearchPagination<HelmChartSearchResult>(
    charts,
    useCallback((c: HelmChartSearchResult, q: string) => c.name.toLowerCase().includes(q), []),
  );

  return (
    <ModalShell title="Search Charts" onClose={onClose} wide>
      <form
        className="mb-4 flex items-end gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          setSubmitted(keyword.trim());
        }}
      >
        <div className="flex-1">
          <label className={fieldLabel}>Keyword</label>
          <input className={fieldInput} value={keyword} onChange={(e) => setKeyword(e.target.value)} placeholder="nginx — leave blank to list all charts" />
        </div>
        <button
          type="submit"
          disabled={isFetching}
          className="inline-flex items-center gap-2 rounded-lg bg-att-500 px-4 py-2 text-sm font-medium text-white hover:bg-att-600 disabled:opacity-50"
        >
          {isFetching && <Spinner className="h-4 w-4" />}
          {isFetching ? "Searching…" : "helm search repo"}
        </button>
      </form>

      <div className={gridStyles.shell}>
        <GridSearchBar
          search={pag.search}
          onSearch={pag.setSearch}
          onPage={pag.setPage}
          totalItems={charts.length}
          shownItems={pag.filtered.length}
          placeholder="Filter results…"
        />
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}>Chart</th>
                <th className={gridStyles.headerCell}>Version</th>
                <th className={gridStyles.headerCell}>App Version</th>
                <th className={gridStyles.headerCell}>Description</th>
                {canWrite && <th className={gridStyles.headerCellCenter}>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {pag.paged.length === 0 && (
                <GridStateRow
                  colSpan={canWrite ? 5 : 4}
                  isLoading={isLoading}
                  isError={isError}
                  emptyText="No charts found. Add a repository and run helm repo update first."
                />
              )}
              {pag.paged.map((c) => (
                <tr key={`${c.name}@${c.version}`} className={gridStyles.row}>
                  <td className={gridStyles.strongCell}>{c.name}</td>
                  <td className={gridStyles.monoCell}>{c.version}</td>
                  <td className={gridStyles.cell}>{c.app_version || "—"}</td>
                  <td className={gridStyles.cell}>
                    <span className="line-clamp-2 text-xs text-gray-600">{c.description || "—"}</span>
                  </td>
                  {canWrite && (
                    <td className={gridStyles.centerCell}>
                      <div className="flex justify-center">
                        <IconActionButton
                          icon="install"
                          tone="teal"
                          title={`Install ${c.name} (helm install)`}
                          onClick={() => onInstall(c.name, c.version)}
                        />
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <GridPager page={pag.page} totalPages={pag.totalPages} onPage={pag.setPage} />
      </div>
    </ModalShell>
  );
}

// ── Install / upgrade ─────────────────────────────────────────────────

function ReleaseFormModal({
  mode,
  clusterId,
  namespaces,
  initialNamespace,
  initialChart,
  initialVersion,
  releaseName: fixedReleaseName,
  onClose,
  showToast,
}: {
  mode: "install" | "upgrade";
  clusterId: string;
  namespaces: string[];
  initialNamespace: string;
  initialChart?: string;
  initialVersion?: string;
  releaseName?: string;
  onClose: () => void;
  showToast: ToastFn;
}) {
  const isInstall = mode === "install";
  const [releaseName, setReleaseName] = useState(fixedReleaseName ?? "");
  const [chart, setChart] = useState(initialChart ?? "");
  const [ns, setNs] = useState(initialNamespace || namespaces[0] || "default");
  const [version, setVersion] = useState(initialVersion ?? "");
  const [valuesYaml, setValuesYaml] = useState("");
  const [createNamespace, setCreateNamespace] = useState(false);

  const installMut = useInstallHelmRelease();
  const upgradeMut = useUpgradeHelmRelease();
  const templateMut = useTemplateHelmChart();
  const lintMut = useLintHelmChart();
  const mut = isInstall ? installMut : upgradeMut;

  const canSubmit = releaseName.trim() !== "" && chart.trim() !== "" && ns !== "";

  const handleSubmit = async () => {
    const base = {
      cluster_id: clusterId,
      release_name: releaseName.trim(),
      chart: chart.trim(),
      namespace: ns,
      version: version.trim() || undefined,
      values_yaml: valuesYaml.trim() || undefined,
    };
    try {
      if (isInstall) {
        await installMut.mutateAsync({ ...base, create_namespace: createNamespace });
        showToast(`Installed ${base.release_name}`);
      } else {
        await upgradeMut.mutateAsync(base);
        showToast(`Upgraded ${base.release_name}`);
      }
      onClose();
    } catch (e) {
      showToast(errText(e, `helm ${mode} failed`), "error");
    }
  };

  return (
    <ModalShell title={isInstall ? "Install Release (helm install)" : `Upgrade ${fixedReleaseName} (helm upgrade)`} onClose={onClose} wide>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className={fieldLabel}>Release name *</label>
          <input
            className={fieldInput}
            value={releaseName}
            onChange={(e) => setReleaseName(e.target.value)}
            disabled={!isInstall}
            placeholder="my-release"
          />
        </div>
        <div>
          <label className={fieldLabel}>Chart *</label>
          <input className={fieldInput} value={chart} onChange={(e) => setChart(e.target.value)} placeholder="bitnami/nginx or oci://registry/chart" />
        </div>
        <div>
          <label className={fieldLabel}>Namespace *</label>
          <select className={fieldInput} value={ns} onChange={(e) => setNs(e.target.value)} disabled={!isInstall}>
            {namespaces.map((n) => (
              <option key={n} value={n}>{n}</option>
            ))}
          </select>
        </div>
        <div>
          <label className={fieldLabel}>Version</label>
          <input className={fieldInput} value={version} onChange={(e) => setVersion(e.target.value)} placeholder="latest if blank" />
        </div>
      </div>

      <div className="mt-3">
        <label className={fieldLabel}>Values (YAML)</label>
        <textarea
          className={`${fieldInput} h-40 font-mono text-xs`}
          value={valuesYaml}
          onChange={(e) => setValuesYaml(e.target.value)}
          placeholder={"replicaCount: 2\nimage:\n  tag: 1.2.3"}
        />
      </div>

      {isInstall && (
        <label className="mt-3 flex items-center gap-2 text-sm text-gray-700">
          <input type="checkbox" checked={createNamespace} onChange={(e) => setCreateNamespace(e.target.checked)} />
          Create the namespace if it does not exist (--create-namespace)
        </label>
      )}

      {/* Dry-run tooling: neither command touches the cluster. */}
      <div className="mt-4 flex flex-wrap items-center gap-2 border-t border-gray-200 pt-4">
        <button
          type="button"
          onClick={async () => {
            try {
              await templateMut.mutateAsync({
                chart: chart.trim(),
                release_name: releaseName.trim() || "release-name",
                namespace: ns,
                version: version.trim() || undefined,
                values_yaml: valuesYaml.trim() || undefined,
              });
            } catch (e) {
              showToast(errText(e, "helm template failed"), "error");
            }
          }}
          disabled={!chart.trim() || templateMut.isPending}
          className="inline-flex items-center gap-2 rounded-lg border border-att-200 bg-white px-3 py-2 text-sm font-medium text-att-700 hover:bg-att-50 disabled:opacity-50"
        >
          {templateMut.isPending && <Spinner className="h-4 w-4" />}
          helm template
        </button>
        <button
          type="button"
          onClick={async () => {
            try {
              await lintMut.mutateAsync({ chart: chart.trim(), values_yaml: valuesYaml.trim() || undefined });
            } catch (e) {
              showToast(errText(e, "helm lint failed"), "error");
            }
          }}
          disabled={!chart.trim() || lintMut.isPending}
          className="inline-flex items-center gap-2 rounded-lg border border-att-200 bg-white px-3 py-2 text-sm font-medium text-att-700 hover:bg-att-50 disabled:opacity-50"
        >
          {lintMut.isPending && <Spinner className="h-4 w-4" />}
          helm lint
        </button>
        <span className="text-xs text-gray-500">Preview only — neither modifies the cluster.</span>
      </div>

      <div className="mt-3">
        <CommandOutput result={lintMut.data ?? templateMut.data} />
      </div>

      <div className="mt-5 flex justify-end gap-2 border-t border-gray-200 pt-4">
        <button type="button" onClick={onClose} className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">
          Cancel
        </button>
        <button
          type="button"
          onClick={handleSubmit}
          disabled={!canSubmit || mut.isPending}
          className={`inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium text-white disabled:opacity-50 ${
            isInstall ? "bg-green-600 hover:bg-green-700" : "bg-att-500 hover:bg-att-600"
          }`}
        >
          {mut.isPending && <Spinner className="h-4 w-4" />}
          {mut.isPending ? `Running…` : isInstall ? "helm install" : "helm upgrade"}
        </button>
      </div>
    </ModalShell>
  );
}

// ── Status ────────────────────────────────────────────────────────────

function StatusModal({
  clusterId,
  release,
  onClose,
}: {
  clusterId: string;
  release: HelmRelease;
  onClose: () => void;
}) {
  const { data, isLoading, isError } = useHelmStatus(clusterId, release.name, release.namespace);
  const info = data?.data?.info;

  return (
    <ModalShell title={`Status: ${release.name} (helm status)`} onClose={onClose} wide>
      {isLoading ? (
        <p className="flex items-center gap-2 py-6 text-sm text-gray-500">
          <Spinner className="h-4 w-4" />Loading release status…
        </p>
      ) : isError ? (
        <p className="py-6 text-sm text-red-600">Could not read release status. The release may have been removed.</p>
      ) : (
        <div className="space-y-4">
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              ["Status", info?.status ?? "—"],
              ["Revision", data?.data?.version != null ? String(data.data.version) : "—"],
              ["Namespace", data?.data?.namespace ?? release.namespace],
              ["Last deployed", info?.last_deployed ? new Date(info.last_deployed).toLocaleString() : "—"],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-att-100 bg-att-50/40 px-3 py-2">
                <dt className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">{label}</dt>
                <dd className="mt-0.5 text-sm font-semibold text-gray-800 break-words">{value}</dd>
              </div>
            ))}
          </dl>
          {info?.description && (
            <div>
              <p className={fieldLabel}>Description</p>
              <p className="text-sm text-gray-700">{info.description}</p>
            </div>
          )}
          {info?.notes && (
            <div>
              <p className={fieldLabel}>Notes</p>
              <pre className={monoBox}>{info.notes}</pre>
            </div>
          )}
        </div>
      )}
    </ModalShell>
  );
}

// ── History + rollback ────────────────────────────────────────────────

function HistoryModal({
  clusterId,
  release,
  canWrite,
  onClose,
  showToast,
}: {
  clusterId: string;
  release: HelmRelease;
  canWrite: boolean;
  onClose: () => void;
  showToast: ToastFn;
}) {
  const { data, isLoading, isError } = useHelmHistory(clusterId, release.name, release.namespace);
  const rollbackMut = useRollbackHelmRelease();
  const [confirm, setConfirm] = useState<HelmRevision | null>(null);

  // Helm returns history oldest-first; newest revisions are what you act on.
  const revisions = useMemo(
    () => [...(data?.revisions ?? [])].sort((a, b) => b.revision - a.revision),
    [data],
  );

  const handleRollback = async (revision: number) => {
    try {
      await rollbackMut.mutateAsync({
        cluster_id: clusterId,
        release_name: release.name,
        namespace: release.namespace,
        revision,
      });
      showToast(`Rolled ${release.name} back to revision ${revision}`);
      setConfirm(null);
      onClose();
    } catch (e) {
      showToast(errText(e, "helm rollback failed"), "error");
    }
  };

  return (
    <ModalShell title={`History: ${release.name} (helm history)`} onClose={onClose} wide>
      {confirm && (
        <div className="mb-4 rounded-lg border-2 border-amber-300 bg-amber-50 p-4">
          <p className="text-sm font-semibold text-amber-900">
            Roll {release.name} back to revision {confirm.revision}?
          </p>
          <p className="mt-1 text-xs text-amber-800">
            This redeploys the chart and values from that revision and creates a new revision on top.
          </p>
          <div className="mt-3 flex gap-2">
            <button
              type="button"
              onClick={() => handleRollback(confirm.revision)}
              disabled={rollbackMut.isPending}
              className="inline-flex items-center gap-2 rounded-lg bg-amber-600 px-4 py-2 text-sm font-medium text-white hover:bg-amber-700 disabled:opacity-50"
            >
              {rollbackMut.isPending && <Spinner className="h-4 w-4" />}
              {rollbackMut.isPending ? "Rolling back…" : "helm rollback"}
            </button>
            <button type="button" onClick={() => setConfirm(null)} className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">
              Cancel
            </button>
          </div>
        </div>
      )}

      <div className={gridStyles.shell}>
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCellCenter}>Revision</th>
                <th className={gridStyles.headerCell}>Updated</th>
                <th className={gridStyles.headerCell}>Status</th>
                <th className={gridStyles.headerCell}>Chart</th>
                <th className={gridStyles.headerCell}>Description</th>
                {canWrite && <th className={gridStyles.headerCellCenter}>Actions</th>}
              </tr>
            </thead>
            <tbody>
              {revisions.length === 0 && (
                <GridStateRow
                  colSpan={canWrite ? 6 : 5}
                  isLoading={isLoading}
                  isError={isError}
                  emptyText="No revision history for this release."
                />
              )}
              {revisions.map((r, idx) => {
                const isCurrent = idx === 0;
                return (
                  <tr key={r.revision} className={gridStyles.row}>
                    <td className={gridStyles.centerCell}>
                      <span className="font-mono text-xs font-semibold">{r.revision}</span>
                      {isCurrent && <span className="ml-2 rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-medium text-green-700">current</span>}
                    </td>
                    <td className={gridStyles.cell}>{r.updated ? new Date(r.updated).toLocaleString() : "—"}</td>
                    <td className={gridStyles.cell}>{r.status}</td>
                    <td className={gridStyles.monoCell}>{r.chart || "—"}</td>
                    <td className={gridStyles.cell}>
                      <span className="text-xs text-gray-600">{r.description || "—"}</span>
                    </td>
                    {canWrite && (
                      <td className={gridStyles.centerCell}>
                        <div className="flex justify-center">
                          <IconActionButton
                            icon="rollback"
                            tone="amber"
                            disabled={isCurrent}
                            title={isCurrent ? "Already the current revision" : `Roll back to revision ${r.revision} (helm rollback)`}
                            onClick={() => setConfirm(r)}
                          />
                        </div>
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </ModalShell>
  );
}

// ── Chart tools (template / lint without a release) ───────────────────

function ChartToolsModal({ onClose, showToast }: { onClose: () => void; showToast: ToastFn }) {
  const [chart, setChart] = useState("");
  const [version, setVersion] = useState("");
  const [valuesYaml, setValuesYaml] = useState("");
  const templateMut = useTemplateHelmChart();
  const lintMut = useLintHelmChart();
  const [last, setLast] = useState<"template" | "lint" | null>(null);

  const run = async (kind: "template" | "lint") => {
    setLast(kind);
    try {
      if (kind === "template") {
        await templateMut.mutateAsync({
          chart: chart.trim(),
          version: version.trim() || undefined,
          values_yaml: valuesYaml.trim() || undefined,
        });
      } else {
        await lintMut.mutateAsync({ chart: chart.trim(), values_yaml: valuesYaml.trim() || undefined });
      }
    } catch (e) {
      showToast(errText(e, `helm ${kind} failed`), "error");
    }
  };

  return (
    <ModalShell title="Chart Tools (helm template / helm lint)" onClose={onClose} wide>
      <p className="mb-4 rounded-lg border border-att-100 bg-att-50/40 px-3 py-2 text-xs text-gray-600">
        Both commands run against the chart only. Nothing is sent to a cluster.
      </p>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <label className={fieldLabel}>Chart *</label>
          <input className={fieldInput} value={chart} onChange={(e) => setChart(e.target.value)} placeholder="bitnami/nginx" />
        </div>
        <div>
          <label className={fieldLabel}>Version</label>
          <input className={fieldInput} value={version} onChange={(e) => setVersion(e.target.value)} placeholder="latest if blank" />
        </div>
      </div>
      <div className="mt-3">
        <label className={fieldLabel}>Values (YAML)</label>
        <textarea className={`${fieldInput} h-32 font-mono text-xs`} value={valuesYaml} onChange={(e) => setValuesYaml(e.target.value)} />
      </div>
      <div className="mt-4 flex gap-2">
        <button
          type="button"
          onClick={() => run("template")}
          disabled={!chart.trim() || templateMut.isPending}
          className="inline-flex items-center gap-2 rounded-lg bg-att-500 px-4 py-2 text-sm font-medium text-white hover:bg-att-600 disabled:opacity-50"
        >
          {templateMut.isPending && <Spinner className="h-4 w-4" />}
          helm template
        </button>
        <button
          type="button"
          onClick={() => run("lint")}
          disabled={!chart.trim() || lintMut.isPending}
          className="inline-flex items-center gap-2 rounded-lg border border-att-200 bg-white px-4 py-2 text-sm font-medium text-att-700 hover:bg-att-50 disabled:opacity-50"
        >
          {lintMut.isPending && <Spinner className="h-4 w-4" />}
          helm lint
        </button>
      </div>
      <div className="mt-4">
        <CommandOutput result={last === "lint" ? lintMut.data : templateMut.data} />
      </div>
    </ModalShell>
  );
}

// ── Main tab ──────────────────────────────────────────────────────────

type SortKey = "name" | "namespace" | "chart" | "revision" | "status";

const HelmManagement: React.FC<Props> = ({ cluster, namespace, namespaces, onNamespaceChange, canWrite, showToast }) => {
  const nsFilter = namespace || undefined;
  const { data, isError, error, refetch, isFetching, isPlaceholderData } = useHelmReleases(cluster.id, nsFilter);
  const isLoading = isFetching && isPlaceholderData;
  // The endpoint returns 200 with a warning when it could not read releases, so
  // the rest of the tab (repos, search, template) stays usable.
  const warning = data?.warning ?? null;
  const uninstallMut = useUninstallHelmRelease();

  const items = data?.releases ?? [];

  const accessor = useCallback((r: HelmRelease, key: string): string | number => {
    switch (key) {
      case "namespace": return r.namespace.toLowerCase();
      case "chart": return (r.chart || "").toLowerCase();
      case "revision": return Number(r.revision) || 0;
      case "status": return (r.status || "").toLowerCase();
      default: return r.name.toLowerCase();
    }
  }, []);
  const { sort, setSort, sorted } = useGridSort<HelmRelease, SortKey>(items, accessor, { key: "name", direction: "asc" });
  const pag = useSearchPagination(
    sorted,
    useCallback((r: HelmRelease, q: string) => r.name.toLowerCase().includes(q) || r.chart.toLowerCase().includes(q), []),
  );

  const [showRepos, setShowRepos] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [showTools, setShowTools] = useState(false);
  const [installSeed, setInstallSeed] = useState<{ chart?: string; version?: string } | null>(null);
  const [upgradeTarget, setUpgradeTarget] = useState<HelmRelease | null>(null);
  const [statusTarget, setStatusTarget] = useState<HelmRelease | null>(null);
  const [historyTarget, setHistoryTarget] = useState<HelmRelease | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<HelmRelease | null>(null);

  const th = (label: string, key: SortKey) => (
    <th className={gridStyles.headerCell}>
      <SortableHeader label={label} active={sort.key === key} direction={sort.direction} onClick={() => setSort(nextSortState(sort, key))} />
    </th>
  );

  return (
    <div className="space-y-4">
      <ExtendedTabToolbar
        title="Helm Releases"
        namespaceSelect={<NamespaceSelect namespaces={namespaces} value={namespace} onChange={onNamespaceChange} />}
        onSync={() => refetch()}
        syncing={isFetching}
        canWrite={canWrite}
      />

      {/* Client-scoped commands sit apart from the cluster-scoped release grid. */}
      <div className="flex flex-wrap items-center gap-2">
        <button type="button" onClick={() => setShowRepos(true)} className="rounded-lg border border-att-200 bg-white px-3 py-2 text-sm font-medium text-att-700 hover:bg-att-50">
          Repositories
        </button>
        <button type="button" onClick={() => setShowSearch(true)} className="rounded-lg border border-att-200 bg-white px-3 py-2 text-sm font-medium text-att-700 hover:bg-att-50">
          Search Charts
        </button>
        <button type="button" onClick={() => setShowTools(true)} className="rounded-lg border border-att-200 bg-white px-3 py-2 text-sm font-medium text-att-700 hover:bg-att-50">
          Chart Tools
        </button>
        {canWrite && (
          <button type="button" onClick={() => setInstallSeed({})} className="rounded-lg bg-green-600 px-3 py-2 text-sm font-medium text-white hover:bg-green-700">
            + Install Release
          </button>
        )}
      </div>

      {warning && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <p className="font-semibold">Helm releases could not be listed</p>
          <p className="mt-1 break-words text-xs">{warning}</p>
        </div>
      )}

      <div className={gridStyles.shell}>
        <GridSearchBar
          search={pag.search}
          onSearch={pag.setSearch}
          onPage={pag.setPage}
          totalItems={items.length}
          shownItems={pag.filtered.length}
          placeholder="Search releases…"
          isSyncing={isFetching}
        />
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                {th("Release", "name")}
                {th("Namespace", "namespace")}
                {th("Chart", "chart")}
                {th("Revision", "revision")}
                {th("Status", "status")}
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {pag.paged.length === 0 && (
                <GridStateRow
                  colSpan={6}
                  isLoading={isLoading}
                  isError={isError}
                  errorText={
                    (error as Error | null)?.message?.toLowerCase().includes("timeout")
                      ? "Timed out listing releases. Select a single namespace — scanning every namespace is much slower."
                      : `Failed to load releases: ${(error as Error | null)?.message ?? "unknown error"}`
                  }
                  emptyText={
                    warning
                      ? "Releases unavailable — see the message above."
                      : pag.search
                        ? "No releases match your search"
                        : "No Helm releases found"
                  }
                />
              )}
              {pag.paged.map((r) => (
                <tr key={`${r.namespace}/${r.name}`} className={gridStyles.row}>
                  <td className={gridStyles.strongCell}>{r.name}</td>
                  <td className={gridStyles.cell}>{r.namespace}</td>
                  <td className={gridStyles.monoCell}>{r.chart}</td>
                  <td className={gridStyles.cell}>{r.revision}</td>
                  <td className={gridStyles.cell}>
                    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${
                      r.status === "deployed" ? "bg-green-100 text-green-700"
                      : r.status === "failed" ? "bg-red-100 text-red-700"
                      : "bg-gray-100 text-gray-700"
                    }`}>
                      {r.status}
                    </span>
                  </td>
                  <td className={gridStyles.centerCell}>
                    <div className="flex justify-center gap-1">
                      <IconActionButton icon="status" tone="teal" title="View status (helm status)" onClick={() => setStatusTarget(r)} />
                      <IconActionButton icon="history" tone="blue" title="Revision history (helm history)" onClick={() => setHistoryTarget(r)} />
                      {canWrite && (
                        <>
                          <IconActionButton icon="upgrade" tone="purple" title="Upgrade release (helm upgrade)" onClick={() => setUpgradeTarget(r)} />
                          <IconActionButton icon="delete" tone="red" title="Uninstall release (helm uninstall)" onClick={() => setDeleteTarget(r)} />
                        </>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <GridPager page={pag.page} totalPages={pag.totalPages} onPage={pag.setPage} />
      </div>

      {showRepos && <RepoManagerModal onClose={() => setShowRepos(false)} canWrite={canWrite} showToast={showToast} />}
      {showTools && <ChartToolsModal onClose={() => setShowTools(false)} showToast={showToast} />}
      {showSearch && (
        <ChartSearchModal
          canWrite={canWrite}
          onClose={() => setShowSearch(false)}
          onInstall={(chart, version) => {
            setShowSearch(false);
            setInstallSeed({ chart, version });
          }}
        />
      )}
      {installSeed && (
        <ReleaseFormModal
          mode="install"
          clusterId={cluster.id}
          namespaces={namespaces}
          initialNamespace={namespace}
          initialChart={installSeed.chart}
          initialVersion={installSeed.version}
          onClose={() => setInstallSeed(null)}
          showToast={showToast}
        />
      )}
      {upgradeTarget && (
        <ReleaseFormModal
          mode="upgrade"
          clusterId={cluster.id}
          namespaces={namespaces}
          initialNamespace={upgradeTarget.namespace}
          initialChart={upgradeTarget.chart}
          releaseName={upgradeTarget.name}
          onClose={() => setUpgradeTarget(null)}
          showToast={showToast}
        />
      )}
      {statusTarget && <StatusModal clusterId={cluster.id} release={statusTarget} onClose={() => setStatusTarget(null)} />}
      {historyTarget && (
        <HistoryModal
          clusterId={cluster.id}
          release={historyTarget}
          canWrite={canWrite}
          onClose={() => setHistoryTarget(null)}
          showToast={showToast}
        />
      )}
      {deleteTarget && (
        <ModalShell title="Uninstall Release" onClose={() => setDeleteTarget(null)}>
          <p className="text-sm text-gray-700">
            Uninstall <strong>{deleteTarget.name}</strong> from <strong>{deleteTarget.namespace}</strong>?
          </p>
          <p className="mt-2 text-xs text-gray-500">
            This removes every resource the release created. Revision history is deleted with it.
          </p>
          <div className="mt-5 flex justify-end gap-2">
            <button type="button" onClick={() => setDeleteTarget(null)} className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">
              Cancel
            </button>
            <button
              type="button"
              onClick={async () => {
                try {
                  await uninstallMut.mutateAsync({
                    clusterId: cluster.id,
                    releaseName: deleteTarget.name,
                    namespace: deleteTarget.namespace,
                  });
                  showToast(`Uninstalled ${deleteTarget.name}`);
                  setDeleteTarget(null);
                } catch (e) {
                  showToast(errText(e, "helm uninstall failed"), "error");
                }
              }}
              disabled={uninstallMut.isPending}
              className="inline-flex items-center gap-2 rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
            >
              {uninstallMut.isPending && <Spinner className="h-4 w-4" />}
              {uninstallMut.isPending ? "Uninstalling…" : "helm uninstall"}
            </button>
          </div>
        </ModalShell>
      )}
    </div>
  );
};

export default HelmManagement;
