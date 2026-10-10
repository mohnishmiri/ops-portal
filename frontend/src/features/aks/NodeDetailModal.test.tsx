/**
 * Node detail: what the scheduler has committed on the node, and the pods on it.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock("../../services/aksApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../services/aksApi")>()),
  useNodeDetail: vi.fn(),
}));

import * as aksApi from "../../services/aksApi";
import { formatBytes, formatCores, NodeDetailModal } from "./NodeDetailModal";

const pod = (name: string, overrides: Partial<aksApi.NodePodRow> = {}): aksApi.NodePodRow => ({
  pod_name: name,
  namespace: "apps",
  phase: "Running",
  status: "Running",
  ready: true,
  node: "aks-np-1",
  pod_ip: "10.0.0.5",
  started_at: "2026-10-01T00:00:00Z",
  restarts: 0,
  containers: ["app"],
  revision: null,
  cpu_request_m: 250,
  cpu_limit_m: 1000,
  memory_request_bytes: 256 * 2 ** 20,
  memory_limit_bytes: 512 * 2 ** 20,
  ready_containers: 1,
  total_containers: 1,
  owner_kind: "ReplicaSet",
  owner_name: "web-abc",
  qos_class: "Burstable",
  terminated: false,
  ...overrides,
});

const DETAIL: aksApi.KubernetesNodeDetail = {
  name: "aks-np-1",
  pool: "np",
  ready: true,
  unschedulable: false,
  pressure: [],
  created_at: "2026-10-01T00:00:00Z",
  zone: "eastus2-2",
  instance_type: "Standard_B2ms",
  node_image_version: "AKSUbuntu-2204gen2containerd-202608.14.0",
  provider_id: null,
  pod_cidr: null,
  addresses: [{ type: "InternalIP", address: "10.224.0.4" }],
  system: { os_image: "Ubuntu 22.04.5 LTS", kernel_version: "5.15", container_runtime: "containerd://1.7", kubelet_version: "v1.36.3", kube_proxy_version: "v1.36.3", architecture: "amd64", operating_system: "linux" },
  capacity: { cpu_m: 2000, memory_bytes: 8 * 2 ** 30, pods: 30, ephemeral_storage_bytes: 0 },
  allocatable: { cpu_m: 1900, memory_bytes: 7 * 2 ** 30, pods: 30, ephemeral_storage_bytes: 100 * 2 ** 30 },
  allocated: { pods: 2, cpu_request_m: 1250, cpu_limit_m: 2000, memory_request_bytes: 2 ** 30, memory_limit_bytes: 2 ** 31, cpu_request_pct: 65.8, memory_request_pct: 14.3, cpu_limit_pct: 105.3, memory_limit_pct: 28.6 },
  usage: { cpu_m: 600, memory_bytes: 3 * 2 ** 30, cpu_pct: 31.6, memory_pct: 42.9, timestamp: null },
  conditions: [{ type: "Ready", status: "True", reason: "KubeletReady", message: "ok", last_transition_time: null }],
  taints: ["CriticalAddonsOnly=true:NoSchedule"],
  labels: { "kubernetes.azure.com/agentpool": "np" },
  annotations: {},
  pods: [pod("web-1", { cpu_usage_m: 12, memory_usage_bytes: 100 * 2 ** 20 }), pod("api-1", { ready: false, ready_containers: 0, status: "CrashLoopBackOff", restarts: 7 }), pod("job-1", { terminated: true, status: "Completed", phase: "Succeeded" })],
  events: [],
};

function renderModal(onOpenPod = vi.fn()) {
  (aksApi.useNodeDetail as any).mockReturnValue({ data: DETAIL, isLoading: false, isError: false });
  render(<NodeDetailModal clusterId="c1" name="aks-np-1" formatDate={(v) => v} onOpenPod={onOpenPod} onClose={vi.fn()} />);
  return onOpenPod;
}

describe("NodeDetailModal", () => {
  it("leads with live usage and shows what pods have requested", () => {
    renderModal();

    const cpu = screen.getByRole("button", { name: "Show pods by CPU use" });
    expect(within(cpu).getByText("31.6%")).toBeTruthy();
    expect(within(cpu).getByText("600m of 1.90 cores in use · 65.8% requested")).toBeTruthy();
    expect(screen.getByText("2/30")).toBeTruthy();
    expect(screen.getByText("Usage vs Requests")).toBeTruthy();
    expect(screen.getByText("Ubuntu 22.04.5 LTS")).toBeTruthy();
  });

  it("falls back to requested shares without metrics-server", () => {
    (aksApi.useNodeDetail as any).mockReturnValue({ data: { ...DETAIL, usage: null }, isLoading: false, isError: false });
    render(<NodeDetailModal clusterId="c1" name="aks-np-1" formatDate={(v) => v} onClose={vi.fn()} />);

    expect(screen.getByText("CPU Requested")).toBeTruthy();
    expect(screen.getByText("1.25 cores of 1.90 cores · live usage unavailable")).toBeTruthy();
    expect(screen.getByText(/metrics-server isn't reporting for this cluster/)).toBeTruthy();
  });

  it("colours node problem conditions by their meaning", () => {
    (aksApi.useNodeDetail as any).mockReturnValue({
      data: {
        ...DETAIL,
        conditions: [
          { type: "Ready", status: "True", reason: "KubeletReady", message: "ok", last_transition_time: null },
          { type: "KubeletProblem", status: "False", reason: "KubeletIsUp", message: "kubelet service is up", last_transition_time: null },
          { type: "DiskPressure", status: "True", reason: "KubeletHasDiskPressure", message: "disk", last_transition_time: null },
        ],
      },
      isLoading: false,
      isError: false,
    });
    render(<NodeDetailModal clusterId="c1" name="aks-np-1" formatDate={(v) => v} onClose={vi.fn()} />);

    const badge = (reason: string) => within(screen.getByText(reason).closest("tr")!).getAllByText(/True|False/)[0].className;
    expect(badge("KubeletReady")).toContain("green");
    expect(badge("KubeletIsUp")).toContain("green"); // False is healthy for a problem condition
    expect(badge("KubeletHasDiskPressure")).toContain("amber");
  });

  it("lists the pods on the node and opens one", () => {
    const onOpenPod = renderModal();

    fireEvent.click(screen.getByRole("button", { name: "Show the pods on this node" }));
    // With pods not ready, the tile opens the grid filtered to them.
    expect(screen.getByRole("button", { name: "api-1" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "web-1" })).toBeNull();

    fireEvent.change(screen.getByLabelText("Filter pods"), { target: { value: "all" } });
    expect(screen.getByText("job-1")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "web-1" }));
    expect(onOpenPod.mock.calls[0][0].pod_name).toBe("web-1");
  });

  it("shows the node's own taints", () => {
    renderModal();

    fireEvent.click(screen.getByRole("tab", { name: /Labels & Taints/ }));
    expect(screen.getByText("CriticalAddonsOnly")).toBeTruthy();
  });
});

describe("node resource formatting", () => {
  it("formats CPU and memory", () => {
    expect(formatCores(250)).toBe("250m");
    expect(formatCores(2000)).toBe("2 cores");
    expect(formatCores(1250)).toBe("1.25 cores");
    expect(formatBytes(512 * 2 ** 20)).toBe("512 MiB");
    expect(formatBytes(7 * 2 ** 30)).toBe("7.0 GiB");
  });
});
