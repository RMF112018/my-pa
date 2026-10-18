"""AT-012 (S2 guards): the record lineage S2 integrity guards, on a live server.

The S2 revision (S2 contract section 4) puts the S2 invariants
in the database so they hold for every writer: append-only and TRUNCATE
refusal on the three S2 tables, the replaced Issue/revision commit check, the
closure predecessor trigger and the closure CHECKs, the deferred closure
evidence count, the local-operator closure attestation, the handoff chain,
holder, recording and time-order guards, the member-version CHECK, the
`blocks`, creation-link and resolution-purpose guards, the composite request
link set and the S2 write-request transitions. Each test drives one guard with
direct SQL inserts -- the handoff and composite writers are later work, so their
rows are synthetic, as the S1 integrity tests' were -- and asserts the
SQLSTATE and the guard's own message or constraint name, so a test can only
pass for the reason it names.

`database` tier on a disposable head-migrated clone per test (the digest
rebuild uses a disposable database through the application). Every value is
synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, insert, text
from sqlalchemy.engine import Connection

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.lineage.canonical import evidence_set_digest
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.issues import SqlIssueRepository
from my_pa.infrastructure.persistence.tables import (
    commitments,
    issue_responsibility_events,
    issue_revision_evidence,
    issue_revisions,
    lineage_evidence_anchors,
    lineage_write_request_links,
    lineage_write_requests,
    record_link_heads,
    record_link_revisions,
    record_links,
    situations,
)
from tests.database.lineage_issue_harness import PRINCIPAL
from tests.database.lineage_record_harness import NOTE_BODY, note_anchor
from tests.database.lineage_s2_harness import GATEWAY, S2Runtime, close
from tests.database.test_commitment_entity_counterparty import seed_counterparty_entity
from tests.database.test_lineage_integrity_guards import (
    ALL_TABLES as S1_TABLES,
)
from tests.database.test_lineage_integrity_guards import (
    CHECK,
    RESTRICT,
    WHEN,
    World,
    _link_revision,
    _link_values,
    _note_anchor,
    _refused,
    _revision_values,
    _task,
    _world,
    _write_link,
)

pytestmark = pytest.mark.database

S2_TABLES: Final = (
    "issue_revision_evidence",
    "issue_responsibility_events",
    "lineage_write_request_links",
)
#: The three immutable S2 tables and a column each can be "updated" through.
IMMUTABLE: Final[dict[str, str]] = {
    "issue_revision_evidence": "role",
    "issue_responsibility_events": "reason",
    "lineage_write_request_links": "revision_no",
}
CLOSED_AT: Final = WHEN + timedelta(hours=1)
DIGEST: Final = "d" * 64


# ------------------------------------------------------------------ seeding


def _close_values(world: World, version: int = 2, **overrides: object) -> dict[str, Any]:
    values = _revision_values(world.principal, world.issue, version, "Synthetic issue")
    values.update(
        action="closed",
        state="closed",
        source_capability="issues.close",
        closed_at=CLOSED_AT,
        outcome="Resolved.",
        evidence_count=1,
        evidence_set_digest=DIGEST,
    )
    values.update(overrides)
    return values


def _evidence(world: World, version: int, ordinal: int = 1, **overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "principal_id": world.principal,
        "issue_id": world.issue,
        "version": version,
        "ordinal": ordinal,
        "anchor_id": world.anchor,
        "role": "resolution",
    }
    values.update(overrides)
    return values


def _set_issue(c: Connection, world: World, version: int, state: str, **row: object) -> None:
    c.execute(
        situations.update()
        .where(situations.c.situation_id == world.issue)
        .values(version=version, state=state, **row)
    )


def _close(c: Connection, world: World) -> None:
    """Close the world's Issue: revision 2, its one evidence row, and the row."""
    c.execute(insert(issue_revisions).values(**_close_values(world)))
    c.execute(insert(issue_revision_evidence).values(**_evidence(world, 2)))
    _set_issue(c, world, 2, "closed", closed_at=CLOSED_AT, outcome="Resolved.")


def _commitment(engine: Engine, principal: str, *, created: datetime = WHEN) -> tuple[str, str]:
    """A Commitment of `principal` and its counterparty Entity: `(commitment, entity)`."""
    entity = seed_counterparty_entity(engine, principal)
    commitment_id = issue_identifier(IdKind.COMMITMENT)
    with engine.begin() as connection:
        connection.execute(
            insert(commitments).values(
                commitment_id=commitment_id,
                principal_id=principal,
                counterparty_entity_id=entity,
                direction="owed_to_principal",
                summary="Synthetic commitment",
                origin_evidence_ref="Synthetic origin.",
                opened_at=created,
                created_at=created,
                updated_at=created,
            )
        )
    return commitment_id, entity


def _handoff(
    world: World,
    commitment_id: str,
    sequence: int,
    *,
    from_entity: str | None,
    to_entity: str | None,
    effective: datetime = WHEN,
    recorded: datetime = CLOSED_AT,
    **overrides: object,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "principal_id": world.principal,
        "handoff_id": issue_identifier(IdKind.ISSUE_HANDOFF),
        "issue_id": world.issue,
        "commitment_id": commitment_id,
        "sequence_no": sequence,
        "predecessor_sequence_no": None if sequence == 1 else sequence - 1,
        "from_holder_kind": "principal" if from_entity is None else "entity",
        "from_entity_id": from_entity,
        "to_holder_kind": "principal" if to_entity is None else "entity",
        "to_entity_id": to_entity,
        "effective_at": effective,
        "recorded_at": recorded,
        "evidence_anchor_id": world.anchor,
        "reason": "Synthetic handoff.",
        "acceptance_basis": "user_confirmed",
        "authority_class": "local_operator",
        "decision_channel": "local_cli",
        "source_capability": "issues.handoffs.record",
    }
    values.update(overrides)
    return values


def _composite_member(c: Connection, world: World, task_id: str, capability: str) -> str:
    """An Issue membership of `task_id` written as a composite's ordinal-1 link."""
    link = _link_values(
        world.principal,
        kind="issue_membership",
        relation="issue_member",
        source=("situation", world.issue),
        target=("task", task_id),
        member_role="work",
        context=world.issue,
        source_capability=capability,
    )
    return _write_link(c, link)


def _reserve(c: Connection, world: World, capability: str, key: str) -> None:
    c.execute(
        insert(lineage_write_requests).values(
            principal_id=world.principal,
            capability=capability,
            idempotency_key=key,
            request_digest="a" * 64,
            created_at=WHEN,
        )
    )


def _complete(c: Connection, world: World, capability: str, key: str, **result: object) -> None:
    c.execute(
        lineage_write_requests.update()
        .where(lineage_write_requests.c.principal_id == world.principal)
        .where(lineage_write_requests.c.capability == capability)
        .where(lineage_write_requests.c.idempotency_key == key)
        .values(completed_at=WHEN, **result)
    )


@dataclass(frozen=True)
class S2World:
    """The S1 world plus one row in each S2 table: a closure, a handoff, a composite."""

    base: World
    commitment: str
    entity: str
    composite_task: str


def _s2_world(engine: Engine) -> S2World:
    base = _world(engine)
    commitment_id, entity = _commitment(engine, base.principal)
    with engine.begin() as c:
        _close(c, base)
    with engine.begin() as c:
        c.execute(
            insert(issue_responsibility_events).values(
                **_handoff(base, commitment_id, 1, from_entity=entity, to_entity=None)
            )
        )
    with engine.begin() as c:
        task_id = _task(c, base.principal)
        link = _composite_member(c, base, task_id, "issues.work.create_task")
        _reserve(c, base, "issues.work.create_task", "world-composite")
        c.execute(
            insert(lineage_write_request_links).values(
                principal_id=base.principal,
                capability="issues.work.create_task",
                idempotency_key="world-composite",
                ordinal=1,
                link_id=link,
                revision_no=1,
            )
        )
        _complete(
            c,
            base,
            "issues.work.create_task",
            "world-composite",
            result_record_family="task",
            result_record_id=task_id,
        )
    return S2World(base, commitment_id, entity, task_id)


@pytest.fixture
def s2world(db_engine: Engine) -> Iterator[S2World]:
    yield _s2_world(db_engine)


@pytest.fixture
def world(db_engine: Engine) -> Iterator[World]:
    yield _world(db_engine)


# ------------------------------------------------------------------ tests


@pytest.mark.parametrize("table", sorted(IMMUTABLE))
def test_s2_immutable_tables_refuse_update_and_delete(
    db_engine: Engine, s2world: S2World, table: str
) -> None:
    del s2world
    column = IMMUTABLE[table]
    _refused(
        db_engine,
        lambda c: c.execute(text(f"UPDATE knowledge.{table} SET {column} = {column}")),  # noqa: S608
        RESTRICT,
        f"{table} is append-only",
    )
    _refused(
        db_engine,
        lambda c: c.execute(text(f"DELETE FROM knowledge.{table}")),  # noqa: S608
        RESTRICT,
        f"{table} is append-only",
    )


@pytest.mark.parametrize("table", S2_TABLES)
def test_s2_tables_refuse_truncate(db_engine: Engine, s2world: S2World, table: str) -> None:
    """Each S2 table, holding a row, refuses on its own trigger: every other is disabled."""
    del s2world
    everything = (*S1_TABLES, *S2_TABLES)

    def truncate(c: Connection) -> None:
        for other in everything:
            if other != table:
                c.execute(
                    text(f"ALTER TABLE knowledge.{other} DISABLE TRIGGER {other}_refuse_truncate")
                )
        c.execute(text("TRUNCATE " + ", ".join(f"knowledge.{t}" for t in everything)))

    _refused(db_engine, truncate, RESTRICT, f"{table} refuses TRUNCATE")


def test_an_issue_cannot_close_without_a_matching_revision(db_engine: Engine, world: World) -> None:
    """The replaced commit check compares `closed_at` and `outcome` too."""

    def mismatched(**row: object) -> Any:  # noqa: ANN401
        def statement(c: Connection) -> None:
            c.execute(insert(issue_revisions).values(**_close_values(world)))
            c.execute(insert(issue_revision_evidence).values(**_evidence(world, 2)))
            _set_issue(c, world, 2, "closed", **row)

        return statement

    for row in (
        {"closed_at": CLOSED_AT + timedelta(minutes=1), "outcome": "Resolved."},
        {"closed_at": CLOSED_AT, "outcome": "Something else."},
    ):
        _refused(db_engine, mismatched(**row), CHECK, "an issue matches its revision")
    # The matching row commits.
    with db_engine.begin() as c:
        _close(c, world)


def test_a_closure_revision_follows_the_lifecycle(db_engine: Engine, world: World) -> None:
    def insert_revision(values: dict[str, Any]) -> Any:  # noqa: ANN401
        return lambda c: c.execute(insert(issue_revisions).values(**values))

    base = _revision_values(world.principal, world.issue, 2, "Synthetic issue")
    # A reopening (or correction) needs a closed predecessor.
    reopening = {
        **base,
        "action": "reopened",
        "state": "active",
        "source_capability": "issues.reopen",
        "reason": "Synthetic reason.",
    }
    _refused(
        db_engine,
        insert_revision(reopening),
        RESTRICT,
        "a reopening or correction follows a closed issue revision",
    )
    with db_engine.begin() as c:
        _close(c, world)
    # After a close, only a reopening or a correction follows.
    updated = _revision_values(world.principal, world.issue, 3, "Synthetic issue")
    _refused(
        db_engine,
        insert_revision(updated),
        RESTRICT,
        "a closed issue is only reopened or corrected",
    )
    # A correction keeps the closure it corrects.
    correction = {
        **_revision_values(world.principal, world.issue, 3, "Corrected title"),
        "action": "corrected",
        "state": "closed",
        "closed_at": CLOSED_AT,
        "outcome": "Rewritten outcome.",
    }
    _refused(db_engine, insert_revision(correction), RESTRICT, "a correction keeps the closure")


def test_a_closed_revision_carries_its_closure_fields(db_engine: Engine, world: World) -> None:
    def insert_revision(**overrides: object) -> Any:  # noqa: ANN401
        return lambda c: c.execute(
            insert(issue_revisions).values(**_close_values(world, **overrides))
        )

    for overrides in ({"closed_at": None}, {"outcome": None}):
        _refused(
            db_engine,
            insert_revision(**overrides),
            CHECK,
            "an_issue_revision_closes_exactly_when_closed",
        )
    # A non-closed revision carries neither.
    open_with_outcome = {
        **_revision_values(world.principal, world.issue, 2, "Synthetic issue"),
        "outcome": "Not yet.",
    }
    _refused(
        db_engine,
        lambda c: c.execute(insert(issue_revisions).values(**open_with_outcome)),
        CHECK,
        "an_issue_revision_closes_exactly_when_closed",
    )


def test_a_closing_revision_has_evidence(db_engine: Engine, world: World) -> None:
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(issue_revisions).values(
                **_close_values(world, evidence_count=0, evidence_set_digest=None)
            )
        ),
        CHECK,
        "an_issue_closing_revision_has_evidence",
    )


def test_issue_closure_evidence_is_frozen(db_engine: Engine, world: World) -> None:
    """At commit a revision holds exactly `evidence_count` rows, from either side."""

    # From the revision side: a count with no row.
    def short(c: Connection) -> None:
        c.execute(insert(issue_revisions).values(**_close_values(world)))
        _set_issue(c, world, 2, "closed", closed_at=CLOSED_AT, outcome="Resolved.")

    _refused(db_engine, short, CHECK, "an issue revision holds exactly its evidence count")
    with db_engine.begin() as c:
        _close(c, world)

    # From the evidence side: a row added to a committed revision later.
    second = _note_anchor(world.principal, world.meeting, world.note, passage=(6, 12))

    def added(c: Connection) -> None:
        c.execute(insert(lineage_evidence_anchors).values(**second))
        c.execute(
            insert(issue_revision_evidence).values(
                **_evidence(world, 2, 2, anchor_id=second["anchor_id"], role="corroborates")
            )
        )

    _refused(db_engine, added, CHECK, "an issue revision holds exactly its evidence count")


def test_an_issue_closure_row_is_local_operator_attested(db_engine: Engine, world: World) -> None:
    for authority, channel in (
        ("ordinary_reviewer", "local_cli"),
        ("local_operator", "remote_interactive"),
        ("local_operator", "local_unattested"),
    ):
        _refused(
            db_engine,
            lambda c, a=authority, ch=channel: c.execute(
                insert(issue_revisions).values(
                    **_close_values(world, authority_class=a, decision_channel=ch)
                )
            ),
            CHECK,
            "an_issue_closure_is_operator_attested",
        )
    with db_engine.begin() as c:
        _close(c, world)
    # A correction of a closed Issue is attested too (R2-F10).
    correction = {
        **_revision_values(
            world.principal,
            world.issue,
            3,
            "Corrected title",
            authority="ordinary_reviewer",
            channel="remote_interactive",
        ),
        "action": "corrected",
        "state": "closed",
        "closed_at": CLOSED_AT,
        "outcome": "Resolved.",
    }
    _refused(
        db_engine,
        lambda c: c.execute(insert(issue_revisions).values(**correction)),
        CHECK,
        "an_issue_closure_is_operator_attested",
    )


def _handoff_world(engine: Engine) -> tuple[World, str, str]:
    world = _world(engine)
    commitment_id, entity = _commitment(engine, world.principal)
    return world, commitment_id, entity


def test_a_handoff_follows_its_predecessor_holder(db_engine: Engine) -> None:
    world, commitment_id, entity = _handoff_world(db_engine)
    with db_engine.begin() as c:
        c.execute(
            insert(issue_responsibility_events).values(
                **_handoff(world, commitment_id, 1, from_entity=entity, to_entity=None)
            )
        )
    # Event 2 must leave the Principal, which event 1 reached.
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(issue_responsibility_events).values(
                **_handoff(world, commitment_id, 2, from_entity=entity, to_entity=None)
            )
        ),
        RESTRICT,
        "a handoff leaves the holder its predecessor reached",
    )
    with db_engine.begin() as c:
        c.execute(
            insert(issue_responsibility_events).values(
                **_handoff(world, commitment_id, 2, from_entity=None, to_entity=entity)
            )
        )


def test_a_handoff_changes_its_holder(db_engine: Engine) -> None:
    world, commitment_id, entity = _handoff_world(db_engine)
    for from_entity, to_entity in ((None, None), (entity, entity)):
        _refused(
            db_engine,
            lambda c, f=from_entity, t=to_entity: c.execute(
                insert(issue_responsibility_events).values(
                    **_handoff(world, commitment_id, 1, from_entity=f, to_entity=t)
                )
            ),
            CHECK,
            "a_handoff_changes_its_holder",
        )


def test_a_handoff_cannot_be_effective_after_recording(db_engine: Engine) -> None:
    world, commitment_id, entity = _handoff_world(db_engine)
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(issue_responsibility_events).values(
                **_handoff(
                    world,
                    commitment_id,
                    1,
                    from_entity=entity,
                    to_entity=None,
                    effective=CLOSED_AT + timedelta(seconds=1),
                    recorded=CLOSED_AT,
                )
            )
        ),
        CHECK,
        "a_handoff_is_not_effective_after_recording",
    )


def test_a_handoff_cannot_be_effective_before_its_commitment(db_engine: Engine) -> None:
    world, commitment_id, entity = _handoff_world(db_engine)
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(issue_responsibility_events).values(
                **_handoff(
                    world,
                    commitment_id,
                    1,
                    from_entity=entity,
                    to_entity=None,
                    effective=WHEN - timedelta(days=1),
                )
            )
        ),
        CHECK,
        "a handoff is not effective before its commitment",
    )


def test_a_handoff_cannot_be_effective_before_its_predecessor(db_engine: Engine) -> None:
    world, commitment_id, entity = _handoff_world(db_engine)
    later = WHEN + timedelta(minutes=30)
    with db_engine.begin() as c:
        c.execute(
            insert(issue_responsibility_events).values(
                **_handoff(
                    world, commitment_id, 1, from_entity=entity, to_entity=None, effective=later
                )
            )
        )
    # After the Commitment's creation, but before event 1: refused by the
    # predecessor clause alone.
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(issue_responsibility_events).values(
                **_handoff(
                    world,
                    commitment_id,
                    2,
                    from_entity=None,
                    to_entity=entity,
                    effective=WHEN + timedelta(minutes=10),
                )
            )
        ),
        CHECK,
        "a handoff is not effective before its predecessor",
    )


def test_a_member_native_version_is_recorded_only_by_membership_writes(
    db_engine: Engine, world: World
) -> None:
    # A semantic revision (an association correction) carries no member version.
    correction = _link_revision(
        world.principal,
        world.origin,
        2,
        "correct_evidence",
        evidence_count=0,
        member_native_version=1,
    )
    _refused(
        db_engine,
        lambda c: c.execute(insert(record_link_revisions).values(**correction)),
        CHECK,
        "only_membership_writes_record_a_member_version",
    )
    zero = _link_revision(
        world.principal,
        world.membership,
        2,
        "correct_evidence",
        source_capability="issues.memberships.correct",
        member_native_version=0,
    )
    _refused(
        db_engine,
        lambda c: c.execute(insert(record_link_revisions).values(**zero)),
        CHECK,
        "a_member_native_version_is_positive",
    )


def test_a_blocks_root_cannot_name_itself(db_engine: Engine, world: World) -> None:
    link = _link_values(
        world.principal,
        kind="semantic",
        relation="blocks",
        source=("task", world.task),
        target=("task", world.task),
    )
    _refused(db_engine, lambda c: _write_link(c, link), CHECK, "a_blocks_link_names_two_records")


def test_a_creation_link_needs_its_composite(db_engine: Engine, world: World) -> None:
    commitment_id, _ = _commitment(db_engine, world.principal)
    for overrides in (
        # Asserted, not written by its composite.
        {
            "relation": "delegated_from",
            "capability": "records.associations.assert",
            "context": world.issue,
        },
        # The Task composite cannot write a delegation.
        {
            "relation": "delegated_from",
            "capability": "issues.work.create_task",
            "context": world.issue,
        },
        # No Issue context.
        {
            "relation": "created_to_resolve",
            "capability": "issues.work.create_task",
            "context": None,
        },
    ):
        source = (
            ("commitment", commitment_id)
            if overrides["relation"] == "delegated_from"
            else (
                "task",
                world.task,
            )
        )
        target = (
            ("task", world.task)
            if overrides["relation"] == "delegated_from"
            else (
                "situation",
                world.issue,
            )
        )
        link = _link_values(
            world.principal,
            kind="semantic",
            relation=str(overrides["relation"]),
            source=source,
            target=target,
            context=overrides["context"],  # type: ignore[arg-type]
            source_capability=overrides["capability"],
        )
        _refused(
            db_engine,
            lambda c, link=link: _write_link(c, link),
            CHECK,
            "a_creation_link_is_written_by_its_composite",
        )


def test_created_to_resolve_revision_one_states_its_purpose(
    db_engine: Engine, world: World
) -> None:
    link = _link_values(
        world.principal,
        kind="semantic",
        relation="created_to_resolve",
        source=("task", world.task),
        target=("situation", world.issue),
        context=world.issue,
        source_capability="issues.work.create_task",
    )
    _refused(db_engine, lambda c: _write_link(c, link), CHECK, "states its purpose")

    def purposeful(c: Connection) -> None:
        c.execute(insert(record_links).values(**link))
        c.execute(
            insert(record_link_revisions).values(
                **_link_revision(
                    world.principal,
                    link["link_id"],
                    1,
                    "assert",
                    source_capability="issues.work.create_task",
                    reason="Created to resolve the Issue.",
                )
            )
        )
        c.execute(
            insert(record_link_heads).values(
                principal_id=world.principal,
                link_id=link["link_id"],
                revision_no=1,
                lifecycle_state="active",
                normalized_identity=link["normalized_identity"],
            )
        )

    with db_engine.begin() as c:
        purposeful(c)


def test_a_composite_request_names_its_record_and_links(db_engine: Engine, world: World) -> None:
    capability = "issues.work.create_task"
    with db_engine.begin() as c:
        task_id = _task(c, world.principal)
        member = _composite_member(c, world, task_id, capability)
        other_task = _task(c, world.principal)
        other = _composite_member(c, world, other_task, capability)

    def completed(key: str, links: tuple[tuple[int, str], ...], record: str = task_id) -> Any:  # noqa: ANN401
        def statement(c: Connection) -> None:
            _reserve(c, world, capability, key)
            for ordinal, link_id in links:
                c.execute(
                    insert(lineage_write_request_links).values(
                        principal_id=world.principal,
                        capability=capability,
                        idempotency_key=key,
                        ordinal=ordinal,
                        link_id=link_id,
                        revision_no=1,
                    )
                )
            _complete(
                c, world, capability, key, result_record_family="task", result_record_id=record
            )

        return statement

    needle = "a completed composite request names its membership and its links"
    # No link at all; ordinal 1 naming another record's membership; a gap.
    _refused(db_engine, completed("composite-a", ()), CHECK, needle)
    _refused(db_engine, completed("composite-b", ((1, other),)), CHECK, needle)
    _refused(db_engine, completed("composite-c", ((1, member), (3, world.origin))), CHECK, needle)
    with db_engine.begin() as c:
        completed("composite-d", ((1, member), (2, world.origin)))(c)


def test_an_s2_write_request_completes_once(db_engine: Engine, world: World) -> None:
    commitment_id, entity = _commitment(db_engine, world.principal)
    handoff = _handoff(world, commitment_id, 1, from_entity=entity, to_entity=None)
    capability = "issues.handoffs.record"
    # A reservation names no result, S2 columns included.
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(lineage_write_requests).values(
                principal_id=world.principal,
                capability=capability,
                idempotency_key="handoff-reserved",
                request_digest="a" * 64,
                created_at=WHEN,
                result_handoff_id=handoff["handoff_id"],
            )
        ),
        CHECK,
        "an_incomplete_lineage_write_request_names_no_result",
    )
    with db_engine.begin() as c:
        c.execute(insert(issue_responsibility_events).values(**handoff))
        _reserve(c, world, capability, "handoff-once")
        _complete(c, world, capability, "handoff-once", result_handoff_id=handoff["handoff_id"])
    # A completed handoff request names only its event.
    _refused(
        db_engine,
        lambda c: (
            _reserve(c, world, capability, "handoff-two"),
            _complete(
                c,
                world,
                capability,
                "handoff-two",
                result_handoff_id=handoff["handoff_id"],
                result_issue_id=world.issue,
                result_issue_version=1,
            ),
        ),
        CHECK,
        "a_completed_handoff_write_names_its_event",
    )
    # It completes once: the S2 result columns are fixed with the rest.
    _refused(
        db_engine,
        lambda c: _complete(c, world, capability, "handoff-once", result_handoff_id=None),
        RESTRICT,
        "a lineage write request completes once",
    )


def test_closure_evidence_digest_rebuilds_from_stored_rows(disposable_database: str) -> None:
    runtime = S2Runtime(disposable_database)
    try:
        issue = runtime.issue("digest")
        meeting_id, note_id, anchor = runtime.evidence_source("digest")
        second = note_anchor(
            meeting_id, note_id, NOTE_BODY, role="corroborates", passage="Next: pour"
        )
        runtime.ok(close(issue, 1, "digest", (anchor, second)), surface=GATEWAY)
        with runtime.engine.connect() as connection:
            revision = SqlIssueRepository(connection).read_issue_revision(PRINCIPAL, issue, 2)
        assert revision is not None
        assert len(revision.evidence) == 2
        assert [cited.anchor.role.value for cited in revision.evidence] in (
            ["corroborates", "resolution"],
            ["resolution", "corroborates"],
        )
        assert revision.evidence_set_digest == evidence_set_digest(
            cited.anchor for cited in revision.evidence
        )
    finally:
        runtime.close()
