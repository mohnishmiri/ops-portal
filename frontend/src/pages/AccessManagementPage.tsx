/**
 * Access Management — Project Admins (their projects) and Super Admins.
 *
 * Tabs:
 *  • Requests          — approve / reject each requested line.
 *  • User Access       — grant people access; change or revoke grants.
 *  • Projects & Apps   — Super Admin: projects, apps, project admins.
 *  • Subscriptions     — Super Admin: place subscriptions in an app and tier.
 *
 * The active tab lives in `?tab=` so notification emails can deep-link to
 * the queue (`/access/requests` redirects to `?tab=requests`).
 *
 * The route is guarded by AccessAdminRoute; the backend enforces every call
 * (a 403 here carries a readable `detail`, surfaced inline).
 */

import React, { useCallback, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { MetricCard, MetricCardIcons } from "../components/MetricCard";
import Toast, { type ToastState } from "../components/Toast";
import { useSession } from "../contexts/SessionContext";
import { formatAxiosError } from "../services/apiErrors";
import {
  useAdminGrants,
  useAdminProjects,
  useAdminRequests,
  useSubscriptionPlacements,
} from "../services/accessApi";
import { AccessIcons, ErrorNote } from "../features/access/accessShared";
import RequestsQueueTab from "../features/access/RequestsQueueTab";
import UserAccessTab, { TransitionGrantBanner } from "../features/access/UserAccessTab";
import ProjectsAppsTab from "../features/access/ProjectsAppsTab";
import SubscriptionPlacementTab from "../features/access/SubscriptionPlacementTab";

type TabKey = "requests" | "users" | "projects" | "subscriptions";

const TABS: { key: TabKey; label: string; superAdminOnly?: boolean }[] = [
  { key: "requests", label: "Requests" },
  { key: "users", label: "User Access" },
  { key: "projects", label: "Projects & Apps", superAdminOnly: true },
  { key: "subscriptions", label: "Subscriptions", superAdminOnly: true },
];

const AccessManagementPage: React.FC = () => {
  const { isSuperAdmin } = useSession();
  const [params, setParams] = useSearchParams();
  const [toast, setToast] = useState<ToastState | null>(null);
  const notify = useCallback((message: string) => setToast({ type: "success", message }), []);
  const closeToast = useCallback(() => setToast(null), []);

  const tabs = useMemo(() => TABS.filter((tab) => isSuperAdmin || !tab.superAdminOnly), [isSuperAdmin]);
  const requested = params.get("tab") as TabKey | null;
  const activeTab: TabKey = tabs.some((tab) => tab.key === requested) ? (requested as TabKey) : "requests";

  const projects = useAdminProjects();
  const grants = useAdminGrants();
  const pending = useAdminRequests("pending");
  const placements = useSubscriptionPlacements(isSuperAdmin);

  const projectList = projects.data ?? [];
  const grantList = grants.data ?? [];
  const pendingLines = (pending.data ?? []).flatMap((request) => request.items).filter((item) => item.status === "pending");
  const decidable = pendingLines.filter((item) => item.can_decide).length;
  const people = new Set(grantList.filter((grant) => grant.subject_type === "user").map((grant) => grant.subject_id)).size;
  const unplaced = (placements.data ?? []).filter((row) => row.app_id == null).length;
  const projectsError = projects.isError ? formatAxiosError(projects.error, "Failed to load projects") : null;
  const grantsError = grants.isError ? formatAxiosError(grants.error, "Failed to load grants") : null;

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
            {AccessIcons.users("h-8 w-8 text-att-500")}
            Access Management
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            {isSuperAdmin
              ? "Super Admin: every project, app and subscription. Decide requests, grant access, and organise projects."
              : `Project Admin for ${projectList.map((project) => project.name).join(", ") || "your projects"}: decide requests and grant access within your projects.`}
          </p>
        </div>
        <Link
          to="/access"
          className="inline-flex items-center gap-2 px-4 py-2 border border-att-200 bg-white text-att-700 rounded-lg text-sm font-semibold hover:bg-att-50 transition"
        >
          My Access
        </Link>
      </div>

      {/* KPI cards */}
      <div className={`grid grid-cols-1 gap-4 sm:grid-cols-2 ${isSuperAdmin ? "xl:grid-cols-4" : "xl:grid-cols-3"}`}>
        <MetricCard
          title="Pending Requests"
          value={pending.isLoading ? "…" : pendingLines.length}
          subtitle={`${decidable} line${decidable === 1 ? "" : "s"} you can decide`}
          icon={AccessIcons.inbox()}
          tone={decidable > 0 ? "amber" : "slate"}
        />
        <MetricCard
          title={isSuperAdmin ? "Projects" : "Your Projects"}
          value={projects.isLoading ? "…" : projectList.length}
          subtitle={`${projectList.reduce((total, project) => total + project.apps.length, 0)} apps`}
          icon={AccessIcons.folder()}
          tone="att"
        />
        <MetricCard
          title="Access Grants"
          value={grants.isLoading ? "…" : grantList.length}
          subtitle={`${people} ${people === 1 ? "person" : "people"} with direct grants`}
          icon={MetricCardIcons.shield()}
          tone="blue"
        />
        {isSuperAdmin && (
          <MetricCard
            title="Unplaced Subscriptions"
            value={placements.isLoading ? "…" : unplaced}
            subtitle="visible to Super Admins only"
            icon={MetricCardIcons.layers()}
            tone={unplaced > 0 ? "orange" : "emerald"}
          />
        )}
      </div>

      <TransitionGrantBanner grants={grantList} isSuperAdmin={isSuperAdmin} />
      <ErrorNote message={projectsError} />

      {/* Tab bar */}
      <div className="border-b border-gray-200">
        <nav className="flex flex-wrap gap-1" role="tablist" aria-label="Access management sections">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.key}
              onClick={() => setParams(tab.key === "requests" ? {} : { tab: tab.key }, { replace: true })}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? "border-att-400 text-att-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab.label}
              {tab.key === "requests" && decidable > 0 && (
                <span className="ml-2 inline-flex items-center justify-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-semibold text-amber-800">
                  {decidable}
                </span>
              )}
            </button>
          ))}
        </nav>
      </div>

      {activeTab === "requests" && <RequestsQueueTab onNotify={notify} />}
      {activeTab === "users" && (
        <UserAccessTab
          projects={projectList}
          grants={grantList}
          grantsLoading={grants.isLoading}
          grantsError={grantsError}
          isSuperAdmin={isSuperAdmin}
          onNotify={notify}
        />
      )}
      {activeTab === "projects" && isSuperAdmin && (
        <ProjectsAppsTab projects={projectList} isLoading={projects.isLoading} error={projectsError} onNotify={notify} />
      )}
      {activeTab === "subscriptions" && isSuperAdmin && (
        <SubscriptionPlacementTab projects={projectList} onNotify={notify} />
      )}

      {toast && <Toast message={toast.message} type={toast.type} onClose={closeToast} />}
    </div>
  );
};

export default AccessManagementPage;
