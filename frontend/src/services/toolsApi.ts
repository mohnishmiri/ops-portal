/**
 * Tools — credential checks and the credential account inventory.
 *
 * Secrets are sent once, over the portal's own API, and are never stored in
 * React Query state: the mutations below take the credential as an argument
 * and keep only the result. Do not add a query that caches a request body.
 *
 * There is no history of checks. The one thing a check leaves behind: when
 * the account is in the inventory, its row records the verdict and the
 * reported expiry / last sign-in (never the credential).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import apiClient from "./apiClient";

const BASE = "/tools/credential-checks";

export type CheckKind = "domain" | "jfrog" | "aaf";
export type DomainName = "ITSERVICES" | "TESTITSERVICES";
export type AafEnvironment = "prod" | "nonprod";
export type JFrogInstance = "bronze" | "gold";

/**
 * What the source reports about the credential beyond yes / no. Every field
 * is optional — AD, Artifactory and AAF each expose a different subset — and
 * null means "not reported", never "none". Datetimes are UTC ISO strings.
 */
export interface CredentialAccountDetails {
  /** AD display name, or the JFrog token description. */
  display_name: string | null;
  expires_at: string | null;
  /** The source says explicitly that it does not expire. */
  never_expires: boolean;
  /** Password last set, or token issued. */
  last_changed_at: string | null;
  last_used_at: string | null;
  /** How far to trust last_used_at, or why it is not shown. */
  last_used_note: string | null;
  /** AD account (not password) expiry; null when the account does not expire. */
  account_expires_at: string | null;
  notes: string[];
}

export interface CredentialCheckResult {
  kind: CheckKind;
  target: string;
  valid: boolean;
  /** valid | invalid | expired | locked | disabled | must_change | denied | error */
  status: string;
  message: string;
  checked_at: string;
  details: Record<string, unknown>;
  /** Expiry / last-used details, when the source would report them. */
  account: CredentialAccountDetails | null;
  /** The account is in the inventory and its row now holds this verdict. */
  inventory_updated: boolean;
  /** What was checked — lets the result add the account to the inventory. */
  directory: AccountDirectory | null;
  account_name: string | null;
}

export interface DomainCheckInput {
  domain: DomainName;
  username: string;
  password: string;
}

export interface JFrogCheckInput {
  instance: JFrogInstance;
  username: string;
  token: string;
}

export interface AafCheckInput {
  environment: AafEnvironment;
  account: string;
  password: string;
}

/**
 * Shared by the three checks. Nothing is cached: the result is the answer.
 * A check of a listed account updates its inventory row, so the grid refetches.
 */
function useCheckMutation<TInput>(path: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (input: TInput) => {
      const { data } = await apiClient.post<CredentialCheckResult>(`${BASE}/${path}`, input);
      return data;
    },
    onSuccess: (result) => {
      if (result.inventory_updated) qc.invalidateQueries({ queryKey: ACCOUNTS_KEY });
    },
  });
}

export const useCheckDomainPassword = () => useCheckMutation<DomainCheckInput>("domain");
export const useCheckJFrogToken = () => useCheckMutation<JFrogCheckInput>("jfrog");
export const useCheckAafPassword = () => useCheckMutation<AafCheckInput>("aaf");

// ── Credential account inventory ─────────────────────────────────────────────

const ACCOUNTS = "/tools/accounts";
const ACCOUNTS_KEY = ["tools", "credential-accounts"] as const;

export type AccountType = "domain" | "aaf" | "jfrog";
/** ITSERVICES / TESTITSERVICES, prod / nonprod (IST), bronze / gold. */
export type AccountDirectory = DomainName | AafEnvironment | JFrogInstance;

/** Where each type of account can live; the first is the default. */
export const ACCOUNT_DIRECTORIES: Record<AccountType, AccountDirectory[]> = {
  domain: ["ITSERVICES", "TESTITSERVICES"],
  aaf: ["prod", "nonprod"],
  jfrog: ["bronze", "gold"],
};

export const TYPE_LABELS: Record<AccountType, string> = { domain: "Domain", aaf: "AAF", jfrog: "JFrog" };

/** Directory on its own — the same words the import and export use. */
export const DIRECTORY_SHORT: Record<AccountDirectory, string> = {
  ITSERVICES: "ITSERVICES",
  TESTITSERVICES: "TESTITSERVICES",
  prod: "Prod",
  nonprod: "IST",
  bronze: "Bronze",
  gold: "Gold",
};

/** "ITSERVICES", "AAF IST", "JFrog Gold" — a domain's name already says what it is. */
export const directoryLabel = (directory: AccountDirectory): string =>
  directory === "ITSERVICES" || directory === "TESTITSERVICES"
    ? directory
    : `${TYPE_LABELS[ACCOUNT_DIRECTORIES.aaf.includes(directory) ? "aaf" : "jfrog"]} ${DIRECTORY_SHORT[directory]}`;

/** Editable fields. Dates are YYYY-MM-DD calendar dates. No password or token, ever. */
export interface CredentialAccountInput {
  application: string;
  app_code: string | null;
  account_type: AccountType;
  directory: AccountDirectory;
  account_name: string;
  owner: string | null;
  expiry_date: string | null;
  never_expires: boolean;
  password_changed_date: string | null;
  last_login_date: string | null;
  failed_logins: number | null;
  reset_url: string | null;
  notes: string | null;
}

/** Add — from the form, or from a check result carrying the directory's name for the account. */
export interface CredentialAccountCreateInput extends CredentialAccountInput {
  display_name?: string | null;
}

export interface CredentialAccount extends CredentialAccountInput {
  id: number;
  /** The directory's own name for the account (AD displayName), set by a check. */
  display_name: string | null;
  /** The most recent Credential Check of this account: the verdict only. */
  last_checked_at: string | null;
  last_check_status: string | null;
  last_checked_by: string | null;
  created_by: string | null;
  created_at: string | null;
  updated_by: string | null;
  updated_at: string | null;
}

/** An imported row: null means the file left it blank, which keeps what is recorded. */
export type CredentialAccountImportRow = Omit<CredentialAccountInput, "never_expires"> & {
  never_expires: boolean | null;
};

export interface ImportPreviewRow {
  row: number;
  action: "create" | "update" | "invalid";
  account: CredentialAccountImportRow | null;
  label: string;
  errors: string[];
}

export interface ImportPreview {
  rows: ImportPreviewRow[];
  total: number;
  create_count: number;
  update_count: number;
  invalid_count: number;
}

/** The grid's filters, sent with an export so the file holds the rows on screen. */
export interface AccountExportFilters {
  application?: string;
  account_type?: AccountType;
  directory?: AccountDirectory;
  view?: "expired" | "expiring" | "failing";
  q?: string;
}

export const useCredentialAccounts = () =>
  useQuery({
    queryKey: ACCOUNTS_KEY,
    queryFn: async () => (await apiClient.get<CredentialAccount[]>(ACCOUNTS)).data,
  });

function useAccountMutation<TInput, TResult>(mutationFn: (input: TInput) => Promise<TResult>) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn,
    onSuccess: () => qc.invalidateQueries({ queryKey: ACCOUNTS_KEY }),
  });
}

export const useCreateCredentialAccount = () =>
  useAccountMutation(
    async (input: CredentialAccountCreateInput) => (await apiClient.post<CredentialAccount>(ACCOUNTS, input)).data,
  );

export const useUpdateCredentialAccount = () =>
  useAccountMutation(
    async ({ id, input }: { id: number; input: CredentialAccountInput }) =>
      (await apiClient.put<CredentialAccount>(`${ACCOUNTS}/${id}`, input)).data,
  );

export const useDeleteCredentialAccount = () =>
  useAccountMutation(async (id: number) => (await apiClient.delete(`${ACCOUNTS}/${id}`)).data);

/** Reads the file and says what importing it would do. Writes nothing. */
export const usePreviewAccountImport = () =>
  useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      const { data } = await apiClient.post<ImportPreview>(`${ACCOUNTS}/import/preview`, form, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      return data;
    },
  });

export const useApplyAccountImport = () =>
  useAccountMutation(
    async (accounts: CredentialAccountImportRow[]) =>
      (await apiClient.post<{ created: number; updated: number }>(`${ACCOUNTS}/import`, { accounts })).data,
  );

/** Save a file the API streams back, using the name it suggests. */
async function downloadFile(path: string, params: Record<string, string | undefined>, fallbackName: string) {
  const response = await apiClient.get(path, { params, responseType: "blob" });
  const disposition: string | undefined = response.headers["content-disposition"];
  const filename = disposition?.split("filename=")[1]?.replace(/"/g, "") || fallbackName;
  const url = window.URL.createObjectURL(new Blob([response.data]));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(url);
}

export const downloadAccountsExport = (format: "xlsx" | "csv", filters: AccountExportFilters) =>
  downloadFile(`${ACCOUNTS}/export`, { format, ...filters }, `credential-accounts.${format}`);

export const downloadAccountsTemplate = () =>
  downloadFile(`${ACCOUNTS}/import-template`, {}, "credential-accounts-template.xlsx");
