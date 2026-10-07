/**
 * Sequence Designer behaviour production support relies on: visible step
 * names while reordering, replica counts that can be retyped, repeated
 * deployments, confirmed runs, guarded deletes, and readable History status.
 */

import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { describe, expect, it, vi } from "vitest";
import SequenceDesigner from "./SequenceDesigner";
import ExecutionHistoryGrid from "./ExecutionHistory";

const deployments = [
  { name: "attccleadsauditlog", namespace: "apps", replicas: 1, ready_replicas: 1 },
  { name: "attccleadscomp", namespace: "apps", replicas: 0, ready_replicas: 0 },
];

const savedSequence = {
  id: 7, name: "SCAL-Up-RTL", sequence_type: "startup", namespace: "apps", cluster_id: "c1",
  rollback_on_failure: true, created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z",
  created_by: "u1", created_by_email: null,
  steps: [
    { order: 1, deployment_name: "attccleadscomp", replicas: 1, wait_condition: "pods_ready", timeout_seconds: 600, retry_count: 3, on_failure: "abort" },
    { order: 2, deployment_name: "attccleadsauditlog", replicas: 2, wait_condition: "pods_ready", timeout_seconds: 600, retry_count: 3, on_failure: "abort" },
  ],
} as any;

function renderDesigner(overrides: Record<string, unknown> = {}) {
  const props = {
    canWrite: true,
    sequences: [savedSequence],
    deployments,
    clusterId: "c1",
    namespace: "apps",
    onCreate: vi.fn().mockResolvedValue(undefined),
    onUpdate: vi.fn().mockResolvedValue(undefined),
    onDelete: vi.fn().mockResolvedValue(undefined),
    onExecuteStart: vi.fn().mockResolvedValue({ execution_id: 1, status: "running" }),
    onExecuteStop: vi.fn().mockResolvedValue({ execution_id: 1, status: "running" }),
    isLoading: false,
    ...overrides,
  };
  render(<SequenceDesigner {...(props as any)} />);
  return props;
}

const stepCards = () => screen.getAllByTestId("sequence-step");
const availableButton = (name: string) => screen.getByTitle(new RegExp(`^Add ${name}`));

describe("SequenceDesigner builder", () => {
  it("lets a replica count be cleared and retyped (1 → 60)", async () => {
    const user = userEvent.setup();
    const props = renderDesigner();
    await user.click(screen.getByTitle("Edit Sequence"));

    const replicas = screen.getByLabelText("Replicas for step 1");
    await user.clear(replicas);
    expect((replicas as HTMLInputElement).value).toBe("");
    await user.type(replicas, "60");
    expect((replicas as HTMLInputElement).value).toBe("60");
    await user.click(screen.getByRole("button", { name: "Update Sequence" }));

    expect(props.onUpdate).toHaveBeenCalledWith(7, expect.objectContaining({
      steps: [
        expect.objectContaining({ order: 1, deployment_name: "attccleadscomp", replicas: 60 }),
        expect.objectContaining({ order: 2, deployment_name: "attccleadsauditlog", replicas: 2 }),
      ],
    }));
  });

  it("restores the previous value when a replica field is left empty", async () => {
    const user = userEvent.setup();
    renderDesigner();
    await user.click(screen.getByTitle("Edit Sequence"));
    const replicas = screen.getByLabelText("Replicas for step 2") as HTMLInputElement;
    await user.clear(replicas);
    await user.tab();
    expect(replicas.value).toBe("2");
  });

  it("allows the same deployment in several steps with different replica counts", async () => {
    const user = userEvent.setup();
    const props = renderDesigner();
    await user.click(screen.getByRole("button", { name: /Create Sequence/ }));
    await user.type(screen.getByLabelText("Sequence Name"), "Warm start");

    await user.click(availableButton("attccleadscomp"));
    await user.click(availableButton("attccleadsauditlog"));
    await user.click(availableButton("attccleadscomp")); // again, to scale it further later

    expect(stepCards()).toHaveLength(3);
    expect(within(stepCards()[0]).getByText("Scale 1 of 2")).toBeTruthy();
    expect(within(stepCards()[2]).getByText("Scale 2 of 2")).toBeTruthy();

    const third = screen.getByLabelText("Replicas for step 3");
    await user.clear(third);
    await user.type(third, "50");
    await user.click(screen.getByRole("button", { name: "Save Sequence" }));

    expect(props.onCreate).toHaveBeenCalledWith(expect.objectContaining({
      name: "Warm start",
      steps: [
        expect.objectContaining({ order: 1, deployment_name: "attccleadscomp", replicas: 1 }),
        expect.objectContaining({ order: 2, deployment_name: "attccleadsauditlog", replicas: 1 }),
        expect.objectContaining({ order: 3, deployment_name: "attccleadscomp", replicas: 50 }),
      ],
    }));
  });

  it("names the step being dragged and reorders on drop", async () => {
    const user = userEvent.setup();
    renderDesigner();
    await user.click(screen.getByTitle("Edit Sequence"));

    const [first, second] = stepCards();
    expect(within(first).getByText("attccleadscomp")).toBeTruthy();

    fireEvent.pointerDown(within(first).getByLabelText(/Drag to reorder step 1/));
    fireEvent.dragStart(first, { dataTransfer: { setData: vi.fn(), effectAllowed: "" } });
    expect(screen.getByRole("status").textContent).toContain("Moving step 1: attccleadscomp");

    second.getBoundingClientRect = () => ({ top: 0, height: 40, bottom: 40, left: 0, right: 0, width: 0, x: 0, y: 0, toJSON: () => ({}) });
    fireEvent.dragOver(second, { clientY: 35, dataTransfer: { dropEffect: "" } });
    fireEvent.drop(second, { dataTransfer: {} });

    const reordered = stepCards();
    expect(within(reordered[0]).getByText("attccleadsauditlog")).toBeTruthy();
    expect(within(reordered[1]).getByText("attccleadscomp")).toBeTruthy();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("moves a step with the arrow buttons", async () => {
    const user = userEvent.setup();
    renderDesigner();
    await user.click(screen.getByTitle("Edit Sequence"));
    await user.click(screen.getByLabelText("Move step 2 up"));
    expect(within(stepCards()[0]).getByText("attccleadsauditlog")).toBeTruthy();
  });

  it("shows the server's reason when saving fails", async () => {
    const user = userEvent.setup();
    renderDesigner({ onUpdate: vi.fn().mockRejectedValue({ response: { data: { detail: "A sequence named 'x' already exists" } } }) });
    await user.click(screen.getByTitle("Edit Sequence"));
    await user.click(screen.getByLabelText("Move step 2 up"));
    await user.click(screen.getByRole("button", { name: "Update Sequence" }));
    expect((await screen.findByRole("alert")).textContent).toContain("already exists");
  });
});

describe("SequenceDesigner runs and deletes", () => {
  it("asks for confirmation with the planned changes before starting", async () => {
    const user = userEvent.setup();
    const props = renderDesigner();
    await user.click(screen.getByTitle("Run Startup Sequence"));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("attccleadscomp")).toBeTruthy();
    expect(props.onExecuteStart).not.toHaveBeenCalled();

    await user.click(within(dialog).getByRole("button", { name: "Start sequence" }));
    expect(props.onExecuteStart).toHaveBeenCalledWith(7, 1, false);
  });

  it("explains why a sequence used by a schedule cannot be deleted", async () => {
    const user = userEvent.setup();
    const props = renderDesigner({ schedules: [{ id: 3, job_name: "morning-start", sequence_id: 7 }] });
    await user.click(screen.getByTitle("Delete Sequence"));

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText("morning-start")).toBeTruthy();
    expect((within(dialog).getByRole("button", { name: "Delete sequence" }) as HTMLButtonElement).disabled).toBe(true);
    expect(props.onDelete).not.toHaveBeenCalled();
  });

  it("shows live step status from the tracked execution", () => {
    renderDesigner({
      trackedExecution: {
        id: 41, execution_type: "sequence", cluster_id: "c1", namespace: "apps", operation: "sequence_startup",
        sequence_name: "SCAL-Up-RTL", sequence_id: 7, status: "running", total_deployments: 2,
        completed_count: 1, failed_count: 0, skipped_count: 0, replica_count: 1, schedule_id: null,
        initiated_by: "u1", initiated_by_email: "ops@example.com", started_at: new Date().toISOString(),
        completed_at: null, duration_seconds: null, error_message: null,
        step_details: [
          { step: 1, deployment: "attccleadscomp", current_replicas: 0, target_replicas: 1, status: "completed", duration_seconds: 12 },
          { step: 2, deployment: "attccleadsauditlog", current_replicas: 1, target_replicas: 2, status: "running", started_at: new Date().toISOString(), wait_condition: "pods_ready" },
        ],
      },
    });
    expect(screen.getByText(/Step 2 of 2:/)).toBeTruthy();
    expect(screen.getAllByText("Completed").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Running").length).toBeGreaterThan(0);
  });
});

describe("ExecutionHistory sequence status", () => {
  it("names the sequence and shows unrun steps of a finished run as Not run, in step order", async () => {
    const user = userEvent.setup();
    render(
      <ExecutionHistoryGrid
        isLoading={false}
        history={[{
          id: 9, execution_type: "sequence", cluster_id: "c1", namespace: "apps", operation: "sequence_startup",
          sequence_name: "SCAL-Up-RTL", status: "failed", total_deployments: 3, completed_count: 1, failed_count: 1,
          skipped_count: 0, replica_count: 1, schedule_id: null, sequence_id: 7, initiated_by: "u1",
          initiated_by_email: "ops@example.com", started_at: "2026-10-07T10:00:00Z", completed_at: "2026-10-07T10:05:00Z",
          duration_seconds: 300, error_message: "Aborted at step 2 (b): only 3/60 pods ready after 600s",
          step_details: [
            { deployment: "c", target_replicas: 1, status: "pending", order: 3 },
            { deployment: "a", target_replicas: 1, status: "completed", order: 1 },
            { deployment: "b", target_replicas: 60, status: "failed", order: 2, error: "only 3/60 pods ready after 600s" },
          ],
        } as any]}
      />,
    );
    expect(screen.getByText("SCAL-Up-RTL")).toBeTruthy();
    await act(async () => { await user.click(screen.getByText("Startup sequence")); });

    // Step rows only: the expanded parent row contains all three names.
    const rows = screen.getAllByRole("row").filter((r) => within(r).queryAllByText(/^[abc]$/).length === 1);
    expect(rows.map((r) => within(r).getByText(/^[abc]$/).textContent)).toEqual(["a", "b", "c"]);
    expect(within(rows[2]).getByText("Not run")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("Aborted at step 2");
  });
});
