/**
 * Key Vault Management Page — Azure Key Vault discovery, secrets, keys, and certificates.
 *
 * KPI tiles filter the grids beneath them (state kept in the URL so a view can
 * be linked). Vault, secret, key, and certificate names open full drill-down
 * views like the AKS Deployment view. Secret values are only read on request
 * (write roles) and every read is audited server-side.
 * All icons are inline SVG vector icons (no emojis).
 */

import React, { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { useAuth } from "../contexts/AuthContext";
import Toast, { type ToastState } from "../components/Toast";
import { MetricCard } from "../components/MetricCard";
import { formatAxiosError } from "../services/apiErrors";
import { AutoRefreshIndicator, gridStyles, type SortState, nextSortState, SortableHeader } from "../components/gridStyles";
import { TileFilterNotice } from "../features/aks/aksGridShared";
import {
  useKeyVaultDashboard,
  useKeyVaults,
  useVaultSecrets,
  useSecretValueSearch,
  useVaultKeys,
  useVaultCertificates,
  useCreateSecret,
  useDeleteSecret,
  useKeyDetail,
  useCreateKey,
  useDeleteKey,
  useDeleteCertificate,
  useKeyVaultAuditHistory,
  useKeyVaultSyncStatus,
  useKeyVaultSync,
  useKeyVaultSyncVault,
  useExtendSecretExpiry,
  useBulkExtendSecretExpiry,
  useBulkValidateSecrets,
  useBulkParseSecretsFile,
  useBulkCreateSecrets,
  useCreateCertificate,
  BulkSecretItem,
  BulkSecretValidationResult,
  BulkSecretUploadResult,
  refreshVaultSecrets,
  refreshVaultKeys,
  refreshVaultCertificates,
  refreshKeyVaultDashboard,
  KeyVaultInfo,
  SecretInfo,
  SecretSearchResult,
  SecretSearchScope,
  SECRET_VALUE_SEARCH_MIN_CHARS,
  SECRET_VALUE_SEARCH_DEBOUNCE_MS,
  KeyInfo,
  CertificateInfo,
  ExpiringItem,
  VaultSummary,
  SecretValueResponse,
  KeyVaultAuditEntry,
  type KeyVaultItemType,
} from "../services/costApi";
import { usePortalTimezone } from "../contexts/TimezoneContext";
import {
  Badge,
  CERTIFICATE_SEARCH_FIELDS,
  type CertificateSearchField,
  certificateMatchFields,
  DaysLeftBadge,
  decodeBase64Utf8,
  fmtDate,
  fmtDateTime,
  Highlight,
  Icons,
  ItemTypeBadge,
  nameLinkClass,
  vaultNameFromUri,
} from "../features/keyvault/kvShared";
import {
  auditActionBadge,
  isReadAction,
  type ItemDetailTab,
  KeyVaultItemDetail,
} from "../features/keyvault/KeyVaultItemDetail";
import { VaultDetailModal } from "../features/keyvault/VaultDetailModal";

/** Opens a secret / key / certificate drill-down from inside a vault's grids. */
type OpenItem = (type: KeyVaultItemType, name: string, tab?: ItemDetailTab) => void;

const KV_PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

// ── Helpers ───────────────────────────────────────────────────────────

const gridSelectStyles =
  "rounded-lg border border-att-200 bg-white px-3 py-2 text-sm text-gray-700 shadow-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100";

function sortCollection<T>(
  items: T[],
  direction: "asc" | "desc",
  accessor: (item: T) => string | number | boolean | null | undefined,
) {
  const dir = direction === "asc" ? 1 : -1;
  return [...items].sort((left, right) => {
    const a = accessor(left);
    const b = accessor(right);

    if (a == null && b == null) return 0;
    if (a == null) return 1;
    if (b == null) return -1;

    const av = typeof a === "boolean" ? Number(a) : a;
    const bv = typeof b === "boolean" ? Number(b) : b;

    if (av < bv) return -dir;
    if (av > bv) return dir;
    return 0;
  });
}

const GridToolbar: React.FC<{
  search: string;
  onSearch: (value: string) => void;
  placeholder: string;
  countLabel: string;
  pageSize: number;
  onPageSizeChange: (value: number) => void;
  onRefresh?: () => void;
  refreshing?: boolean;
  primaryAction?: React.ReactNode;
  secondaryAction?: React.ReactNode;
  /** Extra filter controls rendered immediately left of the search box. */
  filters?: React.ReactNode;
}> = ({
  search,
  onSearch,
  placeholder,
  countLabel,
  pageSize,
  onPageSizeChange,
  onRefresh,
  refreshing = false,
  primaryAction,
  secondaryAction,
  filters,
}) => (
  <div className={gridStyles.panelHeader}>
    <div className="flex flex-wrap items-center gap-3">
      <span className={gridStyles.countBadge}>{countLabel}</span>
      <AutoRefreshIndicator />
    </div>
    <div className="ml-auto flex flex-wrap items-center justify-end gap-3">
      {filters}
      <input
        type="text"
        placeholder={placeholder}
        value={search}
        onChange={(e) => onSearch(e.target.value)}
        className={gridStyles.toolbarInput}
      />
      <select
        value={pageSize}
        onChange={(e) => onPageSizeChange(Number(e.target.value))}
        className={gridSelectStyles}
      >
        {KV_PAGE_SIZE_OPTIONS.map((n) => (
          <option key={n} value={n}>{n} / page</option>
        ))}
      </select>
      {onRefresh && (
        <button
          onClick={onRefresh}
          disabled={refreshing}
          className="inline-flex items-center gap-2 rounded-lg border border-att-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:border-att-300 hover:bg-att-50 disabled:opacity-50"
        >
          <span className={refreshing ? "animate-spin" : ""}>{Icons.refresh()}</span>
          {refreshing ? "Refreshing..." : "Refresh"}
        </button>
      )}
      {secondaryAction}
      {primaryAction}
    </div>
  </div>
);

const readFileAsBase64 = (file: File): Promise<string> =>
  new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      resolve(result.includes(",") ? result.split(",")[1] : result);
    };
    reader.onerror = () => reject(new Error("Failed to read file"));
    reader.readAsDataURL(file);
  });

const downloadBulkSecretTemplate = (format: "csv" | "json") => {
  const csv = "secret_name,secret_value,content_type,expires,tags\nexample-secret,example-value,text/plain,2027-06-10,\n";
  const json = JSON.stringify(
    { secrets: [{ name: "example-secret", value: "example-value", content_type: "text/plain" }] },
    null,
    2
  );
  const blob = new Blob([format === "csv" ? csv : json], { type: "text/plain" });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = format === "csv" ? "keyvault-bulk-secrets-template.csv" : "keyvault-bulk-secrets-template.json";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

const downloadFailureReport = (results: BulkSecretUploadResult["results"]) => {
  const failed = results.filter((r) => r.status === "failed");
  const lines = ["secret_name,error", ...failed.map((r) => `"${r.name}","${(r.error || "").replace(/"/g, '""')}"`)];
  const blob = new Blob([lines.join("\n")], { type: "text/csv" });
  const url = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `keyvault-bulk-failures-${new Date().toISOString().slice(0, 10)}.csv`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
};

const GridPagination: React.FC<{
  page: number;
  totalPages: number;
  totalItems: number;
  pageSize: number;
  onPageChange: (page: number) => void;
}> = ({ page, totalPages, totalItems, pageSize, onPageChange }) => {
  if (totalPages <= 1) return null;

  const start = totalItems === 0 ? 0 : (page - 1) * pageSize + 1;
  const end = Math.min(page * pageSize, totalItems);

  return (
    <div className={gridStyles.pager}>
      <span className="text-gray-600">Showing {start}-{end} of {totalItems}</span>
      <div className="flex items-center gap-2">
        <button onClick={() => onPageChange(1)} disabled={page <= 1} className={gridStyles.pagerButton}>&laquo;</button>
        <button onClick={() => onPageChange(Math.max(1, page - 1))} disabled={page <= 1} className={gridStyles.pagerButton}>Previous</button>
        <span className="text-gray-600">Page {page} of {totalPages}</span>
        <button onClick={() => onPageChange(Math.min(totalPages, page + 1))} disabled={page >= totalPages} className={gridStyles.pagerButton}>Next</button>
        <button onClick={() => onPageChange(totalPages)} disabled={page >= totalPages} className={gridStyles.pagerButton}>&raquo;</button>
      </div>
    </div>
  );
};

/**
 * Every Key Vault grid row is the same height whatever its cells hold — text,
 * badges, or action buttons: 49px = 1px row border + 20px cell padding + one
 * 28px GridIconButton. Plain text rows are padded up to it.
 */
const kvRow = `${gridStyles.row} h-[49px]`;

/** Row action button, 28px square with a 16px icon, so it fits a kvRow. */
const GridIconButton: React.FC<{
  title: string;
  onClick: (e: React.MouseEvent) => void;
  tone: "blue" | "red" | "gray" | "green" | "att";
  disabled?: boolean;
  /** Spins the icon (e.g. a sync in progress). */
  spinning?: boolean;
  children: React.ReactNode;
}> = ({ title, onClick, tone, disabled = false, spinning = false, children }) => {
  const tones: Record<string, string> = {
    blue: "text-blue-600 hover:bg-blue-50",
    red: "text-red-600 hover:bg-red-50",
    gray: "text-gray-600 hover:bg-gray-50",
    green: "text-green-600 hover:bg-green-50",
    att: "text-att-600 hover:bg-att-50",
  };

  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      aria-label={title}
      className={`inline-flex h-7 w-7 items-center justify-center rounded-lg disabled:opacity-50 [&>svg]:h-4 [&>svg]:w-4 ${spinning ? "[&>svg]:animate-spin" : ""} ${tones[tone]}`}
    >
      {children}
    </button>
  );
};

// ── Modal Overlay ─────────────────────────────────────────────────────

/** Dialog above everything else on the page, including the drill-down views (z-50). */
const Modal: React.FC<{
  title: string;
  onClose: () => void;
  wide?: boolean;
  children: React.ReactNode;
}> = ({ title, onClose, wide, children }) => {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label={title}
        className={`bg-white rounded-2xl shadow-2xl ${wide ? "w-[720px]" : "w-[520px]"} max-w-[95vw] max-h-[85vh] overflow-auto`}
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between p-5 border-b border-gray-100">
          <h2 className="text-lg font-semibold text-gray-800">{title}</h2>
          <button onClick={onClose} aria-label="Close" className="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
        </div>
        <div className="p-5">{children}</div>
      </div>
    </div>
  );
};

// ── Expired & Expiring Items ──────────────────────────────────────────

/** Which slice of the expiry list a grid shows. "attention" = expired or within 90 days. */
type ExpiryWindow = "attention" | "expired" | "30" | "90" | "360";

const EXPIRY_WINDOWS: { value: ExpiryWindow; label: string; count: string; empty: string }[] = [
  { value: "attention", label: "Expired or ≤ 90 days", count: "expired or expiring within 90 days", empty: "Nothing has expired or expires within 90 days" },
  { value: "expired", label: "Expired", count: "expired", empty: "Nothing enabled has expired" },
  { value: "30", label: "Expiring ≤ 30 days", count: "expiring within 30 days", empty: "Nothing expires within 30 days" },
  { value: "90", label: "Expiring ≤ 90 days", count: "expiring within 90 days", empty: "Nothing expires within 90 days" },
  { value: "360", label: "Expiring ≤ 360 days", count: "expiring within 360 days", empty: "Nothing expires within 360 days" },
];

const inExpiryWindow = (days: number, expiryWindow: ExpiryWindow) =>
  expiryWindow === "expired" ? days < 0
  : expiryWindow === "attention" ? days <= 90
  : days >= 0 && days <= Number(expiryWindow);

const expiringItemKey = (i: ExpiringItem) => `${i.vault_name}/${i.type}/${i.name}`;

const Spinner: React.FC<{ className?: string }> = ({ className = "w-4 h-4" }) => (
  <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none">
    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
  </svg>
);

const ExpiringItemsTable: React.FC<{
  /** Every expired and expiring (≤ 360 days) item in scope. */
  items: ExpiringItem[];
  /** Controlled by the page's tiles; omit to let the grid keep its own. */
  expiryWindow?: ExpiryWindow;
  defaultWindow?: ExpiryWindow;
  onWindowChange?: (window: ExpiryWindow) => void;
  onRefresh: () => void;
  refreshing: boolean;
  vaultUriByName: Record<string, string>;
  canWrite: boolean;
  onToast: (t: ToastState) => void;
  onOpenItem: (vaultName: string, type: KeyVaultItemType, name: string) => void;
  /** Vault names become links; omitted (and the column hidden) inside a vault's own view. */
  onOpenVault?: (vaultName: string) => void;
}> = ({
  items,
  expiryWindow: controlledWindow,
  defaultWindow = "90",
  onWindowChange,
  onRefresh,
  refreshing,
  vaultUriByName,
  canWrite,
  onToast,
  onOpenItem,
  onOpenVault,
}) => {
  const { timezone } = usePortalTimezone();
  const [ownWindow, setOwnWindow] = useState<ExpiryWindow>(defaultWindow);
  const expiryWindow = controlledWindow ?? ownWindow;
  const showVault = !!onOpenVault;
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [sort, setSort] = useState<SortState<"name" | "vault_name" | "type" | "expires" | "days_remaining">>({ key: "days_remaining", direction: "asc" });
  const [fixingKey, setFixingKey] = useState<string | null>(null);
  const [bulkFixing, setBulkFixing] = useState(false);
  const [confirmBulk, setConfirmBulk] = useState(false);
  // Fixed rows show "Updated" and leave the bulk count at once, before the dashboard re-syncs.
  const [fixedKeys, setFixedKeys] = useState<Set<string>>(new Set());

  const extendMutation = useExtendSecretExpiry();
  const bulkExtendMutation = useBulkExtendSecretExpiry();

  useEffect(() => setPage(1), [expiryWindow]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return items.filter(
      (item) =>
        inExpiryWindow(item.days_remaining, expiryWindow) &&
        (!q || [item.name, item.vault_name, item.type].some((v) => (v || "").toLowerCase().includes(q))),
    );
  }, [items, expiryWindow, search]);
  const sorted = useMemo(() => sortCollection(filtered, sort.direction, (item) => {
    switch (sort.key) {
      case "name": return item.name?.toLowerCase();
      case "vault_name": return item.vault_name?.toLowerCase();
      case "type": return item.type?.toLowerCase();
      case "expires": return item.expires || "";
      case "days_remaining": return item.days_remaining;
    }
  }), [filtered, sort]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const paginated = sorted.slice((safePage - 1) * pageSize, safePage * pageSize);

  const isFixable = (i: ExpiringItem) => i.type === "secret" && !!vaultUriByName[i.vault_name] && !fixedKeys.has(expiringItemKey(i));
  // Bulk fix acts on what the grid shows (window + search), never on hidden rows.
  const bulkTargets = filtered.filter(isFixable);
  const bulkVaults = Array.from(
    bulkTargets.reduce((m, i) => m.set(i.vault_name, (m.get(i.vault_name) ?? 0) + 1), new Map<string, number>()),
  ).sort((a, b) => b[1] - a[1]);
  const newExpiry = fmtDate(new Date(Date.now() + 360 * 86_400_000).toISOString(), timezone);

  const changeWindow = (next: ExpiryWindow) => {
    if (onWindowChange) onWindowChange(next);
    else setOwnWindow(next);
  };

  const handleFix = async (item: ExpiringItem) => {
    const vault_uri = vaultUriByName[item.vault_name];
    if (!vault_uri) {
      onToast({ type: "error", message: `Cannot find vault URI for ${item.vault_name}` });
      return;
    }
    const key = expiringItemKey(item);
    setFixingKey(key);
    try {
      await extendMutation.mutateAsync({ vault_uri, name: item.name });
      setFixedKeys((prev) => new Set(prev).add(key));
      onToast({ type: "success", message: `${item.name} now expires ${newExpiry} (today + 360 days)` });
      onRefresh();
    } catch (e: unknown) {
      onToast({ type: "error", message: `Failed to extend ${item.name}: ${formatAxiosError(e, (e as Error).message)}` });
    } finally {
      setFixingKey(null);
    }
  };

  const handleBulkFix = async () => {
    setConfirmBulk(false);
    if (!bulkTargets.length) return;
    setBulkFixing(true);
    try {
      const result = await bulkExtendMutation.mutateAsync(
        bulkTargets.map((i) => ({ vault_uri: vaultUriByName[i.vault_name], name: i.name })),
      );
      // Match results by vault and name: the same secret name is common across vaults.
      const byUri = new Map(bulkTargets.map((i) => [`${vaultUriByName[i.vault_name]}|${i.name}`, expiringItemKey(i)]));
      const fixed = result.results
        .filter((r) => r.status === "success")
        .map((r) => byUri.get(`${r.vault_uri}|${r.name}`))
        .filter((k): k is string => !!k);
      setFixedKeys((prev) => new Set([...prev, ...fixed]));
      if (result.failed_count > 0) {
        const firstError = result.results.find((r) => r.status === "failed");
        onToast({
          type: "error",
          message: `Bulk fix: ${result.success_count} succeeded, ${result.failed_count} failed${firstError ? ` (e.g. ${firstError.name}: ${firstError.error})` : ""}`,
        });
      } else {
        onToast({ type: "success", message: `${result.success_count} secret(s) now expire ${newExpiry} (today + 360 days)` });
      }
      onRefresh();
    } catch (e: unknown) {
      onToast({ type: "error", message: `Bulk fix failed: ${formatAxiosError(e, (e as Error).message)}` });
    } finally {
      setBulkFixing(false);
    }
  };

  const windowMeta = EXPIRY_WINDOWS.find((w) => w.value === expiryWindow) ?? EXPIRY_WINDOWS[0];
  const columns = 5 + (showVault ? 1 : 0) + (canWrite ? 1 : 0);

  return (
    <div className={gridStyles.shell}>
      <GridToolbar
        search={search}
        onSearch={(value) => { setSearch(value); setPage(1); }}
        placeholder="Search expiring items..."
        countLabel={`${filtered.length} ${windowMeta.count}`}
        pageSize={pageSize}
        onPageSizeChange={(value) => { setPageSize(value); setPage(1); }}
        onRefresh={onRefresh}
        refreshing={refreshing}
        filters={
          <select
            value={expiryWindow}
            onChange={(e) => changeWindow(e.target.value as ExpiryWindow)}
            className={gridSelectStyles}
            aria-label="Expiry window"
          >
            {EXPIRY_WINDOWS.map((w) => (
              <option key={w.value} value={w.value}>{w.label}</option>
            ))}
          </select>
        }
        primaryAction={canWrite && bulkTargets.length > 0 ? (
          <button
            onClick={() => setConfirmBulk(true)}
            disabled={bulkFixing}
            title="Set the expiry of every secret listed to today + 360 days"
            className="inline-flex items-center gap-1.5 rounded-xl bg-att-700 px-3 py-2 text-sm font-semibold text-white hover:bg-att-800 disabled:opacity-50"
          >
            {bulkFixing ? <Spinner /> : Icons.shield("h-4 w-4")}
            {bulkFixing ? "Fixing…" : `Bulk Fix ${bulkTargets.length} Secret${bulkTargets.length !== 1 ? "s" : ""} (+360d)`}
          </button>
        ) : undefined}
      />
      <div className="overflow-auto max-h-[500px]">
        <table className={gridStyles.table}>
          <thead className={gridStyles.stickyHead}>
            <tr>
              <th className={gridStyles.headerCell}><SortableHeader label="Name" active={sort.key === "name"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "name"))} /></th>
              {showVault && <th className={gridStyles.headerCell}><SortableHeader label="Vault" active={sort.key === "vault_name"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "vault_name"))} /></th>}
              <th className={gridStyles.headerCell}><SortableHeader label="Type" active={sort.key === "type"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "type"))} /></th>
              <th className={gridStyles.headerCell}>Status</th>
              <th className={gridStyles.headerCell}><SortableHeader label="Expires" active={sort.key === "expires"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "expires"))} /></th>
              <th className={gridStyles.headerCellCenter}><SortableHeader label="Days Left" active={sort.key === "days_remaining"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "days_remaining"))} align="center" /></th>
              {canWrite && <th className={gridStyles.headerCell}>Action</th>}
            </tr>
          </thead>
          <tbody>
            {paginated.map((item) => {
              const key = expiringItemKey(item);
              const fixed = fixedKeys.has(key);
              return (
                <tr key={key} className={kvRow}>
                  <td className={gridStyles.strongCell}>
                    <button
                      type="button"
                      onClick={() => onOpenItem(item.vault_name, item.type as KeyVaultItemType, item.name)}
                      className={nameLinkClass}
                      title={`Open ${item.type} details`}
                    >
                      {item.name}
                    </button>
                  </td>
                  {showVault && (
                    <td className={gridStyles.cell}>
                      <button type="button" onClick={() => onOpenVault?.(item.vault_name)} className={nameLinkClass} title="Open vault details">
                        {item.vault_name}
                      </button>
                    </td>
                  )}
                  <td className={gridStyles.cell}><ItemTypeBadge type={item.type} /></td>
                  <td className={gridStyles.cell}>
                    <Badge label={item.enabled ? "Enabled" : "Disabled"} color={item.enabled ? "green" : "gray"} />
                  </td>
                  <td className={`${gridStyles.cell} whitespace-nowrap`}>{fmtDate(item.expires, timezone)}</td>
                  <td className={gridStyles.centerCell}><DaysLeftBadge days={item.days_remaining} /></td>
                  {canWrite && (
                    <td className={gridStyles.cell}>
                      {fixed ? (
                        <span className="inline-flex items-center gap-1 text-xs font-medium text-green-700" title="Expiry set to today + 360 days; the grid updates after the next vault sync">
                          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" width={12} height={12}><path d="M20 6L9 17l-5-5" /></svg>
                          Updated
                        </span>
                      ) : isFixable(item) ? (
                        <button
                          onClick={() => handleFix(item)}
                          disabled={fixingKey === key || bulkFixing}
                          className="flex items-center gap-1 whitespace-nowrap rounded px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 hover:bg-green-200 disabled:opacity-50"
                          title="Write a new version with the same value, tags and status that expires today + 360 days"
                        >
                          {fixingKey === key && <Spinner className="w-3 h-3" />}
                          {fixingKey === key ? "Fixing…" : "Fix (+360d)"}
                        </button>
                      ) : null}
                    </td>
                  )}
                </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={columns} className="py-6 text-center text-sm text-slate-400">
                  {search ? `No items match “${search}”` : windowMeta.empty}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <GridPagination page={safePage} totalPages={totalPages} totalItems={filtered.length} pageSize={pageSize} onPageChange={setPage} />

      {confirmBulk && (
        <Modal title="Confirm bulk expiry fix" onClose={() => setConfirmBulk(false)}>
          <p className="text-sm text-gray-700">
            Set the expiry of <span className="font-semibold">{bulkTargets.length} secret{bulkTargets.length !== 1 ? "s" : ""}</span> in{" "}
            {bulkVaults.length} vault{bulkVaults.length !== 1 ? "s" : ""} to <span className="font-semibold">{newExpiry}</span> (today + 360 days)?
          </p>
          <p className="mt-2 text-xs text-gray-500">
            Each secret gets a new version with the same value, content type, tags and enabled state. Applications pinned to a specific version keep reading the old one.
          </p>
          <ul className="mt-3 max-h-40 overflow-auto rounded-lg border border-att-100 text-xs">
            {bulkVaults.map(([vault, count]) => (
              <li key={vault} className="flex justify-between border-t border-att-100 px-3 py-1.5 first:border-t-0">
                <span className="font-medium text-gray-700">{vault}</span>
                <span className="text-gray-500">{count} secret{count !== 1 ? "s" : ""}</span>
              </li>
            ))}
          </ul>
          <div className="mt-4 flex justify-end gap-2">
            <button onClick={() => setConfirmBulk(false)} className="px-4 py-2 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200">Cancel</button>
            <button onClick={() => void handleBulkFix()} className="px-4 py-2 text-sm text-white bg-att-700 rounded-lg hover:bg-att-800">
              Fix {bulkTargets.length} secret{bulkTargets.length !== 1 ? "s" : ""}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
};

// ── Vault Inventory ───────────────────────────────────────────────────

type VaultTypeFilter = "secrets" | "keys" | "certificates";

const VaultSummaryTable: React.FC<{
  vaults: VaultSummary[];
  onSelect: (name: string) => void;
  onOpenVault: (name: string) => void;
  selectedVault: string | null;
  /** Set by the Secrets / Keys / Certificates tiles: only vaults holding that type, most first. */
  typeFilter: VaultTypeFilter | null;
  onRefresh: () => void;
  refreshing: boolean;
  canWrite: boolean;
  onSyncVault?: (vaultName: string, vaultUri: string) => void;
  syncingVault?: string | null;
}> = ({ vaults, onSelect, onOpenVault, selectedVault, typeFilter, onRefresh, refreshing, canWrite, onSyncVault, syncingVault }) => {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [sort, setSort] = useState<SortState<"name" | "location" | "secrets_count" | "keys_count" | "certificates_count">>({ key: "name", direction: "asc" });

  // A type tile ranks vaults by that count; the headers can re-sort afterwards.
  useEffect(() => {
    setSort(typeFilter ? { key: `${typeFilter}_count`, direction: "desc" } : { key: "name", direction: "asc" });
    setPage(1);
  }, [typeFilter]);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return vaults.filter(
      (v) =>
        (!typeFilter || (v[`${typeFilter}_count`] ?? 0) > 0) &&
        (!q || (v.name || "").toLowerCase().includes(q) || (v.location || "").toLowerCase().includes(q)),
    );
  }, [vaults, search, typeFilter]);
  const sorted = useMemo(() => sortCollection(filtered, sort.direction, (vault) => {
    switch (sort.key) {
      case "name": return vault.name?.toLowerCase();
      case "location": return vault.location?.toLowerCase();
      case "secrets_count": return vault.secrets_count;
      case "keys_count": return vault.keys_count;
      case "certificates_count": return vault.certificates_count;
    }
  }), [filtered, sort]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const paginated = sorted.slice((safePage - 1) * pageSize, safePage * pageSize);

  return (
  <div className={gridStyles.shell}>
    <GridToolbar
      search={search}
      onSearch={(value) => { setSearch(value); setPage(1); }}
      placeholder="Search vaults..."
      countLabel={`${filtered.length} vaults`}
      pageSize={pageSize}
      onPageSizeChange={(value) => { setPageSize(value); setPage(1); }}
      onRefresh={onRefresh}
      refreshing={refreshing}
    />
    <div className="overflow-auto max-h-[500px]">
      <table className={gridStyles.table}>
        <thead className={gridStyles.stickyHead}>
          <tr>
            <th className={gridStyles.headerCell}><SortableHeader label="Vault" active={sort.key === "name"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "name"))} /></th>
            <th className={gridStyles.headerCell}><SortableHeader label="Location" active={sort.key === "location"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "location"))} /></th>
            <th className={gridStyles.headerCellCenter}><SortableHeader label="Secrets" active={sort.key === "secrets_count"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "secrets_count"))} align="center" /></th>
            <th className={gridStyles.headerCellCenter}><SortableHeader label="Keys" active={sort.key === "keys_count"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "keys_count"))} align="center" /></th>
            <th className={gridStyles.headerCellCenter}><SortableHeader label="Certs" active={sort.key === "certificates_count"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "certificates_count"))} align="center" /></th>
            <th className={gridStyles.headerCell}>Features</th>
            {canWrite && <th className={gridStyles.headerCellCenter}>Actions</th>}
          </tr>
        </thead>
        <tbody>
          {paginated.map((v) => (
            <tr
              key={v.name}
              onClick={() => onSelect(v.name)}
              title="Manage this vault's secrets, keys and certificates below"
              className={`${kvRow} cursor-pointer transition ${
                selectedVault === v.name ? gridStyles.selectedRow : ""
              }`}
            >
              <td className={gridStyles.strongCell}>
                <button
                  type="button"
                  onClick={(e) => { e.stopPropagation(); onOpenVault(v.name); }}
                  className={nameLinkClass}
                  title="Open vault details"
                >
                  {v.name}
                </button>
              </td>
              <td className={gridStyles.cell}>{v.location}</td>
              <td className={gridStyles.centerCell}><span className={`font-mono ${typeFilter === "secrets" ? "font-semibold text-att-700" : ""}`}>{v.secrets_count}</span></td>
              <td className={gridStyles.centerCell}><span className={`font-mono ${typeFilter === "keys" ? "font-semibold text-att-700" : ""}`}>{v.keys_count}</span></td>
              <td className={gridStyles.centerCell}><span className={`font-mono ${typeFilter === "certificates" ? "font-semibold text-att-700" : ""}`}>{v.certificates_count}</span></td>
              <td className={gridStyles.cell}>
                <div className="flex gap-1 flex-wrap">
                  {v.soft_delete && <Badge label="Soft Delete" color="green" />}
                  {v.purge_protection && <Badge label="Purge Protect" color="blue" />}
                  {v.rbac_enabled && <Badge label="RBAC" color="purple" />}
                </div>
              </td>
              {canWrite && (
                <td className={gridStyles.centerCell}>
                  <div className="flex justify-center gap-1">
                    <GridIconButton
                      onClick={(e) => { e.stopPropagation(); onSyncVault?.(v.name, v.vault_uri); }}
                      disabled={syncingVault === v.name}
                      spinning={syncingVault === v.name}
                      tone="att"
                      title={`Sync ${v.name} from Azure`}
                    >
                      {Icons.refresh()}
                    </GridIconButton>
                  </div>
                </td>
              )}
            </tr>
          ))}
          {filtered.length === 0 && (
            <tr>
              <td colSpan={canWrite ? 7 : 6} className="py-6 text-center text-sm text-slate-400">
                {search ? `No vaults match “${search}”` : typeFilter ? `No vaults hold ${typeFilter}` : "No vaults in the selected subscriptions"}
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
    <GridPagination page={safePage} totalPages={totalPages} totalItems={filtered.length} pageSize={pageSize} onPageChange={setPage} />
  </div>
  );
};

// ── Create / Update Secret Dialog ─────────────────────────────────────

// ── File → Base64 helpers ────────────────────────────────────────────────
const FILE_CONTENT_TYPES: Record<string, string> = {
  jks:  "application/x-java-keystore",
  pfx:  "application/x-pkcs12",
  p12:  "application/x-pkcs12",
  pem:  "application/x-pem-file",
  cer:  "application/x-x509-ca-cert",
  crt:  "application/x-x509-ca-cert",
  p7b:  "application/pkcs7-mime",
  p7c:  "application/pkcs7-mime",
  der:  "application/x-x509-ca-cert",
  json: "application/json",
  txt:  "text/plain",
};

function guessContentType(filename: string): string {
  const ext = filename.split(".").pop()?.toLowerCase() ?? "";
  return FILE_CONTENT_TYPES[ext] ?? "application/octet-stream";
}

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      // result is "data:<mime>;base64,<b64>" — we want only the b64 part
      const result = reader.result as string;
      resolve(result.split(",")[1] ?? "");
    };
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}
// ────────────────────────────────────────────────────────────────────────────

const SecretFormDialog: React.FC<{
  vaultUri: string;
  editSecret?: SecretInfo | null;
  existingValue?: SecretValueResponse | null;
  onClose: () => void;
  onSuccess: () => void;
}> = ({ vaultUri, editSecret, existingValue, onClose, onSuccess }) => {
  const createMutation = useCreateSecret();

  const [name, setName] = useState(editSecret?.name || "");
  const [value, setValue] = useState(existingValue?.value || "");
  const [contentType, setContentType] = useState(editSecret?.content_type || "");
  const [encodeBase64, setEncodeBase64] = useState(false);
  const [decodeInput, setDecodeInput] = useState(false);
  const [decodedPreview, setDecodedPreview] = useState<string | null>(null);
  const [keepOpen, setKeepOpen] = useState(false);
  const isEdit = !!editSecret;

  // File upload state
  const [valueSource, setValueSource] = useState<"manual" | "file">("manual");
  const [uploadedFile, setUploadedFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Date fields — default: today → today + 360 days
  const todayStr = new Date().toISOString().slice(0, 10);
  const defaultExpiry = new Date(Date.now() + 360 * 86400000).toISOString().slice(0, 10);
  const [notBefore, setNotBefore] = useState(todayStr);
  const [expiresDate, setExpiresDate] = useState(defaultExpiry);

  // Live Base64 decode preview
  const handleValueChange = useCallback((v: string) => {
    setValue(v);
    if (decodeInput) setDecodedPreview(decodeBase64Utf8(v));
  }, [decodeInput]);

  const toggleDecodeInput = useCallback(() => {
    setDecodeInput((prev) => {
      const next = !prev;
      if (next) {
        setDecodedPreview(decodeBase64Utf8(value));
      } else {
        setDecodedPreview(null);
      }
      return next;
    });
  }, [value]);

  // File processing
  const processFile = useCallback(async (file: File) => {
    setFileError(null);
    const MAX_MB = 5;
    if (file.size > MAX_MB * 1024 * 1024) {
      setFileError(`File exceeds ${MAX_MB} MB limit.`);
      return;
    }
    try {
      const b64 = await fileToBase64(file);
      setUploadedFile(file);
      setValue(b64);
      // Auto-fill content type only if user hasn't already set one
      setContentType((prev) => prev || guessContentType(file.name));
      // File content is already Base64 — no need to re-encode
      setEncodeBase64(false);
    } catch {
      setFileError("Failed to read file. Please try again.");
    }
  }, []);

  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) processFile(file);
    // Reset so same file can be re-selected
    e.target.value = "";
  }, [processFile]);

  const handleDrop = useCallback((e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) processFile(file);
  }, [processFile]);

  const clearFile = useCallback(() => {
    setUploadedFile(null);
    setValue("");
    setFileError(null);
    setContentType(editSecret?.content_type || "");
  }, [editSecret]);

  const resetForm = useCallback(() => {
    const today = new Date().toISOString().slice(0, 10);
    const expiry = new Date(Date.now() + 360 * 86400000).toISOString().slice(0, 10);
    setName("");
    setValue("");
    setContentType("");
    setEncodeBase64(false);
    setDecodeInput(false);
    setDecodedPreview(null);
    setNotBefore(today);
    setExpiresDate(expiry);
    setValueSource("manual");
    setUploadedFile(null);
    setFileError(null);
    createMutation.reset();
  }, [createMutation]);

  const handleSubmit = () => {
    if (!name.trim() || !value.trim()) return;
    createMutation.mutate(
      {
        vault_uri: vaultUri,
        name: name.trim(),
        value: value.trim(),
        content_type: contentType.trim() || undefined,
        // Every save is a new version, which keeps only the tags sent with it.
        tags: isEdit ? editSecret.tags : undefined,
        // File uploads are already Base64; manual input respects the checkbox
        encode_base64: valueSource === "file" ? false : encodeBase64,
        not_before: notBefore || undefined,
        expires: expiresDate || undefined,
      },
      {
        onSuccess: () => {
          onSuccess();
          if (!isEdit && keepOpen) {
            resetForm();
          } else {
            onClose();
          }
        },
      }
    );
  };

  return (
    <Modal title={isEdit ? `New Version: ${editSecret.name}` : "Create New Secret"} onClose={onClose}>
      <div className="space-y-4">
        {isEdit && (
          <p className="rounded-lg border border-att-100 bg-att-50/60 px-3 py-2 text-xs text-slate-600">
            Saving creates a new version of this secret; earlier versions stay available.
            {Object.keys(editSecret.tags || {}).length > 0 && ` Its ${Object.keys(editSecret.tags).length} tag(s) are carried over.`}
          </p>
        )}
        {/* Name */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Secret Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={isEdit}
            placeholder="my-secret-name"
            className={`w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${
              isEdit ? "bg-gray-100 cursor-not-allowed" : ""
            }`}
          />
          {!isEdit && <p className="text-xs text-gray-400 mt-1">Alphanumeric and hyphens only (1-127 chars)</p>}
        </div>

        {/* Value — source toggle */}
        <div>
          <div className="flex items-center justify-between mb-2">
            <label className="block text-sm font-medium text-gray-700">Secret Value</label>
            {/* Manual / Upload toggle */}
            <div className="flex rounded-md border border-gray-200 overflow-hidden text-xs">
              <button
                type="button"
                onClick={() => { setValueSource("manual"); clearFile(); }}
                className={`px-3 py-1 transition ${
                  valueSource === "manual"
                    ? "bg-blue-600 text-white"
                    : "bg-white text-gray-500 hover:bg-gray-50"
                }`}
              >
                Manual
              </button>
              <button
                type="button"
                onClick={() => setValueSource("file")}
                className={`px-3 py-1 transition border-l border-gray-200 ${
                  valueSource === "file"
                    ? "bg-blue-600 text-white"
                    : "bg-white text-gray-500 hover:bg-gray-50"
                }`}
              >
                Upload File
              </button>
            </div>
          </div>

          {valueSource === "manual" ? (
            <>
              {/* Manual textarea + decode toggle */}
              <div className="flex items-center justify-end mb-1">
                <button
                  type="button"
                  onClick={toggleDecodeInput}
                  className={`text-xs px-2 py-0.5 rounded border transition ${
                    decodeInput
                      ? "bg-blue-100 text-blue-700 border-blue-300"
                      : "bg-gray-50 text-gray-500 border-gray-200 hover:bg-gray-100"
                  }`}
                >
                  {decodeInput ? "Hide Base64 Decode" : "Preview Base64 Decode"}
                </button>
              </div>
              <textarea
                value={value}
                onChange={(e) => handleValueChange(e.target.value)}
                rows={4}
                placeholder={isEdit ? "Enter new value..." : "Enter secret value..."}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
              />
            </>
          ) : (
            /* ── File upload zone ── */
            <div>
              {!uploadedFile ? (
                <div
                  onDragOver={(e) => { e.preventDefault(); setIsDragOver(true); }}
                  onDragLeave={() => setIsDragOver(false)}
                  onDrop={handleDrop}
                  onClick={() => fileInputRef.current?.click()}
                  className={`flex flex-col items-center justify-center gap-2 border-2 border-dashed rounded-lg p-6 cursor-pointer transition ${
                    isDragOver
                      ? "border-blue-400 bg-blue-50"
                      : "border-gray-300 bg-gray-50 hover:border-blue-300 hover:bg-blue-50"
                  }`}
                >
                  <svg className="h-8 w-8 text-att-400" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="17 8 12 3 7 8" /><line x1="12" y1="3" x2="12" y2="15" /></svg>
                  <p className="text-sm font-medium text-gray-700">
                    Drop a file here, or <span className="text-blue-600 underline">browse</span>
                  </p>
                  <p className="text-xs text-gray-400">
                    JKS · PFX / P12 · PEM · CER / CRT · P7B · JSON · TXT · any binary (max 5 MB)
                  </p>
                  <p className="text-xs text-gray-400">
                    File is read and stored as a <strong>Base64</strong> secret value
                  </p>
                  <input
                    ref={fileInputRef}
                    type="file"
                    className="hidden"
                    onChange={handleFileInputChange}
                    accept=".jks,.pfx,.p12,.pem,.cer,.crt,.p7b,.p7c,.der,.json,.txt,*"
                  />
                </div>
              ) : (
                /* Uploaded file badge */
                <div className="flex items-start gap-3 border border-green-200 bg-green-50 rounded-lg p-3">
                  <svg className="mt-0.5 h-5 w-5 shrink-0 text-green-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" /></svg>
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-800 truncate">{uploadedFile.name}</p>
                    <p className="text-xs text-gray-500 mt-0.5">
                      {formatBytes(uploadedFile.size)} · detected type: <code className="bg-green-100 px-1 rounded">{guessContentType(uploadedFile.name)}</code>
                    </p>
                    <p className="text-xs text-gray-400 mt-1">
                      Base64 value ready · {value.length.toLocaleString()} characters
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={clearFile}
                    className="text-xs text-red-500 hover:text-red-700 whitespace-nowrap mt-0.5"
                  >
                    Remove
                  </button>
                </div>
              )}
              {fileError && (
                <p className="text-xs text-red-500 mt-1">{fileError}</p>
              )}
              {/* Read-only Base64 preview when file loaded */}
              {uploadedFile && value && (
                <div className="mt-2">
                  <label className="block text-xs font-medium text-gray-500 mb-1">Base64 Preview (first 200 chars)</label>
                  <p className="text-xs font-mono bg-gray-100 border border-gray-200 rounded px-2 py-1.5 break-all text-gray-600 select-all">
                    {value.slice(0, 200)}{value.length > 200 ? "…" : ""}
                  </p>
                </div>
              )}
            </div>
          )}
        </div>

        {/* Decoded preview (manual mode only) */}
        {valueSource === "manual" && decodeInput && decodedPreview !== null && (
          <div>
            <label className="block text-xs font-medium text-blue-600 mb-1">Base64 Decoded Preview</label>
            <textarea
              readOnly
              value={decodedPreview}
              rows={3}
              className="w-full px-3 py-2 border border-blue-200 rounded-lg text-xs font-mono bg-blue-50 resize-y focus:outline-none"
            />
          </div>
        )}
        {valueSource === "manual" && decodeInput && value && decodedPreview === null && (
          <p className="text-xs text-red-500">Not valid Base64 — cannot decode</p>
        )}

        {/* Encode Base64 option (manual mode only; file is always already Base64) */}
        {valueSource === "manual" && (
          <div className="flex items-center gap-2">
            <input
              type="checkbox"
              id="encode-b64"
              checked={encodeBase64}
              onChange={(e) => setEncodeBase64(e.target.checked)}
              className="accent-blue-600"
            />
            <label htmlFor="encode-b64" className="text-sm text-gray-700">
              Encode value as Base64 before saving
            </label>
          </div>
        )}
        {valueSource === "file" && (
          <p className="text-xs text-blue-600 bg-blue-50 border border-blue-200 rounded px-3 py-1.5">
            File content is already stored as Base64 — no additional encoding applied.
          </p>
        )}

        {/* Start & Expiry Dates */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Start Date (Not Before)</label>
            <input
              type="date"
              value={notBefore}
              onChange={(e) => setNotBefore(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Expiry Date</label>
            <input
              type="date"
              value={expiresDate}
              onChange={(e) => setExpiresDate(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        </div>
        <p className="text-xs text-gray-400 -mt-2">Default validity: 360 days from today</p>

        {/* Content Type */}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Content Type (optional)</label>
          <input
            type="text"
            value={contentType}
            onChange={(e) => setContentType(e.target.value)}
            placeholder="e.g. application/json, text/plain"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        {/* Error */}
        {createMutation.isError && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3">
            <p className="text-sm text-red-700">
              {formatAxiosError(createMutation.error, "Failed to save secret")}
            </p>
          </div>
        )}

        {/* Actions */}
        <div className="flex items-center justify-between gap-4 pt-2">
          {!isEdit && (
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="keep-open"
                checked={keepOpen}
                onChange={(e) => setKeepOpen(e.target.checked)}
                className="accent-blue-600"
              />
              <label htmlFor="keep-open" className="text-sm text-gray-700">
                Keep dialog open to add another secret
              </label>
            </div>
          )}
          <div className={`flex gap-2 ${isEdit ? "ml-auto" : ""}`}>
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 transition"
            >
              Cancel
            </button>
            <button
              onClick={handleSubmit}
              disabled={!name.trim() || !value.trim() || createMutation.isPending}
              className="px-4 py-2 text-sm text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
            >
              {createMutation.isPending ? "Saving..." : isEdit ? "Save New Version" : "Create Secret"}
            </button>
          </div>
        </div>
      </div>
    </Modal>
  );
};

// ── Certificate Upload Dialog ─────────────────────────────────────────

const CertificateFormDialog: React.FC<{
  vaultUri: string;
  onClose: () => void;
  onSuccess: () => void;
}> = ({ vaultUri, onClose, onSuccess }) => {
  const createMutation = useCreateCertificate();
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [tagsText, setTagsText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const todayStr = new Date().toISOString().slice(0, 10);
  const defaultExpiry = new Date(Date.now() + 360 * 86400000).toISOString().slice(0, 10);
  const [notBefore, setNotBefore] = useState(todayStr);
  const [expiresDate, setExpiresDate] = useState(defaultExpiry);

  const fileType = file?.name.split(".").pop()?.toLowerCase() || "";
  const acceptedTypes = ["pfx", "pem", "cer", "crt"];

  const parseTags = (): Record<string, string> => {
    const tags: Record<string, string> = {};
    tagsText.split(",").forEach((pair) => {
      const [k, v] = pair.split("=").map((s) => s.trim());
      if (k && v) tags[k] = v;
    });
    return tags;
  };

  const handleSubmit = async () => {
    if (!file || !name.trim()) return;
    if (!acceptedTypes.includes(fileType)) {
      setFileError("Unsupported file type. Use .pfx, .pem, .cer, or .crt");
      return;
    }
    if (fileType === "pfx" && !password.trim()) {
      setFileError("Password is required for PFX files");
      return;
    }
    setFileError(null);
    try {
      const certificate_base64 = await readFileAsBase64(file);
      createMutation.mutate(
        {
          vault_uri: vaultUri,
          name: name.trim(),
          certificate_base64,
          file_type: fileType,
          password: password.trim() || undefined,
          tags: parseTags(),
          not_before: notBefore || undefined,
          expires: expiresDate || undefined,
        },
        {
          onSuccess: () => {
            onSuccess();
            onClose();
          },
        }
      );
    } catch {
      setFileError("Failed to read certificate file");
    }
  };

  return (
    <Modal title="Add Certificate" onClose={onClose}>
      <div className="space-y-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Certificate Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="my-certificate"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <p className="text-xs text-gray-400 mt-1">Alphanumeric and hyphens only (1-127 chars)</p>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Certificate File</label>
          <input
            type="file"
            accept=".pfx,.pem,.cer,.crt"
            onChange={(e) => {
              setFile(e.target.files?.[0] || null);
              setFileError(null);
            }}
            className="w-full text-sm"
          />
          {file && <p className="text-xs text-gray-500 mt-1">{file.name} ({Math.round(file.size / 1024)} KB)</p>}
        </div>

        {fileType === "pfx" && (
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">PFX Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Not Before</label>
            <input type="date" value={notBefore} onChange={(e) => setNotBefore(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Expiry Date</label>
            <input type="date" value={expiresDate} onChange={(e) => setExpiresDate(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Tags (optional)</label>
          <input
            type="text"
            value={tagsText}
            onChange={(e) => setTagsText(e.target.value)}
            placeholder="env=prod,owner=team-a"
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>

        {(fileError || createMutation.isError) && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3">
            <p className="text-sm text-red-700">
              {fileError || (createMutation.error as any)?.response?.data?.detail || "Failed to import certificate"}
            </p>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 transition">Cancel</button>
          <button
            onClick={() => setConfirmOpen(true)}
            disabled={!name.trim() || !file || createMutation.isPending}
            className="px-4 py-2 text-sm text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
          >
            {createMutation.isPending ? "Uploading..." : "Review Upload"}
          </button>
        </div>
      </div>

      {confirmOpen && (
        <Modal title="Confirm Certificate Upload" onClose={() => setConfirmOpen(false)}>
          <p className="text-sm text-gray-600 mb-4">
            Import certificate <span className="font-mono font-semibold">{name}</span> into the selected vault?
          </p>
          <div className="flex justify-end gap-2">
            <button onClick={() => setConfirmOpen(false)} className="px-4 py-2 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200">Cancel</button>
            <button
              onClick={() => { setConfirmOpen(false); void handleSubmit(); }}
              disabled={createMutation.isPending}
              className="px-4 py-2 text-sm text-white bg-att-600 rounded-lg hover:bg-att-700 disabled:opacity-50"
            >
              {createMutation.isPending ? "Uploading..." : "Confirm Upload"}
            </button>
          </div>
        </Modal>
      )}
    </Modal>
  );
};

// ── Bulk Secret Upload Dialog ───────────────────────────────────────────

const BulkSecretUploadDialog: React.FC<{
  vaultUri: string;
  onClose: () => void;
  onSuccess: (summary: string) => void;
}> = ({ vaultUri, onClose, onSuccess }) => {
  const parseMutation = useBulkParseSecretsFile();
  const validateMutation = useBulkValidateSecrets();
  const uploadMutation = useBulkCreateSecrets();
  const [secrets, setSecrets] = useState<BulkSecretItem[]>([]);
  const [validation, setValidation] = useState<BulkSecretValidationResult | null>(null);
  const [uploadResult, setUploadResult] = useState<BulkSecretUploadResult | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [progress, setProgress] = useState(0);

  const handleFile = async (file: File) => {
    setValidation(null);
    setUploadResult(null);
    const parsed = await parseMutation.mutateAsync(file);
    setSecrets(parsed.secrets);
    const result = await validateMutation.mutateAsync({ vault_uri: vaultUri, secrets: parsed.secrets });
    setValidation(result);
  };

  const handleUpload = async () => {
    if (!validation?.valid || secrets.length === 0) return;
    setConfirmOpen(false);
    setProgress(10);
    try {
      const aggregated = await uploadMutation.mutateAsync({ vault_uri: vaultUri, secrets });
      setProgress(100);
      setUploadResult(aggregated);
      onSuccess(`Uploaded ${aggregated.success_count} of ${aggregated.total} secrets`);
    } catch {
      setProgress(0);
    }
  };

  const busy = parseMutation.isPending || validateMutation.isPending || uploadMutation.isPending;

  return (
    <Modal title="Bulk Secret Upload" onClose={onClose}>
      <div className="space-y-4">
        <div className="flex flex-wrap gap-2">
          <button type="button" onClick={() => downloadBulkSecretTemplate("csv")} className="px-3 py-1.5 text-xs rounded-lg border border-att-200 bg-white hover:bg-att-50">Download CSV Template</button>
          <button type="button" onClick={() => downloadBulkSecretTemplate("json")} className="px-3 py-1.5 text-xs rounded-lg border border-att-200 bg-white hover:bg-att-50">Download JSON Template</button>
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Upload File (CSV, JSON, or XLSX)</label>
          <input
            type="file"
            accept=".csv,.json,.xlsx"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleFile(file).catch(() => setValidation(null));
            }}
            className="w-full text-sm"
          />
        </div>

        {busy && (
          <div className="flex items-center gap-2 text-sm text-gray-600">
            <span className="animate-spin">{Icons.refresh()}</span>
            {uploadMutation.isPending ? `Uploading... ${progress}%` : "Validating..."}
          </div>
        )}

        {validation && (
          <div className={`rounded-lg border p-3 ${validation.valid ? "bg-green-50 border-green-200" : "bg-amber-50 border-amber-200"}`}>
            <p className="text-sm font-medium">{validation.valid ? "Validation passed" : "Validation failed"}</p>
            <p className="text-xs mt-1">{validation.valid_count} valid, {validation.invalid_count} invalid of {validation.total} rows</p>
            {!validation.valid && (
              <ul className="mt-2 max-h-32 overflow-auto text-xs text-amber-800 space-y-1">
                {validation.errors.slice(0, 20).map((err, idx) => (
                  <li key={idx}>Row {err.row} ({err.name}): {err.error}</li>
                ))}
              </ul>
            )}
          </div>
        )}

        {validation?.valid && secrets.length > 0 && !uploadResult && (
          <div className="overflow-auto max-h-40 border border-att-100 rounded-lg">
            <table className="w-full text-xs">
              <thead className="bg-att-50"><tr><th className="px-2 py-1 text-left">Name</th><th className="px-2 py-1 text-left">Content Type</th></tr></thead>
              <tbody>
                {secrets.slice(0, 10).map((s) => (
                  <tr key={s.name} className="border-t border-att-100"><td className="px-2 py-1 font-mono">{s.name}</td><td className="px-2 py-1">{s.content_type || "—"}</td></tr>
                ))}
              </tbody>
            </table>
            {secrets.length > 10 && <p className="text-xs text-gray-500 p-2">...and {secrets.length - 10} more</p>}
          </div>
        )}

        {uploadResult && (
          <div className="rounded-lg border border-att-100 p-3 bg-att-50/40">
            <p className="text-sm font-medium">Upload complete</p>
            <p className="text-xs text-gray-600 mt-1">
              {uploadResult.success_count} succeeded, {uploadResult.failed_count} failed (total {uploadResult.total})
            </p>
            {uploadResult.failed_count > 0 && (
              <button type="button" onClick={() => downloadFailureReport(uploadResult.results)} className="mt-2 px-3 py-1.5 text-xs rounded-lg bg-white border border-att-200 hover:bg-att-50">
                Download Failure Report
              </button>
            )}
          </div>
        )}

        {(parseMutation.isError || validateMutation.isError || uploadMutation.isError) && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700">
            {parseMutation.isError
              ? formatAxiosError(parseMutation.error, "Failed to parse file")
              : validateMutation.isError
                ? formatAxiosError(validateMutation.error, "Validation request failed")
                : formatAxiosError(uploadMutation.error, "Bulk upload failed")}
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 transition">Close</button>
          {!uploadResult && (
            <button
              onClick={() => setConfirmOpen(true)}
              disabled={!validation?.valid || secrets.length === 0 || busy}
              className="px-4 py-2 text-sm text-white bg-att-600 rounded-lg hover:bg-att-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
            >
              Upload {secrets.length > 0 ? `${secrets.length} Secrets` : ""}
            </button>
          )}
        </div>
      </div>

      {confirmOpen && (
        <Modal title="Confirm Bulk Upload" onClose={() => setConfirmOpen(false)}>
          <p className="text-sm text-gray-600 mb-4">Upload {secrets.length} secrets to this vault?</p>
          <div className="flex justify-end gap-2">
            <button onClick={() => setConfirmOpen(false)} className="px-4 py-2 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200">Cancel</button>
            <button onClick={() => void handleUpload()} className="px-4 py-2 text-sm text-white bg-att-600 rounded-lg hover:bg-att-700">Confirm</button>
          </div>
        </Modal>
      )}
    </Modal>
  );
};

// ── Secrets Tab ───────────────────────────────────────────────────────

/**
 * Warning strip for value search. Deliberately silent unless the user has to
 * act: the search failed, or the app can list the vault but not read it. Any
 * result that is merely incomplete stays quiet — the grid already shows it.
 */
const ValueSearchStatus: React.FC<{
  vaultName: string;
  result?: SecretSearchResult;
  error: unknown;
}> = ({ vaultName, result, error }) => {
  const base = "flex items-center gap-2 border-b px-4 py-2 text-xs";

  if (error) {
    // A FastAPI `detail` already explains itself; only network-level failures
    // (timeout, proxy, DNS) need the vault name wrapped around them.
    const detail = formatAxiosError(error, "");
    return (
      <div className={`${base} border-red-200 bg-red-50 text-red-700`}>
        {detail || (
          <>
            Could not search secret values in{" "}
            <span className="font-semibold">{vaultName}</span> —{" "}
            {(error as { message?: string })?.message || "unknown error"}
          </>
        )}
      </div>
    );
  }

  if (!result || result.scope !== "name_and_value") return null;

  // Nothing readable is a permission problem, not an empty search result.
  if (result.scanned > 0 && result.unreadable === result.scanned) {
    return (
      <div className={`${base} border-red-200 bg-red-50 text-red-700`}>
        <span>
          None of the {result.scanned} secret values in{" "}
          <span className="font-semibold">{vaultName}</span> could be read, so values were
          not searched. The app can list this vault but not open its secrets — it needs{" "}
          <strong>Get</strong> on secrets (Key Vault Secrets User), not just List.
          {result.read_error ? ` Azure said: ${result.read_error}` : ""}
        </span>
      </div>
    );
  }

  return null;
};

const SecretsTab: React.FC<{ vaultUri: string | null; onOpenItem: OpenItem }> = ({ vaultUri, onOpenItem }) => {
  const { timezone } = usePortalTimezone();
  const { canWrite } = useAuth();
  const fmt = (iso: string | null) => fmtDate(iso, timezone);
  const { data: secrets, isLoading, isError, error } = useVaultSecrets(vaultUri);
  const queryClient = useQueryClient();
  const deleteMutation = useDeleteSecret();
  const [search, setSearch] = useState("");
  const [searchScope, setSearchScope] = useState<SecretSearchScope>("name");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [editingSecret, setEditingSecret] = useState<SecretInfo | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [showBulkUpload, setShowBulkUpload] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [sort, setSort] = useState<SortState<"name" | "content_type" | "enabled" | "updated" | "not_before" | "expires">>({ key: "name", direction: "asc" });
  const [toast, setToast] = useState<ToastState | null>(null);
  const showToast = useCallback((message: string, type: ToastState["type"] = "success") => setToast({ message, type }), []);

  // Value search hits every secret in the vault, so it waits for typing to settle.
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), SECRET_VALUE_SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [search]);

  const term = search.trim();
  // Reading values needs the same role as viewing a single secret.
  const valueSearch = useSecretValueSearch(vaultUri, debouncedSearch, searchScope === "name_and_value" && canWrite);
  const valueSearchActive =
    searchScope === "name_and_value" && canWrite && term.length >= SECRET_VALUE_SEARCH_MIN_CHARS;
  const valueSearchPending = valueSearchActive && (valueSearch.isFetching || debouncedSearch.trim() !== term);

  const filtered = useMemo<SecretInfo[]>(() => {
    const all = secrets || [];
    if (!term) return all;
    // While a newer term is in flight the previous result stays on screen;
    // a failed scan shows nothing rather than stale matches under an error.
    if (valueSearchActive) return valueSearch.isError ? [] : valueSearch.data?.results ?? [];
    return all.filter((s: SecretInfo) => s.name.toLowerCase().includes(term.toLowerCase()));
  }, [secrets, term, valueSearchActive, valueSearch.data, valueSearch.isError]);

  // name -> how the value matched, so the grid can flag Base64-stored hits.
  const valueMatches = useMemo(
    () =>
      new Map(
        (valueSearch.data?.results ?? [])
          .map((r) => [r.name, r.matched_in.find((m) => m.startsWith("value"))] as const)
          .filter(([, kind]) => kind !== undefined)
      ),
    [valueSearch.data]
  );
  const sorted = useMemo(() => sortCollection(filtered, sort.direction, (secret) => {
    switch (sort.key) {
      case "name": return secret.name?.toLowerCase();
      case "content_type": return secret.content_type?.toLowerCase() || "";
      case "enabled": return secret.enabled ? 1 : 0;
      case "updated": return secret.updated || "";
      case "not_before": return secret.not_before || "";
      case "expires": return secret.expires || "";
    }
  }), [filtered, sort]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const paginated = sorted.slice((safePage - 1) * pageSize, safePage * pageSize);

  if (!vaultUri)
    return <p className="text-gray-500 text-sm py-4">Select a vault to view secrets</p>;
  if (isLoading)
    return <p className="text-gray-500 text-sm py-4">Loading secrets...</p>;
  if (isError) {
    const status = (error as any)?.response?.status;
    const detail = (error as any)?.response?.data?.detail || "Check vault access permissions or network settings.";
    const is403 = status === 403 || /access denied|forbidden|unauthorized/i.test(detail);

    return (
      <div className={`rounded-lg border p-4 my-2 ${is403 ? "bg-amber-50 border-amber-300" : "bg-red-50 border-red-300"}`}>
        <div className="flex items-center gap-2 mb-1">
          <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
            <path d="M10 2L18 17H2L10 2Z" stroke={is403 ? "#d97706" : "#dc2626"} strokeWidth="1.5" fill={is403 ? "#fef3c7" : "#fee2e2"}/>
            <text x="10" y="14" textAnchor="middle" fontSize="10" fontWeight="bold" fill={is403 ? "#d97706" : "#dc2626"}>!</text>
          </svg>
          <span className={`font-semibold text-sm ${is403 ? "text-amber-700" : "text-red-700"}`}>
            {is403 ? "Access Denied" : "Failed to load secrets"}
          </span>
        </div>
        <p className={`text-sm ${is403 ? "text-amber-600" : "text-red-600"}`}>{detail}</p>
        {is403 && (
          <p className="text-xs text-amber-500 mt-2">
            The service principal needs <strong>Key Vault Secrets Officer</strong> RBAC role or <strong>Get, List</strong> secret access policies on this vault.
          </p>
        )}
        <button
          onClick={async () => {
            setRefreshing(true);
            try {
              const fresh = await refreshVaultSecrets(vaultUri!);
              queryClient.setQueryData(["keyvault", "secrets", vaultUri], fresh);
            } catch { /* ignore */ }
            setRefreshing(false);
          }}
          className="mt-3 px-3 py-1 text-xs font-medium rounded bg-white border border-gray-300 hover:bg-gray-50 flex items-center gap-1"
          disabled={refreshing}
        >
          <span className={refreshing ? "animate-spin" : ""}>{Icons.refresh()}</span>
          {refreshing ? "Retrying\u2026" : "Retry"}
        </button>
      </div>
    );
  }

  const handleRefresh = async () => {
    if (!vaultUri) return;
    setRefreshing(true);
    try {
      const freshData = await refreshVaultSecrets(vaultUri);
      queryClient.setQueryData(["keyvault", "secrets", vaultUri], freshData);
    } catch { /* ignore */ }
    setRefreshing(false);
  };

  const handleDelete = (name: string) => {
    deleteMutation.mutate(
      { vaultUri: vaultUri!, name },
      {
        onSuccess: () => {
          showToast("Secret deleted successfully");
          setConfirmDelete(null);
        },
        onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to delete secret", "error"),
      }
    );
  };

  return (
    <div className={gridStyles.shell}>
      <GridToolbar
        search={search}
        onSearch={(value) => { setSearch(value); setPage(1); }}
        placeholder={searchScope === "name_and_value" ? "Search names and values..." : "Search secrets..."}
        countLabel={
          // A scan in progress has no count yet — "0 secrets" would read as a result.
          valueSearchPending && !valueSearch.data
            ? "Searching…"
            : valueSearchActive && valueSearch.data
              ? `${filtered.length} of ${valueSearch.data.total_secrets} secrets`
              : `${filtered.length} secrets`
        }
        filters={canWrite ? (
          <select
            value={searchScope}
            onChange={(e) => { setSearchScope(e.target.value as SecretSearchScope); setPage(1); }}
            className={gridSelectStyles}
            title="Choose which fields the search term is matched against"
            aria-label="Secret search scope"
          >
            <option value="name">Search: Name</option>
            <option value="name_and_value">Search: Name + Value</option>
          </select>
        ) : undefined}
        pageSize={pageSize}
        onPageSizeChange={(value) => { setPageSize(value); setPage(1); }}
        onRefresh={handleRefresh}
        refreshing={refreshing}
        secondaryAction={canWrite ? (
          <button
            onClick={() => setShowBulkUpload(true)}
            className="inline-flex items-center gap-2 rounded-xl border border-att-300 bg-white px-3 py-2 text-sm font-semibold text-att-700 transition hover:bg-att-50"
          >
            Bulk Upload
          </button>
        ) : undefined}
        primaryAction={canWrite ? (
          <button
            onClick={() => { setShowCreate(true); setEditingSecret(null); }}
            className="inline-flex items-center gap-2 rounded-xl bg-att-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-att-700"
          >
            {Icons.plus()} Add Secret
          </button>
        ) : undefined}
      />

      {valueSearchActive && !valueSearchPending && (
        <ValueSearchStatus
          vaultName={vaultNameFromUri(vaultUri)}
          result={valueSearch.data}
          error={valueSearch.error}
        />
      )}

      <div className="overflow-auto max-h-[500px]">
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              <th className={gridStyles.headerCell}><SortableHeader label="Name" active={sort.key === "name"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "name"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Content Type" active={sort.key === "content_type"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "content_type"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Status" active={sort.key === "enabled"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "enabled"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Updated" active={sort.key === "updated"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "updated"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Not Before" active={sort.key === "not_before"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "not_before"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Expires" active={sort.key === "expires"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "expires"))} /></th>
              <th className={gridStyles.headerCellCenter}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginated.map((s: SecretInfo) => (
              <tr key={s.name} className={kvRow}>
                <td className={`${gridStyles.strongCell} font-mono text-xs`}>
                  <span className="inline-flex items-center gap-2">
                    <button type="button" onClick={() => onOpenItem("secret", s.name)} className={nameLinkClass} title="Open secret details">
                      <Highlight text={s.name} term={term} />
                    </button>
                    {s.managed && <Badge label="certificate" color="purple" title="Backs a certificate of the same name" />}
                    {valueSearchActive && valueMatches.has(s.name) && (
                      valueMatches.get(s.name) === "value_base64" ? (
                        <span title="The search term appears in this secret's value once it is Base64-decoded">
                          <Badge label="base64 match" color="blue" />
                        </span>
                      ) : (
                        <span title="The search term appears in this secret's value">
                          <Badge label="value match" color="purple" />
                        </span>
                      )
                    )}
                  </span>
                </td>
                <td className={`${gridStyles.cell} text-xs`}>{s.content_type || "—"}</td>
                <td className={gridStyles.cell}>
                  <Badge label={s.enabled ? "Enabled" : "Disabled"} color={s.enabled ? "green" : "red"} />
                </td>
                <td className={`${gridStyles.cell} text-xs`}>{fmt(s.updated)}</td>
                <td className={`${gridStyles.cell} text-xs`}>{fmt(s.not_before)}</td>
                <td className={`${gridStyles.cell} text-xs`}>{fmt(s.expires)}</td>
                <td className={gridStyles.centerCell}>
                  <div className="flex justify-center gap-1">
                    {/* Reading a secret's value requires write, like the API (GET /keyvault/secrets/{name}). */}
                    <GridIconButton onClick={() => onOpenItem("secret", s.name, canWrite ? "value" : "overview")} title={canWrite ? "View secret value" : "View secret details"} tone="blue">{Icons.eye()}</GridIconButton>
                    {/* A certificate's backing secret cannot be written or deleted directly. */}
                    {canWrite && !s.managed && <GridIconButton onClick={() => setEditingSecret(s)} title="New secret version" tone="blue">{Icons.edit()}</GridIconButton>}
                    {canWrite && !s.managed && <GridIconButton onClick={() => setConfirmDelete(s.name)} title="Delete secret" tone="red">{Icons.trash()}</GridIconButton>}
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={7} className="py-6 text-center text-sm text-slate-400">
                  {valueSearchPending ? "Searching secret values…" : "No secrets found"}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <GridPagination page={safePage} totalPages={totalPages} totalItems={filtered.length} pageSize={pageSize} onPageChange={setPage} />

      {/* Create Secret Modal */}
      {showCreate && vaultUri && (
        <SecretFormDialog
          vaultUri={vaultUri}
          onClose={() => setShowCreate(false)}
          onSuccess={() => showToast("Secret created successfully")}
        />
      )}

      {showBulkUpload && vaultUri && (
        <BulkSecretUploadDialog
          vaultUri={vaultUri}
          onClose={() => setShowBulkUpload(false)}
          onSuccess={(summary) => showToast(summary, "success")}
        />
      )}

      {/* Edit Secret Modal */}
      {editingSecret && vaultUri && (
        <SecretFormDialog
          vaultUri={vaultUri}
          editSecret={editingSecret}
          onClose={() => setEditingSecret(null)}
          onSuccess={() => showToast("Secret updated successfully")}
        />
      )}

      {/* Delete Confirmation */}
      {confirmDelete && (
        <Modal title="Confirm Delete" onClose={() => setConfirmDelete(null)}>
          <p className="text-sm text-gray-700 mb-4">
            Are you sure you want to delete secret <span className="font-mono font-bold">{confirmDelete}</span>?
            This will soft-delete the secret in Azure Key Vault.
          </p>
          {deleteMutation.isError && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-4">
              <p className="text-sm text-red-700">
                {(deleteMutation.error as any)?.response?.data?.detail || "Failed to delete secret"}
              </p>
            </div>
          )}
          <div className="flex justify-end gap-2">
            <button
              onClick={() => setConfirmDelete(null)}
              className="px-4 py-2 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 transition"
            >
              Cancel
            </button>
            <button
              onClick={() => handleDelete(confirmDelete)}
              disabled={deleteMutation.isPending}
              className="px-4 py-2 text-sm text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-50 transition"
            >
              {deleteMutation.isPending ? "Deleting..." : "Delete Secret"}
            </button>
          </div>
        </Modal>
      )}
      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
};

// ── Create / Update Key Dialog ────────────────────────────────────────

const KeyFormDialog: React.FC<{
  vaultUri: string;
  editKey?: KeyInfo | null;
  onClose: () => void;
  onSuccess: () => void;
}> = ({ vaultUri, editKey, onClose, onSuccess }) => {
  const createMutation = useCreateKey();

  const [name, setName] = useState(editKey?.name || "");
  const [kty, setKty] = useState("RSA");
  const [keySize, setKeySize] = useState("2048");
  const [crv, setCrv] = useState("P-256");
  const isEdit = !!editKey;
  // A new version is created from what is sent, so start from the current
  // version's type, size, curve and operations rather than the create defaults.
  const { data: current, isLoading: loadingCurrent } = useKeyDetail(isEdit ? vaultUri : null, editKey?.name ?? null);
  const prefilled = useRef(false);
  useEffect(() => {
    if (!current || prefilled.current) return;
    prefilled.current = true;
    if (current.kty) setKty(current.kty);
    if (current.key_size) setKeySize(String(current.key_size));
    if (current.crv) setCrv(current.crv);
    if (current.key_ops?.length) setKeyOps(current.key_ops);
  }, [current]);

  const todayStr = new Date().toISOString().slice(0, 10);
  const defaultExpiry = new Date(Date.now() + 360 * 86400000).toISOString().slice(0, 10);
  const [notBefore, setNotBefore] = useState(todayStr);
  const [expiresDate, setExpiresDate] = useState(defaultExpiry);

  const [keyOps, setKeyOps] = useState<string[]>(["encrypt", "decrypt", "sign", "verify", "wrapKey", "unwrapKey"]);

  const toggleOp = useCallback((op: string) => {
    setKeyOps((prev) => prev.includes(op) ? prev.filter((o) => o !== op) : [...prev, op]);
  }, []);

  const handleSubmit = () => {
    if (!name.trim()) return;
    createMutation.mutate(
      {
        vault_uri: vaultUri,
        name: name.trim(),
        kty,
        key_size: kty.startsWith("RSA") ? parseInt(keySize) : undefined,
        crv: kty.startsWith("EC") ? crv : undefined,
        key_ops: keyOps.length > 0 ? keyOps : undefined,
        // Every save is a new version, which keeps only the tags sent with it.
        tags: isEdit ? editKey.tags : undefined,
        not_before: notBefore || undefined,
        expires: expiresDate || undefined,
      },
      {
        onSuccess: () => {
          onSuccess();
          onClose();
        },
      }
    );
  };

  return (
    <Modal title={isEdit ? `New Version: ${editKey.name}` : "Create New Key"} onClose={onClose}>
      <div className="space-y-4">
        {isEdit && (
          <p className="rounded-lg border border-att-100 bg-att-50/60 px-3 py-2 text-xs text-slate-600">
            {loadingCurrent
              ? "Reading the current version…"
              : "Saving creates a new version (a key rotation) with these settings; earlier versions stay available for decrypt and verify."}
          </p>
        )}
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Key Name</label>
          <input
            type="text"
            value={name}
            onChange={(e) => setName(e.target.value)}
            disabled={isEdit}
            placeholder="my-key-name"
            className={`w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 ${isEdit ? "bg-gray-100 cursor-not-allowed" : ""}`}
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Key Type</label>
            <select value={kty} onChange={(e) => setKty(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              <option value="RSA">RSA</option>
              <option value="RSA-HSM">RSA-HSM</option>
              <option value="EC">EC</option>
              <option value="EC-HSM">EC-HSM</option>
              <option value="oct">oct (Symmetric)</option>
              <option value="oct-HSM">oct-HSM</option>
            </select>
          </div>
          {kty.startsWith("EC") && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Curve</label>
              <select value={crv} onChange={(e) => setCrv(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="P-256">P-256</option>
                <option value="P-384">P-384</option>
                <option value="P-521">P-521</option>
                <option value="P-256K">P-256K</option>
              </select>
            </div>
          )}
          {kty.startsWith("RSA") && (
            <div>
              <label className="block text-sm font-medium text-gray-700 mb-1">Key Size</label>
              <select value={keySize} onChange={(e) => setKeySize(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
                <option value="2048">2048</option>
                <option value="3072">3072</option>
                <option value="4096">4096</option>
              </select>
            </div>
          )}
        </div>

        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1">Permitted Operations</label>
          <div className="flex gap-2 flex-wrap">
            {["encrypt", "decrypt", "sign", "verify", "wrapKey", "unwrapKey"].map((op) => (
              <label key={op} className="flex items-center gap-1 text-xs cursor-pointer">
                <input type="checkbox" checked={keyOps.includes(op)} onChange={() => toggleOp(op)} className="accent-blue-600" />
                {op}
              </label>
            ))}
          </div>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Start Date (Not Before)</label>
            <input type="date" value={notBefore} onChange={(e) => setNotBefore(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Expiry Date</label>
            <input type="date" value={expiresDate} onChange={(e) => setExpiresDate(e.target.value)} className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
        </div>
        <p className="text-xs text-gray-400 -mt-2">Default validity: 360 days from today</p>

        {createMutation.isError && (
          <div className="bg-red-50 border border-red-200 rounded-lg p-3">
            <p className="text-sm text-red-700">{formatAxiosError(createMutation.error, "Failed to save key")}</p>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 transition">Cancel</button>
          <button
            onClick={handleSubmit}
            disabled={!name.trim() || createMutation.isPending || (isEdit && loadingCurrent)}
            className="px-4 py-2 text-sm text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
          >
            {createMutation.isPending ? "Saving..." : isEdit ? "Save New Version" : "Create Key"}
          </button>
        </div>
      </div>
    </Modal>
  );
};

// ── Keys Tab ──────────────────────────────────────────────────────────

const KeysTab: React.FC<{ vaultUri: string | null; onOpenItem: OpenItem }> = ({ vaultUri, onOpenItem }) => {
  const { timezone } = usePortalTimezone();
  const { canWrite } = useAuth();
  const fmt = (iso: string | null) => fmtDate(iso, timezone);
  const queryClient = useQueryClient();
  const { data: keys, isLoading, isError, error } = useVaultKeys(vaultUri);
  const deleteMutation = useDeleteKey();
  const [search, setSearch] = useState("");
  const [editingKey, setEditingKey] = useState<KeyInfo | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [sort, setSort] = useState<SortState<"name" | "enabled" | "updated" | "not_before" | "expires" | "managed">>({ key: "name", direction: "asc" });
  const [toast, setToast] = useState<ToastState | null>(null);
  const showToast = useCallback((message: string, type: ToastState["type"] = "success") => setToast({ message, type }), []);
  const filtered = (keys || []).filter(
    (k: KeyInfo) => !search || k.name.toLowerCase().includes(search.toLowerCase())
  );
  const sorted = useMemo(() => sortCollection(filtered, sort.direction, (key) => {
    switch (sort.key) {
      case "name": return key.name?.toLowerCase();
      case "enabled": return key.enabled ? 1 : 0;
      case "updated": return key.updated || "";
      case "not_before": return key.not_before || "";
      case "expires": return key.expires || "";
      case "managed": return key.managed ? 1 : 0;
    }
  }), [filtered, sort]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const paginated = sorted.slice((safePage - 1) * pageSize, safePage * pageSize);

  if (!vaultUri)
    return <p className="text-gray-500 text-sm py-4">Select a vault to view keys</p>;
  if (isLoading)
    return <p className="text-gray-500 text-sm py-4">Loading keys...</p>;
  if (isError) {
    const status = (error as any)?.response?.status;
    const detail = (error as any)?.response?.data?.detail || "Check vault access permissions or network settings.";
    const is403 = status === 403 || /access denied|forbidden|unauthorized/i.test(detail);

    return (
      <div className={`rounded-lg border p-4 my-2 ${is403 ? "bg-amber-50 border-amber-300" : "bg-red-50 border-red-300"}`}>
        <div className="flex items-center gap-2 mb-1">
          <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
            <path d="M10 2L18 17H2L10 2Z" stroke={is403 ? "#d97706" : "#dc2626"} strokeWidth="1.5" fill={is403 ? "#fef3c7" : "#fee2e2"}/>
            <text x="10" y="14" textAnchor="middle" fontSize="10" fontWeight="bold" fill={is403 ? "#d97706" : "#dc2626"}>!</text>
          </svg>
          <span className={`font-semibold text-sm ${is403 ? "text-amber-700" : "text-red-700"}`}>
            {is403 ? "Access Denied" : "Failed to load keys"}
          </span>
        </div>
        <p className={`text-sm ${is403 ? "text-amber-600" : "text-red-600"}`}>{detail}</p>
        {is403 && (
          <p className="text-xs text-amber-500 mt-2">
            The service principal needs <strong>Key Vault Crypto Officer</strong> RBAC role or <strong>Get, List</strong> key access policies on this vault.
          </p>
        )}
        <button
          onClick={async () => {
            setRefreshing(true);
            try {
              const fresh = await refreshVaultKeys(vaultUri!);
              queryClient.setQueryData(["keyvault", "keys", vaultUri], fresh);
            } catch { /* ignore */ }
            setRefreshing(false);
          }}
          className="mt-3 px-3 py-1 text-xs font-medium rounded bg-white border border-gray-300 hover:bg-gray-50 flex items-center gap-1"
          disabled={refreshing}
        >
          <span className={refreshing ? "animate-spin" : ""}>{Icons.refresh()}</span>
          {refreshing ? "Retrying\u2026" : "Retry"}
        </button>
      </div>
    );
  }

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const fresh = await refreshVaultKeys(vaultUri!);
      queryClient.setQueryData(["keyvault", "keys", vaultUri], fresh);
    } catch { /* ignore */ }
    setRefreshing(false);
  };

  const handleDelete = (name: string) => {
    deleteMutation.mutate(
      { vaultUri: vaultUri!, name },
      {
        onSuccess: () => {
          showToast("Key deleted successfully");
          setConfirmDelete(null);
        },
        onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to delete key", "error"),
      }
    );
  };

  return (
    <div className={gridStyles.shell}>
      <GridToolbar
        search={search}
        onSearch={(value) => { setSearch(value); setPage(1); }}
        placeholder="Search keys..."
        countLabel={`${filtered.length} keys`}
        pageSize={pageSize}
        onPageSizeChange={(value) => { setPageSize(value); setPage(1); }}
        onRefresh={handleRefresh}
        refreshing={refreshing}
        primaryAction={canWrite ?
          <button
            onClick={() => { setShowCreate(true); setEditingKey(null); }}
            className="inline-flex items-center gap-2 rounded-xl bg-att-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-att-700"
          >
            {Icons.plus()} Add Key
          </button>
        : undefined}
      />

      <div className="overflow-auto max-h-[500px]">
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              <th className={gridStyles.headerCell}><SortableHeader label="Name" active={sort.key === "name"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "name"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Status" active={sort.key === "enabled"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "enabled"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Updated" active={sort.key === "updated"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "updated"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Not Before" active={sort.key === "not_before"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "not_before"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Expires" active={sort.key === "expires"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "expires"))} /></th>
              <th className={gridStyles.headerCellCenter}><SortableHeader label="Managed" active={sort.key === "managed"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "managed"))} align="center" /></th>
              <th className={gridStyles.headerCellCenter}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginated.map((k: KeyInfo) => (
              <tr key={k.name} className={kvRow}>
                <td className={`${gridStyles.strongCell} font-mono text-xs`}>
                  <button type="button" onClick={() => onOpenItem("key", k.name)} className={nameLinkClass} title="Open key details">
                    <Highlight text={k.name} term={search} />
                  </button>
                </td>
                <td className={gridStyles.cell}>
                  <Badge label={k.enabled ? "Enabled" : "Disabled"} color={k.enabled ? "green" : "red"} />
                </td>
                <td className={`${gridStyles.cell} text-xs`}>{fmt(k.updated)}</td>
                <td className={`${gridStyles.cell} text-xs`}>{fmt(k.not_before)}</td>
                <td className={`${gridStyles.cell} text-xs`}>{fmt(k.expires)}</td>
                <td className={gridStyles.centerCell}>{k.managed ? "Yes" : "—"}</td>
                <td className={gridStyles.centerCell}>
                  <div className="flex justify-center gap-1">
                    <GridIconButton onClick={() => onOpenItem("key", k.name)} title="View key details" tone="blue">{Icons.eye()}</GridIconButton>
                    {/* A certificate's backing key cannot be rotated or deleted directly. */}
                    {canWrite && !k.managed && <GridIconButton onClick={() => setEditingKey(k)} title="New key version" tone="blue">{Icons.edit()}</GridIconButton>}
                    {canWrite && !k.managed && <GridIconButton onClick={() => setConfirmDelete(k.name)} title="Delete key" tone="red">{Icons.trash()}</GridIconButton>}
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="py-6 text-center text-sm text-slate-400">No keys found</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <GridPagination page={safePage} totalPages={totalPages} totalItems={filtered.length} pageSize={pageSize} onPageChange={setPage} />

      {showCreate && vaultUri && <KeyFormDialog vaultUri={vaultUri} onClose={() => setShowCreate(false)} onSuccess={() => showToast("Key created successfully")} />}
      {editingKey && vaultUri && <KeyFormDialog vaultUri={vaultUri} editKey={editingKey} onClose={() => setEditingKey(null)} onSuccess={() => showToast("Key updated successfully")} />}

      {confirmDelete && (
        <Modal title="Confirm Delete" onClose={() => setConfirmDelete(null)}>
          <p className="text-sm text-gray-700 mb-4">
            Are you sure you want to delete key <span className="font-mono font-bold">{confirmDelete}</span>?
            This will soft-delete the key in Azure Key Vault.
          </p>
          {deleteMutation.isError && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-4">
              <p className="text-sm text-red-700">{(deleteMutation.error as any)?.response?.data?.detail || "Failed to delete key"}</p>
            </div>
          )}
          <div className="flex justify-end gap-2">
            <button onClick={() => setConfirmDelete(null)} className="px-4 py-2 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 transition">Cancel</button>
            <button
              onClick={() => handleDelete(confirmDelete)}
              disabled={deleteMutation.isPending}
              className="px-4 py-2 text-sm text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-50 transition"
            >
              {deleteMutation.isPending ? "Deleting..." : "Delete Key"}
            </button>
          </div>
        </Modal>
      )}
      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
};

// ── Certificates Tab ──────────────────────────────────────────────────


const CertificatesTab: React.FC<{ vaultUri: string | null; onOpenItem: OpenItem }> = ({ vaultUri, onOpenItem }) => {
  const { timezone } = usePortalTimezone();
  const { canWrite } = useAuth();
  const fmt = (iso: string | null) => fmtDate(iso, timezone);
  const queryClient = useQueryClient();
  const { data: certs, isLoading, isError, error } = useVaultCertificates(vaultUri);
  const deleteMutation = useDeleteCertificate();
  const [search, setSearch] = useState("");
  const [searchField, setSearchField] = useState<CertificateSearchField>("all");
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [toast, setToast] = useState<ToastState | null>(null);
  const showToast = useCallback((message: string, type: ToastState["type"] = "success") => setToast({ message, type }), []);
  const [refreshing, setRefreshing] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [sort, setSort] = useState<SortState<"name" | "cn_name" | "san" | "serial_number" | "enabled" | "expires">>({ key: "expires", direction: "asc" });
  const term = search.trim();
  // Which fields each certificate matched in, so hidden matches (a SAN past
  // "+N more", the thumbprint, a tag) can be called out on the row.
  const matches = useMemo(() => {
    const map = new Map<string, ReturnType<typeof certificateMatchFields>>();
    if (term) (certs || []).forEach((c) => map.set(c.name, certificateMatchFields(c, term, searchField)));
    return map;
  }, [certs, term, searchField]);
  const filtered = useMemo(
    () => (certs || []).filter((c: CertificateInfo) => !term || (matches.get(c.name)?.length ?? 0) > 0),
    [certs, term, matches],
  );
  const sorted = useMemo(() => sortCollection(filtered, sort.direction, (certificate) => {
    switch (sort.key) {
      case "name": return certificate.name?.toLowerCase();
      case "cn_name": return certificate.cn_name?.toLowerCase() || "";
      case "san": return certificate.san?.join(",").toLowerCase() || "";
      case "serial_number": return certificate.serial_number?.toLowerCase() || "";
      case "enabled": return certificate.enabled ? 1 : 0;
      case "expires": return certificate.expires || "";
    }
  }), [filtered, sort]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const paginated = sorted.slice((safePage - 1) * pageSize, safePage * pageSize);

  if (!vaultUri)
    return <p className="text-gray-500 text-sm py-4">Select a vault to view certificates</p>;
  if (isLoading)
    return <p className="text-gray-500 text-sm py-4">Loading certificates...</p>;
  if (isError) {
    const status = (error as any)?.response?.status;
    const detail = (error as any)?.response?.data?.detail || "Check vault access permissions or network settings.";
    const is403 = status === 403 || /access denied|forbidden|unauthorized/i.test(detail);

    return (
      <div className={`rounded-lg border p-4 my-2 ${is403 ? "bg-amber-50 border-amber-300" : "bg-red-50 border-red-300"}`}>
        <div className="flex items-center gap-2 mb-1">
          <svg width="18" height="18" viewBox="0 0 20 20" fill="none">
            <path d="M10 2L18 17H2L10 2Z" stroke={is403 ? "#d97706" : "#dc2626"} strokeWidth="1.5" fill={is403 ? "#fef3c7" : "#fee2e2"}/>
            <text x="10" y="14" textAnchor="middle" fontSize="10" fontWeight="bold" fill={is403 ? "#d97706" : "#dc2626"}>!</text>
          </svg>
          <span className={`font-semibold text-sm ${is403 ? "text-amber-700" : "text-red-700"}`}>
            {is403 ? "Access Denied" : "Failed to load certificates"}
          </span>
        </div>
        <p className={`text-sm ${is403 ? "text-amber-600" : "text-red-600"}`}>{detail}</p>
        {is403 && (
          <p className="text-xs text-amber-500 mt-2">
            The service principal needs <strong>Key Vault Certificates Officer</strong> RBAC role or <strong>Get, List</strong> certificate access policies on this vault.
          </p>
        )}
        <button
          onClick={async () => {
            setRefreshing(true);
            try {
              const fresh = await refreshVaultCertificates(vaultUri!);
              queryClient.setQueryData(["keyvault", "certificates", vaultUri], fresh);
            } catch { /* ignore */ }
            setRefreshing(false);
          }}
          className="mt-3 px-3 py-1 text-xs font-medium rounded bg-white border border-gray-300 hover:bg-gray-50 flex items-center gap-1"
          disabled={refreshing}
        >
          <span className={refreshing ? "animate-spin" : ""}>{Icons.refresh()}</span>
          {refreshing ? "Retrying…" : "Retry"}
        </button>
      </div>
    );
  }

  const handleRefresh = async () => {
    setRefreshing(true);
    try {
      const fresh = await refreshVaultCertificates(vaultUri!);
      queryClient.setQueryData(["keyvault", "certificates", vaultUri], fresh);
    } catch { /* ignore */ }
    setRefreshing(false);
  };

  const handleDelete = (name: string) => {
    deleteMutation.mutate(
      { vaultUri: vaultUri!, name },
      {
        onSuccess: () => {
          showToast("Certificate deleted successfully");
          setConfirmDelete(null);
        },
        onError: (e: any) => showToast(e?.response?.data?.detail || "Failed to delete certificate", "error"),
      }
    );
  };

  return (
    <div className={gridStyles.shell}>
      <GridToolbar
        search={search}
        onSearch={(value) => { setSearch(value); setPage(1); }}
        placeholder={
          searchField === "all" ? "Search name, CN, SAN, serial, thumbprint…" : `Search by ${CERTIFICATE_SEARCH_FIELDS.find((f) => f.value === searchField)?.label.replace("Search: ", "")}…`
        }
        countLabel={term ? `${filtered.length} of ${(certs || []).length} certificates` : `${filtered.length} certificates`}
        filters={
          <select
            value={searchField}
            onChange={(e) => { setSearchField(e.target.value as CertificateSearchField); setPage(1); }}
            className={gridSelectStyles}
            title="Choose which certificate fields the search term is matched against"
            aria-label="Certificate search field"
          >
            {CERTIFICATE_SEARCH_FIELDS.map((f) => (
              <option key={f.value} value={f.value}>{f.label}</option>
            ))}
          </select>
        }
        pageSize={pageSize}
        onPageSizeChange={(value) => { setPageSize(value); setPage(1); }}
        onRefresh={handleRefresh}
        refreshing={refreshing}
        primaryAction={canWrite ? (
          <button
            onClick={() => setShowCreate(true)}
            className="inline-flex items-center gap-2 rounded-xl bg-att-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-att-700"
          >
            {Icons.plus()} Add Certificate
          </button>
        ) : undefined}
      />

      <div className="overflow-auto max-h-[500px]">
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              <th className={gridStyles.headerCell}><SortableHeader label="Name" active={sort.key === "name"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "name"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="CN Name" active={sort.key === "cn_name"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "cn_name"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="SAN" active={sort.key === "san"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "san"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Serial Number" active={sort.key === "serial_number"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "serial_number"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Status" active={sort.key === "enabled"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "enabled"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Expires" active={sort.key === "expires"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "expires"))} /></th>
              <th className={gridStyles.headerCellCenter}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {paginated.map((c: CertificateInfo) => {
              const matched = matches.get(c.name) ?? [];
              const sanTerm = matched.includes("san") ? term.toLowerCase() : "";
              const sans = c.san || [];
              // One chip keeps the row one line high; while searching it is the
              // first matching SAN, so a hit never hides behind "+N more".
              const shownSan = (sanTerm && sans.find((s) => s.toLowerCase().includes(sanTerm))) || sans[0];
              const hiddenSans = sans.length - 1;
              const hidden = matched.filter((f) => f === "thumbprint" || f === "tags");
              return (
              <tr key={c.name} className={kvRow}>
                <td className={`${gridStyles.strongCell} font-mono text-xs`}>
                  <button
                    type="button"
                    onClick={() => onOpenItem("certificate", c.name)}
                    className={`${nameLinkClass} inline-block max-w-[20rem] truncate align-middle`}
                    title={`${c.name} — open certificate details`}
                  >
                    <Highlight text={c.name} term={matched.includes("name") ? term : ""} />
                  </button>
                  {hidden.length > 0 && (
                    <span className="ml-2 inline-flex gap-1 align-middle">
                      {hidden.map((f) => <Badge key={f} label={`${f === "tags" ? "tag" : f} match`} color="blue" />)}
                    </span>
                  )}
                </td>
                <td className={`${gridStyles.cell} max-w-[180px] truncate font-mono text-xs`} title={c.cn_name || ""}>
                  {c.cn_name ? <Highlight text={c.cn_name} term={matched.includes("cn") ? term : ""} /> : "—"}
                </td>
                <td className={`${gridStyles.cell} max-w-[220px] text-xs`}>
                  {sans.length > 0 ? (
                    <div className="flex items-center gap-1" title={sans.join("\n")}>
                      <span className="inline-block max-w-[11rem] truncate rounded bg-blue-50 px-1.5 py-0.5 align-middle font-mono text-[10px] text-blue-700">
                        <Highlight text={shownSan} term={sanTerm} />
                      </span>
                      {hiddenSans > 0 && (
                        <button
                          type="button"
                          onClick={() => onOpenItem("certificate", c.name)}
                          className="shrink-0 whitespace-nowrap px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 text-[10px] hover:bg-gray-200"
                          title="Show every SAN in the certificate details"
                        >
                          +{hiddenSans} more
                        </button>
                      )}
                    </div>
                  ) : <span className="text-gray-400">—</span>}
                </td>
                <td className={`${gridStyles.cell} max-w-[140px] truncate font-mono text-xs`} title={c.serial_number || ""}>
                  {/* Serials are matched without colons or spaces, so highlight the bare hex. */}
                  {c.serial_number ? <Highlight text={c.serial_number} term={matched.includes("serial") ? term.replace(/[\s:]/g, "") : ""} /> : "—"}
                </td>
                <td className={gridStyles.cell}>
                  <Badge label={c.enabled ? "Enabled" : "Disabled"} color={c.enabled ? "green" : "red"} />
                </td>
                <td className={`${gridStyles.cell} text-xs whitespace-nowrap`}>{fmt(c.expires)}</td>
                <td className={gridStyles.centerCell}>
                  <div className="flex justify-center gap-1">
                    <GridIconButton onClick={() => onOpenItem("certificate", c.name)} title="View certificate details" tone="blue">{Icons.eye()}</GridIconButton>
                    {canWrite && <GridIconButton onClick={() => setConfirmDelete(c.name)} title="Delete certificate" tone="red">{Icons.trash()}</GridIconButton>}
                  </div>
                </td>
              </tr>
              );
            })}
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="py-6 text-center text-sm text-slate-400">{term ? `No certificates match “${term}”` : "No certificates found"}</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <GridPagination page={safePage} totalPages={totalPages} totalItems={filtered.length} pageSize={pageSize} onPageChange={setPage} />

      {showCreate && vaultUri && (
        <CertificateFormDialog
          vaultUri={vaultUri}
          onClose={() => setShowCreate(false)}
          onSuccess={() => showToast("Certificate imported successfully")}
        />
      )}

      {confirmDelete && (
        <Modal title="Confirm Delete" onClose={() => setConfirmDelete(null)}>
          <p className="text-sm text-gray-700 mb-4">
            Are you sure you want to delete certificate <span className="font-mono font-bold">{confirmDelete}</span>?
            This will soft-delete the certificate in Azure Key Vault.
          </p>
          {deleteMutation.isError && (
            <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-4">
              <p className="text-sm text-red-700">{(deleteMutation.error as any)?.response?.data?.detail || "Failed to delete certificate"}</p>
            </div>
          )}
          <div className="flex justify-end gap-2">
            <button onClick={() => setConfirmDelete(null)} className="px-4 py-2 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 transition">Cancel</button>
            <button
              onClick={() => handleDelete(confirmDelete)}
              disabled={deleteMutation.isPending}
              className="px-4 py-2 text-sm text-white bg-red-600 rounded-lg hover:bg-red-700 disabled:opacity-50 transition"
            >
              {deleteMutation.isPending ? "Deleting..." : "Delete Certificate"}
            </button>
          </div>
        </Modal>
      )}

      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
};

type AuditResource = "secret" | "key" | "certificate";
const AUDIT_RESOURCE_BADGE: Record<string, { label: string; color: "blue" | "purple" | "gray" }> = {
  secret: { label: "Secret", color: "blue" },
  key: { label: "Key", color: "purple" },
  certificate: { label: "Certificate", color: "gray" },
};

const AuditHistoryTab: React.FC<{ vaultUri: string | null; vaultName: string | null; onOpenItem?: OpenItem }> = ({ vaultUri, vaultName, onOpenItem }) => {
  const { timezone } = usePortalTimezone();
  const fmt = (iso: string | null) => fmtDateTime(iso, timezone);
  const { data, isLoading, isError, error, refetch, isFetching } = useKeyVaultAuditHistory(vaultUri);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "success" | "failed">("all");
  const [resourceFilter, setResourceFilter] = useState<"all" | AuditResource>("all");
  const [activityFilter, setActivityFilter] = useState<"all" | "changes" | "reads">("all");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [sort, setSort] = useState<SortState<"timestamp" | "action" | "resource_type" | "resource_name" | "status" | "user_email">>({ key: "timestamp", direction: "desc" });

  const entries = data?.history || [];
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return entries.filter((entry) => {
      const matchesSearch = !query || [
        entry.action,
        entry.resource_type,
        entry.resource_name,
        entry.summary,
        entry.user_email || "",
        entry.user_id,
      ].some((value) => value.toLowerCase().includes(query));
      const matchesStatus = statusFilter === "all" || entry.status === statusFilter;
      const matchesResource = resourceFilter === "all" || entry.resource_type === resourceFilter;
      const matchesActivity = activityFilter === "all" || (activityFilter === "reads") === isReadAction(entry.action);
      return matchesSearch && matchesStatus && matchesResource && matchesActivity;
    });
  }, [entries, resourceFilter, search, statusFilter, activityFilter]);
  const sorted = useMemo(() => sortCollection(filtered, sort.direction, (entry) => {
    switch (sort.key) {
      case "timestamp": return entry.timestamp || "";
      case "action": return entry.action;
      case "resource_type": return entry.resource_type;
      case "resource_name": return entry.resource_name;
      case "status": return entry.status;
      case "user_email": return entry.user_email || entry.user_id;
    }
  }), [filtered, sort]);
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const paginated = sorted.slice((safePage - 1) * pageSize, safePage * pageSize);


  if (!vaultUri) {
    return <p className="text-sm text-slate-500 py-4">Select a vault to review its audit trail.</p>;
  }

  if (isLoading) {
    return <p className="text-sm text-slate-500 py-4">Loading audit history...</p>;
  }

  if (isError) {
    return (
      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-700">
        <p>Failed to load audit history: {(error as any)?.response?.data?.detail || (error as Error)?.message || "Unknown error"}</p>
        <button
          onClick={() => { void refetch(); }}
          className="mt-3 inline-flex items-center gap-2 rounded-lg border border-red-200 bg-white px-3 py-2 text-xs font-semibold text-red-700 hover:bg-red-100"
        >
          {Icons.refresh()} Retry
        </button>
      </div>
    );
  }

  return (
    <div className={gridStyles.shell}>
      <div className={`${gridStyles.panelHeader} border-b-att-100/80`}>
        <div className="flex flex-col gap-1">
          <span className="text-sm font-semibold text-slate-800">Audit history for {vaultName || "selected vault"}</span>
          <span className="text-xs text-slate-500">Portal changes to secrets, keys and certificates, and every read of a secret value, from the shared audit log.</span>
        </div>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-3">
          <span className={gridStyles.countBadge}>{filtered.length} events</span>
          <AutoRefreshIndicator label="History auto-refresh" />
        </div>
      </div>

      <div className={gridStyles.panelHeader}>
        <div className="ml-auto flex flex-wrap items-center justify-end gap-3">
          <input
            type="text"
            placeholder="Search history..."
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(1);
            }}
            className={gridStyles.toolbarInput}
          />
          <select
            value={activityFilter}
            onChange={(event) => {
              setActivityFilter(event.target.value as "all" | "changes" | "reads");
              setPage(1);
            }}
            className={gridSelectStyles}
            aria-label="Activity type"
          >
            <option value="all">Changes & reads</option>
            <option value="changes">Changes only</option>
            <option value="reads">Value reads only</option>
          </select>
          <select
            value={resourceFilter}
            onChange={(event) => {
              setResourceFilter(event.target.value as "all" | AuditResource);
              setPage(1);
            }}
            className={gridSelectStyles}
            aria-label="Resource type"
          >
            <option value="all">All resources</option>
            <option value="secret">Secrets</option>
            <option value="key">Keys</option>
            <option value="certificate">Certificates</option>
          </select>
          <select
            value={statusFilter}
            onChange={(event) => {
              setStatusFilter(event.target.value as "all" | "success" | "failed");
              setPage(1);
            }}
            className={gridSelectStyles}
          >
            <option value="all">All statuses</option>
            <option value="success">Success</option>
            <option value="failed">Failed</option>
          </select>
          <select
            value={pageSize}
            onChange={(event) => {
              setPageSize(Number(event.target.value));
              setPage(1);
            }}
            className={gridSelectStyles}
          >
            {KV_PAGE_SIZE_OPTIONS.map((size) => (
              <option key={size} value={size}>{size} / page</option>
            ))}
          </select>
          <button
            onClick={() => { void refetch(); }}
            disabled={isFetching}
            className="inline-flex items-center gap-2 rounded-lg border border-att-200 bg-white px-3 py-2 text-sm font-medium text-gray-700 hover:border-att-300 hover:bg-att-50 disabled:opacity-50"
          >
            <span className={isFetching ? "animate-spin" : ""}>{Icons.refresh()}</span>
            {isFetching ? "Refreshing..." : "Refresh"}
          </button>
        </div>
      </div>

      <div className="overflow-auto max-h-[500px]">
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              <th className={gridStyles.headerCell}><SortableHeader label="Timestamp" active={sort.key === "timestamp"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "timestamp"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Action" active={sort.key === "action"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "action"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Resource" active={sort.key === "resource_type"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "resource_type"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Name" active={sort.key === "resource_name"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "resource_name"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Status" active={sort.key === "status"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "status"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="User" active={sort.key === "user_email"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "user_email"))} /></th>
              <th className={gridStyles.headerCell}>Summary</th>
            </tr>
          </thead>
          <tbody>
            {paginated.map((entry: KeyVaultAuditEntry) => (
              <tr key={entry.id} className={kvRow}>
                <td className={`${gridStyles.cell} text-xs whitespace-nowrap`}>{fmt(entry.timestamp)}</td>
                <td className={gridStyles.cell}>{auditActionBadge(entry.action)}</td>
                <td className={gridStyles.cell}>
                  <Badge
                    label={AUDIT_RESOURCE_BADGE[entry.resource_type]?.label ?? entry.resource_type}
                    color={AUDIT_RESOURCE_BADGE[entry.resource_type]?.color ?? "gray"}
                  />
                </td>
                <td className={`${gridStyles.strongCell} font-mono text-xs`}>
                  {/* A value search names the vault, not an item; deleted items have no detail to open. */}
                  {onOpenItem && entry.resource_type in AUDIT_RESOURCE_BADGE && entry.action !== "search_secret_values" && !entry.action.startsWith("delete") && !entry.action.startsWith("bulk") ? (
                    <button type="button" onClick={() => onOpenItem(entry.resource_type as KeyVaultItemType, entry.resource_name)} className={nameLinkClass}>
                      {entry.resource_name}
                    </button>
                  ) : (
                    entry.resource_name
                  )}
                </td>
                <td className={gridStyles.cell}>
                  <Badge label={entry.status === "success" ? "Success" : "Failed"} color={entry.status === "success" ? "green" : "red"} />
                </td>
                <td className={`${gridStyles.cell} text-xs`}>{entry.user_email || entry.user_id}</td>
                <td className={`${gridStyles.cell} text-xs text-slate-600`}>
                  <span className="block max-w-[28rem] truncate" title={entry.summary}>{entry.summary}</span>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={7} className="py-8 text-center text-sm text-slate-400">No audit entries found for this vault.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <GridPagination page={safePage} totalPages={totalPages} totalItems={filtered.length} pageSize={pageSize} onPageChange={setPage} />
    </div>
  );
};

// ── Main Page ─────────────────────────────────────────────────────────

type TabKey = "secrets" | "keys" | "certificates" | "audit";
const TAB_KEYS: TabKey[] = ["secrets", "keys", "certificates", "audit"];

/**
 * KPI tiles filter the grid beneath them; each grid's filter lives in the URL
 * so the view can be linked: `?inventory=` (vault grid) and `?expiry=`
 * (expiring grid, default 90 days). The Vaults and Expiring (90d) tiles reset them.
 */
const VAULT_TYPE_FILTERS: VaultTypeFilter[] = ["secrets", "keys", "certificates"];
const EXPIRY_WINDOW_KEYS: ExpiryWindow[] = ["attention", "expired", "30", "90", "360"];
const INVENTORY_LABELS: Record<VaultTypeFilter, string> = {
  secrets: "Vaults with secrets",
  keys: "Vaults with keys",
  certificates: "Vaults with certificates",
};
const EXPIRY_LABELS: Partial<Record<ExpiryWindow, string>> = {
  attention: "Expired or expiring within 90 days",
  expired: "Expired items",
  "30": "Expiring within 30 days",
  "360": "Expiring within 360 days",
};

interface ItemDetailTarget {
  vaultName: string;
  vaultUri: string;
  type: KeyVaultItemType;
  name: string;
  tab?: ItemDetailTab;
}

const plural = (count: number, noun: string) => `${count} ${noun}${count === 1 ? "" : "s"}`;

/** "Failed vaults (2): a, b | Vaults preserved from cache … (22): x, y" → its parts. */
const syncMessageParts = (message: string) => message.split(" | ").map((part) => part.trim()).filter(Boolean);

const KeyVaultPage: React.FC = () => {
  const queryClient = useQueryClient();
  const { canWrite } = useAuth();
  const { timezone } = usePortalTimezone();
  const { data: dashboard, isPending, isError, error } = useKeyVaultDashboard();
  const { data: vaults } = useKeyVaults();
  const { data: syncStatuses } = useKeyVaultSyncStatus(1);
  const syncMutation = useKeyVaultSync();
  const vaultSyncMutation = useKeyVaultSyncVault();
  const [params, setParams] = useSearchParams();
  const [refreshingDashboard, setRefreshingDashboard] = useState(false);
  const [syncingVault, setSyncingVault] = useState<string | null>(null);
  const [showSyncDetails, setShowSyncDetails] = useState(false);
  const [vaultDetail, setVaultDetail] = useState<string | null>(null);
  const [itemDetail, setItemDetail] = useState<ItemDetailTarget | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const showToast = useCallback((message: string, type: ToastState["type"] = "success") => setToast({ message, type }), []);
  const expiringRef = useRef<HTMLDivElement>(null);
  const inventoryRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  // ── URL state: selected vault, its tab, and the active tile ──
  const selectedVault = params.get("vault");
  const requestedTab = params.get("tab") as TabKey | null;
  const activeTab: TabKey = requestedTab && TAB_KEYS.includes(requestedTab) ? requestedTab : "secrets";
  const requestedInventory = params.get("inventory") as VaultTypeFilter | null;
  const vaultTypeFilter = requestedInventory && VAULT_TYPE_FILTERS.includes(requestedInventory) ? requestedInventory : null;
  const requestedExpiry = params.get("expiry") as ExpiryWindow | null;
  const expiryWindow: ExpiryWindow = requestedExpiry && EXPIRY_WINDOW_KEYS.includes(requestedExpiry) ? requestedExpiry : "90";

  const updateParams = useCallback(
    (changes: Record<string, string | null>) =>
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          Object.entries(changes).forEach(([key, value]) => (value === null ? next.delete(key) : next.set(key, value)));
          return next;
        },
        { replace: true },
      ),
    [setParams],
  );
  const scrollTo = (ref: React.RefObject<HTMLDivElement>) =>
    // After the filter re-renders the grid, so the scroll lands on its new height.
    window.requestAnimationFrame(() => ref.current?.scrollIntoView?.({ behavior: "smooth", block: "start" }));
  /** A tile sets its grid's filter; clicking the active tile again clears it. */
  const toggleInventory = (filter: VaultTypeFilter | null) => {
    updateParams({ inventory: filter === null || vaultTypeFilter === filter ? null : filter });
    scrollTo(inventoryRef);
  };
  const toggleExpiry = (next: ExpiryWindow) => {
    updateParams({ expiry: next === "90" || expiryWindow === next ? null : next });
    scrollTo(expiringRef);
  };

  // ── Sync status ──
  const latestSync = syncStatuses?.[0] ?? null;
  const isSyncing = latestSync?.status === "running" || syncMutation.isPending;
  // A sync started elsewhere (scheduler, another user) finishing: show its data.
  const previousSyncStatus = useRef(latestSync?.status);
  useEffect(() => {
    if (previousSyncStatus.current === "running" && latestSync && latestSync.status !== "running") {
      void queryClient.invalidateQueries({ queryKey: ["keyvault"] });
    }
    previousSyncStatus.current = latestSync?.status;
  }, [latestSync, queryClient]);

  const vaultUriByName = useMemo(() => {
    const map: Record<string, string> = {};
    (vaults || []).forEach((v: KeyVaultInfo) => { if (v.vault_uri) map[v.name] = v.vault_uri; });
    // The dashboard rows are scoped like the page, so they win.
    (dashboard?.vault_summaries || []).forEach((v) => { if (v.vault_uri) map[v.name] = v.vault_uri; });
    return map;
  }, [vaults, dashboard]);
  const selectedVaultUri = selectedVault ? vaultUriByName[selectedVault] ?? null : null;
  const expiringItems = dashboard?.expiring_items ?? [];

  // Bring the vault panel into view when a vault is picked (or opened from a link).
  useEffect(() => {
    if (selectedVault && selectedVaultUri) scrollTo(panelRef);
  }, [selectedVault, selectedVaultUri]);

  const openVault = useCallback((name: string) => setVaultDetail(name), []);
  const openItem = useCallback(
    (vaultName: string, type: KeyVaultItemType, name: string, tab?: ItemDetailTab) => {
      const vaultUri = vaultUriByName[vaultName];
      if (!vaultUri) {
        showToast(`Vault ${vaultName} is not in the current inventory`, "error");
        return;
      }
      setItemDetail({ vaultName, vaultUri, type, name, tab });
    },
    [vaultUriByName, showToast],
  );

  const handleDashboardRefresh = async () => {
    setRefreshingDashboard(true);
    try {
      const fresh = await refreshKeyVaultDashboard();
      // Key includes the active subscription scope — update whichever variant
      // is currently mounted rather than the bare (now-unused) static key.
      queryClient.setQueriesData({ queryKey: ["keyvault", "dashboard"] }, fresh);
    } catch (e) {
      showToast(formatAxiosError(e, "Could not refresh the dashboard"), "error");
    }
    setRefreshingDashboard(false);
  };

  const handleSyncAll = () =>
    syncMutation.mutate(undefined, {
      onSuccess: (result: { status?: string; vaults_synced?: number; vaults_preserved?: number; vaults_failed?: number }) => {
        const kept = (result.vaults_preserved ?? 0) + (result.vaults_failed ?? 0);
        showToast(
          kept > 0
            ? `Synced ${result.vaults_synced ?? 0} vaults; ${kept} could not be read and kept their last synced data`
            : `Synced ${result.vaults_synced ?? 0} vaults from Azure`,
          kept > 0 ? "warning" : "success",
        );
      },
      onError: (e: unknown) => showToast(formatAxiosError(e, "Sync failed"), "error"),
    });

  const handleSyncVault = (vaultName: string, vaultUri: string) => {
    setSyncingVault(vaultName);
    vaultSyncMutation.mutate(
      { vaultName, vaultUri },
      {
        onSuccess: (result: { status?: string; item_failures?: string[] }) => {
          if (result?.status === "partial") {
            showToast(`Vault "${vaultName}" synced partially — could not list: ${(result.item_failures || []).join(", ")}`, "warning");
          } else {
            showToast(`Vault "${vaultName}" synced successfully`);
          }
          setSyncingVault(null);
        },
        onError: (e: unknown) => {
          showToast(formatAxiosError(e, "Vault sync failed"), "error");
          setSyncingVault(null);
        },
      },
    );
  };

  if (isPending) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
        <span className="ml-3 text-gray-500">Loading Key Vault data...</span>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="p-6">
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 text-red-700">
          Failed to load Key Vault data: {formatAxiosError(error, (error as Error)?.message || "Unknown error")}
        </div>
      </div>
    );
  }

  if (!dashboard) {
    return (
      <div className="p-6">
        <div className="bg-yellow-50 border border-yellow-200 rounded-xl p-4 text-yellow-700">
          No Key Vault data available. Please try refreshing the page.
        </div>
      </div>
    );
  }

  const d = dashboard;
  const expiredCount = d.expired_count ?? expiringItems.filter((i) => i.days_remaining < 0).length;
  // Tile tooltips: where the inventory lives, and what kind of items are due.
  const subscriptionCount = new Set(d.vault_summaries.map((v) => v.subscription_id).filter(Boolean)).size;
  const vaultsHolding = (type: VaultTypeFilter) => d.vault_summaries.filter((v) => v[`${type}_count`] > 0).length;
  const typeBreakdown = (inWindow: (days: number) => boolean, none: string) => {
    const due = expiringItems.filter((i) => inWindow(i.days_remaining));
    const parts = (["secret", "certificate", "key"] as const)
      .map((type) => [type, due.filter((i) => i.type === type).length] as const)
      .filter(([, count]) => count > 0)
      .map(([type, count]) => plural(count, type));
    return parts.length ? parts.join(" · ") : none;
  };
  const tabs: { key: TabKey; label: string; icon: React.ReactNode }[] = [
    { key: "secrets", label: "Secrets", icon: Icons.secret("text-green-600") },
    { key: "keys", label: "Keys", icon: Icons.key("text-purple-600") },
    { key: "certificates", label: "Certificates", icon: Icons.certificate("text-indigo-600") },
    { key: "audit", label: "Audit History", icon: Icons.history("text-att-700") },
  ];
  const syncParts = latestSync?.error_message ? syncMessageParts(latestSync.error_message) : [];
  const vaultSummary = (name: string | null) => d.vault_summaries.find((v) => v.name === name);
  const panelVaultKnown = !!selectedVault && !!selectedVaultUri;
  const vaultTabs = (vaultName: string, vaultUri: string): Record<TabKey, React.ReactNode> => {
    const onOpenItem: OpenItem = (type, name, tab) => openItem(vaultName, type, name, tab);
    return {
      secrets: <SecretsTab key={vaultUri} vaultUri={vaultUri} onOpenItem={onOpenItem} />,
      keys: <KeysTab key={vaultUri} vaultUri={vaultUri} onOpenItem={onOpenItem} />,
      certificates: <CertificatesTab key={vaultUri} vaultUri={vaultUri} onOpenItem={onOpenItem} />,
      audit: <AuditHistoryTab key={vaultUri} vaultUri={vaultUri} vaultName={vaultName} onOpenItem={onOpenItem} />,
    };
  };

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
            {Icons.vault("h-8 w-8 text-att-500")}
            Azure Key Vault
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage secrets, keys, and certificates across all monitored subscriptions
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Sync status indicator */}
          {latestSync && (
            <div className="text-right text-xs text-gray-500">
              {isSyncing ? (
                <span className="flex items-center justify-end gap-1 text-blue-600">
                  <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
                  Syncing from Azure…
                </span>
              ) : (
                <span className="flex items-center justify-end gap-1" title={latestSync.started_at ? `Started ${fmtDateTime(latestSync.started_at, timezone)} · ${latestSync.triggered_by}` : undefined}>
                  {latestSync.status === "completed" ? (
                    <svg className="h-3.5 w-3.5 text-green-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 6L9 17l-5-5" /></svg>
                  ) : latestSync.status === "partial" ? (
                    <svg className="h-3.5 w-3.5 text-amber-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>
                  ) : latestSync.status === "failed" ? (
                    <svg className="h-3.5 w-3.5 text-red-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" /></svg>
                  ) : null}
                  {latestSync.status === "failed" ? "Last sync failed: " : "Last synced: "}
                  {latestSync.completed_at ? fmtDateTime(latestSync.completed_at, timezone) : "never"}
                </span>
              )}
              {(latestSync.status === "completed" || latestSync.status === "partial") && (
                <span className="block text-gray-400 mt-0.5" title="Vaults · secrets · keys · certificates synced across all monitored subscriptions">
                  {latestSync.vaults_synced} vaults · {latestSync.secrets_synced} secrets · {latestSync.keys_synced} keys · {latestSync.certificates_synced} certs
                </span>
              )}
              {syncParts.length > 0 && (
                <button
                  type="button"
                  onClick={() => setShowSyncDetails((v) => !v)}
                  aria-expanded={showSyncDetails}
                  className={`mt-0.5 text-[11px] font-medium underline-offset-2 hover:underline ${latestSync.status === "failed" ? "text-red-600" : "text-amber-600"}`}
                >
                  {showSyncDetails ? "Hide sync warnings" : `Sync warnings (${syncParts.length}) — details`}
                </button>
              )}
            </div>
          )}
          {canWrite && (
          <button
            onClick={handleSyncAll}
            disabled={isSyncing}
            className="inline-flex items-center gap-1.5 rounded-lg border border-blue-300 bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-700 transition hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
            title="Sync all vault data from Azure to the portal database"
          >
            <svg className={`h-4 w-4 ${isSyncing ? "animate-spin" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
              <path d="M3 3v5h5" />
              <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
              <path d="M16 16h5v5" />
            </svg>
            {isSyncing ? "Syncing…" : "Sync Now"}
          </button>
          )}
        </div>
      </div>

      {showSyncDetails && syncParts.length > 0 && (
        <div className={`rounded-xl border px-4 py-3 text-sm ${latestSync?.status === "failed" ? "border-red-200 bg-red-50 text-red-800" : "border-amber-200 bg-amber-50 text-amber-900"}`}>
          <p className="font-semibold">Last sync could not read every vault</p>
          <ul className="mt-1 list-disc space-y-1 pl-5">
            {syncParts.map((part) => <li key={part} className="break-words">{part}</li>)}
          </ul>
          <p className="mt-2 text-xs">
            Vaults listed as preserved from cache could be discovered but their secrets or keys could not be listed — usually the vault firewall or a
            private endpoint blocks the portal's network, or its identity lacks List permission. Their last synced items are still shown. Use a vault's
            sync button (or its Azure portal link in the vault details) to check it.
          </p>
        </div>
      )}

      {/* KPI tiles — each filters the grid beneath it, like AKS Operations.
          One row of compact tiles from xl up (the page is max-w-7xl, so seven
          tiles are ~160px each); 4 + 3 below that so titles never clip. The
          detail behind each number is in its tooltip. */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4 xl:grid-cols-7">
        <MetricCard
          compact
          title="Vaults"
          value={d.total_vaults}
          icon={Icons.vault()}
          tone="blue"
          onClick={() => toggleInventory(null)}
          actionLabel={`Show all vaults (in ${plural(subscriptionCount, "subscription")})`}
        />
        <MetricCard
          compact
          title="Secrets"
          value={d.total_secrets}
          icon={Icons.secret()}
          tone="green"
          onClick={() => toggleInventory("secrets")}
          active={vaultTypeFilter === "secrets"}
          actionLabel={`Show vaults that hold secrets, most first (${plural(vaultsHolding("secrets"), "vault")})`}
        />
        <MetricCard
          compact
          title="Keys"
          value={d.total_keys}
          icon={Icons.key()}
          tone="purple"
          onClick={() => toggleInventory("keys")}
          active={vaultTypeFilter === "keys"}
          actionLabel={`Show vaults that hold keys, most first (${plural(vaultsHolding("keys"), "vault")})`}
        />
        <MetricCard
          compact
          title="Certificates"
          value={d.total_certificates}
          icon={Icons.certificate()}
          tone="indigo"
          onClick={() => toggleInventory("certificates")}
          active={vaultTypeFilter === "certificates"}
          actionLabel={`Show vaults that hold certificates, most first (${plural(vaultsHolding("certificates"), "vault")})`}
        />
        <MetricCard
          compact
          title="Expired"
          value={expiredCount}
          icon={Icons.expired()}
          tone={expiredCount > 0 ? "red" : "slate"}
          onClick={() => toggleExpiry("expired")}
          active={expiryWindow === "expired"}
          actionLabel={`Show expired items — enabled, past their expiry date: ${typeBreakdown((days) => days < 0, "none")}`}
        />
        <MetricCard
          compact
          title="Expiring (30d)"
          value={d.expiring_within_30_days}
          icon={Icons.warning()}
          tone={d.expiring_within_30_days > 0 ? "amber" : "slate"}
          onClick={() => toggleExpiry("30")}
          active={expiryWindow === "30"}
          actionLabel={`Show items expiring within 30 days: ${typeBreakdown((days) => days >= 0 && days <= 30, "none")}`}
        />
        <MetricCard
          compact
          title="Expiring (90d)"
          value={d.expiring_within_90_days}
          icon={Icons.clipboard()}
          tone={d.expiring_within_90_days > 0 ? "orange" : "slate"}
          onClick={() => toggleExpiry("90")}
          actionLabel={`Show items expiring within 90 days: ${typeBreakdown((days) => days >= 0 && days <= 90, "none")}`}
        />
      </div>

      {/* Expired & expiring items */}
      <div ref={expiringRef} className="scroll-mt-4 space-y-2">
        <TileFilterNotice label={EXPIRY_LABELS[expiryWindow] ?? null} onClear={() => updateParams({ expiry: null })} />
        <ExpiringItemsTable
          items={expiringItems}
          expiryWindow={expiryWindow}
          onWindowChange={(next) => updateParams({ expiry: next === "90" ? null : next })}
          onRefresh={handleDashboardRefresh}
          refreshing={refreshingDashboard}
          vaultUriByName={vaultUriByName}
          canWrite={canWrite}
          onToast={setToast}
          onOpenItem={(vaultName, type, name) => openItem(vaultName, type, name)}
          onOpenVault={openVault}
        />
      </div>

      {/* Vault Inventory */}
      <div ref={inventoryRef} className="scroll-mt-4 space-y-2">
        <TileFilterNotice label={vaultTypeFilter ? INVENTORY_LABELS[vaultTypeFilter] : null} onClear={() => updateParams({ inventory: null })} />
        <VaultSummaryTable
          vaults={d.vault_summaries}
          onSelect={(name) => updateParams({ vault: name })}
          onOpenVault={openVault}
          selectedVault={selectedVault}
          typeFilter={vaultTypeFilter}
          onRefresh={handleDashboardRefresh}
          refreshing={refreshingDashboard}
          canWrite={canWrite}
          onSyncVault={handleSyncVault}
          syncingVault={syncingVault}
        />
      </div>

      {/* Vault Details — Tabs */}
      {panelVaultKnown && (
        <div ref={panelRef} className="scroll-mt-4 rounded-3xl border border-att-100 bg-gradient-to-br from-white to-att-50/60 p-6 shadow-sm shadow-att-100/40">
          <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <h3 className="text-lg font-semibold text-slate-800">
              <button type="button" onClick={() => openVault(selectedVault!)} className="text-att-700 hover:underline" title="Open vault details">
                {selectedVault}
              </button>
              <span className="ml-2 font-mono text-sm font-normal text-slate-400">
                {selectedVaultUri}
              </span>
            </h3>
            <div className="flex items-center gap-4">
              <button
                onClick={() => openVault(selectedVault!)}
                className="text-sm font-medium text-att-700 transition hover:text-att-900"
              >
                Vault details
              </button>
              <button
                onClick={() => updateParams({ vault: null, tab: null })}
                className="text-sm font-medium text-slate-400 transition hover:text-slate-600"
              >
                Close
              </button>
            </div>
          </div>

          {/* Tab bar */}
          <div className="mb-4 border-b border-att-100">
            <nav className="flex flex-wrap gap-3" role="tablist">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                role="tab"
                aria-selected={activeTab === tab.key}
                onClick={() => updateParams({ tab: tab.key === "secrets" ? null : tab.key })}
                className={`inline-flex items-center gap-2 rounded-t-xl border-b-2 px-3 py-3 text-sm font-semibold whitespace-nowrap transition-colors ${
                  activeTab === tab.key
                    ? "border-att-500 bg-white/80 text-att-700"
                    : "border-transparent text-slate-500 hover:border-att-200 hover:text-slate-700"
                }`}
              >
                {tab.icon} {tab.label}
              </button>
            ))}
            </nav>
          </div>

          {/* Tab content — keyed by vault so search, paging and sort reset on a vault switch */}
          {vaultTabs(selectedVault!, selectedVaultUri!)[activeTab]}
        </div>
      )}

      {vaultDetail && vaultUriByName[vaultDetail] && (() => {
        const uri = vaultUriByName[vaultDetail];
        const sections = vaultTabs(vaultDetail, uri);
        return (
          <VaultDetailModal
            vaultName={vaultDetail}
            vaultUri={uri}
            summary={vaultSummary(vaultDetail)}
            expiring={expiringItems.filter((i) => i.vault_name === vaultDetail)}
            sections={{
              secrets: sections.secrets,
              keys: sections.keys,
              certificates: sections.certificates,
              activity: sections.audit,
              expiring: (
                <ExpiringItemsTable
                  items={expiringItems.filter((i) => i.vault_name === vaultDetail)}
                  defaultWindow="attention"
                  onRefresh={handleDashboardRefresh}
                  refreshing={refreshingDashboard}
                  vaultUriByName={vaultUriByName}
                  canWrite={canWrite}
                  onToast={setToast}
                  onOpenItem={(vaultName, type, name) => openItem(vaultName, type, name)}
                />
              ),
            }}
            actions={
              canWrite ? (
                <button
                  type="button"
                  onClick={() => handleSyncVault(vaultDetail, uri)}
                  disabled={syncingVault === vaultDetail}
                  className="inline-flex items-center gap-1.5 rounded-lg border border-att-200 bg-white px-3 py-1.5 text-sm font-medium text-att-700 hover:bg-att-50 disabled:opacity-50"
                >
                  <span className={syncingVault === vaultDetail ? "inline-block animate-spin" : "inline-block"}>{Icons.refresh("h-4 w-4")}</span>
                  {syncingVault === vaultDetail ? "Syncing…" : "Sync vault"}
                </button>
              ) : undefined
            }
            onOpenItem={(type, name) => openItem(vaultDetail, type, name)}
            onClose={() => setVaultDetail(null)}
          />
        );
      })()}

      {itemDetail && (
        <KeyVaultItemDetail
          key={`${itemDetail.vaultUri}/${itemDetail.type}/${itemDetail.name}/${itemDetail.tab ?? ""}`}
          vaultUri={itemDetail.vaultUri}
          vaultName={itemDetail.vaultName}
          itemType={itemDetail.type}
          name={itemDetail.name}
          initialTab={itemDetail.tab}
          canWrite={canWrite}
          onClose={() => setItemDetail(null)}
          onOpenVault={vaultDetail === itemDetail.vaultName ? undefined : () => { setVaultDetail(itemDetail.vaultName); setItemDetail(null); }}
          renderSecretEditor={(secret, close) => (
            <SecretFormDialog
              vaultUri={itemDetail.vaultUri}
              editSecret={secret}
              onClose={close}
              onSuccess={() => showToast(`New version of ${secret.name} saved`)}
            />
          )}
          onDeleted={(message) => showToast(message)}
        />
      )}

      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
};

export default KeyVaultPage;
