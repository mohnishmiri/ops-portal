/**
 * Role-gated route wrappers for pages that are not module/page-permission
 * records (so they cannot go through ProtectedRoute).
 *
 *  • SuperAdminRoute  — the portal-wide admin console (`/admin`,
 *    `/admin/permissions`). The backend now requires the Entra Super Admin
 *    role for every admin-console API; a Project Admin (Entra Admin role)
 *    administers only their projects, from Access Management.
 *  • AccessAdminRoute — Access Management (`/access/manage`): Super Admins,
 *    and Admins a Super Admin has assigned to at least one project.
 *
 * Both say *why* access was refused rather than silently redirecting, which
 * would read as a broken link. Role facts come from the backend session
 * (`/auth/session`), not the ID token. Frontend gating is UX only — the
 * backend authorizes every call regardless.
 */

import React, { ReactNode } from "react";
import { Link } from "react-router-dom";
import { useSession } from "../contexts/SessionContext";
import AccessDenied from "./AccessDenied";

export const SuperAdminRoute: React.FC<{ children: ReactNode; label: string }> = ({ children, label }) => {
  const { isSuperAdmin, adminProjectIds } = useSession();
  if (isSuperAdmin) return <>{children}</>;
  return (
    <AccessDenied
      resourceName={label}
      reason={
        adminProjectIds.length > 0 ? (
          <>
            The portal-wide admin console is limited to Super Admins. As a Project Admin you manage your projects from{" "}
            <Link to="/access/manage" className="font-semibold text-att-600 hover:text-att-700">
              Access Management
            </Link>
            .
          </>
        ) : (
          "The portal-wide admin console is limited to Super Admins (an Entra-only role)."
        )
      }
    />
  );
};

export const AccessAdminRoute: React.FC<{ children: ReactNode; label: string }> = ({ children, label }) => {
  const { isSuperAdmin, adminProjectIds } = useSession();
  if (isSuperAdmin || adminProjectIds.length > 0) return <>{children}</>;
  return (
    <AccessDenied
      resourceName={label}
      reason={
        <>
          Access Management is for Project Admins and Super Admins. To get access to a project, use{" "}
          <Link to="/access" className="font-semibold text-att-600 hover:text-att-700">
            My Access
          </Link>
          .
        </>
      }
    />
  );
};
