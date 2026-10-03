/**
 * Tests for the "everyone" transition grant warning and its lock.
 *
 * At go-live the backend grants every signed-in user access to Commissions so
 * nobody loses access. While it exists, individual grants make no practical
 * difference, so admins must see it loudly — and only a Super Admin may
 * change or revoke it (the backend refuses anyone else with a 403).
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React from "react";

vi.mock("../../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import apiClient from "../../services/apiClient";
import type { AccessGrant, AdminProject } from "../../services/accessApi";
import { describeEveryoneGrants } from "./accessShared";
import UserAccessTab, { TransitionGrantBanner } from "./UserAccessTab";

const grant = (overrides: Partial<AccessGrant>): AccessGrant => ({
  id: 1,
  subject_type: "user",
  subject_id: "u1",
  subject_email: "pat@example.com",
  scope_type: "project",
  project_id: 1,
  project_name: "Commissions",
  app_id: null,
  app_name: null,
  subscription_id: null,
  subscription_name: null,
  tier: "prod",
  level: "read",
  subscription_count: 4,
  request_item_id: null,
  granted_by: "admin@example.com",
  created_at: "2026-10-01T10:00:00",
  ...overrides,
});

const EVERYONE_PROD = grant({ id: 101, subject_type: "everyone", subject_id: "*", subject_email: null, tier: "prod", level: "write" });
const EVERYONE_NONPROD = grant({ id: 102, subject_type: "everyone", subject_id: "*", subject_email: null, tier: "nonprod", level: "write" });
const PAT = grant({ id: 5, tier: "nonprod" });

const PROJECTS: AdminProject[] = [
  {
    id: 1,
    project_key: "commissions",
    name: "Commissions",
    description: null,
    is_active: true,
    admins: [],
    apps: [{ id: 10, app_code: "31599", name: "ATTCC", description: null, subscription_counts: { prod: 2, nonprod: 2 } }],
  },
];

beforeEach(() => {
  vi.clearAllMocks();
  (apiClient.get as any).mockResolvedValue({ data: [] });
});

describe("describeEveryoneGrants", () => {
  it("reads Prod and Non-Prod on the same project as one phrase", () => {
    expect(describeEveryoneGrants([EVERYONE_PROD, EVERYONE_NONPROD, PAT])).toEqual([
      "write access to Commissions Prod and Non-Prod",
    ]);
  });

  it("ignores individual grants", () => {
    expect(describeEveryoneGrants([PAT])).toEqual([]);
  });
});

describe("TransitionGrantBanner", () => {
  it("warns that every signed-in user has the transition access", () => {
    render(<TransitionGrantBanner grants={[EVERYONE_PROD, EVERYONE_NONPROD, PAT]} isSuperAdmin />);
    const banner = screen.getByRole("alert");
    expect(banner).toHaveTextContent("Transition grant active");
    expect(banner).toHaveTextContent(
      "every signed-in user has write access to Commissions Prod and Non-Prod. Remove it once individual access is set up, and before onboarding another project.",
    );
  });

  it("tells a Project Admin that only a Super Admin can revoke it", () => {
    render(<TransitionGrantBanner grants={[EVERYONE_PROD]} isSuperAdmin={false} />);
    expect(screen.getByRole("alert")).toHaveTextContent("Only a Super Admin can revoke it.");
  });

  it("renders nothing without an everyone grant", () => {
    const { container } = render(<TransitionGrantBanner grants={[PAT]} isSuperAdmin />);
    expect(container).toBeEmptyDOMElement();
  });
});

describe("UserAccessTab — grants grid", () => {
  function renderTab(isSuperAdmin: boolean) {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <UserAccessTab
          projects={PROJECTS}
          grants={[EVERYONE_PROD, PAT]}
          grantsLoading={false}
          grantsError={null}
          isSuperAdmin={isSuperAdmin}
          onNotify={vi.fn()}
        />
      </QueryClientProvider>,
    );
  }

  // The same text also appears in the user filter's options, so pick the grid row.
  const rowOf = (text: string) =>
    screen
      .getAllByText(text)
      .map((element) => element.closest("tr"))
      .find((row): row is HTMLTableRowElement => row !== null) as HTMLElement;

  it("locks the transition grant for a Project Admin but not individual grants", () => {
    renderTab(false);
    const everyoneRow = rowOf("Everyone");
    expect(within(everyoneRow).getByRole("button", { name: /only a super admin/i })).toBeDisabled();
    expect(within(everyoneRow).getByRole("combobox")).toBeDisabled();

    const patRow = rowOf("pat@example.com");
    expect(within(patRow).getByRole("button", { name: "Revoke grant" })).toBeEnabled();
    expect(within(patRow).getByRole("combobox")).toBeEnabled();
  });

  it("lets a Super Admin revoke the transition grant", () => {
    renderTab(true);
    expect(within(rowOf("Everyone")).getByRole("button", { name: "Revoke grant" })).toBeEnabled();
  });
});
