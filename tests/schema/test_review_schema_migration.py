"""The review and promotion revision round-trips, and its triggers are real.

`3c8f1e2a5b74` adds seven tables, three constraint triggers, governed-update
triggers, and lineage triggers on every retained evidence table. Every claim
below is read back from a live server rather than from the file that wrote it,
because a migration is only what the database ends up holding.

**Empty to head and head to empty**, which `AGENTS.md` section 6 requires of a
schema change, plus the two things a table drop does not take with it: three
trigger functions in the `knowledge` schema, and five triggers on tables this
revision does not own. `7e5a1fb93d62` drops the schema with `RESTRICT`, so a
function left behind fails `downgrade base` at a revision written before this one
existed — the failure `1a4c9e77b2d5` had to add an explicit `DROP FUNCTION` for
and `2b7e9f4c1a83` had to repeat.

**Exact evidence is immutable, and state updates are governed.**
`QC-AC-022` requires rejected and corrected proposals to retain lineage. The test
for it asserts an `INSERT` still succeeds in the same database that finds a
`DELETE` refused — otherwise "no row could be removed" would also be satisfied
by a schema in which no row could be added. Proposals and assertions retain their
governed `UPDATE` paths; review cases, decisions, and promotion receipts refuse
`UPDATE OR DELETE` because they have no governed mutation path. Spans and both
span-link tables do the same, including when a parent FK declares a cascade.

**The gap this closes was live before this revision.** `capture_proposals`
accepted `DELETE` and `capture_proposal_spans.proposal_id` cascades, so deleting
a proposal silently removed the evidence links that are the lineage. That is a
pre-existing hole surfaced here rather than a defect this package introduced, and
the test that proves the trigger fires drops it and watches the `DELETE` succeed.

**Every value here is synthetic.** No path exists or is opened, and the fixtures
store only the shortest invented capture content the constraints admit.
The database is disposable, created and dropped by its own fixture and never the
configured one — `downgrade base` deletes schemas, and pointing that at the
canonical `my_pa` database would destroy the migrated corpus.

**The `S608` suppressions are structural, not a convenience.** Every
interpolation into a statement below is one of this module's own `Final`
constants — the schema name, a member of `REVIEW_TABLES` or `UNDELETABLE`, or a
locally declared adversarial mutation. No caller value reaches a
statement's text: every one of those is a bound parameter, which is why the
identifiers the seeds write are passed as `:name` rather than formatted in. The
same argument the revision itself makes for its `CREATE FUNCTION` text.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import ReviewDecisionRequest
from my_pa.domain.capture.assertion import AssertionState
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.capture.review import Disposition, ReviewConflictError
from my_pa.domain.capture.version import digest_of
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.review import (
    decide_review,
    mark_changed_assertions_for_revalidation,
    open_review_case,
)

ROOT = Path(__file__).resolve().parents[2]

SCHEMA = "knowledge"

REVIEW_REVISION = "3c8f1e2a5b74"
PROPOSAL_REVISION = "2b7e9f4c1a83"

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
#: Distinct from every other suite's disposable database, so they cannot collide —
#: the database tier runs serially and these names are server-global.
DISPOSABLE_DATABASE = "my_pa_review_test"

#: The seven tables this revision creates, restated. A table added to the
#: revision has to be acknowledged here, which is the point.
REVIEW_TABLES: Final[frozenset[str]] = frozenset(
    {
        "capture_review_cases",
        "capture_review_decisions",
        "capture_assertions",
        "capture_assertion_spans",
        "capture_promotion_receipts",
        "capture_context_links",
        "capture_conversations",
    }
)

#: The four functions, restated for the same reason.
REVIEW_FUNCTIONS: Final[frozenset[str]] = frozenset(
    {
        "an_assertion_cites_a_span",
        "an_accepted_record_names_an_assertion",
        "review_lineage_stays_as_written",
        "review_state_transition_is_governed",
    }
)

DEFERRED_TRIGGERS: Final[tuple[str, ...]] = (
    "an_assertion_cites_at_least_one_span",
    "a_span_link_leaves_its_assertion_cited",
    "an_accepted_proposal_names_a_real_assertion",
)

#: These two parents are undeletable and accept only exact state transitions.
GOVERNED: Final[tuple[str, ...]] = ("capture_proposals", "capture_assertions")

#: These three are immutable evidence: insert succeeds, update/delete refuse.
IMMUTABLE: Final[dict[str, str]] = {
    "capture_review_cases": "opened_at",
    "capture_review_decisions": "decided_at",
    "capture_promotion_receipts": "issued_at",
}

EXACT_LINEAGE: Final[dict[str, str]] = {
    "capture_spans": "span_role",
    "capture_proposal_spans": "span_id",
    "capture_assertion_spans": "span_id",
}

UNDELETABLE: Final[tuple[str, ...]] = (*GOVERNED, *IMMUTABLE, *EXACT_LINEAGE)

_SUFFIX = "0000000000000001"


def _identifier(prefix: str, ordinal: int) -> str:
    """A well-formed opaque identifier, synthetic and non-semantic."""
    return f"{prefix}_{_SUFFIX[: len(_SUFFIX) - len(str(ordinal))]}{ordinal}"


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
        # CREATE and DROP DATABASE cannot run inside a transaction block.
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


def _tables(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
                ),
                {"schema": SCHEMA},
            ).scalars()
        )


def _row_snapshot(connection: Connection, table: str) -> tuple[tuple[object, ...], ...]:
    """All columns in deterministic primary-key order for a post-refusal check."""
    return tuple(
        tuple(row)
        for row in connection.execute(
            text(f"SELECT * FROM {SCHEMA}.{table} ORDER BY 1, 2")  # noqa: S608
        ).all()
    )


def _seed_proposal(
    connection: Connection, ordinal: int = 1, *, span_count: int = 1
) -> dict[str, str]:
    """One capture, version, span and proposal, with the link the trigger wants.

    Written with the shortest content the constraints admit. The proposal's span
    link is inserted in the same transaction because `2b7e9f4c1a83`'s deferred
    trigger refuses a proposal that cites none at commit.
    """
    ids = {
        "capture_id": _identifier("cap", ordinal),
        "version_id": _identifier("capver", ordinal),
        "span_id": _identifier("span", ordinal),
        "proposal_id": _identifier("prop", ordinal),
        "principal_id": _identifier("prn", ordinal),
        "correlation_id": _identifier("corr", ordinal),
        "audit_id": _identifier("audit", ordinal),
    }
    if span_count not in {1, 2}:
        raise ValueError("the synthetic review fixture supports one or two spans")
    if span_count == 2:
        ids["second_span_id"] = _identifier("span", ordinal + 100)
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.captures (capture_id, owner_principal_id) "  # noqa: S608
            "VALUES (:capture_id, :principal_id)"
        ),
        ids,
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_versions (version_id, capture_id, version_number, "  # noqa: S608
            "content, content_sha256, owner_principal_id, classification, processing_policy, "
            "idempotency_key, correlation_id, audit_id, server_received_at, accepted_at, "
            "recorded_at) VALUES (:version_id, :capture_id, 1, 'x', :digest, :principal_id, "
            "'synthetic_test', 'local_only', :version_id, :correlation_id, :audit_id, now(), "
            "now(), now())"
        ),
        {**ids, "digest": digest_of("x")},
    )
    if span_count == 2:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.capture_spans (span_id, version_id, start_offset, "  # noqa: S608
                "end_offset, offset_basis, line_start, column_start, line_end, column_end, "
                "quoted_text_sha256, span_role) VALUES (:second_span_id, :version_id, 0, 1, "
                "'unicode_code_point_v1', 1, 1, 1, 2, :digest, 'direct')"
            ),
            {**ids, "digest": digest_of("x")},
        )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_spans (span_id, version_id, start_offset, end_offset, "  # noqa: S608
            "offset_basis, line_start, column_start, line_end, column_end, quoted_text_sha256, "
            "span_role) VALUES (:span_id, :version_id, 0, 1, 'unicode_code_point_v1', 1, 1, 1, 2, "
            ":digest, 'direct')"
        ),
        {**ids, "digest": digest_of("x")},
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_proposals (proposal_id, version_id, proposal_type, "  # noqa: S608
            "state, risk_class, method, method_version, schema_version) VALUES (:proposal_id, "
            ":version_id, 'commitment', 'proposed', 'high', 'deterministic_rule', 'v1', 'v1')"
        ),
        ids,
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_proposal_spans (proposal_id, span_id) "  # noqa: S608
            "VALUES (:proposal_id, :span_id)"
        ),
        ids,
    )
    if span_count == 2:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.capture_proposal_spans (proposal_id, span_id) "  # noqa: S608
                "VALUES (:proposal_id, :second_span_id)"
            ),
            ids,
        )
    return ids


def _seed_promotion(
    connection: Connection,
    ids: dict[str, str],
    ordinal: int = 1,
    *,
    cite_span: bool = True,
    disposition: Disposition = Disposition.ACCEPT,
    corrected_value: str | None = None,
) -> dict[str, str]:
    """A review case, one decision, the assertion it accepted, and its span link.

    `cite_span=False` writes everything except the link, which is the one thing
    the deferred trigger is about. Leaving any other column out would be refused
    by a `NOT NULL` before the trigger ever ran, and the test would then pass for
    a reason it does not name.
    """
    if (disposition is Disposition.CORRECT_AND_ACCEPT) is not (corrected_value is not None):
        raise ValueError("the synthetic correction must match its accepting disposition")
    promoted = {
        **ids,
        "review_case_id": _identifier("rvw", ordinal),
        "decision_id": _identifier("rdec", ordinal),
        "assertion_id": _identifier("asrt", ordinal),
        "receipt_id": _identifier("rcpt", ordinal),
    }
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_review_cases (review_case_id, proposal_id, capture_id, "  # noqa: S608
            "version_id) VALUES (:review_case_id, :proposal_id, :capture_id, :version_id)"
        ),
        promoted,
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_review_decisions (decision_id, review_case_id, "  # noqa: S608
            "sequence, disposition, principal_id, correlation_id, audit_id, decided_at) VALUES "
            "(:decision_id, :review_case_id, 1, :disposition, :principal_id, :correlation_id, "
            ":audit_id, now())"
        ),
        {**promoted, "disposition": disposition.value},
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_assertions (assertion_id, version_id, proposal_id, "  # noqa: S608
            "decision_id, assertion_type, state, normalized_value, accepted_at) VALUES "
            "(:assertion_id, :version_id, :proposal_id, :decision_id, 'commitment', 'accepted', "
            ":corrected_value, now())"
        ),
        {**promoted, "corrected_value": corrected_value},
    )
    if cite_span:
        connection.execute(
            text(
                f"INSERT INTO {SCHEMA}.capture_assertion_spans (assertion_id, span_id) "  # noqa: S608
                "VALUES (:assertion_id, :span_id)"
            ),
            promoted,
        )
        if "second_span_id" in promoted:
            connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.capture_assertion_spans (assertion_id, span_id) "  # noqa: S608
                    "VALUES (:assertion_id, :second_span_id)"
                ),
                promoted,
            )
    return promoted


def _seed_receipt(connection: Connection, promoted: dict[str, str]) -> None:
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_promotion_receipts (receipt_id, assertion_id, "  # noqa: S608
            "decision_id, policy_version) VALUES (:receipt_id, :assertion_id, :decision_id, "
            "'policy-v1')"
        ),
        promoted,
    )


def _decision_request(
    review_case_id: str,
    *,
    expected: int,
    disposition: Disposition,
    corrected_value: str | None = None,
) -> ReviewDecisionRequest:
    return ReviewDecisionRequest(
        review_case_id=review_case_id,
        expected_review_version=expected,
        disposition=disposition,
        principal_id=_identifier("prn", 90),
        correlation_id=_identifier("corr", 90),
        audit_id=_identifier("audit", 90),
        policy_version="policy-v1",
        decided_at=datetime(2026, 8, 4, 12, 0, tzinfo=UTC),
        corrected_value=corrected_value,
    )


def _accepted_case_snapshot(connection: Connection, ids: dict[str, str]) -> tuple[object, ...]:
    """Every row a refused post-acceptance decision must leave byte-for-byte alone."""
    proposal = connection.execute(
        text(
            f"SELECT state, normalized_value, accepted_record_type, accepted_record_id "  # noqa: S608
            f"FROM {SCHEMA}.capture_proposals WHERE proposal_id = :proposal_id"
        ),
        ids,
    ).one()
    decisions = connection.execute(
        text(
            f"SELECT decision_id, sequence, disposition, principal_id, correlation_id, "  # noqa: S608
            f"audit_id, decided_at FROM {SCHEMA}.capture_review_decisions "
            "WHERE review_case_id = :review_case_id ORDER BY sequence"
        ),
        ids,
    ).all()
    assertions = connection.execute(
        text(
            f"SELECT assertion_id, decision_id, state, normalized_value, accepted_at, "  # noqa: S608
            f"revalidation_required_at FROM {SCHEMA}.capture_assertions "
            "WHERE proposal_id = :proposal_id ORDER BY assertion_id"
        ),
        ids,
    ).all()
    assertion_spans = connection.execute(
        text(
            f"SELECT s.assertion_id, s.span_id FROM {SCHEMA}.capture_assertion_spans s "  # noqa: S608
            f"JOIN {SCHEMA}.capture_assertions a ON a.assertion_id = s.assertion_id "
            "WHERE a.proposal_id = :proposal_id ORDER BY s.assertion_id, s.span_id"
        ),
        ids,
    ).all()
    receipts = connection.execute(
        text(
            f"SELECT r.receipt_id, r.assertion_id, r.decision_id, r.policy_version, "  # noqa: S608
            f"r.issued_at FROM {SCHEMA}.capture_promotion_receipts r "
            f"JOIN {SCHEMA}.capture_assertions a ON a.assertion_id = r.assertion_id "
            "WHERE a.proposal_id = :proposal_id ORDER BY r.receipt_id"
        ),
        ids,
    ).all()
    return proposal, tuple(decisions), tuple(assertions), tuple(assertion_spans), tuple(receipts)


def test_the_review_revision_is_in_the_chain_on_the_proposal_revision() -> None:
    """Guards the rest of this module: an absent revision would create nothing.

    Deliberately not "is the head", for the reason the capture and audit
    revisions' equivalents record: that property is true only until the next
    revision is written, and asserting it makes every later work package edit
    this file.
    """
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert REVIEW_REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(REVIEW_REVISION).down_revision == PROPOSAL_REVISION


@pytest.mark.database
def test_the_review_revision_runs_empty_to_head_and_head_to_empty(
    disposable_database: str,
) -> None:
    """Reversible, and reversible including what a table drop does not take.

    Four functions and the triggers on tables this revision owns and does not
    own. A trigger goes with its table and the latter have no table to go
    with, so the downgrade has to name them; a function goes with nothing at all.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")

        assert _tables(engine) >= REVIEW_TABLES
        with engine.connect() as connection:
            triggers = dict(
                connection.execute(
                    text(
                        "SELECT t.tgname, pg_get_triggerdef(t.oid, true) FROM pg_trigger t "
                        "JOIN pg_class c ON c.oid = t.tgrelid "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE NOT t.tgisinternal AND n.nspname = :schema"
                    ),
                    {"schema": SCHEMA},
                ).all()
            )
            routines = set(
                connection.execute(
                    text(
                        "SELECT p.proname FROM pg_proc p JOIN pg_namespace n "
                        "ON n.oid = p.pronamespace WHERE n.nspname = :schema"
                    ),
                    {"schema": SCHEMA},
                ).scalars()
            )
        assert routines >= REVIEW_FUNCTIONS
        for name in DEFERRED_TRIGGERS:
            assert "CONSTRAINT TRIGGER" in triggers[name], name
            assert "DEFERRABLE INITIALLY DEFERRED" in triggers[name], name
        for table in UNDELETABLE:
            name = f"{table}_stay_immutable" if table in IMMUTABLE else f"{table}_are_never_deleted"
            if table in EXACT_LINEAGE:
                name = f"{table}_stay_immutable"
            definition = triggers[name]
            assert "BEFORE" in definition and "DELETE" in definition, table
            assert ("UPDATE" in definition) is (table in (*IMMUTABLE, *EXACT_LINEAGE)), table
            # The control: these are ordinary triggers, so "every trigger this
            # revision installs is deferred" is not what the loop above proved.
            assert "DEFERRABLE" not in definition, table
        for table in GOVERNED:
            definition = triggers[f"{table}_updates_are_governed"]
            assert "BEFORE UPDATE" in definition, table
            assert "DEFERRABLE" not in definition, table

        command.downgrade(_config(), "base")

        with engine.connect() as connection:
            remaining = set(connection.execute(text("SELECT nspname FROM pg_namespace")).scalars())
            left = set(
                connection.execute(
                    text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
                ).scalars()
            )
            routines = set(
                connection.execute(
                    text(
                        "SELECT n.nspname || '.' || p.proname FROM pg_proc p "
                        "JOIN pg_namespace n ON n.oid = p.pronamespace "
                        "WHERE n.nspname NOT LIKE 'pg\\_%' "
                        "AND n.nspname <> 'information_schema'"
                    )
                ).scalars()
            )
        assert SCHEMA not in remaining
        assert left == set()
        assert routines == set()
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrading_this_revision_leaves_the_chain_below_it_intact(
    disposable_database: str,
) -> None:
    """A downgrade removes this revision's work and not the schema.

    The control is the second half: the twenty-two tables the revisions below
    created are still there, so "the seven are gone" is a measurement rather than
    the observation that the schema was dropped.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert _tables(engine) >= REVIEW_TABLES

        command.downgrade(_config(), PROPOSAL_REVISION)

        remaining = _tables(engine)
        assert not REVIEW_TABLES & remaining
        assert len(remaining) == 22
        with engine.connect() as connection:
            left = set(
                connection.execute(
                    text(
                        "SELECT p.proname FROM pg_proc p JOIN pg_namespace n "
                        "ON n.oid = p.pronamespace WHERE n.nspname = :schema"
                    ),
                    {"schema": SCHEMA},
                ).scalars()
            )
        assert not REVIEW_FUNCTIONS & left

        command.upgrade(_config(), "head")
        assert _tables(engine) >= REVIEW_TABLES

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_prior_revision_with_existing_proposal_upgrades_to_head_without_rewrite(
    disposable_database: str,
) -> None:
    """The forward migration preserves rows that predate the WP-8 triggers."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PROPOSAL_REVISION)
        with engine.begin() as connection:
            ids = _seed_proposal(connection, ordinal=18)
            before = connection.execute(
                text(
                    f"SELECT * "  # noqa: S608
                    f"FROM {SCHEMA}.capture_proposals WHERE proposal_id = :proposal_id"
                ),
                ids,
            ).one()

        command.upgrade(_config(), "head")

        with engine.connect() as connection:
            after = connection.execute(
                text(
                    f"SELECT * "  # noqa: S608
                    f"FROM {SCHEMA}.capture_proposals WHERE proposal_id = :proposal_id"
                ),
                ids,
            ).one()
        assert after == before

        with pytest.raises(DBAPIError) as refused, engine.begin() as connection:
            connection.execute(
                text(
                    f"DELETE FROM {SCHEMA}.capture_proposals "  # noqa: S608
                    "WHERE proposal_id = :proposal_id"
                ),
                ids,
            )
        assert "retains lineage" in str(refused.value)

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_an_assertion_that_cites_no_span_is_refused_at_commit(
    disposable_database: str,
) -> None:
    """`QC-AC-011`'s accepted-record half, as a property of the schema.

    Two halves, because either alone is satisfied by a schema that refuses
    everything: an assertion written with its span link commits, and the same
    assertion written without one is refused at commit rather than at the
    statement — which is what `DEFERRABLE INITIALLY DEFERRED` buys, since the
    assertion has to exist before a link can reference it.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")

        with engine.begin() as connection:
            _seed_promotion(connection, _seed_proposal(connection, 1), 1)
        # The non-zero control, in the same test: an assertion written *with* its
        # link commits, so the refusal below is about the link and not about the
        # table refusing every row.
        with engine.connect() as connection:
            stored = connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.capture_assertions")  # noqa: S608
            ).scalar_one()
        assert stored == 1

        # Identical in every column, and written in the same shape, except that
        # no row is inserted into `capture_assertion_spans`.
        with pytest.raises(DBAPIError) as refused, engine.begin() as connection:
            _seed_promotion(connection, _seed_proposal(connection, 2), 2, cite_span=False)
        assert "at least one span" in str(refused.value)

        with engine.connect() as connection:
            after = connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.capture_assertions")  # noqa: S608
            ).scalar_one()
        # The whole transaction rolled back, so the first assertion is all there is.
        assert after == 1

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_an_accepted_proposal_must_name_an_assertion_that_exists(
    disposable_database: str,
) -> None:
    """`D-48`'s substitute for the foreign key that cannot be declared.

    `capture_proposals.accepted_record_id` carries no `ForeignKey`, because
    adding one to the shared declaration would change what already-merged
    `2b7e9f4c1a83` emits. Three assertions, because a trigger that refused
    everything would satisfy the first two on its own: the real assertion is
    nameable, an identifier naming nothing is refused, and a type that is not
    `assertion` is refused even when the identifier does exist.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")

        with engine.begin() as connection:
            promoted = _seed_promotion(connection, _seed_proposal(connection), 1)
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.capture_proposals SET state = 'accepted', "  # noqa: S608
                    "accepted_record_type = 'assertion', "
                    "accepted_record_id = :assertion_id WHERE proposal_id = :proposal_id"
                ),
                promoted,
            )
        with engine.connect() as connection:
            named = connection.execute(
                text(
                    f"SELECT accepted_record_id FROM {SCHEMA}.capture_proposals "  # noqa: S608
                    "WHERE proposal_id = :proposal_id"
                ),
                promoted,
            ).scalar_one()
        assert named == promoted["assertion_id"]

        with pytest.raises(DBAPIError) as unknown, engine.begin() as connection:
            absent = _seed_proposal(connection, 2)
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.capture_proposals SET state = 'accepted', "  # noqa: S608
                    "accepted_record_type = 'assertion', "
                    "accepted_record_id = :absent WHERE proposal_id = :proposal_id"
                ),
                {**absent, "absent": _identifier("asrt", 7)},
            )
        assert "exact accepted assertion" in str(unknown.value)

        with pytest.raises(DBAPIError) as wrong_type, engine.begin() as connection:
            wrong = _seed_promotion(connection, _seed_proposal(connection, 3), 3)
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.capture_proposals SET state = 'accepted', "  # noqa: S608
                    "accepted_record_type = 'proposal', "
                    "accepted_record_id = :assertion_id WHERE proposal_id = :proposal_id"
                ),
                wrong,
            )
        assert "governed state transitions" in str(wrong_type.value)

        with pytest.raises(DBAPIError) as wrong_lineage, engine.begin() as connection:
            other = _seed_promotion(connection, _seed_proposal(connection, 4), 4)
            target = _seed_proposal(connection, 5)
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.capture_proposals SET state = 'accepted', "  # noqa: S608
                    "accepted_record_type = 'assertion', accepted_record_id = :assertion_id "
                    "WHERE proposal_id = :proposal_id"
                ),
                {**target, "assertion_id": other["assertion_id"]},
            )
        assert "exact accepted assertion" in str(wrong_lineage.value)

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_proposal_server_guard_allows_only_real_transition_shapes(
    disposable_database: str,
) -> None:
    """Real writer transitions pass; unrelated row deltas fail at the server."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")

        with engine.begin() as connection:
            routed = _seed_proposal(connection, 10)
            review_case_id = open_review_case(connection, routed["proposal_id"])
            assert review_case_id is not None
            assert (
                decide_review(
                    connection,
                    _decision_request(
                        review_case_id,
                        expected=0,
                        disposition=Disposition.REJECT,
                    ),
                )
                is not None
            )

            for ordinal, prior_state in enumerate(
                ("proposed", "needs_review", "rejected", "deferred", "unresolved"),
                start=11,
            ):
                invalidated = _seed_proposal(connection, ordinal)
                if prior_state == "needs_review":
                    assert open_review_case(connection, invalidated["proposal_id"]) is not None
                elif prior_state != "proposed":
                    connection.execute(
                        text(
                            f"UPDATE {SCHEMA}.capture_proposals SET state = :prior_state "  # noqa: S608
                            "WHERE proposal_id = :proposal_id"
                        ),
                        {**invalidated, "prior_state": prior_state},
                    )
                connection.execute(
                    text(
                        f"UPDATE {SCHEMA}.capture_proposals SET state = 'invalidated', "  # noqa: S608
                        "quarantine_reason = 'span_text_does_not_re_derive' "
                        "WHERE proposal_id = :proposal_id"
                    ),
                    invalidated,
                )

            accepted = _seed_promotion(connection, _seed_proposal(connection, 17), 17)
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.capture_proposals SET state = 'accepted', "  # noqa: S608
                    "accepted_record_type = 'assertion', accepted_record_id = :assertion_id "
                    "WHERE proposal_id = :proposal_id"
                ),
                accepted,
            )

            corrected = _seed_promotion(
                connection,
                _seed_proposal(connection, 18),
                18,
                disposition=Disposition.CORRECT_AND_ACCEPT,
                corrected_value="synthetic correction",
            )
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.capture_proposals SET state = 'corrected_accepted', "  # noqa: S608
                    "normalized_value = 'synthetic correction', "
                    "accepted_record_type = 'assertion', accepted_record_id = :assertion_id "
                    "WHERE proposal_id = :proposal_id"
                ),
                corrected,
            )

        with engine.begin() as connection:
            mismatch = _seed_promotion(
                connection,
                _seed_proposal(connection, 19),
                19,
                disposition=Disposition.CORRECT_AND_ACCEPT,
                corrected_value="assertion correction",
            )
        with engine.connect() as connection:
            before_mismatch = _row_snapshot(connection, "capture_proposals")
        with pytest.raises(DBAPIError) as refused_mismatch, engine.begin() as connection:
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.capture_proposals SET state = 'corrected_accepted', "  # noqa: S608
                    "normalized_value = 'different proposal correction', "
                    "accepted_record_type = 'assertion', accepted_record_id = :assertion_id "
                    "WHERE proposal_id = :proposal_id"
                ),
                mismatch,
            )
        assert "exact accepted assertion" in str(refused_mismatch.value)
        with engine.connect() as connection:
            assert _row_snapshot(connection, "capture_proposals") == before_mismatch

        mutations = (
            "created_at = created_at + interval '1 second'",
            "proposal_id = :replacement",
            "version_id = :replacement",
            "proposal_type = 'task'",
            "risk_class = 'critical'",
            "method = 'cloud_model'",
            "method_version = 'v2'",
            "schema_version = 'v2'",
            "missing_required_fields = ARRAY['actor']",
            "normalized_value = 'unauthorized rewrite'",
            "accepted_record_type = 'assertion', accepted_record_id = :replacement",
            "state = 'superseded'",
            "state = 'invalidated', quarantine_reason = 'span_text_does_not_re_derive', "
            "method_version = 'v2'",
        )
        for ordinal, mutation in enumerate(mutations, start=20):
            with engine.begin() as connection:
                ids = _seed_proposal(connection, ordinal)
                case_id = open_review_case(connection, ids["proposal_id"])
                assert case_id is not None
            with engine.connect() as connection:
                before = _row_snapshot(connection, "capture_proposals")
            with pytest.raises(DBAPIError) as refused, engine.begin() as connection:
                connection.execute(
                    text(
                        f"UPDATE {SCHEMA}.capture_proposals SET {mutation} "  # noqa: S608
                        "WHERE proposal_id = :proposal_id"
                    ),
                    {**ids, "replacement": _identifier("prop", ordinal + 200)},
                )
            assert "governed state transitions" in str(refused.value), mutation
            with engine.connect() as connection:
                assert _row_snapshot(connection, "capture_proposals") == before, mutation

        with engine.connect() as connection:
            before_accepted_rewrite = _row_snapshot(connection, "capture_proposals")
        with pytest.raises(DBAPIError) as accepted_rewrite, engine.begin() as connection:
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.capture_proposals "  # noqa: S608
                    "SET normalized_value = 'rewritten after acceptance' "
                    "WHERE proposal_id = :proposal_id"
                ),
                accepted,
            )
        assert "governed state transitions" in str(accepted_rewrite.value)
        with engine.connect() as connection:
            assert _row_snapshot(connection, "capture_proposals") == before_accepted_rewrite

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_assertion_server_guard_allows_only_revalidation_transition(
    disposable_database: str,
) -> None:
    """Only accepted-to-revalidation-required plus its timestamp may change."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.begin() as connection:
            allowed = _seed_promotion(connection, _seed_proposal(connection, 50), 50)
            updated = connection.execute(
                text(
                    f"UPDATE {SCHEMA}.capture_assertions "  # noqa: S608
                    "SET state = 'revalidation_required', revalidation_required_at = now() "
                    "WHERE assertion_id = :assertion_id"
                ),
                allowed,
            ).rowcount
        assert updated == 1

        mutations = (
            "accepted_at = accepted_at + interval '1 second'",
            "assertion_id = :replacement",
            "version_id = :replacement",
            "proposal_id = :replacement",
            "decision_id = :replacement",
            "assertion_type = 'task'",
            "normalized_value = 'unauthorized rewrite'",
            "superseded_by_assertion_id = :replacement",
            "state = 'withdrawn'",
            "revalidation_required_at = now()",
            "state = 'revalidation_required', revalidation_required_at = now(), "
            "accepted_at = accepted_at + interval '1 second'",
        )
        for ordinal, mutation in enumerate(mutations, start=51):
            with engine.begin() as connection:
                ids = _seed_promotion(
                    connection,
                    _seed_proposal(connection, ordinal),
                    ordinal,
                )
            with engine.connect() as connection:
                before = _row_snapshot(connection, "capture_assertions")
            with pytest.raises(DBAPIError) as refused, engine.begin() as connection:
                connection.execute(
                    text(
                        f"UPDATE {SCHEMA}.capture_assertions SET {mutation} "  # noqa: S608
                        "WHERE assertion_id = :assertion_id"
                    ),
                    {**ids, "replacement": _identifier("asrt", ordinal + 200)},
                )
            assert "governed state transitions" in str(refused.value), mutation
            with engine.connect() as connection:
                assert _row_snapshot(connection, "capture_assertions") == before, mutation

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_two_span_proposal_and_assertion_lineage_cannot_be_rewritten_or_deleted(
    disposable_database: str,
) -> None:
    """Two-span promotion succeeds, then every evidence row stays byte-exact."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.begin() as connection:
            promoted = _seed_promotion(
                connection,
                _seed_proposal(connection, 70, span_count=2),
                70,
            )
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.capture_proposals SET state = 'accepted', "  # noqa: S608
                    "accepted_record_type = 'assertion', accepted_record_id = :assertion_id "
                    "WHERE proposal_id = :proposal_id"
                ),
                promoted,
            )
            _seed_receipt(connection, promoted)

        with engine.connect() as connection:
            lineage_before = {
                table: _row_snapshot(connection, table)
                for table in (
                    "capture_spans",
                    "capture_proposal_spans",
                    "capture_assertion_spans",
                    "capture_proposals",
                    "capture_assertions",
                    "capture_review_decisions",
                    "capture_promotion_receipts",
                )
            }

        attempts = (
            (
                "capture_spans",
                "UPDATE",
                "UPDATE knowledge.capture_spans SET quoted_text_sha256 = repeat('1', 64) "
                "WHERE span_id = :span_id",
            ),
            (
                "capture_spans",
                "DELETE",
                "DELETE FROM knowledge.capture_spans WHERE span_id = :span_id",
            ),
            (
                "capture_proposal_spans",
                "UPDATE",
                "UPDATE knowledge.capture_proposal_spans SET span_id = :replacement "
                "WHERE proposal_id = :proposal_id AND span_id = :span_id",
            ),
            (
                "capture_proposal_spans",
                "DELETE",
                "DELETE FROM knowledge.capture_proposal_spans "
                "WHERE proposal_id = :proposal_id AND span_id = :span_id",
            ),
            (
                "capture_assertion_spans",
                "UPDATE",
                "UPDATE knowledge.capture_assertion_spans SET span_id = :replacement "
                "WHERE assertion_id = :assertion_id AND span_id = :span_id",
            ),
            (
                "capture_assertion_spans",
                "DELETE",
                "DELETE FROM knowledge.capture_assertion_spans "
                "WHERE assertion_id = :assertion_id AND span_id = :span_id",
            ),
            (
                "capture_proposals",
                "DELETE",
                "DELETE FROM knowledge.capture_proposals WHERE proposal_id = :proposal_id",
            ),
            (
                "capture_assertions",
                "DELETE",
                "DELETE FROM knowledge.capture_assertions WHERE assertion_id = :assertion_id",
            ),
        )
        bindings = {
            **promoted,
            "replacement": _identifier("span", 999),
        }
        for table, operation, statement in attempts:
            with pytest.raises(DBAPIError) as refused, engine.begin() as connection:
                connection.execute(text(statement), bindings)
            assert "retains lineage" in str(refused.value), (table, operation)

        with engine.connect() as connection:
            for table, before in lineage_before.items():
                assert _row_snapshot(connection, table) == before, table
            proposal = connection.execute(
                text(
                    f"SELECT state, accepted_record_type, accepted_record_id "  # noqa: S608
                    f"FROM {SCHEMA}.capture_proposals WHERE proposal_id = :proposal_id"
                ),
                promoted,
            ).one()
            assertion = connection.execute(
                text(
                    f"SELECT state, proposal_id, decision_id FROM {SCHEMA}.capture_assertions "  # noqa: S608
                    "WHERE assertion_id = :assertion_id"
                ),
                promoted,
            ).one()
            proposal_links = connection.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.capture_proposal_spans "  # noqa: S608
                    "WHERE proposal_id = :proposal_id"
                ),
                promoted,
            ).scalar_one()
            assertion_links = connection.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.capture_assertion_spans "  # noqa: S608
                    "WHERE assertion_id = :assertion_id"
                ),
                promoted,
            ).scalar_one()
        assert tuple(proposal) == ("accepted", "assertion", promoted["assertion_id"])
        assert tuple(assertion) == ("accepted", promoted["proposal_id"], promoted["decision_id"])
        assert proposal_links == assertion_links == 2

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
@pytest.mark.parametrize("table", tuple(IMMUTABLE))
def test_review_evidence_accepts_inserts_but_refuses_updates_and_deletes(
    disposable_database: str, table: str
) -> None:
    """Review cases, decisions and receipts are immutable at the server.

    Two complete promotion lineages are inserted successfully, so each refusal
    is measured against a reachable, non-empty table and does not discharge
    vacuously over a table that accepts no writes.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.begin() as connection:
            _seed_receipt(connection, _seed_promotion(connection, _seed_proposal(connection, 1), 1))

        with engine.connect() as connection:
            first = _row_snapshot(connection, table)

        with pytest.raises(DBAPIError) as deleted, engine.begin() as connection:
            connection.execute(text(f"DELETE FROM {SCHEMA}.{table}"))  # noqa: S608
        assert "retains lineage" in str(deleted.value)
        with engine.connect() as connection:
            assert _row_snapshot(connection, table) == first

        with engine.begin() as connection:
            _seed_receipt(connection, _seed_promotion(connection, _seed_proposal(connection, 2), 2))

        with engine.connect() as connection:
            before_update = _row_snapshot(connection, table)

        with pytest.raises(DBAPIError) as updated, engine.begin() as connection:
            connection.execute(
                text(f"UPDATE {SCHEMA}.{table} SET {IMMUTABLE[table]} = now()")  # noqa: S608
            )
        assert "retains lineage" in str(updated.value)
        with engine.connect() as connection:
            assert _row_snapshot(connection, table) == before_update

        with engine.connect() as connection:
            assert (
                connection.execute(
                    text(f"SELECT count(*) FROM {SCHEMA}.{table}")  # noqa: S608
                ).scalar_one()
                == 2
            )

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_one_active_context_link_per_capture_target_and_role(
    disposable_database: str,
) -> None:
    """`09_LOGICAL_DATA_MODEL.md:124`'s unique active link, as a partial index.

    Both halves, because a unique index that refused the second row
    unconditionally would satisfy the first: a second active link to the same
    target in the same role is refused, and the same row is admitted once the
    first has been superseded.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.begin() as connection:
            ids = _seed_proposal(connection)

        insert = text(
            f"INSERT INTO {SCHEMA}.capture_context_links (capture_context_link_id, capture_id, "  # noqa: S608
            "target_type, target_id, link_role, authority_state) VALUES (:link, :capture_id, "
            "'source_object', :target, 'launch_context', 'deterministic')"
        )
        binding = {**ids, "target": _identifier("obj", 1)}
        with engine.begin() as connection:
            connection.execute(insert, {**binding, "link": _identifier("clink", 1)})

        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.execute(insert, {**binding, "link": _identifier("clink", 2)})

        with engine.begin() as connection:
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.capture_context_links SET authority_state = 'superseded', "  # noqa: S608
                    "superseded_at = now() WHERE capture_context_link_id = :link"
                ),
                {"link": _identifier("clink", 1)},
            )
            connection.execute(insert, {**binding, "link": _identifier("clink", 3)})

        with engine.connect() as connection:
            live = connection.execute(
                text(
                    f"SELECT count(*) FROM {SCHEMA}.capture_context_links "  # noqa: S608
                    "WHERE superseded_at IS NULL"
                )
            ).scalar_one()
            total = connection.execute(
                text(f"SELECT count(*) FROM {SCHEMA}.capture_context_links")  # noqa: S608
            ).scalar_one()
        assert (live, total) == (1, 2)

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_the_frozen_literals_are_what_the_server_stores(
    disposable_database: str,
) -> None:
    """The freeze reaches the database, not only the `Table` copy in the file.

    `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`
    reads this revision's declaration; this reads what PostgreSQL ended up with,
    which is the only thing a row is ever checked against. The control is the
    inequality: the eight sets are not all the same, so eight passing reads
    cannot be one read repeated.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.connect() as connection:
            stored = {
                name: frozenset(re.findall(r"'([^']+)'::text", definition))
                for name, definition in connection.execute(
                    text(
                        "SELECT con.conname, pg_get_constraintdef(con.oid) FROM pg_constraint con "
                        "JOIN pg_class rel ON rel.oid = con.conrelid "
                        "JOIN pg_namespace n ON n.oid = rel.relnamespace "
                        "WHERE n.nspname = :schema AND rel.relname = ANY(:tables) "
                        "AND con.contype = 'c'"
                    ),
                    {"schema": SCHEMA, "tables": sorted(REVIEW_TABLES)},
                ).all()
            }
        assert stored["review_disposition_is_known"] == frozenset(
            {
                "accept",
                "correct_and_accept",
                "reject",
                "defer",
                "mark_unresolved",
                "reprocess",
                "escalate",
            }
        )
        assert stored["assertion_state_is_known"] == frozenset(
            {
                "proposed",
                "accepted",
                "contradicted",
                "stale",
                "superseded",
                "withdrawn",
                "revalidation_required",
            }
        )
        assert stored["context_link_authority_state_is_known"] == frozenset(
            {"deterministic", "user_confirmed", "proposed", "rejected", "superseded"}
        )
        assert stored["conversation_event_state_is_known"] == frozenset(
            {"skeletal", "proposed", "accepted", "superseded", "archived"}
        )
        assert stored["context_link_role_is_known"] == frozenset({"launch_context"})
        assert stored["context_link_target_type_is_known"] == frozenset({"source_object"})
        assert stored["conversation_channel_is_known"] == frozenset({"unknown"})
        assert stored["assertion_type_is_known"] == frozenset(
            {"task", "commitment", "decision", "follow_up", "open_question", "risk", "issue"}
        )
        assert len({stored[name] for name in stored if name.endswith("_is_known")}) >= 6

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_an_acceptance_creates_one_assertion_receipt_and_revalidation_obligation(
    disposable_database: str,
) -> None:
    """QC-AC-020 and ADR-003 clause 8 through the real persistence functions."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.begin() as connection:
            ids = _seed_proposal(connection, ordinal=31)
            review_case_id = open_review_case(connection, ids["proposal_id"])
            assert review_case_id is not None
            state = connection.execute(
                text(
                    f"SELECT state FROM {SCHEMA}.capture_proposals "  # noqa: S608
                    "WHERE proposal_id = :proposal_id"
                ),
                ids,
            ).scalar_one()
            assert state == ProposalState.NEEDS_REVIEW.value

            decision = decide_review(
                connection,
                _decision_request(
                    review_case_id,
                    expected=0,
                    disposition=Disposition.CORRECT_AND_ACCEPT,
                    corrected_value="synthetic corrected commitment",
                ),
            )
            assert decision is not None
            assert decision.assertion_id is not None
            assert decision.receipt_id is not None
            persisted = connection.execute(
                text(
                    f"SELECT a.state, a.normalized_value, r.policy_version "  # noqa: S608
                    f"FROM {SCHEMA}.capture_assertions a "
                    f"JOIN {SCHEMA}.capture_promotion_receipts r "
                    "ON r.assertion_id = a.assertion_id WHERE a.assertion_id = :assertion_id"
                ),
                {"assertion_id": decision.assertion_id},
            ).one()
            assert tuple(persisted) == (
                AssertionState.ACCEPTED.value,
                "synthetic corrected commitment",
                "policy-v1",
            )

            unchanged = mark_changed_assertions_for_revalidation(
                connection,
                prior_version_id=ids["version_id"],
                successor_content="x",
                at=datetime(2026, 8, 4, 12, 1, tzinfo=UTC),
            )
            assert unchanged == 0
            second_version_id = _identifier("capver", 33)
            connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.capture_versions "  # noqa: S608
                    "(version_id, capture_id, version_number, supersedes_version_id, content, "
                    "content_sha256, owner_principal_id, classification, processing_policy, "
                    "idempotency_key, correlation_id, audit_id, server_received_at, "
                    "accepted_at, recorded_at) VALUES (:version_id, :capture_id, 2, "
                    ":prior_version_id, 'x', :digest, :principal_id, 'synthetic_test', "
                    "'local_only', :version_id, :correlation_id, :audit_id, now(), now(), now())"
                ),
                {
                    **ids,
                    "version_id": second_version_id,
                    "prior_version_id": ids["version_id"],
                    "digest": digest_of("x"),
                },
            )
            changed = mark_changed_assertions_for_revalidation(
                connection,
                prior_version_id=second_version_id,
                successor_content="y",
                at=datetime(2026, 8, 4, 12, 2, tzinfo=UTC),
            )
            assert changed == 1
            assertion_state = connection.execute(
                text(
                    f"SELECT state FROM {SCHEMA}.capture_assertions "  # noqa: S608
                    "WHERE assertion_id = :assertion_id"
                ),
                {"assertion_id": decision.assertion_id},
            ).scalar_one()
            assert assertion_state == AssertionState.REVALIDATION_REQUIRED.value
    finally:
        engine.dispose()


@pytest.mark.database
def test_rejection_retains_lineage_and_a_stale_second_decision_is_refused(
    disposable_database: str,
) -> None:
    """QC-AC-022 plus optimistic concurrency against stored decision sequence."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.begin() as connection:
            ids = _seed_proposal(connection, ordinal=32)
            review_case_id = open_review_case(connection, ids["proposal_id"])
            assert review_case_id is not None
            rejected = decide_review(
                connection,
                _decision_request(
                    review_case_id,
                    expected=0,
                    disposition=Disposition.REJECT,
                ),
            )
            assert rejected is not None
            assert rejected.proposal_state is ProposalState.REJECTED
            with pytest.raises(ReviewConflictError, match="stale"):
                decide_review(
                    connection,
                    _decision_request(
                        review_case_id,
                        expected=0,
                        disposition=Disposition.DEFER,
                    ),
                )

            retained = connection.execute(
                text(
                    f"SELECT p.state, count(ps.span_id), count(d.decision_id) "  # noqa: S608
                    f"FROM {SCHEMA}.capture_proposals p "
                    f"JOIN {SCHEMA}.capture_proposal_spans ps ON ps.proposal_id = p.proposal_id "
                    f"JOIN {SCHEMA}.capture_review_cases c ON c.proposal_id = p.proposal_id "
                    f"JOIN {SCHEMA}.capture_review_decisions d "
                    "ON d.review_case_id = c.review_case_id "
                    "WHERE p.proposal_id = :proposal_id GROUP BY p.state"
                ),
                ids,
            ).one()
            assert tuple(retained) == (ProposalState.REJECTED.value, 1, 1)
    finally:
        engine.dispose()


@pytest.mark.database
def test_acceptance_is_terminal_and_every_later_decision_preserves_canonical_rows(
    disposable_database: str,
) -> None:
    """Accept and correct-and-accept close the review-decision lifecycle.

    Every reachable later disposition is attempted with the current expected
    version. The conflict is therefore the terminal-state rule, not optimistic
    concurrency, and the complete proposal/decision/assertion/link/receipt
    snapshot proves the refusal changed nothing.
    """
    engine = create_database_engine(disposable_database)
    later_dispositions = (
        Disposition.REJECT,
        Disposition.DEFER,
        Disposition.MARK_UNRESOLVED,
        Disposition.ACCEPT,
        Disposition.CORRECT_AND_ACCEPT,
    )
    try:
        command.upgrade(_config(), "head")
        with engine.begin() as connection:
            ordinal = 40
            for initial in (Disposition.ACCEPT, Disposition.CORRECT_AND_ACCEPT):
                for later in later_dispositions:
                    ids = _seed_proposal(connection, ordinal=ordinal)
                    ordinal += 1
                    review_case_id = open_review_case(connection, ids["proposal_id"])
                    assert review_case_id is not None
                    accepted = decide_review(
                        connection,
                        _decision_request(
                            review_case_id,
                            expected=0,
                            disposition=initial,
                            corrected_value=(
                                "synthetic corrected value"
                                if initial is Disposition.CORRECT_AND_ACCEPT
                                else None
                            ),
                        ),
                    )
                    assert accepted is not None
                    bound = {**ids, "review_case_id": review_case_id}
                    before = _accepted_case_snapshot(connection, bound)

                    with pytest.raises(ReviewConflictError, match="terminal"):
                        decide_review(
                            connection,
                            _decision_request(
                                review_case_id,
                                expected=1,
                                disposition=later,
                                corrected_value=(
                                    "a later synthetic correction"
                                    if later is Disposition.CORRECT_AND_ACCEPT
                                    else None
                                ),
                            ),
                        )

                    assert _accepted_case_snapshot(connection, bound) == before
    finally:
        engine.dispose()
