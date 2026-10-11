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
 * Handling of secrets on this page:
 *  • a credential is held in component state only until its check returns,
 *    then cleared — nothing is cached by React Query or written to storage;
 *  • inputs are type="password" with autoComplete off;
 *  • nothing is persisted anywhere: no audit row, no history, no result log.
 *
 * Gating matches the API exactly: canWrite && hasCapability("credential_check").
 */

import React, { useCallback, useState } from "react";
import { MetricCardIcons } from "../components/MetricCard";
import { useAuth } from "../contexts/AuthContext";
import { usePermissions } from "../contexts/PermissionsContext";
import { fieldLabel, inputClass, panelClass, primaryButton } from "../features/access/accessShared";
import { formatAxiosError } from "../services/apiErrors";
import {
  type AafEnvironment,
  type CheckKind,
  type CredentialCheckResult,
  type DomainName,
  useCheckAafPassword,
  useCheckDomainPassword,
  useCheckJFrogToken,
} from "../services/toolsApi";

// ── Status presentation ──────────────────────────────────────────────────────

/**
 * Every status the backend can return. "error" means the check never reached
 * a verdict (DNS, TLS, timeout) and must never read as "wrong password".
 */
const STATUS_STYLES: Record<string, { label: string; chip: string; tone: "green" | "red" | "amber" | "slate" }> = {
  valid:        { label: "Valid",            chip: "bg-green-100 text-green-700", tone: "green" },
  invalid:      { label: "Rejected",         chip: "bg-red-100 text-red-700",     tone: "red" },
  expired:      { label: "Expired",          chip: "bg-amber-100 text-amber-800", tone: "amber" },
  must_change:  { label: "Must change",      chip: "bg-amber-100 text-amber-800", tone: "amber" },
  locked:       { label: "Locked out",       chip: "bg-red-100 text-red-700",     tone: "red" },
  disabled:     { label: "Disabled",         chip: "bg-red-100 text-red-700",     tone: "red" },
  denied:       { label: "Sign-in denied",   chip: "bg-amber-100 text-amber-800", tone: "amber" },
  rate_limited: { label: "Rate limited",     chip: "bg-slate-100 text-slate-700", tone: "slate" },
  lockout_guard:{ label: "Blocked",          chip: "bg-slate-100 text-slate-700", tone: "slate" },
  unconfigured: { label: "Not configured",   chip: "bg-slate-100 text-slate-700", tone: "slate" },
  error:        { label: "Unreachable",      chip: "bg-slate-100 text-slate-700", tone: "slate" },
};

const statusStyle = (status: string) => STATUS_STYLES[status] ?? STATUS_STYLES.error;

const StatusChip: React.FC<{ status: string }> = ({ status }) => {
  const style = statusStyle(status);
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${style.chip}`}>
      {style.label}
    </span>
  );
};

// ── Result panel ─────────────────────────────────────────────────────────────

const ResultPanel: React.FC<{ result: CredentialCheckResult | null; error: string | null }> = ({ result, error }) => {
  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2.5 text-sm text-red-700" role="alert">
        {error}
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
    <div className={`rounded-lg border px-4 py-3 text-sm ${surface}`} role="status">
      <div className="flex flex-wrap items-center gap-2">
        <StatusChip status={result.status} />
        <span className="font-mono text-xs">{result.target}</span>
      </div>
      <p className="mt-1.5">{result.message}</p>
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
  children: React.ReactNode;
}> = ({ title, description, icon, onSubmit, allowed, incomplete, pending, result, error, children }) => (
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

    <ResultPanel result={result} error={error} />
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
  const [jfrogUsername, setJfrogUsername] = useState("");
  const [jfrogToken, setJfrogToken] = useState("");
  const [aafEnvironment, setAafEnvironment] = useState<AafEnvironment>("prod");
  const [aafAccount, setAafAccount] = useState("");
  const [aafPassword, setAafPassword] = useState("");

  const [results, setResults] = useState<Partial<Record<CheckKind, CredentialCheckResult>>>({});
  const [errors, setErrors] = useState<Partial<Record<CheckKind, string>>>({});

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

  return (
    <div className="py-6 space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-3xl font-bold text-gray-900 flex items-center gap-3">
          {MetricCardIcons.shield("h-8 w-8 text-att-500")}
          Credential Check
        </h1>
        <p className="mt-1 text-sm text-gray-500">
          Check whether a domain password, a JFrog token or an AAF account password still authenticates. Nothing is
          stored — the credential and the result are gone as soon as the answer is shown.
        </p>
      </div>

      <div className="rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
        <span className="font-semibold">A failed check counts as a failed sign-in.</span> Repeated wrong passwords can
        lock the account out in Active Directory, so the portal pauses a target after a few failures in a row. Check a
        password you believe is current — this is not a way to find one.
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
          description="Username and token, checked against artifact.it.att.com."
          icon={MetricCardIcons.layers("h-5 w-5")}
          onSubmit={() =>
            run(
              "jfrog",
              jfrogCheck.mutateAsync,
              { username: jfrogUsername.trim(), token: jfrogToken },
              () => setJfrogToken(""),
            )
          }
          allowed={canCheck}
          incomplete={!jfrogUsername.trim() || !jfrogToken}
          pending={jfrogCheck.isPending}
          result={results.jfrog ?? null}
          error={errors.jfrog ?? null}
        >
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
              type="password"
              className={inputClass}
              value={aafPassword}
              onChange={(event) => setAafPassword(event.target.value)}
              autoComplete="off"
            />
          </div>
        </CheckCard>
      </div>

    </div>
  );
};

export default CredentialCheckPage;
