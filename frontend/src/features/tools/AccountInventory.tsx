/**
 * Credential account inventory — the section under the Credential Check.
 *
 * The service accounts the team owns, by application: owner, expiry, last
 * login, failed logins and where to reset each one. Never a password or token.
 *
 * Expiry, password change and last login are typed in, imported, or written
 * by a successful check of the account above; failed logins only by hand or
 * import. The tiles filter the grid, and an export holds exactly the rows the
 * grid is showing (all pages).
 *
 * Viewing needs the page; changing needs WRITE (canEditPage). The API
 * enforces both — the buttons only follow.
 */

import React, { useMemo, useState } from "react";
import { MetricCard, MetricCardIcons } from "../../components/MetricCard";
import { SortableHeader, gridStyles } from "../../components/gridStyles";
import { useAuth } from "../../contexts/AuthContext";
import { usePermissions } from "../../contexts/PermissionsContext";
import {
  AccessIcons,
  ActionIconButton,
  ConfirmDialog,
  GridHeader,
  GridMessageRow,
  GridPagerBar,
  compactSelectClass,
  primaryButton,
  secondaryButton,
  textMatches,
  useGridRows,
} from "../access/accessShared";
import { DaysLeftBadge } from "../keyvault/kvShared";
import { formatAxiosError } from "../../services/apiErrors";
import {
  ACCOUNT_DIRECTORIES,
  type AccountDirectory,
  type AccountExportFilters,
  type CredentialAccount,
  DIRECTORY_SHORT,
  TYPE_LABELS,
  directoryLabel,
  downloadAccountsExport,
  useCredentialAccounts,
  useDeleteCredentialAccount,
} from "../../services/toolsApi";
import { formatDate, formatDateTime, parseApiDate } from "../../utils/dateFormat";
import { AccountFormModal, ImportAccountsModal } from "./AccountInventoryDialogs";
import { FAILING_STATUSES, StatusChip, statusStyle } from "./credentialStatus";

const PAGE = "credential_check_main";
const EXPIRING_DAYS = 30;

type View = "expired" | "expiring" | "failing";
type SortKey = "application" | "account" | "owner" | "expiry" | "last_login" | "failed";

const ALL_DIRECTORIES = Object.values(ACCOUNT_DIRECTORIES).flat();

// ── Dates ────────────────────────────────────────────────────────────────────

/** Whole calendar days from today to a YYYY-MM-DD date (negative once past), in the viewer's zone. */
export function calendarDaysUntil(value: string | null): number | null {
  const match = value ? /^(\d{4})-(\d{2})-(\d{2})/.exec(value) : null;
  if (!match) return null;
  const target = new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  const now = new Date();
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  return Math.round((target.getTime() - today.getTime()) / 86_400_000);
}

const daysAgoText = (value: string): string => {
  const days = -(calendarDaysUntil(value) ?? 0);
  if (days <= 0) return "today";
  return days === 1 ? "yesterday" : `${days} days ago`;
};

/** "just now" / "5 min ago" / "3 h ago" / "2 days ago" for a UTC timestamp. */
const sinceText = (iso: string | null): string => {
  const date = parseApiDate(iso);
  if (!date) return "";
  const minutes = Math.floor((Date.now() - date.getTime()) / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} min ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours} h ago`;
  const days = Math.floor(hours / 24);
  return `${days} day${days === 1 ? "" : "s"} ago`;
};

// ── Row classification (the tiles, and the export's `view`) ─────────────────

const expiryDays = (a: CredentialAccount) => (a.never_expires ? null : calendarDaysUntil(a.expiry_date));

export const isExpired = (a: CredentialAccount) => {
  const days = expiryDays(a);
  return days !== null && days < 0;
};

export const isExpiring = (a: CredentialAccount) => {
  const days = expiryDays(a);
  return days !== null && days >= 0 && days <= EXPIRING_DAYS;
};

export const isFailing = (a: CredentialAccount) =>
  (a.failed_logins ?? 0) > 0 || (a.last_check_status !== null && FAILING_STATUSES.has(a.last_check_status));

const VIEW_TESTS: Record<View, (a: CredentialAccount) => boolean> = {
  expired: isExpired,
  expiring: isExpiring,
  failing: isFailing,
};

// ── Grid helpers ─────────────────────────────────────────────────────────────

/** Same words the backend matches for an export's search. */
const searchLabel = (a: CredentialAccount) => `${TYPE_LABELS[a.account_type]} ${DIRECTORY_SHORT[a.directory]}`;

const accountMatches = (a: CredentialAccount, query: string) =>
  textMatches(query, a.application, a.app_code, a.account_name, a.owner, a.notes, searchLabel(a));

const accountAccessor = (a: CredentialAccount, key: SortKey): string | number => {
  switch (key) {
    case "account":
      return a.account_name.toLowerCase();
    case "owner":
      return (a.owner ?? "").toLowerCase();
    case "expiry":
      // Dated first (soonest on top), then unknown, then never.
      return a.never_expires ? 1e9 : (calendarDaysUntil(a.expiry_date) ?? 1e8);
    case "last_login":
      // Oldest sign-in first; never recorded counts as the stalest.
      return calendarDaysUntil(a.last_login_date) ?? -1e9;
    case "failed":
      return a.failed_logins ?? -1;
    default:
      return `${a.application} ${a.account_name}`.toLowerCase();
  }
};

const Muted: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <span className="text-xs text-gray-400">{children}</span>
);

const ExpiryCell: React.FC<{ account: CredentialAccount }> = ({ account }) => (
  <>
    {account.never_expires ? (
      <span className="text-sm text-gray-700">Never</span>
    ) : account.expiry_date ? (
      <span className="inline-flex flex-wrap items-center gap-2">
        <span>{formatDate(account.expiry_date)}</span>
        <DaysLeftBadge days={calendarDaysUntil(account.expiry_date)} />
      </span>
    ) : (
      <Muted>Not recorded</Muted>
    )}
    {account.password_changed_date && (
      <p className="mt-0.5 text-[11px] text-gray-500">Password changed {formatDate(account.password_changed_date)}</p>
    )}
  </>
);

const AdditionalInfo: React.FC<{ account: CredentialAccount }> = ({ account }) => {
  if (!account.reset_url && !account.notes) return <Muted>—</Muted>;
  return (
    <div className="max-w-xs space-y-1">
      {account.reset_url && (
        <a
          href={account.reset_url}
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center gap-1 text-sm font-medium text-att-600 hover:underline"
        >
          Reset password
          <svg viewBox="0 0 24 24" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
            <path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14 21 3" />
          </svg>
        </a>
      )}
      {account.notes && (
        <p className="line-clamp-2 text-xs text-gray-500" title={account.notes}>
          {account.notes}
        </p>
      )}
    </div>
  );
};

// ── Export menu ──────────────────────────────────────────────────────────────

const ExportMenu: React.FC<{ filters: AccountExportFilters; disabled: boolean; onError: (message: string) => void }> = ({
  filters,
  disabled,
  onError,
}) => {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const run = async (format: "xlsx" | "csv") => {
    setOpen(false);
    setBusy(true);
    try {
      await downloadAccountsExport(format, filters);
    } catch (error) {
      onError(formatAxiosError(error, "The export failed."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative">
      <button
        type="button"
        className={secondaryButton}
        aria-haspopup="menu"
        aria-expanded={open}
        disabled={disabled || busy}
        onClick={() => setOpen((value) => !value)}
      >
        {busy ? "Exporting…" : "Export"}
        <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} aria-hidden="true">
          <path d="m6 9 6 6 6-6" />
        </svg>
      </button>
      {open && (
        <>
          <button
            type="button"
            aria-hidden="true"
            tabIndex={-1}
            className="fixed inset-0 z-10 cursor-default"
            onClick={() => setOpen(false)}
          />
          <div role="menu" className="absolute right-0 z-20 mt-1 w-44 rounded-lg border border-att-100 bg-white py-1 shadow-lg">
            {(
              [
                ["xlsx", "Excel (.xlsx)"],
                ["csv", "CSV (.csv)"],
              ] as const
            ).map(([format, label]) => (
              <button
                key={format}
                type="button"
                role="menuitem"
                className="block w-full px-3 py-2 text-left text-sm text-gray-700 hover:bg-att-50"
                onClick={() => run(format)}
              >
                {label}
              </button>
            ))}
          </div>
        </>
      )}
    </div>
  );
};

// ── Section ──────────────────────────────────────────────────────────────────

const AccountInventory: React.FC<{
  /** May run credential checks — shows the per-row "Check" action. */
  canCheck: boolean;
  /** Fill in the check card for an account. */
  onCheck: (account: CredentialAccount) => void;
}> = ({ canCheck, onCheck }) => {
  const { canWrite } = useAuth();
  const { canEditPage } = usePermissions();
  const canEdit = canWrite && canEditPage(PAGE);

  const accountsQuery = useCredentialAccounts();
  const deleteMutation = useDeleteCredentialAccount();
  const accounts = useMemo(() => accountsQuery.data ?? [], [accountsQuery.data]);

  const [application, setApplication] = useState("");
  const [directory, setDirectory] = useState<AccountDirectory | "">("");
  const [view, setView] = useState<View | null>(null);
  const [editing, setEditing] = useState<CredentialAccount | "new" | null>(null);
  const [deleting, setDeleting] = useState<CredentialAccount | null>(null);
  const [importing, setImporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const applications = useMemo(
    () => Array.from(new Set(accounts.map((a) => a.application))).sort((a, b) => a.localeCompare(b)),
    [accounts],
  );

  // Application and directory narrow the tiles too, so the counts read per app.
  const scoped = useMemo(
    () => accounts.filter((a) => (!application || a.application === application) && (!directory || a.directory === directory)),
    [accounts, application, directory],
  );
  const viewed = useMemo(() => (view ? scoped.filter(VIEW_TESTS[view]) : scoped), [scoped, view]);

  const grid = useGridRows<CredentialAccount, SortKey>(viewed, {
    matches: accountMatches,
    accessor: accountAccessor,
    initialSort: { key: "application", direction: "asc" },
  });

  const counts = useMemo(
    () => ({
      expired: scoped.filter(isExpired).length,
      expiring: scoped.filter(isExpiring).length,
      failing: scoped.filter(isFailing).length,
    }),
    [scoped],
  );

  const toggleView = (next: View | null) => setView((current) => (current === next ? null : next));

  const exportFilters: AccountExportFilters = {
    application: application || undefined,
    directory: directory || undefined,
    view: view ?? undefined,
    q: grid.search.trim() || undefined,
  };

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

  const COLUMNS = 8;

  return (
    <section className="space-y-4" aria-labelledby="account-inventory-heading">
      <div>
        <h2 id="account-inventory-heading" className="text-xl font-semibold text-gray-900">
          Account inventory
        </h2>
        <p className="mt-0.5 text-sm text-gray-500">
          The ITSERVICES, AAF and JFrog accounts each application owns — who owns them, when they expire and where to
          reset them. A successful check above keeps an account&apos;s expiry and last sign-in current.
        </p>
      </div>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard
          title="Accounts"
          value={scoped.length}
          icon={AccessIcons.users("h-5 w-5")}
          tone="att"
          subtitle={application || (directory ? directoryLabel(directory) : `${applications.length} applications`)}
          onClick={() => toggleView(null)}
          active={view === null}
          actionLabel="Show every account"
        />
        <MetricCard
          title="Expired"
          value={counts.expired}
          icon={MetricCardIcons.alert("h-5 w-5")}
          tone="red"
          subtitle="Expiry date has passed"
          onClick={() => toggleView("expired")}
          active={view === "expired"}
          actionLabel="Show accounts whose expiry date has passed"
        />
        <MetricCard
          title={`Expiring in ${EXPIRING_DAYS} days`}
          value={counts.expiring}
          icon={MetricCardIcons.calendar("h-5 w-5")}
          tone="amber"
          subtitle="Reset before they lapse"
          onClick={() => toggleView("expiring")}
          active={view === "expiring"}
          actionLabel={`Show accounts expiring in the next ${EXPIRING_DAYS} days`}
        />
        <MetricCard
          title="Failing sign-in"
          value={counts.failing}
          icon={MetricCardIcons.shield("h-5 w-5")}
          tone="orange"
          subtitle="Failed logins, or last check rejected"
          onClick={() => toggleView("failing")}
          active={view === "failing"}
          actionLabel="Show accounts with failed logins, or whose last check was rejected, locked or expired"
        />
      </div>

      <div className={gridStyles.shell}>
        <GridHeader
          title="Accounts"
          subtitle={
            view
              ? `${viewed.length} of ${scoped.length} — ${view === "failing" ? "failing sign-in" : view}`
              : `${scoped.length} account${scoped.length === 1 ? "" : "s"}`
          }
          search={grid.search}
          onSearch={grid.setSearch}
          placeholder="Search account, owner, app…"
        >
          <select
            aria-label="Application"
            className={compactSelectClass}
            value={application}
            onChange={(e) => setApplication(e.target.value)}
          >
            <option value="">All applications</option>
            {applications.map((app) => (
              <option key={app} value={app}>
                {app}
              </option>
            ))}
          </select>
          <select
            aria-label="Directory"
            className={compactSelectClass}
            value={directory}
            onChange={(e) => setDirectory(e.target.value as AccountDirectory | "")}
          >
            <option value="">All directories</option>
            {ALL_DIRECTORIES.map((d) => (
              <option key={d} value={d}>
                {directoryLabel(d)}
              </option>
            ))}
          </select>
          {canEdit && (
            <button type="button" className={secondaryButton} onClick={() => setImporting(true)}>
              Import
            </button>
          )}
          <ExportMenu filters={exportFilters} disabled={grid.total === 0} onError={setExportError} />
          {canEdit && (
            <button type="button" className={primaryButton} onClick={() => setEditing("new")}>
              {AccessIcons.plus()}
              Add account
            </button>
          )}
        </GridHeader>

        {exportError && (
          <div role="alert" className="flex items-start justify-between gap-3 border-b border-red-100 bg-red-50 px-4 py-2 text-sm text-red-700">
            <span>{exportError}</span>
            <button type="button" className="text-xs font-semibold" onClick={() => setExportError(null)}>
              Dismiss
            </button>
          </div>
        )}

        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                {header("Application", "application")}
                {header("Account", "account")}
                {header("Owner", "owner")}
                {header("Expiry", "expiry")}
                {header("Last login", "last_login")}
                {header("Failed logins", "failed", true)}
                <th className={gridStyles.headerCell}>Additional information</th>
                <th className={gridStyles.headerCellCenter}>Actions</th>
              </tr>
            </thead>
            <tbody>
              {accountsQuery.isLoading ? (
                <GridMessageRow colSpan={COLUMNS}>Loading accounts…</GridMessageRow>
              ) : accountsQuery.isError ? (
                <GridMessageRow colSpan={COLUMNS} tone="error">
                  {formatAxiosError(accountsQuery.error, "Could not load the inventory.")}
                </GridMessageRow>
              ) : accounts.length === 0 ? (
                <GridMessageRow colSpan={COLUMNS}>
                  No accounts yet.{" "}
                  {canEdit ? (
                    <>
                      <strong>Add account</strong>, or <strong>Import</strong> the team&apos;s mechID list from Excel.
                    </>
                  ) : (
                    "Someone with write access can add them or import them from Excel."
                  )}
                </GridMessageRow>
              ) : grid.pageRows.length === 0 ? (
                <GridMessageRow colSpan={COLUMNS}>No accounts match the current search or filter.</GridMessageRow>
              ) : (
                grid.pageRows.map((a) => (
                  <tr key={a.id} className={`${gridStyles.row} align-top`}>
                    <td className={gridStyles.strongCell}>
                      {a.application}
                      {a.app_code && <p className="text-[11px] font-normal text-gray-500">App code {a.app_code}</p>}
                    </td>
                    <td className={gridStyles.cell}>
                      <div className="break-all font-mono text-xs text-gray-800">{a.account_name}</div>
                      <div className="mt-1 flex flex-wrap items-center gap-1.5">
                        <span className="rounded bg-att-50 px-1.5 py-0.5 text-[11px] font-medium text-att-700">
                          {directoryLabel(a.directory)}
                        </span>
                        {a.last_check_status && (
                          <span
                            className="inline-flex items-center gap-1"
                            title={`Last checked ${formatDateTime(a.last_checked_at)}${a.last_checked_by ? ` by ${a.last_checked_by}` : ""}: ${statusStyle(a.last_check_status).label}`}
                          >
                            <StatusChip status={a.last_check_status} />
                            <span className="text-[11px] text-gray-500">{sinceText(a.last_checked_at)}</span>
                          </span>
                        )}
                      </div>
                    </td>
                    <td className={gridStyles.cell}>{a.owner || <Muted>—</Muted>}</td>
                    <td className={gridStyles.cell}>
                      <ExpiryCell account={a} />
                    </td>
                    <td className={gridStyles.cell}>
                      {a.last_login_date ? (
                        <>
                          <span>{formatDate(a.last_login_date)}</span>
                          <p className="text-[11px] text-gray-500">{daysAgoText(a.last_login_date)}</p>
                        </>
                      ) : (
                        <Muted>Not recorded</Muted>
                      )}
                    </td>
                    <td className={gridStyles.centerCell}>
                      {a.failed_logins == null ? (
                        <Muted>—</Muted>
                      ) : (
                        <span className={a.failed_logins > 0 ? "font-semibold text-red-600" : "text-gray-600"}>
                          {a.failed_logins}
                        </span>
                      )}
                    </td>
                    <td className={gridStyles.cell}>
                      <AdditionalInfo account={a} />
                    </td>
                    <td className={gridStyles.centerCell}>
                      <div className="inline-flex items-center gap-1">
                        {canCheck && (
                          <ActionIconButton title={`Check ${a.account_name}`} tone="att" onClick={() => onCheck(a)}>
                            {AccessIcons.key("h-[18px] w-[18px]")}
                          </ActionIconButton>
                        )}
                        {canEdit && (
                          <>
                            <ActionIconButton title={`Edit ${a.account_name}`} tone="blue" onClick={() => setEditing(a)}>
                              {AccessIcons.pen("h-[18px] w-[18px]")}
                            </ActionIconButton>
                            <ActionIconButton
                              title={`Remove ${a.account_name}`}
                              tone="red"
                              onClick={() => {
                                deleteMutation.reset();
                                setDeleting(a);
                              }}
                            >
                              {AccessIcons.delete()}
                            </ActionIconButton>
                          </>
                        )}
                        {!canCheck && !canEdit && <Muted>—</Muted>}
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
          noun="accounts"
        />
      </div>

      {editing && (
        <AccountFormModal
          account={editing === "new" ? null : editing}
          applications={applications}
          onClose={() => setEditing(null)}
        />
      )}
      {importing && <ImportAccountsModal onClose={() => setImporting(false)} />}
      {deleting && (
        <ConfirmDialog
          title="Remove account?"
          message={
            <p>
              Remove <span className="font-mono">{deleting.account_name}</span> ({directoryLabel(deleting.directory)}) from{" "}
              <strong>{deleting.application}</strong>? This only removes it from the inventory — the account itself is
              not touched.
            </p>
          }
          confirmLabel="Remove"
          busy={deleteMutation.isPending}
          error={deleteMutation.isError ? formatAxiosError(deleteMutation.error, "Could not remove the account.") : null}
          onConfirm={() => deleteMutation.mutate(deleting.id, { onSuccess: () => setDeleting(null) })}
          onCancel={() => setDeleting(null)}
        />
      )}
    </section>
  );
};

export default AccountInventory;
