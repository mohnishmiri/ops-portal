/**
 * Infrastructure Alert API client and React Query hooks.
 * 
 * Provides:
 * - VM Threshold Alert management (CPU, Memory, Disk)
 * - Custom Expiry Alert management (MechID, Certificates, AAF, Database, ITServices)
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import apiClient from "./apiClient";

// ── Types ─────────────────────────────────────────────────────────────

export type AlertSeverity = "warning" | "critical";
export type AlertStatus = "active" | "acknowledged" | "resolved" | "snoozed";
export type ExpiryAlertType = "mech_id" | "certificate" | "aaf_account" | "database_account" | "itservices_domain";
export type EnvClassification = "prod" | "non_prod";

export interface VMThresholdConfig {
  id: number;
  subscription_id: string;
  resource_group: string;
  vm_name: string;
  vm_id: string;
  cpu_warning_threshold: number;
  cpu_critical_threshold: number;
  memory_warning_threshold: number;
  memory_critical_threshold: number;
  disk_warning_threshold: number;
  disk_critical_threshold: number;
  is_enabled: boolean;
  notification_emails: string[];
  snooze_until: string | null;
  created_at: string;
  created_by: string;
}

export interface VMThresholdAlert {
  id: number;
  config_id: number;
  vm_id: string;
  vm_name: string;
  metric_type: "cpu" | "memory" | "disk";
  current_value: number;
  threshold_value: number;
  severity: AlertSeverity;
  status: AlertStatus;
  created_at: string;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
}

export interface ExpiryConfig {
  id: number;
  alert_type: ExpiryAlertType;
  resource_name: string;
  resource_identifier: string;
  description: string | null;
  environment: EnvClassification | null;
  expiry_date: string;
  warning_days_before: number;
  critical_days_before: number;
  is_enabled: boolean;
  notification_emails: string[];
  metadata: Record<string, unknown>;
  created_at: string;
  created_by: string;
}

export interface ExpiryAlert {
  id: number;
  config_id: number;
  alert_type: ExpiryAlertType;
  resource_name: string;
  expiry_date: string;
  days_until_expiry: number;
  severity: AlertSeverity;
  status: AlertStatus;
  created_at: string;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
}

export interface StorageAlertConfig {
  id: number;
  subscription_id: string;
  resource_group: string;
  account_name: string;
  account_id: string;
  capacity_warning_gb: number;
  capacity_critical_gb: number;
  transactions_warning: number;
  transactions_critical: number;
  egress_warning_gb: number;
  egress_critical_gb: number;
  is_enabled: boolean;
  notification_emails: string[];
  snooze_until: string | null;
  created_at: string;
  created_by: string;
}

export interface PGFlexServer {
  id: string;
  name: string;
  location: string;
  resource_group: string;
  sku_name: string | null;
  sku_tier: string | null;
  version: string | null;
  state: string;
  fqdn: string | null;
  storage_size_gb: number | null;
  backup_retention_days: number | null;
  geo_redundant_backup: string | null;
  ha_mode: string | null;
  ha_state: string | null;
  admin_login: string | null;
  subscription_id: string;
}

export interface PGFlexServerConfig {
  id: number;
  subscription_id: string;
  resource_group: string;
  server_name: string;
  server_id: string;
  cpu_warning_threshold: number;
  cpu_critical_threshold: number;
  memory_warning_threshold: number;
  memory_critical_threshold: number;
  storage_warning_threshold: number;
  storage_critical_threshold: number;
  is_enabled: boolean;
  notification_emails: string[];
  snooze_until: string | null;
  created_at: string;
  created_by: string;
}

export interface PGFlexServerAlert {
  id: number;
  config_id: number;
  server_id: string;
  server_name: string;
  metric_type: "cpu" | "memory" | "storage";
  current_value: number;
  threshold_value: number;
  severity: AlertSeverity;
  status: AlertStatus;
  created_at: string;
  acknowledged_by: string | null;
  acknowledged_at: string | null;
  resolved_at: string | null;
  resolution_notes: string | null;
}

export interface PGMetrics {
  cpu: number | null;
  memory: number | null;
  storage: number | null;
  error?: string;
}

export interface AlertSummary {
  vm_threshold_alerts: {
    by_status: Record<string, number>;
    by_severity: Record<string, number>;
    total?: number;
    active?: number;
  };
  expiry_alerts: {
    by_type: Record<string, number>;
    by_status: Record<string, number>;
    total?: number;
    active?: number;
  };
  pg_flex_alerts?: {
    by_status: Record<string, number>;
    by_severity: Record<string, number>;
    total?: number;
    active?: number;
  };
  total_active_alerts: number;
  last_updated: string;
}

export interface AlertScheduleConfig {
  id: number;
  name: string;
  description: string | null;
  schedule_type: "interval" | "cron";
  interval_minutes: number;
  cron_expression: string | null;
  check_vm_thresholds: boolean;
  check_storage_thresholds: boolean;
  check_disk_thresholds: boolean;
  check_expiry_alerts: boolean;
  check_pg_thresholds: boolean;
  send_daily_digest: boolean;
  digest_time_utc: string;
  digest_recipients: string[];
  is_enabled: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  created_at: string;
  updated_at: string | null;
  created_by: string;
}

export interface CreateAlertScheduleConfigRequest {
  name: string;
  description?: string;
  schedule_type: "interval" | "cron";
  interval_minutes: number;
  cron_expression?: string;
  check_vm_thresholds: boolean;
  check_storage_thresholds: boolean;
  check_disk_thresholds: boolean;
  check_expiry_alerts: boolean;
  check_pg_thresholds: boolean;
  send_daily_digest: boolean;
  digest_time_utc: string;
  digest_recipients: string[];
  is_enabled: boolean;
}

export interface UpdateAlertScheduleConfigRequest {
  name?: string;
  description?: string;
  schedule_type?: "interval" | "cron";
  interval_minutes?: number;
  cron_expression?: string;
  check_vm_thresholds?: boolean;
  check_storage_thresholds?: boolean;
  check_disk_thresholds?: boolean;
  check_expiry_alerts?: boolean;
  check_pg_thresholds?: boolean;
  send_daily_digest?: boolean;
  digest_time_utc?: string;
  digest_recipients?: string[];
  is_enabled?: boolean;
}

export interface VMInfo {
  id: string;
  name: string;
  location: string;
  resource_group: string | null;
  vm_size: string | null;
  power_state: string;
  subscription_id?: string;
  os_type?: string;
  provisioning_state?: string;
  _last_sync?: string;
}

/** Wrapper returned by resource list endpoints (DB-first pattern) */
export interface ResourceListResponse<T> {
  source: "db" | "azure";
  last_sync: string | null;
  count: number;
  resources: T[];
}

export interface VMMetrics {
  cpu: number | null;
  memory: number | null;
  disk: number | null;
  error?: string;
}

// ── Request Types ─────────────────────────────────────────────────────

export interface CreateVMThresholdConfigRequest {
  subscription_id: string;
  resource_group: string;
  vm_name: string;
  vm_id: string;
  cpu_warning_threshold?: number;
  cpu_critical_threshold?: number;
  memory_warning_threshold?: number;
  memory_critical_threshold?: number;
  disk_warning_threshold?: number;
  disk_critical_threshold?: number;
  notification_emails?: string[];
}

export interface UpdateVMThresholdConfigRequest {
  cpu_warning_threshold?: number;
  cpu_critical_threshold?: number;
  memory_warning_threshold?: number;
  memory_critical_threshold?: number;
  disk_warning_threshold?: number;
  disk_critical_threshold?: number;
  is_enabled?: boolean;
  notification_emails?: string[];
  snooze_until?: string;
}

export interface CreateExpiryConfigRequest {
  alert_type: ExpiryAlertType;
  resource_name: string;
  resource_identifier: string;
  expiry_date: string;
  description?: string;
  environment?: EnvClassification;
  warning_days_before?: number;
  critical_days_before?: number;
  notification_emails?: string[];
  metadata?: Record<string, unknown>;
}

export interface UpdateExpiryConfigRequest {
  resource_name?: string;
  description?: string;
  environment?: EnvClassification;
  expiry_date?: string;
  warning_days_before?: number;
  critical_days_before?: number;
  is_enabled?: boolean;
  notification_emails?: string[];
  snooze_until?: string;
  metadata?: Record<string, unknown>;
}

export interface CreateStorageAlertConfigRequest {
  subscription_id: string;
  resource_group: string;
  account_name: string;
  account_id: string;
  capacity_warning_gb?: number;
  capacity_critical_gb?: number;
  transactions_warning?: number;
  transactions_critical?: number;
  egress_warning_gb?: number;
  egress_critical_gb?: number;
  notification_emails?: string[];
}

export interface UpdateStorageAlertConfigRequest {
  capacity_warning_gb?: number;
  capacity_critical_gb?: number;
  transactions_warning?: number;
  transactions_critical?: number;
  egress_warning_gb?: number;
  egress_critical_gb?: number;
  is_enabled?: boolean;
  notification_emails?: string[];
  snooze_until?: string;
}

export interface CreatePGFlexConfigRequest {
  subscription_id: string;
  resource_group: string;
  server_name: string;
  server_id: string;
  cpu_warning_threshold?: number;
  cpu_critical_threshold?: number;
  memory_warning_threshold?: number;
  memory_critical_threshold?: number;
  storage_warning_threshold?: number;
  storage_critical_threshold?: number;
  notification_emails?: string[];
}

export interface UpdatePGFlexConfigRequest {
  cpu_warning_threshold?: number;
  cpu_critical_threshold?: number;
  memory_warning_threshold?: number;
  memory_critical_threshold?: number;
  storage_warning_threshold?: number;
  storage_critical_threshold?: number;
  is_enabled?: boolean;
  notification_emails?: string[];
  snooze_until?: string;
}

// ── API Functions ─────────────────────────────────────────────────────

const API_BASE = "/infra-alerts";
const GRID_REFRESH_INTERVAL = 30_000;
const SUMMARY_REFRESH_INTERVAL = 60_000;

// Alert Summary
export const fetchAlertSummary = async (): Promise<AlertSummary> => {
  const response = await apiClient.get(`${API_BASE}/summary`);
  return response.data;
};

// VM Threshold Configs
export const fetchVMThresholdConfigs = async (
  subscriptionId?: string,
  isEnabled?: boolean
): Promise<VMThresholdConfig[]> => {
  const params = new URLSearchParams();
  if (subscriptionId) params.set("subscription_id", subscriptionId);
  if (isEnabled !== undefined) params.set("is_enabled", String(isEnabled));
  const response = await apiClient.get(`${API_BASE}/vm-thresholds/configs?${params}`);
  return response.data;
};

export const createVMThresholdConfig = async (
  data: CreateVMThresholdConfigRequest
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.post(`${API_BASE}/vm-thresholds/configs`, data);
  return response.data;
};

export const updateVMThresholdConfig = async (
  configId: number,
  data: UpdateVMThresholdConfigRequest
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.put(`${API_BASE}/vm-thresholds/configs/${configId}`, data);
  return response.data;
};

export const deleteVMThresholdConfig = async (
  configId: number
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.delete(`${API_BASE}/vm-thresholds/configs/${configId}`);
  return response.data;
};

// VM Threshold Alerts
export const fetchVMThresholdAlerts = async (
  status?: string,
  severity?: string,
  limit = 100
): Promise<VMThresholdAlert[]> => {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (severity) params.set("severity", severity);
  params.set("limit", String(limit));
  const response = await apiClient.get(`${API_BASE}/vm-thresholds/alerts?${params}`);
  return response.data;
};

export const acknowledgeVMAlert = async (
  alertId: number
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.post(`${API_BASE}/vm-thresholds/alerts/${alertId}/acknowledge`);
  return response.data;
};

export const resolveVMAlert = async (
  alertId: number,
  resolutionNotes?: string
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.post(`${API_BASE}/vm-thresholds/alerts/${alertId}/resolve`, {
    resolution_notes: resolutionNotes,
  });
  return response.data;
};

// VM Discovery & Metrics
export const fetchVMs = async (subscriptionId: string): Promise<VMInfo[]> => {
  const response = await apiClient.get(`${API_BASE}/vms?subscription_id=${subscriptionId}`);
  return response.data;
};

export const fetchVMMetrics = async (
  subscriptionId: string,
  resourceGroup: string,
  vmName: string
): Promise<VMMetrics> => {
  const response = await apiClient.get(
    `${API_BASE}/vms/${subscriptionId}/${resourceGroup}/${vmName}/metrics`
  );
  return response.data;
};

// Expiry Configs
export const fetchExpiryConfigs = async (
  alertType?: ExpiryAlertType,
  isEnabled?: boolean
): Promise<ExpiryConfig[]> => {
  const params = new URLSearchParams();
  if (alertType) params.set("alert_type", alertType);
  if (isEnabled !== undefined) params.set("is_enabled", String(isEnabled));
  const response = await apiClient.get(`${API_BASE}/expiry/configs?${params}`);
  return response.data;
};

export const createExpiryConfig = async (
  data: CreateExpiryConfigRequest
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.post(`${API_BASE}/expiry/configs`, data);
  return response.data;
};

export const updateExpiryConfig = async (
  configId: number,
  data: UpdateExpiryConfigRequest
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.put(`${API_BASE}/expiry/configs/${configId}`, data);
  return response.data;
};

export const deleteExpiryConfig = async (
  configId: number
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.delete(`${API_BASE}/expiry/configs/${configId}`);
  return response.data;
};

// Expiry Alerts
export const fetchExpiryAlerts = async (
  alertType?: ExpiryAlertType,
  status?: string,
  severity?: string,
  limit = 100
): Promise<ExpiryAlert[]> => {
  const params = new URLSearchParams();
  if (alertType) params.set("alert_type", alertType);
  if (status) params.set("status", status);
  if (severity) params.set("severity", severity);
  params.set("limit", String(limit));
  const response = await apiClient.get(`${API_BASE}/expiry/alerts?${params}`);
  return response.data;
};

export const acknowledgeExpiryAlert = async (
  alertId: number
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.post(`${API_BASE}/expiry/alerts/${alertId}/acknowledge`);
  return response.data;
};

export const resolveExpiryAlert = async (
  alertId: number,
  resolutionNotes?: string
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.post(`${API_BASE}/expiry/alerts/${alertId}/resolve`, {
    resolution_notes: resolutionNotes,
  });
  return response.data;
};

export const checkExpiryAlerts = async (): Promise<{ alerts_created: number }> => {
  const response = await apiClient.post(`${API_BASE}/expiry/check`);
  return response.data;
};

// Storage Alert Configs
export const fetchStorageAlertConfigs = async (
  subscriptionId?: string,
  isEnabled?: boolean
): Promise<StorageAlertConfig[]> => {
  const params = new URLSearchParams();
  if (subscriptionId) params.set("subscription_id", subscriptionId);
  if (isEnabled !== undefined) params.set("is_enabled", String(isEnabled));
  const response = await apiClient.get(`${API_BASE}/storage/configs?${params}`);
  return response.data;
};

export const createStorageAlertConfig = async (
  data: CreateStorageAlertConfigRequest
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.post(`${API_BASE}/storage/configs`, data);
  return response.data;
};

export const updateStorageAlertConfig = async (
  configId: number,
  data: UpdateStorageAlertConfigRequest
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.put(`${API_BASE}/storage/configs/${configId}`, data);
  return response.data;
};

export const deleteStorageAlertConfig = async (
  configId: number
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.delete(`${API_BASE}/storage/configs/${configId}`);
  return response.data;
};

// PG Flex Server Configs
export const fetchPGFlexConfigs = async (
  subscriptionId?: string,
  isEnabled?: boolean
): Promise<PGFlexServerConfig[]> => {
  const params = new URLSearchParams();
  if (subscriptionId) params.set("subscription_id", subscriptionId);
  if (isEnabled !== undefined) params.set("is_enabled", String(isEnabled));
  const response = await apiClient.get(`${API_BASE}/pg-thresholds/configs?${params}`);
  return response.data;
};

export const createPGFlexConfig = async (
  data: CreatePGFlexConfigRequest
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.post(`${API_BASE}/pg-thresholds/configs`, data);
  return response.data;
};

export const updatePGFlexConfig = async (
  configId: number,
  data: UpdatePGFlexConfigRequest
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.put(`${API_BASE}/pg-thresholds/configs/${configId}`, data);
  return response.data;
};

export const deletePGFlexConfig = async (
  configId: number
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.delete(`${API_BASE}/pg-thresholds/configs/${configId}`);
  return response.data;
};

// PG Flex Server Alerts
export const fetchPGFlexAlerts = async (
  status?: string,
  severity?: string,
  limit = 100
): Promise<PGFlexServerAlert[]> => {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (severity) params.set("severity", severity);
  params.set("limit", String(limit));
  const response = await apiClient.get(`${API_BASE}/pg-thresholds/alerts?${params}`);
  return response.data;
};

export const acknowledgePGFlexAlert = async (
  alertId: number
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.post(`${API_BASE}/pg-thresholds/alerts/${alertId}/acknowledge`);
  return response.data;
};

export const resolvePGFlexAlert = async (
  alertId: number,
  resolutionNotes?: string
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.post(`${API_BASE}/pg-thresholds/alerts/${alertId}/resolve`, {
    resolution_notes: resolutionNotes,
  });
  return response.data;
};

export const checkPGAlerts = async (): Promise<{ alerts_created: number }> => {
  const response = await apiClient.post(`${API_BASE}/pg-thresholds/check`);
  return response.data;
};

export const fetchAlertScheduleConfigs = async (): Promise<AlertScheduleConfig[]> => {
  const response = await apiClient.get(`${API_BASE}/scheduler/configs`);
  return response.data;
};

export const createAlertScheduleConfig = async (
  data: CreateAlertScheduleConfigRequest
): Promise<{ id: number; name: string; status: string }> => {
  const response = await apiClient.post(`${API_BASE}/scheduler/configs`, data);
  return response.data;
};

export const updateAlertScheduleConfig = async (
  configId: number,
  data: UpdateAlertScheduleConfigRequest
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.put(`${API_BASE}/scheduler/configs/${configId}`, data);
  return response.data;
};

export const deleteAlertScheduleConfig = async (
  configId: number
): Promise<{ id: number; status: string }> => {
  const response = await apiClient.delete(`${API_BASE}/scheduler/configs/${configId}`);
  return response.data;
};

// PG Flex Server Metrics
export const fetchPGMetrics = async (
  subscriptionId: string,
  resourceGroup: string,
  serverName: string
): Promise<PGMetrics> => {
  const response = await apiClient.get(
    `${API_BASE}/pg-servers/${subscriptionId}/${resourceGroup}/${serverName}/metrics`
  );
  return response.data;
};

// ── React Query Hooks ─────────────────────────────────────────────────

// Query Keys
export const infraAlertKeys = {
  all: ["infra-alerts"] as const,
  summary: () => [...infraAlertKeys.all, "summary"] as const,
  vmConfigs: (subscriptionId?: string) =>
    [...infraAlertKeys.all, "vm-configs", subscriptionId] as const,
  vmAlerts: (status?: string, severity?: string) =>
    [...infraAlertKeys.all, "vm-alerts", status, severity] as const,
  vms: (subscriptionId: string) => [...infraAlertKeys.all, "vms", subscriptionId] as const,
  vmMetrics: (subscriptionId: string, resourceGroup: string, vmName: string) =>
    [...infraAlertKeys.all, "vm-metrics", subscriptionId, resourceGroup, vmName] as const,
  expiryConfigs: (alertType?: ExpiryAlertType) =>
    [...infraAlertKeys.all, "expiry-configs", alertType] as const,
  expiryAlerts: (alertType?: ExpiryAlertType, status?: string, severity?: string) =>
    [...infraAlertKeys.all, "expiry-alerts", alertType, status, severity] as const,
  storageConfigs: (subscriptionId?: string) =>
    [...infraAlertKeys.all, "storage-configs", subscriptionId] as const,
  pgConfigs: (subscriptionId?: string) =>
    [...infraAlertKeys.all, "pg-configs", subscriptionId] as const,
  pgAlerts: (status?: string, severity?: string) =>
    [...infraAlertKeys.all, "pg-alerts", status, severity] as const,
  pgMetrics: (subscriptionId: string, resourceGroup: string, serverName: string) =>
    [...infraAlertKeys.all, "pg-metrics", subscriptionId, resourceGroup, serverName] as const,
};

// Summary Hook
export const useAlertSummary = () =>
  useQuery({
    queryKey: infraAlertKeys.summary(),
    queryFn: fetchAlertSummary,
    refetchInterval: SUMMARY_REFRESH_INTERVAL,
  });

// VM Threshold Config Hooks
export const useVMThresholdConfigs = (subscriptionId?: string, isEnabled?: boolean) =>
  useQuery({
    queryKey: infraAlertKeys.vmConfigs(subscriptionId),
    queryFn: () => fetchVMThresholdConfigs(subscriptionId, isEnabled),
    refetchInterval: GRID_REFRESH_INTERVAL,
  });

export const useCreateVMThresholdConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createVMThresholdConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

export const useUpdateVMThresholdConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ configId, data }: { configId: number; data: UpdateVMThresholdConfigRequest }) =>
      updateVMThresholdConfig(configId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

export const useDeleteVMThresholdConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteVMThresholdConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

// VM Threshold Alert Hooks
export const useVMThresholdAlerts = (status?: string, severity?: string, limit = 100) =>
  useQuery({
    queryKey: infraAlertKeys.vmAlerts(status, severity),
    queryFn: () => fetchVMThresholdAlerts(status, severity, limit),
    refetchInterval: GRID_REFRESH_INTERVAL,
  });

export const useAcknowledgeVMAlert = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: acknowledgeVMAlert,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

export const useResolveVMAlert = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ alertId, notes }: { alertId: number; notes?: string }) =>
      resolveVMAlert(alertId, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

// VM Discovery & Metrics Hooks
export const useVMs = (subscriptionId: string) =>
  useQuery({
    queryKey: infraAlertKeys.vms(subscriptionId),
    queryFn: () => fetchVMs(subscriptionId),
    enabled: !!subscriptionId,
  });

export const useVMMetrics = (
  subscriptionId: string,
  resourceGroup: string,
  vmName: string
) =>
  useQuery({
    queryKey: infraAlertKeys.vmMetrics(subscriptionId, resourceGroup, vmName),
    queryFn: () => fetchVMMetrics(subscriptionId, resourceGroup, vmName),
    enabled: !!(subscriptionId && resourceGroup && vmName),
    refetchInterval: SUMMARY_REFRESH_INTERVAL,
  });

// Expiry Config Hooks
export const useExpiryConfigs = (alertType?: ExpiryAlertType, isEnabled?: boolean) =>
  useQuery({
    queryKey: infraAlertKeys.expiryConfigs(alertType),
    queryFn: () => fetchExpiryConfigs(alertType, isEnabled),
    refetchInterval: GRID_REFRESH_INTERVAL,
  });

export const useCreateExpiryConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createExpiryConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

export const useUpdateExpiryConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ configId, data }: { configId: number; data: UpdateExpiryConfigRequest }) =>
      updateExpiryConfig(configId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

export const useDeleteExpiryConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteExpiryConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

// Expiry Alert Hooks
export const useExpiryAlerts = (
  alertType?: ExpiryAlertType,
  status?: string,
  severity?: string,
  limit = 100
) =>
  useQuery({
    queryKey: infraAlertKeys.expiryAlerts(alertType, status, severity),
    queryFn: () => fetchExpiryAlerts(alertType, status, severity, limit),
    refetchInterval: GRID_REFRESH_INTERVAL,
  });

export const useAcknowledgeExpiryAlert = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: acknowledgeExpiryAlert,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

export const useResolveExpiryAlert = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ alertId, notes }: { alertId: number; notes?: string }) =>
      resolveExpiryAlert(alertId, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

export const useCheckExpiryAlerts = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: checkExpiryAlerts,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

// Storage Alert Config Hooks
export const useStorageAlertConfigs = (subscriptionId?: string, isEnabled?: boolean) =>
  useQuery({
    queryKey: infraAlertKeys.storageConfigs(subscriptionId),
    queryFn: () => fetchStorageAlertConfigs(subscriptionId, isEnabled),
    refetchInterval: GRID_REFRESH_INTERVAL,
  });

export const useCreateStorageAlertConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createStorageAlertConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

export const useUpdateStorageAlertConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ configId, data }: { configId: number; data: UpdateStorageAlertConfigRequest }) =>
      updateStorageAlertConfig(configId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

export const useDeleteStorageAlertConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteStorageAlertConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

// PG Flex Server Config Hooks
export const usePGFlexConfigs = (subscriptionId?: string, isEnabled?: boolean) =>
  useQuery({
    queryKey: infraAlertKeys.pgConfigs(subscriptionId),
    queryFn: () => fetchPGFlexConfigs(subscriptionId, isEnabled),
    refetchInterval: GRID_REFRESH_INTERVAL,
  });

export const useCreatePGFlexConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createPGFlexConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

export const useUpdatePGFlexConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ configId, data }: { configId: number; data: UpdatePGFlexConfigRequest }) =>
      updatePGFlexConfig(configId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

export const useDeletePGFlexConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deletePGFlexConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

// PG Flex Server Alert Hooks
export const usePGFlexAlerts = (status?: string, severity?: string, limit = 100) =>
  useQuery({
    queryKey: infraAlertKeys.pgAlerts(status, severity),
    queryFn: () => fetchPGFlexAlerts(status, severity, limit),
    refetchInterval: GRID_REFRESH_INTERVAL,
  });

export const useAcknowledgePGFlexAlert = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: acknowledgePGFlexAlert,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

export const useResolvePGFlexAlert = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ alertId, notes }: { alertId: number; notes?: string }) =>
      resolvePGFlexAlert(alertId, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

export const useCheckPGAlerts = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: checkPGAlerts,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
    },
  });
};

// PG Flex Server Metrics Hook
export const usePGMetrics = (
  subscriptionId: string,
  resourceGroup: string,
  serverName: string
) =>
  useQuery({
    queryKey: infraAlertKeys.pgMetrics(subscriptionId, resourceGroup, serverName),
    queryFn: () => fetchPGMetrics(subscriptionId, resourceGroup, serverName),
    enabled: !!(subscriptionId && resourceGroup && serverName),
    refetchInterval: SUMMARY_REFRESH_INTERVAL,
  });

// ── Utility Functions ─────────────────────────────────────────────────

export const getAlertTypeLabel = (type: ExpiryAlertType): string => {
  const labels: Record<ExpiryAlertType, string> = {
    mech_id: "MechID Expiry",
    certificate: "Certificate Expiry",
    aaf_account: "AAF Account Expiry",
    database_account: "Database Account Expiry",
    itservices_domain: "ITServices Domain Expiry",
  };
  return labels[type] || type;
};

export const getEnvLabel = (env?: EnvClassification | null): string => {
  if (env === "prod") return "PROD";
  if (env === "non_prod") return "NPROD";
  return "\u2014";
};

export const getSeverityColor = (severity: AlertSeverity): string => {
  return severity === "critical" ? "text-red-600" : "text-yellow-600";
};

export const getSeverityBgColor = (severity: AlertSeverity): string => {
  return severity === "critical" ? "bg-red-100" : "bg-yellow-100";
};

export const getStatusColor = (status: AlertStatus): string => {
  const colors: Record<AlertStatus, string> = {
    active: "text-red-600",
    acknowledged: "text-blue-600",
    resolved: "text-green-600",
    snoozed: "text-gray-600",
  };
  return colors[status] || "text-gray-600";
};

// ── Azure Resource Types ──────────────────────────────────────────────

export interface AzureResource {
  id: string;
  name: string;
  resource_group: string;
  subscription_id: string;
  location: string;
  type: string;
}

export interface StorageAccount extends AzureResource {
  sku: string;
  kind: string;
  access_tier?: string;
  provisioning_state: string;
}

export interface ManagedDisk extends AzureResource {
  size_gb: number;
  sku: string;
  os_type?: string;
  disk_state: string;
  managed_by?: string;
}

export interface NetworkSecurityGroup extends AzureResource {
  rules_count: number;
  subnets: string[];
  network_interfaces: string[];
}

export interface PublicIP extends AzureResource {
  ip_address?: string;
  allocation_method: string;
  sku: string;
  associated_to?: string;
}

export interface LoadBalancer extends AzureResource {
  sku: string;
  frontend_ip_count: number;
  backend_pool_count: number;
  rules_count: number;
}

export interface ResourceInventory {
  id: number;
  resource_id: string;
  resource_type: string;
  resource_name: string;
  resource_group: string;
  subscription_id: string;
  location: string;
  metadata: Record<string, unknown>;
  last_sync_at: string;
  created_at: string;
  updated_at: string;
}

export interface ResourceInventorySummary {
  total_resources: number;
  by_type: Record<string, number>;
  by_location: Record<string, number>;
  by_subscription: Record<string, number>;
  last_sync_at?: string;
}

// ── Scheduler Types ───────────────────────────────────────────────────

export interface SchedulerJob {
  job_id: string;
  name: string;
  trigger: string;
  next_run_time: string | null;
  status: "running" | "paused";
}

export interface SchedulerStatus {
  scheduler_running: boolean;
  jobs: SchedulerJob[];
  last_vm_check?: string;
  last_expiry_check?: string;
  last_resource_sync?: string;
}

export interface TriggerResult {
  status: string;
  message: string;
  triggered_at: string;
}

// ── Notification Types ────────────────────────────────────────────────

export type NotificationType = "vm_threshold" | "expiry" | "storage" | "digest" | "test";
export type NotificationStatus = "pending" | "sent" | "failed";

export interface NotificationHistory {
  id: number;
  alert_type: string;
  notification_type: NotificationType;
  recipient_email: string;
  subject: string;
  status: NotificationStatus;
  error_message?: string;
  alert_id?: number;
  sent_at?: string;
  created_at?: string;
}

// ── Azure Resource API Functions ──────────────────────────────────────

export const fetchAzureVMs = async (source: "db" | "azure" = "db"): Promise<ResourceListResponse<VMInfo>> => {
  const response = await apiClient.get(`${API_BASE}/resources/vms?source=${source}`);
  return response.data;
};

export const fetchAzureStorageAccounts = async (source: "db" | "azure" = "db"): Promise<ResourceListResponse<StorageAccount>> => {
  const response = await apiClient.get(`${API_BASE}/resources/storage-accounts?source=${source}`);
  return response.data;
};

export const fetchAzureDisks = async (source: "db" | "azure" = "db"): Promise<ResourceListResponse<ManagedDisk>> => {
  const response = await apiClient.get(`${API_BASE}/resources/disks?source=${source}`);
  return response.data;
};

export const fetchAzurePGServers = async (source: "db" | "azure" = "db"): Promise<ResourceListResponse<PGFlexServer>> => {
  const response = await apiClient.get(`${API_BASE}/resources/pg-servers?source=${source}`);
  return response.data;
};

/** Sync resources from Azure live to DB */
export const syncResourcesToDb = async (resourceType?: string): Promise<Record<string, unknown>> => {
  const params = resourceType ? `?resource_type=${resourceType}` : "";
  const response = await apiClient.post(`${API_BASE}/resources/sync${params}`);
  return response.data;
};

export const fetchAzureNSGs = async (subscriptionId?: string): Promise<NetworkSecurityGroup[]> => {
  const params = subscriptionId ? `?subscription_id=${subscriptionId}` : "";
  const response = await apiClient.get(`${API_BASE}/resources/nsgs${params}`);
  return response.data;
};

export const fetchAzurePublicIPs = async (subscriptionId?: string): Promise<PublicIP[]> => {
  const params = subscriptionId ? `?subscription_id=${subscriptionId}` : "";
  const response = await apiClient.get(`${API_BASE}/resources/public-ips${params}`);
  return response.data;
};

export const fetchAzureLoadBalancers = async (subscriptionId?: string): Promise<LoadBalancer[]> => {
  const params = subscriptionId ? `?subscription_id=${subscriptionId}` : "";
  const response = await apiClient.get(`${API_BASE}/resources/load-balancers${params}`);
  return response.data;
};

export const fetchAllAzureResources = async (subscriptionId?: string): Promise<{
  vms: VMInfo[];
  storage_accounts: StorageAccount[];
  disks: ManagedDisk[];
  nsgs: NetworkSecurityGroup[];
  public_ips: PublicIP[];
  load_balancers: LoadBalancer[];
}> => {
  const params = subscriptionId ? `?subscription_id=${subscriptionId}` : "";
  const response = await apiClient.get(`${API_BASE}/resources/all${params}`);
  return response.data;
};

export const fetchResourceInventory = async (
  resourceType?: string,
  subscriptionId?: string
): Promise<ResourceInventory[]> => {
  const params = new URLSearchParams();
  if (resourceType) params.set("resource_type", resourceType);
  if (subscriptionId) params.set("subscription_id", subscriptionId);
  const queryString = params.toString();
  const response = await apiClient.get(`${API_BASE}/resources/inventory${queryString ? `?${queryString}` : ""}`);
  return response.data;
};

export const fetchResourceInventorySummary = async (): Promise<ResourceInventorySummary> => {
  const response = await apiClient.get(`${API_BASE}/resources/inventory/summary`);
  return response.data;
};

// ── Scheduler API Functions ───────────────────────────────────────────

export const fetchSchedulerStatus = async (): Promise<SchedulerStatus> => {
  const response = await apiClient.get(`${API_BASE}/scheduler/status`);
  return response.data;
};

export const triggerVMCheck = async (): Promise<TriggerResult> => {
  const response = await apiClient.post(`${API_BASE}/scheduler/trigger/vm-check`);
  return response.data;
};

export const triggerExpiryCheck = async (): Promise<TriggerResult> => {
  const response = await apiClient.post(`${API_BASE}/scheduler/trigger/expiry-check`);
  return response.data;
};

export const triggerDailyDigest = async (): Promise<TriggerResult> => {
  const response = await apiClient.post(`${API_BASE}/scheduler/trigger/daily-digest`);
  return response.data;
};

export const triggerResourceSync = async (): Promise<TriggerResult> => {
  const response = await apiClient.post(`${API_BASE}/scheduler/trigger/resource-sync`);
  return response.data;
};

export const triggerPGCheck = async (): Promise<TriggerResult> => {
  const response = await apiClient.post(`${API_BASE}/scheduler/trigger/pg-check`);
  return response.data;
};

// ── Scheduler Start / Stop ────────────────────────────────────────────

export const startScheduler = async (): Promise<SchedulerStatus> => {
  const response = await apiClient.post(`${API_BASE}/scheduler/start`);
  return response.data;
};

export const stopScheduler = async (): Promise<SchedulerStatus> => {
  const response = await apiClient.post(`${API_BASE}/scheduler/stop`);
  return response.data;
};

// ── VM Power Management Types & API Functions ─────────────────────────

export interface VMActionRequest {
  resource_group: string;
  vm_name: string;
}

export interface ResourceActionResult {
  status: string;
  action: string;
  vm_name?: string;
  server_name?: string;
  resource_group: string;
}

export const startVM = async (req: VMActionRequest): Promise<ResourceActionResult> => {
  const response = await apiClient.post(`${API_BASE}/resources/vms/start`, req);
  return response.data;
};

export const stopVM = async (req: VMActionRequest): Promise<ResourceActionResult> => {
  const response = await apiClient.post(`${API_BASE}/resources/vms/stop`, req);
  return response.data;
};

export const restartVM = async (req: VMActionRequest): Promise<ResourceActionResult> => {
  const response = await apiClient.post(`${API_BASE}/resources/vms/restart`, req);
  return response.data;
};

// ── PG Server Power Management Types & API Functions ──────────────────

export interface PGServerActionRequest {
  resource_group: string;
  server_name: string;
}

export const startPGServer = async (req: PGServerActionRequest): Promise<ResourceActionResult> => {
  const response = await apiClient.post(`${API_BASE}/resources/pg-servers/start`, req);
  return response.data;
};

export const stopPGServer = async (req: PGServerActionRequest): Promise<ResourceActionResult> => {
  const response = await apiClient.post(`${API_BASE}/resources/pg-servers/stop`, req);
  return response.data;
};

export const restartPGServer = async (req: PGServerActionRequest): Promise<ResourceActionResult> => {
  const response = await apiClient.post(`${API_BASE}/resources/pg-servers/restart`, req);
  return response.data;
};

// ── Notification API Functions ────────────────────────────────────────

export const fetchNotificationHistory = async (
  notificationType?: NotificationType,
  status?: NotificationStatus,
  limit = 100
): Promise<NotificationHistory[]> => {
  const params = new URLSearchParams();
  if (notificationType) params.set("notification_type", notificationType);
  if (status) params.set("status", status);
  params.set("limit", String(limit));
  const response = await apiClient.get(`${API_BASE}/notifications/history?${params}`);
  return response.data;
};

export const sendTestNotification = async (email: string): Promise<TriggerResult> => {
  const response = await apiClient.post(`${API_BASE}/notifications/test`, {
    recipient_email: email,
    notification_type: "vm_threshold",
  });
  return response.data;
};

// ── Azure Resource Hooks ──────────────────────────────────────────────

// Extended Query Keys
export const resourceKeys = {
  all: ["azure-resources"] as const,
  vms: (source?: string) => [...resourceKeys.all, "vms", source] as const,
  storageAccounts: (source?: string) => [...resourceKeys.all, "storage-accounts", source] as const,
  disks: (source?: string) => [...resourceKeys.all, "disks", source] as const,
  pgServers: (source?: string) => [...resourceKeys.all, "pg-servers", source] as const,
  nsgs: (subscriptionId?: string) => [...resourceKeys.all, "nsgs", subscriptionId] as const,
  publicIps: (subscriptionId?: string) => [...resourceKeys.all, "public-ips", subscriptionId] as const,
  loadBalancers: (subscriptionId?: string) => [...resourceKeys.all, "load-balancers", subscriptionId] as const,
  allResources: (subscriptionId?: string) => [...resourceKeys.all, "all", subscriptionId] as const,
  inventory: (resourceType?: string, subscriptionId?: string) =>
    [...resourceKeys.all, "inventory", resourceType, subscriptionId] as const,
  inventorySummary: () => [...resourceKeys.all, "inventory-summary"] as const,
};

export const schedulerKeys = {
  all: ["scheduler"] as const,
  status: () => [...schedulerKeys.all, "status"] as const,
  configs: () => [...schedulerKeys.all, "configs"] as const,
};

export const notificationKeys = {
  all: ["notifications"] as const,
  history: (type?: NotificationType, status?: NotificationStatus) =>
    [...notificationKeys.all, "history", type, status] as const,
};

// Resource Hooks
export const useAzureVMs = (source: "db" | "azure" = "db") =>
  useQuery({
    queryKey: resourceKeys.vms(source),
    queryFn: () => fetchAzureVMs(source),
    staleTime: 5 * 60 * 1000, // 5 minutes
    refetchInterval: GRID_REFRESH_INTERVAL,
  });

export const useAzureStorageAccounts = (source: "db" | "azure" = "db") =>
  useQuery({
    queryKey: resourceKeys.storageAccounts(source),
    queryFn: () => fetchAzureStorageAccounts(source),
    staleTime: 5 * 60 * 1000,
    refetchInterval: GRID_REFRESH_INTERVAL,
  });

export const useAzureDisks = (source: "db" | "azure" = "db") =>
  useQuery({
    queryKey: resourceKeys.disks(source),
    queryFn: () => fetchAzureDisks(source),
    staleTime: 5 * 60 * 1000,
    refetchInterval: GRID_REFRESH_INTERVAL,
  });

export const useAzurePGServers = (source: "db" | "azure" = "db") =>
  useQuery({
    queryKey: resourceKeys.pgServers(source),
    queryFn: () => fetchAzurePGServers(source),
    staleTime: 5 * 60 * 1000,
    refetchInterval: GRID_REFRESH_INTERVAL,
  });

export const useSyncResources = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (resourceType?: string) => syncResourcesToDb(resourceType),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: resourceKeys.all });
    },
  });
};

export const useAzureNSGs = (subscriptionId?: string) =>
  useQuery({
    queryKey: resourceKeys.nsgs(subscriptionId),
    queryFn: () => fetchAzureNSGs(subscriptionId),
    staleTime: 5 * 60 * 1000,
  });

export const useAzurePublicIPs = (subscriptionId?: string) =>
  useQuery({
    queryKey: resourceKeys.publicIps(subscriptionId),
    queryFn: () => fetchAzurePublicIPs(subscriptionId),
    staleTime: 5 * 60 * 1000,
  });

export const useAzureLoadBalancers = (subscriptionId?: string) =>
  useQuery({
    queryKey: resourceKeys.loadBalancers(subscriptionId),
    queryFn: () => fetchAzureLoadBalancers(subscriptionId),
    staleTime: 5 * 60 * 1000,
  });

export const useAllAzureResources = (subscriptionId?: string) =>
  useQuery({
    queryKey: resourceKeys.allResources(subscriptionId),
    queryFn: () => fetchAllAzureResources(subscriptionId),
    staleTime: 5 * 60 * 1000,
  });

export const useResourceInventory = (resourceType?: string, subscriptionId?: string) =>
  useQuery({
    queryKey: resourceKeys.inventory(resourceType, subscriptionId),
    queryFn: () => fetchResourceInventory(resourceType, subscriptionId),
    staleTime: 5 * 60 * 1000,
  });

export const useResourceInventorySummary = () =>
  useQuery({
    queryKey: resourceKeys.inventorySummary(),
    queryFn: fetchResourceInventorySummary,
    staleTime: 5 * 60 * 1000,
    refetchInterval: GRID_REFRESH_INTERVAL,
  });

// Scheduler Hooks
export const useSchedulerStatus = () =>
  useQuery({
    queryKey: schedulerKeys.status(),
    queryFn: fetchSchedulerStatus,
    refetchInterval: GRID_REFRESH_INTERVAL,
  });

export const useAlertScheduleConfigs = () =>
  useQuery({
    queryKey: schedulerKeys.configs(),
    queryFn: fetchAlertScheduleConfigs,
    refetchInterval: GRID_REFRESH_INTERVAL,
  });

export const useCreateAlertScheduleConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createAlertScheduleConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: schedulerKeys.all });
    },
  });
};

export const useUpdateAlertScheduleConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ configId, data }: { configId: number; data: UpdateAlertScheduleConfigRequest }) =>
      updateAlertScheduleConfig(configId, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: schedulerKeys.all });
    },
  });
};

export const useDeleteAlertScheduleConfig = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: deleteAlertScheduleConfig,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: schedulerKeys.all });
    },
  });
};

export const useTriggerVMCheck = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: triggerVMCheck,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
      queryClient.invalidateQueries({ queryKey: schedulerKeys.all });
    },
  });
};

export const useTriggerExpiryCheck = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: triggerExpiryCheck,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
      queryClient.invalidateQueries({ queryKey: schedulerKeys.all });
    },
  });
};

export const useTriggerDailyDigest = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: triggerDailyDigest,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: notificationKeys.all });
    },
  });
};

export const useTriggerResourceSync = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: triggerResourceSync,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: resourceKeys.all });
    },
  });
};

export const useTriggerPGCheck = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: triggerPGCheck,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: infraAlertKeys.all });
      queryClient.invalidateQueries({ queryKey: schedulerKeys.all });
    },
  });
};

// Notification Hooks
export const useNotificationHistory = (
  notificationType?: NotificationType,
  status?: NotificationStatus,
  limit = 100
) =>
  useQuery({
    queryKey: notificationKeys.history(notificationType, status),
    queryFn: () => fetchNotificationHistory(notificationType, status, limit),
    refetchInterval: SUMMARY_REFRESH_INTERVAL,
  });

export const useSendTestNotification = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: sendTestNotification,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: notificationKeys.all });
    },
  });
};

// ── Scheduler Start/Stop Hooks ────────────────────────────────────────

export const useStartScheduler = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: startScheduler,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: schedulerKeys.all });
    },
  });
};

export const useStopScheduler = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: stopScheduler,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: schedulerKeys.all });
    },
  });
};

// ── VM Power Management Hooks ─────────────────────────────────────────

export const useStartVM = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: startVM,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: resourceKeys.all });
    },
  });
};

export const useStopVM = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: stopVM,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: resourceKeys.all });
    },
  });
};

export const useRestartVM = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: restartVM,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: resourceKeys.all });
    },
  });
};

// ── PG Server Power Management Hooks ──────────────────────────────────

export const useStartPGServer = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: startPGServer,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: resourceKeys.all });
    },
  });
};

export const useStopPGServer = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: stopPGServer,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: resourceKeys.all });
    },
  });
};

export const useRestartPGServer = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: restartPGServer,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: resourceKeys.all });
    },
  });
};

// ── Additional Utility Functions ──────────────────────────────────────

export const getResourceTypeIcon = (type: string): string => {
  const icons: Record<string, string> = {
    vm: "🖥️",
    storage_account: "📦",
    disk: "💿",
    nsg: "🛡️",
    public_ip: "🌐",
    load_balancer: "⚖️",
    pg_flex_server: "🐘",
  };
  return icons[type] || "📋";
};

export const getNotificationTypeLabel = (type: NotificationType): string => {
  const labels: Record<NotificationType, string> = {
    vm_threshold: "VM Threshold Alert",
    expiry: "Expiry Alert",
    storage: "Storage Alert",
    digest: "Daily Digest",
    test: "Test Notification",
  };
  return labels[type] || type;
};

export const getNotificationStatusColor = (status: NotificationStatus): string => {
  const colors: Record<NotificationStatus, string> = {
    pending: "text-yellow-600",
    sent: "text-green-600",
    failed: "text-red-600",
  };
  return colors[status] || "text-gray-600";
};

export const formatDateTime = (dateString: string): string => {
  return new Date(dateString).toLocaleString();
};

export const formatRelativeTime = (dateString: string): string => {
  const date = new Date(dateString);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
};
