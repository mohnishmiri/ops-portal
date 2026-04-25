/**
 * ComplianceDashboard.tsx
 *
 * Modular dashboard component for the Compliance & Drift Detection module.
 * Displays overall compliance score, stats, trend charts, grade distribution,
 * resource table, recent activity feed, and Excel export.
 */
import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useAuth } from "../../contexts/AuthContext";
import {
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
  AreaChart,
  Area,
  BarChart,
  Bar,
  CartesianGrid,
  XAxis,
  YAxis,
  Tooltip,
} from "recharts";
import {
  useComplianceDashboard,
  useCalculateComplianceScore,
  refreshComplianceDashboard,
} from "../../services/complianceApi";
import apiClient from "../../services/apiClient";
import { MetricCard, MetricCardIcons } from "../../components/MetricCard";
import { AutoRefreshIndicator, gridStyles, nextSortState, SortableHeader, type SortState } from "../../components/gridStyles";
import { usePortalTimezone } from "../../contexts/TimezoneContext";

// ── Constants ──────────────────────────────────────────────────────────

export const COLORS = {
  primary: "#3f9bca",
  success: "#10b981",
  warning: "#f59e0b",
  danger: "#ef4444",
  critical: "#7c3aed",
  neutral: "#6b7280",
} as const;

export const PIE_COLORS = [
  "#3f9bca",
  "#2e80ac",
  "#10b981",
  "#f59e0b",
  "#ef4444",
  "#7c3aed",
  "#246690",
  "#14b8a6",
  "#f97316",
];

const RESOURCE_PAGE_SIZE = 8;

type ResourceRow = {
  id: string;
  name: string;
  type: string;
  score: number;
  grade: string;
  critical_issues: number;
};

type ResourceSortKey = "name" | "type" | "score" | "grade" | "critical_issues";

const GRADE_CONFIG: Record<string, { bg: string; text: string; label: string }> = {
  A: { bg: "bg-green-100", text: "text-green-800", label: "Excellent" },
  B: { bg: "bg-blue-100", text: "text-blue-800", label: "Good" },
  C: { bg: "bg-yellow-100", text: "text-yellow-800", label: "Fair" },
  D: { bg: "bg-orange-100", text: "text-orange-800", label: "Poor" },
  F: { bg: "bg-red-100", text: "text-red-800", label: "Critical" },
};

const GRADE_CARD_STYLES: Record<
  string,
  {
    tone: "green" | "blue" | "amber" | "orange" | "red";
    icon: React.ReactNode;
  }
> = {
  A: { tone: "green", icon: MetricCardIcons.checkCircle() },
  B: { tone: "blue", icon: MetricCardIcons.shield() },
  C: { tone: "amber", icon: MetricCardIcons.activity() },
  D: { tone: "orange", icon: MetricCardIcons.alert() },
  F: { tone: "red", icon: MetricCardIcons.alert() },
};

// ── Helpers ────────────────────────────────────────────────────────────

export function getGradeColor(grade: string): string {
  const map: Record<string, string> = {
    A: "bg-green-100 text-green-800",
    B: "bg-blue-100 text-blue-800",
    C: "bg-yellow-100 text-yellow-800",
    D: "bg-orange-100 text-orange-800",
    F: "bg-red-100 text-red-800",
  };
  return map[grade?.toUpperCase()] ?? "bg-gray-100 text-gray-800";
}

export function getSeverityColor(severity: string): string {
  const map: Record<string, string> = {
    critical: "bg-red-100 text-red-800",
    high: "bg-orange-100 text-orange-800",
    medium: "bg-yellow-100 text-yellow-800",
    low: "bg-green-100 text-green-800",
  };
  return map[severity?.toLowerCase()] ?? "bg-gray-100 text-gray-800";
}

function formatDate(value: string | undefined, timezone: string): string {
  if (!value) return "N/A";
  return new Date(value).toLocaleDateString("en-US", {
    timeZone: timezone,
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZoneName: "short",
  });
}

function formatShortDate(value: string, timezone: string): string {
  return new Date(value).toLocaleDateString("en-US", {
    timeZone: timezone,
    month: "short",
    day: "numeric",
  });
}

// ── SVG Icons ──────────────────────────────────────────────────────────

const Icons = {
  shield: (cls = "w-5 h-5") => (
    <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    </svg>
  ),
  synapse: (cls = "w-5 h-5") => (
    <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="3" /><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83" />
    </svg>
  ),
  kubernetes: (cls = "w-5 h-5") => (
    <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M14.7 6.3a1 1 0 000 1.4l1.6 1.6a1 1 0 001.4 0l3.77-3.77a6 6 0 01-7.94 7.94l-6.91 6.91a2.12 2.12 0 01-3-3l6.91-6.91a6 6 0 017.94-7.94l-3.76 3.76z" />
    </svg>
  ),
  refresh: (cls = "w-5 h-5") => (
    <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="23 4 23 10 17 10" /><path d="M20.49 15a9 9 0 11-2.12-9.36L23 10" />
    </svg>
  ),
  download: (cls = "w-5 h-5") => (
    <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" /><polyline points="7 10 12 15 17 10" /><line x1="12" y1="15" x2="12" y2="3" />
    </svg>
  ),
  calculator: (cls = "w-5 h-5") => (
    <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="4" y="2" width="16" height="20" rx="2" /><line x1="8" y1="6" x2="16" y2="6" /><line x1="16" y1="14" x2="16" y2="18" /><line x1="8" y1="10" x2="8" y2="10.01" /><line x1="12" y1="10" x2="12" y2="10.01" /><line x1="16" y1="10" x2="16" y2="10.01" /><line x1="8" y1="14" x2="8" y2="14.01" /><line x1="12" y1="14" x2="12" y2="14.01" /><line x1="8" y1="18" x2="8" y2="18.01" /><line x1="12" y1="18" x2="12" y2="18.01" />
    </svg>
  ),
  alert: (cls = "w-5 h-5") => (
    <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" /><line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12" y2="17.01" />
    </svg>
  ),
  drift: (cls = "w-5 h-5") => (
    <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <polyline points="22 12 18 12 15 21 9 3 6 12 2 12" />
    </svg>
  ),
  check: (cls = "w-5 h-5") => (
    <svg className={cls} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M22 11.08V12a10 10 0 11-5.93-9.14" /><polyline points="22 4 12 14.01 9 11.01" />
    </svg>
  ),
};

// ── Loading Skeleton ───────────────────────────────────────────────────

function DashboardSkeleton() {
  return (
    <div className="space-y-6 animate-pulse">
      <div className="flex justify-between items-center">
        <div className="h-7 w-64 bg-gray-200 rounded" />
        <div className="flex gap-2">
          <div className="h-10 w-28 bg-gray-200 rounded-lg" />
          <div className="h-10 w-28 bg-gray-200 rounded-lg" />
        </div>
      </div>
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <div className="h-20 bg-gray-200 rounded" />
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {[1, 2, 3, 4].map((i) => (
          <div key={i} className="bg-white rounded-xl shadow-sm border border-gray-100 p-4 h-24">
            <div className="h-4 w-24 bg-gray-200 rounded mb-2" />
            <div className="h-8 w-16 bg-gray-200 rounded" />
          </div>
        ))}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-gray-100 rounded-xl border border-gray-200 p-6 h-72" />
        <div className="bg-gray-100 rounded-xl border border-gray-200 p-6 h-72" />
      </div>
    </div>
  );
}

// ── Props ──────────────────────────────────────────────────────────────

interface ComplianceDashboardProps {
  onShowToast: (message: string, type?: "success" | "error" | "warning" | "info") => void;
}

// ── Component ──────────────────────────────────────────────────────────

const ComplianceDashboard: React.FC<ComplianceDashboardProps> = ({ onShowToast }) => {
  const queryClient = useQueryClient();
  const { timezone } = usePortalTimezone();
  const { canWrite } = useAuth();
  const [exportLoading, setExportLoading] = useState(false);
  const [resourceSearch, setResourceSearch] = useState("");
  const [resourcePage, setResourcePage] = useState(0);
  const [resourceSort, setResourceSort] = useState<SortState<ResourceSortKey>>({
    key: "score",
    direction: "desc",
  });

  // ── Data hooks ───────
  const { data: dashboardData, isLoading: dashboardLoading } = useComplianceDashboard();
  const calculateScoreMutation = useCalculateComplianceScore();

  // ── Derived data ─────
  const scoreComponents = useMemo(() => {
    if (!dashboardData?.overall_score?.components) return [];
    return dashboardData.overall_score.components.map(
      (c: { name: string; score: number; weight: number }) => ({
        name: c.name,
        value: c.score,
        weight: c.weight,
      })
    );
  }, [dashboardData]);

  const gradeDistribution = useMemo(() => {
    if (!dashboardData?.by_grade) return [];
    return Object.entries(dashboardData.by_grade).map(([grade, count]) => ({
      grade,
      count: count as number,
      fill: GRADE_CONFIG[grade]?.bg === "bg-green-100" ? COLORS.success
        : grade === "B" ? COLORS.primary
        : grade === "C" ? COLORS.warning
        : grade === "D" ? "#f97316"
        : COLORS.danger,
    }));
  }, [dashboardData]);

  const resourceRows = useMemo<ResourceRow[]>(() => {
    return (dashboardData?.resources ?? []) as ResourceRow[];
  }, [dashboardData]);

  const filteredResources = useMemo(() => {
    if (!resourceSearch) {
      return resourceRows;
    }

    const query = resourceSearch.toLowerCase();
    return resourceRows.filter((resource) => {
      return [resource.name, resource.type, resource.grade]
        .some((value) => value?.toLowerCase().includes(query));
    });
  }, [resourceRows, resourceSearch]);

  const sortedResources = useMemo(() => {
    return [...filteredResources].sort((left, right) => {
      const direction = resourceSort.direction === "asc" ? 1 : -1;

      if (resourceSort.key === "score" || resourceSort.key === "critical_issues") {
        return (left[resourceSort.key] - right[resourceSort.key]) * direction;
      }

      return String(left[resourceSort.key] ?? "")
        .localeCompare(String(right[resourceSort.key] ?? ""), undefined, { sensitivity: "base" }) * direction;
    });
  }, [filteredResources, resourceSort]);

  const resourceTotalPages = Math.max(1, Math.ceil(sortedResources.length / RESOURCE_PAGE_SIZE));
  const pagedResources = useMemo(() => {
    return sortedResources.slice(
      resourcePage * RESOURCE_PAGE_SIZE,
      (resourcePage + 1) * RESOURCE_PAGE_SIZE,
    );
  }, [resourcePage, sortedResources]);

  useEffect(() => {
    setResourcePage(0);
  }, [resourceSearch, resourceSort]);

  // ── Handlers ─────────

  const handleRecalculate = useCallback(() => {
    calculateScoreMutation.mutate(
      { resourceType: "all", resourceId: "all", resourceName: "Full Recalculation", subscriptionId: "all" },
      {
        onSuccess: () => onShowToast("Compliance scores recalculated", "success"),
        onError: () => onShowToast("Score recalculation failed", "error"),
      }
    );
  }, [calculateScoreMutation, onShowToast]);

  const handleRefresh = useCallback(() => {
    refreshComplianceDashboard(queryClient);
    onShowToast("Dashboard data refreshed", "info");
  }, [queryClient, onShowToast]);

  const handleExcelExport = useCallback(async () => {
    setExportLoading(true);
    try {
      const response = await apiClient.get("/compliance/export/excel", {
        responseType: "blob",
        params: {
          include_synapse_drift: true,
          include_aks_drift: true,
          include_scores: true,
          include_checksums: true,
        },
      });
      const blob = new Blob([response.data], {
        type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      });
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      const disposition = response.headers["content-disposition"];
      const filename = disposition
        ? disposition.split("filename=")[1]?.replace(/"/g, "")
        : `compliance_report_${new Date().toISOString().slice(0, 10)}.xlsx`;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.URL.revokeObjectURL(url);
      onShowToast("Excel report downloaded", "success");
    } catch {
      onShowToast("Excel export failed", "error");
    } finally {
      setExportLoading(false);
    }
  }, [onShowToast]);

  // ── Loading ──────────
  if (dashboardLoading) return <DashboardSkeleton />;

  // ── Empty state — no data OR backend returned zero resources ──────
  const hasData = dashboardData && dashboardData.total_resources > 0;
  if (!hasData) {
    return (
      <div className="flex flex-col items-center justify-center py-20 text-gray-400">
        {Icons.shield("w-16 h-16 mb-4")}
        <p className="text-lg font-medium mb-2">No compliance data available</p>
        <p className="text-sm mb-6">Run a compliance score calculation to populate the dashboard.</p>
        {canWrite && (
        <button
          onClick={handleRecalculate}
          disabled={calculateScoreMutation.isPending}
          className="flex items-center gap-2 rounded-lg bg-att-400 px-4 py-2 text-white hover:bg-att-500 disabled:opacity-50"
        >
          {Icons.calculator("w-4 h-4")}
          Calculate Scores
        </button>
        )}
      </div>
    );
  }

  const overallScore = dashboardData.overall_score;
  const currentScore = overallScore?.current_score ?? 0;
  const grade = overallScore?.grade ?? "N/A";
  const calculatedAt = overallScore?.calculated_at;
  const synapseSummary = dashboardData.synapse_summary;
  const aksSummary = dashboardData.aks_summary;

  // ── Render ───────────
  return (
    <div className="space-y-6">
      {/* ── Header ───────────────────────────────────────────────── */}
      <div className="flex flex-wrap justify-between items-center gap-4">
        <h2 className="text-xl font-semibold text-gray-800 flex items-center gap-2">
          {Icons.shield("w-6 h-6 text-att-500")}
          Compliance Dashboard
        </h2>
        <div className="flex flex-wrap gap-2">
          {canWrite && (
          <button
            onClick={handleRecalculate}
            disabled={calculateScoreMutation.isPending}
            className="flex items-center gap-2 rounded-lg bg-att-400 px-4 py-2 text-sm text-white hover:bg-att-500 disabled:opacity-50"
          >
            {calculateScoreMutation.isPending ? (
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              Icons.calculator("w-4 h-4")
            )}
            {calculateScoreMutation.isPending ? "Calculating..." : "Recalculate"}
          </button>
          )}

          {canWrite && (
          <button
            onClick={handleExcelExport}
            disabled={exportLoading}
            className="flex items-center gap-2 rounded-lg bg-att-600 px-4 py-2 text-sm text-white hover:bg-att-700 disabled:opacity-50"
          >
            {exportLoading ? (
              <svg className="animate-spin h-4 w-4" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
            ) : (
              Icons.download("w-4 h-4")
            )}
            {exportLoading ? "Exporting..." : "Export Excel"}
          </button>
          )}

          <button
            onClick={handleRefresh}
            className="flex items-center gap-2 px-3 py-2 bg-gray-100 text-gray-700 rounded-lg hover:bg-gray-200 text-sm"
          >
            {Icons.refresh("w-4 h-4")}
            Refresh
          </button>
        </div>
      </div>

      {/* ── Score Card ───────────────────────────────────────────── */}
      <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
        <div className="flex flex-col md:flex-row items-center md:items-start gap-6">
          {/* Score Ring */}
          <div className="relative flex-shrink-0">
            <svg className="w-32 h-32" viewBox="0 0 120 120">
              <circle cx="60" cy="60" r="50" fill="none" stroke="#e5e7eb" strokeWidth="10" />
              <circle
                cx="60"
                cy="60"
                r="50"
                fill="none"
                stroke={currentScore >= 80 ? COLORS.success : currentScore >= 60 ? COLORS.warning : COLORS.danger}
                strokeWidth="10"
                strokeDasharray={`${(currentScore / 100) * 314.16} 314.16`}
                strokeLinecap="round"
                transform="rotate(-90 60 60)"
              />
            </svg>
            <div className="absolute inset-0 flex flex-col items-center justify-center">
              <span className="text-3xl font-bold text-gray-900">{currentScore.toFixed(0)}%</span>
            </div>
          </div>

          {/* Score Details */}
          <div className="flex-1 text-center md:text-left">
            <div className="flex items-center gap-3 justify-center md:justify-start mb-2">
              <h3 className="text-lg font-semibold text-gray-800">Overall Compliance Score</h3>
              <span className={`px-3 py-1 rounded-full text-sm font-bold ${getGradeColor(grade)}`}>
                Grade {grade}
              </span>
            </div>
            <p className="text-sm text-gray-500 mb-3">
              Last updated: {formatDate(calculatedAt, timezone)}
            </p>
            <div className="flex flex-wrap gap-4 text-sm">
              <div>
                <span className="text-gray-500">Total Resources:</span>{" "}
                <span className="font-semibold">{dashboardData.total_resources ?? 0}</span>
              </div>
              <div>
                <span className="text-gray-500">Critical Issues:</span>{" "}
                <span className="font-semibold text-red-600">{dashboardData.critical_issues ?? 0}</span>
              </div>
              <div>
                <span className="text-gray-500">High Issues:</span>{" "}
                <span className="font-semibold text-orange-600">{dashboardData.high_issues ?? 0}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ── Stats Grid (4 Cards) ─────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          icon={Icons.synapse("w-5 h-5 text-purple-600")}
          label="Synapse Pipelines"
          value={synapseSummary?.total_pipelines ?? 0}
        />
        <StatCard
          icon={Icons.drift("w-5 h-5 text-red-600")}
          label="Synapse Drift"
          value={synapseSummary?.drifted_pipelines ?? 0}
          valueColor={synapseSummary?.drifted_pipelines ? "text-red-600" : undefined}
        />
        <StatCard
          icon={Icons.kubernetes("w-5 h-5 text-blue-600")}
          label="AKS Pods Tracked"
          value={aksSummary?.total_pods ?? 0}
        />
        <StatCard
          icon={Icons.alert("w-5 h-5 text-orange-600")}
          label="AKS Pod Drift"
          value={aksSummary?.drifted_pods ?? 0}
          valueColor={aksSummary?.drifted_pods ? "text-orange-600" : undefined}
        />
      </div>

      {/* ── Charts Row ───────────────────────────────────────────── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Score Components PieChart */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">Score Components</h3>
          {scoreComponents.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              <PieChart>
                <Pie
                  data={scoreComponents}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={100}
                  dataKey="value"
                  label={({ name, value }) => `${name}: ${(value as number).toFixed(0)}%`}
                >
                  {scoreComponents.map((_: unknown, index: number) => (
                    <Cell key={`cell-${index}`} fill={PIE_COLORS[index % PIE_COLORS.length]} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(value: number, name: string) => [`${value.toFixed(1)}%`, name]}
                />
              </PieChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-64 text-gray-400 text-sm">
              No component data available
            </div>
          )}
        </div>

        {/* Score Trend AreaChart */}
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">30-Day Score Trend</h3>
          {dashboardData.score_trend && dashboardData.score_trend.length > 0 ? (
            <ResponsiveContainer width="100%" height={280}>
              <AreaChart data={dashboardData.score_trend}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis
                  dataKey="date"
                  tickFormatter={(v: string) => formatShortDate(v, timezone)}
                  tick={{ fontSize: 12 }}
                />
                <YAxis domain={[0, 100]} tick={{ fontSize: 12 }} />
                <Tooltip
                  labelFormatter={(label: string) => formatDate(label, timezone)}
                  formatter={(value: number) => [`${value.toFixed(1)}%`, "Score"]}
                />
                <Area
                  type="monotone"
                  dataKey="score"
                  stroke={COLORS.primary}
                  fill={COLORS.primary}
                  fillOpacity={0.3}
                />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="flex items-center justify-center h-64 text-gray-400 text-sm">
              Not enough trend data — scores appear after multiple daily calculations
            </div>
          )}
        </div>
      </div>

      {/* ── Grade Distribution ───────────────────────────────────── */}
      {gradeDistribution.length > 0 && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
          <h3 className="text-lg font-semibold text-gray-800 mb-4">Grade Distribution</h3>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-5">
            {["A", "B", "C", "D", "F"].map((g) => {
              const entry = gradeDistribution.find((d) => d.grade === g);
              const count = entry?.count ?? 0;
              const cfg = GRADE_CONFIG[g];
              const gradeCardStyle = GRADE_CARD_STYLES[g];
              return (
                <MetricCard
                  key={g}
                  title={`Grade ${g}`}
                  value={count}
                  subtitle={cfg?.label ?? ""}
                  icon={gradeCardStyle.icon}
                  tone={gradeCardStyle.tone}
                  className="h-full"
                />
              );
            })}
          </div>
        </div>
      )}

      {/* ── Resource Compliance Table ────────────────────────────── */}
      {resourceRows.length > 0 && (
        <div className={gridStyles.shell}>
          <div className={gridStyles.panelHeader}>
            <div className="flex flex-wrap items-center gap-3">
              <h3 className={gridStyles.sectionTitle}>Resource Compliance Scores</h3>
              <span className={gridStyles.countBadge}>
                {filteredResources.length} of {resourceRows.length} resource{resourceRows.length !== 1 ? "s" : ""}
              </span>
              <AutoRefreshIndicator />
            </div>
            <input
              type="text"
              placeholder="Search resources…"
              value={resourceSearch}
              onChange={(event) => setResourceSearch(event.target.value)}
              className={gridStyles.toolbarInput}
            />
          </div>
          <div className="overflow-x-auto">
            <table className={gridStyles.table}>
              <thead className={gridStyles.head}>
                <tr>
                  <th className={gridStyles.headerCell}>
                    <SortableHeader
                      label="Resource"
                      active={resourceSort.key === "name"}
                      direction={resourceSort.direction}
                      onClick={() => setResourceSort((current) => nextSortState(current, "name"))}
                    />
                  </th>
                  <th className={gridStyles.headerCell}>
                    <SortableHeader
                      label="Type"
                      active={resourceSort.key === "type"}
                      direction={resourceSort.direction}
                      onClick={() => setResourceSort((current) => nextSortState(current, "type"))}
                    />
                  </th>
                  <th className={gridStyles.headerCellCenter}>
                    <SortableHeader
                      label="Score"
                      active={resourceSort.key === "score"}
                      direction={resourceSort.direction}
                      onClick={() => setResourceSort((current) => nextSortState(current, "score"))}
                      align="center"
                    />
                  </th>
                  <th className={gridStyles.headerCellCenter}>
                    <SortableHeader
                      label="Grade"
                      active={resourceSort.key === "grade"}
                      direction={resourceSort.direction}
                      onClick={() => setResourceSort((current) => nextSortState(current, "grade"))}
                      align="center"
                    />
                  </th>
                  <th className={gridStyles.headerCellCenter}>
                    <SortableHeader
                      label="Detected Issues"
                      active={resourceSort.key === "critical_issues"}
                      direction={resourceSort.direction}
                      onClick={() => setResourceSort((current) => nextSortState(current, "critical_issues"))}
                      align="center"
                    />
                  </th>
                </tr>
              </thead>
              <tbody>
                {pagedResources.map((resource) => (
                    <tr key={resource.id} className={gridStyles.row}>
                      <td className={`${gridStyles.strongCell} text-gray-900`}>
                        {resource.name}
                      </td>
                      <td className={`${gridStyles.cell} capitalize`}>
                        {resource.type?.replace(/_/g, " ")}
                      </td>
                      <td className={gridStyles.centerCell}>
                        <div className="flex items-center justify-center gap-2">
                          <div className="h-2 w-16 rounded-full bg-att-100">
                            <div
                              className={`h-2 rounded-full ${
                                resource.score >= 80
                                  ? "bg-green-500"
                                  : resource.score >= 60
                                  ? "bg-yellow-500"
                                  : "bg-red-500"
                              }`}
                              style={{ width: `${Math.min(resource.score, 100)}%` }}
                            />
                          </div>
                          <span className="text-sm font-medium text-gray-700">
                            {resource.score.toFixed(0)}%
                          </span>
                        </div>
                      </td>
                      <td className={gridStyles.centerCell}>
                        <span
                          className={`inline-block px-2 py-1 rounded-full text-xs font-bold ${getGradeColor(
                            resource.grade
                          )}`}
                        >
                          {resource.grade}
                        </span>
                      </td>
                      <td className={gridStyles.centerCell}>
                        <span
                          className={`text-sm font-semibold ${
                            resource.critical_issues > 0 ? "text-red-600" : "text-gray-400"
                          }`}
                        >
                          {resource.critical_issues}
                        </span>
                      </td>
                    </tr>
                  ))}
                {pagedResources.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-8 text-center text-sm text-gray-400">
                      No resources match the current search.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {resourceTotalPages > 1 && (
            <div className={gridStyles.pager}>
              <span className="text-gray-600">
                Showing {resourcePage * RESOURCE_PAGE_SIZE + 1}–{Math.min((resourcePage + 1) * RESOURCE_PAGE_SIZE, sortedResources.length)} of {sortedResources.length} resources
              </span>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setResourcePage((pageNumber) => Math.max(0, pageNumber - 1))}
                  disabled={resourcePage === 0}
                  className={gridStyles.pagerButton}
                >
                  Previous
                </button>
                <span className="text-gray-700">
                  Page {resourcePage + 1} of {resourceTotalPages}
                </span>
                <button
                  onClick={() => setResourcePage((pageNumber) => Math.min(resourceTotalPages - 1, pageNumber + 1))}
                  disabled={resourcePage >= resourceTotalPages - 1}
                  className={gridStyles.pagerButton}
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* ── Recent Activity Feed removed — not relevant for org-level use ─── */}
    </div>
  );
};

// ── Sub-components ─────────────────────────────────────────────────────

interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: number;
  valueColor?: string;
}

function StatCard({ icon, label, value, valueColor }: StatCardProps) {
  const tone = valueColor?.includes("red")
    ? "red"
    : valueColor?.includes("orange")
      ? "orange"
      : label.includes("Synapse")
        ? "purple"
        : label.includes("AKS")
          ? "blue"
          : "att";

  return (
    <MetricCard
      title={label}
      value={value}
      icon={icon}
      tone={tone}
      valueClassName={valueColor}
    />
  );
}

export default ComplianceDashboard;
