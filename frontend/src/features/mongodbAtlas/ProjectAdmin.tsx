/**
 * Project administration through the portal's Atlas API key: database
 * users, the IP access list, Atlas alerts and the activity feed, plus the
 * key's own connection status.
 *
 * A generated database-user password is shown once, in this component's
 * state, and dropped when the panel closes — it is not cached, stored or
 * logged anywhere.
 */

import React, { useCallback, useEffect, useMemo, useState } from "react";
import { gridStyles, SortableHeader, Spinner } from "../../components/gridStyles";
import { ConfirmDialog, GridHeader, GridMessageRow, GridPagerBar, Modal, textMatches, useGridRows } from "../access/accessShared";
import { formatAxiosError } from "../../services/apiErrors";
import {
  type AccessListEntry,
  type AtlasAlert,
  type AtlasCluster,
  type AtlasProject,
  type AtlasStatus,
  type ConnectionTestResult,
  type DatabaseUser,
  type DatabaseUserInput,
  useAccessList,
  useAcknowledgeAlert,
  useAddAccessListEntry,
  useAlerts,
  useConnectionTest,
  useCreateDatabaseUser,
  useDatabaseUsers,
  useDeleteAccessListEntry,
  useDeleteDatabaseUser,
  useEvents,
  useUpdateDatabaseUser,
} from "../../services/mongodbAtlasApi";
import {
  ATLAS_PAGE_SIZE,
  AtlasIcons,
  buttonTone,
  CopyButton,
  IconAction,
  InfoNote,
  inputClass,
  labelClass,
  useAtlasCan,
} from "./shared";

// ── Connection ───────────────────────────────────────────────────────────────

const STEP_STYLE = {
  ok: { icon: "✓", cls: "bg-green-100 text-green-700", label: "Passed" },
  failed: { icon: "✕", cls: "bg-red-100 text-red-700", label: "Failed" },
  skipped: { icon: "–", cls: "bg-slate-100 text-slate-500", label: "Skipped" },
} as const;

/** The connection test's steps, in order, with where it broke. */
export const ConnectionTestResults: React.FC<{ result: ConnectionTestResult }> = ({ result }) => (
  <div className="mt-3 space-y-2">
    <ol className="divide-y divide-att-100 rounded-lg border border-att-100 bg-white" aria-label="Connection test steps">
      {result.steps.map((step) => {
        const style = STEP_STYLE[step.status];
        return (
          <li key={step.name} className="flex items-start gap-3 px-3 py-2 text-sm">
            <span
              className={`mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-xs font-bold ${style.cls}`}
              aria-label={style.label}
              title={style.label}
            >
              {style.icon}
            </span>
            <span className="min-w-0 flex-1">
              <span className="font-medium text-slate-800">{step.label}</span>
              {step.ms != null && <span className="ml-2 text-xs text-slate-400">{step.ms} ms</span>}
              <span className={`block break-words text-xs ${step.status === "failed" ? "text-red-700" : "text-slate-500"}`}>{step.detail}</span>
            </span>
          </li>
        );
      })}
    </ol>
    {!result.ok && result.steps.some((s) => (s.name === "tcp" || s.name === "https") && s.status === "failed") && result.proxy_source === "none" && (
      <InfoNote tone="warning">
        The backend calls Atlas directly; your browser most likely reaches the internet through a proxy (PAC file) that
        Python does not read. Find the proxy for <span className="font-mono">cloud.mongodb.com</span> (Windows:{" "}
        <span className="font-mono">netsh winhttp show proxy</span>, or Chrome&apos;s{" "}
        <span className="font-mono">chrome://net-internals/#proxy</span>), set{" "}
        <span className="font-mono">MONGODB_ATLAS_PROXY=http://host:port</span> in the backend&apos;s environment, restart it and
        test again.
      </InfoNote>
    )}
  </div>
);

export const ConnectionPanel: React.FC<{ status: AtlasStatus | undefined; isLoading: boolean; formatDate: (v: string | null | undefined) => string }> = ({
  status,
  isLoading,
  formatDate,
}) => {
  const test = useConnectionTest();
  const unreachable = Boolean(status?.configured && !status.reachable);
  const autoRan = React.useRef(false);
  // When Atlas can't be reached, show where it breaks without making anyone ask.
  useEffect(() => {
    if (unreachable && !autoRan.current) {
      autoRan.current = true;
      test.mutate();
    }
  }, [unreachable, test]);

  if (isLoading || !status) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-500">
        <Spinner /> Checking the Atlas connection…
      </div>
    );
  }
  const ok = status.configured && status.reachable;
  return (
    <section className={`rounded-xl border p-4 ${ok ? "border-att-100 bg-white" : "border-amber-200 bg-amber-50/60"}`} aria-label="Atlas connection">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-sm font-semibold text-slate-800">Atlas API connection</h3>
        <div className="flex items-center gap-2">
          {status.configured && (
            <button type="button" className={buttonTone.neutral} onClick={() => test.mutate()} disabled={test.isPending}>
              {test.isPending ? <Spinner /> : <AtlasIcons.refresh />}
              {test.isPending ? "Testing…" : "Run connection test"}
            </button>
          )}
          <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${ok ? "bg-green-50 text-green-700 ring-1 ring-green-200" : "bg-amber-100 text-amber-800"}`}>
            {!status.configured ? "Not configured" : ok ? "Connected" : "Not reachable"}
          </span>
        </div>
      </div>
      {status.error && <p className="mt-2 break-words text-sm text-amber-900">{status.error}</p>}
      <dl className="mt-3 grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2 lg:grid-cols-5">
        <div>
          <dt className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">API key</dt>
          <dd className="font-mono text-slate-800">{status.public_key ?? "—"}</dd>
        </div>
        <div>
          <dt className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Route to Atlas</dt>
          <dd className="break-all text-slate-800" title={status.proxy_source === "environment" ? "From HTTPS_PROXY / system proxy settings" : undefined}>
            {status.proxy ? <span className="font-mono">{status.proxy}</span> : "Direct (no proxy)"}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Portal's outbound IP</dt>
          <dd className="font-mono text-slate-800" title="Atlas checks this address against the API key's access list">
            {status.portal_ip ?? "—"}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Projects in scope</dt>
          <dd className="text-slate-800">
            {status.project_count}
            {status.project_allowlist.length ? ` (allow-list of ${status.project_allowlist.length})` : ""}
            {status.org_filter ? ` · org ${status.org_filter}` : ""}
          </dd>
        </div>
        <div>
          <dt className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Checked</dt>
          <dd className="text-slate-800">{formatDate(status.checked_at)}</dd>
        </div>
      </dl>
      {status.api_key_roles.length > 0 && (
        <div className="mt-3">
          <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-500">Key roles in Atlas</p>
          <div className="mt-1 flex flex-wrap gap-1.5">
            {status.api_key_roles.map((r) => (
              <span key={`${r.id}-${r.role}`} className="rounded-md bg-att-50 px-2 py-0.5 font-mono text-xs text-att-800" title={`${r.scope} ${r.id}`}>
                {r.role}
              </span>
            ))}
          </div>
        </div>
      )}
      {!status.configured && (
        <p className="mt-3 text-xs text-slate-600">
          Set <span className="font-mono">MONGODB_ATLAS_PUBLIC_KEY</span> and <span className="font-mono">MONGODB_ATLAS_PRIVATE_KEY</span> (Key Vault
          secrets <span className="font-mono">opsportal-backend-mongodb-atlas-*</span>) and restart the backend.
        </p>
      )}
      {test.isError && <div className="mt-3"><InfoNote tone="error">{formatAxiosError(test.error, "The connection test could not run")}</InfoNote></div>}
      {test.data && <ConnectionTestResults result={test.data} />}
    </section>
  );
};

// ── Database users ───────────────────────────────────────────────────────────

const ROLE_PRESETS = [
  { value: "readAnyDatabase@admin", label: "Read any database" },
  { value: "readWriteAnyDatabase@admin", label: "Read and write any database" },
  { value: "atlasAdmin@admin", label: "Atlas admin" },
  { value: "read", label: "Read — one database" },
  { value: "readWrite", label: "Read and write — one database" },
  { value: "dbAdmin", label: "DB admin — one database" },
];

function roleFromPreset(preset: string, database: string): DatabaseUserInput["roles"][number] {
  if (preset.includes("@")) {
    const [role_name, database_name] = preset.split("@");
    return { role_name, database_name };
  }
  return { role_name: preset, database_name: database.trim() };
}

const PasswordReveal: React.FC<{ username: string; password: string }> = ({ username, password }) => (
  <div className="space-y-2 rounded-lg border border-green-200 bg-green-50 p-3">
    <p className="text-sm font-semibold text-green-800">Password for {username} — copy it now</p>
    <div className="flex items-center gap-2">
      <code className="flex-1 break-all rounded-md bg-white px-3 py-2 font-mono text-sm text-slate-800 ring-1 ring-green-200">{password}</code>
      <CopyButton value={password} />
    </div>
    <p className="text-xs text-green-800">It is shown only here and is not stored anywhere by the portal. Put it in the application's Key Vault.</p>
  </div>
);

const CreateUserDialog: React.FC<{ projectId: string; clusters: AtlasCluster[]; onClose: () => void }> = ({ projectId, clusters, onClose }) => {
  const create = useCreateDatabaseUser(projectId);
  const [username, setUsername] = useState("");
  const [preset, setPreset] = useState("readWrite");
  const [database, setDatabase] = useState("");
  const [scopes, setScopes] = useState<string[]>([]);
  const [setOwn, setSetOwn] = useState(false);
  const [password, setPassword] = useState("");
  const [description, setDescription] = useState("");
  const [deleteAfter, setDeleteAfter] = useState("");
  const [revealed, setRevealed] = useState<{ username: string; password: string } | null>(null);

  const needsDb = !preset.includes("@");
  const blocked = !username.trim() || (needsDb && !database.trim()) || (setOwn && password.length < 12) || create.isPending;

  const submit = () =>
    create.mutate(
      {
        username: username.trim(),
        password: setOwn ? password : null,
        roles: [roleFromPreset(preset, database)],
        scopes: scopes.map((name) => ({ name, type: "CLUSTER" as const })),
        description: description.trim() || null,
        delete_after_date: deleteAfter ? new Date(deleteAfter).toISOString() : null,
      },
      {
        onSuccess: (result) => {
          setPassword("");
          if (result.password) setRevealed({ username: result.user.username, password: result.password });
          else onClose();
        },
      },
    );

  return (
    <Modal
      title="New database user"
      subtitle="Password (SCRAM) authentication, created in the admin database"
      onClose={onClose}
      widthClass="max-w-2xl"
      footer={
        revealed ? (
          <button type="button" className={buttonTone.primary} onClick={onClose}>
            I have copied it
          </button>
        ) : (
          <>
            <button type="button" className={buttonTone.neutral} onClick={onClose} disabled={create.isPending}>
              Cancel
            </button>
            <button type="button" className={buttonTone.primary} onClick={submit} disabled={blocked}>
              {create.isPending ? "Creating…" : "Create user"}
            </button>
          </>
        )
      }
    >
      {revealed ? (
        <PasswordReveal {...revealed} />
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <label htmlFor="dbu-name" className={labelClass}>Username</label>
              <input id="dbu-name" value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="off" className={`${inputClass} font-mono`} />
            </div>
            <div>
              <label htmlFor="dbu-desc" className={labelClass}>Description <span className="font-normal text-slate-400">(optional)</span></label>
              <input id="dbu-desc" value={description} maxLength={100} onChange={(e) => setDescription(e.target.value)} placeholder="Application or owner" className={inputClass} />
            </div>
            <div>
              <label htmlFor="dbu-role" className={labelClass}>Role</label>
              <select id="dbu-role" value={preset} onChange={(e) => setPreset(e.target.value)} className={inputClass}>
                {ROLE_PRESETS.map((r) => (
                  <option key={r.value} value={r.value}>
                    {r.label}
                  </option>
                ))}
              </select>
            </div>
            {needsDb && (
              <div>
                <label htmlFor="dbu-db" className={labelClass}>Database</label>
                <input id="dbu-db" value={database} onChange={(e) => setDatabase(e.target.value)} className={`${inputClass} font-mono`} />
              </div>
            )}
          </div>
          <div>
            <p className={labelClass}>Limit to clusters <span className="font-normal text-slate-400">(none = every cluster in the project)</span></p>
            <div className="flex flex-wrap gap-2">
              {clusters.map((c) => (
                <label key={c.name} className="flex items-center gap-1.5 rounded-md border border-att-100 px-2 py-1 text-xs">
                  <input
                    type="checkbox"
                    checked={scopes.includes(c.name)}
                    onChange={() => setScopes((s) => (s.includes(c.name) ? s.filter((x) => x !== c.name) : [...s, c.name]))}
                  />
                  <span className="font-mono">{c.name}</span>
                </label>
              ))}
            </div>
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            <div>
              <label className="flex items-center gap-2 text-sm text-slate-700">
                <input type="checkbox" checked={setOwn} onChange={(e) => setSetOwn(e.target.checked)} />
                Set the password myself (otherwise one is generated)
              </label>
              {setOwn && (
                <input
                  type="password"
                  aria-label="Password"
                  autoComplete="new-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  placeholder="At least 12 characters"
                  className={`${inputClass} mt-2`}
                />
              )}
            </div>
            <div>
              <label htmlFor="dbu-temp" className={labelClass}>Temporary — Atlas deletes it at <span className="font-normal text-slate-400">(optional)</span></label>
              <input id="dbu-temp" type="datetime-local" value={deleteAfter} onChange={(e) => setDeleteAfter(e.target.value)} className={inputClass} />
            </div>
          </div>
          {create.isError && <InfoNote tone="error">{formatAxiosError(create.error, "Could not create the user")}</InfoNote>}
        </>
      )}
    </Modal>
  );
};

type UserSort = "username" | "auth" | "roles";

const DatabaseUsers: React.FC<{ project: AtlasProject; clusters: AtlasCluster[] }> = ({ project, clusters }) => {
  const can = useAtlasCan();
  const allowed = can("atlas_database_access");
  const { data, isLoading, error } = useDatabaseUsers(project.id);
  const update = useUpdateDatabaseUser(project.id);
  const remove = useDeleteDatabaseUser(project.id);
  const [creating, setCreating] = useState(false);
  const [deleting, setDeleting] = useState<DatabaseUser | null>(null);
  const [resetting, setResetting] = useState<DatabaseUser | null>(null);
  const [revealed, setRevealed] = useState<{ username: string; password: string } | null>(null);
  const rows = useMemo(() => data?.users ?? [], [data]);
  const grid = useGridRows<DatabaseUser, UserSort>(rows, {
    matches: useCallback(
      (u: DatabaseUser, q: string) => textMatches(q, u.username, u.auth_type, u.description, ...u.roles.map((r) => `${r.role_name}@${r.database_name}`), ...u.scopes.map((s) => s.name)),
      [],
    ),
    accessor: useCallback((u: DatabaseUser, key: UserSort) => (key === "auth" ? u.auth_type : key === "roles" ? u.roles.length : u.username.toLowerCase()), []),
    initialSort: { key: "username", direction: "asc" },
    pageSize: ATLAS_PAGE_SIZE,
  });
  const header = (label: string, key: UserSort) => (
    <th className={gridStyles.headerCell}>
      <SortableHeader label={label} active={grid.sort.key === key} direction={grid.sort.direction} onClick={() => grid.toggleSort(key)} />
    </th>
  );

  return (
    <div className="space-y-3">
      {revealed && (
        <div className="space-y-2">
          <PasswordReveal {...revealed} />
          <button type="button" className={buttonTone.neutral} onClick={() => setRevealed(null)}>
            Done — hide it
          </button>
        </div>
      )}
      <div className={gridStyles.shell}>
        <GridHeader title="Database users" subtitle={`${rows.length} in ${project.name}`} search={grid.search} onSearch={grid.setSearch} placeholder="Search user, role, cluster…">
          {allowed && (
            <button type="button" className={buttonTone.primary} onClick={() => setCreating(true)}>
              <AtlasIcons.plus />
              New user
            </button>
          )}
        </GridHeader>
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                {header("Username", "username")}
                {header("Authentication", "auth")}
                {header("Roles", "roles")}
                <th className={gridStyles.headerCell}>Clusters</th>
                <th className={gridStyles.headerCell}>Temporary until</th>
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <GridMessageRow colSpan={6}>Loading…</GridMessageRow>
              ) : error ? (
                <GridMessageRow colSpan={6} tone="error">{formatAxiosError(error, "Could not load database users")}</GridMessageRow>
              ) : grid.pageRows.length === 0 ? (
                <GridMessageRow colSpan={6}>{rows.length ? "No user matches." : "No database users."}</GridMessageRow>
              ) : (
                grid.pageRows.map((u) => (
                  <tr key={`${u.auth_database}/${u.username}`} className={gridStyles.row}>
                    <td className={gridStyles.strongCell}>
                      <span className="font-mono">{u.username}</span>
                      {u.description && <div className="text-[11px] font-normal text-slate-500">{u.description}</div>}
                    </td>
                    <td className={gridStyles.cell}>{u.auth_type}</td>
                    <td className={gridStyles.cell}>
                      <div className="flex flex-wrap gap-1">
                        {u.roles.map((r) => (
                          <span key={`${r.role_name}@${r.database_name}${r.collection_name ?? ""}`} className="rounded bg-att-50 px-1.5 py-0.5 font-mono text-[11px] text-att-800">
                            {r.role_name}@{r.database_name}
                            {r.collection_name ? `.${r.collection_name}` : ""}
                          </span>
                        ))}
                      </div>
                    </td>
                    <td className={gridStyles.cell}>{u.scopes.length ? u.scopes.map((s) => s.name).join(", ") : <span className="text-xs text-slate-400">All</span>}</td>
                    <td className={gridStyles.cell}>{u.delete_after ? new Date(u.delete_after).toLocaleString() : <span className="text-xs text-slate-400">—</span>}</td>
                    <td className={gridStyles.centerCell}>
                      <div className="flex items-center justify-center gap-1">
                        <IconAction
                          title={u.auth_type === "Password" ? "Reset password" : "Only password users have a password"}
                          tone="amber"
                          disabled={!allowed || u.auth_type !== "Password"}
                          onClick={() => setResetting(u)}
                        >
                          <AtlasIcons.key />
                        </IconAction>
                        <IconAction title="Delete user" tone="red" disabled={!allowed} onClick={() => setDeleting(u)}>
                          <AtlasIcons.trash />
                        </IconAction>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <GridPagerBar page={grid.page} totalPages={grid.totalPages} total={grid.total} pageSize={grid.pageSize} onPage={grid.setPage} noun="users" />
      </div>
      {creating && <CreateUserDialog projectId={project.id} clusters={clusters} onClose={() => setCreating(false)} />}
      {resetting && (
        <ConfirmDialog
          title="Reset password"
          message={
            <>
              Generate a new password for <b className="font-mono">{resetting.username}</b>? Applications using the old one fail to connect until they are given the new one.
            </>
          }
          confirmLabel="Reset password"
          busy={update.isPending}
          error={update.isError ? formatAxiosError(update.error, "Reset failed") : null}
          onCancel={() => setResetting(null)}
          onConfirm={() =>
            update.mutate(
              { username: resetting.username, auth_database: resetting.auth_database, reset_password: true },
              {
                onSuccess: (r) => {
                  if (r.password) setRevealed({ username: resetting.username, password: r.password });
                  setResetting(null);
                },
              },
            )
          }
        />
      )}
      {deleting && (
        <ConfirmDialog
          title="Delete database user"
          message={
            <>
              Delete <b className="font-mono">{deleting.username}</b> from {project.name}? Anything connecting as this user stops working.
            </>
          }
          confirmLabel="Delete"
          busy={remove.isPending}
          error={remove.isError ? formatAxiosError(remove.error, "Delete failed") : null}
          onCancel={() => setDeleting(null)}
          onConfirm={() => remove.mutate({ username: deleting.username, auth_database: deleting.auth_database }, { onSuccess: () => setDeleting(null) })}
        />
      )}
    </div>
  );
};

// ── IP access list ───────────────────────────────────────────────────────────

const AccessList: React.FC<{ project: AtlasProject }> = ({ project }) => {
  const can = useAtlasCan();
  const allowed = can("atlas_database_access");
  const { data, isLoading, error } = useAccessList(project.id);
  const add = useAddAccessListEntry(project.id);
  const remove = useDeleteAccessListEntry(project.id);
  const [entry, setEntry] = useState("");
  const [comment, setComment] = useState("");
  const [until, setUntil] = useState("");
  const [deleting, setDeleting] = useState<AccessListEntry | null>(null);
  const rows = useMemo(() => data?.entries ?? [], [data]);
  const grid = useGridRows<AccessListEntry, "entry" | "type">(rows, {
    matches: useCallback((e: AccessListEntry, q: string) => textMatches(q, e.entry, e.comment, e.type), []),
    accessor: useCallback((e: AccessListEntry, key: "entry" | "type") => (key === "type" ? e.type : e.entry), []),
    initialSort: { key: "entry", direction: "asc" },
    pageSize: ATLAS_PAGE_SIZE,
  });

  return (
    <div className="space-y-3">
      {allowed && (
        <div className="flex flex-wrap items-end gap-2 rounded-lg border border-att-100 bg-att-50/40 p-3">
          <div className="w-56">
            <label htmlFor="acl-entry" className={labelClass}>IP address or CIDR block</label>
            <input id="acl-entry" value={entry} onChange={(e) => setEntry(e.target.value)} placeholder="10.20.0.0/16" className={`${inputClass} font-mono`} />
          </div>
          <div className="min-w-[12rem] flex-1">
            <label htmlFor="acl-comment" className={labelClass}>Comment</label>
            <input id="acl-comment" value={comment} maxLength={80} onChange={(e) => setComment(e.target.value)} placeholder="AKS egress — prod" className={inputClass} />
          </div>
          <div className="w-56">
            <label htmlFor="acl-until" className={labelClass}>Temporary until <span className="font-normal text-slate-400">(optional)</span></label>
            <input id="acl-until" type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} className={inputClass} />
          </div>
          <button
            type="button"
            className={buttonTone.primary}
            disabled={!entry.trim() || add.isPending}
            onClick={() =>
              add.mutate(
                { entry: entry.trim(), comment: comment.trim() || null, delete_after_date: until ? new Date(until).toISOString() : null },
                { onSuccess: () => (setEntry(""), setComment(""), setUntil("")) },
              )
            }
          >
            <AtlasIcons.plus />
            {add.isPending ? "Adding…" : "Add"}
          </button>
        </div>
      )}
      {add.isError && <InfoNote tone="error">{formatAxiosError(add.error, "Could not add the entry")}</InfoNote>}
      <div className={gridStyles.shell}>
        <GridHeader title="IP access list" subtitle={`${rows.length} entries in ${project.name}`} search={grid.search} onSearch={grid.setSearch} placeholder="Search address or comment…" />
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                <th className={gridStyles.headerCell}>
                  <SortableHeader label="Entry" active={grid.sort.key === "entry"} direction={grid.sort.direction} onClick={() => grid.toggleSort("entry")} />
                </th>
                <th className={gridStyles.headerCell}>
                  <SortableHeader label="Type" active={grid.sort.key === "type"} direction={grid.sort.direction} onClick={() => grid.toggleSort("type")} />
                </th>
                <th className={gridStyles.headerCell}>Comment</th>
                <th className={gridStyles.headerCell}>Expires</th>
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <GridMessageRow colSpan={5}>Loading…</GridMessageRow>
              ) : error ? (
                <GridMessageRow colSpan={5} tone="error">{formatAxiosError(error, "Could not load the access list")}</GridMessageRow>
              ) : grid.pageRows.length === 0 ? (
                <GridMessageRow colSpan={5}>{rows.length ? "Nothing matches." : "The access list is empty — no client can connect."}</GridMessageRow>
              ) : (
                grid.pageRows.map((e) => (
                  <tr key={e.entry} className={gridStyles.row}>
                    <td className={`${gridStyles.cell} font-mono`}>{e.entry}</td>
                    <td className={gridStyles.cell}>{e.type}</td>
                    <td className={gridStyles.cell}>{e.comment ?? "—"}</td>
                    <td className={gridStyles.cell}>{e.delete_after ? new Date(e.delete_after).toLocaleString() : <span className="text-xs text-slate-400">Never</span>}</td>
                    <td className={gridStyles.centerCell}>
                      <IconAction title="Remove" tone="red" disabled={!allowed || e.type === "AWS security group"} onClick={() => setDeleting(e)}>
                        <AtlasIcons.trash />
                      </IconAction>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
        <GridPagerBar page={grid.page} totalPages={grid.totalPages} total={grid.total} pageSize={grid.pageSize} onPage={grid.setPage} noun="entries" />
      </div>
      {deleting && (
        <ConfirmDialog
          title="Remove access list entry"
          message={
            <>
              Remove <b className="font-mono">{deleting.entry}</b>? Clients connecting from it lose access to every cluster in {project.name}.
            </>
          }
          confirmLabel="Remove"
          busy={remove.isPending}
          error={remove.isError ? formatAxiosError(remove.error, "Remove failed") : null}
          onCancel={() => setDeleting(null)}
          onConfirm={() => remove.mutate(deleting.entry, { onSuccess: () => setDeleting(null) })}
        />
      )}
    </div>
  );
};

// ── Alerts ───────────────────────────────────────────────────────────────────

const ACK_OPTIONS = [
  { hours: 1, label: "1 hour" },
  { hours: 4, label: "4 hours" },
  { hours: 24, label: "24 hours" },
  { hours: 0, label: "Until it closes" },
];

const Alerts: React.FC<{ project: AtlasProject; formatDate: (v: string | null | undefined) => string }> = ({ project, formatDate }) => {
  const can = useAtlasCan();
  const allowed = can("atlas_cluster_admin");
  const [status, setStatus] = useState<"OPEN" | "TRACKING" | "CLOSED">("OPEN");
  const { data, isLoading, error } = useAlerts(project.id, status);
  const ack = useAcknowledgeAlert(project.id);
  const [acking, setAcking] = useState<AtlasAlert | null>(null);
  const [hours, setHours] = useState(4);
  const [comment, setComment] = useState("");
  const rows = useMemo(() => data?.alerts ?? [], [data]);
  const grid = useGridRows<AtlasAlert, "created" | "type">(rows, {
    matches: useCallback((a: AtlasAlert, q: string) => textMatches(q, a.event_type, a.cluster_name, a.metric_name, a.host, a.acknowledged_by), []),
    accessor: useCallback((a: AtlasAlert, key: "created" | "type") => (key === "type" ? a.event_type ?? "" : a.created_at ?? ""), []),
    initialSort: { key: "created", direction: "desc" },
    pageSize: ATLAS_PAGE_SIZE,
  });

  return (
    <div className={gridStyles.shell}>
      <GridHeader title="Atlas alerts" subtitle={`${rows.length} ${status.toLowerCase()} in ${project.name}`} search={grid.search} onSearch={grid.setSearch} placeholder="Search alert, cluster, metric…">
        <select value={status} onChange={(e) => setStatus(e.target.value as typeof status)} aria-label="Alert status" className="rounded-lg border border-att-200 bg-white px-2 py-2 text-sm">
          <option value="OPEN">Open</option>
          <option value="TRACKING">Tracking</option>
          <option value="CLOSED">Closed</option>
        </select>
      </GridHeader>
      <div className="overflow-x-auto">
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              <th className={gridStyles.headerCell}>
                <SortableHeader label="Raised" active={grid.sort.key === "created"} direction={grid.sort.direction} onClick={() => grid.toggleSort("created")} />
              </th>
              <th className={gridStyles.headerCell}>
                <SortableHeader label="Alert" active={grid.sort.key === "type"} direction={grid.sort.direction} onClick={() => grid.toggleSort("type")} />
              </th>
              <th className={gridStyles.headerCell}>Where</th>
              <th className={gridStyles.headerCell}>Value</th>
              <th className={gridStyles.headerCell}>Acknowledged</th>
              <th className={gridStyles.headerCellCenter}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <GridMessageRow colSpan={6}>Loading…</GridMessageRow>
            ) : error ? (
              <GridMessageRow colSpan={6} tone="error">{formatAxiosError(error, "Could not load alerts")}</GridMessageRow>
            ) : grid.pageRows.length === 0 ? (
              <GridMessageRow colSpan={6}>{rows.length ? "Nothing matches." : `No ${status.toLowerCase()} alerts.`}</GridMessageRow>
            ) : (
              grid.pageRows.map((a) => {
                const acked = Boolean(a.acknowledged_until && new Date(a.acknowledged_until).getTime() > Date.now());
                return (
                  <tr key={a.id} className={gridStyles.row}>
                    <td className={`${gridStyles.cell} whitespace-nowrap`}>{formatDate(a.created_at)}</td>
                    <td className={gridStyles.cell}>
                      <span className="font-mono text-xs">{a.event_type}</span>
                      {a.metric_name && <div className="text-[11px] text-slate-500">{a.metric_name}</div>}
                    </td>
                    <td className={gridStyles.cell}>
                      {a.cluster_name ?? "—"}
                      {a.host && <div className="font-mono text-[11px] text-slate-500">{a.host}</div>}
                    </td>
                    <td className={gridStyles.cell}>{a.current_value ?? "—"}</td>
                    <td className={gridStyles.cell}>
                      {acked ? (
                        <span className="text-xs text-slate-700" title={a.acknowledgement_comment ?? undefined}>
                          by {a.acknowledged_by ?? "—"} until {new Date(a.acknowledged_until!).getFullYear() > new Date().getFullYear() + 50 ? "closed" : formatDate(a.acknowledged_until)}
                        </span>
                      ) : (
                        <span className="text-xs text-slate-400">No</span>
                      )}
                    </td>
                    <td className={gridStyles.centerCell}>
                      {status !== "CLOSED" && (
                        <IconAction
                          title={acked ? "Un-acknowledge" : "Acknowledge"}
                          tone={acked ? "neutral" : "amber"}
                          disabled={!allowed || ack.isPending}
                          onClick={() => (acked ? ack.mutate({ alertId: a.id, unacknowledge: true, comment: "Un-acknowledged in OpsPortal" }) : setAcking(a))}
                        >
                          <AtlasIcons.clock />
                        </IconAction>
                      )}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      <GridPagerBar page={grid.page} totalPages={grid.totalPages} total={grid.total} pageSize={grid.pageSize} onPage={grid.setPage} noun="alerts" />
      {ack.isError && <div className="p-3"><InfoNote tone="error">{formatAxiosError(ack.error, "Acknowledge failed")}</InfoNote></div>}
      {acking && (
        <Modal
          title="Acknowledge alert"
          subtitle={`${acking.event_type ?? ""} · ${acking.cluster_name ?? ""}`}
          onClose={() => setAcking(null)}
          footer={
            <>
              <button type="button" className={buttonTone.neutral} onClick={() => setAcking(null)}>
                Cancel
              </button>
              <button
                type="button"
                className={buttonTone.primary}
                disabled={ack.isPending}
                onClick={() =>
                  ack.mutate(
                    {
                      alertId: acking.id,
                      acknowledged_until: hours ? new Date(Date.now() + hours * 3600_000).toISOString() : null,
                      comment: comment.trim() || undefined,
                    },
                    { onSuccess: () => (setAcking(null), setComment("")) },
                  )
                }
              >
                Acknowledge
              </button>
            </>
          }
        >
          <p className="text-sm text-slate-600">Atlas stops notifying about this alert for the chosen time.</p>
          <div className="flex flex-wrap gap-3">
            {ACK_OPTIONS.map((o) => (
              <label key={o.hours} className="flex items-center gap-1.5 text-sm">
                <input type="radio" name="ack-for" checked={hours === o.hours} onChange={() => setHours(o.hours)} />
                {o.label}
              </label>
            ))}
          </div>
          <div>
            <label htmlFor="ack-comment" className={labelClass}>Comment</label>
            <input id="ack-comment" value={comment} maxLength={200} onChange={(e) => setComment(e.target.value)} placeholder="Investigating — INC123456" className={inputClass} />
          </div>
        </Modal>
      )}
    </div>
  );
};

// ── Project activity feed ────────────────────────────────────────────────────

const ProjectEvents: React.FC<{ project: AtlasProject; formatDate: (v: string | null | undefined) => string }> = ({ project, formatDate }) => {
  const [page, setPage] = useState(1);
  const pageSize = 50;
  const { data, isLoading, error, isFetching } = useEvents(project.id, null, page, pageSize);
  const [search, setSearch] = useState("");
  const rows = useMemo(
    () => (data?.events ?? []).filter((e) => !search || textMatches(search.toLowerCase(), e.event_type, e.description, e.actor, e.cluster_name, e.host)),
    [data, search],
  );
  const total = data?.total ?? 0;
  return (
    <div className={gridStyles.shell}>
      <GridHeader title="Atlas activity feed" subtitle={`Everything Atlas recorded in ${project.name}, newest first`} search={search} onSearch={setSearch} placeholder="Search this page…">
        {isFetching && <Spinner />}
      </GridHeader>
      <div className="max-h-[32rem] overflow-auto">
        <table className={gridStyles.table}>
          <thead className={gridStyles.stickyHead}>
            <tr>
              <th className={gridStyles.headerCell}>When</th>
              <th className={gridStyles.headerCell}>Event</th>
              <th className={gridStyles.headerCell}>By</th>
              <th className={gridStyles.headerCell}>From</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <GridMessageRow colSpan={4}>Loading…</GridMessageRow>
            ) : error ? (
              <GridMessageRow colSpan={4} tone="error">{formatAxiosError(error, "Could not load events")}</GridMessageRow>
            ) : rows.length === 0 ? (
              <GridMessageRow colSpan={4}>No events.</GridMessageRow>
            ) : (
              rows.map((e) => (
                <tr key={e.id} className={gridStyles.row}>
                  <td className={`${gridStyles.cell} whitespace-nowrap`}>{formatDate(e.created_at)}</td>
                  <td className={gridStyles.cell}>
                    {e.description}
                    <span className="ml-2 font-mono text-[11px] text-slate-400">{e.event_type}</span>
                    {e.cluster_name && <div className="text-[11px] text-slate-500">{e.cluster_name}</div>}
                  </td>
                  <td className={gridStyles.cell}>{e.actor}</td>
                  <td className={gridStyles.monoCell}>{e.remote_address ?? "—"}</td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      <GridPagerBar page={page - 1} totalPages={Math.max(1, Math.ceil(total / pageSize))} total={total} pageSize={pageSize} onPage={(p) => setPage(p + 1)} noun="events" />
    </div>
  );
};

// ── Tab ──────────────────────────────────────────────────────────────────────

type Section = "users" | "network" | "alerts" | "events";

export const ProjectAdmin: React.FC<{
  projects: AtlasProject[];
  clusters: AtlasCluster[];
  status: AtlasStatus | undefined;
  statusLoading: boolean;
  formatDate: (v: string | null | undefined) => string;
}> = ({ projects, clusters, status, statusLoading, formatDate }) => {
  const [projectId, setProjectId] = useState<string>("");
  const [section, setSection] = useState<Section>("users");
  useEffect(() => {
    if (!projectId && projects.length) setProjectId(projects[0].id);
  }, [projectId, projects]);
  const project = projects.find((p) => p.id === projectId) ?? null;
  const projectClusters = clusters.filter((c) => c.project_id === projectId);
  const sections: { key: Section; label: string }[] = [
    { key: "users", label: "Database users" },
    { key: "network", label: "IP access list" },
    { key: "alerts", label: "Alerts" },
    { key: "events", label: "Activity feed" },
  ];

  return (
    <div className="space-y-4">
      <ConnectionPanel status={status} isLoading={statusLoading} formatDate={formatDate} />
      <div className="flex flex-wrap items-center gap-3">
        <label htmlFor="admin-project" className="text-sm font-semibold text-slate-700">
          Atlas project
        </label>
        <select id="admin-project" value={projectId} onChange={(e) => setProjectId(e.target.value)} className="min-w-[16rem] rounded-lg border border-att-200 bg-white px-3 py-2 text-sm">
          {projects.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Administration sections">
          {sections.map((s) => (
            <button
              key={s.key}
              type="button"
              role="tab"
              aria-selected={section === s.key}
              onClick={() => setSection(s.key)}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium ${section === s.key ? "bg-att-500 text-white" : "bg-white text-slate-600 ring-1 ring-att-100 hover:bg-att-50"}`}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>
      {!project ? (
        <InfoNote>No Atlas projects are visible to the portal's API key.</InfoNote>
      ) : section === "users" ? (
        <DatabaseUsers key={project.id} project={project} clusters={projectClusters} />
      ) : section === "network" ? (
        <AccessList key={project.id} project={project} />
      ) : section === "alerts" ? (
        <Alerts key={project.id} project={project} formatDate={formatDate} />
      ) : (
        <ProjectEvents key={project.id} project={project} formatDate={formatDate} />
      )}
    </div>
  );
};
