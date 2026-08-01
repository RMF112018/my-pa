"""Reading the legacy source: read-only, and resumable.

The read-only guarantee is the one thing in this migration that cannot be
undone if it is wrong, so it is asserted directly against a synthetic file:
after a read the bytes are identical and no journal, WAL, or lock file appeared
beside it. Needs no database.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import replace
from pathlib import Path

import pytest
from conftest import SCHEMA_VERSION, build_source

from my_pa.infrastructure.migration.binding import DriftError, RunBinding, file_digest
from my_pa.infrastructure.migration.reader import (
    SourceError,
    count_rows,
    iter_batches,
    open_source,
    read_shape,
    schema_version,
)

ROWS = tuple(
    ("INSERT INTO widget_notes (note_id, body) VALUES (?, ?)", (index, f"body-{index}"))
    for index in range(1, 8)
)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return build_source(tmp_path / "synthetic.sqlite", ROWS)


def test_reading_the_source_changes_nothing_beside_it(source: Path) -> None:
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    neighbours = sorted(path.name for path in source.parent.iterdir())

    with open_source(source) as connection:
        assert count_rows(connection, "widget_notes") == 7
        list(iter_batches(connection, "widget_notes", ["body"], after_rowid=0, first_batch_key=0))

    assert hashlib.sha256(source.read_bytes()).hexdigest() == before
    assert sorted(path.name for path in source.parent.iterdir()) == neighbours


def test_the_source_refuses_a_write(source: Path) -> None:
    """`immutable=1` is an enforcement, not only an intention."""
    with open_source(source) as connection, pytest.raises(sqlite3.OperationalError):
        connection.execute("INSERT INTO widget_notes (note_id, body) VALUES (99, 'x')")


def test_a_missing_source_is_named_rather_than_created(tmp_path: Path) -> None:
    with pytest.raises(SourceError, match="not found"), open_source(tmp_path / "absent.sqlite"):
        pass  # pragma: no cover - the context manager raises on entry
    assert not (tmp_path / "absent.sqlite").exists()


def test_the_schema_version_comes_from_the_source(source: Path) -> None:
    with open_source(source) as connection:
        assert schema_version(connection) == SCHEMA_VERSION


def test_a_shape_reports_the_columns_and_the_key(source: Path) -> None:
    with open_source(source) as connection:
        shape = read_shape(connection, "widget_records")

    assert shape.column_names == (
        "widget_id",
        "label",
        "weight",
        "tally",
        "is_current",
        "created_utc",
    )
    assert shape.primary_key == ("widget_id",)
    assert not shape.without_rowid


def test_batches_start_strictly_after_the_watermark(source: Path) -> None:
    with open_source(source) as connection:
        first = list(
            iter_batches(
                connection,
                "widget_notes",
                ["note_id"],
                after_rowid=0,
                first_batch_key=0,
                batch_size=3,
            )
        )
        resumed = list(
            iter_batches(
                connection,
                "widget_notes",
                ["note_id"],
                after_rowid=first[0].watermark,
                first_batch_key=1,
                batch_size=3,
            )
        )

    assert [batch.batch_key for batch in first] == [0, 1, 2]
    assert [len(batch.rows) for batch in first] == [3, 3, 1]
    assert resumed[0].batch_key == 1
    assert [row[0] for batch in resumed for row in batch.rows] == [4, 5, 6, 7]


def test_the_digest_matches_the_file(source: Path) -> None:
    digest, size = file_digest(source)

    assert digest == hashlib.sha256(source.read_bytes()).hexdigest()
    assert size == source.stat().st_size


@pytest.mark.parametrize(
    "field",
    ["source_sha256", "source_bytes", "source_schema_version", "target_alembic_revision"],
)
def test_every_bound_fact_is_checked(field: str, tmp_path: Path) -> None:
    """HZ-SRC-DRIFT and HZ-TGT-DRIFT: any one of them moving stops the run."""
    bound = RunBinding(
        source_path=tmp_path / "s.sqlite",
        source_sha256="a" * 64,
        source_bytes=10,
        source_schema_version=128,
        target_alembic_revision="abc123",
    )
    replacement = {"source_bytes": 11, "source_schema_version": 129}.get(field, "changed")

    bound.verify(bound)

    with pytest.raises(DriftError, match=field):
        bound.verify(replace(bound, **{field: replacement}))


def test_a_different_path_with_the_same_bytes_is_the_same_source(tmp_path: Path) -> None:
    bound = RunBinding(
        source_path=tmp_path / "one.sqlite",
        source_sha256="a" * 64,
        source_bytes=10,
        source_schema_version=128,
        target_alembic_revision="abc123",
    )
    bound.verify(replace(bound, source_path=tmp_path / "two.sqlite"))
