"""
Deprecated — access control now lives in :mod:`app.core.authz`.

This module previously defined ``AccessControlMiddleware`` and
``SubscriptionFilterMiddleware``.  Both have been removed because they were
non-functional dead code:

* Neither was ever registered in ``app.main.create_application``, so no
  request ever passed through them.
* Both read ``request.state.user`` *before* calling ``call_next``.  Starlette's
  ``BaseHTTPMiddleware`` runs ahead of route dependencies, so the user context
  set by the auth dependency did not exist yet — every request took the
  "no user context → allow" branch.  Registering them as written would have
  been a silent no-op.
* ``AccessControlMiddleware`` matched request paths (``/api/v1/aks/pods``)
  against ``Resource.route_path`` values, which hold *frontend* routes
  (``/aks``).  Those never match, so the resource lookup always fell through
  to "open by default".

The working replacements are FastAPI dependencies, which run *after*
authentication and are wired into ``api_router``:

* :func:`app.core.authz.enforce_portal_access` — portal access gate
* :func:`app.core.authz.enforce_module_access` — module-scoped API access
* :func:`app.core.authz.require_capability` — per-operation authorization

Subscription-scope authorization is handled by
:func:`app.core.subscription_scope.bind_subscription_scope`, which already
intersects the requested scope with the user's allowed subscriptions and
raises 403 on violation.

Re-exported here so any stale import keeps working.
"""

from app.core.authz import enforce_module_access, enforce_portal_access, require_capability

__all__ = ["enforce_module_access", "enforce_portal_access", "require_capability"]
