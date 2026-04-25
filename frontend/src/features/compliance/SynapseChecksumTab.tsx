/**
 * SynapseChecksumTab — Synapse pipeline drift detection sub-component.
 *
 * Extracted from the monolithic CompliancePage for modularity.
 * Displays:
 *   - Workspace selector (grouped by org/environment)
 *   - Header with "Collect Checksums" / "Run Checksum" action buttons
 *   - Summary stat cards scoped to the selected workspace
 *   - Checksum comparison results grid (yesterday vs. current per pipeline)
 *   - Drift table with severity/status/actions
 *   - Detail modal with checksums, diff summary, and acknowledge workflow
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  useSynapseDriftSummary,
  useSynapseDrift,
  useCollectSynapseChecksums,
  useAcknowledgeSynapseDrift,
  useRunChecksumVerification,
  useSynapseChecksumComparison,
  type SynapseDrift,
} from "../../services/complianceApi";
import { useAuth } from "../../contexts/AuthContext";
import { getSeverityColor } from "./ComplianceDashboard";
import WorkspaceSelector from "./WorkspaceSelector";
import ChecksumComparisonGrid from "./ChecksumComparisonGrid";
import { AutoRefreshIndicator, gridStyles, nextSortState, SortableHeader, type SortState } from "../../components/gridStyles";
import { usePortalTimezone } from "../../contexts/TimezoneContext";

const PAGE_SIZE = 20;

// ── SVG Icons (Synapse-tab subset) ────────────────────────────────────

const Icons = {
  scan: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M3 7V5a2 2 0 0 1 2-2h2" /><path d="M17 3h2a2 2 0 0 1 2 2v2" /><path d="M21 17v2a2 2 0 0 1-2 2h-2" /><path d="M7 21H5a2 2 0 0 1-2-2v-2" />
      <line x1="7" y1="12" x2="17" y2="12" />
    </svg>
  ),
  check: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <polyline points="20 6 9 17 4 12" />
    </svg>
  ),
  alert: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <circle cx="12" cy="12" r="10" /><line x1="12" y1="8" x2="12" y2="12" /><line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  ),
  eye: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" /><circle cx="12" cy="12" r="3" />
    </svg>
  ),
  acknowledge: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  ),
};

// ── Props ─────────────────────────────────────────────────────────────

export interface SynapseChecksumTabProps {
  onShowToast: (message: string, type?: "success" | "error" | "info") => void;
  onNavigateToSchedules?: () => void;
}

type DriftSortKey =
  | "workspace_name"
  | "pipeline_name"
  | "severity"
  | "drift_type"
  | "detected_at"
  | "acknowledged";

// ── Component ─────────────────────────────────────────────────────────

export default function SynapseChecksumTab({ onShowToast, onNavigateToSchedules }: SynapseChecksumTabProps) {  // ── Portal timezone ──────────────────────────────────────────────────────
  const { formatDate } = usePortalTimezone();  // ── Local state ───────────────────────────────────────────────────
  const [selectedWorkspace, setSelectedWorkspace] = useState<string | null>(null);
  const [selectedDrift, setSelectedDrift] = useState<SynapseDrift | null>(null);
  const [ackReason, setAckReason] = useState("");
  const [driftPage, setDriftPage] = useState(0);
  const [driftSearch, setDriftSearch] = useState("");
  const [driftSort, setDriftSort] = useState<SortState<DriftSortKey>>({
    key: "detected_at",
    direction: "desc",
  });
  const { canWrite } = useAuth();

  // ── Queries ───────────────────────────────────────────────────────
  const { data: synapseSummary } = useSynapseDriftSummary(7, selectedWorkspace ?? undefined);
  const { data: synapseDriftData, isLoading: loadingSynapse, isError: driftError } = useSynapseDrift(selectedWorkspace ?? undefined);
  const {
    data: comparisonData,
    isLoading: loadingComparison,
  } = useSynapseChecksumComparison(selectedWorkspace);

  // ── Pagination helpers ────────────────────────────────────────────
  const allDrifts = synapseDriftData?.drifts ?? [];
  const filteredDrifts = useMemo(() => {
    if (!driftSearch) {
      return allDrifts;
    }

    const query = driftSearch.toLowerCase();
    return allDrifts.filter((drift) => {
      return [
        drift.workspace_name,
        drift.pipeline_name,
        drift.drift_type,
        drift.severity,
      ].some((value) => String(value ?? "").toLowerCase().includes(query));
    });
  }, [allDrifts, driftSearch]);

  const sortedDrifts = useMemo(() => {
    return [...filteredDrifts].sort((left, right) => {
      const direction = driftSort.direction === "asc" ? 1 : -1;

      if (driftSort.key === "detected_at") {
        const leftValue = new Date(left.detected_at ?? left.detection_date).getTime();
        const rightValue = new Date(right.detected_at ?? right.detection_date).getTime();
        return (leftValue - rightValue) * direction;
      }

      if (driftSort.key === "acknowledged") {
        return (Number(left.acknowledged) - Number(right.acknowledged)) * direction;
      }

      return String(left[driftSort.key] ?? "")
        .localeCompare(String(right[driftSort.key] ?? ""), undefined, { sensitivity: "base" }) * direction;
    });
  }, [driftSort, filteredDrifts]);

  const totalPages = Math.max(1, Math.ceil(sortedDrifts.length / PAGE_SIZE));
  const pagedDrifts = useMemo(
    () => sortedDrifts.slice(driftPage * PAGE_SIZE, (driftPage + 1) * PAGE_SIZE),
    [sortedDrifts, driftPage],
  );

  useEffect(() => {
    setDriftPage(0);
  }, [driftSearch, driftSort, selectedWorkspace]);

  // ── Mutations ─────────────────────────────────────────────────────
  const collectChecksumsMutation = useCollectSynapseChecksums();
  const acknowledgeDriftMutation = useAcknowledgeSynapseDrift();
  const runVerificationMutation = useRunChecksumVerification();

  // ── Handlers ──────────────────────────────────────────────────────

  const handleCollect = useCallback(async () => {
    if (!selectedWorkspace) {
      onShowToast("Please select a workspace first", "info");
      return;
    }
    try {
      const collectResult = await collectChecksumsMutation.mutateAsync({ workspaceName: selectedWorkspace });

      // Check if the collect step itself failed (e.g. Azure SDK timeout,
      // firewall, or permission error for ATTCC workspaces).
      if (collectResult?.status === "failed" || (collectResult?.errors?.length && collectResult?.workspaces === 0)) {
        const errorDetail = collectResult?.error
          || collectResult?.errors?.[0]?.error
          || "Failed to connect to Synapse workspace";
        onShowToast(
          `Checksum collection failed for ${selectedWorkspace}: ${errorDetail}`,
          "error",
        );
        return;
      }

      // After collecting snapshots, run verification for the selected
      // workspace so that ChecksumRun/ChecksumResult records are created
      // and the UI grid + summary cards show data immediately.
      const result = await runVerificationMutation.mutateAsync({ workspaceName: selectedWorkspace });

      // Handle graceful failure from backend (status: "failed")
      if (result.status === "failed") {
        onShowToast(
          result.error || `Checksums collected but verification failed for ${selectedWorkspace}`,
          "error",
        );
        return;
      }

      const parts = [`${result.passed ?? 0} passed`, `${result.failed ?? 0} failed`];
      onShowToast(
        `Checksums collected & verified — ${parts.join(", ")}`,
        (result.failed ?? 0) > 0 ? "error" : "success",
      );
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to collect Synapse checksums";
      onShowToast(msg, "error");
    }
  }, [collectChecksumsMutation, runVerificationMutation, selectedWorkspace, onShowToast]);

  const handleRunChecksum = useCallback(async () => {
    if (!selectedWorkspace) {
      onShowToast("Please select a workspace first", "info");
      return;
    }
    try {
      const result = await runVerificationMutation.mutateAsync({ workspaceName: selectedWorkspace });

      // Handle graceful failure from backend (status: "failed")
      if (result.status === "failed") {
        onShowToast(
          result.error || `Checksum verification failed for ${selectedWorkspace}`,
          "error",
        );
        return;
      }

      const parts: string[] = [
        `${result.passed ?? 0} passed`,
        `${result.failed ?? 0} failed`,
      ];
      const hasErrors = (result.failed ?? 0) > 0;
      onShowToast(
        `Synapse checksum verification complete — ${parts.join(", ")}`,
        hasErrors ? "error" : "success"
      );
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to run Synapse checksum verification";
      onShowToast(msg, "error");
    }
  }, [runVerificationMutation, onShowToast, selectedWorkspace]);

  const handleAcknowledge = useCallback(async () => {
    if (!selectedDrift) return;
    try {
      await acknowledgeDriftMutation.mutateAsync(selectedDrift.id);
      onShowToast("Synapse drift acknowledged");
      setSelectedDrift(null);
      setAckReason("");
    } catch (e: unknown) {
      const msg =
        (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
        "Failed to acknowledge Synapse drift";
      onShowToast(msg, "error");
    }
  }, [selectedDrift, acknowledgeDriftMutation, onShowToast]);

  // ── Render ────────────────────────────────────────────────────────

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-4">
          <h2 className="text-xl font-semibold text-gray-800 whitespace-nowrap">
            Synapse Pipeline Drift Detection
          </h2>
          <WorkspaceSelector
            value={selectedWorkspace}
            onChange={(ws) => { setSelectedWorkspace(ws); setDriftPage(0); }}
            className="min-w-[260px]"
          />
        </div>
        <div className="flex items-center gap-2">
          {canWrite && (
          <button
            onClick={handleCollect}
            disabled={collectChecksumsMutation.isPending || runVerificationMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-lg hover:bg-purple-700 disabled:opacity-50"
          >
            {Icons.scan("w-4 h-4")}
            {collectChecksumsMutation.isPending ? "Scanning..." : "Collect Checksums"}
          </button>
          )}
          {canWrite && (
          <button
            onClick={handleRunChecksum}
            disabled={collectChecksumsMutation.isPending || runVerificationMutation.isPending}
            className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
          >
            {Icons.check("w-4 h-4")}
            {runVerificationMutation.isPending ? "Verifying..." : "Run Checksum"}
          </button>
          )}
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

      {/* Summary Cards — workspace-scoped when comparison data available */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
          <div className="text-2xl font-bold">
            {comparisonData ? comparisonData.total : (synapseSummary?.total_pipelines ?? "—")}
          </div>
          <div className="text-sm text-gray-600">Total Pipelines</div>
        </div>
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
          <div className="text-2xl font-bold text-green-600">
            {comparisonData ? comparisonData.passed : (synapseSummary?.compliant_pipelines ?? "—")}
          </div>
          <div className="text-sm text-gray-600">Passed</div>
        </div>
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
          <div className="text-2xl font-bold text-red-600">
            {comparisonData ? comparisonData.failed : (synapseSummary?.drifted_pipelines ?? "—")}
          </div>
          <div className="text-sm text-gray-600">Failed</div>
        </div>
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
          <div className="text-2xl font-bold text-yellow-600">
            {synapseSummary?.acknowledged_drifts ?? "—"}
          </div>
          <div className="text-sm text-gray-600">Acknowledged</div>
        </div>
      </div>

      {/* Checksum Comparison Grid — per-pipeline yesterday vs current */}
      {selectedWorkspace && (
        <ChecksumComparisonGrid
          results={comparisonData?.results ?? []}
          isLoading={loadingComparison}
          passed={comparisonData?.passed}
          failed={comparisonData?.failed}
          runId={comparisonData?.run_id}
        />
      )}

      {/* Drift Table */}
      {loadingSynapse ? (
        <div className="text-center py-8 text-gray-500">Loading drift data...</div>
      ) : driftError ? (
        <div className="text-center py-8 text-red-500">Failed to load drift data. Please try again.</div>
      ) : allDrifts.length === 0 ? (
        <div className="text-center py-8 text-gray-500">
          {selectedWorkspace
            ? "No drifts detected for this workspace."
            : "Select a workspace to view drift details."}
        </div>
      ) : (
        <>
          <div className={gridStyles.shell}>
            <div className={gridStyles.panelHeader}>
              <div className="flex flex-wrap items-center gap-3">
                <h3 className={gridStyles.sectionTitle}>Detected Drifts</h3>
                <span className={gridStyles.countBadge}>
                  {filteredDrifts.length} of {allDrifts.length} drifts
                </span>
                <AutoRefreshIndicator />
              </div>
              <input
                type="text"
                placeholder="Search drifts…"
                value={driftSearch}
                onChange={(event) => setDriftSearch(event.target.value)}
                className={gridStyles.toolbarInput}
              />
            </div>
            <div className="max-h-[560px] overflow-x-auto overflow-y-auto">
              <table className={gridStyles.table}>
              <thead className={`${gridStyles.head} ${gridStyles.stickyHead}`}>
                <tr>
                  <th className={gridStyles.headerCell}><SortableHeader label="Workspace" active={driftSort.key === "workspace_name"} direction={driftSort.direction} onClick={() => setDriftSort((current) => nextSortState(current, "workspace_name"))} /></th>
                  <th className={gridStyles.headerCell}><SortableHeader label="Pipeline" active={driftSort.key === "pipeline_name"} direction={driftSort.direction} onClick={() => setDriftSort((current) => nextSortState(current, "pipeline_name"))} /></th>
                  <th className={gridStyles.headerCellCenter}><SortableHeader label="Severity" active={driftSort.key === "severity"} direction={driftSort.direction} onClick={() => setDriftSort((current) => nextSortState(current, "severity"))} align="center" /></th>
                  <th className={gridStyles.headerCell}><SortableHeader label="Drift Type" active={driftSort.key === "drift_type"} direction={driftSort.direction} onClick={() => setDriftSort((current) => nextSortState(current, "drift_type"))} /></th>
                  <th className={gridStyles.headerCell}><SortableHeader label="Detected" active={driftSort.key === "detected_at"} direction={driftSort.direction} onClick={() => setDriftSort((current) => nextSortState(current, "detected_at"))} /></th>
                  <th className={gridStyles.headerCellCenter}><SortableHeader label="Status" active={driftSort.key === "acknowledged"} direction={driftSort.direction} onClick={() => setDriftSort((current) => nextSortState(current, "acknowledged"))} align="center" /></th>
                  <th className={gridStyles.headerCellCenter}><span>Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {pagedDrifts.map((drift, idx) => (
                  <tr key={drift.id ?? `drift-${idx}`} className={gridStyles.row}>
                    <td className={gridStyles.cell}>{drift.workspace_name}</td>
                    <td className={gridStyles.strongCell}>{drift.pipeline_name}</td>
                    <td className={gridStyles.centerCell}>
                      <span className={`px-2 py-1 rounded-full text-xs ${getSeverityColor(drift.severity ?? "low")}`}>
                        {drift.severity ?? "low"}
                      </span>
                    </td>
                    <td className={gridStyles.cell}>{drift.drift_type}</td>
                    <td className={gridStyles.cell}>
                      {formatDate(drift.detected_at ?? drift.detection_date)}
                    </td>
                    <td className={gridStyles.centerCell}>
                      {drift.acknowledged ? (
                        <span className="inline-flex items-center gap-1 text-green-600">
                          {Icons.check("w-4 h-4")} Ack
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-red-600">
                          {Icons.alert("w-4 h-4")} Open
                        </span>
                      )}
                    </td>
                    <td className={gridStyles.centerCell}>
                      <div className="flex justify-center gap-1">
                        <button
                          onClick={() => setSelectedDrift(drift)}
                          className="rounded-lg p-2 text-gray-600 transition-colors hover:bg-gray-50"
                          title="View details"
                        >
                          {Icons.eye()}
                        </button>
                        {canWrite && !drift.acknowledged && (
                          <button
                            onClick={() => setSelectedDrift(drift)}
                            className="rounded-lg p-2 text-att-700 transition-colors hover:bg-att-50"
                            title="Acknowledge"
                          >
                            {Icons.acknowledge()}
                          </button>
                        )}
                      </div>
                    </td>
                  </tr>
                ))}
                {pagedDrifts.length === 0 && (
                  <tr>
                    <td colSpan={7} className="px-4 py-8 text-center text-sm text-gray-400">
                      No drifts match the current search.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          </div>

          {/* Pagination controls */}
          {totalPages > 1 && (
            <div className={gridStyles.pager}>
              <span className="text-gray-600">
                Showing {driftPage * PAGE_SIZE + 1}–{Math.min((driftPage + 1) * PAGE_SIZE, sortedDrifts.length)} of {sortedDrifts.length} drifts
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setDriftPage((p) => Math.max(0, p - 1))}
                  disabled={driftPage === 0}
                  className={gridStyles.pagerButton}
                >
                  Previous
                </button>
                <span className="text-gray-700">
                  Page {driftPage + 1} of {totalPages}
                </span>
                <button
                  onClick={() => setDriftPage((p) => Math.min(totalPages - 1, p + 1))}
                  disabled={driftPage >= totalPages - 1}
                  className={gridStyles.pagerButton}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* Detail / Acknowledge Modal */}
      {selectedDrift && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50">
          <div className="bg-white rounded-lg p-6 w-[600px] max-h-[80vh] overflow-y-auto">
            <h3 className="text-lg font-semibold mb-4">Synapse Pipeline Drift Details</h3>

            <div className="space-y-4">
              {/* Metadata grid */}
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-sm text-gray-600">Workspace</div>
                  <div className="font-medium">{selectedDrift.workspace_name}</div>
                </div>
                <div>
                  <div className="text-sm text-gray-600">Pipeline</div>
                  <div className="font-medium">{selectedDrift.pipeline_name}</div>
                </div>
                <div>
                  <div className="text-sm text-gray-600">Drift Type</div>
                  <div className="font-medium">{selectedDrift.drift_type}</div>
                </div>
                <div>
                  <div className="text-sm text-gray-600">Severity</div>
                  <span
                    className={`px-2 py-1 rounded-full text-xs ${getSeverityColor(selectedDrift.severity)}`}
                  >
                    {selectedDrift.severity}
                  </span>
                </div>
              </div>

              {/* Checksums */}
              <div>
                <div className="text-sm text-gray-600 mb-1">Baseline Checksum</div>
                <div className="font-mono text-xs bg-gray-100 p-2 rounded break-all">
                  {selectedDrift.previous_checksum ?? selectedDrift.baseline_checksum ?? "—"}
                </div>
              </div>
              <div>
                <div className="text-sm text-gray-600 mb-1">Current Checksum</div>
                <div className="font-mono text-xs bg-red-50 p-2 rounded break-all">
                  {selectedDrift.current_checksum ?? "—"}
                </div>
              </div>

              {/* Diff summary */}
              {selectedDrift.diff_summary && (
                <div>
                  <div className="text-sm text-gray-600 mb-1">Diff Summary</div>
                  <pre className="text-xs bg-gray-100 p-2 rounded overflow-x-auto">
                    {JSON.stringify(selectedDrift.diff_summary, null, 2)}
                  </pre>
                </div>
              )}

              {/* Acknowledge input */}
              {!selectedDrift.acknowledged && (
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-2">
                    Acknowledgement Reason
                  </label>
                  <textarea
                    value={ackReason}
                    onChange={(e) => setAckReason(e.target.value)}
                    className="w-full px-3 py-2 border rounded-lg"
                    rows={3}
                    placeholder="Provide a reason for acknowledging this drift..."
                  />
                </div>
              )}

              {/* Footer buttons */}
              <div className="flex justify-end gap-3 pt-4">
                <button
                  onClick={() => {
                    setSelectedDrift(null);
                    setAckReason("");
                  }}
                  className="px-4 py-2 text-gray-600 hover:bg-gray-100 rounded-lg"
                >
                  Close
                </button>
                {canWrite && !selectedDrift.acknowledged && (
                  <button
                    onClick={handleAcknowledge}
                    disabled={!ackReason || acknowledgeDriftMutation.isPending}
                    className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-700 disabled:opacity-50"
                  >
                    {acknowledgeDriftMutation.isPending ? "Acknowledging..." : "Acknowledge"}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
