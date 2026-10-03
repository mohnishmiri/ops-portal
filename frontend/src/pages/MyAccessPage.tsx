/**
 * My Access — every signed-in user.
 *
 * Shows what the user can see and change (grants on projects, apps and
 * subscriptions, Prod / Non-Prod), their access requests with per-line
 * status, and the form to request more. Without any grant every module API
 * answers 403, so this is where a new user lands from the "no access yet"
 * panel.
 */

import React, { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { MetricCard, MetricCardIcons } from "../components/MetricCard";
import { SortableHeader, gridStyles } from "../components/gridStyles";
import TierBadge from "../components/TierBadge";
import Toast, { type ToastState } from "../components/Toast";
import { useSession } from "../contexts/SessionContext";
import { formatAxiosError } from "../services/apiErrors";
import {
  type AccessGrant,
  type AccessRequest,
  isCancellable,
  useAccessCatalog,
  useCancelAccessRequest,
  useMyAccess,
  useMyRequests,
} from "../services/accessApi";
import {
  AccessIcons,
  ActionIconButton,
  ConfirmDialog,
  ErrorNote,
  EveryoneBadge,
  GridHeader,
  GridMessageRow,
  GridPagerBar,
  LEVEL_LABELS,
  LevelBadge,
  StatusBadge,
  countLabel,
  fmtWhen,
  grantTargetLabel,
  secondaryButton,
  textMatches,
  tierLabel,
  useGridRows,
} from "../features/access/accessShared";
import RequestAccessForm from "../features/access/RequestAccessForm";

// ── My grants grid ───────────────────────────────────────────────────────────

type GrantSortKey = "project" | "target" | "tier" | "level" | "subscriptions" | "granted_by" | "created_at";

const grantAccessor = (grant: AccessGrant, key: GrantSortKey): string | number => {
  switch (key) {
    case "project":
      return grant.project_name ?? "";
    case "target":
      return grantTargetLabel(grant);
    case "tier":
      return grant.tier ?? "";
    case "level":
      return grant.level;
    case "subscriptions":
      return grant.subscription_count;
    case "granted_by":
      return grant.granted_by ?? "";
    case "created_at":
      return grant.created_at ?? "";
  }
};

const grantMatches = (grant: AccessGrant, query: string) =>
  textMatches(
    query,
    grant.project_name,
    grantTargetLabel(grant),
    tierLabel(grant.tier),
    grant.level,
    grant.granted_by,
    grant.subject_type === "everyone" ? "everyone" : "you",
  );

const MyGrantsGrid: React.FC<{
  grants: AccessGrant[];
  roleCeiling: "read" | "write";
  isLoading: boolean;
  error: string | null;
  emptyText: string;
}> = ({ grants, roleCeiling, isLoading, error, emptyText }) => {
  const grid = useGridRows<AccessGrant, GrantSortKey>(grants, {
    matches: grantMatches,
    accessor: grantAccessor,
    initialSort: { key: "project", direction: "asc" },
  });
  const header = (label: string, key: GrantSortKey, center = false) => (
    <th className={center ? gridStyles.headerCellCenter : gridStyles.headerCell}>
      <SortableHeader
        label={label}
        active={grid.sort.key === key}
        direction={grid.sort.direction}
        onClick={() => grid.toggleSort(key)}
        align={center ? "center" : "left"}
      />
    </th>
  );

  return (
    <div className={gridStyles.shell}>
      <GridHeader
        title="My access grants"
        subtitle="Projects and apps you can work in. A project grant covers every app in it, including apps added later."
        search={grid.search}
        onSearch={grid.setSearch}
        placeholder="Search grants…"
      />
      <div className="overflow-x-auto">
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              {header("Project", "project")}
              {header("App / Scope", "target")}
              {header("Tier", "tier", true)}
              {header("Level", "level", true)}
              {header("Subscriptions", "subscriptions", true)}
              <th className={gridStyles.headerCell}>Granted to</th>
              {header("Granted by", "granted_by")}
              {header("Granted", "created_at")}
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <GridMessageRow colSpan={8}>Loading your access…</GridMessageRow>
            ) : error ? (
              <GridMessageRow colSpan={8} tone="error">
                {error}
              </GridMessageRow>
            ) : grid.total === 0 ? (
              <GridMessageRow colSpan={8}>
                {grants.length === 0 ? emptyText : "No grants match the current search."}
              </GridMessageRow>
            ) : (
              grid.pageRows.map((grant) => (
                <tr key={grant.id} className={gridStyles.row}>
                  <td className={gridStyles.strongCell}>{grant.project_name ?? "—"}</td>
                  <td className={gridStyles.cell}>{grantTargetLabel(grant)}</td>
                  <td className={gridStyles.centerCell}>
                    <TierBadge tier={grant.tier} emptyLabel={grant.scope_type === "subscription" ? "Single sub" : "—"} />
                  </td>
                  <td className={gridStyles.centerCell}>
                    <LevelBadge level={grant.level} />
                    {grant.level === "write" && roleCeiling === "read" && (
                      <span
                        className="block mt-0.5 text-[10px] text-gray-400"
                        title="Your Entra role is read-only, which caps this grant at read."
                      >
                        effective: {LEVEL_LABELS.read}
                      </span>
                    )}
                  </td>
                  <td className={gridStyles.centerCell}>{grant.subscription_count}</td>
                  <td className={gridStyles.cell}>
                    {grant.subject_type === "everyone" ? <EveryoneBadge /> : <span className="text-gray-600">You</span>}
                  </td>
                  <td className={gridStyles.cell}>{grant.granted_by ?? "—"}</td>
                  <td className={`${gridStyles.cell} whitespace-nowrap`}>{fmtWhen(grant.created_at)}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <GridPagerBar
        page={grid.page}
        totalPages={grid.totalPages}
        total={grid.total}
        pageSize={grid.pageSize}
        onPage={grid.setPage}
        noun="grants"
      />
    </div>
  );
};

// ── My requests grid ─────────────────────────────────────────────────────────

type RequestSortKey = "created_at" | "status" | "lines";

const requestAccessor = (request: AccessRequest, key: RequestSortKey): string | number => {
  if (key === "status") return request.status;
  if (key === "lines") return request.items.length;
  return request.created_at ?? "";
};

const requestMatches = (request: AccessRequest, query: string) =>
  textMatches(query, `#${request.id}`, request.justification, request.status) ||
  request.items.some((item) =>
    textMatches(query, item.project_name, item.app_name, tierLabel(item.tier), item.requested_level, item.status),
  );

export const RequestLines: React.FC<{ request: AccessRequest }> = ({ request }) => (
  <ul className="space-y-1">
    {request.items.map((item) => {
      const decided = item.status === "approved" || item.status === "rejected";
      const decisionTitle = decided
        ? [
            `${item.status === "approved" ? "Approved" : "Rejected"} by ${item.decided_by ?? "an approver"}`,
            item.decided_at ? `on ${fmtWhen(item.decided_at)}` : "",
            item.decision_comment ? `— “${item.decision_comment}”` : "",
          ]
            .filter(Boolean)
            .join(" ")
        : undefined;
      return (
        <li key={item.id} className="flex flex-wrap items-center gap-1.5 text-xs text-gray-700">
          <span className="font-medium text-gray-800">{item.project_name ?? "Project"}</span>
          <span className="text-gray-400">·</span>
          <span>{item.scope_type === "app" ? item.app_name ?? "App" : "All apps"}</span>
          <TierBadge tier={item.tier} />
          <LevelBadge level={item.requested_level} />
          <StatusBadge status={item.status} title={decisionTitle} />
          {item.status === "approved" && item.granted_level && item.granted_level !== item.requested_level && (
            <span className="text-[10px] text-gray-500">granted {LEVEL_LABELS[item.granted_level]}</span>
          )}
          {item.decision_comment && (
            <span className="text-[10px] italic text-gray-500" title={decisionTitle}>
              “{item.decision_comment}”
            </span>
          )}
        </li>
      );
    })}
  </ul>
);

const MyRequestsGrid: React.FC<{
  requests: AccessRequest[];
  isLoading: boolean;
  error: string | null;
  onCancel: (request: AccessRequest) => void;
}> = ({ requests, isLoading, error, onCancel }) => {
  const grid = useGridRows<AccessRequest, RequestSortKey>(requests, {
    matches: requestMatches,
    accessor: requestAccessor,
    initialSort: { key: "created_at", direction: "desc" },
  });
  const header = (label: string, key: RequestSortKey, center = false) => (
    <th className={center ? gridStyles.headerCellCenter : gridStyles.headerCell}>
      <SortableHeader
        label={label}
        active={grid.sort.key === key}
        direction={grid.sort.direction}
        onClick={() => grid.toggleSort(key)}
        align={center ? "center" : "left"}
      />
    </th>
  );

  return (
    <div className={gridStyles.shell}>
      <GridHeader
        title="My requests"
        subtitle="Each line is approved or rejected on its own. A request can be cancelled until someone acts on it."
        search={grid.search}
        onSearch={grid.setSearch}
        placeholder="Search requests…"
      />
      <div className="overflow-x-auto">
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              {header("Submitted", "created_at")}
              {header("Requested lines", "lines")}
              <th className={gridStyles.headerCell}>Justification</th>
              {header("Status", "status", true)}
              <th className={gridStyles.headerCellCenter}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <GridMessageRow colSpan={5}>Loading your requests…</GridMessageRow>
            ) : error ? (
              <GridMessageRow colSpan={5} tone="error">
                {error}
              </GridMessageRow>
            ) : grid.total === 0 ? (
              <GridMessageRow colSpan={5}>
                {requests.length === 0 ? "You have not requested access yet." : "No requests match the current search."}
              </GridMessageRow>
            ) : (
              grid.pageRows.map((request) => (
                <tr key={request.id} className={`${gridStyles.row} align-top`}>
                  <td className={`${gridStyles.cell} whitespace-nowrap`}>
                    <span className="block font-mono text-xs text-gray-400">#{request.id}</span>
                    {fmtWhen(request.created_at)}
                  </td>
                  <td className={gridStyles.cell}>
                    <RequestLines request={request} />
                  </td>
                  <td className={`${gridStyles.cell} max-w-xs`}>
                    <span className="line-clamp-3 text-xs text-gray-600" title={request.justification}>
                      {request.justification}
                    </span>
                  </td>
                  <td className={gridStyles.centerCell}>
                    <StatusBadge status={request.status} />
                  </td>
                  <td className={gridStyles.centerCell}>
                    <div className="flex justify-center gap-1">
                      {isCancellable(request) ? (
                        <ActionIconButton title="Cancel request" tone="red" onClick={() => onCancel(request)}>
                          {AccessIcons.cancel()}
                        </ActionIconButton>
                      ) : (
                        <span className="text-xs text-gray-300">—</span>
                      )}
                    </div>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <GridPagerBar
        page={grid.page}
        totalPages={grid.totalPages}
        total={grid.total}
        pageSize={grid.pageSize}
        onPage={grid.setPage}
        noun="requests"
      />
    </div>
  );
};

// ── Page ─────────────────────────────────────────────────────────────────────

const MyAccessPage: React.FC = () => {
  const me = useMyAccess();
  const catalog = useAccessCatalog();
  const myRequests = useMyRequests();
  const cancelRequest = useCancelAccessRequest();
  const { hasSubscriptionAccess, isSuperAdmin, adminProjectIds, refreshSession } = useSession();
  const [toast, setToast] = useState<ToastState | null>(null);
  const [cancelTarget, setCancelTarget] = useState<AccessRequest | null>(null);
  const closeToast = useCallback(() => setToast(null), []);

  // An approval or revocation since sign-in: bring the cached session (which
  // gates the module pages and the scope picker) in line with what the
  // backend reports now.
  const liveHasAccess = me.data?.has_subscription_access;
  useEffect(() => {
    if (liveHasAccess !== undefined && liveHasAccess !== hasSubscriptionAccess) refreshSession();
  }, [liveHasAccess]);

  const data = me.data;
  const superAdmin = data?.is_super_admin ?? isSuperAdmin;
  const roleCeiling = data?.role_ceiling ?? "read";
  const canManage = superAdmin || adminProjectIds.length > 0 || (data?.admin_projects.length ?? 0) > 0;
  const noAccess = data ? !data.has_subscription_access && !superAdmin : false;
  const meError = me.isError ? formatAxiosError(me.error, "Failed to load your access") : null;

  const form = !superAdmin && (
    <RequestAccessForm
      catalog={catalog.data ?? []}
      catalogLoading={catalog.isLoading}
      catalogError={catalog.isError ? formatAxiosError(catalog.error, "Failed to load projects") : null}
      roleCeiling={roleCeiling}
      onSubmitted={(request) =>
        setToast({
          type: "success",
          message: `Request #${request.id} submitted with ${request.items.length} line${
            request.items.length === 1 ? "" : "s"
          }. Approvers have been notified.`,
        })
      }
    />
  );

  const handleCancel = async () => {
    if (!cancelTarget) return;
    try {
      await cancelRequest.mutateAsync(cancelTarget.id);
      setToast({ type: "success", message: `Request #${cancelTarget.id} cancelled.` });
      setCancelTarget(null);
    } catch {
      // Shown in the dialog.
    }
  };

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
            {AccessIcons.key("h-8 w-8 text-att-500")}
            My Access
          </h1>
          <p className="mt-1 text-sm text-gray-500">
            The projects, apps and subscriptions you can see and change in the Ops Portal, and your access requests.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {!superAdmin && (
            <a href="#request-access" className={secondaryButton}>
              Request access
            </a>
          )}
          {canManage && (
            <Link to="/access/manage" className={secondaryButton}>
              Manage access
            </Link>
          )}
        </div>
      </div>

      {superAdmin && (
        <div className="rounded-xl border border-att-200 bg-att-50 px-4 py-3 text-sm text-att-800">
          You are a <span className="font-semibold">Super Admin</span>: you can see and change every subscription, so you
          never need to request access.
        </div>
      )}
      {noAccess && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          <span className="font-semibold">You don&apos;t have access to any subscription yet.</span> Request access to a
          project or app below — a Project Admin will review it, and you will get an email when they decide.
        </div>
      )}
      {data && data.admin_projects.length > 0 && !superAdmin && (
        <div className="rounded-xl border border-att-100 bg-white px-4 py-3 text-sm text-gray-700">
          You are a Project Admin for{" "}
          <span className="font-semibold">{data.admin_projects.map((p) => p.name).join(", ")}</span>.{" "}
          <Link to="/access/manage" className="font-semibold text-att-600 hover:text-att-700">
            Review requests and grant access →
          </Link>
        </div>
      )}
      <ErrorNote message={meError} />

      {/* KPI cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          title="Readable"
          value={countLabel(data ? data.readable_count : undefined, me.isLoading)}
          subtitle="subscriptions you can view"
          icon={MetricCardIcons.layers()}
          tone="blue"
        />
        <MetricCard
          title="Writable"
          value={countLabel(data ? data.writable_count : undefined, me.isLoading)}
          subtitle={
            roleCeiling === "read" ? "your Entra role is read-only" : "subscriptions you can change"
          }
          icon={MetricCardIcons.shield()}
          tone="emerald"
        />
        <MetricCard
          title="Pending Requests"
          value={me.isLoading ? "…" : data?.pending_requests ?? 0}
          subtitle="awaiting an approver"
          icon={MetricCardIcons.calendar()}
          tone={(data?.pending_requests ?? 0) > 0 ? "amber" : "slate"}
        />
        <MetricCard
          title="Access Grants"
          value={me.isLoading ? "…" : data?.grants.length ?? 0}
          subtitle={`level cap: ${LEVEL_LABELS[roleCeiling]} (Entra role)`}
          icon={MetricCardIcons.checkCircle()}
          tone="att"
        />
      </div>

      {noAccess && form}

      <MyGrantsGrid
        grants={data?.grants ?? []}
        roleCeiling={roleCeiling}
        isLoading={me.isLoading}
        error={meError}
        emptyText={
          superAdmin
            ? "No individual grants — as a Super Admin you already have access to every subscription."
            : "You have no access grants yet. Request access below."
        }
      />

      <MyRequestsGrid
        requests={myRequests.data ?? []}
        isLoading={myRequests.isLoading}
        error={myRequests.isError ? formatAxiosError(myRequests.error, "Failed to load your requests") : null}
        onCancel={(request) => {
          cancelRequest.reset();
          setCancelTarget(request);
        }}
      />

      {!noAccess && form}

      {cancelTarget && (
        <ConfirmDialog
          title={`Cancel request #${cancelTarget.id}?`}
          message={`All ${cancelTarget.items.length} line${
            cancelTarget.items.length === 1 ? "" : "s"
          } of this request will be withdrawn. You can submit a new request at any time.`}
          confirmLabel="Cancel request"
          cancelLabel="Keep request"
          busy={cancelRequest.isPending}
          error={cancelRequest.isError ? formatAxiosError(cancelRequest.error, "Failed to cancel the request") : null}
          onConfirm={handleCancel}
          onCancel={() => setCancelTarget(null)}
        />
      )}

      {toast && <Toast message={toast.message} type={toast.type} onClose={closeToast} />}
    </div>
  );
};

export default MyAccessPage;
