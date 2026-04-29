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

export interface EffectivePermissions {
  is_admin: boolean;
  modules: Record<string, string[]>; // resource_name → ["view", "edit"]
  pages: Record<string, string[]>;
}

interface PermissionsCtx {
  isLoading: boolean;
  /** True when the user can navigate to / see a module at all. */
  canViewModule: (moduleName: string) => boolean;
  /** True when the user can view a specific page. */
  canViewPage: (pageName: string) => boolean;
  /** True when the user can perform write actions on a page. */
  canEditPage: (pageName: string) => boolean;
  /** Raw effective permissions from the backend (null while loading). */
  effectivePermissions: EffectivePermissions | null;
}

// ── Defaults (dev mode — full access) ────────────────────────────────────────

const FULL_ACCESS_CTX: PermissionsCtx = {
  isLoading: false,
  canViewModule: () => true,
  canViewPage: () => true,
  canEditPage: () => true,
  effectivePermissions: { is_admin: true, modules: {}, pages: {} },
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
        effectivePermissions: null,
      };
    }

    const { modules, pages } = data;

    return {
      isLoading: false,
      effectivePermissions: data,
      canViewModule: (name) => {
        if (data.is_admin) return true;
        return (modules[name] ?? []).includes("view") || (modules[name] ?? []).includes("edit");
      },
      canViewPage: (name) => {
        if (data.is_admin) return true;
        return (pages[name] ?? []).includes("view") || (pages[name] ?? []).includes("edit");
      },
      canEditPage: (name) => {
        if (data.is_admin) return true;
        return (pages[name] ?? []).includes("edit");
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
