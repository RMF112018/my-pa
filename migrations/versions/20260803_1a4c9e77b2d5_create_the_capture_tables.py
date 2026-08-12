"""create the capture tables

Adds five tables to the existing `knowledge` schema — `captures`,
`capture_versions`, `capture_submissions`, `capture_receipts`, and
`capture_jobs` — widens the two closed-set constraints on `audit_events` to the
capture vocabulary, and installs the trigger that makes a stored capture version
immutable. It creates no schema and reads nothing from the migrated legacy
corpus.

The tables are named explicitly rather than taken from the shared `MetaData`,
for the reason `8b3f5c17d904` states: `my_pa.infrastructure.persistence.tables`
declares every table in this schema in one module, so an unqualified
`create_all` here would also create the ten that earlier revisions own — and
would then start creating whatever a later revision declares, which would make
this file's meaning depend on code written after it.
`tests/schema/test_extraction_schema_migration.py` asserts that each revision
emits exactly the tables it names.

**Why this revision alters two constraints an earlier revision created.**
`audit_events.capability` and `audit_events.purpose` are closed to the
vocabulary that existed when `9c6b4a18ed72` merged, and this package adds four
capabilities and two purposes. Widening them by editing the declaration would
change what that already-merged revision emits — the `D-48` hazard, measured and
proved in that file's own docstring — so the widening is an explicit forward
`ALTER` here instead. **The literals below are frozen**, per the standing rule
`9c6b4a18ed72` states: no Alembic revision may derive a closed-set constraint
from a domain enum. When a later package adds a capability it writes another
`ALTER`, and this file goes on denoting the vocabulary of the day it merged.

**And the same freeze applies to the eight closed-set constraints on this
revision's own five tables**, which is not where the first pass left it. Those
eight were taken straight off the shared declaration, so `ProcessingPolicy`
gaining a member, or `Classification`, or `JobState`, or the public error-code
set, would have changed what *this* revision emits the moment it was merged —
the identical defect, written into the file that restates the rule against it,
by the package that wrote the rule. Nothing has widened them yet, so nothing was
broken; a rule obeyed only where it had already been violated is not a rule.
`transport`, `capture_method`, `trust_state` and `admission_result` each admit
exactly one value today (`D-78`), and a later transport widens them by a forward
`ALTER` in its own revision rather than by editing this one.

That deliberately breaks the coupling that used to guarantee the domain and the
database could not drift, so it is replaced by two checked claims rather than
left unstated. `tests/schema/test_capture_schema_migration.py` asserts against a
live server that head admits exactly the domain's declaration for every one of
these constraints — `Capability`, `Purpose`, `AuditOutcome`, `DenialReason` on
`audit_events`, and the eight on the capture tables — so a member added without
an `ALTER` reddens. `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`
enforces the standing rule itself across every revision in the chain, with the
still-derived sites in the three revisions this package does not edit carried as
an explicit allowlist that must shrink. The precedent for a restatement made
checkable rather than a copy that can drift is `tables.py:_IDENTIFIER_SUFFIX`.

**Why there is a trigger, which no other revision in this schema has.**
`QC-AC-010` requires original text to be immutable by version and asks for the
constraint to hold under concurrent write. No CHECK can express "no UPDATE": a
CHECK is evaluated against the row that results, and an update to a row that
still satisfies every column rule is exactly the write that must be refused. A
`BEFORE UPDATE OR DELETE` trigger is the only server-side mechanism that
expresses it, and expressing it in the server rather than in the writer is the
whole point — the alternative is immutability as a property of the code that
happens to be running, which a repair script, a later revision, or a second
writer does not inherit. The exception it raises names the operation and never a
value, so the refusal discloses nothing about the row it refused.

The downgrade drops the five tables, drops the trigger function — `RESTRICT`, not
`CASCADE`, is what `7e5a1fb93d62` uses to drop the schema, so a function left
behind here would make `downgrade base` fail — and narrows both constraints back
to the frozen historical vocabulary, so that a database downgraded past this
revision is in the state the revision below it describes rather than in a state
no revision describes.

Revision ID: 1a4c9e77b2d5
Revises: af3d35efb9c0
Created: 2026-08-03 09:40:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from alembic import op
from sqlalchemy import CheckConstraint, MetaData, Table

from my_pa.infrastructure.persistence.tables import (
    SCHEMA,
    capture_jobs,
    capture_receipts,
    capture_submissions,
    capture_versions,
    captures,
)

revision: str = "1a4c9e77b2d5"
down_revision: str | None = "af3d35efb9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: Exactly the five tables this revision's docstring documents.
_TABLES: list[Table] = [
    captures,
    capture_versions,
    capture_receipts,
    capture_submissions,
    capture_jobs,
]

#: The audit vocabulary as of this revision, written out. Frozen, per the
#: standing rule in `9c6b4a18ed72`: a later package that adds a capability adds
#: another `ALTER` rather than editing this list, so this revision goes on
#: denoting one schema. Sorted, which is the order the declarative helper
#: produces, so the two texts can be compared directly.
_CAPABILITIES_AT_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'capture.create', 'capture.list', "
    "'capture.read', 'capture.revise', 'knowledge.read', 'knowledge.search', "
    "'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status')"
)
_PURPOSES_AT_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'capture_authoring', 'capture_review', "
    "'content_extraction', 'knowledge_read', 'knowledge_search', "
    "'security_validation', 'source_inspection', 'status_observation')"
)

#: What the revision below emits, restated here because a downgrade has to put
#: the constraint back to the vocabulary that revision denotes rather than to
#: whatever the domain says today.
_CAPABILITIES_BEFORE_THIS_REVISION: Final = (
    "capability IN ('capabilities.get', 'knowledge.read', 'knowledge.search', "
    "'sources.enroll', 'sources.fetch', 'sources.list', 'sources.metadata', "
    "'sources.status')"
)
_PURPOSES_BEFORE_THIS_REVISION: Final = (
    "purpose IN ('bounded_enrollment', 'content_extraction', 'knowledge_read', "
    "'knowledge_search', 'security_validation', 'source_inspection', "
    "'status_observation')"
)

#: Every closed-set constraint on this revision's own five tables, written out.
#: Same mechanism and same reason as the four in `9c6b4a18ed72`: taken off the
#: live declaration these would change what this revision emits the first time a
#: later package adds a member to `Classification`, `ProcessingPolicy`,
#: `CaptureTransport`, `CaptureMethod`, `TrustState`, `AdmissionResult`,
#: `JobState`, or the public error-code set. The texts are the declarative
#: helper's own output — sorted for the enums, declaration order for the error
#: codes — so what is emitted is identical to the derived text, not merely
#: equivalent.
_FROZEN: Final[dict[str, dict[str, str]]] = {
    "capture_versions": {
        "capture_classification_is_known": (
            "classification IN ('private_local', 'restricted_local', 'synthetic_test')"
        ),
        "processing_policy_is_known": "processing_policy IN ('local_only')",
    },
    "capture_submissions": {
        "capture_transport_is_known": "transport IN ('local')",
        "capture_method_is_known": "capture_method IN ('typed_text')",
        "capture_trust_state_is_known": "trust_state IN ('local_principal')",
        "admission_result_is_known": "admission_result IN ('accepted')",
    },
    "capture_jobs": {
        "capture_job_state_is_known": "state IN ('failed', 'queued', 'running', 'succeeded')",
        "capture_job_error_code_is_a_public_error_code": (
            "last_error_code IS NULL OR last_error_code IN ('invalid_request', "
            "'ambiguous_request', 'denied', 'unavailable', 'unsupported', 'not_found', "
            "'conflict', 'rate_limited', 'quarantined', 'cancelled', 'internal_error')"
        ),
    },
}

#: The function and the trigger that make `capture_versions` append only.
_IMMUTABILITY_FUNCTION: Final = "capture_versions_stay_as_written"
_IMMUTABILITY_TRIGGER: Final = "capture_versions_are_append_only"


#: WP-04's queue partition, frozen out of this revision.
#:
#: `4f1a8b6d92e3` adds `principal_id`, its `principal_id_is_an_opaque_identifier`
#: CHECK, and a principal-first claim-order index to "capture_jobs". This
#: revision copies the *live* declaration, so without the subtraction below it
#: would emit those too — retroactively changing what an already-merged revision
#: means, which is the `D-48` hazard, and making a base-to-head replay fail on a
#: duplicate column the moment `4f1a8b6d92e3` runs. Same discipline as
#: `3c8f1e2a5b74`'s `_freeze_out_wp05_principal`: a local subtraction on a
#: throwaway copy, never on the shared declaration, which still carries the
#: column the application reads and writes.
_WP04_QUEUE_PRINCIPAL_TABLES: Final = frozenset({"capture_jobs"})
_WP04_PRINCIPAL_CHECK: Final = "principal_id_is_an_opaque_identifier"
_WP04_PRINCIPAL_INDEXES: Final = frozenset({"capture_jobs_by_principal_claim_order"})


def _freeze_out_wp04_queue_principal(copy: Table) -> None:
    """Remove `4f1a8b6d92e3`'s queue partition from one copied table in place."""
    if copy.name not in _WP04_QUEUE_PRINCIPAL_TABLES:
        return
    for index in [
        candidate for candidate in copy.indexes if candidate.name in _WP04_PRINCIPAL_INDEXES
    ]:
        copy.indexes.discard(index)
    for constraint in [
        candidate for candidate in copy.constraints if candidate.name == _WP04_PRINCIPAL_CHECK
    ]:
        copy.constraints.discard(constraint)
    # `Table` exposes no public column removal; `_columns.remove` is how a copied
    # column is dropped from a throwaway metadata. Neither queue's
    # `principal_id` carries a foreign key or takes part in a primary key, so the
    # copy is otherwise intact.
    copy._columns.remove(copy.c.principal_id)


def _historical_capture_tables() -> list[Table]:
    """The five tables as this revision emits them, with the eight checks frozen.

    Copies into a throwaway `MetaData` rather than restating the declarations,
    which is the pattern `9c6b4a18ed72` establishes and for the reason it gives:
    a duplicated column list here would be a second statement of each table and
    would drift from the first in a way nothing checks. All five are copied into
    the *same* throwaway metadata, so the foreign keys among them — including
    `capture_versions.supersedes`, which points at its own table — resolve inside
    the copy rather than back at the shared declaration.
    """
    frozen = MetaData(schema=SCHEMA)
    copies = [table.to_metadata(frozen) for table in _TABLES]
    for copy in copies:
        _freeze_out_wp04_queue_principal(copy)
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
    inside the revision's own transaction means there is no instant at which the
    column is unconstrained that another session could observe.
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
    frozen = _historical_capture_tables()
    frozen[0].metadata.create_all(op.get_bind(), tables=frozen)
    op.execute(
        f"CREATE FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN "
        "RAISE EXCEPTION 'knowledge.capture_versions is append only; % is refused', TG_OP "
        "USING ERRCODE = 'restrict_violation'; "
        "END; $$"
    )
    op.execute(
        f"CREATE TRIGGER {_IMMUTABILITY_TRIGGER} "
        f"BEFORE UPDATE OR DELETE ON {SCHEMA}.capture_versions "
        f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.{_IMMUTABILITY_FUNCTION}()"
    )


def downgrade() -> None:
    # The trigger goes with its table; the function does not, and `7e5a1fb93d62`
    # drops the schema with RESTRICT, so leaving it behind would fail the
    # downgrade at a revision that has no idea this one existed.
    op.execute(f"DROP TRIGGER IF EXISTS {_IMMUTABILITY_TRIGGER} ON {SCHEMA}.capture_versions")
    frozen = _historical_capture_tables()
    frozen[0].metadata.drop_all(op.get_bind(), tables=frozen)
    op.execute(f"DROP FUNCTION IF EXISTS {SCHEMA}.{_IMMUTABILITY_FUNCTION}()")
    _restate(_CAPABILITIES_BEFORE_THIS_REVISION, _PURPOSES_BEFORE_THIS_REVISION)
