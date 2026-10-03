/**
 * Deployment drill-down: overview, pods, ReplicaSet revisions, events
 * (Deployment + ReplicaSet), and the live manifest — the same layout as the
 * StatefulSet/DaemonSet detail.
 */

import React, { useState } from "react";
import { gridStyles, Spinner } from "../../components/gridStyles";
import { DeploymentDetail, useDeploymentDetail, WorkloadPod } from "../../services/aksApi";
import { GridStateRow } from "./aksGridShared";
import {
  apiErrorDetail,
  ConditionList,
  DetailTabs,
  EventList,
  KeyValue,
  LabelChips,
  SectionTitle,
  WorkloadPodsTable,
  WorkloadStatusBadge,
  YamlView,
} from "./detailShared";
import { ModalShell } from "./K8sResourceModals";
import { DownloadLogsButton, LogArchiveDownload } from "./LogArchiveDownload";

type Section = "overview" | "pods" | "revisions" | "events" | "yaml";

function strategyText(d: DeploymentDetail): string {
  if (d.update_strategy !== "RollingUpdate") return d.update_strategy ?? "—";
  return `RollingUpdate (maxSurge ${d.max_surge ?? "25%"}, maxUnavailable ${d.max_unavailable ?? "25%"})`;
}

export function DeploymentDetailModal({
  clusterId,
  namespace,
  name,
  formatDate,
  logDownload,
  canDeletePod,
  onOpenPod,
  onViewPodLogs,
  onDeletePod,
  onClose,
}: {
  clusterId: string;
  namespace: string;
  name: string;
  formatDate: (value: string) => string;
  logDownload: LogArchiveDownload;
  canDeletePod: boolean;
  onOpenPod: (pod: WorkloadPod) => void;
  onViewPodLogs: (pod: WorkloadPod) => void;
  onDeletePod?: (pod: WorkloadPod) => void;
  onClose: () => void;
}) {
  const [section, setSection] = useState<Section>("overview");
  const { data: detail, isLoading, isError, error } = useDeploymentDetail(clusterId, namespace, name);
  const fmt = (v: string | null | undefined) => (v ? formatDate(v) : "—");

  const tabs: { key: Section; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "pods", label: `Pods${detail ? ` (${detail.pods.length})` : ""}` },
    { key: "revisions", label: `ReplicaSets${detail ? ` (${detail.revisions.length})` : ""}` },
    { key: "events", label: `Events${detail ? ` (${detail.events.length})` : ""}` },
    { key: "yaml", label: "YAML" },
  ];

  return (
    <ModalShell title={`Deployment: ${namespace}/${name}`} onClose={onClose} wide>
      {isLoading && (
        <div className="flex items-center justify-center gap-2 py-8 text-sm text-gray-500"><Spinner className="h-4 w-4" />Loading deployment…</div>
      )}
      {isError && !detail && (
        <p className="text-sm text-red-600">{apiErrorDetail(error, "Failed to load deployment details.")}</p>
      )}
      {detail && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-2 text-sm text-gray-600">
              <WorkloadStatusBadge status={detail.status} />
              <span className="font-mono">{detail.ready}/{detail.desired} ready</span>
              {detail.revision && <span>· revision {detail.revision}</span>}
              {detail.paused && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs text-amber-800">Rollout paused</span>}
            </div>
            <DownloadLogsButton
              download={logDownload}
              downloadKey={`deployment:${namespace}/${name}`}
              request={{ clusterId, kind: "deployment", namespace, name }}
              label={`Deployment ${namespace}/${name}`}
              podCount={detail.pods.length}
            />
          </div>

          <DetailTabs tabs={tabs} active={section} onChange={setSection} />

          {section === "overview" && (
            <div className="grid grid-cols-1 gap-x-6 md:grid-cols-2">
              <div>
                <KeyValue label="Ready / Desired" value={`${detail.ready}/${detail.desired}`} />
                <KeyValue label="Up-to-date" value={detail.updated} />
                <KeyValue label="Available" value={detail.available} />
                <KeyValue label="Unavailable" value={detail.unavailable} />
                <KeyValue label="Strategy" value={strategyText(detail)} />
                <KeyValue label="Min Ready Seconds" value={detail.min_ready_seconds} />
                <KeyValue label="Progress Deadline" value={detail.progress_deadline_seconds != null ? `${detail.progress_deadline_seconds}s` : "—"} />
                <KeyValue label="Revision History Limit" value={detail.revision_history_limit ?? "—"} />
                <KeyValue label="Generation" value={`${detail.observed_generation ?? "—"} / ${detail.generation ?? "—"}`} />
                <KeyValue label="Created" value={fmt(detail.created_at)} />
              </div>
              <div>
                <KeyValue label="Selector" value={Object.entries(detail.selector).map(([k, v]) => `${k}=${v}`).join(", ") || "—"} />
                <KeyValue label="Service Account" value={detail.service_account} />
                <KeyValue label="CPU req / limit" value={`${detail.cpu_request || "—"} / ${detail.cpu_limit || "—"}`} />
                <KeyValue label="Memory req / limit" value={`${detail.memory_request || "—"} / ${detail.memory_limit || "—"}`} />
                <KeyValue label="Node Selector" value={Object.entries(detail.node_selector).map(([k, v]) => `${k}=${v}`).join(", ") || "—"} />
                {detail.hpa ? (
                  <>
                    <KeyValue label="Autoscaler (HPA)" value={`${detail.hpa.name}: ${detail.hpa.min_replicas}–${detail.hpa.max_replicas} replicas`} />
                    <KeyValue label="HPA current / desired" value={`${detail.hpa.current_replicas ?? "—"} / ${detail.hpa.desired_replicas ?? "—"}`} />
                    {detail.hpa.metrics.map((m) => (
                      <KeyValue key={m.name} label={`HPA ${m.name}`} value={`${m.current ?? "?"} of ${m.target ?? "?"} target`} />
                    ))}
                  </>
                ) : (
                  <KeyValue label="Autoscaler (HPA)" value="None" />
                )}
              </div>

              <div className="md:col-span-2">
                <SectionTitle>Containers</SectionTitle>
                <ul className="space-y-1">
                  {detail.containers.map((c) => (
                    <li key={c.name} className="text-sm">
                      <span className="font-medium">{c.name}</span>{" "}
                      <span className="font-mono text-xs text-gray-600 break-all">{c.image}</span>
                      {c.ports.length > 0 && <span className="ml-2 text-xs text-gray-500">ports {c.ports.join(", ")}</span>}
                    </li>
                  ))}
                </ul>
                <SectionTitle>Conditions</SectionTitle>
                <ConditionList conditions={detail.conditions} formatDate={formatDate} />
                <SectionTitle>Labels</SectionTitle>
                <LabelChips labels={detail.labels} />
                <SectionTitle>Annotations</SectionTitle>
                <LabelChips labels={detail.annotations} />
              </div>
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
            <div className="overflow-x-auto">
              <table className={gridStyles.table}>
                <thead className={gridStyles.head}>
                  <tr>
                    <th className={gridStyles.headerCell}>Revision</th>
                    <th className={gridStyles.headerCell}>ReplicaSet</th>
                    <th className={gridStyles.headerCell}>Pods</th>
                    <th className={gridStyles.headerCell}>Images</th>
                    <th className={gridStyles.headerCell}>Created</th>
                  </tr>
                </thead>
                <tbody>
                  {detail.revisions.length === 0 && <GridStateRow colSpan={5} emptyText="No ReplicaSets" />}
                  {detail.revisions.map((r) => (
                    <tr key={r.name} className={gridStyles.row}>
                      <td className={gridStyles.cell}>
                        {r.revision || "—"}
                        {r.is_current && <span className="ml-2 px-1.5 py-0.5 rounded bg-green-100 text-green-700 text-[10px] font-medium">current</span>}
                      </td>
                      <td className={gridStyles.cell}><span className="font-mono text-xs">{r.name}</span></td>
                      <td className={gridStyles.cell}><span className="font-mono text-xs">{r.ready}/{r.desired}</span></td>
                      <td className={gridStyles.cell}><span className="font-mono text-xs break-all">{r.images.join(", ") || "—"}</span></td>
                      <td className={gridStyles.cell}><span className="text-xs">{fmt(r.created_at)}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {section === "events" && <EventList events={detail.events} formatDate={formatDate} showObject />}

          {section === "yaml" && <YamlView yaml={detail.yaml} />}
        </div>
      )}
    </ModalShell>
  );
}

export default DeploymentDetailModal;
