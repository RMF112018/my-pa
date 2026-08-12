"""WP-11's six controls, against a live PostgreSQL server.

The `database` tier. Everything here runs on a disposable database created and
dropped by its own fixture, migrated to head, and never the configured one.

What each section proves, and at what level, stated so the level cannot be
over-read later:

* **Control 1 — principal scope.** Two synthetic Principals, at the
  repository/query boundary, for every object type WP-11 adds and for the Pulse.
  B's read of A's object is answered *identically to absent* — `None`, an empty
  tuple, or `UnknownScopeError`, never an error that discloses existence — and
  every negative carries a non-zero control in the same test so it cannot pass
  against an empty table. **This is not an end-to-end two-identity proof**, and
  none is constructible at this head: `D-15` pins the web tier to exactly one
  Principal under `local_operator`, so no second browser session exists to drive.
* **Control 2 — accepted-only.** A proposal is invisible to every continuity
  read and to the Pulse derivation, and the only path to `accepted` requires a
  review decision *in the caller's own partition* whose disposition accepted
  something. A rejection, another Principal's decision, and an identifier naming
  nothing are all refused identically.
* **Control 3 — no automatic promotion.** A Pulse read is asserted to write
  nothing: every continuity table is counted before and after and every
  `evidence_state` re-read.
* **Control 4 — lifecycle and closure evidence.** A close writes its evidence in
  the same transaction, and the server refuses a `closed` lifecycle row with no
  evidence reference.
* **Control 5 — associations reconstructable.** Given an object and a Principal,
  the `associated` rows name the context and the evidence that justified it.
* **Control 6 — the Pulse basis.** The server refuses a Pulse row with an empty
  `basis_refs`, so an item with no evidentiary basis is unstorable rather than
  merely undesirable.

Every identifier, name, and sentence here is synthetic. No real person, path,
tenant, or credential appears; the counterparty is "Sample Counterparty".
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import Connection, make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.situation.continuity import (
    ClosureEvidenceKind,
    CommitmentDirection,
    ContinuityEvidenceState,
    ContinuityObjectKind,
    LifecycleTransition,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.situation_repository import (
    SqlContinuityRepository,
    SqlProjectRepository,
    SqlPulseRepository,
    SqlSituationRepository,
)

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
DISPOSABLE_DATABASE: Final = "my_pa_continuity_isolation_test"

#: The two synthetic Principals every isolation suite in this repository uses.
#: A writes; B is the Principal whose every read must come back as absence.
PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

COUNTERPARTY: Final = "per_counterparty0001aaaa"
ORIGIN: Final = "cap_origin0001origin0001"

NOW: Final = datetime(2026, 8, 10, 12, tzinfo=UTC)

#: Every table WP-11's write path can touch. Counted before and after a Pulse
#: read, which is how "the derivation writes nothing" is measured rather than
#: asserted.
CONTINUITY_TABLES: Final = (
    "commitments",
    "decisions",
    "tasks",
    "continuity_lifecycle_events",
    "pulse_items",
    "situations",
    "projects",
    "project_situations",
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[arg-type]

    try:
        _administer(drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
        yield url
    finally:
        _administer(drop)
        maintenance.dispose()


@pytest.fixture
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    """The disposable database, upgraded to head and disposed afterwards."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


def _stage_review_decision(
    connection: Connection, *, principal_id: str, disposition: str, suffix: str
) -> str:
    """Insert the minimum capture-plane chain under one review decision.

    Written out in raw SQL rather than driven through the capture service,
    because what this suite needs from the review plane is one row with a
    Principal and a disposition — and building it by hand keeps the acceptance
    gate's test independent of the writer that normally fills those tables.
    Every value is synthetic.
    """
    capture_id = f"cap_stage{suffix}stage{suffix}"
    version_id = f"capver_stage{suffix}stage{suffix}"
    proposal_id = f"prop_stage{suffix}stage{suffix}"
    review_case_id = f"rvw_stage{suffix}stage{suffix}"
    decision_id = f"rdec_stage{suffix}stage{suffix}"
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.captures (capture_id, owner_principal_id, created_at) "  # noqa: S608
            "VALUES (:capture_id, :principal_id, now())"
        ),
        {"capture_id": capture_id, "principal_id": principal_id},
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_versions (version_id, capture_id, version_number, "  # noqa: S608
            "content, content_sha256, owner_principal_id, classification, processing_policy, "
            "idempotency_key, correlation_id, audit_id, server_received_at, accepted_at, "
            "recorded_at) VALUES (:version_id, :capture_id, 1, 'a synthetic note', "
            ":digest, :principal_id, 'synthetic_test', 'local_only', :key, :correlation, "
            ":audit, now(), now(), now())"
        ),
        {
            "version_id": version_id,
            "capture_id": capture_id,
            "digest": "0" * 64,
            "principal_id": principal_id,
            "key": f"stage-{suffix}",
            "correlation": f"corr_stage{suffix}stage{suffix}",
            "audit": f"audit_stage{suffix}stage{suffix}",
        },
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_proposals (proposal_id, version_id, proposal_type, "  # noqa: S608
            "state, risk_class, method, method_version, schema_version, missing_required_fields) "
            "VALUES (:proposal_id, :version_id, 'commitment', 'needs_review', 'high', "
            "'deterministic_rule', 'v1', 'v1', '{}')"
        ),
        {"proposal_id": proposal_id, "version_id": version_id},
    )
    # The deferred trigger `a_proposal_cites_a_span` refuses a proposal with no
    # span, which is the review plane's own rule and is left alone here: the
    # fixture satisfies it rather than working round it.
    span_id = f"span_stage{suffix}stage{suffix}"
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_spans (span_id, version_id, start_offset, "  # noqa: S608
            "end_offset, offset_basis, line_start, column_start, line_end, column_end, "
            "quoted_text_sha256, span_role) VALUES (:span_id, :version_id, 0, 4, "
            "'unicode_code_point_v1', 1, 1, 1, 5, :digest, 'direct')"
        ),
        {"span_id": span_id, "version_id": version_id, "digest": "1" * 64},
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_proposal_spans (proposal_id, span_id) "  # noqa: S608
            "VALUES (:proposal_id, :span_id)"
        ),
        {"proposal_id": proposal_id, "span_id": span_id},
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_review_cases (review_case_id, proposal_id, "  # noqa: S608
            "capture_id, version_id, principal_id, opened_at) VALUES (:review_case_id, "
            ":proposal_id, :capture_id, :version_id, :principal_id, now())"
        ),
        {
            "review_case_id": review_case_id,
            "proposal_id": proposal_id,
            "capture_id": capture_id,
            "version_id": version_id,
            "principal_id": principal_id,
        },
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_review_decisions (decision_id, review_case_id, "  # noqa: S608
            "sequence, disposition, principal_id, correlation_id, audit_id, decided_at) "
            "VALUES (:decision_id, :review_case_id, 1, :disposition, :principal_id, "
            ":correlation, :audit, now())"
        ),
        {
            "decision_id": decision_id,
            "review_case_id": review_case_id,
            "disposition": disposition,
            "principal_id": principal_id,
            "correlation": f"corr_dec{suffix}dec{suffix}xx",
            "audit": f"audit_dec{suffix}dec{suffix}xx",
        },
    )
    return decision_id


def _propose_commitment(
    connection: Connection, *, principal_id: str, due_at: datetime | None = None
) -> str:
    repository = SqlContinuityRepository(connection)
    commitment = repository.propose_commitment(
        principal_id=principal_id,
        counterparty_person_id=COUNTERPARTY,
        direction=CommitmentDirection.OWED_BY_PRINCIPAL,
        summary="Send Sample Counterparty the revised figure",
        origin_evidence_ref=ORIGIN,
        origin_evidence_kind=ClosureEvidenceKind.CAPTURE,
        due_at=due_at,
    )
    return commitment.commitment_id


def _row_counts(connection: Connection) -> dict[str, int]:
    return {
        table: connection.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.{table}")  # noqa: S608 - module constants
        ).scalar_one()
        for table in CONTINUITY_TABLES
    }


# --- Control 1: every continuity object is principal-scoped -----------------


def test_a_commitment_of_a_is_answered_to_b_exactly_as_an_absent_one(
    migrated_engine: Engine,
) -> None:
    """Getter, listing, close, accept and associate, all answered as absence.

    The non-zero control is in the same test: A's own reads return the row, so
    B's empty answers are a partition rather than an empty table.
    """
    with migrated_engine.begin() as connection:
        commitment_id = _propose_commitment(connection, principal_id=PRINCIPAL_A)
        repository = SqlContinuityRepository(connection)

        # Non-zero control.
        assert repository.get_commitment(PRINCIPAL_A, commitment_id) is not None
        assert len(repository.list_commitments(PRINCIPAL_A)) == 1

        # B: identical to absent.
        assert repository.get_commitment(PRINCIPAL_B, commitment_id) is None
        assert repository.list_commitments(PRINCIPAL_B) == ()
        assert repository.lifecycle_events(PRINCIPAL_B, commitment_id) == ()
        assert repository.association_evidence(PRINCIPAL_B, commitment_id) == ()

        # And an absent identifier of the same shape is answered the same way, so
        # the refusal cannot be used to discover that A's commitment exists.
        absent = "cmt_absent0001absent0001"
        assert repository.get_commitment(PRINCIPAL_B, absent) is None

        for object_id in (commitment_id, absent):
            with pytest.raises(UnknownScopeError):
                repository.close(
                    principal_id=PRINCIPAL_B,
                    object_kind=ContinuityObjectKind.COMMITMENT,
                    object_id=object_id,
                    evidence_kind=ClosureEvidenceKind.PRINCIPAL_STATEMENT,
                    evidence_ref="rdec_forced0001forced0001",
                    occurred_at=NOW,
                )
            with pytest.raises(UnknownScopeError):
                repository.accept(
                    principal_id=PRINCIPAL_B,
                    object_kind=ContinuityObjectKind.COMMITMENT,
                    object_id=object_id,
                    review_decision_id="rdec_forced0001forced0001",
                )


def test_a_decision_and_a_task_of_a_are_invisible_to_b(migrated_engine: Engine) -> None:
    """The same partition claim for the other two objects, with its control."""
    with migrated_engine.begin() as connection:
        repository = SqlContinuityRepository(connection)
        decision = repository.propose_decision(
            principal_id=PRINCIPAL_A,
            question="Which synthetic option is taken",
            origin_evidence_ref=ORIGIN,
            origin_evidence_kind=ClosureEvidenceKind.CAPTURE,
            awaiting_authority_ref="rvw_authority0001authority",
        )
        task = repository.propose_task(
            principal_id=PRINCIPAL_A,
            title="Draft the synthetic summary",
            origin_evidence_ref=ORIGIN,
            origin_evidence_kind=ClosureEvidenceKind.CAPTURE,
        )

        assert repository.get_decision(PRINCIPAL_A, decision.decision_id) is not None
        assert repository.get_task(PRINCIPAL_A, task.task_id) is not None
        assert len(repository.list_decisions(PRINCIPAL_A)) == 1
        assert len(repository.list_tasks(PRINCIPAL_A)) == 1

        assert repository.get_decision(PRINCIPAL_B, decision.decision_id) is None
        assert repository.get_task(PRINCIPAL_B, task.task_id) is None
        assert repository.list_decisions(PRINCIPAL_B) == ()
        assert repository.list_tasks(PRINCIPAL_B) == ()


def test_lifecycle_rows_of_a_are_invisible_to_b(migrated_engine: Engine) -> None:
    """The append-only record is partitioned like everything it records."""
    with migrated_engine.begin() as connection:
        commitment_id = _propose_commitment(connection, principal_id=PRINCIPAL_A)
        repository = SqlContinuityRepository(connection)
        assert len(repository.lifecycle_events(PRINCIPAL_A, commitment_id)) == 1
        assert repository.lifecycle_events(PRINCIPAL_B, commitment_id) == ()


def test_the_pulse_of_a_is_never_derived_for_b(migrated_engine: Engine) -> None:
    """Control 1 for the Pulse, which is the read a second Principal would want."""
    with migrated_engine.begin() as connection:
        commitment_id = _propose_commitment(
            connection, principal_id=PRINCIPAL_A, due_at=NOW - timedelta(days=2)
        )
        review_decision = _stage_review_decision(
            connection, principal_id=PRINCIPAL_A, disposition="accept", suffix="aaaa0001"
        )
        SqlContinuityRepository(connection).accept(
            principal_id=PRINCIPAL_A,
            object_kind=ContinuityObjectKind.COMMITMENT,
            object_id=commitment_id,
            review_decision_id=review_decision,
        )
        pulse = SqlPulseRepository(connection)

        # Non-zero control, and the negative beside it.
        derived = pulse.derive_pulse(PRINCIPAL_A, NOW)
        assert [item.item_ref for item in derived] == [commitment_id]
        assert pulse.derive_pulse(PRINCIPAL_B, NOW) == ()


def test_a_situation_and_a_project_of_a_are_invisible_to_b(migrated_engine: Engine) -> None:
    """The two objects WP-06 delivered, re-asserted at the boundary WP-11 exposes."""
    with migrated_engine.begin() as connection:
        situations = SqlSituationRepository(connection)
        projects = SqlProjectRepository(connection)
        situation = situations.open_situation(
            principal_id=PRINCIPAL_A,
            title="North dock reconciliation",
            description=None,
            object_refs=(),
        )
        project = projects.add_project(
            principal_id=PRINCIPAL_A,
            name="Synthetic rollout",
            description=None,
            participants=(),
        )

        assert len(situations.list_situations(PRINCIPAL_A)) == 1
        assert len(projects.list_projects(PRINCIPAL_A)) == 1
        assert situations.list_situations(PRINCIPAL_B) == ()
        assert projects.list_projects(PRINCIPAL_B) == ()
        assert situations.get_situation(PRINCIPAL_B, situation.situation_id) is None
        assert projects.get_project(PRINCIPAL_B, project.project_id) is None


# --- Control 2: accepted-only continuity ------------------------------------


def test_a_proposal_is_not_established_continuity(migrated_engine: Engine) -> None:
    """It is reachable *as a proposal* and reaches the Pulse not at all."""
    with migrated_engine.begin() as connection:
        commitment_id = _propose_commitment(
            connection, principal_id=PRINCIPAL_A, due_at=NOW - timedelta(days=2)
        )
        repository = SqlContinuityRepository(connection)
        pulse = SqlPulseRepository(connection)

        proposed = repository.list_commitments(PRINCIPAL_A, ContinuityEvidenceState.PROPOSED)
        assert [row.commitment_id for row in proposed] == [commitment_id]
        assert repository.list_commitments(PRINCIPAL_A, ContinuityEvidenceState.ACCEPTED) == ()
        # The commitment is past due — the strongest why-now condition there is —
        # and is absent, because acceptance and not urgency is what admits it.
        assert pulse.derive_pulse(PRINCIPAL_A, NOW) == ()


def test_acceptance_requires_a_review_decision_that_accepted_in_this_partition(
    migrated_engine: Engine,
) -> None:
    """Four refusals and one success, all answered the same way when refused."""
    with migrated_engine.begin() as connection:
        commitment_id = _propose_commitment(
            connection, principal_id=PRINCIPAL_A, due_at=NOW - timedelta(days=2)
        )
        repository = SqlContinuityRepository(connection)
        rejected = _stage_review_decision(
            connection, principal_id=PRINCIPAL_A, disposition="reject", suffix="bbbb0001"
        )
        foreign = _stage_review_decision(
            connection, principal_id=PRINCIPAL_B, disposition="accept", suffix="cccc0001"
        )

        for review_decision_id in (
            rejected,
            foreign,
            "rdec_absent0001absent0001",
        ):
            with pytest.raises(UnknownScopeError):
                repository.accept(
                    principal_id=PRINCIPAL_A,
                    object_kind=ContinuityObjectKind.COMMITMENT,
                    object_id=commitment_id,
                    review_decision_id=review_decision_id,
                )
        # Still a proposal after every refusal.
        held = repository.get_commitment(PRINCIPAL_A, commitment_id)
        assert held is not None
        assert held.evidence_state is ContinuityEvidenceState.PROPOSED
        assert held.accepted_by_review_decision_id is None

        accepted_decision = _stage_review_decision(
            connection, principal_id=PRINCIPAL_A, disposition="accept", suffix="dddd0001"
        )
        repository.accept(
            principal_id=PRINCIPAL_A,
            object_kind=ContinuityObjectKind.COMMITMENT,
            object_id=commitment_id,
            review_decision_id=accepted_decision,
        )
        promoted = repository.get_commitment(PRINCIPAL_A, commitment_id)
        assert promoted is not None
        assert promoted.evidence_state is ContinuityEvidenceState.ACCEPTED
        assert promoted.accepted_by_review_decision_id == accepted_decision
        assert len(SqlPulseRepository(connection).derive_pulse(PRINCIPAL_A, NOW)) == 1


def test_the_server_refuses_accepted_continuity_with_no_review_decision(
    migrated_engine: Engine,
) -> None:
    """The storage half of control 2, met by a writer that bypasses the repository."""
    with migrated_engine.begin() as connection, pytest.raises(Exception, match="review_decision"):
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.commitments (commitment_id, principal_id, "  # noqa: S608
                "counterparty_person_id, direction, summary, state, evidence_state, "
                "origin_evidence_ref, opened_at, created_at, updated_at) VALUES "
                "('cmt_forged0001forged0001', :principal_id, :counterparty, "
                "'owed_by_principal', 'A forged acceptance', 'open', 'accepted', "
                ":origin, now(), now(), now())"
            ),
            {"principal_id": PRINCIPAL_A, "counterparty": COUNTERPARTY, "origin": ORIGIN},
        )


# --- Control 3: nothing promotes itself -------------------------------------


def test_a_pulse_read_writes_nothing_at_all(migrated_engine: Engine) -> None:
    """Measured, not asserted: every continuity table counted on both sides.

    A derivation that wrote its own output back — as an accepted commitment, as a
    stored pulse row, as anything — would be automatic consequential promotion
    arriving through a listing, and this is the assertion that would fail.
    """
    with migrated_engine.begin() as connection:
        commitment_id = _propose_commitment(
            connection, principal_id=PRINCIPAL_A, due_at=NOW - timedelta(days=2)
        )
        accepted_decision = _stage_review_decision(
            connection, principal_id=PRINCIPAL_A, disposition="accept", suffix="eeee0001"
        )
        repository = SqlContinuityRepository(connection)
        repository.accept(
            principal_id=PRINCIPAL_A,
            object_kind=ContinuityObjectKind.COMMITMENT,
            object_id=commitment_id,
            review_decision_id=accepted_decision,
        )
        # A second, still-proposed commitment, so the read has something it must
        # leave alone as well as something it must return.
        proposed_id = _propose_commitment(
            connection, principal_id=PRINCIPAL_A, due_at=NOW - timedelta(days=3)
        )

        before = _row_counts(connection)
        derived = SqlPulseRepository(connection).derive_pulse(PRINCIPAL_A, NOW)
        after = _row_counts(connection)

        assert len(derived) == 1
        assert before == after, f"the pulse read changed row counts: {before} -> {after}"
        still_proposed = repository.get_commitment(PRINCIPAL_A, proposed_id)
        assert still_proposed is not None
        assert still_proposed.evidence_state is ContinuityEvidenceState.PROPOSED


# --- Control 4: lifecycle and closure evidence ------------------------------


def test_a_close_writes_its_evidence_in_the_same_transaction(migrated_engine: Engine) -> None:
    """The state change and the evidence row are one act, or neither happened."""
    with migrated_engine.begin() as connection:
        commitment_id = _propose_commitment(connection, principal_id=PRINCIPAL_A)
        repository = SqlContinuityRepository(connection)
        repository.close(
            principal_id=PRINCIPAL_A,
            object_kind=ContinuityObjectKind.COMMITMENT,
            object_id=commitment_id,
            evidence_kind=ClosureEvidenceKind.RELATIONSHIP_EVENT,
            evidence_ref="revt_closed0001closed0001",
            occurred_at=NOW,
        )
        closed = repository.get_commitment(PRINCIPAL_A, commitment_id)
        assert closed is not None
        assert closed.closed_at is not None
        assert closed.closure_evidence_ref == "revt_closed0001closed0001"

        events = repository.lifecycle_events(PRINCIPAL_A, commitment_id)
        transitions = [event.transition for event in events]
        assert LifecycleTransition.OPENED in transitions
        assert LifecycleTransition.CLOSED in transitions
        closure = next(event for event in events if event.transition is LifecycleTransition.CLOSED)
        assert closure.evidence_kind is ClosureEvidenceKind.RELATIONSHIP_EVENT
        assert closure.evidence_ref == "revt_closed0001closed0001"
        assert closure.occurred_at == NOW


def test_the_server_refuses_a_closure_with_no_evidence(migrated_engine: Engine) -> None:
    """The CHECK, met by a writer that does not go through the repository.

    This is what makes closure evidence a property of the database rather than of
    application code remembering to supply it.
    """
    with (
        migrated_engine.begin() as connection,
        pytest.raises(Exception, match="a_closed_transition_carries_evidence"),
    ):
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.continuity_lifecycle_events (event_id, principal_id, "  # noqa: S608
                "object_kind, object_id, transition, evidence_kind, evidence_ref, "
                "occurred_at, recorded_at) VALUES ('lce_bare00001bare00001aa', :principal_id, "
                "'commitment', 'cmt_bare00001bare00001aa', 'closed', 'principal_statement', "
                "NULL, now(), now())"
            ),
            {"principal_id": PRINCIPAL_A},
        )


def test_a_situation_close_carries_evidence_too(migrated_engine: Engine) -> None:
    """All five continuity kinds close the same way, through one record."""
    with migrated_engine.begin() as connection:
        situations = SqlSituationRepository(connection)
        situation = situations.open_situation(
            principal_id=PRINCIPAL_A,
            title="North dock reconciliation",
            description=None,
            object_refs=(),
        )
        situations.close_situation(
            principal_id=PRINCIPAL_A,
            situation_id=situation.situation_id,
            outcome="carried the open commitment forward",
            evidence_kind=ClosureEvidenceKind.FRAME,
            evidence_ref="frm_closure0001closure01",
        )
        events = SqlContinuityRepository(connection).lifecycle_events(
            PRINCIPAL_A, situation.situation_id
        )
        assert [event.transition for event in events] == [LifecycleTransition.CLOSED]
        assert events[0].object_kind is ContinuityObjectKind.SITUATION
        assert events[0].evidence_ref == "frm_closure0001closure01"


# --- Control 5: associations are reconstructable from evidence --------------


def test_why_an_object_belongs_to_a_project_is_a_row_rather_than_an_inference(
    migrated_engine: Engine,
) -> None:
    """Given an object and a Principal, the evidence that justified its context."""
    with migrated_engine.begin() as connection:
        projects = SqlProjectRepository(connection)
        project = projects.add_project(
            principal_id=PRINCIPAL_A,
            name="Synthetic rollout",
            description=None,
            participants=(),
        )
        commitment_id = _propose_commitment(connection, principal_id=PRINCIPAL_A)
        repository = SqlContinuityRepository(connection)
        repository.associate(
            principal_id=PRINCIPAL_A,
            object_kind=ContinuityObjectKind.COMMITMENT,
            object_id=commitment_id,
            project_id=project.project_id,
            situation_id=None,
            evidence_kind=ClosureEvidenceKind.CAPTURE,
            evidence_ref=ORIGIN,
        )

        evidence = repository.association_evidence(PRINCIPAL_A, commitment_id)
        assert len(evidence) == 1
        assert evidence[0].transition is LifecycleTransition.ASSOCIATED
        assert evidence[0].evidence_kind is ClosureEvidenceKind.CAPTURE
        assert evidence[0].evidence_ref is not None
        assert project.project_id in evidence[0].evidence_ref
        assert ORIGIN in evidence[0].evidence_ref

        bound = repository.get_commitment(PRINCIPAL_A, commitment_id)
        assert bound is not None and bound.project_id == project.project_id

        # And B, given the same object identifier, reconstructs nothing.
        assert repository.association_evidence(PRINCIPAL_B, commitment_id) == ()


def test_an_association_cannot_reach_across_the_partition(migrated_engine: Engine) -> None:
    """Neither end of an association may belong to another Principal."""
    with migrated_engine.begin() as connection:
        foreign_project = SqlProjectRepository(connection).add_project(
            principal_id=PRINCIPAL_B,
            name="Another principal's rollout",
            description=None,
            participants=(),
        )
        commitment_id = _propose_commitment(connection, principal_id=PRINCIPAL_A)
        with pytest.raises(UnknownScopeError):
            SqlContinuityRepository(connection).associate(
                principal_id=PRINCIPAL_A,
                object_kind=ContinuityObjectKind.COMMITMENT,
                object_id=commitment_id,
                project_id=foreign_project.project_id,
                situation_id=None,
                evidence_kind=ClosureEvidenceKind.CAPTURE,
                evidence_ref=ORIGIN,
            )


def test_a_project_situation_link_records_the_evidence_that_justified_it(
    migrated_engine: Engine,
) -> None:
    """The `project_situations` half of control 5, column and lifecycle row."""
    with migrated_engine.begin() as connection:
        situations = SqlSituationRepository(connection)
        projects = SqlProjectRepository(connection)
        situation = situations.open_situation(
            principal_id=PRINCIPAL_A,
            title="North dock reconciliation",
            description=None,
            object_refs=(),
        )
        project = projects.add_project(
            principal_id=PRINCIPAL_A,
            name="Synthetic rollout",
            description=None,
            participants=(),
        )
        projects.link_situation(
            principal_id=PRINCIPAL_A,
            project_id=project.project_id,
            situation_id=situation.situation_id,
            evidence_kind=ClosureEvidenceKind.FRAME,
            evidence_ref="frm_reason0001reason0001",
        )
        stored = connection.execute(
            text(
                f"SELECT association_evidence_ref FROM {SCHEMA}.project_situations "  # noqa: S608
                "WHERE principal_id = :principal_id"
            ),
            {"principal_id": PRINCIPAL_A},
        ).scalar_one()
        assert stored == "frm_reason0001reason0001"

        evidence = SqlContinuityRepository(connection).association_evidence(
            PRINCIPAL_A, situation.situation_id
        )
        assert [event.evidence_ref for event in evidence] == ["frm_reason0001reason0001"]


# --- Control 6: no Pulse row without a basis --------------------------------


def test_the_server_refuses_a_pulse_row_with_no_evidentiary_basis(
    migrated_engine: Engine,
) -> None:
    """An activity-feed row is not discouraged here. It is unstorable."""
    statement = text(
        f"INSERT INTO {SCHEMA}.pulse_items (pulse_id, principal_id, item_type, item_ref, "  # noqa: S608
        "reason, reason_code, basis_refs, priority, accepted_only, generated_at) VALUES "
        "(:pulse_id, :principal_id, 'commitment', 'cmt_feed00001feed00001aa', "
        ":reason, :reason_code, :basis, 5, true, now())"
    )
    with (
        migrated_engine.begin() as connection,
        pytest.raises(Exception, match="a_pulse_item_carries_an_evidentiary_basis"),
    ):
        connection.execute(
            statement,
            {
                "pulse_id": "puls_feed00001feed00001aa",
                "principal_id": PRINCIPAL_A,
                "reason": "something happened recently",
                "reason_code": "commitment_overdue",
                "basis": "[]",
            },
        )

    # The non-vacuity control: the same insert with one basis reference is
    # accepted, so the refusal above is about the basis and not about the row.
    with migrated_engine.begin() as connection:
        connection.execute(
            statement,
            {
                "pulse_id": "puls_good00001good00001aa",
                "principal_id": PRINCIPAL_A,
                "reason": "the agreed moment passed two days ago",
                "reason_code": "commitment_overdue",
                "basis": '["cmt_feed00001feed00001aa"]',
            },
        )


def test_the_server_refuses_a_pulse_reason_code_outside_the_vocabulary(
    migrated_engine: Engine,
) -> None:
    """A `recently_updated` reason is not a style choice anyone can make."""
    with (
        migrated_engine.begin() as connection,
        pytest.raises(Exception, match="a_pulse_reason_code_is_known"),
    ):
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.pulse_items (pulse_id, principal_id, item_type, "  # noqa: S608
                "item_ref, reason, reason_code, basis_refs, priority, accepted_only, "
                "generated_at) VALUES ('puls_recent001recent001a', :principal_id, "
                "'commitment', 'cmt_feed00001feed00001aa', 'it changed', 'recently_updated', "
                "'[\"cmt_feed00001feed00001aa\"]', 5, true, now())"
            ),
            {"principal_id": PRINCIPAL_A},
        )
