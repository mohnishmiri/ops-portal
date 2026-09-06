/**
 * Job detail panel — basic info, execution counters, conditions, and the Job's pods.
 *
 * Uses the shared ModalShell so it matches every other AKS resource detail
 * view. Pod rows link out to the page's existing log viewer and pod-delete
 * flows rather than reimplementing them.
 */

import React from "react";
import { JobDetail, JobPod } from "../../services/aksApi";
import { gridStyles } from "../../components/gridStyles";
import { ModalShell } from "./K8sResourceModals";

const POD_PHASE_STYLES: Record<string, string> = {
  Running: "bg-blue-100 text-blue-700",
  Succeeded: "bg-green-100 text-green-700",
  Failed: "bg-red-100 text-red-700",
  Pending: "bg-amber-100 text-amber-700",
};

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs font-semibold uppercase tracking-wide text-gray-500">{label}</dt>
      <dd className="mt-0.5 text-sm text-gray-800 break-all">{value ?? "—"}</dd>
    </div>
  );
}

function KeyValueList({ entries }: { entries: Record<string, string> }) {
  const keys = Object.keys(entries);
  if (keys.length === 0) return <span className="text-sm text-gray-400">None</span>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {keys.map((k) => (
        <span
          key={k}
          className="rounded bg-gray-100 px-2 py-0.5 font-mono text-[11px] text-gray-700"
          title={`${k}=${entries[k]}`}
        >
          {k}={entries[k]}
        </span>
      ))}
    </div>
  );
}

export const JobDetailModal: React.FC<{
  clusterName: string;
  jobRef: { namespace: string; name: string };
  detail?: JobDetail;
  isLoading: boolean;
  isError: boolean;
  formatDate: (value: string) => string;
  canDeletePod: boolean;
  onViewPodLogs: (pod: JobPod) => void;
  onDeletePod?: (pod: JobPod) => void;
  onClose: () => void;
}> = ({
  clusterName,
  jobRef,
  detail,
  isLoading,
  isError,
  formatDate,
  canDeletePod,
  onViewPodLogs,
  onDeletePod,
  onClose,
}) => (
  <ModalShell title={`Job: ${jobRef.name}`} onClose={onClose} wide>
    {isLoading && !detail ? (
      <p className="py-8 text-sm text-gray-500">Loading Job details...</p>
    ) : isError || !detail ? (
      <p className="py-8 text-sm text-red-600">
        Unable to load details for this Job. It may have been deleted or its TTL may have expired.
      </p>
    ) : (
      <div className="space-y-6">
        {/* ── Basic information ── */}
        <section>
          <h4 className={gridStyles.sectionTitle}>Basic Information</h4>
          <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-3">
            <Field label="Job Name" value={detail.name} />
            <Field label="Namespace" value={detail.namespace} />
            <Field label="Cluster" value={clusterName} />
            <Field label="UID" value={<span className="font-mono text-xs">{detail.uid}</span>} />
            <Field
              label="Created"
              value={detail.created_at ? formatDate(detail.created_at) : "—"}
            />
            <Field
              label="Start Time"
              value={detail.start_time ? formatDate(detail.start_time) : "—"}
            />
            <Field
              label="Completion Time"
              value={detail.completion_time ? formatDate(detail.completion_time) : "—"}
            />
            <Field label="Image" value={<span className="font-mono text-xs">{detail.image}</span>} />
            <Field
              label="Created By"
              value={
                detail.created_by ? (
                  <>
                    {detail.created_by}
                    {detail.trigger === "manual" && (
                      <span className="ml-1 rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700">
                        manual
                      </span>
                    )}
                  </>
                ) : (
                  "—"
                )
              }
            />
          </dl>
          <div className="mt-3 space-y-2">
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wide text-gray-500">Labels</dt>
              <dd className="mt-1">
                <KeyValueList entries={detail.labels} />
              </dd>
            </div>
            <div>
              <dt className="text-xs font-semibold uppercase tracking-wide text-gray-500">
                Annotations
              </dt>
              <dd className="mt-1">
                <KeyValueList entries={detail.annotations} />
              </dd>
            </div>
          </div>
        </section>

        {/* ── Execution ── */}
        <section>
          <h4 className={gridStyles.sectionTitle}>Execution</h4>
          <dl className="mt-2 grid grid-cols-2 gap-x-6 gap-y-3 md:grid-cols-4">
            <Field label="Status" value={detail.status} />
            <Field label="Desired Completions" value={detail.completions ?? 1} />
            <Field label="Succeeded" value={detail.succeeded} />
            <Field
              label="Failed"
              value={
                <span className={detail.failed > 0 ? "font-semibold text-red-600" : undefined}>
                  {detail.failed}
                </span>
              }
            />
            <Field label="Active Pods" value={detail.active} />
            <Field label="Parallelism" value={detail.parallelism ?? "—"} />
            <Field label="Backoff Limit" value={detail.backoff_limit ?? "—"} />
            <Field label="Completion Mode" value={detail.completion_mode ?? "—"} />
            <Field
              label="TTL After Finished"
              value={
                detail.ttl_seconds_after_finished !== null
                  ? `${detail.ttl_seconds_after_finished}s`
                  : "Not configured"
              }
            />
            <Field label="Suspended" value={detail.suspended ? "Yes" : "No"} />
          </dl>
        </section>

        {/* ── Conditions ── */}
        {detail.conditions.length > 0 && (
          <section>
            <h4 className={gridStyles.sectionTitle}>Conditions</h4>
            <ul className="mt-2 space-y-1.5">
              {detail.conditions.map((c) => (
                <li key={`${c.type}-${c.last_transition_time}`} className="text-sm text-gray-700">
                  <span className="font-medium">{c.type}</span>
                  <span className="text-gray-500"> = {c.status}</span>
                  {c.reason && <span className="text-gray-500"> · {c.reason}</span>}
                  {c.message && <span className="text-gray-500"> — {c.message}</span>}
                </li>
              ))}
            </ul>
          </section>
        )}

        {/* ── Pods ── */}
        <section>
          <h4 className={gridStyles.sectionTitle}>
            Pods <span className="font-normal text-gray-500">({detail.pods.length})</span>
          </h4>
          {detail.pods.length === 0 ? (
            <p className="mt-2 text-sm text-gray-500">
              No pods found for this Job. They may have been cleaned up by its TTL or by the
              CronJob's history limits.
            </p>
          ) : (
            <div className={`mt-2 ${gridStyles.shell}`}>
              <div className="overflow-x-auto">
                <table className={gridStyles.table}>
                  <thead className={gridStyles.head}>
                    <tr>
                      <th className={gridStyles.headerCell}>Pod</th>
                      <th className={gridStyles.headerCell}>Phase</th>
                      <th className={gridStyles.headerCell}>Node</th>
                      <th className={gridStyles.headerCell}>Restarts</th>
                      <th className={gridStyles.headerCell}>Started</th>
                      <th className={gridStyles.headerCellCenter}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {detail.pods.map((pod) => (
                      <tr key={pod.pod_name} className={gridStyles.row}>
                        <td className={gridStyles.cell}>
                          <span className="font-mono text-xs">{pod.pod_name}</span>
                        </td>
                        <td className={gridStyles.cell}>
                          <span
                            className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                              POD_PHASE_STYLES[pod.phase ?? ""] ?? "bg-gray-100 text-gray-600"
                            }`}
                          >
                            {pod.phase ?? "Unknown"}
                          </span>
                        </td>
                        <td className={gridStyles.cell}>{pod.node ?? "—"}</td>
                        <td className={gridStyles.cell}>
                          <span className={pod.restarts > 0 ? "font-semibold text-red-600" : undefined}>
                            {pod.restarts}
                          </span>
                        </td>
                        <td className={gridStyles.cell}>
                          <span className="text-xs text-gray-600">
                            {pod.started_at ? formatDate(pod.started_at) : "—"}
                          </span>
                        </td>
                        <td className={gridStyles.centerCell}>
                          <div className="flex items-center justify-center gap-1">
                            <button
                              onClick={() => onViewPodLogs(pod)}
                              title="View Logs"
                              className="rounded p-1 text-blue-600 hover:bg-blue-50"
                            >
                              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
                            </button>
                            {canDeletePod && onDeletePod && (
                              <button
                                onClick={() => onDeletePod(pod)}
                                title="Delete Pod"
                                className="rounded p-1 text-red-600 hover:bg-red-50"
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
            </div>
          )}
        </section>
      </div>
    )}
  </ModalShell>
);

export default JobDetailModal;
