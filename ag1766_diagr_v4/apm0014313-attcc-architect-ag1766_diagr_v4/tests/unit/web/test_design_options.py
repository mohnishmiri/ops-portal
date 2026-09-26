"""Route contract tests for the isolated application-wide design lab."""

from fastapi.testclient import TestClient

from migration_intake.web.design_preview import create_design_preview_app
from migration_intake.web.routes.design_options import SCREENS


def test_comparison_page_lists_every_screen() -> None:
    with TestClient(create_design_preview_app()) as client:
        response = client.get("/design-options")

    assert response.status_code == 200
    assert "Application-wide comparison" in response.text
    for label in SCREENS.values():
        assert label in response.text


def test_every_option_renders_every_screen() -> None:
    with TestClient(create_design_preview_app()) as client:
        for option in ("a", "b", "c"):
            for screen, label in SCREENS.items():
                response = client.get(f"/design-options/{option}/{screen}")
                assert response.status_code == 200, (option, screen)
                assert label in response.text
                assert f'/design-options/a/{screen}' in response.text
                assert f'/design-options/b/{screen}' in response.text
                assert f'/design-options/c/{screen}' in response.text


def test_unknown_option_and_screen_return_not_found() -> None:
    with TestClient(create_design_preview_app()) as client:
        assert client.get("/design-options/d/applications").status_code == 404
        assert client.get("/design-options/a/unknown").status_code == 404
