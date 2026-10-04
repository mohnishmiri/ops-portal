/**
 * Pieces shared by the Key Vault page and its drill-down views: date
 * formatting, badges, icons, Base64 helpers, and certificate search.
 * All icons are inline SVG vector icons (no emojis).
 */

import React from "react";
import type { CertificateInfo } from "../../services/costApi";

// ── Dates ─────────────────────────────────────────────────────────────

/**
 * The Key Vault API returns naive UTC timestamps ("2026-10-07T03:00:00").
 * `new Date()` would read those as *local* time and shift every value by the
 * browser's UTC offset, so a missing zone is treated as UTC.
 */
export function parseUtc(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const hasZone = /(Z|[+-]\d{2}:?\d{2})$/i.test(iso);
  const date = new Date(hasZone || !/T\d/.test(iso) ? iso : `${iso}Z`);
  return Number.isNaN(date.getTime()) ? null : date;
}

export const fmtDate = (iso: string | null | undefined, tz?: string) => {
  const date = parseUtc(iso);
  if (!date) return iso ? String(iso) : "—";
  return date.toLocaleDateString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    ...(tz ? { timeZone: tz } : {}),
  });
};

export const fmtDateTime = (iso: string | null | undefined, tz?: string) => {
  const date = parseUtc(iso);
  if (!date) return iso ? String(iso) : "—";
  return date.toLocaleString("en-US", {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    ...(tz ? { timeZone: tz, timeZoneName: "short" } : {}),
  });
};

/** Whole days until `iso` (negative once past); null when there is no date. */
export function daysUntil(iso: string | null | undefined): number | null {
  const date = parseUtc(iso);
  if (!date) return null;
  return Math.floor((date.getTime() - Date.now()) / 86_400_000);
}

// ── Badges ────────────────────────────────────────────────────────────

export type BadgeColor = "green" | "red" | "yellow" | "blue" | "gray" | "purple";

const BADGE_COLORS: Record<BadgeColor, string> = {
  green: "bg-green-100 text-green-800",
  red: "bg-red-100 text-red-800",
  yellow: "bg-yellow-100 text-yellow-800",
  blue: "bg-blue-100 text-blue-800",
  gray: "bg-gray-100 text-gray-800",
  purple: "bg-purple-100 text-purple-800",
};

export const Badge: React.FC<{ label: string; color: BadgeColor; title?: string }> = ({ label, color, title }) => (
  <span title={title} className={`whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ${BADGE_COLORS[color]}`}>
    {label}
  </span>
);

export function expiryTone(days: number | null): BadgeColor {
  if (days === null) return "gray";
  if (days <= 7) return "red";
  if (days <= 30) return "yellow";
  if (days <= 90) return "blue";
  return "gray";
}

/** "Expired 3d ago" / "12d" / "No expiry". */
export function expiryLabel(days: number | null): string {
  if (days === null) return "No expiry";
  if (days < 0) return `Expired ${Math.abs(days)}d ago`;
  return `${days}d`;
}

export const DaysLeftBadge: React.FC<{ days: number | null }> = ({ days }) => (
  <Badge label={expiryLabel(days)} color={days !== null && days < 0 ? "red" : expiryTone(days)} />
);

export const ItemTypeBadge: React.FC<{ type: string }> = ({ type }) => (
  <Badge label={type} color={type === "certificate" ? "purple" : type === "key" ? "blue" : "gray"} />
);

// ── Icons ─────────────────────────────────────────────────────────────

const svg = (size: number, cls: string, children: React.ReactNode) => (
  <svg
    xmlns="http://www.w3.org/2000/svg"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="2"
    strokeLinecap="round"
    strokeLinejoin="round"
    width={size}
    height={size}
    className={cls}
  >
    {children}
  </svg>
);

export const Icons = {
  vault: (cls = "") => svg(20, cls, <><rect x="3" y="11" width="18" height="11" rx="2" ry="2" /><path d="M7 11V7a5 5 0 0 1 10 0v4" /></>),
  secret: (cls = "") =>
    svg(20, cls, <><path d="m15.5 7.5 2.3 2.3a1 1 0 0 0 1.4 0l2.1-2.1a1 1 0 0 0 0-1.4L19 4" /><path d="m21 2-9.6 9.6" /><circle cx="7.5" cy="15.5" r="5.5" /><path d="m5.5 17.5 1-1" /></>),
  key: (cls = "") => svg(20, cls, <path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4" />),
  certificate: (cls = "") =>
    svg(20, cls, <><path d="M15 12a3 3 0 1 1-6 0 3 3 0 0 1 6 0Z" /><path d="M12 4v1m0 14v1m8-8h-1M5 12H4m13.66-5.66-.71.71M6.34 17.66l-.71.71m12.73.01-.71-.71M6.34 6.34l-.71-.71" /><rect x="2" y="2" width="20" height="20" rx="3" /></>),
  shield: (cls = "") => svg(20, cls, <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />),
  warning: (cls = "") =>
    svg(20, cls, <><path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" /></>),
  expired: (cls = "") => svg(20, cls, <><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 3" /><path d="M4 4l16 16" /></>),
  clipboard: (cls = "") =>
    svg(20, cls, <><rect x="9" y="2" width="6" height="4" rx="1" /><path d="M16 4h2a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2h2" /><path d="M12 11h4" /><path d="M12 16h4" /><path d="M8 11h.01" /><path d="M8 16h.01" /></>),
  eye: (cls = "") => svg(18, cls, <><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" /></>),
  edit: (cls = "") => svg(18, cls, <><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z" /></>),
  trash: (cls = "") => svg(18, cls, <><polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" /></>),
  plus: (cls = "") => svg(18, cls, <><line x1="12" y1="5" x2="12" y2="19" /><line x1="5" y1="12" x2="19" y2="12" /></>),
  fingerprint: (cls = "") =>
    svg(20, cls, <><path d="M2 12C2 6.5 6.5 2 12 2a10 10 0 0 1 8 4" /><path d="M5 19.5C5.5 18 6 15 6 12c0-.7.12-1.37.34-2" /><path d="M17.29 21.02c.12-.6.43-2.3.5-3.02" /><path d="M12 10a2 2 0 0 0-2 2c0 1.02-.1 2.51-.26 4" /><path d="M8.65 22c.21-.66.45-1.32.57-2" /><path d="M14 13.12c0 2.38 0 6.38-1 8.88" /><path d="M2 16h.01" /><path d="M21.8 16c.2-2 .131-5.354 0-6" /><path d="M9 6.8a6 6 0 0 1 9 5.2c0 .47 0 1.17-.02 2" /></>),
  copy: (cls = "") => svg(18, cls, <><rect x="9" y="9" width="13" height="13" rx="2" ry="2" /><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" /></>),
  refresh: (cls = "") =>
    svg(18, cls, <><polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" /><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15" /></>),
  history: (cls = "") => svg(20, cls, <><path d="M3 12a9 9 0 1 0 3-6.7" /><path d="M3 4v5h5" /><path d="M12 7v5l3 3" /></>),
  external: (cls = "") => svg(14, cls, <><path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" /><polyline points="15 3 21 3 21 9" /><line x1="10" y1="14" x2="21" y2="3" /></>),
};

// ── Base64 (UTF-8 aware) ──────────────────────────────────────────────

/**
 * Decode Base64 to UTF-8 text. `atob` alone yields a binary string, which
 * garbles any non-ASCII text; null when the value is not Base64 or is binary.
 */
export function decodeBase64Utf8(value: string): string | null {
  const compact = value.replace(/\s+/g, "");
  if (!compact || compact.length % 4 === 1 || !/^[A-Za-z0-9+/_-]+={0,2}$/.test(compact)) return null;
  try {
    const binary = atob(compact.replace(/-/g, "+").replace(/_/g, "/"));
    const bytes = Uint8Array.from(binary, (c) => c.charCodeAt(0));
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return null;
  }
}

/** Encode text as Base64 over its UTF-8 bytes (`btoa` throws on non-Latin-1). */
export function encodeBase64Utf8(value: string): string {
  const bytes = new TextEncoder().encode(value);
  let binary = "";
  bytes.forEach((b) => {
    binary += String.fromCharCode(b);
  });
  return btoa(binary);
}

// ── Certificate search ────────────────────────────────────────────────

export type CertificateSearchField = "all" | "name" | "cn" | "san" | "serial" | "thumbprint" | "tags";

export const CERTIFICATE_SEARCH_FIELDS: { value: CertificateSearchField; label: string }[] = [
  { value: "all", label: "Search: All fields" },
  { value: "name", label: "Search: Name" },
  { value: "cn", label: "Search: CN" },
  { value: "san", label: "Search: SAN" },
  { value: "serial", label: "Search: Serial" },
  { value: "thumbprint", label: "Search: Thumbprint" },
  { value: "tags", label: "Search: Tags" },
];

/** Hex identifiers are shown with or without colons/spaces; compare them bare. */
const bareHex = (value: string) => value.replace(/[\s:]/g, "").toLowerCase();

/** Fields of `cert` that contain `term` (case-insensitive); empty when none do. */
export function certificateMatchFields(
  cert: Pick<CertificateInfo, "name" | "cn_name" | "san" | "serial_number" | "thumbprint" | "tags">,
  term: string,
  field: CertificateSearchField = "all",
): Exclude<CertificateSearchField, "all">[] {
  const q = term.trim().toLowerCase();
  if (!q) return [];
  const hexQ = bareHex(q);
  const checks: Record<Exclude<CertificateSearchField, "all">, () => boolean> = {
    name: () => (cert.name || "").toLowerCase().includes(q),
    cn: () => (cert.cn_name || "").toLowerCase().includes(q),
    san: () => (cert.san || []).some((s) => s.toLowerCase().includes(q)),
    serial: () => !!hexQ && bareHex(cert.serial_number || "").includes(hexQ),
    thumbprint: () => !!hexQ && bareHex(cert.thumbprint || "").includes(hexQ),
    tags: () => Object.entries(cert.tags || {}).some(([k, v]) => `${k}=${v}`.toLowerCase().includes(q)),
  };
  const fields = field === "all" ? (Object.keys(checks) as Exclude<CertificateSearchField, "all">[]) : [field];
  return fields.filter((f) => checks[f]());
}

/** `text` with every case-insensitive occurrence of `term` marked. */
export function Highlight({ text, term }: { text: string; term: string }) {
  const q = term.trim().toLowerCase();
  if (!q || !text) return <>{text}</>;
  const lower = text.toLowerCase();
  const parts: React.ReactNode[] = [];
  let from = 0;
  for (let at = lower.indexOf(q); at >= 0; at = lower.indexOf(q, from)) {
    if (at > from) parts.push(text.slice(from, at));
    parts.push(
      <mark key={at} className="rounded bg-amber-100 px-0.5 text-inherit">
        {text.slice(at, at + q.length)}
      </mark>,
    );
    from = at + q.length;
  }
  if (from < text.length) parts.push(text.slice(from));
  return <>{parts}</>;
}

// ── Misc ──────────────────────────────────────────────────────────────

/** "https://my-kv.vault.azure.net/" -> "my-kv" */
export const vaultNameFromUri = (uri: string | null | undefined) =>
  (uri || "").replace(/^https?:\/\//, "").split(".")[0] || "this vault";

/** Azure portal page for an ARM resource ID (optionally a sub-blade such as "secrets"). */
export const azurePortalUrl = (resourceId: string, blade?: string) =>
  `https://portal.azure.com/#@/resource${resourceId}${blade ? `/${blade}` : ""}`;

/** Link-styled button used for clickable names, like the AKS grids. */
export const nameLinkClass = "text-left font-medium text-blue-600 hover:text-blue-800 hover:underline focus:outline-none focus-visible:underline";
