/**
 * Checksum Schedule Form Component
 * 
 * Form for creating and editing checksum schedules.
 * Supports both Synapse and AKS module types.
 */

import React, { useState, useEffect, useMemo } from "react";
import { ChecksumScheduleCreateRequest, ChecksumScheduleDetail } from "../../services/checksumScheduleApi";
import { useSynapseGroupedWorkspaces, useAKSNamespaces } from "../../services/complianceApi";
import { useCachedClusters } from "../../services/aksApi";

interface ChecksumScheduleFormProps {
  schedule?: ChecksumScheduleDetail;
  onSubmit: (data: ChecksumScheduleCreateRequest) => Promise<void>;
  onCancel: () => void;
  isLoading: boolean;
}

export const ChecksumScheduleForm: React.FC<ChecksumScheduleFormProps> = ({
  schedule,
  onSubmit,
  onCancel,
  isLoading,
}) => {
  const isEditMode = !!schedule;

  // ── Data hooks for dropdowns ───────────────────────────────────────
  const { data: workspaceData } = useSynapseGroupedWorkspaces();
  const { data: clusterData } = useCachedClusters();

  const allWorkspaces = useMemo(() => {
    if (!workspaceData?.groups) return [];
    return workspaceData.groups.flatMap((g) => g.workspaces);
  }, [workspaceData]);

  const clusters = clusterData?.clusters ?? [];

  const [formData, setFormData] = useState<ChecksumScheduleCreateRequest>({
    name: schedule?.name || "",
    description: schedule?.description || "",
    module_type: schedule?.module_type || "synapse",
    system: schedule?.system || "",
    environment: schedule?.environment || "prod",
    workspace_name: schedule?.workspace_name || "",
    cluster_id: schedule?.cluster_id || "",
    cluster_name: schedule?.cluster_name || "",
    namespaces: schedule?.namespaces || [],
    schedule_type: schedule?.schedule_type || "interval",
    interval_hours: schedule?.interval_hours || 24,
    cron_expression: schedule?.cron_expression || "",
    timezone: schedule?.timezone || "America/Chicago",
    notification_emails: schedule?.notification_emails || [],
    is_enabled: schedule?.is_enabled !== undefined ? schedule.is_enabled : true,
  });

  // AKS namespace hook needs cluster_id from formData
  const { data: nsData } = useAKSNamespaces(
    formData.module_type === "aks" && formData.cluster_id ? formData.cluster_id : undefined,
  );
  const availableNamespaces = nsData?.namespaces ?? [];

  const [emailInput, setEmailInput] = useState("");

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>) => {
    const { name, value, type } = e.target;
    
    if (type === "checkbox") {
      setFormData((prev) => ({
        ...prev,
        [name]: (e.target as HTMLInputElement).checked,
      }));
    } else {
      setFormData((prev) => {
        const updated = {
          ...prev,
          [name]: name === "interval_hours" ? parseInt(value) || 0 : value,
        };
        // Reset CES system when switching to AKS
        if (name === "module_type" && value === "aks" && prev.system === "ces") {
          updated.system = "";
        }
        return updated;
      });
    }
  };

  const handleAddEmail = () => {
    if (emailInput && /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(emailInput)) {
      setFormData((prev) => ({
        ...prev,
        notification_emails: [...(prev.notification_emails || []), emailInput],
      }));
      setEmailInput("");
    }
  };

  const handleRemoveEmail = (index: number) => {
    setFormData((prev) => ({
      ...prev,
      notification_emails: (prev.notification_emails || []).filter((_, i) => i !== index),
    }));
  };

  const handleRemoveNamespace = (index: number) => {
    setFormData((prev) => ({
      ...prev,
      namespaces: (prev.namespaces || []).filter((_, i) => i !== index),
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    
    // Validation
    if (!formData.name.trim()) {
      alert("Schedule name is required");
      return;
    }

    if (formData.schedule_type === "interval" && (!formData.interval_hours || formData.interval_hours < 1)) {
      alert("Interval hours must be at least 1");
      return;
    }

    if (formData.schedule_type === "cron" && !formData.cron_expression?.trim()) {
      alert("Cron expression is required for cron-based schedules");
      return;
    }

    if (formData.module_type === "synapse" && !formData.workspace_name?.trim()) {
      alert("Workspace name is required for Synapse module");
      return;
    }

    if (formData.module_type === "aks" && !formData.cluster_name?.trim()) {
      alert("Cluster name is required for AKS module");
      return;
    }

    await onSubmit(formData);
  };

  return (
    <form onSubmit={handleSubmit} className="space-y-6 bg-white p-6 rounded-lg shadow">
      {/* Basic Information */}
      <div>
        <h3 className="text-lg font-semibold text-gray-800 mb-4">Basic Information</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Schedule Name */}
          <div>
            <label htmlFor="name" className="block text-sm font-medium text-gray-700 mb-1">
              Schedule Name *
            </label>
            <input
              type="text"
              id="name"
              name="name"
              value={formData.name}
              onChange={handleChange}
              placeholder="e.g., Daily ATTCC Checksum"
              disabled={isLoading}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
            />
          </div>

          {/* Module Type */}
          <div>
            <label htmlFor="module_type" className="block text-sm font-medium text-gray-700 mb-1">
              Module Type *
            </label>
            <select
              id="module_type"
              name="module_type"
              value={formData.module_type}
              onChange={handleChange}
              disabled={isLoading}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
            >
              <option value="synapse">Synapse</option>
              <option value="aks">AKS</option>
            </select>
          </div>

          {/* System */}
          <div>
            <label htmlFor="system" className="block text-sm font-medium text-gray-700 mb-1">
              System
            </label>
            <select
              id="system"
              name="system"
              value={formData.system}
              onChange={handleChange}
              disabled={isLoading}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
            >
              <option value="">Select System...</option>
              <option value="attcc">ATTCC</option>
              {formData.module_type !== "aks" && (
                <option value="ces">CES</option>
              )}
            </select>
          </div>

          {/* Environment */}
          <div>
            <label htmlFor="environment" className="block text-sm font-medium text-gray-700 mb-1">
              Environment
            </label>
            <select
              id="environment"
              name="environment"
              value={formData.environment}
              onChange={handleChange}
              disabled={isLoading}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
            >
              <option value="">Select Environment...</option>
              <option value="dev">Dev</option>
              <option value="perf">Perf</option>
              <option value="stage">Stage</option>
              <option value="uat">UAT</option>
              <option value="prod">Prod</option>
              <option value="dr">DR</option>
              <option value="poc">POC</option>
            </select>
          </div>
        </div>

        {/* Description */}
        <div className="mt-4">
          <label htmlFor="description" className="block text-sm font-medium text-gray-700 mb-1">
            Description
          </label>
          <textarea
            id="description"
            name="description"
            value={formData.description}
            onChange={handleChange}
            placeholder="Describe the purpose and scope of this schedule..."
            disabled={isLoading}
            rows={3}
            className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
          />
        </div>
      </div>

      {/* Module-Specific Configuration */}
      <div>
        <h3 className="text-lg font-semibold text-gray-800 mb-4">Module Configuration</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {formData.module_type === "synapse" && (
            <div>
              <label htmlFor="workspace_name" className="block text-sm font-medium text-gray-700 mb-1">
                Workspace Name *
              </label>
              <select
                id="workspace_name"
                name="workspace_name"
                value={formData.workspace_name}
                onChange={handleChange}
                disabled={isLoading}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
              >
                <option value="">Select Workspace...</option>
                {allWorkspaces.map((ws) => (
                  <option key={ws.workspace_name} value={ws.workspace_name}>
                    {ws.workspace_name}
                  </option>
                ))}
              </select>
            </div>
          )}

          {formData.module_type === "aks" && (
            <>
              <div className="md:col-span-2">
                <label htmlFor="cluster_id" className="block text-sm font-medium text-gray-700 mb-1">
                  Cluster *
                </label>
                <select
                  id="cluster_id"
                  name="cluster_id"
                  value={formData.cluster_id}
                  onChange={(e) => {
                    const selected = clusters.find((c) => c.id === e.target.value);
                    setFormData((prev) => ({
                      ...prev,
                      cluster_id: e.target.value,
                      cluster_name: selected?.name ?? "",
                      namespaces: [],
                    }));
                  }}
                  disabled={isLoading}
                  className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
                >
                  <option value="">Select Cluster...</option>
                  {clusters.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name} ({c.environment ?? "unknown"})
                    </option>
                  ))}
                </select>
              </div>
            </>
          )}
        </div>

        {/* Namespaces for AKS */}
        {formData.module_type === "aks" && (
          <div className="mt-4">
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Kubernetes Namespaces
            </label>
            {!formData.cluster_id ? (
              <p className="text-sm text-gray-400">Select a cluster first to load namespaces</p>
            ) : availableNamespaces.length === 0 ? (
              <p className="text-sm text-gray-400">Loading namespaces...</p>
            ) : (
              <div className="border border-gray-300 rounded-lg max-h-48 overflow-y-auto p-2 space-y-1">
                {availableNamespaces.map((ns) => (
                  <label key={ns} className="flex items-center gap-2 px-2 py-1 hover:bg-gray-50 cursor-pointer text-sm rounded">
                    <input
                      type="checkbox"
                      checked={formData.namespaces?.includes(ns) ?? false}
                      onChange={() => {
                        setFormData((prev) => {
                          const current = prev.namespaces ?? [];
                          return {
                            ...prev,
                            namespaces: current.includes(ns)
                              ? current.filter((n) => n !== ns)
                              : [...current, ns],
                          };
                        });
                      }}
                      disabled={isLoading}
                      className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                    />
                    {ns}
                  </label>
                ))}
              </div>
            )}
            {(formData.namespaces?.length ?? 0) > 0 && (
              <div className="flex flex-wrap gap-2 mt-2">
                {formData.namespaces?.map((ns, idx) => (
                  <span
                    key={idx}
                    className="px-3 py-1 bg-blue-100 text-blue-800 rounded-full text-sm flex items-center gap-2"
                  >
                    {ns}
                    <button
                      type="button"
                      onClick={() => handleRemoveNamespace(idx)}
                      disabled={isLoading}
                      className="ml-1 text-blue-600 hover:text-blue-800"
                    >
                      ✕
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Schedule Configuration */}
      <div>
        <h3 className="text-lg font-semibold text-gray-800 mb-4">Schedule Configuration</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Schedule Type */}
          <div>
            <label htmlFor="schedule_type" className="block text-sm font-medium text-gray-700 mb-1">
              Schedule Type *
            </label>
            <select
              id="schedule_type"
              name="schedule_type"
              value={formData.schedule_type}
              onChange={handleChange}
              disabled={isLoading}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
            >
              <option value="interval">Interval (every N hours)</option>
              <option value="cron">Cron Expression</option>
            </select>
          </div>

          {/* Timezone */}
          <div>
            <label htmlFor="timezone" className="block text-sm font-medium text-gray-700 mb-1">
              Timezone
            </label>
            <select
              id="timezone"
              name="timezone"
              value={formData.timezone}
              onChange={handleChange}
              disabled={isLoading}
              className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
            >
              <option value="UTC">UTC</option>
              <option value="America/New_York">Eastern Time</option>
              <option value="America/Chicago">Central Time</option>
              <option value="America/Denver">Mountain Time</option>
              <option value="America/Los_Angeles">Pacific Time</option>
            </select>
          </div>

          {/* Interval Hours */}
          {formData.schedule_type === "interval" && (
            <div>
              <label htmlFor="interval_hours" className="block text-sm font-medium text-gray-700 mb-1">
                Interval (hours) *
              </label>
              <input
                type="number"
                id="interval_hours"
                name="interval_hours"
                min={1}
                max={8760}
                value={formData.interval_hours}
                onChange={handleChange}
                disabled={isLoading}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
              />
            </div>
          )}

          {/* Cron Expression */}
          {formData.schedule_type === "cron" && (
            <div>
              <label htmlFor="cron_expression" className="block text-sm font-medium text-gray-700 mb-1">
                Cron Expression *
              </label>
              <input
                type="text"
                id="cron_expression"
                name="cron_expression"
                value={formData.cron_expression}
                onChange={handleChange}
                placeholder="0 0 * * * (daily at midnight)"
                disabled={isLoading}
                className="w-full px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
              />
              <p className="text-xs text-gray-500 mt-1">Format: minute hour day month weekday</p>
            </div>
          )}
        </div>
      </div>

      {/* Notifications */}
      <div>
        <h3 className="text-lg font-semibold text-gray-800 mb-4">Notifications</h3>
        <div>
          <label htmlFor="emailInput" className="block text-sm font-medium text-gray-700 mb-1">
            Notification Emails
          </label>
          <div className="flex gap-2 mb-2">
            <input
              type="email"
              id="emailInput"
              value={emailInput}
              onChange={(e) => setEmailInput(e.target.value)}
              placeholder="admin@company.com"
              disabled={isLoading}
              className="flex-1 px-4 py-2 border border-gray-300 rounded-lg focus:ring-2 focus:ring-blue-500 focus:border-transparent disabled:opacity-50"
            />
            <button
              type="button"
              onClick={handleAddEmail}
              disabled={isLoading || !emailInput}
              className="px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
            >
              Add
            </button>
          </div>
          <div className="space-y-2">
            {formData.notification_emails?.map((email, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between px-4 py-2 bg-gray-100 rounded-lg"
              >
                <span className="text-sm">{email}</span>
                <button
                  type="button"
                  onClick={() => handleRemoveEmail(idx)}
                  disabled={isLoading}
                  className="text-red-600 hover:text-red-800"
                >
                  Remove
                </button>
              </div>
            ))}
            {formData.notification_emails?.length === 0 && (
              <p className="text-sm text-gray-500">No email addresses added yet</p>
            )}
          </div>
        </div>
      </div>

      {/* Status Toggle */}
      <div className="flex items-center gap-3">
        <input
          type="checkbox"
          id="is_enabled"
          name="is_enabled"
          checked={formData.is_enabled}
          onChange={handleChange}
          disabled={isLoading}
          className="w-4 h-4 cursor-pointer"
        />
        <label htmlFor="is_enabled" className="text-sm font-medium text-gray-700">
          Enable this schedule
        </label>
      </div>

      {/* Action Buttons */}
      <div className="flex gap-3 justify-end">
        <button
          type="button"
          onClick={onCancel}
          disabled={isLoading}
          className="px-6 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 disabled:opacity-50"
        >
          Cancel
        </button>
        <button
          type="submit"
          disabled={isLoading}
          className="px-6 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {isLoading ? "Saving..." : isEditMode ? "Update Schedule" : "Create Schedule"}
        </button>
      </div>
    </form>
  );
};
