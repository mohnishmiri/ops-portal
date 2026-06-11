import React from "react";
import { useSubscriptionScope } from "../contexts/SubscriptionContext";

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
          <div className="absolute right-0 z-50 mt-2 w-80 rounded-xl border border-att-100 bg-white p-4 shadow-xl">
            <div className="mb-3">
              <h4 className="text-sm font-semibold text-slate-900">Subscription scope</h4>
              <p className="mt-1 text-xs text-slate-500">
                Your selection applies only to your session and does not change other users&apos; views.
              </p>
            </div>
            <div className="max-h-56 space-y-2 overflow-y-auto">
              {availableSubscriptions.map((sub) => {
                const checked =
                  draft.length === 0
                    ? isAllSelected
                    : draft.includes(sub.subscription_id);
                return (
                  <label
                    key={sub.subscription_id}
                    className="flex cursor-pointer items-start gap-2 rounded-lg border border-att-50 px-2 py-2 hover:bg-att-50/60"
                  >
                    <input
                      type="checkbox"
                      className="mt-0.5"
                      checked={checked}
                      onChange={() => toggleDraft(sub.subscription_id)}
                    />
                    <span className="min-w-0">
                      <span className="block truncate text-sm font-medium text-slate-800">
                        {sub.subscription_name}
                      </span>
                      <span className="block truncate text-[10px] text-slate-500">
                        {sub.environment || "No environment tag"}
                      </span>
                    </span>
                  </label>
                );
              })}
            </div>
            <div className="mt-4 flex items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => setDraft([])}
                className="text-xs font-medium text-att-600 hover:text-att-700"
              >
                Select all monitored
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
