/**
 * Cost pages: dates render as UTC days (no timezone shift), data gaps are
 * surfaced instead of hidden, KPIs say what they compare against, and the
 * amortized detail can be exported.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import React from "react";

vi.mock("../services/apiClient", () => ({
  default: { get: vi.fn(), post: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("../contexts/AuthContext", () => ({ useAuth: vi.fn() }));
vi.mock("../contexts/PermissionsContext", () => ({ usePermissions: () => ({ hasCapability: () => false }) }));
vi.mock("../contexts/SubscriptionContext", () => ({
  useSubscriptionScope: () => ({ effectiveSubscriptionIds: [], isLoading: false }),
}));

import apiClient from "../services/apiClient";
import { useAuth } from "../contexts/AuthContext";
import { fmtCostDate, fmtCostRange } from "../features/costs/costShared";
import AmortizedCostDashboard from "./AmortizedCostDashboard";
import LeadershipDashboard from "./LeadershipDashboard";

// Recharts' ResponsiveContainer needs ResizeObserver, which jsdom lacks.
class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
globalThis.ResizeObserver ??= ResizeObserverStub as unknown as typeof ResizeObserver;

const days = (start: string, count: number) =>
  Array.from({ length: count }, (_, i) => {
    const d = new Date(`${start}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() + i);
    return d.toISOString().slice(0, 10);
  });

const TREND_DAYS = days("2026-09-08", 30); // Sep 8 – Oct 7

const AMORTIZED = {
  environment: "ALL",
  total_cost: 190000.5,
  row_count: 52000,
  date_range: { start: "2026-09-08", end: "2026-10-07" },
  as_of: "2026-10-08",
  data_through: "2026-10-07",
  preliminary_from: "2026-10-05",
  coverage: {
    window_start: "2026-09-08",
    window_end: "2026-10-07",
    expected_subscriptions: 2,
    complete: false,
    issues: [
      {
        subscription_id: "sub-np",
        subscription_name: "ACC-NPRD-31599-ATTCC",
        missing_days: 12,
        total_days: 30,
        missing_ranges: [{ start: "2026-09-08", end: "2026-09-19" }],
        missing_range_count: 1,
      },
    ],
  },
  service_count: 2,
  resource_count: 1432,
  resource_group_count: 40,
  subscription_count: 2,
  commitment: { covered_cost: 100000, covered_pct: 52.6, pricing_total: 190000.5, pricing_coverage_pct: 100, complete: true },
  daily_trend: TREND_DAYS.map((d) => ({
    date: d,
    cost: 6000,
    prod: 4500,
    non_prod: 1500,
    preliminary: d >= "2026-10-05",
  })),
  service_breakdown: [
    { name: "Virtual Machines", cost: 120000, pct: 63.2 },
    { name: "Storage", cost: 70000.5, pct: 36.8 },
  ],
  resource_group_breakdown: [{ name: "rg-app", cost: 190000.5, pct: 100 }],
  resource_type_breakdown: [{ name: "Microsoft.Compute/virtualMachines", cost: 190000.5, pct: 100 }],
  location_breakdown: [{ name: "eastus2", cost: 190000.5, pct: 100 }],
  subscription_breakdown: [
    { name: "ACC-PROD-31599-ATTCC", subscription_id: "sub-p", environment: "Prod", cost: 135000, pct: 71.05 },
    { name: "ACC-NPRD-31599-ATTCC", subscription_id: "sub-np", environment: "Non-Prod", cost: 55000.5, pct: 28.95 },
  ],
  top_resources: [
    { resource_name: "vm-1", resource_group: "rg-app", resource_type: "Microsoft.Compute/virtualMachines", meter_category: "Virtual Machines", location: "eastus2", subscription: "ACC-PROD-31599-ATTCC", cost: 1000, active_days: 30 },
  ],
  monthly_pivot: {
    months: ["2026-09", "2026-10"],
    month_labels: { "2026-09": "2026 Sep", "2026-10": "2026 Oct" },
    month_coverage: {
      "2026-09": { start: "2026-09-08", end: "2026-09-30", days: 23, days_in_month: 30, partial: true },
      "2026-10": { start: "2026-10-01", end: "2026-10-07", days: 7, days_in_month: 31, partial: true },
    },
    services: [],
    monthly_totals: { "2026-09": 150000, "2026-10": 40000.5 },
    grand_total: 190000.5,
  },
  env_comparison: {
    totals: { Prod: 135000, "Non-Prod": 55000.5 },
    monthly: { "2026-09": { Prod: 105000, "Non-Prod": 45000 }, "2026-10": { Prod: 30000, "Non-Prod": 10000.5 } },
  },
  charge_type_breakdown: [{ name: "Usage", cost: 190000.5, pct: 100 }],
  pricing_model_breakdown: [
    { name: "OnDemand", cost: 90000.5, pct: 47.4 },
    { name: "SavingsPlan", cost: 75000, pct: 39.5 },
    { name: "Reservation", cost: 25000, pct: 13.1 },
  ],
  daily_by_service: [],
  top_service_names: [],
  source_date_range: { start: "2026-09-08", end: "2026-10-07" },
  latest_available_date: "2026-10-07",
  has_pending_source_data: false,
  generated_at: "2026-10-08T00:10:00",
};

const SYNC_STATUS = {
  last_sync: "2026-10-08T00:05:00",
  started_at: "2026-10-08T00:01:00",
  status: "completed",
  triggered_by: "scheduler",
  months_synced: 12,
  rows_synced: 14000,
  total_cost: 49000,
  duration_seconds: 240,
  error_message: "Partial sync: 1 of 3 date ranges failed and kept their previous data — ACC-NPRD-31599-ATTCC 2026-09-08..2026-09-19: HTTP 429",
  warning: "Partial sync: 1 of 3 date ranges failed and kept their previous data — ACC-NPRD-31599-ATTCC 2026-09-08..2026-09-19: HTTP 429",
  data_through: "2026-10-07",
  monitored_subscription_ids: ["sub-p", "sub-np"],
  monitored_subscription_count: 2,
};

const LEADERSHIP = {
  kpis: [
    { name: "Month-to-Date Spend", value: "42987.10", unit: "USD", trend: "stable", change_pct: 2.1, description: "Oct 1 – Oct 7, 2026 · 7 of 31 days · 2 subscriptions", comparison_label: "vs Sep 1 – Sep 7, 2026" },
    { name: "Projected Monthly Spend", value: "190370.00", unit: "USD", trend: "stable", change_pct: -2.7, description: "October run-rate: $6,141/day × 31 days", comparison_label: "vs September actual" },
    { name: "Last Month Spend", value: "195700.00", unit: "USD", trend: "up", change_pct: 9.4, description: "September 2026 · full month · 2 subscriptions", comparison_label: "vs August" },
    { name: "Month-over-Month Change", value: 2.1, unit: "%", trend: "stable", change_pct: 2.1, description: "Like-for-like: Oct 1 – Oct 7, 2026 vs Sep 1 – Sep 7, 2026", comparison_label: null },
  ],
  cost_trend: days("2026-09-23", 15).map((d) => ({ date: d, cost: "6100.00", currency: "USD", group_value: "ACC-PROD-31599-ATTCC", group_dimension: "subscription" })),
  top_spenders: [{ group_dimension: "subscription", group_value: "ACC-PROD-31599-ATTCC", total_cost: "42987.10", percentage_of_total: 100, currency: "USD" }],
  six_month_trend: [
    { month: "2026-08", month_label: "Aug 2026", total_cost: "178900.00", prod_cost: "133700.00", non_prod_cost: "45200.00", subscription_breakdown: {}, currency: "USD", complete: true, missing_days: 0 },
    { month: "2026-09", month_label: "Sep 2026", total_cost: "195700.00", prod_cost: "139100.00", non_prod_cost: "56600.00", subscription_breakdown: {}, currency: "USD", complete: true, missing_days: 0 },
  ],
  savings_opportunities: "0",
  report_date: "2026-10-08T00:06:40",
  data_through: "2026-10-07",
  preliminary_from: "2026-10-05",
  data_quality: [
    {
      kind: "missing_data",
      message: "ACC-NPRD-31599-ATTCC has no cost data for 287 day(s)",
      subscription_id: "sub-np",
      subscription_name: "ACC-NPRD-31599-ATTCC",
      missing_days: 287,
      missing_ranges: ["2025-10-01 → 2025-10-31", "2025-12-01 → 2026-08-31"],
    },
  ],
  pricing_mix: [
    { name: "OnDemand", cost: "92000.00", pct: 47.0 },
    { name: "SavingsPlan", cost: "76300.00", pct: 39.0 },
    { name: "Reservation", cost: "27400.00", pct: 14.0 },
  ],
  pricing_mix_month: "Sep 2026",
  pricing_mix_complete: true,
};

const OPTIMIZATION = {
  total_estimated_monthly_savings: 171.8,
  total_estimated_annual_savings: 2062,
  top_recommendations: [],
  recommendations_by_category: {},
  wastage: {
    total_monthly_waste: 171.8,
    idle_vms_count: 0,
    unattached_disks_count: 1,
    disconnected_private_endpoints_count: 0,
    orphaned_snapshots_count: 0,
    overprovisioned_count: 0,
    details: [],
  },
};

function routeGet(url: string) {
  if (url.startsWith("/costs/amortized-summary")) return { data: structuredClone(AMORTIZED) };
  if (url === "/costs/amortized/sync-status") return { data: structuredClone(SYNC_STATUS) };
  if (url === "/dashboards/leadership") return { data: structuredClone(LEADERSHIP) };
  if (url === "/dashboards/leadership/sync-status") return { data: { status: "completed", last_sync: "2026-10-08T00:06:40" } };
  if (url === "/dashboards/leadership/ollama-status") return { data: { enabled: false } };
  if (url.startsWith("/optimize/summary")) return { data: structuredClone(OPTIMIZATION) };
  if (url.startsWith("/costs/nonprod-vs-prod")) return { data: { data: [] } };
  if (url === "/costs/amortized/export") {
    return { data: new Blob(["Subscription\n"]), headers: { "content-disposition": 'attachment; filename="amortized-cost-resources-all.csv"' } };
  }
  throw new Error(`unexpected GET ${url}`);
}

function renderPage(page: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{page}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(apiClient.get).mockReset();
  vi.mocked(apiClient.get).mockImplementation(async (url: string) => routeGet(url) as never);
  vi.mocked(useAuth).mockReturnValue({ canWrite: true, isAdmin: false } as never);
});

describe("cost date formatting", () => {
  it("renders the UTC day as-is, never shifted into the viewer's timezone", () => {
    expect(fmtCostDate("2026-10-07")).toBe("Oct 7");
    expect(fmtCostDate("2026-10-07", { year: true })).toBe("Oct 7, 2026");
    expect(fmtCostDate("2026-10-01", { weekday: true })).toBe("Thu, Oct 1");
    expect(fmtCostRange("2026-07-08", "2026-10-07")).toBe("Jul 8 – Oct 7, 2026");
    expect(fmtCostRange("2025-10-08", "2026-10-07")).toBe("Oct 8, 2025 – Oct 7, 2026");
  });
});

describe("AmortizedCostDashboard", () => {
  it("states the exact period, data cut-off and true resource count", async () => {
    renderPage(<AmortizedCostDashboard />);

    expect(await screen.findByText(/Sep 8 – Oct 7, 2026 \(UTC\) • data through Oct 7, 2026 • 52,000 cost records/)).toBeInTheDocument();
    expect(screen.getByText("2 / 1,432")).toBeInTheDocument(); // not "2 / 50+"
    expect(screen.getByText("52.6%")).toBeInTheDocument(); // commitment coverage
  });

  it("warns which subscription is missing days and why the last sync was partial", async () => {
    renderPage(<AmortizedCostDashboard />);

    expect(await screen.findByText(/Data incomplete for this period/)).toBeInTheDocument();
    expect(screen.getByText(/no cost data for 12 of 30 days \(Sep 8 – Sep 19, 2026\)/)).toBeInTheDocument();
    expect(screen.getByText(/Last sync completed with gaps/)).toBeInTheDocument();
    expect(screen.getAllByText(/Partial sync: 1 of 3 date ranges failed/).length).toBeGreaterThan(0);
  });

  it("shows the real pricing-model split instead of a placeholder", async () => {
    renderPage(<AmortizedCostDashboard />);

    expect(await screen.findByText("By Pricing Model")).toBeInTheDocument();
    expect(screen.getByText("SavingsPlan")).toBeInTheDocument();
    expect(screen.getByText("52.6% of spend is on committed pricing")).toBeInTheDocument();
  });

  it("exports the resource summary for the selected period", async () => {
    const createObjectURL = vi.fn(() => "blob:x");
    Object.assign(window.URL, { createObjectURL, revokeObjectURL: vi.fn() });
    renderPage(<AmortizedCostDashboard />);

    fireEvent.click(await screen.findByRole("button", { name: /Export CSV/ }));
    fireEvent.click(screen.getByRole("menuitem", { name: /Resource summary/ }));

    await waitFor(() =>
      expect(apiClient.get).toHaveBeenCalledWith(
        "/costs/amortized/export",
        expect.objectContaining({ params: { env: "ALL", months: 3, level: "resources" }, responseType: "blob" }),
      ),
    );
    await waitFor(() => expect(createObjectURL).toHaveBeenCalled());
  });
});

describe("LeadershipDashboard (Cost Forecast)", () => {
  it("compares month-to-date like-for-like and labels the comparison", async () => {
    renderPage(<LeadershipDashboard />);

    expect(await screen.findByText("Month-to-Date Spend")).toBeInTheDocument();
    expect(screen.getByText("vs Sep 1 – Sep 7, 2026")).toBeInTheDocument();
    expect(screen.getByText("+2.1%")).toBeInTheDocument();
    expect(screen.getByText("Projected Monthly Spend")).toBeInTheDocument();
    expect(screen.getByText("Data through Oct 7, 2026 (UTC)")).toBeInTheDocument();
  });

  it("surfaces missing data and shows commitment coverage and savings without fake deltas", async () => {
    renderPage(<LeadershipDashboard />);

    expect(await screen.findByText(/Some cost data is missing/)).toBeInTheDocument();
    expect(screen.getByText(/287 day\(s\) with no data/)).toBeInTheDocument();
    expect(screen.getByText("Commitment Coverage")).toBeInTheDocument();
    expect(screen.getByText("53.0%")).toBeInTheDocument();
    expect(await screen.findByText("$2,062/yr")).toBeInTheDocument();
    expect(screen.queryByText("Total Savings Opportunities")).not.toBeInTheDocument();
  });
});
