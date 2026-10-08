/**
 * Run-summary email settings (sequence builder, schedule form, scale dialog)
 * and the schedule form's timing checks and "Next runs" preview.
 */

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../services/environmentApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../services/environmentApi")>()),
  fetchSchedulePreview: vi.fn(),
}));

import { fetchSchedulePreview } from "../../services/environmentApi";
import EnvironmentScaleDialog from "./EnvironmentScaleDialog";
import ScheduleManagement from "./ScheduleManagement";
import SequenceDesigner from "./SequenceDesigner";

const sequence = {
  id: 7, name: "SCAL-Up-UI", sequence_type: "startup", namespace: "apps", cluster_id: "c1",
  rollback_on_failure: false, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
  created_by: "u1", created_by_email: null, notification_emails: "ops-dl@att.com", notify_on: "always",
  steps: [{ order: 1, deployment_name: "api", replicas: 2, wait_condition: "pods_ready", timeout_seconds: 600, retry_count: 3, on_failure: "abort" }],
} as any;

describe("sequence notification settings", () => {
  function renderDesigner(onUpdate = vi.fn().mockResolvedValue(undefined)) {
    render(
      <SequenceDesigner
        canWrite sequences={[sequence]} deployments={[{ name: "api", namespace: "apps", replicas: 0, ready_replicas: 0 }]}
        clusterId="c1" namespace="apps" onCreate={vi.fn()} onUpdate={onUpdate} onDelete={vi.fn()}
        onExecuteStart={vi.fn()} onExecuteStop={vi.fn()} isLoading={false}
      />,
    );
    return onUpdate;
  }

  it("loads, changes and saves who is emailed and when", async () => {
    const user = userEvent.setup();
    const onUpdate = renderDesigner();
    await user.click(screen.getByTitle("Edit Sequence"));

    const emails = screen.getByLabelText(/Also send to/) as HTMLInputElement;
    expect(emails.value).toBe("ops-dl@att.com");
    await user.selectOptions(screen.getByLabelText("Email run summary"), "failure");
    await user.type(emails, ", oncall@att.com");
    await user.click(screen.getByRole("button", { name: "Update Sequence" }));

    expect(onUpdate).toHaveBeenCalledWith(7, expect.objectContaining({
      notify_on: "failure", notification_emails: "ops-dl@att.com, oncall@att.com",
    }));
  });

  it("won't save an invalid address", async () => {
    const user = userEvent.setup();
    const onUpdate = renderDesigner();
    await user.click(screen.getByTitle("Edit Sequence"));
    await user.type(screen.getByLabelText(/Also send to/), " not-an-email");
    expect(screen.getByText("Not a valid email address: not-an-email")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Update Sequence" }));
    expect(onUpdate).not.toHaveBeenCalled();
  });
});

describe("schedule form", () => {
  beforeEach(() => {
    vi.mocked(fetchSchedulePreview).mockReset();
    vi.mocked(fetchSchedulePreview).mockResolvedValue({
      timezone: "US/Central",
      start_utc: "2026-10-09T13:00:00Z",
      runs: [
        { utc: "2026-10-09T13:00:00Z", local: "Fri Oct 09, 2026 08:00 AM CDT" },
        { utc: "2026-10-10T13:00:00Z", local: "Sat Oct 10, 2026 08:00 AM CDT" },
      ],
    });
  });

  const schedule = {
    id: 3, job_name: "Morning start", cluster_id: "c1", namespace: "apps", operation: "scale_up", replica_count: 1,
    schedule_type: "daily", cron_expression: null, timezone: "US/Central", start_date: "2026-10-09T08:00:00",
    end_date: "2026-12-31T00:00:00", is_enabled: true, retry_count: 3, failure_notification: "ops@att.com",
    notify_on: "always", sequence_id: null, created_by: "u1", created_by_email: "owner@att.com",
    created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z", last_run_at: null,
    next_run_at: "2026-10-09T08:00:00", next_run_at_utc: "2026-10-09T13:00:00Z", schedule_description: "Daily at 08:00 (US/Central)",
    last_run_status: null,
  } as any;

  function renderSchedules(overrides: Record<string, unknown> = {}) {
    const props = {
      canWrite: true, schedules: [schedule], sequences: [], clusterId: "c1", namespaces: ["apps"],
      onCreate: vi.fn().mockResolvedValue(undefined), onUpdate: vi.fn().mockResolvedValue(undefined),
      onDelete: vi.fn(), onRunNow: vi.fn(), isLoading: false, ...overrides,
    };
    render(<ScheduleManagement {...(props as any)} />);
    return props;
  }

  it("shows the schedule in plain words with its timezone", () => {
    renderSchedules();
    expect(screen.getByText("Daily at 08:00 (US/Central)")).toBeTruthy();
    expect(screen.getAllByText("US/Central").length).toBeGreaterThan(0);
  });

  it("previews the next runs and requires a start time for a daily schedule", async () => {
    const user = userEvent.setup();
    const props = renderSchedules();
    await user.click(screen.getByRole("button", { name: "+ Create Schedule" }));
    await user.type(screen.getByLabelText("Job Name"), "Evening stop");
    await user.click(screen.getByRole("button", { name: "Create Schedule" }));
    expect(screen.getByRole("alert").textContent).toContain("Choose the start date and time");
    expect(props.onCreate).not.toHaveBeenCalled();

    await user.type(screen.getByLabelText(/^Start/), "2026-10-09T08:00");
    expect(await screen.findByText("Fri Oct 09, 2026 08:00 AM CDT")).toBeTruthy();
    await user.click(screen.getByRole("button", { name: "Create Schedule" }));
    expect(props.onCreate).toHaveBeenCalledWith(expect.objectContaining({
      job_name: "Evening stop", schedule_type: "daily", start_date: "2026-10-09T08:00", notify_on: "always",
    }));
  });

  it("clears the end date and recipients when they are emptied on edit", async () => {
    const user = userEvent.setup();
    const props = renderSchedules();
    await user.click(screen.getByTitle("Edit Schedule"));
    await user.clear(screen.getByLabelText(/^End/));
    await user.clear(screen.getByLabelText(/Also send to/));
    await waitFor(() => expect(fetchSchedulePreview).toHaveBeenCalled());
    await user.click(screen.getByRole("button", { name: "Update Schedule" }));
    expect(props.onUpdate).toHaveBeenCalledWith(3, expect.objectContaining({
      end_date: null, failure_notification: null, sequence_id: null,
    }));
  });

  it("shows why the server refused to save", async () => {
    const user = userEvent.setup();
    renderSchedules({ onUpdate: vi.fn().mockRejectedValue({ response: { data: { detail: "The start time of a one-time schedule is in the past" } } }) });
    await user.click(screen.getByTitle("Edit Schedule"));
    await waitFor(() => expect(fetchSchedulePreview).toHaveBeenCalled());
    await user.click(screen.getByRole("button", { name: "Update Schedule" }));
    expect((await screen.findByRole("alert")).textContent).toContain("in the past");
  });
});

describe("manual scale dialog", () => {
  it("asks for a summary email by default and passes extra recipients", async () => {
    const user = userEvent.setup();
    const onScale = vi.fn().mockResolvedValue({ execution_id: 1, status: "completed", total_deployments: 1, completed: 1, failed: 0, skipped: 0, details: [] });
    render(
      <EnvironmentScaleDialog
        open onClose={vi.fn()} clusterId="c1" namespace="apps" namespaces={["apps"]} onNamespaceChange={vi.fn()}
        deployments={[{ name: "api", namespace: "apps", replicas: 0, ready_replicas: 0 } as any]}
        onRefresh={vi.fn()} isRefreshing={false} isLoadingDeployments={false} onScale={onScale} isScaling={false}
      />,
    );
    expect((screen.getByLabelText("Email me a summary when it finishes") as HTMLInputElement).checked).toBe(true);
    await user.type(screen.getByLabelText("Also email the summary to"), "ops@att.com");
    const scaleButton = screen.getAllByRole("button").find((b) => /^Scale Up \(/.test(b.textContent ?? ""))!;
    await user.click(scaleButton);
    expect(onScale).toHaveBeenCalledWith(expect.objectContaining({ notify: true, notification_emails: "ops@att.com" }));
    expect(within(document.body).queryByText(/Not a valid email/)).toBeNull();
  });
});
