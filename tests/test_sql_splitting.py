"""Statement splitting must not fragment a migration.

The failure mode is silent: a mis-split file applies as several statements, some
of which are syntactically valid on their own. Discovering that during a
promotion is the worst case, so this is a prerequisite to migration 10 rather
than a cleanup after it.
"""

from pathlib import Path

import pytest

from scripts.init_db import split_sql

SCHEMA_DIR = Path(__file__).parents[1] / "db" / "schema"

# Captured from the pre-hardening splitter. These files are applied and
# checksum-immutable, so how they split must not change.
BASELINE_STATEMENT_COUNTS = {
    "01_tables.sql": 6,
    "02_constraints.sql": 1,
    "03_indexes.sql": 10,
    # Entirely comments: the hardened trailing filter drops the comment-only
    # fragment that previously executed as a PostgreSQL no-op.
    "04_triggers.sql": 0,
    "05_views.sql": 4,
    "06_procedures.sql": 2,
    "07_fix_season_metadata.sql": 1,
    "08_shot_attempts.sql": 7,
    "09_single_season_provenance.sql": 10,
    "10_schema_hardening.sql": 7,
}


def test_plain_statements_split_on_semicolons() -> None:
    statements = split_sql("SELECT 1; SELECT 2;")
    assert statements == ["SELECT 1", "SELECT 2"]


def test_comment_only_fragments_are_dropped() -> None:
    assert split_sql("-- a comment\n;\nSELECT 1;") == ["SELECT 1"]


def test_untagged_dollar_quote_protects_its_semicolons() -> None:
    body = "CREATE FUNCTION f() RETURNS void AS $$ BEGIN PERFORM 1; END; $$ LANGUAGE plpgsql;"
    assert len(split_sql(body)) == 1


def test_tagged_dollar_quote_protects_its_semicolons() -> None:
    """`$func$` is as valid as `$$` and is what a real function body often uses."""
    body = (
        "CREATE FUNCTION f() RETURNS void AS $func$ BEGIN PERFORM 1; END; $func$ LANGUAGE plpgsql;"
    )
    assert len(split_sql(body)) == 1, "a tagged dollar quote was split mid-body"


def test_semicolon_inside_a_string_literal_does_not_split() -> None:
    body = "INSERT INTO t (note) VALUES ('a; b');"
    assert split_sql(body) == ["INSERT INTO t (note) VALUES ('a; b')"]


def test_dollars_inside_a_string_literal_do_not_open_a_quote() -> None:
    """A `$$` in a literal must not flip the parser into dollar-quote mode.

    If it does, every following semicolon is swallowed and the rest of the file
    collapses into one statement.
    """
    body = "INSERT INTO t (note) VALUES ('costs $$ today'); SELECT 1;"
    assert split_sql(body) == ["INSERT INTO t (note) VALUES ('costs $$ today')", "SELECT 1"]


def test_escaped_quote_inside_a_literal_is_handled() -> None:
    body = "INSERT INTO t (note) VALUES ('it''s here; ok'); SELECT 1;"
    assert len(split_sql(body)) == 2


def test_line_comment_containing_a_semicolon_does_not_split() -> None:
    body = "SELECT 1; -- trailing; comment\nSELECT 2;"
    statements = split_sql(body)
    # Two statements, not three: the semicolon inside the comment is inert.
    # The comment stays attached to the statement that follows it, which is
    # fine -- PostgreSQL ignores it.
    assert len(statements) == 2
    assert statements[0] == "SELECT 1"
    assert statements[1].endswith("SELECT 2")


@pytest.mark.parametrize("path", sorted(SCHEMA_DIR.glob("*.sql")), ids=lambda p: p.name)
def test_existing_migrations_split_into_runnable_statements(path: Path) -> None:
    """Every applied migration must keep splitting exactly as it does today.

    Applied files are checksum-immutable, so a splitting change that altered how
    one of them parses would change what is executed on a fresh database while
    the checksum still matched.
    """
    statements = split_sql(path.read_text())
    for statement in statements:
        # A statement may open with a comment header; what it may not be is
        # comments alone, which would mean a real statement went missing.
        executable = [
            line
            for line in statement.splitlines()
            if line.strip() and not line.strip().startswith("--")
        ]
        assert executable, f"{path.name} produced a comment-only statement"

    # Applied files are checksum-immutable, so a splitting change that altered
    # how one parses would change what runs on a fresh database while the
    # checksum still matched. Pin the counts.
    assert len(statements) == BASELINE_STATEMENT_COUNTS[path.name], (
        f"{path.name} now splits into {len(statements)} statements, "
        f"not {BASELINE_STATEMENT_COUNTS[path.name]}"
    )
