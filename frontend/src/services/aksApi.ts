/**
 * AKS Operations API client and React Query hooks.
 * 
 * Provides:
 * - Cluster inventory and health
 * - Deployment management
 * - Pod observability
 * - CronJob management
 */

import { useEffect, useRef, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import apiClient from "./apiClient";

// ── Types ─────────────────────────────────────────────────────────────

export interface AKSCluster {
  id: string;
  name: string;
  subscription_id: string;
  subscription_name: string;
  resource_group: string;
  location: string;
  kubernetes_version: string;
  provisioning_state: string;
  power_state: string;
  node_count: number;
  environment?: string;
  tags?: Record<string, string>;
  created_at?: string;
}

export interface ClusterDetails extends AKSCluster {
  node_pools: NodePool[];
  network_profile: {
    network_plugin: string;
    service_cidr: string;
    pod_cidr: string;
  };
  identity: {
    type: string;
    principal_id: string;
  };
  sku: {
    name: string;
    tier: string;
  };
  fqdn: string;
}

export interface NodePool {
  name: string;
  vm_size: string;
  count: number;
  min_count?: number;
  max_count?: number;
  auto_scaling_enabled: boolean;
  mode: string;
  os_type: string;
  kubernetes_version: string;
  power_state: string;
}

export interface Deployment {
  name: string;
  namespace: string;
  replicas: number;
  ready_replicas: number;
  available_replicas: number;
  strategy: string;
  created_at: string;
  images: string[];
  labels: Record<string, string>;
  cpu_request?: string;
  cpu_limit?: string;
  memory_request?: string;
  memory_limit?: string;
}

export interface DeploymentDetail {
  name: string;
  namespace: string;
  yaml: string;
}

export interface PodMetrics {
  namespace: string;
  pod_name: string;
  containers: ContainerMetrics[];
  total_cpu_millicores: number;
  total_memory_mb: number;
  phase?: string;
  node?: string;
  qos_class?: string;
  pod_ip?: string;
  host_ip?: string;
  service_account?: string;
  restart_policy?: string;
  started_at?: string;
  labels?: Record<string, string>;
  conditions?: Array<{ type: string; status: string }>;
  total_cpu_request?: number;
  total_cpu_limit?: number;
  total_memory_request_mb?: number;
  total_memory_limit_mb?: number;
  total_restarts?: number;
}

export interface ContainerMetrics {
  name: string;
  cpu_millicores: number;
  memory_mb: number;
  state?: string;
  cpu_request?: string;
  cpu_limit?: string;
  memory_request?: string;
  memory_limit?: string;
  cpu_request_m?: number;
  cpu_limit_m?: number;
  memory_request_mb?: number;
  memory_limit_mb?: number;
}

export interface PodUtilization {
  snapshot_date: string;
  namespace: string;
  pod_name: string;
  avg_cpu_percent: number;
  avg_memory_percent: number;
  max_cpu_percent: number;
  max_memory_percent: number;
}

export interface UnderutilizedWorkload {
  namespace: string;
  owner_kind: string;
  owner_name: string;
  avg_cpu_percent: number;
  avg_memory_percent: number;
  recommendation: string;
  potential_savings: string;
}

export interface CronJob {
  name: string;
  namespace: string;
  schedule: string;
  suspended: boolean;
  last_schedule_time: string;
  last_successful_time?: string;
  active_count: number;
  created_at: string;
  image?: string;
  concurrency_policy?: string;
}

interface CronJobsResponse {
  cronjobs: CronJob[];
  count: number;
}

interface CachedCronJobsResponse extends CronJobsResponse {
  source: string;
  last_sync: string | null;
}

export interface CronJobDetail extends CronJob {
  command?: string[];
  args?: string[];
  labels: Record<string, string>;
  successful_jobs_history_limit?: number;
  failed_jobs_history_limit?: number;
  resources: {
    requests: Record<string, string>;
    limits: Record<string, string>;
  };
  configmap_refs?: Array<{
    volume_name: string;
    configmap_name: string;
    optional: boolean;
    items: Array<{ key: string; path: string }>;
  }>;
  volume_mounts?: Array<{
    name: string;
    mount_path: string;
    sub_path: string;
    read_only: string;
  }>;
  env_configmap_refs?: Array<{
    name: string;
    optional: boolean;
    prefix: string;
  }>;
}

export interface ConfigMap {
  name: string;
  namespace: string;
  data_keys: string[];
  created_at: string;
  labels: Record<string, string>;
}

export interface ConfigMapDetail {
  name: string;
  namespace: string;
  data: Record<string, string>;
  binary_data_keys: string[];
  labels: Record<string, string>;
  annotations: Record<string, string>;
  created_at: string;
  detail_source?: "live" | "unavailable";
  data_unavailable_reason?: string;
}

export interface ScaleHistory {
  id: number;
  timestamp: string;
  cluster_name: string;
  namespace: string;
  deployment_name: string;
  action?: string;
  previous_replicas: number;
  new_replicas: number;
  user_email: string;
}

export interface NodeDetail {
  name: string;
  pod_count: number;
  allocatable_cpu: string;
  allocatable_memory: string;
  allocatable_pods: string;
  labels: Record<string, string>;
}

export interface NodePoolDetails {
  name: string;
  vm_size: string;
  count: number;
  min_count: number | null;
  max_count: number | null;
  enable_auto_scaling: boolean;
  mode: string;
  os_type: string;
  os_disk_size_gb: number;
  kubernetes_version: string;
  provisioning_state: string;
  power_state: string;
  max_pods: number;
  node_labels: Record<string, string>;
  node_taints: string[];
  availability_zones: string[];
  node_image_version?: string;
  total_pods?: number;
  nodes?: NodeDetail[];
}

export interface ScaleNodePoolResult {
  success: boolean;
  cluster_id: string;
  nodepool_name: string;
  previous_count: number;
  new_count: number;
  error?: string;
}

export interface UpdateAutoscalingResult {
  success: boolean;
  cluster_id: string;
  nodepool_name: string;
  enable_auto_scaling: boolean;
  min_count: number | null;
  max_count: number | null;
  error?: string;
}

export interface ClusterActionResult {
  success: boolean;
  cluster_id: string;
  action: string;
  message: string;
  error?: string;
}

// ── API Functions ─────────────────────────────────────────────────────

const API_PREFIX = "/aks";

/** If the previous fetch is still in-flight, wait longer before retrying; otherwise use the normal interval. */
const safeInterval = (ms: number) => (query: { state: { fetchStatus: string } }) =>
  query.state.fetchStatus === "fetching" ? ms * 2 : ms;

// Clusters
export async function fetchClusters(
  subscriptionIds?: string[],
  environment?: string,
  refresh?: boolean
): Promise<{ clusters: AKSCluster[]; count: number }> {
  const params = new URLSearchParams();
  if (subscriptionIds) {
    subscriptionIds.forEach((id) => params.append("subscription_ids", id));
  }
  if (environment) {
    params.set("environment", environment);
  }
  if (refresh) {
    params.set("refresh", "true");
  }
  const { data } = await apiClient.get(`${API_PREFIX}/clusters`, { params });
  return data;
}

export async function fetchClusterDetails(clusterId: string): Promise<ClusterDetails> {
  const { data } = await apiClient.get(`${API_PREFIX}/clusters/${encodeURIComponent(clusterId)}`);
  return data;
}

export async function snapshotClusters(subscriptionIds?: string[]): Promise<{ success: boolean; clusters_snapshotted: number }> {
  const { data } = await apiClient.post(`${API_PREFIX}/clusters/snapshot`, { subscription_ids: subscriptionIds });
  return data;
}

// DB-cached clusters (fast load)
export async function fetchCachedClusters(
  environment?: string
): Promise<{ source: string; last_sync: string | null; clusters: AKSCluster[]; count: number }> {
  const params = new URLSearchParams();
  if (environment) {
    params.set("environment", environment);
  }
  const { data } = await apiClient.get(`${API_PREFIX}/clusters/cached`, { params, timeout: 8000 });
  return data;
}

// Sync clusters from Azure to DB
export async function syncClustersToDb(): Promise<{
  synced_count: number;
  resource_type: string;
  last_sync: string;
  resources: AKSCluster[];
  db_saved: boolean;
}> {
  const { data } = await apiClient.post(`${API_PREFIX}/clusters/sync`, null, { timeout: 15000 });
  return data;
}

// Deployments
export async function fetchDeployments(
  clusterId: string,
  namespace?: string,
  refresh?: boolean
): Promise<{ deployments: Deployment[]; count: number }> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  if (namespace) {
    params.set("namespace", namespace);
  }
  if (refresh) {
    params.set("refresh", "true");
  }
  const { data } = await apiClient.get(`${API_PREFIX}/deployments`, { params });
  return data;
}

// DB-cached Deployments (fast load)
export async function fetchCachedDeployments(
  clusterId: string,
  namespace?: string
): Promise<{ source: string; last_sync: string | null; deployments: Deployment[]; count: number }> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  if (namespace) {
    params.set("namespace", namespace);
  }
  const { data } = await apiClient.get(`${API_PREFIX}/deployments/cached`, { params, timeout: 8000 });
  return data;
}

// Lightweight status-only poll (name + replicas) for smooth real-time updates
export interface DeploymentStatus {
  name: string;
  namespace: string;
  replicas: number;
  ready_replicas: number;
}

export async function fetchDeploymentStatuses(
  clusterId: string,
  namespace?: string,
  live = false
): Promise<{ statuses: DeploymentStatus[]; count: number }> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  if (namespace) {
    params.set("namespace", namespace);
  }
  if (live) {
    params.set("live", "true");
  }
  const { data } = await apiClient.get(`${API_PREFIX}/deployments/status`, { params, timeout: 8000 });
  return data;
}

// Sync Deployments from Kubernetes to DB
export async function syncDeploymentsToDb(
  clusterId: string,
  namespace?: string
): Promise<{
  synced_count: number;
  resource_type: string;
  cluster_id: string;
  last_sync: string;
  resources: Deployment[];
  db_saved: boolean;
}> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  if (namespace) {
    params.set("namespace", namespace);
  }
  const { data } = await apiClient.post(`${API_PREFIX}/deployments/sync`, null, { params, timeout: 15000 });
  return data;
}

export async function scaleDeployment(
  clusterId: string,
  namespace: string,
  deploymentName: string,
  replicas: number
): Promise<{ success: boolean; deployment: string; replicas: number }> {
  const { data } = await apiClient.post(`${API_PREFIX}/deployments/scale`, {
    cluster_id: clusterId,
    namespace,
    deployment_name: deploymentName,
    replicas,
  });
  return data;
}

export async function restartDeployment(
  clusterId: string,
  namespace: string,
  deploymentName: string
): Promise<{ success: boolean; deployment: string }> {
  const { data } = await apiClient.post(`${API_PREFIX}/deployments/restart`, {
    cluster_id: clusterId,
    namespace,
    deployment_name: deploymentName,
  });
  return data;
}

export async function createDeployment(payload: {
  cluster_id: string;
  namespace: string;
  name: string;
  image: string;
  replicas?: number;
  labels?: Record<string, string>;
  cpu_request?: string;
  cpu_limit?: string;
  memory_request?: string;
  memory_limit?: string;
  port?: number;
  env_vars?: Record<string, string>;
}): Promise<{ success: boolean; deployment: string; namespace: string; replicas: number }> {
  const { data } = await apiClient.post(`${API_PREFIX}/deployments/create`, payload);
  return data;
}

export async function updateDeployment(payload: {
  cluster_id: string;
  namespace: string;
  name: string;
  image?: string;
  replicas?: number;
  cpu_request?: string;
  cpu_limit?: string;
  memory_request?: string;
  memory_limit?: string;
  env_vars?: Record<string, string>;
}): Promise<{ success: boolean; deployment: string; namespace: string }> {
  const { data } = await apiClient.put(`${API_PREFIX}/deployments/update`, payload);
  return data;
}

export async function deleteDeployment(
  clusterId: string,
  namespace: string,
  name: string
): Promise<{ success: boolean; deployment: string; namespace: string }> {
  const params = new URLSearchParams({ cluster_id: clusterId, namespace, name });
  const { data } = await apiClient.delete(`${API_PREFIX}/deployments/delete`, { params });
  return data;
}

// Pod Metrics
export async function fetchPodMetrics(
  clusterId: string,
  namespace?: string,
  refresh?: boolean
): Promise<{ pods: PodMetrics[]; count: number }> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  if (namespace) {
    params.set("namespace", namespace);
  }
  if (refresh) {
    params.set("refresh", "true");
  }
  const { data } = await apiClient.get(`${API_PREFIX}/pods/metrics`, { params, timeout: 60000 });
  return data;
}

// ── Jobs ──────────────────────────────────────────────────────────────

export type JobStatus = "Running" | "Completed" | "Failed" | "Suspended" | "Unknown";

export interface K8sJob {
  name: string;
  namespace: string;
  uid: string;
  status: JobStatus;
  completions: number | null;
  succeeded: number;
  failed: number;
  active: number;
  parallelism: number | null;
  backoff_limit: number | null;
  completion_mode: string | null;
  ttl_seconds_after_finished: number | null;
  suspended: boolean;
  start_time: string | null;
  completion_time: string | null;
  created_at: string | null;
  /** Owning CronJob name, when the Job came from one. */
  created_by: string | null;
  trigger: "manual" | "schedule" | null;
  labels: Record<string, string>;
  annotations: Record<string, string>;
  image: string | null;
}

export interface JobPod {
  pod_name: string;
  namespace: string;
  phase: string | null;
  node: string | null;
  pod_ip: string | null;
  started_at: string | null;
  restarts: number;
  containers: string[];
}

export interface JobCondition {
  type: string;
  status: string;
  reason: string | null;
  message: string | null;
  last_transition_time: string | null;
}

export interface JobDetail extends K8sJob {
  conditions: JobCondition[];
  pods: JobPod[];
}

export async function fetchJobs(
  clusterId: string,
  namespace?: string,
  refresh?: boolean
): Promise<{ jobs: K8sJob[]; count: number }> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  if (namespace) params.set("namespace", namespace);
  if (refresh) params.set("refresh", "true");
  const { data } = await apiClient.get(`${API_PREFIX}/jobs`, { params, timeout: 60000 });
  return data;
}

export async function fetchJobDetail(
  clusterId: string,
  namespace: string,
  name: string
): Promise<JobDetail> {
  const params = new URLSearchParams({ cluster_id: clusterId, namespace, name });
  const { data } = await apiClient.get(`${API_PREFIX}/jobs/detail`, { params });
  return data;
}

export async function fetchJobPods(
  clusterId: string,
  namespace: string,
  jobName: string
): Promise<{ pods: JobPod[]; count: number }> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  const { data } = await apiClient.get(
    `${API_PREFIX}/jobs/${encodeURIComponent(namespace)}/${encodeURIComponent(jobName)}/pods`,
    { params }
  );
  return data;
}

export async function deleteJob(
  clusterId: string,
  namespace: string,
  jobName: string,
  propagationPolicy: "Background" | "Orphan" = "Background"
): Promise<{
  success: boolean;
  job_name: string;
  namespace: string;
  previous_status: string;
  propagation_policy: string;
}> {
  const params = new URLSearchParams({
    cluster_id: clusterId,
    propagation_policy: propagationPolicy,
  });
  const { data } = await apiClient.delete(
    `${API_PREFIX}/jobs/${encodeURIComponent(namespace)}/${encodeURIComponent(jobName)}`,
    { params }
  );
  return data;
}

export interface DeletePodResult {
  success: boolean;
  pod_name: string;
  namespace: string;
  phase: string | null;
  owner: string | null;
  /** True when the pod is controller-owned and Kubernetes will replace it. */
  will_be_recreated: boolean;
}

export async function deletePod(
  clusterId: string,
  namespace: string,
  podName: string
): Promise<DeletePodResult> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  const { data } = await apiClient.delete(
    `${API_PREFIX}/pods/${encodeURIComponent(namespace)}/${encodeURIComponent(podName)}`,
    { params }
  );
  return data;
}

export async function fetchPodUtilizationHistory(
  clusterId: string,
  namespace?: string,
  days: number = 7
): Promise<{ history: PodUtilization[]; count: number }> {
  const params = new URLSearchParams({ cluster_id: clusterId, days: days.toString() });
  if (namespace) {
    params.set("namespace", namespace);
  }
  const { data } = await apiClient.get(`${API_PREFIX}/pods/utilization/history`, { params });
  return data;
}

export async function fetchUnderutilizedWorkloads(
  clusterId: string,
  namespace?: string,
  cpuThreshold: number = 20,
  memoryThreshold: number = 30
): Promise<{ underutilized_workloads: UnderutilizedWorkload[]; count: number }> {
  const params = new URLSearchParams({
    cluster_id: clusterId,
    cpu_threshold: cpuThreshold.toString(),
    memory_threshold: memoryThreshold.toString(),
  });
  if (namespace) {
    params.set("namespace", namespace);
  }
  const { data } = await apiClient.get(`${API_PREFIX}/pods/underutilized`, { params });
  return data;
}

// Pod Logs & Exec
export interface PodLogResult {
  pod_name: string;
  namespace: string;
  container: string | null;
  logs: string;
  line_count: number;
  tail_lines: number;
}

export interface PodLogSearchResult {
  pod_name: string;
  namespace: string;
  pattern: string;
  total_log_lines: number;
  match_count: number;
  severity_counts: { error: number; warning: number; info: number };
  matches: Array<{ line_number: number; text: string; severity: string }>;
}

export interface PodExecResult {
  pod_name: string;
  namespace: string;
  command: string;
  output: string;
  success: boolean;
}

export interface PodContainer {
  name: string;
  image: string;
  state: string;
  ready: boolean;
  restart_count: number;
  is_init?: boolean;
}

export async function fetchPodLogs(
  clusterId: string,
  namespace: string,
  podName: string,
  container?: string,
  tailLines: number = 500,
  sinceSeconds?: number,
): Promise<PodLogResult> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  if (container) params.set("container", container);
  params.set("tail_lines", tailLines.toString());
  if (sinceSeconds) params.set("since_seconds", sinceSeconds.toString());
  const { data } = await apiClient.get(`${API_PREFIX}/pods/${namespace}/${podName}/logs`, { params });
  return data;
}

export async function searchPodLogs(
  clusterId: string,
  namespace: string,
  podName: string,
  pattern?: string,
  container?: string,
  tailLines: number = 2000,
): Promise<PodLogSearchResult> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  if (pattern) params.set("pattern", pattern);
  if (container) params.set("container", container);
  params.set("tail_lines", tailLines.toString());
  const { data } = await apiClient.get(`${API_PREFIX}/pods/${namespace}/${podName}/logs/search`, { params });
  return data;
}

export async function execPodCommand(
  clusterId: string,
  namespace: string,
  podName: string,
  command: string,
  container?: string,
): Promise<PodExecResult> {
  const body: Record<string, string> = { cluster_id: clusterId, command };
  if (container) body.container = container;
  const { data } = await apiClient.post(`${API_PREFIX}/pods/${namespace}/${podName}/exec`, body);
  return data;
}

export async function fetchPodContainers(
  clusterId: string,
  namespace: string,
  podName: string,
): Promise<{ containers: PodContainer[]; count: number }> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  const { data } = await apiClient.get(`${API_PREFIX}/pods/${namespace}/${podName}/containers`, { params });
  return data;
}

// CronJobs
export async function fetchCronJobs(
  clusterId: string,
  namespace?: string,
  refresh?: boolean
): Promise<CronJobsResponse> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  if (namespace) {
    params.set("namespace", namespace);
  }
  if (refresh) {
    params.set("refresh", "true");
  }
  const { data } = await apiClient.get(`${API_PREFIX}/cronjobs`, { params });
  return data;
}

// DB-cached CronJobs (fast load)
export async function fetchCachedCronJobs(
  clusterId: string,
  namespace?: string
): Promise<CachedCronJobsResponse> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  if (namespace) {
    params.set("namespace", namespace);
  }
  const { data } = await apiClient.get(`${API_PREFIX}/cronjobs/cached`, { params, timeout: 8000 });
  return data;
}

export async function fetchDeploymentDetail(
  clusterId: string,
  namespace: string,
  name: string,
): Promise<DeploymentDetail> {
  const params = new URLSearchParams({ cluster_id: clusterId, namespace, name });
  const { data } = await apiClient.get(`${API_PREFIX}/deployments/details`, { params });
  return data;
}

// Sync CronJobs from Kubernetes to DB
export async function syncCronJobsToDb(
  clusterId: string,
  namespace?: string
): Promise<{
  synced_count: number;
  resource_type: string;
  cluster_id: string;
  last_sync: string;
  resources: CronJob[];
  db_saved: boolean;
}> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  if (namespace) {
    params.set("namespace", namespace);
  }
  const { data } = await apiClient.post(`${API_PREFIX}/cronjobs/sync`, null, { params, timeout: 15000 });
  return data;
}

export async function suspendCronJob(
  clusterId: string,
  namespace: string,
  cronjobName: string,
  suspend: boolean
): Promise<{ success: boolean; cronjob: string; suspended: boolean }> {
  const { data } = await apiClient.post(`${API_PREFIX}/cronjobs/suspend`, {
    cluster_id: clusterId,
    namespace,
    cronjob_name: cronjobName,
    suspend,
  });
  return data;
}

export async function createCronJob(payload: {
  cluster_id: string;
  namespace: string;
  name: string;
  schedule: string;
  image: string;
  command?: string[];
  args?: string[];
  restart_policy?: string;
  labels?: Record<string, string>;
  cpu_request?: string;
  cpu_limit?: string;
  memory_request?: string;
  memory_limit?: string;
  concurrency_policy?: string;
  successful_jobs_history_limit?: number;
  failed_jobs_history_limit?: number;
  backoff_limit?: number;
  active_deadline_seconds?: number;
  ttl_seconds_after_finished?: number;
  service_account_name?: string;
}): Promise<{ success: boolean; cronjob: string }> {
  const { data } = await apiClient.post(`${API_PREFIX}/cronjobs`, payload);
  return data;
}

export async function updateCronJob(payload: {
  cluster_id: string;
  namespace: string;
  name: string;
  schedule?: string;
  image?: string;
  command?: string[];
  args?: string[];
  suspended?: boolean;
  concurrency_policy?: string;
  successful_jobs_history_limit?: number;
  failed_jobs_history_limit?: number;
  cpu_request?: string;
  cpu_limit?: string;
  memory_request?: string;
  memory_limit?: string;
}): Promise<{ success: boolean; cronjob: string }> {
  const { data } = await apiClient.put(`${API_PREFIX}/cronjobs/update`, payload);
  return data;
}

export async function deleteCronJob(
  clusterId: string,
  namespace: string,
  name: string
): Promise<{ success: boolean; cronjob: string }> {
  const params = new URLSearchParams({ cluster_id: clusterId, namespace, name });
  const { data } = await apiClient.delete(`${API_PREFIX}/cronjobs/delete`, { params });
  return data;
}

export async function fetchCronJobDetail(
  clusterId: string,
  namespace: string,
  name: string,
  refresh?: boolean
): Promise<CronJobDetail> {
  const params = new URLSearchParams({ cluster_id: clusterId, namespace, name });
  if (refresh) {
    params.set("refresh", "true");
  }
  const { data } = await apiClient.get(`${API_PREFIX}/cronjobs/details`, { params });
  return data;
}

// Trigger CronJob (create Job from CronJob template)
export async function triggerCronJob(
  clusterId: string,
  namespace: string,
  cronjobName: string
): Promise<{
  success: boolean;
  cronjob: string;
  job_name: string;
  namespace: string;
  /** True when a repeated request reused an existing Job instead of creating one. */
  deduplicated?: boolean;
}> {
  const { data } = await apiClient.post(`${API_PREFIX}/cronjobs/trigger`, {
    cluster_id: clusterId,
    namespace,
    cronjob_name: cronjobName,
  });
  return data;
}

// ConfigMaps
export async function fetchConfigMaps(
  clusterId: string,
  namespace: string
): Promise<{ configmaps: ConfigMap[]; count: number }> {
  const params = new URLSearchParams({ cluster_id: clusterId, namespace });
  const { data } = await apiClient.get(`${API_PREFIX}/configmaps`, { params });
  return data;
}

export async function fetchConfigMapDetail(
  clusterId: string,
  namespace: string,
  name: string
): Promise<ConfigMapDetail> {
  const params = new URLSearchParams({ cluster_id: clusterId, namespace, name });
  const { data } = await apiClient.get(`${API_PREFIX}/configmaps/detail`, { params });
  return data;
}

// Scale History
export async function fetchScaleHistory(
  clusterId?: string,
  namespace?: string,
  deploymentName?: string,
  days: number = 30,
  limit: number = 100
): Promise<{ history: ScaleHistory[]; count: number }> {
  const params = new URLSearchParams({ days: days.toString(), limit: limit.toString() });
  if (clusterId) params.set("cluster_id", clusterId);
  if (namespace) params.set("namespace", namespace);
  if (deploymentName) params.set("deployment_name", deploymentName);
  const { data } = await apiClient.get(`${API_PREFIX}/scale-history`, { params });
  return data;
}

// Node Pool Operations
export async function fetchNodePools(
  clusterId: string,
  refresh?: boolean
): Promise<{ node_pools: NodePoolDetails[]; count: number }> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  if (refresh) {
    params.set("refresh", "true");
  }
  const { data } = await apiClient.get(`${API_PREFIX}/nodepools`, { params });
  return data;
}

// DB-cached Node Pools (fast load)
export async function fetchCachedNodePools(
  clusterId: string
): Promise<{ source: string; last_sync: string | null; node_pools: NodePoolDetails[]; count: number }> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  const { data } = await apiClient.get(`${API_PREFIX}/nodepools/cached`, { params, timeout: 8000 });
  return data;
}

// Sync Node Pools from Azure/K8s to DB
export async function syncNodePoolsToDb(
  clusterId: string
): Promise<{
  synced_count: number;
  resource_type: string;
  cluster_id: string;
  last_sync: string;
  resources: NodePoolDetails[];
  db_saved: boolean;
}> {
  const params = new URLSearchParams({ cluster_id: clusterId });
  const { data } = await apiClient.post(`${API_PREFIX}/nodepools/sync`, null, { params, timeout: 15000 });
  return data;
}

export async function scaleNodePool(
  clusterId: string,
  nodepoolName: string,
  nodeCount: number
): Promise<ScaleNodePoolResult> {
  const { data } = await apiClient.post(`${API_PREFIX}/nodepools/scale`, {
    cluster_id: clusterId,
    nodepool_name: nodepoolName,
    node_count: nodeCount,
  });
  return data;
}

export async function updateNodePoolAutoscaling(
  clusterId: string,
  nodepoolName: string,
  enableAutoScaling: boolean,
  minCount?: number,
  maxCount?: number
): Promise<UpdateAutoscalingResult> {
  const { data } = await apiClient.post(`${API_PREFIX}/nodepools/autoscaling`, {
    cluster_id: clusterId,
    nodepool_name: nodepoolName,
    enable_auto_scaling: enableAutoScaling,
    min_count: minCount,
    max_count: maxCount,
  });
  return data;
}

// Cluster Start / Stop
export async function startCluster(clusterId: string): Promise<ClusterActionResult> {
  const { data } = await apiClient.post(`${API_PREFIX}/clusters/start`, {
    cluster_id: clusterId,
  });
  return data;
}

export async function stopCluster(clusterId: string): Promise<ClusterActionResult> {
  const { data } = await apiClient.post(`${API_PREFIX}/clusters/stop`, {
    cluster_id: clusterId,
  });
  return data;
}

// ── Background AKS Sync Jobs ──────────────────────────────────────────

export type AksSyncResourceType =
  | "clusters"
  | "nodepools"
  | "deployments"
  | "pods"
  | "cronjobs"
  | "services"
  | "secrets"
  | "configmaps"
  | "ingress";

export interface SyncJobDetail {
  id: number;
  job_type: string;
  status: "queued" | "running" | "completed" | "failed" | string;
  idempotency_key: string | null;
  triggered_by: string | null;
  attempts: number;
  last_error: string | null;
  result: Record<string, unknown> | null;
  enqueued_at: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface EnqueueSyncJobResponse {
  job_id: number;
  status: string;
  job_type: string;
  idempotency_key: string | null;
  reused: boolean;
}

export async function enqueueAksResourceSync(args: {
  resourceType: AksSyncResourceType;
  clusterId?: string;
  namespace?: string;
  force?: boolean;
}): Promise<EnqueueSyncJobResponse> {
  const scope = args.resourceType === "clusters" ? "all" : args.clusterId || "";
  const namespace = args.namespace || "all";
  const idempotencyKey = `aks:${scope}:${args.resourceType}:${namespace}`.slice(0, 120);
  const { data } = await apiClient.post(
    "/sync-jobs",
    {
      job_type: "aks_resource_sync",
      cluster_id: args.clusterId,
      resource_type: args.resourceType,
      namespace: args.namespace,
      force: args.force ?? false,
      idempotency_key: idempotencyKey,
    },
    { timeout: 8000 }
  );
  return data;
}

export async function fetchSyncJob(jobId: number): Promise<SyncJobDetail> {
  const { data } = await apiClient.get(`/sync-jobs/${jobId}`, { timeout: 8000 });
  return data;
}

const AKS_SYNC_THROTTLE_MS = 10_000; // 10s — sync from K8s for near-real-time
const aksSyncCompletedAt = new Map<string, number>();
const aksSyncAttemptedAt = new Map<string, number>();

function aksSyncKey(resourceType: AksSyncResourceType, clusterId?: string, namespace?: string): string {
  return `${resourceType}:${clusterId || "all"}:${namespace || "all"}`;
}

function invalidateAksResourceQueries(
  queryClient: ReturnType<typeof useQueryClient>,
  resourceType: AksSyncResourceType,
  clusterId?: string,
) {
  const keyMap: Record<AksSyncResourceType, string[]> = {
    clusters: ["aks-clusters-cached", "aks-clusters"],
    nodepools: ["aks-nodepools-cached", "aks-nodepools"],
    deployments: ["aks-deployments-cached", "aks-deployments"],
    pods: ["aks-pod-metrics"],
    cronjobs: ["aks-cronjobs-cached", "aks-cronjobs"],
    services: ["aks-services-cached"],
    secrets: ["aks-secrets-cached"],
    configmaps: ["aks-configmaps-cached"],
    ingress: ["aks-ingress-cached"],
  };
  keyMap[resourceType].forEach((key) => {
    if (resourceType === "clusters" || !clusterId) {
      queryClient.invalidateQueries({ queryKey: [key] });
    } else {
      queryClient.invalidateQueries({ queryKey: [key, clusterId] });
    }
  });
  if (resourceType !== "clusters" && clusterId) {
    queryClient.invalidateQueries({ queryKey: ["aks-namespaces", clusterId] });
  }
}

export function useAksBackgroundSync(args: {
  resourceType: AksSyncResourceType;
  clusterId?: string;
  namespace?: string;
  enabled?: boolean;
  auto?: boolean;
  throttleMs?: number;
}) {
  const {
    resourceType,
    clusterId,
    namespace,
    enabled = true,
    auto = true,
    throttleMs = AKS_SYNC_THROTTLE_MS,
  } = args;
  const queryClient = useQueryClient();
  const [jobId, setJobId] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastStatus, setLastStatus] = useState<string>("idle");
  const processedJobRef = useRef<number | null>(null);
  const jobIdRef = useRef<number | null>(null);
  const pendingRef = useRef(false);
  const syncKey = aksSyncKey(resourceType, clusterId, namespace);

  const enqueueMutation = useMutation({
    mutationFn: (force: boolean = false) =>
      enqueueAksResourceSync({ resourceType, clusterId, namespace, force }),
    onMutate: () => { pendingRef.current = true; },
    onSettled: () => { pendingRef.current = false; },
    onSuccess: (res) => {
      processedJobRef.current = null;
      setJobId(res.job_id);
      jobIdRef.current = res.job_id;
      setLastStatus(res.status || "queued");
      setError(null);
    },
    onError: (err: any) => {
      setLastStatus("failed");
      setError(err?.response?.data?.detail || err?.message || "Failed to enqueue refresh");
    },
  });

  const jobQuery = useQuery({
    queryKey: ["sync-job", jobId],
    queryFn: () => fetchSyncJob(jobId!),
    enabled: !!jobId && lastStatus !== "completed" && lastStatus !== "failed",
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "queued" || status === "running" ? 3000 : false;
    },
    retry: false,
    refetchOnWindowFocus: false,
  });

  const start = (force = false) => {
    if (!enabled) return;
    if (resourceType !== "clusters" && !clusterId) return;
    aksSyncAttemptedAt.set(syncKey, Date.now());
    enqueueMutation.mutate(force);
  };

  // Auto-trigger sync on an interval (checks throttle internally)
  useEffect(() => {
    if (!auto || !enabled) return;
    if (resourceType !== "clusters" && !clusterId) return;

    const trySync = () => {
      // Skip if a sync is already in-flight or a job is being tracked
      if (pendingRef.current || jobIdRef.current) return;
      const lastActivityAt = Math.max(
        aksSyncCompletedAt.get(syncKey) || 0,
        aksSyncAttemptedAt.get(syncKey) || 0
      );
      if (Date.now() - lastActivityAt < throttleMs) return;
      start(false);
    };

    // Fire immediately on mount/tab-switch
    trySync();

    // Then check more frequently than throttle so we pick up completions quickly
    const timer = setInterval(trySync, Math.min(throttleMs, 5_000));
    return () => clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, enabled, syncKey, throttleMs]);

  useEffect(() => {
    const job = jobQuery.data;
    if (!job) return;
    setLastStatus(job.status);
    if (job.status === "completed" && processedJobRef.current !== job.id) {
      processedJobRef.current = job.id;
      aksSyncCompletedAt.set(syncKey, Date.now());
      invalidateAksResourceQueries(queryClient, resourceType, clusterId);
      setError(null);
      setJobId(null);
      jobIdRef.current = null;
    }
    if (job.status === "failed") {
      setError(job.last_error || "Background refresh failed");
      setJobId(null);
      jobIdRef.current = null;
    }
  }, [clusterId, jobQuery.data, queryClient, resourceType, syncKey]);

  const isRunning =
    enqueueMutation.isPending ||
    (!!jobId && lastStatus !== "completed" && lastStatus !== "failed" && lastStatus !== "idle");

  return {
    start,
    job: jobQuery.data,
    jobId,
    status: lastStatus,
    error,
    isRunning,
    isRetrying: isRunning && (jobQuery.data?.attempts || 0) > 1,
  };
}

// ── React Query Hooks ─────────────────────────────────────────────────

export function useClusters(subscriptionIds?: string[], environment?: string) {
  return useQuery({
    queryKey: ["aks-clusters", subscriptionIds, environment],
    queryFn: () => fetchClusters(subscriptionIds, environment),
    staleTime: 5 * 60 * 1000, // 5 min — matches backend Redis TTL
    gcTime: 10 * 60 * 1000,   // keep in React Query cache 10 min
    retry: 2,
  });
}

export function useCachedClusters(environment?: string, autoRefresh = true) {
  return useQuery({
    queryKey: ["aks-clusters-cached", environment],
    queryFn: () => fetchCachedClusters(environment),
    placeholderData: {
      source: "db",
      last_sync: null,
      clusters: [],
      count: 0,
    },
    staleTime: autoRefresh ? 4_000 : 5 * 60 * 1000,
    gcTime: 60_000,
    refetchInterval: autoRefresh ? safeInterval(5_000) : false,
    retry: false,
    refetchOnWindowFocus: false,
  });
}

export function useSyncClusters() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: syncClustersToDb,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-clusters-cached"] });
      queryClient.invalidateQueries({ queryKey: ["aks-clusters"] });
    },
  });
}

export function useDeployments(clusterId: string, namespace?: string) {
  return useQuery({
    queryKey: ["aks-deployments", clusterId, namespace],
    queryFn: () => fetchDeployments(clusterId, namespace),
    enabled: !!clusterId,
    staleTime: 2 * 60 * 1000, // 2 min — matches backend Redis TTL
    gcTime: 5 * 60 * 1000,
    retry: 1,
  });
}

export function useCachedDeployments(clusterId: string, namespace?: string, enabled = true) {
  return useQuery({
    queryKey: ["aks-deployments-cached", clusterId, namespace],
    queryFn: () => fetchCachedDeployments(clusterId, namespace),
    enabled: !!clusterId && enabled,
    placeholderData: (prev) => prev ?? {
      source: "db",
      last_sync: null,
      deployments: [],
      count: 0,
    },
    staleTime: 4_000,
    gcTime: 60_000,
    refetchInterval: safeInterval(5_000), // full refetch every 5s for real-time grid
    retry: 1,
    refetchOnWindowFocus: false,
  });
}

/**
 * Lightweight status-only poll that runs every 5 seconds by default.
 * Merges status (replicas/ready_replicas) into cached deployment data
 * without triggering a full refetch — only the Status column re-renders.
 */
export function useDeploymentStatusPoll(clusterId: string, namespace?: string, enabled = true, intervalMs = 5_000, live = false) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: ["aks-deployment-status", clusterId, namespace, live],
    queryFn: async () => {
      const result = await fetchDeploymentStatuses(clusterId, namespace, live);
      // Merge status into cached deployments without full refetch
      queryClient.setQueryData<{
        source: string;
        last_sync: string | null;
        deployments: Deployment[];
        count: number;
      }>(["aks-deployments-cached", clusterId, namespace], (prev) => {
        if (!prev || !prev.deployments.length) return prev;
        const statusMap = new Map(
          result.statuses.map((s) => [`${s.namespace}/${s.name}`, s])
        );
        let changed = false;
        const updated = prev.deployments.map((d) => {
          const key = `${d.namespace}/${d.name}`;
          const st = statusMap.get(key);
          if (st && (st.replicas !== d.replicas || st.ready_replicas !== d.ready_replicas)) {
            changed = true;
            return { ...d, replicas: st.replicas, ready_replicas: st.ready_replicas };
          }
          return d;
        });
        return changed ? { ...prev, deployments: updated } : prev;
      });
      return result;
    },
    enabled: !!clusterId && enabled,
    refetchInterval: intervalMs > 0 ? safeInterval(intervalMs) : false,
    staleTime: Math.max(intervalMs - 5000, 3000),
    gcTime: 60_000,
    retry: 1,
    refetchOnWindowFocus: false,
  });
}

export function useSyncDeployments() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId, namespace }: { clusterId: string; namespace?: string }) =>
      syncDeploymentsToDb(clusterId, namespace),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-deployments-cached"] });
      queryClient.invalidateQueries({ queryKey: ["aks-deployments"] });
    },
  });
}

export function useScaleDeployment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      clusterId,
      namespace,
      deploymentName,
      replicas,
    }: {
      clusterId: string;
      namespace: string;
      deploymentName: string;
      replicas: number;
    }) => scaleDeployment(clusterId, namespace, deploymentName, replicas),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["aks-deployments", variables.clusterId],
      });
      queryClient.invalidateQueries({ queryKey: ["aks-deployments-cached"] });
      queryClient.invalidateQueries({ queryKey: ["aks-deployment-status"] });
      queryClient.invalidateQueries({ queryKey: ["aks-scale-history"] });
      queryClient.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useRestartDeployment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      clusterId,
      namespace,
      deploymentName,
    }: {
      clusterId: string;
      namespace: string;
      deploymentName: string;
    }) => restartDeployment(clusterId, namespace, deploymentName),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({
        queryKey: ["aks-deployments", variables.clusterId],
      });
      queryClient.invalidateQueries({ queryKey: ["aks-deployments-cached"] });
      queryClient.invalidateQueries({ queryKey: ["aks-deployment-status"] });
      queryClient.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useCreateDeployment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Parameters<typeof createDeployment>[0]) => createDeployment(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-deployments"] });
      queryClient.invalidateQueries({ queryKey: ["aks-deployments-cached"] });
      queryClient.invalidateQueries({ queryKey: ["aks-scale-history"] });
      queryClient.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useUpdateDeployment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Parameters<typeof updateDeployment>[0]) => updateDeployment(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-deployments"] });
      queryClient.invalidateQueries({ queryKey: ["aks-deployments-cached"] });
      queryClient.invalidateQueries({ queryKey: ["aks-scale-history"] });
      queryClient.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useDeleteDeployment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      clusterId,
      namespace,
      name,
    }: {
      clusterId: string;
      namespace: string;
      name: string;
    }) => deleteDeployment(clusterId, namespace, name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-deployments"] });
      queryClient.invalidateQueries({ queryKey: ["aks-deployments-cached"] });
      queryClient.invalidateQueries({ queryKey: ["aks-scale-history"] });
      queryClient.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function usePodMetrics(clusterId: string, namespace?: string, enabled = true) {
  return useQuery({
    queryKey: ["aks-pod-metrics", clusterId, namespace],
    queryFn: () => fetchPodMetrics(clusterId, namespace),
    enabled: !!clusterId && enabled,
    placeholderData: (prev) => prev ?? {
      pods: [],
      count: 0,
    },
    staleTime: 4_000,
    gcTime: 60_000,
    refetchInterval: safeInterval(5_000), // refetch every 5s for real-time pod metrics
    retry: 1,
    refetchOnWindowFocus: false,
  });
}

export function useJobs(clusterId: string, namespace?: string, enabled = true) {
  return useQuery({
    queryKey: ["aks-jobs", clusterId, namespace],
    queryFn: () => fetchJobs(clusterId, namespace),
    enabled: !!clusterId && enabled,
    // No placeholderData: an empty placeholder would make isLoading false for
    // the whole first fetch, so the grid would render "No Jobs found" instead
    // of a loading state, and would carry the previous namespace's rows across
    // a filter change.
    staleTime: 4_000,
    gcTime: 60_000,
    // Jobs are short-lived; poll so a running Job's counters advance and a
    // freshly triggered Job shows up without the user hitting Refresh.
    refetchInterval: safeInterval(10_000),
    retry: 1,
    refetchOnWindowFocus: false,
  });
}

export function useJobDetail(
  clusterId: string,
  namespace: string | undefined,
  name: string | undefined,
  enabled = true
) {
  return useQuery({
    queryKey: ["aks-job-detail", clusterId, namespace, name],
    queryFn: () => fetchJobDetail(clusterId, namespace!, name!),
    enabled: !!clusterId && !!namespace && !!name && enabled,
    staleTime: 4_000,
    refetchInterval: safeInterval(10_000),
    retry: 1,
    refetchOnWindowFocus: false,
  });
}

export function useDeleteJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      clusterId,
      namespace,
      jobName,
      propagationPolicy,
    }: {
      clusterId: string;
      namespace: string;
      jobName: string;
      propagationPolicy?: "Background" | "Orphan";
    }) => deleteJob(clusterId, namespace, jobName, propagationPolicy),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-jobs"] });
      queryClient.invalidateQueries({ queryKey: ["aks-job-detail"] });
      queryClient.invalidateQueries({ queryKey: ["aks-pod-metrics"] });
      queryClient.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useDeletePod() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      clusterId,
      namespace,
      podName,
    }: {
      clusterId: string;
      namespace: string;
      podName: string;
    }) => deletePod(clusterId, namespace, podName),
    onSuccess: () => {
      // Refresh the grid immediately so the user sees the pod terminating (or
      // its replacement appear) without reloading the browser.
      queryClient.invalidateQueries({ queryKey: ["aks-pod-metrics"] });
      queryClient.invalidateQueries({ queryKey: ["aks-pods-cached"] });
      queryClient.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function usePodUtilizationHistory(clusterId: string, namespace?: string, days: number = 7) {
  return useQuery({
    queryKey: ["aks-pod-utilization-history", clusterId, namespace, days],
    queryFn: () => fetchPodUtilizationHistory(clusterId, namespace, days),
    enabled: !!clusterId,
  });
}

export function useUnderutilizedWorkloads(
  clusterId: string,
  namespace?: string,
  cpuThreshold: number = 20,
  memoryThreshold: number = 30
) {
  return useQuery({
    queryKey: ["aks-underutilized", clusterId, namespace, cpuThreshold, memoryThreshold],
    queryFn: () => fetchUnderutilizedWorkloads(clusterId, namespace, cpuThreshold, memoryThreshold),
    enabled: !!clusterId,
  });
}

export function usePodLogs(
  clusterId: string,
  namespace: string,
  podName: string,
  container?: string,
  tailLines: number = 500,
  sinceSeconds?: number,
  enabled: boolean = false,
) {
  return useQuery({
    queryKey: ["aks-pod-logs", clusterId, namespace, podName, container, tailLines, sinceSeconds],
    queryFn: () => fetchPodLogs(clusterId, namespace, podName, container, tailLines, sinceSeconds),
    enabled: enabled && !!clusterId && !!podName,
    staleTime: 15 * 1000,
    gcTime: 60 * 1000,
    retry: 1,
  });
}

export function usePodLogSearch(
  clusterId: string,
  namespace: string,
  podName: string,
  pattern?: string,
  container?: string,
  enabled: boolean = false,
) {
  return useQuery({
    queryKey: ["aks-pod-log-search", clusterId, namespace, podName, pattern, container],
    queryFn: () => searchPodLogs(clusterId, namespace, podName, pattern, container),
    enabled: enabled && !!clusterId && !!podName,
    staleTime: 30 * 1000,
    gcTime: 60 * 1000,
    retry: 1,
  });
}

export function useExecPodCommand() {
  return useMutation({
    mutationFn: ({
      clusterId,
      namespace,
      podName,
      command,
      container,
    }: {
      clusterId: string;
      namespace: string;
      podName: string;
      command: string;
      container?: string;
    }) => execPodCommand(clusterId, namespace, podName, command, container),
  });
}

export function usePodContainers(clusterId: string, namespace: string, podName: string, enabled: boolean = false) {
  return useQuery({
    queryKey: ["aks-pod-containers", clusterId, namespace, podName],
    queryFn: () => fetchPodContainers(clusterId, namespace, podName),
    enabled: enabled && !!clusterId && !!podName,
    staleTime: 60 * 1000,
    gcTime: 3 * 60 * 1000,
  });
}

export function useCronJobs(clusterId: string, namespace?: string) {
  return useQuery({
    queryKey: ["aks-cronjobs", clusterId, namespace],
    queryFn: () => fetchCronJobs(clusterId, namespace),
    enabled: !!clusterId,
    staleTime: 2 * 60 * 1000, // 2 min — matches backend Redis TTL
    gcTime: 5 * 60 * 1000,
    retry: 1,
  });
}

export function useCachedCronJobs(clusterId: string, namespace?: string, enabled = true) {
  return useQuery({
    queryKey: ["aks-cronjobs-cached", clusterId, namespace],
    queryFn: () => fetchCachedCronJobs(clusterId, namespace),
    enabled: !!clusterId && enabled,
    placeholderData: (prev) => prev ?? {
      source: "db",
      last_sync: null,
      cronjobs: [],
      count: 0,
    },
    staleTime: 4_000,
    gcTime: 60_000,
    refetchInterval: safeInterval(5_000),
    retry: 1,
    refetchOnWindowFocus: false,
  });
}

export function useSyncCronJobs() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId, namespace }: { clusterId: string; namespace?: string }) =>
      syncCronJobsToDb(clusterId, namespace),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-cronjobs-cached"] });
      queryClient.invalidateQueries({ queryKey: ["aks-cronjobs"] });
    },
  });
}

export function useSuspendCronJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      clusterId,
      namespace,
      cronjobName,
      suspend,
    }: {
      clusterId: string;
      namespace: string;
      cronjobName: string;
      suspend: boolean;
    }) => suspendCronJob(clusterId, namespace, cronjobName, suspend),
    onSuccess: async (_, variables) => {
      const updateCronJobs = <T extends CronJobsResponse>(current: T | undefined): T | undefined => {
        if (!current) {
          return current;
        }

        const cronjobs = current.cronjobs.map((cronjob) =>
          cronjob.name === variables.cronjobName && cronjob.namespace === variables.namespace
            ? { ...cronjob, suspended: variables.suspend }
            : cronjob,
        );

        return {
          ...current,
          cronjobs,
          count: cronjobs.length,
        };
      };

      queryClient.setQueriesData<CachedCronJobsResponse>(
        { queryKey: ["aks-cronjobs-cached", variables.clusterId] },
        updateCronJobs,
      );
      queryClient.setQueriesData<CronJobsResponse>(
        { queryKey: ["aks-cronjobs", variables.clusterId] },
        updateCronJobs,
      );

      await queryClient.invalidateQueries({
        queryKey: ["aks-cronjobs-cached", variables.clusterId],
      });
      await queryClient.invalidateQueries({
        queryKey: ["aks-cronjobs", variables.clusterId],
      });
      queryClient.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useCreateCronJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Parameters<typeof createCronJob>[0]) => createCronJob(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-cronjobs"] });
      queryClient.invalidateQueries({ queryKey: ["aks-cronjobs-cached"] });
      queryClient.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useUpdateCronJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Parameters<typeof updateCronJob>[0]) => updateCronJob(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-cronjobs"] });
      queryClient.invalidateQueries({ queryKey: ["aks-cronjobs-cached"] });
      queryClient.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useDeleteCronJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      clusterId,
      namespace,
      name,
    }: {
      clusterId: string;
      namespace: string;
      name: string;
    }) => deleteCronJob(clusterId, namespace, name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-cronjobs"] });
      queryClient.invalidateQueries({ queryKey: ["aks-cronjobs-cached"] });
      queryClient.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useCronJobDetail(clusterId: string, namespace: string, name: string) {
  return useQuery({
    queryKey: ["aks-cronjob-detail", clusterId, namespace, name],
    queryFn: () => fetchCronJobDetail(clusterId, namespace, name),
    enabled: !!clusterId && !!namespace && !!name,
    staleTime: 2 * 60 * 1000, // 2 min — matches backend Redis TTL
    gcTime: 5 * 60 * 1000,
    retry: 1,
  });
}

export function useDeploymentDetail(clusterId: string, namespace: string, name: string) {
  return useQuery({
    queryKey: ["aks-deployment-detail", clusterId, namespace, name],
    queryFn: () => fetchDeploymentDetail(clusterId, namespace, name),
    enabled: !!clusterId && !!namespace && !!name,
    staleTime: 2 * 60 * 1000,
    gcTime: 5 * 60 * 1000,
    retry: 1,
  });
}

export function useTriggerCronJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      clusterId,
      namespace,
      cronjobName,
    }: {
      clusterId: string;
      namespace: string;
      cronjobName: string;
    }) => triggerCronJob(clusterId, namespace, cronjobName),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-cronjobs"] });
      queryClient.invalidateQueries({ queryKey: ["aks-cronjobs-cached"] });
      queryClient.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useConfigMaps(clusterId: string, namespace: string) {
  return useQuery({
    queryKey: ["aks-configmaps", clusterId, namespace],
    queryFn: () => fetchConfigMaps(clusterId, namespace),
    enabled: !!clusterId && !!namespace,
    staleTime: 2 * 60 * 1000,
    gcTime: 5 * 60 * 1000,
    retry: 1,
  });
}

export function useConfigMapDetail(clusterId: string, namespace: string, name: string) {
  return useQuery({
    queryKey: ["aks-configmap-detail", clusterId, namespace, name],
    queryFn: () => fetchConfigMapDetail(clusterId, namespace, name),
    enabled: !!clusterId && !!namespace && !!name,
    staleTime: 2 * 60 * 1000,
    gcTime: 5 * 60 * 1000,
    retry: 1,
  });
}

export function useScaleHistory(
  clusterId?: string,
  namespace?: string,
  deploymentName?: string,
  days: number = 30,
  enabled = true
) {
  return useQuery({
    queryKey: ["aks-scale-history", clusterId, namespace, deploymentName, days],
    queryFn: () => fetchScaleHistory(clusterId, namespace, deploymentName, days),
    enabled,
  });
}

// -- Node Pool Hooks --

export function useNodePools(clusterId: string) {
  return useQuery({
    queryKey: ["aks-nodepools", clusterId],
    queryFn: () => fetchNodePools(clusterId),
    enabled: !!clusterId,
    staleTime: 5 * 60 * 1000, // 5 min — matches backend Redis TTL
    gcTime: 10 * 60 * 1000,
    refetchInterval: 5 * 60 * 1000, // poll every 5 min (served from Redis)
    retry: 1,
  });
}

export function useCachedNodePools(clusterId: string, enabled = true) {
  return useQuery({
    queryKey: ["aks-nodepools-cached", clusterId],
    queryFn: () => fetchCachedNodePools(clusterId),
    enabled: !!clusterId && enabled,
    placeholderData: {
      source: "db",
      last_sync: null,
      node_pools: [],
      count: 0,
    },
    staleTime: 4_000,
    gcTime: 60_000,
    refetchInterval: safeInterval(5_000),
    retry: false,
    refetchOnWindowFocus: false,
  });
}

export function useSyncNodePools() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId }: { clusterId: string }) =>
      syncNodePoolsToDb(clusterId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-nodepools-cached"] });
      queryClient.invalidateQueries({ queryKey: ["aks-nodepools"] });
    },
  });
}

export function useScaleNodePool() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      clusterId,
      nodepoolName,
      nodeCount,
    }: {
      clusterId: string;
      nodepoolName: string;
      nodeCount: number;
    }) => scaleNodePool(clusterId, nodepoolName, nodeCount),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["aks-nodepools", variables.clusterId] });
      queryClient.invalidateQueries({ queryKey: ["aks-nodepools-cached", variables.clusterId] });
      queryClient.invalidateQueries({ queryKey: ["aks-clusters"] });
      queryClient.invalidateQueries({ queryKey: ["aks-scale-history"] });
    },
  });
}

export function useUpdateAutoscaling() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({
      clusterId,
      nodepoolName,
      enableAutoScaling,
      minCount,
      maxCount,
    }: {
      clusterId: string;
      nodepoolName: string;
      enableAutoScaling: boolean;
      minCount?: number;
      maxCount?: number;
    }) => updateNodePoolAutoscaling(clusterId, nodepoolName, enableAutoScaling, minCount, maxCount),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["aks-nodepools", variables.clusterId] });
      queryClient.invalidateQueries({ queryKey: ["aks-nodepools-cached", variables.clusterId] });
      queryClient.invalidateQueries({ queryKey: ["aks-clusters"] });
    },
  });
}

export function useStartCluster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId }: { clusterId: string }) => startCluster(clusterId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-clusters"] });
      queryClient.invalidateQueries({ queryKey: ["aks-clusters-cached"] });
    },
  });
}

export function useStopCluster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId }: { clusterId: string }) => stopCluster(clusterId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-clusters"] });
      queryClient.invalidateQueries({ queryKey: ["aks-clusters-cached"] });
    },
  });
}

// ── Cache Refresh Functions ───────────────────────────────────────────
// These bypass both frontend React Query cache AND backend cache
// to force a fresh live API call.

export function refreshClusters(queryClient: ReturnType<typeof useQueryClient>) {
  // Pre-seed with a bypass fetch, then invalidate local queries
  fetchClusters(undefined, undefined, true).then(() => {
    queryClient.invalidateQueries({ queryKey: ["aks-clusters"] });
  });
}

export function refreshDeployments(queryClient: ReturnType<typeof useQueryClient>, clusterId: string) {
  fetchDeployments(clusterId, undefined, true).then(() => {
    queryClient.invalidateQueries({ queryKey: ["aks-deployments", clusterId] });
  });
}

export function refreshPodMetrics(queryClient: ReturnType<typeof useQueryClient>, clusterId: string) {
  fetchPodMetrics(clusterId, undefined, true).then(() => {
    queryClient.invalidateQueries({ queryKey: ["aks-pod-metrics", clusterId] });
  });
}

export function refreshCronJobs(queryClient: ReturnType<typeof useQueryClient>, clusterId: string) {
  fetchCronJobs(clusterId, undefined, true).then(() => {
    queryClient.invalidateQueries({ queryKey: ["aks-cronjobs", clusterId] });
  });
}

export function refreshNodePools(queryClient: ReturnType<typeof useQueryClient>, clusterId: string) {
  fetchNodePools(clusterId, true).then(() => {
    queryClient.invalidateQueries({ queryKey: ["aks-nodepools", clusterId] });
  });
}

// ── Cache Health ──────────────────────────────────────────────────────

export interface CacheStats {
  cache_hits: number;
  cache_misses: number;
  live_api_calls: number;
  invalidations: number;
  hit_rate_pct: number;
  uptime_seconds: number;
  cache_healthy: boolean;
}

export async function fetchCacheStats(): Promise<CacheStats> {
  const { data } = await apiClient.get(`${API_PREFIX}/cache/stats`);
  return data;
}

export async function invalidateAllCache(): Promise<{ success: boolean; message: string }> {
  const { data } = await apiClient.post(`${API_PREFIX}/cache/invalidate`);
  return data;
}

export function useCacheStats() {
  return useQuery({
    queryKey: ["aks-cache-stats"],
    queryFn: fetchCacheStats,
    staleTime: 10 * 1000, // 10s — stats refresh quickly
    refetchInterval: 30 * 1000,
  });
}

export function useInvalidateCache() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: invalidateAllCache,
    onSuccess: () => {
      // After flushing backend cache, also invalidate all frontend queries
      queryClient.invalidateQueries({ queryKey: ["aks-clusters"] });
      queryClient.invalidateQueries({ queryKey: ["aks-deployments"] });
      queryClient.invalidateQueries({ queryKey: ["aks-pod-metrics"] });
      queryClient.invalidateQueries({ queryKey: ["aks-cronjobs"] });
      queryClient.invalidateQueries({ queryKey: ["aks-nodepools"] });
      queryClient.invalidateQueries({ queryKey: ["aks-cache-stats"] });
    },
  });
}

// ── Extended Resources (Secrets, Services, ConfigMaps, Ingress, Helm) ──

export interface K8sSecret {
  name: string;
  namespace: string;
  type: string;
  keys?: string[];
  key_count?: number;
  created_at?: string;
}

export interface SecretDetail {
  name: string;
  namespace: string;
  type: string;
  data: Record<string, string>;
  keys: string[];
  labels?: Record<string, string>;
  created_at?: string;
}

export interface K8sService {
  name: string;
  namespace: string;
  type: string;
  cluster_ip?: string;
  external_ip?: string;
  ports?: Array<{ port: number; target_port?: string; protocol?: string; name?: string }>;
  selector?: Record<string, string>;
  created_at?: string;
}

export interface ServiceDetail {
  name: string;
  namespace: string;
  type: string;
  cluster_ip?: string;
  ports?: Array<{ port: number; target_port?: string; protocol?: string; name?: string }>;
  selector?: Record<string, string>;
  labels?: Record<string, string>;
  annotations?: Record<string, string>;
}

export interface K8sIngress {
  name: string;
  namespace: string;
  hosts?: string[];
  backend_services?: string[];
  tls_secrets?: string[];
  address?: string;
  ingress_class?: string;
}

export interface HelmRelease {
  name: string;
  namespace: string;
  chart: string;
  revision: number;
  status: string;
  updated?: string;
}

export interface AksAuditEntry {
  id: number;
  timestamp: string | null;
  user_email: string;
  action: string;
  resource_name: string;
  status: string;
  summary: string;
}

export interface IngressDetail {
  name: string;
  namespace: string;
  ingress_class?: string;
  rules?: Array<{
    host?: string;
    path?: string;
    path_type?: string;
    service_name?: string;
    service_port?: number;
  }>;
  tls?: Array<{ hosts?: string[]; secret_name?: string }>;
  linked_services?: string[];
  linked_secrets?: string[];
  address?: string;
  labels?: Record<string, string>;
  annotations?: Record<string, string>;
}

export interface CachedExtendedList<T> {
  source: string;
  last_sync: string | null;
  count: number;
  items: T;
}

function extendedCachedParams(clusterId: string, namespace?: string) {
  const params: Record<string, string> = { cluster_id: clusterId };
  if (namespace) {
    params.namespace = namespace;
  }
  return params;
}

const EXTENDED_QUERY_OPTIONS = {
  staleTime: 4_000,
  gcTime: 60_000,
  refetchInterval: safeInterval(5_000),
  retry: false,
  refetchOnWindowFocus: false,
} as const;

export async function fetchCachedSecrets(clusterId: string, namespace?: string) {
  const { data } = await apiClient.get(`${API_PREFIX}/secrets/cached`, {
    params: extendedCachedParams(clusterId, namespace),
    timeout: 8000,
  });
  return data as { secrets: K8sSecret[]; count: number; source?: string; last_sync?: string | null };
}

export async function syncSecretsToDb(clusterId: string, namespace?: string) {
  const { data } = await apiClient.post(`${API_PREFIX}/secrets/sync`, null, { params: { cluster_id: clusterId, namespace }, timeout: 15000 });
  return data;
}

export async function deleteSecretApi(clusterId: string, namespace: string, name: string) {
  const { data } = await apiClient.delete(`${API_PREFIX}/secrets`, { params: { cluster_id: clusterId, namespace, name } });
  return data;
}

export async function fetchSecretDetail(clusterId: string, namespace: string, name: string, reveal = false) {
  const { data } = await apiClient.get(`${API_PREFIX}/secrets/detail`, {
    params: { cluster_id: clusterId, namespace, name, reveal },
  });
  return data as SecretDetail;
}

export async function createSecretApi(
  clusterId: string,
  namespace: string,
  name: string,
  data: Record<string, string>,
  secretType = "Opaque"
) {
  const { data: resp } = await apiClient.post(`${API_PREFIX}/secrets`, {
    cluster_id: clusterId,
    namespace,
    name,
    data,
    secret_type: secretType,
  });
  return resp;
}

export async function updateSecretApi(clusterId: string, namespace: string, name: string, data: Record<string, string>) {
  const { data: resp } = await apiClient.put(`${API_PREFIX}/secrets`, {
    cluster_id: clusterId,
    namespace,
    name,
    data,
  });
  return resp;
}

export async function fetchCachedServices(clusterId: string, namespace?: string) {
  const { data } = await apiClient.get(`${API_PREFIX}/services/cached`, {
    params: extendedCachedParams(clusterId, namespace),
    timeout: 8000,
  });
  return data as { services: K8sService[]; count: number; source?: string; last_sync?: string | null };
}

export async function syncServicesToDb(clusterId: string, namespace?: string) {
  const { data } = await apiClient.post(`${API_PREFIX}/services/sync`, null, { params: { cluster_id: clusterId, namespace }, timeout: 15000 });
  return data;
}

export async function deleteServiceApi(clusterId: string, namespace: string, name: string) {
  const { data } = await apiClient.delete(`${API_PREFIX}/services`, { params: { cluster_id: clusterId, namespace, name } });
  return data;
}

export async function fetchServiceDetail(clusterId: string, namespace: string, name: string) {
  const { data } = await apiClient.get(`${API_PREFIX}/services/detail`, {
    params: { cluster_id: clusterId, namespace, name },
  });
  return data as ServiceDetail;
}

export async function createServiceApi(
  clusterId: string,
  namespace: string,
  name: string,
  port: number,
  targetPort: number | string,
  selector: Record<string, string>,
  serviceType = "ClusterIP"
) {
  const { data } = await apiClient.post(`${API_PREFIX}/services`, {
    cluster_id: clusterId,
    namespace,
    name,
    port,
    target_port: targetPort,
    selector,
    service_type: serviceType,
  });
  return data;
}

export async function updateServiceApi(
  clusterId: string,
  namespace: string,
  name: string,
  port: number,
  targetPort: number | string,
  selector: Record<string, string>,
  serviceType = "ClusterIP"
) {
  const { data } = await apiClient.put(`${API_PREFIX}/services`, {
    cluster_id: clusterId,
    namespace,
    name,
    port,
    target_port: targetPort,
    selector,
    service_type: serviceType,
  });
  return data;
}

export async function fetchCachedConfigMapsExt(clusterId: string, namespace?: string) {
  const { data } = await apiClient.get(`${API_PREFIX}/configmaps/cached`, {
    params: extendedCachedParams(clusterId, namespace),
    timeout: 8000,
  });
  return data as { configmaps: ConfigMap[]; count: number; source?: string; last_sync?: string | null };
}

export async function syncConfigMapsToDb(clusterId: string, namespace?: string) {
  const { data } = await apiClient.post(`${API_PREFIX}/configmaps/sync`, null, { params: { cluster_id: clusterId, namespace }, timeout: 15000 });
  return data;
}

export async function deleteConfigMapApi(clusterId: string, namespace: string, name: string) {
  const { data } = await apiClient.delete(`${API_PREFIX}/configmaps`, { params: { cluster_id: clusterId, namespace, name } });
  return data;
}

export async function createConfigMapApi(clusterId: string, namespace: string, name: string, data: Record<string, string>) {
  const { data: resp } = await apiClient.post(`${API_PREFIX}/configmaps`, {
    cluster_id: clusterId,
    namespace,
    name,
    data,
  });
  return resp;
}

export async function updateConfigMapApi(clusterId: string, namespace: string, name: string, data: Record<string, string>) {
  const { data: resp } = await apiClient.put(`${API_PREFIX}/configmaps`, {
    cluster_id: clusterId,
    namespace,
    name,
    data,
  });
  return resp;
}

export async function fetchCachedIngress(clusterId: string, namespace?: string) {
  const { data } = await apiClient.get(`${API_PREFIX}/ingress/cached`, {
    params: extendedCachedParams(clusterId, namespace),
    timeout: 8000,
  });
  return data as { ingress: K8sIngress[]; count: number; source?: string; last_sync?: string | null };
}

export async function syncIngressToDb(clusterId: string, namespace?: string) {
  const { data } = await apiClient.post(`${API_PREFIX}/ingress/sync`, null, { params: { cluster_id: clusterId, namespace }, timeout: 15000 });
  return data;
}

export async function deleteIngressApi(clusterId: string, namespace: string, name: string) {
  const { data } = await apiClient.delete(`${API_PREFIX}/ingress`, { params: { cluster_id: clusterId, namespace, name } });
  return data;
}

export async function updateIngressApi(
  clusterId: string,
  namespace: string,
  name: string,
  rules: Array<{ host?: string; paths: Array<{ path: string; path_type: string; service_name: string; service_port: number }> }>,
  tls?: Array<{ hosts?: string[]; secret_name: string }> | null,
  ingressClass?: string | null,
) {
  const { data } = await apiClient.put(`${API_PREFIX}/ingress`, {
    cluster_id: clusterId,
    namespace,
    name,
    rules,
    tls: tls || undefined,
    ingress_class: ingressClass || undefined,
  });
  return data;
}

export async function fetchIngressDetail(clusterId: string, namespace: string, name: string) {
  const { data } = await apiClient.get(`${API_PREFIX}/ingress/detail`, {
    params: { cluster_id: clusterId, namespace, name },
  });
  return data as IngressDetail;
}

export async function fetchHelmReleases(clusterId: string, namespace?: string) {
  const { data } = await apiClient.get(`${API_PREFIX}/helm/releases`, { params: { cluster_id: clusterId, namespace }, timeout: 8000 });
  return data as { releases: HelmRelease[]; count: number };
}

export async function uninstallHelmRelease(clusterId: string, releaseName: string, namespace: string) {
  const { data } = await apiClient.delete(`${API_PREFIX}/helm/uninstall`, { params: { cluster_id: clusterId, release_name: releaseName, namespace } });
  return data;
}

export async function fetchAksNamespaces(clusterId: string) {
  const { data } = await apiClient.get(`${API_PREFIX}/namespaces`, { params: { cluster_id: clusterId }, timeout: 8000 });
  return data as { namespaces: string[]; count: number };
}

export async function fetchAksAuditHistory(clusterId?: string, namespace?: string) {
  const { data } = await apiClient.get(`${API_PREFIX}/history`, { params: { cluster_id: clusterId, namespace }, timeout: 8000 });
  return data as { history: AksAuditEntry[]; count: number };
}

export function useCachedSecrets(clusterId: string, namespace?: string, enabled = true) {
  return useQuery({
    queryKey: ["aks-secrets-cached", clusterId, namespace],
    queryFn: () => fetchCachedSecrets(clusterId, namespace),
    enabled: !!clusterId && enabled,
    placeholderData: {
      source: "db",
      last_sync: null,
      secrets: [],
      count: 0,
    },
    ...EXTENDED_QUERY_OPTIONS,
  });
}

export function useSyncSecrets() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId, namespace }: { clusterId: string; namespace?: string }) => syncSecretsToDb(clusterId, namespace),
    onSuccess: (_, v) => qc.invalidateQueries({ queryKey: ["aks-secrets-cached", v.clusterId] }),
  });
}

export function useDeleteSecret() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId, namespace, name }: { clusterId: string; namespace: string; name: string }) =>
      deleteSecretApi(clusterId, namespace, name),
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: ["aks-secrets-cached", v.clusterId] });
      qc.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useSecretDetail(clusterId: string, namespace: string, name: string, reveal = false, enabled = true) {
  return useQuery({
    queryKey: ["aks-secret-detail", clusterId, namespace, name, reveal],
    queryFn: () => fetchSecretDetail(clusterId, namespace, name, reveal),
    enabled: enabled && !!clusterId && !!namespace && !!name,
  });
}

export function useCreateSecret() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { clusterId: string; namespace: string; name: string; data: Record<string, string>; secretType?: string }) =>
      createSecretApi(vars.clusterId, vars.namespace, vars.name, vars.data, vars.secretType),
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: ["aks-secrets-cached", v.clusterId] });
      qc.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useUpdateSecret() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { clusterId: string; namespace: string; name: string; data: Record<string, string> }) =>
      updateSecretApi(vars.clusterId, vars.namespace, vars.name, vars.data),
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: ["aks-secrets-cached", v.clusterId] });
      qc.invalidateQueries({ queryKey: ["aks-secret-detail", v.clusterId, v.namespace, v.name] });
      qc.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useCachedServices(clusterId: string, namespace?: string, enabled = true) {
  return useQuery({
    queryKey: ["aks-services-cached", clusterId, namespace],
    queryFn: () => fetchCachedServices(clusterId, namespace),
    enabled: !!clusterId && enabled,
    placeholderData: {
      source: "db",
      last_sync: null,
      services: [],
      count: 0,
    },
    ...EXTENDED_QUERY_OPTIONS,
  });
}

export function useSyncServices() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId, namespace }: { clusterId: string; namespace?: string }) => syncServicesToDb(clusterId, namespace),
    onSuccess: (_, v) => qc.invalidateQueries({ queryKey: ["aks-services-cached", v.clusterId] }),
  });
}

export function useDeleteService() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId, namespace, name }: { clusterId: string; namespace: string; name: string }) =>
      deleteServiceApi(clusterId, namespace, name),
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: ["aks-services-cached", v.clusterId] });
      qc.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useServiceDetail(clusterId: string, namespace: string, name: string, enabled = true) {
  return useQuery({
    queryKey: ["aks-service-detail", clusterId, namespace, name],
    queryFn: () => fetchServiceDetail(clusterId, namespace, name),
    enabled: enabled && !!clusterId && !!namespace && !!name,
  });
}

export function useCreateService() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: {
      clusterId: string;
      namespace: string;
      name: string;
      port: number;
      targetPort: number | string;
      selector: Record<string, string>;
      serviceType?: string;
    }) =>
      createServiceApi(vars.clusterId, vars.namespace, vars.name, vars.port, vars.targetPort, vars.selector, vars.serviceType),
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: ["aks-services-cached", v.clusterId] });
      qc.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useUpdateService() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: {
      clusterId: string;
      namespace: string;
      name: string;
      port: number;
      targetPort: number | string;
      selector: Record<string, string>;
      serviceType?: string;
    }) =>
      updateServiceApi(vars.clusterId, vars.namespace, vars.name, vars.port, vars.targetPort, vars.selector, vars.serviceType),
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: ["aks-services-cached", v.clusterId] });
      qc.invalidateQueries({ queryKey: ["aks-service-detail", v.clusterId, v.namespace, v.name] });
      qc.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useCachedConfigMaps(clusterId: string, namespace?: string, enabled = true) {
  return useQuery({
    queryKey: ["aks-configmaps-cached", clusterId, namespace],
    queryFn: () => fetchCachedConfigMapsExt(clusterId, namespace),
    enabled: !!clusterId && enabled,
    placeholderData: {
      source: "db",
      last_sync: null,
      configmaps: [],
      count: 0,
    },
    ...EXTENDED_QUERY_OPTIONS,
  });
}

export function useSyncConfigMaps() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId, namespace }: { clusterId: string; namespace?: string }) => syncConfigMapsToDb(clusterId, namespace),
    onSuccess: (_, v) => qc.invalidateQueries({ queryKey: ["aks-configmaps-cached", v.clusterId] }),
  });
}

export function useDeleteConfigMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId, namespace, name }: { clusterId: string; namespace: string; name: string }) =>
      deleteConfigMapApi(clusterId, namespace, name),
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: ["aks-configmaps-cached", v.clusterId] });
      qc.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useCreateConfigMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { clusterId: string; namespace: string; name: string; data: Record<string, string> }) =>
      createConfigMapApi(vars.clusterId, vars.namespace, vars.name, vars.data),
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: ["aks-configmaps-cached", v.clusterId] });
      qc.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useUpdateConfigMap() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: { clusterId: string; namespace: string; name: string; data: Record<string, string> }) =>
      updateConfigMapApi(vars.clusterId, vars.namespace, vars.name, vars.data),
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: ["aks-configmaps-cached", v.clusterId] });
      qc.invalidateQueries({ queryKey: ["aks-configmap-detail", v.clusterId, v.namespace, v.name] });
      qc.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useCachedIngress(clusterId: string, namespace?: string, enabled = true) {
  return useQuery({
    queryKey: ["aks-ingress-cached", clusterId, namespace],
    queryFn: () => fetchCachedIngress(clusterId, namespace),
    enabled: !!clusterId && enabled,
    placeholderData: {
      source: "db",
      last_sync: null,
      ingress: [],
      count: 0,
    },
    ...EXTENDED_QUERY_OPTIONS,
  });
}

export function useSyncIngress() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId, namespace }: { clusterId: string; namespace?: string }) => syncIngressToDb(clusterId, namespace),
    onSuccess: (_, v) => qc.invalidateQueries({ queryKey: ["aks-ingress-cached", v.clusterId] }),
  });
}

export function useDeleteIngress() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId, namespace, name }: { clusterId: string; namespace: string; name: string }) =>
      deleteIngressApi(clusterId, namespace, name),
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: ["aks-ingress-cached", v.clusterId] });
      qc.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useUpdateIngress() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (vars: {
      clusterId: string;
      namespace: string;
      name: string;
      rules: Array<{ host?: string; paths: Array<{ path: string; path_type: string; service_name: string; service_port: number }> }>;
      tls?: Array<{ hosts?: string[]; secret_name: string }> | null;
      ingressClass?: string | null;
    }) => updateIngressApi(vars.clusterId, vars.namespace, vars.name, vars.rules, vars.tls, vars.ingressClass),
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: ["aks-ingress-cached", v.clusterId] });
      qc.invalidateQueries({ queryKey: ["aks-ingress-detail", v.clusterId, v.namespace, v.name] });
      qc.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useIngressDetail(clusterId: string, namespace: string, name: string, enabled = true) {
  return useQuery({
    queryKey: ["aks-ingress-detail", clusterId, namespace, name],
    queryFn: () => fetchIngressDetail(clusterId, namespace, name),
    enabled: enabled && !!clusterId && !!namespace && !!name,
  });
}

export function useHelmReleases(clusterId: string, namespace?: string) {
  return useQuery({
    queryKey: ["aks-helm-releases", clusterId, namespace],
    queryFn: () => fetchHelmReleases(clusterId, namespace),
    enabled: !!clusterId,
    placeholderData: {
      releases: [],
      count: 0,
    },
    staleTime: 4_000,
    gcTime: 60_000,
    refetchInterval: safeInterval(5_000),
    retry: false,
    refetchOnWindowFocus: false,
  });
}

export function useUninstallHelmRelease() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId, releaseName, namespace }: { clusterId: string; releaseName: string; namespace: string }) =>
      uninstallHelmRelease(clusterId, releaseName, namespace),
    onSuccess: (_, v) => {
      qc.invalidateQueries({ queryKey: ["aks-helm-releases", v.clusterId] });
      qc.invalidateQueries({ queryKey: ["aks-audit-history"] });
    },
  });
}

export function useAksNamespaces(clusterId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["aks-namespaces", clusterId],
    queryFn: () => fetchAksNamespaces(clusterId!),
    enabled: !!clusterId && enabled,
    placeholderData: (prev) => prev ?? {
      namespaces: [],
      count: 0,
    },
    staleTime: 4_000,
    gcTime: 60_000,
    refetchInterval: safeInterval(5_000),
    retry: 2,
    refetchOnWindowFocus: false,
  });
}

export function useAksAuditHistory(clusterId?: string, namespace?: string) {
  return useQuery({
    queryKey: ["aks-audit-history", clusterId, namespace],
    queryFn: () => fetchAksAuditHistory(clusterId, namespace),
    placeholderData: {
      history: [],
      count: 0,
    },
    staleTime: 4_000,
    gcTime: 60_000,
    refetchInterval: safeInterval(5_000),
    retry: false,
    refetchOnWindowFocus: false,
  });
}
