/**
 * Shared grid helpers for AKS extended resource tabs — aligned with AKSOperationsPage.
 */

import React, { useMemo, useState } from "react";
import { AutoRefreshIndicator, gridStyles, Spinner, type SortState } from "../../components/gridStyles";
import type { useAksBackgroundSync } from "../../services/aksApi";

export const AKS_PAGE_SIZE = 15;

type BackgroundSyncState = ReturnType<typeof useAksBackgroundSync>;

/** "Sync from Kubernetes" button — same look and behaviour as the Deployments tab. */
export function SyncFromKubernetesButton({
  sync,
  title,
  label = "Sync from Kubernetes",
}: {
  sync: BackgroundSyncState;
  title?: string;
  label?: string;
}) {
  return (
    <button
      type="button"
      onClick={() => sync.start(false)}
      disabled={sync.isRunning}
      title={title}
      className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 text-sm disabled:opacity-50"
    >
      <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={sync.isRunning ? "w-4 h-4 animate-spin" : "w-4 h-4"}>
        <polyline points="23 4 23 10 17 10" /><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10" />
      </svg>
      {sync.isRunning ? "Syncing…" : label}
    </button>
  );
}

/** Source / last-sync row shown under the Deployments toolbar, shared by DB-cached tabs. */
export function CachedSyncStatus({
  source,
  lastSync,
  sync,
  formatDate,
}: {
  source?: string;
  lastSync?: string | null;
  sync: BackgroundSyncState;
  formatDate: (value: string) => string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* No badge until a response arrives — an unloaded grid is not "Kubernetes Live". */}
      {source && (
        <span className={`px-2 py-1 rounded-full text-xs font-medium ${source === "db" ? "bg-blue-100 text-blue-700" : "bg-green-100 text-green-700"}`}>
          Source: {source === "db" ? "Database" : "Kubernetes Live"}
        </span>
      )}
      {lastSync ? (
        <span className="text-sm text-gray-500">Last synced: {formatDate(lastSync)}</span>
      ) : (
        <span className="text-sm text-yellow-600">Not synced yet — cached table will update after background refresh</span>
      )}
      {sync.isRetrying && <span className="text-sm text-amber-600">Refresh delayed, retrying...</span>}
      {!sync.isRunning && sync.error && <span className="text-sm text-red-600">{sync.error}</span>}
    </div>
  );
}

export function useSearchPagination<T>(items: T[], searchFn: (item: T, q: string) => boolean) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);

  const filtered = useMemo(() => {
    if (!search.trim()) return items;
    const q = search.toLowerCase();
    return items.filter((item) => searchFn(item, q));
  }, [items, search, searchFn]);

  const totalPages = Math.max(1, Math.ceil(filtered.length / AKS_PAGE_SIZE));
  const safePage = Math.min(page, totalPages);
  const paged = filtered.slice((safePage - 1) * AKS_PAGE_SIZE, safePage * AKS_PAGE_SIZE);

  return { search, setSearch, page: safePage, setPage, paged, filtered, totalPages };
}

/**
 * Sorting for the AKS resource grids. `accessor` maps a row + column key to a
 * comparable value; strings compare with localeCompare, numbers numerically.
 */
export function useGridSort<T, K extends string>(
  items: T[],
  accessor: (item: T, key: K) => string | number,
  initial: SortState<K>,
) {
  const [sort, setSort] = useState<SortState<K>>(initial);
  const sorted = useMemo(() => {
    const dir = sort.direction === "asc" ? 1 : -1;
    return [...items].sort((a, b) => {
      const av = accessor(a, sort.key);
      const bv = accessor(b, sort.key);
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return String(av).localeCompare(String(bv)) * dir;
    });
  }, [items, sort, accessor]);
  return { sort, setSort, sorted };
}

/** Shared empty/loading/error body for a grid with `colSpan` columns. */
export function GridStateRow({
  colSpan, isLoading, isError, errorText, emptyText,
}: {
  colSpan: number;
  isLoading?: boolean;
  isError?: boolean;
  errorText?: string;
  emptyText: string;
}) {
  return (
    <tr>
      <td colSpan={colSpan} className="py-6 text-center text-sm">
        {isLoading ? (
          <span className="inline-flex items-center gap-2 text-gray-500">
            <Spinner className="h-4 w-4" />Loading…
          </span>
        ) : isError ? (
          <span className="text-red-600">{errorText || "Failed to load. Check cluster connectivity."}</span>
        ) : (
          <span className="text-gray-400">{emptyText}</span>
        )}
      </td>
    </tr>
  );
}

export function GridSearchBar({
  search,
  onSearch,
  onPage,
  totalItems,
  shownItems,
  placeholder,
  isSyncing,
}: {
  search: string;
  onSearch: (v: string) => void;
  onPage: (p: number) => void;
  totalItems: number;
  shownItems: number;
  placeholder?: string;
  isSyncing?: boolean;
}) {
  return (
    <div className={gridStyles.panelHeader}>
      <div className="flex items-center gap-3">
        <span className={gridStyles.countBadge}>{shownItems} of {totalItems}</span>
        <AutoRefreshIndicator label={isSyncing ? "Syncing..." : undefined} />
      </div>
      <input
        type="text"
        value={search}
        onChange={(e) => {
          onSearch(e.target.value);
          onPage(1);
        }}
        placeholder={placeholder || "Search..."}
        className={gridStyles.toolbarInput}
      />
    </div>
  );
}

export function GridPager({
  page,
  totalPages,
  onPage,
}: {
  page: number;
  totalPages: number;
  onPage: (p: number) => void;
}) {
  if (totalPages <= 1) return null;
  return (
    <div className={gridStyles.pager}>
      <span className="text-gray-600">Showing page {page} of {totalPages}</span>
      <div className="flex items-center gap-2">
        <button type="button" disabled={page <= 1} onClick={() => onPage(page - 1)} className={gridStyles.pagerButton}>
          Previous
        </button>
        <span className="text-gray-600">Page {page} of {totalPages}</span>
        <button type="button" disabled={page >= totalPages} onClick={() => onPage(page + 1)} className={gridStyles.pagerButton}>
          Next
        </button>
      </div>
    </div>
  );
}

export function NamespaceSelect({
  namespaces,
  value,
  onChange,
}: {
  namespaces: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} className={gridStyles.toolbarInput}>
      <option value="">All Namespaces</option>
      {namespaces.map((ns) => (
        <option key={ns} value={ns}>{ns}</option>
      ))}
    </select>
  );
}

export function CacheSourceBadge({
  source,
  lastSync,
  formatDate,
}: {
  source?: string;
  lastSync?: string | null;
  formatDate: (value: string) => string;
}) {
  const isDb = source === "db";
  return (
    <div className="flex items-center gap-3">
      <span className={`px-2 py-1 rounded-full text-xs font-medium ${
        isDb ? "bg-blue-100 text-blue-700" : "bg-green-100 text-green-700"
      }`}>
        Source: {isDb ? "Database" : "Kubernetes Live"}
      </span>
      {lastSync ? (
        <span className="text-sm text-gray-500">Last synced: {formatDate(lastSync)}</span>
      ) : (
        <span className="text-sm text-yellow-600">Not synced yet — click Sync to load</span>
      )}
    </div>
  );
}

export function ExtendedTabToolbar({
  title,
  namespaceSelect,
  onSync,
  syncing,
  onCreate,
  createLabel,
  canWrite,
  liveBadge,
}: {
  title: string;
  namespaceSelect?: React.ReactNode;
  onSync?: () => void;
  syncing?: boolean;
  onCreate?: () => void;
  createLabel?: string;
  canWrite?: boolean;
  liveBadge?: React.ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3">
      <div className="flex items-center gap-2">
        <h2 className="text-xl font-semibold text-gray-800">{title}</h2>
        {liveBadge}
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {namespaceSelect}
        {onSync && (
          <button
            type="button"
            onClick={onSync}
            disabled={syncing}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 text-sm"
          >
            {syncing ? "Syncing..." : "Sync from Azure"}
          </button>
        )}
        {canWrite && onCreate && (
          <button
            type="button"
            onClick={onCreate}
            className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 text-sm"
          >
            + {createLabel || "Create"}
          </button>
        )}
      </div>
    </div>
  );
}

/** Shown above a grid while a KPI tile is filtering it, with a one-click clear. */
export function TileFilterNotice({ label, onClear }: { label: string | null; onClear: () => void }) {
  if (!label) return null;
  return (
    <div className="flex items-center">
      <span className="inline-flex items-center gap-2 rounded-full border border-att-200 bg-att-50 px-3 py-1 text-sm text-att-700">
        Filtered by tile: <span className="font-semibold">{label}</span>
        <button
          type="button"
          onClick={onClear}
          aria-label="Clear tile filter"
          title="Clear filter"
          className="rounded-full p-0.5 text-att-600 hover:bg-att-100"
        >
          <svg width={14} height={14} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
        </button>
      </span>
    </div>
  );
}
