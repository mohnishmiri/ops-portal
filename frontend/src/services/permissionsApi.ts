import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import apiClient from "./apiClient";

export interface ResourceItem {
  id: number;
  resource_type: string;
  resource_name: string;
  description?: string;
}

export interface PermissionItem {
  id: number;
  subject_type: string;
  subject_id: string;
  resource_id: number;
  permission_type: string;
}

// Fetch all resources
export function useResources() {
  return useQuery<ResourceItem[]>(["permissions", "resources"], async () => {
    const resp = await apiClient.get("/api/v1/permissions/resources");
    return resp.data;
  });
}

// Create resource
export function useCreateResource() {
  const qc = useQueryClient();
  return useMutation(async (payload: Partial<ResourceItem>) => {
    const resp = await apiClient.post("/api/v1/permissions/resources", payload);
    return resp.data;
  }, {
    onSuccess: () => qc.invalidateQueries(["permissions", "resources"]),
  });
}

// Fetch permissions
export function usePermissions() {
  return useQuery<PermissionItem[]>(["permissions", "list"], async () => {
    const resp = await apiClient.get("/api/v1/permissions/permissions");
    return resp.data;
  });
}

// Create permission
export function useCreatePermission() {
  const qc = useQueryClient();
  return useMutation(async (payload: Partial<PermissionItem>) => {
    const resp = await apiClient.post("/api/v1/permissions/permissions", payload);
    return resp.data;
  }, {
    onSuccess: () => qc.invalidateQueries(["permissions", "list"]),
  });
}
