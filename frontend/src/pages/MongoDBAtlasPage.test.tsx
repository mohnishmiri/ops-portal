/**
 * MongoDB Atlas page: inventory, gating that mirrors the API, the production
 * stop confirmation, schedules, and the not-configured state.
 */

import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import React from "react";

vi.mock("../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("../contexts/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("../contexts/PermissionsContext", () => ({ usePermissions: vi.fn() }));
vi.mock("../contexts/TimezoneContext", () => ({
  usePortalTimezone: () => ({ timezone: "UTC", formatDate: (v: string | null) => v ?? "—", formatShortDate: (v: string | null) => v ?? "—" }),
  TIMEZONE_OPTIONS: [{ value: "UTC", label: "UTC" }],
}));

import apiClient from "../services/apiClient";
import { useAuth } from "../contexts/AuthContext";
import { usePermissions } from "../contexts/PermissionsContext";
import type { AtlasCluster, AtlasSchedule, AtlasStatus } from "../services/mongodbAtlasApi";
import { buildCron, parsePresetCron } from "../features/mongodbAtlas/ScheduleManager";
import MongoDBAtlasPage from "./MongoDBAtlasPage";

const PID = "5f1a2b3c4d5e6f7a8b9c0d1e";

const status = (overrides: Partial<AtlasStatus> = {}): AtlasStatus => ({
  configured: true,
  reachable: true,
  base_url: "https://cloud.mongodb.com",
  public_key: "abcd••••",
  org_filter: null,
  project_allowlist: [],
  operation_timeout_minutes: 60,
  error: null,
  portal_ip: "203.0.113.9",
  api_key_roles: [],
  project_count: 1,
  checked_at: "2026-10-17T10:00:00Z",
  proxy: null,
  proxy_source: "none",
  ...overrides,
});

const cluster = (overrides: Partial<AtlasCluster>): AtlasCluster => ({
  id: "c1",
  name: "dev-cluster",
  project_id: PID,
  project_name: "commissions",
  state: "IDLE",
  paused: false,
  status: "running",
  tier: "M30",
  provider: "AZURE",
  regions: ["US_EAST_2"],
  cluster_type: "REPLICASET",
  mongo_version: "7.0.14",
  mongo_major_version: "7.0",
  disk_size_gb: 40,
  node_count: 3,
  shard_count: 1,
  backup_enabled: true,
  pit_enabled: false,
  termination_protection: false,
  tags: [],
  connection_string: "mongodb+srv://dev-cluster.ab1cd.mongodb.net",
  created_at: null,
  autoscaling: { compute_enabled: false, scale_down_enabled: false, min_tier: null, max_tier: null, disk_enabled: true },
  pausable: true,
  pause_blocker: null,
  environment: "non_production",
  is_production: false,
  schedules: [],
  paused_since: null,
  paused_days: null,
  auto_resume_warning: false,
  operation_in_progress: null,
  ...overrides,
});

const CLUSTERS = [
  cluster({}),
  cluster({ id: "c2", name: "prod-main", environment: "production", is_production: true }),
  cluster({ id: "c3", name: "parked", paused: true, status: "paused", paused_since: "2026-09-20T10:00:00Z", paused_days: 27, auto_resume_warning: true }),
];

const SCHEDULE: AtlasSchedule = {
  id: 7,
  name: "Non-prod off-hours",
  description: null,
  targets: [{ project_id: PID, project_name: "commissions", cluster_name: "dev-cluster" }],
  schedule_type: "recurring",
  timezone: "America/Chicago",
  stop_cron: "0 20 * * 1-5",
  start_cron: "0 7 * * 1-5",
  stop_at: null,
  start_at: null,
  stop_description: "weekdays at 20:00",
  start_description: "weekdays at 07:00",
  next_stop_at: "2026-10-20T01:00:00Z",
  next_start_at: "2026-10-20T12:00:00Z",
  skip_next_stop: false,
  skip_next_start: false,
  is_enabled: true,
  notify_on: "always",
  notification_emails: null,
  remind_minutes_before: 30,
  last_stop_run_at: null,
  last_start_run_at: null,
  last_run_status: "completed",
  created_by: "lead@att.com",
  created_at: "2026-10-01T00:00:00Z",
  updated_by: null,
  updated_at: "2026-10-01T00:00:00Z",
};

const CONNECTION_TEST = {
  ok: false,
  summary: "Could not reach cloud.mongodb.com (SSLEOFError: EOF occurred in violation of protocol). Set MONGODB_ATLAS_PROXY.",
  proxy: null,
  proxy_source: "none",
  checked_at: "2026-10-17T10:00:00Z",
  steps: [
    { name: "configuration", label: "Configuration", status: "ok", detail: "API key vfgi•••• · direct (no proxy)", ms: null },
    { name: "dns", label: "DNS lookup of cloud.mongodb.com", status: "ok", detail: "203.0.113.1", ms: 4 },
    { name: "tcp", label: "TCP connect to cloud.mongodb.com:443", status: "ok", detail: "Connected", ms: 30 },
    {
      name: "https",
      label: "HTTPS to cloud.mongodb.com",
      status: "failed",
      detail: "Could not reach cloud.mongodb.com (SSLEOFError: EOF occurred in violation of protocol). Set MONGODB_ATLAS_PROXY.",
      ms: 41,
    },
    { name: "api_key", label: "API key", status: "skipped", detail: "Skipped — Atlas not reached", ms: null },
    { name: "projects", label: "Projects", status: "skipped", detail: "Skipped", ms: null },
  ],
};

function mockApi(statusBody: AtlasStatus = status()) {
  vi.mocked(apiClient.get).mockImplementation(async (url: string) => {
    if (url.endsWith("/status")) return { data: statusBody };
    if (url.endsWith("/clusters")) return { data: { clusters: CLUSTERS, errors: [], project_count: 1, fetched_at: "2026-10-17T10:00:00Z" } };
    if (url.endsWith("/projects")) return { data: { projects: [{ id: PID, name: "commissions", org_id: "o", cluster_count: 3, created_at: null }], count: 1 } };
    if (url.endsWith("/utilization")) return { data: { clusters: { [`${PID}/dev-cluster`]: { cpu: 41.5, memory: 63 } }, fetched_at: "2026-10-17T10:00:00Z" } };
    if (url.endsWith("/schedules")) return { data: { schedules: [SCHEDULE], count: 1 } };
    if (url.endsWith("/operations")) return { data: { operations: [], count: 0, in_progress: 0 } };
    if (url.endsWith("/connection-test")) return { data: CONNECTION_TEST };
    if (url.includes("/operations/")) return { data: { id: 11, action: "pause", trigger: "manual", status: "in_progress", targets: [], requested_by: "lead@att.com", requested_at: "2026-10-17T10:00:00Z" } };
    return { data: {} };
  });
}

function asUser(canWrite: boolean, capabilities: string[] = ["atlas_cluster_power", "atlas_schedule_manage", "atlas_cluster_admin", "atlas_database_access"]) {
  vi.mocked(useAuth).mockReturnValue({ canWrite, isAdmin: false } as unknown as ReturnType<typeof useAuth>);
  vi.mocked(usePermissions).mockReturnValue({ hasCapability: (c: string) => capabilities.includes(c) } as unknown as ReturnType<typeof usePermissions>);
}

function renderPage(path = "/mongodb-atlas") {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <MongoDBAtlasPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("MongoDBAtlasPage", () => {
  it("lists clusters with status, environment and the 30-day auto-start warning", async () => {
    asUser(true);
    mockApi();
    renderPage();
    const grid = await screen.findByRole("table");
    await within(grid).findByText("prod-main");
    expect(within(grid).getByText("Prod")).toBeInTheDocument();
    expect(within(grid).getAllByText("Paused").length).toBeGreaterThan(0);
    expect(within(grid).getByText(/auto-start in 3d/)).toBeInTheDocument();
    await waitFor(() => expect(within(grid).getByText("42%")).toBeInTheDocument());
  });

  it("disables stop/start for a read-only user, as the API would refuse it", async () => {
    asUser(false);
    mockApi();
    renderPage();
    await screen.findByText("prod-main");
    const stop = screen.getAllByRole("button", { name: /permission/ });
    expect(stop.length).toBeGreaterThan(0);
    stop.forEach((b) => expect(b).toBeDisabled());
  });

  it("requires the production cluster's name before stopping it", async () => {
    asUser(true);
    mockApi();
    vi.mocked(apiClient.post).mockResolvedValue({
      data: { id: 11, action: "pause", trigger: "manual", status: "in_progress", targets: [], requested_by: "lead@att.com", requested_at: "2026-10-17T10:00:00Z" },
    });
    renderPage();
    const row = (await screen.findByText("prod-main")).closest("tr")!;
    fireEvent.click(within(row).getByRole("button", { name: "Stop (pause) this cluster" }));

    const dialog = await screen.findByRole("dialog");
    const submit = within(dialog).getByRole("button", { name: "Stop cluster" });
    expect(submit).toBeDisabled();
    fireEvent.change(within(dialog).getByLabelText(/type/i), { target: { value: "prod-main" } });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);

    await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
    const [url, body] = vi.mocked(apiClient.post).mock.calls[0];
    expect(url).toBe(`/mongodb-atlas/projects/${PID}/clusters/prod-main/pause`);
    expect(body).toMatchObject({ confirm_name: "prod-main", notify: true });
  });

  it("shows schedules and hides New schedule without the capability", async () => {
    asUser(true, ["atlas_cluster_power"]);
    mockApi();
    renderPage("/mongodb-atlas?tab=schedules");
    expect(await screen.findByText("Non-prod off-hours")).toBeInTheDocument();
    expect(screen.getByText("weekdays at 20:00")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /New schedule/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit" })).toBeDisabled();
  });

  it("explains what to configure when no API key is set", async () => {
    asUser(true);
    mockApi(status({ configured: false, reachable: false, error: "MongoDB Atlas is not configured", public_key: null, portal_ip: null, project_count: 0 }));
    renderPage();
    expect(await screen.findByText("Atlas not configured")).toBeInTheDocument();
    expect(screen.getAllByText(/MONGODB_ATLAS_PUBLIC_KEY/).length).toBeGreaterThan(0);
    expect(vi.mocked(apiClient.get).mock.calls.some(([url]) => String(url).endsWith("/clusters"))).toBe(false);
  });
});

describe("MongoDBAtlasPage — KPI tiles", () => {
  const clusterNames = () =>
    within(screen.getByRole("table"))
      .queryAllByRole("row")
      .slice(1)
      .map((row) => row.querySelector("td button")?.textContent)
      .filter(Boolean);

  it("opens the matching view and shows which tile is selected", async () => {
    asUser(true);
    mockApi();
    renderPage();
    await screen.findByText("prod-main");
    expect(clusterNames()).toEqual(["dev-cluster", "prod-main", "parked"]);

    fireEvent.click(screen.getByRole("button", { name: "Show paused clusters" }));
    await waitFor(() => expect(clusterNames()).toEqual(["parked"]));
    expect(screen.getByRole("button", { name: "Show paused clusters" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByLabelText("Filter by status")).toHaveValue("paused");

    fireEvent.click(screen.getByRole("button", { name: "Show running clusters" }));
    await waitFor(() => expect(clusterNames()).toEqual(["dev-cluster", "prod-main"]));

    // One paused cluster is near Atlas's 30-day auto-start.
    fireEvent.click(screen.getByRole("button", { name: "Show what needs attention" }));
    await waitFor(() => expect(clusterNames()).toEqual(["parked"]));

    fireEvent.click(screen.getByRole("button", { name: "Show start/stop schedules" }));
    expect(await screen.findByText("Non-prod off-hours")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Schedules" })).toHaveAttribute("aria-selected", "true");
  });

  it("says 1 project, not 1 projects", async () => {
    asUser(true);
    mockApi();
    renderPage();
    expect(await screen.findByText("Connected · 1 project")).toBeInTheDocument();
  });
});

describe("MongoDBAtlasPage — Atlas not reachable", () => {
  it("runs the connection test by itself, shows the broken step, and does not wait on cluster calls", async () => {
    asUser(true);
    mockApi(status({ reachable: false, error: "Could not reach cloud.mongodb.com (SSLEOFError)", portal_ip: null, project_count: 0 }));
    renderPage();
    expect(await screen.findByText("HTTPS to cloud.mongodb.com")).toBeInTheDocument();
    const steps = screen.getByRole("list", { name: "Connection test steps" });
    expect(within(steps).getAllByLabelText("Failed")).toHaveLength(1);
    expect(within(steps).getAllByLabelText("Skipped")).toHaveLength(2);
    expect(screen.getByText(/netsh winhttp show proxy/)).toBeInTheDocument();
    expect(screen.getByText("Direct (no proxy)")).toBeInTheDocument();
    const called = vi.mocked(apiClient.get).mock.calls.map(([url]) => String(url));
    expect(called.some((url) => url.endsWith("/clusters") || url.endsWith("/utilization"))).toBe(false);
    expect(called.filter((url) => url.endsWith("/connection-test"))).toHaveLength(1);
  });
});

describe("schedule cron helpers", () => {
  it("round-trips a preset", () => {
    expect(buildCron("1-5", "20:00")).toBe("0 20 * * 1-5");
    expect(parsePresetCron("0 20 * * 1-5")).toEqual({ days: "1-5", time: "20:00" });
    expect(parsePresetCron("30 7 * * *")).toEqual({ days: "*", time: "07:30" });
    expect(parsePresetCron("0 20 1 * *")).toBeNull();
  });
});
