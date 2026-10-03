/**
 * ProtectedRoute — wraps a page component with module/page access checks.
 *
 * Usage:
 *   <ProtectedRoute module="aks_operations" page="aks_main">
 *     <AKSOperationsPage />
 *   </ProtectedRoute>
 *
 * While permissions are loading (non-admin users on first render) a spinner
 * is shown rather than immediately denying access, to avoid false positives.
 *
 * Fallback (not admin, permission denied) → renders <AccessDenied />.
 *
 * Subscription access: a module page shows data for the subscriptions the
 * user was granted. With no grant at all every module API answers 403, so a
 * user without subscription access (and not a Super Admin) gets the
 * <NoSubscriptionAccess /> panel pointing at /access instead of a page that
 * loads and fails. This applies to admins too — a Project Admin's access
 * comes from their projects, not from the Entra role.
 *
 * Extending:
 *  Add new module/page names to resource_registry.py on the backend.
 *  The ProtectedRoute checks whatever strings you pass in — no frontend
 *  enum to update.
 */

import React, { ReactNode } from "react";
import { useAuth } from "../contexts/AuthContext";
import { usePermissions } from "../contexts/PermissionsContext";
import { useSession } from "../contexts/SessionContext";
import AccessDenied from "./AccessDenied";
import NoSubscriptionAccess from "./NoSubscriptionAccess";

interface ProtectedRouteProps {
  children: ReactNode;
  /** Module-level access requirement. */
  module?: string;
  /** Page-level access requirement (checked in addition to module). */
  page?: string;
  /** Human-readable label shown in the AccessDenied message. */
  label?: string;
}

const ProtectedRoute: React.FC<ProtectedRouteProps> = ({
  children,
  module,
  page,
  label,
}) => {
  const { isAdmin } = useAuth();
  const { isLoading, canViewModule, canViewPage } = usePermissions();
  const { isSuperAdmin, hasSubscriptionAccess } = useSession();

  // No grant yet → nothing to show on any module page. Checked after the
  // permission check below, so a page the user may never open still says
  // "Access Denied" rather than inviting a request that would not help.
  const noSubscriptions = Boolean(module || page) && !isSuperAdmin && !hasSubscriptionAccess;
  const noSubscriptionsPanel = <NoSubscriptionAccess resourceName={label ?? page ?? module} />;

  // Admins always pass the module/page permission check
  if (isAdmin) return noSubscriptions ? noSubscriptionsPanel : <>{children}</>;

  // While loading permissions, show a neutral spinner
  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[40vh]">
        <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-att-400" />
      </div>
    );
  }

  // Check module access first, then page
  const moduleAllowed = module ? canViewModule(module) : true;
  const pageAllowed = page ? canViewPage(page) : true;

  if (!moduleAllowed || !pageAllowed) {
    return <AccessDenied resourceName={label ?? page ?? module} />;
  }

  if (noSubscriptions) return noSubscriptionsPanel;

  return <>{children}</>;
};

export default ProtectedRoute;
