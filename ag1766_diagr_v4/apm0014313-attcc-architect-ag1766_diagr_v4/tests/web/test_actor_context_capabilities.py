"""
Regression guard for CAT-SEC1b — wire capability enforcement into actor context.

Before this packet, every route module's ``get_actor_context()`` built an
``ActorContext`` with the default empty ``role_codes``, so
``require_capability()`` always rejected the real (non-overridden) actor —
including the CAT-B3 catalog publish routes, which are the first consumer of
``Capability.CATALOG_MANAGE``.

This test proves that each of the five route modules named in the CAT-SEC1b
packet now populates ``role_codes`` with ``CONFIGURED_ACTOR_CAPABILITIES``
(every ``Capability`` value), so ``require_capability()`` checks against the
real actor context succeed exactly as they do against the dependency-override
actors used in other route tests.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from migration_intake.web.security import CONFIGURED_ACTOR_CAPABILITIES, Capability
from migration_intake.web.routes import (
    applications as applications_module,
    evidence as evidence_module,
    questionnaire as questionnaire_module,
    readiness as readiness_module,
    wave_util as wave_util_module,
)

MODULES_UNDER_TEST = (
    applications_module,
    evidence_module,
    questionnaire_module,
    readiness_module,
    wave_util_module,
)


def _fake_request(actor_id: str, actor_display_name: str) -> SimpleNamespace:
    """Build a minimal fake Request exposing app.state.settings.

    Each module's get_actor_context() only reads
    request.app.state.settings.actor_id (and, in some modules,
    .actor_display_name), so a SimpleNamespace stand-in is sufficient without
    booting a full FastAPI app.
    """
    settings = SimpleNamespace(actor_id=actor_id, actor_display_name=actor_display_name)
    state = SimpleNamespace(settings=settings)
    app = SimpleNamespace(state=state)
    return SimpleNamespace(app=app)


class TestActorContextCapabilities:
    @pytest.mark.parametrize("module", MODULES_UNDER_TEST, ids=lambda m: m.__name__)
    def test_get_actor_context_returns_configured_capabilities(self, module) -> None:
        actor_id = str(uuid.uuid4())
        request = _fake_request(actor_id, "Test Actor")

        actor_ctx = module.get_actor_context(request)

        assert actor_ctx.role_codes == CONFIGURED_ACTOR_CAPABILITIES
        assert len(actor_ctx.role_codes) > 0
        for capability in Capability:
            assert capability in actor_ctx.role_codes
        assert Capability.CATALOG_MANAGE in actor_ctx.role_codes
