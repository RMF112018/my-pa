"""Widen the entity proposal record and give it its own evidence table.

Revision ID: c7a1f04b9e63
Revises: c4b0a1d9e827
Create Date: 2026-08-24

**Why B1 did not land this.** `823e23b6cc63`'s docstring records the rule: three
work packages each adding a revision would produce three heads and three
conflicting restatements of one vocabulary. Phase B repeats that discipline, so
every Phase B revision is B7's. This file is B1's exact requirement, written out
so B7 lands it rather than reconstructs it.

**What it does.**

`knowledge.entity_proposals` grows from six kinds to seventeen and from four
states to eight (`MYPA-RI-COMP-03`), gains the method and model identity that say
what produced a proposal, the digest that makes an open-equivalent duplicate a
server refusal, the review case and accepted-record columns that let a decision
be traced to what it produced, and the two moments the four-state record could
not express. `knowledge.entity_proposal_evidence_links` is new: the same
one-evidence discipline `entity_fact_evidence_links` states for a canonical fact,
applied to a proposal, which until now could cite only observations and could not
say that one of them argued against it.

**It refuses to run against a non-empty `entity_proposals`, and that refusal is
the honest option rather than the cautious one.** `dedupe_sha256` is NOT NULL and
is the SHA-256 of a compact key-sorted JSON encoding of the kind and the payload,
produced by `domain.relationship.proposal_payload.dedupe_digest`. A SQL backfill
would have to reproduce that encoding, and a second implementation of a canonical
encoding is exactly the divergence this repository refuses elsewhere -- the
`str.strip()`-versus-`trim()` note on `EDGE_WHITESPACE` is the same failure read
in a different column. Importing the Python function into a revision is worse
still: `D-69` forbids a frozen revision from tracking live code.

So the migration aborts and says why, which `MYPA-RI-COMP-04` sanctions
("Unknown legacy state or conflicts abort; migration never guesses") and
`2fe4e13fb449` already does four times over. The abort is safe in fact as well as
in principle: nothing publishes a capability that writes `entity_proposals` at
`823e23b6cc63` -- `EntityGovernanceService.propose` is reachable only from this
repository's own tests -- so every environment's copy of the table is empty. If a
row is ever found, a human decides what its digest should be; this migration does
not.

`method` and `method_version` are NOT NULL for the same reason and are covered by
the same abort, rather than being defaulted to `'deterministic'`. A default would
be *true* of every row that could exist today, and would still be a migration
asserting on a row's behalf what produced it.

**The closed sets below are frozen literals** (`D-69`), written out and not
derived from `EntityProposalKind`, `EntityProposalState`, `EntityProposalMethod`,
`MutationRecordFamily` or `EvidenceRole`. A database migrated to this revision
holds the vocabulary this revision describes, whatever the domain says on the day
it runs.

**The enum-derivation guard, checked rather than assumed.**
`tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum` reports
any revision whose emitted CHECK vocabulary exactly equals a live domain closed
set. It reads `Table` objects handed to `create_all`; this revision holds none
and does all of its work through `op.execute`, which is the shape
`2fe4e13fb449`, `9d4e7a3b1c62` and `7f2a9d6c4e18` already have and which that
guard cannot read -- PR #154's non-blocking observation 1 is exactly this blind
spot. That is a *reason to look*, not a reason to relax: the eight-state and
seventeen-kind literals here do equal the enums today, and if B7 closes the
observation the allowlist in that test file must gain these sites explicitly.

**No capability and no purpose is admitted here.** `entities.proposals.create`,
`relationship_memory.propose`, `entities.merge.preview`, `entities.merge` and the
three new purposes belong to B7's single vocabulary-widening revision on
`knowledge.audit_events`, for the reason `823e23b6cc63` states.

`downgrade` restores `d2b8f5c04e71`'s six kinds and four states exactly, drops
every column and index this revision adds and drops the new table, so
empty -> head -> empty leaves no residue.
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "c7a1f04b9e63"
down_revision: str | None = "c4b0a1d9e827"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: The suffix rule `domain.common.identifiers.validate_identifier` enforces,
#: restated as the POSIX form the server can check.
_IDENTIFIER_SUFFIX: Final = "[A-Za-z0-9]{8,64}"

#: Longest a stored explanation of one change may be
#: (`governance.ENTITY_CHANGE_REASON_LIMIT`), restated and frozen.
_REASON_LIMIT: Final = 500

#: Longest a method or model version token may be
#: (`governance.PROPOSAL_METHOD_VERSION_LIMIT`), restated and frozen.
_VERSION_TOKEN_LIMIT: Final = 32

# --- the frozen vocabularies, sorted -----------------------------------------

_PROPOSAL_KIND_VALUES_AT_THIS_REVISION: Final = (
    "'bind_identifier', 'create_entity', 'end_assignment', 'end_relationship', "
    "'merge_entities', 'record_alias', 'record_assignment', "
    "'record_relationship', 'resolve_mention', 'retire_alias', "
    "'retire_identifier', 'revise_assignment', 'revise_relationship', "
    "'split_identity', 'supersede_alias', 'supersede_identifier', "
    "'update_entity'"
)

_PROPOSAL_KIND_VALUES_BEFORE_THIS_REVISION: Final = (
    "'bind_identifier', 'create_entity', 'merge_entities', 'record_alias', "
    "'record_assignment', 'record_relationship'"
)

_PROPOSAL_STATE_VALUES_AT_THIS_REVISION: Final = (
    "'accepted', 'corrected_accepted', 'deferred', 'invalidated', "
    "'needs_review', 'proposed', 'rejected', 'superseded'"
)

_PROPOSAL_STATE_VALUES_BEFORE_THIS_REVISION: Final = (
    "'accepted', 'proposed', 'rejected', 'superseded'"
)

_PROPOSAL_METHOD_VALUES: Final = "'deterministic', 'local_model', 'rule'"

#: The states in which a reviewer has made the call. Five where the previous
#: revision named two: a deferral, an invalidation and a corrected acceptance are
#: all somebody having decided. `superseded` is deliberately absent — a proposal
#: a successor overtook was disposed of by nobody, and it carries `superseded_at`.
_DECIDED_STATE_VALUES: Final = (
    "'accepted', 'corrected_accepted', 'deferred', 'invalidated', 'rejected'"
)

_ACCEPTED_STATE_VALUES: Final = "'accepted', 'corrected_accepted'"

#: The states in which a second identical proposal would be a duplicate.
#: `deferred` is among them: without it, re-filing would clear a deferral.
_OPEN_EQUIVALENT_STATE_VALUES: Final = "'deferred', 'needs_review', 'proposed'"

#: The two kinds whose acceptance changes no identity (operator prompt §15).
_IDENTITY_CORRECTION_KIND_VALUES: Final = "'merge_entities', 'split_identity'"

#: `MutationRecordFamily`, restated. The families a promotion can produce.
_RECORD_FAMILY_VALUES: Final = (
    "'alias', 'assignment', 'entity', 'identifier', 'observation', 'relationship'"
)

#: `EvidenceRole`, restated.
_EVIDENCE_ROLE_VALUES: Final = "'counterevidence', 'direct', 'supporting'"


#: Written as a plain string with the schema spelled out rather than
#: interpolated. `ruff` reads an f-string holding a `SELECT` as a query built
#: by concatenation (`S608`), and it is right to: the fix is to stop building
#: one, not to silence the rule. The schema name is a frozen literal in a
#: revision anyway, which is what every other literal in this file is.
_ABORT_ON_AN_EXISTING_PROPOSAL: Final = """
    DO $$
    DECLARE
      affected bigint;
    BEGIN
      SELECT count(*) INTO affected FROM knowledge.entity_proposals;
      IF affected > 0 THEN
        RAISE EXCEPTION USING MESSAGE =
          'knowledge.entity_proposals holds ' || affected || ' row(s), and this '
          || 'migration adds three NOT NULL columns it cannot fill for them. '
          || 'dedupe_sha256 is the digest of a canonical JSON encoding produced '
          || 'in Python; reproducing that encoding in SQL would be a second, '
          || 'divergent implementation of it, and method/method_version state '
          || 'what produced a proposal, which no migration may assert on a '
          || 'writer''s behalf. No published capability writes this table at the '
          || 'preceding revision, so an empty table is the expected state. '
          || 'Decide what these rows should carry, backfill them through the '
          || 'application, and run this again; this migration does not guess.';
      END IF;
    END $$;
    """


def upgrade() -> None:
    op.execute(_ABORT_ON_AN_EXISTING_PROPOSAL)

    # The two closed sets, widened. Dropped and recreated rather than altered,
    # because PostgreSQL has no ALTER CONSTRAINT for a CHECK expression.
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_proposals
          DROP CONSTRAINT a_proposal_kind_is_known,
          DROP CONSTRAINT a_proposal_state_is_known,
          DROP CONSTRAINT a_proposal_is_decided_exactly_when_something_decided_it,
          ADD CONSTRAINT a_proposal_kind_is_known
            CHECK (kind IN ({_PROPOSAL_KIND_VALUES_AT_THIS_REVISION})),
          ADD CONSTRAINT a_proposal_state_is_known
            CHECK (state IN ({_PROPOSAL_STATE_VALUES_AT_THIS_REVISION})),
          ADD CONSTRAINT a_proposal_is_decided_exactly_when_something_decided_it
            CHECK ((state IN ({_DECIDED_STATE_VALUES})) = (decided_by IS NOT NULL))
        """
    )

    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_proposals
          ADD COLUMN method text NOT NULL,
          ADD COLUMN method_version text NOT NULL,
          ADD COLUMN dedupe_sha256 text NOT NULL,
          ADD COLUMN model_id text,
          ADD COLUMN model_version text,
          ADD COLUMN expected_target_version integer,
          ADD COLUMN review_case_id text,
          ADD COLUMN accepted_record_type text,
          ADD COLUMN accepted_record_id text,
          ADD COLUMN accepted_record_version integer,
          ADD COLUMN invalidated_reason text,
          ADD COLUMN superseded_at timestamptz,
          ADD COLUMN superseded_by_proposal_id text
        """
    )

    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_proposals
          ADD CONSTRAINT a_proposal_method_is_known
            CHECK (method IN ({_PROPOSAL_METHOD_VALUES})),
          ADD CONSTRAINT an_accepted_proposal_record_family_is_known
            CHECK (accepted_record_type IN ({_RECORD_FAMILY_VALUES})),
          ADD CONSTRAINT a_proposal_dedupe_digest_is_a_sha256_digest
            CHECK (dedupe_sha256 ~ '^[0-9a-f]{{64}}$'),
          ADD CONSTRAINT proposal_method_and_model_versions_are_bounded_tokens
            CHECK (
              length(method_version) BETWEEN 1 AND {_VERSION_TOKEN_LIMIT}
              AND (model_id IS NULL
                   OR length(model_id) BETWEEN 1 AND {_VERSION_TOKEN_LIMIT})
              AND (model_version IS NULL
                   OR length(model_version) BETWEEN 1 AND {_VERSION_TOKEN_LIMIT})
            ),
          ADD CONSTRAINT a_model_proposal_names_its_model
            CHECK ((method = 'local_model') = (model_id IS NOT NULL)),
          ADD CONSTRAINT a_named_proposal_model_states_its_version
            CHECK ((model_id IS NULL) = (model_version IS NULL)),
          ADD CONSTRAINT a_proposal_expected_target_version_is_positive
            CHECK (expected_target_version IS NULL OR expected_target_version > 0),
          ADD CONSTRAINT a_proposal_names_its_record_only_when_accepted
            CHECK (
              accepted_record_id IS NULL
              OR state IN ({_ACCEPTED_STATE_VALUES})
            ),
          ADD CONSTRAINT an_accepted_identity_correction_names_no_record
            CHECK (
              accepted_record_id IS NULL
              OR kind NOT IN ({_IDENTITY_CORRECTION_KIND_VALUES})
            ),
          ADD CONSTRAINT an_accepted_proposal_record_is_named_in_full
            CHECK (
              (accepted_record_type IS NULL) = (accepted_record_id IS NULL)
              AND (accepted_record_id IS NULL) = (accepted_record_version IS NULL)
            ),
          ADD CONSTRAINT an_accepted_proposal_record_version_is_positive
            CHECK (accepted_record_version IS NULL OR accepted_record_version > 0),
          ADD CONSTRAINT an_invalidated_proposal_records_why
            CHECK ((state = 'invalidated') = (invalidated_reason IS NOT NULL)),
          ADD CONSTRAINT a_proposal_invalidation_reason_is_bounded
            CHECK (
              invalidated_reason IS NULL
              OR length(invalidated_reason) BETWEEN 1 AND {_REASON_LIMIT}
            ),
          ADD CONSTRAINT a_superseded_proposal_records_when
            CHECK ((state = 'superseded') = (superseded_at IS NOT NULL)),
          ADD CONSTRAINT a_proposal_is_not_superseded_before_it_was_proposed
            CHECK (superseded_at IS NULL OR superseded_at >= proposed_at),
          ADD CONSTRAINT only_a_superseded_proposal_names_its_successor
            CHECK (superseded_by_proposal_id IS NULL OR state = 'superseded'),
          ADD CONSTRAINT a_proposal_is_not_its_own_successor
            CHECK (superseded_by_proposal_id IS NULL
                   OR superseded_by_proposal_id <> proposal_id),
          ADD CONSTRAINT a_proposal_is_superseded_within_its_principal
            FOREIGN KEY (superseded_by_proposal_id, principal_id)
            REFERENCES {SCHEMA}.entity_proposals(proposal_id, principal_id)
        """
    )

    # Partial rather than total, and the predicate is the rule. A total unique
    # would mean a proposal refused once could never be raised again on new
    # evidence, which section 15.2 requires to be possible; no unique at all
    # would let a producer put the same candidate in front of a reviewer on
    # every run.
    op.execute(
        f"""
        CREATE UNIQUE INDEX an_open_equivalent_proposal_is_raised_once
          ON {SCHEMA}.entity_proposals (principal_id, dedupe_sha256)
          WHERE state IN ({_OPEN_EQUIVALENT_STATE_VALUES});
        """
    )

    # `(proposal_id, sequence)` and no opaque link identifier: this plane issues
    # a prefix when something has to point at the record, and nothing points at
    # a proposal's evidence. The same ordering key `entity_resolution_decisions`
    # uses. No `authority` column either — a proposal has none, which is what
    # makes it a proposal; the authority a promotion carries is recorded on the
    # fact it produces, in `entity_fact_evidence_links`.
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_proposal_evidence_links (
          proposal_id text NOT NULL,
          sequence integer NOT NULL,
          principal_id text NOT NULL,
          role text NOT NULL,
          entity_observation_id text,
          capture_span_id text,
          knowledge_id text,
          created_at timestamptz NOT NULL DEFAULT now(),
          PRIMARY KEY (proposal_id, sequence),
          CONSTRAINT proposal_id_is_an_opaque_identifier
            CHECK (proposal_id ~ '^eprp_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT a_proposal_evidence_role_is_known
            CHECK (role IN ({_EVIDENCE_ROLE_VALUES})),
          CONSTRAINT proposal_evidence_is_numbered_from_one
            CHECK (sequence > 0),
          CONSTRAINT proposal_evidence_names_exactly_one_record
            CHECK (
              (entity_observation_id IS NOT NULL)::int
              + (capture_span_id IS NOT NULL)::int
              + (knowledge_id IS NOT NULL)::int = 1
            ),
          CONSTRAINT proposal_evidence_names_a_proposal_of_its_principal
            FOREIGN KEY (proposal_id, principal_id)
            REFERENCES {SCHEMA}.entity_proposals(proposal_id, principal_id)
            ON DELETE CASCADE,
          CONSTRAINT proposal_evidence_cites_an_observation_of_its_principal
            FOREIGN KEY (entity_observation_id, principal_id)
            REFERENCES {SCHEMA}.entity_observations(observation_id, principal_id)
            ON DELETE CASCADE
        );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_proposal_evidence_links_by_principal
          ON {SCHEMA}.entity_proposal_evidence_links (principal_id);
        CREATE INDEX entity_proposal_evidence_links_by_observation
          ON {SCHEMA}.entity_proposal_evidence_links (entity_observation_id);
        """
    )


def downgrade() -> None:
    op.execute(f"DROP TABLE {SCHEMA}.entity_proposal_evidence_links")
    op.execute(f"DROP INDEX {SCHEMA}.an_open_equivalent_proposal_is_raised_once")
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_proposals
          DROP CONSTRAINT a_proposal_method_is_known,
          DROP CONSTRAINT an_accepted_proposal_record_family_is_known,
          DROP CONSTRAINT a_proposal_dedupe_digest_is_a_sha256_digest,
          DROP CONSTRAINT proposal_method_and_model_versions_are_bounded_tokens,
          DROP CONSTRAINT a_model_proposal_names_its_model,
          DROP CONSTRAINT a_named_proposal_model_states_its_version,
          DROP CONSTRAINT a_proposal_expected_target_version_is_positive,
          DROP CONSTRAINT a_proposal_names_its_record_only_when_accepted,
          DROP CONSTRAINT an_accepted_identity_correction_names_no_record,
          DROP CONSTRAINT an_accepted_proposal_record_is_named_in_full,
          DROP CONSTRAINT an_accepted_proposal_record_version_is_positive,
          DROP CONSTRAINT an_invalidated_proposal_records_why,
          DROP CONSTRAINT a_proposal_invalidation_reason_is_bounded,
          DROP CONSTRAINT a_superseded_proposal_records_when,
          DROP CONSTRAINT a_proposal_is_not_superseded_before_it_was_proposed,
          DROP CONSTRAINT only_a_superseded_proposal_names_its_successor,
          DROP CONSTRAINT a_proposal_is_not_its_own_successor,
          DROP CONSTRAINT a_proposal_is_superseded_within_its_principal,
          DROP COLUMN method,
          DROP COLUMN method_version,
          DROP COLUMN dedupe_sha256,
          DROP COLUMN model_id,
          DROP COLUMN model_version,
          DROP COLUMN expected_target_version,
          DROP COLUMN review_case_id,
          DROP COLUMN accepted_record_type,
          DROP COLUMN accepted_record_id,
          DROP COLUMN accepted_record_version,
          DROP COLUMN invalidated_reason,
          DROP COLUMN superseded_at,
          DROP COLUMN superseded_by_proposal_id
        """
    )
    # The prior vocabulary, restored exactly. A row in one of the eleven kinds
    # or four states this revision added would refuse to come back down, which
    # is correct: those rows describe requests the earlier schema has no way to
    # represent, and silently coercing them would lose what they asked for.
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_proposals
          DROP CONSTRAINT a_proposal_kind_is_known,
          DROP CONSTRAINT a_proposal_state_is_known,
          DROP CONSTRAINT a_proposal_is_decided_exactly_when_something_decided_it,
          ADD CONSTRAINT a_proposal_kind_is_known
            CHECK (kind IN ({_PROPOSAL_KIND_VALUES_BEFORE_THIS_REVISION})),
          ADD CONSTRAINT a_proposal_state_is_known
            CHECK (state IN ({_PROPOSAL_STATE_VALUES_BEFORE_THIS_REVISION})),
          ADD CONSTRAINT a_proposal_is_decided_exactly_when_something_decided_it
            CHECK ((state IN ('accepted', 'rejected')) = (decided_by IS NOT NULL))
        """
    )
