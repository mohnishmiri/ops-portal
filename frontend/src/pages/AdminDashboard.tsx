/**
 * Admin Dashboard — subscription management, system health, and configuration.
 *
 * Supports subscription management via DB-backed endpoints:
 *  - Enable / disable / monitor toggle per subscription
 *  - Add new subscription manually
 *  - Discover subscriptions from Azure ARM
 *  - Admin config management
 */

import React, { useState, useCallback, useEffect, useMemo } from "react";
import {
  useAdminDashboard,
  useAdminConfigs,
  useAddSubscription,
  useToggleSubscription,
  useDiscoverSubscriptions,
  useSyncSubscriptions,
  useUpsertAdminConfig,
  useReleaseOperationalCache,
  SubscriptionInfo,
  AdminConfigEntry,
} from "../services/costApi";
import { apiErrorMessage } from "../services/infraAlertApi";
import {
  useAllCollections,
  useEnabledCollections,
  useSetEnabledCollections,
} from "../services/certificatesApi";
import {
  usePortalTimezone,
  useUpdatePortalTimezone,
  TIMEZONE_OPTIONS,
} from "../contexts/TimezoneContext";
import { MetricCard, MetricCardIcons } from "../components/MetricCard";
import { Link } from "react-router-dom";

// ── Toggle Switch ─────────────────────────────────────────────────────

const Toggle: React.FC<{
  checked: boolean;
  onChange: () => void;
  disabled?: boolean;
  label?: string;
}> = ({ checked, onChange, disabled, label }) => (
  <button
    type="button"
    role="switch"
    aria-checked={checked}
    aria-label={label}
    disabled={disabled}
    onClick={onChange}
    className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 ${
      checked ? "bg-blue-600" : "bg-gray-200"
    } ${disabled ? "opacity-50 cursor-not-allowed" : ""}`}
  >
    <span
      className={`pointer-events-none inline-block h-5 w-5 transform rounded-full bg-white shadow ring-0 transition duration-200 ease-in-out ${
        checked ? "translate-x-5" : "translate-x-0"
      }`}
    />
  </button>
);

// ── Status Badge ──────────────────────────────────────────────────────

const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const colorMap: Record<string, string> = {
    connected: "bg-green-100 text-green-800",
    healthy: "bg-green-100 text-green-800",
    enabled: "bg-green-100 text-green-800",
    Enabled: "bg-green-100 text-green-800",
    disconnected: "bg-red-100 text-red-800",
    unreachable: "bg-red-100 text-red-800",
    degraded: "bg-yellow-100 text-yellow-800",
    configured: "bg-blue-100 text-blue-800",
    Unknown: "bg-gray-100 text-gray-600",
    // Azure subscription states
    Disabled: "bg-red-100 text-red-800",
    Deleted: "bg-red-100 text-red-800",
    Warned: "bg-yellow-100 text-yellow-800",
    PastDue: "bg-yellow-100 text-yellow-800",
  };

  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${
        colorMap[status] || "bg-gray-100 text-gray-600"
      }`}
    >
      {status}
    </span>
  );
};

// ── Add Subscription Form ─────────────────────────────────────────────

const GUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const AddSubscriptionForm: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const [subId, setSubId] = useState("");
  const [subName, setSubName] = useState("");
  const [env, setEnv] = useState("");
  const [notes, setNotes] = useState("");
  const addMutation = useAddSubscription();
  const idValid = GUID_PATTERN.test(subId.trim());

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!idValid) return;
    try {
      await addMutation.mutateAsync({
        subscription_id: subId.trim(),
        subscription_name: subName.trim() || undefined,
        environment: env.trim() || undefined,
        notes: notes.trim() || undefined,
        enabled: true,
      });
      onClose();
    } catch {
      // Shown inline from addMutation.error.
    }
  };

  return (
    <div className="bg-blue-50 border border-blue-200 rounded-xl p-6 mb-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-4">Add Subscription</h3>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">
              Subscription ID <span className="text-red-500">*</span>
            </label>
            <input
              type="text"
              value={subId}
              onChange={(e) => setSubId(e.target.value)}
              placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              required
            />
            {subId.trim() && !idValid && (
              <p className="mt-1 text-xs text-red-600">Enter the subscription GUID (8-4-4-4-12 hex characters).</p>
            )}
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Display Name</label>
            <input
              type="text"
              value={subName}
              onChange={(e) => setSubName(e.target.value)}
              placeholder="Defaults to the subscription ID"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Environment</label>
            <select
              value={env}
              onChange={(e) => setEnv(e.target.value)}
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            >
              <option value="">— select —</option>
              <option value="production">Production</option>
              <option value="non-production">Non-Production</option>
              <option value="development">Development</option>
              <option value="staging">Staging</option>
              <option value="dr">DR</option>
            </select>
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Notes</label>
            <input
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Optional notes"
              className="w-full px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
            />
          </div>
        </div>
        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={addMutation.isPending || !idValid}
            className="px-4 py-2 bg-blue-600 text-white rounded-lg text-sm font-semibold hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {addMutation.isPending ? "Adding…" : "Add Subscription"}
          </button>
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 bg-gray-100 text-gray-700 rounded-lg text-sm font-semibold hover:bg-gray-200"
          >
            Cancel
          </button>
          {addMutation.isError && (
            <span className="text-red-600 text-sm">
              {apiErrorMessage(addMutation.error, "Failed to add subscription.")}
            </span>
          )}
        </div>
      </form>
    </div>
  );
};

// ── Subscription Table ────────────────────────────────────────────────

/** Background syncs and dashboards only cover subscriptions that are both enabled and monitored. */
const isInScope = (sub: SubscriptionInfo) => sub.enabled && sub.monitored;

type ScopeFilter = "all" | "in" | "out";

const SCOPE_FILTER_LABEL: Record<ScopeFilter, string> = {
  all: "All",
  in: "In scope",
  out: "Not in scope",
};

const SubscriptionTable: React.FC<{
  subs: SubscriptionInfo[];
  onShowAdd: () => void;
  scopeFilter: ScopeFilter;
  onScopeFilterChange: (filter: ScopeFilter) => void;
}> = ({ subs, onShowAdd, scopeFilter, onScopeFilterChange }) => {
  const toggleMutation = useToggleSubscription();
  const discoverMutation = useDiscoverSubscriptions();
  const syncMutation = useSyncSubscriptions();
  const [search, setSearch] = useState("");

  const handleToggle = useCallback(
    (sub: SubscriptionInfo, field: "enabled" | "monitored") => {
      if (!sub.subscription_id) return;
      toggleMutation.mutate({
        subscription_id: sub.subscription_id,
        [field]: field === "enabled" ? !sub.enabled : !sub.monitored,
      });
    },
    [toggleMutation],
  );

  const inScopeCount = subs.filter(isInScope).length;
  const visibleSubs = useMemo(() => {
    const term = search.trim().toLowerCase();
    return subs.filter((sub) => {
      if (scopeFilter === "in" && !isInScope(sub)) return false;
      if (scopeFilter === "out" && isInScope(sub)) return false;
      if (!term) return true;
      return [sub.subscription_name, sub.name, sub.subscription_id, sub.environment]
        .some((value) => value?.toLowerCase().includes(term));
    });
  }, [subs, search, scopeFilter]);

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-4 gap-3">
        <div>
          <h3 className="text-lg font-semibold text-gray-800">
            Managed Subscriptions
          </h3>
          <p className="text-sm text-gray-500">
            {inScopeCount} in scope (enabled &amp; monitored) of {subs.length} total
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => discoverMutation.mutate()}
            disabled={discoverMutation.isPending}
            title="Add subscriptions the service principal can see but the portal doesn't know yet (added disabled)"
            className="inline-flex items-center gap-1.5 px-3 py-2 bg-purple-50 text-purple-700 border border-purple-200 rounded-lg text-sm font-semibold hover:bg-purple-100 disabled:opacity-50"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            {discoverMutation.isPending ? "Discovering…" : "Discover from Azure"}
          </button>
          <button
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
            title="Refresh name and state of existing subscriptions from Azure"
            className="inline-flex items-center gap-1.5 px-3 py-2 bg-indigo-50 text-indigo-700 border border-indigo-200 rounded-lg text-sm font-semibold hover:bg-indigo-100 disabled:opacity-50"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            {syncMutation.isPending ? "Syncing…" : "Sync"}
          </button>
          <button
            onClick={onShowAdd}
            className="inline-flex items-center gap-1.5 px-3 py-2 bg-blue-600 text-white rounded-lg text-sm font-semibold hover:bg-blue-700"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" />
            </svg>
            Add
          </button>
        </div>
      </div>

      {discoverMutation.isSuccess && (
        <div className="mb-4 p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-800">
          Discovered {(discoverMutation.data as any)?.discovered ?? 0} subscriptions
          ({(discoverMutation.data as any)?.new_count ?? 0} new, added disabled for review).
        </div>
      )}
      {syncMutation.isSuccess && (
        <div className="mb-4 p-3 bg-indigo-50 border border-indigo-200 rounded-lg text-sm text-indigo-800">
          Synced {(syncMutation.data as any)?.updated_count ?? 0} of{" "}
          {(syncMutation.data as any)?.discovered ?? 0} subscriptions.
        </div>
      )}
      {discoverMutation.isError && (
        <div role="alert" className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
          Discover failed: {apiErrorMessage(discoverMutation.error, "Azure did not respond.")}
        </div>
      )}
      {syncMutation.isError && (
        <div role="alert" className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
          Sync failed: {apiErrorMessage(syncMutation.error, "Azure did not respond.")}
        </div>
      )}
      {toggleMutation.isError && (
        <div role="alert" className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
          Could not update the subscription: {apiErrorMessage(toggleMutation.error, "request failed.")}
        </div>
      )}

      <div className="mb-3 flex flex-col gap-2 sm:flex-row sm:items-center">
        <input
          type="search"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search name, ID or environment…"
          aria-label="Search subscriptions"
          className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100"
        />
        <div className="inline-flex rounded-lg border border-gray-200 p-0.5" role="group" aria-label="Scope filter">
          {(Object.keys(SCOPE_FILTER_LABEL) as ScopeFilter[]).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => onScopeFilterChange(key)}
              aria-pressed={scopeFilter === key}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                scopeFilter === key ? "bg-blue-600 text-white" : "text-gray-600 hover:bg-gray-100"
              }`}
            >
              {SCOPE_FILTER_LABEL[key]}
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-200">
              <th className="text-left py-2 px-3 font-semibold text-gray-600">Name</th>
              <th className="text-left py-2 px-3 font-semibold text-gray-600">Subscription ID</th>
              <th className="text-center py-2 px-3 font-semibold text-gray-600">Environment</th>
              <th className="text-center py-2 px-3 font-semibold text-gray-600">State</th>
              <th className="text-center py-2 px-3 font-semibold text-gray-600">Enabled</th>
              <th className="text-center py-2 px-3 font-semibold text-gray-600">Monitored</th>
            </tr>
          </thead>
          <tbody>
            {visibleSubs.map((sub) => (
              <tr
                key={sub.subscription_id}
                className={`border-b border-gray-50 hover:bg-gray-50 ${
                  !isInScope(sub) ? "opacity-60" : ""
                }`}
              >
                <td className="py-3 px-3 font-medium text-gray-900">
                  {sub.subscription_name || sub.name}
                </td>
                <td className="py-3 px-3 font-mono text-gray-600 text-xs">
                  {sub.subscription_id}
                </td>
                <td className="py-3 px-3 text-center">
                  {sub.environment ? (
                    <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-700">
                      {sub.environment}
                    </span>
                  ) : (
                    <span className="text-gray-400 text-xs">—</span>
                  )}
                </td>
                <td className="py-3 px-3 text-center">
                  <StatusBadge status={sub.state} />
                </td>
                <td className="py-3 px-3 text-center">
                  <Toggle
                    checked={sub.enabled}
                    onChange={() => handleToggle(sub, "enabled")}
                    disabled={toggleMutation.isPending}
                    label={`Toggle enabled for ${sub.subscription_name || sub.name}`}
                  />
                </td>
                <td className="py-3 px-3 text-center">
                  <Toggle
                    checked={sub.monitored}
                    onChange={() => handleToggle(sub, "monitored")}
                    disabled={toggleMutation.isPending}
                    label={`Toggle monitored for ${sub.subscription_name || sub.name}`}
                  />
                </td>
              </tr>
            ))}
            {subs.length === 0 && (
              <tr>
                <td colSpan={6} className="py-8 text-center text-gray-400">
                  No subscriptions configured. Click <strong>Add</strong> or{" "}
                  <strong>Discover from Azure</strong> to get started.
                </td>
              </tr>
            )}
            {subs.length > 0 && visibleSubs.length === 0 && (
              <tr>
                <td colSpan={6} className="py-8 text-center text-gray-400">
                  No subscriptions match the current search or filter.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};

// ── System Health ─────────────────────────────────────────────────────

const SystemHealth: React.FC<{
  health: { database: string; api: string };
  checkedAtLabel: string;
}> = ({ health, checkedAtLabel }) => {
  const components = [
    {
      name: "PostgreSQL Database",
      detail: "Portal data and the page cache (both live in PostgreSQL).",
      status: health.database,
      icon: (
        <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
        </svg>
      ),
    },
    {
      name: "Azure Management API",
      detail: "Service principal token plus a subscription list call to management.azure.com (re-checked at most once a minute).",
      status: health.api,
      icon: (
        <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 00-9.78 2.096A4.001 4.001 0 003 15z" />
        </svg>
      ),
    },
  ];

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-800">System Health</h3>
        <span className="text-xs text-gray-500">Checked {checkedAtLabel}</span>
      </div>
      <div className="space-y-3">
        {components.map((c) => (
          <div key={c.name} className="flex items-center justify-between gap-3 p-3 bg-gray-50 rounded-lg">
            <div className="flex items-center gap-3">
              <span className="text-xl">{c.icon}</span>
              <div>
                <p className="font-medium text-gray-700">{c.name}</p>
                <p className="text-xs text-gray-500">{c.detail}</p>
              </div>
            </div>
            <StatusBadge status={c.status} />
          </div>
        ))}
      </div>
    </div>
  );
};

// ── Certificate Collections Admin ─────────────────────────────────

const sameIds = (a: Set<number>, b: number[]) => a.size === b.length && b.every((id) => a.has(id));

const CertificateCollectionsAdmin: React.FC = () => {
  const { data: allCollections, isLoading: loadingAll, error: allError } = useAllCollections();
  const { data: enabledConfig, isLoading: loadingEnabled, error: enabledError } = useEnabledCollections();
  const setEnabled = useSetEnabledCollections();
  const [selected, setSelected] = useState<Set<number>>(new Set());
  const [initialized, setInitialized] = useState(false);
  const [search, setSearch] = useState("");

  // Initialize selection from config
  useEffect(() => {
    if (enabledConfig && !initialized) {
      setSelected(new Set(enabledConfig.collection_ids));
      setInitialized(true);
    }
  }, [enabledConfig, initialized]);

  const toggleCollection = (id: number) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const filteredCollections = (allCollections ?? []).filter(
    (c) => !search.trim() || c.name.toLowerCase().includes(search.toLowerCase())
  );

  // With a search active these act on the matching collections only.
  const selectAll = () => {
    setSelected((prev) => new Set([...prev, ...filteredCollections.map((c) => c.id)]));
  };
  const deselectAll = () => {
    const visible = new Set(filteredCollections.map((c) => c.id));
    setSelected((prev) => new Set([...prev].filter((id) => !visible.has(id))));
  };

  const handleSave = () => {
    setEnabled.mutate(Array.from(selected));
  };

  const isLoading = loadingAll || loadingEnabled;
  const loadError = allError || enabledError;
  const isDirty = initialized && !sameIds(selected, enabledConfig?.collection_ids ?? []);

  return (
    <div className="mt-6 bg-white rounded-xl border border-gray-200 overflow-hidden">
      <div className="flex items-center justify-between border-b border-gray-100 bg-gray-50/70 px-5 py-4">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">Certificate Collections</h3>
          <p className="text-xs text-gray-500 mt-0.5">Select which Keyfactor collections are visible in the Certificate module. Unselected collections will be hidden from all users.</p>
        </div>
        <div className="flex items-center gap-2">
          {setEnabled.isError ? (
            <span className="text-xs text-red-600">{apiErrorMessage(setEnabled.error, "Save failed.")}</span>
          ) : setEnabled.isSuccess && !isDirty ? (
            <span className="text-xs text-green-700">Saved</span>
          ) : isDirty ? (
            <span className="text-xs text-amber-700">Unsaved changes</span>
          ) : null}
          <span className="text-xs text-gray-500">{selected.size} of {allCollections?.length ?? 0} enabled</span>
          <button
            type="button"
            onClick={handleSave}
            disabled={setEnabled.isPending || !isDirty}
            className="rounded-lg bg-blue-600 px-4 py-2 text-xs font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
          >
            {setEnabled.isPending ? "Saving…" : "Save"}
          </button>
        </div>
      </div>

      <div className="px-5 py-3 border-b border-gray-100 flex items-center gap-3">
        <input
          type="text"
          placeholder="Search collections…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="flex-1 rounded-lg border border-gray-200 px-3 py-2 text-sm focus:border-blue-400 focus:outline-none focus:ring-2 focus:ring-blue-100"
        />
        <button type="button" onClick={selectAll} className="text-xs font-medium text-blue-600 hover:underline">Select All</button>
        <button type="button" onClick={deselectAll} className="text-xs font-medium text-red-600 hover:underline">Deselect All</button>
      </div>

      <div className="max-h-[320px] overflow-y-auto px-5 py-3">
        {isLoading ? (
          <p className="text-sm text-gray-500 py-4 text-center">Loading collections from Keyfactor…</p>
        ) : loadError ? (
          <p role="alert" className="text-sm text-red-600 py-4 text-center">
            Could not load collections: {apiErrorMessage(loadError, "Keyfactor did not respond.")}
          </p>
        ) : !filteredCollections.length ? (
          <p className="text-sm text-gray-500 py-4 text-center">No collections found.</p>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {filteredCollections.map((c) => (
              <label key={c.id} className={`flex items-center gap-3 rounded-lg border px-3 py-2.5 cursor-pointer transition ${
                selected.has(c.id) ? "border-blue-300 bg-blue-50" : "border-gray-200 hover:bg-gray-50"
              }`}>
                <input
                  type="checkbox"
                  checked={selected.has(c.id)}
                  onChange={() => toggleCollection(c.id)}
                  className="h-4 w-4 rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                />
                <span className="text-sm text-gray-800 truncate">{c.name}</span>
              </label>
            ))}
          </div>
        )}
      </div>

      {initialized && selected.size === 0 && (
        <div className="px-5 py-2 bg-amber-50 border-t border-amber-100 text-xs text-amber-700">
          No collections selected — all collections {isDirty ? "will be" : "are"} visible. Select specific collections to restrict access.
        </div>
      )}
    </div>
  );
};

// ── Admin Utilities Link ─────────────────────────────────────────────

const AdminUtilities: React.FC = () => (
  <div className="bg-white rounded-xl p-4 border">
    <h3 className="text-sm font-semibold mb-2">Admin Utilities</h3>
    <div className="flex gap-3">
      <Link to="/admin/permissions" className="px-3 py-2 bg-att-50 text-att-700 border border-att-100 rounded-md text-sm font-medium hover:bg-att-100">Manage Permissions</Link>
    </div>
  </div>
);

// ── Config helpers ────────────────────────────────────────────────────

/** "Changed by x · date" from the admin_config row, so admins can see who last touched a setting. */
const ConfigChangedBy: React.FC<{ entry?: AdminConfigEntry }> = ({ entry }) => {
  const { formatDate } = usePortalTimezone();
  if (!entry?.updated_at) return null;
  return (
    <p className="mt-1 text-[11px] text-gray-400">
      Changed {entry.updated_by ? `by ${entry.updated_by} · ` : ""}
      {formatDate(entry.updated_at)}
    </p>
  );
};

const InlineError: React.FC<{ error: unknown; fallback: string }> = ({ error, fallback }) =>
  error ? <p role="alert" className="mt-2 text-xs text-red-700">{apiErrorMessage(error, fallback)}</p> : null;

// ── Timezone Selector ─────────────────────────────────────────────────

const TimezoneSelector: React.FC<{ entry?: AdminConfigEntry }> = ({ entry }) => {
  const { timezone } = usePortalTimezone();
  const tzMutation = useUpdatePortalTimezone();
  const [selected, setSelected] = useState(timezone);

  useEffect(() => {
    setSelected(timezone);
  }, [timezone]);

  const handleChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const tz = e.target.value;
    setSelected(tz);
    try {
      await tzMutation.mutateAsync(tz);
    } catch {
      setSelected(timezone);
    }
  };

  const currentLabel = TIMEZONE_OPTIONS.find((o) => o.value === timezone)?.label ?? timezone;

  return (
    <div>
      <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">Portal Timezone</p>
      <div className="flex items-center gap-3">
        <select
          value={selected}
          onChange={handleChange}
          disabled={tzMutation.isPending}
          aria-label="Portal timezone"
          className="flex-1 px-3 py-2 border border-gray-300 rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500 disabled:opacity-50"
        >
          {TIMEZONE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        {tzMutation.isPending && (
          <span className="text-xs text-gray-500 animate-pulse">Saving…</span>
        )}
        {tzMutation.isSuccess && !tzMutation.isPending && (
          <span className="text-xs text-green-600">Saved</span>
        )}
      </div>
      <InlineError error={tzMutation.error} fallback="Failed to save the timezone." />
      <p className="text-xs text-gray-500 mt-1">
        All dates and times across the portal will be displayed in <strong>{currentLabel}</strong>.
      </p>
      <ConfigChangedBy entry={entry} />
    </div>
  );
};

// ── Configuration Panel ───────────────────────────────────────────────

const RPM_MIN = 10;
const RPM_MAX = 10000;
const TTL_MAX_MINUTES = 10080;

const ConfigPanel: React.FC<{
  environment: string;
  version: string;
  rateLimitRpm: number;
  cacheTtl: number;
  corsOrigins: string[];
  cacheEnabled: boolean;
  ollamaEnabled: boolean;
}> = ({ environment, version, rateLimitRpm, cacheTtl, corsOrigins, cacheEnabled, ollamaEnabled }) => {
  const [editingTtl, setEditingTtl] = useState(false);
  const [editingCors, setEditingCors] = useState(false);
  const [editingRpm, setEditingRpm] = useState(false);
  const [rpmValue, setRpmValue] = useState(String(rateLimitRpm));
  const [ttlMode, setTtlMode] = useState<"timed" | "unlimited">(
    cacheTtl <= 0 ? "unlimited" : "timed"
  );
  const [ttlMinutes, setTtlMinutes] = useState(
    cacheTtl <= 0 ? "60" : String(Math.max(1, Math.round(cacheTtl / 60)))
  );
  const [corsText, setCorsText] = useState(corsOrigins.join("\n"));
  // One mutation per setting, so a save or failure on one control never
  // shows up as "Saved"/an error beside another.
  const rpmMutation = useUpsertAdminConfig();
  const ttlMutation = useUpsertAdminConfig();
  const corsMutation = useUpsertAdminConfig();
  const cacheMutation = useUpsertAdminConfig();
  const ollamaMutation = useUpsertAdminConfig();
  const releaseCache = useReleaseOperationalCache();
  const { data: configEntries } = useAdminConfigs();
  const configByKey = useMemo(
    () => new Map((configEntries ?? []).map((entry) => [entry.config_key, entry])),
    [configEntries],
  );

  const isUnlimitedCache = cacheTtl <= 0;
  const rpmParsed = Number(rpmValue);
  const rpmInvalid = !Number.isInteger(rpmParsed) || rpmParsed < RPM_MIN || rpmParsed > RPM_MAX;
  const ttlParsed = Number(ttlMinutes);
  const ttlInvalid =
    ttlMode === "timed" && (!Number.isInteger(ttlParsed) || ttlParsed < 1 || ttlParsed > TTL_MAX_MINUTES);

  const handleToggleCache = () => {
    cacheMutation.mutate({
      config_key: "cache_enabled",
      config_value: cacheEnabled ? "false" : "true",
    });
  };

  const handleToggleOllama = () => {
    ollamaMutation.mutate({
      config_key: "ollama_enabled",
      config_value: ollamaEnabled ? "false" : "true",
    });
  };

  // Sync local state when the prop updates after a refetch
  useEffect(() => {
    if (!editingTtl) {
      setTtlMode(cacheTtl <= 0 ? "unlimited" : "timed");
      setTtlMinutes(cacheTtl <= 0 ? "60" : String(Math.max(1, Math.round(cacheTtl / 60))));
    }
  }, [cacheTtl, editingTtl]);

  useEffect(() => {
    if (!editingCors) {
      setCorsText(corsOrigins.join("\n"));
    }
  }, [corsOrigins, editingCors]);

  useEffect(() => {
    if (!editingRpm) {
      setRpmValue(String(rateLimitRpm));
    }
  }, [rateLimitRpm, editingRpm]);

  const handleSaveRpm = () => {
    if (rpmInvalid) return;
    rpmMutation.mutate(
      { config_key: "rate_limit_rpm", config_value: String(rpmParsed) },
      { onSuccess: () => setEditingRpm(false) },
    );
  };

  const handleSaveTtl = () => {
    if (ttlInvalid) return;
    ttlMutation.mutate(
      {
        config_key: "cache_ttl_seconds",
        config_value: ttlMode === "unlimited" ? "0" : String(ttlParsed * 60),
      },
      { onSuccess: () => setEditingTtl(false) },
    );
  };

  const handleSaveCors = () => {
    corsMutation.mutate(
      {
        config_key: "cors_origins",
        config_value: corsText,
        description: "Allowed browser origins for Ops Portal API CORS.",
      },
      { onSuccess: () => setEditingCors(false) },
    );
  };

  const envColor =
    environment === "production"
      ? "bg-red-100 text-red-800"
      : environment === "staging"
        ? "bg-yellow-100 text-yellow-800"
        : "bg-green-100 text-green-800";

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
      <h3 className="text-lg font-semibold text-gray-800 mb-4">Portal Configuration</h3>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-4">
          <div className="p-3 bg-gray-50 rounded-lg">
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Environment</p>
            <span className={`inline-flex px-2.5 py-0.5 rounded-full text-xs font-bold ${envColor}`}>
              {environment.toUpperCase()}
            </span>
          </div>
          <div className="p-3 bg-gray-50 rounded-lg">
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Version</p>
            <p className="text-lg font-bold text-gray-900">v{version}</p>
          </div>
          <div className="p-3 bg-gray-50 rounded-lg">
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Rate Limit</p>
            {editingRpm ? (
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="number"
                  min={RPM_MIN}
                  max={RPM_MAX}
                  value={rpmValue}
                  onChange={(e) => setRpmValue(e.target.value)}
                  aria-label="Rate limit (requests per minute)"
                  className="w-24 px-2 py-1 border border-gray-300 rounded text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
                <span className="text-sm text-gray-500">req/min</span>
                <button
                  onClick={handleSaveRpm}
                  disabled={rpmMutation.isPending || rpmInvalid}
                  className="px-2 py-1 bg-blue-600 text-white rounded text-xs font-semibold hover:bg-blue-700 disabled:opacity-50"
                >
                  {rpmMutation.isPending ? "…" : "Save"}
                </button>
                <button
                  onClick={() => {
                    setEditingRpm(false);
                    setRpmValue(String(rateLimitRpm));
                    rpmMutation.reset();
                  }}
                  className="px-2 py-1 bg-gray-100 text-gray-600 rounded text-xs font-semibold hover:bg-gray-200"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <p className="text-lg font-bold text-gray-900">
                  {rateLimitRpm} <span className="text-sm font-normal text-gray-500">req/min</span>
                </p>
                <button
                  onClick={() => setEditingRpm(true)}
                  className="p-1 text-gray-400 hover:text-blue-600 rounded transition-colors"
                  title="Edit Rate Limit"
                  aria-label="Edit rate limit"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                  </svg>
                </button>
              </div>
            )}
            {editingRpm && rpmInvalid && (
              <p className="mt-2 text-xs text-red-700">Enter a whole number between {RPM_MIN} and {RPM_MAX}.</p>
            )}
            <InlineError error={rpmMutation.error} fallback="Failed to save the rate limit." />
            <p className="mt-2 text-xs text-gray-500">
              Per client IP, counted separately by each API worker. Other workers apply a change within 30 seconds.
            </p>
            <ConfigChangedBy entry={configByKey.get("rate_limit_rpm")} />
          </div>
          <div className="p-3 bg-gray-50 rounded-lg">
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Page Cache TTL</p>
            {editingTtl ? (
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="number"
                  min={1}
                  max={TTL_MAX_MINUTES}
                  value={ttlMinutes}
                  onChange={(e) => setTtlMinutes(e.target.value)}
                  disabled={ttlMode === "unlimited"}
                  aria-label="Page cache TTL (minutes)"
                  className="w-20 px-2 py-1 border border-gray-300 rounded text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
                <span className="text-sm text-gray-500">min</span>
                <label className="inline-flex items-center gap-2 text-sm text-gray-600">
                  <input
                    type="checkbox"
                    checked={ttlMode === "unlimited"}
                    onChange={(e) => setTtlMode(e.target.checked ? "unlimited" : "timed")}
                    className="rounded border-gray-300 text-blue-600 focus:ring-blue-500"
                  />
                  Unlimited
                </label>
                <button
                  onClick={handleSaveTtl}
                  disabled={ttlMutation.isPending || ttlInvalid}
                  className="px-2 py-1 bg-blue-600 text-white rounded text-xs font-semibold hover:bg-blue-700 disabled:opacity-50"
                >
                  {ttlMutation.isPending ? "…" : "Save"}
                </button>
                <button
                  onClick={() => {
                    setEditingTtl(false);
                    setTtlMode(cacheTtl <= 0 ? "unlimited" : "timed");
                    setTtlMinutes(cacheTtl <= 0 ? "60" : String(Math.max(1, Math.round(cacheTtl / 60))));
                    ttlMutation.reset();
                  }}
                  className="px-2 py-1 bg-gray-100 text-gray-600 rounded text-xs font-semibold hover:bg-gray-200"
                >
                  Cancel
                </button>
              </div>
            ) : (
              <div className="flex items-center gap-2">
                <p className="text-lg font-bold text-gray-900">
                  {isUnlimitedCache ? (
                    <>
                      Unlimited <span className="text-sm font-normal text-gray-500">retention</span>
                    </>
                  ) : (
                    <>
                      {Math.round(cacheTtl / 60)} <span className="text-sm font-normal text-gray-500">min</span>
                    </>
                  )}
                </p>
                <button
                  onClick={() => setEditingTtl(true)}
                  className="p-1 text-gray-400 hover:text-blue-600 rounded transition-colors"
                  title="Edit Cache TTL"
                  aria-label="Edit page cache TTL"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                  </svg>
                </button>
              </div>
            )}
            {editingTtl && ttlInvalid && (
              <p className="mt-2 text-xs text-red-700">Enter whole minutes between 1 and {TTL_MAX_MINUTES} (7 days).</p>
            )}
            <InlineError error={ttlMutation.error} fallback="Failed to save the cache TTL." />
            <p className="mt-2 text-xs text-gray-500">
              Applies to Leadership dashboard, Leadership advisor/forecast, and Amortized payload caches only. Other pages use database snapshots or live API calls instead of page cache.
            </p>
            <ConfigChangedBy entry={configByKey.get("cache_ttl_seconds")} />
          </div>
        </div>

        {/* Page Cache Toggle */}
        <div className="rounded-xl border border-att-100 bg-att-50/50 p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-gray-800">Page Cache</p>
              <p className="text-xs text-gray-500">
                When disabled, Leadership Dashboard reads directly from the database (or Azure API fallback). Advisor and forecast caches are also bypassed.
              </p>
              <ConfigChangedBy entry={configByKey.get("cache_enabled")} />
            </div>
            <button
              onClick={handleToggleCache}
              disabled={cacheMutation.isPending}
              aria-pressed={cacheEnabled}
              aria-label="Page cache"
              className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold transition disabled:opacity-50 ${
                cacheEnabled
                  ? "border-green-200 bg-green-50 text-green-700 hover:bg-green-100"
                  : "border-red-200 bg-red-50 text-red-700 hover:bg-red-100"
              }`}
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                {cacheEnabled ? (
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                ) : (
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
                )}
              </svg>
              {cacheMutation.isPending ? "Updating…" : cacheEnabled ? "Enabled" : "Disabled"}
            </button>
          </div>
          <InlineError error={cacheMutation.error} fallback="Failed to update the page cache setting." />
        </div>

        {/* Ollama LLM Toggle */}
        <div className="rounded-xl border border-att-100 bg-att-50/50 p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-gray-800">Ollama LLM (AI Forecasts &amp; Advisor)</p>
              <p className="text-xs text-gray-500">
                When enabled, Leadership Dashboard uses Ollama LLM for AI-powered forecasts and executive advisor guidance. When disabled, the system falls back to local heuristic projections.
              </p>
              <ConfigChangedBy entry={configByKey.get("ollama_enabled")} />
            </div>
            <button
              onClick={handleToggleOllama}
              disabled={ollamaMutation.isPending}
              aria-pressed={ollamaEnabled}
              aria-label="Ollama LLM"
              className={`inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-sm font-semibold transition disabled:opacity-50 ${
                ollamaEnabled
                  ? "border-green-200 bg-green-50 text-green-700 hover:bg-green-100"
                  : "border-red-200 bg-red-50 text-red-700 hover:bg-red-100"
              }`}
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                {ollamaEnabled ? (
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
                ) : (
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
                )}
              </svg>
              {ollamaMutation.isPending ? "Updating…" : ollamaEnabled ? "Enabled" : "Disabled"}
            </button>
          </div>
          <InlineError error={ollamaMutation.error} fallback="Failed to update the Ollama setting." />
        </div>

        <div className="rounded-xl border border-att-100 bg-att-50/50 p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-gray-800">Cached data release</p>
              <p className="text-xs text-gray-500">
                Clear cached page payloads immediately when you want the next request to rebuild from DB or fresh Azure-backed sync data.
              </p>
            </div>
            <button
              onClick={() => releaseCache.mutate()}
              disabled={releaseCache.isPending}
              className="inline-flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm font-semibold text-red-700 hover:bg-red-100 disabled:opacity-50"
            >
              <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 7h12M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2m-7 0l1 12h6l1-12M10 11v6m4-6v6" />
              </svg>
              {releaseCache.isPending ? "Releasing…" : "Release Cached Data"}
            </button>
          </div>
          {releaseCache.isSuccess ? (
            <p className="mt-3 text-xs text-green-700">
              Released {releaseCache.data.released_keys} cached key(s). The next dashboard requests will rebuild fresh payloads.
            </p>
          ) : null}
          <InlineError error={releaseCache.error} fallback="Failed to release cached data." />
        </div>

        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">CORS Origins</p>
          {editingCors ? (
            <div className="space-y-3">
              <textarea
                value={corsText}
                onChange={(e) => setCorsText(e.target.value)}
                rows={5}
                aria-label="CORS origins"
                placeholder="One origin per line, for example:
http://localhost:5173
http://127.0.0.1:5173"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <div className="flex items-center gap-2">
                <button
                  onClick={handleSaveCors}
                  disabled={corsMutation.isPending || !corsText.trim()}
                  className="px-3 py-1.5 bg-blue-600 text-white rounded text-xs font-semibold hover:bg-blue-700 disabled:opacity-50"
                >
                  {corsMutation.isPending ? "Saving…" : "Save CORS"}
                </button>
                <button
                  onClick={() => {
                    setEditingCors(false);
                    setCorsText(corsOrigins.join("\n"));
                    corsMutation.reset();
                  }}
                  className="px-3 py-1.5 bg-gray-100 text-gray-600 rounded text-xs font-semibold hover:bg-gray-200"
                >
                  Cancel
                </button>
              </div>
              <InlineError error={corsMutation.error} fallback="Failed to update CORS origins." />
            </div>
          ) : (
            <>
              <div className="flex flex-wrap gap-2">
                {corsOrigins.map((origin) => (
                  <span key={origin} className="text-xs bg-gray-100 text-gray-700 px-2 py-1 rounded font-mono">
                    {origin}
                  </span>
                ))}
              </div>
              <div className="mt-3 flex items-center gap-3">
                <button
                  onClick={() => setEditingCors(true)}
                  className="inline-flex items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs font-semibold text-blue-700 hover:bg-blue-100"
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                  </svg>
                  Edit CORS Origins
                </button>
                {corsMutation.isSuccess ? <span className="text-xs text-green-700">Saved</span> : null}
              </div>
            </>
          )}
          <p className="mt-2 text-xs text-gray-500">
            Only needed for browser apps that call the API from a different origin — the portal itself reaches the API
            same-origin through its <code>/api</code> proxy. One full <code>http://</code> or <code>https://</code> origin per
            line; other workers pick up changes within 30 seconds.
          </p>
          <ConfigChangedBy entry={configByKey.get("cors_origins")} />
        </div>

        {/* Portal Timezone */}
        <TimezoneSelector entry={configByKey.get("portal_timezone")} />
      </div>
    </div>
  );
};

// ── Main Component ────────────────────────────────────────────────────

const AdminDashboard: React.FC = () => {
  const { data, isLoading, error } = useAdminDashboard();
  const { formatDate } = usePortalTimezone();
  const [showAddForm, setShowAddForm] = useState(false);
  const [scopeFilter, setScopeFilter] = useState<ScopeFilter>("all");

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[60vh]">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto" />
          <p className="mt-4 text-gray-500">Loading admin data…</p>
        </div>
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="py-6">
        <div className="bg-red-50 border border-red-200 rounded-xl p-6 text-center">
          <p className="text-red-700 font-semibold">Failed to load admin dashboard</p>
          <p className="text-red-600 text-sm mt-1">{apiErrorMessage(error, String(error ?? "No data returned."))}</p>
        </div>
      </div>
    );
  }

  const inScopeCount = data.subscriptions.filter(isInScope).length;
  const outOfScopeCount = data.subscriptions.length - inScopeCount;
  const unhealthy = [
    data.system_health.database !== "connected" && "Database",
    data.system_health.api !== "healthy" && "Azure API",
  ].filter(Boolean) as string[];

  const toggleScopeFilter = (filter: ScopeFilter) =>
    setScopeFilter((current) => (current === filter ? "all" : filter));

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
          <svg className="h-8 w-8 text-att-500" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68 1.65 1.65 0 0 0 10 3.17V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
          Admin Dashboard
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Last updated {formatDate(data.generated_at)}
        </p>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          title="Total Subscriptions"
          value={data.subscription_count}
          subtitle="registered in the portal"
          icon={MetricCardIcons.layers()}
          tone="blue"
          onClick={() => setScopeFilter("all")}
          active={scopeFilter === "all"}
          actionLabel="Show all subscriptions"
        />
        <MetricCard
          title="In Scope"
          value={inScopeCount}
          subtitle="enabled & monitored — synced and on dashboards"
          icon={MetricCardIcons.checkCircle()}
          tone="emerald"
          onClick={() => toggleScopeFilter("in")}
          active={scopeFilter === "in"}
          actionLabel="Show in-scope subscriptions"
        />
        <MetricCard
          title="Not In Scope"
          value={outOfScopeCount}
          subtitle="disabled or unmonitored — not synced"
          icon={MetricCardIcons.alert()}
          tone={outOfScopeCount ? "amber" : "slate"}
          onClick={() => toggleScopeFilter("out")}
          active={scopeFilter === "out"}
          actionLabel="Show subscriptions that are not in scope"
        />
        <MetricCard
          title="System Health"
          value={unhealthy.length ? "Degraded" : "Healthy"}
          subtitle={unhealthy.length ? `${unhealthy.join(" & ")} failing` : "Database & Azure API reachable"}
          icon={MetricCardIcons.activity()}
          tone={unhealthy.length ? "red" : "green"}
        />
      </div>

      {/* Main content grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 items-start">
        <div className="space-y-6">
          <SystemHealth health={data.system_health} checkedAtLabel={formatDate(data.generated_at)} />
          <AdminUtilities />
        </div>
        <ConfigPanel
          environment={data.environment}
          version={data.version}
          rateLimitRpm={data.rate_limit_rpm}
          cacheTtl={data.cache_ttl_seconds}
          corsOrigins={data.cors_origins}
          cacheEnabled={data.cache_enabled ?? true}
          ollamaEnabled={data.ollama_enabled ?? true}
        />
      </div>

      {/* Add Subscription Form */}
      {showAddForm && <AddSubscriptionForm onClose={() => setShowAddForm(false)} />}

      {/* Subscription Table */}
      <SubscriptionTable
        subs={data.subscriptions}
        onShowAdd={() => setShowAddForm(true)}
        scopeFilter={scopeFilter}
        onScopeFilterChange={setScopeFilter}
      />

      {/* Certificate Collections Admin */}
      <CertificateCollectionsAdmin />
    </div>
  );
};

export default AdminDashboard;
