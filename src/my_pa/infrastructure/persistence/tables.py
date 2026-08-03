"""The `knowledge` schema: sources, objects, enrollment, jobs, and extraction.

This is the application's own schema and it is deliberately not any of the ones
that already exist. The eight domain schemas hold the migrated legacy corpus and
are read-only history. `migration_control` is a ledger for one migration run:
reusing it would make an enrollment retry indistinguishable from a migration
retry in the same tables, and would put application code on the write path of
migration governance state. Two planes with different lifetimes, different
writers, and different authority do not share a schema.

Ten concerns, twenty-two tables, and nothing else. There is no scheduler, no
priority column, and no soft-delete flag: each of those would be a mechanism with
no caller, and `AGENTS.md` section 2 rules them out until one exists.
`audit_events` is not the "audit mirror" an earlier revision of this paragraph
ruled out — a mirror duplicates rows another table already owns, and this is the
only place an audit event is stored at all (`D-34`).

**Three columns in the schema hold content, and they are three different
authorities.** `extractions.text` is derived text bound to the source version it
was extracted from. `capture_versions.content` is the text the user typed, which
`ADR-003` makes a product-owned record rather than a source read — a third
authority class, not a source-system write and not a managed-document write.
`capture_processing_text.normalized_text` is `P-02`'s conservative rewrite of
that text for processing only; it is bound to the version it was derived from
and to the mapping that carries its offsets back, and it never replaces the
original. They are confined to those three places on purpose, so the question
"where could a document body be" has an enumerable answer — and that is why
`capture_spans` stores a digest of the quoted text and not the quote, and why
`capture_stage_results` stores a digest of a stage's output and not the output.
`quarantine_records`,
`audit_events`, `capture_submissions`, and `capture_receipts` in particular have
no column a payload could go in, which is the structural half of the section 12
rule that a quarantine stores identifiers and codes and not the thing that
failed, of the section 11 rule that an audit event records that something
happened and never what was in it, and of `QC-AC-041`, which requires that no
capture text appear in an event payload or a receipt.

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
from my_pa.domain.capture.classification import (
    MAX_SCHEME_CHARACTERS,
    CaptureLabel,
    EntityType,
    ResolutionState,
)
from my_pa.domain.capture.pipeline import (
    MAX_PIPELINE_VERSION_CHARACTERS,
    PipelineStage,
    ProcessingState,
)
from my_pa.domain.capture.proposal import (
    MAX_NORMALIZED_VALUE_CHARACTERS,
    MAX_PROPOSAL_VERSION_CHARACTERS,
    ProposalField,
    ProposalMethod,
    ProposalQuarantineReason,
    ProposalState,
    ProposalType,
    RiskClass,
)
from my_pa.domain.capture.span import (
    MAX_MAPPING_VERSION_CHARACTERS,
    OffsetBasis,
    SpanRole,
)
from my_pa.domain.capture.submission import (
    MAX_IDEMPOTENCY_KEY_CHARACTERS,
    MAX_REQUEST_ID_CHARACTERS,
    AdmissionResult,
    CaptureMethod,
    CaptureTransport,
    TrustState,
)
from my_pa.domain.capture.version import (
    DIGEST_PATTERN,
    MAX_CAPTURE_CHARACTERS,
    ProcessingPolicy,
)
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


def _each_one_of(
    column: str, values: type[StrEnum] | frozenset[str], *, name: str
) -> CheckConstraint:
    """Constrain every element of an array `column` to a closed set.

    `IN` cannot express containment of an array, so this is the array form of
    `_one_of` and it is written as `<@ ARRAY[…]`.
    `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`
    reads both shapes, which is why this one may exist at all: a closed set a
    revision emits that the guard could not parse would be a derived site nobody
    could see, and that guard's whole subject is derived sites nobody can see.
    """
    return CheckConstraint(f"{column} <@ ARRAY[{_literals(values)}]", name=name)


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

#: One row per user-authored record: its identity, its owner, and when it began.
#:
#: **There is no `current_version_id` and no lifecycle-state column, and their
#: absence is the design rather than an omission.** Either would have to be
#: written by a revise, which would put an `UPDATE` on the identity row of a
#: chain whose whole guarantee is that it has no mutation path. The current
#: version is `max(version_number)` over `capture_versions` for this capture — a
#: read of the rows themselves, which cannot disagree with them. Withdrawal and
#: archive (`ADR-003` clause 3) are out of scope for this package and are absent
#: rather than declared and unreachable.
#:
#: `owner_principal_id` is stored because `ADR-003` clause 6 requires every
#: stored record to bind its owning principal. It is deliberately *not* an
#: authorization input: see `capture_versions`.
captures = Table(
    "captures",
    METADATA,
    Column("capture_id", Text, primary_key=True),
    Column("owner_principal_id", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _is_identifier("capture_id", IdKind.CAPTURE),
    _is_identifier("owner_principal_id", IdKind.PRINCIPAL),
)

#: One row per immutable version of one capture. Insert only, enforced by the
#: server: revision `1a4c9e77b2d5` adds a `BEFORE UPDATE OR DELETE` trigger,
#: because no CHECK can express "no UPDATE" and `QC-AC-010` asks for the
#: constraint to hold under concurrent write. That is the difference between
#: immutability as a property of the schema and immutability as a property of
#: the current writer — the same argument
#: `tests/schema/test_audit_schema_migration.py` already makes for redaction.
#:
#: **`supersedes_version_id` is `UNIQUE`, and that is what makes the chain
#: unforkable.** Without it two versions could name the same predecessor, and
#: "the successor of v2" would have two answers with nothing to choose between
#: them. With it, a chain is a line.
#:
#: **Five timestamps, none defaulting from another.**
#: `docs/specs/quick-capture/20_TESTING_EVALUATION_AND_ACCEPTANCE.md:191` requires
#: device, server, occurred, processed, and accepted times to remain distinct.
#: `client_created_at` and `occurred_at` are nullable because a transport may
#: supply no device clock and a note may be about no particular moment; a null
#: here is honest absence, and deriving one of them from `server_received_at`
#: would invent a fact about the world out of a fact about this process.
#:
#: **`audit_id` is a reference and not a foreign key.** The audit event it names
#: has already committed, on its own connection, before the transaction holding
#: this row (`D-34`). A reference constraint would make the audit's durability
#: depend on the durability of the work it exists to outlive, which is the same
#: reason `audit_events` itself declares none.
#:
#: **`owner_principal_id` is recorded and never authorized on** (`D-72`).
#: Identity in this build is process-scoped — a restart mints a new principal —
#: so requiring owner equality on read or revise would make `QC-AC-013`
#: unprovable across two processes while enforcing a distinction a
#: single-local-principal, loopback-only deployment cannot make. The column is an
#: honest record of who wrote the version. `docs/operations/mcv-limitations.md`
#: is where the consequence is disclosed.
capture_versions = Table(
    "capture_versions",
    METADATA,
    Column("version_id", Text, primary_key=True),
    Column(
        "capture_id",
        Text,
        ForeignKey(f"{SCHEMA}.captures.capture_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("version_number", Integer, nullable=False),
    Column(
        "supersedes_version_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_versions.version_id", ondelete="CASCADE"),
        unique=True,
    ),
    Column("content", Text, nullable=False),
    Column("content_sha256", Text, nullable=False),
    Column("owner_principal_id", Text, nullable=False),
    Column("classification", Text, nullable=False),
    Column("processing_policy", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("correlation_id", Text, nullable=False),
    Column("audit_id", Text, nullable=False),
    Column("client_created_at", DateTime(timezone=True)),
    Column("server_received_at", DateTime(timezone=True), nullable=False),
    Column("occurred_at", DateTime(timezone=True)),
    Column("accepted_at", DateTime(timezone=True), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    _is_identifier("version_id", IdKind.CAPTURE_VERSION),
    _is_identifier("owner_principal_id", IdKind.PRINCIPAL),
    _is_identifier("correlation_id", IdKind.CORRELATION),
    _is_identifier("audit_id", IdKind.AUDIT),
    _one_of("classification", Classification, name="capture_classification_is_known"),
    _one_of("processing_policy", ProcessingPolicy),
    _matches("content_sha256", DIGEST_PATTERN.pattern, name="content_sha256_is_a_sha256_digest"),
    CheckConstraint("version_number >= 1", name="version_numbers_start_at_one"),
    # The chain rule the value object also enforces, stated where a hand-run
    # statement meets it too. A first version that supersedes something joins a
    # chain it is not the head of; a later version that supersedes nothing starts
    # a second chain inside one capture.
    CheckConstraint(
        "(version_number = 1) = (supersedes_version_id IS NULL)",
        name="only_the_first_version_supersedes_nothing",
    ),
    # An empty capture is not a capture. The domain refuses one on construction
    # and this refuses one from anywhere else.
    CheckConstraint("length(content) > 0", name="a_capture_version_carries_text"),
    CheckConstraint(
        f"length(content) <= {MAX_CAPTURE_CHARACTERS}",
        name="capture_content_is_bounded",
    ),
    CheckConstraint(
        f"length(idempotency_key) BETWEEN 1 AND {MAX_IDEMPOTENCY_KEY_CHARACTERS}",
        name="a_capture_version_records_a_bounded_key",
    ),
    UniqueConstraint("capture_id", "version_number", name="one_version_number_per_capture"),
    Index("capture_versions_by_capture", "capture_id", "version_number"),
)

#: One row per admitted submission: how a capture arrived and that it was
#: accepted. The content it admitted is on the version, once; nothing here holds
#: it, and `payload_sha256` is what makes an idempotent replay decidable without
#: a second copy.
#:
#: **`idempotency_key` is `NOT NULL UNIQUE`, and that index *is* the
#: `QC-AC-031`/`QC-AC-032` mechanism.** Enforcing replay detection in Python
#: alone would leave two concurrent requests able to both read "absent" and both
#: insert; the constraint means the second insert is refused by the server rather
#: than by a check that already ran. It mirrors
#: `enrollments_idempotency_key_is_scoped`, which does the same job for
#: `sources.enroll`.
#:
#: **There is no `registered_client_id`** — absent, not nullable and never
#: written (`D-74`). `RegisteredCaptureClient` is deferred because `D-30` issues
#: no credential, `O-21` has decided no issuance, and `P00-OD-010` has selected
#: no mechanism, so the column could never hold a value; the rule is the one that
#: keeps `item_count` out of `audit_events`.
#:
#: `request_id` is caller-supplied correlation input, so it is bounded by a
#: constraint rather than trusted: an unbounded caller-controlled column is a
#: payload channel whatever it is called.
capture_submissions = Table(
    "capture_submissions",
    METADATA,
    Column("submission_id", Text, primary_key=True),
    Column("idempotency_key", Text, nullable=False),
    Column("request_id", Text, nullable=False),
    Column("correlation_id", Text, nullable=False),
    Column("principal_id", Text, nullable=False),
    Column("transport", Text, nullable=False),
    Column("capture_method", Text, nullable=False),
    Column("trust_state", Text, nullable=False),
    Column("payload_sha256", Text, nullable=False),
    Column("client_created_at", DateTime(timezone=True)),
    Column("server_received_at", DateTime(timezone=True), nullable=False),
    Column("admission_result", Text, nullable=False),
    # Both references are `DEFERRABLE INITIALLY DEFERRED`, and that is what makes
    # the unique key above the *first* statement of an admission rather than the
    # last. The alternative — insert the capture, the version and the receipt and
    # then discover the key is taken — cannot be undone without a savepoint, so a
    # replay would have to unwind rows it had already written. Inserting this row
    # first under `ON CONFLICT DO NOTHING` means a replay writes nothing at all
    # and a conflict writes nothing at all, which is exactly what `QC-AC-032`
    # requires; the references are still checked, at commit, so nothing dangling
    # can survive the transaction.
    Column(
        "version_id",
        Text,
        ForeignKey(
            f"{SCHEMA}.capture_versions.version_id",
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
    ),
    Column(
        "receipt_id",
        Text,
        ForeignKey(
            f"{SCHEMA}.capture_receipts.receipt_id",
            ondelete="CASCADE",
            deferrable=True,
            initially="DEFERRED",
        ),
        nullable=False,
    ),
    _is_identifier("submission_id", IdKind.SUBMISSION),
    _is_identifier("correlation_id", IdKind.CORRELATION),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    _one_of("transport", CaptureTransport, name="capture_transport_is_known"),
    _one_of("capture_method", CaptureMethod, name="capture_method_is_known"),
    _one_of("trust_state", TrustState, name="capture_trust_state_is_known"),
    _one_of("admission_result", AdmissionResult, name="admission_result_is_known"),
    _matches("payload_sha256", DIGEST_PATTERN.pattern, name="payload_sha256_is_a_sha256_digest"),
    CheckConstraint(
        f"length(request_id) BETWEEN 1 AND {MAX_REQUEST_ID_CHARACTERS}",
        name="a_submission_records_a_bounded_request_id",
    ),
    CheckConstraint(
        f"length(idempotency_key) BETWEEN 1 AND {MAX_IDEMPOTENCY_KEY_CHARACTERS}",
        name="a_submission_records_a_bounded_key",
    ),
    UniqueConstraint("idempotency_key", name="a_capture_key_admits_one_submission"),
)

#: One row per issued receipt: safe evidence that one version was accepted.
#:
#: Carries no content and no hash beyond the one the version already holds.
#: `version_id` is `UNIQUE` because a version is accepted once, so a second
#: receipt for it would be a second acknowledgement of one act.
capture_receipts = Table(
    "capture_receipts",
    METADATA,
    Column("receipt_id", Text, primary_key=True),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_versions.version_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column("idempotency_key", Text, nullable=False),
    Column("issued_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _is_identifier("receipt_id", IdKind.RECEIPT),
    CheckConstraint(
        f"length(idempotency_key) BETWEEN 1 AND {MAX_IDEMPOTENCY_KEY_CHARACTERS}",
        name="a_receipt_records_a_bounded_key",
    ),
)

#: One row per unit of processing a stored capture version implies: the capture
#: plane's half of the job/outbox the repository already has.
#:
#: **A separate table rather than a widened `jobs`, and this is the design's most
#: contestable choice** (`D-76`). `jobs.enrollment_id` is `NOT NULL` with a
#: foreign key to `knowledge.enrollments`, and a capture has no enrollment.
#: Relaxing that column would retroactively change the DDL already-merged
#: revision `8b3f5c17d904` emits, which is the hazard `D-48` refused. The `D-41`
#: objection — "the same persistence twice" — is real, and it is answered by
#: **sharing code rather than tables**: the lease, claim, and retry functions in
#: `persistence.jobs` are parameterised over the table they operate on, so there
#: is one implementation of the lease rule and two tables it runs against. Do not
#: merge the two tables to remove the duplication; the duplication is in the
#: column list, and the column list is what differs.
#:
#: Nothing consumes this queue until WP-7. That is what durable-first means: the
#: work is recorded at the moment it is authorized, so a crash between accepting
#: a capture and processing it loses no work. It is not a speculative column.
capture_jobs = Table(
    "capture_jobs",
    METADATA,
    Column("operation_id", Text, primary_key=True),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_versions.version_id", ondelete="CASCADE"),
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
    _is_identifier("operation_id", IdKind.OPERATION),
    _one_of("state", JobState, name="capture_job_state_is_known"),
    CheckConstraint(
        "last_error_code IS NULL OR last_error_code IN ("
        + ", ".join(f"'{code.value}'" for code in ErrorCode)
        + ")",
        name="capture_job_error_code_is_a_public_error_code",
    ),
    CheckConstraint(
        "(lease_owner IS NULL) = (lease_expires_at IS NULL)",
        name="a_capture_lease_has_an_owner_and_an_expiry",
    ),
    CheckConstraint(
        f"(state = '{JobState.RUNNING.value}') = (lease_owner IS NOT NULL)",
        name="a_capture_job_is_running_exactly_while_leased",
    ),
    CheckConstraint(
        f"attempt_count >= 0 AND max_attempts BETWEEN 1 AND {DEFAULT_MAX_ATTEMPTS * 10} "
        "AND attempt_count <= max_attempts",
        name="capture_job_attempts_are_bounded",
    ),
    Index("capture_jobs_by_state", "state", "created_at"),
)

#: `P-02`'s output: the conservative processing text and the mapping that takes
#: an offset in it back to an offset in the original.
#:
#: **The original is never rewritten**, which is what makes this a second row
#: rather than a column on `capture_versions` — and `capture_versions` is
#: append-only at the server, so it could not have been a column there in any
#: case. `11_EXTRACTION_AND_PROPOSAL_PIPELINE.md:50-54` requires the original to
#: be retained untouched and the mapping to be generated; `09_LOGICAL_DATA_MODEL.md:197`
#: requires the mapping to be reversible and traceable, and `10:89` says no
#: proposal may cite only normalized text — so a span measured here names this
#: row and the mapping is how it resolves back.
#:
#: **The mapping is three parallel arrays of runs, not one array per character.**
#: A per-character map over a hundred-thousand-character capture is a hundred
#: thousand integers to store a transformation that changes almost nothing.
#: Conservative normalization is piecewise affine — a run of characters shifts
#: by a constant — so `(normalized_start, original_start, length)` per run is
#: exact, reversible in both directions, and small. The constraint that the
#: three have equal, non-zero cardinality is what stops a partially written
#: mapping from being storable at all.
#:
#: **There is no `transformations` column.** `09_LOGICAL_DATA_MODEL.md:198` lists
#: one; `normalization_version` names the transformation set, and a second
#: column stating the same fact in another vocabulary is two writers for one
#: fact. A later normalization is a new version and a new row.
capture_processing_text = Table(
    "capture_processing_text",
    METADATA,
    Column("processing_text_id", Text, primary_key=True),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_versions.version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("normalization_version", Text, nullable=False),
    Column("normalized_text", Text, nullable=False),
    Column("normalized_sha256", Text, nullable=False),
    # `unknown` is a real answer `11_…:59` requires to be available, and it is
    # not the same answer as "not detected yet", which is null.
    Column("language", Text),
    Column("run_normalized_start", ARRAY(Integer), nullable=False),
    Column("run_original_start", ARRAY(Integer), nullable=False),
    Column("run_length", ARRAY(Integer), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _is_identifier("processing_text_id", IdKind.PROCESSING_TEXT),
    _matches("normalized_sha256", DIGEST_PATTERN.pattern, name="normalized_sha256_is_a_digest"),
    CheckConstraint(
        f"length(normalization_version) BETWEEN 1 AND {MAX_PIPELINE_VERSION_CHARACTERS}",
        name="a_normalization_version_is_a_bounded_token",
    ),
    CheckConstraint("length(normalized_text) > 0", name="processing_text_carries_text"),
    CheckConstraint(
        f"length(normalized_text) <= {MAX_CAPTURE_CHARACTERS}",
        name="processing_text_is_bounded",
    ),
    CheckConstraint(
        "language IS NULL OR language ~ '^([a-z]{2,3}|unknown)$'",
        name="a_detected_language_is_a_code_or_unknown",
    ),
    CheckConstraint(
        "cardinality(run_normalized_start) > 0 "
        "AND cardinality(run_normalized_start) = cardinality(run_original_start) "
        "AND cardinality(run_normalized_start) = cardinality(run_length)",
        name="an_offset_mapping_is_whole",
    ),
    UniqueConstraint(
        "version_id",
        "normalization_version",
        name="one_processing_text_per_normalization_per_version",
    ),
)

#: One row per stage the pipeline ran for one version, and the key that makes
#: re-running it return the prior output instead of a second one.
#:
#: **`idempotency_key` is `UNIQUE`, and that index *is* the `QC-AC-035`
#: mechanism.** It is `11_…:209`'s recommended key,
#: `sha256(capture_version_id | stage | pipeline_version | stage_config_hash)`,
#: built by `domain.capture.pipeline.stage_identity`. Enforcing replay detection
#: in Python alone would leave two workers able to both read "absent" and both
#: insert; the constraint means the second insert is refused by the server. It
#: mirrors `a_capture_key_admits_one_submission`, which does the same job for a
#: save.
#:
#: **There is no output column, and that is structural.** A stage's output is
#: the rows it wrote — processing text, spans, proposals, classifications,
#: mentions — which are readable by version and stage. Storing the output here
#: as well would put derived capture content in a fourth place and would make
#: "returns the prior output" a read of a copy rather than of the record.
#: `output_sha256` identifies what was produced without carrying it, and
#: `output_row_count` is the only quantity.
#:
#: **`processing_state` is not `JobState`** (`D-91`, and see
#: `domain.capture.pipeline`). A job says whether a worker holds work; this says
#: how far the pipeline got and whether what it produced is whole.
capture_stage_results = Table(
    "capture_stage_results",
    METADATA,
    Column("stage_result_id", Text, primary_key=True),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_versions.version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "operation_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_jobs.operation_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("stage", Text, nullable=False),
    Column("pipeline_version", Text, nullable=False),
    Column("stage_config_sha256", Text, nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("processing_state", Text, nullable=False),
    Column("output_sha256", Text),
    Column("output_row_count", Integer, nullable=False, server_default="0"),
    Column("started_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("completed_at", DateTime(timezone=True)),
    _is_identifier("stage_result_id", IdKind.STAGE_RESULT),
    _one_of("stage", PipelineStage, name="capture_stage_is_known"),
    _one_of("processing_state", ProcessingState, name="capture_processing_state_is_known"),
    _matches("idempotency_key", DIGEST_PATTERN.pattern, name="a_stage_key_is_a_digest"),
    _matches("stage_config_sha256", DIGEST_PATTERN.pattern, name="a_stage_config_is_a_digest"),
    CheckConstraint(
        "output_sha256 IS NULL OR output_sha256 ~ '^[0-9a-f]{64}$'",
        name="a_stage_output_digest_is_a_digest",
    ),
    CheckConstraint(
        f"length(pipeline_version) BETWEEN 1 AND {MAX_PIPELINE_VERSION_CHARACTERS}",
        name="a_pipeline_version_is_a_bounded_token",
    ),
    CheckConstraint("output_row_count >= 0", name="a_stage_writes_no_negative_rows"),
    CheckConstraint(
        "completed_at IS NULL OR completed_at >= started_at",
        name="a_stage_completes_after_it_starts",
    ),
    UniqueConstraint("idempotency_key", name="a_stage_key_admits_one_result"),
    Index("capture_stage_results_by_version", "version_id", "stage"),
)

#: `SourceSpan`: an exact, validated trace from a derived record to the text it
#: came from (`09_LOGICAL_DATA_MODEL.md:167-185`, `10:77-98`).
#:
#: **There is no `quoted_text` column**, and its absence is what makes
#: validation mean something. `09_LOGICAL_DATA_MODEL.md:185` requires validation
#: to "re-derive the quoted text from the immutable source version"; storing the
#: quote beside its digest would make that a comparison of one stored value
#: against another, which passes whenever the two were written together —
#: including when both are wrong. See `domain.capture.span`.
#:
#: **`offset_basis` admits one value and it is written out in the revision**
#: rather than read from a Python constant (`D-97`). The scheme name is the
#: specification's (`10:82`), the freeze mechanism owns the literal, and no new
#: single-value-embedding site is created.
capture_spans = Table(
    "capture_spans",
    METADATA,
    Column("span_id", Text, primary_key=True),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_versions.version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    # Nullable: a span measured against the original text names no processing
    # text, and `10:89` only requires that a proposal not cite normalized text
    # *alone*.
    Column(
        "processing_text_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_processing_text.processing_text_id", ondelete="CASCADE"),
    ),
    Column("start_offset", Integer, nullable=False),
    Column("end_offset", Integer, nullable=False),
    Column("offset_basis", Text, nullable=False),
    Column("line_start", Integer, nullable=False),
    Column("column_start", Integer, nullable=False),
    Column("line_end", Integer, nullable=False),
    Column("column_end", Integer, nullable=False),
    Column("quoted_text_sha256", Text, nullable=False),
    Column("span_role", Text, nullable=False),
    Column("mapping_version", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _is_identifier("span_id", IdKind.SPAN),
    _one_of("offset_basis", OffsetBasis, name="span_offset_basis_is_known"),
    _one_of("span_role", SpanRole, name="span_role_is_known"),
    _matches("quoted_text_sha256", DIGEST_PATTERN.pattern, name="quoted_text_sha256_is_a_digest"),
    CheckConstraint(
        "start_offset >= 0 AND end_offset > start_offset",
        name="a_span_covers_at_least_one_character",
    ),
    CheckConstraint(
        f"end_offset <= {MAX_CAPTURE_CHARACTERS}",
        name="a_span_lies_inside_a_capture",
    ),
    CheckConstraint(
        "line_start >= 1 AND column_start >= 1 AND line_end >= 1 AND column_end >= 1",
        name="span_lines_and_columns_start_at_one",
    ),
    CheckConstraint(
        "line_end > line_start OR (line_end = line_start AND column_end > column_start)",
        name="a_span_ends_after_it_starts",
    ),
    CheckConstraint(
        f"mapping_version IS NULL OR length(mapping_version) "
        f"BETWEEN 1 AND {MAX_MAPPING_VERSION_CHARACTERS}",
        name="a_mapping_version_is_a_bounded_token",
    ),
    Index("capture_spans_by_version", "version_id"),
)

#: `Proposal`: a typed, non-canonical candidate derived from one version
#: (`09_LOGICAL_DATA_MODEL.md:143-165`).
#:
#: **`accepted_record_type` and `accepted_record_id` carry no foreign key**, and
#: the reason is that the table they will name does not exist: acceptance is
#: WP-8's. They are declared nullable rather than deferred to that package
#: because it is the very next one and the table is already scoped, which is the
#: difference between a forward reference and the speculative column `D-74`
#: refused for `registered_client_id` — that one had no package and no
#: mechanism.
#:
#: **`quarantine_reason` has its own vocabulary** rather than reusing
#: `QuarantineReason`, which is about source objects and is keyed by
#: `(enrollment_id, source_object_id)`. See `domain.capture.proposal`.
#:
#: **Every proposal carries at least one span**, and that is a deferred
#: constraint trigger rather than a column here (`D-98`). A counter column would
#: be a second statement of a fact `capture_proposal_spans` already holds and
#: would need an `UPDATE` path on this table to maintain.
capture_proposals = Table(
    "capture_proposals",
    METADATA,
    Column("proposal_id", Text, primary_key=True),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_versions.version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("proposal_type", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("risk_class", Text, nullable=False),
    Column("method", Text, nullable=False),
    Column("method_version", Text, nullable=False),
    Column("schema_version", Text, nullable=False),
    Column(
        "missing_required_fields",
        ARRAY(Text),
        nullable=False,
        server_default="{}",
    ),
    Column("normalized_value", Text),
    Column("quarantine_reason", Text),
    Column("accepted_record_type", Text),
    Column("accepted_record_id", Text),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _is_identifier("proposal_id", IdKind.PROPOSAL),
    _one_of("proposal_type", ProposalType, name="proposal_type_is_known"),
    _one_of("state", ProposalState, name="proposal_state_is_known"),
    _one_of("risk_class", RiskClass, name="proposal_risk_class_is_known"),
    _one_of("method", ProposalMethod, name="proposal_method_is_known"),
    CheckConstraint(
        "quarantine_reason IS NULL OR quarantine_reason IN ("
        + _literals(ProposalQuarantineReason)
        + ")",
        name="proposal_quarantine_reason_is_known",
    ),
    _each_one_of(
        "missing_required_fields",
        ProposalField,
        name="a_missing_required_field_is_a_required_field",
    ),
    # The rule `domain.capture.proposal.Proposal` also enforces, stated where a
    # hand-run statement meets it too. An `invalidated` proposal with no reason
    # records that evidence failed without recording how.
    CheckConstraint(
        f"(state = '{ProposalState.INVALIDATED.value}') = (quarantine_reason IS NOT NULL)",
        name="an_invalidated_proposal_records_its_reason",
    ),
    CheckConstraint(
        "(accepted_record_type IS NULL) = (accepted_record_id IS NULL)",
        name="an_accepted_record_is_named_by_type_and_identifier",
    ),
    CheckConstraint(
        f"normalized_value IS NULL OR length(normalized_value) "
        f"BETWEEN 1 AND {MAX_NORMALIZED_VALUE_CHARACTERS}",
        name="a_normalized_value_is_bounded",
    ),
    CheckConstraint(
        f"length(method_version) BETWEEN 1 AND {MAX_PROPOSAL_VERSION_CHARACTERS} "
        f"AND length(schema_version) BETWEEN 1 AND {MAX_PROPOSAL_VERSION_CHARACTERS}",
        name="proposal_versions_are_bounded_tokens",
    ),
    Index("capture_proposals_by_version", "version_id", "state"),
)

#: The `[1..n]` between a proposal and the spans it cites
#: (`09_LOGICAL_DATA_MODEL.md:37`).
#:
#: The composite primary key is the upper half: a proposal cites one span once.
#: The lower half — *at least* one — cannot be a `CHECK`, because PostgreSQL
#: evaluates a check against one row of one table, and is a `DEFERRABLE
#: INITIALLY DEFERRED` constraint trigger installed by the revision instead
#: (`D-98`). Deferred because the proposal and its links are written in one
#: transaction and the proposal has to be inserted first for the link to
#: reference it.
capture_proposal_spans = Table(
    "capture_proposal_spans",
    METADATA,
    Column(
        "proposal_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_proposals.proposal_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "span_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_spans.span_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("linked_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    PrimaryKeyConstraint("proposal_id", "span_id", name="a_proposal_cites_a_span_once"),
    Index("capture_proposal_spans_by_span", "span_id"),
)

#: `CaptureClassification`: one label a deterministic rule attached to one
#: version, with the span it was derived from.
#:
#: **`span_id` is `NOT NULL`**, which is the whole boundary between this record
#: and `CaptureDomainAssignment` (`D-94`, and see
#: `domain.capture.classification`): a classification can be cited and a domain
#: assignment cannot, so the one that can is the one that must.
#:
#: The unique key is `09_CANONICAL_…:146`'s "versioned multi-label": many labels
#: per version, one row per label per scheme version, and a later scheme adds
#: rows beside these rather than replacing them.
capture_classifications = Table(
    "capture_classifications",
    METADATA,
    Column("classification_id", Text, primary_key=True),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_versions.version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "span_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_spans.span_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("scheme", Text, nullable=False),
    Column("scheme_version", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("rule", Text, nullable=False),
    Column("rule_version", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _is_identifier("classification_id", IdKind.CAPTURE_CLASSIFICATION),
    _one_of("label", CaptureLabel, name="capture_label_is_known"),
    CheckConstraint(
        f"length(scheme) BETWEEN 1 AND {MAX_SCHEME_CHARACTERS} "
        f"AND length(scheme_version) BETWEEN 1 AND {MAX_SCHEME_CHARACTERS} "
        f"AND length(rule) BETWEEN 1 AND {MAX_SCHEME_CHARACTERS} "
        f"AND length(rule_version) BETWEEN 1 AND {MAX_SCHEME_CHARACTERS}",
        name="classification_tokens_are_bounded",
    ),
    UniqueConstraint(
        "version_id",
        "scheme",
        "scheme_version",
        "label",
        name="one_label_per_scheme_version_per_capture_version",
    ),
)

#: `CaptureEntityMention`, restricted to the deterministic subset (`D-93`).
#:
#: **There is no surface-text column.** `09_CANONICAL_…:147` asks for "exact
#: surface text"; the span this row requires points at exactly that in the
#: immutable version and re-derives on read, so a second copy would be a fourth
#: place capture content sits and would make "exact" a claim about the copy.
#:
#: `resolution_state` admits one value and is frozen at it. Resolution is `P-07`
#: and `P-07` is excluded, so `candidate` and `resolved` are unreachable; the
#: `D-78` precedent is a forward `ALTER` when a resolver arrives, not a column
#: that already admits states nothing can write.
capture_entity_mentions = Table(
    "capture_entity_mentions",
    METADATA,
    Column("mention_id", Text, primary_key=True),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_versions.version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "span_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_spans.span_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("entity_type", Text, nullable=False),
    Column(
        "resolution_state",
        Text,
        nullable=False,
        server_default=ResolutionState.UNRESOLVED.value,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _is_identifier("mention_id", IdKind.CAPTURE_ENTITY_MENTION),
    _one_of("entity_type", EntityType, name="mention_entity_type_is_known"),
    _one_of("resolution_state", ResolutionState, name="mention_resolution_state_is_known"),
    UniqueConstraint(
        "version_id", "span_id", "entity_type", name="one_mention_per_span_per_entity_type"
    ),
)
