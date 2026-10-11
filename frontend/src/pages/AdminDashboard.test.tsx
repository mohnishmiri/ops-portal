/**
 * Admin Dashboard: KPIs derived from the subscription scope rule, real health
 * status, and per-control feedback on the configuration panel.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, within, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import React from "react";

vi.mock("../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));

import apiClient from "../services/apiClient";
import { TimezoneProvider } from "../contexts/TimezoneContext";
import AdminDashboard from "./AdminDashboard";

const SUB = (id: string, name: string, enabled: boolean, monitored: boolean) => ({
  subscription_id: id, subscription_name: name, name, state: "Enabled", enabled, monitored, environment: null,
  cost_env: name.includes("NPRD") || name.includes("DEV") ? "Non-Prod" : "Prod",
});

const ENV_OPTIONS = [
  { value: "production", label: "Production", cost_env: "Prod" },
  { value: "development", label: "Development", cost_env: "Non-Prod" },
];

const ACTIVITY = Array.from({ length: 12 }, (_, i) => ({
  id: i + 1,
  timestamp: `2026-10-11T05:${String(10 + i).padStart(2, "0")}:00`,
  user_email: i % 2 ? "pat@example.com" : "lee@example.com",
  action: i === 11 ? "admin_cache_release" : "admin_config_update",
  resource_type: i === 11 ? "admin_cache" : "admin_config",
  resource_id: null,
  summary: i === 11 ? "Released 4 cached key(s)" : `Changed cache_ttl_seconds from ${i} to ${i + 1}`,
  status: "success",
}));

const DASHBOARD = {
  subscriptions: [
    SUB("00000000-0000-0000-0000-000000000001", "ACC-PROD-31599-ATTCC", true, true),
    SUB("00000000-0000-0000-0000-000000000002", "ACC-NPRD-31599-ATTCC", true, false),
    SUB("00000000-0000-0000-0000-000000000003", "ACC-DEV-31599-ATTCC", false, false),
  ],
  subscription_count: 3,
  enabled_count: 2,
  environment: "development",
  version: "1.3.0",
  rate_limit_rpm: 10000,
  cache_ttl_seconds: 0,
  cache_enabled: true,
  ollama_enabled: false,
  system_health: { database: "connected", cache: "connected", api: "unreachable" },
  cors_origins: ["http://localhost:5177"],
  environment_options: ENV_OPTIONS,
  generated_at: "2026-10-11T05:26:25",
};

const CONFIGS = [
  { id: 1, config_key: "rate_limit_rpm", config_value: "10000", config_type: "integer", description: null,
    updated_at: "2026-10-10T09:00:00", updated_by: "pat@example.com" },
];

let responses: Record<string, unknown>;

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <MemoryRouter>
      <QueryClientProvider client={qc}>
        <TimezoneProvider>
          <AdminDashboard />
        </TimezoneProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  );
}

const axiosError = (status: number, detail: unknown) =>
  Object.assign(new Error(`Request failed with status code ${status}`), { response: { status, data: { detail } } });

beforeEach(() => {
  vi.clearAllMocks();
  responses = {
    "/dashboards/admin": DASHBOARD,
    "/admin/config": CONFIGS,
    "/admin/portal-timezone": { timezone: "UTC" },
    "/certificates/collections": [{ id: 1, name: "AP-KF-ATTCC-31599" }, { id: 2, name: "AP-KF-OTHER-1" }],
    "/certificates/collections/enabled": { collection_ids: [], mode: "all" },
    "/admin/audit": ACTIVITY,
  };
  (apiClient.get as any).mockImplementation(async (url: string) => {
    if (!(url in responses)) throw new Error(`unexpected GET ${url}`);
    return { data: responses[url] };
  });
});

describe("AdminDashboard", () => {
  it("counts only enabled AND monitored subscriptions as in scope, and filters the table from the KPI", async () => {
    renderPage();

    const inScope = (await screen.findByText("In Scope")).closest("[role='button']") as HTMLElement;
    expect(within(inScope).getByText("1")).toBeInTheDocument();
    const outOfScope = screen.getByText("Not In Scope").closest("[role='button']") as HTMLElement;
    expect(within(outOfScope).getByText("2")).toBeInTheDocument();

    fireEvent.click(outOfScope);
    expect(screen.queryByText("ACC-PROD-31599-ATTCC")).not.toBeInTheDocument();
    expect(screen.getByText("ACC-NPRD-31599-ATTCC")).toBeInTheDocument();
    expect(screen.getByText("ACC-DEV-31599-ATTCC")).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText("Search Managed Subscriptions"), { target: { value: "dev" } });
    expect(screen.queryByText("ACC-NPRD-31599-ATTCC")).not.toBeInTheDocument();
    expect(screen.getByText("ACC-DEV-31599-ATTCC")).toBeInTheDocument();
  });

  it("reports the Azure probe result instead of a fixed healthy status", async () => {
    renderPage();

    expect(await screen.findByText("Degraded")).toBeInTheDocument();
    expect(screen.getByText("Database connected · Azure API unreachable")).toBeInTheDocument();
  });

  it("shows the API's validation message when adding a subscription fails", async () => {
    (apiClient.post as any).mockRejectedValue(axiosError(409, "Subscription 0000 already exists"));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: /^Add$/ }));
    const idInput = screen.getByPlaceholderText("xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx");
    fireEvent.change(idInput, { target: { value: "not-a-guid" } });
    expect(screen.getByText(/Enter the subscription GUID/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Add Subscription" })).toBeDisabled();

    fireEvent.change(idInput, { target: { value: "00000000-0000-0000-0000-000000000009" } });
    fireEvent.click(screen.getByRole("button", { name: "Add Subscription" }));
    expect(await screen.findByText("Subscription 0000 already exists")).toBeInTheDocument();
    // Display name left blank: the API now defaults it, so it is not sent.
    expect((apiClient.post as any).mock.calls[0][1].subscription_name).toBeUndefined();
  });

  it("keeps save feedback on the control that was saved", async () => {
    (apiClient.put as any).mockImplementation(async (_url: string, body: { config_key: string }) => {
      if (body.config_key === "ollama_enabled") throw axiosError(400, "ollama_enabled must be a boolean value (true/false).");
      return { data: body };
    });
    renderPage();

    fireEvent.click(await screen.findByRole("switch", { name: "Ollama LLM" }));
    expect(await screen.findByText("ollama_enabled must be a boolean value (true/false).")).toBeInTheDocument();

    // The Ollama failure is not reported as a CORS problem, and no "Saved" appears beside CORS.
    expect(screen.queryByText("Failed to update CORS origins.")).not.toBeInTheDocument();
    expect(screen.queryByText("Saved")).not.toBeInTheDocument();

    // Rate limit rejects out-of-range values before calling the API.
    fireEvent.click(screen.getByRole("button", { name: "Edit rate limit" }));
    fireEvent.change(screen.getByLabelText("Rate limit (requests per minute)"), { target: { value: "5" } });
    expect(screen.getByText("Enter a whole number between 10 and 10000.")).toBeInTheDocument();
    expect(apiClient.put).toHaveBeenCalledTimes(1);

    // Last change is attributed.
    expect(screen.getByText(/Changed by pat@example.com/)).toBeInTheDocument();
  });

  it("edits a subscription's environment and shows what it does to cost reporting", async () => {
    (apiClient.put as any).mockResolvedValue({ data: { changes: {} } });
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Edit ACC-PROD-31599-ATTCC" }));
    const dialog = screen.getByRole("dialog", { name: "Edit subscription" });
    const env = within(dialog).getByLabelText("Environment");
    expect(within(env).getByRole("option", { name: "Development — Non-Prod spend" })).toBeInTheDocument();

    fireEvent.change(env, { target: { value: "development" } });
    fireEvent.click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(apiClient.put).toHaveBeenCalledWith("/admin/subscriptions/00000000-0000-0000-0000-000000000001", {
        subscription_name: "ACC-PROD-31599-ATTCC",
        environment: "development",
        notes: "",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("asks before removing a subscription and keeps the dialog open on failure", async () => {
    (apiClient.delete as any).mockRejectedValueOnce(axiosError(404, "Subscription not found"));
    renderPage();

    fireEvent.click(await screen.findByRole("button", { name: "Remove ACC-DEV-31599-ATTCC" }));
    const dialog = screen.getByRole("dialog", { name: "Remove subscription?" });
    expect(apiClient.delete).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole("button", { name: "Remove" }));
    expect(await within(dialog).findByText("Subscription not found")).toBeInTheDocument();
    expect(apiClient.delete).toHaveBeenCalledWith("/admin/subscriptions/00000000-0000-0000-0000-000000000003");
  });

  it("paginates the subscription grid ten rows at a time", async () => {
    responses["/dashboards/admin"] = {
      ...DASHBOARD,
      subscriptions: Array.from({ length: 12 }, (_, i) =>
        SUB(`00000000-0000-0000-0000-0000000000${String(i).padStart(2, "0")}`, `SUB-${String(i).padStart(2, "0")}`, true, true),
      ),
      subscription_count: 12,
    };
    renderPage();

    expect(await screen.findByText("Showing 1–10 of 12 subscriptions")).toBeInTheDocument();
    expect(screen.queryByText("SUB-11")).not.toBeInTheDocument();
    const pager = screen.getByText("Showing 1–10 of 12 subscriptions").parentElement as HTMLElement;
    fireEvent.click(within(pager).getByRole("button", { name: "Next" }));
    expect(screen.getByText("SUB-11")).toBeInTheDocument();
  });

  it("lists admin activity newest first with search", async () => {
    renderPage();

    const grid = (await screen.findByText("Admin Activity")).closest("div.overflow-hidden") as HTMLElement;
    await within(grid).findByText("Released 4 cached key(s)");
    const firstRow = within(grid).getAllByRole("row")[1];
    expect(within(firstRow).getByText("Released 4 cached key(s)")).toBeInTheDocument();
    expect(within(firstRow).getByText("Cache released")).toBeInTheDocument();
    expect(within(grid).getByText("Showing 1–10 of 12 changes")).toBeInTheDocument();

    fireEvent.change(within(grid).getByLabelText("Search Admin Activity"), { target: { value: "from 3 to" } });
    expect(within(grid).getByText("Changed cache_ttl_seconds from 3 to 4")).toBeInTheDocument();
    expect(within(grid).getByText("Showing 1–1 of 1 changes")).toBeInTheDocument();
  });

  it("shows environment, version and admin links in the header instead of separate cards", async () => {
    renderPage();

    expect(await screen.findByText("DEVELOPMENT")).toBeInTheDocument();
    expect(screen.getByText("v1.3.0")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Access Management" })).toHaveAttribute("href", "/access/manage");
    expect(screen.queryByText("System Health", { selector: "h3" })).not.toBeInTheDocument();
    // Toggles are switches with their state written out, not colour alone.
    const cache = screen.getByRole("switch", { name: "Page cache" });
    expect(cache).toHaveAttribute("aria-checked", "true");
    expect(within(cache.parentElement as HTMLElement).getByText("On")).toBeInTheDocument();
  });

  it("only enables certificate collection Save when the selection changed, and flags an empty selection", async () => {
    (apiClient.put as any).mockResolvedValue({ data: {} });
    renderPage();

    const save = await screen.findByRole("button", { name: "Save" });
    await waitFor(() => expect(screen.getByLabelText("AP-KF-ATTCC-31599")).toBeInTheDocument());
    expect(save).toBeDisabled();
    expect(screen.getByText(/all collections are visible/)).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText("AP-KF-ATTCC-31599"));
    expect(save).toBeEnabled();
    expect(screen.getByText("Unsaved changes")).toBeInTheDocument();

    fireEvent.click(save);
    await waitFor(() =>
      expect(apiClient.put).toHaveBeenCalledWith("/certificates/collections/enabled", { collection_ids: [1] }),
    );
  });

  it("shows a load error instead of 'No collections found' when Keyfactor fails", async () => {
    (apiClient.get as any).mockImplementation(async (url: string) => {
      if (url === "/certificates/collections") throw axiosError(502, "Keyfactor unavailable");
      if (!(url in responses)) throw new Error(`unexpected GET ${url}`);
      return { data: responses[url] };
    });
    renderPage();

    expect(await screen.findByText(/Could not load collections: Keyfactor unavailable/)).toBeInTheDocument();
    expect(screen.queryByText("No collections found.")).not.toBeInTheDocument();
  });
});
