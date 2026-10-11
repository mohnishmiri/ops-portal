/**
 * Cluster / node / per-pool utilisation history from AKS platform metrics.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock("../../services/aksApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../services/aksApi")>()),
  useClusterMetrics: vi.fn(),
}));

import * as aksApi from "../../services/aksApi";
import { ClusterUtilisation } from "./NodePoolUtilisation";

// recharts' ResponsiveContainer needs ResizeObserver, which jsdom lacks.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

const SERIES: aksApi.NodePoolMetricPoint[] = [
  { t: "2026-10-10T22:00:00Z", cpu_avg: 2.1, cpu_max: 97.5, memory_avg: 40.2, memory_max: 61.0 },
  { t: "2026-10-10T22:15:00Z", cpu_avg: 2.4, cpu_max: 98.0, memory_avg: 40.6, memory_max: 60.6 },
];

const CLUSTER: aksApi.ClusterMetrics = {
  scope: "cluster",
  range: "24h",
  interval: "PT15M",
  node: null,
  series: SERIES,
  cpu: { current: 2.4, average: 2.3, peak: 98.0 },
  memory: { current: 40.6, average: 40.4, peak: 61.0 },
};

const POOLS: aksApi.ClusterMetrics = {
  scope: "nodepools",
  range: "24h",
  interval: "PT15M",
  node: null,
  pools: [
    { name: "system", series: SERIES, cpu: { current: 5.5, average: 5.0, peak: 9.1 }, memory: { current: 55.0, average: 54.0, peak: 58.0 } },
    { name: "np1", series: SERIES, cpu: { current: 1.2, average: 1.1, peak: 98.0 }, memory: { current: 33.3, average: 33.0, peak: 61.0 } },
  ],
};

const result = (data: aksApi.ClusterMetrics | undefined, extra: Record<string, unknown> = {}) => ({
  data,
  isLoading: !data,
  isFetching: false,
  isError: false,
  error: null,
  ...extra,
});

const useClusterMetrics = aksApi.useClusterMetrics as unknown as ReturnType<typeof vi.fn>;

beforeEach(() => {
  useClusterMetrics.mockReset();
  useClusterMetrics.mockImplementation((_id: string, _range: string, opts: { split?: string }) =>
    result(opts.split === "nodepool" ? POOLS : CLUSTER)
  );
});

const renderPanel = (props: Partial<React.ComponentProps<typeof ClusterUtilisation>> = {}) =>
  render(<ClusterUtilisation clusterId="c1" formatDate={(v) => v} {...props} />);

describe("ClusterUtilisation", () => {
  it("summarises the cluster and says the peak is the busiest node", () => {
    renderPanel();
    expect(useClusterMetrics).toHaveBeenLastCalledWith("c1", "24h", { node: undefined, split: "none" });
    const cpu = screen.getByLabelText("CPU summary");
    expect(within(cpu).getByText("2.4%")).toBeInTheDocument();
    expect(within(cpu).getByText("98%")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Memory working set summary")).getByText("40.6%")).toBeInTheDocument();
    expect(screen.getByText(/peak is the busiest node/)).toBeInTheDocument();
  });

  it("splits by node pool with a legend that carries each pool's current value", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "By node pool" }));
    expect(useClusterMetrics).toHaveBeenLastCalledWith("c1", "24h", { node: undefined, split: "nodepool" });
    const legend = screen.getByLabelText("CPU by node pool legend");
    expect(within(legend).getByText("system")).toBeInTheDocument();
    expect(within(legend).getByText("5.5%")).toBeInTheDocument();
    expect(within(legend).getByText("1.2%")).toBeInTheDocument();
    expect(within(screen.getByLabelText("Memory working set by node pool legend")).getByText("33.3%")).toBeInTheDocument();
  });

  it("lists every pool's now/avg/peak in the table view", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "By node pool" }));
    fireEvent.click(screen.getByRole("button", { name: "Show table" }));
    const row = screen.getByRole("row", { name: /np1/ });
    expect(within(row).getByText("98%")).toBeInTheDocument();
    expect(within(row).getByText("61%")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /system/ })).toBeInTheDocument();
  });

  it("doesn't read the cluster response as pools while the split loads", () => {
    useClusterMetrics.mockImplementation(() => result(CLUSTER, { isFetching: true }));
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "By node pool" }));
    expect(screen.getByText("Reading Azure Monitor…")).toBeInTheDocument();
    expect(screen.queryByLabelText("CPU by node pool legend")).not.toBeInTheDocument();
  });

  it("shows one node with no breakdown toggle", () => {
    useClusterMetrics.mockImplementation(() => result({ ...CLUSTER, scope: "node", node: "aks-np1-vmss00000b" }));
    renderPanel({ node: "aks-np1-vmss00000b" });
    expect(useClusterMetrics).toHaveBeenLastCalledWith("c1", "24h", { node: "aks-np1-vmss00000b", split: "none" });
    expect(screen.queryByRole("group", { name: "Breakdown" })).not.toBeInTheDocument();
    expect(screen.queryByText(/busiest node/)).not.toBeInTheDocument();
    expect(screen.getAllByText("This node, %")).toHaveLength(2);
  });

  it("changes the range and explains an Azure Monitor failure", () => {
    renderPanel();
    fireEvent.click(screen.getByRole("button", { name: "7d" }));
    expect(useClusterMetrics).toHaveBeenLastCalledWith("c1", "7d", { node: undefined, split: "none" });

    useClusterMetrics.mockImplementation(() =>
      result(undefined, { isLoading: false, isError: true, error: { response: { data: { detail: "Azure Monitor refused the request" } } } })
    );
    renderPanel();
    expect(screen.getByText("Azure Monitor refused the request")).toBeInTheDocument();
  });
});
