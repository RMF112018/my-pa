"""Two synthetic Principals; zero capture-plane leakage (WP-03, `PKL-MYPA-D-WP03-001`).

Database tier, over a disposable database this module creates and drops. The
subject is the acceptance gate for R2's product-owned capture: `D-72` stored an
owner and enforced nothing on it, and the ratified campaign is the operator
decision that supersedes that posture. What is asserted here, before any live
data exists, is that the enforcement is real at the layer that holds the rows:

* a capture one Principal admitted is unreachable by another through **every**
  read the plane offers — version read, list, and search — and unreachable
  means *indistinguishable from nonexistent*, not error-shaped differently;
* the idempotency key's collision domain is the Principal's own submissions
  (revision `e7f3a9c2d514`): two Principals may hold the same key without
  colliding, a same-key same-content replay returns the original receipt with
  `created=False`, and a same-key different-content submission is refused;
* a request whose payload names a Principal other than the authenticated one
  is refused before anything is written (MU-AC-02), and the refusal stores
  nothing;
* the rows a cross-Principal attempt leaves behind — receipts and audit
  events — carry no capture text (`QC-AC-041` discipline; the full redaction
  criterion lives in `test_capture_redaction.py`).

Every identity is synthetic and every value is invented; no path is opened, no
source is reached, and the configured corpus is never touched.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Connection, Engine, text

from my_pa.contracts.ports import (
    CaptureAdmission,
    CaptureAdmissionRequest,
    CaptureSearchRequest,
    UnknownScopeError,
)
from my_pa.domain.capture.errors import CaptureConflictError
from my_pa.domain.capture.version import CaptureContent, ProcessingPolicy
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.user_account import CallerSuppliedPrincipalError
from my_pa.domain.search.query import SearchQuery
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.capture import admit_capture, capture_page, capture_version
from my_pa.infrastructure.persistence.capture_search import search_captures
from my_pa.infrastructure.persistence.principal_scope import capture_context

ROOT: Final = Path(__file__).resolve().parents[2]

DISPOSABLE_DATABASE: Final = "my_pa_capture_isolation_test"

#: Two synthetic Principals in the bound form `binding.capture_principal_id`
#: renders — 32 lowercase hex after `prn_` — because that is the form every
#: durable identity arrives in once WP-03's binding is the only mint.
PRINCIPAL_A: Final = "prn_aaaa0001aaaaaaaaaaaaaaaa00000001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbbbbbbbbbbbbbb00000002"

#: The one sensitive string in this module. Distinctive enough that a substring
#: scan over receipts and audit rows cannot miss a leak by coincidence.
NOTE: Final = "synthetic-isolation-note: the quarterly figures live in the red folder"

WHEN: Final = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)
ACCEPTED: Final = datetime(2026, 8, 5, 9, 1, tzinfo=UTC)

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
            connection.execute(
                text(
                    "TRUNCATE knowledge.captures, knowledge.capture_versions, "
                    "knowledge.capture_receipts, knowledge.capture_submissions, "
                    "knowledge.capture_jobs, knowledge.audit_events CASCADE"
                )
            )
        yield engine
    finally:
        engine.dispose()


def _request(
    principal_id: str,
    *,
    key: str,
    body: str = NOTE,
    capture_id: str | None = None,
) -> CaptureAdmissionRequest:
    return CaptureAdmissionRequest(
        capture_id=capture_id,
        content=CaptureContent(body),
        idempotency_key=key,
        request_id=f"req-{key}-{principal_id[-8:]}",
        correlation_id=issue_identifier(IdKind.CORRELATION),
        principal_id=principal_id,
        audit_id=issue_identifier(IdKind.AUDIT),
        classification=Classification.PRIVATE_LOCAL,
        processing_policy=ProcessingPolicy.LOCAL_ONLY,
        server_received_at=WHEN,
        accepted_at=ACCEPTED,
    )


def _admit(
    connection: Connection,
    principal_id: str,
    *,
    key: str,
    body: str = NOTE,
    capture_id: str | None = None,
) -> CaptureAdmission:
    return admit_capture(
        connection,
        _request(principal_id, key=key, body=body, capture_id=capture_id),
        context=capture_context(principal_id),
    )


def test_the_capture_is_bound_to_the_authenticated_principal_at_admission(
    engine: Engine,
) -> None:
    """The stored owner is the context's Principal, and payload identity is refused.

    Two halves of the same admission-time binding: what is stored names the
    authenticated Principal, and a payload naming anyone else never reaches the
    store. The count after the refusal is the enforcement of "fails closed" —
    a rejected identity must not leave a half-admitted capture behind.
    """
    with engine.begin() as connection:
        admitted = _admit(connection, PRINCIPAL_A, key="key-binding")
        stored = connection.execute(
            text("SELECT owner_principal_id FROM knowledge.capture_versions")
        ).scalar_one()
    assert admitted.created is True
    assert stored == PRINCIPAL_A

    with engine.connect() as connection:
        with pytest.raises(CallerSuppliedPrincipalError):
            admit_capture(
                connection,
                _request(PRINCIPAL_B, key="key-forged"),
                context=capture_context(PRINCIPAL_A),
            )
        submissions = connection.execute(
            text("SELECT count(*) FROM knowledge.capture_submissions")
        ).scalar_one()
    assert submissions == 1, (
        "a submission whose payload named a foreign Principal was stored, so "
        "the refusal did not fail closed"
    )


def test_the_idempotency_key_collides_within_one_principal_and_not_across_two(
    engine: Engine,
) -> None:
    """One key, two Principals, three outcomes — and each is the right one.

    A and B admit under the *same* key and both succeed, which is revision
    `e7f3a9c2d514`'s two-column constraint doing its work. A's exact replay
    returns A's original receipt with `created=False` — not B's, which is what
    the two-column replay lookup exists to guarantee. A's same-key,
    different-content submission is refused.
    """
    with engine.begin() as connection:
        first_a = _admit(connection, PRINCIPAL_A, key="key-shared")
        first_b = _admit(connection, PRINCIPAL_B, key="key-shared")
        assert first_a.created is True
        assert first_b.created is True
        assert first_a.receipt.receipt_id != first_b.receipt.receipt_id

        replay = _admit(connection, PRINCIPAL_A, key="key-shared")
        assert replay.created is False
        assert replay.receipt == first_a.receipt

    with engine.connect() as connection, pytest.raises(CaptureConflictError):
        _admit(connection, PRINCIPAL_A, key="key-shared", body="different words entirely")


def test_a_foreign_capture_answers_exactly_what_a_nonexistent_one_answers(
    engine: Engine,
) -> None:
    """Read, list, search, revise: four paths, zero disclosure, in both directions.

    The assertions are equalities with the nonexistent case, not merely
    emptiness: `None` from the read, an empty page, a search whose *counts* are
    zero — `stored_versions` included, because a true count over another
    Principal's rows would disclose how much they have written — and the same
    `UnknownScopeError` from a revise that a made-up identifier earns.
    """
    with engine.begin() as connection:
        admitted = _admit(connection, PRINCIPAL_A, key="key-foreign")
    capture_id = admitted.receipt.capture_id
    ours = capture_context(PRINCIPAL_A)
    theirs = capture_context(PRINCIPAL_B)
    request = CaptureSearchRequest(query=SearchQuery("quarterly figures"), limit=10)

    with engine.connect() as connection:
        # The owner reaches everything, so the emptiness below is scoping.
        assert capture_version(connection, capture_id, context=ours) is not None
        assert len(capture_page(connection, limit=10, context=ours)) == 1
        assert search_captures(connection, request, context=ours).stored_versions == 1

        assert capture_version(connection, capture_id, context=theirs) is None
        assert capture_page(connection, limit=10, context=theirs) == ()
        foreign = search_captures(connection, request, context=theirs)
        assert foreign.matches == ()
        assert foreign.stored_versions == 0
        assert foreign.searchable_versions == 0

    with engine.connect() as connection, pytest.raises(UnknownScopeError):
        _admit(connection, PRINCIPAL_B, key="key-revise-foreign", capture_id=capture_id)


def test_no_capture_text_reaches_receipts_or_audit_rows(engine: Engine) -> None:
    """`QC-AC-041` discipline at the store: the rows about a capture never quote it.

    A substring scan over every receipt and audit column, serialized crudely on
    purpose — the leak this guards against is a column *added* to either table
    that happens to carry text, which a column-by-column assertion would not
    notice until someone remembered to extend it.
    """
    with engine.begin() as connection:
        _admit(connection, PRINCIPAL_A, key="key-redaction")
    with engine.connect() as connection:
        receipts = connection.execute(text("SELECT r.* FROM knowledge.capture_receipts r")).all()
        audits = connection.execute(text("SELECT a.* FROM knowledge.audit_events a")).all()
    assert receipts, "the admission issued no receipt, so the scan proves nothing"
    for row in (*receipts, *audits):
        assert NOTE not in repr(tuple(row)), (
            "capture text appeared in a receipt or audit row, which is the one "
            "place QC-AC-041 most expects it to leak"
        )
