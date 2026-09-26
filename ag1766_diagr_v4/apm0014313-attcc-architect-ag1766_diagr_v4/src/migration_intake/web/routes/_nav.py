"""
Shared navigation helpers for template context.

Centralises nav_items construction so every route passes the same
structure to base.html → components/nav.html without duplicating logic.
"""
from __future__ import annotations


def app_nav_items(
    app_id: str,
    intake_id: str,
    active: str,
) -> list[dict]:
    """Build navigation items for app-scoped pages."""
    base = f"/applications/{app_id}/intakes/{intake_id}"
    items = [
        {"key": "hub", "label": "Intake overview", "href": base},
        {"key": "questionnaire", "label": "Questionnaire", "href": f"{base}/questionnaire"},
        {"key": "sources", "label": "Evidence", "href": f"{base}/sources"},
        {"key": "interfaces", "label": "Interfaces", "href": f"{base}/interfaces"},
        {"key": "wave_util", "label": "WaveUtil", "href": f"{base}/wave-util"},
        {"key": "readiness", "label": "Readiness", "href": f"/intakes/{intake_id}/readiness"},
        {"key": "topology", "label": "Topology", "href": f"{base}/topology"},
    ]
    return [{"active": item["key"] == active, **item} for item in items]


def global_nav_items(active: str) -> list[dict]:
    """Nav items for global pages (applications list, catalog admin)."""
    items = [
        {"key": "applications", "label": "Applications", "href": "/applications"},
        {"key": "catalog_admin", "label": "Catalog Admin", "href": "/admin/catalog"},
        {"key": "template_admin", "label": "Template Admin", "href": "/admin/templates"},
    ]
    return [{"active": item["key"] == active, **item} for item in items]
