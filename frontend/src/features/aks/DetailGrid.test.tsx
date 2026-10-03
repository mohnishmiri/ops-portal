/**
 * DetailGrid is the table inside every AKS resource detail view, so the ATT
 * grid rules are tested once here: top-right search, sortable columns, and a
 * bottom pager whose page survives background refreshes.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";
import type { WorkloadEvent, WorkloadPod } from "../../services/aksApi";
import { DetailGrid } from "./DetailGrid";
import { EventsGrid, WorkloadPodsGrid } from "./detailShared";

type Row = { name: string; restarts: number };

const makeRows = (n: number): Row[] => Array.from({ length: n }, (_, i) => ({ name: `pod-${String(i + 1).padStart(2, "0")}`, restarts: i % 3 }));

function renderGrid(rows: Row[]) {
  return render(
    <DetailGrid
      title="Pods"
      rows={rows}
      columns={[
        { key: "name", header: "Name", sortValue: (r) => r.name, render: (r) => r.name },
        { key: "restarts", header: "Restarts", sortValue: (r) => r.restarts, render: (r) => String(r.restarts) },
      ]}
      rowKey={(r) => r.name}
      searchText={(r) => r.name}
      initialSort={{ key: "name", direction: "asc" }}
    />
  );
}

const bodyRows = () => screen.getAllByRole("row").slice(1); // drop the header row
const firstCell = () => within(bodyRows()[0]).getAllByRole("cell")[0].textContent;

describe("DetailGrid", () => {
  it("searches from the top-right box and reports the match count", () => {
    renderGrid(makeRows(25));

    fireEvent.change(screen.getByRole("searchbox", { name: "Search Pods" }), { target: { value: "pod-1" } });

    expect(screen.getByText("10 of 25")).toBeTruthy(); // pod-10 … pod-19
    expect(bodyRows()).toHaveLength(10);

    fireEvent.change(screen.getByRole("searchbox", { name: "Search Pods" }), { target: { value: "nope" } });
    expect(screen.getByText("No results match “nope”")).toBeTruthy();
  });

  it("sorts by a column and toggles direction", () => {
    renderGrid(makeRows(5));
    expect(firstCell()).toBe("pod-01");

    fireEvent.click(screen.getByRole("button", { name: /Name/ }));
    expect(firstCell()).toBe("pod-05");

    fireEvent.click(screen.getByRole("button", { name: /Restarts/ }));
    expect(within(bodyRows()[0]).getAllByRole("cell")[1].textContent).toBe("0");
  });

  it("pages below the grid with a rows-per-page selector", () => {
    renderGrid(makeRows(25));
    expect(screen.getByText("Showing 1–10 of 25")).toBeTruthy();
    expect(screen.getByText("Page 1 of 3")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Next" }));
    expect(screen.getByText("Showing 11–20 of 25")).toBeTruthy();
    expect(firstCell()).toBe("pod-11");

    fireEvent.change(screen.getByLabelText("Rows per page"), { target: { value: "50" } });
    expect(screen.getByText("Showing 1–25 of 25")).toBeTruthy();
    expect(bodyRows()).toHaveLength(25);
  });

  it("returns to page 1 on a new search but keeps the page across a background refresh", () => {
    const { rerender } = renderGrid(makeRows(25));
    fireEvent.click(screen.getByRole("button", { name: "Next" }));

    // The detail views refetch every 10s, producing a new array with the same rows.
    rerender(
      <DetailGrid
        title="Pods"
        rows={makeRows(25)}
        columns={[{ key: "name", header: "Name", sortValue: (r: Row) => r.name, render: (r: Row) => r.name }]}
        rowKey={(r) => r.name}
        searchText={(r) => r.name}
        initialSort={{ key: "name", direction: "asc" }}
      />
    );
    expect(screen.getByText("Page 2 of 3")).toBeTruthy();

    fireEvent.change(screen.getByRole("searchbox", { name: "Search Pods" }), { target: { value: "pod" } });
    expect(screen.getByText("Page 1 of 3")).toBeTruthy();
  });
});

describe("EventsGrid", () => {
  const events: WorkloadEvent[] = [
    { type: "Warning", reason: "FailedCreate", message: "exceeded quota", count: 3, last_seen: "2026-10-03T01:00:00Z" },
    { type: "Normal", reason: "ScalingReplicaSet", message: "Scaled up", count: 1, last_seen: "2026-10-03T02:00:00Z" },
  ];

  it("lists the newest event first and filters by type", () => {
    render(<EventsGrid events={events} formatDate={(v) => v} />);
    expect(within(bodyRows()[0]).getByText("ScalingReplicaSet")).toBeTruthy();

    fireEvent.change(screen.getByLabelText("Filter events"), { target: { value: "Warning" } });

    expect(bodyRows()).toHaveLength(1);
    expect(screen.getByText("FailedCreate")).toBeTruthy();
    expect(screen.queryByText("ScalingReplicaSet")).toBeNull();
  });
});

describe("WorkloadPodsGrid", () => {
  const pod = (name: string, overrides: Partial<WorkloadPod> = {}): WorkloadPod => ({
    pod_name: name,
    namespace: "apps",
    phase: "Running",
    status: "Running",
    ready: true,
    node: "aks-attccprodnp6-30822656-vmss000r8e",
    pod_ip: "10.0.0.5",
    started_at: null,
    restarts: 0,
    containers: ["app"],
    revision: "1",
    ...overrides,
  });

  it("keeps long pod and node names on one line with the full value on hover", () => {
    render(<WorkloadPodsGrid pods={[pod("administration-64c97dbbf5-29k48")]} onOpenPod={vi.fn()} onViewPodLogs={vi.fn()} canDeletePod={false} />);

    const name = screen.getByRole("button", { name: "administration-64c97dbbf5-29k48" });
    expect(name.className).toContain("truncate");
    expect(screen.getByTitle("aks-attccprodnp6-30822656-vmss000r8e").className).toContain("truncate");
  });

  it("filters to pods that are not ready", () => {
    render(
      <WorkloadPodsGrid
        pods={[pod("web-a"), pod("web-b", { ready: false, status: "CrashLoopBackOff", restarts: 4 })]}
        onViewPodLogs={vi.fn()}
        canDeletePod={false}
      />
    );

    fireEvent.change(screen.getByLabelText("Filter pods"), { target: { value: "not-ready" } });

    expect(bodyRows()).toHaveLength(1);
    expect(screen.getByText("web-b")).toBeTruthy();
  });
});
