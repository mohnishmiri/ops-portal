/**
 * Tests for JobsTab — inventory rendering, the filter facets, the delete
 * confirmation, and capability gating of destructive actions.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import React from "react";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock("../../services/aksApi", () => ({
  useJobs: vi.fn(),
  useJobDetail: vi.fn(),
  useDeleteJob: vi.fn(),
}));

import * as aksApi from "../../services/aksApi";
import { JobsTab } from "./JobsTab";

const CLUSTER = {
  id: "/subscriptions/s/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks-01",
  name: "aks-01",
} as any;

function job(overrides: Partial<aksApi.K8sJob> = {}): aksApi.K8sJob {
  return {
    name: "nightly-report-manual-20260820120000",
    namespace: "com-att-prod",
    uid: "u1",
    status: "Completed",
    completions: 1,
    succeeded: 1,
    failed: 0,
    active: 0,
    parallelism: 1,
    backoff_limit: 6,
    completion_mode: "NonIndexed",
    ttl_seconds_after_finished: null,
    suspended: false,
    start_time: "2026-08-20T12:00:00Z",
    completion_time: "2026-08-20T12:05:00Z",
    created_at: new Date().toISOString(),
    created_by: "nightly-report",
    trigger: "manual",
    labels: {},
    annotations: {},
    image: "repo/img:1",
    ...overrides,
  };
}

const mutate = vi.fn();

function setup(jobs: aksApi.K8sJob[], props: Partial<React.ComponentProps<typeof JobsTab>> = {}) {
  (aksApi.useJobs as any).mockReturnValue({
    data: { jobs, count: jobs.length },
    isLoading: false,
    isError: false,
    isFetching: false,
    refetch: vi.fn(),
  });
  (aksApi.useJobDetail as any).mockReturnValue({
    data: undefined,
    isLoading: true,
    isError: false,
  });
  (aksApi.useDeleteJob as any).mockReturnValue({ mutate, isPending: false });

  return render(
    <JobsTab
      cluster={CLUSTER}
      namespace=""
      namespaces={["com-att-prod", "default"]}
      onNamespaceChange={vi.fn()}
      showToast={vi.fn()}
      formatDate={(v) => v}
      canDeleteJob
      canDeletePod
      onViewPodLogs={vi.fn()}
      onDeletePod={vi.fn()}
      {...props}
    />
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("JobsTab inventory", () => {
  it("renders jobs with completions, counts, and creator", () => {
    setup([job()]);

    // Scope to the table: "com-att-prod" also appears as a namespace <option>.
    const row = screen.getByText("nightly-report-manual-20260820120000").closest("tr")!;
    expect(within(row).getByText("com-att-prod")).toBeTruthy();
    expect(within(row).getByText("Completed")).toBeTruthy();
    expect(within(row).getByText("1/1")).toBeTruthy();
    expect(within(row).getByText("nightly-report")).toBeTruthy();
    // Manually triggered Jobs are badged so they are distinguishable from
    // scheduled runs of the same CronJob.
    expect(screen.getByText("manual")).toBeTruthy();
  });

  it("shows an empty state when the cluster has no jobs", () => {
    setup([]);
    expect(screen.getByText(/No Jobs found/i)).toBeTruthy();
  });

  it("filters by status", () => {
    setup([
      job({ name: "job-done", status: "Completed" }),
      job({ name: "job-running", status: "Running", active: 1, succeeded: 0 }),
    ]);

    fireEvent.change(screen.getByLabelText("Filter by status"), { target: { value: "Running" } });

    expect(screen.queryByText("job-done")).toBeNull();
    expect(screen.getByText("job-running")).toBeTruthy();
  });

  it("filters by completion state", () => {
    setup([
      job({ name: "job-done", status: "Completed" }),
      job({ name: "job-running", status: "Running", active: 1 }),
    ]);

    fireEvent.change(screen.getByLabelText("Filter by completion"), {
      target: { value: "unfinished" },
    });

    expect(screen.queryByText("job-done")).toBeNull();
    expect(screen.getByText("job-running")).toBeTruthy();
  });

  it("filters by age, excluding jobs older than the window", () => {
    const old = new Date(Date.now() - 1000 * 60 * 60 * 48).toISOString();
    setup([
      job({ name: "job-fresh", created_at: new Date().toISOString() }),
      job({ name: "job-old", created_at: old }),
    ]);

    fireEvent.change(screen.getByLabelText("Filter by age"), { target: { value: "1h" } });

    expect(screen.getByText("job-fresh")).toBeTruthy();
    expect(screen.queryByText("job-old")).toBeNull();
  });

  it("searches across name, namespace, and owning CronJob", () => {
    setup([
      job({ name: "alpha-job", created_by: "alpha-cron" }),
      job({ name: "beta-job", created_by: "beta-cron" }),
    ]);

    fireEvent.change(screen.getByPlaceholderText(/Search jobs/i), {
      target: { value: "beta-cron" },
    });

    expect(screen.queryByText("alpha-job")).toBeNull();
    expect(screen.getByText("beta-job")).toBeTruthy();
  });
});

describe("JobsTab deletion", () => {
  it("requires confirmation before deleting", () => {
    setup([job({ name: "doomed-job" })]);

    fireEvent.click(screen.getByTitle("Delete Job"));

    // Nothing is deleted just by opening the dialog.
    expect(mutate).not.toHaveBeenCalled();

    const dialog = screen.getByText("Delete Job", { selector: "h3" }).closest("div")!;
    expect(within(dialog.parentElement!).getByText(/doomed-job/)).toBeTruthy();
  });

  it("warns that the job's pods are deleted too", () => {
    setup([job()]);
    fireEvent.click(screen.getByTitle("Delete Job"));
    expect(screen.getByText(/also deletes the pods it created/i)).toBeTruthy();
  });

  it("deletes only after the confirm button is pressed", () => {
    setup([job({ name: "doomed-job", namespace: "ns-a" })]);

    fireEvent.click(screen.getByTitle("Delete Job"));
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(mutate).toHaveBeenCalledTimes(1);
    expect(mutate.mock.calls[0][0]).toEqual({
      clusterId: CLUSTER.id,
      namespace: "ns-a",
      jobName: "doomed-job",
    });
  });

  it("does not delete when the dialog is cancelled", () => {
    setup([job()]);

    fireEvent.click(screen.getByTitle("Delete Job"));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(mutate).not.toHaveBeenCalled();
  });
});

describe("JobsTab capability gating", () => {
  it("hides the delete action without AKS_JOB_DELETE", () => {
    setup([job()], { canDeleteJob: false });
    expect(screen.queryByTitle("Delete Job")).toBeNull();
    // Viewing remains available.
    expect(screen.getByTitle("View Details")).toBeTruthy();
  });

  it("shows the delete action with the capability", () => {
    setup([job()], { canDeleteJob: true });
    expect(screen.getByTitle("Delete Job")).toBeTruthy();
  });
});

describe("JobsTab CronJob handoff", () => {
  it("opens the focused job's detail panel and reports the focus consumed", () => {
    const onFocusConsumed = vi.fn();
    setup([job({ name: "triggered-job", namespace: "com-att-prod" })], {
      focusJob: { namespace: "com-att-prod", name: "triggered-job" },
      onFocusConsumed,
    });

    // The detail panel is opened for the handed-off Job.
    expect(aksApi.useJobDetail).toHaveBeenCalledWith(
      CLUSTER.id,
      "com-att-prod",
      "triggered-job",
      true
    );
    // Consumed once so re-renders don't keep reopening it.
    expect(onFocusConsumed).toHaveBeenCalled();
  });
});
