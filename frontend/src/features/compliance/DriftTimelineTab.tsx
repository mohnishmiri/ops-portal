/**
 * DriftTimelineTab — Drift timeline visualization with trend charts,
 * category breakdowns (pie), and recent activity feed.
 *
 * Uses Synapse drift data (all workspaces) and AKS checksum results
 * to build a unified timeline overview.
 */

import React, { useMemo } from "react";
import {
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  ResponsiveContainer,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
} from "recharts";
import {
  type AKSPodDrift,
  type SynapseDrift,
  useSynapseDrift,
  useSynapseDriftSummary,
  useChecksumRuns,
  useAKSChecksumRuns,
} from "../../services/complianceApi";
import { COLORS, PIE_COLORS } from "./ComplianceDashboard";
import { usePortalTimezone } from "../../contexts/TimezoneContext";

// ── Local Icons (subset needed by this tab) ───────────────────────────

const Icons = {
  synapse: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M5 3v4M3 5h4M6 17v4M4 19h4M13 3l4 4M17 3l-4 4M14 17l4 4M17 17l-4 4M12 8v8M8 12h8" />
    </svg>
  ),
  kubernetes: (cls = "") => (
    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" width={20} height={20} className={cls}>
      <path d="M12 2L2 7l10 5 10-5-10-5z" /><path d="M2 17l10 5 10-5" /><path d="M2 12l10 5 10-5" />
    </svg>
  ),
};

// ── Props ─────────────────────────────────────────────────────────────

interface DriftTimelineTabProps {
  onShowToast: (message: string, type?: "success" | "error" | "info") => void;
}

// ── Component ─────────────────────────────────────────────────────────

export default function DriftTimelineTab({ onShowToast }: DriftTimelineTabProps) {
  void onShowToast;
  const { timezone } = usePortalTimezone();

  // ── Data hooks ────────────────────────────────────────────────────
  const { data: synapseDriftData } = useSynapseDrift("all");
  const { data: synapseSummary } = useSynapseDriftSummary(30);
  const { data: synapseRuns } = useChecksumRuns({ days: 30, module_type: "synapse" });
  const { data: aksRuns } = useAKSChecksumRuns({ days: 30 });

  // ── Build drift timeline from synapse drift detection dates ───────
  const timelineData = useMemo(() => {
    const drifts = synapseDriftData?.drifts ?? [];
    if (drifts.length === 0) return [];

    const dateMap = new Map<string, number>();
    for (const d of drifts) {
      const dateStr = new Date(d.detected_at ?? d.detection_date).toLocaleDateString("en-CA", { timeZone: timezone });
      dateMap.set(dateStr, (dateMap.get(dateStr) ?? 0) + 1);
    }
    return Array.from(dateMap.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, drift_count]) => ({ date, drift_count }));
  }, [synapseDriftData]);

  // ── Build category breakdown from actual drift data ───────────────
  const categoryData = useMemo(() => {
    const synapseDrifts = synapseDriftData?.drifts ?? [];
    const synapseByType = new Map<string, number>();
    for (const d of synapseDrifts) {
      const type = d.drift_type || "unknown";
      synapseByType.set(type, (synapseByType.get(type) ?? 0) + 1);
    }
    const synapse_categories = Array.from(synapseByType.entries())
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count);

    // AKS: derive from checksum runs (failed = drift detected)
    const aksRunsList = aksRuns?.runs ?? [];
    const aksByCluster = new Map<string, number>();
    for (const r of aksRunsList) {
      if (r.failed > 0) {
        const name = r.workspace_name || "unknown";
        aksByCluster.set(name, (aksByCluster.get(name) ?? 0) + r.failed);
      }
    }
    const aks_categories = Array.from(aksByCluster.entries())
      .map(([name, count]) => ({ name, count }))
      .sort((a, b) => b.count - a.count);

    return { synapse_categories, aks_categories };
  }, [synapseDriftData, aksRuns]);

  // ── Build checksum run timeline (combined synapse + AKS) ──────────
  const runsTimelineData = useMemo(() => {
    const allRuns = [
      ...(synapseRuns?.runs ?? []).map((r) => ({ ...r, source: "synapse" as const })),
      ...(aksRuns?.runs ?? []).map((r) => ({ ...r, source: "aks" as const })),
    ];
    if (allRuns.length === 0) return [];

    const dateMap = new Map<string, { synapse_pass: number; synapse_fail: number; aks_pass: number; aks_fail: number }>();
    for (const r of allRuns) {
      const dateStr = new Date(r.execution_date).toLocaleDateString("en-CA", { timeZone: timezone });
      const entry = dateMap.get(dateStr) ?? { synapse_pass: 0, synapse_fail: 0, aks_pass: 0, aks_fail: 0 };
      if (r.source === "synapse") {
        entry.synapse_pass += r.passed;
        entry.synapse_fail += r.failed;
      } else {
        entry.aks_pass += r.passed;
        entry.aks_fail += r.failed;
      }
      dateMap.set(dateStr, entry);
    }
    return Array.from(dateMap.entries())
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([date, vals]) => ({ date, ...vals }));
  }, [synapseRuns, aksRuns]);


  // ── JSX ───────────────────────────────────────────────────────────
  return (
    <div className="space-y-4">
      <h2 className="text-xl font-semibold text-gray-800">
        Drift Detection Timeline
      </h2>

      {/* ── Summary Cards ────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
          <div className="text-2xl font-bold text-gray-800">
            {synapseSummary?.total_pipelines ?? "—"}
          </div>
          <div className="text-sm text-gray-600">Total Synapse Pipelines</div>
        </div>
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
          <div className="text-2xl font-bold text-red-600">
            {synapseSummary?.drifted_pipelines ?? "—"}
          </div>
          <div className="text-sm text-gray-600">Drifts Detected</div>
        </div>
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
          <div className="text-2xl font-bold text-green-600">
            {synapseSummary?.acknowledged_drifts ?? "—"}
          </div>
          <div className="text-sm text-gray-600">Acknowledged</div>
        </div>
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-4">
          <div className="text-2xl font-bold text-blue-600">
            {(aksRuns?.runs?.length ?? 0) + (synapseRuns?.runs?.length ?? 0)}
          </div>
          <div className="text-sm text-gray-600">Checksum Runs (30d)</div>
        </div>
      </div>

      {/* ── Section 1: Drift Over Time (Line Chart from drift data) ─ */}
      {timelineData.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">
            Synapse Drift Over Time
          </h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={timelineData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="date"
                tickFormatter={(d: string) =>
                  new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: timezone })
                }
              />
              <YAxis />
              <Tooltip
                labelFormatter={(d: string) =>
                  new Date(d).toLocaleDateString(undefined, { timeZone: timezone })
                }
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line
                type="monotone"
                dataKey="drift_count"
                stroke={COLORS.danger}
                strokeWidth={2}
                dot={{ r: 4 }}
                name="Drifts Detected"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── Section 1b: Checksum Runs Timeline (Synapse + AKS) ───── */}
      {runsTimelineData.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">
            Checksum Verification Runs (30 days)
          </h3>
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={runsTimelineData}>
              <CartesianGrid strokeDasharray="3 3" />
              <XAxis
                dataKey="date"
                tickFormatter={(d: string) =>
                  new Date(d).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: timezone })
                }
              />
              <YAxis />
              <Tooltip labelFormatter={(d: string) => new Date(d).toLocaleDateString(undefined, { timeZone: timezone })} />
              <Line type="monotone" dataKey="synapse_pass" stroke={COLORS.success} strokeWidth={2} name="Synapse Pass" />
              <Line type="monotone" dataKey="synapse_fail" stroke={COLORS.danger} strokeWidth={2} name="Synapse Fail" strokeDasharray="5 5" />
              <Line type="monotone" dataKey="aks_pass" stroke={COLORS.primary} strokeWidth={2} name="AKS Pass" />
              <Line type="monotone" dataKey="aks_fail" stroke={COLORS.warning} strokeWidth={2} name="AKS Fail" strokeDasharray="5 5" />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* ── Section 2: Drift by Category (Pie Charts) ────────────── */}
      {(categoryData.synapse_categories.length > 0 || categoryData.aks_categories.length > 0) && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">
            Drift by Category
          </h3>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            {/* Synapse Categories */}
            {categoryData.synapse_categories.length > 0 && (
              <div>
                <h4 className="font-medium text-gray-700 mb-3">
                  Synapse Pipeline Drift
                </h4>
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Pie
                      data={categoryData.synapse_categories.map((c) => ({
                        name: c.name,
                        value: c.count,
                      }))}
                      cx="50%"
                      cy="50%"
                      outerRadius={70}
                      dataKey="value"
                      label={({ name, value }: { name: string; value: number }) =>
                        `${name}: ${value}`
                      }
                    >
                      {categoryData.synapse_categories.map((_, index) => (
                        <Cell key={index} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* AKS Categories */}
            {categoryData.aks_categories.length > 0 && (
              <div>
                <h4 className="font-medium text-gray-700 mb-3">
                  AKS Pod Drift (by cluster)
                </h4>
                <ResponsiveContainer width="100%" height={200}>
                  <PieChart>
                    <Pie
                      data={categoryData.aks_categories.map((c) => ({
                        name: c.name,
                        value: c.count,
                      }))}
                      cx="50%"
                      cy="50%"
                      outerRadius={70}
                      dataKey="value"
                      label={({ name, value }: { name: string; value: number }) =>
                        `${name}: ${value}`
                      }
                    >
                      {categoryData.aks_categories.map((_, index) => (
                        <Cell key={index} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>
      )}

      {/* ── No Data Fallback ─────────────────────────────────────── */}
      {timelineData.length === 0 && runsTimelineData.length === 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-10 text-center">
          <div className="text-gray-400 mb-2">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} width={48} height={48} className="mx-auto">
              <line x1="12" y1="20" x2="12" y2="10" /><line x1="18" y1="20" x2="18" y2="4" /><line x1="6" y1="20" x2="6" y2="16" />
            </svg>
          </div>
          <p className="text-lg text-gray-500 mb-1">No drift data available yet</p>
          <p className="text-sm text-gray-400">
            Run checksum verifications from the Synapse or AKS tabs to generate drift timeline data.
          </p>
        </div>
      )}
    </div>
  );
}
