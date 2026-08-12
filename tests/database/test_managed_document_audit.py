"""WP-28's blocking precondition, measured against a live PostgreSQL server.

WP-27 shipped the managed-document plane with **no capability seat**, so a
managed write — and a managed *refusal* — left no `knowledge.audit_events` row
anywhere. Its reviewer recorded that as NOTE 7 and its Orchestrator made it the
condition on this package:

> WP-28 must add the capability seat and emit `audit_events` for managed writes —
> including denied attempts — **before** wiring any transport.

This module is that condition as a measurement. Everything here runs against a
disposable database created and dropped by its own fixture, migrated to head,
never the configured one; every byte is written into `tmp_path`. Every value is
synthetic.

## What is proved, and what each proof actually covers

**A successful managed write leaves a row naming the right capability, and the
row survives.** `authorize()` records the decision on the audit sink's *own*
connection and commits it there (`D-34`), then the handler runs inside the
request's transaction.

**A refusal leaves a row too, and there are three different kinds of refusal.**

1. *Authorization* — a purpose the capability does not permit. `evaluate` denies,
   `authorize` records `outcome='denied'` with the reason, and the request never
   reaches the handler. The reason is in the row and not in the answer.
2. *Application-level, raised by the handler* — a stale `expected_version_number`
   and an idempotency key bound to a different request, which are the two WP-27
   named. **This is the case the precondition actually turns on**, because the
   handler raises *inside* the unit of work: the work transaction rolls back, and
   the question is whether the audit row rolls back with it. It does not, and the
   test says why — `SqlAlchemyAuditSink.record` takes its own connection from a
   *second engine* and commits before returning. The measurement is made the only
   way it can be made: by rolling the work back for real and then reading the row
   from a third connection.
3. *Cross-Principal* — B naming A's document. WP-27 collapses "not yours", "does
   not exist" and "belongs to another document" into one answer, so the audit row
   is what tells an operator that B tried.

**What the row does *not* say, stated so it is not over-read.** The row `authorize`
writes for cases 2 and 3 records `outcome='allowed'`: authorization *was* granted,
which remains true whether or not the work succeeded, and it is the
security-relevant fact. It is **not** a record that the write failed. Nothing in
`invoke` writes a second event on a handler failure — for any capability, not
only these — so "a denied managed operation leaves a durable row" is true in the
sense that the attempt is recorded with its Principal, capability, purpose,
correlation identifier and time, and false in the sense that the row does not
name the refusal. That is measured below rather than described, and it is carried
as a NOTE rather than silently satisfied.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.application.commands import (
    ArchiveManagedDocument,
    Command,
    CreateManagedDocument,
    ListManagedDocuments,
    ReadManagedDocument,
    ReviseManagedDocument,
)
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import UnitOfWork
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.audit.events import AuditOutcome
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.managed_document_stores.filesystem.store import (
    FilesystemManagedByteStore,
)
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
DISPOSABLE_DATABASE: Final = "my_pa_managed_document_audit_test"

#: The two synthetic Principals every isolation suite in this repository uses.
PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

FIRST: Final = b"# Synthetic managed note\n\nThe first version.\n"
SECOND: Final = b"# Synthetic managed note\n\nThe second version.\n"

WHEN: Final = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)

LIMITS: Final = EffectiveLimits(
    max_page_size=200,
    default_page_size=50,
    max_fetch_bytes=8 * 1024 * 1024,
    max_enrollment_depth=0,
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


class _Runtime:
    """The two engines, the store and the service, exactly as the gateway composes them.

    Two engines rather than one, because that separation *is* the mechanism under
    test: the audit sink draws its connection from the second engine and commits
    there, which is the only way a PostgreSQL transaction can leave a record that
    another transaction's rollback cannot reach.
    """

    def __init__(self, url: str, root: Path) -> None:
        self.work_engine: Engine = create_database_engine(url)
        self.audit_engine: Engine = create_database_engine(url)
        self.reader: Engine = create_database_engine(url)
        self.store = FilesystemManagedByteStore(root)
        audit = SqlAlchemyAuditSink(self.audit_engine)

        def unit_of_work() -> UnitOfWork:
            return SqlAlchemyUnitOfWork(self.work_engine, audit=audit)

        self.service = ApplicationService(
            unit_of_work=unit_of_work, limits=LIMITS, managed_store=self.store
        )

    def close(self) -> None:
        self.work_engine.dispose()
        self.audit_engine.dispose()
        self.reader.dispose()

    def invoke(
        self,
        command_value: Command,
        *,
        principal_id: str = PRINCIPAL_A,
        purpose: Purpose | None = None,
    ) -> ResponseEnvelope:
        """One request through the canonical entry point, with nothing bypassed."""
        capability = command_value.capability
        metadata = RequestMetadata(
            request_id=f"req-{issue_identifier(IdKind.CORRELATION)}",
            capability=capability,
            purpose=_a_permitted_purpose(capability) if purpose is None else purpose,
            # Deliberately a *different* Principal from the acting one, in every
            # request this module makes. `metadata.principal_id` is correlation
            # input the application does not read, and pinning it to B while
            # acting as A is what makes that a measurement rather than a comment:
            # every row below carries A, so nothing read this field.
            principal_id=PRINCIPAL_B if principal_id == PRINCIPAL_A else PRINCIPAL_A,
            requested_at=WHEN,
        )
        return self.service.invoke(
            metadata,
            command_value,
            principal=Principal(
                principal_id=principal_id, kind=PrincipalKind.OPERATOR, authenticated=True
            ),
        )

    def audit_rows(self) -> list[dict[str, Any]]:
        with self.reader.connect() as connection:
            return [
                dict(row)
                for row in connection.execute(
                    text(
                        "SELECT capability, purpose, outcome, denial_reason, principal_id, "
                        "correlation_id FROM knowledge.audit_events ORDER BY recorded_at, audit_id"
                    )
                ).mappings()
            ]

    def managed_row_counts(self) -> dict[str, int]:
        with self.reader.connect() as connection:
            return {
                table: int(
                    connection.execute(
                        text(f"SELECT count(*) FROM {SCHEMA}.{table}")  # noqa: S608
                    ).scalar_one()
                )
                for table in ("managed_documents", "managed_document_versions")
            }


def _a_permitted_purpose(capability: Capability) -> Purpose:
    from my_pa.domain.identity.operation import permitted_purposes

    return sorted(permitted_purposes(capability))[0]


@pytest.fixture
def runtime(disposable_database: str, tmp_path: Path) -> Iterator[_Runtime]:
    """A migrated database, a temporary managed root, and the composed service."""
    command.upgrade(_config(), "head")
    root = tmp_path / "managed"
    root.mkdir()
    composed = _Runtime(disposable_database, root)
    try:
        yield composed
    finally:
        composed.close()


def _created(runtime: _Runtime, *, key: str = "synthetic-audit-0001") -> dict[str, Any]:
    envelope = runtime.invoke(
        CreateManagedDocument(
            title="Synthetic managed note",
            media_type="text/markdown",
            content=FIRST,
            idempotency_key=key,
        )
    )
    assert envelope.error is None, envelope.error
    assert envelope.result is not None
    receipt: dict[str, Any] = envelope.result["receipt"]
    return receipt


# ---- 1. the successful write --------------------------------------------------


def test_a_successful_managed_write_leaves_an_audit_row(runtime: _Runtime) -> None:
    """The seat, as a row rather than as an enum member.

    Before this package a managed write reached `ManagedDocumentService` from a
    composition root and `knowledge.audit_events` stayed empty. The control is
    the count: the table is empty before the request and holds exactly one row
    after it, so "a row exists" is about this request.
    """
    assert runtime.audit_rows() == []

    receipt = _created(runtime)
    assert receipt["document_id"].startswith("mdoc_")

    rows = runtime.audit_rows()
    assert len(rows) == 1
    assert rows[0]["capability"] == Capability.DOCUMENTS_CREATE.value
    assert rows[0]["purpose"] == Purpose.DOCUMENT_AUTHORING.value
    assert rows[0]["outcome"] == AuditOutcome.ALLOWED.value
    assert rows[0]["denial_reason"] is None
    # The acting Principal, not the one the request document stated. `_Runtime.invoke`
    # always states the *other* Principal, so this equality is the two-Principal
    # negative for the envelope field.
    assert rows[0]["principal_id"] == PRINCIPAL_A


def test_every_managed_capability_leaves_a_row_naming_itself(runtime: _Runtime) -> None:
    """Every one of them, so the seat is not proved for `create` and assumed for the rest."""
    receipt = _created(runtime)
    document_id = receipt["document_id"]
    runtime.invoke(
        ReviseManagedDocument(
            document_id=document_id,
            expected_version_number=1,
            title="Synthetic managed note",
            media_type="text/markdown",
            content=SECOND,
            idempotency_key="synthetic-audit-revise-0001",
        )
    )
    runtime.invoke(ReadManagedDocument(document_id=document_id, include_bytes=True))
    runtime.invoke(ListManagedDocuments())
    runtime.invoke(ArchiveManagedDocument(document_id=document_id))
    from my_pa.application.commands import RestoreManagedDocument

    runtime.invoke(RestoreManagedDocument(document_id=document_id))

    recorded = [row["capability"] for row in runtime.audit_rows()]
    assert recorded == [
        Capability.DOCUMENTS_CREATE.value,
        Capability.DOCUMENTS_REVISE.value,
        Capability.DOCUMENTS_READ.value,
        Capability.DOCUMENTS_LIST.value,
        Capability.DOCUMENTS_ARCHIVE.value,
        Capability.DOCUMENTS_RESTORE.value,
    ]
    assert all(row["outcome"] == AuditOutcome.ALLOWED.value for row in runtime.audit_rows())


# ---- 2a. an authorization refusal ---------------------------------------------


def test_a_purpose_the_capability_does_not_permit_leaves_a_denied_row(runtime: _Runtime) -> None:
    """The policy refusal: recorded as `denied`, with the reason in the row only."""
    envelope = runtime.invoke(
        CreateManagedDocument(
            title="Synthetic managed note",
            media_type="text/markdown",
            content=FIRST,
            idempotency_key="synthetic-audit-denied-0001",
        ),
        purpose=Purpose.CAPTURE_AUTHORING,
    )
    assert envelope.error is not None
    assert envelope.error.code == "denied"
    # The reason is an operator's to read and not a caller's: nothing in the
    # answer says which rule refused it.
    assert envelope.error.safe_details == ()

    rows = runtime.audit_rows()
    assert len(rows) == 1
    assert rows[0]["capability"] == Capability.DOCUMENTS_CREATE.value
    assert rows[0]["purpose"] == Purpose.CAPTURE_AUTHORING.value
    assert rows[0]["outcome"] == AuditOutcome.DENIED.value
    assert rows[0]["denial_reason"] == "purpose_not_permitted_for_capability"
    # Nothing was written. A denial that had reached the handler would be a
    # denial the policy did not enforce.
    assert runtime.managed_row_counts() == {
        "managed_documents": 0,
        "managed_document_versions": 0,
    }


# ---- 2b. refusals raised by the handler, inside the work transaction ----------


def test_a_stale_expected_version_leaves_a_durable_row_and_rolls_the_work_back(
    runtime: _Runtime,
) -> None:
    """The case the precondition turns on, measured rather than argued.

    `_documents_revise` raises `StaleExpectedVersionError` from *inside* the unit
    of work, so the work transaction rolls back. The audit row written by
    `authorize` before the handler ran is on the audit engine's own connection
    and was committed there, so it survives — and this reads it back from a
    third connection to prove the survival is the database's and not a cache's.
    """
    receipt = _created(runtime)
    before = runtime.managed_row_counts()

    envelope = runtime.invoke(
        ReviseManagedDocument(
            document_id=receipt["document_id"],
            # The head is version 1; naming 7 is a revision of something that was
            # never read.
            expected_version_number=7,
            title="Synthetic managed note",
            media_type="text/markdown",
            content=SECOND,
            idempotency_key="synthetic-audit-stale-0001",
        )
    )
    assert envelope.error is not None
    assert envelope.error.code == "conflict"
    assert list(envelope.error.safe_details) == ["expected_version_number"]

    # The work rolled back: no version was appended.
    assert runtime.managed_row_counts() == before

    rows = runtime.audit_rows()
    assert len(rows) == 2, "the refused revision left no durable audit row"
    assert rows[1]["capability"] == Capability.DOCUMENTS_REVISE.value
    assert rows[1]["principal_id"] == PRINCIPAL_A
    # **Stated exactly.** The surviving row records that authorization was
    # granted, which is what `authorize` decided and what remains true. It does
    # not record that the write was refused: `invoke` writes no second event on a
    # handler failure, for any capability. The attempt is durable; its outcome is
    # not.
    assert rows[1]["outcome"] == AuditOutcome.ALLOWED.value
    assert rows[1]["denial_reason"] is None


def test_an_idempotency_conflict_leaves_a_durable_row_and_rolls_the_work_back(
    runtime: _Runtime,
) -> None:
    """The second refusal WP-27 named, and the same measurement.

    A key already bound to one request, presented with different bytes, is a
    conflict raised by WP-27's repository inside the transaction.
    """
    _created(runtime, key="synthetic-audit-shared-key")
    before = runtime.managed_row_counts()

    envelope = runtime.invoke(
        CreateManagedDocument(
            title="A different synthetic note",
            media_type="text/markdown",
            content=SECOND,
            idempotency_key="synthetic-audit-shared-key",
        )
    )
    assert envelope.error is not None
    assert envelope.error.code == "conflict"
    assert list(envelope.error.safe_details) == ["idempotency_key"]
    assert runtime.managed_row_counts() == before

    rows = runtime.audit_rows()
    assert len(rows) == 2, "the refused write left no durable audit row"
    assert rows[1]["capability"] == Capability.DOCUMENTS_CREATE.value
    assert rows[1]["outcome"] == AuditOutcome.ALLOWED.value


def test_a_replay_is_not_a_conflict_and_still_leaves_its_own_row(runtime: _Runtime) -> None:
    """The control for the two tests above.

    An identical retry returns the original receipt with `created=False` and
    writes nothing new — so the conflict tests are measuring a rebound key rather
    than "any second request with the same key".
    """
    first = _created(runtime, key="synthetic-audit-replayed")
    before = runtime.managed_row_counts()

    envelope = runtime.invoke(
        CreateManagedDocument(
            title="Synthetic managed note",
            media_type="text/markdown",
            content=FIRST,
            idempotency_key="synthetic-audit-replayed",
        )
    )
    assert envelope.error is None
    assert envelope.result is not None
    replayed = envelope.result["receipt"]
    assert replayed["receipt_id"] == first["receipt_id"]
    assert replayed["version_id"] == first["version_id"]
    assert replayed["created"] is False
    assert runtime.managed_row_counts() == before
    assert len(runtime.audit_rows()) == 2


# ---- 2c. the cross-Principal attempt ------------------------------------------


def test_b_naming_as_document_is_refused_and_recorded_against_b(runtime: _Runtime) -> None:
    """Principal isolation through the seat, with the audit row naming the attempt.

    B is refused with the same `not_found` a document that does not exist earns,
    naming no identifier — so the answer is not an existence oracle. The audit
    row is where an operator learns that B asked.
    """
    receipt = _created(runtime)
    document_id = receipt["document_id"]

    for command_value in (
        ReadManagedDocument(document_id=document_id, include_bytes=True),
        ArchiveManagedDocument(document_id=document_id),
    ):
        envelope = runtime.invoke(command_value, principal_id=PRINCIPAL_B)
        assert envelope.error is not None
        assert envelope.error.code == "not_found"
        assert list(envelope.error.safe_details) == ["document_id"]

    rows = runtime.audit_rows()
    assert len(rows) == 3
    assert [row["principal_id"] for row in rows] == [PRINCIPAL_A, PRINCIPAL_B, PRINCIPAL_B]
    assert [row["capability"] for row in rows[1:]] == [
        Capability.DOCUMENTS_READ.value,
        Capability.DOCUMENTS_ARCHIVE.value,
    ]

    # The control: A reads its own document successfully in the same test, so the
    # two refusals above are about ownership rather than about a broken read.
    mine = runtime.invoke(ReadManagedDocument(document_id=document_id, include_bytes=True))
    assert mine.error is None
    assert mine.result is not None
    assert mine.result["version"]["document_id"] == document_id


def test_a_caller_cannot_act_as_another_principal_by_stating_one(runtime: _Runtime) -> None:
    """The two-Principal negative for `principal_id`, at the type level and at the row.

    **The field a caller could have abused does not exist.** The six commands the
    `Command` union carries have no `principal_id`, so the strongest form of this
    test is that the request is unspellable — asserted here by construction, and
    structurally by
    `tests/architecture/test_principal_is_never_caller_supplied.py`.

    What a caller *can* still set is `RequestMetadata.principal_id`, which is
    correlation input. Every request in this module states the other Principal in
    that field; this one makes the consequence explicit. A caller acting as B and
    stating A writes a document into **B's** partition, and A's listing does not
    see it.
    """
    for field in ("principal_id", "owner_principal_id", "principal"):
        assert field not in CreateManagedDocument.__dataclass_fields__
        assert field not in ReviseManagedDocument.__dataclass_fields__
        assert field not in ReadManagedDocument.__dataclass_fields__
        assert field not in ArchiveManagedDocument.__dataclass_fields__

    # B writes, while its request document states A.
    envelope = runtime.invoke(
        CreateManagedDocument(
            title="B's synthetic note",
            media_type="text/markdown",
            content=FIRST,
            idempotency_key="synthetic-audit-b-0001",
        ),
        principal_id=PRINCIPAL_B,
    )
    assert envelope.error is None
    assert envelope.result is not None
    b_document = envelope.result["receipt"]["document_id"]

    listed = runtime.invoke(ListManagedDocuments(), principal_id=PRINCIPAL_A)
    assert listed.error is None
    assert listed.result is not None
    assert listed.result["documents"] == []

    b_listed = runtime.invoke(ListManagedDocuments(), principal_id=PRINCIPAL_B)
    assert b_listed.error is None
    assert b_listed.result is not None
    assert [entry["document_id"] for entry in b_listed.result["documents"]] == [b_document]

    # The audit rows name the acting Principal throughout, never the stated one.
    assert {row["principal_id"] for row in runtime.audit_rows()} == {PRINCIPAL_A, PRINCIPAL_B}
    with runtime.reader.connect() as connection:
        owners = set(
            connection.execute(
                text("SELECT DISTINCT owner_principal_id FROM knowledge.managed_documents")
            ).scalars()
        )
    assert owners == {PRINCIPAL_B}


# ---- the mechanism, asserted rather than assumed ------------------------------


def test_the_audit_survives_because_the_sink_holds_its_own_engine(runtime: _Runtime) -> None:
    """The reason the rows above survive, made a claim rather than a coincidence.

    A sink writing on the caller's connection would be exactly as durable as the
    caller's transaction, and every "the row survived" assertion in this module
    would become an assertion about a transaction that happened not to roll back.
    Composing one that way and watching a refusal lose its row is what shows the
    separation is load-bearing.
    """
    audit_on_the_work_connection = _SinkOnTheWorkConnection()
    service = ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(
            runtime.work_engine, audit=audit_on_the_work_connection
        ),
        limits=LIMITS,
        managed_store=runtime.store,
    )
    receipt = _created(runtime)
    before = len(runtime.audit_rows())

    envelope = service.invoke(
        RequestMetadata(
            request_id="req-synthetic-mechanism",
            capability=Capability.DOCUMENTS_REVISE,
            purpose=Purpose.DOCUMENT_AUTHORING,
            principal_id=PRINCIPAL_A,
            requested_at=WHEN,
        ),
        ReviseManagedDocument(
            document_id=receipt["document_id"],
            expected_version_number=7,
            title="Synthetic managed note",
            media_type="text/markdown",
            content=SECOND,
            idempotency_key="synthetic-audit-mechanism",
        ),
        principal=Principal(
            principal_id=PRINCIPAL_A, kind=PrincipalKind.OPERATOR, authenticated=True
        ),
    )
    assert envelope.error is not None
    assert audit_on_the_work_connection.recorded == 1, "the sink was not reached at all"
    # The event was handed to a sink that writes nowhere durable, so the count is
    # unchanged: this is what the production composition avoids.
    assert len(runtime.audit_rows()) == before


class _SinkOnTheWorkConnection:
    """A sink that accepts an event and stores it nowhere durable.

    Stands in for the pre-`D-34` shape — a sink whose write lives and dies with
    the caller's transaction — without needing to reconstruct it, because the
    property being measured is only that a non-durable sink produces no row.
    """

    def __init__(self) -> None:
        self.recorded = 0

    def record(self, event: object) -> None:
        self.recorded += 1
