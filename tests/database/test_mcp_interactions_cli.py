"""`apps/cli/mcp_interactions.py` end to end, against a current-head clone.

`list`, `show`, `search` and `purge` run through `run_mcp_interactions` with a
runtime over `db_engine` and the real clock. Rows are written with the store's
own `insert_interaction`; a row older than retention is written the way
`tests/database/test_mcp_interaction_store.py` writes one: its insert disables
only the `recorded_at` stamping trigger inside the same transaction and
re-enables it before commit. Every value is synthetic.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from apps.cli.mcp_interactions import (
    EXIT_OK,
    EXIT_REFUSED,
    EXIT_REMAINING,
    Runtime,
    run_mcp_interactions,
)
from sqlalchemy import Engine, func, insert, text

from my_pa.infrastructure.persistence.mcp_interactions import (
    RETENTION_DAYS,
    insert_interaction,
    mcp_interactions,
)

pytestmark = pytest.mark.database

STAMP_TRIGGER: Final = "mcp_interactions_stamp_recorded_at"
EXPIRED: Final = timedelta(days=RETENTION_DAYS + 1)
KEPT: Final = timedelta(days=RETENTION_DAYS - 1)
BODY_MARKER: Final = "synthetic-body-marker-c41e"


def _row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "interaction_id": f"mcpi_{uuid.uuid4().hex}",
        "started_at": datetime(2026, 10, 11, 12, 0, tzinfo=UTC),
        "latency_ms": 8.25,
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
        "request_body": {"jsonrpc": "2.0", "params": {"note": BODY_MARKER, "token": "[REDACTED]"}},
        "response_body": {"jsonrpc": "2.0", "result": {"content": []}},
        "request_body_text": None,
        "response_body_text": None,
        "request_headers": {"content-type": "application/json"},
        "diagnostics": {"is_error": False, "capture": {"redactions": 1}},
    }
    row.update(overrides)
    return row


def _insert(engine: Engine, **overrides: object) -> str:
    row = _row(**overrides)
    with engine.begin() as connection:
        insert_interaction(connection, row)
    return str(row["interaction_id"])


def _insert_aged(engine: Engine, age: timedelta, **overrides: object) -> str:
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


def _ids(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text("SELECT interaction_id FROM observability.mcp_interactions")
            ).scalars()
        )


def _run(engine: Engine, *argv: str) -> tuple[int, list[str]]:
    lines: list[str] = []
    runtime = Runtime(engine=engine, clock=lambda: datetime.now(UTC))
    return run_mcp_interactions(argv, runtime, out=lines.append), lines


def _listed(lines: list[str]) -> list[str]:
    """The interaction ids of the summary lines, in printed order."""
    return [line.split()[1] for line in lines if line.split()[1:2] and "mcpi_" in line.split()[1]]


# ---- list ------------------------------------------------------------------------------


def test_list_prints_newest_first_and_never_a_body(db_engine: Engine) -> None:
    older = _insert_aged(db_engine, timedelta(hours=2))
    newer = _insert(db_engine)
    code, lines = _run(db_engine, "list")
    assert code == EXIT_OK
    assert _listed(lines) == [newer, older]
    assert lines[-1] == "interactions 2"
    printed = "\n".join(lines)
    assert BODY_MARKER not in printed
    assert "client=client-synthetic-a" in printed and "capability=tasks.list" in printed


def test_list_honours_the_limit(db_engine: Engine) -> None:
    for _ in range(3):
        _insert(db_engine)
    code, lines = _run(db_engine, "list", "--limit", "2")
    assert code == EXIT_OK
    assert len(_listed(lines)) == 2
    assert lines[-1] == "interactions 2"


def test_list_of_an_empty_log(db_engine: Engine) -> None:
    assert _run(db_engine, "list") == (EXIT_OK, ["interactions 0"])


# ---- show ------------------------------------------------------------------------------


def test_show_prints_the_full_record(db_engine: Engine) -> None:
    interaction = _insert(db_engine, correlation_id="corr_synthetic0001")
    code, lines = _run(db_engine, "show", interaction)
    assert code == EXIT_OK
    printed = "\n".join(lines)
    assert interaction in printed
    assert BODY_MARKER in printed
    assert "[REDACTED]" in printed
    assert "request_headers:" in printed and "diagnostics:" in printed
    assert "corr_synthetic0001" in printed


def test_show_json_is_one_parseable_object(db_engine: Engine) -> None:
    interaction = _insert(db_engine, http_status=None, outcome="http_error")
    code, lines = _run(db_engine, "show", interaction, "--json")
    assert code == EXIT_OK
    assert len(lines) == 1
    document = json.loads(lines[0])
    assert document["interaction_id"] == interaction
    assert document["http_status"] is None
    assert document["request_body"]["params"]["note"] == BODY_MARKER
    assert datetime.fromisoformat(document["recorded_at"]).tzinfo is not None


def test_show_of_an_unknown_id_is_refused(db_engine: Engine) -> None:
    _insert(db_engine)
    code, lines = _run(db_engine, "show", f"mcpi_{uuid.uuid4().hex}")
    assert code == EXIT_REFUSED
    assert lines == ["refused           no interaction carries that identifier"]


# ---- search ----------------------------------------------------------------------------


def test_search_filters_on_each_column(db_engine: Engine) -> None:
    base = _insert(db_engine)
    other_client = _insert(db_engine, oauth_client_id="client-synthetic-b")
    other_tool = _insert(db_engine, tool_name="my_pa.read", capability="notes.list")
    correlated = _insert(
        db_engine,
        correlation_id="corr_synthetic0002",
        outcome="tool_error",
        error_code="not_found",
    )
    cases = {
        ("--client", "client-synthetic-b"): {other_client},
        ("--tool", "my_pa.read"): {other_tool},
        ("--capability", "notes.list"): {other_tool},
        ("--correlation-id", "corr_synthetic0002"): {correlated},
        ("--outcome", "tool_error"): {correlated},
        ("--client", "client-synthetic-a", "--tool", "invoke", "--outcome", "ok"): {base},
    }
    for argv, expected in cases.items():
        code, lines = _run(db_engine, "search", *argv)
        assert code == EXIT_OK, argv
        assert set(_listed(lines)) == expected, argv
        assert BODY_MARKER not in "\n".join(lines)


def test_search_with_no_filter_is_the_listing(db_engine: Engine) -> None:
    first = _insert(db_engine)
    second = _insert(db_engine)
    _, searched = _run(db_engine, "search")
    _, listed = _run(db_engine, "list")
    assert searched == listed
    assert set(_listed(searched)) == {first, second}


def test_search_time_windows(db_engine: Engine) -> None:
    old = _insert_aged(db_engine, timedelta(days=3))
    recent = _insert(db_engine)
    code, lines = _run(db_engine, "search", "--last", "1d")
    assert code == EXIT_OK
    assert _listed(lines) == [recent]
    cutoff = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert _listed(_run(db_engine, "search", "--until", cutoff)[1]) == [old]
    assert _listed(_run(db_engine, "search", "--since", cutoff)[1]) == [recent]


# ---- purge -----------------------------------------------------------------------------


def test_purge_removes_only_expired_rows_one_batch_per_run(db_engine: Engine) -> None:
    expired = {_insert_aged(db_engine, EXPIRED), _insert_aged(db_engine, EXPIRED)}
    kept = {_insert_aged(db_engine, KEPT), _insert(db_engine)}

    code, lines = _run(db_engine, "purge", "--dry-run")
    assert (code, lines[-1]) == (EXIT_OK, "deleted=0 remaining=2")
    assert lines[0] == f"dry_run retention_days={RETENTION_DAYS}"
    assert _ids(db_engine) == expired | kept

    code, lines = _run(db_engine, "purge", "--batch-size", "1")
    assert (code, lines[-1]) == (EXIT_REMAINING, "deleted=1 remaining=1")
    assert len(_ids(db_engine) & expired) == 1

    code, lines = _run(db_engine, "purge", "--batch-size", "1")
    assert (code, lines[-1]) == (EXIT_OK, "deleted=1 remaining=0")
    assert _ids(db_engine) == kept

    assert _run(db_engine, "purge") == (
        EXIT_OK,
        [f"retention_days={RETENTION_DAYS}", "deleted=0 remaining=0"],
    )
    assert _ids(db_engine) == kept


def test_a_dry_run_exits_zero_even_with_work_remaining(db_engine: Engine) -> None:
    _insert_aged(db_engine, EXPIRED)
    code, lines = _run(db_engine, "purge", "--dry-run", "--batch-size", "1")
    assert (code, lines[-1]) == (EXIT_OK, "deleted=0 remaining=1")
    assert len(_ids(db_engine)) == 1


def test_a_default_purge_drains_a_small_backlog_in_one_run(db_engine: Engine) -> None:
    for _ in range(3):
        _insert_aged(db_engine, EXPIRED)
    survivor = _insert(db_engine)
    assert _run(db_engine, "purge")[1][-1] == "deleted=3 remaining=0"
    assert _ids(db_engine) == {survivor}
