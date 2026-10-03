/**
 * The grid used inside every AKS resource detail view.
 *
 * ATT grid standard: title and count top-left, search (plus optional filters)
 * top-right, sortable columns, and a bottom pager with a page-size selector.
 * Search and sort run before pagination, and the page resets when the search
 * or the data changes so a filter never strands the user on an empty page.
 */

import React, { useEffect, useMemo, useState } from "react";
import { gridStyles, SortableHeader, type SortDirection } from "../../components/gridStyles";

export interface GridColumn<T> {
  key: string;
  header: string;
  render: (row: T) => React.ReactNode;
  /** Makes the column sortable. */
  sortValue?: (row: T) => string | number;
  align?: "left" | "center" | "right";
  /** Extra classes for the body cell, e.g. a max width for truncated text. */
  className?: string;
}

const PAGE_SIZES = [10, 25, 50, 100];

export function DetailGrid<T>({
  title,
  rows,
  columns,
  rowKey,
  searchText,
  searchPlaceholder = "Search...",
  emptyText = "No items",
  initialSort,
  toolbar,
  defaultPageSize = 10,
  expandedKey,
  renderExpanded,
  onRowClick,
}: {
  title: string;
  rows: T[];
  columns: GridColumn<T>[];
  rowKey: (row: T) => string;
  /** Text the search box matches against (case-insensitive). */
  searchText: (row: T) => string;
  searchPlaceholder?: string;
  emptyText?: string;
  initialSort?: { key: string; direction: SortDirection };
  /** Extra controls (filters) shown left of the search box. */
  toolbar?: React.ReactNode;
  defaultPageSize?: number;
  /** Row whose details are shown beneath it. */
  expandedKey?: string | null;
  renderExpanded?: (row: T) => React.ReactNode;
  onRowClick?: (row: T) => void;
}) {
  const [search, setSearch] = useState("");
  const [sort, setSort] = useState(initialSort ?? null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(defaultPageSize);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return q ? rows.filter((row) => searchText(row).toLowerCase().includes(q)) : rows;
  }, [rows, search, searchText]);

  const sorted = useMemo(() => {
    const column = sort && columns.find((c) => c.key === sort.key);
    if (!column?.sortValue) return filtered;
    const dir = sort!.direction === "asc" ? 1 : -1;
    const value = column.sortValue;
    return [...filtered].sort((a, b) => {
      const av = value(a);
      const bv = value(b);
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return String(av).localeCompare(String(bv), undefined, { numeric: true }) * dir;
    });
  }, [filtered, sort, columns]);

  // A new search or a caller-side filter (which changes the row count) starts again from page 1.
  // Keyed on the count, not the array, so the detail views' background refresh keeps the page.
  useEffect(() => setPage(1), [search, rows.length]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, totalPages);
  const start = (safePage - 1) * pageSize;
  const paged = sorted.slice(start, start + pageSize);

  const toggleSort = (key: string) =>
    setSort((prev) => (prev?.key === key ? { key, direction: prev.direction === "asc" ? "desc" : "asc" } : { key, direction: "asc" }));

  const alignClass = (align?: "left" | "center" | "right") =>
    align === "center" ? "text-center" : align === "right" ? "text-right" : "text-left";

  return (
    <div className={gridStyles.shell}>
      <div className={gridStyles.panelHeader}>
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
          <span className={gridStyles.countBadge}>
            {filtered.length === rows.length ? rows.length : `${filtered.length} of ${rows.length}`}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {toolbar}
          <input
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={searchPlaceholder}
            aria-label={`Search ${title}`}
            className={`${gridStyles.toolbarInput} w-56`}
          />
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              {columns.map((c) => (
                <th key={c.key} className={`${gridStyles.headerCell} whitespace-nowrap ${alignClass(c.align)}`}>
                  {c.sortValue ? (
                    <SortableHeader
                      label={c.header}
                      active={sort?.key === c.key}
                      direction={sort?.key === c.key ? sort.direction : "asc"}
                      onClick={() => toggleSort(c.key)}
                      align={c.align === "center" ? "center" : "left"}
                    />
                  ) : (
                    c.header
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {paged.length === 0 && (
              <tr>
                <td colSpan={columns.length} className="px-4 py-8 text-center text-sm text-gray-400">
                  {rows.length === 0 ? emptyText : `No results match “${search}”`}
                </td>
              </tr>
            )}
            {paged.map((row) => {
              const key = rowKey(row);
              const expanded = renderExpanded && expandedKey === key;
              return (
                <React.Fragment key={key}>
                  <tr
                    className={`${gridStyles.row} ${expanded ? gridStyles.selectedRow : ""} ${onRowClick ? "cursor-pointer" : ""}`}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                  >
                    {columns.map((c) => (
                      <td key={c.key} className={`${gridStyles.cell} align-middle ${alignClass(c.align)} ${c.className ?? ""}`}>
                        {c.render(row)}
                      </td>
                    ))}
                  </tr>
                  {expanded && (
                    <tr className="border-t border-att-100">
                      <td colSpan={columns.length} className="bg-att-50/40 px-4 pb-4 pt-2">
                        {renderExpanded!(row)}
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className={gridStyles.pager}>
        <span className="text-gray-600">
          {sorted.length === 0 ? "Showing 0" : `Showing ${start + 1}–${start + paged.length} of ${sorted.length}`}
        </span>
        <div className="flex items-center gap-2">
          <label className="flex items-center gap-1.5 text-gray-500">
            Rows
            <select
              value={pageSize}
              onChange={(e) => {
                setPageSize(Number(e.target.value));
                setPage(1);
              }}
              className="rounded-lg border border-att-200 bg-white px-2 py-1 text-sm text-gray-700"
              aria-label="Rows per page"
            >
              {PAGE_SIZES.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </label>
          <button type="button" disabled={safePage <= 1} onClick={() => setPage(safePage - 1)} className={gridStyles.pagerButton}>
            Previous
          </button>
          <span className="whitespace-nowrap text-gray-700">Page {safePage} of {totalPages}</span>
          <button type="button" disabled={safePage >= totalPages} onClick={() => setPage(safePage + 1)} className={gridStyles.pagerButton}>
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

/** Compact select for a grid toolbar filter. */
export function GridFilterSelect<V extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: V;
  options: { value: V; label: string }[];
  onChange: (value: V) => void;
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value as V)}
      aria-label={label}
      className="rounded-lg border border-att-200 bg-white px-3 py-2 text-sm text-gray-700 shadow-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100"
    >
      {options.map((o) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
}

export default DetailGrid;
