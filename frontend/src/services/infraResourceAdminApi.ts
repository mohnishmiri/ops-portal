/**
 * Infrastructure Alerts — resource utilization and administration API.
 *
 * Utilization (current and history) for VMs and PG Flexible Servers, VM Run
 * Command, resize / redeploy / boot diagnostics, tags, disk snapshot / expand,
 * PG databases and firewall rules.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./apiClient";
import { resourceKeys } from "./infraAlertApi";

const BASE = "/infra-alerts/resources";

export type MetricKind = "vm" | "pg";
export type AdminResourceType = "virtual_machine" | "pg_flex_server" | "storage_account" | "managed_disk";

export interface UtilizationItem {
  state?: string | null;
  cpu: number | null;
  memory: number | null;
  disk?: number | null;
  storage?: number | null;
  collected_at?: string | null;
  error?: string;
}

export interface UtilizationResponse {
  kind: MetricKind;
  generated_at: string;
  /** Keyed by lower-case ARM resource ID. */
  items: Record<string, UtilizationItem>;
}

export interface MetricsPoint {
  time: string;
  cpu?: number;
  cpu_max?: number;
  memory?: number;
  memory_max?: number;
  disk?: number;
  disk_max?: number;
  storage?: number;
  storage_max?: number;
  connections?: number;
  connections_max?: number;
}

export interface MetricsSummary {
  average: number | null;
  peak: number | null;
  latest: number | null;
}

export interface MetricsHistory {
  kind: MetricKind;
  hours: number;
  interval: string;
  points: MetricsPoint[];
  summary: Record<string, MetricsSummary>;
}

export interface VMTarget {
  subscription_id: string;
  resource_group: string;
  vm_name: string;
}

export type RunState = "Pending" | "Running" | "Succeeded" | "Failed" | "TimedOut" | "Canceled" | "Unknown";

export interface RunCommandStatus {
  run_id: string;
  state: RunState;
  exit_code: number | null;
  output: string | null;
  error: string | null;
  message: string | null;
  started_at: string | null;
  finished_at: string | null;
  shell?: string | null;
  script?: string | null;
  tier?: string | null;
}

export interface RunHistoryItem {
  id: number;
  run_id: string | null;
  requested_at: string | null;
  requested_by: string;
  status: string;
  state: RunState | null;
  exit_code: number | null;
  script: string | null;
  output: string | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
}

export interface VMSize {
  name: string;
  cores: number;
  memory_gb: number;
  max_data_disks: number;
}

export interface BootDiagnostics {
  available: boolean;
  log: string;
  truncated: boolean;
  size_bytes?: number;
}

export interface PGOverview {
  databases: { name: string; charset: string | null; collation: string | null }[];
  firewall_rules: { name: string; start_ip: string; end_ip: string }[];
}

export const TERMINAL_RUN_STATES: RunState[] = ["Succeeded", "Failed", "TimedOut", "Canceled"];

export const adminKeys = {
  all: ["infra-resource-admin"] as const,
  utilization: (kind: MetricKind) => [...adminKeys.all, "utilization", kind] as const,
  history: (kind: MetricKind, sub: string, rg: string, name: string, hours: number) =>
    [...adminKeys.all, "history", kind, sub, rg, name, hours] as const,
  run: (runId: string) => [...adminKeys.all, "run", runId] as const,
  runHistory: (target: VMTarget) => [...adminKeys.all, "run-history", target.subscription_id, target.resource_group, target.vm_name] as const,
  sizes: (target: VMTarget) => [...adminKeys.all, "sizes", target.subscription_id, target.resource_group, target.vm_name] as const,
  boot: (target: VMTarget) => [...adminKeys.all, "boot", target.subscription_id, target.resource_group, target.vm_name] as const,
  pg: (sub: string, rg: string, name: string) => [...adminKeys.all, "pg", sub, rg, name] as const,
};

const path = (...parts: string[]) => parts.map(encodeURIComponent).join("/");
const targetParams = (t: VMTarget) => new URLSearchParams({ subscription_id: t.subscription_id, resource_group: t.resource_group, vm_name: t.vm_name });

/** Current CPU / memory of every running VM or PG server — refreshed every two minutes. */
export const useResourceUtilization = (kind: MetricKind, enabled = true) =>
  useQuery({
    queryKey: adminKeys.utilization(kind),
    queryFn: async (): Promise<UtilizationResponse> => (await apiClient.get(`${BASE}/utilization?kind=${kind}`)).data,
    enabled,
    staleTime: 110_000,
    refetchInterval: 120_000,
  });

export const useMetricsHistory = (kind: MetricKind, sub: string, rg: string, name: string, hours: number) =>
  useQuery({
    queryKey: adminKeys.history(kind, sub, rg, name, hours),
    queryFn: async (): Promise<MetricsHistory> =>
      (await apiClient.get(`${BASE}/${kind === "vm" ? "vms" : "pg-servers"}/${path(sub, rg, name)}/metrics/history?hours=${hours}`)).data,
    enabled: !!(sub && rg && name),
    staleTime: 60_000,
    refetchInterval: hours <= 6 ? 60_000 : 300_000,
  });

export const useStartRunCommand = () => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: VMTarget & { script: string; timeout_seconds: number; confirm_name?: string }) =>
      (await apiClient.post(`${BASE}/vms/run-command`, body)).data as { run_id: string; state: RunState; shell: string; tier: string },
    onSettled: (_data, _error, body) => queryClient.invalidateQueries({ queryKey: adminKeys.runHistory(body) }),
  });
};

/** Polls a run every 3 seconds until it finishes. */
export const useRunCommandStatus = (target: VMTarget, runId: string | null) =>
  useQuery({
    queryKey: adminKeys.run(runId ?? ""),
    queryFn: async (): Promise<RunCommandStatus> =>
      (await apiClient.get(`${BASE}/vms/run-command/${encodeURIComponent(runId as string)}?${targetParams(target)}`)).data,
    enabled: !!runId,
    refetchInterval: (query) => (query.state.data && TERMINAL_RUN_STATES.includes(query.state.data.state) ? false : 3_000),
  });

export const useRunCommandHistory = (target: VMTarget, enabled: boolean) =>
  useQuery({
    queryKey: adminKeys.runHistory(target),
    queryFn: async (): Promise<RunHistoryItem[]> => (await apiClient.get(`${BASE}/vms/run-command-history?${targetParams(target)}`)).data,
    enabled,
  });

export const useAvailableSizes = (target: VMTarget, enabled: boolean) =>
  useQuery({
    queryKey: adminKeys.sizes(target),
    queryFn: async (): Promise<VMSize[]> => (await apiClient.get(`${BASE}/vms/available-sizes?${targetParams(target)}`)).data,
    enabled,
    staleTime: 10 * 60_000,
  });

export const useBootDiagnostics = (target: VMTarget, enabled: boolean) =>
  useQuery({
    queryKey: adminKeys.boot(target),
    queryFn: async (): Promise<BootDiagnostics> => (await apiClient.get(`${BASE}/vms/boot-diagnostics?${targetParams(target)}`)).data,
    enabled,
    retry: false,
  });

export const usePGOverview = (sub: string, rg: string, name: string, enabled: boolean) =>
  useQuery({
    queryKey: adminKeys.pg(sub, rg, name),
    queryFn: async (): Promise<PGOverview> => (await apiClient.get(`${BASE}/pg-servers/${path(sub, rg, name)}/overview`)).data,
    enabled: enabled && !!(sub && rg && name),
    retry: false,
  });

/** Mutations that change a resource; each refreshes the inventory grids afterwards. */
function useAdminMutation<TBody>(url: string, method: "post" | "put" = "post") {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: TBody) => (await apiClient[method](`${BASE}/${url}`, body)).data as Record<string, unknown>,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: resourceKeys.all });
      queryClient.invalidateQueries({ queryKey: adminKeys.all });
    },
  });
}

export const useResizeVM = () => useAdminMutation<VMTarget & { size: string }>("vms/resize");
export const useRedeployVM = () => useAdminMutation<VMTarget>("vms/redeploy");
export const useReplaceTags = () =>
  useAdminMutation<{ resource_id: string; resource_type: AdminResourceType; tags: Record<string, string> }>("tags", "put");
export const useSnapshotDisk = () => useAdminMutation<{ subscription_id: string; resource_group: string; disk_name: string }>("disks/snapshot");
export const useExpandDisk = () =>
  useAdminMutation<{ subscription_id: string; resource_group: string; disk_name: string; size_gb: number }>("disks/expand");

export const azurePortalUrl = (resourceId: string) => `https://portal.azure.com/#resource${resourceId}/overview`;
