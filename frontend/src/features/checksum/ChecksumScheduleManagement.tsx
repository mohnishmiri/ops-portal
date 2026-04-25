/**
 * Checksum Schedule Management Component
 * 
 * Main component for managing checksum schedules.
 * Combines form for creating/editing and list for viewing schedules.
 */

import React, { useState } from "react";
import { useAuth } from "../../contexts/AuthContext";
import { ChecksumScheduleForm } from "./ChecksumScheduleForm";
import { ChecksumScheduleList } from "./ChecksumScheduleList";
import { MetricCard } from "../../components/MetricCard";
import {
  useListChecksumSchedules,
  useCreateChecksumSchedule,
  useUpdateChecksumSchedule,
  useDeleteChecksumSchedule,
  useTestChecksumSchedule,
  useToggleChecksumSchedule,
  ChecksumScheduleCreateRequest,
  ChecksumScheduleDetail,
} from "../../services/checksumScheduleApi";

const Icons = {
  calendar: (
    <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="18" rx="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  ),
  enabled: (
    <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M9 12l2 2 4-4" />
      <circle cx="12" cy="12" r="9" />
    </svg>
  ),
  synapse: (
    <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M5 3v4M3 5h4M6 17v4M4 19h4M13 3l4 4M17 3l-4 4M14 17l4 4M17 17l-4 4M12 8v8M8 12h8" />
    </svg>
  ),
  aks: (
    <svg className="h-6 w-6" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 2L2 7l10 5 10-5-10-5z" />
      <path d="M2 17l10 5 10-5" />
      <path d="M2 12l10 5 10-5" />
    </svg>
  ),
};

interface ToastState {
  message: string;
  type: "success" | "error" | "info";
}

interface ChecksumScheduleManagementProps {
  onShowToast?: (message: string, type: "success" | "error" | "info") => void;
}

function getApiErrorMessage(error: unknown, fallback: string): string {
  if (!error || typeof error !== "object") {
    return fallback;
  }

  const maybeAxiosError = error as {
    response?: { data?: { detail?: string; message?: string } };
    message?: string;
  };

  return (
    maybeAxiosError.response?.data?.detail ||
    maybeAxiosError.response?.data?.message ||
    maybeAxiosError.message ||
    fallback
  );
}

export const ChecksumScheduleManagement: React.FC<ChecksumScheduleManagementProps> = ({
  onShowToast,
}) => {
  const { canWrite } = useAuth();
  const [showForm, setShowForm] = useState(false);
  const [editingSchedule, setEditingSchedule] = useState<ChecksumScheduleDetail | null>(null);
  const [selectedScheduleForDelete, setSelectedScheduleForDelete] = useState<ChecksumScheduleDetail | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [runningScheduleId, setRunningScheduleId] = useState<string | number | null>(null);

  // Queries — pause auto-polling while the form is open so refetches don't reset form state
  const {
    data: listData,
    isLoading: isLoadingList,
    isFetching,
    isError: isListError,
    error: listError,
    refetch,
  } = useListChecksumSchedules({
    refetchInterval: showForm ? false : 30_000,
  });

  // Mutations
  const createMutation = useCreateChecksumSchedule({
    onSuccess: () => {
      showToast("Schedule created successfully", "success");
      setShowForm(false);
      setEditingSchedule(null);
      refetch();
    },
    onError: (error: any) => {
      const message = error?.response?.data?.detail || "Failed to create schedule";
      showToast(message, "error");
    },
  });

  const updateMutation = useUpdateChecksumSchedule({
    onSuccess: () => {
      showToast("Schedule updated successfully", "success");
      setShowForm(false);
      setEditingSchedule(null);
      refetch();
    },
    onError: (error: any) => {
      const message = error?.response?.data?.detail || "Failed to update schedule";
      showToast(message, "error");
    },
  });

  const deleteMutation = useDeleteChecksumSchedule({
    onSuccess: () => {
      showToast("Schedule deleted successfully", "success");
      setShowDeleteConfirm(false);
      setSelectedScheduleForDelete(null);
      refetch();
    },
    onError: (error: any) => {
      const message = error?.response?.data?.detail || "Failed to delete schedule";
      showToast(message, "error");
    },
  });

  const testMutation = useTestChecksumSchedule({
    onSuccess: (data) => {
      showToast(data.message || "Schedule executed successfully", "success");
      refetch();
    },
    onError: (error: any) => {
      const message = error?.response?.data?.detail || "Failed to test schedule";
      showToast(message, "error");
    },
  });

  const toggleMutation = useToggleChecksumSchedule({
    onSuccess: (data) => {
      showToast(data.message || "Schedule toggled", "success");
      refetch();
    },
    onError: (error: any) => {
      const message = error?.response?.data?.detail || "Failed to toggle schedule";
      showToast(message, "error");
    },
  });

  // Helper function
  const showToast = (message: string, type: "success" | "error" | "info") => {
    if (onShowToast) {
      onShowToast(message, type);
    }
  };

  // Handlers
  const handleCreateNew = () => {
    setEditingSchedule(null);
    setShowForm(true);
  };

  const handleEdit = (schedule: ChecksumScheduleDetail) => {
    setEditingSchedule(schedule);
    setShowForm(true);
  };

  const handleCancelForm = () => {
    setShowForm(false);
    setEditingSchedule(null);
  };

  const handleFormSubmit = async (data: ChecksumScheduleCreateRequest) => {
    try {
      if (editingSchedule) {
        await updateMutation.mutateAsync({
          scheduleId: String(editingSchedule.id),
          data,
        });
      } else {
        await createMutation.mutateAsync(data);
      }
    } catch (error) {
      console.error("Form submission error:", error);
    }
  };

  const handleDelete = (schedule: ChecksumScheduleDetail) => {
    setSelectedScheduleForDelete(schedule);
    setShowDeleteConfirm(true);
  };

  const handleConfirmDelete = async () => {
    if (selectedScheduleForDelete) {
      await deleteMutation.mutateAsync(String(selectedScheduleForDelete.id));
    }
  };

  const handleTest = async (schedule: ChecksumScheduleDetail) => {
    setRunningScheduleId(schedule.id);
    try {
      await testMutation.mutateAsync(String(schedule.id));
    } finally {
      setRunningScheduleId(null);
    }
  };

  const handleToggle = async (schedule: ChecksumScheduleDetail) => {
    await toggleMutation.mutateAsync(String(schedule.id));
  };

  const schedules = isListError ? [] : listData?.schedules || [];
  const isFormLoading = createMutation.isPending || updateMutation.isPending;
  const listErrorMessage = isListError
    ? getApiErrorMessage(listError, "Failed to load checksum schedules.")
    : null;
  const statsUnavailableValue: number | string = isListError ? "N/A" : schedules.length;
  const enabledValue: number | string = isListError ? "N/A" : schedules.filter(s => s.is_enabled).length;
  const synapseValue: number | string = isListError ? "N/A" : schedules.filter(s => s.module_type === "synapse").length;
  const aksValue: number | string = isListError ? "N/A" : schedules.filter(s => s.module_type === "aks").length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center">
        <div>
          <h2 className="text-2xl font-bold text-gray-900">Checksum Schedule Management</h2>
          <p className="text-gray-600 mt-1">Manage automated checksum verification for Synapse and AKS environments</p>
        </div>
        {canWrite && !showForm && (
          <button
            onClick={handleCreateNew}
            className="flex items-center gap-2 rounded-lg bg-att-400 px-4 py-2 text-white transition-colors hover:bg-att-500"
          >
            <span className="text-lg">+</span> New Schedule
          </button>
        )}
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <StatsCard
          title="Total Schedules"
          value={statsUnavailableValue}
          icon={Icons.calendar}
          subtitle={isListError ? "Unable to load" : undefined}
        />
        <StatsCard
          title="Enabled"
          value={enabledValue}
          icon={Icons.enabled}
          subtitle={isListError ? "Request failed" : undefined}
        />
        <StatsCard
          title="Synapse"
          value={synapseValue}
          icon={Icons.synapse}
          subtitle={isListError ? "Request failed" : undefined}
        />
        <StatsCard
          title="AKS"
          value={aksValue}
          icon={Icons.aks}
          subtitle={isListError ? "Request failed" : undefined}
        />
      </div>

      {listErrorMessage && (
        <div className="rounded-2xl border border-red-200 bg-red-50 px-5 py-4 text-red-900 shadow-sm">
          <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div className="space-y-1">
              <p className="text-sm font-semibold uppercase tracking-[0.16em] text-red-700">
                Schedule Data Unavailable
              </p>
              <p className="text-sm text-red-800">{listErrorMessage}</p>
            </div>
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="inline-flex items-center justify-center rounded-lg border border-red-200 bg-white px-4 py-2 text-sm font-medium text-red-700 transition-colors hover:bg-red-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              {isFetching ? "Retrying..." : "Retry"}
            </button>
          </div>
        </div>
      )}

      {/* Form Section */}
      {canWrite && showForm && (
        <div className="bg-blue-50 border border-blue-200 rounded-xl p-6">
          <h3 className="text-lg font-semibold text-gray-900 mb-4">
            {editingSchedule ? "Edit Schedule" : "Create New Schedule"}
          </h3>
          <ChecksumScheduleForm
            schedule={editingSchedule}
            onSubmit={handleFormSubmit}
            onCancel={handleCancelForm}
            isLoading={isFormLoading}
          />
        </div>
      )}

      {/* List Section */}
      {!showForm && (
        <div className="bg-white rounded-xl shadow-sm border border-gray-100">
          <div className="p-6 border-b border-gray-200">
            <div className="flex justify-between items-center">
              <h3 className="text-lg font-semibold text-gray-900">
                {isListError ? "Schedules unavailable" : `Schedules (${schedules.length})`}
              </h3>
              <button
                onClick={() => refetch()}
                disabled={isFetching}
                className="flex items-center gap-2 rounded-lg bg-att-50 px-3 py-2 text-sm text-att-700 transition-colors hover:bg-att-100 disabled:opacity-50"
              >
                {isFetching ? "Refreshing..." : "Refresh"}
              </button>
            </div>
          </div>
          <div className="p-6">
            {isListError ? (
              <div className="rounded-2xl border border-att-100 bg-att-50/60 px-6 py-10 text-center">
                <p className="text-base font-semibold text-slate-900">The schedules request did not complete.</p>
                <p className="mt-2 text-sm text-slate-600">Refresh the page or retry once the API call succeeds.</p>
              </div>
            ) : (
              <ChecksumScheduleList
                schedules={schedules}
                isLoading={isLoadingList}
                onEdit={handleEdit}
                onDelete={handleDelete}
                onTest={handleTest}
                onToggle={handleToggle}
                runningScheduleId={runningScheduleId}
              />
            )}
          </div>
        </div>
      )}

      {/* Delete Confirmation Modal */}
      {showDeleteConfirm && selectedScheduleForDelete && (
        <div className="fixed inset-0 bg-black bg-opacity-50 flex items-center justify-center z-50 rounded-lg">
          <div className="bg-white rounded-lg shadow-xl p-6 max-w-md w-full mx-4">
            <h3 className="text-lg font-semibold text-gray-900 mb-4">Confirm Deletion</h3>
            <p className="text-gray-600 mb-6">
              Are you sure you want to delete the schedule <span className="font-semibold">"{selectedScheduleForDelete.name}"</span>? This action cannot be undone.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => {
                  setShowDeleteConfirm(false);
                  setSelectedScheduleForDelete(null);
                }}
                disabled={deleteMutation.isPending}
                className="px-4 py-2 border border-gray-300 rounded-lg text-gray-700 hover:bg-gray-50 disabled:opacity-50"
              >
                Cancel
              </button>
              <button
                onClick={handleConfirmDelete}
                disabled={deleteMutation.isPending}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-700 disabled:opacity-50"
              >
                {deleteMutation.isPending ? "Deleting..." : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

// Stats Card Component
interface StatsCardProps {
  title: string;
  value: number | string;
  icon: React.ReactNode;
  subtitle?: React.ReactNode;
}

const StatsCard: React.FC<StatsCardProps> = ({ title, value, icon, subtitle }) => (
  <MetricCard
    title={title}
    value={value}
    icon={icon}
    subtitle={subtitle}
    tone={
      title === "Enabled"
        ? "green"
        : title === "Synapse"
          ? "purple"
          : title === "AKS"
            ? "blue"
            : "att"
    }
  />
);
