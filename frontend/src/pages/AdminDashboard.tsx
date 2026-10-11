/**
 * Admin Dashboard — subscription management, system health, and configuration.
 *
 * Supports subscription management via DB-backed endpoints:
 *  - Enable / disable / monitor toggle per subscription
 *  - Add new subscription manually
 *  - Discover subscriptions from Azure ARM
 *  - Edit name / environment / notes, and remove subscriptions
 *  - Admin config management
 *  - Activity grid of every change made here (audit_logs)
 */

import React, { useState, useCallback, useEffect, useMemo } from "react";
import {
  useAdminDashboard,
  useAdminConfigs,
  useAdminActivity,
  useAddSubscription,
  useToggleSubscription,
  useUpdateSubscription,
  useDeleteSubscription,
  useDiscoverSubscriptions,
  useSyncSubscriptions,
  useUpsertAdminConfig,
  useReleaseOperationalCache,
  SubscriptionInfo,
  AdminConfigEntry,
  AdminActivityEntry,
  EnvironmentOption,
} from "../services/costApi";
import { apiErrorMessage } from "../services/infraAlertApi";
import { SortableHeader, gridStyles } from "../components/gridStyles";
import {
  AccessIcons,
  ActionIconButton,
  ConfirmDialog,
  GridHeader,
  GridMessageRow,
  GridPagerBar,
  Modal,
  fieldLabel,
  inputClass,
  primaryButton,
  secondaryButton,
  textMatches,
  useGridRows,
} from "../features/access/accessShared";
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
    className={`relative inline-flex h-6 w-11 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent transition-colors duration-200 ease-in-out focus:outline-none focus:ring-2 focus:ring-att-300 focus:ring-offset-2 ${
      checked ? "bg-att-400" : "bg-gray-200"
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

/** Azure subscription state (Enabled / Disabled / Warned / PastDue / Deleted). */
const StatusBadge: React.FC<{ status: string }> = ({ status }) => {
  const colorMap: Record<string, string> = {
    Enabled: "bg-green-100 text-green-800",
    Unknown: "bg-gray-100 text-gray-600",
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

/** "Development — Non-Prod spend": what each Environment choice does to cost reporting. */
const environmentOptionLabel = (option: EnvironmentOption) => `${option.label} — ${option.cost_env} spend`;

const AddSubscriptionForm: React.FC<{ onClose: () => void; environmentOptions: EnvironmentOption[] }> = ({
  onClose,
  environmentOptions,
}) => {
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
              <option value="">Not set — classified from the name</option>
              {environmentOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {environmentOptionLabel(option)}
                </option>
              ))}
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

type SubscriptionSortKey = "name" | "environment" | "state";

const subscriptionLabel = (sub: SubscriptionInfo) => sub.subscription_name || sub.name || sub.subscription_id;

const subscriptionMatches = (sub: SubscriptionInfo, query: string) =>
  textMatches(query, sub.subscription_name, sub.name, sub.subscription_id, sub.environment, sub.cost_env);

const subscriptionAccessor = (sub: SubscriptionInfo, key: SubscriptionSortKey): string => {
  if (key === "environment") return sub.environment ?? "";
  if (key === "state") return sub.state ?? "";
  return subscriptionLabel(sub).toLowerCase();
};

const EditSubscriptionModal: React.FC<{
  sub: SubscriptionInfo;
  environmentOptions: EnvironmentOption[];
  onClose: () => void;
}> = ({ sub, environmentOptions, onClose }) => {
  const updateMutation = useUpdateSubscription();
  const [name, setName] = useState(subscriptionLabel(sub));
  const [environment, setEnvironment] = useState(sub.environment ?? "");
  const [notes, setNotes] = useState(sub.notes ?? "");
  // A free-text value saved before the dropdown existed stays selectable.
  const customEnvironment =
    sub.environment && !environmentOptions.some((option) => option.value === sub.environment) ? sub.environment : null;

  const handleSave = () => {
    updateMutation.mutate(
      { subscription_id: sub.subscription_id, subscription_name: name.trim(), environment, notes },
      { onSuccess: onClose },
    );
  };

  return (
    <Modal
      title="Edit subscription"
      subtitle={<span className="font-mono">{sub.subscription_id}</span>}
      onClose={onClose}
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButton} disabled={updateMutation.isPending}>
            Cancel
          </button>
          <button
            type="button"
            onClick={handleSave}
            className={primaryButton}
            disabled={updateMutation.isPending || !name.trim()}
          >
            {updateMutation.isPending ? "Saving…" : "Save"}
          </button>
        </>
      }
    >
      <div>
        <label className={fieldLabel} htmlFor="edit-sub-name">Display name</label>
        <input id="edit-sub-name" value={name} onChange={(e) => setName(e.target.value)} className={inputClass} />
      </div>
      <div>
        <label className={fieldLabel} htmlFor="edit-sub-env">Environment</label>
        <select id="edit-sub-env" value={environment} onChange={(e) => setEnvironment(e.target.value)} className={inputClass}>
          <option value="">Not set — classified from the name</option>
          {environmentOptions.map((option) => (
            <option key={option.value} value={option.value}>
              {environmentOptionLabel(option)}
            </option>
          ))}
          {customEnvironment && (
            <option value={customEnvironment}>
              {customEnvironment} (current) — {sub.cost_env} spend
            </option>
          )}
        </select>
        <p className="mt-1 text-xs text-gray-500">
          Decides whether this subscription&apos;s spend is reported as Prod or Non-Prod on the cost dashboards. It does
          not change who can see it — access tiers are set in Access Management.
        </p>
      </div>
      <div>
        <label className={fieldLabel} htmlFor="edit-sub-notes">Notes</label>
        <textarea id="edit-sub-notes" value={notes} onChange={(e) => setNotes(e.target.value)} rows={3} className={inputClass} />
      </div>
      <InlineError error={updateMutation.error} fallback="Failed to save the subscription." />
    </Modal>
  );
};

const SubscriptionTable: React.FC<{
  subs: SubscriptionInfo[];
  environmentOptions: EnvironmentOption[];
  onShowAdd: () => void;
  scopeFilter: ScopeFilter;
  onScopeFilterChange: (filter: ScopeFilter) => void;
}> = ({ subs, environmentOptions, onShowAdd, scopeFilter, onScopeFilterChange }) => {
  const toggleMutation = useToggleSubscription();
  const discoverMutation = useDiscoverSubscriptions();
  const syncMutation = useSyncSubscriptions();
  const deleteMutation = useDeleteSubscription();
  const [editTarget, setEditTarget] = useState<SubscriptionInfo | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<SubscriptionInfo | null>(null);

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

  const handleDelete = () => {
    if (!deleteTarget) return;
    deleteMutation.mutate(deleteTarget.subscription_id, { onSuccess: () => setDeleteTarget(null) });
  };

  const environmentLabels = useMemo(
    () => new Map(environmentOptions.map((option) => [option.value, option.label])),
    [environmentOptions],
  );
  const inScopeCount = subs.filter(isInScope).length;
  const scoped = useMemo(
    () =>
      subs.filter((sub) => scopeFilter === "all" || (scopeFilter === "in") === isInScope(sub)),
    [subs, scopeFilter],
  );
  const grid = useGridRows<SubscriptionInfo, SubscriptionSortKey>(scoped, {
    matches: subscriptionMatches,
    accessor: subscriptionAccessor,
    initialSort: { key: "name", direction: "asc" },
  });
  const header = (label: string, key: SubscriptionSortKey, center = false) => (
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

  const banners = [
    discoverMutation.isSuccess && (
      <div key="discover" className="p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-800">
        Discovered {(discoverMutation.data as any)?.discovered ?? 0} subscriptions
        ({(discoverMutation.data as any)?.new_count ?? 0} new, added disabled for review).
      </div>
    ),
    syncMutation.isSuccess && (
      <div key="sync" className="p-3 bg-att-50 border border-att-100 rounded-lg text-sm text-att-700">
        Synced {(syncMutation.data as any)?.updated_count ?? 0} of{" "}
        {(syncMutation.data as any)?.discovered ?? 0} subscriptions.
      </div>
    ),
    discoverMutation.isError && (
      <div key="discover-error" role="alert" className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
        Discover failed: {apiErrorMessage(discoverMutation.error, "Azure did not respond.")}
      </div>
    ),
    syncMutation.isError && (
      <div key="sync-error" role="alert" className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
        Sync failed: {apiErrorMessage(syncMutation.error, "Azure did not respond.")}
      </div>
    ),
    toggleMutation.isError && (
      <div key="toggle-error" role="alert" className="p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
        Could not update the subscription: {apiErrorMessage(toggleMutation.error, "request failed.")}
      </div>
    ),
  ].filter(Boolean);

  return (
    <div className={gridStyles.shell}>
      <GridHeader
        title="Managed Subscriptions"
        subtitle={`${inScopeCount} in scope (enabled & monitored) of ${subs.length} total`}
        search={grid.search}
        onSearch={grid.setSearch}
        placeholder="Search name, ID or environment…"
      >
        <div className="inline-flex rounded-lg border border-att-200 bg-white p-0.5" role="group" aria-label="Scope filter">
          {(Object.keys(SCOPE_FILTER_LABEL) as ScopeFilter[]).map((key) => (
            <button
              key={key}
              type="button"
              onClick={() => onScopeFilterChange(key)}
              aria-pressed={scopeFilter === key}
              className={`rounded-md px-3 py-1.5 text-xs font-semibold ${
                scopeFilter === key ? "bg-att-400 text-white" : "text-gray-600 hover:bg-att-50"
              }`}
            >
              {SCOPE_FILTER_LABEL[key]}
            </button>
          ))}
        </div>
        <button
          type="button"
          onClick={() => discoverMutation.mutate()}
          disabled={discoverMutation.isPending}
          title="Add subscriptions the service principal can see but the portal doesn't know yet (added disabled)"
          className={secondaryButton}
        >
          {discoverMutation.isPending ? "Discovering…" : "Discover from Azure"}
        </button>
        <button
          type="button"
          onClick={() => syncMutation.mutate()}
          disabled={syncMutation.isPending}
          title="Refresh name and state of existing subscriptions from Azure"
          className={secondaryButton}
        >
          {syncMutation.isPending ? "Syncing…" : "Sync"}
        </button>
        <button type="button" onClick={onShowAdd} className={primaryButton}>
          {AccessIcons.plus()}
          Add
        </button>
      </GridHeader>

      {banners.length > 0 && <div className="space-y-2 border-b border-att-100 px-4 py-3">{banners}</div>}

      <div className="overflow-x-auto">
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              {header("Name", "name")}
              <th className={gridStyles.headerCell}>Subscription ID</th>
              {header("Environment", "environment")}
              {header("State", "state", true)}
              <th className={gridStyles.headerCellCenter}>Enabled</th>
              <th className={gridStyles.headerCellCenter}>Monitored</th>
              <th className={gridStyles.headerCellCenter}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {subs.length === 0 ? (
              <GridMessageRow colSpan={7}>
                No subscriptions configured. Click <strong>Add</strong> or <strong>Discover from Azure</strong> to get started.
              </GridMessageRow>
            ) : grid.pageRows.length === 0 ? (
              <GridMessageRow colSpan={7}>No subscriptions match the current search or filter.</GridMessageRow>
            ) : (
              grid.pageRows.map((sub) => (
                <tr key={sub.subscription_id} className={`${gridStyles.row} ${!isInScope(sub) ? "opacity-60" : ""}`}>
                  <td className={gridStyles.strongCell}>{subscriptionLabel(sub)}</td>
                  <td className={gridStyles.monoCell}>{sub.subscription_id}</td>
                  <td className={gridStyles.cell}>
                    {sub.environment ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-gray-100 text-gray-700">
                        {environmentLabels.get(sub.environment) ?? sub.environment}
                      </span>
                    ) : (
                      <span className="text-gray-400 text-xs">Not set</span>
                    )}
                    {sub.cost_env && (
                      <p
                        className="mt-0.5 text-[11px] text-gray-500"
                        title="Bucket this subscription's spend is reported in on the cost dashboards"
                      >
                        {sub.cost_env} spend{!sub.environment ? " (from name)" : ""}
                      </p>
                    )}
                  </td>
                  <td className={gridStyles.centerCell}>
                    <StatusBadge status={sub.state} />
                  </td>
                  <td className={gridStyles.centerCell}>
                    <Toggle
                      checked={sub.enabled}
                      onChange={() => handleToggle(sub, "enabled")}
                      disabled={toggleMutation.isPending}
                      label={`Toggle enabled for ${subscriptionLabel(sub)}`}
                    />
                  </td>
                  <td className={gridStyles.centerCell}>
                    <Toggle
                      checked={sub.monitored}
                      onChange={() => handleToggle(sub, "monitored")}
                      disabled={toggleMutation.isPending}
                      label={`Toggle monitored for ${subscriptionLabel(sub)}`}
                    />
                  </td>
                  <td className={gridStyles.centerCell}>
                    <div className="inline-flex items-center gap-1">
                      <ActionIconButton title={`Edit ${subscriptionLabel(sub)}`} tone="att" onClick={() => setEditTarget(sub)}>
                        {AccessIcons.pen("h-[18px] w-[18px]")}
                      </ActionIconButton>
                      <ActionIconButton
                        title={`Remove ${subscriptionLabel(sub)}`}
                        tone="red"
                        onClick={() => {
                          deleteMutation.reset();
                          setDeleteTarget(sub);
                        }}
                      >
                        {AccessIcons.delete()}
                      </ActionIconButton>
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
        noun="subscriptions"
      />

      {editTarget && (
        <EditSubscriptionModal sub={editTarget} environmentOptions={environmentOptions} onClose={() => setEditTarget(null)} />
      )}
      {deleteTarget && (
        <ConfirmDialog
          title="Remove subscription?"
          message={
            <>
              <p>
                Remove <strong>{subscriptionLabel(deleteTarget)}</strong>{" "}
                <span className="font-mono text-xs">({deleteTarget.subscription_id})</span> from the portal? It stops being
                synced and drops off every dashboard.
              </p>
              <p className="mt-2 text-xs text-gray-500">
                Its cost history and any subscription-level access grants are kept. <strong>Discover from Azure</strong>{" "}
                adds it back as disabled while the service principal can still see it.
              </p>
            </>
          }
          confirmLabel="Remove"
          busy={deleteMutation.isPending}
          error={deleteMutation.isError ? apiErrorMessage(deleteMutation.error, "Failed to remove the subscription.") : null}
          onConfirm={handleDelete}
          onCancel={() => setDeleteTarget(null)}
        />
      )}
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

// ── Admin Activity ───────────────────────────────────────────────────

const ACTIVITY_LABELS: Record<string, string> = {
  admin_config_update: "Setting changed",
  admin_cache_release: "Cache released",
  admin_subscription_add: "Subscription added",
  admin_subscription_update: "Subscription edited",
  admin_subscription_delete: "Subscription removed",
  admin_subscription_toggle: "Scope changed",
  admin_subscription_discover: "Discover",
  admin_subscription_sync: "Sync",
  cert_enabled_collections_config: "Certificate collections",
};

const activityLabel = (entry: AdminActivityEntry) => ACTIVITY_LABELS[entry.action] ?? entry.action;

type ActivitySortKey = "timestamp" | "user" | "action";

const activityMatches = (entry: AdminActivityEntry, query: string) =>
  textMatches(query, entry.user_email, activityLabel(entry), entry.summary, entry.resource_id);

const activityAccessor = (entry: AdminActivityEntry, key: ActivitySortKey): string => {
  if (key === "user") return entry.user_email.toLowerCase();
  if (key === "action") return activityLabel(entry);
  return entry.timestamp ?? "";
};

const AdminActivity: React.FC = () => {
  const { data, isLoading, error } = useAdminActivity();
  const { formatDate } = usePortalTimezone();
  const grid = useGridRows<AdminActivityEntry, ActivitySortKey>(data ?? [], {
    matches: activityMatches,
    accessor: activityAccessor,
    initialSort: { key: "timestamp", direction: "desc" },
  });
  const header = (label: string, key: ActivitySortKey) => (
    <th className={gridStyles.headerCell}>
      <SortableHeader
        label={label}
        active={grid.sort.key === key}
        direction={grid.sort.direction}
        onClick={() => grid.toggleSort(key)}
      />
    </th>
  );

  return (
    <div className={gridStyles.shell}>
      <GridHeader
        title="Admin Activity"
        subtitle="Every change made on this page, from the audit log (latest 200)."
        search={grid.search}
        onSearch={grid.setSearch}
        placeholder="Search user, action or details…"
      />
      <div className="overflow-x-auto">
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              {header("When", "timestamp")}
              {header("User", "user")}
              {header("Action", "action")}
              <th className={gridStyles.headerCell}>Details</th>
              <th className={gridStyles.headerCellCenter}>Status</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <GridMessageRow colSpan={5}>Loading activity…</GridMessageRow>
            ) : error ? (
              <GridMessageRow colSpan={5} tone="error">
                Could not load activity: {apiErrorMessage(error, "request failed.")}
              </GridMessageRow>
            ) : grid.pageRows.length === 0 ? (
              <GridMessageRow colSpan={5}>
                {data?.length ? "No activity matches the search." : "No changes recorded yet."}
              </GridMessageRow>
            ) : (
              grid.pageRows.map((entry) => (
                <tr key={entry.id} className={gridStyles.row}>
                  <td className={`${gridStyles.cell} whitespace-nowrap`}>{formatDate(entry.timestamp)}</td>
                  <td className={gridStyles.cell}>{entry.user_email}</td>
                  <td className={`${gridStyles.strongCell} whitespace-nowrap`}>{activityLabel(entry)}</td>
                  <td className={gridStyles.cell}>{entry.summary}</td>
                  <td className={gridStyles.centerCell}>
                    <span
                      className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-semibold ${
                        entry.status === "success" ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
                      }`}
                    >
                      {entry.status}
                    </span>
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
        noun="changes"
      />
    </div>
  );
};

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

// ── Portal Settings ───────────────────────────────────────────────────

const settingButton =
  "inline-flex items-center gap-1.5 whitespace-nowrap rounded-lg border border-att-200 bg-white px-3 py-1.5 text-xs font-semibold text-att-700 hover:bg-att-50 disabled:opacity-50";
const settingSaveButton =
  "rounded-lg bg-att-400 px-2.5 py-1 text-xs font-semibold text-white hover:bg-att-500 disabled:opacity-50";
const settingCancelButton = "rounded-lg px-2 py-1 text-xs font-semibold text-gray-600 hover:bg-gray-100";
const settingInput =
  "w-24 rounded-lg border border-att-200 px-2 py-1 text-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100";

const PencilIcon = () => (
  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
    <path strokeLinecap="round" strokeLinejoin="round" d="M15.232 5.232l3.536 3.536m-2.036-5.036a2.5 2.5 0 113.536 3.536L6.5 21.036H3v-3.572L16.732 3.732z" />
  </svg>
);

/** One setting: name, one-line description and last change on the left, its control on the right. */
const SettingRow: React.FC<{
  title: string;
  description: React.ReactNode;
  entry?: AdminConfigEntry;
  control: React.ReactNode;
  children?: React.ReactNode;
}> = ({ title, description, entry, control, children }) => (
  <div className="py-3.5">
    <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between sm:gap-6">
      <div className="min-w-0">
        <p className="text-sm font-medium text-gray-900">{title}</p>
        <p className="mt-0.5 text-xs text-gray-500">{description}</p>
        <ConfigChangedBy entry={entry} />
      </div>
      <div className="flex shrink-0 items-center gap-2">{control}</div>
    </div>
    {children}
  </div>
);

/** On/off switch with its state spelled out, so it never relies on colour alone. */
const SettingSwitch: React.FC<{ label: string; checked: boolean; pending: boolean; onToggle: () => void }> = ({
  label,
  checked,
  pending,
  onToggle,
}) => (
  <>
    <span className={`w-16 text-right text-xs font-medium ${checked ? "text-att-700" : "text-gray-500"}`}>
      {pending ? "Saving…" : checked ? "On" : "Off"}
    </span>
    <Toggle checked={checked} onChange={onToggle} disabled={pending} label={label} />
  </>
);

const SettingsGroup: React.FC<{ title: string; children: React.ReactNode }> = ({ title, children }) => (
  <section className="px-5 pb-1 pt-4">
    <h3 className="text-[11px] font-semibold uppercase tracking-[0.14em] text-att-700">{title}</h3>
    <div className="divide-y divide-gray-100">{children}</div>
  </section>
);

const TimezoneSetting: React.FC<{ entry?: AdminConfigEntry }> = ({ entry }) => {
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

  return (
    <SettingRow
      title="Portal timezone"
      description="Every date and time in the portal is shown in this zone."
      entry={entry}
      control={
        <>
          {tzMutation.isPending ? (
            <span className="text-xs text-gray-500">Saving…</span>
          ) : tzMutation.isSuccess ? (
            <span className="text-xs text-green-700">Saved</span>
          ) : null}
          <select
            value={selected}
            onChange={handleChange}
            disabled={tzMutation.isPending}
            aria-label="Portal timezone"
            className="rounded-lg border border-att-200 bg-white px-2 py-1.5 text-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100 disabled:opacity-50"
          >
            {TIMEZONE_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>
                {opt.label}
              </option>
            ))}
          </select>
        </>
      }
    >
      <InlineError error={tzMutation.error} fallback="Failed to save the timezone." />
    </SettingRow>
  );
};

const RPM_MIN = 10;
const RPM_MAX = 10000;
const TTL_MAX_MINUTES = 10080;

const PortalSettings: React.FC<{
  rateLimitRpm: number;
  cacheTtl: number;
  corsOrigins: string[];
  cacheEnabled: boolean;
  ollamaEnabled: boolean;
}> = ({ rateLimitRpm, cacheTtl, corsOrigins, cacheEnabled, ollamaEnabled }) => {
  const [editingTtl, setEditingTtl] = useState(false);
  const [editingCors, setEditingCors] = useState(false);
  const [editingRpm, setEditingRpm] = useState(false);
  const [rpmValue, setRpmValue] = useState(String(rateLimitRpm));
  const [ttlMode, setTtlMode] = useState<"timed" | "unlimited">(cacheTtl <= 0 ? "unlimited" : "timed");
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

  const rpmParsed = Number(rpmValue);
  const rpmInvalid = !Number.isInteger(rpmParsed) || rpmParsed < RPM_MIN || rpmParsed > RPM_MAX;
  const ttlParsed = Number(ttlMinutes);
  const ttlInvalid =
    ttlMode === "timed" && (!Number.isInteger(ttlParsed) || ttlParsed < 1 || ttlParsed > TTL_MAX_MINUTES);

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

  const cancelRpm = () => {
    setEditingRpm(false);
    setRpmValue(String(rateLimitRpm));
    rpmMutation.reset();
  };

  const cancelTtl = () => {
    setEditingTtl(false);
    setTtlMode(cacheTtl <= 0 ? "unlimited" : "timed");
    setTtlMinutes(cacheTtl <= 0 ? "60" : String(Math.max(1, Math.round(cacheTtl / 60))));
    ttlMutation.reset();
  };

  return (
    <div className={gridStyles.shell}>
      <div className={gridStyles.panelHeader}>
        <div>
          <h2 className={gridStyles.sectionTitle}>Portal Settings</h2>
          <p className="mt-0.5 text-xs text-gray-500">Stored in the database and applied at runtime — no redeploy needed.</p>
        </div>
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 lg:divide-x lg:divide-att-100">
        <SettingsGroup title="Performance & caching">
          <SettingRow
            title="Rate limit"
            description="Requests per minute per client IP, shared across every API worker. Applies within 30 seconds."
            entry={configByKey.get("rate_limit_rpm")}
            control={
              editingRpm ? (
                <>
                  <input
                    type="number"
                    min={RPM_MIN}
                    max={RPM_MAX}
                    value={rpmValue}
                    onChange={(e) => setRpmValue(e.target.value)}
                    aria-label="Rate limit (requests per minute)"
                    className={settingInput}
                  />
                  <button onClick={handleSaveRpm} disabled={rpmMutation.isPending || rpmInvalid} className={settingSaveButton}>
                    {rpmMutation.isPending ? "…" : "Save"}
                  </button>
                  <button onClick={cancelRpm} className={settingCancelButton}>
                    Cancel
                  </button>
                </>
              ) : (
                <>
                  <span className="text-sm font-semibold text-gray-900">
                    {rateLimitRpm.toLocaleString()} <span className="font-normal text-gray-500">req/min</span>
                  </span>
                  <button
                    onClick={() => setEditingRpm(true)}
                    className="rounded p-1 text-gray-400 transition-colors hover:text-att-600"
                    title="Edit rate limit"
                    aria-label="Edit rate limit"
                  >
                    <PencilIcon />
                  </button>
                </>
              )
            }
          >
            {editingRpm && rpmInvalid && (
              <p className="mt-2 text-xs text-red-700">Enter a whole number between {RPM_MIN} and {RPM_MAX}.</p>
            )}
            <InlineError error={rpmMutation.error} fallback="Failed to save the rate limit." />
          </SettingRow>

          <SettingRow
            title="Page cache"
            description="Serve the Leadership dashboard, advisor and forecast from cache. Off reads straight from the database."
            entry={configByKey.get("cache_enabled")}
            control={
              <SettingSwitch
                label="Page cache"
                checked={cacheEnabled}
                pending={cacheMutation.isPending}
                onToggle={() =>
                  cacheMutation.mutate({ config_key: "cache_enabled", config_value: cacheEnabled ? "false" : "true" })
                }
              />
            }
          >
            <InlineError error={cacheMutation.error} fallback="Failed to update the page cache setting." />
          </SettingRow>

          <SettingRow
            title="Page cache TTL"
            description="How long Leadership and Amortized payloads stay cached. Unlimited keeps them until released."
            entry={configByKey.get("cache_ttl_seconds")}
            control={
              editingTtl ? (
                <>
                  <input
                    type="number"
                    min={1}
                    max={TTL_MAX_MINUTES}
                    value={ttlMinutes}
                    onChange={(e) => setTtlMinutes(e.target.value)}
                    disabled={ttlMode === "unlimited"}
                    aria-label="Page cache TTL (minutes)"
                    className={`${settingInput} w-20 disabled:bg-gray-50`}
                  />
                  <span className="text-xs text-gray-500">min</span>
                  <label className="inline-flex items-center gap-1.5 text-xs text-gray-600">
                    <input
                      type="checkbox"
                      checked={ttlMode === "unlimited"}
                      onChange={(e) => setTtlMode(e.target.checked ? "unlimited" : "timed")}
                      className="rounded border-gray-300 text-att-500 focus:ring-att-400"
                    />
                    Unlimited
                  </label>
                  <button onClick={handleSaveTtl} disabled={ttlMutation.isPending || ttlInvalid} className={settingSaveButton}>
                    {ttlMutation.isPending ? "…" : "Save"}
                  </button>
                  <button onClick={cancelTtl} className={settingCancelButton}>
                    Cancel
                  </button>
                </>
              ) : (
                <>
                  <span className="text-sm font-semibold text-gray-900">
                    {cacheTtl <= 0 ? "Unlimited" : `${Math.round(cacheTtl / 60)} min`}
                  </span>
                  <button
                    onClick={() => setEditingTtl(true)}
                    className="rounded p-1 text-gray-400 transition-colors hover:text-att-600"
                    title="Edit page cache TTL"
                    aria-label="Edit page cache TTL"
                  >
                    <PencilIcon />
                  </button>
                </>
              )
            }
          >
            {editingTtl && ttlInvalid && (
              <p className="mt-2 text-xs text-red-700">Enter whole minutes between 1 and {TTL_MAX_MINUTES} (7 days).</p>
            )}
            <InlineError error={ttlMutation.error} fallback="Failed to save the cache TTL." />
          </SettingRow>

          <SettingRow
            title="Cached data"
            description="Clear cached payloads now so the next request rebuilds from the database."
            control={
              <button onClick={() => releaseCache.mutate()} disabled={releaseCache.isPending} className={settingButton}>
                <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2} aria-hidden="true">
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 7h12M9 7V5a1 1 0 011-1h4a1 1 0 011 1v2m-7 0l1 12h6l1-12M10 11v6m4-6v6" />
                </svg>
                {releaseCache.isPending ? "Releasing…" : "Release cache"}
              </button>
            }
          >
            {releaseCache.isSuccess ? (
              <p className="mt-2 text-xs text-green-700">
                Released {releaseCache.data.released_keys} cached key(s). The next requests rebuild fresh payloads.
              </p>
            ) : null}
            <InlineError error={releaseCache.error} fallback="Failed to release cached data." />
          </SettingRow>
        </SettingsGroup>

        <SettingsGroup title="Features & display">
          <SettingRow
            title="Ollama LLM"
            description="AI forecasts and executive advice on the Leadership dashboard. Off uses local heuristic projections."
            entry={configByKey.get("ollama_enabled")}
            control={
              <SettingSwitch
                label="Ollama LLM"
                checked={ollamaEnabled}
                pending={ollamaMutation.isPending}
                onToggle={() =>
                  ollamaMutation.mutate({ config_key: "ollama_enabled", config_value: ollamaEnabled ? "false" : "true" })
                }
              />
            }
          >
            <InlineError error={ollamaMutation.error} fallback="Failed to update the Ollama setting." />
          </SettingRow>

          <TimezoneSetting entry={configByKey.get("portal_timezone")} />

          <SettingRow
            title="CORS origins"
            description={
              <>
                Only for browser apps calling the API from another origin — the portal itself uses its same-origin{" "}
                <code>/api</code> proxy.
              </>
            }
            entry={configByKey.get("cors_origins")}
            control={
              editingCors ? null : (
                <>
                  {corsMutation.isSuccess ? <span className="text-xs text-green-700">Saved</span> : null}
                  <button onClick={() => setEditingCors(true)} className={settingButton}>
                    <PencilIcon />
                    Edit
                  </button>
                </>
              )
            }
          >
            {editingCors ? (
              <div className="mt-3 space-y-2">
                <textarea
                  value={corsText}
                  onChange={(e) => setCorsText(e.target.value)}
                  rows={4}
                  aria-label="CORS origins"
                  placeholder={"One origin per line, for example:\nhttp://localhost:5173"}
                  className="w-full rounded-lg border border-att-200 px-3 py-2 font-mono text-xs text-gray-700 focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100"
                />
                <div className="flex items-center gap-2">
                  <button
                    onClick={handleSaveCors}
                    disabled={corsMutation.isPending || !corsText.trim()}
                    className={settingSaveButton}
                  >
                    {corsMutation.isPending ? "Saving…" : "Save CORS"}
                  </button>
                  <button
                    onClick={() => {
                      setEditingCors(false);
                      setCorsText(corsOrigins.join("\n"));
                      corsMutation.reset();
                    }}
                    className={settingCancelButton}
                  >
                    Cancel
                  </button>
                  <span className="text-[11px] text-gray-400">
                    Full <code>http://</code> or <code>https://</code> origins, one per line.
                  </span>
                </div>
                <InlineError error={corsMutation.error} fallback="Failed to update CORS origins." />
              </div>
            ) : (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {corsOrigins.map((origin) => (
                  <span key={origin} className="rounded bg-gray-100 px-2 py-0.5 font-mono text-xs text-gray-700">
                    {origin}
                  </span>
                ))}
              </div>
            )}
          </SettingRow>
        </SettingsGroup>
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

  const environmentOptions = data.environment_options ?? [];
  const inScopeCount = data.subscriptions.filter(isInScope).length;
  const outOfScopeCount = data.subscriptions.length - inScopeCount;
  const unhealthy = data.system_health.database !== "connected" || data.system_health.api !== "healthy";
  const envBadge =
    data.environment === "production"
      ? "bg-red-100 text-red-800"
      : data.environment === "staging"
        ? "bg-yellow-100 text-yellow-800"
        : "bg-green-100 text-green-800";

  const toggleScopeFilter = (filter: ScopeFilter) =>
    setScopeFilter((current) => (current === filter ? "all" : filter));

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-start sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
            <svg className="h-8 w-8 text-att-500" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" viewBox="0 0 24 24"><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68 1.65 1.65 0 0 0 10 3.17V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z" /></svg>
            Admin Dashboard
          </h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-2 text-sm text-gray-500">
            <span className={`inline-flex rounded-full px-2 py-0.5 text-[11px] font-bold ${envBadge}`}>
              {data.environment.toUpperCase()}
            </span>
            <span className="inline-flex rounded-full bg-gray-100 px-2 py-0.5 text-[11px] font-semibold text-gray-700">
              v{data.version}
            </span>
            <span>Last updated {formatDate(data.generated_at)}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to="/admin/permissions" className={secondaryButton}>Manage Permissions</Link>
          <Link to="/access/manage" className={secondaryButton}>Access Management</Link>
        </div>
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
          value={unhealthy ? "Degraded" : "Healthy"}
          subtitle={
            <span title="Database: SELECT 1 against PostgreSQL (data and page cache). Azure API: service principal token plus a subscription list call to management.azure.com, re-checked at most once a minute.">
              Database {data.system_health.database} · Azure API {data.system_health.api}
            </span>
          }
          icon={MetricCardIcons.activity()}
          tone={unhealthy ? "red" : "green"}
        />
      </div>

      <PortalSettings
        rateLimitRpm={data.rate_limit_rpm}
        cacheTtl={data.cache_ttl_seconds}
        corsOrigins={data.cors_origins}
        cacheEnabled={data.cache_enabled ?? true}
        ollamaEnabled={data.ollama_enabled ?? true}
      />

      {/* Add Subscription Form */}
      {showAddForm && (
        <AddSubscriptionForm onClose={() => setShowAddForm(false)} environmentOptions={environmentOptions} />
      )}

      {/* Subscription Table */}
      <SubscriptionTable
        subs={data.subscriptions}
        environmentOptions={environmentOptions}
        onShowAdd={() => setShowAddForm(true)}
        scopeFilter={scopeFilter}
        onScopeFilterChange={setScopeFilter}
      />

      {/* Certificate Collections Admin */}
      <CertificateCollectionsAdmin />

      {/* Audit trail of changes made on this page */}
      <AdminActivity />
    </div>
  );
};

export default AdminDashboard;
