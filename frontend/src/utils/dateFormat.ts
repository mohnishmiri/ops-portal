/**
 * Date formatting helpers for grid display in mm-dd-YYYY format, and the
 * shared parser every date formatter in the portal goes through.
 */

const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/;
const NAIVE_DATETIME = /^(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?)$/;

/** "2026-10-07" — a calendar date with no time of day. */
export function isDateOnly(value: unknown): value is string {
  return typeof value === "string" && DATE_ONLY.test(value.trim());
}

/**
 * Parse a timestamp from the API.
 *
 * The backend stores and returns UTC, usually without a zone
 * ("2026-10-07T03:00:00" from `datetime.utcnow().isoformat()`). `new Date()`
 * reads a zone-less date-time as *local* time, which shifts every value by
 * the browser's UTC offset — so zone-less values are read as UTC here.
 * Values that carry a zone (Z, +05:30) are taken as they are.
 */
export function parseApiDate(value: string | Date | null | undefined): Date | null {
  if (value === null || value === undefined || value === "") return null;
  if (value instanceof Date) return Number.isNaN(value.getTime()) ? null : value;
  const text = String(value).trim();
  const naive = NAIVE_DATETIME.exec(text);
  const date = new Date(naive ? `${naive[1]}T${naive[2]}Z` : text);
  return Number.isNaN(date.getTime()) ? null : date;
}

/**
 * Format an ISO date/datetime as mm-dd-YYYY.
 *
 * Date-only values keep their calendar date (parsed from the leading
 * YYYY-MM-DD) so certificate validity dates are never shifted by a day due to
 * timezone conversion.
 */
export function formatDate(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const isoDate = /^(\d{4})-(\d{2})-(\d{2})/.exec(String(value));
  if (isoDate) {
    const [, year, month, day] = isoDate;
    return `${month}-${day}-${year}`;
  }
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return String(value);
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const dd = String(dt.getDate()).padStart(2, "0");
  return `${mm}-${dd}-${dt.getFullYear()}`;
}

/**
 * Format an ISO datetime as mm-dd-YYYY with the local time retained
 * (used for audit / last-run columns where the time of day is meaningful).
 */
export function formatDateTime(value: string | Date | null | undefined): string {
  if (!value) return "—";
  const dt = parseApiDate(value);
  if (!dt) return String(value);
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const dd = String(dt.getDate()).padStart(2, "0");
  const time = dt.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  return `${mm}-${dd}-${dt.getFullYear()}, ${time}`;
}
