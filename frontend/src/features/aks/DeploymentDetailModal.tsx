/**
 * Deployment drill-down: overview, pods, ReplicaSet revisions, events
 * (Deployment + ReplicaSet), metadata, and the live manifest — the same
 * layout as every other AKS resource detail.
 */

import React, { useMemo, useState } from "react";
import { MetricCard, MetricCardIcons } from "../../components/MetricCard";
import { DeploymentDetail, DeploymentRevision, useDeploymentDetail, WorkloadPod } from "../../services/aksApi";
import { DetailGrid, type GridColumn } from "./DetailGrid";
import {
  apiErrorDetail,
  ConditionsGrid,
  ContainerSpecGrid,
  EventsGrid,
  formatAge,
  KeyValueGrid,
  type PodFilter,
  splitImage,
  Truncate,
  WorkloadPodsGrid,
  WorkloadStatusBadge,
  YamlViewer,
} from "./detailShared";
import { DownloadLogsButton, LogArchiveDownload } from "./LogArchiveDownload";
import { DetailCard, KpiRow, PropertyList, ResourceDetailShell, ResourceKindIcons } from "./ResourceDetailShell";

type Section = "overview" | "pods" | "revisions" | "events" | "metadata" | "yaml";

function selectorText(selector: Record<string, string>): string {
  return Object.entries(selector).map(([k, v]) => `${k}=${v}`).join(", ");
}

function ReplicaSetsGrid({ revisions, formatDate }: { revisions: DeploymentRevision[]; formatDate: (v: string) => string }) {
  const columns: GridColumn<DeploymentRevision>[] = [
    {
      key: "revision",
      header: "Revision",
      sortValue: (r) => r.revision,
      render: (r) => (
        <span className="inline-flex items-center gap-2 whitespace-nowrap font-semibold text-slate-800">
          {r.revision || "—"}
          {r.is_current && <span className="rounded-full bg-green-100 px-2 py-0.5 text-[10px] font-semibold text-green-700">current</span>}
        </span>
      ),
    },
    { key: "name", header: "ReplicaSet", sortValue: (r) => r.name, render: (r) => <Truncate value={r.name} className="font-mono text-xs" maxWidth="max-w-[22rem]" /> },
    {
      key: "pods",
      header: "Pods Ready",
      align: "center",
      sortValue: (r) => r.desired,
      render: (r) => <span className={`font-mono text-xs ${r.ready < r.desired ? "font-semibold text-amber-700" : ""}`}>{r.ready}/{r.desired}</span>,
    },
    {
      key: "images",
      header: "Version",
      sortValue: (r) => r.images.join(","),
      render: (r) => (
        <span className="flex flex-wrap gap-1" title={r.images.join("\n")}>
          {r.images.length === 0 && "—"}
          {r.images.map((img) => (
            <span key={img} className="whitespace-nowrap rounded bg-indigo-50 px-2 py-0.5 font-mono text-xs font-semibold text-indigo-700">{splitImage(img).tag}</span>
          ))}
        </span>
      ),
    },
    { key: "created", header: "Created", sortValue: (r) => r.created_at ?? "", render: (r) => <span className="whitespace-nowrap text-xs text-slate-600">{r.created_at ? formatDate(r.created_at) : "—"}</span> },
  ];
  return (
    <DetailGrid
      title="ReplicaSets"
      rows={revisions}
      columns={columns}
      rowKey={(r) => r.name}
      searchText={(r) => `${r.revision} ${r.name} ${r.images.join(" ")}`}
      searchPlaceholder="Search revision, ReplicaSet, image…"
      emptyText="No ReplicaSets"
      initialSort={{ key: "revision", direction: "desc" }}
    />
  );
}

function Overview({
  detail,
  formatDate,
  onShowPods,
  onShowRevisions,
}: {
  detail: DeploymentDetail;
  formatDate: (v: string) => string;
  onShowPods: (filter: PodFilter) => void;
  onShowRevisions: () => void;
}) {
  const restarts = detail.pods.reduce((n, p) => n + p.restarts, 0);
  const restartedPods = detail.pods.filter((p) => p.restarts > 0).length;
  const fullyReady = detail.desired > 0 && detail.ready === detail.desired;
  const hpa = detail.hpa;
  return (
    <>
      <KpiRow>
        <MetricCard
          title="Pods Ready"
          value={`${detail.ready}/${detail.desired}`}
          subtitle={`${detail.available} available · ${detail.unavailable} unavailable`}
          icon={MetricCardIcons.checkCircle()}
          tone={detail.desired === 0 ? "slate" : fullyReady ? "green" : "amber"}
          onClick={() => onShowPods(detail.pods.some((p) => !p.ready) ? "not-ready" : "all")}
          actionLabel="Show the pods that are not ready"
        />
        <MetricCard
          title="Up-to-date"
          value={`${detail.updated}/${detail.desired}`}
          subtitle={detail.revision ? `Revision ${detail.revision}` : "Revision unknown"}
          icon={MetricCardIcons.layers()}
          tone="att"
          onClick={onShowRevisions}
          actionLabel="Show ReplicaSet revisions"
        />
        <MetricCard
          title="Restarts"
          value={restarts}
          subtitle={restartedPods ? `${restartedPods} pod${restartedPods === 1 ? "" : "s"} restarted` : "No pod has restarted"}
          icon={MetricCardIcons.activity()}
          tone={restarts > 0 ? "red" : "green"}
          onClick={() => onShowPods(restartedPods ? "restarted" : "all")}
          actionLabel="Show pods that restarted"
        />
        <MetricCard
          title="Autoscaling"
          value={hpa ? `${hpa.min_replicas}–${hpa.max_replicas}` : "Off"}
          subtitle={hpa ? `${hpa.current_replicas ?? "?"} current · ${hpa.desired_replicas ?? "?"} desired` : "No HorizontalPodAutoscaler"}
          icon={MetricCardIcons.server()}
          tone={hpa ? "indigo" : "slate"}
          onClick={() => onShowPods("all")}
          actionLabel="Show the pods the autoscaler manages"
        />
      </KpiRow>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <DetailCard title="Rollout">
          <PropertyList
            items={[
              { label: "Strategy", value: detail.update_strategy },
              detail.update_strategy === "RollingUpdate" && { label: "Max Surge / Unavailable", value: `${detail.max_surge ?? "25%"} / ${detail.max_unavailable ?? "25%"}` },
              { label: "Min Ready Seconds", value: `${detail.min_ready_seconds}s` },
              { label: "Progress Deadline", value: detail.progress_deadline_seconds != null ? `${detail.progress_deadline_seconds}s` : null },
              { label: "Revision History Limit", value: detail.revision_history_limit },
              { label: "Generation (observed / spec)", value: `${detail.observed_generation ?? "—"} / ${detail.generation ?? "—"}` },
              { label: "Paused", value: detail.paused ? <span className="font-semibold text-amber-700">Yes</span> : "No" },
            ]}
          />
        </DetailCard>
        <DetailCard title="Scheduling & Identity">
          <PropertyList
            items={[
              { label: "Selector", value: selectorText(detail.selector), mono: true, wide: true },
              { label: "Service Account", value: detail.service_account },
              { label: "Created", value: detail.created_at ? `${formatDate(detail.created_at)} (${formatAge(detail.created_at)})` : null },
              { label: "Node Selector", value: selectorText(detail.node_selector), mono: true, wide: true },
              ...(hpa
                ? hpa.metrics.map((m) => ({ label: `HPA ${m.name}`, value: `${m.current ?? "?"} of ${m.target ?? "?"} target` }))
                : []),
            ]}
          />
        </DetailCard>
      </div>

      <ContainerSpecGrid containers={detail.containers} />
      <ConditionsGrid conditions={detail.conditions} formatDate={formatDate} />
    </>
  );
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
  const [podFilter, setPodFilter] = useState<PodFilter>("all");
  const { data: detail, isLoading, isError, error } = useDeploymentDetail(clusterId, namespace, name);
  const warnings = useMemo(() => (detail?.events ?? []).filter((e) => e.type === "Warning").length, [detail]);

  return (
    <ResourceDetailShell
      kind="Deployment"
      name={name}
      namespace={namespace}
      icon={ResourceKindIcons.deployment}
      status={detail && <WorkloadStatusBadge status={detail.status} />}
      meta={
        detail && (
          <>
            <span className="font-mono">{detail.ready}/{detail.desired} ready</span>
            {detail.revision && <span>Revision {detail.revision}</span>}
            {detail.paused && <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-800">Rollout paused</span>}
          </>
        )
      }
      actions={
        detail && (
          <DownloadLogsButton
            download={logDownload}
            downloadKey={`deployment:${namespace}/${name}`}
            request={{ clusterId, kind: "deployment", namespace, name }}
            label={`Deployment ${namespace}/${name}`}
            podCount={detail.pods.length}
          />
        )
      }
      tabs={[
        { key: "overview", label: "Overview" },
        { key: "pods", label: "Pods", count: detail?.pods.length },
        { key: "revisions", label: "ReplicaSets", count: detail?.revisions.length },
        { key: "events", label: "Events", count: detail?.events.length, attention: warnings > 0 },
        { key: "metadata", label: "Metadata" },
        { key: "yaml", label: "YAML" },
      ]}
      activeTab={section}
      onTabChange={setSection}
      isLoading={isLoading}
      error={isError && !detail ? apiErrorDetail(error, "Failed to load deployment details.") : null}
      onClose={onClose}
    >
      {detail && section === "overview" && (
        <Overview
          detail={detail}
          formatDate={formatDate}
          onShowPods={(filter) => {
            setPodFilter(filter);
            setSection("pods");
          }}
          onShowRevisions={() => setSection("revisions")}
        />
      )}
      {detail && section === "pods" && (
        <WorkloadPodsGrid
          pods={detail.pods}
          onOpenPod={onOpenPod}
          onViewPodLogs={onViewPodLogs}
          onDeletePod={onDeletePod}
          canDeletePod={canDeletePod}
          filter={podFilter}
          onFilterChange={setPodFilter}
        />
      )}
      {detail && section === "revisions" && <ReplicaSetsGrid revisions={detail.revisions} formatDate={formatDate} />}
      {detail && section === "events" && <EventsGrid events={detail.events} formatDate={formatDate} showObject />}
      {detail && section === "metadata" && (
        <>
          <KeyValueGrid title="Labels" entries={detail.labels} />
          <KeyValueGrid title="Annotations" entries={detail.annotations} />
        </>
      )}
      {detail && section === "yaml" && <YamlViewer yaml={detail.yaml} fileName={`${namespace}_${name}_deployment.yaml`} />}
    </ResourceDetailShell>
  );
}

export default DeploymentDetailModal;
