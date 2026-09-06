/**
 * Jobs tab — multi-namespace Kubernetes Job inventory for the AKS Operations Center.
 *
 * Built on the same shared grid primitives as the other extended resource tabs
 * (search bar, bottom pager, namespace select) so it reads as a native part of
 * the existing page rather than a new design.
 *
 * Jobs created by a manual CronJob trigger are the primary use case: the
 * CronJobs tab hands off here via `focusJob`, which pre-selects the new Job and
 * opens its detail panel so the user can watch it run.
 *
 * Destructive actions are hidden unless the backend granted the matching
 * capability. That is a UX affordance only — the API authorizes every call
 * independently.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { gridStyles } from "../../components/gridStyles";
import {
  AKSCluster,
  JobPod,
  JobStatus,
  K8sJob,
  useDeleteJob,
  useJobDetail,
  useJobs,
} from "../../services/aksApi";
import {
  GridPager,
  GridSearchBar,
  NamespaceSelect,
  useSearchPagination,
} from "./aksGridShared";
import { DeleteConfirmModal } from "./K8sResourceModals";
import { JobDetailModal } from "./JobDetailModal";

export type JobFocus = { namespace: string; name: string } | null;

type JobsTabProps = {
  cluster: AKSCluster;
  namespace: string;
  namespaces: string[];
  onNamespaceChange: (ns: string) => void;
  showToast: (msg: string, type?: "success" | "error") => void;
  formatDate: (value: string) => string;
  /** Capability gate, supplied by the page. */
  canDeleteJob: boolean;
  canDeletePod: boolean;
  /** Job to select on mount — set when arriving from a CronJob trigger. */
  focusJob?: JobFocus;
  onFocusConsumed?: () => void;
  /** Opens the shared pod log viewer for a Job's pod. */
  onViewPodLogs: (pod: JobPod) => void;
  onDeletePod?: (pod: JobPod) => void;
};

const STATUS_STYLES: Record<JobStatus, string> = {
  Running: "bg-blue-100 text-blue-700",
  Completed: "bg-green-100 text-green-700",
  Failed: "bg-red-100 text-red-700",
  Suspended: "bg-amber-100 text-amber-700",
  Unknown: "bg-gray-100 text-gray-600",
};

const STATUS_FILTERS: (JobStatus | "All")[] = [
  "All",
  "Running",
  "Completed",
  "Failed",
  "Suspended",
  "Unknown",
];

const AGE_FILTERS = [
  { key: "all", label: "Any age", maxHours: Infinity },
  { key: "1h", label: "Last hour", maxHours: 1 },
  { key: "24h", label: "Last 24 hours", maxHours: 24 },
  { key: "7d", label: "Last 7 days", maxHours: 24 * 7 },
] as const;

const COMPLETION_FILTERS = [
  { key: "all", label: "All jobs" },
  { key: "finished", label: "Finished" },
  { key: "unfinished", label: "Unfinished" },
] as const;

/** Hours since `iso`, or null when absent/unparseable. */
function ageHours(iso: string | null): number | null {
  if (!iso) return null;
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return null;
  return (Date.now() - then) / 3_600_000;
}

function formatAge(iso: string | null): string {
  const hours = ageHours(iso);
  if (hours === null) return "—";
  if (hours < 1) return `${Math.max(0, Math.round(hours * 60))}m`;
  if (hours < 24) return `${Math.floor(hours)}h ${Math.round((hours % 1) * 60)}m`;
  const days = Math.floor(hours / 24);
  return `${days}d ${Math.floor(hours % 24)}h`;
}

export const JobsTab: React.FC<JobsTabProps> = ({
  cluster,
  namespace,
  namespaces,
  onNamespaceChange,
  showToast,
  formatDate,
  canDeleteJob,
  canDeletePod,
  focusJob,
  onFocusConsumed,
  onViewPodLogs,
  onDeletePod,
}) => {
  const [statusFilter, setStatusFilter] = useState<JobStatus | "All">("All");
  const [ageFilter, setAgeFilter] = useState<(typeof AGE_FILTERS)[number]["key"]>("all");
  const [completionFilter, setCompletionFilter] =
    useState<(typeof COMPLETION_FILTERS)[number]["key"]>("all");
  const [selected, setSelected] = useState<{ namespace: string; name: string } | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<K8sJob | null>(null);

  const { data, isLoading, isError, refetch, isFetching } = useJobs(
    cluster.id,
    namespace || undefined
  );
  const deleteMut = useDeleteJob();

  const allJobs = data?.jobs ?? [];

  // Arriving from a CronJob trigger: open the new Job's detail panel once.
  useEffect(() => {
    if (!focusJob) return;
    setSelected({ namespace: focusJob.namespace, name: focusJob.name });
    // Clear filters that would hide a brand-new Job.
    setStatusFilter("All");
    setAgeFilter("all");
    setCompletionFilter("all");
    onFocusConsumed?.();
  }, [focusJob, onFocusConsumed]);

  const filteredByFacets = useMemo(() => {
    const maxHours = AGE_FILTERS.find((f) => f.key === ageFilter)?.maxHours ?? Infinity;
    return allJobs.filter((job) => {
      if (statusFilter !== "All" && job.status !== statusFilter) return false;

      if (maxHours !== Infinity) {
        const hours = ageHours(job.created_at);
        if (hours === null || hours > maxHours) return false;
      }

      if (completionFilter !== "all") {
        // "Finished" means Kubernetes reached a terminal condition for the Job,
        // not merely that some pods succeeded.
        const finished = job.status === "Completed" || job.status === "Failed";
        if (completionFilter === "finished" && !finished) return false;
        if (completionFilter === "unfinished" && finished) return false;
      }

      return true;
    });
  }, [allJobs, statusFilter, ageFilter, completionFilter]);

  const searchFn = useCallback(
    (job: K8sJob, q: string) =>
      job.name.toLowerCase().includes(q) ||
      job.namespace.toLowerCase().includes(q) ||
      (job.created_by ?? "").toLowerCase().includes(q) ||
      (job.image ?? "").toLowerCase().includes(q),
    []
  );

  const { search, setSearch, page, setPage, paged, filtered, totalPages } = useSearchPagination(
    filteredByFacets,
    searchFn
  );

  const detail = useJobDetail(cluster.id, selected?.namespace, selected?.name, !!selected);

  const handleDelete = (job: K8sJob) => setDeleteTarget(job);

  const confirmDelete = () => {
    if (!deleteTarget) return;
    deleteMut.mutate(
      {
        clusterId: cluster.id,
        namespace: deleteTarget.namespace,
        jobName: deleteTarget.name,
      },
      {
        onSuccess: () => {
          showToast(`Deleted Job ${deleteTarget.name}`);
          if (selected?.name === deleteTarget.name) setSelected(null);
          setDeleteTarget(null);
        },
        onError: (e: any) => {
          showToast(e?.response?.data?.detail || "Failed to delete Job", "error");
          setDeleteTarget(null);
        },
      }
    );
  };

  return (
    <div className="space-y-4">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 className="text-xl font-semibold text-gray-800">Jobs</h2>
        <div className="flex flex-wrap items-center gap-2">
          <NamespaceSelect namespaces={namespaces} value={namespace} onChange={onNamespaceChange} />

          <select
            value={statusFilter}
            onChange={(e) => {
              setStatusFilter(e.target.value as JobStatus | "All");
              setPage(1);
            }}
            className={gridStyles.toolbarInput}
            aria-label="Filter by status"
          >
            {STATUS_FILTERS.map((s) => (
              <option key={s} value={s}>
                {s === "All" ? "All Statuses" : s}
              </option>
            ))}
          </select>

          <select
            value={ageFilter}
            onChange={(e) => {
              setAgeFilter(e.target.value as typeof ageFilter);
              setPage(1);
            }}
            className={gridStyles.toolbarInput}
            aria-label="Filter by age"
          >
            {AGE_FILTERS.map((f) => (
              <option key={f.key} value={f.key}>
                {f.label}
              </option>
            ))}
          </select>

          <select
            value={completionFilter}
            onChange={(e) => {
              setCompletionFilter(e.target.value as typeof completionFilter);
              setPage(1);
            }}
            className={gridStyles.toolbarInput}
            aria-label="Filter by completion"
          >
            {COMPLETION_FILTERS.map((f) => (
              <option key={f.key} value={f.key}>
                {f.label}
              </option>
            ))}
          </select>

          <button
            type="button"
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm"
          >
            {isFetching ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      {isError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          Unable to load Jobs from this cluster.{" "}
          <button type="button" onClick={() => refetch()} className="underline font-medium">
            Try again
          </button>
        </div>
      )}

      {isLoading ? (
        <p className="text-sm text-gray-500 py-8">Loading Jobs...</p>
      ) : allJobs.length === 0 ? (
        <p className="text-sm text-gray-500 py-8">
          No Jobs found in {namespace ? `namespace "${namespace}"` : "this cluster"}.
        </p>
      ) : (
        <div className={gridStyles.shell}>
          <GridSearchBar
            search={search}
            onSearch={setSearch}
            onPage={setPage}
            totalItems={allJobs.length}
            shownItems={filtered.length}
            placeholder="Search jobs, namespace, or CronJob..."
          />

          <div className="overflow-x-auto">
            <table className={gridStyles.table}>
              <thead className={gridStyles.head}>
                <tr>
                  <th className={gridStyles.headerCell}>Job Name</th>
                  <th className={gridStyles.headerCell}>Namespace</th>
                  <th className={gridStyles.headerCell}>Status</th>
                  <th className={gridStyles.headerCell}>Completions</th>
                  <th className={gridStyles.headerCell}>Active</th>
                  <th className={gridStyles.headerCell}>Failed</th>
                  <th className={gridStyles.headerCell}>Start Time</th>
                  <th className={gridStyles.headerCell}>Completed</th>
                  <th className={gridStyles.headerCell}>Age</th>
                  <th className={gridStyles.headerCell}>Created By</th>
                  <th className={gridStyles.headerCellCenter}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {paged.map((job) => (
                  <tr key={`${job.namespace}/${job.name}`} className={gridStyles.row}>
                    <td className={gridStyles.cell}>
                      <button
                        type="button"
                        onClick={() => setSelected({ namespace: job.namespace, name: job.name })}
                        className="font-medium text-blue-600 hover:text-blue-800 hover:underline text-left"
                      >
                        {job.name}
                      </button>
                    </td>
                    <td className={gridStyles.cell}>{job.namespace}</td>
                    <td className={gridStyles.cell}>
                      <span
                        className={`px-2 py-0.5 rounded-full text-xs font-medium ${STATUS_STYLES[job.status]}`}
                      >
                        {job.status}
                      </span>
                    </td>
                    <td className={gridStyles.cell}>
                      <span className="font-mono text-xs">
                        {job.succeeded}/{job.completions ?? 1}
                      </span>
                    </td>
                    <td className={gridStyles.cell}>{job.active}</td>
                    <td className={gridStyles.cell}>
                      <span className={job.failed > 0 ? "text-red-600 font-semibold" : ""}>
                        {job.failed}
                      </span>
                    </td>
                    <td className={gridStyles.cell}>
                      <span className="text-xs text-gray-600">
                        {job.start_time ? formatDate(job.start_time) : "—"}
                      </span>
                    </td>
                    <td className={gridStyles.cell}>
                      <span className="text-xs text-gray-600">
                        {job.completion_time ? formatDate(job.completion_time) : "—"}
                      </span>
                    </td>
                    <td className={gridStyles.cell}>
                      <span className="font-mono text-xs text-gray-700">
                        {formatAge(job.created_at)}
                      </span>
                    </td>
                    <td className={gridStyles.cell}>
                      {job.created_by ? (
                        <span className="text-xs">
                          {job.created_by}
                          {job.trigger === "manual" && (
                            <span className="ml-1 px-1.5 py-0.5 rounded bg-indigo-100 text-indigo-700 text-[10px] font-medium">
                              manual
                            </span>
                          )}
                        </span>
                      ) : (
                        <span className="text-gray-400">—</span>
                      )}
                    </td>
                    <td className={gridStyles.centerCell}>
                      <div className="flex items-center justify-center gap-1">
                        <button
                          onClick={() => setSelected({ namespace: job.namespace, name: job.name })}
                          title="View Details"
                          className="p-1 rounded hover:bg-blue-50 text-blue-600"
                        >
                          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>
                        </button>
                        {canDeleteJob && (
                          <button
                            onClick={() => handleDelete(job)}
                            disabled={deleteMut.isPending}
                            title="Delete Job"
                            className="p-1 rounded hover:bg-red-50 text-red-600 disabled:opacity-50"
                          >
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/></svg>
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
      )}

      {selected && (
        <JobDetailModal
          clusterName={cluster.name}
          jobRef={selected}
          detail={detail.data}
          isLoading={detail.isLoading}
          isError={detail.isError}
          formatDate={formatDate}
          canDeletePod={canDeletePod}
          onViewPodLogs={onViewPodLogs}
          onDeletePod={onDeletePod}
          onClose={() => setSelected(null)}
        />
      )}

      {deleteTarget && (
        <DeleteConfirmModal
          title="Delete Job"
          message={
            `Are you sure you want to delete Job "${deleteTarget.name}" from namespace ` +
            `"${deleteTarget.namespace}"?\n\n` +
            `Current status: ${deleteTarget.status}\n\n` +
            `Deleting this Job also deletes the pods it created, so their logs will no ` +
            `longer be available through the portal.`
          }
          confirming={deleteMut.isPending}
          onClose={() => setDeleteTarget(null)}
          onConfirm={confirmDelete}
        />
      )}
    </div>
  );
};

export default JobsTab;
