/**
 * Drill-down views for every Infrastructure Alerts grid row: alerts (VM, PG,
 * expiry), their configurations, synced Azure resources, alert schedules and
 * sent notifications. Built on the AKS ResourceDetailShell so every detail in
 * the portal looks and behaves the same.
 *
 * The host reads the same React Query caches the page already holds, so a
 * view always shows the newest copy of its row, and it links related records
 * (an alert opens its configuration, a VM opens its open alerts, a
 * notification opens the alert it was about).
 */

import React, { useMemo, useState } from "react";
import { MetricCard } from "../../components/MetricCard";
import { Spinner } from "../../components/gridStyles";
import {
  type AlertKind,
  type AlertScheduleConfig,
  apiErrorMessage,
  type ExpiryAlert,
  type ExpiryConfig,
  getAlertTypeLabel,
  getEnvLabel,
  getNotificationTypeLabel,
  formatRelativeTime,
  type ManagedDisk,
  type NotificationHistory,
  type PGFlexServer,
  type PGFlexServerAlert,
  type PGFlexServerConfig,
  type StorageAccount,
  type StorageAlertConfig,
  useAcknowledgeExpiryAlert,
  useAcknowledgePGFlexAlert,
  useAcknowledgeVMAlert,
  useAlertNotifications,
  useAlertScheduleConfigs,
  useAzureDisks,
  useAzurePGServers,
  useAzureStorageAccounts,
  useAzureVMs,
  useExpiryAlerts,
  useExpiryConfigs,
  useNotificationHistory,
  usePGFlexAlerts,
  usePGFlexConfigs,
  usePGMetrics,
  useResolveExpiryAlert,
  useResolvePGFlexAlert,
  useResolveVMAlert,
  useStorageAlertConfigs,
  useUpdateAlertScheduleConfig,
  useUpdateExpiryConfig,
  useUpdatePGFlexConfig,
  useUpdateStorageAlertConfig,
  useUpdateVMThresholdConfig,
  useVMMetrics,
  useVMThresholdAlerts,
  useVMThresholdConfigs,
  type VMInfo,
  type VMThresholdAlert,
  type VMThresholdConfig,
} from "../../services/infraAlertApi";
import { DetailGrid, type GridColumn } from "../aks/DetailGrid";
import { CopyButton, KeyValueGrid } from "../aks/detailShared";
import { DetailCard, KpiRow, PropertyList, ResourceDetailShell } from "../aks/ResourceDetailShell";
import type { ConfigEditorTarget } from "./ConfigEditors";
import {
  type ConfirmRequest,
  DiskAdminPanel,
  PGAdminPanel,
  PGDatabasesPanel,
  PortalLinkCard,
  RunCommandPanel,
  TagEditor,
  UtilizationPanel,
  VMAdminPanel,
  VMDisksGrid,
} from "./ResourceAdmin";
import {
  AlertStatusBadge,
  ConfigStateBadge,
  daysLeftText,
  daysLeftTone,
  describeSchedule,
  EXPIRY_TYPE_META,
  ExpiryHealthBadge,
  ExpiryWindowBar,
  expiryHealth,
  formatCalendar,
  humanize,
  InfraIcons,
  isSnoozed,
  PowerStateBadge,
  SeverityBadge,
  ThresholdBar,
} from "./shared";

export type InfraDetailTarget =
  | { kind: "vm-alert"; id: number; snapshot?: VMThresholdAlert }
  | { kind: "pg-alert"; id: number; snapshot?: PGFlexServerAlert }
  | { kind: "expiry-alert"; id: number; snapshot?: ExpiryAlert }
  | { kind: "vm-config" | "pg-config" | "storage-config" | "expiry-config"; id: number }
  | { kind: "vm" | "pg-server" | "storage-account" | "disk"; id: string }
  | { kind: "schedule"; id: number }
  | { kind: "notification"; id: number; snapshot?: NotificationHistory };

export type PowerKind = "vm" | "pg";
export type PowerAction = "start" | "stop" | "restart";
export interface PowerTarget {
  name: string;
  resource_group: string;
  subscription_id?: string;
}

export type { ConfirmRequest };

export interface DetailHostProps {
  target: InfraDetailTarget;
  onOpen: (target: InfraDetailTarget) => void;
  onClose: () => void;
  onEditConfig: (target: ConfigEditorTarget) => void;
  onEditSchedule: (schedule: AlertScheduleConfig) => void;
  onDeleteConfig: (kind: "vm" | "pg" | "storage" | "expiry", id: number, name: string) => void;
  onDeleteSchedule: (schedule: AlertScheduleConfig) => void;
  onPower: (kind: PowerKind, action: PowerAction, resource: PowerTarget) => void;
  powerPendingKey: string | null;
  onToast: (message: string, type?: "success" | "error" | "info") => void;
  /** The page's confirmation dialog (shown above the detail view). */
  onConfirm: (request: ConfirmRequest) => void;
  onDeleteDisk: (disk: ManagedDisk) => void;
  canWrite: boolean;
  canPowerVM: boolean;
  canPowerPG: boolean;
  canRunCommand: boolean;
  canAdminResources: boolean;
  canDeleteDisks: boolean;
  subscriptionNames: Map<string, string>;
  subscriptionTiers: Map<string, "prod" | "nonprod">;
  formatDate: (value: string) => string;
}

const actionButton =
  "inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg border px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 [&>svg]:h-4 [&>svg]:w-4";
const tones = {
  neutral: "border-att-200 bg-white text-slate-700 hover:bg-att-50",
  blue: "border-blue-200 bg-blue-50 text-blue-700 hover:bg-blue-100",
  green: "border-green-200 bg-green-50 text-green-700 hover:bg-green-100",
  red: "border-red-200 bg-red-50 text-red-700 hover:bg-red-100",
  amber: "border-amber-200 bg-amber-50 text-amber-800 hover:bg-amber-100",
};

function HeaderButton({ tone = "neutral", icon, children, ...rest }: React.ButtonHTMLAttributes<HTMLButtonElement> & { tone?: keyof typeof tones; icon?: React.ReactNode }) {
  return (
    <button type="button" className={`${actionButton} ${tones[tone]}`} {...rest}>
      {icon}
      {children}
    </button>
  );
}

function subName(map: Map<string, string>, id: string | null | undefined) {
  if (!id) return "—";
  const name = map.get(id);
  return name ? (
    <span>
      {name} <span className="font-mono text-[11px] text-slate-400">{id}</span>
    </span>
  ) : (
    <span className="font-mono text-xs">{id}</span>
  );
}

function Mono({ value }: { value: string | null | undefined }) {
  if (!value) return <span className="text-slate-400">—</span>;
  return (
    <span className="inline-flex max-w-full items-start gap-2">
      <span className="break-all font-mono text-xs">{value}</span>
      <CopyButton value={value} />
    </span>
  );
}

function Recipients({ emails }: { emails: string[] | undefined }) {
  if (!emails?.length) return <p className="text-sm text-slate-500">No recipients — alerts are shown in the portal only.</p>;
  return (
    <div className="flex flex-wrap gap-1.5">
      {emails.map((email) => (
        <span key={email} className="rounded-full bg-att-50 px-2.5 py-1 text-xs font-medium text-att-800 ring-1 ring-att-200">
          {email}
        </span>
      ))}
    </div>
  );
}

function EmptyNote({ children }: { children: React.ReactNode }) {
  return <p className="rounded-lg border border-dashed border-att-200 bg-white px-4 py-6 text-center text-sm text-slate-500">{children}</p>;
}

interface TimelineEntry {
  label: string;
  at?: string | null;
  by?: string | null;
  note?: string | null;
  tone: "red" | "blue" | "green" | "slate";
}

function Timeline({ entries, formatDate }: { entries: TimelineEntry[]; formatDate: (value: string) => string }) {
  const dot = { red: "bg-red-500", blue: "bg-blue-500", green: "bg-green-500", slate: "bg-slate-400" };
  const shown = entries.filter((e) => e.at);
  if (!shown.length) return <p className="text-sm text-slate-500">No activity yet.</p>;
  return (
    <ol className="relative space-y-4 border-l border-att-100 pl-5">
      {shown.map((entry) => (
        <li key={entry.label} className="relative">
          <span className={`absolute -left-[1.6rem] top-1 h-2.5 w-2.5 rounded-full ring-4 ring-white ${dot[entry.tone]}`} />
          <p className="text-sm font-semibold text-slate-800">{entry.label}</p>
          <p className="text-xs text-slate-500">
            {formatDate(entry.at as string)} · {formatRelativeTime(entry.at as string)}
            {entry.by ? ` · ${entry.by === "system" ? "automatically" : `by ${entry.by}`}` : ""}
          </p>
          {entry.note && <p className="mt-1 rounded-lg bg-slate-50 px-3 py-2 text-sm text-slate-700">{entry.note}</p>}
        </li>
      ))}
    </ol>
  );
}

function alertTimeline(alert: VMThresholdAlert | PGFlexServerAlert | ExpiryAlert): TimelineEntry[] {
  return [
    { label: "Alert raised", at: alert.created_at, tone: "red" },
    { label: "Acknowledged", at: alert.acknowledged_at, by: alert.acknowledged_by, tone: "blue" },
    { label: alert.status === "resolved" ? "Last checked before resolution" : "Last checked", at: alert.status === "resolved" ? null : alert.updated_at, tone: "slate" },
    { label: "Resolved", at: alert.resolved_at, by: alert.resolved_by, note: alert.resolution_notes, tone: "green" },
  ];
}

/** Notifications grid inside a detail view. */
function NotificationsGrid({
  rows,
  isLoading,
  formatDate,
  onOpen,
}: {
  rows: NotificationHistory[];
  isLoading?: boolean;
  formatDate: (value: string) => string;
  onOpen?: (row: NotificationHistory) => void;
}) {
  if (isLoading) {
    return (
      <div className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
        <Spinner /> Loading notifications…
      </div>
    );
  }
  const columns: GridColumn<NotificationHistory>[] = [
    { key: "sent", header: "Sent", sortValue: (n) => n.sent_at ?? "", render: (n) => <span className="whitespace-nowrap text-xs">{n.sent_at ? formatDate(n.sent_at) : "Pending"}</span> },
    { key: "type", header: "Type", sortValue: (n) => n.notification_type, render: (n) => <span className="text-xs font-medium">{getNotificationTypeLabel(n.notification_type)}</span> },
    { key: "to", header: "Recipient", sortValue: (n) => n.recipient_email, render: (n) => <span className="text-xs">{n.recipient_email}</span> },
    { key: "subject", header: "Subject", render: (n) => <span className="block max-w-md truncate text-xs" title={n.subject}>{n.subject}</span> },
    {
      key: "status",
      header: "Status",
      sortValue: (n) => n.status,
      render: (n) => (
        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${n.status === "sent" ? "bg-green-50 text-green-700" : n.status === "failed" ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-800"}`}>
          {n.status}
        </span>
      ),
    },
  ];
  return (
    <DetailGrid
      title="Notifications"
      rows={rows}
      columns={columns}
      rowKey={(n) => String(n.id)}
      searchText={(n) => `${n.recipient_email} ${n.subject} ${n.status} ${n.notification_type}`}
      searchPlaceholder="Search recipient, subject…"
      emptyText="No emails were sent for this alert (no recipients, or email is not configured)."
      initialSort={{ key: "sent", direction: "desc" }}
      onRowClick={onOpen}
    />
  );
}

type AnyThresholdAlert = VMThresholdAlert | PGFlexServerAlert;

function AlertHistoryGrid({
  rows,
  formatDate,
  onOpen,
  title = "Alert history",
}: {
  rows: AnyThresholdAlert[];
  formatDate: (value: string) => string;
  onOpen: (row: AnyThresholdAlert) => void;
  title?: string;
}) {
  const columns: GridColumn<AnyThresholdAlert>[] = [
    { key: "created", header: "Raised", sortValue: (a) => a.created_at, render: (a) => <span className="whitespace-nowrap text-xs">{formatDate(a.created_at)}</span> },
    { key: "metric", header: "Metric", sortValue: (a) => a.metric_type, render: (a) => <span className="text-xs font-semibold uppercase">{a.metric_type}</span> },
    { key: "value", header: "Value", align: "right", sortValue: (a) => a.current_value, render: (a) => <span className="text-xs">{a.current_value.toFixed(1)}%</span> },
    { key: "severity", header: "Severity", sortValue: (a) => a.severity, render: (a) => <SeverityBadge severity={a.severity} /> },
    { key: "status", header: "Status", sortValue: (a) => a.status, render: (a) => <AlertStatusBadge status={a.status} /> },
    { key: "resolved", header: "Resolved", sortValue: (a) => a.resolved_at ?? "", render: (a) => <span className="whitespace-nowrap text-xs">{a.resolved_at ? formatDate(a.resolved_at) : "—"}</span> },
  ];
  return (
    <DetailGrid
      title={title}
      rows={rows}
      columns={columns}
      rowKey={(a) => String(a.id)}
      searchText={(a) => `${a.metric_type} ${a.severity} ${a.status}`}
      searchPlaceholder="Search metric, status…"
      emptyText="No alerts yet."
      initialSort={{ key: "created", direction: "desc" }}
      onRowClick={onOpen}
    />
  );
}

function ExpiryAlertHistoryGrid({ rows, formatDate, onOpen }: { rows: ExpiryAlert[]; formatDate: (value: string) => string; onOpen: (row: ExpiryAlert) => void }) {
  const columns: GridColumn<ExpiryAlert>[] = [
    { key: "created", header: "Raised", sortValue: (a) => a.created_at, render: (a) => <span className="whitespace-nowrap text-xs">{formatDate(a.created_at)}</span> },
    { key: "expiry", header: "For expiry date", sortValue: (a) => a.expiry_date, render: (a) => <span className="text-xs">{formatCalendar(a.expiry_date)}</span> },
    { key: "severity", header: "Severity", sortValue: (a) => a.severity, render: (a) => <SeverityBadge severity={a.severity} /> },
    { key: "status", header: "Status", sortValue: (a) => a.status, render: (a) => <AlertStatusBadge status={a.status} /> },
    { key: "resolved", header: "Resolved", sortValue: (a) => a.resolved_at ?? "", render: (a) => <span className="text-xs">{a.resolved_at ? `${formatDate(a.resolved_at)}${a.resolved_by ? ` · ${a.resolved_by === "system" ? "auto" : a.resolved_by}` : ""}` : "—"}</span> },
  ];
  return (
    <DetailGrid
      title="Alert history"
      rows={rows}
      columns={columns}
      rowKey={(a) => String(a.id)}
      searchText={(a) => `${a.severity} ${a.status} ${a.expiry_date}`}
      emptyText="No alerts yet."
      initialSort={{ key: "created", direction: "desc" }}
      onRowClick={onOpen}
    />
  );
}

/** Every remaining scalar field of an inventory record, so nothing synced is hidden. */
function AllProperties({ data, skip }: { data: Record<string, unknown>; skip: string[] }) {
  const skipped = new Set([...skip, "tags", "resource_type", "_last_sync", "data_disks"]);
  const items = Object.entries(data)
    .filter(([key, value]) => !skipped.has(key) && value !== null && value !== undefined && value !== "" && typeof value !== "object")
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([key, value]) => ({ label: humanize(key), value: typeof value === "boolean" ? (value ? "Yes" : "No") : String(value), mono: /id$|uri|domain|fqdn/i.test(key) }));
  const lists = Object.entries(data).filter(([key, value]) => !skipped.has(key) && Array.isArray(value) && value.length && value.every((v) => typeof v !== "object"));
  if (!items.length && !lists.length) return null;
  return (
    <DetailCard title="All synced properties" subtitle="Everything the last inventory sync recorded for this resource.">
      <PropertyList items={[...items, ...lists.map(([key, value]) => ({ label: humanize(key), value: (value as unknown[]).join(", ") }))]} />
    </DetailCard>
  );
}

// ── Live metrics ──────────────────────────────────────────────────────

function LiveMetricsCard({
  kind,
  subscriptionId,
  resourceGroup,
  name,
  thresholds,
  formatDate,
}: {
  kind: "vm" | "pg";
  subscriptionId: string;
  resourceGroup: string;
  name: string;
  thresholds?: { key: string; label: string; warning: number; critical: number }[];
  formatDate: (value: string) => string;
}) {
  const vm = useVMMetrics(kind === "vm" ? subscriptionId : "", resourceGroup, name);
  const pg = usePGMetrics(kind === "pg" ? subscriptionId : "", resourceGroup, name);
  const query = kind === "vm" ? vm : pg;
  const data = query.data as unknown as Record<string, unknown> | undefined;
  const defaults =
    kind === "vm"
      ? [
          { key: "cpu", label: "CPU", warning: 70, critical: 90 },
          { key: "memory", label: "Memory in use", warning: 75, critical: 90 },
          { key: "disk", label: "Disk I/O (busiest disk)", warning: 80, critical: 95 },
        ]
      : [
          { key: "cpu", label: "CPU", warning: 70, critical: 90 },
          { key: "memory", label: "Memory", warning: 75, critical: 90 },
          { key: "storage", label: "Storage used", warning: 80, critical: 95 },
        ];
  const rows = thresholds ?? defaults;
  return (
    <DetailCard
      title="Live metrics"
      subtitle={
        data?.collected_at
          ? `Azure Monitor · latest reading ${formatDate(String(data.collected_at))} · refreshes every minute`
          : "Azure Monitor platform metrics · refreshes every minute"
      }
    >
      {query.isLoading ? (
        <div className="flex items-center gap-2 text-sm text-slate-500">
          <Spinner /> Reading metrics…
        </div>
      ) : query.isError || data?.error ? (
        <p className="text-sm text-red-700">Could not read metrics: {String(data?.error ?? apiErrorMessage(query.error, "request failed"))}</p>
      ) : (
        <div className="grid gap-5 md:grid-cols-3">
          {rows.map((row) => {
            const value = data?.[row.key] as number | null | undefined;
            return (
              <div key={row.key}>
                <div className="mb-1 flex items-baseline justify-between">
                  <span className="text-xs font-semibold uppercase tracking-wide text-slate-500">{row.label}</span>
                  <span className={`text-lg font-bold ${value == null ? "text-slate-400" : value >= row.critical ? "text-red-600" : value >= row.warning ? "text-amber-600" : "text-slate-900"}`}>
                    {value == null ? "No data" : `${value}%`}
                  </span>
                </div>
                <ThresholdBar value={value} warning={row.warning} critical={row.critical} />
              </div>
            );
          })}
        </div>
      )}
      {kind === "vm" && <p className="mt-3 text-xs text-slate-500">A stopped (deallocated) VM reports no data. Disk I/O is the busiest disk's IOPS/throughput use, not disk space.</p>}
    </DetailCard>
  );
}

// ── Resolve dialog ────────────────────────────────────────────────────

function ResolveDialog({ title, onCancel, onResolve, pending }: { title: string; onCancel: () => void; onResolve: (notes: string) => void; pending: boolean }) {
  const [notes, setNotes] = useState("");
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-900/50 p-4" onClick={onCancel}>
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <h3 className="text-lg font-semibold text-slate-900">{title}</h3>
        <p className="mt-1 text-sm text-slate-500">Recipients are emailed that it was resolved. Add what was done — it stays on the alert's record.</p>
        <textarea
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          rows={4}
          maxLength={2000}
          autoFocus
          placeholder="e.g. Password rotated, CHG0012345"
          className="mt-4 w-full rounded-lg border border-att-200 px-3 py-2 text-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100"
        />
        <div className="mt-4 flex justify-end gap-2">
          <button type="button" onClick={onCancel} className="rounded-lg border border-att-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 hover:bg-att-50">
            Cancel
          </button>
          <button
            type="button"
            disabled={pending}
            onClick={() => onResolve(notes.trim())}
            className="inline-flex items-center gap-2 rounded-lg bg-green-600 px-4 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50"
          >
            {pending && <Spinner className="h-4 w-4 text-white" />}
            Resolve alert
          </button>
        </div>
      </div>
    </div>
  );
}

// ── Alert details ─────────────────────────────────────────────────────

type AlertTab = "overview" | "notifications" | "history";

function useAlertActions(kind: AlertKind, onToast: DetailHostProps["onToast"]) {
  const ackVM = useAcknowledgeVMAlert();
  const ackPG = useAcknowledgePGFlexAlert();
  const ackExpiry = useAcknowledgeExpiryAlert();
  const resolveVM = useResolveVMAlert();
  const resolvePG = useResolvePGFlexAlert();
  const resolveExpiry = useResolveExpiryAlert();
  const ack = kind === "vm" ? ackVM : kind === "pg" ? ackPG : ackExpiry;
  const resolve = kind === "vm" ? resolveVM : kind === "pg" ? resolvePG : resolveExpiry;
  return {
    acknowledging: ack.isPending,
    resolving: resolve.isPending,
    acknowledge: (id: number) =>
      ack.mutate(id, {
        onSuccess: () => onToast("Alert acknowledged — it stays open until it recovers or is resolved"),
        onError: (e) => onToast(apiErrorMessage(e, "Failed to acknowledge the alert"), "error"),
      }),
    resolve: (id: number, notes: string, done: () => void) =>
      resolve.mutate(
        { alertId: id, notes: notes || undefined },
        {
          onSuccess: () => {
            onToast("Alert resolved");
            done();
          },
          onError: (e) => onToast(apiErrorMessage(e, "Failed to resolve the alert"), "error"),
        },
      ),
  };
}

function AlertActions({
  status,
  canWrite,
  onAcknowledge,
  onResolve,
  acknowledging,
  extra,
}: {
  status: string;
  canWrite: boolean;
  onAcknowledge: () => void;
  onResolve: () => void;
  acknowledging: boolean;
  extra?: React.ReactNode;
}) {
  return (
    <>
      {extra}
      {canWrite && status === "active" && (
        <HeaderButton tone="blue" icon={InfraIcons.eye} onClick={onAcknowledge} disabled={acknowledging}>
          Acknowledge
        </HeaderButton>
      )}
      {canWrite && status !== "resolved" && (
        <HeaderButton tone="green" icon={InfraIcons.checkCircle} onClick={onResolve}>
          Resolve
        </HeaderButton>
      )}
    </>
  );
}

function ThresholdAlertDetail({
  kind,
  alert,
  config,
  siblings,
  props,
}: {
  kind: "vm" | "pg";
  alert: AnyThresholdAlert;
  config: VMThresholdConfig | PGFlexServerConfig | undefined;
  siblings: AnyThresholdAlert[];
  props: DetailHostProps;
}) {
  const [tab, setTab] = useState<AlertTab>("overview");
  const [resolving, setResolving] = useState(false);
  const actions = useAlertActions(kind, props.onToast);
  const notifications = useAlertNotifications(kind, alert.id);
  const name = kind === "vm" ? (alert as VMThresholdAlert).vm_name : (alert as PGFlexServerAlert).server_name;
  const metric = alert.metric_type;
  const thresholds = config
    ? {
        warning: (config as unknown as Record<string, number>)[`${metric}_warning_threshold`],
        critical: (config as unknown as Record<string, number>)[`${metric}_critical_threshold`],
      }
    : { warning: alert.severity === "warning" ? alert.threshold_value : alert.threshold_value * 0.8, critical: alert.threshold_value };
  const openFor = alert.resolved_at ?? alert.updated_at ?? alert.created_at;

  return (
    <>
      <ResourceDetailShell
        kind={kind === "vm" ? "VM threshold alert" : "PostgreSQL server alert"}
        name={name}
        icon={kind === "vm" ? InfraIcons.server : InfraIcons.database}
        status={
          <span className="flex items-center gap-1.5">
            <SeverityBadge severity={alert.severity} />
            <AlertStatusBadge status={alert.status} />
          </span>
        }
        meta={
          <>
            <span>
              {metric.toUpperCase()} at <span className="font-semibold text-slate-700">{alert.current_value.toFixed(1)}%</span> (threshold {alert.threshold_value}%)
            </span>
            <span>Raised {formatRelativeTime(alert.created_at)}</span>
            <span className="text-slate-400">Alert #{alert.id}</span>
          </>
        }
        actions={
          <AlertActions
            status={alert.status}
            canWrite={props.canWrite}
            acknowledging={actions.acknowledging}
            onAcknowledge={() => actions.acknowledge(alert.id)}
            onResolve={() => setResolving(true)}
            extra={
              config && (
                <HeaderButton icon={InfraIcons.edit} onClick={() => props.onOpen({ kind: kind === "vm" ? "vm-config" : "pg-config", id: config.id })}>
                  Configuration
                </HeaderButton>
              )
            }
          />
        }
        tabs={[
          { key: "overview", label: "Overview" },
          { key: "notifications", label: "Notifications", count: notifications.data?.length },
          { key: "history", label: `All alerts for this ${kind === "vm" ? "VM" : "server"}`, count: siblings.length },
        ]}
        activeTab={tab}
        onTabChange={setTab}
        onClose={props.onClose}
      >
        {tab === "overview" && (
          <>
            <KpiRow>
              <MetricCard title={`${metric} reading`} value={`${alert.current_value.toFixed(1)}%`} icon={InfraIcons.alert} tone={alert.severity === "critical" ? "red" : "amber"} subtitle={alert.updated_at ? `Checked ${formatRelativeTime(alert.updated_at)}` : undefined} />
              <MetricCard title="Threshold crossed" value={`${alert.threshold_value}%`} icon={InfraIcons.shield} tone="slate" subtitle={`${alert.severity} level`} />
              <MetricCard title="Status" value={<AlertStatusBadge status={alert.status} />} icon={InfraIcons.checkCircle} tone={alert.status === "resolved" ? "green" : alert.status === "acknowledged" ? "blue" : "red"} subtitle={alert.acknowledged_by ? `Ack by ${alert.acknowledged_by}` : undefined} />
              <MetricCard title={alert.status === "resolved" ? "Was open for" : "Open for"} value={formatRelativeTime(alert.created_at).replace(" ago", "")} icon={InfraIcons.clock} tone="att" subtitle={alert.status === "resolved" && alert.resolved_at ? `until ${props.formatDate(openFor)}` : `since ${props.formatDate(alert.created_at)}`} />
            </KpiRow>
            <div className="grid gap-5 lg:grid-cols-2">
              <DetailCard title="Reading vs thresholds" subtitle="Green is normal, amber warning, red critical.">
                <ThresholdBar value={alert.current_value} warning={thresholds.warning} critical={thresholds.critical} />
                <p className="mt-3 text-xs text-slate-500">
                  Open alerts update in place on every check. A worse severity re-opens an acknowledged alert and emails again; dropping below warning resolves it automatically.
                </p>
              </DetailCard>
              <DetailCard title="Activity">
                <Timeline entries={alertTimeline(alert)} formatDate={props.formatDate} />
              </DetailCard>
            </div>
            {config && (
              <UtilizationPanel
                kind={kind}
                subscriptionId={config.subscription_id}
                resourceGroup={config.resource_group}
                name={name}
                formatDate={props.formatDate}
                only={[metric]}
                thresholds={{ [metric]: { warning: thresholds.warning, critical: thresholds.critical } }}
              />
            )}
            {config && (
              <LiveMetricsCard
                kind={kind}
                subscriptionId={config.subscription_id}
                resourceGroup={config.resource_group}
                name={name}
                formatDate={props.formatDate}
                thresholds={
                  kind === "vm"
                    ? [
                        { key: "cpu", label: "CPU", warning: config.cpu_warning_threshold, critical: config.cpu_critical_threshold },
                        { key: "memory", label: "Memory in use", warning: config.memory_warning_threshold, critical: config.memory_critical_threshold },
                        { key: "disk", label: "Disk I/O", warning: (config as VMThresholdConfig).disk_warning_threshold, critical: (config as VMThresholdConfig).disk_critical_threshold },
                      ]
                    : [
                        { key: "cpu", label: "CPU", warning: config.cpu_warning_threshold, critical: config.cpu_critical_threshold },
                        { key: "memory", label: "Memory", warning: config.memory_warning_threshold, critical: config.memory_critical_threshold },
                        { key: "storage", label: "Storage used", warning: (config as PGFlexServerConfig).storage_warning_threshold, critical: (config as PGFlexServerConfig).storage_critical_threshold },
                      ]
                }
              />
            )}
            <DetailCard title={kind === "vm" ? "Virtual machine" : "Server"}>
              <PropertyList
                items={[
                  { label: "Name", value: name },
                  config && { label: "Resource group", value: config.resource_group },
                  config && { label: "Subscription", value: subName(props.subscriptionNames, config.subscription_id) },
                  config && { label: "Monitoring", value: <ConfigStateBadge enabled={config.is_enabled} snoozeUntil={config.snooze_until} /> },
                  { label: "Resource ID", value: <Mono value={kind === "vm" ? (alert as VMThresholdAlert).vm_id : (alert as PGFlexServerAlert).server_id} />, wide: true },
                  config && { label: "Recipients", value: <Recipients emails={config.notification_emails} />, wide: true },
                  !config && { label: "Configuration", value: "This alert's configuration was deleted.", wide: true },
                ]}
              />
            </DetailCard>
          </>
        )}
        {tab === "notifications" && <NotificationsGrid rows={notifications.data ?? []} isLoading={notifications.isLoading} formatDate={props.formatDate} onOpen={(n) => props.onOpen({ kind: "notification", id: n.id, snapshot: n })} />}
        {tab === "history" && (
          <AlertHistoryGrid rows={siblings} formatDate={props.formatDate} onOpen={(a) => props.onOpen({ kind: kind === "vm" ? "vm-alert" : "pg-alert", id: a.id })} />
        )}
      </ResourceDetailShell>
      {resolving && (
        <ResolveDialog
          title={`Resolve ${metric.toUpperCase()} alert on ${name}?`}
          pending={actions.resolving}
          onCancel={() => setResolving(false)}
          onResolve={(notes) => actions.resolve(alert.id, notes, () => setResolving(false))}
        />
      )}
    </>
  );
}

function ExpiryAlertDetail({ alert, config, siblings, props }: { alert: ExpiryAlert; config: ExpiryConfig | undefined; siblings: ExpiryAlert[]; props: DetailHostProps }) {
  const [tab, setTab] = useState<AlertTab>("overview");
  const [resolving, setResolving] = useState(false);
  const actions = useAlertActions("expiry", props.onToast);
  const notifications = useAlertNotifications("expiry", alert.id);
  const warningDays = config?.warning_days_before ?? 30;
  const criticalDays = config?.critical_days_before ?? 7;
  const days = alert.days_until_expiry;
  const health = expiryHealth(days, warningDays, criticalDays);
  const renewedSince = config && config.expiry_date.slice(0, 10) !== alert.expiry_date.slice(0, 10);

  return (
    <>
      <ResourceDetailShell
        kind={`${getAlertTypeLabel(alert.alert_type)} alert`}
        name={alert.resource_name}
        icon={InfraIcons.clock}
        status={
          <span className="flex items-center gap-1.5">
            <SeverityBadge severity={alert.severity} />
            <AlertStatusBadge status={alert.status} />
          </span>
        }
        meta={
          <>
            <span className={daysLeftTone(days, warningDays, criticalDays)}>{daysLeftText(days)}</span>
            <span>Expiry {formatCalendar(alert.expiry_date)}</span>
            {config?.environment && <span>{getEnvLabel(config.environment)}</span>}
            <span className="text-slate-400">Alert #{alert.id}</span>
          </>
        }
        actions={
          <AlertActions
            status={alert.status}
            canWrite={props.canWrite}
            acknowledging={actions.acknowledging}
            onAcknowledge={() => actions.acknowledge(alert.id)}
            onResolve={() => setResolving(true)}
            extra={
              config && (
                <>
                  {props.canWrite && alert.status !== "resolved" && (
                    <HeaderButton tone="amber" icon={InfraIcons.calendar} onClick={() => props.onEditConfig({ kind: "expiry", config })}>
                      Renewed? Update date
                    </HeaderButton>
                  )}
                  <HeaderButton icon={InfraIcons.edit} onClick={() => props.onOpen({ kind: "expiry-config", id: config.id })}>
                    Configuration
                  </HeaderButton>
                </>
              )
            }
          />
        }
        tabs={[
          { key: "overview", label: "Overview" },
          { key: "notifications", label: "Notifications", count: notifications.data?.length },
          { key: "history", label: "All alerts for this item", count: siblings.length },
        ]}
        activeTab={tab}
        onTabChange={setTab}
        onClose={props.onClose}
      >
        {tab === "overview" && (
          <>
            <KpiRow>
              <MetricCard title="Days left" value={days < 0 ? `${days}` : days} icon={InfraIcons.clock} tone={health === "ok" ? "green" : health === "warning" ? "amber" : "red"} subtitle={daysLeftText(days)} />
              <MetricCard title="Expiry date" value={formatCalendar(alert.expiry_date)} icon={InfraIcons.calendar} tone="att" subtitle={renewedSince ? `Config now says ${formatCalendar(config?.expiry_date)}` : undefined} />
              <MetricCard title="Severity" value={<SeverityBadge severity={alert.severity} />} icon={InfraIcons.alert} tone={alert.severity === "critical" ? "red" : "amber"} subtitle={`warn ${warningDays}d · critical ${criticalDays}d before`} />
              <MetricCard title="Status" value={<AlertStatusBadge status={alert.status} />} icon={InfraIcons.checkCircle} tone={alert.status === "resolved" ? "green" : alert.status === "acknowledged" ? "blue" : "red"} subtitle={`Raised ${formatRelativeTime(alert.created_at)}`} />
            </KpiRow>
            {health === "expired" && alert.status !== "resolved" && (
              <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
                <p className="font-semibold">This {EXPIRY_TYPE_META[alert.alert_type]?.short ?? "item"} expired {Math.abs(days)} day{Math.abs(days) === 1 ? "" : "s"} ago.</p>
                <p className="mt-0.5">If it has been renewed, update the expiry date on the configuration — the alert then resolves automatically.</p>
              </div>
            )}
            <div className="grid gap-5 lg:grid-cols-2">
              <DetailCard title="Expiry window">
                <div className="mb-2 flex justify-end">
                  <ExpiryHealthBadge health={health} />
                </div>
                <ExpiryWindowBar expiryDate={alert.expiry_date} warningDays={warningDays} criticalDays={criticalDays} />
              </DetailCard>
              <DetailCard title="Activity">
                <Timeline entries={alertTimeline(alert)} formatDate={props.formatDate} />
              </DetailCard>
            </div>
            <DetailCard title="Tracked item">
              {config ? (
                <PropertyList
                  items={[
                    { label: "Type", value: getAlertTypeLabel(config.alert_type) },
                    { label: "Environment", value: getEnvLabel(config.environment) },
                    { label: "Name", value: config.resource_name },
                    { label: "Identifier", value: <Mono value={config.resource_identifier} /> },
                    { label: "Tracking", value: <ConfigStateBadge enabled={config.is_enabled} snoozeUntil={config.snooze_until} /> },
                    { label: "Configured by", value: config.created_by },
                    config.description && { label: "Description", value: config.description, wide: true },
                    { label: "Recipients", value: <Recipients emails={config.notification_emails} />, wide: true },
                  ]}
                />
              ) : (
                <EmptyNote>The configuration for this alert was deleted.</EmptyNote>
              )}
            </DetailCard>
          </>
        )}
        {tab === "notifications" && <NotificationsGrid rows={notifications.data ?? []} isLoading={notifications.isLoading} formatDate={props.formatDate} onOpen={(n) => props.onOpen({ kind: "notification", id: n.id, snapshot: n })} />}
        {tab === "history" && <ExpiryAlertHistoryGrid rows={siblings} formatDate={props.formatDate} onOpen={(a) => props.onOpen({ kind: "expiry-alert", id: a.id })} />}
      </ResourceDetailShell>
      {resolving && (
        <ResolveDialog
          title={`Resolve the alert for ${alert.resource_name}?`}
          pending={actions.resolving}
          onCancel={() => setResolving(false)}
          onResolve={(notes) => actions.resolve(alert.id, notes, () => setResolving(false))}
        />
      )}
    </>
  );
}

// ── Configuration details ─────────────────────────────────────────────

type ConfigTab = "overview" | "alerts";

function ConfigStateActions({
  enabled,
  snoozeUntil,
  canWrite,
  onToggle,
  onSnooze,
  onEdit,
  onDelete,
  busy,
}: {
  enabled: boolean;
  snoozeUntil?: string | null;
  canWrite: boolean;
  onToggle: () => void;
  onSnooze?: (until: string | null) => void;
  onEdit: () => void;
  onDelete: () => void;
  busy: boolean;
}) {
  if (!canWrite) return null;
  const snoozed = isSnoozed(snoozeUntil);
  return (
    <>
      <HeaderButton icon={InfraIcons.edit} onClick={onEdit}>
        Edit
      </HeaderButton>
      {onSnooze && enabled && (
        <HeaderButton
          tone="amber"
          icon={InfraIcons.bellOff}
          disabled={busy}
          onClick={() => onSnooze(snoozed ? null : new Date(Date.now() + 24 * 3_600_000).toISOString())}
        >
          {snoozed ? "Unsnooze" : "Snooze 24h"}
        </HeaderButton>
      )}
      <HeaderButton tone={enabled ? "neutral" : "green"} icon={InfraIcons.power} disabled={busy} onClick={onToggle}>
        {enabled ? "Disable" : "Enable"}
      </HeaderButton>
      <HeaderButton tone="red" icon={InfraIcons.trash} onClick={onDelete}>
        Delete
      </HeaderButton>
    </>
  );
}

function useConfigUpdater(kind: "vm" | "pg" | "storage" | "expiry", onToast: DetailHostProps["onToast"]) {
  const vm = useUpdateVMThresholdConfig();
  const pg = useUpdatePGFlexConfig();
  const storage = useUpdateStorageAlertConfig();
  const expiry = useUpdateExpiryConfig();
  const mutation = { vm, pg, storage, expiry }[kind];
  return {
    busy: mutation.isPending,
    update: (configId: number, data: Record<string, unknown>, message: string) =>
      (mutation.mutate as (v: { configId: number; data: Record<string, unknown> }, o: object) => void)(
        { configId, data },
        { onSuccess: () => onToast(message), onError: (e: unknown) => onToast(apiErrorMessage(e, "Failed to update the configuration"), "error") },
      ),
  };
}

function ThresholdConfigDetail({
  kind,
  config,
  alerts,
  props,
}: {
  kind: "vm" | "pg" | "storage";
  config: VMThresholdConfig | PGFlexServerConfig | StorageAlertConfig;
  alerts: AnyThresholdAlert[];
  props: DetailHostProps;
}) {
  const [tab, setTab] = useState<ConfigTab>("overview");
  const updater = useConfigUpdater(kind, props.onToast);
  const name = kind === "vm" ? (config as VMThresholdConfig).vm_name : kind === "pg" ? (config as PGFlexServerConfig).server_name : (config as StorageAlertConfig).account_name;
  const resourceId = kind === "vm" ? (config as VMThresholdConfig).vm_id : kind === "pg" ? (config as PGFlexServerConfig).server_id : (config as StorageAlertConfig).account_id;
  const open = alerts.filter((a) => a.status !== "resolved");
  const rows =
    kind === "vm"
      ? [
          ["CPU", (config as VMThresholdConfig).cpu_warning_threshold, (config as VMThresholdConfig).cpu_critical_threshold, "%"],
          ["Memory in use", (config as VMThresholdConfig).memory_warning_threshold, (config as VMThresholdConfig).memory_critical_threshold, "%"],
          ["Disk I/O", (config as VMThresholdConfig).disk_warning_threshold, (config as VMThresholdConfig).disk_critical_threshold, "%"],
        ]
      : kind === "pg"
        ? [
            ["CPU", (config as PGFlexServerConfig).cpu_warning_threshold, (config as PGFlexServerConfig).cpu_critical_threshold, "%"],
            ["Memory", (config as PGFlexServerConfig).memory_warning_threshold, (config as PGFlexServerConfig).memory_critical_threshold, "%"],
            ["Storage", (config as PGFlexServerConfig).storage_warning_threshold, (config as PGFlexServerConfig).storage_critical_threshold, "%"],
          ]
        : [
            ["Used capacity", (config as StorageAlertConfig).capacity_warning_gb, (config as StorageAlertConfig).capacity_critical_gb, " GB"],
            ["Transactions", (config as StorageAlertConfig).transactions_warning, (config as StorageAlertConfig).transactions_critical, ""],
            ["Egress", (config as StorageAlertConfig).egress_warning_gb, (config as StorageAlertConfig).egress_critical_gb, " GB"],
          ];
  const resourceKind = kind === "vm" ? "vm" : kind === "pg" ? "pg-server" : "storage-account";
  const editTarget = { kind, config } as ConfigEditorTarget;

  return (
    <ResourceDetailShell
      kind={kind === "vm" ? "VM threshold configuration" : kind === "pg" ? "PG server configuration" : "Storage alert configuration"}
      name={name}
      icon={kind === "vm" ? InfraIcons.server : kind === "pg" ? InfraIcons.database : InfraIcons.storage}
      status={<ConfigStateBadge enabled={config.is_enabled} snoozeUntil={config.snooze_until} />}
      meta={
        <>
          <span>{config.resource_group}</span>
          <span>{props.subscriptionNames.get(config.subscription_id) || config.subscription_id}</span>
          {isSnoozed(config.snooze_until) && <span>Snoozed until {props.formatDate(config.snooze_until as string)}</span>}
        </>
      }
      actions={
        <>
          <HeaderButton icon={kind === "vm" ? InfraIcons.server : InfraIcons.database} onClick={() => props.onOpen({ kind: resourceKind, id: resourceId } as InfraDetailTarget)}>
            Resource
          </HeaderButton>
          <ConfigStateActions
            enabled={config.is_enabled}
            snoozeUntil={config.snooze_until}
            canWrite={props.canWrite}
            busy={updater.busy}
            onEdit={() => props.onEditConfig(editTarget)}
            onToggle={() => updater.update(config.id, { is_enabled: !config.is_enabled }, config.is_enabled ? `Monitoring for ${name} disabled` : `Monitoring for ${name} enabled`)}
            onSnooze={kind === "storage" ? undefined : (until) => updater.update(config.id, { snooze_until: until }, until ? `${name} snoozed for 24 hours` : `${name} unsnoozed`)}
            onDelete={() => props.onDeleteConfig(kind, config.id, name)}
          />
        </>
      }
      tabs={[
        { key: "overview", label: "Overview" },
        ...(kind === "storage" ? [] : [{ key: "alerts" as ConfigTab, label: "Alerts", count: alerts.length, attention: open.length > 0 }]),
      ]}
      activeTab={tab}
      onTabChange={setTab}
      onClose={props.onClose}
    >
      {tab === "overview" && (
        <>
          {kind === "storage" && (
            <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
              Storage thresholds are saved but not evaluated by the alert schedules yet, so they raise no alerts.
            </div>
          )}
          <KpiRow>
            <MetricCard title="Monitoring" value={<ConfigStateBadge enabled={config.is_enabled} snoozeUntil={config.snooze_until} />} icon={InfraIcons.power} tone={config.is_enabled ? "green" : "slate"} />
            <MetricCard title="Open alerts" value={open.length} icon={InfraIcons.alert} tone={open.length ? "red" : "green"} onClick={kind === "storage" ? undefined : () => setTab("alerts")} actionLabel="Show alerts" />
            <MetricCard title="Alerts raised" value={alerts.length} icon={InfraIcons.clock} tone="att" subtitle="most recent 100 per type" />
            <MetricCard title="Recipients" value={config.notification_emails?.length ?? 0} icon={InfraIcons.mail} tone="blue" />
          </KpiRow>
          <DetailCard title="Thresholds" subtitle="An alert opens at warning and escalates at critical.">
            <div className="grid gap-5 md:grid-cols-3">
              {rows.map(([label, warning, critical, unit]) => (
                <div key={label as string}>
                  <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">{label}</p>
                  <ThresholdBar warning={warning as number} critical={critical as number} unit={unit as string} max={unit === "%" ? 100 : (critical as number) * 1.25} />
                </div>
              ))}
            </div>
          </DetailCard>
          {kind !== "storage" && (
            <LiveMetricsCard
              kind={kind}
              subscriptionId={config.subscription_id}
              resourceGroup={config.resource_group}
              name={name}
              formatDate={props.formatDate}
              thresholds={rows.map(([label, warning, critical], index) => ({
                key: (kind === "vm" ? ["cpu", "memory", "disk"] : ["cpu", "memory", "storage"])[index],
                label: label as string,
                warning: warning as number,
                critical: critical as number,
              }))}
            />
          )}
          <DetailCard title="Details">
            <PropertyList
              items={[
                { label: "Resource", value: name },
                { label: "Resource group", value: config.resource_group },
                { label: "Subscription", value: subName(props.subscriptionNames, config.subscription_id) },
                { label: "Created", value: `${props.formatDate(config.created_at)} by ${config.created_by}` },
                config.updated_at && { label: "Last changed", value: props.formatDate(config.updated_at) },
                { label: "Resource ID", value: <Mono value={resourceId} />, wide: true },
                { label: "Recipients", value: <Recipients emails={config.notification_emails} />, wide: true },
              ]}
            />
          </DetailCard>
        </>
      )}
      {tab === "alerts" && (
        <AlertHistoryGrid title={`Alerts for ${name}`} rows={alerts} formatDate={props.formatDate} onOpen={(a) => props.onOpen({ kind: kind === "vm" ? "vm-alert" : "pg-alert", id: a.id })} />
      )}
    </ResourceDetailShell>
  );
}

function ExpiryConfigDetail({ config, alerts, props }: { config: ExpiryConfig; alerts: ExpiryAlert[]; props: DetailHostProps }) {
  const [tab, setTab] = useState<ConfigTab>("overview");
  const updater = useConfigUpdater("expiry", props.onToast);
  const days = config.days_until_expiry ?? null;
  const health = expiryHealth(days, config.warning_days_before, config.critical_days_before);
  const open = alerts.filter((a) => a.status !== "resolved");
  const meta = EXPIRY_TYPE_META[config.alert_type];

  return (
    <ResourceDetailShell
      kind={`${getAlertTypeLabel(config.alert_type)} tracking`}
      name={config.resource_name}
      icon={InfraIcons.clock}
      status={
        <span className="flex items-center gap-1.5">
          <ExpiryHealthBadge health={health} />
          <ConfigStateBadge enabled={config.is_enabled} snoozeUntil={config.snooze_until} />
        </span>
      }
      meta={
        <>
          <span className={daysLeftTone(days, config.warning_days_before, config.critical_days_before)}>{daysLeftText(days)}</span>
          <span>{getEnvLabel(config.environment)}</span>
          <span className="font-mono text-xs">{config.resource_identifier}</span>
        </>
      }
      actions={
        <ConfigStateActions
          enabled={config.is_enabled}
          snoozeUntil={config.snooze_until}
          canWrite={props.canWrite}
          busy={updater.busy}
          onEdit={() => props.onEditConfig({ kind: "expiry", config })}
          onToggle={() => updater.update(config.id, { is_enabled: !config.is_enabled }, config.is_enabled ? `Tracking for ${config.resource_name} disabled` : `Tracking for ${config.resource_name} enabled`)}
          onSnooze={(until) => updater.update(config.id, { snooze_until: until }, until ? `${config.resource_name} snoozed for 24 hours` : `${config.resource_name} unsnoozed`)}
          onDelete={() => props.onDeleteConfig("expiry", config.id, config.resource_name)}
        />
      }
      tabs={[
        { key: "overview", label: "Overview" },
        { key: "alerts", label: "Alerts", count: alerts.length, attention: open.length > 0 },
      ]}
      activeTab={tab}
      onTabChange={setTab}
      onClose={props.onClose}
    >
      {tab === "overview" && (
        <>
          <KpiRow>
            <MetricCard title="Days left" value={days ?? "—"} icon={InfraIcons.clock} tone={health === "ok" ? "green" : health === "warning" ? "amber" : "red"} subtitle={daysLeftText(days)} />
            <MetricCard title="Expiry date" value={formatCalendar(config.expiry_date)} icon={InfraIcons.calendar} tone="att" />
            <MetricCard title="Open alerts" value={open.length} icon={InfraIcons.alert} tone={open.length ? "red" : "green"} onClick={() => setTab("alerts")} actionLabel="Show alerts" />
            <MetricCard title="Recipients" value={config.notification_emails?.length ?? 0} icon={InfraIcons.mail} tone="blue" />
          </KpiRow>
          <DetailCard title="Expiry window" subtitle={`Warning ${config.warning_days_before} days and critical ${config.critical_days_before} days before the expiry date.`}>
            <ExpiryWindowBar expiryDate={config.expiry_date} warningDays={config.warning_days_before} criticalDays={config.critical_days_before} />
          </DetailCard>
          <DetailCard title="Details">
            <PropertyList
              items={[
                { label: "Type", value: `${getAlertTypeLabel(config.alert_type)} — ${meta?.description ?? ""}` },
                { label: "Environment", value: getEnvLabel(config.environment) },
                { label: meta?.nameLabel ?? "Name", value: config.resource_name },
                { label: meta?.identifierLabel ?? "Identifier", value: <Mono value={config.resource_identifier} /> },
                { label: "Created", value: `${props.formatDate(config.created_at)} by ${config.created_by}` },
                config.updated_at && { label: "Last changed", value: props.formatDate(config.updated_at) },
                isSnoozed(config.snooze_until) && { label: "Snoozed until", value: props.formatDate(config.snooze_until as string) },
                config.description && { label: "Description", value: config.description, wide: true },
                { label: "Recipients", value: <Recipients emails={config.notification_emails} />, wide: true },
              ]}
            />
          </DetailCard>
          {config.metadata && Object.keys(config.metadata).length > 0 && (
            <KeyValueGrid title="Additional metadata" entries={Object.fromEntries(Object.entries(config.metadata).map(([k, v]) => [k, String(v)]))} />
          )}
        </>
      )}
      {tab === "alerts" && <ExpiryAlertHistoryGrid rows={alerts} formatDate={props.formatDate} onOpen={(a) => props.onOpen({ kind: "expiry-alert", id: a.id })} />}
    </ResourceDetailShell>
  );
}

// ── Resource details ──────────────────────────────────────────────────

type ResourceTab = "overview" | "alerts" | "tags";

function PowerButtons({ kind, state, resource, props }: { kind: PowerKind; state: string | null | undefined; resource: PowerTarget; props: DetailHostProps }) {
  const allowed = kind === "vm" ? props.canPowerVM : props.canPowerPG;
  if (!allowed) return null;
  const pending = props.powerPendingKey === `${kind}:${resource.subscription_id}:${resource.name}`;
  const running = kind === "vm" ? state === "running" : state === "Ready";
  const stopped = kind === "vm" ? state === "deallocated" || state === "stopped" : state === "Stopped";
  return (
    <>
      {pending && <Spinner className="h-5 w-5" />}
      {stopped && (
        <HeaderButton tone="green" icon={InfraIcons.play} disabled={pending} onClick={() => props.onPower(kind, "start", resource)}>
          Start
        </HeaderButton>
      )}
      {running && (
        <>
          <HeaderButton tone="amber" icon={InfraIcons.restart} disabled={pending} onClick={() => props.onPower(kind, "restart", resource)}>
            Restart
          </HeaderButton>
          <HeaderButton tone="red" icon={InfraIcons.stop} disabled={pending} onClick={() => props.onPower(kind, "stop", resource)}>
            {kind === "vm" ? "Stop (deallocate)" : "Stop"}
          </HeaderButton>
        </>
      )}
    </>
  );
}

function AlertConfigSummary({
  configured,
  onOpen,
  onCreate,
  canWrite,
  children,
}: {
  configured: boolean;
  onOpen?: () => void;
  onCreate: () => void;
  canWrite: boolean;
  children?: React.ReactNode;
}) {
  return (
    <DetailCard
      title="Alerting"
      actions={
        configured ? (
          onOpen && (
            <HeaderButton icon={InfraIcons.eye} onClick={onOpen}>
              View configuration
            </HeaderButton>
          )
        ) : (
          canWrite && (
            <HeaderButton tone="blue" icon={InfraIcons.plus} onClick={onCreate}>
              Configure alerts
            </HeaderButton>
          )
        )
      }
    >
      {configured ? children : <p className="text-sm text-slate-500">No alert thresholds are configured for this resource.</p>}
    </DetailCard>
  );
}

type VMTab = "overview" | "utilization" | "disks" | "run" | "admin" | "alerts" | "tags";

function VMResourceDetail({
  vm,
  config,
  alerts,
  disks,
  props,
}: {
  vm: VMInfo & Record<string, unknown>;
  config?: VMThresholdConfig;
  alerts: VMThresholdAlert[];
  disks: (ManagedDisk & Record<string, unknown>)[];
  props: DetailHostProps;
}) {
  const [tab, setTab] = useState<VMTab>("overview");
  const open = alerts.filter((a) => a.status !== "resolved");
  const tags = vm.tags ?? {};
  const target = { name: vm.name, resource_group: vm.resource_group || "", subscription_id: vm.subscription_id };
  const powerPending = props.powerPendingKey === `vm:${vm.subscription_id}:${vm.name}`;
  const attachedDisks = disks.filter((d) => String(d.managed_by || "").toLowerCase() === vm.id.toLowerCase());
  const diskCount = Math.max(attachedDisks.length, (vm.data_disks?.length ?? 0) + (vm.os_disk_name ? 1 : 0));
  const diskTotal = attachedDisks.reduce((sum, d) => sum + (d.size_gb || 0), 0) ||
    (vm.os_disk_size_gb || 0) + (vm.data_disks ?? []).reduce((sum, d) => sum + (d.size_gb || 0), 0);
  const thresholds = config
    ? {
        cpu: { warning: config.cpu_warning_threshold, critical: config.cpu_critical_threshold },
        memory: { warning: config.memory_warning_threshold, critical: config.memory_critical_threshold },
        disk: { warning: config.disk_warning_threshold, critical: config.disk_critical_threshold },
      }
    : undefined;
  const tier = props.subscriptionTiers.get((vm.subscription_id || "").toLowerCase());
  return (
    <ResourceDetailShell
      kind="Virtual machine"
      name={vm.name}
      icon={InfraIcons.server}
      status={
        <span className="flex items-center gap-1.5">
          <PowerStateBadge state={vm.power_state} />
          {tier && <span className={`rounded px-2 py-0.5 text-xs font-semibold ${tier === "prod" ? "bg-red-100 text-red-700" : "bg-blue-100 text-blue-700"}`}>{tier === "prod" ? "Prod" : "Non-Prod"}</span>}
        </span>
      }
      meta={
        <>
          <span>{vm.resource_group}</span>
          <span>{props.subscriptionNames.get(vm.subscription_id || "") || vm.subscription_id}</span>
          <span>{vm.location}</span>
          {vm._last_sync && <span className="text-slate-400">Synced {formatRelativeTime(vm._last_sync)}</span>}
        </>
      }
      actions={<PowerButtons kind="vm" state={vm.power_state} resource={target} props={props} />}
      tabs={[
        { key: "overview", label: "Overview" },
        { key: "utilization", label: "Utilization" },
        { key: "disks", label: "Disks", count: diskCount },
        ...(props.canRunCommand ? [{ key: "run" as VMTab, label: "Run command" }] : []),
        { key: "admin", label: "Administration" },
        { key: "alerts", label: "Alerts", count: alerts.length, attention: open.length > 0 },
        { key: "tags", label: "Tags", count: Object.keys(tags).length },
      ]}
      activeTab={tab}
      onTabChange={setTab}
      onClose={props.onClose}
    >
      {tab === "overview" && (
        <>
          <KpiRow>
            <MetricCard title="Power state" value={<PowerStateBadge state={vm.power_state} />} icon={InfraIcons.power} tone={vm.power_state === "running" ? "green" : "slate"} onClick={() => setTab("admin")} actionLabel="Administration" />
            <MetricCard title="Size" value={vm.vm_size || "—"} icon={InfraIcons.server} tone="att" valueClassName="text-lg" onClick={() => setTab("admin")} actionLabel="Resize" />
            <MetricCard title="Disks" value={diskCount} icon={InfraIcons.disk} tone="indigo" subtitle={diskTotal ? `${diskTotal.toLocaleString()} GB total` : undefined} onClick={() => setTab("disks")} actionLabel="Show disks" />
            <MetricCard title="Open alerts" value={open.length} icon={InfraIcons.alert} tone={open.length ? "red" : "green"} onClick={() => setTab("alerts")} actionLabel="Show alerts" />
          </KpiRow>
          {vm.power_state === "running" && vm.subscription_id && (
            <LiveMetricsCard
              kind="vm"
              subscriptionId={vm.subscription_id}
              resourceGroup={vm.resource_group || ""}
              name={vm.name}
              formatDate={props.formatDate}
              thresholds={
                config && [
                  { key: "cpu", label: "CPU", warning: config.cpu_warning_threshold, critical: config.cpu_critical_threshold },
                  { key: "memory", label: "Memory in use", warning: config.memory_warning_threshold, critical: config.memory_critical_threshold },
                  { key: "disk", label: "Disk I/O", warning: config.disk_warning_threshold, critical: config.disk_critical_threshold },
                ]
              }
            />
          )}
          <AlertConfigSummary
            configured={!!config}
            canWrite={props.canWrite}
            onOpen={config && (() => props.onOpen({ kind: "vm-config", id: config.id }))}
            onCreate={() => props.onEditConfig({ kind: "vm", config: null, preset: { resourceId: vm.id } })}
          >
            {config && (
              <div className="flex flex-wrap items-center gap-4 text-sm text-slate-700">
                <ConfigStateBadge enabled={config.is_enabled} snoozeUntil={config.snooze_until} />
                <span>CPU {config.cpu_warning_threshold}/{config.cpu_critical_threshold}%</span>
                <span>Memory {config.memory_warning_threshold}/{config.memory_critical_threshold}%</span>
                <span>Disk I/O {config.disk_warning_threshold}/{config.disk_critical_threshold}%</span>
                <span>{config.notification_emails.length} recipient(s)</span>
              </div>
            )}
          </AlertConfigSummary>
          <DetailCard title="Configuration">
            <PropertyList
              items={[
                { label: "Name", value: vm.name },
                { label: "Resource group", value: vm.resource_group },
                { label: "Subscription", value: subName(props.subscriptionNames, vm.subscription_id) },
                { label: "Location", value: vm.location },
                { label: "Size", value: vm.vm_size },
                { label: "OS", value: (vm.os_type || "").replace("OperatingSystemTypes.", "") || null },
                { label: "Provisioning state", value: vm.provisioning_state },
                {
                  label: "Disks",
                  value: (
                    <button type="button" onClick={() => setTab("disks")} className="font-medium text-att-700 hover:underline">
                      {diskCount} disk{diskCount === 1 ? "" : "s"}{diskTotal ? ` · ${diskTotal.toLocaleString()} GB` : ""} — view all
                    </button>
                  ),
                },
                { label: "Resource ID", value: <Mono value={vm.id} />, wide: true },
                vm._last_sync && { label: "Last synced", value: props.formatDate(vm._last_sync) },
              ]}
            />
          </DetailCard>
        </>
      )}
      {tab === "utilization" &&
        (vm.subscription_id ? (
          <UtilizationPanel kind="vm" subscriptionId={vm.subscription_id} resourceGroup={vm.resource_group || ""} name={vm.name} thresholds={thresholds} formatDate={props.formatDate} />
        ) : (
          <EmptyNote>Subscription unknown — sync resources first.</EmptyNote>
        ))}
      {tab === "disks" && <VMDisksGrid vm={vm} disks={disks} onOpenDisk={(disk) => props.onOpen({ kind: "disk", id: disk.id })} />}
      {tab === "run" && props.canRunCommand && <RunCommandPanel vm={vm} tier={tier} formatDate={props.formatDate} />}
      {tab === "admin" && (
        <VMAdminPanel
          vm={vm}
          canAdmin={props.canAdminResources}
          canPower={props.canPowerVM}
          powerPending={powerPending}
          onPower={(action) => props.onPower("vm", action, target)}
          onConfirm={props.onConfirm}
          onToast={props.onToast}
        />
      )}
      {tab === "alerts" && <AlertHistoryGrid rows={alerts} formatDate={props.formatDate} onOpen={(a) => props.onOpen({ kind: "vm-alert", id: a.id })} title={`Alerts for ${vm.name}`} />}
      {tab === "tags" && <TagEditor key={vm.id} resourceId={vm.id} resourceType="virtual_machine" tags={tags} canEdit={props.canAdminResources} onToast={props.onToast} />}
    </ResourceDetailShell>
  );
}

type PGTab = "overview" | "utilization" | "databases" | "admin" | "alerts" | "tags";

function PGResourceDetail({ server, config, alerts, props }: { server: PGFlexServer; config?: PGFlexServerConfig; alerts: PGFlexServerAlert[]; props: DetailHostProps }) {
  const [tab, setTab] = useState<PGTab>("overview");
  const pgTarget = { name: server.name, resource_group: server.resource_group, subscription_id: server.subscription_id };
  const open = alerts.filter((a) => a.status !== "resolved");
  const tags = server.tags ?? {};
  return (
    <ResourceDetailShell
      kind="PostgreSQL Flexible Server"
      name={server.name}
      icon={InfraIcons.database}
      status={<PowerStateBadge state={server.state} />}
      meta={
        <>
          <span>{server.resource_group}</span>
          <span>{props.subscriptionNames.get(server.subscription_id) || server.subscription_id}</span>
          <span>{server.location}</span>
          {server._last_sync && <span className="text-slate-400">Synced {formatRelativeTime(server._last_sync)}</span>}
        </>
      }
      actions={<PowerButtons kind="pg" state={server.state} resource={pgTarget} props={props} />}
      tabs={[
        { key: "overview", label: "Overview" },
        { key: "utilization", label: "Utilization" },
        { key: "databases", label: "Databases & firewall" },
        { key: "admin", label: "Administration" },
        { key: "alerts", label: "Alerts", count: alerts.length, attention: open.length > 0 },
        { key: "tags", label: "Tags", count: Object.keys(tags).length },
      ]}
      activeTab={tab}
      onTabChange={setTab}
      onClose={props.onClose}
    >
      {tab === "overview" && (
        <>
          <KpiRow>
            <MetricCard title="State" value={<PowerStateBadge state={server.state} />} icon={InfraIcons.power} tone={server.state === "Ready" ? "green" : "slate"} />
            <MetricCard title="Version" value={server.version ? `PostgreSQL ${server.version}` : "—"} icon={InfraIcons.database} tone="att" valueClassName="text-lg" />
            <MetricCard title="SKU" value={server.sku_name || "—"} icon={InfraIcons.server} tone="indigo" valueClassName="text-lg" subtitle={server.sku_tier || undefined} />
            <MetricCard title="Open alerts" value={open.length} icon={InfraIcons.alert} tone={open.length ? "red" : "green"} onClick={() => setTab("alerts")} actionLabel="Show alerts" />
          </KpiRow>
          {server.state === "Ready" && (
            <LiveMetricsCard
              kind="pg"
              subscriptionId={server.subscription_id}
              resourceGroup={server.resource_group}
              name={server.name}
              formatDate={props.formatDate}
              thresholds={
                config && [
                  { key: "cpu", label: "CPU", warning: config.cpu_warning_threshold, critical: config.cpu_critical_threshold },
                  { key: "memory", label: "Memory", warning: config.memory_warning_threshold, critical: config.memory_critical_threshold },
                  { key: "storage", label: "Storage used", warning: config.storage_warning_threshold, critical: config.storage_critical_threshold },
                ]
              }
            />
          )}
          <AlertConfigSummary
            configured={!!config}
            canWrite={props.canWrite}
            onOpen={config && (() => props.onOpen({ kind: "pg-config", id: config.id }))}
            onCreate={() => props.onEditConfig({ kind: "pg", config: null, preset: { resourceId: server.id } })}
          >
            {config && (
              <div className="flex flex-wrap items-center gap-4 text-sm text-slate-700">
                <ConfigStateBadge enabled={config.is_enabled} snoozeUntil={config.snooze_until} />
                <span>CPU {config.cpu_warning_threshold}/{config.cpu_critical_threshold}%</span>
                <span>Memory {config.memory_warning_threshold}/{config.memory_critical_threshold}%</span>
                <span>Storage {config.storage_warning_threshold}/{config.storage_critical_threshold}%</span>
              </div>
            )}
          </AlertConfigSummary>
          <DetailCard title="Configuration">
            <PropertyList
              items={[
                { label: "Host name", value: <Mono value={server.fully_qualified_domain_name} />, wide: true },
                { label: "Resource group", value: server.resource_group },
                { label: "Subscription", value: subName(props.subscriptionNames, server.subscription_id) },
                { label: "Storage", value: server.storage_size_gb ? `${server.storage_size_gb} GB` : null },
                { label: "Backup retention", value: server.backup_retention_days ? `${server.backup_retention_days} days` : null },
                { label: "Geo-redundant backup", value: server.geo_redundant_backup },
                { label: "High availability", value: [server.high_availability_mode, server.high_availability_state].filter(Boolean).join(" · ") || null },
                { label: "Admin login", value: server.admin_login },
                { label: "Resource ID", value: <Mono value={server.id} />, wide: true },
              ]}
            />
          </DetailCard>
        </>
      )}
      {tab === "utilization" && (
        <UtilizationPanel
          kind="pg"
          subscriptionId={server.subscription_id}
          resourceGroup={server.resource_group}
          name={server.name}
          formatDate={props.formatDate}
          thresholds={
            config && {
              cpu: { warning: config.cpu_warning_threshold, critical: config.cpu_critical_threshold },
              memory: { warning: config.memory_warning_threshold, critical: config.memory_critical_threshold },
              storage: { warning: config.storage_warning_threshold, critical: config.storage_critical_threshold },
            }
          }
        />
      )}
      {tab === "databases" && <PGDatabasesPanel server={server} formatDate={props.formatDate} />}
      {tab === "admin" && (
        <PGAdminPanel
          server={server}
          canPower={props.canPowerPG}
          powerPending={props.powerPendingKey === `pg:${server.subscription_id}:${server.name}`}
          onPower={(action) => props.onPower("pg", action, pgTarget)}
        />
      )}
      {tab === "alerts" && <AlertHistoryGrid rows={alerts} formatDate={props.formatDate} onOpen={(a) => props.onOpen({ kind: "pg-alert", id: a.id })} title={`Alerts for ${server.name}`} />}
      {tab === "tags" && <TagEditor key={server.id} resourceId={server.id} resourceType="pg_flex_server" tags={tags} canEdit={props.canAdminResources} onToast={props.onToast} />}
    </ResourceDetailShell>
  );
}

function GenericResourceDetail({
  kind,
  resource,
  props,
  storageConfig,
  attachedVm,
}: {
  kind: "storage-account" | "disk";
  resource: (StorageAccount | ManagedDisk) & Record<string, unknown>;
  props: DetailHostProps;
  storageConfig?: StorageAlertConfig;
  attachedVm?: VMInfo;
}) {
  const [tab, setTab] = useState<"overview" | "admin" | "tags">("overview");
  const tags = (resource.tags as Record<string, string> | undefined) ?? {};
  const disk = resource as ManagedDisk & Record<string, unknown>;
  const account = resource as StorageAccount & Record<string, unknown>;
  return (
    <ResourceDetailShell
      kind={kind === "disk" ? "Managed disk" : "Storage account"}
      name={resource.name}
      icon={kind === "disk" ? InfraIcons.disk : InfraIcons.storage}
      status={
        kind === "disk" ? (
          <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${disk.disk_state === "Attached" ? "bg-green-50 text-green-700" : disk.disk_state === "Unattached" ? "bg-amber-50 text-amber-800" : "bg-slate-100 text-slate-700"}`}>
            {disk.disk_state || "Unknown"}
          </span>
        ) : (
          <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700">{account.provisioning_state || "Unknown"}</span>
        )
      }
      meta={
        <>
          <span>{resource.resource_group}</span>
          <span>{props.subscriptionNames.get(resource.subscription_id) || resource.subscription_id}</span>
          <span>{resource.location}</span>
        </>
      }
      tabs={[
        { key: "overview", label: "Overview" },
        { key: "admin", label: "Administration" },
        { key: "tags", label: "Tags", count: Object.keys(tags).length },
      ]}
      activeTab={tab}
      onTabChange={setTab}
      onClose={props.onClose}
    >
      {tab === "admin" &&
        (kind === "disk" ? (
          <DiskAdminPanel
            disk={disk}
            canAdmin={props.canAdminResources}
            canDelete={props.canDeleteDisks}
            onDelete={() => props.onDeleteDisk(disk)}
            onConfirm={props.onConfirm}
            onToast={props.onToast}
          />
        ) : (
          <PortalLinkCard resourceId={resource.id} label="the storage account" />
        ))}
      {tab === "overview" && (
        <>
          {kind === "disk" ? (
            <KpiRow>
              <MetricCard title="Size" value={disk.size_gb ? `${disk.size_gb} GB` : "—"} icon={InfraIcons.disk} tone="att" />
              <MetricCard title="SKU" value={disk.sku || "—"} icon={InfraIcons.shield} tone="indigo" valueClassName="text-lg" />
              <MetricCard title="IOPS / MBps" value={`${disk.disk_iops_read_write ?? "—"} / ${disk.disk_mbps_read_write ?? "—"}`} icon={InfraIcons.server} tone="blue" valueClassName="text-lg" />
              <MetricCard title="State" value={disk.disk_state || "—"} icon={InfraIcons.power} tone={disk.disk_state === "Unattached" ? "amber" : "green"} valueClassName="text-lg" subtitle={disk.disk_state === "Unattached" ? "Billed while unattached" : undefined} />
            </KpiRow>
          ) : (
            <KpiRow>
              <MetricCard title="Kind" value={account.kind || "—"} icon={InfraIcons.storage} tone="att" valueClassName="text-lg" />
              <MetricCard title="SKU" value={account.sku || "—"} icon={InfraIcons.shield} tone="indigo" valueClassName="text-lg" />
              <MetricCard title="Access tier" value={account.access_tier || "—"} icon={InfraIcons.clock} tone="blue" valueClassName="text-lg" />
              <MetricCard
                title="Public blob access"
                value={account.allow_blob_public_access === true ? "Allowed" : account.allow_blob_public_access === false ? "Blocked" : "—"}
                icon={InfraIcons.globe}
                tone={account.allow_blob_public_access === true ? "amber" : "green"}
                valueClassName="text-lg"
                subtitle={account.minimum_tls_version ? `Min TLS ${String(account.minimum_tls_version).replace("TLS", "").replace("_", ".")}` : undefined}
              />
            </KpiRow>
          )}
          {kind === "disk" && (
            <DetailCard title="Attachment">
              {disk.managed_by ? (
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <Mono value={String(disk.managed_by)} />
                  {attachedVm && (
                    <HeaderButton icon={InfraIcons.server} onClick={() => props.onOpen({ kind: "vm", id: attachedVm.id })}>
                      Open {attachedVm.name}
                    </HeaderButton>
                  )}
                </div>
              ) : (
                <p className="text-sm text-slate-600">Not attached to any VM. Unattached disks are still billed — delete it from the Administration tab if it is no longer needed.</p>
              )}
            </DetailCard>
          )}
          {kind === "storage-account" && (
            <AlertConfigSummary
              configured={!!storageConfig}
              canWrite={props.canWrite}
              onOpen={storageConfig && (() => props.onOpen({ kind: "storage-config", id: storageConfig.id }))}
              onCreate={() => props.onEditConfig({ kind: "storage", config: null, preset: { resourceId: resource.id } })}
            >
              {storageConfig && (
                <p className="text-sm text-slate-700">
                  Capacity {storageConfig.capacity_warning_gb}/{storageConfig.capacity_critical_gb} GB · thresholds saved (storage checks are not evaluated yet).
                </p>
              )}
            </AlertConfigSummary>
          )}
          <DetailCard title="Identity">
            <PropertyList
              items={[
                { label: "Resource group", value: resource.resource_group },
                { label: "Subscription", value: subName(props.subscriptionNames, resource.subscription_id) },
                { label: "Location", value: resource.location },
                { label: "Resource ID", value: <Mono value={resource.id} />, wide: true },
              ]}
            />
          </DetailCard>
          <AllProperties data={resource} skip={["id", "name", "resource_group", "subscription_id", "location", "managed_by"]} />
        </>
      )}
      {tab === "tags" && (
        <TagEditor
          key={resource.id}
          resourceId={resource.id}
          resourceType={kind === "disk" ? "managed_disk" : "storage_account"}
          tags={tags}
          canEdit={props.canAdminResources}
          onToast={props.onToast}
        />
      )}
    </ResourceDetailShell>
  );
}

// ── Schedule and notification details ─────────────────────────────────

function ScheduleDetail({ schedule, props }: { schedule: AlertScheduleConfig; props: DetailHostProps }) {
  const update = useUpdateAlertScheduleConfig();
  const checks = [
    ["VM thresholds", schedule.check_vm_thresholds, true],
    ["PG server thresholds", schedule.check_pg_thresholds, true],
    ["Expiry dates", schedule.check_expiry_alerts, true],
    ["Storage thresholds", schedule.check_storage_thresholds, false],
    ["Disk thresholds", schedule.check_disk_thresholds, false],
  ] as const;
  const toggle = () =>
    update.mutate(
      { configId: schedule.id, data: { is_enabled: !schedule.is_enabled } },
      {
        onSuccess: () => props.onToast(schedule.is_enabled ? `Schedule "${schedule.name}" paused` : `Schedule "${schedule.name}" enabled`),
        onError: (e) => props.onToast(apiErrorMessage(e, "Failed to update the schedule"), "error"),
      },
    );
  return (
    <ResourceDetailShell
      kind="Alert schedule"
      name={schedule.name}
      icon={InfraIcons.schedule}
      status={<ConfigStateBadge enabled={schedule.is_enabled} />}
      meta={
        <>
          <span>{describeSchedule(schedule.schedule_type, schedule.interval_minutes, schedule.cron_expression)}</span>
          {schedule.description && <span>{schedule.description}</span>}
        </>
      }
      actions={
        props.canWrite && (
          <>
            <HeaderButton icon={InfraIcons.edit} onClick={() => props.onEditSchedule(schedule)}>
              Edit
            </HeaderButton>
            <HeaderButton tone={schedule.is_enabled ? "neutral" : "green"} icon={InfraIcons.power} disabled={update.isPending} onClick={toggle}>
              {schedule.is_enabled ? "Pause" : "Enable"}
            </HeaderButton>
            <HeaderButton tone="red" icon={InfraIcons.trash} onClick={() => props.onDeleteSchedule(schedule)}>
              Delete
            </HeaderButton>
          </>
        )
      }
      tabs={[{ key: "overview", label: "Overview" }]}
      activeTab="overview"
      onTabChange={() => undefined}
      onClose={props.onClose}
    >
      <KpiRow>
        <MetricCard title="Status" value={<ConfigStateBadge enabled={schedule.is_enabled} />} icon={InfraIcons.power} tone={schedule.is_enabled ? "green" : "slate"} />
        <MetricCard title="Runs" value={describeSchedule(schedule.schedule_type, schedule.interval_minutes, schedule.cron_expression)} icon={InfraIcons.clock} tone="att" valueClassName="text-lg" />
        <MetricCard title="Last run" value={schedule.last_run_at ? formatRelativeTime(schedule.last_run_at) : "Never"} icon={InfraIcons.checkCircle} tone="blue" valueClassName="text-lg" subtitle={schedule.last_run_at ? props.formatDate(schedule.last_run_at) : undefined} />
        <MetricCard title="Next run" value={schedule.next_run_at ? props.formatDate(schedule.next_run_at) : schedule.is_enabled ? "Scheduling…" : "Paused"} icon={InfraIcons.calendar} tone="indigo" valueClassName="text-base" />
      </KpiRow>
      <div className="grid gap-5 lg:grid-cols-2">
        <DetailCard title="Checks run on each firing">
          <ul className="space-y-2">
            {checks.map(([label, on, supported]) => (
              <li key={label} className="flex items-center justify-between text-sm">
                <span className={on ? "text-slate-800" : "text-slate-400"}>{label}</span>
                {!supported && on ? (
                  <span className="rounded-full bg-amber-50 px-2 py-0.5 text-xs font-semibold text-amber-800">On, but not evaluated yet</span>
                ) : (
                  <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${on ? "bg-green-50 text-green-700" : "bg-slate-100 text-slate-500"}`}>{on ? "On" : "Off"}</span>
                )}
              </li>
            ))}
          </ul>
        </DetailCard>
        <DetailCard title="Daily digest">
          {schedule.send_daily_digest ? (
            <div className="space-y-3 text-sm text-slate-700">
              <p>
                {schedule.schedule_type === "cron"
                  ? "Sent when this schedule fires — at most once per UTC day."
                  : `Sent once a day, on the first run at or after ${schedule.digest_time_utc} UTC.`}{" "}
                Lists every open (active or acknowledged) alert.
              </p>
              <Recipients emails={schedule.digest_recipients} />
              {!schedule.digest_recipients?.length && <p className="text-xs text-slate-500">With no recipients, the digest goes to every alert configuration's recipients.</p>}
            </div>
          ) : (
            <p className="text-sm text-slate-500">This schedule does not send the digest.</p>
          )}
        </DetailCard>
      </div>
      <DetailCard title="Details">
        <PropertyList
          items={[
            { label: "Type", value: schedule.schedule_type === "cron" ? `Cron (${schedule.cron_expression})` : `Interval (${schedule.interval_minutes} min)` },
            { label: "Created", value: `${props.formatDate(schedule.created_at)} by ${schedule.created_by}` },
            schedule.updated_at && { label: "Last changed", value: props.formatDate(schedule.updated_at) },
            schedule.description && { label: "Description", value: schedule.description, wide: true },
          ]}
        />
      </DetailCard>
    </ResourceDetailShell>
  );
}

const KIND_BY_NOTIFICATION_TYPE: Record<string, AlertKind> = {
  vm_threshold: "vm",
  pg_flex_server: "pg",
  custom_expiry: "expiry",
  mech_id: "expiry",
  certificate: "expiry",
  aaf_account: "expiry",
  database_account: "expiry",
  itservices_domain: "expiry",
};

function NotificationDetail({ notification, props }: { notification: NotificationHistory; props: DetailHostProps }) {
  const alertKind = KIND_BY_NOTIFICATION_TYPE[notification.notification_type];
  const canOpenAlert = alertKind && notification.alert_id;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4" onClick={props.onClose}>
      <div className="w-full max-w-2xl overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-att-100" onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
        <header className="relative border-b border-att-100 bg-gradient-to-r from-att-50 via-white to-white px-6 pb-4 pt-5">
          <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-att-300 via-att-500 to-att-300" />
          <div className="flex items-start gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-att-100 text-att-700">{InfraIcons.mail}</div>
            <div className="min-w-0 flex-1">
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-att-600">{getNotificationTypeLabel(notification.notification_type)}</p>
              <h2 className="mt-0.5 text-base font-semibold text-slate-900">{notification.subject}</h2>
            </div>
            <button type="button" onClick={props.onClose} aria-label="Close" className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600">
              <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round">
                <line x1="18" y1="6" x2="6" y2="18" />
                <line x1="6" y1="6" x2="18" y2="18" />
              </svg>
            </button>
          </div>
        </header>
        <div className="space-y-4 px-6 py-5">
          <PropertyList
            items={[
              { label: "Recipient", value: notification.recipient_email },
              {
                label: "Delivery",
                value: (
                  <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${notification.status === "sent" ? "bg-green-50 text-green-700" : notification.status === "failed" ? "bg-red-50 text-red-700" : "bg-amber-50 text-amber-800"}`}>
                    {notification.status}
                  </span>
                ),
              },
              { label: "Sent", value: notification.sent_at ? `${props.formatDate(notification.sent_at)} (${formatRelativeTime(notification.sent_at)})` : "Pending" },
              { label: "Alert", value: notification.alert_id ? `#${notification.alert_id}` : "—" },
            ]}
          />
          {notification.error_message && (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800">
              <p className="font-semibold">Delivery error</p>
              <p className="mt-1 break-words font-mono text-xs">{notification.error_message}</p>
            </div>
          )}
        </div>
        {canOpenAlert && (
          <footer className="flex justify-end border-t border-att-100 bg-att-50/40 px-6 py-3">
            <HeaderButton
              tone="blue"
              icon={InfraIcons.alert}
              onClick={() => props.onOpen({ kind: `${alertKind}-alert` as "vm-alert", id: notification.alert_id as number })}
            >
              Open the alert
            </HeaderButton>
          </footer>
        )}
      </div>
    </div>
  );
}

function NotFound({ what, onClose }: { what: string; onClose: () => void }) {
  return (
    <ResourceDetailShell kind={what} name="Not found" icon={InfraIcons.alert} tabs={[{ key: "x", label: "Overview" }]} activeTab="x" onTabChange={() => undefined} onClose={onClose} error={`This ${what.toLowerCase()} no longer exists, or it is outside your subscription scope.`} />
  );
}

// ── Host ──────────────────────────────────────────────────────────────

export function InfraAlertDetailHost(props: DetailHostProps) {
  const { target } = props;
  const vmAlerts = useVMThresholdAlerts();
  const pgAlerts = usePGFlexAlerts();
  const expiryAlerts = useExpiryAlerts();
  const vmConfigs = useVMThresholdConfigs();
  const pgConfigs = usePGFlexConfigs();
  const storageConfigs = useStorageAlertConfigs();
  const expiryConfigs = useExpiryConfigs();
  const vms = useAzureVMs();
  const pgServers = useAzurePGServers();
  const storageAccounts = useAzureStorageAccounts();
  const disks = useAzureDisks();
  const schedules = useAlertScheduleConfigs();
  const notifications = useNotificationHistory();

  const lower = (v: string | null | undefined) => (v || "").toLowerCase();
  const loading = useMemo(
    () =>
      ({
        "vm-alert": vmAlerts.isLoading || vmConfigs.isLoading,
        "pg-alert": pgAlerts.isLoading || pgConfigs.isLoading,
        "expiry-alert": expiryAlerts.isLoading || expiryConfigs.isLoading,
        "vm-config": vmConfigs.isLoading,
        "pg-config": pgConfigs.isLoading,
        "storage-config": storageConfigs.isLoading,
        "expiry-config": expiryConfigs.isLoading,
        vm: vms.isLoading,
        "pg-server": pgServers.isLoading,
        "storage-account": storageAccounts.isLoading,
        disk: disks.isLoading,
        schedule: schedules.isLoading,
        notification: notifications.isLoading,
      })[target.kind],
    [target.kind, vmAlerts.isLoading, vmConfigs.isLoading, pgAlerts.isLoading, pgConfigs.isLoading, expiryAlerts.isLoading, expiryConfigs.isLoading, storageConfigs.isLoading, vms.isLoading, pgServers.isLoading, storageAccounts.isLoading, disks.isLoading, schedules.isLoading, notifications.isLoading],
  );

  if (loading) {
    return <ResourceDetailShell kind="Details" name="Loading…" icon={InfraIcons.alert} tabs={[{ key: "x", label: "Overview" }]} activeTab="x" onTabChange={() => undefined} isLoading onClose={props.onClose} />;
  }

  switch (target.kind) {
    case "vm-alert": {
      const alert = vmAlerts.data?.find((a) => a.id === target.id) ?? target.snapshot;
      if (!alert) return <NotFound what="VM alert" onClose={props.onClose} />;
      const config = vmConfigs.data?.find((c) => c.id === alert.config_id);
      const siblings = (vmAlerts.data ?? []).filter((a) => a.config_id === alert.config_id);
      return <ThresholdAlertDetail key={alert.id} kind="vm" alert={alert} config={config} siblings={siblings} props={props} />;
    }
    case "pg-alert": {
      const alert = pgAlerts.data?.find((a) => a.id === target.id) ?? target.snapshot;
      if (!alert) return <NotFound what="PG alert" onClose={props.onClose} />;
      const config = pgConfigs.data?.find((c) => c.id === alert.config_id);
      const siblings = (pgAlerts.data ?? []).filter((a) => a.config_id === alert.config_id);
      return <ThresholdAlertDetail key={alert.id} kind="pg" alert={alert} config={config} siblings={siblings} props={props} />;
    }
    case "expiry-alert": {
      const alert = expiryAlerts.data?.find((a) => a.id === target.id) ?? target.snapshot;
      if (!alert) return <NotFound what="Expiry alert" onClose={props.onClose} />;
      const config = expiryConfigs.data?.find((c) => c.id === alert.config_id);
      const siblings = (expiryAlerts.data ?? []).filter((a) => a.config_id === alert.config_id);
      return <ExpiryAlertDetail key={alert.id} alert={alert} config={config} siblings={siblings} props={props} />;
    }
    case "vm-config": {
      const config = vmConfigs.data?.find((c) => c.id === target.id);
      if (!config) return <NotFound what="VM configuration" onClose={props.onClose} />;
      return <ThresholdConfigDetail key={config.id} kind="vm" config={config} alerts={(vmAlerts.data ?? []).filter((a) => a.config_id === config.id)} props={props} />;
    }
    case "pg-config": {
      const config = pgConfigs.data?.find((c) => c.id === target.id);
      if (!config) return <NotFound what="PG configuration" onClose={props.onClose} />;
      return <ThresholdConfigDetail key={config.id} kind="pg" config={config} alerts={(pgAlerts.data ?? []).filter((a) => a.config_id === config.id)} props={props} />;
    }
    case "storage-config": {
      const config = storageConfigs.data?.find((c) => c.id === target.id);
      if (!config) return <NotFound what="Storage configuration" onClose={props.onClose} />;
      return <ThresholdConfigDetail key={config.id} kind="storage" config={config} alerts={[]} props={props} />;
    }
    case "expiry-config": {
      const config = expiryConfigs.data?.find((c) => c.id === target.id);
      if (!config) return <NotFound what="Expiry configuration" onClose={props.onClose} />;
      return <ExpiryConfigDetail key={config.id} config={config} alerts={(expiryAlerts.data ?? []).filter((a) => a.config_id === config.id)} props={props} />;
    }
    case "vm": {
      const vm = vms.data?.resources.find((v) => lower(v.id) === lower(target.id));
      if (!vm) return <NotFound what="Virtual machine" onClose={props.onClose} />;
      const config = vmConfigs.data?.find((c) => lower(c.vm_id) === lower(vm.id));
      const alerts = config ? (vmAlerts.data ?? []).filter((a) => a.config_id === config.id) : [];
      return (
        <VMResourceDetail
          key={vm.id}
          vm={vm as VMInfo & Record<string, unknown>}
          config={config}
          alerts={alerts}
          disks={(disks.data?.resources ?? []) as (ManagedDisk & Record<string, unknown>)[]}
          props={props}
        />
      );
    }
    case "pg-server": {
      const server = pgServers.data?.resources.find((s) => lower(s.id) === lower(target.id));
      if (!server) return <NotFound what="PG server" onClose={props.onClose} />;
      const config = pgConfigs.data?.find((c) => lower(c.server_id) === lower(server.id));
      const alerts = config ? (pgAlerts.data ?? []).filter((a) => a.config_id === config.id) : [];
      return <PGResourceDetail key={server.id} server={server} config={config} alerts={alerts} props={props} />;
    }
    case "storage-account": {
      const account = storageAccounts.data?.resources.find((s) => lower(s.id) === lower(target.id));
      if (!account) return <NotFound what="Storage account" onClose={props.onClose} />;
      const config = storageConfigs.data?.find((c) => lower(c.account_id) === lower(account.id));
      return <GenericResourceDetail key={account.id} kind="storage-account" resource={account as StorageAccount & Record<string, unknown>} storageConfig={config} props={props} />;
    }
    case "disk": {
      const disk = disks.data?.resources.find((d) => lower(d.id) === lower(target.id));
      if (!disk) return <NotFound what="Managed disk" onClose={props.onClose} />;
      const attachedVm = vms.data?.resources.find((v) => lower(v.id) === lower(disk.managed_by));
      return <GenericResourceDetail key={disk.id} kind="disk" resource={disk as ManagedDisk & Record<string, unknown>} attachedVm={attachedVm} props={props} />;
    }
    case "schedule": {
      const schedule = schedules.data?.find((s) => s.id === target.id);
      if (!schedule) return <NotFound what="Schedule" onClose={props.onClose} />;
      return <ScheduleDetail key={schedule.id} schedule={schedule} props={props} />;
    }
    case "notification": {
      const notification = notifications.data?.find((n) => n.id === target.id) ?? target.snapshot;
      if (!notification) return <NotFound what="Notification" onClose={props.onClose} />;
      return <NotificationDetail notification={notification} props={props} />;
    }
  }
}
