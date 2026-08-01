"""The loader against a real PostgreSQL server and a synthetic SQLite source.

Everything asserted here is a contract the migration depends on: rows land with
their provenance, a defect is quarantined rather than dropped or fatal, a
half-finished load resumes exactly, a finished one re-runs as a no-op, and a
dry run leaves nothing behind. No real data is read; the source is built by the
fixture in `conftest.py`.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from conftest import (
    PHASE_ONE,
    PHASE_TWO,
    SCHEMA_VERSION,
    build_source,
    prepare_target,
    synthetic_registry,
)
from sqlalchemy import Engine, text

from my_pa.infrastructure.migration import binding, loader, runs
from my_pa.infrastructure.migration.control_plane import (
    QuarantineCode,
    RunStatus,
    TableState,
)
from my_pa.infrastructure.migration.natural_key import hash_values

pytestmark = pytest.mark.database

#: One row per shape under test. `w3` holds text in an INTEGER column, `d2` has
#: a NULL TEXT primary key, and the two `widget_metrics` rows are identical.
ROWS: tuple[tuple[str, Sequence[object]], ...] = (
    (
        "INSERT INTO widget_records (widget_id, label, weight, tally, is_current) "
        "VALUES (?, ?, ?, ?, ?)",
        ("w1", "alpha", 1.5, 10, 1),
    ),
    (
        "INSERT INTO widget_records (widget_id, label, weight, tally, is_current) "
        "VALUES (?, ?, ?, ?, ?)",
        ("w2", "beta", None, None, 0),
    ),
    (
        "INSERT INTO widget_records (widget_id, label, weight, tally, is_current) "
        "VALUES (?, ?, ?, ?, ?)",
        ("w3", "gamma", 2.0, "not-a-number", 1),
    ),
    ("INSERT INTO widget_defects (defect_id, note) VALUES (?, ?)", ("d1", "present")),
    ("INSERT INTO widget_defects (defect_id, note) VALUES (?, ?)", (None, "absent key")),
    # SQLite stores U+0000 in a TEXT value; PostgreSQL `text` cannot hold it.
    ("INSERT INTO widget_defects (defect_id, note) VALUES (?, ?)", ("d3", "a\x00b")),
    ("INSERT INTO widget_events (event_id, widget_id, detail) VALUES (?, ?, ?)", (7, "w1", "e1")),
    ("INSERT INTO widget_events (event_id, widget_id, detail) VALUES (?, ?, ?)", (9, "w2", "e2")),
    ("INSERT INTO widget_notes (note_id, body) VALUES (?, ?)", (4, "note")),
    ("INSERT INTO widget_metrics (sample, taken_utc) VALUES (?, ?)", (1.0, "t0")),
    ("INSERT INTO widget_metrics (sample, taken_utc) VALUES (?, ?)", (1.0, "t0")),
)


@pytest.fixture
def source(tmp_path: Path) -> Path:
    return build_source(tmp_path / "synthetic.sqlite", ROWS)


@pytest.fixture
def prepared(target: Engine, source: Path) -> Engine:
    prepare_target(target, source)
    return target


def _new_run(engine: Engine, source: Path, *, dry_run: bool = False) -> str:
    with engine.begin() as connection:
        return runs.create_run(connection, binding.observe(source, connection), dry_run=dry_run)


def _load(engine: Engine, source: Path, run_id: str, **kwargs: object) -> loader.LoadOutcome:
    return loader.load(
        engine,
        source,
        synthetic_registry(),
        run_id,
        **kwargs,  # type: ignore[arg-type]
    )


def _count(engine: Engine, relation: str) -> int:
    # S608: `relation` is a literal written in this file, not input.
    statement = f"SELECT count(*) FROM {relation}"  # noqa: S608
    with engine.connect() as connection:
        return int(connection.execute(text(statement)).scalar_one())


def _rows(engine: Engine, statement: str) -> list[tuple[object, ...]]:
    with engine.connect() as connection:
        return [tuple(row) for row in connection.execute(text(statement))]


def test_a_clean_load_lands_every_selected_table_with_its_provenance(
    prepared: Engine, source: Path
) -> None:
    run_id = _new_run(prepared, source)

    outcome = _load(prepared, source, run_id, batch_size=2)

    assert _count(prepared, "core.widget_records") == 2
    assert _count(prepared, "core.widget_defects") == 1
    assert _count(prepared, "core.widget_events") == 2
    assert _count(prepared, "core.widget_notes") == 1
    assert _count(prepared, "core.widget_metrics") == 2
    assert outcome.loaded == 8
    assert outcome.quarantined == 3

    provenance = _rows(
        prepared,
        "SELECT migration_run_id::text, migration_source_table, "
        "migration_source_schema_version, migration_natural_key_hash "
        "FROM core.widget_records WHERE widget_id = 'w1'",
    )
    assert provenance == [(run_id, "widget_records", SCHEMA_VERSION, hash_values(["w1"]))]

    # The promoted boolean and the REAL survive as their target types.
    assert _rows(
        prepared, "SELECT is_current, weight FROM core.widget_records WHERE widget_id = 'w1'"
    ) == [(True, 1.5)]
    # An empty value stays NULL rather than becoming an empty string.
    assert _rows(
        prepared, "SELECT weight, tally FROM core.widget_records WHERE widget_id = 'w2'"
    ) == [(None, None)]

    with prepared.connect() as connection:
        summary = runs.summarise(connection, run_id)
    assert summary.run.status is RunStatus.COMPLETED
    assert summary.rows_loaded == 8
    assert dict(summary.quarantine_by_code) == {
        QuarantineCode.NULL_PRIMARY_KEY.value: 1,
        QuarantineCode.TYPE_CAST_FAILURE.value: 1,
        QuarantineCode.UNSUPPORTED_TEXT_NUL.value: 1,
    }


def test_a_null_primary_key_is_quarantined_rather_than_fabricated(
    prepared: Engine, source: Path
) -> None:
    run_id = _new_run(prepared, source)

    _load(prepared, source, run_id, tables=["widget_defects"])

    assert _rows(prepared, "SELECT defect_id FROM core.widget_defects") == [("d1",)]
    assert (
        "widget_defects",
        "defect_id",
        "NULL_PRIMARY_KEY",
        "NullPrimaryKey",
    ) in _rows(
        prepared,
        "SELECT legacy_table, column_name, error_code, error_class "
        "FROM migration_control.quarantine_records",
    )
    # Both refused rows are counted, not lost.
    assert _rows(
        prepared,
        "SELECT source_row_count, loaded_row_count, quarantined_row_count "
        "FROM migration_control.table_progress WHERE legacy_table = 'widget_defects'",
    ) == [(3, 1, 2)]


def test_a_nul_byte_in_text_is_named_rather_than_stripped(prepared: Engine, source: Path) -> None:
    """PostgreSQL `text` cannot hold U+0000, and removing it would alter content."""
    run_id = _new_run(prepared, source)

    _load(prepared, source, run_id, tables=["widget_defects"])

    assert _rows(
        prepared,
        "SELECT legacy_table, column_name, error_code FROM migration_control.quarantine_records "
        "WHERE error_code = 'UNSUPPORTED_TEXT_NUL'",
    ) == [("widget_defects", "note", "UNSUPPORTED_TEXT_NUL")]


def test_a_value_that_will_not_cast_is_quarantined_with_its_column(
    prepared: Engine, source: Path
) -> None:
    run_id = _new_run(prepared, source)

    _load(prepared, source, run_id, tables=["widget_records"])

    assert _rows(
        prepared,
        "SELECT legacy_table, column_name, error_code FROM migration_control.quarantine_records",
    ) == [("widget_records", "tally", "TYPE_CAST_FAILURE")]
    assert _count(prepared, "core.widget_records") == 2


def test_quarantine_records_carry_no_value_from_the_row(prepared: Engine, source: Path) -> None:
    """`AGENTS.md` section 5: a key hash and a class name, never content."""
    run_id = _new_run(prepared, source)

    _load(prepared, source, run_id)

    recorded = _rows(
        prepared,
        "SELECT legacy_table, column_name, natural_key_hash, error_code, error_class "
        "FROM migration_control.quarantine_records",
    )
    flattened = " ".join(str(value) for row in recorded for value in row)
    for value in ("not-a-number", "absent key", "gamma", "alpha"):
        assert value not in flattened


def test_identity_sequences_are_reset_past_the_loaded_keys(prepared: Engine, source: Path) -> None:
    """OD-016 and OD-022: `BY DEFAULT` identity leaves the sequence behind the data."""
    run_id = _new_run(prepared, source)

    _load(prepared, source, run_id)

    with prepared.begin() as connection:
        # An ordinary insert that supplies no key has to succeed and not collide.
        connection.execute(
            text("INSERT INTO core.widget_events (widget_id, detail) VALUES ('w1', 'next')")
        )
        connection.execute(text("INSERT INTO core.widget_notes (body) VALUES ('next')"))
    assert _rows(prepared, "SELECT max(event_id) FROM core.widget_events") == [(10,)]
    assert _rows(prepared, "SELECT max(note_id) FROM core.widget_notes") == [(5,)]


def test_a_keyless_table_keeps_both_of_two_identical_rows(prepared: Engine, source: Path) -> None:
    """OD-014: the row hash is an idempotency key, not a uniqueness claim."""
    run_id = _new_run(prepared, source)

    _load(prepared, source, run_id, tables=["widget_metrics"])

    hashes = _rows(prepared, "SELECT migration_source_row_hash FROM core.widget_metrics")
    assert len(hashes) == 2
    assert hashes[0] == hashes[1]
    assert _count(prepared, "migration_control.source_key_map") == 0


def test_an_operational_state_table_is_created_and_left_empty(
    prepared: Engine, source: Path
) -> None:
    """OD-025: a queue cursor is empty by design. Carrying one forward would make
    a fresh system believe it had already processed work it has not."""
    run_id = _new_run(prepared, source)

    outcome = _load(prepared, source, run_id)

    assert _count(prepared, "core.widget_cursors") == 0
    assert "widget_cursors" not in {table.legacy_table for table in outcome.tables}


def test_only_the_named_phase_is_loaded(prepared: Engine, source: Path) -> None:
    run_id = _new_run(prepared, source)

    outcome = _load(prepared, source, run_id, phases=[PHASE_TWO])

    assert {table.legacy_table for table in outcome.tables} == {"widget_events"}
    assert _count(prepared, "core.widget_records") == 0
    assert _count(prepared, "core.widget_events") == 2


def test_re_running_a_completed_load_is_a_no_op(prepared: Engine, source: Path) -> None:
    run_id = _new_run(prepared, source)
    first = _load(prepared, source, run_id, batch_size=2)

    second = _load(prepared, source, run_id, batch_size=2)

    assert first.loaded == 8
    assert second.loaded == 0
    assert all(table.skipped for table in second.tables)
    assert _count(prepared, "core.widget_records") == 2
    assert _count(prepared, "core.widget_events") == 2


def test_a_replay_over_lost_checkpoints_quarantines_rather_than_duplicates(
    prepared: Engine, source: Path
) -> None:
    """`source_key_map` is what stops a second pass becoming a second copy."""
    run_id = _new_run(prepared, source)
    _load(prepared, source, run_id, tables=["widget_records"])
    with prepared.begin() as connection:
        connection.execute(text("DELETE FROM migration_control.batch_checkpoints"))
        connection.execute(text("DELETE FROM migration_control.table_progress"))

    outcome = _load(prepared, source, run_id, tables=["widget_records"])

    assert _count(prepared, "core.widget_records") == 2
    assert outcome.loaded == 0
    assert outcome.quarantine_by_code[QuarantineCode.DUPLICATE_NATURAL_KEY.value] == 2


def test_a_failed_load_resumes_from_its_last_checkpoint(
    prepared: Engine, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = _new_run(prepared, source)
    original = loader._copy_batch
    calls = {"count": 0}

    def failing(*args: object, **kwargs: object) -> None:
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("simulated interruption")
        original(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(loader, "_copy_batch", failing)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        _load(prepared, source, run_id, tables=["widget_records"], batch_size=1)

    assert _count(prepared, "core.widget_records") == 1
    with prepared.connect() as connection:
        assert runs.table_state(connection, run_id, "widget_records") is TableState.FAILED
        checkpoint = runs.last_checkpoint(connection, run_id, PHASE_ONE, "widget_records")
    assert checkpoint is not None
    assert checkpoint.batch_key == 0

    monkeypatch.setattr(loader, "_copy_batch", original)
    outcome = _load(prepared, source, run_id, tables=["widget_records"], batch_size=1)

    assert _count(prepared, "core.widget_records") == 2
    assert outcome.loaded == 2
    assert sorted(
        row[0] for row in _rows(prepared, "SELECT widget_id FROM core.widget_records")
    ) == [
        "w1",
        "w2",
    ]


def test_resume_continues_every_phase_that_is_not_complete(
    prepared: Engine, source: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run_id = _new_run(prepared, source)
    original = loader._copy_batch

    def failing(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated interruption")

    monkeypatch.setattr(loader, "_copy_batch", failing)
    with pytest.raises(RuntimeError):
        _load(prepared, source, run_id, phases=[PHASE_ONE])
    monkeypatch.setattr(loader, "_copy_batch", original)

    with prepared.connect() as connection:
        open_phases = runs.open_phases(connection, run_id)
    assert open_phases == (PHASE_ONE,)

    _load(prepared, source, run_id, phases=list(open_phases))

    with prepared.connect() as connection:
        assert runs.open_phases(connection, run_id) == ()
    assert _count(prepared, "core.widget_records") == 2


def test_a_dry_run_transforms_and_counts_without_committing(prepared: Engine, source: Path) -> None:
    run_id = _new_run(prepared, source, dry_run=True)

    outcome = _load(prepared, source, run_id)

    assert outcome.dry_run
    assert outcome.loaded == 8
    assert outcome.quarantined == 3
    assert _count(prepared, "core.widget_records") == 0
    assert _count(prepared, "core.widget_events") == 0
    assert _count(prepared, "migration_control.batch_checkpoints") == 0
    assert _count(prepared, "migration_control.table_progress") == 0
    assert _count(prepared, "migration_control.quarantine_records") == 0


def test_a_source_that_has_changed_refuses_to_load(prepared: Engine, source: Path) -> None:
    """HZ-SRC-DRIFT: the bound digest is the only evidence that the bytes are the bytes."""
    run_id = _new_run(prepared, source)
    with prepared.begin() as connection:
        connection.execute(
            text(
                "UPDATE migration_control.migration_runs SET source_sha256 = 'stale' "
                "WHERE run_id = :run_id"
            ),
            {"run_id": run_id},
        )

    with pytest.raises(binding.DriftError, match="HZ-SRC-DRIFT"):
        _load(prepared, source, run_id)

    assert _count(prepared, "core.widget_records") == 0
    assert _rows(
        prepared,
        "SELECT event_type, code FROM migration_control.audit_events "
        "WHERE event_type = 'IDENTITY_DRIFT_DETECTED'",
    ) == [("IDENTITY_DRIFT_DETECTED", "HZ-SRC-DRIFT")]


def test_a_table_another_run_holds_a_lease_on_is_refused(prepared: Engine, source: Path) -> None:
    holder = _new_run(prepared, source)
    run_id = _new_run(prepared, source)
    with prepared.begin() as connection:
        runs.acquire_lease(connection, holder, "table:widget_records", owner="other", seconds=600)

    with pytest.raises(runs.ControlPlaneError, match="leased by another run"):
        _load(prepared, source, run_id, tables=["widget_records"])

    assert _count(prepared, "core.widget_records") == 0


def test_a_checkpoint_may_not_move_backwards(prepared: Engine, source: Path) -> None:
    run_id = _new_run(prepared, source)
    with prepared.begin() as connection:
        runs.record_checkpoint(
            connection,
            run_id,
            PHASE_ONE,
            "widget_records",
            batch_key=3,
            watermark=30,
            rows_ok=3,
            rows_failed=0,
            rows_quarantined=0,
        )

    with (
        pytest.raises(runs.ControlPlaneError, match="move backwards"),
        prepared.begin() as (connection),
    ):
        runs.record_checkpoint(
            connection,
            run_id,
            PHASE_ONE,
            "widget_records",
            batch_key=2,
            watermark=20,
            rows_ok=1,
            rows_failed=0,
            rows_quarantined=0,
        )
