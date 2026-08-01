"""Turn the legacy SQLite profile into PostgreSQL DDL.

The output is deliberately split into three steps, because the order matters for
the load. Tables come first, carrying their columns, primary key, CHECK
constraints, and provenance columns. Foreign keys come second: SQLite never
enforced its declared constraints, so the data may contain orphans and the
constraints have to be added after the rows land (OD-017). Indexes come last,
for the same reason and because building them after a bulk load is cheaper
(OD-019).

Nothing is inferred from a column name. Types come from the declared type,
booleans from CHECK constraints, and every identifier is quoted and preserved
byte-for-byte unless PostgreSQL's 63-byte budget forces a rename.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from my_pa.infrastructure.migration import expressions, sqlite_ddl, type_mapping
from my_pa.infrastructure.migration.identifiers import Namespace, Rename, qualify, quote
from my_pa.infrastructure.migration.source import (
    Disposition,
    SourceColumn,
    SourceIndex,
    SourceTable,
)

#: OD-011. Added to every created table so a row can always name the run and the
#: source object it came from. Nullable, because the rebuild-class tables are
#: filled by the application rather than by the load.
PROVENANCE_COLUMNS: tuple[tuple[str, str], ...] = (
    ("migration_run_id", "uuid"),
    ("migration_source_table", "text"),
    ("migration_source_schema_version", "integer"),
    ("migration_natural_key_hash", "text"),
)

#: OD-014. Given to any table with neither a primary key nor a unique index, so
#: the load has an idempotency key without inventing a business key the source
#: never had.
SURROGATE_KEY_COLUMN = "migration_surrogate_id"
SOURCE_ROW_HASH_COLUMN = "migration_source_row_hash"


class GenerationError(RuntimeError):
    """The source shape cannot be expressed as PostgreSQL DDL."""


@dataclass(frozen=True)
class DroppedCheck:
    """A CHECK constraint that could not be ported, kept verbatim for the record."""

    table: str
    column: str | None
    predicate: str
    reason: str


@dataclass(frozen=True)
class SkippedForeignKey:
    """A declared foreign key whose target is not created in the target database."""

    table: str
    referenced_table: str
    reason: str


@dataclass
class GenerationReport:
    """What the generator did, in reviewable form."""

    tables_by_schema: Counter[str] = field(default_factory=Counter)
    renames: list[Rename] = field(default_factory=list)
    boolean_promotions: list[tuple[str, str]] = field(default_factory=list)
    identity_columns: list[tuple[str, str]] = field(default_factory=list)
    surrogate_key_tables: list[str] = field(default_factory=list)
    checks_emitted: int = 0
    dropped_checks: list[DroppedCheck] = field(default_factory=list)
    skipped_foreign_keys: list[SkippedForeignKey] = field(default_factory=list)
    foreign_key_count: int = 0
    index_count: int = 0
    unique_index_count: int = 0
    partial_index_count: int = 0
    expression_index_count: int = 0
    column_count: int = 0


@dataclass(frozen=True)
class GeneratedSchema:
    """The three DDL steps, each with the statements that undo it."""

    create_tables: tuple[str, ...]
    drop_tables: tuple[str, ...]
    add_foreign_keys: tuple[str, ...]
    drop_foreign_keys: tuple[str, ...]
    create_indexes: tuple[str, ...]
    drop_indexes: tuple[str, ...]
    report: GenerationReport


@dataclass(frozen=True)
class _TargetColumn:
    name: str
    sql_type: str
    not_null: bool
    default: str | None
    identity: str | None

    def render(self) -> str:
        parts = [quote(self.name), self.sql_type]
        if self.identity is not None:
            parts.append(f"GENERATED {self.identity} AS IDENTITY")
        if self.not_null:
            parts.append("NOT NULL")
        if self.default is not None:
            parts.append(f"DEFAULT {self.default}")
        return " ".join(parts)


@dataclass(frozen=True)
class _TablePlan:
    source: SourceTable
    schema: str
    name: str
    column_names: Mapping[str, str]
    boolean_columns: frozenset[str]
    create_statement: str


def generate(
    tables: Sequence[SourceTable],
    registry: Mapping[str, Disposition],
) -> GeneratedSchema:
    """Build the target DDL for every source table the registry says to create."""
    selected = [
        table
        for table in sorted(tables, key=lambda item: item.name)
        if table.migratable and _is_created(registry, table.name)
    ]
    relations: dict[str, Namespace] = {}
    report = GenerationReport()
    create_tables: list[str] = []
    drop_tables: list[str] = []
    plans: list[_TablePlan] = []

    for table in selected:
        schema = registry[table.name].target_schema
        namespace = relations.setdefault(schema, Namespace(f"schema {schema}"))
        plan = _plan_table(table, schema, namespace, report)
        plans.append(plan)
        create_tables.append(plan.create_statement)
        drop_tables.append(f"DROP TABLE IF EXISTS {qualify(schema, plan.name)} CASCADE;")
        report.tables_by_schema[schema] += 1

    add_foreign_keys: list[str] = []
    drop_foreign_keys: list[str] = []
    create_indexes: list[str] = []
    drop_indexes: list[str] = []
    by_name = {plan.source.name: plan for plan in plans}
    for plan in plans:
        for statement, undo in _foreign_keys(plan, by_name, report):
            add_foreign_keys.append(statement)
            drop_foreign_keys.append(undo)
        for statement, undo in _indexes(plan, relations[plan.schema], report):
            create_indexes.append(statement)
            drop_indexes.append(undo)

    for namespace in relations.values():
        report.renames.extend(namespace.renames)
    report.renames.sort(key=lambda rename: (rename.object_kind, rename.owner, rename.original))
    report.foreign_key_count = len(add_foreign_keys)
    report.index_count = len(create_indexes)

    return GeneratedSchema(
        create_tables=tuple(create_tables),
        drop_tables=tuple(reversed(drop_tables)),
        add_foreign_keys=tuple(add_foreign_keys),
        drop_foreign_keys=tuple(reversed(drop_foreign_keys)),
        create_indexes=tuple(create_indexes),
        drop_indexes=tuple(reversed(drop_indexes)),
        report=report,
    )


def _is_created(registry: Mapping[str, Disposition], name: str) -> bool:
    disposition = registry.get(name)
    if disposition is None:
        raise GenerationError(f"source table {name!r} has no disposition in the registry")
    return disposition.created


def _plan_table(
    table: SourceTable,
    schema: str,
    relations: Namespace,
    report: GenerationReport,
) -> _TablePlan:
    target_name = relations.allocate(table.name, "table", schema)
    parsed = sqlite_ddl.parse_table(table.sql)
    integers = (
        column.name for column in table.columns if column.declared_type.upper() == "INTEGER"
    )
    booleans = type_mapping.boolean_promotions(parsed.checks, integers)
    report.boolean_promotions.extend((table.name, column) for column in sorted(booleans))

    columns = Namespace(f"table {table.name}")
    column_names = {
        column.name: columns.allocate(column.name, "column", table.name) for column in table.columns
    }
    report.column_count += len(column_names)

    definitions = [
        _target_column(column, column_names[column.name], booleans, parsed, table, report).render()
        for column in table.columns
    ]

    if table.primary_key or table.has_unique_index:
        primary_key = tuple(column_names[name] for name in table.primary_key)
    else:
        report.surrogate_key_tables.append(table.name)
        surrogate = columns.allocate(SURROGATE_KEY_COLUMN, "column", table.name)
        row_hash = columns.allocate(SOURCE_ROW_HASH_COLUMN, "column", table.name)
        definitions.append(f"{quote(surrogate)} bigint GENERATED ALWAYS AS IDENTITY")
        definitions.append(f"{quote(row_hash)} text")
        primary_key = (surrogate,)

    for name, sql_type in PROVENANCE_COLUMNS:
        definitions.append(f"{quote(columns.allocate(name, 'column', table.name))} {sql_type}")

    constraints = Namespace(f"constraints of {table.name}")
    if primary_key:
        key_name = relations.allocate(f"{table.name}_pkey", "primary key", table.name)
        constraints.allocate(key_name, "primary key", table.name)
        keys = ", ".join(quote(name) for name in primary_key)
        definitions.append(f"CONSTRAINT {quote(key_name)} PRIMARY KEY ({keys})")

    definitions.extend(
        _check_constraints(table, parsed, column_names, booleans, constraints, report)
    )
    report.renames.extend(columns.renames)
    report.renames.extend(constraints.renames)

    body = ",\n    ".join(definitions)
    statement = f"CREATE TABLE {qualify(schema, target_name)} (\n    {body}\n);"
    return _TablePlan(table, schema, target_name, column_names, booleans, statement)


def _target_column(
    column: SourceColumn,
    target_name: str,
    booleans: frozenset[str],
    parsed: sqlite_ddl.ParsedTable,
    table: SourceTable,
    report: GenerationReport,
) -> _TargetColumn:
    if column.name in booleans:
        sql_type = type_mapping.BOOLEAN_TYPE
    else:
        sql_type = type_mapping.map_declared_type(column.declared_type)
    identity: str | None = None
    if column.name in parsed.autoincrement_columns or column.name == table.rowid_alias_key:
        # OD-016 and OD-022. BY DEFAULT, not ALWAYS: the load inserts the source's
        # own key values. AUTOINCREMENT is not the test -- SQLite auto-assigns any
        # single-column INTEGER PRIMARY KEY on a rowid table, so a table that never
        # declared AUTOINCREMENT would otherwise stop auto-assigning keys here and
        # reject an ordinary insert. Every one of these sequences must be reset to
        # max(key) + 1 once its table has loaded.
        identity = "BY DEFAULT"
        sql_type = type_mapping.INTEGER_IDENTITY_TYPE
        report.identity_columns.append((table.name, column.name))
    default = (
        None if column.default is None else type_mapping.translate_default(column.default, sql_type)
    )
    if identity is not None and default is not None:
        raise GenerationError(
            f"{table.name}.{column.name} declares both an identity and a default {default!r}"
        )
    return _TargetColumn(target_name, sql_type, column.not_null, default, identity)


def _check_constraints(
    table: SourceTable,
    parsed: sqlite_ddl.ParsedTable,
    column_names: Mapping[str, str],
    booleans: frozenset[str],
    constraints: Namespace,
    report: GenerationReport,
) -> list[str]:
    rendered: list[str] = []
    for position, check in enumerate(parsed.checks, start=1):
        if expressions.uses_sqlite_only_function(check.expression):
            report.dropped_checks.append(
                DroppedCheck(
                    table=table.name,
                    column=check.column,
                    predicate=check.expression,
                    reason="uses a SQLite-only function with no PostgreSQL equivalent",
                )
            )
            continue
        owner = f"{table.name}_{check.column}" if check.column else table.name
        name = constraints.allocate(f"{owner}_ck{position}", "check constraint", table.name)
        predicate = expressions.rewrite(check.expression, column_names, booleans)
        rendered.append(f"CONSTRAINT {quote(name)} CHECK {predicate}")
        report.checks_emitted += 1
    return rendered


def _foreign_keys(
    plan: _TablePlan,
    plans: Mapping[str, _TablePlan],
    report: GenerationReport,
) -> list[tuple[str, str]]:
    statements: list[tuple[str, str]] = []
    constraints = Namespace(f"foreign keys of {plan.source.name}")
    for foreign_key in plan.source.foreign_keys:
        target = plans.get(foreign_key.referenced_table)
        if target is None:
            report.skipped_foreign_keys.append(
                SkippedForeignKey(
                    table=plan.source.name,
                    referenced_table=foreign_key.referenced_table,
                    reason="referenced table is not created in the target",
                )
            )
            continue
        name = constraints.allocate(
            f"{plan.source.name}_fk{foreign_key.identifier}", "foreign key", plan.source.name
        )
        columns = ", ".join(quote(plan.column_names[column]) for column in foreign_key.from_columns)
        referenced = ", ".join(
            quote(target.column_names[column]) for column in foreign_key.to_columns
        )
        relation = qualify(target.schema, target.name)
        statements.append(
            (
                # NOT VALID: the constraint binds every future row immediately but
                # does not scan the rows already there. SQLite never enforced its
                # declared foreign keys, so the corpus may contain orphans, and
                # OD-017 requires those be surfaced with a count rather than
                # aborting the migration or being laundered away. Validation is a
                # separate, reportable step (`migration validate-foreign-keys`).
                f"ALTER TABLE {qualify(plan.schema, plan.name)}\n"
                f"    ADD CONSTRAINT {quote(name)} FOREIGN KEY ({columns})\n"
                f"    REFERENCES {relation} ({referenced})\n"
                f"    ON DELETE {foreign_key.on_delete} ON UPDATE {foreign_key.on_update}\n"
                f"    NOT VALID;",
                f"ALTER TABLE {qualify(plan.schema, plan.name)} "
                f"DROP CONSTRAINT IF EXISTS {quote(name)};",
            )
        )
    report.renames.extend(constraints.renames)
    return statements


def _indexes(
    plan: _TablePlan,
    relations: Namespace,
    report: GenerationReport,
) -> list[tuple[str, str]]:
    statements: list[tuple[str, str]] = []
    for index in plan.source.indexes:
        if index.origin == "pk":
            continue  # covered by the primary-key constraint on the table
        if index.origin == "u":
            statements.append(_implicit_unique_index(plan, index, relations, report))
        else:
            statements.append(_explicit_index(plan, index, relations, report))
    return statements


def _implicit_unique_index(
    plan: _TablePlan,
    index: SourceIndex,
    relations: Namespace,
    report: GenerationReport,
) -> tuple[str, str]:
    """Name a table-level ``UNIQUE(...)`` index, which SQLite left as ``sqlite_autoindex_*``."""
    suffix = index.name.rsplit("_", 1)[-1]
    name = relations.allocate(f"{plan.source.name}_uq{suffix}", "unique index", plan.source.name)
    columns = []
    for column in index.columns:
        if column is None:
            raise GenerationError(f"implicit unique index {index.name!r} has an expression key")
        columns.append(quote(plan.column_names[column]))
    report.unique_index_count += 1
    return (
        f"CREATE UNIQUE INDEX {quote(name)} ON {qualify(plan.schema, plan.name)} "
        f"({', '.join(columns)});",
        f"DROP INDEX IF EXISTS {qualify(plan.schema, name)};",
    )


def _explicit_index(
    plan: _TablePlan,
    index: SourceIndex,
    relations: Namespace,
    report: GenerationReport,
) -> tuple[str, str]:
    if index.sql is None:
        raise GenerationError(f"index {index.name!r} has no source statement")
    parsed = sqlite_ddl.parse_index(index.sql)
    name = relations.allocate(index.name, "index", plan.source.name)
    keys = ", ".join(
        expressions.rewrite(key, plan.column_names, plan.boolean_columns)
        for key in parsed.key_expressions
    )
    predicate = ""
    if parsed.predicate is not None:
        rewritten = expressions.rewrite(parsed.predicate, plan.column_names, plan.boolean_columns)
        predicate = f"\n    WHERE {rewritten}"
        report.partial_index_count += 1
    if any(column is None for column in index.columns):
        report.expression_index_count += 1
    if index.unique:
        report.unique_index_count += 1
    unique = "UNIQUE " if index.unique else ""
    return (
        f"CREATE {unique}INDEX {quote(name)} ON {qualify(plan.schema, plan.name)}"
        f" ({keys}){predicate};",
        f"DROP INDEX IF EXISTS {qualify(plan.schema, name)};",
    )
