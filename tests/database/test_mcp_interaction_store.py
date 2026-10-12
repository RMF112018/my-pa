"""The MCP interaction log store and the table's append-only triggers, against a server.

Each test gets a current-head clone (`db_engine`). Every value is synthetic.

**Making rows old.** `recorded_at` is DB-assigned by the BEFORE INSERT trigger
`mcp_interactions_stamp_recorded_at`, so no caller can write a row older than
now. To test retention, `_insert_aged` disables exactly that one trigger with
`ALTER TABLE ... DISABLE TRIGGER mcp_interactions_stamp_recorded_at` inside the
same transaction as its insert, and re-enables it before commit, as the clone's
superuser. `SET session_replication_role = replica` was rejected because it
would also silence the DELETE and UPDATE guards that the same tests measure.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Engine, func, insert, text
from sqlalchemy.exc import DBAPIError

from my_pa.infrastructure.persistence.mcp_interactions import (
    INSERT_COLUMNS,
    RETENTION_DAYS,
    Interaction,
    InteractionSummary,
    PurgeResult,
    get_interaction,
    insert_interaction,
    list_interactions,
    mcp_interactions,
    purge_expired,
    search_interactions,
)

pytestmark = pytest.mark.database

RESTRICT_VIOLATION: Final = "23001"
CHECK_VIOLATION: Final = "23514"
STAMP_TRIGGER: Final = "mcp_interactions_stamp_recorded_at"
OLD: Final = timedelta(days=RETENTION_DAYS, hours=1)
YOUNG: Final = timedelta(days=RETENTION_DAYS - 1)


def _id() -> str:
    return f"mcpi_{uuid.uuid4().hex}"


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "interaction_id": _id(),
        "started_at": datetime(2026, 10, 11, 12, 0, tzinfo=UTC),
        "latency_ms": 12.5,
        "http_method": "POST",
        "http_status": 200,
        "oauth_client_id": "client-synthetic-a",
        "principal_id": "prn_synthetic0001",
        "principal_kind": "operator",
        "mcp_session_id": None,
        "jsonrpc_method": "tools/call",
        "jsonrpc_id": "1",
        "tool_name": "invoke",
        "capability": "tasks.list",
        "correlation_id": None,
        "outcome": "ok",
        "error_code": None,
        "request_bytes": 64,
        "response_bytes": 128,
        "request_sha256": "a" * 64,
        "response_sha256": "b" * 64,
        "request_truncated": False,
        "response_truncated": False,
        "request_body": {"jsonrpc": "2.0", "method": "tools/call", "params": {"name": "invoke"}},
        "response_body": {"jsonrpc": "2.0", "result": {"content": []}},
        "request_body_text": None,
        "response_body_text": None,
        "request_headers": {"content-type": "application/json"},
        "diagnostics": {"is_error": False, "capture": {"redactions": 0}},
    }
    row.update(overrides)
    return row


def _insert(engine: Engine, **overrides: object) -> str:
    row = _row(**overrides)
    with engine.begin() as connection:
        insert_interaction(connection, row)
    return str(row["interaction_id"])


def _insert_aged(engine: Engine, age: timedelta, **overrides: object) -> str:
    """Insert one row whose `recorded_at` is `age` before the database clock.

    Disables only the stamping trigger, inside this transaction (module docstring).
    """
    row = _row(**overrides)
    with engine.begin() as connection:
        connection.execute(
            text(f"ALTER TABLE observability.mcp_interactions DISABLE TRIGGER {STAMP_TRIGGER}")
        )
        connection.execute(
            insert(mcp_interactions).values({**row, "recorded_at": func.clock_timestamp() - age})
        )
        connection.execute(
            text(f"ALTER TABLE observability.mcp_interactions ENABLE TRIGGER {STAMP_TRIGGER}")
        )
    return str(row["interaction_id"])


def _count(engine: Engine) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM observability.mcp_interactions")
            ).scalar_one()
        )


def _sqlstate(error: DBAPIError) -> str | None:
    return getattr(error.orig, "sqlstate", None)


# --- insert and the DB-assigned clock ---------------------------------------


def test_insert_round_trips_through_show(db_engine: Engine) -> None:
    row = _row(correlation_id="corr_synthetic0001", error_code=None)
    with db_engine.begin() as connection:
        insert_interaction(connection, row)
    with db_engine.connect() as connection:
        shown = get_interaction(connection, str(row["interaction_id"]))
    assert isinstance(shown, Interaction)
    for key in INSERT_COLUMNS:
        assert getattr(shown, key) == row[key], key
    assert shown.recorded_at.tzinfo is not None


def test_show_of_an_unknown_id_is_none(db_engine: Engine) -> None:
    with db_engine.connect() as connection:
        assert get_interaction(connection, _id()) is None


def test_null_bodies_are_sql_null_not_json_null(db_engine: Engine) -> None:
    interaction_id = _insert(
        db_engine,
        request_body=None,
        response_body=None,
        request_body_text="not json",
        response_body_text=None,
        request_truncated=True,
    )
    with db_engine.connect() as connection:
        nulls = connection.execute(
            text(
                "SELECT request_body IS NULL, response_body IS NULL "
                "FROM observability.mcp_interactions WHERE interaction_id = :id"
            ),
            {"id": interaction_id},
        ).one()
    assert tuple(nulls) == (True, True)


@pytest.mark.parametrize(
    "keys",
    [
        INSERT_COLUMNS - {"diagnostics"},
        INSERT_COLUMNS | {"recorded_at"},
        INSERT_COLUMNS | {"authorization"},
    ],
)
def test_insert_refuses_a_row_whose_keys_are_not_the_column_set(
    db_engine: Engine, keys: frozenset[str]
) -> None:
    full = {**_row(), "recorded_at": datetime(2020, 1, 1, tzinfo=UTC), "authorization": "x"}
    with db_engine.begin() as connection, pytest.raises(ValueError, match="columns differ"):
        insert_interaction(connection, {key: full[key] for key in keys})
    assert _count(db_engine) == 0


def test_recorded_at_is_assigned_by_the_database_even_when_supplied(db_engine: Engine) -> None:
    backdated = datetime(2020, 1, 1, tzinfo=UTC)
    row = _row()
    with db_engine.begin() as connection:
        before = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
        connection.execute(insert(mcp_interactions).values({**row, "recorded_at": backdated}))
    with db_engine.connect() as connection:
        shown = get_interaction(connection, str(row["interaction_id"]))
    assert shown is not None
    assert shown.recorded_at != backdated
    assert shown.recorded_at >= before


# --- append-only triggers ---------------------------------------------------


def test_update_is_refused(db_engine: Engine) -> None:
    interaction_id = _insert(db_engine)
    with db_engine.begin() as connection, pytest.raises(DBAPIError) as refused:
        connection.execute(
            text(
                "UPDATE observability.mcp_interactions SET outcome = 'tool_error' "
                "WHERE interaction_id = :id"
            ),
            {"id": interaction_id},
        )
    assert _sqlstate(refused.value) == RESTRICT_VIOLATION


def test_update_of_an_old_row_inside_the_purge_switch_is_refused(db_engine: Engine) -> None:
    interaction_id = _insert_aged(db_engine, OLD)
    with db_engine.begin() as connection, pytest.raises(DBAPIError) as refused:
        connection.execute(text("SET LOCAL my_pa.mcp_interaction_purge = 'on'"))
        connection.execute(
            text(
                "UPDATE observability.mcp_interactions SET outcome = 'tool_error' "
                "WHERE interaction_id = :id"
            ),
            {"id": interaction_id},
        )
    assert _sqlstate(refused.value) == RESTRICT_VIOLATION


def test_delete_without_the_purge_switch_is_refused_even_for_an_old_row(
    db_engine: Engine,
) -> None:
    interaction_id = _insert_aged(db_engine, OLD)
    with db_engine.begin() as connection, pytest.raises(DBAPIError) as refused:
        connection.execute(
            text("DELETE FROM observability.mcp_interactions WHERE interaction_id = :id"),
            {"id": interaction_id},
        )
    assert _sqlstate(refused.value) == RESTRICT_VIOLATION
    assert _count(db_engine) == 1


@pytest.mark.parametrize("age", [timedelta(0), YOUNG])
def test_delete_with_the_purge_switch_is_refused_for_a_row_inside_retention(
    db_engine: Engine, age: timedelta
) -> None:
    interaction_id = _insert(db_engine) if not age else _insert_aged(db_engine, age)
    with db_engine.begin() as connection, pytest.raises(DBAPIError) as refused:
        connection.execute(text("SET LOCAL my_pa.mcp_interaction_purge = 'on'"))
        connection.execute(
            text("DELETE FROM observability.mcp_interactions WHERE interaction_id = :id"),
            {"id": interaction_id},
        )
    assert _sqlstate(refused.value) == RESTRICT_VIOLATION
    assert _count(db_engine) == 1


def test_delete_with_the_switch_set_to_anything_but_on_is_refused(db_engine: Engine) -> None:
    interaction_id = _insert_aged(db_engine, OLD)
    with db_engine.begin() as connection, pytest.raises(DBAPIError) as refused:
        connection.execute(text("SET LOCAL my_pa.mcp_interaction_purge = 'true'"))
        connection.execute(
            text("DELETE FROM observability.mcp_interactions WHERE interaction_id = :id"),
            {"id": interaction_id},
        )
    assert _sqlstate(refused.value) == RESTRICT_VIOLATION


def test_truncate_is_refused(db_engine: Engine) -> None:
    _insert(db_engine)
    with db_engine.begin() as connection, pytest.raises(DBAPIError) as refused:
        connection.execute(text("TRUNCATE observability.mcp_interactions"))
    assert _sqlstate(refused.value) == RESTRICT_VIOLATION
    assert _count(db_engine) == 1


def test_truncate_of_an_empty_table_is_refused(db_engine: Engine) -> None:
    with db_engine.begin() as connection, pytest.raises(DBAPIError) as refused:
        connection.execute(text("TRUNCATE observability.mcp_interactions"))
    assert _sqlstate(refused.value) == RESTRICT_VIOLATION


# --- purge ------------------------------------------------------------------


def test_purge_deletes_only_rows_older_than_retention(db_engine: Engine) -> None:
    old = {_insert_aged(db_engine, OLD), _insert_aged(db_engine, timedelta(days=40))}
    young = {_insert_aged(db_engine, YOUNG), _insert(db_engine)}
    with db_engine.begin() as connection:
        result = purge_expired(connection, batch_size=100, dry_run=False)
    assert result == PurgeResult(deleted=2, remaining=0)
    with db_engine.connect() as connection:
        kept = {
            str(value)
            for value in connection.execute(
                text("SELECT interaction_id FROM observability.mcp_interactions")
            ).scalars()
        }
    assert kept == young
    assert kept.isdisjoint(old)


def test_purge_turns_the_switch_off_before_returning(db_engine: Engine) -> None:
    old = _insert_aged(db_engine, OLD)
    newer_old = _insert_aged(db_engine, OLD)
    with db_engine.begin() as connection:
        assert purge_expired(connection, batch_size=1, dry_run=False).deleted == 1
        survivor = old if get_interaction(connection, old) is not None else newer_old
        with pytest.raises(DBAPIError) as refused, connection.begin_nested():
            connection.execute(
                text("DELETE FROM observability.mcp_interactions WHERE interaction_id = :id"),
                {"id": survivor},
            )
        assert _sqlstate(refused.value) == RESTRICT_VIOLATION
    assert _count(db_engine) == 1


def test_purge_dry_run_deletes_nothing_and_reports_counts(db_engine: Engine) -> None:
    for _ in range(3):
        _insert_aged(db_engine, OLD)
    _insert(db_engine)
    with db_engine.begin() as connection:
        result = purge_expired(connection, batch_size=1, dry_run=True)
    assert result == PurgeResult(deleted=0, remaining=3)
    assert _count(db_engine) == 4


def test_purge_batches_and_reports_what_remains(db_engine: Engine) -> None:
    for _ in range(5):
        _insert_aged(db_engine, OLD)
    _insert(db_engine)
    results = []
    for _ in range(3):
        with db_engine.begin() as connection:
            results.append(purge_expired(connection, batch_size=2, dry_run=False))
    assert results == [
        PurgeResult(deleted=2, remaining=3),
        PurgeResult(deleted=2, remaining=1),
        PurgeResult(deleted=1, remaining=0),
    ]
    with db_engine.begin() as connection:
        assert purge_expired(connection, batch_size=2, dry_run=False) == PurgeResult(0, 0)
    assert _count(db_engine) == 1


@pytest.mark.parametrize("batch_size", [0, -1, 10_001])
def test_purge_refuses_an_unbounded_batch(db_engine: Engine, batch_size: int) -> None:
    with db_engine.begin() as connection, pytest.raises(ValueError, match="batch_size"):
        purge_expired(connection, batch_size=batch_size, dry_run=False)


# --- list / show / search ---------------------------------------------------


def _seed_for_search(engine: Engine) -> dict[str, str]:
    return {
        "a_ok": _insert(
            engine, oauth_client_id="client-a", tool_name="invoke", capability="tasks.list"
        ),
        "b_tool_error": _insert(
            engine,
            oauth_client_id="client-b",
            tool_name="invoke",
            capability="capture.create",
            outcome="tool_error",
            correlation_id="corr_synthetic0002",
            error_code="validation_failed",
        ),
        "a_auth": _insert(
            engine,
            oauth_client_id="client-a",
            tool_name=None,
            capability=None,
            jsonrpc_method=None,
            outcome="auth_refused",
            http_status=401,
            error_code="invalid_token",
        ),
        "b_list": _insert(
            engine,
            oauth_client_id="client-b",
            tool_name=None,
            capability=None,
            jsonrpc_method="tools/list",
        ),
    }


def test_list_is_newest_first_and_bounded(db_engine: Engine) -> None:
    seeded = _seed_for_search(db_engine)
    with db_engine.connect() as connection:
        listed = list_interactions(connection, limit=10)
        page = list_interactions(connection, limit=2)
    assert [item.interaction_id for item in listed] == list(reversed(list(seeded.values())))
    assert all(isinstance(item, InteractionSummary) for item in listed)
    assert not hasattr(listed[0], "request_body")
    assert page == listed[:2]


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({"client_id": "client-a"}, {"a_ok", "a_auth"}),
        ({"client_id": "client-b"}, {"b_tool_error", "b_list"}),
        ({"tool": "invoke"}, {"a_ok", "b_tool_error"}),
        ({"capability": "capture.create"}, {"b_tool_error"}),
        ({"correlation_id": "corr_synthetic0002"}, {"b_tool_error"}),
        ({"outcome": "auth_refused"}, {"a_auth"}),
        ({"outcome": "ok"}, {"a_ok", "b_list"}),
        ({"client_id": "client-b", "outcome": "ok"}, {"b_list"}),
        ({"client_id": "client-z"}, set()),
    ],
)
def test_search_filters(db_engine: Engine, filters: dict[str, str], expected: set[str]) -> None:
    seeded = _seed_for_search(db_engine)
    with db_engine.connect() as connection:
        found = search_interactions(connection, limit=100, **filters)  # type: ignore[arg-type]
    assert {item.interaction_id for item in found} == {seeded[name] for name in expected}


def test_search_by_time_window_is_on_recorded_at(db_engine: Engine) -> None:
    old = _insert_aged(db_engine, timedelta(days=3))
    middle = _insert_aged(db_engine, timedelta(days=1))
    recent = _insert(db_engine)
    with db_engine.connect() as connection:
        now = connection.execute(text("SELECT clock_timestamp()")).scalar_one()
        since_two_days = search_interactions(connection, since=now - timedelta(days=2), limit=100)
        until_two_days = search_interactions(connection, until=now - timedelta(days=2), limit=100)
        window = search_interactions(
            connection,
            since=now - timedelta(days=2),
            until=now - timedelta(hours=12),
            limit=100,
        )
    assert {item.interaction_id for item in since_two_days} == {middle, recent}
    assert {item.interaction_id for item in until_two_days} == {old}
    assert {item.interaction_id for item in window} == {middle}


@pytest.mark.parametrize(
    "arguments",
    [
        {"limit": 0},
        {"limit": 1_001},
        {"limit": 10, "outcome": "fine"},
        {"limit": 10, "since": datetime(2026, 10, 1)},  # naive on purpose
    ],
)
def test_search_refuses_bad_arguments(db_engine: Engine, arguments: dict[str, object]) -> None:
    with db_engine.connect() as connection, pytest.raises(ValueError):
        search_interactions(connection, **arguments)  # type: ignore[arg-type]


# --- CHECK constraints ------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        ({"interaction_id": "mcpi_" + "A" * 32}, "mcp_interaction_id_is_an_opaque_identifier"),
        ({"interaction_id": "mcpi_" + "a" * 31}, "mcp_interaction_id_is_an_opaque_identifier"),
        ({"interaction_id": "mcp_" + "a" * 32}, "mcp_interaction_id_is_an_opaque_identifier"),
        ({"request_sha256": "A" * 64}, "mcp_interaction_request_sha256_is_a_digest"),
        ({"response_sha256": "b" * 63}, "mcp_interaction_response_sha256_is_a_digest"),
        ({"outcome": "fine"}, "mcp_interaction_outcome_is_known"),
        ({"latency_ms": -0.1}, "mcp_interaction_latency_is_not_negative"),
        ({"request_bytes": -1}, "mcp_interaction_request_bytes_are_not_negative"),
        ({"response_bytes": -1}, "mcp_interaction_response_bytes_are_not_negative"),
        ({"request_body_text": "{}"}, "mcp_interaction_request_body_is_one_form"),
        ({"response_body_text": "{}"}, "mcp_interaction_response_body_is_one_form"),
        ({"request_truncated": True}, "mcp_interaction_truncated_request_has_no_json_body"),
        ({"response_truncated": True}, "mcp_interaction_truncated_response_has_no_json_body"),
    ],
)
def test_check_constraints_refuse(
    db_engine: Engine, overrides: dict[str, object], constraint: str
) -> None:
    with db_engine.begin() as connection, pytest.raises(DBAPIError) as refused:
        insert_interaction(connection, _row(**overrides))
    assert _sqlstate(refused.value) == CHECK_VIOLATION
    assert getattr(refused.value.orig.diag, "constraint_name", None) == constraint  # type: ignore[union-attr]


def test_a_truncated_body_is_stored_as_text(db_engine: Engine) -> None:
    interaction_id = _insert(
        db_engine,
        response_truncated=True,
        response_body=None,
        response_body_text='{"jsonrpc": "2.0", "result": ',
    )
    with db_engine.connect() as connection:
        shown = get_interaction(connection, interaction_id)
    assert shown is not None
    assert shown.response_body is None
    assert shown.response_body_text == '{"jsonrpc": "2.0", "result": '
