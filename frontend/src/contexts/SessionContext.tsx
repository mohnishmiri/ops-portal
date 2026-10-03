/**
 * SessionContext — the portal authorization gate.
 *
 * Authentication and authorization are two separate controls. MSAL proves
 * *who* the caller is; only the backend can say whether that identity is
 * entitled to the Ops Portal. A valid corporate identity is not portal access.
 *
 * `PortalAccessGate` calls `GET /auth/session` (the one route that is not
 * behind the backend's portal gate, so it can report a denial instead of a
 * bare 403) and renders one of:
 *
 *   • checking        → spinner
 *   • authorized      → children
 *   • not authorized  → Access Denied + sign out
 *   • request failed  → retryable error (never mislabelled as "denied")
 *
 * The gate deliberately sits OUTSIDE SubscriptionProvider and every feature
 * provider, so an unauthorized identity never triggers a subscription,
 * cluster, or cost fetch.
 *
 * Frontend gating is UX only — every protected API enforces authorization
 * server-side regardless of what this component renders.
 */

import React, { createContext, useCallback, useContext, useEffect, ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "../services/apiClient";
import { NO_SUBSCRIPTION_ACCESS_EVENT } from "../services/accessEvents";
import { isDevMode } from "../config/authConfig";
import PortalAccessDenied from "../components/PortalAccessDenied";

// ── Types ─────────────────────────────────────────────────────────────────────

/**
 * Where the user may work: project / app / subscription access.
 *
 * Counts are null for a Super Admin, who is unrestricted.
 */
export interface PortalAccessSummary {
  has_subscription_access: boolean;
  /** Projects this user administers (Project Admin). Empty for a Super Admin. */
  admin_project_ids: number[];
  readable_count?: number | null;
  writable_count?: number | null;
}

export interface PortalSession {
  authenticated: boolean;
  authorized: boolean;
  user?: { user_id: string; display_name: string; email: string };
  roles: string[];
  /** True for both Admin (Project Admin) and Super Admin. */
  is_admin: boolean;
  /** Entra-only role that manages every project and the admin console. */
  is_super_admin?: boolean;
  can_write: boolean;
  /** Upper-cased capability names, e.g. "AKS_POD_DELETE". */
  permissions: string[];
  access?: PortalAccessSummary;
}

interface SessionCtx {
  session: PortalSession | null;
  /** True when the backend granted the named capability. */
  hasCapability: (capability: string) => boolean;
  /** Super Admin — the only role that may open the portal-wide admin console. */
  isSuperAdmin: boolean;
  /**
   * False when the user holds no grant at all, so every module API would
   * answer 403. Always true for a Super Admin.
   */
  hasSubscriptionAccess: boolean;
  /** Projects the user administers as a Project Admin. */
  adminProjectIds: number[];
  /** Re-read /auth/session (after an approval, a revocation, or a "no subscription" 403). */
  refreshSession: () => void;
}

const DEV_SESSION: PortalSession = {
  authenticated: true,
  authorized: true,
  // Mirrors the backend's development bypass user, which is a Super Admin.
  roles: ["super_admin"],
  is_admin: true,
  is_super_admin: true,
  can_write: true,
  permissions: [],
  access: { has_subscription_access: true, admin_project_ids: [], readable_count: null, writable_count: null },
};

/** Derive the access helpers exposed on the context from a session payload. */
export function sessionAccess(session: PortalSession): Pick<SessionCtx, "isSuperAdmin" | "hasSubscriptionAccess" | "adminProjectIds"> {
  const isSuperAdmin = Boolean(session.is_super_admin);
  return {
    isSuperAdmin,
    // A backend that predates project access sends no `access` block; fail
    // open in the UI (the backend still enforces every call) rather than
    // telling every user they have no access.
    hasSubscriptionAccess: isSuperAdmin || (session.access ? Boolean(session.access.has_subscription_access) : true),
    adminProjectIds: session.access?.admin_project_ids ?? [],
  };
}

const DEV_CTX: SessionCtx = {
  session: DEV_SESSION,
  // Dev mode has no backend session to consult — grant everything, matching
  // the backend's development auth bypass.
  hasCapability: () => true,
  ...sessionAccess(DEV_SESSION),
  refreshSession: () => {},
};

const SessionContext = createContext<SessionCtx>(DEV_CTX);

// ── Gate ──────────────────────────────────────────────────────────────────────

const CenteredCard: React.FC<{ children: ReactNode }> = ({ children }) => (
  <div className="min-h-screen bg-gradient-to-br from-att-50 to-att-100 flex items-center justify-center">
    {children}
  </div>
);

export const PortalAccessGate: React.FC<{ children: ReactNode }> = ({ children }) => {
  const queryClient = useQueryClient();
  const { data, isLoading, refetch, isFetching } = useQuery<PortalSession>({
    queryKey: ["auth", "session"],
    queryFn: async () => (await apiClient.get<PortalSession>("/auth/session")).data,
    // A 401 is handled by the apiClient interceptor (silent refresh, then
    // redirect), so retrying here would only duplicate that work.
    retry: 1,
    staleTime: 5 * 60 * 1000,
    refetchOnWindowFocus: false,
    enabled: !isDevMode,
  });

  const refreshSession = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["auth", "session"] });
  }, [queryClient]);

  // A module API refused the call for lack of any subscription: the cached
  // session is stale (e.g. a grant was revoked), so re-read it and let the
  // routes switch to the "request access" panel.
  useEffect(() => {
    if (isDevMode) return undefined;
    window.addEventListener(NO_SUBSCRIPTION_ACCESS_EVENT, refreshSession);
    return () => window.removeEventListener(NO_SUBSCRIPTION_ACCESS_EVENT, refreshSession);
  }, [refreshSession]);

  if (isDevMode) {
    return <SessionContext.Provider value={DEV_CTX}>{children}</SessionContext.Provider>;
  }

  if (isLoading) {
    return (
      <CenteredCard>
        <div className="flex flex-col items-center gap-4">
          <div className="h-10 w-10 border-4 border-att-200 border-t-att-500 rounded-full animate-spin" />
          <p className="text-sm text-gray-600">Checking portal access…</p>
        </div>
      </CenteredCard>
    );
  }

  // Distinguish "we could not determine your access" from "you are denied".
  // Telling an entitled user they are unauthorized because of a transient
  // backend error would be its own kind of outage. A failed *background*
  // refresh keeps the last known session rather than blanking the portal.
  if (!data) {
    return (
      <CenteredCard>
        <div className="bg-white rounded-2xl shadow-xl border border-amber-100 p-10 max-w-md w-full text-center">
          <h2 className="text-xl font-bold text-gray-900 mb-2">Unable to verify access</h2>
          <p className="text-gray-500 text-sm mb-6">
            We couldn't confirm your portal permissions. This is usually temporary.
          </p>
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="px-4 py-2 bg-att-400 text-white rounded-lg text-sm font-semibold hover:bg-att-500 transition disabled:opacity-50"
          >
            {isFetching ? "Retrying…" : "Try again"}
          </button>
        </div>
      </CenteredCard>
    );
  }

  if (!data.authorized) {
    return <PortalAccessDenied email={data.user?.email} />;
  }

  const ctx: SessionCtx = {
    session: data,
    hasCapability: (capability) => data.permissions.includes(capability.toUpperCase()),
    ...sessionAccess(data),
    refreshSession,
  };

  return <SessionContext.Provider value={ctx}>{children}</SessionContext.Provider>;
};

// ── Hook ──────────────────────────────────────────────────────────────────────

export function useSession(): SessionCtx {
  return useContext(SessionContext);
}
