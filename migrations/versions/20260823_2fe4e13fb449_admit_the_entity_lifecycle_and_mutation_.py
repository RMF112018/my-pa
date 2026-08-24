"""Admit the entity lifecycle columns and the three entity ledgers.

WP-RI-A-01 (`MYPA-RI-COMP-04`). Six existing tables gain lifecycle, version and
composite-key columns; two more gain Principal-composite references only; three
tables are created; and one closed set on `entity_external_identifiers` is
restated to admit the two legacy namespaces.

**What this revision is for.** The entity plane could record what it currently
believes and not how it came to believe it. An identifier could be deleted but
not retired, so recording that an address changed meant destroying the row that
resolves a four-year-old message. An assignment carried an open `status` string
that two readers compared against the literal `'active'` while the column
admitted anything, so a row written around the repository was silently excluded
from every corroborating read. Nothing recorded who admitted a change, and
nothing recorded a decision *not* to resolve a mention -- which section 15.2
requires to be an ordinary outcome rather than an absence.

**Order, and one deviation from the order `MYPA-RI-COMP-04` states.** The
contract's sequence is: add backfillable columns; backfill and validate; add the
mutation, evidence and resolution tables; then add uniques, checks and composite
foreign keys. That sequence cannot be run literally, because the three new tables
carry composite `(id, principal_id)` foreign keys and a foreign key needs its
target unique to exist first. So the seven composite-identity uniques are
created in step 2 with the validation, and everything else that is a constraint
is created in the final step. The deviation is exactly one step's worth of
uniques, and it is written down rather than quietly performed.

**Two total uniques come off.** `9def3c2e63bb` and `b7f4d1a92c36` made
`(entity_id, namespace, normalized_value)` and
`(entity_id, alias_type, normalized_value)` unique over every row whatever its
state. Left in place they would make the partial uniques below decorative: a
total unique refuses re-binding an address on the *same* entity it was retired
from, so retiring a binding and recording its replacement would require deleting
the retired row -- the row that resolves a message sent before the address was
reissued, and the reason this vocabulary exists. The rule they encode survives as
the partial unique that replaces each, and the downgrade puts both back.

**Two backfills abort rather than guess.** `entity_assignments.status` becomes
`entity_assignments.state`, and `entity_relationships.state` becomes a closed
set. A row holding a non-empty legacy value outside the known vocabulary is not
mapped to anything: the migration raises, names the offending values and the row
count, and stops. Guessing is the failure this whole revision exists to make
impossible, and a migration that guessed once would put exactly the row the new
CHECK refuses on the other side of the CHECK. An *empty* legacy value is mapped
to `active`, which is the column's own default and the only lifecycle the plane
has ever written; the contract admits that case and it is stated here so a reader
does not have to infer it from the SQL.

**The canonical binding conflict aborts the same way.** The new partial unique on
`(principal_id, namespace, normalized_value) WHERE state = 'active'` is what stops
one address from being the current identity of two entities at once. Existing
rows that already violate it are reported before the index is built, with the
namespace and the value named, rather than surfacing as a duplicate-key failure
from an index build halfway through.

**An entity already `archived` aborts it too.** `archived_from_status` is the
status an entity will be restored to, and no migration can recover what an
already-archived row used to be. Reported with the row count for the same
reason as the other three: a bare `is violated by some row` from the new CHECK
names neither the row nor the remedy.

**The merge ledger's references become composite.** `entity_merge_records`
carries a NOT NULL `principal_id` and named both of its entities and its
proposal by a single column, so the server accepted a merge record owned by one
Principal that merged away another Principal's entity -- the same defect the six
widened tables had. `entity_proposals` gains the `(proposal_id, principal_id)`
unique that the third of those references points at. The single-column
references stay: both are enforced, and removing them would change nothing.

**The two new ledgers are append-only by trigger, not by convention.** No CHECK
can express "no UPDATE", and a rule enforced only by the current writer is a rule
the next writer does not inherit. This is the mechanism `f1c6b904a2d7` installs
on `relationship_memory_versions`, reused here with its own function so that
dropping one plane's trigger cannot silently disarm the other's.

**The closed sets below are frozen literals**, per the standing rule
`9c6b4a18ed72` states: no revision derives a closed-set constraint from a domain
enum. A database migrated to this revision holds the vocabulary this revision
describes, whatever the domain says on the day it runs.

**No capability and no purpose is admitted.** This revision adds no capability,
so it restates neither `capability_is_known` nor `purpose_is_known` on
`audit_events`. The capabilities that will write these ledgers arrive with the
code that writes them.

Revision ID: 2fe4e13fb449
Revises: f1c6b904a2d7
Create Date: 2026-08-23
"""

from __future__ import annotations

from typing import Final

from alembic import op

revision: str = "2fe4e13fb449"
down_revision: str | None = "f1c6b904a2d7"
branch_labels: str | None = None
depends_on: str | None = None

SCHEMA: Final = "knowledge"

#: The suffix rule `domain.common.identifiers.validate_identifier` enforces,
#: restated as the POSIX form the server can check.
_IDENTIFIER_SUFFIX: Final = "[A-Za-z0-9]{8,64}"

#: Longest a stored explanation of one change may be.
_REASON_LIMIT: Final = 500

#: Longest an idempotency key may be, matching the bound the capture and managed
#: submission tables already carry.
_IDEMPOTENCY_KEY_LIMIT: Final = 128

# --- the frozen vocabularies, sorted -----------------------------------------

_ARCHIVABLE_STATUS_VALUES: Final = "'active', 'historical', 'inactive'"

_BINDING_STATE_VALUES: Final = "'active', 'retired', 'superseded'"

_EDGE_STATE_VALUES: Final = "'active', 'ended', 'superseded'"

_OBSERVATION_AUTHORITY_VALUES: Final = (
    "'source_observation', 'system_deterministic_observation', 'user_authored_statement'"
)

_OBSERVATION_STATE_VALUES: Final = "'contradicted', 'current', 'quarantined', 'stale', 'superseded'"

_MUTATION_AUTHORITY_VALUES: Final = (
    "'review_accepted', 'system_deterministic', 'user_confirmed_assertion'"
)

_RECORD_FAMILY_VALUES: Final = (
    "'alias', 'assignment', 'entity', 'identifier', 'observation', 'relationship'"
)

_ACTOR_CLASS_VALUES: Final = "'review_promotion', 'system_deterministic', 'user'"

_EVIDENCE_ROLE_VALUES: Final = "'counterevidence', 'direct', 'supporting'"

_DISPOSITION_VALUES: Final = "'create_new', 'defer', 'link_existing', 'quarantine', 'reject'"

#: The external-identifier namespaces at this revision: the seven `9def3c2e63bb`
#: froze, plus the two identities the WP-9 substrate issued. Recording a
#: `person_id` as a namespace rather than as a column is what lets the two planes
#: be reconciled without either becoming canonical for the other.
_NAMESPACE_VALUES_AT_THIS_REVISION: Final = (
    "'apple_contact_id', 'email', 'entra_object_id', "
    "'legacy_relationship_organization_id', 'legacy_relationship_person_id', "
    "'outlook_contact_id', 'source_participant_id', 'teams_user_id', "
    "'vendor_system_id'"
)

_NAMESPACE_VALUES_BEFORE_THIS_REVISION: Final = (
    "'apple_contact_id', 'email', 'entra_object_id', 'outlook_contact_id', "
    "'source_participant_id', 'teams_user_id', 'vendor_system_id'"
)

#: The known legacy `entity_assignments.status` values. One member, because one
#: is what the plane has ever written: the record's default, the repository's
#: `active_only` filter and the resolver's corroboration rule all name it.
_KNOWN_LEGACY_ASSIGNMENT_STATUS: Final = "'active'"

#: The known legacy `entity_relationships.state` values.
_KNOWN_LEGACY_RELATIONSHIP_STATE: Final = "'active', 'ended', 'superseded'"

#: The function and the triggers that make the two ledgers append only.
_IMMUTABILITY_FUNCTION: Final = "entity_ledger_rows_stay_as_written"
_IMMUTABLE_TABLES: Final = (
    ("entity_mutation_events", "entity_mutation_events_are_append_only"),
    ("entity_resolution_decisions", "entity_resolution_decisions_are_append_only"),
)

#: The two total uniques this revision drops, and the `CREATE` that puts each
#: back. `9def3c2e63bb` and `b7f4d1a92c36` created them over every row whatever
#: its state, which is the shape the partial uniques below replace: a total
#: unique forces the plane to *delete* a retired binding in order to record its
#: replacement, and a deleted binding is the row that resolves a message sent
#: before the address was reissued. Restated rather than removed, because the
#: rule they encode is still the rule -- it now applies to the active row only.
_LEGACY_TOTAL_UNIQUES: Final = (
    (
        "entity_external_identifiers",
        "an_external_identifier_is_recorded_once_per_namespace",
        "entity_id, namespace, normalized_value",
    ),
    (
        "entity_aliases",
        "an_alias_is_recorded_once_per_entity_and_type",
        "entity_id, alias_type, normalized_value",
    ),
)

#: `(table, primary key column, constraint name)` for the composite identity
#: uniques every composite `(id, principal_id)` foreign key on this plane points
#: at. Created before the new tables because a foreign key needs its target.
_COMPOSITE_IDENTITIES: Final = (
    ("entities", "entity_id", "an_entity_is_identified_within_its_principal"),
    (
        "entity_external_identifiers",
        "identifier_id",
        "an_external_identifier_is_identified_within_its_principal",
    ),
    ("entity_aliases", "alias_id", "an_alias_is_identified_within_its_principal"),
    (
        "entity_assignments",
        "assignment_id",
        "an_assignment_is_identified_within_its_principal",
    ),
    (
        "entity_relationships",
        "relationship_id",
        "an_entity_relationship_is_identified_within_its_principal",
    ),
    ("entity_observations", "observation_id", "an_observation_is_identified_within_its_principal"),
    ("entity_proposals", "proposal_id", "a_proposal_is_identified_within_its_principal"),
)


def _abort_on_unknown(table: str, column: str, known: str, subject: str) -> str:
    """SQL that refuses to migrate a legacy vocabulary it does not recognise.

    Reports every offending value and the row count in one message, rather than
    failing on the first row: a migration that names one bad value at a time
    makes a caller run it once per defect, and the whole point of aborting here
    is that somebody can go and look at the data.
    """
    return f"""
        DO $$
        DECLARE
          offending text;
          affected bigint;
        BEGIN
          SELECT string_agg(DISTINCT {column}, ', ' ORDER BY {column}), count(*)
            INTO offending, affected
            FROM {SCHEMA}.{table}
           WHERE {column} IS NOT NULL
             AND btrim({column}) <> ''
             AND {column} NOT IN ({known});
          IF COALESCE(affected, 0) > 0 THEN
            RAISE EXCEPTION USING MESSAGE =
              '{SCHEMA}.{table} holds ' || affected || ' row(s) whose legacy '
              || '{column} is not a known {subject}: ' || offending
              || '. Map or remove them before migrating; this migration does '
              || 'not guess what an unknown state meant.';
          END IF;
        END $$;
        """  # noqa: S608


_ABORT_ON_CONFLICTING_ACTIVE_BINDING: Final = f"""
    DO $$
    DECLARE
      offending text;
      affected bigint;
    BEGIN
      SELECT string_agg(pair, '; ' ORDER BY pair), count(*)
        INTO offending, affected
        FROM (
          SELECT namespace || '=' || normalized_value AS pair
            FROM {SCHEMA}.entity_external_identifiers
           WHERE state = 'active'
           GROUP BY principal_id, namespace, normalized_value
          HAVING count(DISTINCT entity_id) > 1
        ) AS conflicts;
      IF COALESCE(affected, 0) > 0 THEN
        RAISE EXCEPTION USING MESSAGE =
          '{SCHEMA}.entity_external_identifiers holds ' || affected
          || ' active binding(s) claimed by more than one entity of the same '
          || 'Principal: ' || offending
          || '. Retire or supersede all but one before migrating; an active '
          || 'canonical binding names exactly one entity.';
      END IF;
    END $$;
    """  # noqa: S608


_ABORT_ON_AN_ALREADY_ARCHIVED_ENTITY: Final = f"""
    DO $$
    DECLARE
      affected bigint;
    BEGIN
      SELECT count(*) INTO affected FROM {SCHEMA}.entities WHERE status = 'archived';
      IF COALESCE(affected, 0) > 0 THEN
        RAISE EXCEPTION USING MESSAGE =
          '{SCHEMA}.entities holds ' || affected
          || ' row(s) already archived, and this migration cannot tell what '
          || 'status each one was archived from. Set archived_from_status by '
          || 'hand, or restore the prior status, before migrating; this '
          || 'migration does not guess what an archived entity used to be.';
      END IF;
    END $$;
    """  # noqa: S608


def _restate_namespaces(values: str) -> None:
    """Replace the namespace closed set on `entity_external_identifiers`."""
    op.execute(
        f"ALTER TABLE {SCHEMA}.entity_external_identifiers "
        'DROP CONSTRAINT "an_external_identifier_namespace_is_known"'
    )
    op.execute(
        f"ALTER TABLE {SCHEMA}.entity_external_identifiers "
        'ADD CONSTRAINT "an_external_identifier_namespace_is_known" '
        f"CHECK (namespace IN ({values}))"
    )


def upgrade() -> None:
    # --- 1. lifecycle, version and composite-key columns ---------------------
    #
    # Every added column is either nullable or carries a default that is true of
    # every row already there, so this step rewrites no data and decides nothing.
    op.execute(f"ALTER TABLE {SCHEMA}.entities ADD COLUMN archived_from_status text")
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_external_identifiers
          ADD COLUMN state text NOT NULL DEFAULT 'active',
          ADD COLUMN version integer NOT NULL DEFAULT 1,
          ADD COLUMN updated_at timestamptz,
          ADD COLUMN retired_at timestamptz,
          ADD COLUMN superseded_by_identifier_id text
            REFERENCES {SCHEMA}.entity_external_identifiers(identifier_id)
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_aliases
          ADD COLUMN state text NOT NULL DEFAULT 'active',
          ADD COLUMN version integer NOT NULL DEFAULT 1,
          ADD COLUMN updated_at timestamptz,
          ADD COLUMN retired_at timestamptz,
          ADD COLUMN superseded_by_alias_id text
            REFERENCES {SCHEMA}.entity_aliases(alias_id)
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_assignments
          ADD COLUMN version integer NOT NULL DEFAULT 1,
          ADD COLUMN updated_at timestamptz,
          ADD COLUMN ended_at timestamptz,
          ADD COLUMN superseded_by_assignment_id text
            REFERENCES {SCHEMA}.entity_assignments(assignment_id)
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_relationships
          ADD COLUMN updated_at timestamptz,
          ADD COLUMN ended_at timestamptz,
          ADD COLUMN superseded_by_relationship_id text
            REFERENCES {SCHEMA}.entity_relationships(relationship_id)
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_observations
          ADD COLUMN authority text NOT NULL DEFAULT 'source_observation',
          ADD COLUMN state text NOT NULL DEFAULT 'current',
          ADD COLUMN state_reason text,
          ADD COLUMN superseded_by_observation_id text
            REFERENCES {SCHEMA}.entity_observations(observation_id),
          ADD COLUMN resolution_version integer NOT NULL DEFAULT 0
        """
    )

    # --- 2. validate the legacy vocabularies, then map what is safe to map ----
    op.execute(
        _abort_on_unknown(
            "entity_assignments", "status", _KNOWN_LEGACY_ASSIGNMENT_STATUS, "assignment state"
        )
    )
    op.execute(
        _abort_on_unknown(
            "entity_relationships",
            "state",
            _KNOWN_LEGACY_RELATIONSHIP_STATE,
            "relationship state",
        )
    )
    op.execute(_ABORT_ON_CONFLICTING_ACTIVE_BINDING)
    # The fourth abort, for the same reason as the other three. Nothing on this
    # plane writes `archived` today, so this is unreachable from the current
    # code; the asymmetry was the defect. Without it a restored or hand-edited
    # archived row makes `an_entity_records_the_status_it_was_archived_from`
    # fail with a bare `is violated by some row`, naming no row and no remedy.
    op.execute(_ABORT_ON_AN_ALREADY_ARCHIVED_ENTITY)
    op.execute(
        f"UPDATE {SCHEMA}.entity_assignments SET status = 'active' WHERE btrim(status) = ''"  # noqa: S608
    )
    op.execute(
        f"UPDATE {SCHEMA}.entity_relationships SET state = 'active' WHERE btrim(state) = ''"  # noqa: S608
    )
    op.execute(f"ALTER TABLE {SCHEMA}.entity_assignments RENAME COLUMN status TO state")

    # The composite identities, out of step 7 and into this one because a
    # foreign key needs its target unique to exist. See the module docstring.
    for table, key, name in _COMPOSITE_IDENTITIES:
        op.execute(
            f'ALTER TABLE {SCHEMA}.{table} ADD CONSTRAINT "{name}" UNIQUE ({key}, principal_id)'
        )

    # --- 3. the mutation, evidence and resolution tables ---------------------
    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_mutation_events (
          event_id text PRIMARY KEY,
          principal_id text NOT NULL,
          capability text NOT NULL,
          record_family text NOT NULL,
          record_id text NOT NULL,
          prior_version integer,
          new_version integer NOT NULL,
          authority text NOT NULL,
          before_state jsonb,
          after_state jsonb,
          reason text,
          idempotency_key text NOT NULL,
          request_digest text NOT NULL,
          correlation_id text NOT NULL,
          audit_id text NOT NULL,
          receipt_id text,
          actor_class text NOT NULL,
          recorded_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT event_id_is_an_opaque_identifier
            CHECK (event_id ~ '^emut_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT correlation_id_is_an_opaque_identifier
            CHECK (correlation_id ~ '^corr_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT audit_id_is_an_opaque_identifier
            CHECK (audit_id ~ '^audit_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT a_mutated_record_family_is_known
            CHECK (record_family IN ({_RECORD_FAMILY_VALUES})),
          CONSTRAINT a_mutation_authority_is_known
            CHECK (authority IN ({_MUTATION_AUTHORITY_VALUES})),
          CONSTRAINT a_mutation_actor_class_is_known
            CHECK (actor_class IN ({_ACTOR_CLASS_VALUES})),
          CONSTRAINT a_mutation_names_the_capability_that_made_it
            CHECK (length(trim(capability)) > 0),
          CONSTRAINT a_mutated_record_id_is_an_opaque_identifier
            CHECK (record_id ~ '^[a-z]+_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT a_mutation_receipt_id_is_an_opaque_identifier
            CHECK (receipt_id IS NULL OR receipt_id ~ '^[a-z]+_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT a_mutation_request_digest_is_a_sha256_digest
            CHECK (request_digest ~ '^[0-9a-f]{{64}}$'),
          CONSTRAINT a_mutation_idempotency_key_is_bounded
            CHECK (length(idempotency_key) BETWEEN 1 AND {_IDEMPOTENCY_KEY_LIMIT}),
          CONSTRAINT a_mutation_reason_is_bounded
            CHECK (
              reason IS NULL
              OR (length(trim(reason)) > 0 AND length(reason) <= {_REASON_LIMIT})
            ),
          CONSTRAINT a_mutation_new_version_is_positive
            CHECK (new_version >= 1),
          CONSTRAINT a_mutation_advances_the_version_it_names
            CHECK (
              prior_version IS NULL
              OR (prior_version >= 1 AND new_version > prior_version)
            ),
          CONSTRAINT a_mutation_before_state_is_an_object
            CHECK (before_state IS NULL OR jsonb_typeof(before_state) = 'object'),
          CONSTRAINT a_mutation_after_state_is_an_object
            CHECK (after_state IS NULL OR jsonb_typeof(after_state) = 'object'),
          CONSTRAINT one_entity_mutation_per_key_and_capability
            UNIQUE (principal_id, capability, idempotency_key)
        );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_mutation_events_by_principal
          ON {SCHEMA}.entity_mutation_events (principal_id);
        CREATE INDEX entity_mutation_events_by_record
          ON {SCHEMA}.entity_mutation_events (principal_id, record_family, record_id);
        """
    )

    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_fact_evidence_links (
          link_id text PRIMARY KEY,
          principal_id text NOT NULL,
          entity_id text,
          identifier_id text,
          alias_id text,
          assignment_id text,
          relationship_id text,
          entity_observation_id text,
          capture_span_id text,
          knowledge_id text,
          role text NOT NULL,
          authority text NOT NULL,
          created_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT link_id_is_an_opaque_identifier
            CHECK (link_id ~ '^efev_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT an_entity_evidence_role_is_known
            CHECK (role IN ({_EVIDENCE_ROLE_VALUES})),
          CONSTRAINT an_entity_evidence_authority_is_known
            CHECK (authority IN ({_MUTATION_AUTHORITY_VALUES})),
          CONSTRAINT entity_evidence_names_exactly_one_fact
            CHECK (
              (entity_id IS NOT NULL)::int
              + (identifier_id IS NOT NULL)::int
              + (alias_id IS NOT NULL)::int
              + (assignment_id IS NOT NULL)::int
              + (relationship_id IS NOT NULL)::int = 1
            ),
          CONSTRAINT entity_evidence_names_exactly_one_record
            CHECK (
              (entity_observation_id IS NOT NULL)::int
              + (capture_span_id IS NOT NULL)::int
              + (knowledge_id IS NOT NULL)::int = 1
            ),
          CONSTRAINT entity_evidence_names_an_entity_of_its_principal
            FOREIGN KEY (entity_id, principal_id)
            REFERENCES {SCHEMA}.entities (entity_id, principal_id) ON DELETE CASCADE,
          CONSTRAINT entity_evidence_names_an_identifier_of_its_principal
            FOREIGN KEY (identifier_id, principal_id)
            REFERENCES {SCHEMA}.entity_external_identifiers (identifier_id, principal_id)
            ON DELETE CASCADE,
          CONSTRAINT entity_evidence_names_an_alias_of_its_principal
            FOREIGN KEY (alias_id, principal_id)
            REFERENCES {SCHEMA}.entity_aliases (alias_id, principal_id) ON DELETE CASCADE,
          CONSTRAINT entity_evidence_names_an_assignment_of_its_principal
            FOREIGN KEY (assignment_id, principal_id)
            REFERENCES {SCHEMA}.entity_assignments (assignment_id, principal_id)
            ON DELETE CASCADE,
          CONSTRAINT entity_evidence_names_a_relationship_of_its_principal
            FOREIGN KEY (relationship_id, principal_id)
            REFERENCES {SCHEMA}.entity_relationships (relationship_id, principal_id)
            ON DELETE CASCADE,
          CONSTRAINT entity_evidence_cites_an_observation_of_its_principal
            FOREIGN KEY (entity_observation_id, principal_id)
            REFERENCES {SCHEMA}.entity_observations (observation_id, principal_id)
            ON DELETE CASCADE
        );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_fact_evidence_links_by_principal
          ON {SCHEMA}.entity_fact_evidence_links (principal_id);
        CREATE INDEX entity_fact_evidence_links_by_observation
          ON {SCHEMA}.entity_fact_evidence_links (entity_observation_id);
        """
    )

    op.execute(
        f"""
        CREATE TABLE {SCHEMA}.entity_resolution_decisions (
          decision_id text PRIMARY KEY,
          principal_id text NOT NULL,
          observation_id text NOT NULL,
          sequence integer NOT NULL,
          expected_resolution_version integer NOT NULL,
          disposition text NOT NULL,
          entity_id text,
          reason text,
          evidence_link_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
          decided_by text NOT NULL,
          actor_class text NOT NULL,
          review_case_id text,
          correlation_id text NOT NULL,
          audit_id text NOT NULL,
          receipt_id text,
          decided_at timestamptz NOT NULL DEFAULT now(),
          CONSTRAINT decision_id_is_an_opaque_identifier
            CHECK (decision_id ~ '^erdc_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT principal_id_is_an_opaque_identifier
            CHECK (principal_id ~ '^prn_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT observation_id_is_an_opaque_identifier
            CHECK (observation_id ~ '^eobs_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT correlation_id_is_an_opaque_identifier
            CHECK (correlation_id ~ '^corr_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT audit_id_is_an_opaque_identifier
            CHECK (audit_id ~ '^audit_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT a_resolution_disposition_is_known
            CHECK (disposition IN ({_DISPOSITION_VALUES})),
          CONSTRAINT a_resolution_actor_class_is_known
            CHECK (actor_class IN ({_ACTOR_CLASS_VALUES})),
          CONSTRAINT a_resolution_review_case_id_is_an_opaque_identifier
            CHECK (review_case_id IS NULL OR review_case_id ~ '^rvw_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT a_resolution_receipt_id_is_an_opaque_identifier
            CHECK (receipt_id IS NULL OR receipt_id ~ '^[a-z]+_{_IDENTIFIER_SUFFIX}$'),
          CONSTRAINT a_resolution_sequence_is_positive
            CHECK (sequence >= 1),
          CONSTRAINT a_resolution_expects_a_version_that_could_exist
            CHECK (expected_resolution_version >= 0),
          CONSTRAINT a_resolution_names_an_entity_exactly_when_it_binds_one
            CHECK (
              (disposition IN ('link_existing', 'create_new')) = (entity_id IS NOT NULL)
            ),
          CONSTRAINT a_resolution_names_what_decided_it
            CHECK (length(trim(decided_by)) > 0),
          CONSTRAINT a_resolution_reason_is_bounded
            CHECK (
              reason IS NULL
              OR (length(trim(reason)) > 0 AND length(reason) <= {_REASON_LIMIT})
            ),
          CONSTRAINT a_resolution_cites_evidence_as_an_array
            CHECK (jsonb_typeof(evidence_link_ids) = 'array'),
          CONSTRAINT one_resolution_decision_per_observation_and_sequence
            UNIQUE (observation_id, sequence),
          CONSTRAINT a_resolution_decides_an_observation_of_its_principal
            FOREIGN KEY (observation_id, principal_id)
            REFERENCES {SCHEMA}.entity_observations (observation_id, principal_id)
            ON DELETE CASCADE,
          CONSTRAINT a_resolution_binds_an_entity_of_its_principal
            FOREIGN KEY (entity_id, principal_id)
            REFERENCES {SCHEMA}.entities (entity_id, principal_id)
        );
        """
    )
    op.execute(
        f"""
        CREATE INDEX entity_resolution_decisions_by_principal
          ON {SCHEMA}.entity_resolution_decisions (principal_id);
        CREATE INDEX entity_resolution_decisions_by_observation
          ON {SCHEMA}.entity_resolution_decisions (observation_id);
        """
    )

    op.execute(
        f"CREATE FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION '%.% is append only; % is refused', "
        "TG_TABLE_SCHEMA, TG_TABLE_NAME, TG_OP "
        "USING ERRCODE = 'restrict_violation'; "
        "END; $$"
    )
    for table, trigger in _IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE ON {SCHEMA}.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}()"
        )

    # --- 7. the remaining checks, composite foreign keys and uniques ---------
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entities
          ADD CONSTRAINT an_archived_from_status_is_known
            CHECK (archived_from_status IN ({_ARCHIVABLE_STATUS_VALUES})),
          ADD CONSTRAINT an_entity_records_the_status_it_was_archived_from
            CHECK ((status = 'archived') = (archived_from_status IS NOT NULL)),
          ADD CONSTRAINT an_entity_redirects_within_its_principal
            FOREIGN KEY (superseded_by_entity_id, principal_id)
            REFERENCES {SCHEMA}.entities (entity_id, principal_id)
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_external_identifiers
          ADD CONSTRAINT an_external_identifier_state_is_known
            CHECK (state IN ({_BINDING_STATE_VALUES})),
          ADD CONSTRAINT an_external_identifier_version_is_positive
            CHECK (version >= 1),
          ADD CONSTRAINT an_external_identifier_is_retired_only_once_it_leaves_service
            CHECK (retired_at IS NULL OR state <> 'active'),
          ADD CONSTRAINT an_external_identifier_names_a_successor_only_when_superseded
            CHECK (superseded_by_identifier_id IS NULL OR state = 'superseded'),
          ADD CONSTRAINT an_external_identifier_does_not_supersede_itself
            CHECK (
              superseded_by_identifier_id IS NULL
              OR superseded_by_identifier_id <> identifier_id
            ),
          ADD CONSTRAINT an_external_identifier_binds_an_entity_of_its_principal
            FOREIGN KEY (entity_id, principal_id)
            REFERENCES {SCHEMA}.entities (entity_id, principal_id) ON DELETE CASCADE,
          ADD CONSTRAINT an_external_identifier_is_superseded_within_its_principal
            FOREIGN KEY (superseded_by_identifier_id, principal_id)
            REFERENCES {SCHEMA}.entity_external_identifiers (identifier_id, principal_id)
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_aliases
          ADD CONSTRAINT an_alias_state_is_known
            CHECK (state IN ({_BINDING_STATE_VALUES})),
          ADD CONSTRAINT an_alias_version_is_positive
            CHECK (version >= 1),
          ADD CONSTRAINT an_alias_is_retired_only_once_it_leaves_service
            CHECK (retired_at IS NULL OR state <> 'active'),
          ADD CONSTRAINT an_alias_names_a_successor_only_when_superseded
            CHECK (superseded_by_alias_id IS NULL OR state = 'superseded'),
          ADD CONSTRAINT an_alias_does_not_supersede_itself
            CHECK (superseded_by_alias_id IS NULL OR superseded_by_alias_id <> alias_id),
          ADD CONSTRAINT an_alias_names_an_entity_of_its_principal
            FOREIGN KEY (entity_id, principal_id)
            REFERENCES {SCHEMA}.entities (entity_id, principal_id) ON DELETE CASCADE,
          ADD CONSTRAINT an_alias_is_superseded_within_its_principal
            FOREIGN KEY (superseded_by_alias_id, principal_id)
            REFERENCES {SCHEMA}.entity_aliases (alias_id, principal_id)
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_assignments
          ADD CONSTRAINT an_assignment_state_is_known
            CHECK (state IN ({_EDGE_STATE_VALUES})),
          ADD CONSTRAINT an_assignment_version_is_positive
            CHECK (version >= 1),
          ADD CONSTRAINT an_assignment_ends_only_once_it_leaves_service
            CHECK (ended_at IS NULL OR state <> 'active'),
          ADD CONSTRAINT an_assignment_names_a_successor_only_when_superseded
            CHECK (superseded_by_assignment_id IS NULL OR state = 'superseded'),
          ADD CONSTRAINT an_assignment_does_not_supersede_itself
            CHECK (
              superseded_by_assignment_id IS NULL
              OR superseded_by_assignment_id <> assignment_id
            ),
          ADD CONSTRAINT an_assignment_names_an_entity_of_its_principal
            FOREIGN KEY (entity_id, principal_id)
            REFERENCES {SCHEMA}.entities (entity_id, principal_id) ON DELETE CASCADE,
          ADD CONSTRAINT an_assignment_is_scoped_within_its_principal
            FOREIGN KEY (scope_entity_id, principal_id)
            REFERENCES {SCHEMA}.entities (entity_id, principal_id)
            ON DELETE SET NULL (scope_entity_id),
          ADD CONSTRAINT an_assignment_is_superseded_within_its_principal
            FOREIGN KEY (superseded_by_assignment_id, principal_id)
            REFERENCES {SCHEMA}.entity_assignments (assignment_id, principal_id)
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_relationships
          ADD CONSTRAINT an_entity_relationship_state_is_known
            CHECK (state IN ({_EDGE_STATE_VALUES})),
          ADD CONSTRAINT an_entity_relationship_ends_only_once_it_leaves_service
            CHECK (ended_at IS NULL OR state <> 'active'),
          ADD CONSTRAINT an_entity_relationship_names_a_successor_only_when_superseded
            CHECK (superseded_by_relationship_id IS NULL OR state = 'superseded'),
          ADD CONSTRAINT an_entity_relationship_does_not_supersede_itself
            CHECK (
              superseded_by_relationship_id IS NULL
              OR superseded_by_relationship_id <> relationship_id
            ),
          ADD CONSTRAINT an_entity_relationship_leaves_an_entity_of_its_principal
            FOREIGN KEY (from_entity_id, principal_id)
            REFERENCES {SCHEMA}.entities (entity_id, principal_id) ON DELETE CASCADE,
          ADD CONSTRAINT an_entity_relationship_reaches_an_entity_of_its_principal
            FOREIGN KEY (to_entity_id, principal_id)
            REFERENCES {SCHEMA}.entities (entity_id, principal_id) ON DELETE CASCADE,
          ADD CONSTRAINT an_entity_relationship_is_scoped_within_its_principal
            FOREIGN KEY (scope_entity_id, principal_id)
            REFERENCES {SCHEMA}.entities (entity_id, principal_id)
            ON DELETE SET NULL (scope_entity_id),
          ADD CONSTRAINT an_entity_relationship_is_superseded_within_its_principal
            FOREIGN KEY (superseded_by_relationship_id, principal_id)
            REFERENCES {SCHEMA}.entity_relationships (relationship_id, principal_id)
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_observations
          ADD CONSTRAINT an_observation_authority_is_known
            CHECK (authority IN ({_OBSERVATION_AUTHORITY_VALUES})),
          ADD CONSTRAINT an_observation_state_is_known
            CHECK (state IN ({_OBSERVATION_STATE_VALUES})),
          ADD CONSTRAINT an_observation_state_reason_explains_a_departure_from_current
            CHECK (
              state_reason IS NULL
              OR (
                state <> 'current'
                AND length(trim(state_reason)) > 0
                AND length(state_reason) <= {_REASON_LIMIT}
              )
            ),
          ADD CONSTRAINT an_observation_names_a_successor_only_when_superseded
            CHECK (superseded_by_observation_id IS NULL OR state = 'superseded'),
          ADD CONSTRAINT an_observation_does_not_supersede_itself
            CHECK (
              superseded_by_observation_id IS NULL
              OR superseded_by_observation_id <> observation_id
            ),
          ADD CONSTRAINT an_observation_resolution_version_is_not_negative
            CHECK (resolution_version >= 0),
          ADD CONSTRAINT an_observation_refers_to_an_entity_of_its_principal
            FOREIGN KEY (entity_id, principal_id)
            REFERENCES {SCHEMA}.entities (entity_id, principal_id)
            ON DELETE SET NULL (entity_id),
          ADD CONSTRAINT an_observation_is_superseded_within_its_principal
            FOREIGN KEY (superseded_by_observation_id, principal_id)
            REFERENCES {SCHEMA}.entity_observations (observation_id, principal_id)
        """
    )

    # The four partial uniques. Partial rather than total, because the
    # historical rows are the point: a total unique would force the plane to
    # delete a retired binding in order to record its replacement.
    op.execute(
        f"""
        CREATE UNIQUE INDEX an_active_external_identifier_binding_is_unique
          ON {SCHEMA}.entity_external_identifiers (principal_id, namespace, normalized_value)
          WHERE state = 'active';
        CREATE UNIQUE INDEX an_active_alias_is_unique_per_entity_and_type
          ON {SCHEMA}.entity_aliases (principal_id, entity_id, alias_type, normalized_value)
          WHERE state = 'active';
        CREATE UNIQUE INDEX an_active_assignment_is_recorded_once
          ON {SCHEMA}.entity_assignments (
            principal_id,
            entity_id,
            assignment_type,
            COALESCE(scope_entity_id, ''),
            COALESCE(lower(trim(role)), ''),
            COALESCE(lower(trim(discipline)), ''),
            COALESCE(lower(trim(responsibility_class)), '')
          )
          WHERE state = 'active';
        CREATE UNIQUE INDEX an_active_entity_relationship_is_recorded_once
          ON {SCHEMA}.entity_relationships (
            principal_id,
            from_entity_id,
            relationship_type,
            to_entity_id,
            COALESCE(scope_entity_id, '')
          )
          WHERE state = 'active';
        """
    )

    # And the two total uniques they replace come off, in the same step. Leaving
    # them would have made the partial ones decorative: a total unique over
    # `(entity_id, namespace, normalized_value)` refuses re-binding an address on
    # the *same* entity it was retired from, which is the ordinary correction
    # this whole vocabulary exists to record.
    for table, name, _columns in _LEGACY_TOTAL_UNIQUES:
        op.execute(f'ALTER TABLE {SCHEMA}.{table} DROP CONSTRAINT "{name}"')

    # The merge ledger, which named its two entities and its proposal by a
    # single column each and so accepted a merge record of one Principal that
    # merged away another Principal's entity, or cited another Principal's
    # proposal.
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_merge_records
          ADD CONSTRAINT a_merge_retains_an_entity_of_its_principal
            FOREIGN KEY (retained_entity_id, principal_id)
            REFERENCES {SCHEMA}.entities (entity_id, principal_id) ON DELETE CASCADE,
          ADD CONSTRAINT a_merge_merges_away_an_entity_of_its_principal
            FOREIGN KEY (merged_entity_id, principal_id)
            REFERENCES {SCHEMA}.entities (entity_id, principal_id) ON DELETE CASCADE,
          ADD CONSTRAINT a_merge_cites_a_proposal_of_its_principal
            FOREIGN KEY (proposal_id, principal_id)
            REFERENCES {SCHEMA}.entity_proposals (proposal_id, principal_id)
        """
    )

    _restate_namespaces(_NAMESPACE_VALUES_AT_THIS_REVISION)


def downgrade() -> None:
    _restate_namespaces(_NAMESPACE_VALUES_BEFORE_THIS_REVISION)

    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_merge_records
          DROP CONSTRAINT a_merge_cites_a_proposal_of_its_principal,
          DROP CONSTRAINT a_merge_merges_away_an_entity_of_its_principal,
          DROP CONSTRAINT a_merge_retains_an_entity_of_its_principal
        """
    )

    for table, name, columns in reversed(_LEGACY_TOTAL_UNIQUES):
        op.execute(f'ALTER TABLE {SCHEMA}.{table} ADD CONSTRAINT "{name}" UNIQUE ({columns})')

    op.execute(
        f"""
        DROP INDEX {SCHEMA}.an_active_entity_relationship_is_recorded_once;
        DROP INDEX {SCHEMA}.an_active_assignment_is_recorded_once;
        DROP INDEX {SCHEMA}.an_active_alias_is_unique_per_entity_and_type;
        DROP INDEX {SCHEMA}.an_active_external_identifier_binding_is_unique;
        """
    )

    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_observations
          DROP CONSTRAINT an_observation_is_superseded_within_its_principal,
          DROP CONSTRAINT an_observation_refers_to_an_entity_of_its_principal,
          DROP CONSTRAINT an_observation_resolution_version_is_not_negative,
          DROP CONSTRAINT an_observation_does_not_supersede_itself,
          DROP CONSTRAINT an_observation_names_a_successor_only_when_superseded,
          DROP CONSTRAINT an_observation_state_reason_explains_a_departure_from_current,
          DROP CONSTRAINT an_observation_state_is_known,
          DROP CONSTRAINT an_observation_authority_is_known
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_relationships
          DROP CONSTRAINT an_entity_relationship_is_superseded_within_its_principal,
          DROP CONSTRAINT an_entity_relationship_is_scoped_within_its_principal,
          DROP CONSTRAINT an_entity_relationship_reaches_an_entity_of_its_principal,
          DROP CONSTRAINT an_entity_relationship_leaves_an_entity_of_its_principal,
          DROP CONSTRAINT an_entity_relationship_does_not_supersede_itself,
          DROP CONSTRAINT an_entity_relationship_names_a_successor_only_when_superseded,
          DROP CONSTRAINT an_entity_relationship_ends_only_once_it_leaves_service,
          DROP CONSTRAINT an_entity_relationship_state_is_known
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_assignments
          DROP CONSTRAINT an_assignment_is_superseded_within_its_principal,
          DROP CONSTRAINT an_assignment_is_scoped_within_its_principal,
          DROP CONSTRAINT an_assignment_names_an_entity_of_its_principal,
          DROP CONSTRAINT an_assignment_does_not_supersede_itself,
          DROP CONSTRAINT an_assignment_names_a_successor_only_when_superseded,
          DROP CONSTRAINT an_assignment_ends_only_once_it_leaves_service,
          DROP CONSTRAINT an_assignment_version_is_positive,
          DROP CONSTRAINT an_assignment_state_is_known
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_aliases
          DROP CONSTRAINT an_alias_is_superseded_within_its_principal,
          DROP CONSTRAINT an_alias_names_an_entity_of_its_principal,
          DROP CONSTRAINT an_alias_does_not_supersede_itself,
          DROP CONSTRAINT an_alias_names_a_successor_only_when_superseded,
          DROP CONSTRAINT an_alias_is_retired_only_once_it_leaves_service,
          DROP CONSTRAINT an_alias_version_is_positive,
          DROP CONSTRAINT an_alias_state_is_known
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_external_identifiers
          DROP CONSTRAINT an_external_identifier_is_superseded_within_its_principal,
          DROP CONSTRAINT an_external_identifier_binds_an_entity_of_its_principal,
          DROP CONSTRAINT an_external_identifier_does_not_supersede_itself,
          DROP CONSTRAINT an_external_identifier_names_a_successor_only_when_superseded,
          DROP CONSTRAINT an_external_identifier_is_retired_only_once_it_leaves_service,
          DROP CONSTRAINT an_external_identifier_version_is_positive,
          DROP CONSTRAINT an_external_identifier_state_is_known
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entities
          DROP CONSTRAINT an_entity_redirects_within_its_principal,
          DROP CONSTRAINT an_entity_records_the_status_it_was_archived_from,
          DROP CONSTRAINT an_archived_from_status_is_known
        """
    )

    for table, trigger in _IMMUTABLE_TABLES:
        op.execute(f"DROP TRIGGER {trigger} ON {SCHEMA}.{table}")
    op.execute(f"DROP FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}()")
    op.execute(
        f"""
        DROP TABLE {SCHEMA}.entity_resolution_decisions;
        DROP TABLE {SCHEMA}.entity_fact_evidence_links;
        DROP TABLE {SCHEMA}.entity_mutation_events;
        """
    )

    for table, _key, name in reversed(_COMPOSITE_IDENTITIES):
        op.execute(f'ALTER TABLE {SCHEMA}.{table} DROP CONSTRAINT "{name}"')

    op.execute(f"ALTER TABLE {SCHEMA}.entity_assignments RENAME COLUMN state TO status")
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_observations
          DROP COLUMN resolution_version,
          DROP COLUMN superseded_by_observation_id,
          DROP COLUMN state_reason,
          DROP COLUMN state,
          DROP COLUMN authority
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_relationships
          DROP COLUMN superseded_by_relationship_id,
          DROP COLUMN ended_at,
          DROP COLUMN updated_at
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_assignments
          DROP COLUMN superseded_by_assignment_id,
          DROP COLUMN ended_at,
          DROP COLUMN updated_at,
          DROP COLUMN version
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_aliases
          DROP COLUMN superseded_by_alias_id,
          DROP COLUMN retired_at,
          DROP COLUMN updated_at,
          DROP COLUMN version,
          DROP COLUMN state
        """
    )
    op.execute(
        f"""
        ALTER TABLE {SCHEMA}.entity_external_identifiers
          DROP COLUMN superseded_by_identifier_id,
          DROP COLUMN retired_at,
          DROP COLUMN updated_at,
          DROP COLUMN version,
          DROP COLUMN state
        """
    )
    op.execute(f"ALTER TABLE {SCHEMA}.entities DROP COLUMN archived_from_status")
