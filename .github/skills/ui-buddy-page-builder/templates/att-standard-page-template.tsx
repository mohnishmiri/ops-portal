import React, { useMemo, useState } from "react";
import { MetricCard, MetricCardIcons } from "../../../frontend/src/components/MetricCard";
import { gridStyles } from "../../../frontend/src/components/gridStyles";

type ExampleRow = {
  id: string;
  name: string;
  status: string;
  owner: string;
  value: number;
};

const PAGE_SIZE = 10;

export default function ExampleAttStandardPage() {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);

  const rows: ExampleRow[] = [];

  const filteredRows = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) {
      return rows;
    }

    return rows.filter((row) =>
      [row.name, row.status, row.owner, row.value]
        .some((value) => String(value).toLowerCase().includes(query)),
    );
  }, [rows, search]);

  const totalPages = Math.max(1, Math.ceil(filteredRows.length / PAGE_SIZE));
  const pagedRows = useMemo(
    () => filteredRows.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE),
    [filteredRows, page],
  );

  return (
    <div className="space-y-6 p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-slate-900">Example ATT Page</h1>
          <p className="text-sm text-slate-500">Replace this shell with the page-specific business context.</p>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          title="Total Items"
          value={String(rows.length)}
          subtitle="ATT-standard KPI shell"
          icon={MetricCardIcons.layers()}
          tone="blue"
        />
        <MetricCard
          title="Healthy"
          value="0"
          subtitle="Replace with a meaningful metric"
          icon={MetricCardIcons.shield()}
          tone="emerald"
        />
      </div>

      <div className={gridStyles.shell}>
        <div className={gridStyles.panelHeader}>
          <div>
            <h2 className="text-lg font-semibold text-gray-900">Example Grid</h2>
            <p className="text-sm text-gray-500">Search is top-right and pagination stays below the grid.</p>
          </div>
          <input
            type="text"
            placeholder="Search rows..."
            value={search}
            onChange={(event) => {
              setSearch(event.target.value);
              setPage(0);
            }}
            className={gridStyles.toolbarInput}
          />
        </div>

        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}>Name</th>
                <th className={gridStyles.headerCell}>Status</th>
                <th className={gridStyles.headerCell}>Owner</th>
                <th className={`${gridStyles.headerCell} text-right`}>Value</th>
              </tr>
            </thead>
            <tbody>
              {pagedRows.map((row) => (
                <tr key={row.id} className={gridStyles.row}>
                  <td className={gridStyles.strongCell}>{row.name}</td>
                  <td className={gridStyles.cell}>{row.status}</td>
                  <td className={gridStyles.cell}>{row.owner}</td>
                  <td className={`${gridStyles.monoCell} text-right`}>{row.value}</td>
                </tr>
              ))}
              {filteredRows.length === 0 && (
                <tr>
                  <td colSpan={4} className="px-4 py-8 text-center text-sm text-gray-400">
                    No rows match the current search.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        <div className={gridStyles.pager}>
          <span className="text-gray-600">
            {filteredRows.length === 0
              ? "Showing 0 rows"
              : `Showing ${page * PAGE_SIZE + 1}-${Math.min((page + 1) * PAGE_SIZE, filteredRows.length)} of ${filteredRows.length} rows`}
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setPage((current) => Math.max(0, current - 1))}
              disabled={page === 0}
              className={gridStyles.pagerButton}
            >
              Previous
            </button>
            <span className="text-gray-700">Page {page + 1} of {totalPages}</span>
            <button
              type="button"
              onClick={() => setPage((current) => Math.min(totalPages - 1, current + 1))}
              disabled={page >= totalPages - 1}
              className={gridStyles.pagerButton}
            >
              Next
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}