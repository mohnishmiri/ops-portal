/**
 * Replica counts up to 1000, and force stopping a running sequence from the
 * live panel or History (optionally with rollback).
 */

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { describe, expect, it, vi } from "vitest";
import ExecutionHistoryGrid from "./ExecutionHistory";
import SequenceDesigner from "./SequenceDesigner";
import { SequenceExecutionPanel } from "./SequenceRunPanels";

const sequence = {
  id: 7, name: "RTL", sequence_type: "startup", namespace: "com-att-attcc-prod", cluster_id: "c1",
  rollback_on_failure: true, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
  created_by: "u1", created_by_email: null,
  steps: [{ order: 1, deployment_name: "calcaggregationprocessor-rtl", replicas: 1, wait_condition: "pods_ready", timeout_seconds: 600, retry_count: 3, on_failure: "abort" }],
} as any;

function running(overrides: Record<string, unknown> = {}) {
  return {
    id: 88, execution_type: "sequence", cluster_id: "c1", namespace: "com-att-attcc-prod", operation: "sequence_startup",
    sequence_name: "RTL", sequence_id: 7, status: "running", total_deployments: 3, completed_count: 1, failed_count: 0,
    skipped_count: 0, replica_count: 1, schedule_id: null, initiated_by: "u1", initiated_by_email: "starter@att.com",
    started_at: new Date().toISOString(), completed_at: null, duration_seconds: null, error_message: null,
    cancel_requested_at: null, cancel_requested_by: null, cancel_rollback: false,
    step_details: [
      { step: 1, deployment: "compadmin", current_replicas: 30, target_replicas: 0, status: "completed", duration_seconds: 40 },
      { step: 2, deployment: "calcaggregationprocessor-rtl", current_replicas: 0, target_replicas: 800, status: "running", started_at: new Date().toISOString(), wait_condition: "pods_ready" },
      { step: 3, deployment: "reprocess-rtl", target_replicas: 1, status: "pending" },
    ],
    ...overrides,
  } as any;
}

describe("replica counts", () => {
  it("accepts up to 1000 pods per step and caps anything above", async () => {
    const user = userEvent.setup();
    const onUpdate = vi.fn().mockResolvedValue(undefined);
    render(
      <SequenceDesigner
        canWrite sequences={[sequence]} deployments={[]} clusterId="c1" namespace="com-att-attcc-prod"
        onCreate={vi.fn()} onUpdate={onUpdate} onDelete={vi.fn()} onExecuteStart={vi.fn()} onExecuteStop={vi.fn()} isLoading={false}
      />,
    );
    await user.click(screen.getByTitle("Edit Sequence"));
    const replicas = screen.getByLabelText("Replicas for step 1") as HTMLInputElement;
    await user.clear(replicas);
    await user.type(replicas, "750");
    expect(replicas.value).toBe("750");
    await user.clear(replicas);
    await user.type(replicas, "1500"); // the field keeps four digits: 1500
    await user.tab();
    expect(replicas.value).toBe("1000");
    await user.click(screen.getByRole("button", { name: "Update Sequence" }));
    expect(onUpdate).toHaveBeenCalledWith(7, expect.objectContaining({ steps: [expect.objectContaining({ replicas: 1000 })] }));
  });
});

describe("force stop", () => {
  it("stops from the live panel, with rollback when chosen", async () => {
    const user = userEvent.setup();
    const onForceStop = vi.fn().mockResolvedValue(undefined);
    render(<SequenceExecutionPanel execution={running()} onClose={vi.fn()} onForceStop={onForceStop} />);

    await user.click(screen.getByRole("button", { name: /Force stop/ }));
    const dialog = screen.getByRole("dialog", { name: "Force stop this run?" });
    expect(within(dialog).getByText(/step 2 of 3/)).toBeTruthy();

    await user.click(within(dialog).getByLabelText(/Stop and roll back 2 scaled steps/));
    const undo = within(dialog).getByLabelText("Deployments to roll back");
    expect(within(undo).getByText("calcaggregationprocessor-rtl")).toBeTruthy();
    expect(within(undo).getByText("compadmin")).toBeTruthy();

    await user.click(within(dialog).getByRole("button", { name: "Force stop and roll back" }));
    expect(onForceStop).toHaveBeenCalledWith(true);
  });

  it("defaults to stopping without rollback and shows the server's refusal", async () => {
    const user = userEvent.setup();
    const onForceStop = vi.fn().mockRejectedValue(new Error("Execution #88 has already finished (completed)."));
    render(<SequenceExecutionPanel execution={running()} onClose={vi.fn()} onForceStop={onForceStop} />);
    await user.click(screen.getByRole("button", { name: /Force stop/ }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Force stop" }));
    expect(onForceStop).toHaveBeenCalledWith(false);
    expect((await screen.findByRole("alert")).textContent).toContain("already finished");
  });

  it("shows that a stop is under way", () => {
    render(
      <SequenceExecutionPanel
        execution={running({ cancel_requested_at: new Date().toISOString(), cancel_requested_by: "oncall@att.com", cancel_rollback: true })}
        onClose={vi.fn()}
        onForceStop={vi.fn()}
      />,
    );
    expect((screen.getByRole("button", { name: /Stopping/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByRole("status").textContent).toContain("Stop requested by oncall@att.com");
    expect(screen.getByRole("status").textContent).toContain("(with rollback)");
  });

  it("is not offered to read-only users", () => {
    render(<SequenceExecutionPanel execution={running()} onClose={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Force stop/ })).toBeNull();
  });

  it("can be stopped from History, and a stopped run reads Stopped", async () => {
    const user = userEvent.setup();
    const onForceStop = vi.fn().mockResolvedValue(undefined);
    const stopped = running({
      id: 87, status: "cancelled", started_at: "2026-10-12T05:00:00Z", completed_at: "2026-10-12T05:04:00Z", duration_seconds: 240,
      error_message: "Stopped by oncall@att.com at step 2 (calcaggregationprocessor-rtl). Deployments were left at their current replica counts.",
      cancel_requested_at: "2026-10-12T05:03:58Z", cancel_requested_by: "oncall@att.com",
    });
    render(<ExecutionHistoryGrid history={[running(), stopped]} isLoading={false} onForceStop={onForceStop} />);

    // The running one opens on its own.
    await user.click(await screen.findByRole("button", { name: /Force stop/ }));
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Force stop" }));
    expect(onForceStop).toHaveBeenCalledWith(88, false);
    expect(screen.getAllByText("Stopped").length).toBeGreaterThan(0);
  });
});
