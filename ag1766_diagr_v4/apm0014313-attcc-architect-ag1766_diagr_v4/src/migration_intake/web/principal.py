"""Trusted principal boundary for web adapters.

The configured principal is a development/test mode only. Production identity
must be supplied by an approved authentication provider through this adapter;
request headers and form fields are never actor identity inputs.
"""

from __future__ import annotations

from fastapi import Request

from migration_intake.application.dto import ActorContext
from migration_intake.web.security import CONFIGURED_ACTOR_CAPABILITIES


def get_principal(
    request: Request,
    capabilities: frozenset | None = None,
) -> ActorContext:
    """Resolve the server-authenticated principal for the current request."""
    settings = request.app.state.settings
    return ActorContext(
        actor_id=settings.actor_id,
        actor_type="CONFIGURED",
        display_name=settings.actor_display_name,
        role_codes=capabilities or CONFIGURED_ACTOR_CAPABILITIES,
    )
