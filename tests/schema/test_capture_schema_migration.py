"""The capture revision round-trips, and the frozen vocabulary stays frozen.

This module is the guard on the mechanism `D-69` chose, and it exists because
that mechanism deliberately broke something. Until WP-6, `audit_events`'
`capability_is_known` and `purpose_is_known` were *derived* from the domain
enums, so the database and the domain could not drift — at the cost of an
already-merged revision emitting different DDL every time a member was added,
which is the `D-48` hazard in a new shape and was measured rather than argued.
The derivation is now frozen inside `9c6b4a18ed72` and widened forward by an
explicit `ALTER` here. What that costs is the coupling, and `_IDENTIFIER_SUFFIX` in `tables.py` is
the precedent for what replaces it: **a restatement is acceptable when it is
a checked claim rather than a copy that can drift.** These are the checks.

Six claims, separated because they fail for different reasons.

**The revision is in the chain.** Deliberately not "is the head", for the reason
`test_the_audit_revision_is_in_the_chain_on_the_extraction_revision` in
`test_audit_schema_migration.py` records: that property is true only until the
next revision is written, and asserting it makes every later work package edit
this file.

**Empty to head and head to empty.** What `AGENTS.md` section 6 requires of a
schema change, plus the two things this revision adds that a table drop does not
take with it — a trigger function in the `knowledge` schema, and two constraints
on a table it did not create. `7e5a1fb93d62` drops the schema with `RESTRICT`,
so a function left behind fails `downgrade base` at a revision that has no idea
this one exists.

**Stopping at `9c6b4a18ed72` emits the frozen eight and seven.** This is the
whole argument for editing a merged migration: after the edit that revision
emits what it emitted on the day it merged, with twenty-nine capabilities and thirteen
purposes now declared in the domain. If this reddens, the freeze has been undone
and every database at that revision has stopped agreeing with what the chain
says it should hold.

**Head admits exactly the domain's vocabulary.** The checked claim that replaces
the coupling — and it covers **every** enum-backed closed set the chain emits,
not the two WP-6 widened; `CHECKED_VOCABULARY` is that list and a revision that
freezes a set adds to it. Checking `capability` and `purpose` alone, which
is where the first pass left it, replaced the coupling on two constraints and
replaced it with nothing on the rest: `audit_outcome_is_known` and
`denial_reason_is_known` sit on the same table in the same revision, and the
independent reviewer measured a planted `DenialReason` member changing what that
already-merged revision emits with nothing reddening anywhere. A member added
without an `ALTER` — the failure `D-69` exists to prevent, and the one no other
test could catch because every test builds its database from scratch — now fails
here for any of them.

**The two nullable error-code sets.** `jobs.last_error_code` and
`capture_jobs.last_error_code` are `... IS NULL OR ... IN (…)`, so they need
their own read; they track the eleven public `v1` codes.

The database is disposable, created and dropped by its fixture, and never the
configured one: `downgrade base` deletes schemas, and pointing that at the
canonical `my_pa` database would destroy the migrated corpus. Every value here is
synthetic; no path exists and none is opened.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.audit.events import AuditOutcome
from my_pa.domain.capture.assertion import AssertionState
from my_pa.domain.capture.classification import CaptureLabel, EntityType, ResolutionState
from my_pa.domain.capture.context import (
    ContextLinkAuthority,
    ContextLinkRole,
    ContextLinkTarget,
)
from my_pa.domain.capture.pipeline import PipelineStage, ProcessingState
from my_pa.domain.capture.proposal import (
    ProposalField,
    ProposalMethod,
    ProposalQuarantineReason,
    ProposalState,
    ProposalType,
    RiskClass,
)
from my_pa.domain.capture.review import Disposition
from my_pa.domain.capture.span import OffsetBasis, SpanRole
from my_pa.domain.capture.submission import (
    AdmissionResult,
    CaptureMethod,
    CaptureTransport,
    TrustState,
)
from my_pa.domain.capture.version import ProcessingPolicy
from my_pa.domain.common.classification import Classification
from my_pa.domain.conversation.event import ConversationChannel, ConversationState
from my_pa.domain.identity.operation import Capability, NativeSourceCapability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import DenialReason
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.capture_search import SEARCH_CONFIG, SEARCH_INDEX
from my_pa.infrastructure.persistence.tables import JobState

ROOT = Path(__file__).resolve().parents[2]

SCHEMA = "knowledge"

CAPTURE_REVISION = "1a4c9e77b2d5"
PROPOSAL_REVISION = "2b7e9f4c1a83"
ENROLLMENT_OBJECTS_REVISION = "af3d35efb9c0"
AUDIT_REVISION = "9c6b4a18ed72"

#: Fixed name so a run interrupted before teardown is cleaned up by the next
#: one. Distinct from every other suite's disposable database, so they cannot
#: collide — the database tier runs serially and these names are server-global.
DISPOSABLE_DATABASE = "my_pa_capture_test"

#: The five tables this revision creates, restated. A table added to the
#: revision has to be acknowledged here, which is the point.
CAPTURE_TABLES: Final[frozenset[str]] = frozenset(
    {
        "captures",
        "capture_versions",
        "capture_receipts",
        "capture_submissions",
        "capture_jobs",
    }
)

#: The seven tables `2b7e9f4c1a83` creates, restated for the same reason the
#: five above are: a table added to that revision has to be acknowledged here.
PROPOSAL_TABLES: Final[frozenset[str]] = frozenset(
    {
        "capture_processing_text",
        "capture_stage_results",
        "capture_spans",
        "capture_proposals",
        "capture_proposal_spans",
        "capture_classifications",
        "capture_entity_mentions",
    }
)

#: The capability vocabulary `1a4c9e77b2d5` emitted on the day it merged, and
#: which it must still emit now that `2b7e9f4c1a83` has widened head past it.
#: Written out rather than derived, exactly as `FROZEN_CAPABILITIES` is: a test
#: that read the revision's own literal would pass however that literal changed.
CAPABILITIES_AT_THE_CAPTURE_REVISION: Final[frozenset[str]] = frozenset(
    {
        "capabilities.get",
        "capture.create",
        "capture.list",
        "capture.read",
        "capture.revise",
        "knowledge.read",
        "knowledge.search",
        "sources.enroll",
        "sources.fetch",
        "sources.list",
        "sources.metadata",
        "sources.status",
    }
)

#: Exact delta between the frozen capture revision and the current head. This is
#: historical migration evidence, so it is intentionally literal rather than
#: derived from either live domain enum.
CAPABILITIES_ADDED_AFTER_THE_CAPTURE_REVISION: Final[frozenset[str]] = frozenset(
    {
        "capture.search",
        "review.decide",
        "review.list",
        "native_sources.backfill",
        "native_sources.configure",
        "native_sources.disable",
        "native_sources.discover",
        "native_sources.pause",
        "native_sources.preflight",
        "native_sources.reconcile",
        "native_sources.resume",
        "native_sources.retry",
        "native_sources.status",
        "native_sources.sync",
        # WP-9. `5e2c7b0a94f6` is the forward `ALTER` that admits it.
        "knowledge.reveal",
        # WP-11. `8f2b6c4d1a37` is the forward `ALTER` that admits the trio below.
        "continuity.projects",
        "continuity.pulse",
        "continuity.situations",
        # WP-23. `2d9f4a7c1e58` is the forward `ALTER` that admits it.
        "knowledge.coverage",
        # WP-28. `6b3d9a2f8c14` is the forward `ALTER` that admits the plane, and
        # the same revision widens `purpose_is_known` for the pair they map to.
        "documents.archive",
        "documents.create",
        "documents.list",
        "documents.read",
        "documents.restore",
        "documents.revise",
        # Continuity authoring. `7c2e9b4a1d80` is the forward `ALTER` that admits
        # the three explicit create names.
        "continuity.projects.create",
        "continuity.situations.create",
        "continuity.tasks.create",
    }
)

#: The vocabulary `9c6b4a18ed72` emitted on the day it merged. Written out here
#: as well as in the revision, and that duplication is deliberate: a test that
#: imported the revision's own literal would pass however that literal changed,
#: which is the one thing this module exists to notice.
FROZEN_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "capabilities.get",
        "knowledge.read",
        "knowledge.search",
        "sources.enroll",
        "sources.fetch",
        "sources.list",
        "sources.metadata",
        "sources.status",
    }
)

FROZEN_PURPOSES: Final[frozenset[str]] = frozenset(
    {
        "bounded_enrollment",
        "content_extraction",
        "knowledge_read",
        "knowledge_search",
        "security_validation",
        "source_inspection",
        "status_observation",
    }
)

#: The other two closed sets `9c6b4a18ed72` emits. Unchanged since it merged, so
#: these are equal to the live enums today — which is exactly why they were the
#: two the first pass at this freeze left derived, and why the strict-subset
#: guard below cannot be extended to them. They are held by
#: `test_no_revision_derives_a_closed_set_from_an_enum.py`, which reads the
#: revision's frozen declaration structurally rather than by value.
FROZEN_AUDIT_OUTCOMES: Final[frozenset[str]] = frozenset({"allowed", "denied", "failed"})

FROZEN_DENIAL_REASONS: Final[frozenset[str]] = frozenset(
    {
        "destination_not_eligible",
        "operator_required",
        "principal_may_not_hold_authority",
        "principal_not_authenticated",
        "purpose_not_permitted_for_capability",
        "scope_not_authorized",
    }
)

#: The function and the trigger that make `capture_versions` append only.
IMMUTABILITY_FUNCTION = "capture_versions_stay_as_written"
IMMUTABILITY_TRIGGER = "capture_versions_are_append_only"

#: What `3c8f1e2a5b74` admits that the domain has not declared yet, and it is a
#: disclosed gap rather than a mistake.
#:
#: `D-81`'s rule is that the forward `ALTER` is written **before** the member,
#: because a member with no `ALTER` leaves every test green — every test builds
#: its database from scratch — and is refused by the stored constraint on the
#: first audited operation in the field. That revision therefore carries
#: `review.list`, `review.decide` and `review_disposition` already. The members
#: themselves cannot be declared in the same change: `adapters/mcp/tools` builds
#: its tool list at import from `Capability` and indexes `application.commands`
#: by each member's `capability`, so a member with no command raises `KeyError`
#: at import. The member, its command and its handler are one indivisible change.
#:
#: The gap is one-directional and the assertion below says so. A constraint
#: **wider** than the domain refuses nothing the product can write; a domain
#: wider than the constraint is the failure `D-69` exists to prevent, and the
#: equality in `CHECKED_VOCABULARY` still catches it, because a member added with
#: no `ALTER` would be in the left side and not the right.
CAPABILITIES_ADMITTED_AHEAD_OF_THE_DOMAIN: Final[frozenset[str]] = frozenset()

PURPOSES_ADMITTED_AHEAD_OF_THE_DOMAIN: Final[frozenset[str]] = frozenset()

HEAD_CAPABILITIES_DECLARED_BY_DOMAIN: Final[frozenset[str]] = frozenset(
    capability.value
    for capability_type in (Capability, NativeSourceCapability)
    for capability in capability_type
)

#: The thirteen triggers `3c8f1e2a5b74` installs. Four sit on tables it does not
#: create, which is what forward DDL is for: a trigger is not a `Table`
#: attribute, so it changes nothing an already-merged revision emits.
REVIEW_TRIGGERS: Final[frozenset[str]] = frozenset(
    {
        "an_assertion_cites_at_least_one_span",
        "a_span_link_leaves_its_assertion_cited",
        "an_accepted_proposal_names_a_real_assertion",
        "capture_proposals_are_never_deleted",
        "capture_proposals_updates_are_governed",
        "capture_spans_stay_immutable",
        "capture_proposal_spans_stay_immutable",
        "capture_review_cases_stay_immutable",
        "capture_review_decisions_stay_immutable",
        "capture_assertions_are_never_deleted",
        "capture_assertions_updates_are_governed",
        "capture_assertion_spans_stay_immutable",
        "capture_promotion_receipts_stay_immutable",
    }
)

#: The triggers the relationship-identity revision adds above this one. This is
#: explicit so a new trigger cannot disappear into a value derived from the
#: migration under test.
RELATIONSHIP_TRIGGERS: Final[frozenset[str]] = frozenset(
    {
        "identity_review_requires_candidates",
        "identity_resolution_requires_review",
        "identity_resolution_requires_exact_observations",
        "zz_identity_corrections_require_complete_final_state",
        "canonical_person_requires_resolution",
        "person_merge_requires_resolution",
        "observation_link_requires_current_resolution",
        "identity_resolutions_are_append_only",
        "relationship_organizations_are_append_only",
        "identity_observations_are_append_only",
        "unresolved_mentions_are_append_only",
        "identity_candidate_sets_are_append_only",
        "identity_candidate_members_are_append_only",
        "identity_review_cases_are_append_only",
        "identity_review_decisions_are_append_only",
        "resolution_observations_are_append_only",
        "relationship_evidence_is_governed",
        "relationship_evidence_observations_are_append_only",
        "relationship_aliases_match_observations",
        "relationship_affiliations_match_observations",
        "conversation_support_matches_participant",
        "conversation_participant_changes_are_governed",
        "conversation_participants_remain_supported",
        "conversation_observations_remain_supported",
        "observation_link_keeps_participants_supported",
    }
)

#: The exact native-source trigger inventory added above this revision. Restated
#: here so the global equality remains sensitive to both missing and unexpected
#: triggers while this test continues to prove its original span-trigger claim.
NATIVE_SOURCE_TRIGGERS: Final[frozenset[str]] = frozenset(
    {
        "source_version_evidence_is_append_only",
        "native_bridge_observations_is_append_only",
        "native_discovery_snapshots_is_append_only",
        "native_configuration_revisions_is_append_only",
        "native_configuration_buckets_is_append_only",
        "native_sync_runs_is_append_only",
        "native_bucket_runs_is_append_only",
        "native_checkpoints_is_append_only",
        "source_observations_is_append_only",
        "source_memberships_is_append_only",
        "native_watcher_simulations_is_append_only",
        "native_simulation_receipts_is_append_only",
        "native_live_activation_gates_is_append_only",
        "native_checkpoint_requires_current_predecessor",
        "native_simulation_requires_closed_transition",
        "native_configuration_requires_bucket",
        "native_configuration_bucket_matches_seal",
        "source_observation_requires_matching_version",
        "source_membership_requires_matching_contact_version",
        "source_evidence_requires_matching_object_kind",
        "native_account_requires_matching_provider",
        "native_bucket_requires_account_and_parent_scope",
        "native_bucket_run_requires_selected_bucket",
        "native_simulation_receipt_requires_exact_evidence",
        "native_run_requires_exact_frozen_inputs",
        "native_authority_allows_one_exact_consumption",
        "native_job_requires_exact_frozen_run",
        "native_checkpoint_requires_admitted_page",
    }
)

#: WP-27's two append-only triggers, on the managed-document plane's version and
#: lifecycle tables. Neither is deferred: they refuse an `UPDATE` or a `DELETE`
#: outright rather than at commit, and there is no multi-statement invariant for
#: them to wait for.
MANAGED_DOCUMENT_TRIGGERS: Final = (
    "managed_document_versions_are_append_only",
    "managed_document_lifecycle_is_append_only",
)

_CONSTRAINT = text(
    "SELECT pg_get_constraintdef(con.oid) FROM pg_constraint con "
    "JOIN pg_class rel ON rel.oid = con.conrelid "
    "JOIN pg_namespace n ON n.oid = rel.relnamespace "
    "WHERE n.nspname = :schema AND rel.relname = :table AND con.conname = :name"
)

#: Every closed-set constraint this chain emits from a declaration that a domain
#: enum also feeds, with the enum head must agree with. Checking two of these —
#: which is where the first pass left it — replaced the enum-to-CHECK coupling on
#: `capability` and `purpose` and replaced it with *nothing* on the other ten.
#: `audit_outcome_is_known` and `denial_reason_is_known` were the two the
#: independent reviewer measured as still live; the eight on the capture tables
#: are this package's own, and are frozen in `1a4c9e77b2d5` for the same reason.
#:
#: The `last_error_code` constraints are excluded deliberately: their column is
#: nullable, so `_admitted` cannot read a bare value set out of
#: `last_error_code IS NULL OR last_error_code IN (…)` without also parsing the
#: null branch. `test_the_public_error_codes_are_admitted_at_head` below covers
#: them by asking the server directly instead.
CHECKED_VOCABULARY: Final[tuple[tuple[str, str, frozenset[str]], ...]] = (
    (
        "audit_events",
        "capability_is_known",
        HEAD_CAPABILITIES_DECLARED_BY_DOMAIN | CAPABILITIES_ADMITTED_AHEAD_OF_THE_DOMAIN,
    ),
    (
        "audit_events",
        "purpose_is_known",
        frozenset(p.value for p in Purpose) | PURPOSES_ADMITTED_AHEAD_OF_THE_DOMAIN,
    ),
    ("audit_events", "audit_outcome_is_known", frozenset(o.value for o in AuditOutcome)),
    ("audit_events", "denial_reason_is_known", frozenset(d.value for d in DenialReason)),
    (
        "capture_versions",
        "capture_classification_is_known",
        frozenset(c.value for c in Classification),
    ),
    (
        "capture_versions",
        "processing_policy_is_known",
        frozenset(p.value for p in ProcessingPolicy),
    ),
    (
        "capture_submissions",
        "capture_transport_is_known",
        frozenset(t.value for t in CaptureTransport),
    ),
    ("capture_submissions", "capture_method_is_known", frozenset(m.value for m in CaptureMethod)),
    ("capture_submissions", "capture_trust_state_is_known", frozenset(t.value for t in TrustState)),
    (
        "capture_submissions",
        "admission_result_is_known",
        frozenset(a.value for a in AdmissionResult),
    ),
    ("capture_jobs", "capture_job_state_is_known", frozenset(s.value for s in JobState)),
    # The thirteen `2b7e9f4c1a83` freezes, on the same terms and for the same
    # reason: each is restated as a literal inside that revision, so the
    # enum-to-CHECK coupling it broke is replaced by this claim rather than by
    # nothing.
    ("capture_stage_results", "capture_stage_is_known", frozenset(s.value for s in PipelineStage)),
    (
        "capture_stage_results",
        "capture_processing_state_is_known",
        frozenset(s.value for s in ProcessingState),
    ),
    ("capture_spans", "span_offset_basis_is_known", frozenset(b.value for b in OffsetBasis)),
    ("capture_spans", "span_role_is_known", frozenset(r.value for r in SpanRole)),
    ("capture_proposals", "proposal_type_is_known", frozenset(t.value for t in ProposalType)),
    ("capture_proposals", "proposal_state_is_known", frozenset(s.value for s in ProposalState)),
    ("capture_proposals", "proposal_risk_class_is_known", frozenset(r.value for r in RiskClass)),
    ("capture_proposals", "proposal_method_is_known", frozenset(m.value for m in ProposalMethod)),
    (
        "capture_proposals",
        "proposal_quarantine_reason_is_known",
        frozenset(r.value for r in ProposalQuarantineReason),
    ),
    (
        "capture_proposals",
        "a_missing_required_field_is_a_required_field",
        frozenset(f.value for f in ProposalField),
    ),
    (
        "capture_classifications",
        "capture_label_is_known",
        frozenset(label.value for label in CaptureLabel),
    ),
    (
        "capture_entity_mentions",
        "mention_entity_type_is_known",
        frozenset(e.value for e in EntityType),
    ),
    (
        "capture_entity_mentions",
        "mention_resolution_state_is_known",
        frozenset(r.value for r in ResolutionState),
    ),
    # The eight `3c8f1e2a5b74` freezes, on the same terms as the thirteen above.
    # `assertion_type_is_known` admits the same seven as `proposal_type_is_known`
    # and is a different constraint on a different table in a different revision:
    # an assertion carries its proposal's type forward, and both are frozen where
    # they are emitted, so neither tracks `ProposalType`.
    (
        "capture_review_decisions",
        "review_disposition_is_known",
        frozenset(d.value for d in Disposition),
    ),
    ("capture_assertions", "assertion_type_is_known", frozenset(t.value for t in ProposalType)),
    ("capture_assertions", "assertion_state_is_known", frozenset(s.value for s in AssertionState)),
    (
        "capture_context_links",
        "context_link_target_type_is_known",
        frozenset(t.value for t in ContextLinkTarget),
    ),
    (
        "capture_context_links",
        "context_link_role_is_known",
        frozenset(r.value for r in ContextLinkRole),
    ),
    (
        "capture_context_links",
        "context_link_authority_state_is_known",
        frozenset(a.value for a in ContextLinkAuthority),
    ),
    (
        "capture_conversations",
        "conversation_event_state_is_known",
        frozenset(s.value for s in ConversationState),
    ),
    (
        "capture_conversations",
        "conversation_channel_is_known",
        frozenset(c.value for c in ConversationChannel),
    ),
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def test_the_capture_revision_is_in_the_chain_on_the_enrollment_objects_revision() -> None:
    """Guards the rest of this module: an absent revision would create nothing."""
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert CAPTURE_REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(CAPTURE_REVISION).down_revision == ENROLLMENT_OBJECTS_REVISION


def test_the_frozen_vocabulary_is_a_strict_subset_of_the_domains() -> None:
    """Guard the two literals above: equal sets would make the stop-at test vacuous.

    If the domain ever shrank back to the historical eight, "the revision emits
    the frozen eight" and "the revision emits whatever the enum says" would be
    the same assertion, and the test below would pass on a re-coupled revision.
    This is what says the two are distinguishable at all.
    """
    assert {c.value for c in Capability} > FROZEN_CAPABILITIES
    assert {p.value for p in Purpose} > FROZEN_PURPOSES
    assert len(FROZEN_CAPABILITIES) == 8
    assert len(FROZEN_PURPOSES) == 7


def test_the_schema_ahead_gap_closed_when_wp8_declared_its_three_names() -> None:
    """The `D-81` ordering gap is empty now that WP-8 declares all three names.

    `3c8f1e2a5b74` carried the forward `ALTER` first. Emptying these constants
    restores plain head equality; a later schema-ahead change must deliberately
    reopen and explain the gap rather than inheriting WP-8's exception.
    """
    assert frozenset() == CAPABILITIES_ADMITTED_AHEAD_OF_THE_DOMAIN
    assert frozenset() == PURPOSES_ADMITTED_AHEAD_OF_THE_DOMAIN
    assert {c.value for c in Capability} and {p.value for p in Purpose}


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
        # CREATE and DROP DATABASE cannot run inside a transaction block.
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[arg-type]

    try:
        _administer(drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
        yield url
    finally:
        _administer(drop)
        maintenance.dispose()


def _admitted(engine: Engine, constraint: str, table: str = "audit_events") -> frozenset[str]:
    """The values one closed-set constraint admits.

    Read out of the *server* rather than out of the revision, and parsed from
    `pg_get_constraintdef`, so this is what a row would actually be checked
    against rather than what the file that wrote it says.
    """
    with engine.connect() as connection:
        definition = connection.execute(
            _CONSTRAINT, {"schema": SCHEMA, "table": table, "name": constraint}
        ).scalar_one()
    return frozenset(re.findall(r"'([^']+)'::text", str(definition)))


def _tables(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
                ),
                {"schema": SCHEMA},
            ).scalars()
        )


@pytest.mark.database
def test_stopping_at_the_audit_revision_emits_the_frozen_vocabulary(
    disposable_database: str,
) -> None:
    """The whole argument for editing a merged migration, as an assertion.

    A database taken to `9c6b4a18ed72` and no further receives the eight
    capabilities and seven purposes that revision emitted when it merged — not
    the twelve and nine the domain declares today. Reddening here means an
    already-merged revision has started denoting a second schema, which is what
    `D-48` refuses and what the standing rule in that file forbids.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), AUDIT_REVISION)

        assert _admitted(engine, "capability_is_known") == FROZEN_CAPABILITIES
        assert _admitted(engine, "purpose_is_known") == FROZEN_PURPOSES
        # The other two closed sets on the same table, in the same revision.
        # These are the ones the independent reviewer measured as still derived
        # after the first pass at this freeze: a planted `DenialReason` member
        # changed what an already-merged revision emitted, and nothing reddened.
        # They are frozen literals now, and this is what says so against a
        # server rather than against the file that wrote them.
        assert _admitted(engine, "audit_outcome_is_known") == FROZEN_AUDIT_OUTCOMES
        assert _admitted(engine, "denial_reason_is_known") == FROZEN_DENIAL_REASONS
        # The control: the capture tables do not exist yet, so the four sets
        # above are the state of a database that stopped short of this package
        # rather than one that ran it and was then narrowed.
        assert not CAPTURE_TABLES & _tables(engine)

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_head_admits_exactly_the_vocabulary_the_domain_declares(
    disposable_database: str,
) -> None:
    """The checked claim that replaces the coupling `D-69` broke.

    Equality in both directions and against both enums. A capability added to
    the domain without an `ALTER` fails the first half; an `ALTER` that widened
    the constraint past the domain fails the second. No existing test could
    catch the first, because every test builds its database from scratch and a
    fresh database used to receive whatever the enum said.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")

        for table, constraint, expected in CHECKED_VOCABULARY:
            assert _admitted(engine, constraint, table) == expected, f"{table}.{constraint}"
        # The control, in the same test: the four `audit_events` sets are not all
        # equal to each other, so eleven passing equalities cannot be one
        # equality repeated eleven times against a `_admitted` that returned the
        # same thing every time.
        assert len({values for _, _, values in CHECKED_VOCABULARY}) >= 8

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_the_public_error_codes_are_admitted_at_head(
    disposable_database: str,
) -> None:
    """The two nullable closed sets, which `_admitted` cannot read plainly.

    `jobs.last_error_code` and `capture_jobs.last_error_code` are constrained by
    `... IS NULL OR ... IN (…)`, and both track `ErrorCode`. The capture one is
    frozen in `1a4c9e77b2d5`; the `jobs` one is `D-81` allowlist row 5, still
    derived and deliberately not edited here. Both must admit the eleven public
    codes at head, and this asserts it against the server so that a twelfth code
    added without a migration is caught rather than assumed.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")

        codes = {code.value for code in ErrorCode}
        assert len(codes) == 11
        assert _admitted(engine, "last_error_code_is_a_public_error_code", "jobs") == codes
        assert (
            _admitted(engine, "capture_job_error_code_is_a_public_error_code", "capture_jobs")
            == codes
        )

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_the_capture_revision_runs_empty_to_head_and_head_to_empty(
    disposable_database: str,
) -> None:
    """Reversible, and reversible including what a table drop does not take.

    The trigger goes with its table. The trigger *function* does not, and
    `7e5a1fb93d62` drops the schema with `RESTRICT`, so a function left behind
    makes `downgrade base` fail at a revision written before this one existed.
    The residue check is therefore on routines and schemas, not only on tables.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")

        assert _tables(engine) >= CAPTURE_TABLES
        with engine.connect() as connection:
            triggers = set(
                connection.execute(
                    text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
                ).scalars()
            )
            routines = set(
                connection.execute(
                    text(
                        "SELECT p.proname FROM pg_proc p JOIN pg_namespace n "
                        "ON n.oid = p.pronamespace WHERE n.nspname = :schema"
                    ),
                    {"schema": SCHEMA},
                ).scalars()
            )
        assert IMMUTABILITY_TRIGGER in triggers
        assert IMMUTABILITY_FUNCTION in routines

        command.downgrade(_config(), "base")

        with engine.connect() as connection:
            remaining = set(connection.execute(text("SELECT nspname FROM pg_namespace")).scalars())
            left = set(
                connection.execute(
                    text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
                ).scalars()
            )
        assert SCHEMA not in remaining
        assert left == set()
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrading_this_revision_restores_the_previous_vocabulary(
    disposable_database: str,
) -> None:
    """A downgrade puts the constraint back to what the revision below denotes.

    Not to what the domain says today, which is the trap: reading the enum on
    the way down would leave a database at `af3d35efb9c0` holding a constraint
    that revision never described, which is the same defect as the one this
    package fixed, pointed the other way.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert _admitted(engine, "capability_is_known") == (
            HEAD_CAPABILITIES_DECLARED_BY_DOMAIN | CAPABILITIES_ADMITTED_AHEAD_OF_THE_DOMAIN
        )

        command.downgrade(_config(), ENROLLMENT_OBJECTS_REVISION)

        assert _admitted(engine, "capability_is_known") == FROZEN_CAPABILITIES
        assert _admitted(engine, "purpose_is_known") == FROZEN_PURPOSES
        assert not CAPTURE_TABLES & _tables(engine)
        # The control: the tables the revisions below created are still there, so
        # the downgrade removed this revision's work and not the schema.
        assert len(_tables(engine)) == 10

        command.upgrade(_config(), "head")
        assert _tables(engine) >= CAPTURE_TABLES

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_stopping_at_the_capture_revision_emits_the_twelve_it_merged_with(
    disposable_database: str,
) -> None:
    """`D-91`, as an assertion against a server rather than as an argument.

    A database taken to `1a4c9e77b2d5` and no further receives the capability
    vocabulary that revision emitted on the day it merged, not the one the
    domain declares now — and head receives the current one. Both halves are here
    because either alone is satisfied by a chain that never widened anything:
    the first by a freeze that also froze head, and the second by a revision
    that re-derived from the enum.

    **This is the assertion that catches a capability added without an `ALTER`,
    and no other test can.** Every test builds its database from scratch, so a
    further member with no forward `ALTER` leaves every one of them green and is
    refused by the stored constraint on the first audited request in the field.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), CAPTURE_REVISION)
        assert _admitted(engine, "capability_is_known") == CAPABILITIES_AT_THE_CAPTURE_REVISION
        assert not PROPOSAL_TABLES & _tables(engine)

        command.upgrade(_config(), "head")
        admitted_at_head = (
            HEAD_CAPABILITIES_DECLARED_BY_DOMAIN | CAPABILITIES_ADMITTED_AHEAD_OF_THE_DOMAIN
        )
        assert _admitted(engine, "capability_is_known") == admitted_at_head
        assert _tables(engine) >= PROPOSAL_TABLES
        # The two vocabularies differ by exactly the capability WP-7 added and
        # the two WP-8 capabilities widened by `3c8f1e2a5b74`, so the equality
        # above is a measurement rather than a tautology. The schema-ahead gap
        # is empty now that WP-8 has declared both names in the domain.
        assert (
            admitted_at_head - CAPABILITIES_AT_THE_CAPTURE_REVISION
            == CAPABILITIES_ADDED_AFTER_THE_CAPTURE_REVISION
        )

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_head_indexes_capture_text_with_the_configuration_the_predicate_uses(
    disposable_database: str,
) -> None:
    """The index and the predicate are one decision recorded in two files.

    PostgreSQL matches a functional index by expression tree, so a mismatch
    between the configuration the revision wrote and the one
    `persistence.capture_search` compiles **breaks silently**: the query drops
    to a sequential scan and still returns correct rows. Reading the stored
    definition back is what makes the equality checked.

    The control is the second assertion: the extraction plane's index is built
    over `english`, so "the definition names a configuration" is not satisfied
    by every index in the schema.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.connect() as connection:
            definitions = dict(
                connection.execute(
                    text(
                        "SELECT i.relname, pg_get_indexdef(x.indexrelid) FROM pg_index x "
                        "JOIN pg_class i ON i.oid = x.indexrelid "
                        "JOIN pg_class c ON c.oid = x.indrelid "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname = :schema"
                    ),
                    {"schema": SCHEMA},
                ).all()
            )
        capture_index = definitions[SEARCH_INDEX]
        assert f"to_tsvector('{SEARCH_CONFIG}'::regconfig, content)" in capture_index
        assert "USING gin" in capture_index
        assert f"'{SEARCH_CONFIG}'::regconfig" not in definitions["extractions_full_text"]

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_the_span_cardinality_triggers_are_deferred_and_leave_no_residue(
    disposable_database: str,
) -> None:
    """`D-98`, both halves: the trigger is deferred, and its function reverses.

    `7e5a1fb93d62` drops the schema with `RESTRICT`, so a `CREATE FUNCTION` this
    revision leaves behind fails `downgrade base` at a revision written before
    it existed — the failure `1a4c9e77b2d5` had to add an explicit `DROP
    FUNCTION` for. Two triggers share one function here, so there are two
    dependencies to drop and one function to drop after them.

    `DEFERRABLE INITIALLY DEFERRED` is asserted from the stored definition, not
    from the file: a constraint trigger checked per statement would refuse the
    proposal insert that precedes its own link rows, so the deferral is what
    makes the rule expressible at all.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        with engine.connect() as connection:
            triggers = dict(
                connection.execute(
                    text(
                        "SELECT t.tgname, pg_get_triggerdef(t.oid, true) FROM pg_trigger t "
                        "JOIN pg_class c ON c.oid = t.tgrelid "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE NOT t.tgisinternal AND n.nspname = :schema"
                    ),
                    {"schema": SCHEMA},
                ).all()
            )
        assert set(triggers) == {
            IMMUTABILITY_TRIGGER,
            "a_proposal_cites_at_least_one_span",
            "a_span_link_leaves_its_proposal_cited",
            *REVIEW_TRIGGERS,
            *RELATIONSHIP_TRIGGERS,
            *NATIVE_SOURCE_TRIGGERS,
            *MANAGED_DOCUMENT_TRIGGERS,
            "goodnotes_page_versions_are_immutable",
            "goodnotes_region_proposals_are_immutable",
        }
        for name in ("a_proposal_cites_at_least_one_span", "a_span_link_leaves_its_proposal_cited"):
            assert "CONSTRAINT TRIGGER" in triggers[name]
            assert "DEFERRABLE INITIALLY DEFERRED" in triggers[name]
        # The control: the immutability trigger is not deferred, so the two
        # assertions above are about these triggers rather than about every
        # trigger the schema carries.
        assert "DEFERRABLE" not in triggers[IMMUTABILITY_TRIGGER]

        command.downgrade(_config(), "base")

        with engine.connect() as connection:
            relations = set(
                connection.execute(
                    text(
                        "SELECT n.nspname || '.' || c.relname FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "WHERE n.nspname NOT LIKE 'pg\\_%' "
                        "AND n.nspname <> 'information_schema' "
                        "AND c.relkind IN ('r', 'v', 'm', 'p', 'f', 'S')"
                    )
                ).scalars()
            )
            routines = set(
                connection.execute(
                    text(
                        "SELECT n.nspname || '.' || p.proname FROM pg_proc p "
                        "JOIN pg_namespace n ON n.oid = p.pronamespace "
                        "WHERE n.nspname NOT LIKE 'pg\\_%' "
                        "AND n.nspname <> 'information_schema'"
                    )
                ).scalars()
            )
        assert relations == {"public.alembic_version"}
        assert routines == set()
    finally:
        engine.dispose()
