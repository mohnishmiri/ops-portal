/**
 * "Download all logs" for AKS workloads and pods.
 *
 * The page owns a single download (useLogArchiveDownload) so it survives the
 * user closing the modal that started it; LogArchiveProgress shows progress
 * and a cancel action wherever the user is on the page.
 */

import React, { useCallback, useRef, useState } from "react";
import { Spinner } from "../../components/gridStyles";
import { downloadLogArchive, LogArchiveRequest, MAX_LOG_ARCHIVE_PODS } from "../../services/aksApi";
import { DetailIcons } from "./detailShared";

export type LogArchiveDownload = ReturnType<typeof useLogArchiveDownload>;

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function useLogArchiveDownload(showToast: (msg: string, type?: "success" | "error") => void) {
  const [active, setActive] = useState<{ key: string; label: string; bytes: number } | null>(null);
  const controllerRef = useRef<AbortController | null>(null);

  const start = useCallback(
    async (key: string, request: LogArchiveRequest, label: string) => {
      if (controllerRef.current) return; // one archive at a time
      const controller = new AbortController();
      controllerRef.current = controller;
      setActive({ key, label, bytes: 0 });
      try {
        const { blob, filename } = await downloadLogArchive(request, {
          signal: controller.signal,
          onProgress: (bytes) => setActive({ key, label, bytes }),
        });
        saveBlob(blob, filename);
        showToast(`Downloaded complete logs for ${label} (${formatBytes(blob.size)})`);
      } catch (err) {
        if (!controller.signal.aborted) {
          showToast(err instanceof Error ? err.message : "Log download failed", "error");
        }
      } finally {
        controllerRef.current = null;
        setActive(null);
      }
    },
    [showToast]
  );

  const cancel = useCallback(() => controllerRef.current?.abort(), []);

  return { active, start, cancel };
}

const LOG_ARCHIVE_HELP =
  "Downloads a ZIP with the complete log of every container since it started (init containers included), " +
  "the previous instance of any restarted container, and a SUMMARY.txt.";

export function DownloadLogsButton({
  download,
  downloadKey,
  request,
  label,
  podCount,
  confirm,
  variant = "button",
}: {
  download: LogArchiveDownload;
  /** Identifies this target so only its button shows progress. */
  downloadKey: string;
  request: LogArchiveRequest;
  /** Human-readable target used in toasts, e.g. "Deployment apps/web". */
  label: string;
  podCount?: number;
  /** Optional gate (e.g. a confirmation dialog) before the download starts. */
  confirm?: (proceed: () => void) => void;
  variant?: "button" | "icon";
}) {
  const busyHere = download.active?.key === downloadKey;
  const busyElsewhere = !!download.active && !busyHere;
  const noPods = podCount === 0;
  const tooMany = podCount !== undefined && podCount > MAX_LOG_ARCHIVE_PODS;
  const disabled = busyHere || busyElsewhere || noPods || tooMany;
  const title = noPods
    ? "No pods — there are no logs to download"
    : tooMany
      ? `Log archives are limited to ${MAX_LOG_ARCHIVE_PODS} pods — narrow the selection`
      : busyElsewhere
        ? "Another log download is in progress"
        : LOG_ARCHIVE_HELP;
  const onClick = () => {
    const proceed = () => void download.start(downloadKey, request, label);
    if (confirm) confirm(proceed);
    else proceed();
  };

  if (variant === "icon") {
    return (
      <button
        type="button"
        onClick={onClick}
        disabled={disabled}
        title={busyHere ? "Downloading logs…" : `Download all logs. ${title}`}
        aria-label="Download all logs"
        className="p-2 text-sky-700 hover:bg-sky-50 rounded-lg disabled:opacity-40"
      >
        {busyHere ? <Spinner className="h-[18px] w-[18px]" /> : DetailIcons.download}
      </button>
    );
  }

  const text = podCount === undefined ? "Download all logs" : `Download all logs (${podCount} pod${podCount === 1 ? "" : "s"})`;
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={title}
      className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-att-200 text-sm text-att-700 hover:bg-att-50 disabled:opacity-50"
    >
      {busyHere ? <Spinner className="h-4 w-4" /> : DetailIcons.download}
      {busyHere ? `Downloading… ${formatBytes(download.active?.bytes ?? 0)}` : text}
    </button>
  );
}

/** Floating progress for the page's log download, visible even after its modal is closed. */
export function LogArchiveProgress({ download }: { download: LogArchiveDownload }) {
  if (!download.active) return null;
  return (
    <div className="fixed bottom-6 left-6 z-[95] flex max-w-md items-center gap-3 rounded-xl border border-att-200 bg-white px-4 py-3 shadow-lg" role="status">
      <Spinner className="h-5 w-5 shrink-0" />
      <div className="min-w-0 text-sm">
        <p className="font-semibold text-gray-900 truncate">Collecting logs: {download.active.label}</p>
        <p className="text-gray-500">{formatBytes(download.active.bytes)} received — the archive is saved when complete</p>
      </div>
      <button type="button" onClick={download.cancel} className="ml-2 rounded-lg border px-3 py-1.5 text-sm text-gray-700 hover:bg-gray-50">
        Cancel
      </button>
    </div>
  );
}
