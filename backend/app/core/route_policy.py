"""
State-changing routes that are nevertheless *reads* for authorization.

Portal policy: READ users view, WRITE users change.  These POST/PUT/DELETE
routes change nothing in Azure or Kubernetes — they refresh a cache, render a
chart locally, run a read-only query, or touch only the caller's own records —
so a READ user may call them, and the subscription check asks only for read
access on the subscriptions they name.

``tests/test_role_matrix.py`` keeps this list honest in both directions: a
mutating route open to READ users must be listed, and a listed route that is
no longer open to READ users fails the test until it is removed.
"""

from __future__ import annotations

READ_PERMITTED_MUTATIONS: dict[tuple[str, str], str] = {
    **{
        ("POST", f"/api/v1/{path}"): "refreshes the portal's cached copy from Azure/Kubernetes; changes nothing there"
        for path in (
            "aks/clusters/sync",
            "aks/deployments/sync",
            "aks/cronjobs/sync",
            "aks/nodepools/sync",
            "certificates/sync",
            "infra-alerts/resources/sync",
        )
    },
    (
        "POST",
        "/api/v1/sync-jobs",
    ): "AKS cache refresh is open to every role; other job types check WRITE in the handler",
    (
        "POST",
        "/api/v1/aks/dashboard/{env_key}/launch",
    ): "issues a Dashboard session that carries the user's write access",
    **{
        (method, "/api/v1/aks/dashboard/{env_key}/proxy/{path:path}"): "proxy refuses changes from read-only sessions"
        for method in ("POST", "PUT", "PATCH", "DELETE")
    },
    ("POST", "/api/v1/aks/helm/lint"): "lints a chart locally; nothing is applied to a cluster",
    ("POST", "/api/v1/aks/helm/template"): "renders a chart locally; nothing is applied to a cluster",
    ("POST", "/api/v1/aks/logs/archive"): "downloads pod logs (aks_pod_view)",
    ("PUT", "/api/v1/auth/subscription-scope"): "the caller's own view preference",
    ("POST", "/api/v1/certificates/{certificate_id}/download"): "public formats are reads; private keys check WRITE",
    ("POST", "/api/v1/costs/query"): "read-only cost query",
    ("POST", "/api/v1/dashboards/leadership/advisor"): "read-only AI summary of existing data",
    ("POST", "/api/v1/dashboards/leadership/forecast"): "read-only forecast of existing data",
    ("POST", "/api/v1/reports/generate"): "read-only report over existing data",
    ("POST", "/api/v1/access/requests"): "submits an access request; nothing changes until an approver acts",
    ("POST", "/api/v1/access/requests/{request_id}/cancel"): "withdraws the caller's own pending request",
}


def required_level(method: str, route_path: str | None) -> str:
    """``read`` or ``write`` — the subscription access a request needs."""
    if method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return "read"
    if route_path and (method.upper(), route_path) in READ_PERMITTED_MUTATIONS:
        return "read"
    return "write"
