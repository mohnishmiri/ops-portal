/**
 * How a credential-check verdict is shown — shared by the check results and
 * the inventory grid's "last check" column, so one verdict reads the same in
 * both places.
 */

import React from "react";

/**
 * Every status the backend can return. "error" means the check never reached
 * a verdict (DNS, TLS, timeout) and must never read as "wrong password".
 */
export const STATUS_STYLES: Record<string, { label: string; chip: string; tone: "green" | "red" | "amber" | "slate" }> = {
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

/** A last check with one of these verdicts means the account cannot sign in. */
export const FAILING_STATUSES = new Set(["invalid", "expired", "locked", "disabled", "must_change", "denied"]);

export const statusStyle = (status: string) => STATUS_STYLES[status] ?? STATUS_STYLES.error;

export const StatusChip: React.FC<{ status: string }> = ({ status }) => {
  const style = statusStyle(status);
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${style.chip}`}>
      {style.label}
    </span>
  );
};

// ── The account itself, as its directory reports it ──────────────────────────

/**
 * Whether the account can sign in at all — a different question from whether
 * one password works, so it reads differently: a verdict chip is about a
 * moment, this is about the account.
 *
 * "Inactive" is the portal's own reading of a stale sign-in rather than a flag
 * Active Directory holds, so the note that comes with it says the threshold.
 */
export const ACCOUNT_STATUS_STYLES: Record<string, { label: string; chip: string }> = {
  active: { label: "Active", chip: "bg-green-100 text-green-700" },
  inactive: { label: "Inactive", chip: "bg-amber-100 text-amber-800" },
  disabled: { label: "Disabled", chip: "bg-red-100 text-red-700" },
  locked: { label: "Locked out", chip: "bg-red-100 text-red-700" },
  expired: { label: "Account expired", chip: "bg-red-100 text-red-700" },
};

/** Account states that mean it cannot sign in, whatever its password says. */
export const UNUSABLE_STATUSES = new Set(["disabled", "locked", "expired"]);

export const AccountStatusChip: React.FC<{ status: string; title?: string }> = ({ status, title }) => {
  const style = ACCOUNT_STATUS_STYLES[status];
  if (!style) return null;
  return (
    <span
      title={title}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${style.chip}`}
    >
      {style.label}
    </span>
  );
};
