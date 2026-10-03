/**
 * Access API — projects, apps, subscription grants and access requests.
 *
 * Hierarchy: Project (e.g. Commissions) → App (e.g. ATTCC 31599) →
 * Subscription, each subscription Prod or Non-Prod. Users get access through
 * grants (project or app × tier × level, or a single subscription); without a
 * grant every module API answers 403.
 *
 *  • `/access/me`, `/access/catalog`, `/access/requests*` — every signed-in user.
 *  • `/access/admin/*` — Project Admins (their projects) and Super Admins (all).
 *    A 403 there means "not allowed for this project/action"; surface the
 *    backend `detail` (see `formatAxiosError`).
 *
 * Frontend gating is UX only — the backend authorizes every call.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./apiClient";

// ── Vocabulary ───────────────────────────────────────────────────────────────

export type Tier = "prod" | "nonprod";
export type AccessLevel = "read" | "write";
export type GrantScopeType = "project" | "app" | "subscription";
export type RequestScopeType = "project" | "app";
export type RequestStatus = "pending" | "approved" | "rejected" | "partially_approved" | "cancelled";
export type RequestItemStatus = "pending" | "approved" | "rejected" | "cancelled";
export type RequestStatusFilter = RequestStatus | "all";

/** Canonical tier order — Prod first, everywhere. */
export const TIERS: Tier[] = ["prod", "nonprod"];
export const LEVELS: AccessLevel[] = ["read", "write"];

/** Minimum justification length the backend accepts for an access request. */
export const MIN_JUSTIFICATION_LENGTH = 10;

// ── Types ────────────────────────────────────────────────────────────────────

export interface AccessGrant {
  id: number;
  subject_type: "user" | "everyone";
  subject_id: string;
  subject_email: string | null;
  scope_type: GrantScopeType;
  project_id: number | null;
  project_name: string | null;
  app_id: number | null;
  app_name: string | null;
  subscription_id: string | null;
  subscription_name: string | null;
  tier: Tier | null;
  level: AccessLevel;
  subscription_count: number;
  request_item_id: number | null;
  granted_by: string | null;
  created_at: string | null;
}

export interface AccessRequestItem {
  id: number;
  scope_type: RequestScopeType;
  project_id: number | null;
  project_name: string | null;
  app_id: number | null;
  app_name: string | null;
  tier: Tier;
  requested_level: AccessLevel;
  status: RequestItemStatus;
  granted_level: AccessLevel | null;
  decided_by: string | null;
  decided_at: string | null;
  decision_comment: string | null;
  /** True when the caller may approve / reject this line (admin of the project, not the requester). */
  can_decide: boolean;
}

export interface AccessRequest {
  id: number;
  requester_id: string;
  requester_email: string | null;
  requester_name: string | null;
  justification: string;
  status: RequestStatus;
  created_at: string | null;
  updated_at: string | null;
  items: AccessRequestItem[];
}

export interface MyAccess {
  is_super_admin: boolean;
  /** The Entra role caps the level: a read-role user can only ever get read. */
  role_ceiling: AccessLevel;
  has_subscription_access: boolean;
  /** Null for a Super Admin (unlimited). */
  readable_count: number | null;
  writable_count: number | null;
  admin_projects: { id: number; name: string }[];
  grants: AccessGrant[];
  pending_requests: number;
}

export interface CatalogApp {
  id: number;
  name: string;
  app_code: string;
  /** Tiers that currently have at least one subscription. */
  tiers: Tier[];
}

export interface CatalogProject {
  id: number;
  name: string;
  description: string | null;
  apps: CatalogApp[];
}

export interface AdminProjectApp {
  id: number;
  app_code: string;
  name: string;
  description: string | null;
  subscription_counts: Record<Tier, number>;
}

export interface AdminProject {
  id: number;
  project_key: string;
  name: string;
  description: string | null;
  is_active: boolean;
  admins: { user_id: string; email: string | null }[];
  apps: AdminProjectApp[];
}

export interface PortalUserSummary {
  user_id: string;
  email: string | null;
  display_name: string | null;
  roles: string[];
  last_seen_at: string | null;
}

export interface SubscriptionPlacement {
  subscription_id: string;
  subscription_name: string | null;
  enabled: boolean;
  monitored: boolean;
  environment: string | null;
  tier: Tier | null;
  app_id: number | null;
  app_name: string | null;
  project_id: number | null;
  project_name: string | null;
  suggested_tier: Tier | null;
  suggested_app_code: string | null;
  suggested_app_name: string | null;
  suggested_app_id: number | null;
}

export interface AccessRequestItemInput {
  scope_type: RequestScopeType;
  project_id?: number;
  app_id?: number;
  tier: Tier;
  level: AccessLevel;
}

export interface AccessRequestPayload {
  justification: string;
  items: AccessRequestItemInput[];
}

export interface GrantCreatePayload {
  user_ids: string[];
  everyone?: false;
  scope_type: GrantScopeType;
  project_id?: number;
  app_id?: number;
  subscription_id?: string;
  /** One grant is created per tier per user; ignored for subscription scope. */
  tiers: Tier[];
  level: AccessLevel;
}

export interface GrantFilters {
  project_id?: number;
  user_id?: string;
}

export interface DecisionPayload {
  decision: "approve" | "reject";
  /** Approve at the requested level or lower. */
  level?: AccessLevel;
  comment?: string;
}

export interface ProjectCreatePayload {
  name: string;
  description?: string;
  project_key?: string;
}

export interface ProjectUpdatePayload {
  name?: string;
  description?: string;
  is_active?: boolean;
}

export interface AppCreatePayload {
  app_code: string;
  name: string;
  description?: string;
  place_matching: boolean;
}

export interface AppCreateResult {
  id: number;
  app_code: string;
  name: string;
  /** Unplaced subscriptions whose name carried this AppID and were placed straight away. */
  placed_subscriptions: string[];
}

export interface AppUpdatePayload {
  name?: string;
  description?: string;
  project_id?: number;
}

export interface PlacementPayload {
  app_id: number | null;
  tier: Tier;
}

// ── Pure helpers ─────────────────────────────────────────────────────────────

export interface RequestSelection {
  projectIds: number[];
  appIds: number[];
  tiers: Tier[];
  level: AccessLevel;
}

/** The highest level a user may request or hold, given their Entra role. */
export function clampLevel(level: AccessLevel, ceiling: AccessLevel): AccessLevel {
  return ceiling === "read" ? "read" : level;
}

/**
 * Expand a request-form selection into request items: one item per
 * project / app × tier.
 *
 * Duplicate ids and tiers are dropped and tiers come out in canonical order
 * (Prod, then Non-Prod). When `catalog` is given, an app whose project is
 * also selected is skipped — the project line already covers it.
 */
export function buildRequestItems(
  { projectIds, appIds, tiers, level }: RequestSelection,
  catalog?: CatalogProject[],
): AccessRequestItemInput[] {
  const orderedTiers = TIERS.filter((tier) => tiers.includes(tier));
  const projects = Array.from(new Set(projectIds));
  const selectedProjects = new Set(projects);

  const appProject = new Map<number, number>();
  catalog?.forEach((project) => project.apps.forEach((app) => appProject.set(app.id, project.id)));
  const apps = Array.from(new Set(appIds)).filter((appId) => {
    const projectId = appProject.get(appId);
    return projectId === undefined || !selectedProjects.has(projectId);
  });

  const items: AccessRequestItemInput[] = [];
  for (const project_id of projects) {
    for (const tier of orderedTiers) items.push({ scope_type: "project", project_id, tier, level });
  }
  for (const app_id of apps) {
    for (const tier of orderedTiers) items.push({ scope_type: "app", app_id, tier, level });
  }
  return items;
}

/** A request can be withdrawn only while nobody has acted on any of its lines. */
export function isCancellable(request: AccessRequest): boolean {
  return request.status === "pending" && request.items.every((item) => item.status === "pending");
}

// ── Raw calls ────────────────────────────────────────────────────────────────

export const accessApi = {
  // Self-service
  getMyAccess: async () => (await apiClient.get<MyAccess>("/access/me")).data,
  getCatalog: async () => (await apiClient.get<CatalogProject[]>("/access/catalog")).data,
  submitRequest: async (payload: AccessRequestPayload) =>
    (await apiClient.post<AccessRequest>("/access/requests", payload)).data,
  getMyRequests: async () => (await apiClient.get<AccessRequest[]>("/access/requests/mine")).data,
  cancelRequest: async (requestId: number) =>
    (await apiClient.post<AccessRequest>(`/access/requests/${requestId}/cancel`)).data,

  // Projects & apps
  getAdminProjects: async () => (await apiClient.get<AdminProject[]>("/access/admin/projects")).data,
  createProject: async (payload: ProjectCreatePayload) =>
    (await apiClient.post<{ id: number; project_key: string; name: string }>("/access/admin/projects", payload)).data,
  updateProject: async (projectId: number, payload: ProjectUpdatePayload) =>
    (await apiClient.patch(`/access/admin/projects/${projectId}`, payload)).data,
  deleteProject: async (projectId: number) => (await apiClient.delete(`/access/admin/projects/${projectId}`)).data,
  createApp: async (projectId: number, payload: AppCreatePayload) =>
    (await apiClient.post<AppCreateResult>(`/access/admin/projects/${projectId}/apps`, payload)).data,
  updateApp: async (appId: number, payload: AppUpdatePayload) =>
    (await apiClient.patch(`/access/admin/apps/${appId}`, payload)).data,
  deleteApp: async (appId: number) => (await apiClient.delete(`/access/admin/apps/${appId}`)).data,
  addProjectAdmin: async (projectId: number, userId: string) =>
    (await apiClient.post(`/access/admin/projects/${projectId}/admins`, { user_id: userId })).data,
  removeProjectAdmin: async (projectId: number, userId: string) =>
    (await apiClient.delete(`/access/admin/projects/${projectId}/admins/${encodeURIComponent(userId)}`)).data,

  // Subscription placement (Super Admin)
  getSubscriptionPlacements: async () =>
    (await apiClient.get<SubscriptionPlacement[]>("/access/admin/subscriptions")).data,
  placeSubscription: async (subscriptionId: string, payload: PlacementPayload) =>
    (await apiClient.put(`/access/admin/subscriptions/${encodeURIComponent(subscriptionId)}`, payload)).data,

  // Users & grants
  searchUsers: async (search: string) =>
    (
      await apiClient.get<PortalUserSummary[]>("/access/admin/users", {
        params: search.trim() ? { search: search.trim() } : undefined,
      })
    ).data,
  getGrants: async (filters: GrantFilters = {}) =>
    (
      await apiClient.get<AccessGrant[]>("/access/admin/grants", {
        params: {
          ...(filters.project_id != null ? { project_id: filters.project_id } : {}),
          ...(filters.user_id ? { user_id: filters.user_id } : {}),
        },
      })
    ).data,
  createGrants: async (payload: GrantCreatePayload) =>
    (await apiClient.post<AccessGrant[]>("/access/admin/grants", payload)).data,
  updateGrant: async (grantId: number, level: AccessLevel) =>
    (await apiClient.patch<AccessGrant>(`/access/admin/grants/${grantId}`, { level })).data,
  revokeGrant: async (grantId: number) => (await apiClient.delete(`/access/admin/grants/${grantId}`)).data,

  // Requests (approvers)
  getAdminRequests: async (status: RequestStatusFilter = "pending") =>
    (await apiClient.get<AccessRequest[]>("/access/admin/requests", { params: { status } })).data,
  decideItem: async (requestId: number, itemId: number, payload: DecisionPayload) =>
    (
      await apiClient.post<AccessRequest>(
        `/access/admin/requests/${requestId}/items/${itemId}/decision`,
        payload,
      )
    ).data,
};

// ── Query keys ───────────────────────────────────────────────────────────────

export const accessKeys = {
  all: ["access"] as const,
  me: ["access", "me"] as const,
  catalog: ["access", "catalog"] as const,
  myRequests: ["access", "requests", "mine"] as const,
  adminProjects: ["access", "admin", "projects"] as const,
  adminSubscriptions: ["access", "admin", "subscriptions"] as const,
  adminUsers: (search: string) => ["access", "admin", "users", search.trim().toLowerCase()] as const,
  adminGrants: (filters: GrantFilters = {}) => ["access", "admin", "grants", filters] as const,
  adminRequests: (status: RequestStatusFilter) => ["access", "admin", "requests", status] as const,
};

// ── Self-service hooks ───────────────────────────────────────────────────────

export function useMyAccess() {
  return useQuery<MyAccess>({ queryKey: accessKeys.me, queryFn: accessApi.getMyAccess, staleTime: 30 * 1000 });
}

export function useAccessCatalog() {
  return useQuery<CatalogProject[]>({ queryKey: accessKeys.catalog, queryFn: accessApi.getCatalog });
}

export function useMyRequests() {
  return useQuery<AccessRequest[]>({
    queryKey: accessKeys.myRequests,
    queryFn: accessApi.getMyRequests,
    staleTime: 30 * 1000,
  });
}

/** Invalidate everything access-related — grants and requests move together. */
function useInvalidateAccess() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: accessKeys.all });
}

export function useSubmitAccessRequest() {
  const invalidate = useInvalidateAccess();
  return useMutation({ mutationFn: accessApi.submitRequest, onSuccess: invalidate });
}

export function useCancelAccessRequest() {
  const invalidate = useInvalidateAccess();
  return useMutation({ mutationFn: accessApi.cancelRequest, onSuccess: invalidate });
}

// ── Administration hooks ─────────────────────────────────────────────────────

export function useAdminProjects(enabled = true) {
  return useQuery<AdminProject[]>({
    queryKey: accessKeys.adminProjects,
    queryFn: accessApi.getAdminProjects,
    enabled,
  });
}

export function useSubscriptionPlacements(enabled = true) {
  return useQuery<SubscriptionPlacement[]>({
    queryKey: accessKeys.adminSubscriptions,
    queryFn: accessApi.getSubscriptionPlacements,
    enabled,
  });
}

export function useAdminUsers(search: string, enabled = true) {
  return useQuery<PortalUserSummary[]>({
    queryKey: accessKeys.adminUsers(search),
    queryFn: () => accessApi.searchUsers(search),
    enabled,
    staleTime: 60 * 1000,
  });
}

export function useAdminGrants(filters: GrantFilters = {}, enabled = true) {
  return useQuery<AccessGrant[]>({
    queryKey: accessKeys.adminGrants(filters),
    queryFn: () => accessApi.getGrants(filters),
    enabled,
  });
}

export function useAdminRequests(status: RequestStatusFilter = "pending", enabled = true) {
  return useQuery<AccessRequest[]>({
    queryKey: accessKeys.adminRequests(status),
    queryFn: () => accessApi.getAdminRequests(status),
    enabled,
  });
}

export function useCreateProject() {
  const invalidate = useInvalidateAccess();
  return useMutation({ mutationFn: accessApi.createProject, onSuccess: invalidate });
}

export function useUpdateProject() {
  const invalidate = useInvalidateAccess();
  return useMutation({
    mutationFn: ({ projectId, ...payload }: { projectId: number } & ProjectUpdatePayload) =>
      accessApi.updateProject(projectId, payload),
    onSuccess: invalidate,
  });
}

export function useDeleteProject() {
  const invalidate = useInvalidateAccess();
  return useMutation({ mutationFn: accessApi.deleteProject, onSuccess: invalidate });
}

export function useCreateApp() {
  const invalidate = useInvalidateAccess();
  return useMutation({
    mutationFn: ({ projectId, ...payload }: { projectId: number } & AppCreatePayload) =>
      accessApi.createApp(projectId, payload),
    onSuccess: invalidate,
  });
}

export function useUpdateApp() {
  const invalidate = useInvalidateAccess();
  return useMutation({
    mutationFn: ({ appId, ...payload }: { appId: number } & AppUpdatePayload) => accessApi.updateApp(appId, payload),
    onSuccess: invalidate,
  });
}

export function useDeleteApp() {
  const invalidate = useInvalidateAccess();
  return useMutation({ mutationFn: accessApi.deleteApp, onSuccess: invalidate });
}

export function useAddProjectAdmin() {
  const invalidate = useInvalidateAccess();
  return useMutation({
    mutationFn: ({ projectId, userId }: { projectId: number; userId: string }) =>
      accessApi.addProjectAdmin(projectId, userId),
    onSuccess: invalidate,
  });
}

export function useRemoveProjectAdmin() {
  const invalidate = useInvalidateAccess();
  return useMutation({
    mutationFn: ({ projectId, userId }: { projectId: number; userId: string }) =>
      accessApi.removeProjectAdmin(projectId, userId),
    onSuccess: invalidate,
  });
}

export function usePlaceSubscription() {
  const invalidate = useInvalidateAccess();
  return useMutation({
    mutationFn: ({ subscriptionId, ...payload }: { subscriptionId: string } & PlacementPayload) =>
      accessApi.placeSubscription(subscriptionId, payload),
    onSuccess: invalidate,
  });
}

export function useCreateGrants() {
  const invalidate = useInvalidateAccess();
  return useMutation({ mutationFn: accessApi.createGrants, onSuccess: invalidate });
}

export function useUpdateGrant() {
  const invalidate = useInvalidateAccess();
  return useMutation({
    mutationFn: ({ grantId, level }: { grantId: number; level: AccessLevel }) => accessApi.updateGrant(grantId, level),
    onSuccess: invalidate,
  });
}

export function useRevokeGrant() {
  const invalidate = useInvalidateAccess();
  return useMutation({ mutationFn: accessApi.revokeGrant, onSuccess: invalidate });
}

export function useDecideRequestItem() {
  const invalidate = useInvalidateAccess();
  return useMutation({
    mutationFn: ({ requestId, itemId, ...payload }: { requestId: number; itemId: number } & DecisionPayload) =>
      accessApi.decideItem(requestId, itemId, payload),
    onSuccess: invalidate,
  });
}
