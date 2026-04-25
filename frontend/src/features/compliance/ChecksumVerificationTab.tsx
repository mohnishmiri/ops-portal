/**
 * ChecksumVerificationTab — Synapse pipeline checksum verification
 *
 * Extracted from the monolithic CompliancePage.tsx.
 * Handles workspace selection, verification runs, metrics display,
 * results table (shell-script HTML theme), CSV download, and email.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../../contexts/AuthContext";
import {
  useChecksumResults,
  useChecksumRuns,
  useChecksumMetrics,
  useRunChecksumVerification,
  useDownloadChecksumCsv,
  useEmailChecksumResults,
  refreshChecksumResults,
  type ChecksumResultItem,
  type ChecksumRun,
} from "../../services/complianceApi";
import WorkspaceSelector from "./WorkspaceSelector";
import { AutoRefreshIndicator, gridStyles, nextSortState, SortableHeader, type SortState } from "../../components/gridStyles";
import { usePortalTimezone } from "../../contexts/TimezoneContext";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

/* ── Constants ──────────────────────────────────────────────────────── */

const PAGE_SIZE = 20;

const DATE_RANGE_OPTIONS = [
  { label: "7 days", value: 7 },
  { label: "14 days", value: 14 },
  { label: "20 days", value: 20 },
  { label: "30 days", value: 30 },
  { label: "60 days", value: 60 },
  { label: "90 days", value: 90 },
];

type RunsSortKey =
  | "workspace_name"
  | "system"
  | "environment"
  | "execution_date"
  | "total_pipelines"
  | "passed"
  | "failed"
  | "status";

type PipelineSortKey =
  | "pipeline_name"
  | "yesterday_hash"
  | "present_hash"
  | "last_published_date"
  | "result";

/* ── Local Icons (only what this tab needs) ─────────────────────────── */

const Icons = {
  scan: (cls = "") => (
    <svg className={cls} xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="11" cy="11" r="8" /><line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  ),
  refresh: (cls = "") => (
    <svg className={cls} xmlns="http://www.w3.org/2000/svg" width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 4 23 10 17 10" /><polyline points="1 20 1 14 7 14" />
      <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15" />
    </svg>
  ),
};

/* ── Props ──────────────────────────────────────────────────────────── */

interface ChecksumVerificationTabProps {
  onShowToast: (message: string, type?: "success" | "error" | "warning" | "info") => void;
}

/* ── Component ──────────────────────────────────────────────────────── */

export default function ChecksumVerificationTab({ onShowToast }: ChecksumVerificationTabProps) {
  const queryClient = useQueryClient();
  const { timezone, formatDate } = usePortalTimezone();
  const { canWrite } = useAuth();

  // ── Local state ────────────────────────────────────────────────────
  const [checksumWorkspace, setChecksumWorkspace] = useState<string | null>(null);
  const [lastRunId, setLastRunId] = useState<string | null>(null);
  const [checksumEmailAddr, setChecksumEmailAddr] = useState("");
  const [dateRangeDays, setDateRangeDays] = useState(30);
  const [pipelineSearch, setPipelineSearch] = useState("");
  const [pipelinePage, setPipelinePage] = useState(0);
  const [runsSearch, setRunsSearch] = useState("");
  const [runsPage, setRunsPage] = useState(0);
  const [runsSort, setRunsSort] = useState<SortState<RunsSortKey>>({
    key: "execution_date",
    direction: "desc",
  });
  const [pipelineSort, setPipelineSort] = useState<SortState<PipelineSortKey>>({
    key: "pipeline_name",
    direction: "asc",
  });

  // ── Queries ────────────────────────────────────────────────────────
  const { data: checksumResults, isLoading: loadingChecksumResults } = useChecksumResults(
    checksumWorkspace
      ? { workspace_name: checksumWorkspace, days: dateRangeDays, module_type: "synapse" }
      : { days: dateRangeDays, module_type: "synapse" },
  );
  const { data: checksumRuns } = useChecksumRuns({ days: dateRangeDays, module_type: "synapse" });
  const { data: checksumMetrics } = useChecksumMetrics(dateRangeDays, "synapse");

  // ── Mutations ──────────────────────────────────────────────────────
  const runChecksumMutation = useRunChecksumVerification();
  const downloadChecksumCsvMutation = useDownloadChecksumCsv();
  const emailChecksumMutation = useEmailChecksumResults();

  // ── Handlers ───────────────────────────────────────────────────────
  const handleRunChecksum = useCallback(async () => {
    try {
      const result = await runChecksumMutation.mutateAsync({
        workspaceName: checksumWorkspace ?? "",
        ...(checksumEmailAddr ? { notification_emails: [checksumEmailAddr] } : {}),
      });
      setLastRunId(result.run_id);
      const emailNote = checksumEmailAddr ? ` — report emailed to ${checksumEmailAddr}` : "";
      onShowToast(`Checksum verification complete: ${result.passed} PASS, ${result.failed} FAIL${emailNote}`);
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Checksum verification failed";
      onShowToast(msg, "error");
    }
  }, [checksumWorkspace, checksumEmailAddr, runChecksumMutation, onShowToast]);

  const handleDownloadCsv = useCallback(() => {
    if (!lastRunId) {
      onShowToast("No results to download. Run a verification first.", "warning");
      return;
    }
    downloadChecksumCsvMutation.mutate(lastRunId, {
      onSuccess: () => onShowToast("CSV downloaded"),
      onError: () => onShowToast("CSV download failed", "error"),
    });
  }, [lastRunId, downloadChecksumCsvMutation, onShowToast]);

  const handleEmailResults = useCallback(async () => {
    if (!lastRunId) {
      onShowToast("No results to email. Run a verification first.", "warning");
      return;
    }
    if (!checksumEmailAddr) {
      onShowToast("Please enter an email address", "warning");
      return;
    }
    try {
      await emailChecksumMutation.mutateAsync({ runId: lastRunId, recipientEmail: checksumEmailAddr });
      onShowToast(`Results emailed to ${checksumEmailAddr}`);
      setChecksumEmailAddr("");
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Email failed";
      onShowToast(msg, "error");
    }
  }, [lastRunId, checksumEmailAddr, emailChecksumMutation, onShowToast]);

  // ── Computed: pipeline results ─────────────────────────────────────
  const latestResults: ChecksumResultItem[] = lastRunId
    ? (checksumResults?.results?.filter((r) => r.run_id === lastRunId) ?? [])
    : (checksumResults?.results ?? []);

  const filteredPipelines = useMemo(() => {
    if (!pipelineSearch) return latestResults;
    const q = pipelineSearch.toLowerCase();
    return latestResults.filter((r) => r.pipeline_name.toLowerCase().includes(q));
  }, [latestResults, pipelineSearch]);

  const sortedPipelines = useMemo(() => {
    return [...filteredPipelines].sort((left, right) => {
      const direction = pipelineSort.direction === "asc" ? 1 : -1;

      if (pipelineSort.key === "last_published_date") {
        const leftValue = left.last_published_date ? new Date(left.last_published_date).getTime() : 0;
        const rightValue = right.last_published_date ? new Date(right.last_published_date).getTime() : 0;
        return (leftValue - rightValue) * direction;
      }

      return String(left[pipelineSort.key] ?? "")
        .localeCompare(String(right[pipelineSort.key] ?? ""), undefined, { sensitivity: "base" }) * direction;
    });
  }, [filteredPipelines, pipelineSort]);

  const pipelineTotalPages = Math.max(1, Math.ceil(sortedPipelines.length / PAGE_SIZE));
  const pagedPipelines = useMemo(
    () => sortedPipelines.slice(pipelinePage * PAGE_SIZE, (pipelinePage + 1) * PAGE_SIZE),
    [sortedPipelines, pipelinePage],
  );

  // ── Computed: deduplicate runs — keep only latest per workspace per day
  const deduplicatedRuns: ChecksumRun[] = useMemo(() => {
    const allRuns = checksumRuns?.runs ?? [];
    const latestMap = new Map<string, ChecksumRun>();
    for (const run of allRuns) {
      const dateStr = new Date(run.execution_date).toLocaleDateString(undefined, { timeZone: timezone });
      const key = `${run.workspace_name}::${dateStr}`;
      const existing = latestMap.get(key);
      if (!existing || new Date(run.execution_date) > new Date(existing.execution_date)) {
        latestMap.set(key, run);
      }
    }
    return Array.from(latestMap.values()).sort(
      (a, b) => new Date(b.execution_date).getTime() - new Date(a.execution_date).getTime(),
    );
  }, [checksumRuns]);

  // ── Filter runs by selected workspace ──────────────────────────────
  const workspaceFilteredRuns = useMemo(() => {
    if (!checksumWorkspace) return deduplicatedRuns;
    return deduplicatedRuns.filter((r) => r.workspace_name === checksumWorkspace);
  }, [deduplicatedRuns, checksumWorkspace]);

  const filteredRuns = useMemo(() => {
    if (!runsSearch) return workspaceFilteredRuns;
    const q = runsSearch.toLowerCase();
    return workspaceFilteredRuns.filter(
      (r) =>
        r.workspace_name.toLowerCase().includes(q) ||
        r.system.toLowerCase().includes(q) ||
        r.environment.toLowerCase().includes(q),
    );
  }, [workspaceFilteredRuns, runsSearch]);

  const sortedRuns = useMemo(() => {
    return [...filteredRuns].sort((left, right) => {
      const direction = runsSort.direction === "asc" ? 1 : -1;

      if (runsSort.key === "execution_date") {
        return (
          (new Date(left.execution_date).getTime() - new Date(right.execution_date).getTime()) *
          direction
        );
      }

      if (runsSort.key === "total_pipelines" || runsSort.key === "passed" || runsSort.key === "failed") {
        return (left[runsSort.key] - right[runsSort.key]) * direction;
      }

      return String(left[runsSort.key] ?? "")
        .localeCompare(String(right[runsSort.key] ?? ""), undefined, { sensitivity: "base" }) * direction;
    });
  }, [filteredRuns, runsSort]);

  const runsTotalPages = Math.max(1, Math.ceil(sortedRuns.length / PAGE_SIZE));
  const pagedRuns = useMemo(
    () => sortedRuns.slice(runsPage * PAGE_SIZE, (runsPage + 1) * PAGE_SIZE),
    [sortedRuns, runsPage],
  );

  useEffect(() => {
    setRunsPage(0);
  }, [runsSearch, runsSort]);

  useEffect(() => {
    setPipelinePage(0);
  }, [pipelineSearch, pipelineSort, checksumWorkspace]);

  // ── Computed: deduplicated metrics for graph and summary cards ─────
  const dedupedMetrics = useMemo(() => {
    if (!checksumMetrics) return null;

    // Deduplicate runs: latest run per workspace per day for summary + graph
    const allRuns = checksumRuns?.runs ?? [];
    const latestMap = new Map<string, ChecksumRun>();
    for (const run of allRuns) {
      const dateStr = new Date(run.execution_date).toLocaleDateString(undefined, { timeZone: timezone });
      const key = `${run.workspace_name}::${dateStr}`;
      const existing = latestMap.get(key);
      if (!existing || new Date(run.execution_date) > new Date(existing.execution_date)) {
        latestMap.set(key, run);
      }
    }
    const dedupRuns = Array.from(latestMap.values());

    // Build summary from deduped runs — per-workspace
    const wsSummary: Record<string, { pass: number; fail: number; total: number; system: string }> = {};
    const dailyMap: Record<string, Record<string, number>> = {};

    for (const run of dedupRuns) {
      const ws = run.workspace_name;
      if (!wsSummary[ws]) {
        wsSummary[ws] = { pass: 0, fail: 0, total: 0, system: run.system.toUpperCase() };
      }
      wsSummary[ws].pass += run.passed;
      wsSummary[ws].fail += run.failed;
      wsSummary[ws].total += run.passed + run.failed;

      const dateStr = new Date(run.execution_date).toLocaleDateString("en-CA", { timeZone: timezone }); // YYYY-MM-DD
      if (!dailyMap[dateStr]) dailyMap[dateStr] = {};
      const passKey = `${ws}__pass`;
      const failKey = `${ws}__fail`;
      dailyMap[dateStr][passKey] = (dailyMap[dateStr][passKey] ?? 0) + run.passed;
      dailyMap[dateStr][failKey] = (dailyMap[dateStr][failKey] ?? 0) + run.failed;
    }

    const workspaces = Object.keys(wsSummary).sort();
    const daily = Object.entries(dailyMap)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, vals]) => ({ date, ...vals }));

    return { wsSummary, workspaces, daily };
  }, [checksumMetrics, checksumRuns]);

  // ── Computed: aggregated daily totals for trend chart ──────────────
  const aggregatedDaily = useMemo(() => {
    if (!dedupedMetrics?.daily) return [];
    return dedupedMetrics.daily.map((day) => {
      let pass = 0;
      let fail = 0;
      for (const [key, value] of Object.entries(day)) {
        if (key === "date") continue;
        // When a workspace is selected, only aggregate that workspace's keys
        if (checksumWorkspace) {
          const prefix = `${checksumWorkspace}__`;
          if (!key.startsWith(prefix)) continue;
        }
        if (key.endsWith("__pass")) pass += Number(value) || 0;
        else if (key.endsWith("__fail")) fail += Number(value) || 0;
      }
      return { date: day.date, pass, fail };
    }).filter((d) => d.pass > 0 || d.fail > 0);
  }, [dedupedMetrics, checksumWorkspace]);

  // ── Render ─────────────────────────────────────────────────────────
  return (
    <div className="space-y-6">
      {/* Header: title + workspace + buttons */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-4">
          <h2 className="text-xl font-semibold text-gray-800 whitespace-nowrap">
            Synapse Checksum Verification
          </h2>
          <WorkspaceSelector
            value={checksumWorkspace}
            onChange={(ws) => { setChecksumWorkspace(ws); setPipelinePage(0); }}
            allowEmpty
            className="min-w-[260px]"
          />
        </div>
        <div className="flex items-center gap-2">
          {/* Date range selector */}
          <select
            value={dateRangeDays}
            onChange={(e) => setDateRangeDays(Number(e.target.value))}
            className="rounded-lg border border-att-200 bg-white px-3 py-2 text-sm shadow-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100"
          >
            {DATE_RANGE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
          {canWrite && (
          <button
            onClick={handleRunChecksum}
            disabled={runChecksumMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {runChecksumMutation.isPending ? (
              <svg className="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : Icons.scan("w-4 h-4")}
            {runChecksumMutation.isPending ? "Running..." : "Run Verification"}
          </button>
          )}
          <button
            onClick={() => refreshChecksumResults(queryClient)}
            className="flex items-center gap-2 px-3 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
            title="Refresh data"
          >
            {Icons.refresh("w-4 h-4")}
          </button>
        </div>
      </div>



      {/* Daily Verification Trend */}
      {aggregatedDaily.length > 0 && (
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-6 pt-5 pb-2 flex items-center justify-between">
            <div>
              <h3 className="text-base font-semibold text-gray-800">Verification Trend</h3>
              <p className="text-xs text-gray-400 mt-0.5">Daily pass / fail — last {dateRangeDays} days</p>
            </div>
            <div className="flex items-center gap-5 text-xs text-gray-500">
              <span className="flex items-center gap-1.5"><span className="inline-block w-2.5 h-2.5 rounded-full bg-emerald-500" />Passed</span>
              <span className="flex items-center gap-1.5"><span className="inline-block w-2.5 h-2.5 rounded-full bg-red-400" />Failed</span>
            </div>
          </div>
          <ResponsiveContainer width="100%" height={270}>
            <AreaChart data={aggregatedDaily} margin={{ top: 10, right: 24, left: 0, bottom: 4 }}>
              <defs>
                <linearGradient id="synapsePassGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10b981" stopOpacity={0.28} />
                  <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="synapseFailGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#ef4444" stopOpacity={0.22} />
                  <stop offset="100%" stopColor="#ef4444" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#f3f4f6" vertical={false} />
              <XAxis
                dataKey="date"
                tick={{ fontSize: 11, fill: "#9ca3af" }}
                tickLine={false}
                axisLine={{ stroke: "#e5e7eb" }}
              />
              <YAxis
                tick={{ fontSize: 11, fill: "#9ca3af" }}
                tickLine={false}
                axisLine={false}
                width={34}
              />
              <Tooltip
                contentStyle={{
                  background: "#fff",
                  border: "1px solid #e5e7eb",
                  borderRadius: "10px",
                  boxShadow: "0 4px 16px rgba(0,0,0,0.10)",
                  padding: "10px 14px",
                }}
                labelStyle={{ fontWeight: 600, color: "#374151", marginBottom: 4 }}
                itemStyle={{ fontSize: 13 }}
                cursor={{ stroke: "#e5e7eb", strokeWidth: 1 }}
              />
              <Area
                type="monotone"
                dataKey="pass"
                name="Passed"
                stroke="#10b981"
                strokeWidth={2.5}
                fill="url(#synapsePassGrad)"
                dot={false}
                activeDot={{ r: 5, fill: "#10b981", strokeWidth: 0 }}
              />
              <Area
                type="monotone"
                dataKey="fail"
                name="Failed"
                stroke="#ef4444"
                strokeWidth={2.5}
                fill="url(#synapseFailGrad)"
                dot={false}
                activeDot={{ r: 5, fill: "#ef4444", strokeWidth: 0 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Recent Runs — with search + pagination */}
      {(checksumRuns?.runs?.length ?? 0) > 0 && (
        <div className={gridStyles.shell}>
          <div className={gridStyles.panelHeader}>
            <div className="flex flex-wrap items-center gap-3">
              <h3 className={gridStyles.sectionTitle}>Recent Verification Runs</h3>
              <span className={gridStyles.countBadge}>{filteredRuns.length} runs</span>
              <AutoRefreshIndicator />
            </div>
            <input
              type="text"
              placeholder="Search runs…"
              value={runsSearch}
              onChange={(e) => { setRunsSearch(e.target.value); setRunsPage(0); }}
              className={gridStyles.toolbarInput}
            />
          </div>
          <div className="overflow-x-auto">
            <table className={gridStyles.table}>
              <thead className={gridStyles.head}>
                <tr>
                  <th className={gridStyles.headerCell}><SortableHeader label="Workspace" active={runsSort.key === "workspace_name"} direction={runsSort.direction} onClick={() => setRunsSort((current) => nextSortState(current, "workspace_name"))} /></th>
                  <th className={gridStyles.headerCell}><SortableHeader label="System" active={runsSort.key === "system"} direction={runsSort.direction} onClick={() => setRunsSort((current) => nextSortState(current, "system"))} /></th>
                  <th className={gridStyles.headerCell}><SortableHeader label="Environment" active={runsSort.key === "environment"} direction={runsSort.direction} onClick={() => setRunsSort((current) => nextSortState(current, "environment"))} /></th>
                  <th className={gridStyles.headerCell}><SortableHeader label="Date" active={runsSort.key === "execution_date"} direction={runsSort.direction} onClick={() => setRunsSort((current) => nextSortState(current, "execution_date"))} /></th>
                  <th className={gridStyles.headerCellCenter}><SortableHeader label="Total" active={runsSort.key === "total_pipelines"} direction={runsSort.direction} onClick={() => setRunsSort((current) => nextSortState(current, "total_pipelines"))} align="center" /></th>
                  <th className={gridStyles.headerCellCenter}><SortableHeader label="Passed" active={runsSort.key === "passed"} direction={runsSort.direction} onClick={() => setRunsSort((current) => nextSortState(current, "passed"))} align="center" /></th>
                  <th className={gridStyles.headerCellCenter}><SortableHeader label="Failed" active={runsSort.key === "failed"} direction={runsSort.direction} onClick={() => setRunsSort((current) => nextSortState(current, "failed"))} align="center" /></th>
                  <th className={gridStyles.headerCell}><SortableHeader label="Status" active={runsSort.key === "status"} direction={runsSort.direction} onClick={() => setRunsSort((current) => nextSortState(current, "status"))} /></th>
                </tr>
              </thead>
              <tbody>
                {pagedRuns.map((run) => (
                  <tr
                    key={run.run_id}
                    onClick={() => setLastRunId(run.run_id)}
                    className={`${gridStyles.row} cursor-pointer ${lastRunId === run.run_id ? gridStyles.selectedRow : ""}`}
                  >
                    <td className={gridStyles.strongCell}>{run.workspace_name}</td>
                    <td className={`${gridStyles.cell} uppercase`}>{run.system}</td>
                    <td className={gridStyles.cell}>{run.environment}</td>
                    <td className={`${gridStyles.cell} whitespace-nowrap`}>
                      {formatDate(run.execution_date)}
                    </td>
                    <td className={`${gridStyles.centerCell} font-bold text-gray-800`}>{run.total_pipelines}</td>
                    <td className={`${gridStyles.centerCell} font-bold text-green-600`}>{run.passed}</td>
                    <td className={`${gridStyles.centerCell} font-bold text-red-600`}>{run.failed}</td>
                    <td className={gridStyles.cell}>{run.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {runsTotalPages > 1 && (
            <div className={gridStyles.pager}>
              <span className="text-gray-600">
                Showing {runsPage * PAGE_SIZE + 1}–{Math.min((runsPage + 1) * PAGE_SIZE, sortedRuns.length)} of {sortedRuns.length} runs
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setRunsPage((p) => Math.max(0, p - 1))}
                  disabled={runsPage === 0}
                  className={gridStyles.pagerButton}
                >
                  Previous
                </button>
                <span className="text-gray-700">Page {runsPage + 1} of {runsTotalPages}</span>
                <button
                  onClick={() => setRunsPage((p) => Math.min(runsTotalPages - 1, p + 1))}
                  disabled={runsPage >= runsTotalPages - 1}
                  className={gridStyles.pagerButton}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* Download / Email row */}
      {canWrite && (
      <div className="flex flex-wrap gap-3 items-end">
        <button
          onClick={handleDownloadCsv}
          disabled={!lastRunId || downloadChecksumCsvMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
          Download CSV
        </button>
        <div className="flex gap-2 items-center">
          <input
            type="email"
            placeholder="Email address"
            value={checksumEmailAddr}
            onChange={(e) => setChecksumEmailAddr(e.target.value)}
            className="px-3 py-2 border rounded-lg text-sm w-64"
          />
          <button
            onClick={handleEmailResults}
            disabled={!lastRunId || emailChecksumMutation.isPending || !checksumEmailAddr}
            className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" /><polyline points="22,6 12,13 2,6" /></svg>
            {emailChecksumMutation.isPending ? "Sending..." : "Send Email"}
          </button>
        </div>
      </div>
      )}

      {/* Pipeline Results Table — with search + pagination */}
      <div className={gridStyles.shell}>
        <div className={gridStyles.panelHeader}>
          <div className="flex items-center gap-3">
            <h3 className={gridStyles.sectionTitle}>Pipeline Checksum Results</h3>
            <span className={gridStyles.countBadge}>
              {filteredPipelines.length} pipeline{filteredPipelines.length !== 1 ? "s" : ""}
              {lastRunId && <span className="ml-2 text-att-700">Run: {lastRunId.slice(0, 8)}…</span>}
            </span>
            <AutoRefreshIndicator />
          </div>
          <input
            type="text"
            placeholder="Search pipelines…"
            value={pipelineSearch}
            onChange={(e) => { setPipelineSearch(e.target.value); setPipelinePage(0); }}
            className={gridStyles.toolbarInput}
          />
        </div>
        {loadingChecksumResults ? (
          <div className="p-10 text-center">
            <svg className="animate-spin h-8 w-8 mx-auto text-blue-500 mb-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <p className="text-gray-500">Loading results...</p>
          </div>
        ) : filteredPipelines.length === 0 ? (
          <div className="p-10 text-center text-gray-400">
            <p className="text-lg mb-1">No results yet</p>
            <p className="text-sm">Select a workspace and click &quot;Run Verification&quot; to start.</p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className={gridStyles.table}>
                <thead className={gridStyles.head}>
                  <tr>
                    <th className={`${gridStyles.headerCellCenter} w-16`}><span>Sl.No</span></th>
                    <th className={gridStyles.headerCell}><SortableHeader label="Pipeline Name" active={pipelineSort.key === "pipeline_name"} direction={pipelineSort.direction} onClick={() => setPipelineSort((current) => nextSortState(current, "pipeline_name"))} /></th>
                    <th className={gridStyles.headerCell}><SortableHeader label="Yesterday's Checksum" active={pipelineSort.key === "yesterday_hash"} direction={pipelineSort.direction} onClick={() => setPipelineSort((current) => nextSortState(current, "yesterday_hash"))} /></th>
                    <th className={gridStyles.headerCell}><SortableHeader label="Current Checksum" active={pipelineSort.key === "present_hash"} direction={pipelineSort.direction} onClick={() => setPipelineSort((current) => nextSortState(current, "present_hash"))} /></th>
                    <th className={gridStyles.headerCell}><SortableHeader label="Last Published" active={pipelineSort.key === "last_published_date"} direction={pipelineSort.direction} onClick={() => setPipelineSort((current) => nextSortState(current, "last_published_date"))} /></th>
                    <th className={`${gridStyles.headerCellCenter} w-24`}><SortableHeader label="Status" active={pipelineSort.key === "result"} direction={pipelineSort.direction} onClick={() => setPipelineSort((current) => nextSortState(current, "result"))} align="center" /></th>
                  </tr>
                </thead>
                <tbody>
                  {pagedPipelines.map((r, idx) => {
                    const isFail = r.result === "FAIL";
                    return (
                      <tr
                        key={`${r.run_id}-${r.slno}`}
                        className={`${gridStyles.row} ${isFail ? "bg-red-50/40" : ""}`}
                      >
                        <td className={gridStyles.centerCell}>
                          {r.slno ?? pipelinePage * PAGE_SIZE + idx + 1}
                        </td>
                        <td className={gridStyles.strongCell}>{r.pipeline_name}</td>
                        <td className={gridStyles.monoCell}>
                          {r.yesterday_hash || "—"}
                        </td>
                        <td className={`${gridStyles.monoCell} ${isFail ? "font-semibold text-red-700" : ""}`}>
                          {r.present_hash || "—"}
                        </td>
                        <td className={`${gridStyles.cell} whitespace-nowrap`}>
                          {r.last_published_date
                            ? formatDate(r.last_published_date)
                            : "—"}
                        </td>
                        <td className={gridStyles.centerCell}>
                          <span
                            className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-semibold ${
                              isFail ? "bg-red-100 text-red-700" : "bg-green-100 text-green-700"
                            }`}
                          >
                            {r.result}
                          </span>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {pipelineTotalPages > 1 && (
              <div className={gridStyles.pager}>
                <span className="text-gray-600">
                  Showing {pipelinePage * PAGE_SIZE + 1}–{Math.min((pipelinePage + 1) * PAGE_SIZE, sortedPipelines.length)} of {sortedPipelines.length} pipelines
                </span>
                <div className="flex items-center gap-2">
                  <button
                    onClick={() => setPipelinePage((p) => Math.max(0, p - 1))}
                    disabled={pipelinePage === 0}
                    className={gridStyles.pagerButton}
                  >
                    Previous
                  </button>
                  <span className="text-gray-700">Page {pipelinePage + 1} of {pipelineTotalPages}</span>
                  <button
                    onClick={() => setPipelinePage((p) => Math.min(pipelineTotalPages - 1, p + 1))}
                    disabled={pipelinePage >= pipelineTotalPages - 1}
                    className={gridStyles.pagerButton}
                  >
                    Next
                  </button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

    </div>
  );
}
