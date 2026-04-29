/**
 * Cost API service hooks using React Query.
 */

import { useQuery, useMutation, useQueryClient, QueryClient } from "@tanstack/react-query";
import apiClient from "./apiClient";

const GRID_POLL_INTERVAL = 120_000;
const DASHBOARD_POLL_INTERVAL = 120_000;
const SLOW_GRID_POLL_INTERVAL = 5 * 60 * 1000;
const SYNC_STATUS_POLL_INTERVAL = 30_000; // 30 s — match KeyVault polling cadence

// ── Types ─────────────────────────────────────────────────────────────

export interface CostDataPoint {
  date: string;
  cost: number;
  currency: string;
  group_value: string;
  group_dimension: string;
}

export interface CostSummary {
  total_cost: number;
  previous_period_cost: number;
  cost_change_pct: number;
  trend: "up" | "down" | "stable";
  currency: string;
  period_start: string;
  period_end: string;
  subscription_count: number;
}

export interface CostTimeSeriesResponse {
  data_points: CostDataPoint[];
  summary: CostSummary;
}

export interface CostByGroup {
  group_dimension: string;
  group_value: string;
  total_cost: number;
  percentage_of_total: number;
  currency: string;
}

export interface KPIMetric {
  name: string;
  value: number;
  unit: string;
  trend: "up" | "down" | "stable";
  change_pct: number;
  description: string;
}

export interface MonthlyCostPoint {
  month: string;
  month_label: string;
  total_cost: number;
  non_prod_cost: number;
  prod_cost: number;
  subscription_breakdown: Record<string, number>;
  currency: string;
}

export interface LeadershipDashboard {
  kpis: KPIMetric[];
  cost_trend: CostDataPoint[];
  top_spenders: CostByGroup[];
  six_month_trend: MonthlyCostPoint[];
  savings_opportunities: number;
  report_date: string;
}

export interface CostRecommendation {
  id: string;
  category: string;
  priority: string;
  title: string;
  description: string;
  resource: {
    resource_name: string;
    resource_type: string;
    resource_group: string;
    subscription_id: string;
    location: string;
  };
  current_monthly_cost: number;
  estimated_monthly_savings: number;
  estimated_annual_savings: number;
  confidence: string;
  confidence_score: number;
  action_required: string;
  risk_level: string;
  status: string;
  source: string;
}

export interface WastageDetailItem {
  category: string;
  count: number;
  monthly_waste: number;
  annual_waste: number;
  resources: Array<{
    name: string;
    resource_group: string;
    subscription_id: string;
    monthly_cost: string;
    title: string;
    recommendation: string;
    current_sku: string;
    recommended_sku: string;
    priority: string;
    resource_type: string;
    confidence: string;
  }>;
}

export interface OptimizationSummary {
  total_recommendations: number;
  total_estimated_monthly_savings: number;
  total_estimated_annual_savings: number;
  wastage: {
    total_monthly_waste: number;
    idle_vms_count: number;
    unattached_disks_count: number;
    orphaned_snapshots_count: number;
    overprovisioned_count: number;
    details: WastageDetailItem[];
  };
  top_recommendations: CostRecommendation[];
}

function normalizeOptimizationSummary(data: OptimizationSummary): OptimizationSummary {
  data.total_estimated_monthly_savings = Number(data.total_estimated_monthly_savings ?? 0);
  data.total_estimated_annual_savings = Number(data.total_estimated_annual_savings ?? 0);
  if (data.wastage) {
    data.wastage.total_monthly_waste = Number(data.wastage.total_monthly_waste ?? 0);
    if (data.wastage.details) {
      data.wastage.details = data.wastage.details.map((d: WastageDetailItem) => ({
        ...d,
        monthly_waste: Number(d.monthly_waste ?? 0),
        annual_waste: Number(d.annual_waste ?? 0),
      }));
    }
  }
  if (data.top_recommendations) {
    data.top_recommendations = data.top_recommendations.map((r: CostRecommendation) => ({
      ...r,
      estimated_annual_savings: Number(r.estimated_annual_savings ?? 0),
      estimated_monthly_savings: Number(r.estimated_monthly_savings ?? 0),
      current_monthly_cost: Number(r.current_monthly_cost ?? 0),
    }));
  }
  return data;
}

export interface LeadershipAdvisorInsight {
  title: string;
  detail: string;
  estimated_savings?: string;
}

export interface LeadershipAdvisorResponse {
  source: "ollama" | "fallback";
  model: string;
  generated_at: string;
  summary: string;
  focus_areas: string[];
  risks: string[];
  opportunities: LeadershipAdvisorInsight[];
  azure_pricing: {
    status: string;
    details: string;
    resources_considered: number;
  };
}

export interface LeadershipForecastPoint {
  month_key: string;
  month_label: string;
  prod_actual: number | null;
  non_prod_actual: number | null;
  total_actual: number | null;
  prod_forecast: number | null;
  non_prod_forecast: number | null;
  total_forecast: number | null;
}

export interface LeadershipForecastResponse {
  source: "ollama" | "fallback";
  model: string;
  generated_at: string;
  summary: string;
  historical_months: number;
  forecast_months: number;
  forecast_year: number;
  points: LeadershipForecastPoint[];
}

export interface LeadershipAdvisorInput {
  dashboard: LeadershipDashboard;
  optimization?: OptimizationSummary | null;
  trend?: NonProdVsProdTrend | null;
  syncStatus?: LeadershipSyncStatus | null;
}

function buildFallbackLeadershipAdvice(
  input: LeadershipAdvisorInput
): LeadershipAdvisorResponse {
  const totalMonthlySpend = Number(
    input.dashboard.kpis.find((item) => item.name.toLowerCase().includes("monthly spend"))?.value ?? 0
  );
  const monthlyChange = Number(
    input.dashboard.kpis.find((item) => item.name.toLowerCase().includes("month-over"))?.value ?? 0
  );
  const topSpenders = input.dashboard.top_spenders.slice(0, 3);

  return {
    source: "fallback",
    model: "local-heuristic",
    generated_at: new Date().toISOString(),
    summary: `Current monitored monthly spend is $${totalMonthlySpend.toLocaleString()}. The advisor endpoint is unavailable, so this view is using local dashboard heuristics until the backend AI route is reachable.`,
    focus_areas: [
      topSpenders[0]
        ? `${topSpenders[0].group_value} is currently the largest spend concentration at ${topSpenders[0].percentage_of_total.toFixed(1)}% of total cost.`
        : "Use the largest subscription and resource categories as the first review scope.",
      input.optimization
        ? `${input.optimization.total_recommendations} active optimization recommendations are available for execution review.`
        : "Optimization recommendations are still loading.",
      input.trend?.data?.length
        ? `The ${input.trend.months}-month prod vs non-prod trend is available for short-horizon forecasting.`
        : "Trend data is still loading; forecast guidance will improve once historical points are available.",
    ],
    risks: [
      monthlyChange > 0
        ? `Month-over-month spend is up ${monthlyChange.toFixed(1)}%, which increases budget pressure.`
        : `Month-over-month spend is down ${Math.abs(monthlyChange).toFixed(1)}%; confirm that the reduction is durable.`,
      topSpenders.length >= 2
        ? `${topSpenders[0].group_value} and ${topSpenders[1].group_value} account for most current spend and should be reviewed first.`
        : "A small number of subscriptions appear to drive most spend.",
      "Backend advisor endpoint is currently unavailable or not yet restarted, so Ollama guidance could not be generated from the server.",
    ],
    opportunities: (input.optimization?.top_recommendations || []).slice(0, 4).map((item) => ({
      title: item.title,
      detail: `${item.resource.resource_name} in ${item.resource.resource_group}`,
      estimated_savings: `$${Number(item.estimated_annual_savings || 0).toLocaleString()}/yr`,
    })),
    azure_pricing: {
      status: "ollama-only",
      details: "Using local fallback guidance because the backend advisor endpoint was unavailable.",
      resources_considered: input.optimization?.top_recommendations?.length || 0,
    },
  };
}

export async function requestLeadershipOllamaAdvice(
  input: LeadershipAdvisorInput
): Promise<LeadershipAdvisorResponse> {
  try {
    const { data } = await apiClient.post("/dashboards/leadership/advisor", {
      dashboard: input.dashboard,
      optimization: input.optimization ?? null,
      trend: input.trend ?? null,
      sync_status: input.syncStatus ?? null,
    });
    return data;
  } catch {
    return buildFallbackLeadershipAdvice(input);
  }
}

export function useOllamaStatus() {
  return useQuery<{ enabled: boolean; status: string }>({
    queryKey: ["ollama", "status"],
    queryFn: async () => {
      const { data } = await apiClient.get("/dashboards/leadership/ollama-status");
      return data;
    },
    staleTime: 60 * 1000,
  });
}

export function useLeadershipCostAdvisor() {
  return useMutation<LeadershipAdvisorResponse, Error, LeadershipAdvisorInput>({
    mutationFn: requestLeadershipOllamaAdvice,
  });
}

function buildFallbackLeadershipForecast(
  input: LeadershipAdvisorInput
): LeadershipForecastResponse {
  const actual = [...input.dashboard.six_month_trend].sort((left, right) => left.month.localeCompare(right.month));
  if (!actual.length) {
    return {
      source: "fallback",
      model: "local-heuristic",
      generated_at: new Date().toISOString(),
      summary: "No historical data was available to generate a forecast.",
      historical_months: 0,
      forecast_months: 0,
      forecast_year: new Date().getUTCFullYear(),
      points: [],
    };
  }

  const deltasFor = (selector: (point: MonthlyCostPoint) => number) => {
    const deltas = actual.slice(1).map((point, index) => selector(point) - selector(actual[index]));
    return deltas.length ? deltas.reduce((sum, value) => sum + value, 0) / deltas.length : 0;
  };

  const avgProdDelta = deltasFor((point) => Number(point.prod_cost));
  const avgNonProdDelta = deltasFor((point) => Number(point.non_prod_cost));
  const historicalPoints = actual.map((point) => ({
    month_key: point.month,
    month_label: point.month_label,
    prod_actual: Number(point.prod_cost),
    non_prod_actual: Number(point.non_prod_cost),
    total_actual: Number(point.total_cost),
    prod_forecast: null,
    non_prod_forecast: null,
    total_forecast: null,
  }));
  const lastPoint = actual[actual.length - 1];
  const start = new Date(`${lastPoint.month}-01T00:00:00`);
  const forecastPoints = Array.from({ length: 6 }, (_, index) => {
    const date = new Date(start);
    date.setMonth(date.getMonth() + index + 1);
    const prodForecast = Math.max(0, Number(lastPoint.prod_cost) + avgProdDelta * (index + 1));
    const nonProdForecast = Math.max(0, Number(lastPoint.non_prod_cost) + avgNonProdDelta * (index + 1));
    return {
      month_key: `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}`,
      month_label: date.toLocaleDateString("en-US", { month: "short", year: "numeric" }),
      prod_actual: null,
      non_prod_actual: null,
      total_actual: null,
      prod_forecast: prodForecast,
      non_prod_forecast: nonProdForecast,
      total_forecast: prodForecast + nonProdForecast,
    };
  });

  return {
    source: "fallback",
    model: "local-heuristic",
    generated_at: new Date().toISOString(),
    summary: "Ollama forecast generation was unavailable, so the chart is using a baseline projection from the latest six months of prod and non-prod history.",
    historical_months: historicalPoints.length,
    forecast_months: forecastPoints.length,
    forecast_year: new Date(forecastPoints[forecastPoints.length - 1]?.month_key || start).getUTCFullYear(),
    points: [...historicalPoints, ...forecastPoints],
  };
}

export async function requestLeadershipForecast(
  input: LeadershipAdvisorInput
): Promise<LeadershipForecastResponse> {
  try {
    const { data } = await apiClient.post("/dashboards/leadership/forecast", {
      dashboard: input.dashboard,
      optimization: input.optimization ?? null,
      trend: input.trend ?? null,
      sync_status: input.syncStatus ?? null,
    });
    return data;
  } catch {
    return buildFallbackLeadershipForecast(input);
  }
}

export function useLeadershipCostForecast(
  input?: LeadershipAdvisorInput,
  enabled: boolean = true
) {
  return useQuery<LeadershipForecastResponse>({
    queryKey: ["dashboard", "leadership", "forecast", input?.dashboard.report_date ?? "none"],
    enabled: Boolean(input && enabled),
    queryFn: async () => {
      if (!input) {
        throw new Error("Leadership forecast input is required");
      }
      return requestLeadershipForecast(input);
    },
    staleTime: 30 * 60 * 1000,
  });
}

// ── React Query Hooks ─────────────────────────────────────────────────

export function useLeadershipDashboard() {
  return useQuery<LeadershipDashboard>({
    queryKey: ["dashboard", "leadership"],
    queryFn: async () => {
      const { data } = await apiClient.get("/dashboards/leadership");
      // Backend returns Decimal fields as strings — coerce to numbers
      if (data.kpis) {
        data.kpis = data.kpis.map((k: KPIMetric) => ({ ...k, value: Number(k.value) }));
      }
      if (data.cost_trend) {
        data.cost_trend = data.cost_trend.map((p: CostDataPoint) => ({ ...p, cost: Number(p.cost) }));
      }
      if (data.top_spenders) {
        data.top_spenders = data.top_spenders.map((s: CostByGroup) => ({ ...s, total_cost: Number(s.total_cost) }));
      }
      if (data.savings_opportunities != null) {
        data.savings_opportunities = Number(data.savings_opportunities);
      }
      if (data.six_month_trend) {
        data.six_month_trend = data.six_month_trend.map((m: MonthlyCostPoint) => ({
          ...m,
          total_cost: Number(m.total_cost),
          non_prod_cost: Number(m.non_prod_cost ?? 0),
          prod_cost: Number(m.prod_cost ?? 0),
          subscription_breakdown: Object.fromEntries(
            Object.entries(m.subscription_breakdown || {}).map(([k, v]) => [k, Number(v)])
          ),
        }));
      }
      return data;
    },
    staleTime: 5 * 60 * 1000, // 5 minutes
    gcTime: 30 * 60 * 1000,
    refetchInterval: DASHBOARD_POLL_INTERVAL,
  });
}

/**
 * Force-refresh the leadership dashboard by bypassing the backend cache.
 * backend.  Invalidates the React Query cache entry afterwards so the UI
 * immediately re‑renders with fresh data.
 */
export async function refreshLeadershipDashboard(queryClient: QueryClient): Promise<void> {
  await apiClient.post("/dashboards/leadership/sync");
  const { data } = await apiClient.get("/dashboards/leadership");
  // Apply the same numeric coercion as the hook
  if (data.kpis) {
    data.kpis = data.kpis.map((k: KPIMetric) => ({ ...k, value: Number(k.value) }));
  }
  if (data.cost_trend) {
    data.cost_trend = data.cost_trend.map((p: CostDataPoint) => ({ ...p, cost: Number(p.cost) }));
  }
  if (data.top_spenders) {
    data.top_spenders = data.top_spenders.map((s: CostByGroup) => ({ ...s, total_cost: Number(s.total_cost) }));
  }
  if (data.savings_opportunities != null) {
    data.savings_opportunities = Number(data.savings_opportunities);
  }
  if (data.six_month_trend) {
    data.six_month_trend = data.six_month_trend.map((m: MonthlyCostPoint) => ({
      ...m,
      total_cost: Number(m.total_cost),
      non_prod_cost: Number(m.non_prod_cost ?? 0),
      prod_cost: Number(m.prod_cost ?? 0),
      subscription_breakdown: Object.fromEntries(
        Object.entries(m.subscription_breakdown || {}).map(([k, v]) => [k, Number(v)])
      ),
    }));
  }
  // Update the query cache in-place so the UI re-renders immediately
  queryClient.setQueryData(["dashboard", "leadership"], data);
}

export async function refreshOptimizationSummary(queryClient: QueryClient): Promise<void> {
  const { data } = await apiClient.get("/optimize/summary?refresh=true");
  queryClient.setQueryData(["optimization", "summary"], normalizeOptimizationSummary(data));
}

// ── Leadership Dashboard Sync ──────────────────────────────────────

export interface LeadershipSyncStatus {
  last_sync: string | null;
  started_at: string | null;
  status: string | null;
  triggered_by: string | null;
  duration_seconds: number | null;
  error_message: string | null;
  monitored_subscription_count: number | null;
}

export function useLeadershipSyncStatus() {
  return useQuery<LeadershipSyncStatus>({
    queryKey: ["dashboard", "leadership-sync-status"],
    queryFn: async () => {
      const { data } = await apiClient.get("/dashboards/leadership/sync-status");
      return data;
    },
    staleTime: 15 * 1000,                       // 15 s — match KeyVault cadence
    refetchInterval: SYNC_STATUS_POLL_INTERVAL,  // 30 s auto-refresh
    retry: 1,
  });
}

export function useLeadershipSync() {
  const qc = useQueryClient();
  return useMutation<{ status: string }, Error, void>({
    mutationFn: async () => {
      const { data } = await apiClient.post("/dashboards/leadership/sync");
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dashboard", "leadership"] });
      qc.invalidateQueries({ queryKey: ["dashboard", "leadership-sync-status"] });
    },
  });
}

export function useDailyCosts(days: number = 30) {
  return useQuery<CostTimeSeriesResponse>({
    queryKey: ["costs", "daily", days],
    queryFn: async () => {
      const { data } = await apiClient.get(`/costs/daily?days=${days}`);
      return data;
    },
    staleTime: 10 * 60 * 1000,
  });
}

export function useMonthlyCosts(months: number = 12) {
  return useQuery<CostTimeSeriesResponse>({
    queryKey: ["costs", "monthly", months],
    queryFn: async () => {
      const { data } = await apiClient.get(`/costs/monthly?months=${months}`);
      return data;
    },
    staleTime: 30 * 60 * 1000,
  });
}

export function useCostBreakdown(
  dimension: string = "subscription",
  preset: string = "current_month"
) {
  return useQuery({
    queryKey: ["costs", "breakdown", dimension, preset],
    queryFn: async () => {
      const { data } = await apiClient.get(
        `/costs/breakdown?dimension=${dimension}&preset=${preset}`
      );
      return data;
    },
    staleTime: 10 * 60 * 1000,
  });
}

// ── Budget vs RunRate Types ───────────────────────────────────────────

export interface BudgetRunRateApp {
  app_name: string;
  budget_2026: number;
  run_rate_2026: number;
  variance: number;
  utilization_pct: number;
}

export interface BudgetRunRateResponse {
  applications: BudgetRunRateApp[];
  totals: { budget_2026: number; run_rate_2026: number; variance: number; utilization_pct: number };
  generated_at: string;
}

// ── Budget vs RunRate Hook ────────────────────────────────────────────

export function useBudgetRunRate() {
  return useQuery<BudgetRunRateResponse>({
    queryKey: ["dashboard", "budget-runrate"],
    queryFn: async () => {
      const { data } = await apiClient.get("/dashboards/budget-runrate");
      return data;
    },
    staleTime: 10 * 60 * 1000,
    refetchInterval: SLOW_GRID_POLL_INTERVAL,
  });
}

export async function refreshBudgetRunRate(): Promise<BudgetRunRateResponse> {
  const { data } = await apiClient.get("/dashboards/budget-runrate?refresh=true");
  return data;
}

export function useOptimizationSummary() {
  return useQuery<OptimizationSummary>({
    queryKey: ["optimization", "summary"],
    queryFn: async () => {
      const { data } = await apiClient.get("/optimize/summary");
      return normalizeOptimizationSummary(data);
    },
    staleTime: 30 * 60 * 1000,
    gcTime: 60 * 60 * 1000,
  });
}

export function useRecommendations(category?: string) {
  return useQuery<CostRecommendation[]>({
    queryKey: ["optimization", "recommendations", category],
    queryFn: async () => {
      const params = category ? `?category=${category}` : "";
      const { data } = await apiClient.get(`/optimize/recommendations${params}`);
      return data;
    },
    staleTime: 15 * 60 * 1000,
    refetchInterval: SLOW_GRID_POLL_INTERVAL,
  });
}

// ── Operations Dashboard ──────────────────────────────────────────────

export interface DailySpendPoint {
  date: string;
  cost: number;
}

export interface Anomaly {
  date: string;
  cost: number;
  avg: number;
}

export interface SubscriptionCost {
  subscription_id: string;
  cost: number;
}

export interface OpsDashboard {
  cost_by_resource_type: {
    breakdown: CostByGroup[];
    summary: CostSummary;
  };
  cost_by_resource_group: {
    breakdown: CostByGroup[];
    summary: CostSummary;
  };
  cost_by_location: {
    breakdown: CostByGroup[];
    summary: CostSummary;
  };
  daily_spend: DailySpendPoint[];
  daily_avg: number;
  prev_month_daily_avg: number;
  anomalies: Anomaly[];
  subscription_costs: SubscriptionCost[];
  subscriptions_monitored: number;
  generated_at: string;
}

export function useOpsDashboard() {
  return useQuery<OpsDashboard>({
    queryKey: ["dashboard", "ops"],
    queryFn: async () => {
      const { data } = await apiClient.get("/dashboards/ops");
      // Coerce Decimal strings → numbers
      const coerceBreakdown = (b: CostByGroup[]) =>
        b.map((x: CostByGroup) => ({ ...x, total_cost: Number(x.total_cost) }));
      if (data.cost_by_resource_type?.breakdown)
        data.cost_by_resource_type.breakdown = coerceBreakdown(data.cost_by_resource_type.breakdown);
      if (data.cost_by_resource_group?.breakdown)
        data.cost_by_resource_group.breakdown = coerceBreakdown(data.cost_by_resource_group.breakdown);
      if (data.cost_by_location?.breakdown)
        data.cost_by_location.breakdown = coerceBreakdown(data.cost_by_location.breakdown);
      if (data.daily_spend)
        data.daily_spend = data.daily_spend.map((d: DailySpendPoint) => ({ ...d, cost: Number(d.cost) }));
      data.daily_avg = Number(data.daily_avg ?? 0);
      data.prev_month_daily_avg = Number(data.prev_month_daily_avg ?? 0);
      if (data.anomalies)
        data.anomalies = data.anomalies.map((a: Anomaly) => ({ ...a, cost: Number(a.cost), avg: Number(a.avg) }));
      if (data.subscription_costs)
        data.subscription_costs = data.subscription_costs.map((s: SubscriptionCost) => ({ ...s, cost: Number(s.cost) }));
      return data;
    },
    staleTime: 5 * 60 * 1000,
    refetchInterval: DASHBOARD_POLL_INTERVAL,
  });
}

// ── Admin Dashboard ───────────────────────────────────────────────────

export interface SubscriptionInfo {
  id?: number;
  subscription_id: string;
  subscription_name?: string;
  name: string;
  state: string;
  enabled: boolean;
  monitored: boolean;
  environment?: string | null;
  notes?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
  created_by?: string | null;
}

export interface AdminDashboard {
  subscriptions: SubscriptionInfo[];
  subscription_count: number;
  enabled_count: number;
  environment: string;
  version: string;
  rate_limit_rpm: number;
  cache_ttl_seconds: number;
  cache_enabled: boolean;
  ollama_enabled: boolean;
  system_health: {
    database: string;
    cache: string;
    api: string;
  };
  cors_origins: string[];
  generated_at: string;
}

export interface AdminConfigEntry {
  id: number;
  config_key: string;
  config_value: string;
  config_type: string;
  description: string | null;
  updated_at: string | null;
  updated_by: string | null;
}

export interface CacheReleaseResult {
  status: string;
  released_keys: number;
  patterns: Record<string, number>;
  released_at: string;
}

export function useAdminDashboard() {
  return useQuery<AdminDashboard>({
    queryKey: ["dashboard", "admin"],
    queryFn: async () => {
      const { data } = await apiClient.get("/dashboards/admin");
      return data;
    },
    staleTime: 30 * 1000,
    refetchInterval: GRID_POLL_INTERVAL,
  });
}

// ── Admin Subscription CRUD ───────────────────────────────────────────

export function useAdminSubscriptions() {
  return useQuery<SubscriptionInfo[]>({
    queryKey: ["admin", "subscriptions"],
    queryFn: async () => {
      const { data } = await apiClient.get("/admin/subscriptions");
      return data;
    },
    staleTime: 30 * 1000,
    refetchInterval: GRID_POLL_INTERVAL,
  });
}

export function useAddSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      subscription_id: string;
      subscription_name?: string;
      environment?: string;
      notes?: string;
      enabled?: boolean;
    }) => {
      const { data } = await apiClient.post("/admin/subscriptions", payload);
      return data;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["admin", "subscriptions"] });
      qc.invalidateQueries({ queryKey: ["dashboard", "admin"] });
    },
  });
}

export function useToggleSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      subscription_id: string;
      enabled?: boolean;
      monitored?: boolean;
      updated_by?: string;
    }) => {
      const { subscription_id, ...body } = payload;
      const { data } = await apiClient.put(
        `/admin/subscriptions/${subscription_id}/toggle`,
        body,
      );
      return data;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["admin", "subscriptions"] });
      qc.invalidateQueries({ queryKey: ["dashboard", "admin"] });
    },
  });
}

export function useUpdateSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      subscription_id: string;
      subscription_name?: string;
      environment?: string;
      notes?: string;
      updated_by?: string;
    }) => {
      const { subscription_id, ...body } = payload;
      const { data } = await apiClient.put(
        `/admin/subscriptions/${subscription_id}`,
        body,
      );
      return data;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["admin", "subscriptions"] });
      qc.invalidateQueries({ queryKey: ["dashboard", "admin"] });
    },
  });
}

export function useDeleteSubscription() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (subscriptionId: string) => {
      const { data } = await apiClient.delete(
        `/admin/subscriptions/${subscriptionId}`,
      );
      return data;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["admin", "subscriptions"] });
      qc.invalidateQueries({ queryKey: ["dashboard", "admin"] });
    },
  });
}

export function useDiscoverSubscriptions() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data } = await apiClient.post("/admin/subscriptions/discover");
      return data;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["admin", "subscriptions"] });
      qc.invalidateQueries({ queryKey: ["dashboard", "admin"] });
    },
  });
}

export function useSyncSubscriptions() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data } = await apiClient.post("/admin/subscriptions/sync");
      return data;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["admin", "subscriptions"] });
      qc.invalidateQueries({ queryKey: ["dashboard", "admin"] });
    },
  });
}

// ── Admin Config CRUD ─────────────────────────────────────────────────

export function useAdminConfigs() {
  return useQuery<AdminConfigEntry[]>({
    queryKey: ["admin", "config"],
    queryFn: async () => {
      const { data } = await apiClient.get("/admin/config");
      return data;
    },
    staleTime: 60 * 1000,
  });
}

export function useUpsertAdminConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: {
      config_key: string;
      config_value: string;
      config_type?: string;
      description?: string;
      updated_by?: string;
    }) => {
      const { data } = await apiClient.put("/admin/config", payload);
      return data;
    },
    onSettled: () => {
      qc.invalidateQueries({ queryKey: ["admin", "config"] });
      qc.invalidateQueries({ queryKey: ["dashboard", "admin"] });
    },
  });
}

export function useReleaseOperationalCache() {
  const qc = useQueryClient();
  return useMutation<CacheReleaseResult, Error, void>({
    mutationFn: async () => {
      const { data } = await apiClient.post("/admin/cache/release");
      return data;
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["dashboard", "leadership"] });
      qc.invalidateQueries({ queryKey: ["dashboard", "leadership-sync-status"] });
      qc.invalidateQueries({ queryKey: ["optimization", "summary"] });
      qc.invalidateQueries({ queryKey: ["costs", "amortized-summary"] });
      qc.invalidateQueries({ queryKey: ["costs", "amortized-drilldown"] });
      qc.invalidateQueries({ queryKey: ["dashboard", "admin"] });
    },
  });
}

export function useAdminSystemHealth() {
  return useQuery({
    queryKey: ["admin", "health"],
    queryFn: async () => {
      const { data } = await apiClient.get("/admin/system/health");
      return data;
    },
    staleTime: 30 * 1000,
    refetchInterval: GRID_POLL_INTERVAL,
  });
}

// ── Key Vault ─────────────────────────────────────────────────────────

export interface KeyVaultInfo {
  name: string;
  id: string;
  location: string;
  subscription_id: string;
  resource_group: string;
  vault_uri: string;
  sku: string;
  tenant_id: string;
  soft_delete_enabled: boolean;
  purge_protection_enabled: boolean;
  rbac_enabled: boolean;
  provisioning_state: string;
  tags: Record<string, string>;
}

export interface SecretInfo {
  name: string;
  id: string;
  content_type: string;
  enabled: boolean;
  created: string | null;
  updated: string | null;
  expires: string | null;
  not_before: string | null;
  tags: Record<string, string>;
  managed: boolean;
}

export interface KeyInfo {
  name: string;
  kid: string;
  enabled: boolean;
  created: string | null;
  updated: string | null;
  expires: string | null;
  not_before: string | null;
  managed: boolean;
  tags: Record<string, string>;
}

export interface CertificateInfo {
  name: string;
  id: string;
  enabled: boolean;
  created: string | null;
  updated: string | null;
  expires: string | null;
  not_before: string | null;
  cn_name: string;
  san: string[];
  serial_number: string | null;
  thumbprint: string;
  tags: Record<string, string>;
}

export interface ExpiringItem {
  name: string;
  vault_name: string;
  type: string;
  expires: string;
  days_remaining: number;
  enabled: boolean;
}

export interface VaultSummary {
  name: string;
  vault_uri: string;
  location: string;
  subscription_id: string;
  secrets_count: number;
  keys_count: number;
  certificates_count: number;
  soft_delete: boolean;
  purge_protection: boolean;
  rbac_enabled: boolean;
}

export interface KeyVaultDashboard {
  total_vaults: number;
  total_secrets: number;
  total_keys: number;
  total_certificates: number;
  expiring_within_30_days: number;
  expiring_within_90_days: number;
  expiring_items: ExpiringItem[];
  vault_summaries: VaultSummary[];
  generated_at: string;
  source?: string;           // "database" | "azure_api"
  last_synced_at?: string;   // ISO timestamp of last DB sync
}

export function useKeyVaultDashboard() {
  return useQuery<KeyVaultDashboard>({
    queryKey: ["keyvault", "dashboard"],
    queryFn: async () => {
      const { data } = await apiClient.get("/keyvault/dashboard");
      return data;
    },
    staleTime: 5 * 60 * 1000,
    refetchInterval: DASHBOARD_POLL_INTERVAL,
  });
}

export async function refreshKeyVaultDashboard() {
  const { data } = await apiClient.get("/keyvault/dashboard?refresh=true");
  return data;
}

export function useKeyVaults() {
  return useQuery<KeyVaultInfo[]>({
    queryKey: ["keyvault", "vaults"],
    queryFn: async () => {
      const { data } = await apiClient.get("/keyvault/vaults");
      return data;
    },
    staleTime: 5 * 60 * 1000,
    refetchInterval: GRID_POLL_INTERVAL,
  });
}

export async function refreshKeyVaults() {
  const { data } = await apiClient.get("/keyvault/vaults?refresh=true");
  return data;
}

export function useVaultSecrets(vaultUri: string | null) {
  return useQuery<SecretInfo[]>({
    queryKey: ["keyvault", "secrets", vaultUri],
    queryFn: async () => {
      if (!vaultUri) return [];
      const { data } = await apiClient.get(`/keyvault/secrets?vault_uri=${encodeURIComponent(vaultUri)}`);
      return data;
    },
    enabled: !!vaultUri,
    staleTime: 30 * 1000,  // 30 s — allow quick invalidation after mutations
    refetchInterval: GRID_POLL_INTERVAL,
  });
}

export async function refreshVaultSecrets(vaultUri: string) {
  const { data } = await apiClient.get(`/keyvault/secrets?vault_uri=${encodeURIComponent(vaultUri)}&refresh=true`);
  return data;
}

export function useVaultKeys(vaultUri: string | null) {
  return useQuery<KeyInfo[]>({
    queryKey: ["keyvault", "keys", vaultUri],
    queryFn: async () => {
      if (!vaultUri) return [];
      const { data } = await apiClient.get(`/keyvault/keys?vault_uri=${encodeURIComponent(vaultUri)}`);
      return data;
    },
    enabled: !!vaultUri,
    staleTime: 30 * 1000,
    refetchInterval: GRID_POLL_INTERVAL,
  });
}

export async function refreshVaultKeys(vaultUri: string) {
  const { data } = await apiClient.get(`/keyvault/keys?vault_uri=${encodeURIComponent(vaultUri)}&refresh=true`);
  return data;
}

// ── Key Detail (view) ─────────────────────────────────────────────────

export interface KeyDetailResponse {
  name: string;
  kid: string;
  kty: string;
  key_ops: string[];
  key_size: number | null;
  crv: string | null;
  enabled: boolean;
  created: string | null;
  updated: string | null;
  expires: string | null;
  not_before: string | null;
  recovery_level: string;
  tags: Record<string, string>;
}

export function useKeyDetail(vaultUri: string | null, name: string | null) {
  return useQuery<KeyDetailResponse>({
    queryKey: ["keyvault", "key-detail", vaultUri, name],
    queryFn: async () => {
      const { data } = await apiClient.get(
        `/keyvault/keys/${name}?vault_uri=${encodeURIComponent(vaultUri!)}`
      );
      return data;
    },
    enabled: !!vaultUri && !!name,
    staleTime: 30 * 1000,
    gcTime: 60 * 1000,
  });
}

// ── Create / Delete Key ───────────────────────────────────────────────

export interface CreateKeyPayload {
  vault_uri: string;
  name: string;
  kty?: string;
  key_size?: number;
  key_ops?: string[];
  not_before?: string;
  expires?: string;
}

export function useCreateKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: CreateKeyPayload) => {
      const { data } = await apiClient.post("/keyvault/keys", payload);
      return data;
    },
    onSettled: async (_d, _e, vars) => {
      await new Promise((r) => setTimeout(r, 600));
      await qc.invalidateQueries({ queryKey: ["keyvault", "keys", vars.vault_uri] });
      qc.invalidateQueries({ queryKey: ["keyvault", "key-detail"] });
      qc.invalidateQueries({ queryKey: ["keyvault", "dashboard"] });
      qc.invalidateQueries({ queryKey: ["keyvault", "history"] });
    },
  });
}

export function useDeleteKey() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ vaultUri, name }: { vaultUri: string; name: string }) => {
      const { data } = await apiClient.delete(
        `/keyvault/keys/${name}?vault_uri=${encodeURIComponent(vaultUri)}`
      );
      return data;
    },
    onSettled: async (_d, _e, vars) => {
      await new Promise((r) => setTimeout(r, 600));
      await qc.invalidateQueries({ queryKey: ["keyvault", "keys", vars.vaultUri] });
      qc.invalidateQueries({ queryKey: ["keyvault", "key-detail"] });
      qc.invalidateQueries({ queryKey: ["keyvault", "dashboard"] });
      qc.invalidateQueries({ queryKey: ["keyvault", "history"] });
    },
  });
}

export function useVaultCertificates(vaultUri: string | null) {
  return useQuery<CertificateInfo[]>({
    queryKey: ["keyvault", "certificates", vaultUri],
    queryFn: async () => {
      if (!vaultUri) return [];
      const { data } = await apiClient.get(`/keyvault/certificates?vault_uri=${encodeURIComponent(vaultUri)}`);
      return data;
    },
    enabled: !!vaultUri,
    staleTime: 30 * 1000,
    refetchInterval: GRID_POLL_INTERVAL,
  });
}

export async function refreshVaultCertificates(vaultUri: string) {
  const { data } = await apiClient.get(`/keyvault/certificates?vault_uri=${encodeURIComponent(vaultUri)}&refresh=true`);
  return data;
}

// ── Certificate Detail ────────────────────────────────────────────────

export interface CertificateDetailResponse {
  name: string;
  id: string;
  thumbprint: string;
  thumbprint_sha256: string | null;
  cn_name: string;
  san: string[];
  serial_number: string | null;
  issuer_cn: string;
  subject: string;
  enabled: boolean;
  created: string | null;
  updated: string | null;
  expires: string | null;
  not_before: string | null;
  validity_months: number | null;
  key_type: string;
  key_size: number | null;
  key_usage: string[];
  issuer_name: string;
  auto_renew: boolean;
  tags: Record<string, string>;
}

export function useCertificateDetail(vaultUri: string | null, name: string | null) {
  return useQuery<CertificateDetailResponse>({
    queryKey: ["keyvault", "cert-detail", vaultUri, name],
    queryFn: async () => {
      const { data } = await apiClient.get(
        `/keyvault/certificates/${name}?vault_uri=${encodeURIComponent(vaultUri!)}`
      );
      return data;
    },
    enabled: !!vaultUri && !!name,
    staleTime: 60 * 1000,
    gcTime: 2 * 60 * 1000,
  });
}

// ── Secret Value (view / decode) ──────────────────────────────────────

export interface SecretValueResponse {
  name: string;
  value: string;
  content_type: string;
  is_base64: boolean;
  decoded_value: string | null;
  enabled: boolean;
  created: string | null;
  updated: string | null;
  not_before: string | null;
  expires: string | null;
}

export function useSecretValue(vaultUri: string | null, name: string | null) {
  return useQuery<SecretValueResponse>({
    queryKey: ["keyvault", "secret-value", vaultUri, name],
    queryFn: async () => {
      const { data } = await apiClient.get(
        `/keyvault/secrets/${name}?vault_uri=${encodeURIComponent(vaultUri!)}`
      );
      return data;
    },
    enabled: !!vaultUri && !!name,
    staleTime: 30 * 1000,       // 30 s — values can change
    gcTime: 60 * 1000,          // 1 min — don't cache long
  });
}

// ── Create / Update Secret ────────────────────────────────────────────

export interface CreateSecretPayload {
  vault_uri: string;
  name: string;
  value: string;
  content_type?: string;
  tags?: Record<string, string>;
  encode_base64?: boolean;
  not_before?: string;   // ISO date (defaults to today)
  expires?: string;      // ISO date (defaults to today + 360 days)
}

export function useCreateSecret() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (payload: CreateSecretPayload) => {
      const { data } = await apiClient.post("/keyvault/secrets", payload);
      return data;
    },
    onSettled: async (_d, _e, vars) => {
      // Brief delay — Azure KV needs a moment to propagate writes
      await new Promise((r) => setTimeout(r, 600));
      await qc.invalidateQueries({ queryKey: ["keyvault", "secrets", vars.vault_uri] });
      qc.invalidateQueries({ queryKey: ["keyvault", "secret-value"] });
      qc.invalidateQueries({ queryKey: ["keyvault", "dashboard"] });
      qc.invalidateQueries({ queryKey: ["keyvault", "history"] });
    },
  });
}

// ── Delete Secret ─────────────────────────────────────────────────────

export function useDeleteSecret() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ vaultUri, name }: { vaultUri: string; name: string }) => {
      const { data } = await apiClient.delete(
        `/keyvault/secrets/${name}?vault_uri=${encodeURIComponent(vaultUri)}`
      );
      return data;
    },
    onSettled: async (_d, _e, vars) => {
      // Brief delay — Azure KV needs a moment to propagate deletes
      await new Promise((r) => setTimeout(r, 600));
      await qc.invalidateQueries({ queryKey: ["keyvault", "secrets", vars.vaultUri] });
      qc.invalidateQueries({ queryKey: ["keyvault", "secret-value"] });
      qc.invalidateQueries({ queryKey: ["keyvault", "dashboard"] });
      qc.invalidateQueries({ queryKey: ["keyvault", "history"] });
    },
  });
}

export function useKeyVaultAuditHistory(vaultUri: string | null, limit: number = 200, days: number = 90) {
  return useQuery<KeyVaultAuditHistoryResponse>({
    queryKey: ["keyvault", "history", vaultUri, limit, days],
    queryFn: async () => {
      const params = new URLSearchParams({
        limit: String(limit),
        days: String(days),
      });
      if (vaultUri) {
        params.set("vault_uri", vaultUri);
      }

      const { data } = await apiClient.get(`/keyvault/history?${params.toString()}`);
      return data;
    },
    enabled: !!vaultUri,
    staleTime: 30 * 1000,
    refetchInterval: GRID_POLL_INTERVAL,
  });
}

// ── KeyVault Sync (DB-backed) ─────────────────────────────────────────

export interface SyncStatusInfo {
  id: number;
  sync_type: string;        // "full" | "vault" | "incremental"
  status: string;           // "running" | "completed" | "partial" | "failed"
  started_at: string;
  completed_at: string | null;
  vaults_synced: number;
  secrets_synced: number;
  keys_synced: number;
  certificates_synced: number;
  error_message: string | null;
  triggered_by: string;     // "scheduler" | "manual" | "mutation" | "startup"
}

export interface KeyVaultAuditEntry {
  id: number;
  timestamp: string | null;
  user_id: string;
  user_email: string | null;
  action: string;
  resource_type: string;
  resource_id: string | null;
  resource_name: string;
  vault_uri: string;
  vault_name: string;
  status: string;
  summary: string;
  details: Record<string, unknown>;
}

export interface KeyVaultAuditHistoryResponse {
  history: KeyVaultAuditEntry[];
  count: number;
}

export function useKeyVaultSyncStatus(limit: number = 5) {
  return useQuery<SyncStatusInfo[]>({
    queryKey: ["keyvault", "sync-status", limit],
    queryFn: async () => {
      const { data } = await apiClient.get(`/keyvault/sync/status?limit=${limit}`);
      return data.recent_syncs ?? data;
    },
    staleTime: 15 * 1000,      // 15 s — poll frequently for running syncs
    refetchInterval: 30 * 1000, // auto-refresh every 30 s
  });
}

export function useKeyVaultSync() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      const { data } = await apiClient.post("/keyvault/sync");
      return data;
    },
    onSettled: async () => {
      // Invalidate all keyvault queries so UI picks up fresh DB data
      await qc.invalidateQueries({ queryKey: ["keyvault"] });
    },
  });
}

export function useKeyVaultSyncVault() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ vaultName, vaultUri }: { vaultName: string; vaultUri: string }) => {
      const { data } = await apiClient.post(
        `/keyvault/sync/${encodeURIComponent(vaultName)}`,
        null,
        { params: { vault_uri: vaultUri } },
      );
      return data;
    },
    onSettled: async () => {
      await qc.invalidateQueries({ queryKey: ["keyvault"] });
    },
  });
}

export async function triggerKeyVaultSync() {
  const { data } = await apiClient.post("/keyvault/sync");
  return data;
}

// ── Environment Cost Details ──────────────────────────────────────────

export interface EnvCostService {
  service_name: string;
  monthly_costs: Record<string, number>;
  total: number;
}

export interface EnvCostDetails {
  environment: string;
  months: string[];
  month_labels: Record<string, string>;
  services: EnvCostService[];
  monthly_totals: Record<string, number>;
  grand_total: number;
  available_environments: string[];
  generated_at: string;
}

export function useEnvCostDetails(environment: string, months: number = 3) {
  return useQuery<EnvCostDetails>({
    queryKey: ["costs", "env-breakdown", environment, months],
    queryFn: async () => {
      const { data } = await apiClient.get(
        `/costs/env-breakdown?environment=${encodeURIComponent(environment)}&months=${months}`
      );
      // Coerce Decimal strings → numbers
      if (data.services) {
        data.services = data.services.map((s: EnvCostService) => ({
          ...s,
          total: Number(s.total),
          monthly_costs: Object.fromEntries(
            Object.entries(s.monthly_costs || {}).map(([k, v]) => [k, Number(v)])
          ),
        }));
      }
      if (data.monthly_totals) {
        data.monthly_totals = Object.fromEntries(
          Object.entries(data.monthly_totals).map(([k, v]) => [k, Number(v)])
        );
      }
      data.grand_total = Number(data.grand_total ?? 0);
      return data;
    },
    staleTime: 5 * 60 * 1000,
    refetchInterval: SLOW_GRID_POLL_INTERVAL,
  });
}

// ── Non-Prod vs Prod Trend ────────────────────────────────────────────

export interface NonProdVsProdPoint {
  month_key: string;
  month: string;
  non_prod: number;
  prod: number;
  total: number;
}

export interface NonProdVsProdTrend {
  months: number;
  data: NonProdVsProdPoint[];
  generated_at: string;
}

export function useNonProdVsProdTrend(months: number = 6) {
  return useQuery<NonProdVsProdTrend>({
    queryKey: ["costs", "nonprod-vs-prod", months],
    queryFn: async () => {
      const { data } = await apiClient.get(
        `/costs/nonprod-vs-prod?months=${months}`
      );
      if (data.data) {
        data.data = data.data.map((d: NonProdVsProdPoint) => ({
          ...d,
          non_prod: Number(d.non_prod),
          prod: Number(d.prod),
          total: Number(d.total),
        }));
      }
      return data;
    },
    staleTime: 5 * 60 * 1000,
  });
}

// ── Amortized Cost (Blob CSV Exports) ─────────────────────────────────

export interface AmortizedDailyTrendPoint {
  date: string;
  cost: number | null;
  prod: number | null;
  non_prod: number | null;
}

export interface AmortizedBreakdownItem {
  name: string;
  cost: number;
  pct: number;
}

export interface AmortizedTopResource {
  resource_name: string;
  resource_group: string;
  resource_type: string;
  meter_category: string;
  location: string;
  subscription: string;
  cost: number;
}

export interface AmortizedPivotService {
  service_name: string;
  monthly_costs: Record<string, number>;
  total: number;
}

export interface AmortizedMonthlyPivot {
  months: string[];
  month_labels: Record<string, string>;
  services: AmortizedPivotService[];
  monthly_totals: Record<string, number>;
  grand_total: number;
}

export interface AmortizedEnvComparison {
  totals: Record<string, number>;
  monthly: Record<string, Record<string, number>>;
}

export interface AmortizedCostSummary {
  environment: string;
  total_cost: number;
  row_count: number;
  date_range: { start: string; end: string };
  source_date_range: { start: string; end: string };
  latest_available_date: string | null;
  has_pending_source_data: boolean;
  daily_trend: AmortizedDailyTrendPoint[];
  service_breakdown: AmortizedBreakdownItem[];
  resource_group_breakdown: AmortizedBreakdownItem[];
  resource_type_breakdown: AmortizedBreakdownItem[];
  location_breakdown: AmortizedBreakdownItem[];
  subscription_breakdown: AmortizedBreakdownItem[];
  top_resources: AmortizedTopResource[];
  monthly_pivot: AmortizedMonthlyPivot;
  env_comparison: AmortizedEnvComparison;
  charge_type_breakdown: { name: string; cost: number }[];
  pricing_model_breakdown: { name: string; cost: number }[];
  daily_by_service: Record<string, number | string | null>[];
  top_service_names: string[];
  generated_at: string;
}

export interface AmortizedDrilldownResource {
  resource_name: string;
  resource_group: string;
  resource_type: string;
  meter_category: string;
  location: string;
  subscription: string;
  cost: number;
  active_days: number;
}

export interface AmortizedDrilldown {
  filters: {
    environment: string;
    resource_group: string | null;
    meter_category: string | null;
    subscription: string | null;
  };
  total_cost: number;
  row_count: number;
  resources: AmortizedDrilldownResource[];
  daily_trend: { date: string; cost: number }[];
  generated_at: string;
}

export function useAmortizedCostSummary(
  env: string = "ALL",
  months: number = 2,
  refresh: boolean = false,
) {
  return useQuery<AmortizedCostSummary>({
    queryKey: ["costs", "amortized-summary", env, months, refresh],
    queryFn: async () => {
      const params = new URLSearchParams({ env, months: String(months) });
      if (refresh) params.set("refresh", "true");
      const { data } = await apiClient.get(`/costs/amortized-summary?${params}`);
      return data;
    },
    staleTime: SLOW_GRID_POLL_INTERVAL, // match refetch interval so every poll actually runs
    gcTime: 60 * 60 * 1000,
    refetchInterval: SLOW_GRID_POLL_INTERVAL,
  });
}

// ── Amortized Cost Sync (Azure Cost API -> DB) ───────────────────────

export interface AmortizedCostSyncStatus {
  last_sync: string | null;
  started_at: string | null;
  status: string | null;
  triggered_by: string | null;
  months_synced: number | null;
  rows_synced: number | null;
  total_cost: number | null;
  duration_seconds: number | null;
  error_message: string | null;
  monitored_subscription_ids?: string[];
  monitored_subscription_count?: number;
}

export interface AmortizedCostSyncResult {
  status: string;
  months_synced?: number;
  rows_synced?: number;
  total_cost?: number;
  started_at: string;
  completed_at: string;
  duration_seconds?: number;
  error?: string;
}

export function useAmortizedCostSyncStatus() {
  return useQuery<AmortizedCostSyncStatus>({
    queryKey: ["costs", "amortized-sync-status"],
    queryFn: async () => {
      const { data } = await apiClient.get("/costs/amortized/sync-status");
      return data;
    },
    staleTime: 15 * 1000,                       // 15 s — match KeyVault cadence
    refetchInterval: SYNC_STATUS_POLL_INTERVAL,  // 30 s auto-refresh
    retry: 1,
  });
}

export function useAmortizedCostSync() {
  const qc = useQueryClient();
  return useMutation<AmortizedCostSyncResult, Error, { months?: number }>({
    mutationFn: async ({ months = 2 }) => {
      const { data } = await apiClient.post(`/costs/amortized/sync?months=${months}`);
      if (!data || data.status !== "completed") {
        throw new Error(data?.error || data?.detail || "Amortized cost sync failed");
      }

      return {
        ...data,
        months_synced: Number(data.months_synced ?? months),
        rows_synced: Number(data.rows_synced ?? 0),
        total_cost: Number(data.total_cost ?? 0),
        duration_seconds: Number(data.duration_seconds ?? 0),
      };
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["costs", "amortized-summary"] });
      qc.invalidateQueries({ queryKey: ["costs", "amortized-drilldown"] });
      qc.invalidateQueries({ queryKey: ["costs", "amortized-sync-status"] });
    },
  });
}

export function useAmortizedDrilldown(
  env: string = "ALL",
  months: number = 2,
  filters: {
    resource_group?: string;
    meter_category?: string;
    subscription?: string;
  } = {},
  enabled: boolean = true,
) {
  return useQuery<AmortizedDrilldown>({
    queryKey: ["costs", "amortized-drilldown", env, months, filters],
    queryFn: async () => {
      const params = new URLSearchParams({ env, months: String(months) });
      if (filters.resource_group) params.set("resource_group", filters.resource_group);
      if (filters.meter_category) params.set("meter_category", filters.meter_category);
      if (filters.subscription) params.set("subscription", filters.subscription);
      const { data } = await apiClient.get(`/costs/amortized-drilldown?${params}`);
      return data;
    },
    enabled,
    staleTime: 10 * 60 * 1000,
    gcTime: 60 * 60 * 1000,
    refetchInterval: SLOW_GRID_POLL_INTERVAL,
  });
}


