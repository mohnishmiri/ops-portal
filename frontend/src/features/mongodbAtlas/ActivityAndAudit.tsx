/**
 * Activity — every stop / start the portal asked Atlas for, manual or
 * scheduled, followed to its outcome per cluster.
 *
 * Audit — every MongoDB Atlas change made through the portal (stop / start,
 * schedules, tier, failover, snapshots, alerts, database users, IP access
 * list), from the shared audit_logs table. Database-user passwords are never
 * recorded.
 */

import React, { useCallback, useMemo, useState } from "react";
import { gridStyles, SortableHeader } from "../../components/gridStyles";
import { GridHeader, GridMessageRow, GridPagerBar, Modal, textMatches, useGridRows } from "../access/accessShared";
import { formatAxiosError } from "../../services/apiErrors";
import { type AtlasOperation, type AuditEntry, useAtlasAudit, useOperations } from "../../services/mongodbAtlasApi";
import { exportToCsv } from "../../utils/csvExport";
import { OperationSummary } from "./PowerDialog";
import {
  ACTION_LABEL,
  ATLAS_PAGE_SIZE,
  AtlasIcons,
  buttonTone,
  formatDuration,
  IconAction,
  OperationStatusChip,
  TRIGGER_LABEL,
} from "./shared";

type OpSort = "requested" | "status" | "action";

export const OperationsGrid: React.FC<{ formatDate: (v: string | null | undefined) => string }> = ({ formatDate }) => {
  const { data, isLoading, error } = useOperations();
  const [status, setStatus] = useState("");
  const [open, setOpen] = useState<AtlasOperation | null>(null);
  const rows = useMemo(() => (data?.operations ?? []).filter((op) => !status || op.status === status), [data, status]);
  const grid = useGridRows<AtlasOperation, OpSort>(rows, {
    matches: useCallback(
      (op: AtlasOperation, q: string) =>
        textMatches(q, op.schedule_name, op.requested_by, op.reason, op.status, ACTION_LABEL[op.action], ...op.targets.map((t) => `${t.cluster_name} ${t.project_name}`)),
      [],
    ),
    accessor: useCallback((op: AtlasOperation, key: OpSort) => (key === "status" ? op.status : key === "action" ? op.action : op.requested_at), []),
    initialSort: { key: "requested", direction: "desc" },
    pageSize: ATLAS_PAGE_SIZE,
  });
  const header = (label: string, key: OpSort) => (
    <th className={gridStyles.headerCell}>
      <SortableHeader label={label} active={grid.sort.key === key} direction={grid.sort.direction} onClick={() => grid.toggleSort(key)} />
    </th>
  );

  return (
    <div className={gridStyles.shell}>
      <GridHeader
        title="Stop / start activity"
        subtitle={data ? `${data.in_progress} in progress · last ${data.count} operations` : "Loading…"}
        search={grid.search}
        onSearch={grid.setSearch}
        placeholder="Search cluster, schedule, person…"
      >
        <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Filter by outcome" className="rounded-lg border border-att-200 bg-white px-2 py-2 text-sm">
          <option value="">Any outcome</option>
          <option value="in_progress">In progress</option>
          <option value="completed">Completed</option>
          <option value="partial">Partly failed</option>
          <option value="failed">Failed</option>
          <option value="skipped">Skipped</option>
        </select>
      </GridHeader>
      <div className="overflow-x-auto">
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              {header("Requested", "requested")}
              {header("Action", "action")}
              <th className={gridStyles.headerCell}>Clusters</th>
              <th className={gridStyles.headerCell}>Trigger</th>
              <th className={gridStyles.headerCell}>By</th>
              {header("Outcome", "status")}
              <th className={`${gridStyles.headerCell} text-right`}>Took</th>
              <th className={gridStyles.headerCellCenter}>Details</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <GridMessageRow colSpan={8}>Loading…</GridMessageRow>
            ) : error ? (
              <GridMessageRow colSpan={8} tone="error">{formatAxiosError(error, "Could not load activity")}</GridMessageRow>
            ) : grid.pageRows.length === 0 ? (
              <GridMessageRow colSpan={8}>{rows.length ? "Nothing matches." : "No stops or starts yet."}</GridMessageRow>
            ) : (
              grid.pageRows.map((op) => (
                <tr key={op.id} className={gridStyles.row}>
                  <td className={`${gridStyles.cell} whitespace-nowrap`}>{formatDate(op.requested_at)}</td>
                  <td className={gridStyles.cell}>
                    <span className={op.action === "pause" ? "font-semibold text-red-700" : "font-semibold text-green-700"}>{ACTION_LABEL[op.action]}</span>
                  </td>
                  <td className={gridStyles.cell}>
                    <div className="max-w-[18rem] truncate font-mono text-xs" title={op.targets.map((t) => `${t.project_name}/${t.cluster_name}: ${t.status}`).join("\n")}>
                      {op.targets.map((t) => t.cluster_name).join(", ")}
                    </div>
                  </td>
                  <td className={gridStyles.cell}>
                    {TRIGGER_LABEL[op.trigger]}
                    {op.schedule_name && <div className="text-[11px] text-slate-500">{op.schedule_name}</div>}
                  </td>
                  <td className={gridStyles.cell}>{op.requested_by.startsWith("system:") ? "Scheduler" : op.requested_by}</td>
                  <td className={gridStyles.cell}>
                    <OperationStatusChip status={op.status} />
                    {op.error_message && <div className="mt-0.5 max-w-[16rem] truncate text-[11px] text-red-600" title={op.error_message}>{op.error_message}</div>}
                  </td>
                  <td className={`${gridStyles.cell} text-right tabular-nums`}>{formatDuration(op.duration_seconds)}</td>
                  <td className={gridStyles.centerCell}>
                    <IconAction title="Per-cluster outcome" tone="att" onClick={() => setOpen(op)}>
                      <AtlasIcons.details />
                    </IconAction>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <GridPagerBar page={grid.page} totalPages={grid.totalPages} total={grid.total} pageSize={grid.pageSize} onPage={grid.setPage} noun="operations" />
      {open && (
        <Modal
          title={`${ACTION_LABEL[open.action]} — operation #${open.id}`}
          subtitle={`${TRIGGER_LABEL[open.trigger]}${open.schedule_name ? ` “${open.schedule_name}”` : ""} · ${formatDate(open.requested_at)}`}
          onClose={() => setOpen(null)}
          widthClass="max-w-2xl"
          footer={<button type="button" className={buttonTone.neutral} onClick={() => setOpen(null)}>Close</button>}
        >
          {open.reason && <p className="text-sm text-slate-700"><span className="font-semibold">Reason:</span> {open.reason}</p>}
          <OperationSummary op={(data?.operations ?? []).find((o) => o.id === open.id) ?? open} />
        </Modal>
      )}
    </div>
  );
};

// ── Audit ────────────────────────────────────────────────────────────────────

const AUDIT_LABELS: Record<string, string> = {
  atlas_cluster_pause: "Stop requested",
  atlas_cluster_resume: "Start requested",
  atlas_cluster_pause_finished: "Stop finished",
  atlas_cluster_resume_finished: "Start finished",
  atlas_cluster_tier_change: "Tier change",
  atlas_cluster_test_failover: "Test failover",
  atlas_snapshot_create: "Snapshot taken",
  atlas_alert_acknowledge: "Alert acknowledged",
  atlas_alert_unacknowledge: "Alert un-acknowledged",
  atlas_database_user_create: "Database user created",
  atlas_database_user_update: "Database user changed",
  atlas_database_user_delete: "Database user deleted",
  atlas_access_list_add: "IP access entry added",
  atlas_access_list_delete: "IP access entry removed",
  atlas_schedule_create: "Schedule created",
  atlas_schedule_update: "Schedule changed",
  atlas_schedule_delete: "Schedule deleted",
  atlas_schedule_skip: "Schedule run skipped",
  atlas_schedule_unskip: "Schedule skip removed",
};

type AuditSort = "time" | "user" | "action" | "status";

export const AuditGrid: React.FC<{ formatDate: (v: string | null | undefined) => string }> = ({ formatDate }) => {
  const { data, isLoading, error } = useAtlasAudit();
  const [open, setOpen] = useState<AuditEntry | null>(null);
  const rows = useMemo(() => data?.entries ?? [], [data]);
  const grid = useGridRows<AuditEntry, AuditSort>(rows, {
    matches: useCallback(
      (e: AuditEntry, q: string) => textMatches(q, e.user, e.action, AUDIT_LABELS[e.action], e.resource, e.status, e.ip_address, JSON.stringify(e.details)),
      [],
    ),
    accessor: useCallback(
      (e: AuditEntry, key: AuditSort) => (key === "user" ? e.user : key === "action" ? AUDIT_LABELS[e.action] ?? e.action : key === "status" ? e.status : e.timestamp),
      [],
    ),
    initialSort: { key: "time", direction: "desc" },
    pageSize: 15,
  });
  const header = (label: string, key: AuditSort) => (
    <th className={gridStyles.headerCell}>
      <SortableHeader label={label} active={grid.sort.key === key} direction={grid.sort.direction} onClick={() => grid.toggleSort(key)} />
    </th>
  );
  const exportCsv = () =>
    exportToCsv<AuditEntry>("mongodb-atlas-audit", rows, [
      { header: "Time (UTC)", value: (e) => e.timestamp },
      { header: "User", value: (e) => e.user },
      { header: "Action", value: (e) => AUDIT_LABELS[e.action] ?? e.action },
      { header: "Resource", value: (e) => e.resource },
      { header: "Status", value: (e) => e.status },
      { header: "IP", value: (e) => e.ip_address },
      { header: "Details", value: (e) => JSON.stringify(e.details) },
    ]);

  return (
    <div className={gridStyles.shell}>
      <GridHeader
        title="Audit log"
        subtitle="Every MongoDB Atlas change made through the portal, newest first (latest 500)"
        search={grid.search}
        onSearch={grid.setSearch}
        placeholder="Search user, action, cluster…"
      >
        <button type="button" onClick={exportCsv} className={buttonTone.neutral} disabled={!rows.length}>
          <AtlasIcons.download />
          CSV
        </button>
      </GridHeader>
      <div className="overflow-x-auto">
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              {header("When", "time")}
              {header("User", "user")}
              {header("Action", "action")}
              <th className={gridStyles.headerCell}>Resource</th>
              {header("Result", "status")}
              <th className={gridStyles.headerCellCenter}>Details</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <GridMessageRow colSpan={6}>Loading…</GridMessageRow>
            ) : error ? (
              <GridMessageRow colSpan={6} tone="error">{formatAxiosError(error, "Could not load the audit log")}</GridMessageRow>
            ) : grid.pageRows.length === 0 ? (
              <GridMessageRow colSpan={6}>{rows.length ? "Nothing matches." : "No Atlas changes recorded yet."}</GridMessageRow>
            ) : (
              grid.pageRows.map((e) => (
                <tr key={e.id} className={gridStyles.row}>
                  <td className={`${gridStyles.cell} whitespace-nowrap`}>{formatDate(e.timestamp)}</td>
                  <td className={gridStyles.cell}>{e.user.startsWith("system:") ? "Scheduler" : e.user}</td>
                  <td className={gridStyles.cell}>{AUDIT_LABELS[e.action] ?? e.action}</td>
                  <td className={gridStyles.monoCell}>{e.resource ?? "—"}</td>
                  <td className={gridStyles.cell}>
                    <span className={e.status === "success" ? "text-xs font-semibold text-green-700" : "text-xs font-semibold text-red-700"}>
                      {e.status === "success" ? "Success" : "Failed"}
                    </span>
                    {typeof e.details.error === "string" && (
                      <div className="max-w-[16rem] truncate text-[11px] text-red-600" title={e.details.error}>{e.details.error}</div>
                    )}
                  </td>
                  <td className={gridStyles.centerCell}>
                    <IconAction title="All recorded details" tone="att" onClick={() => setOpen(e)}>
                      <AtlasIcons.details />
                    </IconAction>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <GridPagerBar page={grid.page} totalPages={grid.totalPages} total={grid.total} pageSize={grid.pageSize} onPage={grid.setPage} noun="entries" />
      {open && (
        <Modal
          title={AUDIT_LABELS[open.action] ?? open.action}
          subtitle={`${open.user} · ${formatDate(open.timestamp)}${open.ip_address ? ` · from ${open.ip_address}` : ""}`}
          onClose={() => setOpen(null)}
          widthClass="max-w-2xl"
          footer={<button type="button" className={buttonTone.neutral} onClick={() => setOpen(null)}>Close</button>}
        >
          <pre className="max-h-[50vh] overflow-auto rounded-lg bg-slate-50 p-3 text-xs text-slate-700">{JSON.stringify(open.details, null, 2)}</pre>
        </Modal>
      )}
    </div>
  );
};
