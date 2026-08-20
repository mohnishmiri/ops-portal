/**
 * Client-side CSV export helpers.
 *
 * Produces Excel-friendly output: a UTF-8 BOM (so accented/unicode characters
 * render correctly), CRLF line endings, and RFC 4180 quoting so values that
 * contain commas, quotes, or newlines survive intact.
 */

export interface CsvColumn<T> {
  /** Column header shown in the exported file. */
  header: string;
  /** Extracts the cell value for a row. */
  value: (row: T) => string | number | boolean | null | undefined;
}

/** Quote a single field per RFC 4180 when it contains a delimiter/quote/newline. */
function escapeCsvField(value: string | number | boolean | null | undefined): string {
  if (value == null) return "";
  const str = String(value);
  return /[",\r\n]/.test(str) ? `"${str.replace(/"/g, '""')}"` : str;
}

/** Build an RFC 4180 CSV string (CRLF line endings) from rows + column defs. */
export function toCsv<T>(rows: T[], columns: CsvColumn<T>[]): string {
  const header = columns.map((c) => escapeCsvField(c.header)).join(",");
  const body = rows.map((row) => columns.map((c) => escapeCsvField(c.value(row))).join(","));
  return [header, ...body].join("\r\n");
}

/** Trigger a browser download of CSV content as a UTF-8 (BOM) file. */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob(["\uFEFF", csv], { type: "text/csv;charset=utf-8;" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

/** Build and download a CSV in one call, appending a timestamp to the file name. */
export function exportToCsv<T>(baseName: string, rows: T[], columns: CsvColumn<T>[]): void {
  const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
  downloadCsv(`${baseName}-${stamp}.csv`, toCsv(rows, columns));
}
