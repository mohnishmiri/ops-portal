/**
 * Node Pools tab: accurate figures (unavailable is not zero), tile filters,
 * the detail popup's node grid, and validated scale / autoscaling dialogs.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock("../../services/aksApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../services/aksApi")>()),
  useCachedNodePools: vi.fn(),
  useAksBackgroundSync: vi.fn(() => ({ isRunning: false, isRetrying: false, error: null, start: vi.fn() })),
  useScaleNodePool: vi.fn(),
  useUpdateAutoscaling: vi.fn(),
}));

import * as aksApi from "../../services/aksApi";
import { formatCpu, formatMemory, nodeImageVersion, NodePoolsTab, poolIssues } from "./NodePoolsTab";

const CLUSTER = { id: "/subscriptions/s/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/aks-01", name: "aks-01" } as any;

function node(name: string, overrides: Partial<aksApi.NodeDetail> = {}): aksApi.NodeDetail {
  return {
    name,
    pool: "userpool",
    ready: true,
    unschedulable: false,
    pressure: [],
    pod_count: 20,
    allocatable_pods: 30,
    allocatable_cpu: "31580m",
    allocatable_memory: "123456Ki",
    zone: "eastus2-1",
    kubelet_version: "v1.34.1",
    created_at: "2026-10-01T00:00:00Z",
    labels: {},
    ...overrides,
  };
}

function pool(overrides: Partial<aksApi.NodePoolDetails> = {}): aksApi.NodePoolDetails {
  return {
    name: "userpool",
    vm_size: "Standard_D32s_v3",
    count: 2,
    min_count: null,
    max_count: null,
    enable_auto_scaling: false,
    mode: "User",
    os_type: "Linux",
    os_sku: "Ubuntu",
    os_disk_size_gb: 128,
    os_disk_type: "Managed",
    kubernetes_version: "1.34.1",
    provisioning_state: "Succeeded",
    power_state: "Running",
    max_pods: 30,
    node_labels: { nodepool: "elk" },
    node_taints: ["dedicated=elk:NoSchedule"],
    availability_zones: ["1", "2", "3"],
    node_image_version: "AKSUbuntu-2204gen2containerd-202602.13.0",
    scale_set_priority: "Regular",
    node_details_available: true,
    node_details_error: null,
    total_pods: 40,
    pod_capacity: 60,
    ready_nodes: 2,
    cordoned_nodes: 0,
    nodes: [node("aks-userpool-1"), node("aks-userpool-2")],
    ...overrides,
  };
}

const POOLS = [
  pool(),
  pool({ name: "syspool", mode: "System", count: 2, enable_auto_scaling: true, min_count: 2, max_count: 10, nodes: [node("aks-sys-1", { pool: "syspool" }), node("aks-sys-2", { pool: "syspool", ready: false })], ready_nodes: 1 }),
  pool({ name: "batch", count: 20, enable_auto_scaling: true, min_count: 0, max_count: 20, total_pods: 300, pod_capacity: 600, nodes: [], ready_nodes: 0 }),
];

const scaleMutate = vi.fn();
const autoscaleMutate = vi.fn();

function setup(pools: aksApi.NodePoolDetails[] = POOLS, canManage = true) {
  (aksApi.useCachedNodePools as any).mockReturnValue({
    data: { source: "db", last_sync: new Date().toISOString(), node_pools: pools, count: pools.length },
    isFetching: false,
    isPlaceholderData: false,
    isError: false,
  });
  (aksApi.useScaleNodePool as any).mockReturnValue({ mutate: scaleMutate, isPending: false });
  (aksApi.useUpdateAutoscaling as any).mockReturnValue({ mutate: autoscaleMutate, isPending: false });
  render(<NodePoolsTab cluster={CLUSTER} showToast={vi.fn()} formatDate={(v) => v} canManage={canManage} />);
}

const rows = () => screen.getAllByRole("row").slice(1);

describe("NodePoolsTab", () => {
  beforeEach(() => {
    scaleMutate.mockReset();
    autoscaleMutate.mockReset();
  });

  it("shows pods against capacity and the node image release", () => {
    setup([pool()]);

    const row = rows()[0];
    expect(within(row).getByText("Standard_D32s_v3")).toBeTruthy();
    expect(within(row).getByText("/ 60")).toBeTruthy();
    expect(within(row).getByText("202602.13.0")).toBeTruthy();
    expect(within(row).getByText("All ready")).toBeTruthy();
  });

  it("shows unavailable pod counts as unknown, not zero", () => {
    setup([pool({ node_details_available: false, node_details_error: "The Kubernetes API did not respond in time.", total_pods: null, pod_capacity: null, ready_nodes: null, nodes: [] })]);

    expect(screen.getByText(/Node health and pod counts are unavailable: The Kubernetes API did not respond in time/)).toBeTruthy();
    expect(screen.getByText("Node health unavailable")).toBeTruthy();
    expect(screen.getByText("Node health unknown")).toBeTruthy();
    expect(screen.queryByText("All pools healthy")).toBeNull();
    expect(within(rows()[0]).getByTitle("The Kubernetes API did not respond in time.").textContent).toBe("—");
  });

  it("flags stale data even while a sync is marked running", () => {
    (aksApi.useAksBackgroundSync as any).mockReturnValueOnce({ isRunning: true, isRetrying: false, error: null, start: vi.fn() });
    (aksApi.useCachedNodePools as any).mockReturnValue({
      data: { source: "db", last_sync: new Date(Date.now() - 137 * 60_000).toISOString(), node_pools: POOLS, count: 3 },
      isFetching: false,
      isPlaceholderData: false,
      isError: false,
    });
    (aksApi.useScaleNodePool as any).mockReturnValue({ mutate: scaleMutate, isPending: false });
    (aksApi.useUpdateAutoscaling as any).mockReturnValue({ mutate: autoscaleMutate, isPending: false });
    render(<NodePoolsTab cluster={CLUSTER} showToast={vi.fn()} formatDate={(v) => v} canManage />);

    expect(screen.getByText(/This data is 2 h 17 min old: no sync has completed since then/)).toBeTruthy();
    expect(screen.getByText(/A sync is running now/)).toBeTruthy();
  });

  it("filters the grid from the Needs Attention tile", () => {
    setup();

    fireEvent.click(screen.getByRole("button", { name: "Show node pools that need attention" }));

    // syspool has a node that isn't ready; batch is at its autoscaling maximum.
    expect(rows().map((r) => within(r).getAllByRole("button")[0].textContent)).toEqual(["batch", "syspool"]);
    expect(screen.getByText("Pools that need attention")).toBeTruthy();
  });

  it("disables manual scaling for autoscaled pools and validates the count", () => {
    setup();
    const [batch, sys, user] = rows();
    expect((within(batch).getByLabelText("Scale node pool") as HTMLButtonElement).disabled).toBe(true);
    expect((within(sys).getByLabelText("Scale node pool") as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(within(user).getByLabelText("Scale node pool"));
    const input = screen.getByLabelText("Node count");
    fireEvent.change(input, { target: { value: "2" } });
    expect(screen.getByText("userpool already has 2 nodes.")).toBeTruthy();
    fireEvent.change(input, { target: { value: "5" } });
    fireEvent.click(screen.getByRole("button", { name: "Scale" }));

    expect(scaleMutate.mock.calls[0][0]).toEqual({ clusterId: CLUSTER.id, nodepoolName: "userpool", nodeCount: 5 });
  });

  it("keeps a System pool's autoscaling minimum at one or more", () => {
    setup();

    fireEvent.click(within(rows()[1]).getByTitle("Configure autoscaling"));
    const save = screen.getByRole("button", { name: "Save" }) as HTMLButtonElement;
    expect(save.disabled).toBe(true); // nothing changed yet
    fireEvent.change(screen.getByLabelText("Minimum nodes"), { target: { value: "0" } });
    expect(screen.getByText("syspool is a System pool; its minimum must be at least 1 node.")).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Minimum nodes"), { target: { value: "3" } });
    fireEvent.change(screen.getByLabelText("Maximum nodes"), { target: { value: "12" } });
    fireEvent.click(save);

    expect(autoscaleMutate.mock.calls[0][0]).toMatchObject({ nodepoolName: "syspool", enableAutoScaling: true, minCount: 3, maxCount: 12 });
  });

  it("hides changes from users who can't manage node pools", () => {
    setup(POOLS, false);

    expect(screen.queryByLabelText("Scale node pool")).toBeNull();
    expect(screen.queryByTitle("Configure autoscaling")).toBeNull();
    expect(screen.getAllByTitle("View details")).toHaveLength(3);
  });

  it("opens the pool detail with its nodes, filtered to the ones not ready", () => {
    setup();

    fireEvent.click(within(rows()[1]).getByRole("button", { name: "syspool" }));
    fireEvent.click(screen.getByRole("button", { name: "Show this pool's nodes" }));

    expect(screen.getByRole("tab", { name: /Nodes/ }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByText("aks-sys-2")).toBeTruthy();
    expect(screen.queryByText("aks-sys-1")).toBeNull();
  });

  it("lists the pool's taints", () => {
    setup([pool()]);

    fireEvent.click(screen.getByRole("button", { name: "userpool" }));
    fireEvent.click(screen.getByRole("tab", { name: /Labels & Taints/ }));

    expect(screen.getByText("dedicated")).toBeTruthy();
    expect(screen.getByText("NoSchedule")).toBeTruthy();
  });
});

describe("node pool formatting", () => {
  it("reads the node image release from its version", () => {
    const { version, released } = nodeImageVersion("AKSUbuntu-2204gen2containerd-202602.13.0");
    expect(version).toBe("202602.13.0");
    expect(released?.getFullYear()).toBe(2026);
    expect(released?.getMonth()).toBe(1);
    expect(released?.getDate()).toBe(13);
  });

  it("formats Kubernetes CPU and memory quantities", () => {
    expect(formatCpu("31580m")).toBe("31.6 cores");
    expect(formatCpu("8")).toBe("8 cores");
    expect(formatMemory("123456Ki")).toBe("0.1 GiB");
    expect(formatMemory("16Gi")).toBe("16.0 GiB");
  });

  it("flags provisioning, health, and capacity problems", () => {
    expect(poolIssues(pool())).toEqual([]);
    expect(poolIssues(pool({ provisioning_state: "Scaling" }))).toEqual(["Scaling in progress"]);
    expect(poolIssues(pool({ enable_auto_scaling: true, min_count: 1, max_count: 2 }))).toEqual(["At autoscaling maximum"]);
    expect(poolIssues(pool({ node_details_available: false, ready_nodes: null }))).toEqual([]);
  });
});
