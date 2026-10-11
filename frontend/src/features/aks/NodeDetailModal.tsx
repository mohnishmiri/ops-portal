/**
 * Node drill-down — what `kubectl describe node` shows: health and conditions,
 * live usage and its history, system info, capacity with what pods request
 * and limit, every pod on the node, events, labels, and taints. Pod rows
 * open the page's existing Pod detail.
 */

import React, { useMemo, useState } from "react";
import { MetricCard, MetricCardIcons } from "../../components/MetricCard";
import { KubernetesNodeDetail, NodePodRow, useNodeDetail } from "../../services/aksApi";
import { DetailGrid, GridFilterSelect, type GridColumn } from "./DetailGrid";
import {
  apiErrorDetail,
  ConditionsGrid,
  formatBytes,
  formatCores,
  type EventFilter,
  EventsGrid,
  formatAge,
  KeyValueGrid,
  PodStatusBadge,
  ReadyBadge,
  ResourceUsage,
  Truncate,
} from "./detailShared";
import { ClusterUtilisation } from "./NodePoolUtilisation";
import { DetailCard, KpiRow, PropertyList, ResourceDetailShell, ResourceKindIcons } from "./ResourceDetailShell";

type Section = "overview" | "pods" | "events" | "labels";
// Ready is a node's only "good when True" condition; the rest (pressure, and
// node-problem-detector's KubeletProblem, FrequentContainerdRestart, ...) report problems.
const nodeConditionHealthy = (c: { type: string; status: string }) => (c.type === "Ready" ? c.status === "True" : c.status === "False");
type PodFilter = "active" | "all" | "not-ready" | "finished";

export { formatBytes, formatCores } from "./detailShared";

const pct = (value: number | null | undefined) => (value == null ? "—" : `${value}%`);
const tone = (value: number | null | undefined) => (value == null ? "slate" : value >= 90 ? "red" : value >= 75 ? "amber" : "green");

function PodsGrid({
  detail,
  filter,
  onFilterChange,
  sortKey,
  onOpenPod,
}: {
  detail: KubernetesNodeDetail;
  filter: PodFilter;
  onFilterChange: (f: PodFilter) => void;
  sortKey: string;
  onOpenPod: (pod: NodePodRow) => void;
}) {
  const matches = (p: NodePodRow, f: PodFilter) =>
    f === "active" ? !p.terminated : f === "not-ready" ? !p.terminated && !p.ready : f === "finished" ? p.terminated : true;
  const count = (f: PodFilter) => detail.pods.filter((p) => matches(p, f)).length;
  const columns: GridColumn<NodePodRow>[] = [
    {
      key: "name",
      header: "Pod",
      sortValue: (p) => p.pod_name,
      render: (p) => (
        <button type="button" onClick={() => onOpenPod(p)} className="text-left font-mono text-xs font-medium text-att-700 hover:text-att-900 hover:underline">
          <Truncate value={p.pod_name} maxWidth="max-w-[20rem]" />
        </button>
      ),
    },
    { key: "namespace", header: "Namespace", sortValue: (p) => p.namespace, render: (p) => <span className="whitespace-nowrap text-xs text-slate-700">{p.namespace}</span> },
    { key: "status", header: "Status", sortValue: (p) => p.status ?? p.phase ?? "", render: (p) => <PodStatusBadge status={p.status ?? p.phase} /> },
    {
      key: "ready",
      header: "Ready",
      align: "center",
      sortValue: (p) => p.ready_containers - p.total_containers,
      render: (p) => <span className={`font-mono text-xs ${!p.terminated && p.ready_containers < p.total_containers ? "font-semibold text-amber-700" : "text-slate-700"}`}>{p.ready_containers}/{p.total_containers}</span>,
    },
    { key: "restarts", header: "Restarts", align: "center", sortValue: (p) => p.restarts, render: (p) => <span className={p.restarts ? "font-semibold text-red-600" : "text-slate-600"}>{p.restarts}</span> },
    {
      key: "cpu",
      header: "CPU",
      sortValue: (p) => p.cpu_usage_m ?? p.cpu_request_m / 1e6,
      render: (p) => <ResourceUsage kind="cpu" used={p.cpu_usage_m} request={p.cpu_request_m} limit={p.cpu_limit_m} />,
    },
    {
      key: "memory",
      header: "Memory",
      sortValue: (p) => p.memory_usage_bytes ?? p.memory_request_bytes / 1e6,
      render: (p) => <ResourceUsage kind="memory" used={p.memory_usage_bytes} request={p.memory_request_bytes} limit={p.memory_limit_bytes} />,
    },
    {
      key: "owner",
      header: "Owner",
      sortValue: (p) => `${p.owner_kind ?? ""}/${p.owner_name ?? ""}`,
      render: (p) => (p.owner_kind ? <Truncate value={`${p.owner_kind}/${p.owner_name}`} className="text-xs text-slate-600" maxWidth="max-w-[14rem]" /> : <span className="text-xs text-slate-400">—</span>),
    },
    { key: "age", header: "Age", sortValue: (p) => p.started_at ?? "", render: (p) => <span className="whitespace-nowrap text-xs text-slate-600">{formatAge(p.started_at)}</span> },
  ];
  return (
    <DetailGrid
      key={sortKey}
      title="Pods on this Node"
      rows={detail.pods.filter((p) => matches(p, filter))}
      columns={columns}
      rowKey={(p) => `${p.namespace}/${p.pod_name}`}
      toolbar={
        <GridFilterSelect<PodFilter>
          label="Filter pods"
          value={filter}
          onChange={onFilterChange}
          options={[
            { value: "active", label: `Running and pending (${count("active")})` },
            { value: "not-ready", label: `Not ready (${count("not-ready")})` },
            { value: "finished", label: `Completed or failed (${count("finished")})` },
            { value: "all", label: `All pods (${detail.pods.length})` },
          ]}
        />
      }
      searchText={(p) => `${p.pod_name} ${p.namespace} ${p.owner_name ?? ""} ${p.status ?? ""}`}
      searchPlaceholder="Search pod, namespace, owner…"
      emptyText={filter === "all" ? "No pods are scheduled on this node." : "No pods match this filter."}
      initialSort={{ key: sortKey, direction: sortKey === "name" ? "asc" : "desc" }}
      defaultPageSize={25}
    />
  );
}

export function NodeDetailModal({
  clusterId,
  name,
  formatDate,
  onOpenPod,
  onClose,
}: {
  clusterId: string;
  name: string;
  formatDate: (value: string) => string;
  onOpenPod?: (pod: NodePodRow) => void;
  onClose: () => void;
}) {
  const { data: detail, isLoading, isError, error } = useNodeDetail(clusterId, name);
  const [section, setSection] = useState<Section>("overview");
  const [podFilter, setPodFilter] = useState<PodFilter>("active");
  const [podSort, setPodSort] = useState("name");
  const [eventType, setEventType] = useState<EventFilter>("all");
  const warnings = useMemo(() => (detail?.events ?? []).filter((e) => e.type === "Warning").length, [detail]);
  const notReadyPods = useMemo(() => (detail?.pods ?? []).filter((p) => !p.terminated && !p.ready).length, [detail]);
  const showPods = (filter: PodFilter, sort = "name") => {
    setPodFilter(filter);
    setPodSort(sort);
    setSection("pods");
  };

  return (
    <ResourceDetailShell
      kind="Node"
      name={name}
      icon={ResourceKindIcons.nodepool}
      status={
        detail && (
          <span className="inline-flex items-center gap-2">
            <ReadyBadge ready={detail.ready} />
            {detail.unschedulable && <span className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">Cordoned</span>}
          </span>
        )
      }
      meta={
        detail && (
          <>
            {detail.pool && <span>Pool <span className="font-medium text-slate-700">{detail.pool}</span></span>}
            {detail.instance_type && <span className="font-mono">{detail.instance_type}</span>}
            {detail.zone && <span>Zone {detail.zone}</span>}
          </>
        )
      }
      tabs={[
        { key: "overview", label: "Overview" },
        { key: "pods", label: "Pods", count: detail?.pods.filter((p) => !p.terminated).length, attention: notReadyPods > 0 },
        { key: "events", label: "Events", count: detail?.events.length, attention: warnings > 0 },
        { key: "labels", label: "Labels & Taints", count: detail ? Object.keys(detail.labels).length + detail.taints.length : undefined },
      ]}
      activeTab={section}
      onTabChange={setSection}
      isLoading={isLoading}
      error={isError && !detail ? apiErrorDetail(error, "Unable to read this node from the cluster.") : null}
      onClose={onClose}
    >
      {detail && section === "overview" && (
        <>
          {(detail.pressure.length > 0 || !detail.ready) && (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              {!detail.ready && "The node isn't ready. "}
              {detail.pressure.length > 0 && `Pressure: ${detail.pressure.join(", ")}.`}
            </div>
          )}
          <KpiRow>
            <MetricCard
              title="Status"
              value={detail.ready ? "Ready" : "Not ready"}
              subtitle={detail.unschedulable ? "Cordoned: no new pods" : detail.pressure.length ? detail.pressure.join(", ") : "No resource pressure"}
              icon={MetricCardIcons.checkCircle()}
              tone={!detail.ready ? "red" : detail.unschedulable || detail.pressure.length ? "amber" : "green"}
              valueClassName="text-xl"
              onClick={() => {
                setEventType(warnings ? "Warning" : "all");
                setSection("events");
              }}
              actionLabel="Show the node's events"
            />
            <MetricCard
              title="Pods"
              value={`${detail.allocated.pods}/${detail.allocatable.pods}`}
              subtitle={notReadyPods ? `${notReadyPods} not ready` : "Running and pending / max"}
              icon={MetricCardIcons.layers()}
              tone={notReadyPods ? "amber" : "att"}
              onClick={() => showPods(notReadyPods ? "not-ready" : "active")}
              actionLabel="Show the pods on this node"
            />
            <MetricCard
              title={detail.usage ? "CPU" : "CPU Requested"}
              value={pct(detail.usage ? detail.usage.cpu_pct : detail.allocated.cpu_request_pct)}
              subtitle={
                detail.usage
                  ? `${formatCores(detail.usage.cpu_m)} of ${formatCores(detail.allocatable.cpu_m)} in use · ${pct(detail.allocated.cpu_request_pct)} requested`
                  : `${formatCores(detail.allocated.cpu_request_m)} of ${formatCores(detail.allocatable.cpu_m)} · live usage unavailable`
              }
              icon={MetricCardIcons.activity()}
              tone={tone(detail.usage ? detail.usage.cpu_pct : detail.allocated.cpu_request_pct)}
              onClick={() => showPods("active", "cpu")}
              actionLabel="Show pods by CPU use"
            />
            <MetricCard
              title={detail.usage ? "Memory" : "Memory Requested"}
              value={pct(detail.usage ? detail.usage.memory_pct : detail.allocated.memory_request_pct)}
              subtitle={
                detail.usage
                  ? `${formatBytes(detail.usage.memory_bytes)} of ${formatBytes(detail.allocatable.memory_bytes)} in use · ${pct(detail.allocated.memory_request_pct)} requested`
                  : `${formatBytes(detail.allocated.memory_request_bytes)} of ${formatBytes(detail.allocatable.memory_bytes)} · live usage unavailable`
              }
              icon={MetricCardIcons.server()}
              tone={tone(detail.usage ? detail.usage.memory_pct : detail.allocated.memory_request_pct)}
              onClick={() => showPods("active", "memory")}
              actionLabel="Show pods by memory use"
            />
          </KpiRow>

          <ClusterUtilisation clusterId={clusterId} node={detail.name} formatDate={formatDate} title="CPU & Memory History" />

          <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
            <DetailCard title="System">
              <PropertyList
                items={[
                  { label: "OS Image", value: detail.system.os_image },
                  { label: "Kernel", value: detail.system.kernel_version, mono: true },
                  { label: "Container Runtime", value: detail.system.container_runtime, mono: true },
                  { label: "Kubelet", value: detail.system.kubelet_version, mono: true },
                  { label: "Architecture", value: [detail.system.operating_system, detail.system.architecture].filter(Boolean).join(" / ") },
                  { label: "Created", value: detail.created_at ? `${formatDate(detail.created_at)} (${formatAge(detail.created_at)})` : null },
                  { label: "Node Image", value: detail.node_image_version, mono: true, wide: true },
                  ...detail.addresses.map((a) => ({ label: a.type, value: a.address, mono: true })),
                ]}
              />
            </DetailCard>
            <DetailCard title="Capacity" subtitle="Allocatable is what pods can use after the system's reservations.">
              <PropertyList
                items={[
                  { label: "CPU (Allocatable / Capacity)", value: `${formatCores(detail.allocatable.cpu_m)} / ${formatCores(detail.capacity.cpu_m)}` },
                  { label: "Memory (Allocatable / Capacity)", value: `${formatBytes(detail.allocatable.memory_bytes)} / ${formatBytes(detail.capacity.memory_bytes)}` },
                  { label: "Pods (Allocatable)", value: detail.allocatable.pods },
                  { label: "Ephemeral Storage", value: formatBytes(detail.allocatable.ephemeral_storage_bytes) },
                  { label: "CPU Requests", value: `${formatCores(detail.allocated.cpu_request_m)} (${pct(detail.allocated.cpu_request_pct)} of allocatable)` },
                  { label: "Memory Requests", value: `${formatBytes(detail.allocated.memory_request_bytes)} (${pct(detail.allocated.memory_request_pct)} of allocatable)` },
                  { label: "CPU Limits", value: `${formatCores(detail.allocated.cpu_limit_m)} (${pct(detail.allocated.cpu_limit_pct)} of allocatable)` },
                  { label: "Memory Limits", value: `${formatBytes(detail.allocated.memory_limit_bytes)} (${pct(detail.allocated.memory_limit_pct)} of allocatable)` },
                  { label: "Live Usage", value: detail.usage ? `${formatCores(detail.usage.cpu_m)} CPU · ${formatBytes(detail.usage.memory_bytes)} memory` : "metrics-server not available", wide: true },
                ]}
              />
            </DetailCard>
          </div>
          <ConditionsGrid conditions={detail.conditions} formatDate={formatDate} isHealthy={nodeConditionHealthy} />
        </>
      )}

      {detail && section === "pods" && (
        <PodsGrid detail={detail} filter={podFilter} onFilterChange={setPodFilter} sortKey={podSort} onOpenPod={(p) => onOpenPod?.(p)} />
      )}
      {detail && section === "events" && <EventsGrid events={detail.events} formatDate={formatDate} type={eventType} onTypeChange={setEventType} />}
      {detail && section === "labels" && (
        <>
          <KeyValueGrid title="Node Labels" entries={detail.labels} />
          <DetailGrid
            title="Taints"
            rows={detail.taints.map((t) => {
              const [kv, effect = ""] = t.split(":");
              const [key, value = ""] = kv.split("=");
              return { key, value, effect };
            })}
            columns={[
              { key: "key", header: "Key", sortValue: (t) => t.key, render: (t) => <span className="font-mono text-xs text-slate-800">{t.key}</span> },
              { key: "value", header: "Value", sortValue: (t) => t.value, render: (t) => <span className="font-mono text-xs text-slate-700">{t.value || "—"}</span> },
              { key: "effect", header: "Effect", sortValue: (t) => t.effect, render: (t) => <span className="text-xs text-slate-700">{t.effect}</span> },
            ]}
            rowKey={(t) => `${t.key}:${t.effect}`}
            searchText={(t) => `${t.key} ${t.value} ${t.effect}`}
            searchPlaceholder="Search taints…"
            emptyText="No taints on this node."
          />
        </>
      )}
    </ResourceDetailShell>
  );
}

export default NodeDetailModal;
