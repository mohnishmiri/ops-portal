/**
 * AuthContext — portal-wide RBAC role awareness.
 *
 * Extracts app roles from the MSAL ID token claims and exposes helpers
 * so any component can check `isAdmin`, `canWrite`, or `hasRole(...)`.
 *
 * In dev mode (no Azure AD credentials) the user is treated as ADMIN
 * so all UI elements remain visible for local development.
 */

import React, { createContext, useContext, useMemo } from "react";
import { useMsal } from "@azure/msal-react";
import { isDevMode } from "../config/authConfig";

// ── Role enum (mirrors backend UserRole) ──────────────────────────────

export type UserRole = "admin" | "write" | "read";

// ── Context shape ─────────────────────────────────────────────────────

interface AuthCtx {
  displayName: string;
  email: string;
  roles: UserRole[];
  isAdmin: boolean;
  canWrite: boolean;
  hasRole: (role: UserRole) => boolean;
}

const defaultCtx: AuthCtx = {
  displayName: "Local Developer",
  email: "dev@localhost",
  roles: ["admin"],
  isAdmin: true,
  canWrite: true,
  hasRole: () => true,
};

const AuthContext = createContext<AuthCtx>(defaultCtx);

// ── Role mapping (matches backend _map_roles) ─────────────────────────

const ROLE_MAP: Record<string, UserRole> = {
  "opsportal.admin": "admin",
  admin: "admin",
  "opsportal.write": "write",
  write: "write",
  contributor: "write",
  "opsportal.read": "read",
  read: "read",
  reader: "read",
};

function mapRoles(rawRoles: string[]): UserRole[] {
  const mapped: UserRole[] = [];
  for (const raw of rawRoles) {
    const role = ROLE_MAP[raw.toLowerCase()];
    if (role && !mapped.includes(role)) {
      mapped.push(role);
    }
  }
  return mapped;
}

// ── Provider ──────────────────────────────────────────────────────────

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const msal = isDevMode ? null : useMsal();
  const account = msal?.instance.getActiveAccount() ?? msal?.accounts?.[0];

  const ctx = useMemo<AuthCtx>(() => {
    if (isDevMode || !account) return defaultCtx;

    // Azure AD embeds app roles in the idTokenClaims.roles array.
    const claims = account.idTokenClaims as Record<string, unknown> | undefined;
    const rawRoles: string[] = Array.isArray(claims?.roles) ? (claims.roles as string[]) : [];
    const roles = mapRoles(rawRoles);

    const isAdmin = roles.includes("admin");
    const canWrite = isAdmin || roles.includes("write");

    return {
      displayName: account.name ?? account.username ?? "",
      email: account.username ?? "",
      roles,
      isAdmin,
      canWrite,
      hasRole: (role: UserRole) => roles.includes(role),
    };
  }, [account]);

  return <AuthContext.Provider value={ctx}>{children}</AuthContext.Provider>;
};

// ── Hook ──────────────────────────────────────────────────────────────

export function useAuth(): AuthCtx {
  return useContext(AuthContext);
}
