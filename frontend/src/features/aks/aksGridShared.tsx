/**
 * Shared grid helpers for AKS extended resource tabs — aligned with AKSOperationsPage.
 */

import React, { useMemo, useState } from "react";
import { AutoRefreshIndicator, gridStyles } from "../../components/gridStyles";

export const AKS_PAGE_SIZE = 15;

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

export function GridSearchBar({
  search,
  onSearch,
  onPage,
  totalItems,
  shownItems,
  placeholder,
}: {
  search: string;
  onSearch: (v: string) => void;
  onPage: (p: number) => void;
  totalItems: number;
  shownItems: number;
  placeholder?: string;
}) {
  return (
    <div className={gridStyles.panelHeader}>
      <div className="flex items-center gap-3">
        <span className={gridStyles.countBadge}>{shownItems} of {totalItems}</span>
        <AutoRefreshIndicator />
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
