/**
 * One cluster in detail: what it is, how busy it is, its backups, what Atlas
 * recorded about it, and the administrative actions the portal's API key can
 * take on it (tier change, test failover, on-demand snapshot).
 */

import React, { useMemo, useState } from "react";
import { gridStyles, Spinner } from "../../components/gridStyles";
import { GridPagerBar, Modal } from "../access/accessShared";
import { formatAxiosError } from "../../services/apiErrors";
import {
  type AtlasCluster,
  useChangeTier,
  useEvents,
  useSnapshots,
  useTakeSnapshot,
  useTestFailover,
} from "../../services/mongodbAtlasApi";
import {
  AtlasIcons,
  buttonTone,
  ClusterStatusChip,
  CopyButton,
  EnvironmentChip,
  formatBytes,
  InfoNote,
  inputClass,
  labelClass,
  relativeTime,
  useAtlasCan,
} from "./shared";
import { UtilizationCharts } from "./UtilizationCharts";

type Tab = "overview" | "utilization" | "backups" | "activity" | "admin";

const TIERS = ["M10", "M20", "M30", "M40", "M50", "M60", "M80", "M140", "M200", "M300", "R40", "R50", "R60", "R80", "R200", "R300"];

const Fact: React.FC<{ label: string; children: React.ReactNode }> = ({ label, children }) => (
  <div className="rounded-lg border border-att-100 bg-white px-3 py-2">
    <dt className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">{label}</dt>
    <dd className="mt-0.5 text-sm text-slate-800">{children}</dd>
  </div>
);

const Overview: React.FC<{ cluster: AtlasCluster; formatDate: (v: string | null | undefined) => string }> = ({ cluster, formatDate }) => (
  <div className="space-y-4">
    {cluster.auto_resume_warning && (
      <InfoNote tone="warning">
        Paused for {cluster.paused_days} days. Atlas starts a paused cluster by itself after 30 days.
      </InfoNote>
    )}
    <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      <Fact label="Tier">{cluster.tier ?? "—"}</Fact>
      <Fact label="Provider / region">
        {cluster.provider ?? "—"} · {cluster.regions.join(", ") || "—"}
      </Fact>
      <Fact label="Type">
        {cluster.cluster_type ?? "—"}
        {cluster.shard_count > 1 ? ` · ${cluster.shard_count} shards` : ""} · {cluster.node_count} nodes
      </Fact>
      <Fact label="MongoDB">{cluster.mongo_version ?? "—"}</Fact>
      <Fact label="Disk">{cluster.disk_size_gb != null ? `${cluster.disk_size_gb} GB` : "—"}{cluster.autoscaling.disk_enabled ? " · auto-grows" : ""}</Fact>
      <Fact label="Compute auto-scaling">
        {cluster.autoscaling.compute_enabled
          ? `${cluster.autoscaling.min_tier ?? "?"} – ${cluster.autoscaling.max_tier ?? "?"}${cluster.autoscaling.scale_down_enabled ? " (scales down)" : ""}`
          : "Off"}
      </Fact>
      <Fact label="Backup">
        {cluster.backup_enabled ? "On" : "Off"}
        {cluster.pit_enabled ? " · point-in-time" : ""}
      </Fact>
      <Fact label="Termination protection">{cluster.termination_protection ? "On" : "Off"}</Fact>
      <Fact label="Created">{formatDate(cluster.created_at)}</Fact>
      <Fact label="Paused since">
        {cluster.paused ? (cluster.paused_since ? `${formatDate(cluster.paused_since)} (${relativeTime(cluster.paused_since)})` : "Not paused by the portal") : "—"}
      </Fact>
      <Fact label="Pausable">{cluster.pausable ? "Yes" : cluster.pause_blocker ?? "No"}</Fact>
      <Fact label="Environment">
        <EnvironmentChip environment={cluster.environment} />
      </Fact>
    </dl>
    {cluster.connection_string && (
      <div>
        <p className={labelClass}>Connection string (no credentials)</p>
        <div className="flex items-center gap-2">
          <code className="flex-1 truncate rounded-lg border border-att-100 bg-slate-50 px-3 py-2 font-mono text-xs text-slate-700">
            {cluster.connection_string}
          </code>
          <CopyButton value={cluster.connection_string} />
        </div>
      </div>
    )}
    <div className="grid gap-4 md:grid-cols-2">
      <div>
        <p className={labelClass}>Tags</p>
        {cluster.tags.length ? (
          <div className="flex flex-wrap gap-1.5">
            {cluster.tags.map((t) => (
              <span key={t.key} className="rounded-md bg-att-50 px-2 py-0.5 font-mono text-xs text-att-800">
                {t.key}={t.value}
              </span>
            ))}
          </div>
        ) : (
          <p className="text-xs text-slate-400">None. Add an <span className="font-mono">environment</span> tag in Atlas to classify it.</p>
        )}
      </div>
      <div>
        <p className={labelClass}>Schedules</p>
        {cluster.schedules?.length ? (
          <ul className="space-y-1 text-sm">
            {cluster.schedules.map((s) => (
              <li key={s.id} className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-slate-800">{s.name}</span>
                {!s.is_enabled && <span className="text-xs text-slate-400">(disabled)</span>}
                {s.next_stop_at && <span className="text-xs text-slate-500">stop {relativeTime(s.next_stop_at)}</span>}
                {s.next_start_at && <span className="text-xs text-slate-500">start {relativeTime(s.next_start_at)}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-xs text-slate-400">Not on any start/stop schedule.</p>
        )}
      </div>
    </div>
  </div>
);

const Backups: React.FC<{ cluster: AtlasCluster; formatDate: (v: string | null | undefined) => string }> = ({ cluster, formatDate }) => {
  const can = useAtlasCan();
  const { data, isLoading, isError, error } = useSnapshots(cluster.project_id, cluster.name, cluster.backup_enabled);
  const take = useTakeSnapshot();
  const [description, setDescription] = useState("On-demand snapshot from OpsPortal");
  const [retention, setRetention] = useState(7);
  const [page, setPage] = useState(0);
  const snapshots = data?.snapshots ?? [];
  const pageSize = 8;
  const totalPages = Math.max(1, Math.ceil(snapshots.length / pageSize));
  const rows = snapshots.slice(page * pageSize, (page + 1) * pageSize);

  if (!cluster.backup_enabled) return <InfoNote>Cloud Backup is off for this cluster.</InfoNote>;
  return (
    <div className="space-y-3">
      {can("atlas_cluster_admin") && (
        <div className="flex flex-wrap items-end gap-2 rounded-lg border border-att-100 bg-att-50/40 p-3">
          <div className="min-w-[16rem] flex-1">
            <label htmlFor="snap-desc" className={labelClass}>Description</label>
            <input id="snap-desc" value={description} maxLength={200} onChange={(e) => setDescription(e.target.value)} className={inputClass} />
          </div>
          <div className="w-32">
            <label htmlFor="snap-ret" className={labelClass}>Keep (days)</label>
            <input
              id="snap-ret"
              type="number"
              min={1}
              max={365}
              value={retention}
              onChange={(e) => setRetention(Number(e.target.value))}
              className={inputClass}
            />
          </div>
          <button
            type="button"
            className={buttonTone.primary}
            disabled={take.isPending || cluster.paused || !description.trim() || retention < 1 || retention > 365}
            onClick={() => take.mutate({ projectId: cluster.project_id, clusterName: cluster.name, description: description.trim(), retention_days: retention })}
            title={cluster.paused ? "Start the cluster to take a snapshot" : undefined}
          >
            <AtlasIcons.download />
            {take.isPending ? "Requesting…" : "Take snapshot"}
          </button>
        </div>
      )}
      {take.isSuccess && <InfoNote>Snapshot requested. Atlas lists it as queued, then in progress, then completed.</InfoNote>}
      {take.isError && <InfoNote tone="error">{formatAxiosError(take.error, "Could not take a snapshot")}</InfoNote>}
      <div className={gridStyles.shell}>
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}>Created</th>
                <th className={gridStyles.headerCell}>Type</th>
                <th className={gridStyles.headerCell}>Status</th>
                <th className={`${gridStyles.headerCell} text-right`}>Size</th>
                <th className={gridStyles.headerCell}>Expires</th>
                <th className={gridStyles.headerCell}>Description</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={6} className="px-4 py-6 text-center text-sm text-slate-400"><Spinner className="mx-auto h-5 w-5" /></td></tr>
              ) : isError ? (
                <tr><td colSpan={6} className="px-4 py-6 text-center text-sm text-red-600">{formatAxiosError(error, "Could not load snapshots")}</td></tr>
              ) : rows.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-6 text-center text-sm text-slate-400">No snapshots yet.</td></tr>
              ) : (
                rows.map((s) => (
                  <tr key={s.id} className={gridStyles.row}>
                    <td className={gridStyles.cell}>{formatDate(s.created_at)}</td>
                    <td className={gridStyles.cell}>{s.type === "onDemand" ? "On demand" : s.frequency ? `Scheduled · ${s.frequency}` : s.type ?? "—"}</td>
                    <td className={gridStyles.cell}>{s.status ?? "—"}</td>
                    <td className={`${gridStyles.cell} text-right tabular-nums`}>{formatBytes(s.size_bytes)}</td>
                    <td className={gridStyles.cell}>{formatDate(s.expires_at)}</td>
                    <td className={gridStyles.cell}>{s.description ?? "—"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <GridPagerBar page={page} totalPages={totalPages} total={snapshots.length} pageSize={pageSize} onPage={setPage} noun="snapshots" />
      </div>
    </div>
  );
};

const ActivityFeed: React.FC<{ cluster: AtlasCluster; formatDate: (v: string | null | undefined) => string }> = ({ cluster, formatDate }) => {
  const [page, setPage] = useState(1);
  const pageSize = 50;
  const { data, isLoading, isError, error } = useEvents(cluster.project_id, cluster.name, page, pageSize);
  const total = data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className={gridStyles.shell}>
      <div className="max-h-[28rem] overflow-auto">
        <table className={gridStyles.table}>
          <thead className={gridStyles.stickyHead}>
            <tr>
              <th className={gridStyles.headerCell}>When</th>
              <th className={gridStyles.headerCell}>Event</th>
              <th className={gridStyles.headerCell}>By</th>
              <th className={gridStyles.headerCell}>Host</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={4} className="px-4 py-6 text-center"><Spinner className="mx-auto h-5 w-5" /></td></tr>
            ) : isError ? (
              <tr><td colSpan={4} className="px-4 py-6 text-center text-sm text-red-600">{formatAxiosError(error, "Could not load the Atlas activity feed")}</td></tr>
            ) : !data?.events.length ? (
              <tr><td colSpan={4} className="px-4 py-6 text-center text-sm text-slate-400">Atlas recorded no events for this cluster.</td></tr>
            ) : (
              data.events.map((e) => (
                <tr key={e.id} className={gridStyles.row}>
                  <td className={`${gridStyles.cell} whitespace-nowrap`}>{formatDate(e.created_at)}</td>
                  <td className={gridStyles.cell}>
                    {e.description}
                    <span className="ml-2 font-mono text-[11px] text-slate-400">{e.event_type}</span>
                  </td>
                  <td className={gridStyles.cell}>{e.actor}</td>
                  <td className={gridStyles.monoCell}>{e.host ?? e.replica_set ?? "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <GridPagerBar page={page - 1} totalPages={totalPages} total={total} pageSize={pageSize} onPage={(p) => setPage(p + 1)} noun="events" />
    </div>
  );
};

const Administration: React.FC<{ cluster: AtlasCluster }> = ({ cluster }) => {
  const can = useAtlasCan();
  const changeTier = useChangeTier();
  const failover = useTestFailover();
  const [tier, setTier] = useState(cluster.tier ?? "M10");
  const [confirmName, setConfirmName] = useState("");
  const [reason, setReason] = useState("");
  const allowed = can("atlas_cluster_admin");
  const nameOk = !cluster.is_production || confirmName.trim() === cluster.name;
  const tiers = useMemo(() => {
    const family = (cluster.tier ?? "M").charAt(0);
    return TIERS.filter((t) => t.startsWith(family === "R" ? "R" : "M") || t === cluster.tier);
  }, [cluster.tier]);
  const busy = cluster.paused || cluster.state !== "IDLE";

  if (!allowed) {
    return <InfoNote>You can view this cluster. Tier changes, test failover and snapshots need the “atlas_cluster_admin” permission.</InfoNote>;
  }
  return (
    <div className="space-y-4">
      {busy && <InfoNote tone="warning">{cluster.paused ? "Start the cluster before changing it." : `Atlas is busy (${cluster.state}); wait until it is IDLE.`}</InfoNote>}
      {cluster.is_production && (
        <div>
          <label htmlFor="admin-confirm" className={labelClass}>
            {cluster.environment === "production" ? "Production" : "Unclassified"} cluster — type <span className="font-mono">{cluster.name}</span> to enable the actions below
          </label>
          <input id="admin-confirm" value={confirmName} onChange={(e) => setConfirmName(e.target.value)} autoComplete="off" className={`${inputClass} font-mono`} />
        </div>
      )}
      <div>
        <label htmlFor="admin-reason" className={labelClass}>Reason <span className="font-normal text-slate-400">(recorded in the audit log)</span></label>
        <input id="admin-reason" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} className={inputClass} />
      </div>
      <section className="rounded-xl border border-att-100 p-4">
        <h4 className="text-sm font-semibold text-slate-800">Change tier</h4>
        <p className="mt-1 text-xs text-slate-500">
          Atlas resizes one node at a time with a rolling restart; the cluster stays available. Every electable and read-only node moves to the new size.
          {cluster.autoscaling.compute_enabled && ` Compute auto-scaling keeps it between ${cluster.autoscaling.min_tier} and ${cluster.autoscaling.max_tier}.`}
        </p>
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <div className="w-40">
            <label htmlFor="admin-tier" className={labelClass}>New tier</label>
            <select id="admin-tier" value={tier} onChange={(e) => setTier(e.target.value)} className={inputClass}>
              {tiers.map((t) => (
                <option key={t} value={t}>
                  {t}
                  {t === cluster.tier ? " (current)" : ""}
                </option>
              ))}
            </select>
          </div>
          <button
            type="button"
            className={buttonTone.primary}
            disabled={busy || !nameOk || tier === cluster.tier || changeTier.isPending}
            onClick={() =>
              changeTier.mutate({
                projectId: cluster.project_id,
                clusterName: cluster.name,
                instance_size: tier,
                confirm_name: cluster.is_production ? confirmName.trim() : undefined,
                reason: reason.trim() || undefined,
              })
            }
          >
            {changeTier.isPending ? "Requesting…" : `Change to ${tier}`}
          </button>
        </div>
        {changeTier.isSuccess && <div className="mt-2"><InfoNote>Atlas accepted the change and is applying it (state UPDATING).</InfoNote></div>}
        {changeTier.isError && <div className="mt-2"><InfoNote tone="error">{formatAxiosError(changeTier.error, "Tier change failed")}</InfoNote></div>}
      </section>
      <section className="rounded-xl border border-att-100 p-4">
        <h4 className="text-sm font-semibold text-slate-800">Test failover</h4>
        <p className="mt-1 text-xs text-slate-500">
          Restarts the primary so a secondary takes over — proves the application reconnects. Expect a few seconds of failed writes.
        </p>
        <button
          type="button"
          className={`${buttonTone.amber} mt-3`}
          disabled={busy || !nameOk || failover.isPending}
          onClick={() =>
            failover.mutate({
              projectId: cluster.project_id,
              clusterName: cluster.name,
              confirm_name: cluster.is_production ? confirmName.trim() : undefined,
              reason: reason.trim() || undefined,
            })
          }
        >
          <AtlasIcons.bolt />
          {failover.isPending ? "Requesting…" : "Start test failover"}
        </button>
        {failover.isSuccess && <div className="mt-2"><InfoNote>Failover requested. Atlas restarts the primary shortly.</InfoNote></div>}
        {failover.isError && <div className="mt-2"><InfoNote tone="error">{formatAxiosError(failover.error, "Test failover failed")}</InfoNote></div>}
      </section>
    </div>
  );
};

export const ClusterDetail: React.FC<{
  cluster: AtlasCluster;
  initialTab?: Tab;
  onClose: () => void;
  formatDate: (v: string | null | undefined) => string;
}> = ({ cluster, initialTab = "overview", onClose, formatDate }) => {
  const [tab, setTab] = useState<Tab>(initialTab);
  const tabs: { key: Tab; label: string }[] = [
    { key: "overview", label: "Overview" },
    { key: "utilization", label: "Utilization" },
    { key: "backups", label: "Backups" },
    { key: "activity", label: "Atlas activity" },
    { key: "admin", label: "Administration" },
  ];
  return (
    <Modal
      title={cluster.name}
      subtitle={
        <span className="inline-flex flex-wrap items-center gap-2">
          <span>{cluster.project_name}</span>
          <ClusterStatusChip cluster={cluster} />
          <EnvironmentChip environment={cluster.environment} />
        </span>
      }
      onClose={onClose}
      widthClass="max-w-6xl"
      footer={
        <button type="button" onClick={onClose} className={buttonTone.neutral}>
          Close
        </button>
      }
    >
      <div role="tablist" aria-label="Cluster sections" className="flex flex-wrap gap-1 border-b border-att-100">
        {tabs.map((t) => (
          <button
            key={t.key}
            type="button"
            role="tab"
            aria-selected={tab === t.key}
            onClick={() => setTab(t.key)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium ${
              tab === t.key ? "border-att-500 text-att-700" : "border-transparent text-slate-500 hover:text-att-600"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <div role="tabpanel">
        {tab === "overview" && <Overview cluster={cluster} formatDate={formatDate} />}
        {tab === "utilization" && (
          <UtilizationCharts projectId={cluster.project_id} clusterName={cluster.name} paused={cluster.paused} formatDate={(v) => formatDate(v)} />
        )}
        {tab === "backups" && <Backups cluster={cluster} formatDate={formatDate} />}
        {tab === "activity" && <ActivityFeed cluster={cluster} formatDate={formatDate} />}
        {tab === "admin" && <Administration cluster={cluster} />}
      </div>
    </Modal>
  );
};
