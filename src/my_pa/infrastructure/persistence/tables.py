"""The `knowledge` schema: sources, objects, enrollment, jobs, and extraction.

This is the application's own schema and it is deliberately not any of the ones
that already exist. The eight domain schemas hold the migrated legacy corpus and
are read-only history. `migration_control` is a ledger for one migration run:
reusing it would make an enrollment retry indistinguishable from a migration
retry in the same tables, and would put application code on the write path of
migration governance state. Two planes with different lifetimes, different
writers, and different authority do not share a schema.

Eight concerns, ten tables, and nothing else. There is no outbox, no scheduler,
no priority column, and no soft-delete flag: each of those would be a mechanism
with no caller, and `AGENTS.md` section 2 rules them out until one exists.
`audit_events` is not the "audit mirror" an earlier revision of this paragraph
ruled out — a mirror duplicates rows another table already owns, and this is the
only place an audit event is stored at all (`D-34`).

Exactly one column in the schema holds content: `extractions.text`, which is
derived text bound to the version it was extracted from. It is personal data by
default and it is confined to that one place on purpose, so the question "where
could a document body be" has one answer. `quarantine_records` and
`audit_events` in particular have no column a payload could go in, which is the
structural half of the section 12 rule that a quarantine stores identifiers and
codes and not the thing that failed, and of the section 11 rule that an audit
event records that something happened and never what was in it.

`native_root` and `native_locator` are the only provider-native values in the
schema, they exist because an opaque identifier has to resolve back to something,
and no domain type carries either of them. Everything else is an opaque
identifier, an enumerated code, a bounded token, a timestamp, or a count.

The tables are declared once here and used by both the Alembic revisions that
create them and the modules that write to them, so the schema applied and the
schema assumed cannot drift apart. Each revision names the tables it creates
explicitly: this `MetaData` is shared, so a revision that created "everything
declared here" would change meaning every time a table was added to this module.
`tests/schema/test_extraction_schema_migration.py` asserts that correspondence
per revision.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)

from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.audit.events import AuditOutcome
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.provenance import TrustLevel
from my_pa.domain.extraction.coverage import LimitationReason
from my_pa.domain.extraction.quarantine import QuarantineReason, QuarantineReviewState
from my_pa.domain.extraction.text import SUPPORTED_MEDIA_TYPES, ExtractionStatus
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import POLICY_VERSION_PATTERN, DenialReason
from my_pa.domain.source.enrollment import (
    MAX_ENROLLMENT_BYTES,
    MAX_ENROLLMENT_DEPTH,
    MAX_ENROLLMENT_ITEMS,
)
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import SourceProviderKind

SCHEMA: Final = "knowledge"

METADATA: Final = MetaData(schema=SCHEMA)

#: A worker may attempt one job this many times before it is failed terminally.
#: Section 8.6 requires retries to be bounded; this is the bound, and it is the
#: whole of the retry policy. There is no backoff schedule, no dead-letter
#: table, and no per-error classification of what may be retried, because
#: nothing yet needs one.
DEFAULT_MAX_ATTEMPTS: Final = 3

#: Longest a job may be attempted before its lease is considered abandoned.
#: Bounded so a crashed worker cannot hold work forever.
MAX_LEASE_SECONDS: Final = 3600


class JobState(StrEnum):
    """Lifecycle of one unit of application work.

    Four states, because four is what a worker needs to claim work idempotently
    and for a crashed worker's lease to expire. Cancellation is a transport
    concern that section 8.6 describes and nothing here yet implements, so
    `cancel_requested` and `cancelled` are absent rather than declared and
    unreachable.
    """

    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def _literals(values: type[StrEnum] | frozenset[str]) -> str:
    members = values if isinstance(values, frozenset) else [member.value for member in values]
    return ", ".join(f"'{value}'" for value in sorted(members))


def _one_of(
    column: str, values: type[StrEnum] | frozenset[str], *, name: str | None = None
) -> CheckConstraint:
    """Constrain `column` to a closed set, naming the constraint after it.

    `name` overrides the default where two tables constrain a column of the same
    name against different sets; PostgreSQL would accept both, but a reader
    seeing two `reason_is_known` constraints in one schema cannot tell which is
    which.
    """
    return CheckConstraint(f"{column} IN ({_literals(values)})", name=name or f"{column}_is_known")


#: The suffix rule `domain.common.identifiers.validate_identifier` enforces, as a
#: POSIX regular expression the server can check. Restated rather than imported
#: because the domain's own pattern is private to that module; a table that
#: imported it would reach past a deliberate boundary to avoid writing one line.
#: `tests/schema/test_audit_schema_migration.py` compares the two, so the
#: restatement is a checked claim rather than a copy that can drift.
_IDENTIFIER_SUFFIX: Final = "[A-Za-z0-9]{8,64}"


def _is_identifier(column: str, kind: IdKind) -> CheckConstraint:
    """Constrain `column` to the shape of one opaque identifier kind.

    This is the structural half of `INV-PKL-005` for a column with no closed set
    to check against. The alphanumeric suffix admits no `/`, `.`, `:`, `@`, or
    space, so a filesystem path, a host name, a database URL, a credential, and a
    query string are all rejected by the server rather than by a convention the
    writer is trusted to keep.
    """
    return CheckConstraint(
        f"{column} ~ '^{kind.value}_{_IDENTIFIER_SUFFIX}$'",
        name=f"{column}_is_an_opaque_identifier",
    )


def _matches(column: str, pattern: str, *, name: str) -> CheckConstraint:
    """Constrain `column` to a Python pattern, translated to POSIX.

    `\\A` and `\\Z` are Python's absolute anchors and PostgreSQL's are `^` and
    `$`; nothing else in the patterns used here differs between the two dialects.
    Deriving the constraint from the domain's own pattern is what keeps the rule
    the table enforces equal to the rule the value object enforces.
    """
    translated = pattern.replace(r"\A", "^").replace(r"\Z", "$")
    return CheckConstraint(f"{column} ~ '{translated}'", name=name)


#: One row per configured source. `native_root` is the provider's own name for
#: where the source lives — a path today. It is unique per provider so that
#: configuring the same root twice returns the identifier already issued for it
#: instead of minting a second identity for one collection; that lookup is the
#: only reason the column is indexed, and it never leaves this layer.
sources = Table(
    "sources",
    METADATA,
    Column("source_id", Text, primary_key=True),
    Column("provider_kind", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("classification", Text, nullable=False),
    Column("native_root", Text, nullable=False),
    Column("configured_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _one_of("provider_kind", SourceProviderKind),
    _one_of("classification", Classification),
    UniqueConstraint("provider_kind", "native_root", name="sources_native_root_is_configured_once"),
)

#: One row per logical object ever observed. The unique constraint on
#: `(source_id, native_locator)` is what makes `obj_…` stable across
#: observations without the identifier being a function of the locator: identity
#: is issued once and then looked up, never recomputed.
source_objects = Table(
    "source_objects",
    METADATA,
    Column("source_object_id", Text, primary_key=True),
    Column(
        "source_id",
        Text,
        ForeignKey(f"{SCHEMA}.sources.source_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("kind", Text, nullable=False),
    Column("native_locator", Text, nullable=False),
    Column("first_observed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _one_of("kind", ObjectKind),
    UniqueConstraint("source_id", "native_locator", name="source_objects_locator_is_issued_once"),
)

#: One row per distinct observed state of an object. `fingerprint` is whatever
#: the provider can prove the bytes by; the unique constraint means re-observing
#: unchanged bytes reuses the existing `ver_…` rather than issuing a new one, so
#: a version identifier binds an observation the way section 9.4 requires.
source_object_versions = Table(
    "source_object_versions",
    METADATA,
    Column("version_id", Text, primary_key=True),
    Column(
        "source_object_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_objects.source_object_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("fingerprint", Text, nullable=False),
    Column("media_type", Text),
    Column("size_bytes", BigInteger),
    Column("modified_at", DateTime(timezone=True), nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="size_bytes_is_not_negative"),
    UniqueConstraint(
        "source_object_id", "fingerprint", name="source_object_versions_are_one_per_fingerprint"
    ),
)

#: One row per accepted enrollment.
#:
#: `enrollments_idempotency_key_is_scoped` is the structural half of section
#: 8.6. It permits exactly one row per (principal, purpose, source, policy
#: version, key), so a second request carrying a key that is already in use
#: cannot insert; the writer then compares `request_fingerprint` and answers
#: with the existing enrollment or with `conflict`. Enforcing that in Python
#: alone would leave two concurrent requests able to both read "absent" and both
#: insert.
#:
#: The check constraints restate the bounds `domain.source.enrollment` enforces
#: on construction. They are not redundant: the domain type governs this
#: process, and the constraint governs the table, including against a future
#: writer or a hand-run statement.
enrollments = Table(
    "enrollments",
    METADATA,
    Column("enrollment_id", Text, primary_key=True),
    Column(
        "source_id",
        Text,
        ForeignKey(f"{SCHEMA}.sources.source_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("principal_id", Text, nullable=False),
    Column("purpose", Text, nullable=False),
    Column("policy_version", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("request_fingerprint", Text, nullable=False),
    # `root_object_id` deliberately carries no foreign key, and the reason is
    # structural rather than a judgement about the value. `enrollments` is
    # created by revision `7e5a1fb93d62` through `METADATA.create_all`, and this
    # `MetaData` is shared at import time, so declaring a `ForeignKey` here
    # retroactively changes the DDL that already-merged revision emits: a
    # base-to-head replay would produce a constraint the revision never
    # described, and at head the same reference would exist twice. A revision
    # whose meaning changes when a later one is written is not a chain. The
    # guarantee this would have bought — an enrollment naming a root nothing
    # observed — is held instead by enumeration: `record_scope` refuses an
    # object its enrollment's source never observed and refuses an empty set,
    # and both refusals roll the accepting transaction back. Do not add it.
    Column("root_object_id", Text),
    Column("object_ids", ARRAY(Text), nullable=False, server_default="{}"),
    Column("depth", Integer, nullable=False, server_default="0"),
    Column("media_types", ARRAY(Text), nullable=False),
    Column("max_items", Integer, nullable=False),
    Column("max_bytes", BigInteger, nullable=False),
    Column("accepted_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    CheckConstraint(
        "(root_object_id IS NOT NULL) <> (cardinality(object_ids) > 0)",
        name="enrollment_names_exactly_one_selector",
    ),
    CheckConstraint(
        f"depth BETWEEN 0 AND {MAX_ENROLLMENT_DEPTH}",
        name="enrollment_depth_is_bounded",
    ),
    CheckConstraint(
        "root_object_id IS NOT NULL OR depth = 0",
        name="an_object_list_has_no_depth",
    ),
    CheckConstraint(
        f"max_items BETWEEN 1 AND {MAX_ENROLLMENT_ITEMS}",
        name="enrollment_items_are_bounded",
    ),
    # An enrollment that names more objects than it permits has written two
    # bounds that contradict; neither the scope nor the ceiling can see the
    # other on its own, so the relation between them is stated here as well as
    # in the request type.
    CheckConstraint(
        "cardinality(object_ids) <= max_items",
        name="enrollment_names_no_more_objects_than_it_allows",
    ),
    CheckConstraint(
        f"max_bytes BETWEEN 1 AND {MAX_ENROLLMENT_BYTES}",
        name="enrollment_bytes_are_bounded",
    ),
    CheckConstraint("cardinality(media_types) > 0", name="enrollment_allows_some_content_type"),
    UniqueConstraint(
        "principal_id",
        "purpose",
        "source_id",
        "policy_version",
        "idempotency_key",
        name="enrollments_idempotency_key_is_scoped",
    ),
)

#: The enumerated object set one enrollment authorizes: which objects, measured
#: once, at acceptance.
#:
#: This is the fact `persistence.extraction.authorized_object` and
#: `persistence.search` both record as missing and both carry to WP-4. With it,
#: membership applies to a root selector exactly as it applies to a named one,
#: and `count(*)` here is the eligible total nothing measured. Fixing either
#: alone would have meant building this twice.
#:
#: Both columns carry a foreign key, which is the whole point of the table:
#: `enrollments.object_ids` is an `ARRAY(Text)` and PostgreSQL has no
#: element-level reference, so a caller-supplied identifier that named no row
#: was storable and silently authorized nothing. Those two keys are declarable
#: because they are on a new table this revision creates; the same reference on
#: `enrollments.root_object_id` is not, for the reason stated at that column.
#: A root that names no observed object is refused by `record_scope` rather than
#: by a constraint — enumeration finds nothing for it, and an empty set is
#: refused — so the guarantee is held, just not here.
#:
#: The composite primary key is the idempotency mechanism rather than a
#: convenience: `record_scope` inserts under `ON CONFLICT DO NOTHING` against
#: this exact constraint, so re-running an enumeration adds no row.
#:
#: There is no `native_locator`, no ordering column, and no per-object state.
#: Where an object got to is `extractions` and `quarantine_records`; adding a
#: status column here would give the same fact two writers.
enrollment_objects = Table(
    "enrollment_objects",
    METADATA,
    Column(
        "enrollment_id",
        Text,
        ForeignKey(f"{SCHEMA}.enrollments.enrollment_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "source_object_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_objects.source_object_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("enumerated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint(
        "enrollment_id", "source_object_id", name="an_enrollment_holds_an_object_once"
    ),
)

#: One row per unit of work an enrollment authorizes.
#:
#: The lease is two columns and a rule: a job is `running` exactly while an
#: owner holds it, and the owner's claim is only good until `lease_expires_at`.
#: A crashed worker therefore releases its work by doing nothing, which is the
#: only recovery path that survives the worker being gone. `attempt_count` is
#: incremented by the claim itself rather than by the worker, so a worker that
#: dies before reporting anything still consumed an attempt and the bound still
#: converges.
#:
#: `last_error_code` is one of the eleven public error codes and is constrained
#: to be. A free-text column here would be exactly the payload channel section
#: 13 forbids: a driver's message can quote the value it rejected.
jobs = Table(
    "jobs",
    METADATA,
    Column("operation_id", Text, primary_key=True),
    Column(
        "enrollment_id",
        Text,
        ForeignKey(f"{SCHEMA}.enrollments.enrollment_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("state", Text, nullable=False, server_default=JobState.QUEUED.value),
    Column("attempt_count", Integer, nullable=False, server_default="0"),
    Column("max_attempts", Integer, nullable=False, server_default=str(DEFAULT_MAX_ATTEMPTS)),
    Column("lease_owner", Text),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("last_error_code", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _one_of("state", JobState),
    CheckConstraint(
        "last_error_code IS NULL OR last_error_code IN ("
        + ", ".join(f"'{code.value}'" for code in ErrorCode)
        + ")",
        name="last_error_code_is_a_public_error_code",
    ),
    CheckConstraint(
        "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
        name="a_lease_has_an_owner_and_an_expiry",
    ),
    CheckConstraint(
        f"(state = '{JobState.RUNNING.value}') = (lease_owner IS NOT NULL)",
        name="a_job_is_running_exactly_while_leased",
    ),
    CheckConstraint(
        f"attempt_count >= 0 AND max_attempts BETWEEN 1 AND {DEFAULT_MAX_ATTEMPTS * 10} "
        "AND attempt_count <= max_attempts",
        name="attempts_are_bounded",
    ),
    Index("jobs_by_state", "state", "created_at"),
)

#: One row per object that reached an extraction outcome, under one enrollment.
#:
#: A quarantined object is *not* a row here. It is a row in `quarantine_records`,
#: because the two carry different facts and because one of them must never
#: carry text: a single table with a nullable `text` column would put the
#: quarantine path one forgotten `WHERE` clause away from storing the payload
#: that caused it.
#:
#: `status` is what makes `unsupported` explicit rather than absent. Section 12
#: requires unsupported media to be reported and never silently skipped, and a
#: skipped object leaves no row at all, so the difference between "we looked and
#: it is a PDF" and "we never looked" has to be a stored value. `text IS NULL`
#: for such a row, and the check constraint ties the two together so neither can
#: be written without the other.
#:
#: `media_type` is nullable because "not identified" is a real answer for an
#: object whose type the provider could not name, and it is not the same answer
#: as `text/plain`. An extracted row must name a supported type: the constraint
#: is what stops a future writer from filing a PDF's bytes as text while
#: `P00-OD-003` is open.
#:
#: `trust_level` is a column with one permitted value. That is deliberate rather
#: than redundant: `INV-PKL-003` says derived text never carries source
#: authority, and a column that can only be `source_bound_derived` means no
#: writer, hand-run statement, or later revision can file derived text as
#: original.
extractions = Table(
    "extractions",
    METADATA,
    Column("extraction_id", Text, primary_key=True),
    Column(
        "enrollment_id",
        Text,
        ForeignKey(f"{SCHEMA}.enrollments.enrollment_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "source_object_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_objects.source_object_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_object_versions.version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("status", Text, nullable=False),
    Column("media_type", Text),
    Column("extractor", Text, nullable=False),
    Column("extractor_version", Text, nullable=False),
    Column(
        "trust_level", Text, nullable=False, server_default=TrustLevel.SOURCE_BOUND_DERIVED.value
    ),
    Column("text", Text),
    Column("is_truncated", Boolean, nullable=False, server_default="false"),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("processed_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _one_of("status", ExtractionStatus, name="extraction_status_is_known"),
    CheckConstraint(
        f"trust_level = '{TrustLevel.SOURCE_BOUND_DERIVED.value}'",
        name="derived_text_is_never_source_original",
    ),
    CheckConstraint(
        f"(status = '{ExtractionStatus.EXTRACTED.value}') = (text IS NOT NULL)",
        name="text_exists_exactly_when_something_was_extracted",
    ),
    CheckConstraint(
        f"status <> '{ExtractionStatus.EXTRACTED.value}' "
        f"OR media_type IN ({_literals(SUPPORTED_MEDIA_TYPES)})",
        name="only_a_supported_media_type_is_extracted",
    ),
    CheckConstraint("processed_at >= observed_at", name="extraction_follows_its_observation"),
    # One outcome per observed version per enrollment. Re-running extraction over
    # an unchanged object is a retry and must not accumulate rows; a changed
    # object has a new `ver_…` and therefore a new row, which is what keeps the
    # text attributable to the bytes it came from.
    UniqueConstraint(
        "enrollment_id", "version_id", name="one_extraction_per_version_per_enrollment"
    ),
    Index("extractions_by_enrollment", "enrollment_id", "status"),
    # A functional GIN index over the same expression the search predicate uses.
    # There is no stored `tsvector` column and no trigger to maintain one, so the
    # expression here and the one in `persistence.search` must stay equal *as
    # expressions*: PostgreSQL matches a functional index by the expression tree,
    # not by the text, so the two need not read the same and in fact do not — the
    # index is written over `text` and the predicate compiles to
    # `to_tsvector('english', knowledge.extractions.text)`, which is a different
    # string for the same tree and matches. What breaks the match is anything
    # that changes the tree, such as a different text-search configuration, and
    # it breaks silently: the query drops back to a sequential scan that still
    # returns correct rows.
    # `test_the_search_predicate_uses_the_functional_index_and_not_a_sequential_scan`
    # proves the plan, not just the result.
    Index(
        "extractions_full_text",
        text("to_tsvector('english', text)"),
        postgresql_using="gin",
    ),
)

#: One row per object whose processing was stopped, and why.
#:
#: Append-only. Section 12 requires reprocessing to be "explicit bounded recovery
#: and new operation/audit", so a second quarantine of the same object is a
#: second event rather than an update of the first, and there is no unique
#: constraint pretending otherwise.
#:
#: There is no column here that a payload fits in: identifiers, two enumerated
#: codes, and a timestamp. That is the point of the table's shape, not an
#: accident of its current fields.
#:
#: `version_id` is nullable because a containment failure can occur before any
#: version was observed. Recording a version that was never proven would
#: attribute the quarantine to bytes nobody saw.
quarantine_records = Table(
    "quarantine_records",
    METADATA,
    Column("quarantine_id", Text, primary_key=True),
    Column(
        "enrollment_id",
        Text,
        ForeignKey(f"{SCHEMA}.enrollments.enrollment_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "source_object_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_objects.source_object_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_object_versions.version_id", ondelete="CASCADE"),
    ),
    Column("reason", Text, nullable=False),
    Column(
        "review_state",
        Text,
        nullable=False,
        server_default=QuarantineReviewState.PENDING_REVIEW.value,
    ),
    Column("quarantined_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _one_of("reason", QuarantineReason, name="quarantine_reason_is_known"),
    _one_of("review_state", QuarantineReviewState, name="quarantine_review_state_is_known"),
    Index("quarantine_records_by_enrollment", "enrollment_id"),
)

#: One row per (enrollment, snapshot, reason): how many objects a result does not
#: account for, and why, with nothing that says which.
#:
#: This is the plumbing `docs/plans/mcv-completion-plan.md` section 10 says is
#: missing. An object the provider refuses is omitted from a listing with no
#: signal, which converts present evidence into "not there"; section 9.2 permits
#: "safe aggregate limitations may be disclosed" and this is where the layer
#: above the provider puts one.
#:
#: The table has no `source_object_id` column and no locator column, and it never
#: will have one — with either, the aggregate would become a per-object existence
#: disclosure, which is the side channel section 9.2 forbids in the same
#: sentence that permits the aggregate. `affected_count` is the entire detail.
#:
#: The unique key includes `observed_at` because coverage is stated for a
#: snapshot. One listing pass uses one snapshot timestamp for all of its pages,
#: so the count accumulates across pages of that pass and a later pass records
#: its own row rather than editing history.
coverage_limitations = Table(
    "coverage_limitations",
    METADATA,
    Column("limitation_id", Text, primary_key=True),
    Column(
        "enrollment_id",
        Text,
        ForeignKey(f"{SCHEMA}.enrollments.enrollment_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    Column("reason", Text, nullable=False),
    Column("affected_count", Integer, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _one_of("reason", LimitationReason, name="limitation_reason_is_known"),
    CheckConstraint("affected_count >= 1", name="a_limitation_affects_at_least_one_object"),
    UniqueConstraint(
        "enrollment_id",
        "observed_at",
        "reason",
        name="one_limitation_per_reason_per_snapshot",
    ),
)

#: One row per audit event: that something was decided, and how. Never what was
#: in it.
#:
#: **Every column is closed.** Three are opaque identifiers constrained to their
#: own shape, four are constrained to a closed enumerated set, three are bounded
#: counts, one is a timestamp, and one is a version string constrained to the
#: domain's own pattern. There is no `Text` column here that accepts arbitrary
#: text, which is the structural form of the section 11 rule: a document body, a
#: query, a path, a host, a credential, or a personal identifier cannot be stored
#: in any of these columns, because the server rejects the value rather than
#: because a writer remembered not to supply one. `AuditEvent` has no field to
#: carry one either, so the guarantee holds on both sides of the boundary.
#:
#: **There is no foreign key, and that is the point rather than an omission.**
#: This table is written in its own transaction, which commits *before* the work
#: the event describes (`D-34`, and see `persistence.audit`). A foreign key to
#: `enrollments` or `jobs` would make the audit's durability depend on the
#: durability of the work — exactly the coupling that produced the asymmetry
#: WP-4B1 exists to close, since a row referencing work that then rolled back
#: could not have been written at all.
#:
#: **Append-only, and no retention mechanism.** Nothing here updates or deletes a
#: row and no revision provides a way to. `P00-OD-013` (audit retention) is open
#: and `O-10`/`RI-OD-009` cover deletion; building a retention or archival path
#: before the operator has decided one would be this layer deciding how long
#: evidence lives.
audit_events = Table(
    "audit_events",
    METADATA,
    Column("audit_id", Text, primary_key=True),
    Column("correlation_id", Text, nullable=False),
    Column("principal_id", Text, nullable=False),
    Column("capability", Text, nullable=False),
    Column("purpose", Text, nullable=False),
    Column("outcome", Text, nullable=False),
    Column("policy_version", Text, nullable=False),
    Column("denial_reason", Text),
    # The only count with a writer. `AuditEvent` also carries `item_count` and
    # `duration_ms`, and neither is ever set: `authorize` passes this one alone
    # and the mismatch branch passes none. Columns for them would be permanently
    # zero, which `AGENTS.md` section 2 rules out — and a zero that means "never
    # measured" reads as "nothing happened", which is worse than absent. They
    # belong here when something computes them.
    Column("scope_source_id_count", Integer, nullable=False, server_default="0"),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    _is_identifier("audit_id", IdKind.AUDIT),
    _is_identifier("correlation_id", IdKind.CORRELATION),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    _one_of("capability", Capability),
    _one_of("purpose", Purpose),
    _one_of("outcome", AuditOutcome, name="audit_outcome_is_known"),
    _one_of("denial_reason", DenialReason, name="denial_reason_is_known"),
    _matches(
        "policy_version",
        POLICY_VERSION_PATTERN.pattern,
        name="audit_policy_version_is_a_known_shape",
    ),
    # The same rule `AuditEvent.__post_init__` enforces, stated where a future
    # writer or a hand-run statement also meets it. A denial with no reason
    # records that authority was insufficient without recording why, and a
    # non-denial with one attributes a refusal to a request that was not refused.
    CheckConstraint(
        f"(outcome = '{AuditOutcome.DENIED.value}') = (denial_reason IS NOT NULL)",
        name="a_denial_records_its_reason_and_nothing_else_does",
    ),
    CheckConstraint("scope_source_id_count >= 0", name="audit_counts_are_not_negative"),
    # The one lookup this build can already perform: a response envelope hands
    # its caller a `corr_…`, so that is how an operator finds the decision behind
    # a request. No index by principal or by time, because nothing reads by
    # either yet.
    Index("audit_events_by_correlation", "correlation_id"),
)
