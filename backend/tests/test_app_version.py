"""The API must report the same version as the UI footer and Helm chart."""

import json
import re
import tomllib
from pathlib import Path

from app.core.config import Settings

REPO = Path(__file__).resolve().parents[2]


def _pyproject_version() -> str:
    return tomllib.loads((REPO / "backend" / "pyproject.toml").read_text())["project"]["version"]


def test_app_version_comes_from_pyproject() -> None:
    assert _pyproject_version() == Settings().APP_VERSION


def test_version_files_bumped_together() -> None:
    """bump_version.sh updates these together; a hand edit to one shows up here."""
    version = _pyproject_version()
    package = json.loads((REPO / "frontend" / "package.json").read_text())["version"]
    footer = re.search(r'const APP_VERSION = "([^"]+)"', (REPO / "frontend" / "src" / "App.tsx").read_text())
    chart = re.search(r"^version:\s*(\S+)", (REPO / "helm" / "ops-portal" / "Chart.yaml").read_text(), re.M)

    assert package == version
    assert footer and footer.group(1) == version
    assert chart and chart.group(1) == version
