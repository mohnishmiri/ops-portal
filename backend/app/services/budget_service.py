"""
Budget vs RunRate Service.

Reads per-application 2026 budget and run-rate values from
``budget_config.json`` and returns a simple comparison view for
the Leadership Dashboard.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import structlog

from app.core.db_cache import cache_manager

logger = structlog.get_logger(__name__)

_CACHE_KEY = "budget:runrate"
_CACHE_TTL = 600  # 10 minutes

_CFG_PATH = Path(__file__).resolve().parents[2] / "config" / "budget_config.json"


def _load_budget_config() -> list[dict[str, Any]]:
    """Load application budget config from JSON file."""
    if not _CFG_PATH.exists():
        logger.warning("budget_config_not_found", path=str(_CFG_PATH))
        return []
    with open(_CFG_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("applications", [])


class BudgetService:
    """Return Budget vs RunRate comparison from budget_config.json."""

    async def get_budget_runrate(self, *, refresh: bool = False) -> dict:
        """Return budget vs run-rate data for all configured apps."""
        if not refresh:
            cached = await cache_manager.get_cached(_CACHE_KEY)
            if cached:
                return json.loads(cached)

        apps_cfg = _load_budget_config()
        if not apps_cfg:
            return {
                "applications": [],
                "totals": {},
                "generated_at": datetime.utcnow().isoformat(),
            }

        rows: list[dict] = []
        for app in apps_cfg:
            budget = app.get("budget_2026", 0)
            run_rate = app.get("run_rate_2026", 0)
            variance = budget - run_rate
            utilization = (run_rate / budget * 100) if budget > 0 else 0.0
            rows.append(
                {
                    "app_name": app["name"],
                    "budget_2026": budget,
                    "run_rate_2026": run_rate,
                    "variance": round(variance, 2),
                    "utilization_pct": round(utilization, 1),
                }
            )

        total_budget = sum(r["budget_2026"] for r in rows)
        total_run_rate = sum(r["run_rate_2026"] for r in rows)
        total_variance = total_budget - total_run_rate
        total_util = (total_run_rate / total_budget * 100) if total_budget > 0 else 0.0

        result = {
            "applications": rows,
            "totals": {
                "budget_2026": round(total_budget, 2),
                "run_rate_2026": round(total_run_rate, 2),
                "variance": round(total_variance, 2),
                "utilization_pct": round(total_util, 1),
            },
            "generated_at": datetime.utcnow().isoformat(),
        }

        await cache_manager.set_cached(
            _CACHE_KEY,
            json.dumps(result, default=str),
            ttl=_CACHE_TTL,
        )
        return result
