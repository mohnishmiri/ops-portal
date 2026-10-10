/**
 * InfraAlertPage smoke test: every tab renders with realistic data, grid rows
 * open their detail view, deletes and stop/restart ask first, power actions
 * carry the resource's own subscription, and email deep links open the alert.
 */

import { fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";
import { MemoryRouter } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("../contexts/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("../contexts/PermissionsContext", () => ({ usePermissions: vi.fn() }));
vi.mock("../contexts/SubscriptionContext", () => ({ useSubscriptionScope: vi.fn() }));
vi.mock("../contexts/TimezoneContext", () => ({ usePortalTimezone: vi.fn() }));
vi.mock("../services/costApi", () => ({ useAdminSubscriptions: vi.fn(), useDeleteUnattachedDisk: vi.fn() }));
vi.mock("../services/infraAlertApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../services/infraAlertApi")>();
  return Object.fromEntries(Object.entries(actual).map(([name, value]) => [name, name.startsWith("use") ? vi.fn() : value]));
});

import { useAuth } from "../contexts/AuthContext";
import { usePermissions } from "../contexts/PermissionsContext";
import { useSubscriptionScope } from "../contexts/SubscriptionContext";
import { usePortalTimezone } from "../contexts/TimezoneContext";
import * as costApi from "../services/costApi";
import * as api from "../services/infraAlertApi";
import InfraAlertPage from "./InfraAlertPage";

const hooks = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

// Recharts' ResponsiveContainer needs ResizeObserver, which jsdom lacks.
globalThis.ResizeObserver ??= class {
  observe() {}
  unobserve() {}
  disconnect() {}
} as unknown as typeof ResizeObserver;
const mutation = () => ({ mutate: vi.fn(), mutateAsync: vi.fn(), isPending: false });
const query = <T,>(data: T) => ({ data, isLoading: false, isError: false, error: null });

const SUB_NPRD = "d1516897-0000-0000-0000-000000000000";
const SUB_PRD = "169cc835-0000-0000-0000-000000000000";
const VM_ID = `/subscriptions/${SUB_PRD}/resourceGroups/ATTCC-EASTUS2-PRD1-DB-RG/providers/Microsoft.Compute/virtualMachines/attcc-eastus2-prd1-db-vm-p7cud1d4`;

const vmConfig = {
  id: 3,
  subscription_id: SUB_PRD,
  resource_group: "ATTCC-EASTUS2-PRD1-DB-RG",
  vm_name: "attcc-eastus2-prd1-db-vm-p7cud1d4",
  vm_id: VM_ID,
  cpu_warning_threshold: 70,
  cpu_critical_threshold: 90,
  memory_warning_threshold: 75,
  memory_critical_threshold: 90,
  disk_warning_threshold: 80,
  disk_critical_threshold: 95,
  is_enabled: true,
  notification_emails: ["ops@att.com"],
  snooze_until: null,
  created_at: "2026-10-01T00:00:00",
  created_by: "lead@att.com",
};
const vmAlert = {
  id: 12,
  config_id: 3,
  vm_id: VM_ID,
  vm_name: vmConfig.vm_name,
  metric_type: "cpu",
  current_value: 93.4,
  threshold_value: 90,
  severity: "critical",
  status: "active",
  created_at: "2026-10-10T20:00:00",
  updated_at: "2026-10-10T21:00:00",
  acknowledged_by: null,
  acknowledged_at: null,
  resolved_at: null,
};
const expiryConfig = {
  id: 7,
  alert_type: "itservices_domain",
  resource_name: "m52142",
  resource_identifier: "m52142",
  description: null,
  environment: "non_prod",
  expiry_date: "2026-06-28T00:00:00",
  days_until_expiry: -105,
  warning_days_before: 30,
  critical_days_before: 7,
  is_enabled: true,
  notification_emails: [],
  snooze_until: null,
  metadata: {},
  created_at: "2026-06-01T00:00:00",
  created_by: "lead@att.com",
};
const expiryAlert = {
  id: 7,
  config_id: 7,
  alert_type: "itservices_domain",
  resource_name: "m52142",
  expiry_date: "2026-06-28T00:00:00",
  days_until_expiry: -105,
  severity: "critical",
  status: "active",
  created_at: "2026-06-21T00:00:00",
  updated_at: "2026-10-10T00:00:00",
  acknowledged_by: null,
  acknowledged_at: null,
  resolved_at: null,
};
const vm = {
  id: VM_ID,
  name: vmConfig.vm_name,
  location: "eastus2",
  resource_group: vmConfig.resource_group,
  vm_size: "Standard_E96ds_v5",
  power_state: "running",
  subscription_id: SUB_PRD,
  tags: { env: "prd1" },
};
const schedule = {
  id: 1,
  name: "Infra Alert Checks",
  description: null,
  schedule_type: "interval",
  interval_minutes: 15,
  cron_expression: null,
  check_vm_thresholds: true,
  check_storage_thresholds: false,
  check_disk_thresholds: false,
  check_expiry_alerts: true,
  check_pg_thresholds: true,
  send_daily_digest: false,
  digest_time_utc: "08:00",
  digest_recipients: [],
  is_enabled: true,
  last_run_at: "2026-10-10T21:00:00",
  next_run_at: "2026-10-10T21:15:00",
  created_at: "2026-10-01T00:00:00",
  updated_at: null,
  created_by: "system-auto-seed",
};
const notification = {
  id: 55,
  alert_type: "custom_expiry",
  notification_type: "custom_expiry",
  recipient_email: "ops@att.com",
  subject: "[EXPIRED] ITServices Domain Account: m52142 has expired!",
  status: "failed",
  error_message: "SMTP connection refused",
  alert_id: 7,
  sent_at: "2026-10-10T08:00:00",
};

function setup() {
  for (const [name, fn] of Object.entries(hooks)) {
    if (!name.startsWith("use")) continue;
    if (/^use(Create|Update|Delete|Acknowledge|Resolve|Check|Trigger|Sync|Start|Stop|Restart|Send)/.test(name)) fn.mockReturnValue(mutation());
    else fn.mockReturnValue(query([]));
  }
  const resources = <T,>(rows: T[]) => query({ source: "db", last_sync: "2026-10-10T18:53:33", count: rows.length, resources: rows });
  hooks.useAlertSummary.mockReturnValue(
    query({
      vm_threshold_alerts: { by_status: { active: 1 }, by_severity: { critical: 1 }, total: 1, active: 1 },
      expiry_alerts: { by_status: { active: 1, acknowledged: 3, resolved: 6 }, by_type: {}, total: 10, active: 1 },
      pg_flex_alerts: { by_status: {}, by_severity: {}, total: 0, active: 0 },
      total_active_alerts: 2,
      total_open_alerts: 5,
      last_updated: "2026-10-10T21:00:00",
    }),
  );
  hooks.useVMThresholdAlerts.mockReturnValue(query([vmAlert]));
  hooks.useVMThresholdConfigs.mockReturnValue(query([vmConfig]));
  hooks.useExpiryAlerts.mockReturnValue(query([expiryAlert]));
  hooks.useExpiryConfigs.mockReturnValue(query([expiryConfig]));
  hooks.useAzureVMs.mockReturnValue(resources([vm]));
  hooks.useAzureStorageAccounts.mockReturnValue(resources([]));
  hooks.useAzureDisks.mockReturnValue(resources([]));
  hooks.useAzurePGServers.mockReturnValue(resources([]));
  hooks.useAlertScheduleConfigs.mockReturnValue(query([schedule]));
  hooks.useNotificationHistory.mockReturnValue(query([notification]));
  hooks.useSchedulerStatus.mockReturnValue(query({ scheduler_running: true, jobs: [], job_count: 0 }));
  hooks.useResourceInventorySummary.mockReturnValue(query({ total_resources: 1, by_type: {}, by_location: {}, by_subscription: {} }));
  hooks.useVMMetrics.mockReturnValue(query({ cpu: 93.4, memory: 61, disk: 4, collected_at: "2026-10-10T21:00:00" }));

  vi.mocked(useAuth).mockReturnValue({ canWrite: true, email: "lead@att.com" } as ReturnType<typeof useAuth>);
  vi.mocked(usePermissions).mockReturnValue({ hasCapability: () => true } as unknown as ReturnType<typeof usePermissions>);
  vi.mocked(useSubscriptionScope).mockReturnValue({
    availableSubscriptions: [
      { subscription_id: SUB_NPRD, subscription_name: "ACC-NPRD" },
      { subscription_id: SUB_PRD, subscription_name: "ACC-PRD" },
    ],
    effectiveSubscriptionIds: [SUB_NPRD, SUB_PRD],
  } as unknown as ReturnType<typeof useSubscriptionScope>);
  vi.mocked(usePortalTimezone).mockReturnValue({ timezone: "UTC", formatDate: (v: unknown) => String(v ?? "—"), formatShortDate: (v: unknown) => String(v ?? "—") } as unknown as ReturnType<typeof usePortalTimezone>);
  vi.mocked(costApi.useAdminSubscriptions).mockReturnValue(
    query([
      { subscription_id: SUB_NPRD, subscription_name: "ACC-NPRD" },
      { subscription_id: SUB_PRD, subscription_name: "ACC-PRD" },
    ]) as unknown as ReturnType<typeof costApi.useAdminSubscriptions>,
  );
  vi.mocked(costApi.useDeleteUnattachedDisk).mockReturnValue(mutation() as unknown as ReturnType<typeof costApi.useDeleteUnattachedDisk>);
}

const renderPage = (url = "/infra-alerts") =>
  render(
    <MemoryRouter initialEntries={[url]}>
      <InfraAlertPage />
    </MemoryRouter>,
  );

const tab = (label: string) => fireEvent.click(screen.getByRole("button", { name: new RegExp(`^${label}$`) }));

describe("InfraAlertPage", () => {
  beforeEach(setup);

  it("dashboard says an expired account is expired and opens it on click", () => {
    renderPage();
    // Previously "Expires: 6/28/2026" for something 105 days past expiry.
    const item = screen.getByText("m52142").closest("button") as HTMLElement;
    expect(within(item).getByText(/Expired 105 days ago/)).toBeTruthy();
    fireEvent.click(item);
    expect(screen.getByRole("dialog")).toBeTruthy();
    expect(screen.getByText(/expired 105 days ago\./)).toBeTruthy();
    expect(screen.getByRole("button", { name: /Renewed\? Update date/ })).toBeTruthy();
  });

  it("renders every tab and opens a detail from each grid", () => {
    renderPage();
    tab("VM Alerts");
    fireEvent.click(screen.getAllByText(vmConfig.vm_name)[0].closest("tr") as HTMLElement);
    expect(screen.getByText("VM threshold alert")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    tab("PG Alerts");
    expect(screen.getByText(/No PostgreSQL Flexible Server alerts found/)).toBeTruthy();

    tab("Expiry Alerts");
    fireEvent.click(screen.getByText("Expired 105 days ago").closest("tr") as HTMLElement);
    expect(screen.getByText("ITServices Domain Expiry alert")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    tab("Resources");
    fireEvent.click(screen.getByText("Standard_E96ds_v5").closest("tr") as HTMLElement);
    expect(screen.getByText("Virtual machine")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));

    tab("Scheduler");
    fireEvent.click(screen.getByText("Infra Alert Checks").closest("tr") as HTMLElement);
    expect(screen.getByText("Alert schedule")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByText("ops@att.com").closest("tr") as HTMLElement);
    expect(screen.getByText("SMTP connection refused")).toBeTruthy();
  });

  it("configuration: editors open, and deleting asks before it deletes", () => {
    const deleteVm = mutation();
    hooks.useDeleteVMThresholdConfig.mockReturnValue(deleteVm);
    renderPage("/infra-alerts?tab=configs");
    fireEvent.click(screen.getByRole("button", { name: /Track Expiry/ }));
    expect(screen.getByText("Track an expiry date")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    fireEvent.click(screen.getByRole("button", { name: `Delete ${vmConfig.vm_name}` }));
    expect(screen.getByText("Delete VM threshold configuration?")).toBeTruthy();
    expect(deleteVm.mutate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(deleteVm.mutate).toHaveBeenCalledWith(3, expect.anything());
  });

  it("stopping a VM confirms first and targets the VM's own subscription", () => {
    const stopVm = mutation();
    hooks.useStopVM.mockReturnValue(stopVm);
    renderPage("/infra-alerts?tab=resources");
    fireEvent.click(screen.getByRole("button", { name: "Stop (deallocate) VM" }));
    expect(screen.getByText(/will be deallocated/)).toBeTruthy();
    expect(stopVm.mutate).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(stopVm.mutate).toHaveBeenCalledWith(
      { resource_group: vm.resource_group, vm_name: vm.name, subscription_id: SUB_PRD },
      expect.anything(),
    );
  });

  it("opens the alert an email links to", () => {
    renderPage("/infra-alerts?alert=expiry-7");
    expect(screen.getByText("ITServices Domain Expiry alert")).toBeTruthy();
  });
});
