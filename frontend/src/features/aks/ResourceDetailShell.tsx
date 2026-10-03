/**
 * Full-size window for AKS resource drill-downs (Deployment, Pod, StatefulSet,
 * DaemonSet, Job, AzureKeyVaultSecret). Every view gets the same identity
 * header, tab strip with counts, and scrolling body, so moving between
 * resources never changes where things are.
 */

import React, { useId, useRef } from "react";
import { Spinner } from "../../components/gridStyles";
import { CopyButton } from "./detailShared";

const kindIcon = {
  width: 22,
  height: 22,
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export const ResourceKindIcons = {
  deployment: <svg {...kindIcon}><rect x="2" y="3" width="20" height="14" rx="2" /><line x1="8" y1="21" x2="16" y2="21" /><line x1="12" y1="17" x2="12" y2="21" /></svg>,
  pod: <svg {...kindIcon}><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z" /><polyline points="3.27 6.96 12 12.01 20.73 6.96" /><line x1="12" y1="22.08" x2="12" y2="12" /></svg>,
  statefulset: <svg {...kindIcon}><ellipse cx="12" cy="5" rx="9" ry="3" /><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3" /><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5" /></svg>,
  daemonset: <svg {...kindIcon}><rect x="2" y="2" width="8" height="8" rx="1" /><rect x="14" y="2" width="8" height="8" rx="1" /><rect x="2" y="14" width="8" height="8" rx="1" /><rect x="14" y="14" width="8" height="8" rx="1" /></svg>,
  job: <svg {...kindIcon}><path d="M9 11l3 3L22 4" /><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" /></svg>,
  keyvault: <svg {...kindIcon}><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" /></svg>,
};

export interface DetailTab<T extends string> {
  key: T;
  label: string;
  count?: number;
  /** Highlights the count, e.g. warning events. */
  attention?: boolean;
}

export function ResourceDetailShell<T extends string>({
  kind,
  name,
  namespace,
  icon,
  status,
  meta,
  actions,
  tabs,
  activeTab,
  onTabChange,
  isLoading,
  error,
  onClose,
  children,
}: {
  /** e.g. "Deployment". */
  kind: string;
  name: string;
  namespace?: string;
  icon: React.ReactNode;
  /** Status badge shown next to the name. */
  status?: React.ReactNode;
  /** Short facts under the name, e.g. "60/60 ready · revision 4". */
  meta?: React.ReactNode;
  /** Header buttons (logs, download). */
  actions?: React.ReactNode;
  tabs: DetailTab<T>[];
  activeTab: T;
  // NoInfer: infer T from the tabs, not from a setState passed as onTabChange.
  onTabChange: (key: NoInfer<T>) => void;
  isLoading?: boolean;
  /** Shown instead of the body when the resource could not be loaded. */
  error?: string | null;
  onClose: () => void;
  children?: React.ReactNode;
}) {
  const titleId = useId();
  // Close only on a clean backdrop click, so a text selection dragged outside never closes the view.
  const backdropRef = useRef<HTMLDivElement>(null);
  const downOnBackdrop = useRef(false);

  return (
    <div
      ref={backdropRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
      onMouseDown={(e) => { downOnBackdrop.current = e.target === backdropRef.current; }}
      onMouseUp={(e) => {
        if (downOnBackdrop.current && e.target === backdropRef.current) onClose();
        downOnBackdrop.current = false;
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="flex h-[90vh] w-full max-w-[90rem] flex-col overflow-hidden rounded-2xl bg-white shadow-2xl ring-1 ring-att-100"
      >
        <header className="relative shrink-0 border-b border-att-100 bg-gradient-to-r from-att-50 via-white to-white px-6 pb-4 pt-5">
          <div className="absolute inset-x-0 top-0 h-1 bg-gradient-to-r from-att-300 via-att-500 to-att-300" />
          <div className="flex items-start gap-4">
            <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-xl bg-att-100 text-att-700">{icon}</div>
            <div className="min-w-0 flex-1">
              <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-att-600">{kind}</p>
              <div className="mt-0.5 flex min-w-0 items-center gap-2">
                <h2 id={titleId} className="truncate font-mono text-lg font-semibold text-slate-900" title={name}>
                  {name}
                </h2>
                <CopyButton value={name} />
                {status}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-slate-500">
                {namespace && (
                  <span>
                    Namespace <span className="font-medium text-slate-700">{namespace}</span>
                  </span>
                )}
                {meta}
              </div>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              {actions}
              <button
                type="button"
                onClick={onClose}
                aria-label="Close"
                className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-600"
              >
                <svg width={18} height={18} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" /></svg>
              </button>
            </div>
          </div>
        </header>

        <nav className="flex shrink-0 gap-1 overflow-x-auto border-b border-att-100 bg-white px-6" role="tablist">
          {tabs.map((t) => {
            const active = t.key === activeTab;
            return (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={active}
                aria-label={t.count === undefined ? t.label : `${t.label} (${t.count})`}
                onClick={() => onTabChange(t.key)}
                className={`-mb-px flex items-center gap-2 whitespace-nowrap border-b-2 px-3 py-3 text-sm transition-colors ${
                  active ? "border-att-500 font-semibold text-att-700" : "border-transparent text-slate-500 hover:text-slate-800"
                }`}
              >
                {t.label}
                {t.count !== undefined && (
                  <span
                    aria-hidden="true"
                    className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${
                      t.attention ? "bg-amber-100 text-amber-800" : active ? "bg-att-100 text-att-700" : "bg-slate-100 text-slate-600"
                    }`}
                  >
                    {t.count}
                  </span>
                )}
              </button>
            );
          })}
        </nav>

        <div className="flex-1 overflow-y-auto bg-slate-50/70 px-6 py-5">
          {isLoading ? (
            <div className="flex items-center justify-center gap-2 py-16 text-sm text-slate-500">
              <Spinner className="h-5 w-5" />
              Loading {kind.toLowerCase()} details…
            </div>
          ) : error ? (
            <div className="rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">{error}</div>
          ) : (
            <div className="space-y-5">{children}</div>
          )}
        </div>
      </div>
    </div>
  );
}

/** White content card used for every section of a detail view. */
export function DetailCard({
  title,
  subtitle,
  actions,
  children,
}: {
  title: string;
  subtitle?: React.ReactNode;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-att-100 bg-white shadow-sm">
      <header className="flex flex-wrap items-center justify-between gap-3 border-b border-att-100 px-4 py-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
          {subtitle && <p className="text-xs text-slate-500">{subtitle}</p>}
        </div>
        {actions}
      </header>
      <div className="px-4 py-4">{children}</div>
    </section>
  );
}

export interface Property {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
  /** Span both columns (long values). */
  wide?: boolean;
}

/** Labelled facts in a two-column grid — easier to scan than label/value rows. */
export function PropertyList({ items }: { items: (Property | false | null | undefined)[] }) {
  return (
    <dl className="grid grid-cols-1 gap-x-8 gap-y-4 sm:grid-cols-2">
      {items.filter((i): i is Property => !!i).map((item) => (
        <div key={item.label} className={`min-w-0 ${item.wide ? "sm:col-span-2" : ""}`}>
          <dt className="text-[11px] font-semibold uppercase tracking-wide text-slate-500">{item.label}</dt>
          <dd className={`mt-1 break-words text-sm text-slate-800 ${item.mono ? "font-mono text-xs" : ""}`}>
            {item.value === null || item.value === undefined || item.value === "" ? <span className="text-slate-400">—</span> : item.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** Row of MetricCards at the top of an Overview tab. */
export function KpiRow({ children }: { children: React.ReactNode }) {
  return <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">{children}</div>;
}

export default ResourceDetailShell;
