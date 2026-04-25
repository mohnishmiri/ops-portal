import pytest

from app.core.config import settings
from app.schemas.cost import (
    CostByGroup,
    CostDataPoint,
    CostTrendDirection,
    GroupByDimension,
    KPIMetric,
    LeadershipAdvisorOptimizationSummary,
    LeadershipAdvisorRecommendation,
    LeadershipAdvisorRequest,
    LeadershipAdvisorResource,
    LeadershipAdvisorResponse,
    LeadershipAdvisorSyncStatus,
    LeadershipAdvisorTrend,
    LeadershipAdvisorWastage,
    LeadershipDashboard,
    LeadershipForecastResponse,
    MonthlyCostPoint,
    NonProdVsProdPoint,
)
from app.services.leadership_advisor_service import LeadershipAdvisorService


def _payload() -> LeadershipAdvisorRequest:
    return LeadershipAdvisorRequest(
        dashboard=LeadershipDashboard(
            kpis=[
                KPIMetric(
                    name="Total Monthly Spend",
                    value=57324,
                    unit="USD",
                    trend=CostTrendDirection.DOWN,
                    change_pct=-47.5,
                    description="Current month Azure spend across monitored subscriptions",
                ),
                KPIMetric(
                    name="Month-over-Month Change",
                    value=-47.5,
                    unit="%",
                    trend=CostTrendDirection.DOWN,
                    change_pct=-47.5,
                    description="Cost change compared to previous month",
                ),
            ],
            cost_trend=[
                CostDataPoint(
                    date="2026-03-01",
                    cost=100,
                    group_value="PROD-1",
                    group_dimension=GroupByDimension.SUBSCRIPTION,
                )
            ],
            top_spenders=[
                CostByGroup(
                    group_dimension=GroupByDimension.SUBSCRIPTION,
                    group_value="PROD-31599-ATTCC",
                    total_cost=42000,
                    percentage_of_total=73.7,
                )
            ],
            six_month_trend=[
                MonthlyCostPoint(
                    month="2025-10",
                    month_label="Oct 2025",
                    total_cost=89000,
                    non_prod_cost=24000,
                    prod_cost=65000,
                    subscription_breakdown={"PROD-31599-ATTCC": 65000},
                ),
                MonthlyCostPoint(
                    month="2025-11",
                    month_label="Nov 2025",
                    total_cost=94000,
                    non_prod_cost=26000,
                    prod_cost=68000,
                    subscription_breakdown={"PROD-31599-ATTCC": 68000},
                ),
                MonthlyCostPoint(
                    month="2025-12",
                    month_label="Dec 2025",
                    total_cost=101000,
                    non_prod_cost=30000,
                    prod_cost=71000,
                    subscription_breakdown={"PROD-31599-ATTCC": 71000},
                ),
                MonthlyCostPoint(
                    month="2026-01",
                    month_label="Jan 2026",
                    total_cost=137000,
                    non_prod_cost=50000,
                    prod_cost=87000,
                    subscription_breakdown={"PROD-31599-ATTCC": 87000},
                ),
                MonthlyCostPoint(
                    month="2026-02",
                    month_label="Feb 2026",
                    total_cost=109000,
                    non_prod_cost=32000,
                    prod_cost=77000,
                    subscription_breakdown={"PROD-31599-ATTCC": 77000},
                ),
                MonthlyCostPoint(
                    month="2026-03",
                    month_label="Mar 2026",
                    total_cost=59200,
                    non_prod_cost=15400,
                    prod_cost=43800,
                    subscription_breakdown={"PROD-31599-ATTCC": 43800},
                ),
            ],
            savings_opportunities=192,
            report_date="2026-03-15T11:02:58",
        ),
        optimization=LeadershipAdvisorOptimizationSummary(
            total_recommendations=12,
            total_estimated_monthly_savings=5000,
            total_estimated_annual_savings=60000,
            wastage=LeadershipAdvisorWastage(
                total_monthly_waste=5000,
                idle_vms_count=2,
                unattached_disks_count=1,
                orphaned_snapshots_count=1,
                overprovisioned_count=3,
                details=[],
            ),
            top_recommendations=[
                LeadershipAdvisorRecommendation(
                    id="1",
                    category="Compute",
                    priority="high",
                    title="Rightsize VM",
                    description="Reduce oversized VM instance",
                    resource=LeadershipAdvisorResource(
                        resource_name="vm-prod-01",
                        resource_type="Virtual Machine",
                        resource_group="rg-prod",
                        subscription_id="sub-1",
                        location="eastus2",
                    ),
                    current_monthly_cost=400,
                    estimated_monthly_savings=150,
                    estimated_annual_savings=1800,
                    confidence="high",
                    confidence_score=0.92,
                    action_required="Resize",
                    risk_level="low",
                    status="active",
                    source="advisor",
                )
            ],
        ),
        trend=LeadershipAdvisorTrend(
            months=6,
            data=[
                NonProdVsProdPoint(
                    month_key="2025-10",
                    month="Oct 2025",
                    non_prod=24000,
                    prod=65000,
                    total=89000,
                ),
                NonProdVsProdPoint(
                    month_key="2025-11",
                    month="Nov 2025",
                    non_prod=26000,
                    prod=68000,
                    total=94000,
                ),
                NonProdVsProdPoint(
                    month_key="2025-12",
                    month="Dec 2025",
                    non_prod=30000,
                    prod=71000,
                    total=101000,
                ),
                NonProdVsProdPoint(
                    month_key="2026-01",
                    month="Jan 2026",
                    non_prod=50000,
                    prod=87000,
                    total=137000,
                ),
                NonProdVsProdPoint(
                    month_key="2026-02",
                    month="Feb 2026",
                    non_prod=32000,
                    prod=77000,
                    total=109000,
                ),
                NonProdVsProdPoint(
                    month_key="2026-03",
                    month="Mar 2026",
                    non_prod=15400,
                    prod=43800,
                    total=59200,
                ),
            ],
            generated_at="2026-03-15T11:02:58",
        ),
        sync_status=LeadershipAdvisorSyncStatus(
            last_sync="2026-03-15T11:02:58",
            status="completed",
            triggered_by="scheduler",
        ),
    )


@pytest.mark.anyio
async def test_generate_advice_falls_back_when_ollama_fails(monkeypatch):
    service = LeadershipAdvisorService()
    monkeypatch.setattr(settings, "AZURE_PRICING_API_URL", "")

    async def _fail(*_args, **_kwargs):
        raise RuntimeError("ollama unavailable")

    monkeypatch.setattr(service, "_request_ollama_response", _fail)

    result = await service.generate_advice(_payload())

    assert isinstance(result, LeadershipAdvisorResponse)
    assert result.source == "fallback"
    assert result.azure_pricing.status == "ollama-only"
    assert result.opportunities


@pytest.mark.anyio
async def test_generate_forecast_falls_back_when_ollama_fails(monkeypatch):
    service = LeadershipAdvisorService()

    async def _fail(*_args, **_kwargs):
        raise RuntimeError("ollama unavailable")

    monkeypatch.setattr(service, "_request_ollama_forecast_response", _fail)

    result = await service.generate_forecast(_payload())

    assert isinstance(result, LeadershipForecastResponse)
    assert result.source == "fallback"
    assert result.forecast_months == 6
    assert len(result.points) == 12


@pytest.mark.anyio
async def test_generate_forecast_uses_ollama_points(monkeypatch):
    service = LeadershipAdvisorService()

    async def _ok(*_args, **_kwargs):
        return {
            "summary": "Ollama projected a moderate prod decline and flatter non-prod run-rate over the next six months.",
            "forecast_points": [
                {
                    "month": "2026-04",
                    "prod_forecast": 42000,
                    "non_prod_forecast": 14000,
                },
                {
                    "month": "2026-05",
                    "prod_forecast": 41000,
                    "non_prod_forecast": 13500,
                },
                {
                    "month": "2026-06",
                    "prod_forecast": 40000,
                    "non_prod_forecast": 13000,
                },
                {
                    "month": "2026-07",
                    "prod_forecast": 39500,
                    "non_prod_forecast": 12800,
                },
                {
                    "month": "2026-08",
                    "prod_forecast": 39000,
                    "non_prod_forecast": 12500,
                },
                {
                    "month": "2026-09",
                    "prod_forecast": 38500,
                    "non_prod_forecast": 12300,
                },
            ],
        }

    monkeypatch.setattr(service, "_request_ollama_forecast_response", _ok)

    result = await service.generate_forecast(_payload())

    assert result.source == "ollama"
    assert result.forecast_months == 6
    assert len(result.points) == 12
    assert result.points[-1].prod_forecast == 38500


@pytest.mark.anyio
async def test_generate_advice_handles_missing_pricing_filter(monkeypatch):
    service = LeadershipAdvisorService()
    payload = _payload()
    assert payload.optimization is not None
    payload.optimization.top_recommendations[0].resource.location = ""

    azure_pricing, pricing_context = await service._get_azure_pricing_context(payload)

    assert azure_pricing.status == "ollama-only"
    assert pricing_context is None


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def raise_for_status(self):
        return None

    def json(self):
        return self._body


class _FakeAsyncClient:
    last_request = None

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, json=None, headers=None):
        _FakeAsyncClient.last_request = {
            "method": "POST",
            "url": url,
            "json": json,
            "headers": headers or {},
        }
        return _FakeResponse(
            {
                "response": (
                    '{"summary":"LLM summary","focus_areas":["Focus"],'
                    '"risks":["Risk"],"opportunities":[{"title":"Opportunity",'
                    '"detail":"Detail","estimated_savings":"$1000/yr"}]}'
                )
            }
        )

    async def get(self, url, params=None):
        _FakeAsyncClient.last_request = {
            "method": "GET",
            "url": url,
            "params": params or {},
        }
        return _FakeResponse(
            {
                "Items": [
                    {
                        "productName": "Virtual Machines FS Series",
                        "skuName": "F16s",
                        "armRegionName": "eastus2",
                        "retailPrice": 0.42,
                        "unitOfMeasure": "1 Hour",
                    }
                ]
            }
        )


@pytest.mark.anyio
async def test_request_ollama_response_sends_configured_auth_header(monkeypatch):
    service = LeadershipAdvisorService()
    monkeypatch.setattr("app.services.leadership_advisor_service.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(settings, "OLLAMA_AUTH_HEADER_NAME", "Authorization")
    monkeypatch.setattr(settings, "OLLAMA_AUTH_HEADER_VALUE", "Bearer secret-token")
    monkeypatch.setattr(settings, "AZURE_PRICING_API_URL", "")
    azure_pricing, azure_pricing_context = await service._get_azure_pricing_context(_payload())

    result = await service._request_ollama_response(
        _payload(),
        azure_pricing=azure_pricing,
        azure_pricing_context=azure_pricing_context,
    )

    assert result["summary"] == "LLM summary"
    assert _FakeAsyncClient.last_request is not None
    assert _FakeAsyncClient.last_request["headers"]["Authorization"] == "Bearer secret-token"


@pytest.mark.anyio
async def test_generate_advice_uses_official_azure_pricing_api(monkeypatch):
    service = LeadershipAdvisorService()
    monkeypatch.setattr("app.services.leadership_advisor_service.httpx.AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(settings, "AZURE_PRICING_API_URL", "https://prices.azure.com/api/retail/prices")

    result = await service.generate_advice(_payload())

    assert result.azure_pricing.status == "connected"
    assert result.azure_pricing.resources_considered == 1
    assert result.source == "ollama"


def test_build_pricing_query_uses_official_filter_contract():
    service = LeadershipAdvisorService()

    query = service._build_pricing_query(_payload())

    assert query is not None
    assert query["currencyCode"] == "USD"
    assert "serviceName eq 'Virtual Machines'" in query["$filter"]
    assert "armRegionName eq 'eastus2'" in query["$filter"]
