/**
 * Permissions API hooks.
 *
 * Covers resource CRUD, permission CRUD, and the user's effective
 * permissions endpoint.  All hooks are React Query based for consistent
 * caching and invalidation.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import apiClient from "./apiClient";
import type { EffectivePermissions } from "../contexts/PermissionsContext";

// ── Types ─────────────────────────────────────────────────────────────────────

export interface ResourceItem {
  id: number;
  resource_type: "module" | "page" | string;
  resource_name: string;
  description?: string;
  parent_id?: number | null;
  route_path?: string | null;
  is_system?: boolean;
  created_at?: string;
  updated_at?: string;
}

export interface ResourceCreatePayload {
  resource_type: string;
  resource_name: string;
  description?: string;
  parent_id?: number | null;
  route_path?: string | null;
}

export interface ResourceUpdatePayload {
  description?: string;
  route_path?: string | null;
  parent_id?: number | null;
}

export interface PermissionItem {
  id: number;
  subject_type: "user" | "role" | "group" | string;
  subject_id: string;
  resource_id: number;
  resource_name?: string | null;
  resource_type?: string | null;
  permission_type: "view" | "edit" | string;
  environment_scope?: "all" | "prod" | "nonprod" | string;
  created_at?: string;
}

export interface PermissionCreatePayload {
  subject_type: string;
  subject_id: string;
  resource_id: number;
  permission_type: string;
  environment_scope?: string;
}

// ── Resource hooks ────────────────────────────────────────────────────────────

export function useResources() {
  return useQuery<ResourceItem[]>({
    queryKey: ["permissions", "resources"],
    queryFn: async () => {
      const resp = await apiClient.get<ResourceItem[]>("/permissions/resources");
      return resp.data;
    },
  });
}

export function useCreateResource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: ResourceCreatePayload) => {
      const resp = await apiClient.post<ResourceItem>("/permissions/resources", payload);
      return resp.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["permissions", "resources"] }),
  });
}

export function useUpdateResource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...payload }: { id: number } & ResourceUpdatePayload) => {
      const resp = await apiClient.patch<ResourceItem>(`/permissions/resources/${id}`, payload);
      return resp.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["permissions", "resources"] }),
  });
}

export function useDeleteResource() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/permissions/resources/${id}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["permissions", "resources"] });
      qc.invalidateQueries({ queryKey: ["permissions", "list"] });
    },
  });
}

// ── Permission hooks ──────────────────────────────────────────────────────────

export function usePermissions() {
  return useQuery<PermissionItem[]>({
    queryKey: ["permissions", "list"],
    queryFn: async () => {
      const resp = await apiClient.get<PermissionItem[]>("/permissions/permissions");
      return resp.data;
    },
  });
}

export function useCreatePermission() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: PermissionCreatePayload) => {
      const resp = await apiClient.post<PermissionItem>("/permissions/permissions", payload);
      return resp.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["permissions", "list"] });
      qc.invalidateQueries({ queryKey: ["auth", "my-permissions"] });
    },
  });
}

export function useDeletePermission() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => {
      await apiClient.delete(`/permissions/permissions/${id}`);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["permissions", "list"] });
      qc.invalidateQueries({ queryKey: ["auth", "my-permissions"] });
    },
  });
}

// ── Audit log hook ────────────────────────────────────────────────────────────

export interface AuditLogEntry {
  id: number;
  timestamp: string;
  actor_user_id: string;
  actor_email: string;
  action: string;
  summary: string;
  subject_type?: string | null;
  subject_id?: string | null;
  resource_name?: string | null;
  resource_type?: string | null;
  permission_type?: string | null;
  ip_address?: string | null;
}

export interface AuditLogResponse {
  entries: AuditLogEntry[];
  total: number;
}

export function usePermissionsAuditLog(days = 30) {
  return useQuery<AuditLogResponse>({
    queryKey: ["permissions", "audit-log", days],
    queryFn: async () => {
      const resp = await apiClient.get<AuditLogResponse>(
        `/permissions/audit-log?days=${days}&limit=500`
      );
      return resp.data;
    },
    staleTime: 60 * 1000, // 1 min — audit log doesn't need real-time updates
    refetchOnWindowFocus: false,
  });
}

// ── Effective permissions hook ────────────────────────────────────────────────

export function useMyPermissions() {
  return useQuery<EffectivePermissions>({
    queryKey: ["auth", "my-permissions"],
    queryFn: async () => {
      const resp = await apiClient.get<EffectivePermissions>("/auth/my-permissions");
      return resp.data;
    },
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
  });
}

// ── Team types and hooks ──────────────────────────────────────────────────────

export interface TeamMember {
  id: number;
  user_id: string;
  user_email?: string | null;
  created_at?: string | null;
}

export interface TeamItem {
  id: number;
  team_name: string;
  description?: string | null;
  member_count: number;
  members: TeamMember[];
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TeamCreatePayload {
  team_name: string;
  description?: string;
}

export interface TeamMemberPayload {
  user_id: string;
  user_email?: string;
}

export function useTeams() {
  return useQuery<TeamItem[]>({
    queryKey: ["permissions", "teams"],
    queryFn: async () => {
      const resp = await apiClient.get<TeamItem[]>("/permissions/teams");
      return resp.data;
    },
  });
}

export function useCreateTeam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: TeamCreatePayload) => {
      const resp = await apiClient.post<TeamItem>("/permissions/teams", payload);
      return resp.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["permissions", "teams"] }),
  });
}

export function useDeleteTeam() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (teamId: number) => {
      await apiClient.delete(`/permissions/teams/${teamId}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["permissions", "teams"] }),
  });
}

export function useAddTeamMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ teamId, ...payload }: { teamId: number } & TeamMemberPayload) => {
      const resp = await apiClient.post(`/permissions/teams/${teamId}/members`, payload);
      return resp.data;
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["permissions", "teams"] }),
  });
}

export function useRemoveTeamMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ teamId, userId }: { teamId: number; userId: string }) => {
      await apiClient.delete(`/permissions/teams/${teamId}/members/${userId}`);
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ["permissions", "teams"] }),
  });
}

export function useSyncResources() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const resp = await apiClient.post("/permissions/resources/sync");
      return resp.data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["permissions", "resources"] });
      qc.invalidateQueries({ queryKey: ["auth", "my-permissions"] });
    },
  });
}
