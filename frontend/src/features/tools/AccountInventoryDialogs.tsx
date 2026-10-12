/**
 * Dialogs for the credential account inventory: add / edit one account, and
 * import the team's mechID list from Excel or CSV.
 *
 * Neither ever asks for a password or token — the inventory describes
 * accounts, it does not hold their secrets.
 */

import React, { useState } from "react";
import { Modal, fieldLabel, inputClass, primaryButton, secondaryButton } from "../access/accessShared";
import { formatAxiosError } from "../../services/apiErrors";
import {
  ACCOUNT_DIRECTORIES,
  type AccountDirectory,
  type AccountType,
  type CredentialAccount,
  type CredentialAccountInput,
  type ImportPreviewRow,
  TYPE_LABELS,
  directoryLabel,
  downloadAccountsTemplate,
  useApplyAccountImport,
  useCreateCredentialAccount,
  usePreviewAccountImport,
  useUpdateCredentialAccount,
} from "../../services/toolsApi";

const ACCOUNT_PLACEHOLDERS: Record<AccountType, string> = {
  domain: "m52142",
  aaf: "m52142@com.att.attcc",
  jfrog: "m52142@att.com",
};

const NEVER_A_SECRET = "Never enter a password or token here — the inventory describes the account, not its secret.";

// ── Add / edit ───────────────────────────────────────────────────────────────

type FormState = Omit<CredentialAccountInput, "failed_logins"> & { failed_logins: string };

const toForm = (account: CredentialAccount | null): FormState => ({
  application: account?.application ?? "",
  app_code: account?.app_code ?? "",
  account_type: account?.account_type ?? "domain",
  directory: account?.directory ?? "ITSERVICES",
  account_name: account?.account_name ?? "",
  owner: account?.owner ?? "",
  expiry_date: account?.expiry_date ?? "",
  never_expires: account?.never_expires ?? false,
  password_changed_date: account?.password_changed_date ?? "",
  last_login_date: account?.last_login_date ?? "",
  failed_logins: account?.failed_logins == null ? "" : String(account.failed_logins),
  reset_url: account?.reset_url ?? "",
  notes: account?.notes ?? "",
});

const blankToNull = (value: string | null) => (value && value.trim() ? value.trim() : null);

const toInput = (form: FormState): CredentialAccountInput => ({
  application: form.application.trim(),
  app_code: blankToNull(form.app_code),
  account_type: form.account_type,
  directory: form.directory,
  account_name: form.account_name.trim(),
  owner: blankToNull(form.owner),
  expiry_date: form.never_expires ? null : blankToNull(form.expiry_date),
  never_expires: form.never_expires,
  password_changed_date: blankToNull(form.password_changed_date),
  last_login_date: blankToNull(form.last_login_date),
  failed_logins: form.failed_logins.trim() === "" ? null : Number(form.failed_logins),
  reset_url: blankToNull(form.reset_url),
  notes: blankToNull(form.notes),
});

export const AccountFormModal: React.FC<{
  /** null = add a new account. */
  account: CredentialAccount | null;
  /** Applications already listed, offered as suggestions so names stay consistent. */
  applications: string[];
  onClose: () => void;
}> = ({ account, applications, onClose }) => {
  const [form, setForm] = useState<FormState>(() => toForm(account));
  const create = useCreateCredentialAccount();
  const update = useUpdateCredentialAccount();
  const mutation = account ? update : create;
  const set = <K extends keyof FormState>(key: K, value: FormState[K]) => setForm((f) => ({ ...f, [key]: value }));

  const failedInvalid = form.failed_logins.trim() !== "" && !/^\d+$/.test(form.failed_logins.trim());
  const incomplete = !form.application.trim() || !form.account_name.trim() || failedInvalid;

  const save = () => {
    const input = toInput(form);
    if (account) update.mutate({ id: account.id, input }, { onSuccess: onClose });
    else create.mutate(input, { onSuccess: onClose });
  };

  return (
    <Modal
      title={account ? "Edit account" : "Add account"}
      subtitle={NEVER_A_SECRET}
      onClose={onClose}
      widthClass="max-w-2xl"
      footer={
        <>
          <button type="button" onClick={onClose} className={secondaryButton} disabled={mutation.isPending}>
            Cancel
          </button>
          <button type="button" onClick={save} className={primaryButton} disabled={incomplete || mutation.isPending}>
            {mutation.isPending ? "Saving…" : account ? "Save" : "Add account"}
          </button>
        </>
      }
    >
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div>
          <label className={fieldLabel} htmlFor="acct-application">Application *</label>
          <input
            id="acct-application"
            list="acct-application-options"
            className={inputClass}
            value={form.application}
            onChange={(e) => set("application", e.target.value)}
            placeholder="ATTCC"
          />
          <datalist id="acct-application-options">
            {applications.map((app) => (
              <option key={app} value={app} />
            ))}
          </datalist>
        </div>
        <div>
          <label className={fieldLabel} htmlFor="acct-app-code">App code</label>
          <input
            id="acct-app-code"
            className={inputClass}
            value={form.app_code ?? ""}
            onChange={(e) => set("app_code", e.target.value)}
            placeholder="31599"
          />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="acct-type">Type *</label>
          <select
            id="acct-type"
            className={inputClass}
            value={form.account_type}
            onChange={(e) => {
              const type = e.target.value as AccountType;
              setForm((f) => ({ ...f, account_type: type, directory: ACCOUNT_DIRECTORIES[type][0] }));
            }}
          >
            {(Object.keys(TYPE_LABELS) as AccountType[]).map((type) => (
              <option key={type} value={type}>
                {type === "domain" ? "Domain account" : TYPE_LABELS[type]}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={fieldLabel} htmlFor="acct-directory">Directory *</label>
          <select
            id="acct-directory"
            className={inputClass}
            value={form.directory}
            onChange={(e) => set("directory", e.target.value as AccountDirectory)}
          >
            {ACCOUNT_DIRECTORIES[form.account_type].map((directory) => (
              <option key={directory} value={directory}>
                {directoryLabel(directory)}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className={fieldLabel} htmlFor="acct-name">Account *</label>
          <input
            id="acct-name"
            className={`${inputClass} font-mono`}
            value={form.account_name}
            onChange={(e) => set("account_name", e.target.value)}
            placeholder={ACCOUNT_PLACEHOLDERS[form.account_type]}
            autoComplete="off"
          />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="acct-owner">Owner</label>
          <input
            id="acct-owner"
            className={inputClass}
            value={form.owner ?? ""}
            onChange={(e) => set("owner", e.target.value)}
            placeholder="Name or email"
          />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="acct-expiry">Expiry date</label>
          <input
            id="acct-expiry"
            type="date"
            className={inputClass}
            value={form.never_expires ? "" : form.expiry_date ?? ""}
            disabled={form.never_expires}
            onChange={(e) => set("expiry_date", e.target.value)}
          />
          <label className="mt-1.5 inline-flex items-center gap-2 text-xs text-gray-600">
            <input
              type="checkbox"
              checked={form.never_expires}
              onChange={(e) => set("never_expires", e.target.checked)}
            />
            Never expires
          </label>
        </div>
        <div>
          <label className={fieldLabel} htmlFor="acct-changed">Password last changed</label>
          <input
            id="acct-changed"
            type="date"
            className={inputClass}
            value={form.password_changed_date ?? ""}
            onChange={(e) => set("password_changed_date", e.target.value)}
          />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="acct-last-login">Last login</label>
          <input
            id="acct-last-login"
            type="date"
            className={inputClass}
            value={form.last_login_date ?? ""}
            onChange={(e) => set("last_login_date", e.target.value)}
          />
        </div>
        <div>
          <label className={fieldLabel} htmlFor="acct-failed">Failed logins</label>
          <input
            id="acct-failed"
            type="number"
            min={0}
            className={inputClass}
            value={form.failed_logins}
            onChange={(e) => set("failed_logins", e.target.value)}
          />
          {failedInvalid && <p className="mt-1 text-xs text-red-600">A whole number, 0 or more.</p>}
        </div>
        <div className="sm:col-span-2">
          <label className={fieldLabel} htmlFor="acct-reset">Reset link</label>
          <input
            id="acct-reset"
            type="url"
            className={inputClass}
            value={form.reset_url ?? ""}
            onChange={(e) => set("reset_url", e.target.value)}
            placeholder="https://… where this account's password is reset"
          />
        </div>
        <div className="sm:col-span-2">
          <label className={fieldLabel} htmlFor="acct-notes">Additional information</label>
          <textarea
            id="acct-notes"
            rows={3}
            className={inputClass}
            value={form.notes ?? ""}
            onChange={(e) => set("notes", e.target.value)}
            placeholder="Purpose, what uses it, how to rotate it…"
          />
        </div>
      </div>
      <p className="text-xs text-gray-500">
        Expiry, password change and last login are also updated whenever someone runs a successful check of this
        account above.
      </p>
      {mutation.isError && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {formatAxiosError(mutation.error, "Could not save the account.")}
        </div>
      )}
    </Modal>
  );
};

// ── Import ───────────────────────────────────────────────────────────────────

const PREVIEW_ROW_LIMIT = 300;

const ACTION_BADGES: Record<ImportPreviewRow["action"], { label: string; cls: string }> = {
  create: { label: "New", cls: "bg-green-100 text-green-700" },
  update: { label: "Update", cls: "bg-att-100 text-att-700" },
  invalid: { label: "Problem", cls: "bg-red-100 text-red-700" },
};

export const ImportAccountsModal: React.FC<{ onClose: () => void }> = ({ onClose }) => {
  const preview = usePreviewAccountImport();
  const apply = useApplyAccountImport();
  const [templateError, setTemplateError] = useState<string | null>(null);

  const rows = preview.data?.rows ?? [];
  const importable = rows.flatMap((row) => (row.account ? [row.account] : []));
  const done = apply.isSuccess;

  const chooseFile = (file: File | undefined) => {
    apply.reset();
    if (file) preview.mutate(file);
  };

  const downloadTemplate = async () => {
    setTemplateError(null);
    try {
      await downloadAccountsTemplate();
    } catch (error) {
      setTemplateError(formatAxiosError(error, "Could not download the template."));
    }
  };

  return (
    <Modal
      title="Import accounts"
      subtitle="Excel (.xlsx) or CSV — the team's mechID list, one account per row."
      onClose={onClose}
      widthClass="max-w-3xl"
      footer={
        done ? (
          <button type="button" onClick={onClose} className={primaryButton}>
            Done
          </button>
        ) : (
          <>
            <button type="button" onClick={onClose} className={secondaryButton} disabled={apply.isPending}>
              Cancel
            </button>
            <button
              type="button"
              className={primaryButton}
              disabled={importable.length === 0 || apply.isPending || preview.isPending}
              onClick={() => apply.mutate(importable)}
            >
              {apply.isPending ? "Importing…" : `Import ${importable.length} account${importable.length === 1 ? "" : "s"}`}
            </button>
          </>
        )
      }
    >
      <div className="space-y-2 text-sm text-gray-600">
        <p>
          Columns are matched by name: <strong>Application</strong>, <strong>Type</strong> (ITSERVICES,
          TESTITSERVICES, AAF or JFrog) and <strong>Account</strong> are required; Directory, Owner, Expiry Date,
          Password Last Changed, Last Login, Failed Logins, Reset Link and Notes are optional. An export from this grid
          imports back as it is.
        </p>
        <p>Re-importing updates accounts already listed. A blank cell keeps what is recorded — it never erases.</p>
      </div>
      <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-900">
        {NEVER_A_SECRET}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label className={`${secondaryButton} cursor-pointer`}>
          Choose file…
          <input
            type="file"
            accept=".xlsx,.csv"
            className="sr-only"
            aria-label="Choose an Excel or CSV file"
            onChange={(event) => {
              chooseFile(event.target.files?.[0]);
              event.target.value = "";
            }}
          />
        </label>
        <button type="button" onClick={downloadTemplate} className="text-sm font-medium text-att-600 hover:underline">
          Download the Excel template
        </button>
        {preview.isPending && <span className="text-sm text-gray-500">Reading the file…</span>}
      </div>
      {templateError && <p className="text-sm text-red-600">{templateError}</p>}

      {preview.isError && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {formatAxiosError(preview.error, "The file could not be read.")}
        </div>
      )}

      {preview.data && (
        <div className="space-y-3">
          <div className="flex flex-wrap gap-2 text-xs font-semibold">
            <span className="rounded-full bg-green-100 px-2.5 py-1 text-green-700">{preview.data.create_count} new</span>
            <span className="rounded-full bg-att-100 px-2.5 py-1 text-att-700">{preview.data.update_count} to update</span>
            {preview.data.invalid_count > 0 && (
              <span className="rounded-full bg-red-100 px-2.5 py-1 text-red-700">
                {preview.data.invalid_count} with problems — not imported
              </span>
            )}
          </div>
          {rows.length === 0 ? (
            <p className="text-sm text-gray-500">The file has a header row but no accounts under it.</p>
          ) : (
            <div className="max-h-72 overflow-y-auto rounded-lg border border-att-100">
              <table className="w-full text-sm">
                <thead className="sticky top-0 bg-att-50 text-left text-xs uppercase tracking-wide text-att-700">
                  <tr>
                    <th className="px-3 py-2">Row</th>
                    <th className="px-3 py-2">Account</th>
                    <th className="px-3 py-2">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, PREVIEW_ROW_LIMIT).map((row) => (
                    <tr key={row.row} className="border-t border-att-100 align-top">
                      <td className="px-3 py-1.5 text-xs text-gray-500">{row.row}</td>
                      <td className="px-3 py-1.5">
                        <span className="font-mono text-xs text-gray-800">{row.label}</span>
                        {row.account && <span className="ml-2 text-xs text-gray-500">{row.account.application}</span>}
                      </td>
                      <td className="px-3 py-1.5">
                        <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${ACTION_BADGES[row.action].cls}`}>
                          {ACTION_BADGES[row.action].label}
                        </span>
                        {row.errors.map((error) => (
                          <p key={error} className="mt-1 text-xs text-red-600">
                            {error}
                          </p>
                        ))}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {rows.length > PREVIEW_ROW_LIMIT && (
                <p className="border-t border-att-100 px-3 py-2 text-xs text-gray-500">
                  …and {rows.length - PREVIEW_ROW_LIMIT} more rows.
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {apply.isError && (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
          {formatAxiosError(apply.error, "The import failed; nothing was saved.")}
        </div>
      )}
      {done && (
        <div role="status" className="rounded-lg border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-800">
          Imported: {apply.data.created} new, {apply.data.updated} updated.
        </div>
      )}
    </Modal>
  );
};
