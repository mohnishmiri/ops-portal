/**
 * AKS Operations API client and React Query hooks.
 * 
 * Provides:
 * - Cluster inventory and health
 * - Deployment management
 * - Pod observability
 * - CronJob management
 */

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
  const { data } = await apiClient.get(`${API_PREFIX}/clusters/cached`, { params });
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
  const { data } = await apiClient.post(`${API_PREFIX}/clusters/sync`);
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
  const { data } = await apiClient.get(`${API_PREFIX}/deployments/cached`, { params });
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
  const { data } = await apiClient.post(`${API_PREFIX}/deployments/sync`, null, { params });
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
  const { data } = await apiClient.get(`${API_PREFIX}/pods/metrics`, { params });
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
  const { data } = await apiClient.get(`${API_PREFIX}/cronjobs/cached`, { params });
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
  const { data } = await apiClient.post(`${API_PREFIX}/cronjobs/sync`, null, { params });
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
): Promise<{ success: boolean; cronjob: string; job_name: string }> {
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
  const { data } = await apiClient.get(`${API_PREFIX}/nodepools/cached`, { params });
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
  const { data } = await apiClient.post(`${API_PREFIX}/nodepools/sync`, null, { params });
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

export function useCachedClusters(environment?: string) {
  return useQuery({
    queryKey: ["aks-clusters-cached", environment],
    queryFn: () => fetchCachedClusters(environment),
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    refetchInterval: 30_000,
    retry: 2,
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

export function useCachedDeployments(clusterId: string, namespace?: string) {
  return useQuery({
    queryKey: ["aks-deployments-cached", clusterId, namespace],
    queryFn: () => fetchCachedDeployments(clusterId, namespace),
    enabled: !!clusterId,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    refetchInterval: 30_000,
    retry: 2,
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
      queryClient.invalidateQueries({ queryKey: ["aks-scale-history"] });
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
    },
  });
}

export function useCreateDeployment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Parameters<typeof createDeployment>[0]) => createDeployment(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-deployments"] });
      queryClient.invalidateQueries({ queryKey: ["aks-scale-history"] });
    },
  });
}

export function useUpdateDeployment() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Parameters<typeof updateDeployment>[0]) => updateDeployment(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-deployments"] });
      queryClient.invalidateQueries({ queryKey: ["aks-scale-history"] });
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
      queryClient.invalidateQueries({ queryKey: ["aks-scale-history"] });
    },
  });
}

export function usePodMetrics(clusterId: string, namespace?: string) {
  return useQuery({
    queryKey: ["aks-pod-metrics", clusterId, namespace],
    queryFn: () => fetchPodMetrics(clusterId, namespace),
    enabled: !!clusterId,
    staleTime: 60 * 1000,       // 1 min — matches backend Redis TTL
    gcTime: 3 * 60 * 1000,
    refetchInterval: 60 * 1000,  // poll every 1 min (served from Redis)
    retry: 1,
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

export function useCachedCronJobs(clusterId: string, namespace?: string) {
  return useQuery({
    queryKey: ["aks-cronjobs-cached", clusterId, namespace],
    queryFn: () => fetchCachedCronJobs(clusterId, namespace),
    enabled: !!clusterId,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    refetchInterval: 30_000,
    retry: 2,
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
    },
  });
}

export function useCreateCronJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Parameters<typeof createCronJob>[0]) => createCronJob(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-cronjobs"] });
    },
  });
}

export function useUpdateCronJob() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: Parameters<typeof updateCronJob>[0]) => updateCronJob(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-cronjobs"] });
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
  days: number = 30
) {
  return useQuery({
    queryKey: ["aks-scale-history", clusterId, namespace, deploymentName, days],
    queryFn: () => fetchScaleHistory(clusterId, namespace, deploymentName, days),
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

export function useCachedNodePools(clusterId: string) {
  return useQuery({
    queryKey: ["aks-nodepools-cached", clusterId],
    queryFn: () => fetchCachedNodePools(clusterId),
    enabled: !!clusterId,
    staleTime: 5 * 60 * 1000,
    gcTime: 10 * 60 * 1000,
    refetchInterval: 30_000,
    retry: 2,
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
    },
  });
}

export function useStopCluster() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ clusterId }: { clusterId: string }) => stopCluster(clusterId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["aks-clusters"] });
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
