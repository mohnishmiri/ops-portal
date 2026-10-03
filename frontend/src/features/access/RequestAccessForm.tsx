/**
 * RequestAccessForm — ask for access to projects and/or apps.
 *
 * Every selected project / app × tier becomes one request line, which an
 * approver decides on separately. Selecting a whole project covers its apps,
 * so their checkboxes are locked while it is ticked.
 *
 * The user's Entra role caps the level: with a read-only role the Write
 * option is disabled (the backend would refuse it anyway).
 */

import React, { useMemo, useState } from "react";
import TierBadge, { TIER_LABELS } from "../../components/TierBadge";
import { formatAxiosError } from "../../services/apiErrors";
import {
  type AccessLevel,
  type AccessRequest,
  type CatalogProject,
  type Tier,
  MIN_JUSTIFICATION_LENGTH,
  TIERS,
  buildRequestItems,
  clampLevel,
  useSubmitAccessRequest,
} from "../../services/accessApi";
import { ErrorNote, LEVEL_LABELS, fieldLabel, inputClass, panelClass, primaryButton, textMatches } from "./accessShared";

export const WRITE_DISABLED_REASON =
  "Your Ops Portal role in Entra is read-only, so you can only request read access. " +
  "Write access needs membership of the Ops Portal Write group first.";

interface RequestAccessFormProps {
  catalog: CatalogProject[];
  catalogLoading?: boolean;
  catalogError?: string | null;
  /** From /access/me — the highest level the user's Entra role allows. */
  roleCeiling: AccessLevel;
  onSubmitted?: (request: AccessRequest) => void;
}

const RequestAccessForm: React.FC<RequestAccessFormProps> = ({
  catalog,
  catalogLoading,
  catalogError,
  roleCeiling,
  onSubmitted,
}) => {
  const submit = useSubmitAccessRequest();
  const [projectIds, setProjectIds] = useState<number[]>([]);
  const [appIds, setAppIds] = useState<number[]>([]);
  const [tiers, setTiers] = useState<Tier[]>([]);
  const [level, setLevel] = useState<AccessLevel>("read");
  const [justification, setJustification] = useState("");
  const [filter, setFilter] = useState("");

  const effectiveLevel = clampLevel(level, roleCeiling);
  const items = useMemo(
    () => buildRequestItems({ projectIds, appIds, tiers, level: effectiveLevel }, catalog),
    [projectIds, appIds, tiers, effectiveLevel, catalog],
  );

  const names = useMemo(() => {
    const projects = new Map<number, string>();
    const apps = new Map<number, string>();
    catalog.forEach((project) => {
      projects.set(project.id, project.name);
      project.apps.forEach((app) => apps.set(app.id, `${project.name} · ${app.name}`));
    });
    return { projects, apps };
  }, [catalog]);

  const visibleCatalog = useMemo(() => {
    const query = filter.trim().toLowerCase();
    if (!query) return catalog;
    return catalog
      .map((project) =>
        textMatches(query, project.name, project.description)
          ? project
          : { ...project, apps: project.apps.filter((app) => textMatches(query, app.name, app.app_code)) },
      )
      .filter((project) => textMatches(query, project.name, project.description) || project.apps.length > 0);
  }, [catalog, filter]);

  const trimmedJustification = justification.trim();
  const problems: string[] = [];
  if (projectIds.length === 0 && appIds.length === 0) problems.push("choose at least one project or app");
  if (tiers.length === 0) problems.push("choose Prod, Non-Prod, or both");
  if (trimmedJustification.length < MIN_JUSTIFICATION_LENGTH) {
    problems.push(`explain why you need access (at least ${MIN_JUSTIFICATION_LENGTH} characters)`);
  }
  const canSubmit = problems.length === 0 && items.length > 0 && !submit.isPending;

  const toggle = <T,>(list: T[], value: T): T[] =>
    list.includes(value) ? list.filter((entry) => entry !== value) : [...list, value];

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!canSubmit) return;
    try {
      const created = await submit.mutateAsync({ justification: trimmedJustification, items });
      setProjectIds([]);
      setAppIds([]);
      setTiers([]);
      setJustification("");
      onSubmitted?.(created);
    } catch {
      // Shown below from submit.error.
    }
  };

  return (
    <section className={panelClass} id="request-access" aria-labelledby="request-access-title">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h2 id="request-access-title" className="text-base font-semibold text-gray-800">
            Request access
          </h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Pick projects and/or apps, the tiers you need and a level. Each project or app × tier is reviewed
            separately by that project&apos;s admins.
          </p>
        </div>
        <input
          type="search"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter projects and apps…"
          aria-label="Filter projects and apps"
          className="w-64 rounded-lg border border-att-200 bg-white px-3 py-2 text-sm text-gray-700 shadow-sm focus:border-att-400 focus:outline-none focus:ring-2 focus:ring-att-100"
        />
      </div>

      <form onSubmit={handleSubmit} className="space-y-5">
        {/* Catalog */}
        <div>
          <span className={fieldLabel}>
            Projects and apps <span className="text-red-500">*</span>
          </span>
          {catalogLoading ? (
            <p className="text-sm text-gray-400 py-4">Loading projects…</p>
          ) : catalogError ? (
            <ErrorNote message={catalogError} />
          ) : catalog.length === 0 ? (
            <p className="text-sm text-gray-400 py-4">No projects are open for access requests yet.</p>
          ) : visibleCatalog.length === 0 ? (
            <p className="text-sm text-gray-400 py-4">No project or app matches “{filter}”.</p>
          ) : (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
              {visibleCatalog.map((project) => {
                const projectChecked = projectIds.includes(project.id);
                return (
                  <div
                    key={project.id}
                    className={`rounded-xl border p-3 transition ${
                      projectChecked ? "border-att-400 bg-att-50/60" : "border-att-100 bg-white"
                    }`}
                  >
                    <label className="flex cursor-pointer items-start gap-2">
                      <input
                        type="checkbox"
                        className="mt-1"
                        checked={projectChecked}
                        onChange={() => setProjectIds((current) => toggle(current, project.id))}
                        aria-label={`Whole project ${project.name}`}
                      />
                      <span className="min-w-0">
                        <span className="block text-sm font-semibold text-gray-800">{project.name}</span>
                        <span className="block text-xs text-gray-500">
                          Whole project — all {project.apps.length} app{project.apps.length === 1 ? "" : "s"}, including
                          apps added later
                        </span>
                        {project.description ? (
                          <span className="block text-xs text-gray-400 mt-0.5">{project.description}</span>
                        ) : null}
                      </span>
                    </label>
                    {project.apps.length > 0 && (
                      <div className="mt-2 ml-6 grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                        {project.apps.map((app) => (
                          <label
                            key={app.id}
                            className={`flex items-center gap-2 rounded-lg px-2 py-1.5 text-sm ${
                              projectChecked ? "opacity-50 cursor-not-allowed" : "cursor-pointer hover:bg-att-50/60"
                            }`}
                            title={projectChecked ? "Covered by the whole-project selection" : undefined}
                          >
                            <input
                              type="checkbox"
                              checked={projectChecked || appIds.includes(app.id)}
                              disabled={projectChecked}
                              onChange={() => setAppIds((current) => toggle(current, app.id))}
                              aria-label={`App ${app.name}`}
                            />
                            <span className="min-w-0 flex-1 truncate">
                              <span className="font-medium text-gray-800">{app.name}</span>{" "}
                              <span className="font-mono text-[11px] text-gray-400">{app.app_code}</span>
                            </span>
                            <span className="flex gap-1">
                              {app.tiers.map((tier) => (
                                <TierBadge key={tier} tier={tier} />
                              ))}
                            </span>
                          </label>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          )}
        </div>

        {/* Tier + level */}
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <fieldset>
            <legend className={fieldLabel}>
              Tiers <span className="text-red-500">*</span>
            </legend>
            <div className="flex items-center gap-4 py-2">
              {TIERS.map((tier) => (
                <label key={tier} className="inline-flex items-center gap-2 text-sm text-gray-700 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={tiers.includes(tier)}
                    onChange={() => setTiers((current) => toggle(current, tier))}
                  />
                  {TIER_LABELS[tier]}
                </label>
              ))}
            </div>
          </fieldset>
          <div>
            <label htmlFor="request-level" className={fieldLabel}>
              Level
            </label>
            <select
              id="request-level"
              value={effectiveLevel}
              onChange={(event) => setLevel(event.target.value as AccessLevel)}
              className={inputClass}
              title={roleCeiling === "read" ? WRITE_DISABLED_REASON : undefined}
            >
              <option value="read">{LEVEL_LABELS.read} — view data</option>
              <option
                value="write"
                disabled={roleCeiling === "read"}
                title={roleCeiling === "read" ? WRITE_DISABLED_REASON : undefined}
              >
                {LEVEL_LABELS.write} — make changes
              </option>
            </select>
            {roleCeiling === "read" && <p className="mt-1 text-xs text-gray-500">{WRITE_DISABLED_REASON}</p>}
          </div>
          <div className="rounded-lg border border-att-100 bg-att-50/50 px-3 py-2 text-xs text-gray-600 self-start">
            <span className="font-semibold text-att-700">
              {items.length} request line{items.length === 1 ? "" : "s"}
            </span>
            {items.length > 0 ? (
              <ul className="mt-1 space-y-0.5 max-h-24 overflow-y-auto">
                {items.map((item) => (
                  <li key={`${item.scope_type}-${item.project_id ?? item.app_id}-${item.tier}`}>
                    {item.scope_type === "project"
                      ? `${names.projects.get(item.project_id as number) ?? "Project"} (all apps)`
                      : names.apps.get(item.app_id as number) ?? "App"}{" "}
                    · {TIER_LABELS[item.tier]} · {LEVEL_LABELS[item.level]}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-gray-400">Choose a project or app and a tier.</p>
            )}
          </div>
        </div>

        {/* Justification */}
        <div>
          <label htmlFor="request-justification" className={fieldLabel}>
            Justification <span className="text-red-500">*</span>
          </label>
          <textarea
            id="request-justification"
            value={justification}
            onChange={(event) => setJustification(event.target.value)}
            rows={3}
            maxLength={2000}
            placeholder="What do you need this access for? e.g. on-call support for ATTCC production deployments"
            className={inputClass}
          />
          <p
            className={`mt-1 text-xs ${
              trimmedJustification.length >= MIN_JUSTIFICATION_LENGTH ? "text-gray-400" : "text-amber-700"
            }`}
          >
            {trimmedJustification.length}/{MIN_JUSTIFICATION_LENGTH} characters minimum
          </p>
        </div>

        {submit.isError && <ErrorNote message={formatAxiosError(submit.error, "Failed to submit the request")} />}

        <div className="flex flex-wrap items-center gap-3">
          <button type="submit" disabled={!canSubmit} className={primaryButton}>
            {submit.isPending ? "Submitting…" : "Submit request"}
          </button>
          {problems.length > 0 && (
            <span className="text-xs text-gray-500">To submit, {problems.join("; ")}.</span>
          )}
        </div>
      </form>
    </section>
  );
};

export default RequestAccessForm;
