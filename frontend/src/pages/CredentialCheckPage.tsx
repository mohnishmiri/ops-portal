/**
 * Tools → Credential Check.
 *
 * Answers "does this credential still work?" for the three the team keeps
 * running into: an ITSERVICES / TESTITSERVICES domain password, a JFrog
 * token, and an AAF account password. Infrastructure Alerts → Expiry
 * Tracking already says when one is *due* to expire; this says whether it
 * authenticates right now, and for Active Directory it distinguishes a wrong
 * password from an expired one, a locked account and a disabled account.
 *
 * A result also carries what the source will say about the credential —
 * expiry, last change, last use. Each source exposes a different subset (AAF
 * records no last use; AD's last sign-in is only accurate to 9–14 days), so
 * a missing value reads "Not reported", with the backend's reason.
 *
 * Handling of secrets on this page:
 *  • a credential is held in component state only until its check returns,
 *    then cleared — nothing is cached by React Query or written to storage;
 *  • inputs are type="password" with autoComplete off;
 *  • the credential is never persisted: no audit row, no history of checks.
 *    When the checked account is in the inventory below, its row records the
 *    verdict and the reported expiry / last sign-in — never the secret.
 *
 * Gating matches the API exactly: canWrite && hasCapability("credential_check").
 */

import React, { useCallback, useRef, useState } from "react";
import { MetricCardIcons } from "../components/MetricCard";
import { useAuth } from "../contexts/AuthContext";
import { usePermissions } from "../contexts/PermissionsContext";
import { fieldLabel, inputClass, panelClass, primaryButton } from "../features/access/accessShared";
import { DaysLeftBadge, daysUntil } from "../features/keyvault/kvShared";
import AccountInventory from "../features/tools/AccountInventory";
import AddToInventory from "../features/tools/AddToInventory";
import { StatusChip, statusStyle } from "../features/tools/credentialStatus";
import { formatAxiosError } from "../services/apiErrors";
import {
  type AafEnvironment,
  type CheckKind,
  type CredentialAccountDetails,
  type CredentialAccount,
  type CredentialCheckResult,
  type DomainName,
  type JFrogInstance,
  useCheckAafPassword,
  useCheckDomainPassword,
  useCheckJFrogToken,
} from "../services/toolsApi";
import { formatDate, formatDateTime, parseApiDate } from "../utils/dateFormat";

// ── Account details ──────────────────────────────────────────────────────────

/** Row labels differ by source: a JFrog token is "issued", a password "changed". */
const DETAIL_LABELS: Record<CheckKind, { name: string; expires: string; changed: string; used: string }> = {
  domain: { name: "Name", expires: "Password expires", changed: "Password last changed", used: "Last sign-in" },
  jfrog: { name: "Description", expires: "Token expires", changed: "Issued", used: "Last used" },
  aaf: { name: "Name", expires: "Password expires", changed: "Password last changed", used: "Last used" },
};

/** "in 3 days" / "27 days ago" / "today". */
const relativeDays = (iso: string): string => {
  const date = parseApiDate(iso);
  if (!date) return "";
  const days = Math.round((date.getTime() - Date.now()) / 86_400_000);
  if (days === 0) return "today";
  const count = `${Math.abs(days)} day${Math.abs(days) === 1 ? "" : "s"}`;
  return days > 0 ? `in ${count}` : `${count} ago`;
};

/** Local calendar date, with the full time on hover. */
const DateValue: React.FC<{ iso: string }> = ({ iso }) => (
  <span title={formatDateTime(iso)}>{formatDate(parseApiDate(iso))}</span>
);

/** Label left, value right, with any caveat on its own line beneath. */
const DetailRow: React.FC<{ label: string; hint?: string | null; children: React.ReactNode }> = ({
  label,
  hint,
  children,
}) => (
  <div className="py-1.5">
    <div className="flex items-baseline justify-between gap-4">
      <dt className="shrink-0 opacity-75">{label}</dt>
      <dd className="flex flex-wrap items-center justify-end gap-x-2 gap-y-1 text-right font-medium">{children}</dd>
    </div>
    {hint && <p className="mt-0.5 opacity-70">{hint}</p>}
  </div>
);

const NotReported: React.FC<{ text?: string | null }> = ({ text }) => (
  <span className="opacity-75">{text || "Not reported"}</span>
);

/**
 * Expiry and last use, as far as the source would say. Expiry and last use
 * always get a row, so a gap reads as "not reported" rather than vanishing.
 */
const AccountDetails: React.FC<{ kind: CheckKind; account: CredentialAccountDetails }> = ({ kind, account }) => {
  const labels = DETAIL_LABELS[kind];
  return (
    <div className="mt-3 text-xs">
      <dl className="divide-y divide-black/5 border-y border-black/5">
        {account.display_name && <DetailRow label={labels.name}>{account.display_name}</DetailRow>}
        <DetailRow label={labels.expires}>
          {account.never_expires ? (
            <span>Never</span>
          ) : account.expires_at ? (
            <>
              <DateValue iso={account.expires_at} />
              <DaysLeftBadge days={daysUntil(account.expires_at)} />
            </>
          ) : (
            <NotReported />
          )}
        </DetailRow>
        {account.last_changed_at && (
          <DetailRow label={labels.changed}>
            <DateValue iso={account.last_changed_at} />
            <span className="opacity-75">{relativeDays(account.last_changed_at)}</span>
          </DetailRow>
        )}
        <DetailRow label={labels.used} hint={account.last_used_at ? account.last_used_note : null}>
          {account.last_used_at ? (
            <>
              <DateValue iso={account.last_used_at} />
              <span className="opacity-75">{relativeDays(account.last_used_at)}</span>
            </>
          ) : (
            <NotReported text={account.last_used_note} />
          )}
        </DetailRow>
        {(account.failed_sign_ins !== null || account.last_failed_at) && (
          <DetailRow label="Failed sign-ins" hint={account.failed_sign_ins_note}>
            {account.failed_sign_ins === null ? (
              <NotReported />
            ) : (
              <span className={account.failed_sign_ins > 0 ? "font-semibold" : undefined}>
                {account.failed_sign_ins}
              </span>
            )}
            {account.last_failed_at && (
              <span className="opacity-75">
                last on <DateValue iso={account.last_failed_at} />
              </span>
            )}
          </DetailRow>
        )}
        {account.account_expires_at && (
          <DetailRow label="Account expires">
            <DateValue iso={account.account_expires_at} />
            <DaysLeftBadge days={daysUntil(account.account_expires_at)} />
          </DetailRow>
        )}
      </dl>
      {account.notes.map((note) => (
        <p key={note} className="mt-2 opacity-75">
          {note}
        </p>
      ))}
    </div>
  );
};

// ── Result panel ─────────────────────────────────────────────────────────────

/** Clears an answer that has been read, so the card is ready for the next account. */
const DismissButton: React.FC<{ onClick: () => void; label: string }> = ({ onClick, label }) => (
  <button
    type="button"
    onClick={onClick}
    title={label}
    aria-label={label}
    className="absolute right-1.5 top-1.5 rounded p-1 opacity-60 transition hover:bg-black/5 hover:opacity-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-current"
  >
    <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" aria-hidden="true">
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  </button>
);

const ResultPanel: React.FC<{
  result: CredentialCheckResult | null;
  error: string | null;
  onDismiss: () => void;
}> = ({ result, error, onDismiss }) => {
  if (error) {
    return (
      <div className="relative rounded-lg border border-red-200 bg-red-50 py-2.5 pl-4 pr-9 text-sm text-red-700" role="alert">
        {error}
        <DismissButton onClick={onDismiss} label="Dismiss this message" />
      </div>
    );
  }
  if (!result) return null;

  const style = statusStyle(result.status);
  const surface =
    style.tone === "green"
      ? "border-green-200 bg-green-50 text-green-800"
      : style.tone === "red"
        ? "border-red-200 bg-red-50 text-red-800"
        : style.tone === "amber"
          ? "border-amber-200 bg-amber-50 text-amber-900"
          : "border-slate-200 bg-slate-50 text-slate-700";

  return (
    <div className={`relative rounded-lg border px-4 py-3 text-sm ${surface}`} role="status">
      <div className="flex flex-wrap items-center gap-2 pr-6">
        <StatusChip status={result.status} />
        <span className="break-all font-mono text-xs">{result.target}</span>
      </div>
      <DismissButton onClick={onDismiss} label={`Dismiss the result for ${result.target}`} />
      <p className="mt-1.5">{result.message}</p>
      {/* The lockout risk is real only once a password has been refused, so it
          is said then rather than standing on the page for everyone. */}
      {result.kind === "domain" && result.status === "invalid" && (
        <p className="mt-2 rounded-md bg-black/5 px-2.5 py-1.5 text-xs">
          <span className="font-semibold">That counted as a failed sign-in.</span> A few more wrong passwords in a row
          can lock this account out in Active Directory, so the portal pauses it after a few failures. Check a password
          you believe is current — this is not a way to find one.
        </p>
      )}
      {result.account && <AccountDetails kind={result.kind} account={result.account} />}
      <p className="mt-2 text-xs opacity-70">
        Checked {formatDateTime(result.checked_at)}
        {result.inventory_updated && " · saved to this account's row in the inventory below"}
      </p>
      <AddToInventory result={result} />
    </div>
  );
};

// ── Check card shell ─────────────────────────────────────────────────────────

const CheckCard: React.FC<{
  title: string;
  description: string;
  icon: React.ReactNode;
  onSubmit: () => void;
  /** False only when the user genuinely lacks permission. */
  allowed: boolean;
  /** True while a required field is still empty. */
  incomplete: boolean;
  pending: boolean;
  result: CredentialCheckResult | null;
  error: string | null;
  /** Clears the answer shown under this card. */
  onDismiss: () => void;
  children: React.ReactNode;
}> = ({ title, description, icon, onSubmit, allowed, incomplete, pending, result, error, onDismiss, children }) => (
  <form
    className={`${panelClass} flex flex-col gap-4`}
    onSubmit={(event) => {
      event.preventDefault();
      if (allowed && !incomplete && !pending) onSubmit();
    }}
  >
    <div className="flex items-start gap-3">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-att-100 text-att-700">{icon}</span>
      <div className="min-w-0">
        <h2 className="font-semibold text-gray-800">{title}</h2>
        <p className="mt-0.5 text-xs text-gray-500">{description}</p>
      </div>
    </div>

    <div className="space-y-3">{children}</div>

    <div className="flex items-center gap-3">
      <button type="submit" className={primaryButton} disabled={!allowed || incomplete || pending}>
        {pending ? "Checking…" : "Check"}
      </button>
      {/* Only a real permission problem says so — an empty field is not one. */}
      {!allowed && <span className="text-xs text-gray-500">You do not have permission to run checks.</span>}
    </div>

    <ResultPanel result={result} error={error} onDismiss={onDismiss} />
  </form>
);

// ── Page ─────────────────────────────────────────────────────────────────────

const CredentialCheckPage: React.FC = () => {
  const { canWrite } = useAuth();
  const { hasCapability } = usePermissions();
  const canCheck = canWrite && hasCapability("credential_check");

  const [domain, setDomain] = useState<DomainName>("ITSERVICES");
  const [username, setUsername] = useState("");
  const [domainPassword, setDomainPassword] = useState("");
  const [jfrogInstance, setJfrogInstance] = useState<JFrogInstance>("bronze");
  const [jfrogUsername, setJfrogUsername] = useState("");
  const [jfrogToken, setJfrogToken] = useState("");
  const [aafEnvironment, setAafEnvironment] = useState<AafEnvironment>("prod");
  const [aafAccount, setAafAccount] = useState("");
  const [aafPassword, setAafPassword] = useState("");

  const [results, setResults] = useState<Partial<Record<CheckKind, CredentialCheckResult>>>({});
  const [errors, setErrors] = useState<Partial<Record<CheckKind, string>>>({});

  // The secret field each card focuses when the inventory's "Check" fills it in.
  const secretInputs = {
    domain: useRef<HTMLInputElement>(null),
    jfrog: useRef<HTMLInputElement>(null),
    aaf: useRef<HTMLInputElement>(null),
  };

  const domainCheck = useCheckDomainPassword();
  const jfrogCheck = useCheckJFrogToken();
  const aafCheck = useCheckAafPassword();

  /**
   * Run one check and clear its secret afterwards, whatever the outcome —
   * a password left in state would survive in a React DevTools snapshot.
   */
  const run = useCallback(
    async <TInput,>(
      kind: CheckKind,
      mutate: (input: TInput) => Promise<CredentialCheckResult>,
      input: TInput,
      clearSecret: () => void,
    ) => {
      setErrors((current) => ({ ...current, [kind]: undefined }));
      setResults((current) => ({ ...current, [kind]: undefined }));
      try {
        const result = await mutate(input);
        setResults((current) => ({ ...current, [kind]: result }));
      } catch (error) {
        setErrors((current) => ({ ...current, [kind]: formatAxiosError(error) }));
      } finally {
        clearSecret();
      }
    },
    [],
  );

  /** Clear the answer under one card. */
  const dismiss = useCallback((kind: CheckKind) => {
    setResults((current) => ({ ...current, [kind]: undefined }));
    setErrors((current) => ({ ...current, [kind]: undefined }));
  }, []);

  /** The inventory's "Check": fill in the card for that account and put the cursor in its secret field. */
  const prefillCheck = (account: CredentialAccount) => {
    const kind = account.account_type;
    if (kind === "domain") {
      setDomain(account.directory as DomainName);
      setUsername(account.account_name);
    } else if (kind === "jfrog") {
      setJfrogInstance(account.directory as JFrogInstance);
      setJfrogUsername(account.account_name);
    } else {
      setAafEnvironment(account.directory as AafEnvironment);
      setAafAccount(account.account_name);
    }
    setResults((current) => ({ ...current, [kind]: undefined }));
    setErrors((current) => ({ ...current, [kind]: undefined }));
    const input = secretInputs[kind].current;
    input?.scrollIntoView?.({ behavior: "smooth", block: "center" });
    input?.focus({ preventScroll: true });
  };

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
          {MetricCardIcons.shield("h-8 w-8 text-att-500")}
          Credential Check
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Check whether a domain password, a JFrog token or an AAF account password still authenticates — and, where
          the source reports it, when it expires and when it was last used. The password or token is never stored;
          checking an account listed in the inventory below updates its row with the result.
        </p>
      </div>

      {/* Checks */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <CheckCard
          title="Domain account"
          description="ITSERVICES or TESTITSERVICES password, checked by binding to Active Directory."
          icon={MetricCardIcons.server("h-5 w-5")}
          onSubmit={() =>
            run(
              "domain",
              domainCheck.mutateAsync,
              { domain, username: username.trim(), password: domainPassword },
              () => setDomainPassword(""),
            )
          }
          allowed={canCheck}
          incomplete={!username.trim() || !domainPassword}
          pending={domainCheck.isPending}
          result={results.domain ?? null}
          error={errors.domain ?? null}
          onDismiss={() => dismiss("domain")}
        >
          <div>
            <label className={fieldLabel} htmlFor="cc-domain">
              Domain
            </label>
            <select
              id="cc-domain"
              className={inputClass}
              value={domain}
              onChange={(event) => setDomain(event.target.value as DomainName)}
            >
              <option value="ITSERVICES">ITSERVICES</option>
              <option value="TESTITSERVICES">TESTITSERVICES</option>
            </select>
          </div>
          <div>
            <label className={fieldLabel} htmlFor="cc-username">
              Username
            </label>
            <input
              id="cc-username"
              className={inputClass}
              value={username}
              onChange={(event) => setUsername(event.target.value)}
              placeholder="m52142"
              autoComplete="off"
            />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="cc-domain-password">
              Password
            </label>
            <input
              id="cc-domain-password"
              ref={secretInputs.domain}
              type="password"
              className={inputClass}
              value={domainPassword}
              onChange={(event) => setDomainPassword(event.target.value)}
              autoComplete="off"
            />
          </div>
        </CheckCard>

        <CheckCard
          title="JFrog token"
          description="Username and token, checked against Artifactory Bronze (artifact.it.att.com) or Gold (artifact-gold.it.att.com)."
          icon={MetricCardIcons.layers("h-5 w-5")}
          onSubmit={() =>
            run(
              "jfrog",
              jfrogCheck.mutateAsync,
              { instance: jfrogInstance, username: jfrogUsername.trim(), token: jfrogToken },
              () => setJfrogToken(""),
            )
          }
          allowed={canCheck}
          incomplete={!jfrogUsername.trim() || !jfrogToken}
          pending={jfrogCheck.isPending}
          result={results.jfrog ?? null}
          error={errors.jfrog ?? null}
          onDismiss={() => dismiss("jfrog")}
        >
          <div>
            <label className={fieldLabel} htmlFor="cc-jfrog-instance">
              Instance
            </label>
            <select
              id="cc-jfrog-instance"
              className={inputClass}
              value={jfrogInstance}
              onChange={(event) => setJfrogInstance(event.target.value as JFrogInstance)}
            >
              <option value="bronze">Bronze — artifact.it.att.com</option>
              <option value="gold">Gold — artifact-gold.it.att.com</option>
            </select>
          </div>
          <div>
            <label className={fieldLabel} htmlFor="cc-jfrog-username">
              Username
            </label>
            <input
              id="cc-jfrog-username"
              className={inputClass}
              value={jfrogUsername}
              onChange={(event) => setJfrogUsername(event.target.value)}
              placeholder="m52142@att.com"
              autoComplete="off"
            />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="cc-jfrog-token">
              Token
            </label>
            <input
              id="cc-jfrog-token"
              ref={secretInputs.jfrog}
              type="password"
              className={inputClass}
              value={jfrogToken}
              onChange={(event) => setJfrogToken(event.target.value)}
              placeholder="Paste the token"
              autoComplete="off"
            />
            <p className="mt-1 text-xs text-gray-500">
              An identity token, access token or API key. It is used for this one request and not stored.
            </p>
          </div>
        </CheckCard>

        <CheckCard
          title="AAF account"
          description="AAF identity and password, checked against the Prod or IST instance."
          icon={MetricCardIcons.shield("h-5 w-5")}
          onSubmit={() =>
            run(
              "aaf",
              aafCheck.mutateAsync,
              { environment: aafEnvironment, account: aafAccount.trim(), password: aafPassword },
              () => setAafPassword(""),
            )
          }
          allowed={canCheck}
          incomplete={!aafAccount.trim() || !aafPassword}
          pending={aafCheck.isPending}
          result={results.aaf ?? null}
          error={errors.aaf ?? null}
          onDismiss={() => dismiss("aaf")}
        >
          <div>
            <label className={fieldLabel} htmlFor="cc-aaf-env">
              Environment
            </label>
            <select
              id="cc-aaf-env"
              className={inputClass}
              value={aafEnvironment}
              onChange={(event) => setAafEnvironment(event.target.value as AafEnvironment)}
            >
              <option value="prod">Prod</option>
              <option value="nonprod">Non-Prod (IST)</option>
            </select>
          </div>
          <div>
            <label className={fieldLabel} htmlFor="cc-aaf-account">
              Account
            </label>
            <input
              id="cc-aaf-account"
              className={inputClass}
              value={aafAccount}
              onChange={(event) => setAafAccount(event.target.value)}
              placeholder="m52142@com.att.attcc"
              autoComplete="off"
            />
          </div>
          <div>
            <label className={fieldLabel} htmlFor="cc-aaf-password">
              Password
            </label>
            <input
              id="cc-aaf-password"
              ref={secretInputs.aaf}
              type="password"
              className={inputClass}
              value={aafPassword}
              onChange={(event) => setAafPassword(event.target.value)}
              autoComplete="off"
            />
          </div>
        </CheckCard>
      </div>

      <AccountInventory canCheck={canCheck} onCheck={prefillCheck} />
    </div>
  );
};

export default CredentialCheckPage;
