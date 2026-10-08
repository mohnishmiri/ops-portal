/**
 * Shared helpers for the cost pages (Amortized Costs, Cost Forecast).
 */

import React from "react";

/**
 * Format a YYYY-MM-DD cost date.
 *
 * Cost dates are UTC calendar days. Parsing them with `new Date(iso)` and
 * formatting in the portal timezone showed every date a day early for US
 * users (UTC midnight is the previous evening in America/*).
 */
export function fmtCostDate(
  iso: string | null | undefined,
  opts: { year?: boolean; weekday?: boolean } = {},
): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  if (!y || !m || !d) return iso;
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString("en-US", {
    timeZone: "UTC",
    month: "short",
    day: "numeric",
    ...(opts.year ? { year: "numeric" } : {}),
    ...(opts.weekday ? { weekday: "short" } : {}),
  });
}

/** "Jul 8 – Oct 7, 2026", or with both years when they differ. */
export function fmtCostRange(start: string | null | undefined, end: string | null | undefined): string {
  if (!start || !end) return "—";
  if (start.slice(0, 4) === end.slice(0, 4)) {
    return `${fmtCostDate(start)} – ${fmtCostDate(end, { year: true })}`;
  }
  return `${fmtCostDate(start, { year: true })} – ${fmtCostDate(end, { year: true })}`;
}

export interface DataQualityItem {
  key: string;
  title: string;
  detail?: string;
}

const MAX_ITEMS = 5;

/** Amber banner listing gaps that make the figures on the page incomplete. */
export const DataQualityBanner: React.FC<{
  heading: string;
  items: DataQualityItem[];
  footnote?: React.ReactNode;
}> = ({ heading, items, footnote }) => {
  if (!items.length) return null;
  const shown = items.slice(0, MAX_ITEMS);
  return (
    <div role="alert" className="flex items-start gap-3 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
      <svg className="mt-0.5 h-5 w-5 flex-shrink-0 text-amber-500" fill="none" stroke="currentColor" viewBox="0 0 24 24" aria-hidden="true">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
      </svg>
      <div className="min-w-0 space-y-1.5">
        <p className="font-semibold">{heading}</p>
        <ul className="space-y-1">
          {shown.map((item) => (
            <li key={item.key}>
              <span className="font-medium">{item.title}</span>
              {item.detail ? <span className="text-amber-800"> — {item.detail}</span> : null}
            </li>
          ))}
          {items.length > MAX_ITEMS && <li className="text-amber-800">and {items.length - MAX_ITEMS} more</li>}
        </ul>
        {footnote ? <p className="text-amber-800">{footnote}</p> : null}
      </div>
    </div>
  );
};

/** One-line explanation of the shaded "preliminary" days on cost charts. */
export const PreliminaryNote: React.FC<{ from?: string | null; through?: string | null }> = ({ from, through }) => {
  if (!from || !through || from > through) return null;
  return (
    <p className="mt-3 flex items-center gap-2 text-xs text-slate-500">
      <span className="inline-block h-3 w-3 rounded-sm bg-slate-200 ring-1 ring-slate-300" aria-hidden="true" />
      {fmtCostRange(from, through)} is preliminary: Azure can still add usage to a day for up to 72 hours after it ends (UTC).
    </p>
  );
};
