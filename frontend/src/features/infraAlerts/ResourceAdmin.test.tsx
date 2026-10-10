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
import { PGDatabasesPanel, RunCommandPanel, TagEditor, UtilizationPanel, VMDisksGrid } from "./ResourceAdmin";
import { formatBytes } from "./shared";
import type { PGFlexServer } from "../../services/infraAlertApi";

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
    expect(screen.getByText(/Disks · 20,608 GB total/)).toBeTruthy();
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

describe("PGDatabasesPanel", () => {
  const server = { id: "pg-1", name: "attcc-eastus2-prf1-db-psqlfs", resource_group: "rg", subscription_id: "sub-1", state: "Ready" } as unknown as PGFlexServer;

  it("lists databases largest first with size, share and 7-day growth, plus server storage", () => {
    hooks.usePGOverview.mockReturnValue(
      query({
        databases: [
          { name: "postgres", charset: "UTF8", collation: "en_US.utf8", size_bytes: 7_978_007, size_7d_ago_bytes: 7_978_007, size_at: "2026-10-10T21:29:00+00:00" },
          { name: "opsportal", charset: "UTF8", collation: "en_US.utf8", size_bytes: 7_800_912_919, size_7d_ago_bytes: 7_103_998_999, size_at: "2026-10-10T21:29:00+00:00" },
          { name: "azure_sys", charset: "UTF8", collation: "en_US.utf8", size_bytes: 8_436_759, size_7d_ago_bytes: 8_436_759 },
          { name: "newdb", charset: "UTF8", collation: "en_US.utf8" },
        ],
        firewall_rules: [{ name: "AllowAllAzureServicesAndResourcesWithinAzureIps", start_ip: "0.0.0.0", end_ip: "0.0.0.0" }],
        storage: { provisioned_gb: 32, used_bytes: 13_926_389_623, free_bytes: 19_575_367_816, percent: 41.57, backup_bytes: 85_138_174_902, txlogs_bytes: 603_979_776, databases_total_bytes: 7_817_327_685 },
        size_error: null,
      }),
    );
    render(<PGDatabasesPanel server={server} formatDate={(v) => v} />);

    expect(screen.getByText(/13.0 GB used of 32 GB provisioned/)).toBeTruthy();
    expect(screen.getByText("41.6%")).toBeTruthy();
    const dbGrid = screen.getByText(/^Databases ·/).closest("section, div.overflow-hidden") ?? document.body;
    const rows = within(dbGrid as HTMLElement).getAllByRole("row").slice(1);
    expect(rows.map((r) => within(r).getAllByRole("cell")[0].textContent)).toEqual(["opsportal", "azure_sysAzure system", "postgresDefault", "newdb"]);
    expect(within(rows[0]).getByText("7.3 GB")).toBeTruthy();
    expect(within(rows[0]).getByText("+665 MB (+9.8%)")).toBeTruthy();
    expect(within(rows[2]).getByText("no change")).toBeTruthy();
    expect(within(rows[3]).getAllByText("—").length).toBeGreaterThan(0);
    expect(screen.getByText(/allows Azure services/)).toBeTruthy();
  });

  it("still lists databases when sizes cannot be read", () => {
    hooks.usePGOverview.mockReturnValue(
      query({ databases: [{ name: "appdb", charset: "UTF8", collation: "C" }], firewall_rules: [], storage: undefined, size_error: "AuthorizationFailed" }),
    );
    render(<PGDatabasesPanel server={server} formatDate={(v) => v} />);
    expect(screen.getByText(/Database sizes could not be read from Azure Monitor: AuthorizationFailed/)).toBeTruthy();
    expect(screen.getByText("appdb")).toBeTruthy();
  });
});

describe("formatBytes", () => {
  it("uses binary units like Azure and PostgreSQL", () => {
    expect(formatBytes(7_800_912_919)).toBe("7.3 GB");
    expect(formatBytes(679_017_495)).toBe("648 MB");
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(null)).toBe("—");
  });
});
