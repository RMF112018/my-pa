"""A foreign enrollment identifier is exactly an absent one, at the only place it can be.

Database tier, over a disposable database this module creates and drops.

`persistence/search.py` contains **no reference to a principal at all**. It scopes
every statement by `enrollment_id`, and that is a valid design rather than a
defect — an enrollment is the grant, and a grant belongs to one Principal — but
it makes the whole isolation of the extraction plane rest on one function:
`application/authorization._scope_of_enrollment`, which resolves an enrollment
identifier **only within the caller's own enrollments** and returns the empty set
otherwise. An unresolved scope authorizes nothing, so the request is denied
before `search_extractions` is reached.

That is a single point of failure with no test asserting that the query would be
unsafe without it. This module is that test, and it makes two claims rather than
one:

* **Denial.** Principal B naming Principal A's enrollment resolves to the empty
  scope and the request is refused. Principal A naming the same enrollment
  resolves to its source and is allowed — the control, without which "denied"
  could mean the resolver is broken rather than partitioned.
* **Indistinguishability.** B's outcome for A's real enrollment and B's outcome
  for an enrollment identifier that exists nowhere are compared as a pair:
  same allowed flag, same resolved scope, same denial reason class. A refusal
  that differed between the two would tell B that A's enrollment exists, which
  is the fact the partition is there to withhold.

Both are asserted for `SearchKnowledge` and for `ReadKnowledge`, because both resolve
their scope through the same function and a change could break one without the
other.

Every identity, source, and enrollment here is synthetic. No path is opened, no
source is reached, and no query is run against a real corpus.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Engine, text

from my_pa.application.authorization import authorize
from my_pa.application.commands import ReadKnowledge, SearchKnowledge
from my_pa.contracts.ports import UnitOfWork
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

ROOT: Final = Path(__file__).resolve().parents[2]
DISPOSABLE_DATABASE: Final = "my_pa_search_isolation_test"

PRINCIPAL_A: Final = "prn_aaaa0004aaaaaaaaaaaaaaaa00000004"
PRINCIPAL_B: Final = "prn_bbbb0004bbbbbbbbbbbbbbbb00000004"

A_ENROLLMENT: Final = "enr_0000000000000001"
B_ENROLLMENT: Final = "enr_0000000000000002"
ABSENT_ENROLLMENT: Final = "enr_0000000000000099"

WHEN: Final = datetime(2026, 8, 9, 9, 0, tzinfo=UTC)

pytestmark = pytest.mark.database


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    engine = create_database_engine(disposable_database)
    try:
        with engine.begin() as connection:
            connection.execute(text("TRUNCATE knowledge.sources CASCADE"))
            connection.execute(
                text(
                    "INSERT INTO knowledge.sources "
                    "(source_id, provider_kind, label, classification, native_root) "
                    "VALUES ('src_0000000000000001', 'fixture', 'Fixture corpus', "
                    "'synthetic_test', '/synthetic/root')"
                )
            )
            for enrollment_id, principal in (
                (A_ENROLLMENT, PRINCIPAL_A),
                (B_ENROLLMENT, PRINCIPAL_B),
            ):
                connection.execute(
                    text(
                        "INSERT INTO knowledge.enrollments "
                        "(enrollment_id, source_id, principal_id, purpose, policy_version, "
                        " idempotency_key, request_fingerprint, root_object_id, media_types, "
                        " max_items, max_bytes) "
                        "VALUES (:enrollment_id, 'src_0000000000000001', :principal, "
                        "'bounded_enrollment', 'mcv-1', :key, :key, :root, "
                        "ARRAY['text/plain'], 10, 1024)"
                    ),
                    {
                        "enrollment_id": enrollment_id,
                        "principal": principal,
                        "key": f"enroll-{enrollment_id[-4:]}",
                        "root": f"obj_{enrollment_id[-16:]}",
                    },
                )
        yield engine
    finally:
        engine.dispose()


def _principal(principal_id: str) -> Principal:
    return Principal(principal_id=principal_id, kind=PrincipalKind.OPERATOR, authenticated=True)


def _unit_of_work(engine: Engine) -> UnitOfWork:
    return SqlAlchemyUnitOfWork(engine, audit=SqlAlchemyAuditSink(engine))


#: One purpose per capability, because the policy refuses a mismatched pair
#: before it ever considers scope — and a denial for the wrong reason would make
#: every comparison below true of nothing.
PURPOSES: Final = {
    "SearchKnowledge": Purpose.KNOWLEDGE_SEARCH,
    "ReadKnowledge": Purpose.KNOWLEDGE_READ,
}


def _outcome(
    engine: Engine, principal_id: str, command_object: object
) -> tuple[bool, tuple[str, ...], str]:
    """What one authorization decided: allowed, the scope it resolved, and why.

    Returned as one comparable triple so "a foreign identifier is
    indistinguishable from an absent one" is an equality rather than two
    assertions that happen to agree.
    """
    with _unit_of_work(engine) as unit_of_work:
        decision = authorize(
            unit_of_work,
            principal=_principal(principal_id),
            purpose=PURPOSES[type(command_object).__name__],
            command=command_object,  # type: ignore[arg-type]
            correlation_id="corr_0000000000000001",
            request_id="request-0000000001",
            at=WHEN,
        )
    return (
        decision.allowed,
        tuple(sorted(decision.requested_source_ids)),
        str(decision.decision.reason),
    )


def _commands(enrollment_id: str) -> tuple[object, ...]:
    """Both commands that resolve a scope through an enrollment identifier."""
    return (
        SearchKnowledge(enrollment_id=enrollment_id, query="synthetic"),
        ReadKnowledge(enrollment_id=enrollment_id, knowledge_id="kn_0000000000000001"),
    )


def test_a_foreign_enrollment_is_denied_and_reads_exactly_as_an_absent_one(
    engine: Engine,
) -> None:
    """The single-point dependency, asserted: no scope resolves, so nothing is allowed."""
    for foreign, absent in zip(_commands(A_ENROLLMENT), _commands(ABSENT_ENROLLMENT), strict=True):
        foreign_outcome = _outcome(engine, PRINCIPAL_B, foreign)
        absent_outcome = _outcome(engine, PRINCIPAL_B, absent)

        assert foreign_outcome == absent_outcome, (
            f"{type(foreign).__name__}: B's outcome for A's enrollment differs from "
            "its outcome for an enrollment that exists nowhere, which tells B that "
            "A's enrollment exists"
        )
        allowed, scope, _reason = foreign_outcome
        assert allowed is False
        assert scope == (), "a foreign enrollment resolved to a source"
        # The refusal names no Principal and no source.
        assert PRINCIPAL_A not in foreign_outcome[2]


def test_the_owning_principal_resolves_the_same_enrollment_to_its_source(
    engine: Engine,
) -> None:
    """The control. Without it, the denial above could be a broken resolver."""
    for command_object in _commands(A_ENROLLMENT):
        allowed, scope, reason = _outcome(engine, PRINCIPAL_A, command_object)
        assert scope == ("src_0000000000000001",), (
            f"{type(command_object).__name__}: the owner's own enrollment resolved "
            f"to {scope}, so the empty scope above says nothing about partitioning"
        )
        assert allowed is True, f"the owner was denied its own enrollment: {reason}"


def test_the_isolation_holds_in_both_directions(engine: Engine) -> None:
    """A cannot reach B's enrollment either, which a one-sided test would miss."""
    allowed, scope, _reason = _outcome(engine, PRINCIPAL_A, _commands(B_ENROLLMENT)[0])
    assert allowed is False
    assert scope == ()

    allowed, scope, _reason = _outcome(engine, PRINCIPAL_B, _commands(B_ENROLLMENT)[0])
    assert allowed is True
    assert scope == ("src_0000000000000001",)


def test_extraction_and_goodnotes_search_keep_their_distinct_isolation_controls(
    engine: Engine,
) -> None:
    """Extraction stays enrollment-authorized; GoodNotes joins every Principal key."""
    source = (ROOT / "src" / "my_pa" / "infrastructure" / "persistence" / "search.py").read_text(
        encoding="utf-8"
    )
    extraction, goodnotes = source.split("def _accepted_goodnotes_text", maxsplit=1)
    assert "principal_id" not in extraction
    assert "goodnotes_region_proposals.c.principal_id" in goodnotes
    assert "goodnotes_review_decisions.c.principal_id" in goodnotes
    assert "goodnotes_page_versions.c.principal_id" in goodnotes
    assert "goodnotes_pages.c.principal_id" in goodnotes
    assert "authorized_object(" in goodnotes
