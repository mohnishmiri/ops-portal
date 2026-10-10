/**
 * Resource administration UI: one row per disk, Run Command's production
 * confirmation and output, tag editing, and the utilization panel.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("../../services/infraResourceAdminApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../services/infraResourceAdminApi")>();
  return Object.fromEntries(Object.entries(actual).map(([name, value]) => [name, name.startsWith("use") ? vi.fn() : value]));
});

import type { ManagedDisk, VMInfo } from "../../services/infraAlertApi";
import * as admin from "../../services/infraResourceAdminApi";
import { RunCommandPanel, TagEditor, UtilizationPanel, VMDisksGrid } from "./ResourceAdmin";

globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;

const hooks = admin as unknown as Record<string, ReturnType<typeof vi.fn>>;
const mutation = () => ({ mutate: vi.fn(), isPending: false });
const query = <T,>(data: T) => ({ data, isLoading: false, isError: false, error: null, isFetching: false });

const VM_ID = "/subscriptions/sub-1/resourceGroups/ATTCC-EASTUS2-PRF1-DB-RG/providers/Microsoft.Compute/virtualMachines/attcc-eastus2-prf1-db-vm-q7cud1d2";
const vm = {
  id: VM_ID,
  name: "attcc-eastus2-prf1-db-vm-q7cud1d2",
  location: "eastus2",
  resource_group: "ATTCC-EASTUS2-PRF1-DB-RG",
  vm_size: "Standard_D64ads_v5",
  power_state: "running",
  subscription_id: "sub-1",
  os_type: "Linux",
  os_disk_name: "attcc-eastus2-prf1-db-vm-q7cud1d2-os",
  os_disk_size_gb: 128,
  data_disks: [
    { name: "attcc-eastus2-prf1-db-data-q7cud1d2-u01", size_gb: 8192, lun: 0 },
    { name: "attcc-eastus2-prf1-db-data-q7cud1d2-u99", size_gb: 4096, lun: 2 },
    { name: "attcc-eastus2-prf1-db-data-q7cud1d2-u02", size_gb: 8192, lun: 1 },
  ],
} as unknown as VMInfo & Record<string, unknown>;

const disk = (name: string, size: number, extra: Record<string, unknown> = {}) =>
  ({ id: `/subscriptions/sub-1/resourceGroups/RG/providers/Microsoft.Compute/disks/${name}`, name, size_gb: size, sku: "PremiumV2_LRS", managed_by: VM_ID, disk_state: "Attached", disk_iops_read_write: 3000, disk_mbps_read_write: 125, ...extra }) as unknown as ManagedDisk & Record<string, unknown>;

beforeEach(() => {
  for (const [name, fn] of Object.entries(hooks)) {
    if (!name.startsWith("use")) continue;
    if (/^use(Start|Resize|Redeploy|Replace|Snapshot|Expand)/.test(name)) fn.mockReturnValue(mutation());
    else fn.mockReturnValue(query(undefined));
  }
});

describe("VMDisksGrid", () => {
  it("lists the OS disk first, then data disks by LUN, one per row", () => {
    const onOpen = vi.fn();
    render(<VMDisksGrid vm={vm} disks={[disk("attcc-eastus2-prf1-db-data-q7cud1d2-u02", 8192)]} onOpenDisk={onOpen} />);
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell")[0].textContent)).toEqual(["OS disk", "Data · LUN 0", "Data · LUN 1", "Data · LUN 2"]);
    expect(screen.getByText(/4 attached · 20,608 GB total/)).toBeTruthy();
    // Joined with the disk inventory where it is synced.
    expect(within(rows[2]).getByText("PremiumV2_LRS")).toBeTruthy();
    fireEvent.click(within(rows[2]).getByRole("button", { name: "attcc-eastus2-prf1-db-data-q7cud1d2-u02" }));
    expect(onOpen).toHaveBeenCalled();
  });
});

describe("RunCommandPanel", () => {
  it("on a production VM, runs only after the VM name is typed", () => {
    const start = mutation();
    hooks.useStartRunCommand.mockReturnValue(start);
    hooks.useRunCommandHistory.mockReturnValue(query([]));
    render(<RunCommandPanel vm={vm} tier="prod" formatDate={(v) => v} />);

    fireEvent.click(screen.getByRole("button", { name: "Disk usage" }));
    expect((screen.getByLabelText("Command") as HTMLTextAreaElement).value).toBe("df -hT -x tmpfs -x devtmpfs");
    const run = screen.getByRole("button", { name: /Run command/ }) as HTMLButtonElement;
    expect(run.disabled).toBe(true);

    fireEvent.change(screen.getByPlaceholderText(vm.name), { target: { value: vm.name } });
    expect(run.disabled).toBe(false);
    fireEvent.click(run);
    expect(start.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ subscription_id: "sub-1", vm_name: vm.name, script: "df -hT -x tmpfs -x devtmpfs", confirm_name: vm.name, timeout_seconds: 300 }),
      expect.anything(),
    );
  });

  it("does not ask non-production VMs for the name, and shows a finished run's output", () => {
    hooks.useRunCommandHistory.mockReturnValue(
      query([{ id: 1, run_id: "opsportal-1", requested_at: "2026-10-11T02:00:00", requested_by: "ops@att.com", status: "success", state: "Succeeded", exit_code: 0, script: "uptime", output: " 02:00 up 9 days", error: "", started_at: null, finished_at: null }]),
    );
    render(<RunCommandPanel vm={vm} tier="nonprod" formatDate={(v) => v} />);
    expect(screen.queryByPlaceholderText(vm.name)).toBeNull();
    fireEvent.click(screen.getByText("uptime").closest("tr") as HTMLElement);
    expect(screen.getByText("02:00 up 9 days", { exact: false })).toBeTruthy();
    expect(screen.getByText(/Succeeded · exit 0/)).toBeTruthy();
  });

  it("explains that a stopped VM cannot run commands", () => {
    hooks.useRunCommandHistory.mockReturnValue(query([]));
    render(<RunCommandPanel vm={{ ...vm, power_state: "deallocated" }} tier="nonprod" formatDate={(v) => v} />);
    expect(screen.getByText(/This VM is deallocated — start it to run commands/)).toBeTruthy();
  });
});

describe("TagEditor", () => {
  it("edits tags, refuses duplicate names, and saves the full set", () => {
    const save = mutation();
    hooks.useReplaceTags.mockReturnValue(save);
    render(<TagEditor resourceId={VM_ID} resourceType="virtual_machine" tags={{ env: "prf1", owner: "dba" }} canEdit onToast={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Edit tags/ }));
    fireEvent.click(screen.getByRole("button", { name: "+ Add tag" }));
    const inputs = screen.getAllByRole("textbox").filter((el) => el.getAttribute("placeholder") !== "Filter tags…");
    fireEvent.change(inputs[4], { target: { value: "ENV" } });
    expect(screen.getByText(/appears twice/)).toBeTruthy();
    expect((screen.getByRole("button", { name: /Save tags/ }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(inputs[4], { target: { value: "cost-center" } });
    fireEvent.change(inputs[5], { target: { value: "31599" } });
    fireEvent.click(screen.getByRole("button", { name: /Save tags/ }));
    expect(save.mutate).toHaveBeenCalledWith(
      { resource_id: VM_ID, resource_type: "virtual_machine", tags: { env: "prf1", owner: "dba", "cost-center": "31599" } },
      expect.anything(),
    );
  });

  it("is read-only without the admin permission", () => {
    render(<TagEditor resourceId={VM_ID} resourceType="virtual_machine" tags={{ env: "prf1" }} canEdit={false} onToast={vi.fn()} />);
    expect(screen.queryByRole("button", { name: /Edit tags/ })).toBeNull();
    expect(screen.getByText("prf1")).toBeTruthy();
  });
});

describe("UtilizationPanel", () => {
  it("shows now / average / peak and asks for a new range when one is picked", () => {
    hooks.useMetricsHistory.mockReturnValue(
      query({
        kind: "vm",
        hours: 24,
        interval: "PT15M",
        points: [{ time: "2026-10-11T01:00:00+00:00", cpu: 40, cpu_max: 70, memory: 30 }],
        summary: { cpu: { average: 40, peak: 70, latest: 40 }, memory: { average: 30, peak: 30, latest: 30 }, disk: { average: null, peak: null, latest: null } },
      }),
    );
    render(<UtilizationPanel kind="vm" subscriptionId="sub-1" resourceGroup="RG" name="vm" formatDate={(v) => v} />);
    expect(screen.getByText("peak 70%")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "7d" }));
    expect(hooks.useMetricsHistory).toHaveBeenLastCalledWith("vm", "sub-1", "RG", "vm", 168);
    fireEvent.click(screen.getByRole("button", { name: "Table" }));
    expect(screen.getByText("Readings")).toBeTruthy();
  });
});
