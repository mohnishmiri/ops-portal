/**
 * Environment Scheduler: read-only users see schedules and sequences but get
 * no control that creates, edits, runs, or deletes them.
 */

import { render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";
import ScheduleManagement from "./ScheduleManagement";
import SequenceDesigner from "./SequenceDesigner";

const schedule = {
  id: 1, job_name: "nightly-scale-down", cluster_id: "c1", namespace: "apps", operation: "scale_down",
  replica_count: 0, schedule_type: "daily", cron_expression: null, timezone: "UTC", start_date: null,
  end_date: null, is_enabled: true, retry_count: 0, failure_notification: null, sequence_id: null,
  created_by: "u1", created_by_email: null, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
  last_run_at: null, next_run_at: null, last_run_status: null,
} as any;

const sequence = {
  id: 7, name: "perf-startup", sequence_type: "startup", namespace: "apps", cluster_id: "c1",
  steps: [], rollback_on_failure: true, created_at: "2026-10-01T00:00:00Z",
} as any;

function renderSchedules(canWrite: boolean) {
  render(
    <ScheduleManagement
      canWrite={canWrite}
      schedules={[schedule]}
      sequences={[]}
      clusterId="c1"
      namespaces={["apps"]}
      onCreate={vi.fn()}
      onUpdate={vi.fn()}
      onDelete={vi.fn()}
      onRunNow={vi.fn()}
      isLoading={false}
    />
  );
}

function renderSequences(canWrite: boolean) {
  render(
    <SequenceDesigner
      canWrite={canWrite}
      sequences={[sequence]}
      deployments={[]}
      clusterId="c1"
      namespace="apps"
      onCreate={vi.fn()}
      onUpdate={vi.fn()}
      onDelete={vi.fn()}
      onExecuteStart={vi.fn()}
      onExecuteStop={vi.fn()}
      isLoading={false}
    />
  );
}

describe("ScheduleManagement role gating", () => {
  it("shows a read-only user the schedule without any controls", () => {
    renderSchedules(false);
    expect(screen.getByText("nightly-scale-down")).toBeTruthy();
    // A status badge replaces the enable/disable toggle ("Enabled" is also the column header).
    expect(screen.getAllByText("Enabled").some((el) => el.tagName === "SPAN" && el.className.includes("rounded-full"))).toBe(true);
    expect(screen.queryByRole("button", { name: /Create Schedule/ })).toBeNull();
    for (const title of ["Run Now", "Edit Schedule", "Delete Schedule"]) expect(screen.queryByTitle(title)).toBeNull();
  });

  it("gives a write user every schedule control", () => {
    renderSchedules(true);
    expect(screen.getByRole("button", { name: /Create Schedule/ })).toBeTruthy();
    for (const title of ["Run Now", "Edit Schedule", "Delete Schedule"]) expect(screen.getByTitle(title)).toBeTruthy();
  });
});

describe("SequenceDesigner role gating", () => {
  it("shows a read-only user the sequence without any controls", () => {
    renderSequences(false);
    expect(screen.getByText("perf-startup")).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Create Sequence/ })).toBeNull();
    for (const title of ["Run Startup Sequence", "Edit Sequence", "Delete Sequence"]) expect(screen.queryByTitle(title)).toBeNull();
  });

  it("gives a write user every sequence control", () => {
    renderSequences(true);
    expect(screen.getByRole("button", { name: /Create Sequence/ })).toBeTruthy();
    for (const title of ["Run Startup Sequence", "Edit Sequence", "Delete Sequence"]) expect(screen.getByTitle(title)).toBeTruthy();
  });
});
