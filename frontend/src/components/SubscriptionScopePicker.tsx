/**
 * SubscriptionScopePicker — narrows portal data to some of the subscriptions
 * the user was granted.
 *
 * The list is grouped Project → App, each subscription tagged Prod / Non-Prod.
 * Subscriptions not placed in a project yet (only Super Admins see those)
 * are listed flat at the end, exactly as before projects existed.
 */

import React from "react";
import { type AvailableSubscription, useSubscriptionScope } from "../contexts/SubscriptionContext";
import TierBadge from "./TierBadge";

interface AppGroup {
  key: string;
  label: string;
  code: string | null;
  subscriptions: AvailableSubscription[];
}

interface ProjectGroup {
  key: string;
  label: string;
  apps: AppGroup[];
}

/** Group placed subscriptions by project → app; return the unplaced ones separately. */
export function groupSubscriptions(subscriptions: AvailableSubscription[]): {
  projects: ProjectGroup[];
  ungrouped: AvailableSubscription[];
} {
  const projects = new Map<string, ProjectGroup>();
  const ungrouped: AvailableSubscription[] = [];
  for (const sub of subscriptions) {
    if (sub.project_id == null) {
      ungrouped.push(sub);
      continue;
    }
    const projectKey = String(sub.project_id);
    let project = projects.get(projectKey);
    if (!project) {
      project = { key: projectKey, label: sub.project_name || "Project", apps: [] };
      projects.set(projectKey, project);
    }
    const appKey = String(sub.app_id ?? "none");
    let app = project.apps.find((entry) => entry.key === appKey);
    if (!app) {
      app = { key: appKey, label: sub.app_name || "App", code: sub.app_code ?? null, subscriptions: [] };
      project.apps.push(app);
    }
    app.subscriptions.push(sub);
  }
  const byLabel = (a: { label: string }, b: { label: string }) => a.label.localeCompare(b.label);
  const tierRank = (sub: AvailableSubscription) => (sub.tier === "prod" ? 0 : sub.tier === "nonprod" ? 1 : 2);
  const sorted = Array.from(projects.values()).sort(byLabel);
  sorted.forEach((project) => {
    project.apps.sort(byLabel);
    project.apps.forEach((app) =>
      app.subscriptions.sort(
        (a, b) => tierRank(a) - tierRank(b) || (a.subscription_name || "").localeCompare(b.subscription_name || ""),
      ),
    );
  });
  return { projects: sorted, ungrouped };
}

const SubscriptionScopePicker: React.FC = () => {
  const {
    availableSubscriptions,
    selectedSubscriptionIds,
    isLoading,
    isAllSelected,
    scopeLabel,
    setSelectedSubscriptionIds,
    selectAllSubscriptions,
  } = useSubscriptionScope();
  const [open, setOpen] = React.useState(false);
  const [draft, setDraft] = React.useState<string[]>([]);
  const [saving, setSaving] = React.useState(false);

  React.useEffect(() => {
    if (open) {
      setDraft(isAllSelected ? [] : [...selectedSubscriptionIds]);
    }
  }, [open, isAllSelected, selectedSubscriptionIds]);

  const groups = React.useMemo(() => groupSubscriptions(availableSubscriptions), [availableSubscriptions]);

  if (isLoading || availableSubscriptions.length === 0) {
    return null;
  }

  const toggleDraft = (subscriptionId: string) => {
    setDraft((prev) => {
      const allIds = availableSubscriptions.map((sub) => sub.subscription_id);
      const working =
        isAllSelected && prev.length === 0 ? allIds : prev;

      const next = working.includes(subscriptionId)
        ? working.filter((id) => id !== subscriptionId)
        : [...working, subscriptionId];

      if (next.length === 0 || next.length === allIds.length) {
        return [];
      }
      return next;
    });
  };

  const renderSubscription = (sub: AvailableSubscription, grouped: boolean) => {
    const checked = draft.length === 0 ? isAllSelected : draft.includes(sub.subscription_id);
    return (
      <label
        key={sub.subscription_id}
        className={`flex cursor-pointer items-start gap-2 rounded-lg px-2 py-2 hover:bg-att-50/60 ${
          grouped ? "bg-white" : "border border-att-50"
        }`}
      >
        <input
          type="checkbox"
          className="mt-0.5"
          checked={checked}
          onChange={() => toggleDraft(sub.subscription_id)}
        />
        <span className="min-w-0 flex-1">
          <span className="block truncate text-sm font-medium text-slate-800">{sub.subscription_name}</span>
          <span className="block truncate text-[10px] text-slate-500">{sub.environment || "No environment tag"}</span>
        </span>
        {sub.tier && <TierBadge tier={sub.tier} className="mt-0.5 shrink-0" />}
      </label>
    );
  };

  const handleApply = async () => {
    setSaving(true);
    try {
      if (draft.length === 0 || draft.length === availableSubscriptions.length) {
        await selectAllSubscriptions();
      } else {
        await setSelectedSubscriptionIds(draft);
      }
      setOpen(false);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => setOpen((value) => !value)}
        className="inline-flex max-w-[220px] items-center gap-2 rounded-lg border border-att-200 bg-white px-3 py-1.5 text-xs font-medium text-slate-700 shadow-sm hover:bg-att-50"
        title="Filter portal data by subscription scope"
      >
        <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-att-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M3 4h18M8 12h8m-5 8h2" />
        </svg>
        <span className="truncate">{scopeLabel}</span>
      </button>

      {open && (
        <>
          <button
            type="button"
            className="fixed inset-0 z-40 cursor-default"
            aria-label="Close subscription picker"
            onClick={() => setOpen(false)}
          />
          <div className="absolute right-0 z-50 mt-2 w-96 rounded-xl border border-att-100 bg-white p-4 shadow-xl">
            <div className="mb-3">
              <h4 className="text-sm font-semibold text-slate-900">Subscription scope</h4>
              <p className="mt-1 text-xs text-slate-500">
                Your selection applies only to your session and does not change other users&apos; views.
              </p>
            </div>
            <div className="max-h-72 space-y-3 overflow-y-auto pr-1">
              {groups.projects.map((project) => (
                <div key={project.key}>
                  <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-att-700">
                    {project.label}
                  </p>
                  <div className="space-y-2">
                    {project.apps.map((app) => (
                      <div key={app.key} className="rounded-lg border border-att-50 bg-att-50/30 p-1.5">
                        <p className="px-1 pb-1 text-xs font-medium text-slate-600">
                          {app.label}
                          {app.code && <span className="ml-1 font-mono text-[10px] text-slate-400">{app.code}</span>}
                        </p>
                        <div className="space-y-1">
                          {app.subscriptions.map((sub) => renderSubscription(sub, true))}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              ))}
              {groups.ungrouped.length > 0 && (
                <div>
                  {groups.projects.length > 0 && (
                    <p className="mb-1 text-[11px] font-semibold uppercase tracking-[0.14em] text-slate-500">
                      Not in a project
                    </p>
                  )}
                  <div className="space-y-2">{groups.ungrouped.map((sub) => renderSubscription(sub, false))}</div>
                </div>
              )}
            </div>
            <div className="mt-4 flex items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => setDraft([])}
                className="text-xs font-medium text-att-600 hover:text-att-700"
              >
                Select all available
              </button>
              <button
                type="button"
                disabled={saving}
                onClick={handleApply}
                className="rounded-lg bg-att-500 px-3 py-1.5 text-xs font-semibold text-white hover:bg-att-600 disabled:opacity-50"
              >
                {saving ? "Applying…" : "Apply"}
              </button>
            </div>
          </div>
        </>
      )}
    </div>
  );
};

export default SubscriptionScopePicker;
