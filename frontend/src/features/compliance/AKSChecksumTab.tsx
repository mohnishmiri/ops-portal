/**
 * AKSChecksumTab — AKS pod image checksum verification
 *
 * Mirrors the Synapse ChecksumVerificationTab pattern:
 *  - Cluster selector (real-time from AKS API)
 *  - Multi-namespace selector
 *  - Per-cluster daily pass/fail bar chart
 *  - Recent verification runs table
 *  - Pod-level results table (yesterday vs current image checksum)
 *  - CSV download + email results
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../../contexts/AuthContext";
import {
  useAKSNamespaces,
  useAKSChecksumRuns,
  useAKSChecksumMetrics,
  useRunAKSChecksumFull,
  useDownloadAKSChecksumCsv,
  useEmailAKSChecksumResults,
  useChecksumResults,
  refreshChecksumResults,
  type ChecksumResultItem,
  type ChecksumRun,
} from "../../services/complianceApi";
import { useCachedClusters } from "../../services/aksApi";
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { AutoRefreshIndicator, gridStyles, nextSortState, SortableHeader, type SortState } from "../../components/gridStyles";
import { usePortalTimezone } from "../../contexts/TimezoneContext";

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

type PodSortKey =
  | "pipeline_name"
  | "yesterday_hash"
  | "present_hash"
  | "result";

/* ── Local Icons ────────────────────────────────────────────────────── */

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

export interface AKSChecksumTabProps {
  onShowToast: (message: string, type?: "success" | "error" | "warning" | "info") => void;
  onNavigateToSchedules?: () => void;
}

/* ── Component ──────────────────────────────────────────────────────── */

const AKSChecksumTab: React.FC<AKSChecksumTabProps> = ({ onShowToast, onNavigateToSchedules }) => {
  const queryClient = useQueryClient();
  const { timezone, formatDate } = usePortalTimezone();
  const { canWrite } = useAuth();

  // ── Local state ────────────────────────────────────────────────────
  const [selectedClusterId, setSelectedClusterId] = useState<string>("");
  const [selectedNamespaces, setSelectedNamespaces] = useState<string[]>([]);
  const [lastRunId, setLastRunId] = useState<string | null>(null);
  const [emailAddr, setEmailAddr] = useState("");
  const [dateRangeDays, setDateRangeDays] = useState(30);
  const [podSearch, setPodSearch] = useState("");
  const [podPage, setPodPage] = useState(0);
  const [runsSearch, setRunsSearch] = useState("");
  const [runsPage, setRunsPage] = useState(0);
  const [nsDropdownOpen, setNsDropdownOpen] = useState(false);
  const [runsSort, setRunsSort] = useState<SortState<RunsSortKey>>({
    key: "execution_date",
    direction: "desc",
  });
  const [podSort, setPodSort] = useState<SortState<PodSortKey>>({
    key: "pipeline_name",
    direction: "asc",
  });

  // ── Queries ────────────────────────────────────────────────────────
  const { data: clusterData, isLoading: loadingClusters } = useCachedClusters();
  const clusters = clusterData?.clusters ?? [];

  const { data: nsData, isLoading: loadingNamespaces } = useAKSNamespaces(selectedClusterId || undefined);
  const namespaces = nsData?.namespaces ?? [];

  const { data: aksRuns } = useAKSChecksumRuns({ days: dateRangeDays });
  const _aksMetrics = useAKSChecksumMetrics(dateRangeDays);
  void _aksMetrics; // reserved for future use

  const { data: checksumResults, isLoading: loadingResults } = useChecksumResults(
    { days: dateRangeDays, module_type: "aks" } as any,
  );

  // ── Mutations ──────────────────────────────────────────────────────
  const runAKSMutation = useRunAKSChecksumFull();
  const downloadCsvMutation = useDownloadAKSChecksumCsv();
  const emailMutation = useEmailAKSChecksumResults();

  // ── Handlers ───────────────────────────────────────────────────────
  const selectedCluster = useMemo(
    () => clusters.find((c) => c.id === selectedClusterId),
    [clusters, selectedClusterId],
  );

  const handleRunVerification = useCallback(async () => {
    try {
      const result = await runAKSMutation.mutateAsync({
        cluster_id: selectedClusterId,
        system: "attcc",
        environment: selectedCluster?.environment ?? "prod",
        namespaces: selectedNamespaces.length > 0 ? selectedNamespaces : undefined,
        ...(emailAddr ? { notification_emails: [emailAddr] } : {}),
      });
      setLastRunId(result.run_id);
      const hasErrors = (result.failed ?? 0) > 0;
      const emailNote = emailAddr ? ` — report emailed to ${emailAddr}` : "";
      onShowToast(
        `AKS checksum verification complete: ${result.passed ?? 0} PASS, ${result.failed ?? 0} FAIL${emailNote}`,
        hasErrors ? "error" : "success",
      );
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "AKS checksum verification failed";
      onShowToast(msg, "error");
    }
  }, [selectedClusterId, selectedCluster, selectedNamespaces, emailAddr, runAKSMutation, onShowToast]);

  const handleDownloadCsv = useCallback(() => {
    if (!lastRunId) {
      onShowToast("No results to download. Run a verification first.", "warning");
      return;
    }
    downloadCsvMutation.mutate(lastRunId, {
      onSuccess: () => onShowToast("CSV downloaded"),
      onError: () => onShowToast("CSV download failed", "error"),
    });
  }, [lastRunId, downloadCsvMutation, onShowToast]);

  const handleEmailResults = useCallback(async () => {
    if (!lastRunId) {
      onShowToast("No results to email. Run a verification first.", "warning");
      return;
    }
    if (!emailAddr) {
      onShowToast("Please enter an email address", "warning");
      return;
    }
    try {
      await emailMutation.mutateAsync({ runId: lastRunId, recipientEmail: emailAddr });
      onShowToast(`Results emailed to ${emailAddr}`);
      setEmailAddr("");
    } catch (e: unknown) {
      const msg = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ?? "Email failed";
      onShowToast(msg, "error");
    }
  }, [lastRunId, emailAddr, emailMutation, onShowToast]);

  const toggleNamespace = (ns: string) => {
    setSelectedNamespaces((prev) =>
      prev.includes(ns) ? prev.filter((n) => n !== ns) : [...prev, ns],
    );
  };

  // ── Computed: pod results ──────────────────────────────────────────
  const latestResults: ChecksumResultItem[] = lastRunId
    ? (checksumResults?.results?.filter((r) => r.run_id === lastRunId) ?? [])
    : (checksumResults?.results ?? []);

  const filteredPods = useMemo(() => {
    if (!podSearch) return latestResults;
    const q = podSearch.toLowerCase();
    return latestResults.filter((r) => r.pipeline_name.toLowerCase().includes(q));
  }, [latestResults, podSearch]);

  const sortedPods = useMemo(() => {
    return [...filteredPods].sort((left, right) => {
      const direction = podSort.direction === "asc" ? 1 : -1;
      return String(left[podSort.key] ?? "")
        .localeCompare(String(right[podSort.key] ?? ""), undefined, { sensitivity: "base" }) * direction;
    });
  }, [filteredPods, podSort]);

  const podTotalPages = Math.max(1, Math.ceil(sortedPods.length / PAGE_SIZE));
  const pagedPods = useMemo(
    () => sortedPods.slice(podPage * PAGE_SIZE, (podPage + 1) * PAGE_SIZE),
    [sortedPods, podPage],
  );

  // ── Lookup: cluster name → environment from live clusters data ─────
  const clusterEnvMap = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of clusters) {
      map.set(c.name, c.environment ?? "");
    }
    return map;
  }, [clusters]);

  // ── Computed: dedup runs — latest per cluster per day ──────────────
  const deduplicatedRuns: ChecksumRun[] = useMemo(() => {
    const allRuns = aksRuns?.runs ?? [];
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
  }, [aksRuns]);

  // ── Filter runs by selected cluster ───────────────────────────────
  const clusterFilteredRuns = useMemo(() => {
    if (!selectedCluster) return deduplicatedRuns;
    return deduplicatedRuns.filter((r) => r.workspace_name === selectedCluster.name);
  }, [deduplicatedRuns, selectedCluster]);

  const filteredRuns = useMemo(() => {
    if (!runsSearch) return clusterFilteredRuns;
    const q = runsSearch.toLowerCase();
    return clusterFilteredRuns.filter(
      (r) =>
        r.workspace_name.toLowerCase().includes(q) ||
        r.system.toLowerCase().includes(q) ||
        r.environment.toLowerCase().includes(q),
    );
  }, [clusterFilteredRuns, runsSearch]);

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
    setPodPage(0);
  }, [podSearch, podSort, selectedClusterId]);

  // ── Computed: per-cluster daily metrics for chart + summary ────────
  const dedupedMetrics = useMemo(() => {
    if (!aksRuns?.runs?.length) return null;

    const dedupRuns = deduplicatedRuns;
    const clusterSummary: Record<string, { pass: number; fail: number; total: number; system: string }> = {};
    const dailyMap: Record<string, Record<string, number>> = {};

    for (const run of dedupRuns) {
      const cl = run.workspace_name;
      if (!clusterSummary[cl]) {
        clusterSummary[cl] = { pass: 0, fail: 0, total: 0, system: run.system.toUpperCase() };
      }
      clusterSummary[cl].pass += run.passed;
      clusterSummary[cl].fail += run.failed;
      clusterSummary[cl].total += run.passed + run.failed;

      const dateStr = new Date(run.execution_date).toLocaleDateString("en-CA", { timeZone: timezone });
      if (!dailyMap[dateStr]) dailyMap[dateStr] = {};
      const passKey = `${cl}__pass`;
      const failKey = `${cl}__fail`;
      dailyMap[dateStr][passKey] = (dailyMap[dateStr][passKey] ?? 0) + run.passed;
      dailyMap[dateStr][failKey] = (dailyMap[dateStr][failKey] ?? 0) + run.failed;
    }

    const clusterNames = Object.keys(clusterSummary).sort();
    const daily = Object.entries(dailyMap)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, vals]) => ({ date, ...vals }));

    return { clusterSummary, clusterNames, daily };
  }, [aksRuns, deduplicatedRuns]);

  // ── Computed: aggregated daily totals for trend chart ──────────────
  const aggregatedDaily = useMemo(() => {
    if (!dedupedMetrics?.daily) return [];
    return dedupedMetrics.daily.map((day) => {
      let pass = 0;
      let fail = 0;
      for (const [key, value] of Object.entries(day)) {
        if (key === "date") continue;
        // When a cluster is selected, only aggregate that cluster's keys
        if (selectedCluster) {
          const prefix = `${selectedCluster.name}__`;
          if (!key.startsWith(prefix)) continue;
        }
        if (key.endsWith("__pass")) pass += Number(value) || 0;
        else if (key.endsWith("__fail")) fail += Number(value) || 0;
      }
      return { date: day.date, pass, fail };
    }).filter((d) => d.pass > 0 || d.fail > 0);
  }, [dedupedMetrics, selectedCluster]);

  // ── Render ─────────────────────────────────────────────────────────
  return (
    <div className="space-y-6">
      {/* Header: cluster + namespace selectors + buttons */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-4">
          <h2 className="text-xl font-semibold text-gray-800 whitespace-nowrap">
            AKS Pod Drift Detection
          </h2>
          {/* Cluster selector */}
          <select
            value={selectedClusterId}
            onChange={(e) => {
              setSelectedClusterId(e.target.value);
              setSelectedNamespaces([]);
              setPodPage(0);
            }}
            className="min-w-[280px] rounded-lg border border-att-200 bg-white px-3 py-2 text-sm shadow-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100"
          >
            <option value="">— All Clusters —</option>
            {loadingClusters && <option disabled>Loading clusters...</option>}
            {clusters.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name} ({c.environment ?? "unknown"})
              </option>
            ))}
          </select>
          {/* Multi-namespace selector */}
          {selectedClusterId && (
            <div className="relative">
              <button
                onClick={() => setNsDropdownOpen(!nsDropdownOpen)}
                className="flex min-w-[220px] items-center justify-between rounded-lg border border-att-200 bg-white px-3 py-2 text-left text-sm shadow-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100"
              >
                <span className="truncate">
                  {selectedNamespaces.length === 0
                    ? "All namespaces"
                    : `${selectedNamespaces.length} namespace${selectedNamespaces.length > 1 ? "s" : ""}`}
                </span>
                <svg className="w-4 h-4 ml-2 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
              </button>
              {nsDropdownOpen && (
                <div className="absolute z-30 mt-1 w-72 bg-white border border-gray-200 rounded-lg shadow-lg max-h-60 overflow-y-auto">
                  {loadingNamespaces ? (
                    <div className="p-3 text-sm text-gray-500">Loading namespaces...</div>
                  ) : namespaces.length === 0 ? (
                    <div className="p-3 text-sm text-gray-400">No namespaces found</div>
                  ) : (
                    <>
                      <div className="p-2 border-b flex justify-between">
                        <button
                          onClick={() => setSelectedNamespaces(namespaces)}
                          className="text-xs text-blue-600 hover:underline"
                        >
                          Select All
                        </button>
                        <button
                          onClick={() => setSelectedNamespaces([])}
                          className="text-xs text-red-600 hover:underline"
                        >
                          Clear
                        </button>
                      </div>
                      {namespaces.map((ns) => (
                        <label key={ns} className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 cursor-pointer text-sm">
                          <input
                            type="checkbox"
                            checked={selectedNamespaces.includes(ns)}
                            onChange={() => toggleNamespace(ns)}
                            className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                          />
                          {ns}
                        </label>
                      ))}
                    </>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        <div className="flex items-center gap-2">
          <select
            value={dateRangeDays}
            onChange={(e) => setDateRangeDays(Number(e.target.value))}
            className="rounded-lg border border-att-200 bg-white px-3 py-2 text-sm shadow-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100"
          >
            {DATE_RANGE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          {canWrite && (
          <button
            onClick={handleRunVerification}
            disabled={runAKSMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {runAKSMutation.isPending ? (
              <svg className="animate-spin h-4 w-4 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : Icons.scan("w-4 h-4")}
            {runAKSMutation.isPending ? "Running..." : "Run Verification"}
          </button>
          )}
          <button
            onClick={() => refreshChecksumResults(queryClient)}
            className="flex items-center gap-2 px-3 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200"
            title="Refresh data"
          >
            {Icons.refresh("w-4 h-4")}
          </button>
          {onNavigateToSchedules && (
            <button
              onClick={onNavigateToSchedules}
              className="flex items-center gap-2 px-4 py-2 border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50"
            >
              Create Schedule
            </button>
          )}
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
                <linearGradient id="aksPassGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor="#10b981" stopOpacity={0.28} />
                  <stop offset="100%" stopColor="#10b981" stopOpacity={0} />
                </linearGradient>
                <linearGradient id="aksFailGrad" x1="0" y1="0" x2="0" y2="1">
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
                fill="url(#aksPassGrad)"
                dot={false}
                activeDot={{ r: 5, fill: "#10b981", strokeWidth: 0 }}
              />
              <Area
                type="monotone"
                dataKey="fail"
                name="Failed"
                stroke="#ef4444"
                strokeWidth={2.5}
                fill="url(#aksFailGrad)"
                dot={false}
                activeDot={{ r: 5, fill: "#ef4444", strokeWidth: 0 }}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Recent Verification Runs */}
      {(aksRuns?.runs?.length ?? 0) > 0 && (
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
                  <th className={gridStyles.headerCell}><SortableHeader label="Cluster" active={runsSort.key === "workspace_name"} direction={runsSort.direction} onClick={() => setRunsSort((current) => nextSortState(current, "workspace_name"))} /></th>
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
                    <td className={gridStyles.cell}>{clusterEnvMap.get(run.workspace_name) || run.environment}</td>
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
                <button onClick={() => setRunsPage((p) => Math.max(0, p - 1))} disabled={runsPage === 0} className={gridStyles.pagerButton}>Previous</button>
                <span className="text-gray-700">Page {runsPage + 1} of {runsTotalPages}</span>
                <button onClick={() => setRunsPage((p) => Math.min(runsTotalPages - 1, p + 1))} disabled={runsPage >= runsTotalPages - 1} className={gridStyles.pagerButton}>Next</button>
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
          disabled={!lastRunId || downloadCsvMutation.isPending}
          className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" /></svg>
          Download CSV
        </button>
        <div className="flex gap-2 items-center">
          <input
            type="email"
            placeholder="Email address"
            value={emailAddr}
            onChange={(e) => setEmailAddr(e.target.value)}
            className="px-3 py-2 border rounded-lg text-sm w-64"
          />
          <button
            onClick={handleEmailResults}
            disabled={!lastRunId || emailMutation.isPending || !emailAddr}
            className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50"
          >
            <svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" /><polyline points="22,6 12,13 2,6" /></svg>
            {emailMutation.isPending ? "Sending..." : "Send Email"}
          </button>
        </div>
      </div>
      )}

      {/* Pod Image Checksum Results Table */}
      <div className={gridStyles.shell}>
        <div className={gridStyles.panelHeader}>
          <div className="flex items-center gap-3">
            <h3 className={gridStyles.sectionTitle}>Pod Image Checksum Results</h3>
            <span className={gridStyles.countBadge}>
              {filteredPods.length} pod{filteredPods.length !== 1 ? "s" : ""}
              {lastRunId && <span className="ml-2 text-att-700">Run: {lastRunId.slice(0, 8)}…</span>}
            </span>
            <AutoRefreshIndicator />
          </div>
          <input
            type="text"
            placeholder="Search pods…"
            value={podSearch}
            onChange={(e) => { setPodSearch(e.target.value); setPodPage(0); }}
            className={gridStyles.toolbarInput}
          />
        </div>
        {loadingResults ? (
          <div className="p-10 text-center">
            <svg className="animate-spin h-8 w-8 mx-auto text-blue-500 mb-2" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            <p className="text-gray-500">Loading results...</p>
          </div>
        ) : filteredPods.length === 0 ? (
          <div className="p-10 text-center text-gray-400">
            <p className="text-lg mb-1">No results yet</p>
            <p className="text-sm">Select a cluster and click &quot;Run Verification&quot; to start.</p>
          </div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className={gridStyles.table}>
                <thead className={gridStyles.head}>
                  <tr>
                    <th className={`${gridStyles.headerCellCenter} w-16`}><span>Sl.No</span></th>
                    <th className={gridStyles.headerCell}><SortableHeader label="Pod / Owner" active={podSort.key === "pipeline_name"} direction={podSort.direction} onClick={() => setPodSort((current) => nextSortState(current, "pipeline_name"))} /></th>
                    <th className={gridStyles.headerCell}><SortableHeader label="Yesterday's Image Checksum" active={podSort.key === "yesterday_hash"} direction={podSort.direction} onClick={() => setPodSort((current) => nextSortState(current, "yesterday_hash"))} /></th>
                    <th className={gridStyles.headerCell}><SortableHeader label="Current Image Checksum" active={podSort.key === "present_hash"} direction={podSort.direction} onClick={() => setPodSort((current) => nextSortState(current, "present_hash"))} /></th>
                    <th className={`${gridStyles.headerCellCenter} w-24`}><SortableHeader label="Status" active={podSort.key === "result"} direction={podSort.direction} onClick={() => setPodSort((current) => nextSortState(current, "result"))} align="center" /></th>
                  </tr>
                </thead>
                <tbody>
                  {pagedPods.map((r, idx) => {
                    const isFail = r.result === "FAIL";
                    return (
                      <tr
                        key={`${r.run_id}-${r.slno}`}
                        className={`${gridStyles.row} ${isFail ? "bg-red-50/40" : ""}`}
                      >
                        <td className={gridStyles.centerCell}>
                          {r.slno ?? podPage * PAGE_SIZE + idx + 1}
                        </td>
                        <td className={gridStyles.strongCell}>{r.pipeline_name}</td>
                        <td className={gridStyles.monoCell}>
                          {r.yesterday_hash || "—"}
                        </td>
                        <td className={`${gridStyles.monoCell} ${isFail ? "font-semibold text-red-700" : ""}`}>
                          {r.present_hash || "—"}
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
            {podTotalPages > 1 && (
              <div className={gridStyles.pager}>
                <span className="text-gray-600">
                  Showing {podPage * PAGE_SIZE + 1}–{Math.min((podPage + 1) * PAGE_SIZE, sortedPods.length)} of {sortedPods.length} pods
                </span>
                <div className="flex items-center gap-2">
                  <button onClick={() => setPodPage((p) => Math.max(0, p - 1))} disabled={podPage === 0} className={gridStyles.pagerButton}>Previous</button>
                  <span className="text-gray-700">Page {podPage + 1} of {podTotalPages}</span>
                  <button onClick={() => setPodPage((p) => Math.min(podTotalPages - 1, p + 1))} disabled={podPage >= podTotalPages - 1} className={gridStyles.pagerButton}>Next</button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

    </div>
  );
};

export default AKSChecksumTab;
