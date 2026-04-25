/**
 * ChecksumComparisonGrid — Per-pipeline yesterday-vs-current hash comparison table.
 *
 * Columns:
 *   Sl.No | Pipeline Name | Yesterday's Checksum | Current Checksum | Last Published | Status
 *
 * Status is colour-coded: green PASS / red FAIL.
 * Supports optional search filter and CSV-style copy.
 */

import React, { useEffect, useMemo, useState } from "react";
import type { ChecksumResultItem } from "../../services/complianceApi";
import { AutoRefreshIndicator, gridStyles, nextSortState, SortableHeader, type SortState } from "../../components/gridStyles";
import { usePortalTimezone } from "../../contexts/TimezoneContext";

// ── Props ─────────────────────────────────────────────────────────────

export interface ChecksumComparisonGridProps {
  /** Pipeline-level comparison results (from the latest verification run). */
  results: ChecksumResultItem[];
  /** Whether the parent query is still loading. */
  isLoading?: boolean;
  /** Total passed count (pre-computed by the API). */
  passed?: number;
  /** Total failed count (pre-computed by the API). */
  failed?: number;
  /** UUID of the verification run shown. */
  runId?: string | null;
}

// ── Helpers ───────────────────────────────────────────────────────────

function formatHash(hash: string | null): string {
  if (!hash) return "—";
  return hash;
}

type ComparisonSortKey =
  | "pipeline_name"
  | "yesterday_hash"
  | "present_hash"
  | "last_published_date"
  | "result";

// ── Component ─────────────────────────────────────────────────────────

export default function ChecksumComparisonGrid({
  results,
  isLoading = false,
  passed = 0,
  failed = 0,
  runId,
}: ChecksumComparisonGridProps) {
  const { formatDate } = usePortalTimezone();
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"ALL" | "PASS" | "FAIL">("ALL");
  const [page, setPage] = useState(0);
  const [sortState, setSortState] = useState<SortState<ComparisonSortKey>>({
    key: "pipeline_name",
    direction: "asc",
  });
  const pageSize = 20;

  // ── Filter results ─────────────────────────────────────────────────
  const filtered = useMemo(() => {
    let list = results;
    if (search) {
      const q = search.toLowerCase();
      list = list.filter((r) => r.pipeline_name.toLowerCase().includes(q));
    }
    if (statusFilter !== "ALL") {
      list = list.filter((r) => r.result === statusFilter);
    }
    return list;
  }, [results, search, statusFilter]);

  const sorted = useMemo(() => {
    return [...filtered].sort((left, right) => {
      const direction = sortState.direction === "asc" ? 1 : -1;

      if (sortState.key === "last_published_date") {
        const leftValue = left.last_published_date ? new Date(left.last_published_date).getTime() : 0;
        const rightValue = right.last_published_date ? new Date(right.last_published_date).getTime() : 0;
        return (leftValue - rightValue) * direction;
      }

      const leftValue = String(left[sortState.key] ?? "").toLowerCase();
      const rightValue = String(right[sortState.key] ?? "").toLowerCase();
      return leftValue.localeCompare(rightValue) * direction;
    });
  }, [filtered, sortState]);

  // ── Pagination ─────────────────────────────────────────────────────
  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const paged = useMemo(
    () => sorted.slice(page * pageSize, (page + 1) * pageSize),
    [sorted, page],
  );

  // Reset page when filters change
  useEffect(() => {
    setPage(0);
  }, [search, statusFilter, sortState]);

  // ── Loading state ──────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="text-center py-8 text-gray-500">
        Loading comparison results…
      </div>
    );
  }

  // ── Empty state ────────────────────────────────────────────────────
  if (results.length === 0) {
    return (
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-8 text-center">
        <p className="text-gray-500">
          No checksum comparison results available for this workspace.
        </p>
        <p className="text-sm text-gray-400 mt-1">
          Click <strong>Run Checksum</strong> to generate a comparison.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {/* Toolbar: search + status filter + summary */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-3">
          <AutoRefreshIndicator />
          {/* Pipeline search */}
          <input
            type="text"
            placeholder="Search pipelines…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={gridStyles.toolbarInput}
          />

          {/* Status toggle */}
          <div className="flex rounded-lg border border-gray-300 text-sm overflow-hidden">
            {(["ALL", "PASS", "FAIL"] as const).map((s) => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                className={`px-3 py-1.5 transition-colors ${
                  statusFilter === s
                    ? s === "PASS"
                      ? "bg-green-600 text-white"
                      : s === "FAIL"
                        ? "bg-red-600 text-white"
                        : "bg-att-400 text-white"
                    : "bg-white text-gray-600 hover:bg-att-50"
                }`}
              >
                {s === "ALL" ? `All (${results.length})` : s === "PASS" ? `Pass (${passed})` : `Fail (${failed})`}
              </button>
            ))}
          </div>
        </div>

        {/* Run ID badge */}
        {runId && (
          <span className="rounded-full bg-att-50 px-2.5 py-1 text-xs font-mono text-att-700" title={`Run: ${runId}`}>
            Run: {runId.slice(0, 8)}…
          </span>
        )}
      </div>

      {/* Results table */}
      <div className={gridStyles.shell}>
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
            <tr>
              <th className={`${gridStyles.headerCellCenter} w-16`}>
                <span>Sl.No</span>
              </th>
              <th className={gridStyles.headerCell}>
                <SortableHeader
                  label="Pipeline Name"
                  active={sortState.key === "pipeline_name"}
                  direction={sortState.direction}
                  onClick={() => setSortState((current) => nextSortState(current, "pipeline_name"))}
                />
              </th>
              <th className={gridStyles.headerCell}>
                <SortableHeader
                  label="Yesterday's Checksum"
                  active={sortState.key === "yesterday_hash"}
                  direction={sortState.direction}
                  onClick={() => setSortState((current) => nextSortState(current, "yesterday_hash"))}
                />
              </th>
              <th className={gridStyles.headerCell}>
                <SortableHeader
                  label="Current Checksum"
                  active={sortState.key === "present_hash"}
                  direction={sortState.direction}
                  onClick={() => setSortState((current) => nextSortState(current, "present_hash"))}
                />
              </th>
              <th className={gridStyles.headerCell}>
                <SortableHeader
                  label="Last Published"
                  active={sortState.key === "last_published_date"}
                  direction={sortState.direction}
                  onClick={() => setSortState((current) => nextSortState(current, "last_published_date"))}
                />
              </th>
              <th className={`${gridStyles.headerCellCenter} w-24`}>
                <SortableHeader
                  label="Status"
                  active={sortState.key === "result"}
                  direction={sortState.direction}
                  onClick={() => setSortState((current) => nextSortState(current, "result"))}
                  align="center"
                />
              </th>
            </tr>
            </thead>
            <tbody>
            {paged.map((row, idx) => {
              const isFail = row.result === "FAIL";
              return (
                <tr
                  key={row.id ?? `${row.run_id}-${row.slno}`}
                  className={`${gridStyles.row} ${isFail ? "bg-red-50/40" : ""}`}
                >
                  <td className={gridStyles.centerCell}>
                    {row.slno ?? page * pageSize + idx + 1}
                  </td>
                  <td className={gridStyles.strongCell}>
                    {row.pipeline_name}
                  </td>
                  <td className={gridStyles.monoCell} title={row.yesterday_hash ?? ""}>
                    {formatHash(row.yesterday_hash)}
                  </td>
                  <td
                    className={`${gridStyles.monoCell} ${isFail ? "font-semibold text-red-700" : ""}`}
                    title={row.present_hash ?? ""}
                  >
                    {formatHash(row.present_hash)}
                  </td>
                  <td className={`${gridStyles.cell} whitespace-nowrap`}>
                    {row.last_published_date
                      ? formatDate(row.last_published_date)
                      : "—"}
                  </td>
                  <td className={gridStyles.centerCell}>
                    <span
                      className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                        isFail
                          ? "bg-red-100 text-red-700"
                          : "bg-green-100 text-green-700"
                      }`}
                    >
                      {row.result}
                    </span>
                  </td>
                </tr>
              );
            })}

            {filtered.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-8 text-center text-sm text-gray-400">
                  No pipelines match the current filter.
                </td>
              </tr>
            )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      {totalPages > 1 && (
        <div className={gridStyles.pager}>
          <span className="text-gray-600">
            Showing {page * pageSize + 1}–{Math.min((page + 1) * pageSize, sorted.length)} of {sorted.length} pipelines
          </span>
          <div className="flex items-center gap-2">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className={gridStyles.pagerButton}
            >
              Previous
            </button>
            <span className="text-gray-700">
              Page {page + 1} of {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className={gridStyles.pagerButton}
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
