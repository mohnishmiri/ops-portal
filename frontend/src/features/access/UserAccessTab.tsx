/**
 * User Access — grant people access directly and review / change / revoke
 * existing grants.
 *
 * Project Admins see and grant only within the projects they administer (the
 * backend filters `/access/admin/projects` and `/access/admin/grants`); Super
 * Admins see everything.
 *
 * The go-live "everyone" transition grant is called out in a banner: while it
 * exists every signed-in user has that access, so individual grants are
 * invisible in practice. Only a Super Admin can change or revoke it.
 */

import React, { useEffect, useMemo, useState } from "react";
import { SortableHeader, gridStyles } from "../../components/gridStyles";
import TierBadge, { TIER_LABELS } from "../../components/TierBadge";
import { formatAxiosError } from "../../services/apiErrors";
import {
  type AccessGrant,
  type AccessLevel,
  type AdminProject,
  type PortalUserSummary,
  type Tier,
  TIERS,
  useAdminUsers,
  useCreateGrants,
  useRevokeGrant,
  useUpdateGrant,
} from "../../services/accessApi";
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
  compactSelectClass,
  describeEveryoneGrants,
  fieldLabel,
  fmtWhen,
  grantTargetLabel,
  inputClass,
  panelClass,
  primaryButton,
  textMatches,
  tierLabel,
  useGridRows,
} from "./accessShared";

const EVERYONE_LOCKED = "Only a Super Admin can change or revoke the transition grant.";

// ── Transition banner ────────────────────────────────────────────────────────

export const TransitionGrantBanner: React.FC<{ grants: AccessGrant[]; isSuperAdmin: boolean }> = ({
  grants,
  isSuperAdmin,
}) => {
  const phrases = describeEveryoneGrants(grants);
  if (phrases.length === 0) return null;
  return (
    <div className="rounded-xl border-2 border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900" role="alert">
      <div className="flex items-start gap-3">
        <svg className="h-5 w-5 shrink-0 text-amber-600 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0ZM12 9v4M12 17h.01" />
        </svg>
        <div>
          <p>
            <span className="font-semibold">Transition grant active</span> — every signed-in user has{" "}
            {phrases.join("; ")}. Remove it once individual access is set up, and before onboarding another project.
          </p>
          <p className="mt-1 text-xs text-amber-800">
            {isSuperAdmin
              ? "Revoke the rows marked Everyone in the grants table below."
              : "Only a Super Admin can revoke it."}
          </p>
        </div>
      </div>
    </div>
  );
};

// ── Grant form ───────────────────────────────────────────────────────────────

function useDebounced<T>(value: T, delayMs = 250): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(timer);
  }, [value, delayMs]);
  return debounced;
}

const canHoldWrite = (user: PortalUserSummary) =>
  user.roles.some((role) => ["write", "admin", "super_admin"].includes(role.toLowerCase()));

export const UserPicker: React.FC<{
  selected: PortalUserSummary[];
  onToggle: (user: PortalUserSummary) => void;
  isDisabled?: (user: PortalUserSummary) => string | null;
  label?: string;
}> = ({ selected, onToggle, isDisabled, label = "People" }) => {
  const [query, setQuery] = useState("");
  const debounced = useDebounced(query);
  const users = useAdminUsers(debounced);
  const selectedIds = new Set(selected.map((user) => user.user_id));

  return (
    <div>
      <label htmlFor="user-picker-search" className={fieldLabel}>
        {label} <span className="text-red-500">*</span>
      </label>
      <input
        id="user-picker-search"
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search by name or email — only people who have signed in are listed"
        className={inputClass}
      />
      {selected.length > 0 && (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {selected.map((user) => (
            <span
              key={user.user_id}
              className="inline-flex items-center gap-1 rounded-full bg-att-100 px-2.5 py-1 text-xs font-medium text-att-800"
            >
              {user.display_name || user.email || user.user_id}
              <button
                type="button"
                onClick={() => onToggle(user)}
                className="text-att-600 hover:text-att-900"
                aria-label={`Remove ${user.display_name || user.email}`}
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="mt-2 max-h-48 overflow-y-auto rounded-lg border border-att-100 divide-y divide-att-50">
        {users.isLoading ? (
          <p className="px-3 py-3 text-xs text-gray-400">Searching…</p>
        ) : users.isError ? (
          <p className="px-3 py-3 text-xs text-red-600">{formatAxiosError(users.error, "Failed to load users")}</p>
        ) : (users.data ?? []).length === 0 ? (
          <p className="px-3 py-3 text-xs text-gray-400">No one matches. People appear here after their first sign-in.</p>
        ) : (
          (users.data ?? []).map((user) => {
            const disabledReason = isDisabled?.(user) ?? null;
            return (
              <label
                key={user.user_id}
                title={disabledReason ?? undefined}
                className={`flex items-center gap-3 px-3 py-2 text-sm ${
                  disabledReason ? "opacity-50 cursor-not-allowed" : "cursor-pointer hover:bg-att-50/60"
                }`}
              >
                <input
                  type="checkbox"
                  checked={selectedIds.has(user.user_id)}
                  disabled={Boolean(disabledReason)}
                  onChange={() => onToggle(user)}
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium text-gray-800">{user.display_name || user.email}</span>
                  <span className="block truncate text-xs text-gray-500">{user.email}</span>
                </span>
                <span className="flex flex-wrap justify-end gap-1">
                  {user.roles.map((role) => (
                    <span key={role} className="rounded bg-purple-100 px-1.5 py-0.5 text-[10px] font-semibold text-purple-700">
                      {role}
                    </span>
                  ))}
                </span>
              </label>
            );
          })
        )}
      </div>
    </div>
  );
};

const GrantAccessForm: React.FC<{ projects: AdminProject[]; onNotify: (message: string) => void }> = ({
  projects,
  onNotify,
}) => {
  const createGrants = useCreateGrants();
  const [users, setUsers] = useState<PortalUserSummary[]>([]);
  const [scopeType, setScopeType] = useState<"project" | "app">("project");
  const [projectId, setProjectId] = useState<number | "">("");
  const [appId, setAppId] = useState<number | "">("");
  const [tiers, setTiers] = useState<Tier[]>([]);
  const [level, setLevel] = useState<AccessLevel>("read");

  const activeProjects = projects.filter((project) => project.is_active);
  const target = scopeType === "project" ? projectId : appId;
  const readOnlyUsers = users.filter((user) => !canHoldWrite(user));
  const canSubmit = users.length > 0 && target !== "" && tiers.length > 0 && !createGrants.isPending;

  const toggleUser = (user: PortalUserSummary) =>
    setUsers((current) =>
      current.some((entry) => entry.user_id === user.user_id)
        ? current.filter((entry) => entry.user_id !== user.user_id)
        : [...current, user],
    );

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    try {
      const created = await createGrants.mutateAsync({
        user_ids: users.map((user) => user.user_id),
        scope_type: scopeType,
        ...(scopeType === "project" ? { project_id: Number(projectId) } : { app_id: Number(appId) }),
        tiers: TIERS.filter((tier) => tiers.includes(tier)),
        level,
      });
      onNotify(`Saved ${created.length} grant${created.length === 1 ? "" : "s"} for ${users.length} ${users.length === 1 ? "person" : "people"}.`);
      setUsers([]);
      setTiers([]);
    } catch {
      // Shown below.
    }
  };

  return (
    <section className={panelClass}>
      <h2 className="text-base font-semibold text-gray-800">Grant access</h2>
      <p className="text-xs text-gray-500 mt-0.5 mb-4">
        One grant is created per person per tier. A project grant covers all its apps, including apps added later.
      </p>
      <form onSubmit={handleSubmit} className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <UserPicker selected={users} onToggle={toggleUser} />

        <div className="space-y-4">
          <fieldset>
            <legend className={fieldLabel}>Grant on</legend>
            <div className="flex gap-4 py-1">
              {(["project", "app"] as const).map((value) => (
                <label key={value} className="inline-flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                  <input
                    type="radio"
                    name="grant-scope"
                    checked={scopeType === value}
                    onChange={() => setScopeType(value)}
                  />
                  {value === "project" ? "Whole project" : "Single app"}
                </label>
              ))}
            </div>
          </fieldset>

          {scopeType === "project" ? (
            <div>
              <label htmlFor="grant-project" className={fieldLabel}>
                Project <span className="text-red-500">*</span>
              </label>
              <select
                id="grant-project"
                value={projectId}
                onChange={(event) => setProjectId(event.target.value ? Number(event.target.value) : "")}
                className={inputClass}
              >
                <option value="">— select project —</option>
                {activeProjects.map((project) => (
                  <option key={project.id} value={project.id}>
                    {project.name}
                  </option>
                ))}
              </select>
            </div>
          ) : (
            <div>
              <label htmlFor="grant-app" className={fieldLabel}>
                App <span className="text-red-500">*</span>
              </label>
              <select
                id="grant-app"
                value={appId}
                onChange={(event) => setAppId(event.target.value ? Number(event.target.value) : "")}
                className={inputClass}
              >
                <option value="">— select app —</option>
                {activeProjects
                  .filter((project) => project.apps.length > 0)
                  .map((project) => (
                    <optgroup key={project.id} label={project.name}>
                      {project.apps.map((app) => (
                        <option key={app.id} value={app.id}>
                          {app.name} ({app.app_code})
                        </option>
                      ))}
                    </optgroup>
                  ))}
              </select>
            </div>
          )}

          <div className="grid grid-cols-2 gap-4">
            <fieldset>
              <legend className={fieldLabel}>
                Tiers <span className="text-red-500">*</span>
              </legend>
              <div className="flex gap-4 py-2">
                {TIERS.map((tier) => (
                  <label key={tier} className="inline-flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                    <input
                      type="checkbox"
                      checked={tiers.includes(tier)}
                      onChange={() =>
                        setTiers((current) =>
                          current.includes(tier) ? current.filter((t) => t !== tier) : [...current, tier],
                        )
                      }
                    />
                    {TIER_LABELS[tier]}
                  </label>
                ))}
              </div>
            </fieldset>
            <div>
              <label htmlFor="grant-level" className={fieldLabel}>
                Level
              </label>
              <select
                id="grant-level"
                value={level}
                onChange={(event) => setLevel(event.target.value as AccessLevel)}
                className={inputClass}
              >
                <option value="read">Read — view data</option>
                <option value="write">Write — make changes</option>
              </select>
            </div>
          </div>

          {level === "write" && readOnlyUsers.length > 0 && (
            <p className="text-xs text-amber-700">
              {readOnlyUsers.map((user) => user.display_name || user.email).join(", ")}{" "}
              {readOnlyUsers.length === 1 ? "has" : "have"} a read-only Entra role, so the grant will only let them read.
            </p>
          )}
          {activeProjects.length === 0 && (
            <p className="text-xs text-gray-500">There are no active projects you can grant access to.</p>
          )}
          {createGrants.isError && <ErrorNote message={formatAxiosError(createGrants.error, "Failed to grant access")} />}

          <button type="submit" disabled={!canSubmit} className={primaryButton}>
            {createGrants.isPending ? "Granting…" : "Grant access"}
          </button>
        </div>
      </form>
    </section>
  );
};

// ── Grants grid ──────────────────────────────────────────────────────────────

type GrantSortKey = "subject" | "project" | "target" | "tier" | "level" | "subscriptions" | "granted_by" | "created_at";

const subjectLabel = (grant: AccessGrant) =>
  grant.subject_type === "everyone" ? "Everyone" : grant.subject_email ?? grant.subject_id;

const grantAccessor = (grant: AccessGrant, key: GrantSortKey): string | number => {
  switch (key) {
    case "subject":
      return subjectLabel(grant);
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
    subjectLabel(grant),
    grant.project_name,
    grantTargetLabel(grant),
    tierLabel(grant.tier),
    grant.level,
    grant.granted_by,
  );

const GrantsGrid: React.FC<{
  grants: AccessGrant[];
  projects: AdminProject[];
  isSuperAdmin: boolean;
  isLoading: boolean;
  error: string | null;
  onNotify: (message: string) => void;
}> = ({ grants, projects, isSuperAdmin, isLoading, error, onNotify }) => {
  const updateGrant = useUpdateGrant();
  const revokeGrant = useRevokeGrant();
  const [projectFilter, setProjectFilter] = useState<number | "">("");
  const [userFilter, setUserFilter] = useState("");
  const [revokeTarget, setRevokeTarget] = useState<AccessGrant | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const subjects = useMemo(() => {
    const map = new Map<string, string>();
    grants.forEach((grant) => map.set(`${grant.subject_type}:${grant.subject_id}`, subjectLabel(grant)));
    return Array.from(map.entries()).sort((a, b) => a[1].localeCompare(b[1]));
  }, [grants]);

  const filtered = useMemo(
    () =>
      grants.filter(
        (grant) =>
          (projectFilter === "" || grant.project_id === projectFilter) &&
          (userFilter === "" || `${grant.subject_type}:${grant.subject_id}` === userFilter),
      ),
    [grants, projectFilter, userFilter],
  );

  const grid = useGridRows<AccessGrant, GrantSortKey>(filtered, {
    matches: grantMatches,
    accessor: grantAccessor,
    initialSort: { key: "subject", direction: "asc" },
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

  const changeLevel = async (grant: AccessGrant, level: AccessLevel) => {
    setRowError(null);
    try {
      await updateGrant.mutateAsync({ grantId: grant.id, level });
      onNotify(`${subjectLabel(grant)} now has ${LEVEL_LABELS[level].toLowerCase()} access to ${grant.project_name ?? "the project"} ${tierLabel(grant.tier)}.`);
    } catch (err) {
      setRowError(formatAxiosError(err, "Failed to change the level"));
    }
  };

  const handleRevoke = async () => {
    if (!revokeTarget) return;
    try {
      await revokeGrant.mutateAsync(revokeTarget.id);
      onNotify(`Revoked ${subjectLabel(revokeTarget)}'s access to ${revokeTarget.project_name ?? "the project"} ${tierLabel(revokeTarget.tier)}.`);
      setRevokeTarget(null);
    } catch {
      // Shown in the dialog.
    }
  };

  return (
    <div className="space-y-2">
      <ErrorNote message={rowError} />
      <div className={gridStyles.shell}>
        <GridHeader
          title="Access grants"
          subtitle={`${filtered.length} grant${filtered.length === 1 ? "" : "s"}`}
          search={grid.search}
          onSearch={grid.setSearch}
          placeholder="Search grants…"
        >
          <label className="sr-only" htmlFor="grant-project-filter">
            Project
          </label>
          <select
            id="grant-project-filter"
            value={projectFilter}
            onChange={(event) => {
              setProjectFilter(event.target.value ? Number(event.target.value) : "");
              grid.setPage(0);
            }}
            className={compactSelectClass}
          >
            <option value="">All projects</option>
            {projects.map((project) => (
              <option key={project.id} value={project.id}>
                {project.name}
              </option>
            ))}
          </select>
          <label className="sr-only" htmlFor="grant-user-filter">
            User
          </label>
          <select
            id="grant-user-filter"
            value={userFilter}
            onChange={(event) => {
              setUserFilter(event.target.value);
              grid.setPage(0);
            }}
            className={`${compactSelectClass} max-w-[14rem]`}
          >
            <option value="">All users</option>
            {subjects.map(([key, label]) => (
              <option key={key} value={key}>
                {label}
              </option>
            ))}
          </select>
        </GridHeader>
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                {header("User", "subject")}
                {header("Project", "project")}
                {header("App / Scope", "target")}
                {header("Tier", "tier", true)}
                {header("Level", "level", true)}
                {header("Subs", "subscriptions", true)}
                {header("Granted by", "granted_by")}
                {header("Granted", "created_at")}
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <GridMessageRow colSpan={9}>Loading grants…</GridMessageRow>
              ) : error ? (
                <GridMessageRow colSpan={9} tone="error">
                  {error}
                </GridMessageRow>
              ) : grid.total === 0 ? (
                <GridMessageRow colSpan={9}>
                  {grants.length === 0 ? "No access has been granted yet." : "No grants match the current filters."}
                </GridMessageRow>
              ) : (
                grid.pageRows.map((grant) => {
                  const locked = grant.subject_type === "everyone" && !isSuperAdmin;
                  return (
                    <tr
                      key={grant.id}
                      className={`${gridStyles.row} ${grant.subject_type === "everyone" ? "bg-amber-50/60" : ""}`}
                    >
                      <td className={gridStyles.cell}>
                        {grant.subject_type === "everyone" ? (
                          <EveryoneBadge />
                        ) : (
                          <span className="font-medium text-gray-800">{grant.subject_email ?? grant.subject_id}</span>
                        )}
                      </td>
                      <td className={gridStyles.strongCell}>{grant.project_name ?? "—"}</td>
                      <td className={gridStyles.cell}>{grantTargetLabel(grant)}</td>
                      <td className={gridStyles.centerCell}>
                        <TierBadge tier={grant.tier} emptyLabel={grant.scope_type === "subscription" ? "Single sub" : "—"} />
                      </td>
                      <td className={gridStyles.centerCell}>
                        <select
                          aria-label={`Level for ${subjectLabel(grant)}`}
                          value={grant.level}
                          disabled={locked || updateGrant.isPending}
                          title={locked ? EVERYONE_LOCKED : "Change level"}
                          onChange={(event) => changeLevel(grant, event.target.value as AccessLevel)}
                          className={compactSelectClass}
                        >
                          <option value="read">Read</option>
                          <option value="write">Write</option>
                        </select>
                      </td>
                      <td className={gridStyles.centerCell}>{grant.subscription_count}</td>
                      <td className={gridStyles.cell}>
                        {grant.granted_by ?? "—"}
                        {grant.request_item_id ? <span className="block text-[10px] text-gray-400">via request</span> : null}
                      </td>
                      <td className={`${gridStyles.cell} whitespace-nowrap`}>{fmtWhen(grant.created_at)}</td>
                      <td className={gridStyles.centerCell}>
                        <div className="flex justify-center gap-1">
                          <ActionIconButton
                            title={locked ? EVERYONE_LOCKED : "Revoke grant"}
                            tone="red"
                            disabled={locked}
                            onClick={() => {
                              revokeGrant.reset();
                              setRevokeTarget(grant);
                            }}
                          >
                            {AccessIcons.delete()}
                          </ActionIconButton>
                        </div>
                      </td>
                    </tr>
                  );
                })
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

      {revokeTarget && (
        <ConfirmDialog
          title="Revoke access?"
          message={
            revokeTarget.subject_type === "everyone" ? (
              <>
                This removes the <span className="font-semibold">transition grant</span>:{" "}
                every signed-in user without their own grant loses {revokeTarget.level} access to{" "}
                {revokeTarget.project_name} {tierLabel(revokeTarget.tier)} immediately.
              </>
            ) : (
              <>
                <span className="font-semibold">{revokeTarget.subject_email ?? revokeTarget.subject_id}</span> will lose{" "}
                {revokeTarget.level} access to {revokeTarget.project_name} · {grantTargetLabel(revokeTarget)}{" "}
                {tierLabel(revokeTarget.tier)} ({revokeTarget.subscription_count} subscription
                {revokeTarget.subscription_count === 1 ? "" : "s"}) immediately.
              </>
            )
          }
          confirmLabel="Revoke"
          busy={revokeGrant.isPending}
          error={revokeGrant.isError ? formatAxiosError(revokeGrant.error, "Failed to revoke the grant") : null}
          onConfirm={handleRevoke}
          onCancel={() => setRevokeTarget(null)}
        />
      )}
    </div>
  );
};

// ── Tab ──────────────────────────────────────────────────────────────────────

/**
 * The transition banner is rendered by the page above the tab bar, so it stays
 * in view on every tab (including this one) — see AccessManagementPage.
 */
const UserAccessTab: React.FC<{
  projects: AdminProject[];
  grants: AccessGrant[];
  grantsLoading: boolean;
  grantsError: string | null;
  isSuperAdmin: boolean;
  onNotify: (message: string) => void;
}> = ({ projects, grants, grantsLoading, grantsError, isSuperAdmin, onNotify }) => (
  <div className="space-y-6">
    <GrantAccessForm projects={projects} onNotify={onNotify} />
    <GrantsGrid
      grants={grants}
      projects={projects}
      isSuperAdmin={isSuperAdmin}
      isLoading={grantsLoading}
      error={grantsError}
      onNotify={onNotify}
    />
  </div>
);

export default UserAccessTab;
