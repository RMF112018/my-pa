"""Two synthetic Principals; zero review/promotion leakage (WP-05, R4, MU-AC-04).

Database tier, over a disposable database this module creates and drops. WP-03
proved the capture plane refuses cross-Principal reads; this is the same claim
one plane up, at the governed review and promotion records R4 introduces. What
is asserted here, before any live data exists, is that partitioning is real at
the layer that holds the rows:

* a review case is stamped with the *server-stored* owner of the capture it
  reviews and with nothing the caller could name (MU-AC-02); the owner is the
  only Principal whose list reaches it, and a foreign list is *empty*, not
  error-shaped differently (MU-AC-04);
* a decision aimed at another Principal's case is refused as
  `ReviewNotFoundError` — indistinguishable from a case that never existed —
  and the refusal writes no decision, leaving the case exactly as it was found
  (fails closed);
* the canonical rows a promotion creates — the assertion, its span citations,
  and the receipt — all carry the owner's partition, because promotion derives
  the partition from the same capture the case does, never from the deciding
  request's payload.

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

from my_pa.contracts.ports import ReviewDecisionRequest
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.capture.review import Disposition, ReviewNotFoundError
from my_pa.domain.capture.version import digest_of
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.principal_scope import capture_context
from my_pa.infrastructure.persistence.review import (
    decide_review,
    open_review_case,
    review_cases,
)

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

DISPOSABLE_DATABASE: Final = "my_pa_review_isolation_test"

#: Two synthetic Principals in the bound form `binding.capture_principal_id`
#: renders — 32 lowercase hex after `prn_` — the form every durable identity
#: arrives in once WP-03's binding is the only mint.
PRINCIPAL_A: Final = "prn_aaaa0001aaaaaaaaaaaaaaaa00000001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbbbbbbbbbbbbbb00000002"

WHEN: Final = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)

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
                    "knowledge.capture_spans, knowledge.capture_proposals, "
                    "knowledge.capture_proposal_spans, knowledge.capture_review_cases, "
                    "knowledge.capture_review_decisions, knowledge.capture_assertions, "
                    "knowledge.capture_assertion_spans, knowledge.capture_promotion_receipts "
                    "CASCADE"
                )
            )
        yield engine
    finally:
        engine.dispose()


def _seed_consequential_proposal(
    connection: Connection,
    owner: str,
    ordinal: int,
    *,
    span_digest: str | None = None,
) -> str:
    """One capture, version, span and commitment proposal owned by ``owner``.

    A commitment always routes to review regardless of confidence, so the
    proposal this returns is guaranteed to open a case. The owner is stamped on
    the capture and its version exactly as `admit_capture` would stamp it, so
    the review plane derives the same partition the capture plane already holds.
    A caller may supply a deliberately wrong span digest at creation time to
    exercise validation without attempting to rewrite immutable lineage.
    """
    ids = {
        "capture_id": f"cap_{ordinal:032d}",
        "version_id": f"capver_{ordinal:032d}",
        "span_id": f"span_{ordinal:032d}",
        "proposal_id": f"prop_{ordinal:032d}",
        "owner": owner,
        "correlation_id": issue_identifier(IdKind.CORRELATION),
        "audit_id": issue_identifier(IdKind.AUDIT),
        "digest": digest_of("x"),
        "span_digest": digest_of("x") if span_digest is None else span_digest,
    }
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.captures (capture_id, owner_principal_id) "  # noqa: S608
            "VALUES (:capture_id, :owner)"
        ),
        ids,
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_versions (version_id, capture_id, version_number, "  # noqa: S608
            "content, content_sha256, owner_principal_id, classification, processing_policy, "
            "idempotency_key, correlation_id, audit_id, server_received_at, accepted_at, "
            "recorded_at) VALUES (:version_id, :capture_id, 1, 'x', :digest, :owner, "
            "'synthetic_test', 'local_only', :version_id, :correlation_id, :audit_id, now(), "
            "now(), now())"
        ),
        ids,
    )
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.capture_spans (span_id, version_id, start_offset, end_offset, "  # noqa: S608
            "offset_basis, line_start, column_start, line_end, column_end, quoted_text_sha256, "
            "span_role) VALUES (:span_id, :version_id, 0, 1, 'unicode_code_point_v1', 1, 1, 1, 2, "
            ":span_digest, 'direct')"
        ),
        ids,
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
    return ids["proposal_id"]


def _decision(
    review_case_id: str, principal_id: str, disposition: Disposition
) -> ReviewDecisionRequest:
    return ReviewDecisionRequest(
        review_case_id=review_case_id,
        expected_review_version=0,
        disposition=disposition,
        principal_id=principal_id,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
        policy_version="policy-v1",
        decided_at=WHEN,
    )


def test_a_review_case_lists_only_under_the_capture_owners_partition(engine: Engine) -> None:
    """Each owner reaches its own case; neither reaches the other's (MU-AC-04).

    The two cases are opened in one transaction so the emptiness of a foreign
    list cannot be mistaken for a case that simply is not there yet. The stored
    ``principal_id`` on each returned case is the owner, which is what makes the
    scoping a partition and not a coincidence of ordering.
    """
    with engine.begin() as connection:
        proposal_a = _seed_consequential_proposal(connection, PRINCIPAL_A, 1)
        proposal_b = _seed_consequential_proposal(connection, PRINCIPAL_B, 2)
        case_a = open_review_case(connection, proposal_a)
        case_b = open_review_case(connection, proposal_b)
        assert case_a is not None
        assert case_b is not None

        mine = review_cases(connection, limit=10, context=capture_context(PRINCIPAL_A))
        theirs = review_cases(connection, limit=10, context=capture_context(PRINCIPAL_B))

    assert {case.review_case_id for case in mine} == {case_a}
    assert {case.review_case_id for case in theirs} == {case_b}
    assert all(case.principal_id == PRINCIPAL_A for case in mine)
    assert all(case.principal_id == PRINCIPAL_B for case in theirs)


def test_capture_state_filter_reaches_a_match_beyond_the_unfiltered_plane_limit(
    engine: Engine,
) -> None:
    """The state predicate belongs before LIMIT, not on the returned Python page."""
    with engine.begin() as connection:
        for ordinal in range(1, 4):
            proposal = _seed_consequential_proposal(connection, PRINCIPAL_A, ordinal)
            assert open_review_case(connection, proposal) is not None
        ordered = review_cases(connection, limit=10, context=capture_context(PRINCIPAL_A))
        for case in ordered[:2]:
            decide_review(
                connection,
                _decision(case.review_case_id, PRINCIPAL_A, Disposition.REJECT),
            )

        [found] = review_cases(
            connection,
            limit=1,
            context=capture_context(PRINCIPAL_A),
            state=ProposalState.NEEDS_REVIEW,
        )

    assert found.review_case_id == ordered[2].review_case_id


def test_capture_review_keyset_reaches_the_next_same_timestamp_case_without_repeating(
    engine: Engine,
) -> None:
    """The SQL keyset, not a fake merge, advances across an opened-at tie."""
    with engine.begin() as connection:
        for ordinal in range(1, 4):
            proposal = _seed_consequential_proposal(connection, PRINCIPAL_A, ordinal)
            assert open_review_case(connection, proposal) is not None

        expected = review_cases(connection, limit=3, context=capture_context(PRINCIPAL_A))
        first = review_cases(connection, limit=2, context=capture_context(PRINCIPAL_A))
        second = review_cases(
            connection,
            limit=2,
            context=capture_context(PRINCIPAL_A),
            after_opened_at=first[-1].opened_at,
            after_review_case_id=first[-1].review_case_id,
        )

    assert len({case.opened_at for case in expected}) == 1
    first_ids = [case.review_case_id for case in first]
    second_ids = [case.review_case_id for case in second]
    assert set(first_ids).isdisjoint(second_ids)
    assert first_ids + second_ids == [case.review_case_id for case in expected]
    assert len(second_ids) == 1


def test_a_foreign_decision_is_refused_and_writes_nothing(engine: Engine) -> None:
    """B deciding A's case is a nonexistent case to B, and the refusal is inert.

    The decision count for the case is read before and after the refused
    attempt: a guard that raised *after* appending a decision would leave the
    case one row heavier, and the equality is what proves it did not.
    """
    with engine.begin() as connection:
        proposal_a = _seed_consequential_proposal(connection, PRINCIPAL_A, 1)
        case_a = open_review_case(connection, proposal_a)
        assert case_a is not None

    with engine.connect() as connection:
        before = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.capture_review_decisions "  # noqa: S608
                "WHERE review_case_id = :case"
            ),
            {"case": case_a},
        ).scalar_one()
        with pytest.raises(ReviewNotFoundError):
            decide_review(connection, _decision(case_a, PRINCIPAL_B, Disposition.REJECT))
        after = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.capture_review_decisions "  # noqa: S608
                "WHERE review_case_id = :case"
            ),
            {"case": case_a},
        ).scalar_one()
    assert before == 0
    assert after == 0


def test_promotion_records_carry_the_owners_partition(engine: Engine) -> None:
    """Accept under the owner; the assertion, its spans, and the receipt are A's.

    Promotion is where a partition leak would be most consequential: a canonical
    assertion is the record the rest of the system trusts. Every row the
    acceptance creates is read back and asserted to carry ``PRINCIPAL_A`` — the
    owner of the reviewed capture — and none carry the identifier of any other
    Principal.
    """
    with engine.begin() as connection:
        proposal_a = _seed_consequential_proposal(connection, PRINCIPAL_A, 1)
        case_a = open_review_case(connection, proposal_a)
        assert case_a is not None
        decision = decide_review(connection, _decision(case_a, PRINCIPAL_A, Disposition.ACCEPT))
        assert decision is not None
        assert decision.assertion_id is not None
        assert decision.receipt_id is not None

        assertion_principal = connection.execute(
            text(
                f"SELECT principal_id FROM {SCHEMA}.capture_assertions "  # noqa: S608
                "WHERE assertion_id = :assertion"
            ),
            {"assertion": decision.assertion_id},
        ).scalar_one()
        span_principals = (
            connection.execute(
                text(
                    f"SELECT DISTINCT principal_id FROM {SCHEMA}.capture_assertion_spans "  # noqa: S608
                    "WHERE assertion_id = :assertion"
                ),
                {"assertion": decision.assertion_id},
            )
            .scalars()
            .all()
        )
        receipt_principal = connection.execute(
            text(
                f"SELECT principal_id FROM {SCHEMA}.capture_promotion_receipts "  # noqa: S608
                "WHERE receipt_id = :receipt"
            ),
            {"receipt": decision.receipt_id},
        ).scalar_one()

    assert assertion_principal == PRINCIPAL_A
    assert span_principals == [PRINCIPAL_A]
    assert receipt_principal == PRINCIPAL_A
