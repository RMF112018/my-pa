"""Every S6-2 CHECK, foreign key, unique, partial unique and trigger G1-G15, at head.

Schedule scenarios contract sections 14.3, 14.4 and 14.11. Each test breaks
exactly one rule and asserts the refusal names that rule: the constraint name
for a CHECK, unique or foreign key, the SQLSTATE and fixed message for a
trigger. The S5 rows the plane names (Series and publications in every status)
are seeded under `session_replication_role = replica`, so their own lifecycle
need not be replayed; every plane trigger and foreign-key case then runs in the
default mode. CHECK-only cases are inserted under `replica` too (triggers and
foreign keys silenced, CHECKs still applied), so the CHECK is the only thing
that can answer; a foreign-key case disables only the user triggers of its
table inside its own transaction, so the key is the only thing that can answer.

`database` tier (`database_clone` by default): each test gets its own clone of
the head template. Every value is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Final

import pytest
from sqlalchemy import Engine, Table, func, insert, select, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from my_pa.infrastructure.persistence.tables import (
    schedule_baseline_events,
    schedule_baselines,
    schedule_cpm_runs,
    schedule_governing_events,
    schedule_intake_series,
    schedule_scenario_outputs,
    schedule_scenario_versions,
    schedule_scenario_write_refusals,
    schedule_scenario_write_requests,
    schedule_scenarios,
    schedule_series_match_decisions,
)

pytestmark = pytest.mark.database

P: Final = "prn_s62guard0001"
Q: Final = "prn_s62guard0002"
PRJ: Final = "prj_s62guard0001"
PRJ2: Final = "prj_s62guard0002"
QPRJ: Final = "prj_s62guardq001"
DIGEST: Final = "0123456789abcdef" * 4
CONTENT: Final = "c" * 64
OTHER_CONTENT: Final = "e" * 64
SPEC: Final = "d" * 64
CHECK_VIOLATION: Final = "23514"
FOREIGN_KEY_VIOLATION: Final = "23503"
UNIQUE_VIOLATION: Final = "23505"
RESTRICT_VIOLATION: Final = "23001"

PLANE_TABLES: Final[tuple[Table, ...]] = (
    schedule_intake_series,
    schedule_series_match_decisions,
    schedule_baselines,
    schedule_baseline_events,
    schedule_governing_events,
    schedule_scenarios,
    schedule_scenario_versions,
    schedule_cpm_runs,
    schedule_scenario_outputs,
    schedule_scenario_write_requests,
    schedule_scenario_write_refusals,
)
APPEND_ONLY: Final = tuple(
    table for table in PLANE_TABLES if table is not schedule_scenario_write_requests
)

OPERATOR: Final[dict[str, Any]] = {
    "authority_class": "local_operator",
    "decision_channel": "local_cli",
    "asserting_client_id": None,
    "acceptance_basis": "user_confirmed",
}
CLIENT: Final[dict[str, Any]] = {
    "authority_class": "ordinary_reviewer",
    "decision_channel": "remote_interactive",
    "asserting_client_id": "client-7",
    "acceptance_basis": "client_identified",
}


# ---- the S5 world (replica-seeded) -------------------------------------------------


@dataclass(frozen=True)
class World:
    """P's Series and publications in every status the plane distinguishes, and Q's."""

    master: str = "sser_s62gmaster1"
    other: str = "sser_s62gother01"
    elsewhere: str = "sser_s62gelse001"
    intake: str = "sser_s62gintake1"
    complete: str = "spub_s62gcompl01"
    complete2: str = "spub_s62gcompl02"
    complete3: str = "spub_s62gcompl03"
    partial: str = "spub_s62gpartl01"
    queued: str = "spub_s62gqueue01"
    failed: str = "spub_s62gfaild01"
    review: str = "spub_s62greviw01"
    in_other: str = "spub_s62gother01"
    in_intake: str = "spub_s62gintak01"
    intake_failed: str = "spub_s62gintak02"
    q_series: str = "sser_s62gqseries"
    q_publication: str = "spub_s62gqpub001"


W: Final = World()
INTAKE_NAME: Final = "Schedule intake " + DIGEST[:12]
MISSING_SERIES: Final = "sser_s62gmissing"
ORPHAN: Final = "spub_s62gorphan1"

_PROGRESS: Final = {
    "queued": "",
    "complete": (
        ", processing_started_at = now(), completed_at = now(), accepted_parser_run_id = "
        "'sprun_s62guard0001', document_sha256 = :digest, document_size_bytes = 10, "
        "page_count = 1, row_count = 1, activity_count = 1, ambiguous_row_count = 0, "
        "issue_count = 0"
    ),
    "failed": ", processing_started_at = now(), completed_at = now(), issue_count = 1",
}


def _seed_series(c: Connection, series: str, principal: str, project: str, name: str) -> None:
    c.execute(
        text(
            "INSERT INTO knowledge.schedule_series (series_id, principal_id, project_id, name, "
            "name_key) VALUES (:s, :p, :j, :n, lower(:n))"
        ),
        {"s": series, "p": principal, "j": project, "n": name},
    )


def _seed_publication(
    c: Connection,
    publication: str,
    series: str,
    status: str,
    *,
    principal: str = P,
    project: str = PRJ,
    role: str = "update",
    kind: str | None = None,
    supersedes: str | None = None,
) -> None:
    c.execute(
        text(
            "INSERT INTO knowledge.schedule_publications (publication_id, principal_id, "
            "project_id, series_id, enrollment_id, source_object_id, source_version_id, "
            "idempotency_key, request_digest, publication_role, baseline_kind, "
            "supersedes_publication_id) VALUES (:pub, :p, :j, :s, 'enr_s62guard0001', "
            "'obj_s62guard0001', :ver, :key, :digest, :role, :kind, :sup)"
        ),
        {
            "pub": publication,
            "p": principal,
            "j": project,
            "s": series,
            "ver": "ver_" + publication[5:],
            "key": "key-" + publication[5:],
            "digest": DIGEST,
            "role": role,
            "kind": kind,
            "sup": supersedes,
        },
    )
    progress = _PROGRESS["complete" if status in ("partial", "review_required") else status]
    if progress:
        c.execute(
            text(
                f"UPDATE knowledge.schedule_publications SET status = :status{progress} "  # noqa: S608
                "WHERE publication_id = :pub"
            ),
            {"status": status, "pub": publication, "digest": DIGEST},
        )


@pytest.fixture
def engine(db_engine: Engine) -> Engine:
    with db_engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        _seed_series(c, W.master, P, PRJ, "Master")
        _seed_series(c, W.other, P, PRJ, "Other")
        _seed_series(c, W.elsewhere, P, PRJ2, "Elsewhere")
        _seed_series(c, W.intake, P, PRJ, INTAKE_NAME)
        _seed_series(c, W.q_series, Q, QPRJ, "Master")
        for publication, status in (
            (W.complete, "complete"),
            (W.complete2, "complete"),
            (W.complete3, "complete"),
            (W.partial, "partial"),
            (W.queued, "queued"),
            (W.failed, "failed"),
            (W.review, "review_required"),
        ):
            _seed_publication(c, publication, W.master, status)
        _seed_publication(c, W.in_other, W.other, "complete")
        _seed_publication(c, W.in_intake, W.intake, "complete")
        _seed_publication(c, W.q_publication, W.q_series, "complete", principal=Q, project=QPRJ)
    return db_engine


# ---- refusal helpers ------------------------------------------------------------------


def _refused(
    engine: Engine,
    act: Callable[[Connection], object],
    sqlstate: str,
    *,
    names: str | None = None,
    message: str | None = None,
    replica: bool = False,
    disable: Table | None = None,
) -> None:
    with pytest.raises(DBAPIError) as refused, engine.begin() as c:
        if replica:
            c.execute(text("SET LOCAL session_replication_role = replica"))
        if disable is not None:
            c.execute(text(f"ALTER TABLE knowledge.{disable.name} DISABLE TRIGGER USER"))
        act(c)
    orig = refused.value.orig
    assert getattr(orig, "sqlstate", None) == sqlstate, str(refused.value)[:400]
    if names is not None:
        assert orig.diag.constraint_name == names, str(refused.value)[:400]  # type: ignore[union-attr]
    if message is not None:
        assert message in str(refused.value), str(refused.value)[:400]


def _insert(table: Table, **values: Any) -> Callable[[Connection], object]:  # noqa: ANN401
    return lambda c: c.execute(insert(table).values(**values))


# ---- row builders -----------------------------------------------------------------------


def _scenario_row(n: int = 1, **overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    row: dict[str, Any] = {
        "scenario_id": f"sscn_s62gscen{n:04d}",
        "principal_id": P,
        "project_id": PRJ,
        "series_id": W.master,
        "name": "What if",
        "origin_kind": "publication",
        "origin_publication_id": W.complete,
        **OPERATOR,
    }
    row.update(overrides)
    return row


def _version_row(n: int = 1, scenario: int = 1, **overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    row: dict[str, Any] = {
        "version_id": f"sscv_s62gvers{n:04d}",
        "principal_id": P,
        "project_id": PRJ,
        "series_id": W.master,
        "scenario_id": f"sscn_s62gscen{scenario:04d}",
        "version_no": 1,
        "label": "what_if",
        "content_zlib": b"x",
        "content_sha256": CONTENT,
        "content_size_bytes": 1,
        "activity_count": 0,
        "relationship_count": 0,
        "calendar_count": 1,
        "distribution_spec_sha256": SPEC,
        "snapshot_activities": 0,
        "snapshot_milestones": 0,
        "snapshot_durations_quantized": 0,
        "snapshot_durations_out_of_range": 0,
        "snapshot_original_missing": 0,
        "snapshot_remaining_missing": 0,
        **OPERATOR,
    }
    row.update(overrides)
    return row


def _next_version_row(n: int, parent: int, version_no: int, **overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    row = _version_row(n, version_no=version_no, parent_version_id=f"sscv_s62gvers{parent:04d}")
    for name in (
        "snapshot_activities",
        "snapshot_milestones",
        "snapshot_durations_quantized",
        "snapshot_durations_out_of_range",
        "snapshot_original_missing",
        "snapshot_remaining_missing",
    ):
        row[name] = None
    row.update(
        {
            "label": "update",
            "change_set_zlib": b"y",
            "change_set_sha256": DIGEST,
            "change_set_size_bytes": 1,
            "change_set_op_count": 1,
            "ops_applied": 1,
            "relationships_removed": 0,
            "content_changed": True,
        }
    )
    row.update(overrides)
    return row


def _run_row(n: int = 1, **overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    row: dict[str, Any] = {
        "cpm_run_id": f"scpm_s62grun{n:04d}",
        "principal_id": P,
        "version_id": "sscv_s62gvers0001",
        "engine_version": "my-pa-cpm-v1",
        "input_content_sha256": CONTENT,
        "status": "computed",
        "result_zlib": b"r",
        "result_sha256": DIGEST,
        "result_size_bytes": 1,
        "activity_count": 0,
        "relationship_count": 0,
        "project_finish": "2026-06-01T08:00",
        **OPERATOR,
    }
    row.update(overrides)
    return row


def _output_row(n: int = 1, **overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    row: dict[str, Any] = {
        "output_id": f"ssco_s62gout{n:04d}",
        "principal_id": P,
        "version_id": "sscv_s62gvers0001",
        "content_sha256": CONTENT,
        "kind": "monte_carlo",
        "iterations": 100,
        "distribution_spec_sha256": SPEC,
        "payload_zlib": b"o",
        "payload_sha256": DIGEST,
        "payload_size_bytes": 1,
        **CLIENT,
    }
    row.update(overrides)
    return row


def _baseline_row(n: int = 1, publication: str = W.complete, **overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    row: dict[str, Any] = {
        "baseline_id": f"sbl_s62gbase{n:04d}",
        "principal_id": P,
        "project_id": PRJ,
        "series_id": W.master,
        "publication_id": publication,
        "type": "contract",
    }
    row.update(overrides)
    return row


def _event_fields(action: str) -> dict[str, Any]:
    if action == "propose":
        return {"type": "contract", "proposal_ordinal": 0, **CLIENT}
    if action == "approve":
        return {
            "type": "contract",
            "approval_reference": "Award letter",
            "effective_from": "2026-06-01",
            "approved_at_import": False,
            **OPERATOR,
        }
    return dict(OPERATOR if action != "withdraw" else CLIENT)


def _head(c: Connection, table: Table, key: str, project: str = PRJ) -> tuple[int, str | None]:
    row = c.execute(
        select(table.c.seq, table.c[key])
        .where(table.c.principal_id == P, table.c.project_id == project)
        .order_by(table.c.seq.desc())
        .limit(1)
    ).first()
    return (0, None) if row is None else (int(row[0]), str(row[1]))


def _event(
    c: Connection,
    n: int,
    action: str,
    baseline: int = 1,
    publication: str = W.complete,
    **overrides: Any,  # noqa: ANN401
) -> None:
    """Append one event at the Project chain's head (overrides may break any rule)."""
    seq, previous = _head(c, schedule_baseline_events, "event_id")
    approvals = c.execute(
        select(func.count()).where(
            schedule_baseline_events.c.principal_id == P,
            schedule_baseline_events.c.project_id == PRJ,
            schedule_baseline_events.c.action == "approve",
        )
    ).scalar_one()
    row: dict[str, Any] = {
        "event_id": f"sbev_s62gevnt{n:04d}",
        "principal_id": P,
        "project_id": PRJ,
        "baseline_id": f"sbl_s62gbase{baseline:04d}",
        "publication_id": publication,
        "action": action,
        "seq": seq + 1,
        "previous_event_id": previous,
        "recorded_at": func.clock_timestamp(),
        "reason": "Synthetic reason",
        **_event_fields(action),
    }
    if action == "approve":
        row["label"] = f"BL-{approvals}"
    row.update(overrides)
    c.execute(insert(schedule_baseline_events).values(**row))


def _governing(c: Connection, n: int, baseline: int = 1, **overrides: Any) -> None:  # noqa: ANN401
    seq, previous = _head(c, schedule_governing_events, "governing_event_id")
    row: dict[str, Any] = {
        "governing_event_id": f"sgov_s62ggovn{n:04d}",
        "principal_id": P,
        "project_id": PRJ,
        "baseline_id": f"sbl_s62gbase{baseline:04d}",
        "seq": seq + 1,
        "previous_governing_event_id": previous,
        "recorded_at": func.clock_timestamp(),
        "reason": "Synthetic reason",
        **OPERATOR,
    }
    row.update(overrides)
    c.execute(insert(schedule_governing_events).values(**row))


def _approved_baseline(engine: Engine, n: int = 1, publication: str = W.complete) -> None:
    """A Baseline approved directly, committed."""
    with engine.begin() as c:
        c.execute(insert(schedule_baselines).values(**_baseline_row(n, publication)))
        _event(c, 100 + n, "approve", baseline=n, publication=publication)


def _proposed_baseline(engine: Engine, n: int = 1, publication: str = W.complete) -> None:
    with engine.begin() as c:
        c.execute(insert(schedule_baselines).values(**_baseline_row(n, publication)))
        _event(c, 100 + n, "propose", baseline=n, publication=publication)


def _scenario_with_version(engine: Engine, n: int = 1, **overrides: Any) -> None:  # noqa: ANN401
    with engine.begin() as c:
        c.execute(insert(schedule_scenarios).values(**_scenario_row(n, **overrides)))
        c.execute(insert(schedule_scenario_versions).values(**_version_row(n, scenario=n)))


def _intake_row(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    row: dict[str, Any] = {
        "principal_id": P,
        "project_id": PRJ,
        "series_id": W.intake,
        "publication_id": W.in_intake,
    }
    row.update(overrides)
    return row


def _decision_row(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    row: dict[str, Any] = {
        "decision_id": "ssmd_s62gdec00001",
        "principal_id": P,
        "project_id": PRJ,
        "intake_series_id": W.intake,
        "intake_publication_id": W.in_intake,
        "outcome": "needs_series",
        "threshold_version": "series-match-v1",
        "incoming_id_count": 3,
        "candidates": [],
    }
    row.update(overrides)
    return row


def _ledger_row(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    row: dict[str, Any] = {
        "principal_id": P,
        "capability": "schedule_scenarios.create",
        "idempotency_key": "s62-guard-key-0001",
        "request_digest": DIGEST,
        "decision_channel": "local_cli",
    }
    row.update(overrides)
    return row


def _refusal_row(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    row: dict[str, Any] = {
        "principal_id": P,
        "capability": "schedule_baselines.propose",
        "decision_channel": "remote_interactive",
        "asserting_client_id": "client-7",
        "error_code": "rate_limited",
    }
    row.update(overrides)
    return row


def _governing_row(**overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    row: dict[str, Any] = {
        "governing_event_id": "sgov_s62ggovn0001",
        "principal_id": P,
        "project_id": PRJ,
        "baseline_id": "sbl_s62gbase0001",
        "seq": 1,
        "recorded_at": func.now(),
        "reason": "Synthetic",
        **OPERATOR,
    }
    row.update(overrides)
    return row


def _event_row(action: str = "approve", **overrides: Any) -> dict[str, Any]:  # noqa: ANN401
    row: dict[str, Any] = {
        "event_id": "sbev_s62gevnt0001",
        "principal_id": P,
        "project_id": PRJ,
        "baseline_id": "sbl_s62gbase0001",
        "publication_id": W.complete,
        "action": action,
        "seq": 1,
        "recorded_at": func.now(),
        "reason": "Synthetic",
        **_event_fields(action),
    }
    if action == "approve":
        row["label"] = "BL-0"
    row.update(overrides)
    return row


#: One valid row per table, for replica-mode CHECK cases and the G1/G2 seeds.
BASE_ROWS: Final[dict[str, Callable[..., dict[str, Any]]]] = {
    "schedule_intake_series": _intake_row,
    "schedule_series_match_decisions": _decision_row,
    "schedule_baselines": _baseline_row,
    "schedule_baseline_events": _event_row,
    "schedule_governing_events": _governing_row,
    "schedule_scenarios": _scenario_row,
    "schedule_scenario_versions": _version_row,
    "schedule_cpm_runs": _run_row,
    "schedule_scenario_outputs": _output_row,
    "schedule_scenario_write_requests": _ledger_row,
    "schedule_scenario_write_refusals": _refusal_row,
}
TABLE_BY_NAME: Final = {table.name: table for table in PLANE_TABLES}


def _seed_row(engine: Engine, table: Table) -> None:
    """One valid row in `table`, triggers and foreign keys silenced."""
    with engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        values = BASE_ROWS[table.name]()
        if table is schedule_scenario_write_requests:
            values = {
                **values,
                "completed_at": func.now(),
                "result_kind": "scenario",
                "result_id": "sscn_s62gscen0001",
                "result_created": True,
                "result_bytes": 0,
            }
        c.execute(insert(table).values(**values))


# ---- G1 / G2: append-only and TRUNCATE --------------------------------------------------


@pytest.mark.parametrize("table", APPEND_ONLY, ids=lambda t: t.name)
def test_plane_table_is_append_only(engine: Engine, table: Table) -> None:
    _seed_row(engine, table)
    message = f"{table.name} is append-only"
    _refused(
        engine,
        lambda c: c.execute(text(f"UPDATE knowledge.{table.name} SET principal_id = principal_id")),  # noqa: S608
        RESTRICT_VIOLATION,
        message=message,
    )
    _refused(
        engine,
        lambda c: c.execute(text(f"DELETE FROM knowledge.{table.name}")),  # noqa: S608
        RESTRICT_VIOLATION,
        message=message,
    )


@pytest.mark.parametrize("table", PLANE_TABLES, ids=lambda t: t.name)
def test_plane_table_refuses_truncate_when_it_holds_rows(engine: Engine, table: Table) -> None:
    with engine.begin() as c:
        c.execute(text(f"TRUNCATE knowledge.{table.name} CASCADE"))
    _seed_row(engine, table)
    _refused(
        engine,
        lambda c: c.execute(text(f"TRUNCATE knowledge.{table.name} CASCADE")),
        RESTRICT_VIOLATION,
        message=f"{table.name} refuses TRUNCATE",
    )


# ---- G7 / G8: the ledger's one legal transition ------------------------------------------


def _complete(c: Connection, **overrides: Any) -> None:  # noqa: ANN401
    values: dict[str, Any] = {
        "completed_at": func.now(),
        "result_kind": "scenario",
        "result_id": "sscn_s62gscen0001",
        "result_created": True,
        "result_bytes": 10,
    }
    values.update(overrides)
    c.execute(
        schedule_scenario_write_requests.update()
        .where(schedule_scenario_write_requests.c.idempotency_key == "s62-guard-key-0001")
        .values(**values)
    )


def test_write_request_completes_once(engine: Engine) -> None:
    with engine.begin() as c:
        c.execute(insert(schedule_scenario_write_requests).values(**_ledger_row()))
        _complete(c)
    refusal = "a plane write request completes once"
    _refused(engine, lambda c: _complete(c), RESTRICT_VIOLATION, message=refusal)
    _refused(
        engine,
        lambda c: _complete(c, completed_at=None, result_kind=None, result_id=None),
        RESTRICT_VIOLATION,
        message=refusal,
    )
    _refused(
        engine,
        lambda c: c.execute(text("DELETE FROM knowledge.schedule_scenario_write_requests")),
        RESTRICT_VIOLATION,
        message="a plane write request is never deleted",
    )
    _refused(
        engine,
        _insert(
            schedule_scenario_write_requests,
            **_ledger_row(
                idempotency_key="s62-guard-key-0002",
                completed_at=func.now(),
                result_kind="scenario",
                result_id="sscn_s62gscen0001",
                result_created=True,
                result_bytes=0,
            ),
        ),
        RESTRICT_VIOLATION,
        message="a plane write request is reserved incomplete",
    )

    def change_identity(c: Connection) -> None:
        c.execute(
            insert(schedule_scenario_write_requests).values(
                **_ledger_row(idempotency_key="s62-guard-key-0003")
            )
        )
        c.execute(
            schedule_scenario_write_requests.update()
            .where(schedule_scenario_write_requests.c.idempotency_key == "s62-guard-key-0003")
            .values(
                completed_at=func.now(),
                result_kind="scenario",
                result_id="sscn_s62gscen0001",
                result_created=True,
                result_bytes=0,
                request_digest="f" * 64,
            )
        )

    _refused(
        engine,
        change_identity,
        RESTRICT_VIOLATION,
        message="a plane write request keeps its identity",
    )


def test_write_request_is_never_left_reserved(engine: Engine) -> None:
    _refused(
        engine,
        _insert(schedule_scenario_write_requests, **_ledger_row()),
        CHECK_VIOLATION,
        message="a reserved plane write request cannot commit",
    )
    with engine.connect() as c:
        assert (
            c.execute(
                select(func.count()).select_from(schedule_scenario_write_requests)
            ).scalar_one()
            == 0
        )


# ---- CHECKs (replica mode: only the CHECK can answer) -------------------------------------

_SNAPSHOT_NULLS: Final = dict.fromkeys(
    (
        "snapshot_activities",
        "snapshot_milestones",
        "snapshot_durations_quantized",
        "snapshot_durations_out_of_range",
        "snapshot_original_missing",
        "snapshot_remaining_missing",
    )
)

#: The provenance overrides each break `a_<t>_creator_is_known` alone.
_CREATOR_BREAKS: Final = (
    {**OPERATOR, "acceptance_basis": "client_identified"},
    {**OPERATOR, "decision_channel": "local_unattested"},
    {**OPERATOR, "asserting_client_id": "client-7"},
    {**CLIENT, "asserting_client_id": None},
)

#: `(base, constraint, overrides)`: one rule broken per case, every other CHECK
#: of the base row still satisfied (so the named one is the only answer).
CHECK_CASES: Final[tuple[tuple[str, str, dict[str, Any]], ...]] = (
    # Provenance (section 14.3), on every provenance table.
    *(
        (table, f"a_{short}_creator_is_known", overrides)
        for table, short in (
            ("schedule_scenarios", "scenario"),
            ("schedule_scenario_versions", "scenario_version"),
            ("schedule_cpm_runs", "cpm_run"),
            ("schedule_scenario_outputs", "scenario_output"),
            ("schedule_baseline_events:propose", "baseline_event"),
            ("schedule_governing_events", "governing_event"),
        )
        for overrides in _CREATOR_BREAKS
        # A governing event is operator-attested by its own CHECK too.
        if not (
            table == "schedule_governing_events"
            and overrides["authority_class"] != "local_operator"
        )
    ),
    (
        "schedule_scenarios",
        "a_scenario_client_is_bounded",
        {**CLIENT, "asserting_client_id": "c" * 257},
    ),
    # Origin whole (section 14.3.6).
    ("schedule_scenarios", "a_schedule_scenario_origin_is_whole", {"origin_publication_id": None}),
    (
        "schedule_scenarios",
        "a_schedule_scenario_origin_is_whole",
        {
            "origin_kind": "version",
            "origin_publication_id": None,
            "origin_baseline_id": "sbl_s62gbase0001",
            "origin_version_id": "sscv_s62gvers0009",
        },
    ),
    ("schedule_scenarios", "a_schedule_scenario_name_is_normalized", {"name": " padded"}),
    (
        "schedule_scenarios",
        "a_schedule_scenario_description_is_bounded",
        {"description": "d" * 2001},
    ),
    # Change set and snapshot (section 14.3.7).
    ("schedule_scenario_versions", "a_scenario_change_set_is_whole", {"change_set_zlib": b"y"}),
    (
        "schedule_scenario_versions:next",
        "a_scenario_change_set_is_whole",
        {"content_changed": None},
    ),
    (
        "schedule_scenario_versions",
        "a_scenario_snapshot_report_is_whole",
        {"snapshot_activities": None},
    ),
    (
        "schedule_scenario_versions:next",
        "a_scenario_snapshot_report_is_whole",
        dict.fromkeys(_SNAPSHOT_NULLS, 0),
    ),
    (
        "schedule_scenario_versions:next",
        "a_scenario_version_number_is_bounded",
        {"version_no": 501},
    ),
    (
        "schedule_scenario_versions",
        "a_scenario_version_has_a_parent_after_the_first",
        {"parent_version_id": "sscv_s62gvers0009"},
    ),
    ("schedule_scenario_versions", "a_scenario_version_label_is_known", {"label": "baseline"}),
    (
        "schedule_scenario_versions",
        "a_scenario_content_size_is_bounded",
        {"content_size_bytes": 33554433},
    ),
    (
        "schedule_scenario_versions",
        "a_scenario_content_digest_is_sha256",
        {"content_sha256": "X" * 64},
    ),
    (
        "schedule_scenario_versions:next",
        "a_scenario_change_set_size_is_bounded",
        {"change_set_size_bytes": 4194305},
    ),
    (
        "schedule_scenario_versions:next",
        "a_scenario_change_counts_are_bounded",
        {"ops_applied": 2},
    ),
    ("schedule_scenario_versions", "a_scenario_version_counts_are_bounded", {"calendar_count": 0}),
    (
        "schedule_scenario_versions",
        "a_scenario_version_counts_are_bounded",
        {"activity_count": 25001},
    ),
    (
        "schedule_scenario_versions",
        "a_scenario_snapshot_counts_are_not_negative",
        {"snapshot_milestones": -1},
    ),
    ("schedule_scenario_versions", "a_scenario_version_note_is_bounded", {"note": "n" * 2001}),
    # Runs and outputs (sections 14.3.8, 14.3.9).
    ("schedule_cpm_runs", "a_cpm_run_engine_version_is_known", {"engine_version": "my-pa-cpm-v0"}),
    (
        "schedule_cpm_runs",
        "a_cpm_run_status_is_known",
        {"status": "running", "project_finish": None},
    ),
    ("schedule_cpm_runs", "a_cpm_result_size_is_bounded", {"result_size_bytes": 67108865}),
    ("schedule_cpm_runs", "a_cpm_run_finish_is_an_instant", {"project_finish": "2026-06-01"}),
    ("schedule_cpm_runs", "a_rejected_cpm_run_has_no_finish", {"status": "rejected"}),
    ("schedule_cpm_runs", "a_cpm_run_counts_are_bounded", {"relationship_count": 100001}),
    ("schedule_scenario_outputs", "a_scenario_output_kind_is_known", {"kind": "tornado"}),
    ("schedule_scenario_outputs", "a_scenario_output_iterations_are_bounded", {"iterations": 0}),
    (
        "schedule_scenario_outputs",
        "a_scenario_output_size_is_bounded",
        {"payload_size_bytes": 1048577},
    ),
    # Match decisions (section 14.3.2).
    ("schedule_series_match_decisions", "a_series_match_outcome_is_known", {"outcome": "skipped"}),
    (
        "schedule_series_match_decisions",
        "an_ambiguous_match_states_one_reason",
        {"outcome": "ambiguous"},
    ),
    (
        "schedule_series_match_decisions",
        "an_ambiguous_match_states_one_reason",
        {"reason": "margin"},
    ),
    (
        "schedule_series_match_decisions",
        "a_series_match_reason_is_known",
        {"outcome": "ambiguous", "reason": "close"},
    ),
    (
        "schedule_series_match_decisions",
        "a_series_match_threshold_version_is_known",
        {"threshold_version": "series-match-v0"},
    ),
    (
        "schedule_series_match_decisions",
        "a_series_match_count_is_not_negative",
        {"incoming_id_count": -1},
    ),
    (
        "schedule_series_match_decisions",
        "a_series_match_candidates_are_bounded",
        {"candidates": [{"series_id": "sser_x"}] * 51},
    ),
    (
        "schedule_series_match_decisions",
        "a_series_match_refusal_is_known",
        {"outcome": "admission_refused", "admission_refusal": "nope"},
    ),
    (
        "schedule_series_match_decisions",
        "a_series_match_skip_is_known",
        {"outcome": "matched", "target_series_id": W.master, "admission_skipped": "busy"},
    ),
    (
        "schedule_series_match_decisions",
        "a_series_match_records_its_result",
        {"outcome": "matched"},
    ),
    (
        "schedule_series_match_decisions",
        "a_series_match_records_its_result",
        {"outcome": "admission_refused"},
    ),
    (
        "schedule_series_match_decisions",
        "a_series_match_records_its_result",
        {"target_series_id": W.master},
    ),
    (
        "schedule_series_match_decisions",
        "a_series_match_records_its_result",
        {"outcome": "created", "admission_skipped": "plane_disabled", "target_series_id": W.master},
    ),
    # Baselines and events (sections 14.3.3, 14.3.4).
    ("schedule_baselines", "a_schedule_baseline_type_is_known", {"type": "working"}),
    (
        "schedule_baseline_events",
        "a_schedule_baseline_event_seq_is_positive",
        {"seq": 0, "previous_event_id": "sbev_s62gevnt0009"},
    ),
    (
        "schedule_baseline_events",
        "a_schedule_baseline_event_chain_starts_once",
        {"previous_event_id": "sbev_s62gevnt0009"},
    ),
    ("schedule_baseline_events", "a_schedule_baseline_reason_is_bounded", {"reason": ""}),
    ("schedule_baseline_events", "a_schedule_baseline_label_is_well_formed", {"label": "BL-01"}),
    ("schedule_baseline_events", "a_schedule_baseline_event_type_is_known", {"type": "working"}),
    (
        "schedule_baseline_events",
        "a_schedule_approval_reference_is_bounded",
        {"approval_reference": "r" * 501},
    ),
    (
        "schedule_baseline_events",
        "a_schedule_baseline_does_not_supersede_itself",
        {"supersedes_baseline_id": "sbl_s62gbase0001"},
    ),
    (
        "schedule_baseline_events:propose",
        "a_schedule_proposal_ordinal_is_not_negative",
        {"proposal_ordinal": -1},
    ),
    ("schedule_baseline_events", "a_schedule_baseline_event_carries_its_fields", {"label": None}),
    (
        "schedule_baseline_events",
        "a_schedule_baseline_event_carries_its_fields",
        {"proposal_ordinal": 0},
    ),
    (
        "schedule_baseline_events:propose",
        "a_schedule_baseline_event_carries_its_fields",
        {"effective_from": "2026-06-01"},
    ),
    (
        "schedule_baseline_events",
        "a_schedule_baseline_decision_is_operator_attested",
        {**CLIENT},
    ),
    ("schedule_governing_events", "a_governing_event_is_operator_attested", {**CLIENT}),
    (
        "schedule_governing_events",
        "a_governing_event_seq_is_positive",
        {"seq": 0, "previous_governing_event_id": "sgov_s62ggovn0009"},
    ),
    ("schedule_governing_events", "a_governing_event_chain_starts_once", {"seq": 2}),
    ("schedule_governing_events", "a_governing_reason_is_bounded", {"reason": "r" * 2001}),
    # The intake marker (section 14.3.1).
    (
        "schedule_intake_series",
        "an_intake_new_series_name_is_whole",
        {"series_name_if_new": "New Series"},
    ),
    (
        "schedule_intake_series",
        "an_intake_new_series_name_is_normalized",
        {"series_name_if_new": "New  Series", "series_name_if_new_key": "new  series"},
    ),
    # The ledger and the refusal ledger (sections 14.3.10, 14.3.11).
    (
        "schedule_scenario_write_requests",
        "a_plane_write_request_capability_is_known",
        {"capability": "schedule_scenarios.list"},
    ),
    (
        "schedule_scenario_write_requests",
        "a_plane_write_request_key_is_bounded",
        {"idempotency_key": "short"},
    ),
    (
        "schedule_scenario_write_requests",
        "a_plane_write_request_client_is_whole",
        {"decision_channel": "remote_interactive"},
    ),
    (
        "schedule_scenario_write_requests",
        "a_plane_write_request_channel_is_known",
        {"decision_channel": "email"},
    ),
    (
        "schedule_scenario_write_requests",
        "an_incomplete_plane_write_request_names_no_result",
        {"result_bytes": 0},
    ),
    (
        "schedule_scenario_write_requests",
        "a_complete_plane_write_request_names_its_result",
        {
            "completed_at": func.now(),
            "result_kind": "version",
            "result_id": "sscv_s62gvers0001",
            "result_created": True,
            "result_bytes": 0,
        },
    ),
    (
        "schedule_scenario_write_requests",
        "a_plane_write_request_result_is_typed",
        {
            "completed_at": func.now(),
            "result_kind": "scenario",
            "result_id": "sscv_s62gvers0001",
            "result_created": True,
            "result_bytes": 0,
        },
    ),
    (
        "schedule_scenario_write_requests",
        "a_plane_write_request_bytes_are_not_negative",
        {
            "completed_at": func.now(),
            "result_kind": "scenario",
            "result_id": "sscn_s62gscen0001",
            "result_created": True,
            "result_bytes": -1,
        },
    ),
    (
        "schedule_scenario_write_refusals",
        "a_plane_refusal_capability_is_known",
        {"capability": "records.associations.assert"},
    ),
    ("schedule_scenario_write_refusals", "a_plane_refusal_code_is_public", {"error_code": "busy"}),
    (
        "schedule_scenario_write_refusals",
        "a_plane_refusal_client_is_whole",
        {"asserting_client_id": None},
    ),
    (
        "schedule_scenario_write_refusals",
        "a_plane_refusal_channel_is_known",
        {"decision_channel": "email", "asserting_client_id": None},
    ),
)

#: The base rows the CHECK cases start from.
CHECK_BASES: Final[dict[str, Callable[[], dict[str, Any]]]] = {
    **BASE_ROWS,
    "schedule_scenario_versions:next": lambda: _next_version_row(2, parent=1, version_no=2),
    "schedule_baseline_events:propose": lambda: _event_row("propose"),
}


@pytest.mark.parametrize(
    ("base", "name", "overrides"),
    CHECK_CASES,
    ids=[f"{name}-{i}" for i, (_, name, _) in enumerate(CHECK_CASES)],
)
def test_plane_check_refuses(
    engine: Engine, base: str, name: str, overrides: dict[str, Any]
) -> None:
    table = TABLE_BY_NAME[base.split(":")[0]]
    row = CHECK_BASES[base]()
    # The base row is valid with every CHECK applied: inserted, then rolled back.
    with engine.connect() as c:
        transaction = c.begin()
        c.execute(text("SET LOCAL session_replication_role = replica"))
        c.execute(insert(table).values(**row))
        transaction.rollback()
    _refused(
        engine, _insert(table, **{**row, **overrides}), CHECK_VIOLATION, names=name, replica=True
    )


def test_reference_role_is_retired(engine: Engine) -> None:
    """P47: the restated publication CHECKs refuse the retired role and kind."""
    for role, kind, name in (
        ("reference", None, "a_schedule_publication_role_is_known"),
        ("baseline", "working", "a_schedule_baseline_kind_is_known"),
    ):
        _refused(
            engine,
            lambda c, role=role, kind=kind: _seed_publication(
                c, "spub_s62gretired1", W.master, "queued", role=role, kind=kind
            ),
            CHECK_VIOLATION,
            names=name,
            replica=True,
        )
    with engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        _seed_publication(
            c, "spub_s62gapprov1", W.master, "queued", role="baseline", kind="approved_update"
        )


# ---- uniques -------------------------------------------------------------------------------


def test_plane_uniques_refuse_a_second_row(engine: Engine) -> None:
    for table, name, first, second in (
        (
            schedule_scenario_versions,
            "a_scenario_version_number_is_used_once",
            _version_row(1),
            _version_row(2),
        ),
        (schedule_cpm_runs, "a_cpm_run_is_computed_once", _run_row(1), _run_row(2)),
        (
            schedule_series_match_decisions,
            "an_intake_publication_is_decided_once",
            _decision_row(),
            _decision_row(decision_id="ssmd_s62gdec00002"),
        ),
        (
            schedule_intake_series,
            "an_intake_publication_is_marked_once",
            _intake_row(),
            _intake_row(series_id=W.other),
        ),
    ):
        with engine.begin() as c:
            c.execute(text("SET LOCAL session_replication_role = replica"))
            c.execute(insert(table).values(**first))
        _refused(engine, _insert(table, **second), UNIQUE_VIOLATION, names=name, replica=True)


#: Section 12.1: each backstop index alone; rows silenced so G12-G15 and the
#: foreign keys do not fire, with distinct `seq` values except in the `seq` cases.
BACKSTOPS: Final[tuple[tuple[str, Table, dict[str, Any], dict[str, Any]], ...]] = (
    (
        "a_schedule_baseline_is_decided_once",
        schedule_baseline_events,
        _event_row("approve"),
        _event_row(
            "reject", event_id="sbev_s62gevnt0002", seq=2, previous_event_id="sbev_s62gevnt0001"
        ),
    ),
    (
        "a_schedule_baseline_is_revoked_once",
        schedule_baseline_events,
        _event_row("revoke"),
        _event_row(
            "revoke", event_id="sbev_s62gevnt0002", seq=2, previous_event_id="sbev_s62gevnt0001"
        ),
    ),
    (
        "a_schedule_publication_is_approved_once",
        schedule_baseline_events,
        _event_row("approve"),
        _event_row(
            "approve",
            event_id="sbev_s62gevnt0002",
            seq=2,
            previous_event_id="sbev_s62gevnt0001",
            baseline_id="sbl_s62gbase0002",
            label="BL-1",
        ),
    ),
    (
        "a_schedule_baseline_label_is_used_once",
        schedule_baseline_events,
        _event_row("approve"),
        _event_row(
            "approve",
            event_id="sbev_s62gevnt0002",
            seq=2,
            previous_event_id="sbev_s62gevnt0001",
            baseline_id="sbl_s62gbase0002",
            publication_id=W.complete2,
        ),
    ),
    (
        "a_schedule_proposal_ordinal_is_used_once",
        schedule_baseline_events,
        _event_row("propose"),
        _event_row(
            "propose",
            event_id="sbev_s62gevnt0002",
            seq=2,
            previous_event_id="sbev_s62gevnt0001",
            baseline_id="sbl_s62gbase0002",
        ),
    ),
    (
        "a_schedule_baseline_event_seq_is_used_once",
        schedule_baseline_events,
        _event_row("propose"),
        _event_row(
            "propose",
            event_id="sbev_s62gevnt0002",
            baseline_id="sbl_s62gbase0002",
            publication_id=W.complete2,
        ),
    ),
    (
        "a_governing_event_seq_is_used_once",
        schedule_governing_events,
        _governing_row(),
        _governing_row(governing_event_id="sgov_s62ggovn0002"),
    ),
)


@pytest.mark.parametrize(
    ("name", "table", "first", "second"), BACKSTOPS, ids=[name for name, *_ in BACKSTOPS]
)
def test_baseline_backstop_index_refuses_alone(
    engine: Engine, name: str, table: Table, first: dict[str, Any], second: dict[str, Any]
) -> None:
    with engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        c.execute(insert(table).values(**first))
    _refused(engine, _insert(table, **second), UNIQUE_VIOLATION, names=name, replica=True)


# ---- foreign keys (user triggers disabled: only the key can answer) ----------------------


#: `(table, key, a row whose referenced parent exists under another binding)`.
FK_CASES: Final[tuple[tuple[Table, str, Callable[[], dict[str, Any]]], ...]] = (
    (
        schedule_intake_series,
        "an_intake_series_is_a_series_of_its_project",
        lambda: _intake_row(series_id=MISSING_SERIES, publication_id=ORPHAN),
    ),
    (
        schedule_intake_series,
        "an_intake_series_marks_its_publication",
        lambda: _intake_row(series_id=W.other),
    ),
    (
        schedule_series_match_decisions,
        "a_series_match_decides_an_intake_publication",
        lambda: _decision_row(),
    ),
    (
        schedule_series_match_decisions,
        "a_series_match_names_its_intake_publication",
        lambda: _decision_row(
            intake_series_id=W.master, intake_publication_id=W.complete3, project_id=PRJ2
        ),
    ),
    (
        schedule_series_match_decisions,
        "a_series_match_targets_a_series_of_its_project",
        lambda: _decision_row(
            intake_series_id=W.master,
            intake_publication_id=W.complete3,
            outcome="matched",
            admission_skipped="plane_disabled",
            target_series_id=W.elsewhere,
        ),
    ),
    (
        schedule_series_match_decisions,
        "a_series_match_names_a_publication_of_its_target",
        lambda: _decision_row(
            intake_series_id=W.master,
            intake_publication_id=W.complete3,
            outcome="already_present",
            target_series_id=W.other,
            resulting_publication_id=W.complete,
        ),
    ),
    (
        schedule_baselines,
        "a_schedule_baseline_names_a_publication_of_its_series",
        lambda: _baseline_row(5, series_id=W.other),
    ),
    (
        schedule_baseline_events,
        "a_schedule_baseline_event_names_its_baseline",
        lambda: _event_row(publication_id=W.complete2),
    ),
    (
        schedule_baseline_events,
        "a_schedule_baseline_event_follows_its_predecessor",
        lambda: _event_row(
            event_id="sbev_s62gevnt0002", seq=2, previous_event_id="sbev_s62gevnt0099"
        ),
    ),
    (
        schedule_baseline_events,
        "a_schedule_baseline_event_supersedes_a_baseline_of_its_project",
        lambda: _event_row(supersedes_baseline_id="sbl_s62gbase0002"),
    ),
    (
        schedule_governing_events,
        "a_governing_event_names_a_baseline_of_its_project",
        lambda: _governing_row(baseline_id="sbl_s62gbase0002"),
    ),
    (
        schedule_governing_events,
        "a_governing_event_follows_its_predecessor",
        lambda: _governing_row(
            governing_event_id="sgov_s62ggovn0002",
            seq=2,
            previous_governing_event_id="sgov_s62ggovn0099",
        ),
    ),
    (
        schedule_scenarios,
        "a_schedule_scenario_names_a_series_of_its_project",
        lambda: _scenario_row(5, series_id=MISSING_SERIES, origin_publication_id=ORPHAN),
    ),
    (
        schedule_scenarios,
        "a_schedule_scenario_starts_from_a_publication_of_its_series",
        lambda: _scenario_row(5, origin_publication_id=W.in_other),
    ),
    (
        schedule_scenarios,
        "a_schedule_scenario_starts_from_a_baseline_of_its_publication",
        lambda: _scenario_row(
            5, origin_publication_id=W.complete2, origin_baseline_id="sbl_s62gbase0001"
        ),
    ),
    (
        schedule_scenarios,
        "a_schedule_scenario_forks_a_version_of_its_series",
        lambda: _scenario_row(
            2,
            series_id=W.other,
            origin_kind="version",
            origin_publication_id=None,
            origin_version_id="sscv_s62gvers0001",
        ),
    ),
    (
        schedule_scenario_versions,
        "a_scenario_version_belongs_to_its_scenario",
        lambda: _version_row(5, scenario=5, series_id=W.other),
    ),
    (
        schedule_scenario_versions,
        "a_scenario_version_follows_its_parent",
        lambda: _next_version_row(2, parent=9, version_no=2),
    ),
    (
        schedule_cpm_runs,
        "a_cpm_run_computes_its_version_content",
        lambda: _run_row(input_content_sha256=OTHER_CONTENT),
    ),
    (
        schedule_scenario_outputs,
        "a_scenario_output_binds_its_version_content",
        lambda: _output_row(content_sha256=OTHER_CONTENT),
    ),
    (
        schedule_scenario_outputs,
        "a_scenario_output_names_a_run_of_its_version",
        lambda: _output_row(base_cpm_run_id="scpm_s62grun0002"),
    ),
)


def _fk_world(engine: Engine) -> None:
    """Parents for every FK case: a Baseline, events, a Scenario, a version, 2 runs."""
    with engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        c.execute(insert(schedule_baselines).values(**_baseline_row(1)))
        c.execute(
            insert(schedule_baselines).values(
                **_baseline_row(2, series_id=W.elsewhere, project_id=PRJ2)
            )
        )
        c.execute(insert(schedule_scenarios).values(**_scenario_row(1)))
        c.execute(insert(schedule_scenario_versions).values(**_version_row(1)))
        c.execute(insert(schedule_scenarios).values(**_scenario_row(3)))
        c.execute(
            insert(schedule_scenario_versions).values(**_version_row(3, scenario=3, version_no=1))
        )
        c.execute(insert(schedule_cpm_runs).values(**_run_row(2, version_id="sscv_s62gvers0003")))
        c.execute(
            insert(schedule_intake_series).values(
                **_intake_row(series_id=W.master, publication_id=W.complete3)
            )
        )
        # A publication whose Series row is absent: only a Series key can refuse.
        _seed_publication(c, ORPHAN, MISSING_SERIES, "complete")


@pytest.mark.parametrize(("table", "name", "row"), FK_CASES, ids=[name for _, name, _ in FK_CASES])
def test_plane_fk_refuses_a_cross_binding(
    engine: Engine, table: Table, name: str, row: Callable[[], dict[str, Any]]
) -> None:
    _fk_world(engine)
    _refused(
        engine,
        _insert(table, **row()),
        FOREIGN_KEY_VIOLATION,
        names=name,
        disable=table,
    )
    with engine.connect() as c:
        delete_rule = c.execute(
            text("SELECT confdeltype FROM pg_constraint WHERE conname = :n AND contype = 'f'"),
            {"n": name},
        ).scalar_one()
    assert delete_rule == "r", name


# ---- G3 / G4: Scenario origins and first versions -------------------------------------------


@pytest.mark.parametrize(
    ("case", "overrides", "message"),
    [
        ("queued", {"origin_publication_id": W.queued}, "starts from an eligible publication"),
        ("failed", {"origin_publication_id": W.failed}, "starts from an eligible publication"),
        ("review", {"origin_publication_id": W.review}, "starts from an eligible publication"),
        (
            "intake",
            {"series_id": W.intake, "origin_publication_id": W.in_intake},
            "never starts from an intake series",
        ),
        (
            "proposed_baseline",
            {"origin_publication_id": W.complete2, "origin_baseline_id": "sbl_s62gbase0002"},
            "starts from an approved baseline",
        ),
        (
            "revoked_baseline",
            {"origin_baseline_id": "sbl_s62gbase0001"},
            "starts from an approved baseline",
        ),
    ],
)
def test_scenario_origin_must_be_eligible_and_not_intake(
    engine: Engine, case: str, overrides: dict[str, Any], message: str
) -> None:
    _approved_baseline(engine, 1)
    with engine.begin() as c:
        _event(c, 200, "revoke", baseline=1)
    _proposed_baseline(engine, 2, publication=W.complete2)
    with engine.begin() as c:
        c.execute(insert(schedule_intake_series).values(**_intake_row()))
    del case
    _refused(
        engine,
        lambda c: _scenario_and_version(c, overrides),
        RESTRICT_VIOLATION,
        message=f"a schedule scenario {message}",
    )


def _scenario_and_version(c: Connection, overrides: dict[str, Any]) -> None:
    scenario = _scenario_row(**overrides)
    c.execute(insert(schedule_scenarios).values(**scenario))
    c.execute(
        insert(schedule_scenario_versions).values(**_version_row(series_id=scenario["series_id"]))
    )


def test_scenario_origins_that_are_admitted(engine: Engine) -> None:
    _approved_baseline(engine, 1)
    with engine.begin() as c:
        _scenario_and_version(c, {})
        c.execute(
            insert(schedule_scenarios).values(**_scenario_row(2, origin_publication_id=W.partial))
        )
        c.execute(insert(schedule_scenario_versions).values(**_version_row(2, scenario=2)))
        c.execute(
            insert(schedule_scenarios).values(
                **_scenario_row(3, origin_baseline_id="sbl_s62gbase0001")
            )
        )
        c.execute(insert(schedule_scenario_versions).values(**_version_row(3, scenario=3)))


def test_a_scenario_without_a_first_version_fails_at_commit(engine: Engine) -> None:
    _refused(
        engine,
        _insert(schedule_scenarios, **_scenario_row()),
        CHECK_VIOLATION,
        message="a schedule scenario has its first version",
    )


# ---- G5: the version chain --------------------------------------------------------------------


def _fork(**overrides: Any) -> Callable[[Connection], None]:  # noqa: ANN401
    def act(c: Connection) -> None:
        c.execute(
            insert(schedule_scenarios).values(
                **_scenario_row(
                    7,
                    origin_kind="version",
                    origin_publication_id=None,
                    origin_version_id="sscv_s62gvers0001",
                )
            )
        )
        c.execute(
            insert(schedule_scenario_versions).values(
                **_version_row(7, scenario=7, **{**_SNAPSHOT_NULLS, **overrides})
            )
        )

    return act


@pytest.mark.parametrize(
    ("rule", "act", "message"),
    [
        (
            "byte_copy",
            _fork(content_sha256=OTHER_CONTENT),
            "a forked scenario version copies its source",
        ),
        (
            "byte_copy_size",
            _fork(content_size_bytes=2),
            "a forked scenario version copies its source",
        ),
        (
            "byte_copy_spec",
            _fork(distribution_spec_sha256=DIGEST),
            "a forked scenario version copies its source",
        ),
        (
            "snapshot",
            _fork(**{"snapshot_activities": 0, **dict.fromkeys(list(_SNAPSHOT_NULLS)[1:], 0)}),
            "snapshot is reported exactly from a publication",
        ),
        (
            "linear",
            lambda c: c.execute(
                insert(schedule_scenario_versions).values(
                    **_next_version_row(3, parent=1, version_no=2)
                )
            ),
            "a scenario version extends its head",
        ),
    ],
)
def test_scenario_version_chain_rules(
    engine: Engine, rule: str, act: Callable[[Connection], object], message: str
) -> None:
    _scenario_with_version(engine, 1)
    if rule == "linear":
        with engine.begin() as c:
            c.execute(
                insert(schedule_scenario_versions).values(
                    **_next_version_row(2, parent=1, version_no=2)
                )
            )
    _refused(engine, act, RESTRICT_VIOLATION, message=message)


def test_scenario_version_chain_admits_a_fork_and_an_extension(engine: Engine) -> None:
    _scenario_with_version(engine, 1)
    with engine.begin() as c:
        c.execute(
            insert(schedule_scenario_versions).values(
                **_next_version_row(2, parent=1, version_no=2)
            )
        )
        c.execute(
            insert(schedule_scenario_versions).values(
                **_next_version_row(3, parent=2, version_no=3)
            )
        )
    with engine.begin() as c:
        _fork()(c)


# ---- G6: outputs ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "overrides", "message"),
    [
        ("computed_run", {"base_cpm_run_id": "scpm_s62grun0002"}, "names a computed run"),
        ("digest", {"distribution_spec_sha256": DIGEST}, "binds its version distributions"),
    ],
)
def test_output_binds_a_computed_run_and_its_distributions(
    engine: Engine, rule: str, overrides: dict[str, Any], message: str
) -> None:
    del rule
    _scenario_with_version(engine, 1)
    with engine.begin() as c:
        c.execute(insert(schedule_cpm_runs).values(**_run_row(1)))
        c.execute(
            insert(schedule_cpm_runs).values(
                **_run_row(2, engine_version="my-pa-cpm-v2", status="rejected", project_finish=None)
            )
        )
        c.execute(
            insert(schedule_scenario_outputs).values(
                **_output_row(1, base_cpm_run_id="scpm_s62grun0001")
            )
        )
    _refused(
        engine,
        _insert(schedule_scenario_outputs, **_output_row(2, **overrides)),
        RESTRICT_VIOLATION,
        message=f"a scenario output {message}",
    )


# ---- G9 / G10 / G11: intake and match decisions ----------------------------------------------


def test_intake_series_admits_no_other_publication(engine: Engine) -> None:
    with engine.begin() as c:
        c.execute(insert(schedule_intake_series).values(**_intake_row()))
    # G10: no second publication joins a marked intake Series.
    _refused(
        engine,
        lambda c: _seed_publication(c, "spub_s62gintak09", W.intake, "queued"),
        RESTRICT_VIOLATION,
        message="an intake series admits no other publication",
    )
    # G9: a Series holding another publication cannot be marked.
    _refused(
        engine,
        _insert(
            schedule_intake_series, **_intake_row(series_id=W.master, publication_id=W.complete)
        ),
        RESTRICT_VIOLATION,
        message="an intake series holds only its publication",
    )
    # G9: the intake Series is named for its request.
    with engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        _seed_series(c, "sser_s62gintake2", P, PRJ, "Schedule intake 999999999999")
        _seed_publication(c, "spub_s62gintak03", "sser_s62gintake2", "complete")
        _seed_series(c, "sser_s62gintake3", P, PRJ, INTAKE_NAME + " b")
        _seed_publication(
            c, "spub_s62gintak04", "sser_s62gintake3", "complete", role="baseline", kind="contract"
        )
    _refused(
        engine,
        _insert(
            schedule_intake_series,
            **_intake_row(series_id="sser_s62gintake2", publication_id="spub_s62gintak03"),
        ),
        RESTRICT_VIOLATION,
        message="an intake series is named for its request",
    )
    # G9: an intake publication is a plain update.
    _refused(
        engine,
        _insert(
            schedule_intake_series,
            **_intake_row(series_id="sser_s62gintake3", publication_id="spub_s62gintak04"),
        ),
        RESTRICT_VIOLATION,
        message="an intake publication is a plain update",
    )


@pytest.mark.parametrize(
    ("case", "overrides", "message"),
    [
        (
            "matched_for_failed",
            {
                "intake_publication_id": "spub_s62gintak02",
                "outcome": "matched",
                "target_series_id": W.master,
                "resulting_publication_id": W.complete,
            },
            "is not eligible exactly when its intake is not",
        ),
        (
            "not_eligible_for_complete",
            {"outcome": "not_eligible"},
            "is not eligible exactly when its intake is not",
        ),
        (
            "non_terminal",
            {"intake_publication_id": "spub_s62gintak05", "outcome": "not_eligible"},
            "decides a terminal intake publication",
        ),
        (
            "target_is_intake",
            {
                "outcome": "already_present",
                "target_series_id": "sser_s62gintake6",
                "resulting_publication_id": "spub_s62gintak06",
            },
            "never targets an intake series",
        ),
    ],
)
def test_match_decision_follows_its_intake(
    engine: Engine, case: str, overrides: dict[str, Any], message: str
) -> None:
    del case
    with engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        for series, publication, status in (
            ("sser_s62gintake2", "spub_s62gintak02", "failed"),
            ("sser_s62gintake5", "spub_s62gintak05", "processing"),
            ("sser_s62gintake6", "spub_s62gintak06", "complete"),
        ):
            _seed_series(c, series, P, PRJ, "Schedule intake " + series[-12:])
            if status == "processing":
                _seed_publication(c, publication, series, "queued")
                c.execute(
                    text(
                        "UPDATE knowledge.schedule_publications SET status = 'processing', "
                        "processing_started_at = now() WHERE publication_id = :p"
                    ),
                    {"p": publication},
                )
            else:
                _seed_publication(c, publication, series, status)
            c.execute(
                insert(schedule_intake_series).values(
                    **_intake_row(series_id=series, publication_id=publication)
                )
            )
        c.execute(insert(schedule_intake_series).values(**_intake_row()))
    row = _decision_row(**overrides)
    if row["intake_publication_id"] != W.in_intake:
        row["intake_series_id"] = "sser_s62gintake" + row["intake_publication_id"][-1]
    _refused(
        engine,
        _insert(schedule_series_match_decisions, **row),
        RESTRICT_VIOLATION,
        message=f"a series match {message}",
    )


# ---- G12 / G13: Baselines -----------------------------------------------------------------------


def test_a_revoked_publication_is_not_reapproved(engine: Engine) -> None:
    _approved_baseline(engine, 1)
    with engine.begin() as c:
        _event(c, 200, "revoke", baseline=1)

    def again(c: Connection) -> None:
        c.execute(insert(schedule_baselines).values(**_baseline_row(2)))
        _event(c, 201, "propose", baseline=2)

    _refused(
        engine,
        again,
        RESTRICT_VIOLATION,
        message="an approved schedule publication is never baselined again",
    )

    with engine.begin() as c:
        c.execute(insert(schedule_intake_series).values(**_intake_row()))

    def intake(c: Connection) -> None:
        c.execute(
            insert(schedule_baselines).values(
                **_baseline_row(3, publication=W.in_intake, series_id=W.intake)
            )
        )
        _event(c, 202, "propose", baseline=3, publication=W.in_intake)

    _refused(
        engine,
        intake,
        RESTRICT_VIOLATION,
        message="a schedule baseline never names an intake publication",
    )


def test_a_baseline_without_a_first_event_fails_at_commit(engine: Engine) -> None:
    _refused(
        engine,
        _insert(schedule_baselines, **_baseline_row()),
        CHECK_VIOLATION,
        message="a schedule baseline has its first event",
    )


# ---- G14: the Baseline event chain ------------------------------------------------------------


def _chain_case(
    rule: str,
) -> tuple[Callable[[Engine], None], Callable[[Connection], None], str, str]:
    """`(arrange, act, sqlstate, message)` for one G14 rule."""

    def nothing(engine: Engine) -> None:
        del engine

    def proposed(engine: Engine) -> None:
        _proposed_baseline(engine, 1)

    def approved(engine: Engine) -> None:
        _approved_baseline(engine, 1)

    if rule == "chain":
        return (
            proposed,
            lambda c: _event(c, 2, "withdraw", seq=5),
            RESTRICT_VIOLATION,
            "a schedule baseline event extends its project chain",
        )
    if rule == "chain_predecessor":
        return (
            proposed,
            lambda c: _event(c, 2, "withdraw", previous_event_id=None, seq=1),
            RESTRICT_VIOLATION,
            "a schedule baseline event extends its project chain",
        )
    if rule == "order":
        return (
            proposed,
            lambda c: _event(c, 2, "withdraw", recorded_at=text("now() - interval '1 day'")),
            CHECK_VIOLATION,
            "a schedule baseline event is recorded in order",
        )
    if rule == "lifecycle":
        return (
            approved,
            lambda c: _event(c, 2, "reject"),
            RESTRICT_VIOLATION,
            "a schedule baseline decision follows a pending proposal",
        )
    if rule == "lifecycle_revoke":
        return (
            proposed,
            lambda c: _event(c, 2, "revoke"),
            RESTRICT_VIOLATION,
            "a schedule baseline is revoked once after its approval",
        )
    if rule == "lifecycle_governing":

        def governing(engine: Engine) -> None:
            _approved_baseline(engine, 1)
            with engine.begin() as c:
                _governing(c, 1)

        return (
            governing,
            lambda c: _event(c, 2, "revoke"),
            RESTRICT_VIOLATION,
            "the governing schedule baseline is not revoked",
        )
    if rule == "eligibility":

        def act(c: Connection) -> None:
            c.execute(insert(schedule_baselines).values(**_baseline_row(1, publication=W.failed)))
            _event(c, 1, "propose", baseline=1, publication=W.failed)

        return nothing, act, RESTRICT_VIOLATION, "a schedule baseline names an eligible publication"
    if rule == "label":

        def act(c: Connection) -> None:
            c.execute(
                insert(schedule_baselines).values(**_baseline_row(2, publication=W.complete2))
            )
            _event(c, 2, "approve", baseline=2, publication=W.complete2, label="BL-0")

        return (
            approved,
            act,
            RESTRICT_VIOLATION,
            "a schedule baseline label is the next approval ordinal",
        )
    if rule == "ordinal":

        def act(c: Connection) -> None:
            c.execute(insert(schedule_baselines).values(**_baseline_row(1)))
            _event(c, 1, "propose", baseline=1, proposal_ordinal=1)

        return (
            nothing,
            act,
            RESTRICT_VIOLATION,
            "a schedule proposal ordinal counts the decided proposals",
        )
    if rule == "supersedes":

        def act(c: Connection) -> None:
            c.execute(
                insert(schedule_baselines).values(**_baseline_row(2, publication=W.complete2))
            )
            _event(
                c,
                2,
                "approve",
                baseline=2,
                publication=W.complete2,
                supersedes_baseline_id="sbl_s62gbase0001",
            )

        return (
            proposed,
            act,
            RESTRICT_VIOLATION,
            "a schedule baseline supersedes an approved baseline",
        )
    raise AssertionError(rule)


G14_RULES: Final = (
    "chain",
    "chain_predecessor",
    "order",
    "lifecycle",
    "lifecycle_revoke",
    "lifecycle_governing",
    "eligibility",
    "label",
    "ordinal",
    "supersedes",
)


@pytest.mark.parametrize("rule", G14_RULES)
def test_baseline_event_chain_rules(engine: Engine, rule: str) -> None:
    arrange, act, sqlstate, message = _chain_case(rule)
    arrange(engine)
    _refused(engine, act, sqlstate, message=message)


def test_baseline_lifecycle_admits_every_legal_step(engine: Engine) -> None:
    """Propose, adopt by approval, govern, supersede, revoke a non-governing one."""
    _proposed_baseline(engine, 1)
    with engine.begin() as c:
        _event(c, 2, "approve", baseline=1)
        _governing(c, 1)
    with engine.begin() as c:
        c.execute(insert(schedule_baselines).values(**_baseline_row(2, publication=W.complete2)))
        _event(
            c,
            3,
            "approve",
            baseline=2,
            publication=W.complete2,
            supersedes_baseline_id="sbl_s62gbase0001",
        )
        _governing(c, 2, baseline=2)
    with engine.begin() as c:
        _event(c, 4, "revoke", baseline=1)
    with engine.begin() as c:
        c.execute(insert(schedule_baselines).values(**_baseline_row(3, publication=W.partial)))
        _event(c, 5, "propose", baseline=3, publication=W.partial)
    with engine.begin() as c:
        _event(c, 6, "withdraw", baseline=3, publication=W.partial)
    with engine.begin() as c:
        c.execute(insert(schedule_baselines).values(**_baseline_row(4, publication=W.partial)))
        _event(c, 7, "propose", baseline=4, publication=W.partial, proposal_ordinal=1)
        _event(c, 8, "reject", baseline=4, publication=W.partial)


def test_import_approval_needs_a_publication_of_this_transaction(engine: Engine) -> None:
    """G14 (d): `approved_at_import` needs a queued publication admitted in this transaction."""

    def approve_at_import(publication: str) -> Callable[[Connection], None]:
        def act(c: Connection) -> None:
            c.execute(
                insert(schedule_baselines).values(**_baseline_row(1, publication=publication))
            )
            _event(c, 1, "approve", baseline=1, publication=publication, approved_at_import=True)

        return act

    # A queued publication admitted by an earlier transaction.
    _refused(
        engine,
        approve_at_import(W.queued),
        RESTRICT_VIOLATION,
        message="an import-time approval names a publication of its admission",
    )
    # A complete publication.
    _refused(
        engine,
        approve_at_import(W.complete),
        RESTRICT_VIOLATION,
        message="an import-time approval names a publication of its admission",
    )

    # Admitted in this very transaction: accepted.
    def admit_and_approve(c: Connection) -> None:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        _seed_publication(
            c, "spub_s62gnewpub1", W.master, "queued", role="baseline", kind="contract"
        )
        c.execute(text("SET LOCAL session_replication_role = origin"))
        approve_at_import("spub_s62gnewpub1")(c)

    with engine.begin() as c:
        admit_and_approve(c)


# ---- G15: the governing chain -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rule", "arrange", "overrides", "sqlstate", "message"),
    [
        (
            "chain",
            "approved",
            {"seq": 3},
            RESTRICT_VIOLATION,
            "a governing event extends its project chain",
        ),
        (
            "order",
            "governed",
            {"recorded_at": text("now() - interval '1 day'")},
            CHECK_VIOLATION,
            "a governing event is recorded in order",
        ),
        ("eligibility", "proposed", {}, RESTRICT_VIOLATION, "approved, unrevoked and eligible"),
    ],
)
def test_governing_event_chain_rules(
    engine: Engine, rule: str, arrange: str, overrides: dict[str, Any], sqlstate: str, message: str
) -> None:
    del rule
    if arrange == "proposed":
        _proposed_baseline(engine, 1)
    else:
        _approved_baseline(engine, 1)
    if arrange == "governed":
        with engine.begin() as c:
            _governing(c, 1)
    _refused(engine, lambda c: _governing(c, 2, **overrides), sqlstate, message=message)


def test_governing_refuses_a_revoked_or_ineligible_baseline(engine: Engine) -> None:
    _approved_baseline(engine, 1)
    with engine.begin() as c:
        _event(c, 2, "revoke", baseline=1)
    _refused(
        engine,
        lambda c: _governing(c, 1),
        RESTRICT_VIOLATION,
        message="approved, unrevoked and eligible",
    )


# ---- R9-F06: Principal-qualified subject lookups ------------------------------------------------


@pytest.mark.parametrize(
    "case", ["scenario_origin", "baseline_publication", "baseline_event_subject"]
)
def test_a_foreign_principal_subject_is_a_foreign_key_violation(engine: Engine, case: str) -> None:
    """Another Principal's subject decides nothing: the FK answers `23503`, never `23001`."""
    if case == "scenario_origin":

        def act(c: Connection) -> None:
            _scenario_and_version(c, {"origin_publication_id": W.q_publication})

    elif case == "baseline_publication":

        def act(c: Connection) -> None:
            c.execute(
                insert(schedule_baselines).values(**_baseline_row(1, publication=W.q_publication))
            )
            _event(c, 1, "propose", baseline=1, publication=W.q_publication)

    else:
        # Q's Baseline exists; P's event names it.
        with engine.begin() as c:
            c.execute(text("SET LOCAL session_replication_role = replica"))
            c.execute(
                insert(schedule_baselines).values(
                    **_baseline_row(
                        9,
                        publication=W.q_publication,
                        principal_id=Q,
                        project_id=QPRJ,
                        series_id=W.q_series,
                    )
                )
            )

        def act(c: Connection) -> None:
            _event(c, 1, "withdraw", baseline=9, publication=W.q_publication)

    _refused(engine, act, FOREIGN_KEY_VIOLATION)
