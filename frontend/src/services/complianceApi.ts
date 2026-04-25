/**
 * Compliance & Drift Detection API client and React Query hooks.
 * 
 * Provides:
 * - Synapse pipeline drift detection
 * - AKS pod drift detection
 * - Compliance scoring
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import apiClient from "./apiClient";

const GRID_POLL_INTERVAL = 120_000; // 2 min — reduces backend load on grid pages
const DASHBOARD_POLL_INTERVAL = 5 * 60 * 1000; // 5 min — data is pre-computed in DB

// ── Types ─────────────────────────────────────────────────────────────

export interface SynapseDrift {
  id: number;
  detection_date: string;
  detected_at?: string; // alias for detection_date
  workspace_name: string;
  pipeline_name: string;
  drift_type: "added" | "modified" | "deleted";
  previous_checksum: string | null;
  baseline_checksum?: string | null; // alias
  current_checksum: string | null;
  diff_summary: Record<string, unknown>;
  acknowledged: boolean;
  acknowledged_by: string | null;
  compliance_status: string;
  severity?: "critical" | "high" | "medium" | "low"; // optional for Synapse
}

export interface SynapseDriftSummary {
  total_drifts: number;
  total_pipelines?: number;
  compliant_pipelines?: number;
  drifted_pipelines?: number;
  acknowledged_drifts?: number;
  by_type: {
    added: number;
    modified: number;
    deleted: number;
  };
  by_workspace: Record<string, number>;
  timeline: Array<{ date: string; count: number }>;
  unacknowledged: number;
}

export interface AKSPodDrift {
  id: number;
  detection_date: string;
  detected_at?: string; // alias for detection_date
  cluster_name: string;
  namespace: string;
  pod_name: string;
  owner_kind: string;
  owner_name: string;
  drift_type: string;
  drift_category: string;
  severity: "critical" | "high" | "medium" | "low";
  previous_value: unknown;
  current_value: unknown;
  baseline_checksum?: string;
  current_checksum?: string;
  acknowledged: boolean;
  compliance_status: string;
  diff_summary?: Record<string, unknown>;
}

export interface ComplianceScore {
  resource_id: string;
  resource_name: string;
  overall_score: number;
  current_score?: number;
  drift_score: number;
  issues: {
    critical: number;
    high: number;
    medium: number;
    low: number;
    unacknowledged: number;
  };
  components?: number;
  grade: "A" | "B" | "C" | "D" | "F";
  calculated_at?: string;
}

export interface ComplianceDashboard {
  overall_score: {
    current_score: number;
    grade: "A" | "B" | "C" | "D" | "F";
    calculated_at: string;
    components: Array<{ name: string; score: number; weight?: number }>;
  };
  overall_grade: string;
  total_resources: number;
  by_type: Record<string, { count: number; avg_score: number }>;
  by_grade: Record<string, number>;
  critical_issues: number;
  high_issues: number;
  score_trend?: Array<{ date: string; score: number }>;
  synapse_summary?: any;
  aks_summary?: any;
  resources?: Array<{
    id: string;
    name: string;
    type: string;
    score: number;
    grade: string;
    critical_issues: number;
  }>;
  calculated_at?: string;
}

export interface DriftCategory {
  id: string;
  name: string;
  description: string;
  severity: string;
  icon: string;
}

export interface DriftSeverity {
  id: string;
  name: string;
  color: string;
  priority: number;
}

export interface DriftCategoriesResponse {
  categories: DriftCategory[];
  severities: DriftSeverity[];
  grading_scale: Record<string, { min: number; max: number; description: string }>;
  synapse_categories?: DriftCategory[];
  aks_categories?: DriftCategory[];
}

// ── API Functions ─────────────────────────────────────────────────────

const API_PREFIX = "/compliance";

// Synapse Pipeline Drift
export async function collectSynapseChecksums(
  subscriptionIds?: string[],
  workspaceName?: string,
): Promise<{ workspaces: number; pipelines: number; errors: { workspace: string; error: string }[]; status?: string; error?: string }> {
  const { data } = await apiClient.post(`${API_PREFIX}/synapse/collect-checksums`, {
    subscription_ids: subscriptionIds,
    workspace_name: workspaceName,
  });
  return data;
}

export async function detectSynapseDrift(
  workspaceId?: string
): Promise<{ drifts: SynapseDrift[]; count: number }> {
  const params = workspaceId ? { workspace_name: workspaceId } : {};
  const { data } = await apiClient.get(`${API_PREFIX}/synapse/drift`, { params });
  return data;
}

export async function fetchSynapseDriftSummary(
  days: number = 7,
  workspaceId?: string
): Promise<SynapseDriftSummary> {
  const params = new URLSearchParams({ days: days.toString() });
  if (workspaceId) params.set("workspace_name", workspaceId);
  const { data } = await apiClient.get(`${API_PREFIX}/synapse/drift/summary`, { params });
  return data;
}

export async function acknowledgeSynapseDrift(
  driftId: number
): Promise<{ success: boolean; drift_id: number; acknowledged_by: string }> {
  const { data } = await apiClient.post(`${API_PREFIX}/synapse/drift/${driftId}/acknowledge`);
  return data;
}

// AKS Pod Drift
export async function collectPodChecksums(
  clusterId: string,
  namespaces?: string[]
): Promise<{ pods: number; namespaces: number; errors: unknown[] }> {
  const { data } = await apiClient.post(`${API_PREFIX}/aks/collect-checksums`, {
    cluster_id: clusterId,
    namespaces,
  });
  return data;
}

export async function detectPodDrift(
  clusterId: string,
  namespace?: string
): Promise<{ drifts: AKSPodDrift[]; count: number }> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  if (namespace) params.set("namespace", namespace);
  const { data } = await apiClient.get(`${API_PREFIX}/aks/drift`, { params });
  return data;
}

export async function fetchPodDriftTimeline(
  clusterId: string,
  days: number = 30,
  namespace?: string
): Promise<{ timeline: AKSPodDrift[]; count: number; days: number }> {
  const params = new URLSearchParams({ cluster_id: clusterId, days: days.toString() });
  if (namespace) params.set("namespace", namespace);
  const { data } = await apiClient.get(`${API_PREFIX}/aks/drift/timeline`, { params });
  return data;
}

// Compliance Scoring
export async function acknowledgePodDrift(
  driftId: number,
  comment?: string
): Promise<{ success: boolean; drift_id: number; acknowledged_by: string }> {
  const { data } = await apiClient.post(`${API_PREFIX}/aks/drift/${driftId}/acknowledge`, {
    comment,
  });
  return data;
}

// Compliance Scoring
export async function calculateComplianceScore(
  resourceType: string,
  resourceId: string,
  resourceName: string,
  subscriptionId: string
): Promise<ComplianceScore> {
  const { data } = await apiClient.post(`${API_PREFIX}/scores/calculate`, {
    resource_type: resourceType,
    resource_id: resourceId,
    resource_name: resourceName,
    subscription_id: subscriptionId,
  });
  return data;
}

export async function fetchComplianceDashboard(
  subscriptionIds?: string[],
  refresh?: boolean
): Promise<ComplianceDashboard> {
  const params = new URLSearchParams();
  if (subscriptionIds) {
    subscriptionIds.forEach((id) => params.append("subscription_ids", id));
  }
  if (refresh) {
    params.append("refresh", "true");
  }
  const { data } = await apiClient.get(`${API_PREFIX}/dashboard`, { params });
  return data;
}

export async function fetchDriftCategories(): Promise<DriftCategoriesResponse> {
  const { data } = await apiClient.get(`${API_PREFIX}/drift-categories`);
  return data;
}

// ── React Query Hooks ─────────────────────────────────────────────────

// Synapse hooks
export function useSynapseDriftSummary(days: number = 7, workspaceId?: string) {
  return useQuery({
    queryKey: ["synapse-drift-summary", days, workspaceId],
    queryFn: () => fetchSynapseDriftSummary(days, workspaceId),
    staleTime: 5 * 60 * 1000,
    refetchInterval: DASHBOARD_POLL_INTERVAL,
  });
}

export function useSynapseDrift(workspaceId?: string) {
  return useQuery({
    queryKey: ["synapse-drift", workspaceId],
    queryFn: () => detectSynapseDrift(workspaceId),
    staleTime: 5 * 60 * 1000,
    refetchInterval: GRID_POLL_INTERVAL,
  });
}

export function useCollectSynapseChecksums() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params?: { subscriptionIds?: string[]; workspaceName?: string }) =>
      collectSynapseChecksums(params?.subscriptionIds, params?.workspaceName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["synapse-drift"] });
      queryClient.invalidateQueries({ queryKey: ["synapse-drift-summary"] });
      queryClient.invalidateQueries({ queryKey: ["synapse-checksum-comparison"] });
    },
  });
}

export function useAcknowledgeSynapseDrift() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (driftId: number) => acknowledgeSynapseDrift(driftId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["synapse-drift"] });
      queryClient.invalidateQueries({ queryKey: ["synapse-drift-summary"] });
      queryClient.invalidateQueries({ queryKey: ["compliance-dashboard"] });
    },
  });
}

// AKS Pod Drift hooks
export function usePodDrift(clusterId: string, namespace?: string) {
  return useQuery({
    queryKey: ["pod-drift", clusterId, namespace],
    queryFn: async () => {
      if (!clusterId) {
        return { drifts: [] as AKSPodDrift[], count: 0 };
      }
      const result = await detectPodDrift(clusterId, namespace);
      return result;
    },
    enabled: !!clusterId,
    staleTime: 5 * 60 * 1000,
    refetchInterval: GRID_POLL_INTERVAL,
  });
}

export function usePodDriftTimeline(clusterId: string, days: number = 30, namespace?: string) {
  return useQuery({
    queryKey: ["pod-drift-timeline", clusterId, days, namespace],
    queryFn: async () => {
      try {
        if (!clusterId) return { timeline: [] as AKSPodDrift[], count: 0, days };
        return await fetchPodDriftTimeline(clusterId, days, namespace);
      } catch (err) {
        console.warn("Failed to fetch pod drift timeline", err);
        return { timeline: [] as AKSPodDrift[], count: 0, days };
      }
    },
    refetchInterval: GRID_POLL_INTERVAL,
  });
}

export function useCollectPodChecksums() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId, namespaces }: { clusterId: string; namespaces?: string[] }) =>
      collectPodChecksums(clusterId, namespaces),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["pod-drift", variables.clusterId] });
      queryClient.invalidateQueries({ queryKey: ["pod-drift-timeline", variables.clusterId] });
    },
  });
}

export function useAcknowledgePodDrift() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ driftId, comment }: { driftId: number; comment?: string }) =>
      acknowledgePodDrift(driftId, comment),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["pod-drift"] });
      queryClient.invalidateQueries({ queryKey: ["pod-drift-timeline"] });
      queryClient.invalidateQueries({ queryKey: ["compliance-dashboard"] });
    },
  });
}

// Normalize backend response to match the ComplianceDashboard shape the UI expects.
// The backend returns overall_score as a flat number and omits some summary fields.
function normalizeComplianceDashboard(raw: any): ComplianceDashboard {
  const normalized = { ...raw };

  // Backend returns overall_score as a number (e.g. 82.0);
  // the frontend expects { current_score, grade, calculated_at, components }.
  if (typeof normalized.overall_score === "number" || typeof normalized.overall_score === "undefined") {
    const score = typeof normalized.overall_score === "number" ? normalized.overall_score : 0;
    normalized.overall_score = {
      current_score: score,
      grade: normalized.overall_grade || "N/A",
      calculated_at: normalized.calculated_at || "",
      components: normalized.by_type
        ? Object.entries(normalized.by_type).map(([name, val]: [string, any]) => ({
            name,
            score: val?.avg_score ?? 0,
            weight: 1 / Math.max(Object.keys(normalized.by_type).length, 1),
          }))
        : [],
    };
  }

  // Provide defaults for missing summary sections
  if (!normalized.synapse_summary) {
    normalized.synapse_summary = { total_pipelines: 0, compliant_pipelines: 0, drifted_pipelines: 0 };
  }
  if (!normalized.aks_summary) {
    normalized.aks_summary = { clusters: 0, total_pods: 0, compliant_clusters: 0, drifted_clusters: 0, drifted_pods: 0 };
  }
  if (!normalized.score_trend) {
    normalized.score_trend = [];
  }

  return normalized as ComplianceDashboard;
}

// Compliance Dashboard hooks
export function useComplianceDashboard(subscriptionIds?: string[]) {
  return useQuery({
    queryKey: ["compliance-dashboard", subscriptionIds],
    queryFn: async () => normalizeComplianceDashboard(await fetchComplianceDashboard(subscriptionIds)),
    staleTime: 5 * 60 * 1000,
    refetchInterval: DASHBOARD_POLL_INTERVAL,
  });
}

export function useCalculateComplianceScore() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      resourceType,
      resourceId,
      resourceName,
      subscriptionId,
    }: {
      resourceType: string;
      resourceId: string;
      resourceName: string;
      subscriptionId: string;
    }) => calculateComplianceScore(resourceType, resourceId, resourceName, subscriptionId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["compliance-dashboard"] });
    },
  });
}

export function useDriftCategories() {
  return useQuery({
    queryKey: ["drift-categories"],
    queryFn: async () => {
      try {
        return await fetchDriftCategories();
      } catch (err) {
        console.warn("Failed to fetch drift categories, using fallback", err);
        return {
          categories: [
            { key: "synapse_pipeline", label: "Synapse Pipelines", description: "Pipeline configuration drift" },
            { key: "aks_pod", label: "AKS Pods", description: "Pod specification drift" },
          ],
          severities: [
            { key: "critical", label: "Critical", color: "#991b1b" },
            { key: "high", label: "High", color: "#ef4444" },
            { key: "medium", label: "Medium", color: "#f59e0b" },
            { key: "low", label: "Low", color: "#3b82f6" },
          ],
        };
      }
    },
    staleTime: Infinity, // Static data
  });
}

// ── Cache Refresh Functions ───────────────────────────────────────────

export function refreshSynapseDrift(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["synapse-drift"] });
  queryClient.invalidateQueries({ queryKey: ["synapse-drift-summary"] });
}

export function refreshPodDrift(queryClient: ReturnType<typeof useQueryClient>, clusterId: string) {
  queryClient.invalidateQueries({ queryKey: ["pod-drift", clusterId] });
  queryClient.invalidateQueries({ queryKey: ["pod-drift-timeline", clusterId] });
}

export async function refreshComplianceDashboard(queryClient: ReturnType<typeof useQueryClient>) {
  // Invalidate and refetch the dashboard — backend serves from DB cache.
  queryClient.invalidateQueries({ queryKey: ["compliance-dashboard"] });
}


// ── Synapse Workspace Grouping Types ─────────────────────────────────

export interface SynapseWorkspaceGroup {
  label: string;
  workspaces: ChecksumWorkspace[];
}

export interface SynapseGroupedWorkspacesResponse {
  groups: SynapseWorkspaceGroup[];
  total: number;
}

export interface ChecksumComparisonResponse {
  workspace_name: string;
  run_id: string | null;
  results: ChecksumResultItem[];
  total: number;
  passed: number;
  failed: number;
}

// ── Synapse Workspace Grouping API ───────────────────────────────────

async function fetchSynapseGroupedWorkspaces(): Promise<SynapseGroupedWorkspacesResponse> {
  const response = await apiClient.get(`${API_PREFIX}/synapse/workspaces`);
  return response.data;
}

async function fetchSynapseChecksumComparison(
  workspaceName: string,
): Promise<ChecksumComparisonResponse> {
  const response = await apiClient.get(`${API_PREFIX}/synapse/checksum-comparison`, {
    params: { workspace_name: workspaceName },
  });
  return response.data;
}

// ── Synapse Workspace Grouping Hooks ─────────────────────────────────

export function useSynapseGroupedWorkspaces() {
  return useQuery({
    queryKey: ["synapse-grouped-workspaces"],
    queryFn: async () => {
      try {
        return await fetchSynapseGroupedWorkspaces();
      } catch (err) {
        console.warn("Failed to fetch grouped workspaces", err);
        return { groups: [], total: 0 };
      }
    },
    staleTime: 300_000, // 5 min — workspace list rarely changes
    refetchInterval: DASHBOARD_POLL_INTERVAL,
  });
}

export function useSynapseChecksumComparison(workspaceName: string | null) {
  return useQuery({
    queryKey: ["synapse-checksum-comparison", workspaceName],
    queryFn: async (): Promise<ChecksumComparisonResponse> => {
      if (!workspaceName) return { workspace_name: "", run_id: null, results: [], total: 0, passed: 0, failed: 0 };
      const result = await fetchSynapseChecksumComparison(workspaceName);
      return result;
    },
    enabled: !!workspaceName,
    staleTime: 60_000,
    refetchInterval: GRID_POLL_INTERVAL,
  });
}


// ── Synapse Checksum Verification Types ──────────────────────────────

export interface ChecksumWorkspace {
  workspace_name: string;
  system: string;
  environment: string;
  region: string;
}

export interface ChecksumRun {
  run_id: string;
  module_type: string;
  system: string;
  environment: string;
  workspace_name: string;
  execution_date: string;
  total_pipelines: number;
  passed: number;
  failed: number;
  status: string;
}

export interface ChecksumResultItem {
  id: number;
  run_id: string;
  slno: number;
  pipeline_name: string;
  yesterday_hash: string | null;
  present_hash: string | null;
  last_published_date: string | null;
  result: "PASS" | "FAIL";
  workspace_name: string;
  system: string;
  environment: string;
  execution_date: string;
}

export interface ChecksumRunResponse {
  run_id: string;
  workspace_name?: string;
  module_type?: string;
  system?: string;
  environment?: string;
  execution_date: string;
  total: number;
  passed: number;
  failed: number;
  results: ChecksumResultItem[];
  /** Run status: "completed" or "failed" (when Azure SDK can't reach the workspace) */
  status?: "completed" | "failed";
  /** Error message when status is "failed" */
  error?: string;
  /** Batch-mode fields (present when workspace_name / cluster_id was empty) */
  mode?: "batch" | "single";
  workspaces_processed?: number;
  workspaces_failed?: number;
  clusters_processed?: number;
  clusters_failed?: number;
  message?: string;
  workspace_results?: Record<string, unknown>[];
  cluster_results?: Record<string, unknown>[];
}

export interface ChecksumResultsResponse {
  results: ChecksumResultItem[];
  total: number;
}

export interface ChecksumRunsResponse {
  runs: ChecksumRun[];
  total: number;
}

export interface ChecksumMetricsSummary {
  pass: number;
  fail: number;
  total: number;
}

export interface ChecksumDailyMetric {
  date: string;
  attcc_pass: number;
  attcc_fail: number;
  ces_pass: number;
  ces_fail: number;
}

export interface ChecksumMetrics {
  daily: ChecksumDailyMetric[];
  summary: Record<string, ChecksumMetricsSummary>;
}

export interface ChecksumEmailResponse {
  run_id: string;
  recipient: string;
  status: string;
  error: string | null;
}

// ── Checksum Verification API Functions ──────────────────────────────

async function fetchChecksumWorkspaces(params: {
  system?: string;
  environment?: string;
} = {}): Promise<ChecksumWorkspace[]> {
  const response = await apiClient.get(`${API_PREFIX}/checksum/workspaces`, { params });
  // API returns { workspaces: [...], total: N } — extract the array
  const data = response.data;
  return Array.isArray(data) ? data : (data?.workspaces ?? []);
}

async function runChecksumVerification(workspaceName: string, notificationEmails?: string[]): Promise<ChecksumRunResponse> {
  const response = await apiClient.post(`${API_PREFIX}/checksum/verify`, {
    workspace_name: workspaceName,
    ...(notificationEmails?.length ? { notification_emails: notificationEmails } : {}),
  });
  return response.data;
}

async function runAKSChecksumVerification(params: {
  cluster_id: string;
  system?: string;
  environment?: string;
  namespaces?: string[];
  notification_emails?: string[];
}): Promise<ChecksumRunResponse> {
  const response = await apiClient.post(`${API_PREFIX}/aks/checksum/verify`, params);
  return response.data;
}

async function fetchChecksumRuns(params: {
  system?: string;
  environment?: string;
  workspace_name?: string;
  days?: number;
  module_type?: string;
} = {}): Promise<ChecksumRunsResponse> {
  const response = await apiClient.get(`${API_PREFIX}/checksum/runs`, { params });
  return response.data;
}

async function fetchChecksumResults(params: {
  system?: string;
  environment?: string;
  workspace_name?: string;
  days?: number;
  status?: string;
  run_id?: string;
  module_type?: string;
}): Promise<ChecksumResultsResponse> {
  const response = await apiClient.get(`${API_PREFIX}/checksum/results`, { params });
  return response.data;
}

async function fetchChecksumMetrics(days: number = 30, module_type?: string): Promise<ChecksumMetrics> {
  const response = await apiClient.get(`${API_PREFIX}/checksum/metrics`, { params: { days, module_type } });
  return response.data;
}

async function downloadChecksumCsv(runId: string): Promise<Blob> {
  const response = await apiClient.get(`${API_PREFIX}/checksum/download/${runId}`, {
    responseType: "blob",
  });
  return response.data;
}

async function emailChecksumResults(runId: string, recipientEmail: string): Promise<ChecksumEmailResponse> {
  const response = await apiClient.post(`${API_PREFIX}/checksum/email`, {
    run_id: runId,
    recipient_email: recipientEmail,
  });
  return response.data;
}

// ── Checksum Verification React Query Hooks ──────────────────────────

export function useChecksumWorkspaces(params: { system?: string; environment?: string } = {}) {
  return useQuery({
    queryKey: ["checksum-workspaces", params],
    queryFn: async () => {
      try {
        return await fetchChecksumWorkspaces(params);
      } catch (err) {
        console.warn("Failed to fetch checksum workspaces", err);
        return [];
      }
    },
    staleTime: 300_000, // 5 minutes — workspace list rarely changes
  });
}

export function useRunChecksumVerification() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: { workspaceName: string; notification_emails?: string[] }) =>
      runChecksumVerification(params.workspaceName, params.notification_emails),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["checksum-results"] });
      queryClient.invalidateQueries({ queryKey: ["checksum-runs"] });
      queryClient.invalidateQueries({ queryKey: ["checksum-metrics"] });
      queryClient.invalidateQueries({ queryKey: ["synapse-drift"] });
      queryClient.invalidateQueries({ queryKey: ["synapse-drift-summary"] });
      queryClient.invalidateQueries({ queryKey: ["synapse-checksum-comparison"] });
    },
  });
}

export function useRunAKSChecksumVerification() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: { cluster_id: string; system?: string; environment?: string; namespaces?: string[] }) =>
      runAKSChecksumVerification(params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["checksum-results"] });
      queryClient.invalidateQueries({ queryKey: ["checksum-runs"] });
      queryClient.invalidateQueries({ queryKey: ["checksum-metrics"] });
      queryClient.invalidateQueries({ queryKey: ["pod-drift"] });
      queryClient.invalidateQueries({ queryKey: ["pod-drift-timeline"] });
    },
  });
}

export function useChecksumRuns(params: {
  system?: string;
  environment?: string;
  workspace_name?: string;
  days?: number;
  module_type?: string;
} = {}) {
  return useQuery({
    queryKey: ["checksum-runs", params],
    queryFn: async () => {
      try {
        return await fetchChecksumRuns(params);
      } catch (err) {
        console.warn("Failed to fetch checksum runs", err);
        return { runs: [], total: 0 };
      }
    },
    staleTime: 60_000,
    refetchInterval: GRID_POLL_INTERVAL,
  });
}

export function useChecksumResults(params: {
  system?: string;
  environment?: string;
  workspace_name?: string;
  days?: number;
  status?: string;
  run_id?: string;
  module_type?: string;
} = {}) {
  return useQuery({
    queryKey: ["checksum-results", params],
    queryFn: async () => {
      try {
        return await fetchChecksumResults(params);
      } catch (err) {
        console.warn("Failed to fetch checksum results", err);
        return { results: [], total: 0 };
      }
    },
    staleTime: 60_000,
    refetchInterval: GRID_POLL_INTERVAL,
  });
}

export function useChecksumMetrics(days: number = 30, moduleType?: string) {
  return useQuery({
    queryKey: ["checksum-metrics", days, moduleType],
    queryFn: async () => {
      try {
        return await fetchChecksumMetrics(days, moduleType);
      } catch (err) {
        console.warn("Failed to fetch checksum metrics", err);
        return {
          daily: [],
          summary: {
            attcc: { pass: 0, fail: 0, total: 0 },
            ces: { pass: 0, fail: 0, total: 0 },
          },
        };
      }
    },
    staleTime: 5 * 60 * 1000,
    refetchInterval: DASHBOARD_POLL_INTERVAL,
  });
}

export function useDownloadChecksumCsv() {
  return useMutation({
    mutationFn: (runId: string) => downloadChecksumCsv(runId),
    onSuccess: (blob, runId) => {
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `checksum_${runId}.csv`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    },
  });
}

export function useEmailChecksumResults() {
  return useMutation({
    mutationFn: ({ runId, recipientEmail }: { runId: string; recipientEmail: string }) =>
      emailChecksumResults(runId, recipientEmail),
  });
}

export function refreshChecksumResults(queryClient: ReturnType<typeof useQueryClient>) {
  queryClient.invalidateQueries({ queryKey: ["checksum-results"] });
  queryClient.invalidateQueries({ queryKey: ["checksum-runs"] });
  queryClient.invalidateQueries({ queryKey: ["checksum-metrics"] });
}


// ── AKS Drift Tab — API Functions & Hooks ─────────────────────────────

async function fetchAKSNamespaces(clusterId: string): Promise<{ namespaces: string[]; count: number }> {
  const { data } = await apiClient.get(`${API_PREFIX}/aks/namespaces`, { params: { cluster_id: clusterId } });
  return data;
}

export function useAKSNamespaces(clusterId: string | undefined) {
  return useQuery({
    queryKey: ["aks-namespaces", clusterId],
    queryFn: () => fetchAKSNamespaces(clusterId!),
    enabled: !!clusterId,
    staleTime: 5 * 60 * 1000,
  });
}

export function useAKSChecksumRuns(params: {
  workspace_name?: string;
  days?: number;
} = {}) {
  return useQuery({
    queryKey: ["aks-checksum-runs", params],
    queryFn: async () => {
      try {
        return await fetchChecksumRuns({ ...params, module_type: "aks" } as any);
      } catch {
        return { runs: [], total: 0 };
      }
    },
    staleTime: 60_000,
    refetchInterval: GRID_POLL_INTERVAL,
  });
}

async function fetchChecksumRunsWithModule(params: Record<string, any>): Promise<ChecksumRunsResponse> {
  const response = await apiClient.get(`${API_PREFIX}/checksum/runs`, { params });
  return response.data;
}

async function fetchChecksumMetricsWithModule(params: { days: number; module_type?: string }): Promise<ChecksumMetrics> {
  const response = await apiClient.get(`${API_PREFIX}/checksum/metrics`, { params });
  return response.data;
}

export function useAKSChecksumMetrics(days: number = 30) {
  return useQuery({
    queryKey: ["aks-checksum-metrics", days],
    queryFn: async () => {
      try {
        return await fetchChecksumMetricsWithModule({ days, module_type: "aks" });
      } catch {
        return { daily: [], summary: {} };
      }
    },
    staleTime: 60_000,
    refetchInterval: DASHBOARD_POLL_INTERVAL,
  });
}

export function useRunAKSChecksumFull() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (params: { cluster_id: string; system?: string; environment?: string; namespaces?: string[]; notification_emails?: string[] }) =>
      runAKSChecksumVerification(params),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-checksum-runs"] });
      queryClient.invalidateQueries({ queryKey: ["aks-checksum-metrics"] });
      queryClient.invalidateQueries({ queryKey: ["checksum-results"] });
      queryClient.invalidateQueries({ queryKey: ["pod-drift"] });
    },
  });
}

export function useEmailAKSChecksumResults() {
  return useMutation({
    mutationFn: ({ runId, recipientEmail }: { runId: string; recipientEmail: string }) =>
      emailChecksumResults(runId, recipientEmail),
  });
}

export function useDownloadAKSChecksumCsv() {
  return useMutation({
    mutationFn: (runId: string) => downloadChecksumCsv(runId),
    onSuccess: (blob, runId) => {
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `aks_checksum_${runId}.csv`;
      document.body.appendChild(a);
      a.click();
      window.URL.revokeObjectURL(url);
      document.body.removeChild(a);
    },
  });
}
