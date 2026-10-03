/**
 * Subscriptions — Super Admin only.
 *
 * Place every subscription in an app and a tier. Grants resolve through this
 * placement, so an unplaced subscription is visible to Super Admins only. The
 * backend suggests an app and tier from the name (ACC-PROD-31599-ATTCC);
 * "Apply suggestion" saves it in one click.
 */

import React, { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { SortableHeader, gridStyles } from "../../components/gridStyles";
import TierBadge, { TIER_LABELS } from "../../components/TierBadge";
import { formatAxiosError } from "../../services/apiErrors";
import {
  type AdminProject,
  type SubscriptionPlacement,
  type Tier,
  TIERS,
  usePlaceSubscription,
  useSubscriptionPlacements,
} from "../../services/accessApi";
import {
  AccessIcons,
  ActionIconButton,
  ErrorNote,
  GridHeader,
  GridMessageRow,
  GridPagerBar,
  compactSelectClass,
  textMatches,
  tierLabel,
  useGridRows,
} from "./accessShared";

type Draft = { app_id: number | null; tier: Tier };
type View = "all" | "unplaced" | "suggestion";
const VIEWS: View[] = ["all", "unplaced", "suggestion"];
type SortKey = "name" | "project" | "app" | "tier" | "suggestion";

const currentTier = (row: SubscriptionPlacement): Tier => row.tier ?? row.suggested_tier ?? "prod";

const suggestionDiffers = (row: SubscriptionPlacement) =>
  row.suggested_app_id != null && row.suggested_app_id !== row.app_id;

const SubscriptionPlacementTab: React.FC<{
  projects: AdminProject[];
  onNotify: (message: string) => void;
}> = ({ projects, onNotify }) => {
  const { data: rows = [], isLoading, isError, error } = useSubscriptionPlacements();
  const place = usePlaceSubscription();
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  // The view lives in `?view=` so the page's "Unplaced" tile can set it.
  const [params, setParams] = useSearchParams();
  const requestedView = params.get("view") as View | null;
  const view: View = requestedView && VIEWS.includes(requestedView) ? requestedView : "all";
  const setView = (next: View) =>
    setParams(
      (prev) => {
        const updated = new URLSearchParams(prev);
        if (next === "all") updated.delete("view");
        else updated.set("view", next);
        return updated;
      },
      { replace: true },
    );
  const [savingId, setSavingId] = useState<string | null>(null);
  const [rowError, setRowError] = useState<string | null>(null);

  const appIndex = useMemo(() => {
    const map = new Map<number, { name: string; code: string; projectName: string; projectActive: boolean }>();
    projects.forEach((project) =>
      project.apps.forEach((app) =>
        map.set(app.id, { name: app.name, code: app.app_code, projectName: project.name, projectActive: project.is_active }),
      ),
    );
    return map;
  }, [projects]);

  const unplacedCount = rows.filter((row) => row.app_id == null).length;
  const suggestionCount = rows.filter(suggestionDiffers).length;

  const visible = useMemo(() => {
    if (view === "unplaced") return rows.filter((row) => row.app_id == null);
    if (view === "suggestion") return rows.filter(suggestionDiffers);
    return rows;
  }, [rows, view]);

  const grid = useGridRows<SubscriptionPlacement, SortKey>(visible, {
    matches: (row, query) =>
      textMatches(
        query,
        row.subscription_name,
        row.subscription_id,
        row.environment,
        row.project_name,
        row.app_name,
        tierLabel(row.tier),
        row.suggested_app_name,
        row.suggested_app_code,
        row.app_id == null ? "unplaced" : "",
      ),
    accessor: (row, key) => {
      switch (key) {
        case "name":
          return row.subscription_name ?? row.subscription_id;
        case "project":
          return row.project_name ?? "";
        case "app":
          return row.app_name ?? "";
        case "tier":
          return row.tier ?? "";
        case "suggestion":
          return row.suggested_app_name ?? "";
      }
    },
    initialSort: { key: "name", direction: "asc" },
  });
  const header = (label: string, key: SortKey, center = false) => (
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

  const draftFor = (row: SubscriptionPlacement): Draft =>
    drafts[row.subscription_id] ?? { app_id: row.app_id, tier: currentTier(row) };

  const setDraft = (row: SubscriptionPlacement, patch: Partial<Draft>) =>
    setDrafts((current) => ({ ...current, [row.subscription_id]: { ...draftFor(row), ...patch } }));

  const isDirty = (row: SubscriptionPlacement) => {
    const draft = drafts[row.subscription_id];
    return Boolean(draft) && (draft.app_id !== row.app_id || draft.tier !== row.tier);
  };

  const save = async (row: SubscriptionPlacement, target: Draft) => {
    setRowError(null);
    setSavingId(row.subscription_id);
    try {
      await place.mutateAsync({ subscriptionId: row.subscription_id, app_id: target.app_id, tier: target.tier });
      setDrafts((current) => {
        const next = { ...current };
        delete next[row.subscription_id];
        return next;
      });
      const app = target.app_id != null ? appIndex.get(target.app_id) : undefined;
      onNotify(
        app
          ? `${row.subscription_name ?? row.subscription_id} placed in ${app.projectName} · ${app.name} (${TIER_LABELS[target.tier]}).`
          : `${row.subscription_name ?? row.subscription_id} is now unplaced (Super Admins only).`,
      );
    } catch (err) {
      setRowError(`${row.subscription_name ?? row.subscription_id}: ${formatAxiosError(err, "Failed to save placement")}`);
    } finally {
      setSavingId(null);
    }
  };

  return (
    <div className="space-y-3">
      <ErrorNote message={rowError} />
      <div className={gridStyles.shell}>
        <GridHeader
          title="Subscription placement"
          subtitle={
            <>
              {rows.length} subscriptions · <span className="font-semibold text-amber-700">{unplacedCount} unplaced</span> ·{" "}
              {suggestionCount} with a different suggested app. Access grants resolve through this placement.
            </>
          }
          search={grid.search}
          onSearch={grid.setSearch}
          placeholder="Search subscriptions…"
        >
          <label className="sr-only" htmlFor="placement-view">
            Show
          </label>
          <select
            id="placement-view"
            value={view}
            onChange={(event) => {
              setView(event.target.value as View);
              grid.setPage(0);
            }}
            className={compactSelectClass}
          >
            <option value="all">All subscriptions</option>
            <option value="unplaced">Unplaced only</option>
            <option value="suggestion">Suggestion differs</option>
          </select>
        </GridHeader>
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                {header("Subscription", "name")}
                {header("Project", "project")}
                {header("App", "app")}
                {header("Tier", "tier", true)}
                {header("Suggestion", "suggestion")}
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <GridMessageRow colSpan={6}>Loading subscriptions…</GridMessageRow>
              ) : isError ? (
                <GridMessageRow colSpan={6} tone="error">
                  {formatAxiosError(error, "Failed to load subscriptions")}
                </GridMessageRow>
              ) : grid.total === 0 ? (
                <GridMessageRow colSpan={6}>
                  {rows.length === 0 ? "No subscriptions are registered yet." : "No subscriptions match the current filters."}
                </GridMessageRow>
              ) : (
                grid.pageRows.map((row) => {
                  const draft = draftFor(row);
                  const unplaced = row.app_id == null;
                  const draftApp = draft.app_id != null ? appIndex.get(draft.app_id) : undefined;
                  const saving = savingId === row.subscription_id;
                  const canApply = suggestionDiffers(row);
                  return (
                    <tr key={row.subscription_id} className={`${gridStyles.row} ${unplaced ? "bg-amber-50/70" : ""}`}>
                      <td className={gridStyles.cell}>
                        <span className="block font-medium text-gray-800">{row.subscription_name ?? "—"}</span>
                        <span className="block font-mono text-[11px] text-gray-400">{row.subscription_id}</span>
                        <span className="mt-1 flex flex-wrap gap-1">
                          {unplaced && (
                            <span className="inline-flex items-center rounded bg-amber-100 px-1.5 py-0.5 text-[10px] font-semibold text-amber-800">
                              Visible to Super Admins only
                            </span>
                          )}
                          {row.environment && (
                            <span className="inline-flex items-center rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-600">
                              env: {row.environment}
                            </span>
                          )}
                          {!row.enabled && (
                            <span className="inline-flex items-center rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">
                              disabled
                            </span>
                          )}
                          {row.enabled && !row.monitored && (
                            <span className="inline-flex items-center rounded bg-gray-100 px-1.5 py-0.5 text-[10px] text-gray-500">
                              not monitored
                            </span>
                          )}
                        </span>
                      </td>
                      <td className={gridStyles.cell}>
                        {draftApp ? (
                          <>
                            {draftApp.projectName}
                            {!draftApp.projectActive && <span className="block text-[10px] text-gray-400">inactive project</span>}
                          </>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className={gridStyles.cell}>
                        <select
                          aria-label={`App for ${row.subscription_name ?? row.subscription_id}`}
                          value={draft.app_id ?? ""}
                          onChange={(event) =>
                            setDraft(row, { app_id: event.target.value ? Number(event.target.value) : null })
                          }
                          className={`${compactSelectClass} max-w-[16rem]`}
                          disabled={saving}
                        >
                          <option value="">— Unplaced —</option>
                          {projects
                            .filter((project) => project.apps.length > 0)
                            .map((project) => (
                              <optgroup key={project.id} label={project.name}>
                                {project.apps.map((app) => (
                                  <option key={app.id} value={app.id}>
                                    {app.name} ({app.app_code})
                                  </option>
                                ))}
                              </optgroup>
                            ))}
                        </select>
                      </td>
                      <td className={gridStyles.centerCell}>
                        <select
                          aria-label={`Tier for ${row.subscription_name ?? row.subscription_id}`}
                          value={draft.tier}
                          onChange={(event) => setDraft(row, { tier: event.target.value as Tier })}
                          className={compactSelectClass}
                          disabled={saving}
                        >
                          {TIERS.map((tier) => (
                            <option key={tier} value={tier}>
                              {TIER_LABELS[tier]}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td className={gridStyles.cell}>
                        {row.suggested_app_code || row.suggested_tier ? (
                          <span className="flex flex-wrap items-center gap-1.5 text-xs">
                            {row.suggested_app_code ? (
                              <span className="text-gray-700">
                                {row.suggested_app_name ?? "App"} <span className="font-mono text-gray-400">{row.suggested_app_code}</span>
                              </span>
                            ) : (
                              <span className="text-gray-400">no app in name</span>
                            )}
                            <TierBadge tier={row.suggested_tier} />
                            {row.suggested_app_code && row.suggested_app_id == null && (
                              <span className="block w-full text-[10px] text-amber-700">
                                App {row.suggested_app_code} does not exist yet — add it under Projects &amp; Apps.
                              </span>
                            )}
                          </span>
                        ) : (
                          <span className="text-xs text-gray-400">—</span>
                        )}
                      </td>
                      <td className={gridStyles.centerCell}>
                        <div className="flex justify-center gap-1">
                          <ActionIconButton
                            title="Save placement"
                            tone="blue"
                            disabled={!isDirty(row) || saving}
                            onClick={() => save(row, draft)}
                          >
                            {AccessIcons.save()}
                          </ActionIconButton>
                          {canApply && (
                            <ActionIconButton
                              title={`Apply suggestion: ${row.suggested_app_name ?? row.suggested_app_code} (${tierLabel(row.suggested_tier ?? currentTier(row))})`}
                              tone="green"
                              disabled={saving}
                              onClick={() =>
                                save(row, { app_id: row.suggested_app_id, tier: row.suggested_tier ?? currentTier(row) })
                              }
                            >
                              {AccessIcons.wand()}
                            </ActionIconButton>
                          )}
                        </div>
                      </td>
                    </tr>
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
          noun="subscriptions"
        />
      </div>
    </div>
  );
};

export default SubscriptionPlacementTab;
