/**
 * Requests — the approval queue for Project Admins (their projects) and Super
 * Admins (everything).
 *
 * Each requested line is decided on its own: approve (optionally at a lower
 * level than requested) or reject, with an optional comment. Actions are
 * enabled only where the backend says `can_decide` — never on your own
 * request, never outside your projects.
 */

import React, { useMemo, useState } from "react";
import { SortableHeader, gridStyles } from "../../components/gridStyles";
import TierBadge from "../../components/TierBadge";
import { formatAxiosError } from "../../services/apiErrors";
import {
  type AccessLevel,
  type AccessRequest,
  type AccessRequestItem,
  type RequestStatusFilter,
  useAdminRequests,
  useDecideRequestItem,
} from "../../services/accessApi";
import {
  AccessIcons,
  ActionIconButton,
  GridHeader,
  GridMessageRow,
  GridPagerBar,
  LEVEL_LABELS,
  LevelBadge,
  Modal,
  STATUS_LABELS,
  StatusBadge,
  compactSelectClass,
  fieldLabel,
  fmtWhen,
  inputClass,
  secondaryButton,
  textMatches,
  tierLabel,
  useGridRows,
} from "./accessShared";

interface QueueRow {
  request: AccessRequest;
  item: AccessRequestItem;
}

type QueueSortKey = "created_at" | "requester" | "project" | "target" | "tier" | "level" | "status";

const rowAccessor = ({ request, item }: QueueRow, key: QueueSortKey): string | number => {
  switch (key) {
    case "created_at":
      return request.created_at ?? "";
    case "requester":
      return request.requester_name ?? request.requester_email ?? "";
    case "project":
      return item.project_name ?? "";
    case "target":
      return item.scope_type === "app" ? item.app_name ?? "" : "All apps";
    case "tier":
      return item.tier;
    case "level":
      return item.requested_level;
    case "status":
      return item.status;
  }
};

const rowMatches = ({ request, item }: QueueRow, query: string) =>
  textMatches(
    query,
    `#${request.id}`,
    request.requester_name,
    request.requester_email,
    request.justification,
    item.project_name,
    item.app_name,
    tierLabel(item.tier),
    item.requested_level,
    item.status,
  );

const STATUS_FILTERS: RequestStatusFilter[] = ["pending", "approved", "partially_approved", "rejected", "cancelled", "all"];

interface DecisionTarget extends QueueRow {
  decision: "approve" | "reject";
}

const DecisionDialog: React.FC<{
  target: DecisionTarget;
  onClose: (message?: string) => void;
}> = ({ target, onClose }) => {
  const decide = useDecideRequestItem();
  const { request, item, decision } = target;
  const [level, setLevel] = useState<AccessLevel>(item.requested_level);
  const [comment, setComment] = useState("");
  const approving = decision === "approve";
  const who = request.requester_name ?? request.requester_email ?? request.requester_id;
  const what = `${item.project_name ?? "Project"} · ${item.scope_type === "app" ? item.app_name ?? "App" : "All apps"} · ${tierLabel(item.tier)}`;

  const handleConfirm = async () => {
    try {
      await decide.mutateAsync({
        requestId: request.id,
        itemId: item.id,
        decision,
        level: approving ? level : undefined,
        comment: comment.trim() || undefined,
      });
      onClose(
        approving
          ? `Approved ${LEVEL_LABELS[level].toLowerCase()} access to ${what} for ${who}.`
          : `Rejected ${what} for ${who}.`,
      );
    } catch {
      // Shown below.
    }
  };

  return (
    <Modal
      title={approving ? "Approve access" : "Reject access"}
      subtitle={`Request #${request.id} from ${who}`}
      onClose={() => onClose()}
      footer={
        <>
          <button type="button" className={secondaryButton} onClick={() => onClose()} disabled={decide.isPending}>
            Back
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={decide.isPending}
            className={
              approving
                ? "inline-flex items-center gap-2 px-4 py-2 bg-green-600 text-white rounded-lg text-sm font-semibold hover:bg-green-700 disabled:opacity-50 transition"
                : "inline-flex items-center gap-2 px-4 py-2 bg-red-600 text-white rounded-lg text-sm font-semibold hover:bg-red-700 disabled:opacity-50 transition"
            }
          >
            {decide.isPending ? "Saving…" : approving ? "Approve" : "Reject"}
          </button>
        </>
      }
    >
      <div className="rounded-lg border border-att-100 bg-att-50/50 px-3 py-2 text-sm text-gray-700 space-y-1">
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-semibold text-gray-800">{item.project_name}</span>
          <span>{item.scope_type === "app" ? item.app_name : "All apps"}</span>
          <TierBadge tier={item.tier} />
          <span className="text-xs text-gray-500">requested</span>
          <LevelBadge level={item.requested_level} />
        </div>
        <p className="text-xs text-gray-500">“{request.justification}”</p>
      </div>
      {approving && (
        <div>
          <label htmlFor="decision-level" className={fieldLabel}>
            Grant level
          </label>
          <select
            id="decision-level"
            value={level}
            onChange={(event) => setLevel(event.target.value as AccessLevel)}
            className={inputClass}
          >
            {item.requested_level === "write" && <option value="write">Write (as requested)</option>}
            <option value="read">{item.requested_level === "read" ? "Read (as requested)" : "Read (lower than requested)"}</option>
          </select>
          <p className="mt-1 text-xs text-gray-500">You can approve at the requested level or lower, not higher.</p>
        </div>
      )}
      <div>
        <label htmlFor="decision-comment" className={fieldLabel}>
          Comment {approving ? "(optional)" : "(optional, shared with the requester)"}
        </label>
        <textarea
          id="decision-comment"
          rows={3}
          maxLength={1000}
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          className={inputClass}
          placeholder={approving ? "e.g. approved for the Q4 release window" : "e.g. please request the app, not the whole project"}
        />
      </div>
      {decide.isError && (
        <p className="text-xs text-red-600" role="alert">
          {formatAxiosError(decide.error, "Failed to record the decision")}
        </p>
      )}
    </Modal>
  );
};

const RequestsQueueTab: React.FC<{ onNotify: (message: string) => void }> = ({ onNotify }) => {
  const [status, setStatus] = useState<RequestStatusFilter>("pending");
  const { data: requests = [], isLoading, isError, error } = useAdminRequests(status);
  const [target, setTarget] = useState<DecisionTarget | null>(null);

  const rows = useMemo<QueueRow[]>(
    () => requests.flatMap((request) => request.items.map((item) => ({ request, item }))),
    [requests],
  );
  // A "pending" request can already have some lines decided; count only the open ones.
  const openLines = rows.filter((row) => row.item.status === "pending").length;
  const decidable = rows.filter((row) => row.item.can_decide).length;

  const grid = useGridRows<QueueRow, QueueSortKey>(rows, {
    matches: rowMatches,
    accessor: rowAccessor,
    initialSort: { key: "created_at", direction: status === "pending" ? "asc" : "desc" },
  });
  const header = (label: string, key: QueueSortKey, center = false) => (
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

  return (
    <div className="space-y-4">
      <div className={gridStyles.shell}>
        <GridHeader
          title="Access requests"
          subtitle={
            status === "pending"
              ? `${openLines} pending line${openLines === 1 ? "" : "s"} · ${decidable} you can decide`
              : `${rows.length} line${rows.length === 1 ? "" : "s"}`
          }
          search={grid.search}
          onSearch={grid.setSearch}
          placeholder="Search requests…"
        >
          <label className="sr-only" htmlFor="request-status-filter">
            Status
          </label>
          <select
            id="request-status-filter"
            value={status}
            onChange={(event) => {
              setStatus(event.target.value as RequestStatusFilter);
              grid.setPage(0);
            }}
            className={compactSelectClass}
          >
            {STATUS_FILTERS.map((value) => (
              <option key={value} value={value}>
                {value === "all" ? "All statuses" : STATUS_LABELS[value]}
              </option>
            ))}
          </select>
        </GridHeader>
        <div className="overflow-x-auto">
          <table className={gridStyles.table}>
            <thead className={gridStyles.head}>
              <tr>
                {header("Submitted", "created_at")}
                {header("Requester", "requester")}
                {header("Project", "project")}
                {header("App / Scope", "target")}
                {header("Tier", "tier", true)}
                {header("Level", "level", true)}
                <th className={gridStyles.headerCell}>Justification</th>
                {header("Status", "status", true)}
                <th className={gridStyles.headerCellCenter}>Decision</th>
              </tr>
            </thead>
            <tbody>
              {isLoading ? (
                <GridMessageRow colSpan={9}>Loading requests…</GridMessageRow>
              ) : isError ? (
                <GridMessageRow colSpan={9} tone="error">
                  {formatAxiosError(error, "Failed to load requests")}
                </GridMessageRow>
              ) : grid.total === 0 ? (
                <GridMessageRow colSpan={9}>
                  {rows.length === 0
                    ? status === "pending"
                      ? "No pending requests. You're all caught up."
                      : "No requests with this status."
                    : "No requests match the current search."}
                </GridMessageRow>
              ) : (
                grid.pageRows.map(({ request, item }) => (
                  <tr key={item.id} className={`${gridStyles.row} align-top`}>
                    <td className={`${gridStyles.cell} whitespace-nowrap`}>
                      <span className="block font-mono text-xs text-gray-400">#{request.id}</span>
                      {fmtWhen(request.created_at)}
                    </td>
                    <td className={gridStyles.cell}>
                      <span className="block font-medium text-gray-800">{request.requester_name ?? "—"}</span>
                      <span className="block text-xs text-gray-500">{request.requester_email}</span>
                    </td>
                    <td className={gridStyles.strongCell}>{item.project_name ?? "—"}</td>
                    <td className={gridStyles.cell}>{item.scope_type === "app" ? item.app_name ?? "—" : "All apps"}</td>
                    <td className={gridStyles.centerCell}>
                      <TierBadge tier={item.tier} />
                    </td>
                    <td className={gridStyles.centerCell}>
                      <LevelBadge level={item.requested_level} />
                    </td>
                    <td className={`${gridStyles.cell} max-w-xs`}>
                      <span className="line-clamp-3 text-xs text-gray-600" title={request.justification}>
                        {request.justification}
                      </span>
                    </td>
                    <td className={gridStyles.centerCell}>
                      <StatusBadge status={item.status} />
                      {item.status !== "pending" && item.decided_by && (
                        <span className="block mt-1 text-[10px] text-gray-400" title={item.decision_comment ?? undefined}>
                          {item.status === "approved" && item.granted_level ? `${LEVEL_LABELS[item.granted_level]} · ` : ""}
                          {item.decided_by}
                        </span>
                      )}
                    </td>
                    <td className={gridStyles.centerCell}>
                      {item.status === "pending" ? (
                        <div className="flex justify-center gap-1">
                          <ActionIconButton
                            title={item.can_decide ? "Approve" : "You cannot decide this line (your own request, or not your project)"}
                            tone="green"
                            disabled={!item.can_decide}
                            onClick={() => setTarget({ request, item, decision: "approve" })}
                          >
                            {AccessIcons.approve()}
                          </ActionIconButton>
                          <ActionIconButton
                            title={item.can_decide ? "Reject" : "You cannot decide this line (your own request, or not your project)"}
                            tone="red"
                            disabled={!item.can_decide}
                            onClick={() => setTarget({ request, item, decision: "reject" })}
                          >
                            {AccessIcons.reject()}
                          </ActionIconButton>
                        </div>
                      ) : (
                        <span className="text-xs text-gray-300">—</span>
                      )}
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
          noun="lines"
        />
      </div>

      {target && (
        <DecisionDialog
          key={target.item.id}
          target={target}
          onClose={(message) => {
            setTarget(null);
            if (message) onNotify(message);
          }}
        />
      )}
    </div>
  );
};

export default RequestsQueueTab;
