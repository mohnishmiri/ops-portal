/**
 * Checksum Schedule API Service
 * 
 * Handles all API calls for checksum schedule management:
 * - Create/Update/Delete schedules
 * - List schedules
 * - Test schedule execution
 * - Get schedule details
 */

import { useQuery, useMutation, useQueryClient, UseQueryOptions, UseMutationOptions } from "@tanstack/react-query";
import { AxiosError } from "axios";
import apiClient from "./apiClient";

// ─────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────

export interface ChecksumScheduleCreateRequest {
  name: string;
  description?: string;
  module_type: "synapse" | "aks";
  system?: string;
  environment?: string;
  workspace_name?: string;
  cluster_id?: string;
  cluster_name?: string;
  namespaces?: string[];
  schedule_type: "interval" | "cron";
  interval_hours?: number;
  cron_expression?: string;
  timezone: string;
  notification_emails?: string[];
  is_enabled: boolean;
}

export interface ChecksumScheduleDetail {
  id: number | string;
  name: string;
  description?: string;
  module_type: "synapse" | "aks";
  system?: string;
  environment?: string;
  workspace_name?: string;
  cluster_id?: string;
  cluster_name?: string;
  namespaces?: string[];
  schedule_type: "interval" | "cron";
  interval_hours?: number;
  cron_expression?: string;
  timezone: string;
  notification_emails: string[];
  is_enabled: boolean;
  last_run_at?: string;
  next_run_at?: string;
  created_at?: string;
  created_by?: string;
}

export interface ChecksumScheduleResponse {
  success: boolean;
  schedule_id?: string;
  name?: string;
  message: string;
}

export interface ChecksumScheduleListResponse {
  success: boolean;
  count: number;
  schedules: ChecksumScheduleDetail[];
}

export interface ChecksumScheduleTestResponse {
  success: boolean;
  schedule_id: string;
  name: string;
  last_run_at: string;
  message: string;
}

// ─────────────────────────────────────────────────────────────────
// API Client
// ─────────────────────────────────────────────────────────────────

const SCHEDULES_PATH = "/checksum-schedules";

// ─────────────────────────────────────────────────────────────────
// API Methods
// ─────────────────────────────────────────────────────────────────

export const checksumScheduleApi = {
  // Create schedule
  createSchedule: async (data: ChecksumScheduleCreateRequest): Promise<ChecksumScheduleResponse> => {
    const response = await apiClient.post(SCHEDULES_PATH, data);
    return response.data;
  },

  // List all schedules
  listSchedules: async (): Promise<ChecksumScheduleListResponse> => {
    const response = await apiClient.get(SCHEDULES_PATH);
    return response.data;
  },

  // Get specific schedule
  getSchedule: async (scheduleId: string): Promise<ChecksumScheduleDetail> => {
    const response = await apiClient.get(`${SCHEDULES_PATH}/${scheduleId}`);
    return response.data;
  },

  // Update schedule
  updateSchedule: async (
    scheduleId: string,
    data: ChecksumScheduleCreateRequest
  ): Promise<ChecksumScheduleResponse> => {
    const response = await apiClient.patch(`${SCHEDULES_PATH}/${scheduleId}`, data);
    return response.data;
  },

  // Delete schedule
  deleteSchedule: async (scheduleId: string): Promise<ChecksumScheduleResponse> => {
    const response = await apiClient.delete(`${SCHEDULES_PATH}/${scheduleId}`);
    return response.data;
  },

  // Test schedule
  testSchedule: async (scheduleId: string): Promise<ChecksumScheduleTestResponse> => {
    const response = await apiClient.post(`${SCHEDULES_PATH}/${scheduleId}/test`, {});
    return response.data;
  },

  // Toggle enable/disable
  toggleSchedule: async (scheduleId: string): Promise<{ success: boolean; is_enabled: boolean; message: string }> => {
    const response = await apiClient.patch(`${SCHEDULES_PATH}/${scheduleId}/toggle`);
    return response.data;
  },
};

// ─────────────────────────────────────────────────────────────────
// React Query Hooks
// ─────────────────────────────────────────────────────────────────

export const useListChecksumSchedules = (options?: Omit<UseQueryOptions<ChecksumScheduleListResponse>, 'queryKey' | 'queryFn'>) => {
  return useQuery<ChecksumScheduleListResponse, AxiosError>({
    queryKey: ["checksumSchedules"],
    queryFn: () => checksumScheduleApi.listSchedules(),
    refetchInterval: 30_000,
    ...options,
  });
};

export const useGetChecksumSchedule = (
  scheduleId: string,
  options?: UseQueryOptions<ChecksumScheduleDetail>
) => {
  return useQuery<ChecksumScheduleDetail, AxiosError>({
    queryKey: ["checksumSchedules", scheduleId],
    queryFn: () => checksumScheduleApi.getSchedule(scheduleId),
    enabled: !!scheduleId,
    ...options,
  });
};

export const useCreateChecksumSchedule = (
  options?: UseMutationOptions<
    ChecksumScheduleResponse,
    AxiosError,
    ChecksumScheduleCreateRequest
  >
) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data) => checksumScheduleApi.createSchedule(data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["checksumSchedules"] });
    },
    ...options,
  });
};

export const useUpdateChecksumSchedule = (
  options?: UseMutationOptions<
    ChecksumScheduleResponse,
    AxiosError,
    { scheduleId: string; data: ChecksumScheduleCreateRequest }
  >
) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ scheduleId, data }) => checksumScheduleApi.updateSchedule(scheduleId, data),
    onSuccess: (_resp, { scheduleId }) => {
      queryClient.invalidateQueries({ queryKey: ["checksumSchedules"] });
      queryClient.invalidateQueries({ queryKey: ["checksumSchedules", scheduleId] });
    },
    ...options,
  });
};

export const useDeleteChecksumSchedule = (
  options?: UseMutationOptions<
    ChecksumScheduleResponse,
    AxiosError,
    string
  >
) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (scheduleId) => checksumScheduleApi.deleteSchedule(scheduleId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["checksumSchedules"] });
    },
    ...options,
  });
};

export const useTestChecksumSchedule = (
  options?: UseMutationOptions<
    ChecksumScheduleTestResponse,
    AxiosError,
    string
  >
) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (scheduleId) => checksumScheduleApi.testSchedule(scheduleId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["checksumSchedules"] });
      queryClient.invalidateQueries({ queryKey: ["checksum-runs"] });
      queryClient.invalidateQueries({ queryKey: ["checksum-results"] });
      queryClient.invalidateQueries({ queryKey: ["checksum-metrics"] });
      queryClient.invalidateQueries({ queryKey: ["aks-checksum-runs"] });
      queryClient.invalidateQueries({ queryKey: ["aks-checksum-metrics"] });
    },
    ...options,
  });
};

export const useToggleChecksumSchedule = (
  options?: UseMutationOptions<
    { success: boolean; is_enabled: boolean; message: string },
    AxiosError,
    string
  >
) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (scheduleId) => checksumScheduleApi.toggleSchedule(scheduleId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["checksumSchedules"] });
    },
    ...options,
  });
};
