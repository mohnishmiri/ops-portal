/**
 * Who receives Environment Scheduler run-summary emails, and when. Shared by
 * the sequence builder and the schedule form so both read the same way.
 */

import React from "react";
import type { NotifyOn } from "../../services/environmentApi";

export const NOTIFY_OPTIONS: { value: NotifyOn; label: string }[] = [
  { value: "always", label: "Every run" },
  { value: "failure", label: "Only when a run fails" },
  { value: "never", label: "Never" },
];

const EMAIL_RE = /^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$/;

/** Entries in a comma/semicolon/space separated list that aren't email addresses. */
export function invalidEmails(value: string | null | undefined): string[] {
  return (value ?? "").split(/[,;\s]+/).filter((part) => part && !EMAIL_RE.test(part));
}

interface Props {
  notifyOn: NotifyOn;
  onNotifyOnChange: (value: NotifyOn) => void;
  emails: string;
  onEmailsChange: (value: string) => void;
  /** Who is always emailed, e.g. "Whoever starts a run". */
  alwaysIncluded: string;
  idPrefix: string;
}

export const NotificationFields: React.FC<Props> = ({ notifyOn, onNotifyOnChange, emails, onEmailsChange, alwaysIncluded, idPrefix }) => {
  const invalid = invalidEmails(emails);
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <div>
        <label htmlFor={`${idPrefix}-notify-on`} className="text-xs font-semibold text-gray-600">Email run summary</label>
        <select
          id={`${idPrefix}-notify-on`}
          value={notifyOn}
          onChange={(e) => onNotifyOnChange(e.target.value as NotifyOn)}
          className="mt-1 w-full rounded-lg border border-gray-300 px-3 py-2 text-sm"
        >
          {NOTIFY_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
      </div>
      <div className="md:col-span-2">
        <label htmlFor={`${idPrefix}-notify-emails`} className="text-xs font-semibold text-gray-600">
          Also send to <span className="font-normal text-gray-400">(optional, e.g. a team DL)</span>
        </label>
        <input
          id={`${idPrefix}-notify-emails`}
          value={emails}
          onChange={(e) => onEmailsChange(e.target.value)}
          disabled={notifyOn === "never"}
          aria-invalid={invalid.length > 0 || undefined}
          placeholder="ops-team@att.com, oncall@att.com"
          className={`mt-1 w-full rounded-lg border px-3 py-2 text-sm disabled:bg-gray-50 disabled:text-gray-400 ${invalid.length ? "border-red-300" : "border-gray-300"}`}
        />
        {invalid.length > 0 ? (
          <p className="mt-1 text-xs text-red-600">Not a valid email address: {invalid.slice(0, 3).join(", ")}</p>
        ) : (
          <p className="mt-1 text-xs text-gray-400">
            {notifyOn === "never"
              ? "No summary emails are sent."
              : `${alwaysIncluded} always receives it. The summary lists each step, its replica change and result, and why a run failed.`}
          </p>
        )}
      </div>
    </div>
  );
};
