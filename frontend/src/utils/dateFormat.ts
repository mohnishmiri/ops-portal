/**
 * Date formatting helpers for grid display in mm-dd-YYYY format.
 */

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
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return String(value);
  const mm = String(dt.getMonth() + 1).padStart(2, "0");
  const dd = String(dt.getDate()).padStart(2, "0");
  const time = dt.toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  return `${mm}-${dd}-${dt.getFullYear()}, ${time}`;
}
