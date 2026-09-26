"""Tests for the server-side trusted-principal adapter."""

from types import SimpleNamespace
import uuid

from migration_intake.web.principal import get_principal
from migration_intake.web.security import CONFIGURED_ACTOR_CAPABILITIES


def test_principal_uses_server_settings_not_request_headers() -> None:
    settings = SimpleNamespace(
        actor_id=str(uuid.uuid4()),
        actor_display_name="Configured Test Actor",
    )
    request = SimpleNamespace(
        headers={"X-Actor-Id": str(uuid.uuid4()), "X-Actor-Role": "ADMIN"},
        app=SimpleNamespace(state=SimpleNamespace(settings=settings)),
    )

    actor = get_principal(request)

    assert actor.actor_id == settings.actor_id
    assert actor.display_name == settings.actor_display_name
    assert actor.actor_type == "CONFIGURED"
    assert actor.external_subject is None
    assert actor.role_codes == CONFIGURED_ACTOR_CAPABILITIES