"""The `knowledge` schema: sources, objects, enrollment, jobs, and extraction.

This is the application's own schema and it is deliberately not any of the ones
that already exist. The eight domain schemas hold the migrated legacy corpus and
are read-only history. `migration_control` is a ledger for one migration run:
reusing it would make an enrollment retry indistinguishable from a migration
retry in the same tables, and would put application code on the write path of
migration governance state. Two planes with different lifetimes, different
writers, and different authority do not share a schema.

The schema is split into bounded concerns and contains no general scheduler,
priority column, or soft-delete flag: each of those would be a mechanism with no
caller, and `AGENTS.md` section 2 rules them out until one exists.
`audit_events` is not the "audit mirror" an earlier revision of this paragraph
ruled out — a mirror duplicates rows another table already owns, and this is the
only place an audit event is stored at all (`D-34`).

**Four columns in the schema hold content, under three different authorities.**
`source_version_evidence.payload` is byte-exact, source-authoritative evidence
bound to one immutable source version. `extractions.text` is derived text bound
to the source version it was extracted from. `capture_versions.content` is the
text the user typed, which
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

`native_root`, `native_locator`, `private_locator`, and `cursor_private` are the
only provider-native values in the schema. They exist because an opaque
identifier has to resolve back to something, and no domain type carries any of
them. Everything else is an opaque identifier, an enumerated code, a bounded
token, a timestamp, a count, or source-authoritative evidence bytes.

The tables are declared once here for runtime access. Alembic revisions use
frozen literal definitions so an old revision cannot change meaning when this
module evolves. Each revision names the tables it creates explicitly, and schema
tests assert the correspondence.
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
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Identity,
    Index,
    Integer,
    LargeBinary,
    MetaData,
    PrimaryKeyConstraint,
    Table,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB

from my_pa.contracts.v1.errors import ErrorCode
from my_pa.contracts.v1.native_sources import NATIVE_SOURCE_MAX_PAGE_SIZE
from my_pa.domain.audit.events import AuditOutcome
from my_pa.domain.capture.assertion import AssertionState
from my_pa.domain.capture.classification import (
    MAX_SCHEME_CHARACTERS,
    CaptureLabel,
    EntityType,
    ResolutionState,
)
from my_pa.domain.capture.context import (
    ContextLinkAuthority,
    ContextLinkRole,
    ContextLinkTarget,
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
from my_pa.domain.capture.review import Disposition
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
from my_pa.domain.conversation.event import ConversationChannel, ConversationState
from my_pa.domain.extraction.coverage import LimitationReason
from my_pa.domain.extraction.quarantine import QuarantineReason, QuarantineReviewState
from my_pa.domain.extraction.text import SUPPORTED_MEDIA_TYPES, ExtractionStatus
from my_pa.domain.identity.operation import Capability, NativeSourceCapability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.native_sources import (
    LiveActivationGateState,
    NativeRunKind,
    NativeRunState,
    NativeSourceKind,
    WatcherSimulationState,
)
from my_pa.domain.policy.decision import POLICY_VERSION_PATTERN, DenialReason
from my_pa.domain.relationship.event import RelationshipEventType
from my_pa.domain.relationship.identity import ResolutionAction
from my_pa.domain.relationship.profile import EvidenceAuthority
from my_pa.domain.situation.situation import (
    FrameState,
    ProjectState,
    PulseItemType,
    SituationState,
)
from my_pa.domain.source.enrollment import (
    MAX_ENROLLMENT_BYTES,
    MAX_ENROLLMENT_DEPTH,
    MAX_ENROLLMENT_ITEMS,
)
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import SourceProviderKind

SCHEMA: Final = "knowledge"
NATIVE_BASELINE_TERMINAL_CURSOR: Final = "__my_pa_native_baseline_complete__"

METADATA: Final = MetaData(schema=SCHEMA)

#: The current runtime audit vocabulary. Unlike Alembic's historical literals,
#: this declaration follows both capability enums because it describes the
#: schema at head rather than a revision whose meaning must remain frozen.
_CURRENT_AUDIT_CAPABILITIES: Final[frozenset[str]] = frozenset(
    member.value for member in Capability
) | frozenset(member.value for member in NativeSourceCapability)

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
    # The queue's own partition (WP-04, revision `4f1a8b6d92e3`). Ownership was
    # transitive through `enrollment_id -> enrollments.principal_id` until then,
    # which made the dequeue a global FIFO: `claim_job` ordered by
    # `(created_at, operation_id)` across every Principal's work at once, so one
    # Principal's backlog decided when another's work ran, and a count of
    # outstanding work was a count of everybody's. A predicate cannot be written
    # against a column that does not exist, so the column comes first.
    Column("principal_id", Text, nullable=False),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
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
    # Principal first, then the claim's own ordering, so the dequeue reads one
    # Principal's queue rather than filtering the whole table.
    Index("jobs_by_principal_claim_order", "principal_id", "state", "created_at"),
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
    _one_of("capability", _CURRENT_AUDIT_CAPABILITIES),
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
    # As `1a4c9e77b2d5` emitted it. **The head shape is no longer this**:
    # `e7f3a9c2d514` (WP-03) replaces it forward with
    # `a_capture_key_admits_one_submission_per_principal` UNIQUE
    # (principal_id, idempotency_key), because that revision copies this live
    # declaration when it runs and restating the key here would change what a
    # merged revision emits. The mechanism argument above still holds; only the
    # collision domain narrowed from global to per-Principal.
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
    # The capture queue's partition, for the reason `jobs.principal_id` carries
    # one. Ownership here was transitive through
    # `version_id -> capture_versions.owner_principal_id`.
    Column("principal_id", Text, nullable=False),
    _is_identifier("operation_id", IdKind.OPERATION),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
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
    Index("capture_jobs_by_principal_claim_order", "principal_id", "state", "created_at"),
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

#: `ReviewCase`: one proposal held back from canonical until someone decides
#: (`12_REVIEW_AND_PROMOTION_POLICY.md:112-125`).
#:
#: **`proposal_id` is `UNIQUE`**, and that is what makes a re-review a second
#: *decision* rather than a second case. Two cases for one proposal would give
#: "what was decided about this proposal" two answers with nothing to choose
#: between them, which is the argument `capture_versions.supersedes_version_id`
#: makes for its own uniqueness.
#:
#: **There is no `risk_class` and no `authority_class` column.**
#: `12_REVIEW_AND_PROMOTION_POLICY.md:95-100` gives four classes and four
#: default routings, and the four class names are the ones `RiskClass` already
#: carries — so an `authority_class` would be a second enum with the same values
#: as an existing one, which the `D-81` guard keys by value and could not tell
#: apart from it. Reusing `RiskClass` for such a column instead only moves the
#: problem: the proposal this case names already carries `risk_class`, and
#: `proposal_id` is `UNIQUE`, so either column would be a second statement of a
#: fact one join away. It is the rule `capture_processing_text` follows in
#: refusing a `transformations` column.
#:
#: **There is no `allowed_dispositions` column**, although
#: `12_REVIEW_AND_PROMOTION_POLICY.md:124` lists one among a review case's
#: contents: the allowed set is a rule, and a stored copy of a rule is a second
#: place it can be stated and the only place it can be wrong.
#:
#: **And no provenance columns.** `method`, `method_version` and `schema_version`
#: are on the proposal already.
#:
#: `capture_id` and `version_id` *are* carried, although the proposal determines
#: both. `12_REVIEW_AND_PROMOTION_POLICY.md:115` requires a case to bind the
#: exact capture and version and `:118` the expected version, and the same
#: redundancy is already accepted at `capture_classifications` and
#: `capture_entity_mentions`, which carry `version_id` beside a `span_id` that
#: determines it.
capture_review_cases = Table(
    "capture_review_cases",
    METADATA,
    Column("review_case_id", Text, primary_key=True),
    Column(
        "proposal_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_proposals.proposal_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column(
        "capture_id",
        Text,
        ForeignKey(f"{SCHEMA}.captures.capture_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_versions.version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("principal_id", Text, nullable=False),
    Column("opened_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _is_identifier("review_case_id", IdKind.REVIEW_CASE),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    Index("capture_review_cases_by_capture", "capture_id", "opened_at"),
    Index("capture_review_cases_by_principal", "principal_id", "opened_at"),
)

#: `ReviewDecision`: what was decided, by whom, and in what order.
#:
#: **Append only, and there is no `state` column to drift.** The case's current
#: disposition is the row with the greatest `sequence`, which is a read of the
#: rows themselves and so cannot disagree with them — the argument `captures`
#: makes for having no `current_version_id`. `UNIQUE(review_case_id, sequence)`
#: is what makes "the greatest" a single row under concurrent write rather than
#: a race two writers can both win.
#:
#: **`audit_id` is a reference and not a foreign key**, on the terms
#: `capture_versions` states: the audit event committed on its own connection
#: before this transaction opened, and a constraint would make the audit's
#: durability depend on the durability of the work it exists to outlive.
capture_review_decisions = Table(
    "capture_review_decisions",
    METADATA,
    Column("decision_id", Text, primary_key=True),
    Column(
        "review_case_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_review_cases.review_case_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("sequence", Integer, nullable=False),
    Column("disposition", Text, nullable=False),
    Column("principal_id", Text, nullable=False),
    Column("correlation_id", Text, nullable=False),
    Column("audit_id", Text, nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    _is_identifier("decision_id", IdKind.REVIEW_DECISION),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    _is_identifier("correlation_id", IdKind.CORRELATION),
    _is_identifier("audit_id", IdKind.AUDIT),
    _one_of("disposition", Disposition, name="review_disposition_is_known"),
    CheckConstraint("sequence >= 1", name="review_decisions_are_numbered_from_one"),
    UniqueConstraint(
        "review_case_id", "sequence", name="one_decision_per_sequence_per_review_case"
    ),
)

#: `Assertion`: the canonical record an accepted proposal becomes
#: (`09_CANONICAL_OBJECT_AND_DOMAIN_MODEL.md:95`).
#:
#: **`proposal_id` is `UNIQUE`**: one proposal is accepted once, and a second
#: assertion for it would be a second promotion of one act. That is the rule
#: `capture_receipts.version_id` states for acceptance of a version.
#:
#: **`normalized_value` is the assertion's own, not the proposal's.** A
#: corrected accept writes the corrected value here while the proposal keeps what
#: it derived and moves to `corrected_accepted`, so nothing is updated in place
#: and the lineage `QC-AC-022` protects survives. There is no separate correction
#: table; see `domain.capture.assertion`.
#:
#: **`superseded_by_assertion_id` is `UNIQUE`** for the reason
#: `capture_versions.supersedes_version_id` is: without it two assertions could
#: name the same predecessor and the chain would fork.
#:
#: **Every assertion cites at least one span**, and that is a deferred constraint
#: trigger rather than a counter column here, exactly as it is for a proposal: a
#: counter would be a second statement of a fact `capture_assertion_spans`
#: already holds and would need an `UPDATE` path to maintain.
capture_assertions = Table(
    "capture_assertions",
    METADATA,
    Column("assertion_id", Text, primary_key=True),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_versions.version_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "proposal_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_proposals.proposal_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column(
        "decision_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_review_decisions.decision_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("principal_id", Text, nullable=False),
    Column("assertion_type", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("normalized_value", Text),
    Column(
        "superseded_by_assertion_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_assertions.assertion_id", ondelete="CASCADE"),
        unique=True,
    ),
    Column("accepted_at", DateTime(timezone=True), nullable=False),
    Column("revalidation_required_at", DateTime(timezone=True)),
    _is_identifier("assertion_id", IdKind.ASSERTION),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    # The assertion's type is the proposal's type carried forward, so it is
    # constrained against the same vocabulary rather than a parallel one.
    _one_of("assertion_type", ProposalType, name="assertion_type_is_known"),
    _one_of("state", AssertionState, name="assertion_state_is_known"),
    # The rule ADR-003 clause 8 states, where a hand-run statement meets it too.
    # An assertion in `revalidation_required` with no timestamp records that
    # evidence moved without recording when, and any other state with one
    # attributes a re-validation to a record that was never asked for one.
    CheckConstraint(
        f"(state = '{AssertionState.REVALIDATION_REQUIRED.value}') "
        "= (revalidation_required_at IS NOT NULL)",
        name="a_revalidating_assertion_records_when_it_was_asked",
    ),
    CheckConstraint(
        f"normalized_value IS NULL OR length(normalized_value) "
        f"BETWEEN 1 AND {MAX_NORMALIZED_VALUE_CHARACTERS}",
        name="an_asserted_value_is_bounded",
    ),
    Index("capture_assertions_by_principal", "principal_id", "assertion_id"),
    # The historical index, kept exactly as `3c8f1e2a5b74` emitted it so the
    # freeze in that revision stays purely subtractive (`D-48`).
    Index("capture_assertions_by_version", "version_id", "state"),
    # The principal-first composite that makes a per-owner "assertions in this
    # version, by state" read an index scan rather than a filter over the whole
    # version. Added by `b9a4ecdfac0b`; a distinct name so the freeze only ever
    # *drops* WP-05 additions and never has to reshape a historical index.
    Index("capture_assertions_by_principal_version", "principal_id", "version_id", "state"),
)

#: The `[1..n]` between an assertion and the spans it rests on, mirroring
#: `capture_proposal_spans`.
#:
#: The composite primary key is the upper half: an assertion cites one span once.
#: The lower half — *at least* one — is a `DEFERRABLE INITIALLY DEFERRED`
#: constraint trigger installed by the revision, because PostgreSQL evaluates a
#: check against one row of one table and the row that must be refused is an
#: assertion whose *other* table holds nothing.
capture_assertion_spans = Table(
    "capture_assertion_spans",
    METADATA,
    Column(
        "assertion_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_assertions.assertion_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "span_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_spans.span_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("principal_id", Text, nullable=False),
    Column("linked_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    PrimaryKeyConstraint("assertion_id", "span_id", name="an_assertion_cites_a_span_once"),
    Index("capture_assertion_spans_by_span", "span_id"),
    Index("capture_assertion_spans_by_principal", "principal_id", "assertion_id"),
)

#: One row per promotion: safe evidence that one proposal became canonical.
#:
#: **A separate table from `capture_receipts`**, and not a widening of it.
#: That table's `version_id` is `UNIQUE` because a version is accepted once; a
#: promotion is a different act on a different object, and relaxing the existing
#: column would retroactively change what an already-merged revision emits.
#:
#: Carries no content and no summary of what was promoted — the assertion holds
#: that, once. `policy_version` is the same bounded token `audit_events` records,
#: so an operator can say which policy admitted the promotion.
capture_promotion_receipts = Table(
    "capture_promotion_receipts",
    METADATA,
    Column("receipt_id", Text, primary_key=True),
    Column(
        "assertion_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_assertions.assertion_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column(
        "decision_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_review_decisions.decision_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("principal_id", Text, nullable=False),
    Column("policy_version", Text, nullable=False),
    Column("issued_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _is_identifier("receipt_id", IdKind.RECEIPT),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    _matches(
        "policy_version",
        POLICY_VERSION_PATTERN.pattern,
        name="promotion_policy_version_is_a_known_shape",
    ),
    Index("capture_promotion_receipts_by_principal", "principal_id", "receipt_id"),
)

#: `CaptureContextLink`: what a capture was launched from
#: (`09_LOGICAL_DATA_MODEL.md:106-124`).
#:
#: **Bound to the capture and not to the version**, which is where this differs
#: from `capture_classifications`: `09_LOGICAL_DATA_MODEL.md:113` names
#: `capture_id`, and the context a capture was started from does not change when
#: its text is revised.
#:
#: **`target_id` is constrained to a source object's identifier shape.**
#: `target_type` admits one value, so the kind is decided, and giving the column
#: `_is_identifier` is what stops a path, a host, or a query string being stored
#: as a target — the `INV-PKL-005` guard every other identifier column has and
#: `capture_proposals.accepted_record_id` conspicuously lacks.
#:
#: **The partial unique index is `09_LOGICAL_DATA_MODEL.md:124`'s "unique active
#: link"**, and it is narrower than that sentence's "per capture/target/role/
#: authority": including the authority state would admit a `proposed` link and a
#: `deterministic` link to the same target at once. See `domain.capture.context`.
capture_context_links = Table(
    "capture_context_links",
    METADATA,
    Column("capture_context_link_id", Text, primary_key=True),
    Column(
        "capture_id",
        Text,
        ForeignKey(f"{SCHEMA}.captures.capture_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("target_type", Text, nullable=False),
    Column("target_id", Text, nullable=False),
    Column("link_role", Text, nullable=False),
    Column("authority_state", Text, nullable=False),
    Column(
        "evidence_span_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_spans.span_id", ondelete="CASCADE"),
    ),
    Column(
        "review_case_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_review_cases.review_case_id", ondelete="CASCADE"),
    ),
    Column(
        "superseded_by_link_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_context_links.capture_context_link_id", ondelete="CASCADE"),
        unique=True,
    ),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("accepted_at", DateTime(timezone=True)),
    Column("superseded_at", DateTime(timezone=True)),
    _is_identifier("capture_context_link_id", IdKind.CONTEXT_LINK),
    _is_identifier("target_id", IdKind.SOURCE_OBJECT),
    _one_of("target_type", ContextLinkTarget, name="context_link_target_type_is_known"),
    _one_of("link_role", ContextLinkRole, name="context_link_role_is_known"),
    _one_of("authority_state", ContextLinkAuthority, name="context_link_authority_state_is_known"),
    # The rule the partial index below depends on: a link is superseded exactly
    # while it records when it was. Without it a row could claim the superseded
    # authority and still occupy the active slot.
    CheckConstraint(
        f"(authority_state = '{ContextLinkAuthority.SUPERSEDED.value}') "
        "= (superseded_at IS NOT NULL)",
        name="a_superseded_link_records_when_it_was",
    ),
    Index(
        "one_active_context_link_per_capture_target_and_role",
        "capture_id",
        "target_id",
        "link_role",
        unique=True,
        postgresql_where=text("superseded_at IS NULL"),
    ),
)

#: `Conversation`: the event an explicit Conversation Log seeds
#: (`09_LOGICAL_DATA_MODEL.md:202-224`).
#:
#: **The presence of this row is the capture's mode**, which is why there is no
#: `capture_kind` column on `captures`. See `domain.conversation`.
#:
#: **`version_id` is `UNIQUE`**: one conversation event per capture version, so a
#: replayed create cannot seed a second skeletal event for the same text.
#:
#: **No `accepted_summary` and no `summary_authority_state`**
#: (`09_LOGICAL_DATA_MODEL.md:218-219`): a summary needs a model and
#: `P00-OD-006` is open, so the columns are absent rather than declared and
#: unreachable. `channel` defaults to `unknown` because
#: `09_LOGICAL_DATA_MODEL.md:224` requires a skeletal event to be seedable with
#: an unknown channel.
capture_conversations = Table(
    "capture_conversations",
    METADATA,
    Column("conversation_id", Text, primary_key=True),
    Column(
        "capture_id",
        Text,
        ForeignKey(f"{SCHEMA}.captures.capture_id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_versions.version_id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    ),
    Column("event_state", Text, nullable=False),
    Column(
        "channel",
        Text,
        nullable=False,
        server_default=ConversationChannel.UNKNOWN.value,
    ),
    Column("occurred_at_start", DateTime(timezone=True)),
    Column("occurred_at_end", DateTime(timezone=True)),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column(
        "superseded_by_conversation_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_conversations.conversation_id", ondelete="CASCADE"),
        unique=True,
    ),
    _is_identifier("conversation_id", IdKind.CONVERSATION),
    _one_of("event_state", ConversationState, name="conversation_event_state_is_known"),
    _one_of("channel", ConversationChannel, name="conversation_channel_is_known"),
    # An end with no start is a duration with no anchor, and an end before its
    # start is not a conversation. Both are nullable because a Conversation Log
    # may be seeded before either is known.
    CheckConstraint(
        "occurred_at_end IS NULL OR "
        "(occurred_at_start IS NOT NULL AND occurred_at_end >= occurred_at_start)",
        name="a_conversation_ends_after_it_starts",
    ),
    Index("capture_conversations_by_capture", "capture_id", "recorded_at"),
)

# WP-9 relationship identity. Source rows remain in `relationship_identity_observations`;
# the only link to a canonical person is the separate, review-bound resolution table.
relationship_people = Table(
    "relationship_people",
    METADATA,
    Column("person_id", Text, primary_key=True),
    Column("display_name", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column(
        "superseded_by_person_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_people.person_id"),
        unique=True,
    ),
    Column("state_resolution_id", Text, unique=True),
    Column("principal_id", Text, nullable=False),
    _is_identifier("person_id", IdKind.PERSON),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    CheckConstraint("length(trim(display_name)) > 0", name="a_person_name_is_not_blank"),
    Index("relationship_people_by_principal", "principal_id"),
)

relationship_organizations = Table(
    "relationship_organizations",
    METADATA,
    Column("organization_id", Text, primary_key=True),
    Column("display_name", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("principal_id", Text, nullable=False),
    _is_identifier("organization_id", IdKind.ORGANIZATION),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    CheckConstraint("length(trim(display_name)) > 0", name="an_organization_name_is_not_blank"),
    Index("relationship_organizations_by_principal", "principal_id"),
)

relationship_identity_observations = Table(
    "relationship_identity_observations",
    METADATA,
    Column("observation_id", Text, primary_key=True),
    Column("source_id", Text, nullable=False),
    Column("source_object_id", Text, nullable=False),
    Column("source_version", Text, nullable=False),
    Column("source_domain", Text, nullable=False),
    Column("display_name", Text),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("observation_id", IdKind.IDENTITY_OBSERVATION),
    _is_identifier("source_id", IdKind.SOURCE),
    _is_identifier("source_object_id", IdKind.SOURCE_OBJECT),
    CheckConstraint(
        "source_domain IN ('calendar', 'contacts', 'email')",
        name="an_identity_observation_has_a_fixture_domain",
    ),
    CheckConstraint(
        "length(source_version) BETWEEN 1 AND 72",
        name="an_identity_source_version_is_bounded",
    ),
    UniqueConstraint(
        "source_id",
        "source_object_id",
        "source_version",
        name="an_observed_source_version_is_recorded_once",
    ),
    Column("principal_id", Text, nullable=False),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    Index("relationship_identity_observations_by_principal", "principal_id"),
)

relationship_unresolved_mentions = Table(
    "relationship_unresolved_mentions",
    METADATA,
    Column("unresolved_mention_id", Text, primary_key=True),
    Column("source_object_id", Text, nullable=False),
    Column("source_version", Text, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("unresolved_mention_id", IdKind.UNRESOLVED_MENTION),
    _is_identifier("source_object_id", IdKind.SOURCE_OBJECT),
    CheckConstraint(
        "length(source_version) BETWEEN 1 AND 72",
        name="an_unresolved_source_version_is_bounded",
    ),
    Column("principal_id", Text, nullable=False),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    Index("relationship_unresolved_mentions_by_principal", "principal_id"),
)

relationship_duplicate_sets = Table(
    "relationship_duplicate_sets",
    METADATA,
    Column("duplicate_set_id", Text, primary_key=True),
    Column("candidate_kind", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _is_identifier("duplicate_set_id", IdKind.DUPLICATE_SET),
    CheckConstraint(
        "candidate_kind IN ('identity_resolution', 'duplicate')",
        name="identity_candidate_set_kind_is_known",
    ),
    Column("principal_id", Text, nullable=False),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    Index("relationship_duplicate_sets_by_principal", "principal_id"),
)

relationship_duplicate_members = Table(
    "relationship_duplicate_members",
    METADATA,
    Column(
        "duplicate_set_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_duplicate_sets.duplicate_set_id"),
        nullable=False,
    ),
    Column(
        "person_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_people.person_id"),
    ),
    Column(
        "observation_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_identity_observations.observation_id"),
    ),
    CheckConstraint(
        "(person_id IS NULL) <> (observation_id IS NULL)",
        name="a_duplicate_member_names_one_candidate_kind",
    ),
    UniqueConstraint(
        "duplicate_set_id", "person_id", name="a_person_occurs_once_in_a_duplicate_set"
    ),
    UniqueConstraint(
        "duplicate_set_id",
        "observation_id",
        name="an_observation_occurs_once_in_a_duplicate_set",
    ),
    Column("principal_id", Text, nullable=False),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    Index("relationship_duplicate_members_by_principal", "principal_id"),
)

relationship_identity_review_cases = Table(
    "relationship_identity_review_cases",
    METADATA,
    Column("review_case_id", Text, primary_key=True),
    Column(
        "duplicate_set_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_duplicate_sets.duplicate_set_id"),
        nullable=False,
        unique=True,
    ),
    Column("requested_action", Text, nullable=False),
    Column("retained_person_id", Text, ForeignKey(f"{SCHEMA}.relationship_people.person_id")),
    Column("prior_person_id", Text, ForeignKey(f"{SCHEMA}.relationship_people.person_id")),
    Column("opened_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    _is_identifier("review_case_id", IdKind.REVIEW_CASE),
    _one_of("requested_action", ResolutionAction, name="identity_review_action_is_known"),
    CheckConstraint(
        "(requested_action IN ('merge_person', 'split_person')) = "
        "(retained_person_id IS NOT NULL AND prior_person_id IS NOT NULL)",
        name="a_merge_or_split_review_names_both_people",
    ),
    CheckConstraint(
        "retained_person_id IS NULL OR retained_person_id <> prior_person_id",
        name="an_identity_review_names_distinct_people",
    ),
    Column("principal_id", Text, nullable=False),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    Index("relationship_identity_review_cases_by_principal", "principal_id"),
)

relationship_identity_review_decisions = Table(
    "relationship_identity_review_decisions",
    METADATA,
    Column("decision_id", Text, primary_key=True),
    Column(
        "review_case_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_identity_review_cases.review_case_id"),
        nullable=False,
    ),
    Column("sequence", Integer, nullable=False),
    Column("disposition", Text, nullable=False),
    Column("principal_id", Text, nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    _is_identifier("decision_id", IdKind.REVIEW_DECISION),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    CheckConstraint(
        "disposition IN ('accept', 'reject', 'defer')",
        name="identity_review_disposition_is_known",
    ),
    CheckConstraint("sequence >= 1", name="identity_review_decisions_start_at_one"),
    UniqueConstraint("review_case_id", "sequence", name="one_identity_decision_per_sequence"),
    Index("relationship_identity_review_decisions_by_principal", "principal_id"),
)

relationship_identity_resolutions = Table(
    "relationship_identity_resolutions",
    METADATA,
    Column("resolution_id", Text, primary_key=True),
    Column("resolution_sequence", BigInteger, Identity(), nullable=False, unique=True),
    Column("action", Text, nullable=False),
    Column(
        "review_case_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_identity_review_cases.review_case_id"),
        nullable=False,
    ),
    Column(
        "decision_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_identity_review_decisions.decision_id"),
        nullable=False,
        unique=True,
    ),
    Column(
        "retained_person_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_people.person_id"),
        nullable=False,
    ),
    Column(
        "prior_person_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_people.person_id"),
    ),
    Column("decided_at", DateTime(timezone=True), nullable=False),
    _is_identifier("resolution_id", IdKind.IDENTITY_RESOLUTION),
    _one_of("action", ResolutionAction, name="identity_resolution_action_is_known"),
    CheckConstraint(
        "(action = 'link_observation') = (prior_person_id IS NULL)",
        name="a_merge_or_split_retains_both_people",
    ),
    CheckConstraint(
        "prior_person_id IS NULL OR retained_person_id <> prior_person_id",
        name="an_identity_resolution_names_distinct_people",
    ),
    Column("principal_id", Text, nullable=False),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    Index("relationship_identity_resolutions_by_principal", "principal_id"),
)

relationship_resolution_observations = Table(
    "relationship_resolution_observations",
    METADATA,
    Column(
        "resolution_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_identity_resolutions.resolution_id"),
        nullable=False,
    ),
    Column(
        "observation_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_identity_observations.observation_id"),
        nullable=False,
    ),
    Column("principal_id", Text, nullable=False),
    PrimaryKeyConstraint("resolution_id", "observation_id"),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    Index("relationship_resolution_observations_by_principal", "principal_id"),
)

relationship_observation_links = Table(
    "relationship_observation_links",
    METADATA,
    Column(
        "observation_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_identity_observations.observation_id"),
        primary_key=True,
    ),
    Column(
        "person_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_people.person_id"),
        nullable=False,
    ),
    Column(
        "resolution_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_identity_resolutions.resolution_id"),
        nullable=False,
    ),
    Column("principal_id", Text, nullable=False),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    Index("relationship_observation_links_by_principal", "principal_id"),
)

# Added after both declarations so SQLAlchemy can represent the intentionally
# deferred logical cycle: a person is inserted, its resolution is inserted, and
# the person is then bound to that exact state receipt in one transaction.
relationship_people.c.state_resolution_id.append_foreign_key(
    ForeignKey(f"{SCHEMA}.relationship_identity_resolutions.resolution_id")
)

relationship_aliases = Table(
    "relationship_aliases",
    METADATA,
    Column("alias_id", Text, primary_key=True),
    Column(
        "person_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_people.person_id"),
        nullable=False,
    ),
    Column(
        "observation_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_identity_observations.observation_id"),
        nullable=False,
    ),
    Column("value", Text, nullable=False),
    Column("principal_id", Text, nullable=False),
    _is_identifier("alias_id", IdKind.ALIAS),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    UniqueConstraint("observation_id", name="one_source_bound_alias_per_observation"),
    CheckConstraint("length(trim(value)) > 0", name="an_alias_is_not_blank"),
    Index("relationship_aliases_by_principal", "principal_id"),
)

relationship_affiliations = Table(
    "relationship_affiliations",
    METADATA,
    Column("affiliation_id", Text, primary_key=True),
    Column(
        "person_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_people.person_id"),
        nullable=False,
    ),
    Column(
        "organization_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_organizations.organization_id"),
        nullable=False,
    ),
    Column(
        "observation_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_identity_observations.observation_id"),
        nullable=False,
    ),
    Column("role", Text),
    Column("effective_from", DateTime(timezone=True)),
    Column("effective_to", DateTime(timezone=True)),
    Column("principal_id", Text, nullable=False),
    _is_identifier("affiliation_id", IdKind.AFFILIATION),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    CheckConstraint(
        "effective_to IS NULL OR effective_from IS NULL OR effective_to >= effective_from",
        name="an_affiliation_ends_after_it_starts",
    ),
    Index("relationship_affiliations_by_principal", "principal_id"),
)

relationship_evidence = Table(
    "relationship_evidence",
    METADATA,
    Column("evidence_id", Text, primary_key=True),
    Column(
        "person_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_people.person_id"),
        nullable=False,
    ),
    Column("authority", Text, nullable=False),
    Column("effective_at", DateTime(timezone=True)),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("principal_id", Text, nullable=False),
    _one_of("authority", EvidenceAuthority, name="relationship_evidence_authority_is_known"),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    Index("relationship_evidence_by_principal", "principal_id"),
)

relationship_evidence_observations = Table(
    "relationship_evidence_observations",
    METADATA,
    Column(
        "evidence_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_evidence.evidence_id"),
        nullable=False,
    ),
    Column(
        "observation_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_identity_observations.observation_id"),
        nullable=False,
    ),
    Column("principal_id", Text, nullable=False),
    PrimaryKeyConstraint("evidence_id", "observation_id"),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    Index("relationship_evidence_observations_by_principal", "principal_id"),
)

relationship_conversation_participants = Table(
    "relationship_conversation_participants",
    METADATA,
    Column("participant_id", Text, primary_key=True),
    Column(
        "conversation_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_conversations.conversation_id"),
        nullable=False,
    ),
    Column("person_id", Text, ForeignKey(f"{SCHEMA}.relationship_people.person_id")),
    Column(
        "unresolved_mention_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_unresolved_mentions.unresolved_mention_id"),
    ),
    CheckConstraint(
        "(person_id IS NULL) <> (unresolved_mention_id IS NULL)",
        name="a_conversation_participant_names_one_identity_target",
    ),
    Column("principal_id", Text, nullable=False),
    _is_identifier("participant_id", IdKind.CONVERSATION_PARTICIPANT),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    Index("relationship_conversation_participants_by_principal", "principal_id"),
    Index(
        "a_conversation_names_a_person_once",
        "conversation_id",
        "person_id",
        unique=True,
        postgresql_where=text("person_id IS NOT NULL"),
    ),
    Index(
        "a_conversation_names_an_unresolved_mention_once",
        "conversation_id",
        "unresolved_mention_id",
        unique=True,
        postgresql_where=text("unresolved_mention_id IS NOT NULL"),
    ),
)

relationship_conversation_observations = Table(
    "relationship_conversation_observations",
    METADATA,
    Column(
        "participant_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_conversation_participants.participant_id"),
        nullable=False,
    ),
    Column(
        "observation_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_identity_observations.observation_id"),
        nullable=False,
    ),
    Column("principal_id", Text, nullable=False),
    PrimaryKeyConstraint("participant_id", "observation_id"),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    Index("relationship_conversation_observations_by_principal", "principal_id"),
)

# WP-12 provider-neutral source evidence and native control plane. Provider
# locators occur only on account/bucket infrastructure rows; no domain value
# imported above carries one.
source_version_evidence = Table(
    "source_version_evidence",
    METADATA,
    Column("evidence_id", Text, primary_key=True),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_object_versions.version_id"),
        nullable=False,
    ),
    Column("evidence_kind", Text, nullable=False),
    Column("payload", LargeBinary, nullable=False),
    Column("payload_sha256", Text, nullable=False),
    Column("byte_count", BigInteger, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    _is_identifier("evidence_id", IdKind.SOURCE_EVIDENCE),
    CheckConstraint(
        "evidence_kind IN ('calendar_event', 'contact', 'mail_message')",
        name="source_evidence_kind_is_known",
    ),
    CheckConstraint(
        "payload_sha256 ~ '^[0-9a-f]{64}$'",
        name="source_evidence_digest_is_sha256",
    ),
    CheckConstraint(
        "byte_count = octet_length(payload)",
        name="source_evidence_byte_count_matches_payload",
    ),
    UniqueConstraint(
        "version_id",
        "evidence_kind",
        "payload_sha256",
        name="source_version_evidence_is_idempotent",
    ),
)

native_bridges = Table(
    "native_bridges",
    METADATA,
    Column("bridge_id", Text, primary_key=True),
    Column("protocol_version", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    _is_identifier("bridge_id", IdKind.NATIVE_BRIDGE),
    UniqueConstraint("protocol_version", "label", name="a_native_bridge_identity_is_stable"),
)

native_bridge_observations = Table(
    "native_bridge_observations",
    METADATA,
    Column("observation_id", Text, primary_key=True),
    Column("bridge_id", Text, ForeignKey(f"{SCHEMA}.native_bridges.bridge_id"), nullable=False),
    Column("available", Boolean, nullable=False),
    Column("protocol_version", Text, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("observation_id", IdKind.SOURCE_OBSERVATION),
)

native_source_accounts = Table(
    "native_source_accounts",
    METADATA,
    Column("account_id", Text, primary_key=True),
    Column("bridge_id", Text, ForeignKey(f"{SCHEMA}.native_bridges.bridge_id"), nullable=False),
    Column("source_id", Text, ForeignKey(f"{SCHEMA}.sources.source_id"), nullable=False),
    Column("source_kind", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("private_locator", Text, nullable=False),
    Column("first_observed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("account_id", IdKind.NATIVE_ACCOUNT),
    _one_of("source_kind", NativeSourceKind, name="native_account_source_kind_is_known"),
    UniqueConstraint(
        "bridge_id",
        "source_kind",
        "private_locator",
        name="native_account_locator_is_issued_once",
    ),
)

native_source_buckets = Table(
    "native_source_buckets",
    METADATA,
    Column("bucket_id", Text, primary_key=True),
    Column(
        "account_id",
        Text,
        ForeignKey(f"{SCHEMA}.native_source_accounts.account_id"),
        nullable=False,
    ),
    Column("parent_bucket_id", Text, ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id")),
    Column("source_kind", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("private_locator", Text, nullable=False),
    Column("selectable", Boolean, nullable=False),
    Column("first_observed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("bucket_id", IdKind.NATIVE_BUCKET),
    _one_of("source_kind", NativeSourceKind, name="native_bucket_source_kind_is_known"),
    CheckConstraint(
        "parent_bucket_id IS NULL OR parent_bucket_id <> bucket_id",
        name="a_native_bucket_cannot_parent_itself",
    ),
    UniqueConstraint(
        "account_id",
        "private_locator",
        name="native_bucket_locator_is_issued_once",
    ),
)

native_discovery_snapshots = Table(
    "native_discovery_snapshots",
    METADATA,
    Column("discovery_id", Text, primary_key=True),
    Column("bridge_id", Text, ForeignKey(f"{SCHEMA}.native_bridges.bridge_id"), nullable=False),
    Column("snapshot_sha256", Text, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("discovery_id", IdKind.NATIVE_DISCOVERY),
    CheckConstraint(
        "snapshot_sha256 ~ '^[0-9a-f]{64}$'",
        name="native_discovery_digest_is_sha256",
    ),
    UniqueConstraint(
        "bridge_id",
        "snapshot_sha256",
        name="native_discovery_snapshot_is_idempotent",
    ),
)

native_configuration_revisions = Table(
    "native_configuration_revisions",
    METADATA,
    Column("configuration_id", Text, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("bridge_id", Text, ForeignKey(f"{SCHEMA}.native_bridges.bridge_id"), nullable=False),
    Column("timezone_name", Text, nullable=False),
    Column("start_date", Date, nullable=False),
    Column("start_at", DateTime(timezone=True), nullable=False),
    Column("cutoff_at", DateTime(timezone=True), nullable=False),
    Column("calendar_horizon_at", DateTime(timezone=True), nullable=False),
    Column("selection_sha256", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    _is_identifier("configuration_id", IdKind.NATIVE_CONFIGURATION),
    CheckConstraint("revision >= 1", name="native_configuration_revision_starts_at_one"),
    CheckConstraint("start_at <= cutoff_at", name="native_configuration_range_is_ordered"),
    CheckConstraint(
        "calendar_horizon_at = cutoff_at + interval '90 days'",
        name="native_calendar_horizon_is_ninety_days",
    ),
    CheckConstraint(
        "selection_sha256 ~ '^[0-9a-f]{64}$'",
        name="native_configuration_selection_digest_is_sha256",
    ),
    PrimaryKeyConstraint("configuration_id", "revision"),
)

native_configuration_buckets = Table(
    "native_configuration_buckets",
    METADATA,
    Column("configuration_id", Text, nullable=False),
    Column("revision", Integer, nullable=False),
    Column(
        "bucket_id", Text, ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id"), nullable=False
    ),
    ForeignKeyConstraint(
        ["configuration_id", "revision"],
        [
            f"{SCHEMA}.native_configuration_revisions.configuration_id",
            f"{SCHEMA}.native_configuration_revisions.revision",
        ],
    ),
    PrimaryKeyConstraint("configuration_id", "revision", "bucket_id"),
)

native_preflight_observations = Table(
    "native_preflight_observations",
    METADATA,
    Column("observation_id", Text, primary_key=True),
    Column("configuration_id", Text, nullable=False),
    Column("configuration_revision", Integer, nullable=False),
    Column("bucket_id", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("failure", Text),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("observation_id", IdKind.SOURCE_OBSERVATION),
    ForeignKeyConstraint(
        ["configuration_id", "configuration_revision", "bucket_id"],
        [
            f"{SCHEMA}.native_configuration_buckets.configuration_id",
            f"{SCHEMA}.native_configuration_buckets.revision",
            f"{SCHEMA}.native_configuration_buckets.bucket_id",
        ],
        name="native_preflight_requires_selected_bucket",
    ),
    CheckConstraint(
        "state IN ('reachable', 'permission_denied', 'unavailable', 'identity_drift')",
        name="native_preflight_state_is_known",
    ),
    CheckConstraint(
        "failure IS NULL OR failure IN ('permission_denied', 'account_unavailable', "
        "'bucket_unavailable', 'transient_unavailable')",
        name="native_preflight_failure_is_known",
    ),
    CheckConstraint(
        "(state = 'reachable' AND failure IS NULL) OR "
        "(state = 'permission_denied' AND failure = 'permission_denied') OR "
        "(state = 'unavailable' AND failure IN "
        "('account_unavailable', 'bucket_unavailable', 'transient_unavailable')) OR "
        "(state = 'identity_drift' AND failure = 'bucket_unavailable')",
        name="native_preflight_state_and_failure_agree",
    ),
    Index(
        "native_preflight_latest_by_bucket",
        "configuration_id",
        "configuration_revision",
        "bucket_id",
        "observed_at",
    ),
)

native_admission_authorities = Table(
    "native_admission_authorities",
    METADATA,
    Column("authority_id", Text, primary_key=True),
    Column("audit_id", Text, ForeignKey(f"{SCHEMA}.audit_events.audit_id"), nullable=False),
    Column("configuration_id", Text, nullable=False),
    Column("configuration_revision", Integer, nullable=False),
    Column("bridge_id", Text, ForeignKey(f"{SCHEMA}.native_bridges.bridge_id"), nullable=False),
    Column("bucket_id", Text, nullable=False),
    Column("source_id", Text, ForeignKey(f"{SCHEMA}.sources.source_id"), nullable=False),
    Column("host_instance_id", Text, nullable=False),
    Column("envelope_id", Text, nullable=False),
    Column("request_id", Text, nullable=False),
    Column("issued_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True)),
    Column("admission_sha256", Text),
    _is_identifier("authority_id", IdKind.NATIVE_AUTHORITY),
    _is_identifier("host_instance_id", IdKind.NATIVE_BRIDGE),
    ForeignKeyConstraint(
        ["configuration_id", "configuration_revision", "bucket_id"],
        [
            f"{SCHEMA}.native_configuration_buckets.configuration_id",
            f"{SCHEMA}.native_configuration_buckets.revision",
            f"{SCHEMA}.native_configuration_buckets.bucket_id",
        ],
        name="native_authority_requires_selected_bucket",
    ),
    CheckConstraint("bridge_id = host_instance_id", name="native_authority_binds_host"),
    CheckConstraint("expires_at > issued_at", name="native_authority_has_positive_lifetime"),
    CheckConstraint(
        "expires_at <= issued_at + interval '10 minutes'",
        name="native_authority_lifetime_is_bounded",
    ),
    CheckConstraint(
        "length(envelope_id) BETWEEN 1 AND 200 AND length(request_id) BETWEEN 1 AND 200",
        name="native_authority_wire_ids_are_bounded",
    ),
    CheckConstraint(
        "(consumed_at IS NULL) = (admission_sha256 IS NULL)",
        name="native_authority_consumption_is_complete",
    ),
    CheckConstraint(
        "admission_sha256 IS NULL OR admission_sha256 ~ '^[0-9a-f]{64}$'",
        name="native_authority_admission_digest_is_sha256",
    ),
    UniqueConstraint("envelope_id", name="native_authority_envelope_is_issued_once"),
)

native_source_review_routes = Table(
    "native_source_review_routes",
    METADATA,
    Column(
        "source_version_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_object_versions.version_id"),
        nullable=False,
    ),
    Column(
        "proposal_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_proposals.proposal_id"),
        nullable=False,
        unique=True,
    ),
    Column(
        "review_case_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_review_cases.review_case_id"),
        nullable=False,
        unique=True,
    ),
    Column("routed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("source_version_id", IdKind.VERSION),
    _is_identifier("proposal_id", IdKind.PROPOSAL),
    _is_identifier("review_case_id", IdKind.REVIEW_CASE),
    PrimaryKeyConstraint("source_version_id", "proposal_id"),
)

native_sync_runs = Table(
    "native_sync_runs",
    METADATA,
    Column("run_id", Text, primary_key=True),
    Column("configuration_id", Text, nullable=False),
    Column("configuration_revision", Integer, nullable=False),
    Column("run_kind", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("start_at", DateTime(timezone=True), nullable=False),
    Column("cutoff_at", DateTime(timezone=True), nullable=False),
    Column("calendar_horizon_at", DateTime(timezone=True), nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    _is_identifier("run_id", IdKind.NATIVE_RUN),
    _one_of("run_kind", NativeRunKind, name="native_run_kind_is_known"),
    _one_of("state", NativeRunState, name="native_run_state_is_known"),
    ForeignKeyConstraint(
        ["configuration_id", "configuration_revision"],
        [
            f"{SCHEMA}.native_configuration_revisions.configuration_id",
            f"{SCHEMA}.native_configuration_revisions.revision",
        ],
    ),
    CheckConstraint("start_at <= cutoff_at", name="native_run_range_is_ordered"),
    CheckConstraint(
        "calendar_horizon_at = cutoff_at + interval '90 days'",
        name="native_run_calendar_horizon_is_ninety_days",
    ),
    UniqueConstraint(
        "configuration_id",
        "configuration_revision",
        "idempotency_key",
        name="native_sync_run_idempotency_is_scoped",
    ),
)

native_bucket_runs = Table(
    "native_bucket_runs",
    METADATA,
    Column("bucket_run_id", Text, primary_key=True),
    Column("run_id", Text, ForeignKey(f"{SCHEMA}.native_sync_runs.run_id"), nullable=False),
    Column(
        "bucket_id", Text, ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id"), nullable=False
    ),
    Column("state", Text, nullable=False),
    Column("item_count", BigInteger, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    _is_identifier("bucket_run_id", IdKind.NATIVE_BUCKET_RUN),
    _one_of("state", NativeRunState, name="native_bucket_run_state_is_known"),
    CheckConstraint("item_count >= 0", name="native_bucket_run_count_is_not_negative"),
    UniqueConstraint("run_id", "bucket_id", name="one_native_bucket_receipt_per_run"),
)

native_sync_jobs = Table(
    "native_sync_jobs",
    METADATA,
    Column("job_id", Text, primary_key=True),
    Column("configuration_id", Text, nullable=False),
    Column("configuration_revision", Integer, nullable=False),
    Column(
        "bucket_id", Text, ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id"), nullable=False
    ),
    Column("range_start", DateTime(timezone=True), nullable=False),
    Column("range_end", DateTime(timezone=True), nullable=False),
    Column("state", Text, nullable=False),
    Column("lease_owner", Text),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("idempotency_key", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    _is_identifier("job_id", IdKind.NATIVE_JOB),
    ForeignKeyConstraint(
        ["configuration_id", "configuration_revision"],
        [
            f"{SCHEMA}.native_configuration_revisions.configuration_id",
            f"{SCHEMA}.native_configuration_revisions.revision",
        ],
    ),
    ForeignKeyConstraint(
        ["configuration_id", "configuration_revision", "bucket_id"],
        [
            f"{SCHEMA}.native_configuration_buckets.configuration_id",
            f"{SCHEMA}.native_configuration_buckets.revision",
            f"{SCHEMA}.native_configuration_buckets.bucket_id",
        ],
        name="native_job_requires_selected_bucket",
    ),
    CheckConstraint(
        "state IN ('failed', 'queued', 'running', 'succeeded')",
        name="native_sync_job_state_is_known",
    ),
    CheckConstraint("range_start <= range_end", name="native_sync_job_range_is_ordered"),
    CheckConstraint(
        "(state = 'running') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
        name="a_native_job_is_running_exactly_while_leased",
    ),
    UniqueConstraint(
        "configuration_id",
        "configuration_revision",
        "bucket_id",
        "idempotency_key",
        name="native_sync_job_idempotency_is_scoped",
    ),
    Index(
        "one_active_native_lease_per_bucket_range",
        "bucket_id",
        "range_start",
        "range_end",
        unique=True,
        postgresql_where=text("state = 'running'"),
    ),
)

native_checkpoints = Table(
    "native_checkpoints",
    METADATA,
    Column("checkpoint_id", Text, primary_key=True),
    Column(
        "bucket_id", Text, ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id"), nullable=False
    ),
    Column("sequence", BigInteger, nullable=False),
    Column(
        "previous_checkpoint_id",
        Text,
        ForeignKey(f"{SCHEMA}.native_checkpoints.checkpoint_id"),
        unique=True,
    ),
    Column("cursor_private", Text, nullable=False),
    Column("cursor_digest", Text, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    _is_identifier("checkpoint_id", IdKind.NATIVE_CHECKPOINT),
    CheckConstraint("sequence >= 1", name="native_checkpoint_sequence_starts_at_one"),
    CheckConstraint(
        "(sequence = 1) = (previous_checkpoint_id IS NULL)",
        name="native_checkpoint_predecessor_matches_sequence",
    ),
    CheckConstraint(
        "cursor_digest ~ '^[0-9a-f]{64}$'",
        name="native_checkpoint_digest_is_sha256",
    ),
    UniqueConstraint("bucket_id", "sequence", name="native_checkpoint_sequence_is_monotonic"),
)

source_observations = Table(
    "source_observations",
    METADATA,
    Column("observation_id", Text, primary_key=True),
    Column(
        "source_object_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_objects.source_object_id"),
        nullable=False,
    ),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_object_versions.version_id"),
        nullable=False,
    ),
    Column(
        "bucket_id", Text, ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id"), nullable=False
    ),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("observation_id", IdKind.SOURCE_OBSERVATION),
    UniqueConstraint(
        "version_id",
        "bucket_id",
        name="source_version_observation_is_idempotent",
    ),
)

source_memberships = Table(
    "source_memberships",
    METADATA,
    Column("membership_id", Text, primary_key=True),
    Column(
        "parent_bucket_id",
        Text,
        ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id"),
        nullable=False,
    ),
    Column(
        "source_object_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_objects.source_object_id"),
        nullable=False,
    ),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_object_versions.version_id"),
        nullable=False,
    ),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("membership_id", IdKind.SOURCE_MEMBERSHIP),
    UniqueConstraint(
        "parent_bucket_id",
        "version_id",
        name="source_membership_version_is_idempotent",
    ),
)

native_watcher_simulations = Table(
    "native_watcher_simulations",
    METADATA,
    Column("simulation_id", Text, nullable=False),
    Column("sequence", Integer, nullable=False),
    Column(
        "bucket_id", Text, ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id"), nullable=False
    ),
    Column("state", Text, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    _is_identifier("simulation_id", IdKind.NATIVE_SIMULATION),
    _one_of("state", WatcherSimulationState, name="native_simulation_state_is_known"),
    CheckConstraint("sequence >= 1", name="native_simulation_sequence_starts_at_one"),
    PrimaryKeyConstraint("simulation_id", "sequence"),
)

native_simulation_receipts = Table(
    "native_simulation_receipts",
    METADATA,
    Column("receipt_id", Text, primary_key=True),
    Column("simulation_id", Text, nullable=False),
    Column("simulation_sequence", Integer, nullable=False),
    Column(
        "checkpoint_id",
        Text,
        ForeignKey(f"{SCHEMA}.native_checkpoints.checkpoint_id"),
        nullable=False,
    ),
    Column("terminal_state", Text, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    _is_identifier("receipt_id", IdKind.NATIVE_SIMULATION_RECEIPT),
    ForeignKeyConstraint(
        ["simulation_id", "simulation_sequence"],
        [
            f"{SCHEMA}.native_watcher_simulations.simulation_id",
            f"{SCHEMA}.native_watcher_simulations.sequence",
        ],
    ),
    CheckConstraint(
        "terminal_state IN ('simulation_complete', 'simulation_failed')",
        name="native_simulation_receipt_state_is_terminal",
    ),
    UniqueConstraint("simulation_id", name="one_receipt_per_native_simulation"),
)

native_live_activation_gates = Table(
    "native_live_activation_gates",
    METADATA,
    Column("gate_id", Text, primary_key=True),
    Column(
        "bucket_id", Text, ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id"), nullable=False
    ),
    Column("state", Text, nullable=False),
    Column("reason_code", Text, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    _is_identifier("gate_id", IdKind.NATIVE_LIVE_GATE),
    _one_of("state", LiveActivationGateState, name="native_live_gate_state_is_known"),
    UniqueConstraint("bucket_id", name="one_native_live_gate_per_bucket"),
)

# ---------------------------------------------------------------------------
# WP-06 (R5): the relationship / project continuity surface.
#
# These seven tables are the runtime declarations for the surface migration
# `d2e3f4a5b6c7` creates with frozen literals. Every table carries
# `principal_id` (NOT NULL, opaque-identifier CHECK, principal-first index)
# because Today/Pulse and the relationship/project briefing read them and each
# read must be strictly principal-scoped — the partition is present from the
# first row (invariant 11: `principal_id` is a mandatory predicate on every read
# path). `frames` and `project_situations` carry `principal_id` explicitly even
# though they inherit it from their parent, so a query can enforce the partition
# without joining back — the same reasoning the WP-05 review span tables used.
# The declarations mirror the revision's DDL so the applied schema matches what
# `to_metadata` builds (the schema-parity invariant).
# ---------------------------------------------------------------------------

#: `Situation`: a purposeful operational context that *references* one or more
#: objects (via `object_refs`) but does not own them. `object_refs` is a JSONB
#: array of opaque object identifiers, not foreign keys — a Situation points at
#: objects across planes without taking ownership of their lifetime. The closed
#: CHECK ties `closed_at` to the terminal `state`: a closed Situation records
#: when it closed, and an open one has no closing time.
situations = Table(
    "situations",
    METADATA,
    Column("situation_id", Text, primary_key=True),
    Column("principal_id", Text, nullable=False),
    Column("title", Text, nullable=False),
    Column("description", Text),
    Column("state", Text, nullable=False, server_default=text("'open'")),
    Column("object_refs", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("opened_at", DateTime(timezone=True), nullable=False),
    Column("closed_at", DateTime(timezone=True)),
    Column("outcome", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    _is_identifier("situation_id", IdKind.SITUATION),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    CheckConstraint("length(trim(title)) > 0", name="a_situation_title_is_not_blank"),
    _one_of("state", SituationState, name="a_situation_state_is_known"),
    CheckConstraint(
        "(state = 'closed') = (closed_at IS NOT NULL)",
        name="a_closed_situation_records_when_it_closed",
    ),
    Index("situations_by_principal", "principal_id"),
    Index("situations_by_principal_state", "principal_id", "state"),
)

#: `Frame`: the current or saved view *within* a Situation of what matters — the
#: evidence, alternatives, obligations, uncertainty, and the next authority
#: point. `situation_id` is a foreign key to the Situation the Frame frames;
#: `principal_id` is carried explicitly so the partition holds without the join.
frames = Table(
    "frames",
    METADATA,
    Column("frame_id", Text, primary_key=True),
    Column(
        "situation_id",
        Text,
        ForeignKey(f"{SCHEMA}.situations.situation_id"),
        nullable=False,
    ),
    Column("principal_id", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("evidence_refs", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("alternatives", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("obligations", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("uncertainty", Text),
    Column("next_authority", Text),
    Column("state", Text, nullable=False, server_default=text("'current'")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    _is_identifier("frame_id", IdKind.FRAME),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    CheckConstraint("length(trim(label)) > 0", name="a_frame_label_is_not_blank"),
    _one_of("state", FrameState, name="a_frame_state_is_known"),
    Index("frames_by_principal", "principal_id"),
    Index("frames_by_principal_situation", "principal_id", "situation_id"),
)

#: `Trace`: a derived, source-linked temporal reconstruction for one object over
#: a time range, recording the source events it reconstructed (`source_events`)
#: and the gaps it exposed (`gaps`). A Trace is a projection, never source
#: evidence. The range CHECK admits an open-ended or unanchored range but never
#: one that ends before it starts.
traces = Table(
    "traces",
    METADATA,
    Column("trace_id", Text, primary_key=True),
    Column("principal_id", Text, nullable=False),
    Column("object_id", Text, nullable=False),
    Column("object_type", Text, nullable=False),
    Column("time_range_start", DateTime(timezone=True)),
    Column("time_range_end", DateTime(timezone=True)),
    Column("source_events", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("gaps", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("created_at", DateTime(timezone=True), nullable=False),
    _is_identifier("trace_id", IdKind.TRACE),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    CheckConstraint("length(trim(object_type)) > 0", name="a_trace_object_type_is_not_blank"),
    CheckConstraint(
        "time_range_end IS NULL OR time_range_start IS NULL OR time_range_end >= time_range_start",
        name="a_trace_range_ends_after_it_starts",
    ),
    Index("traces_by_principal", "principal_id"),
    Index("traces_by_principal_object", "principal_id", "object_id"),
)

#: `Project`: a durable work context with participants that groups Situations.
#: `participants` is a JSONB array of person/identity references. The closed
#: CHECK ties `closed_at` to the terminal `state`, as `situations` does.
projects = Table(
    "projects",
    METADATA,
    Column("project_id", Text, primary_key=True),
    Column("principal_id", Text, nullable=False),
    Column("name", Text, nullable=False),
    Column("description", Text),
    Column("state", Text, nullable=False, server_default=text("'active'")),
    Column("participants", JSONB, nullable=False, server_default=text("'[]'::jsonb")),
    Column("opened_at", DateTime(timezone=True), nullable=False),
    Column("closed_at", DateTime(timezone=True)),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    _is_identifier("project_id", IdKind.PROJECT),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    CheckConstraint("length(trim(name)) > 0", name="a_project_name_is_not_blank"),
    _one_of("state", ProjectState, name="a_project_state_is_known"),
    CheckConstraint(
        "(state = 'closed') = (closed_at IS NOT NULL)",
        name="a_closed_project_records_when_it_closed",
    ),
    Index("projects_by_principal", "principal_id"),
    Index("projects_by_principal_state", "principal_id", "state"),
)

#: `project_situations`: the link table binding a Project to the Situations it
#: contains, unique per (project, situation) so a Situation links to a Project
#: at most once. `principal_id` is carried explicitly for the same partition
#: reason the span tables carry it.
project_situations = Table(
    "project_situations",
    METADATA,
    Column("project_situation_id", Text, primary_key=True),
    Column(
        "project_id",
        Text,
        ForeignKey(f"{SCHEMA}.projects.project_id"),
        nullable=False,
    ),
    Column(
        "situation_id",
        Text,
        ForeignKey(f"{SCHEMA}.situations.situation_id"),
        nullable=False,
    ),
    Column("principal_id", Text, nullable=False),
    Column("linked_at", DateTime(timezone=True), nullable=False),
    _is_identifier("project_situation_id", IdKind.PROJECT_SITUATION),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    UniqueConstraint("project_id", "situation_id", name="a_situation_links_to_a_project_once"),
    Index("project_situations_by_principal", "principal_id"),
)

#: `relationship_events`: a time/context-aware association event on a Person's
#: relationship timeline. `accepted` gates whether Today/Pulse may read the
#: event, so an unaccepted (proposed) event never surfaces as an accepted
#: timeline fact (invariant 5: no timeline entry presents a proposal as
#: accepted). The principal-and-accepted index serves the accepted-only read.
relationship_events = Table(
    "relationship_events",
    METADATA,
    Column("event_id", Text, primary_key=True),
    Column("principal_id", Text, nullable=False),
    Column(
        "person_id",
        Text,
        ForeignKey(f"{SCHEMA}.relationship_people.person_id"),
        nullable=False,
    ),
    Column("event_type", Text, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("context", Text),
    Column("accepted", Boolean, nullable=False, server_default=text("false")),
    Column("source_ref", Text),
    Column("created_at", DateTime(timezone=True), nullable=False),
    _is_identifier("event_id", IdKind.RELATIONSHIP_EVENT),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    _one_of("event_type", RelationshipEventType, name="a_relationship_event_type_is_known"),
    Index("relationship_events_by_principal", "principal_id"),
    Index("relationship_events_by_principal_person", "principal_id", "person_id"),
    Index("relationship_events_by_principal_accepted", "principal_id", "accepted"),
)

#: `pulse_items`: derived attention recommendations with a reason, a
#: consequence, and a next step. `accepted_only` defaults TRUE and the
#: `pulse_reads_only_accepted_records` CHECK pins it TRUE, encoding the WP-06
#: acceptance criterion "Today/Pulse read only accepted records": a Pulse item
#: is generated only from accepted state, and the schema refuses to store one
#: that claims otherwise. `priority` is a bounded 1..10 rank.
pulse_items = Table(
    "pulse_items",
    METADATA,
    Column("pulse_id", Text, primary_key=True),
    Column("principal_id", Text, nullable=False),
    Column("item_type", Text, nullable=False),
    Column("item_ref", Text, nullable=False),
    Column("reason", Text, nullable=False),
    Column("consequence", Text),
    Column("next_step", Text),
    Column("priority", Integer, nullable=False, server_default=text("5")),
    Column("accepted_only", Boolean, nullable=False, server_default=text("true")),
    Column("generated_at", DateTime(timezone=True), nullable=False),
    Column("dismissed_at", DateTime(timezone=True)),
    _is_identifier("pulse_id", IdKind.PULSE),
    _is_identifier("principal_id", IdKind.PRINCIPAL),
    _one_of("item_type", PulseItemType, name="a_pulse_item_type_is_known"),
    CheckConstraint("length(trim(item_ref)) > 0", name="a_pulse_item_ref_is_not_blank"),
    CheckConstraint("length(trim(reason)) > 0", name="a_pulse_reason_is_not_blank"),
    CheckConstraint("priority BETWEEN 1 AND 10", name="a_pulse_priority_is_bounded"),
    CheckConstraint("accepted_only IS TRUE", name="pulse_reads_only_accepted_records"),
    Index("pulse_items_by_principal", "principal_id"),
    Index("pulse_items_by_principal_dismissed", "principal_id", "dismissed_at"),
)

# WP-12 provider-neutral source evidence and native control plane. Provider
# locators occur only on account/bucket infrastructure rows; no domain value
# imported above carries one.
source_version_evidence = Table(
    "source_version_evidence",
    METADATA,
    Column("evidence_id", Text, primary_key=True),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_object_versions.version_id"),
        nullable=False,
    ),
    Column("evidence_kind", Text, nullable=False),
    Column("payload", LargeBinary, nullable=False),
    Column("payload_sha256", Text, nullable=False),
    Column("byte_count", BigInteger, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    _is_identifier("evidence_id", IdKind.SOURCE_EVIDENCE),
    CheckConstraint(
        "evidence_kind IN ('calendar_event', 'contact', 'mail_message')",
        name="source_evidence_kind_is_known",
    ),
    CheckConstraint(
        "payload_sha256 ~ '^[0-9a-f]{64}$'",
        name="source_evidence_digest_is_sha256",
    ),
    CheckConstraint(
        "byte_count = octet_length(payload)",
        name="source_evidence_byte_count_matches_payload",
    ),
    UniqueConstraint(
        "version_id",
        "evidence_kind",
        "payload_sha256",
        name="source_version_evidence_is_idempotent",
    ),
)

native_bridges = Table(
    "native_bridges",
    METADATA,
    Column("bridge_id", Text, primary_key=True),
    Column("protocol_version", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    _is_identifier("bridge_id", IdKind.NATIVE_BRIDGE),
    UniqueConstraint("protocol_version", "label", name="a_native_bridge_identity_is_stable"),
)

native_bridge_observations = Table(
    "native_bridge_observations",
    METADATA,
    Column("observation_id", Text, primary_key=True),
    Column("bridge_id", Text, ForeignKey(f"{SCHEMA}.native_bridges.bridge_id"), nullable=False),
    Column("available", Boolean, nullable=False),
    Column("protocol_version", Text, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("observation_id", IdKind.SOURCE_OBSERVATION),
)

native_source_accounts = Table(
    "native_source_accounts",
    METADATA,
    Column("account_id", Text, primary_key=True),
    Column("bridge_id", Text, ForeignKey(f"{SCHEMA}.native_bridges.bridge_id"), nullable=False),
    Column("source_id", Text, ForeignKey(f"{SCHEMA}.sources.source_id"), nullable=False),
    Column("source_kind", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("private_locator", Text, nullable=False),
    Column("first_observed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("account_id", IdKind.NATIVE_ACCOUNT),
    _one_of("source_kind", NativeSourceKind, name="native_account_source_kind_is_known"),
    UniqueConstraint(
        "bridge_id",
        "source_kind",
        "private_locator",
        name="native_account_locator_is_issued_once",
    ),
)

native_source_buckets = Table(
    "native_source_buckets",
    METADATA,
    Column("bucket_id", Text, primary_key=True),
    Column(
        "account_id",
        Text,
        ForeignKey(f"{SCHEMA}.native_source_accounts.account_id"),
        nullable=False,
    ),
    Column("parent_bucket_id", Text, ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id")),
    Column("source_kind", Text, nullable=False),
    Column("label", Text, nullable=False),
    Column("private_locator", Text, nullable=False),
    Column("selectable", Boolean, nullable=False),
    Column("first_observed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("bucket_id", IdKind.NATIVE_BUCKET),
    _one_of("source_kind", NativeSourceKind, name="native_bucket_source_kind_is_known"),
    CheckConstraint(
        "parent_bucket_id IS NULL OR parent_bucket_id <> bucket_id",
        name="a_native_bucket_cannot_parent_itself",
    ),
    UniqueConstraint(
        "account_id",
        "private_locator",
        name="native_bucket_locator_is_issued_once",
    ),
)

native_discovery_snapshots = Table(
    "native_discovery_snapshots",
    METADATA,
    Column("discovery_id", Text, primary_key=True),
    Column("bridge_id", Text, ForeignKey(f"{SCHEMA}.native_bridges.bridge_id"), nullable=False),
    Column("snapshot_sha256", Text, nullable=False),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("discovery_id", IdKind.NATIVE_DISCOVERY),
    CheckConstraint(
        "snapshot_sha256 ~ '^[0-9a-f]{64}$'",
        name="native_discovery_digest_is_sha256",
    ),
    UniqueConstraint(
        "bridge_id",
        "snapshot_sha256",
        name="native_discovery_snapshot_is_idempotent",
    ),
)

native_configuration_revisions = Table(
    "native_configuration_revisions",
    METADATA,
    Column("configuration_id", Text, nullable=False),
    Column("revision", Integer, nullable=False),
    Column("bridge_id", Text, ForeignKey(f"{SCHEMA}.native_bridges.bridge_id"), nullable=False),
    Column("timezone_name", Text, nullable=False),
    Column("start_date", Date, nullable=False),
    Column("start_at", DateTime(timezone=True), nullable=False),
    Column("cutoff_at", DateTime(timezone=True), nullable=False),
    Column("calendar_horizon_at", DateTime(timezone=True), nullable=False),
    Column("selection_sha256", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    _is_identifier("configuration_id", IdKind.NATIVE_CONFIGURATION),
    CheckConstraint("revision >= 1", name="native_configuration_revision_starts_at_one"),
    CheckConstraint("start_at <= cutoff_at", name="native_configuration_range_is_ordered"),
    CheckConstraint(
        "calendar_horizon_at = cutoff_at + interval '90 days'",
        name="native_calendar_horizon_is_ninety_days",
    ),
    CheckConstraint(
        "selection_sha256 ~ '^[0-9a-f]{64}$'",
        name="native_configuration_selection_digest_is_sha256",
    ),
    PrimaryKeyConstraint("configuration_id", "revision"),
)

native_configuration_buckets = Table(
    "native_configuration_buckets",
    METADATA,
    Column("configuration_id", Text, nullable=False),
    Column("revision", Integer, nullable=False),
    Column(
        "bucket_id", Text, ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id"), nullable=False
    ),
    ForeignKeyConstraint(
        ["configuration_id", "revision"],
        [
            f"{SCHEMA}.native_configuration_revisions.configuration_id",
            f"{SCHEMA}.native_configuration_revisions.revision",
        ],
    ),
    PrimaryKeyConstraint("configuration_id", "revision", "bucket_id"),
)

native_preflight_observations = Table(
    "native_preflight_observations",
    METADATA,
    Column("observation_id", Text, primary_key=True),
    Column("configuration_id", Text, nullable=False),
    Column("configuration_revision", Integer, nullable=False),
    Column("bucket_id", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("failure", Text),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("observation_id", IdKind.SOURCE_OBSERVATION),
    ForeignKeyConstraint(
        ["configuration_id", "configuration_revision", "bucket_id"],
        [
            f"{SCHEMA}.native_configuration_buckets.configuration_id",
            f"{SCHEMA}.native_configuration_buckets.revision",
            f"{SCHEMA}.native_configuration_buckets.bucket_id",
        ],
        name="native_preflight_requires_selected_bucket",
    ),
    CheckConstraint(
        "state IN ('reachable', 'permission_denied', 'unavailable', 'identity_drift')",
        name="native_preflight_state_is_known",
    ),
    CheckConstraint(
        "failure IS NULL OR failure IN ('permission_denied', 'account_unavailable', "
        "'bucket_unavailable', 'transient_unavailable')",
        name="native_preflight_failure_is_known",
    ),
    CheckConstraint(
        "(state = 'reachable' AND failure IS NULL) OR "
        "(state = 'permission_denied' AND failure = 'permission_denied') OR "
        "(state = 'unavailable' AND failure IN "
        "('account_unavailable', 'bucket_unavailable', 'transient_unavailable')) OR "
        "(state = 'identity_drift' AND failure = 'bucket_unavailable')",
        name="native_preflight_state_and_failure_agree",
    ),
    Index(
        "native_preflight_latest_by_bucket",
        "configuration_id",
        "configuration_revision",
        "bucket_id",
        "observed_at",
    ),
)

native_admission_authorities = Table(
    "native_admission_authorities",
    METADATA,
    Column("authority_id", Text, primary_key=True),
    Column("audit_id", Text, ForeignKey(f"{SCHEMA}.audit_events.audit_id"), nullable=False),
    Column("configuration_id", Text, nullable=False),
    Column("configuration_revision", Integer, nullable=False),
    Column("bridge_id", Text, ForeignKey(f"{SCHEMA}.native_bridges.bridge_id"), nullable=False),
    Column("bucket_id", Text, nullable=False),
    Column("source_id", Text, ForeignKey(f"{SCHEMA}.sources.source_id"), nullable=False),
    Column("host_instance_id", Text, nullable=False),
    Column("envelope_id", Text, nullable=False),
    Column("request_id", Text, nullable=False),
    Column("issued_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("consumed_at", DateTime(timezone=True)),
    Column("admission_sha256", Text),
    Column("checkpoint_job_id", Text, ForeignKey(f"{SCHEMA}.native_sync_jobs.job_id")),
    Column("checkpoint_run_id", Text, ForeignKey(f"{SCHEMA}.native_sync_runs.run_id")),
    Column("checkpoint_cursor_private", Text),
    Column("checkpoint_cursor_digest", Text),
    Column("checkpoint_terminal", Boolean),
    Column("checkpoint_item_count", Integer),
    _is_identifier("authority_id", IdKind.NATIVE_AUTHORITY),
    _is_identifier("host_instance_id", IdKind.NATIVE_BRIDGE),
    ForeignKeyConstraint(
        ["configuration_id", "configuration_revision", "bucket_id"],
        [
            f"{SCHEMA}.native_configuration_buckets.configuration_id",
            f"{SCHEMA}.native_configuration_buckets.revision",
            f"{SCHEMA}.native_configuration_buckets.bucket_id",
        ],
        name="native_authority_requires_selected_bucket",
    ),
    CheckConstraint("bridge_id = host_instance_id", name="native_authority_binds_host"),
    CheckConstraint("expires_at > issued_at", name="native_authority_has_positive_lifetime"),
    CheckConstraint(
        "expires_at <= issued_at + interval '10 minutes'",
        name="native_authority_lifetime_is_bounded",
    ),
    CheckConstraint(
        "length(envelope_id) BETWEEN 1 AND 200 AND length(request_id) BETWEEN 1 AND 200",
        name="native_authority_wire_ids_are_bounded",
    ),
    CheckConstraint(
        "(consumed_at IS NULL) = (admission_sha256 IS NULL)",
        name="native_authority_consumption_is_complete",
    ),
    CheckConstraint(
        "admission_sha256 IS NULL OR admission_sha256 ~ '^[0-9a-f]{64}$'",
        name="native_authority_admission_digest_is_sha256",
    ),
    CheckConstraint(
        "(checkpoint_job_id IS NULL AND checkpoint_run_id IS NULL "
        "AND checkpoint_cursor_private IS NULL AND checkpoint_cursor_digest IS NULL "
        "AND checkpoint_terminal IS NULL AND checkpoint_item_count IS NULL) OR "
        "(checkpoint_job_id IS NOT NULL AND checkpoint_run_id IS NOT NULL "
        "AND checkpoint_cursor_private IS NOT NULL AND checkpoint_cursor_digest IS NOT NULL "
        "AND checkpoint_terminal IS NOT NULL AND checkpoint_item_count IS NOT NULL)",
        name="native_authority_checkpoint_binding_is_complete",
    ),
    CheckConstraint(
        "checkpoint_cursor_private IS NULL OR length(checkpoint_cursor_private) BETWEEN 1 AND 512",
        name="native_authority_checkpoint_cursor_is_bounded",
    ),
    CheckConstraint(
        "checkpoint_cursor_digest IS NULL OR checkpoint_cursor_digest ~ '^[0-9a-f]{64}$'",
        name="native_authority_checkpoint_digest_is_sha256",
    ),
    CheckConstraint(
        f"checkpoint_terminal IS NULL OR "
        f"(checkpoint_terminal AND checkpoint_cursor_private = "
        f"'{NATIVE_BASELINE_TERMINAL_CURSOR}') OR "
        f"(NOT checkpoint_terminal AND checkpoint_cursor_private <> "
        f"'{NATIVE_BASELINE_TERMINAL_CURSOR}')",
        name="native_authority_checkpoint_terminal_matches_cursor",
    ),
    CheckConstraint(
        f"checkpoint_item_count IS NULL OR checkpoint_item_count BETWEEN 0 AND "
        f"{NATIVE_SOURCE_MAX_PAGE_SIZE}",
        name="native_authority_checkpoint_count_is_page_bounded",
    ),
    UniqueConstraint("envelope_id", name="native_authority_envelope_is_issued_once"),
)

native_source_review_routes = Table(
    "native_source_review_routes",
    METADATA,
    Column(
        "source_version_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_object_versions.version_id"),
        nullable=False,
    ),
    Column(
        "proposal_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_proposals.proposal_id"),
        nullable=False,
        unique=True,
    ),
    Column(
        "review_case_id",
        Text,
        ForeignKey(f"{SCHEMA}.capture_review_cases.review_case_id"),
        nullable=False,
        unique=True,
    ),
    Column("routed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("source_version_id", IdKind.VERSION),
    _is_identifier("proposal_id", IdKind.PROPOSAL),
    _is_identifier("review_case_id", IdKind.REVIEW_CASE),
    PrimaryKeyConstraint("source_version_id", "proposal_id"),
)

native_sync_runs = Table(
    "native_sync_runs",
    METADATA,
    Column("run_id", Text, primary_key=True),
    Column("configuration_id", Text, nullable=False),
    Column("configuration_revision", Integer, nullable=False),
    Column("run_kind", Text, nullable=False),
    Column("state", Text, nullable=False),
    Column("start_at", DateTime(timezone=True), nullable=False),
    Column("cutoff_at", DateTime(timezone=True), nullable=False),
    Column("calendar_horizon_at", DateTime(timezone=True), nullable=False),
    Column("idempotency_key", Text, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("bridge_id", Text, ForeignKey(f"{SCHEMA}.native_bridges.bridge_id"), nullable=False),
    Column("adapter_identity", Text, nullable=False),
    _is_identifier("run_id", IdKind.NATIVE_RUN),
    _one_of("run_kind", NativeRunKind, name="native_run_kind_is_known"),
    _one_of("state", NativeRunState, name="native_run_state_is_known"),
    ForeignKeyConstraint(
        ["configuration_id", "configuration_revision"],
        [
            f"{SCHEMA}.native_configuration_revisions.configuration_id",
            f"{SCHEMA}.native_configuration_revisions.revision",
        ],
    ),
    CheckConstraint("start_at <= cutoff_at", name="native_run_range_is_ordered"),
    CheckConstraint(
        "adapter_identity ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$'",
        name="native_run_adapter_identity_is_bounded",
    ),
    CheckConstraint(
        "calendar_horizon_at = cutoff_at + interval '90 days'",
        name="native_run_calendar_horizon_is_ninety_days",
    ),
    UniqueConstraint(
        "configuration_id",
        "configuration_revision",
        "idempotency_key",
        name="native_sync_run_idempotency_is_scoped",
    ),
)

native_bucket_runs = Table(
    "native_bucket_runs",
    METADATA,
    Column("bucket_run_id", Text, primary_key=True),
    Column("run_id", Text, ForeignKey(f"{SCHEMA}.native_sync_runs.run_id"), nullable=False),
    Column(
        "bucket_id", Text, ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id"), nullable=False
    ),
    Column("state", Text, nullable=False),
    Column("item_count", BigInteger, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    _is_identifier("bucket_run_id", IdKind.NATIVE_BUCKET_RUN),
    _one_of("state", NativeRunState, name="native_bucket_run_state_is_known"),
    CheckConstraint("item_count >= 0", name="native_bucket_run_count_is_not_negative"),
    UniqueConstraint("run_id", "bucket_id", name="one_native_bucket_receipt_per_run"),
)

native_sync_jobs = Table(
    "native_sync_jobs",
    METADATA,
    Column("job_id", Text, primary_key=True),
    Column("configuration_id", Text, nullable=False),
    Column("configuration_revision", Integer, nullable=False),
    Column(
        "bucket_id", Text, ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id"), nullable=False
    ),
    Column("range_start", DateTime(timezone=True), nullable=False),
    Column("range_end", DateTime(timezone=True), nullable=False),
    Column("state", Text, nullable=False),
    Column("lease_owner", Text),
    Column("lease_expires_at", DateTime(timezone=True)),
    Column("idempotency_key", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
    Column("run_id", Text, ForeignKey(f"{SCHEMA}.native_sync_runs.run_id")),
    Column("read_mode", Text, nullable=False),
    _is_identifier("job_id", IdKind.NATIVE_JOB),
    ForeignKeyConstraint(
        ["configuration_id", "configuration_revision"],
        [
            f"{SCHEMA}.native_configuration_revisions.configuration_id",
            f"{SCHEMA}.native_configuration_revisions.revision",
        ],
    ),
    ForeignKeyConstraint(
        ["configuration_id", "configuration_revision", "bucket_id"],
        [
            f"{SCHEMA}.native_configuration_buckets.configuration_id",
            f"{SCHEMA}.native_configuration_buckets.revision",
            f"{SCHEMA}.native_configuration_buckets.bucket_id",
        ],
        name="native_job_requires_selected_bucket",
    ),
    CheckConstraint(
        "state IN ('failed', 'queued', 'running', 'succeeded')",
        name="native_sync_job_state_is_known",
    ),
    CheckConstraint("range_start <= range_end", name="native_sync_job_range_is_ordered"),
    CheckConstraint(
        "read_mode IN ('bounded_time', 'current_inventory')",
        name="native_sync_job_read_mode_is_known",
    ),
    CheckConstraint(
        "(state = 'running') = (lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)",
        name="a_native_job_is_running_exactly_while_leased",
    ),
    UniqueConstraint(
        "configuration_id",
        "configuration_revision",
        "bucket_id",
        "idempotency_key",
        name="native_sync_job_idempotency_is_scoped",
    ),
    Index(
        "one_active_native_lease_per_bucket_range",
        "bucket_id",
        "range_start",
        "range_end",
        unique=True,
        postgresql_where=text("state = 'running'"),
    ),
)

native_checkpoints = Table(
    "native_checkpoints",
    METADATA,
    Column("checkpoint_id", Text, primary_key=True),
    Column(
        "bucket_id", Text, ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id"), nullable=False
    ),
    Column("sequence", BigInteger, nullable=False),
    Column(
        "previous_checkpoint_id",
        Text,
        ForeignKey(f"{SCHEMA}.native_checkpoints.checkpoint_id"),
        unique=True,
    ),
    Column("cursor_private", Text, nullable=False),
    Column("cursor_digest", Text, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    Column("job_id", Text, ForeignKey(f"{SCHEMA}.native_sync_jobs.job_id")),
    Column(
        "admission_authority_id",
        Text,
        ForeignKey(f"{SCHEMA}.native_admission_authorities.authority_id"),
        unique=True,
    ),
    Column("terminal", Boolean, nullable=False),
    Column("item_count", Integer, nullable=False),
    _is_identifier("checkpoint_id", IdKind.NATIVE_CHECKPOINT),
    CheckConstraint("sequence >= 1", name="native_checkpoint_sequence_starts_at_one"),
    CheckConstraint(
        "(sequence = 1) = (previous_checkpoint_id IS NULL)",
        name="native_checkpoint_predecessor_matches_sequence",
    ),
    CheckConstraint(
        "cursor_digest ~ '^[0-9a-f]{64}$'",
        name="native_checkpoint_digest_is_sha256",
    ),
    CheckConstraint(
        f"item_count BETWEEN 0 AND {NATIVE_SOURCE_MAX_PAGE_SIZE}",
        name="native_checkpoint_item_count_is_page_bounded",
    ),
    UniqueConstraint("bucket_id", "sequence", name="native_checkpoint_sequence_is_monotonic"),
)

source_observations = Table(
    "source_observations",
    METADATA,
    Column("observation_id", Text, primary_key=True),
    Column(
        "source_object_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_objects.source_object_id"),
        nullable=False,
    ),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_object_versions.version_id"),
        nullable=False,
    ),
    Column(
        "bucket_id", Text, ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id"), nullable=False
    ),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("observation_id", IdKind.SOURCE_OBSERVATION),
    UniqueConstraint(
        "version_id",
        "bucket_id",
        name="source_version_observation_is_idempotent",
    ),
)

source_memberships = Table(
    "source_memberships",
    METADATA,
    Column("membership_id", Text, primary_key=True),
    Column(
        "parent_bucket_id",
        Text,
        ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id"),
        nullable=False,
    ),
    Column(
        "source_object_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_objects.source_object_id"),
        nullable=False,
    ),
    Column(
        "version_id",
        Text,
        ForeignKey(f"{SCHEMA}.source_object_versions.version_id"),
        nullable=False,
    ),
    Column("observed_at", DateTime(timezone=True), nullable=False),
    _is_identifier("membership_id", IdKind.SOURCE_MEMBERSHIP),
    UniqueConstraint(
        "parent_bucket_id",
        "version_id",
        name="source_membership_version_is_idempotent",
    ),
)

native_watcher_simulations = Table(
    "native_watcher_simulations",
    METADATA,
    Column("simulation_id", Text, nullable=False),
    Column("sequence", Integer, nullable=False),
    Column(
        "bucket_id", Text, ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id"), nullable=False
    ),
    Column("state", Text, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    _is_identifier("simulation_id", IdKind.NATIVE_SIMULATION),
    _one_of("state", WatcherSimulationState, name="native_simulation_state_is_known"),
    CheckConstraint("sequence >= 1", name="native_simulation_sequence_starts_at_one"),
    PrimaryKeyConstraint("simulation_id", "sequence"),
)

native_simulation_receipts = Table(
    "native_simulation_receipts",
    METADATA,
    Column("receipt_id", Text, primary_key=True),
    Column("simulation_id", Text, nullable=False),
    Column("simulation_sequence", Integer, nullable=False),
    Column(
        "checkpoint_id",
        Text,
        ForeignKey(f"{SCHEMA}.native_checkpoints.checkpoint_id"),
        nullable=False,
    ),
    Column("terminal_state", Text, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    _is_identifier("receipt_id", IdKind.NATIVE_SIMULATION_RECEIPT),
    ForeignKeyConstraint(
        ["simulation_id", "simulation_sequence"],
        [
            f"{SCHEMA}.native_watcher_simulations.simulation_id",
            f"{SCHEMA}.native_watcher_simulations.sequence",
        ],
    ),
    CheckConstraint(
        "terminal_state IN ('simulation_complete', 'simulation_failed')",
        name="native_simulation_receipt_state_is_terminal",
    ),
    UniqueConstraint("simulation_id", name="one_receipt_per_native_simulation"),
)

native_live_activation_gates = Table(
    "native_live_activation_gates",
    METADATA,
    Column("gate_id", Text, primary_key=True),
    Column(
        "bucket_id", Text, ForeignKey(f"{SCHEMA}.native_source_buckets.bucket_id"), nullable=False
    ),
    Column("state", Text, nullable=False),
    Column("reason_code", Text, nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
    _is_identifier("gate_id", IdKind.NATIVE_LIVE_GATE),
    _one_of("state", LiveActivationGateState, name="native_live_gate_state_is_known"),
    UniqueConstraint("bucket_id", name="one_native_live_gate_per_bucket"),
)
