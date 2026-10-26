"""The record lineage S3.1 database guards, on a live server (S3.1 contract section 5).

The S3.1 revision replaces the S1-S3 local-operator CHECK on the
fact tables and the roots with the provenance rule, bounds the client id,
admits the human channel's `confirm` revision and Project-link event only after
a `client_identified` predecessor (keeping its state, evidence and member
version), records each write request's writer once, and checks a schema-2
report manifest's `lineage` section. Each test drives one guard with direct SQL
and asserts the SQLSTATE and the guard's own message or constraint name, so a
test can only pass for the reason it names.

`database` tier on a disposable head-migrated clone per test. Every value is
synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from datetime import timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, insert, text, update
from sqlalchemy.engine import Connection

from my_pa.infrastructure.persistence.tables import (
    issue_project_membership_events,
    issue_responsibility_corrections,
    issue_responsibility_events,
    lineage_write_requests,
    record_link_revision_evidence,
    record_link_revisions,
    record_links,
)
from tests.database.test_lineage_integrity_guards import (
    CHECK,
    EMPTY_SET_DIGEST,
    RESTRICT,
    WHEN,
    World,
    _advance_head,
    _link_revision,
    _link_values,
    _membership_event,
    _refused,
    _task,
    _world,
)
from tests.database.test_lineage_s2_integrity_guards import _commitment, _handoff
from tests.database.test_lineage_s3_integrity_guards import _correction
from tests.database.test_lineage_s4_integrity_guards import _committed, _copy_artifact, _digest

pytestmark = pytest.mark.database

CLIENT: Final = "client-s31-guard"
PROVENANCE: Final = "a_lineage_row_provenance_is_consistent"
FOLLOWS: Final = "a link revision follows an active predecessor"
EVENT_FOLLOWS: Final = "a membership event follows a predecessor it can follow"

#: The client provenance of a remote client and of an unstamped local caller.
REMOTE: Final[dict[str, Any]] = {
    "acceptance_basis": "client_identified",
    "authority_class": "ordinary_reviewer",
    "decision_channel": "remote_interactive",
    "asserting_client_id": CLIENT,
}
UNSTAMPED: Final[dict[str, Any]] = {
    "acceptance_basis": "client_identified",
    "authority_class": "ordinary_reviewer",
    "decision_channel": "local_unattested",
    "asserting_client_id": None,
}
#: Section 5.1: every pair the provenance CHECK refuses, as overrides of an
#: otherwise-valid operator row.
INCONSISTENT: Final[tuple[dict[str, Any], ...]] = (
    {"acceptance_basis": "user_confirmed", "authority_class": "ordinary_reviewer"},
    {"acceptance_basis": "user_confirmed", "decision_channel": "remote_interactive"},
    {"acceptance_basis": "user_confirmed", "asserting_client_id": CLIENT},
    {"acceptance_basis": "user_confirmed", "user_directed_claim": True},
    {"acceptance_basis": "client_identified"},
    {**REMOTE, "authority_class": "local_operator"},
    {**REMOTE, "asserting_client_id": None},
    {**REMOTE, "decision_channel": "local_cli"},
    {**UNSTAMPED, "asserting_client_id": CLIENT},
    {**UNSTAMPED, "authority_class": "remote_operator_attested"},
)


@pytest.fixture
def world(db_engine: Engine) -> Iterator[World]:
    yield _world(db_engine)


# ------------------------------------------------------------------ seeding


def _client_link(
    c: Connection,
    world: World,
    *,
    relation: str = "discusses",
    source: tuple[str, str] | None = None,
    target: tuple[str, str] | None = None,
    provenance: dict[str, Any] = REMOTE,
    anchored: bool = False,
    member_version: int | None = None,
) -> str:
    """A link a connected client asserted: root, revision 1, evidence and head."""
    membership = relation == "issue_member"
    root = _link_values(
        world.principal,
        kind="issue_membership" if membership else "semantic",
        relation=relation,
        source=source or ("meeting", world.meeting),
        target=target or ("task", world.task),
        member_role="work" if membership else None,
        context=world.issue if membership else None,
        authority_class=provenance["authority_class"],
        decision_channel=provenance["decision_channel"],
    )
    c.execute(insert(record_links).values(**root))
    c.execute(
        insert(record_link_revisions).values(
            **_link_revision(
                world.principal,
                root["link_id"],
                1,
                "assert",
                evidence_count=1 if anchored else 0,
                source_capability=root["source_capability"],
                member_native_version=member_version,
                user_directed_claim=True,
                **provenance,
            )
        )
    )
    if anchored:
        c.execute(
            insert(record_link_revision_evidence).values(
                principal_id=world.principal,
                link_id=root["link_id"],
                revision_no=1,
                ordinal=1,
                anchor_id=world.anchor,
                role="discussion",
            )
        )
    c.execute(
        text(
            "INSERT INTO knowledge.record_link_heads (principal_id, link_id, revision_no, "
            "lifecycle_state, normalized_identity) VALUES (:p, :l, 1, 'active', :i)"
        ),
        {"p": world.principal, "l": root["link_id"], "i": root["normalized_identity"]},
    )
    return str(root["link_id"])


def _confirm(
    world: World,
    link_id: str,
    number: int,
    state: str,
    *,
    capability: str = "records.associations.confirm",
    anchored: bool = False,
    **overrides: object,
) -> Callable[[Connection], None]:
    """The human channel's `confirm` revision `number`, advancing the head."""
    row = _link_revision(
        world.principal,
        link_id,
        number,
        "correct_evidence",
        evidence_count=1 if anchored else 0,
    )
    row.update(action="confirm", lifecycle_state=state, source_capability=capability)
    row.update(overrides)

    def statement(c: Connection) -> None:
        c.execute(insert(record_link_revisions).values(**row))
        if row["evidence_count"]:
            c.execute(
                insert(record_link_revision_evidence).values(
                    principal_id=world.principal,
                    link_id=link_id,
                    revision_no=number,
                    ordinal=1,
                    anchor_id=world.anchor,
                    role="discussion",
                )
            )
        _advance_head(c, world.principal, link_id, number, state)

    return statement


def _revise(
    world: World,
    link_id: str,
    number: int,
    action: str,
    state: str,
    **overrides: object,
) -> Callable[[Connection], None]:
    """Any other revision `number` of `link_id`, advancing the head."""
    capability = {
        "end": "records.associations.end",
        "correct_evidence": "records.associations.correct",
        "contest": "records.associations.contest",
    }[action]
    row = _link_revision(world.principal, link_id, number, "end")
    row.update(action=action, lifecycle_state=state, source_capability=capability)
    row.update(overrides)

    def statement(c: Connection) -> None:
        c.execute(insert(record_link_revisions).values(**row))
        _advance_head(c, world.principal, link_id, number, state)

    return statement


def _event(world: World, number: int, kind: str, **overrides: object) -> dict[str, Any]:
    row = _membership_event(world.principal, world.project, world.issue, number, kind)
    row.update(overrides)
    return row


# ------------------------------------------------------------------ provenance


def test_a_lineage_row_provenance_is_consistent(db_engine: Engine, world: World) -> None:
    commitment_id, entity = _commitment(db_engine, world.principal)
    handoff = _handoff(world, commitment_id, 1, from_entity=entity, to_entity=None)
    with db_engine.begin() as c:
        c.execute(insert(issue_responsibility_events).values(**handoff))
    handoff_id = str(handoff["handoff_id"])
    rows: dict[str, Callable[[dict[str, Any]], Callable[[Connection], object]]] = {
        "record_link_revisions": lambda o: (
            lambda c: c.execute(
                insert(record_link_revisions).values(
                    **_link_revision(world.principal, world.membership, 2, "end", **o)
                )
            )
        ),
        "issue_project_membership_events": lambda o: (
            lambda c: c.execute(
                insert(issue_project_membership_events).values(**_event(world, 2, "end", **o))
            )
        ),
        "issue_responsibility_events": lambda o: (
            lambda c: c.execute(
                insert(issue_responsibility_events).values(
                    **_handoff(world, commitment_id, 2, from_entity=None, to_entity=entity, **o)
                )
            )
        ),
        "issue_responsibility_corrections": lambda o: (
            lambda c: c.execute(
                insert(issue_responsibility_corrections).values(
                    **_correction(world, handoff_id, 1, "void", **o)
                )
            )
        ),
    }
    for row in rows.values():
        for overrides in INCONSISTENT:
            _refused(db_engine, row(overrides), CHECK, PROVENANCE)
    # Each fact table admits the human channel and both client shapes. The
    # remote client's row carries its client id and its unverified claim.
    with db_engine.begin() as c:
        c.execute(
            insert(record_link_revisions).values(
                **_link_revision(
                    world.principal, world.membership, 2, "end", user_directed_claim=True, **REMOTE
                )
            )
        )
        _advance_head(c, world.principal, world.membership, 2, "ended")
    with db_engine.begin() as c:
        c.execute(
            insert(issue_project_membership_events).values(**_event(world, 2, "end", **UNSTAMPED))
        )
    with db_engine.begin() as c:
        c.execute(
            insert(issue_responsibility_corrections).values(
                **_correction(world, handoff_id, 1, "void", user_directed_claim=True, **REMOTE)
            )
        )
    with db_engine.begin() as c:
        c.execute(
            insert(issue_responsibility_events).values(
                **_handoff(world, commitment_id, 2, from_entity=None, to_entity=entity, **UNSTAMPED)
            )
        )
    with db_engine.connect() as c:
        stored = c.execute(
            text(
                "SELECT acceptance_basis, decision_channel, asserting_client_id, "
                "user_directed_claim FROM knowledge.record_link_revisions "
                "WHERE principal_id = :p AND link_id = :l AND revision_no = 2"
            ),
            {"p": world.principal, "l": world.membership},
        ).one()
    assert tuple(stored) == ("client_identified", "remote_interactive", CLIENT, True)


def test_a_record_link_creator_is_known(db_engine: Engine, world: World) -> None:
    for authority, channel in (
        ("ordinary_reviewer", "local_cli"),
        ("ordinary_reviewer", "local_web"),
        ("local_operator", "remote_interactive"),
        ("local_operator", "local_unattested"),
        ("remote_operator_attested", "remote_operator_review"),
    ):
        _refused(
            db_engine,
            lambda c, a=authority, ch=channel: c.execute(
                insert(record_links).values(
                    **_link_values(
                        world.principal,
                        kind="semantic",
                        relation="discusses",
                        source=("meeting", world.meeting),
                        target=("task", world.task),
                        authority_class=a,
                        decision_channel=ch,
                    )
                )
            ),
            CHECK,
            "a_record_link_creator_is_known",
        )
    # Both client shapes create a root, and its client is revision 1's.
    with db_engine.begin() as c:
        _client_link(c, world, provenance=REMOTE)
    with db_engine.begin() as c:
        _client_link(c, world, source=("meeting_note_version", world.note), provenance=UNSTAMPED)


def test_an_asserting_client_is_bounded(db_engine: Engine, world: World) -> None:
    for client in ("", "c" * 257):
        _refused(
            db_engine,
            lambda c, client=client: c.execute(
                insert(record_link_revisions).values(
                    **_link_revision(
                        world.principal,
                        world.membership,
                        2,
                        "end",
                        **{**REMOTE, "asserting_client_id": client},
                    )
                )
            ),
            CHECK,
            "an_asserting_client_is_bounded",
        )
        _refused(
            db_engine,
            lambda c, client=client: c.execute(
                insert(issue_project_membership_events).values(
                    **_event(world, 2, "end", **{**REMOTE, "asserting_client_id": client})
                )
            ),
            CHECK,
            "an_asserting_client_is_bounded",
        )
    # 256 characters is the bound itself.
    with db_engine.begin() as c:
        c.execute(
            insert(record_link_revisions).values(
                **_link_revision(
                    world.principal,
                    world.membership,
                    2,
                    "end",
                    **{**REMOTE, "asserting_client_id": "c" * 256},
                )
            )
        )
        _advance_head(c, world.principal, world.membership, 2, "ended")


# ------------------------------------------------------------------ confirmation


def test_a_confirmation_is_operator_attested(db_engine: Engine, world: World) -> None:
    with db_engine.begin() as c:
        link = _client_link(c, world)
    _refused(
        db_engine,
        _confirm(world, link, 2, "active", **UNSTAMPED),
        CHECK,
        "a_confirmation_is_operator_attested",
    )
    with db_engine.begin() as c:
        c.execute(
            insert(issue_project_membership_events).values(**_event(world, 2, "end", **REMOTE))
        )
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(issue_project_membership_events).values(
                **_event(
                    world,
                    3,
                    "end",
                    action="confirm",
                    state="ended",
                    source_capability="issues.project_links.confirm",
                    **UNSTAMPED,
                )
            )
        ),
        CHECK,
        "a_confirmation_is_operator_attested",
    )
    # A confirm states its reason, on both tables.
    _refused(db_engine, _confirm(world, link, 2, "active", reason=None), CHECK, "reason")
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(issue_project_membership_events).values(
                **_event(
                    world,
                    3,
                    "end",
                    action="confirm",
                    state="ended",
                    reason=None,
                    source_capability="issues.project_links.confirm",
                )
            )
        ),
        CHECK,
        "a_project_link_confirmation_states_its_reason",
    )
    # The human channel's confirm is admitted.
    with db_engine.begin() as c:
        _confirm(world, link, 2, "active")(c)


def test_a_confirmation_follows_a_client_head_and_keeps_its_state(
    db_engine: Engine, world: World
) -> None:
    # An operator head (`world.origin`, user_confirmed) is never confirmed.
    _refused(
        db_engine, _confirm(world, world.origin, 2, "active", anchored=True), RESTRICT, FOLLOWS
    )
    with db_engine.begin() as c:
        link = _client_link(c, world)
    # A confirm keeps its predecessor's state.
    _refused(db_engine, _confirm(world, link, 2, "ended"), RESTRICT, FOLLOWS)
    with db_engine.begin() as c:
        _confirm(world, link, 2, "active")(c)
    # A confirmed head is user_confirmed: it is never confirmed again.
    _refused(db_engine, _confirm(world, link, 3, "active"), RESTRICT, FOLLOWS)
    # A client's contested head is not confirmed (the human ends it instead).
    with db_engine.begin() as c:
        contested = _client_link(c, world, source=("meeting_note_version", world.note))
    with db_engine.begin() as c:
        _revise(world, contested, 2, "contest", "contested", evidence_count=0, **UNSTAMPED)(c)
    for state in ("contested", "active"):
        _refused(db_engine, _confirm(world, contested, 3, state), RESTRICT, FOLLOWS)
    # A client's end: `ended` stays terminal for every action but the confirm,
    # which keeps it ended.
    with db_engine.begin() as c:
        ended = _client_link(
            c,
            world,
            relation="blocks",
            source=("task", world.task),
            target=("task", _task(c, world.principal)),
        )
    with db_engine.begin() as c:
        _revise(world, ended, 2, "end", "ended", **REMOTE)(c)
    _refused(db_engine, _revise(world, ended, 3, "correct_evidence", "active"), RESTRICT, FOLLOWS)
    _refused(db_engine, _confirm(world, ended, 3, "active"), RESTRICT, FOLLOWS)
    with db_engine.begin() as c:
        _confirm(world, ended, 3, "ended")(c)
    _refused(db_engine, _revise(world, ended, 4, "end", "ended"), RESTRICT, FOLLOWS)


def test_a_confirmation_keeps_its_evidence_and_member_version(
    db_engine: Engine, world: World
) -> None:
    with db_engine.begin() as c:
        anchored = _client_link(c, world, anchored=True)
    # The empty set, or the same count under another digest, is not the head's.
    _refused(db_engine, _confirm(world, anchored, 2, "active"), RESTRICT, FOLLOWS)
    _refused(
        db_engine,
        _confirm(world, anchored, 2, "active", anchored=True, evidence_set_digest="f" * 64),
        RESTRICT,
        FOLLOWS,
    )
    # The head's own set, re-cited, is admitted (its count is proved at commit).
    with db_engine.begin() as c:
        _confirm(world, anchored, 2, "active", anchored=True)(c)
    # A membership confirm copies its head's member version: another observed
    # version, or none, is refused; the recorded one is admitted.
    with db_engine.begin() as c:
        member = _client_link(
            c,
            world,
            relation="issue_member",
            source=("situation", world.issue),
            target=("task", world.task),
            member_version=1,
        )
    for observed in (2, None):
        _refused(
            db_engine,
            _confirm(
                world,
                member,
                2,
                "active",
                capability="issues.memberships.confirm",
                member_native_version=observed,
            ),
            RESTRICT,
            FOLLOWS,
        )
    with db_engine.begin() as c:
        _confirm(
            world,
            member,
            2,
            "active",
            capability="issues.memberships.confirm",
            member_native_version=1,
        )(c)
    with db_engine.connect() as c:
        stored = c.execute(
            text(
                "SELECT member_native_version, evidence_set_digest, acceptance_basis "
                "FROM knowledge.record_link_revisions WHERE principal_id = :p AND link_id = :l "
                "ORDER BY revision_no"
            ),
            {"p": world.principal, "l": member},
        ).all()
    assert [tuple(row) for row in stored] == [
        (1, EMPTY_SET_DIGEST, "client_identified"),
        (1, EMPTY_SET_DIGEST, "user_confirmed"),
    ]


def test_a_project_link_confirmation_follows_a_client_event(
    db_engine: Engine, world: World
) -> None:
    def confirm(number: int, state: str, **overrides: object) -> Callable[[Connection], object]:
        return lambda c: c.execute(
            insert(issue_project_membership_events).values(
                **_event(
                    world,
                    number,
                    "end",
                    action="confirm",
                    state=state,
                    reason="Confirmed.",
                    source_capability="issues.project_links.confirm",
                    **overrides,
                )
            )
        )

    # Event 1 is the operator's: it is never confirmed.
    _refused(db_engine, confirm(2, "active"), RESTRICT, EVENT_FOLLOWS)
    with db_engine.begin() as c:
        c.execute(
            insert(issue_project_membership_events).values(**_event(world, 2, "end", **REMOTE))
        )
    # A confirm keeps the client event's state and its evidence anchor.
    _refused(db_engine, confirm(3, "active"), RESTRICT, EVENT_FOLLOWS)
    _refused(
        db_engine, confirm(3, "ended", evidence_anchor_id=world.anchor), RESTRICT, EVENT_FOLLOWS
    )
    with db_engine.begin() as c:
        confirm(3, "ended")(c)
    # The confirmed event is the human channel's: no second confirm.
    _refused(db_engine, confirm(4, "ended"), RESTRICT, EVENT_FOLLOWS)


# ------------------------------------------------------------------ write requests


def _request(**overrides: object) -> dict[str, Any]:
    values: dict[str, Any] = {
        "principal_id": "",
        "capability": "records.associations.end",
        "idempotency_key": "s31-guard-writer",
        "request_digest": "a" * 64,
        "created_at": WHEN,
        "decision_channel": "remote_interactive",
        "asserting_client_id": CLIENT,
    }
    values.update(overrides)
    return values


def test_a_write_request_records_its_writer_once(db_engine: Engine, world: World) -> None:
    p = world.principal
    for writer in (
        {"decision_channel": "remote_interactive", "asserting_client_id": None},
        {"decision_channel": "remote_interactive", "asserting_client_id": ""},
        {"decision_channel": "remote_interactive", "asserting_client_id": "c" * 257},
        {"decision_channel": "local_cli", "asserting_client_id": CLIENT},
        {"decision_channel": "local_unattested", "asserting_client_id": CLIENT},
        {"decision_channel": None, "asserting_client_id": CLIENT},
        {"decision_channel": "remote_operator_review", "asserting_client_id": None},
    ):
        _refused(
            db_engine,
            lambda c, w=writer: c.execute(
                insert(lineage_write_requests).values(**_request(principal_id=p, **w))
            ),
            CHECK,
            "a_lineage_write_request_writer_is_known",
        )
    completion = {
        "completed_at": WHEN + timedelta(seconds=1),
        "result_link_id": world.origin,
        "result_link_revision_no": 1,
    }

    def completing(**writer: object) -> Callable[[Connection], object]:
        def statement(c: Connection) -> None:
            c.execute(insert(lineage_write_requests).values(**_request(principal_id=p)))
            c.execute(
                update(lineage_write_requests)
                .where(lineage_write_requests.c.principal_id == p)
                .where(lineage_write_requests.c.idempotency_key == "s31-guard-writer")
                .values(**completion, **writer)
            )

        return statement

    # The writer is set at reservation and never changes, even when completing.
    for writer in (
        {"decision_channel": "local_cli", "asserting_client_id": None},
        {"asserting_client_id": "client-s31-other"},
        {"decision_channel": None, "asserting_client_id": None},
    ):
        _refused(
            db_engine,
            completing(**writer),
            RESTRICT,
            "a lineage write request changes only by completing",
        )
    with db_engine.begin() as c:
        completing()(c)
    with db_engine.connect() as c:
        stored = c.execute(
            text(
                "SELECT decision_channel, asserting_client_id FROM "
                "knowledge.lineage_write_requests "
                "WHERE principal_id = :p AND idempotency_key = 's31-guard-writer'"
            ),
            {"p": p},
        ).one()
    assert tuple(stored) == ("remote_interactive", CLIENT)


# ------------------------------------------------------------------ manifests


def _lineage_manifest(report_id: str, content: str, version: int, **extra: object) -> str:
    document: dict[str, object] = {
        "manifest_schema_version": version,
        "report": {"report_id": report_id, "content_sha256": content},
        "structured_content": {"present": False, "sha256": None},
        "program": None,
        **extra,
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":"))


def _insert_versioned(
    c: Connection, principal: str, artifact: str, version: int, canonical: str
) -> None:
    c.execute(
        text(
            "INSERT INTO knowledge.intelligence_artifact_manifests (principal_id, artifact_id, "
            "manifest_schema_version, manifest_canonical, manifest_sha256) "
            "VALUES (:p, :a, :v, :canonical, :digest)"
        ),
        {
            "p": principal,
            "a": artifact,
            "v": version,
            "canonical": canonical,
            "digest": _digest(canonical),
        },
    )


def test_a_schema_2_manifest_names_its_lineage_section(db_engine: Engine) -> None:
    principal, source, content = _committed(db_engine)
    misnamed: tuple[tuple[int, dict[str, object]], ...] = (
        # A schema-2 manifest without its `lineage` key, or with a non-object one.
        (2, {}),
        (2, {"lineage": "verified"}),
        (2, {"lineage": [1]}),
        # A schema-1 manifest naming a `lineage` key.
        (1, {"lineage": None}),
        (1, {"lineage": {"verification_state": "not_attempted"}}),
    )
    for version, extra in misnamed:

        def statement(c: Connection, v: int = version, e: dict[str, object] = extra) -> None:
            copy = _copy_artifact(c, principal, source)
            _insert_versioned(c, principal, copy, v, _lineage_manifest(copy, content, v, **e))

        _refused(db_engine, statement, CHECK, "a report manifest names its own artifact")

    # The row's version and the text's must agree.
    def disagreeing(c: Connection) -> None:
        copy = _copy_artifact(c, principal, source)
        _insert_versioned(c, principal, copy, 2, _lineage_manifest(copy, content, 1))

    _refused(db_engine, disagreeing, CHECK, "a report manifest names its own artifact")

    # No third version exists.
    def third(c: Connection) -> None:
        copy = _copy_artifact(c, principal, source)
        _insert_versioned(c, principal, copy, 3, _lineage_manifest(copy, content, 3, lineage=None))

    _refused(db_engine, third, CHECK, "a_manifest_schema_version_is_known")
    # A schema-2 manifest with its section, or with a null one, is admitted.
    for section in ({"verification_state": "not_attempted"}, None):
        with db_engine.begin() as c:
            copy = _copy_artifact(c, principal, source)
            _insert_versioned(
                c, principal, copy, 2, _lineage_manifest(copy, content, 2, lineage=section)
            )
