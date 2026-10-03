/**
 * Projects & Apps — Super Admin only.
 *
 * Create projects, add apps (an app is an AppID such as 31599 ATTCC; adding
 * one places matching unplaced subscriptions straight away), appoint or
 * remove Project Admins, and activate / deactivate projects. A deactivated
 * project's subscriptions become visible to Super Admins only.
 */

import React, { Fragment, useState } from "react";
import { SortableHeader, gridStyles } from "../../components/gridStyles";
import { formatAxiosError } from "../../services/apiErrors";
import {
  type AdminProject,
  type PortalUserSummary,
  useAddProjectAdmin,
  useCreateApp,
  useCreateProject,
  useDeleteApp,
  useDeleteProject,
  useRemoveProjectAdmin,
  useUpdateProject,
} from "../../services/accessApi";
import {
  AccessIcons,
  ActionIconButton,
  ConfirmDialog,
  ErrorNote,
  GridHeader,
  GridMessageRow,
  GridPagerBar,
  Modal,
  fieldLabel,
  inputClass,
  panelClass,
  primaryButton,
  secondaryButton,
  textMatches,
  useGridRows,
} from "./accessShared";
import { UserPicker } from "./UserAccessTab";

const sumTier = (project: AdminProject, tier: "prod" | "nonprod") =>
  project.apps.reduce((total, app) => total + (app.subscription_counts?.[tier] ?? 0), 0);

// ── Create project ───────────────────────────────────────────────────────────

const CreateProjectForm: React.FC<{ onNotify: (message: string) => void }> = ({ onNotify }) => {
  const createProject = useCreateProject();
  const [name, setName] = useState("");
  const [projectKey, setProjectKey] = useState("");
  const [description, setDescription] = useState("");

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!name.trim()) return;
    try {
      const created = await createProject.mutateAsync({
        name: name.trim(),
        project_key: projectKey.trim() || undefined,
        description: description.trim() || undefined,
      });
      onNotify(`Project ${created.name} created. Add its apps next.`);
      setName("");
      setProjectKey("");
      setDescription("");
    } catch {
      // Shown below.
    }
  };

  return (
    <section className={panelClass}>
      <h2 className="text-base font-semibold text-gray-800 mb-4">Create project</h2>
      <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-4 gap-3 items-end">
        <div>
          <label htmlFor="project-name" className={fieldLabel}>
            Name <span className="text-red-500">*</span>
          </label>
          <input id="project-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. BDS" className={inputClass} />
        </div>
        <div>
          <label htmlFor="project-key" className={fieldLabel}>
            Key (optional)
          </label>
          <input
            id="project-key"
            value={projectKey}
            onChange={(e) => setProjectKey(e.target.value)}
            placeholder="derived from the name"
            className={inputClass}
          />
        </div>
        <div>
          <label htmlFor="project-description" className={fieldLabel}>
            Description
          </label>
          <input
            id="project-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Brief description"
            className={inputClass}
          />
        </div>
        <button type="submit" disabled={!name.trim() || createProject.isPending} className={primaryButton}>
          {AccessIcons.plus()}
          {createProject.isPending ? "Creating…" : "Create project"}
        </button>
      </form>
      {createProject.isError && (
        <div className="mt-3">
          <ErrorNote message={formatAxiosError(createProject.error, "Failed to create the project")} />
        </div>
      )}
    </section>
  );
};

// ── Dialogs ──────────────────────────────────────────────────────────────────

const AddAppDialog: React.FC<{ project: AdminProject; onClose: (message?: string) => void }> = ({ project, onClose }) => {
  const createApp = useCreateApp();
  const [appCode, setAppCode] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [placeMatching, setPlaceMatching] = useState(true);
  const valid = appCode.trim() !== "" && name.trim() !== "";

  const handleSubmit = async () => {
    if (!valid) return;
    try {
      const created = await createApp.mutateAsync({
        projectId: project.id,
        app_code: appCode.trim(),
        name: name.trim(),
        description: description.trim() || undefined,
        place_matching: placeMatching,
      });
      const placed = created.placed_subscriptions.length;
      onClose(
        `App ${created.name} (${created.app_code}) added to ${project.name}` +
          (placeMatching ? ` — ${placed} matching subscription${placed === 1 ? "" : "s"} placed.` : "."),
      );
    } catch {
      // Shown below.
    }
  };

  return (
    <Modal
      title={`Add app to ${project.name}`}
      subtitle="An app is an AppID, e.g. 31599 ATTCC. Subscriptions named ACC-PROD-31599-ATTCC / ACC-NPRD-31599-ATTCC belong to it."
      onClose={() => onClose()}
      footer={
        <>
          <button type="button" className={secondaryButton} onClick={() => onClose()} disabled={createApp.isPending}>
            Cancel
          </button>
          <button type="button" className={primaryButton} onClick={handleSubmit} disabled={!valid || createApp.isPending}>
            {createApp.isPending ? "Adding…" : "Add app"}
          </button>
        </>
      }
    >
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label htmlFor="app-code" className={fieldLabel}>
            AppID / code <span className="text-red-500">*</span>
          </label>
          <input id="app-code" value={appCode} onChange={(e) => setAppCode(e.target.value)} placeholder="31599" className={inputClass} />
        </div>
        <div>
          <label htmlFor="app-name" className={fieldLabel}>
            Name <span className="text-red-500">*</span>
          </label>
          <input id="app-name" value={name} onChange={(e) => setName(e.target.value)} placeholder="ATTCC" className={inputClass} />
        </div>
      </div>
      <div>
        <label htmlFor="app-description" className={fieldLabel}>
          Description
        </label>
        <input id="app-description" value={description} onChange={(e) => setDescription(e.target.value)} className={inputClass} />
      </div>
      <label className="flex items-start gap-2 text-sm text-gray-700">
        <input type="checkbox" className="mt-1" checked={placeMatching} onChange={(e) => setPlaceMatching(e.target.checked)} />
        <span>
          Place matching subscriptions now
          <span className="block text-xs text-gray-500">
            Unplaced subscriptions whose name carries this AppID move into the app, with the tier taken from the name.
          </span>
        </span>
      </label>
      {createApp.isError && <ErrorNote message={formatAxiosError(createApp.error, "Failed to add the app")} />}
    </Modal>
  );
};

const holdsAdminRole = (user: PortalUserSummary) =>
  user.roles.some((role) => ["admin", "super_admin"].includes(role.toLowerCase()));

const AppointAdminDialog: React.FC<{ project: AdminProject; onClose: (message?: string) => void }> = ({
  project,
  onClose,
}) => {
  const addAdmin = useAddProjectAdmin();
  const [selected, setSelected] = useState<PortalUserSummary[]>([]);
  const [error, setError] = useState<string | null>(null);
  const existing = new Set(project.admins.map((admin) => admin.user_id));

  const handleSubmit = async () => {
    setError(null);
    const appointed: PortalUserSummary[] = [];
    for (const user of selected) {
      try {
        await addAdmin.mutateAsync({ projectId: project.id, userId: user.user_id });
        appointed.push(user);
      } catch (err) {
        // Keep only the people still to do, so a retry does not repeat work.
        const doneIds = new Set(appointed.map((entry) => entry.user_id));
        setSelected((current) => current.filter((entry) => !doneIds.has(entry.user_id)));
        setError(`${user.display_name || user.email}: ${formatAxiosError(err, "Failed to appoint")}`);
        return;
      }
    }
    const names = appointed.map((user) => user.display_name || user.email || user.user_id);
    onClose(`${names.join(", ")} ${names.length === 1 ? "is now an admin" : "are now admins"} of ${project.name}.`);
  };

  return (
    <Modal
      title={`Appoint admins for ${project.name}`}
      subtitle="Project Admins approve requests and grant access for this project only. They need the Ops Portal Admin role in Entra."
      widthClass="max-w-2xl"
      onClose={() => onClose()}
      footer={
        <>
          <button type="button" className={secondaryButton} onClick={() => onClose()} disabled={addAdmin.isPending}>
            Cancel
          </button>
          <button
            type="button"
            className={primaryButton}
            onClick={handleSubmit}
            disabled={selected.length === 0 || addAdmin.isPending}
          >
            {addAdmin.isPending ? "Saving…" : "Appoint"}
          </button>
        </>
      }
    >
      <UserPicker
        label="Admins"
        selected={selected}
        onToggle={(user) =>
          setSelected((current) =>
            current.some((entry) => entry.user_id === user.user_id)
              ? current.filter((entry) => entry.user_id !== user.user_id)
              : [...current, user],
          )
        }
        isDisabled={(user) =>
          existing.has(user.user_id)
            ? "Already an admin of this project"
            : holdsAdminRole(user)
              ? null
              : "Needs the Ops Portal Admin role in Entra (as of their last sign-in)"
        }
      />
      <ErrorNote message={error} />
    </Modal>
  );
};

// ── Projects grid ────────────────────────────────────────────────────────────

type ProjectSortKey = "name" | "apps" | "prod" | "nonprod" | "status";

type PendingConfirm =
  | { kind: "deactivate"; project: AdminProject }
  | { kind: "deleteProject"; project: AdminProject }
  | { kind: "deleteApp"; project: AdminProject; appId: number; appName: string }
  | { kind: "removeAdmin"; project: AdminProject; userId: string; email: string | null };

const ProjectsAppsTab: React.FC<{
  projects: AdminProject[];
  isLoading: boolean;
  error: string | null;
  onNotify: (message: string) => void;
}> = ({ projects, isLoading, error, onNotify }) => {
  const updateProject = useUpdateProject();
  const deleteProject = useDeleteProject();
  const deleteApp = useDeleteApp();
  const removeAdmin = useRemoveProjectAdmin();
  const [expanded, setExpanded] = useState<number | null>(null);
  const [addAppFor, setAddAppFor] = useState<AdminProject | null>(null);
  const [appointFor, setAppointFor] = useState<AdminProject | null>(null);
  const [confirm, setConfirm] = useState<PendingConfirm | null>(null);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const grid = useGridRows<AdminProject, ProjectSortKey>(projects, {
    matches: (project, query) =>
      textMatches(query, project.name, project.project_key, project.description) ||
      project.apps.some((app) => textMatches(query, app.name, app.app_code)) ||
      project.admins.some((admin) => textMatches(query, admin.email, admin.user_id)),
    accessor: (project, key) => {
      switch (key) {
        case "name":
          return project.name;
        case "apps":
          return project.apps.length;
        case "prod":
          return sumTier(project, "prod");
        case "nonprod":
          return sumTier(project, "nonprod");
        case "status":
          return project.is_active ? 1 : 0;
      }
    },
    initialSort: { key: "name", direction: "asc" },
  });
  const header = (label: string, key: ProjectSortKey, center = false) => (
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

  const activate = async (project: AdminProject) => {
    setRowError(null);
    try {
      await updateProject.mutateAsync({ projectId: project.id, is_active: true });
      onNotify(`${project.name} is active again.`);
    } catch (err) {
      setRowError(formatAxiosError(err, "Failed to activate the project"));
    }
  };

  const confirmBusy = updateProject.isPending || deleteProject.isPending || deleteApp.isPending || removeAdmin.isPending;

  const runConfirm = async () => {
    if (!confirm) return;
    setConfirmError(null);
    try {
      if (confirm.kind === "deactivate") {
        await updateProject.mutateAsync({ projectId: confirm.project.id, is_active: false });
        onNotify(`${confirm.project.name} deactivated.`);
      } else if (confirm.kind === "deleteProject") {
        await deleteProject.mutateAsync(confirm.project.id);
        onNotify(`${confirm.project.name} deleted.`);
      } else if (confirm.kind === "deleteApp") {
        await deleteApp.mutateAsync(confirm.appId);
        onNotify(`App ${confirm.appName} deleted.`);
      } else {
        await removeAdmin.mutateAsync({ projectId: confirm.project.id, userId: confirm.userId });
        onNotify(`${confirm.email ?? confirm.userId} is no longer an admin of ${confirm.project.name}.`);
      }
      setConfirm(null);
    } catch (err) {
      setConfirmError(formatAxiosError(err, "The change failed"));
    }
  };

  const confirmCopy = (pending: PendingConfirm): { title: string; message: string; label: string } => {
    switch (pending.kind) {
      case "deactivate":
        return {
          title: `Deactivate ${pending.project.name}?`,
          message:
            "Its subscriptions become visible to Super Admins only and it disappears from the request catalog. Grants are kept and apply again if you reactivate it.",
          label: "Deactivate",
        };
      case "deleteProject":
        return { title: `Delete ${pending.project.name}?`, message: "The project has no apps and will be removed.", label: "Delete" };
      case "deleteApp":
        return {
          title: `Delete app ${pending.appName}?`,
          message: "The app has no subscriptions and will be removed.",
          label: "Delete",
        };
      case "removeAdmin":
        return {
          title: "Remove project admin?",
          message: `${pending.email ?? pending.userId} will no longer administer ${pending.project.name} (their own grants are unchanged).`,
          label: "Remove",
        };
    }
  };

  return (
    <div className="space-y-6">
      <CreateProjectForm onNotify={onNotify} />
      <ErrorNote message={rowError} />

      <div className={gridStyles.shell}>
        <GridHeader
          title="Projects"
          subtitle="Expand a project to see its apps. Subscription counts are per tier."
          search={grid.search}
          onSearch={grid.setSearch}
          placeholder="Search projects, apps, admins…"
        />
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                {header("Project", "name")}
                {header("Apps", "apps", true)}
                {header("Prod subs", "prod", true)}
                {header("Non-Prod subs", "nonprod", true)}
                <th className={gridStyles.headerCell}>Project admins</th>
                {header("Status", "status", true)}
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <GridMessageRow colSpan={7}>Loading projects…</GridMessageRow>
              ) : error ? (
                <GridMessageRow colSpan={7} tone="error">
                  {error}
                </GridMessageRow>
              ) : grid.total === 0 ? (
                <GridMessageRow colSpan={7}>
                  {projects.length === 0 ? "No projects yet. Create one above." : "No projects match the current search."}
                </GridMessageRow>
              ) : (
                grid.pageRows.map((project) => {
                  const isOpen = expanded === project.id;
                  return (
                    <Fragment key={project.id}>
                      <tr className={`${gridStyles.row} ${project.is_active ? "" : "bg-gray-50"}`}>
                        <td className={gridStyles.cell}>
                          <button
                            type="button"
                            onClick={() => setExpanded(isOpen ? null : project.id)}
                            className="flex items-start gap-2 text-left"
                            aria-expanded={isOpen}
                          >
                            <svg
                              className={`mt-0.5 h-4 w-4 shrink-0 text-att-500 transition-transform ${isOpen ? "rotate-90" : ""}`}
                              fill="none"
                              viewBox="0 0 24 24"
                              stroke="currentColor"
                              strokeWidth={2}
                            >
                              <path strokeLinecap="round" strokeLinejoin="round" d="m9 5 7 7-7 7" />
                            </svg>
                            <span>
                              <span className="block font-semibold text-gray-800">{project.name}</span>
                              <span className="block font-mono text-[11px] text-gray-400">{project.project_key}</span>
                              {project.description ? (
                                <span className="block text-xs text-gray-500">{project.description}</span>
                              ) : null}
                            </span>
                          </button>
                        </td>
                        <td className={gridStyles.centerCell}>{project.apps.length}</td>
                        <td className={gridStyles.centerCell}>{sumTier(project, "prod")}</td>
                        <td className={gridStyles.centerCell}>{sumTier(project, "nonprod")}</td>
                        <td className={gridStyles.cell}>
                          {project.admins.length === 0 ? (
                            <span className="text-xs text-gray-400">None — only Super Admins can approve</span>
                          ) : (
                            <div className="flex flex-wrap gap-1">
                              {project.admins.map((admin) => (
                                <span
                                  key={admin.user_id}
                                  className="inline-flex items-center gap-1 rounded-full bg-att-50 px-2 py-0.5 text-xs text-att-800 border border-att-100"
                                >
                                  {admin.email ?? admin.user_id}
                                  <button
                                    type="button"
                                    className="text-att-500 hover:text-red-600"
                                    title="Remove project admin"
                                    aria-label={`Remove ${admin.email ?? admin.user_id} as admin of ${project.name}`}
                                    onClick={() => {
                                      setConfirmError(null);
                                      setConfirm({ kind: "removeAdmin", project, userId: admin.user_id, email: admin.email });
                                    }}
                                  >
                                    ×
                                  </button>
                                </span>
                              ))}
                            </div>
                          )}
                        </td>
                        <td className={gridStyles.centerCell}>
                          <span
                            className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${
                              project.is_active ? "bg-green-100 text-green-700" : "bg-gray-200 text-gray-600"
                            }`}
                          >
                            {project.is_active ? "Active" : "Inactive"}
                          </span>
                        </td>
                        <td className={gridStyles.centerCell}>
                          <div className="flex justify-center gap-1">
                            <ActionIconButton title="Add app" tone="att" onClick={() => setAddAppFor(project)}>
                              {AccessIcons.plus(18)}
                            </ActionIconButton>
                            <ActionIconButton title="Appoint project admin" tone="blue" onClick={() => setAppointFor(project)}>
                              {AccessIcons.userPlus()}
                            </ActionIconButton>
                            <ActionIconButton
                              title={project.is_active ? "Deactivate project" : "Activate project"}
                              tone={project.is_active ? "amber" : "green"}
                              disabled={updateProject.isPending}
                              onClick={() => {
                                if (project.is_active) {
                                  setConfirmError(null);
                                  setConfirm({ kind: "deactivate", project });
                                } else {
                                  activate(project);
                                }
                              }}
                            >
                              {AccessIcons.power()}
                            </ActionIconButton>
                            <ActionIconButton
                              title={project.apps.length > 0 ? "Move or delete the project's apps first" : "Delete project"}
                              tone="red"
                              disabled={project.apps.length > 0}
                              onClick={() => {
                                setConfirmError(null);
                                setConfirm({ kind: "deleteProject", project });
                              }}
                            >
                              {AccessIcons.delete()}
                            </ActionIconButton>
                          </div>
                        </td>
                      </tr>
                      {isOpen && (
                        <tr className="border-t border-att-100 bg-att-50/30">
                          <td colSpan={7} className="px-4 py-3">
                            {project.apps.length === 0 ? (
                              <p className="text-xs text-gray-500">No apps yet. Use “Add app” to create one.</p>
                            ) : (
                              <table className="w-full text-sm">
                                <thead>
                                  <tr className="text-left text-[11px] uppercase tracking-[0.12em] text-att-700">
                                    <th className="py-1.5 pr-3">AppID</th>
                                    <th className="py-1.5 pr-3">App</th>
                                    <th className="py-1.5 pr-3">Description</th>
                                    <th className="py-1.5 pr-3 text-center">Prod</th>
                                    <th className="py-1.5 pr-3 text-center">Non-Prod</th>
                                    <th className="py-1.5 text-center">Actions</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {project.apps.map((app) => {
                                    const subs = (app.subscription_counts?.prod ?? 0) + (app.subscription_counts?.nonprod ?? 0);
                                    return (
                                      <tr key={app.id} className="border-t border-att-100">
                                        <td className="py-1.5 pr-3 font-mono text-xs text-gray-600">{app.app_code}</td>
                                        <td className="py-1.5 pr-3 font-medium text-gray-800">{app.name}</td>
                                        <td className="py-1.5 pr-3 text-xs text-gray-500">{app.description ?? "—"}</td>
                                        <td className="py-1.5 pr-3 text-center">{app.subscription_counts?.prod ?? 0}</td>
                                        <td className="py-1.5 pr-3 text-center">{app.subscription_counts?.nonprod ?? 0}</td>
                                        <td className="py-1.5 text-center">
                                          <ActionIconButton
                                            title={subs > 0 ? "Move the app's subscriptions to another app first" : "Delete app"}
                                            tone="red"
                                            disabled={subs > 0}
                                            onClick={() => {
                                              setConfirmError(null);
                                              setConfirm({ kind: "deleteApp", project, appId: app.id, appName: app.name });
                                            }}
                                          >
                                            {AccessIcons.delete()}
                                          </ActionIconButton>
                                        </td>
                                      </tr>
                                    );
                                  })}
                                </tbody>
                              </table>
                            )}
                          </td>
                        </tr>
                      )}
                    </Fragment>
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
          noun="projects"
        />
      </div>

      {addAppFor && (
        <AddAppDialog
          project={addAppFor}
          onClose={(message) => {
            setAddAppFor(null);
            if (message) onNotify(message);
          }}
        />
      )}
      {appointFor && (
        <AppointAdminDialog
          project={appointFor}
          onClose={(message) => {
            setAppointFor(null);
            if (message) onNotify(message);
          }}
        />
      )}
      {confirm && (
        <ConfirmDialog
          title={confirmCopy(confirm).title}
          message={confirmCopy(confirm).message}
          confirmLabel={confirmCopy(confirm).label}
          busy={confirmBusy}
          error={confirmError}
          onConfirm={runConfirm}
          onCancel={() => setConfirm(null)}
        />
      )}
    </div>
  );
};

export default ProjectsAppsTab;
