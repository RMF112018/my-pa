"""Capture-content validation stays inside the authenticated Principal partition.

The fixtures are synthetic and the database is disposable.  Both reads under
test use opaque identifiers, so a foreign row must have the same result as an
absent row: no content and no reported fault.  Each owned control deliberately
returns a non-empty result, making deletion of either ownership predicate fail.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Engine, text
from tests.security.test_cross_principal_review_isolation import (
    PRINCIPAL_A,
    PRINCIPAL_B,
    _seed_consequential_proposal,
    disposable_database,
)
from tests.security.test_cross_principal_review_isolation import engine

from my_pa.domain.capture.proposal import ProposalQuarantineReason
from my_pa.domain.capture.version import digest_of
from my_pa.infrastructure.persistence.principal_scope import capture_context
from my_pa.infrastructure.persistence.proposals import span_faults, version_content

_ = disposable_database

pytestmark = pytest.mark.database


def test_version_content_and_span_faults_are_principal_owned(engine: Engine) -> None:
    """Both ownership predicates are load-bearing for two Principals.

    The deliberately bad digest gives each owner a positive fault control.  If
    the ``span_faults`` ownership predicate is removed, the foreign calls return
    that fault.  If the ``version_content`` predicate is removed, the foreign
    calls return ``"x"``.  Missing identifiers are asserted beside both foreign
    results so the refusal discloses no row existence.
    """
    with engine.begin() as connection:
        proposal_a = _seed_consequential_proposal(connection, PRINCIPAL_A, 101)
        proposal_b = _seed_consequential_proposal(connection, PRINCIPAL_B, 202)
        version_a = "capver_00000000000000000000000000000101"
        version_b = "capver_00000000000000000000000000000202"
        connection.execute(
            text(
                "UPDATE knowledge.capture_spans SET quoted_text_sha256 = :wrong "
                "WHERE span_id IN (:span_a, :span_b)"
            ),
            {
                "wrong": digest_of("not x"),
                "span_a": "span_00000000000000000000000000000101",
                "span_b": "span_00000000000000000000000000000202",
            },
        )

    context_a = capture_context(PRINCIPAL_A)
    context_b = capture_context(PRINCIPAL_B)
    absent_version = "capver_99999999999999999999999999999999"
    absent_proposal = "prop_99999999999999999999999999999999"

    with engine.connect() as connection:
        assert version_content(connection, version_a, context=context_a) == "x"
        assert version_content(connection, version_b, context=context_b) == "x"
        assert version_content(connection, version_a, context=context_b) == version_content(
            connection, absent_version, context=context_b
        )
        assert version_content(connection, version_b, context=context_a) == version_content(
            connection, absent_version, context=context_a
        )

        assert tuple(
            fault.reason for fault in span_faults(connection, proposal_a, context=context_a)
        ) == (ProposalQuarantineReason.SPAN_TEXT_DOES_NOT_RE_DERIVE,)
        assert tuple(
            fault.reason for fault in span_faults(connection, proposal_b, context=context_b)
        ) == (ProposalQuarantineReason.SPAN_TEXT_DOES_NOT_RE_DERIVE,)
        assert span_faults(connection, proposal_a, context=context_b) == span_faults(
            connection, absent_proposal, context=context_b
        )
        assert span_faults(connection, proposal_b, context=context_a) == span_faults(
            connection, absent_proposal, context=context_a
        )
