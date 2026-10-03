/**
 * Smoke tests for the My Access and Access Management pages: render each
 * page and tab against realistic API payloads and check the key affordances.
 */

import { describe, it, expect, vi, beforeEach, onTestFinished } from "vitest";
import { render, screen, fireEvent, within, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import React from "react";

vi.mock("../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("../contexts/SessionContext", () => ({ useSession: vi.fn() }));

import apiClient from "../services/apiClient";
import { useSession } from "../contexts/SessionContext";
import MyAccessPage from "./MyAccessPage";
import AccessManagementPage from "./AccessManagementPage";

const EVERYONE = {
  id: 101, subject_type: "everyone", subject_id: "*", subject_email: null, scope_type: "project",
  project_id: 1, project_name: "Commissions", app_id: null, app_name: null, subscription_id: null,
  subscription_name: null, tier: "prod", level: "write", subscription_count: 6, request_item_id: null,
  granted_by: "system", created_at: "2026-10-01T09:00:00",
};
const PAT_GRANT = {
  ...EVERYONE, id: 5, subject_type: "user", subject_id: "u-pat", subject_email: "pat@example.com",
  scope_type: "app", app_id: 10, app_name: "ATTCC", tier: "nonprod", level: "read", subscription_count: 2,
  granted_by: "lead@example.com",
};
const REQUEST = {
  id: 12, requester_id: "u-pat", requester_email: "pat@example.com", requester_name: "Pat Doe",
  justification: "Need ATTCC prod for on-call", status: "pending", created_at: "2026-10-02T08:00:00",
  updated_at: null,
  items: [
    { id: 31, scope_type: "app", project_id: 1, project_name: "Commissions", app_id: 10, app_name: "ATTCC",
      tier: "prod", requested_level: "write", status: "pending", granted_level: null, decided_by: null,
      decided_at: null, decision_comment: null, can_decide: true },
  ],
};
const PROJECTS = [
  { id: 1, project_key: "commissions", name: "Commissions", description: "Commissions apps", is_active: true,
    admins: [{ user_id: "u-lead", email: "lead@example.com" }],
    apps: [{ id: 10, app_code: "31599", name: "ATTCC", description: null, subscription_counts: { prod: 3, nonprod: 2 } }] },
];
const PLACEMENTS = [
  { subscription_id: "sub-1", subscription_name: "ACC-PROD-31599-ATTCC", enabled: true, monitored: true,
    environment: "prod", tier: "prod", app_id: 10, app_name: "ATTCC", project_id: 1, project_name: "Commissions",
    suggested_tier: "prod", suggested_app_code: "31599", suggested_app_name: "ATTCC", suggested_app_id: 10 },
  { subscription_id: "sub-2", subscription_name: "ACC-NPRD-31599-ATTCC", enabled: true, monitored: true,
    environment: null, tier: null, app_id: null, app_name: null, project_id: null, project_name: null,
    suggested_tier: "nonprod", suggested_app_code: "31599", suggested_app_name: "ATTCC", suggested_app_id: 10 },
];

const RESPONSES: Record<string, unknown> = {
  "/access/me": {
    is_super_admin: false, role_ceiling: "read", has_subscription_access: true, readable_count: 6,
    writable_count: 0, admin_projects: [], grants: [EVERYONE, PAT_GRANT], pending_requests: 1,
  },
  "/access/catalog": [{ id: 1, name: "Commissions", description: null, apps: [{ id: 10, name: "ATTCC", app_code: "31599", tiers: ["prod", "nonprod"] }] }],
  "/access/requests/mine": [{ ...REQUEST, items: [{ ...REQUEST.items[0], can_decide: false }] }],
  "/access/admin/projects": PROJECTS,
  "/access/admin/grants": [EVERYONE, PAT_GRANT],
  "/access/admin/requests": [REQUEST],
  "/access/admin/subscriptions": PLACEMENTS,
  "/access/admin/users": [],
};

function mockSession(isSuperAdmin: boolean, adminProjectIds: number[] = []) {
  vi.mocked(useSession).mockReturnValue({
    session: null,
    hasCapability: () => true,
    isSuperAdmin,
    hasSubscriptionAccess: true,
    adminProjectIds,
    refreshSession: vi.fn(),
  });
}

function renderPage(element: React.ReactElement, path = "/") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <MemoryRouter initialEntries={[path]}>
      <QueryClientProvider client={qc}>{element}</QueryClientProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  (apiClient.get as any).mockImplementation(async (url: string) => {
    if (!(url in RESPONSES)) throw new Error(`unexpected GET ${url}`);
    return { data: RESPONSES[url] };
  });
});

describe("MyAccessPage", () => {
  it("shows KPIs, grants with tier badges, and a cancellable request", async () => {
    mockSession(false);
    renderPage(<MyAccessPage />);

    // The app grant's scope cell.
    expect(await screen.findByText("ATTCC", { selector: "td" })).toBeInTheDocument();
    expect(screen.getByText("your Entra role is read-only")).toBeInTheDocument();
    // The transition grant is labelled as coming from "Everyone".
    expect(screen.getAllByText("Everyone").length).toBeGreaterThan(0);
    // The request is still fully pending, so it can be withdrawn.
    expect(await screen.findByRole("button", { name: "Cancel request" })).toBeInTheDocument();
    // Read-only role: Write is offered but disabled in the request form.
    const write = screen.getByRole("option", { name: /write/i }) as HTMLOptionElement;
    expect(write.disabled).toBe(true);
  });
});

describe("AccessManagementPage", () => {
  it("gives a Project Admin the Requests and User Access tabs only", async () => {
    mockSession(false, [1]);
    renderPage(<AccessManagementPage />, "/access/manage");

    const tabs = screen.getAllByRole("tab").map((tab) => tab.textContent);
    expect(tabs.join("|")).toMatch(/^Requests.*\|User Access$/);
    expect(await screen.findByText("Transition grant active", { exact: false })).toBeInTheDocument();

    // Pending line with approve / reject enabled (can_decide).
    const row = (await screen.findByText("Need ATTCC prod for on-call")).closest("tr") as HTMLElement;
    expect(within(row).getByRole("button", { name: "Approve" })).toBeEnabled();
    fireEvent.click(within(row).getByRole("button", { name: "Approve" }));
    const dialog = screen.getByRole("dialog", { name: "Approve access" });
    // Requested write: approver may grant write or a lower read.
    expect(within(dialog).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Write (as requested)",
      "Read (lower than requested)",
    ]);
  });

  it("decides a line with the chosen level and comment", async () => {
    mockSession(false, [1]);
    (apiClient.post as any).mockResolvedValue({ data: REQUEST });
    renderPage(<AccessManagementPage />, "/access/manage");
    const row = (await screen.findByText("Need ATTCC prod for on-call")).closest("tr") as HTMLElement;
    fireEvent.click(within(row).getByRole("button", { name: "Approve" }));
    const dialog = screen.getByRole("dialog", { name: "Approve access" });
    fireEvent.change(within(dialog).getByLabelText("Grant level"), { target: { value: "read" } });
    fireEvent.change(within(dialog).getByLabelText(/comment/i), { target: { value: "read is enough" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/access/admin/requests/12/items/31/decision", {
        decision: "approve",
        level: "read",
        comment: "read is enough",
      }),
    );
  });

  it("gives a Super Admin the Projects & Apps and Subscriptions tabs", async () => {
    mockSession(true);
    renderPage(<AccessManagementPage />, "/access/manage?tab=projects");

    expect(await screen.findByText("lead@example.com")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add app" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("tab", { name: "Subscriptions" }));
    expect(await screen.findByText("ACC-NPRD-31599-ATTCC")).toBeInTheDocument();
    const unplaced = screen.getByText("ACC-NPRD-31599-ATTCC").closest("tr") as HTMLElement;
    expect(within(unplaced).getByText("Visible to Super Admins only")).toBeInTheDocument();
    expect(within(unplaced).getByRole("button", { name: /apply suggestion/i })).toBeEnabled();
    // A row already in its suggested app offers no suggestion button.
    const placed = screen.getByText("ACC-PROD-31599-ATTCC").closest("tr") as HTMLElement;
    expect(within(placed).queryByRole("button", { name: /apply suggestion/i })).toBeNull();
  });

  it("applies a placement suggestion in one click", async () => {
    mockSession(true);
    (apiClient.put as any).mockResolvedValue({ data: {} });
    renderPage(<AccessManagementPage />, "/access/manage?tab=subscriptions");
    const unplaced = (await screen.findByText("ACC-NPRD-31599-ATTCC")).closest("tr") as HTMLElement;
    fireEvent.click(within(unplaced).getByRole("button", { name: /apply suggestion/i }));
    await waitFor(() =>
      expect(apiClient.put).toHaveBeenCalledWith("/access/admin/subscriptions/sub-2", { app_id: 10, tier: "nonprod" }),
    );
  });
});

describe("KPI tiles open their list", () => {
  it("Unplaced Subscriptions shows the Subscriptions tab filtered to unplaced rows", async () => {
    mockSession(true);
    renderPage(<AccessManagementPage />, "/access/manage?tab=projects");

    const tile = await screen.findByRole("button", { name: "Show unplaced subscriptions" });
    fireEvent.click(tile);

    expect(await screen.findByText("ACC-NPRD-31599-ATTCC")).toBeInTheDocument();
    expect(screen.queryByText("ACC-PROD-31599-ATTCC")).toBeNull();
    expect(screen.getByRole("tab", { name: "Subscriptions" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByLabelText("Show")).toHaveValue("unplaced");
    expect(tile).toHaveAttribute("aria-pressed", "true");

    // Choosing another view from the dropdown releases the tile.
    fireEvent.change(screen.getByLabelText("Show"), { target: { value: "all" } });
    expect(await screen.findByText("ACC-PROD-31599-ATTCC")).toBeInTheDocument();
    expect(tile).toHaveAttribute("aria-pressed", "false");
  });

  it("Pending Requests returns to the pending queue from another tab", async () => {
    mockSession(true);
    renderPage(<AccessManagementPage />, "/access/manage?tab=subscriptions&view=unplaced");

    fireEvent.click(await screen.findByRole("button", { name: "Show pending requests" }));

    expect(screen.getByRole("tab", { name: /Requests/ })).toHaveAttribute("aria-selected", "true");
    expect(await screen.findByText("Pat Doe")).toBeInTheDocument();
    expect(screen.getByLabelText("Status")).toHaveValue("pending");
  });

  it("tiles work from the keyboard", async () => {
    mockSession(true);
    renderPage(<AccessManagementPage />, "/access/manage");

    const tile = await screen.findByRole("button", { name: "Show access grants" });
    fireEvent.keyDown(tile, { key: "Enter" });

    expect(screen.getByRole("tab", { name: "User Access" })).toHaveAttribute("aria-selected", "true");
  });

  it("My Access: Pending Requests filters my requests until the chip is cleared", async () => {
    mockSession(false);
    const original = RESPONSES["/access/requests/mine"];
    onTestFinished(() => {
      RESPONSES["/access/requests/mine"] = original;
    });
    RESPONSES["/access/requests/mine"] = [
      { ...REQUEST, items: [{ ...REQUEST.items[0], can_decide: false }] },
      { ...REQUEST, id: 13, status: "cancelled", justification: "Old cancelled request",
        items: [{ ...REQUEST.items[0], id: 32, status: "cancelled", can_decide: false }] },
    ];
    renderPage(<MyAccessPage />, "/access");

    expect(await screen.findByText("Old cancelled request")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show my pending requests" }));

    expect(screen.queryByText("Old cancelled request")).toBeNull();
    expect(screen.getByText("Need ATTCC prod for on-call")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Pending only \(1\)/ }));
    expect(await screen.findByText("Old cancelled request")).toBeInTheDocument();
  });
});
