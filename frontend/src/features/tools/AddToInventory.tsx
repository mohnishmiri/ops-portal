/**
 * "Add to inventory" on a successful check result.
 *
 * The check has just read the account's expiry, password change, last
 * sign-in and — for AD — the directory's name for it. This lists the account
 * under an application with those details, so the grid shows them without
 * anyone retyping dates. Every later check of the account keeps the row
 * current on its own.
 */

import React, { useState } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { usePermissions } from "../../contexts/PermissionsContext";
import { formatAxiosError } from "../../services/apiErrors";
import { type CredentialCheckResult, useCreateCredentialAccount, useCredentialAccounts } from "../../services/toolsApi";
import { parseApiDate } from "../../utils/dateFormat";

const PAGE = "credential_check_main";

/** UTC calendar date of a timestamp — the inventory keeps dates the way the backend writes them. */
const utcDate = (iso: string | null | undefined): string | null => {
  const date = parseApiDate(iso);
  return date ? date.toISOString().slice(0, 10) : null;
};

const AddToInventory: React.FC<{ result: CredentialCheckResult }> = ({ result }) => {
  const { canWrite } = useAuth();
  const { canEditPage } = usePermissions();
  const accounts = useCredentialAccounts();
  const create = useCreateCredentialAccount();
  const [open, setOpen] = useState(false);
  const [application, setApplication] = useState("");

  // Already listed (the check updated its row), not a working credential, or no right to add.
  if (!result.valid || result.inventory_updated || !result.directory || !result.account_name) return null;
  if (!canWrite || !canEditPage(PAGE)) return null;

  if (create.isSuccess) {
    return (
      <p className="mt-2 text-xs opacity-75">
        Added to the inventory under <strong>{create.data.application}</strong> with these details.
      </p>
    );
  }

  const details = result.account;
  const listId = `add-to-inventory-${result.kind}`;
  const applications = Array.from(new Set((accounts.data ?? []).map((a) => a.application))).sort((a, b) =>
    a.localeCompare(b),
  );

  const save = () =>
    create.mutate({
      application: application.trim(),
      app_code: null,
      account_type: result.kind,
      directory: result.directory!,
      account_name: result.account_name!,
      owner: null,
      expiry_date: details?.never_expires ? null : utcDate(details?.expires_at),
      never_expires: details?.never_expires ?? false,
      password_changed_date: utcDate(details?.last_changed_at),
      last_login_date: utcDate(details?.last_used_at),
      failed_logins: null,
      reset_url: null,
      notes: null,
      // AD's displayName names the account; a JFrog "name" is only a token description.
      display_name: result.kind === "domain" ? (details?.display_name ?? null) : null,
    });

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="mt-2 text-xs font-semibold underline underline-offset-2 hover:opacity-80"
      >
        Add to inventory
      </button>
    );
  }

  return (
    <div className="mt-3 border-t border-black/5 pt-3">
      <label className="block text-xs font-medium opacity-80" htmlFor={listId + "-input"}>
        Add to the inventory under application
      </label>
      <div className="mt-1 flex flex-wrap items-center gap-2">
        <input
          id={listId + "-input"}
          list={listId}
          value={application}
          onChange={(event) => setApplication(event.target.value)}
          onKeyDown={(event) => {
            // Inside the check card's form: Enter must add, not re-run the check.
            if (event.key === "Enter") {
              event.preventDefault();
              if (application.trim() && !create.isPending) save();
            }
          }}
          placeholder="ATTCC"
          className="min-w-0 flex-1 rounded-md border border-gray-300 bg-white px-2 py-1 text-sm text-gray-800 focus:outline-none focus:ring-2 focus:ring-att-400"
        />
        <datalist id={listId}>
          {applications.map((app) => (
            <option key={app} value={app} />
          ))}
        </datalist>
        <button
          type="button"
          onClick={save}
          disabled={!application.trim() || create.isPending}
          className="rounded-md bg-att-500 px-3 py-1 text-xs font-semibold text-white hover:bg-att-600 disabled:opacity-50"
        >
          {create.isPending ? "Adding…" : "Add"}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="text-xs font-semibold opacity-75 hover:opacity-100">
          Cancel
        </button>
      </div>
      {create.isError && (
        <p role="alert" className="mt-1 text-xs text-red-700">
          {formatAxiosError(create.error, "Could not add the account.")}
        </p>
      )}
    </div>
  );
};

export default AddToInventory;
