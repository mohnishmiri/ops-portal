import React from "react";

export type SortDirection = "asc" | "desc";

export interface SortState<T extends string> {
  key: T;
  direction: SortDirection;
}

export function nextSortState<T extends string>(
  current: SortState<T>,
  key: T,
): SortState<T> {
  if (current.key !== key) {
    return { key, direction: "asc" };
  }

  return {
    key,
    direction: current.direction === "asc" ? "desc" : "asc",
  };
}

export const gridStyles = {
  shell: "overflow-hidden rounded-xl border border-att-100 bg-white shadow-sm",
  panelHeader:
    "border-b border-att-100 bg-att-50/70 px-4 py-3 flex flex-wrap items-center justify-between gap-3",
  table: "w-full bg-white",
  head: "bg-att-50/80",
  stickyHead: "sticky top-0 z-10 bg-att-50/95 backdrop-blur",
  headerCell:
    "px-4 py-3 text-left text-xs font-semibold uppercase tracking-[0.12em] text-att-700",
  headerCellCenter:
    "px-4 py-3 text-center text-xs font-semibold uppercase tracking-[0.12em] text-att-700",
  row: "border-t border-att-100 hover:bg-att-50/40",
  selectedRow: "bg-att-50/80",
  cell: "px-4 py-2.5 text-sm text-gray-700",
  strongCell: "px-4 py-2.5 text-sm font-medium text-gray-800",
  centerCell: "px-4 py-2.5 text-center text-sm text-gray-700",
  monoCell: "px-4 py-2.5 font-mono text-xs text-gray-600 break-all",
  toolbarInput:
    "w-64 rounded-lg border border-att-200 bg-white px-3 py-2 text-sm text-gray-700 shadow-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100",
  pager:
    "flex items-center justify-between border-t border-att-100 bg-att-50/40 px-4 py-3 text-sm",
  pagerButton:
    "rounded-lg border border-att-200 bg-white px-3 py-1.5 text-gray-700 hover:border-att-300 hover:bg-att-50 disabled:opacity-40",
  countBadge:
    "inline-flex items-center rounded-full bg-att-50 px-2.5 py-1 text-xs font-medium text-att-700",
  sectionTitle: "font-semibold text-gray-800",
};

interface AutoRefreshIndicatorProps {
  label?: string;
}

export function AutoRefreshIndicator({
  label = "Auto-refresh on",
}: AutoRefreshIndicatorProps) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-att-200 bg-white px-3 py-1 text-xs font-medium text-att-700 shadow-sm">
      <span className="relative flex h-2.5 w-2.5">
        <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-green-400 opacity-60" />
        <span className="relative inline-flex h-2.5 w-2.5 rounded-full bg-green-500" />
      </span>
      {label}
    </span>
  );
}

interface SortableHeaderProps {
  label: string;
  active: boolean;
  direction: SortDirection;
  onClick: () => void;
  align?: "left" | "center";
}

export function SortableHeader({
  label,
  active,
  direction,
  onClick,
  align = "left",
}: SortableHeaderProps) {
  const alignmentClass = align === "center" ? "justify-center" : "justify-start";

  return (
    <button
      type="button"
      onClick={onClick}
      className={`inline-flex w-full items-center gap-1 ${alignmentClass} transition-colors hover:text-att-600`}
      aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}
    >
      <span>{label}</span>
      <span className={`inline-flex flex-col leading-none ${active ? "text-att-600" : "text-att-300"}`}>
        <svg viewBox="0 0 12 12" className={`h-2.5 w-2.5 ${active && direction === "asc" ? "opacity-100" : "opacity-50"}`} fill="currentColor" aria-hidden="true">
          <path d="M6 2 9.5 6H2.5L6 2Z" />
        </svg>
        <svg viewBox="0 0 12 12" className={`h-2.5 w-2.5 -mt-0.5 ${active && direction === "desc" ? "opacity-100" : "opacity-50"}`} fill="currentColor" aria-hidden="true">
          <path d="M6 10 2.5 6h7L6 10Z" />
        </svg>
      </span>
    </button>
  );
}