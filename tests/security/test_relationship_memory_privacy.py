"""What the Relationship Memory plane must never disclose, and to whom.

Beside `tests/security/test_entity_privacy_regression.py`, which makes the same
kind of claim about the plane that owns a memory's subject, and using the method
`tests/security/test_audit_redaction.py` established: plant a distinctive marker
where it would most easily escape, run real requests through the real service and
the real durable sink, then read **every column of every row** back and require
the marker to appear in none of it.

Five claims, each with a way it could plausibly fail:

* **A restricted memory is excluded from broad search as a predicate, not as a
  post-filter.** A filtered row can still reach a count, a truncation flag or a
  cursor, and a caller who watched the page shape change while probing terms
  would learn that a `sensitivity` about someone exists — which is most of what
  it says. So the probe here asks for a term that appears *only* in a restricted
  memory and requires nothing back: no rows, no withheld count, no truncation.
* **The note never reaches an audit row.** The audit is what an operator, a
  backup and a future reader see, and a statement copied into a correlation
  field or an idempotency column would be private text in the one place designed
  to be kept and read.
* **A refusal names a field and never a value.** `SafeDetail` is a closed token
  set precisely so a rejected note cannot be echoed back inside the error that
  rejected it.
* **A caller cannot set cloud eligibility.** Not by payload, not by schema, and
  not in what is stored.
* **The classification floor is the server's and not only the domain's.** The
  domain refuses a `sensitivity` below `restricted_local` before any statement
  is issued, so the only way to ask the *server* whether it would have caught a
  writer that skipped the domain is to go around the domain with a raw INSERT.

Everything is synthetic: one invented Principal, invented people, invented notes,
a disposable database this module creates and drops. No real person, no live
data, and no network.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.exc import DBAPIError

from my_pa.adapters.mcp.tools import payload_schema_for
from my_pa.adapters.normalization import PAYLOAD_KEY, normalize
from my_pa.application.commands import (
    ArchiveRelationshipMemory,
    Command,
    CreateRelationshipMemory,
    GetRelationshipMemory,
    GetRelationshipMemoryHistory,
    ListRelationshipMemories,
    RestoreRelationshipMemory,
    ReviseRelationshipMemory,
    SearchRelationshipMemories,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail, problem_detail
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.memory import (
    MemoryKind,
    memory_proposal_dedupe_digest,
    statement_digest,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

ROOT: Final = Path(__file__).resolve().parents[2]

#: Fixed name so a run interrupted before teardown is cleaned up by the next one,
#: and distinct from every other database-tier fixture's disposable database.
DISPOSABLE_DATABASE: Final = "my_pa_relationship_memory_privacy_test"

PRINCIPAL: Final = "prn_dddd0004dddd0004dddd0004"
NOOR: Final = "ent_6aaa0001aaaa0001"
NOOR_NAME: Final = "Noor Synthetic"

WHEN: Final = datetime(2026, 8, 22, 12, tzinfo=UTC)

#: Distinctive enough that a match is evidence rather than coincidence, and long
#: enough that none of them can occur in a stored vocabulary. None names anything
#: real: the "sensitivity" below is about an invented dispute on an invented
#: project, recorded about an invented person.
MARKERS: Final[Mapping[str, str]] = {
    #: A term that appears *only* inside a restricted memory. Probing for it is
    #: the attack: if the shape of the answer changes at all, the probe worked.
    "restricted_only": "zqxjkvbrwn-restricted-term",
    #: A term in an ordinary memory, so the search is proved to work at all and
    #: the emptiness above is evidence rather than a broken query.
    "ordinary": "hgtplmvusd-ordinary-term",
    #: Planted in a statement that is written, revised and archived, so no audit
    #: row for any of the four writes may contain it.
    "statement": "vkbnqrtwxs-planted-statement",
    #: Caller free text on a write path, and therefore the most likely carrier.
    "correction": "pmzldcfgyk-planted-correction",
    "idempotency": "wnrbjxqvth-planted-key",
}

LIMITS: Final = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


class _Runtime:
    """The composed service, its two engines, and one reader.

    Two engines because that separation is the audit mechanism: the sink draws
    its connection from the second and commits there, so an audit row survives a
    rolled-back request. The reader is a third, so the rows below are read from
    outside every transaction that wrote them.
    """

    def __init__(self, url: str) -> None:
        self.work_engine: Engine = create_database_engine(url)
        self.audit_engine: Engine = create_database_engine(url)
        self.reader: Engine = create_database_engine(url)
        audit = SqlAlchemyAuditSink(self.audit_engine)

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(self.work_engine, audit=audit)

        self.service = ApplicationService(
            unit_of_work=unit_of_work,
            limits=LIMITS,
            clock=lambda: WHEN,
            relationship_intelligence_enabled=True,
            relationship_memory_enabled=True,
        )
        self.principal = Principal(
            principal_id=PRINCIPAL, kind=PrincipalKind.OPERATOR, authenticated=True
        )

    def close(self) -> None:
        self.work_engine.dispose()
        self.audit_engine.dispose()
        self.reader.dispose()

    def send(self, request: Command, *, purpose: Purpose | None = None) -> ResponseEnvelope:
        capability = request.capability
        metadata = RequestMetadata(
            request_id=f"req-{issue_identifier(IdKind.CORRELATION)}",
            capability=capability,
            purpose=sorted(permitted_purposes(capability))[0] if purpose is None else purpose,
            principal_id=PRINCIPAL,
            requested_at=WHEN,
        )
        return self.service.invoke(metadata, request, principal=self.principal)

    def result(self, request: Command) -> dict[str, Any]:
        envelope = self.send(request)
        assert envelope.error is None, envelope.error
        assert envelope.result is not None
        return dict(envelope.result)

    def audit_rows(self) -> list[dict[str, object]]:
        """Every audit row, as whole rows.

        `SELECT *` on purpose: a column added later is covered by this without
        anybody remembering to add it here, which is the opposite of the usual
        failure where a new field escapes because the test enumerated the old
        ones.
        """
        with self.reader.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    text("SELECT * FROM knowledge.audit_events")
                ).mappings()
            ]


def _an_entity(entity_id: str, display_name: str) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=PRINCIPAL,
        entity_type=EntityType.PERSON,
        canonical_name=normalize_name(display_name),
        display_name=display_name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[_Runtime]:
    """A migrated database holding one synthetic person, and the composed service."""
    composed = _Runtime(disposable_database)
    with composed.work_engine.begin() as connection:
        SqlEntityRepository(connection).create(PRINCIPAL, _an_entity(NOOR, NOOR_NAME))
    try:
        yield composed
    finally:
        composed.close()


@pytest.fixture
def planted(runtime: _Runtime) -> _Runtime:
    """One restricted memory and one ordinary one, both about the same person.

    Same subject deliberately: the narrow profile read returns both, so the
    restricted row is *provably present* when the broad search declines to
    mention it. Without that, an empty search result would be evidence about an
    empty table.
    """
    runtime.result(
        CreateRelationshipMemory(
            entity_id=NOOR,
            kind=MemoryKind.SENSITIVITY,
            statement=(
                f"Do not raise the {MARKERS['restricted_only']} dispute with Noor Synthetic."
            ),
            idempotency_key="planted-restricted-0001",
        )
    )
    runtime.result(
        CreateRelationshipMemory(
            entity_id=NOOR,
            kind=MemoryKind.GENERAL_NOTE,
            statement=f"Noor Synthetic runs the {MARKERS['ordinary']} review each month.",
            idempotency_key="planted-ordinary-0001",
        )
    )
    return runtime


# --- the broad search discloses no restricted memory, in any way -------------


@pytest.mark.database
def test_the_narrow_profile_read_returns_both_memories(planted: _Runtime) -> None:
    """Guards every search assertion below.

    A restricted memory *is* disclosed on the narrow path: the request already
    names one entity the Principal owns and holds the read purpose for it. So
    this is where the two rows are proved to exist, which is what makes the
    search results below evidence about the exclusion rather than about the
    fixture.
    """
    listed = planted.result(ListRelationshipMemories(entity_id=NOOR))
    memories = listed["memories"]
    assert isinstance(memories, list)
    assert sorted(str(entry["kind"]) for entry in memories) == [
        MemoryKind.GENERAL_NOTE.value,
        MemoryKind.SENSITIVITY.value,
    ]
    statements = " ".join(str(entry["statement"]) for entry in memories)
    assert MARKERS["restricted_only"] in statements
    assert MARKERS["ordinary"] in statements


@pytest.mark.database
def test_a_broad_search_finds_the_ordinary_memory(planted: _Runtime) -> None:
    """The other guard: a search that matched nothing at all would pass the probe."""
    found = planted.result(SearchRelationshipMemories(query=MARKERS["ordinary"]))
    memories = found["memories"]
    assert isinstance(memories, list)
    assert len(memories) == 1
    assert MARKERS["ordinary"] in str(memories[0]["statement"])


@pytest.mark.database
def test_probing_a_term_that_appears_only_in_a_restricted_memory_returns_nothing(
    planted: _Runtime,
) -> None:
    """No rows, no count, and no truncation signal.

    Each of the three is a channel on its own. A count of withheld rows would
    answer "yes, there is one"; a truncation flag or a cursor would say the same
    thing more quietly. The exclusion is a predicate, so the row is never
    selected and there is nothing for any of them to report.
    """
    envelope = planted.send(SearchRelationshipMemories(query=MARKERS["restricted_only"]))
    assert envelope.error is None, envelope.error
    assert envelope.result is not None
    body = envelope.to_canonical_dict()
    result = body["result"]
    assert isinstance(result, dict)
    assert result["memories"] == []
    assert result["memories_withheld_by_policy"] == 0
    disclosure = body["disclosure"]
    assert isinstance(disclosure, dict)
    truncation = disclosure["truncation"]
    assert isinstance(truncation, dict)
    assert truncation["is_truncated"] is False
    assert truncation["reason"] is None
    assert truncation["next_cursor"] is None
    # And the whole rendered answer says nothing about the term or the note.
    assert MARKERS["restricted_only"] not in repr(body)


@pytest.mark.database
def test_a_search_that_matches_both_returns_only_the_unrestricted_one(
    planted: _Runtime,
) -> None:
    """One query, two matching rows, one answer. The restricted one is not counted."""
    found = planted.result(SearchRelationshipMemories(query="Noor Synthetic"))
    memories = found["memories"]
    assert isinstance(memories, list)
    assert [str(entry["kind"]) for entry in memories] == [MemoryKind.GENERAL_NOTE.value]
    assert found["memories_withheld_by_policy"] == 0


# --- the note never reaches an audit row -------------------------------------


@pytest.fixture
def audited(runtime: _Runtime) -> list[dict[str, object]]:
    """Every memory write there is, each carrying a marker, and the resulting rows.

    All four operations, plus a refusal, so the run covers every branch that
    writes an audit row for this plane rather than only the happy one.
    """
    created = runtime.result(
        CreateRelationshipMemory(
            entity_id=NOOR,
            statement=f"Noor Synthetic said {MARKERS['statement']} in the review.",
            idempotency_key=f"create-{MARKERS['idempotency']}",
        )
    )
    memory_id = str(created["memory_id"])
    revised = runtime.result(
        ReviseRelationshipMemory(
            memory_id=memory_id,
            expected_version=int(created["version"]),
            statement=f"Noor Synthetic said {MARKERS['statement']} twice.",
            correction_reason=MARKERS["correction"],
            idempotency_key=f"revise-{MARKERS['idempotency']}",
        )
    )
    archived = runtime.result(
        ArchiveRelationshipMemory(
            memory_id=memory_id,
            expected_version=int(revised["version"]),
            idempotency_key=f"archive-{MARKERS['idempotency']}",
        )
    )
    runtime.result(
        RestoreRelationshipMemory(
            memory_id=memory_id,
            expected_version=int(archived["version"]),
            idempotency_key=f"restore-{MARKERS['idempotency']}",
        )
    )
    # A refusal, so a denied attempt is in the sample too.
    denied = runtime.send(
        CreateRelationshipMemory(
            entity_id=NOOR,
            statement=f"Noor Synthetic said {MARKERS['statement']} once more.",
            idempotency_key=f"denied-{MARKERS['idempotency']}",
        ),
        purpose=Purpose.RELATIONSHIP_MEMORY_READ,
    )
    assert denied.error is not None
    return runtime.audit_rows()


@pytest.mark.database
def test_the_planted_run_produced_audit_rows(audited: list[dict[str, object]]) -> None:
    """Guards the check below: a run that recorded nothing would pass it."""
    assert len(audited) >= 5, f"the planted run recorded only {len(audited)} audit rows"
    assert {str(row["outcome"]) for row in audited} >= {"allowed", "denied"}
    assert {str(row["capability"]) for row in audited} >= {
        Capability.RELATIONSHIP_MEMORY_CREATE.value,
        Capability.RELATIONSHIP_MEMORY_REVISE.value,
        Capability.RELATIONSHIP_MEMORY_ARCHIVE.value,
        Capability.RELATIONSHIP_MEMORY_RESTORE.value,
    }


@pytest.mark.database
@pytest.mark.parametrize("marker", ["statement", "correction", "idempotency"])
def test_no_planted_marker_reaches_any_audit_column(
    audited: list[dict[str, object]], marker: str
) -> None:
    """The note, the correction reason, and the caller's own key.

    Rendered whole rather than column by column, so the claim is about the row
    and not about the columns this file happened to know about.
    """
    rendered = "\n".join(f"{name}={value!r}" for row in audited for name, value in row.items())
    assert MARKERS[marker] not in rendered, (
        f"the planted {marker} reached a stored audit row: {MARKERS[marker]!r}"
    )


def test_the_markers_are_distinctive_enough_to_be_evidence() -> None:
    """Guard the fixtures: a marker that could occur naturally proves nothing.

    Runs in every tier because it needs no server. Each has to be absent from
    the vocabulary the audit legitimately stores, or the checks above would be
    asserting that a legitimate value is missing.
    """
    vocabulary = " ".join(
        member.value for enum in (Capability, Purpose, SafeDetail) for member in enum
    )
    for kind, marker in MARKERS.items():
        assert len(marker) >= 16, f"the {kind} marker is short enough to collide"
        assert marker not in vocabulary, f"the {kind} marker is part of a stored vocabulary"
    assert len(set(MARKERS.values())) == len(MARKERS)


# --- a refusal names a field and never a value -------------------------------

#: A value distinctive enough that finding it in an error is unambiguous.
REJECTED_VALUE: Final = "jdwqvxnbrz-rejected-value"

#: One malformed request per command, each carrying `REJECTED_VALUE` in the
#: field that is wrong. Every command on the plane is here, because a refusal
#: path that no test drives is a refusal path whose disclosure nobody has read.
MALFORMED: Final[tuple[tuple[str, type, dict[str, Any]], ...]] = (
    (
        "create.entity_id",
        CreateRelationshipMemory,
        {
            "entity_id": REJECTED_VALUE,
            "statement": "A synthetic note.",
            "idempotency_key": "malformed-0001",
        },
    ),
    (
        "create.statement",
        CreateRelationshipMemory,
        {"entity_id": NOOR, "statement": "   ", "idempotency_key": REJECTED_VALUE},
    ),
    (
        "create.structured_value",
        CreateRelationshipMemory,
        {
            "entity_id": NOOR,
            "statement": "A synthetic note.",
            "structured_value": REJECTED_VALUE,
            "idempotency_key": "malformed-0002",
        },
    ),
    (
        "create.context_links",
        CreateRelationshipMemory,
        {
            "entity_id": NOOR,
            "statement": "A synthetic note.",
            "context_links": ({"target_type": "entity", "target_id": REJECTED_VALUE},),
            "idempotency_key": "malformed-0003",
        },
    ),
    (
        "get.memory_id",
        GetRelationshipMemory,
        {"memory_id": REJECTED_VALUE},
    ),
    (
        "list.kinds",
        ListRelationshipMemories,
        {"entity_id": NOOR, "kinds": (REJECTED_VALUE,)},
    ),
    (
        "list.after",
        ListRelationshipMemories,
        {"entity_id": NOOR, "after": REJECTED_VALUE},
    ),
    (
        "search.query",
        SearchRelationshipMemories,
        {"query": "   ", "entity_id": REJECTED_VALUE},
    ),
    (
        "history.after",
        GetRelationshipMemoryHistory,
        {"memory_id": "mem_aaaa0001aaaa0001", "after": REJECTED_VALUE},
    ),
    (
        "revise.correction_reason",
        ReviseRelationshipMemory,
        {
            "memory_id": "mem_aaaa0001aaaa0001",
            "expected_version": 1,
            "statement": "A synthetic note.",
            "correction_reason": "   ",
            "idempotency_key": REJECTED_VALUE,
        },
    ),
    (
        "revise.expected_version",
        ReviseRelationshipMemory,
        {
            "memory_id": "mem_aaaa0001aaaa0001",
            "expected_version": 0,
            "statement": "A synthetic note.",
            "idempotency_key": REJECTED_VALUE,
        },
    ),
    (
        "archive.memory_id",
        ArchiveRelationshipMemory,
        {"memory_id": REJECTED_VALUE, "expected_version": 1, "idempotency_key": "m-0004"},
    ),
    (
        "restore.memory_id",
        RestoreRelationshipMemory,
        {"memory_id": REJECTED_VALUE, "expected_version": 1, "idempotency_key": "m-0005"},
    ),
)


@pytest.mark.parametrize(
    ("label", "command_type", "payload"), MALFORMED, ids=[entry[0] for entry in MALFORMED]
)
def test_a_refusal_names_a_field_and_carries_no_value(
    label: str, command_type: type, payload: dict[str, Any]
) -> None:
    """Every refusal the plane can raise, rendered as a caller would see it.

    Two properties, and the second is what the first exists for: every token
    comes from the closed `SafeDetail` set, so no token *can* be a value; and the
    rendered problem carries none of the offending text, so nothing else on the
    error is echoing it either.
    """
    with pytest.raises(InvalidRequestError) as refusal:
        command_type(**payload)
    details = refusal.value.safe_details
    assert details, f"{label} refused without naming a field"
    assert set(details) <= set(SafeDetail)
    rendered = problem_detail(
        refusal.value, correlation_id="corr_aaaa0001aaaa0001"
    ).model_dump_json()
    assert REJECTED_VALUE not in rendered, f"{label} echoed the rejected value"
    for detail in details:
        assert detail.value == detail.value.lower()
        assert " " not in detail.value


def test_every_detail_the_plane_can_raise_names_a_field_the_plane_has() -> None:
    """The tokens are field names, checked against the fields that exist.

    A closed vocabulary stops a *value* being disclosed. It does not stop a token
    from being invented, and a token naming nothing would be a refusal a caller
    cannot act on. Each one is matched against the payload field names the eight
    commands publish, plus the four server-side spellings the plane deliberately
    uses instead of the wire name — `subject_entity_id` for `entity_id`,
    `memory_kind` for `kind`, `cursor` for `after`, and `target_id` for a link
    target — and `subject`, which names the subject of the request itself.
    """
    published: set[str] = set()
    for command_type in (
        CreateRelationshipMemory,
        GetRelationshipMemory,
        ListRelationshipMemories,
        SearchRelationshipMemories,
        GetRelationshipMemoryHistory,
        ReviseRelationshipMemory,
        ArchiveRelationshipMemory,
        RestoreRelationshipMemory,
    ):
        published |= set(payload_schema_for(command_type)["properties"])
    server_side = {"subject_entity_id", "memory_kind", "cursor", "target_id", "subject"}
    raised: set[SafeDetail] = set()
    for _label, command_type, payload in MALFORMED:
        with pytest.raises(InvalidRequestError) as refusal:
            command_type(**payload)
        raised |= set(refusal.value.safe_details)
    assert raised, "no refusal was exercised, so nothing below is evidence"
    for detail in sorted(raised):
        assert detail.value in published | server_side, (
            f"{detail.value} names no field on this plane"
        )


# --- cloud eligibility is not a caller's to set ------------------------------


@pytest.mark.parametrize(
    ("capability", "payload"),
    [
        (
            Capability.RELATIONSHIP_MEMORY_CREATE,
            {
                "entity_id": NOOR,
                "statement": "A synthetic note.",
                "idempotency_key": "cloud-0001",
                "cloud_eligible": True,
            },
        ),
        (
            Capability.RELATIONSHIP_MEMORY_REVISE,
            {
                "memory_id": "mem_aaaa0001aaaa0001",
                "expected_version": 1,
                "statement": "A synthetic note.",
                "idempotency_key": "cloud-0002",
                "cloud_eligible": True,
            },
        ),
    ],
    ids=["create", "revise"],
)
def test_a_caller_cannot_ask_for_cloud_eligibility(
    capability: Capability, payload: dict[str, Any]
) -> None:
    """No path sets it true, and there is no field through which to ask.

    Refused on the wire rather than accepted and ignored, because a field that
    can be sent is a field a later change can start honouring.
    """
    document = {
        "request_id": f"req-{capability.value}",
        "purpose": sorted(permitted_purposes(capability))[0].value,
        "principal_id": PRINCIPAL,
        "requested_at": "2026-08-22T12:00:00Z",
        PAYLOAD_KEY: payload,
    }
    with pytest.raises(InvalidRequestError):
        normalize(capability.value, document)


@pytest.mark.database
def test_what_is_stored_and_disclosed_is_not_cloud_eligible(runtime: _Runtime) -> None:
    """The posture is auditable rather than absent, and it reads false.

    Asserted in both places a reader could look: the disclosed version, and the
    column an operator would query.
    """
    created = runtime.result(
        CreateRelationshipMemory(
            entity_id=NOOR,
            statement="Noor Synthetic prefers written summaries.",
            idempotency_key="cloud-stored-0001",
        )
    )
    detail = runtime.result(GetRelationshipMemory(memory_id=str(created["memory_id"])))
    assert detail["memory"]["current_version"]["cloud_eligible"] is False
    with runtime.reader.connect() as connection:
        eligible = connection.execute(
            text("SELECT bool_or(cloud_eligible) FROM knowledge.relationship_memory_versions")
        ).scalar_one()
    assert eligible is False


# --- the classification floor is the server's, not only the domain's ---------

#: The statement the raw rows below carry. Invented dispute, invented project,
#: invented person, and distinctive enough that a row surviving a rollback would
#: be recognisable as this test's.
FLOOR_PROBE: Final = "Do not raise the invented Synthetic Holdings dispute with Noor Synthetic."


@pytest.fixture
def one_memory(runtime: _Runtime) -> _Runtime:
    """One ordinary memory, so the probe rows below have a real chain to extend."""
    runtime.result(
        CreateRelationshipMemory(
            entity_id=NOOR,
            statement="Noor Synthetic prefers written summaries.",
            idempotency_key="floor-probe-base-0001",
        )
    )
    return runtime


def _append_sensitivity_version(runtime: _Runtime, classification: Classification) -> int:
    """Append one otherwise-valid `sensitivity` version at `classification`, raw.

    *Otherwise valid* is the load-bearing word. PostgreSQL reports one violated
    constraint, so a probe row with a second fault would test whichever the
    server happened to name rather than the floor. This row supersedes the
    memory's real first version, so its number, its predecessor, its actor and
    its authority are all consistent with the chain it joins and the
    classification is the only thing wrong with it.

    Raw SQL rather than a repository call, for the reason the cloud-eligibility
    test beside it goes around the domain: `RelationshipMemoryVersion` refuses
    this in `__post_init__`, so a repository call never reaches the server and
    would prove only that the domain still works. The floor is claimed as
    defence in depth by `RM-AC-006` and `RM-P-AC-006`, and depth that no test
    asks the server about is depth nobody has checked.

    Nothing is committed. The transaction is rolled back when the connection
    closes, so the admitted case leaves no synthetic sensitivity in the database
    and the refused case leaves nothing at all. Returns how many sensitivity
    versions the transaction can see, so an admission is asserted as a row that
    exists rather than as an exception that did not happen.
    """
    with runtime.reader.connect() as connection:
        prior_version_id = connection.execute(
            text("SELECT current_version_id FROM knowledge.relationship_memories")
        ).scalar_one()
        connection.execute(
            text(
                "INSERT INTO knowledge.relationship_memory_versions ("
                "memory_version_id, memory_id, principal_id, version_number, "
                "statement_text, statement_sha256, memory_kind, authority, "
                "classification, cloud_eligible, created_by_actor, recorded_at, "
                "prior_version_id, idempotency_key, correlation_id) "
                "SELECT :version_id, memory_id, :principal_id, 2, :statement, :digest, "
                "'sensitivity', 'user_authored_private_note', :classification, false, "
                "'user', now(), :prior_version_id, :key, :correlation_id "
                "FROM knowledge.relationship_memories"
            ),
            {
                "version_id": issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
                "principal_id": PRINCIPAL,
                "statement": FLOOR_PROBE,
                "digest": statement_digest(FLOOR_PROBE),
                "classification": classification.value,
                "prior_version_id": prior_version_id,
                "key": f"floor-probe-{classification.value}",
                "correlation_id": issue_identifier(IdKind.CORRELATION),
            },
        )
        return int(
            connection.execute(
                text(
                    "SELECT count(*) FROM knowledge.relationship_memory_versions "
                    "WHERE memory_kind = 'sensitivity'"
                )
            ).scalar_one()
        )


@pytest.mark.database
@pytest.mark.parametrize(
    "classification",
    [Classification.SYNTHETIC_TEST, Classification.PRIVATE_LOCAL],
    ids=lambda value: value.value,
)
def test_the_server_refuses_a_sensitivity_below_its_floor(
    one_memory: _Runtime, classification: Classification
) -> None:
    """Both classifications that rank below the floor, not only the named one.

    `a_sensitivity_memory_is_at_least_restricted` read
    `classification <> 'private_local' OR memory_kind <> 'sensitivity'`, which
    named one forbidden value instead of expressing a minimum. `synthetic_test`
    ranks *below* `private_local` in `_CLASSIFICATION_RANK`, `satisfies_floor`
    refuses it, and the server admitted it — a reviewer proved that with a raw
    INSERT of exactly this shape. Parametrized over both ranks so the constraint
    is asked to be a floor rather than asked about one value: a repaired
    expression that again enumerates values passes for whichever value it
    happens to enumerate and fails here.
    """
    with pytest.raises(DBAPIError) as refused:
        _append_sensitivity_version(one_memory, classification)
    assert "a_sensitivity_memory_is_at_least_restricted" in str(refused.value)


@pytest.mark.database
def test_the_server_admits_a_sensitivity_at_its_floor(one_memory: _Runtime) -> None:
    """Guards the two refusals above: a constraint refusing everything would pass them.

    `restricted_local` is the floor and the most restrictive member there is, so
    this is the one classification a `sensitivity` may be stored at. Asserted as
    a row the transaction can see rather than as an absent exception, because
    "nothing was raised" is also what a silently discarded statement looks like.
    """
    assert _append_sensitivity_version(one_memory, Classification.RESTRICTED_LOCAL) == 1


def _stage_sensitivity_proposal(runtime: _Runtime, classification: Classification) -> int:
    """Stage one otherwise-valid `sensitivity` proposal at `classification`, raw.

    The proposal plane's floor is a separate CHECK on a separate table, it was
    weak in the same way and for the same reason, and nothing else in the suite
    asks the server about it — the promotion tests stage their proposals through
    the domain, which refuses this before any statement is issued. A candidate
    that could be staged below the floor its accepted form must meet would make
    the memory-side CHECK the only thing standing between a `sensitivity` and
    `private_local`, which is one control rather than the two the design claims.

    Rolled back like the version probe, so no synthetic proposal survives.
    """
    with runtime.reader.connect() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.relationship_memory_proposals ("
                "memory_proposal_id, principal_id, subject_entity_id, origin_subject_entity_id, "
                "expected_subject_version, proposed_kind, proposed_statement, "
                "proposed_statement_sha256, dedupe_sha256, state, method, "
                "method_version, classification, proposed_at) VALUES ("
                ":proposal_id, :principal_id, :subject_entity_id, :origin_subject_entity_id, "
                "1, 'sensitivity', "
                ":statement, :digest, :dedupe, 'proposed', 'deterministic', 'v1', "
                ":classification, now())"
            ),
            {
                "proposal_id": issue_identifier(IdKind.RELATIONSHIP_MEMORY_PROPOSAL),
                "principal_id": PRINCIPAL,
                "subject_entity_id": NOOR,
                "origin_subject_entity_id": NOOR,
                "statement": FLOOR_PROBE,
                "digest": statement_digest(FLOOR_PROBE),
                "dedupe": memory_proposal_dedupe_digest(
                    principal_id=PRINCIPAL,
                    subject_entity_id=NOOR,
                    proposed_kind=MemoryKind.SENSITIVITY,
                    proposed_statement_sha256=statement_digest(FLOOR_PROBE),
                    structured_value=None,
                ),
                "classification": classification.value,
            },
        )
        return int(
            connection.execute(
                text("SELECT count(*) FROM knowledge.relationship_memory_proposals")
            ).scalar_one()
        )


@pytest.mark.database
@pytest.mark.parametrize(
    "classification",
    [Classification.SYNTHETIC_TEST, Classification.PRIVATE_LOCAL],
    ids=lambda value: value.value,
)
def test_the_server_refuses_a_sensitivity_proposal_below_its_floor(
    runtime: _Runtime, classification: Classification
) -> None:
    """`a_sensitivity_proposal_is_at_least_restricted`, asked of the server directly."""
    with pytest.raises(DBAPIError) as refused:
        _stage_sensitivity_proposal(runtime, classification)
    assert "a_sensitivity_proposal_is_at_least_restricted" in str(refused.value)


@pytest.mark.database
def test_the_server_admits_a_sensitivity_proposal_at_its_floor(runtime: _Runtime) -> None:
    """The same guard the version probe carries: a CHECK refusing everything proves nothing."""
    assert _stage_sensitivity_proposal(runtime, Classification.RESTRICTED_LOCAL) == 1
