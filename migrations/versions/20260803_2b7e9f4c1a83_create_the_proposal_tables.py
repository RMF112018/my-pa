"""create the proposal tables and the exact capture-search index

Adds seven tables to the existing `knowledge` schema — `capture_processing_text`,
`capture_stage_results`, `capture_spans`, `capture_proposals`,
`capture_proposal_spans`, `capture_classifications`, and
`capture_entity_mentions` — widens `audit_events.capability_is_known` to
thirteen, installs the deferred constraint trigger that makes "every proposal
carries at least one span" a property of the schema, and creates the functional
GIN index the exact capture search matches against. It creates no schema and
reads nothing from the migrated legacy corpus.

The tables are named explicitly rather than taken from the shared `MetaData`,
for the reason `8b3f5c17d904` and `1a4c9e77b2d5` both state: every table in this
schema is declared in one module, so an unqualified `create_all` here would also
create the fifteen that earlier revisions own — and would then start creating
whatever a later revision declares, which would make this file's meaning depend
on code written after it.

**Why this revision alters a constraint an earlier revision created.**
`audit_events.capability` is closed to the vocabulary that existed when
`1a4c9e77b2d5` merged, and this package adds one capability, `capture.search`.
Widening it by editing either merged declaration would change what an
already-merged revision emits — the `D-48` hazard — so the widening is an
explicit forward `ALTER` here. **The literals below are frozen**, per the
standing rule `9c6b4a18ed72` states: no Alembic revision may derive a closed-set
constraint from a domain enum. When a later package adds a capability it writes
another `ALTER`, and this file goes on denoting the vocabulary of the day it
merged. **No `Purpose` member is added** (`D-91`): `capture.search` reuses
`capture_review`, which already serves `capture.read` and `capture.list`, so
`purpose_is_known` does not move and this revision does not touch it.

**And the same freeze applies to the thirteen closed-set constraints on this
revision's own seven tables**, taken off the shared declaration and restated
here, because otherwise a member added to any of `PipelineStage`,
`ProcessingState`, `OffsetBasis`, `SpanRole`, `ProposalType`, `ProposalState`,
`RiskClass`, `ProposalMethod`, `ProposalQuarantineReason`, `ProposalField`,
`CaptureLabel`, `EntityType` or `ResolutionState` would change what *this*
revision emits after it merged.
`tests/schema/test_capture_schema_migration.py` asserts against a live server
that head admits exactly the domain's declaration for every one of them, so a
member added without an `ALTER` reddens — which is the checked claim that
replaces the coupling the freeze breaks.
`tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`
enforces the rule across the chain.

`capture_spans.offset_basis` is written out here as the single literal
`'unicode_code_point_v1'` rather than read from a Python constant (`D-97`). The
scheme name is the specification's own
(`docs/specs/quick-capture/10_SOURCE_AUTHORITY_AND_PROVENANCE_MODEL.md:82`), and
keeping the literal inside the freeze is what stops it becoming a new
single-value-embedding site of the class `D-86` records.

**Why there is a constraint trigger.** `QC-AC-011` requires every persisted
proposal to point at validated source spans, and "at least one" is a `[1..n]`
cardinality across two tables. No `CHECK` can express it: a check is evaluated
against one row of one table, and the row that must be refused is a proposal
whose *other* table holds nothing. A counter column on `capture_proposals` could
express it, at the cost of an `UPDATE` path on a table that otherwise has none
and of a second statement of a fact the link table already holds. A `DEFERRABLE
INITIALLY DEFERRED` constraint trigger checked at commit is the remaining
option, and it is the honest one: expressing the rule in the server rather than
in the writer is what makes it survive a repair script, a later revision, or a
second writer — the same argument `1a4c9e77b2d5` makes for its immutability
trigger, and `QC-AC-011` is the criterion a repair script is most likely to
violate. Deferred, because the proposal must be inserted before a link can
reference it. Two triggers share one function so that deleting the last link is
refused on the same terms as inserting a proposal with none; the exception names
the operation and never a value.

**Why there is an index on a table this revision does not create.**
`QC-AC-050` requires *exact* original text to be searchable, and the plane that
serves it is a functional GIN index over `to_tsvector('simple', content)` on
`knowledge.capture_versions`. Declaring that index on the shared `Table` object
would retroactively change what `1a4c9e77b2d5` emits, which is the same `D-48`
hazard as widening a constraint, so it is created here by forward DDL instead
and dropped by the downgrade. `simple` rather than `english`, and that is
measured rather than stylistic: `english` stems, so a query for `run` matches a
capture that only ever said `running`, and `to_tsvector('english', 'a the of
and')` is **empty**, so a stop-word-only capture is saved, valid, and unfindable
with no exception anywhere (`D-89`, `D-90`). The predicate that must match this
expression is `persistence.capture_search`, and a configuration mismatch between
the two breaks **silently** — the query falls back to a sequential scan and
still returns correct rows — so `tests/schema/test_capture_schema_migration.py`
reads the index's stored definition back rather than trusting this file.

The downgrade drops the seven tables, drops both triggers and their shared
function — `RESTRICT`, not `CASCADE`, is what `7e5a1fb93d62` uses to drop the
schema, so a function left behind here would make `downgrade base` fail —
drops the index, and narrows `capability_is_known` back to the frozen twelve, so
that a database downgraded past this revision is in the state the revision below
it describes rather than in a state no revision describes.

Revision ID: 2b7e9f4c1a83
Revises: 1a4c9e77b2d5
Created: 2026-08-03 20:10:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op
from sqlalchemy import CheckConstraint, MetaData, Table

from my_pa.infrastructure.persistence.tables import (
    SCHEMA,
    capture_classifications,
    capture_entity_mentions,
    capture_jobs,
    capture_processing_text,
    capture_proposal_spans,
    capture_proposals,
    capture_spans,
    capture_stage_results,
    capture_versions,
    captures,
)

revision: str = "2b7e9f4c1a83"
down_revision: str | None = "1a4c9e77b2d5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Exactly the seven tables this revision's docstring documents. Ordered so that
#: `create_all` sees a referenced table before the table that references it.
_TABLES: list[Table] = [
    capture_processing_text,
    capture_stage_results,
    capture_spans,
    capture_proposals,
    capture_proposal_spans,
    capture_classifications,
    capture_entity_mentions,
]

#: The capability vocabulary as of this revision, written out. Frozen, per the
#: standing rule in `9c6b4a18ed72`. Sorted, which is the order the declarative
#: helper produces, so the two texts can be compared directly.
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'capture.search', 'knowledge.read', "
    "'knowledge.search', 'sources.enroll', 'sources.fetch', 'sources.list', "
    "'sources.metadata', 'sources.status')"
)

#: What the revision below emits, restated here because a downgrade has to put
#: the constraint back to the vocabulary that revision denotes rather than to
#: whatever the domain says today.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'knowledge.read', 'knowledge.search', "
    "'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status')"
)

#: Every closed-set constraint on this revision's own seven tables, written out.
#: Same mechanism and same reason as the eight in `1a4c9e77b2d5`. The texts are
#: the declarative helper's own output — sorted, and `<@ ARRAY[…]` for the one
#: constraint over an array column — so what is emitted is identical to the
#: derived text, not merely equivalent.
_FROZEN: Final[dict[str, dict[str, str]]] = {
    "capture_stage_results": {
        "capture_stage_is_known": (
            "stage IN ('datetime_normalization', 'detect_language', "
            "'deterministic_extraction', 'index_capture_text', 'normalize', "
            "'persist_proposals', 'segment', 'validate', 'work_object_extraction')"
        ),
        "capture_processing_state_is_known": (
            "processing_state IN ('complete', 'partial', 'permanent_failure', "
            "'policy_denied', 'retryable_failure', 'running', 'waiting')"
        ),
    },
    "capture_spans": {
        "span_offset_basis_is_known": "offset_basis IN ('unicode_code_point_v1')",
        "span_role_is_known": "span_role IN ('context', 'counterevidence', 'direct')",
    },
    "capture_proposals": {
        "proposal_type_is_known": (
            "proposal_type IN ('commitment', 'decision', 'follow_up', 'issue', "
            "'open_question', 'risk', 'task')"
        ),
        "proposal_state_is_known": (
            "state IN ('accepted', 'corrected_accepted', 'deferred', 'invalidated', "
            "'needs_review', 'proposed', 'rejected', 'superseded', 'unresolved')"
        ),
        "proposal_risk_class_is_known": ("risk_class IN ('critical', 'high', 'low', 'moderate')"),
        "proposal_method_is_known": "method IN ('deterministic_rule')",
        "proposal_quarantine_reason_is_known": (
            "quarantine_reason IS NULL OR quarantine_reason IN "
            "('span_cites_another_version', 'span_outside_version_text', "
            "'span_text_does_not_re_derive')"
        ),
        "a_missing_required_field_is_a_required_field": (
            "missing_required_fields <@ ARRAY['action', 'actor', 'counterparty', "
            "'due_condition', 'status']"
        ),
    },
    "capture_classifications": {
        "capture_label_is_known": (
            "label IN ('commitment_mention', 'date_mention', 'external_reference', "
            "'financial_mention', 'identifier_mention')"
        ),
    },
    "capture_entity_mentions": {
        "mention_entity_type_is_known": "entity_type IN ('document', 'project', 'url')",
        "mention_resolution_state_is_known": "resolution_state IN ('unresolved')",
    },
}

#: The function both constraint triggers run, and the triggers themselves.
_SPAN_CARDINALITY_FUNCTION: Final = "a_proposal_cites_a_span"
_PROPOSAL_TRIGGER: Final = "a_proposal_cites_at_least_one_span"
_LINK_TRIGGER: Final = "a_span_link_leaves_its_proposal_cited"

#: The functional GIN index the exact capture search matches against, and the
#: text-search configuration it is built over. Written out here rather than
#: imported from `persistence.capture_search` for the reason every literal in
#: this file is written out: a revision that read a module constant would emit
#: different DDL the day that constant changed.
_SEARCH_INDEX: Final = "capture_versions_full_text"
_SEARCH_INDEX_EXPRESSION: Final = "to_tsvector('simple', content)"


def _historical_wp7_tables() -> list[Table]:
    """The seven tables as this revision emits them, with the thirteen checks frozen.

    Copies into a throwaway `MetaData` rather than restating the declarations,
    which is the pattern `9c6b4a18ed72` establishes and `1a4c9e77b2d5` repeats,
    and for the reason they give: a duplicated column list here would be a
    second statement of each table and would drift from the first in a way
    nothing checks. All seven are copied into the *same* throwaway metadata, so
    the foreign keys among them — `capture_proposal_spans` to both
    `capture_proposals` and `capture_spans`, and `capture_spans` to
    `capture_processing_text` — resolve inside the copy rather than back at the
    shared declaration.

    **Three tables this revision does not create are copied in first**, and that
    is not an oversight in the list above. Six of the seven reference
    `capture_versions` and one references `capture_jobs`, and
    `Table.to_metadata` resolves a foreign key inside the metadata it is copied
    into: without them, emitting this revision raises `NoReferencedTableError`
    before it reaches a server, which is how it was found — `--sql` offline mode
    failed for every revision in the chain. They are copied so the references
    resolve and are **not** returned, so `create_all` and `drop_all` are still
    handed exactly the seven this revision owns and the guard still reads
    exactly the thirteen closed sets this revision emits. `captures` comes with
    them because `capture_versions` references it.

    The name is in `_EMISSION_CALLABLES` in
    `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`.
    Without that entry the guard's `_emitted` returns `None` for this revision
    and every closed set below is checked by nothing — a silent no-op, which is
    why the entry is part of this change rather than a follow-up.
    """
    frozen = MetaData(schema=SCHEMA)
    for referenced in (captures, capture_versions, capture_jobs):
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


def _restate(capability: str) -> None:
    """Replace `audit_events.capability_is_known` in this revision's transaction.

    Dropped and recreated rather than validated in place: PostgreSQL has no
    "alter the expression of a check constraint", and doing it in two statements
    inside the revision's own transaction means there is no instant at which the
    column is unconstrained that another session could observe. `1a4c9e77b2d5`
    does the same for two constraints; this revision moves one, because it adds
    no purpose.
    """
    name = "capability_is_known"
    op.execute(f'ALTER TABLE {SCHEMA}.audit_events DROP CONSTRAINT "{name}"')
    op.execute(f'ALTER TABLE {SCHEMA}.audit_events ADD CONSTRAINT "{name}" CHECK ({capability})')


def upgrade() -> None:
    _restate(_CAPABILITIES_AT_THIS_REVISION)
    frozen = _historical_wp7_tables()
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
        "  subject := OLD.proposal_id; "
        f"  IF NOT EXISTS (SELECT 1 FROM {SCHEMA}.capture_proposals "
        "                 WHERE proposal_id = subject) THEN RETURN NULL; END IF; "
        "ELSE subject := NEW.proposal_id; END IF; "
        f"IF NOT EXISTS (SELECT 1 FROM {SCHEMA}.capture_proposal_spans "
        "               WHERE proposal_id = subject) THEN "
        "  RAISE EXCEPTION "
        "    'knowledge.capture_proposals carries at least one span; % leaves none', TG_OP "
        "    USING ERRCODE = 'restrict_violation'; "
        "END IF; "
        "RETURN NULL; "
        "END; $$"
    )
    op.execute(
        f"CREATE CONSTRAINT TRIGGER {_PROPOSAL_TRIGGER} "
        f"AFTER INSERT ON {SCHEMA}.capture_proposals "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        f"EXECUTE FUNCTION {SCHEMA}.{_SPAN_CARDINALITY_FUNCTION}()"
    )
    op.execute(
        f"CREATE CONSTRAINT TRIGGER {_LINK_TRIGGER} "
        f"AFTER DELETE ON {SCHEMA}.capture_proposal_spans "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW "
        f"EXECUTE FUNCTION {SCHEMA}.{_SPAN_CARDINALITY_FUNCTION}()"
    )
    op.execute(
        f"CREATE INDEX {_SEARCH_INDEX} ON {SCHEMA}.capture_versions "
        f"USING gin ({_SEARCH_INDEX_EXPRESSION})"
    )


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {SCHEMA}.{_SEARCH_INDEX}")
    # Each trigger goes with its table; the function does not, and
    # `7e5a1fb93d62` drops the schema with RESTRICT, so leaving it behind would
    # fail the downgrade at a revision that has no idea this one existed.
    op.execute(f"DROP TRIGGER IF EXISTS {_LINK_TRIGGER} ON {SCHEMA}.capture_proposal_spans")
    op.execute(f"DROP TRIGGER IF EXISTS {_PROPOSAL_TRIGGER} ON {SCHEMA}.capture_proposals")
    frozen = _historical_wp7_tables()
    frozen[0].metadata.drop_all(op.get_bind(), tables=frozen)
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.{_SPAN_CARDINALITY_FUNCTION}()")
    _restate(_CAPABILITIES_BEFORE_THIS_REVISION)
