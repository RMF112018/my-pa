"""create the review, promotion, context-link and conversation tables

Adds seven tables to the existing `knowledge` schema — `capture_review_cases`,
`capture_review_decisions`, `capture_assertions`, `capture_assertion_spans`,
`capture_promotion_receipts`, `capture_context_links` and
`capture_conversations` — widens `audit_events.capability_is_known` to fifteen
and `audit_events.purpose_is_known` to ten, installs the constraint triggers
that make "every assertion cites at least one span" and "an accepted record
names a real assertion" properties of the schema, makes proposals and assertions
undeletable, and makes review cases, decisions, and promotion receipts immutable.
It creates no schema and reads nothing from the migrated legacy corpus.

The tables are named explicitly rather than taken from the shared `MetaData`,
for the reason `8b3f5c17d904`, `1a4c9e77b2d5` and `2b7e9f4c1a83` all state:
every table in this schema is declared in one module, so an unqualified
`create_all` here would also create the twenty-two that earlier revisions own —
and would then start creating whatever a later revision declares, which would
make this file's meaning depend on code written after it.

**Why this revision alters two constraints an earlier revision created.**
`audit_events.capability` and `audit_events.purpose` are closed to the
vocabularies that existed when the revisions below merged, and this package adds
two capabilities (`review.list`, `review.decide`) and one purpose
(`review_disposition`). Widening either by editing a merged declaration would
change what an already-merged revision emits — the `D-48` hazard — so the
widening is an explicit forward `ALTER` here. **The literals below are frozen**,
per the standing rule `9c6b4a18ed72` states: no Alembic revision may derive a
closed-set constraint from a domain enum. **A new purpose rather than a reuse of
`capture_review`** because `review.decide` promotes a proposal to a canonical
assertion: a grant issued for reading captures must not also authorize
promotion, which is the escalation `domain/identity/purpose.py` says the split
exists to refuse.

**The freeze is written before the members, and that order is the whole point.**
A capability added to the enum with no forward `ALTER` leaves every test green —
every test builds its database from scratch — and is refused by the stored
constraint on the first audited operation in the field.
`tests/schema/test_capture_schema_migration.py` holds the other end against a
live server.

**And the same freeze applies to the eight closed-set constraints on this
revision's own seven tables**, taken off the shared declaration and restated
here, because otherwise a member added to any of `Disposition`, `ProposalType`,
`AssertionState`, `ContextLinkTarget`, `ContextLinkRole`, `ContextLinkAuthority`,
`ConversationState` or `ConversationChannel` would change what *this* revision
emits after it merged.
`tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`
enforces the rule across the chain, and this revision's emission callable is
named in that module's `_EMISSION_CALLABLES`; without the entry the guard reads
nothing here and says so by passing.

**Why there is a constraint trigger on `capture_proposals` and not a foreign
key.** `capture_proposals.accepted_record_id` is declared with no `ForeignKey`
because the table it names did not exist when `2b7e9f4c1a83` merged. Adding one
now to the shared declaration would retroactively change what that merged
revision emits, and the freeze does not protect against it: `_historical_wp7_tables`
replaces only the named `CheckConstraint`s, so columns, foreign keys, unique
constraints and indexes are still declaration-driven. A `DEFERRABLE INITIALLY
DEFERRED` constraint trigger created here is not a `Table` attribute, so it
cannot enter that copy — and it is stronger than the foreign key would have
been, because it also refuses an `accepted_record_type` that is not `assertion`.

**Why lineage cannot be rewritten.** `QC-AC-022` requires rejected and corrected
proposals to retain their exact evidence. Only `capture_versions` carried an
append-only trigger before this revision; proposal/assertion parents, spans, and
their link rows could otherwise be deleted or rebound through direct SQL or an
FK cascade. The span evidence table and both link tables therefore refuse
`UPDATE OR DELETE`, while proposals and assertions refuse deletion and admit
only the state-and-companion-column transitions the application actually writes.
Proposal review routing, disposition, acceptance, and invalidation are distinct
allowed row shapes; assertion revalidation is the sole assertion update. Review
cases, decisions, and promotion receipts remain wholly immutable. Every refusal
raises `restrict_violation` at the server rather than trusting the current writer.

The downgrade drops the seven tables, drops every trigger and each shared
function — `RESTRICT`, not `CASCADE`, is what `7e5a1fb93d62` uses to drop the
schema, so a function left behind here would make `downgrade base` fail — and
narrows both constraints back to the frozen thirteen and nine, so that a
database downgraded past this revision is in the state the revision below it
describes rather than in a state no revision describes.

Revision ID: 3c8f1e2a5b74
Revises: 2b7e9f4c1a83
Created: 2026-08-04 09:30:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op
from sqlalchemy import CheckConstraint, MetaData, Table

from my_pa.infrastructure.persistence.tables import (
    SCHEMA,
    capture_assertion_spans,
    capture_assertions,
    capture_context_links,
    capture_conversations,
    capture_processing_text,
    capture_promotion_receipts,
    capture_proposals,
    capture_review_cases,
    capture_review_decisions,
    capture_spans,
    capture_versions,
    captures,
)

revision: str = "3c8f1e2a5b74"
down_revision: str | None = "2b7e9f4c1a83"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Exactly the seven tables this revision's docstring documents. Ordered so that
#: `create_all` sees a referenced table before the table that references it.
_TABLES: list[Table] = [
    capture_review_cases,
    capture_review_decisions,
    capture_assertions,
    capture_assertion_spans,
    capture_promotion_receipts,
    capture_context_links,
    capture_conversations,
]

#: The capability vocabulary as of this revision, written out. Frozen, per the
#: standing rule in `9c6b4a18ed72`. Sorted, which is the order the declarative
#: helper produces, so the two texts can be compared directly.
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'knowledge.read', "
    "'knowledge.search', 'review.decide', 'review.list', 'sources.enroll', "
    "'sources.fetch', 'sources.list', 'sources.metadata', 'sources.status')"
)

#: The purpose vocabulary as of this revision. `review_disposition` is the tenth.
_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'content_extraction', 'knowledge_read', 'knowledge_search', "
    "'review_disposition', 'security_validation', 'source_inspection', "
    "'status_observation')"
)

#: What the revision below emits, restated here because a downgrade has to put
#: the constraints back to the vocabularies that revision denotes rather than to
#: whatever the domain says today.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'knowledge.read', "
    "'knowledge.search', 'sources.enroll', 'sources.fetch', 'sources.list', "
    "'sources.metadata', 'sources.status')"
)

_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'content_extraction', 'knowledge_read', 'knowledge_search', "
    "'security_validation', 'source_inspection', 'status_observation')"
)

#: Every closed-set constraint on this revision's own seven tables, written out.
#: Same mechanism and same reason as the thirteen in `2b7e9f4c1a83`. The texts
#: are the declarative helper's own output — sorted — so what is emitted is
#: identical to the derived text, not merely equivalent.
_FROZEN: Final[dict[str, dict[str, str]]] = {
    "capture_review_decisions": {
        "review_disposition_is_known": (
            "disposition IN ('accept', 'correct_and_accept', 'defer', 'escalate', "
            "'mark_unresolved', 'reject', 'reprocess')"
        ),
    },
    "capture_assertions": {
        "assertion_type_is_known": (
            "assertion_type IN ('commitment', 'decision', 'follow_up', 'issue', "
            "'open_question', 'risk', 'task')"
        ),
        "assertion_state_is_known": (
            "state IN ('accepted', 'contradicted', 'proposed', "
            "'revalidation_required', 'stale', 'superseded', 'withdrawn')"
        ),
    },
    "capture_context_links": {
        "context_link_target_type_is_known": "target_type IN ('source_object')",
        "context_link_role_is_known": "link_role IN ('launch_context')",
        "context_link_authority_state_is_known": (
            "authority_state IN ('deterministic', 'proposed', 'rejected', "
            "'superseded', 'user_confirmed')"
        ),
    },
    "capture_conversations": {
        "conversation_event_state_is_known": (
            "event_state IN ('accepted', 'archived', 'proposed', 'skeletal', 'superseded')"
        ),
        "conversation_channel_is_known": "channel IN ('unknown')",
    },
}

#: The function both assertion-span triggers run, and the triggers themselves.
#: Two triggers rather than one, on `D-98`'s measured grounds: an `AFTER INSERT`
#: alone is satisfied by writing the rows and then removing the link.
_SPAN_CARDINALITY_FUNCTION: Final = "an_assertion_cites_a_span"
_ASSERTION_TRIGGER: Final = "an_assertion_cites_at_least_one_span"
_ASSERTION_LINK_TRIGGER: Final = "a_span_link_leaves_its_assertion_cited"

#: The substitute for the foreign key `capture_proposals.accepted_record_id`
#: cannot carry. See the docstring above.
_ACCEPTED_RECORD_FUNCTION: Final = "an_accepted_record_names_an_assertion"
_ACCEPTED_RECORD_TRIGGER: Final = "an_accepted_proposal_names_a_real_assertion"

#: The type an `accepted_record_type` must name for the identifier beside it to
#: be checked. Written out rather than imported for the reason every literal in
#: this file is written out: a revision that read a module constant would emit
#: different DDL the day that constant changed.
_ACCEPTED_RECORD_TYPE: Final = "assertion"

#: The function the lineage triggers share, and the tables they guard.
#: `capture_proposals` is one of them and is not a table this revision creates:
#: the trigger is forward DDL, so it changes nothing an earlier revision emits.
_LINEAGE_FUNCTION: Final = "review_lineage_stays_as_written"
_GOVERNED_TABLES: Final = (
    "capture_proposals",
    "capture_assertions",
)
_IMMUTABLE_TABLES: Final = (
    "capture_spans",
    "capture_proposal_spans",
    "capture_assertion_spans",
    "capture_review_cases",
    "capture_review_decisions",
    "capture_promotion_receipts",
)
_LINEAGE_TABLES: Final = (*_GOVERNED_TABLES, *_IMMUTABLE_TABLES)

#: Proposal and assertion updates are admitted by one server function only when
#: their complete OLD/NEW row shape is one of the application's real writers.
_GOVERNED_UPDATE_FUNCTION: Final = "review_state_transition_is_governed"


def _lineage_trigger(table: str) -> str:
    if table in _IMMUTABLE_TABLES:
        return f"{table}_stay_immutable"
    return f"{table}_are_never_deleted"


def _governed_update_trigger(table: str) -> str:
    return f"{table}_updates_are_governed"


def _historical_wp8_tables() -> list[Table]:
    """The seven tables as this revision emits them, with the eight checks frozen.

    Copies into a throwaway `MetaData` rather than restating the declarations,
    which is the pattern `9c6b4a18ed72` establishes and `1a4c9e77b2d5` and
    `2b7e9f4c1a83` repeat, and for the reason they give: a duplicated column
    list here would be a second statement of each table and would drift from the
    first in a way nothing checks. All seven are copied into the *same* throwaway
    metadata, so the foreign keys among them — `capture_assertion_spans` to
    `capture_assertions`, `capture_promotion_receipts` to both
    `capture_assertions` and `capture_review_decisions`, and the three self
    references — resolve inside the copy rather than back at the shared
    declaration.

    **Five tables this revision does not create are copied in first**, and that
    is not an oversight in the list above. `Table.to_metadata` resolves a foreign
    key inside the metadata it is copied into: without them, emitting this
    revision raises `NoReferencedTableError` before it reaches a server, which is
    how `2b7e9f4c1a83` found the same thing — `--sql` offline mode failed for
    every revision in the chain. They are copied so the references resolve and
    are **not** returned, so `create_all` and `drop_all` are still handed exactly
    the seven this revision owns and the guard still reads exactly the eight
    closed sets this revision emits. `captures`, `capture_versions` and
    `capture_processing_text` come with them because `capture_proposals` and
    `capture_spans` reference them.

    The name is in `_EMISSION_CALLABLES` in
    `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`.
    Without that entry the guard's `_emitted` falls through to a module-level
    `_TABLES` list, and every closed set below would be read off the live
    declaration instead of off this freeze — which is why that module now refuses
    the fallback for a revision that declares `_FROZEN`.
    """
    frozen = MetaData(schema=SCHEMA)
    for referenced in (
        captures,
        capture_versions,
        capture_processing_text,
        capture_spans,
        capture_proposals,
    ):
        referenced.to_metadata(frozen)
    copies = [table.to_metadata(frozen) for table in _TABLES]
    for copy in copies:
        replacements = _FROZEN.get(copy.name, {})
        for constraint in [
            candidate for candidate in copy.constraints if candidate.name in replacements
        ]:
            copy.constraints.discard(constraint)
        for name, expression in replacements.items():
            copy.append_constraint(CheckConstraint(expression, name=name))
    return copies


def _restate(capability: str, purpose: str) -> None:
    """Replace both closed-set constraints on `audit_events` in one transaction.

    Dropped and recreated rather than validated in place: PostgreSQL has no
    "alter the expression of a check constraint", and doing it in two statements
    inside the revision's own transaction means there is no instant at which
    either column is unconstrained that another session could observe.
    `1a4c9e77b2d5` does the same for the same two; `2b7e9f4c1a83` moved one,
    because it added no purpose.
    """
    for name, expression in (
        ("capability_is_known", capability),
        ("purpose_is_known", purpose),
    ):
        op.execute(f'ALTER TABLE {SCHEMA}.audit_events DROP CONSTRAINT "{name}"')
        op.execute(
            f'ALTER TABLE {SCHEMA}.audit_events ADD CONSTRAINT "{name}" CHECK ({expression})'
        )


def upgrade() -> None:
    _restate(_CAPABILITIES_AT_THIS_REVISION, _PURPOSES_AT_THIS_REVISION)
    frozen = _historical_wp8_tables()
    frozen[0].metadata.create_all(op.get_bind(), tables=frozen)
    op.execute(
        # The `noqa` below is `S608`, and the reason it is safe is structural:
        # the only interpolations are this module's own `Final` constants — the
        # schema name and the function name. No caller value reaches this text,
        # and the trigger's `subject` is a plpgsql variable, not a substitution.
        f"CREATE FUNCTION {SCHEMA}.{_SPAN_CARDINALITY_FUNCTION}() RETURNS trigger "  # noqa: S608
        "LANGUAGE plpgsql AS $$ "
        "DECLARE subject text; "
        "BEGIN "
        "IF TG_OP = 'DELETE' THEN "
        "  subject := OLD.assertion_id; "
        f"  IF NOT EXISTS (SELECT 1 FROM {SCHEMA}.capture_assertions "
        "                 WHERE assertion_id = subject) THEN RETURN NULL; END IF; "
        "ELSE subject := NEW.assertion_id; END IF; "
        f"IF NOT EXISTS (SELECT 1 FROM {SCHEMA}.capture_assertion_spans "
        "               WHERE assertion_id = subject) THEN "
        "  RAISE EXCEPTION "
        "    'knowledge.capture_assertions carries at least one span; % leaves none', TG_OP "
        "    USING ERRCODE = 'restrict_violation'; "
        "END IF; "
        "RETURN NULL; "
        "END; $$"
    )
    op.execute(
        f"CREATE CONSTRAINT TRIGGER {_ASSERTION_TRIGGER} "
        f"AFTER INSERT ON {SCHEMA}.capture_assertions "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        f"EXECUTE FUNCTION {SCHEMA}.{_SPAN_CARDINALITY_FUNCTION}()"
    )
    op.execute(
        f"CREATE CONSTRAINT TRIGGER {_ASSERTION_LINK_TRIGGER} "
        f"AFTER DELETE ON {SCHEMA}.capture_assertion_spans "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        f"EXECUTE FUNCTION {SCHEMA}.{_SPAN_CARDINALITY_FUNCTION}()"
    )
    op.execute(
        # `S608` again, and safe on the same terms: the schema name, the function
        # name and the record type are this module's own constants.
        f"CREATE FUNCTION {SCHEMA}.{_ACCEPTED_RECORD_FUNCTION}() RETURNS trigger "  # noqa: S608
        "LANGUAGE plpgsql AS $$ "
        "BEGIN "
        "IF NEW.accepted_record_id IS NULL THEN RETURN NULL; END IF; "
        f"IF NEW.accepted_record_type IS DISTINCT FROM '{_ACCEPTED_RECORD_TYPE}' THEN "
        "  RAISE EXCEPTION "
        "    'knowledge.capture_proposals names an accepted record of one type' "
        "    USING ERRCODE = 'restrict_violation'; "
        "END IF; "
        f"IF NOT EXISTS (SELECT 1 FROM {SCHEMA}.capture_assertions a "
        f"               JOIN {SCHEMA}.capture_review_decisions d "
        "                 ON d.decision_id = a.decision_id "
        f"               JOIN {SCHEMA}.capture_review_cases c "
        "                 ON c.review_case_id = d.review_case_id "
        "               WHERE a.assertion_id = NEW.accepted_record_id "
        "                 AND a.proposal_id = NEW.proposal_id "
        "                 AND a.version_id = NEW.version_id "
        "                 AND a.assertion_type = NEW.proposal_type "
        # `revalidation_required` is the sole governed post-acceptance state.
        # A deferred proposal check observes the assertion's state at commit,
        # so both states must retain the same exact accepted-record binding.
        "                 AND a.state IN ('accepted', 'revalidation_required') "
        "                 AND a.superseded_by_assertion_id IS NULL "
        "                 AND a.accepted_at IS NOT DISTINCT FROM d.decided_at "
        "                 AND c.proposal_id = NEW.proposal_id "
        "                 AND a.normalized_value IS NOT DISTINCT FROM NEW.normalized_value "
        "                 AND ((NEW.state = 'accepted' AND d.disposition = 'accept') "
        "                   OR (NEW.state = 'corrected_accepted' "
        "                       AND d.disposition = 'correct_and_accept'))) THEN "
        "  RAISE EXCEPTION "
        "    'knowledge.capture_proposals names its exact accepted assertion' "
        "    USING ERRCODE = 'restrict_violation'; "
        "END IF; "
        "RETURN NULL; "
        "END; $$"
    )
    op.execute(
        f"CREATE CONSTRAINT TRIGGER {_ACCEPTED_RECORD_TRIGGER} "
        f"AFTER INSERT OR UPDATE ON {SCHEMA}.capture_proposals "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        f"EXECUTE FUNCTION {SCHEMA}.{_ACCEPTED_RECORD_FUNCTION}()"
    )
    op.execute(
        f"CREATE FUNCTION {SCHEMA}.{_GOVERNED_UPDATE_FUNCTION}() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ "
        "DECLARE allowed boolean := false; "
        "BEGIN "
        "IF TG_TABLE_NAME = 'capture_proposals' THEN "
        "  allowed := "
        "    NEW.proposal_id IS NOT DISTINCT FROM OLD.proposal_id "
        "    AND NEW.version_id IS NOT DISTINCT FROM OLD.version_id "
        "    AND NEW.proposal_type IS NOT DISTINCT FROM OLD.proposal_type "
        "    AND NEW.risk_class IS NOT DISTINCT FROM OLD.risk_class "
        "    AND NEW.method IS NOT DISTINCT FROM OLD.method "
        "    AND NEW.method_version IS NOT DISTINCT FROM OLD.method_version "
        "    AND NEW.schema_version IS NOT DISTINCT FROM OLD.schema_version "
        "    AND NEW.missing_required_fields IS NOT DISTINCT FROM OLD.missing_required_fields "
        "    AND NEW.created_at IS NOT DISTINCT FROM OLD.created_at "
        "    AND ("
        "      (OLD.state = 'proposed' AND NEW.state = 'needs_review' "
        "       AND NEW.normalized_value IS NOT DISTINCT FROM OLD.normalized_value "
        "       AND NEW.quarantine_reason IS NOT DISTINCT FROM OLD.quarantine_reason "
        "       AND NEW.accepted_record_type IS NOT DISTINCT FROM OLD.accepted_record_type "
        "       AND NEW.accepted_record_id IS NOT DISTINCT FROM OLD.accepted_record_id) "
        "      OR (OLD.state IN ('proposed', 'needs_review') "
        "          AND NEW.state IN ('rejected', 'deferred', 'unresolved') "
        "          AND NEW.normalized_value IS NOT DISTINCT FROM OLD.normalized_value "
        "          AND NEW.quarantine_reason IS NOT DISTINCT FROM OLD.quarantine_reason "
        "          AND NEW.accepted_record_type IS NOT DISTINCT FROM OLD.accepted_record_type "
        "          AND NEW.accepted_record_id IS NOT DISTINCT FROM OLD.accepted_record_id) "
        "      OR (OLD.state IN ('proposed', 'needs_review') "
        "          AND NEW.state IN ('accepted', 'corrected_accepted') "
        "          AND NEW.quarantine_reason IS NOT DISTINCT FROM OLD.quarantine_reason "
        "          AND NEW.accepted_record_type = 'assertion' "
        "          AND OLD.accepted_record_type IS NULL "
        "          AND NEW.accepted_record_id IS NOT NULL "
        "          AND OLD.accepted_record_id IS NULL "
        "          AND (NEW.state = 'corrected_accepted' "
        "               OR NEW.normalized_value IS NOT DISTINCT FROM OLD.normalized_value)) "
        "      OR (OLD.state IN ('proposed', 'needs_review', 'rejected', 'deferred', 'unresolved') "
        "          AND NEW.state = 'invalidated' "
        "          AND OLD.quarantine_reason IS NULL "
        "          AND NEW.quarantine_reason IS NOT NULL "
        "          AND NEW.normalized_value IS NOT DISTINCT FROM OLD.normalized_value "
        "          AND NEW.accepted_record_type IS NOT DISTINCT FROM OLD.accepted_record_type "
        "          AND NEW.accepted_record_id IS NOT DISTINCT FROM OLD.accepted_record_id)"
        "    ); "
        "ELSIF TG_TABLE_NAME = 'capture_assertions' THEN "
        "  allowed := OLD.state = 'accepted' "
        "    AND NEW.state = 'revalidation_required' "
        "    AND OLD.revalidation_required_at IS NULL "
        "    AND NEW.revalidation_required_at IS NOT NULL "
        "    AND NEW.assertion_id IS NOT DISTINCT FROM OLD.assertion_id "
        "    AND NEW.version_id IS NOT DISTINCT FROM OLD.version_id "
        "    AND NEW.proposal_id IS NOT DISTINCT FROM OLD.proposal_id "
        "    AND NEW.decision_id IS NOT DISTINCT FROM OLD.decision_id "
        "    AND NEW.assertion_type IS NOT DISTINCT FROM OLD.assertion_type "
        "    AND NEW.normalized_value IS NOT DISTINCT FROM OLD.normalized_value "
        "    AND NEW.superseded_by_assertion_id "
        "        IS NOT DISTINCT FROM OLD.superseded_by_assertion_id "
        "    AND NEW.accepted_at IS NOT DISTINCT FROM OLD.accepted_at; "
        "END IF; "
        "IF allowed IS NOT TRUE THEN "
        "  RAISE EXCEPTION 'knowledge.% permits only governed state transitions', TG_TABLE_NAME "
        "    USING ERRCODE = 'restrict_violation'; "
        "END IF; "
        "RETURN NEW; "
        "END; $$"
    )
    for table in _GOVERNED_TABLES:
        op.execute(
            f"CREATE TRIGGER {_governed_update_trigger(table)} "
            f"BEFORE UPDATE ON {SCHEMA}.{table} FOR EACH ROW "
            f"EXECUTE FUNCTION {SCHEMA}.{_GOVERNED_UPDATE_FUNCTION}()"
        )
    op.execute(
        f"CREATE FUNCTION {SCHEMA}.{_LINEAGE_FUNCTION}() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION 'knowledge.% retains lineage; % is refused', TG_TABLE_NAME, TG_OP "
        "USING ERRCODE = 'restrict_violation'; "
        "END; $$"
    )
    for table in _LINEAGE_TABLES:
        events = "UPDATE OR DELETE" if table in _IMMUTABLE_TABLES else "DELETE"
        op.execute(
            f"CREATE TRIGGER {_lineage_trigger(table)} "
            f"BEFORE {events} ON {SCHEMA}.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_LINEAGE_FUNCTION}()"
        )


def downgrade() -> None:
    # Each trigger goes with its table, and four sit on tables this revision does
    # not drop. The functions go with none of them, and
    # `7e5a1fb93d62` drops the schema with RESTRICT, so a function left behind
    # would fail the downgrade at a revision that has no idea this one existed.
    for table in _LINEAGE_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {_lineage_trigger(table)} ON {SCHEMA}.{table}")
    for table in _GOVERNED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS {_governed_update_trigger(table)} ON {SCHEMA}.{table}")
    op.execute(f"DROP TRIGGER IF EXISTS {_ACCEPTED_RECORD_TRIGGER} ON {SCHEMA}.capture_proposals")
    op.execute(
        f"DROP TRIGGER IF EXISTS {_ASSERTION_LINK_TRIGGER} ON {SCHEMA}.capture_assertion_spans"
    )
    op.execute(f"DROP TRIGGER IF EXISTS {_ASSERTION_TRIGGER} ON {SCHEMA}.capture_assertions")
    frozen = _historical_wp8_tables()
    frozen[0].metadata.drop_all(op.get_bind(), tables=frozen)
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.{_LINEAGE_FUNCTION}()")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.{_GOVERNED_UPDATE_FUNCTION}()")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.{_ACCEPTED_RECORD_FUNCTION}()")
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.{_SPAN_CARDINALITY_FUNCTION}()")
    _restate(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)
