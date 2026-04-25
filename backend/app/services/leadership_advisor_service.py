"""Leadership AI advisor service.

Builds an executive-ready prompt from existing dashboard data, optionally enriches
the context with Azure MCP metadata when available, and proxies generation calls
through the backend so the frontend does not depend on direct Ollama access.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from time import perf_counter
from typing import Any

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.admin_config import get_effective_cache_ttl_seconds, get_ollama_enabled
from app.core.config import settings
from app.core.db_cache import cache_manager
from app.schemas.cost import (
    AzurePricingEnrichmentStatus,
    LeadershipAdvisorInsight,
    LeadershipAdvisorRequest,
    LeadershipAdvisorResponse,
    LeadershipForecastPoint,
    LeadershipForecastResponse,
)

logger = structlog.get_logger(__name__)


class LeadershipAdvisorService:
    """Generate executive cost guidance using Ollama with safe fallbacks."""

    def __init__(self, db: AsyncSession | None = None) -> None:
        self._db = db

    async def generate_forecast(self, payload: LeadershipAdvisorRequest) -> LeadershipForecastResponse:
        started = perf_counter()
        cache_key = self._forecast_cache_key(payload)
        cached = await cache_manager.get_cached(cache_key)
        if cached:
            try:
                response = LeadershipForecastResponse.model_validate_json(cached)
                logger.info(
                    "leadership_forecast_served",
                    source="cache",
                    report_date=payload.report_date,
                    elapsed_ms=round((perf_counter() - started) * 1000, 2),
                )
                return response
            except Exception:
                pass

        historical_points = self._build_historical_forecast_points(payload)
        future_specs = self._build_future_month_specs(payload, months=6)

        if not historical_points or not future_specs:
            response = LeadershipForecastResponse(
                source="fallback",
                model="local-heuristic",
                generated_at=datetime.now(UTC).isoformat(),
                summary="Insufficient six-month history was available, so no Ollama forecast could be generated.",
                historical_months=len(historical_points),
                forecast_months=0,
                forecast_year=datetime.now(UTC).year,
                points=historical_points,
            )
            await self._cache_model(cache_key, response)
            logger.info(
                "leadership_forecast_served",
                source="fallback-empty-history",
                report_date=payload.report_date,
                elapsed_ms=round((perf_counter() - started) * 1000, 2),
            )
            return response

        ollama_enabled = await get_ollama_enabled(self._db)
        if not ollama_enabled:
            logger.info("leadership_forecast_ollama_disabled", report_date=payload.report_date)
            response = self._build_fallback_forecast_response(
                payload=payload,
                historical_points=historical_points,
                future_specs=future_specs,
                reason="Ollama LLM is disabled via Admin panel. The chart is using a baseline projection from the latest six months of prod and non-prod history.",
            )
            await self._cache_model(cache_key, response)
            return response

        try:
            parsed = await self._request_ollama_forecast_response(payload)
            forecast_points = self._merge_ollama_forecast_points(
                parsed=parsed,
                historical_points=historical_points,
                future_specs=future_specs,
            )
            response = LeadershipForecastResponse(
                source="ollama",
                model=settings.OLLAMA_MODEL,
                generated_at=datetime.now(UTC).isoformat(),
                summary=parsed.get(
                    "summary",
                    "Ollama generated a six-month prod and non-prod forecast from the latest six-month history.",
                ),
                historical_months=len(historical_points),
                forecast_months=len(forecast_points),
                forecast_year=int(future_specs[-1][0].split("-")[0]),
                points=[*historical_points, *forecast_points],
            )
            await self._cache_model(cache_key, response)
            logger.info(
                "leadership_forecast_served",
                source="ollama",
                report_date=payload.report_date,
                elapsed_ms=round((perf_counter() - started) * 1000, 2),
            )
            return response
        except Exception as exc:
            logger.warning(
                "leadership_forecast_fallback",
                error=str(exc)[:300],
                error_type=type(exc).__name__,
                ollama_url=settings.OLLAMA_BASE_URL,
                timeout=settings.OLLAMA_TIMEOUT_SECONDS,
            )
            response = self._build_fallback_forecast_response(
                payload=payload,
                historical_points=historical_points,
                future_specs=future_specs,
            )
            await self._cache_model(cache_key, response)
            logger.info(
                "leadership_forecast_served",
                source="fallback",
                report_date=payload.report_date,
                elapsed_ms=round((perf_counter() - started) * 1000, 2),
            )
            return response

    async def generate_advice(self, payload: LeadershipAdvisorRequest) -> LeadershipAdvisorResponse:
        started = perf_counter()
        cache_key = self._advisor_cache_key(payload)
        cached = await cache_manager.get_cached(cache_key)
        if cached:
            try:
                response = LeadershipAdvisorResponse.model_validate_json(cached)
                logger.info(
                    "leadership_advisor_served",
                    source="cache",
                    report_date=payload.report_date,
                    elapsed_ms=round((perf_counter() - started) * 1000, 2),
                )
                return response
            except Exception:
                pass

        azure_pricing, azure_pricing_context = await self._get_azure_pricing_context(payload)

        ollama_enabled = await get_ollama_enabled(self._db)
        if not ollama_enabled:
            logger.info("leadership_advisor_ollama_disabled", report_date=payload.report_date)
            response = self._build_fallback_response(payload, azure_pricing)
            await self._cache_model(cache_key, response)
            return response

        try:
            parsed = await self._request_ollama_response(payload, azure_pricing, azure_pricing_context)
            response = LeadershipAdvisorResponse(
                source="ollama",
                model=settings.OLLAMA_MODEL,
                generated_at=datetime.now(UTC).isoformat(),
                summary=parsed.get("summary", "No executive summary returned."),
                focus_areas=list(parsed.get("focus_areas", []))[:4],
                risks=list(parsed.get("risks", []))[:4],
                opportunities=[
                    LeadershipAdvisorInsight(
                        title=item.get("title", "Opportunity"),
                        detail=item.get("detail", "No detail provided."),
                        estimated_savings=item.get("estimated_savings"),
                    )
                    for item in list(parsed.get("opportunities", []))[:4]
                ],
                azure_pricing=azure_pricing,
            )
            await self._cache_model(cache_key, response)
            logger.info(
                "leadership_advisor_served",
                source="ollama",
                report_date=payload.report_date,
                elapsed_ms=round((perf_counter() - started) * 1000, 2),
            )
            return response
        except Exception as exc:
            logger.warning(
                "leadership_advisor_fallback",
                error=str(exc)[:300],
            )
            response = self._build_fallback_response(payload, azure_pricing)
            await self._cache_model(cache_key, response)
            logger.info(
                "leadership_advisor_served",
                source="fallback",
                report_date=payload.report_date,
                elapsed_ms=round((perf_counter() - started) * 1000, 2),
            )
            return response

    async def _get_azure_pricing_context(
        self, payload: LeadershipAdvisorRequest
    ) -> tuple[AzurePricingEnrichmentStatus, dict[str, Any] | None]:
        resources_considered = len(payload.optimization.top_recommendations) if payload.optimization else 0
        if not settings.AZURE_PRICING_API_URL:
            return (
                AzurePricingEnrichmentStatus(
                    status="ollama-only",
                    details="Azure pricing enrichment is not configured; advisor is using Ollama with application cost data only.",
                    resources_considered=resources_considered,
                ),
                None,
            )

        query = self._build_pricing_query(payload)
        if query is None:
            return (
                AzurePricingEnrichmentStatus(
                    status="ollama-only",
                    details="Azure pricing enrichment could not infer a useful SKU or service filter from the current recommendations; advisor is using Ollama-only mode.",
                    resources_considered=resources_considered,
                ),
                None,
            )

        timeout = httpx.Timeout(settings.AZURE_PRICING_TIMEOUT_SECONDS)

        try:
            async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                response = await client.get(
                    settings.AZURE_PRICING_API_URL,
                    params=query,
                )
                response.raise_for_status()

            body = response.json()
            if not isinstance(body, dict):
                raise ValueError("Azure pricing response was not a JSON object")

            items = body.get("Items") or body.get("items") or []
            if not isinstance(items, list):
                items = []

            sample_prices = []
            for item in items[:5]:
                if not isinstance(item, dict):
                    continue
                sample_prices.append(
                    {
                        "productName": item.get("productName"),
                        "skuName": item.get("skuName"),
                        "armRegionName": item.get("armRegionName"),
                        "retailPrice": item.get("retailPrice"),
                        "unitOfMeasure": item.get("unitOfMeasure"),
                    }
                )

            return (
                AzurePricingEnrichmentStatus(
                    status="connected" if sample_prices else "ollama-only",
                    details=(
                        f"Azure Retail Prices API returned {len(sample_prices)} pricing sample(s) for filter {query.get('$filter', '')}."
                        if sample_prices
                        else "Azure Retail Prices API returned no matching prices for the current recommendation filters; advisor is using Ollama-only mode."
                    ),
                    resources_considered=resources_considered,
                ),
                {
                    "query": query,
                    "sample_prices": sample_prices,
                    "count": len(sample_prices),
                    "next_page_link": body.get("NextPageLink"),
                },
            )
        except Exception as exc:
            logger.warning("leadership_advisor_azure_pricing_unavailable", error=str(exc)[:300])
            return (
                AzurePricingEnrichmentStatus(
                    status="ollama-only",
                    details=f"Azure Retail Prices API call failed, so advisor is continuing in Ollama-only mode. {str(exc)[:180]}",
                    resources_considered=resources_considered,
                ),
                None,
            )

    async def _request_ollama_response(
        self,
        payload: LeadershipAdvisorRequest,
        azure_pricing: AzurePricingEnrichmentStatus,
        azure_pricing_context: dict[str, Any] | None,
    ) -> dict:
        endpoint = settings.OLLAMA_BASE_URL.rstrip("/") + "/api/generate"
        timeout = httpx.Timeout(settings.OLLAMA_TIMEOUT_SECONDS)
        headers = self._build_headers(
            settings.OLLAMA_AUTH_HEADER_NAME,
            settings.OLLAMA_AUTH_HEADER_VALUE,
        )
        headers.setdefault("Content-Type", "application/json")

        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            response = await client.post(
                endpoint,
                json={
                    "model": settings.OLLAMA_MODEL,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.2},
                    "prompt": self._build_prompt(payload, azure_pricing, azure_pricing_context),
                },
                headers=headers,
            )
            response.raise_for_status()

        body = response.json()
        raw_response = body.get("response")
        if not isinstance(raw_response, str) or not raw_response.strip():
            raise ValueError("Ollama response payload missing response text")

        cleaned = raw_response.strip().replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise ValueError("Ollama response was not a JSON object")
        return parsed

    async def _request_ollama_forecast_response(
        self,
        payload: LeadershipAdvisorRequest,
    ) -> dict[str, Any]:
        endpoint = settings.OLLAMA_BASE_URL.rstrip("/") + "/api/generate"
        timeout = httpx.Timeout(settings.OLLAMA_TIMEOUT_SECONDS)
        headers = self._build_headers(
            settings.OLLAMA_AUTH_HEADER_NAME,
            settings.OLLAMA_AUTH_HEADER_VALUE,
        )
        headers.setdefault("Content-Type", "application/json")

        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            response = await client.post(
                endpoint,
                json={
                    "model": settings.OLLAMA_MODEL,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0.15},
                    "prompt": self._build_forecast_prompt(payload),
                },
                headers=headers,
            )
            response.raise_for_status()

        body = response.json()
        raw_response = body.get("response")
        if not isinstance(raw_response, str) or not raw_response.strip():
            raise ValueError("Ollama forecast payload missing response text")

        cleaned = raw_response.strip().replace("```json", "").replace("```", "").strip()
        parsed = json.loads(cleaned)
        if not isinstance(parsed, dict):
            raise ValueError("Ollama forecast response was not a JSON object")
        return parsed

    def _build_prompt(
        self,
        payload: LeadershipAdvisorRequest,
        azure_pricing: AzurePricingEnrichmentStatus,
        azure_pricing_context: dict[str, Any] | None,
    ) -> str:
        compact_context = {
            "report_date": payload.dashboard.report_date.isoformat(),
            "kpis": [item.model_dump(mode="json") for item in payload.dashboard.kpis],
            "top_spenders": [item.model_dump(mode="json") for item in payload.dashboard.top_spenders[:5]],
            "six_month_trend": [item.model_dump(mode="json") for item in payload.dashboard.six_month_trend],
            "optimization": (payload.optimization.model_dump(mode="json") if payload.optimization else None),
            "trend": payload.trend.model_dump(mode="json") if payload.trend else None,
            "sync_status": (payload.sync_status.model_dump(mode="json") if payload.sync_status else None),
            "azure_pricing": azure_pricing.model_dump(mode="json"),
            "azure_pricing_context": azure_pricing_context,
        }

        return "\n".join(
            [
                "You are an enterprise FinOps advisor for AT&T.",
                "Analyze the provided Azure cost dashboard context and return strict JSON only.",
                "Required JSON schema:",
                '{"summary":"string","focus_areas":["string"],"risks":["string"],"opportunities":[{"title":"string","detail":"string","estimated_savings":"string"}]}',
                "Keep the response executive-ready, concise, and action-oriented.",
                "Prioritize concrete savings actions, highlight concentration risks, and mention Azure Retail Prices API limitations if enrichment is unavailable.",
                f"Context: {json.dumps(compact_context, default=str)}",
            ]
        )

    def _build_forecast_prompt(self, payload: LeadershipAdvisorRequest) -> str:
        six_month_history = [
            {
                "month": point.month,
                "month_label": point.month_label,
                "prod_cost": self._to_number(point.prod_cost),
                "non_prod_cost": self._to_number(point.non_prod_cost),
                "total_cost": self._to_number(point.total_cost),
            }
            for point in payload.dashboard.six_month_trend
        ]

        return "\n".join(
            [
                "You are a forecasting assistant for AT&T FinOps leadership.",
                "Use the last 6 months of prod and non-prod monthly costs to forecast the next 6 months.",
                "Return strict JSON only.",
                "Required JSON schema:",
                '{"summary":"string","forecast_points":[{"month":"YYYY-MM","prod_forecast":12345.67,"non_prod_forecast":2345.67}]}',
                "Rules:",
                "- Return exactly 6 forecast points in chronological order after the final historical month.",
                "- Use non-negative numeric values only.",
                "- Keep the trend realistic relative to the provided history; avoid extreme jumps unless clearly implied by the data.",
                f"Historical six-month context: {json.dumps(six_month_history, default=str)}",
            ]
        )

    def _build_fallback_response(
        self,
        payload: LeadershipAdvisorRequest,
        azure_pricing: AzurePricingEnrichmentStatus,
    ) -> LeadershipAdvisorResponse:
        total_monthly_spend = self._find_kpi_value(payload, "monthly spend")
        monthly_change = self._find_kpi_value(payload, "month-over-month")
        top_spenders = payload.dashboard.top_spenders[:3]
        opportunities = [
            LeadershipAdvisorInsight(
                title=item.title,
                detail=f"{item.resource.resource_name} in {item.resource.resource_group}",
                estimated_savings=f"${self._to_number(item.estimated_annual_savings):,.0f}/yr",
            )
            for item in (payload.optimization.top_recommendations[:4] if payload.optimization else [])
        ]

        focus_areas = [
            f"Current monthly spend is ${total_monthly_spend:,.0f}; prioritize controls on the largest subscription and resource categories.",
            (
                f"{top_spenders[0].group_value} represents {top_spenders[0].percentage_of_total:.1f}% of current monitored spend."
                if top_spenders
                else "Subscription concentration data should be reviewed to isolate the main spend driver."
            ),
            (
                f"{payload.optimization.total_recommendations} optimization recommendations are available for execution."
                if payload.optimization
                else "Optimization recommendations are unavailable, so guidance is based on dashboard totals only."
            ),
        ]

        risks = [
            (
                f"Month-over-month spend is up {monthly_change:.1f}%, which increases short-term budget pressure."
                if monthly_change > 0
                else f"Month-over-month spend is down {abs(monthly_change):.1f}%; ensure savings are sustained."
            ),
            (
                f"The top two subscriptions together represent {sum(item.percentage_of_total for item in top_spenders[:2]):.1f}% of current spend."
                if len(top_spenders) >= 2
                else "A small number of subscriptions appear to drive most spend."
            ),
            azure_pricing.details,
        ]

        return LeadershipAdvisorResponse(
            source="fallback",
            model="local-heuristic",
            generated_at=datetime.now(UTC).isoformat(),
            summary=(
                f"Current monitored monthly spend is ${total_monthly_spend:,.0f}. "
                f"Existing optimization signals indicate up to ${self._to_number(payload.optimization.total_estimated_annual_savings) if payload.optimization else 0:,.0f} in annual savings if the highest-value actions are executed."
            ),
            focus_areas=focus_areas,
            risks=risks,
            opportunities=opportunities,
            azure_pricing=azure_pricing,
        )

    def _build_historical_forecast_points(self, payload: LeadershipAdvisorRequest) -> list[LeadershipForecastPoint]:
        ordered = sorted(payload.dashboard.six_month_trend, key=lambda item: item.month)
        return [
            LeadershipForecastPoint(
                month_key=item.month,
                month_label=item.month_label,
                prod_actual=self._to_number(item.prod_cost),
                non_prod_actual=self._to_number(item.non_prod_cost),
                total_actual=self._to_number(item.total_cost),
            )
            for item in ordered
        ]

    def _build_future_month_specs(self, payload: LeadershipAdvisorRequest, months: int) -> list[tuple[str, str]]:
        ordered = sorted(payload.dashboard.six_month_trend, key=lambda item: item.month)
        if not ordered:
            return []

        last_month = datetime.strptime(ordered[-1].month, "%Y-%m")
        specs: list[tuple[str, str]] = []
        for index in range(months):
            month_number = last_month.month + index + 1
            year = last_month.year + (month_number - 1) // 12
            month = ((month_number - 1) % 12) + 1
            month_key = f"{year}-{month:02d}"
            month_label = datetime(year, month, 1).strftime("%b %Y")
            specs.append((month_key, month_label))
        return specs

    def _build_fallback_forecast_response(
        self,
        payload: LeadershipAdvisorRequest,
        historical_points: list[LeadershipForecastPoint],
        future_specs: list[tuple[str, str]],
        reason: str | None = None,
    ) -> LeadershipForecastResponse:
        forecast_points = self._build_baseline_forecast_points(payload, future_specs)
        summary = (
            reason
            or "Ollama forecast generation was unavailable, so the chart is using a baseline projection from the latest six months of prod and non-prod history."
        )
        return LeadershipForecastResponse(
            source="fallback",
            model="local-heuristic",
            generated_at=datetime.now(UTC).isoformat(),
            summary=summary,
            historical_months=len(historical_points),
            forecast_months=len(forecast_points),
            forecast_year=(int(future_specs[-1][0].split("-")[0]) if future_specs else datetime.now(UTC).year),
            points=[*historical_points, *forecast_points],
        )

    def _build_baseline_forecast_points(
        self,
        payload: LeadershipAdvisorRequest,
        future_specs: list[tuple[str, str]],
    ) -> list[LeadershipForecastPoint]:
        historical_points = self._build_historical_forecast_points(payload)
        return self._build_baseline_forecast_points_from_history(historical_points, future_specs)

    def _build_baseline_forecast_points_from_history(
        self,
        historical_points: list[LeadershipForecastPoint],
        future_specs: list[tuple[str, str]],
    ) -> list[LeadershipForecastPoint]:
        if not historical_points:
            return []

        def _average_delta(values: list[float]) -> float:
            deltas = [values[index + 1] - values[index] for index in range(len(values) - 1)]
            return (sum(deltas) / len(deltas)) if deltas else 0.0

        prod_values = [self._to_number(item.prod_actual or 0) for item in historical_points]
        non_prod_values = [self._to_number(item.non_prod_actual or 0) for item in historical_points]
        last_prod = prod_values[-1]
        last_non_prod = non_prod_values[-1]
        avg_prod_delta = _average_delta(prod_values)
        avg_non_prod_delta = _average_delta(non_prod_values)

        forecast_points: list[LeadershipForecastPoint] = []
        for index, (month_key, month_label) in enumerate(future_specs):
            prod_forecast = max(0.0, last_prod + avg_prod_delta * (index + 1))
            non_prod_forecast = max(0.0, last_non_prod + avg_non_prod_delta * (index + 1))
            forecast_points.append(
                LeadershipForecastPoint(
                    month_key=month_key,
                    month_label=month_label,
                    prod_forecast=prod_forecast,
                    non_prod_forecast=non_prod_forecast,
                    total_forecast=prod_forecast + non_prod_forecast,
                )
            )
        return forecast_points

    def _merge_ollama_forecast_points(
        self,
        parsed: dict[str, Any],
        historical_points: list[LeadershipForecastPoint],
        future_specs: list[tuple[str, str]],
    ) -> list[LeadershipForecastPoint]:
        baseline = self._build_baseline_forecast_points_from_history(historical_points, future_specs)
        items = parsed.get("forecast_points")
        if not isinstance(items, list):
            items = []

        points: list[LeadershipForecastPoint] = []
        for index, (month_key, month_label) in enumerate(future_specs):
            baseline_point = baseline[index]
            candidate = items[index] if index < len(items) and isinstance(items[index], dict) else {}
            prod_forecast = self._safe_non_negative(
                candidate.get("prod_forecast"),
                self._to_number(baseline_point.prod_forecast or 0),
            )
            non_prod_forecast = self._safe_non_negative(
                candidate.get("non_prod_forecast"),
                self._to_number(baseline_point.non_prod_forecast or 0),
            )
            points.append(
                LeadershipForecastPoint(
                    month_key=month_key,
                    month_label=month_label,
                    prod_forecast=prod_forecast,
                    non_prod_forecast=non_prod_forecast,
                    total_forecast=prod_forecast + non_prod_forecast,
                )
            )
        return points

    def _safe_non_negative(self, value: Any, default: float) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            parsed = default
        return max(0.0, parsed)

    def _advisor_cache_key(self, payload: LeadershipAdvisorRequest) -> str:
        report_key = (
            payload.dashboard.report_date.isoformat()
            if hasattr(payload.dashboard.report_date, "isoformat")
            else str(payload.dashboard.report_date)
        )
        return f"pagecache:leadership:advisor:{report_key}"

    def _forecast_cache_key(self, payload: LeadershipAdvisorRequest) -> str:
        report_key = (
            payload.dashboard.report_date.isoformat()
            if hasattr(payload.dashboard.report_date, "isoformat")
            else str(payload.dashboard.report_date)
        )
        return f"pagecache:leadership:forecast:{report_key}"

    async def _cache_model(
        self,
        key: str,
        model: LeadershipAdvisorResponse | LeadershipForecastResponse,
    ) -> None:
        ttl = await get_effective_cache_ttl_seconds(self._db)
        await cache_manager.set_cached(key, model.model_dump_json(), ttl=ttl)

    def _find_kpi_value(self, payload: LeadershipAdvisorRequest, match: str) -> float:
        metric = next(
            (item for item in payload.dashboard.kpis if match.lower() in item.name.lower()),
            None,
        )
        return self._to_number(metric.value) if metric else 0.0

    def _to_number(self, value: Decimal | float | int) -> float:
        return float(value)

    def _build_headers(self, name: str, value: str) -> dict[str, str]:
        if not name or not value:
            return {}
        return {name: value}

    def _build_pricing_query(self, payload: LeadershipAdvisorRequest) -> dict[str, str] | None:
        recommendation = next(iter(payload.optimization.top_recommendations), None) if payload.optimization else None
        if recommendation is None:
            return None

        region = (recommendation.resource.location or "").replace(" ", "").lower()
        if not region:
            return None

        resource_type = (recommendation.resource.resource_type or "").lower()
        category = (recommendation.category or "").lower()

        service_name: str | None = None
        service_family: str | None = None

        if "virtual machine" in resource_type or "compute" in category:
            service_name = "Virtual Machines"
        elif "disk" in resource_type or "snapshot" in resource_type or "storage" in category:
            service_family = "Storage"
        elif "sql" in resource_type or "database" in category:
            service_family = "Databases"
        elif "network" in resource_type:
            service_family = "Networking"
        else:
            service_family = "Compute"

        filters = [f"armRegionName eq '{region}'"]
        if service_name:
            filters.insert(0, f"serviceName eq '{service_name}'")
        elif service_family:
            filters.insert(0, f"serviceFamily eq '{service_family}'")

        return {
            "currencyCode": settings.AZURE_PRICING_CURRENCY_CODE,
            "$filter": " and ".join(filters),
        }
