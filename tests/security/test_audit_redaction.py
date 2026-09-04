"""Nothing sensitive reaches a stored audit row.

`tests/security/test_application_redaction.py` makes this claim about the
`AuditEvent` objects a run produces. That is half of it: an event with no field
for a payload proves nothing about the columns it is written into, and the
columns are what an operator, a backup, and a future reader actually see. This
file is the other half, and it is in the `database` tier because the sink, the
table, and its constraints are the subject.

The method is the one the security suite already uses: plant each forbidden
class where it would most easily escape, run real requests through the real
service and the real durable sink, and then read **every column of every row**
back and require none of the markers to appear anywhere in it. Reading the whole
row rather than named columns is deliberate — a column added later is covered
without this file being edited, which is the opposite of the usual failure where
a new field escapes because the test enumerated the old ones.

The markers are distinctive strings, so a match is evidence rather than
coincidence. Everything is synthetic: the tree is pytest's `tmp_path`, the
"credential" is not one, and no live source is reached.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Engine, text
from tests.conftest import DEFAULT_LIMITS

from my_pa.application.commands import (
    EnrollSource,
    FetchSource,
    GetSourceMetadata,
    ListSources,
    Representation,
    SearchKnowledge,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import UnitOfWork
from my_pa.contracts.v1.envelope import RequestMetadata
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import SourceProviderKind, issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.registry import register_source
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from my_pa.infrastructure.providers.registered import RegisteredSourceProviders

ROOT = Path(__file__).resolve().parents[2]

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
DISPOSABLE_DATABASE = "my_pa_audit_redaction_test"

WHEN = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

#: The five classes `AGENTS.md` section 5 and `module-boundaries.md` section 5.6
#: name, as markers distinctive enough that a match cannot be a coincidence.
#: None of these is real: no such path, host, or account exists, and the
#: "credential" is a literal invented for this file.
MARKERS: Final[dict[str, str]] = {
    "query": "zqxjkvbrwn-planted-query-term",
    "host": "planted-host.invalid",
    "path": "planted-path-segment",
    "credential": "planted-credential-vhfmwqzp",
    "content": "planted-source-content-kdlrmxts",
}


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    built = create_database_engine(disposable_database)
    try:
        with built.begin() as connection:
            connection.execute(
                text(
                    "TRUNCATE knowledge.native_simulation_receipts, "
                    "knowledge.native_checkpoints, "
                    "knowledge.native_apple_read_grants, "
                    "knowledge.native_admission_authorities, knowledge.audit_events"
                )
            )
            connection.execute(text("TRUNCATE knowledge.sources CASCADE"))
        yield built
    finally:
        built.dispose()


@pytest.fixture
def planted_root(tmp_path: Path) -> Path:
    """A synthetic tree whose *names* and *contents* both carry markers."""
    root = tmp_path / f"corpus-{MARKERS['path']}"
    root.mkdir()
    (root / f"{MARKERS['path']}-note.md").write_text(
        f"# Notes\n\n{MARKERS['content']}\n\ntoken: {MARKERS['credential']}\n",
        encoding="utf-8",
    )
    (root / "list.txt").write_text(f"{MARKERS['host']}\n", encoding="utf-8")
    return root


def _principal() -> Principal:
    return Principal(
        principal_id=issue_identifier(IdKind.PRINCIPAL),
        kind=PrincipalKind.OPERATOR,
        authenticated=True,
    )


def _metadata(capability: Capability, purpose: Purpose, principal: Principal) -> RequestMetadata:
    return RequestMetadata(
        request_id=f"req-{capability.value}",
        capability=capability,
        purpose=purpose,
        principal_id=principal.principal_id,
        requested_at=WHEN,
    )


def _rows(engine: Engine) -> list[dict[str, object]]:
    """Every audit row, as whole rows.

    `SELECT *` on purpose: a column added to the table later is covered by this
    without anybody remembering to add it here.
    """
    with engine.connect() as connection:
        result = connection.execute(text("SELECT * FROM knowledge.audit_events"))
        return [dict(row) for row in result.mappings()]


def _rendered(rows: list[dict[str, object]]) -> str:
    return "\n".join(f"{name}={value!r}" for row in rows for name, value in row.items())


@pytest.fixture
def audited(engine: Engine, planted_root: Path) -> list[dict[str, object]]:
    """Run every capability that could carry a marker, and return the audit rows.

    One principal that holds an enrollment and one that does not, so the run
    covers an allowed request, a denial, and a mismatch — the three outcomes, and
    therefore every branch that writes a row.
    """
    with engine.begin() as connection:
        source = register_source(
            connection,
            provider_kind=SourceProviderKind.FIXTURE,
            label="Synthetic corpus",
            classification=Classification.SYNTHETIC_TEST,
            # The configured root itself carries the path marker, so a writer
            # that copied a source's `native_root` into an audit row would be
            # caught here as well.
            native_root=str(planted_root),
        )

    # The provider comes from the registered row, through the same lookup a
    # request uses, so the identifiers below are the persisted ones. A provider
    # built here would mint its own, and `record_scope` refuses an identifier
    # `knowledge.source_objects` has never seen — which would have made the
    # enrollment fail rather than the redaction.
    with engine.begin() as connection:
        registered = RegisteredSourceProviders(connection).for_source(source.source_id)
        assert registered is not None, "the registered source has no adapter"
        children = {child.media_type: child for child in registered.list_children()}
    markdown = children["text/markdown"]

    sink = SqlAlchemyAuditSink(engine)

    def unit_of_work() -> UnitOfWork:
        return SqlAlchemyUnitOfWork(engine, audit=sink)

    service = ApplicationService(
        unit_of_work=unit_of_work,
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
    )

    holder = _principal()
    enrolled = service.invoke(
        _metadata(Capability.SOURCES_ENROLL, Purpose.BOUNDED_ENROLLMENT, holder),
        EnrollSource(
            source_id=source.source_id,
            object_ids=(markdown.source_object_id,),
            root_object_id=None,
            depth=0,
            media_types=("text/markdown",),
            # An idempotency key is caller-supplied free text, which makes it the
            # most likely carrier of anything at all.
            idempotency_key=f"enroll-{MARKERS['credential']}",
        ),
        principal=holder,
    )
    assert enrolled.error is None, "the planted run never got as far as enrolling"
    enrollment_id = str(enrolled.result["enrollment_id"])  # type: ignore[index]

    # A search whose query is the marker.
    service.invoke(
        _metadata(Capability.KNOWLEDGE_SEARCH, Purpose.KNOWLEDGE_SEARCH, holder),
        SearchKnowledge(enrollment_id=enrollment_id, query=MARKERS["query"]),
        principal=holder,
    )
    # A fetch of the object whose bytes and whose name both carry markers.
    service.invoke(
        _metadata(Capability.SOURCES_FETCH, Purpose.CONTENT_EXTRACTION, holder),
        FetchSource(
            source_id=source.source_id,
            source_object_id=markdown.source_object_id,
            enrollment_id=enrollment_id,
            representation=Representation.NORMALIZED_TEXT,
            max_bytes=None,
        ),
        principal=holder,
    )
    service.invoke(
        _metadata(Capability.SOURCES_METADATA, Purpose.SOURCE_INSPECTION, holder),
        GetSourceMetadata(
            source_id=source.source_id,
            source_object_id=markdown.source_object_id,
            enrollment_id=enrollment_id,
        ),
        principal=holder,
    )
    # A denial: a principal holding nothing asks to list the same source.
    stranger = _principal()
    service.invoke(
        _metadata(Capability.SOURCES_LIST, Purpose.SOURCE_INSPECTION, stranger),
        ListSources(source_id=source.source_id, parent_object_id=None),
        principal=stranger,
    )
    # A mismatch: the declared capability is not the payload's.
    service.invoke(
        _metadata(Capability.KNOWLEDGE_SEARCH, Purpose.KNOWLEDGE_SEARCH, holder),
        ListSources(source_id=source.source_id, parent_object_id=None),
        principal=holder,
    )
    return _rows(engine)


@pytest.mark.database
def test_the_planted_run_produced_audit_rows(audited: list[dict[str, object]]) -> None:
    """Guards every check below: a run that recorded nothing would pass them all."""
    assert len(audited) >= 6, f"the planted run recorded only {len(audited)} audit rows"
    assert {str(row["outcome"]) for row in audited} == {"allowed", "denied", "failed"}


@pytest.mark.database
@pytest.mark.parametrize("kind", sorted(MARKERS))
def test_no_planted_marker_reaches_any_audit_column(
    audited: list[dict[str, object]], kind: str
) -> None:
    """A query term, a host, a path, a credential, and source content.

    Rendered whole rather than column by column, so the claim is about the row
    and not about the columns this file happened to know about.
    """
    rendered = _rendered(audited)
    assert MARKERS[kind] not in rendered, (
        f"the planted {kind} reached a stored audit row: {MARKERS[kind]!r}"
    )


@pytest.mark.database
def test_every_audit_value_is_an_identifier_an_enum_a_count_or_a_time(
    audited: list[dict[str, object]],
) -> None:
    """The positive form of the rule, so a column of free text cannot pass quietly.

    Absence of five markers is evidence about five values. This says what the
    row may contain at all: every string in it is either an opaque identifier, a
    member of one of the four closed sets, or a well-formed policy version.
    """
    from my_pa.domain.audit.events import AuditOutcome
    from my_pa.domain.common.identifiers import validate_identifier
    from my_pa.domain.policy.decision import DenialReason, validate_policy_version

    closed = (
        {member.value for member in Capability}
        | {member.value for member in Purpose}
        | {member.value for member in AuditOutcome}
        | {member.value for member in DenialReason}
    )
    for row in audited:
        for name, value in row.items():
            if value is None or isinstance(value, int | datetime):
                continue
            assert isinstance(value, str), f"{name} holds an unexpected type"
            if value in closed:
                continue
            if name == "policy_version":
                validate_policy_version(value)
                continue
            # Anything left has to be an opaque identifier, which raises if it
            # is not.
            validate_identifier(value)


def test_the_markers_are_distinctive_enough_to_be_evidence() -> None:
    """Guard the fixtures: a marker that could occur naturally proves nothing.

    Runs in every tier because it needs no server. Each marker has to be absent
    from the vocabulary the audit legitimately stores, or the checks above would
    be asserting that a legitimate value is missing.
    """
    from my_pa.domain.audit.events import AuditOutcome
    from my_pa.domain.policy.decision import DenialReason

    vocabulary = " ".join(
        member.value
        for enum in (Capability, Purpose, AuditOutcome, DenialReason)
        for member in enum
    )
    assert len(MARKERS) == 5
    for kind, marker in MARKERS.items():
        assert len(marker) >= 16, f"the {kind} marker is short enough to collide"
        assert marker not in vocabulary, f"the {kind} marker is part of a stored vocabulary"
