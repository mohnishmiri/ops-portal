/**
 * Multi-select certificate picker for auto-renewal schedules.
 *
 * Server-side, debounced search scoped to a single collection. Selected
 * certificates persist as compact refs even when they scroll out of the
 * current result set, so a schedule can target one or many specific certs.
 */

import React, { useEffect, useMemo, useState } from "react";
import {
  AutoRenewalCertificateRef,
  Certificate,
  useCertificates,
} from "../../services/certificatesApi";
import { gridStyles } from "../../components/gridStyles";
import { StatusBadge } from "./StatusBadge";
import { formatDate } from "../../utils/dateFormat";

interface CertificateMultiSelectProps {
  collectionId: number;
  selected: AutoRenewalCertificateRef[];
  onChange: (next: AutoRenewalCertificateRef[]) => void;
}

const toRef = (c: Certificate): AutoRenewalCertificateRef => ({
  id: c.id,
  common_name: c.common_name,
  thumbprint: c.thumbprint,
  // Captured at selection time, while the full certificate is in hand: the
  // schedule form uses these to preselect the matching Key Vault entries.
  sans: c.sans ?? [],
});

export const CertificateMultiSelect: React.FC<CertificateMultiSelectProps> = ({
  collectionId,
  selected,
  onChange,
}) => {
  const [search, setSearch] = useState("");
  const [debounced, setDebounced] = useState("");

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(search.trim()), 300);
    return () => clearTimeout(timer);
  }, [search]);

  const { data, isLoading, isFetching } = useCertificates(
    { collection_id: collectionId, cn: debounced || undefined, page: 1, page_size: 100 },
    collectionId != null,
  );

  const items = useMemo(() => data?.items ?? [], [data?.items]);
  const total = data?.total ?? 0;
  const selectedIds = useMemo(() => new Set(selected.map((c) => c.id)), [selected]);

  const toggle = (cert: Certificate) => {
    if (selectedIds.has(cert.id)) {
      onChange(selected.filter((c) => c.id !== cert.id));
    } else {
      onChange([...selected, toRef(cert)]);
    }
  };

  const selectAllShown = () => {
    const additions = items.filter((c) => !selectedIds.has(c.id)).map(toRef);
    if (additions.length) onChange([...selected, ...additions]);
  };

  const remove = (id: number) => onChange(selected.filter((c) => c.id !== id));

  return (
    <div className="rounded-lg border border-att-200 bg-white">
      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2 border-b border-att-100 p-2">
        <input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search certificates by common name…"
          aria-label="Search certificates"
          className={`${gridStyles.toolbarInput} min-w-[14rem] flex-1`}
        />
        <button type="button" onClick={selectAllShown} disabled={items.length === 0} className={gridStyles.pagerButton}>
          Select all shown
        </button>
        <button type="button" onClick={() => onChange([])} disabled={selected.length === 0} className={gridStyles.pagerButton}>
          Clear
        </button>
      </div>

      {/* Selected chips */}
      {selected.length > 0 && (
        <div className="flex flex-wrap gap-1.5 border-b border-att-100 bg-att-50/40 p-2">
          {selected.map((c) => (
            <span
              key={c.id}
              className="inline-flex items-center gap-1 rounded-full bg-att-100 px-2 py-0.5 text-xs font-medium text-att-700"
            >
              <span className="max-w-[16rem] truncate" title={c.common_name || `#${c.id}`}>
                {c.common_name || `#${c.id}`}
              </span>
              <button
                type="button"
                onClick={() => remove(c.id)}
                aria-label={`Remove ${c.common_name || c.id}`}
                className="text-att-500 hover:text-att-800"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}

      {/* Results */}
      <div className="max-h-64 overflow-y-auto">
        {isLoading ? (
          <p className="p-4 text-center text-sm text-gray-500">Loading certificates…</p>
        ) : items.length === 0 ? (
          <p className="p-4 text-center text-sm text-gray-500">
            {debounced ? "No certificates match your search." : "No certificates in this collection."}
          </p>
        ) : (
          <ul className="divide-y divide-att-50">
            {items.map((c) => (
              <li key={c.id}>
                <label className="flex cursor-pointer items-center gap-3 px-3 py-2 hover:bg-att-50/50">
                  <input
                    type="checkbox"
                    checked={selectedIds.has(c.id)}
                    onChange={() => toggle(c)}
                    className="h-4 w-4 rounded border-att-300 text-att-600 focus:ring-att-400"
                  />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-gray-800" title={c.common_name}>
                    {c.common_name || "—"}
                  </span>
                  <StatusBadge status={c.status} />
                  <span className="whitespace-nowrap text-xs text-gray-500">
                    {formatDate(c.not_after)}
                  </span>
                </label>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Footer */}
      <div className="flex items-center justify-between border-t border-att-100 bg-att-50/40 px-3 py-2 text-xs text-gray-500">
        <span className="font-medium text-att-700">{selected.length} selected</span>
        <span>
          {isFetching
            ? "Searching…"
            : total > items.length
              ? `Showing ${items.length} of ${total} — refine your search`
              : `${items.length} shown`}
        </span>
      </div>
    </div>
  );
};
