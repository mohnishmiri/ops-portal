/**
 * Tests for the subscription scope picker's Project → App grouping.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent, within } from "@testing-library/react";
import React from "react";

vi.mock("../contexts/SubscriptionContext", () => ({ useSubscriptionScope: vi.fn() }));

import { useSubscriptionScope, type AvailableSubscription } from "../contexts/SubscriptionContext";
import SubscriptionScopePicker, { groupSubscriptions } from "./SubscriptionScopePicker";

const sub = (overrides: Partial<AvailableSubscription>): AvailableSubscription => ({
  subscription_id: "s",
  subscription_name: "sub",
  environment: null,
  tier: null,
  app_id: null,
  app_name: null,
  app_code: null,
  project_id: null,
  project_name: null,
  ...overrides,
});

const SUBS: AvailableSubscription[] = [
  sub({ subscription_id: "a", subscription_name: "ACC-NPRD-31599-ATTCC", tier: "nonprod", app_id: 10, app_name: "ATTCC", app_code: "31599", project_id: 1, project_name: "Commissions" }),
  sub({ subscription_id: "b", subscription_name: "ACC-PROD-31599-ATTCC", tier: "prod", app_id: 10, app_name: "ATTCC", app_code: "31599", project_id: 1, project_name: "Commissions" }),
  sub({ subscription_id: "c", subscription_name: "ACC-PROD-17805-DWS", tier: "prod", app_id: 11, app_name: "DWS", app_code: "17805", project_id: 1, project_name: "Commissions" }),
  sub({ subscription_id: "d", subscription_name: "Legacy Sandbox", environment: "dev" }),
];

describe("groupSubscriptions", () => {
  it("groups by project then app, Prod before Non-Prod", () => {
    const { projects, ungrouped } = groupSubscriptions(SUBS);
    expect(projects).toHaveLength(1);
    expect(projects[0].label).toBe("Commissions");
    expect(projects[0].apps.map((app) => app.label)).toEqual(["ATTCC", "DWS"]);
    expect(projects[0].apps[0].subscriptions.map((s) => s.subscription_id)).toEqual(["b", "a"]);
    expect(ungrouped.map((s) => s.subscription_id)).toEqual(["d"]);
  });

  it("leaves everything ungrouped when nothing is placed", () => {
    const { projects, ungrouped } = groupSubscriptions([SUBS[3]]);
    expect(projects).toEqual([]);
    expect(ungrouped).toHaveLength(1);
  });
});

describe("SubscriptionScopePicker", () => {
  it("renders project and app headings with a tier badge per subscription", () => {
    vi.mocked(useSubscriptionScope).mockReturnValue({
      availableSubscriptions: SUBS,
      selectedSubscriptionIds: [],
      effectiveSubscriptionIds: SUBS.map((s) => s.subscription_id),
      isLoading: false,
      isAllSelected: true,
      scopeLabel: "All available (4)",
      setSelectedSubscriptionIds: vi.fn(),
      selectAllSubscriptions: vi.fn(),
      refreshScope: vi.fn(),
    });
    render(<SubscriptionScopePicker />);
    fireEvent.click(screen.getByTitle(/filter portal data by subscription scope/i));

    expect(screen.getByText("Commissions")).toBeInTheDocument();
    expect(screen.getByText("ATTCC")).toBeInTheDocument();
    expect(screen.getByText("Not in a project")).toBeInTheDocument();

    const prodRow = screen.getByText("ACC-PROD-31599-ATTCC").closest("label") as HTMLElement;
    expect(within(prodRow).getByText("Prod")).toBeInTheDocument();
    const nonProdRow = screen.getByText("ACC-NPRD-31599-ATTCC").closest("label") as HTMLElement;
    expect(within(nonProdRow).getByText("Non-Prod")).toBeInTheDocument();
    // Unplaced subscriptions keep the flat rendering, without a tier badge.
    const legacyRow = screen.getByText("Legacy Sandbox").closest("label") as HTMLElement;
    expect(within(legacyRow).queryByText(/Prod/)).not.toBeInTheDocument();
  });
});
