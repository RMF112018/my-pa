"""The generator's two inputs: the source profile and the disposition registry.

The profile is a machine-readable dump of the legacy SQLite schema (columns,
declared types, primary keys, foreign keys, indexes, row counts, FTS flags). The
registry says, for every source object, which PostgreSQL schema it belongs in
and whether it is created at all. Both are produced by scripts under
``scripts/migration/`` and read here as plain data.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

#: Treatments from OD-025 that cause a target table to be created.
CREATED_TREATMENTS = frozenset(
    {
        "SCHEMA_AND_DATA",
        "SCHEMA_AND_DATA_REBUILDABLE",
        "SCHEMA_ONLY_ASSERT_EMPTY",
        "SCHEMA_ONLY_EMPTY_BY_DESIGN",
        "PROVENANCE_ONLY",
    }
)


@dataclass(frozen=True)
class SourceColumn:
    name: str
    declared_type: str
    not_null: bool
    default: str | None
    pk_position: int


@dataclass(frozen=True)
class SourceForeignKey:
    identifier: int
    referenced_table: str
    from_columns: tuple[str, ...]
    to_columns: tuple[str, ...]
    on_delete: str
    on_update: str


@dataclass(frozen=True)
class SourceIndex:
    name: str
    unique: bool
    origin: str
    partial: bool
    columns: tuple[str | None, ...]
    sql: str | None


@dataclass(frozen=True)
class SourceTable:
    name: str
    object_type: str
    sql: str
    columns: tuple[SourceColumn, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[SourceForeignKey, ...]
    indexes: tuple[SourceIndex, ...]
    row_count: int
    is_fts: bool
    is_virtual: bool
    is_internal: bool
    without_rowid: bool

    @property
    def migratable(self) -> bool:
        """True for ordinary tables: not a view, not FTS, not virtual, not SQLite internal."""
        return (
            self.object_type == "table"
            and not self.is_fts
            and not self.is_virtual
            and not self.is_internal
        )

    @property
    def has_unique_index(self) -> bool:
        return any(index.unique for index in self.indexes)

    @property
    def rowid_alias_key(self) -> str | None:
        """The column SQLite auto-assigns as the rowid alias, if the table has one.

        A single-column ``INTEGER PRIMARY KEY`` on a rowid table *is* the rowid,
        and SQLite fills it in on insert whether or not ``AUTOINCREMENT`` was
        declared. PostgreSQL will not, so this column needs an identity too.
        """
        if self.without_rowid or len(self.primary_key) != 1:
            return None
        key = self.primary_key[0]
        declared = {column.name: column.declared_type.upper() for column in self.columns}
        return key if declared.get(key) == "INTEGER" else None


@dataclass(frozen=True)
class Disposition:
    legacy_object: str
    object_type: str
    target_schema: str
    target_treatment: str
    planning_disposition: str
    ordering_group: str

    @property
    def created(self) -> bool:
        return self.target_treatment in CREATED_TREATMENTS


def _column(raw: Mapping[str, Any]) -> SourceColumn:
    return SourceColumn(
        name=str(raw["name"]),
        declared_type=str(raw["declared_type"] or ""),
        not_null=bool(raw["notnull"]),
        default=None if raw["default"] is None else str(raw["default"]),
        pk_position=int(raw["pk"]),
    )


def _foreign_key(raw: Mapping[str, Any]) -> SourceForeignKey:
    return SourceForeignKey(
        identifier=int(raw["id"]),
        referenced_table=str(raw["referenced_table"]),
        from_columns=tuple(str(name) for name in raw["from_columns"]),
        to_columns=tuple(str(name) for name in raw["to_columns"]),
        on_delete=str(raw["on_delete"] or "NO ACTION"),
        on_update=str(raw["on_update"] or "NO ACTION"),
    )


def _index(raw: Mapping[str, Any]) -> SourceIndex:
    return SourceIndex(
        name=str(raw["name"]),
        unique=bool(raw["unique"]),
        origin=str(raw["origin"]),
        partial=bool(raw["partial"]),
        columns=tuple(None if name is None else str(name) for name in raw["columns"]),
        sql=None if raw["sql"] is None else str(raw["sql"]),
    )


def _table(raw: Mapping[str, Any]) -> SourceTable:
    return SourceTable(
        name=str(raw["name"]),
        object_type=str(raw["type"]),
        sql=str(raw["sql"] or ""),
        columns=tuple(_column(column) for column in raw["columns"]),
        primary_key=tuple(str(name) for name in raw["primary_key"] or ()),
        foreign_keys=tuple(_foreign_key(fk) for fk in raw["foreign_keys"]),
        indexes=tuple(_index(index) for index in raw["indexes"]),
        row_count=int(raw["row_count"] or 0),
        is_fts=bool(raw["is_fts"]),
        is_virtual=bool(raw["is_virtual"]),
        is_internal=bool(raw["is_internal"]),
        without_rowid=bool(raw["without_rowid"]),
    )


def load_profile(path: Path) -> tuple[SourceTable, ...]:
    """Read the source profile JSON into ``SourceTable`` records."""
    document: Mapping[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    objects: Sequence[Mapping[str, Any]] = document["objects"]
    return tuple(_table(raw) for raw in objects)


def load_registry(path: Path) -> dict[str, Disposition]:
    """Read the disposition registry JSON, keyed by legacy object name."""
    document: Mapping[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    entries: Sequence[Mapping[str, Any]] = document["entries"]
    return {
        str(entry["legacy_object"]): Disposition(
            legacy_object=str(entry["legacy_object"]),
            object_type=str(entry["object_type"]),
            target_schema=str(entry["target_schema"]),
            target_treatment=str(entry["target_treatment"]),
            planning_disposition=str(entry["planning_disposition"]),
            ordering_group=str(entry["ordering_group"]),
        )
        for entry in entries
    }
