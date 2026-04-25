/**
 * Checksum Schedule List Component
 * 
 * Displays all checksum schedules in a table with actions:
 * - View schedule details
 * - Edit schedule
 * - Delete schedule
 * - Test schedule execution
 */

import React, { useEffect, useMemo, useState } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { ChecksumScheduleDetail } from "../../services/checksumScheduleApi";
import { AutoRefreshIndicator, gridStyles, nextSortState, SortableHeader, type SortState } from "../../components/gridStyles";
import { usePortalTimezone } from "../../contexts/TimezoneContext";

/* ── SVG Icon Helpers ──────────────────────────────────────────────── */
const InfoIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <circle cx="12" cy="12" r="10" /><line x1="12" y1="16" x2="12" y2="12" /><line x1="12" y1="8" x2="12.01" y2="8" />
  </svg>
);
const PlayIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polygon points="5 3 19 12 5 21 5 3" />
  </svg>
);
const PencilIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <path d="M11 4H4a2 2 0 00-2 2v14a2 2 0 002 2h14a2 2 0 002-2v-7" /><path d="M18.5 2.5a2.121 2.121 0 013 3L12 15l-4 1 1-4 9.5-9.5z" />
  </svg>
);
const TrashIcon = () => (
  <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <polyline points="3 6 5 6 21 6" /><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2" />
  </svg>
);

interface ChecksumScheduleListProps {
  schedules: ChecksumScheduleDetail[];
  isLoading: boolean;
  onEdit: (schedule: ChecksumScheduleDetail) => void;
  onDelete: (schedule: ChecksumScheduleDetail) => void;
  onTest: (schedule: ChecksumScheduleDetail) => void;
  onToggle: (schedule: ChecksumScheduleDetail) => void;
  runningScheduleId?: string | number | null;
}

const PAGE_SIZE = 10;

type ScheduleSortKey =
  | "name"
  | "module_type"
  | "schedule_type"
  | "last_run_at"
  | "next_run_at"
  | "is_enabled";

const getLastRunDisplay = (lastRunAt: string | undefined, fmtShort: (v: string) => string): string => {
  if (!lastRunAt) return "Never";
  const date = new Date(lastRunAt);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "Just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 30) return `${diffDays}d ago`;
  return fmtShort(lastRunAt);
};

const getNextRunDisplay = (nextRunAt: string | undefined, fmtShort: (v: string) => string): string => {
  if (!nextRunAt) return "Pending";
  const date = new Date(nextRunAt);
  const now = new Date();
  const diffMs = date.getTime() - now.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return "Soon";
  if (diffMins < 60) return `In ${diffMins}m`;
  if (diffHours < 24) return `In ${diffHours}h`;
  if (diffDays < 30) return `In ${diffDays}d`;
  return fmtShort(nextRunAt);
};

export const ChecksumScheduleList: React.FC<ChecksumScheduleListProps> = ({
  schedules,
  isLoading,
  onEdit,
  onDelete,
  onTest,
  onToggle,
  runningScheduleId = null,
}) => {
  const { canWrite } = useAuth();
  const { formatDate, formatShortDate } = usePortalTimezone();
  const [expandedScheduleId, setExpandedScheduleId] = useState<string | number | null>(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(0);
  const [sortState, setSortState] = useState<SortState<ScheduleSortKey>>({
    key: "next_run_at",
    direction: "asc",
  });

  // Status badge colors
  const getStatusBadgeClass = (isEnabled: boolean) =>
    isEnabled ? "bg-green-100 text-green-800" : "bg-att-50 text-att-700";

  const getModuleTypeBadgeClass = (moduleType: string) =>
    moduleType === "synapse"
      ? "bg-att-100 text-att-800"
      : "bg-att-50 text-att-700";

  const filteredSchedules = useMemo(() => {
    if (!search) {
      return schedules;
    }

    const query = search.toLowerCase();
    return schedules.filter((schedule) => {
      return [
        schedule.name,
        schedule.description,
        schedule.module_type,
        schedule.system,
        schedule.workspace_name,
        schedule.cluster_name,
      ].some((value) => String(value ?? "").toLowerCase().includes(query));
    });
  }, [schedules, search]);

  const sortedSchedules = useMemo(() => {
    return [...filteredSchedules].sort((left, right) => {
      const direction = sortState.direction === "asc" ? 1 : -1;

      if (sortState.key === "last_run_at" || sortState.key === "next_run_at") {
        const leftValue = left[sortState.key] ? new Date(left[sortState.key] as string).getTime() : 0;
        const rightValue = right[sortState.key] ? new Date(right[sortState.key] as string).getTime() : 0;
        return (leftValue - rightValue) * direction;
      }

      if (sortState.key === "is_enabled") {
        return (Number(left.is_enabled) - Number(right.is_enabled)) * direction;
      }

      return String(left[sortState.key] ?? "")
        .localeCompare(String(right[sortState.key] ?? ""), undefined, { sensitivity: "base" }) * direction;
    });
  }, [filteredSchedules, sortState]);

  const totalPages = Math.max(1, Math.ceil(sortedSchedules.length / PAGE_SIZE));
  const pagedSchedules = useMemo(() => {
    return sortedSchedules.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);
  }, [page, sortedSchedules]);

  useEffect(() => {
    setPage(0);
  }, [search, sortState]);

  if (isLoading) {
    return (
      <div className="flex justify-center items-center h-48">
        <p className="text-gray-600">Loading schedules...</p>
      </div>
    );
  }

  if (schedules.length === 0) {
    return (
      <div className="text-center py-12 bg-gray-50 rounded-lg">
        <p className="text-gray-600 text-lg">No checksum schedules configured yet.</p>
        <p className="text-gray-500 text-sm mt-2">Create your first schedule to get started.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <span className={gridStyles.countBadge}>
            {filteredSchedules.length} of {schedules.length} schedules
          </span>
          <AutoRefreshIndicator />
        </div>
        <input
          type="text"
          placeholder="Search schedules…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className={gridStyles.toolbarInput}
        />
      </div>
      <div className="overflow-x-auto">
        <table className={gridStyles.table}>
          <thead className={gridStyles.head}>
            <tr>
              <th className={gridStyles.headerCell}><SortableHeader label="Name" active={sortState.key === "name"} direction={sortState.direction} onClick={() => setSortState((current) => nextSortState(current, "name"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Module" active={sortState.key === "module_type"} direction={sortState.direction} onClick={() => setSortState((current) => nextSortState(current, "module_type"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Schedule" active={sortState.key === "schedule_type"} direction={sortState.direction} onClick={() => setSortState((current) => nextSortState(current, "schedule_type"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Last Run" active={sortState.key === "last_run_at"} direction={sortState.direction} onClick={() => setSortState((current) => nextSortState(current, "last_run_at"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Next Run" active={sortState.key === "next_run_at"} direction={sortState.direction} onClick={() => setSortState((current) => nextSortState(current, "next_run_at"))} /></th>
              <th className={gridStyles.headerCell}><SortableHeader label="Status" active={sortState.key === "is_enabled"} direction={sortState.direction} onClick={() => setSortState((current) => nextSortState(current, "is_enabled"))} /></th>
              <th className={gridStyles.headerCellCenter}><span>Actions</span></th>
            </tr>
          </thead>
          <tbody>
          {pagedSchedules.map((schedule) => (
            <React.Fragment key={schedule.id}>
              <tr className="border-b border-att-100 transition-colors hover:bg-att-50/40">
                {/* Name */}
                <td className="px-6 py-4">
                  <div>
                    <p className="text-sm font-medium text-gray-900">{schedule.name}</p>
                    {schedule.description && (
                      <p className="text-xs text-gray-500 mt-1">{schedule.description.substring(0, 50)}...</p>
                    )}
                  </div>
                </td>

                {/* Module Type */}
                <td className="px-6 py-4">
                  <span className={`px-3 py-1 rounded-full text-xs font-semibold ${getModuleTypeBadgeClass(schedule.module_type)}`}>
                    {schedule.module_type.toUpperCase()}
                  </span>
                  {schedule.system && (
                    <p className="text-xs text-gray-500 mt-1">{schedule.system}</p>
                  )}
                </td>

                {/* Schedule Type */}
                <td className="px-6 py-4">
                  <div className="text-sm">
                    {schedule.schedule_type === "interval" ? (
                      <p>Every {schedule.interval_hours}h</p>
                    ) : (
                      <p className="font-mono text-xs">{schedule.cron_expression}</p>
                    )}
                    <p className="text-xs text-gray-500">{schedule.timezone}</p>
                  </div>
                </td>

                {/* Last Run */}
                <td className="px-6 py-4">
                  <p className="text-sm text-gray-700">{getLastRunDisplay(schedule.last_run_at, formatShortDate)}</p>
                  {schedule.last_run_at && (
                    <p className="text-xs text-gray-500">
                      {formatDate(schedule.last_run_at)}
                    </p>
                  )}
                </td>

                {/* Next Run */}
                <td className="px-6 py-4">
                  <p className="text-sm text-gray-700">{getNextRunDisplay(schedule.next_run_at, formatShortDate)}</p>
                  {schedule.next_run_at && (
                    <p className="text-xs text-gray-500">
                      {formatDate(schedule.next_run_at)}
                    </p>
                  )}
                </td>

                {/* Status Toggle */}
                <td className="px-6 py-4">
                  {canWrite ? (
                  <button
                    onClick={() => onToggle(schedule)}
                    className="relative inline-flex h-6 w-11 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-[#3f9bca] focus:ring-offset-1"
                    style={{ backgroundColor: schedule.is_enabled ? '#3f9bca' : '#d1d5db' }}
                    title={schedule.is_enabled ? 'Click to disable' : 'Click to enable'}
                  >
                    <span
                      className={`inline-block h-4 w-4 transform rounded-full bg-white shadow transition-transform ${
                        schedule.is_enabled ? 'translate-x-6' : 'translate-x-1'
                      }`}
                    />
                  </button>
                  ) : (
                    <span className={`px-3 py-1 rounded-full text-xs font-semibold ${schedule.is_enabled ? 'bg-green-100 text-green-800' : 'bg-gray-100 text-gray-600'}`}>
                      {schedule.is_enabled ? 'Enabled' : 'Disabled'}
                    </span>
                  )}
                </td>

                {/* Actions */}
                <td className="px-6 py-4">
                  <div className="flex justify-center gap-1">
                    <button
                      onClick={() => setExpandedScheduleId(expandedScheduleId === schedule.id ? null : schedule.id)}
                      className="rounded-lg p-2 text-gray-600 transition-colors hover:bg-gray-50"
                      title="View details"
                    >
                      <InfoIcon />
                    </button>
                    {canWrite && (
                    <button
                      onClick={() => onTest(schedule)}
                      disabled={runningScheduleId === schedule.id}
                      className="rounded-lg p-2 text-indigo-600 transition-colors hover:bg-indigo-50 disabled:cursor-not-allowed disabled:opacity-50"
                      title={runningScheduleId === schedule.id ? "Running schedule" : "Run schedule"}
                    >
                      {runningScheduleId === schedule.id ? (
                        <svg className="h-[18px] w-[18px] animate-spin" viewBox="0 0 24 24" fill="none">
                            <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                            <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                      ) : (
                        <PlayIcon />
                      )}
                    </button>
                    )}
                    {canWrite && (
                    <button
                      onClick={() => onEdit(schedule)}
                      className="rounded-lg p-2 text-blue-600 transition-colors hover:bg-blue-50"
                      title="Edit schedule"
                    >
                      <PencilIcon />
                    </button>
                    )}
                    {canWrite && (
                    <button
                      onClick={() => onDelete(schedule)}
                      className="rounded-lg p-2 text-red-600 transition-colors hover:bg-red-50"
                      title="Delete schedule"
                    >
                      <TrashIcon />
                    </button>
                    )}
                  </div>
                </td>
              </tr>

              {/* Expandable Details Row */}
              {expandedScheduleId === schedule.id && (
                <tr className="border-b border-att-100 bg-att-50">
                  <td colSpan={7} className="px-6 py-4">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
                      {/* Left Column */}
                      <div className="space-y-4">
                        <div>
                          <p className="text-xs font-semibold text-gray-600 uppercase">Schedule ID</p>
                          <p className="text-sm font-mono text-gray-800">{schedule.id}</p>
                        </div>

                        {schedule.module_type === "synapse" && schedule.workspace_name && (
                          <div>
                            <p className="text-xs font-semibold text-gray-600 uppercase">Workspace</p>
                            <p className="text-sm text-gray-800">{schedule.workspace_name}</p>
                          </div>
                        )}

                        {schedule.module_type === "aks" && schedule.cluster_name && (
                          <div>
                            <p className="text-xs font-semibold text-gray-600 uppercase">Cluster</p>
                            <p className="text-sm text-gray-800">{schedule.cluster_name}</p>
                          </div>
                        )}

                        {schedule.namespaces && schedule.namespaces.length > 0 && (
                          <div>
                            <p className="text-xs font-semibold text-gray-600 uppercase">Namespaces</p>
                            <div className="flex flex-wrap gap-2 mt-1">
                              {schedule.namespaces.map((ns, idx) => (
                                <span
                                  key={idx}
                                  className="rounded px-2 py-1 text-xs bg-att-100 text-att-800"
                                >
                                  {ns}
                                </span>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Right Column */}
                      <div className="space-y-4">
                        {schedule.notification_emails && schedule.notification_emails.length > 0 && (
                          <div>
                            <p className="text-xs font-semibold text-gray-600 uppercase">Notifications</p>
                            <div className="space-y-1 mt-1">
                              {schedule.notification_emails.map((email, idx) => (
                                <p key={idx} className="text-sm text-gray-800">{email}</p>
                              ))}
                            </div>
                          </div>
                        )}

                        {schedule.created_by && (
                          <div>
                            <p className="text-xs font-semibold text-gray-600 uppercase">Created By</p>
                            <p className="text-sm text-gray-800">{schedule.created_by}</p>
                          </div>
                        )}

                        {schedule.created_at && (
                          <div>
                            <p className="text-xs font-semibold text-gray-600 uppercase">Created At</p>
                            <p className="text-sm text-gray-800">
                              {formatDate(schedule.created_at)}
                            </p>
                          </div>
                        )}
                      </div>
                    </div>
                  </td>
                </tr>
              )}
            </React.Fragment>
          ))}
          {pagedSchedules.length === 0 && (
            <tr>
              <td colSpan={7} className="px-6 py-8 text-center text-sm text-gray-400">
                No schedules match the current search.
              </td>
            </tr>
          )}
          </tbody>
        </table>
      </div>
      {totalPages > 1 && (
        <div className={gridStyles.pager}>
          <span className="text-gray-600">
            Showing {page * PAGE_SIZE + 1}–{Math.min((page + 1) * PAGE_SIZE, sortedSchedules.length)} of {sortedSchedules.length} schedules
          </span>
          <div className="flex items-center gap-2">
            <button onClick={() => setPage((currentPage) => Math.max(0, currentPage - 1))} disabled={page === 0} className={gridStyles.pagerButton}>Previous</button>
            <span className="text-gray-700">Page {page + 1} of {totalPages}</span>
            <button onClick={() => setPage((currentPage) => Math.min(totalPages - 1, currentPage + 1))} disabled={page >= totalPages - 1} className={gridStyles.pagerButton}>Next</button>
          </div>
        </div>
      )}
    </div>
  );
};
