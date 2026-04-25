/**
 * Admin Dashboard — subscription management, system health, and configuration.
 *
 * Supports CRUD for subscriptions via DB-backed endpoints:
 *  - Enable / disable / monitor toggle per subscription
 *  - Add new subscription manually
 *  - Discover subscriptions from Azure ARM
 *  - Delete subscriptions
 *  - Admin config management
 */

import React, { useState, useCallback, useEffect } from "react";
import {
  useAdminDashboard,
  useAdminSubscriptions,
  useAddSubscription,
  useToggleSubscription,
  useDiscoverSubscriptions,
  useSyncSubscriptions,
  useUpsertAdminConfig,
  useReleaseOperationalCache,
  SubscriptionInfo,
} from "../services/costApi";
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
    degraded: "bg-yellow-100 text-yellow-800",
    configured: "bg-blue-100 text-blue-800",
    Unknown: "bg-gray-100 text-gray-600",
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

const AddSubscriptionForm: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const [subId, setSubId] = useState("");
  const [subName, setSubName] = useState("");
  const [env, setEnv] = useState("");
  const [notes, setNotes] = useState("");
  const addMutation = useAddSubscription();

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!subId.trim()) return;
    await addMutation.mutateAsync({
      subscription_id: subId.trim(),
      subscription_name: subName.trim() || undefined,
      environment: env.trim() || undefined,
      notes: notes.trim() || undefined,
      enabled: true,
    });
    onClose();
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
          </div>
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Display Name</label>
            <input
              type="text"
              value={subName}
              onChange={(e) => setSubName(e.target.value)}
              placeholder="e.g. ATTCC Production"
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
            disabled={addMutation.isPending || !subId.trim()}
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
              {(addMutation.error as Error)?.message || "Failed to add"}
            </span>
          )}
        </div>
      </form>
    </div>
  );
};

// ── Subscription Table ────────────────────────────────────────────────

const SubscriptionTable: React.FC<{
  subs: SubscriptionInfo[];
  onShowAdd: () => void;
}> = ({ subs, onShowAdd }) => {
  const toggleMutation = useToggleSubscription();
  const discoverMutation = useDiscoverSubscriptions();
  const syncMutation = useSyncSubscriptions();

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

  const enabledCount = subs.filter((s) => s.enabled).length;

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between mb-4 gap-3">
        <div>
          <h3 className="text-lg font-semibold text-gray-800">
            Managed Subscriptions
          </h3>
          <p className="text-sm text-gray-500">
            {enabledCount} enabled of {subs.length} total
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => discoverMutation.mutate()}
            disabled={discoverMutation.isPending}
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
          ({(discoverMutation.data as any)?.new_count ?? 0} new).
        </div>
      )}
      {syncMutation.isSuccess && (
        <div className="mb-4 p-3 bg-indigo-50 border border-indigo-200 rounded-lg text-sm text-indigo-800">
          Synced {(syncMutation.data as any)?.updated_count ?? 0} of{" "}
          {(syncMutation.data as any)?.discovered ?? 0} subscriptions.
        </div>
      )}

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
            {subs.map((sub) => (
              <tr
                key={sub.subscription_id}
                className={`border-b border-gray-50 hover:bg-gray-50 ${
                  !sub.enabled ? "opacity-60" : ""
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
          </tbody>
        </table>
      </div>
    </div>
  );
};

// ── System Health ─────────────────────────────────────────────────────

const SystemHealth: React.FC<{
  health: { database: string; cache: string; api: string };
  environment: string;
  rateLimitRpm: number;
  cacheTtl: number;
  corsOrigins: string[];
  generatedAtLabel: string;
}> = ({ health, environment, rateLimitRpm, cacheTtl, corsOrigins, generatedAtLabel }) => {
  const components = [
    {
      name: "PostgreSQL Database",
      status: health.database,
      icon: (
        <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5 text-indigo-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
        </svg>
      ),
    },
    {
      name: "Azure Cost API",
      status: health.api,
      icon: (
        <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 15a4 4 0 004 4h9a5 5 0 10-.1-9.999 5.002 5.002 0 00-9.78 2.096A4.001 4.001 0 003 15z" />
        </svg>
      ),
    },
    {
      name: "DB Cache",
      status: health.cache,
      icon: (
        <svg xmlns="http://www.w3.org/2000/svg" className="w-5 h-5 text-red-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M4 7v10c0 2.21 3.582 4 8 4s8-1.79 8-4V7M4 7c0 2.21 3.582 4 8 4s8-1.79 8-4M4 7c0-2.21 3.582-4 8-4s8 1.79 8 4m0 5c0 2.21-3.582 4-8 4s-8-1.79-8-4" />
        </svg>
      ),
    },
  ];

  const overall = components.every((c) => c.status === "healthy" || c.status === "connected")
    ? "healthy"
    : "degraded";
  const currentOrigin = typeof window !== "undefined" ? window.location.origin : "Unknown";
  const originAllowed = corsOrigins.includes(currentOrigin);
  const cacheLabel = cacheTtl <= 0 ? "Unlimited retention" : `${Math.round(cacheTtl / 60)} min TTL`;

  return (
    <div className="bg-white rounded-xl shadow-sm border border-gray-100 p-6">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-lg font-semibold text-gray-800">System Health</h3>
        <StatusBadge status={overall} />
      </div>
      <div className="space-y-3">
        {components.map((c) => (
          <div key={c.name} className="flex items-center justify-between p-3 bg-gray-50 rounded-lg">
            <div className="flex items-center gap-3">
              <span className="text-xl">{c.icon}</span>
              <span className="font-medium text-gray-700">{c.name}</span>
            </div>
            <StatusBadge status={c.status} />
          </div>
        ))}
      </div>

      <div className="mt-5 rounded-xl border border-att-100 bg-gradient-to-br from-att-50/80 via-white to-att-50/40 p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-[0.16em] text-slate-500">Runtime Overview</p>
            <p className="mt-1 text-sm text-slate-600">Operational context for the current browser session and API configuration.</p>
          </div>
          <StatusBadge status={originAllowed ? "enabled" : "degraded"} />
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          <div className="rounded-lg border border-white/80 bg-white/90 p-3 shadow-sm">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Browser Origin</p>
            <p className="mt-1 break-all font-mono text-xs text-slate-700">{currentOrigin}</p>
            <p className={`mt-2 text-xs font-medium ${originAllowed ? "text-green-700" : "text-amber-700"}`}>
              {originAllowed ? "Allowed by current CORS configuration" : "Not present in current CORS configuration"}
            </p>
          </div>

          <div className="rounded-lg border border-white/80 bg-white/90 p-3 shadow-sm">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Allowed Origins</p>
            <p className="mt-1 text-2xl font-bold text-slate-900">{corsOrigins.length}</p>
            <p className="mt-2 text-xs text-slate-500">Admin-managed origins applied at runtime by the API.</p>
          </div>

          <div className="rounded-lg border border-white/80 bg-white/90 p-3 shadow-sm">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Environment</p>
            <p className="mt-1 text-sm font-semibold text-slate-800">{environment.toUpperCase()}</p>
            <p className="mt-2 text-xs text-slate-500">Rate limit configured at {rateLimitRpm} requests per minute.</p>
          </div>

          <div className="rounded-lg border border-white/80 bg-white/90 p-3 shadow-sm">
            <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-slate-500">Cache Policy</p>
            <p className="mt-1 text-sm font-semibold text-slate-800">{cacheLabel}</p>
            <p className="mt-2 text-xs text-slate-500">Dashboard snapshot generated {generatedAtLabel}.</p>
          </div>
        </div>
      </div>
    </div>
  );
};

// ── Page Footer Area ─────────────────────────────────────────────────

const PageFooterArea: React.FC = () => (
  <div className="mt-6 grid grid-cols-1 md:grid-cols-2 gap-6">
    <div>
      {/* Admin utilities */}
      <div className="bg-white rounded-xl p-4 border">
        <h3 className="text-sm font-semibold mb-2">Admin Utilities</h3>
        <div className="flex gap-3">
          <Link to="/admin/permissions" className="px-3 py-2 bg-att-50 text-att-700 border border-att-100 rounded-md text-sm font-medium hover:bg-att-100">Manage Permissions</Link>
        </div>
      </div>
    </div>
    <div>
      {/* Placeholder for future admin widgets */}
    </div>
  </div>
);

// Add AdminUtilities into the dashboard lower down — simple link to permissions UI

// ── Admin Utilities Link ─────────────────────────────────────────────

const AdminUtilities: React.FC = () => (
  <div className="mt-6 bg-white rounded-xl p-4 border">
    <h3 className="text-sm font-semibold mb-2">Admin Utilities</h3>
    <div className="flex gap-3">
      <Link to="/admin/permissions" className="px-3 py-2 bg-att-50 text-att-700 border border-att-100 rounded-md text-sm font-medium hover:bg-att-100">Manage Permissions</Link>
    </div>
  </div>
);

// ── Timezone Selector ─────────────────────────────────────────────────

const TimezoneSelector: React.FC = () => {
  const { timezone } = usePortalTimezone();
  const tzMutation = useUpdatePortalTimezone();
  const [selected, setSelected] = useState(timezone);

  useEffect(() => {
    setSelected(timezone);
  }, [timezone]);

  const handleChange = async (e: React.ChangeEvent<HTMLSelectElement>) => {
    const tz = e.target.value;
    setSelected(tz);
    await tzMutation.mutateAsync(tz);
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
      <p className="text-xs text-gray-500 mt-1">
        All dates and times across the portal will be displayed in <strong>{currentLabel}</strong>.
      </p>
    </div>
  );
};

// ── Configuration Panel ───────────────────────────────────────────────

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
  const upsertConfig = useUpsertAdminConfig();
  const releaseCache = useReleaseOperationalCache();
  const [togglingCache, setTogglingCache] = useState(false);
  const [togglingOllama, setTogglingOllama] = useState(false);

  const isUnlimitedCache = cacheTtl <= 0;

  const handleToggleCache = async () => {
    setTogglingCache(true);
    try {
      await upsertConfig.mutateAsync({
        config_key: "cache_enabled",
        config_value: cacheEnabled ? "false" : "true",
      });
    } finally {
      setTogglingCache(false);
    }
  };

  const handleToggleOllama = async () => {
    setTogglingOllama(true);
    try {
      await upsertConfig.mutateAsync({
        config_key: "ollama_enabled",
        config_value: ollamaEnabled ? "false" : "true",
      });
    } finally {
      setTogglingOllama(false);
    }
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

  const handleSaveRpm = async () => {
    const rpm = parseInt(rpmValue, 10);
    if (isNaN(rpm) || rpm < 10 || rpm > 10000) return;
    await upsertConfig.mutateAsync({
      config_key: "rate_limit_rpm",
      config_value: String(rpm),
    });
    setEditingRpm(false);
  };

  const handleSaveTtl = async () => {
    if (ttlMode === "unlimited") {
      await upsertConfig.mutateAsync({
        config_key: "cache_ttl_seconds",
        config_value: "0",
      });
      setEditingTtl(false);
      return;
    }

    const minutes = parseInt(ttlMinutes, 10);
    if (isNaN(minutes) || minutes < 1) return;
    await upsertConfig.mutateAsync({
      config_key: "cache_ttl_seconds",
      config_value: String(minutes * 60),
    });
    setEditingTtl(false);
  };

  const handleSaveCors = async () => {
    await upsertConfig.mutateAsync({
      config_key: "cors_origins",
      config_value: corsText,
      description: "Allowed browser origins for Ops Portal API CORS.",
    });
    setEditingCors(false);
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
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={10}
                  max={10000}
                  value={rpmValue}
                  onChange={(e) => setRpmValue(e.target.value)}
                  className="w-24 px-2 py-1 border border-gray-300 rounded text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
                <span className="text-sm text-gray-500">req/min</span>
                <button
                  onClick={handleSaveRpm}
                  disabled={upsertConfig.isPending}
                  className="px-2 py-1 bg-blue-600 text-white rounded text-xs font-semibold hover:bg-blue-700 disabled:opacity-50"
                >
                  {upsertConfig.isPending ? "…" : "Save"}
                </button>
                <button
                  onClick={() => {
                    setEditingRpm(false);
                    setRpmValue(String(rateLimitRpm));
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
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                  </svg>
                </button>
              </div>
            )}
          </div>
          <div className="p-3 bg-gray-50 rounded-lg">
            <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Page Cache TTL</p>
            {editingTtl ? (
              <div className="flex items-center gap-2">
                <input
                  type="number"
                  min={1}
                  max={10080}
                  value={ttlMinutes}
                  onChange={(e) => setTtlMinutes(e.target.value)}
                  disabled={ttlMode === "unlimited"}
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
                  disabled={upsertConfig.isPending}
                  className="px-2 py-1 bg-blue-600 text-white rounded text-xs font-semibold hover:bg-blue-700 disabled:opacity-50"
                >
                  {upsertConfig.isPending ? "…" : "Save"}
                </button>
                <button
                  onClick={() => {
                    setEditingTtl(false);
                    setTtlMode(cacheTtl <= 0 ? "unlimited" : "timed");
                    setTtlMinutes(cacheTtl <= 0 ? "60" : String(Math.max(1, Math.round(cacheTtl / 60))));
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
                >
                  <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
                  </svg>
                </button>
              </div>
            )}
            <p className="mt-2 text-xs text-gray-500">
              Applies to Leadership dashboard, Leadership advisor/forecast, and Amortized payload caches only. Other pages use database snapshots or live API calls instead of page cache.
            </p>
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
            </div>
            <button
              onClick={handleToggleCache}
              disabled={togglingCache}
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
              {togglingCache ? "Updating…" : cacheEnabled ? "Enabled" : "Disabled"}
            </button>
          </div>
        </div>

        {/* Ollama LLM Toggle */}
        <div className="rounded-xl border border-att-100 bg-att-50/50 p-4">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <p className="text-sm font-semibold text-gray-800">Ollama LLM (AI Forecasts &amp; Advisor)</p>
              <p className="text-xs text-gray-500">
                When enabled, Leadership Dashboard uses Ollama LLM for AI-powered forecasts and executive advisor guidance. When disabled, the system falls back to local heuristic projections.
              </p>
            </div>
            <button
              onClick={handleToggleOllama}
              disabled={togglingOllama}
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
              {togglingOllama ? "Updating…" : ollamaEnabled ? "Enabled" : "Disabled"}
            </button>
          </div>
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
          {releaseCache.isError ? (
            <p className="mt-3 text-xs text-red-700">Failed to release cached data.</p>
          ) : null}
        </div>

        <div>
          <p className="text-xs text-gray-500 uppercase tracking-wider mb-2">CORS Origins</p>
          {editingCors ? (
            <div className="space-y-3">
              <textarea
                value={corsText}
                onChange={(e) => setCorsText(e.target.value)}
                rows={5}
                placeholder="One origin per line, for example:
http://localhost:5173
http://127.0.0.1:5173"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono text-gray-700 focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
              <div className="flex items-center gap-2">
                <button
                  onClick={handleSaveCors}
                  disabled={upsertConfig.isPending}
                  className="px-3 py-1.5 bg-blue-600 text-white rounded text-xs font-semibold hover:bg-blue-700 disabled:opacity-50"
                >
                  {upsertConfig.isPending ? "Saving…" : "Save CORS"}
                </button>
                <button
                  onClick={() => {
                    setEditingCors(false);
                    setCorsText(corsOrigins.join("\n"));
                  }}
                  className="px-3 py-1.5 bg-gray-100 text-gray-600 rounded text-xs font-semibold hover:bg-gray-200"
                >
                  Cancel
                </button>
              </div>
              {upsertConfig.isError ? (
                <p className="text-xs text-red-700">
                  {(upsertConfig.error as any)?.response?.data?.detail || "Failed to update CORS origins."}
                </p>
              ) : null}
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
                {upsertConfig.isSuccess && !upsertConfig.isPending ? (
                  <span className="text-xs text-green-700">Saved</span>
                ) : null}
              </div>
            </>
          )}
          <p className="mt-2 text-xs text-gray-500">
            Applies to API CORS checks at runtime for Ops Portal origins. One origin per line. Use full `http://` or `https://` URLs only.
          </p>
        </div>

        {/* Portal Timezone */}
        <TimezoneSelector />
      </div>
    </div>
  );
};

// ── Main Component ────────────────────────────────────────────────────

const AdminDashboard: React.FC = () => {
  const { data, isLoading, error } = useAdminDashboard();
  const { formatDate } = usePortalTimezone();
  const [showAddForm, setShowAddForm] = useState(false);

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
          <p className="text-red-600 text-sm mt-1">{String(error)}</p>
        </div>
      </div>
    );
  }

  const enabledCount = data.enabled_count ?? data.subscriptions.filter((s) => s.enabled).length;

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Admin Dashboard</h1>
        <p className="text-sm text-gray-500">
          Last updated {formatDate(data.generated_at)}
        </p>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          title="Total Subscriptions"
          value={data.subscription_count}
          subtitle="configured in system"
          icon={MetricCardIcons.layers()}
          tone="blue"
        />
        <MetricCard
          title="Enabled"
          value={enabledCount}
          subtitle="actively monitored"
          icon={MetricCardIcons.checkCircle()}
          tone="emerald"
        />
        <MetricCard
          title="API Status"
          value={data.system_health.api}
          subtitle="Azure Cost Management API"
          icon={MetricCardIcons.activity()}
          tone="green"
          valueClassName="capitalize"
        />
        <MetricCard
          title="Cache"
          value={data.system_health.cache}
          subtitle="Database cache layer"
          icon={MetricCardIcons.cloud()}
          tone={data.system_health.cache === "connected" ? "green" : "amber"}
          valueClassName="capitalize"
        />
      </div>

      {/* Main content grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <SystemHealth
          health={data.system_health}
          environment={data.environment}
          rateLimitRpm={data.rate_limit_rpm}
          cacheTtl={data.cache_ttl_seconds}
          corsOrigins={data.cors_origins}
          generatedAtLabel={formatDate(data.generated_at)}
        />
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
      <SubscriptionTable subs={data.subscriptions} onShowAdd={() => setShowAddForm(true)} />
    </div>
  );
};

export default AdminDashboard;
