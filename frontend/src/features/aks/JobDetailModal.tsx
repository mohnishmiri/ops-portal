/**
 * Job drill-down — execution counters, conditions, the Job's pods, and
 * metadata, in the same layout as every other AKS resource detail. Pod rows
 * link out to the page's existing log viewer and pod-delete flows rather than
 * reimplementing them.
 */

import React, { useState } from "react";
import { MetricCard, MetricCardIcons } from "../../components/MetricCard";
import { JobDetail, JobPod } from "../../services/aksApi";
import { DetailGrid, GridFilterSelect, type GridColumn } from "./DetailGrid";
import { ageMs, ConditionsGrid, DetailIcons, KeyValueGrid, Truncate } from "./detailShared";
import { DetailCard, KpiRow, PropertyList, ResourceDetailShell, ResourceKindIcons } from "./ResourceDetailShell";

type Section = "overview" | "pods" | "metadata";
type PhaseFilter = "all" | "Succeeded" | "Failed" | "Running" | "Pending";

const POD_PHASE_STYLES: Record<string, string> = {
  Running: "bg-blue-100 text-blue-700",
  Succeeded: "bg-green-100 text-green-700",
  Failed: "bg-red-100 text-red-700",
  Pending: "bg-amber-100 text-amber-700",
};

const JOB_STATUS_STYLES: Record<string, string> = {
  Completed: "bg-green-100 text-green-700",
  Running: "bg-blue-100 text-blue-700",
  Failed: "bg-red-100 text-red-700",
  Suspended: "bg-gray-100 text-gray-600",
};

function duration(start: string | null, end: string | null): string {
  if (!start) return "—";
  const ms = (end ? Date.parse(end) : Date.now()) - Date.parse(start);
  if (Number.isNaN(ms) || ms < 0) return "—";
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`;
  return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
}

const actionBtn = "p-1.5 rounded-lg disabled:opacity-50";

function JobPodsGrid({
  pods,
  formatDate,
  canDeletePod,
  onViewPodLogs,
  onDeletePod,
  phase,
  onPhaseChange,
}: {
  pods: JobPod[];
  formatDate: (value: string) => string;
  canDeletePod: boolean;
  onViewPodLogs: (pod: JobPod) => void;
  onDeletePod?: (pod: JobPod) => void;
  phase: PhaseFilter;
  onPhaseChange: (phase: PhaseFilter) => void;
}) {
  const rows = phase === "all" ? pods : pods.filter((p) => p.phase === phase);
  const count = (value: string) => pods.filter((p) => p.phase === value).length;
  const columns: GridColumn<JobPod>[] = [
    { key: "name", header: "Pod", sortValue: (p) => p.pod_name, render: (p) => <Truncate value={p.pod_name} className="font-mono text-xs" maxWidth="max-w-[24rem]" /> },
    {
      key: "phase",
      header: "Phase",
      sortValue: (p) => p.phase ?? "",
      render: (p) => (
        <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${POD_PHASE_STYLES[p.phase ?? ""] ?? "bg-gray-100 text-gray-600"}`}>{p.phase ?? "Unknown"}</span>
      ),
    },
    { key: "node", header: "Node", sortValue: (p) => p.node ?? "", render: (p) => <Truncate value={p.node} className="text-xs" maxWidth="max-w-[16rem]" /> },
    { key: "ip", header: "Pod IP", sortValue: (p) => p.pod_ip ?? "", render: (p) => <span className="whitespace-nowrap font-mono text-xs">{p.pod_ip ?? "—"}</span> },
    {
      key: "restarts",
      header: "Restarts",
      align: "center",
      sortValue: (p) => p.restarts,
      render: (p) => <span className={p.restarts > 0 ? "font-semibold text-red-600" : "text-slate-600"}>{p.restarts}</span>,
    },
    { key: "started", header: "Started", sortValue: (p) => ageMs(p.started_at), render: (p) => <span className="whitespace-nowrap text-xs text-slate-600">{p.started_at ? formatDate(p.started_at) : "—"}</span> },
    {
      key: "actions",
      header: "Actions",
      align: "center",
      render: (p) => (
        <div className="flex items-center justify-center gap-1">
          <button type="button" onClick={() => onViewPodLogs(p)} title="View Logs" className={`${actionBtn} text-blue-600 hover:bg-blue-50`}>{DetailIcons.logs}</button>
          {canDeletePod && onDeletePod && (
            <button type="button" onClick={() => onDeletePod(p)} title="Delete Pod" className={`${actionBtn} text-red-600 hover:bg-red-50`}>{DetailIcons.trash}</button>
          )}
        </div>
      ),
    },
  ];
  return (
    <DetailGrid
      title="Pods"
      rows={rows}
      columns={columns}
      rowKey={(p) => p.pod_name}
      toolbar={
        <GridFilterSelect<PhaseFilter>
          label="Filter pods by phase"
          value={phase}
          onChange={onPhaseChange}
          options={[
            { value: "all", label: `All phases (${pods.length})` },
            { value: "Succeeded", label: `Succeeded (${count("Succeeded")})` },
            { value: "Failed", label: `Failed (${count("Failed")})` },
            { value: "Running", label: `Running (${count("Running")})` },
            { value: "Pending", label: `Pending (${count("Pending")})` },
          ]}
        />
      }
      searchText={(p) => `${p.pod_name} ${p.phase ?? ""} ${p.node ?? ""} ${p.pod_ip ?? ""}`}
      searchPlaceholder="Search pod, node, phase…"
      emptyText={
        phase === "all"
          ? "No pods found for this Job. They may have been cleaned up by its TTL or by the CronJob's history limits."
          : `No ${phase} pods`
      }
      initialSort={{ key: "started", direction: "asc" }}
    />
  );
}

function Overview({
  detail,
  clusterName,
  formatDate,
  onShowPods,
}: {
  detail: JobDetail;
  clusterName: string;
  formatDate: (value: string) => string;
  onShowPods: (phase: PhaseFilter) => void;
}) {
  const fmt = (v: string | null) => (v ? formatDate(v) : null);
  return (
    <>
      <KpiRow>
        <MetricCard
          title="Succeeded"
          value={`${detail.succeeded}/${detail.completions ?? 1}`}
          subtitle={`Completion mode ${detail.completion_mode ?? "NonIndexed"}`}
          icon={MetricCardIcons.checkCircle()}
          tone={detail.succeeded >= (detail.completions ?? 1) ? "green" : "att"}
          onClick={() => onShowPods("Succeeded")}
          actionLabel="Show succeeded pods"
        />
        <MetricCard
          title="Failed"
          value={detail.failed}
          subtitle={`Backoff limit ${detail.backoff_limit ?? "—"}`}
          icon={MetricCardIcons.alert()}
          tone={detail.failed > 0 ? "red" : "green"}
          onClick={() => onShowPods("Failed")}
          actionLabel="Show failed pods"
        />
        <MetricCard
          title="Active Pods"
          value={detail.active}
          subtitle={`Parallelism ${detail.parallelism ?? "—"}`}
          icon={MetricCardIcons.activity()}
          tone={detail.active > 0 ? "blue" : "slate"}
          onClick={() => onShowPods("Running")}
          actionLabel="Show running pods"
        />
        <MetricCard
          title="Duration"
          value={duration(detail.start_time, detail.completion_time)}
          subtitle={detail.completion_time ? "Finished" : detail.start_time ? "Still running" : "Not started"}
          icon={MetricCardIcons.calendar()}
          tone="att"
          onClick={() => onShowPods("all")}
          actionLabel="Show all pods"
        />
      </KpiRow>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <DetailCard title="Execution">
          <PropertyList
            items={[
              { label: "Start Time", value: fmt(detail.start_time) },
              { label: "Completion Time", value: fmt(detail.completion_time) },
              { label: "Desired Completions", value: detail.completions ?? 1 },
              { label: "Parallelism", value: detail.parallelism },
              { label: "Backoff Limit", value: detail.backoff_limit },
              { label: "TTL After Finished", value: detail.ttl_seconds_after_finished !== null ? `${detail.ttl_seconds_after_finished}s` : "Not configured" },
              { label: "Suspended", value: detail.suspended ? "Yes" : "No" },
            ]}
          />
        </DetailCard>
        <DetailCard title="Identity">
          <PropertyList
            items={[
              { label: "Cluster", value: clusterName },
              {
                label: "Created By",
                value: detail.created_by ? (
                  <>
                    {detail.created_by}
                    {detail.trigger === "manual" && (
                      <span className="ml-2 rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] font-medium text-indigo-700">manual</span>
                    )}
                  </>
                ) : null,
              },
              { label: "Created", value: fmt(detail.created_at) },
              { label: "UID", value: detail.uid, mono: true },
              { label: "Image", value: detail.image, mono: true, wide: true },
            ]}
          />
        </DetailCard>
      </div>

      <ConditionsGrid conditions={detail.conditions} formatDate={formatDate} />
    </>
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
}> = ({ clusterName, jobRef, detail, isLoading, isError, formatDate, canDeletePod, onViewPodLogs, onDeletePod, onClose }) => {
  const [section, setSection] = useState<Section>("overview");
  const [phase, setPhase] = useState<PhaseFilter>("all");
  return (
    <ResourceDetailShell
      kind="Job"
      name={jobRef.name}
      namespace={jobRef.namespace}
      icon={ResourceKindIcons.job}
      status={
        detail && (
          <span className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${JOB_STATUS_STYLES[detail.status] ?? "bg-amber-100 text-amber-700"}`}>
            {detail.status}
          </span>
        )
      }
      meta={detail?.created_by && <span>From CronJob <span className="font-medium text-slate-700">{detail.created_by}</span></span>}
      tabs={[
        { key: "overview", label: "Overview" },
        { key: "pods", label: "Pods", count: detail?.pods.length },
        { key: "metadata", label: "Metadata" },
      ]}
      activeTab={section}
      onTabChange={setSection}
      isLoading={isLoading && !detail}
      error={!isLoading && (isError || !detail) ? "Unable to load details for this Job. It may have been deleted or its TTL may have expired." : null}
      onClose={onClose}
    >
      {detail && section === "overview" && (
        <Overview
          detail={detail}
          clusterName={clusterName}
          formatDate={formatDate}
          onShowPods={(next) => {
            setPhase(next);
            setSection("pods");
          }}
        />
      )}
      {detail && section === "pods" && (
        <JobPodsGrid
          pods={detail.pods}
          formatDate={formatDate}
          canDeletePod={canDeletePod}
          onViewPodLogs={onViewPodLogs}
          onDeletePod={onDeletePod}
          phase={phase}
          onPhaseChange={setPhase}
        />
      )}
      {detail && section === "metadata" && (
        <>
          <KeyValueGrid title="Labels" entries={detail.labels} />
          <KeyValueGrid title="Annotations" entries={detail.annotations} />
        </>
      )}
    </ResourceDetailShell>
  );
};

export default JobDetailModal;
