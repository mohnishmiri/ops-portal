/**
 * Shared building blocks for the My Access and Access Management pages:
 * badges, the ATT grid header / pager, a search + sort + paginate hook,
 * action icons, and a small modal.
 */

import React, { useEffect, useMemo, useState } from "react";
import { gridStyles, type SortState, nextSortState } from "../../components/gridStyles";
import { TIER_LABELS } from "../../components/TierBadge";
import type {
  AccessGrant,
  AccessLevel,
  RequestItemStatus,
  RequestStatus,
  Tier,
} from "../../services/accessApi";

export const ACCESS_PAGE_SIZE = 10;

// ── Form styles (match PermissionsManagement) ────────────────────────────────

export const fieldLabel = "block text-xs font-medium text-gray-600 mb-1";
export const inputClass =
  "w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-att-400 focus:outline-none";
export const compactSelectClass =
  "px-2 py-1.5 border border-att-200 rounded-lg text-sm bg-white focus:ring-2 focus:ring-att-100 focus:border-att-400 focus:outline-none disabled:opacity-50";
export const primaryButton =
  "inline-flex items-center justify-center gap-2 px-4 py-2 bg-att-400 text-white rounded-lg text-sm font-semibold hover:bg-att-500 disabled:opacity-50 transition";
export const secondaryButton =
  "inline-flex items-center justify-center gap-2 px-4 py-2 border border-att-200 bg-white text-att-700 rounded-lg text-sm font-semibold hover:bg-att-50 disabled:opacity-50 transition";
export const panelClass = "bg-white rounded-xl p-6 shadow-sm border border-att-100";

// ── Badges ───────────────────────────────────────────────────────────────────

const LEVEL_STYLES: Record<AccessLevel, string> = {
  read: "bg-green-100 text-green-700",
  write: "bg-amber-100 text-amber-700",
};

export const LEVEL_LABELS: Record<AccessLevel, string> = { read: "Read", write: "Write" };

export const LevelBadge: React.FC<{ level: AccessLevel | null | undefined }> = ({ level }) =>
  level ? (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${LEVEL_STYLES[level]}`}>
      {LEVEL_LABELS[level]}
    </span>
  ) : (
    <span className="text-xs text-gray-400">—</span>
  );

const STATUS_STYLES: Record<RequestStatus | RequestItemStatus, string> = {
  pending: "bg-amber-100 text-amber-800",
  approved: "bg-green-100 text-green-700",
  rejected: "bg-red-100 text-red-700",
  partially_approved: "bg-sky-100 text-sky-700",
  cancelled: "bg-gray-100 text-gray-500",
};

export const STATUS_LABELS: Record<RequestStatus | RequestItemStatus, string> = {
  pending: "Pending",
  approved: "Approved",
  rejected: "Rejected",
  partially_approved: "Partially approved",
  cancelled: "Cancelled",
};

export const StatusBadge: React.FC<{ status: RequestStatus | RequestItemStatus; title?: string }> = ({
  status,
  title,
}) => (
  <span
    title={title}
    className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold whitespace-nowrap ${
      STATUS_STYLES[status] ?? "bg-gray-100 text-gray-600"
    }`}
  >
    {STATUS_LABELS[status] ?? status}
  </span>
);

export const EveryoneBadge: React.FC = () => (
  <span
    className="inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold bg-amber-100 text-amber-800"
    title="Transition grant — applies to every signed-in user"
  >
    Everyone
  </span>
);

// ── Formatting ───────────────────────────────────────────────────────────────

/** Backend timestamps are naive UTC ISO strings; read them as UTC. */
export function fmtWhen(iso: string | null | undefined): string {
  if (!iso) return "—";
  const hasZone = /[zZ]|[+-]\d{2}:?\d{2}$/.test(iso);
  const date = new Date(hasZone ? iso : `${iso}Z`);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** What a grant or request line covers below the project: an app, a subscription, or all apps. */
export function grantTargetLabel(grant: Pick<AccessGrant, "scope_type" | "app_name" | "subscription_name" | "subscription_id">): string {
  if (grant.scope_type === "app") return grant.app_name ?? "—";
  if (grant.scope_type === "subscription") return grant.subscription_name ?? grant.subscription_id ?? "—";
  return "All apps";
}

export function tierLabel(tier: Tier | null | undefined): string {
  return tier ? TIER_LABELS[tier] : "";
}

/** KPI value for a subscription count; null means unrestricted (Super Admin). */
export function countLabel(count: number | null | undefined, loading: boolean): React.ReactNode {
  if (loading) return "…";
  if (count === null) return "All";
  return count ?? 0;
}

/**
 * Plain-English summary of active "everyone" (transition) grants, grouped so
 * Prod and Non-Prod on the same project read as one phrase:
 * "write access to Commissions Prod and Non-Prod".
 */
export function describeEveryoneGrants(grants: AccessGrant[]): string[] {
  const groups = new Map<string, { label: string; level: AccessLevel; tiers: Set<Tier> }>();
  for (const grant of grants) {
    if (grant.subject_type !== "everyone") continue;
    const target =
      grant.scope_type === "project"
        ? grant.project_name ?? "a project"
        : `${grant.project_name ?? ""} ${grantTargetLabel(grant)}`.trim();
    const key = `${grant.level}|${grant.scope_type}|${grant.project_id}|${grant.app_id}|${grant.subscription_id}`;
    const group = groups.get(key) ?? { label: target, level: grant.level, tiers: new Set<Tier>() };
    if (grant.tier) group.tiers.add(grant.tier);
    groups.set(key, group);
  }
  return Array.from(groups.values()).map(({ label, level, tiers }) => {
    const tierText = (["prod", "nonprod"] as Tier[])
      .filter((tier) => tiers.has(tier))
      .map((tier) => TIER_LABELS[tier])
      .join(" and ");
    return `${level} access to ${label}${tierText ? ` ${tierText}` : ""}`;
  });
}

// ── Grid state: search → sort → paginate ─────────────────────────────────────

export function useGridRows<T, K extends string>(
  rows: T[],
  options: {
    matches: (row: T, query: string) => boolean;
    accessor: (row: T, key: K) => string | number;
    initialSort: SortState<K>;
    pageSize?: number;
  },
) {
  const { matches, accessor, initialSort, pageSize = ACCESS_PAGE_SIZE } = options;
  const [search, setSearchState] = useState("");
  const [sort, setSort] = useState<SortState<K>>(initialSort);
  const [page, setPage] = useState(0);

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return query ? rows.filter((row) => matches(row, query)) : rows;
  }, [rows, search, matches]);

  const sorted = useMemo(() => {
    const dir = sort.direction === "asc" ? 1 : -1;
    return [...filtered].sort((a, b) => {
      const av = accessor(a, sort.key);
      const bv = accessor(b, sort.key);
      if (typeof av === "number" && typeof bv === "number") return (av - bv) * dir;
      return String(av).localeCompare(String(bv), undefined, { numeric: true }) * dir;
    });
  }, [filtered, sort, accessor]);

  const totalPages = Math.max(1, Math.ceil(sorted.length / pageSize));
  const safePage = Math.min(page, totalPages - 1);

  // Data shrinking under the current page (a revoke, a filter) snaps back.
  useEffect(() => {
    if (page !== safePage) setPage(safePage);
  }, [page, safePage]);

  const pageRows = useMemo(
    () => sorted.slice(safePage * pageSize, (safePage + 1) * pageSize),
    [sorted, safePage, pageSize],
  );

  return {
    search,
    setSearch: (value: string) => {
      setSearchState(value);
      setPage(0);
    },
    sort,
    toggleSort: (key: K) => setSort((current) => nextSortState(current, key)),
    page: safePage,
    setPage,
    totalPages,
    total: sorted.length,
    pageRows,
    pageSize,
  };
}

/** Lower-cased haystack check across several fields. */
export function textMatches(query: string, ...values: Array<string | number | null | undefined>): boolean {
  return values.some((value) => value != null && String(value).toLowerCase().includes(query));
}

// ── Grid chrome ──────────────────────────────────────────────────────────────

export const GridHeader: React.FC<{
  title: string;
  subtitle?: React.ReactNode;
  search: string;
  onSearch: (value: string) => void;
  placeholder?: string;
  children?: React.ReactNode;
}> = ({ title, subtitle, search, onSearch, placeholder = "Search…", children }) => (
  <div className={gridStyles.panelHeader}>
    <div className="min-w-0">
      <h2 className={gridStyles.sectionTitle}>{title}</h2>
      {subtitle ? <p className="text-xs text-gray-500 mt-0.5">{subtitle}</p> : null}
    </div>
    <div className="flex flex-wrap items-center gap-2">
      {children}
      <input
        type="search"
        value={search}
        onChange={(event) => onSearch(event.target.value)}
        placeholder={placeholder}
        aria-label={`Search ${title}`}
        className={gridStyles.toolbarInput}
      />
    </div>
  </div>
);

export const GridPagerBar: React.FC<{
  page: number;
  totalPages: number;
  total: number;
  pageSize: number;
  onPage: (page: number) => void;
  noun?: string;
}> = ({ page, totalPages, total, pageSize, onPage, noun = "rows" }) => (
  <div className={gridStyles.pager}>
    <span className="text-gray-600">
      {total === 0
        ? `Showing 0 ${noun}`
        : `Showing ${page * pageSize + 1}–${Math.min((page + 1) * pageSize, total)} of ${total} ${noun}`}
    </span>
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={() => onPage(Math.max(0, page - 1))}
        disabled={page === 0}
        className={gridStyles.pagerButton}
      >
        Previous
      </button>
      <span className="text-gray-700">
        Page {page + 1} of {totalPages}
      </span>
      <button
        type="button"
        onClick={() => onPage(Math.min(totalPages - 1, page + 1))}
        disabled={page >= totalPages - 1}
        className={gridStyles.pagerButton}
      >
        Next
      </button>
    </div>
  </div>
);

export const GridMessageRow: React.FC<{ colSpan: number; children: React.ReactNode; tone?: "muted" | "error" }> = ({
  colSpan,
  children,
  tone = "muted",
}) => (
  <tr>
    <td colSpan={colSpan} className={`px-4 py-8 text-center text-sm ${tone === "error" ? "text-red-600" : "text-gray-400"}`}>
      {children}
    </td>
  </tr>
);

// ── Icons & action buttons (UI_Buddy grid action spec: 18×18, semantic colour, title) ──

const svgProps = {
  xmlns: "http://www.w3.org/2000/svg",
  viewBox: "0 0 24 24",
  fill: "none",
  stroke: "currentColor",
  strokeWidth: 2,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export const AccessIcons = {
  approve: (size = 18) => (
    <svg {...svgProps} width={size} height={size}>
      <path d="M20 6 9 17l-5-5" />
    </svg>
  ),
  reject: (size = 18) => (
    <svg {...svgProps} width={size} height={size}>
      <circle cx="12" cy="12" r="9" />
      <path d="m15 9-6 6M9 9l6 6" />
    </svg>
  ),
  delete: (size = 18) => (
    <svg {...svgProps} width={size} height={size}>
      <polyline points="3 6 5 6 21 6" />
      <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
    </svg>
  ),
  cancel: (size = 18) => (
    <svg {...svgProps} width={size} height={size}>
      <circle cx="12" cy="12" r="9" />
      <path d="M5.6 5.6l12.8 12.8" />
    </svg>
  ),
  save: (size = 18) => (
    <svg {...svgProps} width={size} height={size}>
      <path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2Z" />
      <path d="M17 21v-8H7v8M7 3v5h8" />
    </svg>
  ),
  wand: (size = 18) => (
    <svg {...svgProps} width={size} height={size}>
      <path d="m15 4 5 5L9 20H4v-5L15 4Z" />
      <path d="M19 2v3M17.5 3.5h3" />
    </svg>
  ),
  plus: (size = 16) => (
    <svg {...svgProps} width={size} height={size}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  ),
  userPlus: (size = 18) => (
    <svg {...svgProps} width={size} height={size}>
      <path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M19 8v6M22 11h-6" />
    </svg>
  ),
  power: (size = 18) => (
    <svg {...svgProps} width={size} height={size}>
      <path d="M18.36 6.64a9 9 0 1 1-12.73 0" />
      <path d="M12 2v10" />
    </svg>
  ),
  key: (cls = "h-5 w-5") => (
    <svg {...svgProps} className={cls}>
      <circle cx="7.5" cy="15.5" r="4.5" />
      <path d="m10.7 12.3 9.8-9.8M17 6l3 3M14.5 8.5l2 2" />
    </svg>
  ),
  users: (cls = "h-5 w-5") => (
    <svg {...svgProps} className={cls}>
      <path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2" />
      <circle cx="9" cy="7" r="4" />
      <path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" />
    </svg>
  ),
  inbox: (cls = "h-5 w-5") => (
    <svg {...svgProps} className={cls}>
      <path d="M22 12h-6l-2 3h-4l-2-3H2" />
      <path d="M5.45 5.11 2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11Z" />
    </svg>
  ),
  folder: (cls = "h-5 w-5") => (
    <svg {...svgProps} className={cls}>
      <path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2Z" />
    </svg>
  ),
  pen: (cls = "h-5 w-5") => (
    <svg {...svgProps} className={cls}>
      <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" />
      <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5Z" />
    </svg>
  ),
};

const ACTION_TONES = {
  green: "text-green-600 hover:bg-green-50",
  red: "text-red-600 hover:bg-red-50",
  blue: "text-blue-600 hover:bg-blue-50",
  att: "text-att-600 hover:bg-att-50",
  gray: "text-gray-600 hover:bg-gray-50",
  amber: "text-amber-600 hover:bg-amber-50",
};

export const ActionIconButton: React.FC<{
  title: string;
  onClick: () => void;
  tone: keyof typeof ACTION_TONES;
  disabled?: boolean;
  children: React.ReactNode;
}> = ({ title, onClick, tone, disabled, children }) => (
  <button
    type="button"
    onClick={onClick}
    disabled={disabled}
    title={title}
    aria-label={title}
    className={`p-2 rounded-lg disabled:opacity-40 disabled:cursor-not-allowed ${ACTION_TONES[tone]}`}
  >
    {children}
  </button>
);

// ── Modal ────────────────────────────────────────────────────────────────────

export const Modal: React.FC<{
  title: string;
  subtitle?: React.ReactNode;
  onClose: () => void;
  children: React.ReactNode;
  footer?: React.ReactNode;
  widthClass?: string;
}> = ({ title, subtitle, onClose, children, footer, widthClass = "max-w-lg" }) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center p-4">
    <button type="button" aria-label="Close dialog" className="absolute inset-0 bg-slate-900/40 cursor-default" onClick={onClose} />
    <div role="dialog" aria-modal="true" aria-label={title} className={`relative w-full ${widthClass} rounded-2xl bg-white shadow-xl border border-att-100`}>
      <div className="border-b border-att-100 bg-att-50/70 px-5 py-4 rounded-t-2xl">
        <h3 className="text-base font-semibold text-gray-900">{title}</h3>
        {subtitle ? <div className="mt-1 text-xs text-gray-500">{subtitle}</div> : null}
      </div>
      <div className="px-5 py-4 space-y-4 max-h-[70vh] overflow-y-auto">{children}</div>
      {footer ? <div className="flex justify-end gap-2 border-t border-att-100 px-5 py-3">{footer}</div> : null}
    </div>
  </div>
);

export const ConfirmDialog: React.FC<{
  title: string;
  message: React.ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  busy?: boolean;
  error?: string | null;
  onConfirm: () => void;
  onCancel: () => void;
}> = ({ title, message, confirmLabel, cancelLabel = "Cancel", busy, error, onConfirm, onCancel }) => (
  <Modal
    title={title}
    onClose={onCancel}
    footer={
      <>
        <button type="button" onClick={onCancel} className={secondaryButton} disabled={busy}>
          {cancelLabel}
        </button>
        <button
          type="button"
          onClick={onConfirm}
          disabled={busy}
          className="inline-flex items-center justify-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-semibold hover:bg-red-700 disabled:opacity-50 transition"
        >
          {busy ? "Working…" : confirmLabel}
        </button>
      </>
    }
  >
    <div className="text-sm text-gray-700">{message}</div>
    {error ? <p className="text-xs text-red-600">{error}</p> : null}
  </Modal>
);

export const ErrorNote: React.FC<{ message: string | null | undefined }> = ({ message }) =>
  message ? (
    <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700" role="alert">
      {message}
    </div>
  ) : null;
