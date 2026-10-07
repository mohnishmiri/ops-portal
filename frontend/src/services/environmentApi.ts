/**
 * Environment Scaling & Scheduling API client and React Query hooks.
 *
 * Provides:
 * - Manual environment scale up / down
 * - Schedule CRUD for automated scaling
 * - Sequence CRUD for ordered startup / shutdown
 * - Execution history
 * - Environment status
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import apiClient from "./apiClient";

// ── Types ─────────────────────────────────────────────────────────────

export interface EnvironmentScaleRequest {
  cluster_id: string;
  namespace: string;
  operation: "scale_up" | "scale_down";
  scope: "namespace" | "selected";
  deployment_names?: string[];
  replica_count: number;
  dry_run?: boolean;
}

export interface EnvironmentScaleResult {
  execution_id: number;
  status: string;
  total_deployments: number;
  completed: number;
  failed: number;
  skipped: number;
  details: StepDetail[];
}

export interface StepDetail {
  deployment: string;
  /** Replica count before the step ran (the "from" of 0 → 60). */
  current_replicas?: number | null;
  target_replicas: number;
  status: string;
  error?: string;
  order?: number;
  // Set by the sequence executor per step (environment_scaling_service.py).
  /** 1-based execution position; a deployment can appear in several steps. */
  step?: number;
  wait_condition?: string;
  timeout_seconds?: number;
  on_failure?: string;
  started_at?: string;
  duration_seconds?: number;
  min_ready_percent?: number;
  /** Live while a pod wait runs: pods ready so far and pods needed. */
  ready_replicas?: number;
  required_ready?: number;
  last_progress_at?: string;
  /** Why pods are not ready yet, e.g. "3 pods unschedulable (Insufficient cpu)". */
  pod_issues?: string;
  note?: string;
  rollback_status?: "rolled_back" | "rollback_failed";
  rolled_back_to?: number;
  rollback_error?: string;
}

export interface EnvironmentSchedule {
  id: number;
  job_name: string;
  cluster_id: string;
  namespace: string;
  operation: string;
  replica_count: number;
  schedule_type: string;
  cron_expression: string | null;
  timezone: string;
  start_date: string | null;
  end_date: string | null;
  is_enabled: boolean;
  retry_count: number;
  failure_notification: string | null;
  sequence_id: number | null;
  created_by: string;
  created_by_email: string | null;
  created_at: string;
  updated_at: string;
  last_run_at: string | null;
  next_run_at: string | null;
  last_run_status: string | null;
}

export interface ScheduleCreateRequest {
  job_name: string;
  cluster_id: string;
  namespace: string;
  operation: "scale_up" | "scale_down";
  replica_count: number;
  schedule_type: "one_time" | "daily" | "weekly" | "monthly" | "cron";
  cron_expression?: string;
  timezone?: string;
  start_date?: string;
  end_date?: string;
  is_enabled?: boolean;
  retry_count?: number;
  failure_notification?: string;
  sequence_id?: number;
}

export interface ScheduleUpdateRequest {
  job_name?: string;
  operation?: "scale_up" | "scale_down";
  replica_count?: number;
  schedule_type?: "one_time" | "daily" | "weekly" | "monthly" | "cron";
  cron_expression?: string;
  timezone?: string;
  start_date?: string;
  end_date?: string;
  is_enabled?: boolean;
  retry_count?: number;
  failure_notification?: string;
  sequence_id?: number;
}

export interface SequenceStep {
  order: number;
  deployment_name: string;
  replicas: number;
  wait_condition: "pods_ready" | "health_endpoint" | "fixed_time" | "deployment_available" | "skip";
  /** Pod waits: fail after this long with no newly ready pod (restarts on progress). fixed_time: the wait. */
  timeout_seconds: number;
  /** Pod waits: move on once this share of the target pods is ready (default 100). */
  min_ready_percent?: number;
  health_endpoint?: string;
  retry_count: number;
  on_failure: "abort" | "continue";
}

export interface EnvironmentSequence {
  id: number;
  name: string;
  cluster_id: string;
  namespace: string;
  sequence_type: "startup" | "shutdown";
  steps: SequenceStep[];
  rollback_on_failure: boolean;
  created_by: string;
  created_by_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface SequenceCreateRequest {
  name: string;
  cluster_id: string;
  namespace: string;
  sequence_type: "startup" | "shutdown";
  steps: SequenceStep[];
  rollback_on_failure?: boolean;
}

export interface SequenceUpdateRequest {
  name?: string;
  steps?: SequenceStep[];
  rollback_on_failure?: boolean;
}

export interface SequenceExecuteRequest {
  sequence_id: number;
  replica_count?: number;
  dry_run?: boolean;
}

export interface ExecutionHistory {
  id: number;
  execution_type: string;
  cluster_id: string;
  namespace: string;
  operation: string;
  sequence_name?: string | null;
  schedule_name?: string | null;
  status: string;
  total_deployments: number;
  completed_count: number;
  failed_count: number;
  skipped_count: number;
  replica_count: number | null;
  schedule_id: number | null;
  sequence_id: number | null;
  step_details: StepDetail[] | null;
  initiated_by: string;
  initiated_by_email: string | null;
  started_at: string;
  completed_at: string | null;
  duration_seconds: number | null;
  error_message: string | null;
}

export interface EnvironmentStatus {
  cluster_id: string;
  namespace: string;
  total_deployments: number;
  running: number;
  stopped: number;
  scaling: number;
  failed: number;
  deployments: Record<string, unknown>[];
}

// ── React Query Hooks ─────────────────────────────────────────────────

export function useEnvironmentStatus(cluster_id: string, namespace: string) {
  return useQuery({
    queryKey: ["environment-status", cluster_id, namespace],
    queryFn: async () => {
      const response = await apiClient.get<EnvironmentStatus>("/environment/status", {
        params: { cluster_id, namespace },
      });
      return response.data;
    },
    enabled: !!cluster_id && !!namespace,
    refetchInterval: 30_000,
  });
}

export function useScaleEnvironment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: EnvironmentScaleRequest) => {
      const response = await apiClient.post<EnvironmentScaleResult>("/environment/scale", payload);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["environment-status"] });
      queryClient.invalidateQueries({ queryKey: ["environment-history"] });
      // Key must match useCachedDeployments in aksApi.ts — "deployments-cached"
      // matched nothing, so the deployment grid kept serving stale replica counts.
      queryClient.invalidateQueries({ queryKey: ["aks-deployments-cached"] });
    },
  });
}

// ── Schedules ─────────────────────────────────────────────────────────

export function useEnvironmentSchedules(cluster_id?: string, namespace?: string) {
  return useQuery({
    queryKey: ["environment-schedules", cluster_id, namespace],
    queryFn: async () => {
      const response = await apiClient.get<EnvironmentSchedule[]>("/environment/schedule", {
        params: { cluster_id, namespace },
      });
      return response.data;
    },
  });
}

export function useCreateSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: ScheduleCreateRequest) => {
      const response = await apiClient.post<EnvironmentSchedule>("/environment/schedule", payload);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["environment-schedules"] });
    },
  });
}

export function useUpdateSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...data }: ScheduleUpdateRequest & { id: number }) => {
      const response = await apiClient.put<EnvironmentSchedule>(`/environment/schedule/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["environment-schedules"] });
    },
  });
}

export function useDeleteSchedule() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/environment/schedule/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["environment-schedules"] });
    },
  });
}

export function useRunScheduleNow() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      const response = await apiClient.post<EnvironmentScaleResult>(`/environment/schedule/${id}/run`);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["environment-schedules"] });
      queryClient.invalidateQueries({ queryKey: ["environment-history"] });
      queryClient.invalidateQueries({ queryKey: ["environment-status"] });
      queryClient.invalidateQueries({ queryKey: ["aks-deployments-cached"] });
    },
  });
}

// ── Sequences ─────────────────────────────────────────────────────────

export function useEnvironmentSequences(cluster_id?: string, namespace?: string) {
  return useQuery({
    queryKey: ["environment-sequences", cluster_id, namespace],
    queryFn: async () => {
      const response = await apiClient.get<EnvironmentSequence[]>("/environment/sequence", {
        params: { cluster_id, namespace },
      });
      return response.data;
    },
  });
}

export function useCreateSequence() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: SequenceCreateRequest) => {
      const response = await apiClient.post<EnvironmentSequence>("/environment/sequence", payload);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["environment-sequences"] });
    },
  });
}

export function useUpdateSequence() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...data }: SequenceUpdateRequest & { id: number }) => {
      const response = await apiClient.put<EnvironmentSequence>(`/environment/sequence/${id}`, data);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["environment-sequences"] });
    },
  });
}

export function useDeleteSequence() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/environment/sequence/${id}`);
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["environment-sequences"] });
    },
  });
}

// ── Sequence Execution ────────────────────────────────────────────────

export function useStartSequence() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: SequenceExecuteRequest) => {
      const response = await apiClient.post<EnvironmentScaleResult>("/environment/start-sequence", payload);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["environment-status"] });
      queryClient.invalidateQueries({ queryKey: ["environment-history"] });
      queryClient.invalidateQueries({ queryKey: ["aks-deployments-cached"] });
    },
  });
}

export function useStopSequence() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (payload: SequenceExecuteRequest) => {
      const response = await apiClient.post<EnvironmentScaleResult>("/environment/stop-sequence", payload);
      return response.data;
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["environment-status"] });
      queryClient.invalidateQueries({ queryKey: ["environment-history"] });
      queryClient.invalidateQueries({ queryKey: ["aks-deployments-cached"] });
    },
  });
}

// ── Execution History ─────────────────────────────────────────────────

export function useExecutionHistory(cluster_id?: string, namespace?: string, limit?: number) {
  return useQuery({
    queryKey: ["environment-history", cluster_id, namespace, limit],
    queryFn: async () => {
      const response = await apiClient.get<ExecutionHistory[]>("/environment/history", {
        params: { cluster_id, namespace, limit },
      });
      return response.data;
    },
    refetchInterval: (query) => {
      const data = query.state.data;
      if (data && data.some((h) => h.status === "running")) return 5_000;
      return 30_000;
    },
  });
}

/** One execution, polled every 2s while it runs (live sequence progress). */
export function useExecution(executionId: number | null) {
  return useQuery({
    queryKey: ["environment-execution", executionId],
    queryFn: async () => {
      const response = await apiClient.get<ExecutionHistory>(`/environment/history/${executionId}`);
      return response.data;
    },
    enabled: executionId != null,
    refetchInterval: (query) => (query.state.data?.status === "running" || !query.state.data ? 2_000 : false),
  });
}

export interface AuditLogEntry {
  id: number;
  timestamp: string | null;
  user_id: string;
  user_email: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  status: string;
  details: Record<string, unknown> | null;
}

export function useEnvironmentAuditLogs(limit?: number) {
  return useQuery({
    queryKey: ["environment-audit-logs", limit],
    queryFn: async () => {
      const response = await apiClient.get<AuditLogEntry[]>("/environment/audit-logs", {
        params: { limit },
      });
      return response.data;
    },
    refetchInterval: 30_000,
  });
}
