/**
 * WorkspaceSelector — Grouped dropdown for Synapse workspace selection.
 *
 * Displays workspaces grouped by organisation:
 *   - ATTCC
 *   - CES
 *
 * Persists the last-selected workspace in localStorage so the user's
 * choice survives page refreshes.
 */

import React, { useEffect, useMemo } from "react";
import {
  useSynapseGroupedWorkspaces,
  type SynapseWorkspaceGroup,
} from "../../services/complianceApi";

// ── Constants ─────────────────────────────────────────────────────────

const STORAGE_KEY = "synapse-selected-workspace";

/** Badge colours per organisation */
const GROUP_COLORS: Record<string, string> = {
  ATTCC: "bg-att-100 text-att-800",
  CES: "bg-att-50 text-att-700",
};

// ── Props ─────────────────────────────────────────────────────────────

export interface WorkspaceSelectorProps {
  /** Currently selected workspace name (controlled). */
  value: string | null;
  /** Called when the user picks a workspace. */
  onChange: (workspaceName: string) => void;
  /** When true, shows a "-- Select Workspace --" placeholder and does not auto-select. */
  allowEmpty?: boolean;
  /** Optional extra CSS classes on the root wrapper. */
  className?: string;
}

// ── Component ─────────────────────────────────────────────────────────

export default function WorkspaceSelector({
  value,
  onChange,
  allowEmpty = false,
  className = "",
}: WorkspaceSelectorProps) {
  // ── Data ────────────────────────────────────────────────────────────
  const { data: groupedData, isLoading } = useSynapseGroupedWorkspaces();

  const groups: SynapseWorkspaceGroup[] = useMemo(
    () => groupedData?.groups ?? [],
    [groupedData],
  );

  // ── Auto-select from localStorage or first workspace ───────────────
  useEffect(() => {
    if (allowEmpty || value || groups.length === 0) return;

    const stored = localStorage.getItem(STORAGE_KEY);
    const allNames = groups.flatMap((g) => g.workspaces.map((w) => w.workspace_name));

    if (stored && allNames.includes(stored)) {
      onChange(stored);
    } else if (allNames.length > 0) {
      onChange(allNames[0]);
    }
  }, [value, groups, onChange]);

  // ── Persist selection ──────────────────────────────────────────────
  useEffect(() => {
    if (value) {
      localStorage.setItem(STORAGE_KEY, value);
    }
  }, [value]);

  // ── Find group label for the active workspace (for the badge) ─────
  const activeGroupLabel = useMemo(() => {
    if (!value) return null;
    for (const g of groups) {
      if (g.workspaces.some((w) => w.workspace_name === value)) return g.label;
    }
    return null;
  }, [value, groups]);

  // ── Render ─────────────────────────────────────────────────────────
  return (
    <div className={`flex items-center gap-3 ${className}`}>
      <label
        htmlFor="workspace-select"
        className="text-sm font-medium text-gray-700 whitespace-nowrap"
      >
        Workspace
      </label>

      <div className="relative flex items-center gap-2">
        <select
          id="workspace-select"
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value)}
          disabled={isLoading}
          className="block w-80 rounded-lg border border-att-200 bg-white px-3 py-2 text-sm shadow-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100 disabled:opacity-50"
        >
          {isLoading && <option value="">Loading workspaces…</option>}

          {!isLoading && allowEmpty && (
            <option value="">— All Workspaces —</option>
          )}

          {!isLoading && !allowEmpty && groups.length === 0 && (
            <option value="">No workspaces available</option>
          )}

          {groups.map((group) => (
            <optgroup key={group.label} label={group.label}>
              {group.workspaces.map((ws) => (
                <option key={ws.workspace_name} value={ws.workspace_name}>
                  {ws.workspace_name} ({ws.environment}, {ws.region})
                </option>
              ))}
            </optgroup>
          ))}
        </select>

        {/* Environment tier badge */}
        {activeGroupLabel && (
          <span
            className={`inline-flex items-center whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ${GROUP_COLORS[activeGroupLabel] ?? "bg-gray-100 text-gray-800"}`}
          >
            {activeGroupLabel}
          </span>
        )}
      </div>
    </div>
  );
}
