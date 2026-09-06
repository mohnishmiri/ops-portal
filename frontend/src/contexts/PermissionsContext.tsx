/**
 * PermissionsContext — module/page access awareness.
 *
 * Fetches the current user's effective permissions from the backend
 * (/api/v1/auth/my-permissions) and exposes helper functions that any
 * component can call to check access before rendering or navigating.
 *
 * Design:
 *  • Admin users: backend returns is_admin=true → all checks return true.
 *  • Non-admin:   backend returns a map of resource_name → permission list.
 *  • Module access is inherited by child pages (backend already handles this).
 *  • In dev mode the default context grants full access (mirrors the auth bypass).
 *
 * Extending:
 *  To add a new module/page, register it in the backend resource_registry.py.
 *  The frontend will automatically reflect the new entry once the backend seeds it.
 */

import React, {
  createContext,
  useContext,
  useMemo,
  ReactNode,
} from "react";
import { useQuery } from "@tanstack/react-query";
import apiClient from "../services/apiClient";
import { isDevMode } from "../config/authConfig";
import { useAuth } from "./AuthContext";

// ── Types ─────────────────────────────────────────────────────────────────────

/** Per-resource permission map: env_scope → list of permission types */
export type EnvScopedPerms = Record<string, string[]>;

export interface EffectivePermissions {
  is_admin: boolean;
  modules: Record<string, EnvScopedPerms>; // resource_name → { env_scope: ["view","edit"] }
  pages: Record<string, EnvScopedPerms>;
  teams?: string[];
  /** Upper-cased operation capabilities, e.g. ["AKS_POD_DELETE"]. */
  capabilities?: string[];
}

interface PermissionsCtx {
  isLoading: boolean;
  /** True when the user can navigate to / see a module at all. */
  canViewModule: (moduleName: string) => boolean;
  /** True when the user can view a specific page. */
  canViewPage: (pageName: string) => boolean;
  /** True when the user can perform write actions on a page (any environment). */
  canEditPage: (pageName: string) => boolean;
  /** True when the user can perform write actions for a specific environment. */
  canEditPageForEnv: (pageName: string, environment: string) => boolean;
  /**
   * True when the backend granted the named operation capability
   * (e.g. "AKS_POD_DELETE"). Case-insensitive.
   *
   * Use this to hide destructive actions the user cannot perform. Hiding is
   * a UX affordance only — the backend independently authorizes every
   * protected operation, so a hidden button is not a security control.
   */
  hasCapability: (capability: string) => boolean;
  /** Raw effective permissions from the backend (null while loading). */
  effectivePermissions: EffectivePermissions | null;
}

// ── Defaults (dev mode — full access) ────────────────────────────────────────

const FULL_ACCESS_CTX: PermissionsCtx = {
  isLoading: false,
  canViewModule: () => true,
  canViewPage: () => true,
  canEditPage: () => true,
  canEditPageForEnv: () => true,
  hasCapability: () => true,
  effectivePermissions: { is_admin: true, modules: {}, pages: {}, teams: [], capabilities: [] },
};

const PermissionsContext = createContext<PermissionsCtx>(FULL_ACCESS_CTX);

// ── Provider ──────────────────────────────────────────────────────────────────

export const PermissionsProvider: React.FC<{ children: ReactNode }> = ({ children }) => {
  const { isAdmin } = useAuth();

  const { data, isLoading } = useQuery<EffectivePermissions>({
    queryKey: ["auth", "my-permissions"],
    queryFn: async () => {
      const resp = await apiClient.get<EffectivePermissions>("/auth/my-permissions");
      return resp.data;
    },
    // Refresh every 5 minutes — permissions rarely change mid-session
    staleTime: 5 * 60 * 1000,
    // Don't spam the server on every window focus
    refetchOnWindowFocus: false,
    // If dev mode or MSAL hasn't authenticated yet, skip the fetch
    enabled: !isDevMode,
  });

  const ctx = useMemo<PermissionsCtx>(() => {
    // Dev mode — bypass all checks
    if (isDevMode) return FULL_ACCESS_CTX;

    // Admin always passes — no need to check permission records
    if (isAdmin) return FULL_ACCESS_CTX;

    if (isLoading || !data) {
      return {
        isLoading: true,
        canViewModule: () => false,
        canViewPage: () => false,
        canEditPage: () => false,
        canEditPageForEnv: () => false,
        hasCapability: () => false,
        effectivePermissions: null,
      };
    }

    const { modules, pages } = data;

    /** Check if a resource has a given perm across any environment scope. */
    const hasPermAnyEnv = (scopedPerms: EnvScopedPerms | undefined, perm: string): boolean => {
      if (!scopedPerms) return false;
      return Object.values(scopedPerms).some((perms) => perms.includes(perm));
    };

    /** Check if a resource has a given perm for a specific environment. */
    const hasPermForEnv = (scopedPerms: EnvScopedPerms | undefined, perm: string, env: string): boolean => {
      if (!scopedPerms) return false;
      // 'all' scope always applies
      if (scopedPerms["all"]?.includes(perm)) return true;
      // Check specific env scope
      return scopedPerms[env]?.includes(perm) ?? false;
    };

    const capabilities = new Set((data.capabilities ?? []).map((c) => c.toUpperCase()));

    return {
      isLoading: false,
      effectivePermissions: data,
      hasCapability: (capability) => {
        if (data.is_admin) return true;
        return capabilities.has(capability.toUpperCase());
      },
      canViewModule: (name) => {
        if (data.is_admin) return true;
        return hasPermAnyEnv(modules[name], "view") || hasPermAnyEnv(modules[name], "edit");
      },
      canViewPage: (name) => {
        if (data.is_admin) return true;
        return hasPermAnyEnv(pages[name], "view") || hasPermAnyEnv(pages[name], "edit");
      },
      canEditPage: (name) => {
        if (data.is_admin) return true;
        return hasPermAnyEnv(pages[name], "edit");
      },
      canEditPageForEnv: (name, env) => {
        if (data.is_admin) return true;
        return hasPermForEnv(pages[name], "edit", env);
      },
    };
  }, [isAdmin, isLoading, data]);

  return (
    <PermissionsContext.Provider value={ctx}>
      {children}
    </PermissionsContext.Provider>
  );
};

// ── Hook ──────────────────────────────────────────────────────────────────────

export function usePermissions(): PermissionsCtx {
  return useContext(PermissionsContext);
}
