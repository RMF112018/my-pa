"""Create the Entity plane's review decision ledger, and one index beside it.

`WP-RI-B-05` (`MYPA-RI-COMP-04`). One table is created --
`knowledge.entity_proposal_review_decisions` -- and one partial unique index is
added to `knowledge.entity_proposals`. No existing column is altered and no
existing constraint is restated, so this composes with the other Phase B
revisions in any order the integration owner lands them.

**Why the Entity plane needs a decision ledger of its own.** The canonical Review
surface carries four subject kinds, and each brings its own ledger:
`capture_review_decisions`, `goodnotes_review_decisions` and
`relationship_memory_review_decisions` are the other three. One shared table
would need a foreign key able to name four different proposal tables, which is
the polymorphic reference this schema refuses everywhere else.

**`review_version` is the count of rows here, and that is why a table was needed
rather than a column.** Operator section 27 requires that a stale review version
write nothing. A version derived from "has this proposal been decided" can only
ever be zero or one, which would make `escalate` unrecordable -- an escalated
case is one a reviewer has acted on *and* an operator has still to decide.
`UNIQUE (review_case_id, sequence)` is what makes two reviewers who both read
version 0 produce one decision rather than two.

**`corrected_payload` never overwrites the proposal's own.**
`entity_proposals.payload` is the producer's assertion and stays exactly that;
`dedupe_sha256` is a digest over that kind and that payload, so writing the
reviewer's version over it would leave the digest describing something nobody
proposed. The correction lives on the decision, which is the same shape
`relationship_memory_review_decisions.corrected_statement` has.

**The vocabularies are written out and frozen at this revision** (decision
`D-69`): eight dispositions in `an_entity_review_disposition_is_known`, and the
five reasoned dispositions and the two that require a reason spelled as literals
in their own CHECKs. None of them is derived from a Python enum, so a widening of
`Disposition` cannot change what rows already stored under this revision mean.
`downgrade` drops what `upgrade` created and nothing else.

**One thing this revision does NOT do and B7 must:** adding `invalidate` to
`Disposition` widens two CHECKs that already exist --
`capture_review_decisions.review_disposition_is_known` (revision at
`tables.py:1863`) and
`relationship_memory_review_decisions.a_memory_review_disposition_is_known`.
Both are generated from the enum in `tables.py` and both are frozen literals in
the revisions that created them. A database migrated to the current head will
refuse an `invalidate` row on either table until those two CHECKs are widened.
The Entity plane does not need it -- this revision spells eight from the start --
but `review.decide` is one capability over four planes, and a reviewer
invalidating a capture case would be refused by the column.
"""

from __future__ import annotations

from typing import Final

from alembic import op

# Third in the Phase B chain. Its composite foreign key needs
# `a_proposal_is_identified_within_its_principal`, which `c7a1f04b9e63`'s
# predecessor already provides, so the placement is an ordering and not a
# dependency this file could relax.
revision: str = "e5b0c94d7182"
down_revision: str | None = "d38e6b2fa715"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: The suffix rule `domain.common.identifiers.validate_identifier` enforces,
#: restated as the POSIX form the server can check.
_IDENTIFIER_SUFFIX: Final = "[A-Za-z0-9]{8,64}"

#: Longest a stated reason may be, matching `entity_proposals.decision_reason`
#: and `REVIEW_REASON_LIMIT`, so a reason the request accepted cannot be refused
#: by the column.
_REASON_LIMIT: Final = 500

# --- the frozen vocabularies, sorted -----------------------------------------

_DISPOSITION_VALUES: Final = (
    "'accept', 'correct_and_accept', 'defer', 'escalate', 'invalidate', "
    "'mark_unresolved', 'reject', 'reprocess'"
)

#: The five operator section 13 gives a reason.
_REASONED_DISPOSITION_VALUES: Final = (
    "'defer', 'escalate', 'invalidate', 'mark_unresolved', 'reject'"
)

#: The two that cannot be recorded without one.
_REASON_REQUIRED_DISPOSITION_VALUES: Final = "'escalate', 'invalidate'"


def upgrade() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_proposal_review_decisions (
          decision_id text PRIMARY KEY,
          proposal_id text NOT NULL,
          review_case_id text NOT NULL,
          principal_id text NOT NULL,
          sequence integer NOT NULL,
          disposition text NOT NULL,
          reason text,
          corrected_payload jsonb,
          correlation_id text NOT NULL,
          audit_id text NOT NULL,
          decided_at timestamptz NOT NULL,
          CONSTRAINT decision_id_is_an_opaque_identifier
            CHECK (decision_id ~ '^rdec_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT proposal_id_is_an_opaque_identifier
            CHECK (proposal_id ~ '^eprp_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT review_case_id_is_an_opaque_identifier
            CHECK (review_case_id ~ '^rvw_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT correlation_id_is_an_opaque_identifier
            CHECK (correlation_id ~ '^corr_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT audit_id_is_an_opaque_identifier
            CHECK (audit_id ~ '^audit_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_entity_review_disposition_is_known
            CHECK (disposition IN ({_DISPOSITION_VALUES})),
          CONSTRAINT an_entity_review_sequence_is_positive
            CHECK (sequence >= 1),
          CONSTRAINT an_entity_correction_matches_its_disposition
            CHECK ((disposition = 'correct_and_accept') = (corrected_payload IS NOT NULL)),
          CONSTRAINT an_entity_review_reason_explains_a_departure
            CHECK (reason IS NULL
                   OR disposition IN ({_REASONED_DISPOSITION_VALUES})),
          CONSTRAINT an_escalation_or_invalidation_states_why
            CHECK (disposition NOT IN ({_REASON_REQUIRED_DISPOSITION_VALUES})
                   OR reason IS NOT NULL),
          CONSTRAINT an_entity_review_reason_is_bounded
            CHECK (reason IS NULL OR length(trim(reason)) BETWEEN 1 AND {_REASON_LIMIT}),
          CONSTRAINT one_entity_decision_per_review_sequence
            UNIQUE (review_case_id, sequence),
          CONSTRAINT an_entity_review_decision_names_a_proposal_of_its_principal
            FOREIGN KEY (proposal_id, principal_id)
            REFERENCES {SCHEMA}.entity_proposals (proposal_id, principal_id)
            ON DELETE CASCADE
        );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_proposal_review_decisions_by_case
          ON {SCHEMA}.entity_proposal_review_decisions (review_case_id, sequence);
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_proposal_review_decisions_by_principal
          ON {SCHEMA}.entity_proposal_review_decisions (principal_id);
        """
    )
    # A review case names one proposal. `capture_review_cases` makes that
    # structural with a `UNIQUE` on its own `proposal_id`; this plane keeps the
    # case identifier on the proposal, so the same sentence is a partial unique
    # index -- partial because a kind a configured threshold may accept opens no
    # case at all and many such rows carry NULL together.
    op.execute(
        f"""
        CREATE UNIQUE INDEX a_review_case_names_one_entity_proposal
          ON {SCHEMA}.entity_proposals (review_case_id)
          WHERE review_case_id IS NOT NULL;
        """
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.a_review_case_names_one_entity_proposal;")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA}.entity_proposal_review_decisions;")
