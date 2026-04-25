import React, { useState } from "react";
import { useResources, useCreateResource, usePermissions, useCreatePermission } from "../../services/permissionsApi";

const PermissionsManagement: React.FC = () => {
  const { data: resources, isLoading: loadingResources } = useResources();
  const { data: permissions, isLoading: loadingPerms } = usePermissions();
  const createResource = useCreateResource();
  const createPermission = useCreatePermission();

  const [resourceType, setResourceType] = useState("page");
  const [resourceName, setResourceName] = useState("");
  const [resourceDesc, setResourceDesc] = useState("");

  const [subjectType, setSubjectType] = useState("role");
  const [subjectId, setSubjectId] = useState("");
  const [selectedResourceId, setSelectedResourceId] = useState<number | "">("");
  const [permissionType, setPermissionType] = useState("view");

  const onCreateResource = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!resourceName) return;
    await createResource.mutateAsync({ resource_type: resourceType, resource_name: resourceName, description: resourceDesc });
    setResourceName("");
    setResourceDesc("");
  };

  const onCreatePermission = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!subjectId || !selectedResourceId) return;
    await createPermission.mutateAsync({ subject_type: subjectType, subject_id: subjectId, resource_id: selectedResourceId, permission_type: permissionType });
    setSubjectId("");
    setSelectedResourceId("");
  };

  return (
    <div className="space-y-6">
      <div className="bg-white rounded-xl p-6 shadow-sm border">
        <h2 className="text-lg font-semibold mb-3">Resources (Modules & Pages)</h2>
        <form onSubmit={onCreateResource} className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
          <div>
            <label className="block text-sm text-gray-600 mb-1">Type</label>
            <select value={resourceType} onChange={(e) => setResourceType(e.target.value)} className="w-full px-3 py-2 border rounded">
              <option value="module">Module</option>
              <option value="page">Page</option>
            </select>
          </div>
          <div>
            <label className="block text-sm text-gray-600 mb-1">Name</label>
            <input value={resourceName} onChange={(e) => setResourceName(e.target.value)} className="w-full px-3 py-2 border rounded" />
          </div>
          <div>
            <label className="block text-sm text-gray-600 mb-1">Description</label>
            <input value={resourceDesc} onChange={(e) => setResourceDesc(e.target.value)} className="w-full px-3 py-2 border rounded" />
          </div>
          <div className="md:col-span-3">
            <button type="submit" className="px-4 py-2 bg-blue-600 text-white rounded">Create Resource</button>
          </div>
        </form>

        <div className="mt-6">
          <h3 className="text-sm font-medium text-gray-700 mb-2">Existing Resources</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-500">
                  <th className="py-2">ID</th>
                  <th>Name</th>
                  <th>Type</th>
                  <th>Description</th>
                </tr>
              </thead>
              <tbody>
                {loadingResources ? (
                  <tr><td colSpan={4}>Loading…</td></tr>
                ) : (resources ?? []).map((r) => (
                  <tr key={r.id} className="border-t">
                    <td className="py-2">{r.id}</td>
                    <td className="py-2 font-medium">{r.resource_name}</td>
                    <td className="py-2">{r.resource_type}</td>
                    <td className="py-2">{r.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <div className="bg-white rounded-xl p-6 shadow-sm border">
        <h2 className="text-lg font-semibold mb-3">Permissions</h2>
        <form onSubmit={onCreatePermission} className="grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
          <div>
            <label className="block text-sm text-gray-600 mb-1">Subject Type</label>
            <select value={subjectType} onChange={(e) => setSubjectType(e.target.value)} className="w-full px-3 py-2 border rounded">
              <option value="role">Role</option>
              <option value="user">User</option>
            </select>
          </div>
          <div>
            <label className="block text-sm text-gray-600 mb-1">Subject ID (user id or role)</label>
            <input value={subjectId} onChange={(e) => setSubjectId(e.target.value)} className="w-full px-3 py-2 border rounded" />
          </div>
          <div>
            <label className="block text-sm text-gray-600 mb-1">Resource</label>
            <select value={selectedResourceId as any} onChange={(e) => setSelectedResourceId(Number(e.target.value))} className="w-full px-3 py-2 border rounded">
              <option value="">— select —</option>
              {(resources ?? []).map((r) => (
                <option key={r.id} value={r.id}>{r.resource_name} ({r.resource_type})</option>
              ))}
            </select>
          </div>
          <div>
            <label className="block text-sm text-gray-600 mb-1">Permission</label>
            <select value={permissionType} onChange={(e) => setPermissionType(e.target.value)} className="w-full px-3 py-2 border rounded">
              <option value="view">View</option>
              <option value="edit">Edit</option>
            </select>
          </div>
          <div className="md:col-span-3">
            <button type="submit" className="px-4 py-2 bg-blue-600 text-white rounded">Grant Permission</button>
          </div>
        </form>

        <div className="mt-6">
          <h3 className="text-sm font-medium text-gray-700 mb-2">Existing Permissions</h3>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-gray-500">
                  <th className="py-2">ID</th>
                  <th>Subject</th>
                  <th>Resource ID</th>
                  <th>Permission</th>
                </tr>
              </thead>
              <tbody>
                {loadingPerms ? (
                  <tr><td colSpan={4}>Loading…</td></tr>
                ) : (permissions ?? []).map((p) => (
                  <tr key={p.id} className="border-t">
                    <td className="py-2">{p.id}</td>
                    <td className="py-2">{p.subject_type}: {p.subject_id}</td>
                    <td className="py-2">{p.resource_id}</td>
                    <td className="py-2">{p.permission_type}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};

export default PermissionsManagement;
