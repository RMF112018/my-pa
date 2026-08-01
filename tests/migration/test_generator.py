"""End-to-end DDL generation from a small synthetic source profile.

The fixtures here are written by hand rather than read from the real profile:
the profile is 4.3 MB, is not in the repository, and describes personal data.
These tables reproduce the shapes that matter -- a promoted boolean, an
AUTOINCREMENT key, a table with no key at all, an over-long column name, a
reserved word, a partial index, and a foreign key to a table that is not
created -- and nothing else.
"""

from __future__ import annotations

import pytest

from my_pa.infrastructure.migration.generator import (
    PROVENANCE_COLUMNS,
    SOURCE_ROW_HASH_COLUMN,
    SURROGATE_KEY_COLUMN,
    GenerationError,
    generate,
)
from my_pa.infrastructure.migration.source import (
    Disposition,
    SourceColumn,
    SourceForeignKey,
    SourceIndex,
    SourceTable,
)

LONG_COLUMN = "cost_impact_request_for_quote_currency_configuration_base_currency_iso_code"

ORDERS_SQL = """
CREATE TABLE orders (
  record_key TEXT PRIMARY KEY,
  is_current INTEGER NOT NULL DEFAULT 1 CHECK(is_current IN (0, 1)),
  external_writeback_performed INTEGER NOT NULL DEFAULT 0
      CHECK(external_writeback_performed = 0),
  status TEXT CHECK(status IN ('open', 'closed')),
  amount REAL,
  created_utc TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)
"""


def _column(
    name: str,
    declared_type: str = "TEXT",
    *,
    not_null: bool = False,
    default: str | None = None,
    pk: int = 0,
) -> SourceColumn:
    return SourceColumn(name, declared_type, not_null, default, pk)


def _table(
    name: str,
    sql: str,
    columns: tuple[SourceColumn, ...],
    *,
    primary_key: tuple[str, ...] = (),
    foreign_keys: tuple[SourceForeignKey, ...] = (),
    indexes: tuple[SourceIndex, ...] = (),
    without_rowid: bool = False,
) -> SourceTable:
    return SourceTable(
        name=name,
        object_type="table",
        sql=sql,
        columns=columns,
        primary_key=primary_key,
        foreign_keys=foreign_keys,
        indexes=indexes,
        row_count=0,
        is_fts=False,
        is_virtual=False,
        is_internal=False,
        without_rowid=without_rowid,
    )


ORDERS = _table(
    "orders",
    ORDERS_SQL,
    (
        _column("record_key", not_null=True, pk=1),
        _column("is_current", "INTEGER", not_null=True, default="1"),
        _column("external_writeback_performed", "INTEGER", not_null=True, default="0"),
        _column("status"),
        _column("amount", "REAL"),
        _column("created_utc", not_null=True, default="CURRENT_TIMESTAMP"),
    ),
    primary_key=("record_key",),
    indexes=(
        SourceIndex("sqlite_autoindex_orders_1", True, "pk", False, ("record_key",), None),
        SourceIndex(
            "idx_orders_open",
            False,
            "c",
            True,
            ("status",),
            "CREATE INDEX idx_orders_open ON orders(status) WHERE is_current = 1",
        ),
    ),
)

ORDER_LINES = _table(
    "order_lines",
    f'CREATE TABLE order_lines (id INTEGER PRIMARY KEY AUTOINCREMENT, order_key TEXT, "column" '
    f"TEXT, {LONG_COLUMN} TEXT, FOREIGN KEY(order_key) REFERENCES orders(record_key))",
    (
        _column("id", "INTEGER", not_null=True, pk=1),
        _column("order_key"),
        _column("column"),
        _column(LONG_COLUMN),
    ),
    primary_key=("id",),
    foreign_keys=(
        SourceForeignKey(0, "orders", ("order_key",), ("record_key",), "CASCADE", "NO ACTION"),
    ),
    indexes=(
        SourceIndex(
            "idx_order_lines_order_key",
            False,
            "c",
            False,
            ("order_key",),
            "CREATE INDEX idx_order_lines_order_key ON order_lines(order_key)",
        ),
    ),
)

KEYLESS = _table(
    "relationship_results",
    "CREATE TABLE relationship_results (a TEXT NOT NULL, b TEXT)",
    (_column("a", not_null=True), _column("b")),
    foreign_keys=(SourceForeignKey(0, "archived", ("a",), ("a",), "NO ACTION", "NO ACTION"),),
)

ARCHIVED = _table("archived", "CREATE TABLE archived (a TEXT PRIMARY KEY)", (_column("a", pk=1),))

#: SQLite auto-assigns this key even though it never says AUTOINCREMENT.
ACTIVE_POLICY = _table(
    "active_policy",
    "CREATE TABLE active_policy (id INTEGER PRIMARY KEY, policy_key TEXT)",
    (_column("id", "INTEGER", pk=1), _column("policy_key")),
    primary_key=("id",),
)

TABLES = (ORDERS, ORDER_LINES, KEYLESS, ARCHIVED, ACTIVE_POLICY)

REGISTRY = {
    "orders": Disposition("orders", "table", "core", "SCHEMA_AND_DATA", "MIGRATE_DATA", "g"),
    "order_lines": Disposition(
        "order_lines", "table", "procore", "SCHEMA_AND_DATA", "MIGRATE_DATA", "g"
    ),
    "relationship_results": Disposition(
        "relationship_results", "table", "schedule", "SCHEMA_AND_DATA", "MIGRATE_DATA", "g"
    ),
    "archived": Disposition(
        "archived", "table", "core", "NOT_CREATED", "ARCHIVE_LEGACY_SOURCE_ONLY", "g"
    ),
    "active_policy": Disposition(
        "active_policy", "table", "core", "SCHEMA_AND_DATA", "MIGRATE_DATA", "g"
    ),
}


def _statement(statements: tuple[str, ...], needle: str) -> str:
    matches = [statement for statement in statements if needle in statement]
    assert len(matches) == 1, f"expected one statement containing {needle!r}, got {len(matches)}"
    return matches[0]


def test_only_created_tables_are_emitted() -> None:
    result = generate(TABLES, REGISTRY)

    assert len(result.create_tables) == 4
    assert result.report.tables_by_schema == {"core": 2, "procore": 1, "schedule": 1}
    assert not any('"archived"' in statement for statement in result.create_tables)


def test_a_table_lands_in_the_schema_the_registry_gives_it() -> None:
    result = generate(TABLES, REGISTRY)

    assert 'CREATE TABLE "procore"."order_lines"' in _statement(result.create_tables, "order_lines")


def test_types_come_from_the_declared_type_and_the_checks() -> None:
    orders = _statement(generate(TABLES, REGISTRY).create_tables, '"orders"')

    assert '"record_key" text NOT NULL' in orders
    assert '"amount" double precision' in orders
    assert '"is_current" boolean NOT NULL DEFAULT true' in orders
    assert '"external_writeback_performed" bigint NOT NULL DEFAULT 0' in orders


def test_only_the_zero_or_one_check_promotes_a_boolean() -> None:
    report = generate(TABLES, REGISTRY).report

    assert report.boolean_promotions == [("orders", "is_current")]


def test_checks_are_ported_with_explicit_names() -> None:
    orders = _statement(generate(TABLES, REGISTRY).create_tables, '"orders"')

    assert 'CONSTRAINT "orders_is_current_ck1" CHECK ("is_current" IN (false, true))' in orders
    assert "CHECK (\"status\" IN ('open', 'closed'))" in orders
    assert generate(TABLES, REGISTRY).report.checks_emitted == 3


def test_a_timestamp_default_becomes_utc_text() -> None:
    orders = _statement(generate(TABLES, REGISTRY).create_tables, '"orders"')

    assert "DEFAULT to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD HH24:MI:SS')" in orders


def test_autoincrement_becomes_identity_by_default() -> None:
    result = generate(TABLES, REGISTRY)
    lines = _statement(result.create_tables, '"order_lines"')

    assert '"id" bigint GENERATED BY DEFAULT AS IDENTITY' in lines
    assert ("order_lines", "id") in result.report.identity_columns


def test_a_rowid_alias_key_gets_an_identity_without_declaring_autoincrement() -> None:
    """SQLite fills in a single-column INTEGER PRIMARY KEY either way; PostgreSQL will not."""
    result = generate(TABLES, REGISTRY)
    policy = _statement(result.create_tables, '"active_policy"')

    assert '"id" bigint GENERATED BY DEFAULT AS IDENTITY' in policy
    assert ("active_policy", "id") in result.report.identity_columns
    assert len(result.report.identity_columns) == 2


def test_a_text_key_gets_no_identity() -> None:
    orders = _statement(generate(TABLES, REGISTRY).create_tables, '"orders"')

    assert "IDENTITY" not in orders


def test_a_without_rowid_table_has_no_rowid_alias() -> None:
    table = _table(
        "wr",
        "CREATE TABLE wr (id INTEGER PRIMARY KEY) WITHOUT ROWID",
        (_column("id", "INTEGER", pk=1),),
        primary_key=("id",),
        without_rowid=True,
    )

    assert table.rowid_alias_key is None


def test_a_reserved_word_column_keeps_its_name() -> None:
    lines = _statement(generate(TABLES, REGISTRY).create_tables, '"order_lines"')

    assert '"column" text' in lines


def test_an_over_long_column_is_shortened_and_recorded() -> None:
    result = generate(TABLES, REGISTRY)
    renames = [rename for rename in result.report.renames if rename.object_kind == "column"]

    assert [rename.original for rename in renames] == [LONG_COLUMN]
    assert renames[0].owner == "order_lines"
    assert f'"{renames[0].shortened}" text' in _statement(result.create_tables, '"order_lines"')


def test_every_emitted_identifier_fits_the_budget() -> None:
    result = generate(TABLES, REGISTRY)
    emitted = result.create_tables + result.add_foreign_keys + result.create_indexes

    for statement in emitted:
        for identifier in statement.split('"')[1::2]:
            assert len(identifier.encode("utf-8")) <= 63, identifier


def test_every_created_table_gets_the_provenance_columns() -> None:
    result = generate(TABLES, REGISTRY)

    for statement in result.create_tables:
        for name, sql_type in PROVENANCE_COLUMNS:
            assert f'"{name}" {sql_type}' in statement


def test_a_table_with_no_key_gets_a_surrogate_and_a_row_hash() -> None:
    result = generate(TABLES, REGISTRY)
    keyless = _statement(result.create_tables, '"relationship_results"')

    assert result.report.surrogate_key_tables == ["relationship_results"]
    assert f'"{SURROGATE_KEY_COLUMN}" bigint GENERATED ALWAYS AS IDENTITY' in keyless
    assert f'"{SOURCE_ROW_HASH_COLUMN}" text' in keyless
    assert f'PRIMARY KEY ("{SURROGATE_KEY_COLUMN}")' in keyless


def test_a_keyed_table_keeps_its_own_primary_key() -> None:
    orders = _statement(generate(TABLES, REGISTRY).create_tables, '"orders"')

    assert 'CONSTRAINT "orders_pkey" PRIMARY KEY ("record_key")' in orders
    assert SURROGATE_KEY_COLUMN not in orders


def test_foreign_keys_are_emitted_separately_from_the_tables() -> None:
    result = generate(TABLES, REGISTRY)

    assert not any("FOREIGN KEY" in statement for statement in result.create_tables)
    assert result.report.foreign_key_count == 1
    assert 'REFERENCES "core"."orders" ("record_key")' in result.add_foreign_keys[0]
    assert "ON DELETE CASCADE" in result.add_foreign_keys[0]


def test_a_foreign_key_to_an_uncreated_table_is_skipped_and_reported() -> None:
    skipped = generate(TABLES, REGISTRY).report.skipped_foreign_keys

    assert [(item.table, item.referenced_table) for item in skipped] == [
        ("relationship_results", "archived")
    ]


def test_indexes_are_emitted_separately_and_the_primary_key_index_is_not_repeated() -> None:
    result = generate(TABLES, REGISTRY)

    assert not any("CREATE INDEX" in statement for statement in result.create_tables)
    assert len(result.create_indexes) == 2
    assert not any("sqlite_autoindex" in statement for statement in result.create_indexes)


def test_a_partial_index_predicate_is_rewritten_for_the_promoted_boolean() -> None:
    result = generate(TABLES, REGISTRY)
    index = _statement(result.create_indexes, "idx_orders_open")

    assert 'CREATE INDEX "idx_orders_open" ON "core"."orders" ("status")' in index
    assert 'WHERE "is_current" = true' in index
    assert result.report.partial_index_count == 1


def test_the_downgrade_undoes_each_step() -> None:
    result = generate(TABLES, REGISTRY)

    assert len(result.drop_tables) == len(result.create_tables)
    assert all(statement.startswith("DROP TABLE IF EXISTS") for statement in result.drop_tables)
    assert all(statement.startswith("DROP INDEX IF EXISTS") for statement in result.drop_indexes)
    assert all("DROP CONSTRAINT IF EXISTS" in item for item in result.drop_foreign_keys)


def test_generation_is_deterministic() -> None:
    assert generate(TABLES, REGISTRY).create_tables == generate(TABLES, REGISTRY).create_tables


def test_a_table_missing_from_the_registry_fails_closed() -> None:
    with pytest.raises(GenerationError, match="no disposition"):
        generate(TABLES, {name: REGISTRY[name] for name in REGISTRY if name != "orders"})
