/**
 * PermissionsManagement — admin UI for module/page access control.
 *
 * Three tabs:
 *  1. Resources  — view all modules/pages, create custom ones, delete non-system
 *  2. Permissions — grant / revoke access (role or user) on any resource
 *  3. Matrix     — quick-glance view: which roles can access what
 *
 * Extending:
 *  • To add a new built-in module/page, add it to backend resource_registry.py.
 *    It will appear in the Resources tab on next startup.
 *  • Custom resources can also be created from this UI.
 */

import React, { useState } from "react";
import {
  useResources,
  usePermissions,
  useCreateResource,
  useCreatePermission,
  useDeleteResource,
  useDeletePermission,
  ResourceItem,
  PermissionItem,
} from "../../services/permissionsApi";

// ── Resource display-name mapping ─────────────────────────────────────────────

const RESOURCE_LABELS: Record<string, { label: string; description: string }> = {
  // Modules
  cost_management:   { label: "Cost Management",    description: "FinOps, cost analytics & financial intelligence" },
  aks_operations:    { label: "AKS Operations",     description: "Kubernetes cluster & workload management" },
  compliance:        { label: "Compliance",          description: "Compliance scoring & configuration drift" },
  keyvault:          { label: "Key Vault",           description: "Secrets, keys & certificate lifecycle" },
  infra_alerts:      { label: "Infra Alerts",        description: "Infrastructure alerting & threshold monitoring" },
  admin:             { label: "Admin Panel",         description: "System administration — subscriptions, config & access control" },
  // Pages
  leadership_dashboard: { label: "Leadership Dashboard", description: "Cost KPIs, advisor & executive summary" },
  amortized_costs:      { label: "Amortized Costs",      description: "Amortized cost breakdown & trend analysis" },
  aks_main:             { label: "AKS Main",             description: "AKS cluster overview & workload management" },
  compliance_main:      { label: "Compliance Dashboard",  description: "Compliance score & drift history" },
  keyvault_main:        { label: "Key Vault Dashboard",   description: "Key Vault inventory & expiry tracking" },
  infra_alerts_main:    { label: "Infra Alerts Dashboard",description: "Infrastructure alert feed & thresholds" },
  admin_dashboard:      { label: "Admin Dashboard",       description: "Subscription management, system health & configuration" },
  admin_permissions:    { label: "Access Management",     description: "Module/page-level RBAC and role/user permission management" },
};

const getLabel = (name: string): string =>
  RESOURCE_LABELS[name]?.label ?? name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

const getDesc = (name: string, fallback?: string | null): string =>
  RESOURCE_LABELS[name]?.description ?? fallback ?? "—";

// ── Shared UI primitives ──────────────────────────────────────────────────────

const Badge: React.FC<{ children: React.ReactNode; variant?: "module" | "page" | "role" | "user" | "view" | "edit" | "system" }> = ({
  children,
  variant = "page",
}) => {
  const colors: Record<string, string> = {
    module: "bg-indigo-100 text-indigo-700",
    page: "bg-sky-100 text-sky-700",
    role: "bg-purple-100 text-purple-700",
    user: "bg-teal-100 text-teal-700",
    view: "bg-green-100 text-green-700",
    edit: "bg-amber-100 text-amber-700",
    system: "bg-gray-100 text-gray-500",
  };
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-semibold ${colors[variant] ?? "bg-gray-100 text-gray-600"}`}>
      {children}
    </span>
  );
};

const ConfirmButton: React.FC<{
  onConfirm: () => void;
  disabled?: boolean;
  label?: string;
}> = ({ onConfirm, disabled, label = "Delete" }) => {
  const [confirming, setConfirming] = useState(false);
  if (confirming) {
    return (
      <span className="inline-flex items-center gap-1">
        <button
          onClick={() => { onConfirm(); setConfirming(false); }}
          className="text-xs text-red-600 font-semibold hover:underline"
          disabled={disabled}
        >
          Confirm
        </button>
        <button
          onClick={() => setConfirming(false)}
          className="text-xs text-gray-400 hover:underline"
        >
          Cancel
        </button>
      </span>
    );
  }
  return (
    <button
      onClick={() => setConfirming(true)}
      disabled={disabled}
      className="p-1.5 text-gray-400 hover:text-red-500 rounded transition-colors disabled:opacity-40"
      title={label}
    >
      <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
        <path strokeLinecap="round" strokeLinejoin="round" d="M6 7h12M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2m-7 0l1 12h6l1-12M10 11v6m4-6v6" />
      </svg>
    </button>
  );
};

// ── Tab 1 — Resources ─────────────────────────────────────────────────────────

const ResourcesTab: React.FC = () => {
  const { data: resources = [], isLoading, isError, error, refetch } = useResources();
  const createResource = useCreateResource();
  const deleteResource = useDeleteResource();

  const [rType, setRType] = useState("page");
  const [rName, setRName] = useState("");
  const [rDesc, setRDesc] = useState("");
  const [rPath, setRPath] = useState("");
  const [rParent, setRParent] = useState<number | "">("");

  const modules = resources.filter((r) => r.resource_type === "module");
  const pages = resources.filter((r) => r.resource_type === "page");

  const parentMap: Record<number, string> = {};
  modules.forEach((m) => { parentMap[m.id] = m.resource_name; });

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!rName.trim()) return;
    await createResource.mutateAsync({
      resource_type: rType,
      resource_name: rName.trim(),
      description: rDesc.trim() || undefined,
      route_path: rPath.trim() || undefined,
      parent_id: rParent !== "" ? Number(rParent) : undefined,
    });
    setRName(""); setRDesc(""); setRPath(""); setRParent("");
  };

  const renderTable = (rows: ResourceItem[], title: string) => (
    <div className="mb-6">
      <h3 className="text-sm font-semibold text-gray-700 mb-2">{title}</h3>
      <div className="overflow-x-auto border rounded-lg">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr className="text-left text-xs text-gray-500 font-semibold">
              <th className="py-2 px-3">ID</th>
              <th className="py-2 px-3">Display Name</th>
              <th className="py-2 px-3">Resource Key</th>
              <th className="py-2 px-3">Parent Module</th>
              <th className="py-2 px-3">Route</th>
              <th className="py-2 px-3">Description</th>
              <th className="py-2 px-3 text-center">Type</th>
              <th className="py-2 px-3 text-center">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={8} className="py-4 text-center text-gray-400">Loading…</td></tr>
            ) : rows.length === 0 ? (
              <tr><td colSpan={8} className="py-4 text-center text-gray-300">No entries</td></tr>
            ) : rows.map((r) => (
              <tr key={r.id} className="border-t hover:bg-gray-50">
                <td className="py-2 px-3 font-mono text-xs text-gray-400">{r.id}</td>
                <td className="py-2 px-3">
                  <span className="font-semibold text-gray-800">{getLabel(r.resource_name)}</span>
                </td>
                <td className="py-2 px-3 font-mono text-xs text-gray-500">{r.resource_name}</td>
                <td className="py-2 px-3 text-gray-500 text-xs">
                  {r.parent_id ? getLabel(parentMap[r.parent_id] ?? String(r.parent_id)) : "—"}
                </td>
                <td className="py-2 px-3 font-mono text-xs text-gray-500">
                  {r.route_path ?? "—"}
                </td>
                <td className="py-2 px-3 text-gray-500 text-xs">{getDesc(r.resource_name, r.description)}</td>
                <td className="py-2 px-3 text-center">
                  {r.is_system
                    ? <Badge variant="system">system</Badge>
                    : <Badge variant="page">custom</Badge>}
                </td>
                <td className="py-2 px-3 text-center">
                  {r.is_system ? (
                    <span className="text-xs text-gray-300">protected</span>
                  ) : (
                    <ConfirmButton
                      onConfirm={() => deleteResource.mutate(r.id)}
                      disabled={deleteResource.isPending}
                    />
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );

  return (
    <div className="space-y-6">
      {/* Create custom resource */}
      <div className="bg-white rounded-xl p-6 shadow-sm border">
        <h2 className="text-base font-semibold text-gray-800 mb-4">Add Custom Resource</h2>
        <form onSubmit={handleCreate} className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Type</label>
            <select value={rType} onChange={(e) => setRType(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-att-400">
              <option value="module">Module</option>
              <option value="page">Page</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Name <span className="text-red-500">*</span></label>
            <input value={rName} onChange={(e) => setRName(e.target.value)} required
              placeholder="e.g. billing_reports"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-att-400" />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Route Path</label>
            <input value={rPath} onChange={(e) => setRPath(e.target.value)}
              placeholder="/billing"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-att-400" />
          </div>
          {rType === "page" && (
            <div>
              <label className="block text-xs font-medium text-gray-600 mb-1">Parent Module</label>
              <select value={rParent as any} onChange={(e) => setRParent(e.target.value ? Number(e.target.value) : "")}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-att-400">
                <option value="">— none —</option>
                {modules.map((m) => (
                  <option key={m.id} value={m.id}>{m.resource_name}</option>
                ))}
              </select>
            </div>
          )}
          <div className="md:col-span-2">
            <label className="block text-xs font-medium text-gray-600 mb-1">Description</label>
            <input value={rDesc} onChange={(e) => setRDesc(e.target.value)}
              placeholder="Brief description"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-att-400" />
          </div>
          <div className="flex items-end">
            <button type="submit" disabled={createResource.isPending || !rName.trim()}
              className="w-full px-4 py-2 bg-att-400 text-white rounded-lg text-sm font-semibold hover:bg-att-500 disabled:opacity-50 transition">
              {createResource.isPending ? "Creating…" : "Create Resource"}
            </button>
          </div>
        </form>
        {createResource.isError && (
          <p className="mt-2 text-xs text-red-600">{(createResource.error as any)?.response?.data?.detail ?? "Failed to create resource"}</p>
        )}
      </div>

      {/* Error banner */}
      {isError && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800 flex items-center justify-between">
          <span>
            Failed to load resources: {(error as any)?.response?.data?.detail ?? (error as any)?.message ?? "Network error"}
          </span>
          <button
            onClick={() => refetch()}
            className="ml-4 px-3 py-1 text-xs font-semibold border border-red-300 rounded hover:bg-red-100 transition"
          >
            Retry
          </button>
        </div>
      )}

      {/* Modules table */}
      <div className="bg-white rounded-xl p-6 shadow-sm border">
        {renderTable(modules, "Modules")}
        {renderTable(pages, "Pages")}
      </div>
    </div>
  );
};

// ── Tab 2 — Permissions ───────────────────────────────────────────────────────

const PermissionsTab: React.FC = () => {
  const { data: resources = [] } = useResources();
  const { data: permissions = [], isLoading } = usePermissions();
  const createPerm = useCreatePermission();
  const deletePerm = useDeletePermission();

  const [subjectType, setSubjectType] = useState("role");
  const [subjectId, setSubjectId] = useState("");
  const [resourceId, setResourceId] = useState<number | "">("");
  const [permType, setPermType] = useState("view");

  const handleCreate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!subjectId.trim() || !resourceId) return;
    await createPerm.mutateAsync({
      subject_type: subjectType,
      subject_id: subjectId.trim(),
      resource_id: Number(resourceId),
      permission_type: permType,
    });
    setSubjectId(""); setResourceId("");
  };

  const byModule = resources.filter((r) => r.resource_type === "module");
  const byPage = resources.filter((r) => r.resource_type === "page");

  return (
    <div className="space-y-6">
      {/* Grant permission form */}
      <div className="bg-white rounded-xl p-6 shadow-sm border">
        <h2 className="text-base font-semibold text-gray-800 mb-4">Grant Permission</h2>
        <form onSubmit={handleCreate} className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3 items-end">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Subject Type</label>
            <select value={subjectType} onChange={(e) => setSubjectType(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-att-400">
              <option value="role">Role</option>
              <option value="user">User (by ID)</option>
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              {subjectType === "role" ? "Role" : "User ID"} <span className="text-red-500">*</span>
            </label>
            {subjectType === "role" ? (
              <select value={subjectId} onChange={(e) => setSubjectId(e.target.value)}
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-att-400">
                <option value="">— select —</option>
                <option value="read">read</option>
                <option value="write">write</option>
                <option value="admin">admin</option>
              </select>
            ) : (
              <input value={subjectId} onChange={(e) => setSubjectId(e.target.value)} required
                placeholder="Azure AD object ID"
                className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-att-400" />
            )}
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Resource <span className="text-red-500">*</span></label>
            <select value={resourceId as any} onChange={(e) => setResourceId(e.target.value ? Number(e.target.value) : "")}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-att-400">
              <option value="">— select —</option>
              {byModule.length > 0 && (
                <optgroup label="Modules">
                  {byModule.map((r) => <option key={r.id} value={r.id}>{getLabel(r.resource_name)}</option>)}
                </optgroup>
              )}
              {byPage.length > 0 && (
                <optgroup label="Pages">
                  {byPage.map((r) => <option key={r.id} value={r.id}>{getLabel(r.resource_name)}</option>)}
                </optgroup>
              )}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">Access Level</label>
            <select value={permType} onChange={(e) => setPermType(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-att-400">
              <option value="view">View only</option>
              <option value="edit">View + Edit</option>
            </select>
          </div>
          <div className="md:col-span-2 lg:col-span-4">
            <button type="submit" disabled={createPerm.isPending || !subjectId.trim() || !resourceId}
              className="px-5 py-2 bg-att-400 text-white rounded-lg text-sm font-semibold hover:bg-att-500 disabled:opacity-50 transition">
              {createPerm.isPending ? "Granting…" : "Grant Permission"}
            </button>
            {createPerm.isError && (
              <span className="ml-3 text-xs text-red-600">
                {(createPerm.error as any)?.response?.data?.detail ?? "Failed to grant permission"}
              </span>
            )}
          </div>
        </form>
      </div>

      {/* Permissions table */}
      <div className="bg-white rounded-xl p-6 shadow-sm border">
        <h2 className="text-base font-semibold text-gray-800 mb-4">Granted Permissions</h2>
        <div className="overflow-x-auto border rounded-lg">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr className="text-left text-xs text-gray-500 font-semibold">
                <th className="py-2 px-3">Subject</th>
                <th className="py-2 px-3">Resource</th>
                <th className="py-2 px-3">Resource Type</th>
                <th className="py-2 px-3 text-center">Access</th>
                <th className="py-2 px-3 text-center">Revoke</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <tr><td colSpan={5} className="py-4 text-center text-gray-400">Loading…</td></tr>
              ) : permissions.length === 0 ? (
                <tr><td colSpan={5} className="py-4 text-center text-gray-300">No permissions granted yet</td></tr>
              ) : permissions.map((p) => (
                <tr key={p.id} className="border-t hover:bg-gray-50">
                  <td className="py-2 px-3">
                    <div className="flex items-center gap-2">
                      <Badge variant={p.subject_type as any}>{p.subject_type}</Badge>
                      <span className="font-medium">{p.subject_id}</span>
                    </div>
                  </td>
                  <td className="py-2 px-3 font-medium">{p.resource_name ?? p.resource_id}</td>
                  <td className="py-2 px-3">
                    {p.resource_type ? (
                      <Badge variant={p.resource_type as any}>{p.resource_type}</Badge>
                    ) : "—"}
                  </td>
                  <td className="py-2 px-3 text-center">
                    <Badge variant={p.permission_type as any}>{p.permission_type}</Badge>
                  </td>
                  <td className="py-2 px-3 text-center">
                    <ConfirmButton
                      onConfirm={() => deletePerm.mutate(p.id)}
                      disabled={deletePerm.isPending}
                      label="Revoke permission"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

// ── Tab 3 — Matrix view ───────────────────────────────────────────────────────

const MatrixTab: React.FC = () => {
  const { data: resources = [], isLoading: loadingRes } = useResources();
  const { data: permissions = [], isLoading: loadingPerms } = usePermissions();

  const roles = ["admin", "write", "read"];
  const modules = resources.filter((r) => r.resource_type === "module");
  const pages = resources.filter((r) => r.resource_type === "page");

  const permSet = new Set(
    permissions
      .filter((p) => p.subject_type === "role")
      .map((p) => `${p.subject_id}::${p.resource_name}::${p.permission_type}`)
  );

  const hasAccess = (role: string, resourceName: string, permType: string) =>
    permSet.has(`${role}::${resourceName}::${permType}`);

  if (loadingRes || loadingPerms) {
    return <div className="py-12 text-center text-gray-400">Loading…</div>;
  }

  const isAdminResource = (name: string) =>
    name === "admin" || name.startsWith("admin_");

  const Cell: React.FC<{ role: string; resource: ResourceItem }> = ({ role, resource }) => {
    if (isAdminResource(resource.resource_name)) {
      return (
        <td className="py-2 px-3 text-center">
          {role === "admin"
            ? <Badge variant="system">role-gated</Badge>
            : <span className="text-xs text-gray-200">—</span>}
        </td>
      );
    }
    const canView = hasAccess(role, resource.resource_name, "view");
    const canEdit = hasAccess(role, resource.resource_name, "edit");
    if (!canView && !canEdit) return <td className="py-2 px-3 text-center text-gray-200">—</td>;
    return (
      <td className="py-2 px-3 text-center">
        <div className="flex items-center justify-center gap-1">
          {canView && <Badge variant="view">view</Badge>}
          {canEdit && <Badge variant="edit">edit</Badge>}
        </div>
      </td>
    );
  };

  return (
    <div className="bg-white rounded-xl p-6 shadow-sm border">
      <h2 className="text-base font-semibold text-gray-800 mb-1">Role Access Matrix</h2>
      <p className="text-xs text-gray-500 mb-4">Shows role-based grants. User-specific overrides are not shown here.</p>
      <div className="overflow-x-auto border rounded-lg">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr className="text-left text-xs text-gray-500 font-semibold">
              <th className="py-2 px-3">Resource</th>
              <th className="py-2 px-3">Type</th>
              {roles.map((r) => (
                <th key={r} className="py-2 px-3 text-center">
                  <Badge variant="role">{r}</Badge>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...modules, ...pages].map((resource) => (
              <tr key={resource.id} className={`border-t ${resource.resource_type === "module" ? "bg-gray-50/60" : ""}`}>
                <td className="py-2 px-3">
                  <div className="flex items-center gap-1">
                    {resource.resource_type === "page" && (
                      <span className="text-gray-300 mr-1">└</span>
                    )}
                    <div>
                      <span className="font-medium text-gray-800">{getLabel(resource.resource_name)}</span>
                      <span className="block text-xs font-mono text-gray-400">{resource.resource_name}</span>
                    </div>
                  </div>
                </td>
                <td className="py-2 px-3">
                  <Badge variant={resource.resource_type as any}>{resource.resource_type}</Badge>
                </td>
                {roles.map((role) => (
                  <Cell key={role} role={role} resource={resource} />
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// ── Main component ────────────────────────────────────────────────────────────

type TabKey = "resources" | "permissions" | "matrix";

const TABS: { key: TabKey; label: string }[] = [
  { key: "resources", label: "Resources" },
  { key: "permissions", label: "Permissions" },
  { key: "matrix", label: "Access Matrix" },
];

const PermissionsManagement: React.FC = () => {
  const [activeTab, setActiveTab] = useState<TabKey>("resources");

  return (
    <div className="space-y-4 py-4">
      <div>
        <h1 className="text-xl font-bold text-gray-900">Access Management</h1>
        <p className="text-sm text-gray-500">
          Manage module and page-level permissions. Admin users always have full access.
        </p>
      </div>

      {/* Tab bar */}
      <div className="border-b border-gray-200">
        <nav className="flex gap-1">
          {TABS.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === tab.key
                  ? "border-att-400 text-att-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      {activeTab === "resources" && <ResourcesTab />}
      {activeTab === "permissions" && <PermissionsTab />}
      {activeTab === "matrix" && <MatrixTab />}
    </div>
  );
};

export default PermissionsManagement;
