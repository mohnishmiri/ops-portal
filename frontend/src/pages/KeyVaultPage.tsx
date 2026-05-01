/**
 * Key Vault Management Page — Azure Key Vault discovery, secrets, keys, and certificates.
 * Supports viewing secret values, Base64 decode, create / update / delete secrets and keys,
 * and detailed certificate inspection (thumbprint, CN, SAN).
 * All icons are inline SVG vector icons (no emojis).
 */

import React, { useState, useCallback, useMemo } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../contexts/AuthContext";
import Toast, { type ToastState } from "../components/Toast";
import { AutoRefreshIndicator, gridStyles, type SortState, nextSortState, SortableHeader } from "../components/gridStyles";
import {
  useKeyVaultDashboard,
  useKeyVaults,
  useVaultSecrets,
  useVaultKeys,
  useVaultCertificates,
  useSecretValue,
  useCreateSecret,
  useDeleteSecret,
  useKeyDetail,
  useCreateKey,
  useDeleteKey,
  useCertificateDetail,
  useKeyVaultAuditHistory,
  useKeyVaultSyncStatus,
  useKeyVaultSync,
  useKeyVaultSyncVault,
  useExtendSecretExpiry,
  useBulkExtendSecretExpiry,
  refreshVaultSecrets,
  refreshVaultKeys,
  refreshVaultCertificates,
  refreshKeyVaultDashboard,
  KeyVaultInfo,
  SecretInfo,
  KeyInfo,
  CertificateInfo,
  ExpiringItem,
  VaultSummary,
  SecretValueResponse,
  KeyDetailResponse,
  CertificateDetailResponse,
  SyncStatusInfo,
  KeyVaultAuditEntry,
} from "../services/costApi";
import { usePortalTimezone } from "../contexts/TimezoneContext";

// ── SVG Icons (inline vector) ─────────────────────────────────────────

const Icon: React.FC<{ d: string; className?: string; size?: number }> = ({ d, className = "", size = 20 }) => (
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={size} height={size} className={className}>
    <path d={d} />
  </svg>
);

const Icons = {
  vault: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" />
    </svg>
  ),
  secret: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="m15.5 7.5 2.3 2.3a1 1 0 0 0 1.4 0l2.1-2.1a1 1 0 0 0 0-1.4L19 4" /><path d="m21 2-9.6 9.6" /><circle cx="7.5" cy="15.5" r="5.5" /><path d="m5.5 17.5 1-1" />
    </svg>
  ),
  key: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />
    </svg>
  ),
  certificate: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" /><path d="M12 4v1m0 14v1m8-8h-1M5 12H4m13.66-5.66-.71.71M6.34 17.66l-.71.71m12.73.01-.71-.71M6.34 6.34l-.71-.71" />
      <rect x="2" y="2" width="20" height="20" rx="3" />
    </svg>
  ),
  shield: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  ),
  warning: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  ),
  clipboard: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <rect x="9" y="2" width="6" height="4" rx="1" /><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" /><path d="M12 11h4" /><path d="M12 16h4" /><path d="M8 11h.01" /><path d="M8 16h.01" />
    </svg>
  ),
  eye: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18} className={cls}>
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" />
    </svg>
  ),
  edit: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18} className={cls}>
      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" />
    </svg>
  ),
  trash: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18} className={cls}>
      <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  ),
  plus: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18} className={cls}>
      <line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" />
    </svg>
  ),
  fingerprint: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M2 12C2 6.5 6.5 2 12 2a10 10 0 0 1 8 4" /><path d="M5 19.5C5.5 18 6 15 6 12c0-.7.12-1.37.34-2" /><path d="M17.29 21.02c.12-.6.43-2.3.5-3.02" /><path d="M12 10a2 2 0 0 0-2 2c0 1.02-.1 2.51-.26 4" /><path d="M8.65 22c.21-.66.45-1.32.57-2" /><path d="M14 13.12c0 2.38 0 6.38-1 8.88" /><path d="M2 16h.01" /><path d="M21.8 16c.2-2 .131-5.354 0-6" /><path d="M9 6.8a6 6 0 0 1 9 5.2c0 .47 0 1.17-.02 2" />
    </svg>
  ),
  copy: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18} className={cls}>
      <rect x="9" y="9" width="13" height="13" rx="2" ry="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
    </svg>
  ),
  refresh: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18} className={cls}>
      <polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
    </svg>
  ),
  history: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" /><path d="M12 7v5l3 3" />
    </svg>
  ),
};

const KV_PAGE_SIZE_OPTIONS = [10, 20, 50, 100];

// ── Helpers ───────────────────────────────────────────────────────────

const fmtDate = (iso: string | null, tz?: string) => {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      year: "numeric", month: "short", day: "numeric",
      ...(tz ? { timeZone: tz } : {}),
    });
  } catch { return iso; }
};

const Badge: React.FC<{
  label: string;
  color: "green" | "red" | "yellow" | "blue" | "gray" | "purple";
}> = ({ label, color }) => {
  const colors: Record<string, string> = {
    green: "bg-green-100 text-green-800",
    red: "bg-red-100 text-red-800",
    yellow: "bg-yellow-100 text-yellow-800",
    blue: "bg-blue-100 text-blue-800",
    gray: "bg-gray-100 text-gray-800",
    purple: "bg-purple-100 text-purple-800",
  };
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${colors[color]}`}>
      {label}
    </span>
  );
};

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
}) => (
  <div className={gridStyles.panelHeader}>
    <div className="flex flex-wrap items-center gap-3">
      <span className={gridStyles.countBadge}>{countLabel}</span>
      <AutoRefreshIndicator />
    </div>
    <div className="ml-auto flex flex-wrap items-center justify-end gap-3">
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
      {primaryAction}
    </div>
  </div>
);

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

const GridIconButton: React.FC<{
  title: string;
  onClick: () => void;
  tone: "blue" | "red" | "gray" | "green";
  disabled?: boolean;
  children: React.ReactNode;
}> = ({ title, onClick, tone, disabled = false, children }) => {
  const tones: Record<string, string> = {
    blue: "text-blue-600 hover:bg-blue-50",
    red: "text-red-600 hover:bg-red-50",
    gray: "text-gray-600 hover:bg-gray-50",
    green: "text-green-600 hover:bg-green-50",
  };

  return (
    <button
      onClick={onClick}
      disabled={disabled}
      title={title}
      className={`p-2 rounded-lg disabled:opacity-50 ${tones[tone]}`}
    >
      {children}
    </button>
  );
};

// ── KPI Card ──────────────────────────────────────────────────────────

const KPICard: React.FC<{
  title: string; value: number | string; icon: React.ReactNode; color: string;
  subtitle?: string;
}> = ({ title, value, icon, color, subtitle }) => (
  <div className="relative overflow-hidden rounded-2xl border border-att-100 bg-gradient-to-br from-white via-white to-att-50/70 p-5 shadow-sm shadow-att-100/40">
    <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-att-300 via-att-500 to-att-300" />
    <div className="flex items-center gap-3">
      <div className={`flex h-11 w-11 items-center justify-center rounded-xl ring-1 ring-white/60 ${color}`}>
        {icon}
      </div>
      <div>
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">{title}</p>
        <p className="text-2xl font-bold text-slate-900">{value}</p>
        {subtitle && <p className="mt-0.5 text-xs text-slate-400">{subtitle}</p>}
      </div>
    </div>
  </div>
);

// ── Expiring Items Alert ──────────────────────────────────────────────

const ExpiringItemsTable: React.FC<{
  items: ExpiringItem[];
  totalCount?: number;
  onRefresh: () => void;
  refreshing: boolean;
  vaultUriByName: Record<string, string>;
  canWrite: boolean;
  onToast: (t: ToastState) => void;
}> = ({ items, totalCount, onRefresh, refreshing, vaultUriByName, canWrite, onToast }) => {
  const { timezone } = usePortalTimezone();
  const fmt = (iso: string | null) => fmtDate(iso, timezone);
  const [search, setSearch] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [pageSize, setPageSize] = React.useState(20);
  const [sort, setSort] = React.useState<SortState<"name" | "vault_name" | "type" | "expires" | "days_remaining">>({ key: "days_remaining", direction: "asc" });
  const [fixingName, setFixingName] = React.useState<string | null>(null);
  const [bulkFixing, setBulkFixing] = React.useState(false);
  // Track individually fixed secrets so bulk count drops immediately without waiting for server refresh
  const [fixedKeys, setFixedKeys] = React.useState<Set<string>>(new Set());

  const extendMutation = useExtendSecretExpiry();
  const bulkExtendMutation = useBulkExtendSecretExpiry();

  const _itemKey = (i: ExpiringItem) => `${i.vault_name}/${i.name}`;

  const filtered = items.filter(
    (item) =>
      (item.name || "").toLowerCase().includes(search.toLowerCase()) ||
      (item.vault_name || "").toLowerCase().includes(search.toLowerCase()) ||
      (item.type || "").toLowerCase().includes(search.toLowerCase())
  );
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

  // Exclude already-fixed items so the count drops immediately after each individual fix
  const expiring90Secrets = items.filter(
    (i) => i.type === "secret" && i.days_remaining <= 90 && !fixedKeys.has(_itemKey(i))
  );

  const handleFix = async (item: ExpiringItem) => {
    const vault_uri = vaultUriByName[item.vault_name];
    if (!vault_uri) {
      onToast({ type: "error", message: `Cannot find vault URI for ${item.vault_name}` });
      return;
    }
    setFixingName(item.name);
    try {
      await extendMutation.mutateAsync({ vault_uri, name: item.name });
      setFixedKeys((prev) => new Set(prev).add(_itemKey(item)));
      onToast({ type: "success", message: `Extended expiry for ${item.name} to today + 360 days` });
      onRefresh();
    } catch (e: unknown) {
      onToast({ type: "error", message: `Failed to extend ${item.name}: ${(e as Error).message}` });
    } finally {
      setFixingName(null);
    }
  };

  const handleBulkFix = async () => {
    if (!expiring90Secrets.length) return;
    setBulkFixing(true);
    try {
      const secrets = expiring90Secrets.map((i) => ({ vault_uri: vaultUriByName[i.vault_name] || "", name: i.name })).filter((s) => s.vault_uri);
      const result = await bulkExtendMutation.mutateAsync(secrets);
      // Mark all successfully fixed secrets so count drops to 0 immediately
      const successNames = new Set(
        result.results.filter((r) => r.status === "success").map((r) => {
          const item = expiring90Secrets.find((i) => i.name === r.name);
          return item ? _itemKey(item) : null;
        }).filter(Boolean) as string[]
      );
      setFixedKeys((prev) => new Set([...prev, ...successNames]));
      if (result.failed_count > 0) {
        onToast({ type: "error", message: `Bulk fix: ${result.success_count} succeeded, ${result.failed_count} failed` });
      } else {
        onToast({ type: "success", message: `Extended expiry for ${result.success_count} secret(s) to today + 360 days` });
      }
      onRefresh();
    } catch (e: unknown) {
      onToast({ type: "error", message: `Bulk fix failed: ${(e as Error).message}` });
    } finally {
      setBulkFixing(false);
    }
  };

  if (!items.length) {
    return (
      <div className="rounded-2xl border border-att-100 bg-gradient-to-br from-white to-att-50/50 p-6 shadow-sm">
        <h3 className="text-md font-semibold text-gray-700 mb-3">Expiring Items</h3>
        <p className="text-sm text-green-600">No items expiring within 90 days</p>
      </div>
    );
  }
  return (
    <div className={gridStyles.shell}>
      <div className="flex items-center justify-between gap-2 mb-2 flex-wrap">
        <GridToolbar
          search={search}
          onSearch={(value) => { setSearch(value); setPage(1); }}
          placeholder="Search expiring items..."
          countLabel={`${search ? filtered.length : (totalCount ?? filtered.length)} expiring within 90 days`}
          pageSize={pageSize}
          onPageSizeChange={(value) => { setPageSize(value); setPage(1); }}
          onRefresh={onRefresh}
          refreshing={refreshing}
        />
        {canWrite && expiring90Secrets.length > 0 && (
          <button
            onClick={handleBulkFix}
            disabled={bulkFixing}
            className="shrink-0 rounded-lg bg-att-700 px-4 py-1.5 text-sm font-medium text-white hover:bg-att-800 disabled:opacity-50 flex items-center gap-1.5"
          >
            {bulkFixing ? (
              <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/></svg>
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" width={14} height={14}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
            )}
            {bulkFixing ? "Fixing…" : `Bulk Fix ${expiring90Secrets.length} Secret${expiring90Secrets.length !== 1 ? "s" : ""} (+360d)`}
          </button>
        )}
      </div>
      <div className="overflow-auto max-h-64">
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              <th className={gridStyles.headerCell}><SortableHeader label="Name" active={sort.key === "name"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "name"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Vault" active={sort.key === "vault_name"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "vault_name"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Type" active={sort.key === "type"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "type"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Expires" active={sort.key === "expires"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "expires"))} /></th>
              <th className={gridStyles.headerCellCenter}><SortableHeader label="Days Left" active={sort.key === "days_remaining"} direction={sort.direction} onClick={() => setSort(nextSortState(sort, "days_remaining"))} align="center" /></th>
              {canWrite && <th className={gridStyles.headerCell}>Action</th>}
            </tr>
          </thead>
          <tbody>
            {paginated.map((item, i) => {
              const isFixable = item.type === "secret" && item.days_remaining <= 90 && !!vaultUriByName[item.vault_name];
              const isFixin = fixingName === item.name;
              return (
                <tr key={i} className={gridStyles.row}>
                  <td className={gridStyles.strongCell}>{item.name}</td>
                  <td className={gridStyles.cell}>{item.vault_name}</td>
                  <td className={gridStyles.cell}>
                    <Badge
                      label={item.type}
                      color={item.type === "certificate" ? "purple" : item.type === "key" ? "blue" : "gray"}
                    />
                  </td>
                  <td className={gridStyles.cell}>{fmt(item.expires)}</td>
                  <td className={gridStyles.centerCell}>
                    <Badge
                      label={`${item.days_remaining}d`}
                      color={item.days_remaining <= 7 ? "red" : item.days_remaining <= 30 ? "yellow" : item.days_remaining <= 90 ? "blue" : "gray"}
                    />
                  </td>
                  {canWrite && (
                    <td className={gridStyles.cell}>
                      {isFixable && (
                        <button
                          onClick={() => handleFix(item)}
                          disabled={isFixin || bulkFixing}
                          className="rounded px-2 py-0.5 text-xs font-medium bg-green-100 text-green-700 hover:bg-green-200 disabled:opacity-50 flex items-center gap-1"
                          title="Update expiry to current expiry + 360 days"
                        >
                          {isFixin ? (
                            <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z"/></svg>
                          ) : null}
                          {isFixin ? "Fixing…" : "Fix (+360d)"}
                        </button>
                      )}
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <GridPagination page={safePage} totalPages={totalPages} totalItems={filtered.length} pageSize={pageSize} onPageChange={setPage} />
    </div>
  );
};

// ── Vault Summary Cards ───────────────────────────────────────────────

const VaultSummaryTable: React.FC<{
  vaults: VaultSummary[];
  onSelect: (name: string) => void;
  selectedVault: string | null;
  onRefresh: () => void;
  refreshing: boolean;
  canWrite: boolean;
  onSyncVault?: (vaultName: string, vaultUri: string) => void;
  syncingVault?: string | null;
}> = ({ vaults, onSelect, selectedVault, onRefresh, refreshing, canWrite, onSyncVault, syncingVault }) => {
  const [search, setSearch] = React.useState("");
  const [page, setPage] = React.useState(1);
  const [pageSize, setPageSize] = React.useState(20);
  const [sort, setSort] = React.useState<SortState<"name" | "location" | "secrets_count" | "keys_count" | "certificates_count">>({ key: "name", direction: "asc" });
  const filtered = vaults.filter(
    (v) =>
      (v.name || "").toLowerCase().includes(search.toLowerCase()) ||
      (v.location || "").toLowerCase().includes(search.toLowerCase())
  );
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
    <div className="overflow-auto max-h-64">
      <table className={gridStyles.table}>
        <thead className={gridStyles.head}>
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
              className={`${gridStyles.row} cursor-pointer transition ${
                selectedVault === v.name ? gridStyles.selectedRow : ""
              }`}
            >
              <td className={gridStyles.strongCell}>
                <span className="font-medium text-att-700">{v.name}</span>
              </td>
              <td className={gridStyles.cell}>{v.location}</td>
              <td className={gridStyles.centerCell}><span className="font-mono">{v.secrets_count}</span></td>
              <td className={gridStyles.centerCell}><span className="font-mono">{v.keys_count}</span></td>
              <td className={gridStyles.centerCell}><span className="font-mono">{v.certificates_count}</span></td>
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
                    <button
                      onClick={(e) => { e.stopPropagation(); onSyncVault?.(v.name, v.vault_uri); }}
                      disabled={syncingVault === v.name}
                      className="p-2 text-att-600 hover:bg-att-50 rounded-lg disabled:opacity-50"
                      title={`Sync ${v.name}`}
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={18} height={18} className={syncingVault === v.name ? "animate-spin" : ""}>
                        <polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" />
                      </svg>
                    </button>
                  </div>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
    <GridPagination page={safePage} totalPages={totalPages} totalItems={filtered.length} pageSize={pageSize} onPageChange={setPage} />
  </div>
  );
};

// ── Modal Overlay ─────────────────────────────────────────────────────

const Modal: React.FC<{
  title: string;
  onClose: () => void;
  wide?: boolean;
  children: React.ReactNode;
}> = ({ title, onClose, wide, children }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
    <div
      className={`bg-white rounded-2xl shadow-2xl ${wide ? "w-[720px]" : "w-[520px]"} max-h-[85vh] overflow-auto`}
      onClick={(e) => e.stopPropagation()}
    >
      <div className="flex items-center justify-between p-5 border-b border-gray-100">
        <h2 className="text-lg font-semibold text-gray-800">{title}</h2>
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 text-xl leading-none">&times;</button>
      </div>
      <div className="p-5">{children}</div>
    </div>
  </div>
);

// ── Secret Value Viewer (read-only with decode) ───────────────────────

const SecretValueViewer: React.FC<{
  vaultUri: string;
  secretName: string;
  onClose: () => void;
}> = ({ vaultUri, secretName, onClose }) => {
  const { timezone } = usePortalTimezone();
  const fmt = (iso: string | null) => fmtDate(iso, timezone);
  const { data, isLoading, isError, error } = useSecretValue(vaultUri, secretName);
  const [showDecoded, setShowDecoded] = useState(false);
  const [copied, setCopied] = useState<string | null>(null);

  const copyToClipboard = useCallback((text: string, label: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(label);
      setTimeout(() => setCopied(null), 2000);
    });
  }, []);

  // Try manual Base64 decode for display
  const manualDecode = useMemo(() => {
    if (!data?.value) return null;
    try {
      return atob(data.value);
    } catch {
      return null;
    }
  }, [data?.value]);

  const manualEncode = useMemo(() => {
    if (!data?.value) return null;
    try {
      return btoa(data.value);
    } catch {
      return null;
    }
  }, [data?.value]);

  return (
    <Modal title={`Secret: ${secretName}`} onClose={onClose} wide>
      {isLoading && <p className="text-gray-500 text-sm">Loading secret value...</p>}
      {isError && (
        <p className="text-red-500 text-sm">
          Failed to load secret value: {(error as any)?.response?.data?.detail || "Unknown error"}
        </p>
      )}
      {data && (
        <div className="space-y-4">
          {/* Metadata row */}
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div><span className="text-gray-500">Content Type:</span> <span className="font-medium">{data.content_type || "—"}</span></div>
            <div><span className="text-gray-500">Status:</span> <Badge label={data.enabled ? "Enabled" : "Disabled"} color={data.enabled ? "green" : "red"} /></div>
            <div><span className="text-gray-500">Created:</span> <span className="font-medium">{fmt(data.created)}</span></div>
            <div><span className="text-gray-500">Updated:</span> <span className="font-medium">{fmt(data.updated)}</span></div>
            <div><span className="text-gray-500">Not Before:</span> <span className="font-medium">{fmt(data.not_before)}</span></div>
            <div><span className="text-gray-500">Expires:</span> <span className="font-medium">{fmt(data.expires)}</span></div>
            <div><span className="text-gray-500">Auto-detected Base64:</span> <Badge label={data.is_base64 ? "Yes" : "No"} color={data.is_base64 ? "blue" : "gray"} /></div>
          </div>

          {/* Raw value */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-sm font-medium text-gray-700">Raw Value</label>
              <button
                onClick={() => copyToClipboard(data.value, "raw")}
                className="text-xs text-blue-600 hover:text-blue-800"
              >
                {copied === "raw" ? "✓ Copied!" : "Copy"}
              </button>
            </div>
            <textarea
              readOnly
              value={data.value}
              rows={3}
              className="w-full border border-gray-200 rounded-lg p-3 text-xs font-mono bg-gray-50 resize-y focus:outline-none"
            />
          </div>

          {/* Decode / Encode toggle */}
          <div className="flex gap-2 flex-wrap">
            {manualDecode && (
              <button
                onClick={() => setShowDecoded(true)}
                className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition ${
                  showDecoded
                    ? "bg-blue-600 text-white border-blue-600"
                    : "bg-white text-blue-700 border-blue-300 hover:bg-blue-50"
                }`}
              >
                Decode Base64
              </button>
            )}
            <button
              onClick={() => setShowDecoded(false)}
              className={`px-3 py-1.5 text-xs font-medium rounded-lg border transition ${
                !showDecoded
                  ? "bg-blue-600 text-white border-blue-600"
                  : "bg-white text-blue-700 border-blue-300 hover:bg-blue-50"
              }`}
            >
              Raw
            </button>
            {manualEncode && !data.is_base64 && (
              <button
                onClick={() => copyToClipboard(manualEncode, "encoded")}
                className="px-3 py-1.5 text-xs font-medium rounded-lg border bg-white text-purple-700 border-purple-300 hover:bg-purple-50 transition"
              >
                {copied === "encoded" ? "✓ Copied Base64!" : "Copy as Base64"}
              </button>
            )}
          </div>

          {/* Decoded value (if Base64) */}
          {showDecoded && manualDecode && (
            <div>
              <div className="flex items-center justify-between mb-1">
                <label className="text-sm font-medium text-gray-700">Decoded (Base64 → UTF-8)</label>
                <button
                  onClick={() => copyToClipboard(manualDecode, "decoded")}
                  className="text-xs text-blue-600 hover:text-blue-800"
                >
                  {copied === "decoded" ? "✓ Copied!" : "Copy"}
                </button>
              </div>
              <textarea
                readOnly
                value={manualDecode}
                rows={4}
                className="w-full border border-blue-200 rounded-lg p-3 text-xs font-mono bg-blue-50 resize-y focus:outline-none"
              />
            </div>
          )}

          {/* Server-side decoded value (Python) */}
          {data.is_base64 && data.decoded_value && !showDecoded && (
            <div className="bg-blue-50 border border-blue-200 rounded-lg p-3">
              <p className="text-xs text-blue-600 mb-1">This value is Base64-encoded. Click "Decode Base64" to see the decoded content.</p>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
};

// ── Create / Update Secret Dialog ─────────────────────────────────────

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
  const isEdit = !!editSecret;

  // Date fields — default: today → today + 360 days
  const todayStr = new Date().toISOString().slice(0, 10);
  const defaultExpiry = new Date(Date.now() + 360 * 86400000).toISOString().slice(0, 10);
  const [notBefore, setNotBefore] = useState(todayStr);
  const [expiresDate, setExpiresDate] = useState(defaultExpiry);

  // Live Base64 decode preview
  const handleValueChange = useCallback((v: string) => {
    setValue(v);
    if (decodeInput) {
      try {
        setDecodedPreview(atob(v));
      } catch {
        setDecodedPreview(null);
      }
    }
  }, [decodeInput]);

  const toggleDecodeInput = useCallback(() => {
    setDecodeInput((prev) => {
      const next = !prev;
      if (next) {
        try { setDecodedPreview(atob(value)); } catch { setDecodedPreview(null); }
      } else {
        setDecodedPreview(null);
      }
      return next;
    });
  }, [value]);

  const handleSubmit = () => {
    if (!name.trim() || !value.trim()) return;
    createMutation.mutate(
      {
        vault_uri: vaultUri,
        name: name.trim(),
        value: value.trim(),
        content_type: contentType.trim() || undefined,
        encode_base64: encodeBase64,
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
    <Modal title={isEdit ? `Update Secret: ${editSecret.name}` : "Create New Secret"} onClose={onClose}>
      <div className="space-y-4">
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

        {/* Value */}
        <div>
          <div className="flex items-center justify-between mb-1">
            <label className="block text-sm font-medium text-gray-700">Secret Value</label>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={toggleDecodeInput}
                className={`text-xs px-2 py-0.5 rounded border transition ${
                  decodeInput
                    ? "bg-blue-100 text-blue-700 border-blue-300"
                    : "bg-gray-50 text-gray-500 border-gray-200 hover:bg-gray-100"
                }`}
              >
                {decodeInput ? "✓ Decoding Preview" : "Preview Base64 Decode"}
              </button>
            </div>
          </div>
          <textarea
            value={value}
            onChange={(e) => handleValueChange(e.target.value)}
            rows={4}
            placeholder={isEdit ? "Enter new value..." : "Enter secret value..."}
            className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
          />
        </div>

        {/* Decoded preview */}
        {decodeInput && decodedPreview !== null && (
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
        {decodeInput && value && decodedPreview === null && (
          <p className="text-xs text-red-500">Not valid Base64 — cannot decode</p>
        )}

        {/* Encode Base64 option */}
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
              {(createMutation.error as any)?.response?.data?.detail || "Failed to save secret"}
            </p>
          </div>
        )}

        {/* Actions */}
        <div className="flex justify-end gap-2 pt-2">
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
            {createMutation.isPending ? "Saving..." : isEdit ? "Update Secret" : "Create Secret"}
          </button>
        </div>
      </div>
    </Modal>
  );
};

// ── Secrets Tab ───────────────────────────────────────────────────────

const SecretsTab: React.FC<{ vaultUri: string | null }> = ({ vaultUri }) => {
  const { timezone } = usePortalTimezone();
  const { canWrite } = useAuth();
  const fmt = (iso: string | null) => fmtDate(iso, timezone);
  const { data: secrets, isLoading, isError, error } = useVaultSecrets(vaultUri);
  const queryClient = useQueryClient();
  const deleteMutation = useDeleteSecret();
  const [search, setSearch] = useState("");
  const [viewingSecret, setViewingSecret] = useState<string | null>(null);
  const [editingSecret, setEditingSecret] = useState<SecretInfo | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [sort, setSort] = useState<SortState<"name" | "content_type" | "enabled" | "updated" | "not_before" | "expires">>({ key: "name", direction: "asc" });
  const [toast, setToast] = useState<ToastState | null>(null);
  const showToast = useCallback((message: string, type: ToastState["type"] = "success") => setToast({ message, type }), []);
  const filtered = (secrets || []).filter(
    (s: SecretInfo) => !search || s.name.toLowerCase().includes(search.toLowerCase())
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
          <span className={refreshing ? "animate-spin" : ""} dangerouslySetInnerHTML={{ __html: Icons.refresh }} />
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
        placeholder="Search secrets..."
        countLabel={`${filtered.length} secrets`}
        pageSize={pageSize}
        onPageSizeChange={(value) => { setPageSize(value); setPage(1); }}
        onRefresh={handleRefresh}
        refreshing={refreshing}
        primaryAction={canWrite ?
          <button
            onClick={() => { setShowCreate(true); setEditingSecret(null); }}
            className="inline-flex items-center gap-2 rounded-xl bg-att-600 px-3 py-2 text-sm font-semibold text-white transition hover:bg-att-700"
          >
            {Icons.plus()} Add Secret
          </button>
        : undefined}
      />

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
              <tr key={s.name} className={gridStyles.row}>
                <td className={`${gridStyles.strongCell} font-mono text-xs`}>{s.name}</td>
                <td className={`${gridStyles.cell} text-xs`}>{s.content_type || "—"}</td>
                <td className={gridStyles.cell}>
                  <Badge label={s.enabled ? "Enabled" : "Disabled"} color={s.enabled ? "green" : "red"} />
                </td>
                <td className={`${gridStyles.cell} text-xs`}>{fmt(s.updated)}</td>
                <td className={`${gridStyles.cell} text-xs`}>{fmt(s.not_before)}</td>
                <td className={`${gridStyles.cell} text-xs`}>{fmt(s.expires)}</td>
                <td className={gridStyles.centerCell}>
                  <div className="flex justify-center gap-1">
                    <GridIconButton onClick={() => setViewingSecret(s.name)} title="View secret" tone="blue">{Icons.eye()}</GridIconButton>
                    {canWrite && <GridIconButton onClick={() => setEditingSecret(s)} title="Update secret" tone="blue">{Icons.edit()}</GridIconButton>}
                    {canWrite && <GridIconButton onClick={() => setConfirmDelete(s.name)} title="Delete secret" tone="red">{Icons.trash()}</GridIconButton>}
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="py-6 text-center text-sm text-slate-400">No secrets found</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <GridPagination page={safePage} totalPages={totalPages} totalItems={filtered.length} pageSize={pageSize} onPageChange={setPage} />

      {/* View Secret Modal */}
      {viewingSecret && vaultUri && (
        <SecretValueViewer
          vaultUri={vaultUri}
          secretName={viewingSecret}
          onClose={() => setViewingSecret(null)}
        />
      )}

      {/* Create Secret Modal */}
      {showCreate && vaultUri && (
        <SecretFormDialog
          vaultUri={vaultUri}
          onClose={() => setShowCreate(false)}
          onSuccess={() => showToast("Secret created successfully")}
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

// ── Key Value Viewer (read-only detail) ───────────────────────────────

const KeyValueViewer: React.FC<{
  vaultUri: string;
  keyName: string;
  onClose: () => void;
}> = ({ vaultUri, keyName, onClose }) => {
  const { timezone } = usePortalTimezone();
  const fmt = (iso: string | null) => fmtDate(iso, timezone);
  const { data, isLoading, isError, error } = useKeyDetail(vaultUri, keyName);
  const [copied, setCopied] = useState<string | null>(null);

  const copyToClipboard = useCallback((text: string, label: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(label);
      setTimeout(() => setCopied(null), 2000);
    });
  }, []);

  return (
    <Modal title={`Key: ${keyName}`} onClose={onClose} wide>
      {isLoading && <p className="text-gray-500 text-sm">Loading key details...</p>}
      {isError && (
        <p className="text-red-500 text-sm">
          Failed to load key: {(error as any)?.response?.data?.detail || "Unknown error"}
        </p>
      )}
      {data && (
        <div className="space-y-4">
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div><span className="text-gray-500">Key Type:</span> <span className="font-medium font-mono">{data.kty || "—"}</span></div>
            <div><span className="text-gray-500">Status:</span> <Badge label={data.enabled ? "Enabled" : "Disabled"} color={data.enabled ? "green" : "red"} /></div>
            <div><span className="text-gray-500">Created:</span> <span className="font-medium">{fmt(data.created)}</span></div>
            <div><span className="text-gray-500">Updated:</span> <span className="font-medium">{fmt(data.updated)}</span></div>
            <div><span className="text-gray-500">Not Before:</span> <span className="font-medium">{fmt(data.not_before)}</span></div>
            <div><span className="text-gray-500">Expires:</span> <span className="font-medium">{fmt(data.expires)}</span></div>
            {data.key_size && <div><span className="text-gray-500">Key Size:</span> <span className="font-medium">{data.key_size} bits</span></div>}
            {data.crv && <div><span className="text-gray-500">Curve:</span> <span className="font-medium">{data.crv}</span></div>}
            <div><span className="text-gray-500">Recovery Level:</span> <span className="font-medium">{data.recovery_level || "—"}</span></div>
          </div>

          {/* Key Operations */}
          {data.key_ops && data.key_ops.length > 0 && (
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">Allowed Operations</label>
              <div className="flex gap-1 flex-wrap">
                {data.key_ops.map((op) => (
                  <Badge key={op} label={op} color="blue" />
                ))}
              </div>
            </div>
          )}

          {/* Key ID */}
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="text-sm font-medium text-gray-700">Key ID</label>
              <button
                onClick={() => copyToClipboard(data.kid, "kid")}
                className="text-xs text-blue-600 hover:text-blue-800 flex items-center gap-1"
              >
                {Icons.copy()} {copied === "kid" ? "Copied!" : "Copy"}
              </button>
            </div>
            <div className="w-full border border-gray-200 rounded-lg p-3 text-xs font-mono bg-gray-50 break-all">
              {data.kid}
            </div>
          </div>

          {/* Tags */}
          {data.tags && Object.keys(data.tags).length > 0 && (
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">Tags</label>
              <div className="flex gap-1 flex-wrap">
                {Object.entries(data.tags).map(([k, v]) => (
                  <span key={k} className="px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-700">{k}: {v}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Modal>
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
  const isEdit = !!editKey;

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
        key_ops: keyOps.length > 0 ? keyOps : undefined,
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
    <Modal title={isEdit ? `Update Key: ${editKey.name}` : "Create New Key"} onClose={onClose}>
      <div className="space-y-4">
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
            <p className="text-sm text-red-700">{(createMutation.error as any)?.response?.data?.detail || "Failed to create key"}</p>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button onClick={onClose} className="px-4 py-2 text-sm text-gray-600 bg-gray-100 rounded-lg hover:bg-gray-200 transition">Cancel</button>
          <button
            onClick={handleSubmit}
            disabled={!name.trim() || createMutation.isPending}
            className="px-4 py-2 text-sm text-white bg-blue-600 rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
          >
            {createMutation.isPending ? "Creating..." : isEdit ? "Update Key" : "Create Key"}
          </button>
        </div>
      </div>
    </Modal>
  );
};

// ── Keys Tab ──────────────────────────────────────────────────────────

const KeysTab: React.FC<{ vaultUri: string | null }> = ({ vaultUri }) => {
  const { timezone } = usePortalTimezone();
  const { canWrite } = useAuth();
  const fmt = (iso: string | null) => fmtDate(iso, timezone);
  const queryClient = useQueryClient();
  const { data: keys, isLoading, isError, error } = useVaultKeys(vaultUri);
  const deleteMutation = useDeleteKey();
  const [search, setSearch] = useState("");
  const [viewingKey, setViewingKey] = useState<string | null>(null);
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
          <span className={refreshing ? "animate-spin" : ""} dangerouslySetInnerHTML={{ __html: Icons.refresh }} />
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
              <tr key={k.name} className={gridStyles.row}>
                <td className={`${gridStyles.strongCell} font-mono text-xs`}>{k.name}</td>
                <td className={gridStyles.cell}>
                  <Badge label={k.enabled ? "Enabled" : "Disabled"} color={k.enabled ? "green" : "red"} />
                </td>
                <td className={`${gridStyles.cell} text-xs`}>{fmt(k.updated)}</td>
                <td className={`${gridStyles.cell} text-xs`}>{fmt(k.not_before)}</td>
                <td className={`${gridStyles.cell} text-xs`}>{fmt(k.expires)}</td>
                <td className={gridStyles.centerCell}>{k.managed ? "Yes" : "—"}</td>
                <td className={gridStyles.centerCell}>
                  <div className="flex justify-center gap-1">
                    <GridIconButton onClick={() => setViewingKey(k.name)} title="View key" tone="blue">{Icons.eye()}</GridIconButton>
                    {canWrite && <GridIconButton onClick={() => setEditingKey(k)} title="Update key" tone="blue">{Icons.edit()}</GridIconButton>}
                    {canWrite && <GridIconButton onClick={() => setConfirmDelete(k.name)} title="Delete key" tone="red">{Icons.trash()}</GridIconButton>}
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

      {viewingKey && vaultUri && <KeyValueViewer vaultUri={vaultUri} keyName={viewingKey} onClose={() => setViewingKey(null)} />}
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

// ── Certificate Detail Viewer ─────────────────────────────────────────

const CertificateDetailViewer: React.FC<{
  vaultUri: string;
  certName: string;
  onClose: () => void;
}> = ({ vaultUri, certName, onClose }) => {
  const { timezone } = usePortalTimezone();
  const fmt = (iso: string | null) => fmtDate(iso, timezone);
  const { data, isLoading, isError, error } = useCertificateDetail(vaultUri, certName);
  const [copied, setCopied] = useState<string | null>(null);

  const copyToClipboard = useCallback((text: string, label: string) => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(label);
      setTimeout(() => setCopied(null), 2000);
    });
  }, []);

  return (
    <Modal title={`Certificate: ${certName}`} onClose={onClose} wide>
      {isLoading && <p className="text-gray-500 text-sm">Loading certificate details...</p>}
      {isError && (
        <p className="text-red-500 text-sm">
          Failed to load certificate: {(error as any)?.response?.data?.detail || "Unknown error"}
        </p>
      )}
      {data && (
        <div className="space-y-4">
          {/* Identity Section */}
          <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
            <h4 className="text-sm font-semibold text-blue-800 mb-2 flex items-center gap-2">{Icons.fingerprint("text-blue-600")} Certificate Identity</h4>
            <div className="grid grid-cols-1 gap-2 text-sm">
              <div>
                <span className="text-blue-600 font-medium">Common Name (CN):</span>
                <span className="ml-2 font-mono font-bold text-gray-900">{data.cn_name || "—"}</span>
              </div>
              <div>
                <span className="text-blue-600 font-medium">Subject:</span>
                <span className="ml-2 font-mono text-gray-800 text-xs">{data.subject || "—"}</span>
              </div>
              {data.san && data.san.length > 0 && (
                <div>
                  <span className="text-blue-600 font-medium">Subject Alternative Names (SAN):</span>
                  <div className="mt-1 flex gap-1 flex-wrap">
                    {data.san.map((s, i) => (
                      <span key={i} className="px-2 py-0.5 rounded text-xs bg-blue-100 text-blue-800 font-mono">{s}</span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Thumbprint Section */}
          <div className="bg-purple-50 border border-purple-200 rounded-lg p-4">
            <h4 className="text-sm font-semibold text-purple-800 mb-2 flex items-center gap-2">{Icons.shield("text-purple-600")} Thumbprint</h4>
            <div className="space-y-2 text-sm">
              <div className="flex items-center justify-between">
                <div>
                  <span className="text-purple-600 font-medium">SHA-1:</span>
                  <span className="ml-2 font-mono text-xs text-gray-800 break-all">{data.thumbprint || "—"}</span>
                </div>
                {data.thumbprint && (
                  <button onClick={() => copyToClipboard(data.thumbprint, "sha1")} className="text-xs text-purple-600 hover:text-purple-800 flex items-center gap-1 ml-2 shrink-0">
                    {Icons.copy()} {copied === "sha1" ? "Copied!" : "Copy"}
                  </button>
                )}
              </div>
              {data.thumbprint_sha256 && (
                <div className="flex items-center justify-between">
                  <div>
                    <span className="text-purple-600 font-medium">SHA-256:</span>
                    <span className="ml-2 font-mono text-xs text-gray-800 break-all">{data.thumbprint_sha256}</span>
                  </div>
                  <button onClick={() => copyToClipboard(data.thumbprint_sha256!, "sha256")} className="text-xs text-purple-600 hover:text-purple-800 flex items-center gap-1 ml-2 shrink-0">
                    {Icons.copy()} {copied === "sha256" ? "Copied!" : "Copy"}
                  </button>
                </div>
              )}
              {data.serial_number && (
                <div>
                  <span className="text-purple-600 font-medium">Serial Number:</span>
                  <span className="ml-2 font-mono text-xs text-gray-800">{data.serial_number}</span>
                </div>
              )}
            </div>
          </div>

          {/* Metadata Grid */}
          <div className="grid grid-cols-2 gap-3 text-sm">
            <div><span className="text-gray-500">Status:</span> <Badge label={data.enabled ? "Enabled" : "Disabled"} color={data.enabled ? "green" : "red"} /></div>
            <div><span className="text-gray-500">Issuer:</span> <span className="font-medium">{data.issuer_cn || data.issuer_name || "—"}</span></div>
            <div><span className="text-gray-500">Created:</span> <span className="font-medium">{fmt(data.created)}</span></div>
            <div><span className="text-gray-500">Updated:</span> <span className="font-medium">{fmt(data.updated)}</span></div>
            <div><span className="text-gray-500">Not Before:</span> <span className="font-medium">{fmt(data.not_before)}</span></div>
            <div><span className="text-gray-500">Expires:</span> <span className="font-medium font-mono">{fmt(data.expires)}</span></div>
            {data.validity_months && <div><span className="text-gray-500">Validity:</span> <span className="font-medium">{data.validity_months} months</span></div>}
            <div><span className="text-gray-500">Auto-Renew:</span> <Badge label={data.auto_renew ? "Yes" : "No"} color={data.auto_renew ? "green" : "gray"} /></div>
            {data.key_type && <div><span className="text-gray-500">Key Type:</span> <span className="font-medium">{data.key_type}</span></div>}
            {data.key_size && <div><span className="text-gray-500">Key Size:</span> <span className="font-medium">{data.key_size} bits</span></div>}
          </div>

          {/* Key Usage */}
          {data.key_usage && data.key_usage.length > 0 && (
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">Key Usage</label>
              <div className="flex gap-1 flex-wrap">
                {data.key_usage.map((u) => <Badge key={u} label={u} color="blue" />)}
              </div>
            </div>
          )}

          {/* Tags */}
          {data.tags && Object.keys(data.tags).length > 0 && (
            <div>
              <label className="text-sm font-medium text-gray-700 mb-1 block">Tags</label>
              <div className="flex gap-1 flex-wrap">
                {Object.entries(data.tags).map(([k, v]) => (
                  <span key={k} className="px-2 py-0.5 rounded text-xs bg-gray-100 text-gray-700">{k}: {v}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
};

// ── Certificates Tab ──────────────────────────────────────────────────

const CertificatesTab: React.FC<{ vaultUri: string | null }> = ({ vaultUri }) => {
  const { timezone } = usePortalTimezone();
  const fmt = (iso: string | null) => fmtDate(iso, timezone);
  const queryClient = useQueryClient();
  const { data: certs, isLoading, isError, error } = useVaultCertificates(vaultUri);
  const [search, setSearch] = useState("");
  const [viewingCert, setViewingCert] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [sort, setSort] = useState<SortState<"name" | "cn_name" | "san" | "serial_number" | "enabled" | "expires">>({ key: "expires", direction: "asc" });
  const filtered = (certs || []).filter(
    (c: CertificateInfo) => !search || c.name.toLowerCase().includes(search.toLowerCase())
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
          <span className={refreshing ? "animate-spin" : ""} dangerouslySetInnerHTML={{ __html: Icons.refresh }} />
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

  return (
    <div className={gridStyles.shell}>
      <GridToolbar
        search={search}
        onSearch={(value) => { setSearch(value); setPage(1); }}
        placeholder="Search certificates..."
        countLabel={`${filtered.length} certificates`}
        pageSize={pageSize}
        onPageSizeChange={(value) => { setPageSize(value); setPage(1); }}
        onRefresh={handleRefresh}
        refreshing={refreshing}
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
            {paginated.map((c: CertificateInfo) => (
              <tr key={c.name} className={gridStyles.row}>
                <td className={`${gridStyles.strongCell} font-mono text-xs`}>{c.name}</td>
                <td className={`${gridStyles.cell} max-w-[180px] truncate font-mono text-xs`} title={c.cn_name || ""}>{c.cn_name || "—"}</td>
                <td className={`${gridStyles.cell} max-w-[200px] text-xs`}>
                  {c.san && c.san.length > 0 ? (
                    <div className="flex gap-1 flex-wrap">
                      {c.san.slice(0, 2).map((s, i) => (
                        <span key={i} className="px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 font-mono text-[10px]">{s}</span>
                      ))}
                      {c.san.length > 2 && (
                        <span className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 text-[10px]">+{c.san.length - 2} more</span>
                      )}
                    </div>
                  ) : <span className="text-gray-400">—</span>}
                </td>
                <td className={`${gridStyles.cell} max-w-[140px] truncate font-mono text-xs`} title={c.serial_number || ""}>{c.serial_number || "—"}</td>
                <td className={gridStyles.cell}>
                  <Badge label={c.enabled ? "Enabled" : "Disabled"} color={c.enabled ? "green" : "red"} />
                </td>
                <td className={`${gridStyles.cell} text-xs`}>{fmt(c.expires)}</td>
                <td className={gridStyles.centerCell}>
                  <div className="flex justify-center gap-1">
                    <GridIconButton onClick={() => setViewingCert(c.name)} title="View certificate" tone="blue">{Icons.eye()}</GridIconButton>
                  </div>
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={7} className="py-6 text-center text-sm text-slate-400">No certificates found</td></tr>
            )}
          </tbody>
        </table>
      </div>
      <GridPagination page={safePage} totalPages={totalPages} totalItems={filtered.length} pageSize={pageSize} onPageChange={setPage} />

      {viewingCert && vaultUri && (
        <CertificateDetailViewer vaultUri={vaultUri} certName={viewingCert} onClose={() => setViewingCert(null)} />
      )}
    </div>
  );
};

const AuditHistoryTab: React.FC<{ vaultUri: string | null; vaultName: string | null }> = ({ vaultUri, vaultName }) => {
  const { timezone } = usePortalTimezone();
  const fmt = (iso: string | null) => {
    if (!iso) return "—";
    try {
      return new Date(iso).toLocaleString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric",
        hour: "numeric",
        minute: "2-digit",
        ...(timezone ? { timeZone: timezone } : {}),
      });
    } catch {
      return iso;
    }
  };
  const { data, isLoading, isError, error, refetch, isFetching } = useKeyVaultAuditHistory(vaultUri);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "success" | "failed">("all");
  const [resourceFilter, setResourceFilter] = useState<"all" | "secret" | "key">("all");
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
      return matchesSearch && matchesStatus && matchesResource;
    });
  }, [entries, resourceFilter, search, statusFilter]);
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

  const actionBadge = (action: string) => {
    if (action.startsWith("create")) return <Badge label="Create" color="green" />;
    if (action.startsWith("update")) return <Badge label="Update" color="blue" />;
    if (action.startsWith("delete")) return <Badge label="Delete" color="red" />;
    return <Badge label={action} color="gray" />;
  };

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
          <span className="text-xs text-slate-500">Tracks create, update, and delete operations for secrets and keys via the shared audit log.</span>
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
            value={resourceFilter}
            onChange={(event) => {
              setResourceFilter(event.target.value as "all" | "secret" | "key");
              setPage(1);
            }}
            className={gridSelectStyles}
          >
            <option value="all">All resources</option>
            <option value="secret">Secrets</option>
            <option value="key">Keys</option>
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
              <tr key={entry.id} className={gridStyles.row}>
                <td className={`${gridStyles.cell} text-xs whitespace-nowrap`}>{fmt(entry.timestamp)}</td>
                <td className={gridStyles.cell}>{actionBadge(entry.action)}</td>
                <td className={gridStyles.cell}>
                  <Badge label={entry.resource_type === "secret" ? "Secret" : "Key"} color={entry.resource_type === "secret" ? "blue" : "purple"} />
                </td>
                <td className={`${gridStyles.strongCell} font-mono text-xs`}>{entry.resource_name}</td>
                <td className={gridStyles.cell}>
                  <Badge label={entry.status === "success" ? "Success" : "Failed"} color={entry.status === "success" ? "green" : "red"} />
                </td>
                <td className={`${gridStyles.cell} text-xs`}>{entry.user_email || entry.user_id}</td>
                <td className={`${gridStyles.cell} text-xs text-slate-600`}>{entry.summary}</td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr>
                <td colSpan={7} className="py-8 text-center text-sm text-slate-400">No CRUD audit entries found for this vault.</td>
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

const KeyVaultPage: React.FC = () => {
  const queryClient = useQueryClient();
  const { canWrite } = useAuth();
  const { data: dashboard, isLoading, isError, error } = useKeyVaultDashboard();
  const { data: vaults } = useKeyVaults();
  const { data: syncStatuses } = useKeyVaultSyncStatus(1);
  const syncMutation = useKeyVaultSync();
  const vaultSyncMutation = useKeyVaultSyncVault();
  const [selectedVault, setSelectedVault] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<TabKey>("secrets");
  const [refreshingDashboard, setRefreshingDashboard] = useState(false);
  const [syncingVault, setSyncingVault] = useState<string | null>(null);
  const [toast, setToast] = useState<ToastState | null>(null);
  const showToast = useCallback((message: string, type: ToastState["type"] = "success") => setToast({ message, type }), []);

  const latestSync = syncStatuses?.[0] ?? null;
  const isSyncing = latestSync?.status === "running" || syncMutation.isPending;


  // Derive vault_uri from selected vault name
  const selectedVaultUri = vaults?.find((v: KeyVaultInfo) => v.name === selectedVault)?.vault_uri || null;

  const handleDashboardRefresh = async () => {
    setRefreshingDashboard(true);
    try {
      const fresh = await refreshKeyVaultDashboard();
      queryClient.setQueryData(["keyvault", "dashboard"], fresh);
    } catch { /* ignore */ }
    setRefreshingDashboard(false);
  };

  const handleSyncVault = (vaultName: string, vaultUri: string) => {
    setSyncingVault(vaultName);
    vaultSyncMutation.mutate(
      { vaultName, vaultUri },
      {
        onSuccess: () => {
          showToast(`Vault "${vaultName}" synced successfully`);
          setSyncingVault(null);
        },
        onError: (e: unknown) => {
          const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail || "Vault sync failed";
          showToast(detail, "error");
          setSyncingVault(null);
        },
      },
    );
  };



  if (isLoading) {
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
          Failed to load Key Vault data: {(error as Error)?.message || "Unknown error"}
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
  const tabs: { key: TabKey; label: string; icon: React.ReactNode }[] = [
    { key: "secrets", label: "Secrets", icon: Icons.secret("text-green-600") },
    { key: "keys", label: "Keys", icon: Icons.key("text-purple-600") },
    { key: "certificates", label: "Certificates", icon: Icons.certificate("text-indigo-600") },
    { key: "audit", label: "Audit History", icon: Icons.history("text-att-700") },
  ];

  return (
    <div className="space-y-6 py-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Azure Key Vault</h1>
          <p className="mt-1 text-sm text-gray-500">
            Manage secrets, keys, and certificates across all monitored subscriptions
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Sync status indicator */}
          {latestSync && (
            <div className="text-right text-xs text-gray-500">
              {isSyncing ? (
                <span className="flex items-center gap-1 text-blue-600">
                  <svg className="animate-spin h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M21 12a9 9 0 1 1-6.219-8.56" /></svg>
                  Syncing…
                </span>
              ) : (
                <span className="flex items-center gap-1">
                  {latestSync.status === "completed" ? (
                    <svg className="h-3.5 w-3.5 text-green-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 6L9 17l-5-5" /></svg>
                  ) : latestSync.status === "partial" ? (
                    <svg className="h-3.5 w-3.5 text-amber-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>
                  ) : latestSync.status === "failed" ? (
                    <svg className="h-3.5 w-3.5 text-red-500" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="10" /><line x1="15" y1="9" x2="9" y2="15" /><line x1="9" y1="9" x2="15" y2="15" /></svg>
                  ) : null}
                  Last synced: {latestSync.completed_at
                    ? new Date(latestSync.completed_at).toLocaleTimeString()
                    : "never"}
                </span>
              )}
              {(latestSync.status === "completed" || latestSync.status === "partial") && (
                <span className="block text-gray-400 mt-0.5">
                  {latestSync.vaults_synced}V · {latestSync.secrets_synced}S · {latestSync.keys_synced}K · {latestSync.certificates_synced}C
                  {latestSync.error_message && (
                    <span className="block text-amber-500 text-[10px]" title={latestSync.error_message}>
                      {latestSync.error_message.length > 60 ? latestSync.error_message.slice(0, 60) + "…" : latestSync.error_message}
                    </span>
                  )}
                </span>
              )}
            </div>
          )}
          {canWrite && (
          <button
            onClick={() => syncMutation.mutate()}
            disabled={isSyncing}
            className="inline-flex items-center gap-1.5 rounded-lg border border-blue-300 bg-blue-50 px-3 py-1.5 text-sm font-medium text-blue-700 transition hover:bg-blue-100 disabled:cursor-not-allowed disabled:opacity-50"
            title="Sync all vault data from Azure to local database"
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

      {/* KPI Row */}
      <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
        <KPICard title="Vaults" value={d.total_vaults} icon={Icons.vault("text-blue-600")} color="bg-blue-50" />
        <KPICard title="Secrets" value={d.total_secrets} icon={Icons.secret("text-green-600")} color="bg-green-50" />
        <KPICard title="Keys" value={d.total_keys} icon={Icons.key("text-purple-600")} color="bg-purple-50" />
        <KPICard title="Certificates" value={d.total_certificates} icon={Icons.certificate("text-indigo-600")} color="bg-indigo-50" />
        <KPICard
          title="Expiring (30d)"
          value={d.expiring_within_30_days}
          icon={Icons.warning("text-red-600")}
          color={d.expiring_within_30_days > 0 ? "bg-red-50" : "bg-gray-50"}
          subtitle="within 30 days"
        />
        <KPICard
          title="Expiring (90d)"
          value={d.expiring_within_90_days}
          icon={Icons.clipboard("text-yellow-600")}
          color={d.expiring_within_90_days > 0 ? "bg-yellow-50" : "bg-gray-50"}
          subtitle="within 90 days"
        />
      </div>

      {/* Expiring Items Alert */}
      <ExpiringItemsTable
        items={(d.expiring_items || []).filter((i) => i.days_remaining <= 90)}
        totalCount={d.expiring_within_90_days}
        onRefresh={handleDashboardRefresh}
        refreshing={refreshingDashboard}
        vaultUriByName={Object.fromEntries((d.vault_summaries || []).map((v) => [v.name, v.vault_uri]))}
        canWrite={canWrite}
        onToast={setToast}
      />

      {/* Vault Inventory */}
      <VaultSummaryTable
        vaults={d.vault_summaries}
        onSelect={setSelectedVault}
        selectedVault={selectedVault}
        onRefresh={handleDashboardRefresh}
        refreshing={refreshingDashboard}
        canWrite={canWrite}
        onSyncVault={handleSyncVault}
        syncingVault={syncingVault}
      />

      {/* Vault Details — Tabs */}
      {selectedVault && (
        <div className="rounded-3xl border border-att-100 bg-gradient-to-br from-white to-att-50/60 p-6 shadow-sm shadow-att-100/40">
          <div className="mb-4 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
            <h3 className="text-lg font-semibold text-slate-800">
              <span className="text-att-700">{selectedVault}</span>
              <span className="ml-2 font-mono text-sm font-normal text-slate-400">
                {selectedVaultUri}
              </span>
            </h3>
            <button
              onClick={() => setSelectedVault(null)}
              className="text-sm font-medium text-slate-400 transition hover:text-slate-600"
            >
              Close
            </button>
          </div>

          {/* Tab bar */}
          <div className="mb-4 border-b border-att-100">
            <nav className="flex flex-wrap gap-3">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
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

          {/* Tab content */}
          {activeTab === "secrets" && <SecretsTab vaultUri={selectedVaultUri} />}
          {activeTab === "keys" && <KeysTab vaultUri={selectedVaultUri} />}
          {activeTab === "certificates" && <CertificatesTab vaultUri={selectedVaultUri} />}
          {activeTab === "audit" && <AuditHistoryTab vaultUri={selectedVaultUri} vaultName={selectedVault} />}
        </div>
      )}

      {toast && <Toast message={toast.message} type={toast.type} onClose={() => setToast(null)} />}
    </div>
  );
};

export default KeyVaultPage;
