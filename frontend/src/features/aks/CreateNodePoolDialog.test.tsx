/**
 * "Add a node pool": the validation rules (mirroring Azure's), the request it
 * builds, and the step-by-step flow through Review + create.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

vi.mock("../../services/aksApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../../services/aksApi")>()),
  useNodePoolCreateOptions: vi.fn(),
  useCreateNodePool: vi.fn(),
}));

import * as aksApi from "../../services/aksApi";
import { CreateNodePoolDialog, defaultForm, toPayload, validateForm } from "./CreateNodePoolDialog";

const CLUSTER_ID = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.ContainerService/managedClusters/uat-aks";
const SUBNET = "/subscriptions/s/resourceGroups/rg/providers/Microsoft.Network/virtualNetworks/vnet/subnets/aks-snet";

const size = (name: string, overrides: Partial<aksApi.NodePoolVmSize> = {}): aksApi.NodePoolVmSize => ({
  name,
  vcpus: 8,
  memory_gb: 32,
  zones: ["1", "2", "3"],
  ephemeral_os_disk: true,
  max_ephemeral_os_disk_gb: 200,
  spot: true,
  arch: "x64",
  family: "standardDSv3Family",
  ...overrides,
});

const OPTIONS: aksApi.NodePoolCreateOptions = {
  cluster_name: "uat-aks",
  location: "eastus2",
  power_state: "Running",
  control_plane_version: "1.36.3",
  kubernetes_versions: ["1.36.3"],
  network_plugin: "azure",
  network_plugin_mode: null,
  max_pods_limit: 250,
  windows_supported: true,
  existing_pools: ["attccuatnp1", "attccuatnp6"],
  total_nodes: 6,
  subnets: [{ id: SUBNET, name: "aks-snet", free_ips: 3895, total_ips: 4091, pools: ["attccuatnp1", "attccuatnp6"], pod_subnet: false }],
  vm_sizes: [
    size("Standard_D8s_v3"),
    size("Standard_D32s_v3", { vcpus: 32, memory_gb: 128, max_ephemeral_os_disk_gb: 800 }),
    size("Standard_D2_v2", { vcpus: 2, memory_gb: 7, zones: ["1"], spot: false, ephemeral_os_disk: false }),
  ],
  vm_sizes_error: null,
  zones: ["1", "2", "3"],
  defaults: { vm_size: "Standard_D8s_v3", max_pods: 30, max_surge: "33%", availability_zones: ["1", "2", "3"], os_disk_size_gb: 128 },
  inherited: { source_pool: "attccuatnp1", encryption_at_host: false, fips: false },
};

const valid = () => ({ ...defaultForm(OPTIONS), name: "attccuatnp7" });

describe("node pool form rules", () => {
  it("starts from the cluster's own conventions", () => {
    const form = defaultForm(OPTIONS);
    expect(form).toMatchObject({ version: "1.36.3", vmSize: "Standard_D8s_v3", maxPods: "30", surgeMode: "percent", surgeValue: "33", zones: ["1", "2", "3"], subnetId: SUBNET });
    expect(validateForm(valid(), OPTIONS)).toEqual({});
  });

  it.each([
    [{ name: "attccuatnp6" }, "name", "already has a node pool"],
    [{ name: "Pool-1" }, "name", "lowercase letters and digits"],
    [{ osType: "Windows", name: "winpool1" } as const, "name", "1–6"],
    [{ mode: "System", spot: true } as const, "spot", "User pools"],
    [{ vmSize: "Standard_D2_v2", osDiskType: "" } as const, "zones", "isn't offered in zone 2, 3"],
    [{ vmSize: "Standard_D32s_v3", osDiskType: "Ephemeral", osDiskSize: "1024" } as const, "osDiskSize", "at most 800 GiB"],
    [{ scaleMethod: "auto", minCount: "5", maxCount: "2" } as const, "maxCount", "at least the minimum"],
    [{ mode: "System", minCount: "0" } as const, "minCount", "Use 1–1000"],
    [{ maxPods: "300" }, "maxPods", "10–250"],
    [{ labels: [{ key: "kubernetes.azure.com/mode", value: "user" }] }, "labels", "reserved"],
    [{ taints: [{ key: "dedicated", value: "rules", effect: "" }] }, "taints", "choose an effect"],
    [{ tags: [{ key: "a/b", value: "x" }] }, "tags", "1–512 characters"],
    [{ maxPods: "250", minCount: "20" }, "subnetId", "the first 20 nodes need 5,020"],
  ])("rejects %o", (overrides, field, message) => {
    const errors = validateForm({ ...valid(), ...overrides } as any, { ...OPTIONS, subnets: [{ ...OPTIONS.subnets[0], free_ips: 4000 }] });
    expect(errors[field as keyof typeof errors]).toContain(message);
  });

  it("builds the request Azure needs", () => {
    const payload = toPayload(CLUSTER_ID, {
      ...valid(),
      vmSize: "Standard_D32s_v3",
      labels: [{ key: "nodepool", value: "ruleengine" }, { key: "", value: "" }],
      taints: [{ key: "dedicated", value: "rules", effect: "NoSchedule" }],
      tags: [{ key: "team", value: "attcc" }],
    });
    expect(payload).toMatchObject({
      cluster_id: CLUSTER_ID,
      name: "attccuatnp7",
      vm_size: "Standard_D32s_v3",
      enable_auto_scaling: true,
      min_count: 1,
      max_count: 5,
      node_count: null,
      max_surge: "33%",
      os_disk_type: null,
      node_labels: { nodepool: "ruleengine" },
      node_taints: ["dedicated=rules:NoSchedule"],
      tags: { team: "attcc" },
      subnet_id: SUBNET,
    });
  });
});

describe("CreateNodePoolDialog", () => {
  const mutate = vi.fn();
  beforeEach(() => {
    mutate.mockReset();
    (aksApi.useNodePoolCreateOptions as any).mockReturnValue({ data: OPTIONS, isLoading: false, isError: false });
    (aksApi.useCreateNodePool as any).mockReturnValue({ mutate, isPending: false, isError: false });
  });

  const renderDialog = () => render(<CreateNodePoolDialog clusterId={CLUSTER_ID} clusterName="uat-aks" onClose={vi.fn()} onCreated={vi.fn()} />);

  it("won't create until the problems are fixed", () => {
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "Review + create" }));
    expect(screen.getByText(/Fix 1 problem before creating/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Create" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.click(screen.getByRole("button", { name: "Go to Basics" }));
    fireEvent.change(screen.getByLabelText(/Node pool name/), { target: { value: "attccuatnp7" } });
    fireEvent.click(screen.getByRole("tab", { name: "Review + create" }));
    expect(screen.getByText(/Validation passed/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Create" }));

    expect(mutate.mock.calls[0][0]).toMatchObject({ name: "attccuatnp7", vm_size: "Standard_D8s_v3", min_count: 1, max_count: 5 });
  });

  it("picks a node size from the region's list", () => {
    renderDialog();

    fireEvent.click(screen.getByRole("button", { name: "Choose a size" }));
    fireEvent.change(screen.getByLabelText("Search VM sizes"), { target: { value: "d32s" } });
    const list = screen.getByRole("listbox", { name: "VM sizes" });
    fireEvent.click(within(list).getByRole("option", { name: /Standard D32s v3/ }));

    expect(screen.getByText("32 vCPUs, 128 GiB memory")).toBeTruthy();
    expect(screen.getByRole("option", { name: /Default \(based on selected VM: Ephemeral\)/ })).toBeTruthy();
  });

  it("offers the portal's disk sizes and leaves Default to Azure", () => {
    renderDialog();

    const disk = screen.getByLabelText(/OS disk size/) as HTMLSelectElement;
    expect(Array.from(disk.options).map((o) => o.text)).toEqual(["Default (based on selected VM)", "128", "256", "512", "1024", "2048"]);
    expect(toPayload(CLUSTER_ID, valid()).os_disk_size_gb).toBeNull();

    // An ephemeral OS disk must fit the size's cache or temp disk (200 GiB for D8s v3 here).
    fireEvent.change(screen.getByLabelText(/OS disk type/), { target: { value: "Ephemeral" } });
    const disabled = Array.from(disk.options).filter((o) => o.disabled).map((o) => o.text);
    expect(disabled).toEqual(["256", "512", "1024", "2048"]);
  });

  it("shows the subnet IPs a pool will need", () => {
    renderDialog();

    fireEvent.click(screen.getByRole("tab", { name: "Optional settings" }));

    // Classic Azure CNI: each node reserves max pods + 1 = 31 IPs.
    expect(screen.getByText(/Each node reserves 31 IPs \(max pods \+ 1\)\. Needs 31 IPs for the first 1 node and 155 at 5; 3,895 free\./)).toBeTruthy();
  });

  it("explains when the cluster's settings can't be read", () => {
    (aksApi.useNodePoolCreateOptions as any).mockReturnValue({ data: undefined, isLoading: false, isError: true, error: { response: { data: { detail: "Unable to read the cluster's node pool settings from Azure." } } } });
    renderDialog();

    expect(screen.getByText("Unable to read the cluster's node pool settings from Azure.")).toBeTruthy();
  });
});
