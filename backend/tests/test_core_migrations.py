"""Tests for the startup SQL migration runner.

``create_all`` adds missing tables but never a missing column, so a column added
to a model without a matching migration being applied fails at query time, far
from the cause — how cert_certificates.deleted_at broke certificate sync. These
cover the parsing, which is where a migration silently turns into invalid SQL.
"""

from types import SimpleNamespace

from app.core.migrations import _split_statements, run_sql_migrations

# ── Statement splitting ────────────────────────────────────────────────────────


def test_splits_a_multi_statement_file():
    sql = "ALTER TABLE t ADD COLUMN a INT;\nCREATE INDEX ix ON t (a);"
    assert _split_statements(sql) == ["ALTER TABLE t ADD COLUMN a INT", "CREATE INDEX ix ON t (a)"]


def test_a_semicolon_inside_a_comment_does_not_split_the_file():
    # Every migration header documents its own psql invocation in prose, and
    # that prose contains semicolons. Splitting before stripping comments cut
    # one in half and sent "this script is" to the server as SQL.
    sql = """-- Created by Base.metadata.create_all on startup; this script is
-- for deployments that manage schema out of band.
CREATE TABLE IF NOT EXISTS t (id SERIAL PRIMARY KEY);
"""
    assert _split_statements(sql) == ["CREATE TABLE IF NOT EXISTS t (id SERIAL PRIMARY KEY)"]


def test_trailing_comment_is_not_treated_as_a_statement():
    assert _split_statements("ALTER TABLE t ADD COLUMN a INT;\n-- done\n") == ["ALTER TABLE t ADD COLUMN a INT"]


def test_a_comment_only_file_yields_nothing():
    assert _split_statements("-- nothing to do here\n--\n") == []


def test_a_dollar_quoted_body_is_kept_whole():
    # Semicolons inside $$ ... $$ are part of the body, not separators.
    sql = "CREATE FUNCTION f() RETURNS void AS $$ BEGIN PERFORM 1; PERFORM 2; END $$ LANGUAGE plpgsql;"
    assert len(_split_statements(sql)) == 1


def test_real_migration_files_parse_into_statements():
    # Guards the actual shipped files, not just synthetic input.
    from app.core.migrations import MIGRATIONS_DIR

    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    assert files, "expected migration files to exist"
    for path in files:
        statements = _split_statements(path.read_text())
        assert statements, f"{path.name} parsed to no statements"
        for statement in statements:
            first = statement.split()[0].upper()
            assert first in {"ALTER", "CREATE", "DROP", "UPDATE", "INSERT", "COMMENT"}, (
                f"{path.name} produced a statement starting with {first!r}: {statement[:60]!r}"
            )


# ── Dialect guard ──────────────────────────────────────────────────────────────


async def test_non_postgres_dialects_are_skipped():
    # The files are Postgres DDL; the SQLite test database is built from model
    # metadata instead, so running them there would only produce errors.
    calls: list[object] = []

    class _Conn:
        dialect = SimpleNamespace(name="sqlite")

        async def execute(self, *args, **kwargs):
            calls.append(args)

    assert await run_sql_migrations(_Conn()) == []
    assert calls == []
