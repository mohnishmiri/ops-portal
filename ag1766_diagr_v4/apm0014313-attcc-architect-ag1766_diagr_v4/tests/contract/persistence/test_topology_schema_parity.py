"""TP02 contracts for governed topology migration and ORM metadata parity."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

import migration_intake.persistence.models
import migration_intake.persistence.models_snapshots
import migration_intake.persistence.models_topology  # noqa: F401
from migration_intake.persistence.naming import Base

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine


GOVERNED_TABLES = (
    "topo_base",
    "gen_runs",
    "gen_artifacts",
    "topo_compat",
    "topo_captures",
    "topo_inputs",
    "gen_keys",
    "topo_reviews",
)


def _migrated_engine(tmp_path: Path) -> Engine:
    database_path = tmp_path / "topology-parity.db"
    database_url = f"sqlite:///{database_path.as_posix()}"
    config = Config()
    config.set_main_option(
        "script_location",
        (Path(__file__).parents[3] / "src/migration_intake/persistence/migrations").as_posix(),
    )
    config.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(config, "head")
    return create_engine(database_url)


def test_governed_topology_tables_and_columns_match_migrated_schema(tmp_path: Path) -> None:
    engine = _migrated_engine(tmp_path)
    try:
        inspector = inspect(engine)
        for table_name in GOVERNED_TABLES:
            assert table_name in Base.metadata.tables
            migrated_columns = {
                column["name"] for column in inspector.get_columns(table_name)
            }
            orm_columns = set(Base.metadata.tables[table_name].columns.keys())
            assert orm_columns == migrated_columns, table_name
    finally:
        engine.dispose()


def test_governed_topology_unique_constraints_match_migrated_schema(tmp_path: Path) -> None:
    engine = _migrated_engine(tmp_path)
    try:
        inspector = inspect(engine)
        for table_name in GOVERNED_TABLES:
            migrated = {
                (constraint["name"], tuple(constraint["column_names"]))
                for constraint in inspector.get_unique_constraints(table_name)
            }
            orm = {
                (constraint.name, tuple(column.name for column in constraint.columns))
                for constraint in Base.metadata.tables[table_name].constraints
                if constraint.__class__.__name__ == "UniqueConstraint"
            }
            assert orm == migrated, table_name
    finally:
        engine.dispose()


def test_governed_topology_foreign_keys_match_migrated_schema(tmp_path: Path) -> None:
    engine = _migrated_engine(tmp_path)
    try:
        inspector = inspect(engine)
        for table_name in GOVERNED_TABLES:
            migrated = {
                (
                    foreign_key["name"],
                    tuple(foreign_key["constrained_columns"]),
                    foreign_key["referred_table"],
                    tuple(foreign_key["referred_columns"]),
                )
                for foreign_key in inspector.get_foreign_keys(table_name)
            }
            orm = {
                (
                    constraint.name,
                    tuple(element.parent.name for element in constraint.elements),
                    next(iter(constraint.elements)).column.table.name,
                    tuple(element.column.name for element in constraint.elements),
                )
                for constraint in Base.metadata.tables[table_name].foreign_key_constraints
            }
            assert orm == migrated, table_name
    finally:
        engine.dispose()
