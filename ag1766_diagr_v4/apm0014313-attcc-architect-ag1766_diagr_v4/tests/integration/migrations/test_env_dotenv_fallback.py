"""Regression coverage for CLI migrations loading the repository .env."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_migration_config_uses_dotenv_database_url(tmp_path, monkeypatch) -> None:
    repository_root = Path(__file__).parents[3]
    database_path = tmp_path / "migration.db"
    env_path = tmp_path / ".env"
    env_path.write_text(
        f"AWS_OUTPOST_DATABASE_URL=sqlite:///{database_path}\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AWS_OUTPOST_DATABASE_URL", raising=False)

    config_path = tmp_path / "alembic.ini"
    config_path.write_text(
        (repository_root / "alembic.ini")
        .read_text(encoding="utf-8")
        .replace(
            "script_location = src/migration_intake/persistence/migrations",
            f"script_location = {repository_root.as_posix()}/src/migration_intake/persistence/migrations",
        ),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, "-m", "alembic", "-c", str(config_path), "upgrade", "head"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
