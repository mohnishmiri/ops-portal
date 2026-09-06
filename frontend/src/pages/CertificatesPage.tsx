/**
 * Certificate Management Page — Keyfactor Command certificate lifecycle.
 *
 * Features (matching the InfraAlert page patterns):
 * - Vector icon action buttons (consistent with other pages)
 * - Sortable grid headers
 * - Collection dropdown with search
 * - Consistent pagination (Showing X–Y of Z, page numbers, prev/next)
 * - Status badges, role-gated actions
 */

import React, { useMemo, useState, useCallback, useEffect, useRef } from "react";
import { useAuth } from "../contexts/AuthContext";
import { usePermissions } from "../contexts/PermissionsContext";
import Toast, { type ToastState, type ToastType } from "../components/Toast";
import { gridStyles, SortableHeader, nextSortState, type SortState } from "../components/gridStyles";
import { exportToCsv, type CsvColumn } from "../utils/csvExport";
import { formatDate, formatDateTime } from "../utils/dateFormat";
import {
  Certificate,
  CertificateListParams,
  CertificateAuditEntry,
  AutoRenewalConfig,
  AutoRenewalCertificateRef,
  AlertConfig,
  useCertificates,
  useCollectionCertStats,
  useCollections,
  useCertificateAuditHistory,
  useAutoRenewalConfigs,
  useCreateAutoRenewalConfig,
  useDeleteAutoRenewalConfig,
  useRunAutoRenewalConfig,
  useAlertConfigs,
  useCreateAlertConfig,
  useDeleteAlertConfig,
  STATUS_LABEL,
  certificateErrorMessage,
  fetchAllCertificatesForExport,
  useCertificateSync,
  useCertificateSyncStatus,
} from "../services/certificatesApi";
import { StatusBadge } from "../features/certificates/StatusBadge";
import { EnrollCertificateModal } from "../features/certificates/EnrollCertificateModal";
import { RenewCertificateModal } from "../features/certificates/RenewCertificateModal";
import { RevokeCertificateModal } from "../features/certificates/RevokeCertificateModal";
import { DeleteCertificateModal } from "../features/certificates/DeleteCertificateModal";
import { UpdateMetadataModal } from "../features/certificates/UpdateMetadataModal";
import { CertificateDetailsModal } from "../features/certificates/CertificateDetailsModal";
import { DownloadCertificateModal } from "../features/certificates/DownloadCertificateModal";
import { LoadToAkvModal } from "../features/certificates/LoadToAkvModal";
import { CertificateMultiSelect } from "../features/certificates/CertificateMultiSelect";

const PAGE_SIZE = 25;

// ── Vector Icons ──────────────────────────────────────────────────────

const svgProps = { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2, strokeLinecap: "round" as const, strokeLinejoin: "round" as const };

const Icons = {
  cert: <svg {...svgProps} width={20} height={20}><circle cx="12" cy="8" r="6" /><path d="M15.477 12.89 17 22l-5-3-5 3 1.523-9.11" /></svg>,
  warn: <svg {...svgProps} width={20} height={20}><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>,
  collection: <svg {...svgProps} width={20} height={20}><polygon points="12 2 2 7 12 12 22 7 12 2" /><polyline points="2 17 12 22 22 17" /><polyline points="2 12 12 17 22 12" /></svg>,
  // Action icons
  eye: <svg {...svgProps}><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></svg>,
  download: <svg {...svgProps}><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>,
  refresh: <svg {...svgProps}><polyline points="23 4 23 10 17 10" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" /></svg>,
  play: <svg {...svgProps}><polygon points="5 3 19 12 5 21 5 3" /></svg>,
  edit: <svg {...svgProps}><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></svg>,
  slash: <svg {...svgProps}><circle cx="12" cy="12" r="10" /><line x1="4.93" y1="4.93" x2="19.07" y2="19.07" /></svg>,
  trash: <svg {...svgProps}><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></svg>,
  more: <svg {...svgProps}><circle cx="12" cy="5" r="1" /><circle cx="12" cy="12" r="1" /><circle cx="12" cy="19" r="1" /></svg>,
  keyvault: <svg {...svgProps}><rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></svg>,
};

const actionTones = {
  blue: "text-att-700 hover:bg-att-50",
  green: "text-green-700 hover:bg-green-50",
  red: "text-red-700 hover:bg-red-50",
  orange: "text-orange-700 hover:bg-orange-50",
};

const ActionBtn: React.FC<{ title: string; tone: keyof typeof actionTones; onClick: () => void; disabled?: boolean; children: React.ReactNode }> = ({ title, tone, onClick, disabled, children }) => (
  <button type="button" onClick={onClick} disabled={disabled} title={title} className={`rounded-lg p-2 transition disabled:cursor-not-allowed disabled:opacity-40 ${actionTones[tone]}`}>{children}</button>
);

// ── Expiry date badge with color-coded urgency ─────────────────────────

const expiryColor = (not_after: string | null): { text: string; dot: string; label: string } => {
  if (!not_after) return { text: "text-gray-500", dot: "bg-gray-400", label: "" };
  const days = Math.ceil((new Date(not_after).getTime() - Date.now()) / 86_400_000);
  if (days < 0) return { text: "text-red-700 font-semibold", dot: "bg-red-500", label: "Expired" };
  if (days <= 30) return { text: "text-red-600 font-semibold", dot: "bg-red-500", label: `${days}d` };
  if (days <= 60) return { text: "text-amber-600 font-semibold", dot: "bg-amber-500", label: `${days}d` };
  if (days <= 90) return { text: "text-yellow-600", dot: "bg-yellow-400", label: `${days}d` };
  return { text: "text-green-700", dot: "bg-green-500", label: `${days}d` };
};

const ExpiryBadge: React.FC<{ not_after: string | null }> = ({ not_after }) => {
  const { text, dot, label } = expiryColor(not_after);
  return (
    <span className={`inline-flex items-center gap-1.5 ${text}`}>
      <span className={`h-2 w-2 rounded-full ${dot} shrink-0`} />
      <span>{formatDate(not_after)}</span>
      {label && <span className="rounded-full bg-current/10 px-1.5 py-0.5 text-[11px] font-semibold opacity-80">{label}</span>}
    </span>
  );
};

// ── CSV export button (shared across all tab grids) ───────────────────

const ExportIcon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z" /><polyline points="14 2 14 8 20 8" /><line x1="12" y1="18" x2="12" y2="12" /><polyline points="9 15 12 18 15 15" /></svg>
);

const SpinnerIcon = (
  <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="10" stroke="currentColor" strokeWidth={3} opacity={0.25} /><path d="M12 2a10 10 0 0 1 10 10" stroke="currentColor" strokeWidth={3} strokeLinecap="round" /></svg>
);

const ExportCsvButton: React.FC<{ onClick: () => void; disabled?: boolean; busy?: boolean }> = ({ onClick, disabled, busy }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled || busy}
    title="Export the full grid to a CSV file"
    className="inline-flex items-center gap-2 rounded-lg border border-att-200 bg-white px-3 py-2 text-sm font-medium text-att-700 shadow-sm transition hover:border-att-300 hover:bg-att-50 disabled:cursor-not-allowed disabled:opacity-50"
  >
    {busy ? SpinnerIcon : ExportIcon}
    {busy ? "Exporting…" : "Export CSV"}
  </button>
);

// ── Sync control (DB cache refresh) ─────────────────────────────

const RefreshIcon = (
  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><polyline points="23 4 23 10 17 10" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" /></svg>
);

const ChevronDownIcon = (
  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9" /></svg>
);

const SYNC_RUN_DOT: Record<string, string> = {
  completed: "bg-green-500",
  partial: "bg-amber-500",
  running: "bg-att-500 animate-pulse",
  failed: "bg-red-500",
};

const timeAgo = (iso: string | null): string => {
  if (!iso) return "never";
  const minutes = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.floor(hours / 24)}d ago`;
};

const SyncControl: React.FC<{ collectionId?: number; collectionName?: string; onToast: (message: string, type?: ToastType) => void }> = ({ collectionId, collectionName, onToast }) => {
  const { data: status } = useCertificateSyncStatus();
  const sync = useCertificateSync();
  const [open, setOpen] = useState(false);
  const popoverRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    return () => document.removeEventListener("mousedown", onDown);
  }, [open]);

  const latest = status?.recent_syncs?.[0];
  const running = sync.isPending || latest?.status === "running";
  const lastCompleted = status?.last_completed_at ?? status?.recent_syncs?.find((s) => s.completed_at)?.completed_at ?? null;
  const cachedCerts = status?.certificates_in_db ?? 0;
  const cachedCols = status?.collections_in_db ?? 0;
  const isStale = !running && Boolean(status?.is_stale) && cachedCerts > 0;

  const state = running
    ? { label: "Syncing…", pill: "bg-att-50 text-att-700 ring-att-200", dot: "bg-att-500 animate-pulse" }
    : latest?.status === "failed"
      ? { label: "Sync failed", pill: "bg-red-50 text-red-700 ring-red-200", dot: "bg-red-500" }
      : latest?.status === "partial"
        ? { label: "Partial sync", pill: "bg-amber-50 text-amber-700 ring-amber-200", dot: "bg-amber-500" }
        : isStale
          ? { label: "Data stale", pill: "bg-amber-50 text-amber-700 ring-amber-200", dot: "bg-amber-500" }
          : cachedCerts > 0
            ? { label: "Up to date", pill: "bg-green-50 text-green-700 ring-green-200", dot: "bg-green-500" }
            : { label: "Not synced", pill: "bg-gray-50 text-gray-600 ring-gray-200", dot: "bg-gray-400" };

  const handleSync = (scope: "all" | "collection") => {
    const target = scope === "collection" ? collectionId : undefined;
    sync.mutate(target, {
      onSuccess: (r) =>
        onToast(
          `Synced ${r.certificates_synced.toLocaleString()} certificate(s)${r.collections_synced ? ` across ${r.collections_synced.toLocaleString()} collection(s)` : ""} from Keyfactor.`,
          "success"
        ),
      onError: (e) => onToast(certificateErrorMessage(e, "Sync failed."), "error"),
    });
  };

  return (
    <div className="relative" ref={popoverRef}>
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        title="View certificate data sync status and refresh from Keyfactor"
        className="inline-flex items-center gap-2 rounded-lg border border-att-200 bg-white px-3 py-2 text-sm text-att-700 shadow-sm transition hover:border-att-300 hover:bg-att-50"
      >
        <span className={`h-2 w-2 rounded-full ${state.dot}`} />
        <span className="font-semibold">{state.label}</span>
        <span className="hidden text-xs font-normal text-gray-400 md:inline">
          {cachedCerts > 0 ? `${cachedCerts.toLocaleString()} cached · ` : ""}Updated {timeAgo(lastCompleted)}
        </span>
        <span className={`text-gray-400 transition-transform ${open ? "rotate-180" : ""}`}>{ChevronDownIcon}</span>
      </button>

      {open && (
        <div className="absolute right-0 z-30 mt-2 w-80 rounded-xl border border-att-100 bg-white p-4 shadow-xl">
          <div className="mb-3 flex items-center justify-between">
            <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold ring-1 ${state.pill}`}>
              <span className={`h-1.5 w-1.5 rounded-full ${state.dot}`} />
              {state.label}
            </span>
            <span className="text-[11px] text-gray-400" title={lastCompleted ? new Date(lastCompleted).toLocaleString() : undefined}>
              Updated {timeAgo(lastCompleted)}
            </span>
          </div>

          <dl className="mb-3 grid grid-cols-2 gap-2">
            <div className="rounded-lg border border-att-50 bg-att-50/40 px-3 py-2">
              <dt className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">Certificates cached</dt>
              <dd className="mt-0.5 text-sm font-bold text-gray-800">{cachedCerts.toLocaleString()}</dd>
            </div>
            <div className="rounded-lg border border-att-50 bg-att-50/40 px-3 py-2">
              <dt className="text-[10px] font-semibold uppercase tracking-wide text-gray-400">Collections</dt>
              <dd className="mt-0.5 text-sm font-bold text-gray-800">{cachedCols.toLocaleString()}</dd>
            </div>
          </dl>

          {status?.recent_syncs && status.recent_syncs.length > 0 && (
            <div className="mb-3">
              <p className="mb-1.5 text-[10px] font-semibold uppercase tracking-wide text-gray-400">Recent activity</p>
              <ul className="max-h-40 space-y-1.5 overflow-y-auto pr-1">
                {status.recent_syncs.slice(0, 5).map((r) => (
                  <li key={r.id} className="flex items-start gap-2 text-xs">
                    <span className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${SYNC_RUN_DOT[r.status] ?? "bg-gray-400"}`} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-medium text-gray-700">{r.sync_type === "full" ? "Full sync" : "Collection sync"}</span>
                        <span className="shrink-0 text-gray-400">{timeAgo(r.completed_at ?? r.started_at)}</span>
                      </div>
                      <p className="text-gray-500">
                        {r.status === "running"
                          ? "In progress…"
                          : `${r.certificates_synced.toLocaleString()} cert(s)${r.collections_synced ? ` · ${r.collections_synced.toLocaleString()} coll.` : ""}`}
                      </p>
                      {r.error_message && <p className="truncate text-red-500" title={r.error_message}>{r.error_message}</p>}
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="flex flex-col gap-2">
            {collectionId != null && (
              <button
                type="button"
                onClick={() => handleSync("collection")}
                disabled={running}
                className="inline-flex items-center justify-center gap-1.5 rounded-lg bg-att-600 px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-att-700 disabled:cursor-not-allowed disabled:opacity-60"
              >
                <span className={running ? "animate-spin" : ""}>{RefreshIcon}</span>
                {running ? "Syncing…" : `Sync ${collectionName ? `"${collectionName}"` : "this collection"}`}
              </button>
            )}
            <button
              type="button"
              onClick={() => handleSync("all")}
              disabled={running}
              className="inline-flex items-center justify-center gap-1.5 rounded-lg border border-att-200 bg-white px-3 py-2 text-sm font-medium text-att-700 shadow-sm transition hover:border-att-300 hover:bg-att-50 disabled:cursor-not-allowed disabled:opacity-60"
            >
              <span className={running ? "animate-spin" : ""}>{RefreshIcon}</span>
              {running ? "Syncing…" : "Sync all collections"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
};

// ── Detail panel presentation (shared by schedule & alert views) ───────

const StatusPill: React.FC<{ enabled: boolean }> = ({ enabled }) => (
  <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ${enabled ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-600"}`}>
    <span className={`h-1.5 w-1.5 rounded-full ${enabled ? "bg-green-500" : "bg-gray-400"}`} />
    {enabled ? "Active" : "Disabled"}
  </span>
);

const DetailField: React.FC<{ label: string; children: React.ReactNode; className?: string }> = ({ label, children, className = "" }) => (
  <div className={`rounded-lg border border-att-100 bg-white px-3 py-2 shadow-sm ${className}`}>
    <dt className="text-[11px] font-semibold uppercase tracking-wide text-gray-400">{label}</dt>
    <dd className="mt-1 text-sm font-medium text-gray-800">{children}</dd>
  </div>
);

const DetailPanel: React.FC<{ title: string; icon: React.ReactNode; onClose: () => void; children: React.ReactNode }> = ({ title, icon, onClose, children }) => (
  <div className="border-b border-att-100 bg-gradient-to-br from-att-50/70 via-white to-white px-5 py-4">
    <div className="mb-3 flex items-center justify-between">
      <div className="flex items-center gap-2.5">
        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-att-100 text-att-700 ring-1 ring-att-200/60">{icon}</span>
        <span className="text-sm font-semibold text-gray-800">{title}</span>
      </div>
      <button type="button" onClick={onClose} className="inline-flex items-center gap-1.5 rounded-lg border border-att-200 bg-white px-3 py-1.5 text-sm font-medium text-gray-600 shadow-sm transition hover:border-att-300 hover:bg-att-50">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
        Close
      </button>
    </div>
    {children}
  </div>
);

// ── CSV column definitions (professional, comprehensive) ───────────────

const CERT_CSV_COLUMNS: CsvColumn<Certificate>[] = [
  { header: "Common Name", value: (c) => c.common_name },
  { header: "Status", value: (c) => STATUS_LABEL[c.status] ?? c.status },
  { header: "Environment", value: (c) => getCertEnv(c) },
  { header: "ENV Type", value: (c) => { const e = getCertEnv(c); return e ? (isProdEnv(e) ? "PROD" : "NPROD") : ""; } },
  { header: "Subject DN", value: (c) => c.subject_dn },
  { header: "Issuer DN", value: (c) => c.issuer_dn },
  { header: "Serial Number", value: (c) => c.serial_number },
  { header: "Thumbprint", value: (c) => c.thumbprint },
  { header: "Template", value: (c) => c.template },
  { header: "Certificate Authority", value: (c) => c.certificate_authority },
  { header: "Key Algorithm", value: (c) => c.key_algorithm },
  { header: "Key Size", value: (c) => c.key_size },
  { header: "Signing Algorithm", value: (c) => c.signing_algorithm },
  { header: "Valid From", value: (c) => c.not_before ?? "" },
  { header: "Valid To", value: (c) => c.not_after ?? "" },
  { header: "SANs", value: (c) => c.sans?.join("; ") ?? "" },
  { header: "Revoked", value: (c) => (c.revoked ? "Yes" : "No") },
  { header: "Requester", value: (c) => c.requester },
];

const AUTO_RENEWAL_CSV_COLUMNS: CsvColumn<AutoRenewalConfig>[] = [
  { header: "Collection", value: (c) => c.collection_name || `Collection ${c.collection_id}` },
  { header: "Scope", value: (c) => (c.certificates?.length ? "Specific Certificates" : "Entire Collection") },
  { header: "Certificate Count", value: (c) => c.certificates?.length ?? 0 },
  { header: "Certificates", value: (c) => c.certificates?.map((x) => x.common_name).join("; ") ?? "" },
  { header: "Renew Before (Days)", value: (c) => c.days_before_expiry },
  { header: "Status", value: (c) => (c.enabled ? "Active" : "Disabled") },
  { header: "Notification Emails", value: (c) => c.notification_emails?.join("; ") ?? "" },
  { header: "Created By", value: (c) => c.created_by },
  { header: "Created At", value: (c) => (c.created_at ? new Date(c.created_at).toISOString() : "") },
];

const ALERT_CSV_COLUMNS: CsvColumn<AlertConfig>[] = [
  { header: "Scope", value: (c) => c.collection_name || "All Collections" },
  { header: "Warning (Days)", value: (c) => c.warning_days },
  { header: "Critical (Days)", value: (c) => c.critical_days },
  { header: "Channel", value: (c) => c.notify_channel },
  { header: "Status", value: (c) => (c.enabled ? "Active" : "Disabled") },
  { header: "Notification Emails", value: (c) => c.notification_emails?.join("; ") ?? "" },
  { header: "Created By", value: (c) => c.created_by },
  { header: "Created At", value: (c) => (c.created_at ? new Date(c.created_at).toISOString() : "") },
];
// ── Sortable column keys ──────────────────────────────────────────────

type SortKey = "common_name" | "status" | "environment" | "thumbprint" | "not_before" | "not_after";

/** Read the environment value from certificate metadata (canonical Keyfactor key "Environment"). */
function getCertEnv(cert: Certificate): string {
  const md = cert.metadata ?? {};
  const direct = md["Environment"];
  if (typeof direct === "string" && direct.trim()) return direct.trim();
  for (const [k, v] of Object.entries(md)) {
    if (k.toLowerCase() === "environment" && typeof v === "string" && v.trim()) return v.trim();
  }
  return "";
}

/** Production maps to PROD; every other environment is treated as NPROD. */
function isProdEnv(env: string): boolean {
  const e = env.toLowerCase();
  return e === "production" || e === "prod";
}

const EnvBadge: React.FC<{ cert: Certificate }> = ({ cert }) => {
  const env = getCertEnv(cert);
  if (!env) return <span className="text-gray-400">—</span>;
  const prod = isProdEnv(env);
  const cls = prod ? "bg-green-100 text-green-800 ring-green-200" : "bg-amber-100 text-amber-800 ring-amber-200";
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${cls}`}
      title={`${env} · ${prod ? "PROD" : "NPROD"}`}
    >
      <span className={`h-1.5 w-1.5 rounded-full ${prod ? "bg-green-500" : "bg-amber-500"}`} />
      {env}
    </span>
  );
};

function sortCerts(items: Certificate[], sort: SortState<SortKey>): Certificate[] {
  return [...items].sort((a, b) => {
    let aVal: string;
    let bVal: string;
    if (sort.key === "environment") {
      const aEnv = getCertEnv(a);
      const bEnv = getCertEnv(b);
      // Group PROD first, then NPROD, then unknown; sub-sort by env label.
      aVal = `${aEnv ? (isProdEnv(aEnv) ? "0" : "1") : "2"}-${aEnv}`;
      bVal = `${bEnv ? (isProdEnv(bEnv) ? "0" : "1") : "2"}-${bEnv}`;
    } else {
      aVal = (a[sort.key] ?? "") as string;
      bVal = (b[sort.key] ?? "") as string;
    }
    const cmp = aVal.localeCompare(bVal);
    return sort.direction === "asc" ? cmp : -cmp;
  });
}

// ── Pagination component (consistent with InfraAlert) ─────────────────

const TablePagination: React.FC<{ currentPage: number; totalItems: number; onPageChange: (p: number) => void }> = ({ currentPage, totalItems, onPageChange }) => {
  const totalPages = Math.max(1, Math.ceil(totalItems / PAGE_SIZE));
  const startItem = totalItems === 0 ? 0 : (currentPage - 1) * PAGE_SIZE + 1;
  const endItem = Math.min(currentPage * PAGE_SIZE, totalItems);
  if (totalItems === 0) return null;
  const pages: (number | "...")[] = [];
  for (let p = 1; p <= totalPages; p++) {
    if (p === 1 || p === totalPages || Math.abs(p - currentPage) <= 1) pages.push(p);
    else if (pages[pages.length - 1] !== "...") pages.push("...");
  }
  return (
    <div className={gridStyles.pager}>
      <span className="text-sm text-gray-600">Showing {startItem}–{endItem} of {totalItems}</span>
      <div className="flex items-center gap-1">
        <button onClick={() => onPageChange(1)} disabled={currentPage <= 1} className={`${gridStyles.pagerButton} px-2 py-1 text-xs`}>«</button>
        <button onClick={() => onPageChange(currentPage - 1)} disabled={currentPage <= 1} className={gridStyles.pagerButton}>Prev</button>
        {pages.map((p, i) => p === "..." ? <span key={`e${i}`} className="px-1 text-gray-400 text-sm">…</span> : (
          <button key={p} onClick={() => onPageChange(p)} className={`min-w-[2.25rem] font-semibold ${currentPage === p ? "rounded-lg border border-att-500 bg-att-500 px-3 py-1.5 text-white shadow-sm" : `${gridStyles.pagerButton} text-gray-700`}`}>{p}</button>
        ))}
        <button onClick={() => onPageChange(currentPage + 1)} disabled={currentPage >= totalPages} className={gridStyles.pagerButton}>Next</button>
        <button onClick={() => onPageChange(totalPages)} disabled={currentPage >= totalPages} className={`${gridStyles.pagerButton} px-2 py-1 text-xs`}>»</button>
      </div>
    </div>
  );
};
// ── Audit History Panel ─────────────────────────────────────────────────

const AUDIT_PAGE_SIZE = 20;

const actionBadgeColor: Record<string, string> = {
  enroll_certificate: "bg-green-100 text-green-800",
  renew_certificate: "bg-blue-100 text-blue-800",
  revoke_certificate: "bg-red-100 text-red-800",
  update_certificate_metadata: "bg-amber-100 text-amber-800",
  delete_certificate: "bg-red-100 text-red-800",
  download_certificate: "bg-purple-100 text-purple-800",
  cert_auto_renewal_run: "bg-teal-100 text-teal-800",
};

const actionLabel: Record<string, string> = {
  enroll_certificate: "Enroll",
  renew_certificate: "Renew",
  revoke_certificate: "Revoke",
  update_certificate_metadata: "Update",
  delete_certificate: "Delete",
  download_certificate: "Download",
  cert_auto_renewal_run: "Auto-Renewal Run",
};

const AUDIT_CSV_COLUMNS: CsvColumn<CertificateAuditEntry>[] = [
  { header: "Timestamp", value: (e) => (e.timestamp ? new Date(e.timestamp).toISOString() : "") },
  { header: "Action", value: (e) => actionLabel[e.action] ?? e.action },
  { header: "Resource Type", value: () => "Certificate" },
  { header: "Certificate", value: (e) => e.resource_id ?? "" },
  { header: "Status", value: (e) => (e.status === "success" ? "Success" : "Failed") },
  { header: "User", value: (e) => e.user_email || e.user_id },
  { header: "Summary", value: (e) => e.summary ?? "" },
];

const CertificateAuditHistoryPanel: React.FC = () => {
  const { data, isLoading, isError, error, refetch, isFetching } = useCertificateAuditHistory();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "success" | "failed">("all");
  const [auditPage, setAuditPage] = useState(1);
  const [auditPageSize, setAuditPageSize] = useState(AUDIT_PAGE_SIZE);
  type AuditSortKey = "timestamp" | "action" | "resource_id" | "status" | "user_email" | "summary";
  const [auditSort, setAuditSort] = useState<SortState<AuditSortKey>>({ key: "timestamp", direction: "desc" });

  const history = data?.history ?? [];

  const filtered = useMemo(() => {
    let items = history;
    if (search.trim()) {
      const q = search.toLowerCase();
      items = items.filter((e) =>
        (e.summary || "").toLowerCase().includes(q) ||
        (e.resource_id || "").toLowerCase().includes(q) ||
        (e.user_email || "").toLowerCase().includes(q) ||
        (e.action || "").toLowerCase().includes(q)
      );
    }
    if (statusFilter !== "all") {
      items = items.filter((e) => e.status === (statusFilter === "success" ? "success" : "failed"));
    }
    return items;
  }, [history, search, statusFilter]);

  const sorted = useMemo(() => {
    return [...filtered].sort((a, b) => {
      const aVal = String((a as unknown as Record<string, unknown>)[auditSort.key] ?? "");
      const bVal = String((b as unknown as Record<string, unknown>)[auditSort.key] ?? "");
      const cmp = aVal.localeCompare(bVal);
      return auditSort.direction === "asc" ? cmp : -cmp;
    });
  }, [filtered, auditSort]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / auditPageSize));
  const safePage = Math.min(auditPage, totalPages);
  const paginated = sorted.slice((safePage - 1) * auditPageSize, safePage * auditPageSize);

  // Build page numbers with ellipsis
  const pages: (number | "...")[] = [];
  for (let p = 1; p <= totalPages; p++) {
    if (p === 1 || p === totalPages || Math.abs(p - safePage) <= 1) pages.push(p);
    else if (pages[pages.length - 1] !== "...") pages.push("...");
  }

  if (isLoading) return <p className="text-sm text-gray-500 py-4">Loading audit history…</p>;
  if (isError) return (
    <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
      <p>Failed to load audit history: {(error as Error)?.message || "Unknown error"}</p>
      <button onClick={() => refetch()} className="mt-2 underline text-xs">Retry</button>
    </div>
  );

  return (
    <div className={gridStyles.shell}>
      <div className={gridStyles.panelHeader}>
        <div className="flex flex-col gap-1">
          <span className="text-sm font-semibold text-gray-800">Certificate Audit History</span>
          <span className="text-xs text-gray-500">Tracks all certificate lifecycle operations via the shared audit log.</span>
        </div>
        <div className="ml-auto flex items-center gap-3">
          <span className={gridStyles.countBadge}>{filtered.length} events</span>
        </div>
      </div>
      <div className={gridStyles.panelHeader}>
        <div className="flex flex-wrap items-center gap-3">
          <input type="text" placeholder="Search history…" value={search} onChange={(e) => { setSearch(e.target.value); setAuditPage(1); }} className={gridStyles.toolbarInput} />
          <select value={statusFilter} onChange={(e) => { setStatusFilter(e.target.value as "all" | "success" | "failed"); setAuditPage(1); }} className={`${gridStyles.toolbarInput} w-36`}>
            <option value="all">All statuses</option>
            <option value="success">Success</option>
            <option value="failed">Failed</option>
          </select>
          <select value={auditPageSize} onChange={(e) => { setAuditPageSize(Number(e.target.value)); setAuditPage(1); }} className={`${gridStyles.toolbarInput} w-28`}>
            <option value={10}>10 / page</option>
            <option value={20}>20 / page</option>
            <option value={50}>50 / page</option>
            <option value={100}>100 / page</option>
          </select>
          <button onClick={() => refetch()} disabled={isFetching} className={gridStyles.pagerButton}>
            {isFetching ? "Refreshing…" : "Refresh"}
          </button>
          <ExportCsvButton onClick={() => exportToCsv("certificate-audit-history", sorted, AUDIT_CSV_COLUMNS)} disabled={sorted.length === 0} />
        </div>
      </div>
      <div className="overflow-auto max-h-[500px]">
        <table className={gridStyles.table}>
          <thead className={gridStyles.stickyHead}>
            <tr>
              <th className={gridStyles.headerCell}><SortableHeader label="Timestamp" active={auditSort.key === "timestamp"} direction={auditSort.direction} onClick={() => setAuditSort(nextSortState(auditSort, "timestamp"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Action" active={auditSort.key === "action"} direction={auditSort.direction} onClick={() => setAuditSort(nextSortState(auditSort, "action"))} /></th>
              <th className={gridStyles.headerCell}>Resource</th>
              <th className={gridStyles.headerCell}><SortableHeader label="Certificate" active={auditSort.key === "resource_id"} direction={auditSort.direction} onClick={() => setAuditSort(nextSortState(auditSort, "resource_id"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Status" active={auditSort.key === "status"} direction={auditSort.direction} onClick={() => setAuditSort(nextSortState(auditSort, "status"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="User" active={auditSort.key === "user_email"} direction={auditSort.direction} onClick={() => setAuditSort(nextSortState(auditSort, "user_email"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Summary" active={auditSort.key === "summary"} direction={auditSort.direction} onClick={() => setAuditSort(nextSortState(auditSort, "summary"))} /></th>
            </tr>
          </thead>
          <tbody>
            {paginated.map((entry: CertificateAuditEntry) => (
              <tr key={entry.id} className={gridStyles.row}>
                <td className={`${gridStyles.cell} text-xs whitespace-nowrap`}>{formatDateTime(entry.timestamp)}</td>
                <td className={gridStyles.cell}>
                  <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${actionBadgeColor[entry.action] || "bg-gray-100 text-gray-700"}`}>
                    {actionLabel[entry.action] || entry.action}
                  </span>
                </td>
                <td className={gridStyles.cell}><span className="inline-flex items-center rounded-full bg-att-50 px-2 py-0.5 text-xs font-medium text-att-700">Certificate</span></td>
                <td className={`${gridStyles.cell} text-xs max-w-[200px] truncate`} title={entry.resource_id || ""}>{entry.resource_id || "—"}</td>
                <td className={gridStyles.cell}>
                  <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${entry.status === "success" ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"}`}>
                    {entry.status === "success" ? "Success" : "Failed"}
                  </span>
                </td>
                <td className={`${gridStyles.cell} text-xs`}>{entry.user_email || entry.user_id}</td>
                <td className={`${gridStyles.cell} text-xs text-gray-600`}>{entry.summary}</td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="py-8 text-center text-sm text-gray-400">No certificate audit entries found.</td></tr>
            )}
          </tbody>
        </table>
      </div>
      {/* Pagination */}
      <div className={gridStyles.pager}>
        <span className="text-sm text-gray-600">Showing {sorted.length === 0 ? 0 : (safePage - 1) * auditPageSize + 1}–{Math.min(safePage * auditPageSize, sorted.length)} of {sorted.length}</span>
        <div className="flex items-center gap-1">
          <button onClick={() => setAuditPage(1)} disabled={safePage <= 1} className={`${gridStyles.pagerButton} px-2 py-1 text-xs`}>«</button>
          <button onClick={() => setAuditPage((p) => p - 1)} disabled={safePage <= 1} className={gridStyles.pagerButton}>Prev</button>
          {pages.map((p, i) => p === "..." ? <span key={`e${i}`} className="px-1 text-gray-400 text-sm">…</span> : (
            <button key={p} onClick={() => setAuditPage(p)} className={`min-w-[2.25rem] font-semibold ${safePage === p ? "rounded-lg border border-att-500 bg-att-500 px-3 py-1.5 text-white shadow-sm" : `${gridStyles.pagerButton} text-gray-700`}`}>{p}</button>
          ))}
          <button onClick={() => setAuditPage((p) => p + 1)} disabled={safePage >= totalPages} className={gridStyles.pagerButton}>Next</button>
          <button onClick={() => setAuditPage(totalPages)} disabled={safePage >= totalPages} className={`${gridStyles.pagerButton} px-2 py-1 text-xs`}>»</button>
        </div>
      </div>
    </div>
  );
};
// ── Auto-Renewal Panel ────────────────────────────────────────────────

const AutoRenewalPanel: React.FC<{ onToast: (message: string, type?: ToastType) => void }> = ({ onToast }) => {
  const { data: configs, isLoading } = useAutoRenewalConfigs();
  const { data: collections } = useCollections();
  const create = useCreateAutoRenewalConfig();
  const remove = useDeleteAutoRenewalConfig();
  const run = useRunAutoRenewalConfig();
  const [runningId, setRunningId] = useState<number | null>(null);

  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [viewingConfig, setViewingConfig] = useState<AutoRenewalConfig | null>(null);
  const [formCollectionId, setFormCollectionId] = useState<number | "">("");
  const [formDays, setFormDays] = useState(60);
  const [formEmails, setFormEmails] = useState("");
  const [formScope, setFormScope] = useState<"collection" | "certificates">("collection");
  const [formCerts, setFormCerts] = useState<AutoRenewalCertificateRef[]>([]);

  const resetForm = () => {
    setShowForm(false);
    setEditingId(null);
    setFormCollectionId("");
    setFormDays(60);
    setFormEmails("");
    setFormScope("collection");
    setFormCerts([]);
  };

  const handleEdit = (c: NonNullable<typeof configs>[number]) => {
    setEditingId(c.id);
    setFormCollectionId(c.collection_id ?? "");
    setFormDays(c.days_before_expiry);
    setFormEmails(c.notification_emails?.join(", ") || "");
    const certs = c.certificates ?? [];
    setFormScope(certs.length > 0 ? "certificates" : "collection");
    setFormCerts(certs);
    setShowForm(true);
  };

  const handleCollectionChange = (value: number | "") => {
    setFormCollectionId(value);
    setFormCerts([]);
  };

  const handleCreate = async () => {
    if (!formCollectionId) return;
    if (formScope === "certificates" && formCerts.length === 0) return;
    const collectionName = collections?.find((col) => col.id === Number(formCollectionId))?.name || "";
    // If editing, delete old config first then create new
    if (editingId) {
      await remove.mutateAsync(editingId);
    }
    await create.mutateAsync({
      collection_id: Number(formCollectionId),
      collection_name: collectionName,
      days_before_expiry: formDays,
      notify_on_renewal: true,
      notification_emails: formEmails.split(",").map((e) => e.trim()).filter(Boolean),
      certificates: formScope === "certificates" ? formCerts : [],
    });
    resetForm();
  };

  const handleRun = (c: AutoRenewalConfig) => {
    if (run.isPending) return;
    setRunningId(c.id);
    run.mutate(c.id, {
      onSuccess: (r) => {
        const dueText = r.certificates_due == null ? "" : ` — ${r.certificates_due} certificate(s) due within ${r.days_before_expiry} days`;
        onToast(`Auto-renewal triggered for ${r.collection_name || "collection"}${dueText}. Recorded in audit log.`, "success");
      },
      onError: (e) => onToast(certificateErrorMessage(e, "Failed to run auto-renewal."), "error"),
      onSettled: () => setRunningId(null),
    });
  };

  return (
    <div className={gridStyles.shell}>
      <div className={gridStyles.panelHeader}>
        <div className="flex flex-col gap-1">
          <span className="text-sm font-semibold text-gray-800">Auto-Renewal Scheduling</span>
          <span className="text-xs text-gray-500">Configure automatic certificate renewal a set number of days before expiry. A schedule triggers when a certificate enters its renewal window; use “Run now” to trigger a check immediately — every run is recorded in the audit log.</span>
        </div>
        <div className="flex items-center gap-2">
          <ExportCsvButton onClick={() => exportToCsv("certificate-auto-renewal", configs ?? [], AUTO_RENEWAL_CSV_COLUMNS)} disabled={!configs?.length} />
          <button type="button" className="rounded-lg bg-att-600 px-4 py-2 text-sm font-medium text-white hover:bg-att-700" onClick={() => { resetForm(); setShowForm(true); }}>+ Add Schedule</button>
        </div>
      </div>

      {showForm && (
        <div className="border-b border-att-100 bg-att-50/30 px-5 py-4 space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wide text-gray-600 mb-1">Collection *</label>
              <select className={gridStyles.toolbarInput + " w-full"} value={formCollectionId} onChange={(e) => handleCollectionChange(e.target.value ? Number(e.target.value) : "")}>
                <option value="">Select…</option>
                {collections?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wide text-gray-600 mb-1">Days Before Expiry</label>
              <select className={gridStyles.toolbarInput + " w-full"} value={formDays} onChange={(e) => setFormDays(Number(e.target.value))}>
                <option value={30}>30 days</option>
                <option value={45}>45 days</option>
                <option value={60}>60 days</option>
                <option value={90}>90 days</option>
                <option value={120}>120 days</option>
              </select>
            </div>
            <div className="sm:col-span-2">
              <label className="block text-xs font-semibold uppercase tracking-wide text-gray-600 mb-1">Notification Emails (comma-separated)</label>
              <input className={gridStyles.toolbarInput + " w-full"} value={formEmails} onChange={(e) => setFormEmails(e.target.value)} placeholder="admin@att.com, ops@att.com" />
            </div>
          </div>

          {/* Scope: entire collection vs. specific certificates */}
          <div>
            <label className="block text-xs font-semibold uppercase tracking-wide text-gray-600 mb-1">Apply To</label>
            <div className="inline-flex rounded-lg border border-att-200 bg-white p-0.5">
              <button type="button" onClick={() => setFormScope("collection")} className={`rounded-md px-3 py-1.5 text-sm font-medium transition ${formScope === "collection" ? "bg-att-600 text-white shadow-sm" : "text-gray-600 hover:text-gray-800"}`}>Entire Collection</button>
              <button type="button" onClick={() => setFormScope("certificates")} disabled={!formCollectionId} className={`rounded-md px-3 py-1.5 text-sm font-medium transition disabled:cursor-not-allowed disabled:opacity-50 ${formScope === "certificates" ? "bg-att-600 text-white shadow-sm" : "text-gray-600 hover:text-gray-800"}`}>Specific Certificates</button>
            </div>
            <p className="mt-1 text-xs text-gray-500">
              {formScope === "collection"
                ? "Every certificate in the collection will be auto-renewed."
                : "Only the certificates you select below will be auto-renewed."}
            </p>
          </div>

          {formScope === "certificates" && formCollectionId !== "" && (
            <CertificateMultiSelect collectionId={Number(formCollectionId)} selected={formCerts} onChange={setFormCerts} />
          )}

          <div className="flex gap-2">
            <button type="button" className="rounded-lg bg-att-600 px-4 py-2 text-sm font-medium text-white hover:bg-att-700 disabled:opacity-50" disabled={!formCollectionId || (formScope === "certificates" && formCerts.length === 0) || create.isPending} onClick={handleCreate}>{create.isPending ? "Saving…" : editingId ? "Update Schedule" : "Save Schedule"}</button>
            <button type="button" className={gridStyles.pagerButton} onClick={resetForm}>Cancel</button>
          </div>
        </div>
      )}

      {/* View detail overlay */}
      {viewingConfig && (
        <DetailPanel title="Schedule Details" icon={Icons.refresh} onClose={() => setViewingConfig(null)}>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            <DetailField label="Collection">{viewingConfig.collection_name || `Collection ${viewingConfig.collection_id}`}</DetailField>
            <DetailField label="Scope">
              {viewingConfig.certificates?.length ? (
                <span className="inline-flex items-center rounded-full bg-purple-100 px-2.5 py-0.5 text-xs font-medium text-purple-800">{viewingConfig.certificates.length} certificate{viewingConfig.certificates.length === 1 ? "" : "s"}</span>
              ) : (
                <span className="inline-flex items-center rounded-full bg-att-100 px-2.5 py-0.5 text-xs font-medium text-att-700">Entire collection</span>
              )}
            </DetailField>
            <DetailField label="Renew Before"><span className="inline-flex items-center rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800">{viewingConfig.days_before_expiry} days</span></DetailField>
            <DetailField label="Status"><StatusPill enabled={viewingConfig.enabled} /></DetailField>
            <DetailField label="Notification Emails" className="sm:col-span-2">{viewingConfig.notification_emails?.length ? viewingConfig.notification_emails.join(", ") : "—"}</DetailField>
            <DetailField label="Created By">{viewingConfig.created_by}</DetailField>
            <DetailField label="Created At">{viewingConfig.created_at ? new Date(viewingConfig.created_at).toLocaleString() : "—"}</DetailField>
            <DetailField label="Last Run">{viewingConfig.last_run_at ? new Date(viewingConfig.last_run_at).toLocaleString() : "Never"}</DetailField>
          </dl>
          {viewingConfig.certificates && viewingConfig.certificates.length > 0 && (
            <div className="mt-3 rounded-lg border border-att-100 bg-white px-3 py-2.5 shadow-sm">
              <p className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-gray-400">Certificates ({viewingConfig.certificates.length})</p>
              <div className="flex flex-wrap gap-1.5">
                {viewingConfig.certificates.map((x) => (
                  <span key={x.id} className="inline-flex items-center gap-1.5 rounded-full border border-att-200 bg-att-50 px-2.5 py-1 text-xs font-medium text-att-700" title={x.thumbprint}>
                    <span className="h-1.5 w-1.5 rounded-full bg-att-400" />
                    {x.common_name || `#${x.id}`}
                  </span>
                ))}
              </div>
            </div>
          )}
        </DetailPanel>
      )}

      <table className={gridStyles.table}>
        <thead className={gridStyles.head}>
          <tr>
            <th className={gridStyles.headerCell}>Collection</th>
            <th className={gridStyles.headerCell}>Scope</th>
            <th className={gridStyles.headerCell}>Renew Before</th>
            <th className={gridStyles.headerCell}>Status</th>
            <th className={gridStyles.headerCell}>Notification Emails</th>
            <th className={gridStyles.headerCell}>Created By</th>
            <th className={gridStyles.headerCell}>Last Run</th>
            <th className={gridStyles.headerCellCenter}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            <tr><td colSpan={8} className="px-4 py-8 text-center text-sm text-gray-500">Loading…</td></tr>
          ) : !configs?.length ? (
            <tr><td colSpan={8} className="px-4 py-8 text-center text-sm text-gray-500">No auto-renewal schedules configured. Click “+ Add Schedule” to get started.</td></tr>
          ) : configs.map((c) => (
            <tr key={c.id} className={gridStyles.row}>
              <td className={gridStyles.strongCell}>{c.collection_name || `Collection ${c.collection_id}`}</td>
              <td className={gridStyles.cell}>
                {c.certificates && c.certificates.length > 0 ? (
                  <span className="inline-flex items-center rounded-full bg-purple-100 px-2.5 py-0.5 text-xs font-medium text-purple-800" title={c.certificates.map((x) => x.common_name).join(", ")}>{c.certificates.length} certificate{c.certificates.length === 1 ? "" : "s"}</span>
                ) : (
                  <span className="inline-flex items-center rounded-full bg-att-50 px-2.5 py-0.5 text-xs font-medium text-att-700">Entire collection</span>
                )}
              </td>
              <td className={gridStyles.cell}><span className="inline-flex items-center rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800">{c.days_before_expiry} days</span></td>
              <td className={gridStyles.cell}><span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${c.enabled ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-600"}`}>{c.enabled ? "Active" : "Disabled"}</span></td>
              <td className={`${gridStyles.cell} text-xs`}>{c.notification_emails?.join(", ") || "—"}</td>
              <td className={`${gridStyles.cell} text-xs`}>{c.created_by}</td>
              <td className={`${gridStyles.cell} whitespace-nowrap text-xs`} title={c.last_run_at ? formatDateTime(c.last_run_at) : "Never triggered"}>{c.last_run_at ? formatDateTime(c.last_run_at) : "Never"}</td>
              <td className={gridStyles.centerCell}>
                <div className="flex items-center justify-center gap-0.5">
                  <ActionBtn title="Run now" tone="green" disabled={run.isPending} onClick={() => handleRun(c)}>{run.isPending && runningId === c.id ? SpinnerIcon : Icons.play}</ActionBtn>
                  <ActionBtn title="View" tone="blue" onClick={() => setViewingConfig(c)}>{Icons.eye}</ActionBtn>
                  <ActionBtn title="Edit" tone="blue" onClick={() => handleEdit(c)}>{Icons.edit}</ActionBtn>
                  <ActionBtn title="Delete" tone="red" onClick={() => remove.mutate(c.id)}>{Icons.trash}</ActionBtn>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

// ── Alerts Panel ─────────────────────────────────────────────────────

const AlertsPanel: React.FC = () => {
  const { data: configs, isLoading } = useAlertConfigs();
  const { data: collections } = useCollections();
  const create = useCreateAlertConfig();
  const remove = useDeleteAlertConfig();

  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<number | null>(null);
  const [viewingConfig, setViewingConfig] = useState<AlertConfig | null>(null);
  const [formCollectionId, setFormCollectionId] = useState<number | null | "">(null);
  const [formWarning, setFormWarning] = useState(60);
  const [formCritical, setFormCritical] = useState(30);
  const [formChannel, setFormChannel] = useState("email");
  const [formEmails, setFormEmails] = useState("");

  const resetForm = () => {
    setShowForm(false);
    setEditingId(null);
    setFormCollectionId(null);
    setFormWarning(60);
    setFormCritical(30);
    setFormChannel("email");
    setFormEmails("");
  };

  const handleEdit = (c: NonNullable<typeof configs>[number]) => {
    setEditingId(c.id);
    setFormCollectionId(c.collection_id ?? null);
    setFormWarning(c.warning_days);
    setFormCritical(c.critical_days);
    setFormChannel(c.notify_channel);
    setFormEmails(c.notification_emails?.join(", ") || "");
    setShowForm(true);
  };

  const handleCreate = async () => {
    const collectionName = formCollectionId ? (collections?.find((col) => col.id === Number(formCollectionId))?.name || "") : "";
    // If editing, delete old config first then create new
    if (editingId) {
      await remove.mutateAsync(editingId);
    }
    await create.mutateAsync({
      collection_id: formCollectionId || null,
      collection_name: collectionName,
      warning_days: formWarning,
      critical_days: formCritical,
      notify_channel: formChannel,
      notification_emails: formEmails.split(",").map((e) => e.trim()).filter(Boolean),
    });
    resetForm();
  };

  return (
    <div className={gridStyles.shell}>
      <div className={gridStyles.panelHeader}>
        <div className="flex flex-col gap-1">
          <span className="text-sm font-semibold text-gray-800">Certificate Expiry Alerts</span>
          <span className="text-xs text-gray-500">Configure notifications when certificates approach expiry. Warning and critical thresholds trigger alerts at different urgency levels.</span>
        </div>
        <div className="flex items-center gap-2">
          <ExportCsvButton onClick={() => exportToCsv("certificate-alert-rules", configs ?? [], ALERT_CSV_COLUMNS)} disabled={!configs?.length} />
          <button type="button" className="rounded-lg bg-att-600 px-4 py-2 text-sm font-medium text-white hover:bg-att-700" onClick={() => { resetForm(); setShowForm(true); }}>+ Add Alert Rule</button>
        </div>
      </div>

      {showForm && (
        <div className="border-b border-att-100 bg-att-50/30 px-5 py-4 space-y-3">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-5">
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wide text-gray-600 mb-1">Scope</label>
              <select className={gridStyles.toolbarInput + " w-full"} value={formCollectionId ?? ""} onChange={(e) => setFormCollectionId(e.target.value ? Number(e.target.value) : null)}>
                <option value="">All Collections</option>
                {collections?.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wide text-gray-600 mb-1">Warning (days)</label>
              <select className={gridStyles.toolbarInput + " w-full"} value={formWarning} onChange={(e) => setFormWarning(Number(e.target.value))}>
                {[30, 45, 60, 90, 120, 180].map((d) => <option key={d} value={d}>{d} days</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wide text-gray-600 mb-1">Critical (days)</label>
              <select className={gridStyles.toolbarInput + " w-full"} value={formCritical} onChange={(e) => setFormCritical(Number(e.target.value))}>
                {[7, 14, 21, 30, 45, 60].map((d) => <option key={d} value={d}>{d} days</option>)}
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wide text-gray-600 mb-1">Channel</label>
              <select className={gridStyles.toolbarInput + " w-full"} value={formChannel} onChange={(e) => setFormChannel(e.target.value)}>
                <option value="email">Email</option>
                <option value="teams">Teams</option>
                <option value="both">Both</option>
              </select>
            </div>
            <div>
              <label className="block text-xs font-semibold uppercase tracking-wide text-gray-600 mb-1">Notification Emails</label>
              <input className={gridStyles.toolbarInput + " w-full"} value={formEmails} onChange={(e) => setFormEmails(e.target.value)} placeholder="ops@att.com" />
            </div>
          </div>
          <div className="flex gap-2">
            <button type="button" className="rounded-lg bg-att-600 px-4 py-2 text-sm font-medium text-white hover:bg-att-700 disabled:opacity-50" disabled={create.isPending} onClick={handleCreate}>{create.isPending ? "Saving…" : editingId ? "Update Alert Rule" : "Save Alert Rule"}</button>
            <button type="button" className={gridStyles.pagerButton} onClick={resetForm}>Cancel</button>
          </div>
        </div>
      )}

      {/* View detail overlay */}
      {viewingConfig && (
        <DetailPanel title="Alert Rule Details" icon={Icons.warn} onClose={() => setViewingConfig(null)}>
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            <DetailField label="Scope">{viewingConfig.collection_name || "All Collections"}</DetailField>
            <DetailField label="Warning"><span className="inline-flex items-center rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800">{viewingConfig.warning_days} days</span></DetailField>
            <DetailField label="Critical"><span className="inline-flex items-center rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-800">{viewingConfig.critical_days} days</span></DetailField>
            <DetailField label="Channel"><span className="capitalize">{viewingConfig.notify_channel}</span></DetailField>
            <DetailField label="Status"><StatusPill enabled={viewingConfig.enabled} /></DetailField>
            <DetailField label="Notification Emails" className="sm:col-span-2">{viewingConfig.notification_emails?.length ? viewingConfig.notification_emails.join(", ") : "—"}</DetailField>
            <DetailField label="Created By">{viewingConfig.created_by}</DetailField>
            <DetailField label="Created At">{viewingConfig.created_at ? new Date(viewingConfig.created_at).toLocaleString() : "—"}</DetailField>
          </dl>
        </DetailPanel>
      )}

      <table className={gridStyles.table}>
        <thead className={gridStyles.head}>
          <tr>
            <th className={gridStyles.headerCell}>Scope</th>
            <th className={gridStyles.headerCell}>Warning</th>
            <th className={gridStyles.headerCell}>Critical</th>
            <th className={gridStyles.headerCell}>Channel</th>
            <th className={gridStyles.headerCell}>Status</th>
            <th className={gridStyles.headerCell}>Emails</th>
            <th className={gridStyles.headerCell}>Created By</th>
            <th className={gridStyles.headerCellCenter}>Actions</th>
          </tr>
        </thead>
        <tbody>
          {isLoading ? (
            <tr><td colSpan={8} className="px-4 py-8 text-center text-sm text-gray-500">Loading…</td></tr>
          ) : !configs?.length ? (
            <tr><td colSpan={8} className="px-4 py-8 text-center text-sm text-gray-500">No alert rules configured. Click “+ Add Alert Rule” to get started.</td></tr>
          ) : configs.map((c) => (
            <tr key={c.id} className={gridStyles.row}>
              <td className={gridStyles.strongCell}>{c.collection_name || "All Collections"}</td>
              <td className={gridStyles.cell}><span className="inline-flex items-center rounded-full bg-amber-100 px-2.5 py-0.5 text-xs font-medium text-amber-800">{c.warning_days}d</span></td>
              <td className={gridStyles.cell}><span className="inline-flex items-center rounded-full bg-red-100 px-2.5 py-0.5 text-xs font-medium text-red-800">{c.critical_days}d</span></td>
              <td className={gridStyles.cell}><span className="capitalize text-sm">{c.notify_channel}</span></td>
              <td className={gridStyles.cell}><span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${c.enabled ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-600"}`}>{c.enabled ? "Active" : "Disabled"}</span></td>
              <td className={`${gridStyles.cell} text-xs`}>{c.notification_emails?.join(", ") || "—"}</td>
              <td className={`${gridStyles.cell} text-xs`}>{c.created_by}</td>
              <td className={gridStyles.centerCell}>
                <div className="flex items-center justify-center gap-0.5">
                  <ActionBtn title="View" tone="blue" onClick={() => setViewingConfig(c)}>{Icons.eye}</ActionBtn>
                  <ActionBtn title="Edit" tone="blue" onClick={() => handleEdit(c)}>{Icons.edit}</ActionBtn>
                  <ActionBtn title="Delete" tone="red" onClick={() => remove.mutate(c.id)}>{Icons.trash}</ActionBtn>
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

// ── Main Page Component ───────────────────────────────────────────────

type ModalKind = "enroll" | "view" | "renew" | "revoke" | "delete" | "metadata" | "download" | "load_to_akv" | null;

const CertificatesPage: React.FC = () => {
  const { isAdmin } = useAuth();
  const { canEditPage } = usePermissions();
  const canWrite = isAdmin || canEditPage("certificates_main");

  const [activeTab, setActiveTab] = useState<"certificates" | "auto-renewal" | "alerts" | "audit">("certificates");

  const { data: collections, isLoading: collectionsLoading } = useCollections();
  const [collectionId, setCollectionId] = useState<number | undefined>(undefined);
  const [collectionSearch, setCollectionSearch] = useState("");

  const [draft, setDraft] = useState({ cn: "", thumbprint: "", issuer: "" });
  const [filters, setFilters] = useState<CertificateListParams>({ page: 1, page_size: PAGE_SIZE });
  const [expiryDays, setExpiryDays] = useState<number | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<SortState<SortKey>>({ key: "common_name", direction: "asc" });
  const [modal, setModal] = useState<ModalKind>(null);
  const [selected, setSelected] = useState<Certificate | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const [exporting, setExporting] = useState(false);
  const [openActionMenu, setOpenActionMenu] = useState<number | null>(null);

  useEffect(() => {
    if (openActionMenu === null) return;
    const close = () => setOpenActionMenu(null);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [openActionMenu]);

  const showToast = useCallback((message: string, type: ToastType = "success") => setToast({ message, type }), []);

  const params = useMemo<CertificateListParams>(
    () => ({ ...filters, collection_id: collectionId, expires_in_days: expiryDays, page, page_size: PAGE_SIZE }),
    [filters, collectionId, expiryDays, page]
  );
  const { data, isLoading, isError, error, refetch, isFetching } = useCertificates(params, collectionId != null);

  const items = useMemo(() => sortCerts(data?.items ?? [], sort), [data?.items, sort]);
  const total = data?.total ?? 0;

  // Accurate, collection-wide counts for the tiles (not page-scoped).
  const { data: stats, isLoading: statsLoading } = useCollectionCertStats(collectionId);
  const fmtStat = (v: number | undefined): string =>
    collectionId == null ? "—" : statsLoading ? "…" : (v ?? 0).toLocaleString();
  const expiringByDays: Record<number, number | undefined> = { 30: stats?.expiring30, 60: stats?.expiring60, 90: stats?.expiring90 };

  const applyFilters = () => {
    setPage(1);
    setFilters({ page: 1, page_size: PAGE_SIZE, cn: draft.cn.trim() || undefined, thumbprint: draft.thumbprint.trim() || undefined, issuer: draft.issuer.trim() || undefined });
  };
  const clearFilters = () => { setDraft({ cn: "", thumbprint: "", issuer: "" }); setPage(1); setFilters({ page: 1, page_size: PAGE_SIZE }); };
  const openModal = (kind: ModalKind, cert?: Certificate) => { setSelected(cert ?? null); setModal(kind); };
  const closeModal = () => { setModal(null); setSelected(null); };

  const handleExportCertificates = async () => {
    if (collectionId == null) return;
    setExporting(true);
    try {
      const rows = await fetchAllCertificatesForExport(params);
      exportToCsv("certificates", rows, CERT_CSV_COLUMNS);
      const capped = rows.length < total ? ` (capped at ${rows.length.toLocaleString()} of ${total.toLocaleString()})` : "";
      showToast(`Exported ${rows.length.toLocaleString()} certificate(s) to CSV${capped}.`, "success");
    } catch (e) {
      showToast(certificateErrorMessage(e, "CSV export failed."), "error");
    } finally {
      setExporting(false);
    }
  };

  // Filter collections by search text
  const filteredCollections = useMemo(() => {
    if (!collections) return [];
    if (!collectionSearch.trim()) return collections;
    const q = collectionSearch.toLowerCase();
    return collections.filter((c) => c.name.toLowerCase().includes(q));
  }, [collections, collectionSearch]);

  const selectedCollectionName = useMemo(
    () => collections?.find((c) => c.id === collectionId)?.name,
    [collections, collectionId]
  );

  return (
    <div className="mx-auto max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
      <div className="mb-6 flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Certificate Management</h1>
          <p className="mt-1 text-sm text-gray-500">Manage the certificate lifecycle via Keyfactor Command.</p>
        </div>
        {canWrite && (
          <button type="button" className="rounded-lg bg-att-600 px-4 py-2 text-sm font-medium text-white hover:bg-att-700" onClick={() => openModal("enroll")}>+ Enroll Certificate</button>
        )}
      </div>

      {/* Tabs */}
      <div className="mb-6 flex items-center gap-1 border-b border-att-100">
        <button
          type="button"
          onClick={() => setActiveTab("certificates")}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition border-b-2 ${activeTab === "certificates" ? "border-att-500 text-att-700" : "border-transparent text-gray-500 hover:text-gray-700"}`}
        >
          {Icons.cert}
          Certificates
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("auto-renewal")}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition border-b-2 ${activeTab === "auto-renewal" ? "border-att-500 text-att-700" : "border-transparent text-gray-500 hover:text-gray-700"}`}
        >
          {Icons.refresh}
          Auto-Renewal
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("alerts")}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition border-b-2 ${activeTab === "alerts" ? "border-att-500 text-att-700" : "border-transparent text-gray-500 hover:text-gray-700"}`}
        >
          {Icons.warn}
          Expiry Alerts
        </button>
        <button
          type="button"
          onClick={() => setActiveTab("audit")}
          className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium transition border-b-2 ${activeTab === "audit" ? "border-att-500 text-att-700" : "border-transparent text-gray-500 hover:text-gray-700"}`}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
          Audit History
        </button>
      </div>

      {activeTab === "certificates" && (<>
      {/* Certificate Collection Tiles (clickable selector) */}
      <div className="mb-4">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Certificate Collections</p>
          <div className="flex flex-wrap items-center gap-2">
            <SyncControl collectionId={collectionId} collectionName={selectedCollectionName} onToast={showToast} />
            <input
              aria-label="Search collections"
              className={`${gridStyles.toolbarInput} w-52`}
              placeholder="Search collections…"
              value={collectionSearch}
              onChange={(e) => setCollectionSearch(e.target.value)}
            />
            {collectionId != null && (
              <button type="button" className="text-xs font-medium text-att-600 hover:text-att-700" onClick={() => { setCollectionId(undefined); setPage(1); }}>Clear selection</button>
            )}
          </div>
        </div>
        {collectionsLoading ? (
          <div className="rounded-xl border border-dashed border-att-200 bg-white p-4 text-center text-sm text-gray-500">Loading collections…</div>
        ) : filteredCollections.length > 0 ? (
          <div className="grid max-h-80 grid-cols-1 gap-3 overflow-y-auto pr-1 sm:grid-cols-2 lg:grid-cols-3">
            {filteredCollections.map((c) => (
              <button
                key={c.id}
                type="button"
                aria-pressed={collectionId === c.id}
                onClick={() => { setCollectionId(collectionId === c.id ? undefined : c.id); setPage(1); }}
                className={`flex items-center gap-3 rounded-xl border p-4 text-left transition ${
                  collectionId === c.id
                    ? "border-att-500 bg-att-50 ring-2 ring-att-200"
                    : "border-att-100 bg-white hover:border-att-300 hover:bg-att-50/50"
                }`}
              >
                <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-att-100 text-att-700">
                  {Icons.collection}
                </div>
                <div className="min-w-0 flex-1">
                  <p className="truncate text-sm font-semibold text-gray-900" title={c.name}>{c.name}</p>
                  <p className="text-xs text-gray-500">{(collectionId === c.id && stats ? stats.total : c.certificate_count).toLocaleString()} certs</p>
                </div>
                {collectionId === c.id && (
                  <span className="shrink-0 rounded-full bg-att-100 px-2 py-0.5 text-xs font-medium text-att-600">Active</span>
                )}
              </button>
            ))}
          </div>
        ) : (
          <div className="rounded-xl border border-dashed border-att-200 bg-white p-4 text-center text-sm text-gray-500">
            {collectionSearch.trim() ? "No collections match your search." : "No certificate collections available."}
          </div>
        )}
      </div>

      {/* Expiry Filter Cards */}
      <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {[30, 60, 90].map((days) => (
          <button
            key={days}
            type="button"
            onClick={() => { setExpiryDays(expiryDays === days ? undefined : days); setPage(1); }}
            className={`flex items-center gap-3 rounded-xl border p-4 text-left transition ${
              expiryDays === days
                ? "border-att-500 bg-att-50 ring-2 ring-att-200"
                : "border-att-100 bg-white hover:border-att-300 hover:bg-att-50/50"
            }`}
          >
            <div className={`flex h-10 w-10 items-center justify-center rounded-lg ${
              days === 30 ? "bg-red-100 text-red-700" : days === 60 ? "bg-amber-100 text-amber-700" : "bg-blue-100 text-blue-700"
            }`}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10" /><polyline points="12 6 12 12 16 14" /></svg>
            </div>
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500">Expiring in {days} Days</p>
              <p className="text-lg font-bold text-gray-900">{fmtStat(expiringByDays[days])}</p>
            </div>
            {expiryDays === days && (
              <span className="ml-auto text-xs font-medium text-att-600 bg-att-100 px-2 py-0.5 rounded-full">Active</span>
            )}
          </button>
        ))}
      </div>

      <div className={gridStyles.shell}>
        {/* Toolbar */}
        <div className={gridStyles.panelHeader}>
          <div className="flex flex-wrap items-center gap-2">
            <input aria-label="Filter by common name" className={gridStyles.toolbarInput} placeholder="Common name…" value={draft.cn} onChange={(e) => setDraft({ ...draft, cn: e.target.value })} onKeyDown={(e) => e.key === "Enter" && applyFilters()} />
            <input aria-label="Filter by thumbprint" className={gridStyles.toolbarInput} placeholder="Thumbprint…" value={draft.thumbprint} onChange={(e) => setDraft({ ...draft, thumbprint: e.target.value })} onKeyDown={(e) => e.key === "Enter" && applyFilters()} />
            <input aria-label="Filter by issuer" className={gridStyles.toolbarInput} placeholder="Issuer…" value={draft.issuer} onChange={(e) => setDraft({ ...draft, issuer: e.target.value })} onKeyDown={(e) => e.key === "Enter" && applyFilters()} />
            <button type="button" className={gridStyles.pagerButton} onClick={applyFilters}>Search</button>
            <button type="button" className={gridStyles.pagerButton} onClick={clearFilters}>Clear</button>
          </div>
          <div className="flex items-center gap-2">
            <span className={gridStyles.countBadge}>{total} total{isFetching ? " · refreshing…" : ""}</span>
            <ExportCsvButton onClick={handleExportCertificates} disabled={collectionId == null || total === 0} busy={exporting} />
          </div>
        </div>

        {/* Table */}
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.stickyHead}>
              <tr>
                <th className={gridStyles.headerCell}><SortableHeader label="Common Name" active={sort.key === "common_name"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "common_name"))} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Status" active={sort.key === "status"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "status"))} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="ENV" active={sort.key === "environment"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "environment"))} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Thumbprint" active={sort.key === "thumbprint"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "thumbprint"))} /></th>
                <th className={gridStyles.headerCell}><SortableHeader label="Expiry Date" active={sort.key === "not_after"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "not_after"))} /></th>
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-sm text-gray-500">Loading certificates…</td></tr>
              ) : isError ? (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-sm text-red-600" role="alert">{(error as Error)?.message || "Failed to load certificates."} <button type="button" className="underline" onClick={() => refetch()}>Retry</button></td></tr>
              ) : collectionId == null ? (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-sm text-gray-500">Select a collection from the tiles above to view certificates.</td></tr>
              ) : items.length === 0 ? (
                <tr><td colSpan={6} className="px-4 py-10 text-center text-sm text-gray-500">No certificates found in this collection.</td></tr>
              ) : (
                items.map((cert) => (
                  <tr key={cert.id} className={gridStyles.row}>
                    <td className={gridStyles.strongCell}>{cert.common_name || "—"}</td>
                    <td className={gridStyles.cell}><StatusBadge status={cert.status} /></td>
                    <td className={gridStyles.cell}><EnvBadge cert={cert} /></td>
                    <td className={gridStyles.cell}><span className="font-mono text-xs" title={cert.thumbprint}>{cert.thumbprint || "—"}</span></td>
                    <td className={gridStyles.cell}><ExpiryBadge not_after={cert.not_after} /></td>
                    <td className={gridStyles.centerCell}>
                      <div className="relative flex items-center justify-center">
                        <button
                          type="button"
                          title="Certificate actions"
                          className="rounded-lg p-2 text-gray-500 transition hover:bg-gray-100 hover:text-gray-800"
                          onClick={(e) => { e.stopPropagation(); setOpenActionMenu(openActionMenu === cert.id ? null : cert.id); }}
                        >
                          {Icons.more}
                        </button>
                        {openActionMenu === cert.id && (
                          <div
                            className="absolute right-0 top-8 z-30 min-w-[180px] rounded-xl border border-att-100 bg-white py-1 shadow-xl"
                            onMouseLeave={() => setOpenActionMenu(null)}
                          >
                            <button type="button" className="flex w-full items-center gap-2.5 px-4 py-2 text-sm text-gray-700 hover:bg-att-50" onClick={() => { setOpenActionMenu(null); openModal("view", cert); }}>
                              {Icons.eye} <span>View Certificate</span>
                            </button>
                            <button type="button" className="flex w-full items-center gap-2.5 px-4 py-2 text-sm text-gray-700 hover:bg-att-50" onClick={() => { setOpenActionMenu(null); openModal("download", cert); }}>
                              {Icons.download} <span>Download</span>
                            </button>
                            {canWrite && <>
                              <div className="my-1 border-t border-att-100" />
                              <button type="button" className="flex w-full items-center gap-2.5 px-4 py-2 text-sm text-green-700 hover:bg-green-50" onClick={() => { setOpenActionMenu(null); openModal("renew", cert); }}>
                                {Icons.refresh} <span>Renew Certificate</span>
                              </button>
                              <button type="button" className="flex w-full items-center gap-2.5 px-4 py-2 text-sm text-att-700 hover:bg-att-50" onClick={() => { setOpenActionMenu(null); openModal("load_to_akv", cert); }}>
                                {Icons.keyvault} <span>Load to AKV</span>
                              </button>
                              <div className="my-1 border-t border-att-100" />
                              <button type="button" className="flex w-full items-center gap-2.5 px-4 py-2 text-sm text-gray-700 hover:bg-att-50" onClick={() => { setOpenActionMenu(null); openModal("metadata", cert); }}>
                                {Icons.edit} <span>Edit Metadata</span>
                              </button>
                              <button type="button" className="flex w-full items-center gap-2.5 px-4 py-2 text-sm text-orange-700 hover:bg-orange-50" onClick={() => { setOpenActionMenu(null); openModal("revoke", cert); }}>
                                {Icons.slash} <span>Revoke</span>
                              </button>
                              <button type="button" className="flex w-full items-center gap-2.5 px-4 py-2 text-sm text-red-700 hover:bg-red-50" onClick={() => { setOpenActionMenu(null); openModal("delete", cert); }}>
                                {Icons.trash} <span>Delete</span>
                              </button>
                            </>}
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <TablePagination currentPage={page} totalItems={total} onPageChange={setPage} />
      </div>

      {/* Modals */}
      {modal === "enroll" && <EnrollCertificateModal onClose={closeModal} onSuccess={(m) => showToast(m, "success")} onError={(m) => showToast(m, "error")} />}
      {modal === "view" && selected && <CertificateDetailsModal certificate={selected} onClose={closeModal} />}
      {modal === "renew" && selected && <RenewCertificateModal certificate={selected} collectionId={collectionId} onClose={closeModal} onSuccess={(m) => showToast(m, "success")} onError={(m) => showToast(m, "error")} />}
      {modal === "metadata" && selected && <UpdateMetadataModal certificate={selected} onClose={closeModal} onSuccess={(m) => showToast(m, "success")} onError={(m) => showToast(m, "error")} />}
      {modal === "revoke" && selected && <RevokeCertificateModal certificate={selected} collectionId={collectionId} onClose={closeModal} onSuccess={(m) => showToast(m, "success")} onError={(m) => showToast(m, "error")} />}
      {modal === "delete" && selected && <DeleteCertificateModal certificate={selected} collectionId={collectionId} onClose={closeModal} onSuccess={(m) => showToast(m, "success")} onError={(m) => showToast(m, "error")} />}
      {modal === "download" && selected && <DownloadCertificateModal certificate={selected} collectionId={collectionId} canWrite={canWrite} onClose={closeModal} onSuccess={(m) => showToast(m, "success")} onError={(m) => showToast(m, "error")} />}
      {modal === "load_to_akv" && selected && <LoadToAkvModal certificate={selected} onClose={closeModal} onSuccess={(m) => showToast(m, "success")} onError={(m) => showToast(m, "error")} />}
      </>)}

      {activeTab === "auto-renewal" && <AutoRenewalPanel onToast={showToast} />}
      {activeTab === "alerts" && <AlertsPanel />}
      {activeTab === "audit" && <CertificateAuditHistoryPanel />}

      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
};

export default CertificatesPage;
