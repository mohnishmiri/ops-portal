/**
 * Schedules tab: Run Now of a sequence-linked schedule hands off to the live
 * execution panel instead of waiting on the request.
 */

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { describe, expect, it, vi } from "vitest";
import ScheduleManagement from "./ScheduleManagement";

const schedule = {
  id: 1, job_name: "weekday-start", cluster_id: "c1", namespace: "apps", operation: "scale_up",
  replica_count: 1, schedule_type: "cron", cron_expression: "0 8 * * 1-5", timezone: "UTC", start_date: null,
  end_date: null, is_enabled: true, retry_count: 0, failure_notification: null, sequence_id: 7,
  created_by: "u1", created_by_email: null, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
  last_run_at: "2026-10-07T08:00:00Z", next_run_at: null, last_run_status: "running",
} as any;

const runningExecution = {
  id: 52, execution_type: "scheduled", cluster_id: "c1", namespace: "apps", operation: "sequence_startup",
  sequence_name: "SCAL-Up-RTL", schedule_name: "weekday-start", sequence_id: 7, schedule_id: 1, status: "running",
  total_deployments: 1, completed_count: 0, failed_count: 0, skipped_count: 0, replica_count: 1,
  initiated_by: "u1", initiated_by_email: "ops@example.com", started_at: new Date().toISOString(),
  completed_at: null, duration_seconds: null, error_message: null,
  step_details: [{ step: 1, deployment: "api", current_replicas: 0, target_replicas: 2, status: "running", started_at: new Date().toISOString(), wait_condition: "pods_ready" }],
} as any;

function renderSchedules(overrides: Record<string, unknown> = {}) {
  const props = {
    canWrite: true,
    schedules: [schedule],
    sequences: [],
    clusterId: "c1",
    namespaces: ["apps"],
    onCreate: vi.fn(),
    onUpdate: vi.fn(),
    onDelete: vi.fn(),
    onRunNow: vi.fn().mockResolvedValue({ execution_id: 52, status: "running", total_deployments: 1, completed: 0, failed: 0, skipped: 0, details: [] }),
    isLoading: false,
    ...overrides,
  };
  render(<ScheduleManagement {...(props as any)} />);
  return props;
}

describe("ScheduleManagement Run Now", () => {
  it("drops its own wait panel when the run continues on the server", async () => {
    const user = userEvent.setup();
    const props = renderSchedules();
    await user.click(screen.getByTitle("Run Now"));
    expect(props.onRunNow).toHaveBeenCalledWith(1);
    expect(screen.queryByText("weekday-start — apps")).toBeNull();
  });

  it("shows the live sequence panel and a readable last-run status", () => {
    renderSchedules({ trackedExecution: runningExecution });
    expect(screen.getByText(/Step 1 of 1:/)).toBeTruthy();
    expect(screen.getAllByText("Running").length).toBeGreaterThan(0);
  });
});
