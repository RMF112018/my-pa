"""The `knowledge` schema: configured sources, observed objects, enrollment, jobs.

This is the application's own schema and it is deliberately not any of the ones
that already exist. The eight domain schemas hold the migrated legacy corpus and
are read-only history. `migration_control` is a ledger for one migration run:
reusing it would make an enrollment retry indistinguishable from a migration
retry in the same tables, and would put application code on the write path of
migration governance state. Two planes with different lifetimes, different
writers, and different authority do not share a schema.

Four concerns, five tables, and nothing else. There is no outbox, no scheduler,
no priority column, no soft-delete flag, and no audit mirror: each of those
would be a mechanism with no caller, and `AGENTS.md` section 2 rules them out
until one exists.

Nothing here stores content. `native_root` and `native_locator` are the only
provider-native values in the schema, they exist because an opaque identifier
has to resolve back to something, and no domain type carries either of them.
Everything else is an opaque identifier, an enumerated code, a bounded token, or
a count.

The tables are declared once here and used by both the Alembic revision that
creates them and the modules that write to them, so the schema applied and the
schema assumed cannot drift apart.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from sqlalchemy import (
    ARRAY,
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Table,
    Text,
    UniqueConstraint,
    func,
)

from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.classification import Classification
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


def _one_of(column: str, values: type[StrEnum]) -> CheckConstraint:
    literals = ", ".join(f"'{member.value}'" for member in values)
    return CheckConstraint(f"{column} IN ({literals})", name=f"{column}_is_known")


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
