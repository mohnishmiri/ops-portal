/**
 * Infrastructure Alerts: expiry maths, the recipients box, the expiry editor's
 * validation and preview, and the alert detail view's actions.
 */

import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));

const mutation = () => ({ mutate: vi.fn(), isPending: false });
const query = <T,>(data: T) => ({ data, isLoading: false, isError: false, error: null });

vi.mock("../../services/infraAlertApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../services/infraAlertApi")>();
  const hooks = [
    "useExpiryConfigs",
    "useExpiryAlerts",
    "useVMThresholdAlerts",
    "usePGFlexAlerts",
    "useVMThresholdConfigs",
    "usePGFlexConfigs",
    "useStorageAlertConfigs",
    "useAzureVMs",
    "useAzurePGServers",
    "useAzureStorageAccounts",
    "useAzureDisks",
    "useAlertScheduleConfigs",
    "useNotificationHistory",
    "useAlertNotifications",
    "useVMMetrics",
    "usePGMetrics",
    "useCreateExpiryConfig",
    "useUpdateExpiryConfig",
    "useAcknowledgeVMAlert",
    "useAcknowledgePGFlexAlert",
    "useAcknowledgeExpiryAlert",
    "useResolveVMAlert",
    "useResolvePGFlexAlert",
    "useResolveExpiryAlert",
    "useUpdateVMThresholdConfig",
    "useUpdatePGFlexConfig",
    "useUpdateStorageAlertConfig",
    "useUpdateAlertScheduleConfig",
  ];
  return { ...actual, ...Object.fromEntries(hooks.map((name) => [name, vi.fn()])) };
});

vi.mock("../../services/infraResourceAdminApi", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../services/infraResourceAdminApi")>();
  return Object.fromEntries(
    Object.entries(actual).map(([name, value]) => [
      name,
      name.startsWith("use") ? vi.fn(() => ({ data: undefined, isLoading: false, isError: false, mutate: vi.fn(), isPending: false })) : value,
    ]),
  );
});

import * as api from "../../services/infraAlertApi";
import { EmailChipsInput, ExpiryConfigEditor } from "./ConfigEditors";
import { InfraAlertDetailHost, type DetailHostProps } from "./DetailViews";
import { addDays, daysLeftText, daysUntil, describeSchedule, expiryHealth, todayIso } from "./shared";

const mocked = api as unknown as Record<string, ReturnType<typeof vi.fn>>;

function resetHooks({ expiryConfigs = [] as api.ExpiryConfig[], vmAlerts = [] as api.VMThresholdAlert[], vmConfigs = [] as api.VMThresholdConfig[] } = {}) {
  for (const [name, fn] of Object.entries(mocked)) {
    if (typeof fn !== "function" || !("mockReturnValue" in fn)) continue;
    if (/^use(Create|Update|Acknowledge|Resolve)/.test(name)) fn.mockReturnValue(mutation());
    else fn.mockReturnValue(query(/Azure/.test(name) ? { resources: [], source: "db", last_sync: null, count: 0 } : []));
  }
  mocked.useExpiryConfigs.mockReturnValue(query(expiryConfigs));
  mocked.useVMThresholdAlerts.mockReturnValue(query(vmAlerts));
  mocked.useVMThresholdConfigs.mockReturnValue(query(vmConfigs));
  mocked.useVMMetrics.mockReturnValue(query({ cpu: 91.2, memory: 40, disk: 3, collected_at: "2026-10-11T01:00:00" }));
}

describe("expiry maths", () => {
  it("counts calendar days, so tomorrow is 1 day left even late tonight", () => {
    const lateTonight = new Date(2026, 9, 11, 23, 59);
    expect(daysUntil("2026-10-12T00:00:00", lateTonight)).toBe(1);
    expect(daysUntil("2026-10-11", lateTonight)).toBe(0);
    expect(daysUntil("2026-06-28T00:00:00", lateTonight)).toBe(-105);
  });

  it("classifies the window and words it plainly", () => {
    expect(expiryHealth(45, 30, 7)).toBe("ok");
    expect(expiryHealth(30, 30, 7)).toBe("warning");
    expect(expiryHealth(7, 30, 7)).toBe("critical");
    expect(expiryHealth(-1, 30, 7)).toBe("expired");
    expect(daysLeftText(-105)).toBe("Expired 105 days ago");
    expect(daysLeftText(0)).toBe("Expires today");
    expect(daysLeftText(1)).toBe("1 day left");
  });

  it("describes schedules in words", () => {
    expect(describeSchedule("interval", 15, null)).toBe("Every 15 min");
    expect(describeSchedule("interval", 1440, null)).toBe("Every 1 day");
    expect(describeSchedule("cron", 1440, "0 8 * * *")).toBe("Daily at 08:00 UTC");
    expect(describeSchedule("cron", 1440, "30 6 * * 1-5")).toBe("Weekdays at 06:30 UTC");
  });
});

describe("EmailChipsInput", () => {
  function Harness({ onSubmit }: { onSubmit: () => void }) {
    const [value, setValue] = React.useState<string[]>(["ops@att.com"]);
    return (
      <form onSubmit={(e) => (e.preventDefault(), onSubmit())}>
        <EmailChipsInput value={value} onChange={setValue} />
        <output data-testid="value">{value.join("|")}</output>
      </form>
    );
  }

  it("adds valid addresses, refuses invalid and duplicate ones, and never submits the form", () => {
    const onSubmit = vi.fn();
    render(<Harness onSubmit={onSubmit} />);
    const input = screen.getByLabelText("Notification recipients");

    fireEvent.change(input, { target: { value: "not-an-email" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByText(/Not a valid email: not-an-email/)).toBeTruthy();

    fireEvent.change(input, { target: { value: "OPS@att.com, lead@att.com" } });
    fireEvent.keyDown(input, { key: "Enter" });
    expect(screen.getByTestId("value").textContent).toBe("ops@att.com|lead@att.com");

    fireEvent.keyDown(input, { key: "Enter" });
    expect(onSubmit).not.toHaveBeenCalled();
  });
});

describe("ExpiryConfigEditor", () => {
  beforeEach(() => resetHooks());

  const props = { subscriptionNames: new Map<string, string>(), formatDate: (v: string) => v, onClose: vi.fn(), onSaved: vi.fn() };

  it("previews that saving an item due in 5 days raises a critical alert, then creates it", () => {
    const create = mutation();
    mocked.useCreateExpiryConfig.mockReturnValue(create);
    render(<ExpiryConfigEditor config={null} {...props} />);

    fireEvent.change(screen.getByPlaceholderText("m52142"), { target: { value: "m52142" } });
    // The domain account identifier mirrors the name until edited.
    expect((screen.getByPlaceholderText("ITSERVICES\\m52142") as HTMLInputElement).value).toBe("m52142");
    fireEvent.change(screen.getByLabelText(/Expiry date/), { target: { value: addDays(todayIso(), 5) } });

    expect(screen.getByText(/saving raises a critical alert now/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Start tracking" }));
    expect(create.mutate).toHaveBeenCalledWith(
      expect.objectContaining({ alert_type: "itservices_domain", resource_identifier: "m52142", warning_days_before: 30, critical_days_before: 7 }),
      expect.anything(),
    );
  });

  it("blocks a duplicate identifier and critical days that are not below warning", () => {
    resetHooks({
      expiryConfigs: [
        { id: 4, alert_type: "itservices_domain", resource_name: "m52142", resource_identifier: "M52142" } as api.ExpiryConfig,
      ],
    });
    render(<ExpiryConfigEditor config={null} {...props} />);
    fireEvent.change(screen.getByPlaceholderText("m52142"), { target: { value: "m52142" } });
    fireEvent.change(screen.getByLabelText(/Expiry date/), { target: { value: addDays(todayIso(), 90) } });

    expect(screen.getByText(/Already tracked as/)).toBeTruthy();
    expect((screen.getByRole("button", { name: "Start tracking" }) as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(screen.getByLabelText(/Critical — days before/), { target: { value: "30" } });
    expect(screen.getByText(/fewer days than warning/)).toBeTruthy();
  });
});

describe("InfraAlertDetailHost", () => {
  const vmAlert: api.VMThresholdAlert = {
    id: 12,
    config_id: 3,
    vm_id: "/subscriptions/sub-2/resourceGroups/RG/providers/Microsoft.Compute/virtualMachines/prd-vm",
    vm_name: "prd-vm",
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
  const vmConfig = {
    id: 3,
    subscription_id: "sub-2",
    resource_group: "RG",
    vm_name: "prd-vm",
    vm_id: vmAlert.vm_id,
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
  } as api.VMThresholdConfig;

  const hostProps = (overrides: Partial<DetailHostProps> = {}): DetailHostProps => ({
    target: { kind: "vm-alert", id: 12 },
    onOpen: vi.fn(),
    onClose: vi.fn(),
    onEditConfig: vi.fn(),
    onEditSchedule: vi.fn(),
    onDeleteConfig: vi.fn(),
    onDeleteSchedule: vi.fn(),
    onPower: vi.fn(),
    powerPendingKey: null,
    onToast: vi.fn(),
    onConfirm: vi.fn(),
    onDeleteDisk: vi.fn(),
    canWrite: true,
    canPowerVM: true,
    canPowerPG: true,
    canRunCommand: true,
    canAdminResources: true,
    canDeleteDisks: true,
    subscriptionNames: new Map([["sub-2", "ACC-PRD"]]),
    subscriptionTiers: new Map([["sub-2", "prod" as const]]),
    formatDate: (v: string) => v,
    ...overrides,
  });

  it("shows the reading, live metrics and lets a writer acknowledge", () => {
    resetHooks({ vmAlerts: [vmAlert], vmConfigs: [vmConfig] });
    const ack = mutation();
    mocked.useAcknowledgeVMAlert.mockReturnValue(ack);
    render(<InfraAlertDetailHost {...hostProps()} />);

    expect(screen.getByRole("heading", { name: "prd-vm" })).toBeTruthy();
    expect(screen.getAllByText("93.4%").length).toBeGreaterThan(0);
    expect(screen.getByText("Live metrics")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Acknowledge/ }));
    expect(ack.mutate).toHaveBeenCalledWith(12, expect.anything());
  });

  it("is read-only for readers and links to the configuration", () => {
    resetHooks({ vmAlerts: [vmAlert], vmConfigs: [vmConfig] });
    const props = hostProps({ canWrite: false });
    render(<InfraAlertDetailHost {...props} />);

    expect(screen.queryByRole("button", { name: /Acknowledge/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Resolve/ })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: /Configuration/ }));
    expect(props.onOpen).toHaveBeenCalledWith({ kind: "vm-config", id: 3 });
  });

  it("explains an alert whose row is gone instead of rendering a blank view", () => {
    resetHooks();
    render(<InfraAlertDetailHost {...hostProps({ target: { kind: "expiry-alert", id: 404 } })} />);
    expect(screen.getByText(/no longer exists, or it is outside your subscription scope/)).toBeTruthy();
  });
});
