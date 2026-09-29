"""WP-RE-01: the Record Event tables as the server holds them (RE-AC-002..006).

Marked `database` (auto `database_clone`) and routed to `database-current-head`:
every test runs against a disposable clone migrated to head, so what is checked
is the schema the Record Event revision actually created, not `tables.py`.

* **RE-AC-004** -- `record_events` has exactly the seventeen metadata columns of
  hardened package section 4.2 and no narrative or payload column.
* **RE-AC-002 / RE-AC-003** -- each CHECK clause refuses its own violation with
  its own named constraint: one test per clause, including one per
  `changed_fields` clause (cardinality, one dimension, no NULL element, token
  shape, token length).
* **RE-AC-005 / RE-AC-006** -- an UPDATE and a DELETE of a committed event are
  refused by the append-only trigger with SQLSTATE 23001 (`restrict_violation`).
* the per-Principal UNIQUE sequence, the same-Principal causation reference and
  the server-set `recorded_at`.

Every identity here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest
from sqlalchemy import Engine, delete, insert, select, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import record_event_sequences, record_events

pytestmark = [pytest.mark.database]

WHEN: Final = datetime(2026, 9, 29, 12, tzinfo=UTC)
CHECK_VIOLATION: Final = "23514"
UNIQUE_VIOLATION: Final = "23505"
FOREIGN_KEY_VIOLATION: Final = "23503"
RESTRICT_VIOLATION: Final = "23001"

COLUMNS: Final = frozenset(
    {
        "event_id",
        "principal_id",
        "sequence_number",
        "record_family",
        "record_id",
        "event_kind",
        "record_version",
        "changed_fields",
        "source_capability",
        "source_receipt_id",
        "actor_class",
        "authority",
        "classification",
        "correlation_id",
        "causation_event_id",
        "occurred_at",
        "recorded_at",
    }
)


@pytest.fixture
def engine(db_engine: Engine) -> Engine:
    return db_engine


def _row(principal_id: str, sequence_number: int = 1, /, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "event_id": issue_identifier(IdKind.RECORD_EVENT),
        "principal_id": principal_id,
        "sequence_number": sequence_number,
        "record_family": "task",
        "record_id": "tsk_persist00000001",
        "event_kind": "updated",
        "record_version": 2,
        "changed_fields": ["title", "version"],
        "source_capability": "tasks.update",
        "source_receipt_id": "thst_persist0000001",
        "actor_class": "principal",
        "authority": None,
        "classification": "private_local",
        "correlation_id": "corr_persist0000001",
        "causation_event_id": None,
        "occurred_at": WHEN,
    }
    row.update(overrides)
    return row


def _refused(engine: Engine, row: dict[str, object]) -> tuple[str | None, str | None]:
    with pytest.raises(IntegrityError) as refused, engine.begin() as connection:
        connection.execute(insert(record_events).values(**row))
    diag = getattr(refused.value.orig, "diag", None)
    return (
        getattr(refused.value.orig, "sqlstate", None),
        getattr(diag, "constraint_name", None),
    )


def _principal() -> str:
    return issue_identifier(IdKind.PRINCIPAL)


def test_the_feed_has_exactly_the_seventeen_metadata_columns(engine: Engine) -> None:
    with engine.connect() as connection:
        columns = set(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'knowledge' AND table_name = 'record_events'"
                )
            ).scalars()
        )
    assert columns == COLUMNS


def test_a_well_formed_event_is_accepted_and_recorded_at_is_server_set(engine: Engine) -> None:
    row = _row(_principal())
    with engine.begin() as connection:
        connection.execute(insert(record_events).values(**row))
        recorded = connection.execute(
            select(record_events.c.recorded_at, record_events.c.changed_fields).where(
                record_events.c.event_id == row["event_id"]
            )
        ).one()
    assert recorded.recorded_at is not None
    assert recorded.changed_fields == ["title", "version"]


def test_an_empty_changed_fields_set_is_accepted(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(insert(record_events).values(**_row(_principal(), changed_fields=[])))


CHECKED: Final[list[tuple[str, dict[str, object], str]]] = [
    # RE-AC-002
    ("sequence_zero", {"sequence_number": 0}, "a_record_event_sequence_is_positive"),
    ("version_zero", {"record_version": 0}, "a_record_event_version_is_positive"),
    # RE-AC-003, one per clause
    (
        "changed_fields_over_64",
        {"changed_fields": [f"f{index:03d}" for index in range(65)]},
        "a_record_event_changed_fields_are_bounded",
    ),
    (
        "changed_fields_two_dimensional",
        {"changed_fields": [["title"], ["version"]]},
        "a_record_event_changed_fields_are_bounded",
    ),
    (
        "changed_fields_null_element",
        {"changed_fields": ["title", None]},
        "a_record_event_changed_fields_are_bounded",
    ),
    (
        "changed_fields_not_lower_snake",
        {"changed_fields": ["Title"]},
        "a_record_event_changed_fields_are_bounded",
    ),
    (
        "changed_fields_token_over_64",
        {"changed_fields": ["a" * 65]},
        "a_record_event_changed_fields_are_bounded",
    ),
    (
        "changed_fields_empty_token",
        {"changed_fields": [""]},
        "a_record_event_changed_fields_are_bounded",
    ),
    # opaque identity (RE-AC-001's server half)
    ("event_id_kind", {"event_id": "tsk_persist00000009"}, "event_id_is_an_opaque_identifier"),
    (
        "principal_id_kind",
        {"principal_id": "ent_persist0000009"},
        "principal_id_is_an_opaque_identifier",
    ),
    (
        "record_id_path",
        {"record_id": "notes/one.txt"},
        "a_record_event_record_id_is_an_opaque_identifier",
    ),
    (
        "receipt_id_text",
        {"source_receipt_id": "a receipt"},
        "a_record_event_receipt_id_is_an_opaque_identifier",
    ),
    (
        "correlation_kind",
        {"correlation_id": "tsk_persist00000009"},
        "correlation_id_is_an_opaque_identifier",
    ),
    (
        "causation_kind",
        {"causation_event_id": "tsk_persist00000009"},
        "causation_event_id_is_an_opaque_identifier",
    ),
    # closed vocabularies
    ("family", {"record_family": "tasks"}, "a_record_event_family_is_known"),
    ("kind", {"event_kind": "deleted"}, "a_record_event_kind_is_known"),
    ("actor", {"actor_class": "model"}, "a_record_event_actor_class_is_known"),
    ("classification", {"classification": "public"}, "a_record_event_classification_is_known"),
    ("authority", {"authority": "model_inference"}, "a_record_event_authority_is_known"),
    # source_capability
    ("capability_empty", {"source_capability": ""}, "a_record_event_source_capability_is_bounded"),
    (
        "capability_shape",
        {"source_capability": "Tasks Update"},
        "a_record_event_source_capability_is_bounded",
    ),
    (
        "capability_length",
        {"source_capability": "a" * 129},
        "a_record_event_source_capability_is_bounded",
    ),
]


@pytest.mark.parametrize(
    ("override", "constraint"),
    [(override, constraint) for _, override, constraint in CHECKED],
    ids=[name for name, _, _ in CHECKED],
)
def test_each_check_clause_refuses_its_own_violation(
    engine: Engine, override: dict[str, object], constraint: str
) -> None:
    assert _refused(engine, _row(_principal(), **override)) == (CHECK_VIOLATION, constraint)


def test_an_event_cannot_name_itself_as_its_cause(engine: Engine) -> None:
    event_id = issue_identifier(IdKind.RECORD_EVENT)
    state, constraint = _refused(
        engine, _row(_principal(), event_id=event_id, causation_event_id=event_id)
    )
    assert state == CHECK_VIOLATION
    assert constraint == "a_record_event_is_not_its_own_cause"


def test_a_sequence_number_is_unique_within_its_principal(engine: Engine) -> None:
    principal = _principal()
    with engine.begin() as connection:
        connection.execute(insert(record_events).values(**_row(principal, 1)))
        connection.execute(insert(record_events).values(**_row(_principal(), 1)))
    assert _refused(engine, _row(principal, 1)) == (
        UNIQUE_VIOLATION,
        "a_record_event_sequence_is_unique_within_its_principal",
    )


def test_a_cause_must_be_an_event_of_the_same_principal(engine: Engine) -> None:
    first, second = _principal(), _principal()
    cause = _row(first, 1)
    with engine.begin() as connection:
        connection.execute(insert(record_events).values(**cause))
        # The same Principal, cause inserted earlier in the same statement order.
        connection.execute(
            insert(record_events).values(**_row(first, 2, causation_event_id=cause["event_id"]))
        )
    for row in (
        _row(second, 1, causation_event_id=cause["event_id"]),
        _row(first, 3, causation_event_id=issue_identifier(IdKind.RECORD_EVENT)),
    ):
        assert _refused(engine, row) == (
            FOREIGN_KEY_VIOLATION,
            "a_record_event_cause_is_an_event_of_its_principal",
        )


def _committed(engine: Engine) -> dict[str, object]:
    row = _row(_principal())
    with engine.begin() as connection:
        connection.execute(insert(record_events).values(**row))
    return row


def test_an_update_of_a_committed_event_is_refused(engine: Engine) -> None:
    row = _committed(engine)
    with pytest.raises(DBAPIError) as refused, engine.begin() as connection:
        connection.execute(
            update(record_events)
            .where(record_events.c.event_id == row["event_id"])
            .values(record_version=3)
        )
    assert getattr(refused.value.orig, "sqlstate", None) == RESTRICT_VIOLATION


def test_a_delete_of_a_committed_event_is_refused(engine: Engine) -> None:
    row = _committed(engine)
    with pytest.raises(DBAPIError) as refused, engine.begin() as connection:
        connection.execute(delete(record_events).where(record_events.c.event_id == row["event_id"]))
    assert getattr(refused.value.orig, "sqlstate", None) == RESTRICT_VIOLATION


def test_the_allocator_row_is_mutable_and_bounded(engine: Engine) -> None:
    principal = _principal()
    with engine.begin() as connection:
        connection.execute(
            insert(record_event_sequences).values(principal_id=principal, next_sequence=1)
        )
        connection.execute(
            update(record_event_sequences)
            .where(record_event_sequences.c.principal_id == principal)
            .values(next_sequence=5)
        )
    with pytest.raises(IntegrityError) as refused, engine.begin() as connection:
        connection.execute(
            insert(record_event_sequences).values(principal_id=_principal(), next_sequence=0)
        )
    assert refused.value.orig.diag.constraint_name == "a_record_event_next_sequence_is_positive"  # type: ignore[union-attr]
    with pytest.raises(IntegrityError) as shaped, engine.begin() as connection:
        connection.execute(
            insert(record_event_sequences).values(principal_id="prn_bad", next_sequence=1)
        )
    assert shaped.value.orig.diag.constraint_name == "principal_id_is_an_opaque_identifier"  # type: ignore[union-attr]
