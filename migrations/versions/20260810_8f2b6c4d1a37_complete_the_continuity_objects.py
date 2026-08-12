"""Complete the continuity objects, their lifecycle evidence, and the Pulse basis.

WP-11. One revision, five changes, because they are one schema change: the R5
continuity surface named Commitments, Decisions and Tasks and had no table for
any of them, closure was a status column with no trace, an association was a
foreign key with no justification, and a Pulse row could be stored with no reason
and no evidence at all.

* `knowledge.commitments`, `knowledge.decisions`, `knowledge.tasks` — the three
  objects, principal-partitioned exactly as `situations` is, each carrying an
  `evidence_state` whose closed vocabulary is `('accepted', 'proposed')` and
  whose default is `proposed`, so a writer that forgets to say what it is writing
  writes a proposal and the continuity reads — which filter to `accepted` — see
  nothing.
* `knowledge.continuity_lifecycle_events` — one append-only row per transition.
  `a_closed_transition_carries_evidence` refuses a `closed` row with a blank or
  absent `evidence_ref` **at the server**, which is the whole reason the table
  exists: closure evidence that only application code enforces is closure
  evidence that the next writer forgets.
* `knowledge.pulse_items` gains `reason_code` and `basis_refs`, both `NOT NULL`
  and neither with a default, plus `a_pulse_item_carries_an_evidentiary_basis`,
  which requires `basis_refs` to be a JSON array with at least one element. After
  this revision an activity-feed row — an item surfaced because something
  happened, with nothing a reader could open to check it — is not a style this
  product avoids. It is a row PostgreSQL refuses.
* `knowledge.project_situations` gains `association_evidence_ref`, **nullable**.
* `knowledge.audit_events.capability_is_known` widens from twenty-seven names to
  thirty.

**Existing `pulse_items` rows: refused, not backfilled, and the choice is
recorded rather than left implicit.** The two new columns have no honest default.
A backfilled `reason_code` would be this revision inventing a why-now that
nobody derived, and a backfilled `basis_refs` would be it inventing evidence —
which is the exact failure the columns exist to prevent, committed by the
migration that adds them. So the upgrade refuses outright if the table holds any
row, with a message naming the remedy. The remedy is safe and is why refusing is
proportionate: `pulse_items` is a *derived* attention list, regenerable from the
accepted records under it, so an operator can empty it and lose no source of
truth. Nothing is dropped silently; the upgrade stops and says what to do.

**The literals below are frozen**, per the standing rule `9c6b4a18ed72` states
and every widening revision since has repeated: no Alembic revision may derive a
closed-set constraint from a domain enum. The thirty names are written out here
and so are the twenty-seven this revision's parent denotes, so a database
downgraded past this revision holds the vocabulary that revision describes rather
than whatever the domain says on the day the downgrade runs. The pair is checked
against the domain at head by
`tests/schema/test_continuity_migration.py::test_head_admits_exactly_the_capability_vocabulary_the_domain_declares`.

**Raw SQL rather than a copy of the live declaration**, which is `d2e3f4a5b6c7`'s
shape and `7a1e5f3c9d24`'s: this revision imports no table object, so it emits
exactly what is written here and cannot start meaning something else when
`tables.py` is next edited (`D-48`). The cost is drift, and it is paid by
`tests/schema/test_continuity_migration.py`, which reads the created tables'
columns, constraints and indexes out of `pg_catalog` and compares them against
`METADATA` on a live server.

**Three capabilities, one purpose, no purpose widened.** `continuity.pulse`,
`continuity.situations` and `continuity.projects` are all permitted under
`capture_review`, which `domain/identity/purpose.py` already admits, so
`purpose_is_known` is untouched. `domain/identity/operation.py` records what that
reuse does and does not cover.

Revision ID: 8f2b6c4d1a37
Revises: 7a1e5f3c9d24
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op

revision: str = "8f2b6c4d1a37"
down_revision: str | None = "7a1e5f3c9d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCHEMA: Final = "knowledge"

#: The capability vocabulary as of this revision: nineteen public names and the
#: eleven native-source names, sorted, which is the order the declarative helper
#: produces so the two texts can be compared directly.
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'continuity.projects', "
    "'continuity.pulse', 'continuity.situations', 'knowledge.read', "
    "'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', 'native_sources.discover', "
    "'native_sources.pause', 'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'review.decide', 'review.list', 'sources.enroll', "
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status')"
)

#: What the revision below denotes, restated rather than derived.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'knowledge.read', "
    "'knowledge.reveal', 'knowledge.search', 'native_sources.backfill', "
    "'native_sources.configure', 'native_sources.disable', 'native_sources.discover', "
    "'native_sources.pause', 'native_sources.preflight', 'native_sources.reconcile', "
    "'native_sources.resume', 'native_sources.retry', 'native_sources.status', "
    "'native_sources.sync', 'review.decide', 'review.list', 'sources.enroll', "
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status')"
)

#: The identifier suffix rule every partitioned table restates. Written out here
#: rather than imported for the same reason the vocabularies are.
_SUFFIX: Final = "[A-Za-z0-9]{8,64}"

#: What the operator is told when the upgrade refuses. Named so the test that
#: asserts the refusal can compare against the same string the migration emits.
PULSE_BACKFILL_REFUSAL: Final = (
    "knowledge.pulse_items holds rows that predate reason_code and basis_refs. "
    "This revision will not invent a why-now reason or an evidentiary basis for "
    "them. pulse_items is a derived attention list and is regenerable from the "
    "accepted records under it: empty it, then run this upgrade again."
)


def _replace_capability_check(expression: str) -> None:
    """Drop and recreate the audit capability CHECK in this revision's transaction.

    PostgreSQL has no "alter the expression of a check constraint", and doing it
    in two statements inside one transaction means there is no instant at which
    the column is unconstrained that another session could observe.
    """
    op.execute(f'ALTER TABLE {SCHEMA}.audit_events DROP CONSTRAINT "capability_is_known"')
    op.execute(
        f'ALTER TABLE {SCHEMA}.audit_events ADD CONSTRAINT "capability_is_known" '
        f"CHECK ({expression})"
    )


def _create_commitments() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.commitments (
          commitment_id text PRIMARY KEY
            CONSTRAINT commitment_id_is_an_opaque_identifier
            CHECK (commitment_id ~ '^cmt_{_SUFFIX}$'),
          principal_id text NOT NULL
            CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_SUFFIX}$'),
          counterparty_person_id text NOT NULL
            CONSTRAINT counterparty_person_id_is_an_opaque_identifier
            CHECK (counterparty_person_id ~ '^per_{_SUFFIX}$'),
          direction text NOT NULL
            CONSTRAINT a_commitment_direction_is_known
            CHECK (direction IN ('owed_by_principal', 'owed_to_principal')),
          summary text NOT NULL
            CONSTRAINT a_commitment_summary_is_not_blank
            CHECK (length(trim(summary)) > 0),
          state text NOT NULL DEFAULT 'open'
            CONSTRAINT a_commitment_state_is_known
            CHECK (state IN ('closed', 'open')),
          evidence_state text NOT NULL DEFAULT 'proposed'
            CONSTRAINT a_commitment_evidence_state_is_known
            CHECK (evidence_state IN ('accepted', 'proposed')),
          origin_evidence_ref text NOT NULL
            CONSTRAINT a_commitment_cites_its_origin_evidence
            CHECK (length(trim(origin_evidence_ref)) > 0),
          project_id text REFERENCES {SCHEMA}.projects (project_id),
          situation_id text REFERENCES {SCHEMA}.situations (situation_id),
          due_at timestamptz,
          opened_at timestamptz NOT NULL,
          closed_at timestamptz,
          closure_evidence_ref text,
          accepted_by_review_decision_id text
            CONSTRAINT a_commitment_review_decision_is_an_opaque_identifier
            CHECK (accepted_by_review_decision_id IS NULL
                   OR accepted_by_review_decision_id ~ '^rdec_{_SUFFIX}$'),
          created_at timestamptz NOT NULL,
          updated_at timestamptz NOT NULL,
          CONSTRAINT a_closed_commitment_records_when_it_closed
            CHECK ((state = 'closed') = (closed_at IS NOT NULL)),
          CONSTRAINT a_closed_commitment_carries_closure_evidence
            CHECK (state <> 'closed' OR length(trim(coalesce(closure_evidence_ref, ''))) > 0),
          CONSTRAINT an_accepted_commitment_records_its_review_decision
            CHECK ((evidence_state = 'accepted') = (accepted_by_review_decision_id IS NOT NULL))
        )
        """
    )
    op.execute(f"CREATE INDEX commitments_by_principal ON {SCHEMA}.commitments (principal_id)")
    op.execute(
        f"CREATE INDEX commitments_by_principal_state ON {SCHEMA}.commitments (principal_id, state)"
    )
    op.execute(
        f"CREATE INDEX commitments_by_principal_evidence_state "
        f"ON {SCHEMA}.commitments (principal_id, evidence_state)"
    )


def _create_decisions() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.decisions (
          decision_id text PRIMARY KEY
            CONSTRAINT decision_id_is_an_opaque_identifier
            CHECK (decision_id ~ '^cdec_{_SUFFIX}$'),
          principal_id text NOT NULL
            CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_SUFFIX}$'),
          question text NOT NULL
            CONSTRAINT a_decision_question_is_not_blank
            CHECK (length(trim(question)) > 0),
          state text NOT NULL DEFAULT 'open'
            CONSTRAINT a_decision_state_is_known
            CHECK (state IN ('closed', 'open')),
          evidence_state text NOT NULL DEFAULT 'proposed'
            CONSTRAINT a_decision_evidence_state_is_known
            CHECK (evidence_state IN ('accepted', 'proposed')),
          origin_evidence_ref text NOT NULL
            CONSTRAINT a_decision_cites_its_origin_evidence
            CHECK (length(trim(origin_evidence_ref)) > 0),
          awaiting_authority_ref text,
          project_id text REFERENCES {SCHEMA}.projects (project_id),
          situation_id text REFERENCES {SCHEMA}.situations (situation_id),
          opened_at timestamptz NOT NULL,
          closed_at timestamptz,
          closure_evidence_ref text,
          accepted_by_review_decision_id text
            CONSTRAINT a_decision_review_decision_is_an_opaque_identifier
            CHECK (accepted_by_review_decision_id IS NULL
                   OR accepted_by_review_decision_id ~ '^rdec_{_SUFFIX}$'),
          outcome text,
          created_at timestamptz NOT NULL,
          updated_at timestamptz NOT NULL,
          CONSTRAINT a_closed_decision_records_when_it_closed
            CHECK ((state = 'closed') = (closed_at IS NOT NULL)),
          CONSTRAINT a_closed_decision_carries_closure_evidence
            CHECK (state <> 'closed' OR length(trim(coalesce(closure_evidence_ref, ''))) > 0),
          CONSTRAINT an_accepted_decision_records_its_review_decision
            CHECK ((evidence_state = 'accepted') = (accepted_by_review_decision_id IS NOT NULL))
        )
        """
    )
    op.execute(f"CREATE INDEX decisions_by_principal ON {SCHEMA}.decisions (principal_id)")
    op.execute(
        f"CREATE INDEX decisions_by_principal_state ON {SCHEMA}.decisions (principal_id, state)"
    )
    op.execute(
        f"CREATE INDEX decisions_by_principal_evidence_state "
        f"ON {SCHEMA}.decisions (principal_id, evidence_state)"
    )


def _create_tasks() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.tasks (
          task_id text PRIMARY KEY
            CONSTRAINT task_id_is_an_opaque_identifier
            CHECK (task_id ~ '^tsk_{_SUFFIX}$'),
          principal_id text NOT NULL
            CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_SUFFIX}$'),
          title text NOT NULL
            CONSTRAINT a_task_title_is_not_blank
            CHECK (length(trim(title)) > 0),
          state text NOT NULL DEFAULT 'open'
            CONSTRAINT a_task_state_is_known
            CHECK (state IN ('closed', 'open')),
          evidence_state text NOT NULL DEFAULT 'proposed'
            CONSTRAINT a_task_evidence_state_is_known
            CHECK (evidence_state IN ('accepted', 'proposed')),
          origin_evidence_ref text NOT NULL
            CONSTRAINT a_task_cites_its_origin_evidence
            CHECK (length(trim(origin_evidence_ref)) > 0),
          project_id text REFERENCES {SCHEMA}.projects (project_id),
          situation_id text REFERENCES {SCHEMA}.situations (situation_id),
          due_at timestamptz,
          opened_at timestamptz NOT NULL,
          closed_at timestamptz,
          closure_evidence_ref text,
          accepted_by_review_decision_id text
            CONSTRAINT a_task_review_decision_is_an_opaque_identifier
            CHECK (accepted_by_review_decision_id IS NULL
                   OR accepted_by_review_decision_id ~ '^rdec_{_SUFFIX}$'),
          created_at timestamptz NOT NULL,
          updated_at timestamptz NOT NULL,
          CONSTRAINT a_closed_task_records_when_it_closed
            CHECK ((state = 'closed') = (closed_at IS NOT NULL)),
          CONSTRAINT a_closed_task_carries_closure_evidence
            CHECK (state <> 'closed' OR length(trim(coalesce(closure_evidence_ref, ''))) > 0),
          CONSTRAINT an_accepted_task_records_its_review_decision
            CHECK ((evidence_state = 'accepted') = (accepted_by_review_decision_id IS NOT NULL))
        )
        """
    )
    op.execute(f"CREATE INDEX tasks_by_principal ON {SCHEMA}.tasks (principal_id)")
    op.execute(f"CREATE INDEX tasks_by_principal_state ON {SCHEMA}.tasks (principal_id, state)")
    op.execute(
        f"CREATE INDEX tasks_by_principal_evidence_state "
        f"ON {SCHEMA}.tasks (principal_id, evidence_state)"
    )


def _create_lifecycle_events() -> None:
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.continuity_lifecycle_events (
          event_id text PRIMARY KEY
            CONSTRAINT event_id_is_an_opaque_identifier
            CHECK (event_id ~ '^lce_{_SUFFIX}$'),
          principal_id text NOT NULL
            CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_SUFFIX}$'),
          object_kind text NOT NULL
            CONSTRAINT a_continuity_object_kind_is_known
            CHECK (object_kind IN ('commitment', 'decision', 'project', 'situation', 'task')),
          object_id text NOT NULL
            CONSTRAINT a_lifecycle_event_names_its_object
            CHECK (length(trim(object_id)) > 0),
          transition text NOT NULL
            CONSTRAINT a_continuity_transition_is_known
            CHECK (transition IN ('associated', 'closed', 'opened')),
          evidence_kind text NOT NULL
            CONSTRAINT a_continuity_evidence_kind_is_known
            CHECK (evidence_kind IN ('assertion', 'capture', 'frame', 'principal_statement',
                                     'project', 'relationship_event', 'review_decision',
                                     'situation')),
          evidence_ref text,
          occurred_at timestamptz NOT NULL,
          recorded_at timestamptz NOT NULL,
          CONSTRAINT a_closed_transition_carries_evidence
            CHECK (transition <> 'closed' OR length(trim(coalesce(evidence_ref, ''))) > 0),
          CONSTRAINT an_association_carries_evidence
            CHECK (transition <> 'associated' OR length(trim(coalesce(evidence_ref, ''))) > 0)
        )
        """
    )
    op.execute(
        f"CREATE INDEX continuity_lifecycle_events_by_principal "
        f"ON {SCHEMA}.continuity_lifecycle_events (principal_id)"
    )
    op.execute(
        f"CREATE INDEX continuity_lifecycle_events_by_principal_object "
        f"ON {SCHEMA}.continuity_lifecycle_events (principal_id, object_id)"
    )
    op.execute(
        f"CREATE INDEX continuity_lifecycle_events_by_principal_transition "
        f"ON {SCHEMA}.continuity_lifecycle_events (principal_id, transition)"
    )


def _extend_pulse_items() -> None:
    """Refuse rather than fabricate, then add the two columns and the basis CHECK."""
    # The suppression on the statement below is deliberate: both interpolations
    # are module constants declared in this file (`SCHEMA` and the refusal text),
    # neither reaches this line from a request, a column, or a caller, and the
    # refusal text contains no quote character.
    op.execute(
        f"""
        DO $$
        BEGIN
          IF EXISTS (SELECT 1 FROM {SCHEMA}.pulse_items) THEN
            RAISE EXCEPTION '{PULSE_BACKFILL_REFUSAL}';
          END IF;
        END $$
        """  # noqa: S608
    )
    op.execute(f"ALTER TABLE {SCHEMA}.pulse_items ADD COLUMN reason_code text NOT NULL")
    op.execute(f"ALTER TABLE {SCHEMA}.pulse_items ADD COLUMN basis_refs jsonb NOT NULL")
    op.execute(
        f'ALTER TABLE {SCHEMA}.pulse_items ADD CONSTRAINT "a_pulse_reason_code_is_known" '
        "CHECK (reason_code IN ('commitment_due_soon', 'commitment_overdue', "
        "'decision_awaiting_authority', 'situation_obligation_unmet', "
        "'task_due_soon', 'task_overdue'))"
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.pulse_items ADD CONSTRAINT "
        '"a_pulse_item_carries_an_evidentiary_basis" '
        "CHECK (jsonb_typeof(basis_refs) = 'array' AND jsonb_array_length(basis_refs) > 0)"
    )


def upgrade() -> None:
    _create_commitments()
    _create_decisions()
    _create_tasks()
    _create_lifecycle_events()
    _extend_pulse_items()
    op.execute(f"ALTER TABLE {SCHEMA}.project_situations ADD COLUMN association_evidence_ref text")
    _replace_capability_check(_CAPABILITIES_AT_THIS_REVISION)


def downgrade() -> None:
    """Reverse every change, and restore exactly the twenty-seven names above.

    Dropping the two `pulse_items` columns discards the reason and the basis of
    any row written since the upgrade, which is the correct direction: the row
    itself survives, and a `pulse_items` at the parent revision is by definition
    one whose rows carry neither. The three object tables and the lifecycle
    record go with their own rows, and that is a real loss rather than a
    reversible one — a downgrade past this revision is a decision to stop holding
    commitments, decisions and tasks at all.
    """
    _replace_capability_check(_CAPABILITIES_BEFORE_THIS_REVISION)
    op.execute(f"ALTER TABLE {SCHEMA}.project_situations DROP COLUMN association_evidence_ref")
    op.execute(
        f"ALTER TABLE {SCHEMA}.pulse_items "
        'DROP CONSTRAINT "a_pulse_item_carries_an_evidentiary_basis"'
    )
    op.execute(f'ALTER TABLE {SCHEMA}.pulse_items DROP CONSTRAINT "a_pulse_reason_code_is_known"')
    op.execute(f"ALTER TABLE {SCHEMA}.pulse_items DROP COLUMN basis_refs")
    op.execute(f"ALTER TABLE {SCHEMA}.pulse_items DROP COLUMN reason_code")
    op.execute(f"DROP TABLE {SCHEMA}.continuity_lifecycle_events")
    op.execute(f"DROP TABLE {SCHEMA}.tasks")
    op.execute(f"DROP TABLE {SCHEMA}.decisions")
    op.execute(f"DROP TABLE {SCHEMA}.commitments")
