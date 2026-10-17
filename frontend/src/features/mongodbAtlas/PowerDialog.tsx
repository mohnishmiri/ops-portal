/**
 * Stop (pause) or start (resume) one cluster, then follow it until Atlas
 * finishes. A production or unclassified cluster needs its name typed again
 * before it is stopped — the same rule the API enforces.
 */

import React, { useState } from "react";
import { Modal } from "../access/accessShared";
import { formatAxiosError } from "../../services/apiErrors";
import { type AtlasCluster, type AtlasOperation, type PowerAction, useOperation, usePowerCluster } from "../../services/mongodbAtlasApi";
import { invalidEmails } from "../environment/NotificationFields";
import { Spinner } from "../../components/gridStyles";
import { buttonTone, formatDuration, InfoNote, inputClass, labelClass, OperationStatusChip, TargetStatusText } from "./shared";

export const OperationProgress: React.FC<{ operationId: number }> = ({ operationId }) => {
  const { data: op } = useOperation(operationId);
  if (!op) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-500">
        <Spinner /> Loading…
      </div>
    );
  }
  return <OperationSummary op={op} />;
};

export const OperationSummary: React.FC<{ op: AtlasOperation }> = ({ op }) => (
  <div className="space-y-3" aria-live="polite">
    <div className="flex items-center gap-2">
      <OperationStatusChip status={op.status} />
      {op.status === "in_progress" && <Spinner />}
      <span className="text-xs text-slate-500">
        Operation #{op.id}
        {op.duration_seconds != null ? ` · took ${formatDuration(op.duration_seconds)}` : ""}
      </span>
    </div>
    <ul className="divide-y divide-att-100 rounded-lg border border-att-100">
      {op.targets.map((t) => (
        <li key={`${t.project_id}/${t.cluster_name}`} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm">
          <span>
            <span className="font-mono text-slate-800">{t.cluster_name}</span>
            <span className="ml-2 text-xs text-slate-500">{t.project_name}</span>
          </span>
          <span className="flex items-center gap-2">
            <TargetStatusText status={t.status} />
            {t.message && <span className="text-xs text-slate-500">{t.message}</span>}
          </span>
        </li>
      ))}
    </ul>
    {op.status === "in_progress" && (
      <p className="text-xs text-slate-500">
        Atlas usually takes 5–15 minutes. You can close this window; the Activity tab and the summary email follow it to the end.
      </p>
    )}
  </div>
);

export const PowerDialog: React.FC<{
  cluster: AtlasCluster;
  action: PowerAction;
  onClose: () => void;
  onStarted?: (op: AtlasOperation) => void;
}> = ({ cluster, action, onClose, onStarted }) => {
  const power = usePowerCluster();
  const [confirmName, setConfirmName] = useState("");
  const [reason, setReason] = useState("");
  const [notify, setNotify] = useState(true);
  const [emails, setEmails] = useState("");
  const [operationId, setOperationId] = useState<number | null>(null);

  const stopping = action === "pause";
  const needsName = stopping && cluster.is_production;
  const badEmails = invalidEmails(emails);
  const blocked = (needsName && confirmName.trim() !== cluster.name) || badEmails.length > 0 || power.isPending;
  const verb = stopping ? "Stop" : "Start";

  const submit = () => {
    power.mutate(
      {
        projectId: cluster.project_id,
        clusterName: cluster.name,
        action,
        confirm_name: needsName ? confirmName.trim() : undefined,
        reason: reason.trim() || undefined,
        notify,
        notification_emails: emails.trim() || undefined,
      },
      {
        onSuccess: (op) => {
          setOperationId(op.id);
          onStarted?.(op);
        },
      },
    );
  };

  return (
    <Modal
      title={`${verb} ${cluster.name}`}
      subtitle={`${cluster.project_name} · ${cluster.tier ?? "—"} · ${cluster.provider ?? ""}`}
      onClose={onClose}
      footer={
        operationId ? (
          <button type="button" onClick={onClose} className={buttonTone.primary}>
            Close
          </button>
        ) : (
          <>
            <button type="button" onClick={onClose} className={buttonTone.neutral} disabled={power.isPending}>
              Cancel
            </button>
            <button type="button" onClick={submit} disabled={blocked} className={stopping ? buttonTone.stop : buttonTone.start}>
              {power.isPending ? "Sending to Atlas…" : `${verb} cluster`}
            </button>
          </>
        )
      }
    >
      {operationId ? (
        <OperationProgress operationId={operationId} />
      ) : (
        <>
          {stopping ? (
            <InfoNote tone="warning">
              Applications lose their connection until the cluster is started again. While paused Atlas bills storage only,
              and it <b>starts the cluster by itself after 30 days</b>. Atlas will not pause a cluster that was started less
              than 60 minutes ago.
            </InfoNote>
          ) : (
            <InfoNote>Starting takes several minutes. Connection strings and data are unchanged.</InfoNote>
          )}
          {cluster.schedules && cluster.schedules.length > 0 && (
            <InfoNote>
              On {cluster.schedules.length === 1 ? "a schedule" : `${cluster.schedules.length} schedules`} (
              {cluster.schedules.map((s) => s.name).join(", ")}) — its next run still happens.
            </InfoNote>
          )}
          {needsName && (
            <div>
              <label htmlFor="atlas-confirm-name" className={labelClass}>
                {cluster.environment === "production" ? "Production cluster" : "Unclassified cluster (treated as production)"} — type{" "}
                <span className="font-mono">{cluster.name}</span> to confirm
              </label>
              <input
                id="atlas-confirm-name"
                value={confirmName}
                onChange={(e) => setConfirmName(e.target.value)}
                autoComplete="off"
                className={`${inputClass} font-mono`}
              />
            </div>
          )}
          <div>
            <label htmlFor="atlas-reason" className={labelClass}>
              Reason <span className="font-normal text-slate-400">(optional, recorded in the audit log and email)</span>
            </label>
            <input
              id="atlas-reason"
              value={reason}
              maxLength={500}
              onChange={(e) => setReason(e.target.value)}
              placeholder={stopping ? "e.g. not needed over the weekend" : "e.g. release testing"}
              className={inputClass}
            />
          </div>
          <label className="flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={notify} onChange={(e) => setNotify(e.target.checked)} className="h-4 w-4 rounded border-att-300" />
            Email me a summary when Atlas finishes
          </label>
          <div>
            <label htmlFor="atlas-emails" className={labelClass}>
              Also send to <span className="font-normal text-slate-400">(optional)</span>
            </label>
            <input
              id="atlas-emails"
              value={emails}
              onChange={(e) => setEmails(e.target.value)}
              placeholder="team-dl@att.com"
              aria-invalid={badEmails.length > 0 || undefined}
              className={`${inputClass} ${badEmails.length ? "border-red-300" : ""}`}
            />
            {badEmails.length > 0 && <p className="mt-1 text-xs text-red-600">Not a valid email address: {badEmails.slice(0, 3).join(", ")}</p>}
          </div>
          {power.isError && <InfoNote tone="error">{formatAxiosError(power.error, `Could not ${verb.toLowerCase()} the cluster`)}</InfoNote>}
        </>
      )}
    </Modal>
  );
};
